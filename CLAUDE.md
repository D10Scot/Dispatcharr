# CLAUDE.md

## Repository and direction

Fork. `origin` = `D10Scot/Dispatcharr` (push here); `upstream` = `Dispatcharr/Dispatcharr` (fetch-only; push URL is the literal string `DISABLED`). Upstream targets `dev`; this fork works on `main`.

Purpose: **extract the streaming relay from the Django web workers into its own process** (control/data plane split), not a rewrite. Phase 0 harden in place → 1 extract the boundary, still Python → 2 optionally Go → 3 remove Redis from the data path. **Stopping after Phase 1 is a legitimate outcome. Resist widening scope — that is the main way this fails.**

Four investigation documents hold the detail behind every summary here — **read the relevant one before deep work rather than re-deriving it**:

- Teardown (line-by-line behaviour) — https://claude.ai/code/artifact/7e7330e2-2fad-4e9d-a0b3-22be18c568ae
- Due diligence (gaps, defects, governance) — https://claude.ai/code/artifact/6dddf987-6135-480c-8b77-c5ad621a8c06
- Test-suite report — https://claude.ai/code/artifact/3ced4b71-c684-47e0-bf2f-b4ee1b9826cc
- Splitting the Planes (extraction proposal) — https://claude.ai/code/artifact/149fb554-d140-4e13-abaf-2416429b2e3f

Verified at `fd413f0c` (v0.29.0); line numbers drift.

**Isolation for new work.** Anything large (multi-file, unattended, or a `/goal`) gets its own worktree + branch off `main` — keeps this checkout free and test-hook container state from crossing streams. A small change (one file / few lines) can go on a new branch in this checkout.

## Commands

```bash
uv sync && uv run python manage.py migrate && uv run python manage.py runserver
python manage.py test [apps.channels.tests[.test_x[.Cls.test_y]]]   # custom runner
python manage.py test --shuffle 12345          # reproduce order-dependent failures
TEST_USE_SQLITE=1 python manage.py test        # no-Postgres fallback; PG-only tests self-skip
uv run python manage.py makemigrations <app>

cd frontend && npm install
npm run dev    # Vite :9191, proxies /api -> :5656, /ws -> :8001
npm run build && npm test                      # vitest --run
npm run lint   # ~112 pre-existing errors, disabled in CI. No format script: npx prettier --write
```

- `manage.py` rewrites `DJANGO_SETTINGS_MODULE` to `dispatcharr.settings_test` for `test` only. **Never pass `--settings=dispatcharr.settings` to `test` on a live instance** — it targets the production database.
- Tests need Postgres and Redis. `scripts/ci_bootstrap_backend.sh` is what CI runs; assumes the base image's layout.
- Docker: `docker/docker-compose.{dev,aio}.yml` + `docker-compose.yml` (modular); `DISPATCHARR_ENV` picks the variant. `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh` are good integration tests — wired into no workflow.

## Test hooks (this fork only)

`.claude/settings.json` registers `PostToolUse` on `Write|Edit`, each check scoped to the edited file. Blocking: `*tests/test_*.py` (whole package), `frontend/**/*.test.jsx` (vitest), `*/models.py` (`makemigrations --check`), `live_proxy/{constants,redis_keys}.py` (`manage.py check`), `.github/workflows/*.yml` + `action.yml` + `dependabot.yml` (zizmor), `e2e/**/*.ts` + `e2e-upstream/**/*.ts` (`tsc --noEmit` for that package — blocking, unlike eslint: both packages typecheck clean, so it's a ratchet, and the only automated check those trees have; a full Playwright run is far too slow for a hook), any `*.py` (`scripts/check_credential_logging.sh`). Advisory: eslint on `frontend/**/*.jsx` (so pre-existing errors don't punish touching legacy code).

