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
  All seven tests in this PR carry `{ tag: '@characterization' }` (§ Design ruling 8).
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

### 1. The matrix is one GFM table with a fixed five-column header, and the guard finds it by column names

The document may carry any amount of prose. The table starts at the first line whose cells, split on
`|` and trimmed, are exactly `#`, `Behaviour`, `Source`, `Pin`, `Notes`; the table is the run of
`|`-leading lines after that line and its delimiter row. The guard throws — naming the file and the
canonical header — if no such line exists, if the delimiter row is missing, or if a row does not
split into exactly five cells.

**Matching on trimmed cell names, not on the header line character for character**, is deliberate
and is ruling 11's requirement: a parser that dies on `| #   | Behaviour |` reports "no matrix
header", which tells an author nothing about the padding that actually caused it. The parser is
tolerant; a *named* test (ruling 11) rejects padding and says why. That split — parse loosely, assert
precisely — is what makes the failure message useful.

Why not a Markdown parser: none is available without adding a dependency (a Global Constraint
forbids one), and a hand-rolled loose parser that guesses at structure is the thing that silently
accepts a malformed row. This one guesses at nothing — five named columns or it throws.

**A cell may not contain a literal `|`.** The five-cell requirement enforces this by construction —
a stray pipe splits the row into six cells and fails, naming the line. This is stated in the
document's own § Format so an author is told before the guard tells them.

### 2. Five columns: `#`, `Behaviour`, `Source`, `Pin`, `Notes`

- **`#`** — a decimal integer, unique across the table. Row ids are the phase's addressing scheme
  (2c PRs "close rows 7–10, 13"), so they must be stable: **an id is never reused and never
  renumbered.** **A row is never removed from the table**: one that stops applying is retired *in
  place*, keeping its id and saying so in its Notes, because 2c and 2d address rows by number and a
  row that vanishes takes its obligation with it. That makes the id set exactly `1..N`, which the
  guard asserts (ruling 12). **Ids are not in ascending file order and must not be sorted into it**
  — file order groups rows by the PR that owes them (ruling 11), and re-sorting the table by id
  destroys that property. A new row takes the next free id and is appended to the end of its owning
  PR's block.
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
| One or more real tests | `` `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection` `` — or two such references separated by `, ` | Every reference resolves: the file exists **and** declares that symbol. For `.spec.ts`, the title must be a *literal* title found by `findTestCalls` (`tests/guards/ast.ts`) — so a title in a comment does not count. For `.py`, a line matching `^[ \t]*def <name>(`. For `.go`, a line matching `^func [(recv) ]<Name>(`. Any other extension fails: the guard fails closed on a shape it cannot read |
| A row a later PR owes | `owed: 2a-4` | Matches `^owed: (\S+)$` and the PR id is one of the guard's `PRS` vocabulary |
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

**A test pin is a list, like `Source`, not a single reference.** The first draft of this plan allowed
exactly one, and its own rows contradict that: row 10 asserts two things ("three clients share one
upstream" **and** "closing every client releases it"), row 12 *is* the difference between the fMP4
and TS generators, row 14 spans two endpoints whose answers differ, rows 16 and 17 each have an
authorize side and a payload side, and rows 19–25 each stand for a principal against six check
columns (ruling 6). With one pin per row the first executor who needs two tests either splits a row
— renumbering pressure, which ruling 2 forbids — or writes a cell that fails with a message naming
the wrong problem (verified: `` `a.spec.ts::t` and `b.spec.ts::u` `` parsed as one reference with the
symbol `` t` and `b.spec.ts::u ``). So `Pin` matches every backticked `path::symbol` in the cell and
requires at least one, and every one of them must resolve.

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

### 5. `owed:` is derived from the row itself. There is no `OWED` list

At 2a-1 twenty of the twenty-seven rows have no test — that is what the later PRs exist to fix. A
guard that simply accepted "no test yet" would be green forever and gate nothing, so an unpinned row
must say **which PR owes it**, in its own `Pin` cell.

**And that is the whole mechanism. A row is owed if and only if its `Pin` cell reads `owed: <pr>`.**
There is no second list to keep in step.

The first draft of this plan carried one — `export const OWED: readonly number[]` in
`parity-matrix.ts` — and specified closing a row as "a two-line diff: change the Pin cell, delete the
id from `OWED`". **That defeated ruling 11 at the second file.** Ruling 11 spends sixty lines making
the matrix conflict-free for its concurrent editors and then put every id those seven PRs delete on
*one shared line of the other file they all edit*: 2a-3 deleting `7, 8, 9, 13` and 2a-4 deleting
`1, 2, 3, 4, 5, 6` are edits to the same line, a guaranteed conflict on every pair, every time.
Deriving owed-ness from the table makes closing a row **one line in one file**, which is what ruling
11 was for.

**What is lost — both of them, stated plainly.**

1. **Re-pinning a row to a real but irrelevant test is now green.** Pointing row 13 at
   `shared-upstream.spec.ts` used to fail, because the id stayed in `OWED`.
2. **Un-pinning a row *inside its own block* is now silent.** Reverting a pinned row to
   `owed: 2a-4` is caught by the contiguity check only when the row sits in the *pinned* block, where
   it splits a run. Inside its owning block it is indistinguishable from a row that was never pinned.

The trade is still worth taking, and the reason is the same for both: **the guard never judged pin
*relevance*, and it never could.**

**Relevance is not checkable here, and this plan says so rather than implying a rigour that is not
there.** Three approaches were considered and rejected:

- **Lexical affinity between the pin's file and the cited source** fails on this matrix's own correct
  rows. Row 11 cites `output/profile/manager.py` and pins `output-profile-sharing.spec.ts` — an
  overlap. Row 10 cites `client_manager.py` and `server.py` and pins `shared-upstream.spec.ts` — none
  at all, and it is correct. A check that fires on a correct row gets loosened until it catches
  nothing, which is the failure `ast.ts`'s own header warns about.
- **"Does the pinned test execute the cited lines"** is the check one would actually want, and it is
  a coverage run. For a Playwright pin that means the e2e suite under Python coverage inside the AIO
  container — which destroys the `guards` project's defining property (no container, one second,
  its own CI job) and turns it into a 45-minute one. It would be feasible for the Python pins alone,
  and a guard that verifies half the matrix is worse than one that verifies none: it implies the
  other half was checked.
- **A cap on how many rows may cite one test symbol** is cheap and catches *repeated* lazy pinning,
  but a single lazy pin passes, and legitimate reuse (rows 21 and 24 both cite
  `authorize-matrix.spec.ts`) needs an allowlist to avoid false positives. It catches a pattern, not
  an instance.

So: **relevance is a review control and always was. The guard's job is missing, unresolvable and
vanished pins, and it still does all three.** What ruling 5 changed is not that the claim went
unchecked — it was always unchecked — but *where the claim is made*: closing a row is now a one-line
diff in one file, the row and its new pin and nothing else, which is the most reviewable shape this
judgement can have. A two-file edit nobody reads carefully is not a check either.

Every other mutation stays loud: `white-box-only` is still an allowlist (ruling 4), a deleted row is
caught by ruling 12's completeness check, an unresolvable reference by ruling 3, a row in the wrong
block by ruling 11d's contiguity check, and Gate 1 by the flag.

One relevance-adjacent check *does* become possible later, and belongs to **2c-9**, not here: once
that PR re-points the column at Go tests, a row whose `Pin` is `.go` while its `Source` still cites
only `.py` is a row that was re-pointed without being re-derived. Cheap, static, and it has nothing
to check until 2c-9 exists.

**Gate 1 stays machine-enforced**, by one boolean rather than a list:

```ts
/** Flipped to `true` by the PR that closes the last owed row. */
export const GATE_1_CLOSED = false;
```

While it is `false` the guard asserts at least one row is still owed; the moment the last one closes
that assertion fails, telling that PR to flip the flag in the same commit. Once `true`, the guard
asserts **zero** rows are owed, and Gate 1 can never silently reopen. One line, edited exactly once
in the phase, by one PR — not a four-way contention point.

**`PRS` is the one small shared list that remains** (`['2a-3', '2a-4', '2a-5', '2a-6', '2b-3']` —
every owner the block table names, and nothing else): the vocabulary an `owed:` marker may name. It exists because `owed: 2a-6` written where
`owed: 2a-5` was meant otherwise resolves fine and only fails if it happens to break a block run. It
is a fixed vocabulary, not per-row state — adding an owner is a deliberate edit, and no PR edits it
to close a row.

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

**A principal row carries one behaviour and, now, as many pins as it needs.** The Phase 1 matrix is
seven principals × six check columns — forty-two decision cells — and collapsing it to seven rows
drops the column dimension. That is deliberate: forty-two rows would be a different artefact from
the one the spec asks for, and the six checks for a principal are one authorization outcome from a
client's point of view. Ruling 3's list-valued `Pin` is what makes it honest: a principal row cites
**every** test covering the checks that deny for that principal, not one test standing in for six.

**The renumbering needs an owner, and this PR is not it.** After this ruling the spec's "rows 19-26"
means principals 19–25 and white-box 26–27, and the spec lives on a branch 2a-1 cannot edit. Task 7
step 4 files one issue on `D10Scot/Dispatcharr` carrying this and ruling 7's finding, so the spec's
own numbers do not stay wrong by default.

### 7. The spec's round-6 amendment owns the twelve orphaned rows. The Gate 1 gap it does not close is 2b-3's

**Read the amended spec, not this plan's memory of it.** At `3fb8b2bf` on `docs/phase2-spec`, 2a-5 is
`migration/phase2a-server-and-authorize-coverage` and its gate reads:

> `coverage_live_path.sh` shows a measured increase on `server.py`; **matrix rows 14-17 and 19, 20,
> 23, 25 each carry a test reference the guard test accepts**

So rows **14, 15, 16, 17, 19, 20, 23, 25 are `owed: 2a-5`**, row **12** is `owed: 2a-6`, row **18** is
`owed: 2b-3`, and there is no 2a-8. That is what the matrix is written to.

**This plan proposed a new 2a-8 and was wrong on three counts. Recorded, because the reasoning is
worth more than the verdict:**

1. **It argued against text that had already been amended.** The objection was "2a-5's gate is a
   `server.py` coverage increase, so it cannot see this work" — true of `:867` as it stood, and
   answered on its own terms by the amendment's second clause, which is a *per-row, machine-checked*
   gate on exactly those eight rows, enforced by the guard this PR builds.
2. **2a-8's own gate could not be met inside 2a.** Its gate was Gate 1 — no row carries an `owed:`
   pin — and Gate 1 includes **row 18**, which is `owed: 2b-3` in the original spec, in the amended
   roll-call and in this plan's own table. `2b-3` depends on 2b-1 and 2b-2, which depend on 2a-7. A PR
   named `2a-8` could therefore not merge until after the last PR of stage 2b: a 2b PR wearing a 2a
   name.
3. **Rows 16 and 17 belong in 2a, and this plan argued the opposite side of its own point.** It said
   row 17's invariant "is exactly what that change must not break" — and then routed it *into* the
   change. A test that must not break is written **before** the change, not inside it, or it comes
   out shaped to the new implementation. Pin first, then move: that is what a parity matrix is for,
   and it applies to row 16 and 2b-1 identically.

**The finding underneath survives the amendment, and is not this PR's to fix.** No PR's gate is
Gate 1: 2a-1's is "guard green" (green by design with twenty rows owed), 2a-3/4/5/6's are coverage
increases plus, now, their own rows, and 2a-7's is Gate 2 — yet D7 makes Gate 1 a hard precondition on
every 2c PR. Because row 18 can only close in 2b-3, **2b-3 is the only PR that can own Gate 1**, and
it is therefore the PR that flips `GATE_1_CLOSED`. The orchestrator is amending the spec for that
along with the four gate cells and the "2a stops at 2a-7 with the matrix 100% pinned" sentence, which
was never reachable. **Do not write any of that into this plan** — the matrix simply carries
`owed: 2b-3` on row 18 and lets the flag's own failure message tell 2b-3 to flip it.

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

