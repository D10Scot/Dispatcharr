# Phase 1 PR 7 — Status and Control API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the relay's Redis keys private — every control-plane site that reads a relay-owned
key becomes an HTTP call to five new `/proxy/relay/…` routes served by the relay process and gated
by the same bound internal token PR 6 introduced — so Phase 3 (video off Redis) becomes a
relay-only change.

**Architecture:** `apps/proxy/relay_urls.py` + `relay_views.py` mount five `IsInternalRelay` routes
under `/proxy/relay/` on the relay process; `apps/proxy/relay_client.py` is Django's side of that
boundary, a `requests` client that signs each call with `build_internal_request_header` and reaches
the relay through the API role's nginx, which already carries `location ^~ /proxy/relay/ { …
uwsgi_pass relay_py; }`. `apps/proxy/internal_base_url.py` holds the one four-branch resolver and
the one host validator both directions share (D9). The five existing `IsAdmin` views keep their
URLs, permission class and response shapes and become thin wrappers over `relay_client`.

**Tech Stack:** Django 6 + DRF + drf-spectacular (`apps/proxy/`, `apps/channels/`, `apps/m3u/`,
`core/`), `requests` under gevent, Redis (`RedisKeys`), nginx (`docker/nginx.conf`), Playwright +
TypeScript (`e2e/`), vitest (`frontend/`, read-only here).

**Spec:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` § The eight pull
requests › PR 7 — `migration/phase1-control-api`.

**Branch:** `migration/phase1-control-api` (worktree `.worktrees/phase1-pr7`), off `main`.

## Branch base

This branch was cut from PR 6's head, so PR 6's work is already present here as ordinary file
content: `apps/proxy/internal_auth.py` (the static token **and** the bound per-request token),
`apps/proxy/permissions.py` (`IsInternalRelay`), `apps/proxy/control_plane.py`,
`apps/proxy/next_source.py`, `apps/proxy/{serializers,api_views,api_urls}.py`,
`core/relay_events.py`, and the relay-side rewrites in `live_proxy/`.

