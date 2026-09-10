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
import * as ts from 'typescript';
import { findTestCalls, REPO_ROOT } from './ast';

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
export const HIGHEST_ROW_ID = 29;

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
