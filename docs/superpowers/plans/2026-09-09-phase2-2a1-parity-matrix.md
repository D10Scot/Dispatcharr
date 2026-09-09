# Phase 2 PR 2a-1 — The Relay Parity Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `docs/relay-parity-matrix.md` — one row per externally-observable live-path
behaviour, each carrying a `file:line` citation into the Python relay and a machine-checkable
statement of what pins it — and `e2e/tests/guards/parity-matrix.spec.ts`, the guard that fails
naming any row whose citation does not resolve or whose pin is neither a real test nor an
explicitly-owed one.

**Architecture:** The matrix is a single GFM table inside a Markdown document, with a fixed
five-column header the guard finds by exact string match. A new helper module,
`e2e/tests/guards/parity-matrix.ts`, parses that table and resolves every citation and pin against
the real tree; `e2e/tests/guards/parity-matrix.spec.ts` holds five Playwright tests over it, in the
`guards` project — static analysis over this repository's own source, no container, no browser.
Rows that no test can pin (behaviour deleted rather than ported) are confined to an explicit
allowlist inside the helper, in the same `toEqual`-against-a-hand-written-list idiom
`tests/guards/allowlist.ts` already uses for the grey-box capabilities; rows that a *later* PR owes
a test carry an `owed: <pr>` marker and are pinned by a second such list, so closing one is a
deliberate two-file edit and adding one cannot happen silently.

**Tech Stack:** Playwright + TypeScript 5.7 (`e2e/`, `strict: true`), the TypeScript compiler API
(`typescript`, already a devDependency, reached through `e2e/tests/guards/ast.ts`), Markdown.
No new dependency in either package.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` § Stage 2a › Gate 1 — the
parity matrix, 100% pinned; § Stage 2a › The seven PRs, row `2a-1`; § Documentation.

**Branch:** `migration/phase2a-parity-matrix` (worktree
`/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1`), off `main` at `a948cd8a`.

---

## Branch base

This branch is cut from `main` at `a948cd8a` and depends on nothing. The spec it implements lives
on a **different branch** (`.worktrees/phase2-spec`, the Phase 2 PR 0 branch) and is not present in
this worktree. That is deliberate and does not block: this plan carries every fact from the spec
that the work needs, and the executor does not have to read the spec to execute the plan. If you do
want to read it, it is at
`/Users/dion/git/Dispatcharr/.worktrees/phase2-spec/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`
— read-only, never edit it from here.

**This plan file is already committed on this branch** by the planning pass. Every other file in
§ File Structure is yours to create or modify.

**Every `file:line` this plan quotes was verified against this worktree at `a948cd8a`** on
2026-09-09. Line numbers drift; the tree wins. Where a task says "verify", it means run the command
given and use what it answers, not what this plan says.

---

## Global Constraints

Copied from the spec; every task's requirements implicitly include this section.

- **The branch is `migration/**`, so the full E2E and lifecycle matrices run on it.**
  `e2e-tests.yml` runs every Playwright project including `lifecycle-upgrade`, ignores its path
  filter, and `lifecycle-tests.yml` runs both bash suites. That is a cost this PR pays for its
  branch name, not a signal that this PR touches those surfaces — it touches none of them.
- **The matrix is the artefact every later Phase 2 PR cites.** 2a-3 … 2a-6 fill in test
  references; 2b-3 closes row 18; each 2c PR closes a named set of rows; 2d's cutover checklist is
  "every row shows a passing Go-side equivalent". **Its format is load-bearing: a later PR must be
  able to change a Pin cell without reformatting anything else.**
- **No third-party dependency is added by this PR** — not to `e2e/package.json`, not to
  `pyproject.toml`, not to any Dockerfile. The guard uses `node:fs/promises`, `node:path` and the
  `typescript` compiler API, all already present.
- **zizmor stays at zero findings if any workflow is touched.** No workflow should be touched by
  this PR (§ Design ruling 9). If one ever is, it gets zizmor-clean before the commit, and any new
  `uses:` is a 40-char SHA with a version comment resolved by
  `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha` after confirming the publisher.
- **This PR changes no product code.** Nothing under `apps/`, `core/`, `dispatcharr/`, `frontend/`,
  `docker/`, `scripts/` or `metrics/` is edited. The diff is `docs/`, `e2e/` and `CLAUDE.md`. If a
  task starts to need a product edit, stop and report — that is a different PR.
- **Every `test()` carries exactly one inline tag** in a details object written literally at the
  call site. `e2e/tests/guards/tags.spec.ts` fails a tag passed by reference, two tags, or none.
  All five tests in this PR carry `{ tag: '@characterization' }` (§ Design ruling 8).
- **`e2e/COVERAGE.md` gets its row in the same PR as the test** (`e2e/README.md` rule 10,
  `CLAUDE.md` § Testing).
- **`git add` and `git commit` run in separate Bash calls**, and the commit message is written with
  the Write tool and passed as `-F <msgfile>` — the pre-commit hook matches on command text and
  blocks any single call containing both verbs, and trips on a heredoc that merely contains them.
- **Every `gh` command carries `--repo D10Scot/Dispatcharr`.** Without it `gh` resolves to
  upstream's public tracker (`docs/agents/issue-tracker.md`).
- **The edit hooks do not fire in a worktree** (they resolve the project directory from the
  harness). Run them yourself — § Test environment gives the exact commands. The one that matters
  here is the blocking `tsc --noEmit` on `e2e/**/*.ts`.
- **`CLAUDE.md` rules that bind even though no product code changes**: no channel state in Python
  memory, no blocking call on a gevent path, `os.posix_spawn` stays, DRF serializers for every
  endpoint, migrations ship with model changes, redaction helpers for any URL/header logging. None
  is exercised by this diff; they are listed so a task that starts to need one recognises it has
  left scope.

---

## Design rulings

Each settles something the spec leaves open, or states in a way the tree contradicts. They are
binding on the executor; a reviewer checks the plan against them rather than re-deriving them.

### 1. The matrix is one GFM table with a fixed five-column header, and the guard finds it by exact string match

The document may carry any amount of prose. Exactly one line in it equals

```
| # | Behaviour | Source | Pin | Notes |
```

character for character, and the table is the run of `|`-leading lines after that line and its
delimiter row. The guard throws — naming the file and the expected header — if that line is absent,
if the delimiter row is missing, or if a row does not split into exactly five cells.

Why exact-match and not a Markdown parser: no Markdown parser is available without adding a
dependency (a Global Constraint forbids one), and a hand-rolled loose parser is the thing that
silently accepts a malformed row. An exact header is a format the guard can be trusted about.

**A cell may not contain a literal `|`.** The five-cell requirement enforces this by construction —
a stray pipe splits the row into six cells and fails, naming the line. This is stated in the
document's own § Format so an author is told before the guard tells them.

### 2. Five columns: `#`, `Behaviour`, `Source`, `Pin`, `Notes`

- **`#`** — a decimal integer, unique across the table, strictly ascending. Row ids are the phase's
  addressing scheme (2c PRs "close rows 7–10, 13"), so they must be stable: **an id is never reused
  and never renumbered.** A deleted row's id is retired.
- **`Behaviour`** — one sentence naming the externally-observable behaviour. Prose; the guard only
  requires it to be non-empty.
- **`Source`** — one or more citations, each a backticked `` `path:line` `` or
  `` `path:start-end` ``, repo-relative. The guard resolves every one: the file must exist and the
  line range must lie inside it.
- **`Pin`** — exactly one of three forms (§ ruling 3). The guard resolves it.
- **`Notes`** — prose. Required non-empty on a `white-box-only` row (that is where the
  justification lives); optional elsewhere.

### 3. The `Pin` cell has exactly three legal forms, and each is verified

| Form | Literal | What the guard checks |
|---|---|---|
| A real test | `` `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection` `` | The file exists **and** declares that symbol. For `.spec.ts`, the title must be a *literal* title found by `findTestCalls` (`tests/guards/ast.ts`) — so a title in a comment does not count. For `.py`, a line matching `^[ \t]*def <name>(`. For `.go`, a line matching `^func [(recv) ]<Name>(`. Any other extension fails: the guard fails closed on a shape it cannot read |
| A row a later PR owes | `owed: 2a-4` | Matches `^owed: (2[a-d]-\d{1,2})$`, and the row id appears in the guard's `OWED` list |
| A row no test can pin | `white-box-only` | The row id appears in the guard's `WHITE_BOX_ONLY` list, **and** the row's `Notes` cell is non-empty |

**Enclosing backticks are optional on the last two forms** and required on the first (its own regex
carries them). This was found by prototyping the guard against the three example rows before writing
this plan: a Markdown author's hand backticks `owed: 2a-4` in a table cell because the format section
above writes it as inline code, and a format that fails on the more natural of two spellings is a
format people get wrong. `parsePin` strips one enclosing pair before matching the two bare forms.

The reference syntax is `path::symbol`. A Python reference may carry a class:
`apps/proxy/live_proxy/tests/test_x.py::TestFoo::test_bar` — the guard verifies the **last**
segment. The same `path::symbol` shape takes a Go test in 2c-9 with no reformatting, which is why
the extension, not a separate column, decides how the symbol is verified.

**What this proves and what it does not.** A resolvable citation is not a *correct* citation: the
guard proves `apps/proxy/live_proxy/input/buffer.py:82` is a line that exists, never that line 82 is
the packet-realignment arithmetic. Only review does that. The guard's job is to make drift and
absence loud, and it does both: a deleted file, a truncated file, a renamed test, a row shipped with
an empty Pin.

### 4. `white-box-only` is an allowlist, not a keyword

This is the loophole the spec's own text invites: "behaviour not observable from outside is marked
white-box-only and honestly recorded as behaviour the Go relay is **not** held to". Left as a bare
keyword, `white-box-only` is a one-word way to make any inconvenient row stop counting.

It is therefore confined exactly the way `tests/guards/allowlist.ts` confines the four grey-box
capabilities: a hand-written list in the guard, compared with `toEqual` — not `toContain`. Marking a
row white-box-only requires editing `e2e/tests/guards/parity-matrix.ts` and writing a `why` in the
same diff; **and un-marking one also requires that edit**, so the list cannot rot in either
direction. `capabilities.spec.ts`'s own comment makes the same argument in the same words, and this
guard reuses it deliberately rather than inventing a second discipline.

The matrix ships with exactly two such rows, both named by the spec: `server.py`'s greenlet/thread
topology, and `_execute_redis_command`'s exception-swallowing shape. Both are deleted outright by
the spec's D2 rather than reproduced in Go.

### 5. `owed:` is a ratchet, pinned by the same mechanism

At 2a-1 most rows have no test — that is what 2a-3 … 2a-6 exist to fix. A guard that simply
accepted "no test yet" would be green forever and gate nothing.

So an unpinned row must say **which PR owes it**, and the set of unpinned row ids is pinned in the
guard by `toEqual` against `OWED`. Closing a row is a two-line diff: change the Pin cell to a test
reference, delete the id from `OWED`. Adding an unpinned row is the same edit in reverse, and cannot
happen by accident. When `OWED` reaches `[]`, Gate 1 is met — the phase's own definition of "the
behaviour is pinned" — and 2a-7's coverage gate is the only thing left blocking 2c.

