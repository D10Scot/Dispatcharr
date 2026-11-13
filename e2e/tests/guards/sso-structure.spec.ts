/**
 * The `sso` project's two load-bearing conventions, as assertions (SSO spec PR S5, review
 * round 1).
 *
 * 1. `assertScopedStack()` runs before anything else in every file the `sso-setup` and
 *    `sso` projects load. It is the only barrier between these specs and ADR 0001's
 *    shared container, where switching password login off would lock every other project
 *    out. `sso-scope.spec.ts` pins what the function refuses; this pins that it is
 *    called, and called first.
 *
 *    Enforced here by a scan of the directory rather than structurally through
 *    `tests/sso/fixtures.ts`, because the scan cannot be bypassed by accident: it reads
 *    every file Playwright would load for the two projects, whatever that file imports,
 *    and fails naming it. A fixture would hold only the files that import it (a second
 *    guard would have to hold the import), and Playwright runs a `beforeAll` before any
 *    test-scoped fixture, so only a worker-scoped `auto` fixture would precede a
 *    mutating `beforeAll`, which is ordering nobody can see in the spec. The scan also
 *    holds `sso.setup.ts`, which imports `test` from `@playwright/test` directly.
 *
 *    The rule, per file: it imports `assertScopedStack` from `tests/sso/scope.ts`; it
 *    has no top-level `await`; and its first call on the `test` binding, in source
 *    order, is a top-level statement whose callback's first statement is
 *    `assertScopedStack()` with no argument (which reads `process.env` and nothing an
 *    author could hand it). In a spec that call is a `test.beforeAll` whose callback
 *    takes no fixture; in the setup file it is the setup test itself.
 *
 * 2. The password-off probe in `break-glass.spec.ts` is never retried: a retry could turn
 *    a real 200 into a pass. The one `POST /api/accounts/token/` under `tests/sso/` that
 *    is not a backoff login is a raw `request.post`, awaited as a `const` initializer
 *    directly in the test body (so not inside a loop, a closure, a `try` or a branch, which
 *    is where a retry, `expect.poll` or `toPass` would put it), with no backoff, retry or
 *    poll call before it in that body. Both projects carry `retries: 0`.
 *
 * `@characterization`: these pin the harness's own safety, which no client observes
 * (`docs/adr/0002`).
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { E2E_ROOT, listTsFiles, readSpec } from './ast';

const SSO_DIR = 'tests/sso';
const SCOPE_MODULE = path.join(E2E_ROOT, SSO_DIR, 'scope');
const TOKEN_PATH = '/api/accounts/token/';
const RETRYING = /retry|backoff|poll|topass|loginwith/i;

/** Every file the `sso-setup` and `sso` projects load (`playwright.config.ts`). */
async function ssoLoadedFiles(): Promise<string[]> {
  return (await listTsFiles(path.join(E2E_ROOT, SSO_DIR), SSO_DIR)).filter(
    (rel) => rel.endsWith('.spec.ts') || rel.endsWith('.setup.ts')
  );
}

function parse(rel: string, src: string): ts.SourceFile {
  return ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true);
}

function lineOf(sf: ts.SourceFile, node: ts.Node): number {
  return sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
}

/** Local names bound to an imported `test`, whatever the module or alias. */
function testBindings(sf: ts.SourceFile): Set<string> {
  const names = new Set<string>();
  for (const stmt of sf.statements) {
    if (!ts.isImportDeclaration(stmt)) continue;
    const bindings = stmt.importClause?.namedBindings;
    if (!bindings || !ts.isNamedImports(bindings)) continue;
    for (const el of bindings.elements) {
      if ((el.propertyName ?? el.name).text === 'test') names.add(el.name.text);
    }
  }
  return names;
}

function importsScopeAssertion(rel: string, sf: ts.SourceFile): boolean {
  return sf.statements.some((stmt) => {
    if (!ts.isImportDeclaration(stmt) || !ts.isStringLiteral(stmt.moduleSpecifier)) return false;
    const spec = stmt.moduleSpecifier.text;
    if (!spec.startsWith('.')) return false;
    const target = path.resolve(E2E_ROOT, path.dirname(rel), spec);
    const bindings = stmt.importClause?.namedBindings;
    return (
      target === SCOPE_MODULE &&
      !!bindings &&
      ts.isNamedImports(bindings) &&
      bindings.elements.some((el) => !el.propertyName && el.name.text === 'assertScopedStack')
    );
  });
}