**PR 7 executes only after PR 6 (#188) has merged to `main`.** Task 1 is the gate: reset this
branch onto `origin/main` before anything else. PR 6 arrives on `main` **squashed**, so:

- **This plan cites no PR 6 commit hash anywhere, and neither may the executor.** After a squash
  merge the hashes on this branch do not exist on `main`; `git merge-base --is-ancestor` answers
  "no" for a PR 6 that has demonstrably merged. Every check in Task 1 is a check on **file
  content**.
- **Every file:line below was verified against this worktree before the reset.** Line numbers
  drift; the tree wins. Task 1 re-runs the greps that matter and says what to do with each answer.

## Global Constraints

- **The gate on `/proxy/relay/…` is `IsInternalRelay`, never a principal.** Both internal headers
  are required — the static `X-Dispatcharr-Internal` and the bound
  `X-Dispatcharr-Internal-Request` — exactly as `/api/relay/…` requires them since PR 6. Every
  relay view carries `@authentication_classes([])` and `@permission_classes([IsInternalRelay])`.
  No `IsAdmin`, no session user, no DRF authenticator.
- **`location ^~ /proxy/relay/` stays externally reachable and must NOT become `internal;`.** Django
  dials it as an ordinary HTTP client (from the `api` role and from the `worker` role), so
  `internal;` would 404 every control call. It keeps the `dispatcharr_api_params.conf` blanking
  include and `uwsgi_pass relay_py;`, and it stays outside the authorize hop (spec § PR 5,
  Amendment S8). The token is the whole gate (D9).
- **The five existing admin surfaces are unchanged from the client's side.** `/proxy/ts/status`,
  `/proxy/ts/status/<id>`, `/proxy/ts/stop/<id>`, `/proxy/ts/stop_client/<id>`,
  `/proxy/ts/change_stream/<id>`, `/proxy/ts/next_stream/<id>` and `/proxy/stats/` keep their URLs,
  their `IsAdmin` permission class, their HTTP methods and their JSON shapes — apart from the two
  type fixes the spec names (`ffmpeg_speed` a float, `state` `null` instead of `'unknown'`) and
  three purely additive fields (`width`, `height`, `video_bitrate`) the DVR needs. `frontend/src/`
  is not edited in this PR.
- **DRF serializers for every request and response body** on the five new routes — never a raw
  dict — and every new route present in the drf-spectacular schema, asserted by a test in the same
  shape as `apps/proxy/tests/test_authorize_view.py`'s
  `test_the_view_appears_in_the_openapi_schema`.
- **Routes are mounted per D12:** `apps/proxy/relay_urls.py`, included from `apps/proxy/urls.py` as
  `path('relay/', include('apps.proxy.relay_urls'))` → `/proxy/relay/…`. **`apps/api/urls.py` is
  not touched** — `/api/relay/` is already mounted there by PR 6, so PR 7 does *not* trigger the
  `__all__` alias.
- **`get_relay_control_base_url()` reuses PR 6's host check, extracted rather than duplicated.**
  `apps/proxy/internal_base_url.py` holds `validated_base_url()` (PR 6's `_validated`, moved whole)
  and `resolve_base_url()` (the four-branch DVR formula). `control_plane.get_control_plane_base_url()`
  and `relay_client.get_relay_control_base_url()` are the two thin wrappers D9 asks for, differing
  only in their override variable.
- **HTTP client and timeouts:** `requests`, `allow_redirects=False`, no `Session` cache, one call
  per request. Three budgets, each justified in Task 2: reads called from the tune path `(1, 2)`;
  reads and stops called from an admin request `(2, 5)`; `advance` `(2, 20)`, because
  `ChannelService.change_stream_url`'s non-owner branch polls `RedisKeys.switch_status` for up to
  `STREAM_SWITCH_CONFIRM_TIMEOUT = 15` seconds
  (`apps/proxy/live_proxy/services/channel_service.py`). **No retries anywhere in `relay_client`** —
  a retried `advance` would switch twice, a retried stop doubles an admin's wait, and a retried
  tune-path read blows the relay's own 5-second read budget for `next-source`.
- **A relay that cannot answer means no live clients, so the stream-limit check fails open.**
  `get_user_active_connections`'s live branch contributes an empty list on `RelayUnavailable`, logs
  once at WARNING, and lets the timeshift and VOD branches proceed — the same shape as the
  function's existing `except Exception: return []`. Failing closed would 429 every tune during a
  relay restart.
- **No channel state in Python memory.** `relay_client` caches nothing: no client list, no channel
  map, no base-URL memo beyond the environment read each call already does.
- **Gevent safety, as PR 6 established it.** `requests` is safe here because
  `gevent-early-monkey-patch` is on, so a socket read yields the hub. No `time.sleep` outside a
  gevent-patched process, no blocking file or subprocess call on any path this PR adds.
- **Nothing new may be imported into `apps/proxy/live_proxy/constants.py` or `redis_keys.py`.**
  `apps/channels/models.py:6-7` imports both at module level; one import there stops Django
  booting. Task 8's audit records the outcome; it does not add imports either way.
- **Nothing under `apps/proxy/live_proxy/`, `apps/proxy/vod_proxy/` or `apps/timeshift/`'s
  streaming path imports `relay_client` (D10).** `apps/proxy/live_proxy/views.py` is the one file
  that both hosts relay-served stream views *and* the five API-process admin views; Task 6 imports
  `relay_client` there **function-locally, inside the five admin views only**, and a grep in Task
  14 proves no module-level import exists and no stream view reaches it.
- **No ORM write may land under `apps/proxy/`.** `scripts/metrics/collect_architecture.py` counts
  every write there into `proxy_orm_writes`, a Phase 1 headline metric with target 0
  (`metrics/curated/catalogue.yml`). The relay views added here read Redis and render serializers;
  they write nothing.
- **`os.posix_spawn` stays; no relay internals are rewritten; `apps/proxy/hls_proxy/` stays dead.**
  `ChannelService`'s static methods keep their signatures and behaviour — the relay views call
  them, they do not replace them (D10). The three carried defects this PR touches code near
  (`MAX_STREAM_SWITCHES` not bounding buffering-triggered switches, the 60s/30s channel-stopping
  TTL race, the un-fenced ownership lease) are **carried, not fixed**: no task may quietly change
  any of them.
- **Redaction:** any log line naming a URL, a path, a header dict or a credential goes through
  `redact_url`/`redact_headers` (`dispatcharr/utils.py`) or `scripts/check_credential_logging.py`
  blocks the edit and the commit. `relay_client`'s log lines name the **identifier and the status
  code only**, never the URL it dialled — the same rule `control_plane.ControlPlaneRefused` already
  follows.
- **A channel UUID is a secret.** It appears in a `/proxy/relay/…` path, which is why that location
  is reachable only with the internal token and why no new log line prints a full request URL.
- **`git add` and `git commit` run in separate Bash calls**, and the commit message is written with
  the Write tool and passed as `-F <msgfile>` — the pre-commit hook blocks any single call
  containing both verbs, and trips on a heredoc that merely contains them.
- **Supply-chain pinning** applies to any new `uses:` (40-char SHA + version comment) or
  `FROM` / `COPY --from=` (digest). **This PR adds neither** — it touches no workflow and no
  Dockerfile.
- **CI label routing.** The changed paths of this PR
  (`apps/proxy/**`, `apps/channels/**`, `apps/m3u/**`, `core/**`) resolve through
  `dispatcharr/test_discovery.py` to exactly five labels: `apps.channels.tests`, `apps.m3u.tests`,
  `apps.proxy.live_proxy.tests`, `apps.proxy.tests`, `core.tests` — verified by running
  `labels_for_changed_paths` against this plan's file list. That is the same set the spec's Done
  criterion names. `apps.proxy.vod_proxy.tests` is **not** selected and `apps/api/urls.py` is not
  touched, so this is not an all-16 PR. The branch is `migration/**`, so `lifecycle-tests.yml` and
  `e2e-tests.yml` run in **full mode**.
- **`#177`'s `core/models.py` migration drift is avoided by not touching `core/models.py`.** No
  task in this plan edits it. If a task ever needs to, stop and report: the `*/models.py` edit hook
  runs `makemigrations --check` and will block on drift this PR did not create.

## Design rulings

Each of these settles something the spec leaves open or states in a way the tree contradicts. They
are binding on the executor; a reviewer should check the plan against them, not re-derive them.

1. **`get_relay_control_base_url()` resolves to an nginx, not to the relay's own port, and its
   modular branch uses `DISPATCHARR_WEB_HOST` — not `DISPATCHARR_RELAY_HOST`.** D9's text names
   `DISPATCHARR_RELAY_HOST` (default `relay`), but two other decisions make `http://relay:<port>`
   undialable: D5 gives the relay exactly one listener, `socket = 0.0.0.0:$(DISPATCHARR_RELAY_PORT)`
   in `docker/uwsgi.relay.ini`, which speaks the **uwsgi protocol**, not HTTP, so `requests` cannot
   talk to it; and D14 says the `relay` role runs no nginx, so nothing listens on 9191 in that
   container either. D5's own sentence is the reconciliation — "D9 routes Django's control calls
   through nginx as well, so nothing ever dials a raw HTTP port on the relay." The nginx that can
   reach the relay is the `api`/`all` role's, which already carries
   `location ^~ /proxy/relay/ { … uwsgi_pass relay_py; }`. So both directions resolve to the same
   address and the two wrappers differ only in their override variable:
   `DISPATCHARR_RELAY_BASE_URL` for Django→relay, `DISPATCHARR_INTERNAL_API_BASE_URL` for
   relay→Django. `DISPATCHARR_RELAY_HOST` keeps its existing and only job — the `RELAY_UPSTREAM`
   `sed` in `docker/init/03-init-dispatcharr.sh` — and is not read by `relay_client`.
   `DISPATCHARR_RELAY_BASE_URL` remains the escape hatch for a deployment that does front the relay
   with its own HTTP listener.
2. **`location ^~ /proxy/relay/` must not be `internal;`.** The brief offers `internal`-only or
   trust-token-blanked as the two options; only the second is possible. `internal;` makes nginx
   serve a location for a subrequest or an `X-Accel-Redirect` and 404 every client request, and
   Django's control calls **are** client requests — from the `worker` container across the compose
   network, and from the `api` container to its own nginx. The location therefore keeps exactly
   what PR 4 gave it (the `dispatcharr_api_params.conf` blanking include, so a client-supplied
   `X-Relay-*` header never reaches the relay on this path, and `uwsgi_pass relay_py;`), gains an
   explicit `uwsgi_read_timeout 30s;` so the `advance` budget is visible in the config rather than
   inherited from nginx's 60s default, and gains a greybox assertion pinning all four properties.
3. **`GET /proxy/relay/channels` takes `?clients=all`.** `get_basic_channel_info` caps its client
   list at ten (`list(client_ids)[:10]`), which is fine for the Stats payload and wrong for
   `get_user_active_connections`, whose whole job is counting a user's connections. Rather than
   change the stats payload, `build_live_channel_stats_data` and `get_basic_channel_info` gain a
   `client_limit` keyword defaulting to `10`; the route passes `None` (uncapped) when the query
   parameter is `all`, and the default otherwise. `/proxy/stats/` and `/proxy/ts/status` keep
   today's ten-client payload byte for byte.
4. **`ffmpeg_speed` and `state` are normalised on the detailed side to match the basic side, and
   the change is invisible to the UI.** `get_detailed_channel_info` emits `ffmpeg_speed` as the raw
   Redis string and defaults `state` to `'unknown'`; `get_basic_channel_info` emits `float(...)`
   and leaves `state` `None`. Nothing in `frontend/src/` reads the detailed endpoint at all —
   `API.getChannelStats` accepts a `uuid` argument and ignores it, calling the bare
   `/proxy/ts/status` — so the normalisation reaches only the e2e harness. It does reach that:
   `e2e/fixtures/types.ts` declares `ffmpeg_speed?: string` and `state: string`, and
   `e2e/tests/streaming/stream-profiles.spec.ts` calls `Number.parseFloat` on the value. Both are
   updated in the same task, which is why the type fix is not a free rename.
   `owner`'s identical `'unknown'` default is **carried, not fixed** — the spec names two fields,
   not three, and `e2e/fixtures/types.ts` documents `owner: string | null` against it already.
5. **The detailed payload gains `width`, `height` and `video_bitrate`, purely additively, because
   the DVR's metadata read moves onto it.** `apps/channels/tasks.py`'s `run_recording` reads seven
   video and four audio fields straight out of `RedisKeys.channel_metadata` and stores them under
   `Recording.custom_properties["stream_info"]`. Eight of the eleven already appear in
   `get_detailed_channel_info` under keys identical to their `ChannelMetadataField` values
   (`video_codec`, `resolution`, `source_fps`, `pixel_format`, `audio_codec`, `sample_rate`,
   `audio_channels`, `audio_bitrate`); `width`, `height` and `video_bitrate` do not. They are added
   as **raw strings**, exactly as their eight siblings are, so the DVR keeps its own
   `_d(key, caster)` casting and `stream_info` stays byte-identical. Nothing else reads them.
6. **`core/utils.py`'s event enrichment keeps reading `channel_stream:`/`stream_profile:`
   directly.** The spec's PR 7 bullet says `core/utils.py:778,811` should call `relay_client`, but
   PR 6 made those two keys **Django-owned** — `CLAUDE.md` § Known defects now states it outright
   ("Django is the only writer … the relay reaches them only through `POST /api/relay/…`"). Asking
   the relay for the value of a key Django owns and the relay merely reads would invert the
   ownership PR 6 established. The enrichment runs in the API process (since PR 6 the relay posts
   events rather than calling `log_system_event` itself), reads through `RedisKeys.channel_stream`
   / `RedisKeys.stream_profile`, and stays exactly as it is. Neither literal appears in
   `core/utils.py`, so the spec's Done grep is unaffected.
7. **The Done grep matches two Python attribute accesses that will never go away, so it grows an
   exclusion pipe and keeps the spec's "returns nothing" shape.**
   `grep -rn "live:channel:\|channel_stream:\|stream_profile:" apps/channels/ apps/m3u/ core/
   dispatcharr/ | grep -v tests` also matches `apps/channels/models.py`'s `if self.stream_profile:`
   in `Stream.get_stream_profile` and `if not stream_profile:` in `Channel.get_stream_profile`.
   Both are `StreamProfile` model attributes with no Redis in sight. Every one of the seven genuine
   `live:channel:` string literals in that directory set lives inside `_pick_channel_to_preempt`,
   which this PR deletes. Asserting "exactly those two lines" would be brittle — any new
   `stream_profile:` annotation or attribute access would read as a regression — so the Done form
   everywhere in this plan, and in Amendment S11, is:
   ```bash
   grep -rn "live:channel:\|channel_stream:\|stream_profile:" apps/channels/ apps/m3u/ core/ dispatcharr/ \
     | grep -v tests \
     | grep -v "self.stream_profile:\|not stream_profile:"
   ```
   **Expected: empty**, which is the spec's own criterion with the two attribute accesses named and
   excluded rather than silently tolerated. Task 13 runs it verbatim.
8. **`_pick_channel_to_preempt` is deleted rather than ported, and its deletion is safe because the
   function has never returned a channel.** Three independent reasons, each verified: `models.py`
   never imports `time`, so any candidate reaching the cooldown check raises `NameError`;
   `live:profile:{id}:channels` (the index it prefers) is written nowhere in the repository; and
   the scan fallback parses `int(parts[2])` out of `live:channel:{uuid}:metadata`, whose segment is
   a UUID, so the `int()` always raises into a bare `except` and the candidate set stays empty. The
   commented-out `return` beside its call site goes with it, along with the surrounding
   `if victim_channel_id:` block, whose only remaining statement is a `logger.info` about a
   preemption that never happens. `metrics/curated/defects.yml`'s `preemption-dead-code` row moves
   to `fixed`. **The feature gap is unchanged** — channel preemption stays unimplemented after
   Phase 1, exactly as the spec's Risks section says.
9. **The models.py boot-trap audit's recorded outcome is "no", and that contradicts the spec's
   stated recommendation.** The spec recommends deleting
   `from apps.proxy.live_proxy.redis_keys import RedisKeys`. That import **could only go by
   relocating PR 6's two four-line helpers to a Django-owned module, and doing so would not remove
   the trap while `ChannelMetadataField` remains.** PR 6 moved `channel_stream` and
   `stream_profile` **into** `RedisKeys`, and `apps/channels/models.py` is their owner and only
   writer, reaching them through that class at twenty-six sites — so the import is now the
   legitimate accessor for keys this module owns, not an incidental leak. The second import loses
   one of its two names: `ChannelState` becomes unused the moment `_channel_proxy_is_active` stops
   reading metadata (it is that function's only consumer in the file). `ChannelMetadataField`
   stays, used by `_release_stale_stream_assignment` and `Channel.release_stream`'s metadata
   fallbacks — ruling 10's straggler. So `models_module_level_live_proxy_imports` stays at **2**
   either way, and the boot-cycle trap `CLAUDE.md` names is unchanged. Task 14 writes that outcome,
   in those terms, into `CLAUDE.md`, Amendment S11 and the Requirements row rather than leaving the
   claim ambiguous.
10. **Two relay-key accesses in `apps/channels/models.py` are a named straggler, deferred and
    tracked as issue #190.** `_release_stale_stream_assignment` reads
    `ChannelMetadataField.M3U_PROFILE` out of the metadata hash, and `Channel.release_stream` both
    reads it and `hdel`s two fields from it — a control-plane **write** to a relay key, which the
    spec's Requirements row ("every other relay key was already single-writer") does not
    anticipate. **The read fallback is not the obstacle**: PR 6's `ReleaseRequestSerializer`
    already carries `stream_id` and `m3u_profile_id`, so the relay passes both in the release body
    and the read could go with no contract widening at all. **The `hdel` is.** It clears the relay's
    own metadata hash so a duplicate release cannot `DECR` the provider counter twice, and its
    natural home is the relay's release call sites — a relay-internal edit D10 keeps out of this
    phase, and one this PR's section does not ask for (it names `_channel_proxy_is_active`,
    `_stream_assignment_is_reusable` and the client-count reads, and stops). Deferred, and filed as
    `D10Scot/Dispatcharr` **#190** so the spec's "documented follow-up" is a tracked item rather
    than a paragraph. Task 14 cites #190 in Amendment S11, in the `CLAUDE.md` bullet and in the
    PR body.
11. **`POST /proxy/relay/channels/<id>/advance` carries a fully-resolved source; the relay resolves
    nothing.** PR 6's ruling 10 left this open ("PR 7 moves those views to `relay_client`, at which
    point `change_stream_url` runs in the relay and PR 7 revisits the call"). The answer: the
    request body is `{stream_id, url, user_agent, m3u_profile_id, stream_name}`, all resolved by
    `apps/proxy/next_source.resolve_source` in the **API process**, exactly where it runs today.
    The relay view calls `ChannelService.change_stream_url(channel_id, new_url, user_agent,
    stream_id, m3u_profile_id, stream_name=…)` with `new_url` always present, so
    `change_stream_url`'s `if not new_url and target_stream_id:` branch — the one holding the
    function-local `from apps.proxy.next_source import resolve_source` — is never entered from the
    relay. That branch's only two callers are the two Django views this PR rewrites, so it becomes
    unreachable in practice. It is **left in place**, not deleted: it is relay-internal code this
    phase does not rewrite, and it costs nothing because a function-local import that never
    executes is never imported. Task 13 greps to prove no relay code path reaches it.
12. **`next_stream`'s "what is playing now" read moves to `relay_client.get_channel()`.** The view
    reads `RedisKeys.channel_metadata` for `STREAM_ID` and `M3U_PROFILE` today. After PR 4's
    routing that view runs in the **API** process, so it is a control-plane read of a relay key
    that happens to live in an `apps/proxy/` file — invisible to the spec's Done grep, which covers
    `apps/channels/`, `apps/m3u/`, `core/` and `dispatcharr/`, but exactly the thing this PR
    exists to remove. It becomes one `GET /proxy/relay/channels/<id>` whose payload already carries
    `stream_id` and `m3u_profile_id`. The stream rotation and the `resolve_source` call stay in the
    API process, where the ORM is.
13. **The tune-path reads nest one HTTP hop inside another; their timeout is sized for it and an
    unreachable relay reuses rather than re-reserves.** `Channel.get_stream()` runs inside
    `next_source.resolve_source()`, which the relay reaches over
    `POST /api/relay/channels/<id>/next-source` with a **5-second read timeout and one retry**. Its
    reuse branch calls `_stream_assignment_is_reusable`, which after this PR asks the relay. The
    tune-path budget is therefore `(1, 2)` with **no retry** — at most three seconds, well inside
    the relay's five — and the read is narrowed to a single `HGET` by `?fields=state`
    (ruling 20), not the diagnostics-heavy detail payload.
    **The failure path, exactly as Tasks 5 and 8 build it:** an unreachable relay yields
    `ChannelSnapshot(present=False, active=False, reachable=False)`, `present=False` sends
    `_stream_assignment_is_reusable` to its Django-owned `stream_profile:<id>` fallback, and an
    existing assignment is therefore **reused** — no `release_stream()`, no re-reservation, so the
    provider counter cannot move at all. That is the failure mode that cannot leak a slot; treating
    an unreachable relay as "stopped" would release and re-reserve on a channel that may still be
    running. The nesting is not a deadlock: the relay runs `gevent = 1600`, so the inner request is
    served by a second greenlet while the outer one waits, and the inner handler reads Redis only —
    it makes no control-plane call of its own, so the chain terminates. It happens on a **re-tune**
    only, not on every tune: `_stream_assignment_is_reusable` is reached only when
    `channel_stream:{id}` already exists.
14. **`dev` has two shapes and they behave differently; the note must say both.** Both wrappers
    resolve to `http://127.0.0.1:5656` when `DISPATCHARR_ENV=dev`, and what answers there depends
    on how dev was started.
    *Bare `manage.py runserver 5656`:* one process serves everything, so a tune is request →
    `next-source` (self) → the reuse check (self), three deep. `runserver` is threaded by default
    and serves each nested request on a new thread; **`--nothreading` would hang the outer request
    forever.** That is the warning to write down.
    *Dev inside Docker:* `docker/supervisord/all-dev.conf`'s `[include]` starts **both**
    `api-uwsgi.conf` and `relay-uwsgi.conf` and no nginx, so `:5656` is the **API** uWSGI, not the
    relay. `/proxy/relay/…` is therefore served by the API process there. Status reads still work
    (both processes share one Redis) and stops and `advance` still work (`ChannelService` reaches
    the owner over `live:events:` pub/sub, which is cross-process by design), but **`reset_tried`
    is a silent no-op**: the API process holds no `StreamManager` to clear. Nothing breaks; one
    operator affordance is unavailable in that one shape. Task 14 records both halves.
    PR 6 already put one self-call on this path and documented the dev port in `CLAUDE.md`
    § Commands; the note extends that bullet rather than inventing a second mechanism.
15. **Issue #181's second ask is met without a sixth trust header.** #181 asks to bind or scope the
    internal token before it gates the control API — done by PR 6's `X-Dispatcharr-Internal-Request`
    and by this PR putting `IsInternalRelay` in front of all five `/proxy/relay/…` routes — and
    "also add `is_internal` to `AuthorizeResult` so the view stops re-reading the raw header".
    `AuthorizeResult` gains `is_internal: bool = False` as an **inline-only** field, beside `user`
    and `trusted`, which the docstring already says never cross the wire: `authorize_stream` sets
    it from `request_is_internal`, and `result_from_headers` sets it the same way, because nginx
    forwards a client's `X-Dispatcharr-Internal` unchanged on relay-bound locations (it is not one
    of the five blanked names) so the header is present on both paths. No new `X-Relay-*` header,
    no `auth_request_set` line in nine nginx locations, and no change to the greybox spec's
    six-variable list. `apps/proxy/live_proxy/views.py`'s
    `internal_principal = request_is_internal(getattr(request, "_request", request))` becomes
    `decision.is_internal`, which is the duplication #181 objects to.
16. **The relay control API is not exposed to clients and is not in the client API surface.**
    Its schema entries are tagged `internal`, matching PR 6's three routes, so an operator reading
    `/api/schema/` can tell them apart from the endpoints a player or the SPA may call. The five
    routes answer only to a caller holding `SECRET_KEY`; there is no `IsAdmin` fallback and no
    query-parameter token.

17. **The bound internal token signs `request.get_full_path()`, not `request.path`.** PR 6 signed
    the path because none of its three routes takes a query parameter, so the two strings were
    always equal. Ruling 3 adds one that does, and an unsigned query string is a parameter a replay
    inside the 120-second window could flip — `?clients=all` decides whether the response carries
    every client or the stats surface's first ten. The change is one line on each side of the
    contract and is backward compatible: `get_full_path()` returns exactly `path` when there is no
    query string, so every call PR 6 shipped verifies unchanged. The alternative — leaving the
    query string outside the signature and documenting the hole — would leave the same hole open
    for every future route.
18. **`POST .../advance` carries `reset_tried`, restoring behaviour PR 4 silently broke.**
    `/proxy/ts/change_stream/` has always cleared the running `StreamManager`'s `tried_stream_ids`
    so an operator's manual switch does not inherit a failover's exclusion list. That reset used to
    run in the same process as the manager. PR 4's routing put the view on the `api` role, where
    `proxy_server.stream_managers` is always empty because that process never serves
    `/proxy/ts/stream/`, so the reset has been dead ever since and nothing said so. It moves to the
    relay's advance handler, where the manager is. It is a flag rather than unconditional because
    `next_stream` has never reset it and must not start: rotating to the next stream is what the
    exclusion list is for. This is not a relay-internals rewrite — the same two statements, in the
    process where they mean something.
19. **`Channel._channel_proxy_is_active` is deleted rather than rewritten.** The spec names it and
    `_stream_assignment_is_reusable` as two things to route through `relay_client`, but the
    predicate it computes — is the state one of five `ChannelState` values — is exactly what
    `relay_client.channel_snapshot()` answers, and its only caller in the tree is
    `_stream_assignment_is_reusable`. Keeping a one-line wrapper would either cost a second HTTP
    round trip on the tune path or leave a method with no caller, and it would keep `ChannelState`
    imported into `apps/channels/models.py`, which ruling 9's audit outcome depends on dropping.
    One snapshot, both questions.

20. **The tune-path read asks for one field, `GET /proxy/relay/channels/<id>?fields=state`, and it
    gets its own serializer.** `channel_snapshot` needs two bits — does the relay hold metadata for
    this identifier, and is its state one of five values. Answering that with
    `get_detailed_channel_info` would sample buffer chunk keys, `SCAN` on a miss, walk every client
    and run two ORM name fallbacks, all under a two-second read budget on the tune path, which
    would trip the degraded fallback under load far more often than the question warrants.
    `channel_view` therefore takes `?fields=state` and answers it with one `EXISTS` plus one
    `HGET`, rendered through a two-field **`RelayChannelStateSerializer`**.
    **Not a partial render of `RelayChannelDetailSerializer`**, which is the obvious shortcut and is
    wrong: DRF's `Field.get_attribute` checks `default`, then `allow_null`, and only then `required`
    (`rest_framework/fields.py`, 3.17.1, the pinned version), so a missing key on a
    `required=False, allow_null=True` field renders as **null rather than being skipped** — the
    detail serializer's `url`, `stream_profile` and `owner` would all appear as nulls in an answer
    that knows nothing about them. Ruling 4's absences are unaffected: they rely on fields that are
    `required=False` and *not* `allow_null`, and the four nullable ones are always assigned by both
    info builders on the full payloads. Two shapes under one 200, so the GET `extend_schema` names
    the full serializer in `responses` and the narrow one in its description; a
    `PolymorphicProxySerializer` would want a discriminator field the wire does not carry.

## Done criteria (from the spec)

- [ ] **The control plane holds no relay-key literal.** Run, as one command (ruling 7):
      ```bash
      grep -rn "live:channel:\|channel_stream:\|stream_profile:" apps/channels/ apps/m3u/ core/ dispatcharr/ \
        | grep -v tests \
        | grep -v "self.stream_profile:\|not stream_profile:"
      ```
      Expected: **empty**. The two excluded patterns are the `StreamProfile` model-attribute
      accesses in `Stream.get_stream_profile` and `Channel.get_stream_profile`; anything else,
      and especially any `live:channel:` line, is a failure.
- [ ] **`apps.channels.tests` green**, including `tests/test_ts_proxy_teardown.py`'s ten
      `ProxyServer` constructions: `manage.py test --keepdb apps.channels.tests -v1`.
- [ ] **`apps.m3u.tests` green**: `manage.py test --keepdb apps.m3u.tests -v1`.
- [ ] **`apps.proxy.tests` green**: `manage.py test --keepdb apps.proxy.tests -v1`.
- [ ] **`apps.proxy.live_proxy.tests` green**: `manage.py test --keepdb apps.proxy.live_proxy.tests -v1`.
- [ ] **`core.tests` green**: `manage.py test --keepdb core.tests -v1`.
- [ ] **`E2E result` green in full mode**, with `frontend/src/pages/Stats.jsx`'s existing coverage
      unchanged: `cd frontend && npm test` passes with **no frontend file edited**, and the
      `frontend`, `streaming`, `streaming-failover`, `streaming-greybox` and `lifecycle` Playwright
      projects pass against a stack built from this worktree.
- [ ] **`CLAUDE.md` corrected** — § Structural constraints' `channels/models.py:6-7` boot-cycle
      paragraph carries the audit's actual outcome; § Observing a channel's `ffmpeg_speed` and
      `state` bullets; § Known defects' "channel preemption is dead code" becomes deleted code,
      keeping the history. (Task 14.)

Additional gates this plan owns, in the same spirit:

- [ ] **The schema generates, and no warning names anything this PR added.**
      `--fail-on-warn` is **not** a usable gate here: PR 6's verification runs showed it exits 1 on
      the baseline tree, because most legacy `@api_view` functions carry no `extend_schema` and
      nothing in CI has ever run it. Run instead:
      ```bash
      manage.py spectacular --file /dev/null 2>&1 | grep -i "relay\|/proxy/relay" ; echo "exit=$?"
      ```
      Expected: no matching line (`grep` exits 1, printing `exit=1`). The five new paths appearing
      in the schema is a separate, positive assertion, made by a test in Task 4.
- [ ] `PYTHONPATH=scripts/metrics python scripts/metrics/collect_architecture.py --repo-root .` still prints
      `"proxy_orm_writes": 0` and `"models_module_level_live_proxy_imports": 2`.
- [ ] `python -m metrics.build --validate-only` exits 0 after Task 14's ledger edit.
- [ ] `scripts/check_credential_logging.py` clean on every edited `.py`.
- [ ] `cd e2e && npx tsc --noEmit` clean (Tasks 3 and 13).
- [ ] `docker/tests/test-puid-pgid.sh` passes both `test_modular_mode` and `test_role_split`
      (Task 13) — `test_role_split` is the only test of the cross-container relay hop, and this PR
      adds traffic in the opposite direction across it.

## Test environment for this worktree

The edit/commit hooks resolve the project directory from the harness, so in a worktree they do not
run tests automatically. Run them yourself:

1. Start a container for this worktree (idempotent). **Run it in the background** — it does not
   exit after the container is ready. Poll `pg_isready` in a second call and stop it once that
   answers:
   `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr7 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr7 DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/.claude/hooks/start-test-container.sh`
   **`DISPATCHARR_TEST_IMAGE` is not optional**: without it the script pulls upstream's image,
   which has no `hypothesis`, and every `apps.proxy.live_proxy.tests` run dies on an import error
   that looks nothing like a missing dependency.
2. After editing any file, run the affected-file hook by hand:
   `echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr7 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr7 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/.claude/hooks/run-affected-tests.sh`
   Exit 2 = blocking failure; read the output.
3. Before every commit, run the commit gate by hand:
   `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr7 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr7 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/.claude/hooks/pre-commit-tests.sh --git-hook`
4. Backend tests directly: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr7 /dispatcharrpy/bin/python manage.py test --keepdb <label> -v1`
5. Frontend: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/frontend && npm ci && npm test`.
   E2E typecheck: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/e2e && npm ci && npx tsc --noEmit`.
6. **E2E stack for this worktree only.** **EVERY ONE of the variables below must be exported for
   EVERY command, including the Playwright run itself.** The `lifecycle` project's restart spec
   shells out to `scripts/e2e_up.sh`, and a partially scoped environment falls back to the
   **shared** stack — issue #187, which stopped the shared provider once. Build and bring up with:
   `DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-pr7:local DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr7 DISPATCHARR_E2E_PORT=49191 DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr7-data DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr7-net DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-pr7 DISPATCHARR_E2E_UPSTREAM_PORT=9406 DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 scripts/e2e_up.sh`
   `scripts/e2e_up.sh` silently reuses an existing image tag, so run
   `docker rmi dispatcharr-e2e-pr7:local` before any rebuild. Recreate the provider container with
   `-e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-pr7:8080` or every subprocess-profile test
   fails with "188 bytes then EOF". Run Playwright with the full set:
   `E2E_BASE_URL=http://localhost:49191 E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:9406 E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-pr7:8080 DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-pr7:local DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr7 DISPATCHARR_E2E_PORT=49191 DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr7-data DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr7-net DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-pr7 DISPATCHARR_E2E_UPSTREAM_PORT=9406 DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 npx playwright test --project=<name>`
   **Never pass `--down` or `--reset`**, and never touch the shared `dispatcharr-e2e`,
   `dispatcharr-e2e-g14`, `e2e-upstream` or `dispatcharr-testrunner`. `-g` patterns match exact
   titles. Playwright counts exclude the `bootstrap` setup test unless stated.
7. If the container cannot start, say so in the task report: the work is then unverified, not
   verified.

**`docker exec … manage.py <x>` in the tasks below abbreviates the step 4 command**, with `<x>`
substituted for `test --keepdb <label> -v1`. Write it out in full every time you run it; the
abbreviation exists so the steps stay readable, not because any part of it is optional.

## File Structure

```
apps/proxy/
  internal_base_url.py             NEW     validated_base_url() (PR 6's _validated, moved whole),
                                           resolve_base_url() — the one four-branch D9 formula
  control_plane.py                 MODIFY  _validated/_raise_and_warn_once/_host_validation_warned
                                           move out; get_control_plane_base_url() becomes a
                                           resolve_base_url() wrapper
  relay_client.py                  NEW     Django→relay: get_relay_control_base_url,
                                           list_channels, get_channel, stop_channel, stop_client,
                                           stop_channels, advance, RelayUnavailable, RelayRefused
  relay_serializers.py             NEW     RelayChannel/Client/Detail/List/State, stop and
                                           advance request+response shapes
  relay_views.py                   NEW     channels_view, channel_view (incl. the ?fields=state
                                           tune-path form), channel_client_view,
                                           channel_advance_view — IsInternalRelay, no principal
  relay_urls.py                    NEW     the four route patterns (five routes: GET+DELETE share
                                           one path)
  urls.py                          MODIFY  + path('relay/', include('apps.proxy.relay_urls'))
  utils.py                         MODIFY  get_user_active_connections's live branch and
                                           attempt_stream_termination's live branch use relay_client
  authorize.py                     MODIFY  AuthorizeResult.is_internal (#181)
  authorize_views.py               MODIFY  result_from_headers sets is_internal
  live_proxy/channel_status.py     MODIFY  client_limit kwarg; ffmpeg_speed float; state null;
                                           + width/height/video_bitrate
  live_proxy/views.py              MODIFY  the five admin views become relay_client wrappers;
                                           decision.is_internal replaces the raw header read;
                                           two comments answering a PR 6 review thread
  next_source.py                   MODIFY  one docstring sentence, answering a PR 6 review
                                           thread — no behaviour change
  stats_views.py                   MODIFY  combined_stats' live branch uses relay_client
  tests/test_internal_base_url.py  NEW     the shared resolver and validator, both wrappers
  tests/test_relay_client.py       NEW     signing, timeouts, refusal vs outage, no retry
  tests/test_relay_control_api.py  NEW     the five routes: gate, shapes, schema presence
  tests/test_relay_status_shape.py NEW     ffmpeg_speed/state/width/height/video_bitrate and
                                           client_limit
  tests/test_control_plane_client.py     MODIFY  reset internal_base_url._host_validation_warned
  tests/test_combined_stats.py           MODIFY  patch relay_client instead of Redis
  tests/test_stream_limits.py            MODIFY  live branch now goes through relay_client; the
                                           test patching the deleted ChannelService import is
                                           deleted
  live_proxy/tests/test_admin_control_views.py  NEW  the five views are thin wrappers
apps/channels/
  models.py                        MODIFY  _channel_proxy_is_active / _stream_assignment_is_reusable
                                           via relay_client; _pick_channel_to_preempt deleted with
                                           its commented-out return; ChannelState import dropped
  api_views.py                     MODIFY  the two DVR-client blocks and the three ChannelService
                                           calls go through relay_client
  tasks.py                         MODIFY  run_recording's metadata read → relay_client.get_channel
  tests/test_channel_stream_reuse.py     NEW  the reuse helper against a faked relay_client
  tests/test_get_stream_assignment.py    MODIFY  its five tests answer channel_snapshot from the
                                           fake Redis they already seed; assertions unchanged
  tests/test_dvr_client_teardown.py      NEW  the two DVR blocks against a faked relay_client
apps/m3u/
  tasks.py                         MODIFY  ChannelService.stop_channels → relay_client.stop_channels
  api_views.py                     MODIFY  same
core/
  tasks.py                         MODIFY  fetch_channel_stats → relay_client.list_channels; the
                                           module-level live_proxy import is deleted
  tests/test_fetch_channel_stats.py      NEW  the task's payload and its outage behaviour
docker/nginx.conf                  MODIFY  ^~ /proxy/relay/ gains uwsgi_read_timeout 30s and a
                                           comment naming PR 7's routes
e2e/
  fixtures/types.ts                MODIFY  ChannelStatus.ffmpeg_speed number, state string | null,
                                           + width/height/video_bitrate
  tests/streaming/stream-profiles.spec.ts        MODIFY  ffmpeg_speed is a number now
  tests/streaming-greybox/nginx-stream-buffering.spec.ts  MODIFY  a fourth test pinning
                                           ^~ /proxy/relay/
  COVERAGE.md                      MODIFY  one P1 row
metrics/curated/defects.yml        MODIFY  preemption-dead-code → fixed
docs/superpowers/specs/2026-09-04-phase1-process-split-design.md  MODIFY  Done log + Amendment S11
                                           + the Requirements row's straggler caveat
CLAUDE.md                          MODIFY  the four corrections named in spec § PR 7 plus the dev
                                           --nothreading note
docs/superpowers/plans/2026-09-06-phase1-pr7-control-api.md  NEW  this file
```

---

### Task 1: Reset onto merged `main` and re-verify every anchor

**Files:** none edited. This task produces no commit.
**Interfaces:** Consumes `origin/main`. Produces a verified starting tree for Tasks 2-15.

- [ ] **Step 1: Confirm PR 6 merged, by content and not by hash.**
      Run: `git fetch origin && git log origin/main --oneline -3`
      Run: `git show origin/main:apps/proxy/control_plane.py | grep -c "def get_control_plane_base_url"`
      Run: `git show origin/main:apps/proxy/permissions.py | grep -c "class IsInternalRelay"`
      Expected: `1` from each grep. If either is `0`, **stop**: PR 6 has not merged and this plan
      must not execute.
- [ ] **Step 2: Reset this branch onto `origin/main`.**
      Run: `git status --porcelain` — Expected: empty, apart from this plan file if it is not yet
      committed.
      Run: `git reset --hard origin/main`
      Expected: `HEAD is now at <sha> …`. Then restore this plan file if the reset removed it:
      `git checkout <this-branch>@{1} -- docs/superpowers/plans/2026-09-06-phase1-pr7-control-api.md`
- [ ] **Step 3: Re-verify the anchors this plan cites.** Run each and compare against the expected
      answer. If a line number moved, find the new one with the same grep and use it; if a
      **symbol** is missing, stop and report.
      Run:
      ```bash
      grep -n "def _validated\|def get_control_plane_base_url\|_host_validation_warned" apps/proxy/control_plane.py
      grep -n "def request_is_internal_request\|def build_internal_request_header\|def internal_request_token" apps/proxy/internal_auth.py
      grep -n "def _pick_channel_to_preempt\|# return self.id, profile.id, victim_channel_id\|def _channel_proxy_is_active\|def _stream_assignment_is_reusable" apps/channels/models.py
      grep -n "def get_detailed_channel_info\|def get_basic_channel_info\|def build_live_channel_stats_data" apps/proxy/live_proxy/channel_status.py
      grep -n "def channel_status\|def stop_channel\|def stop_client\|def change_stream\|def next_stream" apps/proxy/live_proxy/views.py
      grep -rn "ChannelService\." apps/channels/api_views.py apps/m3u/tasks.py apps/m3u/api_views.py apps/proxy/utils.py | grep -v "^.*#"
      grep -n "location ^~ /proxy/relay/" -A 4 docker/nginx.conf
      ```
      Expected: `_validated`, `get_control_plane_base_url` and `_host_validation_warned` all
      present in `control_plane.py`; the three internal-token functions present; four
      `apps/channels/models.py` symbols present **including the commented-out `return`**; the three
      `channel_status.py` functions present; the five view functions present; **seven**
      `ChannelService.` call lines — `api_views.py` ×4 (`:105` `stop_channels`, `:3249` and `:3816`
      `stop_client`, `:3831` `stop_channel`), `m3u/tasks.py` ×1, `m3u/api_views.py` ×1,
      `proxy/utils.py` ×1. The spec says "six" because its count excludes `apps/proxy/utils.py:193`;
      seven is what this grep returns and what this plan moves. `api_views.py:3255`'s "Do not call
      ChannelService.stop_channel() here" is a comment, filtered by the `grep -v` above. Also
      expected: `location ^~ /proxy/relay/` present with
      `include /etc/nginx/dispatcharr_api_params.conf;` and `uwsgi_pass relay_py;`.
- [ ] **Step 4: Confirm the Done grep's two false positives are the only non-preempt matches.**
      Run: `grep -rn "live:channel:\|channel_stream:\|stream_profile:" apps/channels/ apps/m3u/ core/ dispatcharr/ | grep -v tests`
      Expected: nine lines — two `apps/channels/models.py` attribute accesses
      (`if self.stream_profile:`, `if not stream_profile:`) and seven `live:channel:` string
      literals, **every one of them inside `_pick_channel_to_preempt`**. Confirm the seven line
      numbers fall between the `def _pick_channel_to_preempt` line and the function's last line
      (ruling 7). If any `live:channel:` literal falls outside that function, stop and report: the
      Done criterion needs re-deriving.
- [ ] **Step 5: Confirm the CI label routing this plan claims.**
      Run:
      ```bash
      python3 -c "
      import importlib.util
      spec = importlib.util.spec_from_file_location('td', 'dispatcharr/test_discovery.py')
      m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
      print(m.labels_for_changed_paths([
        'apps/proxy/relay_client.py','apps/proxy/relay_views.py','apps/proxy/relay_urls.py',
        'apps/proxy/relay_serializers.py','apps/proxy/internal_base_url.py','apps/proxy/urls.py',
        'apps/proxy/utils.py','apps/proxy/authorize.py','apps/proxy/stats_views.py',
        'apps/proxy/live_proxy/channel_status.py','apps/proxy/live_proxy/views.py',
        'apps/channels/models.py','apps/channels/api_views.py','apps/channels/tasks.py',
        'apps/m3u/tasks.py','apps/m3u/api_views.py','core/tasks.py',
        'docker/nginx.conf','CLAUDE.md']))
      "
      ```
      Expected exactly:
      `['apps.channels.tests', 'apps.m3u.tests', 'apps.proxy.live_proxy.tests', 'apps.proxy.tests', 'core.tests']`
      If the list is longer, a path in this plan reaches further than expected — report it before
      proceeding, because the Done criteria name those five labels.
- [ ] **Step 6: Start the test container and take a baseline.**
      Run the § Test environment step 1 command in the background, poll until
      `docker exec dispatcharr-testrunner-pr7 pg_isready` answers, then run the five labels:
      `docker exec … dispatcharr-testrunner-pr7 … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests apps.m3u.tests core.tests -v1`
      Expected: OK. A red baseline is a blocker to report, not something to fix here.

---

### Task 2: Extract the shared base-URL resolver and build `relay_client`'s transport

**Files:**
- Create: `apps/proxy/internal_base_url.py`
- Create: `apps/proxy/relay_client.py` (transport only; the five call methods land in Task 5)
- Modify: `apps/proxy/control_plane.py` — delete `_var_only_subject`, `_subject_with_value`,
  `_raise_and_warn_once`, `_validated` and `_host_validation_warned`; rewrite
  `get_control_plane_base_url()` as a `resolve_base_url()` wrapper; drop the now-unused
  `urlsplit`, `split_domain_port` and `redact_url` imports
- Modify: `apps/proxy/internal_auth.py` — sign and verify `request.get_full_path()`
- Modify: `apps/proxy/tests/test_control_plane_client.py` — reset the warn flag on its new home
- Test: `apps/proxy/tests/test_internal_base_url.py` (new),
  `apps/proxy/tests/test_relay_client.py` (new)

**Interfaces:**
- Produces `apps.proxy.internal_base_url.validated_base_url(url: str, var_name: str | None = None) -> str`
  and `apps.proxy.internal_base_url.resolve_base_url(*, override_var: str, modular_host_var: str,
  modular_host_default: str) -> str`.
- Produces `apps.proxy.relay_client.get_relay_control_base_url() -> str`,
  `RelayUnavailable(Exception)`, `RelayRefused(Exception)` (with `.status`), and the private
  `_request(method: str, path: str, *, timeout: tuple[int, int], payload: dict | None = None,
  params: dict | None = None) -> dict`.
- Consumes `apps.proxy.internal_auth.{HEADER_INTERNAL, HEADER_INTERNAL_REQUEST,
  internal_principal_token, build_internal_request_header}`.

- [ ] **Step 1: Write the failing test for the shared resolver.** Create
      `apps/proxy/tests/test_internal_base_url.py`:
      ```python
      """The one D9 resolver, and the two wrappers over it.

      D9 asks for "two thin wrappers over one function". PR 6 shipped the
      function inside control_plane.py, where relay_client cannot reuse it
      without importing a private name across the boundary. These tests pin
      the extracted module and, crucially, that BOTH wrappers resolve to an
      nginx: the relay's only listener speaks the uwsgi protocol
      (docker/uwsgi.relay.ini), so http://relay:5657 is not a thing requests
      can dial, and the relay role runs no nginx of its own (D14).
      """

      import os
      from unittest import mock

      from django.core.exceptions import ImproperlyConfigured
      from django.test import SimpleTestCase

      from apps.proxy import control_plane, internal_base_url, relay_client


      def _env(**values):
          return mock.patch.dict(os.environ, values, clear=True)


      class ResolveBaseUrlTests(SimpleTestCase):
          def setUp(self):
              internal_base_url._host_validation_warned = False
              self.addCleanup(
                  setattr, internal_base_url, "_host_validation_warned", False
              )

          def test_the_explicit_override_wins_and_loses_its_trailing_slash(self):
              with _env(DISPATCHARR_RELAY_BASE_URL="http://front:8443/"):
                  self.assertEqual(
                      relay_client.get_relay_control_base_url(), "http://front:8443"
                  )

          def test_modular_addresses_the_api_role_s_nginx_not_the_relay(self):
              # The ruling that matters: DISPATCHARR_WEB_HOST, not
              # DISPATCHARR_RELAY_HOST. Setting RELAY_HOST must change nothing.
              with _env(DISPATCHARR_ENV="modular", DISPATCHARR_RELAY_HOST="relay"):
                  self.assertEqual(
                      relay_client.get_relay_control_base_url(), "http://web:9191"
                  )
              with _env(
                  DISPATCHARR_ENV="modular",
                  DISPATCHARR_WEB_HOST="api-1",
                  DISPATCHARR_PORT="8080",
              ):
                  self.assertEqual(
                      relay_client.get_relay_control_base_url(), "http://api-1:8080"
                  )

          def test_dev_is_the_single_runserver_process(self):
              with _env(DISPATCHARR_ENV="dev", DISPATCHARR_PORT="9191"):
                  self.assertEqual(
                      relay_client.get_relay_control_base_url(), "http://127.0.0.1:5656"
                  )

          def test_aio_is_loopback_nginx(self):
              with _env():
                  self.assertEqual(
                      relay_client.get_relay_control_base_url(), "http://127.0.0.1:9191"
                  )

          def test_both_directions_share_one_address_and_differ_only_in_override(self):
              with _env(DISPATCHARR_ENV="modular", DISPATCHARR_WEB_HOST="w"):
                  self.assertEqual(
                      relay_client.get_relay_control_base_url(),
                      control_plane.get_control_plane_base_url(),
                  )
              with _env(
                  DISPATCHARR_ENV="modular",
                  DISPATCHARR_WEB_HOST="w",
                  DISPATCHARR_RELAY_BASE_URL="http://elsewhere:1",
              ):
                  self.assertEqual(
                      relay_client.get_relay_control_base_url(), "http://elsewhere:1"
                  )
                  self.assertEqual(
                      control_plane.get_control_plane_base_url(), "http://w:9191"
                  )

          def test_a_host_django_would_refuse_fails_at_resolve_time(self):
              # Amendment S10 point 10: an underscore reaches get_host() as a
              # Host header Django rejects before ALLOWED_HOSTS is consulted.
              with _env(DISPATCHARR_ENV="modular", DISPATCHARR_WEB_HOST="bad_host"):
                  with self.assertRaises(ImproperlyConfigured) as caught:
                      relay_client.get_relay_control_base_url()
              self.assertEqual(caught.exception.var_name, "DISPATCHARR_WEB_HOST")

          def test_a_scheme_less_override_is_named_but_never_echoed(self):
              with _env(DISPATCHARR_RELAY_BASE_URL="user:pw@relay:9191"):
                  with self.assertRaises(ImproperlyConfigured) as caught:
                      relay_client.get_relay_control_base_url()
              self.assertIn("DISPATCHARR_RELAY_BASE_URL", str(caught.exception))
              self.assertNotIn("pw", str(caught.exception))
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_internal_base_url -v1`
      Expected: FAIL — `ModuleNotFoundError: No module named 'apps.proxy.internal_base_url'`.
- [ ] **Step 2: Create `apps/proxy/internal_base_url.py`,** moving PR 6's four helpers and the
      warn flag across unchanged and adding the parameterised resolver. Copy
      `_var_only_subject`, `_subject_with_value`, `_raise_and_warn_once` and the body of
      `_validated` **verbatim** from `control_plane.py`, including their docstrings and comments —
      they carry the reasoning for every check and re-deriving it is how it gets lost. Rename
      `_validated` to `validated_base_url` and give the module this header:
      ```python
      """One address resolver and one host check, shared by both internal directions.

      Phase 1 D9: "two thin wrappers over one function". PR 6 shipped the
      function inside apps/proxy/control_plane.py, which is the relay's side
      of the boundary; PR 7 needs the same formula on Django's side, and a
      private name imported across that boundary would be a worse coupling
      than a shared module.

      Both wrappers resolve to an address served by **nginx**, never to a raw
      application port:

        relay -> Django   apps/proxy/control_plane.get_control_plane_base_url()
                          DISPATCHARR_INTERNAL_API_BASE_URL, else the api
                          role's nginx.
        Django -> relay   apps/proxy/relay_client.get_relay_control_base_url()
                          DISPATCHARR_RELAY_BASE_URL, else the SAME nginx,
                          which routes ^~ /proxy/relay/ to the relay_py
                          upstream (docker/nginx.conf).

      The second one is why the modular branch reads DISPATCHARR_WEB_HOST for
      both directions rather than DISPATCHARR_RELAY_HOST as D9's text says.
      docker/uwsgi.relay.ini gives the relay exactly one listener,
      `socket = 0.0.0.0:$(DISPATCHARR_RELAY_PORT)`, which speaks the uwsgi
      protocol -- requests cannot dial it -- and D14 gives the relay role no
      nginx of its own, so nothing answers HTTP in that container at all.
      D5 states the resolution: "D9 routes Django's control calls through
      nginx as well, so nothing ever dials a raw HTTP port on the relay."
      DISPATCHARR_RELAY_HOST keeps its one job, the RELAY_UPSTREAM sed in
      docker/init/03-init-dispatcharr.sh; DISPATCHARR_RELAY_BASE_URL is the
      escape hatch for a deployment that does front the relay directly.
      """

      import logging
      import os
      from urllib.parse import urlsplit

      from django.core.exceptions import ImproperlyConfigured
      from django.http.request import split_domain_port

      from dispatcharr.utils import redact_url

      logger = logging.getLogger(__name__)

      # Set once we have logged the ImproperlyConfigured message for this
      # process, so a misconfigured deployment writes one explanation rather
      # than one per call. Callers still see the exception every time.
      _host_validation_warned = False
      ```
      Then append the resolver:
      ```python
      def resolve_base_url(*, override_var, modular_host_var, modular_host_default):
          """The D9 four-branch formula, once, for whichever direction asks.

          Same shape as get_dvr_stream_base_url() (apps/channels/tasks.py),
          which D9 names as the formula it borrows: explicit override, then
          modular by service name, then dev, then AIO through nginx on
          DISPATCHARR_PORT. Every branch validates before returning, so a
          misconfigured host fails loudly here instead of as an opaque 400.

          The dev branch has no nginx to go through, so it names the
          application port directly. What answers there depends on how dev
          was started: a bare `manage.py runserver 5656` is one process
          serving both sides, while docker/supervisord/all-dev.conf runs
          api-uwsgi AND relay-uwsgi with no nginx, so :5656 is the API
          uWSGI and /proxy/relay/... is served by the API process. Both
          work -- one Redis, and ChannelService reaches a channel's owner
          over live:events: pub/sub either way -- but the second cannot
          clear a StreamManager it does not hold (see reset_tried).
          """
          explicit = os.environ.get(override_var)
          if explicit:
              return validated_base_url(explicit.rstrip("/"), override_var)
          env = os.environ.get("DISPATCHARR_ENV", "aio").lower()
          if env == "modular":
              host = os.environ.get(modular_host_var, modular_host_default)
              port = os.environ.get("DISPATCHARR_PORT", "9191")
              return validated_base_url(f"http://{host}:{port}", modular_host_var)
          if env == "dev":
              # Hardcoded, not read from DISPATCHARR_PORT: in dev the port
              # that answers is uWSGI's / runserver's own, not nginx's, and
              # DISPATCHARR_PORT names vite's (CLAUDE.md section Commands).
              return validated_base_url("http://127.0.0.1:5656")
          port = os.environ.get("DISPATCHARR_PORT", "9191")
          return validated_base_url(f"http://127.0.0.1:{port}")
      ```
- [ ] **Step 3: Rewrite `control_plane.get_control_plane_base_url()` as a wrapper** and delete the
      five moved names from that module:
      ```python
      from apps.proxy.internal_base_url import resolve_base_url


      def get_control_plane_base_url():
          """Where Django answers, for this deployment shape (D9).

          One line, because the formula now lives in internal_base_url beside
          relay_client's mirror image of it -- see that module's docstring for
          why both directions resolve to the same nginx.
          """
          return resolve_base_url(
              override_var="DISPATCHARR_INTERNAL_API_BASE_URL",
              modular_host_var="DISPATCHARR_WEB_HOST",
              modular_host_default="web",
          )
      ```
      Delete `_var_only_subject`, `_subject_with_value`, `_raise_and_warn_once`, `_validated` and
      `_host_validation_warned` from `control_plane.py`, and delete the `urlsplit`,
      `split_domain_port` and `redact_url` imports, which nothing else in that file uses.
      Run: `grep -n "urlsplit\|split_domain_port\|redact_url\|_validated\|_host_validation_warned" apps/proxy/control_plane.py`
      Expected: no output.
- [ ] **Step 4: Retarget the existing control-plane tests at the flag's new home.**
      In `apps/proxy/tests/test_control_plane_client.py`, replace every
      `control_plane._host_validation_warned = False` and every
      `self.addCleanup(setattr, control_plane, "_host_validation_warned", False)` with the same
      two lines against `internal_base_url`, importing it beside `control_plane`. Retarget **every
      occurrence** rather than a fixed number of them; find them with
      `grep -n "_host_validation_warned" apps/proxy/tests/test_control_plane_client.py`, and re-run
      that grep afterwards expecting every hit to name `internal_base_url`.
      Change nothing else in that file: every assertion about branch order, redaction and
      exception type still holds, because the code moved rather than changed.
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_control_plane_client apps.proxy.tests.test_internal_base_url -v1`
      Expected: OK, both modules.
- [ ] **Step 5: Write the failing test for signing the query string.** Append to
      `apps/proxy/tests/test_internal_auth.py`:
      ```python
      class BoundTokenCoversTheQueryStringTests(TestCase):
          """PR 7: the bound token signs the full path, query string included.

          PR 6 signed request.path, which no caller of /api/relay/... could
          tell apart from the full path -- none of its three routes takes a
          query parameter. PR 7's GET /proxy/relay/channels does
          (?clients=all, which decides whether the response carries every
          client or the stats surface's first ten), and an unsigned query
          string is a parameter a replay inside the 120s window could flip.
          request.get_full_path() equals request.path when there is no query,
          so PR 6's already-shipped calls verify unchanged.
          """

          def test_a_signature_for_the_bare_path_does_not_clear_a_query_string(self):
              header = build_internal_request_header("GET", "/proxy/relay/channels", b"")
              request = RequestFactory().get(
                  "/proxy/relay/channels",
                  {"clients": "all"},
                  **{META_INTERNAL_REQUEST: header},
              )
              self.assertFalse(request_is_internal_request(request))

          def test_a_signature_for_the_full_path_clears_it(self):
              header = build_internal_request_header(
                  "GET", "/proxy/relay/channels?clients=all", b""
              )
              request = RequestFactory().get(
                  "/proxy/relay/channels",
                  {"clients": "all"},
                  **{META_INTERNAL_REQUEST: header},
              )
              self.assertTrue(request_is_internal_request(request))

          def test_a_path_with_no_query_is_unchanged_from_pr_6(self):
              header = build_internal_request_header("POST", "/api/relay/events", b"{}")
              request = RequestFactory().post(
                  "/api/relay/events",
                  data=b"{}",
                  content_type="application/json",
                  **{META_INTERNAL_REQUEST: header},
              )
              self.assertTrue(request_is_internal_request(request))
      ```
      Add whatever imports that file is missing (`RequestFactory`, `META_INTERNAL_REQUEST`,
      `build_internal_request_header`, `request_is_internal_request`) — check what is already
      imported before adding.
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_internal_auth -v1`
      Expected: FAIL on the first two tests.
- [ ] **Step 6: Sign the full path.** In `apps/proxy/internal_auth.py`, change the one line in
      `request_is_internal_request`:
      ```python
          expected = internal_request_token(
              # get_full_path(), not path: the query string is part of what a
              # caller is asking for, so it has to be part of what the token
              # binds (PR 7). They are the same string when there is no query,
              # which is why every call PR 6 shipped verifies unchanged.
              request.method, request.get_full_path(), request.body, timestamp
          )
      ```
      and extend `build_internal_request_header`'s docstring with one line: *"`path` is the full
      path the caller will request, query string included — `request.get_full_path()` on the other
      side."*
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests -v1`
      Expected: OK — including `test_next_source_api` and `test_internal_relay_permission`, whose
      calls carry no query string.
- [ ] **Step 7: Write the failing test for `relay_client`'s transport.** Create
      `apps/proxy/tests/test_relay_client.py`:
      ```python
      """Django's side of the Django->relay boundary (Phase 1 PR 7, D9/D10).

      Only the transport here; the five call methods are tested in
      test_relay_control_api.py against the real routes.
      """

      import os
      from unittest import mock

      import requests
      from django.test import SimpleTestCase

      from apps.proxy import internal_auth, relay_client


      class _Response:
          def __init__(self, status_code, body=b"{}", json_value=mock.sentinel.use_body):
              self.status_code = status_code
              self.content = body
              self._json = json_value

          def json(self):
              if self._json is mock.sentinel.use_body:
                  import json as _json

                  return _json.loads(self.content)
              if isinstance(self._json, Exception):
                  raise self._json
              return self._json


      class RelayClientTransportTests(SimpleTestCase):
          def setUp(self):
              patcher = mock.patch.dict(
                  os.environ, {"DISPATCHARR_ENV": "aio"}, clear=True
              )
              patcher.start()
              self.addCleanup(patcher.stop)

          def test_every_call_carries_both_internal_headers(self):
              with mock.patch.object(
                  requests, "request", return_value=_Response(200)
              ) as sent:
                  relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
              headers = sent.call_args.kwargs["headers"]
              self.assertEqual(
                  headers[internal_auth.HEADER_INTERNAL],
                  internal_auth.internal_principal_token(),
              )
              self.assertTrue(
                  headers[internal_auth.HEADER_INTERNAL_REQUEST].startswith("v1.")
              )

          def test_the_signature_covers_the_query_string(self):
              with mock.patch.object(
                  requests, "request", return_value=_Response(200)
              ) as sent:
                  relay_client._request(
                      "GET",
                      "/proxy/relay/channels",
                      timeout=(1, 2),
                      params={"clients": "all"},
                  )
              url = sent.call_args.args[1]
              self.assertTrue(url.endswith("/proxy/relay/channels?clients=all"))
              header = sent.call_args.kwargs["headers"][
                  internal_auth.HEADER_INTERNAL_REQUEST
              ]
              _v, timestamp, digest = header.split(".")
              self.assertEqual(
                  digest,
                  internal_auth.internal_request_token(
                      "GET", "/proxy/relay/channels?clients=all", b"", int(timestamp)
                  ),
              )

          def test_a_redirect_is_never_followed(self):
              with mock.patch.object(
                  requests, "request", return_value=_Response(301)
              ) as sent:
                  with self.assertRaises(relay_client.RelayUnavailable):
                      relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
              self.assertIs(sent.call_args.kwargs["allow_redirects"], False)

          def test_a_4xx_is_a_refusal_not_an_outage(self):
              with mock.patch.object(requests, "request", return_value=_Response(403)):
                  with self.assertRaises(relay_client.RelayRefused) as caught:
                      relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
              self.assertEqual(caught.exception.status, 403)
              self.assertNotIsInstance(
                  caught.exception, relay_client.RelayUnavailable
              )

          def test_a_5xx_and_a_transport_error_are_both_outages(self):
              with mock.patch.object(requests, "request", return_value=_Response(502)):
                  with self.assertRaises(relay_client.RelayUnavailable):
                      relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
              with mock.patch.object(
                  requests, "request", side_effect=requests.ConnectionError("nope")
              ):
                  with self.assertRaises(relay_client.RelayUnavailable):
                      relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))

          def test_nothing_is_retried(self):
              # A retried advance switches twice; a retried tune-path read
              # blows the relay's own 5s next-source budget (ruling 13).
              with mock.patch.object(
                  requests, "request", side_effect=requests.ConnectionError("nope")
              ) as sent:
                  with self.assertRaises(relay_client.RelayUnavailable):
                      relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
              self.assertEqual(sent.call_count, 1)

          def test_a_2xx_that_is_not_a_json_object_is_an_outage(self):
              for body in (_Response(200, json_value=ValueError("no")), _Response(200, json_value=[1])):
                  with mock.patch.object(requests, "request", return_value=body):
                      with self.assertRaises(relay_client.RelayUnavailable):
                          relay_client._request(
                              "GET", "/proxy/relay/channels", timeout=(1, 2)
                          )

          def test_an_empty_body_is_an_empty_dict_not_an_error(self):
              with mock.patch.object(
                  requests, "request", return_value=_Response(204, body=b"")
              ):
                  self.assertEqual(
                      relay_client._request(
                          "DELETE", "/proxy/relay/channels/x", timeout=(2, 5)
                      ),
                      {},
                  )

          def test_the_three_timeout_budgets_are_named_constants(self):
              self.assertEqual(relay_client.TUNE_TIMEOUT, (1, 2))
              self.assertEqual(relay_client.ADMIN_TIMEOUT, (2, 5))
              # 15s is STREAM_SWITCH_CONFIRM_TIMEOUT in ChannelService.
              self.assertGreater(relay_client.ADVANCE_TIMEOUT[1], 15)
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_client -v1`
      Expected: FAIL — `ModuleNotFoundError: No module named 'apps.proxy.relay_client'`.
- [ ] **Step 8: Create `apps/proxy/relay_client.py`** with the module header and the transport:
      ```python
      """Django's side of the boundary: how the control plane asks the relay things.

      Phase 1 PR 7, D9 and D10. Five routes, all reached through the api
      role's nginx, which routes `location ^~ /proxy/relay/` to the relay_py
      upstream -- never to a raw application port, because the relay has no
      HTTP listener at all (D5):

        GET    /proxy/relay/channels[?clients=all]           list
        GET    /proxy/relay/channels/<id>[?fields=state]     one channel
        DELETE /proxy/relay/channels/<identifier>            stop the channel
        DELETE /proxy/relay/channels/<id>/clients/<client>   stop one client
        POST   /proxy/relay/channels/<identifier>/advance    switch source

      D10 in one sentence: nothing under apps/proxy/live_proxy/,
      apps/proxy/vod_proxy/ or apps/timeshift/'s streaming path may import
      this module. The in-relay ChannelService statics are called 25 times
      from inside the relay and are untouched; only the Django-side callers
      move here. apps/proxy/live_proxy/views.py is the one file on both
      sides of that line -- its five IsAdmin views run in the API process
      after PR 4's routing -- so it imports this module function-locally,
      inside those five views only.

      Three timeout budgets, no retries anywhere:

        TUNE_TIMEOUT    (1, 2)   reads reached from Channel.get_stream(),
                                 which itself runs inside the relay's
                                 next-source call with a 5s read timeout.
                                 Three seconds worst case leaves room.
        ADMIN_TIMEOUT   (2, 5)   reads and stops behind an admin request.
        ADVANCE_TIMEOUT (2, 20)  ChannelService.change_stream_url polls
                                 RedisKeys.switch_status for up to
                                 STREAM_SWITCH_CONFIRM_TIMEOUT = 15s on the
                                 non-owner path before answering.

      No retry, deliberately: a retried advance switches twice, a retried
      stop doubles an admin's wait for an operation the relay has already
      recorded, and a retried tune-path read exceeds the budget above.
      control_plane's single retry exists because a failed next-source
      strands a viewer; none of these five do.

      Nothing logged here names a URL: scripts/check_credential_logging.py
      cannot see what a caller formats, and a relay path carries a channel
      UUID, which CLAUDE.md treats as a secret.
      """

      import json
      import logging
      from urllib.parse import urlencode

      import requests

      from apps.proxy.internal_auth import (
          HEADER_INTERNAL,
          HEADER_INTERNAL_REQUEST,
          build_internal_request_header,
          internal_principal_token,
      )
      from apps.proxy.internal_base_url import resolve_base_url

      logger = logging.getLogger(__name__)

      TUNE_TIMEOUT = (1, 2)
      ADMIN_TIMEOUT = (2, 5)
      ADVANCE_TIMEOUT = (2, 20)


      class RelayUnavailable(Exception):
          """The relay could not be reached, or answered 5xx, or redirected."""


      class RelayRefused(Exception):
          """The relay answered, and said no. Not a subclass of RelayUnavailable:
          a 404 for an unknown channel and a 403 from a SECRET_KEY mismatch are
          answers, and a caller that treats them as an outage hides both."""

          def __init__(self, status, path):
              # The path, never the body and never the full URL.
              self.status = status
              super().__init__(f"{path} refused with {status}")


      def get_relay_control_base_url():
          """Where the relay answers, for this deployment shape (D9)."""
          return resolve_base_url(
              override_var="DISPATCHARR_RELAY_BASE_URL",
              modular_host_var="DISPATCHARR_WEB_HOST",
              modular_host_default="web",
          )


      def _request(method, path, *, timeout, payload=None, params=None):
          """One signed call. Raises RelayUnavailable or RelayRefused."""
          body = json.dumps(payload).encode() if payload is not None else b""
          full_path = f"{path}?{urlencode(params)}" if params else path
          headers = {
              HEADER_INTERNAL: internal_principal_token(),
              HEADER_INTERNAL_REQUEST: build_internal_request_header(
                  method, full_path, body
              ),
          }
          if payload is not None:
              headers["Content-Type"] = "application/json"
          url = get_relay_control_base_url() + full_path
          try:
              response = requests.request(
                  method,
                  url,
                  data=body or None,
                  headers=headers,
                  timeout=timeout,
                  # Never followed: requests re-sends a redirected request
                  # with every custom header intact, so a stray `return 301`
                  # would forward the signed internal headers off this
                  # deployment. Treated as an outage below instead.
                  allow_redirects=False,
              )
          except requests.RequestException as exc:
              raise RelayUnavailable(f"{path} unreachable: {exc}") from exc
          if 300 <= response.status_code < 400:
              raise RelayUnavailable(f"{path} redirected with {response.status_code}")
          if response.status_code >= 500:
              raise RelayUnavailable(f"{path} answered {response.status_code}")
          if response.status_code >= 400:
              raise RelayRefused(response.status_code, path)
          if not response.content:
              return {}
          try:
              answer = response.json()
          except ValueError as exc:
              raise RelayUnavailable(
                  f"{path} answered 2xx with a non-JSON body"
              ) from exc
          if not isinstance(answer, dict):
              raise RelayUnavailable(f"{path} answered 2xx with a non-object body")
          return answer
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_client -v1`
      Expected: OK.
- [ ] **Step 9: Run the credential-logging guard and the boot check.**
      Run: `python3 scripts/check_credential_logging.py apps/proxy/internal_base_url.py apps/proxy/relay_client.py apps/proxy/control_plane.py apps/proxy/internal_auth.py`
      Expected: exit 0, no output.
      Run: `docker exec … manage.py check`
      Expected: `System check identified no issues`.
- [ ] **Step 10: Commit.** Write the message with the Write tool to
      `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr7-t2.txt`:
      ```
      feat(phase1-pr7): one D9 resolver for both directions, and relay_client's transport

      Extract PR 6's host check and base-URL formula from control_plane into
      apps/proxy/internal_base_url.py so Django's side can reuse it instead of
      importing a private name across the boundary. Both wrappers resolve to
      the api role's nginx: the relay's only listener speaks the uwsgi
      protocol and the relay role runs no nginx, so DISPATCHARR_RELAY_HOST
      names nothing requests can dial. DISPATCHARR_RELAY_BASE_URL is the
      override for a deployment that does front it.

      The bound internal token now signs request.get_full_path() rather than
      request.path, so the ?clients=all parameter PR 7 adds is covered. Every
      call PR 6 shipped verifies unchanged: the two strings are equal when
      there is no query string.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Run the commit gate, then in one Bash call:
      `git add apps/proxy/internal_base_url.py apps/proxy/relay_client.py apps/proxy/control_plane.py apps/proxy/internal_auth.py apps/proxy/tests/test_internal_base_url.py apps/proxy/tests/test_relay_client.py apps/proxy/tests/test_control_plane_client.py apps/proxy/tests/test_internal_auth.py`
      and in a **separate** Bash call:
      `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr7-t2.txt`