Yes, this duplicates a fact between the document and the guard. That duplication *is* the
mechanism, and it is the mechanism this directory already uses.

### 6. Twenty-seven rows, and the spec's "24" is an arithmetic slip

The spec's Gate 1 table enumerates rows 1–18 individually plus a collapsed `19-26` entry standing
for "every row of the Phase 1 authorize matrix (7 principal rows × 6 columns)"; its 2a PR table then
calls the result "Gate 1's 24 rows". Three numbers that cannot all be right: `19-26` is eight ids
for seven principals, and 18 + 7 = 25, not 24.

**Ruling:** expand the collapsed entry to **one row per principal**, which the Phase 1 spec's own
authorize matrix (`docs/superpowers/specs/2026-09-04-phase1-process-split-design.md:705-713`) gives
as seven — Internal, Admin, XC credentials, JWT/API key, Session, Anonymous, Stream-by-hash. That
makes rows 19–25. Add the two `white-box-only` rows the spec's prose names but its table omits, as
rows 26–27. **Total: 27 rows.** The executor may add further rows found while reading the source
(the spec explicitly invites this); ids continue from 28.

### 7. Rows 14–17 are owed by 2a-5

The spec's 2a PR table assigns matrix rows to PRs — 2a-3 closes 7–10 and 13; 2a-4 closes 1–6 and 12;
2a-6 closes 11 — and assigns **no rows at all to 2a-5**, whose stated scope is `server.py`'s
bring-up, event listener loop and zombie detection. Rows 14 (status payload field types), 15
(`stream_xc`'s decision hand-off), 16 (stream-by-hash authorization) and 17 (`ip_address`
provenance) are assigned to no PR by the spec at all.

**Ruling:** they are owed by **2a-5**. All four are view-level or status-payload rows needing no
subprocess harness, which is the bucket 2a-5 is left holding, and leaving a row owed by nobody is
the one outcome the ratchet cannot tolerate. This widens 2a-5's spec scope by four rows; the 2a-5
plan must pick them up, and this plan's final report says so.

