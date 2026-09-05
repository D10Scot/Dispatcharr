# Phase 1 PR 4 — Process Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the relay its own uWSGI process (`docker/uwsgi.relay.ini`, one `relay-uwsgi`
supervisord program) and its own nginx location table, with a request timeout and worker
recycling enabled on the API for the first time — in both the AIO and modular deployment shapes —
without changing one line of relay internals.

**Architecture:** A second uWSGI process (`socket = 0.0.0.0:5657`, `workers = 1`,
`gevent = $(DISPATCHARR_RELAY_GEVENT)`, no `harakiri`) runs the same Django code as the API
process under the same urlconf (D1 — no role-scoped urlconf exists or is added). nginx grows a
`relay_py` upstream and a full location table that sends every long-lived stream surface —
`/proxy/ts/stream/`, the rest of `/proxy/vod/`, `/proxy/catchup/<uuid>`, the six XC streaming
roots, `/streaming/timeshift.php` — to it with `uwsgi_buffering off`, while the API process gains
`harakiri`/`max-requests` now that it no longer serves four-hour streams. The modular compose file
gains a `relay` service sharing the `web`/`celery` services' `/data` volume (D11: `SECRET_KEY`
comes from `/data/jwt`, and a relay with a different key 403s every internal call once PR 5/6 add
internal HMAC auth). No `auth_request`, no trust headers, no `next-source` HTTP call, no control
API — those are PR 5, PR 6 and PR 7. The two legitimate stopping points after this PR (spec
§ Goal) are why PR 4's own done criteria stand alone: a request timeout on the API, a separate
relay process, and zero relay-internals changes.

**Tech Stack:** uWSGI 2.0.31 ini files, supervisord 4.3.0 process configs (already landed by
PR 3), nginx 1.24.0 (`--with-http_auth_request_module`, unused until PR 5) location-table
directives, `docker-compose.yml`, bash (`docker/entrypoint.sh`, `docker/init/03-init-dispatcharr.sh`,
`docker/tests/test-puid-pgid.sh`), Django (`apps/channels/tasks.py`), Playwright + TypeScript
(`e2e/`).

**Spec:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` § The eight pull
requests › PR 4 — `migration/phase1-process-split`.

**Branch:** `migration/phase1-process-split` (worktree `.worktrees/phase1-pr4`), off `main`.

## Branch base

This branch was cut from PR 3's branch, so PR 3's work is already in this worktree as ordinary
file content. **PR 4 executes only after PR 3 has merged to `main`.** Task 1 is the gate: the
executor merges `origin/main` into this branch first, and PR 3's commits arrive **squashed** —
`main` will carry one commit whose tree matches PR 3's, not PR 3's individual commits.

Two consequences bind every task below:

- **This plan cites no PR 3 commit hash anywhere, and neither may the executor.** After a squash
  merge the hashes on this branch no longer exist on `main`, and `git merge-base --is-ancestor`
  answers "no" for a PR 3 that has demonstrably merged. Every check in Task 1 is therefore a check
  on **file content**, not on git history.
- **Every file:line in this plan was verified against this worktree before the merge.** Line
  numbers drift; the tree wins. Task 1 Step 2 re-runs the greps that matter and says what to do
  with each answer.

## Spec amendments made by this plan

House convention: a plan may not silently diverge from its spec. Each amendment below is applied to
`docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` **in this PR**, by Task 13
Step 5, quoting the text it replaces.

| # | Spec location | Amendment | Why |
| --- | --- | --- | --- |
| **S1** | § PR 4, the `docker/docker-compose.yml` bullet | The new `relay` service also carries `stop_grace_period: 160s`, and `web` gains `depends_on: relay: condition: service_started` rather than only the two environment lines. `web` already has `DISPATCHARR_ROLE=api`. | nginx resolves `upstream relay_py { server relay:5657; }` **once, at start**. A `web` container that comes up with no `relay` in DNS fails config load with "host not found in upstream" and `[program:nginx]` goes BACKOFF then FATAL — the whole API surface, not just streaming. `160s` is the value PR 3 set uniformly on every supervisord-backed service in that file, sized to the sum of a rung's `stopwaitsecs` because supervisord's shutdown walk is sequential per priority group. `DISPATCHARR_ROLE=api` on `web` is already in the tree. |
| **S2** | § PR 4, the `relay-uwsgi` program bullet's closing sentences | `docker/init/04-check-hwaccel.sh` moves out of the `all`/`api` gate into its own `if [[ "$DISPATCHARR_ROLE" != "worker" ]]` block, so `relay` gets the report too. | **This reverses the hwaccel note PR 3 added to § PR 4** (PR 3 plan amendment A11 — the letter names a row in `docs/superpowers/plans/2026-09-04-phase1-pr3-supervisord.md`, not anything in the spec, so nothing this PR writes into the spec or the tree may cite it), which recorded the gap as "a deliberate PR 4 decision rather than a rediscovery". PR 4 is where that decision gets made, and it goes the other way: from this PR on, `apps/proxy/live_proxy/`'s ffmpeg spawning runs in the relay process's request path, so the diagnostic answering "can this process reach a GPU" is printed by the wrong container unless it moves. The script is pure diagnostics — every line an `echo`, nothing exported downstream — so running it in one more role costs boot log and nothing else. |
| **S3** | § Decisions, the **D6** row | The **`dev` branch keeps `http://127.0.0.1:5656`**; only AIO (and `debug`, which is `DISPATCHARR_ENV=dev` plus `DISPATCHARR_DEBUG=true`… see the row's own text) moves to `DISPATCHARR_PORT`. | D6 as written breaks the DVR in dev. `docker/supervisord/all-dev.conf`'s `[include]` names `vite.conf`, **not** `nginx.conf` — dev runs no nginx at all — and `frontend/vite.config.js` proxies only `/api` (to `127.0.0.1:5656`) and `/ws`. A DVR fetching `/proxy/ts/stream/<uuid>` through `DISPATCHARR_PORT` in dev would record vite's `index.html`. **PR 5 must know this**: in dev a recording still bypasses the authorize hop, and the authorize design must not assume every DVR fetch crosses nginx. |
| **S4** | § PR 4, the `apps/channels/tasks.py` bullet | `apps/channels/tests/test_dvr_port_resolution.py` has **three** `5656` assertions, not four; two become `9191` and the `dev` one stays. | `grep -n "5656" apps/channels/tests/test_dvr_port_resolution.py` returns three test methods (`test_aio_default_uses_localhost_5656`, `test_aio_explicit_uses_localhost_5656`, `test_dev_mode_uses_localhost_5656`) against a file of eight tests. The spec's "four" is simply wrong, and after S3 only two of the three change. |
| **S5** | § Architecture, the location table; and § PR 4, the `docker/nginx.conf` bullet | A **fifth nested regex location inside `^~ /api/`** sends `GET /api/channels/recordings/<pk>/file/` to the relay: `location ~ ^/api/channels/recordings/\d+/file/$` with `uwsgi_buffering off` and the same read/send timeouts every other relay-bound location carries. | It is the one long-lived response the API serves, and the spec's table left it there. `RecordingViewSet.file` (`apps/channels/api_views.py`, the `file` action; routed by `apps/channels/api_urls.py`'s `DefaultRouter`, `trailing_slash=True`) returns a `StreamingHttpResponse` over the recorded MKV/MP4 with Range support, gated by `network_access_allowed(request, "STREAMS")` and used by the DVR UI for playback — hours, not seconds. Under this PR's new `harakiri = 120` on the API it would be killed partway through every playback, taking that gevent worker's other ~400 in-flight requests with it. Routing it to the relay keeps the same urlconf, view and DRF authentication (D1) and changes nothing under `apps/channels/` (D10). Its sibling `recordings/<pk>/hls/<seg_path>` stays on the API: HLS segments are small files, not one long response. |

No other divergence from the spec exists. The `all-debug.conf` sixth rung the spec once implied,
the `web` service's `DISPATCHARR_ROLE=api`, and the `160s` versus `45s` `stop_grace_period` were
all settled by PR 3 and are already correct in both the tree and the spec.

## Global Constraints

- **Relay uWSGI has exactly one listener**: `socket = 0.0.0.0:5657` (uwsgi protocol), no `http =`
  (D5). `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)` (default **1600**), `listen = 1024`,
  `socket-timeout = 600` (carried from `uwsgi.ini`, unchanged). **No `harakiri` on the relay, ever**
  — it exists to serve the long-lived responses a timeout would kill.
- **API uWSGI gains `harakiri = $(DISPATCHARR_API_HARAKIRI)` (default 120), `harakiri-verbose =
  true`, `max-requests = $(DISPATCHARR_API_MAX_REQUESTS)` (default 5000)** — `docker/uwsgi.ini`
  and `docker/uwsgi.modular.ini` only, not `uwsgi.dev.ini` or `uwsgi.debug.ini` (debug already
  carries its own `harakiri = 3600` for debugging-session length).
- **uWSGI expands `$(VAR)` from its own process environment, not `${VAR:-default}`** — the three new
  vars must be `export`ed in `docker/entrypoint.sh` before `exec supervisord`, with the same
  `export X=${X:-default}` shape the file already uses for `UWSGI_NICE_LEVEL`/`CELERY_NICE_LEVEL`.
- **`relay-uwsgi`'s `stopwaitsecs=20`** is the longest of any supervisord program in this tree and
  is what PR 8's bounded-restart ceiling (N ≤ 30s) is derived from.
- **`stop_grace_period: 160s`** on the new `relay` service — the value PR 3 set on every other
  supervisord-backed service in `docker/docker-compose.yml` (S1).
- **`web` must `depends_on` `relay` with `condition: service_started`** (S1) — nginx resolves the
  `relay_py` upstream once at config load, and a missing `relay` container is a hard nginx failure,
  not a per-request 502.
- **`RELAY_UPSTREAM` is a bare placeholder with no `$`**, substituted by `sed` in
  `docker/init/03-init-dispatcharr.sh` exactly as `NGINX_PORT` already is: `127.0.0.1:5657` outside
  modular, `${DISPATCHARR_RELAY_HOST:-relay}:${DISPATCHARR_RELAY_PORT:-5657}` in modular.
- **`^~` goes on every specific non-root prefix location, never on `/`.** `^~` on `/` would disable
  every regex in the file — the XC three-segment regex this PR adds, the admin→`/login`
  redirect, and all four image-cache regexes. `=` and `^~` are mutually exclusive on one location.
  The XC three-segment regex is **new in this PR**: PR 2 narrowed `XC_STREAM_ID_PATTERN` in Django
  and added tests, but `docker/nginx.conf` has no regex for that form today. Task 5 places it
  **after** the admin regex, and it must stay there: nginx takes the first matching regex in file
  order, and `/admin/<password>/<channel_id>` (XC username literally `admin`) must reach the XC
  branch through the admin regex's own negative lookahead.
- **`uwsgi_pass` to a variable needs a `resolver`; `uwsgi_pass` to a declared `upstream` group name
  does not.** This is why `docker/nginx.conf` gains `upstream relay_py { server RELAY_UPSTREAM; }`
  and every relay-bound location does `uwsgi_pass relay_py;` (a literal group name), not
  `uwsgi_pass $some_variable;`.
- **D1 — same image, same Django settings, same urlconf in both processes.** No role-scoped urlconf
  is created. A misrouted request is served correctly by the wrong process, never 404s at the nginx
  layer (same urlconf, same views).
- **D10 — nothing under `apps/proxy/live_proxy/`, `vod_proxy/` or `apps/timeshift/`'s streaming path
  changes.** This PR is nginx/uwsgi/supervisord/compose/one Django task-helper function; zero lines
  in those three trees.
- **D14 — the relay role runs no nginx.** `docker/supervisord/relay.conf` stays `relay-uwsgi` only
  (via its `relay-*.conf` glob); no `[program:nginx]` is added there.
- **D6, as amended by S3 — `get_dvr_stream_base_url()`'s AIO branch changes from
  `127.0.0.1:5656` to `127.0.0.1:{DISPATCHARR_PORT:-9191}`; the `dev` branch keeps
  `127.0.0.1:5656`** because dev runs vite and no nginx. Modular and explicit-override branches
  unchanged.
- **`RUNNING` is not `listening`.** `docker/tests/test-puid-pgid.sh:180`'s own header says it:
  `startsecs=5` means the program stayed alive five seconds, and `relay-uwsgi` runs through
  `wait-for-stores.sh`, so it is RUNNING while the wrapper is still waiting and uWSGI has not been
  exec'd. **Any assertion that issues an HTTP request must poll `supervisorctl status` for RUNNING
  *and then* retry the request itself on 502/503/504** (Tasks 11, 12, 14).
- **Every `.py` edit is checked by `scripts/check_credential_logging.py`** (blocking hook). Task 9's
  change to `apps/channels/tasks.py` logs no new URL or header — the existing `redact_url(base_url)`
  call is unchanged.
- **`*/models.py` edits run `makemigrations --check`** — not applicable; no model changes.
- **`e2e/**/*.ts` edits are checked by `tsc --noEmit`** (blocking hook) — run after every `e2e/`
  edit (Tasks 10, 11).
- **Every new Playwright `test()` carries exactly one of `@contract`/`@characterization`**
  (`docs/adr/0002-e2e-test-taxonomy.md`, enforced by `e2e/tests/guards/tags.spec.ts`). This PR adds
  zero new `test()` calls — Task 10 widens an existing test's location filter, Task 11 adds
  assertions inside the existing `@characterization` test in `restart-persistence.spec.ts`. **No
  `e2e/tests/guards/allowlist.ts` *entry* changes**: `fixtures/instance.ts` is already on the
  `CONTAINER_LIFECYCLE`, `SUBPROCESS` and `CONTAINER_INTROSPECTION` lists, and
  `tests/streaming-greybox/nginx-stream-buffering.spec.ts` is already on `SUBPROCESS` — Task 10
  Step 2 edits one stale *comment* in that file and nothing else. `capabilities.spec.ts` matches its
  markers (`pgrep`, `docker `, `manage.py`) in string and template literals only, never in comments,
  so neither that edit nor any new comment in the two changed specs can move a guard. No
  `e2e/COVERAGE.md` row is added, because no row is created or retired: both changed specs keep
  their existing COVERAGE lines.
- **A heredoc opened with `<<'WORD'` takes its terminator at column 0, and its body verbatim.**
  Task 12 embeds a Python script in `docker/tests/test-puid-pgid.sh` this way: **both the body and
  the closing `PY` start at column 0**, inside an otherwise-indented shell function. Indenting the
  body would prepend spaces to every Python line and raise `IndentationError` at run time, which
  `bash -n` cannot catch.
