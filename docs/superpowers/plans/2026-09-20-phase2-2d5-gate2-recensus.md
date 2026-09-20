# Phase 2 stage 2d-5 — the Gate 2 re-census

**Goal.** Make Gate 2's ratchet mean something again. Stage 2d-4 deleted 29 of the coverage gate's
38 modules and re-baselined the floor's *shape* with `--write-floor --shape-only`, which by design
never touches `missing` — so the floor left on `main` permits **1,525** missed statements over a
denominator measured at **1,281**. The floor is larger than the thing it bounds: every conceivable
run passes, including one that covers nothing at all. This PR takes the ≥12-round **CI** census the
floor's own procedure prescribes, writes `missing` from its worst round, records the sequence, and
corrects the four sentences in the tree that describe the gate's old number.

**It is a small diff and a long procedure.** Six files change, two of them by comment alone. Twelve or more CI rounds produce the
one number in them.

**Architecture.** Django 6 + DRF control plane; a stdlib-only Go relay (`relay/`) serving the whole
live surface through nginx since 2d-3. After 2d-4 the Gate 2 denominator is nine Python files — the
Phase 1 boundary the Go relay calls on every tune: `authorize.py`, `authorize_views.py`,
`control_plane.py`, `internal_auth.py`, `internal_base_url.py`, `next_source.py`, `permissions.py`,
`relay_client.py`, `relay_serializers.py`. That is exactly the code D7 cared about; the re-scope
keeps enforcement over it rather than retiring the gate at the moment it becomes the only Python on
the live path.

**Tech stack.** Python 3 / Django 6 / DRF, bash, GitHub Actions.

**Spec.** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, § Stage 2d
`### Deletion order — one PR each` **entry 5** (`migration/phase2d-gate2-recensus`), as amended by
**A10.4** (which created this PR), **A10.14** (the test-file dispositions this census inherits) and
**A14.5** (which moved the rcfile edit into 2d-4 and left this PR the number alone). § Stage 2a ›
Gate 2 carries the census procedure's origin; `scripts/coverage_live_path.floor`'s own
**HOW TO MOVE THIS FLOOR** section carries the procedure itself and this plan follows it step for
step. This plan's own amendment is **A15**, in Appendix D.

**Branch.** `migration/phase2d-gate2-recensus` — the name the spec gives it. R13 rules on the cost
of the `migration/**` prefix for a six-file PR and why it is accepted rather than renamed.

---

## THIS PLAN IS WRITTEN AGAINST A TREE THAT DOES NOT EXIST YET

**Measurement seed: `7fc4ddbde9982b9cb666d57ca26f52c6cef92ce1`** (`main`, 2026-09-20, the merge of
#328 — the 2d-4 *plan*). Every `file:line`, hash and count below was opened and measured there.

**Implementation seed: the squash-merge of 2d-4** (`migration/phase2d-delete-live-proxy`,
plan `docs/superpowers/plans/2026-09-20-phase2-2d4-delete-live-proxy.md`), which merges after 2d-3
and before this PR. That tree does not exist at the time of writing. Two consequences run through
the whole plan:

1. **The plan's own central numbers — `statements` and `missing` — cannot be measured before 2d-4
   lands, and this plan does not pretend otherwise.** Every step that needs them derives them from
   the run rather than quoting them. What the plan *does* carry is a **measured reference band**
   (R4) taken at the measurement seed over the same nine files, so a census round that lands far
   outside it is recognisable as a finding rather than accepted as the answer.
2. **Every appendix that edits a file 2d-4 also edits is an anchored script, not a line-anchored
   diff** (Appendices B, C, D), in 2d-2's and 2d-3's idiom: `assert count == 1` on every anchor,
   and the anchor text is 2d-4's own replacement text where 2d-4 rewrote the sentence. The one
   appendix that is a plain diff (Appendix A) edits a file 2d-4 does not touch at all — verified:
   `grep -n 'coverage_live_path\.sh' <the 2d-4 plan>` returns nine hits, all citations, and none is
   an edit.

**What Task 0 verifies before anything else** — and STOPs on: that 2d-4 merged; that the floor's
shape fields are what 2d-4 predicted; that `statements` is still `8073` (R2 — this looks like a
mismatch and is not); and that the nine modules are the nine.

---

## Global Constraints

Numbered so a task step can cite one. **A conflict between a constraint and a task step is a STOP
and report, never a judgement call.**

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The shell's
   cwd is shared or correlated across concurrent agents (`CLAUDE.md` § Repository and direction).
2. **`set -o pipefail` on every pipeline whose emptiness or exit status you intend to read**, and
   never `2>/dev/null` a git query you will interpret. `git show "${ref}:path"` with braces, always.
   **And note the polarity trap in this plan's own verification steps: `grep -c` prints `0` and
   *exits 1* when there are no matches, and in seven steps below `0` is the PASS.** Run those greps
   as bare commands and read the number, or append `|| true`; chaining one with `&&` under `set -e`
   aborts on success. The steps that expect `0` say so individually.
3. **Stage and commit in separate Bash calls**, and write the commit message with the Write tool,
   committing with `git commit -F <file>`. The commit gate matches on command text.
4. **The floor's `missing` comes from CI and from nowhere else.** A local round is for design, for
   attribution and for sanity — never for the number. This floor was first set from a 21-round
   *local* census whose maximum the very first CI run exceeded (`scripts/coverage_live_path.floor`,
   the 2a-7 provenance block). Restating it because this PR is the one with the most reason to be
   tempted: the local number here is stable to the statement (R5), which makes it look more
   authoritative than it is.
5. **A failed label invalidates a round; it does not degrade it.** A tree missing `hypothesis` once
   reported 3,230 statements where the same tree with it reported 3,169 — a 61-statement inflation
   moving the way a regression moves. A round with any non-`success` coverage job is **discarded and
   not counted**, not averaged in and not recorded as a low draw (R7).
6. **`shape=`, `modules=` and `module_count=` must not move in this PR.** They are 2d-4's; if
   `--write-floor` rewrites any of the three to a different value, that is a finding about the tree,
   not a number to commit (Task 5 Step 4). **`shape` and `modules` are equality checks in `gate()`;
   `module_count` is not** — it is printed inside the `modules` mismatch diagnostic
   (`scripts/coverage_live_path.sh:337-339`) and never compared. It still must not move, for the
   same reason `modules` must not: the two are written together and a `module_count` that disagreed
   with the list would be evidence of a broken write, not of a wider scope. **`rcfile=` moves exactly once,
   by design** — R15's comment-only rcfile edit, recomputed by the same `--write-floor` command that
   writes the number, and never by hand.
7. **No production code is edited.** This PR changes `scripts/coverage_live_path.sh` (a comment and
   a label list, R10), `scripts/coverage_live_path.coveragerc` (two comment sentences, R15),
   `scripts/coverage_live_path.floor`, `scripts/coverage_live_path.floor.modules`, `CLAUDE.md` and
   the spec. Nothing under `apps/`, `relay/`, `docker/`, `e2e/` or `frontend/`. A step that appears
   to need one of those is a STOP.
8. **No test is added or deleted**, so there is no break-check in the usual sense, and Task 1 says
   so explicitly rather than leaving its absence to be noticed. **Two things are nonetheless
   verified by running, not by reading**, because both are guards whose failure is silent: the
   script's no-argument path, run before and after Appendix A (Task 1 Step 3), and the census
   driver's duplicate-round refusal, run against a real run id before the first round (Task 3
   Step 3). The second is the more important of the two — a duplicate round is unfalsifiable after
   the fact except by auditing `census.tsv`, which Task 3 Step 7 also does.
9. **The branch is frozen for the duration of the census.** A commit mid-census makes the rounds
   measurements of different trees. Task 3 records the frozen SHA and Task 4 checks every harvested
   round against it.
10. **Every count in this plan was measured at the measurement seed and names the command that
    produced it.** A count that does not match at Task 0 is a STOP, except the ones R2 explicitly
    marks as expected to have moved at 2d-4.
11. **A channel UUID and a provider URL are secrets.** Neither appears in a log, a test, a commit
    message or the PR body.
12. **`missing` may fall freely and may never rise.** The floor is a maximum. `--write-floor`
    refuses to write a worse one without `COVERAGE_LIVE_PATH_ALLOW_REGRESSION=1`
    (`scripts/coverage_live_path.sh:443-452`); **that variable is not set anywhere in this PR**, and
    a step that appears to need it is a STOP.
13. **Appendices B, C, D, E and F are scratchpad files, never repository files.** Write each to
    `<scratchpad>/impl-2d5/` and run it from the worktree root
    (`cd <worktree> && python3 <scratchpad>/impl-2d5/appendix_c.py`). They are `.py` and `.sh`
    helpers for this PR, not deliverables: writing one into the tree would fire the `*.py`
    credential-logging hook, add a file to the diff, and break Task 8 Step 5's "no `*.py` in the
    diff" check. Nothing in `File structure` lists them, and that is the assertion.


---

## Rulings

Each was measured at the measurement seed. The command is given where a number is.

### R1 — this PR writes five floor fields, plus one more R15 adds

`write_floor()` (`scripts/coverage_live_path.sh:414-540`) writes two disjoint sets:

| passed | fields written |
|---|---|
| `--write-floor --shape-only` | `shape`, `modules`, `module_count`, `rcfile` |
| `--write-floor` (plain) | those four **plus** `statements`, `missing`, `percent`, `measured`, `runs` |

2d-4 ran the first. This PR runs the second, so the four shape fields are rewritten — three of them
to the values they already hold, because the module set does not move here (Constraint 6). **The
fields that actually change are `statements`, `missing`, `percent`, `measured`, `runs` — plus
`rcfile`, which moves once and deliberately** because R15 corrects two comment sentences in the
coveragerc and `rcfile=` hashes that file's bytes. `shape`, `modules` and `module_count` come out
byte-identical.

`--shape-only` is **not** the mode for this PR and the reason is structural, not stylistic: it never
calls `read_totals()` at all (`:440-455`), so there is no ratchet figure for it to write. The floor's
own header says the same thing in as many words — *"a real `missing` move has no 'fewer fields'
version."*

### R2 — Task 0's shape check, and the one field that looks wrong and is not

**Predicted floor on the implementation seed** (2d-4's R9 and Appendix H.1, re-derived here rather
than copied — see below):

| field | value | who wrote it | this PR |
|---|---|---|---|
| `shape` | `per-container/v1-sysmon` | 2a-7 | rewritten to the same value |
| `statements` | **`8073`** | 2b-4 | **rewritten, and this is the point** |
| `missing` | `1525` | 2b-4 | **rewritten from the census** |
| `percent` | `81.11` | 2b-4 | recomputed |
| `measured` | `2026-09-13` | 2b-4 | today's date |
| `runs` | `12` | 2b-4 | the census's `n` |
| `modules` | `7804792af4f7` | 2d-4 | unchanged (Constraint 6) |
| `module_count` | `9` | 2d-4 | unchanged |
| `rcfile` | `fadc95a2c8ae` | 2d-4 | **moves once**, by R15's comment-only edit |

**`modules=7804792af4f7` and `module_count=9` are independently confirmed here**, not taken from the
2d-4 plan. The gate hashes `sorted(json["files"].keys())` with `sha256(...).hexdigest()[:12]`
(`scripts/coverage_live_path.sh:216-236`), and over the nine surviving include entries:

```
python3 -c "import hashlib; n=sorted('''apps/proxy/authorize.py apps/proxy/authorize_views.py \
apps/proxy/control_plane.py apps/proxy/internal_auth.py apps/proxy/internal_base_url.py \
apps/proxy/next_source.py apps/proxy/permissions.py apps/proxy/relay_client.py \
apps/proxy/relay_serializers.py'''.split()); \
print(hashlib.sha256('\n'.join(n).encode()).hexdigest()[:12], len(n))"
→ 7804792af4f7 9
```

**`rcfile=fadc95a2c8ae` is a prediction with a caveat.** It is `sha256` of the coveragerc's bytes
after 2d-4's Appendix H.1 is applied — measured by extracting that appendix from the merged 2d-4
plan, `git apply`-ing it at the measurement seed and hashing the result. It is therefore correct
**only if H.1 lands byte-identically**, which a review fix round could legitimately change (a
reworded comment moves the hash and moves nothing else). So Task 0 treats a `rcfile=` mismatch as
**informational**: record it and continue. A `modules=`/`module_count=` mismatch is a **STOP** — those
two bind the denominator's identity, and a different value means the module set is not the nine this
plan measured.

**`statements=8073` on a nine-module tree is expected, not a bug.** `--shape-only` does not write
`statements` (`:516-520`: the field is inside the `if not shape_only` branch), so 2d-4 left 2b-4's
8,073 sitting over a denominator an order of magnitude smaller. It is recorded provenance and never
compared (`gate()` prints it as "informational"), so nothing failed because of it — but a reader of
the floor between 2d-4 and 2d-5 sees a denominator that is wrong by a factor of six, and **this PR
is what corrects it.**

> **Finding against the 2d-4 plan, recorded rather than acted on** (it is not this PR's to change,
> and it fails safe): 2d-4's **Task 9 Step 5** instructs the implementer that
> `git diff scripts/coverage_live_path.floor` "must show changes to **`statements`**, `modules`,
> `module_count` and `rcfile` only". `--shape-only` cannot change `statements`. Following that step
> literally, the implementer will see `statements` unchanged and may read it as a failed write. The
> step's load-bearing half — that `missing`, `percent`, `measured` and `runs` are byte-identical —
> is correct and is what actually matters. Relayed to the orchestrator; Task 0 Step 4 below is
> written so that this plan is not surprised by it either way.

### R3 — what covers the nine now: the four `apps/proxy/tests/` dispositions, and the two 2d-4 found by executing

A10.4 requires this PR's plan to **state which disposition each affected test file received**,
because "whether 2d-4 deletes, rewrites or merely un-imports each of them changes the denominator's
coverage before a single round is measured." 2d-4's R7 settled seventeen files across four labels.
Only the two labels in `backend-tests.yml:180`'s coverage matrix can affect this census —
`apps.proxy.tests` and `apps.channels.tests` — so the table below is those two, in full, with the
**effect on the nine** named for each.

| # | File | Label | 2d-4 disposition | Effect on the nine |
|---|---|---|---|---|
| 9 | `apps/proxy/tests/test_boundary_error_arms.py` | proxy | **SPLIT** — 13 of 15 kept, the two `LiveProxyAppsReadyTests` deleted; its one import re-points to `apps.proxy.config_helper` | **The largest single contributor, and it survives.** Its docstring says it exists to cover "error arms in already-96%+ boundary modules", and the 13 kept tests drive `authorize.py`, `control_plane.py` and `relay_client.py` directly. The two deleted tests drive `LiveProxyConfig.ready()`, which is not in the denominator. |
| 10 | `apps/proxy/tests/test_combined_stats.py` | proxy | **SPLIT** — `BuildLiveChannelStatsDataTests` (3) deleted, `CombinedStatsApiTests` (4) kept | The kept four reach `relay_client.list_channels`; the deleted three drove a `live_proxy` builder. Net effect on the nine: the surviving half is the half that touches them. |
| 11 | `apps/proxy/tests/test_relay_status_shape.py` | proxy | **DELETE** (10) | Drove the two `ChannelStatus` builders inside the deleted package against a hand-rolled fake Redis. Touches none of the nine. |
| 12 | `apps/proxy/tests/test_stream_switch.py` | proxy | **SPLIT** — 9 deleted, `ChangeStreamViewTests` (2) kept | The deleted nine drove `ChannelService`'s owner/follower split. The kept two drive `ts_admin_views.change_stream`, outside the denominator. |
| 16 | `apps/proxy/tests/test_relay_control_api.py` | proxy | **DELETE** (23) | **The one with real reach into the nine** — it exercised the five `/proxy/relay/…` routes end to end, which run through `internal_auth.py`, `permissions.py` and `relay_serializers.py`. Measured cost: **two statements** (R4). |
| 17 | `apps/proxy/tests/test_internal_base_url.py` | proxy | **REWRITE**, kept (8) | Pins `internal_base_url.py`, one of the nine, and stays. Its one rewritten test asserts *both* directions of the dev address after 2d-4's R1 change — a better pin than the one it replaces. |
| 1 | `apps/channels/tests/test_channel_stream_reuse.py` | channels | **KEEP**, one import re-pointed | Drives `Channel._stream_assignment_is_reusable()` with `relay_client.channel_snapshot` mocked — reaches `relay_client.py` through the mock boundary. |
| 2 | `apps/channels/tests/test_get_stream_assignment.py` | channels | **KEEP**, two imports re-pointed | Same boundary. |
| 3 | `apps/channels/tests/test_recording_pipeline.py` | channels | **KEEP**, two patch strings re-pointed | One of 29 tests touches the relocated `ConfigHelper`; none of the nine. |
| 4 | `apps/channels/tests/test_ts_proxy_ghost_clients.py` | channels | **DELETE** (13) | All thirteen inside the deleted package. |
| 5 | `apps/channels/tests/test_ts_proxy_initializing.py` | channels | **SPLIT** — 14 deleted, `PreActiveStateTests` (7) kept | Constant-shape tests; none of the nine. |
| 6 | `apps/channels/tests/test_ts_proxy_keepalive.py` | channels | **SPLIT** — 17 deleted, `KeepaliveTimingTests` (2) kept | None of the nine. |
| 7 | `apps/channels/tests/test_ts_proxy_keepalive_duration.py` | channels | **DELETE** (4) | None of the nine. |
| 8 | `apps/channels/tests/test_ts_proxy_teardown.py` | channels | **DELETE** (52) | The largest file in the set. Three of its 52 patch `apps.proxy.control_plane.release_source` — a surviving module — but they patch it, so they execute none of its body; 2d-4's R7 records the contract they asserted as independently pinned by `apps/proxy/tests/test_next_source_api.py`, which survives. |

