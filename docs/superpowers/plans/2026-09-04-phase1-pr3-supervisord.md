# Phase 1 PR 3 — supervisord replaces the bash supervision loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `docker/entrypoint.sh`'s bash `pkill`-based `trap cleanup` process supervision with `supervisord`, in every `DISPATCHARR_ENV` and under a new `DISPATCHARR_ROLE` (`all`/`api`/`relay`/`worker`), with no relay program and no routing change.

**Architecture:** The entrypoint keeps its one-shot setup (PUID/PGID, TLS key fixup, Postgres/JWT/migration waits, `migrate`/`collectstatic`), now gated by `DISPATCHARR_ROLE`, then `exec`s `supervisord -n -c <selected conf>` instead of backgrounding uWSGI and polling PIDs in a bash loop. A two-input ladder (`DISPATCHARR_ENV=dev` → `all-dev.conf`, otherwise `${DISPATCHARR_ROLE}.conf`) picks one of five static `docker/supervisord/*.conf` rung files, each `[include]`-ing a subset of ten `docker/supervisord.d/*.conf` single-program files. `scripts/wait_for_redis.py` becomes wait-only (D15); nothing flushes Redis anywhere.

**Tech Stack:** supervisor 4.3.0 (added to the lockfile by PR 1, merged), bash, `setpriv` (util-linux), Django's test runner, Playwright lifecycle suite, `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh`.

**Spec:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` § The eight pull requests › PR 3

**Branch:** `migration/phase1-supervisord` (worktree `.worktrees/phase1-pr3`), off `main`.

## Global Constraints

- No relay program, no routing change — this PR is supervision only, verifiable against the unchanged single-process shape (spec § PR 3 opening line).
- `pyproject.toml`/`uv.lock` already carry `supervisor==4.3.0` (PR 1, #167) — do **not** re-add or re-lock; only merge `main` to pick it up.
- `DISPATCHARR_ROLE` ∈ {`all`, `api`, `relay`, `worker`}, orthogonal to `DISPATCHARR_ENV` ∈ {`aio`, `modular`, `dev`} (D3, as amended below). AIO defaults to `all`; **modular defaults to `api`**; `all` + `modular`, and `api`/`relay`/`worker` + non-`modular`, are rejected by the entrypoint.
- Nothing flushes Redis, in any role, ever (D15). `grep -rn "flushdb\|flushall\|_flush_non_celery_keys" scripts/ apps/ core/ dispatcharr/ docker/` must return nothing outside test files **and** `scripts/ci_coverage_backend.sh:26`, which is the backend coverage harness flushing its own throwaway Redis between labels and is explicitly out of D15's scope.
- `priority=` orders start and stop **signals**, not readiness — every program that needs a store waits for it in its own `command=` through `wait-for-stores.sh` (rule 3, as amended: the Celery programs too).
- **Shutdown is sequential, not concurrent.** `Supervisor.ordered_stop_groups_phase_1` stops **one** priority group per pass and only advances when that group is fully stopped, so the container's `stop_grace_period` must cover the **sum** of the per-program `stopwaitsecs`, not the maximum. Measured, not inferred — see § Spec amendments, A9.
- Every long-lived supervisord program carries `stdout_logfile=/dev/stdout`, `stdout_logfile_maxbytes=0`, `redirect_stderr=true`, and an explicit `command=` with no daemonizing flag. Privilege drop is `user=` where `nice` is not involved and `setpriv` inside `command=` where it is (see A4).
- Read-only-rootfs paths: every `logfile`/`pidfile`/`childlogdir`/`file` in the new conf files lives under `/run`.
- **No `docker/Dockerfile` change.** Line 35 is `COPY . /app`, and `.dockerignore` excludes neither directory, so `docker/supervisord/` and `docker/supervisord.d/` land at `/app/docker/supervisord*` on their own. Do not add a `COPY` for them.
- `stop_grace_period: 160s` goes on every compose service that runs supervisord: `docker-compose.aio.yml`'s one service, and `docker-compose.yml`'s `web` and `celery`. The `relay` service does not exist until PR 4 — not added here.
- `CELERY_NICE_LEVEL` stops being a relative offset (spec § PR 3) — supervisord parents every program at nice 0, so the value becomes absolute.
- `docker/entrypoint.celery.sh` and `docker/entrypoint.aio.sh` are deleted, not deprecated.
- Every `*.py` edit is checked by `scripts/check_credential_logging.py` (hook + `lint.yml`) — applies to `scripts/wait_for_redis.py`, `tests/test_wait_for_redis.py`, `core/tests/test_migrate_without_redis.py` and the new `docker/tests/validate-supervisord-conf.py`.
- `*tests/test_*.py` edits run the whole package via the hook (`tests/test_wait_for_redis.py` → the `tests` label; `core/tests/test_migrate_without_redis.py` → `core.tests`).
- `e2e/**/*.ts` edits are typecheck-blocking (`npx tsc --noEmit` for that package).
- No hook covers `docker/**/*.sh`, `docker/**/*.ini`, `docker/supervisord/**`, `docker/supervisord.d/**`, or `docker-compose*.yml` — verify those by hand per the Test environment block.
- `git add` and `git commit` in separate Bash calls; write commit messages with the Write tool and commit with `git commit -F <msgfile>`.
- No placeholders; every file shown here is shown in full.

## Done criteria (from the spec)

- [ ] `Lifecycle result` green in full mode — both bash suites run on this `migration/**` branch and every scenario still passes. Proved by the workflow run on the PR (`lifecycle-tests.yml`'s `suites` job, both matrix legs).
- [ ] `supervisorctl status` after boot shows every program of the role `RUNNING` and none `FATAL` or `BACKOFF`, in `test_fresh_default` and in `test_modular_mode`. Proved by the new assertion added in Task 9 and locally by Task 12 Step 6.
- [ ] `grep -rn "flushdb\|flushall\|_flush_non_celery_keys" scripts/ apps/ core/ dispatcharr/ docker/` returns nothing outside test files, **except** `scripts/ci_coverage_backend.sh:26` (`redis-cli … flushall`), the coverage harness's own throwaway Redis, which D15 does not cover. Proved by Task 12 Step 8.
- [ ] `E2E result` green in full mode — the AIO container still boots and serves the whole Playwright matrix. No relay or routing change, so this is a smoke check, not new coverage.
- [ ] `test_readonly_rootfs` reports the same outcome it does today (a `log_skip`); the read-only property is instead asserted statically: `grep -nE '^(logfile|pidfile|childlogdir|file)\s*=' docker/supervisord/*.conf` returns only paths under `/run`. Proved by Task 4 Step 3.
- [ ] Every rung conf parses under supervisor 4.3.0's own `ServerOptions.realize()`. Proved by `uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py` (Task 4 Step 2, re-run in Task 12 Step 9).
- [ ] `docker-build.yml` is **not** a criterion (push-to-`main`-only, never a PR check).
- [ ] `CLAUDE.md` corrected: § Architecture's `attach-daemon` paragraph and `entrypoint.aio.sh` "legacy" parenthetical; § Architecture § State's `wait_for_redis.py` flush sentence; § Commands' Docker bullet; § Known defects' `die-on-term` sentence.
- [ ] The spec's own § Decisions and § PR 3 carry the twelve amendments listed below, applied in this PR (Task 11).

## Test environment for this worktree

The edit/commit hooks resolve the project directory from the harness, so in a worktree they do not run tests automatically. Run them yourself:

1. Start a container for this worktree (idempotent):
   `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/start-test-container.sh`
2. After editing any file, run the affected-file hook by hand:
   `echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/run-affected-tests.sh`
   Exit 2 = blocking failure; read the output.
3. Before every commit, run the commit gate by hand:
   `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/pre-commit-tests.sh --git-hook`
4. Backend tests directly: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr3 /dispatcharrpy/bin/python manage.py test --keepdb <label> -v1`
5. Frontend: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/frontend && npm ci && npm test`. E2E typecheck: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/e2e && npm ci && npx tsc --noEmit`. A full Playwright project run needs the AIO image built from this worktree (`e2e/README.md`); use a distinct `DISPATCHARR_E2E_CONTAINER`/`_PORT`/`_VOLUME`/`_NETWORK` so the shared `dispatcharr-e2e` stack is untouched, and never pass `--reset`.
6. If the container cannot start, say so in the task report: the work is then unverified, not verified.

For bash/ini/conf/compose files (no hook coverage), verify by hand: `bash -n <file>` for every edited `.sh`; `uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py` after editing anything under `docker/supervisord/` or `docker/supervisord.d/`; `docker compose -f docker/docker-compose.yml config` / `-f docker/docker-compose.aio.yml config` after editing either; and the boot assertions in Task 12.

**`supervisord` has no config-test flag.** Its `-t` is `--strip_ansi`, not a dry run — do not write a verification step around `supervisord -t`. `docker/tests/validate-supervisord-conf.py` (Task 4) is the config test: it drives supervisor's own `ServerOptions.realize()`, which is exactly what a real boot does, minus spawning anything.

## File Structure

```
docker/entrypoint.sh                          MODIFY  role gate, drop bash pids[]/trap/monitor loop, exec supervisord
docker/init/03-init-dispatcharr.sh            MODIFY  role-gate the nginx-port sed + IPv6 strip block
docker/entrypoint.celery.sh                   DELETE  superseded by DISPATCHARR_ROLE=worker
docker/entrypoint.aio.sh                      DELETE  dead code (gunicorn/pm2, zero references)
docker/uwsgi.ini                              MODIFY  drop exec-pre + all five attach-daemon lines
docker/uwsgi.modular.ini                      MODIFY  drop the daphne attach-daemon line
docker/uwsgi.dev.ini                          MODIFY  drop exec-pre + all six attach-daemon lines
docker/uwsgi.debug.ini                        MODIFY  drop exec-before + attach-daemons + honour-stdin
docker/supervisord/all.conf                   NEW     AIO rung: postgres, redis, api-uwsgi, daphne, celery x3, nginx
docker/supervisord/all-dev.conf               NEW     dev+debug rung: postgres, redis-dev, api-uwsgi, daphne, celery x3, vite (no nginx)
docker/supervisord/api.conf                   NEW     modular web rung: api-uwsgi, daphne, nginx
docker/supervisord/worker.conf                NEW     modular worker rung: celery x3
docker/supervisord/relay.conf                 NEW     scaffold for PR 4: glob include matching zero files today
docker/supervisord/supervisorctl.conf         NEW     role-agnostic -c target for supervisorctl (serverurl only)
docker/supervisord.d/postgres.conf            NEW     [program:postgres], foreground, stopsignal=INT
docker/supervisord.d/redis.conf               NEW     [program:redis], non-persistent
docker/supervisord.d/redis-dev.conf           NEW     [program:redis-dev], non-persistent + protected-mode no
docker/supervisord.d/api-uwsgi.conf           NEW     [program:api-uwsgi], nice + setpriv + wait-for-stores.sh
docker/supervisord.d/daphne.conf              NEW     [program:daphne]
docker/supervisord.d/celery-default.conf      NEW     [program:celery-default], nice + setpriv + wait-for-stores.sh
docker/supervisord.d/celery-dvr.conf          NEW     [program:celery-dvr]
docker/supervisord.d/celery-beat.conf         NEW     [program:celery-beat]
docker/supervisord.d/nginx.conf               NEW     [program:nginx], daemon off, stays root
docker/supervisord.d/vite.conf                NEW     [program:vite], all-dev only
docker/supervisord.d/wait-for-stores.sh       NEW     (executable) pg_isready + wait_for_redis.py, then exec "$@"
docker/tests/validate-supervisord-conf.py     NEW     parses every rung with supervisor's own ServerOptions
scripts/wait_for_redis.py                     MODIFY  delete _flush_non_celery_keys + flushdb branch; wait-only
tests/test_wait_for_redis.py                  MODIFY  assert flush never happens; helper no longer exists
core/tests/test_migrate_without_redis.py      MODIFY  docstring: attach-daemon -> supervisord (comment only)
e2e/tests/lifecycle/durable-state.ts          MODIFY  comment: flushdb() -> non-persistent Redis (comment only)
docker/docker-compose.yml                     MODIFY  web: role=api + grace; celery: drop entrypoint, role=worker, grace
docker/docker-compose.aio.yml                 MODIFY  stop_grace_period: 160s
docker/tests/test-puid-pgid.sh                MODIFY  readiness -> supervisorctl; new status assertions; supervisord log dump
docker/tests/test-tls-postgres.sh             MODIFY  readiness -> supervisorctl; celery via DISPATCHARR_ROLE=worker
CLAUDE.md                                     MODIFY  four corrections named in Done criteria
docs/superpowers/specs/2026-09-04-phase1-process-split-design.md  MODIFY  the twelve amendments below
```

## Spec amendments made by this plan

House convention: a plan may not silently diverge from its spec. Each amendment below is applied to the spec file **in this PR** (Task 11, Step 6), quoting the sentence it replaces.

Every "currently N" is a line number in the spec **as it stands on `origin/main`** — that is, after Task 1 Step 2's merge, not in this worktree before it. PR 1 (#167) and PR 2 (#169) both amended the spec, taking it from 1415 lines to 1449, so a citation read against the pre-merge file is off by up to 34 lines below § Architecture. Re-confirm each by reading the file anyway; the tree wins.

| # | Spec location | What changes | Why |
|---|---|---|---|
| **A1** | D2 (currently 423), § PR 3's ladder table (currently 929-933), its rung-file bullet (currently 941-952), the entrypoint bullet's `all` line (currently 913-914), the program table's "Included by" column (currently 958-967), and § PR 4's `relay-uwsgi` bullet (currently 1065), which also lists `all-debug.conf` among the rungs that include it | **Five rung files, not six: `all`, `all-dev`, `api`, `relay`, `worker`. `all-debug.conf` does not exist.** The ladder becomes `DISPATCHARR_ENV = dev → all-dev.conf`, otherwise `${DISPATCHARR_ROLE}.conf`; `DISPATCHARR_DEBUG` selects only `uwsgi.debug.ini` and the empty `DISPATCHARR_UWSGI_EXTRA_ARGS`. The entrypoint sources `docker/init/99-init-dev.sh` when `DISPATCHARR_ENV = dev`. | The spec's "`all-debug` keeps nginx, matching today" is false. `docker-compose.debug.yml:16-17` sets `DISPATCHARR_ENV=dev` **and** `DISPATCHARR_DEBUG=true`, and `entrypoint.sh:300-313` keys the vite-instead-of-nginx branch on `DISPATCHARR_ENV = dev` alone — so today debug already runs vite and no nginx. A `DEBUG`-first ladder would have given debug nginx and no vite, i.e. a broken dev container. Consequence to accept: debug now shares `redis-dev` and therefore gets `--protected-mode no`, a relaxation confined to the dev/debug image. Second consequence: `99-init-dev.sh` (node install, `npm install`, `uv sync`, debugpy) is sourced nowhere in a supervisord entrypoint unless the entrypoint sources it, and without it vite crash-loops and `scripts/debug_wrapper` has no debugpy. |
| **A2** | D3 (currently 424) | **"AIO defaults to `all`; modular defaults to `api`; there is no modular `all`, and no non-modular `api`, `relay` or `worker`."** The entrypoint derives the default from `DISPATCHARR_ENV` and rejects all four impossible pairs with a named error. | Every existing modular deployment sets only `DISPATCHARR_ENV=modular`. Defaulting those to `all` would load `all.conf`, whose `[program:postgres]` starts against an uninitialised `/data/db` and lands in `FATAL`, plus a stray Redis and a duplicated Celery set. This replaces the previous revision's design decision 1 (adding `-e DISPATCHARR_ROLE=api` to `test_modular_mode`): the scenario now deliberately passes **no** role, so it exercises the default. |
| **A3** | § PR 3 boot rule 3 (currently 904-909) | **The three Celery programs also run through `wait-for-stores.sh`, with `startretries=20` and `startsecs=5`.** "Celery retries its broker itself and needs no wrapper" is true of Redis only. | `dispatcharr/settings.py` configures `django_celery_beat`'s `DatabaseScheduler`, which queries PostgreSQL inside `setup_schedule()` at startup; the workers load Django settings and hit the DB as well. Neither retries Postgres. Without the wrapper, every Celery program races the store and lands in `BACKOFF`/`FATAL` on a cold boot — the exact failure the Done criterion is written to catch. |
| **A4** | § PR 3, "Every program also carries `user=%(ENV_POSTGRES_USER)s`…" (currently 969-971) and the `api-uwsgi`/`celery-*` command cells (currently 961, 963-965) | **`user=` is replaced by `setpriv --reuid=… --regid=… --init-groups` inside `command=`, after `nice`, for `api-uwsgi` and the three Celery programs.** `user=` stays on `postgres`, `redis`, `redis-dev`, `daphne` and `vite`; `nginx` stays root. | `user=` makes supervisord `setuid()` **before** exec, which drops `CAP_SYS_NICE`, so `nice -n -5` then fails with "cannot set niceness: Permission denied". `docker-compose.aio.yml` and `docker-compose.yml` both document `UWSGI_NICE_LEVEL=-5` / negative `CELERY_NICE_LEVEL` with `cap_add: SYS_NICE`, and `check_no_permission_errors` in `test-puid-pgid.sh` greps for exactly that string. Running `nice` as root and dropping privileges afterwards with `setpriv` preserves the nice value, which is inherited across the credential change. This is what `entrypoint.sh:359` already does with `nice … su -`. |
| **A5** | § PR 3 (new bullet), replacing the previous revision's design decision 4 | **The entrypoint exports `DISPATCHARR_CELERY_USER` = `$POSTGRES_USER` for roles `all`/`api` and `root` for role `worker`, plus a matching `DISPATCHARR_CELERY_HOME`; the Celery programs `setpriv` to it.** Modular Celery therefore still runs as root. | AIO's Celery already ran as `$POSTGRES_USER` (inherited from uWSGI's `su -`), but `entrypoint.celery.sh` never used `su -`, so modular Celery ran as root and existing installs have root-owned files under `/data/recordings`, `/data/m3us`, `/data/epgs`, `/data/uploads` and `/data/plugins`. `03-init-dispatcharr.sh`'s chown is non-recursive, so silently switching the worker role to PUID would break DVR writes on upgrade. Behaviour-preserving now; dropping the worker to PUID needs a one-time recursive chown of `DATA_DIRS` and is recorded as a follow-up, not done here. |
| **A6** | § PR 3 program table, `postgres` row (currently 958) | **`command=%(ENV_PG_BINDIR)s/postgres -D %(ENV_POSTGRES_DIR)s -c port=%(ENV_POSTGRES_PORT)s`.** | PGDG installs the server binary only under `/usr/lib/postgresql/17/bin` (`docker/DispatcharrBase:167`), which is not on `PATH`; every existing call site uses `$PG_BINDIR` (`entrypoint.sh:256`, `02-postgres.sh`). A bare `postgres` would not resolve and the program would go `FATAL`. |
| **A7** | § PR 3 boot rule 1 (currently 889-894) and the `all` one-shot bullet (currently 913-914) | **Spell the stop out as `su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} stop -m fast -w"`, run after `collectstatic` and the hwaccel check, immediately before the ladder — in the `all` role only.** | The rule was stated in the spec's prose but had no place in the entrypoint. Without it, `[program:postgres]` starts a second postmaster against a data directory whose `postmaster.pid` belongs to the entrypoint's instance, fails, retries and lands in `FATAL`, leaving AIO running on an orphaned, unsupervised postmaster. `-w` so the entrypoint does not race supervisord. |
| **A8** | D15 (currently 436) and § PR 3's Done grep (currently 1027-1029) | **Carve out `scripts/ci_coverage_backend.sh:26` explicitly.** | That line is `redis-cli … flushall` against the coverage harness's own throwaway Redis, between backend test labels — the same thing `.claude/hooks/*.sh` do. It is not a deployment flush and the criterion as written would fail on it forever. |
| **A9** | § PR 3's `priority=` paragraph (currently 972-978), the `stop_grace_period` bullet (currently 1009-1013), the `postgres` row's "well inside the 45 s grace period" (currently 958), and § Requirements' drain row (currently 1321) | **Shutdown is sequential per priority group, not concurrent, and `stop_grace_period` becomes `160s`.** | Measured against supervisor 4.3.0, not inferred: three programs at priorities 100/200/900, each ignoring `TERM`, each `stopwaitsecs=3`, take **9.4 s** to shut down, not 3 s — `Supervisor.ordered_stop_groups_phase_1` (`supervisord.py:156-159`) stops only `stop_groups[-1]`, and `ordered_stop_groups_phase_2` (`:161-172`) pushes that group back on the queue until every process in it is stopped. Each `[program:x]` is its own group, so the budget is the **sum**: 10 (nginx) + 10 (beat) + 30 (dvr) + 30 (default) + 10 (daphne) + 10 (api-uwsgi) + 5 (redis) + 30 (postgres) = **135 s**, and **155 s** once PR 4 adds `relay-uwsgi` at 20 s. `160s` is the smallest round value that covers the arithmetic ceiling including PR 4, which is what lets PR 3 set it once and PR 4 stay code-only. The realistic worst case is far smaller — roughly 90 s, because only the two Celery workers actually consume their window, on warm shutdown with a task in flight, while nginx, daphne, uWSGI, Redis and PostgreSQL each exit in about a second — but 90 s is still twice the 45 s the spec assumed, so 45 s was already too small for the spec's own per-program budgets. Past 160 s Docker `SIGKILL`s, which is no worse than today's 8-second bash ceiling. |
| **A10** | § PR 3 program table, `celery-*` rows (currently 963-965) | **Each Celery command keeps `-l %(ENV_CELERY_LOG_LEVEL)s`, with the entrypoint defaulting it to `info` for role `worker` and `warning` for roles `all`/`api`.** | `entrypoint.celery.sh:62,72,74` passed `-l info`; `uwsgi.ini:13-16`'s `attach-daemon` lines passed no `-l` at all, and celery 5.6.3 (the pinned version — `uv.lock:132-133`) defaults `--loglevel` to `WARNING` for both `worker` and `beat`, verified against the installed package. A single shared program file cannot preserve two different historic defaults without an env var. The per-role default is what makes this PR behaviour-preserving rather than a silent verbosity change on either deployment shape. |
| **A11** | § PR 4 (currently 1061-1067) | **One-line note: `docker/init/04-check-hwaccel.sh` runs in the `all` and `api` roles only; the `relay` role, which is what will actually spawn ffmpeg, gets no hardware-acceleration report.** | PR 3 gates the hwaccel check with the rest of the `all`/`api` one-shot. From PR 4 the byte path lives in the `relay` container, so the diagnostic that tells an operator whether VAAPI/QSV is usable would be printed by a container that never transcodes. Recorded so PR 4 decides deliberately rather than discovering it. |
| **A12** | § PR 3 rung-file bullet (currently 941-952) and readiness bullet (currently 988-997) | **A sixth file, `docker/supervisord/supervisorctl.conf`, carrying only `[supervisorctl] serverurl=unix:///run/supervisor.sock`, is the `-c` target for every `supervisorctl` invocation.** | The readiness contract is `docker exec <name> supervisorctl -c <conf> status api-uwsgi`. Passing a rung file works — supervisor's `ClientOptions` reads only the `[supervisorctl]` section, verified — but forces the caller to know the container's role, which is exactly what `test_modular_mode` must not assume now that its role is defaulted (A2). A serverurl-only file makes every call role-agnostic and self-explaining. It carries no `logfile`/`pidfile`/`childlogdir`, so it does not affect the read-only-rootfs grep. |

Two things verified against supervisor 4.3.0 that the spec states correctly and this plan relies on, recorded so a reviewer need not re-derive them:

- `[include] files` with a glob matching zero files produces a parse **warning** and continues (`options.py:588-601`) — `relay.conf`'s `relay-*.conf` scaffold is legal today and needs no edit when PR 4 adds `relay-uwsgi.conf`.
- An unset `%(ENV_X)s` is a **hard** config error, not an empty expansion (`options.py:2200-2214`) — so `DISPATCHARR_UWSGI_INI`, `DISPATCHARR_UWSGI_EXTRA_ARGS`, `DISPATCHARR_HOME`, `DISPATCHARR_CELERY_USER`, `DISPATCHARR_CELERY_HOME`, `CELERY_LOG_LEVEL`, `PG_BINDIR`, `UWSGI_NICE_LEVEL` and `CELERY_NICE_LEVEL` are exported unconditionally by the entrypoint, in every role, even where the rung does not reference them.

Two more, which change how a step must be written:

- `supervisord` has **no** config-test flag (`-t` is `--strip_ansi`). Hence `docker/tests/validate-supervisord-conf.py`.
- `user=` is resolved against the container's `passwd` database **at config-parse time**, so `01-user-setup.sh` must run before `exec supervisord` — it does, and this plan does not move it after.

## Task 1: Gate — verify PR 1 landed and the base image has supervisord

**Files:** none (verification only).

**Interfaces:** Consumes nothing. Produces the base-image digest recorded in the PR body.

**All three gate facts were confirmed before this plan was written.** The steps below re-check them rather than discover them, so a failure is a signal that something changed, not the expected first outcome:

| Fact | Confirmed value |
|---|---|
| PR 1 (#167) merge commit | `936c742e` |
| `base-image.yml` run that rebuilt `:base` on `main` | `33919668165`, success |
| `:base` digest carrying supervisord | `sha256:427a2e86677863b85dff80eb5c5eadf6c6a00bc9fbd3824ad0b9d781e584b37d` |

- [ ] **Step 1: Confirm PR 1 (#167) is merged to `main`.**
  Run: `gh pr view 167 --repo D10Scot/Dispatcharr --json state,mergedAt,mergeCommit`
  Expected: `"state": "MERGED"`, a non-null `mergedAt`, and a merge commit of `936c742e…`. If not merged, **stop** — every later task depends on `supervisor==4.3.0` already being in `uv.lock` and in the `:base` image.
- [ ] **Step 2: Merge `main` into this worktree's branch.**
  Run (from `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3`): `git fetch origin main && git merge origin/main`
  Expected: fast-forward or clean merge; `git log -1 --oneline` shows a commit at or after `936c742e`. Resolve any conflict before continuing; none is expected, because nothing this plan edits was touched by either merged PR except the spec and `CLAUDE.md`, and this branch has not edited those yet.
  Four things arrive with the merge that later tasks depend on:
  - `pyproject.toml` and `uv.lock` gain `supervisor==4.3.0` (Task 1 Step 4 needs it importable on the host).
  - `docker/tests/test-puid-pgid.sh:1495` and `test-tls-postgres.sh:982` now pass `--build-arg REPO_OWNER=d10scot` in their own build path — a local-only fix, since CI always passes `--skip-build`, and Task 12 Step 8 does too. Nothing to do; noted so the diff is not a surprise.
  - `scripts/e2e_up.sh` builds with `--build-arg REPO_OWNER="$REPO_OWNER"`, from `DISPATCHARR_E2E_REPO_OWNER` defaulting to `d10scot`. This plan never invokes that script, so nothing here changes.
  - The spec grows from 1415 to 1449 lines (#167 and #169 both amended it), which is why every "currently N" in § Spec amendments is a post-merge number.
- [ ] **Step 3: Confirm `pyproject.toml`/`uv.lock` carry the dependency.**
  Run: `grep -n "supervisor" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/pyproject.toml /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/uv.lock | head -5`
  Expected: `pyproject.toml` shows `"supervisor==4.3.0"` in `[project].dependencies`; `uv.lock` has a `[[package]]` block named `supervisor`.
- [ ] **Step 4: Confirm `supervisor` is importable on the host, for Task 4's validator.**
  Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 && uv run --no-project --with supervisor==4.3.0 python -c "import supervisor.options as o; print(o.VERSION)"`
  Expected: prints `4.3.0`.
  Two things about that invocation are deliberate. **`--no-project`**, because `uv sync` against this project cannot succeed on a macOS host: `uv.lock` pins `torch==2.13.0+cpu` from `https://download.pytorch.org/whl/cpu`, which publishes no macOS wheel, so a plain `uv sync` fails on a platform this repo is never deployed to. `--with supervisor==4.3.0` gets the one package the validator needs, in a throwaway environment, at the version PR 1 pinned. **`supervisor.options.VERSION`**, because the top-level `supervisor` package exposes no `version_txt` or `__version__` — `import supervisor; supervisor.version_txt` raises `AttributeError`. `supervisord -v` prints the same string if a shell check is preferred.
- [ ] **Step 5: Confirm `base-image.yml` has rebuilt `:base` on `main` with supervisord present.**
  Run: `gh run list --repo D10Scot/Dispatcharr --workflow base-image.yml --branch main --limit 3 --json databaseId,conclusion,headSha,createdAt`
  Expected: run `33919668165` (or a newer one) with `conclusion: "success"` and a `headSha` at or after `936c742e`. If the newest successful run predates PR 1's merge, the base image does not yet contain supervisord — **stop** and wait for `base-image.yml` to finish on `main`, then re-run this step.
- [ ] **Step 6: Confirm supervisord, setpriv and the postgres binary are present in the rebuilt base image.**
  Run: `docker pull ghcr.io/d10scot/dispatcharr:base && docker run --rm --entrypoint /bin/bash ghcr.io/d10scot/dispatcharr:base -c '/dispatcharrpy/bin/supervisord -v; which setpriv; ls /usr/lib/postgresql/*/bin/postgres'`
  Expected: `4.3.0`, then `/usr/bin/setpriv`, then `/usr/lib/postgresql/17/bin/postgres`, against digest `sha256:427a2e86…`. All three are load-bearing: supervisord for every rung, `setpriv` for A4's privilege drop, and the server binary's real path for A6.
  **`--entrypoint` is required, not stylistic.** `docker/DispatcharrBase` ends with `ENTRYPOINT ["/app/docker/entrypoint.sh"]`, but the base image carries no `/app` — the application tree is copied in by `docker/Dockerfile`, one layer later. A bare `docker run ghcr.io/d10scot/dispatcharr:base /dispatcharrpy/bin/supervisord -v` therefore appends its argument to a missing entrypoint script and fails with `stat /app/docker/entrypoint.sh: no such file or directory`, which reads like a missing binary and is not one.
  Record the digest and the three outputs in the PR description, per PR 1's own done criterion.