---

### Task 3: Normalise the status payload and make the client cap a parameter

**Files:**
- Modify: `apps/proxy/live_proxy/channel_status.py` — `get_detailed_channel_info`'s `state` default
  and `ffmpeg_speed` type, three added video fields, and a `client_limit` keyword on
  `get_basic_channel_info` and `build_live_channel_stats_data`
- Modify: `e2e/fixtures/types.ts` — `ChannelStatus.ffmpeg_speed`, `state`, three added fields
- Modify: `e2e/tests/streaming/stream-profiles.spec.ts` — `ffmpeg_speed` is a number now
- Test: `apps/proxy/tests/test_relay_status_shape.py` (new)

**Interfaces:**
- Produces `ChannelStatus.get_basic_channel_info(channel_id, client_limit=10)` and
  `build_live_channel_stats_data(redis_client, client_limit=10)`; `client_limit=None` means
  uncapped.
- Consumes `apps.proxy.live_proxy.constants.ChannelMetadataField.{WIDTH, HEIGHT, VIDEO_BITRATE}`
  (already defined, values `"width"`, `"height"`, `"video_bitrate"`).

**What is deliberately not changed here.** `owner`'s `'unknown'` default in the detailed payload,
and `source_fps`' string-vs-float divergence between the two functions, are the same class of bug
as the two the spec names and are **carried, not fixed** — the spec names two fields and
`e2e/fixtures/types.ts` already documents `owner: string | null` against the first. Do not widen.

- [ ] **Step 1: Write the failing tests.** Create `apps/proxy/tests/test_relay_status_shape.py`:
      ```python
      """The status payload's two type fixes, three additions and one parameter.

      CLAUDE.md section Observing a channel records that get_detailed_channel_info
      and get_basic_channel_info disagree about ffmpeg_speed's type and state's
      default. PR 7 puts both behind one DRF serializer, so they have to agree
      first. The three added fields exist because the DVR's metadata read moves
      onto this payload (ruling 5) and reads width, height and video_bitrate,
      which the detailed builder never emitted.
      """

      from unittest import mock

      from django.test import SimpleTestCase

      from apps.proxy.live_proxy import channel_status
      from apps.proxy.live_proxy.channel_status import (
          ChannelStatus,
          build_live_channel_stats_data,
      )


      def _metadata(**overrides):
          data = {
              "url": "http://provider.example/live",
              "stream_profile": "3",
              "owner": "worker-1",
              "init_time": "1000.0",
              "total_bytes": "2048",
              "video_codec": "h264",
              "resolution": "1920x1080",
              "width": "1920",
              "height": "1080",
              "video_bitrate": "4200",
              "source_fps": "25.0",
              "audio_codec": "aac",
              "audio_channels": "2",
              "stream_type": "hls",
              "ffmpeg_speed": "1.02",
          }
          data.update(overrides)
          return data


      class _FakeRedis:
          """Only the calls both info builders make."""

          def __init__(self, metadata, client_ids=(), client_hashes=None):
              self._metadata = metadata
              self._client_ids = set(client_ids)
              self._client_hashes = client_hashes or {}

          def hgetall(self, key):
              if key.endswith(":metadata"):
                  return dict(self._metadata)
              return dict(self._client_hashes.get(key, {}))

          def get(self, key):
              return "7" if key.endswith(":index") else None

          def smembers(self, key):
              return set(self._client_ids)

          def scard(self, key):
              return len(self._client_ids)

          def srem(self, key, *members):
              return 0

          def exists(self, key):
              return 1

          def ttl(self, key):
              return 60

          def hmget(self, key, *fields):
              row = self._client_hashes.get(key, {})
              return [row.get(f) for f in fields]

          def scan(self, cursor, match=None, count=None):
              return 0, ["live:channel:abc:metadata"]


      class DetailedInfoTypeTests(SimpleTestCase):
          def _detailed(self, **overrides):
              fake = _FakeRedis(_metadata(**overrides))
              server = mock.Mock(redis_client=fake, stream_managers={})
              with mock.patch.object(
                  channel_status.ProxyServer, "get_instance", return_value=server
              ):
                  return ChannelStatus.get_detailed_channel_info("abc")

          def test_ffmpeg_speed_is_a_float_not_the_raw_redis_string(self):
              self.assertEqual(self._detailed()["ffmpeg_speed"], 1.02)

          def test_an_unparseable_ffmpeg_speed_is_omitted_rather_than_a_500(self):
              self.assertNotIn("ffmpeg_speed", self._detailed(ffmpeg_speed="N/A"))

          def test_state_is_null_when_absent_never_the_string_unknown(self):
              self.assertIsNone(self._detailed()["state"])

          def test_state_is_reported_when_present(self):
              self.assertEqual(self._detailed(state="active")["state"], "active")

          def test_the_three_dvr_video_fields_are_present_as_raw_strings(self):
              info = self._detailed()
              self.assertEqual(info["width"], "1920")
              self.assertEqual(info["height"], "1080")
              self.assertEqual(info["video_bitrate"], "4200")

          def test_the_three_dvr_fields_are_absent_when_redis_has_none(self):
              fake = _FakeRedis(
                  {k: v for k, v in _metadata().items()
                   if k not in ("width", "height", "video_bitrate")}
              )
              server = mock.Mock(redis_client=fake, stream_managers={})
              with mock.patch.object(
                  channel_status.ProxyServer, "get_instance", return_value=server
              ):
                  info = ChannelStatus.get_detailed_channel_info("abc")
              for field in ("width", "height", "video_bitrate"):
                  self.assertNotIn(field, info)


      class ClientLimitTests(SimpleTestCase):
          def _fake(self):
              ids = [f"c{i}" for i in range(14)]
              hashes = {
                  f"live:channel:abc:clients:{cid}": {
                      "user_agent": "vlc",
                      "ip_address": "10.0.0.1",
                      "connected_at": "1000.0",
                      "user_id": "5",
                      "output_format": "mpegts",
                      "output_profile_id": "",
                  }
                  for cid in ids
              }
              return _FakeRedis(_metadata(), client_ids=ids, client_hashes=hashes)

          def _basic(self, **kwargs):
              fake = self._fake()
              server = mock.Mock(redis_client=fake, stream_managers={})
              with mock.patch.object(
                  channel_status.ProxyServer, "get_instance", return_value=server
              ), mock.patch.object(
                  channel_status.ClientManager, "remove_ghost_clients", return_value=set()
              ):
                  return ChannelStatus.get_basic_channel_info("abc", **kwargs)

          def test_the_default_keeps_the_stats_payload_capped_at_ten(self):
              self.assertEqual(len(self._basic()["clients"]), 10)

          def test_client_limit_none_returns_every_client(self):
              # get_user_active_connections counts a user's connections; a cap
              # would under-count and let a viewer past their stream limit.
              self.assertEqual(len(self._basic(client_limit=None)["clients"]), 14)

          def test_client_count_is_the_true_count_either_way(self):
              self.assertEqual(self._basic()["client_count"], 14)

          def test_build_live_channel_stats_data_passes_the_limit_through(self):
              fake = self._fake()
              server = mock.Mock(redis_client=fake, stream_managers={})
              with mock.patch.object(
                  channel_status.ProxyServer, "get_instance", return_value=server
              ), mock.patch.object(
                  channel_status.ClientManager, "remove_ghost_clients", return_value=set()
              ):
                  capped = build_live_channel_stats_data(fake)
                  full = build_live_channel_stats_data(fake, client_limit=None)
              self.assertEqual(len(capped["channels"][0]["clients"]), 10)
              self.assertEqual(len(full["channels"][0]["clients"]), 14)
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_status_shape -v1`
      Expected: FAIL — `ffmpeg_speed` is `'1.02'`, `state` is `'unknown'`, the three fields are
      missing, and `get_basic_channel_info` takes no `client_limit`.
- [ ] **Step 2: Fix `state` and `ffmpeg_speed` in `get_detailed_channel_info`.** Change the `state`
      entry of the `info` dict literal:
      ```python
              'state': metadata.get(ChannelMetadataField.STATE),
      ```
      and replace the `ffmpeg_speed` block near the end of the function:
      ```python
              # A float, matching get_basic_channel_info. The two builders used
              # to disagree about this field's type -- CLAUDE.md section
              # Observing a channel -- which is not a difference a single DRF
              # serializer can carry. An unparseable value is omitted rather
              # than raised: the same shape as the int() parses above, and a
              # malformed Redis value must not 500 an admin's status request.
              ffmpeg_speed = metadata.get(ChannelMetadataField.FFMPEG_SPEED)
              if ffmpeg_speed:
                  try:
                      info['ffmpeg_speed'] = float(ffmpeg_speed)
                  except (TypeError, ValueError):
                      logger.warning(
                          f"Invalid ffmpeg_speed format in Redis: {ffmpeg_speed}"
                      )
      ```
      Note the indentation: `get_detailed_channel_info` has no `@staticmethod` decorator and its
      body sits one level inside `class ChannelStatus`.
- [ ] **Step 3: Add the three DVR video fields,** beside `resolution` and `source_fps` in the same
      function:
      ```python
              # width, height and video_bitrate join the eight sibling fields
              # already here because apps/channels/tasks.py's run_recording
              # stores all eleven under Recording.custom_properties
              # ["stream_info"], and PR 7 moves that read off Redis and onto
              # this payload. Raw strings, exactly like their siblings, so the
              # DVR keeps its own caster and the stored dict is unchanged.
              width = metadata.get(ChannelMetadataField.WIDTH)
              if width:
                  info['width'] = width

              height = metadata.get(ChannelMetadataField.HEIGHT)
              if height:
                  info['height'] = height

              video_bitrate = metadata.get(ChannelMetadataField.VIDEO_BITRATE)
              if video_bitrate:
                  info['video_bitrate'] = video_bitrate
      ```
- [ ] **Step 4: Make the client cap a parameter.** Change `get_basic_channel_info`'s signature and
      the one slice inside it:
      ```python
          @staticmethod
          def get_basic_channel_info(channel_id, client_limit=10):
              """Get basic channel information with Redis error handling.

              client_limit caps the `clients` list: 10 is what the Stats page
              and /proxy/stats/ have always shown, and None returns every
              client, which is what get_user_active_connections needs to count
              a user's connections without under-counting past ten on one
              channel. `client_count` is a SCARD either way and is never
              capped.
              """
      ```
      and, at the client-list loop:
      ```python
                  if client_ids:
                      listed = list(client_ids)
                      if client_limit is not None:
                          listed = listed[:client_limit]
                      for client_id in listed:
      ```
      Then thread it through the collection builder:
      ```python
      def build_live_channel_stats_data(redis_client, client_limit=10):
          """Scan Redis for live channel metadata and build the stats payload.

          client_limit is passed straight to get_basic_channel_info; see there.
          """
      ```
      and at its one call site inside that function:
      ```python
                      channel_info = ChannelStatus.get_basic_channel_info(
                          ch_id, client_limit=client_limit
                      )
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_status_shape -v1`
      Expected: OK.
- [ ] **Step 5: Run the whole proxy and live_proxy suites,** because `get_basic_channel_info` is
      what `/proxy/stats/` and the `channel_stats` WebSocket payload are built from.
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests -v1`
      Expected: OK. If `apps/proxy/tests/test_combined_stats.py` fails on a client count or an
      `ffmpeg_speed` string, read it: the fix belongs in that test only if it asserted the old
      type; if it asserted the ten-client cap, it should still pass and a failure means Step 4's
      default is wrong.
- [ ] **Step 6: Update the e2e type, which is the only consumer of the detailed payload.**
      In `e2e/fixtures/types.ts`, replace the `ffmpeg_speed` paragraph of the `ChannelStatus`
      doc comment with:
      ```ts
       * `ffmpeg_speed` is a `number`. It used to be a `string` here and a `number` on
       * the bare `/proxy/ts/status` collection endpoint, because
       * `get_detailed_channel_info` passed the raw Redis value through while
       * `get_basic_channel_info` wrapped it in `float()`. Phase 1 PR 7 put both
       * behind one DRF serializer on `GET /proxy/relay/channels`, which meant they
       * had to agree first. `state` moved the same way: `null` when the channel has
       * never recorded one, rather than the string `'unknown'`. `owner` keeps its
       * `'unknown'` default — the same bug, deliberately left, since the spec names
       * two fields and not three.
      ```
      and the type members:
      ```ts
        state: string | null;
        ffmpeg_speed?: number;
        video_codec?: string;
        resolution?: string;
        /** Raw Redis strings, added in PR 7 for the DVR's `stream_info` capture. */
        width?: string;
        height?: string;
        video_bitrate?: string;
      ```
- [ ] **Step 7: Fix the one spec that parses the value.** In
      `e2e/tests/streaming/stream-profiles.spec.ts`, replace the comment and the poll body:
      ```ts
        // ffmpeg-derived fields appear on /status only for subprocess profiles.
        // Without this the row is indistinguishable from the Proxy row — and this is
        // the first test in this repository of any kind that spawns a subprocess.
        //
        // ffmpeg_speed is a number since Phase 1 PR 7 normalised the detailed and
        // collection payloads to one type; it used to arrive here as a string and
        // needed parsing.
        await expect
          .poll(
            async () => (await readChannelStatus(api, channel.uuid)).ffmpeg_speed ?? 0,
            { timeout: 60_000 }
          )
          .toBeGreaterThan(0);
      ```
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/e2e && npx tsc --noEmit`
      Expected: clean. A `Number.parseFloat` left anywhere against this field is a type error, and
      that is the point of the check.
- [ ] **Step 8: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/proxy/live_proxy/channel_status.py`
      Expected: exit 0.
      Write the message to `…/scratchpad/pr7-t3.txt`:
      ```
      fix(phase1-pr7): the two status payloads agree on ffmpeg_speed and state

      get_detailed_channel_info emitted ffmpeg_speed as the raw Redis string and
      defaulted state to 'unknown'; get_basic_channel_info emitted a float and
      left state None. PR 7 puts both behind one DRF serializer, which is not a
      thing that can carry the disagreement, so the detailed builder moves to
      the collection builder's types.

      width, height and video_bitrate join the eight sibling video fields
      already on that payload, because the DVR's metadata read moves onto it in
      a later commit and stores all eleven. Raw strings like their siblings, so
      Recording.custom_properties["stream_info"] is unchanged.

      get_basic_channel_info's ten-client cap becomes a parameter.
      get_user_active_connections counts a user's connections and a cap would
      under-count; /proxy/stats/ and the Stats page keep the default.

      owner's identical 'unknown' default and source_fps' identical
      string-vs-float split are carried, not fixed.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Run the commit gate, then `git add apps/proxy/live_proxy/channel_status.py apps/proxy/tests/test_relay_status_shape.py e2e/fixtures/types.ts e2e/tests/streaming/stream-profiles.spec.ts`
      in one Bash call and `git commit -F …/scratchpad/pr7-t3.txt` in a separate one.

---

### Task 4: The five relay control routes

**Files:**
- Create: `apps/proxy/relay_serializers.py`
- Create: `apps/proxy/relay_views.py`
- Create: `apps/proxy/relay_urls.py`
- Modify: `apps/proxy/urls.py` — one `path('relay/', include(...))` line
- Test: `apps/proxy/tests/test_relay_control_api.py` (new)

**Interfaces:**
- Produces `GET /proxy/relay/channels[?clients=all]`, `GET /proxy/relay/channels/<identifier>`,
  `DELETE /proxy/relay/channels/<identifier>`,
  `DELETE /proxy/relay/channels/<identifier>/clients/<client_id>`,
  `POST /proxy/relay/channels/<identifier>/advance`.
- Produces `RelayChannelListSerializer`, `RelayChannelSerializer`, `RelayChannelClientSerializer`,
  `RelayChannelDetailSerializer`, `RelayDetailClientSerializer`, `RelayChannelStateSerializer`,
  `RelayStopResponseSerializer`, `RelayAdvanceRequestSerializer`, `RelayAdvanceResponseSerializer`.
- Consumes `apps.proxy.permissions.IsInternalRelay`,
  `apps.proxy.live_proxy.channel_status.{ChannelStatus, build_live_channel_stats_data}`,
  `apps.proxy.live_proxy.services.channel_service.ChannelService`.

**Why the fields are declared `required=False`.** Both info builders assign optional keys inside
conditionals, so a key can be **absent entirely** rather than null — the behaviour `CLAUDE.md`
§ Observing a channel documents and `e2e/fixtures/types.ts` encodes. DRF's `Field.get_attribute`
raises `SkipField` for a missing key when `required=False` **and neither `default=` nor
`allow_null=True` is set** — in DRF 3.17.1 (`rest_framework/fields.py`, `Field.get_attribute`) the
`except (KeyError, AttributeError)` branch checks `default` first, then `allow_null`, and only then
`required`. So a serializer declared this way renders the same JSON the hand-built dict does,
absences included, **for every field that is not `allow_null=True`**. Do not add `default=` to any
of them, and read the next sentence before adding `allow_null=True` to one: **either one turns an
absence into a null and changes the wire.**

The four `allow_null=True` fields below (`state`, `url`, `stream_profile`, `owner`) are safe on the
full payloads only because both info builders assign all four unconditionally — checked against
`get_basic_channel_info`'s `info = {...}` literal and `get_detailed_channel_info`'s, where each is
a `metadata.get(...)` with or without a fallback, never inside a conditional. They are **not** safe
on a partial payload, which is why the `?fields=state` branch renders through its own two-field
serializer rather than reusing this one (ruling 20).

