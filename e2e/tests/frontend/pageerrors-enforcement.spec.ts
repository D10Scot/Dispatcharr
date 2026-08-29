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
 * too, naming the shape it couldn't read, rather than passing through it.
 */
import { test, expect } from '@playwright/test';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import * as ts from 'typescript';

// This file's own basename, excluded from the scan below: it has no `page`
// to watch and no business destructuring `pageErrors` itself — the same
// self-exclusion `quarantine.spec.ts` applies to its own `SELF_PATH`.
const SELF_FILE = path.basename(__filename);

// Lifecycle hooks share `test`'s namespace but declare a setup/teardown step,
// not a test body — Playwright's automatic `pageErrors.expectClean()`
// teardown fires once per *test*, keyed to that test's own fixture
// instances, so a hook is never the thing it runs against and has no
// obligation to destructure it (`test.afterEach(async ({ api }, testInfo) =>
// …)` in backups.spec.ts and plugins.spec.ts is exactly this shape). Excluding
// exactly these four names is deliberate and minimal, not a retreat from the
// fail-closed rule above: every *other* `test.<prop>(...)` call — `.only`,
// `.skip`, `.fixme`, `.fail`, `.describe`, anything not in this set — still
// shares `test(...)`'s `(name, fn)` shape and is still judged below.
const TEST_HOOK_NAMES = new Set(['beforeEach', 'afterEach', 'beforeAll', 'afterAll']);

function isTestCallee(expr: ts.Expression): boolean {
  // `test(...)`
  if (ts.isIdentifier(expr) && expr.text === 'test') return true;
  // `test.only(...)`, `test.skip(...)`, etc. — same `(name, fn)` shape.
  if (
    ts.isPropertyAccessExpression(expr) &&
    ts.isIdentifier(expr.expression) &&
    expr.expression.text === 'test' &&
    !TEST_HOOK_NAMES.has(expr.name.text)
  ) {
    return true;
  }
  return false;
}

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
        'exclude this file from the scan explicitly (see SELF_FILE); if it does, name `pageErrors`',
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
  const sourceFile = ts.createSourceFile(fileName, src, ts.ScriptTarget.Latest, true);
  const offenses: Offense[] = [];

  function visit(node: ts.Node): void {
    if (ts.isCallExpression(node) && isTestCallee(node.expression)) {
      const verdict = judge(node.arguments);
      if (verdict.kind !== 'ok') {
        const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
        offenses.push({
          file: fileName,
          line: line + 1,
          verdict: verdict.kind,
          reason: verdict.kind === 'unverifiable' ? verdict.reason : undefined,
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return offenses;
}

test('every test() under tests/frontend/ destructures pageErrors', async () => {
  const dir = path.resolve(__dirname);
  const specFiles = (await readdir(dir)).filter(
    (name) => name.endsWith('.spec.ts') && name !== SELF_FILE
  );

  const offenses: Offense[] = [];
  for (const file of specFiles) {
    const src = await readFile(path.join(dir, file), 'utf8');
    offenses.push(...findOffenses(src, file));
  }

  const summary = offenses.map((o) =>
    o.verdict === 'missing'
      ? `${o.file}:${o.line} — does not destructure pageErrors`
      : `${o.file}:${o.line} — UNVERIFIABLE: ${o.reason}`
  );

  expect(
    summary,
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
      `Details — ${summary.join(' | ')}`
  ).toEqual([]);
});
