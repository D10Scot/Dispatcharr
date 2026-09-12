# Phase 2 PR 2b-4 — closing Gate 2's ≥80% floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take Gate 2's live-path statement coverage from ~75.2% to ≥80% and move `scripts/coverage_live_path.floor`'s `missing` to the number a fresh CI census earns, so D7 stops blocking stage 2c. This is the last PR of Phase 2b.

**Architecture:** There is no large uncovered block left to close. At the measurement this plan is scoped from, 1,997 missing statements sit in **926 contiguous blocks** (mean 2.2), 66% of them in blocks of one to three lines, 34% inside `except` handler bodies, and the largest single block in the whole denominator is 20 lines. A plan phrased "cover file X" therefore fails by construction. This plan is organised around **ten branch kinds** — recurring idioms, each closed by one test pattern applied repeatedly — and each task names the kind it closes, the statements it is estimated to buy, and a measurement checkpoint that says whether it bought them. Two CI censuses bracket the work: one to size the scope against an explicit decision rule (Task 2), one to earn the new floor (Task 13).

**Tech Stack:** Django `SimpleTestCase`/`TestCase`, `unittest.mock`, `responses`-free `requests.Session` patching, the 2a relay harness (`apps/proxy/live_proxy/tests/harness/`) where and only where real Redis is needed, `scripts/coverage_live_path.sh` + `scripts/coverage_live_path_isolated.sh` for measurement, `backend-tests.yml` for the two censuses.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — D7 (line 439), § Stage 2a › Gate 2 (line 949), the Stage 2b PR table's `2b-4` row (line 1660). Primary input: `docs/superpowers/analysis/2026-09-12-phase2-2b4-reachability.md` (the measured per-file reachability pass the `2b-4` row demands). Supporting: `scripts/coverage_live_path.floor`'s own "HOW TO MOVE THIS FLOOR", [#266](https://github.com/D10Scot/Dispatcharr/issues/266), [#259](https://github.com/D10Scot/Dispatcharr/issues/259) and `docs/superpowers/analysis/2026-09-12-issue-259-flake-diagnosis.md`.

**Branch:** `migration/phase2b-coverage-80`, cut from `main` **after 2b-3 has merged**. The `migration/**` prefix is load-bearing — it makes `e2e-tests.yml` run every Playwright project (CLAUDE.md § Full E2E runs).

---

## Global Constraints

Every task's requirements implicitly include this section.

1. **Compute the permitted-missing ceiling from the denominator you measure. Never copy a literal from this plan, the spec or the brief.** Three different numbers are in circulation and all three are stale: the spec says **1,595** (arithmetic on 7,978 statements), the reachability brief says **1,602** (arithmetic on 8,011), and the denominator at `04841a47` is already **8,046**, whose ceiling is **1,609**. It will move again when this PR relocates `_live_connections` (Task 1). The formula is fixed and the inputs are not:

   ```bash
   python3 -c "import math; S=8046; print(S - math.ceil(0.8 * S))"   # -> 1609
   ```

   Wherever this plan writes a ceiling or a shortfall it is a **prediction**, labelled as one. Task 2 replaces every one of them with a measurement, and every later task reads Task 2's number, not this plan's.

2. **The floor is measured where it is enforced: CI, never locally.** This is not advice, it is the thing that already went wrong once in this programme — the floor was first set from a correct 21-round *local* census whose maximum the very first CI run exceeded (`scripts/coverage_live_path.floor`, "WHY THIS REPLACES THE 2044 BELOW"). Local rounds are for **per-file attribution during development**; they never set a number that goes in the floor file or in the PR description.

3. **`COVERAGE_CORE=sysmon` is load-bearing and is set by the script itself** (`scripts/coverage_live_path.sh:58`). The default C tracer drops every statement executing after a `gevent.sleep()`, so a C-tracer figure is not comparable with a sysmon one **in either direction**. Never run `coverage` by hand against these modules without going through the script; a hand-rolled invocation produces a number that looks comparable and is not.

4. **One Django label per container.** Locally that is `scripts/coverage_live_path_isolated.sh`; in CI it is `backend-tests.yml`'s `coverage-label` matrix plus its `coverage-gate` combine job. Do not run the three labels in one container and quote the total.

5. **A failed label invalidates a measurement rather than degrading it.** A tree missing `hypothesis` reported 3,230 missing where the same tree with it reported 3,169 — a 61-statement inflation moving the way a *regression* moves. So: any round in which any label failed is **discarded, not averaged, not quoted, and never written into the floor**. Task 0 makes such a round announce itself instead of vanishing.

6. **Shape identity is `modules=` and `rcfile=`; `statements` is provenance; `missing` is the ratchet.** `modules` is a sha256[:12] of the sorted list of files in coverage's JSON `files` report; `rcfile` is a sha256[:12] of `scripts/coverage_live_path.coveragerc`'s raw bytes. Both are **equality** checks. `statements` is printed and never compared. **This PR must not edit `scripts/coverage_live_path.coveragerc`** — no `exclude_lines`, no `omit` narrowing, no new `include` entry. A coverage PR that reaches its number by changing the measurement's definition is exactly what the `rcfile=` hash was added to catch.

7. **Every new test file lives under a `tests/` directory**, which the rcfile omits (`omit = */tests/*`, rcfile lines 15-16 and 35-36). New test files therefore move neither `statements` nor `modules`. The only production-code edit in this PR is Task 1's relocation. **If you find yourself editing a production module to make it testable, stop and report** — that moves the denominator mid-campaign and invalidates Task 2's census.

8. **No dead-code deletion, no `exclude_lines`, and no `# pragma: no cover`.** All three are available levers and all three are declined. Deleting `D` always-missing statements buys only `≈ 0.8 D` of shortfall, because the denominator shrinks with it: `shortfall(D) = (M − D) − ((S − D) − ceil(0.8 × (S − D)))`. D5 and the spec hand dead-code deletion to stage 2d, not here.

   **The pragma deserves its own paragraph, because it is the one cheap lever nothing else in this plan or in Gate 2's machinery stops.** `scripts/coverage_live_path.coveragerc` declares **no `exclude_lines` key at all** (verified: `grep -c exclude_lines` → 0), so coverage's built-in default pragma exclusion is live. A single `# pragma: no cover` on a production line removes it from the numerator **and** the denominator — the same numeric effect as an `exclude_lines` entry, for one comment. And **both of Gate 2's shape checks are structurally blind to it**: `rcfile=` hashes `coverage_live_path.coveragerc`'s bytes, which a pragma does not touch, and `modules=` hashes the *list of files*, which a pragma does not change either. There are **zero** pragmas in the 38 in-scope modules today, so any that appear are this PR's. Adding one is forbidden here, and — unlike an rcfile edit — nothing downstream would catch it. Task 14 Step 5 makes its absence a piece of evidence rather than a promise.

9. **Two functions are forbidden targets, and this is not negotiable.** `server.py`'s `cleanup_task` (78 always-missing at the brief's measurement) ticks on its own interval and samples channels mid-shutdown: chasing it damages the measurement while appearing to improve it, and it is the single largest source of run-to-run flap. `server.py`'s `_cleanup_local_resources` (61) is structurally unreachable ([#230](https://github.com/D10Scot/Dispatcharr/issues/230)) — its non-owner arm sits under `if self.am_i_owner(...)`. Together they are 139 statements, **not** the 222 the spec quotes. Do not write a test that reaches either.