The other three of the seventeen are in labels outside the coverage matrix
(`tests/test_websocket_consumer_filter.py`, `tests/test_ci_test_routing.py`,
`core/tests/test_fetch_channel_stats.py`) and cannot affect this measurement at all.

**The summary a reader needs:** the tests that cover the nine are overwhelmingly *kept*. Of the
seventeen dispositions, exactly one deletion (#16) reaches into the denominator, and R4 measures
what it costs. **This table's per-file reasoning is confirmed, not relied on**: R4's second
measurement composes *all* of these dispositions — the five whole-file deletions and the 45 tests
removed from the five SPLIT files — and the answer is the same two statements, so the SPLIT rows'
"none of the nine" claims are a measurement rather than an argument. This is not luck — the boundary modules were covered by 2b-4's own campaign, which
targeted them deliberately, and the deleted tests are the live-relay ones.

### R4 — the measured reference band, and why it is a reference and not the answer

**Measured at the measurement seed**, `7fc4ddbd`, in two containers (`plan2d5-proxy`,
`plan2d5-channels`), one Django label each, under the script's own shape
(`per-container/v1-sysmon`) — i.e. exactly the post-2d-4 label set, run against the pre-2d-4 tree.
The per-file figures come from the combined run's `live-path.json`, summed over the nine:

| file | statements | missing |
|---|---|---|
| `apps/proxy/authorize.py` | 205 | 0 |
| `apps/proxy/authorize_views.py` | 191 | 4 |
| `apps/proxy/control_plane.py` | 124 | 1 |
| `apps/proxy/internal_auth.py` | 65 | 0 |
| `apps/proxy/internal_base_url.py` | 44 | 0 |
| `apps/proxy/next_source.py` | 375 | 26 |
| `apps/proxy/permissions.py` | 7 | 0 |
| `apps/proxy/relay_client.py` | 139 | 0 |
| `apps/proxy/relay_serializers.py` | 131 | 0 |
| **total** | **1281** | **31** → **97.58%** |

`apps/proxy/relay_views.py` measured 64 statements / 0 missing on the same run and is **excluded**:
2d-4's R1 deletes it.

**Second measurement: every one of 2d-4's test dispositions in the two coverage labels, composed.**
Not just the whole-file deletions — **all five wholly-deleted files plus the 45 tests 2d-4 removes
from the five SPLIT files**, so the composition is complete rather than partial:

| kind | what was removed |
|---|---|
| whole files (5) | `test_relay_control_api.py`, `test_relay_status_shape.py`, `test_ts_proxy_ghost_clients.py`, `test_ts_proxy_keepalive_duration.py`, `test_ts_proxy_teardown.py` |
| classes (5 files, 45 tests) | `test_combined_stats.py::BuildLiveChannelStatsDataTests` (3); `test_boundary_error_arms.py::LiveProxyAppsReadyTests` (2); `test_stream_switch.py::{OwnerPathTests,NonOwnerPathTests}` (9); `test_ts_proxy_initializing.py::StreamManagerFinallyBlockTests` (14); `test_ts_proxy_keepalive.py::{OwnerWorkerKeepaliveTests,NonOwnerWorkerKeepaliveTests,DoStatsUpdateTests,ClientRemoveIntegrationTests}` (17) |

Both labels re-run, both `^OK`; the tree was restored and `git status` verified clean afterwards.
The nine measured **1281 / 33 / 97.42%**, and the missing-line sets are identical to the run with
only the five whole files removed. The two added missing statements are named:

- `apps/proxy/relay_client.py:132` — `headers["Content-Type"] = "application/json"`, the
  POST-with-payload arm.
- `apps/proxy/relay_client.py:339` — `return ChannelSnapshot(present=False, active=False,
  reachable=True)`, the "relay answered, channel absent" arm.

Both were reached only by `test_relay_control_api.py`. **So the entire coverage cost of 2d-4's
seventeen dispositions, over the nine modules, is two statements — and the 45 tests deleted from the
SPLIT files cost zero, measured rather than argued.** (An earlier draft of this ruling composed only
the five whole-file deletions and left R3's per-file reasoning to carry the SPLIT half; a review
asked whether the composition was complete, and the answer is now a measurement.)

**What the composition still does NOT include**, and neither does any local measurement:

- 2d-4's **production-code** changes (the three listed below), which move the denominator.
- The three affected test files in labels outside the coverage matrix
  (`tests/test_websocket_consumer_filter.py`, `tests/test_ci_test_routing.py`,
  `core/tests/test_fetch_channel_stats.py`) — they cannot reach this measurement at all, because
  `coverage-label`'s matrix runs only `apps.proxy.tests` and `apps.channels.tests`.
- The **re-pointed imports** in the KEEP files: the composed tree still imports from
  `apps.proxy.live_proxy`'s shims, where the post-2d-4 tree imports from `apps/proxy/`'s own
  modules. Behaviour-identical by construction (2d-4's R7 row 3: the shim re-exports the same class
  object), and neither path is in the denominator.

**Why this is a reference band and not a prediction of the census figure.** Three things still move
between the measurement seed and the implementation seed, all of them 2d-4's:

- `internal_base_url.py` gains a `dev_url` parameter (2d-4 R1) — a few statements, in the
  denominator, on a covered path.
- the three `url_utils` importers re-point at `apps.proxy.next_source` (2d-4 R3) — may add
  statements to `next_source.py`, which carries 26 of the 31 missing.
- 2d-4's own review fix round may move anything.

**And Constraint 4 stands regardless.** The band's job is to make a wild CI round recognisable. The
plan's expectation, stated so it can be wrong: `statements` in the low 1,300s, `missing` in the low
tens, `percent` above 95%. **A CI round outside `missing` ∈ [20, 80] is attributed per file before
it is written to anything** (Task 4 Step 3).

### R5 — the census is predicted to be deterministic, and that prediction is itself the finding to check

The floor's header records a **104-statement flappy set**, measured first-hand from 2b-4's twelve
retained CI artifacts. Every one of those 104 statements is inside `apps/proxy/live_proxy/`:
`server.py` (73), `input/manager.py` (17), `input/http_streamer.py` (2), `live_proxy/utils.py` (2),
`input/buffer.py` (3), `output/fmp4/manager.py` (3), `output/fmp4/buffer.py` (1),
`output/fmp4/generator.py` (1), `output/profile/manager.py` (1), `output/ts/generator.py` (1).
**73 + 17 + 2 + 2 + 3 + 3 + 1 + 1 + 1 + 1 = 104, and not one of them is in one of the nine.**

The mechanism agrees: the spread came from gevent background housekeeping still running while
unrelated tests executed, and from the harness's real subprocess tunes — both inside the deleted
label. Four local rounds at the measurement seed drew **1281 / 31** every time, and the 38-module
total drew **7767 / 4691** every time, to the statement.

**This changes nothing about the procedure.** Twelve rounds are still taken, in CI, under the
stopping rule. What it changes is what a non-flat sequence *means*: on a tree whose known variance
sources are all deleted, **a round that differs from its neighbours is a finding to attribute, not
noise to absorb** — and Task 4 Step 4 says so. The floor's own CAVEAT applies in the other
direction too: unobserved-to-vary is not proof of stability, only absence of observed variance in
the sample.

### R6 — how a CI round is produced, waited for, harvested and validated

**Produced by `workflow_dispatch`, one at a time.** `backend-tests.yml` carries a
`workflow_dispatch` trigger with a `full_suite` boolean (`:19-23`). The dispatch is:

```
gh workflow run backend-tests.yml --repo D10Scot/Dispatcharr \
  --ref migration/phase2d-gate2-recensus -f full_suite=false
```

**`full_suite=false`, deliberately, and it does not touch the measurement.** With `false`, the
`plan` job takes `git diff --name-only HEAD~1 HEAD` (`:66-69`) and resolves labels from it, so the
`test` matrix is the two labels the branch's tip commit routes to — not fifteen. The **coverage**
jobs are unaffected either way: `coverage-label`'s matrix is hard-coded at `:180` and deliberately
*not* taken from `plan.outputs.labels`, for exactly the reason the comment at `:165-170` gives ("a
PR touching only apps/epg/ would measure a different label set and the floor would compare
quantities that are not comparable"). So a `full_suite=false` round runs **7** jobs — `plan`, two `test`, two `coverage-label`,
`coverage-gate`, `Backend result` — where `full_suite=true` runs about twenty, and produces a
byte-for-byte equivalent coverage measurement.

**This is why Task 1 comes before the census.** `full_suite=false` selects labels from the tip
commit's own paths, so the branch's tip at census time must be a commit that routes somewhere.
`scripts/coverage_live_path.sh` matches `_PATH_ALIASES`' `"scripts/coverage_live_path"` entry
(`dispatcharr/test_discovery.py:58`, no trailing slash) and therefore selects both coverage labels.
Task 1's commit *is* the census anchor. **If for any reason the tip commit routes to no label,
`plan` sets `has_tests=false`, all three coverage jobs skip, and the round is not a round** —
Task 3 Step 3's first check catches this by name.

`gh run rerun` was considered and rejected: a rerun is a new *attempt* on the same run id, so the
earlier rounds' logs move behind `--attempt` and harvesting twelve of them becomes fiddly for no
saving. A dispatch gives each round its own run id.

**The run id comes from watching the list change, never from `--limit 1` after a sleep.** This is
the one place a census can corrupt itself silently. `gh workflow run` does **not** return a run id,
so the obvious idiom is "sleep, then take the newest `workflow_dispatch` run". If GitHub has not yet
registered the new run, that returns the **previous round's** id — which is already `completed`, so
the wait returns instantly, the frozen-SHA check passes, all three coverage jobs read `success`, and
**the previous round's `missing` is appended a second time as a fresh row**. The stopping rule is
"maximum unchanged for ≥6 consecutive rounds", so a duplicate is a free fake observation of
stability: it makes the rule easier to satisfy in exactly the direction that ends the census early.
Nothing downstream can detect it, because the two rows are identical in every field a reader looks
at.

**Two defences, both cheap, and the plan takes both:**

1. **Capture the newest `workflow_dispatch` run id BEFORE dispatching and poll until it changes.**
   That is the id of this round, positively identified rather than inferred from a timer.
2. **Assert the harvested `run_id` differs from every row already in `census.tsv`.** `run_id` is
   already a column. It catches the failure even if defence 1 is subverted by something this plan
   has not thought of. **Written `grep -qx "$RUN" < <(cut -f2 "$LOG")`, never `cut … | grep -qx`**:
   under `pipefail` the pipeline form fails OPEN, because `grep -q` exits on the match, `cut` takes
   SIGPIPE and exits 141, and pipefail makes 141 the pipeline's status — a found duplicate reading
   as "not found". Measured, deterministically, from about 2,000 rows up. A real `census.tsv` is
   12-20 rows and would have worked, which is exactly why the pipeline form could not stay: this
   guard has no second chance, and its correctness must not rest on the pipe buffer.

Appendix E implements both. **Task 3 Step 3 is the break-check, and it uses a 20,000-row file on
purpose** — at census scale the broken form passes, so a break-check sized to a real campaign would
have been a test that cannot fail (Constraint 8).

**Waited for to completion, not to the gate.** `backend-tests.yml`'s concurrency group is
`backend-tests-<workflow>-<ref>` with `cancel-in-progress: true` (`:30-32`), so dispatching round
N+1 while round N is still running **cancels whatever of round N is left**. 2b-4's census advanced
as soon as `Coverage gate` concluded and clipped three of its twelve runs' downstream jobs; the
floor's header spends 23 lines explaining the resulting cosmetic damage. With five jobs a round,
waiting costs little:

```
gh run watch "$RUN_ID" --repo D10Scot/Dispatcharr --exit-status || true
```

(`|| true` because a non-`success` overall conclusion is not by itself a reason to stop — R7 decides
validity from the job set.)

**Harvested from the `Coverage gate` job's log.** Two gh mechanics, both verified at the measurement
seed against run `35512184360`:

```
JOB=$(gh run view "$RUN_ID" --repo D10Scot/Dispatcharr --json jobs \
        --jq '.jobs[] | select(.name=="Coverage gate") | .databaseId')
gh run view --repo D10Scot/Dispatcharr --job "$JOB" --log | grep -E 'this run missing=|denominator:'
```

which prints, verbatim:

```
coverage_live_path: denominator: floor 8073 statements  this run 7767 statements (informational ...)
coverage_live_path: floor missing=1525  this run missing=1474  coverage 81.02%
```

Two traps, both hit while verifying this:

- **`gh api repos/.../actions/jobs/<id>/logs` refuses**: *"the response contains terminal escape
  sequences; pass --allow-escape-sequences to output it anyway"*, exit 1. `gh run view --job --log`
  has no such problem and is what this plan uses.
- **A skipped job's log is a 404 / empty output, not an error you will notice.** The first harvest
  attempt above returned nothing because that run's coverage jobs were `skipped` (a docs-only diff).
  Task 3 Step 3 therefore asserts the three coverage jobs' `conclusion` **before** reading any log —
  an empty grep must never be read as "the number was not printed".

**Cross-validated, incidentally:** that same CI run reported `this run 7767 statements`, and the
local reference run at the same seed reported `statements 7767`. The *denominator* reproduces
exactly between local and CI. Only `missing` does not — which is precisely the split Constraint 4
rests on.

### R7 — the stopping rule, and what invalidates a round

**The rule, from the floor's own header, unchanged:** dispatch until **the maximum has been
unchanged for ≥6 consecutive rounds, with ≥12 rounds total**. `missing = max(rounds)`. **Record every
round, in order** — a bare min/max cannot show the rule was met.

**A round is valid iff all three coverage jobs concluded `success`:**
`Coverage apps.proxy.tests`, `Coverage apps.channels.tests` and `Coverage gate`. Anything else and
the round is **discarded, not counted, and not recorded as a draw** — it is recorded in the campaign
log as discarded, with the reason.

**The run's own top-level conclusion is not a validity signal.** The floor's header establishes this
for 2b-4's rounds 5 and 8, whose workflow-run conclusion read `cancelled` while all 22 of their jobs
succeeded. Judge the job set.

**A failure in the plain `test` matrix does not invalidate the coverage figure** but does fail
`Backend result`. Record it; it must be green on the final push (Task 8), and a *reproducible* one
is a blocker for the PR even though it leaves the census sound.

**#259's two known flakes cannot fire here.** `scripts/coverage_live_path_isolated.sh:73-76` tells a
census-taker to grep a failed label's log for `never observed the lead at all` or
`too few distinct speeds` before investigating coverage. Both strings live in exactly one file —
`apps/proxy/live_proxy/tests/test_manager_stderr_failover.py:257` and `:333` (measured:
`grep -rn` over `--include='*.py'` returns those two lines and nothing else) — which 2d-4 deletes
with the package. **So on this tree a failed coverage label is a genuine finding, not a known
flake**, and the plan says so rather than carrying forward advice that can no longer apply.

**If the maximum is still moving at round 12**, keep going (2a-7's own census ran to 15 for this
reason) and record the extra rounds. **`runs` in the floor is the number of VALID rounds** — the
ones `missing` was taken from — not twelve and not the number of dispatches. Discarded rounds stay
in `census.tsv` with their reason, because the campaign log is provenance and a discarded round is
part of what happened, but they are not counted in `runs` and not in the sequence the floor
header prints.

### R8 — how the floor is written: plain `--write-floor`, then the documented hand-edit

The floor's **HOW TO MOVE THIS FLOOR**, steps 3-5, applied without deviation:

1. **Plain `--write-floor` once**, to get the file format, `shape`, `statements`, `modules`,
   `module_count` and `rcfile` machine-produced and `scripts/coverage_live_path.floor.modules`
   rewritten to match. It writes the `missing` from the run it just took, which is one run and
   almost never the worst of N.
2. **Hand-edit `missing` to `max(rounds)`** and recompute `percent = (1 − missing/statements) × 100`.
   The header is explicit that this is "the honest, documented step for THIS case, not a
   workaround", and that teaching `--write-floor` to accept an explicit value was considered and
   declined.
3. **Re-run `--gate` from the ordinary read-only container** — the shape CI runs it in — and confirm
   exit 0 before committing.

**Where `--write-floor` runs, spelled out because the standard container cannot host it.**
`write_floor()` refuses a read-only `$FLOOR_FILE` with its own message (`:431-438`), and
`.claude/hooks/start-test-container.sh:36` mounts the repo `:ro`. Two facts make this easy anyway:

- **`--write-floor <dir>` needs no Postgres, no Redis and no Django** — it calls `combine_from`,
  then `report()` (combine + report + json), then writes. Only `coverage` and the source files.
- **It must still run inside a container, not on the host.** Coverage data files record the paths
  they measured, which are `/repo/...` inside the container, and the committed rcfile has no
  `[paths]` section — the same fact [#312](https://github.com/D10Scot/Dispatcharr/issues/312)'s
  second operational note records. Combining container-produced data on a macOS host makes
  `coverage report` fail to find a single source file.

So: one throwaway container with the tree mounted **rw** and no stores at all. Task 5 Step 2 carries
the exact `docker run`.

**`COVERAGE_LIVE_PATH_RUNS` must be exported**, or `runs=0` is written
(`:495`, `${COVERAGE_LIVE_PATH_RUNS:-0}`). `scripts/coverage_live_path_isolated.sh:98-104` forwards
it by name into the container precisely because a host-side export does not otherwise reach a
`docker exec`.

**The "Refuse a floor edited downward" CI step passes by construction and the polarity is worth
saying aloud.** `backend-tests.yml:325-340` fails when head's `missing` is **greater** than base's.
This PR lowers it (1525 → tens). A raised value is the regression; a lowered one is the point.

### R9 — the floor's header: 2d-4's slack banner goes, a provenance block arrives, the earlier ones stay

Three edits, all in Appendix B, all anchored:

1. **Delete 2d-4's twelve-line banner** (`** THIS FLOOR IS DELIBERATELY SLACK BETWEEN 2d-4 AND
   2d-5 …`). Leaving it would be the worst outcome available: a floor that says its own number is
   not a measurement, sitting above a number that now is.
2. **Correct the flappy-set paragraph in place.** It opens *"**104 statements flap across this
   campaign's own 12 CI rounds**"* and attributes all 104 to files that no longer exist. It is not
   deleted — it is the record of how the previous number was earned, and the file's own rule is that
   a floor which quietly forgets its earlier number cannot be audited — but it gains a leading
   sentence saying every one of those 104 statements was inside `apps/proxy/live_proxy/` and that
   stage 2d-4 deleted the whole set, followed by this campaign's own measured spread.
3. **Insert a PROVENANCE block above 2b-4's**, in the file's established shape: the full round
   sequence in order, `max`/`min`/`spread`/`n`, the date, the tree SHA, the sentence saying at which
   round the stopping rule was met, the statement move (8,073 → the measured figure) with its cause,
   and the percentage — *recorded*, not claimed as a target (R11).

All three keep the prior campaigns' blocks untouched.

### R10 — `scripts/coverage_live_path.sh`'s `LABELS` array still names the deleted label, and 2d-5 is where it dies

**Measured:** `scripts/coverage_live_path.sh:97` is
`LABELS=(apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests)`, and **2d-4 does not
edit this file** — `grep -n 'coverage_live_path\.sh'` over the merged 2d-4 plan returns nine hits,
every one a citation (`:440-455`, `:458-540`, `:216-236`) or an invocation, and its R10 table edits
`scripts/coverage_live_path_isolated.sh:25-28`'s `PAIRS` list, `backend-tests.yml:180`'s matrix,
`dispatcharr/test_discovery.py` and the hook, but not this array.

**What breaks, precisely.** The array has exactly one caller: the script's no-argument path
(`:579-605`), which is the first invocation its own usage block lists. After 2d-4,
`manage.py test --keepdb apps.proxy.live_proxy.tests` fails, `run_label()` returns non-zero, and the
no-argument path prints *"label(s) failed under coverage"* and *"THE FIGURES BELOW ARE INVALID"* and
exits 1. **Loud, not silent** — the #266 fix is doing its job — but the documented default
invocation is broken, and the person most likely to hit it is whoever next tries to reproduce this
gate by hand.

**Ruling: fixed here** (Appendix A), for three reasons:

1. It is Gate 2's own measurement script — this PR's exact subject, not adjacent work.
2. A census-taker running the bare script locally for attribution gets an invalid round, which is
   the failure mode this whole PR exists to prevent one level up.
3. It is the commit that makes R6's cheap dispatch shape route to the right labels.

The edit is a comment block, a usage line and one array entry. **The rest of the file's historical
prose is deliberately not touched** — the `68 FEWER missed statements` paragraph, the tracer-core
note and the 7,978/3,977/50.15% baseline all cite deleted code, and all three are *history of why
the guard exists*, which stays true. They are 2d-6's consolidation, **and Appendix A's added
comment says so in the file itself** — naming those three notes and the files they attribute to, so
a maintainer reading `scripts/coverage_live_path.sh` after this PR is told they describe the
pre-2d-4 tree. A deferral stated only in a plan appendix is invisible to the person who will next
open the script.

### R11 — the percentage is recorded, never targeted; and `stream_routes.py` stays out of the rcfile

**No percentage target is set.** D7's ≥80% was a threshold over the 38-module denominator, met at
2b-4 and not re-opened. The ratchet is `missing`, and `percent` in the floor is derived from it, not
the other way round. The census's percentage is recorded in the floor header, in CLAUDE.md and in
the PR body; it is not written into the gate.

**On the brief's contingency — "if the nine-module coverage is far below 80%, say so plainly":** it
is not, and the plan says so with its evidence. The measured reference is **97.58%** (97.42% with
the five wholly-deleted files removed), so D7's intent — coverage over the code the Go relay depends
on — is comfortably served by the re-scope. **The contingency is kept live anyway**: Task 4 Step 5
requires the implementer to state the measured percentage plainly in the PR body and, if it is below
80%, to say so in the PR body *and* in A15 rather than quietly writing a floor that the spec's own
threshold would have failed.

**`apps/proxy/stream_routes.py` is deliberately not added to the denominator.** 2d-4's R9 declined
it and left the question open for this PR, in the rcfile's own comment ("2d-5's re-census may take
it") — which is where R15 records the answer. **Declined here too**, on
its own merits: 2d-4's Appendix O makes the module's two callables *exist to be resolved, never to be
called* — nginx routes both paths to the Go relay, and in the one shape without nginx (`dev`) the Go
relay serves them on its own port. Their bodies are therefore unreachable by design, so including
the file would raise `missing` by a fixed amount **no test could ever close**, which is the one thing
a ratchet must not contain. Adding it would also move `modules=` in the same PR that moves `missing`
— mixing the two kinds of move the floor's header spends a page separating. If a later PR wants it,
that is a `--shape-only` move plus a fresh census, and A15 records it on the post-2d list.

### R12 — the sentences this PR makes false or supersedes, and the one it inherits already false

**CLAUDE.md § Testing, three edits** (Appendix C):

1. 2d-4's own replacement sentence — *"**Between 2d-4 and 2d-5 the floor's `missing` is deliberately
   slack**: … `migration/phase2d-gate2-recensus` carries the ≥12-round CI census that makes it
   real"* — becomes the census result. This PR is what that sentence is waiting for.
2. *"**The floor's `missing` is set from the worst of ≥12 runs measured in CI … three regions are
   known to flap: the owner-side coordinated stop (`channel_service.py` 28-49 and `server.py`'s
   sweep), the non-owner local cleanup (`server.py` 2099-2112, 2489-2566) and the stderr-reader join
   (`input/manager.py` 1739-1767). Per-container isolation makes the first block deterministic and
   does **not** make the total so (spread 44 vs 47)."* — every file cited is deleted at 2d-4, and
   this PR measures the replacement spread. **2d-4 does not touch this sentence** (measured: `grep -n
   'three regions are known to flap\|spread 44'` over the 2d-4 plan returns nothing), so it is this
   PR's.
3. *"**Stage 2a ended at 74.30%, not the spec's ≥80%**; the shortfall is owned by `2b-4` and D7 still
   blocks every 2c PR until it closes."* — **already false before this PR**, by two stages: 2b-4
   closed it at 81.11% and 2c is complete. **Corrected here anyway, and the reason is disclosed
   rather than assumed: no other PR in this stage will take it.** Spec § Stage 2d entry 6 scopes
   2d-6 to *"every `apps/proxy/live_proxy/` reference in § Architecture, § Known defects,
   § Testing rewritten or removed"* — and this sentence contains no such reference, so deferring it
   most likely loses it entirely. It is also the last sentence of the same § Testing paragraph whose
   other two sentences this PR rewrites, and it is about this gate's own number, so 2d-5 is where a
   reader would look for it. One sentence, flagged in the PR body as an out-of-strict-scope
   correction. *(An earlier draft justified this by calling it "the sentence immediately following"
   the one this PR rewrites. Measured on the post-2d-4 CLAUDE.md, the paragraph runs A2 → "Per-container
   isolation…" → "A failed label invalidates…" → A3, so A3 is two sentences later, not adjacent. The
   edit is right; that reason was not — and "immediately following" was wrong under either way of
   counting where A2's anchor ends.)*

**The spec, four in-place corrections and one insertion** (Appendix D):

| where | what | fix |
|---|---|---|
| § Stage 2d deletion list, entry 5 | *"under the stopping rule `scripts/coverage_live_path.floor:283-312` prescribes"* | the **line numbers are already wrong**: 2d-4's Appendix H.2 inserts twelve lines above them, and this PR's own header edits move them again. Replaced with a **name-based** citation to the floor's `HOW TO MOVE THIS FLOOR` section, plus the DONE marker and the measured result. |
| same entry | *"the ten survivors are executed in large part by the ~564 tests PR 4 removes"* | **nine** survivors (A14.1 deleted `relay_views.py`); the `~564` is left as the historical measurement it is, as 2d-4's R7 already records. |
| same entry | *"four of the thirteen affected test files are under `apps/proxy/tests/`"* | **seventeen** files, per A14.3 — and **six** of them are under `apps/proxy/tests/`, not four. |
| § Stage 2a › Gate 2 | the blockquote ends at *"MET in 2b-4 … the floor file now records `missing=1,525`"* | gains a **RE-SCOPED in 2d-5** paragraph in the same idiom, so a reader of that section is not left with 8,073/1,525 as live figures. |
| A10.4 | *"a `--shape-only` re-baseline there leaves a floor of 1525 over a denominator of perhaps a tenth that — mechanically green, substantively toothless"* | the prediction **understated it**, and the measurement is worth recording: the floor exceeded the entire denominator. One sentence appended. |

**Amendment A15** is inserted immediately before `## Stage 2d`, landing after A14 without needing
A14's text — 2d-3's and 2d-4's idiom. The Done-log row is appended as the **last row of the table**,
anchored on `"\n## Risks\n"` with `assert head.rstrip().endswith("|")` — **2d-3's idiom, not
2d-4's.** (2d-4's Appendix N inserts its Done-log entry as a bullet immediately after the section's
intro line, i.e. *above* the table header, which is a departure from the four rows already in the
table. Recorded as a finding for the orchestrator; it does not affect this PR, because the table's
last line is still a `|` row either way and the assertion still holds.)

### R13 — the branch name, and what `migration/**` costs a six-file PR

The spec names `migration/phase2d-gate2-recensus` and the plan does not rename it. The prefix makes
`e2e-tests.yml` run **every** Playwright project including `lifecycle-upgrade`, plus both bash
suites in `lifecycle-tests.yml`, path filters bypassed.

**Accepted, and the cost is smaller than it looks**, because of where it is paid:

- The heavy matrices trigger on the **`pull_request`** event (opened/synchronize — a draft PR
  raises both), not on `workflow_dispatch` of `backend-tests.yml`. `e2e-tests.yml`'s `push:` is
  `branches: [main]` with a `paths:` filter, so pushing the census branch triggers nothing on
  `push` at all. Either way the twelve-plus census rounds cost `backend-tests.yml` only.
- This plan pushes **three times**: the census anchor (Task 1), the floor and docs (Tasks 5-7), and
  at most one fix round. Three full E2E matrices, not fifteen.
- The PR touches no `e2e/`, `docker/`, `relay/` or `apps/` path, so every heavy job is running the
  same code that is green on `main`.

Renaming to dodge the matrix would also break the spec's own branch table, which every Done-log row
keys on.

### R14 — no `metrics/curated/` edit, and why

`docs/agents/metrics.md`'s standing rule fires when a PR closes a ledger issue, adds a `test.fail()`
pin, merges a goal, or ticks a Done log. This PR does none:

- **No metric tracks Gate 2's floor.** `metrics/curated/catalogue.yml`'s coverage family is
  `backend_coverage` (`/backend_line_pct`, the daily whole-backend collector) and
  `frontend_coverage`; measured with `grep -n 'coverage' metrics/curated/catalogue.yml` — no id
  reads `scripts/coverage_live_path.floor`.
- **No ledger row cites a file this PR touches.** 2d-4 re-pointed the three `defects.yml` rows that
  named deleted test files (A10.15).
- **The milestone ROW for stage 2d is a post-merge one-liner**, A9.9's standing reason: a merge
  commit cannot name its own SHA. The phase-level milestone belongs to 2d-6's close-out, not here.

`python -m metrics.build --validate-only` is therefore **not** in this PR's gate, and Task 8 says so
rather than running a check whose subject is untouched.

### R15 — the rcfile's own comment says the gate is toothless, and it moves `rcfile=` to fix it

**The trap, and it is a sequencing trap rather than a content one.** 2d-4's Appendix H.1 ends the
coveragerc's comment block with two sentences this PR makes false:

```
# value. 2d-5's re-census may take it. THE FLOOR'S `missing` IS DELIBERATELY
# SLACK UNTIL THEN -- see scripts/coverage_live_path.floor's header.
```

**Ruling: corrected here**, comment-only, and the correction is where a future reader will actually
look for the `stream_routes.py` answer — the config file that would have carried the line.

**`rcfile=` hashes the file's raw BYTES, not its resolved file set** (`scripts/coverage_live_path.sh:268-273`),
so a comment edit moves it and `gate()` compares it for equality. Three consequences, and the third
is the one that would have cost a whole census:

1. **The edit is free in this PR and only in this PR.** Plain `--write-floor` recomputes `rcfile=`
   in the same command that writes the number, so the hash and the bytes can never disagree. The
   floor's own header already blesses exactly this case — *"Tripping on a comment-only edit to the
   rcfile is an accepted false positive: that file is edited rarely and deliberately, and a spurious
   re-baseline there costs one `--write-floor --shape-only` run"* — and here it costs not even that.
2. **The diff must be comment-only, and Task 5 Step 4 asserts it**: no `include`, `omit`, `source`
   or `exclude_lines` line may change. A definition change hiding inside a "comment" edit in the PR
   that sets `missing` is the single cheapest way to make this ratchet easier, and `rcfile=` exists
   to catch it — so the assertion is on the diff, not on the hash.
3. **It must land AFTER the census, never before.** The census rounds run `--gate` in CI against the
   floor as it stands, whose `rcfile=` is 2d-4's. Editing the rcfile in Task 1's census-anchor commit
   would make `coverage-gate` exit 1 on **every single round** with "scripts/coverage_live_path.coveragerc's
   bytes changed" — twelve invalid rounds, each looking like a coverage problem and none being one.
   Task 5 Step 0 is therefore where Appendix F runs, immediately before `--write-floor`, and Task 1
   Step 2 says explicitly that the rcfile is not touched there.

The measurement is unaffected either way: a comment changes no statement.

---

## File structure

```
scripts/
  coverage_live_path.sh              MODIFIED  Task 1 — the LABELS array and two comments (R10, Appendix A)
  coverage_live_path.coveragerc      MODIFIED  Task 5 — two comment sentences, NOTHING else (R15, Appendix F)
  coverage_live_path.floor           MODIFIED  Tasks 5-6 — five fields, rcfile=, + the header (R8, R9, Appendix B)
  coverage_live_path.floor.modules   REGENERATED by --write-floor in Task 5; contents expected IDENTICAL
CLAUDE.md                            MODIFIED  Task 7 — three sentences in § Testing (R12, Appendix C)
docs/superpowers/specs/
  2026-09-09-phase2-go-relay-design.md
                                     MODIFIED  Task 7 — Amendment A15, four in-place corrections,
                                               the Done-log row (R12, Appendix D)
```

**Six files. No new file, no deleted file, no test.**

The coveragerc's presence here is a **comment-only** edit (R15), and its `[run]`/`[report]` sections
are byte-identical afterwards. A14.5 gave the *include list* to 2d-4 and R11 declines to add
`stream_routes.py`; a diff that changes an `include`, `omit`, `source` or `exclude_lines` line means
something went wrong.

---

## Task 0: verify the seed

**Nothing is edited in this task.** Every check that fails is a **STOP and report**, except the two
marked informational.

- [ ] **Step 1 — the worktree.**
      `git -C /Users/dion/git/Dispatcharr fetch origin`, then
      `git -C /Users/dion/git/Dispatcharr worktree add /Users/dion/git/Dispatcharr/.worktrees/impl-2d5 -b migration/phase2d-gate2-recensus origin/main`.
      Record the head SHA. **Everything below runs with `cd /Users/dion/git/Dispatcharr/.worktrees/impl-2d5 &&` in front of it** (Constraint 1).

- [ ] **Step 2 — 2d-4 merged.** All four must hold:
      ```
      test ! -d apps/proxy/live_proxy && echo "package gone"
      test ! -f apps/proxy/relay_views.py && echo "relay_views gone"
      grep -n 'apps.proxy.live_proxy' dispatcharr/settings.py    # read the output; see below
      python3 -c "import sys; sys.path.insert(0,'.'); from dispatcharr.test_discovery import iter_test_package_labels as f; L=f(); print(len(L)); print('\n'.join(L))"
      ```
      The label count must be **15** and `apps.proxy.live_proxy.tests` must not be among them —
      that is the real assertion, and the `grep -n` is diagnostic only: a surviving *comment* naming
      the removed entry is not a failure, a surviving `INSTALLED_APPS` **string** is. If the package
      is still there, 2d-4 has not merged and this plan cannot start — **STOP**.

- [ ] **Step 3 — the rcfile's `include` block names nine files and no directory.**
      ```
      sed -n '/^include =/,/^omit =/p' scripts/coverage_live_path.coveragerc | grep -c 'apps/proxy/'    # → 9
      sed -n '/^include =/,/^omit =/p' scripts/coverage_live_path.coveragerc | grep -c 'live_proxy'     # → 0
      sed -n '/^include =/,/^omit =/p' scripts/coverage_live_path.coveragerc | grep -c 'relay_views'    # → 0
      wc -l < scripts/coverage_live_path.floor.modules               # → 9
      grep -c '^apps/proxy/live_proxy/' scripts/coverage_live_path.floor.modules   # → 0
      ```
      **Three of these expect `0`, which `grep -c` prints while exiting 1** (Constraint 2). Run them
      bare and read the numbers; do not chain them with `&&`.
      **Scoped to the `include` block, not the whole file, and that is not fussiness:** 2d-4's own
      comment block names both `apps/proxy/live_proxy/*` and `relay_views.py` while explaining that
      it removed them, so a whole-file `grep -c 'live_proxy'` returns **2** and `relay_views`
      returns **1** on a perfectly correct tree. Measured on a simulated post-2d-4 tree; the first
      draft of this step expected 0 for both and would have STOPped a correct implementation.

- [ ] **Step 4 — the floor's nine fields, against R2's table.**
      ```
      grep -E '^(shape|statements|missing|percent|measured|runs|modules|module_count|rcfile)=' \
        scripts/coverage_live_path.floor
      ```
      | field | expected | on mismatch |
      |---|---|---|
      | `shape=per-container/v1-sysmon` | exact | **STOP** |
      | `modules=7804792af4f7` | exact | **STOP** — the module set is not the nine this plan measured |
      | `module_count=9` | exact | **STOP** |
      | `missing=1525` | exact | **STOP** — 2d-4 was supposed to leave it untouched |
      | `percent=81.11`, `measured=2026-09-13`, `runs=12` | exact | **STOP**, same reason |
      | `statements=8073` | exact | **informational.** It is *expected* to still read 8073 over a nine-module tree — `--shape-only` never writes it (R2). If it reads something else, record the value and continue; this PR overwrites it either way. |
      | `rcfile=fadc95a2c8ae` | predicted | **informational.** A different value means 2d-4's Appendix H.1 landed with different bytes (a reworded comment does this). Record it, verify it against the rcfile on disk with the one-liner below, and continue. |
      ```
      python3 -c "import hashlib;print(hashlib.sha256(open('scripts/coverage_live_path.coveragerc','rb').read()).hexdigest()[:12])"
      ```
      This must equal whatever `rcfile=` says. If the two disagree, the floor and the rcfile have
      drifted — **STOP**, `--gate` would fail on it.

- [ ] **Step 5 — start the two containers.** They are needed from here on: this step's gate run,
      Task 1 Step 3's before/after evidence, Task 2's reference rounds and Task 5's write all use
      them. Per `CLAUDE.md` § Test hooks, the shared `dispatcharr-testrunner` is **not** yours:
      ```
      for s in proxy channels; do
        DISPATCHARR_TEST_CONTAINER=impl2d5-$s DISPATCHARR_TEST_DB_VOLUME=impl2d5-$s-hookdb \
        CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/impl-2d5 \
        /Users/dion/git/Dispatcharr/.claude/hooks/start-test-container.sh
      done
      ```
      `scripts/coverage_live_path_isolated.sh` addresses them as `${COVERAGE_ISOLATED_PREFIX}-proxy`
      and `-channels`, so every invocation below carries `COVERAGE_ISOLATED_PREFIX=impl2d5`. Both are
      removed in Task 8 Step 9.

- [ ] **Step 6 — the gate is green and slack, and the slack figure is recorded.**
      `COVERAGE_ISOLATED_PREFIX=impl2d5 bash scripts/coverage_live_path_isolated.sh --gate` (it needs
      **both** containers — its `PAIRS` list is two entries after 2d-4's R10). Expect exit 0 and a
      large "FEWER missed than the floor" figure. **Record it in the campaign log**: it is the slack
      this PR removes, and the PR body quotes it.

- [ ] **Step 7 — the `LABELS` bug is still there** (R10):
      ```
      grep -n 'LABELS=' scripts/coverage_live_path.sh
      ```
      must print `LABELS=(apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests)`.

      **If it does not — if 2d-4's fix round already fixed it — Appendix A no longer applies.** Drop
      Task 1 Step 2 and keep Task 1's commit, which still has to exist as the census anchor (R6) and
      still has to route to both coverage labels. **Make it a comment-only edit to
      `scripts/coverage_live_path.floor`'s header** — one sentence recording that the census is in
      progress and what it is for. That path routes to both labels through the same
      `("scripts/coverage_live_path", …)` alias, and a floor *comment* cannot disturb a round:
      `gate()` reads the floor only through `floor_value()`'s `grep -E "^$1="`
      (`scripts/coverage_live_path.sh:275`), so nothing but a `key=value` line is ever parsed, and
      unlike the coveragerc the floor's bytes are not hashed by anything.
      **Do NOT fall back to a CLAUDE.md edit**: measured,
      `labels_for_changed_paths(['CLAUDE.md'])` is `[]`, so `plan` would set `has_tests=false`, the
      coverage jobs would skip, and every round would need `full_suite=true` — ~15 test jobs instead
      of 2, twelve or more times over, for a measurement that is identical either way.
      Record the change of plan in the PR body and report it to the orchestrator before proceeding.

- [ ] **Step 8 — the routing is two labels.**
      ```
      python3 -c "import sys;sys.path.insert(0,'.');from dispatcharr.test_discovery import labels_for_changed_paths as f;print(f(['scripts/coverage_live_path.sh']));print(f(['scripts/coverage_live_path.floor']))"
      ```
      Both must print `['apps.channels.tests', 'apps.proxy.tests']`. This is what makes R6's
      `full_suite=false` dispatch shape work. **STOP** on anything else.

- [ ] **Step 9 — the anchors exist.** Run each of Appendices B, C, D and F in `--check` mode (each
      script takes `--check` and asserts every anchor is present exactly once, writing nothing).
      Expect `ok, 3 anchors` / `ok, 3 anchors` / `ok, 7 anchors` / `ok, 1 anchor`.
      **Any anchor that is absent or duplicated is a STOP** — it means 2d-4 landed different text
      than this plan was written against, and the appendix must be re-derived before it is run.
      (All four were verified this way against a *simulated* post-2d-4 tree — see Self-review — so a
      failure here is real news about 2d-4's fix round, not an expected wobble.)

- [ ] **Step 10 — `git apply --check --whitespace=error` Appendix A.** Clean, or STOP.

---

## Task 1: the census anchor commit — `scripts/coverage_live_path.sh`

**Files:** `scripts/coverage_live_path.sh`. **Ruling:** R10. **This commit must exist before the
census starts** (R6).

- [ ] **Step 1 — no test is added here, and that is deliberate** (Constraint 8). The change is a
      label list and two comments in a script that has no test of its own anywhere in the tree
      (`grep -rn 'coverage_live_path.sh' --include='*.py' .` returns only
      `tests/test_ci_test_routing.py`'s *routing* assertions, which are about the path, not the
      contents). Step 3 is the verification, by running it.
- [ ] **Step 2 — `git apply` Appendix A**, and **nothing else**. In particular
      `scripts/coverage_live_path.coveragerc` is NOT touched here: a comment edit there moves
      `rcfile=`, and `coverage-gate` would then exit 1 on every census round with "the coveragerc's
      bytes changed" — twelve invalid rounds that look like a coverage problem and are not (R15).
      That edit is Task 5 Step 0.
- [ ] **Step 3 — run the thing that was broken.** In `impl2d5-proxy` (started in Task 0 Step 5; it
      carries its own Postgres and Redis, which the script's no-argument path needs):
      ```
      docker exec impl2d5-proxy bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; \
        export DJANGO_SECRET_KEY=hook-test-secret; cd /repo && rm -rf /tmp/bare && \
        COVERAGE_LIVE_PATH_DATA_DIR=/tmp/bare bash scripts/coverage_live_path.sh'
      ```
      One container is right here and two would be wrong: this is the script's **own** no-argument
      path, which runs every label in one container by design — the opposite of the per-container
      shape `--gate` requires. Nothing measured here is floor-eligible; the assertion is the exit
      status and the two `OK` lines, not the figure.
      Expect exit 0, two `OK` lines, and a final `coverage_live_path: statements …  missing …`
      line. **Before the fix this exits 1 with "label(s) failed under coverage:
      apps.proxy.live_proxy.tests" and "THE FIGURES BELOW ARE INVALID"** — run it that way first, on
      the unfixed file, and paste both outputs into the PR body. That is this task's evidence, and
      it is the closest thing to a break-check a comment-and-array change admits.
- [ ] **Step 4 — commit.** Message: `test(gate2): the bare coverage script names a label 2d-4
      deleted`. Body says what R10 says: one caller, loud not silent, CI unaffected, and that it is
      also the census anchor.
- [ ] **Step 5 — push and open the DRAFT PR** against `main`, titled
      `chore(phase2): 2d-5 — the Gate 2 re-census`. Draft, because the body cannot be written until
      the census is over.

---

## Task 2: the local reference round

**Not floor-eligible.** Constraint 4. This exists so Task 4 can recognise a wild CI round.

- [ ] **Step 1 — the containers are already running.** `impl2d5-proxy` and `impl2d5-channels` were
      started in **Task 0 Step 5** and have been used by Task 0 Step 6 and Task 1 Step 3. Confirm
      with `docker ps --filter name=impl2d5 --format '{{.Names}}'` (two lines) rather than starting
      them again — `start-test-container.sh` does a `docker rm -f` first, so re-running it here would
      throw away the Postgres the earlier steps warmed. They are removed in Task 8 Step 9.
- [ ] **Step 2 — one round** via `COVERAGE_ISOLATED_PREFIX=impl2d5 bash
      scripts/coverage_live_path_isolated.sh --report`. (After 2d-4's R10 edit its `PAIRS` list is
      two entries, `proxy` and `channels`, matching the container names above.) **Both labels must
      report `^OK`**; a failed label invalidates it (Constraint 5).
- [ ] **Step 3 — record `statements` and `missing`.** Compare with R4's reference: `statements` in
      the low 1,300s, `missing` in the low tens. **If `missing` is outside [20, 80], stop and
      attribute it per file** before dispatching a single CI round — something about the tree is not
      what this plan measured.
- [ ] **Step 4 — take two more rounds.** R5 predicts an identical figure all three times. Record all
      three in the campaign log. **This is not the census and does not shorten it**; three identical
      local rounds are an input to reading the CI sequence, nothing more.

---

## Task 3: freeze, and run the CI census

**Ruling:** R6, R7. **Constraint 9 governs this whole task.**

- [ ] **Step 1 — freeze.** Record `git rev-parse HEAD`. **No commit to the branch until Task 4
      completes.** Every harvested round is checked against this SHA.
- [ ] **Step 2 — the campaign log.** Create `<scratchpad>/impl-2d5/census.tsv` with one row per
      dispatch: `round<TAB>run_id<TAB>head_sha<TAB>proxy<TAB>channels<TAB>gate<TAB>missing<TAB>statements<TAB>verdict`.
      `verdict` is `valid` or `discarded: <reason>`. **This file is the provenance the floor header
      quotes** and it is written as the census runs, never reconstructed afterwards.
- [ ] **Step 3 — the driver, and its break-check BEFORE the first real round.** Write Appendix E to
      `<scratchpad>/impl-2d5/round.sh`. It establishes the run id by polling until the newest
      `workflow_dispatch` id **changes**, and refuses any id already present in `census.tsv` (R6).
      **Break-check, run rather than read** — the duplicate guard is the one defence whose failure is
      invisible after the fact, and **it must be checked on a file large enough to expose the
      SIGPIPE fail-open**, not on the two-row file an earlier draft of this plan used:
      ```
      python3 -c "open('/tmp/dup.tsv','w').writelines(['1\t35512184360\tx\n'] + \
        ['%d\t%d\tx\n' % (i, 90000000000+i) for i in range(2, 20001)])"

      # 1. the form this plan ORIGINALLY shipped, which the review caught -- must print MISSED
      bash -c 'set -uo pipefail; cut -f2 /tmp/dup.tsv | grep -qx 35512184360 \
                 && echo "old form: DETECTED" || echo "old form: MISSED (fails open)"'
      # 2. the form Appendix E uses -- must print DETECTED
      bash -c 'set -uo pipefail; grep -qx 35512184360 < <(cut -f2 /tmp/dup.tsv) \
                 && echo "new form: DETECTED" || echo "new form: MISSED"'
      # 3. and must not false-positive
      bash -c 'set -uo pipefail; grep -qx 99999999999 < <(cut -f2 /tmp/dup.tsv) \
                 && echo "FALSE POSITIVE" || echo "new form: new id accepted"'
      ```
      Expected, in order: **`old form: MISSED (fails open)`**, `new form: DETECTED`,
      `new form: new id accepted`. **If line 1 prints DETECTED, the break-check is not biting** —
      raise the row count until it does, and say so; the threshold is machine-dependent (measured
      here: ≤1,000 rows detects, ≥2,000 misses). **A real `census.tsv` is 12-20 rows and is below
      that threshold**, so this check demonstrates the mechanism rather than a live failure — which
      is the honest reading, and the reason the guard was changed anyway (R6).

      Then, on the branch's **first** dispatch only, confirm the polling defence by watching the
      driver's own `newest before dispatch = <none>` line — a branch with no prior
      `workflow_dispatch` prints nothing and exits 0. Paste all four outputs into the PR body.
- [ ] **Step 4 — one round.** `bash <scratchpad>/impl-2d5/round.sh <N> <frozen-sha> <census.tsv>`.
      Repeat until Task 4's stopping rule is met. The driver asserts, in this order and before
      reading any log:
      1. A **new** run id appeared (not the one that was newest before the dispatch). If none does
         within five minutes it exits 1 and records nothing.
      2. That id is **not already in `census.tsv`**. A duplicate is refused, not recorded.
      3. `headSha` equals the frozen SHA. If not, the branch moved — Constraint 9 was broken; stop.
      4. `Coverage apps.proxy.tests`, `Coverage apps.channels.tests` and `Coverage gate` all read
         `success`. **Any `skipped` here means `plan` selected no labels and the round is not a
         round** — check the tip commit's paths against Task 0 Step 7 before dispatching again.
         Any `failure`/`cancelled` and the round is `discarded` with the reason (R7).

      Only then does it harvest `this run missing=` and the denominator from the `Coverage gate`
      job's log. **An empty grep is never "the number was not printed"** — it is a skipped job or an
      expired log (`retention-days: 1` on the gate-data artifacts, `backend-tests.yml:241`), so the
      driver exits 1 rather than recording a blank round.
- [ ] **Step 5 — never dispatch round N+1 before round N's run has `completed`.** The concurrency
      group cancels in progress (R6), and 2b-4's census damaged three of its twelve runs exactly
      this way. The driver's `gh run watch` is what enforces it; do not replace it with a poll on the
      gate job alone, and do not run two copies of the driver concurrently.
- [ ] **Step 6 — if a round is discarded, dispatch a replacement.** A discarded round is not a low
      draw and does not count toward the twelve (Constraint 5).
- [ ] **Step 7 — before leaving this task, prove there are no duplicate run ids** across the whole
      campaign, not just adjacent rows:
      ```
      cut -f2 <census.tsv> | sort | uniq -d
      ```
      **Must print nothing.** The driver refuses a duplicate at write time; this is the
      after-the-fact audit that survives a driver bug, a hand-added row, or an interrupted round.

---

## Task 4: the stopping rule, and the number

**Ruling:** R7, R4, R5, R11.

- [ ] **Step 1 — apply the rule.** Stop when **the maximum has been unchanged for ≥6 consecutive
      valid rounds and there are ≥12 valid rounds total**. If the maximum is still moving at 12,
      continue and record the extra rounds; `runs` is the total taken.
- [ ] **Step 2 — `M_final = max(valid rounds)`, `S = statements`** (identical on every round; if it
      is *not* identical, the tree moved mid-census — Constraint 9 — and the census is void).
- [ ] **Step 3 — sanity, not acceptance.** `M_final` must lie in **[20, 80]** (R4's band). Outside
      it: **STOP and attribute per file** — download two rounds' `gate-data-*` artifacts and diff
      the per-file `missing_lines` **sets**, never difference the totals. The floor's own gate
      message prescribes exactly this. Write the attribution into the PR body whatever it shows.
- [ ] **Step 4 — read the sequence, and say what it shows.** R5 predicts a flat sequence.
      - **Flat** (spread 0): record it as measured, and say plainly in the floor header and the PR
        body that the previous 104-statement flappy set was entirely inside the deleted package.
      - **Not flat**: that is a **finding**, not noise to absorb. Attribute the differing round per
        line against a neighbour before writing anything, and record what flaps in the floor
        header's flappy paragraph — that paragraph exists to be re-derived, and this is the third
        time it has changed.
- [ ] **Step 5 — the percentage.** Compute `P = (1 − M_final/S) × 100`. **Record it; do not target
      it** (R11). If `P` is below 80, say so plainly in the PR body **and** in A15, with the
      statement that D7's threshold was a claim about the 38-module denominator and is not being
      re-litigated here — and flag it to the orchestrator before writing the floor.

---

## Task 5: write the floor

**Files:** `scripts/coverage_live_path.floor`, `scripts/coverage_live_path.floor.modules`.
**Ruling:** R8. **Constraints 6 and 12 govern this task.**

- [ ] **Step 0 — the rcfile's two stale sentences** (R15). `python3 <Appendix F> --check`, then run
      it. `git diff scripts/coverage_live_path.coveragerc` must show **comment lines only** — no
      `include`, `omit`, `source` or `exclude_lines` line may appear in the diff at all. This runs
      **now and not in Task 1**: before the census it would have invalidated every round.
- [ ] **Step 1 — one clean local round to write from.** Re-run
      `COVERAGE_ISOLATED_PREFIX=impl2d5 bash scripts/coverage_live_path_isolated.sh --report`, both
      labels `^OK`, and keep the combined directory (`${COVERAGE_ISOLATED_OUT:-/tmp/dispatcharr-coverage-isolated}`).
      **This run supplies the FORMAT and `statements`, not `missing`** — `statements` is the
      denominator and reproduces exactly between local and CI (R6's cross-validation), while
      `missing` comes from Task 4.
- [ ] **Step 2 — a throwaway writable container.** The standard hook container mounts `/repo` read
      only and `--write-floor` refuses it by name (R8):
      ```
      docker run -d --name impl2d5-rw --entrypoint sleep \
        -v /Users/dion/git/Dispatcharr/.worktrees/impl-2d5:/repo:rw -w /repo \
        -e PYTHONDONTWRITEBYTECODE=1 ghcr.io/d10scot/dispatcharr:latest infinity
      docker cp /tmp/dispatcharr-coverage-isolated impl2d5-rw:/tmp/combined
      ```
      No Postgres, no Redis: `--write-floor <dir>` combines, reports and writes, and needs neither.
      It must nonetheless run **in a container**, because the coverage data records `/repo/...`
      paths and the rcfile has no `[paths]` section (#312's second note).
- [ ] **Step 3 — write.** `COVERAGE_LIVE_PATH_RUNS` must be exported inside the container or `runs=0`
      is written (`scripts/coverage_live_path.sh:495`):
      ```
      docker exec impl2d5-rw bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; \
        export COVERAGE_LIVE_PATH_RUNS=<N valid rounds>; cd /repo && \
        bash scripts/coverage_live_path.sh --write-floor /tmp/combined'
      ```
      Expect `coverage_live_path: floor written -- statements <S> missing <one run's> coverage …%
      modules 7804792af4f7 (9 files) rcfile <hash>`.
- [ ] **Step 4 — assert what did and did not move** (Constraint 6).
      `git diff scripts/coverage_live_path.floor` must show `shape=`, `modules=` and
      `module_count=` **unchanged**, and `git diff --stat scripts/coverage_live_path.floor.modules`
      must be **empty**. **If any of those three moved, STOP**: the module set drifted since 2d-4,
      which is a finding about the tree and not a number to commit.
      **`rcfile=` must have moved, exactly once, to `sha256` of the edited coveragerc** — check it:
      ```
      python3 -c "import hashlib;print(hashlib.sha256(open('scripts/coverage_live_path.coveragerc','rb').read()).hexdigest()[:12])"
      grep '^rcfile=' scripts/coverage_live_path.floor
      ```
      The two must agree. If `rcfile=` did **not** move, Step 0 did not run and the floor now claims
      a definition the file no longer has — redo Step 0 and Step 3.
      (`statements`, `missing`, `percent`, `measured`, `runs` and `rcfile` are the six that change —
      R1 plus R15.)
- [ ] **Step 5 — the hand-edit.** Set `missing=<M_final>` from Task 4 and
      `percent=<(1 − M_final/S) × 100, two decimals>`. This is the floor's own documented step 4 and
      is stated as such in the commit message. Leave `statements`, `measured` and `runs` exactly as
      `--write-floor` produced them.
- [ ] **Step 6 — verify from the shape CI uses.** `COVERAGE_ISOLATED_PREFIX=impl2d5 bash
      scripts/coverage_live_path_isolated.sh --gate` from the ordinary **read-only** containers.
      Exit 0. Expect it to print either an exact match or a small "FEWER missed" figure — the
      local round is one draw against a maximum of N.

      **If it exits 1 — a local draw ABOVE the CI maximum — STOP; do not raise the floor.** R5
      predicts this cannot happen (the local rounds in Task 2 were identical and every known
      flapping statement was deleted at 2d-4), so it is a finding, not a tolerance problem. Two
      things it could mean, and they are distinguished by the same method the gate's own failure
      message prescribes — diff the per-file `missing_lines` **sets**, never difference totals:
      either the local shape is measuring something CI is not (a container difference, a stale data
      directory), or the census sequence was not the whole story and the CI rounds understated the
      spread. **Report to the orchestrator before touching the floor.** Raising `missing` to swallow
      a local draw would defeat the entire PR, and `COVERAGE_LIVE_PATH_ALLOW_REGRESSION` is
      forbidden here by Constraint 12.
- [ ] **Step 7 — stop the writable container** (`docker rm -f impl2d5-rw`) before doing anything
      else, so nothing else in this PR can write into the tree through it.

---

## Task 6: the floor's header

**Files:** `scripts/coverage_live_path.floor`. **Ruling:** R9. **Appendix B.**

- [ ] **Step 1 — `python3 <Appendix B> --check`**: every anchor present exactly once.
- [ ] **Step 2 — run it** with the census's figures as arguments: the round sequence, `max`, `min`,
      `spread`, `n`, the frozen SHA, the date, `statements` old and new, and the round at which the
      stopping rule was met. Prints `ok, 3 edits`.
- [ ] **Step 3 — read the result.** The 2d-4 slack banner is gone; the flappy paragraph opens with
      the sentence saying all 104 were inside the deleted package; the new PROVENANCE block sits
      **above** 2b-4's and neither 2b-4's nor 2a-7's nor the original local campaign's block has
      been touched (`git diff` shows additions and one deletion, no edits inside them).
- [ ] **Step 4 — `--gate` once more** from the read-only container: the header is comments, but a
      header edit that corrupted a `key=value` line would be caught only here.
- [ ] **Step 5 — commit** `scripts/coverage_live_path.floor`,
      `scripts/coverage_live_path.floor.modules` **and** `scripts/coverage_live_path.coveragerc`
      **together** — the coveragerc because its bytes and the floor's `rcfile=` must move in one
      commit or `--gate` fails on the intermediate one, and the companion because it is what lets a future
      `--gate` mismatch name files rather than show two unequal hashes). Message, in the floor's own
      vocabulary: `test(gate2): lower the floor to <M_final> over the nine surviving modules,
      campaign attached`.

---

## Task 7: CLAUDE.md and the spec

**Files:** `CLAUDE.md`, `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`.
**Ruling:** R12. **Appendices C and D.**

- [ ] **Step 1 — `python3 <Appendix C> --check`**, then run it with the census figures. Prints
      `ok, 3 edits`.
- [ ] **Step 2 — grep the old phrases to zero:**
      ```
      grep -c 'deliberately slack' CLAUDE.md          # → 0
      grep -c 'three regions are known to flap' CLAUDE.md   # → 0
      grep -c 'D7 still blocks every 2c PR' CLAUDE.md # → 0
      ```
      All three expect `0`, and `grep -c` exits 1 while printing it (Constraint 2) — run them bare.
- [ ] **Step 3 — `python3 <Appendix D> --check`**, then run it. Prints `ok, 6 edits` (A15, four
      in-place corrections, the Done-log row).
- [ ] **Step 4 — grep the spec's old phrases to zero:**
      ```
      grep -c 'coverage_live_path.floor:283-312' docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md   # → 0
      grep -c 'four of the thirteen affected test files are' docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md  # → 0
      ```
      **Note the trailing `are` in the second grep, and do not drop it.** Both Appendix D's own
      replacement (*"superseding this sentence's original 'four of the thirteen'"*) and the Done-log
      row (*"A10.4's 'four of the thirteen affected test files' is six of seventeen"*) quote the old
      phrase deliberately, so a grep without the trailing word returns 2 and looks like a failed
      edit. Measured on the simulated tree; the grep was corrected because of it. Both expect `0`,
      which `grep -c` prints while exiting 1 (Constraint 2) — run them bare.
- [ ] **Step 5 — the Done-log row is the table's LAST row.**
      ```
      python3 -c "import pathlib;s=pathlib.Path('docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md').read_text();h,_=s.split('\n## Risks\n',1);print(h.rstrip().splitlines()[-1][:60])"
      ```
      must begin `| 2d-5 -- the Gate 2 re-census`.
- [ ] **Step 6 — commit.** `docs(phase2): record the 2d-5 census in CLAUDE.md and the spec`.

---

## Task 8: the gate, and the PR

- [ ] **Step 1 — the backend, locally.** All **fifteen** labels green in the two containers (run the
      full set once; the commit gate will select only two). Each must print `^OK`.
- [ ] **Step 2 — `scripts/coverage_live_path_isolated.sh --gate`** from the read-only containers:
      exit 0 against the new floor.
- [ ] **Step 3 — `tests/test_ci_test_routing.py`** green. This PR does not edit
      `dispatcharr/test_discovery.py`, but it edits three paths the alias routes, so the test is the
      one that proves the routing still holds.
- [ ] **Step 4 — `python manage.py check`** green, and `makemigrations --check` in whatever state
      2d-1's A11 recorded as pre-existing (`core/0028_alter_streamprofile_parameters` was already
      dirty at 2d-1's seed; neither caused nor fixed here — record the state, do not fix it).
- [ ] **Step 5 — `scripts/check_credential_logging.py`** is not triggered: no `*.py` is edited.
      Confirm with `git diff --name-only origin/main...HEAD | grep -c '\.py$'` → **0**.
- [ ] **Step 6 — `python -m metrics.build --validate-only` is deliberately NOT run** (R14). Confirm
      no `metrics/` path is in the diff.
- [ ] **Step 7 — push, mark the PR ready, and write the body** from the template below.
- [ ] **Step 8 — CI.** `Backend result` green **including `Coverage gate` on the new floor**, and its
      "Refuse a floor edited downward" step green (the polarity: this PR lowers `missing`, which is
      the permitted direction). `E2E result`, `Lifecycle result`, `Go result`, `Frontend result`
      green — all four running the same code as `main` (R13).
- [ ] **Step 9 — clean up.** `docker rm -f impl2d5-proxy impl2d5-channels` and
      `docker volume rm impl2d5-proxy-hookdb impl2d5-channels-hookdb`. Confirm `impl2d5-rw` is
      already gone (Task 5 Step 7).

---

## PR body template

```markdown
## What

Gate 2's floor was measured over 38 modules and 8,073 statements. Stage 2d-4 deleted 29 of
those modules and re-baselined the floor's *shape* with `--write-floor --shape-only`, which by
design never writes `missing` — so `main` carried a floor permitting **1,525** missed statements
over a denominator of **<S>**. The floor was larger than the thing it bounded: every possible
run passed, including one covering nothing at all. `--gate` measured **<slack> FEWER missed than
the floor** on the pre-census tree; that figure *is* the slack.

This PR takes the ≥12-round CI census the floor's own procedure prescribes and writes the number.

| | before | after |
|---|---|---|
| modules | 9 (2d-4) | 9, unchanged |
| `statements` | 8,073 (2b-4's, stale) | **<S>** |
| `missing` | 1,525 (2b-4's, stale) | **<M_final>** |
| `percent` | 81.11 | **<P>** |
| `runs` | 12 (2b-4's) | **<N>** |

## The census

Full sequence, in order, from `backend-tests.yml`'s own `coverage-label` + `coverage-gate` jobs on
`<frozen SHA>`:

    <the sequence>

max=<M> (round <i>)  min=<m> (round <j>)  spread=<d>  n=<N>. Stopping rule (maximum unchanged for
≥6 consecutive rounds, minimum 12) met at round <k>. <X> rounds discarded and replaced: <reasons>.

<If the spread is 0:> Every one of the 104 statements the previous floor's header recorded as
flapping was inside `apps/proxy/live_proxy/` — `server.py` 73, `input/manager.py` 17, and eight
more files — and 2d-4 deleted all of them. The measured spread here is <d>.

## Why the coverage did not fall when the tests did

2d-4 disposed of seventeen test files. Six are under `apps/proxy/tests/`, the label this gate
measures most. Measured at `7fc4ddbd` by composing **every** one of those dispositions that lands
in the two coverage labels — the five wholly-deleted files **and** the 45 tests removed from the
five SPLIT files — and re-running both: the nine modules went from 31 missed to 33, with identical
missing-line sets either way. **The entire coverage cost of 2d-4's dispositions, over this
denominator, is two statements** — `relay_client.py:132` and `:339`, both reached only by
`test_relay_control_api.py`; the 45 SPLIT-class tests cost zero. The tests that cover the boundary
are the ones 2d-4 kept.

## Also in this PR

- `scripts/coverage_live_path.sh`'s `LABELS` array still named `apps.proxy.live_proxy.tests`. 2d-4
  edited the isolated script's list, the CI matrix, the routing table and the hook, but not this
  one. Its only caller is the script's own no-argument invocation — the first one its usage block
  lists — which failed loudly (`label(s) failed under coverage`, `THE FIGURES BELOW ARE INVALID`)
  from 2d-4's merge until this commit. Both outputs, before and after, are below.
- `scripts/coverage_live_path.coveragerc`'s comment block ended "2d-5's re-census may take it. THE
  FLOOR'S `missing` IS DELIBERATELY SLACK UNTIL THEN". Both sentences are this PR's to answer, and
  the answer belongs in the config file a future reader will check. **`rcfile=` moves with it** — it
  hashes the file's bytes, not its resolved file set — recomputed by the same `--write-floor` that
  writes the number. The `[run]` and `[report]` sections are byte-identical; the diff is comments
  only. It lands *after* the census on purpose: editing it earlier would have failed
  `coverage-gate` on every round with "the coveragerc's bytes changed".
- **One out-of-strict-scope correction, flagged:** CLAUDE.md's "Stage 2a ended at 74.30% … D7 still
  blocks every 2c PR until it closes" has been false since 2b-4, two stages ago. It is corrected
  here because **no other PR in this stage will take it**: spec § Stage 2d entry 6 scopes 2d-6 to
  `apps/proxy/live_proxy/` references, and this sentence contains none. It also closes the same
  § Testing paragraph whose other two sentences this PR rewrites.

## What this PR does NOT do

- **It does not change `scripts/coverage_live_path.coveragerc`'s module list.** A14.5 moved that
  edit into 2d-4; only two comment sentences change here.
- **It does not add `apps/proxy/stream_routes.py` to the denominator.** Its two callables exist to
  be resolved and never to be called (2d-4's Appendix O), so including it would raise `missing` by
  an amount no test could close. On the post-2d list; a `--shape-only` move plus a fresh census, if
  ever.
- **It sets no percentage target.** The ratchet is `missing`. D7's ≥80% was a claim about the
  38-module denominator, met at 2b-4, and is not re-litigated here.
- **It ships no `metrics/curated/` change.** No metric reads this floor; the stage-2d milestone row
  is 2d-6's close-out.
- **It corrects no other stale `live_proxy` prose** in CLAUDE.md or the spec — that is 2d-6's
  consolidation pass.

## Gate

- `Backend result` green including `Coverage gate` **on the new floor**, and "Refuse a floor edited
  downward" green (`missing` is a maximum; this PR lowers it).
- `tests/test_ci_test_routing.py` green — three of the five files here route through the
  `scripts/coverage_live_path` alias.
- `manage.py check` green; no `*.py` in the diff, so the credential lint has nothing to run on.
- `E2E result`, `Lifecycle result`, `Go result`, `Frontend result` green — the `migration/**` prefix
  runs all of them on code identical to `main`'s.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

---

## Self-review

Every `file:line` cited above was opened at the measurement seed `7fc4ddbd` and confirmed. What was
checked, and what changed as a result:

- **`scripts/coverage_live_path.sh:97`** — `LABELS=(apps.proxy.tests apps.proxy.live_proxy.tests
  apps.channels.tests)`. Confirmed. Confirmed too that its **only** reader is the `""` case at
  `:579-605` (`grep -n 'LABELS' scripts/coverage_live_path.sh` → two hits, the assignment and
  `for label in "${LABELS[@]}"`).
- **`scripts/coverage_live_path.sh:414-540`** (`write_floor`) — confirmed that `statements` sits
  inside the `if not shape_only` field list at `:516-520`, which is what makes R2's
  "`statements=8073` is expected" true and 2d-4's Task 9 Step 5 wrong.
- **`scripts/coverage_live_path.sh:443-452`** — the regression refusal and
  `COVERAGE_LIVE_PATH_ALLOW_REGRESSION`. Confirmed (Constraint 12).
- **`scripts/coverage_live_path.sh:216-236`** — `read_modules`'s hash. Re-derived independently;
  `7804792af4f7`/9 over the nine, `e76dc7dcf590`/10 with `relay_views.py`, both matching 2d-4's R9.
- **`scripts/coverage_live_path_isolated.sh:25-29, 98-104`** — the `PAIRS` list (three entries at
  this seed, two after 2d-4's R10) and the `COVERAGE_LIVE_PATH_RUNS` forwarding. Confirmed.
- **`backend-tests.yml:19-23, 30-32, 66-69, 165-180, 325-340`** — the dispatch input, the
  cancel-in-progress concurrency group, the `full_suite=false` diff mode, the hard-coded coverage
  matrix and the floor-downward guard. All confirmed, and the guard's polarity re-read twice.
- **`dispatcharr/test_discovery.py:53-59, 208`** — the alias table and, importantly,
  `if full_suite or not paths: return all_labels`. **This changed a ruling**: an *empty* path list
  also returns every label, so a `full_suite=false` dispatch on a tip commit that touches nothing
  routable is not cheap-and-wrong but expensive-and-right. R6 and Task 0 Step 7 were rewritten to
  check the tip commit's routing rather than assume it.
- **`scripts/ci_backend_test_labels.py:50`** — `FULL_SUITE` from the environment, which
  `backend-tests.yml:109` sets only for a `workflow_dispatch` with `full_suite == true`. Confirmed.
- **`scripts/coverage_live_path.floor`** — the 104-statement flappy set was summed file by file from
  the header's own prose (73+17+2+2+3+3+1+1+1+1 = 104, matching its stated total) and **every file
  named is inside `apps/proxy/live_proxy/`**. That is R5's whole basis and it was checked rather
  than asserted.
- **`apps/proxy/live_proxy/tests/test_manager_stderr_failover.py:257, :333`** — #259's two flake
  strings, confirmed to exist in that one file and nowhere else (R7).
- **The 2d-4 plan's R7, R9, R10, A14.5 and Appendices H.1/H.2/N** — all read in full. H.1 was
  extracted and `git apply --check`ed at this seed (clean) to derive `rcfile=fadc95a2c8ae`.
- **The spec's entry 5, A10.4, A10.14 and the Done-log table** — read at this seed and the
  post-2d-4 text reconstructed from A14's own `sub()` calls, which is what Appendix D's anchors are
  written against. `"\n## Risks\n"` and `"\n## Stage 2d — cutover, and its trap\n"` each occur
  exactly once (measured).

**The appendices were verified against a SIMULATED post-2d-4 tree, not only reasoned about.** A
scratch directory was seeded with `CLAUDE.md`, the spec, the floor and the coveragerc from the
measurement seed; 2d-4's own Appendix K (`python3 d4_k.py 15 2100 28.5` → `ok, 19 edits`), Appendix N
(`ok, 6 edits`) and Appendices H.1/H.2 (via `patch -p1`) were **executed** there; then this plan's
Appendices B, C, D and F were run in `--check` mode against the result:

```
ok, 3 anchors   (B)      ok, 3 anchors   (C)      ok, 7 anchors   (D)      ok, 1 anchor    (F)
```

and then for real, with sample figures: `ok, 3 edits` / `ok, 3 edits` / `ok, 6 edits` / `ok, 1 edit`.
Task 7's greps were run on the output. The simulated rcfile hashed to **`fadc95a2c8ae`**, confirming
R2's prediction by construction rather than by arithmetic.

**Which anchors match at the measurement seed, and which cannot.** Checked individually:
`C.A2`, `C.A3`, `D.C2`–`D.C5`, `D.STAGE_2D`, `D.RISKS`, `B.FLAPPY_ANCHOR` and `B.PROV_ANCHOR` all
occur **exactly once** on `main` today. `C.A1`, `D.C1` and `B.BANNER` occur **zero** times, because
all three are text 2d-4 *writes*. That split is exactly what a correctly-anchored plan against an
unbuilt tree should show, and it is why Task 0 Step 8 exists.

**Corrections made to this plan during self-review:**

1. The first draft ruled the census would be dispatched with `full_suite=true`, on the reading that
   `full_suite=false` might select no labels. Measuring `labels_for_changed_paths` showed the alias
   covers `scripts/coverage_live_path*` and that the empty-path case is safe, so the cheap shape was
   adopted — with Task 0 Step 7 added to verify it rather than trust it, and Task 3 Step 3's
   `skipped` assertion added as the backstop.
2. The first draft had Task 5 running `--write-floor` on the host. Coverage's absolute `/repo` paths
   and the rcfile's missing `[paths]` section make that fail; R8 and Task 5 Step 2 now carry the
   throwaway rw container.
3. The first draft treated `statements=8073` on the post-2d-4 floor as a STOP condition. Reading
   `write_floor()` showed `--shape-only` cannot write that field, so it is expected; Task 0 Step 4
   marks it informational and R2 records the 2d-4 plan defect behind it.
4. The first draft asserted a `rcfile=` value as a STOP. It is a prediction contingent on 2d-4's
   appendix landing byte-identically, so it was demoted to informational with a consistency check
   against the rcfile on disk (which *is* a STOP, because `--gate` fails on that drift).
5. **The first draft said the coveragerc was not touched at all, which would have left two false
   sentences in it — and the obvious fix would have destroyed the census.** Running 2d-4's Appendix
   H.1 in the simulation showed its comment block ends "2d-5's re-census may take it. THE FLOOR'S
   `missing` IS DELIBERATELY SLACK UNTIL THEN". Correcting that moves `rcfile=`, which `gate()`
   compares for equality — so putting the edit in Task 1's census-anchor commit would have failed
   `coverage-gate` on **every round** with a message about the coveragerc's bytes, producing twelve
   invalid rounds that read like a coverage problem. R15, Task 5 Step 0 and the revised Constraint 6
   are the result: the edit lands after the census, in the same command that recomputes the hash.
6. Task 0 Step 3's first draft expected `grep -c 'live_proxy' scripts/coverage_live_path.coveragerc`
   → 0. On the simulated post-2d-4 tree it returns **2**, because 2d-4's own comment names what it
   removed; `relay_views` returns **1** for the same reason. Both greps are now scoped to the
   `include` block. A verification step that STOPs a correct implementation is worse than no step.
7. Task 7 Step 4's grep for `four of the thirteen affected test files` returned **1** on the
   simulated output, because Appendix D's own replacement and the Done-log row both quote the
   corrected phrase deliberately. The grep gained a trailing `are`, which measures 0. A grep whose
   expected count is wrong is worse than no grep: it teaches the implementer to ignore it.

**Corrections made after review (PR #330, 8 should-fix, 0 blocking; every finding reproduced before
being applied).** The review re-measured R4 both ways, R5's spread, R6's harvest against run
`35512184360` and all four appendices on its own independently-composed post-2d-4 tree, and every
figure reproduced. What changed:

8. **S1 — the census driver could record one CI run twice.** `gh workflow run` returns no run id, so
   Appendix E took `gh run list --limit 1` after a fixed sleep; if GitHub had not yet registered the
   new run that returns the *previous* round's id, already `completed`, and every assertion passes
   against it. Under a "maximum unchanged for ≥6 consecutive rounds" rule a duplicate is a free fake
   observation of stability, and it is invisible afterwards. The driver now establishes the id by
   polling until the newest `workflow_dispatch` id **changes**, refuses any id already in
   `census.tsv`, and Task 3 Step 3 break-checks the duplicate guard against a real run id before the
   first round; Step 7 audits the whole file with `cut -f2 | sort | uniq -d`. **This was the review's
   own "would not merge without".**
9. **S5 — R4's second measurement composed only five of 2d-4's nine deletion events.** It has been
   re-taken with **all** of them — the five whole files plus the 45 tests from the five SPLIT files
   — and the answer is the same 1281/33/97.42% with identical missing-line sets, so the SPLIT rows'
   "none of the nine" claims in R3 are now a measurement rather than an argument. The caveat list
   also names what no local composition can include (2d-4's production-code changes, the three
   files in labels outside the coverage matrix, the re-pointed imports).
10. **S8 — Task 0's fallback census anchor was the most expensive one available.** If 2d-4's fix
    round has already fixed `LABELS`, the plan sent the implementer to a CLAUDE.md edit, which
    routes to **no** label (measured) and would have forced `full_suite=true` on all twelve-plus
    rounds. The fallback is now a comment-only edit to the floor's header: it routes to both
    coverage labels through the same alias, and `gate()` parses the floor only through
    `floor_value()`'s `grep -E "^$1="`, so a comment there cannot disturb a round — unlike the
    coveragerc, whose bytes are hashed.
11. **S2 — two tasks used containers a later task created.** Task 0 Step 5 now starts them and Task 2
    Step 1 confirms rather than re-creates (re-running `start-test-container.sh` does a `docker rm
    -f` first and would discard the warmed Postgres). Task 1 Step 3 names `impl2d5-proxy` and says
    why one container is right there and two would be wrong.
12. **S3 — R12's justification for the 74.30%/D7 edit was factually wrong.** That sentence is not
    "immediately following" the one this PR rewrites. The edit stands on a better reason: 2d-6's
    scope is `apps/proxy/live_proxy/` references and this sentence has none, so deferring it loses
    it.
13. **S4 — R10 claimed "Appendix A's own comment says which is which" about a comment that said no
    such thing.** The added block now names the three historical notes (gevent housekeeping, the C
    tracer, the 7,978/3,977/50.15% baseline) and records that they describe the pre-2d-4 tree — in
    the script, where a maintainer will see it, not only in a plan appendix they will not.
14. **S6/S7 — two ways to hand an implementer a step that fails on success.** `grep -c` prints `0`
    and exits 1, and seven steps expect `0`; Constraint 2 now says so and each step repeats it.
    And the plan never said where Appendices B–F live: new Constraint 13 puts them in the
    scratchpad, since a `.py` written into the tree would fire the credential-logging hook and
    break Task 8 Step 5's own "no `*.py` in the diff" assertion.
15. Four notes applied: `runs` counts **valid** rounds (N1); `module_count` is not compared by
    `gate()` and the constraint no longer says it is (N2); the `migration/**` cost comes from the
    `pull_request` event, not `push` — `e2e-tests.yml`'s `push:` is `branches: [main]` (N3); a
    `full_suite=false` round is **7** jobs, not ~5 (N4); and Task 5 Step 6 gained the contingency it
    lacked for a local `--gate` draw above the CI maximum — STOP and report, never raise the floor
    (N5).

**Round-2 review (PASS; one should-fix and one note, both reproduced).** The reviewer re-measured S5
from scratch with an AST class-stripper and got byte-identical missing sets, and found two defects
**in the S1 fix itself** — which is the right place to look, since that fix was written in the same
round it was reviewed:

16. **R2-S1 — the duplicate guard failed open under the very `pipefail` this plan mandates.**
    `cut -f2 "$LOG" | grep -qx "$RUN"`: `grep -q` exits on the match, `cut` takes SIGPIPE and exits
    141, `pipefail` makes 141 the pipeline's status, and the `if` reads a found duplicate as "not
    found". Reproduced exactly — `pipeline exit=141` on a 100k-row file with the match on line 1,
    and `MISSED (fails open)` — then bisected: ≤1,000 rows detects, ≥2,000 misses, five runs each,
    deterministic. **A real `census.tsv` is 12-20 rows and would have worked**, so this was a latent
    fail-open in the one guard with no second chance rather than a live one. Fixed with
    `grep -qx "$RUN" < <(cut -f2 "$LOG")`, verified detecting at 20/2,000/20,000 rows with no false
    positive. **And the break-check was rewritten around it**: the old two-row check could not have
    caught this, so Task 3 Step 3 now uses a 20,000-row file, asserts the OLD form prints
    `MISSED (fails open)` first, and says plainly that the check demonstrates the mechanism rather
    than a census-scale failure. A break-check that cannot fail is the defect this plan's own
    Constraint 8 exists to prevent.
17. **R2-N1 — the stated reason for `// empty` was not reproducible.** The note claimed that without
    it "`jq` prints `null`". Bare `jq` does (`echo '[]' | jq -r '.[0].databaseId'` → `null`), but
    **`gh --jq` does not**: measured on gh 2.100.0 against a branch with no dispatch run, the output
    without `// empty` is exactly one byte (`\n`) and with it zero bytes, and through `$( )` both
    yield a zero-length `BEFORE`. `// empty` is kept — it states the intent and survives the command
    being run outside a substitution — but it is no longer described as load-bearing.

**What could not be settled from the tree, and why.** `statements` and `missing` for the
implementation seed: the tree does not exist. R4 carries the measured reference over the same nine
files instead, with the three named reasons it will move, and every task step that needs the real
figures derives them from a run.

---

## Appendices

### Appendix A — `scripts/coverage_live_path.sh` (R10), Task 1

`git apply --check --whitespace=error` verified clean at the measurement seed. 2d-4 does not touch
this file, so it applies unchanged on the implementation seed. **Only the label list and the two
sentences that state the label count are edited** — the file's historical prose about gevent
housekeeping, the C tracer and the 7,978-statement baseline all describe deleted code and all remain
true *as history of why the guard exists*; they are 2d-6's.

```diff
diff --git a/scripts/coverage_live_path.sh b/scripts/coverage_live_path.sh
index 068db6e4..67501d91 100755
--- a/scripts/coverage_live_path.sh
+++ b/scripts/coverage_live_path.sh
@@ -1,8 +1,10 @@
 #!/usr/bin/env bash
 # Gate 2's measurement (Phase 2 spec, § Stage 2a > Gate 2): statement coverage
-# over apps/proxy/live_proxy/** plus the ten Phase 1 boundary modules.
+# over the nine surviving Phase 1 boundary modules. It measured
+# apps/proxy/live_proxy/** plus ten boundary modules until Phase 2 stage 2d-4
+# deleted the package and relay_views.py with it.
 #
-#   scripts/coverage_live_path.sh                       run all three labels, then report
+#   scripts/coverage_live_path.sh                       run both labels, then report
 #   scripts/coverage_live_path.sh --label <label>       run one label, leave its data file
 #   scripts/coverage_live_path.sh --report [dir]        combine and report; over <dir> if given
 #   scripts/coverage_live_path.sh --combine-from <dir>  combine data collected elsewhere, then report
@@ -91,10 +93,30 @@ set -uo pipefail
 REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
 cd "$REPO_ROOT"
 
-# The three labels whose tests reach the modules in the denominator. Hard-coded
+# The two labels whose tests reach the modules in the denominator. Hard-coded
 # rather than derived: the spec names exactly these, and a 16-label control run
 # at a948cd8a moved live_proxy by zero statements.
-LABELS=(apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests)
+#
+# Three until Phase 2 stage 2d-4, which deleted apps/proxy/live_proxy/ and with
+# it the label apps.proxy.live_proxy.tests. A label that no longer exists fails
+# `manage.py test`, run_label() returns non-zero, and the no-argument path below
+# then prints "label(s) failed under coverage" and refuses to quote the figures
+# -- loud rather than silent, but the default invocation was broken from 2d-4's
+# merge until stage 2d-5 fixed this line. Nothing in CI noticed, and that is the
+# point worth recording: backend-tests.yml's coverage-label matrix calls --label
+# once per container and carries its own hard-coded list, and
+# scripts/coverage_live_path_isolated.sh carries its own PAIRS list (2d-4 edited
+# both). This array's only caller is a maintainer typing the script's own name
+# with no arguments -- the invocation this file's usage block puts first.
+#
+# WHAT 2d-5 DELIBERATELY DID NOT TOUCH, so a reader does not take it for live
+# fact: the notes ABOVE about gevent daemon threads, the C tracer's losses and
+# the clean-tree baseline (7,978 statements / 3,977 missing / 50.15%, and the
+# per-file attribution to server.py / input/manager.py / channel_service.py)
+# all describe the PRE-2d-4 tree, whose files no longer exist. They are kept as
+# the history of why the shape guard and the sysmon export are here, which is
+# still true; consolidating them is stage 2d-6's.
+LABELS=(apps.proxy.tests apps.channels.tests)
 
 export COVERAGE_LIVE_PATH_DATA_DIR="${COVERAGE_LIVE_PATH_DATA_DIR:-/tmp/dispatcharr-coverage-live-path}"
 RC="$REPO_ROOT/scripts/coverage_live_path.coveragerc"
```

> **If `git apply` rejects the first hunk**, 2d-4's fix round edited the header after all. Re-derive
> by content: the two lines to change are the one ending `plus the ten Phase 1 boundary modules.` and
> the usage line containing `run all three labels`. Report the divergence.

### Appendix F — `scripts/coverage_live_path.coveragerc`'s two stale sentences (R15), Task 5 Step 0

Anchored, not a diff: 2d-4's Appendix H.1 writes the block this edits, and a review fix round could
reword it. **Comment-only** — the `[run]` and `[report]` sections come out byte-identical, and Task 5
Step 4 asserts that from the diff rather than trusting the script.

```python
#!/usr/bin/env python3
"""Appendix F -- the rcfile's two sentences that stage 2d-5 makes false.

    python3 appendix_f.py --check
    python3 appendix_f.py

Run from the repository root, in Task 5 BEFORE --write-floor. COMMENT-ONLY:
no `include`, `omit`, `source` or `exclude_lines` line is touched, and Task 5
Step 4 asserts that from the diff. `assert count == 1` on the one anchor.
"""
import argparse
import pathlib
import sys

RC = pathlib.Path("scripts/coverage_live_path.coveragerc")

# 2d-4's Appendix H.1 text, the last two lines of the comment block it added.
A = (
    "# value. 2d-5's re-census may take it. THE FLOOR'S `missing` IS DELIBERATELY\n"
    "# SLACK UNTIL THEN -- see scripts/coverage_live_path.floor's header.\n"
)

R = (
    "# value. Stage 2d-5's re-census DECLINED to take it, on a stronger reason than\n"
    "# 2d-4's: both of its callables exist to be RESOLVED by the authorize hop and\n"
    "# never to be called (apps/proxy/stream_routes.py's own header says so), so\n"
    "# their bodies are unreachable by design and including the file would raise\n"
    "# `missing` by an amount NO TEST COULD EVER CLOSE -- the one thing a ratchet\n"
    "# must not contain. THE FLOOR'S `missing` WAS DELIBERATELY SLACK BETWEEN 2d-4\n"
    "# AND 2d-5 AND NO LONGER IS: 2d-5 measured this module list over >=12 CI\n"
    "# rounds. Note for whoever edits this file next -- a COMMENT-ONLY edit here\n"
    "# still moves the floor's `rcfile=` field, which hashes these BYTES and not\n"
    "# the resolved file set, so any edit ships with a --write-floor in the same\n"
    "# PR. The floor's own header calls that an accepted false positive and says\n"
    "# what it costs.\n"
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    src = RC.read_text()
    n = src.count(A)
    assert n == 1, f"anchor found {n} times, expected 1"
    if a.check:
        print("ok, 1 anchor")
        return 0
    RC.write_text(src.replace(A, R, 1))
    print("ok, 1 edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Appendix B — `scripts/coverage_live_path.floor`'s header (R9), Task 6

An anchored script, not a diff: 2d-4 rewrites this file's header **and** its `key=value` block, so a
line-anchored hunk cannot survive. `--check` asserts every anchor and writes nothing.

```python
#!/usr/bin/env python3
"""Appendix B -- the floor header for stage 2d-5's census.

Run from the repository root, AFTER Task 5 has written the key=value fields.

    python3 appendix_b.py --check
    python3 appendix_b.py --seq "31 31 31 ..." --max 33 --min 31 --spread 2 \
        --n 12 --sha <frozen sha> --met-at 12 --old-statements 8073 \
        --statements 1307 --percent 97.48 --date 2026-09-21

Three edits, `assert count == 1` on every anchor:

  1. DELETE 2d-4's twelve-line "DELIBERATELY SLACK" banner.
  2. PREPEND one sentence to the 104-statement flappy paragraph saying every one
     of those statements was inside the deleted package, and append this
     campaign's measured spread.
  3. INSERT this campaign's PROVENANCE block immediately above 2b-4's.

Nothing else in the file is touched. The 2b-4, 2a-7 and original-local campaign
blocks stay exactly as they are: the file's own rule is that a floor which
quietly forgets its earlier number cannot be audited.
"""
import argparse
import pathlib
import sys

FLOOR = pathlib.Path("scripts/coverage_live_path.floor")

# --- anchor 1: 2d-4's banner, verbatim from that PR's Appendix H.2. -----------
BANNER = """\
# ** THIS FLOOR IS DELIBERATELY SLACK BETWEEN 2d-4 AND 2d-5, AND `missing` BELOW IS NOT
# ** A MEASUREMENT OF THE TREE IT SITS ON. Phase 2 stage 2d-4 deleted
# ** apps/proxy/live_proxy/ and apps/proxy/relay_views.py, taking the resolved file set
# ** from 38 modules to 9 and the denominator with it. That PR shipped
# ** `--write-floor --shape-only`, which rewrites `modules`, `module_count`, `rcfile` and
# ** the informational `statements` and DELIBERATELY DOES NOT TOUCH `missing`, `percent`,
# ** `measured` or `runs` -- so 1525 is still the figure the pre-delete tree earned, over
# ** a denominator roughly a tenth its former size. The gate is mechanically green and
# ** substantively toothless until `migration/phase2d-gate2-recensus` (2d-5) carries the
# ** >=12-round CI census that makes the number real, under the stopping rule this header
# ** prescribes below. A green run in that window proves the SHAPE checks, not coverage.
#
"""

# --- anchor 2: the opening of the 104-statement flappy paragraph. -------------
FLAPPY_ANCHOR = "# gate carries no separate tolerance parameter: the measured spread is already inside\n# the number. **104 statements flap across this campaign's own 12 CI rounds**, measured\n"

FLAPPY_PREFIX = """\
# gate carries no separate tolerance parameter: the measured spread is already inside
# the number.
#
# EVERY STATEMENT IN THE 104-LINE FLAPPY SET BELOW WAS INSIDE apps/proxy/live_proxy/,
# and Phase 2 stage 2d-4 deleted the whole package. server.py contributed 73 of the 104,
# input/manager.py 17, and eight further files the remaining 14 -- not one of them is
# among the nine modules this gate now measures. The paragraph is kept because it is the
# record of how the PREVIOUS number was earned, and a floor that quietly forgets its
# earlier number cannot be audited; it is not a description of this tree. This campaign's
# own measured spread is recorded in the 2d-5 PROVENANCE block below.
#
# WHAT FOLLOWS DESCRIBES THE PRE-2d-4 TREE. **104 statements flap across that tree's own
# 12 CI rounds**, measured
"""

# --- anchor 3: the head of 2b-4's provenance block. ---------------------------
PROV_ANCHOR = "# PROVENANCE (Phase 2 PR 2b-4, Task 13 -- measured in CI, where the gate is\n"


def build_block(a) -> str:
    return f"""\
# PROVENANCE (Phase 2 PR 2d-5 -- measured in CI, where the gate is enforced).
# THE RE-SCOPE'S NUMBER. Phase 2 stage 2d-4 deleted apps/proxy/live_proxy/ and
# apps/proxy/relay_views.py and re-baselined this floor's SHAPE only, which by
# design leaves `missing` alone -- so between 2d-4 and this PR the floor
# permitted 1525 missed statements over a denominator of {a.statements}. The
# floor was larger than the thing it bounded: every possible run passed,
# including one covering nothing at all. This block is the measurement that
# ends that.
#
# `missing` below is the WORST of {a.n} rounds of backend-tests.yml's own
# coverage-label + coverage-gate jobs, on migration/phase2d-gate2-recensus at
# {a.sha}, {a.date}. Full sequence, in order:
#   {a.seq}
# max={a.max} (round {a.max_round})  min={a.min} (round {a.min_round})  spread={a.spread}  n={a.n}
# The stopping rule (maximum unchanged for >=6 consecutive rounds, minimum 12)
# was met at round {a.met_at}.
#
# `statements` moved {a.old_statements} -> {a.statements}, and the move is the
# whole point rather than drift: {a.old_statements} was 2b-4's 38-module
# denominator, which --write-floor --shape-only cannot rewrite (it writes the
# four shape fields only, scripts/coverage_live_path.sh:516-520), so 2d-4 left
# it standing over nine modules. `modules`, `module_count` and `rcfile` are
# UNCHANGED from 2d-4's own --shape-only write: this PR moves the NUMBER and
# nothing about the denominator's identity.
#
# THE VARIANCE THIS CENSUS MEASURED, AND WHY IT IS NOT THE ONE ABOVE. Every one
# of the 104 flapping statements the pre-2d-4 tree carried was inside the
# deleted package; the gevent background housekeeping and the harness's real
# subprocess tunes that produced them are gone with it. Three local rounds at
# the implementation seed drew an identical figure, and the CI spread measured
# {a.spread}. Unobserved-to-vary is not proof of stability -- the CAVEAT at the
# top of this file applies to this campaign exactly as it applied to the last
# one -- but a round that differs from its neighbours on THIS tree is a finding
# to attribute per line, not noise to absorb.
#
# Coverage at the floor: {a.percent}%. RECORDED, NOT TARGETED. D7's >=80%
# threshold was a claim about the 38-module denominator and was met at 2b-4;
# the ratchet here is `missing`, and no percentage is enforced.
#
"""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    for name in ("seq", "sha", "date"):
        p.add_argument(f"--{name}", default="")
    for name in ("max", "min", "spread", "n", "met-at", "old-statements",
                 "statements", "max-round", "min-round"):
        p.add_argument(f"--{name}", default="")
    p.add_argument("--percent", default="")
    a = p.parse_args()

    src = FLOOR.read_text()
    for label, anchor in (("banner", BANNER), ("flappy", FLAPPY_ANCHOR),
                          ("provenance", PROV_ANCHOR)):
        n = src.count(anchor)
        assert n == 1, f"anchor {label!r} found {n} times, expected 1"
    if a.check:
        print("ok, 3 anchors")
        return 0

    for field in ("seq", "sha", "date", "max", "min", "spread", "n", "met_at",
                  "old_statements", "statements", "percent", "max_round", "min_round"):
        assert getattr(a, field), f"--{field.replace('_','-')} is required for a real run"

    src = src.replace(BANNER, "", 1)
    src = src.replace(FLAPPY_ANCHOR, FLAPPY_PREFIX, 1)
    src = src.replace(PROV_ANCHOR, build_block(a) + PROV_ANCHOR, 1)
    FLOOR.write_text(src)
    print("ok, 3 edits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> **If the `banner` anchor is absent**, 2d-4's Appendix H.2 landed with different bytes. Re-derive it
> from the file itself (it is the only block whose lines begin `# ** `) and report the divergence
> before running.

### Appendix C — `CLAUDE.md` § Testing (R12), Task 7

Three anchored replacements. Anchors 1 is 2d-4's **own replacement text** (from its Appendix K,
item 5); anchors 2 and 3 are unchanged at the measurement seed and 2d-4 does not touch them
(measured: `grep -n 'three regions are known to flap\|Stage 2a ended at 74.30'` over the 2d-4 plan
returns nothing).

```python
#!/usr/bin/env python3
"""Appendix C -- CLAUDE.md's three Gate 2 sentences, for stage 2d-5.

    python3 appendix_c.py --check
    python3 appendix_c.py --missing 33 --statements 1307 --percent 97.48 --n 12 --spread 2

Run from the repository root. `assert count == 1` on every anchor.
"""
import argparse
import pathlib
import sys

DOC = pathlib.Path("CLAUDE.md")

# 1 -- 2d-4's own replacement sentence, which named this PR as what it waits for.
A1 = (
    "**Between 2d-4 and 2d-5 the floor's `missing` is deliberately slack**: "
    "2d-4 shipped `--write-floor --shape-only`, which rewrites the shape hashes and never "
    "touches `missing`, so 1525 is still the figure the pre-delete tree earned over a "
    "denominator roughly a tenth its size. `migration/phase2d-gate2-recensus` carries the "
    "≥12-round CI census that makes it real"
)

# 2 -- the flappy-region sentence. Every file it names was deleted at 2d-4.
A2 = (
    "**The floor's `missing` is set from the worst of ≥12 runs measured in CI, where the gate "
    "is enforced, so there is no tolerance parameter** — the measurement is bimodal, not noisy, "
    "and three regions are known to flap: the owner-side coordinated stop "
    "(`channel_service.py` 28-49 and `server.py`'s sweep), the non-owner local cleanup "
    "(`server.py` 2099-2112, 2489-2566) and the stderr-reader join (`input/manager.py` "
    "1739-1767). Per-container isolation makes the first block deterministic and does **not** "
    "make the total so (spread 44 vs 47)."
)

# 3 -- two stages stale before this PR. Corrected here; see R12.
A3 = (
    "**Stage 2a ended at 74.30%, not the spec's ≥80%**; the shortfall is owned by `2b-4` and "
    "D7 still blocks every 2c PR until it closes."
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    for name in ("missing", "statements", "percent", "n", "spread"):
        p.add_argument(f"--{name}", default="")
    a = p.parse_args()

    src = DOC.read_text()
    for i, anchor in enumerate((A1, A2, A3), start=1):
        n = src.count(anchor)
        assert n == 1, f"anchor {i} found {n} times, expected 1"
    if a.check:
        print("ok, 3 anchors")
        return 0
    for field in ("missing", "statements", "percent", "n", "spread"):
        assert getattr(a, field), f"--{field} is required for a real run"

    r1 = (
        f"Stage 2d-5's ≥{a.n}-round CI census set `missing` to **{a.missing}** over a "
        f"denominator of **{a.statements}** (**{a.percent}%**), from the worst round of "
        f"{a.n}; the floor's own header carries the sequence"
    )
    r2 = (
        "**The floor's `missing` is set from the worst of ≥12 runs measured in CI, where the "
        "gate is enforced, so there is no tolerance parameter** — and on the post-2d-4 "
        f"denominator the measured spread across stage 2d-5's {a.n} CI rounds was **{a.spread}**. "
        "That is not an improvement this programme engineered: every one of the 104 statements "
        "the pre-delete floor recorded as flapping was inside `apps/proxy/live_proxy/` — 73 in "
        "`server.py` alone — and 2d-4 deleted the package. The gate still carries no tolerance "
        "parameter, and on this tree a round that differs from its neighbours is a finding to "
        "attribute per line rather than noise to absorb."
    )
    r3 = (
        "Gate 2's own history in one line: stage 2a ended at 74.30% against the spec's ≥80%, "
        "`2b-4` closed the shortfall at 81.11% and unblocked D7, and stage 2d-5 re-measured the "
        "gate over the nine modules that survived the delete."
    )

    src = src.replace(A1, r1, 1).replace(A2, r2, 1).replace(A3, r3, 1)
    DOC.write_text(src)
    print("ok, 3 edits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Appendix D — Amendment A15, four in-place corrections, and the Done-log row (R12), Task 7

A15 is inserted immediately **before** `## Stage 2d`, so it lands after A14 without needing A14's
text. The Done-log row is appended as the table's **last row**, anchored on `"\n## Risks\n"` with
2d-3's `head.rstrip().endswith("|")` assertion.

```python
#!/usr/bin/env python3
"""Appendix D -- Amendment A15, four in-place corrections, and the Done-log row.

    python3 appendix_d.py --check
    python3 appendix_d.py --missing 33 --statements 1307 --percent 97.48 \
        --n 12 --spread 2 --slack <the FEWER figure Task 0 Step 5 recorded>

Run from the repository root. `assert count == 1` on every anchor. Prints
`ok, 6 edits`.

The four corrections, each a sentence THIS PR makes false or supersedes.
Task 7 Step 4 greps for the first two OLD phrases and expects zero hits:

  1. entry 5's line-number citation into the floor (already wrong before this
     PR: 2d-4's Appendix H.2 inserted twelve lines above it).
  2. entry 5's "ten survivors" and "four of the thirteen affected test files".
  3. § Stage 2a > Gate 2's blockquote, which ends at 2b-4's figures.
  4. A10.4's "perhaps a tenth that" prediction, which understated the outcome.
"""
import argparse
import pathlib
import sys

SPEC = pathlib.Path("docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md")

STAGE_2D = "\n## Stage 2d — cutover, and its trap\n"
RISKS = "\n## Risks\n"

C1 = ("What remains here is the NUMBER, under the stopping rule "
      "`scripts/coverage_live_path.floor:283-312` prescribes.")
C2 = ("It cannot merge with PR 4: the ten survivors are executed in large part by the ~564 "
      "tests PR 4\n   removes,")
C3 = ("four of the thirteen affected test files are\n   under `apps/proxy/tests/` and contribute "
      "to covering the very modules this gate will measure, so\n   the plan states which "
      "disposition each received.")
C4 = ("The floor file\n> now records `missing=1,525`; D7's threshold half is green, and — with "
      "Gate 1 closed in 2b-3 —\n> both halves of D7 are.")
C5 = ("moves `modules=` again and\ndrops the real draw by most of its value, so a `--shape-only` "
      "re-baseline there leaves a floor of\n1525 over a denominator of perhaps a tenth that — "
      "mechanically green, substantively toothless.")


def amendment(a) -> str:
    return f"""#### Amendment A15 (stage 2d-5) — six rulings from the Gate 2 re-census

**Measured on the merged 2d-4 tree.** Where an item contradicts a sentence in A10 or in § Stage 2d's
deletion list, that sentence is **edited in place** and the item says so.

**A15.1 — the gate was not merely slack between 2d-4 and 2d-5; the floor was larger than the
denominator.** A10.4 predicted "a floor of 1525 over a denominator of perhaps a tenth that —
mechanically green, substantively toothless". Measured: the denominator is **{a.statements}**
statements, so the floor permitted more missed statements than existed. Every possible run passed,
including one covering nothing at all. A10.4's sentence is corrected in place. The prediction was
right in kind and understated in degree, which is worth recording because the same arithmetic
governs any future stage that deletes most of a ratchet's subject.

**A15.2 — the census, and its number.** `missing={a.missing}` over `statements={a.statements}`
(**{a.percent}%**), the worst of **{a.n}** CI rounds on `migration/phase2d-gate2-recensus` under the
stopping rule the floor's own **HOW TO MOVE THIS FLOOR** section prescribes. The full sequence is in
the floor's header, in order, as § Stage 2d's entry 5 requires. `shape`, `modules`, `module_count`
and `rcfile` are unchanged from 2d-4's `--shape-only` write: this PR moved the number and nothing
about the denominator's identity.

**A15.3 — the spread collapsed, and not because anything was engineered.** The pre-delete floor
recorded 104 flapping statements, measured first-hand from 2b-4's twelve retained CI artifacts.
**All 104 were inside `apps/proxy/live_proxy/`** — 73 in `server.py`, 17 in `input/manager.py`, 14
across eight further files — and 2d-4 deleted the package. The measured spread across this
campaign's {a.n} rounds is **{a.spread}**. The gate still carries no tolerance parameter, and the
floor's own CAVEAT still applies: unobserved-to-vary is not proof of stability. What changes is what
a non-flat sequence now *means* — on this tree it is a finding to attribute per line.

**A15.4 — A10.4's worry about the census tree, measured and answered.** A10.4 required this plan to
state which disposition each affected test file received, "because whether 2d-4 deletes, rewrites or
merely un-imports each of them changes the denominator's coverage before a single round is
measured." A14.3 settled seventeen files, **six** of them under `apps/proxy/tests/` (A10.4 said four
of thirteen; corrected in place). Measured directly at `7fc4ddbd` by removing the five wholly-deleted
files from the two coverage labels and re-running both: the nine modules went **31 → 33 missed**.
**The entire coverage cost of the seventeen dispositions, over this denominator, is two
statements** — `apps/proxy/relay_client.py:132` and `:339`, both reached only by
`test_relay_control_api.py`. The worry was correct to raise and the answer is that the tests covering
the boundary are the ones 2d-4 kept.

**A15.5 — `scripts/coverage_live_path.sh`'s `LABELS` array survived 2d-4 naming the deleted label,
and § Stage 2d names no owner for it.** 2d-4's R10 edited
`scripts/coverage_live_path_isolated.sh`'s `PAIRS`, `backend-tests.yml`'s coverage matrix,
`dispatcharr/test_discovery.py`'s two aliases, `tests/test_ci_test_routing.py` and the boot-check
hook arm — six places that knew the label count — but not `scripts/coverage_live_path.sh:97`, whose
one caller is the script's own no-argument path. From 2d-4's merge until this PR, the invocation the
file's usage block lists first exited 1 with "label(s) failed under coverage" and "THE FIGURES BELOW
ARE INVALID". Loud rather than silent, and harmless to CI (which calls `--label` per container), but
it is the command a maintainer reproducing this gate by hand types. Fixed here, in the PR whose
subject it is.

**A15.6 — `apps/proxy/stream_routes.py` is deliberately NOT in the denominator, and the reason is
not scope.** 2d-4's R9 declined it and left the question open here. Declined again: A14's own
Appendix O states that the module's two callables "exist to BE RESOLVED, never to be called" —
nginx routes both paths to the Go relay, and the one shape without nginx serves them from the Go
relay's own port — so their bodies are unreachable by design and including the file would raise
`missing` by an amount **no test could ever close**, which is the one thing a ratchet must not
contain. Adding it would also move `modules=` in the same PR that moves `missing`, mixing the two
kinds of move the floor's header separates at length. On the post-2d list: a `--shape-only` move
plus a fresh census, if ever.

"""


def done_row(a) -> str:
    return (
        "| 2d-5 -- the Gate 2 re-census (`migration/phase2d-gate2-recensus`). The floor 2d-4 left "
        "on main permitted 1525 missed statements over a denominator of "
        f"{a.statements} -- larger than the thing it bounded, so every possible run passed and "
        f"`--gate` printed \"{a.slack} FEWER missed than the floor\". A {a.n}-round CI census under "
        "the floor's own stopping rule sets `missing` to "
        f"**{a.missing}** ({a.percent}%), with the full sequence recorded in the floor's header and "
        f"a measured spread of {a.spread}. Amendment A15, six rulings, three of which correct A10 "
        "or § Stage 2d in place: A10.4's \"a denominator of perhaps a tenth that\" understated it "
        "(the floor exceeded the whole denominator); A10.4's \"four of the thirteen affected test "
        "files\" is six of seventeen after A14.3; and entry 5's line-number citation into the floor "
        "was already wrong before this PR, since 2d-4's own header edit moved those lines -- "
        "replaced with a name-based one. The census cost of 2d-4's seventeen dispositions, measured "
        "by removing the five wholly-deleted files and re-running both coverage labels, is **two "
        "statements** (`relay_client.py:132` and `:339`, reached only by the deleted "
        "`test_relay_control_api.py`): the tests covering the boundary are the ones 2d-4 kept. The "
        "104-statement flappy set the previous floor recorded was entirely inside the deleted "
        "package, which is why this campaign's spread is what it is rather than anything this PR "
        "engineered. Also fixed: `scripts/coverage_live_path.sh:97`'s `LABELS` array, which 2d-4's "
        "six-site label-count edit missed, leaving the script's own no-argument invocation failing "
        "loudly since that merge. No percentage target is set -- the ratchet is `missing`, and "
        "D7's >=80% was a claim about the 38-module denominator, met at 2b-4. "
        "| `migration/phase2d-gate2-recensus` | pending |\n"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    for name in ("missing", "statements", "percent", "n", "spread", "slack"):
        p.add_argument(f"--{name}", default="")
    a = p.parse_args()

    s = SPEC.read_text()
    anchors = {"STAGE_2D": STAGE_2D, "RISKS": RISKS,
               "C1": C1, "C2": C2, "C3": C3, "C4": C4, "C5": C5}
    for name, anchor in anchors.items():
        n = s.count(anchor)
        assert n == 1, f"anchor {name} found {n} times, expected 1"
    head, _ = s.split(RISKS, 1)
    assert head.rstrip().endswith("|"), "the Done log's last line is not a table row"
    if a.check:
        print("ok, 7 anchors")
        return 0
    for field in ("missing", "statements", "percent", "n", "spread", "slack"):
        assert getattr(a, field), f"--{field} is required for a real run"

    # 1 -- entry 5's stale line-number citation, plus the DONE marker.
    s = s.replace(C1, (
        "What remains here is the NUMBER, under the stopping rule the floor's own\n"
        "   **HOW TO MOVE THIS FLOOR** section prescribes — named rather than cited by line, "
        "because\n   2d-4's and 2d-5's header edits each move those lines and the citation was "
        "already wrong\n   when 2d-5 opened it. **DONE at 2d-5** (Amendment A15): "
        f"`missing={a.missing}` over `statements={a.statements}`\n   (**{a.percent}%**), the worst "
        f"of {a.n} CI rounds, sequence in the floor's header."
    ), 1)

    # 2 -- entry 5's "ten survivors".
    s = s.replace(C2, (
        "It cannot merge with PR 4: the **nine** survivors are executed in large part by the "
        "~564\n   tests PR 4 removes,"
    ), 1)

    # 3 -- entry 5's "four of the thirteen".
    s = s.replace(C3, (
        "**six of the seventeen affected test files**\n   (A14.3's count, superseding this "
        "sentence's original \"four of the thirteen\") are under\n   `apps/proxy/tests/` and "
        "contribute to covering the very modules this gate will measure, so\n   the plan states "
        "which disposition each received. **Measured at 2d-5: the coverage cost of\n   all "
        "seventeen, over the nine modules, is two statements** (A15.4)."
    ), 1)

    # 4 -- § Stage 2a > Gate 2 gains a RE-SCOPED paragraph in the blockquote's idiom.
    s = s.replace(C4, C4 + (
        "\n>\n"
        "> **RE-SCOPED in 2d-5, and the figures above are no longer this gate's.** Stage 2d-4 "
        "deleted\n> 29 of the 38 modules and re-baselined the floor's shape only, leaving "
        f"`missing=1,525` over a\n> denominator of {a.statements} — a floor larger than the thing "
        "it bounds. A "
        f"{a.n}-round CI census on\n> `migration/phase2d-gate2-recensus` sets `missing={a.missing}` "
        f"over `statements={a.statements}`\n> (**{a.percent}%**), spread {a.spread}, with the full "
        "sequence in `scripts/coverage_live_path.floor`.\n> **No percentage threshold is enforced "
        "and none is claimed**: D7's ≥80% was a claim about the\n> 38-module denominator, met at "
        "2b-4, and the ratchet here is `missing` (Amendment A15)."
    ), 1)

    # 5 -- A10.4's understated prediction.
    s = s.replace(C5, C5.rstrip(".") + (
        ". **Measured at 2d-5 and understated here: the denominator is "
        f"{a.statements}\nstatements, so the floor did not merely dwarf it — it EXCEEDED it, and "
        "every possible run in that\nwindow passed, including one covering nothing at all "
        "(Amendment A15.1).**"
    ), 1)

    # 6 -- A15, before ## Stage 2d, landing after A14.
    s = s.replace(STAGE_2D, "\n" + amendment(a) + STAGE_2D.lstrip("\n"), 1)

    # 7 -- the Done-log row, as the table's LAST row.
    head, tail = s.split(RISKS, 1)
    assert head.rstrip().endswith("|"), "the Done log's last line is not a table row"
    s = head.rstrip("\n") + "\n" + done_row(a) + RISKS + tail

    SPEC.write_text(s)
    print("ok, 6 edits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> **Anchors C1–C5 were reconstructed from 2d-4's Appendix N `sub()` calls**, not read from a tree
> that exists. Task 0 Step 8's `--check` run is what verifies them, and an absent anchor is a STOP
> with a re-derivation, not a guess.

### Appendix E — the census driver (Task 3)

A scratchpad script, not a repository file. It dispatches one round, waits for the run to
**complete**, asserts the three coverage jobs and the frozen SHA, and appends a row to `census.tsv`.

```bash
#!/usr/bin/env bash
# One census round. Usage: bash round.sh <round-number> <frozen-sha> <census.tsv>
#
# The run id is established by WATCHING THE LIST CHANGE, never by `--limit 1`
# after a sleep: `gh workflow run` returns no id, and a list taken before
# GitHub has registered the new run returns the PREVIOUS round's -- already
# completed, so every assertion below passes and the previous round's figure is
# recorded twice. A duplicate is a free fake observation of stability under a
# "maximum unchanged for >=6 consecutive rounds" rule. Two defences: poll until
# the newest id changes, and refuse an id already in census.tsv.
set -uo pipefail
R="$1"; FROZEN="$2"; LOG="$3"
REPO=D10Scot/Dispatcharr
BRANCH=migration/phase2d-gate2-recensus

newest() {
  gh run list --repo "$REPO" --workflow backend-tests.yml --branch "$BRANCH" \
    --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId // empty'
}

BEFORE=$(newest)            # may be empty on the very first round; that is fine
echo "round $R: newest before dispatch = ${BEFORE:-<none>}"

gh workflow run backend-tests.yml --repo "$REPO" --ref "$BRANCH" -f full_suite=false || exit 1

# Defence 1: poll until the newest id is not the one that was there before.
RUN=""
for _ in $(seq 1 60); do
  sleep 5
  CAND=$(newest)
  if [ -n "$CAND" ] && [ "$CAND" != "$BEFORE" ]; then RUN="$CAND"; break; fi
done
if [ -z "$RUN" ]; then
  echo "round $R: no NEW workflow_dispatch run appeared within 5 minutes -- do not record; investigate"
  exit 1
fi
echo "round $R: run $RUN"

# Defence 2: an id already in census.tsv is a duplicate, whatever produced it.
#
# Process substitution, NOT `cut ... | grep -qx`. Under `pipefail` the pipeline
# form FAILS OPEN: `grep -q` exits the moment it matches, `cut` then takes
# SIGPIPE and exits 141, and pipefail makes 141 the pipeline's status -- so a
# FOUND duplicate reads as "not found". Measured: deterministic from about 2,000
# rows up on this machine, and a real census.tsv (12-20 rows) is far below that,
# so the pipeline form would have worked here and stayed a latent fail-open in
# the one guard that has no second chance.
if [ -f "$LOG" ] && grep -qx "$RUN" < <(cut -f2 "$LOG"); then
  echo "round $R: REFUSING -- run $RUN is already recorded in $LOG. A duplicate row is a"
  echo "round $R: fake observation of stability under the stopping rule. Investigate before retrying."
  exit 1
fi

# Wait for the RUN, not the gate job -- the concurrency group cancels in
# progress, so dispatching the next round early clips this one's tail.
gh run watch "$RUN" --repo "$REPO" --exit-status >/dev/null 2>&1 || true

SHA=$(gh run view "$RUN" --repo "$REPO" --json headSha --jq .headSha)
if [ "$SHA" != "$FROZEN" ]; then
  printf '%s\t%s\t%s\t-\t-\t-\t-\t-\tdiscarded: branch moved\n' "$R" "$RUN" "$SHA" >> "$LOG"
  echo "round $R: BRANCH MOVED ($SHA != $FROZEN) -- Constraint 9 broken, stop"; exit 1
fi

jobs_json=$(gh run view "$RUN" --repo "$REPO" --json jobs)
get() { printf '%s' "$jobs_json" | jq -r --arg n "$1" '.jobs[]|select(.name==$n)|.conclusion'; }
P=$(get "Coverage apps.proxy.tests"); C=$(get "Coverage apps.channels.tests"); G=$(get "Coverage gate")

if [ "$P$C$G" != "successsuccesssuccess" ]; then
  printf '%s\t%s\t%s\t%s\t%s\t%s\t-\t-\tdiscarded: coverage job not success\n' \
    "$R" "$RUN" "$SHA" "$P" "$C" "$G" >> "$LOG"
  echo "round $R: DISCARDED (proxy=$P channels=$C gate=$G)"; exit 0
fi

JOB=$(printf '%s' "$jobs_json" | jq -r '.jobs[]|select(.name=="Coverage gate")|.databaseId')
GATELOG=$(gh run view --repo "$REPO" --job "$JOB" --log)
LINE=$(printf '%s' "$GATELOG" | grep -E 'this run missing=' | tail -1)
[ -n "$LINE" ] || { echo "round $R: gate job logged no figure -- investigate, do not record"; exit 1; }
M=$(printf '%s' "$LINE" | sed -E 's/.*this run missing=([0-9]+).*/\1/')
S=$(printf '%s' "$GATELOG" | grep -E 'denominator: floor' | tail -1 \
      | sed -E 's/.*this run ([0-9]+) statements.*/\1/')
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\tvalid\n' "$R" "$RUN" "$SHA" "$P" "$C" "$G" "$M" "$S" >> "$LOG"
echo "round $R: missing=$M statements=$S"
```

**Note the two `|| true`-free places.** An empty `$LINE` exits 1 rather than recording a blank round
— an empty grep is a skipped job or an expired log, never "the number was not printed" (R6). And
`gh run watch`'s status is deliberately discarded, because a non-`success` overall conclusion is not
by itself a reason to discard a round; the job set decides (R7).

**Three mechanics verified at the measurement seed, so the implementer does not discover them at
round 1:**

- `gh run list … --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId // empty'`
  on a branch with no dispatch prints **nothing and exits 0**, which is why `BEFORE` may legitimately
  be empty on the first round. **`// empty` is intent, not a fix**, and an earlier draft of this note
  claimed otherwise: it said that without it "`jq` prints `null`". Bare `jq` does — `echo '[]' | jq -r
  '.[0].databaseId'` prints `null` — but **`gh --jq` does not**. Measured on gh 2.100.0 against a
  branch with no dispatch run: without `// empty` the output is exactly one byte, `\n`; with it,
  zero bytes; and through `$( )` both give a zero-length `BEFORE`. Keep `// empty` because it says
  what is meant and survives the command being run outside a substitution, not because the poll
  would otherwise chase a run that does not exist.
- The gate log is fetched **once** into `$GATELOG` and grepped twice. The first draft called
  `gh run view --log` twice, which is two API round trips for one answer and two chances for the
  second to come back different from the first.
- **The duplicate check is `grep -qx "$RUN" < <(cut -f2 "$LOG")` and not a pipeline**, for a
  reason worth stating because it is the opposite of the usual advice. Under `set -o pipefail` —
  which this script and Global Constraint 2 both require — `cut -f2 "$LOG" | grep -qx "$RUN"`
  **fails open**: `grep -q` exits as soon as it matches, `cut` takes SIGPIPE writing to the closed
  pipe and exits **141**, and pipefail hands 141 to the `if`, which reads it as "no duplicate".
  Measured on this machine: ≤1,000 rows detects, ≥2,000 rows misses, deterministically
  (`pipeline exit=141` on a 100k-row file with the match on line 1). **A real `census.tsv` is
  12-20 rows, far below the threshold, so the pipeline form would have worked here** — which is
  precisely why it had to go: a guard that has no second chance must not depend on the pipe buffer.
  The process-substitution form detects at 20, 2,000 and 20,000 rows and false-positives at none.
- `-x` matters independently — without it a future run id that merely *contains* an earlier one
  would match. Verified: `35512184360` matches, `35512184361` and `99999999999` do not.
