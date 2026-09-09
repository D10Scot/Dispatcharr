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
import {
  canonicalLineOffenders,
  citationProblem,
  citationsIn,
  MATRIX_REL,
  parseMatrix,
  parsePin,
  PRS,
  readMatrix,
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

  // Ruling 12's id-completeness assertion belongs here and is added in Task 5,
  // once HIGHEST_ROW_ID exists and the table actually holds rows 1..27. It
  // cannot live here yet: this task's document has three worked rows (11, 14,
  // 27), and no value of HIGHEST_ROW_ID makes that set equal 1..N.

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
