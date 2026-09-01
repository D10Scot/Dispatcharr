/**
 * Enforces that every `test()` under `e2e/tests/frontend/` destructures
 * `pageErrors`, following the precedent at
 * `e2e/tests/streaming-greybox/quarantine.spec.ts`: "a convention written
 * down in a file would rot silently; this one fails CI instead".
 *
 * Why this has to be a source scan, not a runtime check. `fixtures/index.ts`'s
 * `pageErrors` fixture has no `auto: true` (deliberately — see below), so
 * Playwright only *constructs* the collector, and only runs its automatic
 * `expectClean()` teardown, for a test that names `pageErrors` in its
 * destructured parameter. A test that never names it doesn't fail an
 * assertion or get a waiver recorded — the collector simply never exists for
 * that test, and a console error or a >=400 response during its run passes
 * completely unseen. Nothing at runtime can catch a fixture nobody asked for;
 * only reading the test's own parameter list, before it runs, can.
 *
 * Why not `auto: true` on the fixture instead. That would make this file
 * unnecessary for `tests/frontend/`, but `fixtures/index.ts` is shared with
 * G6's sibling goals, whose specs are API-only (`api`/`seed`, no `page` at
 * all) — forcing every one of those tests to also construct a
 * `PageErrorCollector` bound to a `page` they never open would be a
 * behaviour change to fixtures those goals own, not a decision this task
 * gets to make unilaterally. Scoping the enforcement to this directory, in
 * this directory's own file, keeps the blast radius to G6.
 *
 * Fails closed, not open. The first version of this checker only recognised
 * one shape — `test('name', async ({ … }) => { … })` — and silently skipped
 * anything else: a named helper (`test('name', someHelper)`), a call with no
 * inline function at all, a first parameter that isn't a destructured object
 * pattern. That is the exact defect this file exists to close, one level up:
 * the original hole was Playwright silently skipping a fixture nobody named;
 * a checker that silently skips a *shape it cannot read* has the same blind
 * spot with the same consequence — a spec's page-error coverage goes
 * unverified and nothing says so. So every `test()` call this file finds is
 * put into exactly one of three buckets: verified clean, verified missing
 * `pageErrors`, or **unverifiable** — and the last of those fails the check
 * too, naming the shape it couldn't read, rather than passing through it,
 * unless the exact location is pinned in `KNOWN_UNVERIFIABLE` with a reason.
 *
 * Moved here from `tests/frontend/` and refactored onto `./ast`, which now
 * owns the walker this file originated. Verified by mutation after the move:
 * adding an untagged `test('…', async ({ page }) => …)` to
 * `tests/frontend/stats.spec.ts` failed the check naming that file and line;
 * reverting it passed again. The rule and its verdicts are unchanged — only
 * where the walker lives.
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { E2E_ROOT, findTestCalls, listSpecFiles, readSpec } from './ast';

// The directory whose rule this file enforces. It is no longer the directory
// this file lives in — the checker moved to `tests/guards/` (no page, no
// container, so it belongs with the other static-analysis specs) while the
// rule it enforces stayed put.
const TARGET_DIR = 'tests/frontend';

// No self-exclusion any more: this checker used to live in the directory it
// scans and had to skip its own file. Moving it to `tests/guards/` removed
// the need — the scanned directory and the scanning file are now disjoint.

// `isTestCallee` and the lifecycle-hook exclusions moved to `./ast`, shared
// with the other guards in this directory — three of them were about to
// re-derive "what is a test declaration" and drift from each other and from
// this file, which got there first.
//
// What stays here is `judge()`, which is specific to this rule. Note that
// being *judged* rather than exempted does not mean every `test.<prop>(...)`
// shares `test(...)`'s `(name, fn)` shape: `test.use({...})`,
// `test.setTimeout(n)`, `test.slow()`, `test.step(name, fn)` and the
// two-argument `test.skip(cond, 'reason')` form take no inline test callback,
// and `test.describe(name, fn)`'s callback takes no fixture parameter to
// destructure — `judge()` reads none of these as `'ok'`. None are used under
// `tests/frontend/` today, so this is latent, but it fails *loud*: such a call
// is reported `'unverifiable'` rather than silently passed, the same
// fail-closed outcome as any other unreadable shape.

type CallVerdict =
  | { kind: 'ok' }
  | { kind: 'missing' }
  | { kind: 'unverifiable'; reason: string };

/**
 * Judges one `test()` call's final argument (the test body). Returns
 * `'ok'` only when the shape is one this checker can actually read *and*
 * that reading finds `pageErrors` bound. Every other case — including every
 * shape this checker doesn't recognise — is `'unverifiable'` or `'missing'`,
 * never silently passed.
 */
