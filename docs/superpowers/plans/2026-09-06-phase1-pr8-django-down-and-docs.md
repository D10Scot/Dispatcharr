# Phase 1 PR 8 — Django-down and Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Phase 1 by proving the two properties the acceptance suite still cannot check —
that a running stream survives the API process going away and that a relay restart is bounded —
and by finalizing every document Phase 1 has made stale, so the spec's Requirements table, Done
log, `CLAUDE.md`, `e2e/COVERAGE.md` and the metrics ledger all say what the tree actually does.

**Architecture:** A new Playwright project, `streaming-split`, owns two tests in one spec file.
Both drive `instance.supervisorctl()` — the fixture method PR 4 added — to stop and start one
supervisord program at a time inside the AIO container, and observe the result only through
client-facing surfaces: a byte stream through nginx, an unauthenticated readiness route, and the
REST row a Celery task writes. Everything else in this PR is documentation: the spec's Requirements
table and Done log get real PR numbers and merge SHAs, `CLAUDE.md` gets the corrections no earlier
PR folded in, and two issues close.

**Tech Stack:** Playwright + TypeScript (`e2e/`), supervisord (`docker/supervisord.d/`), nginx
(`docker/nginx.conf`, read-only here), GitHub Actions (`.github/workflows/e2e-tests.yml`),
`metrics/` (PyYAML validator), `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` § The eight pull
requests › PR 8 — `migration/phase1-django-down-and-docs`.

**Branch:** `migration/phase1-django-down-and-docs` (worktree `.worktrees/phase1-pr8`), off `main`.

---

## Branch base

This branch was cut from PR 7's head, so PR 7's work is present here as ordinary file content:
`apps/proxy/relay_client.py`, `apps/proxy/relay_views.py`, `apps/proxy/relay_urls.py`,
`apps/proxy/internal_base_url.py`, the `^~ /proxy/relay/` block in `docker/nginx.conf`, and
`CLAUDE.md`'s PR 7 corrections.

**PR 8 executes only after PR 7 (#194) has merged to `main`.** Task 1 is the gate: reset this
branch onto `origin/main` before anything else. PR 7 arrives on `main` **squashed**, so:

- **This plan cites no PR 7 commit hash anywhere, and neither may the executor.** After a squash
  merge the hashes on this branch do not exist on `main`; `git merge-base --is-ancestor` answers
  "no" for a PR 7 that has demonstrably merged. Every check in Task 1 is a check on **file
  content**.
- **PR 7's merge SHA is the one hash this PR needs and cannot know at writing time.** Task 1
  reads it from `git log --first-parent origin/main` after the reset, and Task 6 writes it into
  the Requirements table and the Done log. The other six are already known and verified (Task 1,
  step 3).
- **Every file:line below was verified against this worktree before the reset.** Line numbers
  drift; the tree wins. Task 1 re-runs the greps that matter and says what to do with each answer.

---

## Global Constraints

- **This PR changes no product code.** Nothing under `apps/`, `core/`, `dispatcharr/`,
  `frontend/`, `docker/` (other than nothing at all) is edited. The diff is `e2e/`,
  `.github/workflows/e2e-tests.yml`, `metrics/curated/`, `CLAUDE.md`, `docs/`. If a task ever
  needs a product edit, stop and report — that is a different PR.
- **The two supervisord program names are `api-uwsgi` and `relay-uwsgi`**
  (`docker/supervisord.d/api-uwsgi.conf:1`, `relay-uwsgi.conf:1`). `relay-uwsgi` carries
  `stopwaitsecs=20`, `startsecs=5`, `stopsignal=TERM`, `autorestart=true`, `startretries=20`;
  `api-uwsgi` carries `stopwaitsecs=10` and the same rest. An explicitly stopped program is not
  restarted by `autorestart`, which is what makes Scenario A possible at all.
- **The new spec drives `instance.supervisorctl()`, never a subprocess of its own.** No
  `node:child_process` import, and no string literal containing `pgrep`, `docker ` or `manage.py`
  anywhere in the file — those two capabilities have their own allowlists
  (`e2e/tests/guards/allowlist.ts`) and this file must appear on exactly one list,
  `CONTAINER_LIFECYCLE`. Comments may name any of those words; `capabilities.spec.ts` parses, and
  never reads comments.
- **`CONTAINER_LIFECYCLE` is a `toEqual` allowlist, not `toContain`.** Adding the entry without
  the file, or the file without the entry, fails `capabilities.spec.ts` naming the offender. Both
  land in the same task (Task 3).
- **Every `test()` carries exactly one inline tag**, `{ tag: '@contract' }`, in a details object
  written literally at the call site — `tests/guards/tags.spec.ts` fails a tag passed by
  reference, two tags, or none.
- **`e2e/COVERAGE.md` gets its rows in the same PR as the tests** (`e2e/README.md`'s rule 10 and
  `CLAUDE.md` § Testing).
- **A new Playwright project is wired in three places or it has no CI signal**: `projects` in
  `e2e/playwright.config.ts`, the `projects=` JSON list in `.github/workflows/e2e-tests.yml`'s
  `changes` job, and `e2e/package.json`'s script list. `e2e/README.md` § CI says this outright.
- **zizmor stays at zero findings.** `.github/workflows/e2e-tests.yml` is edited (one JSON string)
  and the edit hook runs zizmor on it. No new `uses:` and no new `FROM` in this PR, so no
  supply-chain pin is needed; if one ever were, it is a 40-char SHA with a version comment
  resolved by `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`.
- **Never `--reset`, never `--down`, never touch the shared stacks.** The `streaming-split`
  project does not use `instance.up()`, `restart()`, `recreate()` or `down()` — only
  `supervisorctl()`. `Instance.owned` therefore stays `false` and the fixture's teardown net does
  nothing, which is the intended behaviour here, not an oversight.
- **Every test that stops a program restores it in an unconditional `finally`.** A Playwright
  timeout abandons a test body without running its `finally`, so Task 3's test also re-asserts
  RUNNING at the top of the next test rather than trusting the previous one's cleanup.
- **`metrics/curated/` is validated before every commit that touches it**:
  `python -m metrics.build --validate-only --curated metrics/curated` and
  `scripts/run_metrics_tests.sh`. Status moves forward only, and the four values are `open`,
  `pinned`, `carried`, `fixed`.
- **`git add` and `git commit` run in separate Bash calls**, and the commit message is written
  with the Write tool and passed as `-F <msgfile>` — the pre-commit hook blocks any single call
  containing both verbs, and trips on a heredoc that merely contains them.
- **Every `gh` command carries `--repo D10Scot/Dispatcharr`.** Without it `gh` resolves to
  upstream's public tracker (`docs/agents/issue-tracker.md`).
- **CI label routing.** This PR touches no path under `apps/`, `core/` or `dispatcharr/`, so
  `labels_for_changed_paths()` selects **no backend label**. Task 11 runs all sixteen anyway,
  because the Done criteria are about the tree as a whole and the full set costs about
  thirty-five seconds. The branch is `migration/**`, so `e2e-tests.yml` and `lifecycle-tests.yml`
  both run in **full mode**.
- **`CLAUDE.md` rules that bite even though no product code changes**: no channel state in Python
  memory, no blocking call on a gevent path, `os.posix_spawn` stays, DRF serializers for every
  endpoint, routes in `api_urls.py` and in the spectacular schema, migrations ship with model
  changes, redaction helpers for any URL/header logging. None of them is exercised by this diff;
  they are listed so a task that starts to need one recognises it has left scope.

---

## Design rulings

Each settles something the spec leaves open or states in a way the tree contradicts. They are
binding on the executor; a reviewer checks the plan against them rather than re-deriving them.

1. **A new project, `streaming-split`, not a spec inside `streaming-greybox`.** The spec offers
   both. Only the project works. Stopping `api-uwsgi` takes down a supervisord program the whole
   container shares, which is the same blast radius that put the lifecycle specs in their own
   projects: in CI every matrix project gets its own container
   (`.github/workflows/e2e-tests.yml`), so a project is the only unit that confines the outage. A
   greybox spec would put an API outage inside a container `output-profile-sharing.spec.ts` and
   `vod-redirect-profile.spec.ts` are also using, and `streaming-greybox`'s single worker protects
   against overlap *within* that project only — it says nothing about a spec that leaves
   `api-uwsgi` stopped after a timeout. The project also keeps the container (unlike the
   lifecycle projects, which replace it), so it takes `dependencies: ['bootstrap']` and the admin
   `storageState`, and uses the ordinary `api`/`seed`/`upstream`/`streamClient` fixtures.
2. **One spec file, two tests.** The spec says "second scenario, same spec". One file is also one
   `CONTAINER_LIFECYCLE` allowlist line rather than two. `workers: 1`, `fullyParallel: false` and
   `retries: 0`: attempt 1 mutates container-wide process state, and a retry beginning while the
   previous attempt's `finally` is still bringing `api-uwsgi` back would measure the wrong thing —
   the same reasoning `pristine` and `lifecycle` give for `retries: 0`. `timeout: 600_000`, which
   is **derived, not copied from the streaming projects' 300 s**: each test is a chain of
   sequential poll budgets, and Scenario B's post-restart chain alone sums to 385 s
   (25 + 60 + 120 + 60 + 120). 600 s is that chain plus ~215 s of margin for the two
   `expectRunning` pre-checks and `seed.upstreamM3UAccount`'s own refresh wait — deliberately less
   than those three worst cases summed (~270 s, giving a theoretical ~655 s), because a run in
   which every one of them takes its maximum has already failed for a reason no timeout will
   clarify. What the budget must cover is the ordinary over-budget case, a restart taking 40 s or
   60 s instead of 25 s, which lands near 350 s: that has to fail with the measured `elapsedMs`
   the assertion was written to report, not with a bare Playwright timeout.
3. **The new tune during the outage asserts `500`, and the 500 is deliberately not narrowed.**
   Amendment S7 already establishes the number:
   `ngx_http_auth_request_module` returns 2xx as allow, passes 401 and 403 through, and maps
   *every other outcome* — including an unreachable subrequest upstream — to its own
   `500`. Narrowing would mean `error_page 500 = @something` on nine relay-bound locations, and
   **nginx cannot tell the two 500s apart at that point**: a genuine 500 raised by
   `/_dispatcharr/authorize` and an `api-uwsgi` that is not listening arrive at the same handler
   with the same status. Relabelling both as 503 would tell a player "retry, this is temporary"
   about an authorize-view bug, and every player in the supported set retries a 503 forever. The
   distinction *is* available where an operator can use it — `$upstream_status` in the access log
   carries the subrequest's own code — so the cost of not narrowing is that a client sees 500
   where 503 would have been friendlier, and the fix for that is diagnosis, not a status rewrite.
   Recorded in the spec's § Error handling per hop and in `CLAUDE.md` so the 500 is readable
   rather than mysterious.
4. **The bounded-restart ceiling is asserted against a fresh tune; the same-channel reconnect is
   measured out of band and filed, not asserted.** The spec's own justification for N ≤ 30 s is
   about the process — "`stopwaitsecs=20` plus process start has to fit inside it or the restart
   is not bounded in any useful sense" — and that is exactly what a fresh tune measures. A viewer
   reconnecting to the **same** channel is a different question, and the tree answers it badly:
   - `apps/proxy/live_proxy/views.py`'s `_channel_setup_needed` returns `(False, state, False)`
     for a channel whose metadata says `active`, **without consulting the owner's heartbeat** —
     that check exists only on the unknown-state branch below it. So the reconnecting client
     attaches as a follower to a channel whose owner process no longer exists.
   - `ProxyServer.check_if_channel_exists`, which *does* detect a zombie by the
     `live:worker:<id>:heartbeat` key, is unreachable from that path: `_channel_setup_needed`
     returns before it.
   - `_check_orphaned_metadata` (`apps/proxy/live_proxy/server.py`) is the only sweep that can
     clear it, it runs every 30 s from the cleanup thread, and it declines to clean a channel that
     still has a real client — which a retrying reconnect keeps supplying.
   The worker id is `f"{hostname}:{pid}"`, so a restarted relay never inherits the dead worker's
   identity; the heartbeat key simply expires on its own 30 s TTL. Net effect: a same-channel
   reconnect can take well over the ceiling, in a way no amount of test tuning improves. Task 4
   step 4 measures it once by hand against the running stack, Task 10 files the issue, Task 5
   records it as a COVERAGE row, and Task 6 corrects the spec's § Error handling per hop row that
   currently promises "then a normal reconnect".
   **The measurement must require delivered bytes, not a 200.** A follower on an ownerless channel
   answers 200 with an empty body, so a status-only probe would report a fast reconnect that
   delivered nothing — and that false-fast number would be written into four documents as evidence
   against the very finding they record. Task 4 step 4's loop therefore checks a byte count and
   caps itself. **No number may be written into the COVERAGE row, the issue body, the spec's error
   table or the PR body until that corrected loop has produced one**; if it cannot run, all four
   say "not measured in this environment".
5. **The Celery no-flush observable is an M3U refresh, discriminated by `updated_at`.** D15's
   Celery half exists to catch a start path that runs a blind `flushdb` — the kind that would take
   the broker with it, which `_flush_non_celery_keys` was written to spare. The test dispatches
   `POST /api/m3u/refresh/<id>/` (a 202 that queues `refresh_single_m3u_account`) immediately
   before the restart and, after it, polls the account until `status` is `success` **and**
   `updated_at` has moved. `updated_at` is bumped only by a successful refresh
   (`e2e/fixtures/types.ts`'s own note on the field), so it discriminates "the task ran" from "the
   row was already successful from seeding". The test does not claim to pin the instant the
   message sat in the broker; it claims a task dispatched immediately before a relay restart still
   runs to completion across it, which is the observable form of the rule.
6. **The API-down control assertion uses `/api/accounts/initialize-superuser/` and expects 502.**
   It is the route `scripts/e2e_up.sh` already polls for readiness, it is `AllowAny`, and once
   bootstrap has run it answers `200 {"superuser_exists": true}` (`apps/accounts/api_views.py`).
   With `api-uwsgi` stopped, nginx's `uwsgi_pass unix:/app/uwsgi.sock` fails directly and returns
   **502** — which is both the control assertion (the API really is down, so a passing test cannot
   be a test that never stopped anything) and a free pin on the distinction the spec's error table
   draws: 502 where `uwsgi_pass` fails, 500 where the `auth_request` subrequest fails.
7. **`streaming-split` runs in `e2e-tests.yml`'s matrix, not `lifecycle-tests.yml`.** It needs one
   container, no baseline image and no `docker pull`, so it costs a matrix row rather than a job;
   and the spec's Done criterion names `E2E result`. It joins the single `projects=` list in the
   `changes` job, which both modes read.
8. **The Requirements table is finalized with two named exceptions, not an unqualified "Met".**
   The row "the relay's Redis keys have exactly one writer, and no control-plane code reads them"
   already carries #190 (`Channel.release_stream()`'s `hdel` on the relay's metadata hash). A
   second survives and PR 7's Done grep could not see it, because its directory list is
   `apps/channels/ apps/m3u/ core/ dispatcharr/`: `apps/proxy/tasks.py`'s `fetch_channel_stats`
   builds the live stats payload straight off Redis and runs in the `worker` role — control-plane
   code inside `apps/proxy/`. It is the disabled half of a duplicated beat entry
   (`dispatcharr/settings.py`'s `CELERY_BEAT_SCHEDULE["fetch-channel-statuses"]` ships
   `"enabled": False`), it is tracked as **#193**, and deleting it would touch
   `dispatcharr/settings.py`, whose `_SHARED_PATH_PREFIXES` entry forces all sixteen backend
   labels for a dead-code removal this PR's section does not ask for. Named in the table, not
   fixed here.
9. **The `phase-done` milestone cannot be added by this PR, and the missing `phase-start` can.**
   `metrics/build/curated.py` requires every milestone `sha` to be a full 40-character
   **first-parent commit on `main`** and rejects anything else, and that validator runs in the
   `metrics/**` edit hook and in the commit gate — so PR 8 could not even commit a row naming its
   own merge commit, let alone have it validate. The `phase-done` row therefore goes into the PR
   body with everything but the SHA filled in, exactly as `docs/agents/metrics.md` prescribes for
   a `fixed_in` with no number yet, **and the orchestrator has taken it, with the Done log's last
   cell, as a docs-only follow-up commit on `main` after PR 8 merges** (Task 12 step 4 states both
   and says why neither could ship inside the PR). The *`phase-start`* row for `phase1` is a different matter: it
   is simply missing (`metrics/curated/milestones.yml` declares the `phase1` phase and no
   milestone references it), its commit is `37dbf734c2f440b67613c90311ae283f07810a6f` (#164, the
   spec), and PR 8 adds it.
10. **#87 carries no `wontfix` label today.** `gh issue view 87 --repo D10Scot/Dispatcharr --json
    labels` returns an empty list, so the erroneous label Amendment S4 promised PR 8 would remove
    is already gone. Task 10 re-verifies at execution time and removes it only if it is there; the
    task reports which of the two it found. Both issues still close.
11. **`preemption-dead-code` moves to `fixed` with `fixed_in: 194`.** PR 7's plan allowed its
    executor to defer the ledger edit when the PR number was not yet known; the row is still
    `status: open` on this branch, and #194 is a real, merged-by-then PR. PR 8 makes the move,
    with `status_changed` set to the day the work is done.
12. **`CLAUDE.md`'s `max-requests` sentence overstates the recycle.** It currently says "harakiri
    and a max-requests recycle kill the whole gevent worker, and with it every other in-flight
    request on it". Only harakiri does that. A `max-requests` recycle is a **graceful reload**: the
    worker stops taking new requests, finishes what it holds, and the master waits
    `worker-reload-mercy` — uWSGI's default 60 s, set in neither `docker/uwsgi.ini` nor
    `docker/uwsgi.modular.ini` — before escalating to a kill. The caveat worth keeping is
    narrower and true: uWSGI's gevent plugin waits for request greenlets, not for greenlets an
    application spawned outside a request, unless `gevent-wait-for-hub` is set, and it is not.
13. **`CLAUDE.md`'s counted claims are refreshed only where an instrument in this repo produces
    the number.** `scripts/metrics/collect_architecture.py` is that instrument for
    `reverse_imports_into_proxy` (24 in the text, 29 at PR 7's head — Phase 1 raised it by adding
    `relay_client` callers outside `apps/proxy/`), and the sixteen-label run in Task 11 is the
    instrument for the "~1,787 tests" figure that appears twice. The "367 cross-app imports over
    50 edges, four cycles" sentence is **not** touched: the collector counts a different thing
    (`apps.<x>` → `apps.<y>` statements only, 199 over 39 edges, one cycle), and replacing one
    definition's number with another's would make the sentence wrong in a new way.
14. **Scope: PR 8 is not a cleanup PR.** In scope, because this PR's own work settles them: #87
    and #95 (closed, referencing PR 5), #181 (verified closed by PR 7's merge — its body carries
    `Closes #181`), #190 and #193 (named in the Requirements table). Out of scope, each for one
    reason: **#177** (a pre-existing `makemigrations --check` drift on `main`; this PR edits no
    model), **#178** and **#179** (new E2E coverage for the authorize hop — PR 5's follow-ups,
    not PR 8's two scenarios), **#180** (`03-init` templating, a `docker/` change), **#182**
    (`get_client_ip` trusting `X-Forwarded-For`, a security change with its own blast radius),
    **#183** (`apps.timeshift.tests` log noise, a backend test change), **#186** (`str(e)` in 500
    bodies, labelled `wontfix`), **#187** (`e2e_up.sh`'s partial-environment fallback — this
    plan's test-environment block guards against it rather than fixing the script). Naming them
    here is the deliberate decision not to widen; § Non-goals of the spec calls scope creep the
    fork's named failure mode.
    **Two deliberate additions beyond what the spec's own PR 8 section lists**, recorded here
    because this ruling is where scope decisions live. § Documentation names four `COVERAGE.md`
    rows and Task 5 writes six. The fifth is the SPA three-segment route: PR 2 shipped it with no
    row, § Testing lists it beside the TTFB test, and `e2e/README.md`'s rule 10 makes the row owed
    — leaving one of PR 2's two tests unrecorded would make this PR's reconciliation incomplete on
    purpose. The sixth is the reconnect gap ruling 4 found. Each is one row of prose and neither
    adds work to any other task.

