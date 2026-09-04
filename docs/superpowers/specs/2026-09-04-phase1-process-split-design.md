# Phase 1 — Process Split (Still Python)

**Date:** 2026-09-04
**Status:** Draft
**Parent:** *Relay Extraction Route* (route page, artifact `45f88f7b-d29f-4801-b0ad-135185186ef2`,
revised 2026-09-03) and *Splitting the Planes* (extraction proposal, artifact `149fb554`), which the
route page revises after Phase 0 landed.
**Predecessor:** `docs/superpowers/specs/2026-09-03-phase0-harden-in-place-design.md` (Phase 0,
done). Its § Carried, not fixed table is lifted into this spec's § Requirements the relay meets or
carries.
**Verified at:** `main` `9bcaaf10`. Line numbers drift; symbol and setting names are the durable
half of every citation.

## Goal

Move the streaming relay out of the process that serves the API, without moving any relay
internals and without rewriting a line of `apps/proxy/live_proxy/`, `vod_proxy/` or
`apps/timeshift/`'s streaming path. The route page defines Phase 1 as five steps and states they
change no relay internals; this spec delivers all five, because the route page and `CLAUDE.md`
both say stopping earlier is not this spec's outcome (`CLAUDE.md` § Repository and direction names
"1 extract the boundary, still Python" as one phase, not five options):

1. **Process split** — two uWSGI processes behind one nginx, a real process supervisor, and a
   `DISPATCHARR_ROLE` switch, in both the AIO and modular deployment shapes.
2. **Authorize hop** — one function Django calls once per tune, reached by nginx `auth_request`
   with an inline fallback; the relay never resolves a user or queries PostgreSQL to authorize.
3. **Next-source and events** — the relay asks Django for its next stream at failover instead of
   picking one itself, and posts its transitions as events instead of writing them only to Redis.
4. **Status and control API** — every control-plane site that reads or writes a *relay-owned*
   Redis key directly becomes an HTTP call through one client module; the relay's own keys become
   private. Keys Django writes and owns — the provider-slot counters, the timeshift and VOD
   connection sets — stay in Redis by design and are not part of that move.
5. **Tune-path tests and lifted constraints** — the two properties the acceptance suite does not
   yet check (time to first byte through nginx, tuning while Django is down), and Phase 0's carried
   constraints reworded as requirements this design must meet.

Two legitimate stopping points exist inside this plan: after PR 4 (a request timeout and worker
recycling for the API, at the cost of no code change to the relay) and after PR 7 (the relay's
state is private and Phase 3 — video off Redis — becomes a relay-only change). Both are named in
§ The eight pull requests.

Not this spec: a Go relay (Phase 2), removing Redis from the video path (Phase 3), HLS output
(Phase 4), or any of the native-app or remote-access-hardening work the route page's § B discusses.
See § Non-goals.

## What the code says that the route did not

The route page states it was checked against `main` at `75a68555`; three research passes plus this
spec's own verification against `9bcaaf10` found it under-counted in several places. Where the tree
and a prior document disagree, the tree wins; each disagreement below names the winner and the
command that settled it.

- **ORM reads inside `apps/proxy/`: 39 `.objects.` sites across 9 files.** Not "~15 read sites
  inside the relay" (route page), not "reads of 14 model classes" (`CLAUDE.md` § Structural
  constraints — a class count, not a site count, and it is the route page that says fifteen sites in
  seven files), and not the 42-in-12 that `research-coupling.md §3` reported. Verified here with
  `grep -rn "\.objects\." apps/proxy/` excluding `tests/`: 39 hits in
  `live_proxy/{channel_status,server,url_utils,views}.py`,
  `live_proxy/services/channel_service.py`, `live_proxy/input/manager.py`,
  `live_proxy/output/{fmp4,ts}/generator.py`, `vod_proxy/views.py`. The research file's extra three
  files (`apps/proxy/config.py`, `apps/proxy/utils.py`,
  `vod_proxy/multi_worker_connection_manager.py`) contain no `.objects.` query at all —
  `config.py` reads settings through `CoreSettings.get_proxy_settings()` (a classmethod, not a
  queryset) and the other two only import model modules. Use 39/9.
- **The relay is not zero-ORM-write.** `apps/proxy/live_proxy/services/channel_service.py:869`
  runs `stream.save(update_fields=['stream_stats', 'stream_stats_updated_at'])` inside
  `_update_stream_stats_in_db`, called from three hot-path sites: `input/manager.py:1104` (periodic
  bitrate flush), `input/manager.py:1407` (final flush on stop), `channel_service.py:775`
  (synchronous, on every parsed codec line). It is the only `.save(`/`.create(` in non-test
  `apps/proxy/`. `CLAUDE.md`'s "exactly one ORM write" is right about the count and wrong about the
  call being harmless; the route page's "the relay writes nothing to the database" is wrong
  outright. PR 6 is what makes the claim true.
- **`log_system_event` is a second ORM write the zero-writes claim never counted.**
  `core/utils.py:871` writes a `SystemEvent` row, and the relay calls it at **13 sites**:
  `live_proxy/server.py:796` (`channel_start`), `:1563` (`channel_stop`);
  `live_proxy/input/manager.py:483` (`channel_reconnect`), `:540` and `:570` (`channel_error`),
  `:1152` (`channel_failover`), `:1171` (`channel_buffering`), `:1497` (`stream_switch`), `:1629`
  (`channel_reconnect`); `live_proxy/output/fmp4/generator.py:108` (`client_connect`);
  `live_proxy/output/ts/generator.py:128` (`client_connect`), `:642` (`client_disconnect`);
  `vod_proxy/multi_worker_connection_manager.py:902` (`vod_start`/`vod_stop`). PR 6 replaces all
  thirteen with the events client.
- **`channel_stream:{id}` and `stream_profile:{stream_id}` are split-brain.** Both keys are read
  *and written* by `apps/channels/models.py` (`Channel.get_stream`/`release_stream`, lines 692-995)
  and independently read and written by `apps/proxy/live_proxy/`, and read by `core/utils.py:778`
  and `:811` inside `log_system_event`'s enrichment. Neither is in `RedisKeys`
  (`apps/proxy/live_proxy/redis_keys.py`) — both are hand-rolled f-strings on both sides. PR 6
  gives Django sole ownership.
- **Django sites touching relay Redis keys: ~40 direct, not "about thirty"** (route page). ~32 in
  `apps/channels/models.py` alone, 1 in `apps/channels/tasks.py` (`:2377`, reading
  `RedisKeys.channel_metadata` after `run_recording`), 4 in `apps/channels/api_views.py`, 2 in
  `core/utils.py`, 1 in `core/tasks.py` (`fetch_channel_stats`, `:424`).
- **Channel preemption's `return` is commented out, verified in place**: `apps/channels/models.py`
  line 804 reads `# return self.id, profile.id, victim_channel_id`, immediately after the
  `_pick_channel_to_preempt` call at `:796`. The function (`:476`) still runs its full Redis scan
  and scoring for a result nothing consumes. PR 7 deletes it.
- **The channel-stopping key race is 3-at-60s / 3-at-30s inside `live_proxy` itself**, not
  "5@60s/3@30s" (`CLAUDE.md` § Known defects). `setex(..., 60, ...)`: `channel_service.py:44`,
  `input/manager.py:694`, `server.py:1782`. `setex(..., 30, ...)`: `server.py:383`, `server.py:525`,
  `channel_service.py:633`. Carried, not fixed — see § Requirements.
- **`channel_buffering` is a real event the relay fires and Connect cannot see**:
  `input/manager.py:1171` calls `log_system_event('channel_buffering', ...)`, but
  `apps/connect/models.py`'s `SUPPORTED_EVENTS` (17 entries, verified by full read) does not list
  it. PR 6 adds it.
- **`stream_switch`, `channel_failover` and `client_disconnect` already exist as events**, fired
  from inside the relay (`input/manager.py:1497`, `:1152`; `output/ts/generator.py:642`). What is
  missing is a WebSocket push — `channel_stats` is the only WS type the relay emits
  (`live_proxy/views.py:967`). The route page's step-3 panel implies these events do not exist yet.
- **`ffmpeg_speed` and `state` type/default mismatches, verified at their real lines**:
  `channel_status.py:351` emits `ffmpeg_speed` as a string (detailed info, `get_detailed_channel_
  info` at `:25`) vs `:559` as a `float` (basic info, `get_basic_channel_info` at `:390`); `:41`
  defaults `state` to the string `'unknown'` vs `:420` leaving it `None`. PR 7's serializer fixes
  both.
- **Both bash lifecycle suites gate container readiness on a log line the entrypoint prints and
  supervisord will not.** `wait_for_ready()` matches the literal `uwsgi started with PID`
  (`docker/tests/test-puid-pgid.sh:171`, `docker/tests/test-tls-postgres.sh:146`), and each suite
  greps the same string a second time in its log-classification helper (`test-puid-pgid.sh:291`,
  `test-tls-postgres.sh:249`). The string is produced once, at `docker/entrypoint.sh:360`, by the
  line PR 3 deletes. **All four sites break in PR 3 unless PR 3 changes them**; this is the single
  largest correctness risk in the whole sequence and is not mentioned in the route page, the brief
  or the research files. See PR 3.
- **`test-tls-postgres.sh` asserts two strings that only `docker/entrypoint.celery.sh` prints**:
  `log_matches "$celery_name" "starting Celery"` (`:946`) and
  `check_log_contains "$celery_name" "Migrations complete"` (`:955`), both from
  `entrypoint.celery.sh:61`, driven by the `--entrypoint` override at `:923`. Deleting that file
  (PR 3) breaks the `test_modular_full_tls_celery` scenario at three lines, not one.
- **`test_readonly_rootfs` does not currently pass — it skips**, and a startup failure inside it
  cannot fail the suite: `docker/tests/test-puid-pgid.sh:1447-1449` classifies any log matching
  `read-only file system|No such file or directory` as `log_skip`, and `e2e/README.md:780-783`
  records the current suite result as "135 passed / 0 failed / 1 skipped (`readonly_rootfs`, which
  needs more tmpfs mounts and is expected)". "`test_readonly_rootfs` still passes" is therefore not
  a usable done criterion for PR 3. See PR 3 for what replaces it.
- **The greybox Redis quarantine file named in `CLAUDE.md` § Testing no longer exists.**
  `e2e/tests/streaming-greybox/quarantine.spec.ts` was replaced by
  `e2e/tests/guards/allowlist.ts` + `capabilities.spec.ts` (four capabilities:
  `GREYBOX_REDIS`, `CONTAINER_LIFECYCLE`, `SUBPROCESS`, `CONTAINER_INTROSPECTION`, plus
  `GLOBAL_SETTINGS_WRITE`), still enforcing the same principle. `e2e/README.md:104` and `:111`
  still name the deleted file; `e2e/README.md:780` still says `Lifecycle result` is not in the Main
  ruleset, which the live ruleset contradicts. PR 2 fixes all three lines.
- **E2E has 13 Playwright projects, not "five" (`CLAUDE.md` § Testing) or "seven."**
  `bootstrap`, `guards`, `pristine`, `seeded`, `streaming`, `streaming-failover`,
  `streaming-greybox`, `frontend`, `dvr`, `lifecycle`, `lifecycle-upgrade`, `lifecycle-restore`,
  `lifecycle-scheduling`.
- **The fake provider has twelve injectable faults, not "eight."** `e2e-upstream/src/faults.ts:4-16`.
- **Issue #87 carries a `wontfix` label applied in error.** The issue is open and describes a live
  defect (`stream_xc` omits the `is_adult`/`hidden_from_output` filters every listing path applies);
  the triage workflow closed it as "a duplicate of open issue #87" — a self-duplication. PR 5 must
  remove the `wontfix` label before closing the issue on the fix, or the closure reads as a
  reversal of a considered decision. Issue #95 (catch-up, `ready-for-agent`) is correctly labelled.
- **The copy-pasted channel-authorization filter appears at 12 sites, not eight.** `CLAUDE.md`
  § Known defects says eight; the verified set is `live_proxy/views.py:809`, `output/epg.py:1150`
  and `:1169`, `timeshift/views.py:782`, `output/views.py:154,174,592,636,819`,
  `hdhr/api_views.py:144`, `channels/api_views.py:1017` and `:3351`. PR 5 deletes the two on the
  streaming path (`live_proxy/views.py`, `timeshift/views.py`) by folding them into
  `authorize_stream`; the other ten are listing paths this spec does not touch, so the corrected
  count in `CLAUDE.md` becomes ten, not zero.
- **`docs/agents/issue-tracker.md`** names the `resolveReviewThread` mutation but carries no
  runnable example. PR 8 adds one.
- **Nginx `location` matching creates live collisions with the XC three-segment root form.** New
  information this spec contributes; see § Architecture, "The three-segment regex trap."

## Verified facts this design rests on

**Entrypoint and supervision today.** `docker/entrypoint.sh` (396 lines) runs as root, does
one-shot setup (PUID/PGID, PG init or wait, external-Redis wait in modular only at `:290-295`,
migrate and collectstatic at `:329-330`, nginx port `sed`), starts nginx (`:307-312`, skipped in
`dev`), then launches uWSGI as a single backgrounded `su -` wrapper (`:359`) whose PID is the only
one of five real daemons tracked in the `pids[]` array — Redis, both Celery queues, Celery beat and
Daphne are uWSGI `attach-daemon`s. `trap cleanup TERM INT` (`:61`) does `pkill -TERM` by process
name, an 8-second wait loop (`_shutdown_timeout=8`, `:37`), then `pkill -KILL`, then
`pg_ctl stop -m immediate` for Postgres (`:53`). No drain logic exists for an in-flight `/proxy/`
stream. `docker/entrypoint.aio.sh` is dead code (gunicorn/pm2, zero references).
`docker/entrypoint.celery.sh` is live: used by `docker/docker-compose.yml`'s `celery` service
(`:123`) and by `docker/tests/test-tls-postgres.sh:923`; it waits on `/data/jwt` (`:16-24`) and
`manage.py migrate --check` (`:49-58`), then runs beat plus two workers.

**Environment reaches uWSGI through a generated profile script, not the process environment.**
`docker/entrypoint.sh:177-184` lists every variable it propagates and writes them to
`/etc/profile.d/dispatcharr.sh`, which the `su -` login shell sources. A new env var that is not
added to that `variables=()` array is invisible to uWSGI. Under supervisord this indirection stops
being load-bearing — supervisord's children inherit supervisord's own environment, and supervisord
is `exec`'d by the entrypoint — but the file stays for interactive `docker exec` and for the
Postgres helpers that still use `su -`. Both facts are needed by PR 3 and PR 4.

**uWSGI ini selection and content.** `entrypoint.sh:332-345` picks the ini by
`DISPATCHARR_ENV`/`DISPATCHARR_DEBUG`. `docker/uwsgi.ini` and `docker/uwsgi.modular.ini` are
byte-identical except the daemon block. Both carry, verified in full: `socket = /app/uwsgi.sock`,
`chmod-socket = 777`, `http = 0.0.0.0:5656`, `http-keepalive = 1`, `workers = 4`, `gevent = 400`,
`gevent-early-monkey-patch = true`, `import = dispatcharr.gevent_patch`, `master = true`,
`module = dispatcharr.wsgi:application`, `virtualenv = /dispatcharrpy`, `chdir = /app`,
`env = DJANGO_SETTINGS_MODULE=...`, `env = USE_NGINX_ACCEL=true`, `buffer-size = 65536`,
`post-buffering = 4096`, `http-timeout = 600`, `socket-timeout = 600`, `lazy-apps = true`,
`thunder-lock = true`, `vacuum = true`, `die-on-term = true`, `static-map = /static=/app/static`,
and the log block (`log-master`, `logformat-strftime`, `log-date`, `log-format`, `log-buffering`).
**No `harakiri` directive exists in either.** `uwsgi.ini` alone carries
`exec-pre = python /app/scripts/wait_for_redis.py` (`:8`); `uwsgi.dev.ini` carries the same at
`:8`; `uwsgi.debug.ini` carries `attach-daemon`s but no `exec-pre`. **uWSGI expands `$(VAR)` from
the environment, not `${VAR:-default}`** — the file already relies on this at
`$(CELERY_NICE_LEVEL)`, whose default is supplied by `entrypoint.sh`'s `export X=${X:-…}` pattern
(`:100`, `:122`).

