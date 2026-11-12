/**
 * The SSO projects' load-bearing conventions, as assertions (SSO spec PR S5, review
 * round 1; tightened by the ID-token fault follow-up).
 *
 * 1. `assertScopedStack()` runs before anything else in every file the `sso-setup`,
 *    `sso`, `sso-faults-setup` and `sso-faults` projects load. It is the only barrier
 *    between these specs and ADR 0001's shared container, where switching password login
 *    off would lock every other project out. `sso-scope.spec.ts` pins what the function
 *    refuses; this pins that it is called, and called first.
 *
 *    Enforced here by a scan of the directory rather than structurally through
 *    `tests/sso/fixtures.ts`, because the scan cannot be bypassed by accident: it reads
 *    every `.ts` file under `tests/sso/`, whatever imports it, and fails naming it. The
 *    scan also holds `sso.setup.ts`, which imports `test` from `@playwright/test`
 *    directly.
 *
 *    Every file under `tests/sso/` is either a declared support module (`SUPPORT_MODULES`)
 *    or a file the projects load (`sso.setup.ts`, or a `.spec.ts`); anything else fails,
 *    so a project matching a new suffix cannot load an unscanned file. The rules:
 *
 *    - Placement, per loaded file: it imports `assertScopedStack` from
 *      `tests/sso/scope.ts`; it has no top-level `await`; and its first call on the `test`
 *      binding, in source order, is a top-level statement whose callback's first
 *      statement is `assertScopedStack()` with no argument (which reads `process.env`
 *      and nothing an author could hand it). In a spec that call is a `test.beforeAll`
 *      whose callback takes no fixture; in the setup file it is the setup test itself.
 *      Configuration that runs nothing may come first: a top-level
 *      `test.describe.configure(...)` or `test.use(...)` with no function in its
 *      arguments.
 *    - Load time, per file, support modules included: nothing the file evaluates when it
 *      is imported may make a request, because module code runs before any hook. A call
 *      evaluated at load is allowed only on the `test` binding (whose callbacks run
 *      later, except a `describe` body, which is walked as load-time code) or as one of
 *      `LOAD_SAFE_METHODS` (whose callbacks are walked too); a `new` only of
 *      `LOAD_SAFE_CONSTRUCTORS`. `void fetch(...)` at the top of a spec fails here.
 *    - No `scope: 'worker'` and no `auto` fixture option anywhere under `tests/sso/`: a
 *      worker-scoped auto fixture is set up before any `beforeAll`, which is ordering
 *      nobody can see in a spec. A support module calls the `test` binding only to
 *      `extend` it.
 *
 *    Each project that can load a file under `tests/sso/` (its `testDir` is inside it
 *    or contains it) must be one of the four, with its `testDir`, `testMatch`,
 *    `testIgnore` and `retries` pinned.
 *
 * 2. The password-off probe in `break-glass.spec.ts` is never retried: a retry could turn
 *    a real 200 into a pass. The one `POST /api/accounts/token/` under `tests/sso/` that
 *    is not a backoff login is a raw `request.post`, awaited as a `const` initializer
 *    directly in the test body (so not inside a loop, a closure, a `try` or a branch, which
 *    is where a retry, `expect.poll` or `toPass` would put it), with no backoff, retry or
 *    poll call before it in that body. Every SSO project carries `retries: 0`.
 *
 * What it cannot see: code outside `tests/sso/` that a spec imports (`fixtures/`,
 * `setup/`, another directory's helpers) runs at import too, and is policed only as the
 * rest of the suite is; and a deliberately computed property name (`{ ['au' + 'to']: … }`).
 *
 * `@characterization`: these pin the harness's own safety, which no client observes
 * (`docs/adr/0002`).
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { E2E_ROOT, listTsFiles, readSpec } from './ast';

const SSO_DIR = 'tests/sso';
const SSO_ABS = path.join(E2E_ROOT, SSO_DIR);
const SCOPE_MODULE = path.join(E2E_ROOT, SSO_DIR, 'scope');
const TOKEN_PATH = '/api/accounts/token/';
const RETRYING = /retry|backoff|poll|topass|loginwith/i;

/** The files under `tests/sso/` that no project loads as tests: imported only. */
const SUPPORT_MODULES = new Set([
  'tests/sso/budget.ts',
  'tests/sso/fixtures.ts',
  'tests/sso/helpers.ts',
  'tests/sso/scope.ts',
  'tests/sso/testids.ts',
]);