10. **Flappy lines are not headroom.** 114 lines flap across rounds and 1,929 are missing in every round. Only the always-missing set is plannable. When you attribute a delta between two local rounds, diff the missing-line **sets** (`live-path.json`'s per-file `missing_lines`), never the totals — differencing totals reads flap as progress.

### The four ways a test can be green and meaningless

This PR writes roughly 180–200 new tests whose stated purpose is to move a number. That is precisely the condition under which hollow tests get written, because the metric rewards **execution** and not **assertion**. All four shapes below were found on 2b-2. Every test this plan adds is bound by all four, and every task's final step is a **break-check**: patch the defect in, watch the new test go red *for the right reason*, revert. A break-check that does not go red is a finding, not a formality — stop and fix the assertion.

1. **The tautological oracle.** A test whose expected value is computed by the code under test cannot fail. Expected dicts, expected messages, expected tuples are **literals typed by a human**, never values re-derived at run time from the subject.

2. **A pin that supplies the default pins nothing.** A test must supply a value that could not arise by accident. Seeding a metadata hash with `total_bytes = 0` does not distinguish the four rungs of the byte-formatting ladder; seeding `1048576` does.

3. **A test can go hollow without changing.** Ask of every assertion: *what edit to production code would make this fail?* If the answer is "none", it is not a test. A changed return value silently disarms an untouched test, and a diff-scoped review cannot see it.

4. **A fixture that patches away the subject its docstring names.** The rule that makes this tractable: **patching the sink you assert against is how you observe; patching the logic that decides what reaches the sink is how you blind yourself.**

   **Corollary, and it bites hardest on log assertions: when the same log string is emitted from more than one function, asserting the string pins nothing.** Two tests written that way pass with the arms swapped — shape 4 arriving through the back door, because the "sink" you are observing is shared by code you are not driving. Pin the **value** the arm formats into the message, or pin the **record count** against the one entry point the test drives, or both. Before writing any `assertLogs` assertion in this PR, grep the message for a second emitter; this codebase has at least one such pair (`"Invalid m3u_profile_id format in Redis"` at `channel_status.py:117` and again at `:596`) and 848 broad `except Exception` handlers to hide more. `@patch("apps.proxy.live_proxy.channel_status.ProxyServer")` to supply a fake Redis is observing — the branch ladder still runs. `@patch.object(cm, "_execute_redis_command")` in a test whose subject is `_execute_redis_command` is blinding.

### The fifth shape, which is specific to this PR: the `except`-body test that pins nothing

34% of the target is inside `except` bodies, and they are the easiest place in this codebase to write a test that asserts nothing but "it did not raise". The rule:

> **An `except`-body test must assert something that only that arm produces.** If the assertion would hold equally for the arm's neighbour, or for the `try` succeeding, it does not pin the arm — it merely executes it.

Worked example, on `ClientManager._execute_redis_command` (`apps/proxy/live_proxy/client_manager.py:181-193`), which has two arms that both return `None`:

```python
        try:
            return command_func()
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis connection error in ClientManager: {e}")
            return None
        except Exception as e:
            logger.error(f"Redis command error in ClientManager: {e}")
            return None
```

**Wrong — executes the arm, pins nothing:**

```python
def test_execute_redis_command_handles_connection_error(self):
    cm = self._client_manager()
    cm.redis_client.scard.side_effect = ConnectionError("boom")
    cm.get_total_client_count()          # must not raise
```

Three defects. It asserts nothing at all. It reaches the arm through `get_total_client_count`, whose *own* `except Exception` at `:425-427` would swallow the same error, so it passes with `_execute_redis_command` deleted entirely. And it cannot tell the two arms apart.

**Also wrong — patches away the subject (shape 4):**

```python
with patch.object(cm, "_execute_redis_command", return_value=None):
    self.assertIsNone(cm._execute_redis_command(lambda: 1))
```

**Right** — with the fixture it needs, which is not optional here:

```python
def _client_manager(self):
    """A real ClientManager over a MagicMock Redis.

    redis_client MUST be truthy. client_manager.py:183-184 returns None
    *before* the try when it is falsy, so a fixture built with
    redis_client=None never enters either except arm and the assertLogs
    below fails with "no logs of level WARNING or higher triggered" --
    and the tempting fix for that failure is deleting the very assertion
    this example exists to teach. The `redis_client = None` case is a
    DIFFERENT branch (kind 5) and belongs in Task 7's guard tests.
    """
    return ClientManager(
        channel_id="chan", redis_client=MagicMock(), worker_id="w1"
    )


def test_a_redis_connection_error_degrades_to_None_and_warns(self):
    """_execute_redis_command's (ConnectionError, TimeoutError) arm.

    The sink patched is the logger (via assertLogs); the subject -- the
    except arm, its log level and its return -- runs unpatched. The level
    assertion is what separates this arm from its Exception neighbour,
    which returns the same None at ERROR.
    """
    cm = self._client_manager()

    def boom():
        raise ConnectionError("redis gone")

    with self.assertLogs("live_proxy.client_manager", level="WARNING") as logs:
        result = cm._execute_redis_command(boom)

    self.assertIsNone(result)
    self.assertEqual([record.levelname for record in logs.records], ["WARNING"])
    self.assertIn("Redis connection error in ClientManager", logs.output[0])
```

and its neighbour, which must assert the *other* level:

```python
def test_any_other_redis_error_degrades_to_None_and_logs_at_error(self):
    cm = self._client_manager()

    def boom():
        raise RuntimeError("something else")

    with self.assertLogs("live_proxy.client_manager", level="ERROR") as logs:
        result = cm._execute_redis_command(boom)

    self.assertIsNone(result)
    self.assertEqual([record.levelname for record in logs.records], ["ERROR"])
    self.assertIn("Redis command error in ClientManager", logs.output[0])
```

Note `get_logger()` derives the logger name from the calling module (`apps/proxy/live_proxy/utils.py:102-127`), so `client_manager.py`'s logger is `live_proxy.client_manager`, `channel_status.py`'s is `live_proxy.channel_status`, and so on. Confirm the name with `logger.name` in a scratch shell rather than guessing when a module is not listed in this plan.

### Working rules

11. **Test-hook container.** Writing any `.py` fires `PostToolUse`, which runs the whole `apps.proxy.live_proxy.tests` package (plus `apps.channels.tests` via `_PATH_ALIASES`) in the container named `dispatcharr-testrunner`, flushing shared Redis. `DISPATCHARR_TEST_CONTAINER` does **not** reach a hook. Before the first `.py` edit, run

    ```bash
    docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
    ```

    and re-point it at this worktree if it names another. Note `scripts/coverage_live_path*` is routed by `_PATH_ALIASES` to Gate 2's own three labels, so Task 0's `.sh` edit also fires the hook.

12. **Stage and commit in separate Bash calls**, and pass the message with `git commit -F <file>` written by the Write tool. The `PreToolUse` gate matches on command text, so one call doing both is blocked, and a heredoc containing the words trips it too.

13. **Never `2>/dev/null` a git query whose emptiness you intend to interpret, and never read `$?` through a pipe.** Use `set -o pipefail`. Brace every ref in a `git show`: `git show "${sha}:path"`, never `git show "$sha:path"` — zsh eats the path as a history modifier and prints the tip commit's diff instead, exit 0.

14. **`--repo D10Scot/Dispatcharr` on every `gh` call.** Without it `gh` resolves to the upstream public tracker.

15. **When a target turns out to be unreachable, say so in the PR — never weaken an assertion to reach it.** A statement you could not close is a fact about the code; a test that executes it without asserting anything is worse than leaving it red, because it also spends the reviewer's attention.

---

## Rulings

These are decisions this plan makes. Each was reached against the tree at `04841a47`; an implementer who disagrees should say so with `file:line` evidence rather than quietly diverging.

### R1 — Fix #266 first, as Task 0, and do not fix #259.

Two flaky-measurement issues sit in this stage's path and they get opposite answers.

**#266 is in scope.** `scripts/coverage_live_path_isolated.sh` opens `set -euo pipefail` (`:12`) and drives three labels in a bare loop; `--label` ends `run_label "$2"; exit $?` (`scripts/coverage_live_path.sh:552`), so a single failing test in the **second** label (`liveproxy`) aborts the wrapper mid-loop: `channels` never runs, no `docker cp`, no combine, **no measurement at all**. Observed twice in one day by two different agents. This PR takes more local measurements than any before it — a checkpoint after each of Tasks 3-12 — so it is the workload that makes this bite. The fix is ~20 lines of bash in a file the Gate 2 denominator does not measure (`source = apps/proxy`), so it cannot move any number, and the shape already exists in the sibling script's no-argument path (`scripts/coverage_live_path.sh:579-605`). Cheap, bounded, and it pays for itself on the first lost round.

**#259 is not in scope, and that is a deliberate call, not an oversight.** Its CI rate is ~3% per push (1 failure in 32 `coverage-label` jobs), so across this PR's twenty CI rounds (8 sizing + 12 floor) the chance of losing *any* round to it is roughly 45% — expect about one lost round in total, which is one re-dispatch, not a campaign. It is `ready-for-agent` with a full diagnosis and two recommended fixes already written (`docs/superpowers/analysis/2026-09-12-issue-259-flake-diagnosis.md` § 4 and § 4a), and both fixes change `test_manager_stderr_failover.py`, a file with no bearing on Gate 2's number. Folding it in would widen a PR whose gate is a coverage figure, in exchange for avoiding one probable re-dispatch. **What this plan does instead** is give the implementer the recognition rule from that diagnosis: when `Coverage apps.proxy.live_proxy.tests` fails, grep the log for `never observed the lead at all` (row 4, the CI-exposed one) or `too few distinct speeds` (row 5, a local-only hazard at 28/72 locally, 0/64 in CI) **before** investigating coverage. Either string means discard the round and re-dispatch; neither means a regression.

### R2 — `_live_connections` moves to `apps/proxy/relay_client.py`, and that destination costs **no** shape re-baseline.

The user ruling (reachability brief § 8) is that `_live_connections` (`apps/proxy/utils.py:256-321`, 28 statements, 4 missing, 85.7% covered) relocates to a boundary module so it joins the gate denominator, carried in this PR. The ruling is settled; the **destination** is not, and the choice matters more than the brief assumed.

The brief assumed relocation into a *new* module, which would have to be added to `scripts/coverage_live_path.coveragerc`'s `[report] include` — moving both `modules=` and `rcfile=`, and forcing a `--write-floor --shape-only` re-baseline. **Relocating into `apps/proxy/relay_client.py` avoids all of it.** That file is already one of the ten Phase 1 boundary modules, already in `[report] include`, and already line 36 of `scripts/coverage_live_path.floor.modules`. Moving a function from a file that is *not* in the report into a file that already *is* leaves coverage's `files` set byte-identical, so `modules=` is unchanged; the rcfile is untouched, so `rcfile=` is unchanged. Only `statements` moves (+28), and `statements` is recorded provenance, not a comparison.

It is also the right home on the merits, not merely the cheap one. `_live_connections`'s entire body is one `relay_client.list_channels(all_clients=True, timeout=relay_client.TUNE_TIMEOUT)` call plus its `RelayUnavailable`/`RelayRefused` and `ImproperlyConfigured` arms plus shaping of the response — it is a `relay_client` call wearing a `utils` coat. `relay_client.py` already owns `RelayUnavailable`, `RelayRefused`, `TUNE_TIMEOUT` and `list_channels`, and imports nothing from `apps/proxy/utils.py`, so the move creates no cycle and deletes a function-local import rather than adding one. D10's rule — nothing under `apps/proxy/live_proxy/` may import `relay_client` — is unaffected: the only caller is `apps/proxy/utils.py:345`.

**Verification is a step, not an assumption.** Task 1 Step 6 runs `--gate` after the move and requires it to pass *without* a re-baseline. If `modules=` mismatches for any reason this ruling did not anticipate, fall back to `scripts/coverage_live_path.sh --write-floor --shape-only`, say so in the PR in the floor file's own words ("re-baselined with `--shape-only`, `missing` unchanged"), and report the surprise — do not silently run plain `--write-floor`, which would overwrite the campaign's `missing`/`runs` provenance with one run's figure.

### R3 — The relocation happens **before** the sizing census, not after it.

The brief's ruling says "relocate first, re-measure, then scope", and the sizing census is the re-measurement. A census taken on a denominator that is about to move by 28 statements is a census of the wrong tree — the same error class as carrying `1,595` forward past a denominator that had already moved twice. Twelve sequential CI rounds are the long pole of this PR; spending them on a stale denominator and then discovering it is the expensive mistake here, not the cheap one.

So the order is Task 0 (#266) → Task 1 (relocate) → Task 2 (census). The census may be dispatched the moment Task 1's commit is pushed; Tasks 3 onward are blocked on its result.

### R4 — The census sets the scope by an explicit rule, decided before the number is known.

A decision rule written after seeing the number is not a decision rule. Task 2 Step 5 fixes the scope from the measured shortfall by the table in that task, and the implementer follows it. The one branch that is *not* the implementer's call is `shortfall > 520`: that means Tier A alone cannot meet the gate, and the remaining options (Tier B harness work, Tier C deletion at 0.8 on the statement, or a spec amendment to the threshold) are decisions above an implementer. **Stop and escalate; do not start writing tests against a target you cannot reach.**

### R5 — Coverage is the *reason* for these tests and never their *oracle*.

Every test in Tasks 3-12 asserts a behaviour that a reader who had never heard of Gate 2 would recognise as worth pinning. The statement count is how the tasks are *sized* and how progress is *checked*; it is never what an assertion is about. Concretely: no test may assert on coverage data, no test's docstring may say "closes N statements" as its whole justification, and no test may be added that the implementer cannot state the behavioural claim of in one sentence. If you cannot write that sentence, the statement stays red and goes in the PR's "not closed" list (Global Constraint 15).

### R6 — Estimates in this plan are the brief's, adjusted; the checkpoints are what make them true.

The per-task `est.` figures descend from the reachability brief's `est. avail.` column, which is a careful reading of uncovered lines and **not** a demonstration. The brief says so itself, and records that reachability estimates in this programme have historically come in optimistic. Each of Tasks 3-12 therefore ends with a measurement checkpoint comparing delivered against estimated. **If a task delivers less than 60% of its estimate, stop and report before starting the next one** — the cushion is 15-25%, which absorbs a few tasks landing short and does not absorb a systematic optimism.

---

## File Structure

```
scripts/
  coverage_live_path_isolated.sh              MODIFIED  Task 0 (#266): run every label, report status, never lose a round
  coverage_live_path.floor                    MODIFIED  Task 13: new `missing` from the final CI census
  coverage_live_path.floor.modules            REGENERATED by --write-floor in Task 13 (contents expected identical)
  coverage_live_path.coveragerc               UNTOUCHED (Global Constraint 6)

apps/proxy/
  relay_client.py                             MODIFIED  Task 1: gains live_connections(user_id)
  utils.py                                    MODIFIED  Task 1: loses _live_connections, calls relay_client.live_connections
  tests/
    test_stream_limits.py                     MODIFIED  Task 1: three existing tests re-pointed at the new home
    test_next_source_edges.py                 NEW       Task 5  (kind 3)
    test_boundary_error_arms.py               NEW       Task 11 (kind 10)

apps/proxy/live_proxy/tests/
  test_vlc_streamlink_parsers.py              NEW       Task 3  (kind 1)
  test_validate_stream_url.py                 NEW       Task 4  (kind 4)
  test_channel_status_fields.py               NEW       Task 6  (kinds 2 + 7)
  test_degraded_redis.py                      NEW       Task 7  (kinds 5 + 6)
  test_setup_and_init_wait.py                 NEW       Task 8  (kind 2)
  test_channel_service_state.py               NEW       Task 9  (kind 9)
  test_non_owner_branches.py                  NEW       Task 10 (kind 8)

docs/superpowers/specs/
  2026-09-09-phase2-go-relay-design.md        MODIFIED  Task 14: the 2b-4 row's stale 455/1,595, D7's status
docs/relay-parity-matrix.md                   MODIFIED  Task 14 only if a new test supersedes a row's reference
metrics/curated/                              MODIFIED  Task 14: milestone + defect ledger (CLAUDE.md § Agent skills)
```

### The ten branch kinds, and which task closes each

| kind | idiom | where it repeats | task | est. |
|---|---|---|---|---:|
| 1 | Pure `str -> Optional[dict]`; no mocks at all | `log_parsers.py` VLC + Streamlink | 3 | 65 |
| 2 | Pure decision logic over a seeded metadata hash | `channel_status`, `views._channel_setup_needed`, `ts/generator` init-wait | 6, 8 | 60 |
| 3 | ORM-fixture branches, no relay state | `next_source.py` | 5 | 55 |
| 4 | `requests` boundary; patch the transport, assert the tuple | `url_utils.validate_stream_url` | 4 | 45 |
| 5 | `if not self.redis_client: return <X>` guards | `client_manager`, `channel_status`, `server`, `channel_service` | 7 | 18 |
| 6 | `_execute_redis_command`-shaped two-arm wrappers | `client_manager`, `channel_status`, `server` | 7 | 26 |
| 7 | `except ValueError` around `int()`/`float()` of a Redis value | `channel_status`, `client_manager` | 6 | 12 |
| 8 | The non-owner second branch of an owner-gated path | `server.ensure_output_profile`/`ensure_output_format`'s five non-owner gates, `client_manager`'s three | 10 | 45 |
| 9 | Failure-rollback, TTL-refresh and sweep arms | `client_manager`, `channel_service` | 9 | 103 |
| 10 | Small error arms in already-96%+ boundary modules | `authorize`, `authorize_views`, `config_helper`, `control_plane`, `relay_client`, `apps` | 11 | 24 |
| | **total estimated** | | | **453** |

**The kind table and the task table must always sum to the same number, and this one does: 453.** Per task that is `65 + 45 + 55 + 35 + 44 + 37 + 103 + 45 + 24`. Three earlier drafts of this plan disagreed with themselves — kind 2 kept a 70 after Task 6 took 2b-3's 7-statement subtraction; kind 8 carried a 70 that was two whole functions' always-missing rather than the non-owner arms Task 10 actually scopes; and its correction to 35 was itself wrong, by cancelling errors (Task 10's header has the post-mortem). If you change any task's estimate, change its kind row in the same edit and re-add both columns.

Predicted shortfall at the branch point is ~405 (see Task 2), and R6's historical discount on these estimates is ~10%, so **realistic delivery is ~408 against ~405 needed**. That is not a cushion — it is level. Task 12's reserve items 1 and 2 should therefore be read as **expected work, not contingency**, at any measured shortfall above ~380.

---

## Task 0: Fix #266 — a failing label must not delete a whole round

**Estimated statements closed: 0.** This is measurement infrastructure. `scripts/` is outside `source = apps/proxy`, so it cannot move any coverage number.

### Step 1: Read the sibling's shape

- [ ] Read `scripts/coverage_live_path.sh:579-605` — the no-argument path. Note its three properties: it collects failures into `failed=()` and runs **every** label regardless; it prints the failure *before* the figures; and it exits 1.
- [ ] Read `scripts/coverage_live_path_isolated.sh` in full (60 lines). Note `set -euo pipefail` at `:12` and the bare `docker exec` inside the `for pair` loop.
- [ ] Read [#266](https://github.com/D10Scot/Dispatcharr/issues/266)'s "What must NOT change" section. Aborting on a failed label is correct and stays the default; the improvement is that the round *completes and reports* instead of dying at label 2.

### Step 2: Rewrite the loop

- [ ] Replace the `for pair in "${PAIRS[@]}"` loop in `scripts/coverage_live_path_isolated.sh` with:

```bash
# A failing label must not delete the whole round. Under the previous
# `set -e` loop a single failing test in `liveproxy` -- the SECOND of three
# -- aborted before `channels` ran, before either docker cp, and before the
# combine: no measurement at all, and nothing saying which label died.
# Issue #266. The shape below is the sibling script's own (its no-argument
# path, coverage_live_path.sh:579-605): run every label, say which failed,
# say it BEFORE the figures, and never emit a floor-eligible number from an
# incomplete round.
declare -a FAILED=()
declare -a STATUS=()
for pair in "${PAIRS[@]}"; do
  suffix="${pair%%:*}"; label="${pair#*:}"
  c="${PREFIX}-${suffix}"
  rc=0
  docker exec "$c" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; export DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY_FOR_EXEC; cd /repo && \
    rm -rf /tmp/rd && COVERAGE_LIVE_PATH_DATA_DIR=/tmp/rd \
    bash scripts/coverage_live_path.sh --label ${label}" || rc=$?
  STATUS+=("${suffix}=${rc}")
  if [ "$rc" -ne 0 ]; then
    FAILED+=("$label")
    # Still copy: a label that failed after tuning has already executed most
    # of its lines, so the partial data dir is useful for per-file
    # ATTRIBUTION even though its TOTAL is not quotable. If the label died
    # before coverage wrote anything, this cp fails and is not fatal.
    docker cp "${c}:/tmp/rd" "${OUT}/${suffix}" || true
  else
    docker cp "${c}:/tmp/rd" "${OUT}/${suffix}"
  fi
done

echo "coverage_live_path_isolated: labels: ${STATUS[*]}" >&2
```

- [ ] Immediately after the loop, and **before** the combine, add the refusal:

```bash
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "coverage_live_path_isolated: label(s) failed: ${FAILED[*]}" >&2
  echo "coverage_live_path_isolated: THE FIGURES BELOW ARE INVALID -- a failed" >&2
  echo "coverage_live_path_isolated: label under-runs the suite and INFLATES" >&2
  echo "coverage_live_path_isolated: 'missing' the way a regression moves." >&2
  echo "coverage_live_path_isolated: use them for per-file attribution if you" >&2
  echo "coverage_live_path_isolated: must; never quote the total, never write a" >&2
  echo "coverage_live_path_isolated: floor from them. Discard the round." >&2
  echo "coverage_live_path_isolated: known flakes (#259): grep the label's log" >&2
  echo "coverage_live_path_isolated: for 'never observed the lead at all' or" >&2
  echo "coverage_live_path_isolated: 'too few distinct speeds' before" >&2
  echo "coverage_live_path_isolated: investigating coverage." >&2
  case "${1:---report}" in
    --write-floor|--gate)
      echo "coverage_live_path_isolated: refusing ${1} on an incomplete round." >&2
      exit 1
      ;;
  esac
fi
```

- [ ] Leave the combine/report block that follows **unchanged**, then change the final line so the requested mode's exit status is preserved and a failed label still fails the script:

```bash
report_rc=0
docker exec "${PREFIX}-proxy" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; export DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY_FOR_EXEC; \
  export COVERAGE_LIVE_PATH_ALLOW_REGRESSION='${COVERAGE_LIVE_PATH_ALLOW_REGRESSION:-}'; \
  export COVERAGE_LIVE_PATH_RUNS='${COVERAGE_LIVE_PATH_RUNS:-0}'; cd /repo && \
  bash scripts/coverage_live_path.sh ${1:---report} /tmp/combined" || report_rc=$?

if [ "${#FAILED[@]}" -gt 0 ]; then exit 1; fi
exit "$report_rc"
```

- [ ] `set -euo pipefail` stays at `:12`. The `|| rc=$?` and `|| true` forms are what disarm `set -e` for exactly the commands that must not abort; nothing else changes.

### Step 3: Prove it with an injected failure

- [ ] Temporarily add a module named `apps/proxy/live_proxy/tests/test_zzz_injected_failure.py` containing one `SimpleTestCase` whose single test calls `self.fail("injected for #266")`. This is a scratch file, **not** committed.
- [ ] Run `bash scripts/coverage_live_path_isolated.sh --report`. Require, in order: the `channels` label runs (its output appears after `liveproxy`'s failure); the status line reads `labels: proxy=0 liveproxy=1 channels=0`; the INVALID banner appears **before** the coverage table; the script exits 1.
- [ ] Run `bash scripts/coverage_live_path_isolated.sh --write-floor` with the injected failure still present. **Run this from your own writable worktree checkout, not from inside the hook container** — `.claude/hooks/start-test-container.sh` bind-mounts `/repo` **read-only** (`docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.RW}}{{end}}'` → `false`), so a floor file that is unchanged there proves the mount is read-only and nothing about whether the refusal fired.

  Require all three of:
  1. exit status 1;
  2. the string `refusing --write-floor on an incomplete round` on **stderr**;
  3. **no report-block output at all** — the coverage table must not be printed, because the refusal is meant to happen *before* the combine, not after it.

  Then, and only as a secondary check, `git diff --exit-code scripts/coverage_live_path.floor scripts/coverage_live_path.floor.modules`. **Both files, not just the floor**: `--write-floor` rewrites the companion module list as well (the floor's own step 3 says so), so checking the floor alone would miss half of what a leaked write would have done.

  The reason this step is spelled out at this length: items 1-3 are what can actually fail, and the byte-identity check — the obvious thing to assert — is the one that cannot in the environment an implementer is most likely to reach for. A vacuous check inside the task whose whole purpose is to stop a measurement vanishing silently would be the plan's own worst joke.
- [ ] Delete the scratch file. Re-run `bash scripts/coverage_live_path_isolated.sh --report` and require exit 0 with `labels: proxy=0 liveproxy=0 channels=0`.

### Step 4: Commit

- [ ] Stage `scripts/coverage_live_path_isolated.sh`.
- [ ] Commit with a message stating that a failed label now completes the round and refuses `--write-floor`/`--gate`, and that aborting remains the default. Close #266 from the PR body in Task 14, not here.

---

## Task 1: Relocate `_live_connections` to `relay_client.py`

**Estimated statements closed: 0 net.** This moves 28 statements (4 of them missing) into the denominator. Predicted effect: `statements` 8,046 → 8,074, permitted ceiling 1,609 → **1,614**, missing +4. Net shortfall change ≈ −1. See R2.

### Step 1: Read both ends

- [ ] Read `apps/proxy/utils.py:256-321` (`_live_connections`) and `:324-360` (`get_user_active_connections`, its only caller, at `:345`).
- [ ] Read `apps/proxy/relay_client.py:1-120` (module docstring, `logger`, `TUNE_TIMEOUT`, `RelayUnavailable`, `RelayRefused`) and `:216-224` (`list_channels`).
- [ ] Confirm `relay_client.py` imports nothing from `apps.proxy.utils`: `grep -n 'from apps.proxy.utils\|from .utils\|import utils' apps/proxy/relay_client.py` must be empty. If it is not, stop — R2's no-cycle claim is wrong and the destination needs rethinking.

### Step 2: Add `live_connections` to `relay_client.py`

- [ ] Insert immediately after `list_channels` (`apps/proxy/relay_client.py:216-224`):

```python
def live_connections(user_id):
    """The live half of get_user_active_connections, over HTTP.

    live:channel:*:clients:* is relay-private state -- the family
    Phase 3 moves out of Redis -- so the control plane asks the relay
    for it rather than scanning it. all_clients=True because a cap
    under-counts a user with more than ten clients on one channel,
    which is exactly the case this function exists to catch, and
    TUNE_TIMEOUT because authorize_stream calls this on every tune.

    A relay that cannot answer contributes nothing and logs once. That
    fails open, and open is correct here: the relay is the only process
    serving live clients, so a relay that is not answering has none.
    Failing closed would 429 every tune for the length of a restart.

    Moved here from apps/proxy/utils.py in Phase 2 PR 2b-4. The body is
    unchanged; the home is. This function is one relay_client call plus
    its three failure arms plus shaping, so relay_client owns it -- and
    relay_client is inside Gate 2's denominator, which apps/proxy/utils.py
    is not, so the tune-path relay call now sits inside the gate that
    guards the Go port (reachability brief, § 8).
    """
    from django.core.exceptions import ImproperlyConfigured

    try:
        # TUNE_TIMEOUT, not the admin budget: check_user_stream_limits
        # calls this from inside authorize_stream, so it is on the tune
        # path for every stream-limited user, and Global Constraints put
        # tune-path reads at (1, 2) with no retry.
        payload = list_channels(all_clients=True, timeout=TUNE_TIMEOUT)
    except (RelayUnavailable, RelayRefused) as exc:
        logger.warning("[stream limits] the relay could not list channels: %s", exc)
        return []
    except ImproperlyConfigured as exc:
        # Unlike Channel.get_stream() this is a limit *check*, not the
        # reservation itself: failing open here (see the docstring) is
        # the same choice a misconfigured relay deserves as an
        # unreachable one -- propagating would 429/500 every tune for a
        # problem a retry cannot fix.
        logger.warning(
            "[stream limits] the relay could not list channels: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return []

    connections = []
    for channel in payload.get("channels") or []:
        media_id = channel.get("channel_id")
        for client in channel.get("clients") or []:
            raw_user_id = client.get("user_id")
            if user_id is not None:
                try:
                    if raw_user_id is None or int(raw_user_id) != user_id:
                        continue
                except (TypeError, ValueError):
                    continue
            try:
                connected_at = float(client.get("connected_at") or 0)
            except (TypeError, ValueError):
                continue
            connections.append({
                'media_id': media_id,
                'client_id': client.get("client_id"),
                'connected_at': connected_at,
                'type': 'live',
            })
    return connections
```

- [ ] Note the two substitutions the move requires and nothing else: `relay_client.list_channels(...)` → `list_channels(...)`, `relay_client.TUNE_TIMEOUT` → `TUNE_TIMEOUT`, `relay_client.RelayUnavailable, relay_client.RelayRefused` → `RelayUnavailable, RelayRefused`, and the now-redundant `from apps.proxy import relay_client` import is dropped. The `ImproperlyConfigured` import stays function-local, as it was.

### Step 3: Update the caller

- [ ] Delete `apps/proxy/utils.py:256-321` in full.
- [ ] At `apps/proxy/utils.py:345`, change `connections = _live_connections(user_id) if include_live else []` to:

```python
    if include_live:
        from apps.proxy import relay_client

        connections = relay_client.live_connections(user_id)
    else:
        connections = []
```

- [ ] `grep -rn '_live_connections' --include='*.py' apps/` and fix every remaining reference. At `04841a47` they are: `apps/proxy/tests/test_stream_limits.py:337` (a comment), and `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py:150` (a comment). Update both comments to name `relay_client.live_connections`.

### Step 4: Re-point the three existing tests

- [ ] The three tests in `apps/proxy/tests/test_stream_limits.py`'s `LiveConnectionsComeFromTheRelayTests` (`:272`, `:322`, `:335`) patch `mock.patch.object(relay_client, "list_channels", ...)` and call `utils.get_user_active_connections(5)`. **They keep working unchanged**, because `live_connections` now calls the module-global `list_channels` in the module being patched. Run them and confirm before touching anything.
- [ ] Add one assertion to `test_live_connections_are_read_over_http_not_scanned` that pins the new home, so the relocation is a checked fact rather than a silent refactor:

```python
        # Phase 2 PR 2b-4: this function's home is relay_client, not
        # apps/proxy/utils.py -- that is what puts the tune-path relay call
        # inside Gate 2's denominator. Deleting the relocation would move it
        # back out and nothing else in the suite would notice.
        self.assertFalse(
            hasattr(utils, "_live_connections"),
            "_live_connections moved to relay_client in 2b-4; a copy left "
            "behind in utils.py is outside the Gate 2 denominator",
        )
        self.assertTrue(callable(relay_client.live_connections))
```

- [ ] Add one test that exercises `live_connections` directly rather than only through `get_user_active_connections`, so the four currently-missing statements have an owner. Pick the `TypeError`/`ValueError` arms, which are the ones a shaped-payload test reaches:

```python
    def test_a_client_with_an_unparseable_user_id_or_timestamp_is_skipped(self):
        """The two (TypeError, ValueError) arms inside the shaping loop.

        The relay's payload is JSON from another process: a `user_id` that is
        not an int and a `connected_at` that is not a float must drop that
        client, not raise out of a tune-path limit check.
        """
        from apps.proxy import relay_client

        payload = {
            "channels": [
                {
                    "channel_id": "abc",
                    "clients": [
                        {"client_id": "bad-user", "user_id": "not-a-number",
                         "connected_at": 1000.0},
                        {"client_id": "bad-time", "user_id": "5",
                         "connected_at": "not-a-float"},
                        {"client_id": "good", "user_id": "5",
                         "connected_at": 1002.0},
                    ],
                }
            ],
            "count": 1,
        }
        with mock.patch.object(relay_client, "list_channels", return_value=payload):
            connections = relay_client.live_connections(5)

        self.assertEqual(
            [c["client_id"] for c in connections], ["good"],
            "a malformed user_id or connected_at drops that client only",
        )
```

- [ ] **Break-check:** delete the `except (TypeError, ValueError): continue` at the `connected_at` parse and confirm the new test raises rather than failing an assertion — that is the right red. Revert.

### Step 5: Credential-logging and boot checks

- [ ] `python scripts/check_credential_logging.py` must pass on both edited files. `relay_client.py`'s module docstring states "Nothing logged here names a URL"; the moved warnings log an exception and a variable name, so this should hold — but confirm rather than assume, since the checker is scoped per file and `relay_client.py` has a stricter self-imposed rule than `utils.py` did.
- [ ] `python manage.py check` must pass (the `apps/channels/models.py:6-7` module-level import trap makes a new cycle fatal for every management command).

### Step 6: Prove the shape did not move

- [ ] Run `bash scripts/coverage_live_path_isolated.sh --gate`.
- [ ] Require: **exit 0**, no `modules=` mismatch, no `rcfile=` mismatch. `statements` should print ~8,074 against the floor's 7,978 — expected and not compared.
- [ ] Record the printed `this run missing=` and `statements` in the PR description as the pre-census baseline.
- [ ] **If `modules=` mismatches**, R2's claim is wrong for a reason not anticipated. Run `bash scripts/coverage_live_path_isolated.sh --write-floor --shape-only`, confirm `git diff scripts/coverage_live_path.floor` touches only `shape`/`modules`/`module_count`/`rcfile` and leaves `statements`/`missing`/`percent`/`measured`/`runs` byte-identical, and **report the surprise to the orchestrator**. Do not run plain `--write-floor`.

### Step 7: Commit

- [ ] Stage `apps/proxy/relay_client.py`, `apps/proxy/utils.py`, `apps/proxy/tests/test_stream_limits.py`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py`.
- [ ] Commit. The message must say the move is into Gate 2's denominator, that it is a code move rather than an rcfile edit, and whether a `--shape-only` re-baseline was needed.

---

## Task 2: The sizing census, and the decision rule that fixes scope

**Estimated statements closed: 0.** This task produces one number and one scope decision. **Every later task reads this number.**

### Step 1: Push and confirm the branch is measurable

- [ ] Push `migration/phase2b-coverage-80` with Tasks 0 and 1 committed.
- [ ] Confirm `backend-tests.yml` has no `paths:` filter that would skip `coverage-label` on this branch, and that `plan.outputs.has_tests` is `true` for this diff (it touches `.py`, so it is).
- [ ] Note the concurrency constraint from the floor file: `backend-tests.yml`'s concurrency group is **per-ref with `cancel-in-progress`**. Dispatching round N+1 while round N is running **cancels round N**. Rounds are strictly sequential. Budget accordingly and do not parallelise.

### Step 2: Run the census

- [ ] For each round: `gh workflow run backend-tests.yml --repo D10Scot/Dispatcharr --ref migration/phase2b-coverage-80`, wait for completion, then read the `coverage-gate` job's log for the two lines it prints: `this run missing=<N>` and `denominator: floor <F> statements  this run <S> statements`.
- [ ] Record **every round, in order**, in a scratch file — `min`/`max` alone cannot show the stopping rule was met, and the PR description must carry the full sequence.
- [ ] **Stopping rule:** maximum unchanged for ≥6 consecutive rounds, minimum **8** rounds total.

  **Why 8 here and 12 in Task 13, ruled 2026-09-12.** This census's output is *thrown away* — Task 13 re-measures from scratch on the finished tree, and nothing this census says reaches the floor file. Its precision requirement is therefore set by the width of the decision-rule bands below (a 16-22% cushion), not by the floor's. What it buys that the floor census cannot is **ordering**: it fixes scope before ~200 tests are written, so a shortfall that turns out to be 550 rather than 405 is discovered at the start of the work rather than at the end, and the escalation branch fires before the effort is spent. Eight rounds preserve that entirely. **Eight is the floor and not a suggestion: below 8 the stopping rule cannot be met at all** (it needs ≥6 consecutive unchanged maxima plus at least two rounds to establish one), and an unmet stopping rule means the observed maximum is a sample rather than a bound. Do not trim it further.

  **The band shift in Step 5 exists because of this cut.** A short census understates the worst case — fewer draws from a bimodal distribution means a lower observed maximum — and understating the worst case puts the implementer in the wrong band, which is the one failure this task exists to prevent. The bands below are therefore set ~10 statements lower than the shortfall they nominally describe, so a census that came in 10 low still selects the right scope.
- [ ] **Discard, do not average, any round in which a `coverage-label` job failed** (Global Constraint 5). `coverage-gate` has `needs: [plan, coverage-label]` with no `if: always()`, so a failed label means `coverage-gate` is skipped and no number is produced — the CI side already fails safe. Before investigating such a failure as a coverage problem, grep the failing label's log for `never observed the lead at all` or `too few distinct speeds`; either is #259 and means re-dispatch, not diagnose (R1).
- [ ] If `S` (statements) differs between rounds, **stop** — something landed on the branch mid-census and the rounds are not measuring the same tree.

### Step 3: Compute the target

- [ ] Let `S` = the statements figure the census reports (constant across rounds) and `M_worst` = the maximum `missing` over the census.
- [ ] Compute the permitted ceiling and the shortfall:

```bash
python3 - <<'PY'
import math
S = 0          # <- statements from the census
M_worst = 0    # <- worst `missing` from the census
permitted = S - math.ceil(0.8 * S)
print(f"statements     {S}")
print(f"worst missing  {M_worst}")
print(f"permitted (>=80%)  {permitted}")
print(f"SHORTFALL      {M_worst - permitted}")
PY
```

- [ ] **Prediction, for sanity only — not a substitute for the measurement.** At `04841a47`: `S = 8046`, single-round `missing = 1994`. Task 1 adds ~28 statements and ~4 missing; 2b-3's fixtures close ~7 at `channel_status.py:72-78`. A census worst typically sits ~30 above a single round (the 2a-7 CI census spread was 34, the local 13-round spread at `93900a6f` was 53). So expect `S ≈ 8074`, `permitted ≈ 1614`, `M_worst ≈ 2020`, **shortfall ≈ 405**. **Treat 405 as the low end of a 405-455 range, not as a point estimate**: the two censuses on record imply 455 (2a-7's CI campaign: 2,050 against a 1,595 ceiling) and 420 (the reachability brief's own local worst-of-13, which says in as many words "plan against 420, not 393"). A measurement anywhere in 380-470 is the expected outcome. Say so before proceeding only if it lands outside that.

### Step 4: Write the census down

- [ ] Record in the PR description, verbatim: the full round sequence in order, `n`, `min`, `max`, `S`, `permitted`, `shortfall`, and the SHA every round ran against. Label it **"sizing census — not a floor"**, because it is taken before the coverage work and `missing` will move.

### Step 5: Apply the decision rule

- [ ] Fix the scope from the measured shortfall. This rule was written before the number was known (R4) and is followed, not re-argued. **The boundaries sit below the shortfalls they nominally describe, for two compounding reasons** — an 8-round census understates the worst case (Step 2's ruling), and the stated estimates carry R6's ~10% optimism. Both push the same way, so the edges are set against the *realistic* column, not the stated one:

| measured shortfall | scope | stated est. | realistic (−10%) |
|---|---|---:|---:|
| **≤ 230** | Tasks 3, 4, 5, 6, 7, 11 only. Skip Tasks 8, 9, 10. | 268 | 241 |
| **231 – 380** | **Tasks 3-11 as written.** | 453 | 408 |
| **381 – 400** | **Tasks 3-11, plus Tasks 8b and 9b from the start** — not as contingency. See the note below; this is a row of the table precisely so it is *selected* rather than remembered. | 531 | 478 |
| **401 – 520** | Tasks 3-11, **plus** Task 12's reserve promoted into the plan: `stream_ts`'s connection-retry loop (`views.py:348-394` — the `remaining_time <= retry_interval` break, the `gevent.sleep` back-off, the final attempt at the timeout boundary, and `control_plane.release_source` on the abandoned slot) as Task 8b; `input/manager.py`'s `_wait_for_existing_processes_to_close` (18 statements, **zero** in `except`, pure polling logic) as Task 9b; **and reserve items 3-4** (`_close_socket`/`_attempt_reconnect`'s mockable socket arms, `input/http_streamer.py` behind an in-process `http.server`). | ~610 | ~550 |
| **> 520** | **STOP. Escalate to the orchestrator before writing a single test.** Tier A cannot meet the gate from here. The options — Tier B harness work, Tier C deletion at 0.8 on the statement, a spec amendment to the threshold — are above an implementer's call (R4). | — | — |

**Why 381-400 is its own row rather than a clause inside the band below it.** At a ~405 shortfall, band 2's stated 453 against a realistic 408 is a three-statement margin — survivable only because Task 12's reserve items 1-2 (`stream_ts`'s retry loop, ~60; `_wait_for_existing_processes_to_close`, 18) are available, which makes the real figure `453 + ~78`. That is a perfectly sound margin **and it evaporates if the promotion is read as advice.** A conditional buried in prose inside the band it modifies is the shape that gets skimmed, so it is a row: an implementer whose census lands at 390 selects Tasks 8b and 9b the same way they select any other scope, rather than recalling a sentence. Below 381 they remain reserve.

**Read the fourth column, not the third.** Every `est.` figure in this plan is a reading of uncovered lines, not a demonstration, and R6 records that such estimates have come in optimistic throughout this programme; the ~10% haircut is that history applied. A band whose *realistic* column sits below its own upper bound is a band that cannot deliver, which is why band 3 draws all four reserve items rather than the two an earlier draft named.

**Why these edges are lower than the shortfall this plan predicts.** The prediction is ~405. The two censuses actually on record imply more: 2a-7's CI campaign ended at 2,050 missing against a 1,595 ceiling, a **455** shortfall; and the reachability brief's own local worst-of-13 gives **420**, with the brief itself saying in as many words "plan against 420, not 393." A ±60 sanity band around 405 would not have flagged either. If your census lands at 446, you are in band 3 and that is an ordinary outcome, not a surprise.

- [ ] State in the PR description which band the census landed in and which scope that selected.

---

## Task 3: Kind 1 — the VLC and Streamlink parsers

**Estimated: 65 statements.** `apps/proxy/live_proxy/services/log_parsers.py`. The cheapest statements in the denominator and D7's own stated rationale for Gate 2 ("`log_parsers.py` is 235 statements of exactly the logic a byte-for-byte port has to get right"). Pure `str -> Optional[dict]`: no Redis, no DB, no mocks, so none of the four hollow shapes can occur except the tautological oracle, and a literal expected dict rules that out too.

New file: `apps/proxy/live_proxy/tests/test_vlc_streamlink_parsers.py`, a `SimpleTestCase`.

### Step 1: Establish what is already covered

- [ ] Read `apps/proxy/live_proxy/tests/test_property_log_parsers.py`. It is a Hypothesis suite asserting **robustness** (never raises, stateless across calls) plus round-trips on generated **FFmpeg** lines. It does not assert a single VLC or Streamlink field value. The work here is complementary, not duplicative — say so in the new file's module docstring.
- [ ] Read `apps/proxy/live_proxy/services/log_parsers.py:155-358` (`VLCLogParser`, `StreamlinkLogParser`) and `:361-413` (`LogParserFactory`).

### Step 2: `VLCLogParser.can_parse` — one test per return

- [ ] Six cases, each a literal line and a literal expected return. These are the six exits of `:163-188`:

| input line | expected |
|---|---|
| `"main input error: Your input can't be opened: VLC is unable to open the MRL 'http://x/y.ts'"` | `'vlc_input_failed'` |
| `"ts demux debug: pid 256 type=0x1b video"` | `'vlc_video'` |
| `"ts demux debug: pid 257 type=0x0f audio"` | `'vlc_audio'` |
| `"avcodec decoder debug: AAC channels: 2 samplerate: 48000"` | `'vlc_audio'` |
| `"stream_out_transcode debug: source fps 30/1"` | `'vlc_video'` |
| `"nothing a vlc parser recognises"` | `None` |

- [ ] Write them as one `subTest`-parameterised test. Include a comment on the fourth row recording the trap: `:178`'s guard is `'decoder' in lower and ('channels:' in lower or 'samplerate:' in lower or 'x' in line or 'fps' in lower)` — `'x' in line` matches an `x` anywhere, so a decoder line with no audio marker and any `x` in it falls to the `else` at `:181-182` and returns `'vlc_video'`. Add that seventh case explicitly, with the expected `'vlc_video'`, because it is the kind of accident a Go port reproduces only if someone wrote it down:
  `"avcodec decoder debug: using max resolution 1920x1080"` → `'vlc_video'`.

### Step 3: `VLCLogParser.parse_video_stream` — the codec map, the fps forms, the resolution bounds

- [ ] Four codec-map rows (`:200-210`), one test each, asserting the whole returned dict as a literal:

```python
    def test_the_ts_demux_codec_map(self):
        """One row of video_codec_map per assertion, dict compared whole.

        The map is four tuples of aliases against four codec names; a Go port
        gets this wrong by transcribing three of the four, which a
        'video_codec' in result assertion would not catch.
        """
        parser = VLCLogParser()
        for line, expected in [
            ("ts demux debug: pid 256 type=0x1b", {"video_codec": "h264"}),
            ("ts demux debug: pid 256 hevc", {"video_codec": "hevc"}),
            ("ts demux debug: pid 256 type=0x02", {"video_codec": "mpeg2video"}),
            ("ts demux debug: pid 256 mpeg-4", {"video_codec": "mpeg4"}),
        ]:
            with self.subTest(line=line):
                self.assertEqual(parser.parse_video_stream(line), expected)
```

- [ ] The `source fps N/D` fraction form (`:213-218`): `"stream_out_transcode debug: source fps 30000/1001"` → `source_fps` == `30000/1001`. Add the `denominator == 0` case — `"source fps 30/0"` — and assert `source_fps` is **absent**, not zero: `:217`'s `if denominator > 0` is the guard, and asserting absence is what distinguishes it from a division that happened to yield 0.
- [ ] The `source WxH` form (`:221-228`): `"stream_out_transcode debug: source 1280x720"` → `{"resolution": "1280x720", "width": 1280, "height": 720}`.
- [ ] The **bounds** at `:225`. Supply values that could not arise by accident (hollow shape 2): `"stream_out_transcode debug: source 9999x9999"` must produce the resolution keys, and `"stream_out_transcode debug: source 0099x0099"` must not. Note `\d{3,4}` means a 5-digit number cannot match at all, so the upper bound `<= 10000` is only reachable at exactly `9999`; record that in a comment rather than writing an unreachable case.
- [ ] The generic-resolution **fallback** at `:229-238`, which runs only when the `source ` form did **not** match: `"avcodec decoder debug: 1920x1080 yuv420p"` → the three resolution keys. Its own bounds check needs its own out-of-range case: `"avcodec decoder debug: 099x099"` → `None` (no other field matched either).
- [ ] The generic-fps fallback at `:241-244`, which runs only when `source_fps` was not already set: `"avcodec decoder debug: 29.97 fps"` → `{"source_fps": 29.97}`. Then the **precedence** case, which is the one a port gets wrong: a line carrying both forms — `"stream_out_transcode debug: source fps 30/1 at 25 fps"` — must yield `source_fps == 30.0`, not `25.0`.
- [ ] The empty-result exit at `:246`: a line `can_parse` routes here but that matches nothing, e.g. `"ts demux debug: pid 256 type=0x99"` → `None`.

### Step 4: `VLCLogParser.parse_audio_stream`

- [ ] Four codec-map rows (`:260-265`), same shape as Step 3's.
- [ ] `channels:` → name mapping (`:273-279`): assert all four named values (1→`'mono'`, 2→`'stereo'`, 6→`'5.1'`, 8→`'7.1'`) **and** the `.get` default with an unmapped count: `"channels: 3"` → `'3'` (the string, not the int).
- [ ] `samplerate:` (`:281-284`) → `{"sample_rate": 48000}`.
- [ ] The `Hz` form (`:287-289`) and its `'sample_rate' not in result` precedence: a line with both `samplerate: 48000` and `44100 hz` must yield `48000`.
- [ ] The word-format channel fallback (`:292-295`) and its `'audio_channels' not in result` precedence: a line with both `channels: 2` and the word `mono` must yield `'stereo'`.
- [ ] The empty-result exit at `:297` → `None`.

### Step 5: `StreamlinkLogParser`

- [ ] `can_parse` (`:312-319`): `"[cli][info] Opening stream: 720p (hls)"` → `'streamlink'`; `"[cli][info] Available streams: 480p, 720p"` → `'streamlink'`; anything else → `None`.
- [ ] `parse_video_stream` (`:324-350`) — the `WxH` branch (`:331-333`) and the named-quality table (`:335-342`). Assert the **whole five-key dict** as a literal for each, because the constant fields (`'video_codec': 'h264'`, `'pixel_format': 'yuv420p'`) are exactly the kind of hard-coded assumption a port drops:

```python
        self.assertEqual(
            parser.parse_video_stream("[cli][info] Opening stream: 720p (hls)"),
            {"video_codec": "h264", "resolution": "1280x720",
             "width": 1280, "height": 720, "pixel_format": "yuv420p"},
        )
```

- [ ] All five table rows (`2160p`, `1080p`, `720p`, `480p`, `360p`), the `WxH` branch (`"Opening stream: 1600x900"`), the **unmapped-quality default** (`"Opening stream: 144p"` → the `1920x1080` fallback — a surprising default, which is exactly why it needs a literal pin), and the no-match exit (`"[cli][info] Found matching plugin"` → `None`).
- [ ] `parse_input_format` and `parse_audio_stream` both return `None` unconditionally (`:321-322`, `:357-358`) — one assertion each.

### Step 6: `LogParserFactory`

- [ ] `_get_parser_and_method`'s no-match exit (`:379`): `LogParserFactory.parse("not_a_stream_type", "x")` → `None`.
- [ ] `parse`'s dispatch for a VLC type and a Streamlink type, asserting the same literal dicts as above so the routing is pinned independently of the parsers.
- [ ] `auto_parse` (`:398-413`): a VLC transcode line returns `("vlc_video", {...})`; a line no parser claims returns `None`; and — the branch a port misses — a line a parser *claims* but parses to nothing returns `None` rather than a tuple with an empty dict. Use `"ts demux debug: pid 256 type=0x99 video"`, which `can_parse` routes to `'vlc_video'` and `parse_video_stream` returns `None` for.

### Step 7: Break-check and checkpoint

- [ ] **Break-check:** change `'720p': ('1280x720', 1280, 720)` to `('1280x721', 1280, 721)` and confirm exactly the Streamlink table test fails on the literal dict. Revert. Then change `:225`'s `100 <= width` to `0 <= width` and confirm the bounds test fails. Revert.
- [ ] Run the label: `python manage.py test apps.proxy.live_proxy.tests.test_vlc_streamlink_parsers`.
- [ ] **Checkpoint.** Run `bash scripts/coverage_live_path_isolated.sh --report`. Record `missing` and the delta from Task 2's single-round baseline, and read `live-path.json`'s `missing_lines` for `apps/proxy/live_proxy/services/log_parsers.py` to see what is still red. Compare delivered against the 65 estimate. **If under 39 (60%), stop and report** (R6).
- [ ] Commit.

---

## Task 4: Kind 4 — `validate_stream_url`

**Estimated: 45 statements.** All 47 of `apps/proxy/live_proxy/url_utils.py`'s always-missing statements are in one function, `validate_stream_url` (`:138-262`). It is live code — called from `views.py:479` and `:501`. Plain `requests`: patch the `Session` and assert the four-tuple.

**Reporting rule for this task, ruled 2026-09-12.** `validate_stream_url` measures at ~48 statements, so 45 assumes near-total conversion — the most optimistic estimate in the plan. **Report to the orchestrator at anything under 45**, not at the 60%-of-estimate threshold R6 sets for the other tasks. Task 12's reserve can absorb a 40, but a silent 40 absorbed into the reserve is exactly what defeats the ordering argument that justifies having a sizing census at all: the point of measuring early is that shortfalls surface while scope can still change.

New file: `apps/proxy/live_proxy/tests/test_validate_stream_url.py`, a `SimpleTestCase`.

### Step 1: The fixture

- [ ] Patch the transport, not the function. `validate_stream_url` constructs `requests.Session()` at `:161`, so the patch target is `apps.proxy.live_proxy.url_utils.requests.Session`:

```python
    def _session(self, *, head=None, get=None):
        """A fake requests.Session whose head/get are scripted.

        Patching Session is patching the SINK the subject writes to; the
        subject -- the HEAD/GET ladder, the status check, the content-type
        table and the four-tuple -- runs unpatched. Patching
        validate_stream_url itself, or any branch inside it, would be
        blinding (Global Constraints, shape 4).
        """
        session = MagicMock()
        session.head = MagicMock(**head) if isinstance(head, dict) else MagicMock(return_value=head)
        session.get = MagicMock(**get) if isinstance(get, dict) else MagicMock(return_value=get)
        return session

    def _response(self, status, *, content_type=None, chunks=(b"x" * 1880,)):
        response = MagicMock()
        response.status_code = status
        response.headers = {"Content-Type": content_type} if content_type else {}
        response.iter_content = MagicMock(return_value=iter(chunks))
        return response
```

### Step 2: The non-HTTP early return (`:155-157`)

- [ ] Three schemes, asserting the whole tuple and that **no session was constructed at all**:

```python
    def test_udp_rtp_and_rtsp_skip_validation_without_a_request(self):
        for url in ("udp://239.0.0.1:1234", "rtp://239.0.0.1:1234",
                    "rtsp://example.invalid/stream"):
            with self.subTest(url=url):
                with patch("apps.proxy.live_proxy.url_utils.requests.Session") as session_cls:
                    result = validate_stream_url(url)
                self.assertEqual(
                    result,
                    (True, url, 200,
                     "Non-HTTP protocol (UDP/RTP/RTSP) - validation skipped"),
                )
                session_cls.assert_not_called()
```

The `assert_not_called` is what makes this pin the *early return* rather than merely a truthy result — without it the test passes if the early return is deleted and the HEAD happens to succeed.

### Step 3: The HEAD/GET ladder

- [ ] **HEAD succeeds** (`:181-183`): `head` returns a 200; assert `(True, url, 200, "Valid (HEAD request)")` and `session.get.assert_not_called()`.
- [ ] **HEAD raises** (`:176-178`), GET succeeds: `head.side_effect = requests.exceptions.RequestException("no HEAD")`; a 200 GET with `content_type="video/mp2t"` and one 1880-byte chunk. Assert `is_valid is True`, `status_code == 200`, and that the message contains both `"received 1880 bytes"` and `"recognized as valid stream format"` — the second half is what pins the content-type table, which the first half does not.
- [ ] **HEAD returns a non-2xx** (`:181` false without an exception, e.g. 405): assert the GET ran. This is the branch the docstring is about and it is distinct from the exception branch above; `head_request_success` is `True` here and `False` there.
- [ ] **GET non-2xx** (`:194-196`): a 404 GET → `(False, url, 404, "Invalid HTTP status: 404")`. Assert `get_response.iter_content` was **not** called — the comment at `:193` says status is checked first, and that ordering is the assertion.
- [ ] **Empty body** (`:203-205`): a 200 GET whose `iter_content` yields nothing → `is_valid is False` and the message starts `"Empty response from server"`. Note the tuple's first element is `False` while the status is 200 — assert both, because a reader who only checks the status sees a success.

### Step 4: The content-type table (`:208-244`)

- [ ] A recognised type: `content_type="application/vnd.apple.mpegurl"` → message ends `", recognized as valid stream format)"`.
- [ ] An **unrecognised** type: `content_type="text/html"` → message ends `", unrecognized but may still work)"` **and** `is_valid is True`, because `:236-237`'s comment is explicit that content is what decides. That pairing is the behaviour; asserting only the suffix misses it.
- [ ] **No** `Content-Type` header at all (`:238` false) → the message carries no `(Content-Type:` fragment. This is the third branch of a three-way and the one a port drops.
- [ ] One substring-matching case that documents the table's looseness: `content_type="video/"` matches on `'video/'`, and `content_type="application/x-custom-ts"` matches on the bare `'ts'` entry. Pin the second with a comment — an entry of `'ts'` matching any content type containing the letters `ts` is a real property of this table.

### Step 5: The four terminal `except` arms (`:252-259`)

- [ ] Four tests, one per arm, each asserting the **message that only that arm produces** (the fifth hollow shape's rule):

| raised by `session.get` | expected tuple |
|---|---|
| `requests.exceptions.Timeout()` | `(False, url, 0, "Timeout connecting to stream")` |
| `requests.exceptions.TooManyRedirects()` | `(False, url, 0, "Too many redirects")` |
| `requests.exceptions.RequestException("boom")` | `(False, url, 0, "Request error: boom")` |
| `ValueError("boom")` | `(False, url, 0, "Validation error: boom")` |

Note the ordering dependency worth a comment: `Timeout` and `TooManyRedirects` are both subclasses of `RequestException`, so the arms must stay in this order for the first two to be reachable at all. Assert the exact messages, which is what proves the order held.

- [ ] The `finally` at `:260-261`: assert `session.close()` was called on both a success path and the `ValueError` path.

### Step 6: Break-check and checkpoint

- [ ] **Break-check:** swap the `Timeout` and `RequestException` arms and confirm the Timeout test fails with `"Request error: "`. Revert.
- [ ] Run the label, take the checkpoint (as Task 3 Step 7), compare against 45, commit.

---

## Task 5: Kind 3 — `next_source.py`'s ORM-fixture branches

**Estimated: 55 statements.** `apps/proxy/next_source.py`. Ordinary `TestCase` with model fixtures; no relay state at all. **Caution: 2b-2 edited this file** (it added the `output_profiles` map to the `next-source` response), so re-derive every line number from a fresh `live-path.json` rather than from the reachability brief's `93900a6f` numbers.

New file: `apps/proxy/tests/test_next_source_edges.py`.

### Step 1: Re-measure before writing

- [ ] From the most recent local round, read `live-path.json`'s `missing_lines` for `apps/proxy/next_source.py` and list them. Map each to a function with `sed -n`. Work from that list, not from the table below, which is the brief's pre-2b-2 reading.
- [ ] Read `apps/proxy/tests/test_next_source_resolution.py` and `test_next_source_api.py` to find the existing fixture builders; reuse them rather than writing a third.

### Step 2: The branches

- [ ] One test per row. Each asserts the **response or exception the branch produces**, never merely that it did not raise:

| branch | fixture | assertion |
|---|---|---|
| `Stream` with no M3U account | a `Stream` row with `m3u_account=None` | the documented refusal, not a 500 |
| account with no default profile | `M3UAccount` with no `is_default=True` profile | the documented refusal |
| `is_active == False` on the account | `M3UAccount(is_active=False)` | the stream is not offered |
| no profile with connection capacity | every profile at its `max_streams` | the documented "no capacity" answer |
| `stream_id is None` | a candidate carrying no id | skipped, remaining candidates still considered |
| `get_transformed_credentials` XC form | an XC-shaped account | the built URL is exactly `{base}/live/{user}/{pass}/{id}.ts` — a literal, typed by hand |
| `ordered_stream_ids.index()` raising `ValueError` | an ordering list that omits a candidate's id | the candidate is still returned, in the documented position |
| `isinstance(channel, Stream)` guard | call the resolver with a `Stream` rather than a `Channel` | the single-stream path, not the channel path |

- [ ] For the XC credential row, note CLAUDE.md's rule: the assertion must not put a provider password in a failure message that could reach a log. Assert on the built URL with a fixture password like `"pw-fixture"` that is obviously synthetic.

### Step 3: Break-check and checkpoint

- [ ] **Break-check:** change the XC URL template's `/live/` to `/stream/` and confirm only that test fails. Revert.
- [ ] Run `python manage.py test apps.proxy.tests.test_next_source_edges`, take the checkpoint, compare against 55, commit.

---

## Task 6: Kinds 2 + 7 — `channel_status.py`'s seeded-hash branches

**Estimated: 35 statements** (the brief's 40, less the ~7 that 2b-3's fixtures close at `:72-78`, plus a small allowance). `apps/proxy/live_proxy/channel_status.py`. Almost all one- and two-line branches over a metadata hash that the test writes.

New file: `apps/proxy/live_proxy/tests/test_channel_status_fields.py`, a `SimpleTestCase`.

### Step 1: The fixture

- [ ] Use the idiom already in the tree at `apps/proxy/live_proxy/tests/test_live_db_cleanup.py:322-344`: patch `ProxyServer` in `channel_status`'s namespace and hand it a `MagicMock` redis client whose `hgetall` returns a plain dict. No Redis, no DB, fast.

```python
    def _info(self, metadata, *, buffer_index="1", client_metadata=None):
        """Drive get_detailed_channel_info over a hand-written metadata hash.

        ProxyServer is patched because it is the SOURCE of the hash, not the
        subject: every branch this file tests -- the byte ladder, the bitrate
        formatting, the int-parse arms -- runs unpatched on the dict below.
        """
        with patch("apps.proxy.live_proxy.channel_status.ProxyServer") as proxy_cls, \
             patch("apps.proxy.live_proxy.channel_status.close_old_connections"):
            proxy_server = MagicMock()
            proxy_server.redis_client = MagicMock()
            proxy_server.redis_client.hgetall.side_effect = (
                lambda key: client_metadata.get(key, {}) if client_metadata and "clients:" in key
                else metadata
            )
            proxy_server.redis_client.get.return_value = buffer_index
            proxy_server.redis_client.smembers.return_value = set()
            proxy_cls.get_instance.return_value = proxy_server
            return ChannelStatus.get_detailed_channel_info("chan-uuid")
```

- [ ] Read `channel_status.py:25-120` and adjust the fake's method set to whatever the function actually calls — do not guess. The `smembers`/client-metadata plumbing is only needed for Step 4.

### Step 2: The absent-metadata and duration guards

- [ ] `:32-33` — `hgetall` returns `{}` → the function returns `None`. Assert `assertIsNone`, not falsiness.
- [ ] `:18-19` — `_calculate_bitrate(total_bytes=1000, duration=0)` returns `0`, and `duration=-1` also returns `0`. Call the static directly; it is a pure function and needs no fixture.
- [ ] The `owner` fallback at `:45`: a hash with no `owner` field yields the literal string `'unknown'`, not `None`. This is a carried defect CLAUDE.md names ("truthiness checks pass when nobody owns the channel") — pin it as behaviour with a comment saying it is deliberate, so 2c reproduces it.

### Step 3: The byte ladder and the bitrate formatting (kind 2)

- [ ] `:142-149` is a four-rung ladder. Supply one value per rung that could not land on a neighbour (hollow shape 2), and assert the **formatted string**, which is the only thing that differs between rungs:

```python
    def test_the_total_data_ladder_formats_each_rung(self):
        for total_bytes, expected in [
            (512, "512 B"),
            (1536, "1.50 KB"),
            (1572864, "1.50 MB"),
            (1610612736, "1.50 GB"),
        ]:
            with self.subTest(total_bytes=total_bytes):
                info = self._info({"state": "active", "total_bytes": str(total_bytes)})
                self.assertEqual(info["total_data"], expected)
                self.assertEqual(info["total_bytes"], total_bytes)
```

- [ ] `:152-160` — `avg_bitrate` requires `uptime` in `info`, which requires the `INIT_TIME` field. Seed `init_time` far enough in the past to make `uptime` a known-ish positive, then assert the **Mbps/Kbps split** at `:157`: one case whose bitrate exceeds 1000 (message ends `" Mbps"`) and one below (ends `" Kbps"`). Because `uptime` is `time.time() - created_at`, patch `time.time` in the module's namespace to a fixed value so the expected string is a literal rather than a recomputation (hollow shape 1).
- [ ] `:152` false — `total_bytes` present but no `init_time` → `avg_bitrate_kbps` is **absent** from the dict, not `None`. `assertNotIn`, which is what the CLAUDE.md contract ("can be absent entirely (not null)") actually says.

### Step 4: The client-row branches

- [ ] `:173-176` — a client id in the set whose metadata hash is empty is a ghost: it is skipped and lands in `stale_client_ids`. Assert the client is absent from `info["clients"]`.
- [ ] `:187-191` — `output_profile_id` parsing. Four cases: a numeric string → the int; `'None'`, `'0'` and `''` → `None`. All four in one `subTest` loop; the three sentinel strings are the pin, and a test that only supplies a number passes with the sentinel list deleted.
- [ ] `:206-209` — the legacy `transfer_rate_KBps` fallback. Three cases: `avg_rate_KBps` present → used; only `transfer_rate_KBps` present → used; **both** present → `avg_rate_KBps` wins. The third is the precedence and the only one that pins the `elif`.

### Step 5: The `except ValueError` int-parse arms (kind 7)

- [ ] Seed a non-numeric value into each field the brief names and assert the documented degradation plus the warning that only that arm emits. At the brief's measurement these were `channel_status.py` `81-82`, `115-116`, `494-495`, `501-502`, `595-596`; re-derive the current lines from `live-path.json` first.
- [ ] The shape, using `:115-118` (`m3u_profile_id` not an int) as the worked case:

```python
    def test_a_non_numeric_m3u_profile_id_warns_and_omits_the_name(self):
        """channel_status.py's except ValueError around int(m3u_profile).

        The arm's own product is the warning naming the bad value and the
        ABSENCE of m3u_profile_name -- both asserted, because 'did not raise'
        would hold with the whole try/except deleted.
        """
        with self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            info = self._info({"state": "active", "m3u_profile": "not-an-int"})
        self.assertNotIn("m3u_profile_name", info)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("Invalid m3u_profile_id format in Redis", logs.output[0])
        # The VALUE, not just the string: "Invalid m3u_profile_id format in
        # Redis" is emitted from channel_status.py:117 AND from :596, in a
        # different function. Pinning the message alone gives two tests that
        # pass with the arms swapped. The rejected value reaches :117's
        # message via m3u_profile_id_bytes, so asserting it is what ties this
        # assertion to this arm.
        self.assertIn("not-an-int", logs.output[0])
```

  **Carry that pattern to the `:595-596` arm rather than the `any(...)` one.** `get_basic_channel_info` emits the same string, so a test for `:595-596` written with a bare substring check would be green whichever function ran. Drive each arm from its own entry point and pin the value.

### Step 6: `_execute_redis_command`'s two arms in this module

- [ ] The brief names `channel_status.py:425-430` (6 statements) as a second copy of the `_execute_redis_command` idiom. Cover it with the two-arm pattern from the Global Constraints worked example, on `live_proxy.channel_status`'s logger. **Check first whether Task 7 already owns it** — if the two modules' copies are genuinely identical, put both in Task 7's file and leave this step empty rather than writing the same test twice.

### Step 7: Break-check and checkpoint

- [ ] **Break-check:** change the **divisor at `:147`** — `f"{total_bytes / (1024 * 1024):.2f} MB"` → `f"{total_bytes / (1024 * 1024 * 2):.2f} MB"` — and confirm exactly the MB rung fails on the formatted string. Revert.

  **Not `:146`.** That line is the rung *boundary* (`elif total_bytes < 1024 * 1024 * 1024:`), and widening it leaves 1,572,864 in the MB rung, so the test stays green and an implementer following this plan's own rule ("a break-check that does not go red is a finding") would go looking for a fault in a correct test. The divisor is what the assertion reads; the boundary is only reachable by a value chosen to sit on it.
- [ ] Run the label, take the checkpoint, compare against 35, commit.

---

## Task 7: Kinds 5 + 6 — the degraded-Redis idioms, everywhere they repeat

**Estimated: 44 statements** (18 of kind 5, 26 of kind 6). This is the most *repetitive* task in the plan and the one where a hollow test is most likely, because every branch returns the same shape.

New file: `apps/proxy/live_proxy/tests/test_degraded_redis.py`, a `SimpleTestCase`.

### Step 1: Enumerate the guards (kind 5)

- [ ] Find every `if not self.redis_client` / `if not redis_client` guard in the denominator's modules and record its file, line and **documented return**:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/plan-2b4 && \
  grep -rn 'if not self\.redis_client\|if not redis_client' \
    --include='*.py' apps/proxy/live_proxy apps/proxy/*.py | grep -v /tests/
```

- [ ] Cross-check the result against `live-path.json`'s `missing_lines` and keep only the guards still red. The brief names `client_manager.py` (`:57`, `:184`, `:335`, `:407`, `:418-419`), `channel_status.py:421`, `server.py` (`:1440-1441`, `:1455-1456`) and several in `channel_service.py`.
- [ ] **Two more belong here and were briefly mis-assigned to Task 10: `server.py:1454` and `server.py:1303`**, both `if not self.redis_client: return False`, in `ensure_output_profile` and `ensure_output_format` respectively. They sit among Task 10's non-owner gates but are the kind-5 idiom, not an owner/follower branch, and covering them there would double-count against this task. Supply a `ProxyServer` with `redis_client = None` and assert each function returns **`False`** — note the value, because the kind-5 guards in this task do not all return the same thing: `ClientManager`'s return `None`, `0`, or the **local client count**. A test that only checks falsiness would pass against `None` or `0`; it would *fail* against the local count, which is truthy once seeded, and Step 2 seeds two clients for exactly that reason. So `assertIs(..., False)` and `assertEqual(..., 2)` are each pinning something a bare `assertFalse` would not.

### Step 2: One parameterised test per class, not per method

- [ ] For each class, construct the object with `redis_client=None` and call every guarded public method, asserting each one's **specific** documented degraded return. The returns differ — `None`, `[]`, `0`, `len(self.clients)` — and that difference is the assertion:

```python
    def test_a_client_manager_with_no_redis_degrades_per_method(self):
        """Every `if not self.redis_client` guard in ClientManager.

        Each method's degraded return is asserted individually. A loop that
        only checked `is not None` would pass with every guard returning the
        same thing, which is precisely what these guards do NOT do:
        get_total_client_count falls back to the LOCAL count, not to zero.
        """
        cm = ClientManager(channel_id="chan", redis_client=None, worker_id="w1")
        cm.clients = {"c1", "c2"}

        self.assertIsNone(cm._execute_redis_command(lambda: "never runs"))
        self.assertEqual(cm.get_total_client_count(), 2)   # local fallback, not 0
        self.assertIsNone(cm.refresh_client_ttl())
        self.assertIsNone(cm._notify_owner_of_activity())
```

- [ ] The `get_total_client_count` line is the one that earns the test. Seed `cm.clients` with **two** entries so a fallback to `0` and a fallback to `len(self.clients)` give different answers — a test with an empty client set passes either way (hollow shape 2).
- [ ] Repeat for `channel_status`, `server` and `channel_service`'s guards, each with a value that distinguishes the real fallback from a zero/empty one.

### Step 3: The two-arm wrappers (kind 6)

- [ ] Apply the Global Constraints worked example verbatim to each copy of the `_execute_redis_command` idiom found in Step 1's grep — `client_manager.py:181-193`, `channel_status.py`'s copy, and `server.py:138-159` (14 statements, the largest). Two tests per copy: the `(ConnectionError, TimeoutError)` arm at WARNING and the `Exception` arm at ERROR, each asserting the level list **and** the message fragment that only that arm emits.
- [ ] `server.py:138-159` is 14 statements, so it is likely more than two arms. Read it and write one test per arm, each with an assertion unique to that arm. If two arms are genuinely indistinguishable from outside, say so in a comment and cover only one — do not write a second test that cannot fail independently.

### Step 4: Break-check and checkpoint

- [ ] **Break-check:** change `client_manager.py:190`'s `return None` to `return 0` and confirm the `assertIsNone(cm._execute_redis_command(...))` test fails. Then swap `:189`'s `logger.warning` to `logger.error` and confirm the level-list assertion fails while the `assertIsNone` still passes — that is the proof the level assertion is doing work. Revert both.
- [ ] Run the label, take the checkpoint, compare against 44, commit.

---

## Task 8: Kind 2 — `_channel_setup_needed` and the TS generator's init wait

**Estimated: 37 statements.** Two pure decision functions with **zero** `except` lines between them — the cheapest non-trivial block left.

New file: `apps/proxy/live_proxy/tests/test_setup_and_init_wait.py`.

### Step 1: `views._channel_setup_needed` (11 statements, `apps/proxy/live_proxy/views.py:60-99`)

- [ ] It is directly callable: `_channel_setup_needed(proxy_server, channel_id)` returning `(needs_setup, state, wait_for_init)`. Six seeded-hash cases close all eleven. Assert the **whole three-tuple** each time, because `wait_for_init` is the field two of the cases exist to distinguish.
- [ ] The fixture, which the cases below all use:

```python
    def _proxy(self, *, metadata=None, heartbeat_exists=False, channel_exists=False):
        """A stand-in ProxyServer carrying one metadata hash.

        Only the four members _channel_setup_needed actually reads are
        supplied; the decision ladder itself runs unpatched. Pass
        metadata=None to exercise the `if proxy_server.redis_client` /
        empty-hash paths at views.py:67-69.
        """
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.hgetall.return_value = metadata or {}
        proxy_server.redis_client.exists.return_value = heartbeat_exists
        proxy_server.check_if_channel_exists.return_value = channel_exists
        return proxy_server
```

  For the `:67` false case (no Redis client at all), set `proxy_server.redis_client = None` on the object this returns rather than adding a fifth keyword — that branch is one line and does not earn a parameter.

```python
    def test_the_six_setup_decisions(self):
        for state, exists_heartbeat, expected in [
            (ChannelState.ACTIVE,               False, (False, ChannelState.ACTIVE, False)),
            (ChannelState.INITIALIZING,         False, (False, ChannelState.INITIALIZING, True)),
            (ChannelState.CONNECTING,           False, (False, ChannelState.CONNECTING, True)),
            (ChannelState.STOPPING,             False, (False, ChannelState.STOPPING, False)),
            (ChannelState.ERROR,                False, (True,  ChannelState.ERROR, False)),
            (ChannelState.STOPPED,              False, (True,  ChannelState.STOPPED, False)),
        ]:
            with self.subTest(state=state):
                proxy_server = self._proxy(metadata={"state": state})
                self.assertEqual(_channel_setup_needed(proxy_server, "chan"), expected)
```

- [ ] `ChannelState.WAITING_FOR_CLIENTS` and `ChannelState.BUFFERING` are in the same tuple as ACTIVE (`:71-77`) but produce `wait_for_init = False`; add both, because a port that transcribes the two tuples as one gets those two rows wrong and nothing else catches it.
- [ ] The unknown-state owner branch (`:88-94`), which is three outcomes and the interesting part of the function:
  - unknown state, `owner` present, heartbeat key **exists** → `(False, state, False)`;
  - unknown state, `owner` present, heartbeat key **absent** → `(True, state, False)`;
  - unknown state, **no** `owner` → falls through to `:96`.
  Assert the heartbeat key the function builds is exactly `f"live:worker:{owner}:heartbeat"` by checking `proxy_server.redis_client.exists.call_args`. That string is a hard-coded key with no `RedisKeys` helper — precisely what a port gets wrong.
- [ ] `:96-97` — no metadata at all but `check_if_channel_exists` returns `True` → `(False, None, False)`; and `:99` — neither → `(True, None, False)`. Note `state` is `None` in both, not `''`.
- [ ] `:67` false — `proxy_server.redis_client` is `None` → skips straight to `:96`. One more case.

### Step 2: `ts/generator._init_wait_abort_reason` + `_wait_for_initialization` (26 statements)

- [ ] Read `apps/proxy/live_proxy/output/ts/generator.py:157-252`. `_init_wait_abort_reason` returns one of `"stopping"`, `"client_gone"`, `"stalled"` or `None`; `_wait_for_initialization` is a generator that yields an error TS packet and returns `False` for each, or returns `True` on readiness.
- [ ] Four tests on `_init_wait_abort_reason`, one per return, each with the state that produces only that answer. The `"stalled"` branch (`:190-196`) has three conditions — buffer index `> 0`, the `last_data` key, and the grace period — so it needs a case where each of the first two individually suppresses the `"stalled"` answer, not just one where all are absent.
- [ ] `_wait_for_initialization` is a generator whose **return value** is the subject, so drive it with `next()`/`StopIteration.value`:

```python
    def _run(self, generator):
        """Drain a generator and return (yielded_packets, return_value)."""
        packets = []
        try:
            while True:
                packets.append(next(generator))
        except StopIteration as stop:
            return packets, stop.value
```

- [ ] Three abort cases (`"stopping"`, `"client_gone"`, `"stalled"`): assert the return is `False` **and** the yielded packet carries the arm's own message — `"Error: Channel is stopping"`, `"Error: Client disconnected"`, `"Error: Connection stalled"`. Three different messages is what separates three arms that otherwise all return `False`.
- [ ] The ready path (`:230-233`): metadata state `waiting_for_clients` or `active` → returns `True` and yields **nothing**. Assert the empty packet list; a test that only checks the return passes with a spurious error packet emitted.
- [ ] The error-state path (`:234-238`): state `error`/`stopped`/`stopping` with an `error_message` → returns `False`, packet carries `f"Error: {error_message}"`. Supply a distinctive `error_message` (`"upstream said no"`), not the default — asserting against `"Unknown error"` pins the default and not the field.
- [ ] The stop-flag path (`:241-245`) and the timeout exit (`:249-251`). For the timeout, patch `ConfigHelper.client_wait_timeout` to a small value and `gevent.sleep` to a no-op so the loop terminates without wall-clock cost; assert the final packet says `"Error: Initialization timeout"`.

### Step 3: Break-check and checkpoint

- [ ] **Break-check:** move `ChannelState.BUFFERING` out of `views.py:71-77`'s tuple and confirm the BUFFERING row fails while the others pass. Revert.
- [ ] Run both labels, take the checkpoint, compare against 37, commit.

---

## Task 9: Kind 9 — `channel_service.py`'s state machine and the rollback arms

**Estimated: 103 statements.** The largest Tier A pool. Pure Python plus Redis calls; no subprocess.

**The two numbers in this task are measured and estimated respectively, and an earlier draft conflated them.** Step 2 enumerates **90 always-missing** statements across five `channel_service` functions (33 + 30 + 14 + 6 + 7) — that is the measured pool. Applying R6's discount gives **~77 estimated available**, and `client_manager`'s rollback/TTL/sweep arms (Step 3) add **26**, for the 103 above. The draft wrote "(77 in `channel_service`)" beside a step that enumerates 90, which reads as an arithmetic error rather than as a pool-versus-estimate distinction. Keep the two labelled separately wherever you restate them.

**Do not "correct" the 103 upward. It is partly pre-discounted, and that is deliberate.** The 77 already carries R6's ~10% haircut, which every other task's estimate does not — those are pre-haircut, and the band table applies the −10% to the lot. So Task 9 is discounted twice and contributes ~9 statements less to the realistic column than a uniform treatment would give it. That errs **conservative**, which is the direction this plan wants to err, so it stays. Written down because the inconsistency is real and a later reader who spots it will otherwise raise the number and silently delete the margin.

New file: `apps/proxy/live_proxy/tests/test_channel_service_state.py`.

### Step 1: Pick the fixture level deliberately

- [ ] `ChannelService`'s methods are statics taking a `channel_id` and reaching Redis through `ProxyServer.get_instance()`. Prefer the `MagicMock`-Redis fixture from Task 6 for branch work — it is fast and the branches are pure. Use `RelayHarnessTestCase` (real Redis) **only** where the branch depends on a real Redis semantic a `MagicMock` cannot fake (a pipeline's atomicity, a `SETNX` outcome, a TTL). State which you chose per test in its docstring, and why.
- [ ] Known real-Redis dependency: anything asserting on the ownership lease or on `setex` TTLs. Note CLAUDE.md's standing gap — the lease still never meets real Redis semantics outside the harness — and do **not** claim otherwise in a docstring.

### Step 2: The four target functions

- [ ] `change_stream_url` (33 always-missing). Read `apps/proxy/live_proxy/services/channel_service.py:383-587` and write one test per uncovered branch. The axis to walk systematically is **owner versus non-owner** (see Task 10 and CLAUDE.md's "owner/follower is a systematic axis"): the owner switches directly, the non-owner publishes on `live:events:` and polls `RedisKeys.switch_status` up to `STREAM_SWITCH_CONFIRM_TIMEOUT`. Confirm which branch each uncovered line is in before writing.
- [ ] `validate_channel_state` (30). One test per state the validator rejects and one per state it accepts; assert the returned tuple/flag, never just truthiness.
- [ ] `cancel_pending_shutdown` (14). At minimum: no pending shutdown to cancel; a pending shutdown cancelled successfully; and the failure arm. Assert the Redis key's resulting presence or absence, which is the only externally-visible product.
- [ ] `_channel_proxy_is_active` (6) and `stop_channels` (7). `stop_channels` takes a list; cover the empty list, one identifier, and the per-identifier failure that must not abort the rest — that last one is the behaviour worth pinning and it mirrors `relay_client.stop_channels`'s own per-channel-versus-abort rule that CLAUDE.md documents.

### Step 3: `client_manager`'s rollback, TTL and sweep arms (26)

- [ ] `add_client`'s failure rollback (`:301-306`). Make the `publish` or the `sadd` raise and assert the client is **not** left in `self.clients` and **not** left in the Redis set — the rollback's product, not the exception.
- [ ] `refresh_client_ttl` end to end (`:429-...`, 9 statements). Assert the `expire`/`hset` calls it issues for each locally-held client, with the TTL value it computes. Supply a non-default `client_ttl` so the assertion pins the computation rather than the constant.
- [ ] The ghost-client sweep (`:465-482`, 11 statements). Seed a client set with three ids, of which two have no metadata hash; assert exactly those two are returned and exactly those two are `srem`'d. Asserting the count alone would pass with the wrong two removed.

### Step 4: Break-check and checkpoint

- [ ] **Break-check:** in the ghost sweep, invert the `if not exists` filter and confirm the test fails naming the wrong ids. Revert.
- [ ] Run the label, take the checkpoint, compare against 103, commit. This is the largest task; consider committing Steps 2 and 3 separately.

---

## Task 10: Kind 8 — the non-owner second branch

**Estimated: 45 statements. Ceiling 50.** The relay's organising conditional. Three PRs running in this programme have had a defect hiding in one branch, and CLAUDE.md records owner-versus-follower as a systematic axis: ask at every hop whether a second branch takes a different route.

**The eight non-owner arms, measured with `PythonParser` at `04841a47`:**

| gate | condition | file:range | stmts |
|---|---|---|---:|
| A | `existing is None` and `state != PROFILE_STATE_ACTIVE` | `server.py:1440-1453` | 9 |
| B | `state == PROFILE_STATE_ACTIVE` and `owner_val != self.worker_id` | `server.py:1464-1475` | 5 |
| C | `not self.am_i_owner(...)` — `ensure_output_profile` | `server.py:1483-1519` | 15 |
| B′ | same as B, in `ensure_output_format` | `server.py:1310-1311` | 2 |
| C′ | same as C, in `ensure_output_format` | `server.py:1321-1339` | 11 |
| D | non-owner `elif remaining == 0 and _has_local_upstream_activity` | `client_manager.py:377-381` | 2 |
| E | non-owner `else` — publish `CLIENT_DISCONNECTED` | `client_manager.py:383-396` | 3 |
| F | lease-expiry promotion | `client_manager.py:361-364` | 3 |
| | **ceiling** | | **50** |

**50 is a ceiling on TOTAL statements in those ranges, not an always-missing figure.** The always-missing subset is strictly smaller — some of these lines are already covered — so **40 is the realistic planning figure and 45 the estimate**. Read the distinction rather than the number: conflating "statements in the range" with "statements still red" is exactly what produced this task's two earlier wrong figures.

**Both earlier figures were wrong, and the first was wrong in a way worth naming.** A draft said 70, which was the reachability brief's 66 — two *whole* functions' always-missing, owner arms included, which this task excludes. The correction said ~35, which was close to right **for the wrong reasons**: it undercounted gate C by ~18 and omitted `ensure_output_format` (B′ and C′) altogether, while over-crediting `client_manager`'s else-body by about the same amount. The errors cancelled. **A figure that is right because two mistakes cancel is worth no more than a wrong one**, and unlike a wrong one it propagates silently — see Task 12 Step 1, which now checks ranges and not only totals.

**Overlap with Task 9 is clean, and here is why, so nobody re-litigates it.** Task 9 Step 2's five functions are all in `channel_service.py`; Task 9 Step 3's `client_manager` ranges are `:301-306`, `:429-444` and `:465-482`. Gates A-C′ are in `server.py`, which Task 9 claims nowhere, and D/E/F at `:361-396` intersect none of Task 9's ranges. The one real double-count was Task 10 Step 3's "`channel_service` follower routes" against Task 9 Step 2's `change_stream_url` non-owner arm, and Step 3 below no longer claims it.

New file: `apps/proxy/live_proxy/tests/test_non_owner_branches.py`.

### Step 1: `server.ensure_output_profile` / `ensure_output_format`'s non-owner arms

- [ ] Gates **A, B, C** (`ensure_output_profile`) and **B′, C′** (`ensure_output_format`) need only a seeded `output_state`/`output_owner` key and a real Redis — `manager.start()` there deliberately fails to acquire the lock and never spawns. The **owner** arms spawn and are out of scope. Use the ranges in the table above, which are tighter than the brief's `:1461-1477`/`:1482-1518` and were measured, not read off.
- [ ] **`if not self.redis_client: return False` at `server.py:1454` and `:1303` is NOT this task's.** It is the `redis_client is None` guard idiom — kind 5 — and belongs to Task 7, which covers that idiom everywhere it repeats. It is excluded from the 50 above. Covering it here would double-count it against Task 7's 18.
- [ ] Use `RelayHarnessTestCase` for real Redis. Seed the owner key to a worker id that is **not** this process's, then call the function and assert it took the follower route: no `posix_spawn_proc` call (patch it and assert not called — patching the spawn is patching the sink), and the documented return.
- [ ] Re-derive the line numbers from `live-path.json` first; `server.py` is 1,492 statements and the brief's numbers are pre-2b-2.

### Step 2: `client_manager`'s non-owner arms — gates D, E and F

**Two traps here, both of which make the obvious fixture run the wrong branch.**

- [ ] **Trap 1 — seeding a foreign owner is not enough, because the code promotes you.** `client_manager.py:361-364` (gate F) re-acquires ownership mid-function:

  ```python
  am_i_owner = self.proxy_server and self.proxy_server.am_i_owner(self.channel_id)

  # Owner lock TTL can expire while local ffmpeg is still running on this worker.
  if (not am_i_owner and self.proxy_server
          and self.proxy_server._has_local_upstream_activity(self.channel_id)):
      if self.proxy_server.extend_ownership(self.channel_id):
          am_i_owner = True
  ```

  A fixture that seeds a foreign owner and stops there therefore runs the **owner** branch, and the test passes while asserting the opposite of its own docstring. **The fixture must control one of the two, and this plan specifies which: make `_has_local_upstream_activity` return `False`.** That is the honest non-owner shape — a worker with no local ffmpeg genuinely has no claim — whereas forcing `extend_ownership` to fail models a Redis failure and would silently also exercise gate F's failure path. Gate F gets its own test, with `_has_local_upstream_activity` **truthy** and `extend_ownership` returning `True`, asserting the owner branch ran *because of the promotion*.

- [ ] **Trap 2 — `:366-396` is a three-way, not a two-way.** `if am_i_owner:` / `elif remaining == 0 and _has_local_upstream_activity:` (gate D, `:377-381`) / `else:` (gate E, the publish, `:383-396`). A test that seeds `remaining == 0` to reach "the non-owner branch" lands in **D**, not in the publish arm, and D's product is `schedule_disconnect = True` plus a warning — not a publish. So:
  - **Gate E** (the publish) needs `remaining > 0`. Assert the `publish` call's channel (`RedisKeys.events_channel`) and the decoded JSON payload's `event`, `remaining_clients` and `username` fields, and assert the owner-side handler was **not** called.

    `remaining > 0` is **over-constrained on purpose**: gate E is in fact reachable with `remaining == 0` too, once `_has_local_upstream_activity` is `False` (the `elif`'s second conjunct fails and control falls to the `else`). Constraining it anyway makes the test independent of `_has_local_upstream_activity` entirely, so a future change to gate D's condition cannot silently move this test into gate D. Deliberate, not an oversight — leave it.
  - **Gate D** needs `remaining == 0` **and** `_has_local_upstream_activity` truthy **and** `extend_ownership` falsy. Assert the warning is logged and that `_spawn_on_hub(handle_client_disconnect, ...)` was scheduled, and that **nothing was published** — that last assertion is what separates D from E.

  **The two gates use different levers, and that is what makes them consistent rather than contradictory.** Gate E holds `_has_local_upstream_activity` False and is indifferent to `extend_ownership`; gate D needs it truthy and must therefore force `extend_ownership` falsy — the very lever gate E declines (Trap 1). Anyone reading the two fixtures side by side sees one test doing what the other refused to do; the reason is that each gate is reached by failing a *different* conjunct, so a single lever cannot serve both. Stated here because it reads as an inconsistency to anyone who notices it without the reasoning.

### Step 3: Reconcile with Task 9 — **this step adds no new statements**

- [ ] Task 9 Step 2 already covers `change_stream_url`'s non-owner arm, so `channel_service`'s follower routes are **not** a third source for this task and are not in its 45. Confirm from `live-path.json` that nothing non-owner-only in `channel_service` is still red after Task 9; if something is, it belongs in Task 9's file, not this one, and its statements go on Task 9's checkpoint rather than being counted twice.

### Step 4: Break-check and checkpoint

- [ ] **Three break-checks, one per gate — not one file-wide check.** An earlier draft prescribed a single break-check on `am_i_owner`, which cannot go red for gates A, B, B′ or D/E/F and would therefore manufacture a false finding under this plan's own "a break-check that does not go red is a finding" rule. Each break-check must name, in the commit or the PR, **which subset of this file's tests it turned red**; a break-check whose claimed blast radius exceeds what it can reach is the same defect as an assertion that pins nothing.

  | gate | break-check | must red |
  |---|---|---|
  | **A** — `existing is None` and `state != PROFILE_STATE_ACTIVE` | invert `existing is not None` at `:1438`, or force `state == PROFILE_STATE_ACTIVE` | the `server.py:1440-1453` tests only |
  | **B / B′** — `state == PROFILE_STATE_ACTIVE` and `owner_val != self.worker_id` | make `owner_val == self.worker_id` | `server.py:1464-1475` and `:1310-1311` |
  | **C / C′** — `not self.am_i_owner(...)` | `am_i_owner` → `True` unconditionally | `server.py:1483-1519` and `:1321-1339`, **plus every gate D/E/F test** |

  **C is the only one of the three whose blast radius crosses files, and it genuinely does reach D/E/F.** `ClientManager` reads ownership through `self.proxy_server.am_i_owner` at `client_manager.py:359`, so forcing it `True` also skips the lease-expiry promotion (gate F's `:364` never runs, because `not am_i_owner` is already false at `:361`) and takes the `if am_i_owner:` arm at `:367`, making gates D and E unreachable. So C's expected red set is larger than A's or B's by design — confirm that it is, rather than treating the extra failures as collateral. If the `client_manager` tests stay green under C, one of them is not on the branch it claims.

- [ ] Run the label, take the checkpoint, **compare against 45 — and against the gate table's ranges, not only its total** (Task 12 Step 1's rule). Commit.

---

## Task 11: Kind 10 — the boundary smalls

**Estimated: 24 statements** across `authorize.py` (12), `authorize_views.py` (4), `config_helper.py` (4), `control_plane.py` (3), `relay_client.py` (3), `apps.py` (2). Small error arms in modules already at 94-98%. Cheap, and these are the modules a Go port must match exactly.

New file: `apps/proxy/tests/test_boundary_error_arms.py`.

### Step 1: Enumerate from the measurement, not from this plan

- [ ] Read `live-path.json`'s `missing_lines` for each of the six modules and list every line.

- [ ] **`authorize.py` has drifted further than anything else in scope, and it is this task's largest single claim** (12 of the 24). Measured statically at `04841a47` against the reachability brief's `93900a6f` baseline: **188 → 205 statements, +17**. The brief's 12 always-missing lines are a reading of a file that has since gained 17 statements, so treat its line numbers as void here rather than approximate. Full drift table for the modules this plan targets, same method:

  | module | brief | now | Δ |
  |---|---:|---:|---:|
  | `apps/proxy/authorize.py` | 188 | 205 | **+17** |
  | `apps/proxy/next_source.py` | 329 | 341 | +12 |
  | `apps/proxy/authorize_views.py` | 108 | 114 | +6 |
  | `apps/proxy/live_proxy/output/ts/generator.py` | 377 | 378 | +1 |
  | `apps/proxy/live_proxy/client_manager.py` | 262 | 263 | +1 |
  | `apps/proxy/live_proxy/views.py` | 613 | 606 | **−7** |
  | `apps/proxy/relay_client.py` | 112 | 112 | 0 (before Task 1's +28) |
  | `apps/proxy/live_proxy/server.py` | 1492 | 1492 | 0 |

  `views.py`'s **negative** drift is the one to watch and affects Task 8 and Task 12's reserve, not this task: statements were *removed*, so a line the brief recorded as missing may no longer exist at all. A target that has vanished is not a target you failed to reach — say so in the "not closed" list rather than hunting for it.
- [ ] For each line, write one sentence saying what behaviour it produces. If you cannot, it goes in the PR's "not closed" list (R5, Global Constraint 15).

### Step 2: Write one test per arm

- [ ] Each asserts the arm's own product — the status code, the fixed body, the log's variable name — per the three-way policy CLAUDE.md documents for this boundary: `ImproperlyConfigured` propagates uncaught from the tune path; the five admin views answer with a **fixed body** that never echoes the exception text or the rejected value; five callers degrade exactly as they do for an unreachable relay, logging the variable name only.
- [ ] That last clause is itself an assertion worth making: for any arm that logs a misconfiguration, assert the log line contains the **variable name** and does **not** contain the rejected URL or any userinfo. A test that only checks the status code would pass with the URL leaked into the log, which is the defect this policy exists to prevent.

### Step 3: Break-check and checkpoint

- [ ] **Break-check:** make one admin view's handler include `str(exc)` in its response body and confirm the "fixed body" assertion fails. Revert.
- [ ] Run `python manage.py test apps.proxy.tests.test_boundary_error_arms`, take the checkpoint, compare against 24, commit.

---

## Task 12: Reconcile, and close the gap if one remains

**Estimated: whatever Tasks 3-11 left.**

### Step 1: Measure where you actually are

- [ ] Run `bash scripts/coverage_live_path_isolated.sh --report`. Record `missing`, `statements` and the per-file `missing_lines`.
- [ ] **When delivered statements match the estimate, check that they came from the ranges the estimate named.** A matching total over *different* ranges does not validate the estimate — it means two errors cancelled, and the surplus range is uncounted work that will go missing somewhere else. This is not hypothetical: Task 10's first correction landed at ~35 against a true ~45 by undercounting one gate by ~18, omitting two more entirely, and over-crediting a fourth by about the same amount. The total looked defensible and every component was wrong. Diff the **missing-line sets** per file against the ranges each task claimed, exactly as Global Constraint 10 requires for attributing a delta.
- [ ] Compute `single_round_missing - permitted` using Task 2's `permitted`. **Remember this is a single local round, and the floor is a CI worst.** The rule of thumb from the two censuses on record: a CI worst sits roughly 30-35 above a single round, and the 2a-7 history is that local understates CI by ~6 on top of that. **Treat the target as `permitted - 40`, not `permitted`.**
- [ ] If the single local round is already below `permitted - 40`, go to Task 13.

### Step 2: If a gap remains

- [ ] Draw on the reserve, in this order, and stop as soon as the margin is met:
  1. `views.py`'s `stream_ts` state branches and connection-retry loop (`:348-394` at the brief's measurement) — ~60. Seeded metadata hash with `generate_stream_url` patched to return `None` then a URL. Cover the `remaining_time <= retry_interval` break, the `gevent.sleep` + 25 ms back-off, the final attempt at the timeout boundary, and `control_plane.release_source` on the abandoned slot.
  2. `input/manager.py`'s `_wait_for_existing_processes_to_close` — 18 statements, **zero** in `except`, pure polling logic, no subprocess.
  3. `input/manager.py`'s `_close_socket` (23, 18 in except) and `_attempt_reconnect` (37) socket arms — mockable without the harness.
  4. `input/http_streamer.py` (21) — the Proxy stream profile. Needs an HTTP upstream stand-in, not ffmpeg; an in-process `http.server` makes it Tier A.
- [ ] **Do not** draw on `server.py`'s `cleanup_task` or `_cleanup_local_resources` (Global Constraint 9), and do not delete code or edit the rcfile (Constraints 6 and 8).
- [ ] If the reserve is exhausted and the margin is still not met, **stop and report to the orchestrator** with the current figure, the per-file residual, and what you judge the remaining pool to be. Do not weaken an assertion or target a forbidden function to close the last few statements.

---

## Task 13: The final CI census, and the floor

**This task writes the number D7 is measured against. Everything in it is procedure from `scripts/coverage_live_path.floor`'s own "HOW TO MOVE THIS FLOOR", steps 1-5.**

### Step 1: Freeze the branch

- [ ] No further commits to the branch until the census completes. A commit mid-census makes the rounds measurements of different trees. Record the SHA.

### Step 2: Run the census in CI

- [ ] Dispatch `backend-tests.yml` repeatedly on the branch, sequentially (the concurrency group cancels in progress). Read `this run missing=` from each `coverage-gate` job.
- [ ] **Stopping rule: maximum unchanged for ≥6 consecutive rounds, minimum 12 rounds.** Record every round, in order.
- [ ] Discard any round with a failed label; grep for #259's two strings first (R1).
- [ ] `M_final = max(rounds)`.

### Step 3: Check it against the gate before writing anything

- [ ] Recompute `permitted = S - ceil(0.8 * S)` from the census's own `statements`.
- [ ] **`M_final` must be ≤ `permitted`.** If it is not, the gate is not met: return to Task 12 Step 2 with the residual, and run the census again afterwards. Do not write a floor that does not meet ≥80% and do not describe the gate as closed.

### Step 4: Write the floor

- [ ] Run plain `bash scripts/coverage_live_path_isolated.sh --write-floor` once, from a writable checkout (`/repo` is read-only in the standard hook container), to get the file format, `shape`, `statements`, `modules`, `module_count` and `rcfile` machine-produced, and `scripts/coverage_live_path.floor.modules` rewritten to match.
- [ ] Hand-edit `missing` to `M_final` from Step 2 — `--write-floor` writes the figure from the run it just took, one run, not the worst of N — and recompute `percent = (1 - missing/statements) * 100` to match. This hand-edit is the documented step for this case, not a workaround.
- [ ] Replace the floor file's PROVENANCE block with this campaign's: the full round sequence in order, `max`, `min`, `spread`, `n`, the date, the SHA, and the sentence that the stopping rule was met at round N. **Keep the two earlier campaigns' blocks** — the file's own rule is that a floor which quietly forgets its earlier number cannot be audited.
- [ ] Add one sentence to the flappy-region paragraph recording what the reachability brief re-measured: two of the four named regions (the `channel_service.py` coordinated stop and the `input/manager.py` stderr-reader join) no longer flap at all, a third (`_wait_for_channel_ready`'s error branch) does not flap on this tree, both survivors are in `server.py`, and two regions on nobody's list do flap (`server.py:2014-2046` inside `cleanup_task`, and `input/http_streamer.py:153-161`).

### Step 5: Verify from the shape CI uses

- [ ] Re-run `bash scripts/coverage_live_path_isolated.sh --gate` from the ordinary **read-only** test-hook container and confirm exit 0 against the new floor before committing.
- [ ] Push and confirm `backend-tests.yml`'s `coverage-gate` job is green, and that its "Refuse a floor edited downward" step passes — note the polarity: `missing` is a maximum, so a **raised** value is the regression, and this PR lowers it.

### Step 6: Commit

- [ ] Stage `scripts/coverage_live_path.floor` and `scripts/coverage_live_path.floor.modules` together — the companion file is what lets a future `--gate` mismatch name files rather than show two unequal hashes.
- [ ] The commit message says which kind of move this is, in the floor file's own vocabulary: **"lowered the floor to N, campaign attached"**, plus whether a `--shape-only` re-baseline was also needed (Task 1 Step 6).

---

## Task 14: The spec, the tracker, the metrics, and the PR

### Step 1: Correct the spec's stale arithmetic

- [ ] `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, the `2b-4` row at line 1660, says the PR "closes the remaining **455** statements and moves the floor to the **1,595** the gate allows". Both are stale: 455 was arithmetic on a 7,978-statement denominator and 1,595 was `7978 - ceil(0.8 × 7978)`. Correct them in place to the measured figures, and add one sentence saying **why** the literal was wrong — the denominator moves whenever a statement is added to an already-included module, so a hard-coded permitted-missing figure goes stale on ordinary code edits and must be recomputed from the denominator at hand. Strike rather than delete, in this document's own convention.
- [ ] Same document, D7 (line 439) and § Stage 2a › Gate 2 (line 949): record that Gate 2's ≥80% threshold is **met**, at the measured percentage, in 2b-4, and that both halves of D7 are therefore green. Do not claim Gate 1 — that is 2b-3's.
- [ ] Same document, the `server.py` "222 unreachable or must not be targeted" figure: correct to **139** (`_cleanup_local_resources` still exactly 61, `cleanup_task` 78 rather than 161 — stage 2a halved it incidentally). This is the figure that made the five-biggest-files strategy look 100 statements short.

  **It appears at five sites, not one, and correcting one of them leaves the document contradicting itself.** Enumerated by `grep -n '222\|283'` at `04841a47`:

  | spec line | what it says | fix |
  |---|---|---|
  | 243 | "`server.py` alone contributes **222** statements that are unreachable or…" | → 139 |
  | 280 | "**222 of its missed statements are unreachable or must not be targeted at all**" | → 139 |
  | 1189 | 2a-5's row: "840 missed, **222 forbidden-or-unreachable**" | → 139 |
  | 1212 | "**blocked-or-unreachable is 283** — 61 more than the 222 previously carried" | **derived from the 222 and invalidated with it**; recompute and rewrite the clause, do not just swap the numeral |
  | 1432 | lists "the 283" among the derived figures | → whatever 1212 becomes |

  **Line 436 is NOT one of them** — its `283` is the tail of the line range `apps/proxy/utils.py:256-283` in D4, which is about `_live_connections` and is unrelated. Do not "fix" it. (Note that Task 1 moves that function, so if D4's range is worth updating it is for the relocation, not for this.)

### Step 2: The parity matrix

- [ ] `docs/relay-parity-matrix.md` — only if a test this PR added is a **better** reference for a row than the one recorded. Do not churn the matrix for the sake of it; Gate 1 closed in 2b-3 and this PR does not reopen it.

### Step 3: Metrics

- [ ] CLAUDE.md § Agent skills: a PR that closes a ledger issue, adds a `test.fail()` pin, merges a goal, or ticks a Done log updates `metrics/curated/` in the same PR. This one closes #266 and ticks Gate 2. Update the catalogue, the milestones and the defect ledger accordingly.
- [ ] `python -m metrics.build --validate-only` must pass.

### Step 4: Issues

- [ ] Close [#266](https://github.com/D10Scot/Dispatcharr/issues/266) from the PR body (`Closes #266`), noting that aborting remains the default and what the new per-label status line looks like.
- [ ] Do **not** close #259. Add a comment to it recording this PR's observed CI rate across two censuses (how many rounds were lost to it, out of how many) — that is a real measurement of the rate its own issue could only bracket at 1-in-32, and it is the data the eventual fix will be judged against.

### Step 5: The PR

- [ ] Open against `main` with `--repo D10Scot/Dispatcharr`. Branch is `migration/phase2b-coverage-80`, so every Playwright project runs.
- [ ] The description must carry, at minimum:
  - both censuses in full, in order, labelled **"sizing census — not a floor"** and **"floor census"**, each with `n`, `min`, `max`, `statements`, `permitted`, and the SHA;
  - the decision-rule band Task 2 selected, and the scope that followed;
  - a per-task table of estimated versus delivered statements — this is the record that tells the next campaign whether the reachability estimates were optimistic again;
  - the `_live_connections` relocation, stated as a **code move into the denominator, not an rcfile edit**, and whether a `--shape-only` re-baseline was needed;
  - the **not closed** list from R5/Constraint 15: every statement targeted and not reached, with the reason — including any target that turned out to have been *deleted* rather than missed (`views.py` lost 7 statements since the brief; see Task 11 Step 1's drift table);
  - **the break-check evidence: per new test file, which break-check was performed and the failure message observed.** Without this the break-checks live only in per-task steps and in Self-review item 6, neither of which reaches a reviewer — and a break-check nobody can see is indistinguishable from one nobody ran. This is the single most load-bearing line in the PR description, because it is the only evidence that ~200 new tests assert anything;
  - an explicit statement that `scripts/coverage_live_path.coveragerc` is untouched, that no code was deleted, and that **no `# pragma: no cover` was added**, so the number moved by covering code and not by redefining the measurement.
- [ ] Paste all three of these as evidence rather than asserting them:

  ```bash
  git diff main --stat -- scripts/coverage_live_path.coveragerc     # must be empty
  git diff main -- 'apps/proxy/**/*.py' | grep -c 'pragma'          # must be 0
  git diff main --stat -- 'apps/proxy/**/*.py'                      # Task 1's move, and nothing else
  ```

  The pragma count is the one that would otherwise go unchecked anywhere in this repo: Global Constraint 8 records why neither `modules=` nor `rcfile=` can see a pragma, so this grep is the only thing standing between the plan's rule and a silent denominator edit.

---

## Self-review

Before reporting this PR complete, answer each of these in writing:

1. **Is the gate actually met?** `M_final ≤ permitted`, where `permitted` was recomputed from the census's own `statements` — not copied from this plan, the spec or the brief. Show the arithmetic.
2. **Was the floor measured where it is enforced?** Every round in the floor census came from a `coverage-gate` job, not from a local container. Show the run URLs.
3. **Did any round with a failed label reach the floor?** It must not have. Say how many rounds were discarded and why.
4. **Did the measurement's definition change?** `scripts/coverage_live_path.coveragerc` untouched, no code deleted, no `exclude_lines`, **no `# pragma: no cover`**. Show the empty diff *and* the zero pragma count — the pragma is the only one of the four that neither shape hash can see, so it is the only one where "I did not do that" is the sole check unless you run the grep.
4b. **Did a break-check that could not go red get recorded as one?** Two in this plan were caught at review: Task 6's byte-ladder break-check named the rung boundary rather than the divisor, and Task 10's named `am_i_owner` for arms gated on `owner_val != self.worker_id`. Both would have turned an implementer's correct test into a suspected fault. For each break-check you ran, confirm the line you edited is the line the assertion actually reads.
5. **Are the forbidden functions still red?** `cleanup_task` and `_cleanup_local_resources` were not targeted. Confirm from `live-path.json`.
6. **Pick three tests at random from the ones you wrote and break the production code they claim to pin.** Do all three go red, for the right reason? If any goes green, that test is hollow and so, probably, are its neighbours — audit the whole file it came from.
7. **For every `except`-body test: does its assertion distinguish that arm from its neighbour?** If two arms' tests would both pass with the arms swapped, you covered two statements and pinned nothing.
8. **Can you state, in one sentence each, the behavioural claim of every test file added?** If not, R5 was violated and coverage became the oracle.
