# Phase 2 PR 2a-5 — `server.py` Coverage and the Eight Unowned Matrix Rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the eight parity-matrix rows no other PR owns — 14, 15, 16, 17, 19, 20, 23 and
25 — with tests that drive the relay over real HTTP against real Redis and a real control plane,
and in the same PR raise statement coverage on `apps/proxy/live_proxy/server.py`, the single
largest file in the Gate 2 denominator.

**Architecture:** Every test in this PR is a `RelayHarnessTestCase` (2a-2's harness: a
`LiveServerTestCase`, so one Django process serves both the relay surfaces and `/api/relay/…`,
against the same real Redis and a real Postgres). Tests reach that process the way a client or
nginx does — `requests` to `self.live_server_url` — and assert on what comes back: a status code,
a response header, a JSON field's presence and type, bytes on the wire. Three HTTP surfaces carry
the whole PR: `GET /proxy/ts/stream/<identifier>` (the tune), `GET /_dispatcharr/authorize` (the
hop nginx makes, whose five `X-Relay-*` response headers 2c's Go relay consumes verbatim), and
`GET|DELETE /proxy/relay/channels[/<id>[/clients/<client>]]` (the internal control API, signed
with the two production tokens from `apps/proxy/internal_auth.py`). Nothing is mocked.

**Tech Stack:** Python 3.13, Django 6 (`LiveServerTestCase` / `TransactionTestCase` semantics),
`requests` (already a dependency), the 2a-2 harness under
`apps/proxy/live_proxy/tests/harness/`, real Redis, real Postgres. **No new dependency anywhere.**

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, on the **`phase2-spec`
worktree** at `0c7e19a4` (PR #225) — read-only, and not present in this worktree:
`/Users/dion/git/Dispatcharr/.worktrees/phase2-spec/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`.
The sections this plan implements: § Stage 2a › Gate 1 (the matrix and its guard), § Stage 2a ›
Gate 2 (the coverage measurement), § Stage 2a › The subprocess harness (the composition rule), and
the `2a-5` row of § The seven PRs. Every fact the work needs is carried below; you should not need
to open the spec.

**Branch:** `migration/phase2a-server-and-authorize-coverage`, in worktree
`/Users/dion/git/Dispatcharr/.worktrees/phase2-2a5`, **stacked on `migration/phase2a-subprocess-harness`
at `2a826e07`** (2a-2, the harness and `scripts/coverage_live_path.sh`). Not off `main`: every test
here needs the harness.

---

## Branch base and what is already here

`2a826e07` is 2a-2's tip. It carries:

- `apps/proxy/live_proxy/tests/harness/` — `relay.py` (`RelayHarnessTestCase`, `wait_until`),
  `process.py` (`StandInBin`, `stand_in_stream_profile`), `upstream.py` (`FakeUpstream`),
  `faults.py`, `asset.py`, `ffmpeg_stderr.py`, `standin.py`, and `README.md`. **Read
  `harness/README.md` before Task 1** — it is the contract for everything below.
- `scripts/coverage_live_path.sh` + `scripts/coverage_live_path.coveragerc` — the only sanctioned
  measurement.
- `docs/relay-parity-matrix.md` (from 2a-1, `#223`) with rows 14, 15, 16, 17, 19, 20, 23 and 25
  standing as `owed: 2a-5` in the `<!-- block: owed by 2a-5 -->` block, plus row 28 added by 2a-2.
- `docs/superpowers/plans/2026-09-10-phase2-2a2-subprocess-harness.md`.

**This plan file is already committed on this branch** by the planning pass. Every other file in
§ File structure is yours to create or modify.

**Every `file:line` and every number below was verified against this worktree and against a live
container on 2026-09-10.** Line numbers drift; the tree wins. Where a step says "verify", run the
command and use what it answers.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **The composition rule, and it is the difference between a test that helps 2c and one that only
  moves a number.** Drive the relay through its **HTTP surface** against **real dependencies** —
  the fake upstream, real Redis, the real control plane, real subprocesses. **Never** against mocks
  of `server.py`'s or `input/manager.py`'s internals. Ask of every assertion: *would this still
  mean anything when the implementation underneath is Go?* A test that patches `ProxyServer` and
  asserts a call count inflates coverage and teaches the Go implementer nothing. `unittest.mock` is
  permitted in exactly two shapes in this PR, both named in the tasks that use them:
  `patch.object` on a **configuration class attribute** (the production lever, e.g.
  `TSConfig.BUFFER_CHUNK_SIZE`, which `RelayHarnessTestCase.setUp` already does), and nothing else.
  If a task appears to need a third, stop and report.
- **No production-code change.** Nothing outside `apps/proxy/live_proxy/tests/` and
  `docs/relay-parity-matrix.md`. 2a-2 settled the seam question (real subprocesses throughout, no
  extracted seam); this PR inherits that and needs no edit either. If a task starts to need one,
  stop and report — that is a change to a settled decision, not a detail.
- **No workflow file is edited, and no floor file is written.** The CI wiring, the floor and the
  blocking behaviour are **2a-7's**. This PR runs `scripts/coverage_live_path.sh` locally and
  pastes its output into the PR description.
- **The branch is `migration/**`, so the full E2E and lifecycle matrices run on it.**
  `e2e-tests.yml` runs every Playwright project including `lifecycle-upgrade` and ignores its path
  filter; `lifecycle-tests.yml` runs both bash suites. That is a cost the branch name pays, not a
  signal this PR touches those surfaces. The one Playwright artefact it does touch is
  `docs/relay-parity-matrix.md`, checked by `e2e/tests/guards/parity-matrix.spec.ts` in the
  `guards` project, which needs no container.
- **`TransactionTestCase` flushes every table after each test, migration-seeded rows included.**
  Once any `RelayHarnessTestCase` has run in a process, the locked `ffmpeg` `StreamProfile` and
  every `CoreSettings` group are gone for the rest of that process. **Every test in this PR creates
  every row it needs.** This bites 2a-5 harder than its siblings because authorize tests need
  users, channels, profiles and settings groups. Two consequences you can rely on rather than work
  around:
  - **`CoreSettings` is one row per settings *group*, not per setting** (`core/models.py:201-208`,
    eight groups), and every group is instance-wide, so any write is blast radius. Do not write one
    unless a test genuinely needs it.
  - **A `CoreSettings` group written by a test outlives the flush, in Redis — and the reason is
    the flush, not the write.** `_get_group` caches each group's JSON in the Django cache, which is
    Redis, DB 0, the same instance the relay uses. **The write itself is fine**:
    `core/signals.py:11-15` is `@receiver(post_save, sender=CoreSettings)` calling
    `invalidate_group_cache(instance.key)`, so `objects.update_or_create(...)` invalidates
    correctly. **The flush is what breaks it** — `TransactionTestCase._fixture_teardown` truncates
    with raw SQL and fires **no signals**, so the row vanishes from Postgres while the cached value
    stays in Redis for every later test in the process, and every one of them then reads a setting
    whose row no longer exists. **Any test that writes a settings group must call
    `CoreSettings.invalidate_group_cache(<KEY>)` from `addCleanup`.** Calling it immediately after
    the write as well is harmless and makes the intent obvious. **Tasks 3 and 4 both write one**
    (`network_access` and `user_limit_settings` respectively) and both must do this.
  - **With no `network_access` group row at all, the STREAMS ACL is open.**
    `CoreSettings.get_network_access_settings()` (`core/models.py:720-722`) returns `{}` for a
    missing group, and `network_access_allowed` (`dispatcharr/utils.py:406-420`) falls back to
    `["0.0.0.0/0", "::/0"]` for every key except `M3U_EPG`. So a flushed database is an
    ACL-permissive one and no seeding is needed to make an allowed tune allowed. A test that wants
    the ACL *closed* writes the group; Task 3 is the only one that does.
- **`CELERY_TASK_ALWAYS_EAGER` is off globally and stays off.** `post_save` on `M3UAccount` calls
  `.delay()`; `harness.relay.make_channel` creates one, so the task is enqueued to the real Redis
  broker and never runs. That is correct. Do not add
  `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)` anywhere in this PR.
- **Never pass `--settings=dispatcharr.settings` to `manage.py test`.** `manage.py:11` rewrites the
  settings module to `dispatcharr.settings_test` for the `test` command only; overriding it points
  the suite at the production database.
- **`manage.py test` is not gevent-monkey-patched.** The relay's background threads under test are
  ordinary daemon OS threads. `gevent.sleep()` inside them still works — gevent creates a hub per
  thread.
- **No test sleeps for a fixed duration.** Every wait is `harness.relay.wait_until(predicate,
  timeout=…, interval=…, what="…")`, which returns as soon as the predicate holds and raises
  `AssertionError` naming what it was waiting for when it does not.
- **Derive every timing literal; never hard-code one.** A test that needs a timestamp 61 seconds in
  the past computes `time.time() - 61`; a test that needs a threshold reads the constant that
  defines it. A hard-coded wall-clock literal is a defect this programme has paid for before.
- **`scripts/check_credential_logging.py` runs on every edited `*.py`, test files included** — it is
  given the edited path and has no test exclusion. **Do not pass a URL, path, header or credential
  to a `logger.*` call anywhere in this PR.** Use `print()` if you need to see something while
  developing, and delete it before committing.
- **`git add` and `git commit` run in separate Bash calls**, and the commit message is written with
  the Write tool and passed as `-F <msgfile>` — the `PreToolUse` hook matches on command text and
  blocks any single call containing both verbs, and trips on a heredoc that merely contains them.
- **Every `gh` command carries `--repo D10Scot/Dispatcharr`.** Without it `gh` resolves to
  upstream's public tracker.
- **Commit trailers.** Every commit in this PR ends with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
  ```

---

## Start from the materialised copy, not from this document

A review pass **materialised every test in this plan, ran them, and left the result in place** at
`scratchpad/repo-2a5/`, with a container `dispatcharr-testrunner-rev5` mounting it at `/repo` and
`dexec.sh` / `covrun.sh` helpers beside it. Eight probe files map to Tasks 1-8; **B1's and B2's
fixes are already applied there**, and Task 8 has two green shapes to choose between.

**Use it.** Transcribing ~1,200 lines of Python out of a Markdown document is a whole class of
avoidable error, and the copy is the same code with the measurements already taken. Read this plan
for *why* each test asserts what it does — that is what a materialised file cannot carry — and take
the code from the copy. Where the two disagree, **the copy has been run and this document has
not**: prefer the copy, and say in the PR description which task the disagreement was in.

## Running the tests

The backend suite needs Postgres and Redis. Use **your own** container — sibling PRs share the
default name:

```bash
DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a5 \
DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest \
DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a5 \
.claude/hooks/start-test-container.sh
```

The image override is **required**: the script's default is upstream's image, which carries neither
`coverage` nor `hypothesis` (issue #228). Remove the container and the volume when the PR is done.

One test run, with the environment the hook uses:

```bash
docker exec \
  -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  -e LD_LIBRARY_PATH=/usr/local/lib \
  dispatcharr-testrunner-2a5 bash -lc \
  'cd /repo && redis-cli flushall >/dev/null && \
   /dispatcharrpy/bin/python manage.py test --keepdb <label> --durations 10'
```

Abbreviated below as `<dexec> manage.py test …`. `LD_LIBRARY_PATH=/usr/local/lib` is needed for
real `ffmpeg` (issue #226) and is harmless otherwise. **The commit hook runs the whole package**,
so `apps.proxy.live_proxy` is what actually gates a commit here.

---

## Measured baselines — take your own before you start

Measured on this worktree at `2a826e07`, in the container above, on 2026-09-10:

| Quantity | Value |
|---|---|
| `scripts/coverage_live_path.sh` total | **7,978 statements, 3,213 missing, 59.73%** |
| `apps/proxy/live_proxy/server.py` | **1,490 statements, 840–844 missing, 43.4–44%** (two runs of one tree) |
| `apps.proxy.live_proxy` label | **179 tests, 6.787 s** (`real 0m7.893s`) |
| A `RelayHarnessTestCase` test that tunes a channel and reads bytes | **0.64 – 1.09 s** |
| A `SimpleTestCase` in the same file | 0.056 s |

Three things about these numbers, all of which have cost this programme time before:

1. **The denominator, 7,978, is the check.** It is a property of
   `scripts/coverage_live_path.coveragerc`'s module list and moves only if that list moves. A
   changed denominator is a finding.
2. **`missing` is not reproducible and you must not treat it as if it were.** Eight runs of the
   gate on one unmodified tree spanned `missing` 3,202–3,221 — **19 statements** — with the
   denominator identical every time. **Four of the moving regions are in `server.py`**:
   `:1778-1786` (`_recover_stuck_channel_stops`), `:2436` (`refresh_channel_registry`'s
   skip-mid-shutdown branch) and `:1814` (`stop_channel`'s "stop key already exists" branch), all
   reached only when the cleanup thread's tick (`CLEANUP_CHECK_INTERVAL = 1` s,
   `apps/proxy/config.py:111`) lands while a channel sits in `_stopping_channels`. In the baseline
   run above, `:1778-1786` was missed and `:1814` was covered; the next run may differ. **So:**
   - this PR's gate is **"a measured increase"**, never "exactly N statements";
   - **no test in this PR may assert anything that depends on which thread wins a teardown race**;
   - **no test in this PR may deliberately target `cleanup_task` (`server.py:1880-2196`),
     `_recover_stuck_channel_stops` (`:1773-1798`) or `refresh_channel_registry` (`:2427-2447`).**
     They are the noise source. Leave them missed. § Deliberate non-goals says so again.
**Every number in this section is C-tracer basis, and the stage is moving to `sysmon`.**
`scripts/coverage_live_path.sh` at this branch's base (`2a826e07`) sets no `COVERAGE_CORE`, the
rcfile sets none, and the test image's environment carries none — verified, not assumed. 2a-2
adopted `COVERAGE_CORE=sysmon` in `9c865538`, which is **not** an ancestor of this branch.
**When this branch is rebased onto a 2a-2 that carries `9c865538`, every baseline below shifts and
must be re-taken before it is quoted.** Measured here, one session, same tree, both cores:

| | C tracer | sysmon | delta |
|---|---|---|---|
| Gate total | 7,978 / **3,208** / 59.79% | 7,978 / **3,112** / 60.99% | **−96 missed** |
| `server.py` | 1,490 / **844** / 43.4% | 1,490 / **796** / 46.6% | **−48 missed** |

**Half the whole delta lands in this one file, and all of it lands in exactly two functions:**
`cleanup_task` 161 → 130 and `event_listener` 120 → 108 (plus `check_if_channel_exists` 35 → 34
and four statements in the tail). That is the expected signature — sysmon recovers statements
executing after a `gevent.sleep()`, and those two `while True` loops are the file's sleepers.
**No function changed bucket**: the classification below transfers between cores unchanged, only
three counts shrink. Blocked-or-unreachable is **283 under ctrace, 252 under sysmon**.

**And the files this PR's eight row-tests target do not move at all under either core** —
`authorize.py` 12, `authorize_views.py` 4, `next_source.py` 64, `views.py` 187,
`channel_status.py` 66, `client_manager.py` 92, `url_utils.py` 60, identical to the statement. So
the row-test yield estimates below are core-independent; only the `server.py` figures are not.

**`apps/proxy/utils.py` is NOT in the Gate 2 denominator.** `scripts/coverage_live_path.coveragerc`'s
`[report] include` names `apps/proxy/live_proxy/*` plus ten `apps/proxy/*.py` modules, and
`utils.py` is not one of them — so `check_user_stream_limits`, `get_user_active_connections` and
`_live_connections` are outside the gate entirely. **Task 4's stream-limit test exercises the whole
D4 loop and none of that half counts.** Do not read a small Task 4 coverage movement as a failed
test; the test is pinning rows 20 and 25, and its coverage contribution is incidental by
construction.

**Where `server.py`'s missed statements actually are — a complete attribution, not a sample.**
Produced by AST-walking the module and mapping **every** missed line to its innermost enclosing
`def`, so the rows sum to the file's total exactly. Fifty functions carry at least one missed
statement; they are grouped below by what it would cost to reach them. **An earlier draft of this
plan carried an eight-row subset presented as if it were the whole file, and a "reachable ≈ 150"
figure that was really "what Tasks 6-8 will close" — two different quantities. Both are corrected
here.** Measured on this branch, `server.py` **1,490 statements / 844 missed / 43.4%** (an earlier
run of the same tree gave 840; that four-statement difference is the documented run-to-run spread,
not a change).

| Bucket | Missed | What is in it |
|---|---|---|
| **Blocked — must not be targeted** | **175** | `cleanup_task` `:1880-2190` (161), `_recover_stuck_channel_stops` `:1773-1797` (14). The gate's own non-determinism lives here. |
| **Unreachable or white-box-only** | **108** | `_cleanup_local_resources` `:2487-2569` (61, issue #230); `_check_orphaned_metadata` `:2236-2321` (26, called only from `cleanup_task:2139`, so it inherits that non-determinism); `_execute_redis_command` `:138-159` (14, matrix row 27, declared white-box-only); `_check_orphaned_channels` `:2197-2234` (7, **no callers anywhere in the tree — dead code**). |
| **Reachable, but 2a-6's subject** | **142** | `ensure_output_profile` (64), `ensure_output_format` (45), `stop_output_profile` (14), `stop_output_format` (10), `_parse_output_key` (7), `stop_all_output_*` (2). Reached from `views.py:731` and `:754` on a tune that resolves an Output Profile. **Do not target these here** — 2a-6 owns `output/profile/manager.py` and `output/fmp4/manager.py` and will move them as a side effect. |
| **Reachable by this PR's surfaces** | **269** | `event_listener` `:178-465` (120), `initialize_channel` (51), `handle_client_disconnect` (47), `check_if_channel_exists` (35), `_clean_zombie_channel` (11), `_cleanup_failed_init` (3, **not reachable by Task 8** — a tune by channel uuid never enters `initialize_channel`, which holds this method's only two callers), `_clean_redis_keys` (2). |
| **Reachable, but expensive per statement** | **150** | the ownership lease (`extend_ownership` 17, `try_acquire_ownership` 10, `release_ownership` 9, `get_channel_owner` 7); teardown edges (`_stop_local_stream_activity_locked` 9, `_wait_for_shutdown_delay` 8, `_broadcast_upstream_stop` 8, `check_inactive_channels` 7, `stop_channel` 6, `_release_stream_resources` 6, …); and ~28 functions carrying 1-6 each, almost all `except Exception: logger.error(...)` arms needing fault injection. |

175 + 108 + 142 + 269 + 150 = **844**. The buckets are exhaustive.

**What this PR actually takes: about 121 — a target, not a measurement — out of the 269 (ctrace)
/ 257 (sysmon) pool.** Tasks 6 and 7 target `check_if_channel_exists` (35 ctrace / 34 sysmon),
`_clean_zombie_channel` (11), `_clean_redis_keys` (2) and roughly 74 of the event listener's
120/108 (CLIENT_STOP 13, CHANNEL_STOP 13, STREAM_SWITCH 48). **Task 8 contributes nothing to
`server.py`** — it reaches `views.py:612-615`. A review pass that materialised these tests measured
**−122, range −118…−126** across three runs, which is this target landing.
`initialize_channel`'s 51 and `handle_client_disconnect`'s 47
are reachable and deliberately left: both are teardown- and timing-adjacent, and § Deliberate
non-goals would rather leave statements on the table than add a test whose answer depends on which
thread wins.

**A later PR chasing the last few points toward 80% must not aim at the first two buckets.**
Together they are **283** statements and they look like the biggest prize in the file; one is
unreachable or dead, the other is precisely the region whose non-determinism the gate's tolerance
exists to absorb. Aiming there buys a ratchet that reddens at random.

3. **Budget: this PR adds ≈10.4 s, and that is accepted.** The fixed 15 s stage ceiling is
   withdrawn; the trigger is the `apps.proxy.live_proxy` label crossing **45 s**, and this PR takes
   it to ~17.3 s under the gate. § Keeping the suite fast has the breakdown and the one real lever
   (`LiveServerTestCase` classes, ~0.4–0.5 s each). **Check `--durations` before concluding a test
   is inherently slow** — twice in this stage the cost has been a library default, not the work.

---

## Two things about `RelayHarnessTestCase` you will trip over

Both are in `harness/README.md` and `harness/relay.py`; repeated because every task below depends
on them.

- **The `ProxyServer` singleton is process-wide and is never torn down.** Its cleanup thread
  (`server.py:2192`) and event listener (`server.py:467`) are `while True` loops with no stop flag.
  Tests isolate by **unique channel UUID** and by deleting that channel's Redis keys, never by
  rebuilding the server. Every identifier this PR seeds must be a fresh `uuid.uuid4()`.
- **`self.live_server_url` is the whole deployment.** `setUp` points both
  `DISPATCHARR_INTERNAL_API_BASE_URL` and `DISPATCHARR_RELAY_BASE_URL` at it, so
  `apps/proxy/control_plane.py` (relay → Django) and `apps/proxy/relay_client.py` (Django → relay)
  both resolve to the same live server. That is what makes the stream-limit path in Task 4 a real
  end-to-end loop rather than a mock: `authorize_stream` → `check_user_stream_limits`
  (`apps/proxy/utils.py:410`) → `get_user_active_connections` → `_live_connections` →
  `relay_client.list_channels(all_clients=True)` → a signed `GET /proxy/relay/channels?clients=all`
  over real HTTP → `build_live_channel_stats_data` → Redis.

---

## Two header sets in one PR, and the collapse that must not happen

**Why this PR re-tests code that is already covered, in one sentence.** `apps/proxy/authorize.py`
is at 93.6% and `apps/proxy/tests/test_authorize.py` has 48 tests, four of which are named after
matrix rows this PR owns — and not one of them ports, because every one calls `authorize_stream()`
directly through a `RequestFactory` and patches `network_access_allowed` (`:70`), `_drf_user`
(`:104-105`) or `check_user_stream_limits` (`:120`). That is the spec's white-box bucket — 22 files,
~361 test functions, none surviving a rewrite into another language — meeting the parity matrix for
the first time. **"The tests exist and none of them port" is the fact that justifies stage 2a**, and
it is the answer to anyone who asks why covered code is being tested again.

**This PR sends `X-Dispatcharr-Internal` in two places that require different things of it, and
conflating them is the defect class that produced a total-auth-bypass during the spec's own
review.** Keep these apart:

| Where | What is checked | By what | Headers needed |
|---|---|---|---|
| `/proxy/relay/channels[…]` — Tasks 1, 2, 6, 7 | *is this caller part of the deployment **and** is this exact call, just now* | `IsInternalRelay`, a **permission class** (`apps/proxy/permissions.py:21-27`) | **Both** — static `X-Dispatcharr-Internal` **and** bound `X-Dispatcharr-Internal-Request` |
| `GET /_dispatcharr/authorize` and the tune — Task 3, row 19 | *is this caller part of the deployment* | `authorize_stream`, a **decision function** (`apps/proxy/authorize.py:418` → `_resolve_principal:309-310`) | **Static only** |

The header name is the same; the requirement is not. "The permission class requires two headers" is
**not** the same claim as "the authorize decision requires two headers", and only the first is true.
`internal_auth.py:44-49` gives the reason the streaming surface takes the weaker credential: the
DVR's ffmpeg re-sends its `-headers` line on every reconnect for the life of a recording, so a
120-second windowed token would 403 that reconnect.

**The general form of the trap, which recurs three more times in this PR's own subject matter.** A
view's `permission_classes` / `authentication_classes` describe what DRF does; they say almost
nothing about what `authorize_stream` then decides. Three live instances, each of which a task here
depends on getting right:

1. **`stream_ts` and `stream_xc` are `@permission_classes([AllowAny])`** (`views.py:158-160`,
   `:817-819`) and are nonetheless fully authorized — by `resolve_authorization`, inside the view
   body. "AllowAny" here means "DRF does not gate this", not "this is ungated". Rows 15, 16, 20, 25.
2. **`authorize_view` is `@authentication_classes([])` and DRF still authenticates.**
   `@api_view`'s own `dispatch()` runs `perform_authentication` regardless, which sets
   `request.user` to `AnonymousUser` **before** `authorize_stream` ever runs. That is precisely why
   `_session_user` (`authorize.py:268-287`) reads
   `django.contrib.auth.get_user(http_request)` rather than `http_request.user`, and why
   `_drf_user` (`:227-265`) restores `http_request.user` on a miss. **Row 23 turns entirely on
   this**: a test asserting the session principal must assert `X-Relay-User` carries the id, which
   is only true because the session is re-read from the session store.
3. **"the authenticator set produced no user" has two opposite meanings.** `_drf_user` raises
   `AuthorizeDenied(401)` for a credential an authenticator explicitly *rejected* (a malformed
   Bearer token, an unknown API key) and returns `None` for one merely *declined* (nothing
   presented). A port that maps both to "anonymous" turns a rejected credential into a successful
   anonymous tune of any ordinary channel.

**If a task starts to reason from a view's decorators about who the caller is, stop.** Read
`authorize_stream` instead.

## The three HTTP surfaces, and how to reach each

### 1. The tune — `GET /proxy/ts/stream/<identifier>`

Use the harness: `self.tuned(channel)` (a context manager yielding a reader, response held open) or
`self.tune(channel)` (open, read, close). For a request the harness's helpers do not shape — an
extra header, a non-`Channel` identifier, an expected non-200 — call `requests` directly:

```python
response = requests.get(
    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
    headers={"X-Forwarded-For": "203.0.113.9"},
    stream=True,
    timeout=20,
)
```

**Never build an assertion message from `response.text` on a 200.** A live streaming body does not
end and the read never returns — the `timeout` is a socket timeout, not a wall-clock one. Only a
non-200 has a body worth reading. `harness/relay.py`'s `tuned()` carries the same warning for the
same reason.

### 2. The authorize hop — `GET /_dispatcharr/authorize`

`dispatcharr/urls.py:36` → `apps/proxy/authorize_views.py:243`'s `authorize_view`, which is
`@permission_classes([AllowAny])` and takes the URI being authorized in `X-Original-URI` (nginx's
`$request_uri`, query string included). **This is the cheapest surface in the PR: it makes the
whole decision and tunes nothing.**

- 200 carries five headers — `X-Relay-Channel`, `X-Relay-Output`, `X-Relay-Client`,
  `X-Relay-User`, `X-Relay-Name` (`authorize_views.py:307-312`).
- A denial is **401 or 403 only** — `subrequest_error_response` (`authorize_views.py:95`) maps
  every non-401 status to 403 and puts the real one in `X-Authorize-Status`, because
  `ngx_http_auth_request_module` can carry nothing else. **So a stream-limit denial is
  `403` + `X-Authorize-Status: 429`, and an unknown channel is `403` + `X-Authorize-Status: 404`.**
  Assert both halves; asserting only the 403 proves nothing.

### 3. The internal control API — `/proxy/relay/…`

`apps/proxy/relay_urls.py`, gated by `IsInternalRelay` (`apps/proxy/permissions.py:21-27`), which
requires **both** headers: `request_is_internal(...) and request_is_internal_request(...)`. Mint
them with the production functions, never by hand:

```python
from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)

def signed(method, path, body=b""):
    """The two headers /proxy/relay/... requires. Same shape as
    apps/proxy/relay_client.py:120-133, which is what Django itself sends."""
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }
```

**`path` must be the full path including the query string**, exactly as
`request.get_full_path()` will reconstruct it on the other side — `internal_auth.py:174-186` signs
`request.get_full_path()` deliberately, so `"/proxy/relay/channels"` and
`"/proxy/relay/channels?clients=all"` are different tokens.

`relay_client` already offers `list_channels()` / `get_channel()`, but this PR reads the **wire**,
where the difference between `"owner": null` and no `owner` key at all is the whole point of row
14. Issue the request yourself and read `response.json()`.

**This helper is deliberately local to each test module that needs it, not added to
`harness/`.** 2a-3, 2a-4 and 2a-6 branch off the same 2a-2 commit and merge independently; the
harness package is the one place their diffs can collide, and a five-line helper is not worth a
conflict. If two of this PR's own modules need it, the second one repeats it.

---

## File structure

**Create — eight test modules, one subject each:**

| File | Responsibility | Rows | Tunes |
|---|---|---|---|
| `apps/proxy/live_proxy/tests/test_relay_status_wire.py` | What the two status endpoints put on the wire: field set, types, and the `owner` asymmetry | 14 | 0 |
| `apps/proxy/live_proxy/tests/test_client_ip_provenance.py` | Where `ip_address` in the status payload comes from | 17 | 1 |
| `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py` | The Internal, Admin and Session principals, decided over real HTTP at the hop | 19, 20, 23 (+ a test row 21's Notes ask for, whose line is **not** edited) | 0 |
| `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py` | The stream-by-hash shape: no channel check, ACL and stream limit still applied — on the hop and on the byte path | 16, 25 (+ row 20's stream-limit cell) | **2** |
| `apps/proxy/live_proxy/tests/test_xc_decision_handoff.py` | `stream_xc` authorizes once and hands its decision to `stream_ts` | 15 | 1 |
| `apps/proxy/live_proxy/tests/test_server_registry.py` | `server.py`'s zombie detection and channel-existence registry | — (coverage) | 0 |
| `apps/proxy/live_proxy/tests/test_server_event_listener.py` | `server.py`'s Redis event listener loop | — (coverage) | 1 |
| `apps/proxy/live_proxy/tests/test_server_bringup_failures.py` | A tune whose source cannot be resolved releases its ownership (`views.py:612-615`, **not** `server.py`) | — | 1 (fails fast) |

Eight modules, three of which share one subject (`server.py`) split by the behaviour each drives.
Two of the eight — `test_server_registry.py` and `test_server_event_listener.py` — carry no matrix
row: they exist for Gate 2, and § Deliberate non-goals explains what they leave alone and why.

**Modify:**

- `docs/relay-parity-matrix.md` — **edits to exactly nine lines, all of them rows 14, 15, 16, 17,
  19, 20, 23 and 25** (row 20's line twice, in Tasks 3 and 4), each replacing an `owed: 2a-5` cell
  with a test reference; row 15's Notes cell is also narrowed in Task 5. **No line outside this
  PR's own block is touched** — see Task 3 Step 4 for the one candidate that was dropped and why. **One row is one line; cells are never padded to align columns; do not run a
  Markdown formatter over this file.** Each row is closed in the task that lands its test, so the
  matrix and the tests never disagree at a task boundary. **Closing rows one at a time cannot
  break the guard's contiguity check** — `e2e/tests/guards/parity-matrix.spec.ts:336-364` collects
  **only** the rows still marked `owed:` and skips pinned ones, exactly so a PR that closes part of
  its block does not fail for the rows it left. Verified by reading the test, not assumed.

**Not touched, deliberately:**

- `apps/proxy/live_proxy/tests/harness/**` — see the helper note above.
- `e2e/**` — no Playwright test is added. `e2e/tests/guards/parity-matrix.ts`'s `HIGHEST_ROW_ID`
  stays at **28**: this PR closes rows, it adds none. `e2e/COVERAGE.md` tracks the Playwright
  suite's coverage and is not this PR's ledger.
- `scripts/coverage_live_path.*`, `.github/workflows/**`, `scripts/coverage_live_path.floor` —
  2a-7's.
- Anything under `apps/proxy/` outside `live_proxy/tests/`.

---

## Deliberate non-goals — say so in the PR description

Each of these is a place a reviewer will reasonably ask "why not?", and each has an answer that is
not "we ran out of time".

- **`cleanup_task` (`server.py:1880-2196`, **161** missed at the baseline), `_recover_stuck_channel_stops`
  (`:1773-1798`) and `refresh_channel_registry` (`:2427-2447`).** These are the measured source of
  the gate's 19-statement run-to-run spread (§ Measured baselines). A test that provokes them
  deliberately buys statements and sells reproducibility, and the PR that then has to explain a red
  CI run is 2a-7's. Left missed on purpose.
- **`_cleanup_local_resources` (`server.py:2487-2569`, **61** missed).** Reachable from exactly two
  places: the cleanup loop (above), and the event listener's CHANNEL_STOP branch at `:389`. That
  branch needs a worker that **owns** the channel (the whole event body is inside
  `if self.am_i_owner(channel_id):` at `:245`, indentation verified) while holding a buffer or
  client manager but **no** stream manager — a follower/owner hybrid a single-process harness can
  only fake. Contrived, unportable, skipped.
- **The event listener's STREAM_SWITCH *failure* branch (`server.py:333-357`).** Needs
  `StreamManager.update_url()` to return `False`, which is `input/manager.py`'s behaviour and 2a-4's
  subject. The success and same-URL branches are covered (Task 7).
- **`ENSURE_OUTPUT_FORMAT` / `ENSURE_OUTPUT_PROFILE` (`server.py:420-431`).** Both spawn an output
  process; `output/fmp4/manager.py` and `output/profile/manager.py` are **2a-6's** files. Covering
  them here would duplicate 2a-6's work and blow this PR's time budget.
- **`initialize_channel`'s Redirect/Proxy-profile branches.** `next_source`'s profile shape is
  2a-4's and 2a-6's ground; this PR uses the ffmpeg-shaped stand-in profile throughout.

---

## Keeping the suite fast

- **Budget: ≈ 10.4 s added, and that is the plan's number rather than an aspiration.** An earlier
  draft promised ≤ 3.5 s. That figure was wrong and — worse — **its own drop list could not have
  reached it**, which is the real defect: a plan must not promise a number its remedies cannot
  deliver. Measured on a materialised copy of these tests, without coverage: **≈10.4 s for ~35
  tests**; under the gate the `apps.proxy.live_proxy` label goes 179 tests / 7.6 s → 215 / 17.3 s.
- **Where the 10.4 s actually goes**, none of which the earlier draft costed:
  - `TransactionTestCase`'s flush is **~80–100 ms per test**, not "tens of milliseconds". At ~35
    tests that alone is ~3.2 s, and it is unavoidable — the harness base class is a
    `LiveServerTestCase`.
  - Each `LiveServerTestCase` **class** costs **~0.4–0.5 s** to start and stop its server thread.
    Nine classes ≈ 4 s. **This is the only real lever**: the cost is per class, not per file, so
    folding two classes in one module into one saves half a second. Task 7's two classes are the
    obvious candidate if you want it back.
  - **Five tuning tests, not four.** The earlier draft wrote "four tunes (Tasks 2, 4, 5, 7)" while
    Task 4 has **two** — and Task 4 now has two again after the B1 fix. At ~0.7 s each that is
    ~3.5 s.
- **The fixed 15 s stage ceiling is withdrawn.** The trigger is the `apps.proxy.live_proxy` label
  crossing **45 s**; with 2a-4's ~8.5 s this PR is well inside it.
- **Do not cut tests to hit a number.** Every test here pins a matrix row or a named `server.py`
  region, and the two that would have been dropped first under the old list —
  Task 7's stream-switch test and Task 4's held-open tune — are respectively the largest single
  `server.py` gain (48 statements) and the only end-to-end proof in the tree that the stream-limit
  loop closes over real HTTP. **Report the measured number in the PR description; do not trade
  coverage for it.**
- **The live server is already amortised per class by Django itself** (verified against Django
  6.0.8: `LiveServerTestCase.setUpClass` starts one server thread and registers
  `addClassCleanup`). Sharing across classes needs a custom runner and is not worth it. The residual
  per-test cost is `TransactionTestCase._fixture_teardown`'s table flush.

---

## Task 1: Row 14 — the status payload's field set and types

`GET /proxy/relay/channels/<id>` (detail) and `GET /proxy/relay/channels` (list) are built by two
different functions from the same Redis hash, and they disagree in three ways that 2c must
reproduce exactly. No tune: the subject is what the builders and serializers do with a metadata
hash, so the test writes one.

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_relay_status_wire.py`
- Modify: `docs/relay-parity-matrix.md` (row 14 only)

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase`; `apps.proxy.internal_auth`'s
  `HEADER_INTERNAL` / `HEADER_INTERNAL_REQUEST` / `internal_principal_token` /
  `build_internal_request_header`; `apps.proxy.live_proxy.redis_keys.RedisKeys.channel_metadata`;
  `apps.proxy.live_proxy.constants.ChannelMetadataField` and `ChannelState`.
- Produces: nothing other tasks import. Task 4 and Task 6 each repeat the four-line `signed()`
  helper rather than importing it from here — see § The three HTTP surfaces.

**The facts this task pins, each verified in this worktree:**

| Field | Detail (`get_detailed_channel_info`, `channel_status.py:25-401`) | List (`get_basic_channel_info`, `channel_status.py:419-618`) |
|---|---|---|
| `owner`, when the hash records none | `:45` — `metadata.get(OWNER, 'unknown')` → the **string `"unknown"`** | `:460` — `metadata.get(OWNER)` → **`null`** |
| `ffmpeg_speed` | `:376` — `float(...)` | `:599` — `float(...)` |
| `source_fps` | `:339` — the **raw Redis string**, no coercion | `:595` — `float(...)` |
| `state`, when never recorded | `:41` — `metadata.get(STATE)` → **`null`**, never `"unknown"` | `:457` — same |

Neither serializer supplies a `default=`, so the builder's value reaches the wire unchanged:
`relay_serializers.py:107` (`owner`, detail) and `:43` (list) are both
`CharField(required=False, allow_null=True)`; `:129` types detail's `source_fps` as `CharField` and
`:59` types list's as `FloatField`; `:136` and `:60` type `ffmpeg_speed` as `FloatField` on both.
`relay_serializers.py:8-16` records why every optional field is `required=False` with no default:
DRF's `Field.get_attribute` raises `SkipField` for a missing key in exactly that configuration, so
`total_bytes`, `avg_bitrate_kbps`, `stream_id` and `stream_name` are **absent from the JSON
entirely** rather than null when the builders never assigned them.

Which endpoint each route reaches, verified in `apps/proxy/relay_views.py`: `channels_view`
(`:85`, the **list** route) calls `build_live_channel_stats_data` (`channel_status.py:619`) which
calls `get_basic_channel_info`; `channel_view` (`:145`, the **detail** route) calls
`get_detailed_channel_info` directly at `:180`.

- [ ] **Step 1: Write the failing test**

`apps/proxy/live_proxy/tests/test_relay_status_wire.py`:

```python
"""What the two status endpoints put on the wire (parity-matrix row 14).

Two builders read one Redis hash and disagree in three ways. 2c has to
reproduce all three, so all three are asserted here against the JSON a
client of /proxy/relay/... actually receives -- not against the builders'
Python dicts, where a serializer could still change the answer.

No tune: the subject is the mapping from a metadata hash to a wire shape.
The hash is written here with RedisKeys and ChannelMetadataField, the same
vocabulary server.py:777 and :860 write it with in production.
"""

import json
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.relay import RelayHarnessTestCase


def _signed(method, path, body=b""):
    """The two headers IsInternalRelay requires, minted the production way.

    Deliberately a module-local copy rather than a harness addition: 2a-3,
    2a-4 and 2a-6 branch off the same commit and the harness package is the
    one file their diffs can collide in.

    `path` carries the query string, because internal_auth.py:174-186 signs
    request.get_full_path() and not request.path.
    """
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


class StatusWireShapeTests(RelayHarnessTestCase):
    def setUp(self):
        super().setUp()
        self.identifier = str(uuid_module.uuid4())
        self.redis = ProxyServer.get_instance().redis_client
        self.assertIsNotNone(self.redis, "the harness needs a real Redis client")
        self.addCleanup(self.redis.delete, RedisKeys.channel_metadata(self.identifier))

    def _seed(self, **fields):
        self.redis.hset(RedisKeys.channel_metadata(self.identifier), mapping=fields)

    def _detail(self):
        path = f"/proxy/relay/channels/{self.identifier}"
        response = requests.get(
            self.live_server_url + path, headers=_signed("GET", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.json()

    def _list_row(self):
        path = "/proxy/relay/channels"
        response = requests.get(
            self.live_server_url + path, headers=_signed("GET", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        rows = [
            row
            for row in response.json()["channels"]
            if row["channel_id"] == self.identifier
        ]
        self.assertEqual(len(rows), 1, "exactly one row for the seeded channel")
        return rows[0]

    def test_owner_is_the_string_unknown_on_detail_and_null_on_list(self):
        # The asymmetry itself, and the reason a test that checks one
        # endpoint proves nothing about the other. channel_status.py:45
        # supplies 'unknown' as get()'s default; :460 supplies none.
        self._seed(**{ChannelMetadataField.STATE: ChannelState.ACTIVE})

        self.assertEqual(self._detail()["owner"], "unknown")

        row = self._list_row()
        self.assertIn("owner", row)
        self.assertIsNone(row["owner"])

    def test_source_fps_is_a_string_on_detail_and_a_float_on_list(self):
        # channel_status.py:339 passes the raw Redis string through;
        # :595 coerces. relay_serializers.py types the field to match
        # (:129 CharField, :59 FloatField). Carried, not fixed (spec D5).
        self._seed(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.SOURCE_FPS: "29.97",
        })

        self.assertEqual(self._detail()["source_fps"], "29.97")
        self.assertEqual(self._list_row()["source_fps"], 29.97)

    def test_ffmpeg_speed_is_a_float_on_both_endpoints(self):
        # The half of the old string/float split that Phase 1 PR 7 closed
        # (channel_status.py:376 and :599 both float()). Asserted so the
        # Go relay is held to the fixed behaviour, not the historical one.
        self._seed(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.FFMPEG_SPEED: "1.02",
        })

        self.assertEqual(self._detail()["ffmpeg_speed"], 1.02)
        self.assertEqual(self._list_row()["ffmpeg_speed"], 1.02)

    def test_state_is_null_rather_than_the_string_unknown_when_never_recorded(self):
        # A hash with no state field at all: both builders read it with a
        # bare get(), so the wire carries null. CLAUDE.md records this as
        # the field that used to disagree and no longer does.
        self._seed(**{ChannelMetadataField.CHANNEL_NAME: "seeded"})

        self.assertIsNone(self._detail()["state"])
        self.assertIsNone(self._list_row()["state"])

    def test_optional_fields_are_absent_entirely_rather_than_null(self):
        # relay_serializers.py:8-16: every optional field is required=False
        # with no default, so DRF's SkipField keeps an absence an absence.
        # A `default=` anywhere in those serializers would turn each of
        # these into a null and silently change /proxy/ts/status.
        self._seed(**{ChannelMetadataField.STATE: ChannelState.ACTIVE})

        detail = self._detail()
        for field in ("total_bytes", "avg_bitrate_kbps", "stream_id", "stream_name"):
            self.assertNotIn(field, detail, f"{field} must be absent, not null")

        row = self._list_row()
        for field in ("total_bytes", "avg_bitrate_kbps", "stream_id", "stream_name"):
            self.assertNotIn(field, row, f"{field} must be absent, not null")
```

- [ ] **Step 2: Run it and see it pass or fail for a reason you understand**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_relay_status_wire -v2
```

This test describes behaviour that already exists, so **passing on the first run is the expected
outcome** — it is a characterization pin, not a red-green cycle. What you must do instead is prove
it would go red if the behaviour regressed. Do all three, and record the output in the PR
description:

1. Edit `apps/proxy/live_proxy/channel_status.py:45` to `metadata.get(ChannelMetadataField.OWNER)`
   and confirm `test_owner_is_the_string_unknown_on_detail_and_null_on_list` fails. **Revert.**
2. Add `default=None` to `relay_serializers.py:53` (`total_bytes`) and confirm
   `test_optional_fields_are_absent_entirely_rather_than_null` fails. **Revert.**
3. Change **`relay_serializers.py:129`** — detail's `source_fps` — from `CharField` to
   `FloatField`, and confirm `test_source_fps_is_a_string_on_detail_and_a_float_on_list` fails.
   **Revert.** **Not** the `float()` edit in `channel_status.py:339` an earlier draft of this plan
   named: that cannot go red, because the detail serializer is a `CharField` and
   `str(float("29.97"))` is `"29.97"` again, so the wire is unchanged. The serializer is where this
   row's type actually lives.

`git diff` must be empty of `apps/proxy/live_proxy/channel_status.py` and
`apps/proxy/relay_serializers.py` before you commit.

If `_detail()` returns 404 rather than 200 for a metadata-only channel, read
`relay_views.py:180-194`: `get_detailed_channel_info` returned falsy. Seed at least one field the
builder assigns unconditionally (`channel_id` is synthesised, `state` is not) and re-run.

- [ ] **Step 3: Close row 14 in the matrix**

Replace the `Pin` cell of row 14 — the line beginning `| 14 |` — changing **only** that cell:

```
`owed: 2a-5`
```

becomes

```
`apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_owner_is_the_string_unknown_on_detail_and_null_on_list`, `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_source_fps_is_a_string_on_detail_and_a_float_on_list`, `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_ffmpeg_speed_is_a_float_on_both_endpoints`
```

Three references because the row asserts three distinct disagreements, in the idiom row 10 already
uses. Do not pad the cell, do not touch any other line, and do not let an editor reformat the file.

- [ ] **Step 4: Run the guard**

```bash
cd e2e && npx playwright test --project=guards parity-matrix
```

Expected: green, and the printed counts show one fewer `owed` row than before. The guard resolves
each `.py` symbol by looking for `def <symbol>(` in the named file, so a typo in a test name fails
here rather than rotting.

- [ ] **Step 5: Commit**

```bash
git add apps/proxy/live_proxy/tests/test_relay_status_wire.py docs/relay-parity-matrix.md
```

```bash
git commit -F <msgfile>
```

Message subject: `test(phase2): pin the status payload's field set and types (matrix row 14)`.

---

## Task 2: Row 17 — where `ip_address` comes from

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_client_ip_provenance.py`
- Modify: `docs/relay-parity-matrix.md` (row 17 only)

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase` (`make_channel`, `tuned`, `stand_in`,
  `wait_until`), `harness.process.stand_in_stream_profile`, the `_signed` helper repeated locally.
- Produces: nothing.

**The facts:** `stream_ts` resolves the client address **once**, at
`apps/proxy/live_proxy/views.py:195` — `client_ip = get_client_ip(request)` — and hands it to
`client_manager.add_client(client_id, client_ip, …)` at both registration sites (`views.py:593` and
`:712`). `ClientManager.add_client` (`client_manager.py:215-230`) stores it, and both serializers
expose it (`relay_serializers.py:29` on the list row, `:79` on the detail row).

`get_client_ip` (`dispatcharr/utils.py:342-370`) honours `X-Real-IP` and `X-Forwarded-For` **only
when `REMOTE_ADDR` is a trusted proxy**, which by default means `LOCAL_NETWORK_CIDRS` —
loopback included. **In the harness `REMOTE_ADDR` is `127.0.0.1`, so it is trusted, so a forwarded
header is honoured.** That is what makes this testable without nginx: a tune carrying
`X-Forwarded-For: 203.0.113.9` must report `203.0.113.9`, and a tune carrying none must report
`127.0.0.1` — never empty, never a placeholder.

The row's own Notes say 2b-2 will replace `get_client_ip(request)` with `X-Relay-Client-IP` set by
the authorize hop. **The invariant this test pins survives that change**, because the hop calls the
same `get_client_ip` on the same request — which is exactly why the test asserts the *value* and
never the mechanism. Do not assert anything about which header was read.

**One channel, two clients, one read.** A second client on an already-running channel costs no
second channel initialization and no second spawn, so both provenance cases fit inside one tune.

- [ ] **Step 1: Write the failing test**

```python
"""Where ip_address in the status payload comes from (parity-matrix row 17).

stream_ts resolves the address once (views.py:195) and hands it to
add_client; the row's invariant is that what lands on the wire is the real
client's address. Asserted as a value, never as a mechanism: 2b-2 changes
the source to X-Relay-Client-IP and this test must survive that.

REMOTE_ADDR is 127.0.0.1 under LiveServerTestCase, which get_client_ip
treats as a trusted proxy (dispatcharr/utils.py:342-370, LOCAL_NETWORK_CIDRS),
so a forwarded header is honoured here exactly as it is behind nginx.
"""

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


def _signed(method, path, body=b""):
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


FORWARDED_CLIENT = "203.0.113.9"  # TEST-NET-3, RFC 5737: never routable, never local


class ClientIpProvenanceTests(RelayHarnessTestCase):
    def test_ip_address_is_the_real_client_address_on_both_status_endpoints(self):
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            identifier = str(channel.uuid)

            # The first client holds the channel open for the whole test.
            with self.tuned(channel) as first:
                first.read(20 * 188)

                # The second client joins the running channel: no second
                # initialization, no second spawn.
                second = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    headers={"X-Forwarded-For": FORWARDED_CLIENT},
                    stream=True,
                    timeout=20,
                )
                self.addCleanup(second.close)
                self.assertEqual(second.status_code, 200)
                # Pull one chunk so registration has certainly happened
                # before the status read; never format response.text on a
                # live 200 -- the body does not end.
                next(second.iter_content(chunk_size=188))

                detail_path = f"/proxy/relay/channels/{identifier}"

                def two_clients():
                    payload = requests.get(
                        self.live_server_url + detail_path,
                        headers=_signed("GET", detail_path),
                        timeout=10,
                    ).json()
                    return len(payload.get("clients", [])) >= 2

                wait_until(two_clients, timeout=10, what="both clients registered")

                detail = requests.get(
                    self.live_server_url + detail_path,
                    headers=_signed("GET", detail_path),
                    timeout=10,
                ).json()
                addresses = sorted(c["ip_address"] for c in detail["clients"])
                self.assertEqual(addresses, ["127.0.0.1", FORWARDED_CLIENT])

                list_path = "/proxy/relay/channels?clients=all"
                rows = requests.get(
                    self.live_server_url + list_path,
                    headers=_signed("GET", list_path),
                    timeout=10,
                ).json()["channels"]
                row = next(r for r in rows if r["channel_id"] == identifier)
                self.assertEqual(
                    sorted(c["ip_address"] for c in row["clients"]),
                    ["127.0.0.1", FORWARDED_CLIENT],
                )

            self.stop_channel(channel)
```

`sorted()` rather than positional indexing: which client the payload lists first is not a behaviour
this row pins, and asserting it would make the test depend on registration order.

- [ ] **Step 2: Run it**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_client_ip_provenance -v2 --durations 5
```

Expected: PASS. Record the duration — it is one of this PR's **five** tuning tests and § Keeping
the suite fast is measured against it.

- [ ] **Step 3: Prove it would fail if the behaviour regressed**

Edit `apps/proxy/live_proxy/views.py:195` to `client_ip = request.META.get("REMOTE_ADDR", "")` —
the naive form the row exists to forbid — and confirm the test fails with `["127.0.0.1",
"127.0.0.1"]`. **Revert**, and confirm `git diff apps/proxy/live_proxy/views.py` is empty.

- [ ] **Step 4: Close row 17 in the matrix**

Row 17's `Pin` cell becomes:

```
`apps/proxy/live_proxy/tests/test_client_ip_provenance.py::test_ip_address_is_the_real_client_address_on_both_status_endpoints`
```

- [ ] **Step 5: Run the guard, then commit**

```bash
cd e2e && npx playwright test --project=guards parity-matrix
```

```bash
git add apps/proxy/live_proxy/tests/test_client_ip_provenance.py docs/relay-parity-matrix.md
```

```bash
git commit -F <msgfile>
```

Subject: `test(phase2): pin ip_address's provenance on both status endpoints (matrix row 17)`.

---

## Task 3: Rows 19, 20 and 23 — the authorize matrix over real HTTP

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py`
- Modify: `docs/relay-parity-matrix.md` (rows 19, 20 and 23 — **and no other line**; see Step 4)

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase`; `apps.accounts.models.User`;
  `apps.channels.models.Channel`; `apps.proxy.internal_auth.internal_principal_token` and
  `HEADER_INTERNAL`; `core.models.CoreSettings`.
- Produces: nothing.

**Why the hop and not the tune.** These three rows are about a **decision**, and the decision has
its own HTTP surface: `GET /_dispatcharr/authorize`, which nginx calls once per tune and whose five
`X-Relay-*` response headers the relay consumes. Driving that surface asserts the decision without
initializing a channel or spawning anything, which is what lets this PR pin three rows for tens of
milliseconds instead of three tunes. It is also the surface whose contract 2c is held to: the Go
relay reads exactly these headers.

**The auth fact you must get right, because getting it wrong caused a total-auth-bypass defect
during this spec's own review.** There are **three** HMAC contexts (`apps/proxy/internal_auth.py`):

| Header | Context | Means | Required by |
|---|---|---|---|
| `X-Dispatcharr-Authorized` | `b"relay-trust"` (`:39`) | *nginx made this decision; trust the `X-Relay-*` params* | `request_is_relay_trusted` (`:110-118`), consulted by `resolve_authorization` (`authorize_views.py:148`) |
| `X-Dispatcharr-Internal` | `b"internal-principal"` (`:40`) | *this caller is part of this deployment* | `request_is_internal` (`:121-123`), consulted by `authorize_stream` via `_resolve_principal` (`authorize.py:309-310`) |
| `X-Dispatcharr-Internal-Request` | `b"internal-request"` (`:50`) | *…and this exact call, just now* — bound to method + `get_full_path()` + timestamp + body digest, 120 s window (`:155-186`) | `IsInternalRelay` (`permissions.py:21-27`), **alongside** the static one, on the five `/proxy/relay/…` and two `/api/relay/…` routes **only** |

**Row 19's Internal principal is the *second* header alone.** `authorize_stream` calls
`request_is_internal(http_request)` (`authorize.py:418`) and nothing else; the bound header is not
part of that decision. `internal_auth.py:44-49` says why in production terms: the DVR's ffmpeg
re-sends its `-headers` line on every reconnect for the life of a recording, and a windowed token
would 403 the reconnect. **So a row-19 test sends `X-Dispatcharr-Internal` only.** Sending the
bound header too would not be wrong, but it would misdescribe the contract in a test whose whole
job is to describe it.

**What each row claims, with the code that decides it:**

- **Row 19, Internal.** `_resolve_principal` returns `INTERNAL_PRINCIPAL` (`authorize.py:309-310`);
  `_apply_channel_checks` returns immediately for it (`:376-377`), so `user_level`, profile
  membership, `hidden_from_output` and adult filtering are all bypassed; `user` is `None` at `:423`,
  so the stream-limit block at `:436-442` (guarded by `if user is not None`) never runs. The ACL at
  `:425-426` is **not** bypassed — `network_access_allowed(http_request, "STREAMS", None)`.
- **Row 20, Admin.** `_apply_channel_checks` returns at `:379-385` for
  `user_level >= User.UserLevel.ADMIN`, **before** the `hidden_from_output` check at `:386` —
  deliberately, so the admin UI can preview any channel. But `user` is not `None`, so the stream
  limit at `:436-442` **does** run. The whole content of the row is that asymmetry; its stream-limit
  half is pinned in **Task 4**, which has the live client to prove it with.
- **Row 23, Session.** `_drf_user` returns `None` (no DRF credential presented), so
  `_session_user` (`:268-287`) runs and reads the session with
  `django.contrib.auth.get_user(http_request)` — deliberately **not** `http_request.user`, because
  `authorize_view`'s own `@api_view` dispatch clobbers `request.user` to `AnonymousUser` before
  `authorize_stream` ever runs. A non-admin session principal is subject to every check.

**Sessions over real HTTP.** `settings.py` sets no `SESSION_ENGINE`, so Django's default
database-backed sessions apply, and a `LiveServerTestCase`'s server thread sees rows the test
committed. `self.client.force_login(user)` writes a session row and sets the cookie on the Django
test client; copy its value onto a `requests` call:

```python
self.client.force_login(user)
cookies = {"sessionid": self.client.cookies["sessionid"].value}
```

If that turns out not to authenticate through the live server, the fallback is to build the session
directly — `SessionStore()` + `django.contrib.auth.login`, the recipe
`apps/proxy/tests/test_authorize.py:483-492` already uses — and read `session.session_key`. Try
`force_login` first and only fall back if it fails.

**Also written here: the test row 21's Notes ask 2a-5 for — but row 21's line is not edited.**
Row 21 is **already pinned** (`e2e/tests/streaming/authorize-matrix.spec.ts`), so it carries no
`owed:` marker and is outside Gate 1's accounting entirely. What it carries is a sentence in its
**Notes** — "the adult-filter half for this principal is proven only by a catch-up-root test …
so 2a-5 owes a live-root equivalent instead" — an obligation recorded where no check can see it.
This task writes that test,
`test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root`, and leaves row 21's line
alone for the merge-conflict reason Step 4 gives.

- [ ] **Step 1: Write the failing test**

```python
"""The authorize matrix, decided over real HTTP (rows 19, 20, 23, plus the
live-root test row 21's Notes ask 2a-5 for -- row 21's own line is already
pinned and is not edited by this PR).

Driven at GET /_dispatcharr/authorize -- the subrequest nginx makes once per
tune, whose five X-Relay-* response headers 2c's Go relay consumes verbatim.
That surface makes the whole decision and tunes nothing, which is why three
rows fit in this file for the cost of no spawns at all.

apps/proxy/tests/test_authorize.py already covers these principals by calling
authorize_stream() directly with a RequestFactory and patching
network_access_allowed, _drf_user and check_user_stream_limits. Those tests
stay and are worth having; they are not what pins a parity row, because an
assertion about one Python function calling another does not port to Go.
Every assertion here is a status code or a response header.

A denial from this view is 401 or 403 ONLY -- subrequest_error_response
(authorize_views.py:95-99) maps every other status to 403 and puts the real
one in X-Authorize-Status, because ngx_http_auth_request_module can carry
nothing else. Assert both halves.
"""

import requests

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.proxy.internal_auth import HEADER_INTERNAL, internal_principal_token
from core.models import CoreSettings, NETWORK_ACCESS_KEY

from .harness.relay import RelayHarnessTestCase


class AuthorizeMatrixOverHttpTests(RelayHarnessTestCase):
    """Every row that no e2e spec pins, asserted on the hop's own wire.

    TransactionTestCase flushes every table after each test, so each test
    creates the rows it needs; setUp, not setUpTestData.
    """

    def setUp(self):
        super().setUp()
        self.plain = Channel.objects.create(name="row-plain", channel_number=9701)
        self.hidden = Channel.objects.create(
            name="row-hidden", channel_number=9702, hidden_from_output=True
        )
        self.adult = Channel.objects.create(
            name="row-adult", channel_number=9703, is_adult=True
        )

    def hop(self, uri, *, headers=None, cookies=None):
        """One auth_request subrequest, exactly as nginx makes it."""
        return requests.get(
            f"{self.live_server_url}/_dispatcharr/authorize",
            headers={"X-Original-URI": uri, **(headers or {})},
            cookies=cookies or {},
            timeout=10,
        )

    def assertDenied(self, response, real_status):
        # 403 on the wire, the real code in the header nginx's error_page
        # reads back. Asserting only the 403 would pass for the wrong reason.
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(response.headers.get("X-Authorize-Status"), str(real_status))

    # -- row 19: the Internal principal ---------------------------------

    def internal(self):
        """The STATIC header only, and the reason is the row.

        authorize_stream's is_internal is request_is_internal() alone
        (authorize.py:418, feeding _resolve_principal:309-310). The bound
        X-Dispatcharr-Internal-Request gates the five /proxy/relay/... and
        two /api/relay/... routes through IsInternalRelay
        (permissions.py:21-27) -- it is NOT part of this decision.

        WHY the streaming surface deliberately takes the weaker credential,
        from internal_auth.py:44-49: the DVR's stream fetch sends only the
        static header, because ffmpeg re-sends its -headers line on every
        reconnect for the life of a recording, and a 120-second windowed
        token would 403 that reconnect. A recording that survives an
        upstream blip is the behaviour being bought.

        This is exactly the kind of deliberate asymmetry a Go implementer
        would "fix" while porting -- requiring both headers everywhere
        looks strictly safer and silently breaks every long recording. The
        matrix exists to stop that, so adding the bound header to this test
        because it seems more correct would defeat the row.
        """
        return {HEADER_INTERNAL: internal_principal_token()}

    def test_the_internal_principal_streams_a_channel_hidden_from_output(self):
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}", headers=self.internal()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Channel"], str(self.hidden.uuid))
        # No user resolved: the DVR has no account, so no user_level,
        # membership or stream_limit is in the path of a recording.
        self.assertEqual(response.headers["X-Relay-User"], "")

    def test_the_internal_principal_streams_an_adult_channel(self):
        response = self.hop(
            f"/proxy/ts/stream/{self.adult.uuid}", headers=self.internal()
        )
        self.assertEqual(response.status_code, 200)

    def test_the_internal_principal_is_still_subject_to_the_streams_acl(self):
        # The one check it does NOT bypass (authorize.py:425-426). The ACL
        # is instance-wide state -- CoreSettings is one row per settings
        # GROUP -- so this test writes the group and the flush removes it.
        CoreSettings.objects.update_or_create(
            key=NETWORK_ACCESS_KEY, defaults={"value": {"STREAMS": "10.255.255.0/32"}}
        )
        # CoreSettings has no save() override, so the write alone leaves the
        # Redis-backed group cache stale -- and that cache outlives the
        # Postgres flush, poisoning every later test in this process.
        CoreSettings.invalidate_group_cache(NETWORK_ACCESS_KEY)
        self.addCleanup(CoreSettings.invalidate_group_cache, NETWORK_ACCESS_KEY)

        response = self.hop(
            f"/proxy/ts/stream/{self.plain.uuid}", headers=self.internal()
        )
        self.assertDenied(response, 403)

    def test_a_forged_internal_token_is_not_an_internal_principal(self):
        # The header is an HMAC of SECRET_KEY, not a flag: a caller who
        # merely sends the header name is anonymous, and anonymous is
        # refused a hidden channel.
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}",
            headers={HEADER_INTERNAL: "not-the-token"},
        )
        self.assertDenied(response, 403)

    # -- row 20: Admin ---------------------------------------------------

    def test_an_admin_streams_a_channel_hidden_from_output(self):
        admin = User.objects.create_user(
            username="row20-admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.client.force_login(admin)
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-User"], str(admin.id))

    def test_an_admin_streams_an_adult_channel_despite_hide_adult_content(self):
        # _apply_channel_checks returns at authorize.py:379-385, BEFORE the
        # adult check at :393 -- so an admin who set the preference for
        # themselves still previews the channel.
        admin = User.objects.create_user(
            username="row20-admin-adult",
            password="x",
            user_level=User.UserLevel.ADMIN,
            custom_properties={"hide_adult_content": True},
        )
        self.client.force_login(admin)
        response = self.hop(
            f"/proxy/ts/stream/{self.adult.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertEqual(response.status_code, 200)

    # -- row 23: Session, non-admin --------------------------------------

    def test_a_session_principal_streams_an_ordinary_channel(self):
        """The identity assertion is the test. The 200 is not.

        DO NOT TRIM THE X-Relay-User ASSERTION AS REDUNDANT. A 200 here
        proves nothing, because an ORDINARY channel streams to an
        ANONYMOUS request too (matrix row 24) -- so if the session
        principal were lost entirely, this request would still answer 200
        with bytes and this test would still pass. What would have
        silently stopped applying is every user-scoped check: user_level,
        Channel Profile membership, adult filtering and the stream limit.
        The one visible symptom would be a hidden_from_output channel
        still 403ing (it 403s for anonymous as well), so the working half
        keeps working while the invisible half is gone -- the worst
        failure signature an auth change can have.

        Only X-Relay-User carrying this user's id proves the principal
        survived. It survives because _session_user (authorize.py:268-287)
        re-reads the session with django.contrib.auth.get_user(request)
        instead of trusting http_request.user: @api_view's dispatch() runs
        perform_authentication even under @authentication_classes([]) and
        sets request.user to AnonymousUser BEFORE authorize_stream runs.
        _drf_user restores it on a miss for the same reason (:227-265).

        This is the assertion that catches the failure mode 2b's dev
        fallback could introduce -- POST /_dispatcharr/authorize-internal
        forwards a session cookie, and a receiving view that resolves the
        principal from request.user rather than from the session store
        would downgrade every session viewer to anonymous with no error
        anywhere.
        """
        user = User.objects.create_user(
            username="row23-standard", password="x", user_level=1
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{self.plain.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-User"], str(user.id))

    def test_a_session_principal_is_refused_a_hidden_channel(self):
        user = User.objects.create_user(
            username="row23-hidden", password="x", user_level=1
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertDenied(response, 403)

    def test_a_session_principal_is_refused_an_adult_channel_when_hiding_adult(self):
        user = User.objects.create_user(
            username="row23-adult",
            password="x",
            user_level=1,
            custom_properties={"hide_adult_content": True},
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{self.adult.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertDenied(response, 403)

    def test_a_session_principal_below_the_channels_user_level_is_refused(self):
        gated = Channel.objects.create(
            name="row23-gated", channel_number=9704, user_level=10
        )
        user = User.objects.create_user(
            username="row23-gated-user", password="x", user_level=1
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{gated.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertDenied(response, 403)

    # -- no row: a rejected credential is not an anonymous tune ----------

    def test_a_rejected_credential_is_401_and_never_an_anonymous_tune(self):
        """_drf_user's two meanings of "no user", asserted on the wire.

        authorize.py:227-265 RAISES AuthorizeDenied(401) for a credential
        an authenticator explicitly rejected (a malformed Bearer token, an
        unknown API key) and RETURNS None for one merely declined (nothing
        presented). A port that maps both to "anonymous" turns a rejected
        credential into a successful anonymous tune of any ordinary
        channel -- the same silent-downgrade shape as the session case
        above.

        PINS NO MATRIX ROW, deliberately: no row states this, and adding
        one would bump HIGHEST_ROW_ID against three sibling PRs in flight.
        Recommended for 2a-7 in this PR's description instead.
        """
        rejected = self.hop(
            f"/proxy/ts/stream/{self.plain.uuid}",
            headers={"Authorization": "Bearer not-a-token"},
        )
        self.assertDenied(rejected, 401)

        # The other meaning of "no user": nothing presented at all, which
        # is a legitimate anonymous tune of an ordinary channel (row 24).
        declined = self.hop(f"/proxy/ts/stream/{self.plain.uuid}")
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(declined.headers["X-Relay-User"], "")

    # -- row 21's outstanding live-root cell -----------------------------

    def test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root(self):
        # Row 21's Notes: the adult-filter half for the XC principal was
        # proven only by a catch-up-root test, which is off this matrix's
        # live-path scope and can never carry a 2d cutover obligation.
        # This is the live-root equivalent that row owed 2a-5.
        User.objects.create_user(
            username="row21-xc",
            password="x",
            user_level=1,
            custom_properties={
                "xc_password": "xc-secret",
                "hide_adult_content": True,
            },
        )
        response = self.hop(f"/live/row21-xc/xc-secret/{self.adult.id}")
        self.assertDenied(response, 403)
```

Two shapes in that file to be deliberate about:

- **The XC live root addresses a channel by its numeric `id`**, not its uuid
  (`authorize.py:366-369`: `Channel.objects.filter(id=int(identifier))`). `self.adult.id`, not
  `self.adult.uuid`.
- **`NETWORK_ACCESS_KEY`** is the `CoreSettings` group key for the ACL, defined at
  `core/models.py:211` alongside the other seven group keys. `10.255.255.0/32` is a CIDR that
  cannot contain `127.0.0.1` by construction.

- [ ] **Step 2: Run it**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_authorize_matrix_over_http -v2 --durations 15
```

Expected: PASS — twelve tests, every one well under 100 ms, because none of them tunes. If any is
slow, something is
initializing a channel that should not be; read `--durations` before changing anything.

If `test_a_session_principal_streams_an_ordinary_channel` returns a 200 with an empty
`X-Relay-User`, the session cookie did not reach the live server. Use the `SessionStore` fallback
described above before assuming a code defect.

- [ ] **Step 3: Prove the row-19 and row-20 bypasses would be caught**

Comment out `authorize.py:376-377` (the `INTERNAL_PRINCIPAL` early return in
`_apply_channel_checks`) and confirm
`test_the_internal_principal_streams_a_channel_hidden_from_output` fails. **It fails with a 500,
not a 403** — `INTERNAL_PRINCIPAL` is a bare `object()` (`authorize.py:102`), so the next line's
`user.user_level` raises `AttributeError` before any check runs. Red either way, which is what the
falsification needs; do not "fix" the test to expect a 403. **Revert.** Then comment out `:379-385`
(the admin early return) and confirm `test_an_admin_streams_a_channel_hidden_from_output` fails —
that one really is a 403, the admin being a real `User`. **Revert**, and confirm
`git diff apps/proxy/authorize.py` is empty.

- [ ] **Step 4: Close rows 19, 20 and 23**

Row 19's `Pin` cell:

```
`apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_the_internal_principal_streams_a_channel_hidden_from_output`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_the_internal_principal_is_still_subject_to_the_streams_acl`
```

Row 20's `Pin` cell — three references, the third landing in Task 4, so **write the first two now
and add the third in Task 4 Step 4**:

```
`apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_admin_streams_a_channel_hidden_from_output`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_admin_streams_an_adult_channel_despite_hide_adult_content`
```

Row 23's `Pin` cell:

```
`apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_a_session_principal_streams_an_ordinary_channel`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_a_session_principal_is_refused_a_hidden_channel`
```

**Row 21's line is NOT edited — deliberately, and this is a change from an earlier draft of this
plan.** Row 21 is at `docs/relay-parity-matrix.md:185` and row 11 is at `:184` — **one line
apart** — and row 11's own Notes invite 2a-6 to re-pin it ("2a-6 may re-pin this to a harness test;
the existing e2e spec stands until it does"). The matrix's header comment records the measured
rule: *git conflicts on two edits ONE line apart and merges cleanly at TWO.* So editing row 21 here
would conflict with 2a-6 for a Notes-only change the guard never reads. The test is written; the
row's line is left alone. **Say in the PR description that row 21's Notes still read "2a-5 owes a
live-root equivalent instead", that the obligation is discharged by
`test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root`, and that **2b-3 is the
expected corrector** — it is the last PR the spec has touching this file (it closes row 18, the
final `owed:` row), so the sentence can be fixed in a diff that is already there. Name 2b-3
explicitly rather than "whichever PR next edits that block": an obligation addressed to nobody in
particular is how row 21 got into this state in the first place.**

**Also reframe the `Notes` cell on each of rows 19, 20 and 23** — same line, so no extra conflict
surface. Each currently opens `No \`e2e/tests/\` spec pins this principal — see ruling 13`, which
reads as "nothing pins this row" and is false. Replace that clause, on each of the three, with:

```
No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13
```

Keep whatever else the cell already says (row 23 carries a second sentence about `_session_user`;
leave it). **Row 14's Notes carry no such clause and are not edited** — check before assuming, the
reframe applies only where the clause is actually present.

- [ ] **Step 5: Run the guard, then commit**

```bash
cd e2e && npx playwright test --project=guards parity-matrix
```

```bash
git add apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py docs/relay-parity-matrix.md
```

```bash
git commit -F <msgfile>
```

Subject: `test(phase2): pin the Internal, Admin and Session principals on the hop (matrix rows 19, 20, 23)`.

---

## Task 4: Rows 16 and 25 — the stream-by-hash shape, and row 20's stream limit

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py`
- Modify: `docs/relay-parity-matrix.md` (rows 16 and 25; row 20's `Pin` cell gains its third
  reference)

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase` (`make_channel`, `tuned`, `stand_in`),
  `harness.process.stand_in_stream_profile`, `apps.accounts.models.User`,
  `rest_framework_simplejwt.tokens.RefreshToken`.
- Produces: nothing.

**What rows 16 and 25 say, and how they differ.** Row 16 states the *shape*:
`/proxy/ts/stream/<stream_hash>` — the admin UI's single-stream preview — has **no channel at all**,
so the ACL and the per-user stream limit apply and **no channel check of any kind** does. Row 25 is
the matrix cell that has to stay true after 2b extends `next-source`'s identifier resolution: any
principal, ACL applied, limit enforced when a principal resolved, no channel check.

The code: `get_stream_object` (`apps/proxy/next_source.py:69-79`, re-exported through
`apps/proxy/live_proxy/url_utils.py:25`) tries `Channel` by uuid and falls back to `Stream` by
`stream_hash`. `_resolve_channel` (`authorize.py:340-349`) returns `(None, True)` for that case, so
`authorize_stream`'s `if channel is not None:` at `:434` never runs `_apply_channel_checks` — while
the ACL at `:425-426` and the stream limit at `:436-442` run unconditionally. The limit's
`media_id` is `str(identifier)`, i.e. the hash itself (`:437`).

**The sharpener that makes this a real test rather than a restatement.** The harness's
`make_channel` builds a `Channel` **and** a `Stream` with a `stream_hash`, joined by a
`ChannelStream`. Mark that channel `hidden_from_output=True` and then tune the **stream's hash**:
if any channel check leaked into the hash path, the tune would 403. It streams. That is row 16's
"no channel check of any kind", demonstrated rather than asserted.

**Row 20's third cell lands here** because this is the one test in the PR that holds a live client
open, and the stream limit can only be observed against one. The chain is real end to end:
`authorize_stream` → `check_user_stream_limits` (`apps/proxy/utils.py:410-412`) →
`get_user_active_connections` → `_live_connections` → `relay_client.list_channels(all_clients=True)`
→ a signed `GET /proxy/relay/channels?clients=all` over HTTP → `build_live_channel_stats_data` →
Redis. Nothing in that chain is stubbed.

`check_user_stream_limits` is a no-op unless `user.stream_limit > 0` (`apps/proxy/utils.py:412`),
so the admin in these tests is created with `stream_limit=1`.

- [ ] **Step 1: Write the failing test**

```python
"""The stream-by-hash authorization shape (rows 16 and 25), and the one cell
of row 20 that needs a live client to observe (the admin's stream limit).

/proxy/ts/stream/<stream_hash> is the admin UI's single-stream preview. It
resolves a Stream, not a Channel (next_source.py:69-79), so
authorize_stream's channel checks never run (authorize.py:431) while the
ACL (:425-426) and the stream limit (:436-442) still do.

The channel that owns the stream is marked hidden_from_output here on
purpose: if any channel check leaked into the hash path, the tune would 403
instead of streaming.
"""

import requests

from apps.accounts.models import User
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer
from core.models import CoreSettings, USER_LIMITS_SETTINGS_KEY

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


class StreamByHashAuthorizationTests(RelayHarnessTestCase):
    def setUp(self):
        super().setUp()
        self.profile = stand_in_stream_profile()
        self.channel = self.make_channel(
            upstream_url=self.upstream.url, profile=self.profile
        )
        # The owning channel is hidden: a leaked channel check would 403
        # the hash tune below, so this is the assertion's teeth.
        self.channel.hidden_from_output = True
        self.channel.save(update_fields=["hidden_from_output"])
        self.stream = self.channel.streams.first()
        self.assertIsNotNone(self.stream, "make_channel attaches exactly one Stream")

    def hop(self, uri, **headers):
        return requests.get(
            f"{self.live_server_url}/_dispatcharr/authorize",
            headers={"X-Original-URI": uri, **headers},
            timeout=10,
        )

    def assertDenied(self, response, real_status):
        # Repeated from the Task 3 module rather than shared: these are two
        # independent test modules and nothing crosses between them.
        # subrequest_error_response (authorize_views.py:95-99) maps every
        # non-401 status to 403 and puts the real one in the header, so
        # asserting only the 403 would pass for the wrong reason.
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(response.headers.get("X-Authorize-Status"), str(real_status))

    def a_client_stop_was_requested(self, identifier):
        """True once the relay has been asked to stop ANY client on `identifier`.

        Deliberately a scan rather than a named client id: the held client's
        id is minted inside the hop and never reaches this test, and inventing
        a way to learn it would be more machinery than the assertion is worth.
        RedisKeys.client_stop(channel, client) is
        live:channel:{channel}:client:{client}:stop, so the prefix is the
        question "was anyone stopped here".
        """
        client = ProxyServer.get_instance().redis_client
        pattern = f"live:channel:{identifier}:client:*:stop"
        return any(True for _ in client.scan_iter(match=pattern, count=500))

    def test_a_stream_hash_tune_applies_no_channel_check(self):
        # Row 16. The hop resolves a Stream, so X-Relay-Channel is empty --
        # there is no channel uuid to name -- and the request is allowed
        # even though the channel carrying this stream is hidden.
        response = self.hop(f"/proxy/ts/stream/{self.stream.stream_hash}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Channel"], "")
        self.assertTrue(response.headers["X-Relay-Client"].startswith("client_"))

        # And it really streams: the byte path takes the same identifier
        # straight through, keyed on the hash rather than a channel uuid.
        with self.stand_in():
            body = requests.get(
                f"{self.live_server_url}/proxy/ts/stream/{self.stream.stream_hash}",
                stream=True,
                timeout=20,
            )
            self.addCleanup(body.close)
            self.assertEqual(body.status_code, 200)
            received = b""
            for chunk in body.iter_content(chunk_size=4096):
                received += chunk
                if len(received) >= 20 * 188:
                    break
            self.assertGreaterEqual(len(received), 20 * 188)
            self.assertEqual(received[0], 0x47, "the first byte is a TS sync byte")

    def test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune(self):
        """The production default, which is NOT "the new tune is refused".

        check_user_stream_limits (apps/proxy/utils.py:463-476) reads
        terminate_on_limit_exceeded, whose default is True
        (core/models.py:762-768). At the limit it therefore calls
        attempt_stream_termination, which stops the held client and returns
        True -- so the hop ADMITS the new tune and the old one is dropped.
        "The stream limit is enforced" means "a slot is freed", not "you are
        turned away", and rows 20 and 25 are held to the default.

        Pinning only the refusal path would pin the branch operators do not
        run.
        """
        admin = User.objects.create_user(
            username="hash-admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
            stream_limit=1,
        )
        self.client.force_login(admin)
        session = self.client.cookies["sessionid"].value

        with self.stand_in():
            held = requests.get(
                f"{self.live_server_url}/proxy/ts/stream/{self.stream.stream_hash}",
                cookies={"sessionid": session},
                stream=True,
                timeout=20,
            )
            self.addCleanup(held.close)
            self.assertEqual(held.status_code, 200)
            next(held.iter_content(chunk_size=188))

            # The whole D4 loop runs for real: authorize_stream ->
            # check_user_stream_limits -> _live_connections ->
            # relay_client.list_channels() -> a signed HTTP call to this same
            # process's GET /proxy/relay/channels?clients=all.
            second = self.hop(
                f"/proxy/ts/stream/{self.channel.uuid}",
                **{"Cookie": f"sessionid={session}"},
            )
            self.assertEqual(
                second.status_code, 200,
                "the default frees a slot rather than refusing the tune",
            )

            # And the slot really was freed at the held client's expense:
            # the relay has been asked to stop a client on that channel.
            wait_until(
                lambda: self.a_client_stop_was_requested(self.stream.stream_hash),
                timeout=10,
                what="the held client to be stopped to free the slot",
            )

        self.stop_channel(self.channel)

    def test_the_stream_limit_refuses_when_termination_is_disabled(self):
        """The other branch, which an operator selects deliberately.

        With terminate_on_limit_exceeded False, check_user_stream_limits
        returns False at :464-465 without terminating anything, and
        authorize_stream raises AuthorizeDenied(429) -- which the nginx-facing
        view can only carry as 403 plus X-Authorize-Status: 429.

        user_limit_settings is a CoreSettings GROUP, so this write is
        instance-wide and the flush does not undo the Redis cache (see
        Global Constraints); addCleanup does.
        """
        CoreSettings.objects.update_or_create(
            key=USER_LIMITS_SETTINGS_KEY,
            defaults={"value": {"terminate_on_limit_exceeded": False}},
        )
        CoreSettings.invalidate_group_cache(USER_LIMITS_SETTINGS_KEY)
        self.addCleanup(
            CoreSettings.invalidate_group_cache, USER_LIMITS_SETTINGS_KEY
        )

        admin = User.objects.create_user(
            username="hash-admin-strict",
            password="x",
            user_level=User.UserLevel.ADMIN,
            stream_limit=1,
        )
        self.client.force_login(admin)
        session = self.client.cookies["sessionid"].value

        with self.stand_in():
            held = requests.get(
                f"{self.live_server_url}/proxy/ts/stream/{self.stream.stream_hash}",
                cookies={"sessionid": session},
                stream=True,
                timeout=20,
            )
            self.addCleanup(held.close)
            self.assertEqual(held.status_code, 200)
            next(held.iter_content(chunk_size=188))

            # Row 25: enforced for a principal on the by-hash surface.
            second = self.hop(
                f"/proxy/ts/stream/{self.stream.stream_hash}",
                **{"Cookie": f"sessionid={session}"},
            )
            self.assertDenied(second, 429)

            # Row 20: an admin's bypasses do not reach the stream limit. Same
            # held client, a different identifier, so this is the limit and
            # not a same-channel exemption.
            channel_attempt = self.hop(
                f"/proxy/ts/stream/{self.channel.uuid}",
                **{"Cookie": f"sessionid={session}"},
            )
            self.assertDenied(channel_attempt, 429)

        self.stop_channel(self.channel)
```

Two notes on that code:

- **`self.hop(..., Cookie=...)`** rather than `requests`' `cookies=`: `hop` above takes extra
  headers, and passing the cookie as a header keeps one helper. If you prefer, give `hop` a
  `cookies=` parameter — but then use it consistently.
- **`self.stop_channel(self.channel)`** stops the *channel*, whereas the hash tune ran under the
  hash as its identifier. `RelayHarnessTestCase._cleanup_channels` deletes
  `live:channel:{channel.uuid}:*` and will not reach `live:channel:{stream_hash}:*`. **Add an
  explicit cleanup for the hash identifier in `setUp`:**

  ```python
  from apps.proxy.live_proxy.server import ProxyServer

  def _drop_hash_keys(self):
      server = ProxyServer.get_instance()
      try:
          server.stop_channel(self.stream.stream_hash)
      except Exception:
          pass
      client = server.redis_client
      if client is not None:
          for key in client.scan_iter(
              match=f"live:channel:{self.stream.stream_hash}:*", count=500
          ):
              client.delete(key)
  ```

  registered with `self.addCleanup(self._drop_hash_keys)` at the end of `setUp`. Without it the
  next test in the process sees a stale channel under that identifier — and `make_channel` mints a
  fresh hash per call, so this only ever matters within one test, but leaving relay state behind is
  how the singleton bites.

- [ ] **Step 2: Run it**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_stream_by_hash_authorization -v2 --durations 5
```

Expected: PASS. If the hash tune answers 500 rather than streaming, read
`apps/proxy/next_source.py:410-470` — `resolve_initial_source`'s `isinstance(channel_or_stream,
Stream)` branch requires the `Stream` to have an `m3u_account` (`:430-432`), which `make_channel`
supplies. Do not paper over a failure here; the row is the claim that this path works.

If the second hop answers 200 rather than a 429, the held client was not visible to
`_live_connections`. Check it directly before changing the test:

```bash
# from inside the container, while nothing else is running
redis-cli --scan --pattern 'live:channel:*:clients*'
```

- [ ] **Step 3: Prove the limit assertion has teeth**

Change the admin's `stream_limit` to `0` in
`test_the_stream_limit_refuses_when_termination_is_disabled` and confirm both 429 assertions fail
(the hop answers 200) — `check_user_stream_limits` returns early for a non-positive limit
(`apps/proxy/utils.py:412`). **Revert to 1.** A test-only edit, so no production diff to check.

Then prove the two tests really are opposite branches rather than one behaviour written twice:
**delete the `terminate_on_limit_exceeded: False` write** from that test and confirm it now fails
with a 200, because the default terminates a client and admits the tune. **Restore it.** If both
tests pass with the setting removed, one of them is not asserting what its name says.

- [ ] **Step 4: Close rows 16 and 25, and finish row 20's cell**

Row 16's `Pin` cell:

```
`apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_a_stream_hash_tune_applies_no_channel_check`
```

Row 25's `Pin` cell:

```
`apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_a_stream_hash_tune_applies_no_channel_check`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_refuses_when_termination_is_disabled`
```

Row 20's `Pin` cell — append the third reference to the two Task 3 wrote:

```
, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune`
```

**Reframe row 25's `Notes` cell the same way Task 3 Step 4 reframes rows 19, 20 and 23** — it
carries the identical `No \`e2e/tests/\` spec pins this principal` clause and the identical
problem. Row 16's Notes carry no such clause and are not edited.

- [ ] **Step 5: Run the guard, then commit**

```bash
cd e2e && npx playwright test --project=guards parity-matrix
```

```bash
git add apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py docs/relay-parity-matrix.md
```

```bash
git commit -F <msgfile>
```

Subject: `test(phase2): pin the stream-by-hash shape and the admin's stream limit (matrix rows 16, 25)`.

---

## Task 5: Row 15 — `stream_xc` authorizes once and hands its decision on

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_xc_decision_handoff.py`
- Modify: `docs/relay-parity-matrix.md` (row 15 only)

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase`, `harness.process.stand_in_stream_profile`,
  `apps.accounts.models.User`.
- Produces: nothing.

**The mechanism.** `stream_xc` (`views.py:819`) calls `resolve_authorization` itself under
`SURFACE_LIVE_XC` (`:825-831`) and then calls `stream_ts` with `decision=decision` (`:845-851`).
`stream_ts` re-runs the hop **only** when `decision is None` (`views.py:162-166`) — the comment
there says why: "re-running the hop would re-check a limit that has not changed and mint a second
client id."

**Finding the observable, because the obvious one is not observable.** "Does not mint a second
client id" has no visible consequence: `stream_ts` registers exactly one client either way, and the
extra `mint_client_id()` call would simply be discarded. **Do not write a test that pretends
otherwise** — an assertion on `client_count == 1` passes whether or not the hand-off exists and
therefore proves nothing.

What *is* observable is the first clause, and sharply. If `stream_ts` re-ran the hop it would run it
under `SURFACE_LIVE`, not `SURFACE_LIVE_XC` — and **the XC credentials live in the URL path
segments, which `SURFACE_LIVE` never reads**. `_drf_user` finds no header credential and
`_session_user` finds no session, so the re-run resolves **anonymous** (`authorize.py:316`;
`SURFACE_LIVE` is not in `_PRINCIPAL_REQUIRED`, `:82-84`, so the 401 at `:325-326` does not
fire either). An anonymous principal is
refused a channel marked `hidden_from_output` — the one check anonymous also fails
(`authorize.py:386-389`).

So: **an admin XC user tuning a `hidden_from_output` channel over the XC live root gets 200 and
bytes. Delete `decision=decision` from `views.py:850` and the same request answers 403.** That is
the pin, and Step 3 makes you prove it.

This test is also the PR's only end-to-end proof that an admin's `hidden_from_output` bypass
(row 20) reaches the byte path, not just the hop.

- [ ] **Step 1: Write the failing test**

```python
"""stream_xc authorizes once and hands its decision to stream_ts (row 15).

The observable consequence, and the only one: the XC credentials live in
the URL path segments, which SURFACE_LIVE never reads. A second hop under
SURFACE_LIVE would therefore resolve anonymous -- and anonymous is refused a
channel marked hidden_from_output (authorize.py:386-389). So an ADMIN XC
user tuning a HIDDEN channel over the XC live root is 200 with the hand-off
and 403 without it.

The row's second clause -- "does not mint a second client id" -- has no
externally observable consequence: stream_ts registers exactly one client
either way, and a discarded extra mint_client_id() call is invisible on the
wire. It is recorded here rather than asserted, because a test that appeared
to assert it would pass whether or not the hand-off existed.
"""

import requests

from apps.accounts.models import User

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase


XC_USERNAME = "row15-xc-admin"
XC_PASSWORD = "row15-xc-secret"


class XcDecisionHandoffTests(RelayHarnessTestCase):
    def test_an_xc_tune_is_not_re_authorized_as_an_anonymous_live_tune(self):
        User.objects.create_user(
            username=XC_USERNAME,
            password="x",
            user_level=User.UserLevel.ADMIN,
            custom_properties={"xc_password": XC_PASSWORD},
        )
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            channel.hidden_from_output = True
            channel.save(update_fields=["hidden_from_output"])

            # The XC live root addresses a channel by its NUMERIC id, and
            # the extension only chooses the output format
            # (authorize_views.py:176-183, views.py:821-822).
            url = (
                f"{self.live_server_url}"
                f"/live/{XC_USERNAME}/{XC_PASSWORD}/{channel.id}.ts"
            )
            response = requests.get(url, stream=True, timeout=20)
            self.addCleanup(response.close)

            # Only a non-200 has a body worth reading: a live 200 never ends.
            if response.status_code != 200:
                self.fail(
                    "the XC tune was re-authorized as an anonymous live tune: "
                    f"{response.status_code} {response.text[:200]}"
                )

            received = b""
            for chunk in response.iter_content(chunk_size=4096):
                received += chunk
                if len(received) >= 20 * 188:
                    break
            self.assertGreaterEqual(len(received), 20 * 188)
            self.assertEqual(received[0], 0x47, "the first byte is a TS sync byte")

        self.stop_channel(channel)
```

- [ ] **Step 2: Run it**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_xc_decision_handoff -v2 --durations 5
```

Expected: PASS. A 401 means `resolve_xc_user` did not match — check that `xc_password` landed in
`custom_properties` and that the username in the URL matches the row exactly.

- [ ] **Step 3: Prove the pin — this is the whole point of the task**

Delete `decision=decision,` from `apps/proxy/live_proxy/views.py:850` (inside `stream_xc`'s
`return stream_ts(...)` call) and re-run. **Expected: the test fails, naming a 403.** Paste that
failure into the PR description — it is the evidence that this row is pinned rather than merely
described. **Revert**, and confirm `git diff apps/proxy/live_proxy/views.py` is empty.

- [ ] **Step 4: Close row 15 in the matrix**

Row 15's `Pin` cell:

```
`apps/proxy/live_proxy/tests/test_xc_decision_handoff.py::test_an_xc_tune_is_not_re_authorized_as_an_anonymous_live_tune`
```

Then edit row 15's `Notes` cell so it does not claim more than the test proves. Append, inside the
existing cell (still one line, still no padding):

```
 The second clause -- no second client id -- has no externally observable consequence and is recorded, not pinned; the pin is the anonymous-re-authorization case, which 403s without the hand-off
```

- [ ] **Step 5: Run the guard, then commit**

```bash
cd e2e && npx playwright test --project=guards parity-matrix
```

```bash
git add apps/proxy/live_proxy/tests/test_xc_decision_handoff.py docs/relay-parity-matrix.md
```

```bash
git commit -F <msgfile>
```

Subject: `test(phase2): pin the stream_xc decision hand-off (matrix row 15)`.

---

## Task 6: `server.py` — zombie detection and the channel registry

The first of three `server.py` coverage tasks. **No tunes**: every behaviour here is a decision
about Redis state, driven through the internal control API.

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_server_registry.py`

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase`, `RedisKeys`, `ChannelMetadataField`,
  `ChannelState`, `ProxyServer`, the local `_signed` helper.
- Produces: nothing.

**What `check_if_channel_exists` (`server.py:881-969`) decides, and how each branch is reached.**
Every one of these is reached through `DELETE /proxy/relay/channels/<identifier>` →
`ChannelService.stop_channel` (`services/channel_service.py:565`) → `check_if_channel_exists` at
`:578`, whose answer decides the JSON the route returns (`relay_views.py:146-148`,
`RelayStopResponseSerializer`).

| Redis state seeded | Branch | `server.py` lines | Observable |
|---|---|---|---|
| `state` in the valid set, `owner` names a worker whose `live:worker:<id>:heartbeat` key exists | present | `:909-914` | response `status: "success"` |
| same, but **no** heartbeat key | **zombie** → `_clean_zombie_channel` | `:915-931`, `:1022-1038` | response `status: "error"`, and the metadata key is **gone** afterwards |
| `state` = `stopped` or `error` | terminal | `:932-935` | `status: "error"` |
| `state` outside every known value, with `state_changed_at` more than 60 s old | stale → zombie | `:936-947` | `status: "error"`, metadata gone |
| no metadata key, but `live:channel:<id>:clients` exists | orphaned keys → `_clean_redis_keys` | `:951-967`, `:2391-2426` | `status: "error"`, the clients key gone |
| nothing at all | absent | `:969` | `status: "error"` |

The heartbeat key's shape is `RedisKeys.worker_heartbeat(worker_id)` → `live:worker:{id}:heartbeat`
(`redis_keys.py:78-80`); `check_if_channel_exists:910` builds the same string inline. Use
`RedisKeys.worker_heartbeat` in the test so the two stay tied.

- [ ] **Step 1: Write the failing test**

```python
"""server.py's channel registry and zombie detection (Gate 2 coverage).

check_if_channel_exists (server.py:881-969) is the relay's answer to "is
this channel real, and is anyone still running it". Every branch is a
decision about Redis state, so every one is reachable by seeding that state
and asking the question over HTTP -- DELETE /proxy/relay/channels/<id>,
whose JSON says which way the answer went.

NOT a matrix row. Ownership leases and cross-worker heartbeats are deleted
outright by spec D2 (the Go relay is one process, ownership is a
map[uuid]*Channel behind a sync.RWMutex), so there is no Go behaviour to
hold to parity here. What survives the port is the requirement these tests
describe: a channel nobody is running must not be reported as running, and
its keys must not outlive it. These tests are deleted with
apps/proxy/live_proxy/ in 2d.
"""

import time
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.relay import RelayHarnessTestCase


def _signed(method, path, body=b""):
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


# check_if_channel_exists:944 treats a channel in an unrecognised state as
# stale once it has been there longer than this. Read from the code, not
# invented: server.py:944 is `if state_age > 60:`.
STALE_STATE_SECONDS = 60


class ChannelRegistryTests(RelayHarnessTestCase):
    def setUp(self):
        super().setUp()
        self.redis = ProxyServer.get_instance().redis_client
        self.assertIsNotNone(self.redis)
        self.identifier = str(uuid_module.uuid4())
        self.addCleanup(self._drop_keys)

    def _drop_keys(self):
        for key in self.redis.scan_iter(
            match=f"live:channel:{self.identifier}:*", count=500
        ):
            self.redis.delete(key)

    def _seed_metadata(self, **fields):
        self.redis.hset(
            RedisKeys.channel_metadata(self.identifier), mapping=fields
        )

    def _stop(self):
        path = f"/proxy/relay/channels/{self.identifier}"
        response = requests.delete(
            self.live_server_url + path, headers=_signed("DELETE", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.json()

    def _metadata_exists(self):
        return bool(self.redis.exists(RedisKeys.channel_metadata(self.identifier)))

    def test_a_channel_whose_owner_still_heartbeats_is_reported_present(self):
        # NOTE the shape of the assertion, and do not add a metadata check
        # here: on the success path stop_channel goes on to run
        # _clean_redis_keys (server.py:1831), which DELETES the hash. A
        # `status: success` and a surviving metadata key are mutually
        # exclusive by construction. previous_state is the field that proves
        # the registry saw the channel, and it comes back in the body.
        worker = f"worker-{uuid_module.uuid4().hex[:8]}"
        heartbeat = RedisKeys.worker_heartbeat(worker)
        self.redis.setex(heartbeat, 30, "1")
        self.addCleanup(self.redis.delete, heartbeat)
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.OWNER: worker,
        })

        result = self._stop()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["previous_state"], {"state": ChannelState.ACTIVE})

    def test_a_channel_whose_owner_stopped_heartbeating_is_cleaned_as_a_zombie(self):
        # No heartbeat key for the named owner: server.py:915-931 calls it a
        # zombie and _clean_zombie_channel deletes its keys.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.OWNER: "worker-that-died",
        })

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(
            self._metadata_exists(), "the zombie's metadata key must be gone"
        )

    def test_a_zombie_with_clients_still_attached_is_cleaned(self):
        # The scard > 0 arm of the same branch (server.py:922-928): the
        # comment there reserves ownership takeover for the future and
        # cleans up "to be safe" today. Pinned as it is, per spec D5.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.OWNER: "worker-that-died",
        })
        self.redis.sadd(RedisKeys.clients(self.identifier), "client_ghost")

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(self._metadata_exists())

    def test_a_channel_in_a_terminal_state_is_reported_absent(self):
        # server.py:932-935: stopped/error mean "clean up and reinitialize",
        # and unlike the zombie branch this one leaves the metadata alone.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.STOPPED,
            ChannelMetadataField.OWNER: "anyone",
        })

        self.assertEqual(self._stop()["status"], "error")

    def test_a_channel_stuck_in_an_unrecognised_state_becomes_a_zombie(self):
        # server.py:936-947. The age is derived from the threshold in the
        # code, never written as a wall-clock literal.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: "a-state-no-constant-defines",
            ChannelMetadataField.STATE_CHANGED_AT: str(
                time.time() - (STALE_STATE_SECONDS + 1)
            ),
        })

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(self._metadata_exists())

    def test_a_channel_recently_moved_to_an_unrecognised_state_is_reported_present(self):
        # The other side of the same branch (server.py:949-950): still in
        # progress, so check_if_channel_exists answers True and the stop
        # proceeds. previous_state carries the state it saw -- which is the
        # only thing that distinguishes this from the stale case, since the
        # stop then deletes the hash either way (server.py:1831).
        self._seed_metadata(**{
            ChannelMetadataField.STATE: "a-state-no-constant-defines",
            ChannelMetadataField.STATE_CHANGED_AT: str(time.time()),
        })

        result = self._stop()
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            result["previous_state"], {"state": "a-state-no-constant-defines"}
        )

    def test_orphaned_keys_without_metadata_are_cleaned_up(self):
        # server.py:951-967 -> _clean_redis_keys (:2391-2426). A clients
        # set with no metadata hash is the shape a half-finished teardown
        # leaves behind.
        clients_key = RedisKeys.clients(self.identifier)
        self.redis.sadd(clients_key, "client_orphan")

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(self.redis.exists(clients_key))

    def test_an_identifier_nothing_knows_about_is_reported_absent(self):
        self.assertEqual(self._stop()["status"], "error")
```

- [ ] **Step 2: Run it**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_server_registry -v2 --durations 10
```

Expected: PASS. **If a success-path test fails on a metadata assertion, the diagnosis is not the
cleanup thread** — an earlier draft of this plan said it was, and that was wrong in a way that
would have sent you chasing a race that is not there. `ChannelService.stop_channel` calls
`proxy_server.stop_channel`, whose `_clean_redis_keys` (`server.py:1831`) deletes the hash on the
success path, so `status: "success"` and a surviving metadata key cannot both be true. Assert
`previous_state` instead, as the two tests above do. The metadata assertions are correct **only**
on the zombie and orphan tests, where `check_if_channel_exists` answered False and the deletion was
the cleanup, not the stop.

- [ ] **Step 3: Confirm the coverage moved**

```bash
<dexec> bash -lc 'cd /repo && scripts/coverage_live_path.sh --label apps.proxy.live_proxy.tests && scripts/coverage_live_path.sh --report'
```

Read the `apps/proxy/live_proxy/server.py` row. This is a partial measurement (one label of three)
and is only for your own feedback; **the gate is the three-label run in Task 9**.

- [ ] **Step 4: Commit**

```bash
git add apps/proxy/live_proxy/tests/test_server_registry.py
```

```bash
git commit -F <msgfile>
```

Subject: `test(phase2): cover server.py's channel registry and zombie detection`.

---

## Task 7: `server.py` — the event listener loop

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_server_event_listener.py`

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase` (`make_channel`, `tuned`, `stand_in`,
  `wait_until`), `harness.process.stand_in_stream_profile`, `RedisKeys`, `EventType`,
  `ChannelMetadataField`, `ChannelState`, `ProxyServer`, the local `_signed` helper.
- Produces: nothing.

**How the listener is structured, verified by indentation.** `_start_event_listener`
(`server.py:173`) starts a daemon thread running `event_listener` (`:178`), which `psubscribe`s to
`live:events:*` and, for each message, parses JSON at `:238` and then enters
`if channel_id and event_type:` (`:243`) → **`if self.am_i_owner(channel_id):` (`:245`)**. Every
event branch is inside that ownership guard — `CLIENT_CONNECTED` (`:246`), `CLIENT_DISCONNECTED`
(`:253`), `STREAM_SWITCH` (`:262`), `CHANNEL_STOP` (`:359`), `CLIENT_STOP` (`:402`),
`ENSURE_OUTPUT_FORMAT` (`:420`), `ENSURE_OUTPUT_PROFILE` (`:426`) — at indent 36 under the guard's
indent 32.

**That is worth recording as a finding, not just a fact.** The `CHANNEL_STOP` branch contains an
arm explicitly labelled "Non-owner worker cleaning local resources" (`:382-389`), which cannot run
for a non-owner, because a non-owner never gets past `:245`. It is reachable only by a worker that
owns the channel but has already dropped its stream manager. Say so in the PR description; do not
"fix" it — spec D5 is strict parity, defects included.

**So a test reaches the listener by owning the channel and publishing an event that names another
worker as its requester.** Publishing onto `live:events:<id>` is not a back door: it is the
architecture's own inter-worker interface, and it is exactly what
`ChannelService._publish_channel_stop_event` (`services/channel_service.py:969-990`) and
`_publish_client_stop_event` (`:992-1013`) put on that channel. Mirror their payload shape rather
than inventing one.

Note the asymmetry in those payloads, which the tests below depend on:
`_publish_channel_stop_event` and `_publish_client_stop_event` set **`requester_worker_id`**, and
the `CHANNEL_STOP` branch ignores an event whose `requester_worker_id` equals its own worker id
(`:366-372`); `_publish_stream_switch_event` (`:942-966`) sets **`requester`** and the
`STREAM_SWITCH` branch never reads it, so a self-published switch **is** processed.

**One tune, for the largest branch.** `STREAM_SWITCH` (`:252-358`) holds **48** of the listener's
120 missed statements — the largest single block in it — and needs a
live `StreamManager` in `self.stream_managers`. It is this task's one tune, and the first thing to
drop if the time budget is over (§ Keeping the suite fast).

- [ ] **Step 1: Write the failing test**

```python
"""server.py's Redis event listener loop (Gate 2 coverage).

The listener (server.py:173-470) is the relay's inter-worker interface: a
daemon thread psubscribed to live:events:*, acting on each event only when
this worker owns the channel (the guard at :245, which every branch sits
under). Tests reach it by owning the channel and publishing the payload
another worker would publish -- the shapes ChannelService._publish_*
(services/channel_service.py:942-1013) put on that channel, mirrored rather
than invented.

NOT a matrix row. Spec D2 deletes the multi-worker protocol outright: the Go
relay is one process, so there is no second worker to hear from. What ports
is the requirement, not the mechanism -- an admin's stop must reach the
worker serving the stream. These tests are deleted with
apps/proxy/live_proxy/ in 2d.

The listener runs on its own OS thread, so every assertion here is a
wait_until on an observable, never a sleep.
"""

import json
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.live_proxy.constants import (
    ChannelMetadataField,
    ChannelState,
    EventType,
)
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


def _signed(method, path, body=b""):
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


class EventListenerTests(RelayHarnessTestCase):
    """Events on a channel this worker owns, published as another worker."""

    def setUp(self):
        super().setUp()
        self.server = ProxyServer.get_instance()
        self.redis = self.server.redis_client
        self.assertIsNotNone(self.redis)
        self.identifier = str(uuid_module.uuid4())
        self.addCleanup(self._drop_keys)

        # Own the channel, and give the owner a heartbeat so
        # check_if_channel_exists calls it present rather than a zombie.
        self.heartbeat = RedisKeys.worker_heartbeat(self.server.worker_id)
        self.redis.setex(self.heartbeat, 60, "1")
        self.addCleanup(self.redis.delete, self.heartbeat)
        self.redis.setex(
            RedisKeys.channel_owner(self.identifier), 60, self.server.worker_id
        )
        self.redis.hset(
            RedisKeys.channel_metadata(self.identifier),
            mapping={
                ChannelMetadataField.STATE: ChannelState.ACTIVE,
                ChannelMetadataField.OWNER: self.server.worker_id,
            },
        )

    def _drop_keys(self):
        for key in self.redis.scan_iter(
            match=f"live:channel:{self.identifier}:*", count=500
        ):
            self.redis.delete(key)

    def _publish(self, payload):
        self.redis.publish(
            RedisKeys.events_channel(self.identifier), json.dumps(payload)
        )

    def test_the_admin_stop_route_publishes_when_the_client_is_not_local(self):
        """The HTTP half, and ONLY the HTTP half.

        This test deliberately does NOT wait for the stop key, and an earlier
        draft of this plan did: stop_client sets that key ITSELF, first thing
        (services/channel_service.py:647-651), before it checks the channel
        exists and long before it publishes anything. A wait_until on the key
        therefore passes with the event listener dead, which makes it a test
        of nothing. The listener's own branch is asserted below, by a route
        that cannot be satisfied any other way.
        """
        client_id = "client_on_some_other_worker"
        path = f"/proxy/relay/channels/{self.identifier}/clients/{client_id}"
        response = requests.delete(
            self.live_server_url + path, headers=_signed("DELETE", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        body = response.json()
        self.assertTrue(body["event_published"])
        self.assertFalse(body["locally_processed"])
        self.assertTrue(body["stop_key_set"])

    def test_a_client_stop_event_from_another_worker_sets_the_clients_stop_key(self):
        """The listener's CLIENT_STOP branch (server.py:402-419).

        Published directly rather than through the admin route, and that is
        the point: the route sets the stop key itself before publishing, so
        only an event that arrives WITHOUT the route running can prove the
        listener set it. The payload mirrors
        ChannelService._publish_client_stop_event (:992-1013) exactly; a
        second relay worker puts precisely this on the channel.
        """
        client_id = "client_only_the_listener_can_stop"
        stop_key = RedisKeys.client_stop(self.identifier, client_id)
        self.assertFalse(
            self.redis.exists(stop_key), "the key must not exist before the event"
        )

        self._publish({
            "event": EventType.CLIENT_STOP,
            "channel_id": self.identifier,
            "client_id": client_id,
            "requester_worker_id": "some-other-worker",
        })

        wait_until(
            lambda: bool(self.redis.exists(stop_key)),
            timeout=10,
            what="the listener to set the client's stop key",
        )

    def test_a_channel_stop_event_from_another_worker_is_acknowledged(self):
        pubsub = self.redis.pubsub()
        pubsub.subscribe(RedisKeys.events_channel(self.identifier))
        self.addCleanup(pubsub.close)

        self._publish({
            "event": EventType.CHANNEL_STOP,
            "channel_id": self.identifier,
            "requester_worker_id": "some-other-worker",
        })

        seen = []

        def acknowledged():
            message = pubsub.get_message(timeout=0.1)
            while message is not None:
                if message.get("type") == "message":
                    try:
                        seen.append(json.loads(message["data"]))
                    except (TypeError, ValueError):
                        pass
                message = pubsub.get_message(timeout=0.0)
            return any(
                event.get("event") == EventType.CHANNEL_STOPPED
                and event.get("worker_id") == self.server.worker_id
                for event in seen
            )

        wait_until(
            acknowledged,
            timeout=10,
            what="a channel_stopped acknowledgement from this worker",
        )

    def test_a_malformed_event_payload_does_not_kill_the_listener(self):
        # server.py:432-433 catches per-message, so the listener survives a
        # payload it cannot parse. Proven by the NEXT event still working --
        # a test that only published garbage would prove nothing.
        self.redis.publish(
            RedisKeys.events_channel(self.identifier), b"this is not json"
        )

        client_id = "client_after_garbage"
        self._publish({
            "event": EventType.CLIENT_STOP,
            "channel_id": self.identifier,
            "client_id": client_id,
            "requester_worker_id": "some-other-worker",
        })

        stop_key = RedisKeys.client_stop(self.identifier, client_id)
        wait_until(
            lambda: bool(self.redis.exists(stop_key)),
            timeout=10,
            what="the listener to keep working after a malformed payload",
        )


class StreamSwitchEventTests(RelayHarnessTestCase):
    """The listener's largest branch (server.py:262-357), which needs a live
    StreamManager and is therefore this task's one tune."""

    def test_a_stream_switch_event_from_another_worker_switches_the_channel(self):
        server = ProxyServer.get_instance()
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            identifier = str(channel.uuid)
            detail_path = f"/proxy/relay/channels/{identifier}"

            with self.tuned(channel) as stream:
                stream.read(20 * 188)

                # A URL the same fake upstream also serves, so the switch
                # can actually connect. FakeUpstream.url is the canonical
                # one; a query string makes it a different URL without
                # making it a different server.
                new_url = f"{self.upstream.url}?switched=1"
                server.redis_client.publish(
                    RedisKeys.events_channel(identifier),
                    json.dumps({
                        "event": EventType.STREAM_SWITCH,
                        "channel_id": identifier,
                        "url": new_url,
                        "user_agent": "harness",
                        "stream_id": None,
                        "m3u_profile_id": None,
                        "stream_name": None,
                        "requester": "some-other-worker",
                    }),
                )

                def switched():
                    payload = requests.get(
                        self.live_server_url + detail_path,
                        headers=_signed("GET", detail_path),
                        timeout=10,
                    ).json()
                    return payload.get("url") == new_url

                wait_until(
                    switched,
                    timeout=15,
                    what="the status endpoint to report the switched URL",
                )

                # The listener records the outcome for whoever asked
                # (server.py:330-332).
                status_key = RedisKeys.switch_status(identifier)
                self.assertEqual(server.redis_client.get(status_key), "switched")

                # The same URL again: server.py:296-300 treats that as a
                # success without asking the manager to reconnect.
                server.redis_client.delete(status_key)
                server.redis_client.publish(
                    RedisKeys.events_channel(identifier),
                    json.dumps({
                        "event": EventType.STREAM_SWITCH,
                        "channel_id": identifier,
                        "url": new_url,
                        "requester": "some-other-worker",
                    }),
                )
                wait_until(
                    lambda: server.redis_client.get(status_key) == "switched",
                    timeout=15,
                    what="the same-URL switch to be recorded as switched",
                )

            self.stop_channel(channel)
```

- [ ] **Step 2: Run it**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_server_event_listener -v2 --durations 10
```

Expected: PASS. Three failure modes worth naming before you start debugging:

- **`test_a_client_stop_event_...` times out on the stop key.** Check `am_i_owner`:
  `try_acquire_ownership`/`get_channel_owner` read `RedisKeys.channel_owner`, and `setUp` writes
  `server.worker_id` into it. If the singleton's `worker_id` changed between `setUp` and the
  publish, the guard at `:245` refused. Print `server.worker_id` on both sides.
- **`test_a_stream_switch_event_...` never reports the new URL.** Read the detail payload's
  `state`: a switch that failed rolls the URL back (`server.py:333-345`) and records
  `switch_status = "failed"`. If the stand-in cannot connect to `?switched=1`, use a second
  `FakeUpstream` instead of a query string.
- **A pub/sub message is missed.** `pubsub.subscribe` must be issued *before* the publish; that is
  why `setUp` in the first class does not subscribe and the one test that needs it subscribes
  inline, first thing.

**If the switch test is flaky for any reason at all, delete it** and record in the PR description
that the branch is left uncovered. It is the drop-first test in § Keeping the suite fast, and a
flaky test in a coverage gate is a liability 2a-7 inherits.

- [ ] **Step 3: Commit**

```bash
git add apps/proxy/live_proxy/tests/test_server_event_listener.py
```

```bash
git commit -F <msgfile>
```

Subject: `test(phase2): cover server.py's Redis event listener loop`.

---

## Task 8: `server.py` — bring-up failure and failed-init cleanup

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_server_bringup_failures.py`

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase`, `harness.process.stand_in_stream_profile`,
  `RedisKeys`, `ProxyServer`, `apps.channels.models.Stream`.
- Produces: nothing.

**Coverage value on `server.py`: zero. Say so plainly.** This task reaches
`views.py:612-615`, not `server.py` — see the recipe note below for why `_cleanup_failed_init` is
never entered. Its worth is behavioural: nothing in the tree asserts that a tune which cannot be
served releases its ownership rather than stranding it, and the Go relay is held to that just as
much. **Do not claim `_cleanup_failed_init` coverage in the PR description**, and do not let
Task 9's arithmetic count 3 statements this task does not close.

**The path.** `stream_ts` acquires the init lock, calls `generate_stream_url` in a retry loop
(`views.py:318-345`) and, when no URL comes back for a reason that is not a connection limit,
stops retrying immediately — so this test costs a fraction of a tune rather than a whole one.
`initialize_channel` (`server.py:604-880`) never runs; `_cleanup_failed_init` (`:971-1021`) does,
releasing ownership without the stopping gate, dropping the local dicts and calling
`_clean_redis_keys`.

**How to make the source unresolvable, and why the obvious recipe crashes.**

**Do not write `stream.m3u_account = None; stream.save(...)`.** `Stream` carries a `pre_save`
receiver, `apps/channels/signals.py:52-65`'s `set_default_m3u_account`, which on a falsy
`m3u_account` calls `M3UAccount.get_custom_account()` and raises when there is none — and after
`TransactionTestCase`'s flush there is none, because the locked custom account is migration-seeded.
The field **is** nullable; checking that tells you nothing, because the signal is what fails. This
is the same seeded-row trap § Global Constraints names, arriving through a receiver rather than a
lookup.

Two shapes that work, both measured at 12-14 ms. Pick either:

```python
# (a) bypass the signal: queryset.update() issues UPDATE and fires no signals
from apps.channels.models import Stream
Stream.objects.filter(id=channel.streams.first().id).update(m3u_account=None)

# (b) leave the channel with no streams at all
channel.channelstream_set.all().delete()
```

**And correct the mechanism story while you are here — the earlier draft of this task had it
wrong.** The tune is by **channel uuid**, so `resolve_initial_source` takes the `Channel` branch,
not the `Stream` branch, and `Channel.get_stream()` simply skips a stream it cannot resolve. So
**`initialize_channel` is never entered and `_cleanup_failed_init` is never reached** — its only
callers are `server.py:719` and `:874`, both inside `initialize_channel`. Ownership is released by
`stream_ts`'s own `finally` at `views.py:612-615`.

**Consequence for this task's claim: its `server.py` yield is 0, not 3.** It is still worth
keeping, because it pins `views.py:614-615` — that a tune which cannot be served releases its
ownership rather than stranding it — and nothing else in the tree asserts that. **Say so in the PR
description rather than claiming `_cleanup_failed_init` coverage this test does not produce.**

- [ ] **Step 1: Write the failing test**

```python
"""A tune whose source cannot be resolved releases its ownership.

stream_ts stops retrying as soon as the failure is not a connection limit
(views.py:336-343) and its own finally block releases ownership at
views.py:612-615. That release is the whole subject.

NOT _cleanup_failed_init. The tune is by channel uuid, so
resolve_initial_source takes the Channel branch and Channel.get_stream()
skips the unresolvable stream; initialize_channel is never entered, and
_cleanup_failed_init's only callers (server.py:719 and :874) are inside it.
This test's server.py yield is ZERO. It earns its place on views.py.

NOT a matrix row -- the ownership lease is D2-deleted machinery. What ports
is the observable: a tune that cannot be served answers an error and leaves
nothing claiming the channel.

Cheap on purpose: nothing spawns, because the failure happens before any
subprocess is reached.
"""

import requests

from apps.channels.models import Stream
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


class BringUpFailureTests(RelayHarnessTestCase):
    def test_a_tune_whose_source_cannot_be_resolved_leaves_nothing_behind(self):
        server = ProxyServer.get_instance()
        profile = stand_in_stream_profile()
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=profile
        )
        identifier = str(channel.uuid)

        # queryset.update(), never instance.save(): Stream has a pre_save
        # receiver (apps/channels/signals.py:52-65) that raises when it
        # cannot find the migration-seeded custom M3UAccount, which the
        # flush has already removed.
        Stream.objects.filter(id=channel.streams.first().id).update(
            m3u_account=None
        )

        response = requests.get(
            f"{self.live_server_url}/proxy/ts/stream/{identifier}",
            stream=True,
            timeout=20,
        )
        self.addCleanup(response.close)
        self.assertNotEqual(
            response.status_code, 200, "an unresolvable source must not stream"
        )

        # Nothing is left claiming the channel: no ownership key, no
        # metadata hash, and no local manager.
        wait_until(
            lambda: not server.redis_client.exists(
                RedisKeys.channel_owner(identifier)
            ),
            timeout=10,
            what="the failed init to release ownership",
        )
        self.assertFalse(
            server.redis_client.exists(RedisKeys.channel_metadata(identifier))
        )
        self.assertNotIn(identifier, server.stream_managers)
        self.assertNotIn(identifier, server.stream_buffers)
```

The last two assertions read `ProxyServer`'s dicts. That is the one place in this PR where a test
looks inside the singleton, and it is justified the same way `test_harness_smoke.py` justifies
reading a pid: the claim is precisely "no local state survived", which has no wire representation.
**Say so in a comment** and do not extend the habit.

- [ ] **Step 2: Run it**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy.tests.test_server_bringup_failures -v2 --durations 5
```

Expected: PASS in well under a second. If it takes ~3 s, the retry loop did not break early — read
the returned error string against `views.py:337` (`"maximum connection limits" not in error_reason`)
and pick a different unresolvable shape rather than waiting the loop out.

- [ ] **Step 3: Commit**

```bash
git add apps/proxy/live_proxy/tests/test_server_bringup_failures.py
```

```bash
git commit -F <msgfile>
```

Subject: `test(phase2): cover server.py's bring-up failure and failed-init cleanup`.

---

## Task 9: The gate — coverage, the guard, the budget, and the PR description

**Files:**
- Modify: none (this task measures and reports; any fix it provokes belongs to the task that owns
  the file).

- [ ] **Step 1: Run the whole label set the commit hook will run**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy
```

```bash
<dexec> manage.py test --keepdb apps.proxy
```

```bash
<dexec> manage.py test --keepdb apps.channels
```

Expected: all green. `apps.channels` is in the Gate 2 label set and its
`tests/test_ts_proxy_teardown.py` builds a real `ProxyServer` ten times — if this PR broke anything
about the singleton's lifecycle, that label is where it shows.

- [ ] **Step 2: Measure the gate**

```bash
<dexec> bash -lc 'cd /repo && scripts/coverage_live_path.sh'
```

Three checks, in this order:

1. **The denominator is 7,978.** It is a property of the rcfile's module list. Anything else is a
   finding — stop and report rather than continuing.
2. **`server.py`'s missed count has fallen measurably.** **Take your own before-number in this
   same session, on this same container, and compare against that** — never against a figure quoted
   from this document. Every baseline here is C-tracer basis and this branch may by then be rebased
   onto a `sysmon` 2a-2, which moves `server.py` by 48 statements on its own.

   **The target is ≈121, and it is a target, not a measurement.** It is what Tasks 6 and 7 are
   expected to close **out of a reachable pool of 257** (sysmon) — the gap is deliberate and
   § Deliberate non-goals says why. Derivation: `check_if_channel_exists` 34 +
   `_clean_zombie_channel` 11 + `_clean_redis_keys` 2 (Task 6) = 47, plus roughly 74 of the event
   listener's 108 (CLIENT_STOP 13, CHANNEL_STOP 13, STREAM_SWITCH 48) in Task 7. **Task 8
   contributes 0 to `server.py`** — it reaches `views.py:612-615` instead, for the reason its own
   section gives.

   **Expected band 100–140.** Below 80 means a task did not land what it claimed; above 160 means
   something incidental moved and is worth attributing before you celebrate it. A movement of a few
   dozen is not evidence either way: eight runs on one unmodified tree moved `missing` by 19
   statements, and four of the moving regions are in this file.

   **A reference measurement exists.** A review pass materialised these tests and measured
   `server.py` **820/823/819 → 698/697/701 across three runs: −122, range −118…−126.** That is the
   ≈121 target landing. If your number is far from it, the difference is in your tests, not in the
   estimate. **Report the before and after as two numbers from
   runs taken in the same session, on the same container, and say how many runs you took.**
3. **Zero `CoverageWarning` lines.**

If `server.py`'s improvement is under ~50 statements, something is wrong with the measurement, not
with the tests — the most likely cause is reporting over a stale data directory. `rm -rf
/tmp/dispatcharr-coverage-live-path` and re-run the script with no arguments.

- [ ] **Step 3: Measure the runtime cost**

```bash
<dexec> manage.py test --keepdb apps.proxy.live_proxy --durations 15
```

```bash
<dexec> manage.py test --keepdb apps.proxy --durations 15
```

Compare each against the same command at **`2a826e07`** — name the SHA, not `main`; a local `main`
ref can sit behind the branch point. `git stash` is the quickest way to take the before number on
the same container.

**Budget: ≤ 3.5 s added across the two labels combined.** Baseline for `apps.proxy.live_proxy` at
`2a826e07` was **179 tests in 6.787 s**. If you are over, read `--durations` first — twice in this
stage the cost has been a library default rather than the work — then drop in the order § Keeping
the suite fast gives. **Report the number either way**, over or under, so 2a-7 can see the trend.

- [ ] **Step 4: Run the guard and confirm all eight rows are closed**

```bash
cd e2e && npx playwright test --project=guards parity-matrix
```

Then read the file yourself and confirm, one by one, that **rows 14, 15, 16, 17, 19, 20, 23 and 25**
each carry a test reference and none of them still says `owed: 2a-5`:

```bash
grep -n '^| \(14\|15\|16\|17\|19\|20\|23\|25\) |' docs/relay-parity-matrix.md
```

`grep -c 'owed: 2a-5' docs/relay-parity-matrix.md` must print **`0`**. **That is the whole check.**
Do not assert anything about the file's other `owed:` markers: on this branch there are also four
`owed: 2a-3`, nine `owed: 2a-4`, one `owed: 2a-6` and one `owed: 2b-3`, and they stay until those
PRs land. Gate 1 closing at 2b-3 is a statement about the end of the phase, not about this branch.

- [ ] **Step 5: Confirm no production file changed**

```bash
git diff --stat 2a826e07..HEAD
```

Expected: `docs/relay-parity-matrix.md`, this plan file, and eight new files under
`apps/proxy/live_proxy/tests/`. **Nothing else.** Every "prove it would fail" step above edits a
production file temporarily; if one shows up here, a revert was missed.

- [ ] **Step 6: Write the PR description**

It must carry, at minimum:

- The eight rows and the test that pins each — all eight, enumerated, not ranged.
- The gate numbers: denominator, `server.py` before and after, the total percentage, and how many
  runs each figure came from.
- The runtime cost, against `2a826e07`, and whether it is inside the 3.5 s budget.
- The falsification evidence from Task 1 Step 2, Task 2 Step 3, Task 3 Step 3, Task 4 Step 3 and
  **especially Task 5 Step 3** — the 403 that appears when `decision=decision` is removed.
- § Deliberate non-goals, verbatim, so a reviewer does not have to ask.
- The five findings and recommendations this PR is expected to surface, if they held up:
  1. The event listener's "Non-owner worker cleaning local resources" arm (`server.py:382-389`) is
     unreachable for a non-owner, because every branch sits under `if self.am_i_owner(...)` at
     `:245`. Recorded, not fixed (D5).
  2. Row 15's second clause has no externally observable consequence and is recorded rather than
     pinned.
  3. **A recommendation for 2a-7, not a row**: `_drf_user` (`apps/proxy/authorize.py:227-265`)
     raises `AuthorizeDenied(401)` for a credential an authenticator *rejected* and returns `None`
     for one merely *declined*. A Go port would flatten both to "anonymous", turning a rejected
     credential into a successful anonymous tune. This PR pins it on the wire
     (`test_a_rejected_credential_is_401_and_never_an_anonymous_tune`) but adds **no matrix row** —
     a `HIGHEST_ROW_ID` bump would conflict with the three sibling coverage PRs in flight.
     **2a-7 should add the row**, citing that test; it runs after all four have merged, so its
     bump conflicts with nothing. (2b-3 is the fallback, being the last PR the spec has editing
     this file.) Same disposal 2a-4 used for its Proxy/Redirect finding.
  4. **Two production findings from the review pass's probes, as findings, not fixes.** (a) Every
     hash-identified tune logs `Failed to log system event channel_start: ['"harness-hash-…" is
     not a valid UUID.']` — the control plane's event serializer rejects a relay event whose
     identifier is a `stream_hash`, so the admin single-stream preview raises no `channel_start`
     event at all. (b) `try_acquire_ownership` (`server.py:507-513`) reads `SET NX`'s
     None-on-contention as "Redis command failed — assuming ownership", which makes `:519-529`
     dead code and makes contention **fail open** — a fourth fail-open shape alongside the three
     `CLAUDE.md` records. Both filed, neither fixed (D5).
  5. Whether the container reports `Your models in app(s): 'core' have changes that are not yet
     reflected in a migration` on this branch. It did during planning. If it reproduces from a
     clean `main` checkout too, it is pre-existing and belongs in an issue, not this PR; if it does
     not, something on this stack introduced it and the PR must not merge until it is understood.
- **Row 21's status, in one sentence**: its Notes still say "2a-5 owes a live-root equivalent
  instead"; the test exists
  (`test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root`); its line was **not**
  edited because row 21 (`:185`) sits one line from row 11 (`:184`), which 2a-6 may re-pin, and
  the matrix's own measured rule is that edits one line apart conflict. **2b-3 is the expected
  corrector**, being the last PR the spec has touching this file.
- Anything dropped for budget, and why.

- [ ] **Step 7: Clean up the container**

```bash
docker rm -f dispatcharr-testrunner-2a5 && docker volume rm dispatcharr-hookdb-2a5
```

---

## Self-review — run this before opening the PR

1. **Spec coverage.** The `2a-5` row of § The seven PRs asks for two things: tests against
   `server.py`'s bring-up, event listener loop and zombie detection (Tasks 6, 7, 8), and the eight
   matrix rows (Tasks 1–5). Its gate asks for a measured increase on `server.py` **and** all eight
   rows carrying a test reference the guard accepts (Task 9). Point at the task for each. Any gap is
   a plan defect, not a scope decision.
2. **Placeholder scan.** No step in this plan says "add appropriate error handling", "similar to
   Task N" or "write tests for the above". If your implementation added one, remove it.
3. **Type and name consistency.** The helper is `_signed(method, path, body=b"")` in every module
   that has one, with the same body. The harness API used throughout is exactly
   `make_channel(upstream_url=…, profile=…)`, `tuned(channel)`, `tune(channel)`, `stand_in(**kw)`,
   `stop_channel(channel)` and `wait_until(predicate, timeout=…, interval=…, what=…)` — check each
   against `harness/relay.py` rather than against this plan if they disagree.
4. **Negative-scope claims.** § File structure says the harness package is not touched, § Global
   Constraints says no production code changes, and § Deliberate non-goals names five things left
   uncovered. If a task drifted, fix the section as well as the code.
5. **Every `Expected:` in this plan is a claim about what the code emits.** If one turns out to be
   wrong, the plan was wrong — say so in the PR description rather than quietly adjusting the
   assertion to match.