function rootIdentifier(expr: ts.Expression): string | undefined {
  let e: ts.Expression = expr;
  while (ts.isPropertyAccessExpression(e) || ts.isCallExpression(e)) e = e.expression;
  return ts.isIdentifier(e) ? e.text : undefined;
}

function enclosingFunction(node: ts.Node): ts.Node | undefined {
  for (let p = node.parent; p; p = p.parent) if (ts.isFunctionLike(p)) return p;
  return undefined;
}

function lastFunctionArg(call: ts.CallExpression): ts.ArrowFunction | ts.FunctionExpression | undefined {
  const last = call.arguments[call.arguments.length - 1];
  return last && (ts.isArrowFunction(last) || ts.isFunctionExpression(last)) ? last : undefined;
}

function isBareScopeAssertion(stmt: ts.Statement | undefined): boolean {
  return (
    !!stmt &&
    ts.isExpressionStatement(stmt) &&
    ts.isCallExpression(stmt.expression) &&
    ts.isIdentifier(stmt.expression.expression) &&
    stmt.expression.expression.text === 'assertScopedStack' &&
    stmt.expression.arguments.length === 0
  );
}

/** Why `rel` breaks rule 1, or undefined when it holds. */
function scopeProblem(rel: string, src: string): string | undefined {
  const sf = parse(rel, src);
  const isSetup = rel.endsWith('.setup.ts');
  if (!importsScopeAssertion(rel, sf)) return 'does not import assertScopedStack from tests/sso/scope.ts';

  let topAwait: ts.Node | undefined;
  const calls: ts.CallExpression[] = [];
  const names = testBindings(sf);
  if (names.size === 0) return 'imports no `test` binding this guard can follow';
  (function visit(node: ts.Node): void {
    if (ts.isAwaitExpression(node) && !enclosingFunction(node)) topAwait ??= node;
    if (ts.isCallExpression(node)) {
      const root = rootIdentifier(node.expression);
      if (root && names.has(root)) calls.push(node);
    }
    ts.forEachChild(node, visit);
  })(sf);
  if (topAwait) return `has a top-level await at line ${lineOf(sf, topAwait)}, which runs before any hook`;

  calls.sort((a, b) => a.getStart() - b.getStart());
  const first = calls[0];
  if (!first) return 'declares no test';
  const where = `its first \`test\` call (line ${lineOf(sf, first)})`;
  if (!ts.isExpressionStatement(first.parent) || first.parent.parent !== sf) {
    return `${where} is not a top-level statement`;
  }
  const callee = first.expression;
  if (isSetup) {
    if (!ts.isIdentifier(callee)) return `${where} is not the setup test itself`;
  } else {
    if (!ts.isPropertyAccessExpression(callee) || callee.name.text !== 'beforeAll') {
      return `${where} is not a test.beforeAll`;
    }
  }
  const fn = lastFunctionArg(first);
  if (!fn || !ts.isBlock(fn.body)) return `${where} has no block-bodied callback`;
  if (!isSetup && fn.parameters.length > 0) {
    return `${where} takes fixtures, which are set up before its first statement runs`;
  }
  if (!isBareScopeAssertion(fn.body.statements[0])) {
    return `${where}'s first statement is not assertScopedStack()`;
  }
  return undefined;
}