- The migration check resolves the app label via `apps.get_app_configs()`, never the directory name: `apps.channels` has label `dispatcharr_channels`, and the guess `channels` hits the *Django Channels library*, which reports "no changes" and exits 0 — guessing fails silently.
- The boot check exists because `apps/channels/models.py:6–7` imports two `live_proxy` leaf modules at module level; a cycle there breaks `manage.py check` for every command.
- zizmor blocks on **every** finding in the edited file, legacy included. Workflows are at **zero findings** — a ratchet; keep it there. Same zizmor version pinned in `.github/workflows/actions-lint.yml`; the hook warns on version drift — bump both together. **Deliberately no `.github/zizmor.yml`** (defaults already enforce hash-pinning, `persist-credentials`, least-privilege permissions); suppress a considered exception with a trailing `# zizmor: ignore[audit-name]`. Online audits are **on** (`impostor-commit` catches SHAs from the wrong repo — invisible offline); token from `$GH_TOKEN` / `$GITHUB_TOKEN` / `gh auth token`, degrades loudly to offline without one. Opt out with `ZIZMOR_HOOK_OFFLINE=1` — **not** zizmor's own `ZIZMOR_OFFLINE`, a `true`/`false` flag that `=1` breaks.
- Backend runs in the `dispatcharr-testrunner` container, repo bind-mounted **read-only** at `/repo`; PG data in the `dispatcharr-hookdb` volume (PG won't run on a macOS bind mount). Restart with `.claude/hooks/start-test-container.sh` (idempotent, ~2s); `DISPATCHARR_TEST_CONTAINER` / `_IMAGE` / `_DB_VOLUME` override.
- Deliberate, matching CI: **Redis is flushed before every backend run** and **the whole package runs, not just the edited module**.
- If Docker/the container is down the hook says so loudly and exits 0. **Then say the tests did not run — do not describe the work as verified.**

`PreToolUse` on `Bash(git commit*)` gates commits on the tests covering whatever is **staged**, deriving labels from `scripts/ci_backend_test_labels.py` (exactly what CI would run); anything under `frontend/` runs the whole frontend suite; `git commit -a` is handled. Infrastructure failures warn rather than block. Baseline **16/16** backend packages pass (~1,787 tests, ~34s). The gate inherits the two routing defects under *Testing* on purpose: it must not disagree with CI. **Stage and commit in separate Bash calls** — the hook runs before the command, so one doing both is blocked. It matches on command text, so a heredoc — or a commit message — merely *containing* those two words trips it as well; write such files with the Write tool and commit with `-F <file>`.

## Architecture

Django 6 + DRF, React 19 SPA same-origin, Celery, Redis for broker/cache/channel-layer **and the video path**, PostgreSQL for durable state. A third of the backend is `apps/proxy` (22.3k LOC) and `apps/channels` (20.8k); then `epg`, `timeshift` (Xtream catch-up), `m3u`, `core` (settings registry, profiles, events), `output`, `vod`, `plugins`, `hdhr`.

`docker/uwsgi.ini` runs uWSGI (4 workers × `gevent = 400`, `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`) with the rest as `attach-daemon`: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. (`docker/entrypoint.aio.sh` starts gunicorn and is referenced nowhere — legacy.) Consequences constraining nearly every `apps/proxy` change:

- Four worker processes ⇒ **no channel state may live in Python memory**.
- Early monkey-patching ⇒ the proxy's 27 `threading.Thread`s are greenlets sharing one OS thread with 400 request greenlets. **One blocking call stalls the hub.**
- `StreamManager` spawns ffmpeg with **`os.posix_spawn`** and a hand-rolled Popen-compatible wrapper because `fork()`-based approaches hang in gevent's `_before_fork` (`input/manager.py`). **Do not "simplify" this back to `Popen`.**
- **DB backend differs per process**: uWSGI gets `django-db-geventpool` (MAX_CONNS=8, REUSE_CONNS=3); Celery and Daphne get plain `postgresql`, deliberately unpatched.
- nginx **`uwsgi_buffering off`** on `/proxy/` is load-bearing — a past bug used `proxy_buffering off` (wrong directive family for `uwsgi_pass`) and nginx spooled live TS to disk.

**State.** PostgreSQL holds durable rows — including settings, but **`CoreSettings` is one row per settings *group*, not per setting**: `key` unique, `value` a `JSONField`, eight groups (`core/models.py:201-208`). Every group is instance-wide, so there is no scoped settings write — treat any as blast radius (E2E allowlists them; see `docs/adr/0003`). `epg_settings` has no seeding migration, so POST it before you can PATCH it. Redis holds ownership leases, channel metadata, client sets, counters and switch requests (TTL'd), **the video bytes** in a ring buffer (**~1.06 MB chunks** — `TS_PACKET_SIZE * 5644`, `input/buffer.py` `target_chunk_size`, override `BUFFER_CHUNK_SIZE`; at a 54 KB/s trickle a chunk takes ~20s to roll — 60s TTL), `live:events:*` pub/sub, plus Celery broker / Channels layer / Django cache. All share **DB 0**, so video memory pressure takes out the task queue and cache. `scripts/wait_for_redis.py` does `flushdb()` on every AIO boot; the modular variant preserves only Celery prefixes and has no instance scoping.

**Video path.** Three locked built-in **Stream Profiles** = three architectures: *Redirect* (302 to provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). Default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). **There is no HLS output**: `_OUTPUT_FORMAT_MANAGERS` registers only `fmp4`, MPEG-TS (default) uses no output-side ffmpeg, and the 1,206-line `apps/proxy/hls_proxy/` is dead. HLS *upstreams* are handled by forcing the ffmpeg profile.

One uWSGI worker owns a channel's upstream, elected by `redis.set("live:channel:{id}:owner", worker_id, nx=True, ex=30)` (`live_proxy/server.py`); followers serve their own clients from the same keys and ask the owner to act over `live:events:{id}`. `_ensure_owner_or_stop()` runs each main-loop iteration. `input/buffer.py` realigns to 188-byte TS packets before writing chunks. **The chunk index is monotonic for the channel's life, never reset by a stream switch** — why a switch doesn't touch clients; new clients start ~5s behind live via the timestamp zset.

Failover: three independent triggers into `_try_next_stream()` — buffering (`speed=` < 1.0× sustained > 15s), dead air (> 10s, 3× @ 5s), connect failure (3 in 30 min). The buffering detector is **ffmpeg-exclusive** (Proxy/Redirect have no stderr; `buffering_speed`/`buffering_timeout` silently inert there, nothing in the UI says so), and `speed=` is a cumulative average since process start, so a front-loaded lead must burn off before it arms (~55s measured — the ~25s dead-air watchdog usually wins). It earns its keep only on *partial* degradation; `buffering_speed` above 1.0 is the lever. Thresholds are snapshotted in `StreamManager.__init__` — UI changes don't affect running channels. **No quality measurement exists** — bitrate is displayed, never thresholded; no continuity-counter, PCR-gap or discontinuity checks.

VOD is deliberately different: no ring buffer (`iter_content(8192)` passthrough), one upstream per session, stateless across workers, pre-stream failover only. Its stream counter's four Lua scripts bypass the metadata lock **on purpose** — a real bug fix, pinned by `vod_proxy/tests/test_vod_lock_contention.py`.

**Auth — two opposite defaults.** REST API is deny-by-default (`DEFAULT_PERMISSION_CLASSES = IsAdmin`): views are admin-only unless they opt down; authorization runs on `user_level` (Streamer 0 / Standard 1 / Admin 10) plus M2M to `ChannelProfile` — Django's Group/Permission tables are vestigial. Streaming is the opposite: `stream_ts` is `AllowAny`, gated only by `network_access_allowed(request, "STREAMS")`, STREAMS ACL defaulting to `0.0.0.0/0` — a deliberate concession (tuner URLs can't carry bearer tokens). The WebSocket consumer marks stats events admin-only. **A channel UUID is a secret; treat it as one.** If you touch the stream endpoint during the extraction, the intended replacement is a Django-minted short-lived HMAC-signed URL the relay validates statelessly.