**`scripts/wait_for_redis.py` flushes, and both branches are destructive.** `:100-103`:
`DISPATCHARR_ENV == 'modular'` calls `_flush_non_celery_keys`, anything else calls
`redis_client.flushdb()`. `_flush_non_celery_keys` (`:20-35`) scans the whole keyspace and deletes
every key whose name does not start with `celery`, `_kombu` or `unacked` — which is every relay
key, `channel_stream:*`, `stream_profile:*`, `profile_connections:*` and every timeshift and VOD
session key. In AIO this runs from uWSGI's `exec-pre` on **every uWSGI start**, so a second uWSGI
process running it would flush the video ring buffer under the first. **Relay keys do not need it**:
the ownership lease is set with a TTL (`server.py:474`), the channel-stopping key is `setex`, and
the metadata hash gets `REDIS_TTL_DEFAULT` = 3600 s (`server.py:766`, `constants.py:8`), refreshed
only while the channel is alive; `ProxyServer._cleanup_failed_init` (`server.py:937`) handles the
one case TTLs are slow for, an unowned channel stuck in `initializing`, and
`apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py:55-102` pins it. D15 deletes both flush
paths.

**nginx today.** `docker/nginx.conf` (120 lines, verified in full) is one `server` block with, in
file order: `location /` → `uwsgi_pass unix:/app/uwsgi.sock`; `/assets/`, `/static/`, `/logos/`
static; `/protected-backups/` `internal`; four `proxy_cache` **regex** locations
(`^/api/channels/logos/…`, `^/api/vod/vodlogos/…`, `^/api/vod/(movies|series|episodes)/…/image/`,
`^/api/epg/programs/…/poster/`) each `proxy_pass http://127.0.0.1:5656`; the admin **regex**
`^/admin(?!/[^/]+/[^/]+/?$)(?:/|$)` → `return 301 /login`; `location /hdhr`; `location /ws/` →
Daphne; and `location /proxy/` with `uwsgi_buffering off`, `uwsgi_read_timeout 300s`,
`uwsgi_send_timeout 300s`, `client_max_body_size 0` (`:112-119`). Templating is a literal
placeholder plus `sed`: `listen NGINX_PORT;` (`:9-10`) substituted at
`docker/init/03-init-dispatcharr.sh:64`. nginx is 1.24.0 built `--with-http_auth_request_module`
(research-deploy §11), so `auth_request` needs no rebuild. There is **no `/output/` location today**
— `/output/…` falls through to `location /`.

**Routes that move, verified against every `urls.py` in the request path.**
- `apps/proxy/urls.py`: `stats/` (short JSON), `ts/` → `live_proxy.urls`, `catchup/` →
  `apps.timeshift.urls`, `vod/` → `vod_proxy.urls`.
- `live_proxy/urls.py`: `stream/<channel_id>` is the only long-lived route; `change_stream`,
  `status` (**no trailing slash**), `status/<id>`, `stop`, `stop_client`, `next_stream` are short
  and `IsAdmin` (`views.py:837,939,989,1018,1053`).
- `vod_proxy/urls.py`: four `stream_vod` variants (long-lived) plus `stats/` and `stop_client/`,
  both short and both with a trailing slash — which is what makes an nginx `location = ` exact
  exclusion sufficient.
- `apps/timeshift/urls.py`: `stats/`, `programs/`, `stop_client/` (short, trailing slash) and
  `<uuid:channel_id>` → `catchup_proxy` (long-lived), i.e. `/proxy/catchup/<uuid>` is itself a
  three-segment URI with no trailing slash.
- `dispatcharr/urls.py` (81 lines, verified in full): Xtream roots mounted before the SPA
  catch-all. Long-lived: `live/<user>/<pass>/<id>` (4 segments), the bare `<user>/<pass>/<id>`
  (**3 segments**), `timeshift/<user>/<pass>/<duration>/<timestamp>/<id>` (6),
  `streaming/timeshift.php` (2), `movie/<user>/<pass>/<id>.<ext>` (4),
  `series/<user>/<pass>/<id>.<ext>` (4). Short: `player_api.php`, `panel_api.php`, `get.php`,
  `xmltv.php` — all unanchored `re_path`, none containing a `/`.
- Three-segment, no-trailing-slash URIs the API owns: `/hdhr/<channel_profile>/discover.json`
  (and `lineup.json`, `lineup_status.json`) at `apps/hdhr/urls.py:28-30`, and
  `/output/m3u/<profile_name>` / `/output/epg/<profile_name>` at `apps/output/urls.py:8-9`
  (the trailing slash is optional in both regexes). These are the collisions § Architecture
  addresses.

**Authorization today, verified per view.** `stream_ts` (`live_proxy/views.py:154-157`):
`@permission_classes([AllowAny])`, gated only by `network_access_allowed(request, "STREAMS")` at
`:157` — no user resolution for the bare `/proxy/ts/stream/<uuid>` path. (`research-coupling.md §2`
says `stream_ts` has no `network_access_allowed`; the research is wrong and the line is there.)
`stream_xc` (`:776-831`): resolves `User` by username, `network_access_allowed(..., 'STREAMS',
user)`, plaintext `custom_properties["xc_password"] != password`, then a copy-pasted
`user_level__lte` + `channelprofilemembership__enabled` filter — no `hide_adult_content`.
`stream_vod` (`vod_proxy/views.py:610-613`): `AllowAny` plus `[JWTAuthentication,
ApiKeyAuthentication, QueryParamJWTAuthentication]`, with a Redis session-to-user fallback at
`:776`. `_user_can_access_channel` (`apps/timeshift/views.py:771-786`) is the one extracted helper;
the same filter is copy-pasted at **12** sites. `network_access_allowed`
(`dispatcharr/utils.py:388-428`): CIDR allowlist from `CoreSettings`, default `0.0.0.0/0` + `::/0`
for every key except `M3U_EPG`. `_resolve_output_profile` (`live_proxy/views.py:135-151`) reads
`?output_profile=` then the user's `custom_properties['output_profile']`. `client_id` is minted in
the view at `:179` when the request does not carry one.

**The two channel flags, and the admin bypass.** The model fields are `Channel.hidden_from_output`
(`apps/channels/models.py:393`) and `Channel.is_adult` (`:359`; `Stream.is_adult` is a separate
field at `:105`). **There is no field named `hidden`** — `hide_adult_content` is the *user*
preference read against `is_adult`. `_user_can_access_channel` (`apps/timeshift/views.py:771-786`)
denies on `user.user_level < channel.user_level`, then **returns `True` for
`user_level >= User.UserLevel.ADMIN`** (`:774`), then returns `True` when the user has no channel
profiles at all, and otherwise applies the membership filter. Both bypasses are load-bearing for
the authorize matrix.

**`/proxy/ts/stream/<id>` serves two different things.** `get_stream_object`
(`live_proxy/url_utils.py:50-58`) tries `Channel` by `uuid` and, on failure, `Stream` by
`stream_hash`; `server.py:2373` and both generators' cleanup paths do the same fallback. The admin
UI drives both: `ChannelsTable.jsx:653,665` play a channel UUID, and `ChannelTableStreams.jsx:404`
and `StreamsTable.jsx:954` play a raw `stream_hash` for single-stream preview. Both go through
`buildLiveStreamUrl` (`frontend/src/utils/components/FloatingVideoUtils.js:8`), which adds no
credential — the JWT reaches the server as an `Authorization` header set on the mpegts.js player
config (`FloatingVideo.jsx:492-494`), so the admin preview *is* an authenticated request and the
matrix's admin row decides whether it keeps working.

**Boot-order facts PR 3 turns on.** `entrypoint.sh:253-258` starts Postgres with
`pg_ctl start -w -t 300` and then polls `pg_isready`, before `migrate` and `collectstatic` at
`:329-330`; AIO Redis does not exist until uWSGI's `attach-daemon` starts it, which is after the
entrypoint finishes. `scripts/wait_for_redis.py:75` defaults to 30 retries at 2-second intervals
and returns `False` after 60 seconds. `docker/init/03-init-dispatcharr.sh` is sourced
unconditionally at `entrypoint.sh:250` and does both nginx edits — the `NGINX_PORT` `sed` at `:64`
and the IPv6 `listen` strip at `:67-72` — alongside `/app` and data-dir ownership work that every
role needs, so a role gate has to sit inside the script, not at the call site. The lifecycle image
tarball already contains the fake provider: `lifecycle-tests.yml:196` builds
`dispatcharr-e2e-upstream:local` and `:204` saves it beside `dispatcharr-e2e:local`, though
`test-puid-pgid.sh` references neither today. `scripts/e2e_up.sh:110-111`'s `--stop` is a plain
`docker stop` followed by `docker rm -f`, so it inherits Docker's 10-second grace period.

**`check_user_stream_limits` spans three surfaces with two different owners.**
`apps/proxy/utils.py:304` → `get_user_active_connections` (`:232`) `scan_iter`s
`live:channel:*:clients:*` — relay-owned, and the family Phase 3 moves out of Redis —
alongside `timeshift:channel:*:clients:*` and `vod_persistent_connection:*`, which Django-side
handlers write and keep; on a breach it calls
`attempt_stream_termination` (`:144`), which calls `ChannelService.stop_client` (`:193`). Its three
callers today are `live_proxy/views.py:193`, `vod_proxy/views.py:781` and
`apps/timeshift/views.py:493` — all three inside stream views that move to the relay, and all three
replaced by the authorize hop in PR 5.

**`ChannelService` is called from inside the relay, 25 times.** `apps/proxy/utils.py:193`;
`live_proxy/client_manager.py:248,291`; `live_proxy/server.py:276,1216,1221,1226,1590,1972`;
`live_proxy/views.py:199,233,249,260,505,515,642,877,995,1029,1155`;
`live_proxy/input/manager.py:1031,1034,1104,1407,1933`; `live_proxy/output/ts/generator.py:153`.
Django-side callers are only six, in four files: `apps/m3u/tasks.py:62` and
`apps/m3u/api_views.py:295` (`stop_channels`), `apps/channels/api_views.py:105` (`stop_channels`),
`:3249` and `:3816` (`stop_client`), `:3831` (`stop_channel`). `ChannelService.stop_client`
(`channel_service.py:613-676`) already works cross-process: it `setex`es a stop key and publishes
`live:events:` when the client is not local.

**`Channel.get_stream()` and the slot counter (`apps/channels/models.py:692-831`).** Reuse path
returns the cached assignment with no re-reservation; fresh path iterates
`self.streams.all().order_by("channelstream__order")`, calls `reserve_profile_slot`
(`apps/m3u/connection_pool.py:280-313`, atomic `INCR`-first with rollback) and writes
`channel_stream:{id}` / `stream_profile:{stream.id}` with a plain `SET`, no TTL. Callers inside the
relay: `url_utils.py:82,116` (tune), `:284` (failover), `channel_service.py:159`
(`cancel_pending_shutdown`). `profile_connections:{id}` is the same key VOD
(`vod_proxy/views.py:542,544,566,568`) and catch-up (`apps/timeshift/views.py:679,1672,1680,2140,
2364,2428`) reserve against — one counter, three consumers.

**Process-local cache (`apps/proxy/config.py:20-45`).** `BaseConfig._proxy_settings_cache` is a
class attribute with a 10-second TTL, i.e. one copy per OS process. A single relay process
(`workers = 1`) is internally consistent by construction. `clear_proxy_settings_cache()` is called
only from `core/models.py`'s `CoreSettings.invalidate_group_cache` signal, so a Django-side save
clears only the writing process; the relay stays up to 10s stale. Unchanged by this spec.

**Address-from-variable precedent (`apps/channels/tasks.py:1306-1329`).**
`get_dvr_stream_base_url()`: explicit override `DISPATCHARR_INTERNAL_TS_BASE_URL` → modular
`http://{DISPATCHARR_WEB_HOST:-web}:{DISPATCHARR_PORT:-9191}` → AIO/dev/debug
`http://127.0.0.1:5656`. Its single call site is `tasks.py:1582`; the URL is built at `:1640` and
handed to ffmpeg by `_dvr_build_ffmpeg_cmd` (`:1203-1229`), which today passes `-user_agent` and
**no `-headers`**. `apps/channels/tests/test_dvr_port_resolution.py` has 8 tests, 4 of which assert
`5656`.

**nginx `location` matching order** (primary docs, `ngx_http_core_module` — "Matching types and
priority"): an exact (`=`) match wins outright; otherwise nginx finds the longest matching *prefix*
location, and **if that prefix carries `^~` it is used immediately without checking regexes**;
otherwise every regex location is tested in file order and the first match wins over the prefix.
Corollaries this design depends on: `=` and `^~` are mutually exclusive on one location, and
**`^~` on `/` disables every regex in the file**, because `/` is the longest matching prefix for
any URI no other prefix claims.

**nginx header handling under `uwsgi_pass`** (primary docs, `ngx_http_uwsgi_module`):
`uwsgi_pass_request_headers` defaults to `on`, so every client header reaches the app as
`HTTP_*` — that is how Django sees `Host` today. Since nginx 0.8.40 (CHANGES-1.8, documented for
`fastcgi_param` and shared by the uwsgi module) **a `*_param` whose name begins with `HTTP_`
overrides the client's same-named header**. `uwsgi_param` is an array directive: a location that
declares any `uwsgi_param` of its own inherits none from the enclosing level, which is why
`include uwsgi_params;` is repeated in every location in the file today.

**nginx `auth_request`** (primary docs, `ngx_http_auth_request_module`): 2xx allows, 401/403 deny
and are returned to the client, anything else is a server error nginx reports itself.
`auth_request_set` assigns after the subrequest completes and "may contain variables from the
authorization request, such as `$upstream_http_*`" — that is the **only** context in which the
subrequest's response headers are readable. In the main request `$upstream_http_x_relay_name` is
unset.

**nginx pass-address variables** (primary docs, `ngx_http_proxy_module` / `ngx_http_fastcgi_module`
`*_pass`): when the address contains variables, nginx first searches the defined server groups and
otherwise resolves the name with `resolver`. A bare `relay:5657` in a variable therefore fails with
"no resolver defined" in the modular shape unless an `upstream` block declares it.

**supervisord semantics** (primary docs, `supervisord.org/configuration.html`). `user=` on a
`[program:x]` takes effect only when supervisord runs as root — which matches the entrypoint's
current root-then-`su -` shape. `priority=` orders start ascending and shutdown in reverse;
`stopsignal=` takes a signal *name*; `stopwaitsecs=` is per program. `%(ENV_X)s` expands
environment variables in configuration options. The `[include]` section's `files` value is
documented as evaluated "against a dictionary that includes `host_node_name` and `here`", but the
4.3.0 source is broader than its reference: `supervisor/options.py:578-588` builds that dictionary
from `here` and `host_node_name` and then calls `expansions.update(self.environ_expansions)`
before expanding `files`, so `%(ENV_X)s` **does** work there. **The design still uses six separate
conf files selected with `-c`**, not one file with a variable in its glob — not because the
expansion is unavailable, but because the selector is role × env × debug and no single environment
variable names that. The entrypoint already resolves the same three inputs in bash to pick a uWSGI
ini (`:332-345`); doing it once more is cheaper to read than encoding a ladder in a glob.
`[supervisord] logfile`, `pidfile` and
`childlogdir` default to the current directory and the system temp dir and must be set explicitly
under a writable path. With `nodaemon` true and `silent` false (the defaults for `supervisord -n`)
the activity log is **echoed to stdout**, which is what keeps `docker logs` useful. **`%` is the
expansion character in supervisord config**, so a `command=` containing Celery's `-n default@%h`
must write `%%h`, the same escaping `docker/uwsgi.ini:13` already uses.

**Compose files, verified in full.** `docker/docker-compose.yml` (modular): `web` (port 9191,
`DISPATCHARR_ENV=modular`, `./data:/data`), `celery` (`entrypoint.celery.sh`, `./data:/data`, no
ports, `depends_on: web: service_started`, `DISPATCHARR_WEB_HOST` documented but commented out at
`:136`), `db` (`postgres:17`, **`5436:5432` published on all interfaces**, `:191`), `redis` (no
ports). `docker/docker-compose.aio.yml`: one service, port 9191, `DISPATCHARR_ENV=aio`.
Neither file has a `relay` service or a `DISPATCHARR_ROLE` variable. Neither sets
`stop_grace_period`, so Docker's 10-second default applies.

**E2E harness reach (`scripts/e2e_up.sh:247-253`).** A plain `docker run` with
`-e DISPATCHARR_ENV=aio` and `-p 127.0.0.1:${PORT}:9191`; uWSGI's `http = 0.0.0.0:5656` is never
published. Every Playwright test already goes through nginx, so the TTFB test needs no new port
mapping — and `e2e_up.sh` stays AIO-only in this spec, which is why the cross-container role-split
scenario lives in `docker/tests/test-puid-pgid.sh` beside `test_modular_mode` (`:980-1046`), not in
a Playwright project.

**CI facts each PR's done criteria rely on.** `backend-tests.yml` runs one matrix job per label;
`dispatcharr/test_discovery.py`'s `_PATH_ALIASES` routes `apps/api/` to `__all__` (so any change to
`apps/api/urls.py` runs all 16 labels) and `apps/proxy/live_proxy/` to both
`apps.proxy.live_proxy.tests` and `apps.channels.tests`; `_SHARED_PATH_PREFIXES` includes
`pyproject.toml`, so PR 1 runs the full backend set. `lifecycle-tests.yml:231` gates the two bash
suites on `github.event_name != 'pull_request' || needs.changes.outputs.full == 'true'`, and
`:119-124` sets `full=true` for a `migration/*` branch — so every code PR here runs them.
`docker-build.yml` triggers **only on push to `main`** and is therefore never a PR check.
The Main ruleset requires `E2E result`, `Lifecycle result`, `Backend result`, `Frontend result`,
`agent` and `safe_outputs`.

