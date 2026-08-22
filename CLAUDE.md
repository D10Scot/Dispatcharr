# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository and direction

This checkout is a fork. `origin` is `D10Scot/Dispatcharr` (push here); `upstream` is
`Dispatcharr/Dispatcharr` (fetch only — its push URL is set to the string `DISABLED`). Upstream
targets its `dev` branch; this fork works on `main`.

The fork exists to **extract the streaming relay from the Django web workers into its own
process** (control plane / data plane split), not to rewrite the product. Scope fence: the relay
is ~6k of ~137k lines. Phase 0 harden in place → Phase 1 extract the boundary still in Python →
Phase 2 optionally reimplement in Go → Phase 3 delete Redis from the data path. Stopping after
Phase 1 is a legitimate outcome. Resist widening the scope; that is the main way this fails.

Four prior investigation documents hold the detail behind the summaries below. Read the relevant
one before deep work rather than re-deriving it:

- **Teardown** (how it actually works, line by line) — https://claude.ai/code/artifact/7e7330e2-2fad-4e9d-a0b3-22be18c568ae
- **Due diligence** (gaps, defects, governance) — https://claude.ai/code/artifact/6dddf987-6135-480c-8b77-c5ad621a8c06
- **Test-suite report** (coverage, what's untested) — https://claude.ai/code/artifact/3ced4b71-c684-47e0-bf2f-b4ee1b9826cc
- **Splitting the Planes** (the extraction proposal) — https://claude.ai/code/artifact/149fb554-d140-4e13-abaf-2416429b2e3f

All findings below were verified at commit `fd413f0c` (v0.29.0). Line numbers drift.

## Test hooks (this fork only)

`.claude/settings.json` registers a `PostToolUse` hook on `Write|Edit` that verifies whatever
file was just edited. Every check is scoped to that file, so none of them depends on the repo's
pre-existing backlog being cleared first.

| Trigger | Check | Blocks? | Cost |
|---|---|---|---|
| `*tests/test_*.py` | run the whole test package | yes | 2–8s |
| `frontend/**/*.test.jsx` | run that file under vitest | yes | 1.8s |
| `*/models.py` | `makemigrations --check` for that app | yes | 2s |
| `live_proxy/{constants,redis_keys}.py` | `manage.py check` | yes | 1s |
| `frontend/**/*.jsx` | `eslint` on that file | no | 0.3s |
| any `*.py` | credential-logging grep | no | instant |

Blocking failures exit 2, which feeds the output back. Advisory findings and "could not run" both
exit 0 but are stated loudly.

The migration check resolves the Django app label through `apps.get_app_configs()` rather than
guessing from the directory (`.claude/hooks/_pending_migrations.py`). This matters: `apps.channels`
has the label `dispatcharr_channels`, and the plausible guess `channels` is a **different
installed app** — the Django Channels library — which reports "no changes" and exits 0. Guessing
fails silently.

The boot check exists because `apps/channels/models.py:6–7` imports those two leaf modules at
module level; adding a cycle there was verified to break `manage.py check` for every command.

eslint is advisory rather than blocking because 112 pre-existing errors across 76 files would
mean blocking punishes touching legacy code rather than improving new code. One `note` → `block`
swap in the script flips it.

Backend work runs in a local container (`dispatcharr-testrunner`, from
`ghcr.io/dispatcharr/dispatcharr:latest`, holding PostgreSQL and Redis).

The repo is bind-mounted **read-only** at `/repo`, so the container always sees the live working
tree — there is no sync step, and nothing it does can write into your checkout. PostgreSQL's data
lives in the `dispatcharr-hookdb` named volume, not a bind mount: PG will not run on a macOS bind
mount, and keeping it in a volume means rebuilding the container does not repay `initdb`.
Measured: a clean package (`apps.channels.tests`, 420 tests) takes 3.6s end to end, a frontend
file 1.8s, a full container rebuild 2.0s.

Two things about it are deliberate and measured, not incidental:

- **Redis is flushed before every backend run.** Outcomes here depend on cache state left by
  previous test *processes*: `apps.timeshift.tests` exits 0 with a warm Redis (3/3 runs) and
  exits 1 flushed (2/2). Flushing matches what CI provisions.
- **The whole package runs, not the edited module**, because that is what CI runs. A module run
  skips the tests that warm shared state, so it can fail where CI passes and vice versa.

If the container is not running (or Docker is down) the hook says so loudly and exits 0 rather
than skipping silently. When that happens, say the tests did not run — do not describe the work
as verified. Bring it back with `.claude/hooks/start-test-container.sh`, which is idempotent and
takes ~2s. The `-e DISPATCHARR_TEST_CONTAINER` / `_IMAGE` / `_DB_VOLUME` env vars override the
defaults.

A second hook, `PreToolUse` on `Bash(git commit*)`, gates commits on the tests covering whatever
is **staged** — source files included, not just test files. It derives backend labels from the
repo's own `scripts/ci_backend_test_labels.py`, so it runs exactly what CI would run for the same
diff, and runs the whole frontend suite if anything under `frontend/` is staged. `git commit -a`
is handled (it diffs against `HEAD` rather than the index). Infrastructure failures warn rather
than block — a gate that fails closed on a stopped Docker just gets bypassed.

Baseline at the time of writing: **15 of 16 backend packages pass**, 1,787 tests, 34s for the
full sweep. The exception is `apps.timeshift.tests` (`connection is closed`), so editing or
committing anything that maps to it will block until that is fixed.

Note the mapping inherits the two routing defects described under Testing below — a change to
`live_proxy/server.py` selects only `apps.proxy.live_proxy.tests`, and `apps/vod/` still routes
to `apps.output`. That is deliberate: the gate should not disagree with CI. Fixing
`test_discovery.py` fixes both at once.

## Commands

### Backend

```bash
uv sync                                   # Python 3.13+, uv + pyproject
uv run python manage.py migrate
uv run python manage.py runserver

python manage.py test                     # full suite (custom runner; see Testing)
python manage.py test apps.channels.tests
python manage.py test apps.channels.tests.test_recording_pipeline
python manage.py test apps.channels.tests.test_recording_pipeline.SomeTests.test_x
python manage.py test --shuffle 12345     # reproduce order-dependent failures
TEST_USE_SQLITE=1 python manage.py test   # no-Postgres fallback; PG-only tests self-skip

uv run python manage.py makemigrations <app>
```

`manage.py` rewrites `DJANGO_SETTINGS_MODULE` to `dispatcharr.settings_test` for the `test`
subcommand only. **Never** pass `--settings=dispatcharr.settings` to `test` on a live instance —
it points the suite at the production database.

Tests need Postgres and Redis. `scripts/ci_bootstrap_backend.sh` is what CI runs: it boots an
internal Postgres + Redis inside the base image and `exec`s `manage.py test --keepdb "$@"`. It is
the fastest way to reproduce CI if you have the base image (`ghcr.io/<owner>/<repo>:base`, or
`:base-dev` for non-`main` branches); it assumes that image's layout (`/dispatcharrpy` venv,
`/usr/lib/postgresql`).

