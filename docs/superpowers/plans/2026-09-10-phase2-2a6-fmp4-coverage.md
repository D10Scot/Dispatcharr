# Phase 2 PR 2a-6 — fMP4 and Output Profile Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the output side of the live path — Output Profile process sharing
(matrix row 11) and the fMP4 generator's health-blind client timeout (matrix row 12,
[#222](https://github.com/D10Scot/Dispatcharr/issues/222), reproduced not fixed) — as
behavioural tests driven through the relay's HTTP surface, and raise measured statement
coverage on `apps/proxy/live_proxy/output/fmp4/manager.py`,
`apps/proxy/live_proxy/output/fmp4/generator.py`,
`apps/proxy/live_proxy/output/fmp4/buffer.py` and
`apps/proxy/live_proxy/output/profile/manager.py`.

**Architecture:** Every test is a `RelayHarnessTestCase` (2a-2): a real Django control
plane on a live server, real Redis, a real in-process fake upstream, and real spawned
child processes. Two child programs appear, and which one a test uses is a decision this
plan makes explicitly per test:

- the **stand-in** (`harness/standin.py`, a dumb pipe) wherever the subject is the
  relay's *reaction* to a process — how many it spawns, what it does when one goes
  quiet;
- **real `ffmpeg`** wherever the subject is *the bytes a remuxer produces* — the whole
  fMP4 path, because `FMP4RemuxManager._reader_loop` parses `moof` boxes out of its
  child's stdout and a dumb pipe carrying MPEG-TS contains none.

That split is the harness's own stated rule (`harness/README.md` § The stated rule) and
`harness/asset.py`'s `build_real_ts_asset()` docstring already names the fMP4 path as the
case that needs it. Nothing mocks `FMP4RemuxManager`, `OutputProfileManager` or
`ProxyServer`. The only patched objects are configuration (`apps/proxy/config.py`'s
`TSConfig` class attributes), which is the production lever, not a seam. Assertions are
on what a client can see: the bytes a tune serves, whether its response ended or is still
open, and — for attribution only, never as the pin — the relay's own log records.

**Tech Stack:** Python 3.13, Django 6, `manage.py test` (custom runner), the 2a-2 harness
under `apps/proxy/live_proxy/tests/harness/`, 2a-4's `tests/manager_support.py`,
`coverage` via `scripts/coverage_live_path.sh`, the parity-matrix guard in the `guards`
Playwright project.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` at `e838d00b`
(worktree `.worktrees/phase2-spec`, branch `docs/phase2-spec`) — § Stage 2a's Gate 1 and
Gate 2, the reachability section, and the `2a-6` row of § The seven PRs. The harness it
consumes is specified by
`docs/superpowers/plans/2026-09-10-phase2-2a2-subprocess-harness.md`; the immediately
preceding plan is `docs/superpowers/plans/2026-09-10-phase2-2a4-manager-coverage.md`,
both on this branch.

---

## Global Constraints

Exact values, copied from the spec, `CLAUDE.md`, the branch and from measurement. Every
task's requirements implicitly include this section.

- **Branch:** `migration/phase2a-fmp4-coverage`, stacked on
  `migration/phase2a-manager-coverage` (2a-4, PR #236) at `8ec02d45`, which is itself
  stacked on `migration/phase2a-subprocess-harness` (2a-2, PR #229). Worktree
  `/Users/dion/git/Dispatcharr/.worktrees/phase2-2a6`. **Run every command from
  there, with absolute paths.** Other agents are live in the sibling `.worktrees/*`
  directories; do not `cd` into one and never write outside your own.
- **Container:** your own, never the shared one. Start it with
  `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a6 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a6 DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2-2a6 bash /Users/dion/git/Dispatcharr/.worktrees/phase2-2a6/.claude/hooks/start-test-container.sh`.
  Re-pointing `dispatcharr-testrunner` contaminates another agent's in-flight
  measurement; we have paid for that once. `DISPATCHARR_TEST_IMAGE` is not optional
  here — the default upstream image carries neither `coverage` nor `hypothesis` (§ Step
  2a below).
- **The container recipe you actually need, reconstructed by hand because the hook
  script's own bring-up left a container with no database (see the MISCONF/no-database
  finding this task records):** every `docker exec` that runs `manage.py` needs
  `-e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr
  -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost
  -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret
  -e DISPATCHARR_LOG_LEVEL=WARNING` — this is `run-affected-tests.sh`'s own `dexec()`
  recipe, and nothing in the image sets these by default (`docker inspect`'s `Config.Env`
  carries none of them). **`--keepdb` is required on every `manage.py test` invocation**,
  not just `scripts/coverage_live_path.sh`'s own internal ones: that script's runs leave
  `test_dispatcharr` behind, and a bare `manage.py test` without `--keepdb` against an
  already-existing test database prompts interactively (`EOFError: EOF when reading a
  line`) rather than running anything. `scripts/run_metrics_tests.sh` and
  `python -m metrics.build --validate-only` (Task 8) want `git` on `PATH`, which the test
  container does not have — run those two on the host instead, from this worktree.
- **`PostToolUse` hook output is advisory and is frequently a false positive here.**
  Hooks are spawned by the harness, not by your shell, so `DISPATCHARR_TEST_CONTAINER`
  never reaches them: an edit-triggered run always uses the shared
  `dispatcharr-testrunner`, mounted at whatever tree *that* container has, and
  `CLAUDE_PROJECT_DIR` may not track this worktree, which mis-resolves the test package
  label and reports FAILED on every edit. **Run your own tests in your own container and
  treat every hook verdict as noise.**
- **Failure signature to recognise:** a test run that fails with no `FAIL:`/`ERROR:`
  body, or a discovery count that does not match what you just wrote, means the container
  is mounted at the wrong tree — **or** that its Redis has gone MISCONF (fixed in
  PR #238; a container created before that merges needs
  `redis-cli CONFIG SET save ""` inside it). A third signature with the same root:
  `ModuleNotFoundError: No module named 'hypothesis'` (or `coverage`) from the two
  `test_property_*` modules means the container came from upstream's image rather than
  the fork's — PR #238 changed the default. **Never treat any of the three as a bad run
  to repeat: they invalidate a coverage measurement rather than degrade it** (Task 1
  Step 4).
- **Never pass `--settings=dispatcharr.settings` to `test`.** It targets the production
  database.
- **Composition rule** (spec § The subprocess harness, final paragraph; restated in
  `harness/README.md`): drive the relay through its **HTTP surface** against **real
  dependencies** — the fake upstream, real Redis, real spawned children — and assert on
  **observable behaviour**, never on an internal call count and never against a mock of
  `server.py`'s or a manager's internals. `test_harness_smoke.py` is the one file allowed
  to read a spawned process's pid or reach into `ProxyServer`'s dicts; nothing in this PR
  may. Reading a Redis key through `RedisKeys` is permitted (the harness's own
  `relay.py` does it for cleanup) and is used here exactly twice, both times as a
  *secondary* assertion beside a client-observable one.
- **D5 is strict parity, defects included.** Row 12 is a defect the Go relay must
  reproduce. **The test pins the wrong behaviour, and its docstring says so and cites
  #222**, so that nobody later "fixes" the test. Do not fix `_is_timeout`.
- **Two tiers of running.** A claim that a test *reaches* a branch is settled by an
  `INFO`-level observation — here, an `assertLogs` assertion inside the test itself. A
  claim that a test *pins* a behaviour requires a **break check**: patch the production
  behaviour, watch the test fail, revert, watch it pass. A test that stays green when its
  subject is broken is pinning nothing, and no amount of reading reveals that; row 7 in
  2a-3 passed with its subject broken, which is why every `owed:` row now carries a
  mandatory break check. **A break check that passes is not evidence until you have
  confirmed the break applied** — `sed -n` the patched lines back out and look at them
  before running.
- **A break check's lever must break the MECHANISM, not select a second documented
  behaviour.** 2a-3's row 8 tried `new_client_behind_seconds = 0` as its lever; that
  setting's own docstring says *"0 means start at live (buffer head)"*, so the "break"
  chose a supported mode and proved nothing. Ask of every lever: does the code now do
  something it is documented never to do?
- **Every expected failure quoted in this plan is PREDICTED, not observed.** 2a-3's plan
  carried a predicted `AssertionError` that was quoted, asserted and never actually seen,
  and finding that out cost a full investigation. Record what the run really printed, and
  if it differs from the quotation here, **say so in the PR description** rather than
  editing the memory of it — a prediction that missed is a finding about this plan.
- **No wall-clock assertion may be a pin.** A test that compares elapsed time against
  what production pacing would cost is inert: the ring buffer holds a backlog, so a
  client's read is served from Redis at memory speed regardless of what the upstream or
  the positioning logic did. Row 8 was pinned on exactly such a comparison and stayed
  green with its subject deliberately broken — `drained_in` 0.000342 s broken against
  0.000168 s working, both two orders of magnitude under a 0.0226 s threshold. **The pin
  is always the observable consequence** — which bytes arrived, whether a response ended,
  how many processes were spawned, what a status field reads — and those are also the
  only assertions that port to Go row-for-row. A clock may appear in this PR in exactly
  two roles, both explicitly labelled where they occur: a **deadline** inside
  `wait_until`, and a **lower bound** guarding against a false positive (Task 6 Step 3).
  Neither is the pin.
  *(One correction to the framing this arrived in, recorded because a mis-stated
  mechanism propagates: `FakeUpstream` **is** paced — `rate` defaults to `1.0` and
  `_Handler._stream` sleeps to hold it, `harness/upstream.py`. The reason elapsed-read
  assertions are inert is not missing pacing but the buffered backlog between upstream
  and client, which is true at any rate. Both plans reach the same rule; only the second
  reason survives contact with the code.)*
- **Gates are relative, never absolute.** Every coverage claim in this PR is stated as
  "strictly fewer missed statements than a same-session baseline taken in the same
  container under the same tracer core". Absolute figures rot; three of this spec's five
  reachability estimates were checked and all three were wrong.
- **The coverage number is not deterministic, and these files are the noisy ones.**
  Measured spread on `missing`: 2 statements on a base tree, 10 with 2a-3's tests, and
  **51** once the fMP4/Output-Profile managers are exercised, because they start
  background loops of their own. Take **three runs per side** and report `min-max`, never
  a single digit.
- **Do not difference coverage totals to reason about what a test covered.** Writing
  `gap(t)` for what a tracer fails to credit, `delta_sysmon − delta_C ≡ gap(after) −
  gap(base)` **identically**, so a totals difference is true under a hypothesis and its
  negation alike. **Diff the missed-line sets** (`coverage json`'s per-file
  `missing_lines`), which is how both of this spec's contested buckets were finally
  settled.
- **The tracer core is sysmon, and the script sets it — there is nothing to decide.**
  `migration/phase2a-subprocess-harness` was merged into this branch to bring in
  `9c865538`, so `scripts/coverage_live_path.sh` now does `export COVERAGE_CORE=sysmon`
  (`:42`) and stamps `SHAPE_ID="per-label/v2-${COVERAGE_CORE}"` (`:92`). Run it plainly
  and do not set the variable yourself. **Do not edit the script** — 2a-2 owns it, that
  ruling stands, and its shape guard now refuses to report over a data file stamped by
  any other core.

  *An earlier draft of this plan carried a two-branch fallback for a base where sysmon was
  absent; the merge removed the need for it, and it is deleted rather than left as dead
  instruction.* **Never compare a figure taken under one core against a baseline or floor
  taken under the other**: the two differ by about a hundred statements on this
  denominator, twice the run-to-run spread. That has a live consequence for review —
  **2a-4 (#236) and 2a-5 (#237) both measured under the default C tracer**, because
  `9c865538` is an ancestor of only `migration/phase2a-ts-generator-coverage` and their
  branches were cut from an earlier 2a-2 head. Their PR bodies say so. **2a-6's numbers
  are therefore not comparable with theirs**, are comparable with 2a-3's, and are the
  basis 2a-7's floor will use. Say that in the PR description so no reviewer lines the
  four PRs up in a table.
- **Do not "simplify" `os.posix_spawn` back to `Popen`** — fork-based approaches hang in
  gevent's `_before_fork`.
- **`gh` always with an explicit `--repo D10Scot/Dispatcharr`**; it otherwise resolves to
  the upstream public tracker.
- **Stage and commit in separate Bash calls**, and write commit messages to a file,
  committing with `-F <file>` — the pre-commit hook matches on command text, so a
  message merely *containing* the two words trips it. This plan file itself contains
  them, so it must be written with the Write tool, never a shell heredoc.
- **Commit per task.** Report progress per commit, not only at the end.
- **`TransactionTestCase` flushes every table after each test, including
  migration-seeded rows** (`harness/README.md` § Two traps). Every test creates every row
  it needs: the `StreamProfile`, the `OutputProfile`, the `CoreSettings` groups.
- **Timing levers that exist, and one that does not.** `TSConfig.STREAM_TIMEOUT` (20) and
  `TSConfig.FAILOVER_GRACE_PERIOD` (20) are plain class attributes read through
  `ConfigHelper.get` (`apps/proxy/live_proxy/config_helper.py:30`, `:104`), so
  `patch.object` is the production lever. `INIT_SEGMENT_TIMEOUT = 15`
  (`output/fmp4/manager.py:60`) is a module constant the generator imports **by value**
  at `output/fmp4/generator.py:18`, so patching the manager's copy does nothing — treat
  15s as a hard ceiling on how long a broken fMP4 tune hangs, and set every client-side
  deadline below it so a failure reads as a failure rather than a timeout.
- **Cost budget.** 2a-2's stage budget of ≤15s across all of 2a was replaced by 2a-4's
  ruling (a) with **per-PR measurement and a reconsideration trigger at 45 s wall on the
  `apps.proxy.live_proxy` label**. Record that label's wall time before and after this
  PR's tests and say both figures in the PR description; if the after figure crosses 45 s,
  stop and reconsider scope rather than absorbing it silently.

---

## File Structure

```
apps/proxy/live_proxy/tests/
  output_support.py                      NEW — this PR's levers (Task 2)
  test_output_profile_sharing.py         NEW — matrix row 11 (Task 3)
  test_fmp4_output.py                    NEW — the fMP4 pipeline, end to end (Task 4, Task 5)
  test_fmp4_client_timeout.py            NEW — matrix row 12, the #222 defect pin (Task 6)
  harness/asset.py                       EDIT — one optional argument (Task 2 Step 1)
docs/relay-parity-matrix.md              EDIT — rows 11 and 12 (Task 7)
metrics/curated/defects.yml              EDIT — #222 open -> pinned (Task 8)
docs/superpowers/plans/2026-09-10-phase2-2a6-fmp4-coverage.md   this file
```

**Why a new `output_support.py` rather than additions to `harness/`.** `harness/` is
2a-2's deliverable and 2a-5 (`migration/phase2a-server-and-authorize-coverage`, complete
at `597e562a`, open as PR #237) and 2a-3 (`migration/phase2a-ts-generator-coverage`, open
as PR #239 and **still adding to `harness/`** — a packet-index payload in `synthetic_ts`)
both sit off the same base, so an edit inside `harness/` is a live merge risk. 2a-4 set the precedent with `tests/manager_support.py` for exactly this reason and
this PR follows it. The **one** exception is `harness/asset.py`, argued in Task 2 Step 1.

**What this PR imports rather than rewrites:** `harness.relay.RelayHarnessTestCase` and
`wait_until`; `harness.asset.TS_PACKET_SIZE`, `assert_ts_aligned`, `require_real_ffmpeg`,
`ffmpeg_env`, `build_real_ts_asset`; `harness.upstream.FakeUpstream` (via the base class);
`manager_support.proxy_stream_profile`. **2a-3's `harness/control.py` is not on this
branch** (2a-3 stacked off 2a-2, not off 2a-4) — do not import it.

---

## Verified facts this plan rests on

Everything below was checked against the tree at `8ec02d45` or measured in a throwaway
container running `ghcr.io/dispatcharr/dispatcharr:latest`. Nothing here is an estimate.

**F1 — a dumb-pipe stand-in can never drive the fMP4 path, and this is not a tuning
problem.** `FMP4RemuxManager._reader_loop` (`output/fmp4/manager.py:316-332`) holds every
byte its child writes in `init_buf` until `_find_moof_offset` finds an MP4 `moof` box, and
gives up at 10 MB (`:334-339`). The stand-in copies its input verbatim, so on the TS path
its stdout is MPEG-TS and contains no MP4 box structure at all: `_find_moof_offset`
unpacks `0x47…` as a box length, jumps past the end of the buffer and returns −1 on every
read. The init segment is therefore never stored, `_wait_for_fmp4_ready`
(`output/fmp4/generator.py:164-189`) polls for 15s and returns False, and the client gets
an empty 200. **Any fMP4 test that asserts on fragments needs real `ffmpeg` as the remux
child.**

**F2 — real ffmpeg does produce what the manager parses, measured.** Feeding the exact
`FFMPEG_REMUX_CMD` (`output/fmp4/manager.py:32-45`) a real MPEG-TS asset built the way
`build_real_ts_asset()` builds one gives `ftyp` at 0, `moov` at 28, `moof` at 1247 — so
`_find_moof_offset` fires at offset 1247 and a 1,247-byte init segment is stored. ffmpeg
version in the image: **8.1.2**.

**F3 — `build_real_ts_asset()` as written yields exactly ONE `moof` per pass, and `-g` is
an improvement, not a requirement (corrected — an earlier draft of this finding overstated
it as an impossibility, and the PR's shipped docstrings repeated that overstatement until
review caught it).** Measured: a 2-second `testsrc` encoded with `libx264 -preset ultrafast`
and no `-g` has one keyframe, so `-movflags frag_keyframe` emits one fragment for the whole
asset. `_flush_complete_fragments` (`output/fmp4/manager.py:252-287`) bounds the current
fragment by *the next* `moof`, so a single pass through the remux flushes nothing — **but
every caller here feeds the asset through a LOOPING upstream** (`harness.upstream.FakeUpstream`
replays its payload), and the next loop's own `moof` bounds the previous loop's fragment just
fine. Fed the exact `FFMPEG_REMUX_CMD` three concatenated loops with no `-g`: **3 fragments,
one per loop, ~95 KB each** — not zero. A test built naively on the harness's own fMP4 helper
would NOT see zero chunks; it would see fewer, larger, later ones. **`-g 12` is still worth
keeping**: the same three loops with it gave **15 fragments of 11–27 KB**, i.e. five per loop
instead of one — smaller fragments, and a client's first one arrives sooner. Task 2 Step 1
applies `-g 12` as the improvement it actually is.

**F4 — end-to-end remux latency, measured against a paced feed.** Writing a looped
`-g 12` asset into the real `FFMPEG_REMUX_CMD` in 1,880-byte chunks paced at
250 KB/s (`FakeUpstream`'s `rate=1.0`) produced the init segment **1.69 s** after spawn and
eight fragments immediately behind it. That is comfortably inside `INIT_SEGMENT_TIMEOUT`'s
15 s, and it is the number to beat when choosing an upstream rate.

**F5 — `os.posix_spawn` passes `os.environ` to the child** (`live_proxy/utils.py:154`), so
a real `ffmpeg` spawned by *production* code needs `LD_LIBRARY_PATH=/usr/local/lib` in the
**test process's own environment**, not merely in a `subprocess.run` env dict. Without it
the child dies with `undefined symbol: rist_peer_config_defaults_set_versioned` — issue
[#226](https://github.com/D10Scot/Dispatcharr/issues/226), which `harness/asset.py`'s
`ffmpeg_env()` already documents but only applies to the harness's *own* subprocess calls.

**F6 — the Output Profile path needs no real ffmpeg at all.** `OutputProfileManager`
writes its child's stdout straight into a `StreamBuffer`
(`output/profile/manager.py:249-256`) with no parsing, and the profile's command comes
from an `OutputProfile` row whose `build_command()` is `[command] + shlex_split(parameters)`
(`core/models.py:200-203`) — a test therefore chooses the executable by absolute path. A
dumb-pipe stand-in is exactly right there, and row 11's test is cheap because of it.

**F7 — `?output_profile=` and `?output_format=fmp4` are reachable inline, with no nginx
and no trusted header.** `resolve_output_profile` (`apps/proxy/authorize.py:201-219`)
reads `request.GET["output_profile"]` and `_resolve_output_format`
(`live_proxy/views.py:112-133`) reads `output_format`/`output`; `stream_ts` then calls
`ensure_output_profile` (`views.py:731`) and `ensure_output_format` (`views.py:754`).
With both set, the format key becomes `fmp4:p<id>` (`views.py:696-699`) and the fMP4
remux's source is the profile's output buffer, not the raw TS buffer (`views.py:736-739`,
`:756`).

**F8 — row 12's stated mechanism is not the divergence that is reachable, and the row
understates the defect.** Three findings, all read off the source:

  1. **Corrected on review — the original version of this finding was wrong about the
     `url_switching` window.** `url_switching` is set True at the top of `update_url()`
     (`input/manager.py:1432`) and cleared in that method's `finally` (`:1496`), but the
     body between them is NOT free of network I/O and is NOT sub-millisecond:
     `_close_socket()` (`:1675`) does `proc.wait(timeout=0.5)` and, separately, joins the
     stderr reader thread for up to `2.0` s (`stderr_join_timeout = 0.25 if self.stopping
     else 2.0`, `:1735-1736`); and `emit_event('stream_switch', ...)` (`:1476-1482`) goes
     through `control_plane._spawn` (`control_plane.py:329-335`), which calls its
     function **synchronously** — a real HTTP POST to Django — whenever the process is
     not gevent-monkey-patched, which is exactly the harness's own test process
     (`manage.py test` is never patched, `harness/README.md`). So the window can carry
     up to several seconds of real work, not sub-millisecond, and is reachable from a
     test. That correction removes the argument this finding originally rested on, but
     not its conclusion — see 2 and 3, which do not depend on the window's size at all.
  2. The divergence that *is* always present is larger and simpler: the TS generator
     returns True only when the stream manager is **unhealthy**
     (`ts/generator.py:584`) — the fMP4 version (`fmp4/generator.py:339-346`) returns True
     on elapsed time alone, health irrelevant.
  3. Larger still: the TS generator **sends keepalive packets** while waiting at the
     buffer head on an unhealthy stream (`ts/generator.py:366-389`,
     `_should_send_keepalive` at `:533-542`), and each one refreshes `last_yield_time`.
     Its own comment says so: *"Keepalive packets refresh last_yield_time, so
     `_is_timeout()` never fires during sustained stream failure"* (`:311-312`); the
     wall-clock cap is `MAX_KEEPALIVE_DURATION = 300` (`apps/proxy/config.py:122`).
     **The fMP4 generator has no keepalive path at all.** So the observable gap for an
     fMP4 viewer is: dropped 40 s into a stall, against a TS viewer held for up to
     300 s.

  **The argument the conclusion actually rests on, once point 1's original reasoning
  is removed:** TS `_is_timeout()` needs BOTH 40 s with no yielded data AND the stream
  manager unhealthy before it even looks at `url_switching` (`ts/generator.py:582-583`).
  But the keepalive path (point 3) refreshes `last_yield_time` on every packet it sends
  while the client sits at the buffer head on an unhealthy stream — which is exactly
  the condition that would otherwise lead to that check. So in ordinary operation the
  40-s-elapsed side of the AND rarely converges with "unhealthy" for long enough to
  reach the `url_switching` branch at all: the keepalive machinery, not the size of the
  `url_switching` window, is what shadows it. That holds regardless of whether the
  window is sub-millisecond or carries several seconds of real I/O (point 1) — the
  window's size was never the load-bearing fact, and this PR's pin does not depend on
  it either way.

  Task 7 amends row 12's Behaviour and Notes to say this, keeping its id, its citations
  and #222. Amending a Notes cell is precedented — 2a-4's ruling (c): *"a half-pinned row
  that looks whole is worse than one that says which half is pinned"*.

  **The amendment corrects the row's DESCRIPTION, not the defect, and nothing here makes
  row 12 easier.** `output/fmp4/generator.py:339-346` is unchanged and stays unchanged:
  the fMP4 generator still has no `url_switching` exemption, no health check and no
  keepalive, D5 says reproduce rather than fix, and 2c-6 is held to the drop. What
  changed is only that the row now names the gap that is always present — a TS viewer
  held through a stall for up to `MAX_KEEPALIVE_DURATION` (300 s) against an fMP4 viewer
  dropped at `stream_timeout + failover_grace_period` (40 s) — instead of naming only the
  `url_switching` window between `input/manager.py:1432` and `:1496`, which the keepalive
  path shadows in practice regardless of how long that window runs. The defect got
  **wider**, not smaller: the original wording described a race a viewer would almost
  never lose, and the reality is a
  disconnect on every sustained stall. A reader who skims this must not come away
  thinking the row was downgraded.

**F9 — `FMP4RemuxManager._handle_bsf_error` contains an unreachable branch.** It sets
`self.running = True` at `output/fmp4/manager.py:403` and then tests
`if not self.running:` at `:405`, whose body (`:406-413`, the "stop() was called while we
were restarting" cleanup) can never execute. Roughly nine statements inside this PR's own
denominator are dead by construction. Task 10 files it rather than covering it.

**F10 — the matrix will conflict, once, and predictably.** 2a-3
(`migration/phase2a-ts-generator-coverage`) has already rewritten row 10, which is the
line immediately above row 11. The matrix's own comment records that git conflicts on two
edits **one** line apart and merges cleanly at two. Re-pinning row 11 therefore costs one
trivial modify/modify conflict at merge, resolved by taking both sides. Row 12 sits alone
in `<!-- block: owed by 2a-6 -->` with marker lines above and below and conflicts with
nothing.

---

## Rulings this plan makes

**R1 — re-pin row 11 to a harness test, and keep the e2e spec cited beside it. Yes.**
The e2e spec (`e2e/tests/streaming-greybox/output-profile-sharing.spec.ts`) proves the row
through nginx in a real container and stays. But it is `@characterization` and its own
comment concedes the weakness: *"After the extraction the transcode may not be in this
container, or may not be a process named `ffmpeg`"* — it counts `pgrep -x ffmpeg`
container-wide, which is a whole-container observable it has to pre-flight to zero to make
unambiguous. A harness test counts **this profile's own spawns**, by name, in
milliseconds, inside the coverage denominator this PR is gated on, and ports to Go
row-for-row: 2c-7 spawns the same `OutputProfile.command` and can log the same way.
It genuinely pins the same claim — one spawn per `(channel, profile)` however many clients
attach — and pins it more sharply, because a spawn log counts *spawns* rather than
*surviving processes*. Cost: F10's one-line conflict. Worth it.

**R2 — the Proxy/Redirect inert-buffering-detector row stays with 2a-7.** Its subject is
`input/manager.py`'s health monitor and `services/log_parsers.py` — 2a-4's files, not
this PR's. Taking it here would mean writing tests against a module whose coverage
another PR is concurrently measuring, and it would put a *input-side* row in the matrix
block that 2c-6/2c-7 read as the fMP4/Output-Profile block. Nothing in
`output/fmp4/**` or `output/profile/**` decides whether the buffering detector runs.

**R3 — the rejected-vs-declined credential row stays with 2a-5 or 2a-7, not here.** It is
an `apps/proxy/authorize.py` behaviour (`_drf_user`'s treatment of a credential an
authenticator explicitly rejects). This PR touches no authorize surface.

**R4 — row 21's prose-only obligation is not 2a-6's, and the choice is between amending
2a-5 and handing it to 2a-7.** Row 21's own Notes cell names the owner: *"a pin is a 2d
cutover obligation a `/timeshift/` test can never acquire, so 2a-5 owes a live-root
equivalent instead"*. It is an XC-credential authorize behaviour with no output-side
component; 2a-6 taking it would be misfiling.

**Corrected:** an earlier draft of this section reasoned that 2a-5 could still take the
obligation because `migration/phase2a-server-coverage` had no commits. **There is no such
branch.** 2a-5 is `migration/phase2a-server-and-authorize-coverage`, it is complete at
`597e562a` with four commits, and it is open and green as PR #237. So the two live routes
are (a) amending #237 before it merges, or (b) 2a-7 inheriting it. **(a) is the better
one** while #237 is still open: the row's obligation is an authorize behaviour, 2a-5 is the
authorize PR, and its harness fixtures and the live-root drive it already builds are
exactly what the equivalent test needs — 2a-7 would have to rebuild them to do the same
work. If #237 merges first, it falls to 2a-7 by default, and **2a-7's plan must say it
inherited it rather than absorb it silently.**

**R5 — `output/fmp4/buffer.py` earns its place in scope, but gets no test of its own.**
Every one of its statements that matters (`put_fragment`, `get_chunks`,
`find_chunk_index_by_time`, `cleanup_redis`) is on the path of Tasks 4–6 and is measured
by the same gate. A separate unit test over it would assert Redis mechanics rather than
observable behaviour and would earn nothing the pipeline tests do not.

**R6 — no new matrix rows, and `HIGHEST_ROW_ID` stays at 28.** F8 is an amendment to an
existing row, not a new one. Adding a row would mean editing
`e2e/tests/guards/parity-matrix.ts:552`, which every row-adding PR in the phase also
edits.

---

## Task 1 — Container, baseline, and the tracer-core decision

**Files:** none (measurement only)

**Interfaces:** `scripts/coverage_live_path.sh`, `scripts/coverage_live_path.coveragerc`

- [ ] **Step 1.** Start your own container:
      `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a6 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a6 CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2-2a6 bash /Users/dion/git/Dispatcharr/.worktrees/phase2-2a6/.claude/hooks/start-test-container.sh`
      Confirm it is mounted at *this* worktree:
      `docker exec dispatcharr-testrunner-2a6 ls /repo/docs/superpowers/plans/ | grep 2a6`
      must print `2026-09-10-phase2-2a6-fmp4-coverage.md`. If it does not, stop — every
      number you take afterwards is from the wrong tree.
- [ ] **Step 2.** Guard against the MISCONF signature before you measure:
      `docker exec dispatcharr-testrunner-2a6 redis-cli CONFIG SET save ""` and
      `docker exec dispatcharr-testrunner-2a6 redis-cli ping` (expect `PONG`).
- [ ] **Step 2a.** Prove the container can actually run the measurement, before you take
      one. Both imports must succeed:
      `docker exec dispatcharr-testrunner-2a6 /dispatcharrpy/bin/python -c 'import coverage, hypothesis; print(coverage.__version__, hypothesis.__version__)'`.
      If either fails, the container was created from **upstream's** image, which carries
      neither; PR #238 changed `.claude/hooks/start-test-container.sh` to default to the
      fork's image, which does. **Re-create the container** rather than pip-installing
      into it — a hand-patched container is a measurement nobody else can reproduce.
      This check exists because a missing `hypothesis` does not announce itself as a
      missing dependency: it announces itself as 61 extra missed statements. See Step 4.
- [ ] **Step 3.** Confirm the tracer core is what this branch expects, then stop thinking
      about it. Run
      `docker exec dispatcharr-testrunner-2a6 grep -n 'SHAPE_ID=\|COVERAGE_CORE' /repo/scripts/coverage_live_path.sh`.
      It must print `export COVERAGE_CORE=sysmon` and
      `SHAPE_ID="per-label/v2-${COVERAGE_CORE}"`. If it prints `per-label/v1` instead, the
      2a-2 merge is missing from your checkout — re-merge
      `migration/phase2a-subprocess-harness` rather than working around it, and **never
      edit the script**, which 2a-2 owns. Do not set `COVERAGE_CORE` yourself in any
      command: the script exports it, and the shape guard now refuses to report over a
      data file stamped by a different core, so a hand-set variable can only take a
      measurement away from you.
- [ ] **Step 4.** Take the baseline, three runs, each into its own data directory so the
      per-run JSON survives (`--report` consumes the `.coverage.*` files).

      **A non-zero exit from any label INVALIDATES the whole measurement — it is not a
      warning to note and move past.** A label that errors never runs its tests, and every
      statement those tests would have covered is counted as *missed*, so the printed
      percentage is not a worse measurement of the same thing but a measurement of a
      different thing. Measured on one tree: **3,230 missed with two modules failing to
      import against 3,169 with them importing** — a 61-statement phantom, larger than the
      51-statement spread this plan tells you to tolerate, and in the same direction a
      real regression would move. The cause was that the container image carried neither
      `coverage` nor `hypothesis`, so `test_property_log_parsers.py` and
      `test_property_ts_realignment.py` failed at import. The script now says so before
      the figures (`coverage_live_path: THE FIGURES BELOW ARE INVALID — a failed label`,
      `scripts/coverage_live_path.sh:175`) and exits 1 — that improvement is on this
      branch via the `6e292d53` merge. **Check the exit code of every run, and discard any
      run that did not exit 0.** Do not average a bad run in, and do not report a figure
      taken from one.
      ```
      for i in 1 2 3; do
        docker exec -e COVERAGE_LIVE_PATH_DATA_DIR=/tmp/2a6-base-$i \
          dispatcharr-testrunner-2a6 bash /repo/scripts/coverage_live_path.sh
      done
      ```
      Record for each run: `TOTAL` statements (**must be 7978 every time — the
      denominator is the check and does not vary**), `TOTAL` `Miss`, and the `Miss`
      column for `apps/proxy/live_proxy/output/fmp4/manager.py`,
      `output/fmp4/generator.py`, `output/fmp4/buffer.py` and
      `output/profile/manager.py`. A changed denominator is a finding; a changed `Miss`
      is ordinary variance — see the 51-statement spread in Global Constraints.
- [ ] **Step 5.** Save the baseline missed-line **sets** *inside the container*, at
      `/tmp/2a6-base-missing.json`, which is what Task 9 diffs against (totals are not
      evidence). The repo is mounted read-only, so this file lives in the container's own
      `/tmp` and the container must therefore survive until Task 9 — do not restart it
      between the two measurements, and if you must, re-take the baseline.
      ```
      docker exec dispatcharr-testrunner-2a6 /dispatcharrpy/bin/python -c '
      import json
      d = json.load(open("/tmp/2a6-base-1/live-path.json"))["files"]
      keep = {k: v["missing_lines"] for k, v in d.items() if "/output/" in k}
      json.dump(keep, open("/tmp/2a6-base-missing.json", "w"))
      print(sorted(keep))'
      ```
      It must print the four output paths. Copy the same JSON out to your scratchpad as a
      belt-and-braces backup:
      `docker cp dispatcharr-testrunner-2a6:/tmp/2a6-base-missing.json <scratchpad>/`.
- [ ] **Step 6.** Record the wall time of the `apps.proxy.live_proxy` label as it stands
      today, for 2a-4's 45 s reconsideration trigger:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && time python manage.py test apps.proxy.live_proxy.tests'`.
      Write the figure down; Task 9 repeats it.
- [ ] **Step 7.** Commit nothing. This task produces numbers, not a diff. Paste the
      baseline table into the PR description draft as you go.

---

## Task 2 — `output_support.py`, and one additive harness fix

**Files:** `apps/proxy/live_proxy/tests/harness/asset.py` (edit),
`apps/proxy/live_proxy/tests/output_support.py` (new)

**Interfaces:**
```python
build_real_ts_asset(seconds: float = 2.0, *, keyframe_interval: int | None = None) -> bytes
real_ffmpeg_environment()                 # context manager; skips if ffmpeg is unusable
fragmentable_upstream_payload()           # bytes: a real TS asset a remux can fragment
spawn_logging_standin(directory, log_path, *, name="output-standin") -> str
spawn_count(log_path) -> int
standin_stream_profile(directory, *, name, extra: str = "") -> StreamProfile
StreamTap                                 # background reader: bytes, last_byte_at, ended_at
tapped(test, channel, query="")           # context manager yielding a StreamTap
```

- [ ] **Step 1.** Add one optional keyword argument to `build_real_ts_asset` in
      `apps/proxy/live_proxy/tests/harness/asset.py`. This is the plan's one sanctioned
      `harness/` edit: the helper was written for this PR (its own docstring says *"that
      is 2a-6's territory"*), it is an IMPROVEMENT for the fMP4 path (§ F3 — smaller,
      sooner fragments; the asset works without it too, since every caller loops the
      payload), and the alternative — a near-duplicate builder in `output_support.py` —
      leaves the trap in place for the next caller. It is additive, at the end of a
      signature.

      **Conflict check, done rather than assumed, and worth redoing at implementation
      time**: `git diff HEAD...origin/migration/phase2a-ts-generator-coverage -- apps/proxy/live_proxy/tests/harness/`
      shows 2a-3 (#239) touching only `README.md` and `control.py`, not `asset.py`. If
      2a-3 later lands the `synthetic_ts` payload change it has been reported to be
      making, it edits the **top** of `asset.py` while this edit is in
      `build_real_ts_asset` at the **bottom**, roughly ninety lines apart — far enough to
      merge cleanly. Re-run that diff before you edit; if 2a-3 has by then changed
      `build_real_ts_asset` itself, fall back to a local builder in `output_support.py`
      and say so in the PR description.

      **And check `synthetic_ts`'s current shape rather than this plan's description of
      it.** 2a-3 has a payload change in flight for it — a packet index, because its row-8
      test could not tell positions apart beyond 256 packets. Read the function before
      relying on what any document says its bytes are. Where that does and does not bite,
      stated precisely so the check is cheap: **Tasks 4, 5 and 6 are not exposed at all** —
      they replace the payload outright with `fragmentable_upstream_payload()`, a real
      ffmpeg encode, because a synthetic stream cannot be remuxed to fMP4 (§ F1). **Task 3
      does use the default `synthetic_ts` payload**, and its only assertion over those
      bytes is `assert_ts_aligned`, which checks the 0x47 sync byte at a 188-byte stride —
      a property any packet-index change must preserve to be useful to 2a-3 either. So the
      expected exposure is nil; confirm that rather than assume it, and if Task 3 ever
      grows an assertion about payload *content*, this is the paragraph that stops it
      being written against a stale description.

      Change the signature to
      `def build_real_ts_asset(seconds: float = 2.0, *, keyframe_interval: int | None = None) -> bytes:`
      and insert `-g <keyframe_interval>` into the encoder arguments immediately before
      `"-b:v", "400k"` when it is not None. Add to the docstring:

      > `keyframe_interval` is `-g`: with libx264's default (250 frames) a 2-second asset
      > has one keyframe, so `-movflags frag_keyframe` produces a single `moof` for the
      > whole asset. That is NOT unusable through the fMP4 remux by itself — a caller
      > that loops the payload (`harness.upstream.FakeUpstream` does) still gets more
      > than one fragment, because the next loop's own `moof` bounds the previous one.
      > Passing a value well below `seconds × rate` here is an IMPROVEMENT, not a
      > requirement: it trades one large fragment per loop for several smaller ones,
      > which reaches a client's first fragment sooner. See the 2a-6 plan's F3.
- [ ] **Step 2.** Create `apps/proxy/live_proxy/tests/output_support.py` with a module
      docstring saying what it is and why it is not in `harness/`:

      ```python
      """Levers the output-side (fMP4, Output Profile) behaviour tests pull.

      Deliberately NOT under harness/: harness/ is 2a-2's deliverable and both 2a-3
      (PR #239) and 2a-5 (PR #237) sit off the same base with harness/ edits of their
      own, so an addition there is a merge conflict for another open PR. 2a-4's
      manager_support.py exists for the same reason and this file follows it.

      Two child programs appear in this PR and the split is deliberate (harness/README.md
      § The stated rule): the stand-in wherever the subject is the relay's reaction to a
      process, real ffmpeg wherever the subject is the bytes a remuxer produces. A dumb
      pipe cannot drive the fMP4 path at all -- FMP4RemuxManager parses moof boxes out of
      its child's stdout and MPEG-TS carries none.
      """
      ```
- [ ] **Step 3.** Add `real_ffmpeg_environment()`. `os.posix_spawn` hands the child
      `os.environ` (§ F5), so the variable has to be in the **test process's** environment,
      not in a `subprocess.run` env dict:

      ```python
      @contextlib.contextmanager
      def real_ffmpeg_environment():
          """`ffmpeg` on PATH, actually runnable, for the duration.

          require_real_ffmpeg() skips (not fails) when the image links ffmpeg wrongly:
          whether ffmpeg loads is a property of the image, not of the code under test.
          The LD_LIBRARY_PATH export is issue #226's workaround, applied to os.environ
          because live_proxy/utils.py:154 passes os.environ straight to os.posix_spawn --
          harness.asset.ffmpeg_env() only reaches the harness's own subprocess calls.
          """
          require_real_ffmpeg()
          with patch.dict(os.environ, ffmpeg_env()):
              yield
      ```
- [ ] **Step 4.** Add the payload helper, with the measured numbers in its docstring:

      ```python
      _PAYLOAD_SECONDS = 2.0
      _PAYLOAD_GOP = 12

      @functools.lru_cache(maxsize=1)
      def fragmentable_upstream_payload() -> bytes:
          """A real TS asset the fMP4 remux can turn into more than one fragment per loop.

          gop=12 at 25 fps is a keyframe every ~0.48s, so one 2-second loop carries five
          moof boxes -- measured, against ffmpeg 8.1.2. This is an IMPROVEMENT over the
          default (no -g, one keyframe per 250 frames, ONE moof for the whole asset), not
          a requirement: FakeUpstream loops its payload, so even the one-moof-per-loop
          shape still gets flushed once per loop (the next loop's own moof bounds the
          previous fragment). -g 12 instead gives five smaller fragments per loop
          (~22 KB each, vs. ~95 KB for the whole loop unfragmented), which reaches a
          client's first fragment sooner. See the 2a-6 plan's F3.

          Cached: building it costs about a second of real ffmpeg and every test in this
          PR wants the same bytes.
          """
          return build_real_ts_asset(_PAYLOAD_SECONDS, keyframe_interval=_PAYLOAD_GOP)
      ```
      Note that `lru_cache` survives `TransactionTestCase`'s flush because it holds bytes,
      not rows.
- [ ] **Step 5.** Add the spawn-logging stand-in. It is the stand-in — it imports nothing
      from the repository and is a genuinely external program — with one line added
      before it runs:

      ```python
      _STANDIN_SOURCE = os.path.join(
          os.path.dirname(os.path.abspath(harness_process.__file__)), "standin.py"
      )

      def spawn_logging_standin(directory, log_path, *, name="output-standin"):
          """An executable that appends its pid to `log_path`, then runs harness/standin.py.

          Why a log rather than a process count: the claim matrix row 11 makes is about
          how many transcodes are STARTED for one (channel, profile) pair, and a log of
          spawns says that directly. A count of surviving processes says it only
          indirectly, needs /proc or pgrep, and -- as the e2e spec this re-pins has to
          document at length -- is ambiguous about processes from elsewhere.

          Copied into `directory` for the same reason StandInBin copies it: the repository
          is bind-mounted read-only in the test container, so nothing in the tree can be
          given an exec bit at test time.
          """
          shutil.copyfile(_STANDIN_SOURCE, os.path.join(directory, "standin.py"))
          wrapper = os.path.join(directory, name)
          body = (
              f"#!{sys.executable}\n"
              "import os, runpy, sys\n"
              f"open({log_path!r}, 'a').write(str(os.getpid()) + chr(10))\n"
              "sys.argv[0] = 'ffmpeg'\n"
              f"runpy.run_path(os.path.join({directory!r}, 'standin.py'), run_name='__main__')\n"
          )
          with open(wrapper, "w", encoding="utf-8") as handle:
              handle.write(body)
          os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
          return wrapper


      def spawn_count(log_path) -> int:
          """How many times the logging stand-in has been spawned. 0 if never."""
          try:
              with open(log_path, encoding="utf-8") as handle:
                  return len([line for line in handle if line.strip()])
          except FileNotFoundError:
              return 0
      ```
- [ ] **Step 6.** Add `standin_stream_profile(directory, *, name, extra="")`, which builds
      a `StreamProfile` whose `command` is an absolute path to a logging stand-in rather
      than the bare string `ffmpeg`. This is what keeps the input child a stand-in while
      `ffmpeg` on PATH stays **real** for the fMP4 remux — `StandInBin` cannot be used in
      any fMP4 test, because it shadows `ffmpeg` on PATH and `FFMPEG_REMUX_CMD[0]` is the
      bare string `"ffmpeg"`:

      ```python
      def standin_stream_profile(directory, *, name, extra=""):
          """An input StreamProfile that spawns the stand-in WITHOUT shadowing `ffmpeg`.

          StandInBin puts its wrapper first on PATH, which also captures
          output/fmp4/manager.py:32's FFMPEG_REMUX_CMD -- and a dumb pipe cannot produce
          an fMP4 init segment (this plan's F1). Naming the executable in the profile row
          reaches input/manager.py's spawn (build_command at core/models.py:200) and
          leaves PATH alone.

          `extra` carries stand-in flags, e.g. "--dead-air-after-bytes 2500000".
          """
          from core.models import StreamProfile

          log = os.path.join(directory, f"{name}-spawns.log")
          executable = spawn_logging_standin(directory, log, name=name)
          profile = StreamProfile.objects.create(
              name=f"harness-{name}",
              command=executable,
              parameters=f"-i {{streamUrl}} {extra}".strip(),
          )
          return profile
      ```
      The stand-in's argument parser matches `--dead-air-after-bytes` explicitly before
      its generic `startswith("-")` branch (`harness/standin.py:_parse`), so the flag
      survives `shlex_split`.
- [ ] **Step 7.** Add `StreamTap` and `tapped()`. A background thread rather than socket
      timeouts, because the distinction the row-12 pin turns on — *ended* versus *still
      open but silent* — is exactly what a blocking iterator in its own thread reports
      cleanly and what `iter_content` plus a read timeout reports badly:

      ```python
      class StreamTap(threading.Thread):
          """Drains a streaming response in the background, recording when it went quiet
          and when (if ever) it ended.

          A real thread, not a greenlet: manage.py test is not monkey-patched
          (harness/README.md), so this is the same primitive FakeUpstream already uses.
          """

          def __init__(self, response):
              super().__init__(daemon=True, name="stream-tap")
              self._response = response
              self._lock = threading.Lock()
              self._buffer = bytearray()
              self.bytes_read = 0
              self.last_byte_at = None
              self.ended_at = None
              self.error = None

          def run(self):
              try:
                  for chunk in self._response.iter_content(chunk_size=4096):
                      if not chunk:
                          continue
                      with self._lock:
                          self._buffer += chunk
                          self.bytes_read += len(chunk)
                          self.last_byte_at = time.monotonic()
              except Exception as exc:          # the response being closed is an ordinary end
                  self.error = exc
              finally:
                  with self._lock:
                      self.ended_at = time.monotonic()

          def snapshot(self) -> bytes:
              with self._lock:
                  return bytes(self._buffer)

          def quiet_for(self) -> float:
              """Seconds since the last byte, or since the tap started if none arrived."""
              with self._lock:
                  return time.monotonic() - (self.last_byte_at or self._started_at)
      ```
      Set `self._started_at = time.monotonic()` in `start()` (override it, call `super()`).
      Then:

      ```python
      @contextlib.contextmanager
      def tapped(test, channel, query=""):
          """GET /proxy/ts/stream/<uuid><query> over real HTTP, drained in the background.

          NEVER format response.text into an assertion message on a 200: the body of a
          live tune does not end and the read never returns (harness/relay.py's `tuned`
          carries the same warning, for the same reason).
          """
          url = f"{test.live_server_url}/proxy/ts/stream/{channel.uuid}{query}"
          response = requests.get(url, stream=True, timeout=20)
          if response.status_code != 200:
              body = response.text[:200]
              response.close()
              test.fail(f"tune returned {response.status_code}: {body}")
          tap = StreamTap(response)
          tap.start()
          try:
              yield tap
          finally:
              response.close()
      ```
- [ ] **Step 8.** Add `wait_for_bytes(test, tap, count, *, timeout, what)`, a thin
      `wait_until` wrapper that fails naming what was being waited for and how many bytes
      did arrive:

      ```python
      def wait_for_bytes(test, tap, count, *, timeout=10.0, what="bytes"):
          wait_until(
              lambda: tap.bytes_read >= count,
              timeout=timeout,
              what=f"{count} {what} (got {tap.bytes_read} so far)",
          )
      ```
      Note that `wait_until`'s message is built once, at the raise, so the count in it is
      the final one.
- [ ] **Step 9.** Add the two MP4 shape helpers the fMP4 tests assert with. They read the
      box structure rather than searching for a byte string, so a test cannot pass on a
      `moof` that happens to appear inside media data:

      ```python
      def mp4_boxes(data: bytes):
          """[(offset, size, type)] walking the top-level MP4 box chain, stopping at the
          first malformed length. Deliberately a re-implementation of the walk rather
          than an import of _find_moof_offset: a test that parses with the code under
          test proves the code agrees with itself."""

      def assert_fmp4_init_then_fragment(test, data: bytes):
          """Fail unless `data` is ftyp, then moov, then at least one moof followed by an
          mdat -- the shape output/fmp4/manager.py splits at and the shape a player needs."""
      ```
- [ ] **Step 10.** Run the label to prove the module imports cleanly and breaks nothing:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && python manage.py test apps.proxy.live_proxy.tests'`.
      Expect the same pass count as before plus zero (no tests added yet).
- [ ] **Step 11.** Stage, then commit in a separate call, message in a file, `-F`:
      `test(phase2): 2a-6 support module — the output-side levers, and a keyframe interval for the real TS asset`.

---

## Task 3 — Matrix row 11: one transcode per `(channel, profile)`

**Files:** `apps/proxy/live_proxy/tests/test_output_profile_sharing.py` (new)

**Interfaces:** `RelayHarnessTestCase`, `manager_support.proxy_stream_profile`,
`output_support.spawn_logging_standin` / `spawn_count` / `tapped` / `wait_for_bytes`,
`harness.asset.assert_ts_aligned`, `RedisKeys.output_owner`

This test needs **no real ffmpeg** (§ F6) and **no `StandInBin`**: the input is the locked
Proxy profile, which spawns nothing, so every spawn in the process belongs to the Output
Profile under test. That mirrors the e2e spec's own reason for choosing Proxy, and here it
is exact rather than approximate.

- [ ] **Step 1.** Write the module docstring, naming the row and the re-pin:

      ```python
      """Matrix row 11: one transcode process per active (channel, profile) pair.

      Re-pins the row that e2e/tests/streaming-greybox/output-profile-sharing.spec.ts
      already covers. Both stand: the e2e spec proves it through nginx in a real
      container by counting `pgrep -x ffmpeg`; this proves it in-process by counting
      SPAWNS of the profile's own command, which is unambiguous without a container-wide
      pre-flight and which 2c-7 can reproduce unchanged in Go.

      The channel's input is the locked Proxy stream profile, which spawns no subprocess
      at all, so every line in the spawn log is an Output Profile transcode.
      """
      ```
- [ ] **Step 2.** Write the test body:

      ```python
      class OutputProfileSharingTests(RelayHarnessTestCase):
          def test_two_clients_on_one_output_profile_share_a_single_transcode(self):
              directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
              self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
              log = os.path.join(directory, "spawns.log")
              executable = spawn_logging_standin(directory, log)

              output = OutputProfile.objects.create(
                  name="harness-output-profile",
                  command=executable,
                  parameters="-i pipe:0 -f mpegts pipe:1",
                  is_active=True,
              )
              channel = self.make_channel(
                  upstream_url=self.upstream.url, profile=proxy_stream_profile()
              )
              query = f"?output_profile={output.id}"

              with tapped(self, channel, query) as first:
                  wait_for_bytes(self, first, 20 * TS_PACKET_SIZE, what="bytes for the first client")
                  with tapped(self, channel, query) as second:
                      wait_for_bytes(self, second, 20 * TS_PACKET_SIZE, what="bytes for the second client")

                      assert_ts_aligned(first.snapshot()[: 20 * TS_PACKET_SIZE])
                      assert_ts_aligned(second.snapshot()[: 20 * TS_PACKET_SIZE])

                      self.assertEqual(
                          spawn_count(log), 1,
                          "two clients on one output profile spawned "
                          f"{spawn_count(log)} transcodes, expected exactly 1",
                      )

                      owner_key = RedisKeys.output_owner(
                          str(channel.uuid), f"mpegts:p{output.id}"
                      )
                      self.assertTrue(
                          ProxyServer.get_instance().redis_client.exists(owner_key),
                          f"no owner lock at {owner_key}; the transcode never claimed the pair",
                      )
              self.stop_channel(channel)
      ```
      The owner-lock assertion is complementary, not redundant — it is the e2e spec's own
      second assertion, and its key name is more useful in a failure message than a bare
      count. It is built through `RedisKeys` rather than hardcoded, which trades "a key
      rename is caught" for "a key rename does not fail this test for the wrong reason";
      say so in a comment.
- [ ] **Step 3.** Run it:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && python manage.py test apps.proxy.live_proxy.tests.test_output_profile_sharing -v2'`.
      Expect `OK`, one test, under 5 s.
- [ ] **Step 4.** **Break check.** The repo is bind-mounted **read-only**, so patch a
      writable copy inside the container and run the test from there. This copy is the
      break-check idiom for the whole PR; Task 6 reuses it.
      ```
      docker exec dispatcharr-testrunner-2a6 bash -lc '
        rm -rf /work && cp -a /repo /work &&
        sed -i "s/^        if profile_id in channel_profiles:$/        if False and profile_id in channel_profiles:/" \
          /work/apps/proxy/live_proxy/server.py'
      ```
      **Confirm the break applied before you run anything:**
      ```
      docker exec dispatcharr-testrunner-2a6 grep -n "if False and profile_id in channel_profiles:" /work/apps/proxy/live_proxy/server.py
      ```
      must print exactly one line, inside `ensure_output_profile`. A `sed` that matched
      nothing exits 0 and leaves a green run that proves nothing — this grep is what makes
      the break check evidence. Then:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /work && python manage.py test apps.proxy.live_proxy.tests.test_output_profile_sharing -v2'`.
- [ ] **Step 5.** Read the failure and check it is the right one. **Predicted, not
      observed — record what actually printed and replace this quotation if it differs.**
      With the short-circuit gone the second client falls through to the stale-state
      branch, finds
      `owner_val == self.worker_id` (one worker, one process), reaches
      `am_i_owner` → True and starts a **second** manager whose `_acquire_owner_lock`
      returns True on the `existing == self.worker_id` path
      (`output/profile/manager.py:444-445`). The expected failure is:
      ```
      AssertionError: 2 != 1 : two clients on one output profile spawned 2 transcodes, expected exactly 1
      ```
      If the failure is anything else — an empty read, a 500 — the test is failing for a
      reason other than its subject; fix that before continuing.
- [ ] **Step 6.** Discard the copy (`docker exec dispatcharr-testrunner-2a6 rm -rf /work`).
      Re-run the test from `/repo` and confirm `OK`.
- [ ] **Step 7.** Stage, then commit separately, message in a file:
      `test(phase2): row 11 — two clients on one Output Profile share a single transcode`.

---

## Task 4 — The fMP4 pipeline, end to end

**Files:** `apps/proxy/live_proxy/tests/test_fmp4_output.py` (new)

**Interfaces:** `real_ffmpeg_environment`, `fragmentable_upstream_payload`,
`standin_stream_profile`, `tapped`, `wait_for_bytes`, `assert_fmp4_init_then_fragment`,
`patch.object(TSConfig, "BUFFER_CHUNK_SIZE", …)`

This is the PR's largest coverage mover: it is the only thing that reaches
`FMP4RemuxManager._reader_loop`'s init parsing and `_flush_complete_fragments`,
`FMP4StreamBuffer.put_fragment`/`get_chunks`, and the whole of
`FMP4StreamGenerator._setup_streaming`/`_stream_data_generator`.

- [ ] **Step 1.** Set the class up so the expensive parts happen once:

      ```python
      class FMP4OutputTests(RelayHarnessTestCase):
          """The fMP4 output path against a REAL ffmpeg remux.

          Real ffmpeg, not the stand-in, and the reason is structural rather than a
          preference: FMP4RemuxManager parses moof boxes out of its child's stdout
          (output/fmp4/manager.py:316-332) and a dumb pipe carrying MPEG-TS contains
          none, so a stand-in remux stores no init segment, _wait_for_fmp4_ready polls
          for INIT_SEGMENT_TIMEOUT (15s) and the client gets an empty 200. See the 2a-6
          plan's F1.
          """

          def setUp(self):
              super().setUp()
              self.enterContext(real_ffmpeg_environment())
              # A real TS asset, and a bigger chunk than the base class's 1,880 bytes:
              # this test moves megabytes rather than kilobytes and 1,880-byte chunks
              # would put thousands of keys into the shared DB 0 (harness/README.md's
              # second trap). 37,600 bytes at 500 KB/s is a chunk every 75ms, still far
              # below anything a client waits on.
              self.upstream.payload = fragmentable_upstream_payload()
              self.upstream.rate = 2.0
              self.enterContext(patch.object(TSConfig, "BUFFER_CHUNK_SIZE", TS_PACKET_SIZE * 200))
      ```
      Three notes on that block. `enterContext` is on `unittest.TestCase` from Python 3.11
      and the container runs 3.13. The base class already patches `BUFFER_CHUNK_SIZE` to
      `TS_PACKET_SIZE * 10`; this one nests over it and unwinds cleanly. And reassigning
      `self.upstream.payload`/`.rate` after `FakeUpstream.start()` is safe **only because
      no request has been made yet** — `_Handler._stream` reads both per request
      (`harness/upstream.py`), so do it in `setUp`, never mid-tune.
- [ ] **Step 2.** Write the first test — an fMP4 client on a channel a TS client has
      already brought up, which keeps `channel_initializing` False and avoids
      `_wait_for_channel_ready`'s 60 s ceiling:

      ```python
      def test_an_fmp4_client_receives_an_init_segment_and_fragments(self):
          directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
          self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
          profile = standin_stream_profile(directory, name="fmp4-input")
          channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

          with tapped(self, channel) as ts_client:
              wait_for_bytes(self, ts_client, 20 * TS_PACKET_SIZE, what="TS bytes")
              with tapped(self, channel, "?output_format=fmp4") as fmp4_client:
                  # 14s, deliberately under INIT_SEGMENT_TIMEOUT's 15: past that the
                  # generator gives up and returns an empty 200, and the failure would
                  # read as "no bytes" instead of "the remux never produced an init
                  # segment". Measured end-to-end at 1.69s against a 250 KB/s feed.
                  wait_for_bytes(self, fmp4_client, 40_000, timeout=14.0, what="fMP4 bytes")
                  assert_fmp4_init_then_fragment(self, fmp4_client.snapshot())
          self.stop_channel(channel)
      ```
- [ ] **Step 3.** Run it and read the whole output, not just the verdict:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && python manage.py test apps.proxy.live_proxy.tests.test_fmp4_output -v2'`.
      If it fails, the three likely causes, in order, are: the asset has one keyframe
      (§ F3 — check `fragmentable_upstream_payload` passes `keyframe_interval`); the
      child ffmpeg cannot load (§ F5 — check `real_ffmpeg_environment` is entered, and
      look for `rist_peer_config_defaults_set_versioned` in the captured logs); the
      remux writer started at a buffer head that never advances (raise
      `self.upstream.rate`). Do not "fix" it by lengthening the timeout.
- [ ] **Step 4.** Add a second test for the joining client, which exercises
      `_setup_streaming`'s non-initializing branch (`output/fmp4/generator.py:210-241`)
      and `FMP4StreamBuffer.find_chunk_index_by_time`:

      ```python
      def test_a_second_fmp4_client_joins_the_running_remux(self):
          ...
          with tapped(self, channel) as ts_client:
              wait_for_bytes(self, ts_client, 20 * TS_PACKET_SIZE, what="TS bytes")
              with tapped(self, channel, "?output_format=fmp4") as first:
                  wait_for_bytes(self, first, 40_000, timeout=14.0, what="fMP4 bytes for the first client")
                  spawns_before = spawn_count(remux_log)   # see Step 5
                  with tapped(self, channel, "?output_format=fmp4") as second:
                      wait_for_bytes(self, second, 40_000, timeout=14.0, what="fMP4 bytes for the second client")
                      assert_fmp4_init_then_fragment(self, second.snapshot())
      ```
      The second client is served from the same remux, and the assertion that says so is
      that it receives a well-formed init segment plus a fragment **without** a second
      `moof`-producing child appearing.
- [ ] **Step 5.** To count remux spawns here the child must be the *real* ffmpeg, so the
      spawn-log trick from Task 3 is not available (it would shadow `ffmpeg` on PATH and
      break the remux). Assert the sharing through the owner lock instead — one key, one
      value — and say in a comment that row 11's spawn-count pin is the sharing pin and
      this is its fMP4 sibling, deliberately weaker:
      ```python
      owner_key = RedisKeys.output_owner(str(channel.uuid), "fmp4")
      self.assertEqual(
          ProxyServer.get_instance().redis_client.get(owner_key),
          ProxyServer.get_instance().worker_id,
          "the fMP4 remux owner lock moved between the two clients",
      )
      ```
      Drop the `spawns_before` line from Step 4 when you do; it was a placeholder for a
      count this shape cannot take.
- [ ] **Step 6.** Run the file. Record its wall time. Expect both tests green in under
      15 s combined; if either exceeds 10 s alone, raise `self.upstream.rate` before
      raising a timeout, and record the value you settled on and why.
- [ ] **Step 7.** Stage, then commit separately:
      `test(phase2): the fMP4 output path, against a real remux`.

---

## Task 5 — fMP4 layered on an Output Profile

**Files:** `apps/proxy/live_proxy/tests/test_fmp4_output.py` (extend)

The `fmp4:p<id>` compound key is a distinct path through `views.py:696-699`,
`ProxyServer._parse_output_key` and `ensure_output_format`'s `source_buffer` argument, and
nothing else in the suite reaches it. It is cheap here because the two children compose:
the Output Profile's child is named by an absolute path (a stand-in dumb pipe passing real
TS through), and the fMP4 remux's child is the bare `ffmpeg` from PATH (real).

- [ ] **Step 1.** Add the test:

      ```python
      def test_an_fmp4_client_on_an_output_profile_gets_its_own_pipeline(self):
          directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
          self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
          log = os.path.join(directory, "profile-spawns.log")
          executable = spawn_logging_standin(directory, log, name="profile-standin")
          output = OutputProfile.objects.create(
              name="harness-output-profile-fmp4",
              command=executable,
              parameters="-i pipe:0 -f mpegts pipe:1",
              is_active=True,
          )
          channel = self.make_channel(
              upstream_url=self.upstream.url, profile=proxy_stream_profile()
          )
          query = f"?output_format=fmp4&output_profile={output.id}"

          with tapped(self, channel, query) as client:
              wait_for_bytes(self, client, 40_000, timeout=14.0, what="fMP4 bytes")
              assert_fmp4_init_then_fragment(self, client.snapshot())
              self.assertEqual(spawn_count(log), 1, "the Output Profile transcode did not start exactly once")
              # The compound key is the point of this test: the remux runs under
              # `fmp4:p<id>`, not `fmp4`, and reads the PROFILE's buffer rather than the
              # raw TS buffer (views.py:696-699, :736-739, :756).
              redis_client = ProxyServer.get_instance().redis_client
              self.assertTrue(
                  redis_client.exists(RedisKeys.output_state(str(channel.uuid), f"fmp4:p{output.id}")),
                  "no fMP4 state key under the compound format key",
              )
              self.assertFalse(
                  redis_client.exists(RedisKeys.output_state(str(channel.uuid), "fmp4")),
                  "a bare `fmp4` remux started as well as the profile-scoped one",
              )
          self.stop_channel(channel)
      ```
      Note this test uses the **Proxy** input profile: with an Output Profile in play there
      is no need for an input child, and one fewer process is one fewer thing to go wrong.
- [ ] **Step 2.** Run the file; expect three tests green.
- [ ] **Step 3.** **Reach check (tier 1).** Confirm the compound path really executed
      rather than the test passing on the bare-`fmp4` path by luck: run with `-v2` and
      grep the captured relay logs for `[output:fmp4:p` —
      `… -v2 2>&1 | grep -c '\[output:fmp4:p'` must be ≥ 1. If it is 0 the assertions
      above are passing for the wrong reason and the query string is not being honoured.
      **This grep is a reach-check trap at the hooks' own default log level.**
      `server.py`'s `ensure_output_profile` logs `[output:{fmt}]` at `logger.info`, and
      `DISPATCHARR_LOG_LEVEL=WARNING` — the level every `dexec()` recipe in this repo
      uses by default — suppresses it, so the grep returns 0 there even though the
      compound path ran correctly. That reads exactly like "the path is never reached",
      which is the wrong conclusion. Run this one check with
      `-e DISPATCHARR_LOG_LEVEL=INFO` added to the `docker exec`; the routine test runs
      that don't need to read this log stay at `WARNING`.
- [ ] **Step 4.** Stage, then commit separately:
      `test(phase2): an fMP4 client layered on an Output Profile`.

---

## Task 6 — Matrix row 12: the fMP4 client timeout (#222), reproduced not fixed

**Files:** `apps/proxy/live_proxy/tests/test_fmp4_client_timeout.py` (new)

**The pin is a defect pin.** The test asserts the *wrong* behaviour on purpose, per spec
D5, and its docstring must say so loudly enough that a future reader does not "fix" it.

**What is being pinned, precisely (§ F8).** With the source stalled and the channel still
healthy, an fMP4 client's response **ends** `stream_timeout + failover_grace_period` after
its last fragment, while a TS client on the same channel at the same moment is **still
open**. The `url_switching` clause row 12 names is a sub-millisecond window in production
and is not what this test provokes; the divergence it does provoke — no health check, no
keepalive — is present on every stall and is the reachable form of the same defect. Task 7
amends the row to say that.

- [ ] **Step 1.** Write the module docstring:

      ```python
      """Matrix row 12 / issue #222: the fMP4 generator drops a stalled client, and the
      TS generator does not.

      THIS TEST PINS A DEFECT. It asserts the behaviour that is WRONG, deliberately,
      because spec D5 holds the Go relay to strict parity including known defects: 2c-6
      must reproduce this drop, so 2a must be able to tell whether it did. Do not "fix"
      this test by making the fMP4 client survive; fixing #222 means changing
      output/fmp4/generator.py:339-346 AND this test AND the matrix row together.

      What the two generators actually do, which is broader than row 12's original
      wording (see the 2a-6 plan's F8): the TS generator returns True only when the
      stream manager is unhealthy (output/ts/generator.py:584) and, before it can get
      there, sends keepalive packets that refresh last_yield_time and stop _is_timeout()
      firing at all -- its own comment at :311-312 says so, capped by
      MAX_KEEPALIVE_DURATION (300s). The fMP4 generator has no health check, no
      url_switching exemption and no keepalive: elapsed time alone disconnects it.
      """
      ```
- [ ] **Step 2.** Write the fixture. The input child must go quiet while staying alive —
      that is `--dead-air-after-bytes`, which stops writing to stdout and sleeps forever
      (`harness/standin.py`'s copy loop). A `FakeUpstream` fault cannot be used: `dead-air`
      and `disconnect` are both read once at `_stream()` entry
      (`harness/upstream.py:_Handler`), so arming either mid-tune does nothing to a
      connection already in flight.

      ```python
      class FMP4ClientTimeoutTests(RelayHarnessTestCase):
          # Compressed from 20 + 20 = 40s. Both are plain TSConfig class attributes read
          # through ConfigHelper.get (config_helper.py:30, :104), so patching them is the
          # production lever. 1 + 1 = 2s is short enough that the health monitor has not
          # yet flipped the channel unhealthy (CONNECTION_TIMEOUT is 10s and is NOT
          # compressed here, on purpose: an unhealthy channel would start the TS
          # keepalives and blur which of the two mechanisms held the TS client open).
          TIMEOUT = 1
          GRACE = 1

          def setUp(self):
              super().setUp()
              self.enterContext(real_ffmpeg_environment())
              self.upstream.payload = fragmentable_upstream_payload()
              self.upstream.rate = 2.0
              self.enterContext(patch.object(TSConfig, "BUFFER_CHUNK_SIZE", TS_PACKET_SIZE * 200))
              self.enterContext(patch.object(TSConfig, "STREAM_TIMEOUT", self.TIMEOUT))
              self.enterContext(patch.object(TSConfig, "FAILOVER_GRACE_PERIOD", self.GRACE))
      ```
- [ ] **Step 3.** Write the test:

      ```python
      def test_a_stalled_fmp4_client_is_dropped_while_a_ts_client_is_not(self):
          directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
          self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
          # 2.5 MB at 500 KB/s puts the stall about five seconds into the tune, which
          # leaves room for the remux to produce its init segment and at least one
          # fragment first (measured at 1.69s against a 250 KB/s feed). If the assertion
          # in the middle of this test fires, RAISE this number rather than the deadlines.
          profile = standin_stream_profile(
              directory, name="fmp4-input", extra="--dead-air-after-bytes 2500000"
          )
          channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

          with tapped(self, channel) as ts_client:
              wait_for_bytes(self, ts_client, 20 * TS_PACKET_SIZE, what="TS bytes")
              with tapped(self, channel, "?output_format=fmp4") as fmp4_client:
                  wait_for_bytes(self, fmp4_client, 40_000, timeout=14.0, what="fMP4 bytes")
                  self.assertIsNone(
                      fmp4_client.ended_at,
                      "the fMP4 stream ended before the source went quiet -- the stall "
                      "arrived too early; raise --dead-air-after-bytes",
                  )

                  # The source goes quiet: no new fragment reaches either client.
                  wait_until(
                      lambda: fmp4_client.quiet_for() > 1.0,
                      timeout=20.0,
                      what="the fMP4 stream to go quiet",
                  )
                  quiet_since = fmp4_client.last_byte_at

                  # THE DEFECT: elapsed time alone ends the fMP4 response.
                  wait_until(
                      lambda: fmp4_client.ended_at is not None,
                      timeout=self.TIMEOUT + self.GRACE + 5.0,
                      what="the fMP4 client to be disconnected by _is_timeout()",
                  )
                  # NOT THE PIN, and a lower bound only. A wall-clock assertion can never
                  # be a pin here (see Global Constraints): this one exists solely to
                  # catch a FALSE POSITIVE -- a teardown that ended the response before
                  # _is_timeout() could have. It fails in one direction and is silent in
                  # the other, which is the only shape a clock is allowed to take in this
                  # PR. The pin is the two assertions around it: the fMP4 response ended
                  # and the TS response did not.
                  self.assertGreaterEqual(
                      fmp4_client.ended_at - quiet_since,
                      self.TIMEOUT + self.GRACE,
                      "the fMP4 client was dropped sooner than "
                      "stream_timeout + failover_grace_period, so this is not _is_timeout()",
                  )

                  # AND THE CONTRAST, which is the whole content of row 12: the TS client
                  # on the same channel, silent for at least as long, is still connected.
                  self.assertIsNone(
                      ts_client.ended_at,
                      "the TS client was dropped too -- there is no divergence to pin, "
                      "and either the health monitor fired or a teardown ended both",
                  )
          self.stop_channel(channel)
      ```
- [ ] **Step 4.** Add the attribution assertion (tier 1, reach). The disconnect must be
      `_is_timeout()`'s, not a teardown that happened to coincide. Wrap the quiet-and-wait
      section in:
      ```python
      with self.assertLogs("live_proxy.generator", level="WARNING") as captured:
          ...
      self.assertTrue(
          any("fMP4 no data for" in line for line in captured.output),
          "no `fMP4 no data for …s, disconnecting` record: the stream ended for some "
          f"other reason. Captured: {captured.output}",
      )
      ```
      `get_logger()` derives its name from the module file, so **both** generators log
      under `live_proxy.generator` — the message text is what separates them
      (`output/fmp4/generator.py:342-344`). Say that in a comment. This assertion is
      attribution; the pin is the EOF above it.
- [ ] **Step 5.** Run it:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && python manage.py test apps.proxy.live_proxy.tests.test_fmp4_client_timeout -v2'`.
      Expect `OK`, one test, roughly 8–10 s. If the TS-client assertion fails, check
      whether `CONNECTION_TIMEOUT` was accidentally compressed, or whether the stall ran
      long enough for the health monitor's three checks to fire; shorten the window rather
      than deleting the assertion.
- [ ] **Step 6.** **Break check — and read this paragraph before choosing a lever, because
      the obvious one does not run.** The row pins a *defect*, so the break runs backwards:
      the patch **adds** the missing behaviour and the test must go red. But **adding the
      `url_switching` exemption specifically cannot serve as that lever here, and would
      produce a green run that proves nothing.** The exemption only returns False when
      `stream_manager.url_switching` is True, and this test provokes a *stall*, not a
      switch — `url_switching` is False throughout, so the added branch never executes and
      the client is dropped exactly as before. That is not a flaw in the test: it is § F8,
      the finding that the flag is set and cleared inside `update_url()`'s own body with no
      network I/O between, giving a sub-millisecond window a test cannot land inside. **A
      lever that cannot fail is the very thing break checks exist to catch, so do not use
      it.**

      Use the guard that the reachable half of the divergence is missing — the TS
      generator's health check (`output/ts/generator.py:584`), which is also the shape a
      real fix for #222 would take. The channel is still healthy at the moment of the drop
      (the stall lands ~5 s in, `CONNECTION_TIMEOUT` is 10 s and `_monitor_health` needs
      three checks), so guarding on health makes the fMP4 client survive:
      ```
      docker exec dispatcharr-testrunner-2a6 bash -lc '
        rm -rf /work && cp -a /repo /work &&
        sed -i "s|^    def _is_timeout(self) -> bool:$|    def _is_timeout(self) -> bool:\\n        return False  # BREAK CHECK ONLY|" \
          /work/apps/proxy/live_proxy/output/fmp4/generator.py'
      ```
      `return False` is that guard reduced to its effect, and is used rather than a
      faithful health lookup because `FMP4StreamGenerator` holds no `stream_manager`
      reference at all — which is itself part of why #222 exists. It breaks the
      mechanism (the generator now does what it is documented never to do: hold a client
      through an unbounded stall) rather than selecting a second documented mode.

      **Confirm the break applied before you run anything:**
      ```
      docker exec dispatcharr-testrunner-2a6 sed -n '339,342p' /work/apps/proxy/live_proxy/output/fmp4/generator.py
      ```
      must show `def _is_timeout(self) -> bool:` immediately followed by
      `return False  # BREAK CHECK ONLY`. Then run the test from `/work`.
- [ ] **Step 7.** Read the failure. **Predicted, not observed** — record what actually
      printed. The expected text is `wait_until`'s, naming what it was waiting for:
      ```
      AssertionError: timed out after 7.0s waiting for the fMP4 client to be disconnected by _is_timeout()
      ```
      With `assertLogs` wrapping that region there is a second plausible shape: `assertLogs`
      fails first, with `no logs of level WARNING or higher triggered on live_proxy.generator`,
      because the break also removes the log record. Either is the right failure — both say
      the drop did not happen. Anything *else* — an earlier `wait_for_bytes` timeout, a
      non-200 tune — means the test is not pinning the disconnect and must be fixed before
      this task can be called done. Whichever appeared, quote the real text in the PR
      description and in this step, replacing the prediction.
- [ ] **Step 8.** Discard the copy (`docker exec dispatcharr-testrunner-2a6 rm -rf /work`).
      Re-run from `/repo`; confirm `OK`.
- [ ] **Step 9.** Stage, then commit separately:
      `test(phase2): row 12 — a stalled fMP4 client is dropped and a TS client is not (#222)`.

---

## Task 7 — The parity matrix

**Files:** `docs/relay-parity-matrix.md`

**Interfaces:** `e2e/tests/guards/parity-matrix.spec.ts` (the guard), run with
`cd e2e && npx playwright test --project=guards parity-matrix` — no container needed.

Read the HTML comment at the top of the matrix before touching it. **One row is one line;
cells are never padded; do not run a Markdown formatter over the file; do not sort by id;
do not delete a `<!-- block: … -->` marker.** `HIGHEST_ROW_ID` stays 28 (§ R6) and
`e2e/tests/guards/parity-matrix.ts` is not edited.

- [ ] **Step 1.** Close row 12 and amend it per § F8. Replace the whole line with a single
      unpadded line whose cells are:
      - `#`: `12`
      - `Behaviour`: `The fMP4 generator's `_is_timeout()` disconnects a client on elapsed time since its last fragment alone — no stream-health check, no `url_switching` exemption and no keepalive — so an fMP4 viewer is dropped `stream_timeout + failover_grace_period` (40s by default) into a stall that leaves a TS viewer on the same channel connected`
      - `Source`: `` `apps/proxy/live_proxy/output/fmp4/generator.py:339-346`, `apps/proxy/live_proxy/output/ts/generator.py:574-595`, `apps/proxy/live_proxy/output/ts/generator.py:311-312`, `apps/proxy/live_proxy/output/ts/generator.py:366-389` ``
      - `Pin`: `` `apps/proxy/live_proxy/tests/test_fmp4_client_timeout.py::FMP4ClientTimeoutTests::test_a_stalled_fmp4_client_is_dropped_while_a_ts_client_is_not` ``
      - `Notes`: keep the existing #222 / D5 sentence verbatim, then append: `The row's original wording named only the `url_switching` clause; 2a-6 found that clause to be near-unreachable — `url_switching` is set and cleared inside `update_url()`'s own body, which does no network I/O, while the TS generator only consults it after 40s of no data — and that the reachable divergence is larger: the TS generator disconnects only an unhealthy stream and, before that, sends keepalives that refresh `last_yield_time` for up to `MAX_KEEPALIVE_DURATION` (300s), which the fMP4 generator has no equivalent of. The pin drives the reachable form; the `url_switching` clause is carried in the citations, not tested. This widens the row rather than narrowing it — the original wording described a race a viewer would almost never lose, and the reality is a disconnect on every sustained stall — and it changes the description only: `_is_timeout()` is untouched, D5 still says reproduce rather than fix, and 2c-6 is held to the drop.`
      - Check every citation range exists: `ts/generator.py` is 684 lines and
        `fmp4/generator.py` is 404, so all four are inside their files.
      - **No cell may contain a literal `|`.**
      - **Nothing in this step edits production code.** If the diff for Task 7 shows a
        change under `apps/`, you have fixed the defect instead of describing it; revert
        and re-read § F8.
- [ ] **Step 2.** Re-pin row 11. Keep the e2e reference and append the harness one to the
      `Pin` cell, comma-separated (rows 10, 13 and 24 already carry multiple references):
      `` …output-profile-sharing.spec.ts::two clients on one output profile share a single transcode`, `apps/proxy/live_proxy/tests/test_output_profile_sharing.py::OutputProfileSharingTests::test_two_clients_on_one_output_profile_share_a_single_transcode` ``
      Replace the Notes tail `2a-6 may re-pin this to a harness test; the existing e2e
      spec stands until it does` with: `2a-6 added the second pin, an in-process harness
      test that counts SPAWNS of the profile's own command rather than surviving
      processes: the channel runs the locked Proxy stream profile, which spawns nothing,
      so every line in the spawn log is an Output Profile transcode. Both stand — the e2e
      spec proves the same claim through nginx in a container.`
- [ ] **Step 3.** Run the guard:
      `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a6/e2e && npx playwright test --project=guards parity-matrix`.
      Expect green. The guard prints a `… pinned, … owed, … white-box-only` census on
      every run: row 12 moves one row from `owed` to `pinned`, and row 11 was already
      pinned so it moves nothing. Read the printed line rather than predicting it — the
      other 2a PRs are closing rows on their own branches and the absolute numbers depend
      on what has merged.
- [ ] **Step 4.** Confirm the contiguity check is satisfied trivially: 2a-6's block now
      holds no `owed:` row at all, so `rows owed by one PR are contiguous`
      (`e2e/tests/guards/parity-matrix.spec.ts:336`) has nothing to order. Confirm the
      `<!-- block: owed by 2a-6 -->` marker line is **kept** even though its block is now
      empty of owed rows — deleting it would put row 12 one line from row 13 and
      reintroduce exactly the conflict the markers prevent.
- [ ] **Step 5.** Record in the PR description that row 11's edit sits one line below row
      10, which 2a-3 has already rewritten, so a modify/modify conflict at merge is
      **expected** and is resolved by taking both sides (§ F10).
- [ ] **Step 6.** Stage, then commit separately:
      `docs(phase2): close row 12 and re-pin row 11; record what row 12 actually diverges on`.

---

## Task 8 — The defect ledger

**Files:** `metrics/curated/defects.yml`

- [ ] **Step 1.** Find the `fmp4-timeout-no-switch-exemption` entry (id on line 22 today).
      It reads `status: open`, `test: null`, `status_changed: 2026-08-22`.
- [ ] **Step 2.** Change it to `status: pinned`,
      `test: apps/proxy/live_proxy/tests/test_fmp4_client_timeout.py`, and
      `status_changed:` to the date this lands — matching exactly the shape 2a-4 used for
      #221 on line 21. Leave `fixed_in: null` and `carried_as: null`: D5 keeps the defect.
- [ ] **Step 3.** Validate:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && python -m metrics.build --validate-only'`
      and `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && bash scripts/run_metrics_tests.sh'`.
      Both must pass.
- [ ] **Step 4.** Stage, then commit separately:
      `chore(phase2): #222 is pinned, not merely open`.

---

## Task 9 — Measure, and say what moved

**Files:** none (measurement), plus the PR description

- [ ] **Step 1.** Take the after-side measurement, three runs, same container, same
      unmodified script (which fixes the core at sysmon), into `/tmp/2a6-after-{1,2,3}`.
      Record `TOTAL` statements (**7978 every time**), `TOTAL` `Miss`, and the four output
      files' `Miss`. **Check each run's exit code and discard any that is non-zero** — per
      Task 1 Step 4, a failed label makes the figures a measurement of something else, and
      the phantom it produces (61 statements, measured) is larger than the spread this
      plan tolerates. This bites harder on the after side than the baseline: your own new
      tests are now in `apps.proxy.live_proxy.tests`, so a genuine failure in one of them
      would both fail the label *and* inflate `Miss` — read the exit code first and the
      figures second.
- [ ] **Step 2.** State the gate as a **separated interval**, which is immune to the
      51-statement spread: the **maximum** after-side `Miss` must be strictly below the
      **minimum** baseline `Miss`. Report both as `min-max`. If the intervals overlap, the
      PR has not demonstrated a coverage increase and the right response is to find out
      why, not to take a fourth run and pick the best one.
- [ ] **Step 3.** Diff the missed-line **sets**, per file, against the baseline JSON saved
      in Task 1 Step 5 — never the totals (§ Global Constraints):
      ```
      docker exec dispatcharr-testrunner-2a6 /dispatcharrpy/bin/python - /tmp/2a6-after-1/live-path.json <<'PY'
      import json, sys
      after = {k: set(v["missing_lines"]) for k, v in json.load(open(sys.argv[1]))["files"].items()}
      base  = {k: set(v) for k, v in json.load(open("/tmp/2a6-base-missing.json")).items()}
      for path in sorted(base):
          gained = sorted(base[path] - after.get(path, set()))
          lost   = sorted(after.get(path, set()) - base[path])
          print(f"{path}: +{len(gained)} covered, {len(lost)} newly missed")
          if lost:
              print("   newly missed:", lost)
      PY
      ```
      Any **newly missed** line is a finding to explain, not noise to absorb — but expect
      a handful in the teardown regions of `output/fmp4/manager.py` and
      `output/profile/manager.py`, which is where this group's variance lives.
- [ ] **Step 4.** Re-measure the `apps.proxy.live_proxy` label's wall time (Task 1
      Step 6). Report before and after. If the after figure crosses **45 s**, stop and say
      so rather than absorbing it: that is 2a-4's ruling (a) reconsideration trigger.
- [ ] **Step 5.** Run the three coverage labels' test suites plainly, to prove nothing
      regressed outside the coverage run:
      `docker exec dispatcharr-testrunner-2a6 bash -lc 'cd /repo && python manage.py test apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests'`.
      Expect green. **If the run fails with no `FAIL:`/`ERROR:` body, that is the
      wrong-tree / MISCONF signature — fix the container, do not debug the tests.**
- [ ] **Step 6.** Write the PR description: the tracer core and how it was selected; the
      baseline and after intervals; the per-file line-set deltas; the label wall times;
      the row-11 conflict warning; and the two findings from Task 10.

---

## Task 10 — File what this PR found and could not take

**Files:** none in the repo (issues), plus the PR description

- [ ] **Step 1.** File the `_handle_bsf_error` dead branch (§ F9):
      `gh issue create --repo D10Scot/Dispatcharr --title "FMP4RemuxManager._handle_bsf_error's stop()-during-restart branch is unreachable" --label needs-triage --body-file <file>`.
      The body states: `output/fmp4/manager.py:403` assigns `self.running = True` and
      `:405` immediately tests `if not self.running:`, so `:406-413` can never run; the
      branch's comment says it handles `stop()` being called during the restart, which the
      assignment above it makes impossible; roughly nine statements inside Phase 2's Gate 2
      denominator are dead by construction. Note that it is **not** fixed here: D5 governs
      *behaviour* parity and dead code is not behaviour, but fixing it is a production
      change and 2a is a test-only stage.
- [ ] **Step 2.** Add the ledger entry for it in `metrics/curated/defects.yml`, in the
      shape 2a-2 used for #226: `status: open`, `test: null`, `area: correctness`,
      `severity: low`, `source: null`, the issue number, today's dates. Re-run
      `python -m metrics.build --validate-only`.
- [ ] **Step 3.** Record in the PR description the deferred obligations this PR
      **declined**, with reasons, so 2a-7 inherits a decision rather than a silence:
      the Proxy/Redirect inert-buffering-detector row (§ R2, stays with 2a-7 — an
      `input/manager.py` behaviour), the rejected-vs-declined credential row (§ R3, an
      `authorize.py` behaviour), row 21's prose-only obligation (§ R4, which row 21's
      own Notes assign to 2a-5 — open as PR #237, so the routes are amending it before it
      merges or 2a-7 inheriting it, and § R4 argues for the first while it is still open),
      and the spec's own open question to this PR (spec `:1265`, `:1424`): does 2a-6 take
      `apps/proxy/live_proxy/input/http_streamer.py`? **Not taken. Still unowned.** Record
      that one line so 2a-7 does not inherit the question silently, the same way the
      other three declines are recorded.
- [ ] **Step 4.** Record the §F3 finding prominently — `build_real_ts_asset()` as
      2a-2 shipped it produces a single `moof` per pass, and every caller here loops the
      payload, so the asset works either way; `-g` (added by this PR) turns one large
      fragment per loop into five smaller, sooner ones. State the improvement, not a false
      impossibility — an earlier draft of this finding overstated it, and the correction
      matters because the next reader of this helper will otherwise assume `-g` is load-
      bearing when it is not.
- [ ] **Step 5.** Stage, then commit separately:
      `chore(phase2): file the unreachable BSF-retry branch`.

---

## Done criteria

- [ ] Four new test files' worth of tests green in `dispatcharr-testrunner-2a6`, run from
      `/repo`, with the full three-label suite green alongside them.
- [ ] Both `owed`-row break checks performed, each with the break **confirmed applied by
      `sed -n` before the run**, each reverted and re-run green — and **the failure text
      each one actually printed recorded in the PR description**, flagged where it differs
      from this plan's prediction.
- [ ] No assertion in this PR compares elapsed time against what production pacing would
      cost. The one clock that survives review is Task 6 Step 3's lower bound, labelled in
      the source as a false-positive guard rather than a pin.
- [ ] `docs/relay-parity-matrix.md`: row 12 closed with a resolvable test reference and an
      amended Behaviour/Notes; row 11 carrying both pins. The guard green, run in the
      `guards` project.
- [ ] `metrics/curated/defects.yml`: #222 `pinned` with its test path; the new dead-branch
      defect added; `python -m metrics.build --validate-only` green.
- [ ] A coverage measurement, three runs a side, same container, same tracer core, **every
      run exited 0**, whose after-side maximum `Miss` is strictly below the baseline
      minimum, reported as intervals with per-file missed-line-set diffs — not as
      differenced totals.
- [ ] The `apps.proxy.live_proxy` label's wall time reported before and after, and under
      45 s.
- [ ] The PR description names: the tracer core and how it was chosen; the expected row-11
      merge conflict; the three declined obligations and why; and the two findings
      (§ F3, § F9).
- [ ] No production code changed. No `harness/` file changed except the one additive
      argument in `asset.py`, argued in Task 2 Step 1.