## Decisions

| # | Decision | Why |
|---|---|---|
| **D1** | **Same image, same Django settings, same urlconf in both processes; only the nginx location table and the uWSGI ini differ.** Role-scoped urlconfs are Phase 2+ hardening. | A misrouted request is served correctly by the wrong process, never 404 — the split degrades gracefully under any nginx-config mistake. Building two urlconfs now is the scope-widening `CLAUDE.md` names as the main failure mode. |
| **D2** | **supervisord**, added to `pyproject.toml`/`uv.lock` in its own PR (PR 1), replaces the bash `pkill`-based `trap cleanup` in **every** `DISPATCHARR_ENV`, including `dev` and `debug`. Not s6, not uWSGI `attach-daemon`. | The venv is built once in `docker/DispatcharrBase` with `--no-dev --locked`, and `base-image.yml` rebuilds `:base` only on `main`, so a PR that both adds the dependency and execs it fails its own image build. Covering `dev`/`debug` too costs one extra program file per mode and avoids the outcome the route page warns about most: two supervision shapes that drift. The one casualty is `uwsgi.debug.ini:72`'s `honour-stdin = true`, which PR 3 removes: supervisord gives a child no controlling TTY, so uWSGI would hold a stdin that is never a terminal. Nothing is lost — debugpy attaches over TCP :5678 (`docker-compose.debug.yml`), never over stdin; the flag exists for an interactive `pdb`, which was already unreachable through `docker logs`. Landing the dependency alone is necessary but not sufficient for CI to ever exercise it: `e2e-tests.yml`, `lifecycle-tests.yml` and `scripts/e2e_up.sh` build `docker/Dockerfile` with no `REPO_OWNER` build-arg, which defaults to upstream (`ghcr.io/dispatcharr/dispatcharr:base`) rather than this fork's rebuilt `:base` — fixed in this same PR, discovered verifying PR 1's own done criteria rather than anticipated when this decision was written. |
| **D3** | **`DISPATCHARR_ROLE` ∈ {`all`, `api`, `relay`, `worker`}**, orthogonal to `DISPATCHARR_ENV` ∈ {`aio`, `modular`, `dev`}. AIO defaults to `all`; the modular compose file's `web`/`relay`/`celery` services set `api`/`relay`/`worker`. | `DISPATCHARR_ENV` answers "where do Postgres and Redis run"; `DISPATCHARR_ROLE` answers "which programs does supervisord start in *this* container". Conflating them would need a third value nothing else reads. |
| **D4** | **Every long-lived response surface moves to the relay in one PR (PR 4)**, not just live TS: VOD, catch-up and all six XC streaming root forms together. | If VOD or catch-up stay on the API process, `harakiri = 120` kills a two-hour movie at two minutes and the timeout the split exists to enable never applies. The route page calls this "free in step 1"; it is the point of step 1, not scope creep. |
| **D5** | **The relay's uWSGI has exactly one listener, `socket = 0.0.0.0:5657` (uwsgi protocol). No `http =` listener.** | The relay's byte path (PR 4) and its control API (PR 7, `/proxy/relay/…`) are both plain Django views reached through nginx `uwsgi_pass` — the directive family `CLAUDE.md` records as load-bearing for `uwsgi_buffering off`. D9 routes Django's control calls through nginx as well, so nothing ever dials a raw HTTP port on the relay. This diverges from the brief's tentative "add `http = 127.0.0.1:5658`". |
| **D6** | **`get_dvr_stream_base_url()`'s AIO/dev/debug branch changes from `http://127.0.0.1:5656` to `http://127.0.0.1:{DISPATCHARR_PORT:-9191}`** (nginx); the modular and explicit-override branches are unchanged. | The DVR fetches `/proxy/ts/stream/<uuid>` exactly like a player. Once PR 5 puts that route behind the authorize hop, a recording that bypasses nginx bypasses authorization. `apps/channels/tests/test_dvr_port_resolution.py`'s four `5656` assertions change in the same PR. |
| **D7** | **`^~` goes on every specific non-root prefix location, never on `/`.** The four `proxy_cache` regexes move inside a new `location ^~ /api/ { … }`; the admin regex stays ahead of the XC regex; exact (`=`) locations carry no `^~`. | `^~` on `/` would disable every regex in the file, including the XC three-segment regex the change exists to add, the admin→`/login` redirect and all four image caches — `/` is the longest matching prefix for any URI no other prefix claims. Nesting the cache regexes inside `^~ /api/` keeps them reachable while `^~` protects `/api/`. SPA deep links that happen to be three segments with no trailing slash still fall to the XC regex and are served correctly by the relay (D1); PR 2's test pins that. |
| **D8** | **`authorize_stream(request, surface, ...)` lives at `apps/proxy/authorize.py`, no new Django app.** Two callers: nginx `auth_request` (production) and an inline call from the stream views when the nginx marker is absent (dev `runserver`). | `apps/proxy/` already has a discovered test label (`apps.proxy.tests`), so a new module there is covered by CI routing on day one; a new app with no `tests/` dir selects zero backend tests silently. One function behind two callers makes "same gate everywhere" a property of the code. |
| **D9** | **One internal base-URL resolver, shared by both directions.** `get_relay_control_base_url()` (Django→relay) and `get_control_plane_base_url()` (relay→Django) are two thin wrappers over one function using the DVR formula: explicit override (`DISPATCHARR_RELAY_BASE_URL` and `DISPATCHARR_INTERNAL_API_BASE_URL` respectively) → modular `http://{HOST}:{DISPATCHARR_PORT:-9191}` → AIO `http://127.0.0.1:{DISPATCHARR_PORT:-9191}`, with `HOST` being `DISPATCHARR_RELAY_HOST` (default `relay`) or `DISPATCHARR_WEB_HOST` (default `web`) respectively. **`/proxy/relay/` is gated by the internal token alone, with no source-IP allowlist.** | Two of the four roles have no local nginx to loop back to. The `worker` role runs `core/tasks.py:424 fetch_channel_stats`, `apps/m3u/tasks.py:62 ChannelService.stop_channels` and `apps/channels/tasks.py:2377`, and in modular it must reach the relay across the compose network; a loopback address would be connection-refused and `allow 127.0.0.1; deny all;` would reject its source address anyway. A source-IP allowlist does not survive a compose network, so the token is the whole gate. This replaces the earlier draft's "always the caller's local nginx" and the brief's Django-side `RELAYS` dict. |
| **D10** | **Nothing under `apps/proxy/live_proxy/`, `apps/proxy/vod_proxy/` or `apps/timeshift/`'s streaming path imports `relay_client`.** The in-relay `ChannelService` static methods are untouched; only the six Django-side call sites move. | `ChannelService` statics are called 25 times *inside* the relay. Reimplementing them on `relay_client` would make the relay call itself over HTTP through an nginx it does not run, and would rewrite relay internals — the one thing this phase forbids. The facade splits by caller, not by symbol. |
| **D11** | **Two HMACs of `SECRET_KEY`, both compared with `hmac.compare_digest`, are the only auth on every internal surface.** `X-Dispatcharr-Internal` = `HMAC(SECRET_KEY, "internal-principal")` gates `/api/relay/…` (relay→Django), `/proxy/relay/…` (Django→relay) and the DVR's stream fetch. `X-Dispatcharr-Authorized` = `HMAC(SECRET_KEY, "relay-trust")` is the marker nginx sets so the relay will trust the `X-Relay-*` headers. Neither surface is `IsAdmin`. | Both processes share `SECRET_KEY` — but only because `docker/entrypoint.sh:103-117` generates `/data/jwt` once and every role reads the same file from the same `/data` volume. That is a deployment fact, not a settings fact, and PR 4's `relay` service must mount `./data:/data` or it generates its own key and every internal call 403s. `IsAdmin` requires a resolved `User`, which is exactly what this hop must not need. Two context strings rather than one so a marker leaked through the nginx config cannot be replayed as an internal principal — and the marker is a secret at all because uWSGI's `http = 0.0.0.0:5656` is published in `dev`/`debug` and the relay's `:5657` is reachable across a compose network, so "only nginx can reach the relay" is not a property this design may assume. |
| **D12** | **`apps/proxy/api_urls.py` (new) is mounted in `apps/api/urls.py` as `path('relay/', include(('apps.proxy.api_urls', 'relay'), namespace='relay'))` → `/api/relay/…`.** `apps/proxy/relay_urls.py` (new) is mounted in `apps/proxy/urls.py` as `path('relay/', include('apps.proxy.relay_urls'))` → `/proxy/relay/…`. | Matches `CLAUDE.md` § Conventions ("routes in the app's `api_urls.py`"); both files land inside `apps/proxy/`, covered by the existing `apps.proxy.tests` label. Note the CI cost: touching `apps/api/urls.py` is aliased to `__all__`, so PR 6 runs all 16 backend labels. |
| **D13** | **`Channel.get_stream()` and `release_stream()` keep their signature and Redis-key ownership.** PR 6 adds an HTTP wrapper the relay calls instead of calling `get_stream()` directly; Django still runs the ORM query and the `reserve_profile_slot` `INCR`. | The counter is shared with VOD and catch-up, which reserve from Django-side request handlers. A live-only relay cannot own a counter three surfaces share (ADR 0005). |
| **D14** | **The `relay` role runs no nginx.** Its health is observed through supervisord (`supervisorctl status relay-uwsgi`) and, end to end, through the `api` role's nginx. | The `api`/`all` roles already run nginx in every shape. A second nginx on `relay` would resolve the same `$relay_upstream` map with nothing behind it but itself. |
| **D15** | **Nothing flushes Redis, in any role, ever.** `scripts/wait_for_redis.py` becomes wait-only: both `redis_client.flushdb()` and `_flush_non_celery_keys` are deleted (PR 3), along with the `exec-pre` that ran them and the entrypoint's modular call. In the `all` role supervisord's `[program:redis]` runs `redis-server --save "" --appendonly no`, so AIO Redis starts empty without a flush step. | A flush is destructive to *live* state, not just stale state, and under the split there is no role that can be sure it holds neither. `_flush_non_celery_keys` (`scripts/wait_for_redis.py:20-35`) deletes every key not prefixed `celery`/`_kombu`/`unacked` — the relay's metadata, chunks, client sets and lease, plus `channel_stream:*`, `profile_connections:*` and the timeshift and VOD session keys. Running it in the `api` one-shot would wipe a running relay's channels on every modular `web` start, which is exactly the Django deploy this phase exists to make harmless. **Stale keys need no flush**: the ownership lease is `set(..., ex=ttl)` (`server.py:474`), the channel-stopping key is `setex` at 30 or 60 s, and the metadata hash carries `REDIS_TTL_DEFAULT` = 3600 s refreshed only while the channel lives (`server.py:766`, `constants.py:8`) — so a dead relay's keys expire on their own. What TTLs cannot catch, `ProxyServer._cleanup_failed_init` (`server.py:937`) does: an unowned channel stuck in `initializing` is torn down by the next init, pinned by `CleanupFailedInitTests` in `apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py:55-102`. |
| **D16** | **PR sequence is nine items: PR 0 is this spec's docs-only branch (`docs/phase1-spec`), PRs 1-8 are the code changes on `migration/phase1-*`.** | `migration/**` bypasses the E2E and lifecycle path filters (`lifecycle-tests.yml:119-124`), which every code PR here needs; the docs PR must *not* be on that branch prefix so the heavy jobs skip. |

## Architecture

### Before

One image, one uWSGI process (`workers = 4`, `gevent = 400`), fronted by one nginx `server` block
that sends every request — API, UI, Xtream JSON, HDHR, and every long-lived `/proxy/`/XC stream —
through the same unix socket. No `harakiri` exists in production because the process serving
four-hour streams is the process serving the API. AIO supervision is a bash `pkill` loop with one
tracked PID; every other daemon is a uWSGI `attach-daemon` child. The relay reads PostgreSQL at 39
sites, writes two rows (`stream.save`, `SystemEvent`), and both reads and writes two Redis keys
that `apps/channels/models.py` also reads and writes, with no single owner.

### After

**Two uWSGI processes, one image, one urlconf (D1).**

| | API process | Relay process |
|---|---|---|
| `workers` | 4 | 1 |
| `gevent` | 400 (unchanged) | `$(DISPATCHARR_RELAY_GEVENT)`, default **1600** |
| `harakiri` | `$(DISPATCHARR_API_HARAKIRI)`, default 120, plus `harakiri-verbose = true` | none — long-lived responses live here |
| `max-requests` | `$(DISPATCHARR_API_MAX_REQUESTS)`, default 5000 | none |
| Listener | `socket = /app/uwsgi.sock` + `http = 0.0.0.0:5656` (image-cache `proxy_pass`, unchanged) | `socket = 0.0.0.0:5657` only (D5) — TCP so the modular `relay` container is reachable over the compose network |
| `listen` (accept backlog) | uWSGI default 100 (unchanged) | `listen = 1024` |
| `die-on-term` | `true` (unchanged) | `true` (unchanged) |
| Routes served | `/`, `/api/`, `/hdhr`, `/output/`, `/proxy/stats/`, `/proxy/ts/{change_stream,status,stop,stop_client,next_stream}`, `/proxy/vod/{stats,stop_client}`, `/proxy/catchup/{stats,programs,stop_client}`, `player_api.php`/`panel_api.php`/`get.php`/`xmltv.php`, `admin/`, `/_dispatcharr/authorize` | `/proxy/ts/stream/`, the rest of `/proxy/vod/`, `/proxy/catchup/<uuid>`, `/live/`, `/movie/`, `/series/`, `/timeshift/`, `/streaming/timeshift.php`, the XC 3-segment root form, `/proxy/relay/…` |