**Routing.** `dispatcharr/urls.py` mounts Xtream endpoints (`player_api.php`, `get.php`, `/<user>/<pass>/<id>`) at the site root **before** the SPA catch-all — root-level route additions shadow the frontend. Client surface: `/proxy/{ts/stream/<uuid>,vod,catchup}`, `/output/{m3u,epg}`, `/hdhr/`, plus the XC API's 17 actions. **Every `live_proxy` endpoint is keyed by the channel's UUID *string*, never its numeric id** — all seven routes capture `<str:channel_id>` and `channel_status` passes it straight to Redis with no DB lookup; the XC path resolves a `Channel` then calls `stream_ts(..., str(channel.uuid), ...)`. Passing `channel.id` to `/status/`, `/change_stream/`, `/next_stream/` or `/stop/` 404s for every channel, always. No SSDP/UPnP discovery for the HDHomeRun emulation; the generated M3U emits no `catchup=` attributes (advertised only via XC `tv_archive`).

**Observing a channel.** `GET /proxy/ts/status/<uuid>` (admin-only) is the only status surface; four fields mislead. `owner` falls back to the literal string `'unknown'`, never null — truthiness checks pass when nobody owns the channel. `total_bytes`, `avg_bitrate_kbps`, `stream_id`, `stream_name` can be **absent entirely** (not null). `ffmpeg_speed` is a **string** in `get_detailed_channel_info` but a `float` in `get_basic_channel_info` — the two endpoints disagree on its type. **No WebSocket event exists for stream switch, failover or client teardown** — `channel_stats` is the only `live_proxy` emission, its payload a JSON-encoded *string* under `data.stats`, broadcast as a side effect of polling the bare `GET /proxy/ts/status`. Observe transitions by polling the per-channel endpoint.