- [ ] **Step 1: Write the failing tests.** Create `apps/proxy/tests/test_relay_control_api.py`:
      ```python
      """The five /proxy/relay/... routes (Phase 1 PR 7, D12).

      Served by the relay process, gated by IsInternalRelay -- the two internal
      HMAC headers, never a principal. nginx routes them to the relay_py
      upstream and adds nothing: the token is the whole gate (D9), and the
      location is deliberately outside the authorize hop, since
      authorize_stream() would 404 a URI naming no channel (spec Amendment S8).
      """

      import json
      from unittest import mock

      from django.test import TestCase
      from rest_framework.test import APIClient

      from apps.accounts.models import User
      from apps.proxy import relay_views
      from apps.proxy.internal_auth import (
          HEADER_INTERNAL,
          HEADER_INTERNAL_REQUEST,
          build_internal_request_header,
          internal_principal_token,
      )


      def _signed(method, path, body=b""):
          return {
              "HTTP_X_DISPATCHARR_INTERNAL": internal_principal_token(),
              "HTTP_X_DISPATCHARR_INTERNAL_REQUEST": build_internal_request_header(
                  method, path, body
              ),
          }


      class RelayControlGateTests(TestCase):
          def setUp(self):
              self.client = APIClient()

          def test_an_unsigned_request_is_refused(self):
              self.assertEqual(self.client.get("/proxy/relay/channels").status_code, 403)

          def test_the_static_token_alone_is_not_enough(self):
              response = self.client.get(
                  "/proxy/relay/channels",
                  HTTP_X_DISPATCHARR_INTERNAL=internal_principal_token(),
              )
              self.assertEqual(response.status_code, 403)

          def test_an_admin_session_is_not_a_way_in(self):
              admin = User.objects.create_user(
                  username="a", password="p", user_level=User.UserLevel.ADMIN
              )
              self.client.force_authenticate(user=admin)
              self.assertEqual(self.client.get("/proxy/relay/channels").status_code, 403)

          def test_a_signature_for_a_different_path_does_not_open_this_one(self):
              headers = _signed("GET", "/proxy/relay/channels/other")
              self.assertEqual(
                  self.client.get("/proxy/relay/channels", **headers).status_code, 403
              )

          def test_a_correctly_signed_request_is_admitted(self):
              # ProxyServer.get_instance() is patched here and in every list
              # test below: channels_view reaches it for the Redis client, and
              # leaving it unpatched builds a real singleton that outlives the
              # test. The advance tests already patch it for the same reason.
              with mock.patch.object(
                  relay_views, "build_live_channel_stats_data",
                  return_value={"channels": [], "count": 0},
              ), mock.patch.object(
                  relay_views.ProxyServer, "get_instance",
                  return_value=mock.Mock(redis_client=mock.Mock(), stream_managers={}),
              ):
                  response = self.client.get(
                      "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
                  )
              self.assertEqual(response.status_code, 200)


      class RelayChannelListTests(TestCase):
          def setUp(self):
              self.client = APIClient()
              patcher = mock.patch.object(
                  relay_views.ProxyServer, "get_instance",
                  return_value=mock.Mock(redis_client=mock.Mock(), stream_managers={}),
              )
              patcher.start()
              self.addCleanup(patcher.stop)

          def _channel(self, **overrides):
              data = {
                  "channel_id": "abc",
                  "state": "active",
                  "url": "http://provider.example/live",
                  "stream_profile": "3",
                  "owner": "worker-1",
                  "buffer_index": 7,
                  "client_count": 2,
                  "uptime": 12.5,
                  "started_at": 1000.0,
                  "clients": [
                      {
                          "client_id": "c1",
                          "user_agent": "vlc",
                          "output_format": "mpegts",
                          "output_profile_id": None,
                          "user_id": "5",
                          "connected_at": 1000.0,
                          "ip_address": "10.0.0.1",
                      }
                  ],
              }
              data.update(overrides)
              return data

          def test_the_payload_is_channels_and_count(self):
              with mock.patch.object(
                  relay_views, "build_live_channel_stats_data",
                  return_value={"channels": [self._channel()], "count": 1},
              ):
                  response = self.client.get(
                      "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
                  )
              body = response.json()
              self.assertEqual(body["count"], 1)
              self.assertEqual(body["channels"][0]["channel_id"], "abc")
              self.assertEqual(body["channels"][0]["clients"][0]["client_id"], "c1")

          def test_an_absent_optional_field_stays_absent_rather_than_null(self):
              # stream_id and avg_bitrate_kbps are assigned inside conditionals
              # in get_basic_channel_info, so the wire has to be able to omit
              # them -- CLAUDE.md section Observing a channel.
              with mock.patch.object(
                  relay_views, "build_live_channel_stats_data",
                  return_value={"channels": [self._channel()], "count": 1},
              ):
                  response = self.client.get(
                      "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
                  )
              channel = response.json()["channels"][0]
              self.assertNotIn("stream_id", channel)
              self.assertNotIn("avg_bitrate_kbps", channel)

          def test_clients_all_asks_for_an_uncapped_client_list(self):
              path = "/proxy/relay/channels?clients=all"
              with mock.patch.object(
                  relay_views, "build_live_channel_stats_data",
                  return_value={"channels": [], "count": 0},
              ) as built:
                  response = self.client.get(path, **_signed("GET", path))
              self.assertEqual(response.status_code, 200)
              self.assertIsNone(built.call_args.kwargs["client_limit"])

          def test_the_default_keeps_the_stats_cap(self):
              with mock.patch.object(
                  relay_views, "build_live_channel_stats_data",
                  return_value={"channels": [], "count": 0},
              ) as built:
                  self.client.get(
                      "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
                  )
              self.assertEqual(built.call_args.kwargs["client_limit"], 10)


      class RelayChannelDetailTests(TestCase):
          def setUp(self):
              self.client = APIClient()

          def test_a_known_channel_returns_its_detailed_info(self):
              path = "/proxy/relay/channels/abc"
              with mock.patch.object(
                  relay_views.ChannelStatus, "get_detailed_channel_info",
                  return_value={
                      "channel_id": "abc",
                      "state": None,
                      "url": "",
                      "stream_profile": "",
                      "owner": "unknown",
                      "buffer_index": 0,
                      "clients": [],
                      "client_count": 0,
                      "buffer_stats": {"chunks": 0, "diagnostics": {}},
                      "ffmpeg_speed": 1.02,
                      "width": "1920",
                  },
              ):
                  response = self.client.get(path, **_signed("GET", path))
              body = response.json()
              self.assertEqual(response.status_code, 200)
              self.assertIsNone(body["state"])
              self.assertEqual(body["ffmpeg_speed"], 1.02)
              self.assertEqual(body["width"], "1920")

          def test_an_unknown_channel_is_a_404(self):
              path = "/proxy/relay/channels/nope"
              with mock.patch.object(
                  relay_views.ChannelStatus, "get_detailed_channel_info", return_value=None
              ):
                  response = self.client.get(path, **_signed("GET", path))
              self.assertEqual(response.status_code, 404)

          def test_fields_state_answers_from_two_redis_calls_and_no_detail_walk(self):
              # Ruling 20: the tune path asks one question, so it must not pay
              # for buffer-chunk sampling and two ORM name fallbacks. The
              # exact-equality assertion is the point -- it is what fails if
              # the branch ever renders through RelayChannelDetailSerializer,
              # whose four allow_null fields would add url/stream_profile/
              # owner as nulls this answer knows nothing about.
              path = "/proxy/relay/channels/abc?fields=state"
              redis = mock.Mock()
              redis.exists.return_value = 1
              redis.hget.return_value = "active"
              with mock.patch.object(
                  relay_views.ProxyServer, "get_instance",
                  return_value=mock.Mock(redis_client=redis),
              ), mock.patch.object(
                  relay_views.ChannelStatus, "get_detailed_channel_info"
              ) as detailed:
                  response = self.client.get(path, **_signed("GET", path))
              detailed.assert_not_called()
              self.assertEqual(
                  response.json(), {"channel_id": "abc", "state": "active"}
              )

          def test_fields_state_404s_when_the_relay_holds_no_metadata(self):
              path = "/proxy/relay/channels/abc?fields=state"
              redis = mock.Mock()
              redis.exists.return_value = 0
              with mock.patch.object(
                  relay_views.ProxyServer, "get_instance",
                  return_value=mock.Mock(redis_client=redis),
              ):
                  response = self.client.get(path, **_signed("GET", path))
              self.assertEqual(response.status_code, 404)
              self.assertEqual(
                  response.json(), {"channel_id": "abc", "state": None}
              )

          def test_delete_stops_the_channel(self):
              path = "/proxy/relay/channels/abc"
              with mock.patch.object(
                  relay_views.ChannelService, "stop_channel",
                  return_value={"status": "success", "previous_state": {"state": "active"}},
              ) as stopped:
                  response = self.client.delete(path, **_signed("DELETE", path))
              stopped.assert_called_once_with("abc")
              self.assertEqual(response.status_code, 200)
              self.assertEqual(response.json()["status"], "success")

          def test_delete_reports_the_relay_s_own_not_found(self):
              path = "/proxy/relay/channels/abc"
              with mock.patch.object(
                  relay_views.ChannelService, "stop_channel",
                  return_value={"status": "error", "message": "Channel not found"},
              ):
                  response = self.client.delete(path, **_signed("DELETE", path))
              self.assertEqual(response.status_code, 200)
              self.assertEqual(response.json()["status"], "error")
              self.assertEqual(response.json()["message"], "Channel not found")


      class RelayClientAndAdvanceTests(TestCase):
          def setUp(self):
              self.client = APIClient()

          def test_deleting_a_client_calls_stop_client(self):
              path = "/proxy/relay/channels/abc/clients/c1"
              with mock.patch.object(
                  relay_views.ChannelService, "stop_client",
                  return_value={"status": "success", "locally_processed": True},
              ) as stopped:
                  response = self.client.delete(path, **_signed("DELETE", path))
              stopped.assert_called_once_with("abc", "c1")
              self.assertEqual(response.json()["locally_processed"], True)

          def test_advance_passes_a_fully_resolved_source_through(self):
              # Ruling 11: the relay resolves nothing. new_url is always
              # present, so change_stream_url never takes its next_source
              # branch from here.
              path = "/proxy/relay/channels/abc/advance"
              payload = {
                  "stream_id": 42,
                  "url": "http://provider.example/next",
                  "user_agent": "Dispatcharr",
                  "m3u_profile_id": 3,
                  "stream_name": "Two",
              }
              body = json.dumps(payload).encode()
              with mock.patch.object(
                  relay_views.ChannelService, "change_stream_url",
                  return_value={"status": "success", "success": True, "direct_update": True},
              ) as changed:
                  response = self.client.post(
                      path, data=body, content_type="application/json",
                      **_signed("POST", path, body),
                  )
              changed.assert_called_once_with(
                  "abc",
                  "http://provider.example/next",
                  "Dispatcharr",
                  42,
                  3,
                  stream_name="Two",
              )
              self.assertEqual(response.json()["success"], True)

          def test_advance_requires_a_url(self):
              path = "/proxy/relay/channels/abc/advance"
              body = json.dumps({"stream_id": 42}).encode()
              response = self.client.post(
                  path, data=body, content_type="application/json",
                  **_signed("POST", path, body),
              )
              self.assertEqual(response.status_code, 400)

          def test_advance_reports_an_unconfirmed_switch_without_inventing_a_status(self):
              path = "/proxy/relay/channels/abc/advance"
              payload = {"stream_id": 42, "url": "http://p/x", "user_agent": "d"}
              body = json.dumps(payload).encode()
              with mock.patch.object(
                  relay_views.ChannelService, "change_stream_url",
                  return_value={
                      "status": "success", "success": False, "confirmed": False,
                      "message": "not confirmed", "direct_update": False,
                  },
              ):
                  response = self.client.post(
                      path, data=body, content_type="application/json",
                      **_signed("POST", path, body),
                  )
              body_json = response.json()
              self.assertEqual(response.status_code, 200)
              self.assertIs(body_json["success"], False)
              self.assertIs(body_json["confirmed"], False)


      class RelaySchemaTests(TestCase):
          def test_the_five_routes_appear_in_the_openapi_schema(self):
              from drf_spectacular.generators import SchemaGenerator

              schema = SchemaGenerator().get_schema(request=None, public=True)
              for path in (
                  "/proxy/relay/channels",
                  "/proxy/relay/channels/{identifier}",
                  "/proxy/relay/channels/{identifier}/clients/{client_id}",
                  "/proxy/relay/channels/{identifier}/advance",
              ):
                  self.assertIn(path, schema["paths"])
              detail = schema["paths"]["/proxy/relay/channels/{identifier}"]
              self.assertIn("get", detail)
              self.assertIn("delete", detail)
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_control_api -v1`
      Expected: FAIL — `ModuleNotFoundError: No module named 'apps.proxy.relay_views'`.
- [ ] **Step 2: Create `apps/proxy/relay_serializers.py`.** Declare every field the two info
      builders can emit, reading them off `channel_status.py` rather than from memory:
      ```python
      """Wire shapes for /proxy/relay/... (Phase 1 PR 7, D12).

      The other direction's shapes live in apps/proxy/serializers.py; these are
      Django->relay. CLAUDE.md section Conventions: a serializer for every
      request and response body, never a raw dict, and every route in the
      drf-spectacular schema.

      Every optional field is declared `required=False` with NO `default=`.
      Both info builders in apps/proxy/live_proxy/channel_status.py assign
      their optional keys inside conditionals, so a key can be absent entirely
      rather than null -- the behaviour CLAUDE.md section Observing a channel
      documents and e2e/fixtures/types.ts encodes. DRF's Field.get_attribute
      raises SkipField for a missing key in exactly that configuration, so the
      rendered JSON keeps the absences. Adding a default would turn every
      absence into a null and change /proxy/ts/status and /proxy/stats/, which
      this PR must leave alone.
      """

      from rest_framework import serializers


      class RelayChannelClientSerializer(serializers.Serializer):
          """One row of get_basic_channel_info's `clients` list."""

          client_id = serializers.CharField()
          user_agent = serializers.CharField(required=False, allow_null=True)
          output_format = serializers.CharField(required=False, allow_null=True)
          output_profile_id = serializers.IntegerField(required=False, allow_null=True)
          ip_address = serializers.CharField(required=False)
          connected_at = serializers.FloatField(required=False)
          user_id = serializers.CharField(required=False)


      class RelayChannelSerializer(serializers.Serializer):
          """get_basic_channel_info, field for field."""

          channel_id = serializers.CharField()
          state = serializers.CharField(required=False, allow_null=True)
          url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
          stream_profile = serializers.CharField(
              required=False, allow_blank=True, allow_null=True
          )
          owner = serializers.CharField(required=False, allow_null=True)
          buffer_index = serializers.IntegerField(required=False)
          client_count = serializers.IntegerField(required=False)
          uptime = serializers.FloatField(required=False)
          started_at = serializers.FloatField(required=False, allow_null=True)
          channel_name = serializers.CharField(required=False)
          logo_id = serializers.IntegerField(required=False)
          m3u_profile_id = serializers.IntegerField(required=False)
          stream_id = serializers.IntegerField(required=False)
          stream_name = serializers.CharField(required=False)
          total_bytes = serializers.IntegerField(required=False)
          avg_bitrate_kbps = serializers.FloatField(required=False)
          avg_bitrate = serializers.CharField(required=False)
          healthy = serializers.BooleanField(required=False)
          video_codec = serializers.CharField(required=False)
          resolution = serializers.CharField(required=False)
          source_fps = serializers.FloatField(required=False)
          ffmpeg_speed = serializers.FloatField(required=False)
          audio_codec = serializers.CharField(required=False)
          audio_channels = serializers.CharField(required=False)
          stream_type = serializers.CharField(required=False)
          clients = RelayChannelClientSerializer(many=True, required=False)


      class RelayChannelListSerializer(serializers.Serializer):
          channels = RelayChannelSerializer(many=True)
          count = serializers.IntegerField()


      class RelayDetailClientSerializer(serializers.Serializer):
          """One row of get_detailed_channel_info's `clients` list. Six fields
          always assigned with a fallback default, the rest conditional."""

          client_id = serializers.CharField()
          user_agent = serializers.CharField()
          worker_id = serializers.CharField()
          ip_address = serializers.CharField()
          user_id = serializers.CharField()
          output_format = serializers.CharField()
          output_profile_id = serializers.IntegerField(allow_null=True)
          connected_at = serializers.FloatField(required=False)
          last_active = serializers.FloatField(required=False)
          last_active_ago = serializers.FloatField(required=False)
          bytes_sent = serializers.IntegerField(required=False)
          avg_rate_KBps = serializers.FloatField(required=False)
          current_rate_KBps = serializers.FloatField(required=False)


      class RelayChannelDetailSerializer(serializers.Serializer):
          """get_detailed_channel_info, field for field.

          buffer_stats and local_manager are DictFields: buffer_stats carries a
          free-form `diagnostics` sub-dict whose keys depend on which Redis
          probe found something, and pinning it would turn a diagnostic into a
          contract.
          """

          channel_id = serializers.CharField()
          state = serializers.CharField(required=False, allow_null=True)
          url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
          stream_profile = serializers.CharField(
              required=False, allow_blank=True, allow_null=True
          )
          started_at = serializers.FloatField(required=False)
          owner = serializers.CharField(required=False, allow_null=True)
          buffer_index = serializers.IntegerField(required=False)
          channel_name = serializers.CharField(required=False)
          stream_id = serializers.IntegerField(required=False)
          stream_name = serializers.CharField(required=False)
          m3u_profile_id = serializers.IntegerField(required=False)
          m3u_profile_name = serializers.CharField(required=False)
          state_changed_at = serializers.FloatField(required=False)
          state_duration = serializers.FloatField(required=False)
          uptime = serializers.FloatField(required=False)
          total_bytes = serializers.IntegerField(required=False)
          total_data = serializers.CharField(required=False)
          avg_bitrate_kbps = serializers.FloatField(required=False)
          avg_bitrate = serializers.CharField(required=False)
          client_count = serializers.IntegerField(required=False)
          buffer_stats = serializers.DictField(required=False)
          local_manager = serializers.DictField(required=False)
          video_codec = serializers.CharField(required=False)
          resolution = serializers.CharField(required=False)
          width = serializers.CharField(required=False)
          height = serializers.CharField(required=False)
          video_bitrate = serializers.CharField(required=False)
          source_fps = serializers.CharField(required=False)
          pixel_format = serializers.CharField(required=False)
          source_bitrate = serializers.CharField(required=False)
          audio_codec = serializers.CharField(required=False)
          sample_rate = serializers.CharField(required=False)
          audio_channels = serializers.CharField(required=False)
          audio_bitrate = serializers.CharField(required=False)
          ffmpeg_speed = serializers.FloatField(required=False)
          ffmpeg_fps = serializers.CharField(required=False)
          actual_fps = serializers.CharField(required=False)
          ffmpeg_bitrate = serializers.CharField(required=False)
          stream_type = serializers.CharField(required=False)
          clients = RelayDetailClientSerializer(many=True, required=False)


      class RelayChannelStateSerializer(serializers.Serializer):
          """The two-field answer to GET /proxy/relay/channels/<id>?fields=state.

          Its own serializer rather than a partial render of
          RelayChannelDetailSerializer, and the reason is a DRF detail worth
          knowing: Field.get_attribute's except branch checks `default`, then
          `allow_null`, and only then `required` (rest_framework/fields.py,
          3.17.1). So a missing key on a field declared
          `required=False, allow_null=True` renders as null rather than being
          skipped -- which would put "url": null, "stream_profile": null and
          "owner": null into this response. Harmless to channel_snapshot,
          which reads only `state`, but a lie on the wire and in the schema.

          `state` is nullable here for the same reason it is on the detail
          serializer: a channel whose metadata hash carries no `state` field
          reports null, never the string 'unknown' (Phase 1 PR 7, ruling 4).
          """

          channel_id = serializers.CharField()
          state = serializers.CharField(allow_null=True)


      class RelayStopResponseSerializer(serializers.Serializer):
          """ChannelService.stop_channel / stop_client, passed through.

          `status` is the service layer's own 'success' or 'error' and travels
          in the body rather than as an HTTP status: the relay answered, and
          "this channel is not running here" is an answer, not a refusal. The
          Django-side wrapper is what turns it into the 404 the admin API has
          always returned.
          """

          status = serializers.CharField()
          message = serializers.CharField(required=False)
          channel_id = serializers.CharField(required=False)
          client_id = serializers.CharField(required=False)
          previous_state = serializers.DictField(required=False, allow_null=True)
          model_released = serializers.BooleanField(required=False)
          locally_processed = serializers.BooleanField(required=False)
          stop_key_set = serializers.BooleanField(required=False)
          event_published = serializers.BooleanField(required=False)


      class RelayAdvanceRequestSerializer(serializers.Serializer):
          """A fully-resolved source (ruling 11). `url` is required: Django
          resolves the candidate in the API process, where the ORM is, and the
          relay applies it. Without it ChannelService.change_stream_url would
          take its own next_source branch, putting an ORM query back inside the
          relay process that PR 6 took out of it."""

          url = serializers.CharField()
          user_agent = serializers.CharField(
              required=False, allow_blank=True, allow_null=True, default=None
          )
          stream_id = serializers.IntegerField(required=False, allow_null=True, default=None)
          m3u_profile_id = serializers.IntegerField(
              required=False, allow_null=True, default=None
          )
          stream_name = serializers.CharField(
              required=False, allow_blank=True, allow_null=True, default=None
          )


      class RelayAdvanceResponseSerializer(serializers.Serializer):
          """ChannelService.change_stream_url's dict, passed through.

          `confirmed` is present only when the owner never answered within
          STREAM_SWITCH_CONFIRM_TIMEOUT; the Django-side wrapper maps its
          absence to 502 and its presence to 504, which is what
          /proxy/ts/change_stream/ returns today.
          """

          status = serializers.CharField()
          success = serializers.BooleanField(required=False)
          confirmed = serializers.BooleanField(required=False)
          message = serializers.CharField(required=False)
          error = serializers.CharField(required=False)
          direct_update = serializers.BooleanField(required=False)
          event_published = serializers.BooleanField(required=False)
          metadata_updated = serializers.BooleanField(required=False)
          worker_id = serializers.CharField(required=False)
          diagnostics = serializers.DictField(required=False)
      ```
- [ ] **Step 3: Create `apps/proxy/relay_views.py`:**
      ```python
      """The relay's control API (Phase 1 PR 7, D12).

      Five routes under /proxy/relay/, served by the relay process, gated by
      IsInternalRelay -- the static X-Dispatcharr-Internal plus the bound
      X-Dispatcharr-Internal-Request, never a principal and never IsAdmin,
      which would need a resolved User these hops must not need.

      They exist so no control-plane process reads a relay-owned Redis key.
      Everything here reads Redis or calls an in-relay ChannelService static;
      nothing here queries the ORM for a decision and nothing writes a row.
      The two ORM reads that survive are inside get_detailed_channel_info's
      name fallbacks, which the spec's ORM-reads table keeps in the relay
      precisely because this handler is now the relay's side of the boundary.

      nginx routes these through `location ^~ /proxy/relay/`, which carries
      the dispatcharr_api_params.conf blanking include and no authorize hop:
      authorize_stream() would 404 a URI naming no channel (spec Amendment
      S8), and the location must stay externally reachable because Django
      dials it as an ordinary client, from the worker role across the compose
      network and from the api role through its own nginx.
      """

      import logging

      from drf_spectacular.utils import OpenApiParameter, extend_schema
      from rest_framework import status
      from rest_framework.decorators import (
          api_view,
          authentication_classes,
          permission_classes,
      )
      from rest_framework.response import Response

      from apps.proxy.live_proxy.channel_status import (
          ChannelStatus,
          build_live_channel_stats_data,
      )
      from apps.proxy.live_proxy.constants import ChannelMetadataField
      from apps.proxy.live_proxy.redis_keys import RedisKeys
      from apps.proxy.live_proxy.server import ProxyServer
      from apps.proxy.live_proxy.services.channel_service import ChannelService
      from apps.proxy.permissions import IsInternalRelay
      from apps.proxy.relay_serializers import (
          RelayAdvanceRequestSerializer,
          RelayAdvanceResponseSerializer,
          RelayChannelDetailSerializer,
          RelayChannelListSerializer,
          RelayChannelStateSerializer,
          RelayStopResponseSerializer,
      )

      logger = logging.getLogger(__name__)

      # What the Stats page and /proxy/stats/ have always shown. `?clients=all`
      # lifts it for get_user_active_connections, which counts a user's
      # connections and would under-count past ten on one channel.
      DEFAULT_CLIENT_LIMIT = 10


      @extend_schema(
          operation_id="internal_relay_list_channels",
          description=(
              "Internal. Every channel this relay is running, with the payload "
              "/proxy/stats/ and the channel_stats WebSocket message are built "
              "from. Not part of the client API."
          ),
          parameters=[
              OpenApiParameter(
                  name="clients",
                  description=(
                      "Pass `all` for every client on each channel; omitted, the "
                      "list is capped at ten, as the stats surfaces have always "
                      "shown it."
                  ),
                  required=False,
                  type=str,
              )
          ],
          responses={200: RelayChannelListSerializer},
          tags=["internal"],
      )
      @api_view(["GET"])
      @authentication_classes([])
      @permission_classes([IsInternalRelay])
      def channels_view(request):
          client_limit = (
              None
              if request.query_params.get("clients") == "all"
              else DEFAULT_CLIENT_LIMIT
          )
          proxy_server = ProxyServer.get_instance()
          payload = build_live_channel_stats_data(
              proxy_server.redis_client, client_limit=client_limit
          )
          return Response(RelayChannelListSerializer(payload).data)


      @extend_schema(
          methods=["GET"],
          operation_id="internal_relay_channel",
          description=(
              "Internal. One channel's detailed status, the payload "
              "/proxy/ts/status/<id> is built from, serialized by "
              "RelayChannelDetailSerializer. With `?fields=state` the answer is "
              "instead a RelayChannelStateSerializer -- `channel_id` and `state` "
              "only -- read with one EXISTS and one HGET rather than the full "
              "diagnostic walk. Two shapes under one 200, so the schema names "
              "the full one and this description names the narrow one; a "
              "PolymorphicProxySerializer would need a discriminator field the "
              "wire does not carry."
          ),
          parameters=[
              OpenApiParameter(
                  name="fields",
                  description=(
                      "Pass `state` for the two-field tune-path form "
                      "(RelayChannelStateSerializer)."
                  ),
                  required=False,
                  type=str,
              )
          ],
          responses={
              200: RelayChannelDetailSerializer,
              # The 404 body is the identifier and a null state, which is
              # exactly the narrow serializer's shape -- and true, since a
              # 404 here means the relay holds no metadata hash at all.
              404: RelayChannelStateSerializer,
          },
          tags=["internal"],
      )
      @extend_schema(
          methods=["DELETE"],
          operation_id="internal_relay_stop_channel",
          description=(
              "Internal. Stop the channel and release its resources, the "
              "operation /proxy/ts/stop/<id> wraps."
          ),
          responses={200: RelayStopResponseSerializer},
          tags=["internal"],
      )
      @api_view(["GET", "DELETE"])
      @authentication_classes([])
      @permission_classes([IsInternalRelay])
      def channel_view(request, identifier):
          if request.method == "DELETE":
              result = ChannelService.stop_channel(identifier)
              return Response(RelayStopResponseSerializer(result).data)
          if request.query_params.get("fields") == "state":
              # The tune path's question and only that (ruling 20): one EXISTS
              # and one HGET, instead of get_detailed_channel_info's buffer
              # chunk sampling, client walk and two ORM name fallbacks, under
              # relay_client's two-second tune budget.
              #
              # Rendered through RelayChannelStateSerializer, not a partial
              # RelayChannelDetailSerializer: DRF skips a missing key only
              # when the field is neither allow_null nor defaulted, so the
              # detail serializer's four nullable fields would put
              # "url": null, "stream_profile": null and "owner": null into an
              # answer that knows none of them.
              redis_client = ProxyServer.get_instance().redis_client
              metadata_key = RedisKeys.channel_metadata(identifier)
              if not redis_client or not redis_client.exists(metadata_key):
                  return Response(
                      RelayChannelStateSerializer(
                          {"channel_id": identifier, "state": None}
                      ).data,
                      status=status.HTTP_404_NOT_FOUND,
                  )
              return Response(
                  RelayChannelStateSerializer(
                      {
                          "channel_id": identifier,
                          "state": redis_client.hget(
                              metadata_key, ChannelMetadataField.STATE
                          ),
                      }
                  ).data
              )
          info = ChannelStatus.get_detailed_channel_info(identifier)
          if not info:
              # The relay has no metadata hash for this identifier. A real
              # answer, not a refusal -- but a 404 rather than a 200 with a
              # null, because relay_client.RelayRefused is how the Django-side
              # wrapper tells "no such running channel" from an outage, and
              # /proxy/ts/status/<id> has always answered 404 here. Rendered
              # through the narrow serializer, not a raw dict: CLAUDE.md
              # section Conventions, and the shape is exactly right.
              return Response(
                  RelayChannelStateSerializer(
                      {"channel_id": identifier, "state": None}
                  ).data,
                  status=status.HTTP_404_NOT_FOUND,
              )
          return Response(RelayChannelDetailSerializer(info).data)


      @extend_schema(
          operation_id="internal_relay_stop_client",
          description=(
              "Internal. Stop one client connection on one channel: sets the "
              "client's stop key and, when the client is not on this worker, "
              "publishes the stop over live:events. Wrapped by "
              "/proxy/ts/stop_client/<id>."
          ),
          responses={200: RelayStopResponseSerializer},
          tags=["internal"],
      )
      @api_view(["DELETE"])
      @authentication_classes([])
      @permission_classes([IsInternalRelay])
      def channel_client_view(request, identifier, client_id):
          result = ChannelService.stop_client(identifier, client_id)
          return Response(RelayStopResponseSerializer(result).data)


      @extend_schema(
          operation_id="internal_relay_advance",
          description=(
              "Internal. Switch a running channel to an already-resolved source. "
              "Django resolves the candidate in the API process, where the ORM "
              "is; the relay only applies it. Wrapped by "
              "/proxy/ts/change_stream/<id> and /proxy/ts/next_stream/<id>."
          ),
          request=RelayAdvanceRequestSerializer,
          responses={200: RelayAdvanceResponseSerializer},
          tags=["internal"],
      )
      @api_view(["POST"])
      @authentication_classes([])
      @permission_classes([IsInternalRelay])
      def channel_advance_view(request, identifier):
          payload = RelayAdvanceRequestSerializer(data=request.data)
          payload.is_valid(raise_exception=True)
          source = payload.validated_data
          # Positional exactly as change_stream_url declares them, with
          # new_url always present so its own next_source branch -- an ORM
          # query PR 6 took out of the relay process -- is never entered.
          result = ChannelService.change_stream_url(
              identifier,
              source["url"],
              source["user_agent"],
              source["stream_id"],
              source["m3u_profile_id"],
              stream_name=source["stream_name"],
          )
          return Response(RelayAdvanceResponseSerializer(result).data)
      ```