### Frontend

```bash
cd frontend
npm install
npm run dev     # Vite on :9191, proxies /api -> :5656 and /ws -> :8001
npm run build
npm test        # vitest --run
npm run lint    # eslint — currently 112 errors / 55 warnings; disabled in CI
```

No `npm run format` script exists despite CONTRIBUTING.md referencing it; Prettier is a
devDependency, so use `npx prettier --write`.

### Docker

`docker/docker-compose.dev.yml` (dev), `docker-compose.yml` (modular), `docker-compose.aio.yml`
(single container). `DISPATCHARR_ENV` picks `aio` / `modular` / `dev`.
`docker/tests/test-puid-pgid.sh` (20 scenarios) and `test-tls-postgres.sh` (8) are real container
integration suites — the best integration testing in the repo, wired into no workflow.

## Architecture

Django 6 + DRF, React 19 SPA on the same origin, Celery for async work, Redis for
broker/cache/channel-layer **and the video path**, PostgreSQL for durable state.

Roughly a third of the backend is two apps: `apps/proxy` (22.3k LOC — live/VOD/HLS relay, stats)
and `apps/channels` (20.8k — channel/stream models, DVR, EPG matching). Then `apps/epg` (14.3k),
`apps/timeshift` (12.8k, Xtream catch-up), `apps/m3u` (11.9k), `core` (7.4k, settings registry +
profiles + system events), `apps/output` (5.8k, M3U/XMLTV/Xtream export), `apps/vod` (5.8k),
`apps/plugins` (2.9k), `apps/hdhr` (0.3k). `apps/dashboard` is 77 lines with no API surface.

