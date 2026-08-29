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
 */
import { test, expect } from '@playwright/test';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import * as ts from 'typescript';

// This file's own basename, excluded from the scan below: it has no `page`
// to watch and no business destructuring `pageErrors` itself — the same
// self-exclusion `quarantine.spec.ts` applies to its own `SELF_PATH`.
const SELF_FILE = path.basename(__filename);

function isTestCallee(expr: ts.Expression): boolean {
  // `test(...)`
  if (ts.isIdentifier(expr) && expr.text === 'test') return true;
  // `test.only(...)`, `test.skip(...)`, etc. — same `(name, fn)` shape.
  if (
    ts.isPropertyAccessExpression(expr) &&
    ts.isIdentifier(expr.expression) &&
    expr.expression.text === 'test'
  ) {
    return true;
  }
  return false;
}

/**
 * For one `test(...)` call's final argument (the test body), the names bound
 * by its first parameter's destructuring — `[]` if that parameter isn't an
 * object pattern at all (e.g. a test that takes no fixtures).
 */
function destructuredFixtureNames(fn: ts.ArrowFunction | ts.FunctionExpression): string[] {
  const param = fn.parameters[0];
  if (!param || !ts.isObjectBindingPattern(param.name)) return [];
  return param.name.elements.map((el) =>
    (ts.isIdentifier(el.propertyName ?? el.name) ? (el.propertyName ?? el.name) : el.name).getText()
  );
}

/** 1-based source lines of every `test()` call in `src` that omits `pageErrors`. */
function findOffendingLines(src: string, fileName: string): number[] {
  const sourceFile = ts.createSourceFile(fileName, src, ts.ScriptTarget.Latest, true);
  const offending: number[] = [];

  function visit(node: ts.Node): void {
    if (ts.isCallExpression(node) && isTestCallee(node.expression)) {
      const fn = node.arguments[node.arguments.length - 1];
      if (fn && (ts.isArrowFunction(fn) || ts.isFunctionExpression(fn))) {
        if (!destructuredFixtureNames(fn).includes('pageErrors')) {
          const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
          offending.push(line + 1);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return offending;
}

test('every test() under tests/frontend/ destructures pageErrors', async () => {
  const dir = path.resolve(__dirname);
  const specFiles = (await readdir(dir)).filter(
    (name) => name.endsWith('.spec.ts') && name !== SELF_FILE
  );

  const offenders: string[] = [];
  for (const file of specFiles) {
    const src = await readFile(path.join(dir, file), 'utf8');
    const lines = findOffendingLines(src, file);
    if (lines.length > 0) offenders.push(`${file}:${lines.join(',')}`);
  }

  expect(
    offenders,
    'One or more test() calls under e2e/tests/frontend/ do not destructure ' +
      '`pageErrors` from the fixtures. Playwright only constructs a fixture a ' +
      "test names — with no `auto: true` on `pageErrors` (fixtures/index.ts), " +
      "the collector's automatic expectClean() teardown never runs for a test " +
      'that never names it, so console errors and >=400 responses during that ' +
      "test pass unseen. Fix: add `pageErrors` to the offending test's " +
      'destructured fixture parameter (see any of render.spec.ts, ' +
      'guide.spec.ts, users.spec.ts, settings.spec.ts for the pattern). ' +
      `Offending file:line — ${offenders.join('; ')}`
  ).toEqual([]);
});