- [ ] **Step 4: Create `apps/proxy/relay_urls.py`:**
      ```python
      """The relay control API's routes (Phase 1 D12).

      Mounted at /proxy/relay/ from apps/proxy/urls.py, so they are served by
      whichever process nginx sends /proxy/relay/ to -- the relay (D5, D14).
      No trailing slashes, matching apps/proxy/live_proxy/urls.py, which is
      what makes nginx's `location ^~ /proxy/relay/` prefix sufficient and
      keeps APPEND_SLASH out of the internal contract.
      """

      from django.urls import path

      from apps.proxy import relay_views

      app_name = "relay_control"

      urlpatterns = [
          path("channels", relay_views.channels_view, name="channels"),
          path(
              "channels/<str:identifier>",
              relay_views.channel_view,
              name="channel",
          ),
          path(
              "channels/<str:identifier>/clients/<str:client_id>",
              relay_views.channel_client_view,
              name="channel-client",
          ),
          path(
              "channels/<str:identifier>/advance",
              relay_views.channel_advance_view,
              name="channel-advance",
          ),
      ]
      ```
      And add one line to `apps/proxy/urls.py`, after the `stats/` entry:
      ```python
          path('relay/', include('apps.proxy.relay_urls')),
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_control_api -v1`
      Expected: OK.
- [ ] **Step 5: Check the schema generates cleanly.**
      Run: `docker exec … manage.py spectacular --file /dev/null 2>&1 | grep -i "relay\|/proxy/relay"`
      Expected: no output. **Do not use `--fail-on-warn`** — it is red on the baseline tree for
      pre-existing un-annotated legacy views, so it cannot tell this PR's warnings from theirs.
      A warning naming a `/proxy/relay/` path or a `Relay*Serializer` is a real finding: fix the
      annotation rather than widening the grep.
- [ ] **Step 6: Prove no ORM write landed under `apps/proxy/`.**
      Run: `grep -rn "log_system_event(\|\.save(\|\.objects\.create(" apps/proxy/ | grep -v tests`
      Expected: no output — PR 6's Done grep still holds.
      Run: `PYTHONPATH=scripts/metrics python3 scripts/metrics/collect_architecture.py --repo-root . | grep proxy_orm_writes`
      Expected: `"proxy_orm_writes": 0`.
- [ ] **Step 7: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/proxy/relay_views.py apps/proxy/relay_serializers.py apps/proxy/relay_urls.py apps/proxy/urls.py`
      Expected: exit 0.
      Write the message to `…/scratchpad/pr7-t4.txt`:
      ```
      feat(phase1-pr7): the relay's control API, five routes behind the internal token

      GET /proxy/relay/channels[?clients=all], GET and DELETE
      /proxy/relay/channels/<identifier>, DELETE .../clients/<client_id> and
      POST .../advance, all IsInternalRelay: the static internal token plus the
      bound per-request one PR 6 added, never a principal and never IsAdmin.

      Serializers for every body, every route in the drf-spectacular schema
      under the `internal` tag. Optional fields are required=False with no
      default, because both status builders assign their optional keys inside
      conditionals and the wire has to keep the absences /proxy/ts/status has
      always had.

      advance takes a fully-resolved source. Django resolves the candidate in
      the API process, where the ORM is; passing new_url always means
      ChannelService.change_stream_url never takes its own next_source branch,
      so no ORM query returns to the relay process.

      Nothing here is wired up yet -- the Django-side wrappers land next.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Run the commit gate, then `git add apps/proxy/relay_serializers.py apps/proxy/relay_views.py apps/proxy/relay_urls.py apps/proxy/urls.py apps/proxy/tests/test_relay_control_api.py`
      in one Bash call and `git commit -F …/scratchpad/pr7-t4.txt` in a separate one.

---

### Task 5: `relay_client`'s six call methods

**Files:**
- Modify: `apps/proxy/relay_client.py` — append the call surface
- Test: `apps/proxy/tests/test_relay_client.py` — append a class

**Interfaces:**
- Produces `list_channels(*, all_clients=False, timeout=ADMIN_TIMEOUT) -> dict`,
  `get_channel(identifier, *, timeout=ADMIN_TIMEOUT) -> dict | None`,
  `channel_snapshot(identifier, *, timeout=TUNE_TIMEOUT) -> ChannelSnapshot`,
  `stop_channel(identifier, *, timeout=ADMIN_TIMEOUT) -> dict`,
  `stop_client(identifier, client_id, *, timeout=ADMIN_TIMEOUT) -> dict`,
  `stop_channels(identifiers) -> None`,
  `advance(identifier, *, url, user_agent=None, stream_id=None, m3u_profile_id=None,
  stream_name=None, reset_tried=False) -> dict`, and
  `ChannelSnapshot(present: bool, active: bool, reachable: bool)`.

- [ ] **Step 1: Write the failing tests.** Append to `apps/proxy/tests/test_relay_client.py`:
      ```python
      class RelayClientCallTests(SimpleTestCase):
          def setUp(self):
              patcher = mock.patch.dict(
                  os.environ, {"DISPATCHARR_ENV": "aio"}, clear=True
              )
              patcher.start()
              self.addCleanup(patcher.stop)

          def test_list_channels_asks_for_every_client_only_when_told_to(self):
              with mock.patch.object(
                  relay_client, "_request", return_value={"channels": [], "count": 0}
              ) as sent:
                  relay_client.list_channels()
                  self.assertIsNone(sent.call_args.kwargs["params"])
                  relay_client.list_channels(all_clients=True)
                  self.assertEqual(
                      sent.call_args.kwargs["params"], {"clients": "all"}
                  )

          def test_get_channel_turns_the_relay_s_404_into_none(self):
              with mock.patch.object(
                  relay_client,
                  "_request",
                  side_effect=relay_client.RelayRefused(404, "/proxy/relay/channels/x"),
              ):
                  self.assertIsNone(relay_client.get_channel("x"))

          def test_get_channel_re_raises_every_other_refusal(self):
              with mock.patch.object(
                  relay_client,
                  "_request",
                  side_effect=relay_client.RelayRefused(403, "/proxy/relay/channels/x"),
              ):
                  with self.assertRaises(relay_client.RelayRefused):
                      relay_client.get_channel("x")

          def test_an_identifier_is_percent_encoded_into_the_path(self):
              with mock.patch.object(relay_client, "_request", return_value={}) as sent:
                  relay_client.get_channel("a/b")
              self.assertEqual(sent.call_args.args[1], "/proxy/relay/channels/a%2Fb")

          def test_channel_snapshot_reports_present_and_active(self):
              with mock.patch.object(
                  relay_client, "_request", return_value={"state": "active"}
              ):
                  snapshot = relay_client.channel_snapshot("x")
              self.assertEqual((snapshot.present, snapshot.active, snapshot.reachable),
                               (True, True, True))

          def test_channel_snapshot_calls_a_stopping_channel_present_but_inactive(self):
              with mock.patch.object(
                  relay_client, "_request", return_value={"state": "stopping"}
              ):
                  snapshot = relay_client.channel_snapshot("x")
              self.assertEqual((snapshot.present, snapshot.active), (True, False))

          def test_channel_snapshot_uses_the_tune_budget_and_the_narrow_form(self):
              with mock.patch.object(relay_client, "_request", return_value={}) as sent:
                  relay_client.channel_snapshot("x")
              self.assertEqual(sent.call_args.kwargs["timeout"], relay_client.TUNE_TIMEOUT)
              # Ruling 20: one EXISTS + one HGET on the relay, not the full
              # diagnostic walk, under a two-second budget.
              self.assertEqual(sent.call_args.kwargs["params"], {"fields": "state"})

          def test_an_unreachable_relay_is_a_snapshot_not_an_exception(self):
              # get_stream()'s reuse branch runs inside the relay's own
              # next-source call; raising here would turn a relay hiccup into
              # a failed tune (ruling 13).
              with mock.patch.object(
                  relay_client, "_request",
                  side_effect=relay_client.RelayUnavailable("down"),
              ):
                  snapshot = relay_client.channel_snapshot("x")
              self.assertEqual((snapshot.present, snapshot.active, snapshot.reachable),
                               (False, False, False))

          def test_stop_channels_never_raises_and_visits_every_identifier(self):
              seen = []

              def _fail_on_the_second(identifier, **kwargs):
                  seen.append(identifier)
                  if identifier == "b":
                      raise relay_client.RelayUnavailable("down")
                  return {"status": "success"}

              with mock.patch.object(
                  relay_client, "stop_channel", side_effect=_fail_on_the_second
              ):
                  relay_client.stop_channels(iter(["a", "b", "c"]))
              self.assertEqual(seen, ["a", "b", "c"])

          def test_stop_channels_skips_a_falsy_identifier(self):
              with mock.patch.object(
                  relay_client, "stop_channel", return_value={"status": "success"}
              ) as stopped:
                  relay_client.stop_channels([None, "", "a"])
              self.assertEqual(stopped.call_count, 1)

          def test_advance_sends_the_resolved_source_and_the_long_budget(self):
              with mock.patch.object(
                  relay_client, "_request", return_value={"status": "success"}
              ) as sent:
                  relay_client.advance(
                      "abc",
                      url="http://p/next",
                      user_agent="d",
                      stream_id=42,
                      m3u_profile_id=3,
                      stream_name="Two",
                      reset_tried=True,
                  )
              self.assertEqual(sent.call_args.args, ("POST", "/proxy/relay/channels/abc/advance"))
              self.assertEqual(
                  sent.call_args.kwargs["payload"],
                  {
                      "url": "http://p/next",
                      "user_agent": "d",
                      "stream_id": 42,
                      "m3u_profile_id": 3,
                      "stream_name": "Two",
                      "reset_tried": True,
                  },
              )
              self.assertEqual(
                  sent.call_args.kwargs["timeout"], relay_client.ADVANCE_TIMEOUT
              )

          def test_stop_client_encodes_both_segments(self):
              with mock.patch.object(relay_client, "_request", return_value={}) as sent:
                  relay_client.stop_client("abc", "c 1")
              self.assertEqual(
                  sent.call_args.args[1], "/proxy/relay/channels/abc/clients/c%201"
              )
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_client -v1`
      Expected: FAIL — the six methods do not exist.
- [ ] **Step 2: Append the call surface to `apps/proxy/relay_client.py`:**
      ```python
      @dataclass(frozen=True)
      class ChannelSnapshot:
          """What Channel.get_stream()'s reuse branch needs, in one round trip.

          present   the relay holds a metadata hash for this identifier
          active    ... and its state is one the tune path may reuse
          reachable the relay answered at all

          An unreachable relay reports (False, False, False) rather than
          raising: this runs inside Channel.get_stream(), which the relay
          itself reached over POST /api/relay/.../next-source with a five
          second read budget, and a raise here would turn a relay hiccup into
          a failed tune. present=False sends _stream_assignment_is_reusable to
          its stream_profile fallback, which reuses the existing assignment --
          the outcome that cannot leak a provider slot.
          """

          present: bool
          active: bool
          reachable: bool


      def list_channels(*, all_clients=False, timeout=ADMIN_TIMEOUT):
          """Every channel the relay is running. Shape: {channels, count}."""
          params = {"clients": "all"} if all_clients else None
          return _request(
              "GET", "/proxy/relay/channels", timeout=timeout, params=params
          )


      def get_channel(identifier, *, timeout=ADMIN_TIMEOUT, fields=None):
          """One channel's detailed status, or None when the relay has none.

          A 404 is an answer -- "this channel is not running" -- not an
          outage, so it becomes None. Every other refusal propagates: a 403
          means the two roles disagree about SECRET_KEY, and swallowing it
          would make every status read look like an idle system.

          fields="state" asks for the two-field tune-path form (ruling 20).
          It travels as a query parameter, which the bound token signs along
          with the path (ruling 17).
          """
          path = f"/proxy/relay/channels/{quote(str(identifier), safe='')}"
          params = {"fields": fields} if fields else None
          try:
              return _request("GET", path, timeout=timeout, params=params)
          except RelayRefused as exc:
              if exc.status == 404:
                  return None
              raise


      def channel_snapshot(identifier, *, timeout=TUNE_TIMEOUT):
          """The tune-path read. See ChannelSnapshot for the failure mode.

          Asks for ?fields=state (ruling 20), so the relay answers with one
          EXISTS and one HGET rather than get_detailed_channel_info's buffer
          chunk sampling, client walk and two ORM name fallbacks -- which
          would trip the two-second budget under load far more often than
          this question warrants.
          """
          from apps.proxy.live_proxy.constants import ChannelState

          reusable_states = (
              ChannelState.ACTIVE,
              ChannelState.WAITING_FOR_CLIENTS,
              ChannelState.BUFFERING,
              ChannelState.INITIALIZING,
              ChannelState.CONNECTING,
          )
          try:
              info = get_channel(identifier, timeout=timeout, fields="state")
          except (RelayUnavailable, RelayRefused) as exc:
              logger.warning(
                  "Relay could not answer for channel %s: %s", identifier, exc
              )
              return ChannelSnapshot(present=False, active=False, reachable=False)
          if info is None:
              return ChannelSnapshot(present=False, active=False, reachable=True)
          return ChannelSnapshot(
              present=True, active=info.get("state") in reusable_states, reachable=True
          )


      def stop_channel(identifier, *, timeout=ADMIN_TIMEOUT):
          """Stop a channel. Returns ChannelService.stop_channel's own dict."""
          path = f"/proxy/relay/channels/{quote(str(identifier), safe='')}"
          return _request("DELETE", path, timeout=timeout)


      def stop_channels(identifiers):
          """Best-effort stop for each identifier. Never raises.

          Same contract as ChannelService.stop_channels, which the three
          Django-side callers relied on: proxy teardown runs before a DB
          delete and must never block it.
          """
          for identifier in identifiers:
              if not identifier:
                  continue
              try:
                  stop_channel(str(identifier))
              except Exception as exc:
                  logger.warning(
                      "Failed to stop proxy session for channel %s: %s",
                      identifier,
                      exc,
                  )


      def stop_client(identifier, client_id, *, timeout=ADMIN_TIMEOUT):
          """Stop one client on one channel."""
          path = (
              f"/proxy/relay/channels/{quote(str(identifier), safe='')}"
              f"/clients/{quote(str(client_id), safe='')}"
          )
          return _request("DELETE", path, timeout=timeout)


      def advance(
          identifier,
          *,
          url,
          user_agent=None,
          stream_id=None,
          m3u_profile_id=None,
          stream_name=None,
          reset_tried=False,
      ):
          """Switch a running channel to an already-resolved source.

          url is required and always sent: Django resolved the candidate in
          the API process, where the ORM is (ruling 11). ADVANCE_TIMEOUT's
          20-second read budget covers ChannelService.change_stream_url's
          non-owner path, which polls for the owner's confirmation for up to
          STREAM_SWITCH_CONFIRM_TIMEOUT = 15s before answering.
          """
          path = f"/proxy/relay/channels/{quote(str(identifier), safe='')}/advance"
          return _request(
              "POST",
              path,
              timeout=ADVANCE_TIMEOUT,
              payload={
                  "url": url,
                  "user_agent": user_agent,
                  "stream_id": stream_id,
                  "m3u_profile_id": m3u_profile_id,
                  "stream_name": stream_name,
                  "reset_tried": reset_tried,
              },
          )
      ```
      Add `from dataclasses import dataclass` and `from urllib.parse import quote, urlencode` to the
      module's imports.
- [ ] **Step 3: Accept `reset_tried` on the relay side and restore the behaviour PR 4 broke.**
      In `apps/proxy/relay_serializers.py`, add to `RelayAdvanceRequestSerializer`:
      ```python
          # /proxy/ts/change_stream/ has always cleared the running manager's
          # tried_stream_ids so an operator's manual switch does not inherit a
          # failover's exclusion list. That reset used to run in the same
          # process as the manager; since PR 4's routing put the view on the
          # API role, proxy_server.stream_managers there is always empty and
          # the reset silently stopped happening. It moves here, where the
          # manager is. next_stream never reset it and still does not, which
          # is why this is a flag rather than unconditional.
          reset_tried = serializers.BooleanField(required=False, default=False)
      ```
      and in `apps/proxy/relay_views.py`'s `channel_advance_view`, before the
      `ChannelService.change_stream_url` call:
      ```python
          if source["reset_tried"]:
              manager = ProxyServer.get_instance().stream_managers.get(identifier)
              if manager is not None:
                  manager.tried_stream_ids = set()
                  logger.debug(
                      f"Reset tried stream IDs for channel {identifier} during a "
                      f"manual stream change"
                  )
      ```
      Append to `apps/proxy/tests/test_relay_control_api.py`'s `RelayClientAndAdvanceTests`:
      ```python
          def test_reset_tried_clears_the_local_manager_s_exclusion_list(self):
              path = "/proxy/relay/channels/abc/advance"
              payload = {"url": "http://p/x", "stream_id": 42, "reset_tried": True}
              body = json.dumps(payload).encode()
              manager = mock.Mock(tried_stream_ids={1, 2})
              server = mock.Mock(stream_managers={"abc": manager})
              with mock.patch.object(
                  relay_views.ProxyServer, "get_instance", return_value=server
              ), mock.patch.object(
                  relay_views.ChannelService, "change_stream_url",
                  return_value={"status": "success", "success": True},
              ):
                  self.client.post(
                      path, data=body, content_type="application/json",
                      **_signed("POST", path, body),
                  )
              self.assertEqual(manager.tried_stream_ids, set())

          def test_reset_tried_is_off_by_default(self):
              path = "/proxy/relay/channels/abc/advance"
              payload = {"url": "http://p/x", "stream_id": 42}
              body = json.dumps(payload).encode()
              manager = mock.Mock(tried_stream_ids={1, 2})
              server = mock.Mock(stream_managers={"abc": manager})
              with mock.patch.object(
                  relay_views.ProxyServer, "get_instance", return_value=server
              ), mock.patch.object(
                  relay_views.ChannelService, "change_stream_url",
                  return_value={"status": "success", "success": True},
              ):
                  self.client.post(
                      path, data=body, content_type="application/json",
                      **_signed("POST", path, body),
                  )
              self.assertEqual(manager.tried_stream_ids, {1, 2})
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_relay_client apps.proxy.tests.test_relay_control_api -v1`
      Expected: OK.
- [ ] **Step 4: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/proxy/relay_client.py apps/proxy/relay_views.py apps/proxy/relay_serializers.py`
      Expected: exit 0.
      Write `…/scratchpad/pr7-t5.txt`:
      ```
      feat(phase1-pr7): relay_client's call surface

      list_channels, get_channel, channel_snapshot, stop_channel, stop_channels,
      stop_client and advance. Three timeout budgets and no retries: a retried
      advance switches twice, and a retried tune-path read exceeds the five
      second budget the relay gave next-source.

      channel_snapshot is the tune-path read, and an unreachable relay is a
      snapshot rather than an exception -- it runs inside Channel.get_stream(),
      which the relay itself reached over HTTP, and a raise there would turn a
      relay hiccup into a failed tune.

      advance carries reset_tried, which restores the tried_stream_ids clear
      that /proxy/ts/change_stream/ silently stopped doing when PR 4's routing
      moved the view to a process that holds no stream managers.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `apps/proxy/relay_client.py apps/proxy/relay_serializers.py apps/proxy/relay_views.py apps/proxy/tests/test_relay_client.py apps/proxy/tests/test_relay_control_api.py`, then commit with `-F`.

---

### Task 6: The five admin views and `/proxy/stats/` become thin wrappers

**Files:**
- Modify: `apps/proxy/live_proxy/views.py` — `channel_status`, `stop_channel`, `stop_client`,
  `change_stream`, `next_stream`
- Modify: `apps/proxy/stats_views.py` — `combined_stats`' live section
- Modify: `apps/proxy/tests/test_combined_stats.py` — patch `relay_client`, not Redis
- Test: `apps/proxy/live_proxy/tests/test_admin_control_views.py` (new)

**Interfaces:** Consumes `apps.proxy.relay_client`. **Every import of it in `live_proxy/views.py`
is function-local, inside one of these five views** (D10): that file also hosts `stream_ts` and
`stream_xc`, which run in the relay, and a module-level import would put Django's side of the
boundary into the relay's process image.

**The client-visible contract does not move.** Same URLs, same `IsAdmin`, same methods, same JSON
keys, same status codes for every outcome that exists today. Two statuses are new because a new
failure mode exists: `503` when the relay cannot be reached and `502` when it refuses. Neither is
reachable in a single-process deployment.

- [ ] **Step 1: Write the failing tests.** Create
      `apps/proxy/live_proxy/tests/test_admin_control_views.py`:
      ```python
      """The five IsAdmin views are wrappers now, and nothing else changed.

      They keep their URLs, their permission class, their methods and their
      JSON. What changed is where the answer comes from: relay_client instead
      of a direct Redis read or an in-process ChannelService call. These tests
      assert the mapping in both directions, including the two statuses that
      are new because a relay that cannot be reached is a new thing to be.
      """

      from unittest import mock

      from django.test import TestCase
      from rest_framework.test import APIClient

      from apps.accounts.models import User
      from apps.proxy import relay_client
      from apps.proxy.live_proxy import views


      class AdminControlViewTests(TestCase):
          def setUp(self):
              self.admin = User.objects.create_user(
                  username="admin", password="p", user_level=User.UserLevel.ADMIN
              )
              self.client = APIClient()
              self.client.force_authenticate(user=self.admin)

          def test_status_collection_returns_the_relay_s_payload(self):
              payload = {"channels": [{"channel_id": "abc"}], "count": 1}
              with mock.patch.object(
                  relay_client, "list_channels", return_value=payload
              ), mock.patch.object(views, "send_websocket_update") as pushed:
                  response = self.client.get("/proxy/ts/status")
              self.assertEqual(response.json(), payload)
              # The broadcast is a side effect of polling this endpoint and
              # stays a side effect of polling this endpoint.
              self.assertEqual(pushed.call_args.args[2]["type"], "channel_stats")

          def test_status_detail_returns_the_relay_s_channel(self):
              with mock.patch.object(
                  relay_client, "get_channel", return_value={"channel_id": "abc"}
              ):
                  response = self.client.get("/proxy/ts/status/abc")
              self.assertEqual(response.json()["channel_id"], "abc")

          def test_status_detail_404s_for_a_channel_the_relay_does_not_hold(self):
              with mock.patch.object(relay_client, "get_channel", return_value=None):
                  response = self.client.get("/proxy/ts/status/abc")
              self.assertEqual(response.status_code, 404)

          def test_an_unreachable_relay_is_503_not_500(self):
              with mock.patch.object(
                  relay_client, "list_channels",
                  side_effect=relay_client.RelayUnavailable("down"),
              ):
                  response = self.client.get("/proxy/ts/status")
              self.assertEqual(response.status_code, 503)

          def test_a_refusing_relay_is_502(self):
              with mock.patch.object(
                  relay_client, "get_channel",
                  side_effect=relay_client.RelayRefused(403, "/proxy/relay/channels/abc"),
              ):
                  response = self.client.get("/proxy/ts/status/abc")
              self.assertEqual(response.status_code, 502)

          def test_stop_channel_maps_the_service_error_to_404_as_before(self):
              with mock.patch.object(
                  relay_client, "stop_channel",
                  return_value={"status": "error", "message": "Channel not found"},
              ):
                  response = self.client.post("/proxy/ts/stop/abc")
              self.assertEqual(response.status_code, 404)
              self.assertEqual(response.json()["error"], "Channel not found")

          def test_stop_channel_reports_the_previous_state_as_before(self):
              with mock.patch.object(
                  relay_client, "stop_channel",
                  return_value={"status": "success", "previous_state": {"state": "active"}},
              ) as stopped:
                  response = self.client.post("/proxy/ts/stop/abc")
              stopped.assert_called_once_with("abc")
              self.assertEqual(
                  response.json(),
                  {
                      "message": "Channel stop request sent",
                      "channel_id": "abc",
                      "previous_state": {"state": "active"},
                  },
              )

          def test_stop_client_requires_a_client_id_as_before(self):
              response = self.client.post(
                  "/proxy/ts/stop_client/abc", data={}, format="json"
              )
              self.assertEqual(response.status_code, 400)

          def test_stop_client_passes_both_segments_through(self):
              with mock.patch.object(
                  relay_client, "stop_client",
                  return_value={"status": "success", "locally_processed": True},
              ) as stopped:
                  response = self.client.post(
                      "/proxy/ts/stop_client/abc",
                      data={"client_id": "c1"},
                      format="json",
                  )
              stopped.assert_called_once_with("abc", "c1")
              self.assertEqual(response.json()["locally_processed"], True)

          def test_change_stream_resolves_in_django_and_applies_on_the_relay(self):
              source = {
                  "url": "http://p/next",
                  "user_agent": "d",
                  "m3u_profile_id": 3,
                  "stream_name": "Two",
              }
              with mock.patch(
                  "apps.proxy.next_source.resolve_source",
                  return_value={"source": source, "error": None},
              ), mock.patch.object(
                  relay_client, "advance",
                  return_value={"status": "success", "success": True, "direct_update": True},
              ) as advanced:
                  response = self.client.post(
                      "/proxy/ts/change_stream/abc",
                      data={"stream_id": 42},
                      format="json",
                  )
              self.assertEqual(response.status_code, 200)
              self.assertIs(advanced.call_args.kwargs["reset_tried"], True)
              self.assertEqual(advanced.call_args.kwargs["stream_id"], 42)
              self.assertEqual(response.json()["stream_id"], 42)

          def test_change_stream_still_rejects_a_non_integer_stream_id(self):
              response = self.client.post(
                  "/proxy/ts/change_stream/abc",
                  data={"stream_id": "not-a-number"},
                  format="json",
              )
              self.assertEqual(response.status_code, 400)

          def test_change_stream_maps_an_unconfirmed_switch_to_504(self):
              with mock.patch.object(
                  relay_client, "advance",
                  return_value={
                      "status": "success", "success": False, "confirmed": False,
                      "message": "not confirmed",
                  },
              ):
                  response = self.client.post(
                      "/proxy/ts/change_stream/abc",
                      data={"url": "http://p/x"},
                      format="json",
                  )
              self.assertEqual(response.status_code, 504)

          def test_change_stream_maps_a_reported_failure_to_502(self):
              with mock.patch.object(
                  relay_client, "advance",
                  return_value={"status": "success", "success": False, "message": "no"},
              ):
                  response = self.client.post(
                      "/proxy/ts/change_stream/abc",
                      data={"url": "http://p/x"},
                      format="json",
                  )
              self.assertEqual(response.status_code, 502)
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.live_proxy.tests.test_admin_control_views -v1`
      Expected: FAIL — the views still read Redis and call `ChannelService`.
- [ ] **Step 2: Rewrite `channel_status`.** Replace its body:
      ```python
      @api_view(["GET"])
      @permission_classes([IsAdmin])
      def channel_status(request, channel_id=None):
          """
          Returns status information about channels with detail level based on request:
          - /status/ returns basic summary of all channels
          - /status/{channel_id} returns detailed info about specific channel

          Phase 1 PR 7: the answer comes from the relay over
          GET /proxy/relay/channels[/<id>] rather than from this process's own
          Redis reads. The URL, the IsAdmin gate and the JSON are unchanged;
          the two new statuses below exist because "the relay did not answer"
          is a thing that can now happen and 500 would say nothing useful.
          """
          # Function-local (D10): this module also hosts stream_ts and
          # stream_xc, which run in the relay process, and relay_client is
          # Django's side of that boundary.
          from apps.proxy import relay_client

          try:
              if channel_id:
                  channel_info = relay_client.get_channel(channel_id)
                  if channel_info is None:
                      return JsonResponse(
                          {"error": f"Channel {channel_id} not found"}, status=404
                      )
                  return JsonResponse(channel_info)

              live_stats = relay_client.list_channels()

              # Send WebSocket update with the stats
              # Format it the same way the original Celery task did
              send_websocket_update(
                  "updates",
                  "update",
                  {
                      "success": True,
                      "type": "channel_stats",
                      "stats": json.dumps(live_stats),
                  }
              )

              return JsonResponse(live_stats)

          except relay_client.RelayRefused as e:
              logger.error(f"Relay refused a status request with {e.status}")
              return JsonResponse({"error": "Relay refused the request"}, status=502)
          except relay_client.RelayUnavailable as e:
              logger.error(f"Relay not available for status: {e}")
              return JsonResponse({"error": "Relay not available"}, status=503)
          except Exception as e:
              logger.error(f"Error in channel_status: {e}", exc_info=True)
              return JsonResponse({"error": str(e)}, status=500)
          finally:
              close_old_connections()
      ```
      The `proxy_server = ProxyServer.get_instance()` line and the
      `if not proxy_server.redis_client:` guard go with it: this view no longer touches Redis, and
      constructing a `ProxyServer` in the API process to read nothing is the coupling the PR
      exists to remove. `close_old_connections()` stays — `IsAdmin` resolved a user through the
      ORM even if the view no longer does.
- [ ] **Step 3: Rewrite `stop_channel` and `stop_client`.** Both keep every response key; only the
      call changes, plus the two new failure statuses:
      ```python
              from apps.proxy import relay_client

              result = relay_client.stop_channel(channel_id)
      ```
      and
      ```python
              from apps.proxy import relay_client

              result = relay_client.stop_client(channel_id, client_id)
      ```
      Add the same two `except` clauses to each, above the existing
      `except Exception`:
      ```python
          except relay_client.RelayRefused as e:
              logger.error(f"Relay refused the stop request with {e.status}")
              return JsonResponse({"error": "Relay refused the request"}, status=502)
          except relay_client.RelayUnavailable as e:
              logger.error(f"Relay not available for the stop request: {e}")
              return JsonResponse({"error": "Relay not available"}, status=503)
      ```
      `stop_client`'s existing `except json.JSONDecodeError` stays first. Because the `import` is
      function-local, move it to the top of each `try:` block so the `except` clauses can name it.