/** Method calls allowed in code a file evaluates when it is imported. Their callbacks are walked. */
const LOAD_SAFE_METHODS = new Set(['find', 'map', 'filter', 'flatMap', 'some', 'every', 'includes', 'join']);
/** Constructors allowed in code a file evaluates when it is imported. */
const LOAD_SAFE_CONSTRUCTORS = new Set(['Error', 'RegExp', 'Set', 'Map']);

/**
 * Every project that may load a file under `tests/sso/`, and the config text that decides
 * what it loads. A `testIgnore` of `undefined` means the project sets none.
 */
const SSO_PROJECTS: Record<string, { testDir: string; testMatch: string; testIgnore?: string; retries: string }> = {
  'sso-setup': { testDir: "'./tests/sso'", testMatch: '/sso\\.setup\\.ts$/', retries: '0' },
  sso: { testDir: "'./tests/sso'", testMatch: '/\\.spec\\.ts$/', testIgnore: '/\\/faults\\//', retries: '0' },
  'sso-faults-setup': { testDir: "'./tests/sso'", testMatch: '/sso\\.setup\\.ts$/', retries: '0' },
  'sso-faults': { testDir: "'./tests/sso/faults'", testMatch: '/\\.spec\\.ts$/', retries: '0' },
};

/** Every `.ts` file under `tests/sso/`. */
async function ssoFiles(): Promise<string[]> {
  return listTsFiles(SSO_ABS, SSO_DIR);
}

