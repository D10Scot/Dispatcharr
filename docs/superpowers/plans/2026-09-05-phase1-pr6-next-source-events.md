# Phase 1 PR 6 — Next-source and Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the relay ask Django for its next stream instead of picking one itself, and post its
transitions as events instead of writing rows — taking `apps/proxy/` to zero ORM writes, giving
`channel_stream:*`/`stream_profile:*` a single writer, and pushing `channel_failover`,
`stream_switch` and `client_disconnect` to the UI over the WebSocket for the first time.

**Architecture:** Three internal routes under `/api/relay/…` (`next-source`, `release`, `events`),
served by the API process behind an `IsInternalRelay` permission class that checks the static
`X-Dispatcharr-Internal` HMAC **and** a per-request HMAC binding method, path, body and a
120-second window. `apps/proxy/next_source.py` holds the source-resolution logic lifted out of
`apps/proxy/live_proxy/url_utils.py` — it is the only place `Channel.get_stream()`,
`release_stream()` and `update_stream_profile()` are reached from now on. `apps/proxy/control_plane.py`
is the relay's side: a `requests` client with `timeout=(2, 5)`, one retry, and a degraded fallback
to a resolved candidate list cached in Redis at channel start. `core/relay_events.py` turns a posted
event batch into `log_system_event()` calls and the one `Stream.save()` the relay used to perform,
and lives outside `apps/proxy/` on purpose so the ORM-write metric and the spec's Done grep both
read zero.

**Tech Stack:** Django 6 + DRF (`apps/proxy/`, `apps/connect/`, `core/`), `requests` under gevent,
Redis (`RedisKeys`), Django Channels (`dispatcharr/consumers.py`), React 19 + Zustand + vitest
(`frontend/`), Playwright + TypeScript (`e2e/`).

