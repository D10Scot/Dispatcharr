# CLAUDE.md

## Repository and direction

Fork. `origin` = `D10Scot/Dispatcharr` (push here); `upstream` = `Dispatcharr/Dispatcharr` (fetch only — push URL is the literal string `DISABLED`). Upstream targets `dev`; this fork works on `main`.

Purpose: **extract the streaming relay from the Django web workers into its own process** (control/data plane split), not a rewrite. Phase 0 harden in place → 1 extract the boundary, still Python → 2 optionally Go → 3 remove Redis from the data path. **Stopping after Phase 1 is a legitimate outcome. Resist widening scope — that is the main way this fails.**

Four investigation documents hold the detail behind every summary here. **Read the relevant one before deep work rather than re-deriving it.**

- Teardown (line-by-line behaviour) — https://claude.ai/code/artifact/7e7330e2-2fad-4e9d-a0b3-22be18c568ae
- Due diligence (gaps, defects, governance) — https://claude.ai/code/artifact/6dddf987-6135-480c-8b77-c5ad621a8c06
- Test-suite report — https://claude.ai/code/artifact/3ced4b71-c684-47e0-bf2f-b4ee1b9826cc
- Splitting the Planes (the extraction proposal) — https://claude.ai/code/artifact/149fb554-d140-4e13-abaf-2416429b2e3f

Verified at `fd413f0c` (v0.29.0); line numbers drift.