No commit for this task (no files changed).

## Task 2: `wait_for_redis.py` becomes wait-only (D15)

**Files:**
- Test: `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/tests/test_wait_for_redis.py` (Modify)
- Modify: `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/scripts/wait_for_redis.py`

**Interfaces:** `wait_for_redis(host, port, db, password, username, max_retries, retry_interval) -> bool` — signature unchanged; body no longer flushes. `_flush_non_celery_keys(client)` and `_CELERY_KEY_PREFIXES` are deleted entirely. `_build_ssl_kwargs()` is untouched.

- [ ] **Step 1: Write failing tests asserting no-flush behaviour.**
  Replace `tests/test_wait_for_redis.py` in full. The two flush-behaviour tests (`test_aio_mode_calls_flushdb`, `test_modular_mode_does_not_call_flushdb`, currently lines 28-58) become tests that flushing never happens in either mode, plus one that the selective-flush helper is gone. The four connection-behaviour tests are carried verbatim.

  ```python
  import sys
  import os
  import importlib
  from django.test import SimpleTestCase
  from unittest.mock import patch, MagicMock

  import redis as redis_module

  # Ensure the scripts directory is importable
  sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


  def _import_wait_for_redis_module():
      """Import (or reimport) scripts/wait_for_redis.py."""
      import wait_for_redis as module
      importlib.reload(module)
      return module


  def _import_wait_for_redis():
      """Import (or reimport) the wait_for_redis function from scripts/."""
      return _import_wait_for_redis_module().wait_for_redis


  class WaitForRedisTests(SimpleTestCase):
      """
      Tests for scripts/wait_for_redis.py.

      D15: nothing flushes Redis, in any role, ever. wait_for_redis() only
      waits for a successful ping — no flushdb, no selective key deletion,
      in either AIO or modular mode. AIO starts empty because supervisord's
      [program:redis] runs redis-server non-persistent, not because anything
      wipes it.
      """

      @patch('wait_for_redis.redis.Redis')
      def test_aio_mode_never_flushes(self, mock_redis_cls):
          """In AIO mode (default), flushdb must NOT be called."""
          mock_client = MagicMock()
          mock_client.ping.return_value = True
          mock_redis_cls.return_value = mock_client

          with patch.dict(os.environ, {}, clear=False):
              os.environ.pop('DISPATCHARR_ENV', None)
              wait_for_redis = _import_wait_for_redis()
              result = wait_for_redis(max_retries=1, retry_interval=0)

          self.assertTrue(result)
          mock_client.flushdb.assert_not_called()
          mock_client.delete.assert_not_called()

      @patch('wait_for_redis.redis.Redis')
      def test_modular_mode_never_flushes(self, mock_redis_cls):
          """In modular mode, flushdb must NOT be called either."""
          mock_client = MagicMock()
          mock_client.ping.return_value = True
          mock_redis_cls.return_value = mock_client

          with patch.dict(os.environ, {'DISPATCHARR_ENV': 'modular'}):
              wait_for_redis = _import_wait_for_redis()
              result = wait_for_redis(max_retries=1, retry_interval=0)

          self.assertTrue(result)
          mock_client.flushdb.assert_not_called()
          mock_client.scan.assert_not_called()
          mock_client.delete.assert_not_called()

      def test_selective_flush_helper_removed(self):
          """_flush_non_celery_keys is deleted, not moved (D15)."""
          module = _import_wait_for_redis_module()
          self.assertFalse(
              hasattr(module, '_flush_non_celery_keys'),
              "_flush_non_celery_keys must be deleted, not carried forward",
          )
          self.assertFalse(
              hasattr(module, '_CELERY_KEY_PREFIXES'),
              "_CELERY_KEY_PREFIXES must be deleted with its only caller",
          )

      @patch('wait_for_redis.redis.Redis')
      def test_retries_on_connection_error(self, mock_redis_cls):
          """Should retry on ConnectionError and eventually succeed."""
          mock_client = MagicMock()
          mock_client.ping.side_effect = [
              redis_module.exceptions.ConnectionError("refused"),
              redis_module.exceptions.ConnectionError("refused"),
              True,
          ]
          mock_redis_cls.return_value = mock_client

          wait_for_redis = _import_wait_for_redis()
          result = wait_for_redis(max_retries=5, retry_interval=0)

          self.assertTrue(result)
          self.assertEqual(mock_client.ping.call_count, 3)

      @patch('wait_for_redis.redis.Redis')
      def test_returns_false_after_max_retries(self, mock_redis_cls):
          """Should return False when max retries are exhausted."""
          mock_client = MagicMock()
          mock_client.ping.side_effect = redis_module.exceptions.ConnectionError("refused")
          mock_redis_cls.return_value = mock_client

          wait_for_redis = _import_wait_for_redis()
          result = wait_for_redis(max_retries=2, retry_interval=0)

          self.assertFalse(result)

      @patch('wait_for_redis.redis.Redis')
      def test_unexpected_error_returns_false(self, mock_redis_cls):
          """Generic exceptions should return False immediately."""
          mock_client = MagicMock()
          mock_client.ping.side_effect = RuntimeError("unexpected")
          mock_redis_cls.return_value = mock_client

          wait_for_redis = _import_wait_for_redis()
          result = wait_for_redis(max_retries=5, retry_interval=0)

          self.assertFalse(result)
  ```

  Run: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr3 /dispatcharrpy/bin/python manage.py test --keepdb tests -v1`
  Expected: **FAIL** — `test_aio_mode_never_flushes` fails because `wait_for_redis()` still calls `flushdb()`; `test_modular_mode_never_flushes` fails on `scan`/`delete`; `test_selective_flush_helper_removed` fails because the helper still exists.

- [ ] **Step 2: Delete the flush branch and the selective-flush helper.**
  In `scripts/wait_for_redis.py`, delete lines 15-34 (the `_CELERY_KEY_PREFIXES` constant, its two comment lines and the whole `_flush_non_celery_keys` function) and replace the flush block at lines 96-104 so the `try` body reads:

  ```python
          try:
              redis_client = redis.Redis(
                  host=host,
                  port=port,
                  db=db,
                  password=password if password else None,
                  username=username if username else None,
                  socket_timeout=2,
                  socket_connect_timeout=2,
                  **ssl_kwargs
              )
              redis_client.ping()
              logger.info(f"✅ Redis at {host}:{port}/{db} is now available!")
              return True
  ```

  and give the function the docstring that says why:

  ```python
  def wait_for_redis(host='localhost', port=6379, db=0, password='', username='', max_retries=30, retry_interval=2):
      """Wait for Redis to become available.

      Wait-only (D15). A restart of any role must never disturb a running
      relay's Redis state, so this never flushes — neither a full flushdb nor
      the old selective non-Celery-key deletion. AIO's Redis starts empty
      because supervisord's [program:redis] runs it non-persistent
      (--save "" --appendonly no), not because anything wipes it.
      """
  ```

  Nothing else in the file changes: `_build_ssl_kwargs()`, the retry/backoff arms and the `__main__` block are untouched.

  Run: same `manage.py test --keepdb tests -v1` command as Step 1.
  Expected: **PASS** — six tests green (`Ran 6 tests ... OK`).

- [ ] **Step 3: Run the affected-file hook (blocking: `*.py` credential check; `*tests/test_*.py` runs the whole `tests` package).**
  Run: `echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/scripts/wait_for_redis.py"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/run-affected-tests.sh`
  Expected: exit 0, credential-logging check passes.
  Run: `echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/tests/test_wait_for_redis.py"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/run-affected-tests.sh`
  Expected: exit 0, `tests` package passes.

- [ ] **Step 4: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/scripts/wait_for_redis.py /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/tests/test_wait_for_redis.py`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-2.txt` with the Write tool:
  ```
  fix(docker): make wait_for_redis.py wait-only (D15)

  Nothing flushes Redis in any role, ever. AIO's non-persistent
  redis-server (Task 3) is what makes AIO start empty without a flush
  step; a restart of the control plane must never disturb a running
  relay's state.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-2.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-2.txt`

## Task 3: `docker/supervisord.d/` — one program per file, plus the store wrapper

**Files:**
- Create: `docker/supervisord.d/{postgres,redis,redis-dev,api-uwsgi,daphne,celery-default,celery-dvr,celery-beat,nginx,vite}.conf`
- Create (executable): `docker/supervisord.d/wait-for-stores.sh`

(All paths relative to `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3`.)

**Interfaces:**
- Consumed by `docker/supervisord/*.conf`'s `[include] files =` lines (Task 4), by absolute `/app/docker/supervisord.d/<name>.conf` path.
- Every `%(ENV_X)s` below is exported unconditionally by `docker/entrypoint.sh` (Task 5): `PG_BINDIR`, `POSTGRES_DIR`, `POSTGRES_PORT`, `POSTGRES_USER`, `DISPATCHARR_HOME`, `DISPATCHARR_CELERY_USER`, `DISPATCHARR_CELERY_HOME`, `CELERY_LOG_LEVEL`, `UWSGI_NICE_LEVEL`, `CELERY_NICE_LEVEL`, `VIRTUAL_ENV`, `DISPATCHARR_UWSGI_INI`, `DISPATCHARR_UWSGI_EXTRA_ARGS`. An unset one is a hard config error, so none may be conditional.
- `wait-for-stores.sh` consumes `$PG_BINDIR`, `$POSTGRES_HOST`, `$POSTGRES_PORT` and runs `python3 /app/scripts/wait_for_redis.py` (Task 2), then `exec "$@"`.

No pre-existing test to fail first — these are new static config files under no hook glob. The failing-then-passing cycle for them is Task 4 Step 2's validator, which cannot run until a rung file includes them; Task 4 is therefore this task's test.