**Capacity of one relay worker.** uWSGI's `gevent = N` is the number of concurrent requests a
worker will carry: today's four workers × 400 give 1600 simultaneous connections, and one relay
worker at `gevent = 400` would give 400. `DISPATCHARR_RELAY_GEVENT` defaults to **1600** so the
split preserves today's ceiling exactly, at a cost the ini already documents (~2-4 KB per idle
greenlet, so ~3-6 MB). `listen = 1024` raises the accept backlog from uWSGI's default of 100,
because a relay restart makes every viewer reconnect at once and 100 pending connections is below
the client count this ceiling allows. The single worker is deliberate and is what makes the
ownership lease contention-free in practice (route page, step 1).

**Why `harakiri = 120` and not 60.** Xtream `player_api.php` and `get.php` regenerate a full
catalogue on a large provider; `xmltv.php` and `/output/{m3u,epg}` are synchronous file generation;
backup creation (`apps/backups/services.py`) runs inline on its request. All four are observed to
exceed 60s on a two-core host. Anything past 120s is treated as a bug the timeout exists to
surface, not a workload it should accommodate — hence `harakiri-verbose = true`, so a kill names
the offending request. `DISPATCHARR_API_HARAKIRI` makes a field correction a config change.

**nginx location table (PR 4/PR 5), replacing `docker/nginx.conf`'s single `/proxy/` block.**
Written in the order nginx evaluates: exact matches, then the longest `^~` prefix, then regexes in
file order, then plain prefixes.

```nginx
upstream relay_py { server RELAY_UPSTREAM; }   # sed'd at boot, like NGINX_PORT

map $relay_name $relay_upstream {              # $relay_name set by auth_request_set (PR 5)
    default relay_py;
    py      relay_py;
}

# --- exact matches: short JSON control routes that stay on the API ---
location = /proxy/ts/status              { API }     # note: no trailing slash in urls.py
location = /proxy/vod/stats/             { API }
location = /proxy/vod/stop_client/       { API }
location = /proxy/catchup/stats/         { API }
location = /proxy/catchup/programs/      { API }
location = /proxy/catchup/stop_client/   { API }
location = /streaming/timeshift.php      { relay }
location = /_dispatcharr/authorize       { internal; API }

# --- ^~ prefixes: win outright, no regex is consulted for them ---
location ^~ /api/ {
    include /etc/nginx/dispatcharr_api_params.conf;   # blanks the trust headers, see below
    uwsgi_pass unix:/app/uwsgi.sock;
    location ~ ^/api/channels/logos/(?<logo_id>\d+)/cache/          { proxy_cache … }
    location ~ ^/api/vod/vodlogos/(?<logo_id>\d+)/cache/            { proxy_cache … }
    location ~ ^/api/vod/(movies|series|episodes)/(?<vod_id>\d+)/image/ { proxy_cache … }
    location ~ ^/api/epg/programs/(?<prog_id>\d+)/poster/           { proxy_cache … }
}
location ^~ /assets/            { static }
location ^~ /static/            { static }
location ^~ /logos/             { static }
location ^~ /protected-backups/ { internal; alias }
location ^~ /output/            { API }     # new: /output/m3u/<profile> is 3 segments
location ^~ /hdhr               { API }     # /hdhr/<profile>/discover.json is 3 segments
location ^~ /ws/                { Daphne }
location ^~ /proxy/             { API }     # everything under /proxy/ not claimed below
location ^~ /proxy/ts/stream/   { relay }
location ^~ /proxy/vod/         { relay }
location ^~ /proxy/catchup/     { relay }
location ^~ /proxy/relay/       { relay; internal token is the whole gate (D9) }
location ^~ /live/              { relay }
location ^~ /movie/             { relay }
location ^~ /series/            { relay }
location ^~ /timeshift/         { relay }

# --- regexes, first match wins; admin must precede the XC form ---
location ~ ^/admin(?!/[^/]+/[^/]+/?$)(?:/|$)  { return 301 /login; }   # unchanged
location ~ ^/[^/]+/[^/]+/[^/]+$               { relay }                # XC 3-segment root

# --- plain prefix fallback ---
location /                      { API }     # SPA + everything else; NEVER ^~
```

**The three-segment regex trap, spelled out once.** The XC root form `/<user>/<pass>/<id>` has no
distinguishing prefix, so it can only be matched by a regex. Once that regex exists it also matches
every other three-segment URI with no trailing slash, and three groups of those are real:
`/hdhr/<channel_profile>/discover.json` and its two siblings (`apps/hdhr/urls.py:28-30`),
`/output/m3u/<profile_name>` and `/output/epg/<profile_name>` (`apps/output/urls.py:8-9`), and SPA
deep links. `^~` on `/hdhr` and the new `^~ /output/` take the first two out of the regex's reach
outright. SPA deep links stay in it, are answered correctly by the relay because the urlconf is
identical (D1), and are pinned by PR 2's test. What must never happen is `^~` on `/`: it would take
*every* URI out of regex reach, silently disabling the XC regex, the admin redirect and all four
image caches at once.

### The contract, every endpoint and header named