function judge(callArgs: readonly ts.Expression[]): CallVerdict {
  const fn = callArgs[callArgs.length - 1];

  if (!fn) {
    return { kind: 'unverifiable', reason: 'test() call has no callback argument to inspect' };
  }

  if (!ts.isArrowFunction(fn) && !ts.isFunctionExpression(fn)) {
    // `test('name', someHelper)`, `test('name', factory())`, a spread, etc.
    // — the callback isn't written inline, so there is no parameter list
    // here at all to read; it may destructure `pageErrors` in its own
    // definition elsewhere, or may not, and this checker cannot tell either
    // way from this call site.
    return {
      kind: 'unverifiable',
      reason: `test callback is not an inline function this checker can read (found ${ts.SyntaxKind[fn.kind]}) — inline it, or add explicit support for this shape in pageerrors-enforcement.spec.ts`,
    };
  }

  const param = fn.parameters[0];
  if (!param) {
    // Zero fixtures named at all. Could legitimately be a test that opens no
    // page (nothing for pageErrors to watch) — or could be an oversight.
    // This checker cannot distinguish those, so it does not guess either way.
    return {
      kind: 'unverifiable',
      reason:
        'test callback destructures no fixtures at all — if it never opens a page, ' +
        'pin this location in KNOWN_UNVERIFIABLE with a reason (a whole-file exclusion is ' +
        'not available per-test, and a sibling test in the same file may still ' +
        'open a page and need checking); if it does, name `pageErrors`',
    };
  }

  if (!ts.isObjectBindingPattern(param.name)) {
    // e.g. `async (fixtures) => { … fixtures.pageErrors … }` — a bare
    // identifier or array pattern. `pageErrors` might be used through it,
    // but not by a name this checker can see in the parameter list.
    return {
      kind: 'unverifiable',
      reason: `test callback's first parameter isn't a destructured {…} object pattern this checker can read (found ${ts.SyntaxKind[param.name.kind]})`,
    };
  }

  const hasRest = param.name.elements.some((el) => el.dotDotDotToken);
  const names = param.name.elements.map((el) =>
    (ts.isIdentifier(el.propertyName ?? el.name)
      ? (el.propertyName ?? el.name)
      : el.name
    ).getText()
  );

  if (names.includes('pageErrors')) return { kind: 'ok' };

  if (hasRest) {
    // `{ adminPage, ...rest }` — `pageErrors` isn't bound by that name, but
    // could still be reached as `rest.pageErrors` in the body. Not a shape
    // this checker can rule either way on.
    return {
      kind: 'unverifiable',
      reason:
        "test callback's parameter pattern includes a rest element (`...`) without naming " +
        '`pageErrors` directly — it may still be reachable through the rest binding, which ' +
        'this checker does not follow into the function body',
    };
  }

  return { kind: 'missing' };
}

type Offense = { file: string; line: number; verdict: 'missing' | 'unverifiable'; reason?: string };