- [ ] **Step 1: Write the store programs.**

  `docker/supervisord.d/postgres.conf` (A6: the server binary is not on `PATH`):
  ```ini
  [program:postgres]
  command=%(ENV_PG_BINDIR)s/postgres -D %(ENV_POSTGRES_DIR)s -c port=%(ENV_POSTGRES_PORT)s
  user=%(ENV_POSTGRES_USER)s
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  priority=100
  autostart=true
  autorestart=true
  startsecs=5
  startretries=20
  stopsignal=INT
  stopwaitsecs=30
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  Foreground `postgres`, not `pg_ctl start`, which daemonises and would leave supervisord supervising the wrong process. `stopsignal=INT` is PostgreSQL's fast shutdown — clean, unlike the `-m immediate` the old entrypoint used because it had only 8 seconds. No `directory=`: supervisord would `chdir` there before exec, and a home directory that does not exist would turn a cosmetic detail into a spawn failure; `-D` is absolute.

  `docker/supervisord.d/redis.conf`:
  ```ini
  [program:redis]
  command=redis-server --save "" --appendonly no
  user=%(ENV_POSTGRES_USER)s
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  directory=/tmp
  priority=110
  autostart=true
  autorestart=true
  stopsignal=TERM
  stopwaitsecs=5
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  Non-persistent, which is what removes the boot flush (rule 2) — an empty `--save` and no AOF, so nothing is ever read back from disk. `directory=/tmp` because supervisord's own cwd is not guaranteed writable by `$POSTGRES_USER` and a future `redis-server` that decides to write anything should not fail on it. supervisord splits `command=` with `shlex`, so the empty `""` survives as a real empty argument.

  `docker/supervisord.d/redis-dev.conf`:
  ```ini
  [program:redis-dev]
  command=redis-server --save "" --appendonly no --protected-mode no
  user=%(ENV_POSTGRES_USER)s
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  directory=/tmp
  priority=110
  autostart=true
  autorestart=true
  stopsignal=TERM
  stopwaitsecs=5
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  One flag more than `redis`, in its own file so the single rung that lowers a security default says so by name. `uwsgi.dev.ini:11` already ran `redis-server --protected-mode no`, and dropping the flag would break dev tooling rather than merely harden it: `docker-compose.dev.yml:60` points `redis-commander` at `dispatcharr:6379` across the compose network, and protected mode refuses every non-loopback connection (the `DENIED` trap `CLAUDE.md` records). Under A1 the debug rung shares this program, so `docker-compose.debug.yml` now also runs Redis with protected mode off — a relaxation confined to the dev/debug image, called out in the PR body.

- [ ] **Step 2: Write the five store-dependent programs and their wrapper.**
  `api-uwsgi`, `daphne` and the three `celery-*` programs, plus `wait-for-stores.sh`. All five wait for PostgreSQL and Redis, four of them through the wrapper; `daphne` is the exception and the note under it says why.

  `docker/supervisord.d/api-uwsgi.conf` (A4: `nice` as root, then `setpriv`; A3's wrapper; `%(ENV_DISPATCHARR_UWSGI_INI)s` and `..._EXTRA_ARGS` come from the entrypoint's existing ladder):
  ```ini
  [program:api-uwsgi]
  command=nice -n %(ENV_UWSGI_NICE_LEVEL)s setpriv --reuid=%(ENV_POSTGRES_USER)s --regid=%(ENV_POSTGRES_USER)s --init-groups /app/docker/supervisord.d/wait-for-stores.sh %(ENV_VIRTUAL_ENV)s/bin/uwsgi --ini %(ENV_DISPATCHARR_UWSGI_INI)s %(ENV_DISPATCHARR_UWSGI_EXTRA_ARGS)s
  directory=/app
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  priority=200
  autostart=true
  autorestart=true
  startretries=20
  startsecs=5
  stopsignal=TERM
  stopwaitsecs=10
  killasgroup=true
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  No `user=`: supervisord's `user=` calls `setuid()` before exec, which drops `CAP_SYS_NICE`, and `nice -n -5` would then print "cannot set niceness: Permission denied" — a string `check_no_permission_errors` fails the puid suite on. `nice` runs as root, the nice value survives the credential change, and `setpriv` drops to `$POSTGRES_USER` with the supplementary groups `--init-groups` computes (the `video`/`render` membership `01-user-setup.sh` grants for GPU access). `killasgroup=true` because uWSGI's master forks four workers; supervisord always `setpgrp()`s the child, so the whole tree shares one process group.

  `docker/supervisord.d/daphne.conf`:
  ```ini
  [program:daphne]
  command=daphne -b 0.0.0.0 -p 8001 dispatcharr.asgi:application
  user=%(ENV_POSTGRES_USER)s
  directory=/app
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  priority=210
  autostart=true
  autorestart=true
  startretries=20
  startsecs=5
  stopsignal=TERM
  stopwaitsecs=10
  killasgroup=true
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  Keeps `user=`: no `nice` in front of it, so nothing needs `CAP_SYS_NICE`. Daphne holds no long-running task, so it needs no store wrapper — it retries its own connections and Channels reconnects to Redis.

  `docker/supervisord.d/celery-default.conf` (A3 wrapper, A4 `setpriv`, A5 identity, A10 log level):
  ```ini
  [program:celery-default]
  command=nice -n %(ENV_CELERY_NICE_LEVEL)s setpriv --reuid=%(ENV_DISPATCHARR_CELERY_USER)s --regid=%(ENV_DISPATCHARR_CELERY_USER)s --init-groups /app/docker/supervisord.d/wait-for-stores.sh celery -A dispatcharr worker -Q celery -n default@%%h --autoscale=6,1 -l %(ENV_CELERY_LOG_LEVEL)s
  directory=/app
  environment=HOME="%(ENV_DISPATCHARR_CELERY_HOME)s",USER="%(ENV_DISPATCHARR_CELERY_USER)s"
  priority=220
  autostart=true
  autorestart=true
  startretries=20
  startsecs=5
  stopsignal=TERM
  stopwaitsecs=30
  killasgroup=true
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  `%%h`, because `%` is supervisord's expansion character; it reaches Celery as `%h`. `stopwaitsecs=30` for a task in flight — warm shutdown, and the one program that genuinely consumes its window (see A9's arithmetic).

  `docker/supervisord.d/celery-dvr.conf`:
  ```ini
  [program:celery-dvr]
  command=nice -n %(ENV_CELERY_NICE_LEVEL)s setpriv --reuid=%(ENV_DISPATCHARR_CELERY_USER)s --regid=%(ENV_DISPATCHARR_CELERY_USER)s --init-groups /app/docker/supervisord.d/wait-for-stores.sh celery -A dispatcharr worker -Q dvr -n dvr@%%h --pool=threads --concurrency=20 -l %(ENV_CELERY_LOG_LEVEL)s
  directory=/app
  environment=HOME="%(ENV_DISPATCHARR_CELERY_HOME)s",USER="%(ENV_DISPATCHARR_CELERY_USER)s"
  priority=221
  autostart=true
  autorestart=true
  startretries=20
  startsecs=5
  stopsignal=TERM
  stopwaitsecs=30
  killasgroup=true
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```

  `docker/supervisord.d/celery-beat.conf`:
  ```ini
  [program:celery-beat]
  command=nice -n %(ENV_CELERY_NICE_LEVEL)s setpriv --reuid=%(ENV_DISPATCHARR_CELERY_USER)s --regid=%(ENV_DISPATCHARR_CELERY_USER)s --init-groups /app/docker/supervisord.d/wait-for-stores.sh celery -A dispatcharr beat -l %(ENV_CELERY_LOG_LEVEL)s
  directory=/app
  environment=HOME="%(ENV_DISPATCHARR_CELERY_HOME)s",USER="%(ENV_DISPATCHARR_CELERY_USER)s"
  priority=222
  autostart=true
  autorestart=true
  startretries=20
  startsecs=5
  stopsignal=TERM
  stopwaitsecs=10
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  Beat is the reason A3 exists: `django_celery_beat`'s `DatabaseScheduler` queries PostgreSQL inside `setup_schedule()` before it can tick, and nothing in Celery retries that. It forks nothing, so no `killasgroup`.

  `docker/supervisord.d/wait-for-stores.sh`:
  ```bash
  #!/bin/bash
  # Waits for PostgreSQL and Redis to be reachable, then execs the given
  # command — the real uwsgi invocation for api-uwsgi, the real celery
  # invocation for the three Celery programs, and from PR 4 relay-uwsgi.
  #
  # supervisord's priority= only orders the SIGNAL each program receives, at
  # both start and stop (Supervisor.runforever sorts the process groups by
  # priority; ordered_stop_groups_phase_1 walks them in reverse). It is not a
  # readiness barrier, so a program that needs a store to be reachable has to
  # wait for it here rather than rely on start order.
  #
  # Runs after setpriv, i.e. as the program's own unprivileged user, so it
  # must not need root: pg_isready and a Redis PING are all it does.
  set -euo pipefail

  until "$PG_BINDIR/pg_isready" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -q; do
      echo "wait-for-stores: waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
      sleep 1
  done

  # Wait-only after D15 — no flag needed, and nothing here may flush.
  # Exits 1 after REDIS_WAIT_RETRIES x REDIS_WAIT_INTERVAL (default 30 x 2s),
  # which under set -e fails the program and lets supervisord's
  # startretries=20 back off and try again.
  python3 /app/scripts/wait_for_redis.py

  exec "$@"
  ```
  `$POSTGRES_HOST` is `/var/run/postgresql` in AIO (a socket directory) and a hostname in modular; `pg_isready -h` accepts both. `python3` resolves to `/dispatcharrpy/bin/python3` because the image puts `$VIRTUAL_ENV/bin` first on `PATH` — the same invocation `entrypoint.sh:293` uses today.

- [ ] **Step 3: Write the two programs that are not stores or workers.**

  `docker/supervisord.d/nginx.conf`:
  ```ini
  [program:nginx]
  command=nginx -g 'daemon off;'
  priority=900
  autostart=true
  autorestart=true
  stopsignal=QUIT
  stopwaitsecs=10
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  No `user=`, deliberately: nginx's master stays root exactly as the bash-launched `nginx` did, and its own config already drops the *worker* processes to `$POSTGRES_USER` via the `user` directive `01-user-setup.sh:127` rewrites. Without `daemon off` nginx forks and exits and supervisord restarts it forever. Highest priority, so it starts last and is signalled first. `stopsignal=QUIT` is nginx's graceful shutdown.

  `docker/supervisord.d/vite.conf`:
  ```ini
  [program:vite]
  command=npm run dev
  directory=/app/frontend
  user=%(ENV_POSTGRES_USER)s
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  priority=910
  autostart=true
  autorestart=true
  stopsignal=TERM
  stopwaitsecs=10
  stopasgroup=true
  killasgroup=true
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```
  The only rung with vite is `all-dev`, and it is the only rung **without** nginx: `entrypoint.sh:300-313` starts vite instead of nginx whenever `DISPATCHARR_ENV = dev`, and vite serves 9191 itself. `stopasgroup` as well as `killasgroup` because `npm run dev` is a shell wrapper around the real vite process, and a bare `TERM` to npm leaves vite holding 9191. `HOME` matters here more than anywhere else — npm writes its cache there — which is why every non-root program carries it (`su -` set it for free; supervisord does not, and a child would otherwise inherit root's `HOME=/root`).

- [ ] **Step 4: Make the wrapper executable and syntax-check it.**
  Run: `chmod +x /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord.d/wait-for-stores.sh && bash -n /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord.d/wait-for-stores.sh && stat -f '%A %N' /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord.d/wait-for-stores.sh`
  Expected: no `bash -n` output, then a mode containing the executable bit (e.g. `755`). The bit is captured on `git add` in Step 5; `docker/Dockerfile` copies the tree as-is, so a non-executable wrapper would make every wrapped program fail to spawn.

- [ ] **Step 5: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord.d/`
  Then confirm the mode was recorded: `git ls-files -s /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord.d/wait-for-stores.sh`
  Expected: mode `100755`.
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-3.txt` with the Write tool:
  ```
  feat(docker): add per-program supervisord.d conf files

  One [program:x] per file, named by the rung conf files that include them
  (Task 4). api-uwsgi and the three Celery programs are wrapped by
  wait-for-stores.sh, because priority= orders start and stop signals but
  is not a readiness barrier, and they drop privileges with setpriv after
  nice rather than with user=, which would drop CAP_SYS_NICE and break a
  negative nice level.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-3.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-3.txt`

## Task 4: `docker/supervisord/` — the five rung files, the supervisorctl target, and the config test

**Files:**
- Create: `docker/supervisord/{all,all-dev,api,relay,worker}.conf`
- Create: `docker/supervisord/supervisorctl.conf`
- Create: `docker/tests/validate-supervisord-conf.py`

**Interfaces:** `SUPERVISORD_CONF` (Task 5) selects one rung by absolute path. Each rung `[include]`s a subset of Task 3's program files. `validate-supervisord-conf.py` takes an optional repo root (default: two directories above itself), exits 0 when every rung parses, 1 otherwise.

- [ ] **Step 1: Write the validator first — it fails now, because no rung file exists.**

  `docker/tests/validate-supervisord-conf.py`:
  ```python
  #!/usr/bin/env python
  """Parse every docker/supervisord/*.conf rung with supervisor's own parser.

  supervisord has no config-test flag (its -t is --strip_ansi), so this is
  the config test: it drives ServerOptions.realize(), which is exactly what
  a real boot does minus spawning anything. Catches a bad datatype, an
  unset %(ENV_x)s, an [include] that resolves to nothing it should have
  matched, and a priority or stopsignal that does not mean what was
  intended.

  Off-image, /app and /run do not exist, so the conf files are copied to a
  temporary tree with those two prefixes rewritten. The environment is a
  representative one, not the real one; POSTGRES_USER is the invoking user
  because supervisord resolves `user=` against the local passwd database at
  parse time.

  Usage: uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py [repo_root]
  """

  from __future__ import annotations

  import getpass
  import os
  import re
  import shutil
  import sys
  import tempfile

  from supervisor.options import ServerOptions

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

  FAKE_ENV = {
      "PG_BINDIR": "/usr/lib/postgresql/17/bin",
      "POSTGRES_DIR": "/data/db",
      "POSTGRES_PORT": "5432",
      "POSTGRES_USER": getpass.getuser(),
      "DISPATCHARR_HOME": os.path.expanduser("~"),
      "DISPATCHARR_CELERY_USER": getpass.getuser(),
      "DISPATCHARR_CELERY_HOME": os.path.expanduser("~"),
      "CELERY_LOG_LEVEL": "warning",
      # Negative on purpose: the point of setpriv-after-nice is that a
      # negative value is expressible at all.
      "UWSGI_NICE_LEVEL": "-5",
      "CELERY_NICE_LEVEL": "5",
      "VIRTUAL_ENV": "/dispatcharrpy",
      "DISPATCHARR_UWSGI_INI": "/app/docker/uwsgi.ini",
      "DISPATCHARR_UWSGI_EXTRA_ARGS": "--disable-logging",
  }

  RUNTIME_PATH_KEYS = r"logfile|pidfile|childlogdir|file|serverurl"


  def stage(repo_root: str) -> tuple[str, str]:
      """Copy the two conf directories to a temp tree, rewriting /app and /run."""
      tmp = tempfile.mkdtemp(prefix="supervisord-validate-")
      app = os.path.join(tmp, "app", "docker")
      run = os.path.join(tmp, "run")
      os.makedirs(app)
      os.makedirs(run)
      for name in ("supervisord", "supervisord.d"):
          shutil.copytree(os.path.join(repo_root, "docker", name),
                          os.path.join(app, name))
      for name in ("supervisord", "supervisord.d"):
          directory = os.path.join(app, name)
          for entry in sorted(os.listdir(directory)):
              if not entry.endswith(".conf"):
                  continue
              path = os.path.join(directory, entry)
              with open(path) as handle:
                  text = handle.read()
              text = text.replace("/app/docker/", app + "/")
              text = re.sub(
                  r"(?m)^(\s*(?:%s)\s*=\s*(?:unix://)?)/run" % RUNTIME_PATH_KEYS,
                  r"\1" + run,
                  text,
              )
              with open(path, "w") as handle:
                  handle.write(text)
      return app, run


  def main() -> int:
      repo_root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
          os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
      os.environ.update(FAKE_ENV)
      try:
          app, _run = stage(repo_root)
      except FileNotFoundError as exc:
          # Before the rung files exist this is the expected failing state,
          # and a traceback is a worse way to say so than a FAIL line.
          print("FAIL: %s missing (%s)" % (
              os.path.relpath(exc.filename or "docker/supervisord", repo_root),
              exc.strerror))
          return 1
      rung_dir = os.path.join(app, "supervisord")

      failures = 0
      seen = set()
      for rung in sorted(os.listdir(rung_dir)):
          if not rung.endswith(".conf") or rung == "supervisorctl.conf":
              continue
          seen.add(rung)
          options = ServerOptions()
          try:
              options.realize(["-c", os.path.join(rung_dir, rung)], doc=__doc__)
          except SystemExit as exc:
              print("FAIL %s: supervisor rejected the config (exit %s)" % (rung, exc))
              failures += 1
              continue
          names = [group.name for group in
                   sorted(options.process_group_configs, key=lambda g: g.priority)]
          expected = EXPECTED.get(rung)
          if expected is None:
              print("FAIL %s: unknown rung, add it to EXPECTED" % rung)
              failures += 1
              continue
          if names != expected:
              print("FAIL %s: programs %s, expected %s" % (rung, names, expected))
              failures += 1
              continue
          print("OK   %s: %s" % (rung, ", ".join(names) or "(no programs yet)"))
          for warning in options.parse_warnings:
              print("       warn: %s" % warning)

      missing = set(EXPECTED) - seen
      if missing:
          print("FAIL missing rung files: %s" % ", ".join(sorted(missing)))
          failures += 1

      print("%d rung(s) checked, %d failure(s)" % (len(seen), failures))
      return 1 if failures else 0


  if __name__ == "__main__":
      sys.exit(main())
  ```

  Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 && uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py; echo "exit=$?"`
  Expected: **FAIL** — a single line `FAIL: docker/supervisord missing (No such file or directory)` and `exit=1`, because Step 2 has not created that directory yet. A one-line failure rather than a traceback, so the red state of the cycle reads the same way the green one will. Do not paper over it by creating the directory first.

- [ ] **Step 2: Write the five rung files and the supervisorctl target.**

  Every rung repeats the same four control sections; only `[include] files` differs. Five files rather than one file with `%(ENV_…)s` in `[include]`: supervisor 4.3.0 *does* expand environment variables there (`options.py:578-588` merges `environ_expansions` into the dictionary `[include] files` is expanded against, though the reference documents only `here` and `host_node_name`), but no single environment variable names the rung — the selector is env × role, the same inputs the entrypoint already resolves in bash for the uWSGI ini. Doing it the same way twice is cheaper to read than encoding a ladder in a glob.

  `docker/supervisord/all.conf` — the AIO rung, `DISPATCHARR_ROLE=all` with `DISPATCHARR_ENV` of `aio`:
  ```ini
  [supervisord]
  nodaemon=true
  logfile=/run/supervisord.log
  logfile_maxbytes=1MB
  logfile_backups=1
  pidfile=/run/supervisord.pid
  childlogdir=/run

  [unix_http_server]
  file=/run/supervisor.sock

  [rpcinterface:supervisor]
  supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

  [supervisorctl]
  serverurl=unix:///run/supervisor.sock

  [include]
  files = /app/docker/supervisord.d/postgres.conf /app/docker/supervisord.d/redis.conf /app/docker/supervisord.d/api-uwsgi.conf /app/docker/supervisord.d/daphne.conf /app/docker/supervisord.d/celery-default.conf /app/docker/supervisord.d/celery-dvr.conf /app/docker/supervisord.d/celery-beat.conf /app/docker/supervisord.d/nginx.conf
  ```

  `docker/supervisord/all-dev.conf` — `DISPATCHARR_ENV=dev`, with or without `DISPATCHARR_DEBUG=true` (A1). `redis-dev` rather than `redis`; `vite` rather than `nginx`:
  ```ini
  [supervisord]
  nodaemon=true
  logfile=/run/supervisord.log
  logfile_maxbytes=1MB
  logfile_backups=1
  pidfile=/run/supervisord.pid
  childlogdir=/run

  [unix_http_server]
  file=/run/supervisor.sock

  [rpcinterface:supervisor]
  supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

  [supervisorctl]
  serverurl=unix:///run/supervisor.sock

  [include]
  files = /app/docker/supervisord.d/postgres.conf /app/docker/supervisord.d/redis-dev.conf /app/docker/supervisord.d/api-uwsgi.conf /app/docker/supervisord.d/daphne.conf /app/docker/supervisord.d/celery-default.conf /app/docker/supervisord.d/celery-dvr.conf /app/docker/supervisord.d/celery-beat.conf /app/docker/supervisord.d/vite.conf
  ```

  `docker/supervisord/api.conf` — the modular `web` container, and the default for any `DISPATCHARR_ENV=modular` container that names no role (A2). No local stores, no Celery:
  ```ini
  [supervisord]
  nodaemon=true
  logfile=/run/supervisord.log
  logfile_maxbytes=1MB
  logfile_backups=1
  pidfile=/run/supervisord.pid
  childlogdir=/run

  [unix_http_server]
  file=/run/supervisor.sock

  [rpcinterface:supervisor]
  supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

  [supervisorctl]
  serverurl=unix:///run/supervisor.sock

  [include]
  files = /app/docker/supervisord.d/api-uwsgi.conf /app/docker/supervisord.d/daphne.conf /app/docker/supervisord.d/nginx.conf
  ```

  `docker/supervisord/worker.conf` — the modular `celery` container, replacing `entrypoint.celery.sh` (Task 8):
  ```ini
  [supervisord]
  nodaemon=true
  logfile=/run/supervisord.log
  logfile_maxbytes=1MB
  logfile_backups=1
  pidfile=/run/supervisord.pid
  childlogdir=/run

  [unix_http_server]
  file=/run/supervisor.sock

  [rpcinterface:supervisor]
  supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

  [supervisorctl]
  serverurl=unix:///run/supervisor.sock

  [include]
  files = /app/docker/supervisord.d/celery-default.conf /app/docker/supervisord.d/celery-dvr.conf /app/docker/supervisord.d/celery-beat.conf
  ```

  `docker/supervisord/relay.conf` — a PR 4 scaffold. The glob matches zero files today, which supervisor reports as a parse warning and continues past (`options.py:588-601`); a literal filename that does not exist yet would be a hard error instead:
  ```ini
  [supervisord]
  nodaemon=true
  logfile=/run/supervisord.log
  logfile_maxbytes=1MB
  logfile_backups=1
  pidfile=/run/supervisord.pid
  childlogdir=/run

  [unix_http_server]
  file=/run/supervisor.sock

  [rpcinterface:supervisor]
  supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

  [supervisorctl]
  serverurl=unix:///run/supervisor.sock

  # No relay program exists until PR 4 adds
  # docker/supervisord.d/relay-uwsgi.conf, which this glob then picks up with
  # no edit here (D14: the relay role runs no nginx, so relay-uwsgi is and
  # stays the only program this rung includes).
  [include]
  files = /app/docker/supervisord.d/relay-*.conf
  ```

  `docker/supervisord/supervisorctl.conf` — the role-agnostic `-c` target (A12). Every rung defines the same `serverurl`, but a caller should not have to know the container's role to ask it a question, and after A2 `test_modular_mode` deliberately does not know it:
  ```ini
  # The -c target for every supervisorctl call, in the test suites and by
  # hand: `docker exec <container> supervisorctl -c
  # /app/docker/supervisord/supervisorctl.conf status`. supervisor's
  # ClientOptions reads only the [supervisorctl] section, so this needs
  # nothing else, and carrying nothing else is the point — it is correct
  # whatever role the container is running.
  [supervisorctl]
  serverurl=unix:///run/supervisor.sock
  ```

  Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 && uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py`
  Expected: **PASS** — five `OK` lines with exactly the program sets in `EXPECTED`, one `warn:` line under `relay.conf` naming the unmatched `relay-*.conf` glob, and `5 rung(s) checked, 0 failure(s)`.

- [ ] **Step 3: Verify the read-only-rootfs path invariant statically.**
  This is the substitute the spec accepts for `test_readonly_rootfs`, which can only ever `log_skip`.
  Run: `grep -nE '^(logfile|pidfile|childlogdir|file)\s*=' /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord/*.conf`
  Expected: fifteen matches (three per rung: `logfile`, `pidfile`, `file`) plus five `childlogdir` lines, every value starting `/run`. Nothing from `supervisorctl.conf`, which carries none of those keys.
  Run: `grep -nE '^(logfile|pidfile|childlogdir|file)\s*=' /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord/*.conf | grep -v '=/run' || echo CLEAN`
  Expected: `CLEAN`.

- [ ] **Step 4: Check the validator against the credential-logging linter.**
  Run: `echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/validate-supervisord-conf.py"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/run-affected-tests.sh`
  Expected: exit 0. The file prints paths but no URL, header or credential, so `scripts/check_credential_logging.py` has nothing to flag.

- [ ] **Step 5: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/supervisord/ /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/validate-supervisord-conf.py`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-4.txt` with the Write tool:
  ```
  feat(docker): add the five per-rung supervisord conf files

  Selected by DISPATCHARR_ENV=dev first, then DISPATCHARR_ROLE. There is no
  all-debug rung: docker-compose.debug.yml sets ENV=dev as well as
  DEBUG=true, and the pre-supervisord entrypoint already keyed its
  vite-instead-of-nginx branch on ENV=dev alone, so debug shares all-dev
  and DEBUG selects only the uwsgi ini. relay.conf is a PR 4 scaffold: its
  include glob matches zero files until relay-uwsgi.conf exists.
  supervisorctl.conf carries a serverurl and nothing else, so every
  supervisorctl call is role-agnostic.

  validate-supervisord-conf.py is the config test supervisord itself does
  not provide: its -t is --strip_ansi, not a dry run.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-4.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-4.txt`

## Task 5: Rewrite `docker/entrypoint.sh`

**Files:** Modify: `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.sh` (all 398 lines replaced)

**Interfaces:**
- Produces, exported for supervisord to expand: `DISPATCHARR_ROLE`, `DISPATCHARR_HOME`, `DISPATCHARR_CELERY_USER`, `DISPATCHARR_CELERY_HOME`, `CELERY_LOG_LEVEL`, `CELERY_NICE_LEVEL` (now absolute), `UWSGI_NICE_LEVEL`, `DISPATCHARR_UWSGI_INI`, `DISPATCHARR_UWSGI_EXTRA_ARGS`, plus the existing `PG_BINDIR`, `POSTGRES_*`, `REDIS_*`, `DJANGO_SECRET_KEY`, `VIRTUAL_ENV`.
- Consumes `docker/init/{01-user-setup,00-fix-pg-ssl-key,02-postgres,03-init-dispatcharr,04-check-hwaccel,99-init-dev}.sh`. Only `03` is edited (Task 6); `02` and `04` become role-gated at the call site; `99` is newly sourced.
- Terminal action: `exec supervisord -n -c "$SUPERVISORD_CONF"`.

Four ordering changes from today, each deliberate:
1. `01-user-setup.sh` moves **before** the `variables=()` block, so `DISPATCHARR_HOME` and `DISPATCHARR_CELERY_HOME` can be read from `getent passwd` and written into `/etc/environment`. Nothing between the two blocks reads either file, and `01` reads neither.
2. `04-check-hwaccel.sh` moves **before** `exec supervisord` (today it runs after uWSGI plus a `sleep 5`). It is pure diagnostics — `lspci`, `ffmpeg -hwaccels`, `vainfo` — with no dependency on a running service, so the `sleep 5` bought nothing.
3. `99-init-dev.sh` is sourced when `DISPATCHARR_ENV = dev`, as root, before `migrate`, because `uv sync` inside it can change the venv (A1).
4. The `all` role stops its own PostgreSQL with `pg_ctl … stop -m fast -w` immediately before the ladder (A7).

No automated test covers `entrypoint.sh` directly. `bash -n` and the greps below are the static gate; Task 12's real container boots are the functional one.

- [ ] **Step 1: Replace `docker/entrypoint.sh` in full.**

  ```bash
  #!/bin/bash

  set -e  # Exit immediately if a command exits with a non-zero status

  # Function to echo with timestamp
  echo_with_timestamp() {
      echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
  }

  # Set PostgreSQL environment variables
  export POSTGRES_DB=${POSTGRES_DB:-dispatcharr}
  export POSTGRES_USER=${POSTGRES_USER:-dispatch}
  # AIO mode: default to 'secret' for internal DB.
  # Modular mode + TLS: no default — cert-only auth (mTLS) uses no password.
  # Modular mode + no TLS: preserve 'secret' default for backward compatibility.
  if [[ "${DISPATCHARR_ENV:-}" == "modular" && "${POSTGRES_SSL:-}" == "true" ]]; then
      export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
  else
      export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-secret}"
  fi
  export DISPATCHARR_ENV=${DISPATCHARR_ENV:-aio}

  # DISPATCHARR_ROLE selects which supervisord programs this container runs.
  # It is orthogonal to DISPATCHARR_ENV, which answers where Postgres and
  # Redis run — but the impossible pairings are rejected rather than left to
  # fail later as a FATAL program or a five-minute wait loop:
  #   * role all runs its own Postgres and Redis, so it cannot be modular;
  #   * roles api, relay and worker have neither, so they cannot be anything
  #     else. A non-modular worker would sit in the migrate --check loop
  #     below until MIG_TIMEOUT against a database nothing was going to
  #     start.
  # Every deployment that predates this variable sets only DISPATCHARR_ENV,
  # so the default is derived from it: modular means api, anything else means
  # all. Without that derivation an existing modular web container would load
  # all.conf and its [program:postgres] would fail against an uninitialised
  # /data/db forever.
  if [ -z "${DISPATCHARR_ROLE:-}" ]; then
      if [ "$DISPATCHARR_ENV" = "modular" ]; then
          DISPATCHARR_ROLE=api
      else
          DISPATCHARR_ROLE=all
      fi
  fi
  export DISPATCHARR_ROLE
  case "$DISPATCHARR_ROLE" in
      all|api|relay|worker) ;;
      *)
          echo ""
          echo "================================================================"
          echo "ERROR: DISPATCHARR_ROLE must be one of: all, api, relay, worker."
          echo "  DISPATCHARR_ROLE=$DISPATCHARR_ROLE"
          echo "================================================================"
          echo ""
          exit 1
          ;;
  esac
  if [ "$DISPATCHARR_ROLE" = "all" ] && [ "$DISPATCHARR_ENV" = "modular" ]; then
      echo ""
      echo "================================================================"
      echo "ERROR: DISPATCHARR_ROLE=all runs its own PostgreSQL and Redis and"
      echo "  cannot be combined with DISPATCHARR_ENV=modular."
      echo "  Use DISPATCHARR_ROLE=api (the default in modular mode)."
      echo "================================================================"
      echo ""
      exit 1
  fi
  case "$DISPATCHARR_ROLE" in
      api|relay|worker)
          if [ "$DISPATCHARR_ENV" != "modular" ]; then
              echo ""
              echo "================================================================"
              echo "ERROR: DISPATCHARR_ROLE=$DISPATCHARR_ROLE expects external"
              echo "  PostgreSQL and Redis, and therefore DISPATCHARR_ENV=modular."
              echo "  DISPATCHARR_ENV=$DISPATCHARR_ENV"
              echo "  Use DISPATCHARR_ROLE=all for a self-contained container."
              echo "================================================================"
              echo ""
              exit 1
          fi
          ;;
  esac
  echo "🎛️  DISPATCHARR_ROLE=$DISPATCHARR_ROLE (DISPATCHARR_ENV=$DISPATCHARR_ENV)"

  if [[ "$DISPATCHARR_ENV" == "aio" ]]; then
      # Use Unix socket for loopback values (unset, localhost, 127.0.0.1)
      if [[ -z "$POSTGRES_HOST" || "$POSTGRES_HOST" == "localhost" || "$POSTGRES_HOST" == "127.0.0.1" ]]; then
          export POSTGRES_HOST=/var/run/postgresql
      fi
  else
      export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
  fi
  export POSTGRES_PORT=${POSTGRES_PORT:-5432}
  export PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
  export PG_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"
  export REDIS_HOST=${REDIS_HOST:-localhost}
  export REDIS_PORT=${REDIS_PORT:-6379}
  export REDIS_DB=${REDIS_DB:-0}
  export REDIS_PASSWORD=${REDIS_PASSWORD:-}
  export REDIS_USER=${REDIS_USER:-}
  export DISPATCHARR_PORT=${DISPATCHARR_PORT:-9191}
  export LIBVA_DRIVERS_PATH='/usr/local/lib/x86_64-linux-gnu/dri'
  export LD_LIBRARY_PATH='/usr/local/lib'
  export SECRET_FILE="/data/jwt"

  if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
      # Ensure Django secret key exists or generate a new one
      if [ ! -f "$SECRET_FILE" ]; then
        echo "Generating new Django secret key..."
        old_umask=$(umask)
        umask 077
        tmpfile="$(mktemp "${SECRET_FILE}.XXXXXX")" || { echo "mktemp failed"; exit 1; }
        python3 - <<'PY' >"$tmpfile" || { echo "secret generation failed"; rm -f "$tmpfile"; exit 1; }
  import secrets
  print(secrets.token_urlsafe(64))
  PY
        mv -f "$tmpfile" "$SECRET_FILE" || { echo "move failed"; rm -f "$tmpfile"; exit 1; }
        umask $old_umask
      fi
  else
      # relay and worker never generate the key: they mount the same /data
      # volume as the all/api container, and two roles racing to create
      # /data/jwt on first boot would leave one writer's key overwritten and
      # every internal HMAC comparison 403ing. Lifted from the deleted
      # docker/entrypoint.celery.sh:12-24.
      echo 'Waiting for Django secret key...'
      JWT_TIMEOUT=120
      JWT_WAITED=0
      while [ ! -f "$SECRET_FILE" ]; do
          if [ "$JWT_WAITED" -ge "$JWT_TIMEOUT" ]; then
              echo "❌ ERROR: Timed out waiting for ${SECRET_FILE} after ${JWT_TIMEOUT}s."
              echo "   Is the api/all container running? Does it have the /data volume mounted?"
              exit 1
          fi
          sleep 1
          JWT_WAITED=$((JWT_WAITED + 1))
      done
  fi
  export DJANGO_SECRET_KEY="$(tr -d '\r\n' < "$SECRET_FILE")"

  # Process priority configuration
  # UWSGI_NICE_LEVEL: Absolute nice value for uWSGI/streaming (default: 0 = normal priority)
  # CELERY_NICE_LEVEL: Absolute nice value for Celery/background tasks (default: 5 = low priority)
  # Both are absolute now. Before supervisord, Celery was an attach-daemon of
  # an already-niced uWSGI, so the entrypoint subtracted UWSGI_NICE_LEVEL to
  # reach the intended absolute value. Under supervisord every program is a
  # direct child of supervisord at nice 0, so the subtraction would land
  # Celery at the wrong priority at any non-zero UWSGI_NICE_LEVEL.
  # Negative values still need cap_add: SYS_NICE, which is why the programs
  # run `nice` as root and drop privileges afterwards with setpriv rather
  # than using supervisord's own user=.
  export UWSGI_NICE_LEVEL=${UWSGI_NICE_LEVEL:-0}
  export CELERY_NICE_LEVEL=${CELERY_NICE_LEVEL:-5}

  # Who Celery runs as, and how loudly — both per role, both preserving what
  # the deployment did before supervisord.
  #   * AIO's Celery was an attach-daemon of a uWSGI started under `su -`,
  #     so it ran as $POSTGRES_USER, and it carried no -l, so celery's own
  #     default of WARNING applied.
  #   * entrypoint.celery.sh never used `su -`, so modular Celery ran as
  #     root, and it passed -l info on all three commands.
  # Dropping the worker to $POSTGRES_USER needs a one-time recursive chown of
  # /data/recordings, /data/m3us, /data/epgs, /data/uploads and /data/plugins
  # — 03-init-dispatcharr.sh's chown is non-recursive — so it is a follow-up,
  # not this PR.
  if [ "$DISPATCHARR_ROLE" = "worker" ]; then
      export DISPATCHARR_CELERY_USER="${DISPATCHARR_CELERY_USER:-root}"
      export CELERY_LOG_LEVEL="${CELERY_LOG_LEVEL:-info}"
  else
      export DISPATCHARR_CELERY_USER="${DISPATCHARR_CELERY_USER:-$POSTGRES_USER}"
      export CELERY_LOG_LEVEL="${CELERY_LOG_LEVEL:-warning}"
  fi

  # Set LIBVA_DRIVER_NAME if user has specified it
  if [ -v LIBVA_DRIVER_NAME ]; then
      export LIBVA_DRIVER_NAME
  fi
  # Extract version information from version.py
  export DISPATCHARR_VERSION=$(python -c "import sys; sys.path.append('/app'); import version; print(version.__version__)")
  export DISPATCHARR_TIMESTAMP=$(python -c "import sys; sys.path.append('/app'); import version; print(version.__timestamp__ or '')")

  # Display version information with timestamp if available
  if [ -n "$DISPATCHARR_TIMESTAMP" ]; then
      echo "📦 Dispatcharr version: ${DISPATCHARR_VERSION} (build: ${DISPATCHARR_TIMESTAMP})"
  else
      echo "📦 Dispatcharr version: ${DISPATCHARR_VERSION}"
  fi
  export DISPATCHARR_LOG_LEVEL
  # Set log level with default if not provided
  DISPATCHARR_LOG_LEVEL=${DISPATCHARR_LOG_LEVEL:-INFO}
  # Convert to uppercase
  DISPATCHARR_LOG_LEVEL=${DISPATCHARR_LOG_LEVEL^^}


  echo "Environment DISPATCHARR_LOG_LEVEL set to: '${DISPATCHARR_LOG_LEVEL}'"

  # Select the uwsgi ini that [program:api-uwsgi] will load, and the extra
  # args that go with it. Unconditional, in every role: an unset %(ENV_x)s is
  # a hard supervisord config error, not an empty expansion, and it is
  # cheaper to always export these two than to reason about which rungs
  # include api-uwsgi. Same ladder, same order, as the pre-supervisord
  # entrypoint used at :332-353.
  if [ "$DISPATCHARR_ENV" = "dev" ] && [ "$DISPATCHARR_DEBUG" != "true" ]; then
      export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.dev.ini"
  elif [ "$DISPATCHARR_DEBUG" = "true" ]; then
      export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.debug.ini"
  elif [ "$DISPATCHARR_ENV" = "modular" ]; then
      export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.modular.ini"
  else
      export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.ini"
  fi
  # uWSGI's own per-request access log, independent of Django's logging.
  # Suppressed outside debug mode; debug.ini needs it to see request timing
  # while attached. api-uwsgi.conf is one file shared by every rung that runs
  # it, so the flag travels as an env var rather than being baked in.
  if [ "$DISPATCHARR_DEBUG" != "true" ]; then
      export DISPATCHARR_UWSGI_EXTRA_ARGS="--disable-logging"
  else
      export DISPATCHARR_UWSGI_EXTRA_ARGS=""
  fi

  # Translate Dispatcharr POSTGRES_SSL_* env vars into libpq-recognized PGSSL*
  # env vars. Called once before any external PostgreSQL connection; all child
  # processes (psql, pg_dump, pg_isready, createdb, dropdb) inherit these
  # automatically. No-op when POSTGRES_SSL is not "true".
  setup_pg_ssl_env() {
      if [ "${POSTGRES_SSL:-false}" != "true" ]; then
          return 0
      fi
      export PGSSLMODE="${POSTGRES_SSL_MODE:-verify-full}"
      if [ -n "${POSTGRES_SSL_CA_CERT:-}" ]; then export PGSSLROOTCERT="$POSTGRES_SSL_CA_CERT"; fi
      if [ -n "${POSTGRES_SSL_CERT:-}" ];    then export PGSSLCERT="$POSTGRES_SSL_CERT"; fi
      if [ -n "${POSTGRES_SSL_KEY:-}" ];     then export PGSSLKEY="$POSTGRES_SSL_KEY"; fi
  }

  # READ-ONLY - don't let users change these
  export POSTGRES_DIR=/data/db

  # Run init scripts. User setup runs before the environment files are
  # written, so DISPATCHARR_HOME can be read back from the passwd database
  # this script has just reconciled with PUID/PGID.
  echo "Starting user setup..."
  . /app/docker/init/01-user-setup.sh

  # supervisord gives a child no login shell, so nothing sets HOME and USER
  # the way `su -` did: without these, every non-root program would inherit
  # HOME=/root and fail or litter (npm's cache, Celery's, psql's history).
  # Read from getent rather than assumed, because 01-user-setup.sh may have
  # renamed a pre-existing account at this PUID rather than creating one.
  _dispatcharr_home=$(getent passwd "$POSTGRES_USER" | cut -d: -f6)
  export DISPATCHARR_HOME="${_dispatcharr_home:-/home/$POSTGRES_USER}"
  _dispatcharr_celery_home=$(getent passwd "$DISPATCHARR_CELERY_USER" | cut -d: -f6)
  export DISPATCHARR_CELERY_HOME="${_dispatcharr_celery_home:-$DISPATCHARR_HOME}"
  unset _dispatcharr_home _dispatcharr_celery_home

  # Global variables, stored so other users inherit them.
  # Rewritten every startup so that container restarts with changed env vars
  # pick up the new values (not stale ones from a previous run).
  # Define all variables to process
  variables=(
      PATH VIRTUAL_ENV DJANGO_SETTINGS_MODULE PYTHONUNBUFFERED PYTHONDONTWRITEBYTECODE
      POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT
      DISPATCHARR_ENV DISPATCHARR_ROLE DISPATCHARR_DEBUG DISPATCHARR_LOG_LEVEL DISPATCHARR_ENABLE_IP_LOOKUP
      REDIS_HOST REDIS_PORT REDIS_DB REDIS_PASSWORD REDIS_USER POSTGRES_DIR DISPATCHARR_PORT
      DISPATCHARR_VERSION DISPATCHARR_TIMESTAMP LIBVA_DRIVERS_PATH LIBVA_DRIVER_NAME LD_LIBRARY_PATH
      CELERY_NICE_LEVEL UWSGI_NICE_LEVEL DJANGO_SECRET_KEY
      PG_BINDIR DISPATCHARR_HOME DISPATCHARR_CELERY_USER DISPATCHARR_CELERY_HOME CELERY_LOG_LEVEL
      DISPATCHARR_UWSGI_INI DISPATCHARR_UWSGI_EXTRA_ARGS
  )

  # Optional variables, only propagate when set to avoid noisy warnings
  for _opt_var in POSTGRES_SSL POSTGRES_SSL_MODE POSTGRES_SSL_CA_CERT POSTGRES_SSL_CERT POSTGRES_SSL_KEY \
                  REDIS_SSL REDIS_SSL_VERIFY REDIS_SSL_CA_CERT REDIS_SSL_CERT REDIS_SSL_KEY \
                  DISPATCHARR_SETUP_ALLOWED_IP DISPATCHARR_TRUSTED_PROXIES; do
      if [ -n "${!_opt_var+x}" ]; then
          variables+=("$_opt_var")
      fi
  done

  # Truncate files before rewriting
  > /etc/profile.d/dispatcharr.sh

  # Process each variable for both profile.d and environment
  for var in "${variables[@]}"; do
      # Check if the variable is set in the environment
      if [ -n "${!var+x}" ]; then
          # Add to profile.d (quoted to handle special characters in values)
          echo "export ${var}='${!var}'" >> /etc/profile.d/dispatcharr.sh
          # Add/update in /etc/environment
          sed -i "/^${var}=/d" /etc/environment
          echo "${var}='${!var}'" >> /etc/environment
      else
          echo "Warning: Environment variable $var is not set"
      fi
  done

  chmod +x /etc/profile.d/dispatcharr.sh

  # Ensure root's .bashrc sources the profile.d scripts for interactive non-login shells
  if ! grep -q "profile.d/dispatcharr.sh" /root/.bashrc 2>/dev/null; then
      cat >> /root/.bashrc << 'EOF'

  # Source Dispatcharr environment variables
  if [ -f /etc/profile.d/dispatcharr.sh ]; then
      . /etc/profile.d/dispatcharr.sh
  fi
  EOF
  fi

  # Fix TLS client key permissions/ownership BEFORE any external PG connections.
  # Must run after 01-user-setup.sh (user exists for chown) and before
  # 02-postgres.sh / pg_isready (which make the first external PG connections).
  # The destination is per-role because api, relay and worker containers share
  # one /data volume from PR 4 on, and a single fixed path would have three
  # writers racing on it. The file is a per-boot scratch copy, never read
  # across boots, so renaming it costs nothing.
  FIXED_KEY_PATH="/data/.pg-client-${DISPATCHARR_ROLE}.key"
  . /app/docker/init/00-fix-pg-ssl-key.sh
  # Propagate the fixed path to login shells (su - strips env vars)
  if [ "${POSTGRES_SSL_KEY:-}" = "$FIXED_KEY_PATH" ]; then
      sed -i "/^POSTGRES_SSL_KEY=/d" /etc/environment
      echo "POSTGRES_SSL_KEY='$FIXED_KEY_PATH'" >> /etc/environment
      sed -i "s|export POSTGRES_SSL_KEY=.*|export POSTGRES_SSL_KEY='$FIXED_KEY_PATH'|" /etc/profile.d/dispatcharr.sh
  fi

  # Export libpq TLS env vars so all subsequent psql/pg_dump/pg_isready calls
  # (in 02-postgres.sh, modular-mode checks, etc.) use TLS automatically.
  setup_pg_ssl_env

  if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
      # Initialize PostgreSQL (script handles modular vs internal mode
      # internally, and defines promote_app_role, ensure_app_database,
      # ensure_utf8_encoding, check_external_postgres_version and
      # prepare_pg_socket_dir, all used below).
      echo "Setting up PostgreSQL..."
      . /app/docker/init/02-postgres.sh
  fi

  echo "Starting init process..."
  . /app/docker/init/03-init-dispatcharr.sh

  # --- NumPy version switching for legacy hardware ---
  # Outside the role gate: docker-compose.yml documents USE_LEGACY_NUMPY on
  # the celery service as well as the web one, and entrypoint.celery.sh ran
  # this same block. A worker on a pre-2009 CPU needs the swap as much as the
  # API does.
  if [ "$USE_LEGACY_NUMPY" = "true" ]; then
      # Check if NumPy was compiled with baseline support
      if "$VIRTUAL_ENV/bin/python" -c "import numpy; numpy.show_config()" 2>&1 | grep -qi "baseline" || [ $? -ne 0 ]; then
          echo_with_timestamp "🔧 Switching to legacy NumPy (no CPU baseline)..."
          uv pip install --python "$VIRTUAL_ENV/bin/python" --no-cache --force-reinstall --no-deps /opt/numpy-*.whl
          echo_with_timestamp "✅ Legacy NumPy installed"
      else
          echo_with_timestamp "✅ Legacy NumPy (no baseline) already installed, skipping reinstallation"
      fi
  fi

  if [[ "$DISPATCHARR_ROLE" == "all" ]]; then
      # Start PostgreSQL exactly as before. supervisord's [program:postgres]
      # takes it over after the one-shot work; see the fast stop below.
      echo "Starting Postgres..."
      prepare_pg_socket_dir
      su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 300 -o '-c port=${POSTGRES_PORT}'"
      # Wait for PostgreSQL to be ready
      until su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
          echo_with_timestamp "Waiting for PostgreSQL to be ready..."
          sleep 1
      done
      echo "✅ Postgres is ready"

      # Unconditional startup guarantees — run on every AIO startup.
      # Each is idempotent and handles all scenarios (fresh, upgrade, restart).
      promote_app_role
      ensure_app_database
  elif [[ "$DISPATCHARR_ROLE" == "api" ]]; then
      echo "🔗 Modular mode: Using external PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}"
      # Wait for external PostgreSQL to be ready using pg_isready (checks actual protocol readiness)
      echo_with_timestamp "Waiting for external PostgreSQL to be ready..."
      until $PG_BINDIR/pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -q >/dev/null 2>&1; do
          echo_with_timestamp "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
          sleep 1
      done
      echo "✅ External PostgreSQL is ready"

      # Check PostgreSQL version compatibility
      check_external_postgres_version || exit 1

      # Wait for external Redis so a misconfigured host fails here with a
      # clear message rather than inside a supervisord program's retry loop.
      # wait_for_redis.py is wait-only after D15 — it must not, and does not,
      # flush: a modular web restart cannot be allowed to wipe a running
      # relay's keys. [program:api-uwsgi] waits again through
      # wait-for-stores.sh, which is what actually gates the process.
      echo "🔗 Modular mode: Using external Redis at ${REDIS_HOST}:${REDIS_PORT}"
      echo_with_timestamp "Waiting for Redis to be ready..."
      python3 /app/scripts/wait_for_redis.py
      echo "✅ Redis is ready"
  fi

  if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
      # Ensure database encoding is UTF8 (handles both internal and external databases)
      ensure_utf8_encoding

      # Development container setup: node, npm install, uv sync, and debugpy
      # when DISPATCHARR_DEBUG=true. Runs as root, before migrate, because
      # `uv sync` inside it can change the venv the migration then runs from,
      # and because [program:vite] starts as soon as supervisord does — a
      # container without node would crash-loop it.
      if [[ "$DISPATCHARR_ENV" == "dev" ]]; then
          . /app/docker/init/99-init-dev.sh
      fi

      # Run Django commands as non-root user to prevent permission issues
      su - "$POSTGRES_USER" -c "cd /app && python manage.py migrate --noinput"
      su - "$POSTGRES_USER" -c "cd /app && python manage.py collectstatic --noinput"

      # Run hardware acceleration check. Pure diagnostics (lspci, ffmpeg
      # -hwaccels, vainfo), so it no longer waits behind a running uWSGI.
      echo "🔍 Running hardware acceleration check..."
      . /app/docker/init/04-check-hwaccel.sh
  elif [[ "$DISPATCHARR_ROLE" == "relay" || "$DISPATCHARR_ROLE" == "worker" ]]; then
      # Wait for migrations to complete. 'migrate --check' exits 0 only when
      # every migration is applied, and exits 1 on either an unapplied
      # migration or a connection error (safe either way). Lifted from the
      # deleted docker/entrypoint.celery.sh:43-58, including running as root
      # rather than through `su -`, so the worker role does exactly what its
      # own entrypoint did.
      MIG_TIMEOUT=300
      MIG_WAITED=0
      echo 'Waiting for migrations to complete...'
      until (cd /app && python manage.py migrate --check) >/dev/null 2>&1; do
          if [ "$MIG_WAITED" -ge "$MIG_TIMEOUT" ]; then
              echo "❌ ERROR: Timed out waiting for migrations after ${MIG_TIMEOUT}s."
              echo "   Check the api/all container logs for migration errors."
              exit 1
          fi
          echo_with_timestamp 'Migrations not ready yet, waiting...'
          sleep 2
          MIG_WAITED=$((MIG_WAITED + 2))
      done
      echo "✅ Migrations complete."
      if [ "$DISPATCHARR_ROLE" = "worker" ]; then
          # Wording preserved verbatim from entrypoint.celery.sh:61 —
          # docker/tests/test-tls-postgres.sh waits on this exact substring.
          echo 'Migrations complete, starting Celery...'
      fi
  fi

  if [[ "$DISPATCHARR_ROLE" == "all" ]]; then
      # Hand PostgreSQL over to supervisord. Without this stop,
      # [program:postgres] starts a second postmaster against a data
      # directory whose postmaster.pid belongs to this script's instance; it
      # fails, retries and lands in FATAL, leaving the container running on
      # an orphaned, unsupervised postmaster. -w so supervisord's own start
      # cannot race the shutdown. -m fast, not -m immediate: this script is
      # no longer racing an 8-second ceiling.
      echo "Handing PostgreSQL over to supervisord (fast stop)..."
      su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} stop -m fast -w"
      echo "✅ Postgres stopped; supervisord will start it as [program:postgres]"
  fi

  # Select the supervisord config. Two inputs, not three: DISPATCHARR_DEBUG
  # chooses only the uwsgi ini (above), because docker-compose.debug.yml sets
  # DISPATCHARR_ENV=dev as well as DISPATCHARR_DEBUG=true and the
  # pre-supervisord entrypoint keyed its vite-instead-of-nginx branch on
  # DISPATCHARR_ENV=dev alone. A debug rung with nginx and no vite would not
  # match what debug does today.
  if [ "$DISPATCHARR_ENV" = "dev" ]; then
      SUPERVISORD_CONF="/app/docker/supervisord/all-dev.conf"
  else
      SUPERVISORD_CONF="/app/docker/supervisord/${DISPATCHARR_ROLE}.conf"
  fi

  echo "🚀 Starting supervisord ($DISPATCHARR_ROLE) with $SUPERVISORD_CONF"
  exec supervisord -n -c "$SUPERVISORD_CONF"
  ```

  Note on the heredocs above: the `python3 - <<'PY'` body and the `cat >> /root/.bashrc << 'EOF'` body are shown at the indentation the file must contain — both are quoted heredocs with unindented terminators (`PY`, `EOF`) at column 0 in the real file, exactly as today. If the editor re-indents them the script breaks silently.

- [ ] **Step 2: Syntax-check and confirm the heredoc terminators survived.**
  Run: `bash -n /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.sh && grep -cn '^PY$\|^EOF$' /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.sh`
  Expected: no `bash -n` output, then `2`.

- [ ] **Step 3: Confirm the deleted process-tracking machinery is gone.**
  A regression here would silently reintroduce the bash `pkill` loop this PR exists to remove.
  Run: `grep -n "pids=\|pid_names\|trap cleanup\|while kill -0\|pkill\|uwsgi started with PID\|CELERY_NICE_ABSOLUTE" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.sh`
  Expected: no output. `CELERY_NICE_ABSOLUTE` is in the list because its disappearance is what makes `CELERY_NICE_LEVEL` absolute.

- [ ] **Step 4: Confirm every `%(ENV_x)s` a rung can reference is exported.**
  Run:
  ```
  cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3
  grep -ho '%(ENV_[A-Z_]*)s' docker/supervisord.d/*.conf | sort -u | sed 's/%(ENV_\(.*\))s/\1/' \
    | while read -r v; do
        grep -q "export $v=" docker/entrypoint.sh && continue
        grep -q "^ENV $v=" docker/Dockerfile docker/DispatcharrBase && continue
        echo "MISSING: $v"
      done
  ```
  Expected: no `MISSING:` lines. Thirteen names are checked; twelve come from `docker/entrypoint.sh` and `VIRTUAL_ENV` comes from the image itself (`docker/Dockerfile:30`, `docker/DispatcharrBase:11,119`), which is why the check accepts either source. An unset one is a hard supervisord config error at boot, in every role whose rung includes that program.

- [ ] **Step 5: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.sh`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-5.txt` with the Write tool:
  ```
  refactor(docker): entrypoint execs supervisord instead of tracking pids

  Adds DISPATCHARR_ROLE (all/api/relay/worker), defaulted from
  DISPATCHARR_ENV so every existing modular deployment becomes api rather
  than all, and role-gates the one-shot setup: JWT generation versus wait,
  local versus external Postgres, migrate/collectstatic, the hwaccel
  check. The all role hands its Postgres over with pg_ctl stop -m fast -w
  before exec, so supervisord's [program:postgres] is the only postmaster.
  CELERY_NICE_LEVEL becomes absolute; HOME, USER, the Celery identity and
  the Celery log level are exported per role so supervisord's children
  behave as their `su -` predecessors did. The bash pids array, trap
  cleanup and monitor loop are gone.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-5.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-5.txt`

## Task 6: Role-gate the nginx sed in `docker/init/03-init-dispatcharr.sh`

**Files:** Modify: `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/init/03-init-dispatcharr.sh` (lines 59-72)

**Interfaces:** Consumes `$DISPATCHARR_ROLE`, exported by `docker/entrypoint.sh` before this script is sourced (Task 5). No signature change — still sourced unconditionally from the same call site, because the spec is explicit that the gate lives **inside** the script, not around the call.

- [ ] **Step 1: Wrap the `NGINX_PORT` sed and the IPv6 strip in a role check.**
  Current lines 59-72, verified:
  ```bash
  # Configure nginx port
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
  ```
  Replace with:
  ```bash
  # Configure nginx port and IPv6 — only the roles that run nginx.
  # all and api are the two rungs that include [program:nginx]; all-dev runs
  # vite instead and is reached with DISPATCHARR_ROLE=all, so it passes this
  # gate and templates a config nothing loads, which is harmless and keeps
  # the condition about roles rather than about rungs. relay and worker have
  # no nginx and must not touch /etc/nginx/sites-enabled/default: under a
  # read-only rootfs, or simply on a container that never serves HTTP, that
  # is a write with no reader.
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
  Use the Edit tool with the exact current block as `old_string` (re-read the file first to confirm no drift) and the new block as `new_string`.

- [ ] **Step 2: Confirm nothing else in the file moved.**
  The `DATA_DIRS`/`APP_DIRS` creation, the `/app` ownership fix, the chown loops and the consolidated warning all stay unconditional — every role needs them, including `relay` and `worker`, which write recordings and read plugins.
  Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 && git diff --stat docker/init/03-init-dispatcharr.sh && git diff docker/init/03-init-dispatcharr.sh`
  Expected: one hunk; the only changes are the added `if`/`fi` and the re-indentation of the fourteen lines between them, plus the new comment.

- [ ] **Step 3: Syntax-check.**
  Run: `bash -n /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/init/03-init-dispatcharr.sh`
  Expected: exit 0, no output.

- [ ] **Step 4: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/init/03-init-dispatcharr.sh`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-6.txt` with the Write tool:
  ```
  fix(docker): role-gate the nginx port/IPv6 sed in 03-init-dispatcharr.sh

  relay and worker containers run no nginx, so they must not template
  /etc/nginx/sites-enabled/default. The gate lives inside the script
  because the entrypoint sources it unconditionally: directory creation
  and ownership in the same file stay unconditional, since every role
  needs them.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-6.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-6.txt`

## Task 7: Strip `exec-pre`/`attach-daemon` from the four uWSGI ini files

**Files:**
- Modify: `docker/uwsgi.ini` (lines 1-19), `docker/uwsgi.modular.ini` (lines 1-15), `docker/uwsgi.dev.ini` (lines 1-20), `docker/uwsgi.debug.ini` (lines 1-18 and line 72)

**Interfaces:** No signature change — the same `[uwsgi]` sections, minus the daemon-management directives supervisord now owns. Leaving any of them would start Redis, Celery and Daphne twice and re-run the (now removed) Redis wait on every uWSGI restart.

- [ ] **Step 1: `docker/uwsgi.ini` — delete the daemon block.**
  Replace lines 1-19 (`[uwsgi]` through the blank line before `# Core settings`):
  ```ini
  [uwsgi]
  ; Remove file creation commands since we're not logging to files anymore
  ; exec-pre = mkdir -p /data/logs
  ; exec-pre = touch /data/logs/uwsgi.log
  ; exec-pre = chmod 666 /data/logs/uwsgi.log

  ; First run Redis availability check script once
  exec-pre = python /app/scripts/wait_for_redis.py

  ; Start Redis first
  attach-daemon = redis-server
  ; Default prefork worker: every queue except `dvr`.
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr worker -Q celery -n default@%%h --autoscale=6,1
  ; DVR worker: thread pool for the long-running, I/O-bound run_recording task.
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr worker -Q dvr -n dvr@%%h --pool=threads --concurrency=20
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr beat
  attach-daemon = daphne -b 0.0.0.0 -p 8001 dispatcharr.asgi:application

  # Core settings
  ```
  with:
  ```ini
  [uwsgi]
  ; Redis, Celery and Daphne are supervisord programs now
  ; (docker/supervisord/all.conf), not uwsgi attach-daemons, and the Redis
  ; wait moved into docker/supervisord.d/wait-for-stores.sh.

  # Core settings
  ```
  Everything from `chdir = /app` to the end of the file is unchanged.

- [ ] **Step 2: `docker/uwsgi.modular.ini` — delete the comment block and the single daphne `attach-daemon`.**
  Replace lines 1-15:
  ```ini
  [uwsgi]
  ; Modular deployment mode - external PostgreSQL, Redis, and Celery
  ; Remove file creation commands since we're not logging to files anymore
  ; exec-pre = mkdir -p /data/logs
  ; exec-pre = touch /data/logs/uwsgi.log
  ; exec-pre = chmod 666 /data/logs/uwsgi.log

  ; Redis wait + flush is handled by the entrypoint in modular mode
  ; (uWSGI exec-pre runs under 'su -' which strips Docker env vars)

  ; Start Daphne for WebSocket support (required for real-time features)
  ; Redis and Celery run in separate containers in modular mode
  attach-daemon = daphne -b 0.0.0.0 -p 8001 dispatcharr.asgi:application

  # Core settings
  ```
  with:
  ```ini
  [uwsgi]
  ; Modular deployment mode - external PostgreSQL, Redis, and Celery.
  ; Daphne is a supervisord program now (docker/supervisord/api.conf), and
  ; the Redis wait moved into docker/supervisord.d/wait-for-stores.sh. It
  ; waits only: nothing flushes Redis in any role (D15).

  # Core settings
  ```

- [ ] **Step 3: `docker/uwsgi.dev.ini` — delete the daemon block.**
  Replace lines 1-20:
  ```ini
  [uwsgi]
  ; Remove file creation commands since we're not logging to files anymore
  ; exec-pre = mkdir -p /data/logs
  ; exec-pre = touch /data/logs/uwsgi-dev.log
  ; exec-pre = chmod 666 /data/logs/uwsgi-dev.log

  ; First run Redis availability check script once
  exec-pre = python /app/scripts/wait_for_redis.py

  ; Start Redis first
  attach-daemon = redis-server --protected-mode no
  ; Default prefork worker: every queue except `dvr`.
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr worker -Q celery -n default@%%h --autoscale=6,1
  ; DVR worker: thread pool for the long-running, I/O-bound run_recording task.
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr worker -Q dvr -n dvr@%%h --pool=threads --concurrency=20
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr beat
  attach-daemon = daphne -b 0.0.0.0 -p 8001 dispatcharr.asgi:application
  attach-daemon = cd /app/frontend && npm run dev

  # Core settings
  ```
  with:
  ```ini
  [uwsgi]
  ; Redis, Celery, Daphne and vite are supervisord programs now
  ; (docker/supervisord/all-dev.conf). --protected-mode no moved with Redis
  ; to docker/supervisord.d/redis-dev.conf, which is the only program that
  ; lowers it and says so.

  # Core settings
  ```

- [ ] **Step 4: `docker/uwsgi.debug.ini` — delete the daemon block and `honour-stdin`.**
  Replace lines 1-18:
  ```ini
  [uwsgi]
  ; exec-before = python manage.py collectstatic --noinput
  ; exec-before = python manage.py migrate --noinput

  ; First run Redis availability check script once
  exec-before = python /app/scripts/wait_for_redis.py

  ; Start Redis first
  attach-daemon = redis-server
  ; Default prefork worker: every queue except `dvr`.
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr worker -Q celery -n default@%%h --autoscale=6,1
  ; DVR worker: thread pool for the long-running, I/O-bound run_recording task.
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr worker -Q dvr -n dvr@%%h --pool=threads --concurrency=20
  attach-daemon = nice -n $(CELERY_NICE_LEVEL) celery -A dispatcharr beat
  attach-daemon = daphne -b 0.0.0.0 -p 8001 dispatcharr.asgi:application
  attach-daemon = cd /app/frontend && npm run dev

  # Core settings
  ```
  with:
  ```ini
  [uwsgi]
  ; Redis, Celery, Daphne and vite are supervisord programs now. Debug shares
  ; the dev rung (docker/supervisord/all-dev.conf), because
  ; docker-compose.debug.yml sets DISPATCHARR_ENV=dev as well as
  ; DISPATCHARR_DEBUG=true and the pre-supervisord entrypoint already ran
  ; vite and no nginx on that basis; DISPATCHARR_DEBUG selects this ini and
  ; nothing else.

  # Core settings
  ```
  Then, in the "Debugging settings" block, delete `honour-stdin = true` (line 72). Replace:
  ```ini
  # Debugging settings
  # Reload API workers: touch /app/.uwsgi-reload
  ; py-autoreload = 1
  touch-workers-reload = /app/.uwsgi-reload
  honour-stdin = true
  ```
  with:
  ```ini
  # Debugging settings
  # Reload API workers: touch /app/.uwsgi-reload
  ; py-autoreload = 1
  touch-workers-reload = /app/.uwsgi-reload
  ; honour-stdin removed with the move to supervisord (D2): a supervisord
  ; child has no controlling TTY, so uWSGI would hold a stdin that is never a
  ; terminal. Nothing is lost — debugpy attaches over TCP :5678, never over
  ; stdin, and the interactive pdb the flag existed for was already
  ; unreachable through `docker logs`.
  ```

- [ ] **Step 5: Confirm nothing survived.**
  Run: `grep -n "exec-pre\|exec-before\|attach-daemon\|honour-stdin = " /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/uwsgi*.ini`
  Expected: no output. (The `; honour-stdin removed…` comment does not match, because the pattern requires the ` = ` an active directive has.)
  Run: `head -8 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/uwsgi.debug.ini`
  Expected: `[uwsgi]` on line 1 — no file may lose its section header to the deletion.

- [ ] **Step 6: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/uwsgi.ini /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/uwsgi.modular.ini /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/uwsgi.dev.ini /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/uwsgi.debug.ini`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-7.txt` with the Write tool:
  ```
  fix(docker): drop exec-pre/attach-daemon from every uwsgi ini

  Redis, Celery, Daphne and vite are supervisord programs now (Tasks 3-4).
  Leaving the attach-daemons would start each of them twice, and leaving
  the exec-pre would re-run the Redis wait on every uwsgi restart.
  uwsgi.debug.ini also drops honour-stdin: a supervisord child has no
  controlling TTY, and debugpy attaches over TCP rather than stdin.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-7.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-7.txt`

## Task 8: Delete the two superseded entrypoints; update the compose files

**Files:**
- Delete: `docker/entrypoint.celery.sh`, `docker/entrypoint.aio.sh`
- Modify: `docker/docker-compose.yml`, `docker/docker-compose.aio.yml`

**Interfaces:** `docker-compose.yml`'s `celery` service boots through the shared `docker/entrypoint.sh` (Task 5) with `DISPATCHARR_ROLE=worker` instead of its own `entrypoint:` override. `web` gains an explicit `DISPATCHARR_ROLE=api` — the same value the entrypoint would derive, stated so a reader of the compose file can see which programs the container runs without reading the entrypoint.

- [ ] **Step 1: Delete the two files.**
  Run: `rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.celery.sh /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.aio.sh`
  `entrypoint.aio.sh` starts gunicorn and pm2 and is referenced by nothing — dead since before this fork. `entrypoint.celery.sh`'s two wait loops and its NumPy block are now in `docker/entrypoint.sh`'s `worker` branch.

- [ ] **Step 2: `docker/docker-compose.yml` — the `web` service.**
  Add `stop_grace_period` after `restart:` (line 12) and the role to the environment block (after line 29). Change:
  ```yaml
    web:
      image: ghcr.io/dispatcharr/dispatcharr:latest
      container_name: dispatcharr_web
      restart: unless-stopped
      ports:
        - 9191:9191
  ```
  to:
  ```yaml
    web:
      image: ghcr.io/dispatcharr/dispatcharr:latest
      container_name: dispatcharr_web
      restart: unless-stopped
      # supervisord stops its programs one priority group at a time, waiting
      # for each to finish before signalling the next, so the budget is the
      # sum of their stopwaitsecs and not the largest of them: 135s today,
      # 155s once PR 4 adds relay-uwsgi at 20s. 160s covers that ceiling, and
      # is set here once so PR 4's relay service needs no compose change.
      # The realistic stop is nearer 90s -- only the two Celery workers use
      # their full window, on warm shutdown with a task in flight.
      stop_grace_period: 160s
      ports:
        - 9191:9191
  ```
  and change:
  ```yaml
      # --- Environment Configuration ---
      environment:
        # Deployment Mode
        - DISPATCHARR_ENV=modular

        # PostgreSQL Connection
        - POSTGRES_HOST=db
  ```
  to:
  ```yaml
      # --- Environment Configuration ---
      environment:
        # Deployment Mode
        - DISPATCHARR_ENV=modular
        # Which supervisord programs this container runs: nginx, uwsgi and
        # daphne. This is also what the entrypoint would default to in
        # modular mode; stated explicitly so the compose file answers the
        # question on its own.
        - DISPATCHARR_ROLE=api

        # PostgreSQL Connection
        - POSTGRES_HOST=db
  ```
  Both `old_string` blocks are unique to the `web` service — the `celery` service's environment block starts with `DISPATCHARR_ENV=modular` too but is followed by the `DISPATCHARR_PORT` comment, not `POSTGRES_HOST=db`. Re-read the file and confirm before editing.

- [ ] **Step 3: `docker/docker-compose.yml` — the `celery` service.**
  Change:
  ```yaml
    celery:
      image: ghcr.io/dispatcharr/dispatcharr:latest
      container_name: dispatcharr_celery
      restart: unless-stopped
      depends_on:
  ```
  to:
  ```yaml
    celery:
      image: ghcr.io/dispatcharr/dispatcharr:latest
      container_name: dispatcharr_celery
      restart: unless-stopped
      # Both Celery workers carry stopwaitsecs=30 for a task in flight, and
      # supervisord waits for each in turn — see the web service above.
      stop_grace_period: 160s
      depends_on:
  ```
  Then delete the `entrypoint:` override (line 123) and add the role. Change:
  ```yaml
      extra_hosts:
        - "host.docker.internal:host-gateway"
      entrypoint: ["/app/docker/entrypoint.celery.sh"]

      # --- Environment Configuration ---
      environment:
        # Deployment Mode
        - DISPATCHARR_ENV=modular
  ```
  to:
  ```yaml
      extra_hosts:
        - "host.docker.internal:host-gateway"

      # --- Environment Configuration ---
      environment:
        # Deployment Mode
        - DISPATCHARR_ENV=modular
        # Which supervisord programs this container runs: the three Celery
        # programs and nothing else. Replaces the entrypoint override that
        # used to point at docker/entrypoint.celery.sh.
        - DISPATCHARR_ROLE=worker
  ```
  Leave the rest of the `celery` environment block, including the commented `#- DISPATCHARR_WEB_HOST=web` line and its explanation, untouched.

- [ ] **Step 4: `docker/docker-compose.aio.yml` — add the grace period.**
  Change:
  ```yaml
  services:
    dispatcharr:
      # build:
      #   context: .
      #   dockerfile: Dockerfile
      image: ghcr.io/dispatcharr/dispatcharr:latest
      restart: unless-stopped
      container_name: dispatcharr
  ```
  to:
  ```yaml
  services:
    dispatcharr:
      # build:
      #   context: .
      #   dockerfile: Dockerfile
      image: ghcr.io/dispatcharr/dispatcharr:latest
      restart: unless-stopped
      # supervisord stops its programs one priority group at a time, waiting
      # for each before signalling the next, so the budget is the sum of
      # their stopwaitsecs (nginx, three Celery programs, daphne, uwsgi,
      # Redis, PostgreSQL) rather than the largest. Docker's 10s default
      # would SIGKILL partway through PostgreSQL's fast shutdown.
      stop_grace_period: 160s
      container_name: dispatcharr
  ```

- [ ] **Step 5: Validate both edited compose files parse, and that the grace periods landed.**
  Run: `docker compose -f /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/docker-compose.yml config >/dev/null && echo OK`
  Expected: `OK`.
  Run: `docker compose -f /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/docker-compose.aio.yml config >/dev/null && echo OK`
  Expected: `OK`.
  Run: `docker compose -f /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/docker-compose.yml config | grep -E "stop_grace_period|DISPATCHARR_ROLE"`
  Expected: two `stop_grace_period: 160s` lines (`web`, `celery`) and two role lines (`DISPATCHARR_ROLE: api`, `DISPATCHARR_ROLE: worker`).

- [ ] **Step 6: Confirm no functional reference to either deleted file survives.**
  Run: `grep -rn "entrypoint\.celery\.sh\|entrypoint\.aio\.sh" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/ /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/scripts/ /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.github/workflows/*.yml 2>/dev/null`
  Expected: two matches, both in `docker/tests/test-tls-postgres.sh` (currently `:202` and `:928`), both inside comments that Task 10 rewrites, and both still present at this point because Task 10 has not run. Nothing under `docker/*.yml`, `docker/*.sh` outside `tests/`, `scripts/` or the compiled workflows.
  Two known mentions stay out of scope and are recorded as follow-ups rather than edited here: `CHANGELOG.md` (history, never rewritten) and `.github/workflows/claude-md-maintenance.md:122`, which lists `entrypoint.aio.sh` among the dead-code items that agentic workflow watches for. Editing that file means recompiling its `.lock.yml` with `gh aw compile` and re-linting with zizmor, which is a workflow change this supervision PR should not carry.

- [ ] **Step 7: Commit.**
  Run: `git add -A /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.celery.sh /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/entrypoint.aio.sh /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/docker-compose.yml /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/docker-compose.aio.yml`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-8.txt` with the Write tool:
  ```
  refactor(docker): delete entrypoint.celery.sh/.aio.sh, role the services

  entrypoint.aio.sh was dead (gunicorn and pm2, zero references).
  entrypoint.celery.sh is superseded by the shared entrypoint's worker
  branch, which lifts both of its wait loops and its NumPy block, so the
  celery service now boots through the shared entrypoint with
  DISPATCHARR_ROLE=worker instead of an entrypoint override. web states
  DISPATCHARR_ROLE=api explicitly.

  stop_grace_period: 160s on every service that runs supervisord.
  supervisord stops one priority group at a time and waits for each before
  signalling the next, so the container budget is the sum of the programs'
  stopwaitsecs, not the largest: measured at 9.4s for three programs at 3s
  each. Docker's 10s default would SIGKILL partway through PostgreSQL's
  fast shutdown.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-8.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-8.txt`

## Task 9: `docker/tests/test-puid-pgid.sh` — readiness contract and new assertions

**Files:** Modify: `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh` (lines 158-179, 291-304, 354-369, 401-437, 977-1046)

**Interfaces:**
- `wait_for_ready(name, timeout=$STARTUP_TIMEOUT)` — same signature and 0/1 return; internals swap the `uwsgi started with PID` log grep for `supervisorctl status api-uwsgi`.
- `check_migrations_done(container)` — same signature; the same swap in its fallback arm.
- `dump_logs_on_fail(container)` — same signature; additionally dumps `/run/supervisord.log`.
- New helper `supervisorctl_status(container, [program])` used by all of the above.
- `test_fresh_default` and `test_modular_mode` each gain a status assertion; `test_modular_mode` deliberately passes **no** `DISPATCHARR_ROLE`.

**This is the riskiest task in the plan.** The spec names it: replacing the entrypoint invalidates the readiness marker both suites match on, and a wrong swap makes every scenario time out rather than fail informatively.

- [ ] **Step 1: Add the `supervisorctl_status` helper, above `wait_for_ready` (before line 158).**
  One helper rather than five inline `docker exec` lines, so the `-c` target is written once.
  ```bash
  # Ask a container's supervisord for status. The -c target is a
  # serverurl-only file, not a rung, so this makes no claim about which role
  # the container is running — which matters because test_modular_mode below
  # deliberately does not set one.
  supervisorctl_status() {
      local name="$1" program="${2:-}"
      docker exec "$name" supervisorctl \
          -c /app/docker/supervisord/supervisorctl.conf status $program 2>/dev/null
  }
  ```
  `$program` is deliberately unquoted: empty means "every program", and `supervisorctl status ""` is an error.

- [ ] **Step 2: `wait_for_ready` — swap the log grep for the status check.**
  Current lines 158-179, verified:
  ```bash
  # Wait for container startup (looks for uwsgi or a known failure)
  wait_for_ready() {
      local name="$1"
      local timeout="${2:-$STARTUP_TIMEOUT}"
      local elapsed=0

      while [ $elapsed -lt $timeout ]; do
          # Check if container is still running
          if ! docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
              echo "  Container $name exited unexpectedly"
              return 1
          fi
          # Success: uwsgi started
          if log_matches "$name" "uwsgi started with PID"; then
              return 0
          fi
          # Known fatal: our error handler
          if log_matches "$name" "ERROR: Cannot update ownership"; then
              echo "  Container hit ownership error (expected in some tests)"
              return 1
          fi
          sleep 3
          ((elapsed+=3))
      done
      echo "  Timeout (${timeout}s) waiting for $name"
      return 1
  }
  ```
  Replace with:
  ```bash
  # Wait for container startup (api-uwsgi RUNNING under supervisord, or a
  # known failure).
  #
  # RUNNING is a weaker claim than the "uwsgi started with PID" line it
  # replaces: api-uwsgi runs through wait-for-stores.sh, and startsecs=5
  # means "this process stayed alive five seconds", so on a slow Postgres
  # the program is RUNNING while the wrapper is still waiting and uWSGI has
  # not been exec'd. That is enough for every assertion in this file — they
  # read logs the entrypoint wrote before supervisord started, or reach
  # PostgreSQL through docker exec — and no scenario here issues an HTTP
  # request. A test that needs uWSGI to be serving must poll the port, not
  # this.
  wait_for_ready() {
      local name="$1"
      local timeout="${2:-$STARTUP_TIMEOUT}"
      local elapsed=0

      while [ $elapsed -lt $timeout ]; do
          # Check if container is still running
          if ! docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
              echo "  Container $name exited unexpectedly"
              return 1
          fi
          # Success: api-uwsgi is RUNNING under supervisord
          if supervisorctl_status "$name" api-uwsgi | grep -q "RUNNING"; then
              return 0
          fi
          # Known fatal: our error handler
          if log_matches "$name" "ERROR: Cannot update ownership"; then
              echo "  Container hit ownership error (expected in some tests)"
              return 1
          fi
          sleep 3
          ((elapsed+=3))
      done
      echo "  Timeout (${timeout}s) waiting for $name"
      return 1
  }
  ```

- [ ] **Step 3: `check_migrations_done` — swap its fallback arm.**
  Current lines 291-304, verified. Replace only the `elif` branch and its comment:
  ```bash
      elif grep -q "uwsgi started with PID" "$tmplog"; then
          # uwsgi starts AFTER migrations — if it's running, migrations succeeded
          log_pass "Django migrations completed (confirmed via uwsgi startup)"
  ```
  with:
  ```bash
      elif supervisorctl_status "$container" api-uwsgi | grep -q "RUNNING"; then
          # supervisord does not start until the entrypoint's migrate has
          # returned, so an api-uwsgi program that exists at all means
          # migrations succeeded
          log_pass "Django migrations completed (confirmed via api-uwsgi startup)"
  ```
  The `if` arm (the log patterns) and the `else` arm are unchanged, as is the `$tmplog` capture the `if` arm still uses.

- [ ] **Step 4: `dump_logs_on_fail` — also dump supervisord's own log.**
  supervisord logs its state transitions (`entered RUNNING state`, `entered FATAL state`, `waiting for … to die`) to `/run/supervisord.log`, not to the container's stdout, so a `docker logs` dump alone no longer explains a supervision failure — and supervision failures are what this PR can newly cause. Append inside the existing `if` at lines 356-368, after the `docker logs` block:
  ```bash
          echo -e "  ${RED}--- supervisord log ---${NC}"
          # supervisord's own state transitions go to /run/supervisord.log,
          # not to container stdout, so `docker logs` alone cannot explain a
          # program that went FATAL or BACKOFF.
          docker exec "$container" cat /run/supervisord.log 2>/dev/null \
              | tail -60 | sed 's/^/  | /' || echo "  | (unavailable)"
          echo -e "  ${RED}--- supervisorctl status ---${NC}"
          supervisorctl_status "$container" | sed 's/^/  | /' || echo "  | (unavailable)"
          echo -e "  ${RED}--- End logs ---${NC}"
  ```
  and delete the `echo -e "  ${RED}--- End logs ---${NC}"` that currently closes the `docker logs` block, so there is one closing marker rather than two.

- [ ] **Step 5: `test_fresh_default` — assert every `all`-role program is healthy.**
  Insert after the ownership-sentinel check (currently ends at line 431), still inside the `if wait_for_ready …` block:
  ```bash
          # Every program of the `all` role RUNNING, none FATAL or BACKOFF.
          # This is the assertion that catches a uwsgi, daphne or celery
          # program losing its race with Postgres or Redis: priority= orders
          # the start signals but is not a readiness barrier, so only each
          # program's own wait-for-stores.sh wrapper prevents it.
          local status_output
          status_output=$(supervisorctl_status "$name")
          if [ -z "$status_output" ]; then
              log_fail "supervisorctl status returned nothing"
          elif echo "$status_output" | grep -qE "FATAL|BACKOFF"; then
              log_fail "supervisorctl status shows FATAL/BACKOFF:"
              echo "$status_output" | sed 's/^/    /'
          else
              local missing=""
              for prog in postgres redis api-uwsgi daphne celery-default celery-dvr celery-beat nginx; do
                  echo "$status_output" | grep -qE "^${prog}[[:space:]]+RUNNING" || missing="$missing $prog"
              done
              if [ -n "$missing" ]; then
                  log_fail "supervisorctl status: not RUNNING:$missing"
                  echo "$status_output" | sed 's/^/    /'
              else
                  log_pass "supervisorctl status: all eight programs of role 'all' RUNNING"
                  echo "$status_output" | sed 's/^/    /'
              fi
          fi
  ```
  The explicit name list is the point: a `grep -qE "FATAL|BACKOFF"` alone would pass a rung that silently included nothing.

- [ ] **Step 6: `test_modular_mode` — assert the defaulted role and the `api` program set.**
  Do **not** add `-e DISPATCHARR_ROLE=api` to the `docker run` (currently lines 1015-1025). Leaving it off is what makes this scenario cover A2's default: every existing modular deployment sets only `DISPATCHARR_ENV=modular`, and if the default ever regresses to `all` this scenario fails with `postgres` in `FATAL` rather than passing quietly. Add a comment above the unchanged `docker run` saying so:
  ```bash
      # No DISPATCHARR_ROLE on purpose. A modular container that names no
      # role must default to `api` — which is what every deployment written
      # before that variable existed looks like. If the default regressed to
      # `all`, all.conf's [program:postgres] would start against an
      # uninitialised /data/db and the status assertion below would catch it.
  ```
  Then insert after `check_migrations_done "$name"` (currently line 1039):
  ```bash
          check_log_contains "$name" "DISPATCHARR_ROLE=api" \
              "Modular container defaulted to role api"

          # The api rung has no postgres or redis program at all, so this
          # asserts the role split as well as the health of what it runs.
          local status_output
          status_output=$(supervisorctl_status "$name")
          if [ -z "$status_output" ]; then
              log_fail "supervisorctl status returned nothing"
          elif echo "$status_output" | grep -qE "FATAL|BACKOFF"; then
              log_fail "supervisorctl status shows FATAL/BACKOFF:"
              echo "$status_output" | sed 's/^/    /'
          elif echo "$status_output" | grep -qE "^(postgres|redis|celery-)"; then
              log_fail "supervisorctl status: role api must run no local stores or Celery:"
              echo "$status_output" | sed 's/^/    /'
          else
              local missing=""
              for prog in api-uwsgi daphne nginx; do
                  echo "$status_output" | grep -qE "^${prog}[[:space:]]+RUNNING" || missing="$missing $prog"
              done
              if [ -n "$missing" ]; then
                  log_fail "supervisorctl status: not RUNNING:$missing"
                  echo "$status_output" | sed 's/^/    /'
              else
                  log_pass "supervisorctl status: all three programs of role 'api' RUNNING"
                  echo "$status_output" | sed 's/^/    /'
              fi
          fi
  ```

- [ ] **Step 7: Confirm the old marker is gone from this file and the new one is used consistently.**
  Run: `grep -n "uwsgi started with PID" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh`
  Expected: no output.
  Run: `grep -c "supervisorctl_status" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh`
  Expected: `6` — the definition plus one call each in `wait_for_ready`, `check_migrations_done`, `dump_logs_on_fail`, `test_fresh_default` and `test_modular_mode`.
  Run: `grep -n "supervisord/supervisorctl.conf" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh`
  Expected: exactly one line, inside `supervisorctl_status`.

- [ ] **Step 8: Syntax-check, and confirm the scenario list still resolves.**
  Run: `bash -n /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh`
  Expected: exit 0, no output. This is what catches an unbalanced `if`/`fi` in Step 4's rewritten `dump_logs_on_fail`.
  Run: `grep -c "^test_[a-z_]*()" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh`
  Expected: `18` — the same count as before this task. This PR changes what two scenarios assert; it adds and removes none. (The suite has no `--help`; a scenario name is a bare positional argument.)

- [ ] **Step 9: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-9.txt` with the Write tool:
  ```
  test(docker): move test-puid-pgid.sh's readiness contract to supervisorctl

  wait_for_ready and check_migrations_done no longer grep for the deleted
  "uwsgi started with PID" line; both ask supervisord whether api-uwsgi is
  RUNNING, through a serverurl-only conf so the call makes no claim about
  the container's role. test_fresh_default asserts all eight programs of
  role all, test_modular_mode asserts the three of role api and that it
  runs no local stores. test_modular_mode still passes no
  DISPATCHARR_ROLE, so it covers the modular default. dump_logs_on_fail
  also dumps /run/supervisord.log, where supervisord records the state
  transitions that a docker logs dump cannot show.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-9.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-9.txt`

## Task 10: `docker/tests/test-tls-postgres.sh` — readiness contract and the Celery scenario

**Files:** Modify: `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-tls-postgres.sh` (lines 134-151, 196-215, 241-253, 273-283, 917-931)

**Interfaces:** the same three helper swaps as Task 9, plus `test_modular_full_tls_celery`'s Celery container booting via `-e DISPATCHARR_ROLE=worker` instead of `--entrypoint /app/docker/entrypoint.celery.sh`.

Both containers in that scenario reach the shared entrypoint now: the web container sets `DISPATCHARR_ENV=modular` and no role, so it defaults to `api` (A2), and the Celery container names `worker` explicitly because nothing in its environment implies it.

- [ ] **Step 1: Add the `supervisorctl_status` helper, above `wait_for_ready` (before line 134).**
  Identical to Task 9 Step 1 — the two suites share no library, so the helper is defined in each:
  ```bash
  # Ask a container's supervisord for status. The -c target is a
  # serverurl-only file, not a rung, so this makes no claim about which role
  # the container is running.
  supervisorctl_status() {
      local name="$1" program="${2:-}"
      docker exec "$name" supervisorctl \
          -c /app/docker/supervisord/supervisorctl.conf status $program 2>/dev/null
  }
  ```

- [ ] **Step 2: `wait_for_ready` — same swap as Task 9 Step 2.**
  Current lines 134-151, verified:
  ```bash
  wait_for_ready() {
      local name="$1"
      local timeout="${2:-$STARTUP_TIMEOUT}"
      local elapsed=0

      while [ $elapsed -lt $timeout ]; do
          if ! docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
              echo "  Container $name exited unexpectedly"
              return 1
          fi
          if log_matches "$name" "uwsgi started with PID"; then
              return 0
          fi
          sleep 3
          ((elapsed+=3))
      done
      echo "  Timeout (${timeout}s) waiting for $name"
      return 1
  }
  ```
  Replace with:
  ```bash
  # RUNNING is a weaker claim than the "uwsgi started with PID" line it
  # replaces — api-uwsgi runs through wait-for-stores.sh and startsecs=5
  # counts from the wrapper, not from uWSGI — but every assertion in this
  # file reads logs or runs psql, and none issues an HTTP request.
  wait_for_ready() {
      local name="$1"
      local timeout="${2:-$STARTUP_TIMEOUT}"
      local elapsed=0

      while [ $elapsed -lt $timeout ]; do
          if ! docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
              echo "  Container $name exited unexpectedly"
              return 1
          fi
          if supervisorctl_status "$name" api-uwsgi | grep -q "RUNNING"; then
              return 0
          fi
          sleep 3
          ((elapsed+=3))
      done
      echo "  Timeout (${timeout}s) waiting for $name"
      return 1
  }
  ```

- [ ] **Step 3: `check_migrations_done` — same fallback swap as Task 9 Step 3.**
  Current lines 241-253, verified. Replace only:
  ```bash
      elif grep -q "uwsgi started with PID" "$tmplog"; then
          log_pass "Django migrations completed (confirmed via uwsgi startup)"
  ```
  with:
  ```bash
      elif supervisorctl_status "$container" api-uwsgi | grep -q "RUNNING"; then
          log_pass "Django migrations completed (confirmed via api-uwsgi startup)"
  ```

- [ ] **Step 4: `dump_logs_on_fail` — also dump supervisord's own log.**
  Insert before the closing `echo -e "  ${YELLOW}--- End logs ---${NC}"` at line 281:
  ```bash
          echo -e "  ${YELLOW}--- supervisord log ($container) ---${NC}"
          # supervisord's state transitions go to /run/supervisord.log, not
          # to container stdout; a program that went FATAL is invisible in
          # `docker logs` alone.
          docker exec "$container" cat /run/supervisord.log 2>/dev/null \
              | tail -60 | sed 's/^/    /' || echo "    (unavailable)"
          echo -e "  ${YELLOW}--- supervisorctl status ($container) ---${NC}"
          supervisorctl_status "$container" | sed 's/^/    /' || echo "    (unavailable)"
  ```

- [ ] **Step 5: Rewrite the two comments that name the deleted Celery entrypoint.**
  Both are prose that would otherwise point at a file this PR removes. Current lines 202-214 (the `wait_log_contains` preamble), verified:
  ```bash
  # check_log_contains, but waits for the pattern instead of reading once.
  #
  # entrypoint.celery.sh prints "Migrations complete, starting Celery..." and
  # only THEN execs the workers, whose Django settings import emits the TLS
  # banners. The wait loop returns on the former, so a bare check_log_contains
  # reads the log before the latter has been written. The app container has no
  # such gap: its banners come from the entrypoint's own `manage.py` calls,
  # which run before uwsgi starts, while the celery entrypoint sends its
  # equivalent (`migrate --check`) to /dev/null.
  ```
  Replace that comment block (leaving the paragraph about the pipefail/SIGPIPE fix that follows it untouched) with:
  ```bash
  # check_log_contains, but waits for the pattern instead of reading once.
  #
  # The shared entrypoint's worker branch prints "Migrations complete,
  # starting Celery..." and only THEN execs supervisord, whose Celery
  # programs emit the TLS banners on their Django settings import. The wait
  # loop returns on the former, so a bare check_log_contains reads the log
  # before the latter has been written. The app container has no such gap:
  # its banners come from the entrypoint's own `manage.py` calls, which run
  # before supervisord starts, while the worker branch sends its equivalent
  # (`migrate --check`) to /dev/null.
  ```
  Current lines 926-933 (the wait-loop preamble in the scenario), verified:
  ```bash
      # Wait for Celery to start (look for "starting Celery" message).
      #
      # $STARTUP_TIMEOUT, not a hardcoded 90. entrypoint.celery.sh emits
      # "Migrations complete, starting Celery..." only AFTER running the whole
      # Django migration set over a TLS connection, so this budget covers
      # migrations, not process startup — and 90s is inside the range a loaded
      # machine takes to do that. Observed failing at 90s and passing at the
      # same code minutes earlier. CI never caught it because all seven TLS
  ```
  Replace the first three sentences so the reference is to the shared entrypoint:
  ```bash
      # Wait for Celery to start (look for "starting Celery" message).
      #
      # $STARTUP_TIMEOUT, not a hardcoded 90. The shared entrypoint's worker
      # branch emits "Migrations complete, starting Celery..." only AFTER the
      # whole Django migration set has been applied over a TLS connection by
      # the api container, so this budget covers migrations, not process
      # startup — and 90s is inside the range a loaded machine takes to do
      # that. Observed failing at 90s and passing at the same code minutes
      # earlier. CI never caught it because all seven TLS
  ```
  Leave the remainder of that comment (from `scenarios died at settings import…`) exactly as it is.

- [ ] **Step 6: `test_modular_full_tls_celery` — boot the Celery container by role.**
  Current lines 917-924, verified:
  ```bash
      # Start Celery container (shares /data volume for JWT, waits for migrations)
      docker run -d --name "$celery_name" --network "$net" \
          "${tls_env[@]}" \
          -e DJANGO_SETTINGS_MODULE=dispatcharr.settings \
          -e PYTHONUNBUFFERED=1 \
          -v "${cert_mount}:/certs:ro" \
          -v "${vol}:/data" \
          --entrypoint /app/docker/entrypoint.celery.sh \
          "$IMAGE_NAME" >/dev/null
  ```
  Replace with:
  ```bash
      # Start Celery container (shares /data volume for JWT, waits for
      # migrations). No entrypoint override: the shared entrypoint's worker
      # role does what entrypoint.celery.sh did, including running Celery as
      # root and passing -l info, and it additionally does the PUID/PGID and
      # TLS client-key setup that script did differently.
      docker run -d --name "$celery_name" --network "$net" \
          "${tls_env[@]}" \
          -e DJANGO_SETTINGS_MODULE=dispatcharr.settings \
          -e PYTHONUNBUFFERED=1 \
          -e DISPATCHARR_ROLE=worker \
          -v "${cert_mount}:/certs:ro" \
          -v "${vol}:/data" \
          "$IMAGE_NAME" >/dev/null
  ```
  The two log assertions that follow — `log_matches "$celery_name" "starting Celery"` (line 946) and `check_log_contains "$celery_name" "Migrations complete"` (line 955) — need **no** text change: Task 5's worker branch prints `✅ Migrations complete.` and then `Migrations complete, starting Celery...`, reusing the historic wording verbatim so both substrings still match. Leave them alone.

- [ ] **Step 7: Confirm the swaps landed and no functional reference to the deleted script remains.**
  Run: `grep -n "uwsgi started with PID" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-tls-postgres.sh`
  Expected: no output.
  Run: `grep -n -- "--entrypoint /app/docker/" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-tls-postgres.sh`
  Expected: no output. Tightened twice over the obvious pattern: a bare `entrypoint.celery.sh` grep matches the two prose comments and could never reach zero, and a bare `--entrypoint` grep matches the two legitimate `--entrypoint sh` / `--entrypoint chown` helper calls at lines 314 and 359, which this PR does not touch.
  Run: `grep -rn "entrypoint\.celery\.sh\|entrypoint\.aio\.sh" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/`
  Expected: no output, now that Step 5 has rewritten both comments and Step 6 has removed the override.

- [ ] **Step 8: Syntax-check.**
  Run: `bash -n /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-tls-postgres.sh`
  Expected: exit 0, no output.
  Run: `grep -c "^test_[a-z_]*()" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-tls-postgres.sh`
  Expected: `8` — the same count as before this task. This PR changes how one scenario starts a container and adds none.

- [ ] **Step 9: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-tls-postgres.sh`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-10.txt` with the Write tool:
  ```
  test(docker): move test-tls-postgres.sh's readiness contract to supervisorctl

  Same swap as test-puid-pgid.sh: wait_for_ready and check_migrations_done
  ask supervisord whether api-uwsgi is RUNNING instead of grepping the
  deleted "uwsgi started with PID" line, and dump_logs_on_fail also dumps
  /run/supervisord.log. test_modular_full_tls_celery boots its Celery
  container with DISPATCHARR_ROLE=worker instead of an entrypoint override
  pointing at the deleted entrypoint.celery.sh; its two log assertions are
  unchanged, because the shared entrypoint prints the same "Migrations
  complete, starting Celery..." wording at the equivalent point. The two
  comments that explained the old script's log ordering now describe the
  shared entrypoint's worker branch.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-10.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-10.txt`

## Task 11: `CLAUDE.md` corrections, two stale comments, and the twelve spec amendments

**Files:**
- Modify: `CLAUDE.md` (lines 40, 59, 67, 122)
- Modify: `core/tests/test_migrate_without_redis.py` (docstring, lines 3-4)
- Modify: `e2e/tests/lifecycle/durable-state.ts` (comment, lines 5-8)
- Modify: `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (the twelve amendments)

**Interfaces:** none — documentation and comments only. No behaviour changes in this task; the two source files change a docstring and a block comment respectively, and both still run under their existing hooks.

- [ ] **Step 1: `CLAUDE.md` § Architecture — the `attach-daemon` paragraph and the `entrypoint.aio.sh` parenthetical.**
  Current line 59, verified, opening of the paragraph:
  ```
  `docker/uwsgi.ini` runs uWSGI (4 workers × `gevent = 400`, `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`) with the rest as `attach-daemon`: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. (`docker/entrypoint.aio.sh` starts gunicorn and is referenced nowhere — legacy.) Consequences constraining nearly every `apps/proxy` change:
  ```
  Replace with:
  ```
  `docker/uwsgi.ini` runs uWSGI (4 workers × `gevent = 400`, `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`) as one `supervisord` program among several (`docker/supervisord/` holds one conf per rung, `docker/supervisord.d/` one `[program:x]` per file): Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. **`DISPATCHARR_ROLE`** (`all`/`api`/`relay`/`worker`, defaulted from `DISPATCHARR_ENV`) picks which subset a container runs; `DISPATCHARR_ENV=dev` picks the `all-dev` rung instead, which runs vite and no nginx. `priority=` orders start and stop *signals*, so each program waits for its own stores through `docker/supervisord.d/wait-for-stores.sh`, and shutdown walks one priority group at a time rather than signalling everything at once. (`docker/entrypoint.aio.sh` and `docker/entrypoint.celery.sh` are deleted, not legacy.) Consequences constraining nearly every `apps/proxy` change:
  ```

- [ ] **Step 2: `CLAUDE.md` § Architecture § State — the flush sentence.**
  Current line 67, mid-paragraph, verified:
  ```
  `scripts/wait_for_redis.py` does `flushdb()` on every AIO boot; the modular variant preserves only Celery prefixes and has no instance scoping.
  ```
  Replace with:
  ```
  `scripts/wait_for_redis.py` is wait-only — it never flushes, in any role. AIO's Redis starts empty because supervisord runs it non-persistent (`--save "" --appendonly no`), not because anything wipes it, so a control-plane restart leaves a running relay's keys untouched.
  ```

- [ ] **Step 3: `CLAUDE.md` § Commands — the Docker bullet.**
  Current line 40, verified:
  ```
  - Docker: `docker/docker-compose.{dev,aio}.yml` + `docker-compose.yml` (modular); `DISPATCHARR_ENV` picks the variant. `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh` are good integration tests — wired into no workflow.
  ```
  Replace with:
  ```
  - Docker: `docker/docker-compose.{dev,aio}.yml` + `docker-compose.yml` (modular); `DISPATCHARR_ENV` picks the deployment shape and `DISPATCHARR_ROLE` (`all`/`api`/`relay`/`worker`) picks which supervisord programs the container runs. `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh` are good integration tests, run by `lifecycle-tests.yml`'s `suites` job in full mode.
  ```
  The "wired into no workflow" half is stale independently of this PR — G12 wired both suites into `lifecycle-tests.yml` — and is corrected here because this PR is the reason to read the line. Recorded in the final report so the correction is not mistaken for something this PR did.

- [ ] **Step 4: `CLAUDE.md` § Known defects — the `die-on-term` sentence.**
  Current line 122, mid-paragraph, verified:
  ```
  `die-on-term` with no drain — every deploy drops every viewer and leaves Redis state behind.
  ```
  Replace with:
  ```
  `die-on-term` with no drain — every deploy still drops every viewer, but the stop is now bounded rather than raced: supervisord signals each program in descending `priority` and waits out its `stopwaitsecs` before moving to the next, so the container budget is the *sum* of those windows (135s, 155s after PR 4) rather than the largest, hence a 160s `stop_grace_period` against a realistic ~90s stop, instead of the old entrypoint's 8-second `pkill` ceiling. Redis state is no longer wiped on boot either (`wait_for_redis.py` is wait-only), so what a deploy leaves behind is now deliberate.
  ```

- [ ] **Step 5: The two stale comments that name behaviour this PR removes.**
  `core/tests/test_migrate_without_redis.py`, current lines 3-4:
  ```python
  In AIO, ``manage.py migrate`` runs in the entrypoint before uWSGI starts
  Redis via ``attach-daemon``. Any data migration that hard-requires Redis
  ```
  Replace with:
  ```python
  In AIO, ``manage.py migrate`` runs in the entrypoint before supervisord —
  and therefore before Redis — starts at all. Any data migration that
  hard-requires Redis
  ```
  The test's premise is unchanged and in fact strengthened: Redis is now started strictly later than it was.

  `e2e/tests/lifecycle/durable-state.ts`, current lines 5-8:
  ```typescript
   * Postgres-backed rows only. Redis is excluded by construction rather than by
   * preference: AIO configures no persistence and `scripts/wait_for_redis.py`
   * calls `flushdb()` on every boot, so a Redis-backed persistence assertion
   * would be asserting a falsehood (spec D11).
  ```
  Replace with:
  ```typescript
   * Postgres-backed rows only. Redis is excluded by construction rather than by
   * preference: AIO runs Redis non-persistent (`--save "" --appendonly no`), so
   * it starts empty on every boot and a Redis-backed persistence assertion
   * would be asserting a falsehood (spec D11). Nothing flushes it any more —
   * `scripts/wait_for_redis.py` is wait-only — but the observable outcome for
   * this file is the same.
  ```
  Run the two hooks after these edits:
  `echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/core/tests/test_migrate_without_redis.py"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/run-affected-tests.sh`
  Expected: exit 0, the `core.tests` package passes.
  `echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/e2e/tests/lifecycle/durable-state.ts"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr3 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.claude/hooks/run-affected-tests.sh`
  Expected: exit 0, `npx tsc --noEmit` clean for the `e2e` package.

- [ ] **Step 6: Apply the twelve amendments to the spec.**
  Work through the § Spec amendments table at the top of this plan, top to bottom. For each: re-read the named region of `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (line numbers drift, the tree wins), then Edit it so the spec states what this PR builds. Concretely:
  - **A1** — D2's "Covering `dev`/`debug` too costs one extra program file per mode" becomes one extra *rung* (`all-dev`) covering both. The ladder table loses its `DISPATCHARR_DEBUG = true → all-debug.conf` row and becomes two rows: `DISPATCHARR_ENV = dev → all-dev.conf`, `otherwise, by DISPATCHARR_ROLE → all.conf, api.conf, relay.conf, worker.conf`. The rung bullet says five files plus `supervisorctl.conf`, and its "the selector is role × env × debug, the same three inputs" becomes two inputs. In the program table, delete every `all-debug` from the "Included by" column, and rewrite the `vite` row's closing sentence — "`all-debug` keeps nginx, matching today" — to say the debug compose file sets `DISPATCHARR_ENV=dev` as well, so debug shares the dev rung and gets vite and no nginx, which is what it has today. Add the `99-init-dev.sh` sourcing to the entrypoint bullet's `all` line. Finally, in § PR 4, the `relay-uwsgi` bullet's "It is included by `all.conf`, `all-dev.conf`, `all-debug.conf` and `relay.conf`" loses `all-debug.conf` — that is the one place outside § PR 3 where the deleted rung is named, and missing it would leave PR 4 instructed to edit a file this PR never creates.
  - **A2** — D3's "AIO defaults to `all`; the modular compose file's `web`/`relay`/`celery` services set `api`/`relay`/`worker`" becomes "AIO defaults to `all` and modular defaults to `api`, because every deployment predating this variable sets only `DISPATCHARR_ENV`; the modular compose file states `api`/`relay`/`worker` explicitly anyway. There is no modular `all`, and no non-modular `api`, `relay` or `worker`; the entrypoint rejects all four."
  - **A3** — boot rule 3's "Celery retries its broker itself and needs no wrapper" becomes a statement that this holds for Redis only, that `django_celery_beat`'s `DatabaseScheduler` queries PostgreSQL in `setup_schedule()`, and that all five long-lived programs (both uWSGI and the three Celery) therefore run through the wrapper with `startretries=20` and `startsecs=5`.
  - **A4** — replace the "Every program also carries `user=%(ENV_POSTGRES_USER)s`" sentence with the split rule, and put `setpriv` into the `api-uwsgi` and three `celery-*` command cells.
  - **A5** — add the `DISPATCHARR_CELERY_USER` bullet after the `CELERY_NICE_LEVEL` one, and the follow-up note that dropping the worker to PUID needs a recursive chown.
  - **A6** — the `postgres` row's command cell gains `%(ENV_PG_BINDIR)s/`.
  - **A7** — boot rule 1 and the `all` one-shot line get the exact `su - … pg_ctl … stop -m fast -w` invocation and its position (after the hwaccel check).
  - **A8** — D15 and the Done grep gain the `scripts/ci_coverage_backend.sh` carve-out.
  - **A9** — rewrite the `priority=` paragraph: cite `Supervisor.ordered_stop_groups_phase_1`/`_phase_2` (`supervisord.py:156-172`) rather than `ProcessGroup.stop_all` alone, state that the budget is the sum, give the 135s arithmetic and the 9.4s measurement, and change every `45s`/`45 s` to `160s`/`160 s` — in that paragraph, in the `stop_grace_period` bullet, in the `postgres` row's "well inside the 45 s grace period", and in § Requirements' drain row.
  - **A10** — the three `celery-*` command cells gain `-l %(ENV_CELERY_LOG_LEVEL)s`, with a note naming the two historic defaults.
  - **A11** — add the one-line `04-check-hwaccel.sh` note to § PR 4, beside the `relay-uwsgi` program bullet.
  - **A12** — the rung bullet names `supervisorctl.conf`, and the readiness bullet's `supervisorctl -c <role conf>` becomes `supervisorctl -c /app/docker/supervisord/supervisorctl.conf`.

  Do not touch § Done log, § Risks or § Non-goals except where A9 requires the `45s` → `160s` change; those sections describe the programme, not this PR.

- [ ] **Step 7: Confirm the amendments landed and left no contradiction.**
  Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 && grep -n "all-debug\|45s\|45 s" docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`
  Expected: no output.
  Run: `grep -c "supervisorctl.conf\|DISPATCHARR_CELERY_USER\|CELERY_LOG_LEVEL\|setpriv\|stop -m fast -w\|ci_coverage_backend" docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`
  Expected: at least `6` — one match per amendment that introduces a new identifier.
  Run: `grep -n "entrypoint.aio.sh\|entrypoint.celery.sh\|attach-daemon\|does \`flushdb()\`" /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/CLAUDE.md`
  Expected: no output.

- [ ] **Step 8: Commit.**
  Run: `git add /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/CLAUDE.md /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/core/tests/test_migrate_without_redis.py /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/e2e/tests/lifecycle/durable-state.ts /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`
  Write `/Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-11.txt` with the Write tool:
  ```
  docs: correct CLAUDE.md and the Phase 1 spec for supervisord

  Four CLAUDE.md corrections named by the spec's PR 3 section: the
  attach-daemon paragraph and the entrypoint.aio.sh "legacy"
  parenthetical, the wait_for_redis.py flush sentence, the Docker bullet,
  and the die-on-term sentence. Two stale comments in the same vein, in a
  core test's docstring and the e2e durable-state preamble.

  Twelve spec amendments, each recorded in the plan with the sentence it
  replaces. The load-bearing ones: five rung files rather than six because
  the debug compose file sets ENV=dev too; modular defaults to role api;
  the Celery programs also wait for their stores; setpriv rather than
  user= so a negative nice level survives; and supervisord shutdown is
  sequential per priority group, which makes the container grace period
  the sum of the stopwaitsecs and not the largest of them.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
  Run (separate Bash call): `git commit -F /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-11.txt && rm /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/.git-commit-msg-11.txt`

## Task 12: Full local verification — build, boot, assert

**Files:** none (verification only — the last gate before opening the PR).

**Interfaces:** none. Every container, volume, network and port below is `pr3`-suffixed so nothing collides with the PR 2 stack or the shared `dispatcharr-e2e` one. Never pass `--reset` or `--down` to `scripts/e2e_up.sh`; this task does not use that script at all.

Long-running commands (`docker build`, both bash suites) run in the foreground with `</dev/null` and a 600000 ms timeout, so a prompt cannot hang them and a slow build is not cut short.

- [ ] **Step 1: Build the AIO image from this worktree.**
  Run (foreground, 600000 ms timeout):
  `docker build --build-arg REPO_OWNER=d10scot -f /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/Dockerfile -t dispatcharr-pr3:local /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 </dev/null`
  Expected: exit 0. `REPO_OWNER=d10scot` is what resolves `BASE_IMAGE` to `ghcr.io/d10scot/dispatcharr:base` — the fork's base image, the one PR 1 added supervisord to. Without it the build pulls upstream's base, which has no supervisord, and every rung fails at `exec`. If the base pull 404s, re-check Task 1 Steps 5 and 6.

- [ ] **Step 2: Confirm the three binaries the new configs name are present in the built image.**
  Run: `docker run --rm --entrypoint /bin/bash dispatcharr-pr3:local -c 'which supervisord; which setpriv; which nice; PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -n1); ls /usr/lib/postgresql/$PG_VERSION/bin/postgres'`
  Expected: `/dispatcharrpy/bin/supervisord`, `/usr/bin/setpriv`, `/usr/bin/nice`, `/usr/lib/postgresql/17/bin/postgres`. Each is load-bearing: `supervisord` for the exec, `setpriv` for A4's privilege drop, `nice` because supervisord runs `command=` without a shell so it must be a real binary, and the last for A6.
  Run: `docker run --rm --entrypoint /dispatcharrpy/bin/python dispatcharr-pr3:local /app/docker/tests/validate-supervisord-conf.py /app`
  Expected: the same five `OK` lines and `0 failure(s)` Task 4 produced — now against the paths the image actually has, with `/app` and `/run` real rather than rewritten.

- [ ] **Step 3: Boot an AIO container.**
  Run: `docker volume create dispatcharr-pr3-data && docker run -d --name dispatcharr-pr3-aio -p 127.0.0.1:29191:9191 -v dispatcharr-pr3-data:/data -e DISPATCHARR_ENV=aio -e DISPATCHARR_LOG_LEVEL=info dispatcharr-pr3:local`
  Expected: a container ID, exit 0. Port 29191 on the host, not 19191: the PR 2 stack holds that one.
  Run: `for i in $(seq 1 90); do curl -sf http://127.0.0.1:29191/api/accounts/initialize-superuser/ >/dev/null 2>&1 && echo READY && break; sleep 2; done`
  Expected: `READY` within ~180s. This is the same endpoint `scripts/e2e_up.sh` probes, and it goes through nginx to uWSGI, so it proves what `supervisorctl status` alone cannot: the API is actually serving.
  If it never prints, run `docker logs dispatcharr-pr3-aio 2>&1 | tail -60` and `docker exec dispatcharr-pr3-aio cat /run/supervisord.log | tail -60` before changing anything — the second is where a `FATAL` program is named.

- [ ] **Step 4: Assert the role announcement, the program set and the absence of a second postmaster.**
  Run: `docker exec dispatcharr-pr3-aio supervisorctl -c /app/docker/supervisord/supervisorctl.conf status`
  Expected: eight lines — `postgres`, `redis`, `api-uwsgi`, `daphne`, `celery-default`, `celery-dvr`, `celery-beat`, `nginx` — every one `RUNNING`, none `FATAL`, `BACKOFF` or `STOPPED`.
  Run: `docker logs dispatcharr-pr3-aio 2>&1 | grep -E "DISPATCHARR_ROLE=|Handing PostgreSQL over|Supervisor is running as root"`
  Expected: `🎛️  DISPATCHARR_ROLE=all (DISPATCHARR_ENV=aio)`, then `Handing PostgreSQL over to supervisord (fast stop)...`. The third pattern will **not** appear in `docker logs` — supervisord records that CRIT in `/run/supervisord.log`, not on stdout — which is the next check.
  Run: `docker exec dispatcharr-pr3-aio grep -c "Privileges were not dropped" /run/supervisord.log`
  Expected: `1`. This message is expected and correct: supervisord must stay root so `user=` and `setpriv` can drop each child individually. Adding `user=` to `[supervisord]` would silence it and break every privilege drop. Record it in the PR body so a reviewer reading a boot log does not treat it as a defect.
  Run: `docker exec dispatcharr-pr3-aio bash -c 'ps -eo pid,ppid,user,ni,comm | grep -E "postgres|uwsgi|celery|nginx|redis" | head -30'`
  Expected: exactly one `postgres` parent process (the postmaster, plus its own background workers), whose PPID is supervisord's; no orphan whose PPID is 1 other than supervisord itself. The nice column shows `0` for uWSGI (the default `UWSGI_NICE_LEVEL`) and `5` for the Celery processes — the absolute value, which is the visible half of the `CELERY_NICE_LEVEL` change.

- [ ] **Step 5: Measure the shutdown, since A9 changed the number the compose files carry.**
  Run: `time docker stop -t 160 dispatcharr-pr3-aio`
  Expected: completes in well under 160s — every program exits on its stop signal, so the sequential walk costs a second or two per program, not each program's full `stopwaitsecs`. Record the measured wall time and `docker inspect dispatcharr-pr3-aio --format '{{.State.ExitCode}}'` in the task report and the PR body: nothing pins either today, and A9's 160s is the arithmetic ceiling (135s now, 155s after PR 4), not a measurement of this container. A stop that takes anywhere near 160s means a program is ignoring its stop signal — investigate which, rather than raising the number.
  Run: `docker inspect dispatcharr-pr3-aio --format '{{.State.Status}} {{.State.ExitCode}}'`
  Expected: `exited` and an exit code of `0` or `143`. Note which; `137` would mean Docker `SIGKILL`ed supervisord and the grace period is too small after all, which is a finding, not a pass.
  Run: `docker rm -f dispatcharr-pr3-aio; docker volume rm dispatcharr-pr3-data`
  Expected: both succeed.

- [ ] **Step 6: Modular boot — the defaulted `api` role and an explicit `worker`.**
  Run:
  ```
  docker network create dispatcharr-pr3-net
  docker run -d --name dispatcharr-pr3-db --network dispatcharr-pr3-net -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=dispatcharr postgres:17
  docker run -d --name dispatcharr-pr3-redis --network dispatcharr-pr3-net redis:latest
  docker volume create dispatcharr-pr3-webdata
  until docker exec dispatcharr-pr3-db pg_isready -U dispatch >/dev/null 2>&1; do sleep 2; done; echo DB_READY
  docker run -d --name dispatcharr-pr3-web --network dispatcharr-pr3-net -e DISPATCHARR_ENV=modular -e POSTGRES_HOST=dispatcharr-pr3-db -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=dispatcharr -e REDIS_HOST=dispatcharr-pr3-redis -v dispatcharr-pr3-webdata:/data dispatcharr-pr3:local
  for i in $(seq 1 90); do docker exec dispatcharr-pr3-web supervisorctl -c /app/docker/supervisord/supervisorctl.conf status api-uwsgi 2>/dev/null | grep -q RUNNING && echo WEB_READY && break; sleep 2; done
  docker run -d --name dispatcharr-pr3-worker --network dispatcharr-pr3-net -e DISPATCHARR_ENV=modular -e DISPATCHARR_ROLE=worker -e POSTGRES_HOST=dispatcharr-pr3-db -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=dispatcharr -e REDIS_HOST=dispatcharr-pr3-redis -v dispatcharr-pr3-webdata:/data dispatcharr-pr3:local
  for i in $(seq 1 90); do docker exec dispatcharr-pr3-worker supervisorctl -c /app/docker/supervisord/supervisorctl.conf status celery-default 2>/dev/null | grep -q RUNNING && echo WORKER_READY && break; sleep 2; done
  ```
  Expected: `DB_READY`, `WEB_READY`, `WORKER_READY`, each within ~180s. The `web` container passes **no** `DISPATCHARR_ROLE` on purpose — this is the local counterpart of the `test_modular_mode` assertion, covering A2's default. If `WORKER_READY` never prints, check `docker logs dispatcharr-pr3-worker` for the JWT-wait or migrate-check timeout: the likeliest cause is the two containers not actually sharing `dispatcharr-pr3-webdata`, since `SECRET_KEY` is read from `/data/jwt` (D11).
  Run: `docker logs dispatcharr-pr3-web 2>&1 | grep "DISPATCHARR_ROLE="`
  Expected: `🎛️  DISPATCHARR_ROLE=api (DISPATCHARR_ENV=modular)` — the default, not `all`.
  Run: `docker exec dispatcharr-pr3-web supervisorctl -c /app/docker/supervisord/supervisorctl.conf status`
  Expected: exactly three lines — `api-uwsgi`, `daphne`, `nginx`, all `RUNNING`. No `postgres`, `redis` or `celery-*` line at all: they are not in `api.conf`'s include list.
  Run: `docker exec dispatcharr-pr3-worker supervisorctl -c /app/docker/supervisord/supervisorctl.conf status`
  Expected: exactly three lines — `celery-default`, `celery-dvr`, `celery-beat`, all `RUNNING`.
  Run: `docker exec dispatcharr-pr3-worker bash -c 'ps -eo user,ni,args | grep "[c]elery" | head -5'`
  Expected: the Celery processes owned by `root` at nice `5`, with `-l info` on their command lines — A5 and A10's behaviour-preservation, visible.
  Run: `! docker exec dispatcharr-pr3-web pgrep -f celery`
  Expected: exit 0 for the whole command, meaning `pgrep` found nothing — no Celery process in the `api` container. Written as a negated `pgrep` rather than `ps | grep … ; echo $?`, because in a pipeline `$?` is the *last* command's status: a `grep` that matches nothing followed by `head` reports `head`'s success and the check silently always passes.
  Run: `docker rm -f dispatcharr-pr3-web dispatcharr-pr3-worker dispatcharr-pr3-db dispatcharr-pr3-redis; docker network rm dispatcharr-pr3-net; docker volume rm dispatcharr-pr3-webdata`
  Expected: all succeed.

- [ ] **Step 7: Reject the three impossible role/env pairs.**
  Each command captures the container's own status before the pipeline, because `docker run … | tail -8; echo $?` reports `tail`'s exit, not the container's, and `tail` always succeeds.
  Run: `out=$(docker run --rm -e DISPATCHARR_ENV=modular -e DISPATCHARR_ROLE=all dispatcharr-pr3:local 2>&1); rc=$?; echo "$out" | tail -8; echo "exit=$rc"`
  Expected: the "runs its own PostgreSQL and Redis" error and `exit=1`. No `/data` volume is needed, because the guard fires before anything touches it.
  Run: `out=$(docker run --rm -e DISPATCHARR_ENV=aio -e DISPATCHARR_ROLE=api dispatcharr-pr3:local 2>&1); rc=$?; echo "$out" | tail -8; echo "exit=$rc"`
  Expected: the "expects external PostgreSQL and Redis" error and `exit=1`.
  Run: `out=$(docker run --rm -e DISPATCHARR_ENV=aio -e DISPATCHARR_ROLE=worker dispatcharr-pr3:local 2>&1); rc=$?; echo "$out" | tail -8; echo "exit=$rc"`
  Expected: the "expects external PostgreSQL and Redis" error naming `worker`, and `exit=1`. All three guards exist so a misconfiguration fails in one line rather than as a `FATAL` program twenty seconds later, or — for `worker` — as a `migrate --check` loop that times out after five minutes against a database that was never going to be there.

- [ ] **Step 8: Run the touched scenarios from both bash suites against the built image.**
  Run: `docker tag dispatcharr-pr3:local dispatcharr:puid-test`
  Run (foreground, 600000 ms timeout): `bash /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh --skip-build fresh_default </dev/null`
  Expected: exit 0, with the new `supervisorctl status: all eight programs of role 'all' RUNNING` pass line.
  Run (foreground, 600000 ms timeout): `bash /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-puid-pgid.sh --skip-build modular_mode </dev/null`
  Expected: exit 0, with `Modular container defaulted to role api` and `supervisorctl status: all three programs of role 'api' RUNNING`.
  Run: `docker tag dispatcharr-pr3:local dispatcharr:tls-test`
  Run (foreground, 600000 ms timeout): `bash /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3/docker/tests/test-tls-postgres.sh --skip-build modular_full_tls_celery </dev/null`
  Expected: exit 0 — the web container starts through the supervisorctl-based `wait_for_ready`, the Celery container starts with `DISPATCHARR_ROLE=worker` and prints both `Migrations complete` and `starting Celery`, and both TLS banners are seen. This scenario is the one the spec's risk list names, because it is what catches a divergence between the deleted Celery entrypoint and the shared one.
  Do **not** pass `--keep-on-fail` to either suite: the TLS suite reuses one set of container names across all eight scenarios, and the puid suite's keep branch is run-global.
  `--skip-build` on both is what makes the retag above the whole story: each suite otherwise builds its own image, and since PR 1 both do so with `--build-arg REPO_OWNER=d10scot` baked in (`test-puid-pgid.sh:1495`, `test-tls-postgres.sh:982`). Dropping `--skip-build` would therefore still produce a correct image, just a second one — three full builds instead of the one Step 1 already did.

- [ ] **Step 9: Final greps — the D15 gate and the config test.**
  Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr3 && grep -rn "flushdb\|flushall\|_flush_non_celery_keys" scripts/ apps/ core/ dispatcharr/ docker/`
  Expected: exactly one line — `scripts/ci_coverage_backend.sh:26`, the backend coverage harness flushing its own throwaway Redis between labels. That is the carve-out A8 adds to the criterion. Any other hit is a regression: name it in the task report rather than accepting it.
  Run: `uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py`
  Expected: five `OK` lines, `0 failure(s)`.
  Run: `grep -nE '^(logfile|pidfile|childlogdir|file)\s*=' docker/supervisord/*.conf | grep -v '=/run' || echo CLEAN`
  Expected: `CLEAN`.

- [ ] **Step 10: Report.** No commit for this task. In the final report record: which of Steps 1-9 passed; every deviation from an `Expected`; the measured `docker stop` wall time and exit code from Step 5, since nothing pins either today; and, if any container could not be started, say the work is unverified rather than describing it as verified.

## Final report to the orchestrator

Report, in this order:

1. The path of this plan and the task count (12).
2. One line per review finding 1-16, saying how it was resolved and in which task.
3. The twelve spec amendments, by letter, and the task step that applies each (Task 11, Step 6).
4. Any spec requirement with no mapped task (there should be none).
5. Anything that could not be verified from the plan-writing worktree — in particular that Tasks 1 and 12 cannot run until PR 1 is merged and `base-image.yml` has rebuilt `:base` on `main`, and that no container was started or exec'd into while writing this plan.
6. The three follow-ups this PR deliberately does not do:
   - **Modular Celery still runs as root** (A5). Dropping it to `$POSTGRES_USER` needs a one-time recursive chown of `/data/recordings`, `/data/m3us`, `/data/epgs`, `/data/uploads` and `/data/plugins`, because `03-init-dispatcharr.sh`'s chown is non-recursive and existing installs have root-owned files there. File it as an issue; it is a data-migration change, not a supervision one.
   - **`.github/workflows/claude-md-maintenance.md:122`** still lists `entrypoint.aio.sh` among the dead-code items that workflow watches for. Editing it means recompiling its `.lock.yml` with `gh aw compile` and re-linting with zizmor, which this PR should not carry.
   - **`04-check-hwaccel.sh` runs in the `all` and `api` roles only** (A11). From PR 4 the `relay` role is what spawns ffmpeg, so the hardware-acceleration report is printed by a container that never transcodes. PR 4 decides.