**Spec:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` § The eight pull
requests › PR 6 — `migration/phase1-next-source-events`.

**Branch:** `migration/phase1-next-source` (worktree `.worktrees/phase1-pr6`), off `main`.

**Two naming facts the executor must not "fix".** The spec's PR 6 heading names the branch
`migration/phase1-next-source-events`; the branch that exists, and the one this plan targets, is
`migration/phase1-next-source`. Both match `migration/**`, which is the only property the CI gate
cares about (`lifecycle-tests.yml:119-124`). Do not rename the branch. The plan file keeps the
spec's slug so it sorts beside its siblings.

## Branch base

This branch was cut from PR 5's branch, so PR 5's work is already present in this worktree as
ordinary file content: `apps/proxy/internal_auth.py` (two HMAC tokens), `apps/proxy/authorize.py`
(`authorize_stream`, `AuthorizeResult`, `resolve_output_profile`, `mint_client_id`),
`apps/proxy/authorize_views.py` (`authorize_view`, `resolve_authorization`, `result_from_headers`),
the seven stream views authorizing through the hop, the DVR internal principal and the no-redirect
override, `docker/nginx.conf` with `auth_request` on the nine relay-bound locations,
`docker/dispatcharr_api_params.conf`, `^~ /proxy/relay/`, and the E2E authorize matrix.

**PR 6 executes only after PR 5 (#176) has merged to `main`.** Task 1 is the gate: reset this
branch onto `origin/main` before anything else. PR 5 arrives on `main` **squashed**, so:

- **This plan cites no PR 5 commit hash anywhere, and neither may the executor.** After a squash
  merge the hashes on this branch do not exist on `main`; `git merge-base --is-ancestor` answers
  "no" for a PR 5 that has demonstrably merged. Every check in Task 1 is a check on **file content**.
- **Every file:line below was verified against this worktree before the reset.** Line numbers
  drift; the tree wins. Task 1 re-runs the greps that matter and says what to do with each answer.

## Global Constraints

- **The gate on `/api/relay/…` is the internal token, never a principal.** `IsInternalRelay` calls
  `request_is_internal()` (`apps/proxy/internal_auth.py`) and the new bound-request check. It must
  not accept a DRF authenticator, a session user, `IsAdmin`, or `_drf_user`/`_session_user` from
  `apps/proxy/authorize.py`. `authentication_classes([])` on every one of the three views.
- **The internal token is bound in this PR, not deferred to PR 7** (spec § PR 6's follow-up bullet
  requires one or the other; issue #181 asks for it). Static `X-Dispatcharr-Internal` =
  `HMAC(SECRET_KEY, "internal-principal")` still says "part of this deployment" and still gates the
  DVR's stream fetch unchanged. A second header, `X-Dispatcharr-Internal-Request`, adds scope and
  expiry to the three new routes: `v1.<unix_seconds>.<hexdigest>` over
  `method\npath\ntimestamp\nsha256hex(body)` under the context `b"internal-request"`, accepted
  inside ±120 s. Both headers are required on `/api/relay/…`; a leaked static token alone no longer
  opens the control API. PR 7 inherits the helper for `/proxy/relay/…`.
- **The DVR keeps the static token only.** `_dvr_build_ffmpeg_cmd` sends one `-headers` line that
  ffmpeg re-sends on every reconnect for the life of a recording; a 120-second window would 403 a
  reconnect mid-recording. Do not add the bound header to the DVR path.
- Contract, exactly as spec § Architecture › "2. Next-source / release / events (PR 6)" states it:
  `POST /api/relay/channels/<identifier>/next-source` body `{exclude_stream_ids, reason}` →
  `{stream_id, url, user_agent, stream_profile: {id, command, args}, m3u_profile_id, transcode}`;
  `POST /api/relay/channels/<identifier>/release`; `POST /api/relay/events` body a list of
  `{type, channel_id, client_id?, stream_id?, details}`.
- Routes are mounted per D12: `apps/proxy/api_urls.py`, included from `apps/api/urls.py` as
  `path('relay/', include(('apps.proxy.api_urls', 'relay'), namespace='relay'))`.
- DRF serializers for every request and response body — never a raw dict — and every route present
  in the drf-spectacular schema, asserted by a test in the same shape as
  `apps/proxy/tests/test_authorize_view.py:134-138`.
- **`get_control_plane_base_url()` (D9)**: `DISPATCHARR_INTERNAL_API_BASE_URL` → modular
  `http://{DISPATCHARR_WEB_HOST:-web}:{DISPATCHARR_PORT:-9191}` → dev `http://127.0.0.1:5656` → AIO
  `http://127.0.0.1:{DISPATCHARR_PORT:-9191}`. Same four-branch shape as
  `get_dvr_stream_base_url()` (`apps/channels/tasks.py:1359-1395`), which is the formula D9 names.
- **HTTP client and timeouts:** `requests`, `timeout=(2, 5)` (connect 2 s, read 5 s), **one** retry
  on `requests.RequestException` and on 5xx, no retry on 4xx. `requests` is gevent-safe here for
  the same reason `url_utils.validate_stream_url` already uses it: `gevent-early-monkey-patch` is
  on, so the socket read yields the hub rather than blocking it. No `urllib3.Retry`, no `Session`
  cache — one call per request keeps the failure mode legible.
- **Fire-and-forget for events only.** `emit_event()` posts on a spawned greenlet, mirroring
  `core/utils.py:_dispatch_system_event_integrations` (`_should_use_sync_websocket_send()` →
  synchronous, `_is_gevent_monkey_patched()` → `gevent.spawn`, else synchronous), so the byte path
  never waits on Django and tests are deterministic. `next_source()` and `release_source()` are
  synchronous: their answers are load-bearing.
- **No channel state in Python memory.** The degraded fallback's candidate list lives in Redis at
  `RedisKeys.channel_source_cache(channel_id)` with `ex=REDIS_TTL_DEFAULT` (3600, `constants.py:8`),
  never on `self`.
- **Nothing new may be imported into `apps/proxy/live_proxy/constants.py` or `redis_keys.py`.**
  `apps/channels/models.py:6-7` imports both at module level; one import there stops Django booting.
  New `RedisKeys` methods are pure f-strings. Function-local imports elsewhere are the house habit
  (602 of them) and are the tool for any relay module reaching `apps.proxy.control_plane`.
- **No ORM write may land in `apps/proxy/`.** `scripts/metrics/collect_architecture.py:125-155`
  counts `.save()`, `.objects.<write>()` and queryset-chain writes across **every** non-test file
  under `apps/proxy/`, and `proxy_orm_writes` is a phase-1 headline metric with target 0
  (`metrics/curated/catalogue.yml:39`). The event batch's `log_system_event()` calls and the
  `Stream.save()` therefore live in `core/relay_events.py`, not in `apps/proxy/api_views.py`.
- **The relay's `channel_stream:*`/`stream_profile:*` writes are deleted, all of them.** After this
  PR the only writers are `Channel.get_stream()`, `Channel.release_stream()`,
  `Channel.update_stream_profile()` and `Channel._release_stale_stream_assignment()`, all in
  `apps/channels/models.py`, all reached only from `apps/proxy/next_source.py`. Relay-side *reads*
  of those two keys stay (they are Django-owned keys, not relay state).
- `channel_buffering` joins `apps/connect/models.py`'s `SUPPORTED_EVENTS`, and because
  `EventSubscription.event`'s `choices` is `list(SUPPORTED_EVENTS.items())`, that **is** a model
  change: it ships with `apps/connect/migrations/0004_alter_eventsubscription_event.py`. The app
  label is `dispatcharr_connect`, not `connect`.
- `stream_stats` is **not** added to `SUPPORTED_EVENTS` and **must not** create a `SystemEvent` row.
- **`MAX_STREAM_SWITCHES` still does not bound buffering-triggered switches.** Carried, not fixed
  (`CLAUDE.md` § Known defects). No task may quietly add that bound, and none may remove the one
  that exists.
- **Redaction:** any log line naming a URL or a header goes through `redact_url`/`redact_headers`
  (`dispatcharr/utils.py`) or `scripts/check_credential_logging.py` blocks the edit and the commit.
  `current_url` travels in a request **body**, never in a URL or a log line.
- **A channel UUID is a secret.** The `relay_event` WebSocket payload is a whitelist —
  `event`, `channel_id`, `channel_name`, `client_id`, `stream_id`, `reason`, `timestamp` — never
  the raw `details` dict, which carries `new_url` at `input/manager.py:1497`. `relay_event` joins
  `ADMIN_ONLY_UPDATE_TYPES` in `dispatcharr/consumers.py:12-18` for the same reason
  `channel_stats` is there.
- `os.posix_spawn` stays; no relay internals are rewritten; `apps/proxy/hls_proxy/` stays dead.
- **`git add` and `git commit` run in separate Bash calls**, and the commit message is written with
  the Write tool and passed as `-F <msgfile>` — the pre-commit hook blocks any single call
  containing both verbs, and trips on a heredoc that merely contains them.
- Supply-chain pinning applies to any new `uses:` (40-char SHA + version comment) or `FROM` /
  `COPY --from=` (digest). **This PR adds neither** — it touches no workflow and no Dockerfile.
- **CI label routing:** this PR edits `apps/api/urls.py`, aliased to `__all__`
  (`dispatcharr/test_discovery.py:38`), and `dispatcharr/consumers.py`, which is under the
  `dispatcharr/` shared prefix (`:10-18`). Either alone means `backend-tests.yml` runs **all 16
  labels**. The branch is `migration/**`, so `lifecycle-tests.yml` and `e2e-tests.yml` run in full
  mode.
- **`metrics/curated/` is not touched.** This PR closes no ledger issue, adds no `test.fail()` pin,
  merges no goal, and is not the *final* tick of the spec's Done log (PR 7 and PR 8 remain), which
  is the only tick `docs/agents/metrics.md:76` turns into a `milestones.yml` row.

## Design rulings

Each of these settles something the spec leaves open or states in a way the tree contradicts. They
are binding on the executor; a reviewer should check the plan against them, not re-derive them.

1. **The event-batch writes live in `core/relay_events.py`, not `apps/proxy/api_views.py`.** D12
   puts the routes inside `apps/proxy/`, and the spec's Done grep demands
   `grep -rn "log_system_event(\|\.save(\|\.objects\.create(" apps/proxy/ | grep -v tests` return
   nothing. Both cannot hold if the events view performs the writes itself. Splitting view from
   write satisfies both, and makes `proxy_orm_writes` actually reach its target of 0.
2. **The next-source path parameter is the relay's identifier, not strictly a channel UUID.** Every
   `live_proxy` endpoint is keyed by `<str:channel_id>` (`CLAUDE.md` § Routing), and
   `get_stream_object` resolves a channel UUID *or* a `stream_hash` — the admin UI's single-stream
   preview depends on the second. The route is `channels/<str:identifier>/next-source`; the view
   resolves it exactly as `get_stream_object` does today. Narrowing it to a UUID would break the
   by-hash preview surface, which `url_utils.py:83`'s `stream.get_stream()` serves.
3. **The response carries `slot_reserved`, which the spec's field list omits.**
   `generate_stream_url` returns it and `stream_ts` uses it to decide whether to release on every
   error path (`views.py:383,510,539,560`). Without it the relay cannot tell a reused assignment
   from a new reservation and would double-release.
4. **`stream_profile` is returned as `{id, command, args}` as the spec states, and PR 6's relay
   consumes only `id`.** `_establish_transcode_connection` keeps building the command from
   `channel.get_stream_profile()`, because the § ORM reads table deliberately keeps
   `input/manager.py:733`'s `StreamProfile` read in the relay. The other two fields are the stated
   contract and are what a Go relay (Phase 2) will need; narrowing a contract the spec spells out
   is a larger deviation than carrying two fields.
5. **Django, not the relay, decides which candidate is acceptable.** Today `_try_next_stream` loops
   candidates and rejects one whose URL equals the current URL. The request therefore carries
   `current_url`, Django skips any candidate resolving to it, and the relay accepts the single
   answer. This preserves today's semantics with one round trip instead of N, and it is why
   `update_url`'s only `return False` branch becomes unreachable from the failover path.
6. **The slot moves when Django hands out a source, not when the relay applies it — and
   `update_stream_profile()` itself is not changed.** `input/manager.py:1425-1450`'s
   `channel.update_stream_profile(...)` is deleted and the identical call happens inside
   `next_source.resolve_source()` for the returned source only, never for cached alternates. Spec:
   "`input/manager.py:1430`'s `update_stream_profile` moves into Django's next-source handling".
   **Read what that method actually does before writing a test against it**
   (`apps/channels/models.py:933-1003`): it reads `channel_stream:{channel.id}` to find the
   **original** stream, rewrites `stream_profile:{original_stream_id}` to the new profile, moves the
   credential slot and the two `profile_connections:*` counters — and **never writes
   `channel_stream:*` at all**. So after a failover the channel's `channel_stream` key still names
   the stream it first tuned, and `release_stream()` (`:842-864`), `get_stream()`'s reuse branch
   (`:711-723`) and `core/utils.py:778,811`'s event enrichment all read it that way on purpose.
   PR 6 preserves that chain exactly. Changing it would mean deleting the stale
   `stream_profile:{old}` and re-deriving three readers — relay-internal semantics D13 and the
   spec's "no relay internals rewritten" put out of scope. Recorded as an S10 note so PR 8 or
   Phase 2 can revisit it deliberately.
   Consequence of the move, stated rather than hidden: if the relay fails to apply a switch after
   Django moved the slot, the counter reflects a stream that is not running until the next switch or
   release. Today the same failure leaves it un-moved. A two-phase commit is out of scope.
7. **Every relay-side `release_stream()` call becomes `control_plane.release_source()`, not only
   the six the spec enumerates.** The spec names `server.py:2363,2373`,
   `output/ts/generator.py:618,620` and `output/fmp4/generator.py:378,380` because those are the
   rows in its § ORM reads table, but `views.py:383,510,539,560,785` call the same method on a
   `Channel` the relay loaded, and `release_stream()` deletes `channel_stream:*`/`stream_profile:*`.
   Leaving them would contradict the spec's own Requirements row ("exactly one writer").
8. **`server.py:2335,2342`'s deletes move to Django rather than disappearing.** They are the
   channel-deleted-mid-playback fallback. The relay reads its own metadata hash and passes
   `stream_id`/`m3u_profile_id`/`channel_pk` in the release body; Django performs the deletes and
   `release_profile_slot`. The metadata read stays in the relay, so PR 7's "no control-plane code
   reads relay keys" stays reachable.
9. **A release that cannot reach Django logs at `WARNING` and continues.** The profile-slot counter
   then over-counts until the next release for that profile. Accepted: refusing to tear a channel
   down because the control plane is unreachable is worse, and the pre-existing failure mode when
   Redis or the DB is unavailable is identical.
10. **`get_alternate_streams` and `get_stream_info_for_switch` end up deleted from `url_utils.py`,
    but not until Task 8.** That is the end state, not the sequence: `views.py:32-34`,
    `input/manager.py:19` and `services/channel_service.py:16` import both names at module level and
    keep doing so until Tasks 7 and 8 rewrite their call sites, so deleting them in Task 3 would
    `ImportError` every `apps.proxy.live_proxy.tests` run and `manage.py check` in between. Task 3
    therefore leaves **module-level aliases** in `url_utils.py` re-exporting the moved
    implementations, and Task 8's last step deletes the aliases with a grep proving no importer is
    left. `get_stream_object` is the exception: its re-export is **permanent**, because
    `input/manager.py:727` and `views.py:190` still need it and the spec's § ORM reads table keeps
    that lookup in the relay. Once the aliases are gone, the three API-process callers
    (`views.py:869`, `views.py:1157`, `services/channel_service.py:384`) call `next_source` directly,
    because they run in the API process after PR 4's routing and an HTTP self-call would be a
    loopback with no benefit. PR 7 moves those views to `relay_client`, at which point
    `change_stream_url` runs in the relay and PR 7 revisits the call — recorded here so PR 7 does not
    read it as a leak.
11. **`generate_stream_url` keeps its name, its location and its exact 6-tuple return.**
    `apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py` patches
    `apps.proxy.live_proxy.views.generate_stream_url` at four sites and asserts call ordering
    against the init lock. Changing the symbol or the arity would rewrite a test that pins a
    concurrency property this PR has no business touching.
12. **`relay_event` is admin-only on the socket.** `dispatcharr/consumers.py:9-18` restricts
    `channel_stats` and friends because their payloads carry channel UUIDs usable against anonymous
    `/proxy/ts/stream/<uuid>`. A `relay_event` carrying `channel_id` is the same telemetry and gets
    the same treatment; the payload is a field whitelist so no provider URL can ride along.
13. **"No candidate available" is a 200 with a null source, not a 4xx.** The client turns every 4xx
    into `ControlPlaneUnavailable`, which is what makes the degraded fallback fire; if "this channel
    has no stream left" arrived as a 409, a legitimate exhausted-channel answer would be
    indistinguishable from a Django outage and would trigger the unenforced fallback. So
    `next-source` answers `200 {"source": null, "error": "<reason>"}` whenever the identifier
    resolved, and `404` only when it resolved to neither a `Channel` nor a `Stream`. The `error`
    string is `get_stream()`'s own `error_reason`, verbatim, because `stream_ts`'s retry loop
    branches on `"maximum connection limits" not in error_reason` (`views.py:336`).
14. **The degraded fallback needs resolved candidates, so the initial call asks for them.**
    "the candidate stream list cached at channel start" is only usable without Django if each entry
    already carries `url`, `user_agent`, `transcode` and the profile ids. Resolving them costs the
    same queries `get_alternate_streams` runs at every failover today, paid once at tune;
    `get_transformed_credentials` (`apps/m3u/tasks.py:3048`) is pure string work with no network
    call, so there is no hidden cost.
15. **A refusal is not an outage: `ControlPlaneRefused` is a separate exception from
    `ControlPlaneUnavailable`, and only the second fires the degraded fallback.** `_post` raises
    `ControlPlaneRefused(status, body)` on 4xx and `ControlPlaneUnavailable` on 5xx, a timeout or a
    connection error; `ControlPlaneRefused` is **not** a subclass of it. Without the split, two real
    failures become silent degradation: a channel deleted mid-playback answers 404 at failover and
    the relay would keep streaming it from the stale cached list — where today
    `get_alternate_streams` catches the `Http404` and `_try_next_stream` returns `False`; and a 403
    from a `SECRET_KEY` mismatch between the api and relay roles would make **every** failover on the
    deployment degrade forever instead of failing loudly. `next_source()` maps a 404 to
    `{"source": None, "alternates": [], "error": "identifier not found"}` (an ordinary "no source");
    400 and 403 propagate as `ControlPlaneRefused`, which every caller treats as "no source" and logs
    at ERROR with the status only — never the body, never a URL.
16. **Replay inside the ±120 s window is possible and accepted.** The bound token carries no nonce,
    so a captured internal call can be repeated for up to two minutes. Accepted because the effect is
    bounded and the alternative is not worth it: a replayed `next-source` is idempotent once the 404
    mapping in ruling 15 lands, since `Channel.get_stream()` reuses a live assignment and reports
    `slot_reserved=False`; the worst case is a replayed `release` after a new tune re-reserved,
    which under-counts one provider slot until that channel's next release. A nonce store would need
    Redis on the verify path, and an attacker positioned to capture on the internal network already
    holds the static `X-Dispatcharr-Internal` token. Stated in the docstring and in S10.
17. **The two synchronous calls can stall one greenlet for ~14 s.** Worst case is
    2 × (2 s connect + 5 s read) + 0.1 s retry delay. `_try_next_stream` runs on the channel's
    main-loop greenlet and each generator's release runs inside the client response's `finally`, so a
    Django outage stalls that channel's failover and each disconnecting client's teardown for up to
    ~14 s. Other greenlets are unaffected — this is a cooperative yield, not a blocked hub. Stated
    because it is the number PR 8's Django-down scenario measures against.
18. **`channel_stream:*` semantics do not change in this PR.** See ruling 6: the test asserts what
    `update_stream_profile()` observably does today, not what its name suggests.

## Done criteria (from the spec)

- [ ] **The failover-events spec passes.** `cd e2e && npx playwright test --project=streaming-failover
      -g "a dead-air failover is reported as an event and a relay_event push"` (Task 13), and the
      whole `streaming-failover` project green.
- [ ] **All 16 backend labels green** (touching `apps/api/urls.py` routes to `__all__` via
      `_PATH_ALIASES`): `manage.py test --keepdb <label>` for each of `apps.accounts.tests`,
      `apps.backups.tests`, `apps.channels.tests`, `apps.connect.tests`, `apps.dashboard.tests`,
      `apps.epg.tests`, `apps.m3u.tests`, `apps.output.tests`, `apps.plugins.tests`,
      `apps.proxy.live_proxy.tests`, `apps.proxy.tests`, `apps.proxy.vod_proxy.tests`,
      `apps.timeshift.tests`, `apps.vod.tests`, `core.tests`, `tests`.
- [ ] **The relay writes nothing:**
      `grep -rn "log_system_event(\|\.save(\|\.objects\.create(" apps/proxy/ | grep -v tests`
      prints nothing.
- [ ] **`CLAUDE.md` corrected** — § Structural constraints ("exactly one ORM write" → zero, with
      the `log_system_event` sites named), § Known defects (the `channel_stream:*`/`stream_profile:*`
      split-brain, now Django-only), § Observing a channel ("No WebSocket event exists for stream
      switch, failover or client teardown" → `relay_event`). (Task 15.)

Additional gates this plan owns, in the same spirit:

- [ ] `python -m metrics.build --validate-only` exits 0 (the metrics edit hook fires on nothing
      here, but the architecture collector's `proxy_orm_writes` must read 0):
      `PYTHONPATH=scripts/metrics python scripts/metrics/collect_architecture.py .` prints
      `"proxy_orm_writes": 0`.
- [ ] `python manage.py spectacular --validate --fail-on-warn --file /dev/null` exits 0.
- [ ] `python manage.py makemigrations --check --dry-run dispatcharr_connect` exits 0 after Task 5.
- [ ] `scripts/check_credential_logging.py` clean on every edited `.py`.
- [ ] `cd frontend && npm test` green (Task 12).
- [ ] `cd e2e && npx tsc --noEmit` clean (Task 13).

## Test environment for this worktree

The edit/commit hooks resolve the project directory from the harness, so in a worktree they do not
run tests automatically. Run them yourself:

1. Start a container for this worktree (idempotent). **Run it in the foreground with `</dev/null`
   and a 600000 ms timeout** — it does not exit after the container is ready; poll `pg_isready` in
   a second call and kill it once that answers:
   `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr6 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr6 DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest /Users/dion/git/Dispatcharr/.worktrees/phase1-pr6/.claude/hooks/start-test-container.sh </dev/null`
2. After editing any file, run the affected-file hook by hand:
   `echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr6 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr6 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr6/.claude/hooks/run-affected-tests.sh`
   Exit 2 = blocking failure; read the output.
3. Before every commit, run the commit gate by hand:
   `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr6 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr6 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr6/.claude/hooks/pre-commit-tests.sh --git-hook`
4. Backend tests directly: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr6 /dispatcharrpy/bin/python manage.py test --keepdb <label> -v1`
5. Frontend: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr6/frontend && npm ci && npm test`.
   E2E typecheck: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr6/e2e && npm ci && npx tsc --noEmit`.
6. **E2E stack for this worktree only.** Build and bring up with
   `DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-pr6:local DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr6 DISPATCHARR_E2E_PORT=59191 DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr6 DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr6 DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-pr6 DISPATCHARR_E2E_UPSTREAM_PORT=9405 DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 scripts/e2e_up.sh`.
   `scripts/e2e_up.sh` silently reuses an existing image tag, so `docker rmi dispatcharr-e2e-pr6:local`
   before any rebuild. Recreate the provider container with
   `-e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-pr6:8080` or every subprocess-profile test fails
   with "188 bytes then EOF". Run Playwright with
   `E2E_BASE_URL=http://localhost:59191 DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr6 E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:9405 E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-pr6:8080`.
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
  internal_auth.py                 MODIFY  add the bound per-request token: INTERNAL_REQUEST_CONTEXT,
                                           HEADER/META_INTERNAL_REQUEST, internal_request_token(),
                                           request_is_internal_request()
  permissions.py                   NEW     IsInternalRelay — both internal headers, no principal
  next_source.py                   NEW     control-plane source resolution: get_stream_object,
                                           transform_url, resolve_initial_source,
                                           get_stream_info_for_switch, get_alternate_streams,
                                           order_alternates_from_current, resolve_source,
                                           release_source
  control_plane.py                 NEW     relay-side client: get_control_plane_base_url,
                                           next_source, release_source, emit_event, post_events,
                                           ControlPlaneUnavailable, ControlPlaneRefused
  serializers.py                   NEW     NextSourceRequest/Response, ReleaseRequest/Response,
                                           RelayEvent(Batch)/Response serializers
  api_views.py                     NEW     next_source_view, release_view, events_view
  api_urls.py                      NEW     the three routes
  live_proxy/redis_keys.py         MODIFY  + channel_stream, stream_profile, channel_source_cache
  live_proxy/url_utils.py          MODIFY  generate_stream_url becomes a control-plane wrapper and
                                           gains _cache_alternates / read_cached_alternates;
                                           get_stream_object and transform_url re-exported
                                           permanently; the other three aliased in Task 3 and
                                           deleted in Task 8
  live_proxy/views.py              MODIFY  redirect-alternates branch uses the cached alternates;
                                           release_stream() → control_plane.release_source();
                                           change_stream / next_stream call next_source directly
  live_proxy/server.py             MODIFY  release via control_plane; the two key deletes removed;
                                           log_system_event → emit_event
  live_proxy/input/manager.py      MODIFY  _try_next_stream is one next-source call; update_url's
                                           ORM block deleted; log_system_event → emit_event
  live_proxy/services/channel_service.py
                                   MODIFY  cancel_pending_shutdown and change_stream_url;
                                           _update_stream_stats_in_db becomes an event
  live_proxy/output/ts/generator.py       MODIFY  release + events
  live_proxy/output/fmp4/generator.py     MODIFY  release + events
  vod_proxy/multi_worker_connection_manager.py  MODIFY  vod_start/vod_stop events
  tests/test_internal_relay_permission.py NEW  the bound token and the permission class
  tests/test_next_source_api.py          NEW  the three views: gate, reservation, batch mapping
  tests/test_next_source_resolution.py   NEW  resolve_source branches, moved from url_utils tests
  tests/test_control_plane_client.py     NEW  base URL, timeout, retry, degraded fallback
  live_proxy/tests/test_redirect_transcode_flag.py  DELETE  moved to tests/ (below), imports
                                           retargeted to next_source
  tests/test_redirect_transcode_flag.py    NEW     the PR 5 Redirect-is-Proxy pin, moved whole
  live_proxy/tests/test_alternate_stream_order.py   MODIFY  import retargeted to next_source
  live_proxy/tests/test_try_next_stream.py          NEW  failover uses next-source; degraded path
core/
  relay_events.py                  NEW     apply_event_batch(): log_system_event calls + the one
                                           Stream.save(); the relay_event WebSocket push
  tests/test_relay_events.py       NEW     batch → rows, stream_stats writes no row, WS whitelist
apps/connect/
  models.py                        MODIFY  + channel_buffering in SUPPORTED_EVENTS
  migrations/0004_alter_eventsubscription_event.py  NEW  the choices change
apps/api/urls.py                   MODIFY  mount apps.proxy.api_urls at relay/
dispatcharr/consumers.py           MODIFY  relay_event joins ADMIN_ONLY_UPDATE_TYPES
tests/test_relay_event_visibility.py NEW   the consumer gate, admin vs Standard
frontend/src/
  WebSocket.jsx                    MODIFY  handleRelayEvent export + case 'relay_event'
  store/channels.jsx               MODIFY  relayEvents state + applyRelayEvent action
  store/__tests__/channels.test.jsx MODIFY  applyRelayEvent coverage
  __tests__/websocketRelayEvent.test.jsx NEW  the first vitest WebSocket.jsx has ever had
e2e/
  tests/streaming-failover/failover-events.spec.ts  NEW  @contract: SystemEvent row + relay_event
  COVERAGE.md                      MODIFY  one P1 row
docs/superpowers/specs/2026-09-04-phase1-process-split-design.md  MODIFY  Done log + amendment S10
CLAUDE.md                          MODIFY  three corrections named in spec § PR 6
```

---

### Task 1: Reset onto merged `main` and re-verify every anchor

**Files:** none edited. This task produces no commit.
**Interfaces:** Consumes `origin/main`. Produces a verified starting tree for Tasks 2-15.

- [ ] **Step 1: Confirm PR 5 merged, by content and not by hash.**
      Run: `git fetch origin && git log origin/main --oneline -3`
      Run: `git show origin/main:apps/proxy/internal_auth.py | grep -c "internal_principal_token"`
      Expected: `1` or more. If `0`, **stop**: PR 5 has not merged and this plan must not execute.
- [ ] **Step 2: Reset this branch onto `origin/main`.**
      Run: `git status --porcelain` — Expected: empty (this plan file is committed on the branch
      already, or stash it first).
      Run: `git reset --hard origin/main`
      Expected: `HEAD is now at <sha> …`. Then re-add this plan file if the reset removed it:
      `git checkout <this-branch>@{1} -- docs/superpowers/plans/2026-09-05-phase1-pr6-next-source-events.md`
- [ ] **Step 3: Re-verify the anchors this plan cites.** Run each and compare to the expected count;
      if a count differs, find the new lines with the same grep and use those, but if a *symbol* is
      missing, stop and report.
      Run:
      ```bash
      grep -c "log_system_event(" apps/proxy/live_proxy/server.py apps/proxy/live_proxy/input/manager.py apps/proxy/live_proxy/output/ts/generator.py apps/proxy/live_proxy/output/fmp4/generator.py apps/proxy/vod_proxy/multi_worker_connection_manager.py
      grep -rn "\.save(\|\.objects\.create(" apps/proxy/ | grep -v "/tests/" | grep '\.py:'
      grep -n "def generate_stream_url\|def get_stream_info_for_switch\|def get_alternate_streams\|def get_stream_object\|def order_alternates_from_current" apps/proxy/live_proxy/url_utils.py
      grep -rn "channel_stream:\|stream_profile:" apps/proxy/ | grep -v "/tests/" | grep '\.py:'
      grep -n "ADMIN_ONLY_UPDATE_TYPES" dispatcharr/consumers.py
      ```
      Expected: 2, 7, 2, 1, 1 event calls respectively (13 total); exactly one write,
      `services/channel_service.py:869`; the five function definitions present; eight
      `channel_stream:`/`stream_profile:` sites in `apps/proxy/` (server ×2, views ×2, url_utils ×4,
      channel_service ×1 — nine lines, eight statements); `ADMIN_ONLY_UPDATE_TYPES` defined once.
- [ ] **Step 4: Start the test container and take a baseline.**
      Run the § Test environment step 1 command, then
      `docker exec … dispatcharr-testrunner-pr6 … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests -v1`
      Expected: OK. A red baseline is a blocker to report, not something to fix here.

---

### Task 2: Bind the internal token and add `IsInternalRelay`

**Files:**
- Modify: `apps/proxy/internal_auth.py` (append after `request_is_internal`, currently the last
  function in the file)
- Create: `apps/proxy/permissions.py`
- Test: `apps/proxy/tests/test_internal_relay_permission.py`

**Interfaces:**
- Produces `INTERNAL_REQUEST_CONTEXT: bytes`, `HEADER_INTERNAL_REQUEST: str`,
  `META_INTERNAL_REQUEST: str`, `INTERNAL_REQUEST_WINDOW_SECONDS: int`,
  `internal_request_token(method: str, path: str, body: bytes, timestamp: int) -> str`,
  `build_internal_request_header(method: str, path: str, body: bytes) -> str` (what a caller sends;
  Task 4 and PR 7 use it), `request_is_internal_request(request) -> bool`, and
  `IsInternalRelay(rest_framework.permissions.BasePermission)`.
- Consumes `settings.SECRET_KEY`, `apps.proxy.internal_auth.request_is_internal`.

- [ ] **Step 1: Write the failing tests.** Create
      `apps/proxy/tests/test_internal_relay_permission.py`:
      ```python
      """The gate on /api/relay/... — both internal headers, never a principal.

      Phase 1 PR 6. The static X-Dispatcharr-Internal token says "part of this
      deployment" and is long-lived; issue #181 asks for a bound form before it
      becomes the sole gate on a control API. X-Dispatcharr-Internal-Request adds
      the binding: method, path, body and a 120s window.
      """
      import hashlib
      import hmac
      import time

      from django.conf import settings
      from django.test import RequestFactory, SimpleTestCase, override_settings

      from apps.proxy.internal_auth import (
          HEADER_INTERNAL,
          HEADER_INTERNAL_REQUEST,
          INTERNAL_REQUEST_WINDOW_SECONDS,
          internal_principal_token,
          internal_request_token,
          request_is_internal_request,
      )
      from apps.proxy.permissions import IsInternalRelay

      BODY = b'{"reason": "failover"}'
      PATH = "/api/relay/channels/abc/next-source"


      def _request(factory, *, static=True, bound=True, timestamp=None, path=PATH, body=BODY):
          headers = {}
          if static:
              headers["HTTP_X_DISPATCHARR_INTERNAL"] = internal_principal_token()
          if bound:
              ts = int(time.time()) if timestamp is None else timestamp
              headers["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = (
                  f"v1.{ts}." + internal_request_token("POST", path, body, ts)
              )
          return factory.post(
              path, data=body, content_type="application/json", **headers
          )


      class InternalRequestTokenTests(SimpleTestCase):
          def setUp(self):
              self.factory = RequestFactory()

          def test_a_correctly_signed_request_is_accepted(self):
              self.assertTrue(request_is_internal_request(_request(self.factory)))

          def test_the_signature_is_bound_to_the_path(self):
              request = _request(self.factory, path=PATH)
              request.path = "/api/relay/events"
              self.assertFalse(request_is_internal_request(request))

          def test_the_signature_is_bound_to_the_body(self):
              request = _request(self.factory, body=b'{"reason": "failover"}')
              request._body = b'{"reason": "tamper"}'
              self.assertFalse(request_is_internal_request(request))

          def test_an_expired_timestamp_is_refused(self):
              stale = int(time.time()) - INTERNAL_REQUEST_WINDOW_SECONDS - 5
              self.assertFalse(
                  request_is_internal_request(_request(self.factory, timestamp=stale))
              )

          def test_a_future_timestamp_beyond_the_window_is_refused(self):
              ahead = int(time.time()) + INTERNAL_REQUEST_WINDOW_SECONDS + 5
              self.assertFalse(
                  request_is_internal_request(_request(self.factory, timestamp=ahead))
              )

          def test_a_malformed_header_is_refused_rather_than_raising(self):
              request = self.factory.post(PATH, data=BODY, content_type="application/json")
              for value in ("", "v1", "v1.notanint.abc", "v2.1.abc", "\udcff"):
                  request.META["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = value
                  self.assertFalse(request_is_internal_request(request))

          @override_settings(SECRET_KEY="a-different-secret-entirely")
          def test_a_token_from_another_secret_is_refused(self):
              # Signed under the test's own SECRET_KEY, verified under another.
              request = self.factory.post(PATH, data=BODY, content_type="application/json")
              ts = int(time.time())
              other = hmac.new(
                  b"the-original-secret",
                  b"internal-request\nPOST\n" + PATH.encode() + b"\n" + str(ts).encode()
                  + b"\n" + hashlib.sha256(BODY).hexdigest().encode(),
                  hashlib.sha256,
              ).hexdigest()
              request.META["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = f"v1.{ts}.{other}"
              self.assertFalse(request_is_internal_request(request))


      class IsInternalRelayTests(SimpleTestCase):
          def setUp(self):
              self.factory = RequestFactory()
              self.permission = IsInternalRelay()

          def test_both_headers_are_required(self):
              self.assertTrue(
                  self.permission.has_permission(_request(self.factory), None)
              )

          def test_the_static_token_alone_is_not_enough(self):
              self.assertFalse(
                  self.permission.has_permission(
                      _request(self.factory, bound=False), None
                  )
              )

          def test_the_bound_token_alone_is_not_enough(self):
              self.assertFalse(
                  self.permission.has_permission(
                      _request(self.factory, static=False), None
                  )
              )

          def test_an_authenticated_admin_without_the_headers_is_refused(self):
              request = self.factory.post(PATH, data=BODY, content_type="application/json")

              class _Admin:
                  is_authenticated = True
                  user_level = 10

              request.user = _Admin()
              self.assertFalse(self.permission.has_permission(request, None))
      ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_internal_relay_permission -v1`
      Expected: FAIL — `ImportError: cannot import name 'HEADER_INTERNAL_REQUEST'`.
- [ ] **Step 2: Extend `apps/proxy/internal_auth.py`.** Add to the constants block, beside
      `INTERNAL_PRINCIPAL_CONTEXT`:
      ```python
      # A third context, for the *bound* form of the internal principal. The
      # static token above is long-lived and shared by every internal caller
      # (issue #181); this one binds a single request — method, path, body — and
      # expires. /api/relay/... (PR 6) and /proxy/relay/... (PR 7) require both:
      # the static header says "part of this deployment", the bound one says
      # "and this exact call, just now". The DVR's stream fetch deliberately
      # sends only the static header, because ffmpeg re-sends its -headers line
      # on every reconnect for the life of a recording and a windowed token
      # would 403 the reconnect.
      INTERNAL_REQUEST_CONTEXT = b"internal-request"
      INTERNAL_REQUEST_WINDOW_SECONDS = 120
      ```
      and to the header/META blocks:
      ```python
      HEADER_INTERNAL_REQUEST = "X-Dispatcharr-Internal-Request"
      ...
      META_INTERNAL_REQUEST = "HTTP_X_DISPATCHARR_INTERNAL_REQUEST"
      ```
- [ ] **Step 3: Add the two functions** at the end of `apps/proxy/internal_auth.py`:
      ```python
      def internal_request_token(method: str, path: str, body: bytes, timestamp: int) -> str:
          """The hex digest half of X-Dispatcharr-Internal-Request.

          Signed over the method, the path, the timestamp and a digest of the
          body, so a captured call cannot be replayed against another route or
          with different arguments, and cannot be replayed at all once the
          window closes.

          Replay INSIDE the window is possible and accepted: there is no nonce.
          The effect is bounded — a replayed next-source is idempotent, since
          Channel.get_stream() reuses a live assignment and reports
          slot_reserved=False, and the worst case is a replayed release after a
          new tune re-reserved, which under-counts one provider slot until that
          channel's next release. A nonce store would put Redis on the verify
          path, and an attacker positioned to capture on the internal network
          already holds the static X-Dispatcharr-Internal token.
          """
          message = b"\n".join(
              [
                  INTERNAL_REQUEST_CONTEXT,
                  method.upper().encode(),
                  path.encode(),
                  str(int(timestamp)).encode(),
                  hashlib.sha256(body or b"").hexdigest().encode(),
              ]
          )
          return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


      def build_internal_request_header(method: str, path: str, body: bytes) -> str:
          """The full header value a caller sends. Used by control_plane and PR 7."""
          timestamp = int(time.time())
          return f"v1.{timestamp}.{internal_request_token(method, path, body, timestamp)}"


      def request_is_internal_request(request) -> bool:
          """True when this exact request was signed, recently, with SECRET_KEY."""
          raw = request.META.get(META_INTERNAL_REQUEST)
          if not isinstance(raw, str) or not raw.isascii():
              return False
          parts = raw.split(".")
          if len(parts) != 3 or parts[0] != "v1":
              return False
          try:
              timestamp = int(parts[1])
          except ValueError:
              return False
          if abs(int(time.time()) - timestamp) > INTERNAL_REQUEST_WINDOW_SECONDS:
              return False
          expected = internal_request_token(
              request.method, request.path, request.body, timestamp
          )
          return _matches(parts[2], expected)
      ```
      and add `import time` to the imports at the top of the file.
- [ ] **Step 4: Create `apps/proxy/permissions.py`:**
      ```python
      """The gate on every internal control surface (Phase 1 D11, PR 6).

      Not IsAdmin: IsAdmin needs a resolved User, which is exactly what these
      hops must not need — the caller is a process in this deployment, not a
      person. Two headers are required together. X-Dispatcharr-Internal is the
      long-lived identity token PR 5 introduced and the DVR still uses;
      X-Dispatcharr-Internal-Request binds one call to one method, path, body
      and 120-second window, so a leaked identity token alone opens nothing
      here (issue #181).
      """

      from rest_framework.permissions import BasePermission

      from apps.proxy.internal_auth import (
          request_is_internal,
          request_is_internal_request,
      )


      class IsInternalRelay(BasePermission):
          message = "Internal endpoint."

          def has_permission(self, request, view):
              http_request = getattr(request, "_request", request)
              return request_is_internal(http_request) and request_is_internal_request(
                  http_request
              )
      ```
- [ ] **Step 5: Run the tests.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_internal_relay_permission -v1`
      Expected: OK (11 tests) — `InternalRequestTokenTests` ×7 and `IsInternalRelayTests` ×4.
- [ ] **Step 6: Run the whole package and the credential guard.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests -v1` and
      `python scripts/check_credential_logging.py apps/proxy/internal_auth.py apps/proxy/permissions.py`
      Expected: OK; exit 0.
- [ ] **Step 7: Commit.** Write the message with the Write tool to
      `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/msg-pr6-t2.txt`:
      ```
      feat(phase1-pr6): bind the internal principal token per request

      X-Dispatcharr-Internal is static and long-lived: every internal caller
      shares one value for as long as SECRET_KEY is unrotated (issue #181).
      Before it becomes the sole gate on a control API, add the bound form.

      X-Dispatcharr-Internal-Request carries v1.<unix>.<hmac> over the context
      string, the method, the path, the timestamp and a SHA-256 of the body,
      accepted inside 120s. IsInternalRelay requires both headers, so a leaked
      identity token alone opens no route, and accepts no DRF or session
      principal at all. The DVR keeps the static header only: ffmpeg re-sends
      its -headers line on every reconnect and a window would break a long
      recording.
      ```
      Then, in one Bash call:
      `git add apps/proxy/internal_auth.py apps/proxy/permissions.py apps/proxy/tests/test_internal_relay_permission.py`
      and, in a **separate** Bash call:
      `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/msg-pr6-t2.txt`
      Every later task's commit follows this same three-step shape — Write the message file, one
      `git add` call, one `git commit -F` call — with the message file named `msg-pr6-t<N>.txt` in
      the same scratchpad directory.

---

### Task 3: Move source resolution to the control plane (`apps/proxy/next_source.py`)

**Files:**
- Create: `apps/proxy/next_source.py`
- Modify: `apps/proxy/live_proxy/url_utils.py` — move out `_resolve_live_stream_url` (22-46),
  `get_stream_object` (50-59), `transform_url` (172-213) with `URL_TRANSFORM_REGEX_TIMEOUT` (170)
  and the `regex` import (5), `get_stream_info_for_switch` (214-335),
  `order_alternates_from_current` (337-362) and `get_alternate_streams` (364-489), leaving
  **module-level re-exports** for the five public names — two permanent, three transitional.
  `generate_stream_url` (62-165) keeps its name and 6-tuple and calls the moved code directly;
  Task 7 replaces its body with the HTTP call. What stays: `generate_stream_url`,
  `validate_stream_url` (491) and `get_connections_left` (617).
- Modify: `apps/proxy/live_proxy/tests/test_live_db_cleanup.py:164-215` — move the three
  `UrlUtilsDbCleanupTests` methods that patch the moved symbols
  (`test_generate_stream_url_closes_db` `:166-178`, `test_get_alternate_streams_closes_db`
  `:180-191`, `test_get_stream_info_for_switch_closes_db_on_error` `:193-203`) into the new test
  file; `test_get_connections_left_closes_db` (`:205-215`) stays, because `get_connections_left`
  stays.
- Delete: `apps/proxy/live_proxy/tests/test_redirect_transcode_flag.py` (moved whole, Step 5)
- Create: `apps/proxy/tests/test_redirect_transcode_flag.py`
- Modify: `apps/proxy/live_proxy/tests/test_alternate_stream_order.py` (import at `:4`)
- Test: `apps/proxy/tests/test_next_source_resolution.py`

**Interfaces:**
- Produces, all public in `apps.proxy.next_source`: `get_stream_object(identifier)`,
  `transform_url(input_url, search_pattern, replace_pattern)`, `URL_TRANSFORM_REGEX_TIMEOUT`,
  `resolve_initial_source(identifier) -> dict`,
  `get_stream_info_for_switch(channel_id, target_stream_id=None) -> dict`,
  `get_alternate_streams(channel_id, current_stream_id=None) -> list[dict]`,
  `order_alternates_from_current(alternates, ordered_stream_ids, current_stream_id)`,
  `resolve_source(identifier, *, exclude_stream_ids=(), current_url=None, target_stream_id=None, reason="initial", include_alternates=False) -> dict`,
  `release_source(identifier, *, stream_id=None, m3u_profile_id=None, channel_pk=None) -> bool`.
  The three middle names keep their **original names and signatures** deliberately: they are the
  moved implementations, `resolve_source` is built on them, and the aliases Task 3 leaves in
  `url_utils.py` point at them so the tree is importable after every commit (ruling 10).
- Consumes `Channel.get_stream()`, `Channel.release_stream()`, `Channel.update_stream_profile()`,
  `Stream.get_stream()`, `Stream.release_stream()`, `M3UAccountProfile`,
  `apps.m3u.connection_pool.{get_profile_connection_count, profile_available_for_channel_switch, release_profile_slot}`.

- [ ] **Step 1: Write the failing tests.** Create `apps/proxy/tests/test_next_source_resolution.py`
      with the resolution behaviour the relay used to own. Use `TestCase` (DB) and one channel with
      two streams on one `M3UAccount` with one active default profile (`max_streams` large enough
      not to interfere) — except for the profile-move case below, which needs a second account, and
      says why. Assert:
      ```python
      """Source resolution, now on the control-plane side of the boundary.

      Phase 1 PR 6. These are the properties apps/proxy/live_proxy/url_utils.py
      used to hold: pick a stream, reserve its slot, resolve its URL, and treat
      a Redirect profile exactly like Proxy on every derivation (the PR 5
      re-review's fix, which must survive the move).
      """
      ```
      - `test_the_initial_call_reserves_a_slot_once`: `resolve_source(uuid)` returns
        `source["slot_reserved"] is True` and `source["stream_id"] == streams[0].id`; a second call
        with the assignment still in Redis returns `slot_reserved is False` and the same stream.
      - `test_a_stream_hash_identifier_resolves_the_stream_surface`:
        `resolve_source(stream.stream_hash)` returns that stream's id.
      - `test_excluded_streams_are_skipped`: `resolve_source(uuid, exclude_stream_ids=[streams[0].id],
        reason="failover")` returns `streams[1].id`.
      - `test_a_candidate_resolving_to_the_current_url_is_skipped`: pass `current_url` equal to the
        first candidate's resolved URL and assert the answer is the other stream.
      - `test_no_candidate_left_is_an_error_not_an_exception`: exclude both → `{"source": None,
        "error": <non-empty str>}`.
      - `test_an_unknown_identifier_raises_http404`: `resolve_source("not-a-channel")` raises
        `django.http.Http404` rather than returning an error dict. Both moved helpers catch
        `Exception` broadly (`url_utils.py:161-163`, `:485`), so `resolve_source` has to resolve the
        identifier before entering them or the 404 route in Task 6 is unreachable and the tune gets
        an opaque error string instead.
      - `test_include_alternates_returns_resolved_candidates_that_reserve_nothing`: the `alternates`
        list carries `url`/`user_agent`/`transcode`/`m3u_profile_id` and every entry has
        `slot_reserved is False`.
      - the two Redirect-is-Proxy assertions: `transcode is False` for a locked Redirect stream
        profile on both the initial and the `target_stream_id` branch. **These are not new tests** —
        Step 4 moves `apps/proxy/live_proxy/tests/test_redirect_transcode_flag.py` here whole; do not
        write a second copy.
      - `test_a_switch_moves_the_profile_slot_and_leaves_channel_stream_alone`. **This one case needs
        a second fixture**, and the reason is the whole point of the test. With the single-account
        fixture above, `get_stream_info_for_switch(uuid, streams[1].id)` (`url_utils.py:258-289`)
        computes `channel_using_profile=True` for the one default profile and selects it, so
        `_commit` calls `update_stream_profile(<the profile already set>)`, which returns `True` at
        the "Don't do anything if the profile is already set" guard (`apps/channels/models.py:961-963`)
        having moved nothing. Nothing to assert, and an executor trying to make an assertion pass
        would edit the method rulings 6 and 18 forbid touching.
        So: build `streams[1]` on a **second `M3UAccount` with its own active default profile
        `P_b`**, leaving `streams[0]` on `P_a`. With an assignment live on `streams[0]` and
        `target_stream_id=streams[1].id`, assert exactly what `update_stream_profile()` does
        (`apps/channels/models.py:933-1003` — read it before writing this):
        - `stream_profile:<streams[0].id>` — the **original** stream's key — now names `P_b.id`;
        - `profile_connections:<P_a.id>` decremented by one, `profile_connections:<P_b.id>`
          incremented by one;
        - `stream_profile:<streams[1].id>` does **not** exist;
        - `channel_stream:<channel.id>` still names `streams[0].id`, unchanged.
        **Do not assert `channel_stream` moved**: that method never writes it, `release_stream()`
        (`:842-864`), `get_stream()`'s reuse branch (`:711-723`) and `core/utils.py:778,811` all
        depend on it staying put, and making it move is a semantics change ruling 6 and 18 put out
        of scope. The last two assertions together *are* the chain S10 item 6 records for PR 8.
        Every other case in this file keeps the single-account fixture.
      - the three geventpool-release pins moved from
        `apps/proxy/live_proxy/tests/test_live_db_cleanup.py` (Step 5). They keep their assertions
        and change only their patch targets, from `apps.proxy.live_proxy.url_utils.*` to
        `apps.proxy.next_source.*`:
        ```python
        class NextSourceDbCleanupTests(SimpleTestCase):
            @patch("apps.proxy.next_source.close_old_connections")
            @patch("apps.proxy.next_source.get_stream_object")
            def test_resolve_source_closes_db(self, mock_get_object, mock_close):
                channel = MagicMock()
                channel.get_stream.return_value = (None, None, "no streams", False)
                mock_get_object.return_value = channel

                from apps.proxy.next_source import resolve_source

                answer = resolve_source("channel-uuid")

                self.assertIsNone(answer["source"])
                mock_close.assert_called_once()

            @patch("apps.proxy.next_source.close_old_connections")
            @patch("apps.proxy.next_source.get_stream_object")
            def test_get_alternate_streams_closes_db(self, mock_get_object, mock_close):
                channel = MagicMock()
                channel.streams.all.return_value.order_by.return_value.exists.return_value = False
                mock_get_object.return_value = channel

                from apps.proxy.next_source import get_alternate_streams

                self.assertEqual(get_alternate_streams("channel-uuid", current_stream_id=1), [])
                mock_close.assert_called_once()

            @patch("apps.proxy.next_source.close_old_connections")
            @patch("apps.proxy.next_source.get_object_or_404")
            def test_get_stream_info_for_switch_closes_db_on_error(self, mock_get_404, mock_close):
                mock_get_404.side_effect = RuntimeError("db error")

                from apps.proxy.next_source import get_stream_info_for_switch

                result = get_stream_info_for_switch("channel-uuid", target_stream_id=99)

                self.assertIn("error", result)
                mock_close.assert_called_once()
        ```
        `test_resolve_source_closes_db` asserts `close_old_connections` is called **once**, which is
        why `resolve_source` must carry no `finally` of its own: each moved function keeps the
        `try/finally` it has today and the dispatcher adds none (Step 2).
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_next_source_resolution -v1`
      Expected: FAIL — `ModuleNotFoundError: No module named 'apps.proxy.next_source'`.
- [ ] **Step 2: Create `apps/proxy/next_source.py`** by moving the four functions verbatim and
      wrapping them in `resolve_source`. Header:
      ```python
      """Which stream a channel plays next — Django's answer, not the relay's.

      Phase 1 PR 6. Everything here used to live in
      apps/proxy/live_proxy/url_utils.py and ran inside the relay: the ordered
      traversal of a channel's streams, the per-profile capacity check, the
      provider-slot reservation, and the URL/user-agent/transcode derivation.
      It moves here whole, not rewritten — the relay reaches it over
      POST /api/relay/channels/<identifier>/next-source (ADR 0005), and the six
      Django-side callers reach it by import.

      Nothing in this module runs in the relay process. It is the only place
      Channel.get_stream(), Channel.release_stream() and
      Channel.update_stream_profile() are called from, which is what gives
      channel_stream:* and stream_profile:* a single writer.
      """
      ```
      Move these **verbatim, keeping their names and signatures** — the aliases in Step 3 and the
      moved tests both depend on the names surviving:
      - `_resolve_live_stream_url` (from `url_utils.py:22-46`).
      - `get_stream_object` (from `url_utils.py:50-59`).
      - **`transform_url` (from `url_utils.py:172-213`) and `URL_TRANSFORM_REGEX_TIMEOUT`
        (`:170`), with the `import regex` at `:5`.** Not optional and not cosmetic:
        `_resolve_live_stream_url` ends by calling `transform_url` (`url_utils.py:43-47`), so leaving
        it behind would make `next_source` import `url_utils` at module level while `url_utils`
        imports `next_source` for the Step 3 aliases — a circular import that fails in **either**
        load order and takes `manage.py check` with it. Its two outside callers import it
        function-locally (`apps/m3u/connection_pool.py:81`, `dispatcharr/consumers.py:116`) and are
        served by the permanent re-export Step 3 adds. `apps/proxy/vod_proxy/views.py:591`'s
        `_transform_url` is a different, private function and is untouched.
      - `order_alternates_from_current` (from `url_utils.py:337-362`).
      - `get_stream_info_for_switch(channel_id, target_stream_id=None)` (from `url_utils.py:214-335`),
        including its `try/finally: close_old_connections()`.
      - `get_alternate_streams(channel_id, current_stream_id=None)` (from `url_utils.py:364-489`),
        including its `try/finally`. Note its second parameter is a single id to *exclude*; the
        multi-exclude filtering is `resolve_source`'s, applied to the list it returns.
      - The body of `generate_stream_url` (from `url_utils.py:62-165`) as
        `resolve_initial_source(identifier)`, returning `{"source": <dict|None>, "error": <str|None>}`
        instead of the 6-tuple, keeping its `try/finally` and both of its branches (the `Stream`
        by-hash preview branch and the `Channel` branch).
      Also move `from django.shortcuts import get_object_or_404` and
      `from django.db import close_old_connections` — the moved tests patch both by their new module
      path — plus `redact_url`, `requests`, the `apps.channels.models` and `apps.m3u` imports, and
      `typing`'s `Optional`/`List`.
      **`next_source.py` gets its own logger, not `url_utils`'s.** `url_utils` builds its at `:19`
      from `.utils.get_logger`, which is another `live_proxy` import and would reintroduce the cycle
      MAJOR A closes. Use `logger = logging.getLogger("live_proxy")` — the same logger name
      `services/channel_service.py:20` already uses, so every moved line logs to exactly the stream
      it logs to today.
      Then the two public entry points:
      ```python
      def resolve_source(
          identifier,
          *,
          exclude_stream_ids=(),
          current_url=None,
          target_stream_id=None,
          reason="initial",
          include_alternates=False,
      ):
          """Resolve one playable source, and optionally the fallback list.

          Three shapes, one function:
            * no excludes, no target -> Channel.get_stream() unchanged (D13),
              which reuses a live assignment or reserves a new slot.
            * target_stream_id -> that stream, if a profile has capacity; the
              provider slot moves to its profile.
            * exclude_stream_ids -> the ordered traversal, skipping what the
              relay has already tried and anything resolving to current_url,
              then the slot moves to the winner. current_url is what lets
              Django make the whole decision: the relay used to loop
              candidates only to reject one whose URL matched its own.

          Returns {"source": <dict|None>, "alternates": [dict], "error": <str|None>}.
          Only "source" ever reserves or moves a slot; alternates are
          resolution only, which is what makes the relay's degraded fallback
          unenforced by construction. This function adds no try/finally of its
          own: each moved helper still closes its own connections, and
          NextSourceDbCleanupTests asserts exactly one close on the initial path.
          """
          # Resolve the identifier FIRST, outside every try. Both moved
          # helpers end in `except Exception` (url_utils.py:161-163 and :485)
          # and would swallow the Http404 get_stream_object raises for an
          # unknown identifier, turning a 404 into a 200 with an opaque
          # "No Stream matches the given query." error string. The view's
          # `except Http404 -> 404` (Task 6) depends on this line, and so does
          # test_next_source_404s_an_unknown_identifier. The DB-cleanup pin
          # patches this same name, so test_resolve_source_closes_db is
          # unaffected.
          get_stream_object(identifier)

          excluded = {int(sid) for sid in exclude_stream_ids or ()}

          if not excluded and target_stream_id is None:
              answer = resolve_initial_source(identifier)
              if answer["source"] is not None and include_alternates:
                  answer["alternates"] = _resolve_alternates(
                      identifier, answer["source"]["stream_id"]
                  )
              answer.setdefault("alternates", [])
              return answer

          if target_stream_id is not None:
              info = get_stream_info_for_switch(identifier, target_stream_id)
              if "error" in info:
                  return {"source": None, "alternates": [], "error": info["error"]}
              return {
                  "source": _commit(identifier, info),
                  "alternates": [],
                  "error": None,
              }

          # Failover: the ordered traversal, minus what the relay has tried and
          # minus anything resolving to the URL already playing. That last check
          # is the only reason input/manager.py used to loop candidates itself.
          for candidate in get_alternate_streams(identifier):
              if candidate["stream_id"] in excluded:
                  continue
              info = get_stream_info_for_switch(identifier, candidate["stream_id"])
              if "error" in info or not info.get("url"):
                  continue
              if current_url and info["url"] == current_url:
                  continue
              return {
                  "source": _commit(identifier, info),
                  "alternates": [],
                  "error": None,
              }
          return {
              "source": None,
              "alternates": [],
              "error": "No alternate stream with available connections",
          }


      def _commit(identifier, info):
          """Move the provider slot to the chosen candidate, then shape it.

          This is exactly the call input/manager.py's update_url made at :1437,
          moved here because the credential-slot move belongs on the side that
          owns the counter. Channel.update_stream_profile() is UNCHANGED: it
          rewrites stream_profile:{the channel's ORIGINAL stream} and moves both
          profile_connections counters, and it never writes channel_stream:*.
          That chain is what release_stream(), get_stream()'s reuse branch and
          core/utils.py's event enrichment all read; PR 6 does not touch it
          (spec § PR 6 amendment S10).
          """
          channel = get_stream_object(identifier)
          slot_reserved = False
          if isinstance(channel, Channel) and info.get("m3u_profile_id"):
              slot_reserved = bool(channel.update_stream_profile(info["m3u_profile_id"]))
          return _source_from_info(info, slot_reserved=slot_reserved)
      ```
      `_source_from_info(info, *, slot_reserved)` shapes one Source dict from what
      `get_stream_info_for_switch` returns plus the `StreamProfile` row named by `info['stream_profile']`
      — the seven fields in `apps/proxy/serializers.py`'s `SourceSerializer` (Task 6).
      `_resolve_alternates(identifier, current_stream_id)` calls `get_alternate_streams` then
      `get_stream_info_for_switch` per candidate, returning Source dicts with `slot_reserved=False`
      and committing nothing.
      and
      ```python
      def release_source(identifier, *, stream_id=None, m3u_profile_id=None, channel_pk=None):
          """Give the provider slot back. Wraps release_stream() (D13).

          The three-step fallback is what apps/proxy/live_proxy/server.py used
          to run: Channel.release_stream(), then Stream.release_stream(), then
          — for a channel deleted mid-playback, where neither row exists — the
          ids the relay read out of its own metadata hash, which is why they
          arrive as arguments rather than being re-read here.
          """
      ```
      The metadata fallback body is lifted from
      `apps/proxy/live_proxy/server.py:2320-2354`'s `_release_profile_slot_from_redis_metadata`,
      minus its metadata *reads* (they stay in the relay) and minus the `hdel`, keeping the two
      `delete()` calls and `release_profile_slot(profile_id, redis_client)`.
- [ ] **Step 3: Point `url_utils.py` at the moved code, with aliases.** Delete the five function
      bodies from `apps/proxy/live_proxy/url_utils.py` and add at the top, after the existing
      imports:
      ```python
      # The implementations moved to apps/proxy/next_source.py in Phase 1 PR 6,
      # because resolving a source is Django's job now.
      #
      # These two re-exports are PERMANENT. get_stream_object: input/manager.py
      # :727, views.py:190 and authorize.py:330 still look a channel or stream
      # up by identifier, and the spec's § ORM reads table keeps that read in
      # the relay. transform_url: apps/m3u/connection_pool.py:81 and
      # dispatcharr/consumers.py:116 both import it from here, function-locally,
      # and neither should have to learn that it moved.
      #
      # The other three are TRANSITIONAL aliases. views.py:32-34,
      # input/manager.py:19 and services/channel_service.py:16 import them at
      # module level today; Tasks 7 and 8 rewrite those call sites and Task 8's
      # last step deletes these three lines. Without them, every commit between
      # here and there leaves the package unimportable.
      from apps.proxy.next_source import get_stream_object, transform_url  # noqa: F401
      from apps.proxy.next_source import (  # noqa: F401  transitional, deleted in Task 8
          get_alternate_streams,
          get_stream_info_for_switch,
          order_alternates_from_current,
      )
      ```
      **The import graph after this step, which is the thing to check rather than re-derive.**
      Module-level edges only; function-local imports are not edges and are how the tree already
      breaks its worst tangles (602 of them):

      ```
      apps/proxy/next_source.py
        -> django, regex, requests, typing, logging
        -> apps.channels.models      -> apps.proxy.live_proxy.{redis_keys, constants}   (leaves)
        -> apps.m3u.{models, connection_pool}
        -> dispatcharr.utils (redact_url)
        (imports NOTHING from apps.proxy.live_proxy — this is the invariant)

      apps/proxy/live_proxy/url_utils.py
        -> apps.proxy.next_source          (the five re-exports)
        -> .utils, .redis_keys, .constants (its own package, still)

      apps/m3u/connection_pool.py:81  -> url_utils.transform_url   (function-local, not an edge)
      dispatcharr/consumers.py:116    -> url_utils.transform_url   (function-local, not an edge)
      apps/proxy/authorize.py:330     -> url_utils.get_stream_object (function-local, not an edge)
      ```

      `next_source` importing anything under `apps.proxy.live_proxy` at module level closes the loop
      and breaks every management command, not just this module. Step 6 proves both load orders.

      **Prune `url_utils.py`'s own imports to what the three survivors still use.** After the move it
      keeps `generate_stream_url` (Task 7 turns it into the HTTP wrapper), `validate_stream_url`
      (`:491`) and `get_connections_left` (`:617`), so it still needs `requests`, `redact_url`,
      `M3UAccountProfile`, `close_old_connections`, `logger` and `Optional`/`Tuple`. It no longer
      needs `regex` (moved), `Channel`/`Stream`/`M3UAccount` (`:9-10` — every remaining user moved),
      `get_object_or_404` (moved) or the `apps.m3u.connection_pool` import at `:11-14`
      (`get_profile_connection_count` and `profile_available_for_channel_switch` are both
      `get_alternate_streams`'s and `get_stream_info_for_switch`'s, and both moved). Dropping that
      last one matters beyond tidiness: `connection_pool` imports `transform_url` back out of
      `url_utils`, and removing the module-level edge in the other direction leaves that pair with no
      import relationship at all outside a function body.
      Keep `generate_stream_url` for now, with its body replaced by a direct call:
      ```python
      def generate_stream_url(channel_id):
          """Unchanged 6-tuple contract; the resolution moved to next_source.

          Task 7 replaces this body again with the control-plane call. Split in
          two so the move and the HTTP hop are separately reviewable.
          """
          from apps.proxy.next_source import resolve_source

          answer = resolve_source(channel_id, reason="initial", include_alternates=True)
          source = answer["source"]
          if source is None:
              return None, None, False, None, False, answer["error"]
          return (
              source["url"],
              source["user_agent"],
              source["transcode"],
              source["stream_profile"]["id"],
              source["slot_reserved"],
              None,
          )
      ```
- [ ] **Step 4: Move the PR 5 Redirect pin that followed the code.**
      `apps/proxy/live_proxy/tests/test_redirect_transcode_flag.py` holds exactly two tests —
      `test_initial_tune_reports_transcode_false` (`:95`) and `test_switch_path_agrees_transcode_false`
      (`:118`) — plus the `FakeRedirectRedis` helper (`:30`) and the `RedirectTranscodeFlagTests`
      fixture (`:47`). Both assert `transcode is False` for a locked Redirect profile, and both call
      code that now lives in `next_source.py`. **Move the whole file** to
      `apps/proxy/tests/test_redirect_transcode_flag.py` and `git rm` the original, changing exactly
      three things and nothing else:
      - the module imports become `from apps.proxy.next_source import get_stream_info_for_switch,
        resolve_initial_source`;
      - the two `@patch("apps.proxy.live_proxy.url_utils.close_old_connections")` decorators (`:92`,
        `:114`) become `@patch("apps.proxy.next_source.close_old_connections")`;
      - the first test's call becomes
        ```python
        answer = resolve_initial_source(str(self.channel.uuid))

        self.assertIsNone(answer["error"])
        self.assertFalse(answer["source"]["transcode"])
        self.assertEqual(answer["source"]["stream_profile"]["id"], self.redirect_profile.id)
        ```
        replacing the 6-tuple unpack, because `generate_stream_url` becomes an HTTP call in Task 7
        and this pin must keep testing the derivation, not the transport.
      The second test is unchanged below its decorator: `get_stream_info_for_switch` moved verbatim
      and still returns `stream_profile` as a bare profile id. The pin is a PR 5 re-review finding —
      a Redirect channel's first automatic switch rebuilding an empty ffmpeg command — and it must
      survive the move intact, not be rewritten. The two Redirect-is-Proxy cases listed in Step 1 are
      therefore **not** written from scratch: they are these two, moved.
- [ ] **Step 5: Move the three geventpool pins that followed the code.** In
      `apps/proxy/live_proxy/tests/test_live_db_cleanup.py`, cut `UrlUtilsDbCleanupTests`'s first
      three methods (`test_generate_stream_url_closes_db` `:166-178`,
      `test_get_alternate_streams_closes_db` `:180-191`,
      `test_get_stream_info_for_switch_closes_db_on_error` `:193-203`) and paste them into
      `apps/proxy/tests/test_next_source_resolution.py` as `NextSourceDbCleanupTests`, in the form
      Step 1 gives. **Leave `test_get_connections_left_closes_db` (`:205-215`) where it is** —
      `get_connections_left` stays in `url_utils.py` — and leave the class in place around it, with
      `TsGeneratorDbCleanupTests` and everything above untouched. They pin "the live proxy releases
      its geventpool checkout after ORM work", a property the move must not lose. Also change
      `apps/proxy/live_proxy/tests/test_alternate_stream_order.py:4` to
      `from apps.proxy.next_source import order_alternates_from_current`.
- [ ] **Step 6: Run.**
      Run: `docker exec … manage.py check`
      Expected: `System check identified no issues`.
      Run, because `manage.py check` only exercises whichever order the app registry happens to
      reach first, and a cycle is asymmetric:
      ```bash
      docker exec … /dispatcharrpy/bin/python -c "
      import django; django.setup()
      import apps.proxy.next_source, apps.proxy.live_proxy.url_utils"
      docker exec … /dispatcharrpy/bin/python -c "
      import django; django.setup()
      import apps.proxy.live_proxy.url_utils, apps.proxy.next_source"
      ```
      Expected: both exit 0 with no output. An `ImportError: cannot import name … (most likely due to
      a circular import)` from either means something under `apps.proxy.live_proxy` is still imported
      at `next_source`'s module level.
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests -v1`
      Expected: OK — including `test_live_db_cleanup`, `test_alternate_stream_order` and the moved
      Redirect pin. `apps.channels.tests` is in scope because `_PATH_ALIASES` routes
      `apps/proxy/live_proxy/` there (`dispatcharr/test_discovery.py:41`).
      Run: `grep -rn "from ..url_utils import\|from .url_utils import\|live_proxy.url_utils" apps/ | grep -v "/tests/"`
      Expected: `views.py`, `input/manager.py` and `services/channel_service.py` still import the
      transitional names — that is what Step 3's aliases exist for, and Task 8 removes both ends.
- [ ] **Step 7: Check the metric moved the right way.**
      Run: `PYTHONPATH=scripts/metrics python scripts/metrics/collect_architecture.py . | python -c "import json,sys; print(json.load(sys.stdin)['proxy_orm_writes'])"`
      Expected: `1` — still the `channel_service.py:869` save, which Task 10 removes. Any other
      number means a write moved into `apps/proxy/` by accident.
- [ ] **Step 8: Commit.** Step 4's `git rm` of
      `apps/proxy/live_proxy/tests/test_redirect_transcode_flag.py` has already staged that
      deletion, so do **not** name that path in the staging call — it no longer exists on disk and
      naming it fails. Write `msg-pr6-t3.txt`, then in one Bash call stage exactly
      `apps/proxy/next_source.py apps/proxy/live_proxy/url_utils.py apps/proxy/tests/test_next_source_resolution.py apps/proxy/tests/test_redirect_transcode_flag.py apps/proxy/live_proxy/tests/test_live_db_cleanup.py apps/proxy/live_proxy/tests/test_alternate_stream_order.py`,
      and in a separate call commit with `-F <path>/msg-pr6-t3.txt`. Subject:
      `refactor(phase1-pr6): move source resolution to apps/proxy/next_source.py`.

---

### Task 4: The relay's control-plane client (`apps/proxy/control_plane.py`)

**Files:**
- Create: `apps/proxy/control_plane.py`
- Modify: `apps/proxy/live_proxy/redis_keys.py` — add `channel_source_cache`
- Test: `apps/proxy/tests/test_control_plane_client.py`

**Interfaces:**
- Produces `get_control_plane_base_url() -> str`, `ControlPlaneUnavailable(Exception)`,
  `ControlPlaneRefused(Exception)` (**not** a subclass of the first — ruling 15),
  `next_source(identifier, *, exclude_stream_ids=(), current_url=None, target_stream_id=None, reason="initial", include_alternates=False) -> dict`,
  `release_source(identifier, *, stream_id=None, m3u_profile_id=None, channel_pk=None) -> bool`,
  `post_events(events: list[dict]) -> bool`, `emit_event(event_type, channel_id=None, channel_name=None, **details) -> None`.
- Consumes `apps.proxy.internal_auth.{internal_principal_token, build_internal_request_header,
  HEADER_INTERNAL, HEADER_INTERNAL_REQUEST}`, `requests`.

- [ ] **Step 1: Write the failing tests.** Create `apps/proxy/tests/test_control_plane_client.py`,
      `SimpleTestCase` throughout, `requests.request` patched:
      - `test_the_base_url_follows_the_dvr_formula`: four `override_settings`-free
        `patch.dict(os.environ, ...)` cases — explicit `DISPATCHARR_INTERNAL_API_BASE_URL` wins and
        is `rstrip('/')`ed; `DISPATCHARR_ENV=modular` gives
        `http://web:9191` and honours `DISPATCHARR_WEB_HOST`/`DISPATCHARR_PORT`;
        `DISPATCHARR_ENV=dev` gives `http://127.0.0.1:5656`; the default gives
        `http://127.0.0.1:9191`.
      - `test_both_internal_headers_are_sent`: assert the call carries `X-Dispatcharr-Internal` equal
        to `internal_principal_token()` and an `X-Dispatcharr-Internal-Request` that
        `request_is_internal_request` accepts when replayed through a `RequestFactory` request built
        from the same method, path and body.
      - `test_the_timeout_is_two_and_five`: assert `kwargs["timeout"] == (2, 5)`.
      - `test_one_retry_on_a_connection_error_then_success`: first call raises
        `requests.ConnectionError`, second returns 200 → the answer is returned and
        `mock.call_count == 2`.
      - `test_two_failures_raise_control_plane_unavailable`: both raise → `ControlPlaneUnavailable`,
        `call_count == 2`.
      - `test_a_500_is_retried_once_and_a_400_is_not`: two separate assertions on `call_count`.
      - `test_a_4xx_raises_refused_not_unavailable`: a 403 raises `ControlPlaneRefused` with
        `.status == 403`, and `assertNotIsInstance(exc, ControlPlaneUnavailable)`. The two must not
        share a base class, or `except ControlPlaneUnavailable` in `_try_next_stream` silently
        catches a refusal and degrades (ruling 15).
      - `test_a_404_is_no_source_not_an_outage`: `next_source(...)` against a 404 returns
        `{"source": None, "alternates": [], "error": "identifier not found"}` and raises nothing —
        this is the channel-deleted-mid-playback case, which `get_alternate_streams` answers today by
        catching `Http404` and letting `_try_next_stream` return `False`.
      - `test_a_403_is_not_retried`: `call_count == 1`.
      - `test_emit_event_never_raises_when_the_control_plane_is_down`: `requests.request` always
        raises; `emit_event('channel_start', channel_id='x')` returns `None` and logs.
      - `test_emit_event_never_raises_on_a_refusal`: the answer is 403; `emit_event(...)` returns
        `None` and logs at ERROR. `_spawn` is synchronous in the test environment, so an escaping
        `ControlPlaneRefused` would surface here exactly as it would inside `stop_channel`.
      - `test_a_2xx_with_a_non_json_body_is_an_outage`: `response.json()` raises `ValueError` →
        `ControlPlaneUnavailable`, not a bare `ValueError` out of a greenlet.
      - `test_emit_event_posts_one_batch_of_one`: assert the JSON body is
        `{"events": [{"type": "channel_start", "channel_id": "x", "details": {...}}]}`.
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_control_plane_client -v1`
      Expected: FAIL — `ModuleNotFoundError: No module named 'apps.proxy.control_plane'`.
- [ ] **Step 2: Create `apps/proxy/control_plane.py`.** Header and base URL:
      ```python
      """The relay's side of the boundary: how it asks Django things.

      Phase 1 PR 6, D9. Three calls, all through nginx on the API role's port,
      never to a raw uWSGI listener (D5):

        POST /api/relay/channels/<identifier>/next-source   what to play next
        POST /api/relay/channels/<identifier>/release       give the slot back
        POST /api/relay/events                              what just happened

      Timeouts are (connect 2s, read 5s) with one retry, as the spec's
      "Degraded fallback" row states. requests is safe to call from a relay
      greenlet because gevent-early-monkey-patch is on: the socket read yields
      the hub rather than blocking it, which is the same reason
      url_utils.validate_stream_url already uses it on the tune path.

      Nothing here imports apps/proxy/relay_client.py (D10) — that is the other
      direction, Django to relay, and it is PR 7's.
      """
      ```
      ```python
      CONNECT_TIMEOUT = 2
      READ_TIMEOUT = 5
      TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)
      ATTEMPTS = 2  # the first try plus the one retry the spec allows


      def get_control_plane_base_url():
          """Where Django answers, for this deployment shape (D9).

          The same four-branch formula as get_dvr_stream_base_url()
          (apps/channels/tasks.py), with its own override variable: explicit,
          then modular by service name, then dev (no nginx — uWSGI's own http
          listener), then AIO through nginx on DISPATCHARR_PORT.
          """
          explicit = os.environ.get("DISPATCHARR_INTERNAL_API_BASE_URL")
          if explicit:
              return explicit.rstrip("/")
          env = os.environ.get("DISPATCHARR_ENV", "aio").lower()
          if env == "modular":
              host = os.environ.get("DISPATCHARR_WEB_HOST", "web")
              port = os.environ.get("DISPATCHARR_PORT", "9191")
              return f"http://{host}:{port}"
          if env == "dev":
              return "http://127.0.0.1:5656"
          port = os.environ.get("DISPATCHARR_PORT", "9191")
          return f"http://127.0.0.1:{port}"
      ```
      **A bare `manage.py runserver` needs `DISPATCHARR_ENV=dev`.** `CLAUDE.md` § Commands documents
      running the server with neither variable set; that falls through to the AIO branch, resolves to
      `http://127.0.0.1:9191`, and every tune answers "Control plane unreachable" — while the spec's
      error table says the dev shape resolves to the single process's own port. The fix is the same
      shape `get_dvr_stream_base_url()` already needs: run
      `DISPATCHARR_ENV=dev uv run python manage.py runserver`, or set
      `DISPATCHARR_INTERNAL_API_BASE_URL=http://127.0.0.1:8000`. Task 15 adds this to
      `CLAUDE.md` § Commands. Add a `test_a_bare_runserver_environment_resolves_to_the_aio_default`
      case asserting the fall-through so the trap is pinned rather than discovered.
      The one transport function:
      ```python
      def _post(path, payload):
          """One POST, signed, with one retry. Raises ControlPlaneUnavailable."""
          body = json.dumps(payload).encode()
          headers = {
              "Content-Type": "application/json",
              HEADER_INTERNAL: internal_principal_token(),
              HEADER_INTERNAL_REQUEST: build_internal_request_header("POST", path, body),
          }
          url = get_control_plane_base_url() + path
          last = None
          for attempt in range(ATTEMPTS):
              try:
                  response = requests.request(
                      "POST", url, data=body, headers=headers, timeout=TIMEOUT
                  )
              except requests.RequestException as exc:
                  last = exc
              else:
                  if response.status_code < 400:
                      try:
                          return response.json()
                      except ValueError as exc:
                          # A 2xx with a body that is not JSON is nginx or a
                          # proxy answering, not Django. Treat it as an outage
                          # so the caller's existing handling applies rather
                          # than letting a ValueError escape a greenlet.
                          raise ControlPlaneUnavailable(
                              f"{path} answered 2xx with a non-JSON body"
                          ) from exc
                  if response.status_code < 500:
                      # A refusal, not an outage — and the distinction is
                      # load-bearing. Only ControlPlaneUnavailable fires the
                      # degraded, unenforced fallback; a 404 (channel deleted
                      # mid-playback) or a 403 (SECRET_KEY mismatch between the
                      # api and relay roles) must fail the switch loudly instead
                      # of making every failover on the deployment degrade
                      # silently forever. Not a subclass: `except
                      # ControlPlaneUnavailable` must not catch this.
                      raise ControlPlaneRefused(response.status_code, path)
                  last = ControlPlaneUnavailable(f"{path} answered {response.status_code}")
              if attempt + 1 < ATTEMPTS:
                  # gevent-patched: this yields the hub, it does not block it.
                  time.sleep(RETRY_DELAY)
          raise ControlPlaneUnavailable(f"{path} unreachable: {last}")
      ```
      with `RETRY_DELAY = 0.1` beside the timeouts.
      with the two exception classes defined at the top of the module:
      ```python
      class ControlPlaneUnavailable(Exception):
          """Django could not be reached, or answered 5xx. Degrade."""


      class ControlPlaneRefused(Exception):
          """Django answered, and said no. Do not degrade — fail the attempt."""

          def __init__(self, status, path):
              # The path, never the body and never a URL: a refusal body can
              # echo request content, and scripts/check_credential_logging.py
              # cannot see what a caller formats into a log line from here.
              self.status = status
              super().__init__(f"{path} refused with {status}")
      ```
      **Three notes for the executor.** The header is signed once and reused across the retry: the
      whole call is bounded by two attempts of at most 7 s plus the delay, far inside the 120 s
      window, so re-signing would only make the retry stop being a pure repeat. `next_source()`
      catches `ControlPlaneRefused` with `.status == 404` and returns
      `{"source": None, "alternates": [], "error": "identifier not found"}` — an ordinary "no source"
      — and lets every other refusal propagate. And **the whole two-attempt sequence can occupy one
      greenlet for ~14 s** (2 × (2 s connect + 5 s read) + 0.1 s): `_try_next_stream` runs on the
      channel's main-loop greenlet and each generator's release runs inside the client response's
      `finally`, so a Django outage stalls that channel's failover and each disconnecting client's
      teardown for that long. Other greenlets are unaffected — this is a cooperative yield, not a
      blocked hub — and it is the number PR 8's Django-down scenario measures against (ruling 17).
- [ ] **Step 3: Add the three public calls.** `next_source()` and `release_source()` build the
      payload and call `_post`, returning the parsed answer (`next_source` returns the whole
      `{"source", "alternates", "error"}` dict; `release_source` returns `answer["released"]`).
      `post_events(events)` posts `{"events": events}` and returns `True`/`False`, swallowing
      **both** exception types — `ControlPlaneUnavailable` at `WARNING`, `ControlPlaneRefused` at
      `ERROR` with `.status`. Both, not just the first: `emit_event` is fire-and-forget, and on the
      synchronous `_spawn` path (a Celery worker, and every test) an escaping `ControlPlaneRefused`
      from a token fault would propagate out of `initialize_channel` or `stop_channel` and break a
      teardown; on the gevent path it is an unhandled greenlet exception nobody sees. An event that
      cannot be delivered is a lost event, never a raised one. `emit_event` has **the same signature as
      `core.utils.log_system_event`** so the thirteen call sites in Task 10 change one word:
      ```python
      def emit_event(event_type, channel_id=None, channel_name=None, **details):
          """Post one transition. Same signature as core.utils.log_system_event.

          Fire and forget, on a greenlet, for the same reason
          _spawn_channel_stop_event already spawns: a teardown or a tune must
          not wait on Django, and this call now crosses a process boundary.
          The cost is that a worker dying inside the window loses the event;
          the alternative is a 5s stall on the byte path.
          """
          event = {"type": event_type, "details": details}
          if channel_id is not None:
              event["channel_id"] = str(channel_id)
          if channel_name is not None:
              event["channel_name"] = channel_name
          for key in ("client_id", "stream_id"):
              if key in details:
                  event[key] = details[key]
          _spawn(post_events, [event])
      ```
      with `_spawn` mirroring `core/utils.py:_dispatch_system_event_integrations`:
      ```python
      def _spawn(fn, *args):
          from core.utils import _is_gevent_monkey_patched, _should_use_sync_websocket_send

          if _should_use_sync_websocket_send() or not _is_gevent_monkey_patched():
              fn(*args)
              return
          import gevent

          gevent.spawn(fn, *args)
      ```
- [ ] **Step 4: Add the cache key.** In `apps/proxy/live_proxy/redis_keys.py`, append:
      ```python
      @staticmethod
      def channel_source_cache(channel_id):
          """Resolved failover candidates, cached at channel start.

          Read only when the control plane is unreachable at failover time
          (Phase 1 PR 6's degraded fallback): the entries are stale, carry no
          slot reservation, and are used unenforced.
          """
          return f"live:channel:{channel_id}:source_cache"
      ```
      **No import may be added to this file** — `apps/channels/models.py:6-7` imports it at module
      level and one import here stops Django booting.
- [ ] **Step 5: Run.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_control_plane_client -v1`
      Expected: OK.
      Run: `docker exec … manage.py check` — Expected: `System check identified no issues` (the
      boot check that `redis_keys.py` edits exist for).
- [ ] **Step 6: Commit.** Write `msg-pr6-t4.txt`, then
      `git add apps/proxy/control_plane.py apps/proxy/live_proxy/redis_keys.py apps/proxy/tests/test_control_plane_client.py`
      and, separately, `git commit -F <path>/msg-pr6-t4.txt`. Subject:
      `feat(phase1-pr6): the relay's control-plane client`.

---

### Task 5: The Django-side event writer and `channel_buffering`

**Files:**
- Create: `core/relay_events.py`
- Modify: `apps/connect/models.py:3-21` (`SUPPORTED_EVENTS`)
- Create: `apps/connect/migrations/0004_alter_eventsubscription_event.py`
- Test: `core/tests/test_relay_events.py`

**Interfaces:**
- Produces `core.relay_events.apply_event_batch(events: list[dict]) -> dict` returning
  `{"accepted": int, "rejected": int}`, and `RELAY_WS_EVENT_TYPES: frozenset`.
- Consumes `core.utils.log_system_event`, `core.utils.send_websocket_update`,
  `apps.channels.models.Stream`.

- [ ] **Step 1: Write the failing tests.** Create `core/tests/test_relay_events.py`:
      - `test_each_event_becomes_a_system_event_row`: post a batch of `channel_start` and
        `channel_failover`; assert two `SystemEvent` rows with the right `event_type`, `channel_id`
        and `details`.
      - `test_stream_stats_writes_the_stream_row_and_no_event_row`: a `stream_stats` event with
        `stream_id` and `{"ffmpeg_output_bitrate": 4200.0}` updates `Stream.stream_stats` and
        `stream_stats_updated_at` and creates **zero** `SystemEvent` rows. This is the one that
        matters: `channel_service.py:775` fires on every parsed codec line and `log_system_event`
        trims to `max_system_events` (default 100), so a row per stats line would evict every real
        event.
      - `test_stream_stats_merges_rather_than_replaces`: pre-set `stream_stats` to
        `{"video_codec": "h264"}`, post a bitrate-only update, assert both keys survive and a
        `None` value in the batch does not overwrite an existing key (today's
        `_update_stream_stats_in_db` semantics).
      - `test_an_unknown_event_type_is_counted_as_rejected_not_raised`.
      - `test_an_event_without_a_channel_id_still_writes_a_row`: a batch of one `vod_start` carrying
        `content_name`/`client_ip`/`username` in `details` and **no** `channel_id` produces exactly
        one `SystemEvent` row whose `channel_id` is `None`. `SystemEvent.channel_id` is a
        `UUIDField` (`core/models.py:803`) and `UUIDField.to_python("")` raises `ValidationError`
        that `log_system_event`'s bare `except Exception` (`core/utils.py:922-924`) swallows, so an
        empty string here would silently stop writing every VOD event — which the relay writes
        today. `apply_event_batch` normalises `""` to `None` for `channel_id`, `channel_name` and
        `client_id` before the call, belt and braces beside the serializer's `default=None`.
      - `test_only_the_three_ui_visible_types_push_a_relay_event`: patch
        `core.relay_events.send_websocket_update`; `channel_failover`, `stream_switch` and
        `client_disconnect` each push once; `channel_start` pushes nothing.
      - `test_the_relay_event_payload_is_a_whitelist`: post a `stream_switch` whose details carry
        `new_url`; assert the pushed payload has no `new_url` and no `details` key, and does carry
        `event`, `channel_id`, `stream_id`, `timestamp`.
      - `test_stream_stats_releases_the_db_connection`: patch
        `core.relay_events.close_old_connections` and assert it is called once per
        `stream_stats` event. This is the geventpool property
        `apps/proxy/live_proxy/tests/test_atomic_db_close.py:34-43` used to pin on the relay side;
        Task 10 replaces that test with one about the post, so the property has to be asserted here
        or it is silently dropped.
      Run: `docker exec … manage.py test --keepdb core.tests.test_relay_events -v1`
      Expected: FAIL — `ModuleNotFoundError: No module named 'core.relay_events'`.
- [ ] **Step 2: Create `core/relay_events.py`:**
      ```python
      """Turning the relay's posted transitions into rows and pushes.

      Phase 1 PR 6. The relay used to call log_system_event() at thirteen sites
      and Stream.save() at one; both now arrive here as
      POST /api/relay/events. This module lives in core/, not in apps/proxy/,
      for two reasons that point the same way: log_system_event's own
      implementation is here (core/utils.py), and
      scripts/metrics/collect_architecture.py counts every ORM write under
      apps/proxy/ into proxy_orm_writes, whose Phase 1 target is zero. The view
      is in apps/proxy/api_views.py (D12); the writes are here.
      """
      ```
      with:
      ```python
      # The transitions a human watching the Stats page cares about. Each also
      # becomes a SystemEvent row; the push is what stops the UI polling
      # channel_status to notice a switch.
      RELAY_WS_EVENT_TYPES = frozenset(
          {"channel_failover", "stream_switch", "client_disconnect"}
      )

      # Everything the push may carry. Never the raw details dict:
      # input/manager.py's stream_switch puts a truncated provider URL in
      # new_url, and a channel UUID is a capability against anonymous
      # /proxy/ts/stream/<uuid>. dispatcharr/consumers.py keeps the whole type
      # admin-only for the same reason it keeps channel_stats admin-only.
      _WS_FIELDS = ("channel_id", "channel_name", "client_id", "stream_id", "reason")
      ```
      **`close_old_connections` is imported at module level**, as
      `from django.db import close_old_connections` — the same place
      `services/channel_service.py:10` imports it today, and what
      `test_stream_stats_releases_the_db_connection` patches as
      `core.relay_events.close_old_connections`. A function-local import would make that patch a
      no-op that passes.
      **`apply_event_batch` normalises before it writes**: `""` becomes `None` for `channel_id`,
      `channel_name` and `client_id`, so a channel-less event reaches
      `SystemEvent.channel_id` (a `UUIDField`) as `None` rather than an empty string that
      `UUIDField.to_python` rejects.
      `apply_event_batch(events)` iterates, dispatching `stream_stats` to `_apply_stream_stats`
      (the body of `ChannelService._update_stream_stats_in_db`, moved verbatim including its
      `if value is not None` merge and its `close_old_connections()` in `finally`) and everything
      else to `log_system_event(event["type"], channel_id=..., channel_name=..., **details)`,
      then `_push(event)` when the type is in `RELAY_WS_EVENT_TYPES`:
      ```python
      def _push(event):
          payload = {"success": True, "type": "relay_event", "event": event["type"],
                     "timestamp": time.time()}
          details = event.get("details") or {}
          for field in _WS_FIELDS:
              value = event.get(field, details.get(field))
              if value is not None:
                  payload[field] = value
          send_websocket_update("updates", "update", payload)
      ```
- [ ] **Step 3: Add `channel_buffering` to `SUPPORTED_EVENTS`.** In `apps/connect/models.py`, after
      `"channel_failover": "Channel Failover",`:
      ```python
      "channel_buffering": "Channel Buffering",
      ```
      It is a real event the relay has always fired (`input/manager.py:1171`) that Connect could
      never subscribe to.
- [ ] **Step 4: Generate the migration.** `EventSubscription.event`'s `choices` is
      `list(SUPPORTED_EVENTS.items())` (`apps/connect/models.py:37`), so this is a model change.
      Run: `docker exec … manage.py makemigrations dispatcharr_connect`
      Expected: `0004_alter_eventsubscription_event.py` created. The app label is
      `dispatcharr_connect`; `makemigrations connect` would hit the Django Channels library and
      report "no changes" while exiting 0.
      Run: `docker exec … manage.py makemigrations --check --dry-run dispatcharr_connect`
      Expected: exit 0.
- [ ] **Step 5: Run.**
      Run: `docker exec … manage.py test --keepdb core.tests apps.connect.tests -v1`
      Expected: OK.
- [ ] **Step 6: Commit.** Write `msg-pr6-t5.txt`, stage exactly
      `core/relay_events.py core/tests/test_relay_events.py apps/connect/models.py apps/connect/migrations/0004_alter_eventsubscription_event.py`
      in one Bash call, then commit with `-F <path>/msg-pr6-t5.txt` in a separate call.
      Subject: `feat(phase1-pr6): Django-side event writer, channel_buffering subscribable`.

---

### Task 6: The three `/api/relay/…` routes

**Files:**
- Create: `apps/proxy/serializers.py`, `apps/proxy/api_views.py`, `apps/proxy/api_urls.py`
- Modify: `apps/api/urls.py` (after the `connect/` line)
- Test: `apps/proxy/tests/test_next_source_api.py`

**Interfaces:**
- Produces routes `relay:next-source` (`POST /api/relay/channels/<str:identifier>/next-source`),
  `relay:release` (`POST /api/relay/channels/<str:identifier>/release`), `relay:events`
  (`POST /api/relay/events`).
- Consumes `apps.proxy.permissions.IsInternalRelay`, `apps.proxy.next_source`,
  `core.relay_events.apply_event_batch`.

- [ ] **Step 1: Write the failing tests.** Create `apps/proxy/tests/test_next_source_api.py`
      (`TestCase`; build the request headers with a helper that signs like `control_plane` does):
      - `test_every_route_refuses_a_request_with_no_internal_headers` → 403 on all three.
      - `test_every_route_refuses_an_authenticated_admin_without_the_headers` → 403, proving the
        gate is not a principal check.
      - `test_next_source_returns_the_contract_fields`: 200 with `stream_id`, `url`, `user_agent`,
        `stream_profile` (`id`, `command`, `args`), `m3u_profile_id`, `transcode`, `slot_reserved`.
      - `test_next_source_reserves_a_slot_exactly_once_per_call`: read
        `profile_connections:<profile.id>` before and after; one call increments by exactly one, and
        a second call while the assignment is live increments by zero.
      - `test_next_source_answers_200_with_a_null_source_when_nothing_is_left`: exclude every stream
        → HTTP 200, `source is None`, `error` a non-empty string. Not a 4xx: the client turns every
        4xx into `ControlPlaneUnavailable` and an exhausted channel is not an outage (ruling 13).
      - `test_next_source_404s_an_unknown_identifier` — resolves to neither a `Channel` nor a
        `Stream`.
      - `test_release_gives_the_slot_back` → counter decremented, `channel_stream:` gone.
      - `test_events_turns_a_batch_into_rows` → `{"accepted": 2, "rejected": 0}` and two
        `SystemEvent` rows.
      - `test_the_three_routes_appear_in_the_openapi_schema`, in the shape of
        `apps/proxy/tests/test_authorize_view.py:134-138`:
        ```python
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        for path in (
            "/api/relay/channels/{identifier}/next-source",
            "/api/relay/channels/{identifier}/release",
            "/api/relay/events",
        ):
            self.assertIn(path, schema["paths"])
        ```
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests.test_next_source_api -v1`
      Expected: FAIL — 404 on every route.
- [ ] **Step 2: Create `apps/proxy/serializers.py`:**
      ```python
      """Wire shapes for /api/relay/... (Phase 1 PR 6, D12).

      Every request body is validated through one of these and every response
      rendered through one — CLAUDE.md § Conventions, no raw dicts. They also
      make the routes describable to drf-spectacular, which is where the
      contract in the spec's § Architecture becomes checkable.
      """

      from rest_framework import serializers


      class StreamProfileRefSerializer(serializers.Serializer):
          """A StreamProfile, flattened.

          `args` is the wire name the spec's contract uses; the model field is
          `parameters` (core/models.py:57) — a TextField of shell-style
          arguments that StreamProfile.build_command() shlex-splits. The
          `source=` keeps the wire name and the model name from having to agree.
          """

          id = serializers.IntegerField()
          command = serializers.CharField(allow_blank=True)
          args = serializers.CharField(source="parameters", allow_blank=True)


      class SourceSerializer(serializers.Serializer):
          stream_id = serializers.IntegerField()
          stream_name = serializers.CharField(allow_blank=True, allow_null=True)
          url = serializers.CharField()
          user_agent = serializers.CharField(allow_blank=True)
          transcode = serializers.BooleanField()
          m3u_profile_id = serializers.IntegerField()
          # Whether THIS call reserved a provider slot. The relay releases only
          # what it reserved; without it, views.py's error paths double-release.
          slot_reserved = serializers.BooleanField()
          stream_profile = StreamProfileRefSerializer()


      class NextSourceRequestSerializer(serializers.Serializer):
          exclude_stream_ids = serializers.ListField(
              child=serializers.IntegerField(), required=False, default=list
          )
          # The URL already playing. Django skips any candidate resolving to it,
          # which is the only reason input/manager.py used to loop candidates.
          # A body field, never a query parameter: it carries provider
          # credentials and must not reach an access log.
          current_url = serializers.CharField(
              required=False, allow_blank=True, allow_null=True, default=None
          )
          target_stream_id = serializers.IntegerField(
              required=False, allow_null=True, default=None
          )
          reason = serializers.CharField(required=False, default="initial")
          include_alternates = serializers.BooleanField(required=False, default=False)


      class NextSourceResponseSerializer(serializers.Serializer):
          source = SourceSerializer(allow_null=True)
          alternates = SourceSerializer(many=True)
          error = serializers.CharField(allow_null=True)


      class ReleaseRequestSerializer(serializers.Serializer):
          # Read by the relay out of its own metadata hash and passed in, so the
          # channel-deleted-mid-playback fallback needs no second round trip and
          # Django never reads a relay-owned key.
          stream_id = serializers.IntegerField(required=False, allow_null=True, default=None)
          m3u_profile_id = serializers.IntegerField(required=False, allow_null=True, default=None)
          channel_pk = serializers.IntegerField(required=False, allow_null=True, default=None)


      class ReleaseResponseSerializer(serializers.Serializer):
          released = serializers.BooleanField()


      class RelayEventSerializer(serializers.Serializer):
          type = serializers.CharField()
          # None, never "". SystemEvent.channel_id is a UUIDField
          # (core/models.py:803, null=True); UUIDField.to_python("") raises
          # ValidationError, and log_system_event's bare `except Exception`
          # (core/utils.py:922-924) would swallow it — no row, no Connect
          # fan-out, one error log per event. Every channel-less event hits
          # this: vod_start and vod_stop
          # (vod_proxy/multi_worker_connection_manager.py:902) carry no channel
          # at all, and they are written today.
          channel_id = serializers.CharField(
              required=False, allow_null=True, default=None
          )
          channel_name = serializers.CharField(
              required=False, allow_null=True, default=None
          )
          client_id = serializers.CharField(
              required=False, allow_null=True, default=None
          )
          stream_id = serializers.IntegerField(required=False, allow_null=True, default=None)
          details = serializers.DictField(required=False, default=dict)


      class RelayEventBatchSerializer(serializers.Serializer):
          events = RelayEventSerializer(many=True, max_length=200)


      class RelayEventResponseSerializer(serializers.Serializer):
          accepted = serializers.IntegerField()
          rejected = serializers.IntegerField()
      ```
- [ ] **Step 3: Create `apps/proxy/api_views.py`:**
      ```python
      """The three internal routes the relay calls (Phase 1 PR 6, D12).

      Gated by IsInternalRelay -- the two internal HMAC headers, never a DRF or
      session principal, never IsAdmin (which would need a resolved User, the
      one thing these hops must not need).

      No ORM write appears in this file, deliberately: the event batch's
      log_system_event() calls and the one Stream.save() live in
      core/relay_events.py, because scripts/metrics/collect_architecture.py
      counts every write under apps/proxy/ into proxy_orm_writes, whose Phase 1
      target is zero, and because the spec's Done grep runs over this directory.
      """

      import logging

      from django.http import Http404
      from drf_spectacular.utils import extend_schema
      from rest_framework import status
      from rest_framework.decorators import (
          api_view,
          authentication_classes,
          permission_classes,
      )
      from rest_framework.response import Response

      from apps.proxy import next_source
      from apps.proxy.permissions import IsInternalRelay
      from apps.proxy.serializers import (
          NextSourceRequestSerializer,
          NextSourceResponseSerializer,
          RelayEventBatchSerializer,
          RelayEventResponseSerializer,
          ReleaseRequestSerializer,
          ReleaseResponseSerializer,
      )
      from core.relay_events import apply_event_batch

      logger = logging.getLogger(__name__)


      @extend_schema(
          operation_id="internal_relay_next_source",
          description=(
              "Internal. The relay asks which stream to play next: at the initial "
              "tune, at a failover, and when an operator names a target. Django "
              "runs Channel.get_stream() and moves the provider slot; the relay "
              "never chooses. Not part of the client API."
          ),
          request=NextSourceRequestSerializer,
          responses={200: NextSourceResponseSerializer},
          tags=["internal"],
      )
      @api_view(["POST"])
      @authentication_classes([])
      @permission_classes([IsInternalRelay])
      def next_source_view(request, identifier):
          payload = NextSourceRequestSerializer(data=request.data)
          payload.is_valid(raise_exception=True)
          try:
              answer = next_source.resolve_source(identifier, **payload.validated_data)
          except Http404:
              # Neither a Channel by uuid nor a Stream by stream_hash. The only
              # 4xx this route answers: "no candidate available" is a 200 with a
              # null source, because the client turns every 4xx into a refusal
              # and an exhausted channel is not a refusal (rulings 13 and 15).
              return Response(
                  {"error": "identifier not found"}, status=status.HTTP_404_NOT_FOUND
              )
          return Response(NextSourceResponseSerializer(answer).data)


      @extend_schema(
          operation_id="internal_relay_release_source",
          description=(
              "Internal. Give the provider slot back. The optional ids are what "
              "the relay read out of its own metadata hash, used when the Channel "
              "row was deleted mid-playback and neither ORM release can run."
          ),
          request=ReleaseRequestSerializer,
          responses={200: ReleaseResponseSerializer},
          tags=["internal"],
      )
      @api_view(["POST"])
      @authentication_classes([])
      @permission_classes([IsInternalRelay])
      def release_view(request, identifier):
          payload = ReleaseRequestSerializer(data=request.data)
          payload.is_valid(raise_exception=True)
          released = next_source.release_source(identifier, **payload.validated_data)
          return Response(ReleaseResponseSerializer({"released": released}).data)


      @extend_schema(
          operation_id="internal_relay_events",
          description=(
              "Internal. A batch of relay transitions. Each becomes a SystemEvent "
              "row and a Connect fan-out; the three UI-visible types also push a "
              "relay_event WebSocket message. stream_stats is the exception: it "
              "writes the Stream row and no event row."
          ),
          request=RelayEventBatchSerializer,
          responses={200: RelayEventResponseSerializer},
          tags=["internal"],
      )
      @api_view(["POST"])
      @authentication_classes([])
      @permission_classes([IsInternalRelay])
      def events_view(request):
          payload = RelayEventBatchSerializer(data=request.data)
          payload.is_valid(raise_exception=True)
          counts = apply_event_batch(payload.validated_data["events"])
          return Response(RelayEventResponseSerializer(counts).data)
      ```
      The `@extend_schema` blocks follow `apps/proxy/authorize_views.py:209-232`'s shape.
      **No `log_system_event(`, no `.save(`, no `.objects.create(` may appear in this file** — the
      Done grep and `proxy_orm_writes` both read it.
- [ ] **Step 4: Create `apps/proxy/api_urls.py`:**
      ```python
      """Internal control-plane routes the relay calls (Phase 1 D12).

      Mounted at /api/relay/ from apps/api/urls.py. Not part of the client API:
      IsInternalRelay, no principal, no IsAdmin. nginx serves them through the
      existing `location ^~ /api/` block, which carries the blanking include —
      it blanks the five X-Relay-* trust params and leaves the two internal
      headers alone, which is exactly right here.
      """

      from django.urls import path

      from apps.proxy import api_views

      app_name = "relay"

      urlpatterns = [
          path(
              "channels/<str:identifier>/next-source",
              api_views.next_source_view,
              name="next-source",
          ),
          path(
              "channels/<str:identifier>/release",
              api_views.release_view,
              name="release",
          ),
          path("events", api_views.events_view, name="events"),
      ]
      ```
      **The identifier is a channel UUID or a `stream_hash`**, matching `get_stream_object` and the
      `<str:channel_id>` convention every `live_proxy` route already uses.
- [ ] **Step 5: Mount it.** In `apps/api/urls.py`, after the `connect/` entry:
      ```python
      path('relay/', include(('apps.proxy.api_urls', 'relay'), namespace='relay')),
      ```
- [ ] **Step 6: Run.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests -v1`
      Expected: OK.
      Run: `docker exec … manage.py spectacular --validate --fail-on-warn --file /dev/null`
      Expected: exit 0, no output.
- [ ] **Step 7: Commit.** Write `msg-pr6-t6.txt`, stage exactly
      `apps/proxy/serializers.py apps/proxy/api_views.py apps/proxy/api_urls.py apps/api/urls.py apps/proxy/tests/test_next_source_api.py`
      in one Bash call, then commit with `-F <path>/msg-pr6-t6.txt` in a separate call.
      Subject: `feat(phase1-pr6): /api/relay next-source, release and events`.

---

### Task 7: Point the relay's tune path at the control plane

**Files:**
- Modify: `apps/proxy/live_proxy/url_utils.py` — `generate_stream_url` body
- Modify: `apps/proxy/live_proxy/views.py:32-33` (imports), `:449-500` (the redirect-alternates
  loop), `:869`, `:1157`
- Modify: `apps/proxy/live_proxy/services/channel_service.py:16` (import), `:384`
- Test: `apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py` (unchanged — it must still pass)

**Interfaces:**
- Consumes `apps.proxy.control_plane.next_source`, `ControlPlaneRefused`, `ControlPlaneUnavailable`,
  `apps.proxy.next_source.resolve_source`.
- Produces `url_utils._cache_alternates(channel_id, alternates)` and
  `url_utils.read_cached_alternates(channel_id) -> list[dict]`; `generate_stream_url` keeps its
  exact name and 6-tuple.
- **Neither error string may reach a viewer as a stream failure the retry loop misreads:**
  `stream_ts` branches on `"maximum connection limits" not in error_reason` (`views.py:336`) to
  decide whether to retry, and neither of these two contains it, so both stop the retry immediately —
  which is right, because retrying a refusal or an outage inside three seconds changes nothing.

- [ ] **Step 1: Make `generate_stream_url` cross the boundary and seed the fallback cache.**
      Replace the Task 3 body with:
      ```python
      def generate_stream_url(channel_id):
          """Ask Django what to play. Same 6-tuple every caller already reads.

          Phase 1 PR 6: the resolution runs in the API process now
          (apps/proxy/next_source.py). The alternates that come back are cached
          in Redis so a failover during a Django outage has something to fall
          back to — unenforced, no reservation, exactly as the spec's degraded
          fallback states.
          """
          from apps.proxy import control_plane

          try:
              answer = control_plane.next_source(
                  channel_id, reason="initial", include_alternates=True
              )
          except control_plane.ControlPlaneRefused as exc:
              # Django said no — a deleted channel, a token fault. Distinct from
              # an outage so a refusal never looks like one (ruling 15).
              logger.error(
                  f"Control plane refused the tune for channel {channel_id}: "
                  f"{exc.status}"
              )
              return None, None, False, None, False, "Control plane refused this channel"
          except control_plane.ControlPlaneUnavailable as exc:
              logger.error(f"Control plane unreachable for channel {channel_id}: {exc}")
              return None, None, False, None, False, "Control plane unreachable"

          source = answer.get("source")
          if source is None:
              return None, None, False, None, False, answer.get("error")

          _cache_alternates(channel_id, answer.get("alternates") or [])
          return (
              source["url"],
              source["user_agent"],
              source["transcode"],
              source["stream_profile"]["id"],
              source["slot_reserved"],
              None,
          )


      def _cache_alternates(channel_id, alternates):
          """Store resolved candidates for the degraded failover path.

          In Redis, not on any object: four uWSGI workers and no channel state
          in Python memory. TTL matches the metadata hash's REDIS_TTL_DEFAULT,
          so a dead channel's cache expires on its own like every other key
          (D15 — nothing flushes Redis).
          """
          if not alternates:
              return
          try:
              from core.utils import RedisClient
              from .constants import REDIS_TTL_DEFAULT

              client = RedisClient.get_client()
              if client:
                  client.set(
                      RedisKeys.channel_source_cache(channel_id),
                      json.dumps(alternates),
                      ex=REDIS_TTL_DEFAULT,
                  )
          except Exception as exc:
              logger.debug(f"Could not cache alternates for {channel_id}: {exc}")
      ```
      Add `import json` and `from .redis_keys import RedisKeys` to `url_utils.py`'s imports.
- [ ] **Step 2: Rewrite the redirect-alternates loop in `views.py`.** In `stream_ts`, the branch at
      `views.py:449-500` imports `get_alternate_streams` and `get_stream_info_for_switch` to find a
      redirect target that validates. It now reads the cached alternates
      `generate_stream_url` just wrote — the same candidates, already resolved:
      ```python
      # Phase 1 PR 6: the alternates were resolved by Django on the
      # next-source call a few lines above and cached in Redis; the
      # relay no longer re-queries for them. Validation of each URL
      # stays here, because it is an HTTP probe of the provider, not a
      # database question.
      from .url_utils import validate_stream_url, read_cached_alternates

      # (the primary-URL validation above this point is unchanged)
      tried_streams = {stream_id}
      for alt in read_cached_alternates(channel_id):
          if alt["stream_id"] in tried_streams:
              continue
          tried_streams.add(alt["stream_id"])
          logger.info(
              f"[{client_id}] Trying alternate stream #{alt['stream_id']}"
          )
          is_valid, final_url, status_code, message = validate_stream_url(
              alt["url"], user_agent=alt["user_agent"], timeout=(5, 5)
          )
          if is_valid:
              logger.info(
                  f"[{client_id}] Alternate stream #{alt['stream_id']} validated"
              )
              break
          logger.warning(
              f"[{client_id}] Alternate stream #{alt['stream_id']} failed "
              f"validation: {message}"
          )
      # (the release-then-redirect tail below this point is unchanged)
      ```
      The two log lines that named `alt_info['url']` (`views.py:490`) lose the URL: it is a provider
      URL and `scripts/check_credential_logging.py` matches a log call naming one. Everything from
      `# Release stream lock before redirecting` onward stays exactly as it is.
      Add `read_cached_alternates(channel_id) -> list[dict]` to `url_utils.py` beside
      `_cache_alternates` (read the key, `json.loads`, return `[]` on anything unexpected). Delete
      the `get_alternate_streams`/`get_stream_info_for_switch` import from that branch and from
      `views.py:32-33`.
- [ ] **Step 3: Point the two API-process views at `next_source` directly.** `views.py:869`
      (`change_stream`) and `views.py:1157` (`next_stream`) run in the API process after PR 4's
      routing (`location = /proxy/ts/change_stream/` and friends stay on the API). Replace
      `get_stream_info_for_switch(channel_id, stream_id)` with:
      ```python
      from apps.proxy.next_source import resolve_source

      answer = resolve_source(channel_id, target_stream_id=stream_id, reason="operator")
      stream_info = answer["source"] or {"error": answer["error"]}
      ```
      keeping every downstream check on `stream_info` exactly as it is. Do the same at
      `services/channel_service.py:384` inside `change_stream_url`, and delete the
      `from ..url_utils import get_stream_info_for_switch` import at `channel_service.py:16`.
      **Comment each site** with: this is API-process code today; PR 7 turns these views into
      `relay_client` wrappers, at which point `change_stream_url` runs in the relay and PR 7 revisits
      the call (D10).
- [ ] **Step 4: Run.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests -v1`
      Expected: OK. `test_ghost_session_cleanup.py` still patches
      `apps.proxy.live_proxy.views.generate_stream_url` and must pass untouched — if it does not,
      the 6-tuple or the symbol moved and Step 1 is wrong.
- [ ] **Step 5: Commit.** Write `msg-pr6-t7.txt`, stage exactly
      `apps/proxy/live_proxy/url_utils.py apps/proxy/live_proxy/views.py apps/proxy/live_proxy/services/channel_service.py`
      in one Bash call, then commit with `-F <path>/msg-pr6-t7.txt` in a separate call.
      Subject: `refactor(phase1-pr6): the tune path asks Django for its source`.

---

### Task 8: Failover asks for its next source

**Files:**
- Modify: `apps/proxy/live_proxy/input/manager.py:19` (import), `:1414-1450` (`update_url`'s ORM
  block), `:1986-2085` (`_try_next_stream`)
- Modify: `apps/proxy/live_proxy/services/channel_service.py:105-175` (`cancel_pending_shutdown`)
- Test: `apps/proxy/live_proxy/tests/test_try_next_stream.py`

**Interfaces:**
- Consumes `apps.proxy.control_plane.next_source`, `ControlPlaneUnavailable`,
  `ControlPlaneRefused`, `url_utils.read_cached_alternates`.
- Produces no new public symbol; `_try_next_stream` keeps returning `bool`.
- **Removes** the three transitional aliases Task 3 left in `url_utils.py` (Step 5), once no
  importer is left.

- [ ] **Step 1: Write the failing tests.** Create
      `apps/proxy/live_proxy/tests/test_try_next_stream.py` (`SimpleTestCase` with a hand-built
      `StreamManager`-shaped object is not possible — use `TestCase` and a real `StreamManager`
      constructed the way `apps/proxy/live_proxy/tests/test_vlc_failover.py` builds one; copy that
      construction rather than inventing another):
      - `test_failover_makes_one_next_source_call_carrying_what_it_has_tried`: patch
        `apps.proxy.control_plane.next_source`; assert it was called once with
        `exclude_stream_ids` containing the current and previously tried ids, `current_url` equal to
        `manager.url`, and `reason="failover"`.
      - `test_the_returned_source_is_applied_without_a_second_call`: the answer's URL is adopted,
        `current_stream_id` updated, the metadata hash carries `STREAM_ID`, `M3U_PROFILE`,
        `STREAM_PROFILE`, `STREAM_SWITCH_TIME` and `STREAM_SWITCH_REASON`.
      - `test_no_source_left_returns_false`: `{"source": None, "error": "…"}` → `False`, and no
        metadata write.
      - `test_the_degraded_path_uses_the_cached_alternates_and_reserves_nothing`: `next_source`
        raises `ControlPlaneUnavailable`, the Redis cache holds two candidates, the first untried
        one is adopted, `logger.warning` fired, and `control_plane.release_source` /
        `next_source` were not called again.
      - `test_the_degraded_path_skips_the_current_url`: the cache's first entry has the manager's
        own URL; the second is chosen.
      - `test_a_channel_error_event_is_posted_once_django_answers_again`: after a degraded failover,
        the next successful `next_source` call is followed by an `emit_event("channel_error", …)`
        naming the degradation.
      - `test_a_404_ends_the_switch_attempt_rather_than_degrading`: `next_source` returns
        `{"source": None, "alternates": [], "error": "identifier not found"}` (what the client makes
        of a 404 — the channel was deleted mid-playback); `_try_next_stream` returns `False` and the
        cached list is **not** read. This is what `get_alternate_streams` does today by catching the
        `Http404`.
      - `test_a_403_never_triggers_the_degraded_fallback`: `next_source` raises
        `ControlPlaneRefused(403, …)`; `_try_next_stream` returns `False`, logs at ERROR with the
        status, and does not touch `read_cached_alternates`. A `SECRET_KEY` mismatch between the api
        and relay roles must fail loudly on the first failover, not degrade every failover on the
        deployment silently and forever.
      Run: `docker exec … manage.py test --keepdb apps.proxy.live_proxy.tests.test_try_next_stream -v1`
      Expected: FAIL — the new behaviour does not exist.
- [ ] **Step 2: Rewrite `_try_next_stream`.** Replace `manager.py:1986-2085` with a single call and
      one application block. Keep `self.tried_stream_ids` (it is what makes repeated failovers
      converge) and keep the metadata write verbatim, sourced from the answer:
      ```python
      def _try_next_stream(self):
          """Ask Django for the next stream and adopt it.

          Phase 1 PR 6: this used to be get_alternate_streams() plus a
          get_stream_info_for_switch() per candidate, looping until one
          resolved to a URL different from the current one. Django does the
          whole traversal now — current_url is what lets it, since rejecting a
          candidate that resolves to the URL already playing was the only
          reason the loop had to be here.
          """
          from apps.proxy import control_plane
          from ..url_utils import read_cached_alternates

          exclude = set(self.tried_stream_ids)
          if self.current_stream_id:
              exclude.add(self.current_stream_id)

          degraded = False
          try:
              answer = control_plane.next_source(
                  self.channel_id,
                  exclude_stream_ids=sorted(exclude),
                  current_url=self.url,
                  reason="failover",
              )
              source = answer.get("source")
          except control_plane.ControlPlaneRefused as exc:
              # Django answered, and said no: a deleted channel, a bad token, a
              # SECRET_KEY mismatch between roles. Never degrade on a refusal —
              # the cached list would keep a deleted channel streaming, and a
              # token fault would make every failover on the deployment degrade
              # forever instead of failing once, loudly. Today's equivalent is
              # get_alternate_streams catching Http404 and returning [].
              logger.error(
                  f"Control plane refused the failover for channel "
                  f"{self.channel_id} with {exc.status}"
              )
              return False
          except control_plane.ControlPlaneUnavailable as exc:
              # Degraded fallback: the candidate list cached at channel start.
              # Stale, unenforced, and no slot moves — refusing to fail over at
              # all is worse for the viewer, and the channel_error event below
              # makes it visible after the fact.
              logger.warning(
                  f"Control plane unreachable during failover for channel "
                  f"{self.channel_id}: {exc}; using the cached candidate list "
                  f"unenforced"
              )
              degraded = True
              source = self._pick_cached_alternate(read_cached_alternates(self.channel_id), exclude)

          if not source:
              logger.error(f"No alternate stream available for channel {self.channel_id}")
              return False

          stream_id = source["stream_id"]
          profile_id = source["m3u_profile_id"]
          self.tried_stream_ids.add(stream_id)
          logger.info(
              f"Switching channel {self.channel_id} to stream {stream_id} "
              f"with M3U profile {profile_id}"
          )

          if not self.update_url(source["url"], stream_id, profile_id):
              # Unreachable from here since Phase 1 PR 6: update_url's only
              # False branch is "the URL did not change", and Django was given
              # current_url precisely so it never answers with it.
              logger.error(
                  f"Failed to update URL for stream {stream_id} on channel "
                  f"{self.channel_id}"
              )
              return False

          self.current_stream_id = stream_id
          self.user_agent = source["user_agent"]
          self.transcode = source["transcode"]

          if hasattr(self.buffer, "redis_client") and self.buffer.redis_client:
              self.buffer.redis_client.hset(
                  RedisKeys.channel_metadata(self.channel_id),
                  mapping={
                      ChannelMetadataField.URL: source["url"],
                      ChannelMetadataField.USER_AGENT: source["user_agent"],
                      ChannelMetadataField.STREAM_PROFILE: str(source["stream_profile"]["id"]),
                      ChannelMetadataField.M3U_PROFILE: str(profile_id),
                      ChannelMetadataField.STREAM_ID: str(stream_id),
                      ChannelMetadataField.STREAM_SWITCH_TIME: str(time.time()),
                      ChannelMetadataField.STREAM_SWITCH_REASON: "max_retries_exceeded",
                  },
              )

          if degraded:
              self._failover_degraded = True
          elif self._failover_degraded:
              # Django is answering again: say, once, that an earlier failover
              # ran blind on the cached list and may have exceeded max_streams.
              self._failover_degraded = False
              emit_event(
                  "channel_error",
                  channel_id=self.channel_id,
                  channel_name=self.channel_name,
                  reason="degraded_failover",
              )

          logger.info(
              f"Successfully switched channel {self.channel_id} to stream {stream_id}"
          )
          return True
      ```
      `RedisKeys`, `ChannelMetadataField` and `time` are already imported in this module; the
      metadata mapping is today's (`manager.py:2062-2069`) with its values taken from `source`.
      `_pick_cached_alternate(alternates, exclude)` is a new private method: the first entry whose
      `stream_id` is not in `exclude` and whose `url` differs from `self.url`, else `None`.
      `self._failover_degraded` is a per-manager bool initialised to `False` in `__init__` beside
      `self.tried_stream_ids` — not channel state, and correctly lost with the process, since it
      means "this manager failed over blind".
      **Two import edits in `manager.py` in this task.** Add
      `from apps.proxy.control_plane import emit_event` to the module imports beside the existing
      `from core.utils import log_system_event` (Task 10 removes the latter once this file's other
      seven call sites have moved). And trim `:19` from
      `from ..url_utils import get_alternate_streams, get_stream_info_for_switch, get_stream_object`
      to `from ..url_utils import get_stream_object` — this step deletes the only uses of the other
      two in the file, and Step 5 cannot delete the aliases while an importer still names them.
- [ ] **Step 3: Delete `update_url`'s ORM block.** Remove `manager.py:1422-1450` — the
      `from apps.channels.models import Stream, Channel` and `from django.db import connection`
      imports, the `Channel.objects.get(uuid=...)` and the
      `channel.update_stream_profile(m3u_profile_id)` call with its `try/except/finally`. Leave a
      comment in its place:
      ```python
      # The provider slot moves in Django now, inside the next-source answer
      # that named this stream (Phase 1 PR 6, spec § PR 6: "input/manager.py's
      # update_stream_profile moves into Django's next-source handling, where
      # the credential-slot move already belongs"). Nothing to do here.
      ```
      `update_url`'s `if new_url == self.url: return False` guard stays — it is now unreachable from
      the failover path (Django never returns the current URL) but it still guards
      `change_stream_url`'s operator path.
- [ ] **Step 4: Rewrite `cancel_pending_shutdown`'s re-reservation.** In
      `services/channel_service.py`, replace the `Channel.objects.filter(uuid=channel_id).first()`
      / `channel.get_stream()` block (`:154-172`) with:
      ```python
      from apps.proxy import control_plane

      try:
          answer = control_plane.next_source(channel_id, reason="resume")
      except (control_plane.ControlPlaneRefused, control_plane.ControlPlaneUnavailable) as exc:
          # Both end the re-reservation, and neither is fatal: the channel is
          # still running on the slot it already holds. Only the reasons differ,
          # which is why the exception object goes in the message.
          logger.warning(
              f"Could not re-reserve stream for {channel_id} after shutdown "
              f"cancel: {exc}"
          )
      else:
          source = answer.get("source")
          if source is None:
              logger.warning(
                  f"Could not re-reserve stream for {channel_id} after shutdown "
                  f"cancel: {answer.get('error')}"
              )
          elif source["slot_reserved"]:
              proxy_server.redis_client.hset(metadata_key, mapping={
                  ChannelMetadataField.STREAM_ID: str(source["stream_id"]),
                  ChannelMetadataField.M3U_PROFILE: str(source["m3u_profile_id"]),
              })
              logger.info(
                  f"Re-reserved profile slot for {channel_id} "
                  f"(stream={source['stream_id']}, profile={source['m3u_profile_id']})"
              )
      ```
      The `if not redis.get(f"channel_stream:{channel.id}")` guard goes with the ORM read it
      needed: `Channel.get_stream()` already reuses a live assignment and reports
      `slot_reserved=False` for it, which is the same decision expressed once instead of twice.
- [ ] **Step 5: Delete the transitional aliases.** Every importer of the three names Task 3 aliased
      has now been rewritten — `views.py` in Task 7 Steps 2-3, `input/manager.py` in Step 2 above,
      `services/channel_service.py` in Task 7 Step 3 and Step 4 above. Prove it, then remove them.
      Run, excluding the alias lines themselves — they name all three, so an unfiltered grep here
      would always hit and the "a call site was missed" reading would misfire:
      `grep -rn "get_alternate_streams\|get_stream_info_for_switch\|order_alternates_from_current" apps/ core/ dispatcharr/ | grep -v "/tests/" | grep -v "apps/proxy/next_source.py" | grep -v "live_proxy/url_utils.py"`
      Expected: **no output**. If a hit remains, that call site was missed — fix it before deleting
      the alias, never the other way round.
      Then delete from `apps/proxy/live_proxy/url_utils.py` the four-line import Task 3 marked
      `# noqa: F401  transitional, deleted in Task 8`, keeping the permanent
      `get_stream_object, transform_url` re-export above it and its first paragraph. Delete that
      comment's second paragraph, which describes an arrangement that no longer exists.
      Run the same grep again, now **unfiltered** — the aliases are gone, so nothing outside
      `next_source.py` may name them:
      `grep -rn "get_alternate_streams\|get_stream_info_for_switch\|order_alternates_from_current" apps/ core/ dispatcharr/ | grep -v "/tests/" | grep -v "apps/proxy/next_source.py"`
      Expected: no output.
      Run: `grep -n "transitional" apps/proxy/live_proxy/url_utils.py`
      Expected: no output.
- [ ] **Step 6: Run.**
      Run: `docker exec … manage.py check`
      Expected: `System check identified no issues` — the alias deletion's import proof.
      Run: `docker exec … manage.py test --keepdb apps.proxy.live_proxy.tests apps.proxy.tests apps.channels.tests -v1`
      Expected: OK.
- [ ] **Step 7: Commit.** Write `msg-pr6-t8.txt`, stage exactly
      `apps/proxy/live_proxy/input/manager.py apps/proxy/live_proxy/url_utils.py apps/proxy/live_proxy/views.py apps/proxy/live_proxy/services/channel_service.py apps/proxy/live_proxy/tests/test_try_next_stream.py`
      in one Bash call, then commit with `-F <path>/msg-pr6-t8.txt` in a separate call.
      Subject: `refactor(phase1-pr6): failover asks Django for its next source`.

---

### Task 9: One writer for `channel_stream:*` and `stream_profile:*`

**Files:**
- Modify: `apps/proxy/live_proxy/server.py:2320-2385` (the two deletes and both `release_stream()`
  calls), `apps/proxy/live_proxy/views.py:383,510,539,560,785`,
  `apps/proxy/live_proxy/output/ts/generator.py:614-624`,
  `apps/proxy/live_proxy/output/fmp4/generator.py:374-384`
- Modify: `apps/proxy/live_proxy/redis_keys.py` — add `channel_stream` and `stream_profile`
- Modify: `apps/channels/models.py` (every `f"channel_stream:…"` / `f"stream_profile:…"`),
  `core/utils.py:778,811`, and the relay's remaining reads
  (`views.py:411,414`, `next_source.py`'s moved copies, `channel_service.py`)
- Modify: `apps/proxy/live_proxy/tests/test_atomic_db_close.py:11-31` —
  `CleanRedisKeysUsesStandardCloseTests` patches `apps.proxy.live_proxy.server.Channel.objects.get`
  and `…Stream.objects.get` (`:12-13`), the import Step 3 deletes, so it too must be retargeted
  **in this task** (Step 5) rather than in Task 10, which touches only the other class in that file
  one commit later.
- Modify: `apps/channels/tests/test_ts_proxy_teardown.py:433-505` — `CleanRedisKeysOrderTests`'s
  two methods pin the release path this task rewrites and **must be retargeted in this task**
  (Step 5), not left to fail: `test_clean_redis_keys_releases_profile_slot_before_live_keys_deleted`
  (`:435-468`) patches `apps.proxy.live_proxy.server.Channel.objects.get` and asserts
  `channel.release_stream.assert_called_once()`; `..._from_metadata_when_channel_gone` (`:470-505`)
  patches `apps.m3u.connection_pool.release_profile_slot` and asserts
  `delete("channel_stream:224")` / `delete("stream_profile:2243070")` on the relay's Redis client.
  Both break the moment the relay stops calling the ORM and stops deleting those keys.
- Test: `apps/proxy/live_proxy/tests/test_live_db_cleanup.py` (existing — must still pass)

**Interfaces:**
- Produces `RedisKeys.channel_stream(channel_pk)`, `RedisKeys.stream_profile(stream_id)`.
- Consumes `apps.proxy.control_plane.release_source`.

- [ ] **Step 1: Add the two key helpers** to `apps/proxy/live_proxy/redis_keys.py`:
      ```python
      # Written only by apps/channels/models.py — Channel.get_stream(),
      # release_stream(), update_stream_profile() — and reached only through
      # apps/proxy/next_source.py since Phase 1 PR 6. They were hand-rolled
      # f-strings on both sides of the boundary, which is what made them
      # split-brain; naming them here is what makes a second writer visible.
      @staticmethod
      def channel_stream(channel_pk):
          """Stream id currently assigned to this channel (numeric channel pk)."""
          return f"channel_stream:{channel_pk}"

      @staticmethod
      def stream_profile(stream_id):
          """M3U account profile id serving this stream."""
          return f"stream_profile:{stream_id}"
      ```
      Note the argument is the channel's **numeric primary key**, not its UUID — every existing
      site passes `self.id` / `channel.id`. Say so in the docstring so the next reader cannot get
      it wrong.
- [ ] **Step 2: Convert every f-string site to the helper.** `apps/channels/models.py`
      (lines 228, 253-254, 271, 275, 279, 645, 652, 689-690, 711, 723, 781-782, 842, 863-864, 883,
      888, 892, 894, 946, 954, 995 — re-derive the list with
      `grep -n "channel_stream:\|stream_profile:" apps/channels/models.py`), `core/utils.py:778,811`
      (function-local `from apps.proxy.live_proxy.redis_keys import RedisKeys`, the same shape
      `dispatch_event_system` already uses for its other imports), and the relay's remaining reads.
      This is mechanical; the tests that cover it are `apps.channels.tests` and
      `apps.proxy.live_proxy.tests`.
- [ ] **Step 3: Collapse `server.py`'s two release paths into one call carrying the metadata ids.**
      `_release_stream_resources` (`server.py:2356-2386`) tries `Channel.release_stream()`, then
      `Stream.release_stream()`, then `_release_profile_slot_from_redis_metadata`
      (`:2300-2354`). Django now owns all three, so the relay must not make three round trips — or
      even two. Read the metadata ids **first** (that hash is the relay's own key) and send one
      request:
      ```python
      def _release_stream_resources(self, channel_id):
          """Ask Django to release the provider slot.

          Phase 1 PR 6: the three-step fallback — Channel, then Stream, then
          the ids in this channel's own metadata hash for a channel deleted
          mid-playback — moved to apps/proxy/next_source.release_source(). The
          metadata READ stays here, because that hash is relay state and PR 7
          takes the control plane out of relay keys entirely; only the ids
          cross. One call, not one per fallback rung.
          """
          from apps.proxy import control_plane

          metadata_key = RedisKeys.channel_metadata(channel_id)
          stream_id = self._redis_field_to_str(
              self.redis_client.hget(metadata_key, ChannelMetadataField.STREAM_ID)
          )
          m3u_profile_id = self._redis_field_to_str(
              self.redis_client.hget(metadata_key, ChannelMetadataField.M3U_PROFILE)
          )
          channel_pk = self._redis_field_to_str(
              self.redis_client.hget(metadata_key, ChannelMetadataField.CHANNEL_ID)
          )

          try:
              released = control_plane.release_source(
                  channel_id,
                  stream_id=_int_or_none(stream_id),
                  m3u_profile_id=_int_or_none(m3u_profile_id),
                  channel_pk=_int_or_none(channel_pk),
              )
          except control_plane.ControlPlaneRefused as exc:
              logger.warning(
                  f"Channel {channel_id}: control plane refused the release "
                  f"({exc.status}); profile slot stays counted"
              )
              return False
          except control_plane.ControlPlaneUnavailable as exc:
              logger.warning(
                  f"Channel {channel_id}: control plane unreachable for release; "
                  f"profile slot stays counted: {exc}"
              )
              return False

          if released:
              self.redis_client.hdel(
                  metadata_key,
                  ChannelMetadataField.STREAM_ID,
                  ChannelMetadataField.M3U_PROFILE,
              )
          return released
      ```
      with `_int_or_none(value)` a module-level helper that returns `int(value)` and `None` on
      `ValueError`/`TypeError` — not a bare `int()`. The retargeted teardown test drives this method
      with a `MagicMock` Redis client whose `hget` returns `MagicMock` objects for fields its
      `side_effect` does not map, and `int(MagicMock)` raises `TypeError`; the production path can
      also see a truncated or absent metadata field. Delete
      `_release_profile_slot_from_redis_metadata` entirely — its two `delete()` calls and its
      `release_profile_slot(...)` are now `next_source.release_source`'s (Task 3 Step 2), and its
      `hdel` of the relay's own metadata fields is the four lines kept above. Then remove two
      now-unused imports from `server.py`: `release_profile_slot`, and **`from apps.channels.models
      import Channel, Stream` at `:18`** — `_release_stream_resources` was its only consumer
      (`:2363-2377`, verified with `grep -n "Channel\.\|Stream\." server.py`), and leaving a dead
      ORM import in the relay's largest module is exactly the kind of thing the extraction is meant
      to remove. Removing it is also why the next step drops two `@patch` decorators rather than
      retargeting them: `patch("apps.proxy.live_proxy.server.Channel.objects.get")` raises
      `AttributeError` at decoration time once the name is gone.
- [ ] **Step 4: Convert the other eight relay `release_stream()` calls.**
      `views.py:383,510,539,560,785`, `output/ts/generator.py:621`,
      `output/fmp4/generator.py:381`. Each becomes:
      ```python
      from apps.proxy import control_plane

      try:
          released = control_plane.release_source(<identifier>)
      except (control_plane.ControlPlaneRefused, control_plane.ControlPlaneUnavailable) as exc:
          logger.warning(f"Could not release the slot for {<identifier>}: {exc}")
          released = False
      ```
      keeping the existing `if not released: logger…` line at each site verbatim. In both
      generators this replaces the `Channel.objects.get` / `Stream.objects.get` pair as well —
      `release_source` resolves the identifier itself, so `obj = Channel.objects.get(...)` and its
      `except Channel.DoesNotExist: obj = Stream.objects.get(...)` fallback go with it.
- [ ] **Step 5: Retarget the two teardown pins this task rewrites.** In
      `apps/channels/tests/test_ts_proxy_teardown.py`'s `CleanRedisKeysOrderTests` (`:433-505`):
      - `test_clean_redis_keys_releases_profile_slot_before_live_keys_deleted` (`:435-468`) keeps its
        whole point — the slot is released **before** the Redis scan deletes the live keys, or the
        release loses the data it needs. Replace the two `@patch(…server.Channel.objects.get)` and
        `(…server.Stream.objects.get)` decorators with a single
        `@patch("apps.proxy.control_plane.release_source", return_value=True)`, append `"release"` to
        `call_order` from its `side_effect`, and keep
        `self.assertEqual(call_order, ["release", "redis", "redis"])` exactly as it is. Replace
        `channel.release_stream.assert_called_once()` with `mock_release.assert_called_once()`.
      - `..._from_metadata_when_channel_gone` (`:470-505`) keeps its point too — a delete-without-stop
        must still free the slot from the metadata hash. Drop the
        `@patch("apps.m3u.connection_pool.release_profile_slot")` and the two
        `assert_any_call("channel_stream:224")` / `("stream_profile:2243070")` assertions on the
        relay's Redis client, which are Django's writes now; keep the `hget` side effect and assert
        instead that `control_plane.release_source` was called once with
        `stream_id=2243070, m3u_profile_id=50, channel_pk=224`. Same property, expressed on the new
        side of the boundary: the ids the relay found in its own metadata reach the releaser.
        **Drop both `@patch("apps.proxy.live_proxy.server.Channel.objects.get")` and
        `…Stream.objects.get` decorators here too**, and their parameters, along with the
        `Channel.DoesNotExist` / `Stream.DoesNotExist` side effects: Step 3 deletes that import from
        `server.py`, so `patch()` on those attributes raises `AttributeError` before the test body
        runs. Replace them with the single
        `@patch("apps.proxy.control_plane.release_source", return_value=True)` this assertion needs.
      - `apps/proxy/live_proxy/tests/test_atomic_db_close.py:11-31`
        (`CleanRedisKeysUsesStandardCloseTests`) is the third pin Step 3's import deletion breaks,
        and it is in a different file from the two above. It pins `_clean_redis_keys`'s
        `finally: close_old_connections()` (`server.py:2419-2420`), which this task does not touch —
        so keep the assertion and fix only the patching. Drop both
        `@patch("apps.proxy.live_proxy.server.Stream.objects.get", …)` and
        `@patch("apps.proxy.live_proxy.server.Channel.objects.get", …)` (`:12-13`) and their two
        `_channel_get` / `_stream_get` parameters, and add
        `@patch("apps.proxy.control_plane.release_source", return_value=False)` in their place so
        `_release_stream_resources` attempts no HTTP call. `mock_close.assert_called()` and the
        `assertGreaterEqual` after it stay exactly as they are.
      Add a matching case in `apps/proxy/tests/test_next_source_resolution.py` asserting
      `next_source.release_source("gone", stream_id=…, m3u_profile_id=…, channel_pk=…)` deletes both
      keys and calls `release_profile_slot` when neither the `Channel` nor the `Stream` row exists —
      the half of the pin that moved to Django.
- [ ] **Step 6: Run.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests core.tests -v1`
      Expected: OK, `test_ts_proxy_teardown` included.
      Run: `grep -rn "channel_stream:\|stream_profile:" apps/proxy/ | grep -v "/tests/"`
      Expected: no hits outside `redis_keys.py` (every use goes through the helpers).
      Run: `grep -rn "release_stream(" apps/proxy/ | grep -v "/tests/"`
      Expected: only `next_source.py`.
- [ ] **Step 7: Commit.** Write `msg-pr6-t9.txt`, stage exactly
      `apps/proxy/live_proxy/redis_keys.py apps/proxy/live_proxy/server.py apps/proxy/live_proxy/views.py apps/proxy/live_proxy/output/ts/generator.py apps/proxy/live_proxy/output/fmp4/generator.py apps/proxy/next_source.py apps/channels/models.py core/utils.py apps/channels/tests/test_ts_proxy_teardown.py apps/proxy/live_proxy/tests/test_atomic_db_close.py apps/proxy/tests/test_next_source_resolution.py`
      — `test_atomic_db_close.py` is staged here for its `CleanRedisKeysUsesStandardCloseTests` fix
      and again in Task 10 for its other class; a file appearing in two commits is fine.
      in one Bash call, then commit with `-F <path>/msg-pr6-t9.txt` in a separate call. Subject:
      `refactor(phase1-pr6): one writer for channel_stream and stream_profile`.

---

### Task 10: Every transition becomes an event

**Files:**
- Modify: `apps/proxy/live_proxy/server.py:19,796,1563`,
  `apps/proxy/live_proxy/input/manager.py:13,483,540,570,1152,1171,1497,1629`,
  `apps/proxy/live_proxy/output/ts/generator.py:11,128,642`,
  `apps/proxy/live_proxy/output/fmp4/generator.py:13,108`,
  `apps/proxy/vod_proxy/multi_worker_connection_manager.py:884,902`
- Modify: `apps/proxy/live_proxy/services/channel_service.py:17` (an unused
  `log_system_event` import) and `:850-882` (`_update_stream_stats_in_db`)
- Modify, in this task, the six pins that patch the names it removes:
  `apps/proxy/live_proxy/tests/test_atomic_db_close.py:34-43`,
  `apps/proxy/live_proxy/tests/test_buffering_state_recovery.py:69,93,120`,
  `apps/proxy/live_proxy/tests/test_health_reconnect.py:169`,
  `apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py:181`
- Test: the whole relay package plus `core.tests`

**Interfaces:**
- Consumes `apps.proxy.control_plane.emit_event`, which has the same signature as
  `core.utils.log_system_event`.

- [ ] **Step 1: Swap the imports at the five modules.**
      - `server.py:19`: `from core.utils import RedisClient, log_system_event` becomes
        `from core.utils import RedisClient`, plus a new
        `from apps.proxy.control_plane import emit_event` — the file has two renamed calls at `:796`
        and `:1563` and needs the name.
      - `output/ts/generator.py:11` and `output/fmp4/generator.py:13`: replace
        `from core.utils import log_system_event` with `from apps.proxy.control_plane import emit_event`.
      - `input/manager.py:13`: **delete only** the `log_system_event` import — Task 8 already added
        `from apps.proxy.control_plane import emit_event` to this module.
      - `services/channel_service.py:17`: `from core.utils import log_system_event` has **no call
        sites in the file** — delete it rather than swapping it, and add nothing (Step 3's
        `emit_event` import is function-local).
      - `vod_proxy/multi_worker_connection_manager.py:884`: the function-local
        `from core.utils import send_websocket_update, log_system_event` becomes
        `from core.utils import send_websocket_update` plus
        `from apps.proxy.control_plane import emit_event`.
- [ ] **Step 2: Rename the thirteen calls.** `log_system_event(` → `emit_event(` at
      `server.py:796` (`channel_start`) and `:1563` (`channel_stop`, already inside
      `gevent.spawn` — leave the spawn, `emit_event` spawning again is harmless and the outer
      spawn also covers the metadata read beside it); `manager.py:483` (`channel_reconnect`),
      `:540` and `:570` (`channel_error`), `:1152` (`channel_failover`), `:1171`
      (`channel_buffering`), `:1497` (`stream_switch`), `:1629` (`channel_reconnect`);
      `output/fmp4/generator.py:108` and `output/ts/generator.py:128` (`client_connect`);
      `output/ts/generator.py:642` (`client_disconnect`);
      `vod_proxy/multi_worker_connection_manager.py:902` (`vod_start`/`vod_stop`). **Arguments do
      not change at any site** — that is the whole point of matching the signature.
- [ ] **Step 3: Turn the last ORM write into an event.** Replace the body of
      `ChannelService._update_stream_stats_in_db` (`channel_service.py:850-882`) with:
      ```python
      @staticmethod
      def _update_stream_stats_in_db(stream_id, **stats):
          """Post the stats; Django writes the row.

          Phase 1 PR 6: this was the relay's only ORM write
          (stream.save(update_fields=['stream_stats', 'stream_stats_updated_at'])),
          called from three hot-path sites. The merge semantics — a None value
          never overwrites an existing key — move with it to
          core/relay_events.py. stream_stats is deliberately not in
          apps/connect/models.py's SUPPORTED_EVENTS and writes no SystemEvent
          row: input/manager.py flushes every 30s and
          parse_and_store_stream_info fires on every parsed codec line, and
          log_system_event trims to max_system_events (100 by default), so a
          row per stats line would evict every real event.
          """
          from apps.proxy.control_plane import emit_event

          emit_event("stream_stats", stream_id=stream_id, **stats)
          return True
      ```
      Its three callers (`input/manager.py:1104`, `:1407`, `channel_service.py:775`) are unchanged.
      Remove the file's now-unused `from django.utils import timezone` if nothing else uses it;
      `Stream` is still imported function-locally at `:908` and stays.
- [ ] **Step 4: Retarget the six pins this task breaks.** Each is a `patch()` on a name that no
      longer exists in its module, which raises `AttributeError` at decoration time — they fail
      immediately, not subtly.
      - `apps/proxy/live_proxy/tests/test_atomic_db_close.py:34-43`
        (`UpdateStreamStatsUsesStandardCloseTests`) asserts the old ORM shape:
        `_update_stream_stats_in_db(123, ffmpeg_output_bitrate=1.0)` returns `False` and
        `close_old_connections` is called once. Both are gone with the write. Replace the class with
        one that pins the new contract:
        ```python
        class UpdateStreamStatsPostsAnEventTests(SimpleTestCase):
            @patch("apps.proxy.control_plane.emit_event")
            def test_update_stream_stats_posts_rather_than_writes(self, mock_emit):
                from apps.proxy.live_proxy.services.channel_service import ChannelService

                self.assertTrue(
                    ChannelService._update_stream_stats_in_db(123, ffmpeg_output_bitrate=1.0)
                )
                mock_emit.assert_called_once_with(
                    "stream_stats", stream_id=123, ffmpeg_output_bitrate=1.0
                )
        ```
        The geventpool property it used to pin moves with the write: `core/relay_events.py`'s
        `_apply_stream_stats` keeps the `finally: close_old_connections()` and
        `core/tests/test_relay_events.py` (Task 5) asserts it.
      - `apps/proxy/live_proxy/tests/test_buffering_state_recovery.py:69`, `:93`, `:120` —
        `patch("apps.proxy.live_proxy.input.manager.log_system_event")` becomes
        `patch("apps.proxy.live_proxy.input.manager.emit_event")`.
      - `apps/proxy/live_proxy/tests/test_health_reconnect.py:169` — same substitution.
      - `apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py:181` —
        `patch("apps.proxy.live_proxy.server.log_system_event")` becomes
        `patch("apps.proxy.live_proxy.server.emit_event")`.
      Leave `apps/channels/tests/test_recording_stop_cancel.py:248` alone: it patches
      `core.utils.log_system_event` on the DVR path, which this PR does not touch.
- [ ] **Step 5: Verify the two Done greps.**
      Run: `grep -rn "log_system_event(\|\.save(\|\.objects\.create(" apps/proxy/ | grep -v tests`
      Expected: **no output**. This is the spec's Done criterion, verbatim.
      Run: `grep -rn "log_system_event" apps/proxy/ | grep -v "/tests/"`
      Expected: only the explanatory comment in `channel_service.py`'s docstring — no import, no call.
      Run: `PYTHONPATH=scripts/metrics python scripts/metrics/collect_architecture.py . | python -c "import json,sys; print(json.load(sys.stdin)['proxy_orm_writes'])"`
      Expected: `0`.
- [ ] **Step 6: Run the affected packages.**
      Run: `docker exec … manage.py test --keepdb apps.proxy.tests apps.proxy.live_proxy.tests apps.proxy.vod_proxy.tests apps.channels.tests core.tests apps.connect.tests -v1`
      Expected: OK.
- [ ] **Step 7: Commit.** Write `msg-pr6-t10.txt`, stage exactly
      `apps/proxy/live_proxy/server.py apps/proxy/live_proxy/input/manager.py apps/proxy/live_proxy/output/ts/generator.py apps/proxy/live_proxy/output/fmp4/generator.py apps/proxy/live_proxy/services/channel_service.py apps/proxy/vod_proxy/multi_worker_connection_manager.py apps/proxy/live_proxy/tests/test_atomic_db_close.py apps/proxy/live_proxy/tests/test_buffering_state_recovery.py apps/proxy/live_proxy/tests/test_health_reconnect.py apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py`
      in one Bash call, then commit with `-F <path>/msg-pr6-t10.txt` in a separate call. Subject:
      `feat(phase1-pr6): the relay posts events instead of writing rows`.

---

### Task 11: `relay_event` on the WebSocket, admin-only

**Files:**
- Modify: `dispatcharr/consumers.py:12-18` (`ADMIN_ONLY_UPDATE_TYPES`)
- Test: `core/tests/test_relay_events.py` (extend), `tests/` for the consumer gate

**Interfaces:**
- Consumes `core.relay_events._push` (Task 5), `dispatcharr.consumers.user_may_receive_update`.

- [ ] **Step 1: Write the failing test.** Add to the repo-root `tests/` package a
      `tests/test_relay_event_visibility.py`:
      ```python
      """relay_event is connection telemetry: admin sockets only.

      dispatcharr/consumers.py already keeps channel_stats and friends off
      Standard-user sockets because their payloads carry channel UUIDs, which
      are usable against anonymous /proxy/ts/stream/<uuid>. relay_event carries
      the same channel_id and is gated the same way (Phase 1 PR 6).
      """
      from django.test import SimpleTestCase

      from dispatcharr.consumers import ADMIN_ONLY_UPDATE_TYPES, user_may_receive_update


      class _User:
          def __init__(self, level):
              self.is_authenticated = True
              self.user_level = level


      class RelayEventVisibilityTests(SimpleTestCase):
          def test_relay_event_is_listed_admin_only(self):
              self.assertIn("relay_event", ADMIN_ONLY_UPDATE_TYPES)

          def test_a_standard_user_does_not_receive_it(self):
              self.assertFalse(
                  user_may_receive_update(_User(1), {"type": "relay_event", "channel_id": "x"})
              )

          def test_an_admin_receives_it(self):
              self.assertTrue(
                  user_may_receive_update(_User(10), {"type": "relay_event", "channel_id": "x"})
              )
      ```
      Run: `docker exec … manage.py test --keepdb tests.test_relay_event_visibility -v1`
      Expected: FAIL — `relay_event` not in the set.
- [ ] **Step 2: Add it.** In `dispatcharr/consumers.py`, inside `ADMIN_ONLY_UPDATE_TYPES`, after
      `"vod_stopped",`:
      ```python
      "relay_event",
      ```
      and extend the block comment above the set with one sentence naming `relay_event` and its
      channel id.
- [ ] **Step 3: Run.**
      Run: `docker exec … manage.py test --keepdb tests core.tests -v1`
      Expected: OK.
      Note: editing `dispatcharr/consumers.py` puts this PR on the shared-path route to all 16
      backend labels, which it was already on via `apps/api/urls.py`.
- [ ] **Step 4: Commit.** Write `msg-pr6-t11.txt`, stage exactly
      `dispatcharr/consumers.py tests/test_relay_event_visibility.py`
      in one Bash call, then commit with `-F <path>/msg-pr6-t11.txt` in a separate call.
      Subject: `feat(phase1-pr6): relay_event is admin-only telemetry`.

---

### Task 12: The frontend handles `relay_event`

**Files:**
- Modify: `frontend/src/store/channels.jsx` (state and one action)
- Modify: `frontend/src/WebSocket.jsx` — one `handleRelayEvent` export beside
  `scheduleRecordingFetch` (`:26-36`) and one `case` at `:315`, beside `case 'channel_stats'`
- Test: `frontend/src/store/__tests__/channels.test.jsx` (the store action) and
  `frontend/src/__tests__/websocketRelayEvent.test.jsx` (NEW — the first vitest `WebSocket.jsx` has
  ever had)

**Interfaces:**
- Produces `useChannelsStore.getState().relayEvents` (object keyed by channel uuid) and
  `applyRelayEvent(payload)`.

- [ ] **Step 1: Write the failing tests.** Add a `describe('applyRelayEvent', …)` block to
      `frontend/src/store/__tests__/channels.test.jsx`:
      - stores the newest event per channel, keyed by `channel_id`, with `event`, `stream_id`,
        `reason` and `timestamp`;
      - a second event for the same channel replaces the first;
      - an event with no `channel_id` is ignored and leaves `relayEvents` unchanged;
      - `client_disconnect` for a channel with no prior entry still records.
      Run: `cd frontend && npx vitest run src/store/__tests__/channels.test.jsx`
      Expected: FAIL — `applyRelayEvent is not a function`.
- [ ] **Step 2: Add the store slice.** In `frontend/src/store/channels.jsx`, add `relayEvents: {}`
      to the initial state and, beside `setChannelStats` (`:420`):
      ```jsx
      // The relay's transitions, pushed over the WebSocket since Phase 1 PR 6.
      // Before this there was no push for a stream switch, a failover or a
      // client teardown at all — the only way to see one was to poll
      // /proxy/ts/status. One entry per channel, newest wins: this is a
      // "what just happened" indicator, not a log.
      applyRelayEvent: (payload) =>
        set((state) => {
          const uuid = payload?.channel_id;
          if (!uuid) return state;
          return {
            relayEvents: {
              ...state.relayEvents,
              [uuid]: {
                event: payload.event,
                streamId: payload.stream_id ?? null,
                clientId: payload.client_id ?? null,
                reason: payload.reason ?? null,
                timestamp: payload.timestamp ?? null,
              },
            },
          };
        }),
      ```
- [ ] **Step 3: Handle the message.** In `frontend/src/WebSocket.jsx`, beside
      `case 'channel_stats':` (`:315`):
      ```jsx
      case 'relay_event':
        useChannelsStore.getState().applyRelayEvent(parsedEvent.data);
        break;
      ```
      Use `useChannelsStore.getState()` rather than a hook selector, matching the file's own
      pattern at `:334` and `:288`.
- [ ] **Step 3b: Extract the dispatch so it can be tested, and test it.** `WebSocket.jsx` has no
      vitest today — `api.js` and `WebSocket.jsx` are the two largest files in the tree with none
      (`CLAUDE.md` § Frontend) — and mounting `WebsocketProvider` to exercise one `case` would mean
      standing up a socket, a token and four stores. Instead lift the switch's payload handling for
      this one type into a named export the provider calls, so the test drives a function rather
      than a component. At the top of `frontend/src/WebSocket.jsx`, beside `scheduleRecordingFetch`:
      ```jsx
      // Exported for tests: WebSocket.jsx has no vitest coverage, and a case in
      // a switch inside a provider's onmessage cannot be reached without a live
      // socket. Phase 1 PR 6 starts the coverage here rather than adding an
      // untested branch to the largest untested file in the tree.
      export function handleRelayEvent(payload) {
        useChannelsStore.getState().applyRelayEvent(payload);
      }
      ```
      and the case becomes `case 'relay_event': handleRelayEvent(parsedEvent.data); break;`.
      Then create `frontend/src/__tests__/websocketRelayEvent.test.jsx`:
      ```jsx
      import { describe, expect, it, vi, beforeEach } from 'vitest';
      import { handleRelayEvent } from '../WebSocket';
      import useChannelsStore from '../store/channels';

      describe('handleRelayEvent', () => {
        beforeEach(() => {
          useChannelsStore.setState({ relayEvents: {} });
        });

        it('routes a relay_event payload into the channels store', () => {
          handleRelayEvent({
            type: 'relay_event',
            event: 'channel_failover',
            channel_id: 'uuid-a',
            stream_id: 7,
            reason: 'dead_air',
            timestamp: 1234,
          });

          expect(useChannelsStore.getState().relayEvents['uuid-a']).toEqual({
            event: 'channel_failover',
            streamId: 7,
            clientId: null,
            reason: 'dead_air',
            timestamp: 1234,
          });
        });

        it('ignores a payload with no channel id rather than throwing', () => {
          const spy = vi.spyOn(useChannelsStore.getState(), 'applyRelayEvent');
          handleRelayEvent({ type: 'relay_event', event: 'stream_switch' });
          expect(spy).toHaveBeenCalled();
          expect(useChannelsStore.getState().relayEvents).toEqual({});
        });
      });
      ```
      Run: `cd frontend && npx vitest run src/__tests__/websocketRelayEvent.test.jsx`
      Expected: FAIL first (`handleRelayEvent is not exported`), then pass.
- [ ] **Step 4: Run the whole frontend suite** — the files are under `frontend/`, so the commit gate
      runs all of it.
      Run: `cd frontend && npm test`
      Expected: pass (~6,128 tests). Default order only; the suite is known to fail under
      `--sequence.shuffle` for pre-existing reasons and this task must not be blamed for that.
- [ ] **Step 5: Commit.** Write `msg-pr6-t12.txt`, stage exactly
      `frontend/src/WebSocket.jsx frontend/src/store/channels.jsx frontend/src/store/__tests__/channels.test.jsx frontend/src/__tests__/websocketRelayEvent.test.jsx`
      in one Bash call, then commit with `-F <path>/msg-pr6-t12.txt` in a separate call. Subject:
      `feat(phase1-pr6): the UI sees failovers and switches as they happen`.

---

### Task 13: E2E — a failover produces an event and a push

**Files:**
- Create: `e2e/tests/streaming-failover/failover-events.spec.ts`
- Modify: `e2e/COVERAGE.md`

**Interfaces:**
- Consumes the `upstream`, `seed`, `api`, `streamClient` and `ws` fixtures from `../../fixtures`,
  `lockedProfile` from `../streaming/helpers`.
- Adds no greybox import, so `e2e/tests/guards/allowlist.ts` needs no entry.

- [ ] **Step 1: Write the spec.** Create
      `e2e/tests/streaming-failover/failover-events.spec.ts`, modelled on
      `failover-dead-air.spec.ts` (same project, `workers: 1`, 300 s timeout, admin storageState):
      ```ts
      import { test, expect, readChannelStatus } from '../../fixtures';
      import { lockedProfile } from '../streaming/helpers';

      // Phase 1 PR 6: the relay stopped writing SystemEvent rows itself and
      // started posting them to Django over /api/relay/events, which is also
      // where the relay_event WebSocket push is emitted. Both halves are
      // asserted here, because a batch that reaches the view but never pushes
      // would still fill the events list and look correct.
      test(
        'a dead-air failover is reported as an event and a relay_event push',
        { tag: '@contract' },
        async ({ upstream, seed, api, streamClient, ws }) => {
          const scenario = await upstream.scenario({
            channels: [
              { id: 1, name: 'P1 Events A', tvgId: 'p1-events-a.e2e', logo: null },
              { id: 2, name: 'P1 Events B', tvgId: 'p1-events-b.e2e', logo: null },
            ],
            rate: 20,
          });
          const proxy = await lockedProfile(api, 'Proxy');
          const { channel, streams } = await seed.upstreamChannel(scenario, {
            channelIds: [1, 2],
            streamProfileId: proxy.id,
          });

          await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
          await streamClient.readPackets(100);
          expect(
            (await readChannelStatus(api, channel.uuid)).stream_id,
            'should start on stream A'
          ).toBe(streams[0].id);

          await upstream.fault(scenario, 'dead-air', { channel: 1 });

          // The push. /ws/ is one broadcast group, so correlate on this
          // channel's own uuid — another spec's failover must not satisfy it.
          const pushed = ws.waitForMessage('relay_event', {
            where: (data) =>
              data.channel_id === channel.uuid && data.event === 'channel_failover',
            timeoutMs: 120_000,
          });

          await expect
            .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
              timeout: 120_000,
              intervals: [2_000],
            })
            .toBe(streams[1].id);

          const message = await pushed;
          expect(message.data?.channel_id).toBe(channel.uuid);
          expect(
            message.data,
            'the push is a field whitelist — no provider URL reaches a browser'
          ).not.toHaveProperty('new_url');

          // The row. Django wrote it, from the batch the relay posted.
          const events = await api.json<{ events: Array<{ channel_id: string }> }>(
            await api.get('/api/core/system-events/?event_type=channel_failover&limit=100'),
            'system events after a dead-air failover'
          );
          expect(
            events.events.some((event) => event.channel_id === channel.uuid),
            'channel_failover should be recorded for this channel'
          ).toBe(true);
        }
      );
      ```
      The option is `timeoutMs`, not `timeout` (`e2e/fixtures/ws.ts:129-137`); the default is 30 s,
      which is under the dead-air watchdog's ~25 s plus the switch, so it must be raised explicitly.
      `where` is mandatory here: `/ws/` is one broadcast group and every socket sees every
      instance-wide event.
- [ ] **Step 2: Typecheck.**
      Run: `cd e2e && npx tsc --noEmit`
      Expected: clean. This is the only automated check the `e2e/` tree has and it is a ratchet.
- [ ] **Step 3: Add the COVERAGE row.** In `e2e/COVERAGE.md`, in the Streaming area beside the
      existing `P1` authorize row (`:194`):
      ```
      | Streaming | Relay events: a `dead-air` failover posts `channel_failover` to `/api/relay/events`, Django writes the `SystemEvent` row that `GET /api/core/system-events/` returns, and pushes a `relay_event` WebSocket message whose payload carries the channel uuid and no provider URL | P1 | done |
      ```
- [ ] **Step 4: Run the project.** Bring the pr6 stack up per § Test environment step 6, then:
      Run: `cd e2e && E2E_BASE_URL=http://localhost:59191 DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr6 E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:9405 E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-pr6:8080 npx playwright test --project=streaming-failover`
      Expected: all specs pass, including the four pre-existing ones. If the container cannot be
      built or started, say so in the task report: the work is then unverified, not verified.
- [ ] **Step 5: Commit.** Write `msg-pr6-t13.txt`, stage exactly
      `e2e/tests/streaming-failover/failover-events.spec.ts e2e/COVERAGE.md`
      in one Bash call, then commit with `-F <path>/msg-pr6-t13.txt` in a separate call.
      Subject: `test(phase1-pr6): a failover is observable as an event and a push`.

---

### Task 14: Full verification

**Files:** none edited. This task produces no commit unless it finds something.

- [ ] **Step 1: All 16 backend labels.** For each label in § Done criteria run
      `docker exec … manage.py test --keepdb <label> -v1`.
      Expected: OK for all 16. Record the counts.
- [ ] **Step 2: The commit gate, as CI would compute it.**
      Run: `CLAUDE_HOOK_REPO_ROOT=<worktree> DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr6 <worktree>/.claude/hooks/pre-commit-tests.sh --git-hook`
      Expected: exit 0.
- [ ] **Step 3: The guards.**
      Run: `python scripts/check_credential_logging.py $(git diff --name-only origin/main...HEAD -- '*.py')`
      Expected: exit 0.
      Run: `docker exec … manage.py spectacular --validate --fail-on-warn --file /dev/null`
      Expected: exit 0.
      Run: `docker exec … manage.py makemigrations --check --dry-run dispatcharr_connect dispatcharr_channels proxy`
      Expected: `No changes detected`. Three deliberate choices in that label list:
      - **`proxy`, not `dispatcharr_proxy`.** `apps/proxy/apps.py`'s `ProxyConfig` sets `name` and
        `verbose_name` but no `label`, so Django derives the label from the last path segment. The
        made-up name would abort the command with "No installed app with label".
      - **`core` is deliberately absent**, and stays absent until #177 merges. Issue #177 records a
        pending `AlterField` on `core.StreamProfile.parameters` that predates Phase 1; including
        `core` here would report it and contradict this Expected. **Do not gate PR 6 on #177**, and
        do not generate that migration here — it is a different change with a different reviewer.
      - The three labels are exactly the apps whose `models.py` this PR edits (`dispatcharr_connect`,
        Task 5) or whose app gains routes and modules (`proxy`, and `dispatcharr_channels` through
        the `_PATH_ALIASES` coupling).
      The `PostToolUse` hook is unaffected either way — `.claude/hooks/_pending_migrations.py` takes
      one app label, so Task 5's `apps/connect/models.py` edit checks only `dispatcharr_connect`.
      **If a later task edits `core/models.py`**, the hook then checks `core` and will report #177's
      drift; that is pre-existing, and the correct response is to say so, not to generate it.
      Run: `docker exec … manage.py check`
      Expected: no issues.
- [ ] **Step 4: The metric and the Done grep.**
      Run: `grep -rn "log_system_event(\|\.save(\|\.objects\.create(" apps/proxy/ | grep -v tests`
      Expected: no output.
      Run: `PYTHONPATH=scripts/metrics python scripts/metrics/collect_architecture.py . | python -c "import json,sys; d=json.load(sys.stdin); print(d['proxy_orm_writes'], d['models_module_level_live_proxy_imports'])"`
      Expected: `0 2` — zero writes, and the boot-cycle trap still at its baseline of two.
      Run: `python -m metrics.build --validate-only`
      Expected: exit 0.
- [ ] **Step 5: Frontend and E2E.**
      Run: `cd frontend && npm test` — Expected: pass.
      Run: `cd e2e && npx tsc --noEmit` — Expected: clean.
      Run the `streaming`, `streaming-failover`, `streaming-greybox` and `lifecycle` projects
      against the pr6 stack, and `docker/tests/test-puid-pgid.sh` restricted to `test_role_split`
      and `test_modular_mode` under `/opt/homebrew/bin/bash`.
      Expected: green. **`test_role_split` is the only place the relay→Django hop is exercised across
      containers, and this PR is the first time it carries traffic.** That scenario already sets
      `DISPATCHARR_WEB_HOST=<api container>` on both the relay and worker services and the api's
      nginx listens on 9191, so `get_control_plane_base_url()`'s modular branch resolves; if it does
      not, the symptom is every tune in that scenario answering "Control plane unreachable", and the
      thing to check is that variable, not the relay. Report any project that could not run and why.

---

### Task 15: Documentation

**Files:**
- Modify: `CLAUDE.md` (three corrections)
- Modify: `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (Done log, and a new
  Amendment S10)

- [ ] **Step 1: `CLAUDE.md` § Structural constraints.** Replace "non-test `apps/proxy/` contains
      **exactly one ORM write**" with the post-PR-6 statement: non-test `apps/proxy/` contains
      **zero** ORM writes as of Phase 1 PR 6 — the `stream.save()` in
      `services/channel_service.py` and all thirteen `log_system_event()` calls
      (`server.py` ×2, `input/manager.py` ×7, `output/ts/generator.py` ×2,
      `output/fmp4/generator.py` ×1, `vod_proxy/multi_worker_connection_manager.py` ×1) now post to
      `POST /api/relay/events` and Django performs the write in `core/relay_events.py`. Keep the
      sentence about 24 reverse-import sites and 14 model classes: this PR did not change it.
- [ ] **Step 2: `CLAUDE.md` § Known defects.** The spec says to correct "the
      `channel_stream:*`/`stream_profile:*` split-brain description"; **there is no such bullet in
      `CLAUDE.md` today** — the split-brain is described only in the spec's § What the code says.
      Verify that first with
      `grep -n "channel_stream" CLAUDE.md` (expected: no output), then **add** a bullet to
      § Known defects › Correctness rather than editing one, since a reader of that section needs to
      know the keys have a single owner: both keys were read *and written* by
      `apps/channels/models.py` and independently by `apps/proxy/live_proxy/`, with neither in
      `RedisKeys`; as of Phase 1 PR 6 they are `RedisKeys.channel_stream` /
      `RedisKeys.stream_profile`, `apps/channels/models.py` is the only writer, and the relay reaches
      them only through `POST /api/relay/channels/<identifier>/next-source` and `/release`. Say
      explicitly that the relay still *reads* them (`live_proxy/views.py`) on purpose: they are
      Django-owned keys, not relay state, so PR 7's "no control-plane code reads relay keys" does not
      cover them.
- [ ] **Step 3: `CLAUDE.md` § Observing a channel.** Replace "**No WebSocket event exists for stream
      switch, failover or client teardown**" with: `relay_event` is pushed for `channel_failover`,
      `stream_switch` and `client_disconnect` (`core/relay_events.py`), admin-only like
      `channel_stats` (`dispatcharr/consumers.py`), payload a field whitelist that never carries a
      provider URL. Keep the rest of the paragraph — `channel_stats` is still the only *stats*
      emission and still a JSON-encoded string under `data.stats`.
- [ ] **Step 3b: `CLAUDE.md` § Events and plugins** (`:83`). It opens "Every interesting transition
      calls `log_system_event()` (`core/utils.py`)", which stopped being true for the relay in this
      PR. Add one clause: the relay posts its thirteen transitions to `POST /api/relay/events`
      instead, and `core/relay_events.py` makes the `log_system_event()` call on the API process. The
      sentence's point — that this is the extension point to use before adding polling anywhere — is
      unchanged and stays. Not named in the spec's correction list; it is the same sentence going
      stale for the same reason, so it is corrected in the same pass.
- [ ] **Step 4: The spec's Done log.** Set the `Next-source + events` row's `PR` cell to this PR's
      number. **The number is not known while writing the code**, so this step runs after the PR is
      opened, as a final commit on the branch — the same sequence PR 5 used to record `#176`.
- [ ] **Step 5: Amendment S10 in the spec's § PR 6.** Record, in the spec's own amendment style, the
      five places the tree required a decision the spec did not make:
      1. the internal token **is** bound in PR 6 (the follow-up bullet's first option), by a second
         header rather than by changing the existing one, because the DVR's ffmpeg reconnect cannot
         re-sign;
      2. the event-batch writes live in `core/relay_events.py`, because D12 puts the routes in
         `apps/proxy/` and the Done grep forbids a write there — and because
         `scripts/metrics/collect_architecture.py` counts every write under `apps/proxy/` into the
         phase's own headline metric;
      3. the next-source request carries `current_url` and the response carries `slot_reserved` and
         `alternates`, three fields the spec's list omits, each named with the caller that needs it;
      4. every relay-side `release_stream()` call moves, not only the six the spec enumerates,
         because the Requirements row ("exactly one writer") is the binding statement;
      5. `next-source` answers 200 with a null `source` when a channel has no candidate left, and
         404 only for an unresolvable identifier; the client raises `ControlPlaneRefused` (distinct
         from `ControlPlaneUnavailable`) on every other 4xx, and **only `ControlPlaneUnavailable`
         fires the degraded fallback** — otherwise a deleted channel or a `SECRET_KEY` mismatch
         between roles would degrade silently instead of failing;
      6. **`channel_stream:*` semantics are unchanged.** `Channel.update_stream_profile()`
         (`apps/channels/models.py:933-1003`) reads `channel_stream:{id}` to find the channel's
         *original* stream and rewrites `stream_profile:{original}`; it never writes
         `channel_stream` itself, so after a failover that key still names the first stream tuned,
         and `release_stream()`, `get_stream()`'s reuse branch and `core/utils.py`'s event
         enrichment all read the chain that way. PR 6 moves *where* the method is called from and
         changes nothing about *what* it does. Fixing the chain would mean deleting the stale
         `stream_profile:{old}` and re-deriving three readers — a relay-internals change this phase
         forbids. **Recorded here so PR 8 or Phase 2 revisits it deliberately rather than
         discovering it.**
      7. the bound token has no nonce, so replay inside the ±120 s window is possible and accepted;
         the reasoning is in `internal_auth.internal_request_token`'s docstring and in ruling 16;
      8. the two synchronous calls can occupy one greenlet for ~14 s during a Django outage
         (ruling 17) — the number PR 8's Django-down scenario measures against.
- [ ] **Step 5b: `CLAUDE.md` § Commands.** The documented
      `uv sync && uv run python manage.py migrate && uv run python manage.py runserver` line now
      leaves `DISPATCHARR_ENV` unset, which sends `get_control_plane_base_url()` down the AIO branch
      to `http://127.0.0.1:9191` and makes every tune answer "Control plane unreachable". Add
      `DISPATCHARR_ENV=dev` to the `runserver` invocation and one clause saying why: since PR 6 the
      relay asks Django for its source over HTTP, and `dev` is the branch that points that call at
      the single process's own port. `DISPATCHARR_INTERNAL_API_BASE_URL` is the escape hatch for any
      other local shape.
- [ ] **Step 5c: The PR body says what it does and does not close.** Issue #181 asks for the internal
      token to be bound or scoped before it gates a control API. PR 6 binds it for `/api/relay/…`
      only; `/proxy/relay/…` does not exist until PR 7. The PR description must say **"partially
      addresses #181; the `/proxy/relay/…` half is PR 7's"** and must not use a closing keyword —
      `Closes`, `Fixes` and `Resolves` all auto-close on merge and would leave the second half
      untracked.
- [ ] **Step 6: Run the docs checks.**
      Run: `grep -n "exactly one ORM write" CLAUDE.md` — Expected: no output.
      Run: `grep -n "No WebSocket event exists" CLAUDE.md` — Expected: no output.
      Run: `grep -c "RedisKeys.channel_stream" CLAUDE.md` — Expected: 1 or more (Step 2 added the
      bullet that did not exist).
- [ ] **Step 7: Commit.** Write `msg-pr6-t15.txt`, stage exactly
      `CLAUDE.md docs/superpowers/specs/2026-09-04-phase1-process-split-design.md docs/superpowers/plans/2026-09-05-phase1-pr6-next-source-events.md`
      in one Bash call — the plan file itself is part of this PR and is staged nowhere else — then
      commit with `-F <path>/msg-pr6-t15.txt` in a separate call. Subject:
      `docs(phase1-pr6): CLAUDE.md and the spec record the new boundary`. Step 4's Done-log edit is a
      second, later commit on the same branch, once the PR number exists.