**1. Authorize (PR 5).** Every relay-bound `location` above issues
`auth_request /_dispatcharr/authorize;`. That location is `internal;` and reaches Django the same
way every other Django-bound location does — `include uwsgi_params; uwsgi_pass unix:/app/uwsgi.sock;`
— plus `uwsgi_param HTTP_X_ORIGINAL_URI $request_uri;` (the subrequest's own URI is
`/_dispatcharr/authorize`, so the original path must be forwarded explicitly, the `uwsgi_pass`
equivalent of the auth_request docs' canonical `X-Original-URI` header) and
`uwsgi_pass_request_body off;`. The Django view wraps `apps/proxy/authorize.py`'s
`authorize_stream` and answers:

| Status | Meaning |
|---|---|
| `200` | Authorized. Response carries `X-Relay-Channel` (uuid), `X-Relay-Output` (Output Profile id or empty), `X-Relay-Client` (client id, minted here when the request has none — the logic now at `live_proxy/views.py:179`), `X-Relay-User` (user id or empty), `X-Relay-Name` (from `settings.RELAY_DEFAULT_NAME`). |
| `401` | No principal resolved where one is required (the XC credential surfaces). |
| `403` | STREAMS ACL denied, or `hidden_from_output` / `is_adult` + the user's `hide_adult_content` / `user_level` / profile membership denied. |
| `404` | Nothing resolved for the identifier — neither a `Channel` by uuid nor a `Stream` by `stream_hash`, nor a VOD or catch-up target. |
| `429` | `check_user_stream_limits` denied and `attempt_stream_termination` could not free a slot. |

nginx then does, once per relay-bound location:

```nginx
auth_request_set $relay_name    $upstream_http_x_relay_name;
auth_request_set $relay_channel $upstream_http_x_relay_channel;
auth_request_set $relay_output  $upstream_http_x_relay_output;
auth_request_set $relay_client  $upstream_http_x_relay_client;
auth_request_set $relay_user    $upstream_http_x_relay_user;

include uwsgi_params;
uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED "RELAY_TRUST_TOKEN";   # sed'd at boot
uwsgi_param HTTP_X_RELAY_CHANNEL $relay_channel;
uwsgi_param HTTP_X_RELAY_OUTPUT  $relay_output;
uwsgi_param HTTP_X_RELAY_CLIENT  $relay_client;
uwsgi_param HTTP_X_RELAY_USER    $relay_user;
uwsgi_buffering off;
uwsgi_pass $relay_upstream;
```

`auth_request_set` is the only place `$upstream_http_*` from the subrequest is readable, which is
also why `$relay_name` — not `$upstream_http_x_relay_name` — is the `map` key. `uwsgi_pass` takes a
variable, so `relay_py` must be an `upstream` group; a bare `relay:5657` in a variable would need a
`resolver` and fail without one. `RELAY_UPSTREAM` is a bare placeholder with no `$`, substituted by
`sed` exactly as `NGINX_PORT` is (`docker/init/03-init-dispatcharr.sh:64`), defaulting to
`127.0.0.1:5657` and taking `${DISPATCHARR_RELAY_HOST:-relay}:${DISPATCHARR_RELAY_PORT:-5657}` in
modular.

**Why the trust marker cannot be forged, in two layers.**

*Layer one, the marker is a secret.* `X-Dispatcharr-Authorized` does **not** carry the literal `1`.
It carries `HMAC-SHA256(SECRET_KEY, "relay-trust")`, and the relay compares it with
`hmac.compare_digest`. The entrypoint computes it from `/data/jwt` in the `all` and `api` roles and
`sed`s it into `nginx.conf` at the `RELAY_TRUST_TOKEN` placeholder, exactly as it already `sed`s
`NGINX_PORT`; the relay derives the same value in Python from the same `SECRET_KEY`. This matters
because nginx is not always in front of the relay's port: `docker/uwsgi.ini` binds
`http = 0.0.0.0:5656`, which is unpublished in `aio` and `modular` but **is** published in `dev` and
`debug` (`docker-compose.dev.yml`, `docker-compose.debug.yml`), and the relay's own `:5657` is
reachable from anywhere on a compose network. A marker whose value is `1` would let anyone who can
reach either port hand the relay a hand-written `X-Relay-Channel` for a hidden channel and skip the
authorize hop entirely. A marker derived from `SECRET_KEY` cannot be produced without it.

*Layer two, nginx overrides what the client sent.* `uwsgi_pass_request_headers` is on by default,
so a client's own `X-Dispatcharr-Authorized` header would reach the application on its own. The
nginx 0.8.40 rule that a `*_param` beginning with `HTTP_` overrides the same-named client header is
what replaces it: in every relay-bound location the four `uwsgi_param HTTP_X_RELAY_*` lines and the
marker overwrite whatever arrived. That covers relay-bound locations only, and D1 means **every**
Django-bound location can serve a stream view, so the non-relay uwsgi locations set the same five
params to the empty string:

```nginx
# /etc/nginx/dispatcharr_api_params.conf — included by every non-relay uwsgi location:
#   /  ,  ^~ /api/  ,  ^~ /output/  ,  ^~ /hdhr  ,  ^~ /proxy/  ,  the six exact = control
#   routes, and = /_dispatcharr/authorize.  (The static, /ws/ and proxy_cache locations use
#   root/alias or proxy_pass, reach no stream view, and need nothing.)
include uwsgi_params;
uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED "";
uwsgi_param HTTP_X_RELAY_CHANNEL "";
uwsgi_param HTTP_X_RELAY_OUTPUT  "";
uwsgi_param HTTP_X_RELAY_CLIENT  "";
uwsgi_param HTTP_X_RELAY_USER    "";
```

It has to be an include repeated per location, not a server-level block, because a location that
declares any `uwsgi_param` of its own inherits none from above. An empty value is still sent, so
the relay sees `""` and fails the constant-time compare, falling through to the inline
`authorize_stream` call — the correct outcome, since that location's request was never authorized.
PR 5 ships an E2E `@contract` test that sends a forged marker and a forged `X-Relay-Channel` for a
hidden channel and asserts 403.

**Two tokens, not one, and they are not interchangeable.** `X-Dispatcharr-Authorized` =
`HMAC(SECRET_KEY, "relay-trust")` answers "did nginx authorize this request", and its only consumer
is the relay's stream views. `X-Dispatcharr-Internal` = `HMAC(SECRET_KEY, "internal-principal")`
(D11) answers "is this caller part of this deployment", and its consumers are `/api/relay/…`,
`/proxy/relay/…` and the authorize hop's internal-principal row. Distinct context strings mean a
leaked marker cannot be replayed as an internal principal, which matters because the marker sits in
a config file nginx reads and the internal token does not.

**The dev fallback.** With no nginx (`manage.py runserver`), the marker is absent and each stream
view calls `authorize_stream` inline, re-deriving everything from the request. Same function, so
the two paths cannot drift.

**The authorize matrix.** Rows are principals; every cell is what `authorize_stream` does, on every
relay-served surface (`/proxy/ts/stream/<uuid>`, `/proxy/catchup/<uuid>`, `/proxy/vod/…`, and the
six XC streaming roots: `live/<user>/<pass>/<id>`, the bare `<user>/<pass>/<id>`,
`timeshift/<user>/<pass>/<duration>/<timestamp>/<id>`, `streaming/timeshift.php`,
`movie/<user>/<pass>/<id>.<ext>` and `series/<user>/<pass>/<id>.<ext>` — the same six enumerated
in § Verified facts, counted the same way everywhere in this spec and in ADR 0005).

The field names are `hidden_from_output` (`apps/channels/models.py:393`) and `is_adult` (`:359`);
there is no field called `hidden`, and `hide_adult_content` is the *user* preference read against
`Channel.is_adult`. `user_level >= User.UserLevel.ADMIN` (10) bypasses every check except the
network ACL, matching the one extracted helper in the tree today
(`apps/timeshift/views.py:774`).

| Principal | Resolved from | STREAMS ACL | `user_level` | Profile membership | `hidden_from_output` | `is_adult` + `hide_adult_content` | `stream_limit` |
|---|---|---|---|---|---|---|---|
| **Internal** (DVR, and any caller with a valid `X-Dispatcharr-Internal`) | HMAC header (D11) | applied | bypassed | bypassed | bypassed | bypassed | bypassed |
| **Admin** (`user_level >= 10`, any authenticator) | JWT / API key / session | applied | bypassed | bypassed | bypassed | bypassed | enforced |
| **XC credentials** | `<user>/<pass>` path segments, `hmac.compare_digest` | applied | enforced | enforced | 403 | 403 | enforced |
| **JWT / API key / query-param JWT** (non-admin) | DRF authenticators | applied | enforced | enforced | 403 | 403 | enforced |
| **Session** (non-admin) | `request.user` when authenticated | applied | enforced | enforced | 403 | 403 | enforced |
| **Anonymous** (bare `/proxy/ts/stream/<uuid>`) | none | applied | not applicable | not applicable | **403** | not applicable | not applicable |
| **Stream-by-hash** (`/proxy/ts/stream/<stream_hash>`), any principal | as above | applied | not applicable | not applicable | not applicable | not applicable | enforced when a principal resolved |

Four rows carry the whole behaviour change, and each is deliberate:

- **Anonymous keeps streaming a valid channel UUID.** The UUID is the capability, exactly as
  today; `stream_ts` is `AllowAny` and gated only by the ACL (`views.py:154-157`). Removing that
  would break every tuner URL in every cached playlist, which is the reason ADR 0005 rejects signed
  URLs. What changes is that a channel with `hidden_from_output` now 403s even anonymously, because
  that field is a property of the channel and needs no principal. `hide_adult_content` is a
  per-*user* preference, so it cannot apply to an anonymous request and is marked not applicable
  rather than skipped — the same distinction `CLAUDE.md` draws for HDHR.
- **Admin bypasses everything but the ACL, and the row is load-bearing.** The admin UI plays
  `/proxy/ts/stream/<uuid>` for any channel from the channels table
  (`frontend/src/components/tables/ChannelsTable.jsx:653,665`), and mpegts.js sends the admin's
  JWT as an `Authorization` header (`FloatingVideo.jsx:492-494`), so the request *does* resolve a
  principal. Without this row, PR 5 would 403 the admin preview of every channel marked
  `hidden_from_output` or `is_adult` — a regression, not a fix. `_user_can_access_channel`
  (`apps/timeshift/views.py:774`) already grants exactly this bypass on the catch-up path;
  `authorize_stream` generalises it rather than inventing it. `stream_limit` still applies, since
  an admin holding a provider slot is the same slot.
- **Stream-by-hash is a separate surface with no channel.** `/proxy/ts/stream/<id>` also serves a
  raw `Stream` when `<id>` is a `stream_hash` rather than a channel UUID — `get_stream_object`
  (`live_proxy/url_utils.py:50-58`) tries `Channel` by uuid and falls back to
  `Stream.objects.get(stream_hash=…)`, and the admin UI uses it for single-stream preview
  (`ChannelTableStreams.jsx:404`, `StreamsTable.jsx:954`). There is no channel, so no
  `user_level`, no profile membership and neither channel flag applies. **PR 5 preserves this
  exactly**: the ACL applies always, the per-user `stream_limit` applies only when a principal
  resolved — an anonymous request has none to check, the same reading as the anonymous row — and
  nothing else applies at all, so an anonymous request with a valid hash still streams. The
  contract's `404` row means "neither a channel UUID nor a stream hash resolved", not
  "not a channel".
- **The DVR is an internal principal.** `run_recording` fetches `/proxy/ts/stream/<uuid>` through
  ffmpeg (`apps/channels/tasks.py:1640`, `_dvr_build_ffmpeg_cmd` at `:1203`) with no credential of
  any kind. After D6 that request goes through nginx and hits the authorize hop; without an
  internal principal, every recording of a hidden or adult or profile-gated channel breaks
  silently. **Mechanism:** `_dvr_build_ffmpeg_cmd` gains
  `"-headers", "X-Dispatcharr-Internal: " + token + "\r\n"` before `-i`, which is ffmpeg's
  documented way to add a request header to an HTTP input. The terminating CR LF must be the two
  real control characters — ffmpeg splits `-headers` on them and does not unescape a literal
  backslash-r backslash-n, so a header built with escaped text is silently sent as one malformed
  line. **Two consequences PR 5 must handle:** the
  function's signature gains the token, and `apps/channels/tasks.py:1726`'s
  `logger.debug(f"... FFmpeg command: {' '.join(...)}")` currently renders the whole argv — it
  would print the internal token, and `scripts/check_credential_logging.py`'s `CREDENTIAL_RE` does
  **not** match `ffmpeg_cmd`, so the guard would not catch it. PR 5 routes that log line through a
  new `_dvr_redact_cmd()` helper and unit-tests it beside `test_dvr_port_resolution.py`.

**2. Next-source / release / events (PR 6).**

- `POST /api/relay/channels/<uuid>/next-source` — body `{exclude_stream_ids, reason}` → Django runs
  `Channel.get_stream()` unchanged and returns `{stream_id, url, user_agent, stream_profile: {id,
  command, args}, m3u_profile_id, transcode}`.
- `POST /api/relay/channels/<uuid>/release` — releases the slot on stop (wraps `release_stream()`).
- `POST /api/relay/events` — body a list of `{type, channel_id, client_id?, stream_id?, details}`;
  each becomes a `log_system_event()` call **in Django**. `channel_buffering` is added to
  `apps/connect/models.py`'s `SUPPORTED_EVENTS`; `stream_stats` is a new type whose `details` carry
  what `_update_stream_stats_in_db` used to write, and Django performs the `stream.save(...)`.

All three require `X-Dispatcharr-Internal` (D11), enforced by an `IsInternalRelay` DRF permission
class. Connect/UI-visible transitions (`channel_failover`, `stream_switch`, `client_disconnect`)
additionally trigger a WebSocket `relay_event` push, so the frontend stops polling
`channel_status` to notice a switch.

**Degraded fallback (relay→Django unreachable at failover).** `apps/proxy/control_plane.py`:
connect timeout 2s, read timeout 5s, one retry. On failure the relay falls back to the candidate
stream list cached at channel start — unenforced, no new slot reservation — logs at `WARNING`, and
posts a `channel_error` event once Django answers again. An existing stream is unaffected.

**3. Relay control API (PR 7).** Served by the relay process, mounted at `/proxy/relay/…`,
`IsInternalRelay`-protected, reached over `get_relay_control_base_url()` (D9).

| Route | Method | Replaces |
|---|---|---|
| `/proxy/relay/channels` | `GET` | (new — list; backs `fetch_channel_stats`) |
| `/proxy/relay/channels/<uuid>` | `GET` | `channel_status`'s Redis reads |
| `/proxy/relay/channels/<uuid>` | `DELETE` | `stop_channel` |
| `/proxy/relay/channels/<uuid>/clients/<client_id>` | `DELETE` | `stop_client` |
| `/proxy/relay/channels/<uuid>/advance` | `POST` `{stream_id?}` | `change_stream` / `next_stream` |

The existing `IsAdmin` views (`channel_status`, `stop_channel`, `stop_client`, `change_stream`,
`next_stream`, `/proxy/stats/`) keep their URLs, names and permission class and become thin
wrappers over `apps/proxy/relay_client.py`. Frontend `api.js` is unchanged. Per D10, only the six
Django-side `ChannelService` call sites move to `relay_client`; the in-relay `ChannelService` is
untouched. `build_live_channel_stats_data` (`channel_status.py:579`) moves behind a DRF serializer
on the relay side of `GET /proxy/relay/channels`, which is where `ffmpeg_speed` and `state` are
normalised.

### ORM reads that remain in the relay after PR 7

Phase 1 takes the relay to zero ORM *writes*. It does not take it to zero reads, and the difference
matters for Phase 2: a Go relay cannot execute any row in this table, so each one is either work
Phase 2 inherits or a decision Phase 2 revisits. Twelve of the 39 sites survive.

| Site | Model | When it runs | Why it stays |
|---|---|---|---|
| `live_proxy/input/manager.py:733` | `StreamProfile` | Every reconnect on the force-ffmpeg path (`_establish_transcode_connection`) | A fallback profile lookup by name, not part of the next-source payload. Folding it in would change what next-source means; PR 6 keeps the contract narrow. |
| `live_proxy/services/channel_service.py:318` | `Channel` | Channel init, when no name was supplied | Display-only name fallback for the metadata hash and the event payload. |
| `live_proxy/services/channel_service.py:325` | `Stream` | Channel init, when no stream name was supplied | Same, for the stream name. |
| `live_proxy/services/channel_service.py:908` | `Stream` | `_update_channel_metadata` after a switch | Same, for the switched-to stream name. |
| `live_proxy/channel_status.py:74` | `Stream` | `GET /proxy/relay/channels/<uuid>`, when Redis has no stream name | After PR 7 this handler *is* the relay's control API, so the read moves to the relay's side of the boundary rather than away. |
| `live_proxy/channel_status.py:92` | `M3UAccountProfile` | Same handler, profile-name fallback | Same. |
| `vod_proxy/views.py:230`, `:310` | `Movie`, `Episode` | Every VOD tune (`_get_content_and_relation`) | Phase 1 builds no VOD control API; VOD keeps its own tune-time resolution. Out of scope, stated in § Non-goals by omission of a VOD contract. |
| `vod_proxy/views.py:494`, `:510`, `:535`, `:552` | `M3UAccountProfile` | Every VOD tune (`_get_m3u_profile`) | Same. |
| `vod_proxy/views.py:1101`, `:1135`, `:1173` | `Movie`, `Episode`, `M3UAccountProfile` | `build_vod_stats_data`, on the VOD stats surface | Same; the VOD stats payload is not part of the relay control API. |
| `vod_proxy/views.py:1420`, `:1456` | `M3UMovieRelation`, `M3UEpisodeRelation` | XC movie/series tune | The authorize hop resolves the *principal*, not the content object; content resolution stays in the view. |
| `live_proxy/url_utils.py:614` | `M3UAccountProfile` | Never — `get_connections_left` has zero callers | Dead. Deleting it is a one-line cleanup PR 7 may take or leave; it changes nothing either way. |

Everything else goes: the four `Channel.get_stream()` sites and the failover traversals become
next-source calls (PR 6); `server.py:2363,2373`, `output/ts/generator.py:618,620` and
`output/fmp4/generator.py:378,380` all call `release_stream()` and become the release call;
`input/manager.py:1430`'s `update_stream_profile` moves into Django's next-source handling, where
the credential-slot move already belongs; `channel_service.py:856` disappears with the write it
precedes; and `views.py:140,148,804,813`'s tune-time lookups move into `authorize_stream`, which
runs in the API process (PR 5).

### Error handling per hop

| Hop failing | Behaviour |
|---|---|
| **Django down, existing viewer** | Unaffected. Nothing on the byte path calls Django once a stream runs; next-source fires only at failover. |
| **Django down, new tune** | The `auth_request` subrequest to an unreachable upstream is not a 2xx and not 401/403, so nginx reports its own error: `502` when the API process is stopped (connection refused), `504` when it is hung. PR 8's test asserts the status is in `{502, 503, 504}` rather than one code, because which one appears depends on how the API died. |
| **Django down, failover on an existing stream** | Degraded fallback above — stale candidate list, unenforced, logged, `channel_error` posted on recovery. |
| **Relay down, existing viewer** | Connection drops; retries get `502`/`504` until supervisord restarts `relay-uwsgi`, then a normal reconnect. Bounded, not invisible (route page, "Honest limits"). |
| **Relay down, new tune** | Authorize succeeds (Django is up), `uwsgi_pass` to `$relay_upstream` fails, nginx returns `502`/`504`; every player in the supported set retries a failed connect. |
| **Relay up but overloaded** | Past `gevent` concurrency the worker stops accepting; `listen = 1024` absorbs a reconnect storm, beyond which nginx returns `502`. |
| **nginx absent (dev `runserver`)** | The inline `authorize_stream` fallback (D8) runs in the stream view; `get_relay_control_base_url()`/`get_control_plane_base_url()` both resolve to the single dev process's own port. None of the split machinery activates. |

## The eight pull requests

Eight code PRs plus one docs PR (D16). PR 0 is this spec's own branch (`docs/phase1-spec`),
carrying this document, ADR 0005 and the `CONTEXT.md` glossary entries — docs-only, and
deliberately *not* on `migration/**`, so the heavy CI jobs take their change-detector skip path.
PRs 1-8 are `migration/phase1-*`, which makes `lifecycle-tests.yml`'s `suites` job and the full
E2E project matrix run on every one of them (`lifecycle-tests.yml:119-124`, `:231`). Budget ~10-15
minutes per real CI run; backend ~11-12 min, E2E and lifecycle ~8-13 min in full mode.

The two legitimate stopping points are **after PR 4** (the API has a request timeout and worker
recycling, the relay is its own process, and no relay code has changed) and **after PR 7** (the
relay's Redis keys are private and Phase 3 becomes a relay-only change). PR 8 is not a third
optional PR bolted on the end: it is the gate for anything after Phase 1, and its two scenarios
depend on PR 5 (the Django-down test needs the authorize hop to be the thing that fails) and PR 3
(the bounded-restart test needs `supervisorctl`). Stopping after PR 4 therefore means stopping
without PR 8 — take the docs and lifted-constraints half of PR 8 with PR 4 and leave the two E2E
scenarios for whenever PR 5 lands. Stopping after PR 7 means taking PR 8 whole.

### PR 1 — `migration/phase1-supervisor-dep`

- `pyproject.toml`: add `"supervisor==4.3.0"` to `[project].dependencies`, following the exact-pin
  half of the file's convention (11 of its entries pin with `==`); a supervisor version change
  swaps the process supervisor for every deployment, which is the case for pinning exactly.
  `uv.lock` regenerated with `uv lock`.
- No entrypoint or ini change. The dependency lands alone so `base-image.yml` rebuilds
  `ghcr.io/…:base` on `main` before any later PR execs `supervisord` in a CI-built image (D2).
- **Done:** `uv lock --check` green in `lint.yml`; `Backend result` green — it runs in full,
  because `pyproject.toml` is in `_SHARED_PATH_PREFIXES`; `base-image.yml`'s `docker` job green on
  the PR itself (build-only on `pull_request`, `:148`; this is the real `uv sync --locked` proof,
  run in the actual `DispatcharrBase` build stage against this branch's lockfile); `E2E result` and
  `Lifecycle result` green, now built against this fork's own `:base` rather than upstream's
  default (`docker/Dockerfile`'s `REPO_OWNER` build-arg, fixed in this same PR — see D2).
  After merge, `base-image.yml` runs on `main` and the new `:base` digest contains supervisord —
  confirmed by `docker run --rm <digest> /dispatcharrpy/bin/supervisord -v`, recorded in the PR.

### PR 2 — `migration/phase1-ttfb-test`

- New E2E spec in the `streaming` project, `@contract`: request `/proxy/ts/stream/<uuid>` through
  port 9191 and assert at least one 188-byte-aligned TS packet arrives within **N seconds, where
  N ≤ 10**. Ten seconds is the ceiling: past it the assertion no longer distinguishes a live stream
  from nginx spooling to disk, which is the only thing this test exists to catch. The implementing
  PR measures the current value against G4's `streaming` timings and records both the measurement
  and the chosen N in its description.
- New E2E spec, same project, `@contract`: a three-segment root URI that is a valid SPA deep link
  still serves the SPA shell, not a 404. Written **before** PR 4's routing change exists, on the
  current single-process shape, so it is a real regression guard rather than a test written to
  match the code.
- `e2e/README.md:104` and `:111` corrected to name `e2e/tests/guards/allowlist.ts` +
  `capabilities.spec.ts`; `e2e/README.md:780` corrected — the live Main ruleset already requires
  `Lifecycle result`.
- **Done:** both specs pass in the `streaming` project on `main`'s current shape; `E2E result`
  green; `e2e/tests/guards/tags.spec.ts` passes (each new `test()` carries exactly one tag).
- **`CLAUDE.md` corrected:** § Testing, "five projects" → thirteen and "eight injectable faults" →
  twelve; the greybox-quarantine sentence naming the deleted file.

### PR 3 — `migration/phase1-supervisord`

Supervision only. No relay program, no routing change, so the PR is verifiable against the
unchanged single-process shape.

**Boot order is the whole difficulty of this PR.** The one-shot work needs Postgres and, in
modular, Redis — and supervisord has not started anything when the entrypoint runs. Three rules
resolve it, and each exists because a simpler arrangement provably does not boot:

1. **The `all` role starts Postgres exactly as today** (`entrypoint.sh:253-258`,
   `pg_ctl start -w -t 300` then the `pg_isready` loop), runs the one-shot against it, then
   **`pg_ctl -D $POSTGRES_DIR stop -m fast`** before `exec supervisord`. Without the stop,
   supervisord's `[program:postgres]` starts a second postmaster against a data directory whose
   `postmaster.pid` belongs to the entrypoint's instance; it fails, retries, and lands in `FATAL`.
   After the stop, supervisord's foreground `postgres` is the only instance in the container.
2. **No role flushes Redis, and the `all` one-shot does not wait for it either.** AIO Redis does
   not exist until supervisord starts it, so a wait in that one-shot counts 30 retries × 2 s and
   exits 1 (`scripts/wait_for_redis.py:75`). The wait is also unnecessary there once
   `[program:redis]` runs `redis-server --save "" --appendonly no`: a non-persistent Redis starts
   empty, which is the state today's boot `flushdb()` produces, and that persistence (today's bare
   `redis-server` writes `dump.rdb` into its working directory) was the only reason the flush
   existed. `_flush_non_celery_keys` and the `flushdb()` branch are **deleted**, not moved —
   `scripts/wait_for_redis.py` becomes wait-only (D15). Programs that need Redis wait for it in
   their own command (rule 3).
3. **`priority=` is start order, not a readiness barrier**, so every program that needs a store
   waits for it in its own `command=`. Both uWSGI programs run through a small wrapper
   (`docker/supervisord.d/wait-for-stores.sh`) that loops on `pg_isready` and then runs
   `python /app/scripts/wait_for_redis.py` — wait-only after this PR, so no flag is needed —
   before `exec`ing uWSGI; Celery retries its broker itself and needs no wrapper. `startretries=20` and `startsecs=5` on both, so a slow
   Postgres cannot exhaust the retries and drive a program to `FATAL`.

- `docker/entrypoint.sh`: add `export DISPATCHARR_ROLE=${DISPATCHARR_ROLE:-all}` with a `case`
  validating it against the four values, and **role-gate the one-shot work**:
  - `all`: PUID/PGID, PG init/upgrade, start Postgres as today, `migrate`, `collectstatic`, the
    nginx `sed`, then `pg_ctl stop -m fast` (rule 1 above). No Redis wait (rule 2).
  - `api`: PUID/PGID, generate-or-read `/data/jwt`, `migrate`, `collectstatic`, the nginx `sed`.
    It may wait for external Redis if a fast failure message is wanted, but it **must not flush**;
    `api-uwsgi`'s own wrapper waits anyway (rule 3).
  - `relay`, `worker`: PUID/PGID and the TLS key fixup, then wait for `/data/jwt` and for
    `manage.py migrate --check`, lifting the two loops from `entrypoint.celery.sh:12-24` and
    `:45-58` verbatim. No nginx `sed`, no `migrate`, no `collectstatic`.
- **The supervisord config is selected by a three-input ladder, not by role alone.** `dev` and
  `debug` are `DISPATCHARR_ENV`/`DISPATCHARR_DEBUG` values, not roles, and D2 commits to covering
  them: dev runs vite and **no nginx** (`entrypoint.sh:300-313` — vite serves 9191 and proxies
  `/api` to 5656), and debug runs a different uWSGI ini. `exec supervisord -n -c
  /app/docker/supervisord/${DISPATCHARR_ROLE}.conf` cannot say any of that. The entrypoint
  therefore computes `SUPERVISORD_CONF` with the same ladder it already uses for `uwsgi_file` at
  `:332-345`, in the same order:

  | Condition | Conf |
  |---|---|
  | `DISPATCHARR_DEBUG = true` | `all-debug.conf` |
  | `DISPATCHARR_ENV = dev` | `all-dev.conf` |
  | otherwise, by `DISPATCHARR_ROLE` | `all.conf`, `api.conf`, `relay.conf`, `worker.conf` |

  then `exec supervisord -n -c "$SUPERVISORD_CONF"`. Add `DISPATCHARR_ROLE` to the `variables=()`
  array at `:177-184` so `docker exec` shells see it.
- `docker/init/03-init-dispatcharr.sh` is sourced unconditionally at `entrypoint.sh:250`, so the
  role gate on the nginx work has to live **inside** that script, around the `NGINX_PORT` `sed` at
  `:64` and the IPv6 strip at `:67-72`, not at the call site. The `/app` ownership and data-dir
  chown steps in the same script stay unconditional — every role needs them.
- `docker/supervisord/{all,all-dev,all-debug,api,relay,worker}.conf` — six files, one per rung of
  the ladder above. Each carries `[supervisord]` (`nodaemon=true`, `logfile=/run/supervisord.log`,
  `logfile_maxbytes=1MB`, `logfile_backups=1`, `pidfile=/run/supervisord.pid`,
  `childlogdir=/run`), `[unix_http_server] file=/run/supervisor.sock`,
  `[rpcinterface:supervisor]`, `[supervisorctl] serverurl=unix:///run/supervisor.sock`, and one
  `[include] files = …` naming its programs explicitly. Six files rather than one file with
  `%(ENV_…)s` in `[include]`: supervisor 4.3.0 *does* expand environment variables there
  (`supervisor/options.py:578-588` merges `environ_expansions` into the dictionary
  `[include] files` is expanded against, though the reference documents only `here` and
  `host_node_name`), but no single environment variable names the rung — the selector is
  role × env × debug, the same three inputs `entrypoint.sh:332-345` already resolves in bash for
  the uWSGI ini. Doing it the same way twice is cheaper to read than encoding a ladder in a glob.
- `docker/supervisord.d/*.conf` — one `[program:…]` per file, `command=` given in full so no
  daemonising form slips in, and each named by the conf files that include it:

  | Program | Included by | `command=` | Notes |
  |---|---|---|---|
  | `postgres` | `all`, `all-dev`, `all-debug` | `postgres -D %(ENV_POSTGRES_DIR)s -c port=%(ENV_POSTGRES_PORT)s` | Foreground. Not `pg_ctl start`, which daemonises and would leave supervisord supervising the wrong process. `stopsignal=INT` — Postgres's fast shutdown, clean and well inside the 45 s grace period; `-m immediate` (`QUIT`) is what the old entrypoint used only because it had 8 seconds. `stopwaitsecs=30`. |
  | `redis` | `all`, `all-debug` | `redis-server --save "" --appendonly no` | AIO only. Non-persistent, which is what removes the boot flush (rule 2). `stopsignal=TERM`, `stopwaitsecs=5`. |
  | `redis-dev` | `all-dev` | `redis-server --save "" --appendonly no --protected-mode no` | Same program with one more flag, because `uwsgi.dev.ini:11` already runs `redis-server --protected-mode no` and dropping that flag would break dev tooling, not just relax it: `docker-compose.dev.yml:60` points `redis-commander` at `dispatcharr:6379` over the compose network, and protected mode refuses every non-loopback connection (the `DENIED` trap `CLAUDE.md` records). A separate program rather than a conditional flag, so the one rung that lowers a security default says so in its own file. |
  | `api-uwsgi` | `all`, `all-dev`, `all-debug`, `api` | `nice -n %(ENV_UWSGI_NICE_LEVEL)s /app/docker/supervisord.d/wait-for-stores.sh %(ENV_VIRTUAL_ENV)s/bin/uwsgi --ini <selected ini>` | `<selected ini>` is the value `entrypoint.sh:332-345` already computes, exported for supervisord to read. `startretries=20`, `startsecs=5`, `stopwaitsecs=10`. |
  | `daphne` | `all`, `all-dev`, `all-debug`, `api` | `daphne -b 0.0.0.0 -p 8001 dispatcharr.asgi:application` | `stopwaitsecs=10`. |
  | `celery-default` | `all`, `all-dev`, `all-debug`, `worker` | `nice -n %(ENV_CELERY_NICE_LEVEL)s celery -A dispatcharr worker -Q celery -n default@%%h --autoscale=6,1` | `%%h`, because `%` is supervisord's expansion character. `stopwaitsecs=30` — a task in flight. **`CELERY_NICE_LEVEL` becomes absolute**: see below. |
  | `celery-dvr` | `all`, `all-dev`, `all-debug`, `worker` | `nice -n %(ENV_CELERY_NICE_LEVEL)s celery -A dispatcharr worker -Q dvr -n dvr@%%h --pool=threads --concurrency=20` | `stopwaitsecs=30`. |
  | `celery-beat` | `all`, `all-dev`, `all-debug`, `worker` | `nice -n %(ENV_CELERY_NICE_LEVEL)s celery -A dispatcharr beat` | `stopwaitsecs=10`. |
  | `nginx` | `all`, `all-debug`, `api` | `nginx -g 'daemon off;'` | Without `daemon off` nginx forks and exits, and supervisord restarts it forever. Highest `priority`, so it starts last and is signalled first on shutdown — signalled, not waited for; see below. `stopsignal=QUIT` is nginx's own graceful-shutdown signal. |
  | `vite` | `all-dev` | `npm run dev` (`directory=/app/frontend`) | Only rung with vite, and the only one **without** `nginx`: today `entrypoint.sh:300-313` starts vite instead of nginx in dev, and vite serves 9191 itself. `all-debug` keeps nginx, matching today. |

  Every program also carries `user=%(ENV_POSTGRES_USER)s` where the entrypoint used `su -`,
  `stdout_logfile=/dev/stdout`, `stdout_logfile_maxbytes=0` and `redirect_stderr=true` so
  container logs keep working, and a `priority=` that starts the stores first and nginx last.
- **`priority=` orders signals on shutdown, not waits.** Verified against the supervisor 4.3.0
  source: `ProcessGroup.stop_all` (`supervisor/process.py:813-828`) sorts by priority, reverses,
  and calls `proc.stop()` on each in one pass; `Subprocess.stop` (`:379-383`) sends the signal and
  returns immediately. So nginx is *signalled* before the relay, but every program's
  `stopwaitsecs` runs concurrently. The consequence that matters is the grace period: the container
  needs to cover the **longest** single `stopwaitsecs` (Postgres at 30 s), not their sum, which is
  why 45 s is enough for a program set whose stop windows add up to more than two minutes.
- **`CELERY_NICE_LEVEL` has to stop being a relative offset.** `entrypoint.sh:128` exports it as
  `CELERY_NICE_ABSOLUTE - UWSGI_NICE_LEVEL` (`:124`, `:123`) because Celery is an `attach-daemon`
  of an already-niced uWSGI and `nice` composes with the parent's value. Under supervisord every
  program is a child of supervisord at nice 0, so the offset would be applied as an absolute and
  Celery would land at the wrong priority — at the defaults, nice 5 today versus nice 5 minus 0,
  which happens to agree, and at any non-zero `UWSGI_NICE_LEVEL`, silently wrong. PR 3 deletes the
  subtraction and exports the absolute value, and the comment at `:120-122` is updated to say
  supervisord is now the parent. This is the one behavioural change in PR 3 that is not visible in
  any test, so it is called out here rather than left to the diff.
- **Fix the readiness contract the bash suites depend on.** `docker/tests/test-puid-pgid.sh:171`
  and `:291` and `docker/tests/test-tls-postgres.sh:146` and `:249` all match the literal
  `uwsgi started with PID`, produced only by `docker/entrypoint.sh:360`, which this PR deletes.
  All four move to `docker exec <name> supervisorctl -c <role conf> status api-uwsgi` reporting
  `RUNNING`. That is the same signal as supervisord's `success: … entered RUNNING state` log line
  but in a documented, version-stable form — the log text is supervisor-internal, while
  `supervisorctl status`'s output is in the reference — and it is role-aware, so the modular
  scenarios can wait on the program they actually care about. The existing `docker ps` liveness
  check ahead of the loop already covers the container-exited-before-supervisord case. Without
  this change every scenario in both suites times out.
- **`docker/entrypoint.celery.sh` deleted**; `docker/docker-compose.yml`'s `celery` service drops
  its `entrypoint:` override and sets `DISPATCHARR_ROLE=worker`.
  `docker/tests/test-tls-postgres.sh:923` drops the `--entrypoint` override for
  `-e DISPATCHARR_ROLE=worker`, and its two log assertions at `:946` ("starting Celery") and `:955`
  ("Migrations complete") move to the strings the shared entrypoint prints.
- `docker/entrypoint.aio.sh` deleted (dead code).
- `docker/uwsgi.ini`, `uwsgi.modular.ini`, `uwsgi.dev.ini`, `uwsgi.debug.ini`: **every `exec-pre`
  and every `attach-daemon` removed.** Those daemons are now supervisord programs, and the
  `exec-pre` Redis flush is gone entirely (rule 2). Leaving them would start Redis, Celery and
  Daphne twice and would flush Redis on every uWSGI restart. `uwsgi.debug.ini` additionally drops
  `honour-stdin = true` (`:72`) — see D2.
- `stop_grace_period: 45s` on `docker/docker-compose.aio.yml`'s one service **and on the modular
  `web` and `relay` services** in `docker/docker-compose.yml`. Docker's 10-second default would
  SIGKILL supervisord partway through the relay's `stopwaitsecs=20` (PR 4) and Postgres's 30;
  setting it on every service that runs supervisord keeps PR 4 to code. The `celery` service gets
  it too, since `celery-default`/`celery-dvr` carry `stopwaitsecs=30`.
- `docker/tests/test-puid-pgid.sh`: `test_fresh_default` gains an assertion that
  `docker exec … supervisorctl -c … status` reports every program of role `all` as `RUNNING` and
  none as `FATAL` or `BACKOFF`.
- `scripts/e2e_up.sh` needs no change, but the `--stop` path (`:110-111`) uses `docker stop`'s
  10-second default, so from PR 4 on a relay in `stopwaitsecs=20` is SIGKILLed rather than stopped.
  That is acceptable for a test harness tearing the container down, and it is why
  `restart-persistence.spec.ts` asserts recovery after a restart rather than a clean drain — stated
  here so the difference between the harness and a real deployment is not read as a defect.
- **Done:** `Lifecycle result` green in full mode — both bash suites run on a `migration/**` branch
  and every scenario still passes, which is the real proof the readiness-marker change is complete;
  `supervisorctl status` after boot shows every program of the role `RUNNING` and none `FATAL` or
  `BACKOFF`, in `test_fresh_default` and in `test_modular_mode` (the assertion that would catch a
  uWSGI program losing its race with Postgres or Redis, which `priority=` alone does not prevent);
  `grep -rn "flushdb\|flushall\|_flush_non_celery_keys" scripts/ apps/ core/ dispatcharr/ docker/`
  returns nothing outside test files, which is the check that D15 actually landed rather than
  moving the flush somewhere quieter;
  `E2E result` green in full mode (the AIO container still boots and serves the whole Playwright
  matrix); `test_readonly_rootfs` reports the same outcome it does today, a `log_skip`
  (`e2e/README.md:780-783` records the current 135/0/1 result — the scenario cannot currently pass,
  and `test-puid-pgid.sh:1447-1449` turns any read-only startup failure into a skip, so "it still
  passes" would be an unverifiable criterion). The read-only property is instead asserted
  statically: `grep -nE '^(logfile|pidfile|childlogdir|file)\s*=' docker/supervisord/*.conf` returns
  only paths under `/run`. `docker-build.yml` is **not** a criterion — it runs only on push to
  `main` and is never a PR check.
- **`CLAUDE.md` corrected:** § Architecture, the "`docker/uwsgi.ini` runs uWSGI … with the rest as
  `attach-daemon`" paragraph and the `entrypoint.aio.sh` "legacy" parenthetical (deleted, not
  legacy); § Architecture § State, "`scripts/wait_for_redis.py` does `flushdb()` on every AIO boot;
  the modular variant preserves only Celery prefixes" — after this PR it flushes nothing and AIO
  Redis is simply non-persistent; § Commands, the Docker bullet; § Known defects, "`die-on-term`
  with no drain" reworded to name supervisord's bounded stop.

### PR 4 — `migration/phase1-process-split`

- `docker/uwsgi.relay.ini`: `docker/uwsgi.ini` minus the (now removed) daemon block and minus
  `http`/`http-keepalive`/`http-timeout`, plus `socket = 0.0.0.0:5657`, `chmod-socket` dropped (TCP),
  `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)`, `listen = 1024`. Everything else carried
  verbatim so the relay is the same application: `chdir`, `module`, `virtualenv`, `master`, both
  `env =` lines, `gevent-early-monkey-patch`, `import = dispatcharr.gevent_patch`, `buffer-size`,
  `post-buffering`, `socket-timeout = 600`, `lazy-apps`, `thunder-lock`, `vacuum`, `die-on-term`,
  `static-map`, and the log block. **No `harakiri`.**
- `docker/uwsgi.ini` / `uwsgi.modular.ini` (the API's inis): add
  `harakiri = $(DISPATCHARR_API_HARAKIRI)`, `harakiri-verbose = true`,
  `max-requests = $(DISPATCHARR_API_MAX_REQUESTS)`. uWSGI expands `$(VAR)` only, so
  `docker/entrypoint.sh` gains `export DISPATCHARR_API_HARAKIRI=${DISPATCHARR_API_HARAKIRI:-120}`,
  `export DISPATCHARR_API_MAX_REQUESTS=${DISPATCHARR_API_MAX_REQUESTS:-5000}` and
  `export DISPATCHARR_RELAY_GEVENT=${DISPATCHARR_RELAY_GEVENT:-1600}`, each added to the
  `variables=()` array at `:177-184`.
- New supervisord program `relay-uwsgi`, the same shape as `api-uwsgi` in PR 3's table —
  `nice -n %(ENV_UWSGI_NICE_LEVEL)s`, the `wait-for-stores.sh` wrapper, `startretries=20`,
  `startsecs=5` — with `--ini /app/docker/uwsgi.relay.ini` and `stopwaitsecs=20`, the longest of
  any program and the number PR 8's bounded-restart ceiling is derived from. It is included by
  `all.conf`, `all-dev.conf`, `all-debug.conf` and `relay.conf`; `api.conf` (`api-uwsgi`, `daphne`,
  `nginx`) and `relay.conf` (`relay-uwsgi` only, D14) start being used as whole files for the first
  time here.
- `docker/nginx.conf`: the full location table in § Architecture, minus the `auth_request` block
  and minus the `map`. PR 4 writes `upstream relay_py { server RELAY_UPSTREAM; }` and
  `uwsgi_pass relay_py;` directly — there is no `X-Relay-Name` header to key a `map` on until PR 5,
  and a one-branch `map` on a constant would be noise a reader has to disprove.
  `docker/init/03-init-dispatcharr.sh` gains a `RELAY_UPSTREAM` `sed` beside the `NGINX_PORT` one
  at `:64` (inside the same role gate PR 3 added), plus a numeric guard on
  `DISPATCHARR_RELAY_PORT` matching the existing `DISPATCHARR_PORT` guard.
- `apps/channels/tasks.py`: `get_dvr_stream_base_url()`'s AIO/dev/debug branch per D6.
  `apps/channels/tests/test_dvr_port_resolution.py`: the four `5656` assertions become `9191`, and
  a fifth test pins that `DISPATCHARR_PORT` is honoured in AIO.
- `docker/docker-compose.yml`: new `relay` service — same image, `DISPATCHARR_ROLE=relay`,
  `DISPATCHARR_ENV=modular`, **`./data:/data`** (D11: without it the relay generates its own
  `SECRET_KEY` and every internal call 403s), `POSTGRES_HOST=db`, `REDIS_HOST=redis`, no published
  ports, `depends_on` db and redis `service_healthy`. `web` gains `DISPATCHARR_ROLE=api` and
  `DISPATCHARR_RELAY_HOST=relay`. `docker/docker-compose.yml:191`'s `5436:5432` publish is **not**
  touched (carried; see § Requirements).
- `docker/tests/test-puid-pgid.sh`: new `test_role_split`, modelled on `test_modular_mode`
  (`:980-1046`). It is the only test in the programme that exercises the modular relay hop; a
  Playwright project cannot do it, because `scripts/e2e_up.sh:247` is a single `docker run` with
  `DISPATCHARR_ENV=aio` and stays that way in this spec. The scenario has more moving parts than
  any existing one in that file, so the spec fixes its shape rather than leaving it to be
  rediscovered:

  1. **Containers**, all on one created network: `postgres:17` and `redis:latest` as
     `test_modular_mode` starts them, `dispatcharr-e2e-upstream:local` as the fake provider
     (already in the lifecycle image tarball — `lifecycle-tests.yml:196` builds it and `:204`
     saves it alongside `dispatcharr-e2e:local`, and `test-puid-pgid.sh` references neither today),
     and three app containers with `DISPATCHARR_ROLE` of `api`, `relay` and `worker`.
  2. **Shared state.** All three app containers mount **one** `/data` volume, because
     `SECRET_KEY` is read from `/data/jwt` and a relay with a different key 403s every internal
     call (D11). `api` publishes 9191; `relay` and `worker` publish nothing.
     `DISPATCHARR_WEB_HOST` is the api container's name (worker → Django, and relay → Django), and
     `DISPATCHARR_RELAY_HOST` is the relay container's name (nginx → relay, and Django → relay).
  3. **Seeding, ported from `e2e/fixtures/seed.ts`** rather than reinvented — that file is the
     authority on the call sequence and the reason for each step. Minimum path, all against the
     api container's 9191: `GET`/`POST /api/accounts/initialize-superuser/`
     (`e2e/setup/provision-admin.ts:38,48`), `POST /api/accounts/token/` for an access token,
     `POST /scenarios` on the provider's control port to get a scenario (`e2e/fixtures/upstream.ts:265`),
     `POST /api/channels/streams/` with `url` = `<scenario.internal>/stream/<n>.ts`
     (`seed.ts:220,326`), then `POST /api/channels/channels/` with `streams: [<id>]`
     (`seed.ts:106`). No M3U account and no refresh: `seed.upstreamChannel` (`:304-320`) creates
     streams directly, which is the shortest path to a playable channel and the one this scenario
     should copy.
  4. **The UUID** comes from the create-channel response body's `uuid` field; no extra lookup.
  5. **The assertion**: `curl` the api container's `http://127.0.0.1:9191/proxy/ts/stream/<uuid>`,
     read N bytes, and assert byte 0 and byte 188 are both `0x47`. That proves nginx routed to the
     relay container over the network, the relay tuned the upstream, and the bytes came back
     TS-aligned. A second assertion stops the `relay` container and checks a new tune fails while
     the api container stays up and answers `/api/channels/channels/`.
- `e2e/fixtures/instance.ts`: new `supervisorctl(argv)` helper beside the existing `manage()`
  (`:355-385`), same `docker exec` shape and same `ManageResult` return. **This is not optional
  tidiness**: reading `supervisorctl` from a spec is a `SUBPROCESS` and
  `CONTAINER_INTROSPECTION` use, and `e2e/tests/guards/allowlist.ts` grants both to
  `fixtures/instance.ts` and the greybox spec only. A spec that shells out directly fails the
  `guards` project with `capabilities.spec.ts` naming it. Putting the helper on the fixture keeps
  the allowlist unchanged, which is the design that file argues for. PR 8's Django-down spec uses
  the same helper for `stop`/`start`/`restart`.
- `e2e/tests/lifecycle/restart-persistence.spec.ts`: reshaped per its own in-file
  `@characterization` warning, but only as far as the AIO harness allows — a container restart now
  asserts through `instance.supervisorctl(['status'])` that both `api-uwsgi` and `relay-uwsgi`
  return to `RUNNING`, and that a stream re-tunes, in addition to the existing durable-state
  assertions. The two-unit, restart-one-not-the-other scenario lives in `test_role_split`, not
  here.
- **Done:** PR 2's TTFB and SPA-three-segment specs still pass, now genuinely crossing the process
  boundary; `E2E result` green in full mode including `streaming` and `streaming-failover` (G4's
  existing coverage running against two processes is the evidence the split preserved relay
  behaviour); `Lifecycle result` green with `test_role_split` passing; `Backend result` green
  (`apps.channels.tests` covers the DVR URL change).
- **`CLAUDE.md` corrected:** § Architecture's opening paragraph (one uWSGI → two); the
  `uwsgi_buffering off` bullet, to name the relay-bound locations; § Known defects, "No `harakiri`,
  and it can't be enabled while the relay shares a process with the API" — now enabled on the API.

### PR 5 — `migration/phase1-authorize`

- `apps/proxy/authorize.py`: `authorize_stream()`, `AuthorizeResult`, `AuthorizeDenied`.
  `apps/proxy/authorize_views.py`: the `AllowAny` DRF view nginx calls, plus the inline-fallback
  helper the stream views use.
- `stream_ts`, `stream_xc`, `stream_vod`, `catchup_proxy`, `timeshift_proxy[_query]`,
  `stream_xc_movie`, `stream_xc_episode` call `authorize_stream` first; their inline
  `network_access_allowed`, plaintext password compare, `_user_can_access_channel` and
  `check_user_stream_limits` calls are deleted, not duplicated. The XC compare becomes
  `hmac.compare_digest`.
- `check_user_stream_limits` moves *inside* `authorize_stream` unchanged, still scanning Redis
  directly from whichever process runs the hop. That is the intermediate state, not the end state:
  PR 7 splits `get_user_active_connections` by owner so the live branch goes through
  `relay_client`. Recorded here because between PR 5 and PR 7 the API process reads a relay key,
  which PR 7's own grep would otherwise look like a regression against.
- The authenticator set becomes the union of what the four stream views accept today, which means
  `/proxy/ts/stream/` gains `QueryParamJWTAuthentication` — VOD (`vod_proxy/views.py:611`) and
  catch-up (`apps/timeshift/views.py:281`) already accept `?token=`, live TS does not. A small,
  deliberate widening: it makes one function possible, and it matches what the frontend already
  does for recordings (`FloatingVideo.jsx:22-30`).
- `dispatcharr/settings.py`: `RELAY_DEFAULT_NAME = os.environ.get("DISPATCHARR_RELAY_DEFAULT_NAME",
  "py")`. That is the only definition; the nginx `map` key is the literal string `py` and needs no
  templating.
- `docker/nginx.conf`: `location = /_dispatcharr/authorize { internal; … }`; every relay-bound
  location gains the `auth_request` + five `auth_request_set` + `uwsgi_param HTTP_X_*` block from
  § Architecture; every non-relay uwsgi location switches to the shared
  `dispatcharr_api_params.conf` include that blanks the five trust headers; the `map` key becomes
  `$relay_name`.
- `apps/channels/tasks.py`: `_dvr_build_ffmpeg_cmd` gains `-headers` with
  `X-Dispatcharr-Internal`, and the argv debug log at `:1726` goes through a new `_dvr_redact_cmd`.
- Remove the erroneous `wontfix` label from issue #87 before closing it (see § What the code says).
- `docker/init/03-init-dispatcharr.sh`: compute `HMAC(SECRET_KEY, "relay-trust")` with a
  `python3 - <<'PY'` heredoc — the same tool and shape the entrypoint already uses to generate the
  secret at `:110-113`, and the only one guaranteed present, since nothing in either Dockerfile
  installs `openssl` as an app dependency — and `sed` it into `nginx.conf`'s `RELAY_TRUST_TOKEN`
  placeholder, beside the `NGINX_PORT` and `RELAY_UPSTREAM` substitutions inside the same role
  gate. Runs in the `all` and `api` roles only, the two that run nginx.
- New E2E `@contract` specs: a channel with `hidden_from_output` and one with `is_adult` (against a user with `hide_adult_content`) both 403 on `/proxy/ts/stream/<uuid>`,
  `/proxy/catchup/<uuid>` and each XC root form (closing #87 and #95); an anonymous request with a
  valid UUID for an ordinary channel still streams; a client-supplied
  `X-Dispatcharr-Authorized` value plus a forged `X-Relay-Channel` for a hidden channel gets 403.
- Unit tests: the full authorize matrix above, one test per cell that differs from its neighbours;
  `_dvr_redact_cmd`; the DVR internal-principal path, beside `test_dvr_port_resolution.py`.
- **Done:** the E2E authorize specs pass in full mode; `apps.proxy.tests`,
  `apps.proxy.live_proxy.tests`, `apps.channels.tests` and `apps.timeshift.tests` green;
  `scripts/check_credential_logging.py` clean on `apps/channels/tasks.py`; issues #87 and #95
  closeable, with the closure recorded in PR 8's Done log rather than performed here.
- **`CLAUDE.md` corrected:** § Known defects § Security, the plaintext-`!=` bullet (now
  `hmac.compare_digest`, still plaintext at rest — reworded, not removed); § Architecture § Auth,
  "Streaming is the opposite … gated only by `network_access_allowed`"; the "hidden channels are
  unlistable yet streamable" bullet (closed on relay-served surfaces; HDHR's separate defect
  explicitly untouched).

### PR 6 — `migration/phase1-next-source-events`

- `apps/proxy/api_urls.py` (D12): `next-source`, `release`, `events`, behind an `IsInternalRelay`
  permission class checking `X-Dispatcharr-Internal` (D11). DRF serializers for every request and
  response body, verified present in the drf-spectacular schema.
- `apps/proxy/control_plane.py`: `get_control_plane_base_url()` (D9), the next-source/release/events
  clients with the stated timeouts, one retry and the degraded fallback.
- `apps/proxy/live_proxy/url_utils.py:82,116,284` and `services/channel_service.py:159` (the four
  `Channel.get_stream()` call sites) call the control-plane client; the failover-time ORM reads in
  `get_alternate_streams` and `get_stream_info_for_switch` move behind the same call.
- **All 13 `log_system_event` call sites** listed in § What the code says post to the events client
  instead. `channel_service.py:869`'s `stream.save(...)` becomes a `stream_stats` event, and its
  three callers (`input/manager.py:1104,1407`, `channel_service.py:775`) post rather than write.
  This is the point at which the relay reaches zero ORM writes.
- `channel_stream:{id}` / `stream_profile:{stream_id}` added to `RedisKeys`; the relay's writes to
  both are deleted, leaving `Channel.get_stream()`/`release_stream()` as the only writers.
- `apps/connect/models.py`: `channel_buffering` added to `SUPPORTED_EVENTS`.
- WebSocket `relay_event` push on `channel_failover`/`stream_switch`/`client_disconnect`, emitted
  from the Django events view beside the existing `send_websocket_update` call pattern
  (`live_proxy/views.py:967`); `frontend/src/WebSocket.jsx` handles the new type and updates the
  channels store.
- New E2E `@contract` spec in `streaming-failover`: after a `dead-air` fault,
  `GET /api/core/system-events/` (`core/api_urls.py:29`) contains `channel_failover`, and the
  WebSocket receives `relay_event`.
- Unit tests: control-plane client timeout, retry and degraded-fallback behaviour with `requests`
  mocked; the next-source view reserves a slot exactly once per call; the events view turns a batch
  into the right `SystemEvent` rows.
- **Done:** the failover-events spec passes; **all 16 backend labels** green (touching
  `apps/api/urls.py` routes to `__all__` via `_PATH_ALIASES`);
  `grep -rn "log_system_event(\|\.save(\|\.objects\.create(" apps/proxy/ | grep -v tests` returns
  nothing.
- **`CLAUDE.md` corrected:** § Structural constraints, "exactly one ORM write" → zero as of this PR,
  with the `log_system_event` sites named; § Known defects, the `channel_stream:*`/`stream_profile:*`
  split-brain description (now Django-only); § Observing a channel, "No WebSocket event exists for
  stream switch, failover or client teardown" (now `relay_event`).

### PR 7 — `migration/phase1-control-api`

- `apps/proxy/relay_urls.py` / `relay_views.py` (D12): the five routes in § Architecture,
  `IsInternalRelay`-protected, DRF serializers throughout.
- `apps/proxy/relay_client.py`: `get_relay_control_base_url()` (D9). `channel_status`,
  `stop_channel`, `stop_client`, `change_stream`, `next_stream` and `/proxy/stats/` become thin
  wrappers over it, URLs and `IsAdmin` unchanged.
- The **six Django-side `ChannelService` call sites** move to `relay_client`: `apps/m3u/tasks.py:62`,
  `apps/m3u/api_views.py:295`, `apps/channels/api_views.py:105`, `:3249`, `:3816`, `:3831`. Per D10
  nothing under `apps/proxy/live_proxy/`, `apps/proxy/vod_proxy/` or `apps/timeshift/`'s streaming
  path imports `relay_client`, and the in-relay `ChannelService` is unchanged.
- `apps/channels/models.py`'s remaining relay-Redis reads (`_channel_proxy_is_active`,
  `_stream_assignment_is_reusable`, the client-count reads) route through `relay_client`;
  `_pick_channel_to_preempt` (`:476`) is **deleted**, not ported, along with the commented-out
  `return` at `:804`.
- `core/tasks.py:424`'s `fetch_channel_stats` and `core/utils.py:778,811`'s enrichment call
  `relay_client` instead of reading Redis. Both run in the `worker` role, which is why D9's resolver
  must produce a network address, not a loopback one.
- `apps/proxy/live_proxy/channel_status.py`: `build_live_channel_stats_data` moves behind the DRF
  serializer on the relay side, normalising `ffmpeg_speed` to a float and `state` to `null` rather
  than `'unknown'`.
- **`get_user_active_connections` (`apps/proxy/utils.py:232`) is split by owner.** It scans three
  key families and they do not have the same owner: `live:channel:*:clients:*` is relay-private
  state that Phase 3 moves out of Redis, while `timeshift:channel:*:clients:*` and
  `vod_persistent_connection:*` are written by Django-side handlers and stay where they are. PR 7
  replaces the live branch with a `relay_client` call to `GET /proxy/relay/channels`, whose payload
  already carries each channel's client list, and leaves the other two branches reading Redis
  directly. `attempt_stream_termination`'s `ChannelService.stop_client` call at `:193` becomes a
  `relay_client` call in the same change — after PR 5 its only caller is `authorize_stream`, which
  runs in the API process. Until PR 7 lands, the scan stays exactly as it is today, including from
  inside `authorize_stream` (stated in PR 5 so the intermediate state is not mistaken for the end
  state).
- **After this PR**, audit whether `apps/channels/models.py:6-7`'s module-level
  `from apps.proxy.live_proxy.redis_keys import RedisKeys` and the `ChannelMetadataField` /
  `ChannelState` import beside it can be deleted — **recommendation: yes** for `RedisKeys`, which
  removes the boot-cycle trap `CLAUDE.md` names. If a straggler remains, the PR names it and defers
  the removal to a documented follow-up rather than leaving the claim ambiguous.
- **Done:**
  `grep -rn "live:channel:\|channel_stream:\|stream_profile:" apps/channels/ apps/m3u/ core/ dispatcharr/ | grep -v tests`
  returns nothing (the grep names the control-plane modules explicitly rather than "outside
  `apps/proxy/`", because `apps/timeshift/`'s streaming views run in the relay process while its
  `stats_views.py` runs in the API — ownership here is per function, not per file);
  `apps.channels.tests` (including `test_ts_proxy_teardown.py`'s ten `ProxyServer` constructions),
  `apps.m3u.tests`, `apps.proxy.tests`, `apps.proxy.live_proxy.tests` and `core.tests` green;
  `E2E result` green with `Stats.jsx`'s existing frontend coverage unchanged, since URLs,
  permissions and response shape are unchanged apart from the two type fixes.
- **`CLAUDE.md` corrected:** § Structural constraints, the `channels/models.py:6-7` boot-cycle
  paragraph (state the audit's actual outcome); § Observing a channel, both the `ffmpeg_speed` and
  `state` bullets; § Known defects, "channel preemption is dead code" → deleted code, keeping the
  history.

### PR 8 — `migration/phase1-django-down-and-docs`

- New `streaming-split` E2E project (or a greybox spec), `@contract`, driving
  `instance.supervisorctl()` (added in PR 4) rather than shelling out, so
  `e2e/tests/guards/allowlist.ts` needs no new entry and `capabilities.spec.ts` stays green:
  `supervisorctl stop api-uwsgi` → an existing stream keeps flowing, a new tune returns one of
  `{502, 503, 504}`; `supervisorctl start api-uwsgi` → a new tune succeeds. The project does need
  `CONTAINER_LIFECYCLE` for the `instance` fixture itself, which is one allowlist line.
- Second scenario, same spec: `supervisorctl restart relay-uwsgi` → a client reconnecting within
  **N seconds, where N ≤ 30**, gets bytes. Thirty seconds is the ceiling: `stopwaitsecs=20` plus
  process start has to fit inside it or the restart is not bounded in any useful sense. The PR
  records the measured value. Both scenarios also carry a no-flush assertion, which is the
  observable form of D15 and would fail if any start path still wiped Redis DB 0: restarting
  `api-uwsgi` must leave an already-running stream flowing (its metadata, chunks and client set
  live in the same DB), and restarting `relay-uwsgi` must leave a **queued Celery task** intact and
  still executed afterwards (the broker keys live there too, and are exactly what
  `_flush_non_celery_keys` was written to spare).
- § Requirements the relay meets or carries, finalized with real PR numbers and merge SHAs.
- Remaining `CLAUDE.md` corrections not folded into an earlier PR, plus § Repository and direction
  gaining this spec beside the four investigation documents.
- `e2e/COVERAGE.md`: new rows for time-to-first-byte, Django-down, bounded relay restart, the
  authorize matrix and the modular role split — all five absent today.
- `docs/agents/issue-tracker.md`: the `resolveReviewThread` GraphQL example.
- Issues #87 and #95 closed, referencing PR 5.
- This spec's § Done log filled in.
- **Done:** both new scenarios pass in full-mode CI; `E2E result` and `Lifecycle result` green;
  `e2e/tests/guards/capabilities.spec.ts` passes with the widened allowlist (it fails naming the
  offender if the new file reaches for a capability it did not declare).

## Requirements the relay meets or carries

Phase 0's § Carried, not fixed table, with a status column now that Phase 1 exists to answer it.

| Requirement | Status after Phase 1 | Where |
|---|---|---|
| The relay's own stores bind to loopback or an internal network by default, never `0.0.0.0`, with no default credential. | **Still carried.** `docker/docker-compose.yml:191`'s `5436:5432` publish as `dispatch`/`secret` is deliberately untouched by PR 4. | — |
| `Host`/origin validated, deny-by-default, not conditioned on a debug flag. | **Still carried.** `ALLOWED_HOSTS=["*"]`, `CORS_ALLOW_ALL_ORIGINS=True`, `CSRF_TRUSTED_ORIGINS=["http://*","https://*"]` untouched. | — |
| Any credential the relay stores or compares is hashed or constant-time compared, never plaintext-equality. | **Partially met.** The XC password compare becomes `hmac.compare_digest` (PR 5) and the internal token is `hmac.compare_digest`-checked from day one (PR 5/6). XC passwords remain **plaintext at rest** in `custom_properties["xc_password"]` — out of scope (ADR 0005). | PR 5, PR 6 |
| A request timeout and a drain-on-shutdown from day one. | **Met as a timeout, bounded rather than graceful as a shutdown.** `harakiri = 120` on the API (PR 4) is the first request timeout this codebase has run in production. The relay gets a bounded restart via supervisord `stopwaitsecs=20` inside a 45s `stop_grace_period` (PR 3/4), not a drain: in-flight streams still drop and players reconnect, exactly as the route page's "Honest limits" states. | PR 3, PR 4 |
| The relay's stream endpoint is authorized by a Django-minted, short-lived, signed URL; the UUID alone is not a capability. | **Reworded per ADR 0005, and met in the reworded form.** No signed URL exists or is planned for Phase 1; the UUID stays the public, cacheable identifier. Authorization is Django's decision, made once per tune (PR 5), never per byte. | PR 5 |
| The relay's logging never emits a provider URL or header set except through the redaction helpers. | **Met, and extended.** No new logging site bypasses `redact_url`/`redact_headers`, and PR 5 additionally redacts the DVR ffmpeg argv, which would otherwise print the internal token past a guard that does not match it. | PR 5 |
| *(new)* Every long-lived stream surface authorizes through one function; a channel with `hidden_from_output` or `is_adult` is not streamable by UUID alone. | **Met.** `authorize_stream`, both callers (PR 5). Closes #87 and #95. | PR 5 |
| *(new)* The relay performs zero ORM writes. | **Met.** The `stream.save(...)` and all 13 `log_system_event` calls move to Django via the events batch. | PR 6 |
| *(new)* The relay's Redis keys have exactly one writer, and no control-plane code reads them. | **Met.** `channel_stream:*`/`stream_profile:*` get a single writer in PR 6; every other relay key was already single-writer. PR 7 removes the control plane's *reads* too, including the live branch of `get_user_active_connections`, which moves to `GET /proxy/relay/channels`. The timeshift and VOD branches of that same scan keep reading Redis — those key families are written by Django-side handlers, so they are not relay state and are not in scope for this row. | PR 6, PR 7 |
| *(new)* A restart of the control plane does not disturb a running stream. | **Met.** Nothing flushes Redis in any role (D15): `scripts/wait_for_redis.py` becomes wait-only, and AIO's Redis starts empty because it is non-persistent, not because anything wipes it. A modular `web` or `worker` restart therefore leaves a running relay's keys untouched, and PR 8's bounded-restart scenario asserts it. | PR 3, PR 8 |
| *(new)* Django and the relay authenticate each other on every internal call, and the relay never trusts an unauthenticated header. | **Met.** Two context-separated HMACs of `SECRET_KEY`, `hmac.compare_digest` on both, covering relay→Django, Django→relay, the DVR and the nginx trust marker (D11). | PR 5, PR 6, PR 7 |

## Testing

- **Time to first byte through nginx** (`streaming`, `@contract`, PR 2, N ≤ 10 s) — must exist
  before PR 4's routing change and still pass after it.
- **SPA three-segment route still serves the SPA** (`streaming`, `@contract`, PR 2) — the regex
  trap D7 identifies.
- **Modular role split** (`docker/tests/test-puid-pgid.sh` `test_role_split`, PR 4) — api, relay and
  worker containers on one network; TS bytes read through the api container's nginx. The only test
  of the cross-container relay hop; `scripts/e2e_up.sh` stays AIO-only.
- **Authorize matrix** (`streaming`, `@contract`, PR 5) — `hidden_from_output` and `is_adult` 403 on every
  relay-served surface, anonymous-plus-valid-UUID still streams, forged trust headers 403.
- **Failover produces events** (`streaming-failover`, `@contract`, PR 6) — `dead-air` fault →
  `channel_failover` in `GET /api/core/system-events/` and a `relay_event` WebSocket message.
- **Django down / bounded relay restart** (`streaming-split`, `@contract`, PR 8, N ≤ 30 s) — plus
  the unrelated-stream and queued-Celery-task assertions that pin D15.
- **Unit tests**: the authorize matrix and `_dvr_redact_cmd` (PR 5); control-plane client
  timeout/retry/fallback and the next-source single-reservation guard (PR 6); `relay_client`
  timeouts and the status serializer (PR 7); `get_dvr_stream_base_url` (PR 4, extending
  `test_dvr_port_resolution.py`); the events view's batch-to-rows mapping (PR 6).
- **Existing coverage this spec relies on rather than re-proves**: G4's `streaming` and
  `streaming-failover` projects (TS alignment, shared upstreams, mid-stream switch, all three
  failover triggers, all three Stream Profile architectures, Output Profile sharing). None change
  shape here, so their continuing to pass after PR 4 is itself the evidence the split preserved
  relay behaviour. `apps/channels/tests/test_ts_proxy_teardown.py` and
  `apps/proxy/live_proxy/tests/test_property_*.py` are untouched, because no PR here changes relay
  internals.

## Documentation

Per-PR `CLAUDE.md` corrections are listed under each PR. Additionally:

- `CONTEXT.md` glossary and ADR 0005 — PR 0 (this branch), not deferred.
- `e2e/README.md`'s two stale quarantine-file lines (`:104`, `:111`) and the stale
  `Lifecycle result` line (`:780`) — PR 2, the first PR touching E2E docs.
- `e2e/COVERAGE.md` rows for TTFB, Django-down, bounded relay restart, the authorize matrix and the
  modular role split — PR 8.
- `docs/agents/issue-tracker.md`'s missing `resolveReviewThread` example — PR 8.

## Done log

Filled in as PRs merge. Empty at spec-writing time.

| Item | PR | Merged |
|---|---|---|
| Supervisor dependency | — | — |
| TTFB + SPA-three-segment tests | — | — |
| Supervisord | — | — |
| Process split | — | — |
| Authorize hop | — | — |
| Next-source + events | — | — |
| Control API | — | — |
| Django-down + docs | — | — |

## Risks

- **PR 3 is the riskiest PR in the sequence, and its risk is in the test harness, not the product.**
  Replacing the entrypoint's process management invalidates the readiness marker both bash suites
  match on, at four sites, plus two log assertions that come from the deleted Celery entrypoint. Get
  any of the six wrong and the suites time out rather than fail informatively. The mitigation is
  that `Lifecycle result` runs in full mode on a `migration/**` branch, so the mistake surfaces on
  the PR itself.
- **`test_readonly_rootfs` cannot prove the read-only property.** It skips today and its failure
  path is a `log_skip`. PR 3 substitutes a static grep over the supervisord configs, which proves
  the paths are right but not that the container boots read-only. Accepted: making that scenario
  pass is a separate piece of work about tmpfs mounts, not about supervision.
- **The `^~` audit (D7) is only as complete as the routes enumerated here.** A future route added
  under a plain-prefix location without `^~` falls behind the XC regex again if it happens to be
  exactly three segments with no trailing slash. Nothing catches this automatically; a lint rule
  over `nginx.conf` is a follow-up issue, not a PR here.
- **`harakiri = 120` is bounded by observation, not measurement across every catalogue size.** A
  provider with an unusually large catalogue could still exceed it on `player_api.php`.
  `DISPATCHARR_API_HARAKIRI` exists so that is a config change.
- **The degraded next-source fallback is unenforced by design** — a failover while Django is down
  can exceed `max_streams` on the cached candidate's profile. Accepted: refusing to fail over at all
  is worse for the viewer, and the `channel_error` event on recovery makes it visible after the fact.
- **`gevent = 1600` on one worker preserves the connection ceiling but not the CPU headroom.** Four
  workers meant four OS threads; one relay worker is one. At the route page's measured ~4% of a core
  per channel this is not the binding constraint, but it is a real change and the first place to
  look if the relay saturates.
- **Deleting `entrypoint.celery.sh` changes what a `worker` container does before it starts Celery.**
  The waits are lifted verbatim, but the shared entrypoint also runs PUID/PGID setup and TLS key
  fixup that the Celery entrypoint did differently. `test-tls-postgres.sh`'s
  `test_modular_full_tls_celery` is the test that catches a divergence, which is why PR 3 updates it
  rather than skipping it.
- **Eight `migration/**` PRs plus one `docs/` PR is a long queue under the Main ruleset's strict
  up-to-date policy** — each PR re-runs the full aggregate set once the one ahead of it merges.
  Accepted, as Phase 0 accepted it; fewer, larger PRs were rejected because routing changes what is
  tested and PR 3 in particular has to be reviewable on its own.
- **`_pick_channel_to_preempt`'s deletion removes code, not the underlying feature gap.** Channel
  preemption stays unimplemented after Phase 1, as before. Called out so the deletion is not read as
  a feature decision.

## Non-goals — deliberately out of scope

- **A Go relay** (Phase 2). No PR here touches `apps/proxy/live_proxy/`'s internals — only what
  calls into and out of the process boundary around them.
- **HLS output.** `_OUTPUT_FORMAT_MANAGERS` still registers only `fmp4`; `apps/proxy/hls_proxy/`
  stays dead and unrouted.
- **Removing Redis from the video path** (Phase 3). The ring buffer, ownership lease and follower
  code are unchanged; PR 7 makes the relay's keys *private*, which is what makes Phase 3 possible
  later, not what performs it now.
- **Fencing the ownership lease.** `StreamBuffer.add_chunk()` still writes with no fencing token.
  One relay worker makes the interleave unreachable in practice, which is a deployment property,
  not a fix; the defect stays on the books for Phase 2/3.
- **Remote-access hardening** (wildcard hosts, CORS, CSRF, TLS, XC password hashing at rest) — see
  § Requirements' "still carried" rows; the route page's § B gives this its own future spec.
- **Role-scoped urlconfs.** D1 keeps one urlconf everywhere; a role-aware urlconf is Phase 2+.
- **HDHomeRun authorization.** `apps/hdhr/api_views.py`'s four `AllowAny` views performing no
  authorization at all is a *separate* defect from the `hide_adult_content` gap PR 5 closes, with a
  different fix; not touched.
- **`healthz`, metrics, or a Docker `HEALTHCHECK`.** PR 8's tests observe behaviour through the
  existing status surface and `supervisorctl status`.
- **Adaptive bitrate or any new transcode capability.** Output Profile's existing shared-per-
  `(channel, profile)` transcode is unchanged.
- **Channel preemption revival.** `_pick_channel_to_preempt` is deleted, not fixed.
- **A second relay, sharding, or the canary switch itself.** The relay-name header and the nginx
  `map` exist so Phase 2 is a map entry and a settings change; adding a second relay is not this
  spec's work.
- **The published Postgres port on `5436`.** Repeated here for emphasis: PR 4 edits
  `docker/docker-compose.yml` and deliberately leaves line 191 alone.