- **`git add` and `git commit` in separate Bash calls**, commit message written with the Write tool
  under
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/`
  and committed with `-F <msgfile>` — the pre-commit hook matches on command text and blocks a call
  that does both.
- **Every long `docker` command runs in the foreground with `</dev/null` and a Bash `timeout` of
  600000 ms.** Backgrounded, `start-test-container.sh`'s own heredoc never returns and the call
  hangs until the harness kills it.
- **Carried, not fixed, in this PR** (spec § Requirements, § Non-goals): the published Postgres port
  `5436:5432` on all interfaces (`docker/docker-compose.yml`, untouched); `ALLOWED_HOSTS=["*"]` /
  `CORS_ALLOW_ALL_ORIGINS` / `CSRF_TRUSTED_ORIGINS` (untouched); the unfenced ownership lease
  (untouched, D10); no authorization hop yet — `stream_ts` is still `AllowAny` gated only by the
  `STREAMS` network ACL until PR 5.
- **Branch name already matches `migration/**`** (`git branch --show-current` =
  `migration/phase1-process-split`), so `lifecycle-tests.yml`'s full-mode gate and the whole
  Playwright matrix already apply to every push on this branch (D16).

## Done criteria (from the spec)

- [ ] PR 2's TTFB spec (`e2e/tests/streaming/time-to-first-byte.spec.ts`) and SPA-three-segment spec
      (`e2e/tests/streaming/spa-three-segment-route.spec.ts`) still pass, now genuinely crossing the
      process boundary — proven by `E2E result` on this branch's CI run (`streaming` project) and,
      locally, by Task 14 Step 4's
      `npx playwright test --project=streaming -g "liveness ceiling|SPA"`.
- [ ] `E2E result` green in full mode, specifically the `streaming` and `streaming-failover`
      projects (G4's existing coverage running unmodified against two processes is the evidence the
      split preserved relay behaviour) — proven by CI on this branch (full mode, `migration/**`).
- [ ] `Lifecycle result` green in full mode, with the new `test_role_split` scenario passing **and
      `test_modular_mode` still passing** (Task 6 gives every modular role-`api` container a relay
      upstream nginx resolves at config load; Task 12 Step 1 is what keeps that scenario bootable) —
      proven by CI's `lifecycle-tests.yml` `suites` job (`puid-pgid` matrix leg) on this branch, and
      locally by `bash docker/tests/test-puid-pgid.sh role_split` (Task 12 Step 4) and
      `bash docker/tests/test-puid-pgid.sh modular_mode` (Task 12 Step 1).
- [ ] `Backend result` green; `apps.channels.tests` covers the DVR base-URL change — proven by
      `manage.py test apps.channels.tests.test_dvr_port_resolution -v2` (Task 9) and the full
      `apps.channels.tests` package via the commit-gate hook.
- [ ] `CLAUDE.md` corrected per Task 13 (§ Architecture opening paragraph at `:59`, the
      worker-count bullet at `:61`, the `uwsgi_buffering off` bullet at `:65`, the "No `harakiri`"
      sentence at `:122`) — proven by Task 13 Step 6's grep returning `0`.
- [ ] The spec carries amendments S1–S5 — proven by Task 13 Step 6's grep.

## Test environment for this worktree

The edit/commit hooks resolve the project directory from the harness, so in a worktree they do not
run tests automatically. Run them yourself:

1. Start a container for this worktree (idempotent). **Foreground, `</dev/null`, 600000 ms Bash
   timeout** — backgrounded, the script's heredoc never returns:
   `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr4 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr4 DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/.claude/hooks/start-test-container.sh </dev/null`
2. After editing any file, run the affected-file hook by hand:
   `echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr4 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr4 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/.claude/hooks/run-affected-tests.sh`
   Exit 2 = blocking failure; read the output.
3. Before every commit, run the commit gate by hand:
   `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr4 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr4 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/.claude/hooks/pre-commit-tests.sh --git-hook`
4. Backend tests directly: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr4 /dispatcharrpy/bin/python manage.py test --keepdb <label> -v1`
5. Frontend: not touched by this PR — skip. E2E typecheck:
   `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/e2e && npm ci && npx tsc --noEmit`.
   A full Playwright project run needs the AIO image built from this worktree (`e2e/README.md`);
   Task 14 does that with pr4-suffixed `DISPATCHARR_E2E_CONTAINER`/`_PORT`/`_VOLUME`/`_NETWORK`/
   `_IMAGE` so the shared `dispatcharr-e2e` stack is untouched. **Never pass `--reset` or `--down`**
   — both call `destroy()`, which removes the shared Docker network and takes the shared
   `e2e-upstream` provider container with it (issue #168).
6. If the container cannot start, say so in the task report: the work is then unverified, not
   verified.
7. **Supervisord config syntax, with no Docker at all**:
   `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4 && uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py`
   — parses every `docker/supervisord/*.conf` rung with supervisor's own `ServerOptions.realize()`
   and checks each rung's program list against the `EXPECTED` dict in that script. Task 4 updates
   `EXPECTED` for the three rungs that gain `relay-uwsgi`.

## File Structure

```
docker/uwsgi.relay.ini                         NEW  relay uWSGI ini: socket=0.0.0.0:5657, workers=1
docker/uwsgi.ini                               MODIFY  + harakiri/harakiri-verbose/max-requests
docker/uwsgi.modular.ini                       MODIFY  + harakiri/harakiri-verbose/max-requests
docker/entrypoint.sh                           MODIFY  + 3 exports; hwaccel-check gate moved
docker/supervisord.d/relay-uwsgi.conf          NEW  [program:relay-uwsgi], mirrors api-uwsgi.conf
docker/supervisord/all.conf                    MODIFY  [include] gains relay-uwsgi.conf
docker/supervisord/all-dev.conf                MODIFY  [include] gains relay-uwsgi.conf
docker/supervisord/relay.conf                  MODIFY  header comment only (its glob already matches)
docker/tests/validate-supervisord-conf.py      MODIFY  EXPECTED gains relay-uwsgi for 3 rungs
docker/nginx.conf                              MODIFY (full rewrite)  relay_py upstream + location table (S5: recordings file)
docker/init/03-init-dispatcharr.sh             MODIFY  + RELAY_UPSTREAM sed, inside the existing role gate
docker/docker-compose.yml                      MODIFY  + relay service; web + RELAY_HOST + depends_on
apps/channels/tasks.py                         MODIFY  get_dvr_stream_base_url() AIO + new dev branch (D6/S3)
apps/channels/tests/test_dvr_port_resolution.py MODIFY  2 assertions -> 9191, dev retargeted, +1 test
e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts  MODIFY  location filter widened
e2e/tests/guards/allowlist.ts                  MODIFY  one stale comment above that spec's entry
e2e/fixtures/instance.ts                       MODIFY  + supervisorctl() helper
e2e/tests/lifecycle/restart-persistence.spec.ts MODIFY  + polled RUNNING assertions, + retried re-tune
docker/tests/test-puid-pgid.sh                 MODIFY  + test_role_split, + upstream-image build, + modular_mode relay host
CLAUDE.md                                      MODIFY  4 corrections (Task 13)
docs/superpowers/specs/2026-09-04-phase1-process-split-design.md  MODIFY  amendments S1-S5 (Task 13)
docs/superpowers/plans/2026-09-04-phase1-pr4-process-split.md     ADD     this plan, committed with the PR
```

---
### Task 1: Merge `origin/main` once PR 3 has landed, and re-verify this plan's anchors

**Files:** none (git operations and verification only).

**Interfaces:** none.

- [ ] **Step 1: Confirm PR 3 is on `main` by content, then merge**

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  git fetch origin main
  git show origin/main:docker/supervisord/relay.conf >/dev/null 2>&1 \
    && echo "PR 3 content IS on main" || echo "PR 3 content is NOT on main"
  git show origin/main:docker/supervisord/supervisorctl.conf >/dev/null 2>&1 \
    && echo "supervisorctl.conf IS on main" || echo "supervisorctl.conf is NOT on main"
  ```
  Expected: both lines say `IS on main`. **A commit-hash test is the wrong test here** — PR 3
  merges squashed, so its commits do not exist on `main` and `git merge-base --is-ancestor` would
  say "not merged" about a PR that plainly is. If either file is absent, **stop**: every task below
  edits files PR 3 introduced. Re-run this step after PR 3 merges.

  Then merge:
  ```bash
  git merge origin/main
  ```
  Expected: a merge commit, usually clean. Because `main`'s squashed PR 3 and this branch's PR 3
  commits carry the same content, git resolves most files as identical changes. Where a conflict
  does appear, it is because PR 3 was amended during its own review: **resolve in favour of
  `origin/main`** for every file this plan has not yet edited (no task has run yet, so that is all
  of them), then confirm with
  `git diff origin/main --stat` — Expected: empty, or only this plan file.

- [ ] **Step 2: Re-verify the anchors this plan cites**

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  grep -n "^supervisorctl_status()" docker/tests/test-puid-pgid.sh
  grep -rn "uwsgi started with PID" docker/ scripts/ apps/ dispatcharr/ || echo "no stale readiness marker"
  ls docker/supervisord/
  grep -n "as one .supervisord. program among several" CLAUDE.md
  grep -n "uwsgi_buffering off" CLAUDE.md
  grep -n "No .harakiri., and it can" CLAUDE.md
  grep -c "def test_" apps/channels/tests/test_dvr_port_resolution.py
  grep -c "127.0.0.1:5656" apps/channels/tests/test_dvr_port_resolution.py
  grep -n "deliberate PR 4 decision" docs/superpowers/specs/2026-09-04-phase1-process-split-design.md
  ```
  Expected, and what each answer means:

  | Check | Expected | If it differs |
  | --- | --- | --- |
  | `supervisorctl_status()` | one hit (≈`:162`) | PR 3's readiness contract is missing — stop and re-check the merge. |
  | `uwsgi started with PID` | `no stale readiness marker` | PR 3's readiness-marker fix regressed; report it, it blocks nothing in PR 4 but breaks both bash suites. |
  | `ls docker/supervisord/` | exactly `all-dev.conf all.conf api.conf relay.conf supervisorctl.conf worker.conf` | An `all-debug.conf` would mean a sixth rung exists; add it to Task 4's `EXPECTED` and to the two `[include]` edits. |
  | CLAUDE.md `supervisord program among several` | one hit (≈`:59`) | Task 13 Step 1's `old_string` must be re-quoted from the tree before editing. |
  | CLAUDE.md `uwsgi_buffering off` | one hit (≈`:65`) | same. |
  | CLAUDE.md `No harakiri, and it can` | one hit (≈`:122`) | same. |
  | `def test_` count | `8` | Task 9's arithmetic (8 → 9 tests) needs redoing. |
  | `127.0.0.1:5656` count | `3` | S4's "three, not four" claim needs re-deriving before Task 13 applies it. |
  | spec `deliberate PR 4 decision` | one hit (≈`:1137`), the hwaccel note PR 3 added | S2's `old_string` must be re-quoted from the tree. |

  This step changes no files. Record every answer in the task report — Task 13 reads it.

---

### Task 2: Create the relay uWSGI ini

**Files:**
- Create: `docker/uwsgi.relay.ini`

**Interfaces:**
- Consumes: `dispatcharr.wsgi:application` (same WSGI app the API ini already loads — D1, same
  Django settings, same urlconf).
- Produces: a uWSGI ini that `docker/supervisord.d/relay-uwsgi.conf` (Task 4) execs with
  `--ini /app/docker/uwsgi.relay.ini`.

- [ ] **Step 1: Write `docker/uwsgi.relay.ini`**

  `docker/uwsgi.ini`'s current content minus the daemon-block comment, minus
  `socket = /app/uwsgi.sock` / `chmod-socket = 777` / `http = 0.0.0.0:5656` / `http-keepalive = 1` /
  `http-timeout = 600`, plus a TCP socket, `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)`,
  `listen = 1024`. Everything else — `chdir`, `module`, `virtualenv`, `master`, both `env =` lines,
  `vacuum`, `die-on-term`, `static-map`, `buffer-size`, `post-buffering`, `socket-timeout = 600`,
  `lazy-apps`, `gevent-early-monkey-patch` + `import = dispatcharr.gevent_patch`, `thunder-lock`,
  `log-4xx`/`log-5xx`/`disable-logging`, and the full log block — carried verbatim so the relay is
  the same application under a different listener. **No `harakiri` anywhere in this file.**

  ```ini
  [uwsgi]
  ; The relay's own uWSGI process (Phase 1 PR 4). Same Django app, same
  ; urlconf as the API process (D1) — only the listener, worker count and
  ; concurrency differ. No harakiri: this process exists to serve the
  ; long-lived responses a request timeout would kill (live TS, VOD,
  ; catch-up, the XC streaming roots). Started as [program:relay-uwsgi]
  ; (docker/supervisord.d/relay-uwsgi.conf), the same shape as
  ; [program:api-uwsgi], through the same wait-for-stores.sh wrapper.

  # Core settings
  chdir = /app
  module = dispatcharr.wsgi:application
  virtualenv = /dispatcharrpy
  master = true
  env = DJANGO_SETTINGS_MODULE=dispatcharr.settings
  env = USE_NGINX_ACCEL=true
  vacuum = true
  die-on-term = true
  static-map = /static=/app/static

  # Listener: TCP, not the API's unix socket, so the modular `relay`
  # container is reachable over the compose network (D5). No `http =`
  # listener exists on this process — nginx reaches it only via uwsgi_pass
  # to the relay_py upstream group (docker/nginx.conf).
  socket = 0.0.0.0:5657
  # listen = 1024 is the kernel accept-queue depth uWSGI asks for. It is
  # silently clamped to net.core.somaxconn, which is 4096 by default on
  # kernels >= 5.4 — so this is a no-op on a modern host and a clamp to
  # 128 on an ancient one. Noted in the PR body rather than guarded here:
  # a clamped queue costs latency under a connection burst, never
  # correctness.
  listen = 1024

  # One worker, deliberately: it is what makes the ownership lease's
  # contention rare in practice, at the cost of one OS thread instead of
  # four for GPU-bound ffmpeg work.
  workers = 1

  buffer-size = 65536  # Increase buffer for large payloads
  post-buffering = 4096  # Reduce buffering for real-time streaming
  socket-timeout = 600  # Prevent write timeouts when client buffers
  lazy-apps = true  # Improve memory efficiency

  # Async mode (use gevent for high concurrency). Default 1600 preserves
  # today's aggregate ceiling of 4 workers x 400 = 1600 concurrent
  # connections, now on one worker (docker/entrypoint.sh exports the
  # default; DISPATCHARR_RELAY_GEVENT overrides it).
  gevent = $(DISPATCHARR_RELAY_GEVENT)
  # Each unused greenlet costs ~2-4KB of memory; at 1600 that is ~3-6MB.

  # Patch the stdlib (socket, threading, time, ...) before any app code
  # loads so blocking calls yield to the gevent hub. Without this, a single
  # blocking requests / DNS call freezes every greenlet on the
  # worker. psycopg3 uses Python's socket layer, so no additional patching is needed.
  gevent-early-monkey-patch = true
  import = dispatcharr.gevent_patch

  # Performance tuning
  thunder-lock = true
  log-4xx = true
  log-5xx = true
  disable-logging = false

  # Logging configuration
  # Enable console logging (stdout)
  log-master = true
  # Enable strftime formatting for timestamps
  logformat-strftime = true
  log-date = %%Y-%%m-%%d %%H:%%M:%%S,000
  # Use formatted time with environment variable for log level
  log-format = %(ftime) $(DISPATCHARR_LOG_LEVEL) uwsgi.requests Worker ID: %(wid) %(method) %(status) %(uri) %(msecs)ms
  log-buffering = 1024  # Add buffer size limit for logging
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  grep -c "harakiri" docker/uwsgi.relay.ini
  grep -n "socket = 0.0.0.0:5657\|workers = 1\|gevent = \$(DISPATCHARR_RELAY_GEVENT)\|listen = 1024" docker/uwsgi.relay.ini
  ```
  Expected: the first command prints `0` (no `harakiri`, ever); the second prints exactly four
  lines, one per directive. uWSGI's `.ini` dialect is not strict INI (`env =` repeats, `#` and `;`
  both comment), so no Python INI parser is a valid syntax check here — **the only real proof this
  file is loadable is uWSGI itself starting against it, which is Task 14 Step 3.**

- [ ] **Step 2: Commit**

  ```bash
  git add docker/uwsgi.relay.ini
  ```
  Write the commit message with the Write tool to
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-1.txt`:
  ```
  feat(docker): add the relay's own uWSGI ini

  socket=0.0.0.0:5657 (uwsgi protocol, TCP so the modular relay container
  is reachable), workers=1, gevent=$(DISPATCHARR_RELAY_GEVENT) default
  1600, listen=1024. No harakiri: the relay exists to serve the long-lived
  responses a request timeout would kill. Carries every other directive
  from docker/uwsgi.ini verbatim so the relay is the same application
  under a different listener (D1, D5).

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Then, in a separate Bash call:
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-1.txt
  ```

---

### Task 3: Give the API a request timeout and worker recycling

**Files:**
- Modify: `docker/uwsgi.ini` (after `workers = 4` at line 20)
- Modify: `docker/uwsgi.modular.ini` (after `workers = 4` at line 21)
- Modify: `docker/entrypoint.sh` (insert after line 219, the `fi` closing the
  `DISPATCHARR_UWSGI_EXTRA_ARGS` conditional; add three names to the `variables=()` array at lines
  259-268)

**Interfaces:**
- Produces: `DISPATCHARR_API_HARAKIRI` (default `120`), `DISPATCHARR_API_MAX_REQUESTS` (default
  `5000`), `DISPATCHARR_RELAY_GEVENT` (default `1600`, consumed by Task 2's
  `docker/uwsgi.relay.ini`) — all three exported by `entrypoint.sh` before `exec supervisord`, read
  by uWSGI's own `$(VAR)` expansion.

- [ ] **Step 1: Add the three exports to `docker/entrypoint.sh`**

  Insert after line 219 (the `fi` closing the `DISPATCHARR_UWSGI_EXTRA_ARGS` conditional), before
  the blank line preceding the `setup_pg_ssl_env()` comment block:

  ```bash

  # uWSGI's own $(VAR) expansion reads these from its process environment
  # (not %(ENV_x)s — that is supervisord's own syntax, irrelevant to what
  # the uwsgi binary itself expands). Exported unconditionally, in every
  # role, for the same reason DISPATCHARR_UWSGI_INI is: an unset $(VAR) in
  # an ini uWSGI does not even load is harmless, but a role that does load
  # it (relay-uwsgi reads DISPATCHARR_RELAY_GEVENT; api-uwsgi reads the
  # other two) must never see an empty expansion.
  export DISPATCHARR_API_HARAKIRI=${DISPATCHARR_API_HARAKIRI:-120}
  export DISPATCHARR_API_MAX_REQUESTS=${DISPATCHARR_API_MAX_REQUESTS:-5000}
  export DISPATCHARR_RELAY_GEVENT=${DISPATCHARR_RELAY_GEVENT:-1600}
  ```

  Then extend the `variables=()` array (lines 259-268) by replacing its last entry line:

  ```bash
      DISPATCHARR_UWSGI_INI DISPATCHARR_UWSGI_EXTRA_ARGS
  ```
  with:
  ```bash
      DISPATCHARR_UWSGI_INI DISPATCHARR_UWSGI_EXTRA_ARGS
      DISPATCHARR_API_HARAKIRI DISPATCHARR_API_MAX_REQUESTS DISPATCHARR_RELAY_GEVENT
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash -n docker/entrypoint.sh && echo "syntax OK"
  grep -n "DISPATCHARR_RELAY_GEVENT" docker/entrypoint.sh
  ```
  Expected: `syntax OK`, then exactly two hits for `DISPATCHARR_RELAY_GEVENT` (the `export` and the
  `variables=()` entry).

- [ ] **Step 2: Add the three directives to `docker/uwsgi.ini`**

  After line 20 (`workers = 4`), insert:

  ```ini

  # Request timeout and worker recycling (PR 4). The relay's own ini
  # (docker/uwsgi.relay.ini) carries neither: this process no longer serves
  # long-lived streams (docker/nginx.conf routes those to the relay), so a
  # bounded request time and periodic worker respawn are safe here for the
  # first time in this codebase's history.
  harakiri = $(DISPATCHARR_API_HARAKIRI)
  harakiri-verbose = true
  max-requests = $(DISPATCHARR_API_MAX_REQUESTS)
  ```

- [ ] **Step 3: Add the same three directives to `docker/uwsgi.modular.ini`**

  Same insertion, after its own `workers = 4` (line 21), with the same comment.

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  grep -c "harakiri" docker/uwsgi.ini docker/uwsgi.modular.ini
  grep -c "harakiri" docker/uwsgi.relay.ini
  ```
  Expected: `docker/uwsgi.ini:2` and `docker/uwsgi.modular.ini:2` (the `harakiri` directive plus the
  `harakiri-verbose` line in each), and `0` for the relay ini.

- [ ] **Step 4: Commit**

  ```bash
  git add docker/uwsgi.ini docker/uwsgi.modular.ini docker/entrypoint.sh
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-2.txt`:
  ```
  feat(docker): enable harakiri and max-requests on the API uWSGI

  DISPATCHARR_API_HARAKIRI (default 120s) and DISPATCHARR_API_MAX_REQUESTS
  (default 5000), plus harakiri-verbose so a kill names the offending
  request. Safe now that the relay's own ini serves every long-lived
  stream surface (docker/uwsgi.relay.ini, this branch). Also exports
  DISPATCHARR_RELAY_GEVENT, consumed by that ini.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-2.txt
  ```

---

### Task 4: Add the `relay-uwsgi` supervisord program

**Files:**
- Create: `docker/supervisord.d/relay-uwsgi.conf`
- Modify: `docker/supervisord/all.conf` (the `[include] files =` line, line 19)
- Modify: `docker/supervisord/all-dev.conf` (the `[include] files =` line, line 19)
- Modify: `docker/supervisord/relay.conf` (its header comment above `[include]`, lines 18-21)
- Modify: `docker/tests/validate-supervisord-conf.py` (the `EXPECTED` dict, lines 31-44)

**Interfaces:**
- Consumes: `docker/supervisord.d/wait-for-stores.sh` (unchanged), `docker/uwsgi.relay.ini` (Task 2).
- Produces: `[program:relay-uwsgi]`, priority `205` (between `api-uwsgi` at `200` and `daphne` at
  `210`), picked up automatically by `docker/supervisord/relay.conf`'s existing `relay-*.conf` glob
  with no edit to that file's `[include]`.

- [ ] **Step 1: Update the validator's expectations first (red)**

  In `docker/tests/validate-supervisord-conf.py`, replace lines 31-44:

  ```python
  EXPECTED = {
      "all.conf": [
          "postgres", "redis", "api-uwsgi", "daphne",
          "celery-default", "celery-dvr", "celery-beat", "nginx",
      ],
      "all-dev.conf": [
          "postgres", "redis-dev", "api-uwsgi", "daphne",
          "celery-default", "celery-dvr", "celery-beat", "vite",
      ],
      "api.conf": ["api-uwsgi", "daphne", "nginx"],
      "worker.conf": ["celery-default", "celery-dvr", "celery-beat"],
      # PR 4 adds relay-uwsgi.conf; the glob matches nothing until then.
      "relay.conf": [],
  }
  ```

  with:

  ```python
  EXPECTED = {
      "all.conf": [
          "postgres", "redis", "api-uwsgi", "relay-uwsgi", "daphne",
          "celery-default", "celery-dvr", "celery-beat", "nginx",
      ],
      "all-dev.conf": [
          "postgres", "redis-dev", "api-uwsgi", "relay-uwsgi", "daphne",
          "celery-default", "celery-dvr", "celery-beat", "vite",
      ],
      "api.conf": ["api-uwsgi", "daphne", "nginx"],
      "worker.conf": ["celery-default", "celery-dvr", "celery-beat"],
      # relay.conf's [include] is a glob (relay-*.conf); PR 4 is what
      # first populates it, with relay-uwsgi (D14 — the relay role runs
      # no nginx, so this program is and stays the only one this rung
      # includes).
      "relay.conf": ["relay-uwsgi"],
  }
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py
  ```
  Expected: FAIL — the last line reads `5 rung(s) checked, 3 failure(s)`, with `all.conf`,
  `all-dev.conf` and `relay.conf` each printing `FAIL ...: programs [...], expected [...]`, because
  `relay-uwsgi.conf` does not exist yet. (`supervisorctl.conf` is skipped by the script's own
  `or rung == "supervisorctl.conf": continue`, so the count is 5, not 6.)

- [ ] **Step 2: Write `docker/supervisord.d/relay-uwsgi.conf`**

  Mirrors `docker/supervisord.d/api-uwsgi.conf` exactly (same `setpriv`-after-`nice` shape —
  a negative `UWSGI_NICE_LEVEL` needs root to set, then drops privilege, rather than supervisord's
  own `user=`), pointed at the relay's own ini by an absolute path rather than
  `%(ENV_DISPATCHARR_UWSGI_INI)s` (that variable names the *API's* ini and is role-independent), with
  the longest `stopwaitsecs` in the tree:

  ```ini
  [program:relay-uwsgi]
  command=nice -n %(ENV_UWSGI_NICE_LEVEL)s setpriv --reuid=%(ENV_POSTGRES_USER)s --regid=%(ENV_POSTGRES_USER)s --init-groups /app/docker/supervisord.d/wait-for-stores.sh %(ENV_VIRTUAL_ENV)s/bin/uwsgi --ini /app/docker/uwsgi.relay.ini %(ENV_DISPATCHARR_UWSGI_EXTRA_ARGS)s
  directory=/app
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  priority=205
  autostart=true
  autorestart=true
  startretries=20
  startsecs=5
  stopsignal=TERM
  stopwaitsecs=20
  killasgroup=true
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```

  `stopwaitsecs=20`, not `api-uwsgi`'s `10`: an in-flight stream, unlike an API request under
  `harakiri`, has no timeout of its own, and PR 8's bounded-restart ceiling (N ≤ 30s) is derived
  from this number plus process-start time.

- [ ] **Step 3: Wire it into `all.conf` and `all-dev.conf`, and correct `relay.conf`'s comment**

  In `docker/supervisord/all.conf`, replace line 19:

  ```
  files = /app/docker/supervisord.d/postgres.conf /app/docker/supervisord.d/redis.conf /app/docker/supervisord.d/api-uwsgi.conf /app/docker/supervisord.d/daphne.conf /app/docker/supervisord.d/celery-default.conf /app/docker/supervisord.d/celery-dvr.conf /app/docker/supervisord.d/celery-beat.conf /app/docker/supervisord.d/nginx.conf
  ```

  with (inserting `relay-uwsgi.conf` after `api-uwsgi.conf`):

  ```
  files = /app/docker/supervisord.d/postgres.conf /app/docker/supervisord.d/redis.conf /app/docker/supervisord.d/api-uwsgi.conf /app/docker/supervisord.d/relay-uwsgi.conf /app/docker/supervisord.d/daphne.conf /app/docker/supervisord.d/celery-default.conf /app/docker/supervisord.d/celery-dvr.conf /app/docker/supervisord.d/celery-beat.conf /app/docker/supervisord.d/nginx.conf
  ```

  In `docker/supervisord/all-dev.conf`, replace line 19:

  ```
  files = /app/docker/supervisord.d/postgres.conf /app/docker/supervisord.d/redis-dev.conf /app/docker/supervisord.d/api-uwsgi.conf /app/docker/supervisord.d/daphne.conf /app/docker/supervisord.d/celery-default.conf /app/docker/supervisord.d/celery-dvr.conf /app/docker/supervisord.d/celery-beat.conf /app/docker/supervisord.d/vite.conf
  ```

  with:

  ```
  files = /app/docker/supervisord.d/postgres.conf /app/docker/supervisord.d/redis-dev.conf /app/docker/supervisord.d/api-uwsgi.conf /app/docker/supervisord.d/relay-uwsgi.conf /app/docker/supervisord.d/daphne.conf /app/docker/supervisord.d/celery-default.conf /app/docker/supervisord.d/celery-dvr.conf /app/docker/supervisord.d/celery-beat.conf /app/docker/supervisord.d/vite.conf
  ```

  In `docker/supervisord/relay.conf`, replace the comment above `[include]`:

  ```
  # No relay program exists until PR 4 adds
  # docker/supervisord.d/relay-uwsgi.conf, which this glob then picks up with
  # no edit here (D14: the relay role runs no nginx, so relay-uwsgi is and
  # stays the only program this rung includes).
  ```
  with:
  ```
  # relay-uwsgi.conf (Phase 1 PR 4) is the only program this glob picks up
  # (D14: the relay role runs no nginx), and needed no edit here to start
  # being included.
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py
  ```
  Expected: PASS — the last line reads exactly `5 rung(s) checked, 0 failure(s)`. Every rung prints
  `OK`; `all.conf` and `all-dev.conf` list `relay-uwsgi` between `api-uwsgi` and `daphne`
  (the script sorts by `priority`, and 205 sits between 200 and 210), and `relay.conf` lists
  `relay-uwsgi` alone.

- [ ] **Step 4: Commit**

  ```bash
  git add docker/supervisord.d/relay-uwsgi.conf docker/supervisord/all.conf docker/supervisord/all-dev.conf docker/supervisord/relay.conf docker/tests/validate-supervisord-conf.py
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-3.txt`:
  ```
  feat(docker): add the relay-uwsgi supervisord program

  Same shape as api-uwsgi (setpriv-after-nice, the wait-for-stores.sh
  wrapper), pointed at docker/uwsgi.relay.ini, stopwaitsecs=20 (the
  longest in the tree — PR 8's bounded-restart ceiling is derived from
  it). Wired into all.conf and all-dev.conf's [include]; relay.conf's own
  relay-*.conf glob picks it up with no edit. Updates
  validate-supervisord-conf.py's EXPECTED for all three rungs.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-3.txt
  ```

---
### Task 5: Give the relay its own nginx location table

**Files:**
- Modify: `docker/nginx.conf` (full file, lines 1-120)

**Interfaces:**
- Produces: `upstream relay_py { server RELAY_UPSTREAM; }`, a location table routing every
  long-lived stream surface to it. No `auth_request`, no `map`, no `X-Relay-*` headers (PR 5) — PR 4
  writes `uwsgi_pass relay_py;` directly, per the spec's own note: "there is no `X-Relay-Name`
  header to key a `map` on until PR 5."
- Consumes: `apps/proxy/live_proxy/urls.py`, `apps/proxy/vod_proxy/urls.py`,
  `apps/timeshift/urls.py`, `apps/hdhr/urls.py`, `apps/output/urls.py`, `dispatcharr/urls.py`,
  `apps/channels/api_urls.py` — every route this table's `^~`, `=` and nested regex locations name.

- [ ] **Step 1: Rewrite `docker/nginx.conf`**

  Verified against the tree's actual `urls.py` files, not just the spec's table: the six exact API
  routes are `/proxy/ts/status` (no trailing slash — `live_proxy/urls.py`, `path('status', ...)`),
  `/proxy/vod/stats/` and `/proxy/vod/stop_client/` (`vod_proxy/urls.py`), and
  `/proxy/catchup/stats/`, `/proxy/catchup/programs/`, `/proxy/catchup/stop_client/`
  (`apps/timeshift/urls.py`). The one exact relay route is `/streaming/timeshift.php`
  (`dispatcharr/urls.py`, `timeshift_proxy_query`, long-lived). `/output/m3u/<profile>` and
  `/output/epg/<profile>` (`apps/output/urls.py`) and every `/hdhr/<profile>/...` form
  (`apps/hdhr/urls.py`) are three-segment URIs with no guaranteed trailing slash, so both need `^~`
  to stay out of the XC three-segment regex's reach (D7) — `/output/` is new to this table; `/hdhr`
  already existed as a plain prefix and gains `^~` here.

  **One long-lived route lives under `/api/`, and must move with the rest** (amendment S5).
  `RecordingViewSet.file` — `GET /api/channels/recordings/<pk>/file/`, registered by
  `apps/channels/api_urls.py`'s `DefaultRouter` (`trailing_slash=True`) as a DRF
  `@action(url_path="file")` — returns a `StreamingHttpResponse` over the recorded MKV/MP4 with
  Range support (`apps/channels/api_views.py`, the `file` action), and the DVR UI uses it for
  playback. It is hours long. Left on the API it would meet the `harakiri = 120` this PR enables and
  be killed partway through every playback, taking that gevent worker's other ~400 in-flight
  requests with it. A **nested regex location inside `^~ /api/`** sends it to the relay: same
  urlconf, same view, same DRF authentication (D1), only a different process. Nothing under
  `apps/channels/` changes — this is a routing decision, not a code one (D10). Its sibling
  `recordings/<pk>/hls/<seg_path>` stays on the API: HLS segments are small files, not a single
  long response.

  ```nginx
  # Channel/VOD logos and SD program posters share /data/cache/ with separate zones.
  proxy_cache_path /data/cache/logos levels=1:2 keys_zone=logo_cache:10m
                   inactive=24h use_temp_path=off;

  proxy_cache_path /data/cache/sd_posters levels=1:2 keys_zone=sd_poster_cache:10m
                   inactive=14d use_temp_path=off;

  # The relay's uWSGI process (Phase 1 PR 4). A literal upstream group name,
  # not a bare address in a variable: uwsgi_pass to a variable needs a
  # resolver, uwsgi_pass to a declared upstream group does not. RELAY_UPSTREAM
  # is a bare placeholder with no $, sed'd at boot exactly like NGINX_PORT
  # (docker/init/03-init-dispatcharr.sh) -- 127.0.0.1:5657 outside modular,
  # <relay host>:<relay port> in modular.
  #
  # nginx resolves this name ONCE, at config load. In modular mode a `web`
  # container started with no `relay` container in DNS fails config load
  # outright ("host not found in upstream"), which is why
  # docker/docker-compose.yml gives `web` a depends_on on `relay`, and why
  # recreating the relay with a new IP needs `nginx -s reload` in the web
  # container.
  upstream relay_py {
      server RELAY_UPSTREAM;
  }

  server {
      listen NGINX_PORT;
      listen [::]:NGINX_PORT;

      proxy_connect_timeout 75;
      proxy_send_timeout 300;
      proxy_read_timeout 300;
      client_max_body_size 0;

      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Host $host:$server_port;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Port $server_port;

      # --- Exact matches: short JSON control routes that stay on the API,
      # plus the one exact relay route below. An exact match wins outright
      # over every prefix and regex location, so order among these seven
      # doesn't matter, and none needs ^~. ---
      location = /proxy/ts/status {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      location = /proxy/vod/stats/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      location = /proxy/vod/stop_client/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      location = /proxy/catchup/stats/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      location = /proxy/catchup/programs/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      location = /proxy/catchup/stop_client/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      # /streaming/timeshift.php (dispatcharr/urls.py timeshift_proxy_query)
      # is long-lived, like the catchup/<uuid> route below.
      location = /streaming/timeshift.php {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }

      # --- ^~ prefixes: the longest matching one wins outright, no regex is
      # consulted for it. Order among ^~ locations does not matter to nginx
      # (longest prefix wins regardless of file order); grouped here by
      # destination for readability only. ---
      location ^~ /api/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;

          location ~ ^/api/channels/logos/(?<logo_id>\d+)/cache/ {
              proxy_pass http://127.0.0.1:5656;
              proxy_cache logo_cache;
              proxy_cache_key "$scheme$request_uri";  # Cache per logo URL
              proxy_cache_valid 200 24h;  # Cache successful logos for 24 hours
              proxy_cache_valid 404 1m;   # Short negative cache; avoids stampeding Django/upstream
              proxy_cache_use_stale error timeout updating;  # Serve stale if Django is slow
          }

          location ~ ^/api/vod/vodlogos/(?<logo_id>\d+)/cache/ {
              proxy_pass http://127.0.0.1:5656;
              proxy_cache logo_cache;
              proxy_cache_key "$scheme$request_uri";  # Cache per logo URL
              proxy_cache_valid 200 24h;  # Cache successful logos for 24 hours
              proxy_cache_valid 404 1m;   # Short negative cache; avoids stampeding Django/upstream
              proxy_cache_use_stale error timeout updating;  # Serve stale if Django is slow
          }

          # Parent-scoped VOD images (backdrops, episode stills, etc.)
          location ~ ^/api/vod/(movies|series|episodes)/(?<vod_id>\d+)/image/ {
              proxy_pass http://127.0.0.1:5656;
              proxy_cache logo_cache;
              proxy_cache_key "$scheme$request_uri";
              proxy_cache_valid 200 24h;
              proxy_cache_valid 404 1m;
              proxy_cache_use_stale error timeout updating;
          }

          # SD program posters: 14d nginx cache. Clients pass ?v=<hash of sd_icon>
          # Do not add proxy_cache_valid 404 here. Bare HTTP 404s from SD/CDN are treated
          # as transient in the poster proxy (only code 5000 blacklists); a negative cache
          # would delay legitimate retries. Permanent misses are handled in Django/DB.
          location ~ ^/api/epg/programs/(?<prog_id>\d+)/poster/ {
              proxy_pass http://127.0.0.1:5656;
              proxy_cache sd_poster_cache;
              proxy_cache_key "$scheme$request_uri";
              proxy_cache_valid 200 14d;
              proxy_cache_use_stale error timeout updating;
          }

          # The one long-lived response under /api/: RecordingViewSet.file
          # (apps/channels/api_views.py) is a StreamingHttpResponse of the
          # recorded MKV/MP4 with Range support, played back by the DVR UI --
          # hours long, not seconds. Left on the API it would be killed by the
          # new harakiri = 120 partway through every playback, taking the
          # worker's other ~400 in-flight requests with it. Routed here
          # instead: same urlconf, same view, same DRF authentication (D1),
          # only a different process. The trailing slash is DefaultRouter's
          # (trailing_slash=True); a slashless request 301s from the ^~ /api/
          # block above and comes back here.
          location ~ ^/api/channels/recordings/\d+/file/$ {
              include uwsgi_params;
              uwsgi_buffering off;
              uwsgi_read_timeout 300s;
              uwsgi_send_timeout 300s;
              client_max_body_size 0;
              uwsgi_pass relay_py;
          }
      }
      location ^~ /assets/ {
          root /app/static;
      }
      location ^~ /static/ {
          root /app;
      }
      location ^~ /logos/ {
          root /data;
      }
      # Internal location for X-Accel-Redirect backup downloads
      # Django handles auth, nginx serves the file directly
      location ^~ /protected-backups/ {
          internal;
          alias /data/backups/;
      }
      # New in this PR: /output/m3u/<profile_name> and /output/epg/<profile_name>
      # (apps/output/urls.py) are 3-segment, no-trailing-slash URIs the API
      # owns -- ^~ takes them out of the XC three-segment regex's reach (D7).
      location ^~ /output/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      # /hdhr/<channel_profile>/discover.json and its siblings are also
      # 3-segment, no-trailing-slash -- same reasoning as /output/ above.
      location ^~ /hdhr {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      location ^~ /ws/ {
          proxy_pass http://127.0.0.1:8001;
          proxy_http_version 1.1;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection "Upgrade";
      }
      # Everything else under /proxy/ that the more specific ^~ locations
      # below don't claim: /proxy/ts/{change_stream,status/<id>,stop,
      # stop_client,next_stream}, all short and IsAdmin.
      location ^~ /proxy/ {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
      location ^~ /proxy/ts/stream/ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }
      location ^~ /proxy/vod/ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }
      location ^~ /proxy/catchup/ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }
      # No route exists behind this yet (PR 7 adds the relay control API);
      # added now because PR 4 writes the full location table in one shot,
      # and D1 means a request here today just 404s from Django, harmlessly.
      # It is reachable without authentication -- noted in the PR body, and
      # the reason PR 7 must not mount anything here without its own auth.
      location ^~ /proxy/relay/ {
          include uwsgi_params;
          uwsgi_pass relay_py;
      }
      location ^~ /live/ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }
      location ^~ /movie/ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }
      location ^~ /series/ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }
      location ^~ /timeshift/ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }

      # --- Regexes, first match in file order wins. Admin must precede the
      # XC three-segment form (D7): /admin/<password>/<channel_id> (XC
      # username "admin") is deliberately excluded by the admin regex's own
      # negative lookahead and must fall through to the XC regex below it. ---

      # Admin UI disabled outside dedicated admin access. Match /admin and all
      # deeper Django admin paths (e.g. /admin/login/), but do not match the
      # three-segment XC stream form /admin/<password>/<channel_id> used when
      # the XC username is literally "admin".
      location ~ ^/admin(?!/[^/]+/[^/]+/?$)(?:/|$) {
          return 301 /login;
      }
      # The XC three-segment root form: the bare <user>/<pass>/<id> mount at
      # the site root (dispatcharr/urls.py), long-lived. XC_STREAM_ID_PATTERN,
      # narrowed by PR 2, is what keeps a same-shaped SPA deep link out of
      # this route at the Django layer; this regex only decides which
      # *process* answers a URI shaped like one.
      location ~ ^/[^/]+/[^/]+/[^/]+$ {
          include uwsgi_params;
          uwsgi_buffering off;
          uwsgi_read_timeout 300s;
          uwsgi_send_timeout 300s;
          client_max_body_size 0;
          uwsgi_pass relay_py;
      }

      # --- Plain prefix fallback: SPA + everything else. NEVER ^~ -- that
      # would disable every regex above, including the two just written. ---
      location / {
          include uwsgi_params;
          uwsgi_pass unix:/app/uwsgi.sock;
      }
  }
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  grep -cE '^[[:space:]]*location ' docker/nginx.conf
  grep -c 'uwsgi_pass relay_py;' docker/nginx.conf
  grep -c 'uwsgi_buffering off;' docker/nginx.conf
  ```
  Expected, all three counted against the block above rather than estimated: `32` locations
  (7 exact + 17 top-level `^~` + 5 nested `^~ /api/` regexes + 2 top-level regexes + 1 plain `/`);
  `11` `uwsgi_pass relay_py;` (the **ten** streaming locations — seven top-level `^~`,
  `= /streaming/timeshift.php`, the XC three-segment regex, and the nested recordings-file regex —
  plus `/proxy/relay/`); `10` `uwsgi_buffering off;` (every one of those ten streaming locations;
  `/proxy/relay/` is the only relay-bound location without it, because it serves short JSON).

- [ ] **Step 2: Verify with `nginx -t` inside a disposable container**

  The checked-in file has two literal placeholders (`NGINX_PORT`, `RELAY_UPSTREAM`) that are not
  valid nginx syntax until `sed`'d, so `nginx -t` against the raw file fails even before this PR.
  Substitute both with dummy values and test the result. The container is a throwaway syntax
  checker, not a build input, so it needs no digest pin.

  Run (foreground, `</dev/null`, 600000 ms timeout):
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  sed -e 's/NGINX_PORT/9191/g' -e 's/RELAY_UPSTREAM/127.0.0.1:5657/g' docker/nginx.conf \
    > /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-nginx-test.conf
  docker run --rm \
    -v /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-nginx-test.conf:/etc/nginx/conf.d/default.conf:ro \
    nginx:1.24.0 nginx -t </dev/null
  ```
  Expected: `nginx: configuration file /etc/nginx/nginx.conf test is successful`. The stock image
  `include`s `conf.d/*.conf` from inside its `http {}` block, which is exactly the context
  `proxy_cache_path`, `upstream` and `server` need, and it ships `/etc/nginx/uwsgi_params` so the
  `include uwsgi_params;` lines resolve. This proves syntax and the nested-location structure; it
  does not prove routing behaviour — Task 14 Step 3 does that against the real image.

- [ ] **Step 3: Commit**

  ```bash
  git add docker/nginx.conf
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-4.txt`:
  ```
  feat(nginx): route every long-lived stream surface to the relay

  New relay_py upstream (RELAY_UPSTREAM, sed'd at boot like NGINX_PORT).
  Every specific prefix location gains ^~ (D7) so the XC three-segment
  regex can't hijack /assets/, /output/, /hdhr or any other prefix; the
four proxy_cache regexes move inside ^~ /api/, nested. Relay-bound
  locations (/proxy/ts/stream/, /proxy/vod/, /proxy/catchup/, /live/,
  /movie/, /series/, /timeshift/, /streaming/timeshift.php, the XC
  three-segment regex) carry uwsgi_buffering off plus the same read/send
  timeouts the old single /proxy/ block used.

  A fifth nested regex inside ^~ /api/ sends GET
  /api/channels/recordings/<pk>/file/ to the relay as well (spec amendment
  S5): RecordingViewSet.file streams a recorded MKV/MP4 with Range support
  and is hours long, so on the API it would meet this PR's new harakiri=120
  partway through every playback. Same urlconf, same view, same DRF
  authentication -- only a different process (D1).

  No auth_request, no trust headers, no map yet -- those are PR 5.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-4.txt
  ```

---

### Task 6: Template `RELAY_UPSTREAM` at boot

**Files:**
- Modify: `docker/init/03-init-dispatcharr.sh` (lines 67-81, the existing
  `DISPATCHARR_ROLE == "all" || "api"` gate PR 3 added)

**Interfaces:**
- Consumes: `DISPATCHARR_ENV`, `DISPATCHARR_RELAY_HOST` (new, default `relay`),
  `DISPATCHARR_RELAY_PORT` (new, default `5657`).
- Produces: `docker/nginx.conf`'s `RELAY_UPSTREAM` placeholder resolved in
  `/etc/nginx/sites-enabled/default`.

- [ ] **Step 1: Add the sed, beside the existing `NGINX_PORT` one**

  Replace lines 67-81:

  ```bash
  if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
      if ! [[ "$DISPATCHARR_PORT" =~ ^[0-9]+$ ]]; then
          echo "⚠️  Warning: DISPATCHARR_PORT is not a valid integer, using default port 9191"
          DISPATCHARR_PORT=9191
      fi
      sed -i "s/NGINX_PORT/${DISPATCHARR_PORT}/g" /etc/nginx/sites-enabled/default

      # Configure nginx based on IPv6 availability
      if ip -6 addr show | grep -q "inet6"; then
          echo "✅ IPv6 is available, enabling IPv6 in nginx"
      else
          echo "⚠️  IPv6 not available, disabling IPv6 in nginx"
          sed -i '/listen \[::\]:/d' /etc/nginx/sites-enabled/default
      fi
  fi
  ```

  with:

  ```bash
  if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
      if ! [[ "$DISPATCHARR_PORT" =~ ^[0-9]+$ ]]; then
          echo "⚠️  Warning: DISPATCHARR_PORT is not a valid integer, using default port 9191"
          DISPATCHARR_PORT=9191
      fi
      sed -i "s/NGINX_PORT/${DISPATCHARR_PORT}/g" /etc/nginx/sites-enabled/default

      # Relay upstream address (Phase 1 PR 4), sed'd exactly like
      # DISPATCHARR_PORT above. Outside modular the relay shares this
      # container (all/dev/debug), so the address is always loopback; in
      # modular it is the relay compose service's name, the same override
      # shape get_dvr_stream_base_url() uses for DISPATCHARR_WEB_HOST.
      if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
          RELAY_HOST="${DISPATCHARR_RELAY_HOST:-relay}"
      else
          RELAY_HOST="127.0.0.1"
      fi
      RELAY_PORT="${DISPATCHARR_RELAY_PORT:-5657}"
      if ! [[ "$RELAY_PORT" =~ ^[0-9]+$ ]]; then
          echo "⚠️  Warning: DISPATCHARR_RELAY_PORT is not a valid integer, using default port 5657"
          RELAY_PORT=5657
      fi
      sed -i "s/RELAY_UPSTREAM/${RELAY_HOST}:${RELAY_PORT}/g" /etc/nginx/sites-enabled/default

      # Configure nginx based on IPv6 availability
      if ip -6 addr show | grep -q "inet6"; then
          echo "✅ IPv6 is available, enabling IPv6 in nginx"
      else
          echo "⚠️  IPv6 not available, disabling IPv6 in nginx"
          sed -i '/listen \[::\]:/d' /etc/nginx/sites-enabled/default
      fi
  fi
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash -n docker/init/03-init-dispatcharr.sh && echo "syntax OK"
  grep -c "RELAY_UPSTREAM" docker/init/03-init-dispatcharr.sh
  ```
  Expected: `syntax OK`, then `1` (the one `sed -i` line; `RELAY_HOST`/`RELAY_PORT` are separate
  names).

- [ ] **Step 2: Commit**

  ```bash
  git add docker/init/03-init-dispatcharr.sh
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-5.txt`:
  ```
  feat(docker): template RELAY_UPSTREAM into nginx at boot

  Same tool and shape as the existing NGINX_PORT sed, inside the same
  all/api role gate PR 3 added. Loopback outside modular;
  DISPATCHARR_RELAY_HOST (default "relay") in modular, with the same
  numeric guard DISPATCHARR_PORT already has.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-5.txt
  ```

---

### Task 7: Add the modular `relay` compose service

**Files:**
- Modify: `docker/docker-compose.yml` (`web`'s `depends_on` block at lines 29-33; one new
  environment line on `web` after line 75; a new `relay` service between `web`, which ends at line
  118, and the `# Celery Service` banner at line 120)

**Interfaces:**
- Produces: a `relay` service, same image as `web`/`celery`, `DISPATCHARR_ROLE=relay`,
  `DISPATCHARR_ENV=modular`, `stop_grace_period: 160s`, sharing `web`/`celery`'s `./data:/data`
  volume (D11).
- Consumes: `DISPATCHARR_RELAY_HOST` on `web`, read by Task 6's `sed`.

- [ ] **Step 1: Make `web` depend on `relay`, and tell it the relay's hostname**

  `web` already carries `DISPATCHARR_ROLE=api` (PR 3, line 45) — **do not add it again.**

  Replace `web`'s `depends_on` block (lines 29-33):

  ```yaml
      depends_on:
        db:
          condition: service_healthy
        redis:
          condition: service_healthy
  ```
  with:
  ```yaml
      depends_on:
        db:
          condition: service_healthy
        redis:
          condition: service_healthy
        # service_started, not service_healthy: the relay has no healthcheck,
        # and what nginx needs is only that the name resolves. nginx resolves
        # `upstream relay_py { server relay:5657; }` ONCE, at config load, so a
        # web container that starts with no relay container in DNS fails with
        # "host not found in upstream" and [program:nginx] goes BACKOFF then
        # FATAL -- taking the whole API surface down, not just streaming.
        relay:
          condition: service_started
  ```

  Then, in the `# Logging` block right after `- DISPATCHARR_LOG_LEVEL=info` (line 75), add:

  ```yaml

        # Internal Service Communication: nginx's RELAY_UPSTREAM sed
        # (docker/init/03-init-dispatcharr.sh) uses this to reach the relay
        # service below. It defaults to "relay" (the service name), so this
        # line only needs changing if the service is renamed.
        #
        # It must always name something DNS can resolve, though. nginx
        # resolves the relay_py upstream once, at config load, so a web
        # container brought up without a relay -- `docker compose up web`, or
        # a cut-down compose file -- fails config load outright unless this
        # points somewhere resolvable. 127.0.0.1 is the answer in that case:
        # it resolves, and streaming simply 502s, leaving the API up.
        - DISPATCHARR_RELAY_HOST=relay
  ```

- [ ] **Step 2: Add the `relay` service**

  Insert between `web` (ending at line 118) and the `# Celery Service` banner (line 120):

  ```yaml

    # ============================================================================
    # Relay Service — the streaming relay's own uWSGI process (Phase 1 PR 4)
    # ============================================================================
    relay:
      image: ghcr.io/dispatcharr/dispatcharr:latest
      container_name: dispatcharr_relay
      restart: unless-stopped
      # Same rationale as web/celery above: 160s is used uniformly across
      # every supervisord-backed service here, sized to the largest rung's
      # summed stopwaitsecs rather than tuned per-service. This rung sums to
      # 20s (relay-uwsgi alone).
      stop_grace_period: 160s
      depends_on:
        db:
          condition: service_healthy
        redis:
          condition: service_healthy
      volumes:
        # Same volume as web and celery: SECRET_KEY comes from /data/jwt
        # (docker/entrypoint.sh), and a relay that generates its own key
        # 403s every internal call once PR 5/6 add internal HMAC auth (D11).
        - ./data:/data
      extra_hosts:
        - "host.docker.internal:host-gateway"

      environment:
        - DISPATCHARR_ENV=modular
        - DISPATCHARR_ROLE=relay

        - POSTGRES_HOST=db
        - POSTGRES_PORT=5432
        - POSTGRES_DB=dispatcharr
        - POSTGRES_USER=dispatch
        - POSTGRES_PASSWORD=secret

        - REDIS_HOST=redis
        - REDIS_PORT=6379

        - DISPATCHARR_LOG_LEVEL=info

        - DJANGO_SETTINGS_MODULE=dispatcharr.settings
        - PYTHONUNBUFFERED=1

        # Process Priority Configuration (Optional)
        #- UWSGI_NICE_LEVEL=-5   # uWSGI/FFmpeg/Streaming (default: 0, recommended: -5 for high priority)

      # --- Advanced Configuration ---
      # Uncomment to enable high priority for streaming (required if UWSGI_NICE_LEVEL < 0)
      #cap_add:
      #  - SYS_NICE

      # --- Hardware Acceleration (Optional) ---
      # Uncomment for GPU access (transcoding acceleration) -- the relay is
      # where ffmpeg actually runs after this PR.
      #group_add:
      #  - video
      #  #- render  # Uncomment if your GPU requires it
      #devices:
      #  - /dev/dri:/dev/dri  # For Intel/AMD GPU acceleration (VA-API)
  ```

  No published ports (matching `celery`'s shape and D14). No `depends_on: web`: nothing the relay
  does in this PR calls back into Django — that starts at PR 6 — and a cycle with `web`'s new
  `depends_on: relay` would make the file unstartable.

  Run (foreground, `</dev/null`, 600000 ms timeout):
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  docker compose -f docker/docker-compose.yml config --quiet </dev/null && echo "compose OK"
  docker compose -f docker/docker-compose.yml config </dev/null | grep -n "dispatcharr_relay\|DISPATCHARR_RELAY_HOST"
  ```
  Expected: `compose OK` (exit 0, no YAML or interpolation error, and no dependency-cycle error —
  compose rejects a cycle at `config` time), then lines showing `container_name:
  dispatcharr_relay` and `DISPATCHARR_RELAY_HOST=relay` on `web`. This starts no container.

- [ ] **Step 3: Commit**

  ```bash
  git add docker/docker-compose.yml
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-6.txt`:
  ```
  feat(docker): add the modular relay service

  Same image as web/celery, DISPATCHARR_ROLE=relay, DISPATCHARR_ENV=modular,
  stop_grace_period 160s, sharing web/celery's /data volume (D11 --
  SECRET_KEY lives at /data/jwt). No published ports. web gains
  DISPATCHARR_RELAY_HOST=relay and a depends_on the relay: nginx resolves
  the relay_py upstream once at config load, so a web container with no
  relay in DNS fails config load outright rather than 502ing per request.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-6.txt
  ```

---

### Task 8: Move the hardware-acceleration check off the API-only gate

**Files:**
- Modify: `docker/entrypoint.sh` (lines 399-446)

**Interfaces:**
- Consumes: `docker/init/04-check-hwaccel.sh` (unchanged — pure diagnostics; every line is an
  `echo`, and nothing it sets is read downstream).

- [ ] **Step 1: Split the hwaccel check out of the `all|api` migrate block**

  In `docker/entrypoint.sh`, delete these four lines from inside the `all`/`api` branch (they sit
  immediately after the `collectstatic` line):

  ```bash

      # Run hardware acceleration check. Pure diagnostics (lspci, ffmpeg
      # -hwaccels, vainfo), so it no longer waits behind a running uWSGI.
      echo "🔍 Running hardware acceleration check..."
      . /app/docker/init/04-check-hwaccel.sh
  ```

  and append this block immediately after the `fi` that closes the whole
  `if all|api … elif relay|worker … fi` construct (line 446), before the
  `if [[ "$DISPATCHARR_ROLE" == "all" ]]; then` block that hands PostgreSQL to supervisord:

  ```bash

  # Hardware acceleration is a diagnostic (lspci, ffmpeg -hwaccels, vainfo;
  # nothing exported downstream) about whether *this* process can reach a
  # GPU. Before this PR that was always the all/api process; from this PR on,
  # apps/proxy/live_proxy/'s ffmpeg spawning runs in the relay process's
  # request path (docker/nginx.conf routes stream tunes there), so relay
  # needs the same report. worker runs no ffmpeg and stays excluded.
  # This reverses the note PR 3 added to the spec's PR 4 section, which
  # recorded the gap as a deliberate PR 4 decision -- PR 4 decides the
  # other way (spec amendment S2).
  if [[ "$DISPATCHARR_ROLE" != "worker" ]]; then
      echo "🔍 Running hardware acceleration check..."
      . /app/docker/init/04-check-hwaccel.sh
  fi
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash -n docker/entrypoint.sh && echo "syntax OK"
  grep -c "04-check-hwaccel.sh" docker/entrypoint.sh
  grep -n 'DISPATCHARR_ROLE" != "worker"' docker/entrypoint.sh
  ```
  Expected: `syntax OK`; `1` (the check is sourced from exactly one place now, not two); one hit for
  the new gate.

- [ ] **Step 2: Commit**

  ```bash
  git add docker/entrypoint.sh
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-7.txt`:
  ```
  fix(docker): run the hwaccel check for relay too, not just all/api

  apps/proxy/live_proxy/'s ffmpeg spawning now runs in the relay process's
  request path (docker/nginx.conf routes stream tunes there). The
  diagnostic is pure echo output with nothing consumed downstream, so
  moving it out of the migrate/collectstatic block and gating it on
  role != worker instead costs nothing for all/api and adds relay. This
  reverses the note PR 3 added to the spec's PR 4 section, amended in the
  same PR as S2.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-7.txt
  ```

---
### Task 9: Point the DVR at nginx in AIO, and keep dev on the uwsgi port (D6 / S3)

**Files:**
- Test: `apps/channels/tests/test_dvr_port_resolution.py` (8 existing tests; 2 assertions change,
  1 docstring is retargeted, 1 new test added — 9 total)
- Modify: `apps/channels/tasks.py` (lines 1306-1329, `get_dvr_stream_base_url`'s docstring and
  final branch)

**Interfaces:**
- Consumes/Produces: `get_dvr_stream_base_url() -> str` — same name, same signature. The priority
  order grows from three tiers to four: explicit override → modular → **dev** → AIO/anything else.
  Single call site unchanged (`tasks.py:1582`, feeding `_dvr_build_ffmpeg_cmd` through the
  `stream_url` built at `tasks.py:1640`).

- [ ] **Step 1: Update the tests first (red)**

  The tree has exactly **three** tests asserting `http://127.0.0.1:5656` (`grep -n "5656"` — three,
  not the spec's four; amendment S4). Two become `9191`; the `dev` one keeps `5656` and gains a
  docstring explaining why (amendment S3). Replace lines 14-30 of
  `apps/channels/tests/test_dvr_port_resolution.py`:

  ```python
      @patch.dict(os.environ, {}, clear=True)
      def test_aio_default_uses_localhost_5656(self):
          """AIO mode (default) reaches uwsgi directly on loopback port 5656."""
          url = get_dvr_stream_base_url()
          self.assertEqual(url, 'http://127.0.0.1:5656')

      @patch.dict(os.environ, {'DISPATCHARR_ENV': 'aio'}, clear=True)
      def test_aio_explicit_uses_localhost_5656(self):
          """Explicit DISPATCHARR_ENV=aio also uses loopback port 5656."""
          url = get_dvr_stream_base_url()
          self.assertEqual(url, 'http://127.0.0.1:5656')

      @patch.dict(os.environ, {'DISPATCHARR_ENV': 'dev'}, clear=True)
      def test_dev_mode_uses_localhost_5656(self):
          """Dev mode shares the container with uwsgi — uses loopback port 5656."""
          url = get_dvr_stream_base_url()
          self.assertEqual(url, 'http://127.0.0.1:5656')
  ```

  with:

  ```python
      @patch.dict(os.environ, {}, clear=True)
      def test_aio_default_uses_localhost_nginx_port(self):
          """AIO mode (default) reaches uwsgi through nginx, on DISPATCHARR_PORT
          (default 9191) — not the uwsgi socket's own port 5656 directly. Once
          PR 5 puts /proxy/ts/stream/<uuid> behind the authorize hop, a
          recording that bypassed nginx would bypass authorization (D6)."""
          url = get_dvr_stream_base_url()
          self.assertEqual(url, 'http://127.0.0.1:9191')

      @patch.dict(os.environ, {'DISPATCHARR_ENV': 'aio'}, clear=True)
      def test_aio_explicit_uses_localhost_nginx_port(self):
          """Explicit DISPATCHARR_ENV=aio also goes through nginx on port 9191."""
          url = get_dvr_stream_base_url()
          self.assertEqual(url, 'http://127.0.0.1:9191')

      @patch.dict(os.environ, {'DISPATCHARR_ENV': 'dev'}, clear=True)
      def test_dev_mode_keeps_the_uwsgi_port(self):
          """Dev is the one mode that must NOT go through DISPATCHARR_PORT.

          docker/supervisord/all-dev.conf includes vite.conf, not nginx.conf —
          dev runs no nginx at all — and frontend/vite.config.js proxies only
          /api and /ws. A DVR fetch of /proxy/ts/stream/<uuid> through vite
          would record vite's index.html, so dev keeps reaching uwsgi's own
          http listener on 5656. The consequence, recorded for PR 5: in dev a
          recording bypasses the authorize hop (spec S3)."""
          url = get_dvr_stream_base_url()
          self.assertEqual(url, 'http://127.0.0.1:5656')

      @patch.dict(os.environ, {'DISPATCHARR_ENV': 'aio', 'DISPATCHARR_PORT': '9195'}, clear=True)
      def test_aio_honours_custom_dispatcharr_port(self):
          """A non-default DISPATCHARR_PORT (a custom_port deployment) is
          honoured, matching docker/init/03-init-dispatcharr.sh's own NGINX_PORT
          sed and its 9191 default."""
          url = get_dvr_stream_base_url()
          self.assertEqual(url, 'http://127.0.0.1:9195')
  ```

  Run:
  ```bash
  docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr4 /dispatcharrpy/bin/python manage.py test --keepdb apps.channels.tests.test_dvr_port_resolution -v2 </dev/null
  ```
  Expected: FAIL — `Ran 9 tests`, with exactly three failures:
  `test_aio_default_uses_localhost_nginx_port`, `test_aio_explicit_uses_localhost_nginx_port` and
  `test_aio_honours_custom_dispatcharr_port`, each `AssertionError: 'http://127.0.0.1:5656' !=
  'http://127.0.0.1:9191'` (or `:9195`). `test_dev_mode_keeps_the_uwsgi_port` already passes, and so
  do the five modular/override tests.

- [ ] **Step 2: Change the function (green)**

  In `apps/channels/tasks.py`, replace lines 1306-1329:

  ```python
  def get_dvr_stream_base_url():
      """Return the single correct base URL for DVR to reach the TS stream proxy.

      Priority:
      1. DISPATCHARR_INTERNAL_TS_BASE_URL — explicit override, always wins.
      2. Modular mode (DISPATCHARR_ENV=modular) — celery runs in a separate container
         and must reach the web container by its Docker service name on DISPATCHARR_PORT.
         Override the host with DISPATCHARR_WEB_HOST for non-standard compose setups.
      3. AIO / dev / debug — celery shares the container with uwsgi which binds on
         port 5656; use 127.0.0.1 to avoid any nginx layer.
      """
      explicit = os.environ.get('DISPATCHARR_INTERNAL_TS_BASE_URL')
      if explicit:
          return explicit.rstrip('/')

      dispatcharr_env = os.environ.get('DISPATCHARR_ENV', 'aio').lower()

      if dispatcharr_env == 'modular':
          host = os.environ.get('DISPATCHARR_WEB_HOST', 'web')
          port = os.environ.get('DISPATCHARR_PORT', '9191')
          return f'http://{host}:{port}'

      # AIO, dev, debug: celery and uwsgi share the container, reach uwsgi directly
      return 'http://127.0.0.1:5656'
  ```

  with:

  ```python
  def get_dvr_stream_base_url():
      """Return the single correct base URL for DVR to reach the TS stream proxy.

      Priority:
      1. DISPATCHARR_INTERNAL_TS_BASE_URL — explicit override, always wins.
      2. Modular mode (DISPATCHARR_ENV=modular) — celery runs in a separate container
         and must reach the web container by its Docker service name on DISPATCHARR_PORT.
         Override the host with DISPATCHARR_WEB_HOST for non-standard compose setups.
      3. Dev (and debug, which sets DISPATCHARR_ENV=dev too) — docker/supervisord/
         all-dev.conf runs vite, not nginx, and frontend/vite.config.js proxies only
         /api and /ws, so DISPATCHARR_PORT would serve vite's index.html here. Reach
         uwsgi's own http listener on 5656 instead. Consequence for Phase 1 PR 5:
         in dev a recording bypasses the authorize hop.
      4. AIO — celery shares the container with nginx; go through nginx on
         DISPATCHARR_PORT (default 9191), not the uwsgi socket's own port 5656
         directly (D6, Phase 1 PR 4). The DVR fetches /proxy/ts/stream/<uuid>
         exactly like a player; once that route sits behind the authorize hop
         (PR 5), a recording that bypassed nginx would bypass authorization.
      """
      explicit = os.environ.get('DISPATCHARR_INTERNAL_TS_BASE_URL')
      if explicit:
          return explicit.rstrip('/')

      dispatcharr_env = os.environ.get('DISPATCHARR_ENV', 'aio').lower()

      if dispatcharr_env == 'modular':
          host = os.environ.get('DISPATCHARR_WEB_HOST', 'web')
          port = os.environ.get('DISPATCHARR_PORT', '9191')
          return f'http://{host}:{port}'

      if dispatcharr_env == 'dev':
          # No nginx in this deployment shape — reach uwsgi's http listener.
          return 'http://127.0.0.1:5656'

      # AIO: reach nginx, not the uwsgi socket directly.
      port = os.environ.get('DISPATCHARR_PORT', '9191')
      return f'http://127.0.0.1:{port}'
  ```

  Run:
  ```bash
  docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr4 /dispatcharrpy/bin/python manage.py test --keepdb apps.channels.tests.test_dvr_port_resolution -v2 </dev/null
  ```
  Expected: PASS — `Ran 9 tests`, `OK`.

  Run (credential-logging guard, since this touches `apps/channels/tasks.py`):
  ```bash
  docker exec dispatcharr-testrunner-pr4 python3 /repo/scripts/check_credential_logging.py apps/channels/tasks.py </dev/null
  ```
  Expected: clean, exit 0 — the `logger.debug(..., redact_url(base_url))` call near `tasks.py:1584`
  is unchanged; this task edits only the value that function returns, not the log call.

- [ ] **Step 3: Run the whole package (the commit-gate scope)**

  Run:
  ```bash
  docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr4 /dispatcharrpy/bin/python manage.py test --keepdb apps.channels.tests -v1 </dev/null
  ```
  Expected: `OK` for the full package. This is the label the commit gate derives for a change under
  `apps/channels/`.

- [ ] **Step 4: Commit**

  ```bash
  git add apps/channels/tasks.py apps/channels/tests/test_dvr_port_resolution.py
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-8.txt`:
  ```
  fix(dvr): fetch the TS stream through nginx in AIO, not the uwsgi socket

  get_dvr_stream_base_url()'s AIO branch changes from the hardcoded
  http://127.0.0.1:5656 to http://127.0.0.1:{DISPATCHARR_PORT} (default
  9191). The DVR fetches /proxy/ts/stream/<uuid> exactly like a player;
  once PR 5 puts that route behind the authorize hop, a recording that
  bypasses nginx bypasses authorization (D6).

  dev is now its own branch and keeps 5656: all-dev.conf runs vite, not
  nginx, and vite proxies only /api and /ws, so DISPATCHARR_PORT there
  would record vite's index.html. In dev a recording therefore still
  bypasses the authorize hop -- recorded in the spec as amendment S3 so
  PR 5 designs for it. Modular and explicit-override branches unchanged.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-8.txt
  ```

---

### Task 10: Widen the nginx-buffering greybox spec's location filter

**Files:**
- Modify: `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` (the header comment's final
  paragraph at lines 90-96, and the test at lines 98-122)
- Modify: `e2e/tests/guards/allowlist.ts` (the two-line comment above this spec's `SUBPROCESS`
  entry, lines 62-63 — comment text only, no allowlist entry changes)

**Interfaces:**
- Consumes: unchanged — `docker exec <container> nginx -T`, the same `parseLocationBlocks` parser
  and its documented `target` normalisation (a regex location's leading `^` is stripped, so
  `location ~ ^/[^/]+/[^/]+/[^/]+$` has `target === '/[^/]+/[^/]+/[^/]+$'`).
- No new `test()` — this widens the existing `@contract` test's assertion scope, so no
  `docs/adr/0002` tag change and no `e2e/COVERAGE.md` row change is needed.

- [ ] **Step 1: Widen the filter, the title and the vacuous-pass guard**

  Replace the header comment's final paragraph (lines 90-96):

  ```
   * `@contract`, not `@characterization`, despite being on the `SUBPROCESS`
   * allowlist (normally a `@characterization` signal, `docs/adr/0002`): the
   * directive it pins is a load-bearing deploy fact that must survive the
   * process split, not an implementation detail of the current single-process
   * shape. A red run here is meant to block PR 4 by design, the way any other
   * `@contract` test does.
   */
  ```
  with:
  ```
   * `@contract`, not `@characterization`, despite being on the `SUBPROCESS`
   * allowlist (normally a `@characterization` signal, `docs/adr/0002`): the
   * directive it pins is a load-bearing deploy fact that must survive the
   * process split, not an implementation detail of the current single-process
   * shape. PR 4 is the process split this test was written to survive — its
   * location filter now covers every location that split introduced, not just
   * the original single `/proxy/` block.
   */
  ```

  Then replace the whole test (lines 98-122):

  ```typescript
  test(
    'the /proxy/ location keeps uwsgi_buffering off',
    { tag: '@contract' },
    async () => {
      const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
      const blocks = parseLocationBlocks(stdout);
      const proxyBlocks = blocks.filter((b) => b.target.startsWith('/proxy/'));

      // Vacuous-pass guard: if nginx's config ever stops declaring a /proxy/
      // location at all (renamed, merged into another block), the `.every()`
      // below would pass on an empty array and this test would silently stop
      // meaning anything. Fail loudly instead.
      expect(
        proxyBlocks.length,
        `expected at least one location block targeting /proxy/ in nginx -T's output; found blocks: ${blocks.map((b) => b.header).join(', ')}`
      ).toBeGreaterThan(0);

      for (const block of proxyBlocks) {
        expect(
          block.body.some((line) => /^\s*uwsgi_buffering\s+off\s*;/.test(line)),
          `location block "${block.header}" does not set uwsgi_buffering off:\n${block.body.join('\n')}`
        ).toBe(true);
      }
    }
  );
  ```

  with:

  ```typescript
  /**
   * Every relay-bound location as of Phase 1 PR 4 (docker/nginx.conf), by the
   * exact `target` `parseLocationBlocks` produces for it. Widened from the
   * original single `/proxy/` prefix once that block split into eight
   * relay-bound locations plus the XC three-segment regex — this list is what
   * keeps the buffering pin covering the whole relay surface rather than the
   * one route it happened to be written against.
   *
   * **Exact targets, deliberately, not `startsWith` prefixes.** A prefix test
   * on `/proxy/vod/` also matches the `= /proxy/vod/stats/` and
   * `= /proxy/vod/stop_client/` exact locations, which stay on the API and
   * correctly carry no `uwsgi_buffering off` — the same trap applies to the
   * three `/proxy/catchup/` control routes. Comparing whole targets keeps the
   * filter naming exactly the nine blocks it means.
   *
   * Two relay-adjacent locations are absent on purpose: `^~ /proxy/`, which is
   * the API's own short IsAdmin control routes, and `^~ /proxy/relay/`, PR 7's
   * control API, which will serve short JSON rather than a stream.
   *
   * A third is absent because it cannot appear: PR 4 also routes
   * `^/api/channels/recordings/\d+/file/$` to the relay, but that location is
   * **nested inside `^~ /api/`**, and `parseLocationBlocks` walks by brace
   * depth from each `location` header — so the nested block's lines are part
   * of `/api/`'s own `body`, and it never surfaces as a separate entry with a
   * `target` of its own. Adding it to this list would make the set assertion
   * below fail on a correct config. Its `uwsgi_buffering off` is pinned by
   * `docker/nginx.conf` review and Task 5's grep counts instead.
   *
   * The last entry is the XC three-segment root form: `parseLocationBlocks`
   * strips a regex location's leading `^` from its `target`, so this is the
   * literal the parser produces for `location ~ ^/[^/]+/[^/]+/[^/]+$`.
   */
  const RELAY_BOUND_TARGETS = [
    '/proxy/ts/stream/',
    '/proxy/vod/',
    '/proxy/catchup/',
    '/live/',
    '/movie/',
    '/series/',
    '/timeshift/',
    '/streaming/timeshift.php',
    '/[^/]+/[^/]+/[^/]+$',
  ];

  test(
    'every relay-bound location keeps uwsgi_buffering off',
    { tag: '@contract' },
    async () => {
      const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
      const blocks = parseLocationBlocks(stdout);
      const relayBlocks = blocks.filter((b) => RELAY_BOUND_TARGETS.includes(b.target));

      // Vacuous-pass guard: if nginx's config ever stops declaring these
      // locations (renamed, merged, or the relay split reverted), the loop
      // below would pass over an empty array and this test would silently
      // stop meaning anything. Fail loudly instead — and assert the full set,
      // not just "more than zero", so losing eight of the nine is a failure
      // rather than a pass.
      expect(
        relayBlocks.map((b) => b.target).sort(),
        `expected every relay-bound location in nginx -T's output (${RELAY_BOUND_TARGETS.join(', ')}); found blocks: ${blocks.map((b) => b.header).join(', ')}`
      ).toEqual([...RELAY_BOUND_TARGETS].sort());

      for (const block of relayBlocks) {
        expect(
          block.body.some((line) => /^\s*uwsgi_buffering\s+off\s*;/.test(line)),
          `location block "${block.header}" does not set uwsgi_buffering off:\n${block.body.join('\n')}`
        ).toBe(true);
      }
    }
  );
  ```

- [ ] **Step 2: Correct the allowlist's description of this spec**

  `e2e/tests/guards/allowlist.ts`'s `SUBPROCESS` entry still describes this file as pinning "the
  `/proxy/` location". The entry itself is correct and does not change; only its comment is now
  stale. Replace lines 62-63:

  ```typescript
      // Reads the resolved nginx config with `docker exec ... nginx -T` to pin
      // uwsgi_buffering off on the /proxy/ location.
  ```
  with:
  ```typescript
      // Reads the resolved nginx config with `docker exec ... nginx -T` to pin
      // uwsgi_buffering off on every relay-bound location (Phase 1 PR 4 split
      // the original single /proxy/ block into nine).
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/e2e && npx tsc --noEmit
  ```
  Expected: no output (no type errors).

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/e2e && npx playwright test --project=guards
  ```
  Expected: PASS — `tags.spec.ts` still finds exactly one tag on the renamed test, and
  `capabilities.spec.ts` still finds this file on the `SUBPROCESS` allowlist only. The comment edit
  is invisible to the guard by design: `capabilities.spec.ts` matches markers in string and template
  literals only, never in comments.