---

## Done criteria (from the spec)

- [ ] **Both new scenarios pass in full-mode CI.** The branch is `migration/**`, so
      `e2e-tests.yml` runs every project including the new one. Locally:
      `npx playwright test --project=streaming-split` with the full variable set from § Test
      environment, green, two tests.
- [ ] **`E2E result` green.** All eight existing matrix projects plus `streaming-split` plus
      `guards` and `upstream`. Locally, Task 11 runs `streaming`, `streaming-greybox`,
      `streaming-split`, `lifecycle` and `guards`; CI says the rest.
- [ ] **`Lifecycle result` green**, including `docker/tests/test-puid-pgid.sh`'s `modular_mode`
      and `role_split` scenarios (Task 11).
- [ ] **`e2e/tests/guards/capabilities.spec.ts` passes with the widened allowlist**:
      `npx playwright test --project=guards`. It fails naming the offender if the new file reaches
      for a capability it did not declare, or if the allowlist names a file that does not use one.
- [ ] **§ Requirements the relay meets or carries is finalized** with real PR numbers and merge
      SHAs for all seven code PRs (Task 6).
- [ ] **The spec's § Done log is filled in** — every one of the seven earlier rows carries a PR
      number and a merge SHA. PR 8's own row carries its PR number (written by Task 12's follow-up
      commit) and the literal `this PR` in the `Merged` column: a merge commit cannot name itself,
      so the orchestrator completes that one cell after merge (Task 6 step 4, Task 12 step 4).
      `this PR` in that cell is the criterion met, not a criterion outstanding.
- [ ] **`CLAUDE.md` corrected**: § Repository and direction lists this spec beside the four
      investigation documents and the Phase 0 spec; the `max-requests` sentence in § Operationally
      is corrected (ruling 12); § Testing names fourteen E2E projects including `streaming-split`;
      the two counted claims in ruling 13 are refreshed; the relay-restart recovery finding is
      recorded (Task 7).
- [ ] **`e2e/COVERAGE.md` carries the missing Phase 1 rows** — time to first byte, the SPA
      three-segment route, Django-down, bounded relay restart, the modular role split, and the
      same-channel reconnect gap (Task 5).
- [ ] **`docs/agents/issue-tracker.md` carries a working `resolveReviewThread` example** (Task 8).
- [ ] **The second `@contract`-on-an-allowlist exception is recorded where the first one is** —
      `e2e/README.md`'s "Tags versus grey-box capabilities" paragraph and
      `e2e/tests/guards/capabilities.spec.ts`'s header both name the new file (Task 3, step 6),
      because the new file's own header asserts that they do.
- [ ] **Issues #87 and #95 are closed**, each with a comment referencing PR 5 (#176) and the test
      that covers it; #181 is verified closed by PR 7 (Task 10).
- [ ] **`python -m metrics.build --validate-only --curated metrics/curated` exits 0** and
      `scripts/run_metrics_tests.sh` is green after Task 9's ledger and milestone edits.

Additional gates this plan owns, in the same spirit:

- [ ] `cd e2e && npx tsc --noEmit` clean.
- [ ] `git diff --name-only origin/main...HEAD` names no file under `apps/`, `core/`,
      `dispatcharr/`, `frontend/` or `docker/` (ruling: this PR changes no product code).
- [ ] All sixteen backend labels green (Task 11) — unchanged, since nothing they cover was
      edited, and the number they report is what Task 7 writes into `CLAUDE.md`.
- [ ] zizmor clean on `.github/workflows/e2e-tests.yml` after Task 2's edit.

---

## Test environment for this worktree

The edit/commit hooks resolve the project directory from the harness, so in a worktree they do not
run tests automatically. Run them yourself:

1. Start a container for this worktree (idempotent). **Run it in the background** — the script does
   not exit after the container is ready. Poll `pg_isready` in a second call and stop it once that
   answers:
   `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr8 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr8 DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.claude/hooks/start-test-container.sh`
   **`DISPATCHARR_TEST_IMAGE` is not optional**: without it the script pulls upstream's image,
   which has no `hypothesis`, and every `apps.proxy.live_proxy.tests` run dies on an import error
   that looks nothing like a missing dependency.
2. After editing any file, run the affected-file hook by hand:
   `echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr8 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr8 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.claude/hooks/run-affected-tests.sh`
   Exit 2 = blocking failure; read the output.
3. Before every commit, run the commit gate by hand:
   `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr8 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr8 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.claude/hooks/pre-commit-tests.sh --git-hook`
4. Backend tests directly: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr8 /dispatcharrpy/bin/python manage.py test --keepdb <label> -v1`
5. Frontend: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/frontend && npm ci && npm test`.
   E2E typecheck: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/e2e && npm ci && npx tsc --noEmit`.
6. **E2E stack for this worktree only. EVERY ONE of the variables below must be exported for
   EVERY command, including the Playwright run itself.** The `lifecycle` project's restart spec
   shells out to `scripts/e2e_up.sh`, and a partially scoped environment falls back to the
   **shared** stack — issue #187, which stopped the shared provider once. Build and bring up with:
   `DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-pr8:local DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr8 DISPATCHARR_E2E_PORT=39191 DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr8-data DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr8-net DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-pr8 DISPATCHARR_E2E_UPSTREAM_PORT=9407 DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 scripts/e2e_up.sh`
   `scripts/e2e_up.sh` silently reuses an existing image tag, so run
   `docker rmi dispatcharr-e2e-pr8:local` before any rebuild. Recreate the provider container with
   `-e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-pr8:8080` or every subprocess-profile test
   fails with "188 bytes then EOF". Run Playwright with the full set:
   `E2E_BASE_URL=http://localhost:39191 E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:9407 E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-pr8:8080 DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-pr8:local DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr8 DISPATCHARR_E2E_PORT=39191 DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr8-data DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr8-net DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-pr8 DISPATCHARR_E2E_UPSTREAM_PORT=9407 DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 npx playwright test --project=<name>`
   **Never pass `--down` or `--reset`**, and never touch the shared `dispatcharr-e2e`,
   `dispatcharr-e2e-g14`, `e2e-upstream` or `dispatcharr-testrunner`. **The shared `e2e-upstream`
   container is currently stopped and is not ours to start.** `-g` patterns match exact titles.
   Playwright counts exclude the `bootstrap` setup test unless stated.
7. If the container cannot start, say so in the task report: the work is then unverified, not
   verified.

**`docker exec … manage.py <x>` in the tasks below abbreviates the step 4 command**, with `<x>`
substituted for `test --keepdb <label> -v1`. Write it out in full every time you run it; the
abbreviation exists so the steps stay readable, not because any part of it is optional.

---

## File Structure

```
e2e/
  playwright.config.ts                    MODIFY  + the streaming-split project
  package.json                            MODIFY  + test:streaming-split, + the echo list
  fixtures/instance.ts                    MODIFY  header: who may import this, now three projects
  fixtures/index.ts                       MODIFY  the `instance` fixture's doc comment and its
                                                  wiring comment name streaming-split too
  tests/guards/allowlist.ts               MODIFY  one CONTAINER_LIFECYCLE entry + its why
  tests/guards/capabilities.spec.ts       MODIFY  header only: two documented @contract
                                                  exceptions now, not one. No assertion changes
  tests/streaming-split/process-restart.spec.ts   NEW  two @contract tests: api-uwsgi down and
                                                  back, relay-uwsgi restarted
  COVERAGE.md                             MODIFY  six rows (five P1, one gap)
  README.md                               MODIFY  Task 2: Projects table row, bootstrap row,
                                                  § CI's project list and its "both projects
                                                  lists" instruction. Task 3: the ADR-0002
                                                  tension paragraph names all three files
.github/workflows/
  e2e-tests.yml                           MODIFY  streaming-split in the changes job's projects
docs/superpowers/specs/
  2026-09-04-phase1-process-split-design.md  MODIFY  § Requirements finalized, § Done log filled,
                                                  § Error handling per hop corrected, Amendment S12
docs/agents/
  issue-tracker.md                        MODIFY  the resolveReviewThread example
metrics/curated/
  defects.yml                             MODIFY  preemption-dead-code -> fixed
  milestones.yml                          MODIFY  + the phase1 phase-start milestone
CLAUDE.md                                 MODIFY  six corrections (Task 7)
docs/superpowers/plans/
  2026-09-06-phase1-pr8-django-down-and-docs.md   NEW  this file
```

---

### Task 1: Reset onto merged `main` and re-verify every anchor

**Files:** none edited. This task produces no commit.
**Interfaces:** Consumes `origin/main`. Produces a verified starting tree, and the two facts every
later task needs: PR 7's merge SHA and the current state of the metrics ledger.

- [ ] **Step 1: Confirm PR 7 merged, by content and not by hash.**
      Run: `git fetch origin && git log --first-parent origin/main --format='%H %s' | head -3`
      Run: `git show origin/main:apps/proxy/relay_client.py | grep -c "def get_relay_control_base_url"`
      Run: `git show origin/main:apps/proxy/relay_views.py | grep -c "def channel_advance_view"`
      Expected: the log's first line names PR 7 (`… (#194)`), and both greps print `1`.
      **If PR 7 has not merged, stop and report.** Nothing below is safe on an unmerged base: the
      Requirements table needs its merge SHA and the Done log needs its row.
- [ ] **Step 2: Reset this branch onto the merged tip.**
      Run: `git status --short`
      Expected: clean. If it is not, stop and report what is uncommitted.
      Run: `git reset --hard origin/main`
      Run: `git log --oneline -1`
      Expected: the same commit step 1 named.