- [ ] **Step 4: Rewrite `change_stream`.** Keep the `stream_id` integer coercion, the
      `resolve_source` call and every response key exactly as they are. Replace the
      `ChannelService.change_stream_url(...)` call and the dead manager-reset block that follows
      it:
      ```python
              # Phase 1 PR 7: the switch is applied by the relay, which is the
              # process that holds the StreamManager. reset_tried carries the
              # tried_stream_ids clear that used to happen here -- PR 4's
              # routing moved this view to the API process, where
              # proxy_server.stream_managers is always empty, so the reset had
              # silently stopped happening.
              result = relay_client.advance(
                  channel_id,
                  url=new_url,
                  user_agent=user_agent,
                  stream_id=stream_id,
                  m3u_profile_id=m3u_profile_id,
                  stream_name=stream_name,
                  reset_tried=True,
              )
      ```
      Delete the `stream_manager = proxy_server.stream_managers.get(channel_id)` block and its
      `if stream_manager:` body. `proxy_server.worker_id` still appears in two response payloads;
      leave both — the field has always reported *the answering worker*, and this view's answering
      worker is the API process. Add the two relay `except` clauses beside the existing
      `except json.JSONDecodeError` and `except Exception`, and move
      `from apps.proxy import relay_client` to the top of the `try:`.
- [ ] **Step 5: Rewrite `next_stream`'s Redis read.** Replace the
      `if proxy_server.redis_client:` metadata block with one relay call, and replace the
      `ChannelService.change_stream_url(...)` call with `relay_client.advance(...)`:
      ```python
              # Phase 1 PR 7: what is playing now comes from the relay, which
              # owns the metadata hash. This view runs in the API process after
              # PR 4's routing, so reading live:channel:<id>:metadata here was
              # the control plane reading a relay key -- invisible to the
              # spec's Done grep, which covers apps/channels, apps/m3u, core
              # and dispatcharr, and exactly what this PR removes.
              running = relay_client.get_channel(channel_id)
              current_stream_id = (running or {}).get("stream_id")
              profile_id = (running or {}).get("m3u_profile_id")
      ```
      and, at the bottom:
      ```python
              result = relay_client.advance(
                  channel_id,
                  url=stream_info["url"],
                  user_agent=stream_info["user_agent"],
                  stream_id=next_stream_id,
                  m3u_profile_id=stream_info.get("m3u_profile_id"),
                  stream_name=stream_info.get("stream_name"),
              )
      ```
      `reset_tried` is deliberately **absent**: `next_stream` has never cleared `tried_stream_ids`,
      and rotating to the next stream is what the exclusion list is for. Keep the two `logger.info`
      lines about the found ids, the `if not current_stream_id:` 404, the whole rotation block, the
      `resolve_source` call and every response key. Add the two relay `except` clauses above the
      existing `except Exception`, below `except Http404: raise`.
      Run: `docker exec … manage.py test --keepdb apps.proxy.live_proxy.tests.test_admin_control_views -v1`
      Expected: OK.
- [ ] **Step 6: Rewrite `combined_stats`' live section.** In `apps/proxy/stats_views.py`, replace
      the `build_live_channel_stats_data` import and call:
      ```python
      from apps.proxy import relay_client
      ```
      ```python
      @api_view(["GET"])
      @permission_classes([IsAdmin])
      def combined_stats(request):
          """Return live, VOD, and catch-up stats in one response."""
          redis_client = RedisClient.get_client()
          if not redis_client:
              return JsonResponse({"error": "Redis not available"}, status=500)

          # Phase 1 PR 7: the live section comes from the relay; the VOD and
          # catch-up sections are built from Django-owned keys and stay here.
          # A relay that cannot answer degrades that one section to empty
          # rather than failing the whole response -- the Stats page reads all
          # three, and blanking VOD and catch-up because the relay is
          # restarting would be a worse answer than an empty live list.
          try:
              live = relay_client.list_channels()
          except (relay_client.RelayUnavailable, relay_client.RelayRefused) as e:
              logger.warning(f"Relay could not answer for combined stats: {e}")
              live = {"channels": [], "count": 0}

          return JsonResponse({
              "live": live,
              "vod": build_vod_stats_data(redis_client),
              "catchup": build_timeshift_stats_data(redis_client),
              "timestamp": time.time(),
          })
      ```
- [ ] **Step 7: Retarget `test_combined_stats.py`.**
      `apps/proxy/tests/test_combined_stats.py:65` is
      `@patch("apps.proxy.stats_views.build_live_channel_stats_data")`, which raises
      `AttributeError` the moment Step 6 removes that import. Replace it with
      `@patch("apps.proxy.stats_views.relay_client.list_channels")`; the decorator's position in
      the stack and the `live_mock` parameter name stay, so nothing else in that test changes.
      Re-run `grep -n "build_live_channel_stats_data" apps/proxy/tests/test_combined_stats.py`
      afterwards, expecting no output. Add one test:
      ```python
          def test_a_relay_outage_empties_only_the_live_section(self):
              from apps.proxy import relay_client

              with mock.patch.object(
                  relay_client, "list_channels",
                  side_effect=relay_client.RelayUnavailable("down"),
              ):
                  response = self.client.get("/proxy/stats/")
              body = response.json()
              self.assertEqual(response.status_code, 200)
              self.assertEqual(body["live"], {"channels": [], "count": 0})
              self.assertIn("vod", body)
              self.assertIn("catchup", body)
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests -v1`
      Expected: OK.
- [ ] **Step 8: Prove the D10 boundary holds.**
      Run: `grep -n "relay_client" apps/proxy/live_proxy/views.py`
      Expected: every hit is `from apps.proxy import relay_client` **indented inside a function**,
      or a `relay_client.` call, or a comment — no line at column 0.
      Run: `grep -rn "relay_client" apps/proxy/live_proxy/ apps/proxy/vod_proxy/ apps/timeshift/ | grep -v "/tests/"`
      Expected: hits in `apps/proxy/live_proxy/views.py` only.
- [ ] **Step 9: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/proxy/live_proxy/views.py apps/proxy/stats_views.py`
      Expected: exit 0. `change_stream`'s existing
      `logger.info(f"... to {redact_url(new_url)}")` already goes through the helper; do not
      un-redact it.
      Write `…/scratchpad/pr7-t6.txt`:
      ```
      refactor(phase1-pr7): the five admin views ask the relay instead of Redis

      channel_status, stop_channel, stop_client, change_stream, next_stream and
      /proxy/stats/ keep their URLs, IsAdmin, methods and JSON. What moved is
      where the answer comes from. next_stream's read of the channel metadata
      hash goes with them: that view runs in the API process after PR 4's
      routing, so it was the control plane reading a relay key.

      Two statuses are new because a new failure exists: 503 when the relay
      cannot be reached, 502 when it refuses. /proxy/stats/ degrades only its
      live section, so a relay restart does not blank VOD and catch-up too.

      change_stream's tried_stream_ids reset moves to the relay via
      reset_tried. It had been dead since PR 4 put the view on a process that
      holds no stream managers.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `apps/proxy/live_proxy/views.py apps/proxy/stats_views.py apps/proxy/tests/test_combined_stats.py apps/proxy/live_proxy/tests/test_admin_control_views.py`, then commit with `-F`.

---

### Task 7: Split `get_user_active_connections` by owner

**Files:**
- Modify: `apps/proxy/utils.py` — `get_user_active_connections`'s live branch and
  `attempt_stream_termination`'s live branch
- Modify: `apps/proxy/tests/test_stream_limits.py`
- Test: same file, plus new cases for the relay-outage path

**Interfaces:** Produces the private `_live_connections(user_id)`. Consumes
`relay_client.list_channels(all_clients=True)` and `relay_client.stop_client`.

**The split, in one sentence:** `live:channel:*:clients:*` is relay-private state Phase 3 moves out
of Redis, while `timeshift:channel:*:clients:*` and `vod_persistent_connection:*` are written by
Django-side handlers and stay exactly where they are. Amendment S1 flagged the intermediate state
PR 5 left here — the API process scanning a relay key from inside `authorize_stream` — and this is
the task that ends it.

- [ ] **Step 1: Write the failing tests.** Append to `apps/proxy/tests/test_stream_limits.py` (read
      its existing fixtures first and reuse them rather than inventing a second Redis fake):
      ```python
      class LiveConnectionsComeFromTheRelayTests(TestCase):
          def test_live_connections_are_read_over_http_not_scanned(self):
              from apps.proxy import relay_client, utils

              payload = {
                  "channels": [
                      {
                          "channel_id": "abc",
                          "clients": [
                              {"client_id": "c1", "user_id": "5", "connected_at": 1000.0},
                              {"client_id": "c2", "user_id": "9", "connected_at": 1001.0},
                          ],
                      }
                  ],
                  "count": 1,
              }
              with mock.patch.object(
                  relay_client, "list_channels", return_value=payload
              ) as listed:
                  connections = utils.get_user_active_connections(5)
              # Uncapped: a cap would under-count a user with more than ten
              # clients on one channel and let them past their stream limit.
              self.assertIs(listed.call_args.kwargs["all_clients"], True)
              live = [c for c in connections if c["type"] == "live"]
              self.assertEqual(
                  live,
                  [{"media_id": "abc", "client_id": "c1", "connected_at": 1000.0,
                    "type": "live"}],
              )

          def test_user_id_none_returns_every_live_client(self):
              from apps.proxy import relay_client, utils

              payload = {
                  "channels": [
                      {
                          "channel_id": "abc",
                          "clients": [
                              {"client_id": "c1", "user_id": "5", "connected_at": 1.0},
                              {"client_id": "c2", "user_id": "9", "connected_at": 2.0},
                          ],
                      }
                  ],
                  "count": 1,
              }
              with mock.patch.object(relay_client, "list_channels", return_value=payload):
                  connections = utils.get_user_active_connections(None)
              self.assertEqual(
                  len([c for c in connections if c["type"] == "live"]), 2
              )

          def test_an_unreachable_relay_contributes_no_live_connections(self):
              # A relay that cannot answer is a relay serving no live clients,
              # so failing open is both correct and safe. Failing closed would
              # 429 every tune for the length of a relay restart.
              from apps.proxy import relay_client, utils

              with mock.patch.object(
                  relay_client, "list_channels",
                  side_effect=relay_client.RelayUnavailable("down"),
              ):
                  connections = utils.get_user_active_connections(5)
              self.assertEqual([c for c in connections if c["type"] == "live"], [])

          def test_terminating_a_live_client_goes_through_the_relay(self):
              from apps.proxy import relay_client, utils

              with mock.patch.object(
                  relay_client, "stop_client", return_value={"status": "success"}
              ) as stopped:
                  freed = utils.attempt_stream_termination(
                      5,
                      "requester",
                      [{"media_id": "abc", "client_id": "c1", "connected_at": 1.0,
                        "type": "live"}],
                  )
              stopped.assert_called_once_with("abc", "c1")
              self.assertTrue(freed)

          def test_a_relay_that_cannot_stop_denies_the_new_stream(self):
              from apps.proxy import relay_client, utils

              with mock.patch.object(
                  relay_client, "stop_client",
                  side_effect=relay_client.RelayUnavailable("down"),
              ):
                  freed = utils.attempt_stream_termination(
                      5,
                      "requester",
                      [{"media_id": "abc", "client_id": "c1", "connected_at": 1.0,
                        "type": "live"}],
                  )
              self.assertFalse(freed)
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_stream_limits -v1`
      Expected: FAIL.
- [ ] **Step 2: Replace the live branch of `get_user_active_connections`.** Add above it:
      ```python
      def _live_connections(user_id):
          """The live half of get_user_active_connections, over HTTP.

          live:channel:*:clients:* is relay-private state -- the family
          Phase 3 moves out of Redis -- so the control plane asks the relay
          for it rather than scanning it. all_clients=True because a cap
          under-counts a user with more than ten clients on one channel,
          which is exactly the case this function exists to catch, and
          TUNE_TIMEOUT because authorize_stream calls this on every tune.

          A relay that cannot answer contributes nothing and logs once. That
          fails open, and open is correct here: the relay is the only process
          serving live clients, so a relay that is not answering has none.
          Failing closed would 429 every tune for the length of a restart.
          """
          from apps.proxy import relay_client

          try:
              # TUNE_TIMEOUT, not the admin budget: check_user_stream_limits
              # calls this from inside authorize_stream, so it is on the tune
              # path for every stream-limited user, and Global Constraints put
              # tune-path reads at (1, 2) with no retry.
              payload = relay_client.list_channels(
                  all_clients=True, timeout=relay_client.TUNE_TIMEOUT
              )
          except (relay_client.RelayUnavailable, relay_client.RelayRefused) as exc:
              logger.warning(
                  "[stream limits] the relay could not list channels: %s", exc
              )
              return []

          connections = []
          for channel in payload.get("channels") or []:
              media_id = channel.get("channel_id")
              for client in channel.get("clients") or []:
                  raw_user_id = client.get("user_id")
                  if user_id is not None:
                      try:
                          if raw_user_id is None or int(raw_user_id) != user_id:
                              continue
                      except (TypeError, ValueError):
                          continue
                  try:
                      connected_at = float(client.get("connected_at") or 0)
                  except (TypeError, ValueError):
                      continue
                  connections.append({
                      'media_id': media_id,
                      'client_id': client.get("client_id"),
                      'connected_at': connected_at,
                      'type': 'live',
                  })
          return connections
      ```
      Then in `get_user_active_connections`, replace the two-pattern loop with the timeshift
      pattern alone and seed the list from `_live_connections`:
      ```python
      def get_user_active_connections(user_id):
          """Return active stream connections for a single user.

          Pass `user_id=None` to return all active connections across the system.

          Phase 1 PR 7 split this by owner. The live connections come from the
          relay over GET /proxy/relay/channels?clients=all; the timeshift and
          VOD key families are written by Django-side handlers, are not relay
          state, and keep being read here.
          """
          redis_client = RedisClient.get_client()
          connections = _live_connections(user_id)

          try:
              # Timeshift only: same key layout as the live family, different
              # namespace and a different owner.
              for key in redis_client.scan_iter(
                  match="timeshift:channel:*:clients:*", count=1000
              ):
      ```
      Keep the body of that loop byte for byte, with `conn_type` replaced by the literal
      `'timeshift'` in the two places it appears, and keep the VOD loop and the
      `except Exception: return []` tail unchanged.
- [ ] **Step 3: Route the live termination through the relay.** In `attempt_stream_termination`,
      replace the `t['type'] == 'live'` branch:
      ```python
                  if t['type'] == 'live':
                      from apps.proxy import relay_client

                      try:
                          result = relay_client.stop_client(t['media_id'], t['client_id'])
                      except (relay_client.RelayUnavailable, relay_client.RelayRefused) as exc:
                          # Deny the new stream if we cannot stop the old one,
                          # exactly as the timeshift branch below does when
                          # Redis is unavailable.
                          logger.warning(
                              f"[stream limits][{requesting_client_id}] Relay could not "
                              f"stop client {t['client_id']}: {exc}"
                          )
                          return False
                      if result.get("status") == "error":
                          logger.warning(f"[stream limits][{requesting_client_id}] Failed to stop client {t['client_id']} on channel {t['media_id']}")
      ```
      Delete the now-unused `ChannelService` import from the module header if nothing else in
      `apps/proxy/utils.py` uses it.
      Run: `grep -n "ChannelService" apps/proxy/utils.py`
      Expected: no output.
- [ ] **Step 4: Retarget the existing test that patches the deleted import.**
      `apps/proxy/tests/test_stream_limits.py`'s `test_live_termination_still_uses_channel_service`
      does `patch("apps.proxy.utils.ChannelService.stop_client", return_value={"status": "ok"})`.
      The moment Step 3 removes that import, the patch raises `AttributeError` and the suite is
      red — this is not optional cleanup. **Delete that test**: Step 1's
      `test_terminating_a_live_client_goes_through_the_relay` asserts the same property
      (`stop_mock.assert_called_once_with("42", "live_client_1")` becomes
      `stopped.assert_called_once_with("abc", "c1")`) against the call site that now exists, and
      `test_a_relay_that_cannot_stop_denies_the_new_stream` adds the failure mode the old test had
      no way to express. Keeping both would leave one asserting a name the module no longer has.
      Run: `grep -rn "apps.proxy.utils.ChannelService" apps/proxy/tests/`
      Expected: no output.
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests -v1`
      Expected: OK.
- [ ] **Step 5: Check the other consumer of this function.** `apps/output/views.py` imports
      `get_user_active_connections` at module level.
      Run: `grep -n "get_user_active_connections" -A 6 apps/output/views.py`
      Read what it does with the result. The signature and the dict shape are unchanged, so no edit
      should be needed; if that call site indexes a key `_live_connections` no longer produces,
      stop and report rather than widening the payload.
      Run: `docker exec … manage.py test --keepdb apps.output.tests -v1`
      Expected: OK. (`apps.output.tests` is not in this PR's routed label set; run it once here
      because this is the only task that could reach it.)
- [ ] **Step 6: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/proxy/utils.py`
      Expected: exit 0.
      Write `…/scratchpad/pr7-t7.txt` with the subject
      `refactor(phase1-pr7): live connections come from the relay, timeshift and VOD stay in Redis`
      and a body naming the three key families, the uncapped read, and the fail-open reasoning.
      End it with the two attribution lines. Stage
      `apps/proxy/utils.py apps/proxy/tests/test_stream_limits.py`, then commit with `-F`.

---

### Task 8: `apps/channels/models.py` — the reuse check, and delete the preemption corpse

**Files:**
- Modify: `apps/channels/models.py`
- Modify: `apps/channels/tests/test_get_stream_assignment.py` — five tests whose relay-state source
  moves; assertions unchanged
- Test: `apps/channels/tests/test_channel_stream_reuse.py` (new)

**Interfaces:** Consumes `relay_client.channel_snapshot`. Removes
`Channel._channel_proxy_is_active` and `Channel._pick_channel_to_preempt`.

**Two deletions, for different reasons.** `_channel_proxy_is_active` goes because
`relay_client.channel_snapshot()` *is* the relay-client route the spec asks for and answers both of
`_stream_assignment_is_reusable`'s questions in one round trip; keeping a one-line wrapper would
cost a second HTTP call on the tune path or leave a method with no caller.
`_pick_channel_to_preempt` goes because it is dead three times over (ruling 8).

- [ ] **Step 1: Find every caller, in code and in tests.**
      Run: `grep -rn "_channel_proxy_is_active\|_pick_channel_to_preempt\|_stream_assignment_is_reusable" --include=\*.py .`
      Expected: `apps/channels/models.py` and **`apps/channels/tests/test_get_stream_assignment.py`**,
      which Step 2 rewrites. Nothing calls `_pick_channel_to_preempt` from a test. If any other
      caller appears, stop and report — this task's whole premise is that
      `_stream_assignment_is_reusable` is `_channel_proxy_is_active`'s only caller.
- [ ] **Step 2: Rewrite `test_get_stream_assignment.py`'s relay-state source.** That file's five
      tests seed `live:channel:<uuid>:metadata` in a `FakeAssignmentRedis` and assert
      `get_stream()`'s reuse-or-stale outcome from it. After this task the state comes from
      `relay_client.channel_snapshot`, which in the test container would dial `127.0.0.1:9191`, get
      connection-refused, report `present=False` and fall through to the Django-owned key —
      **`test_reuses_assignment_when_proxy_active`,
      `test_releases_stale_assignment_when_proxy_stopped` and
      `test_stream_assignment_not_reusable_when_stopped` would all fail**, and the other two would
      pass only after burning a connect timeout each. Do not rewrite what the tests assert; change
      only where the state is read from, with one helper that answers `channel_snapshot` out of the
      same fake Redis the tests already seed. Add to `ChannelGetStreamAssignmentTests`:
      ```python
          def _relay_snapshot(self):
              """Answer channel_snapshot from the fake Redis these tests seed.

              Phase 1 PR 7 moved "is the proxy running" off a direct metadata
              read and onto GET /proxy/relay/channels/<uuid>?fields=state. The
              metadata hash is still where the relay reads it and still what
              these tests seed; only who reads it changed. Without this the
              call leaves the process, is refused, and every state-dependent
              assertion below silently becomes an assertion about a relay
              outage instead.
              """
              from apps.proxy import relay_client

              reusable = (
                  ChannelState.ACTIVE,
                  ChannelState.WAITING_FOR_CLIENTS,
                  ChannelState.BUFFERING,
                  ChannelState.INITIALIZING,
                  ChannelState.CONNECTING,
              )

              def _snapshot(identifier, **kwargs):
                  if not self.redis.exists(self.metadata_key):
                      return relay_client.ChannelSnapshot(
                          present=False, active=False, reachable=True
                      )
                  state = self.redis.hget(
                      self.metadata_key, ChannelMetadataField.STATE
                  )
                  return relay_client.ChannelSnapshot(
                      present=True, active=state in reusable, reachable=True
                  )

              return patch(
                  "apps.proxy.relay_client.channel_snapshot", side_effect=_snapshot
              )
      ```
      Then wrap each of the five test bodies in `with self._relay_snapshot():` — including the two
      that would accidentally pass, so no test in the file makes a network call. The patch target
      is `apps.proxy.relay_client.channel_snapshot`, not a name on `apps.channels.models`: the
      method imports the module function-locally.
      Run: `docker exec … manage.py test --keepdb apps.channels.tests.test_get_stream_assignment -v1`
      Expected: **OK** — the patch is applied but unused until Step 4 moves the read, and an unused
      patch fails nothing: the five tests still read the seeded fake Redis directly and pass. This
      step is a no-op on the result and a prerequisite for Step 4; **the file must stay green
      across Step 4 as well**, which is where the patch starts doing work.
- [ ] **Step 3: Write the failing tests.** Create
      `apps/channels/tests/test_channel_stream_reuse.py`:
      ```python
      """Channel.get_stream()'s reuse check asks the relay, not Redis.

      live:channel:<uuid>:metadata is relay-owned. channel_stream:<pk> and
      stream_profile:<id> are Django-owned (PR 6) and stay a direct read --
      the fallback branch below is reading Django's own key, which is why it
      is still Redis here.
      """

      from unittest import mock

      from django.test import TestCase

      from apps.channels.models import Channel
      from apps.proxy import relay_client
      from apps.proxy.live_proxy.redis_keys import RedisKeys


      class _Redis:
          def __init__(self, values=None):
              self._values = values or {}

          def get(self, key):
              return self._values.get(key)


      class StreamAssignmentReuseTests(TestCase):
          def setUp(self):
              self.channel = Channel.objects.create(name="One", channel_number=1)

          def _snapshot(self, **kwargs):
              defaults = {"present": False, "active": False, "reachable": True}
              defaults.update(kwargs)
              return relay_client.ChannelSnapshot(**defaults)

          def test_a_running_channel_keeps_its_assignment(self):
              with mock.patch.object(
                  relay_client, "channel_snapshot",
                  return_value=self._snapshot(present=True, active=True),
              ):
                  self.assertTrue(
                      self.channel._stream_assignment_is_reusable(_Redis(), 7)
                  )

          def test_metadata_not_written_yet_falls_back_to_the_django_owned_key(self):
              # Between get_stream() reserving and initialize_channel()
              # starting, the relay holds nothing and stream_profile:<id> is
              # what says the assignment is real.
              redis = _Redis({RedisKeys.stream_profile(7): "3"})
              with mock.patch.object(
                  relay_client, "channel_snapshot", return_value=self._snapshot()
              ):
                  self.assertTrue(
                      self.channel._stream_assignment_is_reusable(redis, 7)
                  )
              with mock.patch.object(
                  relay_client, "channel_snapshot", return_value=self._snapshot()
              ):
                  self.assertFalse(
                      self.channel._stream_assignment_is_reusable(_Redis(), 7)
                  )

          def test_metadata_present_but_inactive_is_a_stale_assignment(self):
              redis = _Redis({RedisKeys.stream_profile(7): "3"})
              with mock.patch.object(
                  relay_client, "channel_snapshot",
                  return_value=self._snapshot(present=True, active=False),
              ):
                  self.assertFalse(
                      self.channel._stream_assignment_is_reusable(redis, 7)
                  )

          def test_the_relay_is_asked_once_not_twice(self):
              with mock.patch.object(
                  relay_client, "channel_snapshot",
                  return_value=self._snapshot(present=True, active=True),
              ) as asked:
                  self.channel._stream_assignment_is_reusable(_Redis(), 7)
              self.assertEqual(asked.call_count, 1)

          def test_an_unreachable_relay_reuses_rather_than_re_reserving(self):
              # A snapshot with reachable=False reports present=False, which
              # sends this to the Django-owned fallback. Reusing cannot leak a
              # provider slot; re-reserving could.
              redis = _Redis({RedisKeys.stream_profile(7): "3"})
              with mock.patch.object(
                  relay_client, "channel_snapshot",
                  return_value=self._snapshot(reachable=False),
              ):
                  self.assertTrue(
                      self.channel._stream_assignment_is_reusable(redis, 7)
                  )


      class PreemptionIsGoneTests(TestCase):
          def test_the_preemption_corpse_is_deleted(self):
              # It never returned a channel: models.py imports no `time`, the
              # index key it prefers is written nowhere, and the scan fallback
              # int()s a UUID. Deleting it removes code, not a feature -- there
              # was never a feature.
              self.assertFalse(hasattr(Channel, "_pick_channel_to_preempt"))
              self.assertFalse(hasattr(Channel, "_channel_proxy_is_active"))
      ```
      Run: `docker exec … manage.py test --keepdb apps.channels.tests.test_channel_stream_reuse -v1`
      Expected: FAIL.
- [ ] **Step 4: Rewrite the reuse check and delete `_channel_proxy_is_active`.** Replace both
      methods with one:
      ```python
          def _stream_assignment_is_reusable(self, redis_client, stream_id: int) -> bool:
              """
              Return True when an existing channel_stream assignment should be reused.

              Reuse when the proxy is active, or when metadata is not written yet
              (between get_stream() reserving slots and initialize_channel() starting).
              When metadata exists but the proxy is inactive, the assignment is stale.

              Phase 1 PR 7: whether the proxy is active is the relay's answer, not
              a read of live:channel:<uuid>:metadata from here -- that hash is
              relay-owned and this method runs in the API process, inside
              Channel.get_stream(). One snapshot answers both questions, so the
              tune path pays one round trip and not two. stream_profile:<id> is
              still read directly because PR 6 made it Django's own key.
              """
              from apps.proxy import relay_client

              snapshot = relay_client.channel_snapshot(str(self.uuid))
              if snapshot.active:
                  return True
              if not snapshot.present:
                  return redis_client.get(RedisKeys.stream_profile(stream_id)) is not None
              return False
      ```
      Run: `docker exec … manage.py test --keepdb apps.channels.tests.test_channel_stream_reuse apps.channels.tests.test_get_stream_assignment -v1`
      Expected: OK — **both** files. Step 2's retargeted patch is what makes the second one pass; a
      failure there means the patch target is wrong (it is
      `apps.proxy.relay_client.channel_snapshot`, because this method imports the module
      function-locally), not that an assertion needs changing.
- [ ] **Step 5: Delete `_pick_channel_to_preempt` and its call site.** Remove the whole method
      (from `def _pick_channel_to_preempt(` through its `return victim_id`). At the call site,
      replace the `else:` block's preemption attempt with a comment and keep everything from
      `has_streams_but_maxed_out = True` onward:
      ```python
                  else:
                      # At capacity on this profile. A preemption attempt used to
                      # run here and could never succeed: _pick_channel_to_preempt
                      # scored candidates it never found (the profile index key it
                      # reads is written nowhere, and its scan fallback int()s a
                      # channel UUID), reached a cooldown check against a `time`
                      # this module never imported, and returned into a commented-out
                      # `return`. Deleted in Phase 1 PR 7. Channel preemption stays
                      # unimplemented -- that is unchanged, not decided here.
                      has_streams_but_maxed_out = True
      ```
- [ ] **Step 6: Drop `ChannelState` from the module-level import.**
      Run: `grep -n "ChannelState" apps/channels/models.py`
      Expected: only line 7. Change that line to
      `from apps.proxy.live_proxy.constants import ChannelMetadataField` and re-run the grep:
      expected no output. **Do not touch line 6** — `RedisKeys` is how this module reaches
      `channel_stream:` and `stream_profile:`, the two keys PR 6 made it the sole writer of
      (ruling 9).
      Run: `grep -c "ChannelMetadataField" apps/channels/models.py`
      Expected: a number greater than 1 — the release-path metadata fallbacks (ruling 10's named
      straggler) still use it. If it is 1, the import is now unused and both lines can go; report
      that, because it changes Task 14's recorded audit outcome.
- [ ] **Step 7: Run the migration check and both affected label sets.**
      Run: `docker exec … manage.py makemigrations --check --dry-run dispatcharr_channels`
      Expected: `No changes detected` — deleting a method is not a model change. The label is
      `dispatcharr_channels`, never `channels`, which resolves to the Django Channels library and
      exits 0 for the wrong reason.
      Run: `docker exec … manage.py test --keepdb apps.channels.tests apps.proxy.tests apps.proxy.live_proxy.tests -v1`
      Expected: OK. `apps/channels/tests/test_ts_proxy_teardown.py` builds a real `ProxyServer` ten
      times and is the richest test of this area; a failure there is a real finding.
- [ ] **Step 8: Confirm the Done grep is now empty.**
      Run, as one command (ruling 7):
      ```bash
      grep -rn "live:channel:\|channel_stream:\|stream_profile:" apps/channels/ apps/m3u/ core/ dispatcharr/ \
        | grep -v tests \
        | grep -v "self.stream_profile:\|not stream_profile:"
      ```
      Expected: **empty**. Run the same grep without the second exclusion pipe as a cross-check: it
      should print exactly the two `apps/channels/models.py` attribute accesses and nothing else,
      which is what makes the exclusion honest rather than a way of hiding a real hit.