**Isolation for new work.** A new goal or any large piece of work (spans multiple files, runs
unattended, or is a `/goal`) gets its own git worktree and branch off `main` — this checkout stays
free for other work in parallel, and in-flight test-hook container state doesn't cross streams. A
small change — one file, or a handful of lines — can go straight on a new branch in this checkout,
no worktree needed.

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
npm run lint   # 112 errors/55 warnings, disabled in CI. No format script: npx prettier --write
```

- `manage.py` rewrites `DJANGO_SETTINGS_MODULE` to `dispatcharr.settings_test` for `test` only. **Never pass `--settings=dispatcharr.settings` to `test` on a live instance** — it points the suite at the production database.
- Tests need Postgres and Redis. `scripts/ci_bootstrap_backend.sh` is what CI runs, and assumes the base image's layout.
- Docker: `docker/docker-compose.{dev,aio}.yml` + `docker-compose.yml` (modular); `DISPATCHARR_ENV` picks the variant. `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh` are the repo's best integration tests — wired into no workflow.

## Test hooks (this fork only)

`.claude/settings.json` registers `PostToolUse` on `Write|Edit`, each check scoped to the file just edited. Blocking: `*tests/test_*.py` (runs the whole package), `frontend/**/*.test.jsx` (vitest), `*/models.py` (`makemigrations --check`), `live_proxy/{constants,redis_keys}.py` (`manage.py check`), `.github/workflows/*.yml` + `action.yml` + `dependabot.yml` (zizmor). Advisory: eslint on `frontend/**/*.jsx`, credential-logging grep on any `*.py`.

- The migration check resolves the app label through `apps.get_app_configs()`, never the directory name (`.claude/hooks/_pending_migrations.py`): `apps.channels` has label `dispatcharr_channels`, and the plausible guess `channels` is the *Django Channels library*, which reports "no changes" and exits 0. Guessing fails silently.
- The boot check exists because `apps/channels/models.py:6–7` imports two `live_proxy` leaf modules at module level; a cycle there breaks `manage.py check` for every command.
- eslint is advisory so 112 pre-existing errors don't punish touching legacy code; one `note` → `block` swap flips it.
- zizmor blocks on **every** finding in the edited file, legacy included — deliberately unlike advisory eslint. **The workflows are currently at zero findings** (the 101-finding backlog was cleared), so this is now a ratchet: keep it there. `--min-severity=low` in the hook would stop informational findings blocking. The same check runs in CI as `.github/workflows/actions-lint.yml`, pinned to the same zizmor version; the hook checks `zizmor --version` against that pin and warns on drift, so the two are enforced to agree — bump both together.
- zizmor's defaults already enforce three rules this repo states by hand — blanket hash-pin (`unpinned-uses`), `persist-credentials` (`artipacked`), least-privilege `permissions` (`excessive-permissions`) — so **there is deliberately no `.github/zizmor.yml`**; suppress a considered exception with a trailing `# zizmor: ignore[audit-name]` comment rather than a config entry. Online audits are **on**: `impostor-commit` catches a SHA belonging to a different repo — a pin that looks genuine and isn't — which the offline run cannot see at all. They add ~0.1s (zizmor caches HTTP), and now that every action is hash-pinned they are what keeps those pins honest. The token comes from `$GH_TOKEN`, `$GITHUB_TOKEN`, then `gh auth token` (gh keeps it in the keyring, so it must be handed over explicitly); with no token the hook degrades to offline and says so loudly. `ZIZMOR_HOOK_OFFLINE=1` opts out — **not** zizmor's own `ZIZMOR_OFFLINE`, which is a `true`/`false` flag that a `=1` collides with and breaks.
- Backend runs in `dispatcharr-testrunner` with the repo bind-mounted **read-only** at `/repo` — no sync step, and it cannot write your checkout; PG data lives in the `dispatcharr-hookdb` volume (PG won't run on a macOS bind mount). Restart with `.claude/hooks/start-test-container.sh` (idempotent, ~2s); `DISPATCHARR_TEST_CONTAINER` / `_IMAGE` / `_DB_VOLUME` override defaults.
- Deliberate, because both match CI: **Redis is flushed before every backend run** (results depend on cache state left by previous test *processes*) and **the whole package runs, not the edited module**.
- If Docker or the container is down the hook says so loudly and exits 0. **When that happens, say the tests did not run — do not describe the work as verified.**

`PreToolUse` on `Bash(git commit*)` gates commits on the tests covering whatever is **staged** (source files included), deriving labels from `scripts/ci_backend_test_labels.py` so it runs exactly what CI would; anything under `frontend/` runs the whole frontend suite, and `git commit -a` is handled. Infrastructure failures warn rather than block. Baseline **16/16** backend packages pass (~1,787 tests, 34s). `apps.timeshift.tests` used to fail on `connection is closed`; that was `CatchupProxyTests` letting `close_old_connections()` run under `TestCase`, fixed by patching it out in `setUp`. The gate inherits the two routing defects under *Testing* on purpose: it must not disagree with CI.

## Architecture

Django 6 + DRF, React 19 SPA same-origin, Celery, Redis for broker/cache/channel-layer **and the video path**, PostgreSQL for durable state. A third of the backend is `apps/proxy` (22.3k LOC) and `apps/channels` (20.8k); then `epg`, `timeshift` (Xtream catch-up), `m3u`, `core` (settings registry, profiles, events), `output`, `vod`, `plugins`, `hdhr`.

`docker/uwsgi.ini` runs uWSGI (4 workers × `gevent = 400`, `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`) with the rest as `attach-daemon`: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler, so schedules are UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. (`docker/entrypoint.aio.sh` starts gunicorn and is referenced nowhere — legacy.) Consequences constraining nearly every change in `apps/proxy`:

- Four worker processes ⇒ **no channel state may live in Python memory**.
- Early monkey-patching ⇒ the proxy's 27 `threading.Thread`s are greenlets sharing one OS thread with 400 request greenlets. **One blocking call stalls the hub** (`server.py:1740`: *"blocked on logging"*).
- `StreamManager` spawns ffmpeg with **`os.posix_spawn`** and a hand-rolled Popen-compatible wrapper because all `fork()`-based approaches hang in gevent's `_before_fork` (`input/manager.py:786–870`). **Do not "simplify" this back to `Popen`.**
- **DB backend differs per process**: uWSGI gets `django-db-geventpool` (MAX_CONNS=8, REUSE_CONNS=3); Celery and Daphne get plain `postgresql`, deliberately unpatched (`settings.py:233–264`).
- nginx **`uwsgi_buffering off`** on `/proxy/` is load-bearing — a past bug used `proxy_buffering off`, the wrong directive family for a `uwsgi_pass` upstream, and nginx spooled live TS to disk.

**State.** PostgreSQL holds durable rows. Redis holds ownership leases, channel metadata, client sets, counters and switch requests (TTL'd), **the video bytes** in a ring buffer (**~1.06 MB chunks** — `TS_PACKET_SIZE * 5644`, `input/buffer.py`'s `target_chunk_size`, overridable via `BUFFER_CHUNK_SIZE`; this doc said ~256 KB until 2026-08-28 and was wrong by 4x, which matters when reasoning about Redis memory pressure or how long a new client waits for its first chunk — at a 54 KB/s trickle a chunk takes ~20s to roll — 60s TTL), `live:events:*` pub/sub, and the Celery broker / Channels layer / Django cache. All five share **DB 0**, so video memory pressure takes out the task queue and cache with it. `scripts/wait_for_redis.py:103` does `flushdb()` on every AIO boot; the modular variant preserves only Celery prefixes and has no instance scoping.

**Video path.** Three locked built-in **Stream Profiles** are three architectures: *Redirect* (302 at the provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). The default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (how we talk upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). **There is no HLS output**: `_OUTPUT_FORMAT_MANAGERS` registers only `fmp4`, MPEG-TS (the default) uses no output-side ffmpeg at all, and the 1,206-line `apps/proxy/hls_proxy/` is dead. HLS *upstreams* are handled by forcing the ffmpeg profile.

One uWSGI worker owns a channel's upstream, elected by `redis.set("live:channel:{id}:owner", worker_id, nx=True, ex=30)` (`live_proxy/server.py:463`); followers serve their own clients from the same keys and ask the owner to act over `live:events:{id}`. `_ensure_owner_or_stop()` runs at the top of every main-loop iteration. `input/buffer.py:65–134` realigns to 188-byte TS packets before writing chunks. **The chunk index is monotonic for the channel's life and is never reset by a stream switch** — which is why a switch doesn't touch clients; new clients start ~5s behind live via the timestamp zset.

Failover has three independent triggers into `_try_next_stream()`: buffering (`speed=` < 1.0× sustained > 15s), dead air (> 10s, 3× @ 5s), connect failure (3 in 30 min). The buffering detector is **ffmpeg-exclusive** — Proxy and Redirect have no stderr, so `buffering_speed`/`buffering_timeout` are silently inert and nothing in the UI says so — and `speed=` is a cumulative average since process start, so a provider's front-loaded lead must burn off before it can arm (~55s measured, by which point the ~25s dead-air watchdog has won). It only earns its keep on *partial* degradation; `buffering_speed` above 1.0 is the lever that moves. Thresholds are snapshotted in `StreamManager.__init__`, so UI changes don't affect running channels. There is **no quality measurement at all** — bitrate is displayed, never thresholded; no continuity-counter, PCR-gap or discontinuity checks.

VOD is deliberately different: no ring buffer (`iter_content(8192)` passthrough), one upstream per session, stateless across workers, pre-stream failover only. Its stream counter's four Lua scripts bypass the metadata lock **on purpose** — a real bug fix, pinned by `vod_proxy/tests/test_vod_lock_contention.py`.

**Auth — two opposite defaults.** The REST API is deny-by-default (`DEFAULT_PERMISSION_CLASSES = ["apps.accounts.permissions.IsAdmin"]`): a view is admin-only unless it opts down, and authorization runs on `user_level` (Streamer 0 / Standard 1 / Admin 10) plus M2M to `ChannelProfile` — Django's Group/Permission tables are vestigial. Streaming is the opposite: `stream_ts` is `AllowAny`, gated only by `network_access_allowed(request, "STREAMS")`, with the STREAMS ACL defaulting to `0.0.0.0/0`. That is a deliberate concession (Plex/Jellyfin/TiviMate can't carry a bearer token on a tuner URL), and the WebSocket consumer correspondingly marks stats events admin-only. **A channel UUID is a secret; treat it as one.** If you touch the stream endpoint during the extraction, the intended replacement is a Django-minted short-lived HMAC-signed URL the relay validates statelessly.