- **`e2e-tests.yml`: two lines change, and the first draft of this plan was wrong to rule it out.**
  The `guards` project does have its own container-less CI job (`e2e/README.md` § CI: "`guards` is
  the one project deliberately **not** in that matrix") and it runs the project rather than a file
  list, so the new spec file needs no wiring. **But that job is gated on a path filter with no
  `docs/` in it**, so it cannot fire on the one file it guards.
  `.github/workflows/e2e-tests.yml:332-336` is `guards: … if: needs.changes.outputs.e2e == 'true'`,
  and the `changes` job's pattern (`:105`) is
  `^(apps/|core/|dispatcharr/|frontend/|docker/|scripts/|e2e/|e2e-upstream/|pyproject\.toml$|uv\.lock$|version\.py$|manage\.py$|\.github/workflows/e2e-tests\.yml$)`
  — the same list as the `push` trigger's `paths:` (`:9-22`). A pull request editing **only**
  `docs/relay-parity-matrix.md` — a citation refresh, a Notes correction, 2c-9's Go re-pointing of
  the whole column, 2d retiring a row — sets `e2e=false`, skips `guards`, and passes `E2E result`
  through its not-required branch. The guard never runs on the file it exists to guard. Task 2 adds
  `docs/relay-parity-matrix.md` to both lists. **Do not add anything to the `changes` job's
  `projects` list** — that list is for new Playwright *projects*, and this PR adds none.
- **`.claude/hooks/run-affected-tests.sh`: one new branch.** Nothing in the hook matches `*.md`, so
  editing the matrix runs no check at all locally, and the commit gate routes only backend labels
  and `frontend/`. A guard that fires only when someone happens to also touch a `.ts` file is not a
  gate. Task 2 adds a `docs/relay-parity-matrix.md` case that runs the `guards` project, in the same
  shape as the existing `e2e/*.ts` typecheck branch — blocking when it can run, a loud `note` when
  `e2e/node_modules` is missing.
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
`e2e/tests/guards/parity-matrix.spec.ts` holds the seven tests. This is the split the directory
already has (`ast.ts` and `allowlist.ts` are helper modules; the `.spec.ts` files are assertions),
and it is what lets 2a-3 … 2a-6 edit one small list without touching a test body.

**Do not put the lists in `allowlist.ts`.** That file is the grey-box capability allowlist,
`capabilities.spec.ts`'s data, and its `Capability` type does not fit. A second concern in it makes
both harder to read.

### 11. The format is designed for concurrent editors, and the guard enforces that

**This is the constraint that shapes every other format decision, and it arrived after the first
draft of this plan.** 2a-3, 2a-4, 2a-5 and 2a-6 all depend only on 2a-2 and touch disjoint *source*
files, so they will be developed in parallel as stacked PRs on 2a-2's branch; 2b-3 closes the last row
later. **Five PRs fill in test references in this one file**, four of them at the same time, so their
merges contend on it and on nothing else. Four properties make that contention
trivial. **Two of the four are asserted by named tests** — a property nobody checks is a property the
first person to run a Markdown formatter destroys — one holds by construction, and one is held by
review plus the file's own header comment. A fifth, (e), is what ruling 5 is for.

**(a) One row is one line, and no line's content depends on any other line.** No wrapped rows, no
multi-line cells, no continuation syntax. Closing a row is a one-line diff, so two PRs closing
different rows produce no conflict at all. *Enforced by construction*: the parser reads one row per
line and there is no continuation syntax to get wrong.

**(b) Cells are never padded to align columns.** Every table line — header, delimiter and rows —
is exactly `| ` + cells joined by ` | ` + ` |`, with no trailing whitespace. Padding is the failure
mode this rule exists for: one cell growing by a character re-aligns the whole column, so all four
PRs rewrite all twenty-seven lines and every merge conflicts on the entire file. The table looks
ragged in raw text. **That is the intended appearance, not a defect to tidy.** *Enforced by a named
test* (`the matrix table is one canonical line per row`) which fails naming the padded line, so
someone who runs a formatter learns exactly what they did rather than seeing "no matrix header".

**(c) The document stores no derived aggregate.** No "18 of 27 rows pinned" counter, no per-block
subtotal, no "last updated" line. Any such number is incremented by every one of the four PRs and
conflicts four ways, for a fact the guard can compute in a millisecond. *Enforced by review plus the
file's own header comment*; the guard **prints** the pinned/owed/white-box counts on every run, so
the number is available without being stored. If you find yourself wanting a count in the document,
that is the guard's output, not the document's content.

**(d) File order groups rows by the PR that owes them, not by id.** The spec's 2a table scatters
ownership across the id sequence — 2a-4 owns 1–6, 2a-3 owns 7–10 and 13 — so id order interleaves the
owners and turns every merge into an interleaved conflict. Block order makes each PR's edits
contiguous.

**"Contiguous, adjacent-line at worst" would not have been good enough, and the block markers are
what save it.** Measured in a scratch repo rather than assumed: git conflicts on two edits **one**
line apart and merges cleanly at **two**, and that holds for modify-vs-modify (`CONFLICT` at
distance 0 and 1, `CLEAN` at 2 and 3), modify-vs-delete and delete-vs-delete alike. Closing a row is
a *modify* — ruling 5 removed the only deletion — so two PRs closing rows in **adjacent blocks**
would conflict if the last row of one block sat directly above the first row of the next. The
`<!-- block: … -->` line between them is what makes that distance two. **The markers are load-bearing
for merge safety, not decoration the parser happens to skip**, and the matrix's own header comment
says so in those words: deleting them to tidy the file reintroduces precisely the conflicts the block
order exists to prevent. (Within a block adjacency is harmless — a block has exactly one owner, so
every edit in it comes from the same PR.)

The blocks, in file order:

| Block | Rows, in this order | Owner |
|---|---|---|
| 1 | 1, 2, 3, 4, 5, 6 | owed by 2a-4 |
| 2 | 7, 8, 9, 13 | owed by 2a-3 |
| 3 | 12 | owed by 2a-6 |
| 4 | 14, 15, 16, 17, 19, 20, 23, 25 | owed by 2a-5 |
| 5 | 18 | owed by 2b-3 |
| 6 | 10, 11, 21, 22, 24 | already pinned |
| 7 | 26, 27 | white-box-only |

**Seven blocks, five of them owed.** `PRS` lists exactly those five owners and nothing else, and
Task 5 step 6 checks the two against each other by eye.

*Enforced by a named test* (`rows owed by one PR are contiguous`): it takes the owed rows **in file
order**, maps each to its PR, and fails if any PR's label appears in two separate runs. Rows that are
already pinned are skipped, so a PR that closes part of its block does not break the property for the
rest — which is what makes the check survive the whole 2a sequence rather than only its first PR.

An HTML comment marks each block in the file. The parser skips blank lines and HTML-comment lines
*inside* the table run — the one piece of tolerance the parser has beyond trimming — so the blocks
are visible in raw text. It still stops at any other non-`|` line, so a row that loses its leading
pipe truncates the table and surfaces as a missing id in ruling 12's completeness check rather than
passing silently.

**(e) The property must hold in the guard's own file too, and that is why `OWED` is gone.** The
first draft satisfied (a)–(d) in the document and then put every id the four PRs delete on one shared
line of `parity-matrix.ts`. Ruling 5 deletes that list rather than reformatting it: owed-ness is read
from the row's own `Pin` cell, so closing a row is one line in one file. What is left in
`parity-matrix.ts` — `WHITE_BOX_ONLY` (two entries, edited only when a row becomes unobservable),
`PRS` (a fixed vocabulary) and `GATE_1_CLOSED` (flipped once, by one PR) — is none of it per-row
state and none of it a four-way contention point.

**Row 12 is owed by 2a-6, not by the 2a-4 the spec names.** The spec's 2a table says "2a-4 … closes
matrix rows 1-6, 12", but row 12 is the difference between `output/fmp4/generator.py:339`'s
`_is_timeout` and `output/ts/generator.py:574-585`'s, and 2a-4's stated subject is
`input/manager.py`. 2a-6 is the PR that works on the fMP4 side. The first draft of this plan
reported the mismatch and followed the spec anyway; the orchestrator has ruled it to 2a-6 and is
amending the spec, so the matrix is written to the ruling. It gets its own one-row block, and `PRS`
carries `2a-6`.

### 12. The id set is `1..N`, and the guard asserts it

Nothing in the first draft noticed a **deleted** row. Ids `[1, 10]` parse without complaint; a table
with row 19 removed passes every check — ids still unique, every remaining line canonical, every
surviving citation and pin resolving, `white-box-only` untouched — and the only count assertion was
`expect(rows.length).toBeGreaterThan(20)`, which 26 rows satisfy. At Gate 1 the hole widens to the
whole table: once every row is pinned, six could be deleted before that floor bit. The plan's own
framing — "everything after 2a-1 addresses rows by number", "2d's cutover checklist: every row must
show a passing Go-side equivalent" — depends on the row set being the row set, and nothing checked
that it was.

Ruling 2 already forbids the only thing that would make this expensive: ids are never renumbered and
a row that stops applying is retired **in place**, keeping its id. So the id set is exactly
`1..max(ids)`, and `the parity matrix parses` asserts it directly, naming the missing ids.

**The first draft of this check derived `N` from the data, and that left the tail unanchored in three
ways.** Measured, not reasoned: deleting the **highest** row passed, because `max` moved down with it
and `1..max` still held; a row appended **after** the terminator was invisible, so twenty-seven rows
parsed and row 28 simply did not exist; and an early terminator above the white-box block truncated
the table to twenty-five rows with completeness *passing* — caught only because `WHITE_BOX_ONLY`'s
`toEqual` happens to hold the two highest ids. That third one made **the white-box block's position at
the end of the table load-bearing and written down nowhere** — precisely the class of accident
ruling 11d fixed for the block markers, and not one to leave standing twice.

**Two of the three are closed outright; the third candidate fix is rejected. Each with its reason:**

1. **`HIGHEST_ROW_ID` replaces the derived maximum.** `expected` is `1..HIGHEST_ROW_ID`, a constant in
   `parity-matrix.ts`, so the check is two-sided: deleting the highest row fails, and adding row 28
   without saying so fails too. That closes the deletion hole **and** retires the white-box accident —
   truncation now fails on its own account, not because of where a different list happens to point.

   **Yes, this is a stored number, and B1 deleted one.** The two are not the same thing, and the
   distinction is worth stating rather than glossing. `toBeGreaterThan(20)` was a *threshold* that did
   not assert the property — 26 rows passed it with a row missing — and whose message blamed the
   parser. `HIGHEST_ROW_ID` asserts the property exactly and names the mismatch. Ruling 11c bans
   stored aggregates **in the document**, because five PRs would each bump one; this lives in the
   guard, beside `WHITE_BOX_ONLY` and `PRS`, and **no PR edits it to close a row** — rows are added
   only by a deliberate extension of the matrix. It is the same reasoning that made `white-box-only`
   an allowlist rather than a keyword: the edit that should be deliberate is made deliberate, in two
   places, with the guard naming the mismatch if you do half of it.

2. **Nothing below the terminator may parse as a matrix row.** `scanTable` scans the remainder of the
   file and throws on any five-cell line whose first cell is a number.

   **That is narrower than refusing every table, but broader than "a stray matrix row", and the plan
   says so rather than claiming a precision it does not have.** A five-column table with a numeric
   first column below the terminator is refused — and that is an ordinary Markdown construct, a
   numbered list of steps or an indexed reference table. So is a fenced worked example of a matrix
   row, which a `## Format` section is a natural place to want. Four-column tables, and five-column
   tables with a non-numeric first cell, are unaffected. The document's § Format states the
   constraint so an author meets it before the guard does, and the error message carries a second
   clause for the false-positive case, where "you added a row in the wrong place" would be wrong
   advice.

   **Fence-tracking is deliberately not the fix**, though it looks like the principled one: the
   duplicate-header refusal *relies* on a header inside a fenced block being visible, which is what
   stops a worked example in § Format being parsed as the matrix. Teaching the scanner about fences
   would make that example legal and silently retire a mutation this plan has proved. Treating fenced
   content as real content everywhere is consistent; this constraint is its price.

3. **Rejected: "the last row before the terminator carries the highest id."** It would close the same
   holes, and it fights ruling 11d. A new row goes at the end of **its owning PR's block**, not at the
   end of the table — so row 28 added to 2a-4's block, which is the first block, would fail a
   correct edit. A check that fires on the right action is the failure mode this directory's own
   guards are built to avoid, and it would also freeze the white-box block's position as a rule
   rather than a convention, buying nothing that `HIGHEST_ROW_ID` does not buy without the
   constraint.

**What stays open afterwards, stated rather than left to be discovered.** Two things, both real:

- **Moving a *pinned* row between blocks is undetected.** The contiguity check reads owed rows only,
  so a pinned row has no owner to be contiguous with. It costs nothing today — pinned rows are not
  edited by concurrent PRs — but a later PR re-pinning one could park it anywhere.
- **A row's *content* can be rewritten while its id and pin stay valid.** The guard checks that a
  citation resolves and a pin exists, never that either still describes the Behaviour cell beside it.
  That is the same limit ruling 5 states about relevance, and it has the same answer: review. It is
zero-maintenance — the maximum id supplies `N`, so adding a row needs no edit anywhere — and it is
not a stored aggregate (ruling 11c), because it is computed from the ids themselves. It replaces the
`toBeGreaterThan(20)` magic number, whose message ("That is this guard being broken, not the matrix
being short") trained a reader to suspect the parser rather than the deletion.

### 13. Four of the seven authorize principals have no test anywhere in `e2e/`

The first draft asserted that rows 19–25 "cite the tests PR 5 already shipped". Checked against the
tree, that is true of three of the seven and false of four.
`e2e/tests/streaming/authorize-matrix.spec.ts` declares ten tests, organised by **surface × filter**
— hidden-from-output and adult-content refusals across the native, catch-up and XC routes — not by
principal:

| Row | Principal | Test in the tree? |
|---|---|---|
| 19 | Internal (`X-Dispatcharr-Internal`) | **none** — `grep -rl "X-Dispatcharr-Internal" e2e/` returns nothing |
| 20 | Admin (`user_level >= 10`): every channel check bypassed, stream limit still enforced | **none** |
| 21 | XC credentials | yes — `a hidden channel is refused on the XC live root to an ordinary XC user`, `an adult channel is refused on the XC catch-up root to a hide_adult_content viewer` |
| 22 | JWT / API key | yes — `a hidden channel is refused on the native catch-up route to a JWT viewer` |
| 23 | Session, non-admin | **none** |
| 24 | Anonymous | yes — `a channel hidden from output is refused even to an anonymous request`, `an ordinary channel still streams with no credential at all` |
| 25 | Stream-by-hash | **none** — `grep -rl "stream_hash\|streamHash" e2e/tests/` hits only `seeded/auto-channel-sync.spec.ts` |

**That is a Phase 1 coverage gap this PR discovers, not a matrix bookkeeping detail**, and it is
worth saying in those words: the authorize hop PR 5 shipped has no test for the internal principal,
for the admin bypass, for an ordinary session, or for the stream-by-hash surface. The matrix records
it as four owed rows, `owed: 2a-5` per the spec's round-6 amendment, rather than papering over it; the PR body and the
filed issue both say so.

Consequences, corrected throughout this plan: **twenty rows are owed, not sixteen**; **five are
pinned, not nine**; two are white-box. The line the guard prints at 2a-1 is
`parity matrix: 27 rows — 5 pinned, 20 owed, 2 white-box-only`.

---

## Done criteria

- [ ] **`docs/relay-parity-matrix.md` exists** and carries 27 rows: 1–18 as the spec's Gate 1 table
      enumerates them, 19–25 one per Phase 1 authorize-matrix principal, 26–27 the two
      `white-box-only` rows. **Ids run `1..27` with no gaps** and the guard asserts it (ruling 12).
- [ ] **The guard prints `parity matrix: 27 rows — 5 pinned, 20 owed, 2 white-box-only`** — the
      counts ruling 13's grep produces, not the ones the first draft assumed.
- [ ] **The `guards` CI job fires on a diff that touches only `docs/relay-parity-matrix.md`** —
      the file is in `e2e-tests.yml`'s `push` `paths:` and in the `changes` job's pattern — and
      zizmor still reports **zero findings** on that workflow.
- [ ] **`prettier --write` cannot rewrite the matrix**, from the repo root or from `frontend/`, and
      the frontend tree's own Prettier result is unchanged (54 files, before and after).
- [ ] **Editing the matrix runs the guard locally** — `.claude/hooks/run-affected-tests.sh` has a
      `docs/relay-parity-matrix.md` case, demonstrated firing (Task 2 step 10).
- [ ] **Every row's `Source` cell carries at least one `file:line` citation that resolves** against
      this worktree — file present, line range inside it.
- [ ] **Every row's `Pin` cell is one of the three legal forms, and resolves** — a real test symbol,
      an `owed: <pr>` marker naming a PR in `PRS`, or `white-box-only` with a non-empty `Notes`
      cell and an id in `WHITE_BOX_ONLY`.
- [ ] **Every table line is canonical** — `| ` + cells joined by ` | ` + ` |`, no padding, no
      trailing whitespace — and **file order groups rows by owning PR**, seven blocks in the order
      ruling 11d gives, five of them owed. Both are asserted; both exist because four 2a PRs edit this file at once.
- [ ] **The document stores no derived count** — the guard prints them.
- [ ] **`e2e/tests/guards/parity-matrix.spec.ts` is green**, seven tests:
      `npx playwright test --project=guards parity-matrix`
- [ ] **The whole `guards` project is green**, including `tags.spec.ts`, which now sees seven more
      declarations: `npx playwright test --project=guards`
- [ ] **`cd e2e && npx tsc --noEmit` is clean.**
- [ ] **Each of the guard's seven checks is verified by mutation** (fourteen mutations), and the mutations are recorded in
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
.prettierignore                               NEW     one line: the matrix, with why
frontend/
  .prettierignore                             NEW     ../docs/relay-parity-matrix.md — Prettier
                                                      resolves ignores from the working directory,
                                                      and CLAUDE.md runs it from here
docs/
  relay-parity-matrix.md                      NEW     prose + § Format + the 27-row table
  superpowers/plans/
    2026-09-09-phase2-2a1-parity-matrix.md    PRESENT this file, committed by the planning pass
e2e/
  tests/guards/parity-matrix.ts               NEW     parser, types, WHITE_BOX_ONLY, PRS,
                                                      HIGHEST_ROW_ID, GATE_1_CLOSED
  tests/guards/parity-matrix.spec.ts          NEW     five @characterization tests
  COVERAGE.md                                 MODIFY  one row in the Guards (G11) table
  README.md                                   MODIFY  § Projects' guards row names the new guard
.github/workflows/
  e2e-tests.yml                               MODIFY  docs/relay-parity-matrix.md in the push
                                                      paths: list and the changes job's pattern,
                                                      so the guard can fire on a docs-only diff
.claude/hooks/
  run-affected-tests.sh                       MODIFY  one case running the guards project when
                                                      the matrix is edited
CLAUDE.md                                     MODIFY  one line in § Repository and direction
```

Touched and reverted, not in the diff: `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts`
(Task 6 step 4 puts a misspelled title in a comment there to prove the guard ignores comments, then
reverts it; Task 6 step 7's `git status --short` is what catches a failure to).

Nothing else. In particular: no `e2e/playwright.config.ts` change (no new project), no
`e2e/package.json` change (no new script, no new dependency), no `metrics/` change — § Design
ruling 9.

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
passing. The directory holds **six** `.spec.ts` files today — `tags`, `capabilities`, `testid`,
`global-mutation`, `pageerrors-enforcement`, `upstream-contract` — plus two helper modules
(`ast.ts`, `allowlist.ts`) that declare no tests. **Record the passing test count** — Task 8 checks
it went up by exactly seven.

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
  `COLUMNS: readonly string[]`,
  `type MatrixRow = { id: number; behaviour: string; source: string; pin: string; notes: string;
  line: number }`, `parseMatrix(markdown: string): MatrixRow[]`, `readMatrix(): Promise<string>`,
  `canonicalLineOffenders(markdown: string): string[]`.
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
 * Seven checks, in `./parity-matrix`:
 *   1. the table parses — found by its five column names, five cells a row,
 *      ids unique;
 *   2. every table line is canonical: `| ` + cells joined by ` | ` + ` |`,
 *      no padding, no trailing whitespace;
 *   3. every `Source` citation resolves to a real file and a line inside it;
 *   4. every `Pin` resolves — a real test symbol, an `owed:` marker naming a
 *      real PR, or `white-box-only`;
 *   5. `white-box-only` rows are exactly the allowlisted ones, each with a
 *      justification in its `Notes` cell;
 *   6. unpinned rows are exactly the ones the guard still owes;
 *   7. rows owed by one PR are contiguous in file order.
 *
 * Checks 5 and 6 duplicate a fact between the document and this directory on
 * purpose, in `capabilities.spec.ts`'s idiom and for its reason: `toEqual`,
 * not `toContain`, so that closing a row and opening one are both deliberate
 * edits, and the list cannot rot in either direction.
 *
 * Checks 2 and 7 exist because FOUR pull requests edit this file at once.
 * 2a-3, 2a-4, 2a-5 and 2a-6 depend only on 2a-2 and touch disjoint source
 * files, so they are developed in parallel; 2b-3 closes the last row later.
 * Their merges contend on the matrix and nothing else. Padding cells to align columns makes one growing
 * cell rewrite twenty-seven lines, so all four conflict on the whole file;
 * ordering rows by id instead of by owning PR interleaves the four PRs' edits
 * instead of keeping each one's contiguous. Both properties are invisible —
 * a Markdown formatter destroys the first in one keystroke and looks like
 * tidying — so both are asserted rather than written down. The matrix's own
 * header comment says the same thing to whoever opens the file.
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
import { canonicalLineOffenders, MATRIX_REL, parseMatrix, readMatrix } from './parity-matrix';

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, Markdown column layout, test
// titles declared in other specs. None of it is client-observable behaviour,
// and all of it changes shape when the suite is restructured. See
// docs/adr/0002-e2e-test-taxonomy.md.
test('the parity matrix parses', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());

  const ids = rows.map((r) => r.id);
  const duplicates = ids.filter((id, i) => ids.indexOf(id) !== i);
  expect(
    duplicates,
    `${MATRIX_REL} reuses a row id. Ids are this phase's addressing scheme — 2c PRs close ` +
      '"rows 7-10, 13" — so an id is never reused and never renumbered. A new row takes the ' +
      "next free id and is appended to the end of its owning PR's block.",
  ).toEqual([]);

  // Deliberately NOT an ascending-order check. File order groups rows by the
  // PR that owes them, not by id — see the header, and the contiguity check
  // below, which is the property that actually matters.

  // Ruling 12. Ids are never renumbered and a row that stops applying is
  // retired IN PLACE, keeping its id — so the id set is exactly 1..max, and a
  // gap means a row was deleted. Without this a pinned row can be dropped in
  // silence: every other check has nothing left to complain about.
  //
  // Zero-maintenance and not a stored aggregate (ruling 11c): the maximum id
  // supplies N, so adding a row needs no edit anywhere.
  const sorted = [...ids].sort((a, b) => a - b);
  const expected = Array.from({ length: HIGHEST_ROW_ID }, (_, i) => i + 1);
  const missing = expected.filter((id) => !sorted.includes(id));
  const unexpected = sorted.filter((id) => id > HIGHEST_ROW_ID);
  expect(
    sorted,
    `${MATRIX_REL} does not carry exactly rows 1..${HIGHEST_ROW_ID}. Ids run 1..N with no gaps: a ` +
      'row is never deleted, only retired in place with its Notes saying so, because 2c and 2d ' +
      'address rows by number and a row that vanishes takes its obligation with it.\n' +
      (missing.length ? `  Missing: ${missing.join(', ')}\n` : '') +
      (unexpected.length
        ? `  Above HIGHEST_ROW_ID: ${unexpected.join(', ')} — adding a row is a deliberate edit in ` +
          'two places; raise HIGHEST_ROW_ID in e2e/tests/guards/parity-matrix.ts in the same diff.\n'
        : ''),
  ).toEqual(expected);

  const empty = rows.filter((r) => r.behaviour === '').map((r) => `${MATRIX_REL}:${r.line}`);
  expect(
    empty,
    `${MATRIX_REL} has a row with an empty Behaviour cell. A row names one ` +
      'externally-observable live-path behaviour, in one sentence.',
  ).toEqual([]);
});