- [ ] **Step 3: Record the seven merge SHAs Task 6 writes into the spec.**
      Run: `git log --first-parent origin/main --format='%h %s' | grep -E "Phase 1 PR [1-7]|\(#16[479]\)|\(#17[356]\)|\(#188\)|\(#194\)"`
      Expected: exactly these, and write them into the task report:

      | Item | PR | Merge SHA |
      |---|---|---|
      | Spec (PR 0) | #164 | `37dbf734` |
      | Supervisor dependency | #167 | `936c742e` |
      | TTFB + SPA-three-segment tests | #169 | `fbc40265` |
      | Supervisord | #173 | `9c9100f0` |
      | Process split | #175 | `c9cf78a6` |
      | Authorize hop | #176 | `ce25bd7e` |
      | Next-source + events | #188 | `ce5c1d44` |
      | Control API | #194 | *(read from step 1)* |

      Six of the eight were verified against `origin/main` while this plan was written; the seventh
      is PR 7's, which step 1 just read. If any of the six disagrees with the tree, **the tree
      wins** — say so in the report and use what `git log` printed.
- [ ] **Step 4: Re-verify the three anchors this PR's tests depend on.**
      Run: `grep -n "async supervisorctl" e2e/fixtures/instance.ts`
      Expected: one hit. This is the method both tests drive; if it is gone, stop and report.
      Run: `grep -n "stopwaitsecs\|startsecs" docker/supervisord.d/relay-uwsgi.conf docker/supervisord.d/api-uwsgi.conf`
      Expected: `relay-uwsgi` 20/5 and `api-uwsgi` 10/5. Task 4's ceiling is derived from the
      first pair; if either has changed, report the new numbers and carry them into Task 4's
      constant and its comment.
      Run: `grep -n "auth_request /_dispatcharr/authorize" docker/nginx.conf | wc -l`
      Expected: a non-zero count (nine at PR 7's head). The 500 in Task 3 depends on
      `/proxy/ts/stream/` being one of them: `grep -n -A2 "location \^~ /proxy/ts/stream/" docker/nginx.conf`
      must show the `auth_request` line directly under it.
- [ ] **Step 5: Re-verify the four documentation anchors.**
      Run: `grep -n "status: open" metrics/curated/defects.yml | grep preemption`
      Expected: one hit — the row Task 9 moves. If it is already `fixed`, Task 9 skips that edit
      and says so.
      Run: `grep -c "phase1" metrics/curated/milestones.yml`
      Expected: `1` — the phase declaration only, no milestone (ruling 9). If a `phase1` milestone
      exists, Task 9 adds nothing and reports what it found.
      Run: `grep -n "| P1 |" e2e/COVERAGE.md | wc -l`
      Expected: `3` (authorize, relay events, relay control API). Task 5 adds to these; if the
      count differs, read the rows before writing new ones so nothing is duplicated.
      Run: `gh issue view 87 --repo D10Scot/Dispatcharr --json state,labels --jq '{state, labels: [.labels[].name]}'`
      Run: `gh issue view 95 --repo D10Scot/Dispatcharr --json state,labels --jq '{state, labels: [.labels[].name]}'`
      Run: `gh issue view 181 --repo D10Scot/Dispatcharr --json state --jq .state`
      Expected: #87 and #95 `OPEN`; #181 `CLOSED` (PR 7's body carries `Closes #181`). Record all
      three. Ruling 10: #87 was label-free when this plan was written — report which you found.

---

### Task 2: Wire the `streaming-split` project

**Files:**
- Modify: `e2e/playwright.config.ts` (the `projects` array, after the `streaming-greybox` entry)
- Modify: `e2e/package.json` (`scripts`)
- Modify: `.github/workflows/e2e-tests.yml` (the `changes` job's `projects=` line)
- Modify: `e2e/README.md` (§ Projects table, the `bootstrap` row, § CI)

**Interfaces:** Produces the project name `streaming-split`, consumed by Task 3's spec file
(through `testDir: './tests/streaming-split'`), by CI, and by the npm script.

- [ ] **Step 1: The project entry.** In `e2e/playwright.config.ts`, insert after the
      `streaming-greybox` object and before `frontend`:
      ```ts
    {
      // Owns one supervisord program at a time: `supervisorctl stop api-uwsgi`
      // and `supervisorctl restart relay-uwsgi` inside the shared container.
      // Its own project, not a spec under `streaming-greybox`, for the reason
      // the lifecycle projects have their own: in CI every matrix project gets
      // its own container, so a project is the only unit that confines an
      // outage. A greybox spec would stop the API process inside a container
      // two other specs are using, and `streaming-greybox`'s single worker
      // protects against overlap *within* that project only — it says nothing
      // about a spec that leaves `api-uwsgi` stopped after a timeout.
      //
      // Unlike the lifecycle projects this one keeps its container, so it can
      // take `bootstrap`'s admin state: nothing here replaces the instance the
      // persisted token describes.
      name: 'streaming-split',
      testDir: './tests/streaming-split',
      dependencies: ['bootstrap'],
      // 600s, and derived rather than copied from the three streaming
      // projects' 300s. Each test here is a chain of sequential poll budgets,
      // and the sum is what has to fit. Scenario B's post-restart chain is
      // 385s: 25s in the restart, 60s waiting for RUNNING, 120s polling for a
      // tune, 60s on the first packet, 120s on the refresh. 600s is that 385s
      // plus ~215s of margin for what precedes it — two `expectRunning`
      // pre-checks at 60s each and `seed.upstreamM3UAccount`, which wraps a
      // refresh wait of its own. That margin is not the sum of those worst
      // cases (they total ~270s, so the theoretical worst case is ~655s); it
      // is deliberately sized for one thing going wrong at a time, because a
      // run in which the pre-checks AND the seeding AND the restart all take
      // their maxima has already failed for a reason no timeout will clarify.
      // The over-budget case that matters is the ordinary one — a restart
      // taking 40s or 60s instead of 25s — and it lands near 350s, well
      // inside this budget, so the assertion fails with the measured
      // `elapsedMs` rather than with a bare "Test timeout of Ns exceeded".
      // Sized above the poll budgets for the same reason `lifecycle` sizes
      // itself above the `instance` fixture's subprocess timeouts.
      timeout: 600_000,
      // One worker and no intra-file parallelism: each test stops a program
      // the whole container shares, which is container-wide state in exactly
      // the sense `streaming-failover` and `dvr` serialise for.
      workers: 1,
      fullyParallel: false,
      // Attempt 1 mutates container-wide process state. A retry beginning
      // while the previous attempt's `finally` is still bringing `api-uwsgi`
      // back would measure the restart of a process that was already
      // restarting — the same reason `pristine` and `lifecycle` set this.
      retries: 0,
      // Required. `adminPage` is an alias of `page`; the admin identity comes
      // from this line, not from the fixture.
      use: { storageState: 'playwright/.auth/admin.json' },
    },
      ```
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/e2e && npx tsc --noEmit`
      Expected: clean.
- [ ] **Step 2: The npm script.** In `e2e/package.json`, add after `test:streaming-greybox`:
      ```json
    "test:streaming-split": "playwright test --project=streaming-split",
      ```
      and extend the `test` script's message so the new population is listed. **No apostrophe
      anywhere in the message**: the existing value is a single-quoted shell string inside a JSON
      string, so the shell idiom for an embedded apostrophe (`'\''`) would put `\'` into the JSON,
      and `\'` is not one of the eight escapes JSON allows — `JSON.parse` throws
      `Bad escaped character`. The wording below says the same thing without one:
      ```json
    "test": "echo 'Pick a population: npm run test:guards | test:pristine | test:seeded | test:streaming | test:streaming-failover | test:streaming-greybox | test:streaming-split | test:frontend | test:dvr | test:lifecycle | test:lifecycle-upgrade | test:lifecycle-restore | test:lifecycle-scheduling — they need different container states and cannot share one invocation. The four lifecycle populations drive the container themselves and must run alone; streaming-split stops and starts one uWSGI program at a time and must run alone too.' && exit 1",
      ```
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/e2e && node -e "JSON.parse(require('fs').readFileSync('package.json','utf8')); console.log('ok')"`
      Expected: `ok`.
- [ ] **Step 3: The CI matrix.** In `.github/workflows/e2e-tests.yml`, in the `changes` job's
      "Decide whether the E2E suite needs to run" step, replace the `projects=` line with:
      ```bash
          projects='["pristine","seeded","streaming","streaming-failover","streaming-greybox","streaming-split","lifecycle","frontend","dvr"]'
      ```
      Nothing else in the workflow changes: the `test` job reads the list through
      `fromJSON(needs.changes.outputs.projects)`, gives every row its own container, and runs
      `npx playwright test --project="$PLAYWRIGHT_PROJECT"` with the project name passed through
      the environment rather than interpolated (the zizmor `template-injection` fix already in
      place).
      Run: `echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.github/workflows/e2e-tests.yml"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr8 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.claude/hooks/run-affected-tests.sh`
      Expected: exit 0, zizmor reporting zero findings. **Exit 2 is blocking** — the repo is at
      zero findings and that is a ratchet.
- [ ] **Step 4: `e2e/README.md` § Projects.** Add a row after `streaming-greybox`:
      ```markdown
| `streaming-split` | The two uWSGI processes restarted independently: `supervisorctl stop api-uwsgi` with a stream running, and `supervisorctl restart relay-uwsgi` with a Celery task queued. Long timeouts, one worker, no retries — **must be run alone locally**: in CI each matrix job gets its own container, but locally all projects share one, and this project takes the API process away for the length of a test. It keeps its container (unlike the four lifecycle projects), so it depends on `bootstrap` like its streaming siblings |
      ```
      and extend the `bootstrap` row's dependency list from
      `` `seeded`, `streaming`, `streaming-failover`, `streaming-greybox`, `frontend` and `dvr` ``
      to
      `` `seeded`, `streaming`, `streaming-failover`, `streaming-greybox`, `streaming-split`, `frontend` and `dvr` ``.
- [ ] **Step 5: `e2e/README.md` § CI.** In the paragraph beginning "`.github/workflows/e2e-tests.yml`
      builds the AIO image once", add `streaming-split` to the listed matrix, and correct the
      instruction below it, which says "add it to **both** `projects` lists in that job" — there
      is one list in that job today, and telling a reader to find a second one sends them looking
      for something that is not there:
      ```markdown
**That project list is no longer hardcoded in the `test` job** — it is built by
the `changes` job and consumed as `fromJSON(needs.changes.outputs.projects)`,
so full mode can extend it. **If you add another project to
`playwright.config.ts`, add it to the `projects` list in that job** (unless it
belongs in `lifecycle-tests.yml` instead — see `lifecycle-upgrade` below).
There is one list, read by both modes; `streaming-split` was the first project
added after it stopped being two. Nothing wires new projects in automatically,
and a project in neither place gets no CI coverage and no failure signal.
      ```
- [ ] **Step 6: Commit.** Write
      `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr8-t2.txt`:
      ```
      test(phase1-pr8): a streaming-split project for the process-restart scenarios

      Its own project rather than a spec under streaming-greybox: in CI every
      matrix project gets its own container, so a project is the only unit
      that confines an api-uwsgi outage. It keeps its container, unlike the
      four lifecycle projects, so it depends on bootstrap and uses the
      ordinary fixtures.

      Wired in all three places the README names -- playwright.config.ts,
      the changes job's projects list, and package.json -- and the README's
      own instruction to edit "both projects lists" is corrected to the one
      list that exists.

      Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `e2e/playwright.config.ts e2e/package.json .github/workflows/e2e-tests.yml e2e/README.md`
      in one Bash call, then commit with `-F` in a separate call.

---

### Task 3: Scenario A — the API process goes away

**Files:**
- Create: `e2e/tests/streaming-split/process-restart.spec.ts`
- Modify: `e2e/tests/guards/allowlist.ts` (`CONTAINER_LIFECYCLE.allow`)
- Modify: `e2e/fixtures/instance.ts` (the "WHO MAY IMPORT THIS" header)
- Modify: `e2e/fixtures/index.ts` (the `instance` fixture's doc comment and wiring comment)

**Interfaces:**
Consumes `instance.supervisorctl(argv: string[]): Promise<ManageResult>`,
`lockedProfile(api, name)`, `newStreamClient(baseURL)`, `withDeadline(promise, ms, what)`,
`seed.upstreamChannel(scenario, opts)`, `upstream.scenario({channels, rate})`,
`streamClient.open/readPackets/close`, `expectTsAligned`, `TS_PACKET_SIZE`, `StreamStatusError`.
Produces the file `tests/streaming-split/process-restart.spec.ts`, referenced by the allowlist.

- [ ] **Step 1: Widen the allowlist, and watch it fail.** In `e2e/tests/guards/allowlist.ts`, add
      to `CONTAINER_LIFECYCLE.allow`, after the four lifecycle entries:
      ```ts
    // Stops and starts one supervisord program at a time (`api-uwsgi`,
    // `relay-uwsgi`) through `instance.supervisorctl()`. It never calls
    // `up`/`restart`/`recreate`/`down`, so it neither replaces nor destroys
    // the container — but taking the API process away is container-wide state
    // in the same sense, which is why it has its own project and its own CI
    // container.
    'tests/streaming-split/process-restart.spec.ts',
      ```
      and extend the capability's `why` so a reviewer sees both shapes:
      ```ts
  why: 'Restarts, replaces and upgrades the container, or stops and starts one supervisord program inside it — the subject of the lifecycle and streaming-split projects, and meaningless once the relay is a separate process.',
      ```
      Run the guards with the full variable set from § Test environment step 6:
      `npx playwright test --project=guards`
      **Expected: FAIL**, `capabilities.spec.ts` reporting that the allowlist names a file that
      does not use the capability (the `toEqual` compares the allowlist against the files actually
      found). That failure is the point: it proves the guard is live before the file exists.
- [ ] **Step 2: Write the spec file's header and Scenario A.** Create
      `e2e/tests/streaming-split/process-restart.spec.ts`:
      ```ts
/**
 * The two uWSGI processes restart independently (Phase 1 PR 8).
 *
 * COVERAGE: Streaming — Django down; Lifecycle — bounded relay restart (P1).
 *
 * Runs alone in its own project. Each test takes one supervisord program away
 * for part of its run; `e2e/fixtures/instance.ts`'s header and
 * `playwright.config.ts`'s project comment say why that needs a container of
 * its own rather than a single worker inside an existing project.
 *
 * ---------------------------------------------------------------------------
 * WHY @contract, ON AN ALLOWLISTED CAPABILITY
 * ---------------------------------------------------------------------------
 * ADR-0002 says anything on `tests/guards/allowlist.ts` is
 * `@characterization` by construction, because those calls stop meaning
 * anything once the relay is its own process. This file is the second
 * exception, and it is the opposite case: the relay IS its own process here,
 * and the promise under test — an established stream is not disturbed by the
 * control plane going away, and a relay restart is bounded — is exactly what
 * a Go relay in Phase 2 must also keep. `supervisorctl` is the vocabulary,
 * not the subject. `tests/streaming-greybox/nginx-stream-buffering.spec.ts`
 * carries the same argument for `SUBPROCESS`; `e2e/README.md` records both.
 *
 * ---------------------------------------------------------------------------
 * WHAT AN OPERATOR SEES WHILE DJANGO IS DOWN, AND WHY THE NEW TUNE IS A 500
 * ---------------------------------------------------------------------------
 * Since Phase 1 PR 5, PR 6 and PR 7 the control plane is on more paths than
 * the authorize hop, and all of them fail together:
 *
 *  - a new tune  — nginx's `auth_request` subrequest to `api-uwsgi` cannot be
 *    served. `ngx_http_auth_request_module` allows 2xx, passes 401 and 403
 *    through, and maps everything else to its own 500 — so the client sees
 *    500, not the 502/504 a failed `uwsgi_pass` gives. That is why the probe
 *    below asserts 502 on an ordinary `/api/` route and 500 on a tune in the
 *    same outage: two different failure sites, two different codes.
 *  - a failover on a channel already running — `next_source()` and
 *    `release_source()` are the two synchronous control-plane calls, each
 *    (2 s connect + 5 s read) with one retry and a 0.1 s delay, so each can
 *    hold the channel's main-loop greenlet for ~14 s (spec Amendment S10,
 *    point 8). The failover then falls back to the candidate list cached at
 *    channel start — stale and unenforced — and posts a `channel_error` with
 *    reason `degraded_failover` once Django answers again.
 *  - every `relay_client` call from the control plane — but those originate
 *    in the process that is down, so they simply do not happen. Their budgets
 *    matter in the other direction (a relay outage): (1, 2) on the tune path,
 *    (2, 5) for admin reads and stops, (2, 20) for `advance`, no retries.
 *  - events — `emit_event` is fire-and-forget on a greenlet, so a transition
 *    during the outage is lost, logged once at the start and once on recovery
 *    ("Relay events reachable again after an outage"). Nothing on the byte
 *    path waits for it.
 *
 * This file asserts the first of those four; the other three are covered by
 * unit tests PR 6 shipped (`apps/proxy/live_proxy/tests/test_try_next_stream.py`)
 * and are described here so the numbers live beside the scenario that
 * motivates them.
 */
import {
  test,
  expect,
  StreamStatusError,
  TS_PACKET_SIZE,
  expectTsAligned,
} from '../../fixtures';
import type { Instance, M3uAccount } from '../../fixtures';
import { lockedProfile, newStreamClient, withDeadline } from '../streaming/helpers';

/**
 * nginx's own readiness route (`scripts/e2e_up.sh` polls it), `AllowAny`, and
 * served by the API process through `location ^~ /api/`. Once `bootstrap` has
 * run it answers 200; with `api-uwsgi` stopped, `uwsgi_pass` to the unix
 * socket fails and nginx answers 502.
 */
const API_PROBE = '/api/accounts/initialize-superuser/';

/** supervisord reports RUNNING once a program has stayed alive `startsecs=5`. */
const RUNNING_TIMEOUT_MS = 60_000;

async function expectRunning(
  instance: Instance,
  program: string,
  message: string
): Promise<void> {
  // Polled, not asserted once: both uWSGI programs run through
  // `wait-for-stores.sh`, so supervisord can report RUNNING before the store
  // waits finish — the same reasoning `tests/lifecycle/restart-persistence.spec.ts`
  // records at its own status polls.
  await expect
    .poll(async () => (await instance.supervisorctl(['status', program])).stdout, {
      timeout: RUNNING_TIMEOUT_MS,
      intervals: [1_000],
      message,
    })
    .toMatch(/RUNNING/);
}

/**
 * Open a stream and report the outcome as a string.
 *
 * Nothing is rethrown. `expect.poll` fails the test on the first throw from
 * its callback rather than retrying, so a transient connection reset while
 * uWSGI finishes recycling would end the test outright instead of being
 * retried like the status beside it. Every outcome becomes a string, the
 * budget covers all of them, and the failure message prints the last one —
 * `expect.poll`'s own `message` is typed `string`, not a callback, so the
 * reason has to travel in the polled value.
 */
async function openOutcome(
  client: ReturnType<typeof newStreamClient>,
  path: string
): Promise<string> {
  try {
    await client.open(path);
    return 'ok';
  } catch (error) {
    if (error instanceof StreamStatusError) return `HTTP ${error.status}`;
    return String(error);
  }
}

test(
  'a running stream outlives the API process, and a new tune answers 500 until it is back',
  { tag: '@contract' },
  async ({ instance, api, seed, upstream, streamClient, request, baseURL }) => {
    // Everything is seeded before the API goes away: with `api-uwsgi` stopped
    // there is no REST surface at all, so a test that seeded lazily would fail
    // on its own setup and report it as the product's failure.
    await expectRunning(instance, 'api-uwsgi', 'api-uwsgi was not RUNNING before this test began');
    await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi was not RUNNING before this test began');

    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'split running', tvgId: 'split-running.e2e', logo: null },
        { id: 2, name: 'split new tune', tvgId: 'split-new-tune.e2e', logo: null },
      ],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel: running } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    // A second channel, never tuned, so the blocked request below is a genuine
    // new tune rather than a second client on a channel the relay already
    // serves. nginx runs `auth_request` either way; using a fresh channel
    // removes the objection that it might not have.
    const { channel: fresh } = await seed.upstreamChannel(scenario, {
      channelIds: [2],
      streamProfileId: proxy.id,
    });

    await streamClient.open(`/proxy/ts/stream/${running.uuid}`);
    expectTsAligned(await streamClient.readPackets(1));

    let stopped = false;
    try {
      await instance.supervisorctl(['stop', 'api-uwsgi']);
      stopped = true;

      // Control assertion, first: a test that never actually stopped anything
      // passes everything below it. 502, not 500 — `uwsgi_pass` failing
      // directly on an `/api/` location, which is the distinction the tune
      // assertion completes.
      await expect
        .poll(async () => (await request.get(API_PROBE)).status(), {
          timeout: 30_000,
          intervals: [500],
          message: 'the API process was stopped but nginx still answered its readiness route',
        })
        .toBe(502);

      // (a) The established stream is undisturbed. Nothing on the byte path
      // calls Django once a stream runs.
      const during = await withDeadline(
        streamClient.readPackets(20),
        60_000,
        'the already-open stream during the API outage'
      );
      expect(during.byteLength).toBe(20 * TS_PACKET_SIZE);
      expectTsAligned(during);

      // (b) A new tune is refused, and the refusal is nginx's own 500.
      const blocked = newStreamClient(baseURL!);
      const outcome = await openOutcome(blocked, `/proxy/ts/stream/${fresh.uuid}`);
      await blocked.close();
      expect(
        outcome,
        'with api-uwsgi stopped, the auth_request subrequest fails and nginx reports its own ' +
          'error: 500, not the 502/504 a direct uwsgi_pass failure gives (spec Amendment S7)'
      ).toBe('HTTP 500');
    } finally {
      if (stopped) await instance.supervisorctl(['start', 'api-uwsgi']);
    }

    await expectRunning(instance, 'api-uwsgi', 'api-uwsgi did not return to RUNNING');
    await expect
      .poll(async () => (await request.get(API_PROBE)).status(), {
        timeout: RUNNING_TIMEOUT_MS,
        intervals: [1_000],
        message: 'the API process came back but never served its readiness route',
      })
      .toBe(200);

    // (c) A new tune succeeds again.
    const resumed = newStreamClient(baseURL!);
    await expect
      .poll(async () => openOutcome(resumed, `/proxy/ts/stream/${fresh.uuid}`), {
        timeout: RUNNING_TIMEOUT_MS,
        intervals: [2_000],
        message: 'no tune succeeded after api-uwsgi came back',
      })
      .toBe('ok');
    expectTsAligned(await withDeadline(resumed.readPackets(1), 30_000, 'the resumed tune'));
    await resumed.close();

    // (d) D15, the observable form: restarting the control plane left the
    // relay's channel state in Redis alone. If any start path still flushed
    // DB 0, this channel's metadata, chunks and client set would have gone
    // with it and these packets would never arrive.
    const after = await withDeadline(
      streamClient.readPackets(20),
      60_000,
      'the already-open stream after the API process came back'
    );
    expect(after.byteLength).toBe(20 * TS_PACKET_SIZE);
    expectTsAligned(after);
    await streamClient.close();
  }
);
      ```
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/e2e && npx tsc --noEmit`
      Expected: clean. `M3uAccount` is imported here and first used by Task 4; that is fine and
      needs no hedge — `e2e/tsconfig.json` sets neither `noUnusedLocals` nor
      `noUnusedParameters`, so an unused type import is not an error and the two tasks stay
      separate. `Instance` is used by `expectRunning`'s signature. **Do not import `ApiClient`**:
      `api` arrives destructured and already typed, and `api.json<M3uAccount>(…)` needs no
      hand-written client type.