**Routing.** `dispatcharr/urls.py` mounts Xtream endpoints (`player_api.php`, `get.php`, `/<user>/<pass>/<id>`) at the site root **before** the SPA catch-all, so root-level route additions shadow the frontend. Client surface: `/proxy/{ts/stream/<uuid>,vod,catchup}`, `/output/{m3u,epg}`, `/hdhr/`, plus the XC API's 17 actions. **Every `live_proxy` endpoint is keyed by the channel's UUID *string*, never its numeric id** — all seven routes capture `<str:channel_id>`, `stream_ts` never reassigns it, and `channel_status` passes it straight to `RedisKeys.channel_metadata()` with no DB lookup. The XC path settles which is canonical: it resolves a `Channel` and then calls `stream_ts(request._request, str(channel.uuid), ...)`. Passing `channel.id` to `/status/`, `/change_stream/`, `/next_stream/` or `/stop/` returns 404 for every channel, always. No SSDP/UPnP discovery exists for the HDHomeRun emulation, and the generated M3U emits no `catchup=` attributes (advertised only via XC `tv_archive`).

**Observing a channel.** `GET /proxy/ts/status/<uuid>` (admin-only) is the only status surface, and four of its fields will mislead you. `owner` falls back to the literal string `'unknown'` and is **never null**, so a truthiness check on it passes when nobody owns the channel. `total_bytes` and `avg_bitrate_kbps` are assigned only inside conditionals and can be **absent entirely**, as can `stream_id`/`stream_name` — absent, not null, so the value is `undefined` rather than something you can compare. And `ffmpeg_speed` is a **string**: `get_detailed_channel_info` assigns the raw Redis value with no conversion while the neighbouring `get_basic_channel_info` wraps it in `float()`, so the per-channel and collection endpoints genuinely disagree about that field's type. **There is also no WebSocket event for a stream switch, a failover or a client teardown** — `channel_stats` is the only thing `live_proxy` emits, its payload arrives as a JSON-encoded *string* under `data.stats`, and the bare `GET /proxy/ts/status` broadcasts it as a side effect of being polled. Observe transitions by polling the per-channel endpoint, not by waiting on the socket.