- [ ] **Step 9: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/channels/models.py`
      Expected: exit 0.
      Write `…/scratchpad/pr7-t8.txt` with the subject
      `refactor(phase1-pr7): the reuse check asks the relay; the preemption corpse is deleted`
      and a body carrying ruling 8's three reasons the function never returned a channel, the
      one-snapshot-not-two point, and the note that channel preemption stays unimplemented. End it
      with the two attribution lines. Stage
      `apps/channels/models.py apps/channels/tests/test_channel_stream_reuse.py apps/channels/tests/test_get_stream_assignment.py`,
      then commit with `-F`.

---

### Task 9: The six Django-side `ChannelService` call sites and the two DVR client scans

**Files:**
- Modify: `apps/channels/api_views.py` — `_stop_proxy_sessions_for_channel_ids`,
  `_stop_dvr_clients`, `RecordingViewSet.destroy`
- Modify: `apps/m3u/tasks.py` — `_delete_channels_stopping_streams`
- Modify: `apps/m3u/api_views.py` — the account `destroy` path
- Test: `apps/channels/tests/test_dvr_client_teardown.py` (new)

**Interfaces:** Consumes `relay_client.{stop_channels, stop_client, stop_channel, get_channel}`.
The sixth site, `apps/proxy/utils.py:attempt_stream_termination`, moved in Task 7.

**The two DVR blocks are near-duplicates and both are rewritten, not merged.** They differ in three
ways the tree records — one decodes bytes and the other does not, one filters on a recording id,
one stops the channel when no clients remain — and merging them is a refactor this PR has not
budgeted for. Each keeps its own shape; both stop scanning `RedisKeys.clients` /
`RedisKeys.client_metadata` and read the client list off `relay_client.get_channel` instead, which
returns the **detailed** payload: uncapped, and carrying `user_agent` on every client.

- [ ] **Step 1: Write the failing tests.** Create
      `apps/channels/tests/test_dvr_client_teardown.py`:
      ```python
      """Stopping DVR clients no longer scans the relay's client keys.

      Both blocks used RedisKeys.clients / RedisKeys.client_metadata directly.
      They now read GET /proxy/relay/channels/<uuid>, whose detailed payload
      carries every client and every client's user_agent -- which is what the
      "Dispatcharr-DVR" match needs.
      """

      from unittest import mock

      from django.test import TestCase

      from apps.channels import api_views
      from apps.proxy import relay_client


      def _channel(clients):
          return {"channel_id": "abc", "client_count": len(clients), "clients": clients}


      class StopDvrClientsTests(TestCase):
          def test_only_dvr_clients_are_stopped(self):
              payload = _channel([
                  {"client_id": "c1", "user_agent": "Dispatcharr-DVR/recording-7"},
                  {"client_id": "c2", "user_agent": "VLC/3.0"},
              ])
              with mock.patch.object(
                  relay_client, "get_channel", return_value=payload
              ), mock.patch.object(
                  relay_client, "stop_client", return_value={"status": "success"}
              ) as stopped:
                  count = api_views._stop_dvr_clients("abc")
              self.assertEqual(count, 1)
              stopped.assert_called_once_with("abc", "c1")

          def test_a_recording_id_narrows_the_match(self):
              payload = _channel([
                  {"client_id": "c1", "user_agent": "Dispatcharr-DVR/recording-7"},
                  {"client_id": "c2", "user_agent": "Dispatcharr-DVR/recording-8"},
              ])
              with mock.patch.object(
                  relay_client, "get_channel", return_value=payload
              ), mock.patch.object(
                  relay_client, "stop_client", return_value={"status": "success"}
              ) as stopped:
                  count = api_views._stop_dvr_clients("abc", recording_id=8)
              self.assertEqual(count, 1)
              stopped.assert_called_once_with("abc", "c2")

          def test_a_channel_the_relay_does_not_hold_stops_nothing(self):
              with mock.patch.object(
                  relay_client, "get_channel", return_value=None
              ), mock.patch.object(relay_client, "stop_client") as stopped:
                  self.assertEqual(api_views._stop_dvr_clients("abc"), 0)
              stopped.assert_not_called()

          def test_an_unreachable_relay_stops_nothing_and_does_not_raise(self):
              with mock.patch.object(
                  relay_client, "get_channel",
                  side_effect=relay_client.RelayUnavailable("down"),
              ):
                  self.assertEqual(api_views._stop_dvr_clients("abc"), 0)
      ```
      Run: `docker exec … manage.py test --keepdb apps.channels.tests.test_dvr_client_teardown -v1`
      Expected: FAIL.
- [ ] **Step 2: Rewrite `_stop_proxy_sessions_for_channel_ids`.** Replace the two lines that import
      and call `ChannelService`:
      ```python
          from apps.proxy import relay_client

          uuids = list(
              Channel.objects.filter(id__in=channel_ids).values_list("uuid", flat=True)
          )
          relay_client.stop_channels(uuids)
      ```
      `relay_client.stop_channels` has the same never-raises contract `ChannelService.stop_channels`
      had, which is what the docstring above it depends on: teardown runs outside Django's delete
      atomic and must never block the delete.
- [ ] **Step 3: Rewrite `_stop_dvr_clients`.** Replace the Redis scan and the per-client
      `hget` with one relay read, keeping the user-agent match, the recording-id filter and the
      per-client `try/except` shape:
      ```python
          from apps.proxy import relay_client

          try:
              channel_info = relay_client.get_channel(channel_uuid)
          except (relay_client.RelayUnavailable, relay_client.RelayRefused) as e:
              logger.debug(f"Relay could not list clients for channel {channel_uuid}: {e}")
              return 0
          if not channel_info:
              return 0

          stopped = 0
          for client in channel_info.get("clients") or []:
              try:
                  cid = client.get("client_id")
                  ua_s = client.get("user_agent") or ""
                  if not (cid and "Dispatcharr-DVR" in ua_s):
                      continue
                  # When a recording_id is specified, only stop the client for that recording.
                  # Each run_recording task connects with User-Agent "Dispatcharr-DVR/recording-{id}",
                  # so we can safely target just this recording without affecting others on the channel.
                  if recording_id is not None and f"recording-{recording_id}" not in ua_s:
                      continue
                  try:
                      relay_client.stop_client(channel_uuid, cid)
                      stopped += 1
                  except Exception as inner_e:
                      logger.debug(f"Failed to stop DVR client {cid} for channel {channel_uuid}: {inner_e}")
              except Exception as inner:
                  logger.debug(f"Error while checking client metadata: {inner}")
      ```
      The bytes-decoding of `cid` and `ua` goes: JSON gives strings. Keep the comment block below
      about deliberately not calling `stop_channel` here.
- [ ] **Step 4: Rewrite `RecordingViewSet.destroy`'s block.** Same read, plus the
      remaining-client check, which becomes a second relay read rather than an `scard`:
      ```python
                  from apps.proxy import relay_client

                  channel_info = relay_client.get_channel(channel_uuid)
                  stopped = 0
                  for client in (channel_info or {}).get("clients") or []:
                      try:
                          cid = client.get("client_id")
                          ua = client.get("user_agent") or ""
                          # Identify DVR recording client by its user agent
                          if cid and "Dispatcharr-DVR" in ua:
                              try:
                                  relay_client.stop_client(channel_uuid, cid)
                                  stopped += 1
      ```
      keeping the inner `except` exactly as it is, and then:
      ```python
                  if stopped:
                      logger.info(f"Stopped {stopped} DVR client(s) for channel {channel_uuid} due to recording cancellation")
                  # If no clients remain after stopping DVR clients, proactively stop the channel
                  try:
                      remaining = (relay_client.get_channel(channel_uuid) or {}).get(
                          "client_count", 0
                      )
                  except Exception:
                      remaining = 0
                  if remaining == 0:
                      try:
                          relay_client.stop_channel(channel_uuid)
                          logger.info(f"Stopped channel {channel_uuid} (no clients remain)")
                      except Exception as sc_e:
                          logger.debug(f"Unable to stop channel {channel_uuid}: {sc_e}")
      ```
      Delete the `r = RedisClient.get_client()` / `if r:` scaffolding around it, and the
      `RedisKeys` and `ChannelService` function-local imports, keeping the enclosing
      `try: … except Exception as e: logger.debug(...)`. **A stop is asynchronous** — it sets a key
      and publishes — so the re-read can still see the client, exactly as the `scard` could. That
      is unchanged behaviour, not a regression this task introduces.
- [ ] **Step 5: Rewrite the two `apps/m3u` sites.** In `apps/m3u/tasks.py`'s
      `_delete_channels_stopping_streams`:
      ```python
          from apps.channels.models import Channel
          from apps.proxy import relay_client
      ```
      ```python
          try:
              relay_client.stop_channels(
                  getattr(channel, "uuid", None) for channel in channel_list
              )
          except Exception as e:
              # stop_channels is best-effort and normally never raises; never block
              # the DB delete on proxy teardown failure.
              logger.warning("Failed stopping proxy sessions before channel delete: %s", e)
      ```
      and in `apps/m3u/api_views.py`'s account `destroy`:
      ```python
          from apps.channels.models import Channel
          from apps.proxy import relay_client
      ```
      ```python
          relay_client.stop_channels(
              channel_uuid for _, channel_uuid in channels_to_delete
          )
      ```
- [ ] **Step 6: Prove no `ChannelService` import is left in the control plane.**
      Run: `grep -rn --include=\*.py "ChannelService" apps/channels apps/m3u core dispatcharr | grep -v "/tests/"`
      Expected: **four lines, every one a comment or a docstring** — `apps/channels/models.py`'s
      "(e.g. from `_clean_redis_keys` or `ChannelService.stop_channel`)",
      `apps/channels/api_views.py`'s "Do not call ChannelService.stop_channel() here", and
      `core/relay_events.py`'s two references to `ChannelService._update_stream_stats_in_db`, in a
      docstring and a comment. **No call site.** Reword only the `api_views.py` one to name
      `relay_client.stop_channel` instead, so the comment still describes the code beside it; the
      other three describe relay-side code that has not moved and are correct as they stand.
      Run: `grep -rn --include=\*.py "RedisKeys\.\|ChannelMetadataField" apps/channels/api_views.py`
      Expected: no output.
- [ ] **Step 7: Run the three affected labels.**
      Run: `docker exec … manage.py test --keepdb apps.channels.tests apps.m3u.tests apps.proxy.tests -v1`
      Expected: OK.
- [ ] **Step 8: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/channels/api_views.py apps/m3u/tasks.py apps/m3u/api_views.py`
      Expected: exit 0.
      Write `…/scratchpad/pr7-t9.txt` with the subject
      `refactor(phase1-pr7): the six Django-side ChannelService calls go over HTTP`
      and a body naming the five files, the two DVR client scans that stop reading
      RedisKeys.clients, and the never-raises contract stop_channels keeps. End it with the two
      attribution lines. Stage
      `apps/channels/api_views.py apps/m3u/tasks.py apps/m3u/api_views.py apps/channels/tests/test_dvr_client_teardown.py`,
      then commit with `-F`.

---

### Task 10: `core/tasks.py` and the DVR's recording metadata

**Files:**
- Modify: `core/tasks.py` — `fetch_channel_stats` and the module-level `live_proxy` import
- Modify: `apps/channels/tasks.py` — `run_recording`'s metadata capture
- Test: `core/tests/test_fetch_channel_stats.py` (new)

**Interfaces:** Consumes `relay_client.list_channels` and `relay_client.get_channel`.

**Both run in the `worker` role, which is why D9's resolver has to produce a network address.**
`fetch_channel_stats` is a beat task and `run_recording` runs on the `dvr` queue; neither container
has an nginx to loop back to, so both reach the api role's by service name (ruling 1).

**`core/tasks.py:10` is the only eager module-level import of a relay module in the control
plane** — every other one in the surveyed set is function-local. It goes, which is what makes
`from apps.proxy.live_proxy.channel_status import build_live_channel_stats_data` disappear from
`core/`.

- [ ] **Step 1: Write the failing test.** Create `core/tests/test_fetch_channel_stats.py`:
      ```python
      """The beat task that broadcasts channel_stats asks the relay.

      It runs in the worker role, which has no nginx of its own and no access
      to a relay-owned Redis key it has any business reading. A relay outage
      must not push an empty stats payload: the Stats page clears its rows on
      one, and a restarting relay is not an idle system.
      """

      from unittest import mock

      from django.test import TestCase

      from apps.proxy import relay_client
      from core import tasks


      class FetchChannelStatsTests(TestCase):
          def test_the_payload_is_the_relay_s_channel_list(self):
              payload = {"channels": [{"channel_id": "abc"}], "count": 1}
              with mock.patch.object(
                  relay_client, "list_channels", return_value=payload
              ), mock.patch.object(tasks, "send_websocket_update") as pushed:
                  tasks.fetch_channel_stats()
              message = pushed.call_args.args[2]
              self.assertEqual(message["type"], "channel_stats")
              self.assertEqual(message["stats"], tasks.json.dumps(payload))

          def test_a_relay_outage_pushes_nothing_at_all(self):
              with mock.patch.object(
                  relay_client, "list_channels",
                  side_effect=relay_client.RelayUnavailable("down"),
              ), mock.patch.object(tasks, "send_websocket_update") as pushed:
                  tasks.fetch_channel_stats()
              pushed.assert_not_called()

          def test_core_tasks_no_longer_imports_a_relay_module_at_module_level(self):
              import inspect

              source = inspect.getsource(tasks)
              header = source.split("def ", 1)[0]
              self.assertNotIn("apps.proxy.live_proxy", header)
      ```
      Run: `docker exec … manage.py test --keepdb core.tests.test_fetch_channel_stats -v1`
      Expected: FAIL.
- [ ] **Step 2: Rewrite `fetch_channel_stats`.** Delete `core/tasks.py`'s module-level
      `from apps.proxy.live_proxy.channel_status import build_live_channel_stats_data` and replace
      the function body:
      ```python
      def fetch_channel_stats():
          # Function-local: this task runs in the worker role, and importing a
          # relay module at module level made every Celery child load it.
          from apps.proxy import relay_client

          try:
              live_stats = relay_client.list_channels()
          except (relay_client.RelayUnavailable, relay_client.RelayRefused) as e:
              # Push nothing rather than an empty payload: the Stats page
              # clears its rows on one, and a restarting relay is not an idle
              # system.
              logger.warning(f"Relay could not answer for channel stats: {e}")
              return
          except Exception as e:
              logger.error(f"Error in channel_status: {e}", exc_info=True)
              return

          send_websocket_update(
              "updates",
              "update",
              {
                  "success": True,
                  "type": "channel_stats",
                  "stats": json.dumps(live_stats),
              },
              collect_garbage=True
          )
      ```
      The `redis_client = RedisClient.get_client()` line goes with it. Check whether `RedisClient`
      is still used elsewhere in `core/tasks.py` before removing its import
      (`grep -n "RedisClient" core/tasks.py`).
- [ ] **Step 3: Rewrite `run_recording`'s metadata capture.** In `apps/channels/tasks.py`, replace
      the Redis read at the head of that block, keeping `_d` and both field loops verbatim:
      ```python
              # Try to get stream stats from the relay's status payload
              try:
                  from apps.proxy import relay_client
                  from apps.proxy.live_proxy.constants import ChannelMetadataField

                  # Phase 1 PR 7: this runs in the dvr Celery worker, which has
                  # no business reading live:channel:<uuid>:metadata directly.
                  # The relay's detailed payload uses the same key names --
                  # ChannelMetadataField's values are exactly the JSON keys --
                  # so the eleven fields below and the casts they carry are
                  # unchanged, and Recording.custom_properties["stream_info"]
                  # comes out identical. width, height and video_bitrate were
                  # added to that payload for this call.
                  md = relay_client.get_channel(str(channel.uuid)) or {}
                  if md:
                      def _d(bkey, cast=str):
      ```
      Keep the rest of the block — `_d`'s body, both `for key, caster in [...]` loops, the
      `if stream_info: cp["stream_info"] = stream_info`, and the outer
      `except Exception as e: logger.debug(...)` — exactly as it is. Delete the
      `from apps.proxy.live_proxy.redis_keys import RedisKeys`, the `from core.utils import
      RedisClient` line **only if nothing else in that `try:` uses it**, the
      `r = RedisClient.get_client()` / `if r is not None:` scaffolding and the
      `metadata_key = …` / `md = r.hgetall(metadata_key)` pair. Re-indent the body by one level
      where the `if r is not None:` guard is removed.
- [ ] **Step 4: Verify the DVR's stored shape is unchanged.**
      Run: `grep -n "stream_info" apps/channels/tasks.py`
      Read the surrounding lines and confirm `cp["stream_info"]` is still assigned from the same
      `stream_info` dict built by the same two loops. Then:
      Run: `docker exec … manage.py test --keepdb apps.channels.tests core.tests -v1`
      Expected: OK. If a DVR test asserts on a `stream_info` key, it is the strongest check this
      step has — read its failure before changing it.
- [ ] **Step 5: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py core/tasks.py apps/channels/tasks.py`
      Expected: exit 0.
      Write `…/scratchpad/pr7-t10.txt` with the subject
      `refactor(phase1-pr7): the worker role stops reading relay keys`
      and a body naming `fetch_channel_stats`, `run_recording`'s metadata capture, the deleted
      module-level import, and the fact that the stored `stream_info` dict is unchanged because the
      payload's keys are `ChannelMetadataField`'s values. End it with the two attribution lines.
      Stage `core/tasks.py apps/channels/tasks.py core/tests/test_fetch_channel_stats.py`, then
      commit with `-F`.

---

### Task 11: Close issue #181's second half — `is_internal` on `AuthorizeResult`

**Files:**
- Modify: `apps/proxy/authorize.py` — `AuthorizeResult.is_internal`, set in `authorize_stream`
- Modify: `apps/proxy/authorize_views.py` — `result_from_headers` sets it too
- Modify: `apps/proxy/live_proxy/views.py` — `stream_ts` reads `decision.is_internal`
- Test: `apps/proxy/tests/test_authorize.py` and
  `apps/proxy/tests/test_redirect_transcode_flag.py` (append)

**Interfaces:** Produces `AuthorizeResult.is_internal: bool`. Removes `live_proxy/views.py`'s
direct `request_is_internal(...)` call.

**Why no new header.** `is_internal` joins `user` and `trusted`, which the dataclass docstring
already says "never cross the wire and exist only for the inline caller" — except that
`result_from_headers` can set this one too, because nginx forwards a client's
`X-Dispatcharr-Internal` unchanged on relay-bound locations (it is not one of the five names
`dispatcharr_api_params.conf` blanks). So both paths compute the same answer from the same header,
in one module, with no sixth `auth_request_set` line across nine nginx locations and no change to
the greybox spec's six-variable list.

- [ ] **Step 1: Write the failing tests.** Append to `apps/proxy/tests/test_authorize.py`:
      ```python
      class AuthorizeResultCarriesTheInternalFlagTests(TestCase):
          """Issue #181: the stream view was re-reading the raw header.

          The decision already resolved the internal principal; asking the same
          question twice, in a second module, is the duplication #181 objects
          to. The flag is inline-only, like `user` and `trusted` -- nginx
          forwards X-Dispatcharr-Internal unchanged on relay-bound locations,
          so result_from_headers answers it from the same header the hop did.
          """

          def test_an_internal_caller_is_flagged_on_the_inline_path(self):
              request = self._request(
                  HTTP_X_DISPATCHARR_INTERNAL=internal_principal_token()
              )
              decision = authorize_stream(request, SURFACE_LIVE, identifier=str(self.channel.uuid))
              self.assertIs(decision.is_internal, True)

          def test_an_ordinary_caller_is_not(self):
              request = self._request()
              decision = authorize_stream(request, SURFACE_LIVE, identifier=str(self.channel.uuid))
              self.assertIs(decision.is_internal, False)

          def test_a_forged_token_is_not(self):
              request = self._request(HTTP_X_DISPATCHARR_INTERNAL="0" * 64)
              decision = authorize_stream(request, SURFACE_LIVE, identifier=str(self.channel.uuid))
              self.assertIs(decision.is_internal, False)

          def test_the_nginx_path_reaches_the_same_answer(self):
              from apps.proxy.authorize_views import result_from_headers

              request = self._request(
                  HTTP_X_DISPATCHARR_INTERNAL=internal_principal_token(),
                  HTTP_X_RELAY_CHANNEL=str(self.channel.uuid),
              )
              self.assertIs(
                  result_from_headers(request, SURFACE_LIVE).is_internal, True
              )
      ```
      Reuse whatever request factory and `SURFACE_*` constants that file already has; read it
      before writing, and name the helper `self._request` only if it exists — otherwise follow the
      file's own convention.
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_authorize -v1`
      Expected: FAIL — `AuthorizeResult` has no `is_internal`.
- [ ] **Step 2: Add the field.** In `apps/proxy/authorize.py`:
      ```python
      @dataclass
      class AuthorizeResult:
          """What the hop tells the relay. The five string fields are the five
          X-Relay-* response headers, verbatim; `user`, `trusted` and
          `is_internal` never cross the wire and exist only for the caller.

          is_internal is set on both paths rather than carried in a sixth
          X-Relay-* header (issue #181): nginx forwards a client's
          X-Dispatcharr-Internal unchanged on relay-bound locations, so
          result_from_headers can answer it from the same header the hop
          read, and a sixth auth_request_set line across nine locations buys
          nothing.
          """

          surface: str
          channel_uuid: str = ""
          output_profile_id: str = ""
          client_id: str = ""
          user_id: str = ""
          relay_name: str = ""
          user: object = None
          trusted: bool = False
          is_internal: bool = False
      ```
      Set it wherever `authorize_stream` builds its `AuthorizeResult`, from the same
      `request_is_internal(http_request)` value `_resolve_principal` already computes — hoist that
      call to a local rather than calling it twice.
- [ ] **Step 3: Set it on the nginx path.** In `apps/proxy/authorize_views.py`'s
      `result_from_headers`, add to the returned `AuthorizeResult(...)`:
      ```python
              # Same header, same check, one module. nginx does not blank
              # X-Dispatcharr-Internal on a relay-bound location -- it is not
              # one of the five names dispatcharr_api_params.conf clears -- so
              # the DVR's token reaches the relay exactly as it reached the hop.
              is_internal=request_is_internal(request),
      ```
      and import `request_is_internal` from `apps.proxy.internal_auth` beside the other names that
      module already imports.
- [ ] **Step 4: Read the flag in the stream view.** In `apps/proxy/live_proxy/views.py`, replace:
      ```python
                      internal_principal = request_is_internal(
                          getattr(request, "_request", request)
                      )
      ```
      with:
      ```python
                      # The decision already resolved this; issue #181.
                      internal_principal = decision.is_internal
      ```
      using whatever name that function has for the `AuthorizeResult` in scope — read the
      surrounding lines rather than assuming `decision`.
      Run: `grep -n "request_is_internal" apps/proxy/live_proxy/views.py`
      Expected: no output. Remove the now-unused import from that file's header.