**Events and plugins.** Every interesting transition calls `log_system_event()` (`core/utils.py`), writing a `SystemEvent` row and fanning out to Connect (webhook/script/API) on its own greenlet; vocabulary is a fixed dict at `apps/connect/models.py`. **Use this extension point before adding polling anywhere.** Plugins live outside `INSTALLED_APPS` in `/app/data/plugins/<name>/` (see `Plugins.md`), run arbitrary Python in-process, unsandboxed; `dispatcharr/celery.py` calls `PluginManager.discover_plugins()` in `worker_process_init` — per forked child, deliberately, so children don't inherit DB connections.

**Frontend.** `frontend/src/store/*.jsx` — Zustand, one store per domain; **new global state goes here, not React Context**. `frontend/src/api.js` — all HTTP; **components must not call fetch/axios directly**. `frontend/src/WebSocket.jsx` — one consumer on `/ws/`, generic `updates` group. Mantine 8; **do not add UI libraries.** `api.js` and `WebSocket.jsx` are the two largest files in the tree with no tests.

## Structural constraints on refactoring

- **The apps are a mesh, not a stack**: 367 cross-app imports over 50 edges, four cycles centred on `channels`. Extracting the relay pulls in `channels` → `m3u`/`epg` → back. There is no clean seam.
- `apps/channels/models.py:6–7` imports `RedisKeys` and `ChannelMetadataField` from `apps.proxy.live_proxy` at **module level** — loaded by every migration and management command. It survives only because those are leaf modules: **one import added to `live_proxy/constants.py` and Django stops booting.** Hence 602 function-local imports.
- Good news: non-test `apps/proxy/` contains **exactly one ORM write**. The obstacle is 24 reverse-import sites and reads of 14 model classes, not transactional coupling.
- Complexity is concentrated: 111 functions hold 43% of function lines — `fetch_schedules_direct()` (1,323 lines), `run_recording()` (1,139, 47 `try` blocks), `sync_auto_channels()` (1,010).

## Known defects and traps

Verified. **Don't "fix" surrounding code without knowing these are already there; don't reintroduce them in new code.**

Security — treat the first as an incident:

- Provider credentials were logged at INFO at five sites (VOD proxy request path/headers, M3U URL transform, DVR stream URLs); all five now log at DEBUG through `redact_url`/`redact_headers` (`dispatcharr/utils.py`), and `scripts/check_credential_logging.sh` blocks any log call naming a URL, path, header or credential that bypasses them — in the edit hook and in `lint.yml`.
- `docker/docker-compose.yml` publishes Postgres on `5436:5432` (all interfaces) as `dispatch`/`secret`.
- `settings.py`: `ALLOWED_HOSTS=["*"]`, `CORS_ALLOW_ALL_ORIGINS=True`, `CSRF_TRUSTED_ORIGINS=["http://*","https://*"]` — none conditioned on `DEBUG`.
- Xtream passwords plaintext in `custom_properties["xc_password"]`, compared with `!=`; API keys looked up by plaintext value, unscoped.

Correctness:

- **The ownership lease is time-bounded, not fenced.** `StreamBuffer.add_chunk()` writes with no ownership check or fencing token — two owners interleave chunks at alternating monotonic indices and readers decode a spliced stream with every check passing. The lease **fails open** three ways (`live_proxy/server.py` and `_execute_redis_command` swallowing exceptions to `None`); `release_ownership` is GET→compare→DELETE, `extend_ownership` GET→EXPIRE, both non-atomic. **If you carry this design forward: lease token in the write path via Lua, never fail open.**
- Channel preemption is dead code — `_pick_channel_to_preempt()` exists but `apps/channels/models.py` has the `return` commented out.
- The `preferred-region` read can never succeed (`core/migrations/0020` deleted the flat row it reads; the value now lives inside the `system_settings` group) — EPG matching runs with no regional weighting, silently. **Three sites, not one**: `epg_matching.py:get_preferred_region_code` plus inline copies of the same `CoreSettings.objects.get(key="preferred-region")` lookup in both bulk tasks (`apps/channels/tasks.py:236` and `:340`), so fixing the helper alone fixes a third of it. `CoreSettings.get_preferred_region()` works; none of the three call it.
- **Both scheduler migration reverses are broken**: `epg/migrations/0007` deletes *every* `IntervalSchedule`/`PeriodicTask`; `m3u/migrations/0006` filters on a field `IntervalSchedule` never had (`FieldError`). 16 migrations have no reverse; nothing in CI exercises reverse migrations or `makemigrations --check`.
- Channel-authorization filter copy-pasted across **eight** sites; `output/views.py` uses `"channels__user_level": 0` instead of `__lte`. `hide_adult_content` applied in listing paths but **not** in `live_proxy/views.py` or `timeshift/views.py` — hidden channels are unlistable yet streamable. **`hdhr/api_views.py` is a separate defect, not an instance of that one**: all four endpoint views (`DiscoverAPIView`, `LineupAPIView`, `LineupStatusAPIView`, `HDHRDeviceXMLAPIView`) are `AllowAny` and never resolve a user, gated only by `network_access_allowed(request, "M3U_EPG")` — so a per-*user* preference like `hide_adult_content` is inapplicable there rather than forgotten, and the real gap is that the HDHomeRun surface performs no authorization of any kind. The two need different fixes and neither closes the other. The one extracted helper: `_user_can_access_channel` (`apps/timeshift/views.py`).
- Channel-stopping key written `setex(..., 60, ...)` on five paths and `setex(..., 30, ...)` on three — a race generator.
- `MAX_STREAM_SWITCHES` doesn't bound buffering-triggered switches: they come from the stderr greenlet, bypassing the main loop's counter.
- The fMP4 generator's `_is_timeout()` lacks the TS generator's `url_switching` exemption — fMP4 viewers can be dropped at 40s during a slow failover.

Dead or unwired: `apps/proxy/hls_proxy/`; `dispatcharr/persistent_lock.py` (no callers; `refresh()` sets `has_lock = False` on success, and an attribute shadows the `has_lock` method); `_attempt_health_recovery()`; `head_vod()` (no route); `MAX_HEALTH_RECOVERY_ATTEMPTS` / `MAX_RECONNECT_ATTEMPTS` / `MIN_STABLE_TIME_BEFORE_RECONNECT` (`config.py` — real values are bare literals in the health-monitor body); `M3UAccount.stream_profile`; `HDHRDevice.tuner_count`.

Style debt: 236 exception handlers whose whole body is `pass`, 21 bare `except:`, 848 broad `except Exception`; six ways to get a Redis client, five ways to read configuration (102 raw `os.environ` reads). Almost no TODO/FIXME markers — the debt is invisible, not absent.

Two debugging traps. **Redis runs in protected mode with no password** — it refuses every non-loopback connection; publishing 6379 connects at the Docker layer and fails with `DENIED`. `CONFIG GET bind` reports `* -::*`, which looks permissive but is the implicit default, so protected mode stays up. Use `docker exec <container> redis-cli`. **`proxy_settings` is cached process-locally for 10s across four uWSGI workers** (`apps/proxy/config.py`); saving clears the cache only in the worker that handled the write, and buffering thresholds are snapshotted again in `StreamManager.__init__` — a threshold change needs >10s to reach the owning worker and must land before the channel starts.

Operationally: no metrics, `/healthz`, readiness probe or structured logs. `die-on-term` with no drain — every deploy drops every viewer and leaves Redis state behind. `os.posix_spawn` runs with no `setsid`/`PDEATHSIG`, so an ffmpeg blocked on a stalled upstream survives worker death holding a provider slot. No `harakiri`, and it can't be enabled while the relay shares a process with the API.

## Testing

`dispatcharr/test_runner.py` expands a label-less `manage.py test` via `dispatcharr/test_discovery.py` (AST-parses `INSTALLED_APPS`). 16 labels; ~1,787 backend tests, ~6,128 frontend tests.