function isLoadedFile(rel: string): boolean {
  return rel === 'tests/sso/sso.setup.ts' || rel.endsWith('.spec.ts');
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

/** The property names after the root of a callee: `test.describe.configure` → describe, configure. */
function calleeChain(expr: ts.Expression): string[] {
  const names: string[] = [];
  let e: ts.Expression = expr;
  while (ts.isPropertyAccessExpression(e)) {
    names.unshift(e.name.text);
    e = e.expression;
  }
  return names;
}

function enclosingFunction(node: ts.Node): ts.Node | undefined {
  for (let p = node.parent; p; p = p.parent) if (ts.isFunctionLike(p)) return p;
  return undefined;
}

function containsFunction(node: ts.Node): boolean {
  let found = false;
  (function visit(n: ts.Node): void {
    if (found) return;
    if (ts.isFunctionLike(n)) {
      found = true;
      return;
    }
    ts.forEachChild(n, visit);
  })(node);
  return found;
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

/**
 * A top-level `test.describe.configure(...)` or `test.use(...)` with no function in its
 * arguments: configuration that runs nothing, so it may precede the `beforeAll`.
 */
function isInertConfigCall(call: ts.CallExpression, sf: ts.SourceFile): boolean {
  const chain = calleeChain(call.expression).join('.');
  return (
    (chain === 'describe.configure' || chain === 'use') &&
    ts.isExpressionStatement(call.parent) &&
    call.parent.parent === sf &&
    !call.arguments.some(containsFunction)
  );
}

/** Why loaded file `rel` breaks the placement rule, or undefined when it holds. */
function scopeProblem(rel: string, sf: ts.SourceFile): string | undefined {
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
  const inert = calls.filter((c) => isInertConfigCall(c, sf));
  const first = calls.find(
    (c) => !inert.some((cfg) => c.getStart() >= cfg.getStart() && c.getEnd() <= cfg.getEnd())
  );
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

/**
 * Every call or `new` the file evaluates when it is imported that could act: anything but
 * a call on the `test` binding, a `LOAD_SAFE_METHODS` call or a `LOAD_SAFE_CONSTRUCTORS`
 * `new`. Function bodies run later and are not walked, except a `describe` body and the
 * callbacks of a load-safe method, which run now.
 */
function loadTimeProblems(sf: ts.SourceFile): string[] {
  const names = testBindings(sf);
  const problems: string[] = [];
  const at = (node: ts.Node) => `\`${node.getText(sf).split('\n')[0].slice(0, 60)}\` (line ${lineOf(sf, node)})`;

  function walkNow(node: ts.Node): void {
    if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
      if (ts.isBlock(node.body)) node.body.statements.forEach(walk);
      else walk(node.body);
    } else {
      walk(node);
    }
  }

  function walk(node: ts.Node): void {
    if (ts.isFunctionLike(node)) return;
    if (ts.isCallExpression(node)) {
      const root = rootIdentifier(node.expression);
      if (root && names.has(root)) {
        walk(node.expression);
        const isDescribe = calleeChain(node.expression)[0] === 'describe' && calleeChain(node.expression)[1] !== 'configure';
        for (const arg of node.arguments) (isDescribe ? walkNow : walk)(arg);
        return;
      }
      if (ts.isPropertyAccessExpression(node.expression) && LOAD_SAFE_METHODS.has(node.expression.name.text)) {
        walk(node.expression.expression);
        node.arguments.forEach(walkNow);
        return;
      }
      problems.push(`calls ${at(node)} when the file loads, before any hook`);
      return;
    }
    if (ts.isNewExpression(node)) {
      if (ts.isIdentifier(node.expression) && LOAD_SAFE_CONSTRUCTORS.has(node.expression.text)) {
        node.arguments?.forEach(walk);
        return;
      }
      problems.push(`constructs ${at(node)} when the file loads, before any hook`);
      return;
    }
    if (ts.isTaggedTemplateExpression(node)) {
      problems.push(`calls the tag of ${at(node)} when the file loads, before any hook`);
      return;
    }
    ts.forEachChild(node, walk);
  }

  sf.statements.forEach(walk);
  return problems;
}

/** A fixture option that sets a fixture up before any `beforeAll`, anywhere in the file. */
function fixtureOrderProblems(sf: ts.SourceFile): string[] {
  const problems: string[] = [];
  (function visit(node: ts.Node): void {
    if (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) {
      const key = ts.isIdentifier(node.name) || ts.isStringLiteral(node.name) ? node.name.text : undefined;
      const init = ts.isPropertyAssignment(node) ? node.initializer : undefined;
      if (key === 'scope' && (!init || !ts.isStringLiteralLike(init) || init.text === 'worker')) {
        problems.push(`sets a fixture scope (line ${lineOf(sf, node)}): no worker-scoped fixture under tests/sso/`);
      }
      if (key === 'auto' && !(init && init.kind === ts.SyntaxKind.FalseKeyword)) {
        problems.push(`sets an auto fixture (line ${lineOf(sf, node)}): no auto fixture under tests/sso/`);
      }
    }
    ts.forEachChild(node, visit);
  })(sf);
  return problems;
}

/** A support module may call the `test` binding only to `extend` it. */
function supportModuleProblems(sf: ts.SourceFile): string[] {
  const names = testBindings(sf);
  const problems: string[] = [];
  (function visit(node: ts.Node): void {
    if (ts.isCallExpression(node)) {
      const root = rootIdentifier(node.expression);
      const chain = calleeChain(node.expression);
      if (root && names.has(root) && !(chain.length === 1 && chain[0] === 'extend')) {
        problems.push(`calls ${root}${chain.map((n) => `.${n}`).join('')}(...) (line ${lineOf(sf, node)}), but a support module only extends test`);
      }
    }
    ts.forEachChild(node, visit);
  })(sf);
  return problems;
}

/** The config's projects, by name, with the text of each property; problems for what cannot be read. */
function readProjects(sf: ts.SourceFile): { projects: Map<string, Record<string, string>>; topTestDir?: string; problems: string[] } {
  const problems: string[] = [];
  const projects = new Map<string, Record<string, string>>();
  let topTestDir: string | undefined;
  let config: ts.ObjectLiteralExpression | undefined;
  (function visit(node: ts.Node): void {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === 'defineConfig' &&
      node.arguments[0] &&
      ts.isObjectLiteralExpression(node.arguments[0])
    ) {
      config = node.arguments[0];
    }
    ts.forEachChild(node, visit);
  })(sf);
  if (!config) return { projects, problems: ['playwright.config.ts: no defineConfig({...}) this guard can read'] };

  let list: ts.Expression | undefined;
  for (const p of config.properties) {
    if (!ts.isPropertyAssignment(p) || !ts.isIdentifier(p.name)) continue;
    if (p.name.text === 'testDir') topTestDir = p.initializer.getText(sf);
    if (p.name.text === 'projects') list = p.initializer;
  }
  if (!list || !ts.isArrayLiteralExpression(list)) {
    return { projects, topTestDir, problems: ['playwright.config.ts: `projects` is not an array literal'] };
  }
  for (const el of list.elements) {
    if (!ts.isObjectLiteralExpression(el)) {
      problems.push(`playwright.config.ts line ${lineOf(sf, el)}: a project that is not an object literal`);
      continue;
    }
    const props: Record<string, string> = {};
    for (const p of el.properties) {
      if (ts.isPropertyAssignment(p) && ts.isIdentifier(p.name)) props[p.name.text] = p.initializer.getText(sf);
      else problems.push(`playwright.config.ts line ${lineOf(sf, p)}: a project property this guard cannot read`);
    }
    const name = props.name;
    if (!name || !/^'[^']+'$/.test(name)) {
      problems.push(`playwright.config.ts line ${lineOf(sf, el)}: a project without a literal name`);
      continue;
    }
    projects.set(name.slice(1, -1), props);
  }
  return { projects, topTestDir, problems };
}