**Events and plugins.** Every interesting transition calls `log_system_event()` (`core/utils.py:751–825`), writing a `SystemEvent` row and fanning out to Connect (webhook/script/API) on its own greenlet; the vocabulary is a fixed dict at `apps/connect/models.py:3–21`. **This is the extension point to use before adding polling anywhere.** Plugins live outside `INSTALLED_APPS` in `/app/data/plugins/<name>/` (see `Plugins.md`) and run arbitrary Python in-process, unsandboxed; `autodiscover_tasks()` can't see them, so `dispatcharr/celery.py` calls `PluginManager.discover_plugins()` in `worker_process_init` — per forked child, deliberately not the parent, so children don't inherit DB connections.

**Frontend.** `frontend/src/store/*.jsx` — Zustand, one store per domain; **new global state goes here, not React Context**. `frontend/src/api.js` — all HTTP; **components must not call fetch/axios directly**. `frontend/src/WebSocket.jsx` — one consumer on `/ws/` carrying a generic `updates` group. Mantine 8; **do not add UI libraries.** `api.js` and `WebSocket.jsx` are the two largest files in the tree with no tests at all.

## Structural constraints on refactoring

- **The apps are a mesh, not a stack**: 367 cross-app imports over 50 edges, four cycles centred on `channels`. Extracting the relay pulls in `channels` → `m3u`/`epg` → back. There is no clean seam.
- `apps/channels/models.py:6–7` imports `RedisKeys` and `ChannelMetadataField` from `apps.proxy.live_proxy` at **module level** — a models module, loaded by every migration and management command, depending on the streaming package. It survives only because those are leaf modules: **add one import to `live_proxy/constants.py` and Django stops booting.** Hence 602 function-local imports.
- Good news: all non-test `apps/proxy/` contains **exactly one ORM write**. The obstacle is 24 reverse-import sites and reads of 14 model classes, not transactional coupling.
- Complexity is concentrated: 111 functions hold 43% of all function lines — `fetch_schedules_direct()` (1,323 lines), `run_recording()` (1,139, 47 `try` blocks), `sync_auto_channels()` (1,010). `apps/timeshift/views.py` is long but well-factored.

## Known defects and traps

Verified. **Don't "fix" surrounding code without knowing these are already there, and don't reintroduce them in new code.**

Security — treat the first as an incident, not a backlog item:

- Provider credentials logged at **INFO**: `vod_proxy/views.py:628` (full path + entire header dict; Xtream URLs carry the password in the path), `m3u/tasks.py:3084`, `channels/tasks.py:1577` and `:1633`. Anyone who shared a support log shared working credentials.
- `docker/docker-compose.yml` publishes Postgres on `5436:5432` (all interfaces) as `dispatch`/`secret`.
- `settings.py:72` `ALLOWED_HOSTS=["*"]`, `:447` `CORS_ALLOW_ALL_ORIGINS=True`, `:448` `CSRF_TRUSTED_ORIGINS=["http://*","https://*"]` — none conditioned on `DEBUG`.
- Xtream passwords plaintext in `custom_properties["xc_password"]`, compared with `!=`; API keys looked up by plaintext value, unscoped.

Correctness:

- **The ownership lease is time-bounded, not fenced.** `StreamBuffer.add_chunk()` writes with no ownership check and no fencing token, so two owners interleave chunks at alternating monotonic indices — readers decode a spliced stream with every consistency check passing. The lease also **fails open** three ways (`live_proxy/server.py:465`, `:477`, and `_execute_redis_command` swallowing exceptions to `None`); `release_ownership` does GET→compare→DELETE and `extend_ownership` GET→EXPIRE, both non-atomically. **If you carry this design forward, put the lease token in the write path via Lua and never fail open.**
- Channel preemption is dead code — `_pick_channel_to_preempt()` is implemented, but `apps/channels/models.py:795–804` has the `return` commented out.
- `get_preferred_region_code()` can never succeed (`core/migrations/0020` deleted the row it reads), so EPG matching runs with no regional weighting, silently. The live accessor `CoreSettings.get_preferred_region()` works; the matcher just doesn't call it.
- **Both scheduler migration reverses are broken**: `epg/migrations/0007` deletes *every* `IntervalSchedule` and `PeriodicTask` in the system; `m3u/migrations/0006` filters by `name`, a field `IntervalSchedule` has never had (`FieldError`). 16 migrations have no reverse at all, and nothing in CI exercises reverse migrations or `makemigrations --check`.
- The channel-authorization filter is copy-pasted across **eight** sites; `output/views.py:593` uses `"channels__user_level": 0` instead of `__lte`. `hide_adult_content` is applied in listing paths but **not** in `live_proxy/views.py`, `timeshift/views.py` or `hdhr/api_views.py` — hidden channels are unlistable yet still streamable. The one extracted helper is `_user_can_access_channel` (`apps/timeshift/views.py:771`).
- The channel-stopping key is written `setex(..., 60, ...)` on five paths and `setex(..., 30, ...)` on three — a race generator.
- `MAX_STREAM_SWITCHES` doesn't bound buffering-triggered switches: they come from the stderr greenlet, bypassing the main loop's counter.
- The fMP4 generator's `_is_timeout()` lacks the TS generator's `url_switching` exemption, so fMP4 viewers can be dropped at 40s during a slow failover.

Dead or unwired: `apps/proxy/hls_proxy/`; `dispatcharr/persistent_lock.py` (no callers; `refresh()` sets `has_lock = False` on the success path, and an instance attribute shadows the `has_lock` method); `_attempt_health_recovery()` (`manager.py:1651`); `head_vod()` (no route); `MAX_HEALTH_RECOVERY_ATTEMPTS` / `MAX_RECONNECT_ATTEMPTS` / `MIN_STABLE_TIME_BEFORE_RECONNECT` (`config.py:117–119` — the real values are bare literals in the health-monitor body); `M3UAccount.stream_profile`; `HDHRDevice.tuner_count`.

Style debt worth knowing before adding to it: 236 exception handlers whose whole body is `pass`, 21 bare `except:`, 848 broad `except Exception`; six ways to get a Redis client and five ways to read configuration, including 102 raw `os.environ` reads. Two TODOs repo-wide and no FIXME/HACK/XXX — the debt is invisible, not absent.

Two traps worth knowing before you debug either subsystem. **Redis runs in protected mode with no password**, so it refuses every non-loopback connection — publishing port 6379 connects at the Docker layer and fails at the Redis layer with `DENIED`. `CONFIG GET bind` reports `* -::*`, which looks permissive and is not: protected mode only stands down when the bind was set *explicitly*, and that value is the built-in default of a bare `redis-server`. Reach it with `docker exec <container> redis-cli` instead. **And `proxy_settings` is cached process-locally for 10 seconds across four uWSGI workers** (`apps/proxy/config.py`, `_proxy_settings_cache_ttl`); saving the row calls `clear_proxy_settings_cache()` only in the worker that handled the write, and the buffering thresholds are snapshotted again in `StreamManager.__init__` — so a threshold change needs >10s to reach the worker that ends up owning a channel, and must land before that channel starts.

Operationally: no metrics, `/healthz`, readiness probe or structured logs. `die-on-term` with no drain and no shutdown hook, so every deploy drops every viewer and leaves Redis state behind. `os.posix_spawn` runs with no `setsid`/`PDEATHSIG`, so an ffmpeg blocked on a stalled upstream survives worker death holding a provider slot. No `harakiri`, and it can never be enabled while the relay shares a process with the API.

## Testing

`dispatcharr/test_runner.py` expands a label-less `manage.py test` via `dispatcharr/test_discovery.py`, which AST-parses `INSTALLED_APPS`. 16 labels; 130 backend files (1,787 tests), 202 frontend files (6,128 tests).