- [ ] **Step 3: Note the runtime verification, which belongs to Task 14**

  This spec cannot pass until an image carrying Task 5's `docker/nginx.conf` is running. It is run
  in **Task 14 Step 4**, against the pr4 stack, as
  `npx playwright test --project=streaming-greybox -g relay-bound`. Do not block this commit on it,
  and do not skip it there.

- [ ] **Step 4: Commit**

  ```bash
  git add e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts e2e/tests/guards/allowlist.ts
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-9.txt`:
  ```
  test(e2e): widen the nginx-buffering pin to every relay-bound location

  Was /proxy/ only; PR 4 splits that one block into seven relay-bound ^~
  prefixes, one exact match and the XC three-segment regex, all
  uwsgi_buffering off. The guard now asserts the exact set of locations
  found, not merely that the set is non-empty, so losing one is a failure
  rather than a pass. Same test, same @contract tag, same SUBPROCESS
  allowlist entry -- only that entry's comment changes, to stop describing
  the pin as covering "the /proxy/ location".

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-9.txt
  ```

---

### Task 11: `instance.supervisorctl()` and the restart-persistence reshape

**Files:**
- Modify: `e2e/fixtures/instance.ts` (add a method after `manage()`, which ends at line 385, before
  the class's closing `}` at line 386)
- Modify: `e2e/tests/lifecycle/restart-persistence.spec.ts` (imports at lines 9-15; the test's
  destructured fixture list at lines 27-32; new assertions before the closing `});`)

**Interfaces:**
- Produces: `Instance.supervisorctl(argv: string[]): Promise<ManageResult>` — same return shape and
  the same plain-token argument validation as `manage()`, `docker exec`ing
  `supervisorctl -c /app/docker/supervisord/supervisorctl.conf <argv>` instead of
  `su - dispatch -c "python manage.py ..."`.
- Consumes (in the spec): `lockedProfile` from `../streaming/helpers`, and `StreamStatusError`,
  `expectTsAligned`, `TS_PACKET_SIZE` plus the `streamClient` fixture from `../../fixtures`.

- [ ] **Step 1: Add `supervisorctl()` to `e2e/fixtures/instance.ts`**

  After `manage()` (ending at line 385), before the class's closing `}`, add:

  ```typescript

    /**
     * Run `supervisorctl` inside the container, returning the exit code rather
     * than throwing — `supervisorctl status` exits non-zero when any queried
     * process isn't RUNNING, which callers here check by inspecting `stdout`,
     * not `code`.
     *
     * `docker/supervisord/supervisorctl.conf` is the one config this always
     * points at: it carries only a `[supervisorctl]` section naming the same
     * `unix:///run/supervisor.sock` every rung's `[unix_http_server]` listens
     * on, so it works whichever role (`all`/`api`/`relay`/`worker`) the
     * container is actually running — see that file's own header comment.
     *
     * `argv` reaches `docker exec` as an argv array, not a shell string, so
     * the same plain-token restriction `manage()` applies is more than
     * enough; it is kept for symmetry with that method rather than out of
     * quoting need.
     */
    async supervisorctl(argv: string[]): Promise<ManageResult> {
      for (const arg of argv) {
        if (!/^[A-Za-z0-9._/=-]+$/.test(arg)) {
          throw new Error(
            `instance.supervisorctl() argument ${JSON.stringify(arg)} contains ` +
              'characters that are not plain tokens.'
          );
        }
      }
      try {
        const { stdout, stderr } = await run(
          'docker',
          [
            'exec',
            CONTAINER,
            'supervisorctl',
            '-c',
            '/app/docker/supervisord/supervisorctl.conf',
            ...argv,
          ],
          { timeout: DOCKER_TIMEOUT_MS, maxBuffer: MAX_BUFFER }
        );
        return { code: 0, stdout, stderr };
      } catch (error) {
        if (isExecError(error) && typeof error.code === 'number') {
          return {
            code: error.code,
            stdout: error.stdout ?? '',
            stderr: error.stderr ?? '',
          };
        }
        throw new Error(
          `docker exec … supervisorctl ${argv.join(' ')} did not run: ${String(error)}`
        );
      }
    }
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/e2e && npx tsc --noEmit
  ```
  Expected: no output — `ManageResult`, `run`, `CONTAINER`, `DOCKER_TIMEOUT_MS`, `MAX_BUFFER` and
  `isExecError` are all already in scope in this file (`manage()`, immediately above, uses every
  one).

- [ ] **Step 2: Reshape `restart-persistence.spec.ts`**

  Replace the import line (line 9):

  ```typescript
  import { test, expect, ApiClient, Seeder, Waiter } from '../../fixtures';
  ```
  with:
  ```typescript
  import {
    test,
    expect,
    ApiClient,
    Seeder,
    StreamStatusError,
    TS_PACKET_SIZE,
    Waiter,
    expectTsAligned,
  } from '../../fixtures';
  import { lockedProfile } from '../streaming/helpers';
  ```

  Add `streamClient` to the test's destructured fixtures. Replace lines 27-32:

  ```typescript
  test('durable state and the signing key survive a container restart', { tag: '@characterization' }, async ({
    instance,
    request,
    baseURL,
    upstream,
  }, testInfo) => {
  ```
  with:
  ```typescript
  test('durable state and the signing key survive a container restart', { tag: '@characterization' }, async ({
    instance,
    request,
    baseURL,
    upstream,
    // Safe to take alongside the hand-built ApiClient below: the
    // `streamClient` fixture depends only on `baseURL`, so unlike
    // `api`/`seed`/`waitFor` it reads nothing from `playwright/.auth/`.
    streamClient,
  }, testInfo) => {
  ```

  Then, after the existing final two lines of the test body:

  ```typescript
    await assertAdminTokenStillValid(request, tokens.access);
    await assertDurableState(api, request, state);
  ```

  and before the closing `});`, add:

  ```typescript

    // Phase 1 PR 4 reshape: two uWSGI processes now live behind this one
    // container, and a restart must bring both back, not just the container's
    // own liveness. This is as far as the AIO harness can take the two-unit
    // restart the file's @characterization header warned about; the
    // restart-one-not-the-other scenario across separate containers lives in
    // docker/tests/test-puid-pgid.sh's test_role_split.
    //
    // Polled, not asserted once. supervisord reports RUNNING as soon as a
    // program has stayed alive `startsecs=5`, and both uWSGI programs run
    // through wait-for-stores.sh, so RUNNING can precede the store waits
    // finishing (docker/tests/test-puid-pgid.sh:180 says the same thing).
    await expect
      .poll(async () => (await instance.supervisorctl(['status', 'api-uwsgi'])).stdout, {
        timeout: 60_000,
        message: 'api-uwsgi did not return to RUNNING after the restart',
      })
      .toMatch(/RUNNING/);
    await expect
      .poll(async () => (await instance.supervisorctl(['status', 'relay-uwsgi'])).stdout, {
        timeout: 60_000,
        message: 'relay-uwsgi did not return to RUNNING after the restart',
      })
      .toMatch(/RUNNING/);

    // A stream re-tunes after the restart. Deliberately a *fresh* scenario and
    // channel, not durable-state.ts's pre-restart channel: that channel's
    // upstream scenario lives in the fake provider's in-memory
    // ScenarioRegistry, which `instance.restart()` also restarts. Asserting
    // against it here would be asserting against an upstream that no longer
    // exists, for a reason unrelated to whether the relay came back.
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'restart re-tune', tvgId: 'restart-retune.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });

    // RUNNING is not listening: nginx answers 502 while relay-uwsgi's socket
    // is still unbound. Retry the tune itself rather than trusting the status
    // line — a bare open() here is the race this reshape exists to avoid.
    //
    // Nothing is rethrown from this callback. `expect.poll` does not retry a
    // callback that throws — it fails the test on the first throw — so a
    // transient fetch failure (a connection reset while nginx and the uWSGI
    // workers finish recycling, seconds after the container comes back) would
    // end the test outright instead of being retried like the 502 beside it.
    // Every outcome becomes a string instead, so the 60s budget covers all of
    // them and the failure message prints the last one received. It has to be
    // the polled *value* that carries the reason: `expect.poll`'s `message`
    // option is typed `string`, not a callback
    // (`playwright/types/test.d.ts`, `poll<T>`), so a thunk there would not
    // compile.
    await expect
      .poll(
        async () => {
          try {
            await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
            return 'ok';
          } catch (error) {
            if (error instanceof StreamStatusError) return `HTTP ${error.status}`;
            return String(error);
          }
        },
        {
          timeout: 60_000,
          intervals: [2_000],
          message: 'the relay never served a tune after the restart',
        }
      )
      .toBe('ok');

    const packet = await streamClient.readPackets(1);
    expect(packet.byteLength).toBe(TS_PACKET_SIZE);
    expectTsAligned(packet);
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/e2e && npx tsc --noEmit
  ```
  Expected: no output. `api` and `seed` are local `const`s already declared earlier in this test
  body (lines 37 and 42), so no further fixture is needed for them.

- [ ] **Step 3: Note the runtime verification, which CI owns**

  Do **not** run `--project=lifecycle` locally in this worktree. `instance.restart()` is
  `scripts/e2e_up.sh --stop` followed by a start, and `--stop` stops `$UPSTREAM_NAME`, which
  defaults to the **shared** `e2e-upstream` provider container — the one every other local
  Playwright project is using. CI's `lifecycle-tests.yml` runs this project on its own runner with
  nothing shared, and that is the evidence for this task. Task 14 runs the two projects that can be
  run safely against a pr4-suffixed stack instead.

- [ ] **Step 4: Commit**

  ```bash
  git add e2e/fixtures/instance.ts e2e/tests/lifecycle/restart-persistence.spec.ts
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-10.txt`:
  ```
  test(e2e): assert both uWSGI processes come back after a restart

  instance.supervisorctl(), same shape as the existing manage() helper,
  pointed at docker/supervisord/supervisorctl.conf so it works whatever
  role the container runs. restart-persistence.spec.ts now polls for
  api-uwsgi and relay-uwsgi RUNNING and then retries a real tune on
  502/503/504 -- RUNNING means the program stayed alive startsecs=5, not
  that uWSGI is bound, so a bare assertion would race the boot. The tune
  uses a freshly seeded channel, not the pre-restart durable-state one,
  whose upstream scenario the provider forgets across a restart.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-10.txt
  ```

---
### Task 12: `test_role_split` — the modular three-container scenario

**Files:**
- Modify: `docker/tests/test-puid-pgid.sh` — one new `-e` line on `test_modular_mode`'s `docker run`
  (lines 1078-1087); a new "ensure the fake-provider image exists" block after the
  `PG16_AVAILABLE` block (which ends at line 1581) and before
  `# Build test image from local changes` (line 1583); a new `test_role_split` function after
  `test_modular_mode`, which ends at line 1138; a new entry in the `SCENARIOS` array (lines
  1597-1618)

**Interfaces:**
- Consumes: `dispatcharr-e2e-upstream:local` (built locally if absent; CI's `suites` job already
  `docker load`s it from the shared build artifact), `$IMAGE_NAME` (`dispatcharr:puid-test`),
  `$TEST_PREFIX` (`puid_test`), and the file's own helpers `section`, `log_pass`, `log_fail`,
  `log_info`, `fresh_volume`, `track_container`, `track_network`, `cleanup_scenario`,
  `wait_for_ready`, `supervisorctl_status`, `dump_logs_on_fail`.
- Produces: `test_role_split` — seven containers (postgres, redis, the fake provider, and three app
  containers `api`/`relay`/`worker`) on one network, the three app containers sharing one `/data`
  volume, seeded and read through the api container's own nginx by one `python3` script.

- [ ] **Step 1: Keep `test_modular_mode` bootable (regression from Task 6)**

  Task 6 makes every modular role-`api` container `sed` `RELAY_UPSTREAM` to
  `${DISPATCHARR_RELAY_HOST:-relay}:5657`. `test_modular_mode` (`:1037-1138`) starts exactly such a
  container — modular, role defaulted to `api` — with **no relay container on its network and no
  `DISPATCHARR_RELAY_HOST`**. nginx would then fail config load with "host not found in upstream",
  `[program:nginx]` would go BACKOFF then FATAL, and that scenario's own assertions at `:1112-1127`
  would fail twice ("FATAL/BACKOFF" and "not RUNNING: nginx"), turning `Lifecycle result` red on
  this branch. This is the plan's own MAJOR-6 reasoning landing on an existing scenario, and it must
  be fixed in the same PR that introduces the cause.

  In `test_modular_mode`'s `docker run` (lines 1078-1087), add one line after
  `-e REDIS_HOST="$redis_name" \`:

  ```bash
          -e DISPATCHARR_RELAY_HOST=127.0.0.1 \
  ```

  (eight spaces of indentation, matching the `-e` lines around it), and, above the `docker run`,
  extend the existing "No DISPATCHARR_ROLE on purpose" comment with a second paragraph at the
  comment's own four-space indentation:

  ```bash
      # DISPATCHARR_RELAY_HOST is set, though, and to loopback rather than to a
      # container name. From Phase 1 PR 4 nginx declares
      # `upstream relay_py { server <relay host>:5657; }` and resolves that name
      # once, at config load — so a role-api container with no relay on its
      # network must still be given something resolvable or nginx never starts.
      # Loopback always resolves and simply 502s at request time, which is the
      # correct behaviour for a deployment that has no relay: the API surface
      # this scenario actually asserts on stays up.
  ```

  `docker/tests/test-tls-postgres.sh` needs no equivalent change: it asserts only on `api-uwsgi` and
  issues no HTTP request, so an nginx that never loaded would not be caught there either way — but
  verify that with `grep -n "nginx" docker/tests/test-tls-postgres.sh` before concluding it.

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash -n docker/tests/test-puid-pgid.sh && echo "syntax OK"
  grep -n "DISPATCHARR_RELAY_HOST" docker/tests/test-puid-pgid.sh
  ```
  Expected: `syntax OK`, then one hit inside `test_modular_mode` (Step 3's `test_role_split` adds a
  second later, pointing at the relay container's name).

  Run (foreground, `</dev/null`, 600000 ms timeout — this scenario boots its own containers):
  ```bash
  bash docker/tests/test-puid-pgid.sh modular_mode </dev/null
  ```
  Expected: PASS, including `supervisorctl status: all three programs of role 'api' RUNNING`. **Run
  this after Tasks 5 and 6 have landed, not before** — before them there is no `RELAY_UPSTREAM` in
  `docker/nginx.conf` and the scenario passes for the old reason, proving nothing.

- [ ] **Step 2: Ensure the fake-provider image exists**

  This suite has never referenced `dispatcharr-e2e-upstream:local` before. In CI it is already
  present — `lifecycle-tests.yml`'s `build` job saves it alongside the AIO image and the `suites`
  job `docker load`s both — so this block is a local-developer convenience that no-ops on CI.
  Insert it after the `PG16_AVAILABLE` block (line 1581) and before the
  `# Build test image from local changes` comment (line 1583). It sits **outside** the
  `if [ "$SKIP_BUILD" = false ]` guard on purpose: CI passes `--skip-build`, and the `docker image
  inspect` below already makes the block a no-op there.

  ```bash

  # dispatcharr-e2e-upstream:local — the fake provider test_role_split seeds
  # against. CI's suites job already docker-loads it from the shared build
  # artifact, so this inspect succeeds there and nothing is built. Locally,
  # build it once if it is missing.
  if ! docker image inspect dispatcharr-e2e-upstream:local >/dev/null 2>&1; then
      section "Building fake upstream provider image"
      if docker build -f e2e-upstream/Dockerfile -t dispatcharr-e2e-upstream:local e2e-upstream >/dev/null; then
          log_pass "Upstream provider image built (dispatcharr-e2e-upstream:local)"
      else
          log_info "Upstream provider build failed — role_split will skip with a failure of its own"
      fi
  fi
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash -n docker/tests/test-puid-pgid.sh && echo "syntax OK"
  ```
  Expected: `syntax OK`.

- [ ] **Step 3: Write `test_role_split`**

  Insert immediately after `test_modular_mode`'s closing `}` (line 1138).

  **The `<<'PY'` heredoc's body and its closing `PY` both start at column 0**, inside an otherwise
  four-space-indented function. `<<'PY'` (not `<<-`) takes the body verbatim, so indenting it would
  prepend four spaces to every Python line and raise `IndentationError` at run time — something
  `bash -n` cannot catch. Write it exactly as shown.

  ```bash
  # Verifies the modular role split (Phase 1 PR 4): three app containers —
  # api, relay, worker — on one network, sharing one /data volume (SECRET_KEY
  # lives in /data/jwt; D11). TS bytes are read through the api container's
  # own nginx, which uwsgi_passes to the relay container over the network
  # (RELAY_UPSTREAM sed'd to <relay-container>:5657 in modular). This is the
  # only test in either bash suite exercising the cross-container relay hop:
  # scripts/e2e_up.sh is a single AIO `docker run`, so no Playwright project
  # can reach this topology.
  test_role_split() {
      CURRENT_SCENARIO="role_split"
      section "Modular role split — api, relay, worker containers (PR 4)"

      if ! docker image inspect dispatcharr-e2e-upstream:local >/dev/null 2>&1; then
          log_fail "dispatcharr-e2e-upstream:local not available; role_split cannot seed a channel"
          return
      fi

      local net="${TEST_PREFIX}_role_net"
      local pg_name="${TEST_PREFIX}_role_pg"
      local redis_name="${TEST_PREFIX}_role_redis"
      local upstream_name="${TEST_PREFIX}_role_upstream"
      local api_name="${TEST_PREFIX}_role_api"
      local relay_name="${TEST_PREFIX}_role_relay"
      local worker_name="${TEST_PREFIX}_role_worker"
      local vol="${TEST_PREFIX}_role_data"
      cleanup_scenario

      docker network create "$net" >/dev/null 2>&1
      fresh_volume "$vol"
      track_network "$net"
      track_container "$pg_name"
      track_container "$redis_name"
      track_container "$upstream_name"
      track_container "$api_name"
      track_container "$relay_name"
      track_container "$worker_name"

      docker run -d --name "$pg_name" --network "$net" \
          -e POSTGRES_USER=dispatch \
          -e POSTGRES_PASSWORD=secret \
          -e POSTGRES_DB=dispatcharr \
          postgres:17 >/dev/null

      docker run -d --name "$redis_name" --network "$net" \
          redis:latest >/dev/null

      # UPSTREAM_INTERNAL_ORIGIN: the provider echoes an internal stream URL
      # built from this on every /scenarios response (e2e-upstream/src/
      # server.ts), so the app containers on THIS network can reach it. Its
      # default names the shared e2e-upstream host, which does not exist here.
      docker run -d --name "$upstream_name" --network "$net" \
          -e "UPSTREAM_INTERNAL_ORIGIN=http://${upstream_name}:8080" \
          dispatcharr-e2e-upstream:local >/dev/null

      local elapsed=0
      while [ $elapsed -lt 30 ]; do
          if docker exec "$pg_name" pg_isready -U dispatch 2>/dev/null | grep -q "accepting"; then
              break
          fi
          sleep 2
          ((elapsed+=2))
      done

      # relay BEFORE api, deliberately. nginx in the api container resolves
      # `upstream relay_py { server <relay>:5657; }` ONCE, at config load. With
      # no relay container in Docker's DNS by then, nginx fails config load
      # with "host not found in upstream" and [program:nginx] goes BACKOFF then
      # FATAL — the api container would then fail for a reason that has
      # nothing to do with what this scenario is testing.
      #
      # The relay's own entrypoint waits on `migrate --check`, which only the
      # api container ever satisfies, so it sits waiting until api has
      # migrated. That is fine: DNS resolves as soon as the container exists.
      docker run -d --name "$relay_name" --network "$net" \
          -e DISPATCHARR_ENV=modular -e DISPATCHARR_ROLE=relay \
          -e POSTGRES_HOST="$pg_name" -e POSTGRES_PORT=5432 \
          -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=dispatcharr \
          -e REDIS_HOST="$redis_name" \
          -v "${vol}:/data" \
          "$IMAGE_NAME" >/dev/null

      # No published port: every HTTP call below runs inside this container
      # through `docker exec`, so nothing on the host needs to reach it.
      docker run -d --name "$api_name" --network "$net" \
          -e DISPATCHARR_ENV=modular -e DISPATCHARR_ROLE=api \
          -e POSTGRES_HOST="$pg_name" -e POSTGRES_PORT=5432 \
          -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=dispatcharr \
          -e REDIS_HOST="$redis_name" \
          -e DISPATCHARR_RELAY_HOST="$relay_name" \
          -v "${vol}:/data" \
          "$IMAGE_NAME" >/dev/null

      docker run -d --name "$worker_name" --network "$net" \
          -e DISPATCHARR_ENV=modular -e DISPATCHARR_ROLE=worker \
          -e POSTGRES_HOST="$pg_name" -e POSTGRES_PORT=5432 \
          -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=dispatcharr \
          -e REDIS_HOST="$redis_name" \
          -e DISPATCHARR_WEB_HOST="$api_name" \
          "$IMAGE_NAME" >/dev/null

      if ! wait_for_ready "$api_name" 180; then
          log_fail "api container failed to start"
          dump_logs_on_fail "$api_name"
          dump_logs_on_fail "$relay_name"
          dump_logs_on_fail "$worker_name"
          cleanup_scenario
          return
      fi

      # The relay only leaves its migrate-wait once api has migrated, so it is
      # polled separately and with its own budget. RUNNING is still a weaker
      # claim than "listening" (see wait_for_ready's header), which is why the
      # seeding script below retries the tune itself.
      local relay_elapsed=0
      while [ $relay_elapsed -lt 180 ]; do
          if supervisorctl_status "$relay_name" relay-uwsgi | grep -q "RUNNING"; then
              break
          fi
          sleep 3
          ((relay_elapsed+=3))
      done

      # The worker needs its own poll, for the same reason and on the same
      # budget. It leaves the migrate-wait within a second or two of the relay
      # and celery-default has startsecs=5 (docker/supervisord.d/
      # celery-default.conf), so a status read taken right after the relay's
      # poll regularly lands while celery-default is still STARTING -- or
      # before supervisord's socket exists at all, when supervisorctl_status
      # returns nothing. Either way the assertion below would log_fail
      # intermittently on a required CI job.
      local worker_elapsed=0
      while [ $worker_elapsed -lt 180 ]; do
          if supervisorctl_status "$worker_name" celery-default | grep -q "RUNNING"; then
              break
          fi
          sleep 3
          ((worker_elapsed+=3))
      done

      # supervisorctl status per role, proving each container runs the
      # program(s) its own rung's [include] names (docker/supervisord/
      # {api,relay,worker}.conf) and that none is FATAL or BACKOFF.
      local api_ctl relay_ctl worker_ctl
      api_ctl=$(supervisorctl_status "$api_name")
      if echo "$api_ctl" | grep -q "api-uwsgi.*RUNNING" && ! echo "$api_ctl" | grep -qE "FATAL|BACKOFF"; then
          log_pass "api container: api-uwsgi RUNNING, nothing FATAL/BACKOFF"
      else
          log_fail "api container supervisorctl status unexpected: $api_ctl"
      fi
      relay_ctl=$(supervisorctl_status "$relay_name")
      if echo "$relay_ctl" | grep -q "relay-uwsgi.*RUNNING" && ! echo "$relay_ctl" | grep -qE "FATAL|BACKOFF"; then
          log_pass "relay container: relay-uwsgi RUNNING, nothing FATAL/BACKOFF"
      else
          log_fail "relay container supervisorctl status unexpected: $relay_ctl"
      fi
      worker_ctl=$(supervisorctl_status "$worker_name")
      if echo "$worker_ctl" | grep -q "celery-default.*RUNNING" && ! echo "$worker_ctl" | grep -qE "FATAL|BACKOFF"; then
          log_pass "worker container: celery-default RUNNING, nothing FATAL/BACKOFF"
      else
          log_fail "worker container supervisorctl status unexpected: $worker_ctl"
      fi

      # Seed a channel and read TS bytes through the api container's nginx —
      # proving nginx routed to the relay container over the network, the relay
      # tuned the upstream, and the bytes came back TS-aligned. One python3
      # process inside the api container does the whole sequence (superuser,
      # token, provider scenario, stream, channel, byte read) so there is
      # nothing to shuttle between separate docker exec calls. It prints one
      # line: OK:<uuid>, BAD-ALIGNMENT:<bytes> or ERROR:<message>.
      local result
      result=$(docker exec -i "$api_name" python3 - "$upstream_name" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

upstream_host = sys.argv[1]
base = "http://127.0.0.1:9191"
upstream_control = "http://%s:8080" % upstream_host


def call(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


try:
    _, state = call("GET", base + "/api/accounts/initialize-superuser/")
    if not (state or {}).get("superuser_exists"):
        call("POST", base + "/api/accounts/initialize-superuser/", {
            "username": "role-split-admin",
            "password": "Role-Split-Test-42!",
            "email": "role-split-admin@example.com",
        })
    _, tokens = call("POST", base + "/api/accounts/token/", {
        "username": "role-split-admin",
        "password": "Role-Split-Test-42!",
    })
    auth = {"Authorization": "Bearer " + tokens["access"]}

    _, profiles = call("GET", base + "/api/core/streamprofiles/", headers=auth)
    rows = profiles if isinstance(profiles, list) else profiles.get("results", [])
    proxy_profile = next(p for p in rows if p["name"] == "Proxy")

    _, scenario = call("POST", upstream_control + "/scenarios", {
        "channels": [
            {"id": 1, "name": "role-split", "tvgId": "role-split.e2e", "logo": None}
        ],
        "rate": 20,
    })
    # Mirrors Seeder.upstreamStreamUrl() in e2e/fixtures/seed.ts.
    stream_url = "%s/stream/1.ts%s" % (
        scenario["internal"], scenario.get("credentialQuery", "")
    )

    _, stream = call("POST", base + "/api/channels/streams/", {
        "name": "role-split-stream",
        "url": stream_url,
        "is_custom": True,
    }, headers=auth)

    _, channel = call("POST", base + "/api/channels/channels/", {
        "name": "role-split-channel",
        "streams": [stream["id"]],
        "stream_profile_id": proxy_profile["id"],
    }, headers=auth)

    # relay-uwsgi RUNNING is not relay-uwsgi listening: nginx answers
    # 502/503/504 while the socket is still unbound. Retry for up to 60s.
    deadline = time.monotonic() + 60
    packet = b""
    last = "never attempted"
    while True:
        try:
            req = urllib.request.Request(base + "/proxy/ts/stream/" + channel["uuid"])
            with urllib.request.urlopen(req, timeout=15) as resp:
                packet = resp.read(189)
            break
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code not in (502, 503, 504) or time.monotonic() >= deadline:
                break
            time.sleep(2)
        except Exception as exc:
            last = str(exc)
            if time.monotonic() >= deadline:
                break
            time.sleep(2)

    if len(packet) >= 189 and packet[0] == 0x47 and packet[188] == 0x47:
        print("OK:" + channel["uuid"])
    elif not packet:
        print("ERROR:relay served no tune within 60s (last: %s)" % last)
    else:
        print("BAD-ALIGNMENT:%r" % packet[:20])
except Exception as exc:
    print("ERROR:%s" % exc)
PY
      )

      local channel_uuid=""
      case "$result" in
          OK:*)
              channel_uuid="${result#OK:}"
              log_pass "TS bytes read through api's nginx -> relay container (bytes 0 and 188 are 0x47)"
              ;;
          *)
              log_fail "role_split channel seed/read failed: $result"
              ;;
      esac

      if [ -n "$channel_uuid" ]; then
          # Second assertion: stop the relay container. A new tune must fail —
          # nginx's uwsgi_pass to relay_py gets connection-refused, so it
          # answers 502 — while the api container stays up and keeps answering
          # its own DB-backed routes.
          #
          # timeout=70, not 10. A stopped container's IP simply vanishes from
          # the bridge; nginx normally gets EHOSTUNREACH within a few seconds
          # and answers 502, but on some network drivers it waits out
          # uwsgi_connect_timeout (60s default) and answers 504. A 10s client
          # timeout would turn that second, equally correct outcome into
          # `ERR:timed out` and a spurious log_fail. 70 lets nginx be the one
          # that decides, and both of its verdicts are accepted below.
          docker stop "$relay_name" >/dev/null
          sleep 2

          local after_stop_status
          after_stop_status=$(docker exec "$api_name" python3 -c "
import urllib.error, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:9191/proxy/ts/stream/${channel_uuid}', timeout=70)
    print('200')
except urllib.error.HTTPError as e:
    print(e.code)
except Exception as e:
    print('ERR:%s' % e)
" 2>/dev/null)
          case "$after_stop_status" in
              502|503|504)
                  log_pass "new tune fails ($after_stop_status) with the relay container stopped"
                  ;;
              *)
                  log_fail "expected 502/503/504 with the relay stopped, got: $after_stop_status"
                  ;;
          esac

          local api_alive_status
          api_alive_status=$(docker exec "$api_name" python3 -c "
import urllib.error, urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:9191/api/channels/channels/', timeout=10)
    print(r.status)
except urllib.error.HTTPError as e:
    # Any HTTP status (401 from IsAdmin included) proves Django is still
    # answering through this container's own nginx and uwsgi.
    print(e.code)
except Exception as e:
    print('ERR:%s' % e)
" 2>/dev/null)
          case "$api_alive_status" in
              ERR:*|'')
                  log_fail "api container stopped answering with the relay down: ${api_alive_status:-<no output>}"
                  ;;
              *)
                  log_pass "api container still answers /api/channels/channels/ (HTTP $api_alive_status) with the relay stopped"
                  ;;
          esac
      else
          log_info "skipping the relay-stopped assertions — no channel UUID from the seed step"
      fi

      dump_logs_on_fail "$api_name"
      dump_logs_on_fail "$relay_name"
      dump_logs_on_fail "$worker_name"
      cleanup_scenario
  }
  ```

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash -n docker/tests/test-puid-pgid.sh && echo "syntax OK"
  grep -c '^import json$' docker/tests/test-puid-pgid.sh
  grep -c '^PY$' docker/tests/test-puid-pgid.sh
  grep -nE '^[[:space:]]+(import json|import sys|import time|upstream_host = |base = |upstream_control = |def call)' docker/tests/test-puid-pgid.sh || echo "no top-level Python line is indented"
  ```
  Expected: `syntax OK`, then `1`, then `1`, then `no top-level Python line is indented`.

  The point of the check is the Python script's **top-level** lines and the terminator, not the
  whole body: `def call`'s body, the `try:` block and the retry loop are legitimately indented, so
  "nothing is indented" would be both false and useless. What must sit at column 0 is every
  statement Python reads at module level, plus the closing `PY` — indent any of those and the
  container raises `IndentationError` at run time, which `bash -n` cannot see because the heredoc is
  opaque to it.

- [ ] **Step 4: Register the scenario and run it**

  In the `SCENARIOS=(...)` array (lines 1597-1618), add `role_split` immediately after
  `modular_mode`:

  ```bash
  SCENARIOS=(
      fresh_default
      fresh_custom_puid
      upgrade_explicit_puid
      upgrade_default_puid
      restart_idempotent
      puid_change
      uid_collision_102
      puid_zero
      puid_non_numeric
      bind_mount
      bind_mount_upgrade
      bind_mount_default_puid
      modular_mode
      role_split
      custom_postgres_user
      custom_port
      tmpfs_volume
      pg_major_upgrade
      pg_upgrade_post_puid
      e2e_web_ui
      readonly_rootfs
  )
  ```

  Run (foreground, `</dev/null`, 600000 ms timeout — the first run builds
  `dispatcharr:puid-test` from this worktree and takes several minutes):
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash docker/tests/test-puid-pgid.sh role_split </dev/null
  ```
  Expected: five `✅` lines — the three `supervisorctl` role checks, the TS-byte read, the
  relay-stopped 502, and the api-still-alive check — and a final summary with `0` failures for this
  scenario. **This topology has never run before.** If it fails, report the actual output rather
  than guessing a fix; `dump_logs_on_fail` prints all three app containers' logs plus each
  supervisord log.

- [ ] **Step 5: Commit**

  ```bash
  git add docker/tests/test-puid-pgid.sh
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-11.txt`:
  ```
  test(docker): add test_role_split — api/relay/worker containers, PR 4

  Also gives test_modular_mode a DISPATCHARR_RELAY_HOST of 127.0.0.1: from
  this PR every modular role-api container seds a relay upstream into
  nginx, which resolves it once at config load, so that scenario's
  relay-less container would otherwise fail config load and take
  [program:nginx] to FATAL.

  Three app containers on one network sharing one /data volume (D11),
  seeded by one python3 script inside the api container (superuser, token,
  a fake-provider scenario, a stream, a channel), reading TS bytes through
  the api container's nginx to the relay container over the network. The
  relay starts before the api because nginx resolves the relay_py upstream
  once at config load. A second assertion stops the relay and checks a new
  tune fails 502/503/504 while the api container keeps answering its own
  routes. The only test in either bash suite exercising the cross-container
  relay hop -- scripts/e2e_up.sh is AIO-only, so no Playwright project can.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-11.txt
  ```

---
### Task 13: `CLAUDE.md` corrections and spec amendments S1–S5

**Files:**
- Modify: `CLAUDE.md` (line 59, the § Architecture opening paragraph; line 61, the worker-count
  bullet; line 65, the `uwsgi_buffering off` bullet; line 122, the "No `harakiri`" sentence)
- Add: `docs/superpowers/plans/2026-09-04-phase1-pr4-process-split.md` — this plan, currently
  untracked. Every Phase 1 PR so far has committed its own plan (#167, #169, #173); this one is
  staged here so PR 4 does the same.
- Modify: `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (the **D6** row at line
  428; § Architecture's location table, the `^~ /api/` block at lines 506-513; § PR 4's
  `relay-uwsgi` bullet at lines 1128-1137, whose hwaccel sentences are lines 1134-1137; its
  `docker/nginx.conf` bullet at lines 1138-1147; its `apps/channels/tasks.py` bullet at lines
  1148-1150; its `docker-compose.yml` bullet at lines 1151-1156)

**Interfaces:** none (documentation only).

Every `old_string` below was quoted from this worktree. **Re-quote any that Task 1 Step 2 reported
as changed before editing** — line numbers and wording both drift.

- [ ] **Step 1: `CLAUDE.md` § Architecture's opening paragraph (line 59)**

  Replace:
  ```
  `docker/uwsgi.ini` runs uWSGI (4 workers × `gevent = 400`, `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`) as one `supervisord` program among several (`docker/supervisord/` holds one conf per rung, `docker/supervisord.d/` one `[program:x]` per file): Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image.
  ```
  with:
  ```
  **Two uWSGI processes**, running the same Django app under the same urlconf and differing only in listener, worker count and concurrency: the **API** process (`docker/uwsgi.ini` / `uwsgi.modular.ini`, unix socket, 4 workers × `gevent = 400`, `harakiri = $(DISPATCHARR_API_HARAKIRI)` default 120s, `max-requests` 5000) serves everything except long-lived streams, and the **relay** process (`docker/uwsgi.relay.ini`, `socket = 0.0.0.0:5657`, `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)` default 1600, **no `harakiri`**) serves `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php` and the XC streaming roots — `docker/nginx.conf`'s location table is the authority on exactly which. Both carry `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`, and each is one `supervisord` program among several (`docker/supervisord/` holds one conf per rung, `docker/supervisord.d/` one `[program:x]` per file), alongside: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image.
  ```

  The rest of that paragraph — the `DISPATCHARR_ROLE` sentence, the `priority=` sentence and the
  deleted-entrypoints parenthetical, all written by PR 3 — is **not** touched and must survive this
  edit intact.

- [ ] **Step 2: The worker-count bullet (line 61)**

  The split makes this bullet's premise read as if it no longer holds. Replace:
  ```
  - Four worker processes ⇒ **no channel state may live in Python memory**.
  ```
  with:
  ```
  - Four API worker processes plus the relay's one ⇒ **no channel state may live in Python memory**. The relay running a single worker does not relax this: an API worker, a Celery task and the relay all read the same channel through Redis, and PR 8's bounded restart replaces the relay process itself.
  ```

- [ ] **Step 3: The `uwsgi_buffering off` bullet (line 65)**

  Replace:
  ```
  - nginx **`uwsgi_buffering off`** on `/proxy/` is load-bearing — a past bug used `proxy_buffering off` (wrong directive family for `uwsgi_pass`) and nginx spooled live TS to disk.
  ```
  with:
  ```
  - nginx **`uwsgi_buffering off`** on every relay-bound location (`/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/live/`, `/movie/`, `/series/`, `/timeshift/`, `/streaming/timeshift.php`, the XC three-segment regex, and the nested `^/api/channels/recordings/\d+/file/$` regex — the one long-lived response under `/api/`) is load-bearing — a past bug used `proxy_buffering off` (wrong directive family for `uwsgi_pass`) and nginx spooled live TS to disk. Pinned by `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`, which asserts the exact set of the nine top-level ones; the tenth is nested inside `^~ /api/`, and that spec's own `parseLocationBlocks` folds a nested block into its parent's body rather than giving it a target of its own.
  ```

- [ ] **Step 4: The "No `harakiri`" sentence (line 122)**

  Replace only the final sentence of the "Operationally:" paragraph:
  ```
  No `harakiri`, and it can't be enabled while the relay shares a process with the API.
  ```
  with:
  ```
  The API now runs `harakiri = $(DISPATCHARR_API_HARAKIRI)` (default 120s, `harakiri-verbose = true`) and `max-requests = 5000`, enabled once Phase 1 PR 4 gave the relay its own process (`docker/uwsgi.relay.ini`); the relay itself carries no `harakiri`, because serving long-lived responses is the reason that process exists. Both are blunt: harakiri and a max-requests recycle kill the whole gevent worker, and with it every other in-flight request on it.
  ```

- [ ] **Step 5: Apply the four spec amendments**

  **S3 — the D6 row (line 428).** Replace:
  ```
  | **D6** | **`get_dvr_stream_base_url()`'s AIO/dev/debug branch changes from `http://127.0.0.1:5656` to `http://127.0.0.1:{DISPATCHARR_PORT:-9191}`** (nginx); the modular and explicit-override branches are unchanged. | The DVR fetches `/proxy/ts/stream/<uuid>` exactly like a player. Once PR 5 puts that route behind the authorize hop, a recording that bypasses nginx bypasses authorization. `apps/channels/tests/test_dvr_port_resolution.py`'s four `5656` assertions change in the same PR. |
  ```
  with:
  ```
  | **D6** | **`get_dvr_stream_base_url()`'s AIO branch changes from `http://127.0.0.1:5656` to `http://127.0.0.1:{DISPATCHARR_PORT:-9191}`** (nginx). **`dev` becomes its own branch and keeps `http://127.0.0.1:5656`**; the modular and explicit-override branches are unchanged. | The DVR fetches `/proxy/ts/stream/<uuid>` exactly like a player. Once PR 5 puts that route behind the authorize hop, a recording that bypasses nginx bypasses authorization. `dev` is the exception because there is nothing to go through: `docker/supervisord/all-dev.conf`'s `[include]` names `vite.conf`, not `nginx.conf`, and `frontend/vite.config.js` proxies only `/api` and `/ws` — a DVR fetch on `DISPATCHARR_PORT` there would record vite's `index.html`. **PR 5 must design for this**: in `dev` (and `debug`, which sets `DISPATCHARR_ENV=dev` as well) a recording still bypasses the authorize hop. `apps/channels/tests/test_dvr_port_resolution.py` has **three** `5656` assertions, not four; two become `9191` and the `dev` one stays. |
  ```

  **S2 — the hwaccel sentences in the `relay-uwsgi` bullet (lines 1134-1137).** Replace:
  ```
  `docker/init/04-check-hwaccel.sh`
    runs in the `all` and `api` roles only (PR 3's one-shot gate); the `relay` role, which is what
    will actually spawn ffmpeg from PR 4 on, gets no hardware-acceleration report. Recorded here so
    the gap is a deliberate PR 4 decision rather than a rediscovery.
  ```
  with:
  ```
  `docker/init/04-check-hwaccel.sh`
    moves out of PR 3's `all`/`api` one-shot gate into its own
    `if [[ "$DISPATCHARR_ROLE" != "worker" ]]` block, run after the migrate/wait branch rather than
    inside it, so the `relay` role — which is what actually spawns ffmpeg from PR 4 on — gets the
    report too. **This reverses PR 3's note**, which recorded the gap as a deliberate PR 4
    decision; PR 4 is where that decision gets made, and it goes the other way. The script is pure diagnostics
    (`lspci`, `ffmpeg -hwaccels`, `vainfo` — every line an `echo`, nothing consumed downstream), so
    running it in one more role costs boot log and nothing else, and a relay container that cannot
    reach the GPU is exactly the container an operator needs told about.
  ```
  (Re-check the leading whitespace against the tree before editing — the bullet is a wrapped
  paragraph and the continuation lines are indented two spaces.)

  **S4 — the `apps/channels/tasks.py` bullet (lines 1148-1150).** Replace:
  ```
  - `apps/channels/tasks.py`: `get_dvr_stream_base_url()`'s AIO/dev/debug branch per D6.
    `apps/channels/tests/test_dvr_port_resolution.py`: the four `5656` assertions become `9191`, and
    a fifth test pins that `DISPATCHARR_PORT` is honoured in AIO.
  ```
  with:
  ```
  - `apps/channels/tasks.py`: `get_dvr_stream_base_url()`'s AIO branch per D6, with `dev` split out
    into its own branch that keeps `127.0.0.1:5656`.
    `apps/channels/tests/test_dvr_port_resolution.py` has **three** `5656` assertions, not four
    (`test_aio_default_uses_localhost_5656`, `test_aio_explicit_uses_localhost_5656`,
    `test_dev_mode_uses_localhost_5656`): the two AIO ones become `9191`, the `dev` one keeps `5656`
    under a docstring saying why, and a fourth test pins that `DISPATCHARR_PORT` is honoured in AIO.
  ```

  **S1 — the `docker-compose.yml` bullet (lines 1151-1156).** Replace:
  ```
  - `docker/docker-compose.yml`: new `relay` service — same image, `DISPATCHARR_ROLE=relay`,
    `DISPATCHARR_ENV=modular`, **`./data:/data`** (D11: without it the relay generates its own
    `SECRET_KEY` and every internal call 403s), `POSTGRES_HOST=db`, `REDIS_HOST=redis`, no published
    ports, `depends_on` db and redis `service_healthy`. `web` gains `DISPATCHARR_ROLE=api` and
    `DISPATCHARR_RELAY_HOST=relay`. `docker/docker-compose.yml:191`'s `5436:5432` publish is **not**
    touched (carried; see § Requirements).
  ```
  with:
  ```
  - `docker/docker-compose.yml`: new `relay` service — same image, `DISPATCHARR_ROLE=relay`,
    `DISPATCHARR_ENV=modular`, **`./data:/data`** (D11: without it the relay generates its own
    `SECRET_KEY` and every internal call 403s), `POSTGRES_HOST=db`, `REDIS_HOST=redis`, no published
    ports, `depends_on` db and redis `service_healthy`, and `stop_grace_period: 160s` — the value
    PR 3 set uniformly on every supervisord-backed service in this file, sized to the sum of a
    rung's `stopwaitsecs`, not tuned per-service. `web` gains `DISPATCHARR_RELAY_HOST=relay` (its
    `DISPATCHARR_ROLE=api` was already added by PR 3) **and `depends_on: relay: condition:
    service_started`**: nginx resolves `upstream relay_py { server relay:5657; }` **once, at config
    load**, so a `web` container that starts with no `relay` in DNS fails with "host not found in
    upstream" and `[program:nginx]` goes BACKOFF then FATAL — taking the whole API surface down, not
    just streaming. The corollary for operators: recreating the relay with a new IP needs
    `nginx -s reload` in the web container. `docker/docker-compose.yml:191`'s `5436:5432` publish is
    **not** touched (carried; see § Requirements).
  ```

  **S5 — the recordings-file route, in two places.**

  First, § Architecture's location table (lines 506-513). Replace:
  ```
      location ~ ^/api/epg/programs/(?<prog_id>\d+)/poster/           { proxy_cache … }
  }
  ```
  with:
  ```
      location ~ ^/api/epg/programs/(?<prog_id>\d+)/poster/           { proxy_cache … }
      location ~ ^/api/channels/recordings/\d+/file/$                  { relay }   # long-lived; see below
  }
  ```

  Second, § PR 4's `docker/nginx.conf` bullet (lines 1138-1147). Replace its opening sentence:
  ```
  - `docker/nginx.conf`: the full location table in § Architecture, minus the `auth_request` block
    and minus the `map`. PR 4 writes `upstream relay_py { server RELAY_UPSTREAM; }` and
    `uwsgi_pass relay_py;` directly — there is no `X-Relay-Name` header to key a `map` on until PR 5,
    and a one-branch `map` on a constant would be noise a reader has to disprove.
  ```
  with:
  ```
  - `docker/nginx.conf`: the full location table in § Architecture, minus the `auth_request` block
    and minus the `map`. PR 4 writes `upstream relay_py { server RELAY_UPSTREAM; }` and
    `uwsgi_pass relay_py;` directly — there is no `X-Relay-Name` header to key a `map` on until PR 5,
    and a one-branch `map` on a constant would be noise a reader has to disprove.
    **The table's `^~ /api/` block carries a fifth nested regex**,
    `location ~ ^/api/channels/recordings/\d+/file/$`, sending `GET
    /api/channels/recordings/<pk>/file/` to the relay with `uwsgi_buffering off` and the same
    read/send timeouts every other relay-bound location has. `RecordingViewSet.file`
    (`apps/channels/api_views.py`, routed by `apps/channels/api_urls.py`'s `DefaultRouter`,
    `trailing_slash=True`) returns a `StreamingHttpResponse` over the recorded MKV/MP4 with Range
    support and is played back by the DVR UI — hours, not seconds, and therefore the one response
    on the API that this PR's `harakiri = 120` would kill, taking its gevent worker's other ~400
    in-flight requests with it. Routing keeps the same urlconf, view and DRF authentication (D1)
    and changes nothing under `apps/channels/` (D10). Its sibling
    `recordings/<pk>/hls/<seg_path>` stays on the API: HLS segments are small files, not one long
    response.
  ```

- [ ] **Step 6: Confirm both documents landed**

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  grep -c "attach-daemon\|can't be enabled while the relay shares\|deliberate PR 4 decision" CLAUDE.md docs/superpowers/specs/2026-09-04-phase1-process-split-design.md
  grep -c "uwsgi.relay.ini" CLAUDE.md
  grep -c "condition: service_started\|host not found in upstream\|three .5656. assertions" docs/superpowers/specs/2026-09-04-phase1-process-split-design.md
  ```
  Expected: the first command prints `CLAUDE.md:0` and the spec `:0` — none of the three superseded
  phrasings survives in either file; the second prints `2` (the § Architecture paragraph and the
  harakiri sentence); the third prints at least `3`, one per amendment that introduces a new
  identifier.

- [ ] **Step 7: Commit**

  ```bash
  git add CLAUDE.md docs/superpowers/specs/2026-09-04-phase1-process-split-design.md docs/superpowers/plans/2026-09-04-phase1-pr4-process-split.md
  ```
  Write
  `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-12.txt`:
  ```
  docs: describe the two-process split, amend the spec, commit the plan

  CLAUDE.md: § Architecture's opening paragraph now names both uWSGI
  processes and what each serves; the worker-count bullet says the relay's
  single worker does not relax the no-state-in-memory rule; the
  uwsgi_buffering bullet lists every relay-bound location; harakiri is
  described as enabled on the API rather than absent.

  Spec: S1 the relay service also gets stop_grace_period 160s and web
  depends_on relay (nginx resolves the upstream once at config load);
  S2 the hwaccel check moves to role != worker, reversing PR 3's note; S3 D6's
  dev branch keeps 5656 because dev runs vite and no nginx, so a dev
  recording bypasses PR 5's authorize hop; S4 the test file has three
  5656 assertions, not four; S5 routes the one long-lived /api/ response,
  GET /api/channels/recordings/<pk>/file/, to the relay so the new API
  harakiri cannot kill a DVR playback.

  Adds this PR's implementation plan under docs/superpowers/plans/, as
  every Phase 1 PR before it did.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  ```bash
  git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr4-commit-msg-12.txt
  ```

---

### Task 14: Local verification — build, boot, prove the split end to end

**Files:** none (verification only; no code changes, no commit).

**Interfaces:** none.

Every step here runs a long `docker` command **in the foreground, with `</dev/null` and a Bash
timeout of 600000 ms**. Backgrounded, `scripts/e2e_up.sh`'s own output handling never returns.

**Never pass `--reset` or `--down` to `scripts/e2e_up.sh`.** Both call its `destroy()`, which
removes the shared Docker network and takes the shared `e2e-upstream` provider container with it
(issue #168) — breaking every other local Playwright run, not just this one.

- [ ] **Step 1: Build the image from this worktree**

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  docker build -f docker/Dockerfile --build-arg REPO_OWNER=d10scot -t dispatcharr-e2e-pr4:local . </dev/null
  ```
  Expected: build succeeds. If `base-image.yml` has not yet rebuilt
  `ghcr.io/d10scot/dispatcharr:base` with PR 1's `supervisor==4.3.0` dependency, this fails at
  `uv sync --locked` — report that as an infrastructure blocker on PR 1, not a PR 4 defect.

- [ ] **Step 2: Bring up a pr4-suffixed stack with `scripts/e2e_up.sh`**

  A bare `docker run` cannot serve this: the Playwright projects in Step 3 need the fake provider on
  the same Docker network and a seeded admin, both of which this script arranges. Every name is
  pr4-suffixed so nothing collides with the shared `dispatcharr-e2e` stack.

  The **provider container is deliberately not renamed**. `scripts/e2e_up.sh` starts it with no
  `UPSTREAM_INTERNAL_ORIGIN`, so the origin it hands Dispatcharr is the hard default
  `http://e2e-upstream:8080` — renaming the container would leave that name unresolvable. The
  script's `ensure_on_network` attaches the existing shared provider to the pr4 network instead,
  which is what makes reuse correct. The one hazard is that the script rebuilds the provider image
  every run and recreates the container if the image id moved; pass
  `DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1` when the image already exists so the shared provider is
  left completely alone.

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  docker image inspect dispatcharr-e2e-upstream:local >/dev/null 2>&1 \
    && export DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1
  DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr4 \
  DISPATCHARR_E2E_PORT=39191 \
  DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr4-data \
  DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr4-net \
  DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-pr4:local \
    ./scripts/e2e_up.sh </dev/null
  ```
  Expected: the script prints the provider as ready, then the app container as ready, and exits 0.
  If the provider image is absent the export above is skipped and the script builds it — that is
  the correct fallback, at the cost of recreating the shared provider container.

- [ ] **Step 3: Verify both uWSGI programs and the resolved nginx config**

  Run:
  ```bash
  for i in $(seq 1 60); do
    docker exec dispatcharr-e2e-pr4 supervisorctl -c /app/docker/supervisord/supervisorctl.conf status relay-uwsgi 2>/dev/null | grep -q RUNNING && break
    sleep 5
  done
  docker exec dispatcharr-e2e-pr4 supervisorctl -c /app/docker/supervisord/supervisorctl.conf status
  ```
  Expected: nine programs, with `api-uwsgi` and `relay-uwsgi` both `RUNNING` alongside `postgres`,
  `redis`, `daphne`, the three Celery programs and `nginx` — matching `all.conf`'s `EXPECTED` list
  from Task 4.

  Run:
  ```bash
  docker exec dispatcharr-e2e-pr4 nginx -T 2>/dev/null | grep -A6 "location \^~ /proxy/ts/stream/"
  docker exec dispatcharr-e2e-pr4 nginx -T 2>/dev/null | grep -A2 "upstream relay_py"
  ```
  Expected: the first shows `uwsgi_buffering off;` and `uwsgi_pass relay_py;` inside that block; the
  second shows `server 127.0.0.1:5657;` — the `RELAY_UPSTREAM` placeholder resolved by Task 6's
  `sed`, proving the AIO (non-modular) branch took loopback.

- [ ] **Step 4: Run the three Playwright specs this PR is answerable for**

  Playwright resolves its base URL from `E2E_BASE_URL` (`e2e/playwright.config.ts:5`), **not** from
  `DISPATCHARR_E2E_PORT`; `DISPATCHARR_E2E_CONTAINER` is what the greybox spec `docker exec`s into.
  Both are needed.

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4/e2e
  E2E_BASE_URL=http://localhost:39191 DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr4 \
    npx playwright test --project=streaming -g "liveness ceiling|SPA" </dev/null
  E2E_BASE_URL=http://localhost:39191 DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr4 \
    npx playwright test --project=streaming-greybox -g relay-bound </dev/null
  ```
  Expected: PASS on both. The first is PR 2's TTFB and SPA-three-segment specs, now genuinely
  crossing the process boundary — the first Done criterion. The second is Task 10's widened
  buffering pin, running for the first time against a config that actually has nine relay-bound
  locations.

  **Do not run `--project=lifecycle` here.** `instance.restart()` is `scripts/e2e_up.sh --stop`
  followed by a start, and `--stop` stops `$UPSTREAM_NAME` — which, since the provider is
  deliberately not renamed, is the **shared** `e2e-upstream` container. CI's `lifecycle-tests.yml`
  runs that project on an isolated runner, and that is the evidence for Task 11.

- [ ] **Step 5: Run `test_role_split` if Task 12 Step 4 has not already been run in this session**

  Run:
  ```bash
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr4
  bash docker/tests/test-puid-pgid.sh role_split </dev/null
  ```
  Expected: as Task 12 Step 4.

- [ ] **Step 6: Tear down this task's own resources only**

  Run:
  ```bash
  docker rm -f dispatcharr-e2e-pr4 >/dev/null 2>&1 || true
  docker volume rm dispatcharr-e2e-pr4-data >/dev/null 2>&1 || true
  docker network rm dispatcharr-e2e-pr4-net >/dev/null 2>&1 || true
  ```
  Do **not** touch `dispatcharr-e2e`, `dispatcharr-e2e-data`, `dispatcharr-e2e-net` or
  `e2e-upstream` — those belong to the shared stack — nor any `puid_test_*` container, which
  `test-puid-pgid.sh`'s own `cleanup_scenario` owns. Removing the pr4 network while the shared
  provider is still attached to it is safe: Docker detaches it, leaving the container running on
  its own network.

- [ ] **Step 7: Write the PR body**

  Assemble the PR description from the § PR description section below, filling in which steps
  passed and any deviation Task 12's new topology required. If a step could not run — Docker
  unavailable, base image not yet rebuilt with `supervisor` — **say so plainly: the work is then
  unverified, not verified.**

---

## PR description

The PR body must carry these, none of which is obvious from the diff:

- **`harakiri` on a gevent worker is blunt.** When it fires, uWSGI kills the whole worker process,
  and with it every one of that worker's ~400 in-flight greenlets — not only the request that ran
  long. `max-requests = 5000` recycling has exactly the same blast radius, and fires far more often.
  The API is now the only process where either can happen, and it no longer serves anything
  long-lived, which is what makes both acceptable; on the relay they would be a live-stream killer,
  which is why `docker/uwsgi.relay.ini` has neither.
- **That sentence is only true because of one extra route.** `GET
  /api/channels/recordings/<pk>/file/` (`RecordingViewSet.file`) streams a recorded MKV/MP4 with
  Range support and runs for hours, and it sits under `/api/`. This PR routes it to the relay
  through a nested regex location inside `^~ /api/` — same urlconf, same view, same DRF
  authentication, different process. Without that, enabling `harakiri` would kill every DVR playback
  at the two-minute mark and take ~400 unrelated in-flight requests with it each time. Recorded as
  spec amendment S5. Its sibling `recordings/<pk>/hls/<seg_path>` stays on the API: HLS segments are
  small files, not one long response.
- **nginx resolves `upstream relay_py { server relay:5657; }` once, at config load.** Three
  consequences for operators: `web` now `depends_on` `relay` (`condition: service_started`) so it
  cannot start into a "host not found in upstream" config-load failure; **recreating the relay
  container with a new IP needs `nginx -s reload` in the web container** — a `docker compose up -d
  relay` alone leaves nginx pointing at the old address; and **a modular `web` brought up without a
  relay at all needs `DISPATCHARR_RELAY_HOST` pointed at something resolvable** (`127.0.0.1` is the
  right answer — streaming then 502s while the API stays up), because otherwise nginx never loads
  and the whole API surface is down, not just streaming. `docker/tests/test-puid-pgid.sh`'s
  `test_modular_mode` is exactly that deployment, and this PR sets it there for the same reason.
- **`listen = 1024` on the relay is a request, not a guarantee.** The kernel silently clamps it to
  `net.core.somaxconn`, which is 4096 by default on kernels ≥ 5.4 and 128 on much older ones. On a
  host that has not raised it, a burst of simultaneous tunes is dropped at the accept queue rather
  than queued. It costs latency under burst, never correctness, so nothing in this PR guards it —
  raise `net.core.somaxconn` on the host if you see it.
- **`/proxy/relay/` is now routed to the relay process and reachable with no authentication**, and
  it 404s from Django until PR 7 mounts the control API behind it (D1: same urlconf both sides, so
  an unmatched path is an ordinary Django 404). PR 7 must not mount anything there without its own
  authentication — the nginx location provides none.
- **In `dev`, the DVR still bypasses nginx**, and therefore will bypass PR 5's authorize hop.
  `all-dev.conf` runs vite and no nginx, so `get_dvr_stream_base_url()` keeps `127.0.0.1:5656`
  there. Recorded in the spec as amendment S3 so PR 5 designs for it rather than discovering it.
- **Nothing under `apps/proxy/live_proxy/`, `apps/proxy/vod_proxy/` or `apps/timeshift/`'s streaming
  path changed** (D10). The evidence the split preserved relay behaviour is G4's existing
  `streaming` and `streaming-failover` projects passing unmodified against two processes.
- **Verification actually run**, step by step, with the real output — including whether
  `test_role_split` needed any fix beyond what the plan specifies. Its three-app-container topology
  had never run before this PR.

## Final report to the orchestrator

Report, in order:

1. The plan's path and the task count (14).
2. Which spec requirements had no mapped task — expected: none. Every bullet in § The eight pull
   requests › PR 4 maps to Tasks 2-12, and the hwaccel note PR 3 added to that section maps to
   Task 8.
3. Every place the tree contradicts the spec, quoting both — expected: exactly the four recorded as
   amendments S1-S5 above, all applied by Task 13 Step 5.
4. Any step that could not be run, and why. A step that did not run leaves its claim unverified,
   and must be reported as such rather than as a pass.