test('the matrix table is one canonical line per row', { tag: '@characterization' }, async () => {
  const offenders = canonicalLineOffenders(await readMatrix());

  expect(
    offenders,
    'Every table line is exactly "| " + cells joined by " | " + " |", with no padding and no ' +
      'trailing whitespace. Four pull requests (2a-3 … 2a-6) fill in test references in this ' +
      'one file concurrently; padding a cell to align a column rewrites every line, so all ' +
      'four conflict on the whole file instead of on the one row each changed. The table looks ' +
      'ragged in raw text and that is intended — do not run a Markdown table formatter over ' +
      'it.\n' + offenders.join('\n'),
  ).toEqual([]);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL — both tests error with `Cannot find module './parity-matrix'`.

- [ ] **Step 3: Write the minimal helper module.**

Create `e2e/tests/guards/parity-matrix.ts`:

```ts
/**
 * `docs/relay-parity-matrix.md`'s parser, and the two lists a row's status is
 * pinned against.
 *
 * Separate from `parity-matrix.spec.ts` for the reason `allowlist.ts` is
 * separate from `capabilities.spec.ts`: 2a-3, 2a-4, 2a-5, 2a-6, 2b-3 and
 * every 2c PR each close a matrix row, and closing one is a ONE-line diff in
 * ONE file — change that row's Pin cell — not an edit inside a test body and
 * not a deletion from a shared list of ids that all six would contend on.
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

/** The five column names, in order. The table is found by matching these. */
export const COLUMNS: readonly string[] = ['#', 'Behaviour', 'Source', 'Pin', 'Notes'];

/**
 * The canonical spelling of the header, for error messages and for the
 * no-padding check. The table is located by COLUMNS, not by this string, so a
 * padded header still parses — and then fails the padding check with a message
 * that names the real problem instead of "no matrix header".
 */
export const MATRIX_HEADER = canonicalLine(COLUMNS);

/**
 * The one legal spelling of a table line: `| ` + cells joined by ` | ` + ` |`.
 *
 * Cells are never padded to align columns, because four pull requests edit
 * this table concurrently and a padded column turns a one-cell edit into a
 * twenty-seven-line diff that conflicts four ways. `canonicalLineOffenders`
 * enforces it.
 */
export function canonicalLine(cells: readonly string[]): string {
  return `| ${cells.join(' | ')} |`;
}

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

function isHeaderLine(line: string): boolean {
  if (!line.trimStart().startsWith('|')) return false;
  const cells = splitRow(line);
  return cells.length === COLUMNS.length && cells.every((c, i) => c === COLUMNS[i]);
}

/**
 * Refuses to choose between two header rows.
 *
 * `findIndex` would take the first, and the first is not necessarily the real
 * table: this document's own "Format" section explains the format in prose, and
 * the natural next edit anyone makes to it is a worked example in a fenced
 * block — which would then be parsed instead of the matrix, silently, with
 * every check downstream enforcing nothing. Matching on trimmed column names
 * rather than on the literal header line makes that MORE likely, not less: a
 * padded example header binds where an exact-string match would have missed it.
 * "Parse loosely, assert precisely" only holds if the loose parse still refuses
 * to bind to two things.
 */
function findHeaderIndex(lines: readonly string[]): number {
  const matches = lines.flatMap((line, i) => (isHeaderLine(line) ? [i] : []));
  if (matches.length > 1) {
    throw new Error(
      `${MATRIX_REL} has ${matches.length} lines naming the five matrix columns (lines ` +
        `${matches.map((i) => i + 1).join(', ')}). There is exactly one matrix table in this ` +
        'file; a second — a worked example in a fenced block, say — would be parsed instead of ' +
        'the real one, so it is refused rather than guessed at.',
    );
  }
  return matches.length === 1 ? matches[0] : -1;
}

/**
 * The line that ends the table.
 *
 * An explicit terminator, because otherwise a truncation is indistinguishable
 * from a legitimate end: the table stops at the first line that is not a row,
 * so a stray prose line in the middle of it ends the table there and every
 * walker goes blind to everything below. With a terminator the walk knows it
 * stopped early and says so, naming the line.
 */
export const MATRIX_END_MARKER = '<!-- end of matrix -->';

/**
 * Lines inside the table run that are not rows: blanks, and HTML comments,
 * including multi-line ones.
 *
 * Multi-line matters. The matrix opens with a thirty-line
 * `<!-- READ THIS BEFORE EDITING -->` block, so that is the file's idiom, and
 * an author extending a one-line block marker into a two-line note is doing the
 * obvious thing. A single-line-only rule truncates the table there.
 */
type LineKind = 'row' | 'skip' | 'open' | 'end';

function classifyTableLine(line: string, insideComment: boolean): LineKind {
  const t = line.trim();
  if (insideComment) return t.includes('-->') ? 'skip' : 'open';
  if (t === '') return 'skip';
  if (t.startsWith('<!--')) return t.includes('-->') ? 'skip' : 'open';
  if (t.startsWith('|')) return 'row';
  return 'end';
}

export type TableScan = {
  headerLine: number;
  headerRaw: string;
  delimiterLine: number;
  delimiterRaw: string;
  rows: { line: number; raw: string }[];
};

/**
 * The one walk over the table region. Every check below uses it, and none has
 * its own idea of where the table starts or stops.
 *
 * This exists because two independent walkers went blind in different places
 * and in different ways: one returned `[]` when it could not find what it was
 * looking for — a check that passes because it found nothing to look at — and
 * both stopped at the first stray line, so a padded row *underneath* a stray
 * prose line was reported by nobody. Every structural failure now throws, from
 * one place, naming the line: a missing or duplicated header, a malformed
 * delimiter, a row that is not five cells, a table that stops before its
 * terminator, and a table with no terminator at all.
 */
export function scanTable(markdown: string): TableScan {
  const lines = markdown.split('\n');
  const headerIndex = findHeaderIndex(lines);
  if (headerIndex === -1) {
    throw new Error(
      `${MATRIX_REL} has no header row naming the five columns:\n  ${MATRIX_HEADER}\n` +
        'Every guard here finds the table by those five names. Do not add, rename or reorder a ' +
        'column without updating COLUMNS in e2e/tests/guards/parity-matrix.ts.',
    );
  }

  const delimiterRaw = lines[headerIndex + 1] ?? '';
  // The column count is checked too, not just the shape: `|---|---|` under a
  // five-column header is a well-formed delimiter for the wrong table.
  if (
    !/^\s*\|(?:\s*:?-+:?\s*\|)+\s*$/.test(delimiterRaw) ||
    splitRow(delimiterRaw).length !== COLUMNS.length
  ) {
    throw new Error(
      `${MATRIX_REL}:${headerIndex + 2} should be the table's ${COLUMNS.length}-column delimiter ` +
        `row (|---|---|---|---|---|), found ${JSON.stringify(delimiterRaw)}.`,
    );
  }

  const rows: { line: number; raw: string }[] = [];
  let insideComment = false;
  let terminatorIndex = -1;

  for (let i = headerIndex + 2; i < lines.length; i++) {
    const raw = lines[i];
    const location = `${MATRIX_REL}:${i + 1}`;

    if (!insideComment && raw.trim() === MATRIX_END_MARKER) {
      terminatorIndex = i;
      break;
    }

    const kind = classifyTableLine(raw, insideComment);
    if (kind === 'open') {
      insideComment = true;
      continue;
    }
    if (kind === 'skip') {
      insideComment = false;
      continue;
    }
    if (kind === 'end') {
      throw new Error(
        `${location} ends the table before its "${MATRIX_END_MARKER}" line: ` +
          `${JSON.stringify(raw)}. Everything below it would be invisible to every check here, ` +
          'which is why the table has an explicit terminator rather than stopping wherever it ' +
          'happens to stop. A row that lost its leading "|" looks exactly like this.',
      );
    }

    const cells = splitRow(raw);
    if (cells.length !== COLUMNS.length) {
      throw new Error(
        `${location} has ${cells.length} cells, expected ${COLUMNS.length} ` +
          '(# | Behaviour | Source | Pin | Notes). A literal "|" inside a cell splits the row; ' +
          'this table does not allow one.',
      );
    }

    rows.push({ line: i + 1, raw });
  }

  if (terminatorIndex === -1) {
    throw new Error(
      `${MATRIX_REL} has no "${MATRIX_END_MARKER}" line after the table. Without it a truncation ` +
        'is indistinguishable from the end of the table, and every check stops early in silence.',
    );
  }

  // Nothing below the terminator may be a matrix row. Without this a row
  // appended after it is simply invisible: twenty-seven rows parse, every check
  // is green, and row 28 does not exist. Deliberately narrow — an unrelated
  // table later in the document stays legal, because only a five-cell line
  // whose first cell is a number is refused.
  for (let i = terminatorIndex + 1; i < lines.length; i++) {
    const raw = lines[i];
    if (!raw.trimStart().startsWith('|')) continue;
    const cells = splitRow(raw);
    if (cells.length === COLUMNS.length && /^\d+$/.test(cells[0])) {
      throw new Error(
        `${MATRIX_REL}:${i + 1} looks like a matrix row but sits BELOW the ` +
          `"${MATRIX_END_MARKER}" line, where no check would ever see it: ${JSON.stringify(raw)}. ` +
          "A new row goes at the end of its owning PR's block, never after the terminator — or, " +
          'if this is not a matrix row at all, give it a different shape (a column count other ' +
          'than five, or a non-numeric first cell) or move it above the header. This scan cannot ' +
          'tell a five-column numbered table from a stray row, and refuses both.',
      );
    }
  }
  if (rows.length === 0) {
    throw new Error(
      `${MATRIX_REL} has the matrix header but no rows under it. That is this module being ` +
        'broken, or the table being empty; either way nothing below is enforcing anything.',
    );
  }

  return {
    headerLine: headerIndex + 1,
    headerRaw: lines[headerIndex],
    delimiterLine: headerIndex + 2,
    delimiterRaw,
    rows,
  };
}

export function parseMatrix(markdown: string): MatrixRow[] {
  return scanTable(markdown).rows.map(({ line, raw }) => {
    const [idCell, behaviour, source, pin, notes] = splitRow(raw);
    if (!/^\d+$/.test(idCell)) {
      throw new Error(
        `${MATRIX_REL}:${line} has ${JSON.stringify(idCell)} in the # column; a row id is a ` +
          'decimal integer, unique and never reused.',
      );
    }
    return { id: Number(idCell), behaviour, source, pin, notes, line };
  });
}