**CI never runs the suite in one process** — `backend-tests.yml` runs each label as its own matrix job in its own container, so every test gets a fresh interpreter and database. The full in-process run has historically **failed** with a different set each time while every failing test passed in its shard. The constant one (`timeshift…test_missing_session_id_redirects`) is now fixed — it died on `the connection is closed` because `catchup_proxy` calls `close_old_connections()` on every return, which under `TestCase` closes the connection holding the test transaction. The remainder are `SimpleTestCase` subclasses in `test_catchup_redirect.py` that reach the DB and pass only when an earlier test warmed the `CoreSettings` cache; those are **not** fixed. **A green CI run does not mean a green suite.** The frontend suite passes in default order but fails under `vitest --sequence.shuffle` — module mocks and store singletons leaking.

**Two path-routing defects in `labels_for_changed_paths()`:** `_PATH_ALIASES` routes `apps/vod/` → `apps.output` only, so `apps/vod/tests/` never runs for VOD changes; and a change to `live_proxy/server.py` selects only `apps.proxy.live_proxy.tests`, skipping the richest proxy tests (`apps/channels/test_ts_proxy_teardown.py` builds a real `ProxyServer` ten times) precisely when the proxy is edited. Fixing `test_discovery.py` fixes both. `_SHARED_PATH_PREFIXES` (`dispatcharr/`, `pyproject.toml`, `manage.py`, …) forces the full set.

Coverage is 45.6% backend / 71.9% frontend and **inversely correlated with criticality**: `hls_proxy` 0%, `plugins` 25%, `vod_proxy` 35.6%, `live_proxy` 38.5% vs `timeshift` 78.7%; `log_parsers.py`, which decides a stream is buffering, is 20.4%. **Nothing is tested end to end** — no Playwright/Cypress/Selenium, no `LiveServerTestCase`, and **no test spawns a subprocess**, so ffmpeg lifecycle and stderr parsing run only against hand-written strings. Exactly one test file talks to a real Redis; the lease and ring buffer never meet real Redis semantics, and the fakes reimplement the Lua in Python — proving the reimplementation correct while saying nothing about atomicity. Nothing gates on any of it: `ci.yml`, `release.yml` and `docker-build.yml` have no test job in their `needs:` graph, and upstream has no branch protection. (**Correction, 2026-08-28:** this doc previously said `docker-build.yml` "has never run and is broken by construction". It runs on every push to `main` and its `build-and-push` job **succeeds**, publishing `ghcr.io/d10scot/dispatcharr:latest` and a full-40-char-SHA tag per push. The workflow showed red only because the separate `sign-and-attest` job hit a GitHub attestation-storage billing restriction on a private fork; making the repo public cleared it. `release.yml` genuinely has never run — no releases exist and tags stop at `v0.29.0`, inherited from upstream.) Test filenames name defects, not capabilities (`test_ts_proxy_ghost_clients`, `test_xc_empty_fetch_guard`) — a free hazard map.

## Builds are not fully reproducible (improving)

As of PR #4 (2026-08-23 hardening pass): `uv.lock` is committed (previously gitignored, 18 of 31 dependencies still have no exact pin in `pyproject.toml` itself, but the lockfile now pins and hashes every resolved transitive version regardless); every `FROM`/`COPY --from=` in both Dockerfiles is digest-pinned, including the dynamic base (see "Supply chain security" above). Remaining, real gaps: CI installs the frontend with `npm ci` but **`docker/Dockerfile:14` still uses `npm install`**, so the shipped bundle comes from a dependency set that was never tested by CI; the base image still compiles comskip from `refs/heads/master` (no tagged release builds on current Ubuntu/FFmpeg/gcc — see the comment in `docker/DispatcharrBase`) and installs Redis/PostgreSQL from unversioned apt (deliberate — see "OS patches applied at build time"). There is also still no Python linter, formatter, type checker or pre-commit config, and no CodeQL/SAST over the *application* code (only over the GitHub Actions workflows themselves, via `codeql.yml`'s `actions` language pack) or Bandit.

## Supply chain security

New rules, applying from now on — not true of existing history. Modeled on the sibling repo `D10Scot/docker-ansible`, trimmed to what a self-hosted fork with one maintainer needs.

Pinning — apply to every new or edited workflow or Dockerfile line:

- **GitHub Actions**: every `uses:` is a full 40-character commit SHA, never a tag (`@v4`, `@main`, `@latest`), with the version as a trailing comment: `uses: actions/checkout@<sha>  # v6.0.1`. Resolve with a tool, never type or guess one — `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha` or `pinact run`. **Before** resolving, confirm `<owner>/<repo>` is the action's real publisher (the org named in its own README or Marketplace listing): a short name like `checkout` can exist under any account, and a plausible SHA on a same-named fork is worse than a floating tag because it *looks* pinned. A SHA that isn't the literal output of a resolution command run against a confirmed upstream is not a valid pin.
- **Docker base images**: every `FROM` is `image:tag@sha256:<digest>` — tag for readability, digest enforced. Resolve with `docker buildx imagetools inspect <image>:<tag>` or `crane digest`, against the official namespace (`docker.io/library/*`, `ghcr.io/<real-owner>/*`, `lscr.io/linuxserver/*`). Don't hand-type a digest.
- **Workflows and Dockerfiles are both done** (as of the `harden-supply-chain` branch/PR #4): every `uses:` across all 12 workflows is SHA-pinned, publisher-verified, and zizmor-clean (enforced by the hook and `actions-lint.yml`); `docker/Dockerfile` and `docker/DispatcharrBase` digest-pin every base image, including the dynamic `ghcr.io/<owner>/<repo>:base` reference — CI resolves that tag to a digest once per run (see the "Resolve base image digest" steps in `ci.yml`/`docker-build.yml`/`release.yml`) and passes it through a `BASE_IMAGE` build-arg, so a floating tag can never diverge mid-build. **Keep this clean going forward** — any new `FROM`/`uses:`/`COPY --from=` needs the same digest pin, resolved with a tool per the rule above, not hand-typed.
- `renovate.json` exists, extending `helpers:pinGitHubActionDigestsToSemver` + `docker:pinDigests`, with `docker-ansible`'s asymmetry: **action SHA bumps get a 7-day cooldown and require human review**, **base-image digest and dependency patch bumps automerge after a 3-day cooldown + green CI**. It does nothing until the Renovate GitHub App (or a self-hosted runner) is actually installed on this repo — that's a repo-settings action, not something a commit can do.

Distributed artifacts (GHCR pushes from `docker-build.yml`, `base-image.yml`, `ci.yml`, `release.yml`) — signed and attested as of PR #4, in a `sign-and-attest` job per workflow that is the *only* job in each holding `id-token`/`attestations` write:

- **SBOM**: generated with `anchore/syft` (digest-pinned container, not the `anchore/sbom-action` marketplace action), SPDX format, attached via `actions/attest-sbom`.
- **Provenance**: `actions/attest-build-provenance`, not `docker/build-push-action`'s weaker built-in `provenance:` flag.
- **Signing**: `cosign sign --yes <image>@<digest>` keyless (GitHub OIDC/Fulcio). Verify with the identity pinned to the actual publishing workflow: `--certificate-identity-regexp='^https://github\.com/D10Scot/Dispatcharr/\.github/workflows/<file>\.yml@refs/.*$'` — see `docs/supply-chain.md` for copy-paste commands.
- The rest of `docker-ansible`'s posture — Trivy + Grype + OSV-Scanner (`vuln-scan.yml`, tiered blocking policy), OpenSSF Scorecard (`scorecard.yml`, weekly, non-blocking), CodeQL's `actions` language (`codeql.yml`) — is now in too, per the 2026-08-23 hardening pass (PR #4). **Not** done: a self-hosted vulnerability-DB mirror (Trivy/Grype's own signature/checksum verification was judged sufficient for a single-maintainer fork's threat model — see `docs/supply-chain.md`), per-arch hash-pinned Python lockfiles beyond the single universal `uv.lock`, GitHub's native secret-scanning/Dependabot toggles (repo settings, not files), and branch protection / required-review enforcement (CODEOWNERS exists to make that enforceable later, but nothing currently requires it).

Permission hygiene: every workflow sets `permissions: contents: read` at the top level and grants more (`packages: write`, `id-token: write` for cosign/attestations) only on the job that needs it, never at workflow level. Add `persist-credentials: false` to every `actions/checkout` — nothing here needs the token to survive the checkout.

## Conventions

Backend: DRF serializers for every endpoint (never return raw dicts); register routes in the app's `api_urls.py` and verify they appear in the drf-spectacular schema; ship migrations with model changes; Celery tasks go in the app's `tasks.py` (or `core/tasks.py`) and must be idempotent.

Tests: `CELERY_TASK_ALWAYS_EAGER` is deliberately **off** globally — `post_save` on `M3UAccount`/`EPGSource` calls `.delay()`, and eager mode runs it inside the `TestCase` transaction and poisons the connection. Opt in per-test with `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)`. `settings_test` also forces the plain `postgresql` backend rather than `django-db-geventpool`, which breaks `TestCase` isolation on pooled connections.

See `CONTRIBUTING.md` for the upstream PR process and fuller style guide.

## Agent skills

### Issue tracker

GitHub Issues on the fork, `D10Scot/Dispatcharr` — **always with an explicit `--repo` flag, never inferred.** This clone is a fork of `Dispatcharr/Dispatcharr`, so `gh` resolves to the upstream public tracker whenever no default is set; the `DISABLED` push URL does not guard against that. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, label strings equal to their names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Agentic workflows (gh-aw)

Three GitHub Agentic Workflows (`.github/workflows/*.md`, compiled with `gh aw compile` — the `.md`, the generated `.lock.yml`, and `.github/aw/actions-lock.json` are all committed together) form a label-driven pipeline: **domain-fuzz-campaign** files findings as issues labelled `needs-triage` + self-assigned `priority:p0–p3` → **issue-triage** validates, dedupes, audits the priority against the rubric, and routes to `ready-for-agent`/`ready-for-human`/`needs-info`/`wontfix` (always removing `needs-triage`) → **issue-remediation** picks the highest-priority `ready-for-agent` issue (run-seeded random among ties), reproduces before fixing, mirrors the commit gate for verification, passes a second-model review, and opens a draft PR. The `workflow_dispatch` `issue_number` input on remediation deliberately bypasses the triage gate — human override. Docs: https://github.github.com/gh-aw/ — consult before editing; the reference sections on frontmatter, safe-outputs, and tools answer most questions.

Rules that hold for every workflow here, learned the hard way:

- **Auth is a personal PAT** in the `COPILOT_GITHUB_TOKEN` secret. Never add `permissions: copilot-requests: write` — the org has no centralized Copilot billing (PR #23); `gh aw compile` emits a tip suggesting it every time — ignore the tip.
- **Token economy: deterministic `steps:` do the work, the agent does the judgment.** Selection, environment bootstrap, and context staging are plain scripts. Writing `{"type":"noop","message":...}` to `$GH_AW_SAFE_OUTPUTS` from a pre-step and exiting 0 stops the run before the engine starts — zero AI credits; gate the remaining pre-steps with `if: env.X != ''` (GITHUB_ENV values are visible to later steps' `if`). Stage issue bodies/comments into workspace files (`.issue-context/issue-N.md`) and state environment facts in the prompt so the agent never spends turns on discovery.
- **The agent runs inside the gh-aw firewall container**: host services (a Redis you started, localhost anything) are unreachable, but `$GITHUB_WORKSPACE` and the tool cache are mounted at identical paths and GITHUB_ENV propagates. So: build `.venv` on the host and it works in-container; stage needed binaries *into the workspace* (`.fuzz-env/bin/redis-server`); tests run with `TEST_USE_SQLITE=1` because Postgres isn't there.
- **Pin actions in the `.md` by tag, not SHA** (`astral-sh/setup-uv@v10.0.1`): the compiler resolves and SHA-pins in the lock with the version comment zizmor expects; a hand-placed SHA in the `.md` produces a bare-SHA comment and a `ref-version-mismatch` finding. Lint the `.lock.yml` (zizmor only accepts YAML), same zero-findings ratchet as the rest of the repo.
- **Second-model review** is an inline sub-agent: a `## agent: \`name\`` block in the same workflow file, frontmatter supports exactly `description` and `model` (gh-aw ADR-29793), extracted at activation to `.github/agents/*.agent.md`. The model must match the run's api-proxy allowlist (see `apiProxy.models.agent` in the lock — `sonnet-6x` covers sonnet-4.5/4.6/5). Remediation's reviewer is claude-sonnet-5; MAJOR findings loop back (max 2 cycles) and block the PR, unactioned MINOR findings become a PR comment with per-item deferral rationale.
- **Referencing a resource created in the same run**: give `create_pull_request` a `temporary_id: aw_xxx`, then target it from `add_comment` with `item_number: "#aw_xxx"` — resolved after creation, deferred until then.
- **Step ordering**: `pre-steps:` (before checkout) → `steps:` (after checkout) → cache-memory restore → `pre-agent-steps:` → engine → `post-steps:`. A step that needs `/tmp/gh-aw/cache-memory/` (fuzz's domain rotation) must be in `pre-agent-steps:`, not `steps:`.
- Safe-outputs are the only write path (jobs run with read-only permissions); `create-pull-request` is draft-enforced and its protected-files rules block `.github/workflows/` edits; `add-labels`/`remove-labels` use explicit allowlists sized to the worst case (a priority swap + routing = 2 adds, 2 removes).