Row 18 is owed by **2b-3**, which the spec states outright ("2b-3 records the answer as part of
closing this row").

### 8. The guard's own tests are `@characterization`

`docs/adr/0002-e2e-test-taxonomy.md`: `@contract` means the assertion is at a client-facing surface
and must survive any behaviour-preserving reimplementation; `@characterization` means it is
deliberately coupled to *this* implementation and must carry a comment naming the fact it pins.

Every test in this PR asserts facts about this repository's own source tree — a Markdown file's
column layout, file paths under `apps/`, test titles in `e2e/tests/`. None of it is client-observable
behaviour, and all of it changes shape when the suite is restructured; the matrix itself is
explicitly rewritten in 2c-9 and its Python citations go away in 2d. That is `@characterization` by
the ADR's own definition, and it is what every other file in `tests/guards/` carries. The comment
requirement is met by reusing the block comment the five existing guards already share, verbatim.

Note the direction of the ADR's asymmetry — ambiguity resolves to `@contract` — and why it does not
apply: there is no ambiguity here. A `@contract` tag on a test that reads `docs/` off disk would be
a false claim that some client can observe the file.

### 9. No workflow change, no metrics change

- **`e2e-tests.yml`:** unchanged. The `guards` project already has its own container-less CI job
  (`e2e/README.md` § CI: "`guards` is the one project deliberately **not** in that matrix"), and it
  runs the project, not a file list. A new spec file inside `tests/guards/` gets CI coverage with no
  wiring. **Do not add anything to the `changes` job's `projects` list** — that list is for new
  Playwright *projects*, and this PR adds none.
- **`metrics/curated/`:** unchanged. `CLAUDE.md` § Agent skills requires a metrics update from a PR
  that closes a ledger issue, adds a `test.fail()` pin, merges a goal, or ticks a Done log. This PR
  does none of the four: it closes no issue, adds no `test.fail()`, is not a goal merge, and the
  Phase 2 Done log lives in the spec on the PR 0 branch, not here. The spec's own § Documentation
  puts the phase's `metrics/curated/` work in `migration/phase2d-docs`. Task 8 verifies the diff
  names nothing under `metrics/`.
- **`CLAUDE.md`:** one line added (Task 7). `docs/relay-parity-matrix.md` becomes a load-bearing
  top-level document that every later Phase 2 PR cites, and `CLAUDE.md` § Repository and direction
  is where this fork lists exactly that kind of document. A matrix nobody can find is not
  load-bearing.

### 10. Two files, not one

`e2e/tests/guards/parity-matrix.ts` holds the parser, the types and the two pinned lists;
`e2e/tests/guards/parity-matrix.spec.ts` holds the five tests. This is the split the directory
already has (`ast.ts` and `allowlist.ts` are helper modules; the `.spec.ts` files are assertions),
and it is what lets 2a-3 … 2a-6 edit one small list without touching a test body.

**Do not put the lists in `allowlist.ts`.** That file is the grey-box capability allowlist,
`capabilities.spec.ts`'s data, and its `Capability` type does not fit. A second concern in it makes
both harder to read.

---

## Done criteria

- [ ] **`docs/relay-parity-matrix.md` exists** and carries 27 rows: 1–18 as the spec's Gate 1 table
      enumerates them, 19–25 one per Phase 1 authorize-matrix principal, 26–27 the two
      `white-box-only` rows.
- [ ] **Every row's `Source` cell carries at least one `file:line` citation that resolves** against
      this worktree — file present, line range inside it.
- [ ] **Every row's `Pin` cell is one of the three legal forms, and resolves** — a real test symbol,
      an `owed: <pr>` marker whose id is in `OWED`, or `white-box-only` with a non-empty `Notes`
      cell and an id in `WHITE_BOX_ONLY`.
- [ ] **`e2e/tests/guards/parity-matrix.spec.ts` is green**, five tests:
      `npx playwright test --project=guards parity-matrix`
- [ ] **The whole `guards` project is green**, including `tags.spec.ts`, which now sees five more
      declarations: `npx playwright test --project=guards`
- [ ] **`cd e2e && npx tsc --noEmit` is clean.**
- [ ] **Each of the guard's five checks is verified by mutation**, and the mutations are recorded in
      the spec file's header comment — the discipline every other guard in the directory follows
      and states in its own header (Task 6).
- [ ] **`e2e/COVERAGE.md`'s Guards table carries a row for the new guard**, with its "Proved by"
      column filled from Task 6's real mutation results, not from this plan.
- [ ] **`e2e/README.md` § Projects' `guards` enumeration names the parity matrix guard.**
- [ ] **`CLAUDE.md` § Repository and direction names `docs/relay-parity-matrix.md`.**
- [ ] **`git diff --name-only main...HEAD` names nothing under `apps/`, `core/`, `dispatcharr/`,
      `frontend/`, `docker/`, `scripts/` or `metrics/`.**
- [ ] **The PR is open** against `main`, with the plan committed on the branch.

---

## Test environment for this worktree

The edit and commit hooks resolve the project directory from the harness, so **in a worktree they do
not run automatically**. Run them yourself.

1. **Install the e2e package once** — `e2e/node_modules` is absent in a fresh worktree, and without
   it both the typecheck hook and Playwright are unavailable:
   ```bash
   cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npm ci
   ```
   If it is missing the typecheck hook says so and exits 0 — **a skipped check is not a passed
   check**; say so in the task report rather than describing the work as verified.
2. **After editing any `.ts` file, run the affected-file hook by hand.** For `e2e/**/*.ts` it is a
   blocking `tsc --noEmit` over the whole `e2e` package:
   ```bash
   echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' \
     | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 \
       /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/.claude/hooks/run-affected-tests.sh
   ```
   Exit 2 = blocking failure; read the output. Equivalent direct command, which is what the hook
   runs: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit`.
   **Markdown files match no hook** — `docs/relay-parity-matrix.md`, `e2e/COVERAGE.md`,
   `e2e/README.md` and `CLAUDE.md` are checked only by the guard itself and by your own reading.
3. **Run the guards project.** No container, no browser, no fixtures — about a second:
   ```bash
   cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
   ```
   Just this PR's file: `npx playwright test --project=guards parity-matrix`
   One test: `npx playwright test --project=guards -g 'the parity matrix parses'` (`-g` matches
   exact titles, so quote them in full).
   **No `E2E_BASE_URL`, no `scripts/e2e_up.sh`, no container variables are needed for `guards`, and
   none should be set.** Never run `scripts/e2e_up.sh` for this PR, and never pass `--down` or
   `--reset` to anything: the shared `dispatcharr-e2e` and `e2e-upstream` stacks are not ours to
   touch, and killing the shared provider is a real incident this repo has already had (#187).
4. **Before every commit, run the commit gate by hand:**
   ```bash
   CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 \
     /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/.claude/hooks/pre-commit-tests.sh --git-hook
   ```
   This PR stages nothing under `apps/`, `core/`, `dispatcharr/` or `frontend/`, so
   `labels_for_changed_paths()` selects **no backend label** and the gate has nothing to run. That
   is the expected, correct answer here — not a skipped check.
5. **No backend test container is needed for this PR.** Nothing in the diff is Python. If you find
   yourself starting `dispatcharr-testrunner`, you have left scope.

---

## File Structure

```
docs/
  relay-parity-matrix.md                      NEW     prose + § Format + the 27-row table
  superpowers/plans/
    2026-09-09-phase2-2a1-parity-matrix.md    PRESENT this file, committed by the planning pass
e2e/
  tests/guards/parity-matrix.ts               NEW     parser, types, WHITE_BOX_ONLY, OWED
  tests/guards/parity-matrix.spec.ts          NEW     five @characterization tests
  COVERAGE.md                                 MODIFY  one row in the Guards (G11) table
  README.md                                   MODIFY  § Projects' guards row names the new guard
CLAUDE.md                                     MODIFY  one line in § Repository and direction
```

Nothing else. In particular: no `e2e/playwright.config.ts` change (no new project), no
`e2e/package.json` change (no new script, no new dependency), no `.github/workflows/` change, no
`metrics/` change — § Design ruling 9.

---

### Task 1: Verify the base and the anchors

**Files:** none edited. This task produces no commit.

**Interfaces:**
- Consumes: the worktree at `a948cd8a`.
- Produces: a verified starting tree, an installed `e2e/node_modules`, and confirmation that the
  three anchors Task 4 cites literally are still where this plan says they are.

- [ ] **Step 1: Confirm the worktree, branch and base.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
git branch --show-current
git log --oneline -1
git status --short
```

Expected: `migration/phase2a-parity-matrix`; `a948cd8a docs(phase1): the phase is done …` (or that
commit plus this plan's own commit); a clean tree, or only this plan file. **If the branch is
anything else, stop** — every other task edits files, and doing that on the wrong branch is not
recoverable by a later step.

- [ ] **Step 2: Install the e2e package and prove the guards project is green today.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npm ci
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
```

Expected: `npm ci` completes; `tsc` prints nothing and exits 0; Playwright reports all guards
passing (7 spec files today: `tags`, `capabilities`, `testid`, `global-mutation`,
`pageerrors-enforcement`, `upstream-contract`, plus whatever else the directory holds). **Record the
passing test count** — Task 8 checks it went up by exactly five.

If any of the three fails on an untouched tree, stop and report: this PR cannot be verified on a
base that is already red.

- [ ] **Step 3: Verify the three anchors Task 4 writes literally.**

These are the only `file:line` values this plan hands you to copy rather than derive. Each was
verified at `a948cd8a`; confirm before copying.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
sed -n '45p;339p;460p;595p' apps/proxy/live_proxy/channel_status.py
sed -n '59p;129p' apps/proxy/relay_serializers.py
sed -n '67p;79p;312p' apps/proxy/live_proxy/output/profile/manager.py
sed -n '138p;161p' apps/proxy/live_proxy/server.py
grep -n "three clients share exactly one upstream connection" e2e/tests/streaming/shared-upstream.spec.ts
grep -n "two clients on one output profile share a single transcode" e2e/tests/streaming-greybox/output-profile-sharing.spec.ts
```

Expected, in order: `'owner': metadata.get(ChannelMetadataField.OWNER, 'unknown'),`;
`info['source_fps'] = source_fps`; `'owner': metadata.get(ChannelMetadataField.OWNER),`;
`info['source_fps'] = float(source_fps)`; `source_fps = serializers.FloatField(required=False)`;
`source_fps = serializers.CharField(required=False)`; `def start(self) -> bool:`; the
`"Another worker owns transcode, using shared buffer"` string; `def _acquire_owner_lock(self)`;
`def _execute_redis_command(self, command_func, *args, **kwargs):`;
`def _spawn_on_hub(self, fn, *args, **kwargs):`; and the two test titles at line 4 and line 47.

**Any line that does not match: use what the tree says, not what this plan says**, and note the drift
in the task report.

---

### Task 2: The matrix skeleton and the guard's structural parse

**Files:**
- Create: `e2e/tests/guards/parity-matrix.spec.ts`
- Create: `e2e/tests/guards/parity-matrix.ts`
- Create: `docs/relay-parity-matrix.md`

**Interfaces:**
- Consumes: `REPO_ROOT` from `e2e/tests/guards/ast.ts`.
- Produces: `MATRIX_REL: string`, `MATRIX_PATH: string`, `MATRIX_HEADER: string`,
  `type MatrixRow = { id: number; behaviour: string; source: string; pin: string; notes: string;
  line: number }`, `parseMatrix(markdown: string): MatrixRow[]`, `readMatrix(): Promise<string>`.
  Tasks 3–5 add to this same module and never change these signatures.

- [ ] **Step 1: Write the failing test.**

Create `e2e/tests/guards/parity-matrix.spec.ts`:

```ts
/**
 * `docs/relay-parity-matrix.md` stays machine-readable, and every row stays
 * accounted for.
 *
 * The matrix is Phase 2's load-bearing artifact: 2a's own checklist, 2c's
 * implementation spec (each Go PR closes a named set of rows), and 2d's
 * cutover checklist. Everything after 2a-1 addresses rows by number, so the
 * table's format is a contract, not a style choice — and a contract nobody
 * checks is the thing `tests/guards/allowlist.ts` already says decays
 * silently: "a convention plus a README decays silently. This does not."
 *
 * Five checks, in `./parity-matrix`:
 *   1. the table parses — found by its exact header, five cells a row, ids
 *      unique and ascending;
 *   2. every `Source` citation resolves to a real file and a line inside it;
 *   3. every `Pin` resolves — a real test symbol, an `owed:` marker naming a
 *      real PR, or `white-box-only`;
 *   4. `white-box-only` rows are exactly the allowlisted ones, each with a
 *      justification in its `Notes` cell;
 *   5. unpinned rows are exactly the ones the guard still owes.
 *
 * Checks 4 and 5 duplicate a fact between the document and this directory on
 * purpose, in `capabilities.spec.ts`'s idiom and for its reason: `toEqual`,
 * not `toContain`, so that closing a row and opening one are both deliberate
 * edits, and the list cannot rot in either direction.
 *
 * What this guard does NOT prove: that a citation points at the *right* code.
 * `input/buffer.py:82` is checked to be a line that exists, never to be the
 * packet-realignment arithmetic. Review does that. This guard makes drift and
 * absence loud, which is the half that rots without enforcement.
 *
 * No container, no browser: every file is read straight off disk with
 * `node:fs/promises`, the same shape `upstream-contract.spec.ts` uses.
 */
import { test, expect } from '@playwright/test';
import { MATRIX_REL, parseMatrix, readMatrix } from './parity-matrix';

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, Markdown column layout, test
// titles declared in other specs. None of it is client-observable behaviour,
// and all of it changes shape when the suite is restructured. See
// docs/adr/0002-e2e-test-taxonomy.md.
test('the parity matrix parses', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());

  const ids = rows.map((r) => r.id);
  expect(
    new Set(ids).size,
    `${MATRIX_REL} reuses a row id. Ids are this phase's addressing scheme — 2c PRs close ` +
      '"rows 7-10, 13" — so an id is never reused and never renumbered. Ids seen: ' +
      ids.join(', '),
  ).toBe(ids.length);

  const outOfOrder = ids.filter((id, i) => i > 0 && id <= ids[i - 1]);
  expect(
    outOfOrder,
    `${MATRIX_REL} has rows out of ascending id order. Append new rows at the end with the ` +
      'next free id; never renumber.',
  ).toEqual([]);

  const empty = rows.filter((r) => r.behaviour === '').map((r) => `${MATRIX_REL}:${r.line}`);
  expect(
    empty,
    `${MATRIX_REL} has a row with an empty Behaviour cell. A row names one ` +
      'externally-observable live-path behaviour, in one sentence.',
  ).toEqual([]);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL — `Cannot find module './parity-matrix'`.

- [ ] **Step 3: Write the minimal helper module.**

Create `e2e/tests/guards/parity-matrix.ts`:

```ts
/**
 * `docs/relay-parity-matrix.md`'s parser, and the two lists a row's status is
 * pinned against.
 *
 * Separate from `parity-matrix.spec.ts` for the reason `allowlist.ts` is
 * separate from `capabilities.spec.ts`: 2a-3 through 2a-6, 2b-3 and every 2c
 * PR each close a matrix row, and closing one should be a two-line diff —
 * change a Pin cell, delete an id from `OWED` — not an edit inside a test
 * body.
 *
 * The table is found by exact header match rather than parsed as Markdown.
 * No Markdown parser is available without adding a dependency, which this
 * phase forbids, and a hand-rolled loose parser is exactly the thing that
 * silently accepts a malformed row. An exact header is a format this module
 * can be trusted about; anything it cannot read throws, naming the file and
 * the line.
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from './ast';

/** Repo-relative, for error messages a reader can paste into an editor. */
export const MATRIX_REL = 'docs/relay-parity-matrix.md';

export const MATRIX_PATH = path.join(REPO_ROOT, MATRIX_REL);

/**
 * The one line this module finds the table by, character for character.
 * Changing it means changing every guard below; do not reformat it.
 */
export const MATRIX_HEADER = '| # | Behaviour | Source | Pin | Notes |';

export type MatrixRow = {
  id: number;
  behaviour: string;
  source: string;
  pin: string;
  notes: string;
  /** 1-based line number of this row inside the matrix document. */
  line: number;
};

export function readMatrix(): Promise<string> {
  return readFile(MATRIX_PATH, 'utf8');
}

/**
 * Cells of one table row, outer pipes stripped and each cell trimmed.
 *
 * A literal `|` inside a cell splits the row into six and is rejected by the
 * caller, naming the line. That is the whole escaping rule, and the document's
 * own "Format" section states it.
 */
function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

export function parseMatrix(markdown: string): MatrixRow[] {
  const lines = markdown.split('\n');
  const headerIndex = lines.findIndex((line) => line.trim() === MATRIX_HEADER);
  if (headerIndex === -1) {
    throw new Error(
      `${MATRIX_REL} has no line equal to the matrix header:\n  ${MATRIX_HEADER}\n` +
        'Every guard here finds the table by that exact line. Do not reformat it, and do not ' +
        'add or rename a column without updating e2e/tests/guards/parity-matrix.ts.',
    );
  }

  const delimiter = lines[headerIndex + 1] ?? '';
  if (!/^\s*\|(?:\s*:?-+:?\s*\|)+\s*$/.test(delimiter)) {
    throw new Error(
      `${MATRIX_REL}:${headerIndex + 2} should be the table's delimiter row ` +
        `(|---|---|---|---|---|), found ${JSON.stringify(delimiter)}.`,
    );
  }

  const rows: MatrixRow[] = [];
  for (let i = headerIndex + 2; i < lines.length; i++) {
    const raw = lines[i];
    if (!raw.trimStart().startsWith('|')) break;

    const location = `${MATRIX_REL}:${i + 1}`;
    const cells = splitRow(raw);
    if (cells.length !== 5) {
      throw new Error(
        `${location} has ${cells.length} cells, expected 5 (# | Behaviour | Source | Pin | ` +
          'Notes). A literal "|" inside a cell splits the row; this table does not allow one.',
      );
    }

    const [idCell, behaviour, source, pin, notes] = cells;
    if (!/^\d+$/.test(idCell)) {
      throw new Error(
        `${location} has ${JSON.stringify(idCell)} in the # column; a row id is a decimal ` +
          'integer, unique and never reused.',
      );
    }

    rows.push({ id: Number(idCell), behaviour, source, pin, notes, line: i + 1 });
  }

  if (rows.length === 0) {
    throw new Error(
      `${MATRIX_REL} has the matrix header but no rows under it. That is this module being ` +
        'broken, or the table being empty; either way nothing below is enforcing anything.',
    );
  }

  return rows;
}
```

- [ ] **Step 4: Run it to verify it fails for the next reason.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL — `ENOENT … docs/relay-parity-matrix.md`.

- [ ] **Step 5: Create the matrix document with its prose and three rows.**

These three rows are the format's worked examples: a pinned row, an owed row, and a
`white-box-only` row. Tasks 3–5 add the other twenty-four around them. **Write them literally** —
every value here was verified in Task 1 step 3.

Create `docs/relay-parity-matrix.md`:

````markdown
# The relay parity matrix

Every externally-observable behaviour of the **live** relay path, the Python source it was derived
from, and what pins it.

This document is Phase 2's load-bearing artifact
(`docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` § Stage 2a, Gate 1). It is 2a's own
checklist, 2c's implementation spec — each Go PR closes a named set of rows — and 2d's cutover
checklist: every row must show a passing Go-side equivalent before nginx's live locations move.
Rows are addressed **by number** everywhere in the phase, so **an id is never reused and never
renumbered**; a retired row keeps its id and says so in its Notes.

Rows were derived by reading the source, not by cataloguing tests that happen to exist. Most rows
therefore start life with no test at all — that is the gap 2a-3 through 2a-6 exist to close, and the
`owed:` marker below is how a row says which PR owes it.

Scope is the live TS/fMP4 path only (spec D1). VOD, catch-up and `timeshift.php` stay on the Python
relay for the whole of Phase 2 and are not rows here.

Enforced by `e2e/tests/guards/parity-matrix.spec.ts`, in the `guards` Playwright project. It needs
no container: `cd e2e && npx playwright test --project=guards parity-matrix`.

## Format

The guard finds the table by the exact line `| # | Behaviour | Source | Pin | Notes |`. Do not
reformat that line, and do not add or rename a column without changing
`e2e/tests/guards/parity-matrix.ts` in the same commit.