**CI never runs the suite in one process** — `backend-tests.yml` runs each label as its own matrix job in its own container. The full in-process run has historically **failed** with a different set each time while every failure passed in its shard: `SimpleTestCase` subclasses in `test_catchup_redirect.py` reach the DB and pass only when an earlier test warmed the `CoreSettings` cache. **A green CI run does not mean a green suite.** The frontend suite passes in default order but fails under `vitest --sequence.shuffle` — module mocks and store singletons leak.

**Two path-routing defects in `labels_for_changed_paths()`:** `_PATH_ALIASES` routes `apps/vod/` → `apps.output` only, so `apps/vod/tests/` never runs for VOD changes; and a change to `live_proxy/server.py` selects only `apps.proxy.live_proxy.tests`, skipping the richest proxy tests (`apps/channels/test_ts_proxy_teardown.py` builds a real `ProxyServer` ten times) precisely when the proxy is edited. Fixing `test_discovery.py` fixes both. `_SHARED_PATH_PREFIXES` (`dispatcharr/`, `pyproject.toml`, `manage.py`, …) forces the full set.

Coverage ~45.6% backend / 71.9% frontend, **inversely correlated with criticality**: `hls_proxy` 0%, `plugins` 25%, `vod_proxy` 35.6%, `live_proxy` 38.5% vs `timeshift` 78.7%; `log_parsers.py`, which decides a stream is buffering, is 20.4%. **No backend unit test spawns a subprocess** — ffmpeg lifecycle and stderr parsing run only against hand-written strings there (the e2e suite now covers real ffmpeg lifecycle). Exactly one test file talks to a real Redis; the lease and ring buffer never meet real Redis semantics — the fakes reimplement the Lua in Python, proving the reimplementation correct while saying nothing about atomicity. The fuzz campaign contributes permanent Hypothesis property tests (`apps/proxy/live_proxy/tests/test_property_*.py`; `hypothesis` is a dev dependency).

**E2E exists now**: a Playwright suite in `e2e/` (five projects: `pristine`, `seeded`, `streaming`, `streaming-failover`, `streaming-greybox` — each its own CI job and container) runs against a shared, API-seeded AIO container (ADR `docs/adr/0001`), with `e2e-upstream/` providing a fake provider image with eight injectable faults. G4 covers the live streaming data path: TS alignment/continuity, multi-client upstream sharing, mid-stream switching, all three failover triggers, the three Stream Profile architectures, Output Profile process sharing. Read `e2e/README.md` before adding to it and `e2e/COVERAGE.md` for what is/isn't covered (the shared worklist across the seven-goal programme — updated in the same PR as the tests). `e2e-tests.yml` runs on push/PR, and the fork's **Main ruleset requires its checks on every PR** (the workflow always triggers; a `changes` job skips the heavy jobs for docs-only diffs, since a skipped job still satisfies a required check).

**The e2e suite quarantines its Redis coupling on purpose.** `e2e/fixtures/greybox/redis.ts` is the only sanctioned way a test reaches Redis; `tests/streaming-greybox/quarantine.spec.ts` enforces an importer allowlist with a test that fails naming the offender — an assertion, not a convention. Phase 3 removes Redis from the data path, at which point every greybox test is rewritten or deleted; one file keeps that a single grep. Importing it from outside `tests/streaming-greybox/` adds work to that refactor. One row is deliberately uncovered: the un-fenced ownership lease couldn't be provoked from outside the container (the owner's cleanup loop re-acquires the deleted key in <500ms; a follower only contends when channel *metadata* is absent too) — `COVERAGE.md` carries the full trace and the untried lever, recorded as a gap rather than shipped as a passing test, deliberately.

`docker-build.yml` runs on every push to `main` and publishes `ghcr.io/d10scot/dispatcharr:latest` + a full-SHA tag. `release.yml` has never run — no releases; tags stop at `v0.29.0`, inherited from upstream. Test filenames name defects, not capabilities (`test_ts_proxy_ghost_clients`, `test_xc_empty_fetch_guard`) — a free hazard map.

**Full E2E runs.** A branch named `migration/**` runs every Playwright project, including `lifecycle-upgrade`, plus both bash suites in `lifecycle-tests.yml` — the path filters are bypassed. Any other branch gets the seven-project matrix gated on changed paths; `workflow_dispatch` with `full: true` does the same on any branch. **Name the relay-extraction branches `migration/…`** so the gate applies. `Lifecycle result` is the aggregate that can be required on those branches, and must not join the Main ruleset until G12 leaves both bash suites green. Every test carries `@contract` or `@characterization` — see `docs/adr/0002-e2e-test-taxonomy.md`, enforced by `e2e/tests/guards/`.