### One container, several processes

`docker/uwsgi.ini` runs uWSGI with everything else as `attach-daemon` — including Redis:

- **uWSGI**: 4 workers × `gevent = 400` greenlets, `gevent-early-monkey-patch = true` plus
  `dispatcharr/gevent_patch.py` imported before app code.
- **Celery** `default` (prefork, `--autoscale=6,1`) and **`dvr`** (`--pool=threads
  --concurrency=20`, for the long-running `run_recording`). Routing in `dispatcharr/celery.py`.
- **Celery beat** (DB scheduler, so schedules are UI-editable). The static schedule is short;
  M3U/EPG/VOD refresh are per-account `django_celery_beat` rows.
- **Daphne** :8001 for WebSockets. **Redis** and **PostgreSQL** in the AIO image.

Consequences that constrain almost every change in `apps/proxy`:

- Four worker processes ⇒ **no channel state can live in Python memory**.
- `gevent-early-monkey-patch` ⇒ every `threading.Thread` in the proxy (27 of them) is really a
  greenlet on one OS thread shared with the 400 request greenlets. One blocking call stalls the
  hub — the maintainers have already hit this (`server.py:1740` docstring: *"blocked on
  logging"*).
- `StreamManager` spawns ffmpeg with **`os.posix_spawn`**, not `subprocess.Popen`, with a
  hand-rolled Popen-compatible wrapper, because all `fork()`-based approaches hang in gevent's
  `_before_fork` handler (`input/manager.py:786–870`). Do not "simplify" this back to `Popen`.
- The **DB backend differs per process**: uWSGI gets `django-db-geventpool` (MAX_CONNS=8,
  REUSE_CONNS=3), Celery and Daphne get plain `django.db.backends.postgresql` because they are
  deliberately not monkey-patched (`settings.py:233–264`).
- nginx uses **`uwsgi_buffering off`** on `/proxy/` — load-bearing. A past bug used
  `proxy_buffering off`, the wrong directive family for a `uwsgi_pass` upstream, so nginx spooled
  live TS to disk.
- `docker/entrypoint.aio.sh` starts gunicorn and is referenced nowhere. Legacy.

### Where state lives

| Store | Holds | Lifetime |
|---|---|---|
| PostgreSQL | Channels, streams, accounts, VOD, users, recordings, settings, events | Durable |
| Redis keys | Ownership leases, channel metadata hash, client sets, counters, switch requests | Seconds–minutes, TTL'd |
| Redis ring buffer | **The actual video bytes**, ~256 KB chunks (188 × 1361, TS-aligned) | 60s TTL |
| Redis pub/sub | `live:events:*` — switch, stop, client connect/disconnect | Ephemeral |
| Redis broker | Celery queues, Channels layer, Django cache | Ephemeral |

All five share **DB 0**, so video memory pressure takes out the task queue and cache with it.
`scripts/wait_for_redis.py:103` does a `flushdb()` on every AIO boot; the modular variant
preserves only Celery prefixes and has no instance scoping.

### The video path

Three **Stream Profiles** exist as locked built-ins, and they are three different architectures:

| Profile | What happens | Bytes through Dispatcharr | Live failover |
|---|---|---|---|
| Redirect | validate URL, then 302 the client at the provider | no | none after connect |
| Proxy | raw HTTP passthrough into the ring buffer, no subprocess | yes | dead-air only |
| FFmpeg / VLC / Streamlink | spawn process, read stdout, parse stderr | yes | full |

The default FFmpeg profile is `-c:v copy -c:a copy -f mpegts pipe:1` — a remux, not a transcode.

Do not confuse **Stream Profile** (how we talk *upstream*) with **Output Profile** (an optional
transcode applied *downstream*, reading the shared buffer on `pipe:0`). Output profiles are
shared per `(channel, profile)` across the cluster, so ten clients wanting AC3 cost one ffmpeg.
Container formats: MPEG-TS (default, no output-side ffmpeg at all) and fMP4. **There is no HLS
output** — `_OUTPUT_FORMAT_MANAGERS` registers only `fmp4`, and the 1,206-line
`apps/proxy/hls_proxy/` is dead (URLconf never included, `apps.py` says so). HLS *upstreams* are
handled by forcing the channel to the ffmpeg profile.

**Channel ownership.** One uWSGI worker owns a channel's upstream connection, elected by
`redis.set(f"live:channel:{id}:owner", worker_id, nx=True, ex=30)` (`live_proxy/server.py:463`).
The owner runs `StreamManager` and writes chunks; other workers attach as followers, serve their
own clients from the same Redis keys, and ask the owner to act via `live:events:{id}` pub/sub.
`_ensure_owner_or_stop()` runs at the top of every main-loop iteration.

**Buffer mechanics** (`input/buffer.py:65–134`): realigns to 188-byte TS packets carrying a
remainder in `_partial_packet`; accumulates ~256 KB then `INCR` + one pipelined
`SETEX`/`ZADD`/`ZREMRANGEBYSCORE`/`EXPIRE`. **The index is monotonic for the life of the channel
and is never reset by a stream switch** — which is exactly why a switch doesn't touch clients.
New clients start ~5s behind live (`new_client_behind_seconds`), located via the timestamp zset.

**Failover has three independent triggers** funnelling into `_try_next_stream()`:

| Trigger | Signal | Threshold | Available in |
|---|---|---|---|
| Buffering | ffmpeg stderr `speed=` | < 1.0× sustained > 15s | **ffmpeg only** |
| Dead air | wall clock since last byte | > 10s, 3× @ 5s | all proxied modes |
| Connect failure | EOF/exception on connect | 3 within 30 min | all proxied modes |

Two things about the buffering detector that are not obvious from the code:

1. It is **ffmpeg-exclusive**. Proxy and Redirect profiles have no stderr, so `buffering_speed`
   and `buffering_timeout` are silently inert. Nothing in the UI surfaces this.
2. `speed=` is a **cumulative average since process start**, not an instantaneous rate. Providers
   front-load media at connect (~40s measured on a live install), and the detector cannot arm
   until that banked lead is burned. Measured time-to-failover is ~55s for a hard stall, not 15s
   — by which point the dead-air watchdog (~25s) has already won. The buffering path only earns
   its keep on *partial* degradation. Raising `buffering_speed` above 1.0 is the lever that
   moves; lowering `buffering_timeout` barely helps.

Thresholds are snapshotted in `StreamManager.__init__`, so UI changes don't affect running
channels. There is **no quality measurement at all** — bitrate is parsed and displayed but never
thresholded; no continuity-counter, PCR-gap or discontinuity checking.

VOD is a deliberately different architecture: no ring buffer (`iter_content(8192)` passthrough),
one upstream per session, stateless across workers (session rehydrated from Redis by URL path),
pre-stream failover only. Its stream counter uses four Lua scripts that bypass the metadata lock
on purpose — that was a real bug fix, pinned by `vod_proxy/tests/test_vod_lock_contention.py`.

### Auth posture — two opposite defaults

The REST API is **deny-by-default**: `DEFAULT_PERMISSION_CLASSES = ["apps.accounts.permissions.IsAdmin"]`.
A view is admin-only unless it explicitly opts down. Authorization runs on `user_level`
(Streamer 0 / Standard 1 / Admin 10) plus M2M to `ChannelProfile`; Django's own
Group/Permission tables are vestigial.

The streaming endpoints are the opposite: `stream_ts` is `@permission_classes([AllowAny])` gated
only by `network_access_allowed(request, "STREAMS")`, and the STREAMS ACL defaults to
`0.0.0.0/0`. Anyone on an allowed network who knows a channel UUID can stream anonymously. This
is a deliberate concession — Plex/Jellyfin/TiviMate can't carry a bearer token on a tuner URL —
and the WebSocket consumer is correspondingly careful to mark stats events admin-only, because a
UUID is a credential. **A channel UUID is a secret. Treat it as one.**

If you touch the stream endpoint during the extraction, the intended replacement is a
Django-minted short-lived HMAC-signed URL the relay validates statelessly.

### Routing

`dispatcharr/urls.py` mounts Xtream-compatible endpoints at the site root (`player_api.php`,
`get.php`, `/<user>/<pass>/<id>`) **before** the SPA catch-all, so root-level route additions can
shadow the frontend. Client-facing surface: `/proxy/ts/stream/<uuid>`, `/proxy/vod/...`,
`/proxy/catchup/...`, `/output/m3u`, `/output/epg`, `/hdhr/...`, plus the XC API's 17 actions.

No SSDP/UPnP discovery exists for the HDHomeRun emulation — clients must be pointed at the URL by
hand. The generated M3U emits no `catchup=` attributes; catch-up is advertised only via XC
`tv_archive` fields.

### Events and plugins

Every interesting transition calls `log_system_event()` (`core/utils.py:751–825`), which writes a
`SystemEvent` row and fans out to the Connect subsystem (webhook / script / API handlers). The
event vocabulary is a fixed dict at `apps/connect/models.py:3–21` and includes
`channel_buffering`, `channel_failover`, `channel_reconnect`, `stream_switch`, `channel_error`.
Under gevent, dispatch is spawned on its own greenlet so a slow webhook can't stall teardown.
**This is the extension point to use before adding polling anywhere.**

Plugins live outside `INSTALLED_APPS` in `/app/data/plugins/<name>/` (`plugin.json` +
`plugin.py`); see `Plugins.md`. `autodiscover_tasks()` can't see them, so `dispatcharr/celery.py`
runs `PluginManager.discover_plugins()` in `worker_process_init` — per forked child, deliberately
not in the parent, so children don't inherit DB connections. Plugins execute arbitrary Python
in-process, unsandboxed, with 12 tests.

### Frontend

`frontend/src/store/*.jsx` — Zustand, one store per domain (new global state goes here, not React
Context). `frontend/src/api.js` — all HTTP calls; components must not call fetch/axios directly.
`frontend/src/WebSocket.jsx` — one consumer on `/ws/` carrying a generic `updates` group.
Mantine 8; do not add UI libraries. `api.js` and `WebSocket.jsx` are the two largest files in the
tree with **no test files at all** — they are mocked away everywhere else.

## Structural constraints on refactoring

- **The apps are a mesh, not a stack.** 367 cross-app imports over 50 edges, with four cycles
  centred on `channels` (97 out / 67 in). Extracting the relay pulls in `channels`, which pulls in
  `m3u` and `epg`, which reach back. There is no clean seam.
- `apps/channels/models.py:6–7` imports `RedisKeys` and `ChannelMetadataField` from
  `apps.proxy.live_proxy` at **module level**. A models module — loaded by every migration and
  management command — depends on the streaming package. It survives only because those two are
  leaf modules. Add one import to `live_proxy/constants.py` and Django stops booting.
- 602 function-local imports (68 in `channels/tasks.py`) — the workaround for the above.
- Good news for extraction: across all non-test `apps/proxy/` there is **exactly one ORM write**.
  Everything else goes to Redis. The obstacle is 24 reverse-import sites and read dependency on
  14 model classes, not transactional coupling.
- Complexity is concentrated, not diffuse: median function is 14 lines, but 49 functions exceed
  200 lines and 111 functions hold 43% of all function lines. Worst offenders:
  `fetch_schedules_direct()` (1,323 lines / 235 branches), `run_recording()` (1,139 / 257, and 47
  separate `try` blocks), `sync_auto_channels()` (1,010). `apps/timeshift/views.py` is long but
  well-factored — it is not the problem.

## Known defects and traps

Verified. Do not "fix" the surrounding code without knowing these are already there, and do not
reintroduce them in new code.

**Security (treat the first as an incident, not a backlog item):**
- Provider credentials are logged at **INFO**. `apps/proxy/vod_proxy/views.py:628` logs the full
  request path and the entire header dict; Xtream URLs carry the password in the path.
  `apps/m3u/tasks.py:3084` logs upstream URLs. `apps/channels/tasks.py:1577` and `:1633` log the
  DVR stream base URL and stream URL at INFO — a third site, found by the credential-logging
  hook, not in the original audit. Anyone who has shared a support log has shared working
  credentials.
- `docker/docker-compose.yml` publishes Postgres on `5436:5432` (all interfaces) as
  `dispatch`/`secret`.
- `settings.py:72` `ALLOWED_HOSTS = ["*"]`, `:447` `CORS_ALLOW_ALL_ORIGINS = True`, `:448`
  `CSRF_TRUSTED_ORIGINS = ["http://*", "https://*"]` — none conditioned on `DEBUG`.
- Xtream passwords stored plaintext in `custom_properties["xc_password"]`, compared with `!=`.
  API keys looked up by plaintext value with no scoping.

**Correctness:**
- **The ownership lease is time-bounded, not fenced.** `StreamBuffer.add_chunk()` writes with no
  ownership check and no fencing token. Two owners interleave chunks at alternating monotonic
  indices — readers see a gapless sequence and decode a spliced stream, with every consistency
  check passing. The lease also **fails open** three ways in `live_proxy/server.py` (`:465`,
  `:477`, and `_execute_redis_command` swallowing exceptions to `None`). `release_ownership` does
  GET→compare→DELETE non-atomically; `extend_ownership` does GET (`:538`) → EXPIRE (`:563`)
  non-atomically. If you carry this design forward, put the lease token in the write path via Lua
  and never fail open.
- Channel preemption is dead code: `_pick_channel_to_preempt()` is fully implemented, but
  `apps/channels/models.py:795–804` has the `return` commented out. The log line fires and
  nothing happens.
- `get_preferred_region_code()` can never succeed — `core/migrations/0020` deleted the settings
  row it reads. EPG matching runs with no regional weighting, silently. (The live accessor
  `CoreSettings.get_preferred_region()` works; the matcher just doesn't call it.)
- **Both scheduler migration reverses are broken.** `apps/epg/migrations/0007` deletes *every*
  `IntervalSchedule` and `PeriodicTask` in the system; `apps/m3u/migrations/0006` filters
  `IntervalSchedule` by `name`, a field it has never had, so it raises `FieldError`. 16 migrations
  have no reverse at all. Nothing in CI exercises reverse migrations or
  `makemigrations --check`.
- The channel-authorization filter is copy-pasted across **eight** sites; one
  (`output/views.py:593`) uses `"channels__user_level": 0` instead of `__lte`. `hide_adult_content`
  is applied in listing paths and **not** in `live_proxy/views.py`, `timeshift/views.py` or
  `hdhr/api_views.py` — hidden channels are unlistable but still streamable. The one extracted
  helper, `_user_can_access_channel`, is at `apps/timeshift/views.py:771`.
- The channel-stopping key is written with `setex(..., 60, ...)` on five paths and
  `setex(..., 30, ...)` on three. That is a race generator.
- `MAX_STREAM_SWITCHES` doesn't bound buffering-triggered switches — they're called from the
  stderr greenlet, bypassing the main loop's counter.
- The fMP4 generator's `_is_timeout()` lacks the `url_switching` exemption the TS generator has,
  so fMP4 viewers can be dropped at 40s during a slow failover.

**Dead or unwired:** `apps/proxy/hls_proxy/` (1,206 lines), `dispatcharr/persistent_lock.py` (no
callers; its `refresh()` sets `self.has_lock = False` on the success path, and an instance
attribute shadows the `has_lock` method), `_attempt_health_recovery()` (`manager.py:1651`),
`head_vod()` (no route), `MAX_HEALTH_RECOVERY_ATTEMPTS` / `MAX_RECONNECT_ATTEMPTS` /
`MIN_STABLE_TIME_BEFORE_RECONNECT` in `config.py:117–119` (the real values are bare literals in
the health-monitor body), `M3UAccount.stream_profile`, `HDHRDevice.tuner_count`.

**Style debt worth knowing before you add to it:** 236 exception handlers whose entire body is
`pass` (17% of 1,376), 21 bare `except:`, 848 broad `except Exception`. Six ways to obtain a
Redis client and five ways to read configuration, including 102 raw `os.environ` reads in
application code. Two TODOs in the whole repository and no FIXME/HACK/XXX — the debt is
invisible, not absent.

**Operationally:** no metrics, no `/healthz`, no readiness probe, unstructured logs. `die-on-term`
with no drain and no application shutdown hook, so every deploy drops every viewer and leaves
Redis state behind. `os.posix_spawn` is called with no `setsid`/`PDEATHSIG`, so an ffmpeg blocked
on a stalled upstream survives worker death holding a provider slot. No `harakiri` — and it can
never be enabled while the relay shares a process with the API.

## Testing

`dispatcharr/test_runner.py` expands a label-less `manage.py test` using
`dispatcharr/test_discovery.py`, which AST-parses `INSTALLED_APPS` (no Django import) and finds
every `tests/` package. 16 labels; 130 backend test files (1,787 tests), 202 frontend files
(6,128 tests).

**CI never runs the suite in one process.** `.github/workflows/backend-tests.yml` runs each label
as its own matrix job in its own container (`max-parallel: 6`), so every test gets a fresh
interpreter and database. As of `fd413f0c` the full in-process run **fails** — four runs gave
7, 1, 1 and 8 failures with different sets each time. Every failing test passes in its shard.
The constant one, `apps.timeshift.tests.test_views.CatchupProxyTests.test_missing_session_id_redirects`,
dies on `psycopg.OperationalError: the connection is closed` — the proxy closes connections on
purpose (that's what `test_atomic_db_close.py` asserts) and the state leaks forward. The rest are
`SimpleTestCase` subclasses in `test_catchup_redirect.py` that reach the DB and only pass when an
earlier test warmed the `CoreSettings` cache. **A green CI run does not mean a green suite.**

The frontend suite passes in default order but fails under `vitest --sequence.shuffle`
(16 failures on one seed, 15 on another) — module mocks and store singletons leaking between
files.

**Two path-routing defects in `labels_for_changed_paths()`:**
- `_PATH_ALIASES` routes `apps/vod/` → `apps.output` only. `apps/vod/tests/` exists (7 files,
  1,285 lines) and never runs for VOD changes.
- The richest proxy tests live under `apps/channels/` — `test_ts_proxy_teardown.py` builds a real
  `ProxyServer` ten times. A change to `live_proxy/server.py` selects only
  `apps.proxy.live_proxy.tests`, so they're skipped precisely when the proxy is edited.

`_SHARED_PATH_PREFIXES` (`dispatcharr/`, `pyproject.toml`, `manage.py`, …) forces the full set.

**Coverage is 45.6% backend / 71.9% frontend lines, and inversely correlated with criticality.**
`hls_proxy` 0%, `plugins` 25%, `vod_proxy` 35.6%, `live_proxy` 38.5%, versus `timeshift` 78.7%.
`log_parsers.py` — which decides a stream is buffering — is at 20.4%. Test density per kLOC:
timeshift 63.7, proxy 8.3, plugins 4.5.

**Nothing is tested end to end.** No Playwright/Cypress/Selenium, no `LiveServerTestCase`. **No
test spawns a subprocess** — zero references to `subprocess`/`Popen`/`posix_spawn` across all test
files, so ffmpeg lifecycle and stderr parsing are only exercised against hand-written strings.
Exactly one test file talks to a real Redis (`tests/test_wait_for_redis.py`, which tests the
wait script). The ownership lease and ring buffer never run against real Redis semantics; Redis
fakes reimplement the Lua scripts in Python, proving the reimplementation correct while saying
nothing about atomicity.

Nothing gates on any of it: `ci.yml`, `release.yml` and `docker-build.yml` have no test job in
their `needs:` graph, and upstream's `main`/`dev` have no branch protection and no rulesets.
`docker-build.yml` has never run and is broken by construction (`context: docker` against a
Dockerfile whose first instruction is `COPY ./frontend`).

Test filenames name defects, not capabilities (`test_ts_proxy_ghost_clients`,
`test_xc_empty_fetch_guard`, `test_buffering_state_recovery`). Read that list as a free hazard map
for this problem domain.

## Builds are not reproducible

Relevant whenever you debug "works locally, not in the image":

- `uv.lock` is **gitignored**. 18 of 31 `pyproject.toml` dependencies are unpinned, including
  `psycopg[binary]`, `uwsgi`, `daphne`, `channels`, `django-redis` and
  `djangorestframework-simplejwt`.
- CI installs the frontend with `npm ci`; **`docker/Dockerfile:14` uses `npm install`**, so the
  shipped bundle is built from a dependency set that was never tested.
- `docker/Dockerfile:4` uses `ARG BASE_TAG=base`, a floating tag. The base image compiles comskip
  from `refs/heads/master`, installs Redis and PostgreSQL from unversioned apt, and copies uv from
  `:latest`.
- Net effect: you cannot rebuild v0.29.0 and get v0.29.0. A running instance was observed
  reporting Django 6.0.5 against a `pyproject.toml` pinning 6.0.7.

There is no Python linter, formatter, type checker or pre-commit config anywhere, and no CodeQL,
Dependabot, Trivy, Bandit, SBOM or signing. Return-type annotations cover 188 of 1,891 functions.

## Conventions

Backend: DRF serializers for every endpoint (never return raw dicts); register routes in the app's
`api_urls.py` and verify they appear in the drf-spectacular schema; ship migrations with model
changes; Celery tasks go in the app's `tasks.py` (or `core/tasks.py`) and should be idempotent.

Tests: `CELERY_TASK_ALWAYS_EAGER` is deliberately **off** globally — `post_save` on
`M3UAccount`/`EPGSource` calls `.delay()`, and eager mode runs it inside the `TestCase`
transaction and poisons the connection. Opt in per-test with
`@override_settings(CELERY_TASK_ALWAYS_EAGER=True)`. `settings_test` also forces the plain
`postgresql` backend rather than `django-db-geventpool`, which breaks `TestCase` isolation on
pooled connections.

See `CONTRIBUTING.md` for the upstream PR process and fuller style guide.
