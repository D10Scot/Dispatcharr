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
 *
 * Verified by mutation, all fourteen, each reverted before the next:
 *   1. Renaming the header's `Notes` column to `Note` failed every check with
 *      "has no header row naming the five columns", printing the canonical
 *      header; and adding a SECOND five-column header (a worked example in a
 *      fenced block) failed every check too, with "has 2 lines naming the five
 *      matrix columns (lines 97, 155)" — refused rather than guessed at.
 *   2. Padding one cell (`| 27  |`) failed ONLY the canonical-line check,
 *      naming the line and printing both spellings — the whole reason the
 *      parser tolerates padding instead of dying on it.
 *   3. Moving row 6 out of 2a-4's block into 2a-5's failed ONLY the contiguity
 *      check, printing the owner sequence with 2a-4 in two separate runs
 *      ("2a-4 → 2a-3 → 2a-6 → 2a-5 → 2a-4 → 2b-3").
 *   4. Widening row 27's citation to `server.py:138-99999` failed the citation
 *      check naming row 27 and "runs past the end of the file, which has 2570
 *      lines".
 *   5. Misspelling row 11's cited test title failed the pin check, printing
 *      the literal titles that file does declare; adding the misspelling as a
 *      COMMENT in that spec kept it red, which is the whole argument for
 *      parsing over grep.
 *   6. Re-marking row 12 `white-box-only` failed the allowlist check, reporting
 *      [12, 26, 27] against [26, 27] — the marker cannot be used to make an
 *      inconvenient row stop counting without a stated reason in this file.
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
 *  10. "owed: 2a-9" failed ONLY the pin check, listing the five legal PR ids
 *      (2a-3, 2a-4, 2a-5, 2a-6, 2b-3).
 *  11. GATE_1_CLOSED flipped early failed ONLY the Gate 1 check ("cannot
 *      silently reopen"), and pinning every owed row with the flag still false
 *      failed the same check from the other side ("you just closed the last
 *      one. Flip GATE_1_CLOSED to true"), telling that PR to flip it. Both
 *      branches, so the one that matters at the end of the phase is not first
 *      exercised by the PR that depends on it.
 *  12. Deleting the HIGHEST row (27) failed completeness with "does not carry
 *      exactly rows 1..27" and "Missing: 27" — and the white-box allowlist
 *      check failed too, because 27 is on it. That second failure is the
 *      accident ruling 12 replaced, not the mechanism: derived from the data
 *      this deletion would have passed, because the maximum moved down with
 *      it.
 *  13. A row appended BELOW the terminator, and the terminator moved above the
 *      white-box block, each failed EVERY check naming the offending line.
 *      Before this the appended row was simply invisible.
 *  14. Two controls, both behaving: row 28 added properly mid-table with
 *      HIGHEST_ROW_ID raised to 28 passes all seven, printing "28 rows — 5
 *      pinned, 21 owed, 2 white-box-only"; the same edit without raising it
 *      fails completeness alone, with "Above HIGHEST_ROW_ID: 28 — adding a
 *      row is a deliberate edit in two places". The first is why "the last
 *      row carries the highest id" was rejected — it would have failed a
 *      correct edit.
 */
import { test, expect } from '@playwright/test';
import {
  canonicalLineOffenders,
  citationProblem,
  citationsIn,
  GATE_1_CLOSED,
  HIGHEST_ROW_ID,
  MATRIX_REL,
  parseMatrix,
  parsePin,
  PRS,
  readMatrix,
  WHITE_BOX_ONLY,
  testRefProblem,
} from './parity-matrix';

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
  // retired IN PLACE, keeping its id — so the id set is exactly
  // 1..HIGHEST_ROW_ID, and a gap means a row was deleted. Without this a pinned
  // row can be dropped in silence: every other check has nothing left to
  // complain about.
  //
  // Bounded rather than derived, in both directions: `1..max(ids)` is satisfied
  // by deleting the HIGHEST row, because the maximum moves down with it.
  // HIGHEST_ROW_ID is a stored number and ruling 12 says why that is the right
  // kind — it lives beside WHITE_BOX_ONLY and PRS, not in the contended
  // document, and no PR edits it to close a row.
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
    'Rows owed by one PR must be contiguous in file order. Five PRs close rows in this table ' +
      'and three of them run in parallel; interleaving their rows interleaves their diffs and ' +
      'turns every '  +
      'merge into a conflict. Order in the file is by owning block, NOT by id — do not sort ' +
      `this table. Owner sequence read from the file: ${runs.join(' → ')}. Rows, in file ` +
      `order: ${owners.map((o) => `${o.id}(${o.pr})`).join(', ')}.`,
  ).toEqual([]);
});
