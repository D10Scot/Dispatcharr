# Phase 2 PR 2a-7 — the coverage gate, its floor and its CI wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Gate 2 from a number in a spec into a CI-enforced ratchet — a floor file measured on the tree it gates, a `--gate` mode in `scripts/coverage_live_path.sh` that fails a PR that regresses it, a job in `backend-tests.yml` that runs it, and an honest, dated record of the fact that the stage lands near **72%**, not the **≥80%** the spec asked for.

**Architecture:** One CI job, one container, `scripts/ci_bootstrap_backend.sh` with `CI_BACKEND_RUNNER=scripts/coverage_live_path.sh --gate` — the shape `metrics.yml` already proves. The floor is a committed file holding the measurement shape, the denominator and a maximum permitted `missing` count, set from the **worst** of ten runs, so the ratchet needs no separate tolerance parameter. Two inherited parity-matrix rows are closed in the same PR, and the spec's 80% requirement is reassigned to a named owner in stage 2b rather than quietly deleted.

**Tech Stack:** Bash, `coverage` 7.10+ under `COVERAGE_CORE=sysmon`, Django's test runner, GitHub Actions, Playwright (the parity-matrix guard is a Playwright test), `zizmor` (workflow lint ratchet).

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — § Stage 2a › **Gate 2 — 80% statement coverage**, and the 2a-7 row of the PR table. Read the whole Gate 2 section before Task 5; it is the authority on why the measurement shape is part of the number.