/**
 * Table lines whose raw text is not the canonical spelling of their own cells.
 *
 * Catches padding (`| #   |`), a missing space after a pipe, and trailing
 * whitespace — every way a Markdown formatter turns a one-line edit into a
 * whole-file diff. Returns `file:line — the line`, one per offender, so the
 * message says which line and what it looks like.
 *
 * The delimiter row is checked against its own canonical spelling rather than
 * against `canonicalLine`, since its cells are dashes, not content.
 *
 * It walks nothing itself: `scanTable` decides what the table is, so this check
 * cannot disagree with the parse about where the table stops, and cannot go
 * quietly blind below a stray line.
 */
export function canonicalLineOffenders(markdown: string): string[] {
  const scan = scanTable(markdown);
  const canonicalDelimiter = `|${COLUMNS.map(() => '---').join('|')}|`;
  const offenders: string[] = [];

  const check = (line: number, raw: string, expected: string): void => {
    if (raw !== expected) {
      offenders.push(
        `  ${MATRIX_REL}:${line} — is ${JSON.stringify(raw)}, should be ${JSON.stringify(expected)}`,
      );
    }
  };

  check(scan.headerLine, scan.headerRaw, MATRIX_HEADER);
  check(scan.delimiterLine, scan.delimiterRaw, canonicalDelimiter);
  for (const { line, raw } of scan.rows) check(line, raw, canonicalLine(splitRow(raw)));

  return offenders;
}
```

- [ ] **Step 4: Run it to verify it fails for the next reason.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL — `ENOENT … docs/relay-parity-matrix.md`.

- [ ] **Step 5: Create the matrix document with its prose and three rows.**

These three rows are the format's worked examples: an owed row, a pinned row and a
`white-box-only` row, each already inside its block comment. Tasks 3–5 add the other twenty-four
around them. **Write them literally** — every value here was verified in Task 1 step 3, and every
table line is already in the canonical no-padding spelling Task 2's second check requires.

> **The one way this goes wrong, and it is not the TypeScript.** The guard's code in this plan was
> prototyped and run four times; it compiles and behaves as described. **The divergence will be in
> this file, and it will be column alignment.** Every Markdown author aligns pipe tables, most
> editors do it on save, and this repo points you straight at the tool that does it: `CLAUDE.md:36`
> says "No format script: `npx prettier --write`", and Prettier's Markdown formatter pads pipe tables
> by default. Run on a four-row sample it produced:
>
> ```
> | #   | Behaviour                           | Source     | Pin            | Notes               |
> | --- | ----------------------------------- | ---------- | -------------- | ------------------- |
> ```
>
> Every line rewritten; every concurrent merge conflicted. **Never run a Markdown formatter over
> `docs/relay-parity-matrix.md`** — `npx prettier --write` included — and turn format-on-save off for
> it. If `the matrix table is one canonical line per row` is red on your first run, that is what
> happened. **Fix the file, not the guard.** Loosening that check deletes the property ruling 11
> exists for, and it will not be obvious for months.
>
> Steps 9b and 9c add two `.prettierignore` files so the common case cannot happen at all. They do
> not cover `--no-ignore`, another formatter, or hand-alignment — hence this note, and hence the
> guard.

**A note for the 2c-9 planner, recorded here because this is where the format is defined.** One
relevance-adjacent check becomes possible only in that PR: when 2c-9 re-points the `Pin` column at Go
tests, a row whose pin is `.go` while its `Source` still cites only `.py` is a row that was
re-pointed without being re-derived. Cheap, static, and it has nothing to check until then — see
ruling 5 for why no relevance check is possible now.
>
> Two runners-up, at the steps where they happen. **Citing a span you did not open** (Tasks 3–5): the
> guard proves a range *resolves*, never that it is right, so a range guessed from a `grep` hit
> passes and is wrong — open the file. **Putting a row in the wrong block** (Tasks 4–5): writing rows
> in id order and reordering afterwards loses one; the contiguity check catches it.

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

<!--
  READ THIS BEFORE EDITING THE TABLE BELOW.

  Five pull requests fill in test references in this table: 2a-3, 2a-4, 2a-5
  and 2a-6 (developed in parallel — they depend only on 2a-2 and touch disjoint
  source files), plus 2b-3, which closes the last row later. The ONLY thing
  their merges contend on is this table. Four
  properties keep that contention trivial. Three of them are asserted by
  e2e/tests/guards/parity-matrix.spec.ts, because a property nobody checks is a
  property the next person to run a Markdown formatter destroys.

  1. ONE ROW IS ONE LINE. No wrapped rows, no multi-line cells. Closing a row is
     a one-line diff, so two PRs closing different rows do not conflict at all.

  2. CELLS ARE NEVER PADDED TO ALIGN COLUMNS. Every table line is exactly
     "| " + cells joined by " | " + " |", with no trailing whitespace. Padding
     means one growing cell re-aligns the whole column, all four PRs rewrite
     every line, and every merge conflicts on the entire file. THE TABLE LOOKS
     RAGGED IN RAW TEXT AND THAT IS INTENTIONAL. Do not run a Markdown table
     formatter over this file.

  3. NO STORED COUNTS. No "18 of 27 pinned" line, no per-block subtotal, no
     "last updated" stamp - every one of the four PRs would bump it and conflict
     four ways over a number the guard computes in a millisecond. The guard
     PRINTS the pinned / owed / white-box counts on every run.

  4. ROW ORDER GROUPS BY OWNING PR, NOT BY ID. The spec scatters ownership
     across the id sequence (2a-4 owns 1-6, 2a-3 owns 7-10 and 13), so id order
     interleaves the PRs' edits. Block order keeps each PR's edits contiguous.
     DO NOT SORT THIS TABLE BY ID.

     DO NOT RUN A MARKDOWN FORMATTER OVER THIS FILE. `npx prettier --write`,
     which CLAUDE.md points you at, pads pipe tables by default and rewrites
     every line here. So does format-on-save in most editors. The guard's
     "one canonical line per row" check will fail; fix the file, not the guard.

     THE `<!-- block: -->` MARKER LINES ARE NOT DECORATION. Measured: git
     conflicts on two edits ONE line apart and merges cleanly at TWO, for
     modify-vs-modify, modify-vs-delete and delete-vs-delete alike. Closing a
     row is a modify, so the last row of one block and the first row of the
     next would conflict if they were adjacent — the marker line between them
     is what makes the distance two. Deleting the markers to "tidy up"
     reintroduces exactly the conflicts the block order exists to prevent.

  5. THE TABLE ENDS AT `<!-- end of matrix -->`. Keep that line, and DO NOT PUT
     A ROW BELOW IT — a row down there is invisible to every check here, and the
     guard refuses one, naming it. Without the terminator at all, a stray line
     in the middle of the table truncates it and every check below goes blind.

     Below the terminator this file must also not contain a five-column table
     with a numeric first column, nor a fenced example of a matrix row: the
     guard cannot tell either from a stray row, and refuses both. That is a
     deliberate trade — see § Format.

  A new row takes the next free id and is appended to the end of its owning
  PR's block. An id is never reused and never renumbered: 2c PRs address rows by
  number ("closes rows 7-10, 13").
-->

## Format

The guard finds the table by its five column names — `#`, `Behaviour`, `Source`, `Pin`, `Notes` —
trimmed, and **refuses to run if two lines in this file name them**. So do not add a worked example
table to this section: a second header would otherwise be parsed instead of the real matrix, silently.
Quoting the header inline in a sentence is fine — the guard only considers lines that *begin* with a
pipe. Do not add, rename or reorder a column without changing
`e2e/tests/guards/parity-matrix.ts` in the same commit. The header's canonical spelling is
`| # | Behaviour | Source | Pin | Notes |`, and every table line must be canonical the same way
(see the comment above): the parser tolerates padding so that it can tell you about it, and a named
check then fails it.

- **`#`** — a decimal integer. Unique, never reused, never renumbered. **A row is never removed from
  this table**: one that stops applying is retired *in place*, keeping its id and saying so in its
  Notes. The guard asserts the ids run `1..N` with no gaps, so deleting a row fails loudly. **Not in
  ascending file order** — rows are grouped by the PR that owes them.
- **`Behaviour`** — one sentence naming the externally-observable behaviour.
- **`Source`** — one or more backticked, repo-relative citations: `` `path:line` `` or
  `` `path:start-end` ``. The guard checks that each file exists and each range lies inside it. It
  cannot check that the range is the *right* code; that is what review is for.
- **`Pin`** — exactly one of three forms:
  - a test reference, `` `path::symbol` `` — for a `.spec.ts` the symbol is the test's literal
    title; for a `.py` it is the `def` name (optionally `path::Class::method`, of which the last
    segment is checked); for a `.go` it is the `func` name. The guard resolves the symbol in the
    file, so a renamed test fails here;
  - `owed: <pr>` — no test yet, and the named PR owes one. `<pr>` is a Phase 2 PR id from the
    guard's `PRS` vocabulary. **This cell is the only place owed-ness is recorded**, so closing a
    row is one line in one file — which is the point, because six PRs close rows in this table;
  - `white-box-only` — behaviour no client can observe, recorded honestly as behaviour **the Go
    relay is not held to**. This is an allowlist, not a keyword: the row id must also appear in the
    guard's `WHITE_BOX_ONLY` list with a `why`, and the `Notes` cell must say why here too.

  Enclosing backticks are optional on the last two — `` `owed: 2a-4` `` and `owed: 2a-4` both
  parse — and required on the test reference.
- **`Notes`** — prose. Required non-empty on a `white-box-only` row.

**No cell may contain a literal `|`.** A stray pipe splits the row into six cells and the guard
fails naming the line.

**The table ends at a literal `<!-- end of matrix -->` line, and needs one.** Without a terminator a
truncation is indistinguishable from the end of the table: a stray prose line in the middle silently
ends it there and every check goes blind to everything below. With one, the walk knows it stopped
early and says which line did it — which is also how a row that lost its leading `|` is reported as
itself rather than as a missing id.

**Do not put a row below the terminator.** A row down there is invisible to every check, so the guard
refuses one. **And know what that costs**, because it is broader than "a stray matrix row": below the
terminator this file must not contain **a five-column table whose first column is numeric**, nor **a
fenced example of a matrix row**. The guard cannot tell either from a row someone appended in the
wrong place, and a numbered five-column table is an ordinary Markdown construct — a numbered list of
steps, an indexed reference table — so this is a real constraint on what else this document may say,
not a theoretical one. Four-column tables and five-column tables with a non-numeric first column are
unaffected.

The alternative — teaching the scanner about fenced blocks — is **deliberately not taken**. The
duplicate-header refusal relies on a header inside a fenced block being visible: that is what stops a
worked example in this very section being parsed as the matrix. Treating fenced content as real
content everywhere is the consistent choice, and this constraint is its price.

## The matrix

Blocks, in file order: rows owed by 2a-4, then 2a-3, 2a-6, 2a-5 and 2b-3, then the rows already
pinned, then the `white-box-only` rows. Add a row to the end of its own block, and keep the
`<!-- block: … -->` line above it — it is what puts two lines between one PR's last row and the next
PR's first, which is the distance git needs to merge them cleanly.

| # | Behaviour | Source | Pin | Notes |
|---|---|---|---|---|
<!-- block: owed by 2a-5 -->
| 14 | Status payload field types differ by endpoint: `owner` is `null` on the list endpoint and the literal string `unknown` on the detail endpoint, `ffmpeg_speed` is a float on both, and `source_fps` is a float on list but a string on detail | `apps/proxy/live_proxy/channel_status.py:45`, `apps/proxy/live_proxy/channel_status.py:460`, `apps/proxy/live_proxy/channel_status.py:339`, `apps/proxy/live_proxy/channel_status.py:595`, `apps/proxy/relay_serializers.py:59`, `apps/proxy/relay_serializers.py:129` | `owed: 2a-5` | Neither serializer supplies a `default=`, so the builder's value reaches the wire unchanged. A test that checks the string against only one of the two endpoints proves nothing about the other |
<!-- block: already pinned -->
| 11 | One transcode process runs per active `(channel, profile)` pair across the cluster: a second client on the same Output Profile attaches to the existing process's buffer instead of spawning its own | `apps/proxy/live_proxy/output/profile/manager.py:67-122`, `apps/proxy/live_proxy/output/profile/manager.py:312-321` | `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts::two clients on one output profile share a single transcode` | Ten AC3 clients cost one ffmpeg. 2a-6 may re-pin this to a harness test; the existing e2e spec stands until it does |
<!-- block: white-box-only -->
| 27 | Not held to: `_execute_redis_command` swallows every Redis exception to `None` after one reconnect attempt, so a caller cannot distinguish "key absent" from "Redis unreachable" | `apps/proxy/live_proxy/server.py:138-159` | `white-box-only` | Deleted, not ported: spec D2 removes Redis from the live path entirely, so there is no analogous call in the Go relay to swallow anything. One of the three fail-open paths `CLAUDE.md` records as a live defect |
<!-- end of matrix -->
````

- [ ] **Step 6: Run the test to verify it passes.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 2 tests.

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

- [ ] **Step 8: Make the guard reachable in CI — its own detector output, not the heavy one.**

The `guards` CI job is gated on `needs.changes.outputs.e2e`, and neither that pattern nor the `push`
trigger's `paths:` names `docs/`. A pull request editing only the matrix skips the job entirely
(ruling 9). Confirm the anchors first — **use what the tree says, not what this plan says**:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
grep -n "docs/" .github/workflows/e2e-tests.yml
grep -n "pattern='\^(apps/" .github/workflows/e2e-tests.yml
grep -n "'\.github/workflows/e2e-tests\.yml'" .github/workflows/e2e-tests.yml
grep -n "outputs.e2e == 'true'" .github/workflows/e2e-tests.yml
```

Expected at `a948cd8a`: no `docs/` hit; the `pattern=` line at `:107`; the quoted `paths:` entry at
`:22`; and **four** jobs gated on `outputs.e2e` — `build` (`:118`), `upstream` (`:172`), `test`
(`:201`) and `guards` (`:336`).

**That fourth fact is why this is not a two-line edit.** `e2e` gates the 45-minute AIO image build and
the nine-project Playwright matrix as well as `guards`, and `e2e-result` then requires `upstream`,
`test` *and* `guards` to be exactly `success`. Adding `docs/relay-parity-matrix.md` to that one
pattern would make a one-line matrix edit trigger the heaviest workflow in the repo and block the
merge on all of it — the opposite of what the comment beside it says, and a recurring cost, since
2c-9 re-points the whole test-reference column and 2d walks the rows. **Give `guards` its own
detector output instead.**

Edit 1 — the `push` trigger's `paths:` list, after `- '.github/workflows/e2e-tests.yml'`. This one is
cheap as written, because `push` only fires on `main`:

```yaml
      # The parity matrix (Phase 2 Gate 1) is guarded by the `guards` project,
      # so a matrix-only edit has to reach it. Every other `docs/` path stays
      # out: this is the heaviest workflow in the repo and a docs merge must
      # not trigger an image build.
      - 'docs/relay-parity-matrix.md'
```

Edit 2 — the `changes` job's `outputs:` block (`:58-60`), adding one line:

```yaml
    outputs:
      e2e: ${{ steps.filter.outputs.e2e }}
      guards: ${{ steps.filter.outputs.guards }}
      projects: ${{ steps.filter.outputs.projects }}
```

Edit 3 — in the same job's script, after the existing `e2e=` decision, a second decision that does
**not** borrow it:

```bash
          # The guards project is static analysis over this repo's own source —
          # no image, no container, about a second. It must run whenever
          # anything it reads changes, including the parity matrix on its own,
          # without dragging the AIO build and the Playwright matrix along for
          # a docs edit.
          if [ "$full" = "true" ] || [ "$EVENT_NAME" != "pull_request" ] \
             || printf '%s\n' "$changed" | grep -qE '^(docs/relay-parity-matrix\.md$|e2e/)'; then
            echo "guards=true" >> "$GITHUB_OUTPUT"
          else
            echo "guards=false" >> "$GITHUB_OUTPUT"
          fi
