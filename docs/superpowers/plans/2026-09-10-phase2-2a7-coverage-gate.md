# Phase 2 PR 2a-7 — the coverage gate, its floor and its CI wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Gate 2 from a number in a spec into a CI-enforced ratchet — a floor file measured on the tree it gates, a `--gate` mode in `scripts/coverage_live_path.sh` that fails a PR that regresses it, per-label CI wiring in `backend-tests.yml`, and an honest record of where stage 2a actually lands against the spec's ≥80%.

**Architecture:** The gate runs one Django test label per container, three containers, combined — the shape `backend-tests.yml`'s matrix already uses, and the shape the isolation probe measured. The floor is a committed file holding the measurement shape, the denominator and a maximum permitted `missing` count, set from the **worst** of at least twelve runs, so the ratchet needs no separate tolerance parameter. Two inherited parity-matrix rows are closed in the same PR.

**Tech Stack:** Bash, `coverage` 7.10+ under `COVERAGE_CORE=sysmon`, Django's test runner, GitHub Actions, Playwright (the parity-matrix guard is a Playwright test), `zizmor` (workflow lint ratchet).

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — § Stage 2a › **Gate 2 — 80% statement coverage**, and the 2a-7 row of the PR table. Read the whole Gate 2 section before Task 5; it is the authority on why the measurement shape is part of the number.

**Branch:** `migration/phase2a-coverage-gate`. 2a-7 measures the tree it gates, so **Task 1 builds that tree** by merging all four coverage branches; it cannot be based on `main`.

---

## THE GATE DECISION — read this before the tasks

**The honest answer today is: unknown, and knowable only by one measurement that nobody has taken.** This section says why, gives the band, and states a **decision rule committed in advance** so that Task 1's measurement picks between the options rather than an arguer picking after seeing the number.

### Why the earlier answer was wrong, and why the new one is not yet right

The brief that commissioned this plan projected a **~700-statement shortfall** and 71.23%. That rested on `2a-4 ≈ 61 statements`, which is `input/manager.py` alone from #236's body — **one file's delta presented as a whole PR's contribution.** 2a-6's baseline (2,863-2,874) measures a tree carrying 2a-2 **plus 2a-4**, against a 2a-2-only baseline of ~3,168: **2a-4 bought on the order of 300.** In the same direction, 2a-6's finished tests measure **2,183-2,232** against that baseline — a gain of **~630-690**, not the ~483 its two probe tests projected.

**But the corrected figures do not compose either.** Every delta above was measured on a different tree, and this stage has already measured what happens when two are added: **2a-3 and 2a-5 double-counted 84 statements when finally measured together — 25% of their naive sum.** Nobody has measured 2a-4 against 2a-6, or any three of the four together.

| Tree | `missing` | runs | caveat |
|---|---|---|---|
| 2a-2 only | 3,110-3,176 (median 3,168.5) | 8 | bimodal — two clusters ~56 apart |
| 2a-2 + **2a-3 + 2a-5** | **2,839** (median) | 8 | the only multi-PR figure measured directly |
| 2a-2 + **2a-4** | 2,863-2,874 | 3 | **three runs cannot see a bimodal step** |
| 2a-2 + 2a-4 + **2a-6** | 2,183-2,232 | ? | |

Building the band from the one n=8 multi-PR measurement and bracketing the two unmeasured increments by their disjoint-file floor and their standalone ceiling:

```
2a-2 + 2a-3 + 2a-5 (measured, sysmon, n=8, median)              2839

2a-4 incremental:  floor 135  (input/manager.py 61-72 + http_streamer.py 74
                               -- files no other 2a PR targets)
                   ceiling 300 (its full standalone gain)
2a-6 incremental:  floor 483  (the group's own files, set-diff verified)
                   ceiling 690 (its full measured gain)

optimistic  2839 - 300 - 690 =  1849   shortfall 254   coverage 76.8%
pessimistic 2839 - 135 - 483 =  2221   shortfall 626   coverage 72.2%
mid, applying 2a-3+2a-5's own 25% overlap precedent
            2839 - 0.75*(300+690) =  2096   shortfall 501   coverage 73.7%

gate allows (0.20 x 7978)                                       1595
```

**The band is 254 to 626 statements.** That straddles the boundary between "one more PR closes this" and "it does not close in this stage", which is exactly why no recommendation can responsibly be made from it. The mid estimate — the one that applies this stage's only measured overlap figure — sits at 501, above the boundary; but 2a-3 and 2a-5 both hammer `server.py` and `channel_service.py`, while 2a-4 and 2a-6 target `input/manager.py`, `http_streamer.py` and the fmp4/profile managers, so 25% may be too pessimistic here. That is an argument, and arguments have lost to measurement five times in this stage.

**The denominator is not in doubt.** 7,978, re-derived statically for this plan at `e62ab428` — `coverage.parser.PythonParser().statements` summed over the 38 non-test files `scripts/coverage_live_path.coveragerc`'s `[report] include` names. It is a property of the module list, independent of any run. The 80% allowance is **1,595 missing** (1,595 → 80.008%, 1,596 → 79.995%).

### The decision rule, committed before the measurement

Task 1 merges all four coverage branches onto one tree and measures it at n≥12 under sysmon. **The floor's value is `max(runs)`; the option is chosen by `max(runs)`.**

| Task 1's measured `missing` | Shortfall | Recommendation |
|---|---|---|
| **≤ 1,995** | ≤ 400 | **(b) — extend scope by ONE PR, `2a-8`.** Target the ~898-statement mid-sized pool no PR owns: `views.py`, `channel_status.py`, `client_manager.py`, `input/buffer.py`, `log_parsers.py`, `url_utils.py`. Set 2a-7's floor at the measured level anyway, so the ratchet exists while `2a-8` runs, and let `2a-8` raise it to ≤1,595. |
| **> 1,995** | > 400 | **(a) — ratchet at the achieved level, and reassign ≥80% to a new owned PR `2b-4`.** Do not lower the gate; move it, with an owner and a date. |

**Where 400 comes from, so the threshold is arguable rather than asserted.** 2a-3's five tests moved the gate by 139 statements — **~28 statements per test** on ordinary, non-fault-injection code. 400 ÷ 28 ≈ **15 tests**, which is one PR sized between 2a-3's five and 2a-5's thirty-five: proportionate. Above 400 you need 20-25 tests *plus* the `server.py` expensive tail (146 statements across ~28 `except Exception: logger.error(...)` arms needing faults injected into Redis, `emit_event` or the OS), which is two PRs with a falling yield per test.

**A correction to this plan's own earlier reasoning, recorded rather than quietly fixed.** An earlier revision argued against (b) on the grounds that "the marginal statement in the remaining pool is a fault-injected `except Exception` arm." **That was wrong.** It was computed from the supply table *minus* the ~898-statement mid-sized pool, which is ordinary code in six files that no PR owns and which 2a-3 demonstrated is cheap — 9 of the 40 statements it took from `client_manager.py` arrived as a side effect of a correctness fix. The expensive tail is what is left **after** that pool, not before it. That correction is most of the reason (b) is now on the table at all.

### What is NOT recommended, in either branch

**Do not change the denominator to reach the gate.** Measured for this plan at `e62ab428` (`PythonParser` plus an `ast` walk mapping statements to their enclosing `def`), the exclusion candidates are:

| Candidate | Statements | Verdict |
|---|---|---|
| `server.py::_cleanup_local_resources` | **62** | excludable (#230) — but see below, it is a live variance source |
| `server.py::_check_orphaned_channels` | **24** | excludable (#230, no callers anywhere) |
| `input/manager.py` dead cluster (#231) | **~62** (`_close_connection` 13, `_close_all_connections` 20, `_create_session` 7, ~2/3 of `stop`) | excludable |
| `fmp4/manager.py::_handle_bsf_error` | **35 — and NOT dead** | **reject.** Reached whenever ffmpeg's stderr carries `aac_adtstoasc ... is not supported by the bitstream filter` (`output/fmp4/manager.py:373`), which 2a-2's `PATH` stand-in can print on demand. The brief's "~9 dead statements" was wrong in both count and kind. |
| `input/http_streamer.py` | 101 | **void.** 73% covered since 2a-4 (#236: 101 → 27). The spec's bracket row "+ `http_streamer.py`'s 101" is **spent** — the fourth instance of the already-banked shape the spec names three of, and the first carried in a *conclusion* rather than a supply table. |

**~148 defensible statements, worth about 1.4 percentage points.** That cannot reach the gate in the pessimistic branch and is not needed in the optimistic one. Excluding merely-inconvenient code is the same hazard the rcfile's `[run] source`-not-`include` ruling exists to prevent, wearing a different coat. Leave the dead code in the denominator; the right disposal is **deletion**, which raises the floor for free and is in scope for `2a-8`/`2b-4`.

**And note `_cleanup_local_resources` is not merely dead — it is one of the four measured variance sources** (the isolation probe caught `server.py` 2489-2566 flipping between rounds). Excluding it would remove a flapping region from the measurement, which is the shape of a fix that improves the number by making the gate blind. Another reason not to.

### The decision the user owes: `apps/proxy/utils.py`

260 statements (measured for this plan; the brief's figure confirmed), 90 missed, currently outside the `[report] include` list — so work there earns nothing toward the gate. **D4 makes the live half of `get_user_active_connections` (`apps/proxy/utils.py:256`, `_live_connections`) part of the contract the Go relay reproduces.**

**Recommendation: defer it to `2a-8`/`2b-4`; do not add it in 2a-7.** This reverses an earlier revision of this plan, and the reversal has a reason worth stating rather than hiding:

- The earlier argument was that 2a-7 is the only moment where a denominator change invalidates no in-flight measurement. **That advantage is now void** — Task 1's merged-tree measurement becomes the new reference for everything downstream anyway, and whichever PR closes the shortfall re-measures from scratch.
- Adding it enlarges the denominator to **8,238** and the missing count by 90. The allowance rises to 1,647, so the **net effect is +38 statements of shortfall** — a cost paid at the exact moment the shortfall is the live question.
- The contract argument covers *part* of the file. Including a grab-bag module to capture `_live_connections` is imprecise; the sharper fix is to relocate that function and its helpers to a relay-boundary module in 2b, where boundary work is already in scope, and let it enter the denominator by relocation rather than by inclusion.

**This is the user's call, not the implementer's.** Task 9 implements inclusion and is a clean drop if the answer is "defer" (the recommendation) or "no".

---

## THE TOLERANCE RULING

### What is measured

- **The 64-statement teardown block is sequence-induced.** Block-complete 64/64 in **10/10 isolated rounds** (a fresh container, and so a fresh Redis, per label) against **5/11 shared-container runs**; Fisher exact two-tailed **p = 0.0124**. The PostgreSQL volume was shared across every round, so PG data state is excluded as a cause; a per-container process census found no stray ffmpeg and no leftovers, so "load or leftovers from the preceding label" is excluded too. What remains — the Redis process and the container's accumulated state — is **not separated, and this plan does not guess at it.**
- **Isolation does not make the total deterministic.** Isolated totals over ten rounds: `2841, 2837, 2834, 2834, 2831, 2831, 2827, 2825, 2797, 2797` — **spread 44**, against the shared shape's **47**. The spread barely moved. What changed is *which* region flaps: rounds 9-10 covered a **second, 28-line block** that rounds 1-8 all missed — `server.py` 2099-2112 (the cleanup loop's **non-owner** branch) and 2489-2566 (`_cleanup_local_resources`). Block one is the **owner's** coordinated stop; block two the **non-owner's** local cleanup. Same class of code, different path.
- **Three variance sources are known:** (1) `channel_service.py` 28-49 / 575-601 / 971-989 plus `server.py`'s owner-side teardown; (2) `server.py` 2099-2112 and 2489-2566, non-owner cleanup; (3) `input/manager.py`'s stderr-reader-thread join (:1739-1767).
- **`output/ts/generator.py` 227-230 is NOT a fourth source, and this plan said it was.** Corrected here rather than silently: `_wait_for_channel_ready`'s error/stopped/stopping branch is **missed in all 37 runs across five trees** — stable and permanent — **except on 2a-6's branch, where 2a-6's own tests introduce the flap.** It was reported to this plan as "missed in 2 of 3 runs on a tree whose PR does not touch that file", which read as a spontaneous fourth region and was written up as one. **Nothing may be sized against it.** But it is not irrelevant to 2a-7 either, and the reason is easy to miss: **the 2a-7 tree carries 2a-6's tests**, so this region is expected to flap there. Task 2 must classify it as *2a-6-introduced* rather than as a discovery, and the general-case variance list stays at three.
- **Machine load is an uncontrolled confound.** Isolated rounds 9-10 — the two that fired the second region — ran in the quietest window. Result 1 was protected by interleaving three shared runs in that same window (2847 at 64/64, 2866 at 45/64, 2829 at 64/64 — still flapping while isolated rounds were not), making it a paired comparison. **Result 2 is not load-controlled**, and whether the second region is load-driven or merely rare is unknown.

### The ruling

**The floor's `missing` is set from the WORST of at least twelve runs, and the gate carries no tolerance parameter.**

A ratchet asks one question: *is today's `missing` greater than the committed floor?* If the floor is a median, a tolerance must be bolted on to absorb the spread. If the floor **is** the worst observed run, the spread is already inside the number and the tolerance is redundant. The two have **identical exposure**, but the floor has one fewer knob and, decisively:

> **A tolerance is a number nobody re-derives. A floor is a number the monotonicity check already polices.** Widening a tolerance is a one-character edit in a script no CI check inspects. Widening a floor is an edit to a committed file that `--gate` refuses downward and that the CI wiring compares against `origin/main` in the same run.

**The evidence has strengthened this ruling since it was first drafted.** A fixed tolerance would have been sized at ~51 by the 2a-6 plan, at ≥66 by the shared-shape step, and at ~45 by the isolated shape — three numbers in three weeks, each correct for a shape or a tree that then changed. **And the region count itself moved twice while this plan was being written** — from one to two when the isolation probe's rounds 9-10 fired the non-owner cleanup, and from three back down again when `output/ts/generator.py` 227-230 turned out to be permanently missed rather than flapping. A number that has to be re-derived every time the tree moves is a number that will be stale in the file. A worst-run floor absorbs whatever the spread is on the day, without anyone having to name it.

This **contradicts the spec**, which says "2a-7's ratchet carries a small tolerance, and three constraints on it". All three constraints survive: (i) sized to the measured residual on the gated tree; (ii) justified by the per-file attribution Task 2 produces; (iii) a movement outside it — a run worse than the worst of twelve — is a finding. Task 8 records the contradiction and the argument in the spec.

**Cost, to be stated in the PR:** expect the worst-run floor to sit **~44-47 statements above the median**, ≈0.55pp of headroom given away. Say the measured number, not this estimate.

### Why twelve runs, and a stopping rule instead of a number

**At five isolated rounds the answer was clean and wrong.** Spread 10, block 5/5, and the conclusion "isolation fixes it". Rounds 9 and 10 inverted it by firing a region the first eight never touched. That is the second time in this session that more sampling on this suite did not *refine* a result but **reversed** it.

Ten was therefore also at the edge — a floor set from those ten runs would have been set from rounds 1-8's regime and broken the first time round 9's regime recurred. So the plan specifies a rule, not a count:

> **Run until the maximum has been unchanged for six consecutive runs, with a minimum of twelve runs.** If the maximum moves at run 12, keep going. Record every run, in order, in the PR description — the sequence is the evidence that the stopping rule was met, and a bare min/max cannot show it.

### The shape ruling

**Make the gate isolate per label — one label per container — on correctness grounds, and do not present it as a determinism fix.**

`backend-tests.yml` runs one label per matrix job in its own container; the gate should measure what CI measures, and the isolation probe measured that shape. It buys the block-level determinism above and **it does not buy total determinism**: 44 against 47. Task 6 implements it; Task 8 records both halves.

**The counter-argument, recorded so the choice is not one-sided:** a single job running the three labels in one container is self-consistent (the local script and the CI job would be byte-identical), simpler, and needs no artifact plumbing — and since the gate *is* the CI job, "measure what CI measures" is partly circular. It was rejected because per-container is the shape every measurement in this stage was taken under, and a floor should not be the first thing to introduce a new one.

---

## Global Constraints

Copied from `CLAUDE.md`, PR **#240** (open, unmerged — see below) and the spec. Every task's requirements implicitly include this section.

- **Container discipline.** This PR's implementer gets its own containers: base name `dispatcharr-testrunner-2a7` (Task 6's per-label shape needs three, suffixed `-proxy`, `-liveproxy`, `-channels`), `DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a7`, `DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest`. **Upstream's image (`ghcr.io/dispatcharr/dispatcharr:latest`, the script's default) carries neither `coverage` nor `hypothesis`** — the fork's image is not optional here.
- **Issue #241's mechanism is now known**: `start-test-container.sh`'s inner `docker exec -i … bash -s <<HEREDOC` contains a stdin-consuming `su` that eats the rest of the heredoc, so `ensure_app_database` never runs and the container comes up with no database while exiting 0. **Fixed on #238** (staged to a file, second `docker exec` without `-i`). **Until #238 merges, check for the database rather than assuming it** — Task 1 Step 4 checks. A container built from a script older than #238 also needs `docker exec <c> redis-cli CONFIG SET save ""`.
- **Three shell hazards are in PR #240, which is OPEN AND UNMERGED.** They are not in `CLAUDE.md` on `main` at `e62ab428`. Cite #240 as pending if you cite them; do not write as though `CLAUDE.md` documents them. The three:
  - **zsh applies history-style modifiers to a bare parameter expansion**, so `git show "$b:scripts/x.sh"` has the `:s…` parsed as a substitute modifier and consumed — git receives the bare ref and prints **the tip commit's diff**, exiting 0 with plausible output. **Brace it: `git show "${b}:path"`.** Harmless in bash, so a `bash -c` wrapper can behave while the interactive shell does not.
  - **Never `2>/dev/null` a git query whose emptiness you intend to interpret, and never read `$?` through a pipe.** `git log … 2>/dev/null` exits 128 on a nonexistent ref; `git log … 2>/dev/null | cat` exits 0, because `$?` after a pipeline is the last stage's status. **Use `set -o pipefail`** — measured at 128 in both zsh and bash. Do **not** reach for `${PIPESTATUS[0]}`: that is a bash name, expands to the empty string in zsh (falsy, reads as success), zsh's is `${pipestatus[1]}`, and either array is clobbered by the very next pipeline including an `echo`.
  - **A clean worktree is not an unoccupied one.** Every plan in this programme opens with a measurement task that writes no files, so an agent faithfully executing task one is invisible to `git status` for its whole first task. Check `docker ps --filter name=<the-container-from-task-1>`.
- **Never** pass `--settings=dispatcharr.settings` to `manage.py test`.
- **Stage and commit in separate Bash calls.** The `PreToolUse` hook on `Bash(git commit*)` runs before the command, so one call doing both is blocked. It matches on command text, so write commit messages to a file with the Write tool and use `git commit -F <file>`.
- `gh` **always** with `--repo D10Scot/Dispatcharr`.
- **Two tiers of running.** A test *reaching* a branch is settled by an `INFO` grep. A test *pinning* a behaviour needs a **break check**: patch the production behaviour, confirm the patch applied with `sed -n` on the patched lines, watch it go red, revert, watch it go green. **One red is not a break check** — a shipped assertion in this stage went red 1 run in 5; require **three consecutive reds**. A break lever must break the *mechanism*, not select a second documented behaviour.
- **A change made for readability is still a change to the mechanism.** Any edit to an existing test — a docstring included — re-runs that test's break check.
- **No wall-clock assertion may be a pin.** The harness's upstream is paced, but the relay reads ahead into Redis and the generator serves from there, so a client's read is served at memory speed regardless.
- Every predicted failure string in this plan is marked **PREDICTED, NOT OBSERVED**. Quote what you actually saw.
- `COVERAGE_CORE=sysmon` throughout; the script exports it. A C-tracer figure is not comparable with a sysmon one **in either direction**, and #236 and #237 quote C-tracer figures for exactly that reason.
- **A failed label invalidates a measurement rather than degrading it.** A tree missing `hypothesis` reported 3,230 where the same tree with it reported 3,169 — a 61-statement inflation moving the way a regression moves. Discard any run announcing `label(s) failed under coverage:`; never record it.
- **zizmor is a zero-findings ratchet.** `.github/workflows/backend-tests.yml` is edited here; every finding in that file blocks. `persist-credentials: false` on every `actions/checkout`; every `uses:` a full 40-character SHA with the version as a trailing comment, resolved with `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`, never hand-typed.
- **Machine load affects these measurements.** Note what else was running (`docker ps`) beside each recorded run. An unattributed number taken in a busy window is not evidence.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `scripts/coverage_live_path.floor` | The committed ratchet. `shape`, `statements`, `missing`, `percent`, `measured`, `runs`. `shape` and `statements` are **equality** checks; **`missing` is the ratchet** — a maximum, not a target. The percentage is derived and informational; the spec's Gate 2 section records that percentages are what hid the error it exists to correct. |
| `scripts/coverage_live_path_isolated.sh` | Host-side driver: one container per label, `--label` in each, collect the data directories, `--report`/`--gate` over the union. Lets a developer reproduce the CI number locally, which the in-container script cannot do by itself. |
| `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py` | Row 30's pin. |

**Modified**

| Path | Change |
|---|---|
| `scripts/coverage_live_path.sh` | `--gate`, `--write-floor`, `--combine-from <dir>`; `SHAPE_ID` → `per-container/v1-${COVERAGE_CORE}`. Existing shape guard, tracer export and failed-label announcement untouched. |
| `.github/workflows/backend-tests.yml` | A three-way `coverage-label` matrix, a `coverage-gate` combine job, and `Backend result` extended to require the latter. |
| `docs/relay-parity-matrix.md` | Rows 29 and 30, both pinned. |
| `e2e/tests/guards/parity-matrix.ts` | `HIGHEST_ROW_ID` 28 → 30. |
| `apps/proxy/live_proxy/tests/test_manager_connection_failover.py` | Docstring only; re-break-checked. |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | Gate 2 amendment; `2a-8` **or** `2b-4` added to the PR table per Task 1's rule. |
| `CLAUDE.md` | § Testing gains the gate, its floor, the shape and how to run it. |
| `metrics/curated/*` | Milestone + ledger updates. |

**Untouched, deliberately:** `scripts/coverage_live_path.coveragerc`, unless Task 9 runs.

---

## Task 1: Build the merged tree and take THE measurement

**This is the task the recommendation depends on.** Every projection in § THE GATE DECISION is arithmetic over incommensurable trees; this task replaces all of it with one number.

**Files:** none modified in the repo beyond the merge itself.

**Interfaces:**
- Produces: the 2a-7 base tree (2a-2 + 2a-3 + 2a-4 + 2a-5 + 2a-6); `runs[]` at n≥12 under the isolated shape; `max(runs)` — the floor's value and the input to the decision rule.

- [ ] **Step 1: Build the tree**

All four coverage branches stack on 2a-2 (#229); 2a-6 stacks on 2a-4. Merge them onto this branch in dependency order:

```bash
cd /Users/dion/git/Dispatcharr
git worktree add .worktrees/phase2-2a7 migration/phase2a-coverage-gate
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a7
set -o pipefail
git merge --no-ff migration/phase2a-subprocess-harness
git merge --no-ff migration/phase2a-ts-generator-coverage
git merge --no-ff migration/phase2a-manager-coverage
git merge --no-ff migration/phase2a-server-and-authorize-coverage
git merge --no-ff migration/phase2a-fmp4-coverage
```

**Expect conflicts in exactly two files**, both of which every coverage PR edits: `docs/relay-parity-matrix.md` (each PR deletes its own `owed:` markers) and `e2e/tests/guards/parity-matrix.ts` (`HIGHEST_ROW_ID`). Resolve by **union** — keep every PR's deletions, and take the highest `HIGHEST_ROW_ID`. The test files themselves are disjoint and must not conflict; **if a test file conflicts, stop** — two PRs wrote the same module and that is a finding to report before continuing.

- [ ] **Step 2: Prove the merge is complete rather than merely clean**

```bash
set -o pipefail
grep -o "owed: [0-9a-z-]*" docs/relay-parity-matrix.md | sort | uniq -c
grep -n "HIGHEST_ROW_ID" e2e/tests/guards/parity-matrix.ts
ls apps/proxy/live_proxy/tests/ | wc -l
```

Expected: **exactly one owed marker, `owed: 2b-3`** (plus the legend's empty `owed: ` example, which is not a row); `HIGHEST_ROW_ID = 28`; and the test directory carrying every module from all four PRs. A surviving `owed: 2a-N` marker means a merge dropped an edit — find it before measuring.

- [ ] **Step 3: Start three containers, one per label**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a7
for suffix in proxy liveproxy channels; do
  DISPATCHARR_TEST_CONTAINER="dispatcharr-testrunner-2a7-$suffix" \
  DISPATCHARR_TEST_DB_VOLUME="dispatcharr-hookdb-2a7-$suffix" \
  DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest \
  CLAUDE_HOOK_REPO_ROOT="$PWD" \
    bash .claude/hooks/start-test-container.sh
done
```

- [ ] **Step 4: Check each container for the three things that come up silently broken**

Until #238 merges, a container can exit 0 with no database (#241) and Redis can be refusing every write (#238).

```bash
set -o pipefail
for suffix in proxy liveproxy channels; do
  C="dispatcharr-testrunner-2a7-$suffix"
  echo "== $C"
  docker exec "$C" bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; \
    psql -h /var/run/postgresql -U dispatch -l' | grep -c dispatcharr
  docker exec "$C" redis-cli CONFIG SET save ""
  docker exec "$C" redis-cli SET __probe__ 1
  docker exec "$C" bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; \
    python -c "import coverage, hypothesis; print(coverage.__version__, hypothesis.__version__)"'
done
```

Expected per container: a count ≥ 1, `OK` twice, and two version strings. **A count of 0 means the container is unusable** — re-run Step 3 and read the script's output, not its exit code.

- [ ] **Step 5: One isolated round, to establish the denominator**

```bash
set -o pipefail
rm -rf /tmp/2a7-cov && mkdir -p /tmp/2a7-cov
run_round() {
  local out="$1"; rm -rf "$out"; mkdir -p "$out"
  local pairs=("proxy:apps.proxy.tests" "liveproxy:apps.proxy.live_proxy.tests" "channels:apps.channels.tests")
  for p in "${pairs[@]}"; do
    local suffix="${p%%:*}" label="${p#*:}"
    local C="dispatcharr-testrunner-2a7-$suffix"
    docker exec "$C" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; cd /repo && \
      rm -rf /tmp/rd && COVERAGE_LIVE_PATH_DATA_DIR=/tmp/rd \
      bash scripts/coverage_live_path.sh --label $label" >/dev/null 2>&1 || return 1
    docker cp "$C":/tmp/rd "$out/$suffix" || return 1
  done
}
run_round /tmp/2a7-cov/round-0 && echo "round 0 ok"
```

Then combine and report inside any one container (Task 5 ships `--combine-from`; until then, copy the `.coverage.*` and `*.shape` files into one directory and run `--report`). Expected on the last line:

```
coverage_live_path: statements 7978  missing NNNN  coverage NN.NN%
```

**7,978 is the check.** A different denominator means the module list moved and every figure below it is against a different gate.

- [ ] **Step 6: Run the stopping rule**

Repeat Step 5's round until **the maximum `missing` has been unchanged for six consecutive rounds, minimum twelve rounds.** Record every round in order, with the `docker ps` output beside it. Discard and re-take any round announcing a failed label.

**Do not stop at ten because ten is a round number.** The isolation probe's rounds 9 and 10 fired a region rounds 1-8 never touched and inverted its own conclusion; a floor set from those first eight would have broken the first time that region recurred.

- [ ] **Step 7: Apply the decision rule and report**

```
max(runs) <= 1995  ->  recommend (b): one added PR, 2a-8, against the ~898-statement
                       mid-sized pool; 2a-7 still sets a floor at the measured level.
max(runs) >  1995  ->  recommend (a): ratchet at the measured level, reassign >=80% to 2b-4.
```

**Report the number and the verdict to the orchestrator before proceeding past Task 2.** The rule was committed in advance precisely so this step is arithmetic rather than judgement — do not re-argue it after seeing the number. If the measurement lands within ±20 of 1,995, say so plainly and ask; that is inside the measured spread and the rule cannot separate the options there.

- [ ] **Step 8: Commit the merge**

---

## Task 2: Attribute the variance, per file and per line

The spec requires the floor be "justified by per-file attribution, not picked". Three variance regions are known, plus one that 2a-6's own tests introduce; this task's job is to say which move on **this** tree and whether a genuinely new one has appeared.

**Files:** none modified.

**Interfaces:**
- Consumes: Task 1's rounds and their `live-path.json` files.
- Produces: the attribution table the PR description carries.

- [ ] **Step 1: Diff the best and worst rounds, per file and then per line**

```bash
python3 - <<'PY'
import json, glob, os
runs = {}
for d in sorted(glob.glob('/tmp/2a7-cov/round-*')):
    p = os.path.join(d, 'live-path.json')
    if os.path.exists(p):
        runs[d] = json.load(open(p))
tot = {k: v['totals']['missing_lines'] for k, v in runs.items()}
for k in sorted(tot, key=tot.get):
    print(f'{tot[k]:6d}  {k}')
best, worst = min(tot, key=tot.get), max(tot, key=tot.get)
print(f'\nspread {tot[worst]-tot[best]}  best {tot[best]}  worst {tot[worst]}\n')
for f in sorted(runs[best]['files']):
    a = runs[best]['files'][f]['summary']['missing_lines']
    b = runs[worst]['files'][f]['summary']['missing_lines']
    if a != b:
        sa = set(runs[best]['files'][f]['missing_lines'])
        sb = set(runs[worst]['files'][f]['missing_lines'])
        print(f'{b-a:+5d}  {f}')
        print('        only-missed-in-worst:', sorted(sb - sa))
        print('        only-missed-in-best :', sorted(sa - sb))
PY
```

Each round's `live-path.json` is written by `report()` into `$COVERAGE_LIVE_PATH_DATA_DIR`; copy it out beside each round's data in Task 1 Step 5 if it is not there already.

- [ ] **Step 2: Classify every moving region**

| # | Region | Path | Status |
|---|---|---|---|
| 1 | `channel_service.py` 28-49, 575-601, 971-989 + `server.py` 252, 261, 359-426, 888, 1259-1260, 1802-1803, 2010-2042 | owner-side coordinated stop | general — sequence-induced, and this shape suppresses it |
| 2 | `server.py` 2099-2112, 2489-2566 | non-owner local cleanup | general — fired in isolated rounds 9-10 only |
| 3 | `input/manager.py` 1739-1767 | stderr-reader-thread join | general |
| — | `output/ts/generator.py` 227-230 | `_wait_for_channel_ready`'s error/stopped/stopping branch | **NOT a general region.** Missed in all 37 runs across five trees; it flaps **only** on trees carrying 2a-6's tests, which this one does. Expect it, classify it as 2a-6-introduced, and size nothing against it. |

**Anything outside this table is a new finding — report it before writing a floor.** Note what the table's own history establishes: region 2 appeared at isolated round 9 after eight rounds had suggested a clean answer, and the `generator.py` row was written into an earlier revision of this plan as a fourth general region on a 2-of-3-run report before a 37-run count across five trees showed it was permanently missed instead. **Both directions of that error argue the same thing: a fixed tolerance sized on any snapshot of this table would have been wrong.**

- [ ] **Step 3: Record the attribution table** in the scratchpad; it goes into the PR description verbatim.

---

## Task 3: Parity-matrix row 29 — the buffering detector is inert on Proxy and Redirect

An obligation **inherited from 2a-4**, which found the behaviour, wrote a test asserting it, and recorded that the row was 2a-7's to add because bumping `HIGHEST_ROW_ID` against several in-flight PRs was not its to do. Named as inherited, not absorbed.

**Files:**
- Modify: `docs/relay-parity-matrix.md` (row 29)
- Modify: `e2e/tests/guards/parity-matrix.ts` (`HIGHEST_ROW_ID` 28 → 29)
- Modify: `apps/proxy/live_proxy/tests/test_manager_connection_failover.py` (docstring only)

**Interfaces:**
- Consumes: `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::ConnectionFailoverTests::test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats`, which sets `buffering_speed` to the API maximum and asserts `ffmpeg_speed` never appears, `state` never becomes `buffering`, and no `channel_buffering` event is written.
- Produces: row 29 pinned; `HIGHEST_ROW_ID = 29`.

- [ ] **Step 1: Break-check the existing test BEFORE citing it**

The lever must break the *mechanism* — make a Proxy-profile channel report an ffmpeg speed. In `apps/proxy/live_proxy/input/manager.py`, find the successful-connect path of `_establish_http_connection` and insert as the last statement of the success branch:

```python
        self._update_ffmpeg_stats_in_redis(0.5, None, None, None)  # BREAK CHECK
```

- [ ] **Step 2: Confirm the break applied**

```bash
set -o pipefail
sed -n "$(grep -n 'BREAK CHECK' apps/proxy/live_proxy/input/manager.py | cut -d: -f1),+1p" \
  apps/proxy/live_proxy/input/manager.py
```

Expected: the inserted line printed back. **A break check that prints nothing here is not a break check** — a green run after an unapplied patch was nearly reported as "cannot reproduce" earlier in this stage.

- [ ] **Step 3: Three runs, all red**

```bash
docker exec dispatcharr-testrunner-2a7-liveproxy bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  for i in 1 2 3; do python manage.py test --keepdb \
  apps.proxy.live_proxy.tests.test_manager_connection_failover.ConnectionFailoverTests.test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats 2>&1 | tail -4; done'
```

**PREDICTED, NOT OBSERVED:**

```
AssertionError: 'ffmpeg_speed' unexpectedly found in {...} : the Proxy profile reported an ffmpeg speed; there is no ffmpeg
```

Quote what you actually see. If fewer than three of three go red, do not cite the test — strengthen its assertion and break-check that instead.

- [ ] **Step 4: Revert and confirm green**

```bash
set -o pipefail
git checkout -- apps/proxy/live_proxy/input/manager.py
grep -c "BREAK CHECK" apps/proxy/live_proxy/input/manager.py   # expect 0
```

Re-run the test once; expect `OK`.

- [ ] **Step 5: Add row 29**

Append immediately before `<!-- end of matrix -->`, matching the surrounding rows' exact column shape:

```markdown
| 29 | The buffering failover detector is ffmpeg-exclusive: on the Proxy and Redirect Stream Profiles `buffering_speed` and `buffering_timeout` are read and then never consulted — no `ffmpeg_speed` is ever written, `state` never becomes `buffering`, and no `channel_buffering` event is raised, however far below the threshold the upstream runs | `apps/proxy/live_proxy/input/manager.py:1092` (`_update_ffmpeg_stats_in_redis` is called only from `_parse_ffmpeg_stats`), `apps/proxy/live_proxy/input/manager.py:1122` (the buffering comparison, in the same function), reached only from the stderr reader a transcode profile has | `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::ConnectionFailoverTests::test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats` | Found by 2a-4, which wrote the test and recorded that the row was 2a-7's to add; inherited here rather than absorbed. Externally observable — an operator who raises `buffering_speed` on a Proxy channel gets no failover and no indication the setting did nothing, and nothing in the UI says so. D5 is strict parity, so the Go relay reproduces the inertness. |
```

Verify the `Source` line numbers resolve against the merged tree before committing; they drift, and the guard checks each citation.

- [ ] **Step 6: Raise `HIGHEST_ROW_ID` to 29**

In `e2e/tests/guards/parity-matrix.ts`, `export const HIGHEST_ROW_ID = 29;`. If the merge left it at 27, Task 1's union resolution dropped an edit — go back.

- [ ] **Step 7: Update the cited test's docstring**

Replace `Closes no matrix row, and is here for two reasons.` with:

```
        Pins matrix row 29 (added by 2a-7), and is here for two reasons.
```

- [ ] **Step 8: A readability edit is still an edit — repeat Steps 1-4 exactly.** Three reds, revert, green. The rule exists because a cosmetic fix to a failure message inverted a pin earlier in this stage and was caught only by re-breaking it.

- [ ] **Step 9: Run the guard**

```bash
cd e2e && npx playwright test tests/guards/parity-matrix.spec.ts --reporter=list 2>&1 | tail -20
```

Expected: seven passes and `29 rows — <n> pinned, 1 owed, 2 white-box-only`.

- [ ] **Step 10: Commit** (stage and commit in separate calls; message via `-F`)

---

## Task 4: Parity-matrix row 30 — a rejected credential 401s, a declined one falls through

The second inherited obligation. 2a-5 documented `_drf_user`'s two-way disposition in a test docstring as a porting hazard, but no row and no test pin it. **A hazard recorded in a docstring is not pinned**: a port flattening both cases to "anonymous" turns a rejected credential into a successful anonymous tune of any ordinary channel, and nothing in the suite goes red.

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py`
- Modify: `docs/relay-parity-matrix.md` (row 30)
- Modify: `e2e/tests/guards/parity-matrix.ts` (`HIGHEST_ROW_ID` 29 → 30)

**Interfaces:**
- Consumes: `apps/proxy/authorize.py:251-265` (`_drf_user`) — `except AuthenticationFailed: raise AuthorizeDenied(401, "Invalid credentials")` versus `except APIException: return None` and the no-match fall-through. Authenticator set at `apps/proxy/authorize.py:93-97`: `(JWTAuthentication, ApiKeyAuthentication, QueryParamJWTAuthentication)`.
- Consumes: the harness base class the sibling PRs use. **Read `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py` (2a-5) and copy its import header and request idiom** rather than inventing one; that module already drives `/proxy/ts/stream/<uuid>` over HTTP with headers.
- Produces: row 30 pinned; `HIGHEST_ROW_ID = 30`.

- [ ] **Step 1: Write the test**

```python
"""Row 30: a credential an authenticator REJECTS is 401; one it DECLINES is anonymous.

`_drf_user` (apps/proxy/authorize.py:251-265) has two exits that a porter reads as
one. `AuthenticationFailed` -- raised by JWTAuthentication for a malformed or
unverifiable Bearer token, and by ApiKeyAuthentication for an unknown key --
becomes AuthorizeDenied(401). Every other outcome, including "no credential was
presented at all", returns None and the caller falls through to the anonymous
principal, which is still allowed to stream an ordinary channel by UUID.

A Go port that flattens both to "anonymous" fails no other test in this suite, and
the failure it introduces is silent: a request carrying a credential the control
plane rejected streams anyway.

The two requests below differ in exactly one thing -- whether an Authorization
header is present -- and they must get different answers.
"""


class CredentialDispositionTests(RelayHarnessTestCase):
    def test_a_rejected_bearer_token_is_refused_with_401(self):
        channel = self.make_channel(upstream_url=self.upstream.url)
        response = self.client.get(
            f"/proxy/ts/stream/{channel.uuid}",
            HTTP_AUTHORIZATION="Bearer not.a.jwt",
        )
        self.assertEqual(
            response.status_code,
            401,
            "a credential the JWT authenticator rejected did not 401; if this is "
            "200 the request streamed as anonymous, which is the flattening row 30 "
            "exists to catch",
        )

    def test_no_credential_at_all_streams_as_anonymous(self):
        channel = self.make_channel(upstream_url=self.upstream.url)
        with self.tuned(channel) as stream:
            served = stream.read(20 * TS_PACKET_SIZE)
        self.assertTrue(
            served,
            "an anonymous tune of an ordinary channel served no bytes; the "
            "declined-credential half of row 30 is the one that must NOT 401",
        )
```

Import `TS_PACKET_SIZE` and `RelayHarnessTestCase` from wherever `test_manager_connection_failover.py` imports them; do not re-declare either.

- [ ] **Step 2: Run it and watch it pass**

```bash
docker exec dispatcharr-testrunner-2a7-liveproxy bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  python manage.py test --keepdb \
  apps.proxy.live_proxy.tests.test_authorize_credential_disposition -v2 2>&1 | tail -15'
```

Expected: `OK` for both. This is a characterization test of existing behaviour, so passing first time is correct — which is exactly why Step 3 is not optional.

- [ ] **Step 3: Break check — flatten the rejection**

In `apps/proxy/authorize.py`, change

```python
    except AuthenticationFailed:
        raise AuthorizeDenied(401, "Invalid credentials") from None
```

to

```python
    except AuthenticationFailed:
        return None  # BREAK CHECK
```

- [ ] **Step 4: Confirm the break applied**

```bash
set -o pipefail
sed -n "$(grep -n 'BREAK CHECK' apps/proxy/authorize.py | cut -d: -f1),+1p" apps/proxy/authorize.py
```

Expected: the `return None  # BREAK CHECK` line printed back.

- [ ] **Step 5: Three consecutive runs, all red**

```bash
docker exec dispatcharr-testrunner-2a7-liveproxy bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  for i in 1 2 3; do python manage.py test --keepdb \
  apps.proxy.live_proxy.tests.test_authorize_credential_disposition.CredentialDispositionTests.test_a_rejected_bearer_token_is_refused_with_401 \
  2>&1 | tail -5; done'
```

**PREDICTED, NOT OBSERVED:**

```
AssertionError: 200 != 401 : a credential the JWT authenticator rejected did not 401; ...
```

Quote the real text. If the observed status is neither 200 nor 401 — a 403, say — the flattening reaches a different refusal; reword the message to match what actually happens and repeat from Step 3.

- [ ] **Step 6: Revert and confirm green**

```bash
set -o pipefail
git checkout -- apps/proxy/authorize.py
grep -c "BREAK CHECK" apps/proxy/authorize.py   # expect 0
```

Re-run both tests; expect `OK`.

- [ ] **Step 7: Add row 30**

Immediately before `<!-- end of matrix -->`:

```markdown
| 30 | A credential an authenticator explicitly REJECTS (a malformed Bearer JWT, an unknown API key) is refused 401; a credential merely DECLINED — no header presented at all — falls through to the anonymous principal, which still streams an ordinary channel by UUID | `apps/proxy/authorize.py:258-259` (`except AuthenticationFailed: raise AuthorizeDenied(401, ...)`) vs `apps/proxy/authorize.py:260-265` (`except APIException: return None`, and the no-match fall-through), over the authenticator set at `apps/proxy/authorize.py:93-97` | `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py::CredentialDispositionTests::test_a_rejected_bearer_token_is_refused_with_401`, `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py::CredentialDispositionTests::test_no_credential_at_all_streams_as_anonymous` | Found by 2a-5, recorded as a porting hazard in a docstring only; inherited by 2a-7 and pinned here. A port that flattens both exits to "anonymous" fails no other test in the suite, and the failure it introduces is silent — a request carrying a credential the control plane rejected streams anyway. |
```

Verify the line numbers resolve before committing.

- [ ] **Step 8: Raise `HIGHEST_ROW_ID` to 30 and run the guard**

```bash
cd e2e && npx playwright test tests/guards/parity-matrix.spec.ts --reporter=list 2>&1 | tail -20
```

Expected: seven passes and `30 rows — 29 pinned, 1 owed, 2 white-box-only`.

**Note on the guard's PR vocabulary:** `PRS` in `e2e/tests/guards/parity-matrix.ts:396` is `['2a-3','2a-4','2a-5','2a-6','2b-3']` — **`2a-7` is not in it.** Both new rows are pinned with real test references, so no `owed:` marker is needed and `PRS` does not change. **If Task 8 adds `2a-8` or `2b-4` to the spec and any matrix row ever carries `owed: 2a-8`/`owed: 2b-4`, `PRS` must gain it in the same diff** or the guard fails the pin check, listing the legal ids.

- [ ] **Step 9: Run the whole package**

```bash
docker exec dispatcharr-testrunner-2a7-liveproxy bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  python manage.py test --keepdb apps.proxy.live_proxy.tests 2>&1 | tail -5'
```

Expected: `OK`, with the test count two higher than before this task.

- [ ] **Step 10: Commit**

---

## Task 5: `--gate`, `--write-floor` and `--combine-from` in `scripts/coverage_live_path.sh`, plus the isolated driver

**Files:**
- Modify: `scripts/coverage_live_path.sh`
- Create: `scripts/coverage_live_path_isolated.sh`
- Create: `scripts/coverage_live_path.floor` (placeholder here; Task 7 writes the real one)

**Interfaces:**
- Consumes: the script's existing `report()` (prints `coverage_live_path: statements N  missing M  coverage P%`, writes `$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json`), `run_label()`, and `SHAPE_ID`.
- Produces: `--gate` (exit 0 pass, 1 fail), `--write-floor`, `--combine-from <dir>`; the floor file's six-key format, used by Task 6's CI job and Task 8's docs.

- [ ] **Step 1: Bump the shape**

```bash
SHAPE_ID="per-container/v1-${COVERAGE_CORE}"
```

Extend the comment above it: the gate now runs one label per container, matching `backend-tests.yml`'s matrix and the shape the isolation probe measured. **A floor written under `per-label/v2` must be refused rather than compared** — that is what the shape guard is for, and this is the first time it earns its keep.

- [ ] **Step 2: Add `--combine-from`**

```bash
combine_from() {
  local src="$1"
  [ -d "$src" ] || { echo "coverage_live_path: no such directory: $src" >&2; return 1; }
  rm -rf "$COVERAGE_LIVE_PATH_DATA_DIR"; mkdir -p "$SHAPE_DIR"
  # Each per-label run produced its own data dir with a .coverage.* file and a
  # matching .shape stamp. Copying both preserves the existing stamp check across
  # the container boundary: report() still refuses data it cannot account for.
  find "$src" -name '.coverage.*' -exec cp {} "$COVERAGE_LIVE_PATH_DATA_DIR/" \;
  find "$src" -name '*.shape'     -exec cp {} "$SHAPE_DIR/" \;
}
```

- [ ] **Step 3: Create the floor file with the format and a placeholder**

`scripts/coverage_live_path.floor`:

```
# Gate 2's ratchet floor. See docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
# (Stage 2a > Gate 2) and docs/superpowers/plans/2026-09-10-phase2-2a7-coverage-gate.md.
#
# `missing` is the ratchet -- a MAXIMUM, not a target, and lower is better. It is set
# from the WORST run of at least twelve on the tree that earned it, which is why this
# gate carries no separate tolerance parameter: the measured spread is already inside
# the number. Four regions are known to flap (owner-side coordinated stop, non-owner
# local cleanup, the stderr-reader join, _wait_for_channel_ready's error branch) and
# the list has grown twice; a fixed tolerance would be stale on arrival.
#
# `shape` and `statements` are EQUALITY checks, not comparisons. A different measurement
# shape or module list makes two numbers incomparable rather than better or worse, and
# the gate says so instead of ratcheting.
#
# Written by:  scripts/coverage_live_path.sh --write-floor
# Enforced by: scripts/coverage_live_path.sh --gate  (backend-tests.yml, job coverage-gate)
shape=per-container/v1-sysmon
statements=7978
missing=99999
percent=0.00
measured=PLACEHOLDER
runs=0
```

- [ ] **Step 4: Add `--gate` and `--write-floor`**

```bash
FLOOR_FILE="$REPO_ROOT/scripts/coverage_live_path.floor"

# Reads the figures report() just wrote, rather than re-deriving them, so --gate and
# --write-floor can never drift from what a bare run prints.
read_totals() {
  python - "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" <<'PY'
import json, sys
t = json.load(open(sys.argv[1]))["totals"]
print(t["num_statements"], t["missing_lines"], f'{t["percent_covered"]:.2f}')
PY
}

floor_value() { grep -E "^$1=" "$FLOOR_FILE" | head -1 | cut -d= -f2-; }

gate() {
  local stmts missing pct f_shape f_stmts f_missing
  read -r stmts missing pct < <(read_totals) || return 1
  f_shape="$(floor_value shape)"; f_stmts="$(floor_value statements)"
  f_missing="$(floor_value missing)"

  if [ "$f_shape" != "$SHAPE_ID" ]; then
    echo "coverage_live_path: floor was written under shape '$f_shape'; this run is '$SHAPE_ID'." >&2
    echo "coverage_live_path: these are not comparable. Re-baseline deliberately with --write-floor." >&2
    return 1
  fi
  if [ "$f_stmts" != "$stmts" ]; then
    echo "coverage_live_path: the denominator moved: floor $f_stmts, this run $stmts." >&2
    echo "coverage_live_path: the module list in scripts/coverage_live_path.coveragerc changed." >&2
    echo "coverage_live_path: that is a finding, not a regression. Re-baseline with --write-floor" >&2
    echo "coverage_live_path: and say in the PR why the module list moved." >&2
    return 1
  fi
  echo "coverage_live_path: floor missing=$f_missing  this run missing=$missing  coverage ${pct}%"
  if [ "$missing" -gt "$f_missing" ]; then
    echo "coverage_live_path: GATE FAILED -- $(( missing - f_missing )) more missed statements than the floor." >&2
    echo "coverage_live_path: the floor is the worst of >=12 runs on the tree that set it, so this is" >&2
    echo "coverage_live_path: outside the measured spread: a finding to investigate, not noise." >&2
    echo "coverage_live_path: attribute it per FILE and then per LINE before widening anything --" >&2
    echo "coverage_live_path: diff live-path.json's per-file missing_lines, do not difference totals." >&2
    return 1
  fi
  if [ "$missing" -lt "$f_missing" ]; then
    echo "coverage_live_path: $(( f_missing - missing )) FEWER missed than the floor. The floor is not"
    echo "coverage_live_path: lowered automatically -- run --write-floor in the PR that earned it."
  fi
  return 0
}

write_floor() {
  local stmts missing pct old
  read -r stmts missing pct < <(read_totals) || return 1
  old="$(floor_value missing)"
  if [ "$missing" -gt "$old" ] && [ "${COVERAGE_LIVE_PATH_ALLOW_REGRESSION:-}" != "1" ]; then
    echo "coverage_live_path: refusing to write a WORSE floor ($old -> $missing)." >&2
    echo "coverage_live_path: a floor may rise only in the PR that earns and explains the rise, and" >&2
    echo "coverage_live_path: may never simply be edited down. If this is a deliberate re-baseline" >&2
    echo "coverage_live_path: (the module list moved, or the shape changed), set" >&2
    echo "coverage_live_path: COVERAGE_LIVE_PATH_ALLOW_REGRESSION=1 and say why in the PR." >&2
    return 1
  fi
  python - "$FLOOR_FILE" "$SHAPE_ID" "$stmts" "$missing" "$pct" "${COVERAGE_LIVE_PATH_RUNS:-0}" <<'PY'
import re, sys, datetime
path, shape, stmts, missing, pct, runs = sys.argv[1:7]
src = open(path).read()
for k, v in (("shape", shape), ("statements", stmts), ("missing", missing),
             ("percent", pct), ("measured", datetime.date.today().isoformat()),
             ("runs", runs)):
    src = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", src)
open(path, "w").write(src)
print(f"coverage_live_path: floor written -- statements {stmts} missing {missing} coverage {pct}%")
PY
}
```

New `case` branches, each taking an optional data directory so they work over `--combine-from`:

```bash
  --gate|--write-floor)
    mode="$1"
    if [ $# -eq 2 ]; then combine_from "$2" || exit 1; fi
    report >/dev/null || exit 1
    if [ "$mode" = "--gate" ]; then gate; else write_floor; fi
    exit $?
    ;;
```

Update the `usage:` string to `[--label <label> | --report | --combine-from <dir> | --gate [dir] | --write-floor [dir]]`.

**Note the failed-label policy.** `report()` already refuses data it did not stamp. `--gate` and `--write-floor` must additionally never produce a verdict over a partial combine: **a gate that passes on an under-run suite is worse than a gate that errors.** The stamp count check in `report()` gives this for free — three labels means three stamps and three data files.

- [ ] **Step 5: Create `scripts/coverage_live_path_isolated.sh`**

The host-side driver that reproduces CI's shape locally. It must not run inside a container — it creates them.

```bash
#!/usr/bin/env bash
# Reproduce the CI coverage gate locally: one container per Django test label, the
# shape backend-tests.yml's matrix uses and the shape the isolation probe measured.
#
# The in-container script cannot do this by itself -- it runs INSIDE one container --
# so the per-label split lives here and the combine lives back in the script, over
# --combine-from, which preserves the shape-stamp check across the boundary.
#
# The block-level determinism this shape buys is real (64/64 in 10/10 isolated rounds
# against 5/11 shared, p=0.0124) and the TOTAL determinism it buys is NOT: spread 44
# isolated against 47 shared. Do not read this script as a variance fix.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${COVERAGE_ISOLATED_OUT:-/tmp/dispatcharr-coverage-isolated}"
PREFIX="${COVERAGE_ISOLATED_PREFIX:-dispatcharr-testrunner-2a7}"

declare -a PAIRS=(
  "proxy:apps.proxy.tests"
  "liveproxy:apps.proxy.live_proxy.tests"
  "channels:apps.channels.tests"
)

rm -rf "$OUT"; mkdir -p "$OUT"
for pair in "${PAIRS[@]}"; do
  suffix="${pair%%:*}"; label="${pair#*:}"
  c="${PREFIX}-${suffix}"
  docker exec "$c" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; cd /repo && \
    rm -rf /tmp/rd && COVERAGE_LIVE_PATH_DATA_DIR=/tmp/rd \
    bash scripts/coverage_live_path.sh --label ${label}"
  docker cp "${c}:/tmp/rd" "${OUT}/${suffix}"
done

# Combine and report in any one of them; the stamps travel with the data.
docker cp "$OUT" "${PREFIX}-proxy:/tmp/combined"
docker exec "${PREFIX}-proxy" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; cd /repo && \
  bash scripts/coverage_live_path.sh ${1:---report} /tmp/combined"
```

- [ ] **Step 6: Prove `--gate` fails when it should**

Edit the floor on the host to `missing=1`, then:

```bash
set -o pipefail
bash scripts/coverage_live_path_isolated.sh --gate; echo "rc=$?"
```

**PREDICTED, NOT OBSERVED:** `coverage_live_path: GATE FAILED -- NNNN more missed statements than the floor.` and `rc=1`.

- [ ] **Step 7: Prove `--gate` passes when it should** — restore `missing=99999`, re-run, expect `rc=0`.

- [ ] **Step 8: Prove the denominator check fires** — set `statements=7977`, re-run. **PREDICTED, NOT OBSERVED:** `the denominator moved: floor 7977, this run 7978.` and `rc=1`.

- [ ] **Step 9: Prove the shape check fires** — set `shape=per-label/v2-sysmon`, re-run. **PREDICTED, NOT OBSERVED:** `floor was written under shape 'per-label/v2-sysmon'; this run is 'per-container/v1-sysmon'.` and `rc=1`. **This is the check that stops a floor from before this PR being compared against a number after it.**

- [ ] **Step 10: Prove `--write-floor` refuses to write worse** — set `missing=100`, run `--write-floor`. **PREDICTED, NOT OBSERVED:** `refusing to write a WORSE floor (100 -> NNNN).` and `rc=1`. Then set `COVERAGE_LIVE_PATH_ALLOW_REGRESSION=1` and confirm it writes.

- [ ] **Step 11: Restore the placeholder floor; `chmod +x` the new script; commit**

---

## Task 6: Wire the gate into `backend-tests.yml`

**Files:**
- Modify: `.github/workflows/backend-tests.yml`

**Interfaces:**
- Consumes: `scripts/ci_bootstrap_backend.sh`'s `CI_BACKEND_RUNNER` hook (used already by `metrics.yml:168`, the working precedent for running coverage over the backend suite here); `plan.outputs.has_tests` and `plan.outputs.base_image`.
- Produces: jobs `coverage-label` (3-way matrix) and `coverage-gate`; the latter required through the existing `Backend result` aggregate.

**Why the gate's matrix is hard-coded and not `plan.outputs.labels`.** The existing `test` matrix is **diff-gated** — a PR touching only `apps/epg/` never expands the three gate labels, and a docs-only PR skips the matrix before expansion. The gate must measure **the same three labels every time** or the floor is not comparable between runs. So it gets its own matrix with the three labels written out, gated only on `has_tests` so a docs-only PR still costs nothing.

- [ ] **Step 1: Resolve the artifact action SHAs with a tool**

```bash
set -o pipefail
gh api repos/actions/upload-artifact/commits/v4.6.2 --jq .sha
gh api repos/actions/download-artifact/commits/v4.3.0 --jq .sha
```

**Never hand-type these.** Confirm `actions/upload-artifact` and `actions/download-artifact` are the real publishers before trusting a SHA — a plausible SHA on a same-named fork is worse than a floating tag because it looks pinned.

- [ ] **Step 2: Add the two jobs**

Insert between `test` and `backend-result`, substituting the SHAs from Step 1 for `<UPLOAD_SHA>` / `<DOWNLOAD_SHA>`:

```yaml
  # Gate 2 (Phase 2 spec, Stage 2a). One Django test label per container -- the shape
  # the `test` matrix above already uses, and the shape stage 2a's isolation probe
  # measured. The labels are hard-coded rather than taken from plan.outputs.labels
  # BECAUSE that list is diff-gated: a PR touching only apps/epg/ would measure a
  # different label set and the floor would compare quantities that are not comparable.
  # See docs/superpowers/plans/2026-09-10-phase2-2a7-coverage-gate.md, Task 6.
  coverage-label:
    name: Coverage ${{ matrix.label }}
    needs: plan
    if: needs.plan.outputs.has_tests == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    strategy:
      fail-fast: false
      matrix:
        label: [apps.proxy.tests, apps.proxy.live_proxy.tests, apps.channels.tests]
    container:
      image: ${{ needs.plan.outputs.base_image }} # zizmor: ignore[unpinned-images]
      credentials:
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
      options: --entrypoint ""
    env:
      DISPATCHARR_ENV: aio
      DJANGO_SECRET_KEY: ci-test-secret-key
      POSTGRES_DB: dispatcharr
      POSTGRES_USER: dispatch
      POSTGRES_PASSWORD: secret
      DISPATCHARR_LOG_LEVEL: WARNING
      # metrics.yml sets this for the same reason: it picks up `coverage` and
      # `hypothesis` from uv.lock before the base image is next rebuilt. Both are in
      # pyproject.toml's MAIN dependency list, not a dev group, precisely because CI
      # installs with --no-dev (pyproject.toml:41-45).
      SYNC_PYTHON_DEPS: 'true'
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Verify the measurement can be trusted
        run: |
          set -euo pipefail
          export PATH="/dispatcharrpy/bin:$PATH"
          # An import failure here does not fail a label loudly -- it fails two test
          # modules, the label reports errors, and ~61 statements they would have
          # covered are silently counted as missed, moving the number the way a
          # regression moves.
          python -c "import coverage, hypothesis; print(coverage.__version__, hypothesis.__version__)"

      - name: Measure one label
        env:
          GITHUB_WORKSPACE: ${{ github.workspace }}
          COVERAGE_LIVE_PATH_DATA_DIR: /tmp/gate-data
          CI_BACKEND_RUNNER: bash scripts/coverage_live_path.sh --label ${{ matrix.label }}
        run: bash scripts/ci_bootstrap_backend.sh

      - name: Upload this label's coverage data
        uses: actions/upload-artifact@<UPLOAD_SHA> # v4.6.2
        with:
          name: gate-data-${{ matrix.label }}
          path: /tmp/gate-data
          include-hidden-files: true
          retention-days: 1

  coverage-gate:
    name: Coverage gate
    needs: [plan, coverage-label]
    if: needs.plan.outputs.has_tests == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    container:
      image: ${{ needs.plan.outputs.base_image }} # zizmor: ignore[unpinned-images]
      credentials:
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
      options: --entrypoint ""
    env:
      SYNC_PYTHON_DEPS: 'true'
    steps:
      - name: Install git
        # The base image ships no git, so actions/checkout falls back to a tarball with
        # no .git/ and the floor comparison below cannot fetch the base ref. Unversioned
        # apt is the base image's own convention (CLAUDE.md, build reproducibility).
        run: apt-get update && apt-get install -y --no-install-recommends git

      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false
          fetch-depth: 0

      - name: Download every label's coverage data
        uses: actions/download-artifact@<DOWNLOAD_SHA> # v4.3.0
        with:
          pattern: gate-data-*
          path: /tmp/gate-parts

      - name: Compare against the floor
        run: |
          set -euo pipefail
          export PATH="/dispatcharrpy/bin:$PATH"
          bash scripts/coverage_live_path.sh --gate /tmp/gate-parts

      - name: Refuse a floor edited downward
        if: always()
        env:
          BASE_REF: ${{ github.base_ref || github.event.repository.default_branch }}
        run: |
          set -euo pipefail
          # `missing` is a MAXIMUM and lower is better, so a RAISED value is the
          # regression. Read that twice; the polarity is the opposite of a percentage's.
          git fetch --depth=1 origin "$BASE_REF"
          if ! OLD_FILE=$(git show "origin/${BASE_REF}:scripts/coverage_live_path.floor"); then
            echo "no floor on the base ref; nothing to compare"
            exit 0
          fi
          OLD=$(printf '%s\n' "$OLD_FILE" | grep -E '^missing=' | cut -d= -f2)
          NEW=$(grep -E '^missing=' scripts/coverage_live_path.floor | cut -d= -f2)
          echo "floor: base=$OLD head=$NEW"
          if [ "$NEW" -gt "$OLD" ]; then
            echo "The floor was raised ($OLD -> $NEW): more missed statements are now permitted."
            echo "A floor may rise only in a PR that earns and explains the rise."
            exit 1
          fi
```

Note the base-ref read uses `if ! OLD_FILE=$(git show …)` rather than `git show … 2>/dev/null || echo ""`: **discarding stderr on a git query whose emptiness you intend to interpret makes "empty because it worked" and "empty because the ref is wrong" indistinguishable** (PR #240, pending).

- [ ] **Step 3: Extend `Backend result`**

Change `needs: [plan, test]` to `needs: [plan, test, coverage-gate]`, add to the step's `env:`

```yaml
          GATE_RESULT: ${{ needs.coverage-gate.result }}
```

and insert before the final `echo "Backend suite passed."`:

```bash
          if [ "$GATE_RESULT" != "success" ]; then
            echo "Coverage gate was required and did not succeed."
            exit 1
          fi
```

Extend the first `echo` to print `gate=$GATE_RESULT`. The existing three-branch logic is preserved exactly: a `plan` failure fails; `has_tests != true` passes (both `test` and the two coverage jobs skip together, legitimately); otherwise both must be `success`.

- [ ] **Step 4: zizmor must find nothing**

The edit hook runs it automatically. If unavailable, run it by hand at the version `.github/workflows/actions-lint.yml` pins:

```bash
zizmor .github/workflows/backend-tests.yml
```

Expected: `No findings`. Any finding blocks — the workflows are at zero and that is a ratchet.

- [ ] **Step 5: actionlint**

```bash
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest -color .github/workflows/backend-tests.yml
```

Expected: no output.

- [ ] **Step 6: Commit**

---

## Task 7: Measure the gated tree and write the real floor

**Run this only after Tasks 3-6.** Tasks 3 and 4 add tests and change the number; Tasks 5 and 6 change the shape, so the mechanism measured must be the shipped one.

**Files:**
- Modify: `scripts/coverage_live_path.floor`

- [ ] **Step 1: Run the stopping rule again on the final tree**

Repeat Task 1 Step 6 verbatim against the branch with Tasks 3-6 committed, through `scripts/coverage_live_path_isolated.sh --report`. **Maximum unchanged for six consecutive runs, minimum twelve.** Discard any run announcing a failed label. Record every run in order with its `docker ps` context.

- [ ] **Step 2: Take the worst**

The floor's `missing` is `max(runs)`. Record the median too — the PR description states the headroom given away, as `max − median`.

- [ ] **Step 3: Attribute, again** — repeat Task 2 Step 1's per-file/per-line diff on the final tree, and classify against Task 2 Step 2's table. **The PR description carries this table.** The spec requires the floor be justified by per-file attribution and that a later widening make the same case; a floor with no attribution beside it cannot be argued with later.

- [ ] **Step 4: Write it**

```bash
set -o pipefail
COVERAGE_LIVE_PATH_RUNS=<n> bash scripts/coverage_live_path_isolated.sh --write-floor
```

Then **check `missing` by hand**: it must equal `max(runs)` from Step 2, not whatever the run that invoked `--write-floor` happened to produce. Edit the file to `max(runs)` if they differ, and re-run `--gate` to confirm it passes.

```bash
cat scripts/coverage_live_path.floor
```

- [ ] **Step 5: Prove the committed floor passes** — run `--gate` three more times. All three must exit 0. **If any fails, the floor is not the worst run** — return to Step 1 and keep running; the stopping rule was not met.

- [ ] **Step 6: Commit**

---

## Task 8: The record — spec amendment, `CLAUDE.md`, matrix, metrics

This is what turns "2a landed where it landed" from a thing a reader infers into a thing the repository says.

**Files:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, `CLAUDE.md`, `docs/relay-parity-matrix.md` (verify), `metrics/curated/*`

- [ ] **Step 1: Verify the matrix is complete and consistent**

```bash
set -o pipefail
grep -o "owed: [0-9a-z-]*" docs/relay-parity-matrix.md | sort | uniq -c
cd e2e && npx playwright test tests/guards/ --reporter=list 2>&1 | tail -20
```

Expected: exactly one owed marker, `owed: 2b-3`; every guard test green; `30 rows — 29 pinned, 1 owed, 2 white-box-only`. `GATE_1_CLOSED` stays `false` — **row 18 is 2b-3's and 2a-7 does not flip it.** The guard asserts "at least one row is still owed" while it is `false`, so flipping it here would fail.

- [ ] **Step 2: Amend the spec's Gate 2 section**

Append, in the spec's idiom — superseded claims struck in place, never deleted. Fill `<…>` from Task 7:

```markdown
**MEASURED, 2026-09-10, by 2a-7, on the first tree that carried all four coverage PRs
at once.** `missing` <MIN>-<MAX> of 7,978 (<PCT>%) over <N> runs under
`per-container/v1-sysmon`, against an allowance of 1,595 — a shortfall of <SHORT>.

**Every projection this section previously carried was arithmetic over incommensurable
trees, and one of them was wrong in the family this section already names.** 2a-4 was
credited with ~61 statements; that is `input/manager.py` alone from #236's body — a
single file's delta presented as a whole PR's contribution (failure mode 2, a subset
presented as a whole). Measured against 2a-6's own baseline, 2a-4 bought ~300. In the
same direction, 2a-6's finished tests measured ~630-690 against the ~483 its two probe
tests projected. **Neither correction could be composed with the others**: 2a-3 and 2a-5
double-counted 84 statements — 25% of their naive sum — when finally measured together,
and no one had measured 2a-4 against 2a-6 at all. **The rule this adds to the four
already here: a delta measured on tree A and a delta measured on tree B do not add. Only
a measurement on one tree settles a sum, and this stage produced three separate
occasions to learn it.**

Three further corrections, each of the same family:

1. **`+ http_streamer.py's 101` is spent.** 2a-4 covered 74 of that file as a side
   effect (#236: 101 -> 27), so the bracket row that closes the gate by +91 no longer
   exists. Fourth instance of the already-banked shape, and the first carried in a
   *conclusion* rather than a supply table.
2. **`_handle_bsf_error` is 35 statements and is NOT dead** — reached whenever ffmpeg's
   stderr carries `aac_adtstoasc ... is not supported by the bitstream filter`
   (`output/fmp4/manager.py:373`), which 2a-2's PATH stand-in can print on demand.
3. **Excluding every provably-dead statement anyone has found moves the gate by ~1.4
   percentage points** (~148: `_cleanup_local_resources` 62, `_check_orphaned_channels`
   24, #231's `input/manager.py` cluster ~62). Denominator surgery cannot reach this
   gate, so it is not attempted; the dead code stays in the denominator to be *deleted*,
   which raises the floor for free. `_cleanup_local_resources` is additionally one of
   the four measured variance regions, so excluding it would improve the number by
   making the gate blind to a flapping region.

**The ratchet carries no tolerance parameter, and the tolerance paragraph above is
amended rather than met.** The floor's `missing` is set from the WORST of at least
twelve runs on the tree it gates, under a stopping rule (maximum unchanged for six
consecutive runs). All three of that paragraph's constraints hold: sized to the measured
residual on the gated tree, justified by 2a-7's per-file attribution, and a movement
outside it — a run worse than the worst of twelve — is a finding. The argument for
preferring it over a number: a tolerance is a number nobody re-derives, while a floor is
one the monotonicity check in `backend-tests.yml` compares against `origin/main` on every
run. **The evidence for it is that the tolerance was sized at ~51, then >=66, then ~45 in
three weeks, and that the variance-region count itself moved twice while 2a-7's plan was
being written** — up, when the isolation probe's rounds 9-10 fired the non-owner cleanup
that its first eight rounds never touched; and back down, when `output/ts/generator.py`
227-230 was reported as a new flapping region on a 2-of-3-run observation and a 37-run
count across five trees then showed it permanently missed everywhere except on trees
carrying 2a-6's tests. **A tolerance sized on any snapshot of that list would have been
wrong, and wrong in both directions.**

**The gate runs one label per container.** Measured: the 64-line teardown block is
block-complete in 10/10 isolated rounds against 5/11 shared-container runs (Fisher exact
two-tailed p = 0.0124), with the PostgreSQL volume shared throughout and a per-container
process census finding no leftovers — so PG state and stray processes are excluded, and
what remains (the Redis process, the container's accumulated state) is not separated.
**Isolation does NOT make the total deterministic**: spread 44 isolated against 47
shared, with a second 28-line region (`server.py` 2099-2112 and 2489-2566, the
NON-owner's local cleanup) firing in rounds 9-10 that rounds 1-8 all missed. **The shape
is adopted on correctness grounds — the gate should measure what CI measures — and not
as a variance fix.**
```

- [ ] **Step 3: Add the PR that owns the shortfall**

**Per Task 1's decision rule, exactly one of these.** Insert in the PR table; add nothing to `PRS` in `e2e/tests/guards/parity-matrix.ts` unless a matrix row later carries an `owed:` marker for it.

If `max(runs) ≤ 1,995` — after the 2a-7 row:

```markdown
| 2a-8 | `migration/phase2a-mid-sized-pool` | Close the measured <SHORT>-statement shortfall to Gate 2's ≥80%, against the ~898-statement mid-sized pool no PR owns: `views.py`, `channel_status.py`, `client_manager.py`, `input/buffer.py`, `log_parsers.py`, `url_utils.py`. Ordinary code, not the `server.py` fault-injection tail; 2a-3 demonstrated ~28 statements per test there. Deleting #230's and #231's dead code raises the floor for free and is in scope. | `scripts/coverage_live_path.sh --gate` green against a floor of ≤1,595 missing, and the floor raised in this PR | 2a-7 |
```

If `max(runs) > 1,995` — after the 2b-3 row:

```markdown
| 2b-4 | `migration/phase2b-coverage-to-80` | Close the measured <SHORT>-statement shortfall to Gate 2's ≥80%. Supply, from § Gate 2's pool table minus what 2a-3…2a-6 took: `input/manager.py` ~177-187, 2a-5's surfaces ~133, 2a-6's group residual 76-127, `server.py`'s expensive tail 146 (**a cost judgement, not a measurement** — ~28 `except Exception: logger.error(...)` arms needing fault injection), and the ~898-statement mid-sized pool no PR owns. Deleting #230's and #231's dead code raises the floor for free and is in scope. Also decides `apps/proxy/utils.py`'s place in the denominator (§ Gate 2). | `scripts/coverage_live_path.sh --gate` green against a floor of ≤1,595 missing, and the floor raised in this PR | 2a-7 |
```

**And amend D7 in the same edit** so the roll-call stays true: D7's "No PR in stage 2c may merge until both gates are green" is **unchanged in force**; its owner for Gate 2 is now `2a-8`/`2b-4`, not `2a-7`. **2a-7 turns the ratchet on; it does not turn the blocker off.** Also amend § "2a's own legitimate stopping point", which says coverage sits at ≥80% after 2a-7 — it does not, and a stage that claims a gate it did not reach makes the gate unfalsifiable rather than met, which is that paragraph's own argument turned on itself.

- [ ] **Step 4: `CLAUDE.md` § Testing**

```markdown
**Gate 2 is a CI-enforced coverage ratchet on the relay's own modules.**
`scripts/coverage_live_path.sh` measures statement coverage over
`apps/proxy/live_proxy/**` plus the ten Phase 1 boundary modules — a 7,978-statement
denominator fixed by `scripts/coverage_live_path.coveragerc`, **one Django label per
container** (`scripts/coverage_live_path_isolated.sh` locally; `backend-tests.yml`'s
`coverage-label` matrix plus its `coverage-gate` combine job in CI), under
`COVERAGE_CORE=sysmon` — the default C tracer drops every statement executing after a
`gevent.sleep()`, so a C-tracer figure is not comparable with a sysmon one **in either
direction**. `--gate` compares against `scripts/coverage_live_path.floor` and exits 1 on
a regression; `Backend result` requires it. **The floor's `missing` is set from the worst
of ≥12 runs, so there is no tolerance parameter** — the measurement is bimodal, not
noisy, and three regions are known to flap: the owner-side coordinated stop
(`channel_service.py` 28-49 and `server.py`'s sweep), the non-owner local cleanup
(`server.py` 2099-2112, 2489-2566) and the stderr-reader join (`input/manager.py`
1739-1767). Per-container isolation makes the first
block deterministic and does **not** make the total so (spread 44 vs 47). **A failed
label invalidates a measurement rather than degrading it** — a tree missing `hypothesis`
reported 3,230 where the same tree with it reported 3,169, a 61-statement inflation
moving the way a regression moves. **Stage 2a ended at <PCT>%, not the spec's ≥80%**; the
shortfall is owned by `<2a-8|2b-4>` and D7 still blocks every 2c PR until it closes.
```

Also correct, in the same edit, the existing "`hypothesis` is a dev dependency" — it is in `pyproject.toml`'s **main** list (`pyproject.toml:41-45`), deliberately, because CI installs with `--no-dev`. And note `#240`'s three shell hazards if it has merged by now; if it has not, leave `CLAUDE.md` alone on that point rather than duplicating an open PR.

- [ ] **Step 5: Metrics**

```bash
set -o pipefail
python3 -m metrics.build --validate-only
```

Expected: `ok: N metrics, M milestones, K defects`. Add a milestone for stage 2a's close carrying the measured percentage, and ledger entries for anything Tasks 1-4 found. The hook on `metrics/**` runs `scripts/run_metrics_tests.sh` automatically.

- [ ] **Step 6: Commit**

---

## Task 9: OPTIONAL, USER'S CALL — add `apps/proxy/utils.py` to the denominator

**This plan recommends deferring it** (see § THE GATE DECISION). Do this task only on an explicit user instruction to include it now.

**Files:** `scripts/coverage_live_path.coveragerc`, `scripts/coverage_live_path.sh`, `scripts/coverage_live_path.floor`, the spec, `CLAUDE.md`

- [ ] **Step 1: Add the module**

In `[report] include`, after `apps/proxy/internal_base_url.py`:

```
    apps/proxy/utils.py
```

and extend the comment above the block:

```
# apps/proxy/utils.py is here because D4 makes the live half of
# get_user_active_connections (utils.py:256, _live_connections) part of the contract the
# Go relay reproduces. The module also holds a good deal that has nothing to do with the
# relay boundary, so this is an imprecise instrument for a precise need -- recorded
# because the sharper alternative (relocate _live_connections to a boundary module in 2b
# and let it enter by relocation) was considered and deferred, not overlooked.
```

- [ ] **Step 2: Bump the shape** — `SHAPE_ID="per-container/v2-${COVERAGE_CORE}"`, with a comment saying the denominator changed and a v1 floor must be refused rather than compared.

- [ ] **Step 3: Confirm the new denominator**

```bash
set -o pipefail
bash scripts/coverage_live_path_isolated.sh --report | tail -3
```

**PREDICTED, NOT OBSERVED:** `statements 8238` — 7,978 + 260, the 260 measured statically for this plan at `e62ab428`. **If it is not 8,238, `utils.py` changed size or another module moved; find out which before continuing.**

- [ ] **Step 4: Redo Task 7 in full.** The old floor is not comparable and `--gate` will say so — correctly.

- [ ] **Step 5: Update the spec, `CLAUDE.md` and the PR description** to say 8,238 wherever 7,978 appeared, and to record that the allowance rises to 1,647 while the missing count rises by ~90, i.e. **a net +38 statements of shortfall** — and that the decision was taken on D4's contract argument, not on the arithmetic, precisely because the arithmetic pointed the other way.

- [ ] **Step 6: Commit**

---

## Task 10: The PR description

**Files:** none in the repo. Write to a file and use `gh pr create --repo D10Scot/Dispatcharr --body-file`. **Do not open the PR** unless the orchestrator asks.

Required, in this order:

1. **The measurement and the verdict.** Task 1's number, the decision rule as it was committed *before* the measurement, and which branch it selected. Lead with where stage 2a landed against ≥80% and who owns the shortfall. A reader must not have to infer it.
2. **Why the earlier projections were wrong** — 2a-4's 61-was-one-file, 2a-6's 483-was-a-probe, and the incommensurable-trees rule that outlives both.
3. **The tolerance ruling** — worst-run floor, the stopping rule, the three general variance regions plus 2a-6's introduced one, and **the measured headroom given away** as `max − median`.
4. **The shape ruling** — per-container, on correctness grounds, with the p-value *and* the spread that did not move, plus the counter-argument for the single-job shape and why it lost.
5. **Task 2's and Task 7's per-file/per-line attribution tables.**
6. **The two inherited rows**, named as inherited: row 29 from 2a-4, row 30 from 2a-5. Row 21's prose-only obligation was discharged by 2a-5 at `cbdc66c2` and is **not** 2a-7's — say so, so nobody looks for it.
7. **Every break check**, with the failure text **actually observed**.
8. **The spec contradictions taken deliberately:** the tolerance (a floor, not a parameter), the hard-coded gate matrix (the existing one is diff-gated), and the gate value (a ratchet at the measured level, with ≥80% reassigned rather than lowered).
9. **`apps/proxy/utils.py`** — the recommendation to defer, its reasoning, and that it is the user's open decision.
10. **Timings** — how much `coverage-label` + `coverage-gate` add to a CI run, measured.

---

## Self-review notes

- **Spec coverage.** 2a-7's row names four deliverables: the floor file (Tasks 5, 7), the `backend-tests.yml` wiring (Task 6), the gate CI-blocking (Task 6 Step 3), and "green at ≥80%" — **conditional**: delivered if Task 1 selects (b) and `2a-8` lands, otherwise reassigned by Task 8 Step 3. The Gate 2 section's tolerance requirement is answered by the ruling and recorded in Task 8. The stage's two inherited obligations are Tasks 3 and 4. Matrix completeness is Task 8 Step 1.
- **Ordering.** Task 1 gates everything (it builds the tree and takes the decision measurement). Tasks 3-4 must precede Task 7 (they change the number). Tasks 5-6 must precede Task 7 (the measured mechanism must be the shipped one). Task 9, if taken, invalidates Task 7 and repeats it.
- **What this plan does not do.** It does not exclude anything from the denominator, does not delete dead code, and does not itself widen any coverage PR's scope — the first two are argued against above, and the third is `2a-8`'s if Task 1 selects it.
- **The one thing a reviewer should push on.** The 1,995 threshold is a judgement built on 2a-3's ~28-statements-per-test yield. If a reviewer thinks the mid-sized pool is dearer than that, the threshold moves down and (a) wins more often. That is the right argument to have, and it is better had **before** Task 1's number arrives than after.