**Branch:** `migration/phase2a-coverage-gate`, stacked on **2a-6** (`migration/phase2a-fmp4-coverage`), which is stacked on 2a-4, 2a-5, 2a-3 and 2a-2 (#229). 2a-7 measures the tree it gates, so it cannot be based on `main`.

---

## THE GATE DECISION — read this before the tasks

The spec's 2a-7 row says the deliverable is "the gate turning green and CI-blocking at ≥80%". **Measurement says ≥80% is not reachable by stage 2a as scoped.** This section gives the arithmetic, its provenance, and a recommendation. The user decides; the tasks below implement the recommendation and say exactly which task to drop if the user decides otherwise.

### The arithmetic, with provenance on every term

| Term | Value | Where it comes from | Confidence |
|---|---|---|---|
| Denominator | **7,978** | **Re-derived for this plan**, statically, at `e62ab428`: `coverage.parser.PythonParser().statements` summed over the 38 non-test files `scripts/coverage_live_path.coveragerc`'s `[report] include` names. Reproduces the spec and 2a-2's run to the statement. | HARD |
| Allowance at 80% | **1,595** missing | 0.20 × 7,978 = 1,595.6; 1,595 missing → 80.008%, 1,596 → 79.995% | HARD |
| 2a-3 + 2a-5 combined | **2,839** missing | sysmon, n=8, median, measured by the `measure-combined` agent on `measure/2a3-plus-2a5`. Not re-measured here. | MEASURED, not by this plan |
| 2a-4, incremental on top of that | **−74** floor / −130 mid / **−219** ceiling | #236, C tracer: gate total 3,202-3,216 → 2,988-2,992, i.e. −210..−228 against a *base* tree. Of that, `input/http_streamer.py` 101 → 27 = **−74 is fully incremental** — nothing else in the tree imports that file (the rcfile's own comment and the spec's `source`-vs-`include` ruling both rest on it). `input/manager.py` −61..−72 is partly incremental. The rest lands in files 2a-3 and 2a-5 have already moved. | floor HARD, rest ESTIMATE |
| 2a-6, incremental | **−483** low / **−575** high | Spec's probe table, sysmon: 3,115 → 2,540 = −575 gate-wide from two probe tests, of which 483 in the fmp4/Output-Profile group's own files. `server.py`'s 142-statement Output-Profile bucket is **not** inside the 2,839 — the spec records that 2a-5 deliberately left it — so the higher figure is the right one to use. | MEASURED (probes), PROJECTED (finished tests) |

```
combined 2a-3 + 2a-5 (measured, sysmon, n=8 median)          2839
optimistic:  − 219 (2a-4 ceiling) − 575 (2a-6 high)   =      2045
mid:         − 130               − 483                =      2226
pessimistic: −  74 (2a-4 floor)  − 483                =      2282

gate allows (0.20 x 7978)                                    1595
                                        SHORTFALL      450 .. 687
                             projected coverage    71.4% .. 74.4%
```

**The brief that commissioned this plan carried `2a-4 ≈ −61`. That is below 2a-4's own hard floor.** −61 is the `input/manager.py`-only figure from #236; it omits `http_streamer.py`'s −74, which #236 measured directly and which no other PR can duplicate. Correcting it moves the projection from 71.23% to a band of 71.4-74.4%. **It does not change the answer**, and that is the point of stating it: the shortfall survives every correction anyone has found.

### Option (b) — extend 2a's scope to close ~450-690 statements

What is actually left, from the spec's own pool table minus what the four PRs report taking:

| Pool | Remaining | Note |
|---|---|---|
| 2a-4 `input/manager.py` | ~177-187 | pool 247 reachable, #236 reports taking ~60-70 |
| 2a-5 (`server.py` 257 + authorize rows 89-158) | ~133 | took its 124 target plus the rows |
| 2a-6 group residual | 76-127 | 254 pool at the spec's 30-50% |
| `server.py` expensive tail | 146 | **a cost judgement, not a measurement** — ~28 functions whose bodies are `except Exception: logger.error(...)`, needing faults injected into Redis, `emit_event` or the OS |
| `input/http_streamer.py` | **27, not 101** | **the spec's bracket row "+ `http_streamer.py`'s 101" is spent.** 2a-4 took 74 of it as a side effect (#236). Adding 101 to any supply total now is the fourth instance of the already-banked error the spec names three of. |
| mid-sized pool nobody owns (`views.py`, `channel_status.py`, `client_manager.py`, `input/buffer.py`, `log_parsers.py`, `url_utils.py`) | ~898 | spec's figure after 2a-3 spent ~53 of it |

Max supply outside the unowned mid-sized pool: **~593**. That lands inside the shortfall band's middle but **below its pessimistic end**, and only by taking every last reachable statement *plus* the whole soft fault-injection tail. In practice option (b) means widening into the ~898-statement pool as well — 2 to 4 more PRs at the four coverage PRs' own demonstrated rate (8-35 tests each, 140-260 statements each), each carrying the full break-check discipline, on statements that are by construction the hardest and lowest-yield remaining.

**And they buy nothing for Gate 1.** Every parity-matrix row is owned and closable without them.

### Option (c) — change the denominator

Measured for this plan at `e62ab428` (`coverage.parser.PythonParser` + an `ast` walk mapping statements to their enclosing `def`):

| Candidate | Statements | Verdict |
|---|---|---|
| `server.py::_cleanup_local_resources` | **62** | excludable — #230, behind a branch only an owner can reach |
| `server.py::_check_orphaned_channels` | **24** | excludable — #230, no callers anywhere in the tree |
| `input/manager.py` dead cluster (#231): `_close_connection` 13, `_close_all_connections` 20, `_create_session` 7, ~2/3 of `stop` (33 total) | **~62** (the PR called it ~46) | excludable |
| `fmp4/manager.py::_handle_bsf_error` | **35 — and NOT dead** | **reject.** It is reached whenever ffmpeg's stderr carries `aac_adtstoasc ... is not supported by the bitstream filter` (`output/fmp4/manager.py:373`), which 2a-2's `PATH` stand-in can print on demand. The brief's "~9 dead statements" is wrong in both count and kind. |
| `input/http_streamer.py` | 101 | **void** — 73% covered since 2a-4 (#236: 101 → 27). Excluding it now changes the percentage by ~0.0pp. |

Defensible exclusions total **~148**. Applied to the mid projection: denominator 7,978 → 7,830, missing 2,226 → 2,078 → **73.5%** against 72.1%. Allowance becomes 1,566; still **512 short**.

**Every provably-dead statement anyone has found, excluded together, moves the gate by about 1.4 percentage points against an eight-point gap.**

### Recommendation

**Take (a) — ratchet at the achieved level — and do NOT take (c).** Three reasons, in order of weight:

1. **(c) cannot reach the gate, so it cannot be justified as a way of reaching it.** 1.4pp against 8pp. Any *other* justification for excluding those statements is a different PR's argument, and it should be made on its own merits, in daylight, not folded into the PR whose job is to set the number the exclusions flatter. The `[run] source` ruling in the rcfile exists precisely because a denominator that shrinks when code goes untested is the wrong shape for a ratchet; hand-excluding inconvenient code is that same hazard wearing a different coat.
2. **The right disposal of dead code is deletion, not exclusion** — and deletion raises the floor for free, with no argument about where the line sits. `#230` and `#231` are already filed. Stage 2b deletes Python wholesale; 2d deletes `live_proxy` entirely. Leave them in the denominator and let the floor tell the truth.
3. **(b) buys the number at the price of the stage.** The marginal statement in the remaining pool is a fault-injected `except Exception: logger.error(...)` arm. Pinning those is not what makes a Go port safe — the parity matrix is, and D7's own stated reason for Gate 2 ("the 63 portable tests alone are not enough to catch a subtle regression in, say, the buffering detector's cumulative-average arithmetic") is **already discharged**: 2a-4 pinned exactly that, rows 1-6 and 28, with mutation tests. The gate's *purpose* is met at ~72%. Its *number* is not, and those are different claims.

**But do not lower the gate. Move it, and name its owner.** The spec's own roll-call principle — "owned by nobody was the actual defect it fixed" — applies to a requirement as much as to a matrix row. So 2a-7 ships:

- a floor at the measured achieved level, CI-enforced, that can rise and cannot be edited down;
- a spec amendment recording the measured shortfall, dated, with the arithmetic above;
- **the ≥80% requirement retained and reassigned to a new owned PR in stage 2b** (proposed id `2b-4`), keeping D7's rule that no 2c PR merges until Gate 2 reads ≥80% — so the phase's first hard blocker stays on, and 2a-7 does not silently become the PR that turned it off.

That is the honest version of (a): the stage does not meet the gate, the gate is not weakened, and the shortfall has an owner and a date.

### The one denominator change this plan does recommend: `apps/proxy/utils.py`

Measured for this plan: **260 statements** (the brief's figure, confirmed). It is outside the `[report] include` list today, so work there earns nothing toward the gate — while **D4 makes the live half of `get_user_active_connections` part of the contract the Go relay reproduces**. A module the port must reproduce belongs in the denominator of the gate that protects the port.

Recommend **adding it, in 2a-7 specifically**, because 2a-7 is the only moment in the stage where changing the denominator invalidates no in-flight measurement: every sibling PR has already quoted its figures and merged. After 2a-7 the denominator is a committed floor and moving it is a deliberate re-baseline.

Cost, stated plainly: the denominator becomes **8,238**, the shape id bumps to `v3`, every figure in #225/#229/#236/#237/#238/#239 becomes historical, and — because `utils.py` sits at roughly 65% against a projected ~72% — **the headline percentage falls by about 0.2 points.** That it moves the number the wrong way is the reason to decide it on the contract argument rather than on the arithmetic.

**This is the user's open question.** Task 9 implements it and is a clean drop if the answer is no.

---

## THE TOLERANCE RULING

### What is known

- Eight unmodified baseline runs on one tree gave `3169, 3176, 3168, 3172, 3169, 3112, 3110, 3111`. Two clusters, **56 apart**; within-cluster spread ≤ 8; **max − min = 66**.
- A 64-statement block flips as a unit — 0/64 or 44-64/64, never between: `channel_service.py` 28-49 (`mark_channel_stopping`), 575-601, 971-989, plus `server.py` 252, 261, the 359-426 region, 888, 1259-1260, 1802-1803, 2010-2042. The teardown path. Found independently by two agents on different trees.
- The spec measured a 63-statement spread over twelve sysmon runs, and 51 with 2a-6's probes present.
- A failed label **invalidates** a measurement rather than degrading it: a tree missing `hypothesis` reported 3,230 where the same tree with it reported 3,169 — a 61-statement inflation, larger than any tolerance and moving the way a regression moves.

### The ruling

**The floor is set from the WORST of ten runs, and the gate carries no separate tolerance parameter.**

A ratchet asks one question: *is today's `missing` greater than the committed floor?* If the floor is the median, a tolerance must be bolted on to absorb the spread. If the floor **is** the worst observed run, the spread is already absorbed and the tolerance is redundant. The two have **identical exposure** — a regression smaller than the spread hides under either — but the worst-run floor has one fewer knob, and, decisively:

> **A tolerance is a number nobody re-derives. A floor is a number the monotonicity check already polices.** Widening a tolerance is a one-character edit in a script that no CI check inspects. Widening a floor is an edit to a committed file that `--gate` refuses to accept downward and that the CI wiring compares against `origin/main`'s copy in the same run.

This **contradicts the spec**, which says "2a-7's ratchet carries a small tolerance, and three constraints on it". All three of its constraints survive intact under a worst-run floor: (i) it is sized to the measured residual on the tree being gated, not to an inherited band; (ii) it is justified by per-file attribution, which Task 2 produces; (iii) a movement outside it is a finding — under this shape, "outside it" means *a run worse than the worst of ten*, which is exactly the signal wanted. Task 8 records the contradiction and the argument in the spec.

**Concretely:** whatever Task 2's ten runs measure, the floor's `missing` is `max(runs)`. Given the evidence above, expect that to sit **60-80 statements above the median** — call it ~0.8-1.0pp of headroom given away. **Say that number in the PR description.** It is the price of the ruling and it must not be discovered later.

### The isolation question, and what to do with either answer

`apps.proxy.live_proxy.tests` reportedly hits the 64-block **64/64 when run in isolation**, and flaps only inside `coverage_live_path.sh`'s three-label sequence. `backend-tests.yml` runs one label per matrix job in its own container and never reproduces that sequence.

Task 2 measures this locally rather than waiting on anyone: five isolated `--label apps.proxy.live_proxy.tests` runs against ten full-script runs, with a per-line diff.

- **If isolation is deterministic** — the block is 64/64 in all five isolated runs and flaps in the full-script runs — then the measurement harness is the cause, the gate should isolate per label, and **Task 7a** (written out below) replaces the single-job CI shape with per-label containers plus artifact combine, and the floor is set from a much tighter spread.
- **If it flaps in isolation too**, the cause is the relay's own cleanup thread sampling a channel mid-shutdown, which no test harness controls. The worst-run floor stands as ruled and Task 7a is dropped.

**Do not guess which.** The plan carries both, and Task 2 decides by measurement.

---

## Global Constraints

Copied from `CLAUDE.md` and the spec. Every task's requirements implicitly include this section.

- **Container discipline.** This PR's implementer gets its own container: `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a7`, `DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a7`, `DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest`. **Upstream's image (`ghcr.io/dispatcharr/dispatcharr:latest`, the script's default) carries neither `coverage` nor `hypothesis`** — the fork's image is not optional here.
- A container built from a `start-test-container.sh` older than **#238** also needs `docker exec <c> redis-cli CONFIG SET save ""`, and may come up with **no database at all while exiting 0** (issue #241). **Check, do not assume** — Task 1 Step 3 checks.
- **Never** pass `--settings=dispatcharr.settings` to `manage.py test`.
- **Stage and commit in separate Bash calls.** The `PreToolUse` hook on `Bash(git commit*)` runs *before* the command, so one call doing both is blocked. It matches on command text, so write commit messages to a file with the Write tool and use `git commit -F <file>` — a message merely *containing* the words "git commit" trips it too.
- `gh` **always** with `--repo D10Scot/Dispatcharr`; without it `gh` resolves to the upstream public tracker.
- **Two tiers of running.** A test *reaching* a branch is settled by an `INFO` grep. A test *pinning* a behaviour needs a **break check**: patch the production behaviour, confirm the patch applied with `sed -n` on the patched lines, watch it go red, revert, watch it go green. **One red is not a break check** — a shipped assertion in this stage went red 1 run in 5; require **three consecutive reds**. A break lever must break the *mechanism*, not select a second documented behaviour.
- **A change made for readability is still a change to the mechanism.** Any edit to an existing test — a docstring included — re-runs that test's break check.
- **No wall-clock assertion may be a pin.** The harness's upstream is paced, but the relay reads ahead into Redis and the generator serves from there, so a client's read is served at memory speed regardless. Elapsed-read assertions are inert at any rate.
- Every predicted failure string in this plan is marked **PREDICTED, NOT OBSERVED**. Quote what you actually saw, never what this plan said you would see.
- `COVERAGE_CORE=sysmon` throughout. `scripts/coverage_live_path.sh` exports it itself; do not override it. A figure taken under the C tracer is not comparable with one taken under sysmon **in either direction**, and #236 and #237 quote C-tracer figures for exactly this reason.
- **A failed label invalidates a measurement.** Any run in which `coverage_live_path.sh` prints `label(s) failed under coverage:` is discarded, not recorded.
- **zizmor is a zero-findings ratchet.** `.github/workflows/backend-tests.yml` is edited by this PR; every finding in that file blocks, legacy included. Add `persist-credentials: false` to every `actions/checkout`; grant no permission a job does not need.
- Shell hazards that have each produced a wrong answer in this stage: in zsh, brace the variable in `git show "${b}:path"` — unbraced, `:path` is read as a history modifier; **a clean worktree is not an unoccupied one** (an agent on a measurement task writes no files for its whole first task — use `docker ps --filter name=<container>`); and a non-zero exit **does not survive a pipe** — check `${PIPESTATUS[0]}` or drop the pipe, and never discard stderr from a measurement command.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `scripts/coverage_live_path.floor` | The committed ratchet. Five `key=value` lines: measurement shape, denominator, maximum permitted `missing`, the derived percentage, and the date and run count it was measured over. The percentage is derived and informational; **`missing` is the ratchet**, because a percentage is what hid the error the spec's Gate 2 section records. |
| `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py` | Row 30's pin: a credential an authenticator *rejects* 401s; one merely *declined* falls through to anonymous and streams. |

**Modified**

| Path | Change |
|---|---|
| `scripts/coverage_live_path.sh` | Two new modes — `--gate` (measure, then compare to the floor, exit 1 on regression or on a shape/denominator mismatch) and `--write-floor` (measure, then write the floor, refusing to write a worse one without an explicit override). The existing shape guard, tracer export and failed-label announcement are untouched. |
| `.github/workflows/backend-tests.yml` | One new job, `coverage-gate`, and `Backend result` extended to require it. |
| `docs/relay-parity-matrix.md` | Two new rows, 29 and 30, both pinned. |
| `e2e/tests/guards/parity-matrix.ts` | `HIGHEST_ROW_ID` 28 → 30. |
| `apps/proxy/live_proxy/tests/test_manager_connection_failover.py` | Docstring only: the row-29 test stops saying "Closes no matrix row". Re-break-checked because a readability edit is still an edit. |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | Gate 2 amendment: the measured outcome, the reassignment of ≥80% to `2b-4`, and the tolerance ruling. Plus `2b-4` added to the PR table. |
| `CLAUDE.md` | § Testing gains the gate, its floor and how to run it. |
| `metrics/curated/*` | Milestone + ledger updates (a PR that merges a goal updates them in the same PR). |

**Untouched, deliberately:** `scripts/coverage_live_path.coveragerc` — unless Task 9 runs, in which case it gains `apps/proxy/utils.py` and the shape id bumps to `v3`.

---

## Task 1: The container, and a baseline that is known-good rather than assumed

**Files:** none modified. This task produces a recorded measurement.

**Interfaces:**
- Produces: a verified container named `dispatcharr-testrunner-2a7`; one full `coverage_live_path.sh` run with all three labels green and a denominator of 7,978 (or 8,238 if Task 9 has already run — it has not; it runs last).

- [ ] **Step 1: Create the worktree and stack the branch on 2a-6**

```bash
cd /Users/dion/git/Dispatcharr
git worktree add .worktrees/phase2-2a7 migration/phase2a-coverage-gate
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a7
git rebase migration/phase2a-fmp4-coverage
git log --oneline -3
```

If `migration/phase2a-fmp4-coverage` has not landed its final commits yet, stop and ask the orchestrator. 2a-7 measures the tree it gates; measuring a tree missing 2a-6 produces a floor nobody can meet or a floor anyone can meet, and there is no way to tell which from the number.

- [ ] **Step 2: Start the container**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a7
DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a7 \
DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a7 \
DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest \
CLAUDE_HOOK_REPO_ROOT="$PWD" \
  bash .claude/hooks/start-test-container.sh
```

- [ ] **Step 3: Check the three things that come up silently broken**

Issue #241: the container can exit 0 with no database. #238: Redis started with a save schedule against a read-only mount refuses every write for the container's life. And the fork's image must carry both `coverage` and `hypothesis`.

```bash
C=dispatcharr-testrunner-2a7
docker exec "$C" bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; \
  psql -h /var/run/postgresql -U dispatch -l | grep -c dispatcharr'
docker exec "$C" redis-cli CONFIG SET save ""
docker exec "$C" redis-cli SET __probe__ 1
docker exec "$C" bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; \
  python -c "import coverage, hypothesis; print(coverage.__version__, hypothesis.__version__)"'
```

Expected: a count of at least 1 for the database; `OK` from both redis-cli calls; two version strings. **If the database count is 0, the container is not usable** — re-run Step 2 and read the script's output rather than its exit code.

- [ ] **Step 4: One full gate run**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc \
  'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && bash scripts/coverage_live_path.sh' \
  2>&1 | tail -30
```

Expected, on the last line:

```
coverage_live_path: statements 7978  missing NNNN  coverage NN.NN%
```

**The denominator, 7,978, is the check.** A different denominator means the module list moved and every figure below it is against a different gate. `missing` is a question, not a defect — see the Gate 2 ratchet paragraph.

**If the output contains `label(s) failed under coverage:`, the figures are invalid.** Fix the failure and re-run; do not record the number. **PREDICTED, NOT OBSERVED:** the most likely cause on a fresh container is a missing `hypothesis`, which fails the two `test_property_*.py` modules at import and inflates `missing` by about 61.

- [ ] **Step 5: Record it**

Write the run's full tail to `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/<session>/scratchpad/2a7-baseline.txt`. Nothing is committed by this task.

---

## Task 2: Measure the variance, attribute it, and decide the CI shape

The spec requires the floor be "justified by per-file attribution, not picked". This task produces that attribution, and it decides between Task 7 and Task 7a.

**Files:** none modified. Produces measurements.

**Interfaces:**
- Consumes: Task 1's container.
- Produces: `runs[]` (ten `missing` counts), `max(runs)` — the floor's value — the per-line diff between the best and worst runs, and a ruling on the isolation question.

- [ ] **Step 1: Ten unmodified runs**

```bash
C=dispatcharr-testrunner-2a7
for i in $(seq 1 10); do
  docker exec "$C" bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
    bash scripts/coverage_live_path.sh' > /tmp/2a7-run-$i.txt 2>&1
  echo "run $i rc=$? $(grep -h 'statements 7' /tmp/2a7-run-$i.txt | tail -1)"
  docker cp "$C":/tmp/dispatcharr-coverage-live-path/live-path.json /tmp/2a7-json-$i.json
done
```

Note the `rc=$?` is read directly, not through a pipe — a non-zero exit does not survive one. Discard and re-take any run whose output contains `label(s) failed under coverage:`.

- [ ] **Step 2: Tabulate**

Record all ten `missing` values, their min, median and max, and `max − min`. **Expected shape, PREDICTED, NOT OBSERVED:** two clusters roughly 56 apart with a within-cluster spread under 10, giving `max − min` around 60-70. A single tight cluster is a finding — say so and continue.

- [ ] **Step 3: Attribute the spread per file, and then per line**

```bash
python3 - <<'PY'
import json, glob
runs = {p: json.load(open(p)) for p in sorted(glob.glob('/tmp/2a7-json-*.json'))}
tot = {p: d['totals']['missing_lines'] for p, d in runs.items()}
best, worst = min(tot, key=tot.get), max(tot, key=tot.get)
print('best', best, tot[best], '| worst', worst, tot[worst], '| spread', tot[worst]-tot[best])
for f in sorted(runs[best]['files']):
    a = runs[best]['files'][f]['summary']['missing_lines']
    b = runs[worst]['files'][f]['summary']['missing_lines']
    if a != b:
        print(f'{b-a:+5d}  {f}')
        sa = set(runs[best]['files'][f]['missing_lines'])
        sb = set(runs[worst]['files'][f]['missing_lines'])
        print('        only-missed-in-worst:', sorted(sb - sa))
        print('        only-missed-in-best :', sorted(sa - sb))
PY
```

The per-line lists are the deliverable. Compare them against the block the spec and #239 name — `channel_service.py` 28-49, 575-601, 971-989 and `server.py` 252, 261, 359-426, 888, 1259-1260, 1802-1803, 2010-2042. **If the moving lines are that block, the finding is confirmed and reproduced rather than inherited, which is what the spec asks 2a-7 to do. If they are somewhere else, that is a new finding — report it before proceeding.**

- [ ] **Step 4: The isolation experiment**

```bash
C=dispatcharr-testrunner-2a7
for i in 1 2 3 4 5; do
  docker exec "$C" bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
    rm -rf /tmp/iso && COVERAGE_LIVE_PATH_DATA_DIR=/tmp/iso \
    bash scripts/coverage_live_path.sh --label apps.proxy.live_proxy.tests >/dev/null 2>&1 && \
    COVERAGE_LIVE_PATH_DATA_DIR=/tmp/iso bash scripts/coverage_live_path.sh --report' \
    2>&1 | tail -2
done
```

For each of the five, extract `channel_service.py`'s missing-line set and check whether lines 28-49 are covered. **The question is binary: is the block 64/64 in all five isolated runs?**

- [ ] **Step 5: Rule**

Write the ruling into the scratchpad and into the eventual PR description:

- **All five isolated runs cover the block, and the full-script runs flap** ⇒ the three-label sequence is the cause; CI's per-label matrix would not reproduce it. **Do Task 7a instead of Task 7.**
- **The block flaps in isolation too** ⇒ the relay's own cleanup thread is the cause, uncontrollable from a test. **Do Task 7; drop Task 7a.**
- **Anything else** — report it and stop for a decision rather than choosing.

Do not proceed to Task 5 until this is ruled.

---

## Task 3: Parity-matrix row 29 — the buffering detector is inert on Proxy and Redirect

An obligation **inherited from 2a-4**, which found the behaviour, wrote a test that asserts it, and recorded in its own PR body that the row must be added by 2a-7 because bumping `HIGHEST_ROW_ID` against several in-flight PRs was not its to do. It is named as inherited here, not absorbed.

**Files:**
- Modify: `docs/relay-parity-matrix.md` (add row 29)
- Modify: `e2e/tests/guards/parity-matrix.ts` (`HIGHEST_ROW_ID` 28 → 29)
- Modify: `apps/proxy/live_proxy/tests/test_manager_connection_failover.py` (docstring only)

**Interfaces:**
- Consumes: 2a-4's `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::ConnectionFailoverTests::test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats`, which already sets `buffering_speed` to the API maximum and asserts `ffmpeg_speed` never appears, `state` never becomes `buffering`, and no `channel_buffering` event is written.
- Produces: row 29, pinned; `HIGHEST_ROW_ID = 29`.

- [ ] **Step 1: Break-check the existing test BEFORE citing it**

The row will claim the threshold is inert on the Proxy profile. Confirm the test catches a violation of that claim rather than merely coexisting with it. The lever must break the *mechanism* — make a Proxy-profile channel report an ffmpeg speed:

In `apps/proxy/live_proxy/input/manager.py`, find the successful-connect path of `_establish_http_connection` and insert, as the last statement of the success branch:

```python
        self._update_ffmpeg_stats_in_redis(0.5, None, None, None)  # BREAK CHECK
```

- [ ] **Step 2: Confirm the break applied**

```bash
grep -n "BREAK CHECK" apps/proxy/live_proxy/input/manager.py
sed -n "$(grep -n 'BREAK CHECK' apps/proxy/live_proxy/input/manager.py | cut -d: -f1),+1p" \
  apps/proxy/live_proxy/input/manager.py
```

Expected: the inserted line printed back. **A break check that prints nothing here is not a break check** — a green run after an unapplied patch was nearly reported as "cannot reproduce" earlier in this stage.

- [ ] **Step 3: Run the test three times and record what it says**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  for i in 1 2 3; do python manage.py test --keepdb \
  apps.proxy.live_proxy.tests.test_manager_connection_failover.ConnectionFailoverTests.test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats 2>&1 | tail -4; done'
```

**PREDICTED, NOT OBSERVED:** three failures reading approximately

```
AssertionError: 'ffmpeg_speed' unexpectedly found in {...} : the Proxy profile reported an ffmpeg speed; there is no ffmpeg
```

**Quote what you actually see, not this.** If fewer than three of three go red, the pin is weaker than the row would claim — do not cite it; write a stronger assertion into the test and break-check that instead.

- [ ] **Step 4: Revert the break and confirm green**

```bash
git checkout -- apps/proxy/live_proxy/input/manager.py
grep -c "BREAK CHECK" apps/proxy/live_proxy/input/manager.py   # expect 0
```

Re-run the test once; expect `OK`.

- [ ] **Step 5: Add row 29**

Append to `docs/relay-parity-matrix.md`, immediately before `<!-- end of matrix -->`, matching the surrounding rows' exact column shape:

```markdown
| 29 | The buffering failover detector is ffmpeg-exclusive: on the Proxy and Redirect Stream Profiles `buffering_speed` and `buffering_timeout` are read and then never consulted — no `ffmpeg_speed` is ever written, `state` never becomes `buffering`, and no `channel_buffering` event is raised, however far below the threshold the upstream runs | `apps/proxy/live_proxy/input/manager.py:1092` (`_update_ffmpeg_stats_in_redis` is called only from `_parse_ffmpeg_stats`), `apps/proxy/live_proxy/input/manager.py:1122` (the buffering comparison, in the same function), reached only from the stderr reader a transcode profile has | `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::ConnectionFailoverTests::test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats` | Found by 2a-4, which wrote the test and recorded that the row was 2a-7's to add; inherited here rather than absorbed. Externally observable — an operator who raises `buffering_speed` on a Proxy channel gets no failover and no indication that the setting did nothing, and nothing in the UI says so. D5 is strict parity, so the Go relay reproduces the inertness. |
```

Verify the `Source` line numbers against the tree before committing — they drift, and the guard checks that each citation resolves.

- [ ] **Step 6: Raise `HIGHEST_ROW_ID`**

In `e2e/tests/guards/parity-matrix.ts`, change `export const HIGHEST_ROW_ID = 28;` to `= 29;`. (It is 28 on the stacked branches; if the rebase left it at 27, the 2a-2..2a-6 stack is incomplete — stop.)

- [ ] **Step 7: Update the cited test's docstring**

In `test_manager_connection_failover.py`, replace the docstring's opening claim `Closes no matrix row, and is here for two reasons.` with:

```
        Pins matrix row 29 (added by 2a-7), and is here for two reasons.
```

- [ ] **Step 8: A readability edit is still an edit — re-break-check**

Repeat Steps 1-4 exactly. The docstring change cannot alter behaviour, and the rule exists because a cosmetic fix to a failure message inverted a pin earlier in this stage and was caught only by re-breaking it. Three reds, then revert, then green.

- [ ] **Step 9: Run the guard**

```bash
cd e2e && npx playwright test tests/guards/parity-matrix.spec.ts --reporter=list 2>&1 | tail -20
```

Expected: all seven guard tests pass, and the summary line reads `29 rows — <n> pinned, <m> owed, 2 white-box-only` with `<m>` unchanged by this task.

- [ ] **Step 10: Commit**

```bash
git add docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts \
        apps/proxy/live_proxy/tests/test_manager_connection_failover.py
```

Then, in a separate call, write the message to a file and:

```bash
git commit -F /tmp/2a7-msg-row29.txt
```

Message body: `docs(phase2): parity row 29 — the buffering detector is inert on Proxy and Redirect`, plus the inheritance note and the observed break-check text.

---

## Task 4: Parity-matrix row 30 — a rejected credential 401s, a declined one falls through

The second inherited obligation. 2a-5 documented `_drf_user`'s two-way disposition in a test docstring as a porting hazard, but no row and no test pin it. **A hazard recorded in a docstring is not pinned**; a port that flattens both cases to "anonymous" turns a rejected credential into a successful anonymous tune of any ordinary channel, and nothing in the suite goes red.

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py`
- Modify: `docs/relay-parity-matrix.md` (add row 30)
- Modify: `e2e/tests/guards/parity-matrix.ts` (`HIGHEST_ROW_ID` 29 → 30)

**Interfaces:**
- Consumes: `apps/proxy/authorize.py:227-265` (`_drf_user`) — `except AuthenticationFailed: raise AuthorizeDenied(401, "Invalid credentials")` versus `except APIException: return None` and the no-match fall-through to `return None`. The authenticator set is `(JWTAuthentication, ApiKeyAuthentication, QueryParamJWTAuthentication)` at `apps/proxy/authorize.py:93-97`.
- Consumes: the harness base class the sibling PRs use — `RelayHarnessTestCase` from `apps/proxy/live_proxy/tests/harness/`, with `self.make_channel(...)` and `self.tuned(channel)`. Read `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py` (2a-5) for the exact import path and the request idiom before writing this file; that module already drives `/proxy/ts/stream/<uuid>` over HTTP with headers.
- Produces: row 30, pinned; `HIGHEST_ROW_ID = 30`.

- [ ] **Step 1: Write the failing test**

Create `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py`. Match 2a-5's imports for the harness base class and helpers — read `test_authorize_matrix_over_http.py` and copy its header rather than inventing one.

```python
"""Row 30: a credential an authenticator REJECTS is 401; one it DECLINES is anonymous.

`_drf_user` (apps/proxy/authorize.py:252-265) has two exits that a porter reads
as one. `AuthenticationFailed` -- raised by JWTAuthentication for a malformed or
unverifiable Bearer token, and by ApiKeyAuthentication for an unknown key --
becomes AuthorizeDenied(401). Every other outcome, including "no credential was
presented at all", returns None and the caller falls through to the anonymous
principal, which is still allowed to stream an ordinary channel by UUID.

A Go port that flattens both to "anonymous" does not fail any test in this
suite without this one, and the failure it introduces is silent: a request
carrying a credential the control plane rejected streams anyway.

The two requests below differ in exactly one thing -- whether an Authorization
header is present -- and they must get different status codes.
"""
```

The two tests, inside one `class CredentialDispositionTests(RelayHarnessTestCase):`

```python
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
            "200 the request streamed as anonymous, which is the flattening "
            "row 30 exists to catch",
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

Import `TS_PACKET_SIZE` from wherever `test_manager_connection_failover.py` imports it; do not re-declare it.

- [ ] **Step 2: Run it and watch it pass**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  python manage.py test --keepdb \
  apps.proxy.live_proxy.tests.test_authorize_credential_disposition -v2 2>&1 | tail -15'
```

Expected: `OK` for both. This is a **characterization** test of existing behaviour, so passing first time is correct — which is exactly why Step 3 is not optional.

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
sed -n "$(grep -n 'BREAK CHECK' apps/proxy/authorize.py | cut -d: -f1),+1p" apps/proxy/authorize.py
```

Expected: the `return None  # BREAK CHECK` line printed back.

- [ ] **Step 5: Three consecutive runs, all red**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  for i in 1 2 3; do python manage.py test --keepdb \
  apps.proxy.live_proxy.tests.test_authorize_credential_disposition.CredentialDispositionTests.test_a_rejected_bearer_token_is_refused_with_401 \
  2>&1 | tail -5; done'
```

**PREDICTED, NOT OBSERVED:**

```
AssertionError: 200 != 401 : a credential the JWT authenticator rejected did not 401; ...
```

Quote the real text. If the observed status is neither 200 nor 401 — a 403, say — the flattening reaches a different refusal and the test's message needs rewording to match what actually happens; reword it and repeat from Step 3.

- [ ] **Step 6: Revert and confirm green**

```bash
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

Expected: seven passes and `30 rows — <n> pinned, <m> owed, 2 white-box-only`.

**Note on the guard's PR vocabulary:** `PRS` in `e2e/tests/guards/parity-matrix.ts` is `['2a-3','2a-4','2a-5','2a-6','2b-3']` — **`2a-7` is not in it.** Both new rows are pinned with real test references, so no `owed: 2a-7` marker is needed and `PRS` does not change. **If a later revision of this plan ever needs to mark a row `owed: 2a-7`, `PRS` must gain it in the same diff** or the guard fails the pin check naming the legal ids.

- [ ] **Step 9: Run the whole package (the edit hook does this too)**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  python manage.py test --keepdb apps.proxy.live_proxy.tests 2>&1 | tail -5'
```

Expected: `OK`, with the test count two higher than before this task.

- [ ] **Step 10: Commit** (stage and commit in separate calls, message via `-F`)

---

## Task 5: `--gate` and `--write-floor` in `scripts/coverage_live_path.sh`

**Files:**
- Modify: `scripts/coverage_live_path.sh`
- Create: `scripts/coverage_live_path.floor` (placeholder value in this task; Task 7 writes the real one)

**Interfaces:**
- Consumes: the script's existing `report()`, which prints `coverage_live_path: statements N  missing M  coverage P%` and writes `$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json`; and `SHAPE_ID`, currently `per-label/v2-${COVERAGE_CORE}`.
- Produces: `scripts/coverage_live_path.sh --gate` (exit 0 pass, 1 fail) and `--write-floor`; the floor file's five-key format, which Task 6's CI job and Task 8's docs both refer to.

- [ ] **Step 1: Create the floor file with the format and a placeholder**

`scripts/coverage_live_path.floor`:

```
# Gate 2's ratchet floor. See docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
# (Stage 2a > Gate 2) and docs/superpowers/plans/2026-09-10-phase2-2a7-coverage-gate.md.
#
# `missing` is the ratchet -- a maximum, not a target. It is set from the WORST of ten
# runs on the tree that earned it, which is why this gate carries no separate tolerance
# parameter: the spread is already inside the number. A percentage appears here only as
# a derived convenience; the spec's Gate 2 section records that percentages are what hid
# the error it exists to correct.
#
# `shape` and `statements` are EQUALITY checks, not comparisons. A different measurement
# shape or a different module list makes the two numbers incomparable rather than better
# or worse, and the gate says so instead of ratcheting.
#
# Written by:  scripts/coverage_live_path.sh --write-floor
# Enforced by: scripts/coverage_live_path.sh --gate  (backend-tests.yml, job coverage-gate)
shape=per-label/v2-sysmon
statements=7978
missing=99999
percent=0.00
measured=PLACEHOLDER
```

- [ ] **Step 2: Add the two modes to the script**

Insert before the closing `case` block, and add the two branches to the `case` itself.

```bash
FLOOR_FILE="$REPO_ROOT/scripts/coverage_live_path.floor"

# Reads the last figures report() printed, from the JSON it wrote. Kept separate
# from report() so --gate and --write-floor cannot drift from what a bare run
# prints -- they read the same artefact rather than re-deriving it.
read_totals() {
  python - "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" <<'PY'
import json, sys
t = json.load(open(sys.argv[1]))["totals"]
print(t["num_statements"], t["missing_lines"], f'{t["percent_covered"]:.2f}')
PY
}

floor_value() { grep -E "^$1=" "$FLOOR_FILE" | head -1 | cut -d= -f2-; }

gate() {
  local stmts missing pct
  read -r stmts missing pct < <(read_totals) || return 1
  local f_shape f_stmts f_missing
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
    echo "coverage_live_path: the floor is the worst of ten runs on the tree that set it, so this is" >&2
    echo "coverage_live_path: outside the measured spread and is a finding to investigate, not noise." >&2
    echo "coverage_live_path: attribute it per file before widening anything: diff live-path.json's" >&2
    echo "coverage_live_path: per-file missing_lines against the previous run's." >&2
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
    echo "coverage_live_path: a floor may rise in the PR that earns the rise and may never simply be" >&2
    echo "coverage_live_path: edited down. If this is a deliberate re-baseline (the module list moved," >&2
    echo "coverage_live_path: or the shape changed), set COVERAGE_LIVE_PATH_ALLOW_REGRESSION=1 and say" >&2
    echo "coverage_live_path: why in the PR description." >&2
    return 1
  fi
  python - "$FLOOR_FILE" "$SHAPE_ID" "$stmts" "$missing" "$pct" <<'PY'
import re, sys, datetime
path, shape, stmts, missing, pct = sys.argv[1:6]
src = open(path).read()
for k, v in (("shape", shape), ("statements", stmts), ("missing", missing),
             ("percent", pct), ("measured", datetime.date.today().isoformat())):
    src = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", src)
open(path, "w").write(src)
print(f"coverage_live_path: floor written -- statements {stmts} missing {missing} coverage {pct}%")
PY
}
```

And in the `case`:

```bash
  --gate)
    rm -rf "$COVERAGE_LIVE_PATH_DATA_DIR"; mkdir -p "$SHAPE_DIR"
    failed=()
    for label in "${LABELS[@]}"; do run_label "$label" || failed+=("$label"); done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "coverage_live_path: label(s) failed under coverage: ${failed[*]}" >&2
      echo "coverage_live_path: NOT GATING on an under-run suite -- a failed label inflates 'missing'" >&2
      echo "coverage_live_path: and moves it the way a regression moves. Fix the failure and re-run." >&2
      exit 1
    fi
    report >/dev/null || exit 1
    gate; exit $?
    ;;
  --write-floor)
    rm -rf "$COVERAGE_LIVE_PATH_DATA_DIR"; mkdir -p "$SHAPE_DIR"
    failed=()
    for label in "${LABELS[@]}"; do run_label "$label" || failed+=("$label"); done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "coverage_live_path: label(s) failed under coverage: ${failed[*]} -- not writing a floor." >&2
      exit 1
    fi
    report || exit 1
    write_floor; exit $?
    ;;
```

Update the `usage:` string in the final `*)` branch to `[--label <label> | --report | --gate | --write-floor]`.

**Note the failed-label handling is stricter in these two modes than in the default one.** The default run reports the invalid figures after announcing them, so a human can see what happened; `--gate` and `--write-floor` refuse to produce a verdict at all. A gate that passes on an under-run suite is worse than a gate that errors.

- [ ] **Step 3: Prove `--gate` fails when it should**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  sed -i "s/^missing=99999/missing=1/" scripts/coverage_live_path.floor 2>/dev/null; \
  bash scripts/coverage_live_path.sh --gate; echo "rc=$?"' 2>&1 | tail -8
```

The repo is bind-mounted read-only, so run this against a writable copy instead: `docker cp` the tree, or edit the floor on the host and re-run. **PREDICTED, NOT OBSERVED:**

```
coverage_live_path: GATE FAILED -- NNNN more missed statements than the floor.
rc=1
```

- [ ] **Step 4: Prove `--gate` passes when it should** — restore `missing=99999`, re-run, expect `rc=0`.

- [ ] **Step 5: Prove the denominator check fires** — set `statements=7977` in the floor, re-run `--gate`. **PREDICTED, NOT OBSERVED:** `the denominator moved: floor 7977, this run 7978.` and `rc=1`.

- [ ] **Step 6: Prove `--write-floor` refuses to write worse** — set `missing=100`, run `--write-floor`. **PREDICTED, NOT OBSERVED:** `refusing to write a WORSE floor (100 -> NNNN).` and `rc=1`. Then set `COVERAGE_LIVE_PATH_ALLOW_REGRESSION=1` and confirm it writes.

- [ ] **Step 7: Restore the placeholder floor and commit both files**

---

## Task 6: Wire the gate into `backend-tests.yml`

**Files:**
- Modify: `.github/workflows/backend-tests.yml`

**Interfaces:**
- Consumes: `scripts/ci_bootstrap_backend.sh`'s `CI_BACKEND_RUNNER` hook (used already by `metrics.yml:168`, which is the working precedent for running coverage over the backend suite in this repo); `scripts/coverage_live_path.sh --gate` from Task 5; `plan.outputs.has_tests` and `plan.outputs.base_image` from the existing `plan` job.
- Produces: a job named `coverage-gate`, required through the existing `Backend result` aggregate.

**Why one job and not the per-label matrix the spec describes.** This is a **contradiction with the spec, taken deliberately**, and Task 8 records it:

1. **The existing matrix is diff-gated.** `plan` selects labels from changed paths; a PR touching only `apps/epg/` never runs `apps.proxy.live_proxy.tests`, and a docs-only PR skips the matrix before expansion. The gate must measure the *same three labels every time* or the floor is not comparable between runs. Piggybacking would need the three gate labels force-added to every matrix expansion — which changes what `Backend result` means for every other PR.
2. **`coverage_live_path.sh`'s shape guard stamps the shape it produced.** Running the three labels in three separate containers and combining artifacts is a *different shape* from the script's own, and a floor written locally under one shape must not be compared against a CI number produced under another — which is the exact failure the shape guard exists to prevent. Splitting across containers means extending the stamp mechanism across an artifact boundary it has never crossed.
3. The script already gives each label **its own process**, which is the spec's stated reason for per-label ("CI never runs the suite in one process"). Per-*container* adds isolation the spec asks for for a second reason — daemon-thread credit — and Task 2 measures whether that second reason bites. If it does, **Task 7a** takes the split.

- [ ] **Step 1: Add the job**

Insert between the `test` job and `backend-result`:

```yaml
  # Gate 2 (Phase 2 spec, Stage 2a). One job, one container, three labels in three
  # processes -- byte for byte the shape scripts/coverage_live_path.sh stamps, so a
  # floor measured locally and a number measured here are the same kind of quantity.
  # Deliberately NOT folded into the `test` matrix above: that matrix is diff-gated and
  # would measure a different label set on every PR, and the floor would compare numbers
  # that are not comparable. See docs/superpowers/plans/2026-09-10-phase2-2a7-coverage-gate.md,
  # Task 6, for the full argument and for what would change this decision.
  coverage-gate:
    name: Coverage gate
    needs: plan
    if: needs.plan.outputs.has_tests == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 30
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
      # metrics.yml sets this for the same reason: it picks up `coverage` (and
      # `hypothesis`) from uv.lock before the base image is next rebuilt. Both are in
      # pyproject.toml's MAIN dependency list, not a dev group, precisely because CI
      # installs with --no-dev.
      SYNC_PYTHON_DEPS: 'true'
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false
          fetch-depth: 0

      - name: Verify the measurement can be trusted
        run: |
          set -euo pipefail
          export PATH="/dispatcharrpy/bin:$PATH"
          python -c "import coverage, hypothesis; print(coverage.__version__, hypothesis.__version__)"

      - name: Run Gate 2
        env:
          GITHUB_WORKSPACE: ${{ github.workspace }}
          CI_BACKEND_RUNNER: bash scripts/coverage_live_path.sh --gate
        run: bash scripts/ci_bootstrap_backend.sh

      - name: Refuse a floor edited downward
        if: always()
        run: |
          set -euo pipefail
          git fetch --depth=1 origin "${GITHUB_BASE_REF:-main}"
          OLD=$(git show "origin/${GITHUB_BASE_REF:-main}:scripts/coverage_live_path.floor" \
                 2>/dev/null | grep -E '^missing=' | cut -d= -f2 || echo "")
          NEW=$(grep -E '^missing=' scripts/coverage_live_path.floor | cut -d= -f2)
          if [ -z "$OLD" ]; then echo "no floor on the base ref; nothing to compare"; exit 0; fi
          echo "floor: base=$OLD head=$NEW"
          if [ "$NEW" -gt "$OLD" ]; then
            echo "The floor was raised ($OLD -> $NEW): more missed statements are now permitted."
            echo "A floor may rise only in a PR that earns and explains the rise."
            exit 1
          fi
```

The `Verify the measurement can be trusted` step exists because an import failure in `hypothesis` does not fail a label loudly — it fails two test modules, the label reports errors, and 61 statements are silently counted as missed. That moves the number the way a regression moves.

**Note:** the "Refuse a floor edited downward" step is deliberately worded around `missing`, where *lower is better* — so a **raised** `missing` is the regression. Read it twice; the polarity is the opposite of a coverage percentage's.

- [ ] **Step 2: Extend `Backend result`**

Change `needs: [plan, test]` to `needs: [plan, test, coverage-gate]`, add to the step's `env:`

```yaml
          GATE_RESULT: ${{ needs.coverage-gate.result }}
```

and insert, before the final `echo "Backend suite passed."`:

```bash
          if [ "$GATE_RESULT" != "success" ]; then
            echo "Coverage gate was required and did not succeed."
            exit 1
          fi
```

Also extend the first `echo` to print `gate=$GATE_RESULT`. The existing three-branch logic is preserved exactly: a `plan` failure fails, `has_tests != true` passes (both `test` and `coverage-gate` skip together, legitimately), and otherwise both must be `success`.

- [ ] **Step 3: zizmor must find nothing**

The edit hook runs zizmor on this file automatically. If it is not available, run it by hand at the version `.github/workflows/actions-lint.yml` pins:

```bash
zizmor .github/workflows/backend-tests.yml
```

Expected: `No findings`. Any finding blocks — the workflows are at zero and that is a ratchet.

- [ ] **Step 4: actionlint**

```bash
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest -color .github/workflows/backend-tests.yml
```

Expected: no output.

- [ ] **Step 5: Commit**

---

## Task 7: Measure the gated tree and write the real floor

**Run this only after Tasks 3 and 4**, which add tests and therefore change the number. Run it after Tasks 5 and 6 so the mechanism being measured is the shipped one.

**Files:**
- Modify: `scripts/coverage_live_path.floor`

**Interfaces:**
- Consumes: Task 2's ruling and Task 5's `--write-floor`.
- Produces: the committed floor.

- [ ] **Step 1: Ten runs on the final tree**

Repeat Task 2 Step 1 verbatim against the branch with Tasks 3-6 committed. Discard any run announcing a failed label.

- [ ] **Step 2: Take the worst**

Record all ten. The floor's `missing` is `max(runs)`. Record the median too — the PR description states **how much headroom the worst-run floor gives away**, as `max − median`.

- [ ] **Step 3: Attribute, again**

Re-run Task 2 Step 3's per-file/per-line diff on the final tree. **The PR description carries this table.** The spec requires the floor be justified by per-file attribution and that a later widening make the same case; a floor with no attribution beside it cannot be argued with later.

- [ ] **Step 4: Write it**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  bash scripts/coverage_live_path.sh --write-floor' 2>&1 | tail -5
```

The repo mount is read-only; write the floor on the host instead, by hand, from the worst run's figures, in exactly the format Task 5 Step 1 defines. Then verify:

```bash
cat scripts/coverage_live_path.floor
```

`missing` must equal `max(runs)` from Step 2, not the run `--write-floor` happened to take.

- [ ] **Step 5: Prove the committed floor passes**

Run `--gate` three times against the committed floor. All three must exit 0. **If any fails, the floor is not the worst run** — go back to Step 2.

- [ ] **Step 6: Commit**

---

## Task 7a: CONTINGENCY — per-label containers, if and only if Task 2 Step 5 ruled for isolation

**Do not do this task unless Task 2 Step 5 ruled that the 64-statement block is deterministic in isolation and flaps only in the three-label sequence.** If that is the ruling, the flapping is an artefact of the measurement harness, CI's shape would not reproduce it, and a much tighter floor is available.

**Files:**
- Modify: `.github/workflows/backend-tests.yml` (replace Task 6's single job)
- Modify: `scripts/coverage_live_path.sh` (accept externally-supplied data files)

- [ ] **Step 1: Teach `report()` to accept data from another container**

The shape stamp is per-label already (`run_label` writes `$SHAPE_DIR/<label>.shape`). Add a `--combine-from <dir>` mode that copies `.coverage.*` and `*.shape` from a directory into `$COVERAGE_LIVE_PATH_DATA_DIR` before reporting, so the existing stamp check runs unchanged across the artifact boundary. Bump `SHAPE_ID` to `per-container/v1-${COVERAGE_CORE}` — **a different shape is a different number and the guard must say so**, which is the whole reason the stamp exists.

- [ ] **Step 2: Three matrix jobs plus a combine job**

Replace `coverage-gate` with a `coverage-label` job whose matrix is the three gate labels — hard-coded, **not** `plan.outputs.labels`, for the reason in Task 6 — each running `CI_BACKEND_RUNNER: bash scripts/coverage_live_path.sh --label ${{ matrix.label }}` and uploading `/tmp/dispatcharr-coverage-live-path` with `actions/upload-artifact`; then a `coverage-gate` job that downloads all three and runs `--combine-from`. Pin `actions/upload-artifact` and `actions/download-artifact` by full 40-character SHA with the version as a trailing comment, resolved with `gh api repos/actions/upload-artifact/commits/<tag> --jq .sha` — never hand-typed.

- [ ] **Step 3: Re-measure ten times under the new shape and re-run Task 7 entirely.** A floor measured under `per-label/v2` is not comparable with a number measured under `per-container/v1`; the guard will refuse it, correctly.

- [ ] **Step 4: State the new spread in the PR description** and, if it is genuinely tight, say by how much the floor is tighter than the worst-run figure Task 7 would have produced. **That number is the whole justification for this task's existence** — if it is not materially tighter, revert to Task 6 rather than carrying two shapes.

---

## Task 8: The record — spec amendment, `CLAUDE.md`, matrix completeness, metrics

This task is what turns "2a did not meet its gate" from a thing a reader has to infer into a thing the repository says.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`
- Modify: `CLAUDE.md`
- Verify: `docs/relay-parity-matrix.md`
- Modify: `metrics/curated/` (milestones, defect ledger)

- [ ] **Step 1: Verify the matrix is complete and consistent**

```bash
grep -o "owed: [0-9a-z-]*" docs/relay-parity-matrix.md | sort | uniq -c
```

Expected: **exactly one owed marker, `owed: 2b-3`** (plus the legend's empty `owed: ` example line, which is not a row). Every 2a-3/2a-4/2a-5/2a-6 marker must be gone — all four merged before this PR, each removing its own. **If any survive, the stack did not merge cleanly and the rebase dropped an edit** — find it before proceeding; a surviving marker means a row nobody pinned.

```bash
cd e2e && npx playwright test tests/guards/ --reporter=list 2>&1 | tail -20
```

Expected: every guard test green, and `30 rows — 29 pinned, 1 owed, 2 white-box-only`. `GATE_1_CLOSED` stays `false` — **row 18 is 2b-3's and 2a-7 does not flip it.** The guard asserts "at least one row is still owed" while it is `false`, so flipping it here would fail.

- [ ] **Step 2: Amend the spec's Gate 2 section**

Append, in the spec's own idiom (superseded claims struck in place, never deleted):

```markdown
**MEASURED AND CLOSED, 2026-09-10, by 2a-7. Stage 2a does not reach 80%, and the
requirement is reassigned rather than lowered.** With 2a-3 through 2a-6 landed, the
measured figure is <MISSING> missing of 7,978, <PCT>%, against an allowance of 1,595.
The shortfall is <N> statements. The full arithmetic, with provenance on every term, is
in `docs/superpowers/plans/2026-09-10-phase2-2a7-coverage-gate.md` § THE GATE DECISION.

Three corrections that section makes to this one, each of the family this section
already names:

1. **`+ http_streamer.py's 101` is spent.** 2a-4 covered 74 of that file as a side
   effect (#236: 101 -> 27), so the bracket row that closes the gate by +91 no longer
   exists. This is the fourth instance of the already-banked shape, and the first to
   have been carried in a *conclusion* rather than in a supply table.
2. **`_handle_bsf_error` is 35 statements and is NOT dead** — it is reached whenever
   ffmpeg's stderr carries `aac_adtstoasc ... is not supported by the bitstream filter`
   (`output/fmp4/manager.py:373`), which 2a-2's PATH stand-in can print on demand.
3. **Excluding every provably-dead statement anyone has found moves the gate by about
   1.4 percentage points** (~148 statements: `_cleanup_local_resources` 62,
   `_check_orphaned_channels` 24, #231's `input/manager.py` cluster ~62), against an
   eight-point gap. Denominator surgery cannot reach this gate, so it is not attempted,
   and the dead code is left in the denominator to be *deleted* by 2b/2d, which raises
   the floor for free.

**The ratchet carries no tolerance parameter, and the tolerance paragraph above is
amended rather than met.** The floor's `missing` is set from the WORST of ten runs on
the tree it gates, which absorbs the measured spread with one fewer knob and identical
exposure. All three of that paragraph's constraints hold: sized to the measured residual
on the gated tree, justified by the per-file attribution in 2a-7's PR description, and a
movement outside it -- a run worse than the worst of ten -- is a finding. The argument
for preferring it: a tolerance is a number nobody re-derives, while a floor is one the
monotonicity check in `backend-tests.yml` compares against `origin/main` on every run.

**The gate runs as ONE job in one container, not in the per-label matrix this section
specifies.** `backend-tests.yml`'s matrix is diff-gated -- a PR touching only `apps/epg/`
never expands the three gate labels -- so the gate would measure a different label set on
every PR and the floor would compare quantities that are not comparable. The script
already gives each label its own process, which is this section's stated first reason for
per-label. Its second reason (daemon-thread credit) was measured by 2a-7 and <RULING>.
```

- [ ] **Step 3: Add `2b-4` to the spec's PR table, immediately after `2b-3`**

```markdown
| 2b-4 | `migration/phase2b-coverage-to-80` | Close the remaining <N>-statement shortfall to Gate 2's ≥80%. The supply, from § Gate 2's own pool table minus what 2a-3…2a-6 took: `input/manager.py` ~177-187, 2a-5's surfaces ~133, 2a-6's group residual 76-127, `server.py`'s expensive tail 146 (**a cost judgement, not a measurement** — ~28 `except Exception: logger.error(...)` arms needing fault injection), and the ~898-statement mid-sized pool no PR owns (`views.py`, `channel_status.py`, `client_manager.py`, `input/buffer.py`, `log_parsers.py`, `url_utils.py`). Deleting #230's and #231's dead code raises the floor for free and is in scope. | `scripts/coverage_live_path.sh --gate` green against a floor of ≤1,595 missing, and the floor file raised in this PR | 2a-7 |
```

**And amend D7 in the same edit** so the roll-call stays true: D7's "No PR in stage 2c may merge until both gates are green" is unchanged in force, but its owner for Gate 2 is now `2b-4`, not `2a-7`. **The requirement is retained, not weakened** — 2a-7 turns the ratchet on; it does not turn the blocker off. Add `2b-4` to `PRS` in `e2e/tests/guards/parity-matrix.ts` only if a matrix row ever gets an `owed: 2b-4` marker; none does today, so leave `PRS` alone.

- [ ] **Step 4: `CLAUDE.md` § Testing**

Add, after the coverage paragraph:

```markdown
**Gate 2 is a CI-enforced coverage ratchet on the relay's own modules.**
`scripts/coverage_live_path.sh` measures statement coverage over
`apps/proxy/live_proxy/**` plus the ten Phase 1 boundary modules — a 7,978-statement
denominator fixed by `scripts/coverage_live_path.coveragerc`, three Django labels in
three processes, `COVERAGE_CORE=sysmon` (the default C tracer drops every statement
executing after a `gevent.sleep()`, so a C-tracer figure is not comparable with a sysmon
one **in either direction**). `--gate` compares against `scripts/coverage_live_path.floor`
and exits 1 on a regression; `backend-tests.yml`'s `coverage-gate` job runs it and
`Backend result` requires it. **The floor's `missing` is set from the worst of ten runs,
so there is no tolerance parameter** — the measurement is bimodal, not noisy: a
64-statement teardown block (`channel_service.py` 28-49, 575-601, 971-989 and
`server.py`'s cleanup sweep) is covered 0/64 or 44-64/64 per run and never in between.
**A failed label invalidates a measurement rather than degrading it** — a tree missing
`hypothesis` reported 3,230 where the same tree with it reported 3,169, a 61-statement
inflation that moves the way a regression moves — so `--gate` refuses to produce a
verdict when any label fails. **Stage 2a ended at <PCT>%, not the spec's ≥80%**; the
shortfall is owned by `2b-4` and D7 still blocks every 2c PR until it closes.
```

Also correct, in the same edit, the existing sentence "`hypothesis` is a dev dependency" — it is in `pyproject.toml`'s **main** dependency list (`pyproject.toml:41-45`), deliberately, because CI installs with `--no-dev`.

- [ ] **Step 5: Metrics**

```bash
python3 -m metrics.build --validate-only
```

Expected: `ok: N metrics, M milestones, K defects`. Add a milestone for stage 2a's close carrying the measured percentage, and ledger entries for anything Tasks 2-4 found. The hook on `metrics/**` runs `scripts/run_metrics_tests.sh` automatically.

- [ ] **Step 6: Commit**

---

## Task 9: OPTIONAL, USER'S CALL — add `apps/proxy/utils.py` to the denominator

**Do not do this without the user's answer.** See § THE GATE DECISION's last subsection for the argument. If the answer is no, skip this task entirely; nothing else depends on it.

**Files:**
- Modify: `scripts/coverage_live_path.coveragerc`
- Modify: `scripts/coverage_live_path.sh` (`SHAPE_ID` v2 → v3)
- Modify: `scripts/coverage_live_path.floor`
- Modify: `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, `CLAUDE.md`

- [ ] **Step 1: Add the module**

In `scripts/coverage_live_path.coveragerc`'s `[report] include` list, after `apps/proxy/internal_base_url.py`:

```
    apps/proxy/utils.py
```

and extend the block comment above it:

```
# apps/proxy/utils.py is here because D4 makes the live half of
# get_user_active_connections part of the contract the Go relay reproduces. A module the
# port must reproduce belongs in the denominator of the gate that protects the port. It
# was outside the list through stage 2a, so work there earned nothing toward the gate;
# 2a-7 is the only moment in the stage where adding it invalidates no in-flight
# measurement, every sibling PR having already quoted its figures and merged.
```

- [ ] **Step 2: Bump the shape**

In `scripts/coverage_live_path.sh`, `SHAPE_ID="per-label/v3-${COVERAGE_CORE}"`, and extend the comment above it: the denominator changed, so a floor written under v2 must be refused rather than compared.

- [ ] **Step 3: Confirm the new denominator**

```bash
docker exec dispatcharr-testrunner-2a7 bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; cd /repo && \
  bash scripts/coverage_live_path.sh' 2>&1 | tail -3
```

**PREDICTED, NOT OBSERVED:** `statements 8238`. 7,978 + 260, the 260 measured statically for this plan at `e62ab428`. **If it is not 8,238, `utils.py` changed size or another module moved — find out which before continuing.**

- [ ] **Step 4: Redo Task 7 in full** — ten runs, worst-run floor, per-file attribution. The old floor is not comparable and `--gate` will say so.

- [ ] **Step 5: Update the spec, `CLAUDE.md` and the PR description** to say 8,238 everywhere 7,978 appeared, and to record that the headline percentage fell by roughly 0.2 points because `utils.py` sits below the tree's average — **and that the decision was taken on D4's contract argument, not on the arithmetic, precisely because the arithmetic pointed the other way.**

- [ ] **Step 6: Commit**

---

## Task 10: The PR description

**Files:** none in the repo. Write to a file and use `gh pr create --repo D10Scot/Dispatcharr --body-file`. **Do not open the PR** unless the orchestrator asks.

The description must carry, in this order:

1. **The gate decision** — the arithmetic table with provenance on every term, the recommendation, and what shipped. Lead with the fact that **stage 2a lands near 72%, not 80%**, and that the requirement moved to `2b-4` rather than being lowered. A reader must not have to infer it.
2. **The tolerance ruling** — worst-run floor, no tolerance parameter, the argument, and **the headroom it gives away** as `max − median` from Task 7 Step 2.
3. **Task 2's per-file/per-line attribution table**, and the isolation ruling.
4. **The two inherited rows**, named as inherited: row 29 from 2a-4, row 30 from 2a-5. Row 21's prose-only obligation was discharged by 2a-5 at `cbdc66c2` and is **not** 2a-7's — say so, so nobody looks for it.
5. **Every break check**, with the failure text **actually observed**, not this plan's predictions.
6. **The three spec contradictions** this PR takes deliberately: the CI shape (one job, not the per-label matrix), the tolerance (a floor, not a parameter), and the gate value (a ratchet at the measured level, with ≥80% reassigned).
7. **The corrections to sibling PRs and to the brief:** `http_streamer.py`'s 101 is spent; `_handle_bsf_error` is 35 statements and not dead; 2a-4's contribution is at least −74 and not −61; `hypothesis` is not a dev dependency.
8. **Timings** — how long `coverage-gate` adds to a CI run, measured, not estimated.

---

## Self-review notes

- **Spec coverage.** 2a-7's row names four deliverables: the floor file (Task 5, Task 7), the `backend-tests.yml` wiring (Task 6), the gate CI-blocking (Task 6 Step 2), and "green at ≥80%" (**not delivered** — Task 8 records why and reassigns it, which is the honest discharge of a requirement measurement shows is unreachable). The Gate 2 section's tolerance requirement is answered by the ruling in Task 7 and recorded in Task 8. The stage's two inherited obligations are Tasks 3 and 4. Matrix completeness is Task 8 Step 1.
- **Ordering constraints.** Task 2 must precede Task 5 (it decides Task 7 vs 7a). Tasks 3 and 4 must precede Task 7 (they change the number). Tasks 5 and 6 must precede Task 7 (the measured mechanism must be the shipped one). Task 9, if taken, invalidates Task 7 and repeats it.
- **What this plan does not do.** It does not widen any coverage PR's scope, does not exclude anything from the denominator, and does not delete dead code — all three are argued against in § THE GATE DECISION and left to `2b-4`.