- [ ] **Step 3: Run the guards, which must now pass.**
      Run, with the full variable set: `npx playwright test --project=guards`
      Expected: green. `capabilities.spec.ts` now finds exactly the five files the
      `CONTAINER_LIFECYCLE` allowlist names, and `tags.spec.ts` finds one inline tag on the new
      test. If `capabilities.spec.ts` reports the new file under `SUBPROCESS` or
      `CONTAINER_INTROSPECTION`, a string literal in the file contains `pgrep`, `docker ` or
      `manage.py` — move it into a comment.
- [ ] **Step 4: Run the new project.**
      Run, with the full variable set: `npx playwright test --project=streaming-split`
      Expected: 1 passed (Task 4 adds the second). If the 500 arrives as something else, **do not
      change the assertion** — record the observed status, re-read
      `docker/nginx.conf`'s `location ^~ /proxy/ts/stream/` block, and report: Amendment S7 is a
      claim about this exact configuration and a different number means the configuration changed.
      Afterwards, confirm the container was left whole:
      Run: `docker exec dispatcharr-e2e-pr8 supervisorctl -c /app/docker/supervisord/supervisorctl.conf status`
      Expected: every program RUNNING.
- [ ] **Step 5: Update the two fixture headers that say "lifecycle projects only".** In
      `e2e/fixtures/instance.ts`, the WHO MAY IMPORT THIS paragraph opens with exactly one line,
      and it is already wrong on its own terms — there are four lifecycle projects, not two:
      ```
 * Only the two lifecycle projects — `e2e/tests/lifecycle/`. Nothing else.
      ```
      Replace that single line with:
      ```
 * Only the four lifecycle projects — `e2e/tests/lifecycle/` — and the
 * `streaming-split` project, which uses `supervisorctl()` alone. Nothing else.
 *
 * The two are not the same risk. A lifecycle spec stops, replaces and
 * destroys the container every other project shares, and
 * `scripts/e2e_up.sh`'s `destroy()` removes the shared network and the
 * `e2e-upstream` provider with it. `streaming-split` never calls
 * `up`/`restart`/`recreate`/`down` at all: it stops and starts one
 * supervisord program inside a container that stays. That is a smaller blast
 * radius and still a container-wide one — the API process is gone for every
 * test sharing the instance while it is stopped — which is why it too runs in
 * a project of its own with its own CI container, and why it is on the same
 * allowlist.
      ```
      and in `e2e/fixtures/index.ts`, change the `instance: Instance` doc line
      "**lifecycle projects only.**" to
      "**lifecycle and `streaming-split` projects only.**", and the fixture-wiring comment
      "Lifecycle projects only — `instance.ts`'s header says why" to
      "Lifecycle and `streaming-split` projects only — `instance.ts`'s header says why". Leave the
      rest of both comments untouched; nothing about the teardown net changes, and
      `streaming-split` never sets `owned`.
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/e2e && npx tsc --noEmit`
      Expected: clean.
- [ ] **Step 6: Record the second `@contract`-on-an-allowlist exception, in both places that
      claim there is one.** The new file's header says "`e2e/README.md` records both", and two
      files today say otherwise.

      In `e2e/README.md`, in the paragraph beginning "**Tags versus grey-box capabilities — an
      open ADR-0002 follow-up.**", replace its last two sentences ("Recorded here rather than
      retagged unilaterally — resolving it either way … not a side effect of this goal's tests.")
      with:
      ```markdown