```

**Mind the early `exit 0`.** The existing script returns early when `full` is true or the event is
not a `pull_request`. Place this block so it runs on every path that sets `e2e` — read the job in
full before inserting, and if the `e2e` decision exits early, `guards=true` must be written **before**
that exit as well, or a full-mode run silently skips the guard.

Edit 4 — the `guards` job's own gate (`:336`):

```yaml
    if: needs.changes.outputs.guards == 'true'
```

Edit 5 — `e2e-result`, so the guards leg is judged on its own requirement rather than the heavy
suite's. Add `GUARDS_REQUIRED` to the `env:` block and move the guards check **above** the
`E2E_REQUIRED` early exit:

```bash
          if [ "$CHANGES_RESULT" != "success" ]; then
            echo "Change detection itself failed — cannot prove the suite was unnecessary."
            exit 1
          fi
          if [ "$GUARDS_REQUIRED" = "true" ] && [ "$GUARDS_RESULT" != "success" ]; then
            echo "The guards project was required and did not succeed."
            exit 1
          fi
          if [ "$E2E_REQUIRED" != "true" ]; then
            echo "No E2E-relevant paths changed; suite deliberately skipped."
            exit 0
          fi
          if [ "$UPSTREAM_RESULT" != "success" ] || [ "$TEST_RESULT" != "success" ]; then
            echo "E2E suite was required and did not fully succeed."
            exit 1
          fi
          echo "E2E suite passed."
```

`GUARDS_RESULT` drops out of the last condition because it is judged above it. **That ordering is the
whole point**: `guards` can be required on a run where the heavy suite is not, which is exactly the
matrix-only diff this step exists for.

- [ ] **Step 8b: Prove the two paths are now independent.**

There is no way to run the `changes` job locally, so reason it through against the file and record
the answer:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
grep -n "outputs.e2e == 'true'\|outputs.guards == 'true'" .github/workflows/e2e-tests.yml
grep -n "GUARDS_REQUIRED\|GUARDS_RESULT\|E2E_REQUIRED" .github/workflows/e2e-tests.yml
```

Expected: three jobs on `outputs.e2e` (`build`, `upstream`, `test`) and **one** on `outputs.guards`;
`GUARDS_REQUIRED` present in `e2e-result`'s `env:` and used before the `E2E_REQUIRED` early exit.
**If `guards` is still on `outputs.e2e`, the edit did not land** — a matrix-only PR would then run the
image build, which is the thing this step exists to prevent.


- [ ] **Step 9: Lint the workflow with zizmor and confirm zero findings.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
grep -n "zizmor" .github/workflows/actions-lint.yml | head -5
zizmor .github/workflows/e2e-tests.yml
```

Expected: the pinned zizmor version from `actions-lint.yml`, and **zero findings**. The workflows are
at zero and that is a ratchet (`CLAUDE.md` § Test hooks). This edit adds no `uses:` and no `FROM`, so
no supply-chain pin is involved. If zizmor is not installed the hook and this step both say so —
**then say the lint did not run rather than describing the workflow as clean.**

- [ ] **Step 9b: Make the padding hazard impossible, not merely discouraged.**

Task 2 step 5's note tells the implementer never to run a Markdown formatter over the matrix.
**Documentation loses to muscle memory and to format-on-save**, so make the common case impossible as
well. There is no `.prettierignore` anywhere in this repo today; there is a `frontend/prettier.config.js`
and Prettier 3.9.6 as a `frontend/` devDependency.

**Two files, because one does not cover the idiom `CLAUDE.md` prescribes.** Measured, not assumed —
Prettier resolves `--ignore-path` relative to the **current working directory**, so a repo-root
ignore file is invisible when Prettier runs from `frontend/`, which is exactly where `CLAUDE.md:36`
tells you to run it:

| Run from | Ignore file | Result on the matrix |
|---|---|---|
| repo root | none | **padded** |
| `frontend/` | none | **padded** |
| repo root | root `.prettierignore` | untouched |
| `frontend/` | root `.prettierignore` | **padded** |
| `frontend/` | `frontend/.prettierignore` naming `../docs/relay-parity-matrix.md` | untouched |

Create `/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/.prettierignore`:

```
# The Phase 2 parity matrix is machine-read by
# e2e/tests/guards/parity-matrix.spec.ts. Its table is deliberately NOT
# column-aligned: several PRs edit it concurrently, and padding one cell
# rewrites every line, so every merge conflicts on the whole file. Prettier's
# Markdown formatter pads pipe tables by default, so it must not touch this
# one. See docs/superpowers/plans/2026-09-09-phase2-2a1-parity-matrix.md,
# ruling 11.
docs/relay-parity-matrix.md
```

Create `/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/frontend/.prettierignore`:

```
# Prettier resolves its ignore file relative to the working directory, so the
# repo-root .prettierignore does not apply when Prettier runs from here — which
# is where CLAUDE.md's "npx prettier --write" is documented to run. The parity
# matrix must not be column-aligned; see the root .prettierignore.
../docs/relay-parity-matrix.md
```

- [ ] **Step 9c: Prove both files work and that neither changes the frontend tree.**

**First, make sure there is a Prettier to run.** `frontend/node_modules` is **absent in a fresh
worktree** — § Test environment installs only `e2e/node_modules` — so `npx --no-install prettier`
here resolves from the npx cache or a parent `node_modules`, if at all. It is not the `frontend/`
devDependency this step is about, and on a machine without that cache it reports no binary:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/frontend && npx --no-install prettier --version
```

Expected: `3.9.6`. **If it prints nothing, run `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/frontend && npm install` first** — without it this whole step is unrunnable, and a step that
silently does not run is worse than one that fails.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
cp docs/relay-parity-matrix.md /tmp/matrix-before.md
npx --no-install prettier --write docs/relay-parity-matrix.md
diff -q /tmp/matrix-before.md docs/relay-parity-matrix.md && echo "root: UNTOUCHED"
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/frontend
npx --no-install prettier --write ../docs/relay-parity-matrix.md
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && diff -q /tmp/matrix-before.md docs/relay-parity-matrix.md && echo "frontend: UNTOUCHED"
```

Both must print `UNTOUCHED` and `git diff --stat docs/relay-parity-matrix.md` must be empty. **If
either rewrites the file, the ignore file is not being read** — check which directory you ran from.

Then confirm the frontend tree is unaffected, which is the one side effect worth ruling out:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/frontend
npx --no-install prettier --check 'src/**/*.jsx' 2>&1 | tail -1
```

Expected: `Code style issues found in 54 files` — **the same count as before this PR**, because
neither ignore file names anything under `frontend/src/`. A different number means an ignore pattern
is matching more than the matrix; narrow it.

**Two caveats on that 54.** It was measured with `frontend/node_modules` installed, so it is only
reachable after the `npm install` above. And it was measured against the **main checkout**, of
necessity — a fresh worktree has no `frontend/node_modules` to measure with. Treat it as the expected
value and, if your own baseline differs, **compare your own before-and-after rather than chasing the
number**: what this step proves is that the two ignore files change nothing for the frontend tree,
not that the tree has exactly 54 unformatted files.

**Belt and braces, on purpose.** These files stop `prettier --write` and format-on-save. They do not
stop `--no-ignore`, or a different formatter, or someone aligning the columns by hand — which is why
the imperative note stays at Task 2 step 5 and in the matrix's own header, and why the guard's
canonical-line check is the thing that actually enforces it.

- [ ] **Step 10: Make the guard reachable — the local edit hook.**

Nothing in `.claude/hooks/run-affected-tests.sh` matches `*.md`, so editing the matrix runs no check
locally, and the commit gate routes only backend labels and `frontend/`. Add a case beside the
existing `e2e/*.ts` typecheck branch:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
grep -n "e2e/\*.ts|e2e-upstream/\*.ts)" .claude/hooks/run-affected-tests.sh
```

Immediately after that `case … esac` block, add:

```sh
# ------------------------------------------------------------ parity matrix ---
# The Phase 2 parity matrix is machine-read by `e2e/tests/guards/parity-matrix.spec.ts`,
# and nothing else in this hook matches a Markdown file — so without this, the
# one document the guard exists to police is the one document it never runs on
# locally. The `guards` project needs no container and no browser; it is about
# a second.
case "$REL" in
  docs/relay-parity-matrix.md)
    if [ -d e2e/node_modules ]; then
      OUT="$(cd e2e && npx playwright test --project=guards parity-matrix 2>&1)"
      if [ $? -ne 0 ]; then
        block "parity-matrix guard after editing ${REL}" "$(printf '%s' "$OUT" | tail -30)"
      else
        printf '%s\n' "$OUT" | grep -E 'parity matrix: |passed' | head -2
      fi
    else
      note "Did NOT run the parity-matrix guard — e2e/node_modules is missing. Run 'cd e2e && npm ci'."
    fi
    ;;
esac
```

Then prove it fires, using the padding mutation from Task 6:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
echo '{"tool_input":{"file_path":"/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/docs/relay-parity-matrix.md"}}' \
  | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 \
    /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/.claude/hooks/run-affected-tests.sh
```

Expected on a clean matrix: the printed `parity matrix: …` count line, exit 0. **Record it.**

- [ ] **Step 11: Commit.**

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
are unique and never reused, and three worked rows covering the three Pin
forms.

Four 2a PRs will edit this table concurrently, so the format is built for that:
one row per line, no column padding, no stored counts, and file order grouped
by owning PR rather than by id. Two of the guard's checks exist to keep those
properties from being tidied away.

The parser lives beside the tests rather than inside them, for the reason
allowlist.ts lives beside capabilities.spec.ts: closing a row is one line in
one file, not an edit in a test body.

Two lines of wiring come with it. The guards CI job is gated on a path filter
with no docs/ in it, so it could not fire on the one file it guards; and no
edit hook matches a Markdown file, so a matrix edit ran no check locally
either. A guard that only runs when someone happens to also touch a .ts file
is not a gate.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git add docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts e2e/tests/guards/parity-matrix.spec.ts .github/workflows/e2e-tests.yml .claude/hooks/run-affected-tests.sh .prettierignore frontend/.prettierignore
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