function findOffenses(src: string, fileName: string): Offense[] {
  const offenses: Offense[] = [];
  for (const call of findTestCalls(src, fileName)) {
    const verdict = judge(call.args);
    if (verdict.kind !== 'ok') {
      offenses.push({
        file: fileName,
        line: call.line,
        verdict: verdict.kind,
        reason: verdict.kind === 'unverifiable' ? verdict.reason : undefined,
      });
    }
  }
  return offenses;
}

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, import specifiers, allowlist
// membership. None of it is client-observable behaviour, and all of it changes
// shape when the suite is restructured. See docs/adr/0002-e2e-test-taxonomy.md.
test('every test() under tests/frontend/ destructures pageErrors', { tag: '@characterization' }, async () => {
  // `listSpecFiles` sorts, and that matters: `readdir` returns filesystem
  // order, which is not alphabetical on every platform and is not stable
  // across runs. `KNOWN_UNVERIFIABLE` below is a hand-written,
  // alphabetically-sorted list compared with `.toEqual` — an unsorted listing
  // would flake on directory order rather than on a real change to the
  // unverifiable set.
  //
  // Relative paths are trimmed back to basenames so `KNOWN_UNVERIFIABLE`
  // keeps naming files the way it always has, unaffected by this checker
  // moving directories.
  const specFiles = await listSpecFiles(path.join(E2E_ROOT, TARGET_DIR), TARGET_DIR);

  const offenses: Offense[] = [];
  for (const rel of specFiles) {
    offenses.push(...findOffenses(await readSpec(rel), path.basename(rel)));
  }

  // Partition on the structured `verdict` field, not on the rendered English
  // below — `summary` (all offenses, for the failure messages) and the two
  // per-verdict arrays used in the assertions are both built from `offenses`
  // directly, so a `missing` template that happened to contain the word
  // "UNVERIFIABLE" could never misbucket into the wrong list.
  const missingOffenses = offenses.filter((o) => o.verdict === 'missing');
  const unverifiableOffenses = offenses.filter((o) => o.verdict === 'unverifiable');

  const summary = offenses.map((o) =>
    o.verdict === 'missing'
      ? `${o.file}:${o.line} — does not destructure pageErrors`
      : `${o.file}:${o.line} — UNVERIFIABLE: ${o.reason}`
  );

  // Two assertions, not one, because `missing` and `unverifiable` mean
  // different things and must fail differently.
  //
  // `missing` is the real enforcement and is absolute: a test that opens a
  // page without naming `pageErrors` gets no teardown check, and no list may
  // ever excuse one.
  //
  // `unverifiable` means the checker could not read the test's shape. That is
  // deliberately not silent — an unreadable shape is a hole until someone
  // looks at it — but one entry is genuinely unreadable *and* genuinely fine,
  // so it is pinned here rather than excused by widening `judge()` (which
  // would blind the checker to that whole shape) or by excluding the file
  // (`SELF_FILE` is whole-file, and plugins.spec.ts's other test does open a
  // page and must stay checked).
  //
  // Pinning keeps this fail-closed: a NEW unreadable shape is not in the list
  // and still fails. Removing a fixed entry also fails, which is correct — the
  // list is only as true as its last edit. **Add an entry deliberately, with a
  // reason, and never merely to make the suite green.**
  //
  // Pinned by `file:line` only, not the rendered reason text — the reason
  // string duplicates, verbatim, the `reason:` literal in judge()'s
  // zero-parameter branch (`if (!param) { … }` above, the "Zero fixtures
  // named at all" case), so pinning the full message would break this list
  // on a wording-only change to that literal, or on an unrelated import
  // shifting plugins.spec.ts's line numbers. (An earlier version of this
  // comment cited that literal by line number — `:114-117` — which was
  // already wrong when written: at the commit that introduced it, those
  // lines were a closing brace, a blank line and the two statements that
  // now read `const param = fn.parameters[0]; if (!param) {`, not the
  // reason string. Named by symbol here instead, per this repo's own
  // citation rule, so a future line shift can't repeat that mistake.) The
  // point of the pin is that a change to the *set* of
  // unverifiable locations is loud, not that a change to the *wording* is.
  const KNOWN_UNVERIFIABLE = [
    // plugins.spec.ts's first test is the synchronous zip-builder unit test.
    // It takes no fixtures because it opens no page and does no I/O — it calls
    // buildPluginZip() and asserts on the returned Buffer — so `pageErrors`
    // would have nothing to observe.
    'plugins.spec.ts:15',
  ];

  expect(
    missingOffenses.map((o) => `${o.file}:${o.line}`),
    'A test() call under e2e/tests/frontend/ opens a page without naming the ' +
      '`pageErrors` fixture, so no error check runs for it. Playwright only ' +
      'constructs the fixture (and its automatic expectClean() teardown — no ' +
      '`auto: true`, see fixtures/index.ts) for a test that names it. Add ' +
      '`pageErrors` to the destructured fixture parameter; see render.spec.ts, ' +
      'guide.spec.ts, users.spec.ts or settings.spec.ts for the pattern. ' +
      `Details — ${summary.join(' | ')}`
  ).toEqual([]);

  expect(
    unverifiableOffenses.map((o) => `${o.file}:${o.line}`),
    'One or more test() calls under e2e/tests/frontend/ failed the pageErrors ' +
      'check. Playwright only constructs the `pageErrors` fixture (and runs its ' +
      "automatic expectClean() teardown — no `auto: true`, see fixtures/index.ts) " +
      "for a test that names it. Entries marked \"does not destructure pageErrors\" " +
      'need `pageErrors` added to the destructured fixture parameter (see ' +
      'render.spec.ts, guide.spec.ts, users.spec.ts or settings.spec.ts for the ' +
      'pattern). Entries marked UNVERIFIABLE use a shape this checker cannot read ' +
      "at all — inline the test callback as a plain async arrow function " +
      'destructuring `{ …, pageErrors }`, or extend `judge()` in ' +
      'pageerrors-enforcement.spec.ts to understand the new shape explicitly. ' +
      'If it is genuinely unreadable and genuinely safe, add its `file:line` to ' +
      'KNOWN_UNVERIFIABLE above with a reason. ' +
      `Details — ${summary.join(' | ')}`
  ).toEqual(KNOWN_UNVERIFIABLE);
});