Two more files now sit in the same position, each arguing its case in its own header rather than
silently: `streaming-greybox/nginx-stream-buffering.spec.ts` (on `SUBPROCESS`, because it reads the
resolved nginx config, while what it pins — `uwsgi_buffering off` on every relay-bound location —
is a promise any reimplementation must keep) and `streaming-split/process-restart.spec.ts` (on
`CONTAINER_LIFECYCLE`, because `supervisorctl` is the only vocabulary for "the API process is
down", while what it pins — an established stream is undisturbed by the control plane going away,
and a relay restart is bounded — is exactly what a Go relay in Phase 2 must also keep). All three
are recorded here rather than retagged unilaterally: resolving the tension either way (loosen the
ADR's claim, or retag the files and add a cross-check guard) is a call for whoever owns ADR-0002
next, not a side effect of the goal or phase that happened to add the third.
      ```

      In `e2e/tests/guards/capabilities.spec.ts`, amend the header sentence that names one
      exception:
      ```ts
 * Four capabilities, four allowlists, in `./allowlist.ts`. Everything on those
 * lists is normally `@characterization`: they are the calls that stop meaning
 * anything once the relay is its own process. Two exceptions document
 * themselves in-file — see `tests/streaming-greybox/nginx-stream-buffering.spec.ts`'s
 * own header for why it's `@contract` despite being `SUBPROCESS`-listed, and
 * `tests/streaming-split/process-restart.spec.ts`'s for why it's `@contract`
 * despite being `CONTAINER_LIFECYCLE`-listed. `e2e/README.md`'s "Tags versus
 * grey-box capabilities" paragraph records the open ADR-0002 follow-up behind
 * both.
      ```
      This is a comment-only edit to a guard file: **no assertion, allowlist or detector changes.**
      Run, with the full variable set: `npx playwright test --project=guards`
      Expected: green, four tests, unchanged.
- [ ] **Step 7: Commit.** Write
      `…/scratchpad/pr8-t3.txt`:
      ```
      test(phase1-pr8): a stream outlives the API process; a new tune is a 500

      Scenario A of the spec's PR 8: stop api-uwsgi with a stream running,
      assert the bytes keep arriving, assert a new tune answers 500 -- nginx's
      own error for an auth_request subrequest it cannot serve, not the
      502/504 a direct uwsgi_pass failure gives -- then start api-uwsgi and
      assert a new tune succeeds and the original stream is still flowing.

      The last assertion is D15 in observable form: nothing flushes Redis on a
      start path, so a control-plane restart leaves the relay's channel state
      alone.

      The 502 probe on /api/accounts/initialize-superuser/ is the control: a
      test that never actually stopped anything would pass every other
      assertion in the file.

      The file is the second @contract test on a grey-box allowlist, so the
      two places that claim there is one exception -- the README's ADR-0002
      follow-up paragraph and capabilities.spec.ts's header -- now name both.
      Comment-only in the guard file.

      Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `e2e/tests/streaming-split/process-restart.spec.ts e2e/tests/guards/allowlist.ts e2e/tests/guards/capabilities.spec.ts e2e/fixtures/instance.ts e2e/fixtures/index.ts e2e/README.md`,
      then commit with `-F`.

---

### Task 4: Scenario B — the relay restart is bounded

**Files:**
- Modify: `e2e/tests/streaming-split/process-restart.spec.ts` (second test, same file)

**Interfaces:** Consumes everything Task 3 imported plus `seed.upstreamM3UAccount(scenario)`,
`api.get`/`api.post`/`api.json<T>`, and the `M3uAccount` type. Produces no new symbol.

- [ ] **Step 1: Add the ceiling constant and its derivation**, beside `RUNNING_TIMEOUT_MS`:
      ```ts
/**
 * The spec's ceiling for a bounded relay restart, and its own justification:
 * "`stopwaitsecs=20` plus process start has to fit inside it or the restart is
 * not bounded in any useful sense". `docker/supervisord.d/relay-uwsgi.conf`
 * carries `stopwaitsecs=20` and `startsecs=5`, so 25s is the configured worst
 * case and 30s is the budget it has to fit inside. Measured from the moment
 * the restart command is issued, not from when it returns.
 *
 * What this ceiling covers is the *process*: the relay serving tunes again.
 * A viewer reconnecting to the SAME channel is a different question with a
 * worse answer — `_channel_setup_needed` (apps/proxy/live_proxy/views.py)
 * returns "no setup needed" for a channel whose metadata still says `active`
 * without consulting the dead owner's heartbeat, so the reconnecting client
 * attaches as a follower to a channel nobody owns, and only
 * `_check_orphaned_metadata`'s 30s sweep can clear it — and that sweep
 * declines to clean a channel that still has a live client, which a retrying
 * reconnect keeps supplying. Recorded in `e2e/COVERAGE.md` and filed rather
 * than asserted here; this test tunes a channel that was not running when the
 * relay went away.
 */
const RELAY_RESTART_CEILING_MS = 30_000;
      ```
- [ ] **Step 2: Write the test.** Two things about it are deliberate and would otherwise be
      "simplified" away:

      **The refresh wait is hand-rolled, and must stay hand-rolled.** `fixtures/wait.ts` exports
      `Waiter.m3uRefreshComplete(accountId, options)`, which already does the baseline read, the
      `POST /api/m3u/refresh/<id>/` and the terminal-status discrimination — and it must not be
      used here. Its phase 1 **re-fires the trigger** up to `M3U_MAX_RETRIGGERS` times at
      `M3U_RETRIGGER_INTERVAL_MS`, a workaround for the task-lock race in
      D10Scot/Dispatcharr#59. A retrigger fired *after* the restart would dispatch a brand-new
      task and the test would then prove that Celery works now, not that the task queued before
      the restart survived it — a tautology that passes forever. The test therefore triggers once,
      itself, and polls a plain `GET`.

      **`seed.upstreamM3UAccount` and `seed.upstreamChannel` are used against the same scenario,
      which no existing spec does.** It is safe, and the reason is worth stating so a failure here
      reads as a finding rather than a mystery: `seed.stream()` creates rows with
      `m3u_account: null` and `stream_hash: null`, so the account's refresh — which reconciles and
      ages out *its own* streams by hash — never reaches the channel's stream, and `Stream.url`
      carries no unique constraint, so the account's catalogue may hold the same upstream URL
      without colliding. The two provider channels (`id: 1` and `id: 2`) keep the streaming half
      away from the refresh's catalogue in any case.

      Append to the same file:
      ```ts
test(
  'a relay restart is bounded, and leaves a Celery task queued across it to finish',
  { tag: '@contract' },
  async ({ instance, api, seed, upstream, streamClient, baseURL }) => {
    await expectRunning(instance, 'api-uwsgi', 'api-uwsgi was not RUNNING before this test began');
    await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi was not RUNNING before this test began');

    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'split relay running', tvgId: 'split-relay-running.e2e', logo: null },
        { id: 2, name: 'split relay after', tvgId: 'split-relay-after.e2e', logo: null },
      ],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    // An M3U account is the Celery half: refreshing one is a real queued task
    // whose completion is visible over REST. Seeded (and refreshed) before
    // anything else so the create-time group refresh has settled and the
    // account's task lock is free by the time the test triggers its own.
    const account = await seed.upstreamM3UAccount(scenario);
    const { channel: running } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const { channel: after } = await seed.upstreamChannel(scenario, {
      channelIds: [2],
      streamProfileId: proxy.id,
    });

    await streamClient.open(`/proxy/ts/stream/${running.uuid}`);
    expectTsAligned(await streamClient.readPackets(1));
    // Printed for Task 11's hand-run same-channel reconnect measurement, which
    // needs a channel this project left streaming and has no other way to
    // learn its uuid.
    console.log(`[relay-restart] channel ${running.uuid} is streaming before the restart`);

    const before = await api.json<M3uAccount>(
      await api.get(`/api/m3u/accounts/${account.id}/`),
      `M3U account ${account.id} before the relay restart`
    );

    const triggered = await api.post(`/api/m3u/refresh/${account.id}/`, {});
    expect(
      triggered.status(),
      'the refresh must be queued before the restart, or there is nothing to survive it'
    ).toBe(202);

    const restartBegan = Date.now();
    await instance.supervisorctl(['restart', 'relay-uwsgi']);
    console.log(
      `[relay-restart] supervisorctl restart returned after ${Date.now() - restartBegan}ms`
    );

    // The running stream died with the process it was served by. Closing the
    // client here is bookkeeping, not an assertion: nothing processed its
    // disconnect, so its entry stays in the channel's client set until the
    // relay's own ghost-client sweep removes it.
    await streamClient.close();

    await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi did not return to RUNNING');

    // The bounded half: a tune the relay has never served answers with real,
    // aligned TS bytes inside the ceiling.
    const client = newStreamClient(baseURL!);
    await expect
      .poll(async () => openOutcome(client, `/proxy/ts/stream/${after.uuid}`), {
        // Deliberately above the ceiling. The assertion below is on the
        // measured number, so an over-budget restart fails with the number it
        // took rather than with a bare poll timeout — the shape
        // `tests/streaming/time-to-first-byte.spec.ts` uses.
        timeout: 120_000,
        intervals: [1_000],
        message: 'the relay never served a tune after the restart',
      })
      .toBe('ok');
    const packet = await withDeadline(
      client.readPackets(1),
      60_000,
      'the first TS packet after the relay restart'
    );
    const elapsedMs = Date.now() - restartBegan;
    console.log(
      `[relay-restart] first TS byte ${elapsedMs}ms after the restart began ` +
        `(ceiling ${RELAY_RESTART_CEILING_MS}ms)`
    );
    expect(packet.byteLength).toBe(TS_PACKET_SIZE);
    expectTsAligned(packet);
    expect(
      elapsedMs,
      `the relay served its first byte ${elapsedMs}ms after the restart began; the ceiling is ` +
        `${RELAY_RESTART_CEILING_MS}ms (stopwaitsecs=20 + startsecs=5)`
    ).toBeLessThanOrEqual(RELAY_RESTART_CEILING_MS);
    await client.close();

    // D15's Celery half: the task dispatched a moment before the restart still
    // ran to completion. A blind flush on any start path would take the broker
    // and the result backend with it — they share Redis DB 0 with the relay's
    // channel state. `updated_at` is bumped only by a successful refresh, so
    // it discriminates "the task ran" from "the row was already successful".
    await expect
      .poll(
        async () => {
          const body = await api.json<M3uAccount>(
            await api.get(`/api/m3u/accounts/${account.id}/`),
            `M3U account ${account.id} after the relay restart`
          );
          return `${body.status}:${body.updated_at === before.updated_at ? 'unchanged' : 'bumped'}`;
        },
        {
          timeout: 120_000,
          intervals: [2_000],
          message:
            'the refresh queued before the restart never completed. If it sits at the ' +
            'pre-trigger status forever, the create-time task lock was still held when it ' +
            'was triggered (D10Scot/Dispatcharr#59) rather than the restart having eaten it',
        }
      )
      .toBe('success:bumped');
  }
);
      ```
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/e2e && npx tsc --noEmit`
      Expected: clean, and the `M3uAccount` type import Task 3 added is now used.
- [ ] **Step 3: Run the project.**
      Run, with the full variable set: `npx playwright test --project=streaming-split`
      Expected: 2 passed. **Record both logged numbers** — the `supervisorctl restart` duration and
      the first-byte elapsed — in the task report; Task 5, Task 6 and the PR body all quote the
      second one.
      **If `elapsedMs` exceeds the ceiling**, do not raise the constant silently. Report the
      number, and use step 4's measurement below to separate the stop from the start; say
      in the report which half exceeded its configured window. A ceiling the product misses is a
      finding the spec asked this PR to produce, not a constant to tune.
- [ ] **Step 4: Measure the same-channel reconnect by hand, now, while the stack is up.** This
      is the number Task 5, Task 6, Task 10 and the PR body all quote, and it is taken here rather
      than in the verification task because Tasks 5, 6 and 10 all write before that task runs. It
      is measured out of band, rather than asserted in the test, precisely because ruling 4 says it
      is not assertable. **The measurement must require bytes, not a status code.** A follower attached to
      an ownerless channel is exactly the case that answers **200 with an empty body**, so
      `curl -f` — which fails only on HTTP ≥ 400 — would exit 0 and report a reconnect that
      delivered nothing. That false-fast number would then be written into three documents as
      evidence that ruling 4's mechanism does not bite, retracting a correct finding. The loop is
      also capped, so the opposite case ends with a statement instead of hanging this task.

      Take the uuid from Scenario B's `[relay-restart] channel` log line (step 2 prints it for this
      purpose; the project run leaves the channel seeded but no longer streaming, so the
      script below re-establishes a viewer first). Run in one shell:
      ```bash
      UUID=<channel uuid from the [relay-restart] channel log line>
      BASE=http://localhost:39191
      PROBE=/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr8-reconnect-probe.bin
      CAP=300
      # A viewer, so the relay is genuinely serving this channel when it dies —
      # the state the reconnect is about. It ends on its own with the process.
      curl -s --max-time 600 -o /dev/null "$BASE/proxy/ts/stream/$UUID" &
      VIEWER=$!
      sleep 15
      # START goes BEFORE the restart, matching the test's `restartBegan`.
      # `supervisorctl restart` blocks through the stop (stopwaitsecs=20) and
      # the start (startsecs=5), so taking the clock after it would silently
      # exclude ~25s that the in-test number includes -- and the two numbers
      # are quoted side by side.
      START=$(date +%s)
      docker exec dispatcharr-e2e-pr8 supervisorctl -c /app/docker/supervisord/supervisorctl.conf restart relay-uwsgi
      kill "$VIEWER" 2>/dev/null || true
      GOT=0
      while [ $(( $(date +%s) - START )) -lt "$CAP" ]; do
        rm -f "$PROBE"
        curl -s --max-time 10 --range 0-1879 -o "$PROBE" "$BASE/proxy/ts/stream/$UUID" || true
        if [ -f "$PROBE" ] && [ "$(wc -c < "$PROBE")" -ge 1880 ]; then GOT=1; break; fi
        sleep 2
      done
      ELAPSED=$(( $(date +%s) - START ))
      if [ "$GOT" = 1 ]; then
        echo "same-channel reconnect: ${ELAPSED}s to 1880 bytes"
      else
        echo "same-channel reconnect: gave up after ${ELAPSED}s with no bytes (cap ${CAP}s)"
      fi
      ```
      1880 bytes is ten TS packets — enough that a keep-alive burst followed by silence cannot be
      mistaken for a working stream, and small enough to arrive in one range request.
      **Two things about the clock, both of which have to be reported with the number.** `START` is
      taken *before* the `docker exec`, so this measurement shares its origin with the test's
      `restartBegan` and the two are comparable — the whole point of quoting them in the same
      COVERAGE row, the same error-table row and the same PR paragraph. And `ELAPSED` is computed
      after the successful probe returns, so it can overshoot the true first-byte moment by up to
      that probe's own `--max-time 10`. That error runs in the conservative direction (it can only
      make the reconnect look slower, never faster), it needs no change to the loop, and it is
      worth stating in the report because with the origin corrected the two errors no longer
      cancel each other.
      **Report the line the loop printed, whatever it says.** A value under 30 s would mean the
      mechanism in ruling 4 does not bite the way the code reads, which is worth knowing and worth
      saying; a value well over 30 s, or the give-up line, confirms the finding.
      **Nothing may quote this number until this step has produced it** (orchestrator ruling on
      ruling 4): Task 5's COVERAGE row, Task 6's error-table row, Task 10's issue body and Task
      12's PR body each carry a `<reconnect>` placeholder that only this line fills. If this step
      cannot run — Docker down, no stack — replace `<reconnect>` in all four with the literal
      sentence *"not measured in this environment"* and say so in the task report. A missing
      measurement is a stated gap; a guessed one is a false finding, and three documents would
      carry it.
- [ ] **Step 5: Confirm the container is whole and the guards still pass.**
      Run: `docker exec dispatcharr-e2e-pr8 supervisorctl -c /app/docker/supervisord/supervisorctl.conf status`
      Expected: every program RUNNING.
      Run, with the full variable set: `npx playwright test --project=guards`
      Expected: green — the second test adds no capability and no untagged declaration.
- [ ] **Step 6: Commit.** Write `…/scratchpad/pr8-t4.txt`:
      ```
      test(phase1-pr8): the relay restart is bounded, and spares a queued task

      Scenario B: restart relay-uwsgi with a stream running and an M3U refresh
      just dispatched. The relay serves a tune it has never served before
      within the 30s ceiling stopwaitsecs=20 + startsecs=5 has to fit inside,
      and the refresh queued a moment earlier still completes -- the broker
      and the result backend share Redis DB 0 with the relay's channel state,
      so a blind flush on a start path would take all three.

      The ceiling is asserted against a fresh tune, not a same-channel
      reconnect. A reconnect to the channel that was running reaches
      _channel_setup_needed's active-state early return, which does not
      consult the dead owner's heartbeat, and only the 30s orphan sweep can
      clear it. Measured and filed rather than asserted; the header and
      COVERAGE.md carry the mechanism.

      Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `e2e/tests/streaming-split/process-restart.spec.ts`, then commit with `-F`.

---

### Task 5: `e2e/COVERAGE.md` — the rows Phase 1 owes

**Files:** Modify `e2e/COVERAGE.md`

**Interfaces:** none in code. Consumes the bounded-restart number from Task 4 step 3 and the
same-channel reconnect line from Task 4 step 4.

- [ ] **Step 1: Confirm what is missing before writing anything.**
      Run: `grep -n "| P1 |" e2e/COVERAGE.md`
      Expected: the three rows PRs 5, 6 and 7 added (authorize hop, relay events, relay control
      API). PRs 2 and 4 added **no** row, contradicting the orchestrating assumption that they
      did — say so in the task report.
      Run: `grep -ni "first byte\|three-segment\|role split" e2e/COVERAGE.md`
      Expected: no output.
- [ ] **Step 2: Add the six rows** immediately after the existing `Relay control API` P1 row, so
      all P1 rows stay together. Five are the Phase 1 tests that shipped without a row; the sixth
      is the gap Task 4 found. Substitute the measured number from Task 4 step 3 for `<N>`:
      ```markdown
| Streaming | Time to first byte through nginx: a live channel answers with a valid 188-byte-aligned TS packet within a 10s liveness ceiling, through whichever process serves `/proxy/ts/stream/<uuid>` — written before PR 4 gave that route its own nginx location and unchanged after it, which is what makes it a routing guard rather than a performance test. Deliberately **not** a spooling detector: at the scenario's `rate: 20` a buffered nginx would still forward inside 10s, so the `uwsgi_buffering off` directive is pinned statically in `streaming-greybox/nginx-stream-buffering.spec.ts` instead. `tests/streaming/time-to-first-byte.spec.ts` | P1 | done |
| Streaming | The SPA three-segment route still serves the SPA: a deep link shaped like the Xtream `/<user>/<pass>/<id>` root form falls through to the frontend catch-all instead of `stream_xc`, because PR 2 narrowed the URL pattern's `channel_id` segment (`XC_STREAM_ID_PATTERN`) to the numeric-with-optional-extension shape a real stream id has. Without it the route matched first and DRF's exception handler absorbed `get_object_or_404`'s `Http404` before Django's catch-all ever saw it. `tests/streaming/spa-three-segment-route.spec.ts` | P1 | done |
| Streaming | Django down: with `api-uwsgi` stopped, an already-running stream keeps delivering aligned TS (nothing on the byte path calls Django once a stream runs), an ordinary `/api/` route answers **502** (`uwsgi_pass` failing directly) and a new tune answers **500** (the `auth_request` subrequest failing, which `ngx_http_auth_request_module` reports as its own error — the two codes in one outage are the distinction). Starting `api-uwsgi` again restores tunes, and the pre-existing stream is still flowing afterwards, which is D15 in observable form: no start path flushes Redis DB 0. `tests/streaming-split/process-restart.spec.ts` | P1 | done |
| Lifecycle | Bounded relay restart: `supervisorctl restart relay-uwsgi` returns the relay to RUNNING and it serves a fresh tune with aligned TS **<N>ms** after the restart command was issued, inside the 30s ceiling that `stopwaitsecs=20` plus `startsecs=5` has to fit within. An M3U refresh dispatched immediately before the restart still completes afterwards (`updated_at` bumped, status `success`) — the Celery broker and result backend live in the same Redis DB 0 as the relay's channel state, so a blind flush on a start path would take all three. `tests/streaming-split/process-restart.spec.ts` | P1 | done |
| Lifecycle | Modular role split: `api`, `relay` and `worker` containers on one network, with TS bytes read through the `api` container's nginx and the relay reached across the compose network. The only test of the cross-container relay hop in either direction — `scripts/e2e_up.sh` is AIO-only — and therefore the only place a `DISPATCHARR_WEB_HOST` that Django's `get_host()` rejects (an underscore in a container name) would surface. `docker/tests/test-puid-pgid.sh`'s `test_role_split`, run by `lifecycle-tests.yml`'s `suites` job in full mode. The same scenario, not a second one: the bash-suite bullet list below already names it as "the programme's only cross-container relay scenario"; this row is the flow entry it never got | P1 | done |
| Streaming | **Gap (found by the bounded-restart test):** a viewer reconnecting to the **same** channel after a relay restart is not covered by that restart's bound. `_channel_setup_needed` (`apps/proxy/live_proxy/views.py`) returns "no setup needed" for a channel whose metadata still says `active` and never consults the dead owner's `live:worker:<id>:heartbeat` — the zombie check in `ProxyServer.check_if_channel_exists` sits behind that early return and is unreachable from the tune path. The reconnecting client therefore attaches as a follower to a channel nobody owns, and only `_check_orphaned_metadata`'s 30s sweep can clear it — which declines to clean a channel that still has a live client, exactly what a retrying reconnect keeps supplying. The worker id is `hostname:pid`, so the new process never inherits the dead one's identity; the heartbeat simply expires on its own 30s TTL. Measured at **<reconnect>** against a channel a viewer was watching when the relay was restarted, requiring 1880 delivered bytes rather than a 200 (a follower on an ownerless channel answers 200 with nothing). The test tunes a channel that was *not* running when the relay went away, and the reconnect is filed ([#<issue>](https://github.com/D10Scot/Dispatcharr/issues/<issue>)) rather than asserted | P1 | todo |
      ```
      **`<issue>` is filled in by Task 10**, which files it, and **`<reconnect>` by Task 4 step
      4**, which measures it — Task 11 step 6 only restates that measurement, it does not take it.
      Leave both until then, and do not commit this file before Task 10 has run. No number may be written here from any other source — the corrected measurement is the
      only thing that has produced one, and the earlier, status-only form of that loop could
      report a reconnect that delivered no bytes.
- [ ] **Step 3: Verify the table still parses as a table.**
      Run: `grep -c "^| " e2e/COVERAGE.md`
      Expected: the previous count plus six. Every added line must begin with `| ` and end with
      ` |`, and contain no unescaped `|` inside a cell.
      This file is committed in Task 10, together with the issue number it references.

---

### Task 6: The spec — Requirements, Done log, the error table, Amendment S12

**Files:** Modify `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`

**Interfaces:** Consumes the SHA table from Task 1 step 3 and the measured restart number from
Task 4 step 3.

- [ ] **Step 1: Finalize § Requirements the relay meets or carries.** Rewrite the `Where` column
      of every row so it names the PR *and* its merge SHA, using the table from Task 1 step 3:
      `PR 3 (#173, 9c9100f0)`, `PR 4 (#175, c9cf78a6)`, `PR 5 (#176, ce25bd7e)`,
      `PR 6 (#188, ce5c1d44)`, `PR 7 (#194, <sha>)`, `PR 8 (#<this PR>, <filled by Task 12>)`.
      The two `Still carried` rows keep their `—`. Add a sentence to the table's introduction:
      ```markdown
Phase 0's § Carried, not fixed table, with a status column now that Phase 1 exists to answer it.
Every `Where` cell names the pull request and the commit it merged as, so a reader can go from a
requirement to the diff that met it in one step; `—` means no PR touched the row and the
requirement is carried forward unchanged.
      ```
- [ ] **Step 2: Name the second exception in the single-writer row.** Change that row's status
      from **Met, with one named exception** to **Met, with two named exceptions**, and in the row
      "*(new)* The relay's Redis keys have exactly one writer, and no control-plane code reads
      them", append to the status cell, after the existing #190 sentence:
      ```markdown
A second exception PR 7's Done grep could not see, because its directory list is
`apps/channels/ apps/m3u/ core/ dispatcharr/`: `apps/proxy/tasks.py`'s `fetch_channel_stats` builds
the live stats payload straight off Redis and runs in the `worker` role — control-plane code that
happens to live inside `apps/proxy/`. It is the disabled half of a duplicated beat entry
(`dispatcharr/settings.py`'s `CELERY_BEAT_SCHEDULE["fetch-channel-statuses"]` ships
`"enabled": False`, and `core/tasks.py` carries the live one), so nothing runs it on a stock
instance. Tracked as issue #193 and deliberately not deleted here: the removal would touch
`dispatcharr/settings.py`, whose `_SHARED_PATH_PREFIXES` entry forces all sixteen backend labels
for a dead-code change PR 8's section does not ask for.

Phase 1 closes with both exceptions open, deliberately. Neither is a correctness defect — #190's
`hdel` prevents a double `DECR` and #193's task is unscheduled — and both are relay-internal edits
D10 keeps out of this phase. Phase 1's goal was the extraction, and the route page and `CLAUDE.md`
both say stopping cleanly is a legitimate outcome; stopping with two named, tracked exceptions is
what that looks like in a table, as against a "Met" that would have to be read as unqualified.
      ```
- [ ] **Step 3: Correct § Error handling per hop.** Two rows are wrong against the tree. Replace
      the `Relay down, existing viewer` row:
      ```markdown
| **Relay down, existing viewer** | Connection drops; retries get `502`/`504` until supervisord restarts `relay-uwsgi`. Bounded for the *process* — PR 8 measured a fresh tune served <N> ms after `supervisorctl restart relay-uwsgi` was issued, inside the 30 s the `stopwaitsecs=20` + `startsecs=5` budget has to fit within. **Not bounded for a viewer reconnecting to the same channel**: `_channel_setup_needed` (`apps/proxy/live_proxy/views.py`) returns "no setup needed" for a channel whose metadata still reads `active` without consulting the dead owner's heartbeat, so the reconnecting client attaches as a follower to a channel nobody owns; `ProxyServer.check_if_channel_exists`'s zombie check sits behind that early return, and `_check_orphaned_metadata`'s 30 s sweep declines to clean a channel that still has a live client — which a retrying reconnect keeps supplying. Measured at <reconnect>, requiring delivered bytes rather than a 200. Found by PR 8's own scenario, filed as issue #<issue>, and left as a Phase 2 item: the fix is inside the relay, which this phase does not rewrite. |
      ```
      and add a row after `Django down, failover on an existing stream`:
      ```markdown
| **Django down, everything else the relay needs** | Events are lost, not delayed: `emit_event` is fire-and-forget on a greenlet (`apps/proxy/control_plane.py`), so a transition during the outage never reaches `SystemEvent`; the transport logs once at the start of an outage and once on recovery ("Relay events reachable again after an outage"). The two synchronous calls, `next_source()` and `release_source()`, can each hold one greenlet for ~14 s — 2 × (2 s connect + 5 s read) + a 0.1 s retry delay (Amendment S10, point 8). `relay_client`'s budgets run the other way and do not apply here: (1, 2) on the tune path, (2, 5) for admin reads and stops, (2, 20) for `advance`, no retries anywhere. |
      ```
      Substitute `<N>` from Task 4 step 3, and leave `#<issue>` for Task 10 and `<reconnect>` for
      Task 4 step 4. **`<reconnect>` may not be filled from anything but that step's corrected,
      byte-requiring loop** — this row is the spec's own statement of the contradiction, and a
      false-fast number here would retract it in the document that records it.
- [ ] **Step 4: Fill the Done log.** Replace the whole table with:
      ```markdown
| Item | PR | Merged |
|---|---|---|
| Supervisor dependency | #167 | `936c742e` |
| TTFB + SPA-three-segment tests | #169 | `fbc40265` |
| Supervisord | #173 | `9c9100f0` |
| Process split | #175 | `c9cf78a6` |
| Authorize hop | #176 | `ce25bd7e` |
| Next-source + events | #188 | `ce5c1d44` |
| Control API | #194 | `<sha from Task 1>` |
| Django-down + docs | #<this PR> | this PR |
      ```
      PR 7's SHA is the one cell Task 1 could not know from this branch. Read it directly rather
      than inferring it from a log line:
      Run: `gh pr view 194 --repo D10Scot/Dispatcharr --json mergeCommit --jq .mergeCommit.oid`
      Expected: a 40-character SHA whose first eight characters match the commit Task 1 step 1
      found at the tip of `origin/main`. Use the short form in the table, as every other row does.
      PR 8's own `Merged` cell reads `this PR` rather than a placeholder: a merge commit cannot
      name itself, the orchestrator has confirmed they will fill it after merge (Task 12 step 4),
      and `this PR` is a true statement in the meantime where a `—` would read as "never merged".
      Change the sentence above the table from "Filled in as PRs merge. Empty at spec-writing
      time." to:
      ```markdown
Filled in as PRs merge; the spec itself landed as #164 (`37dbf734`). PR 8's own row names the pull
request and leaves the commit as "this PR" — a merge commit cannot name itself, so that cell is
completed after the merge.
      ```
- [ ] **Step 5: Add Amendment S12** after Amendment S11:
      ```markdown
**Amendment S12 (PR 8 Django-down and docs).** Six decisions this section did not make:

1. **A new project, `streaming-split`, not a spec under `streaming-greybox`.** This section offers
   both. Only the project confines the hazard: in CI every matrix project gets its own container,
   so a project is the unit that contains an `api-uwsgi` outage, and `streaming-greybox`'s single
   worker protects against overlap *within* that project only. Unlike the four lifecycle projects
   it keeps its container, so it depends on `bootstrap` and uses the ordinary fixtures; it never
   calls `up`/`restart`/`recreate`/`down`, only `supervisorctl()`.
2. **The 500 is not narrowed, and the reason is that nginx cannot narrow it.** A genuine 500 from
   `/_dispatcharr/authorize` and an unreachable `api-uwsgi` arrive at the same `error_page` with
   the same status, so any narrowing would relabel an authorize-view bug as "retry, this is
   temporary" — which every player in the supported set would do, forever. The distinction is
   available where it is useful, in the access log's `$upstream_status`. The cost of leaving it is
   that a client sees 500 where 503 would read better; the mitigation is that the 500 is now
   documented in `CLAUDE.md` and in § Error handling per hop rather than mysterious.
3. **The ≤ 30 s ceiling is asserted against a fresh tune, not a same-channel reconnect**, because
   the ceiling's own justification in this section is about the process. The same-channel
   reconnect is worse than this section assumed and is recorded in § Error handling per hop, in
   `e2e/COVERAGE.md` and as an issue: the tune path's active-state early return never consults the
   dead owner's heartbeat, and the sweep that would clear the zombie declines to run while a
   client is attached.
4. **The Celery half of D15 is an M3U refresh discriminated by `updated_at`**, which is bumped only
   by a successful refresh. The test does not pin the instant a message sat in the broker; it pins
   that a task dispatched immediately before the restart still ran to completion across it, which
   is what a blind `flushdb` on a start path would break.
5. **The `phase-done` milestone cannot be added by the PR that earns it.**
   `metrics/build/curated.py` requires every milestone `sha` to be a full first-parent commit on
   `main`, and a merge commit cannot name itself, so the row goes into the PR body for whoever
   merges — the same shape `docs/agents/metrics.md` prescribes for a `fixed_in` with no number
   yet. The missing `phase-start` row for `phase1` (`37dbf734`, #164) is added by PR 8, since its
   commit has existed since the spec landed.
6. **§ Requirements gains a second named exception, `apps/proxy/tasks.py`'s
   `fetch_channel_stats` (#193).** PR 7's Done grep names four control-plane directories and this
   one lives inside `apps/proxy/`, so the grep was structurally unable to see it. It is the
   disabled half of a duplicated beat entry; deleting it would touch `dispatcharr/settings.py` and
   force all sixteen backend labels for a dead-code removal PR 8's section does not ask for.
      ```
      This file is committed in Task 10 with the issue number Task 3's finding produced.

---

### Task 7: `CLAUDE.md` — the corrections Phase 1 owes

**Files:** Modify `CLAUDE.md`

**Interfaces:** Consumes the sixteen-label count from Task 11 (step 5 is written last) and the
architecture-collector number from its own step 4.

- [ ] **Step 1: § Repository and direction lists this spec.** The section names four investigation
      documents and the Phase 0 spec; Phase 1's spec is not there, so a reader is sent to the route
      page for something this spec settled. Change the introductory sentence and add the entry:
      ```markdown
Four investigation documents and two phase specs hold the detail behind every summary here —
**read the relevant one before deep work rather than re-deriving it**:
      ```
      and after the Phase 0 spec bullet:
      ```markdown
- Phase 1 spec (process split, eight PRs) — `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`. The decisions D1–D16, the nginx location contract, the per-hop error table and Amendments S1–S12 are all there; it is the authority on anything the split touches, and `docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md` is the ADR it rests on.
      ```
- [ ] **Step 2: § Operationally — the `max-requests` overstatement (ruling 12).** Replace the final
      sentence of that paragraph, "Both are blunt: harakiri and a max-requests recycle kill the
      whole gevent worker, and with it every other in-flight request on it.", with:
      ```markdown
The two are blunt in different degrees, and the difference matters when reading a log. **Harakiri is abrupt**: it kills the whole gevent worker and every other in-flight request on it, naming only the request it fired for (`harakiri-verbose = true`). **A `max-requests` recycle is not** — it is a graceful reload: the worker stops accepting new requests, finishes what it holds, and the master waits `worker-reload-mercy` (uWSGI's default of 60s; set in neither `docker/uwsgi.ini` nor `docker/uwsgi.modular.ini`) before escalating. The caveat that survives is narrower: uWSGI's gevent plugin waits for *request* greenlets, not for greenlets the application spawned outside a request, unless `gevent-wait-for-hub` is set, and it is not. Neither applies to the relay, which carries neither directive.
      ```
- [ ] **Step 3: § Operationally — what a control-plane outage looks like.** Append to the same
      paragraph:
      ```markdown
Phase 1 PR 8 measured the two restart shapes end to end. **Stopping `api-uwsgi` does not disturb a running stream** (nothing on the byte path calls Django once a stream runs) but refuses every new tune with a **500** — nginx's `auth_request` subrequest cannot be served, and `ngx_http_auth_request_module` maps everything that is not 2xx/401/403 to its own error, so a stream URL answers 500 while an ordinary `/api/` route in the same outage answers 502 from the failed `uwsgi_pass`. A failover during the outage falls back to the candidate list cached at channel start, unenforced, after up to ~14s per control-plane call, and posts a `channel_error` with reason `degraded_failover` on recovery; events raised during the outage are lost, not queued. **Restarting `relay-uwsgi` is bounded for the process** — a fresh tune is served well inside the 30s `stopwaitsecs=20` + `startsecs=5` budget — **but not for a viewer reconnecting to the same channel**: the tune path's active-state early return never consults the dead owner's heartbeat, so the reconnecting client attaches as a follower to a channel nobody owns, and the 30s orphan sweep that would clear it declines to run while a client is attached. Both are pinned by `e2e/tests/streaming-split/process-restart.spec.ts`; the reconnect gap is filed, not fixed, because the fix is inside the relay.
      ```
- [ ] **Step 4: § Structural constraints — the reverse-import count.**
      Run: `PYTHONPATH=scripts/metrics python3 scripts/metrics/collect_architecture.py --repo-root .`
      Expected: JSON including `"reverse_imports_into_proxy"`, `"proxy_orm_writes": 0` and
      `"models_module_level_live_proxy_imports": 2`. It printed 29 while this plan was written.
      In the "Good news" bullet, replace "The obstacle is 24 reverse-import sites and reads of 14
      model classes, not transactional coupling." with, substituting the measured number:
      ```markdown
The obstacle is **<N> reverse-import sites** (`scripts/metrics/collect_architecture.py`'s `reverse_imports_into_proxy`, which counts non-test import statements outside `apps/proxy/` that import from it — Phase 1 raised the number on purpose, by giving the control plane one `relay_client` to import instead of a Redis key to read) and reads of 14 model classes, not transactional coupling.
      ```
      Leave the "367 cross-app imports over 50 edges, four cycles" sentence alone (ruling 13): the
      collector counts a different population and swapping one definition's number into another
      definition's sentence would make it wrong in a new way.
- [ ] **Step 5: § Testing — the E2E project list.** In the "**E2E exists now**" paragraph change
      "thirteen projects" to "fourteen projects" and insert `streaming-split` into the list after
      `streaming-greybox`. Then append to that paragraph:
      ```markdown
`streaming-split` is the newest, and the only project that takes a supervisord program away rather than the container: it stops `api-uwsgi` with a stream running and restarts `relay-uwsgi` with a Celery task queued, driving `instance.supervisorctl()` so it needs one allowlist line and no new grey-box capability.
      ```
- [ ] **Step 6: The two test counts (ruling 13).** After Task 11 has run all sixteen labels,
      substitute the measured total for `~1,787` in both places — § Test hooks' "Baseline **16/16**
      backend packages pass (~1,787 tests, ~34s)" and § Testing's "16 labels; ~1,787 backend
      tests, ~6,128 frontend tests". Use the number the run printed, and the wall time it took.
      **If Task 11 has not run yet, leave both alone and come back. If Task 11 could not run at
      all — Docker down, no container — drop this step entirely** (orchestrator ruling): a stale
      count is a pre-existing condition, an invented one is a new false statement, and neither is a
      reason to hold the PR. Say in the task report that the count edit was dropped and why.
      This file is committed in Task 10.

---

### Task 8: `docs/agents/issue-tracker.md` — the `resolveReviewThread` example

**Files:** Modify `docs/agents/issue-tracker.md`

**Interfaces:** none in code.

- [ ] **Step 1: Replace the one-line Review threads bullet** under § Pull requests as a triage
      surface. Today it says the mutation exists and stops there, which leaves the reader to
      invent the query. Replace it with:
      ````markdown
- **Review threads** (not exposed by `gh pr view`): read them with `gh api graphql`, and resolve one with the `resolveReviewThread` mutation on its thread id. This matters on every PR here, not only on triage: the Main ruleset turns on `required_review_thread_resolution`, so a PR merges only once every thread the review bot opened is resolved, and no `gh pr` subcommand lists them.

  List the unresolved threads on a PR, newest comment first:

  ```bash
  gh api graphql -f query='
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              path
              line
              comments(first: 1) { nodes { author { login } body } }
            }
          }
        }
      }
    }' -f owner=D10Scot -f name=Dispatcharr -F number=<pr> \
    --jq '.data.repository.pullRequest.reviewThreads.nodes[]
          | select(.isResolved | not)
          | {id, path, line, first: .comments.nodes[0].body}'
  ```

  `-f` sends a string and `-F` infers a type, so `number` must use `-F` or the API rejects it as a
  `String!` where an `Int!` was declared. Then resolve one by its `id` (a `PRRT_`-prefixed node
  id, not a number):

  ```bash
  gh api graphql -f query='
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { id isResolved }
      }
    }' -f threadId=<PRRT_…>
  ```

  Resolve a thread only after acting on it. `unresolveReviewThread` takes the same input and
  reopens one.
      ````
- [ ] **Step 2: Check the fences.** The bullet nests two fenced blocks inside a list item, which
      Markdown allows only when the fences are indented to the item's content column. (The block
      above is delimited by **four** backticks in this plan purely so its three-backtick contents
      survive; what you paste into `issue-tracker.md` uses three, as shown.)
      Run: `sed -n '/Review threads/,/unresolveReviewThread/p' docs/agents/issue-tracker.md`
      Expected: every ``` line indented two spaces under the bullet, and no stray blank line
      between the bullet text and its first fenced block beyond the one shown.
      This file is committed in Task 10.

---

### Task 9: The metrics ledger and the missing phase milestone

**Files:**
- Modify: `metrics/curated/defects.yml`
- Modify: `metrics/curated/milestones.yml`

**Interfaces:** none in code. The validator is the gate.

- [ ] **Step 1: Move `preemption-dead-code` to `fixed` (ruling 11).** Replace the row:
      ```yaml