## Build reproducibility (improving)

`uv.lock` is committed and hash-pins every resolved version (18 of 31 deps still have no exact pin in `pyproject.toml` itself); every `FROM`/`COPY --from=` in both Dockerfiles is digest-pinned. Remaining gaps: CI installs the frontend with `npm ci` but **`docker/Dockerfile` still uses `npm install`** — the shipped bundle comes from a dependency set CI never tested; the base image compiles comskip from `refs/heads/master` (no tagged release builds on current Ubuntu/FFmpeg/gcc — see comment in `docker/DispatcharrBase`) and installs Redis/PostgreSQL from unversioned apt (deliberate). Still no Python linter, formatter, type checker or pre-commit config. `lint.yml` covers actionlint, hadolint, gitleaks (full history) and `uv.lock` freshness — all as digest-pinned containers. CodeQL (`codeql.yml`) analyzes three language packs: `actions`, `python`, `javascript-typescript`.

## Supply chain security

Applies to every new or edited workflow or Dockerfile line (modeled on sibling repo `D10Scot/docker-ansible`, trimmed for a single-maintainer fork):

- **GitHub Actions**: every `uses:` is a full 40-char commit SHA with the version as trailing comment: `uses: actions/checkout@<sha>  # v6.0.1`. Resolve with a tool (`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha` or `pinact run`), never hand-typed. **First confirm `<owner>/<repo>` is the real publisher** — a plausible SHA on a same-named fork is worse than a floating tag because it *looks* pinned.
- **Docker base images**: every `FROM` is `image:tag@sha256:<digest>` — resolve with `docker buildx imagetools inspect` or `crane digest` against the official namespace. Don't hand-type digests.
- **Both are done and enforced** (hook + `actions-lint.yml`, zero-findings ratchet). The dynamic `ghcr.io/<owner>/<repo>:base` reference is resolved to a digest once per CI run and passed through a `BASE_IMAGE` build-arg, so a floating tag can't diverge mid-build. **Keep it clean**: any new `FROM`/`uses:`/`COPY --from=` gets the same tool-resolved pin.
- `renovate.json` extends `helpers:pinGitHubActionDigestsToSemver` + `docker:pinDigests`: action SHA bumps get a 7-day cooldown + human review; base-image digest and dependency patch bumps automerge after 3-day cooldown + green CI. Inert until the Renovate app is installed on the repo (a settings action, not a commit).