Append to `e2e/tests/guards/parity-matrix.spec.ts`, **adding** `citationProblem` and `citationsIn`
to the existing `./parity-matrix` import — do not replace the list, or `canonicalLineOffenders` drops
out and Task 2's second test breaks:

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
const CITATION_RE = /`([^`\s]+):([1-9]\d*)(?:-([1-9]\d*))?`/g;

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
Expected: PASS, 3 tests. All three rows' citations resolve — they were verified in Task 1 step 3.

- [ ] **Step 5: Locate and add rows 1–9.**

Each row below gives the behaviour text to write, the PR that owes it (§ Design ruling 7), and
**how to find the citation**. Run the locator, read enough of the surrounding code to be sure you
have the right construct, and cite the span — a whole function where the behaviour is a function, a
tight range where it is a few lines. Do not cite a whole file.

**Insert them as two new blocks at the top of the table**, before the `<!-- block: owed by 2a-5 -->`
comment Task 2 wrote, each with its own block comment (ruling 11d). The result, in file order:

```
| # | Behaviour | Source | Pin | Notes |
|---|---|---|---|---|
<!-- block: owed by 2a-4 -->
| 1 | … | 2 | … | 3 | … | 4 | … | 5 | … | 6 | …          (one per line)
<!-- block: owed by 2a-3 -->
| 7 | … | 8 | … | 9 | …                                   (13 joins them in Task 4)
<!-- block: owed by 2a-5 -->
| 14 | …
<!-- block: already pinned -->
| 11 | …
<!-- block: white-box-only -->
| 27 | …
```

**Not in id order** — the ids in a block are whatever the spec assigned to that PR, and sorting the
table by id is the one edit ruling 11d forbids. Every new line is canonical: `| ` + cells joined by
` | ` + ` |`, no padding, no trailing space.

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
Expected: PASS, 3 tests. A failure here names the row and the citation; fix the citation, not the
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

Append to `e2e/tests/guards/parity-matrix.spec.ts`, **adding** `parsePin`, `PRS` and
`testRefProblem` to the existing import — again, add, never replace:

```ts
test('every pin resolves', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());
  const findings: string[] = [];

  for (const row of rows) {
    const where = `${MATRIX_REL}:${row.line} (row ${row.id})`;
    const pin = parsePin(row.pin);
    if (pin === undefined) {
      findings.push(
        `${where} — Pin cell ${JSON.stringify(row.pin)} is none of the three legal forms: one ` +
          'or more backticked `path::symbol` test references, "owed: <pr>" naming the PR that ' +
          'owes a test, or "white-box-only".',
      );
      continue;
    }
    if (pin.kind === 'owed') {
      if (!PRS.includes(pin.pr)) {
        findings.push(
          `${where} — "owed: ${pin.pr}" names a PR that is not in this phase's vocabulary ` +
            `(${PRS.join(', ')}). A typo here resolves silently otherwise. Add the PR to PRS in ` +
            'e2e/tests/guards/parity-matrix.ts if it is a real new owner.',
        );
      }
      continue;
    }
    if (pin.kind !== 'test') continue;
    for (const ref of pin.refs) {
      const problem = await testRefProblem(ref);
      if (problem !== undefined) findings.push(`${where} — ${problem}`);
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
/** A single `path::symbol` reference out of a Pin cell. */
export type TestRef = { file: string; symbol: string };

export type Pin =
  | { kind: 'test'; refs: TestRef[] }
  | { kind: 'owed'; pr: string }
  | { kind: 'white-box-only' };

/**
 * The PR ids an `owed:` marker may name.
 *
 * A fixed vocabulary, not per-row state: no PR edits this to close a row, so
 * it is not a contention point (ruling 11e). It exists because `owed: 2a-6`
 * written where `owed: 2a-5` was meant otherwise resolves fine, and the block
 * contiguity check only catches it if it happens to split a run.
 */
export const PRS: readonly string[] = ['2a-3', '2a-4', '2a-5', '2a-6', '2b-3'];

const OWED_RE = /^owed: (\S+)$/;

/**
 * `` `path::symbol` ``. The path is a non-space run up to the first `::`; the
 * symbol is everything after it up to the closing backtick, spaces included,
 * because a Playwright title is a sentence. A Python reference may carry a
 * class (`path::TestFoo::test_bar`); `symbolOf` takes the last segment.
 *
 * Global, because a Pin cell holds a LIST of references (ruling 3) — several
 * of the matrix's own rows are two-sided behaviours. The symbol is
 * `[^`]+` rather than `.+` so two references in one cell cannot be swallowed
 * into one mangled match, which is exactly what the anchored single-reference
 * form did.
 */
const TEST_REF_RE = /`([^\s`]+?)::([^`]+)`/g;

export function parsePin(cell: string): Pin | undefined {
  // Enclosing backticks are optional on the two bare forms and required on a
  // test reference, so both `owed: 2a-4` and owed: 2a-4 parse. Found while
  // prototyping this guard: the format section writes these tokens as inline
  // code, and a Markdown author's hand backticks them in the table too. A
  // format that fails on the more natural of two spellings is a format people
  // get wrong, so it accepts both rather than policing punctuation.
  const bare = cell.replace(/^`(.*)`$/, '$1').trim();
  if (bare === 'white-box-only') return { kind: 'white-box-only' };

  const owed = OWED_RE.exec(bare);
  if (owed !== null) return { kind: 'owed', pr: owed[1] };

  const matches = [...cell.matchAll(TEST_REF_RE)];
  if (matches.length > 0) {
    // Nothing outside the references but separators. Without this a cell
    // reading `` `a.spec.ts::t` and owed: 2a-5 `` — "partly pinned, the rest
    // still owed" — parses as fully pinned and the owed half is discarded
    // silently, which is the one direction this guard must never round in.
    const leftover = matches
      .reduce((rest, m) => rest.replace(m[0], ''), cell)
      .replace(/[\s,;·—-]+/g, '');
    if (leftover !== '') return undefined;
    return { kind: 'test', refs: matches.map((m) => ({ file: m[1], symbol: m[2] })) };
  }

  return undefined;
}

function symbolOf(ref: TestRef): string {
  const parts = ref.symbol.split('::');
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

/** A human-readable reason, or `undefined` when the reference resolves. */
export async function testRefProblem(ref: TestRef): Promise<string | undefined> {
  let src: string;
  try {
    src = await readFile(path.join(REPO_ROOT, ref.file), 'utf8');
  } catch {
    return `pin names no such file: ${ref.file}`;
  }

  const symbol = symbolOf(ref);

  if (ref.file.endsWith('.spec.ts')) {
    const titles = literalTitles(src, ref.file);
    if (titles.includes(symbol)) return undefined;
    return (
      `${ref.file} declares no test titled ${JSON.stringify(symbol)}. Literal titles found: ` +
      (titles.length === 0 ? '(none)' : titles.map((t) => JSON.stringify(t)).join(', '))
    );
  }

  if (ref.file.endsWith('.py')) {
    return new RegExp(String.raw`^[ \t]*def\s+${escapeRe(symbol)}\s*\(`, 'm').test(src)
      ? undefined
      : `${ref.file} has no "def ${symbol}("`;
  }

  if (ref.file.endsWith('.go')) {
    return new RegExp(String.raw`^func\s+(?:\([^)]*\)\s*)?${escapeRe(symbol)}\s*\(`, 'm').test(src)
      ? undefined
      : `${ref.file} has no "func ${symbol}("`;
  }

  // Fails closed, in `ast.ts`'s discipline: a shape this guard cannot read is
  // a failure, never a pass. 2c-9 re-points this matrix at Go tests, which is
  // why `.go` is already here.
  return (
    `${ref.file} has an extension this guard cannot verify. It reads .spec.ts (literal test ` +
    'titles), .py (def) and .go (func); anything else must be added to testRefProblem first.'
  );
}
```

- [ ] **Step 4: Run the test to verify it passes on the twelve existing rows.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 4 tests. Row 11's title reference resolves through `findTestCalls`; rows 1–9's
`owed:` markers parse; row 27's `white-box-only` parses.

- [ ] **Step 5: Locate and add rows 10, 12–18.**

Rows 10 and 11 are pinned by tests that already exist. Rows 12–18 are owed. **Each goes at the end
of its own block** (ruling 11d), never in id order:

- **12** → a new `<!-- block: owed by 2a-6 -->` after the 2a-3 block. **Not** 2a-4's block: the
  spec says 2a-4 but row 12 is `output/fmp4/generator.py` versus `output/ts/generator.py`, and
  2a-4's subject is `input/manager.py`. Ruled to 2a-6 (ruling 11d); the spec is being amended.
- **13** → end of the `owed by 2a-3` block, after row 9.
- **15** → end of the `owed by 2a-5` block, after row 14.
- **16, 17** → end of the `owed by 2a-5` block, after row 15. Both are 2a-5's under the spec's
  round-6 amendment, and the reason is the discipline the matrix exists for: a parity test pins
  behaviour that exists **now**, while 2b-1 and 2b-2 are the PRs that *change* those two mechanisms
  (`next-source`'s identifier resolution; `X-Relay-Client-IP` end to end). A test written inside the
  PR that changes the thing comes out shaped to the new implementation. **Pin first, then move.**
- **18** → a new `<!-- block: owed by 2b-3 -->` after the 2a-5 block, before the pinned block.
- **10** → the `already pinned` block, before row 11.

Row 18 owns a one-row block. That looks fussy and is not: it is the only row that cannot close inside
stage 2a — it is phrased as a question 2b-3 answers — so it is the last owed row in the phase, and the
PR that closes it is the one the Gate 1 flag's failure message tells to flip `GATE_1_CLOSED`.

Row 11 already exists from Task 2 — leave it where it is.

| # | Behaviour to write | Pin | How to find the Source |
|---|---|---|---|
| 10 | Multi-client upstream sharing: three clients on one channel share exactly one upstream connection, and closing every client releases it | `` `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection` `` | `grep -n "def add_client\|_registered_clients" apps/proxy/live_proxy/client_manager.py` — `add_client` and its duplicate guard (around `:215-245`); and the owner election in `grep -n "def.*owner\|nx=True" apps/proxy/live_proxy/server.py` (around `:505-530`). Cite both. Verify the title with `grep -n "three clients share exactly one upstream connection" e2e/tests/streaming/shared-upstream.spec.ts` |
| 12 | The fMP4 generator's `_is_timeout()` lacks the TS generator's `url_switching` exemption, so an fMP4 viewer can be dropped mid-failover while a TS viewer on the same channel is not | `owed: 2a-6` | `grep -n "_is_timeout" apps/proxy/live_proxy/output/fmp4/generator.py` (around `:339`) and `grep -n "_is_timeout\|url_switching" apps/proxy/live_proxy/output/ts/generator.py` (around `:574-590`). Cite both, because the row is the *difference* between them. **Filed as an issue and reproduced, not fixed** (spec D5) — say so in Notes |
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
Expected: PASS, 4 tests. Row 10's title is resolved through the compiler API, so a typo in it fails
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

### Task 5: The white-box allowlist, the Gate 1 flag, and rows 19–27

**Files:**
- Modify: `e2e/tests/guards/parity-matrix.ts` (append `WHITE_BOX_ONLY`, `HIGHEST_ROW_ID`, `GATE_1_CLOSED`)
- Modify: `e2e/tests/guards/parity-matrix.spec.ts` (append three tests, raise the self-check)
- Modify: `docs/relay-parity-matrix.md` (nine rows)

**Interfaces:**
- Consumes: everything Tasks 2–4 produced, including `parsePin`, whose `{ kind: 'owed'; pr }` is
  what the contiguity check reads.
- Produces: `type WhiteBoxRow = { id: number; why: string }`,
  `WHITE_BOX_ONLY: readonly WhiteBoxRow[]`, `HIGHEST_ROW_ID: number`, `GATE_1_CLOSED: boolean`. **Neither is per-row state**
  — `WHITE_BOX_ONLY` is edited only when a row becomes unobservable, and `GATE_1_CLOSED` is flipped
  once, by 2b-3. Their names and shapes are fixed here.

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

The second command prints each declaration's literal title. **Four of the seven principals have no
test at all** — ruling 13 records the grep results and what that means. Verify before writing; the
tree wins:

```bash
grep -rl "X-Dispatcharr-Internal" e2e/          # row 19 — expect no output
grep -rl "stream_hash\|streamHash" e2e/tests/   # row 25 — expect only seeded/auto-channel-sync.spec.ts
```

**Do not invent a title** for a principal with no test, and **do not mark it `white-box-only`**: an
authorization outcome is observable at a client-facing surface by definition, so `white-box-only`
would be a false claim. Mark it `owed: 2a-5` (ruling 7).

Ruling 3 makes `Pin` a **list**, so a principal that is covered by two tests cites both, separated
by `, `. That is what keeps ruling 6 honest — a principal row stands for six check columns, and it
should cite every test covering the checks that deny for that principal rather than one standing in
for six.

| # | Behaviour to write | Pin |
|---|---|---|
| 19 | Authorize matrix — **Internal** principal (DVR, any caller with a valid `X-Dispatcharr-Internal`): the STREAMS ACL applies; `user_level`, profile membership, `hidden_from_output`, adult filtering and the stream limit are all bypassed | `owed: 2a-5` |
| 20 | Authorize matrix — **Admin** (`user_level >= 10`, any authenticator): ACL applies, every channel check bypassed, the stream limit still enforced | `owed: 2a-5` |
| 21 | Authorize matrix — **XC credentials** (`<user>/<pass>` path segments, compared with `hmac.compare_digest`): every check enforced; `hidden_from_output` and adult filtering answer 403 | `` `e2e/tests/streaming/authorize-matrix.spec.ts::a hidden channel is refused on the XC live root to an ordinary XC user` ``, `` `e2e/tests/streaming/authorize-matrix.spec.ts::an adult channel is refused on the XC catch-up root to a hide_adult_content viewer` `` |
| 22 | Authorize matrix — **JWT / API key / query-param JWT**, non-admin: every check enforced | `` `e2e/tests/streaming/authorize-matrix.spec.ts::a hidden channel is refused on the native catch-up route to a JWT viewer` `` |
| 23 | Authorize matrix — **Session**, non-admin: every check enforced | `owed: 2a-5` |
| 24 | Authorize matrix — **Anonymous** (a bare channel UUID): the ACL applies, `hidden_from_output` answers 403, and every user-scoped check is inapplicable — an anonymous request with a valid UUID still streams an ordinary channel | `` `e2e/tests/streaming/authorize-matrix.spec.ts::a channel hidden from output is refused even to an anonymous request` ``, `` `e2e/tests/streaming/authorize-matrix.spec.ts::an ordinary channel still streams with no credential at all` `` |
| 25 | Authorize matrix — **Stream-by-hash** (`/proxy/ts/stream/<stream_hash>`), any principal: the ACL applies and the stream limit is enforced when a principal resolved; no channel check applies | `owed: 2a-5` |
| 26 | Not held to: the greenlet and OS-thread topology inside `server.py` — three `threading.Thread(daemon=True)` supervisors sharing one OS thread with the request greenlets, and `_spawn_on_hub`'s cross-thread scheduling onto the gevent hub | `white-box-only` |

**Every Pin cell above is written literally, and the cell text is only what is between the pipes** —
rows 19, 20, 23 and 25 carry exactly `owed: 2a-5`, nothing more. (An earlier draft appended a gloss
inside the cell; `OWED_RE` is anchored, so a cell reading `owed: 2a-5 — no test exists` is
unparseable. The guard says so loudly, but there is no reason to write it wrong.) The reason those
four are owed belongs in the row's **Notes** cell: *no `e2e/tests/` spec pins this principal — see
ruling 13.*

The four titles were read out of `authorize-matrix.spec.ts` at `a948cd8a` (lines 28, 56, 135, 178,
206); verify each with the `grep` before copying, and use what the tree says.

**The spec now carries citations for these rows too** — the round-6 amendments give row 19
`apps/proxy/authorize.py:309-310`, `:376-377`, `:436-442`, row 23 `apps/proxy/authorize.py:268-276`
(`_session_user`, which reads the session directly rather than `http_request.user`) and row 25
`apps/proxy/next_source.py:69-79`. Carry them, **verifying each with `sed -n` first**; where the spec
gives only a bare module (`apps/proxy/authorize.py` for rows 20, 21, 22, 24), locate the span
yourself — a citation must name lines, not a file.

**Placement (ruling 11d).** Rows 21, 22 and 24 are pinned, so they go in the `already pinned` block
after row 11. Rows 19, 20, 23 and 25 are owed by 2a-5, so they go in the `owed by 2a-5` block after
row 15. Row 26 goes in the `white-box-only` block, before row 27. The contiguity check in step 2
fails, naming the PR, if any of them lands in the wrong block.

Row 26's Source: `apps/proxy/live_proxy/server.py:161-172` (`_spawn_on_hub`, verified) plus the
`threading.Thread(...)` sites — `grep -n "threading.Thread" apps/proxy/live_proxy/server.py` (three
at `a948cd8a`: `:467`, `:851`, `:2192`). Cite `_spawn_on_hub`'s span and at least one thread site.
Notes: deleted, not ported — the Go relay's concurrency model is goroutines and a `sync.RWMutex`
(spec D2), and no client can observe which greenlet did what.

- [ ] **Step 2: Write the three failing tests.**

Append to `e2e/tests/guards/parity-matrix.spec.ts`, extending the import to add
`{ GATE_1_CLOSED, HIGHEST_ROW_ID, WHITE_BOX_ONLY }`:

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

test('Gate 1: the matrix is fully pinned when the flag says so', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());
  const owed = rows.filter((row) => parsePin(row.pin)?.kind === 'owed');
  const ids = owed.map((row) => row.id).sort((a, b) => a - b);

  if (GATE_1_CLOSED) {
    expect(
      ids,
      'GATE_1_CLOSED is true, so no row may carry an "owed:" pin. Gate 1 — the spec\'s own ' +
        'definition of "the behaviour is pinned" — cannot silently reopen. If a row genuinely ' +
        'needs to go back to owed, flip GATE_1_CLOSED in the same diff and say why.',
    ).toEqual([]);
  } else {
    expect(
      ids.length,
      'No row is owed any more — you just closed the last one. Flip GATE_1_CLOSED to true in ' +
        'e2e/tests/guards/parity-matrix.ts, in this same commit: Gate 1 is met, and from here ' +
        'the guard asserts it stays met. This is the phase\'s first hard blocker turning off.',
    ).toBeGreaterThan(0);
  }

  // The counts live here, computed, rather than in the document, where four
  // concurrent PRs would each bump them and conflict four ways over a number
  // that takes a millisecond to derive (ruling 11c).
  const kinds = rows.map((row) => parsePin(row.pin)?.kind);
  console.log(
    `parity matrix: ${rows.length} rows — ` +
      `${kinds.filter((k) => k === 'test').length} pinned, ` +
      `${kinds.filter((k) => k === 'owed').length} owed, ` +
      `${kinds.filter((k) => k === 'white-box-only').length} white-box-only.`,
  );
});

test('rows owed by one PR are contiguous', { tag: '@characterization' }, async () => {
  const rows = parseMatrix(await readMatrix());

  // Owed rows only, in FILE order. Pinned rows are skipped rather than
  // breaking a run, so a PR that closes part of its block does not fail this
  // check for the rows it left — which is what makes the property survive the
  // whole 2a sequence instead of only its first PR.
  const owners: { pr: string; id: number }[] = [];
  for (const row of rows) {
    const pin = parsePin(row.pin);
    if (pin?.kind === 'owed') owners.push({ pr: pin.pr, id: row.id });
  }

  const runs: string[] = [];
  for (const { pr } of owners) {
    if (runs[runs.length - 1] !== pr) runs.push(pr);
  }

  const split = runs.filter((pr, i) => runs.indexOf(pr) !== i);
  expect(
    split,
    'Rows owed by one PR must be contiguous in file order. Seven PRs close rows in this table ' +
      'and three of them run in parallel; interleaving their rows interleaves their diffs and ' +
      'turns every '  +
      'merge into a conflict. Order in the file is by owning block, NOT by id — do not sort ' +
      `this table. Owner sequence read from the file: ${runs.join(' → ')}. Rows, in file ` +
      `order: ${owners.map((o) => `${o.id}(${o.pr})`).join(', ')}.`,
  ).toEqual([]);
});
```

- [ ] **Step 3: Run them to verify they fail.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: FAIL. Playwright transpiles TypeScript but does not typecheck it, and `e2e/package.json`
declares no `"type": "module"`, so a missing named export surfaces at **run time** from the
transpiled CommonJS as `TypeError: (0 , _parityMatrix.WHITE_BOX_ONLY) is not a function` or an
`undefined` read — not as a TypeScript diagnostic. Verified by probe. `npx tsc --noEmit` is where the
type error appears; the Playwright run is where the runtime one does.

- [ ] **Step 4: Add the allowlist, the row bound and the Gate 1 flag.**

Append to `e2e/tests/guards/parity-matrix.ts`. **Neither is a list of owed row ids** — ruling 5
deleted that, and owed-ness is read from each row's own `Pin` cell.

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
 * The highest row id the matrix carries. Bounded here rather than derived from
 * the table, and the difference matters in both directions.
 *
 * Derived, the check was `1..max(ids)` — which a **tail** deletion satisfies,
 * because dropping the highest row just lowers the maximum. Bounded, deleting
 * the highest row fails, and so does adding row 28 without saying so here.
 *
 * It is a stored number and that is deliberate (ruling 12): it lives beside
 * `WHITE_BOX_ONLY` and `PRS` rather than in the matrix, and **no PR edits it to
 * close a row** — rows are added only by a deliberate extension of the matrix,
 * which is exactly the edit that should take two places and a stated reason.
 */
export const HIGHEST_ROW_ID = 27;

/**
 * Gate 1's own switch. Flipped to `true` by the PR that closes the last owed
 * row. That is 2b-3: row 18 is the only row that cannot close inside stage 2a,
 * so 2b-3 is the last PR in the phase that closes one.
 *
 * There is deliberately no list of owed row ids here. A row is owed if and
 * only if its own `Pin` cell says so, which is what makes closing one a
 * one-line edit in one file: 2a-3, 2a-4, 2a-5, 2a-6 and 2b-3 all edit
 * this matrix, and a shared list of ids would put every one of their deletions
 * on the same line of this file (ruling 5, ruling 11e).
 *
 * The guard asserts "at least one row is still owed" while this is `false`, so
 * the PR that closes the last row is told to flip it rather than discovering
 * later that Gate 1 was met and nobody noticed; and "no row is owed" once it is
 * `true`, so Gate 1 cannot silently reopen.
 */
export const GATE_1_CLOSED = false;
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: PASS, 7 tests.

The printed line should read `parity matrix: 27 rows — 5 pinned, 20 owed, 2 white-box-only`. If it
does not, count the Pin cells rather than editing the guard: the numbers are computed, so a different
answer means the table is different from what this plan expects, not that the check is wrong.

A mistyped PR id in an `owed:` marker fails `every pin resolves` against the `PRS` vocabulary, naming
the row and listing the legal ids.

- [ ] **Step 6: Confirm the matrix is complete.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
grep -c '^| [0-9]' docs/relay-parity-matrix.md
grep -o '^| [0-9]*' docs/relay-parity-matrix.md | tr -d '| ' | sort -n | tr '\n' ' '
```

Expected: `27`, and `1 2 3 … 27` with no gaps and no repeats. **`sort -n` is doing the sorting —
the file itself is not in id order and must not be** (ruling 11d). A gap means a row was missed; a
repeat means the first test would have caught it, so a repeat here means the table was edited after
the last run — re-run step 5.

Confirm the block structure too:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1
grep -n "^<!-- block: \|^| [0-9]" docs/relay-parity-matrix.md | sed 's/\(:.\{0,40\}\).*/\1/'
```

Expected: nine `<!-- block: … -->` lines, in the order `owed by 2a-4`, `owed by 2a-3`,
`owed by 2a-6`, `owed by 2a-5`, `owed by 2b-3`, `already pinned`, `white-box-only`, with the rows of
each block between them, and one `<!-- end of matrix -->` after the last row.

Then check `PRS` against the block table by eye: **the set of PR ids appearing in `owed:` cells must
equal `PRS` exactly** — five ids, `2a-3`, `2a-4`, `2a-5`, `2a-6`, `2b-3`. An owner named in the table
but missing from `PRS` fails `every pin resolves`; one in `PRS` but not in the table is dead
vocabulary. The step 5 contiguity check asserts the same thing; this is the human-readable view
of it.

- [ ] **Step 7: Typecheck, run the whole guards project, and commit.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx tsc --noEmit
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards
```

Expected: silent; all green, seven more tests than Task 1 step 2 recorded.

Message to `<SCRATCH>/msg-task5.txt`:

```
docs(phase2): the authorize rows, the white-box allowlist and the owed ratchet

Rows 19-25 cite the seven authorize-matrix principals to the tests PR 5
already shipped; rows 26-27 record the two behaviours the Go relay is
deliberately not held to.

Both markers are allowlists compared with toEqual, not keywords: marking a
row white-box-only, and leaving one unpinned, each take a deliberate edit in
two places. That is what makes "no test yet" a ratchet rather than a
permanently green answer — Gate 1 is met when no row carries an owed: pin.

A third check keeps each owing PR's rows contiguous in file order, and the
pinned/owed/white-box counts are printed by the guard rather than stored in
the document. Four 2a PRs edit this table at once; an interleaved order or a
stored counter would make all four conflict on every merge.

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

**Interfaces:** none. Produces the fourteen mutation results Task 7 writes into `e2e/COVERAGE.md`.

Every guard in this directory records in its own header that it was verified by mutation, and says
what the mutation was and what it printed. `capabilities.spec.ts` makes the argument: a guard that
has never been seen to fail is a guard nobody knows works. This task does that five times.

**Each mutation is made, run, and reverted before the next one.** `git diff` must be empty on
`docs/relay-parity-matrix.md` and `e2e/tests/guards/parity-matrix.ts` at the end of every mutation.

- [ ] **Step 1: Mutate the header. Expect check 1 to fail.**

Edit `docs/relay-parity-matrix.md`: change the table header's `Notes` to `Note`.

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: every check fails with `has no header row naming the five columns`, printing the
canonical header. **Record the message.**

Revert: restore `Notes`. Re-run; expected PASS, 7 tests. Confirm with
`git diff --stat docs/relay-parity-matrix.md` — empty.

Then the second half of this check, which is the one the format's own § Format section makes likely:
add a **second** five-column header row inside a fenced ```` ```markdown ```` block above the real
table, the way anyone would demonstrate the format. Expected: every check fails with
`has 2 lines naming the five matrix columns (lines <a>, <b>)`. **Record it** — before this the parser
took the first match and enforced nothing about the real table, silently. Revert and re-run.

- [ ] **Step 1b: Pad one cell. Expect the canonical-line check to fail, and only it.**

Edit `docs/relay-parity-matrix.md`: in row 27, change `| 27 |` to `| 27  |` — one extra space, the
single edit a Markdown table formatter makes twenty-seven of.

Run: `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1/e2e && npx playwright test --project=guards parity-matrix`
Expected: **only** `the matrix table is one canonical line per row` fails, naming
`docs/relay-parity-matrix.md:<line>` and printing both the padded line and its canonical spelling.
Every other check stays green — which is the point of parsing tolerantly and asserting precisely:
padding is reported as padding, not as "no matrix header". **Record the message.**

Revert and re-run; expected PASS, 7 tests.

- [ ] **Step 1c: Move one owed row out of its block. Expect the contiguity check to fail, and only it.**

Edit `docs/relay-parity-matrix.md`: cut the `| 6 | …` line out of the `owed by 2a-4` block and paste
it at the end of the `owed by 2a-5` block, after row 25. Nothing about the row's content changes, so
its citation and pin still resolve — only its position does.

Run the same command.
Expected: **only** `rows owed by one PR are contiguous` fails, printing the owner sequence read from
the file — `2a-4` in two separate runs — and the owed rows in file order. **Record the message.**
This is the mutation that proves someone cannot re-sort the table by id, or drop a row into the wrong
block, without being told.

Revert and re-run; expected PASS, 7 tests.

- [ ] **Step 2: Mutate a citation. Expect check 2 to fail.**

Edit `docs/relay-parity-matrix.md`: in row 27's Source, change
`` `apps/proxy/live_proxy/server.py:138-159` `` to `` `apps/proxy/live_proxy/server.py:138-99999` ``.

Run the same command.
Expected: `every row cites source that resolves` fails, naming `row 27` and
`runs past the end of the file, which has <N> lines`. **Record the message and `<N>`.**

Revert and re-run; expected PASS, 7 tests.

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

Revert both; re-run; expected PASS, 7 tests.

- [ ] **Step 4: Mutate the white-box marker. Expect check 4 to fail.**

Edit `docs/relay-parity-matrix.md`: change row 12's Pin from `owed: 2a-6` to `white-box-only`.

Run the same command.
Expected: `white-box-only rows are confined to an allowlist` fails, reporting `[12, 26, 27]` against
`[26, 27]`. **Record it.** Ruling 5 removed the second failure the first draft expected here — there
is no list of owed ids any more — and the allowlist is now the whole defence: the marker cannot be
applied without a matching entry and a stated `why` in `parity-matrix.ts`.

Revert and re-run; expected PASS, 7 tests.

- [ ] **Step 4b: Truncate the table with a stray line. Expect every check to fail, naming that line.**

Edit `docs/relay-parity-matrix.md`: insert a line of prose — `A note about the block below.` — between
two rows in the middle of the table, and separately delete the leading `|` from one row.

Run the same command.
Expected, for each: **every check fails** with `ends the table before its "<!-- end of matrix -->"
line`, naming the offending line and quoting it. **Record both.** This is the mutation the explicit
terminator exists for: without it the table simply ended at that line, the parse silently lost every
row below, and the padding check went blind to them too — a padded row underneath a stray line was
reported by nobody.

Then delete the `<!-- end of matrix -->` line itself. Expected: every check fails — with
`has no "<!-- end of matrix -->" line after the table` if nothing follows the table, or with
`ends the table before its "<!-- end of matrix -->" line` naming the **first line of prose after the
table**, if something does. Both are correct and both are loud; record whichever you see.

Revert all three; re-run; expected PASS, 7 tests.

- [ ] **Step 5: Delete a pinned row. Expect only the completeness check to fail.**

Edit `docs/relay-parity-matrix.md`: delete row 24's line outright — a **pinned** row, so no
`owed:` marker goes missing and nothing else has anything to complain about.

Run the same command.
Expected: only `the parity matrix parses` fails, with `is missing row ids` and `Missing: 24`.
**Record the message.** This is the mutation that matters most after Gate 1: once every row is
pinned, deletion is the only way a row can stop being an obligation, and before ruling 12 it was
silent — every other check passes on a table that is simply shorter.

Revert and re-run; expected PASS, 7 tests.

- [ ] **Step 5b: The three assertions no mutation has touched yet.**

The eight above cover the header, padding, block order, citations, titles, the white-box marker,
truncation and deletion. Three assertions are still unexercised against the real document — and one
of them is the mechanism that turns the phase's first hard blocker off, whose `true` branch is
otherwise never run until the PR that needs it.

**PR vocabulary.** Change any row's `owed: 2a-5` to `owed: 2a-9`. Expected: only `every pin resolves`
fails, naming the row and listing the five legal ids. Revert.

**Gate 1, flipped early.** Set `GATE_1_CLOSED = true` in `e2e/tests/guards/parity-matrix.ts` with the
matrix untouched. Expected: only the Gate 1 check fails, with `GATE_1_CLOSED is true, so no row may
carry an "owed:" pin`. **Record it** — this is the assertion that stops Gate 1 being declared met
before it is. Revert.

**Gate 1, reached.** Leave `GATE_1_CLOSED = false` and temporarily change **every** `owed:` cell to a
pin that resolves — the simplest is `` `e2e/tests/streaming/shared-upstream.spec.ts::three clients
share exactly one upstream connection` `` in all twenty. Expected: only the Gate 1 check fails, with
`No row is owed any more — you just closed the last one. Flip GATE_1_CLOSED to true`. **Record it** —
this is what tells 2b-3 it has finished the job. Revert all twenty; `git diff --stat` must be empty.

- [ ] **Step 5c: The tail — three mutations that were silent before ruling 12.**

**Delete the highest row.** Remove row 27's line. Expected: `the parity matrix parses` fails with
`does not carry exactly rows 1..27` and `Missing: 27` (the white-box allowlist fails too, because 27
is on it — that second failure is the *accident* ruling 12 replaced, not the mechanism). Revert.

**Append a row after the terminator.** Add
a row shaped like any other — id 28, a resolving citation, `owed: 2a-4` — immediately **below** the
`<!-- end of matrix -->` line. Expected: every check fails with `looks like a matrix row but sits
BELOW the "<!-- end of matrix -->" line`, quoting it. **Record it** — before this, that row was simply
invisible: twenty-seven rows parsed and every check was green. Revert.

**Move the terminator above the white-box block.** Expected: every check fails, naming row 26 as a
row below the terminator. Revert.

Then the two controls, which matter as much as the mutations — a check that fires on a correct edit
is worse than no check:

- **Add row 28 properly** at the end of the `owed by 2a-4` block — in the *middle* of the table, which
  is where a new row belongs — and raise `HIGHEST_ROW_ID` to 28. Expected: **all seven pass**, and the
  printed line reads `28 rows — 5 pinned, 21 owed, 2 white-box-only`. This is why ruling 12 rejected
  "the last row carries the highest id": that rule would have failed this correct edit.
- **The same edit without raising `HIGHEST_ROW_ID`.** Expected: only `the parity matrix parses` fails,
  with `Above HIGHEST_ROW_ID: 28 — adding a row is a deliberate edit in two places`.

Revert both; `git diff --stat` must be empty for the matrix and for `parity-matrix.ts`.

- [ ] **Step 6: Record the fourteen mutations in the header comment.**

Append to the block comment at the top of `e2e/tests/guards/parity-matrix.spec.ts`, immediately
before the closing `*/`, using **the messages you actually saw**, not the ones this plan predicts:

```
 * Verified by mutation, all fourteen, each reverted before the next:
 *   1. Renaming the header's `Notes` column to `Note` failed every check with
 *      "has no header row naming the five columns", printing the canonical
 *      header; and adding a SECOND five-column header (a worked example in a
 *      fenced block) failed every check too, with "has 2 lines naming the five
 *      matrix columns (lines 12, 19)" — refused rather than guessed at.
 *   2. Padding one cell (`| 27  |`) failed ONLY the canonical-line check,
 *      naming the line and printing both spellings — the whole reason the
 *      parser tolerates padding instead of dying on it.
 *   3. Moving row 6 out of 2a-4's block into 2a-5's failed ONLY the contiguity
 *      check, printing the owner sequence with 2a-4 in two separate runs.
 *   4. Widening row 27's citation to `server.py:138-99999` failed the citation
 *      check naming row 27 and "<the message you saw>".
 *   5. Misspelling row 11's cited test title failed the pin check, printing
 *      the literal titles that file does declare; adding the misspelling as a
 *      COMMENT in that spec kept it red, which is the whole argument for
 *      parsing over grep.
 *   6. Re-marking row 12 `white-box-only` failed the allowlist check naming
 *      it — the marker cannot be used to make an inconvenient row stop
 *      counting without a stated reason in this file.
 *   7. Deleting a PINNED row (24) failed ONLY the completeness check, with
 *      "Missing: 24". Every other check passes on a table that is simply
 *      shorter, which is why that check exists.
 *   8. A stray prose line mid-table, a row that lost its leading "|", and a
 *      missing "<!-- end of matrix -->" each failed EVERY check, naming the
 *      line. Before the terminator, all three silently ended the table where
 *      they sat and every check below went blind.
 *   9. A second five-column header — a worked example in a fenced block —
 *      failed EVERY check with "has 2 lines naming the five matrix columns",
 *      refused rather than guessed at.
 *  10. "owed: 2a-9" failed ONLY the pin check, listing the five legal PR ids.
 *  11. GATE_1_CLOSED flipped early failed ONLY the Gate 1 check ("cannot
 *      silently reopen"), and pinning every owed row with the flag still false
 *      failed the same check from the other side, telling that PR to flip it.
 *      Both branches, so the one that matters at the end of the phase is not
 *      first exercised by the PR that depends on it.
 *  12. Deleting the HIGHEST row (27) failed completeness with "does not carry
 *      exactly rows 1..27". Derived from the data this passed, because the
 *      maximum moved down with it.
 *  13. A row appended BELOW the terminator, and the terminator moved above the
 *      white-box block, each failed EVERY check naming the offending line.
 *      Before this the appended row was simply invisible.
 *  14. Two controls, both behaving: row 28 added properly mid-table with
 *      HIGHEST_ROW_ID raised passes all seven; the same edit without raising
 *      it fails completeness alone, naming what to do. The first is why
 *      "the last row carries the highest id" was rejected — it would have
 *      failed a correct edit.
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
test(phase2): record the parity guard's fourteen mutation verifications

Every guard in this directory records what it was seen to fail on, because a
guard nobody has watched fail is a guard nobody knows works. Fourteen mutations,
each reverted: a renamed column, a padded cell, an owed row moved out of its
block, an out-of-range citation, a misspelled test title (and the same
misspelling in a comment, which stayed red), a white-box-only marker used to
drop a row from the ratchet, and a row closed in the matrix without being
closed in the guard.

The padding and block mutations each failed exactly one check and left the
other six green — the two properties that keep four concurrent 2a PRs from
conflicting on every merge, and the two a Markdown formatter would otherwise
destroy silently.

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
| `tests/guards/parity-matrix.spec.ts` | `docs/relay-parity-matrix.md` stays machine-readable and stays cheap for six concurrent editors: exactly one table, found by its five column names; row ids unique and running `1..N` with no gaps, so a deleted row is loud; every table line canonical (`\| ` + cells + ` \|`, no padding — several 2a/2b PRs edit this file at once and an aligned column makes every merge conflict on the whole file); every `Source` citation resolving to a real file and a line inside it; every `Pin` a resolvable test symbol / an `owed: <pr>` naming a PR in the guard's vocabulary / `white-box-only` from a `toEqual` allowlist; rows owed by one PR contiguous in file order; and Gate 1 asserted through one `GATE_1_CLOSED` flag. Phase 2's Gate 1 | Renaming the `Notes` column failed every check; padding one cell failed only the canonical-line check, printing both spellings; moving an owed row into another PR's block failed only the contiguity check, printing the owner sequence; deleting a pinned row failed only the completeness check, naming the missing id; a citation widened past end-of-file failed naming the row; a misspelled cited test title failed, and stayed red with the misspelling added as a **comment**; a `white-box-only` marker used to drop a row failed the allowlist |
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

- [ ] **Step 4: Confirm no issue is owed.**

An earlier draft of this plan filed one, carrying the row count, the twelve unowned rows and the four
missing authorize tests. **All three have since landed in the spec** (`3fb8b2bf`, round-6 amendments):
the Gate 1 table now runs 1–27 with rows 26 and 27 present, the collapsed `19-26` is corrected, rows
19/20/23/25 are marked as pinned by no `e2e/tests/` spec, and the eight orphaned rows are assigned.
The one finding still open — that no PR's gate is Gate 1 — is the orchestrator's own spec amendment
(ruling 7), not this PR's to file.

Verify rather than assume, then move on:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-spec
grep -c "24 rows" docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
grep -n "^| 26 \|^| 27 " docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
```

Expected: `0`, and both white-box rows present. **If either answers otherwise, stop and report** —
that means the amendment did not land and the matrix is being written against a spec that still
contradicts it.


- [ ] **Step 5: Confirm the diff is still documentation-only, and commit.**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a1 && git status --short
```

Expected: exactly `CLAUDE.md`, `e2e/COVERAGE.md`, `e2e/README.md`.

Message to `<SCRATCH>/msg-task7.txt`:

```
docs(phase2): the parity matrix in COVERAGE, README and CLAUDE.md

COVERAGE.md's Guards table gets the new guard and the fourteen mutations that
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

Expected: clean tree; `tsc` silent; every guard green, **exactly seven more passing tests than Task 1
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
19-25 one per Phase 1 authorize-matrix principal; 26-27 the two behaviours the
Go relay is deliberately not held to. **5 pinned, 20 owed, 2 white-box-only** —
the guard prints that line on every run rather than the document storing it.

**`e2e/tests/guards/parity-matrix.spec.ts`** — seven checks in the `guards`
project, which needs no container. Exactly one table, found by its five column
names; ids unique and running `1..N` with no gaps, so a deleted row is loud;
every citation resolving to a real file and a line inside it; every pin a
resolvable test symbol (`.spec.ts` titles read through the TypeScript compiler
API, so a title in a comment is not a match), an `owed: <pr>` naming a PR in the
guard's vocabulary, or `white-box-only` from a `toEqual` allowlist; and Gate 1
asserted through one `GATE_1_CLOSED` flag, which the PR closing the last owed
row is told to flip.

**Two of the seven exist because several PRs edit this file at once.** 2a-3,
2a-4, 2a-5, 2a-6 and 2b-3 all fill in test references here, so the format
is built for concurrent editing: one row per line, cells never padded to align
columns (a named check fails the padded line, so a formatter run says what it
did instead of breaking the parse), no stored aggregate, and file order grouped
by owning PR rather than by id, which a second named check enforces. Owed-ness
is read from each row's own Pin cell and there is **no shared list of owed
ids** — closing a row is one line in one file.

**Two lines of wiring, and they matter.** The `guards` CI job was gated on a
path filter with no `docs/` in it, so it could not fire on the one file it
guards — a citation refresh, a Notes correction, 2c-9's Go re-pointing of the
whole column would all have skipped it. `docs/relay-parity-matrix.md` joins
`e2e-tests.yml`'s `push` `paths:` and the `changes` job's pattern (zizmor still
zero findings), and `.claude/hooks/run-affected-tests.sh` gains a case so
editing the matrix runs the guard locally too.

Verified by mutation, eight times, each reverted; the spec file's header records
what each one printed.

**Written to the spec's round-6 amendments** (`3fb8b2bf`), which absorbed
the three findings an earlier draft of this PR reported: the Gate 1 table now
runs 1-27 with both white-box rows, the collapsed `19-26` is corrected, and the
eight rows no PR owned are assigned to 2a-5 with a per-row gate clause. Rows
19, 20, 23 and 25 are recorded as owed because **four of the seven authorize
principals have no test anywhere in `e2e/`** — the Internal principal, the Admin
bypass, an ordinary Session and stream-by-hash. `authorize-matrix.spec.ts` is
organised by surface x filter and covers XC, JWT and Anonymous only. That is a
Phase 1 coverage gap; the matrix records it rather than papering over it.

One finding stays open and is not this PR's to close: **no PR's gate is Gate 1**,
and because row 18 can only close in 2b-3, 2b-3 is the only PR that can own it.
The guard's `GATE_1_CLOSED` flag is written so that whichever PR closes the last
owed row is told, by a failing assertion, to flip it in the same commit.

No product code. No new dependency. No `metrics/` change — the spec puts this
phase's `metrics/curated/` work in `migration/phase2d-docs`, and none of
`CLAUDE.md`'s four triggers fires here.

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

**No divergence from the spec remains.** Three findings this plan reported — the row count
(ruling 6), the eight rows no PR owned (ruling 7) and the four authorize principals with no test
(ruling 13) — all landed in the spec's round-6 amendments at `3fb8b2bf`, and the matrix is written to
those. One finding stays open and is the orchestrator's to close, not this PR's: no PR's gate is
Gate 1, and row 18 makes 2b-3 the only candidate (ruling 7).

**Revised twice after the first draft.**

*Round 1*, when the orchestrator supplied a constraint the spec does not carry: 2a-3 through 2a-6 are
stacked PRs developed in parallel, so four of them edit `docs/relay-parity-matrix.md` concurrently.
That produced ruling 11 and two of the guard's checks (canonical lines, owner contiguity), removed
the ascending-id requirement in favour of block order, made the header match on column names rather
than on the literal line, and moved the row counts out of the document into the guard's printed
output.

*Round 2*, against review. Four blocking findings, all verified against the tree before applying:
the id set was unasserted so a row could be deleted in silence (ruling 12); `OWED` put every PR's
deletions on one shared line and so defeated ruling 11 at the second file (ruling 5 deletes the list
outright); four of the seven authorize principals turn out to have no test at all, moving the owed
count from sixteen to twenty (ruling 13); and the `guards` CI job was gated on a path filter with no
`docs/` in it, so it could not fire on the file it guards (ruling 9, plus the local edit hook, which
matched no Markdown file either). Five majors followed: the header parse took the first of several
matches (now refuses to choose), a multi-line HTML comment truncated the table silently (now tracked
across lines), the `Pin` cell admitted one reference where five of the matrix's own rows are
two-sided (now a list), and ruling 7's conclusion conflicted with 2a-5's own gate as it then stood.

**Two review findings were checked and rejected, with evidence:**

- *"`CLAUDE.md` § Observing a channel is wrong about `ffmpeg_speed`"* — it is not, on this branch.
  `CLAUDE.md:83` reads "`ffmpeg_speed` is a **float on both endpoints** … `source_fps` still
  disagrees", which is exactly what row 14 says and exactly what the tree does. The review quoted the
  pre-Phase-1-PR-7 text. Task 7 step 3's "this PR alters no fact `CLAUDE.md` states" stands.
- *"the plan's project enumerations omit `streaming-split`"* — the plan enumerates no Playwright
  projects anywhere. Nothing to correct. (The reviewer withdrew both findings, confirming it had
  quoted a `CLAUDE.md` from its own session context that predates Phase 1 PR 7 rather than grepping
  the worktree.)

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

**Re-prototyped after ruling 11 was added**, this time against a full twenty-seven-row table with
the block layout as it stood at that round — sixteen owed rows, nine pinned, two white-box. All seven
checks passed on it and the count line printed accordingly. (Ruling 13 later corrected those numbers
to 5 / 20 / 2; the round-three prototype below is the one run against the shape this plan actually
ships.) Three mutations were run:

- Padding one cell (`| 27  |`) failed **only** check 2, naming
  `docs/relay-parity-matrix.md:39` and printing both the padded line and its canonical spelling.
- Moving row 12 from 2a-4's block into 2a-3's failed **only** check 7, printing the owner sequence
  it read from the file with `2a-4` appearing twice, and the owed rows in file order.
- Closing row 8 — the *middle* of 2a-3's block — by pinning it to a real test kept all seven green
  and the printed count moved by one. That is the design claim ruling 11d makes (a partially-closed
  block does not break contiguity), checked rather than asserted.

- **A second design bug was found and fixed**: renaming a column made six checks fail and
  `canonicalLineOffenders` **pass**, because it returned `[]` when it could not find the table — the
  "silently skips a shape it cannot read" hole `ast.ts`'s own header warns about. It now throws, and
  the renamed-column mutation fails all seven.

**Re-prototyped a third time after the review round**, against a twenty-seven-row table in the new
eight-block layout, with two multi-line HTML comments inside the table and one row carrying a
two-reference pin. All seven checks pass and the printed line reads exactly
`parity matrix: 27 rows — 5 pinned, 20 owed, 2 white-box-only`, which is what the Done criteria
claim. Five more mutations, all reverted:

- Deleting **pinned** row 24 failed **only** `the parity matrix parses`, with `Missing: 24`. Before
  ruling 12 that table passed every check.
- Adding a second five-column header in a fenced example failed **all seven**, with
  `has 2 lines naming the five matrix columns (lines 12, 19)`. Before M1's fix the parser took the
  first match — the example — and enforced nothing about the real table.
- `owed: 9z-9` failed **only** `every pin resolves`, naming row 17 and listing the six legal PR ids.
- Pinning every owed row with `GATE_1_CLOSED` still `false` failed **only** the Gate 1 check, with
  "No row is owed any more — you just closed the last one. Flip GATE_1_CLOSED to true".
- Setting `GATE_1_CLOSED = true` with rows still owed failed the same check from the other side:
  "Gate 1 … cannot silently reopen".

The two multi-line comments are themselves the M2 regression check: all twenty-seven rows parse
through them, where the single-line-only rule truncated the table at the first one.

**Re-prototyped a fourth time after the second review round**, against the nine-block layout with
row 12 in its own 2a-6 block, an explicit `<!-- end of matrix -->` terminator and prose after it. All
seven checks pass, printing `parity matrix: 27 rows — 5 pinned, 20 owed, 2 white-box-only`. What the
new shared walker buys, measured:

- A stray prose line mid-table, and a row that lost its leading `|`, each fail **all seven** checks
  naming the line and quoting it (`docs/relay-parity-matrix.md:23 ends the table before its
  "<!-- end of matrix -->" line: "A note about the block below."`). Before the terminator, both
  silently ended the table where they sat.
- **The blindness case is closed**: a padded row *below* a stray line used to be reported by nobody —
  the parse stopped, the padding walker stopped at the same place, and the run was green on that
  count. It now fails all seven, naming the stray line.
- Deleting the terminator fails everything too.
- Moving row 6 out of 2a-4's block into another PR's fails **only** the contiguity check, printing
  the owner sequence with `2a-4` in two separate runs.
- Deleting **pinned** row 24 fails **only** the completeness check, with `Missing: 24`.

**The adjacent-line claim was measured, not taken on trust**, in a throwaway git repo: two edits one
line apart conflict; two lines apart merge cleanly. That holds for modify-vs-modify (`CONFLICT` at
distance 0 and 1, `CLEAN` at 2 and 3), modify-vs-delete and delete-vs-delete. Since ruling 5 made
closing a row a *modify*, the modify-vs-modify row is the one that matters, and it is why the
`<!-- block: -->` marker lines are recorded as load-bearing rather than decorative.

**Re-prototyped a fifth time, against the ruled layout** — seven blocks, rows 14-17 and 19/20/23/25
on 2a-5, row 12 on 2a-6, row 18 on 2b-3, `PRS` five ids — then deleted. All seven checks pass and
print `parity matrix: 27 rows — 5 pinned, 20 owed, 2 white-box-only`. The three assertions review 2
found unexercised were run against it and each fails alone: `owed: 2a-9` names the five legal ids;
`GATE_1_CLOSED` true with rows owed fails "cannot silently reopen"; every row pinned with the flag
still false fails "Flip GATE_1_CLOSED to true". The mixed-form Pin cell
(`` `…::title` and owed: 2b-3 ``) is now rejected as none of the three legal forms, and the
legitimate two-reference cell still resolves.

**Re-prototyped a sixth time, with the tail anchored** — `HIGHEST_ROW_ID` replacing the derived
maximum, and `scanTable` refusing any matrix-shaped line below the terminator. Baseline green,
printing `27 rows — 5 pinned, 20 owed, 2 white-box-only`. The three previously-silent tail holes each
fail now: deleting row 27 fails completeness by name; a row appended below the terminator fails every
check quoting it; an early terminator above the white-box block does the same. **Both controls pass
too**, which is the half that decided the design — row 28 added properly *mid-table* with the bound
raised is green on all seven, and the same edit without raising it fails completeness alone. The
rejected candidate ("the last row carries the highest id") would have failed that first control,
which is the empirical reason it was rejected rather than an argued one.

**The Prettier ignore scoping was measured, not assumed** (Task 2 steps 9b/9c). Prettier resolves
`--ignore-path` relative to the working directory, so a repo-root `.prettierignore` protects the
matrix when Prettier runs from the root and **does nothing** when it runs from `frontend/` — which is
exactly where `CLAUDE.md:36` says to run it. Hence two files. Neither changes the frontend tree:
`prettier --check 'src/**/*.jsx'` reports 54 files with and without both, the same file list.

Task 6's mutation work is still owed in full — the prototype proved the checks fire on a synthetic
table; Task 6 proves they fire on the real document, and its recorded messages are what
`e2e/COVERAGE.md` cites.