- {id: preemption-dead-code, title: "Channel preemption is dead code: _pick_channel_to_preempt exists, the return is commented out", area: dead-code, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: 194, carried_as: null, first_seen: 2026-08-22, status_changed: <today>}
      ```
      `fixed_in: 194` is PR 7, which deleted the function and its commented-out `return`; PR 7's
      plan allowed its executor to defer this edit when the number was not yet known, and by now
      it is. Substitute the actual date for `<today>`. **If Task 1 step 5 found the row already
      `fixed`, skip this step and say so** — status moves forward only, and the validator rejects a
      backward move.
- [ ] **Step 2: Add the missing `phase-start` milestone (ruling 9).** In
      `metrics/curated/milestones.yml`, append to `milestones:`:
      ```yaml
  - {sha: 37dbf734c2f440b67613c90311ae283f07810a6f, label: Phase 1 spec, kind: phase-start, phase: phase1, pr: 164, summary: "Process split and the relay contract: sixteen decisions, eight PRs, ADR 0005."}
      ```
      This is the commit that landed the spec, it is first-parent on `main`, and the `phase1`
      phase has been declared since the metrics dashboard's Part B with no milestone pointing at
      it. **No `phase-done` row here.** Not a choice: `metrics/build/curated.py` requires a
      first-parent SHA on `main`, PR 8's merge commit does not exist yet, and this same validator
      runs in the `metrics/**` edit hook and in the commit gate — so a row with a placeholder SHA
      would stop this PR from committing its own ledger. Task 12 step 4 hands the row to the
      orchestrator, who has taken it as a **docs-only follow-up commit on `main` after PR 8
      merges**, with everything but the SHA already filled in.
- [ ] **Step 3: Validate.**
      Run: `python3 -m metrics.build --validate-only --curated metrics/curated`
      Expected: exit 0, no errors listed. A `sha … is not a first-parent commit` error means the
      local `origin/main` is stale — `git fetch origin` and re-run.
      Run: `scripts/run_metrics_tests.sh`
      Expected: green. This is what the `metrics/**` edit hook runs, and a malformed row fails
      here rather than in the Pages build.
      This file is committed in Task 10.

---

### Task 10: Close the issues, file the finding, and commit the documents

**Files:**
- Modify: `e2e/COVERAGE.md` (fill in Task 5's `<issue>` placeholder)
- Modify: `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (same placeholder)
- Commit: everything Tasks 5–9 wrote

**Interfaces:** Consumes the finding from Task 4. Produces the issue number both documents cite.

- [ ] **Step 1: File the same-channel reconnect finding.** Write the body to
      `…/scratchpad/pr8-reconnect-issue.md`:
      ```markdown
      After `supervisorctl restart relay-uwsgi`, a viewer reconnecting to the
      **same** channel is not covered by the restart's bound. Phase 1 PR 8's
      `streaming-split` project measured a fresh tune served well inside the
      30s ceiling; a reconnect to the channel that was running when the relay
      went away is a different path.

      Mechanism, three sites:

      1. `apps/proxy/live_proxy/views.py`'s `_channel_setup_needed` returns
         `(False, state, False)` for a channel whose metadata still reads
         `active`, **without consulting the owner's heartbeat**. That check
         exists only on the unknown-state branch below it.
      2. `ProxyServer.check_if_channel_exists` does detect a zombie, by
         `live:worker:<id>:heartbeat`, and cleans it — but it sits behind that
         early return and is unreachable from the tune path.
      3. `ProxyServer._check_orphaned_metadata` runs every 30s from the
         cleanup thread and is the only sweep that can clear the state. It
         declines to clean a channel that still has a live client after ghost
         removal, which a retrying reconnect keeps supplying.

      The worker id is `f"{hostname}:{pid}"`, so a restarted relay never
      inherits the dead worker's identity; the heartbeat key simply expires on
      its own 30s TTL. Nothing calls `ProxyServer.shutdown()` on a uWSGI
      SIGTERM, so a restart leaves the metadata hash saying `active` with an
      owner that is gone.

      Measured: <reconnect>, against a channel a viewer was watching when
      `supervisorctl restart relay-uwsgi` ran. The probe requires 1880
      delivered bytes rather than a 200, because a follower attached to an
      ownerless channel is precisely the case that answers 200 with an empty
      body — a status-only probe reports a reconnect that delivered nothing.

      Not fixed in Phase 1: the fix is inside the relay, and Phase 1 rewrites
      no relay internals (spec § Non-goals). Phase 2 or 3 owns it.

      Filed by Phase 1 PR 8. See
      `e2e/tests/streaming-split/process-restart.spec.ts` and
      `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`
      § Error handling per hop.
      ```
      **Substitute `<reconnect>` and prove it is gone before filing.** This is the only one of the
      four `<reconnect>` sites that is outward-facing, and it is the one Task 12's closing grep
      cannot reach: that grep scans `docs/`, `CLAUDE.md`, `e2e/COVERAGE.md` and `metrics/curated/`,
      and this body lives in the session scratchpad. A placeholder that reaches a public issue is
      published before anyone notices.
      Replace `<reconnect>` in the body file with the line Task 4 step 4 printed — or with the
      literal `not measured in this environment` if that step could not run — and then:
      Run: `grep -c '<reconnect>' /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr8-reconnect-issue.md`
      Expected: `0`. **A non-zero count means stop and substitute; do not file.**
      Only then:
      Run: `gh issue create --repo D10Scot/Dispatcharr --title "Relay restart: a viewer reconnecting to the same channel is not covered by the restart bound" --label needs-triage --body-file /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr8-reconnect-issue.md`
      Record the number. Substitute it for `<issue>` in `e2e/COVERAGE.md` (Task 5, row 6) and in
      the spec's § Error handling per hop row (Task 6, step 3).
- [ ] **Step 2: Verify #87's labels, then close both issues (ruling 10).**
      Run: `gh issue view 87 --repo D10Scot/Dispatcharr --json labels --jq '[.labels[].name]'`
      If the output contains `wontfix`:
      Run: `gh issue edit 87 --repo D10Scot/Dispatcharr --remove-label wontfix`
      If it does not, **do nothing and say so in the report** — Amendment S4 promised a removal
      that is no longer needed, and reporting that is the deliverable.
      Run:
      ```bash
      gh issue close 87 --repo D10Scot/Dispatcharr --comment "Fixed by Phase 1 PR 5 (#176): every relay-served surface now authorizes through apps/proxy/authorize.py's authorize_stream, which applies hidden_from_output and the user's hide_adult_content against Channel.is_adult on /proxy/ts/stream/, /proxy/catchup/ and both XC roots. Covered by e2e/tests/streaming/hidden-channel-streamable.spec.ts and the authorize-matrix row in e2e/COVERAGE.md; the ledger entry hidden-channel-streamable is fixed_in 176. The separate HDHomeRun gap (all four apps/hdhr/api_views.py views are AllowAny and resolve no user) is #82, not this issue."
      ```
      Run:
      ```bash
      gh issue close 95 --repo D10Scot/Dispatcharr --comment "Fixed by Phase 1 PR 5 (#176): the catch-up path authorizes through the same function as every other relay-served surface, so an adult channel is no longer unlistable-yet-streamable there. Covered by e2e/tests/streaming/catchup-proxy-mode.spec.ts; the ledger entry hidden-catchup-streamable is fixed_in 176."
      ```
      Run: `gh issue view 87 --repo D10Scot/Dispatcharr --json state --jq .state` and the same for
      95. Expected: `CLOSED` for both.
- [ ] **Step 3: Verify #181 closed with PR 7.**
      Run: `gh issue view 181 --repo D10Scot/Dispatcharr --json state,stateReason --jq '{state, stateReason}'`
      Expected: `CLOSED`. If it is still open, close it referencing PR 7:
      `gh issue close 181 --repo D10Scot/Dispatcharr --comment "Closed by Phase 1 PR 7 (#194): both asks are met — the internal token is bound per request (PR 6's X-Dispatcharr-Internal-Request, signing method, full path, body and a 120s window) and all five /proxy/relay/ routes are IsInternalRelay, and AuthorizeResult.is_internal carries the second half without a sixth trust header (Amendment S11, ruling 15)."`
      Report which of the two you did.
- [ ] **Step 4: Commit the documents.** Write `…/scratchpad/pr8-t10.txt`:
      ```
      docs(phase1-pr8): finalize the spec, CLAUDE.md, COVERAGE and the ledger

      The spec's Requirements table now names the pull request and the merge
      commit for every requirement, its Done log carries all eight rows, and
      Amendment S12 records the six decisions PR 8 had to make. Two rows of
      the per-hop error table were wrong against the tree: a relay restart is
      bounded for the process, not for a viewer reconnecting to the same
      channel, and a Django outage costs more than the authorize hop.

      CLAUDE.md gains the Phase 1 spec beside the four investigation
      documents, loses its overstatement about max-requests (a recycle is a
      graceful reload bounded by worker-reload-mercy; only harakiri is
      abrupt), and records what a control-plane outage actually looks like.

      COVERAGE.md gains the five Phase 1 rows that shipped without one and the
      reconnect gap. The ledger records channel preemption as deleted, and the
      phase1 phase finally has the phase-start milestone its spec commit
      earned.

      Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md CLAUDE.md e2e/COVERAGE.md e2e/README.md docs/agents/issue-tracker.md metrics/curated/defects.yml metrics/curated/milestones.yml`,
      then commit with `-F`.
      **Note:** `e2e/README.md` may already be committed by Task 2. Stage it here only if
      `git status --short` shows it modified.

---

### Task 11: Full verification

**Files:** none edited unless a check fails. A fix is committed with the task it belongs to, not
here — except `CLAUDE.md`'s test counts (Task 7, step 6), which are written from this task's
numbers and committed with a `--amend`-free follow-up commit in Task 12.

**Interfaces:** none. This is the evidence for every Done criterion above.

- [ ] **Step 1: All sixteen backend labels.** This PR edits no backend file, so the routed set is
      empty; the full set is run anyway, because the Done criteria are about the tree and it costs
      about thirty-five seconds.
      Run: `docker exec … dispatcharr-testrunner-pr8 … manage.py test --keepdb apps.accounts.tests apps.backups.tests apps.channels.tests apps.connect.tests apps.dashboard.tests apps.epg.tests apps.m3u.tests apps.output.tests apps.plugins.tests apps.proxy.live_proxy.tests apps.proxy.tests apps.proxy.vod_proxy.tests apps.timeshift.tests apps.vod.tests core.tests tests -v1`
      Expected: OK, 16/16. **Record the test count and the wall time** — Task 7 step 6 writes both
      into `CLAUDE.md`.
- [ ] **Step 2: The commit gate, as CI derives it.**
      Run: `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr8 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr8 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.claude/hooks/pre-commit-tests.sh --git-hook`
      Expected: pass.
- [ ] **Step 3: No product code changed.**
      Run: `git diff --name-only origin/main...HEAD`
      Expected: only paths under `e2e/`, `.github/workflows/e2e-tests.yml`, `metrics/curated/`,
      `docs/` and `CLAUDE.md`. **Anything under `apps/`, `core/`, `dispatcharr/`, `frontend/` or
      `docker/` means the PR left its scope — stop and report.**
- [ ] **Step 4: Metrics and guards over the tree.**
      Run: `PYTHONPATH=scripts/metrics python3 scripts/metrics/collect_architecture.py --repo-root .`
      Expected: `"proxy_orm_writes": 0` and `"models_module_level_live_proxy_imports": 2`,
      unchanged — this PR touches no Python. Record `reverse_imports_into_proxy` and confirm it
      matches what Task 7 step 4 wrote.
      Run: `python3 -m metrics.build --validate-only --curated metrics/curated`
      Expected: exit 0.
      Run: `scripts/run_metrics_tests.sh`
      Expected: green.
- [ ] **Step 5: Frontend and E2E static checks.**
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/frontend && npm ci && npm test`
      Expected: green, and `git diff --name-only origin/main...HEAD -- frontend/` prints nothing.
      Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/e2e && npm ci && npx tsc --noEmit`
      Expected: clean.
- [ ] **Step 6: Restate the same-channel reconnect measurement.** It was taken in Task 4 step 4,
      while that stack and that channel were already up, and it is not re-run here: step 7 below
      rebuilds the image and resets the stack, so the channel it measured no longer exists. Quote
      the line Task 4 step 4 printed in this task's report, and confirm `<reconnect>` carries it —
      or the literal "not measured in this environment" — in all four places that step lists. Only
      if Task 4 step 4 never ran should you take the measurement here, and then take it **after**
      step 7, using the uuid from that run's `[relay-restart] channel` log line.

- [ ] **Step 7: Build this worktree's E2E stack and run five projects.** Build with
      `docker rmi dispatcharr-e2e-pr8:local` first, then `scripts/e2e_up.sh` with every variable
      from § Test environment step 6, then recreate the provider with
      `-e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-pr8:8080`. Run, each with the **full**
      variable set:
      `--project=guards`, `--project=streaming-split`, `--project=streaming`,
      `--project=streaming-greybox`, `--project=lifecycle`.
      Expected: green. `guards` proves the allowlist and tag rules; `streaming-split` is this PR's
      own work; `streaming` and `streaming-greybox` prove the new project left the container in
      the state its siblings expect; `lifecycle` shells out to `scripts/e2e_up.sh` and is the
      reason every variable has to be exported (issue #187).
      **Never pass `--reset` or `--down`**, and never touch the shared `dispatcharr-e2e`,
      `e2e-upstream` or `dispatcharr-testrunner`. The shared `e2e-upstream` container is stopped
      and is not ours to start.
- [ ] **Step 8: Both bash lifecycle scenarios.**
      Run: `docker/tests/test-puid-pgid.sh modular_mode`
      Run: `docker/tests/test-puid-pgid.sh role_split`
      (The script takes a single scenario name as a bare argument; run the whole suite instead if
      the run budget allows.) Expected: the same pass/fail/skip counts `e2e/README.md` records,
      with `readonly_rootfs` still the one skip. Report the counts. `role_split` is the only test
      of the cross-container relay hop and this PR's COVERAGE row claims it.
- [ ] **Step 9: zizmor on the edited workflow.**
      Run: `echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.github/workflows/e2e-tests.yml"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr8 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr8/.claude/hooks/run-affected-tests.sh`
      Expected: exit 0, zero findings.
- [ ] **Step 10: Write the verification report.** State, per check: the command, the result, and
      the count where there is one. Anything that could not run — Docker down, a project that
      needs an image this machine cannot build — is reported as **not run**, not as passing. The
      work is then unverified, not verified. Include the two measured numbers (the bounded restart
      and the same-channel reconnect) explicitly; three documents quote them.

---

### Task 12: The plan, the PR, and the follow-up commit

**Files:**
- Create (commit): `docs/superpowers/plans/2026-09-06-phase1-pr8-django-down-and-docs.md`
- Modify: `CLAUDE.md` (test counts, from Task 11 step 1)
- Modify: `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (PR 8's own number,
  then its merge SHA)

**Interfaces:** none in code.

- [ ] **Step 1: Commit `CLAUDE.md`'s measured counts and this plan.** Apply Task 7 step 6 now that
      Task 11 has produced the number — **or, if Task 11 could not run, skip the count edit and
      commit the plan alone**, trimming the commit message's second paragraph to match. Write
      `…/scratchpad/pr8-t12.txt`:
      ```
      docs(phase1-pr8): the plan, and the measured backend test count

      Both "~1,787 tests" figures are replaced with what the sixteen-label run
      actually reports on this tree; the E2E project list is fourteen with
      streaming-split.

      Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage `CLAUDE.md docs/superpowers/plans/2026-09-06-phase1-pr8-django-down-and-docs.md`, then
      commit with `-F`.
- [ ] **Step 2: Open the PR.** Title:
      `Phase 1 PR 8: Django-down, a bounded relay restart, and the documents Phase 1 owes`.
      The body must carry, in this order:
      1. What the two scenarios assert and what they measured — the fresh-tune restart number
         (Task 4 step 3) and the same-channel reconnect number (Task 4 step 4). Both are quoted
         from those steps' output and from nowhere else; if either did not run, say so in the
         body rather than omitting it.
      2. Why the new tune during the outage is a 500 and why it is not narrowed (Amendment S12,
         point 2), naming the 502 on `/api/` in the same outage as the contrast.
      3. The new `streaming-split` project: why a project and not a greybox spec, the one
         `CONTAINER_LIFECYCLE` allowlist line, and the three places it is wired.
      4. The same-channel reconnect finding, its three code sites, and the issue number — stated
         as a Phase 2 item, because the fix is inside the relay.
      5. The documents finalized: the Requirements table with PR numbers and merge SHAs, the Done
         log, Amendment S12, the corrected per-hop error rows, the `CLAUDE.md` corrections
         (naming the `max-requests` one explicitly), the six COVERAGE rows, the
         `resolveReviewThread` example.
      6. `Closes #87` and `Closes #95`, with one sentence saying PR 5 (#176) is what fixed them
         and this PR performs the closure the spec's Done item deferred here.
      7. The two named exceptions the Requirements table keeps, #190 and #193, each with its
         one-line reason, and one sentence saying why the phase closes with both open: neither is
         a correctness defect and both are relay-internal edits D10 keeps out of this phase, so
         stopping with named, tracked exceptions is the clean stop the route page and `CLAUDE.md`
         call a legitimate outcome — not an unqualified "Met" that would have to be read as more
         than it is.
      8. The two post-merge items, verbatim, because a merge commit cannot name itself and the
         metrics validator rejects any milestone SHA that is not already first-parent on `main`:
         ```
         After merge, as a docs-only follow-up commit on main. The orchestrator has taken both.
         Neither could ship inside this PR: metrics/build/curated.py rejects a milestone sha that
         is not already a first-parent commit on main, and that validator runs in the metrics/**
         edit hook and in the commit gate -- so a row naming this PR's own merge commit would have
         stopped this PR from committing its ledger at all. A validator constraint, not an
         oversight.
         1. In the Phase 1 spec's Done log, replace "this PR" in the Django-down + docs row's
            Merged column with the short merge SHA.
         2. Append to metrics/curated/milestones.yml —
         {sha: <this PR's merge commit>, label: Phase 1 done, kind: phase-done, phase: phase1, pr: <this PR>, summary: "Eight PRs: two uWSGI processes, one authorize hop, next-source and events over HTTP, and the relay's Redis keys private."}
            then re-run: python3 -m metrics.build --validate-only --curated metrics/curated
         ```
      9. Task 11's verification report.
      Then the two footer lines the session requires. **Do not** claim `E2E result` or
      `Lifecycle result` green from a local run — say what was run locally and let CI say the rest.
- [ ] **Step 3: The follow-up commit, once the PR has a number.** GitHub assigns a number as soon
      as the PR opens. Substitute it for `#<this PR>` in the spec's Done log row and in the
      Requirements table's PR 8 cells, and for `<issue>` anywhere Task 10 could not reach.
      Run: `grep -rn "#<this PR>\|<issue>\|<reconnect>\|<N>\|<sha from Task 1>\|<today>" docs/ CLAUDE.md e2e/COVERAGE.md metrics/curated/ /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr8-reconnect-issue.md`
      Expected: no output. **Any remaining placeholder is a defect in this PR**, not a note for
      later. `<reconnect>` is filled either with Task 4 step 4's measured line or with the literal
      "not measured in this environment" — both satisfy this grep, and a bare placeholder does
      not. The issue body file is scanned here as a **second** belt only: it is already filed by
      then, so Task 10 step 1's own pre-filing check is the one that protects it, and a hit here
      means an issue needs editing on GitHub rather than a file needing a fix. The one thing that is deliberately not a placeholder is the Done log's `this PR` in the
      `Merged` column, which step 4 hands on.
      Write `…/scratchpad/pr8-t12b.txt`:
      ```
      docs(phase1-pr8): record this PR's number in the spec

      Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
      ```
      Stage the spec (and any other file that held a placeholder), then commit with `-F` and push.
- [ ] **Step 4: Hand the two post-merge items to the orchestrator, who has confirmed they will
      carry them.** A merge commit cannot name itself, and `metrics/build/curated.py` rejects any
      milestone SHA that is not a first-parent commit on `main` — the metrics edit hook, the commit
      gate and `pages.yml` all run that validator, so a row carrying a placeholder SHA would make
      this PR unable to commit its own ledger. Both items are therefore stated in the PR body and
      repeated in the final task report, with the PR number already filled in so only one field is
      left:

      Both land as a **docs-only follow-up commit on `main` after PR 8 merges** — the orchestrator
      has taken them, and this is a validator constraint rather than an oversight or a deferral of
      convenience.

      1. **The spec's Done log**, `Django-down + docs` row: replace `this PR` in the `Merged`
         column with the short merge SHA.
      2. **`metrics/curated/milestones.yml`**, appended to `milestones:`:
         ```yaml
  - {sha: <PR 8's merge commit>, label: Phase 1 done, kind: phase-done, phase: phase1, pr: <this PR>, summary: "Eight PRs: two uWSGI processes, one authorize hop, next-source and events over HTTP, and the relay's Redis keys private."}
         ```
         `label` is 12 characters, inside the 40-character limit, and `phase-done` is the kind
         `docs/agents/metrics.md` reserves for a spec's Done log getting its final tick — which
         this PR is. Validate after adding with
         `python3 -m metrics.build --validate-only --curated metrics/curated`.

      Nothing in CI enforces either, which is why both are named in the PR body, here, and in the
      final task report.