GHCR pushes (`docker-build.yml`, `base-image.yml`, `ci.yml`, `release.yml`) are signed and attested, each in a `sign-and-attest` job that is the *only* job holding `id-token`/`attestations` write: SBOM via `anchore/syft` (digest-pinned container, SPDX, attached with `actions/attest-sbom`); provenance via `actions/attest-build-provenance` (not build-push-action's weaker `provenance:` flag); keyless `cosign sign --yes <image>@<digest>` — verify with the identity pinned to the publishing workflow; copy-paste commands in `docs/supply-chain.md`. Also in place: Trivy + Grype + OSV-Scanner (`vuln-scan.yml`, tiered blocking), OpenSSF Scorecard (weekly, non-blocking), CodeQL. **Not** done: self-hosted vuln-DB mirror (judged unnecessary — see `docs/supply-chain.md`), per-arch Python lockfiles, GitHub secret-scanning/Dependabot toggles (repo settings), required-review enforcement (CODEOWNERS exists to enable it later).

Permission hygiene: every workflow sets top-level `permissions: contents: read` and grants more only on the job that needs it. Add `persist-credentials: false` to every `actions/checkout`.

## Conventions

Backend: DRF serializers for every endpoint (never raw dicts); routes in the app's `api_urls.py`, verified present in the drf-spectacular schema; migrations ship with model changes; Celery tasks in the app's `tasks.py` (or `core/tasks.py`), idempotent.

Tests: `CELERY_TASK_ALWAYS_EAGER` is deliberately **off** globally — `post_save` on `M3UAccount`/`EPGSource` calls `.delay()`, and eager mode runs it inside the `TestCase` transaction and poisons the connection. Opt in per-test with `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)`. `settings_test` forces plain `postgresql` (geventpool breaks `TestCase` isolation).

See `CONTRIBUTING.md` for the upstream PR process and fuller style guide.

## Agent skills

- **Issue tracker**: GitHub Issues on the fork, `D10Scot/Dispatcharr` — **always with an explicit `--repo` flag**; `gh` otherwise resolves to the upstream public tracker. See `docs/agents/issue-tracker.md`.
- **Triage labels**: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.
- **Domain docs**: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Agentic workflows (gh-aw)

Three gh-aw workflows (`.github/workflows/*.md`, compiled with `gh aw compile` — the `.md`, generated `.lock.yml`, and `.github/aw/actions-lock.json` are committed together) form a label-driven pipeline: **domain-fuzz-campaign** files findings as `needs-triage` issues with self-assigned `priority:p0–p3` → **issue-triage** validates, dedupes, audits priority, routes to `ready-for-agent`/`ready-for-human`/`needs-info`/`wontfix` (always removing `needs-triage`) → **issue-remediation** picks the highest-priority `ready-for-agent` issue, reproduces before fixing, mirrors the commit gate, passes a second-model review, opens a draft PR. `codeql-ingest.yml` is a second, non-LLM feeder: it converts open code-scanning alerts into `needs-triage` issues with suggested priorities (marker-based dedupe, max 5 per run, never p0). Remediation's `workflow_dispatch` `issue_number` input deliberately bypasses triage — human override. Docs: https://github.github.com/gh-aw/ — consult before editing.

Rules learned the hard way:

- **Auth is a personal PAT** in `COPILOT_GITHUB_TOKEN`. Never add `permissions: copilot-requests: write` — the org has no centralized Copilot billing; ignore `gh aw compile`'s tip suggesting it.
- **Deterministic `steps:` do the work, the agent does the judgment.** Writing `{"type":"noop","message":...}` to `$GH_AW_SAFE_OUTPUTS` from a pre-step and exiting 0 stops the run before the engine starts — zero AI credits; gate remaining pre-steps with `if: env.X != ''`. Stage issue bodies into workspace files and state environment facts in the prompt so the agent never spends turns on discovery.
- **The agent runs inside the gh-aw firewall container**: host services are unreachable, but `$GITHUB_WORKSPACE` and the tool cache mount at identical paths and GITHUB_ENV propagates. Build `.venv` on the host and it works in-container; stage needed binaries *into the workspace*; tests run `TEST_USE_SQLITE=1` (no Postgres there).
- **Pin actions in the `.md` by tag, not SHA** (`astral-sh/setup-uv@v10.0.1`): the compiler SHA-pins in the lock with the comment zizmor expects; a hand-placed SHA produces a `ref-version-mismatch` finding. Lint the `.lock.yml` (zizmor only reads YAML), same zero-findings ratchet.
- **Second-model review** is an inline sub-agent: a `## agent: \`name\`` block in the same file, frontmatter supports exactly `description` and `model`, extracted at activation to `.github/agents/*.agent.md`. The model must match the run's api-proxy allowlist (`apiProxy.models.agent` in the lock: `sonnet-6x`, `gpt-5.x`, `gemini-pro`, `kimi`, `any`, …). MAJOR findings loop back (max 2 cycles) and block the PR; unactioned MINOR findings become a PR comment with deferral rationale.
- **Model choice is a reliability decision, not just quality.** Any gpt-5.x main agent on security-adjacent work risks OpenAI's cybersecurity classifier killing the run mid-turn (HTTP 422 "flagged for possible cybersecurity risk", TAC program gate; retries get the same verdict — both post-property-test fuzz schedule runs died this way). Fuzz and remediation therefore run `kimi-k3` (on the allowlist, no such filter); the remediation reviewer stays `claude-sonnet-5`. If switching models, grep a failed run's log for `422` before blaming the prompt.
- **Same-run resource references**: give `create_pull_request` a `temporary_id: aw_xxx`, target it from `add_comment` with `item_number: "#aw_xxx"`.
- **Step ordering**: `pre-steps:` (before checkout) → `steps:` → cache-memory restore → `pre-agent-steps:` → engine → `post-steps:`. Anything needing `/tmp/gh-aw/cache-memory/` must be in `pre-agent-steps:`.
- Safe-outputs are the only write path (jobs run read-only); `create-pull-request` is draft-enforced and blocks `.github/workflows/` edits; label allowlists are sized to the worst case.
