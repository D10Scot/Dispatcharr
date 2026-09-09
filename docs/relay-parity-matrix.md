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