test.describe('the sso project', () => {
  test(
    'calls assertScopedStack() first in every file the sso and sso-setup projects load',
    { tag: '@characterization' },
    async () => {
      const files = await ssoLoadedFiles();
      // Guards the guard: an empty or partial listing is the scan being broken.
      expect(files, 'the scan found the sso project files').toEqual(
        expect.arrayContaining([
          'tests/sso/break-glass.spec.ts',
          'tests/sso/sign-in.spec.ts',
          'tests/sso/sso.setup.ts',
          'tests/sso/unmapped.spec.ts',
        ])
      );
      const problems: string[] = [];
      for (const rel of files) {
        const problem = scopeProblem(rel, await readSpec(rel));
        if (problem) problems.push(`${rel}: ${problem}`);
      }
      expect(
        problems,
        'assertScopedStack() must run before anything else in every sso file: the first ' +
          'statement of the setup test, and of a test.beforeAll that is the first test call ' +
          'in every spec. It is the only barrier between these specs and the shared ' +
          'container (tests/guards/sso-structure.spec.ts says why).'
      ).toEqual([]);
    }
  );

  test(
    'loads only what this guard scans, and never retries',
    { tag: '@characterization' },
    async () => {
      const sf = parse('playwright.config.ts', await readSpec('playwright.config.ts'));
      const projects: Record<string, Record<string, string>> = {};
      (function visit(node: ts.Node): void {
        if (ts.isObjectLiteralExpression(node)) {
          const props: Record<string, string> = {};
          for (const p of node.properties) {
            if (ts.isPropertyAssignment(p) && ts.isIdentifier(p.name)) props[p.name.text] = p.initializer.getText(sf);
          }
          if (props.name === "'sso'" || props.name === "'sso-setup'") projects[props.name] = props;
        }
        ts.forEachChild(node, visit);
      })(sf);
      const pick = (p: Record<string, string> | undefined) =>
        p && { testDir: p.testDir, testMatch: p.testMatch, retries: p.retries };
      expect(pick(projects["'sso-setup'"])).toEqual({
        testDir: "'./tests/sso'",
        testMatch: '/sso\\.setup\\.ts$/',
        retries: '0',
      });
      expect(pick(projects["'sso'"])).toEqual({
        testDir: "'./tests/sso'",
        testMatch: '/\\.spec\\.ts$/',
        retries: '0',
      });
    }
  );

  test(
    'sends the password-off probe once, raw, and never retries it',
    { tag: '@characterization' },
    async () => {
      const probes: { rel: string; sf: ts.SourceFile; call: ts.CallExpression }[] = [];
      for (const rel of await listTsFiles(path.join(E2E_ROOT, SSO_DIR), SSO_DIR)) {
        const sf = parse(rel, await readSpec(rel));
        (function visit(node: ts.Node): void {
          if (
            ts.isCallExpression(node) &&
            node.arguments[0] &&
            ts.isStringLiteralLike(node.arguments[0]) &&
            node.arguments[0].text === TOKEN_PATH
          ) {
            probes.push({ rel, sf, call: node });
          }
          ts.forEachChild(node, visit);
        })(sf);
      }
      expect(
        probes.map((p) => `${p.rel}:${lineOf(p.sf, p.call)}`),
        `exactly one raw POST ${TOKEN_PATH} under tests/sso/: the break-glass spec's password-off probe`
      ).toHaveLength(1);
      expect(probes[0].rel).toBe('tests/sso/break-glass.spec.ts');

      const { sf, call } = probes[0];
      const at = `tests/sso/break-glass.spec.ts:${lineOf(sf, call)}`;
      const callee = call.expression;
      expect(
        ts.isPropertyAccessExpression(callee) &&
          ts.isIdentifier(callee.expression) &&
          callee.expression.text === 'request' &&
          callee.name.text === 'post',
        `${at}: the probe is a raw request.post, not a helper`
      ).toBe(true);

      // await request.post(...) as a const initializer, directly in the test body.
      const awaited = call.parent;
      const decl = awaited?.parent;
      const list = decl?.parent;
      const stmt = list?.parent;
      const body = stmt?.parent;
      const fn = body?.parent;
      const shapeOk =
        !!awaited &&
        ts.isAwaitExpression(awaited) &&
        !!decl &&
        ts.isVariableDeclaration(decl) &&
        !!list &&
        ts.isVariableDeclarationList(list) &&
        (list.flags & ts.NodeFlags.Const) !== 0 &&
        !!stmt &&
        ts.isVariableStatement(stmt) &&
        !!body &&
        ts.isBlock(body) &&
        !!fn &&
        (ts.isArrowFunction(fn) || ts.isFunctionExpression(fn)) &&
        ts.isCallExpression(fn.parent) &&
        ts.isIdentifier(fn.parent.expression) &&
        fn.parent.expression.text === 'test';
      expect(
        shapeOk,
        `${at}: the probe must be \`const x = await request.post(...)\` directly in the test ` +
          'body: not in a loop, closure, try or branch, where a retry, expect.poll or toPass would put it'
      ).toBe(true);

      const before: string[] = [];
      for (const s of (body as ts.Block).statements) {
        if (s === stmt) break;
        (function visit(node: ts.Node): void {
          if (ts.isCallExpression(node)) {
            const name = ts.isPropertyAccessExpression(node.expression)
              ? node.expression.name.text
              : ts.isIdentifier(node.expression)
                ? node.expression.text
                : '';
            if (RETRYING.test(name)) before.push(`${name} (line ${lineOf(sf, node)})`);
          }
          ts.forEachChild(node, visit);
        })(s);
      }
      expect(before, `${at}: no backoff, retry or poll call before the probe in the test body`).toEqual([]);
    }
  );
});