- **`#`** — a decimal integer. Unique, strictly ascending, never reused, never renumbered.
- **`Behaviour`** — one sentence naming the externally-observable behaviour.
- **`Source`** — one or more backticked, repo-relative citations: `` `path:line` `` or
  `` `path:start-end` ``. The guard checks that each file exists and each range lies inside it. It
  cannot check that the range is the *right* code; that is what review is for.
- **`Pin`** — exactly one of three forms:
  - a test reference, `` `path::symbol` `` — for a `.spec.ts` the symbol is the test's literal
    title; for a `.py` it is the `def` name (optionally `path::Class::method`, of which the last
    segment is checked); for a `.go` it is the `func` name. The guard resolves the symbol in the
    file, so a renamed test fails here;
  - `owed: <pr>` — no test yet, and the named PR owes one. `<pr>` is a Phase 2 PR id such as
    `2a-4`. The set of owed row ids is pinned in the guard, so closing a row is a two-line diff
    (change this cell, delete the id from `OWED`) and opening one cannot happen silently;
  - `white-box-only` — behaviour no client can observe, recorded honestly as behaviour **the Go
    relay is not held to**. This is an allowlist, not a keyword: the row id must also appear in the
    guard's `WHITE_BOX_ONLY` list with a `why`, and the `Notes` cell must say why here too.

  Enclosing backticks are optional on the last two — `` `owed: 2a-4` `` and `owed: 2a-4` both
  parse — and required on the test reference.
- **`Notes`** — prose. Required non-empty on a `white-box-only` row.

**No cell may contain a literal `|`.** A stray pipe splits the row and the guard fails naming the
line.

## The matrix

| # | Behaviour | Source | Pin | Notes |
|---|---|---|---|---|
| 11 | One transcode process runs per active `(channel, profile)` pair across the cluster: a second client on the same Output Profile attaches to the existing process's buffer instead of spawning its own | `apps/proxy/live_proxy/output/profile/manager.py:67-122`, `apps/proxy/live_proxy/output/profile/manager.py:312-321` | `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts::two clients on one output profile share a single transcode` | Ten AC3 clients cost one ffmpeg. 2a-6 may re-pin this to a harness test; the existing e2e spec stands until it does |
| 14 | Status payload field types differ by endpoint: `owner` is `null` on the list endpoint and the literal string `unknown` on the detail endpoint, `ffmpeg_speed` is a float on both, and `source_fps` is a float on list but a string on detail | `apps/proxy/live_proxy/channel_status.py:45`, `apps/proxy/live_proxy/channel_status.py:460`, `apps/proxy/live_proxy/channel_status.py:339`, `apps/proxy/live_proxy/channel_status.py:595`, `apps/proxy/relay_serializers.py:59`, `apps/proxy/relay_serializers.py:129` | `owed: 2a-5` | Neither serializer supplies a `default=`, so the builder's value reaches the wire unchanged. A test that checks the string against only one of the two endpoints proves nothing about the other |
| 27 | Not held to: `_execute_redis_command` swallows every Redis exception to `None` after one reconnect attempt, so a caller cannot distinguish "key absent" from "Redis unreachable" | `apps/proxy/live_proxy/server.py:138-159` | `white-box-only` | Deleted, not ported: spec D2 removes Redis from the live path entirely, so there is no analogous call in the Go relay to swallow anything. One of the three fail-open paths `CLAUDE.md` records as a live defect |
````

- [ ] **Step 6: Run the test to verify it passes.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 1 test.

Note there is no row-count self-check yet — it arrives in Task 5, once all 27 rows exist. A
threshold asserted now would be a number to churn three times.

- [ ] **Step 7: Typecheck and run the whole guards project.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
```

Expected: `tsc` silent; every guard green, including `tags.spec.ts` — which now sees one more
declaration and requires its inline `{ tag: '@characterization' }`. If `tags.spec.ts` reports the new
test as untagged, the details object was not written as an inline literal.

- [ ] **Step 8: Commit.**

Write the message with the Write tool to `<SCRATCH>/msg-task2.txt`, then stage and commit in **two
separate Bash calls**.

**`<SCRATCH>` throughout this plan means your session's scratchpad directory** — the absolute path
your harness names in its environment section. If you do not have one, use `/tmp/dispatcharr-2a1/`
and `mkdir -p` it first. It must be **outside the repository**: a message file committed by accident
is a file this PR's diff is not allowed to contain (Task 8 step 2 checks).

```
docs(phase2): the parity matrix's format, and the guard that parses it

Gate 1 of the Phase 2 spec needs a matrix that later PRs can address by row
number and fill in without reformatting. This lands the format and its
parser: an exact five-column header the guard finds by string match, ids that
are unique, ascending and never reused, and three worked rows covering the
three Pin forms.

The parser lives beside the tests rather than inside them, for the reason
allowlist.ts lives beside capabilities.spec.ts: closing a row should be a
two-line diff, not an edit in a test body.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git add docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts e2e/tests/guards/parity-matrix.spec.ts
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git commit -F <SCRATCH>/msg-task2.txt
```

---

### Task 3: Citations resolve, and rows 1–9

**Files:**
- Modify: `e2e/tests/guards/parity-matrix.ts` (append)
- Modify: `e2e/tests/guards/parity-matrix.spec.ts` (append one test)
- Modify: `docs/relay-parity-matrix.md` (nine rows)

**Interfaces:**
- Consumes: `MatrixRow`, `MATRIX_REL`, `parseMatrix`, `readMatrix` from Task 2.
- Produces: `type Citation = { path: string; start: number; end: number }`,
  `citationsIn(source: string): Citation[]`,
  `citationProblem(c: Citation): Promise<string | undefined>` — `undefined` means fine, a string is
  the human-readable reason. Task 4 uses the same "problem or `undefined`" shape.

- [ ] **Step 1: Write the failing test.**

Append to `e2e/tests/guards/parity-matrix.spec.ts` (and extend the import from `./parity-matrix` to
`{ citationProblem, citationsIn, MATRIX_REL, parseMatrix, readMatrix }`):

```ts
test('every row cites source that resolves', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());
  const findings: string[] = [];

  for (const row of rows) {
    const citations = citationsIn(row.source);
    if (citations.length === 0) {
      findings.push(
        `${MATRIX_REL}:${row.line} (row ${row.id}) — Source cell carries no citation. ` +
          'Every row names the Python source it was derived from, as `path:line` or ' +
          '`path:start-end` in backticks.',
      );
      continue;
    }
    for (const citation of citations) {
      const problem = await citationProblem(citation);
      if (problem !== undefined) {
        findings.push(`${MATRIX_REL}:${row.line} (row ${row.id}) — ${problem}`);
      }
    }
  }

  expect(
    findings,
    'A citation that no longer resolves is a row nobody can act on. Re-locate the behaviour and ' +
      'update the line numbers; the tree wins, not the matrix.\n' +
      findings.join('\n'),
  ).toEqual([]);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL — `Cannot find module` is gone, but TypeScript reports `citationsIn` and
`citationProblem` are not exported from `./parity-matrix`.

- [ ] **Step 3: Implement the citation resolver.**

Append to `e2e/tests/guards/parity-matrix.ts`:

```ts
export type Citation = { path: string; start: number; end: number };

/**
 * `` `path:12` `` and `` `path:12-40` ``. Backticked, so prose that happens to
 * read like a path never matches — the same "code, not comments" discipline
 * `ast.ts` argues for at the TypeScript level, at the level Markdown offers.
 */
const CITATION_RE = /`([^`\s]+):(\d+)(?:-(\d+))?`/g;

export function citationsIn(source: string): Citation[] {
  const out: Citation[] = [];
  for (const match of source.matchAll(CITATION_RE)) {
    const start = Number(match[2]);
    // Truthiness, not `!== undefined`: `RegExpMatchArray`'s index signature is
    // `string`, so comparing an absent group to `undefined` is a type error
    // under `strict`. A `(\d+)` capture is never the empty string, so an
    // absent end-of-range is the only falsy case.
    out.push({ path: match[1], start, end: match[3] ? Number(match[3]) : start });
  }
  return out;
}

/**
 * `null` means "no such file". Cached because a 27-row matrix cites the same
 * half-dozen large files many times over, and `server.py` alone is 2,500
 * lines.
 */
const lineCounts = new Map<string, number | null>();

async function lineCountOf(rel: string): Promise<number | null> {
  const cached = lineCounts.get(rel);
  if (cached !== undefined) return cached;
  let count: number | null;
  try {
    count = (await readFile(path.join(REPO_ROOT, rel), 'utf8')).split('\n').length;
  } catch {
    count = null;
  }
  lineCounts.set(rel, count);
  return count;
}

/** A human-readable reason, or `undefined` when the citation resolves. */
export async function citationProblem(citation: Citation): Promise<string | undefined> {
  const { path: rel, start, end } = citation;
  const count = await lineCountOf(rel);
  if (count === null) return `no such file: ${rel}`;
  if (start < 1 || start > count) {
    return `${rel}:${start} is outside the file, which has ${count} lines`;
  }
  if (end < start) return `${rel}:${start}-${end} ends before it starts`;
  if (end > count) {
    return `${rel}:${start}-${end} runs past the end of the file, which has ${count} lines`;
  }
  return undefined;
}
```

- [ ] **Step 4: Run the test to verify it passes on the three existing rows.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 2 tests. All three rows' citations resolve — they were verified in Task 1 step 3.

- [ ] **Step 5: Locate and add rows 1–9.**

Each row below gives the behaviour text to write, the PR that owes it (§ Design ruling 7), and
**how to find the citation**. Run the locator, read enough of the surrounding code to be sure you
have the right construct, and cite the span — a whole function where the behaviour is a function, a
tight range where it is a few lines. Do not cite a whole file.

Insert them **before** row 11, keeping the table in ascending id order.

| # | Behaviour to write | Pin | How to find the Source |
|---|---|---|---|
| 1 | Buffering failover trigger: ffmpeg's reported `speed=` below `buffering_speed`, sustained longer than `buffering_timeout` (15s default), calls `_try_next_stream()` | `owed: 2a-4` | `grep -n "buffering_speed\|buffering_timeout" apps/proxy/live_proxy/input/manager.py` — the health-monitor block that compares `ffmpeg_speed` to `self.buffering_speed` and measures `buffering_duration` against `self.buffering_timeout` before calling `_try_next_stream()` (around `:1120-1195` at `a948cd8a`). Cite that span **and** the `speed=` extraction in `apps/proxy/live_proxy/services/log_parsers.py`'s `FFmpegLogParser` (`grep -n "class FFmpegLogParser" apps/proxy/live_proxy/services/log_parsers.py`) |
| 2 | Dead-air failover trigger: no data for longer than the inactivity threshold, observed on three consecutive 5-second health checks | `owed: 2a-4` | `grep -n "_health_inactivity_threshold\|consecutive_unhealthy_checks\|max_unhealthy_checks" apps/proxy/live_proxy/input/manager.py` — `_health_inactivity_threshold` and the loop that increments `consecutive_unhealthy_checks` and compares it to `max_unhealthy_checks` (around `:1503-1560`). Cite both |
| 3 | Connect-failure trigger: `MAX_RETRIES` (3) connection failures inside `RETRY_WINDOW_SECONDS` (1800) exhausts the source; the counter resets after a window with no failure | `owed: 2a-4` | `grep -n "max_retries\|_retry_window_seconds\|_last_failure_time" apps/proxy/live_proxy/input/manager.py` — the two `__init__` snapshots (around `:50-51`) and the window comparison (around `:187`). Also cite the defaults in `apps/proxy/config.py` (`grep -n "MAX_RETRIES\|RETRY_WINDOW_SECONDS" apps/proxy/config.py`) |
| 4 | `speed=` is ffmpeg's cumulative average since process start, not an instantaneous rate, so a front-loaded lead must burn off before the buffering detector can arm — roughly 55 seconds measured | `owed: 2a-4` | `apps/proxy/live_proxy/services/log_parsers.py`, `FFmpegLogParser`'s `speed=` extraction — the same span cited in row 1. The behaviour is a property of the value, not of extra code; the Notes cell is where the ~55s and its consequence go. Cite the parser and the comparison site that consumes it |
| 5 | Buffering thresholds are snapshotted in `StreamManager.__init__`; changing `proxy_settings` mid-stream does not reach a running channel | `owed: 2a-4` | `grep -n "ConfigHelper.buffering_timeout()\|ConfigHelper.buffering_speed()" apps/proxy/live_proxy/input/manager.py` — the two `self.` assignments in `__init__` (around `:60-61`). Cite that pair |
| 6 | `MAX_STREAM_SWITCHES` does not bound buffering-triggered switches: those come from the stderr reader, which calls `_try_next_stream()` without passing through the main loop's counter | `owed: 2a-4` | `grep -rn "max_stream_switches" apps/proxy/live_proxy/` for where the bound *is* applied, and `grep -n "_try_next_stream" apps/proxy/live_proxy/input/manager.py` for the call sites. Cite the stderr-path call site and the counter it bypasses. **Filed as an issue and reproduced, not fixed** (spec D5) — say so in Notes |
| 7 | The chunk index is monotonic for the channel's life and is never reset by a stream switch, which is why a switch does not disturb connected clients | `owed: 2a-3` | `grep -n "def add_chunk\|def reset_buffer_position\|buffer_index" apps/proxy/live_proxy/input/buffer.py` — `add_chunk`'s index increment (around `:65-135`). Cite it, and `reset_buffer_position` (around `:136`) if reading it confirms it is not on the switch path |
| 8 | A new client joins roughly 5 seconds behind live, positioned through the `chunk_timestamps` sorted set rather than at the newest chunk | `owed: 2a-3` | `grep -n "find_chunk_index_by_time\|chunk_timestamps_key" apps/proxy/live_proxy/input/buffer.py` — the Lua reverse-scan and `find_chunk_index_by_time` (around `:459-514`); and its caller, `grep -n "find_chunk_index_by_time\|initial_behind" apps/proxy/live_proxy/output/ts/generator.py` (around `:263` and `:354-355`). Cite both sides |
| 9 | Data is realigned to 188-byte TS packet boundaries before a chunk is written; a partial trailing packet is carried into the next chunk | `owed: 2a-3` | `grep -n "TS_PACKET_SIZE\|complete_packets_size" apps/proxy/live_proxy/input/buffer.py` — the `add_chunk` arithmetic (around `:82`). Cite the alignment lines, and `apps/proxy/live_proxy/constants.py`'s `TS_PACKET_SIZE` (`grep -n "TS_PACKET_SIZE" apps/proxy/live_proxy/constants.py`) |

**Do not copy the parenthesised line numbers above into the matrix.** They say where the construct
was at `a948cd8a` so you know you have found the right one; the citation you write is the range you
actually read.

- [ ] **Step 6: Run the test to verify the nine new rows resolve.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 2 tests. A failure here names the row and the citation; fix the citation, not the
guard.

The `owed:` markers are **not** checked yet — that arrives in Tasks 4 and 5. A typo in one passes
silently until then; Task 5 catches it.

- [ ] **Step 7: Typecheck, run the whole guards project, and commit.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
```

Expected: silent; all green.

Message to `<SCRATCH>/msg-task3.txt`:

```
docs(phase2): the failover, buffer and alignment rows, with resolving citations

Rows 1-9 of the parity matrix: the three failover triggers, the cumulative
speed= average and its arming delay, threshold snapshotting, the unbounded
buffering-triggered switch, the monotonic chunk index, the ~5s-behind join
and 188-byte realignment.

The guard now resolves every citation against the tree — file present, range
inside it. It cannot prove a range is the right code; it makes a stale or
absent one loud, which is the half that rots without enforcement.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git add docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts e2e/tests/guards/parity-matrix.spec.ts
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git commit -F <SCRATCH>/msg-task3.txt
```

---

### Task 4: Pins resolve, and rows 10, 12–18

**Files:**
- Modify: `e2e/tests/guards/parity-matrix.ts` (append)
- Modify: `e2e/tests/guards/parity-matrix.spec.ts` (append one test)
- Modify: `docs/relay-parity-matrix.md` (eight rows)

**Interfaces:**
- Consumes: everything Tasks 2 and 3 produced.
- Produces: `type Pin = { kind: 'test'; file: string; symbol: string } | { kind: 'owed'; pr: string }
  | { kind: 'white-box-only' }`, `parsePin(cell: string): Pin | undefined`,
  `testRefProblem(pin: Extract<Pin, { kind: 'test' }>): Promise<string | undefined>`.

- [ ] **Step 1: Write the failing test.**

Append to `e2e/tests/guards/parity-matrix.spec.ts`, and extend the import to
`{ citationProblem, citationsIn, MATRIX_REL, parseMatrix, parsePin, readMatrix, testRefProblem }`:

```ts
test('every pin resolves', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());
  const findings: string[] = [];

  for (const row of rows) {
    const pin = parsePin(row.pin);
    if (pin === undefined) {
      findings.push(
        `${MATRIX_REL}:${row.line} (row ${row.id}) — Pin cell ${JSON.stringify(row.pin)} is ` +
          'none of the three legal forms: a backticked `path::symbol` test reference, ' +
          '"owed: <pr>" naming the PR that owes a test, or "white-box-only".',
      );
      continue;
    }
    if (pin.kind !== 'test') continue;
    const problem = await testRefProblem(pin);
    if (problem !== undefined) {
      findings.push(`${MATRIX_REL}:${row.line} (row ${row.id}) — ${problem}`);
    }
  }

  expect(
    findings,
    'A pin that does not resolve is a row claiming cover it does not have — the one failure ' +
      'mode this matrix exists to prevent.\n' + findings.join('\n'),
  ).toEqual([]);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL — `parsePin` and `testRefProblem` are not exported from `./parity-matrix`.

- [ ] **Step 3: Implement the pin resolver.**

Append to `e2e/tests/guards/parity-matrix.ts`. Extend that file's imports to
`import * as ts from 'typescript';` and `import { findTestCalls, REPO_ROOT } from './ast';`:

```ts
export type Pin =
  | { kind: 'test'; file: string; symbol: string }
  | { kind: 'owed'; pr: string }
  | { kind: 'white-box-only' };

/** `owed: 2a-4`. The PR id vocabulary is the four Phase 2 stages. */
const OWED_RE = /^owed: (2[a-d]-\d{1,2})$/;

/**
 * `` `path::symbol` ``. The path is a non-space run up to the first `::`; the
 * symbol is everything after it, spaces included, because a Playwright title
 * is a sentence. A Python reference may carry a class
 * (`path::TestFoo::test_bar`); `symbolOf` takes the last segment.
 */
const TEST_REF_RE = /^`([^\s`]+?)::(.+)`$/;

export function parsePin(cell: string): Pin | undefined {
  // Enclosing backticks are optional on the two bare forms and required on the
  // test reference, so both `owed: 2a-4` and owed: 2a-4 parse. Found while
  // prototyping this guard: the format section writes these tokens as inline
  // code, and a Markdown author's hand backticks them in the table too. A
  // format that fails on the more natural of two spellings is a format people
  // get wrong, so it accepts both rather than policing punctuation.
  const bare = cell.replace(/^`(.*)`$/, '$1').trim();
  if (bare === 'white-box-only') return { kind: 'white-box-only' };

  const owed = OWED_RE.exec(bare);
  if (owed !== null) return { kind: 'owed', pr: owed[1] };

  const ref = TEST_REF_RE.exec(cell);
  if (ref !== null) return { kind: 'test', file: ref[1], symbol: ref[2] };

  return undefined;
}

function symbolOf(pin: Extract<Pin, { kind: 'test' }>): string {
  const parts = pin.symbol.split('::');
  return parts[parts.length - 1];
}

function escapeRe(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * A spec file's *literal* test titles, read with the compiler API.
 *
 * Parsed, not grepped, for `ast.ts`'s reason: a title quoted in a comment is
 * trivia to the parser and a match to a text scan, and a guard that accepts a
 * title from a comment accepts a row pinned by a test that does not exist. A
 * parameterised title built from a template is not a literal and so cannot be
 * cited; inline the title, or cite a different test.
 */
function literalTitles(src: string, rel: string): string[] {
  const titles: string[] = [];
  for (const call of findTestCalls(src, rel)) {
    const first = call.args[0];
    if (first !== undefined && ts.isStringLiteralLike(first)) titles.push(first.text);
  }
  return titles;
}

/** A human-readable reason, or `undefined` when the pin resolves. */
export async function testRefProblem(
  pin: Extract<Pin, { kind: 'test' }>,
): Promise<string | undefined> {
  let src: string;
  try {
    src = await readFile(path.join(REPO_ROOT, pin.file), 'utf8');
  } catch {
    return `pin names no such file: ${pin.file}`;
  }

  const symbol = symbolOf(pin);

  if (pin.file.endsWith('.spec.ts')) {
    const titles = literalTitles(src, pin.file);
    if (titles.includes(symbol)) return undefined;
    return (
      `${pin.file} declares no test titled ${JSON.stringify(symbol)}. Literal titles found: ` +
      (titles.length === 0 ? '(none)' : titles.map((t) => JSON.stringify(t)).join(', '))
    );
  }

  if (pin.file.endsWith('.py')) {
    return new RegExp(String.raw`^[ \t]*def\s+${escapeRe(symbol)}\s*\(`, 'm').test(src)
      ? undefined
      : `${pin.file} has no "def ${symbol}("`;
  }

  if (pin.file.endsWith('.go')) {
    return new RegExp(String.raw`^func\s+(?:\([^)]*\)\s*)?${escapeRe(symbol)}\s*\(`, 'm').test(src)
      ? undefined
      : `${pin.file} has no "func ${symbol}("`;
  }

  // Fails closed, in `ast.ts`'s discipline: a shape this guard cannot read is
  // a failure, never a pass. 2c-9 re-points this matrix at Go tests, which is
  // why `.go` is already here.
  return (
    `${pin.file} has an extension this guard cannot verify. It reads .spec.ts (literal test ` +
    'titles), .py (def) and .go (func); anything else must be added to testRefProblem first.'
  );
}
```

- [ ] **Step 4: Run the test to verify it passes on the twelve existing rows.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 3 tests. Row 11's title reference resolves through `findTestCalls`; rows 1–9's
`owed:` markers parse; row 27's `white-box-only` parses.

- [ ] **Step 5: Locate and add rows 10, 12–18.**

Rows 10 and 11 are pinned by tests that already exist. Rows 12–18 are owed. Insert each in ascending
id order.

| # | Behaviour to write | Pin | How to find the Source |
|---|---|---|---|
| 10 | Multi-client upstream sharing: three clients on one channel share exactly one upstream connection, and closing every client releases it | `` `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection` `` | `grep -n "def add_client\|_registered_clients" apps/proxy/live_proxy/client_manager.py` — `add_client` and its duplicate guard (around `:215-245`); and the owner election in `grep -n "def.*owner\|nx=True" apps/proxy/live_proxy/server.py` (around `:505-530`). Cite both. Verify the title with `grep -n "three clients share exactly one upstream connection" e2e/tests/streaming/shared-upstream.spec.ts` |
| 12 | The fMP4 generator's `_is_timeout()` lacks the TS generator's `url_switching` exemption, so an fMP4 viewer can be dropped mid-failover while a TS viewer on the same channel is not | `owed: 2a-4` | `grep -n "_is_timeout" apps/proxy/live_proxy/output/fmp4/generator.py` (around `:339`) and `grep -n "_is_timeout\|url_switching" apps/proxy/live_proxy/output/ts/generator.py` (around `:574-590`). Cite both, because the row is the *difference* between them. **Filed as an issue and reproduced, not fixed** (spec D5) — say so in Notes |
| 13 | Client registration is idempotent per client id, and a client whose heartbeat stops for `GHOST_CLIENT_MULTIPLIER` × the heartbeat interval is removed as a ghost | `owed: 2a-3` | `grep -n "ghost\|GHOST_CLIENT_MULTIPLIER\|def remove_ghost_clients" apps/proxy/live_proxy/client_manager.py` — the sweep (around `:110-130`) and `remove_ghost_clients` (around `:434-470`). Cite both. Notes: extends the existing `apps/channels/tests/test_ts_proxy_ghost_clients.py`, which is the partial cover the spec records |
| 14 | *(already written in Task 2)* | `owed: 2a-5` | — |
| 15 | `stream_xc` authorizes once and passes its `decision` into `stream_ts`, so an XC tune is not authorized twice and does not mint a second client id for one connection | `owed: 2a-5` | `grep -n "decision=decision\|def stream_ts\|def stream_xc" apps/proxy/live_proxy/views.py` — the `if decision is None:` guard and its comment inside `stream_ts` (spec cites `:161-165`; at `a948cd8a` the comment is at `:162-166` — **verify and cite what you read**), the `resolve_authorization` call inside `stream_xc` (spec cites `:825`; verified correct at `a948cd8a`), and the `stream_ts(...)` hand-off (around `:845-851`). Cite all three |
| 16 | `/proxy/ts/stream/<stream_hash>` — the admin single-stream preview, with no channel at all — applies the STREAMS ACL and the per-user stream limit when a principal resolved, and no channel check of any kind, because there is no channel to check | `owed: 2a-5` | `apps/proxy/next_source.py:69-79`, `get_stream_object`'s `Stream.stream_hash` fallback — the spec's citation, verified exact at `a948cd8a`. Confirm with `sed -n '69,79p' apps/proxy/next_source.py` and cite it. Add the authorize side: `grep -n "stream_hash\|SURFACE_LIVE" apps/proxy/authorize.py` |
| 17 | `ip_address` on both status endpoints is the real client address, derived from `X-Relay-Client-IP` as set by whichever authorize response the relay trusted, never from `REMOTE_ADDR` or `X-Forwarded-For` read at the relay | `owed: 2a-5` | The spec's citations, all verified at `a948cd8a`: `dispatcharr/utils.py:342-370` (`get_client_ip`), `apps/proxy/live_proxy/client_manager.py:215-230` (`add_client`'s `ip_address`), `apps/proxy/relay_serializers.py:29`, `apps/proxy/relay_serializers.py:79`. Confirm each with `sed -n` before copying |
| 18 | What the status payload's `stream_name` and `m3u_profile_name` contain when the channel metadata hash was never written one | `owed: 2b-3` | `apps/proxy/live_proxy/channel_status.py:74` and `:92` — the two ORM name fallbacks, both verified at `a948cd8a` (`sed -n '70,95p' apps/proxy/live_proxy/channel_status.py`). Notes: **phrased as a question 2b-3 must answer**, not an assumed "always present"; whatever 2b-3 concludes when it deletes these reads is the answer 2c is then held to |

Row 14 already exists from Task 2 — leave it where it is; the table row above is a placeholder so
the numbering reads continuously.

- [ ] **Step 6: Run the tests to verify the new rows resolve.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 3 tests. Row 10's title is resolved through the compiler API, so a typo in it fails
here and names the literal titles the file does declare.

- [ ] **Step 7: Typecheck, run the whole guards project, and commit.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
```

Message to `<SCRATCH>/msg-task4.txt`:

```
docs(phase2): the client, status and authorization-shape rows, with resolving pins

Rows 10 and 12-18: multi-client upstream sharing, fMP4's missing
url_switching exemption, ghost clients, the stream_xc decision hand-off, the
stream-by-hash authorization shape, ip_address provenance, and the
stream_name question 2b-3 has to answer.

A pin now has exactly three legal forms and each is resolved: a test
reference against the real symbol (.spec.ts titles through the compiler API,
so a title in a comment is not a match), an owed: marker, or white-box-only.
An extension the guard cannot read fails rather than passes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git add docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts e2e/tests/guards/parity-matrix.spec.ts
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git commit -F <SCRATCH>/msg-task4.txt
```

---

### Task 5: The two pinned lists, and rows 19–27

**Files:**
- Modify: `e2e/tests/guards/parity-matrix.ts` (append the two lists)
- Modify: `e2e/tests/guards/parity-matrix.spec.ts` (append two tests, raise the self-check)
- Modify: `docs/relay-parity-matrix.md` (nine rows)

**Interfaces:**
- Consumes: everything Tasks 2–4 produced.
- Produces: `type WhiteBoxRow = { id: number; why: string }`,
  `WHITE_BOX_ONLY: readonly WhiteBoxRow[]`, `OWED: readonly number[]`. **These two constants are
  what 2a-3 … 2a-6, 2b-3 and every 2c PR edit.** Their names and shapes are fixed here.

- [ ] **Step 1: Add rows 19–26.**

Row 27 already exists from Task 2. Rows 19–25 are one per principal in the Phase 1 authorize matrix
(`docs/superpowers/specs/2026-09-04-phase1-process-split-design.md:705-713` — the spec is present in
this worktree; read the table before writing the rows). **The matrix cites those tests, it does not
re-test them** — the pin for each is a test in `e2e/tests/streaming/authorize-matrix.spec.ts`, which
PR 5 shipped as `@contract`.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
sed -n '692,721p' docs/superpowers/specs/2026-09-04-phase1-process-split-design.md
grep -n "^test(" -A 3 e2e/tests/streaming/authorize-matrix.spec.ts
```

The second command prints each declaration's literal title; **use those titles verbatim** as the
pins. Map one principal to the test that covers it. If a principal has no test in that file, search
the rest of `e2e/tests/streaming/` for it before concluding it is unpinned:

```bash
grep -rn "^test(" -A 3 e2e/tests/streaming/*.spec.ts | grep -v authorize-matrix
```

If, after that search, a principal genuinely has no test, mark it `owed: 2a-5` and add its id to
`OWED` in step 3 — **do not** invent a title, and do not mark it `white-box-only`: an authorization
outcome is observable at a client-facing surface by definition, so `white-box-only` would be false.

| # | Behaviour to write | Pin |
|---|---|---|
| 19 | Authorize matrix — **Internal** principal (DVR, any caller with a valid `X-Dispatcharr-Internal`): the STREAMS ACL applies; `user_level`, profile membership, `hidden_from_output`, adult filtering and the stream limit are all bypassed | the matching literal title from `e2e/tests/streaming/authorize-matrix.spec.ts` |
| 20 | Authorize matrix — **Admin** (`user_level >= 10`, any authenticator): ACL applies, every channel check bypassed, the stream limit still enforced | as above |
| 21 | Authorize matrix — **XC credentials** (`<user>/<pass>` path segments, compared with `hmac.compare_digest`): every check enforced; `hidden_from_output` and adult filtering answer 403 | as above |
| 22 | Authorize matrix — **JWT / API key / query-param JWT**, non-admin: every check enforced | as above |
| 23 | Authorize matrix — **Session**, non-admin: every check enforced | as above |
| 24 | Authorize matrix — **Anonymous** (a bare channel UUID): the ACL applies, `hidden_from_output` answers 403, and every user-scoped check is inapplicable — an anonymous request with a valid UUID still streams an ordinary channel | as above |
| 25 | Authorize matrix — **Stream-by-hash** (`/proxy/ts/stream/<stream_hash>`), any principal: the ACL applies and the stream limit is enforced when a principal resolved; no channel check applies | as above; if none exists, `owed: 2a-5` (see row 16, the same shape from the other side) |
| 26 | Not held to: the greenlet and OS-thread topology inside `server.py` — three `threading.Thread(daemon=True)` supervisors sharing one OS thread with the request greenlets, and `_spawn_on_hub`'s cross-thread scheduling onto the gevent hub | `white-box-only` |

Row 26's Source: `apps/proxy/live_proxy/server.py:161-172` (`_spawn_on_hub`, verified) plus the
`threading.Thread(...)` sites — `grep -n "threading.Thread" apps/proxy/live_proxy/server.py` (three
at `a948cd8a`: `:467`, `:851`, `:2192`). Cite `_spawn_on_hub`'s span and at least one thread site.
Notes: deleted, not ported — the Go relay's concurrency model is goroutines and a `sync.RWMutex`
(spec D2), and no client can observe which greenlet did what.

- [ ] **Step 2: Write the two failing tests.**

Append to `e2e/tests/guards/parity-matrix.spec.ts`, extending the import to add
`{ OWED, WHITE_BOX_ONLY }`:

```ts
test('white-box-only rows are confined to an allowlist', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());

  const marked = rows.filter((row) => parsePin(row.pin)?.kind === 'white-box-only');
  const actual = marked.map((row) => row.id).sort((a, b) => a - b);
  const allowed = WHITE_BOX_ONLY.map((row) => row.id).sort((a, b) => a - b);

  // `toEqual`, not `toContain`: un-marking a row must also be a deliberate
  // edit, or the list rots in the other direction — capabilities.spec.ts's
  // own argument, applied to the one marker that can make an inconvenient row
  // stop counting.
  expect(
    actual,
    'A row marked white-box-only is behaviour the Go relay is NOT held to, so marking one is a ' +
      'deliberate edit in two places: the matrix, and WHITE_BOX_ONLY in ' +
      'e2e/tests/guards/parity-matrix.ts, where it must carry a `why`. Say in the diff why no ' +
      'client can observe it.',
  ).toEqual(allowed);

  const unjustified = marked
    .filter((row) => row.notes === '')
    .map((row) => `${MATRIX_REL}:${row.line} (row ${row.id})`);
  expect(
    unjustified,
    'A white-box-only row must justify itself in its Notes cell, not only in the guard. See ' +
      'docs/adr/0002-e2e-test-taxonomy.md on why an unobservable pin needs a stated reason.',
  ).toEqual([]);
});

test('unpinned rows are exactly the ones still owed', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());

  // Guards the guard: a parser that silently found nothing would pass every
  // assertion here while enforcing nothing. Deliberately well below the row
  // count so retiring a row is not a guard failure.
  expect(
    rows.length,
    `Found ${rows.length} rows in ${MATRIX_REL}, expected more than 20. That is this guard ` +
      'being broken, not the matrix being short — check parseMatrix and MATRIX_HEADER.',
  ).toBeGreaterThan(20);

  const unpinned = rows.filter((row) => parsePin(row.pin)?.kind === 'owed');
  const actual = unpinned.map((row) => row.id).sort((a, b) => a - b);

  expect(
    actual,
    'The set of unpinned rows is a ratchet. Closing one is a two-line diff: change the Pin cell ' +
      'to a test reference, and delete the id from OWED in ' +
      'e2e/tests/guards/parity-matrix.ts. Opening one is the same edit in reverse, and cannot ' +
      'happen silently. Gate 1 is met when OWED is empty.',
  ).toEqual([...OWED].sort((a, b) => a - b));
});
```

- [ ] **Step 3: Run them to verify they fail.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL — `WHITE_BOX_ONLY` and `OWED` are not exported from `./parity-matrix`.

- [ ] **Step 4: Add the two lists.**

Append to `e2e/tests/guards/parity-matrix.ts`. **The `OWED` ids below are the ones this plan
expects; use the ones your table actually carries** — if step 1 left row 25 owed, it belongs here
too.

```ts
export type WhiteBoxRow = { id: number; why: string };

/**
 * Rows no test can pin, because no client can observe them.
 *
 * Compared with `toEqual`, in `allowlist.ts`'s idiom and for its reason: this
 * marker is the one word that can make an inconvenient row stop counting, so
 * both adding and removing one must be a deliberate edit with a stated
 * reason. Both entries here are deleted outright by the spec's D2 rather than
 * reproduced in Go — that is what makes them honest to record rather than
 * convenient to hide.
 */
export const WHITE_BOX_ONLY: readonly WhiteBoxRow[] = [
  {
    id: 26,
    why:
      "server.py's greenlet and OS-thread topology. The Go relay's concurrency model is " +
      'goroutines behind a sync.RWMutex (spec D2); no client can observe which greenlet did ' +
      'what, and the threads themselves are deleted, not ported.',
  },
  {
    id: 27,
    why:
      '_execute_redis_command swallowing every Redis exception to None. D2 removes Redis from ' +
      'the live path entirely, so the Go relay has no analogous call to swallow anything.',
  },
];

/**
 * Rows whose test a later PR owes. **This list only shrinks.**
 *
 * The Pin cell says which PR owes each one; this list is what stops "no test
 * yet" from being a permanently green answer. Gate 1 — the spec's own
 * definition of "the behaviour is pinned" — is met when this is `[]`.
 *
 * Assignments, from the spec's 2a PR table, plus this plan's ruling 7 for the
 * four rows it assigns to no PR at all:
 *   2a-3: 7, 8, 9, 13     2a-4: 1, 2, 3, 4, 5, 6, 12
 *   2a-5: 14, 15, 16, 17  2b-3: 18
 */
export const OWED: readonly number[] = [
  1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18,
];
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 5 tests.

A mismatch on `OWED` prints both sets — reconcile by fixing whichever is wrong. A row whose `owed:`
marker was mistyped in Task 3 surfaces here as an id present in `OWED` but absent from the matrix's
owed set, or vice versa; that is the check catching the typo, as designed.

- [ ] **Step 6: Confirm the matrix is complete.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
grep -c '^| [0-9]' docs/relay-parity-matrix.md
grep -o '^| [0-9]*' docs/relay-parity-matrix.md | tr -d '| ' | sort -n | tr '\n' ' '
```

Expected: `27`, and `1 2 3 … 27` with no gaps and no repeats. A gap means a row was missed; a repeat
means the first test would have caught it, so a repeat here means the table was edited after the
last run — re-run step 5.

- [ ] **Step 7: Typecheck, run the whole guards project, and commit.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
```

Expected: silent; all green, five more tests than Task 1 step 2 recorded.

Message to `<SCRATCH>/msg-task5.txt`:

```
docs(phase2): the authorize rows, the white-box allowlist and the owed ratchet

Rows 19-25 cite the seven authorize-matrix principals to the tests PR 5
already shipped; rows 26-27 record the two behaviours the Go relay is
deliberately not held to.

Both markers are allowlists compared with toEqual, not keywords: marking a
row white-box-only, and leaving one unpinned, each take a deliberate edit in
two places. That is what makes "no test yet" a ratchet rather than a
permanently green answer — Gate 1 is met when OWED is empty.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git add docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts e2e/tests/guards/parity-matrix.spec.ts
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git commit -F <SCRATCH>/msg-task5.txt
```

---

### Task 6: Prove each check by mutation

**Files:**
- Modify: `e2e/tests/guards/parity-matrix.spec.ts` (header comment only — no assertion changes)

**Interfaces:** none. Produces the five mutation results Task 7 writes into `e2e/COVERAGE.md`.

Every guard in this directory records in its own header that it was verified by mutation, and says
what the mutation was and what it printed. `capabilities.spec.ts` makes the argument: a guard that
has never been seen to fail is a guard nobody knows works. This task does that five times.

**Each mutation is made, run, and reverted before the next one.** `git diff` must be empty on
`docs/relay-parity-matrix.md` and `e2e/tests/guards/parity-matrix.ts` at the end of every mutation.

- [ ] **Step 1: Mutate the header. Expect check 1 to fail.**

Edit `docs/relay-parity-matrix.md`: change the table header's `Notes` to `Note`.

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: every check fails with `has no line equal to the matrix header`, printing the expected
header. **Record the message.**

Revert: restore `Notes`. Re-run; expected PASS, 5 tests. Confirm with
`git diff --stat docs/relay-parity-matrix.md` — empty.

- [ ] **Step 2: Mutate a citation. Expect check 2 to fail.**

Edit `docs/relay-parity-matrix.md`: in row 27's Source, change
`` `apps/proxy/live_proxy/server.py:138-159` `` to `` `apps/proxy/live_proxy/server.py:138-99999` ``.

Run the same command.
Expected: `every row cites source that resolves` fails, naming `row 27` and
`runs past the end of the file, which has <N> lines`. **Record the message and `<N>`.**

Revert and re-run; expected PASS, 5 tests.

- [ ] **Step 3: Mutate a test title. Expect check 3 to fail.**

Edit `docs/relay-parity-matrix.md`: in row 11's Pin, change
`::two clients on one output profile share a single transcode` to
`::two clients on one output profile share a single transcodes`.

Run the same command.
Expected: `every pin resolves` fails, naming `row 11` and printing the literal titles the file does
declare. **Record the message.**

Then make the second half of this check's argument, which is the one that justifies parsing over
grep: put the fake title in a **comment** in that spec file and leave the matrix mutated. Expected:
still FAIL — a title in a comment is not a declaration. **Record that it stayed red.**

Revert both; re-run; expected PASS, 5 tests.

- [ ] **Step 4: Mutate the white-box marker. Expect check 4 to fail.**

Edit `docs/relay-parity-matrix.md`: change row 12's Pin from `owed: 2a-4` to `white-box-only`.

Run the same command.
Expected: two failures — `white-box-only rows are confined to an allowlist` reporting `[12, 26, 27]`
against `[26, 27]`, and `unpinned rows are exactly the ones still owed` reporting `12` missing.
**Record both.** That both fire together is the point: the marker cannot be used to quietly drop a
row from the ratchet.

Revert and re-run; expected PASS, 5 tests.

- [ ] **Step 5: Close a row without telling the guard. Expect check 5 to fail.**

Edit `docs/relay-parity-matrix.md`: change row 13's Pin from `owed: 2a-3` to
`` `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection` ``
— a real, resolvable test, so checks 1–4 stay green — and leave `OWED` untouched.

Run the same command.
Expected: only `unpinned rows are exactly the ones still owed` fails, reporting `13` present in
`OWED` and absent from the matrix. **Record it.** This is the mutation that proves a row cannot be
declared closed by editing one file.

Revert and re-run; expected PASS, 5 tests.

- [ ] **Step 6: Record the five mutations in the header comment.**

Append to the block comment at the top of `e2e/tests/guards/parity-matrix.spec.ts`, immediately
before the closing `*/`, using **the messages you actually saw**, not the ones this plan predicts:

```
 * Verified by mutation, all five, each reverted before the next:
 *   1. Renaming the header's `Notes` column to `Note` failed every check with
 *      "has no line equal to the matrix header", printing the expected line.
 *   2. Widening row 27's citation to `server.py:138-99999` failed check 2
 *      naming row 27 and "<the message you saw>".
 *   3. Misspelling row 11's cited test title failed check 3, printing the
 *      literal titles that file does declare; adding the misspelling as a
 *      COMMENT in that spec kept it red, which is the whole argument for
 *      parsing over grep.
 *   4. Re-marking row 12 `white-box-only` failed checks 4 and 5 together —
 *      the marker cannot be used to drop a row out of the ratchet.
 *   5. Pinning row 13 to a real, resolvable test without deleting 13 from
 *      OWED failed check 5 alone: a row cannot be closed by editing one file.
```

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit`
Then: `npx playwright test --project=guards`
Expected: silent; all green.

- [ ] **Step 7: Confirm nothing but the comment changed, and commit.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git status --short && git diff --stat
```

Expected: only `e2e/tests/guards/parity-matrix.spec.ts` modified. **If `docs/relay-parity-matrix.md`
or `parity-matrix.ts` shows as modified, a mutation was not reverted** — revert it before
committing.

Message to `<SCRATCH>/msg-task6.txt`:

```
test(phase2): record the parity guard's five mutation verifications

Every guard in this directory records what it was seen to fail on, because a
guard nobody has watched fail is a guard nobody knows works. Five mutations,
each reverted: a renamed column, an out-of-range citation, a misspelled test
title (and the same misspelling in a comment, which stayed red), a
white-box-only marker used to drop a row from the ratchet, and a row closed
in the matrix without being closed in the guard.

Comment only; no assertion changed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git add e2e/tests/guards/parity-matrix.spec.ts
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git commit -F <SCRATCH>/msg-task6.txt
```

---

### Task 7: The documents this PR owes

**Files:**
- Modify: `e2e/COVERAGE.md`
- Modify: `e2e/README.md`
- Modify: `CLAUDE.md`

**Interfaces:** Consumes Task 6's five recorded mutation results.

- [ ] **Step 1: Add the Guards row to `e2e/COVERAGE.md`.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && grep -n "upstream-contract.spec.ts" e2e/COVERAGE.md
```

Expected: one hit, the last row of the Guards (G11) table. Add this row immediately after it, with
`<the message you saw>` replaced from Task 6:

```markdown
| `tests/guards/parity-matrix.spec.ts` | `docs/relay-parity-matrix.md` stays machine-readable: the table is found by its exact header, ids are unique and ascending, every `Source` citation resolves to a real file and a line inside it, every `Pin` is a resolvable test symbol / an `owed: <pr>` marker / `white-box-only`, and the white-box and owed sets are `toEqual` allowlists in `tests/guards/parity-matrix.ts`. Phase 2's Gate 1 | Renaming the `Notes` column failed every check; a citation widened past end-of-file failed naming the row; a misspelled cited test title failed, and stayed red with the misspelling added as a **comment**; a `white-box-only` marker used to drop a row failed the allowlist and the ratchet together; a row closed in the matrix but not in `OWED` failed the ratchet alone |
```

Verify the table still parses:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && grep -c "^| " e2e/COVERAGE.md
```

Expected: the previous count plus one. The added line begins with `| ` and ends with ` |`, and
contains no unescaped `|` inside a cell.

- [ ] **Step 2: Name the new guard in `e2e/README.md` § Projects.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && grep -n "Home for every enforcement spec" e2e/README.md
```

That enumeration currently ends `…the instance-wide settings-write allowlist and the `pageErrors`
check (which moved here from `tests/frontend/`)`. Extend it so the list names the new guard —
append, before the closing `|` of that table cell:

```
, the `e2e-upstream` contract-version check and the Phase 2 parity matrix's format
```

**Note the enumeration was already stale** (it omitted `upstream-contract.spec.ts`); this edit
corrects that at the same time. Say so in the task report.

- [ ] **Step 3: Name the matrix in `CLAUDE.md` § Repository and direction.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && grep -n "^- Phase 1 spec (process split" CLAUDE.md
```

That bullet — not the Phase 0 one — is the last entry in § Repository and direction's document list
at `a948cd8a`; it runs several lines and ends with the ADR 0005 sentence. Add one bullet **after its
final line**:

```markdown
- Relay parity matrix (Phase 2 Gate 1 — every externally-observable live-path behaviour, its `file:line` and what pins it) — `docs/relay-parity-matrix.md`
```

Nothing else in `CLAUDE.md` changes: this PR alters no fact the file states about the product.

- [ ] **Step 4: Confirm the diff is still documentation-only, and commit.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git status --short
```

Expected: exactly `CLAUDE.md`, `e2e/COVERAGE.md`, `e2e/README.md`.

Message to `<SCRATCH>/msg-task7.txt`:

```
docs(phase2): the parity matrix in COVERAGE, README and CLAUDE.md

COVERAGE.md's Guards table gets the new guard and the five mutations that
proved it. README's guards enumeration names it — and, while there, the
e2e-upstream contract check it had already been missing. CLAUDE.md lists the
matrix beside the specs, because every later Phase 2 PR cites it and a
document nobody can find is not load-bearing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git add CLAUDE.md e2e/COVERAGE.md e2e/README.md
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git commit -F <SCRATCH>/msg-task7.txt
```

---

### Task 8: Full verification and the pull request

**Files:** none edited.

**Interfaces:** Consumes the whole branch.

- [ ] **Step 1: Typecheck and run the whole guards project one more time, from a clean tree.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git status --short
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
```

Expected: clean tree; `tsc` silent; every guard green, **exactly five more passing tests than Task 1
step 2 recorded**. A different delta means a test was added or lost somewhere unintended — find out
which before continuing.

- [ ] **Step 2: Prove the diff touched no product code.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git diff --name-only main...HEAD
```

Expected, exactly:

```
CLAUDE.md
docs/relay-parity-matrix.md
docs/superpowers/plans/2026-09-09-phase2-2a1-parity-matrix.md
e2e/COVERAGE.md
e2e/README.md
e2e/tests/guards/parity-matrix.spec.ts
e2e/tests/guards/parity-matrix.ts
```

**Nothing under `apps/`, `core/`, `dispatcharr/`, `frontend/`, `docker/`, `scripts/`, `metrics/` or
`.github/`.** If any of those appears, that file does not belong in this PR.

- [ ] **Step 3: Run the commit gate once against the full branch.**

```bash
CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 \
  /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/.claude/hooks/pre-commit-tests.sh --git-hook
```

Expected: nothing staged, so nothing to run — the gate's correct answer for a diff with no backend
or frontend paths. Record that it ran and said so.

- [ ] **Step 4: Push and open the pull request.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git push -u origin migration/phase2a-parity-matrix
```

Write the PR body with the Write tool to `<SCRATCH>/pr-body.md`:

```markdown
Phase 2 PR 2a-1. Gate 1's artefact: a matrix naming every externally-observable
live-path behaviour, and the guard that keeps it honest.

**`docs/relay-parity-matrix.md`** — 27 rows. 1-18 as the spec's Gate 1 table
enumerates them (the three failover triggers, `speed=`'s cumulative average and
its arming delay, threshold snapshotting, the unbounded buffering-triggered
switch, the monotonic chunk index, the ~5s-behind join, 188-byte realignment,
multi-client and Output Profile sharing, fMP4's missing `url_switching`
exemption, ghost clients, the status payload's per-endpoint field types, the
`stream_xc` decision hand-off, the stream-by-hash authorization shape,
`ip_address` provenance, and the `stream_name` question 2b-3 has to answer);
19-25 one per Phase 1 authorize-matrix principal, citing the tests PR 5 already
shipped; 26-27 the two behaviours the Go relay is deliberately not held to.

**`e2e/tests/guards/parity-matrix.spec.ts`** — five checks in the `guards`
project, which needs no container. The table parses; every citation resolves to
a real file and a line inside it; every pin is a resolvable test symbol
(`.spec.ts` titles read through the TypeScript compiler API, so a title in a
comment is not a match), an `owed: <pr>` marker, or `white-box-only`. The last
two are `toEqual` allowlists, not keywords — closing a row and marking one
unobservable are each deliberate edits in two files. Gate 1 is met when `OWED`
is empty.

Verified by mutation, five times, each reverted; the spec file's header records
what each one printed.

Two things the spec gets wrong, followed the code instead and reported rather
than silently diverged:

- Gate 1's table enumerates rows 1-18 plus a collapsed `19-26`, then calls the
  result "24 rows". `19-26` is eight ids for the seven principals the Phase 1
  authorize matrix actually has, and 18 + 7 = 25. Expanded to one row per
  principal: 25, plus the two white-box rows the prose names but the table
  omits, = 27.
- Rows 14-17 are assigned to no 2a PR by the spec. They are view-level rows
  needing no subprocess harness, so this PR marks them `owed: 2a-5` — which
  widens 2a-5's scope by four rows. The 2a-5 plan has to pick them up.

No product code. No new dependency. No workflow or metrics change — the spec
puts this phase's `metrics/curated/` work in `migration/phase2d-docs`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && gh pr create --repo D10Scot/Dispatcharr --base main --head migration/phase2a-parity-matrix --title "docs(phase2): the relay parity matrix and its guard (Phase 2 PR 2a-1)" --body-file <SCRATCH>/pr-body.md
```

- [ ] **Step 5: Watch the required checks.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && gh pr checks --repo D10Scot/Dispatcharr --watch
```

The branch is `migration/**`, so `e2e-tests.yml` and `lifecycle-tests.yml` run in **full mode** —
every Playwright project including `lifecycle-upgrade`, plus both bash suites. This is slow and this
PR touches none of those surfaces; it is the price of the branch name and is expected.

Required: `E2E result`, `Lifecycle result`, `Backend result`, `Frontend result`, plus `pr-review`'s
`agent` and `safe_outputs`. **`Backend result` and `Frontend result` pass by their not-required
branch** — the change detector sees no backend or frontend path — which is the designed behaviour,
not a skipped check to worry about.

If `E2E result` is red, read which project failed. A `guards` failure is this PR's. Any other
project failing on a documentation-and-guards diff is a pre-existing flake or an unrelated break —
say which in the report rather than editing this PR to chase it.

---

## Self-review notes

Recorded so a reviewer can check the plan against the spec without re-deriving it.

**Spec coverage.** § Stage 2a › Gate 1 asks for three things: the matrix document with its rows
(Tasks 2–5), the `file:line` and test-reference columns (rulings 2 and 3, enforced by Tasks 3 and 4),
and the guard under `e2e/tests/guards/` following `allowlist.ts`/`capabilities.spec.ts`'s pattern
(rulings 4, 5 and 10; Tasks 2–6). The 2a PR table's row for 2a-1 asks for those two artefacts and
sets the gate at "guard test green" (Done criteria, Task 8 step 1). § Documentation asks for
`docs/relay-parity-matrix.md` created on this branch (Task 2), `e2e/COVERAGE.md` updated in the same
PR as the test (Task 7 step 1), and puts `metrics/curated/` in `migration/phase2d-docs` (ruling 9,
verified by Task 8 step 2). The spec's white-box paragraph is ruling 4 and rows 26–27.

**Not covered here, deliberately:** Gate 2 (coverage) is 2a-2 and 2a-7; the subprocess harness is
2a-2; every `New` test the matrix's rows call for is 2a-3 … 2a-6 and 2b-3 — this PR records that
they are owed, which is its whole job.

**Known divergences from the spec, both reported in the PR body:** the row count (ruling 6) and the
2a-5 assignment (ruling 7).

**The guard's code in this plan was prototyped and run before the plan was finished**, in a
throwaway copy under `e2e/tests/guards/` that was deleted afterwards, against a three-row matrix
holding exactly the example rows in Task 2 step 5. What that run established, so the executor knows
which parts are already known-good and which are still their own to prove:

- `npx tsc --noEmit` is clean on the module as written, under the package's `strict: true`.
- All three example rows parse; every citation in them resolves; row 11's `.spec.ts` title resolves
  through `findTestCalls`; a `.py` symbol (`get_basic_channel_info` in `channel_status.py`) resolves
  through the `def` regex.
- Five negative controls fire: a missing file (`no such file`), an out-of-range end
  (`runs past the end`), a misspelled test title (`declares no test titled`, listing the file's real
  titles), an out-of-vocabulary PR id (`owed: 9z-1` → unparseable), and an empty Pin cell
  (unparseable).
- **One design bug was found this way and is fixed in the plan**: `parsePin` originally required the
  two bare forms to be unbackticked, and a Markdown author's hand backticks them. See ruling 3.

Task 6's mutation work is still owed in full — the prototype proved the checks *can* fire on
synthetic input; Task 6 proves they fire on the real document, and its recorded messages are what
`e2e/COVERAGE.md` cites.