- [ ] **Step 5: Run the three suites that pin the redirect behaviour.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests apps.timeshift.tests -v1`
      Expected: OK. `apps/proxy/tests/test_redirect_transcode_flag.py` is the PR 5 pin that an
      internal principal on a Redirect-profile channel is served through the Proxy path rather
      than a 302; it must still pass unchanged, and if it does not, the name substituted in Step 4
      is wrong.
- [ ] **Step 6: Guard and commit.**
      Run: `python3 scripts/check_credential_logging.py apps/proxy/authorize.py apps/proxy/authorize_views.py apps/proxy/live_proxy/views.py`
      Expected: exit 0.
      Write `…/scratchpad/pr7-t11.txt`:
      ```
      refactor(phase1-pr7): AuthorizeResult carries is_internal (#181)

      The stream view re-read X-Dispatcharr-Internal to decide whether to
      refuse a redirect, duplicating a question the authorize decision had
      already answered. The flag joins user and trusted as an inline-only
      field: nginx forwards that header unchanged on relay-bound locations, so
      result_from_headers answers it the same way the hop did, and no sixth
      X-Relay-* header or auth_request_set line is needed.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `apps/proxy/authorize.py apps/proxy/authorize_views.py apps/proxy/live_proxy/views.py apps/proxy/tests/test_authorize.py`,
      then commit with `-F`.

---

### Task 12: Pin the nginx handling of `/proxy/relay/`

**Files:**
- Modify: `docker/nginx.conf` — the `^~ /proxy/relay/` block
- Modify: `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` — a fourth `@contract` test
  and one comment correction
- Modify: `e2e/COVERAGE.md` — one `P1` row

**Interfaces:** none in code. This task turns ruling 2 into an assertion.

**No allowlist entry is needed.** `nginx-stream-buffering.spec.ts` is already listed under the
`SUBPROCESS` capability in `e2e/tests/guards/allowlist.ts` (it shells out to
`docker exec … nginx -T`), and this task adds a test to that file rather than a new file. Do not
touch `allowlist.ts`.

- [ ] **Step 1: Give the location an explicit read timeout and say what it serves.** In
      `docker/nginx.conf`, replace the `^~ /proxy/relay/` block's comment and body:
      ```nginx
          # The relay's control API (Phase 1 PR 7): five routes Django calls so
          # no control-plane process reads a relay-owned Redis key.
          #
          # NOT `internal;`, deliberately. Django dials these as an ordinary
          # HTTP client -- from the worker role across the compose network and
          # from the api role through this very nginx -- and `internal;` serves
          # a location only for a subrequest or an X-Accel-Redirect, 404ing
          # every client request. The gate is the two internal HMAC headers,
          # checked by IsInternalRelay in Django (D9, D11): no principal, no
          # IsAdmin, no source-IP allowlist, because a source-IP allowlist does
          # not survive a compose network.
          #
          # Deliberately outside the authorize hop (spec amendment S8):
          # authorize_stream() would 404 a URI that names no channel. The
          # blanking include is still here, so a client-supplied X-Relay-*
          # header never reaches the relay on this path.
          #
          # No uwsgi_buffering off: these serve short JSON, not a stream.
          # uwsgi_read_timeout is explicit rather than nginx's 60s default
          # because one route has a real budget behind it --
          # POST .../advance waits on ChannelService.change_stream_url, whose
          # non-owner path polls for the owner's confirmation for up to
          # STREAM_SWITCH_CONFIRM_TIMEOUT = 15s. relay_client's own read
          # timeout for that call is 20s; 30s here leaves the client's timeout
          # as the one that fires.
          location ^~ /proxy/relay/ {
              include /etc/nginx/dispatcharr_api_params.conf;
              uwsgi_read_timeout 30s;
              uwsgi_pass relay_py;
          }
      ```
- [ ] **Step 2: Correct the stale comment in the greybox spec.** In
      `nginx-stream-buffering.spec.ts`, the `RELAY_BOUND_TARGETS` doc comment says `^~ /proxy/relay/`
      is "PR 7's still-unmounted control API". Replace that sentence:
      ```
       * Two locations are absent on purpose, for different reasons: `^~ /proxy/`
       * stays on the API — it is the API's own short IsAdmin control routes, never
       * `uwsgi_pass relay_py`. `^~ /proxy/relay/` *is* relay-bound
       * (`uwsgi_pass relay_py`) but carries no `uwsgi_buffering off`, correctly:
       * it is the relay control API Phase 1 PR 7 mounted, and it serves short
       * JSON rather than a stream. Its own properties are pinned by the fourth
       * test in this file.
      ```
- [ ] **Step 3: Add the fourth test,** after the "blanks the trust params" test:
      ```ts
      test(
        'the relay control API is routed to the relay and gated by no nginx-level authorizer',
        { tag: '@contract' },
        async () => {
          const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
          const blocks = parseLocationBlocks(stdout);
          const block = blocks.find((b) => b.target === '/proxy/relay/');
          expect(block, 'no ^~ /proxy/relay/ location found').toBeTruthy();

          // Relay-bound: these five routes exist so no control-plane process
          // reads a relay-owned Redis key, which only works if they reach the
          // relay. A literal upstream group, not $relay_upstream: no
          // subrequest runs here, so $relay_name is unset and a variable pass
          // nothing feeds is a thing a reader has to disprove.
          expect(
            block!.body.some((line) => /^\s*uwsgi_pass\s+relay_py\s*;/.test(line)),
            'the relay control API must reach the relay'
          ).toBe(true);

          // NOT internal;. Django dials these as an ordinary HTTP client --
          // from the worker container across the compose network, and from
          // the api container through this nginx -- and `internal;` would 404
          // every one of those calls.
          expect(
            block!.body.some((line) => /^\s*internal\s*;/.test(line)),
            'the relay control API must stay reachable by Django, which is an ordinary client here'
          ).toBe(false);

          // The token is the whole gate (D9): authorize_stream() would 404 a
          // URI that names no channel, so the hop must not sit in front of it.
          expect(
            block!.body.some((line) => /^\s*auth_request\s+\//.test(line)),
            'the relay control API must not run the authorize subrequest'
          ).toBe(false);

          // A client-supplied X-Relay-* header still never reaches the relay
          // on this path.
          expect(
            block!.body.some((line) => /dispatcharr_api_params\.conf\s*;/.test(line)),
            'the relay control API must still blank the trust params'
          ).toBe(true);

          // POST .../advance waits on the owner's confirmation for up to
          // STREAM_SWITCH_CONFIRM_TIMEOUT = 15s; relay_client allows 20s.
          // An explicit window above both keeps the client's timeout the one
          // that fires rather than nginx's 60s default.
          expect(
            block!.body.some((line) => /^\s*uwsgi_read_timeout\s+30s\s*;/.test(line)),
            'the relay control API needs a read timeout above the advance budget'
          ).toBe(true);
        }
      );
      ```
- [ ] **Step 4: Add the COVERAGE row.** Append to `e2e/COVERAGE.md`'s main table, beside the two
      existing `P1` rows:
      ```
      | Streaming | Relay control API: `^~ /proxy/relay/` reaches the relay (`uwsgi_pass relay_py`), is not `internal;` so Django can dial it as an ordinary client from the worker role and through the api role's own nginx, runs no `auth_request` because the internal token is the whole gate, still blanks the five `X-Relay-*` trust params, and carries a read timeout above the 15s the owner-confirmation poll can take | P1 | done |
      ```
- [ ] **Step 5: Typecheck and lint the config change.**
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/e2e && npx tsc --noEmit`
      Expected: clean.
      Run: `python -m metrics.build --validate-only`
      Expected: exit 0 — `e2e/COVERAGE.md`'s row counts feed three metrics
      (`coverage_rows_done`, `coverage_rows_known_bug`, `coverage_rows_todo`), so a malformed row
      fails here rather than on the dashboard.
- [ ] **Step 6: Commit.** Write `…/scratchpad/pr7-t12.txt` with the subject
      `feat(phase1-pr7): pin the nginx handling of the relay control API`
      and a body carrying ruling 2's reasoning — why `internal;` is impossible, why the hop stays
      off it, and where the 30-second read timeout comes from. End it with the two attribution
      lines. Stage
      `docker/nginx.conf e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts e2e/COVERAGE.md`,
      then commit with `-F`.

---

### Task 13: Full verification

**Files:** none edited unless a check fails. This task produces no commit unless a fix is needed;
a fix is committed with the task it belongs to, not here.

**Interfaces:** none. This is the evidence for every Done criterion above.

- [ ] **Step 1: All sixteen backend labels.** The routed set is five (Task 1, step 5), but a
      control-plane change reaches further than its own directory and the full set costs about
      thirty-five seconds:
      Run: `docker exec … dispatcharr-testrunner-pr7 … manage.py test --keepdb apps.accounts.tests apps.backups.tests apps.channels.tests apps.connect.tests apps.dashboard.tests apps.epg.tests apps.m3u.tests apps.output.tests apps.plugins.tests apps.proxy.live_proxy.tests apps.proxy.tests apps.proxy.vod_proxy.tests apps.timeshift.tests apps.vod.tests core.tests tests -v1`
      Expected: OK, 16/16. Report the count.
- [ ] **Step 2: The commit gate, as CI derives it.**
      Run: `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr7 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr7 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/.claude/hooks/pre-commit-tests.sh --git-hook`
      Expected: pass.
- [ ] **Step 3: The Done grep, verbatim.**
      Run, as one command:
      ```bash
      grep -rn "live:channel:\|channel_stream:\|stream_profile:" apps/channels/ apps/m3u/ core/ dispatcharr/ \
        | grep -v tests \
        | grep -v "self.stream_profile:\|not stream_profile:"
      ```
      Expected: **empty** (ruling 7).
- [ ] **Step 4: The relay writes nothing, still.**
      Run: `grep -rn "log_system_event(\|\.save(\|\.objects\.create(" apps/proxy/ | grep -v tests`
      Expected: no output.
- [ ] **Step 5: The D10 boundary.**
      Run: `grep -rn "relay_client" apps/proxy/live_proxy/ apps/proxy/vod_proxy/ apps/timeshift/ | grep -v "/tests/"`
      Expected: `apps/proxy/live_proxy/views.py` only, every import indented inside a function.
      Run: `grep -rn "from apps.proxy import relay_client" apps/proxy/live_proxy/views.py | grep -v "^\S*:[0-9]*:    "`
      Expected: no output — every occurrence is indented.
      Run: `grep -rn "control_plane" apps/proxy/relay_client.py apps/proxy/relay_views.py`
      Expected: no output — the two directions do not import each other.
- [ ] **Step 6: Ruling 11's dead branch really is unreachable from the relay.**
      Run: `grep -rn --include=\*.py "change_stream_url" apps/ | grep -v "/tests/"`
      Expected: the definition in `services/channel_service.py`, its one call in
      `apps/proxy/relay_views.py`, and comments. No caller passes `target_stream_id` without a
      `new_url`, so the function-local `from apps.proxy.next_source import resolve_source` inside
      it never executes. Report the line numbers in the task report; the branch is left in place
      because it is relay-internal code this phase does not rewrite.
- [ ] **Step 7: Architecture metrics.**
      Run: `PYTHONPATH=scripts/metrics python3 scripts/metrics/collect_architecture.py --repo-root .`
      Expected: `"proxy_orm_writes": 0` and `"models_module_level_live_proxy_imports": 2`. Record
      `reverse_imports_into_proxy` before and after in the task report: it moves, and Task 14's
      `CLAUDE.md` wording should not claim a direction the number contradicts.
      Run: `python -m metrics.build --validate-only`
      Expected: exit 0.
- [ ] **Step 8: Schema and credential guards over the whole diff.**
      Run: `docker exec … manage.py spectacular --file /dev/null 2>&1 | grep -i "relay\|/proxy/relay"`
      Expected: no output — the schema generates and no warning names a `/proxy/relay/` path or a
      `Relay*Serializer`. `--fail-on-warn` is deliberately not used: it is red on the baseline tree
      for pre-existing legacy views, so it would fail this PR for someone else's warnings.
      Run: `git diff --name-only origin/main...HEAD -- '*.py' | xargs python3 scripts/check_credential_logging.py`
      Expected: exit 0.
- [ ] **Step 9: Frontend, untouched and green.**
      Run: `git diff --name-only origin/main...HEAD -- frontend/`
      Expected: no output. **If any frontend file appears, stop and report** — the Done criterion
      is that `Stats.jsx`'s coverage is unchanged because the response shapes are.
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/frontend && npm ci && npm test`
      Expected: green.
- [ ] **Step 10: E2E typecheck and guards.**
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr7/e2e && npm ci && npx tsc --noEmit`
      Expected: clean.
      Run the `guards` project with the full variable set from § Test environment step 6.
      Expected: green — `capabilities.spec.ts` fails naming the offender if a file reached for a
      capability it did not declare, and `tags.spec.ts` fails if the new test carries no tag or
      two.
- [ ] **Step 11: Build this worktree's E2E stack and run four projects.** Build with
      `docker rmi dispatcharr-e2e-pr7:local` first, then `scripts/e2e_up.sh` with every variable
      from § Test environment step 6, then recreate the provider with
      `-e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-pr7:8080`. Run, each with the **full**
      variable set:
      `--project=streaming`, `--project=streaming-failover`, `--project=streaming-greybox`,
      `--project=lifecycle`.
      Expected: green. `streaming-greybox` carries Task 12's new assertion and
      `nginx-stream-buffering.spec.ts`'s three existing ones; `streaming` carries
      `stream-profiles.spec.ts`, which Task 3 edited; `streaming-failover` exercises the tune and
      failover path this PR put two HTTP hops on; `lifecycle` shells out to `scripts/e2e_up.sh`
      and is the reason every variable has to be exported (issue #187).
      **Never pass `--reset` or `--down`.**
- [ ] **Step 12: Both bash lifecycle scenarios.** `test_role_split` is the only test of the
      cross-container relay hop, and this PR is the first to send traffic across it in the
      Django→relay direction.
      Run: `docker/tests/test-puid-pgid.sh` (the whole suite, or at minimum `test_modular_mode`
      and `test_role_split` if the script supports selecting a scenario — read its usage first).
      Expected: the same pass/fail/skip counts `e2e/README.md` records, with `readonly_rootfs`
      still the one skip. Report the counts.
- [ ] **Step 13: Write the verification report.** State, per check: the command, the result, and
      the count where there is one. Anything that could not run — Docker down, a project that
      needs an image this machine cannot build — is reported as **not run**, not as passing. The
      work is then unverified, not verified.

---

### Task 14: Documentation, the ledger, and this plan

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`
- Modify: `metrics/curated/defects.yml`
- Create (commit): `docs/superpowers/plans/2026-09-06-phase1-pr7-control-api.md`

**Interfaces:** none in code.

- [ ] **Step 1: `CLAUDE.md` § Structural constraints — the boot-trap paragraph.** Replace the
      `apps/channels/models.py:6–7` bullet with the audit's actual outcome:
      ```
      - `apps/channels/models.py:6–7` imports `RedisKeys` and `ChannelMetadataField` from
        `apps.proxy.live_proxy` at **module level** — loaded by every migration and management
        command. It survives only because those are leaf modules: **one import added to
        `live_proxy/constants.py` and Django stops booting.** Hence 602 function-local imports.
        Phase 1 PR 7 audited whether either could go and the answer is no. `RedisKeys` could
        only go by relocating PR 6's two four-line key helpers to a Django-owned module: PR 6 moved
        `channel_stream:*` and `stream_profile:*` into that class, and this module is their owner
        and only writer, reaching them through it at twenty-six sites — so the import is now the
        legitimate accessor for keys this module owns, not an incidental leak. Doing that
        relocation would not remove the trap anyway, because `ChannelMetadataField` stays:
        `Channel.release_stream()` and `_release_stale_stream_assignment()` still read and `hdel`
        the relay's metadata hash on their fallback paths, the one relay-key access PR 7 left in
        the control plane (see § Known defects, and issue #190). PR 7 did drop the third name,
        `ChannelState`, with the reuse check that used it. Two module-level imports remain, and the
        trap with them.
      ```
- [ ] **Step 2: `CLAUDE.md` § Observing a channel — the two type bullets and the new surface.**
      Replace the `ffmpeg_speed` sentence and the `owner` sentence's neighbours:
      ```
      **Observing a channel.** `GET /proxy/ts/status/<uuid>` (admin-only) is the only status
      surface, and since Phase 1 PR 7 it is a thin wrapper over `GET /proxy/relay/channels/<uuid>`
      on the relay — the control plane no longer reads a relay Redis key to answer it. Two fields
      still mislead and one no longer does. `owner` falls back to the literal string `'unknown'`,
      never null — truthiness checks pass when nobody owns the channel. `total_bytes`,
      `avg_bitrate_kbps`, `stream_id`, `stream_name` can be **absent entirely** (not null), which
      the DRF serializer preserves deliberately. `ffmpeg_speed` is a **float on both endpoints**
      and `state` is **`null` rather than `'unknown'`** when the channel has never recorded one:
      PR 7 put both payloads behind one serializer, which is not a thing that can carry the
      disagreement they used to have. `source_fps` still disagrees — a string on the per-channel
      endpoint, a float on the collection one — and is carried, not fixed.
      ```
      Leave the `relay_event` and `channel_stats` sentences that follow it exactly as they are.
- [ ] **Step 3: `CLAUDE.md` § Known defects — preemption, and the new straggler.** Replace the
      preemption bullet:
      ```
      - Channel preemption is **gone, and was never alive**: `_pick_channel_to_preempt()` was
        deleted in Phase 1 PR 7 along with the commented-out `return` beside its call site. It
        could never have returned a channel — `apps/channels/models.py` imports no `time`, so its
        cooldown check raised `NameError`; the profile index key it prefers is written nowhere in
        the tree; and its scan fallback `int()`s a segment of `live:channel:{uuid}:metadata`, which
        is a UUID. The feature gap is unchanged: channel preemption stays unimplemented.
      ```
      and add one bullet beside the `channel_stream:*`/`stream_profile:*` one:
      ```
      - **Two relay-key accesses survive in the control plane, both on `Channel.release_stream()`'s
        fallback path** ([#190](https://github.com/D10Scot/Dispatcharr/issues/190)).
        `_release_stale_stream_assignment()` reads `ChannelMetadataField.M3U_PROFILE` out of
        `live:channel:<uuid>:metadata`, and `release_stream()` both reads it and `hdel`s two fields
        from it — a control-plane *write* to a relay key, which the Phase 1 spec's "every other
        relay key was already single-writer" does not anticipate. Both are fallbacks, used only
        when the Django-owned `channel_stream:`/`stream_profile:` keys are already gone. **The read
        is easy and the write is not**: PR 6's `ReleaseRequestSerializer` already carries
        `stream_id` and `m3u_profile_id`, so the relay passes both and the read could go with no
        contract change at all — but the `hdel` clears the relay's own hash so a duplicate release
        cannot `DECR` the provider counter twice, and its natural home is the relay's release call
        sites, a relay-internal edit D10 keeps out of Phase 1. Everything else — the reuse check,
        the DVR client scans, `fetch_channel_stats`, the recording metadata capture and the live
        branch of `get_user_active_connections` — goes through `apps/proxy/relay_client.py`.
      ```
- [ ] **Step 4: `CLAUDE.md` § Architecture — the control API and the nginx location.** In the
      "Two uWSGI processes" paragraph, extend the relay's route list to name `/proxy/relay/…`, and
      add to the `uwsgi_buffering off` bullet that `^~ /proxy/relay/` is relay-bound but carries no
      `uwsgi_buffering off` on purpose, because it serves short JSON — pinned by the fourth test in
      `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`. In the § Auth paragraph, add:
      ```
      Since Phase 1 PR 7 there is a second internal surface, the mirror image of `/api/relay/…`:
      `/proxy/relay/…` on the relay, five routes Django calls through `apps/proxy/relay_client.py`
      so no control-plane process reads a relay-owned Redis key. Both surfaces take the same two
      headers — the static `X-Dispatcharr-Internal` and the per-request `X-Dispatcharr-Internal-Request`,
      which binds method, full path (query string included), body and a 120-second window — and
      neither is `IsAdmin`. `^~ /proxy/relay/` is deliberately **not** `internal;` in nginx: Django
      dials it as an ordinary client, from the `worker` role across the compose network and from
      the `api` role through its own nginx.
      ```
- [ ] **Step 5: `CLAUDE.md` § Commands — extend PR 6's dev note.** Append to the bullet that
      already explains `DISPATCHARR_ENV=dev` and `runserver 5656`:
      ```
      Since PR 7 the dev process also calls *itself* in the other direction: `Channel.get_stream()`
      asks the relay whether a channel is still running, and in `dev` that call goes to
      `http://127.0.0.1:5656` too. What answers depends on how dev was started. Under a bare
      `manage.py runserver 5656` one process serves everything, so a re-tune is three levels deep —
      request, `next-source`, then the reuse check — and it works only because `runserver` is
      threaded by default; **`--nothreading` makes the outer request wait forever on a nested one
      it will never serve, so do not pass it.** Inside Docker, `DISPATCHARR_ENV=dev` selects the
      `all-dev` rung, which starts **both** `api-uwsgi` and `relay-uwsgi` and no nginx, so `:5656`
      is the API uWSGI and `/proxy/relay/…` is served by the API process rather than the relay.
      Status reads still work (one Redis) and stops and `advance` still work (`ChannelService`
      reaches the owner over `live:events:` pub/sub), but `reset_tried` is a silent no-op there:
      the API process holds no `StreamManager` to clear.
      ```
- [ ] **Step 6: The spec's Done log and Amendment S11.** In
      `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`, fill the Done log row:
      ```
      | Control API | #<this PR's number> | — |
      ```
      and add, after Amendment S10, **this text verbatim** — it is the condensed form of this
      plan's § Design rulings and needs no re-derivation:
      ```markdown
      **Amendment S11 (PR 7 control API).** The tree required twenty decisions this section did not
      make, recorded here rather than re-derived by PR 8 or Phase 2:

      1. **`get_relay_control_base_url()`'s modular branch reads `DISPATCHARR_WEB_HOST`, not
         `DISPATCHARR_RELAY_HOST`.** D9's text names the latter, but `docker/uwsgi.relay.ini` gives
         the relay one listener — `socket = 0.0.0.0:$(DISPATCHARR_RELAY_PORT)`, the uwsgi protocol,
         which `requests` cannot dial — and D14 gives the `relay` role no nginx, so nothing answers
         HTTP in that container at all. D5 already stated the resolution ("D9 routes Django's
         control calls through nginx as well"). Both internal directions therefore resolve to the
         **api role's** nginx, which routes `^~ /proxy/relay/` to the `relay_py` upstream, and
         differ only in their override variable: `DISPATCHARR_RELAY_BASE_URL` for Django→relay,
         `DISPATCHARR_INTERNAL_API_BASE_URL` for relay→Django. `DISPATCHARR_RELAY_HOST` keeps its
         one job, the `RELAY_UPSTREAM` `sed`.
      2. **`location ^~ /proxy/relay/` must not be `internal;`.** Django dials it as an ordinary
         HTTP client — from the `worker` role across the compose network and from the `api` role
         through its own nginx — and `internal;` serves a location only for a subrequest or an
         `X-Accel-Redirect`. It keeps the blanking include and `uwsgi_pass relay_py;`, gains an
         explicit `uwsgi_read_timeout 30s;`, stays outside the authorize hop (S8), and is pinned by
         a fourth test in `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`.
      3. **`GET /proxy/relay/channels` takes `?clients=all`.** `get_basic_channel_info` caps its
         client list at ten, which is right for the stats payload and wrong for
         `get_user_active_connections`, whose job is counting a user's connections against
         `stream_limit`. `build_live_channel_stats_data` and `get_basic_channel_info` gain a
         `client_limit` keyword defaulting to 10; `/proxy/stats/` and `/proxy/ts/status` keep
         today's payload byte for byte.
      4. **`ffmpeg_speed` and `state` are normalised on the detailed side, invisibly to the UI.**
         Nothing in `frontend/src/` reads `/proxy/ts/status/<id>` — `API.getChannelStats` takes a
         uuid and ignores it — so only `e2e/fixtures/types.ts` and
         `e2e/tests/streaming/stream-profiles.spec.ts` needed updating. `owner`'s identical
         `'unknown'` default and `source_fps`' identical string-vs-float split are carried, not
         fixed: this section names two fields.
      5. **The detailed payload gains `width`, `height` and `video_bitrate` as raw strings**,
         because `run_recording`'s metadata capture moves onto it (ruling 12 below) and reads
         eleven fields of which the builder emitted eight. Raw strings like their siblings, so the
         DVR keeps its own casting and `Recording.custom_properties["stream_info"]` is unchanged.
      6. **`core/utils.py`'s event enrichment keeps its direct Redis read.** This section says it
         should call `relay_client`, but PR 6 made `channel_stream:*`/`stream_profile:*`
         **Django-owned** keys that the relay merely reads; asking the relay for their value would
         invert that ownership. The bullet predates PR 6. Neither literal appears in
         `core/utils.py`, so the Done grep is unaffected.
      7. **The Done grep grows an exclusion pipe.** It also matches two `StreamProfile`
         model-attribute accesses in `apps/channels/models.py` (`if self.stream_profile:` and
         `if not stream_profile:`) that will never go away, so "returns nothing" is unreachable as
         written. The form used from PR 7 on is
         `… | grep -v tests | grep -v "self.stream_profile:\|not stream_profile:"` → empty. Every
         genuine `live:channel:` literal in that directory set lived inside
         `_pick_channel_to_preempt`, which PR 7 deletes.
      8. **`_pick_channel_to_preempt` never returned a channel, three ways over.**
         `apps/channels/models.py` imports no `time`, so its cooldown check raised `NameError`; the
         `live:profile:{id}:channels` index it prefers is written nowhere in the tree; and its scan
         fallback `int()`s a segment of `live:channel:{uuid}:metadata`, which is a UUID. (Its
         commented-out `return` was also a 3-tuple where `get_stream()` is a 4-tuple.) Deleted with
         the commented-out `return`. **Channel preemption stays unimplemented** — unchanged, not
         decided here.
      9. **The `models.py:6-7` audit's answer is "no", contradicting this section's stated
         recommendation.** `RedisKeys` could go only by relocating PR 6's two four-line helpers to
         a Django-owned module, and doing so would not remove the trap while `ChannelMetadataField`
         remains (ruling 10). PR 6 made this module the sole writer of `channel_stream:*` and
         `stream_profile:*` through that class, at twenty-six sites, so the import is now the
         legitimate accessor for keys it owns. `ChannelState` did go, with the reuse check.
         `models_module_level_live_proxy_imports` stays at **2** either way.
      10. **Two relay-key accesses survive in the control plane, tracked as issue #190.**
          `_release_stale_stream_assignment()` reads `ChannelMetadataField.M3U_PROFILE` from the
          relay's metadata hash and `Channel.release_stream()` both reads it and `hdel`s two fields
          — a control-plane *write*, which § Requirements' "every other relay key was already
          single-writer" does not anticipate. The **read** needs no contract change: PR 6's
          `ReleaseRequestSerializer` already carries `stream_id` and `m3u_profile_id`. The **`hdel`**
          is the obstacle — it stops a duplicate release `DECR`ing the provider counter twice, and
          its natural home is the relay's own release call sites, which D10 keeps out of Phase 1.
      11. **`POST /proxy/relay/channels/<id>/advance` carries a fully-resolved source.** Django
          resolves the candidate with `next_source.resolve_source` in the API process, where the
          ORM is, and always sends `url`, so `ChannelService.change_stream_url`'s
          `if not new_url and target_stream_id:` branch — the one holding a function-local
          `resolve_source` import — is never entered from the relay. That branch's only two callers
          are the views PR 7 rewrote, so it is unreachable in practice; left in place, because it
          is relay-internal code this phase does not rewrite.
      12. **Three worker-role and API-role reads move that this section does not name**:
          `next_stream`'s `RedisKeys.channel_metadata` read (that view runs in the API process after
          PR 4's routing, so it was the control plane reading a relay key, invisible to the Done
          grep's directory list), and `run_recording`'s metadata capture in
          `apps/channels/tasks.py` (the `dvr` Celery worker). § Requirements' "PR 7 removes the
          control plane's *reads* too" is what requires both.
      13. **The tune-path reads nest one HTTP hop inside another.** `Channel.get_stream()` runs
          inside `next_source.resolve_source()`, which the relay reached with a 5 s read timeout and
          one retry, so `relay_client`'s tune budget is `(1, 2)` with **no retry** and the read is
          narrowed by `?fields=state` (ruling 20). An unreachable relay yields
          `ChannelSnapshot(present=False, …)`, which sends `_stream_assignment_is_reusable` to its
          Django-owned `stream_profile:<id>` fallback and **reuses** the assignment — no release, no
          re-reservation, so the provider counter cannot move. Not a deadlock: the relay runs
          `gevent = 1600` and the inner handler reads Redis only. It fires on a re-tune, not on
          every tune.
      14. **`dev` has two shapes.** Under a bare `manage.py runserver 5656` one process serves
          everything, so a re-tune is three self-calls deep and works only because `runserver` is
          threaded by default — `--nothreading` hangs it. Inside Docker the `all-dev` rung starts
          **both** `api-uwsgi` and `relay-uwsgi` and no nginx, so `:5656` is the API uWSGI and
          `/proxy/relay/…` is served by the API process: status reads and stops still work (one
          Redis, and `ChannelService` reaches the owner over `live:events:`), but `reset_tried` is a
          silent no-op there.
      15. **Issue #181's second ask is met without a sixth trust header.** `AuthorizeResult` gains
          `is_internal` as an inline-only field beside `user` and `trusted`; `result_from_headers`
          sets it the same way, because nginx forwards `X-Dispatcharr-Internal` unchanged on
          relay-bound locations (it is not one of the five names the blanking include clears). A
          sixth `X-Relay-*` header would mean a seventh `auth_request_set` line in nine locations
          for a computation that cannot diverge.
      16. **The five routes are tagged `internal` in the schema**, matching PR 6's three, so
          `/api/schema/` distinguishes them from endpoints a player or the SPA may call.
      17. **The bound internal token signs `request.get_full_path()`, not `request.path`.** PR 6's
          three routes take no query parameter, so the two strings were always equal there; ruling 3
          adds one, and an unsigned query string is a value a replay inside the ±120 s window could
          flip. One line on each side, backward compatible with every call PR 6 shipped.
      18. **`advance` carries `reset_tried`, restoring behaviour PR 4 silently broke.**
          `/proxy/ts/change_stream/` has always cleared the running `StreamManager`'s
          `tried_stream_ids`; PR 4's routing put that view on the `api` role, where
          `stream_managers` is always empty, so the reset had been dead since. It moves to the relay
          view. A flag, not unconditional: `next_stream` has never reset it and must not start.
      19. **`Channel._channel_proxy_is_active` is deleted rather than rewritten.** Its predicate is
          exactly what `relay_client.channel_snapshot()` answers and its only caller was
          `_stream_assignment_is_reusable`; a wrapper would cost a second round trip or leave a
          method with no caller, and would keep `ChannelState` imported into `models.py`.
      20. **The tune-path read asks `?fields=state`, and has its own serializer.** Answering it
          with `get_detailed_channel_info` would sample buffer chunk keys, `SCAN` on a miss, walk
          every client and run two ORM name fallbacks under a two-second budget. `channel_view`
          answers the narrow form with one `EXISTS` and one `HGET`, rendered through a two-field
          `RelayChannelStateSerializer` — **not** a partial render of the detail serializer, whose
          `url`, `stream_profile` and `owner` are `required=False, allow_null=True` and would
          therefore render as nulls rather than be skipped: DRF's `Field.get_attribute` checks
          `default`, then `allow_null`, and only then `required` (3.17.1). The full payloads are
          unaffected, since both info builders assign all four unconditionally.
      ```
      Two notes for the executor: this text is the **corrected** rulings, including ruling 13's
      reuse-not-re-reserve behaviour and ruling 10's `hdel`-is-the-obstacle reason. Do not
      re-condense from an earlier draft. Convert `\|` back to a literal `|` inside the ruling 7 code
      span if the markdown renders it oddly; the spec file has no code-fence nesting constraint
      here.
- [ ] **Step 7: Amend the Requirements row that ruling 10 contradicts.** In § Requirements the
      relay meets or carries, change the "*(new)* The relay's Redis keys have exactly one writer,
      and no control-plane code reads them" row's status from **Met** to **Met, with one named
      exception**, and add to its cell:
      ```
      Amendment S11 ruling 10: `Channel.release_stream()` and `_release_stale_stream_assignment()`
      still read — and `hdel` — the relay's metadata hash on their fallback paths, so "every other
      relay key was already single-writer" is not quite true of the metadata hash. The read needs
      no contract change (PR 6's release body already carries `stream_id` and `m3u_profile_id`);
      the `hdel` belongs on the relay's own release call sites, which D10 keeps out of this phase.
      Named and tracked as issue #190 rather than fixed here, since PR 7's section names three
      sites and not these.
      ```
- [ ] **Step 8: The defect ledger.** In `metrics/curated/defects.yml`, move the
      `preemption-dead-code` row to `status: fixed` with `fixed_in: <this PR's number>` and
      `status_changed: 2026-09-06`. **If the PR is not yet open**, leave the row untouched and put
      a line in the PR body instead — `ledger: preemption-dead-code → fixed` — for whoever merges,
      which is what `docs/agents/metrics.md` prescribes when no number exists yet. Do not invent a
      status; the four are `open`, `pinned`, `carried`, `fixed`, and status moves forward only.
      No `milestones.yml` row: `docs/agents/metrics.md` reserves that for the *final* tick of a
      spec's Done log, and PR 8 remains.
      Run: `python -m metrics.build --validate-only`
      Expected: exit 0.
      Run: `scripts/run_metrics_tests.sh`
      Expected: green — the metrics edit hook runs both, and a malformed ledger row fails here.
- [ ] **Step 9: Answer the two PR 6 review threads, in comments only.** Kimi's PR 6 review left two
      `[question]` threads that PR 7 answers where the reader will be standing. **No behaviour
      change, no wire change, no test change** — if either edit changes anything but a comment or a
      docstring, it is wrong.

      **(a) The wire `Source` carries no `stream_name`, deliberately.**
      `apps/proxy/next_source.py`'s `_source_from_info` builds the seven-field contract
      (`stream_id`, `url`, `user_agent`, `transcode`, `stream_profile`, `m3u_profile_id`,
      `slot_reserved`) and drops the `stream_name` that `get_stream_info_for_switch` had in hand.
      So `stream_info.get("stream_name")` in `change_stream` (near the `resolve_source` call, after
      Task 6's rewrite) and in `next_stream` (the `stream_name=` argument to `relay_client.advance`)
      is **always `None`**, in-process and over the wire alike. Add one comment at each site:
      ```python
              # Always None: the Source contract (S10 point 3, apps/proxy/
              # next_source.py's _source_from_info) carries seven fields and
              # stream_name is not one of them. The name is resolved by primary
              # key on the relay side instead -- ChannelService.
              # _update_channel_metadata and initialize_channel both fall back
              # to Stream.objects.filter(id=stream_id) when the caller passes
              # none, and the spec's ORM-reads table keeps exactly those two
              # lookups in the relay. Passing the key through and letting the
              # relay resolve it is the intended path, not an omission.
      ```
      Keep the `stream_name=` argument itself: dropping it would change
      `ChannelService.change_stream_url`'s call signature at two sites for no gain, and the
      argument is what a future contract widening would fill.

      **(b) `resolve_source`'s docstring says what `slot_reserved` means and why the double call is
      fine.** In `apps/proxy/next_source.py`, add one sentence to `resolve_source`'s docstring,
      immediately after the `Returns {...}` paragraph's "Only \"source\" ever reserves or moves a
      slot" sentence:
      ```
          May reserve a profile slot for the returned source (`slot_reserved`);
          the double call from `change_stream` -> `update_url` is the pre-move
          behaviour, idempotent on both halves.
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests -v1`
      Expected: OK, and `git diff` for both files shows comment and docstring lines only.
- [ ] **Step 10: Commit the docs and this plan.**
      Write `…/scratchpad/pr7-t14.txt`:
      ```
      docs(phase1-pr7): CLAUDE.md corrections, spec amendment S11, the plan

      The models.py boot-trap audit's answer is no, and for two separate
      reasons: RedisKeys is now the legitimate accessor for the two keys PR 6
      made this module the sole writer of, and ChannelMetadataField is still
      used by release_stream()'s fallback path -- the one relay-key access PR 7
      leaves in the control plane, named rather than fixed.

      Channel preemption is recorded as deleted rather than dead, with the
      three reasons it could never have returned a channel. The feature gap is
      unchanged.

      Amendment S11 carries every ruling this PR made, including that D9's
      DISPATCHARR_RELAY_HOST names a container with no HTTP listener and no
      nginx, so both internal directions resolve to the api role's.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Add one paragraph to that message for Step 9:
      ```
      Two PR 6 review threads answered in comments: the wire Source carries no
      stream_name on purpose (the relay resolves it by primary key), and
      resolve_source's docstring now says what slot_reserved means and why the
      change_stream -> update_url double call is idempotent.
      ```
      Stage `CLAUDE.md docs/superpowers/specs/2026-09-04-phase1-process-split-design.md metrics/curated/defects.yml docs/superpowers/plans/2026-09-06-phase1-pr7-control-api.md apps/proxy/next_source.py apps/proxy/live_proxy/views.py`,
      then commit with `-F`.
- [ ] **Step 11: Open the PR.** Title:
      `Phase 1 PR 7: status and control API — the relay's Redis keys become private`.
      The body must carry, in this order: what moved and why (one paragraph); the five new routes
      and their gate; the list of control-plane sites that stopped reading a relay key; the one
      that did not, with ruling 10's reason (the read is free — PR 6's release body already carries
      both ids — and the `hdel` is the obstacle) and its tracking issue **`#190`**, which the body
      must name so the deferral is followable; the two new HTTP statuses on the admin surfaces; the
      `?clients=all` parameter and why the bound token now signs the query string; the `reset_tried`
      behaviour PR 4 had silently broken; **`Closes #181`**, with one sentence saying that the
      issue's first ask was met by PR 6's bound token plus this PR's `IsInternalRelay` on all five
      routes and its second by `AuthorizeResult.is_internal`; one line saying the two PR 6
      `[question]` review threads are answered in comments only (Step 9), naming the two files; the
      ledger line if Step 8 deferred it; and the verification report from Task 13. Then the two footer lines the session requires.
      **Do not** claim `Lifecycle result` or `E2E result` green from a local run — say what was run
      locally and let CI say the rest.

---