/** Whether a project with `testDirText` can load a file under `tests/sso/`; undefined if unreadable. */
function overlapsSsoDir(testDirText: string): boolean | undefined {
  const m = /^'([^']*)'$/.exec(testDirText);
  if (!m) return undefined;
  const dir = path.resolve(E2E_ROOT, m[1]);
  const inside = (child: string, parent: string) => child === parent || child.startsWith(parent + path.sep);
  return inside(dir, SSO_ABS) || inside(SSO_ABS, dir);
}

test.describe('the sso projects', () => {
  test(
    'calls assertScopedStack() first in every file the SSO projects load',
    { tag: '@characterization' },
    async () => {
      const files = await ssoFiles();
      // Guards the guard: an empty or partial listing is the scan being broken.
      expect(files, 'the scan found the SSO project files').toEqual(
        expect.arrayContaining([
          'tests/sso/break-glass.spec.ts',
          'tests/sso/faults/id-token-faults.spec.ts',
          'tests/sso/sign-in.spec.ts',
          'tests/sso/sso.setup.ts',
          'tests/sso/unmapped.spec.ts',
          ...SUPPORT_MODULES,
        ])
      );
      const problems: string[] = [];
      for (const rel of files) {
        if (SUPPORT_MODULES.has(rel)) continue;
        if (!isLoadedFile(rel)) {
          problems.push(
            `${rel}: is neither a support module (SUPPORT_MODULES in this guard) nor a file the ` +
              'SSO projects load (sso.setup.ts or a .spec.ts)'
          );
          continue;
        }
        const problem = scopeProblem(rel, parse(rel, await readSpec(rel)));
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
    'runs nothing under tests/sso/ before the scope check: no load-time call, no worker or auto fixture',
    { tag: '@characterization' },
    async () => {
      const problems: string[] = [];
      for (const rel of await ssoFiles()) {
        const sf = parse(rel, await readSpec(rel));
        for (const p of loadTimeProblems(sf)) problems.push(`${rel}: ${p}`);
        for (const p of fixtureOrderProblems(sf)) problems.push(`${rel}: ${p}`);
        if (SUPPORT_MODULES.has(rel)) for (const p of supportModuleProblems(sf)) problems.push(`${rel}: ${p}`);
      }
      expect(
        problems,
        'Code under tests/sso/ that runs when a file is imported, or a fixture that is set up ' +
          'before every beforeAll, runs before assertScopedStack() and could reach the shared ' +
          'container (tests/guards/sso-structure.spec.ts says why).'
      ).toEqual([]);
    }
  );

  test(
    'loads tests/sso/ only through the four SSO projects, which never retry',
    { tag: '@characterization' },
    async () => {
      const sf = parse('playwright.config.ts', await readSpec('playwright.config.ts'));
      const { projects, topTestDir, problems } = readProjects(sf);
      for (const [name, props] of projects) {
        const testDir = props.testDir ?? topTestDir ?? "'.'";
        const overlaps = overlapsSsoDir(testDir);
        if (overlaps === undefined) problems.push(`project '${name}': testDir ${testDir} is not a string literal`);
        else if (overlaps && !(name in SSO_PROJECTS)) {
          problems.push(`project '${name}': its testDir ${testDir} can load files under tests/sso/`);
        }
      }
      expect(problems, 'only the four SSO projects may load tests/sso/').toEqual([]);
      for (const [name, expected] of Object.entries(SSO_PROJECTS)) {
        const props = projects.get(name);
        expect(
          props && { testDir: props.testDir, testMatch: props.testMatch, testIgnore: props.testIgnore, retries: props.retries },
          `project '${name}'`
        ).toEqual({ testIgnore: undefined, ...expected });
      }
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
