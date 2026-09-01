/**
 * The one AST walker every guard in this directory shares.
 *
 * Extracted from `pageerrors-enforcement.spec.ts`, which established both the
 * technique and the discipline: parse with the TypeScript compiler API rather
 * than scanning source text, and treat a shape the checker cannot read as a
 * failure rather than a pass. Its header states why — "a checker that
 * silently skips a shape it cannot read has the same blind spot with the same
 * consequence".
 *
 * Why parsing and not grep, concretely: a source scan for `docker` across
 * `e2e/tests/**` matches `output-m3u.spec.ts`, `plugins.spec.ts` and
 * `connect.spec.ts` — all three in *comments*, none a grey-box escape. A guard
 * that cannot tell code from prose either fails on prose or gets loosened
 * until it catches nothing. Comments are trivia to the compiler API; a walk
 * over expressions never sees them.
 *
 * This module exists because three guards were about to re-derive "what is a
 * test declaration" independently, and drift from each other and from the
 * pageErrors checker that got there first.
 */
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import * as ts from 'typescript';

/** `e2e/` — the root every guard's relative paths are expressed against. */
export const E2E_ROOT = path.resolve(__dirname, '../..');

/** Repository root, for guards that read `frontend/src/`. */
export const REPO_ROOT = path.resolve(E2E_ROOT, '..');

/**
 * Lifecycle hooks share `test`'s namespace but declare a setup/teardown step,
 * not a test. Excluding exactly these four is deliberate and minimal: every
 * other `test.<prop>(…)` — `.only`, `.skip`, `.fixme`, `.fail` — is still a
 * test declaration and is still judged.
 */
export const TEST_HOOK_NAMES: ReadonlySet<string> = new Set([
  'beforeEach',
  'afterEach',
  'beforeAll',
  'afterAll',
]);

export function isTestCallee(expr: ts.Expression): boolean {
  if (ts.isIdentifier(expr) && expr.text === 'test') return true;
  return (
    ts.isPropertyAccessExpression(expr) &&
    ts.isIdentifier(expr.expression) &&
    expr.expression.text === 'test' &&
    !TEST_HOOK_NAMES.has(expr.name.text)
  );
}

/** `test.describe(...)` and its variants (`.serial`, `.parallel`, `.only`). */
export function isDescribeCallee(expr: ts.Expression): boolean {
  if (
    ts.isPropertyAccessExpression(expr) &&
    ts.isIdentifier(expr.expression) &&
    expr.expression.text === 'test' &&
    expr.name.text === 'describe'
  ) {
    return true;
  }
  return (
    ts.isPropertyAccessExpression(expr) &&
    ts.isPropertyAccessExpression(expr.expression) &&
    ts.isIdentifier(expr.expression.expression) &&
    expr.expression.expression.text === 'test' &&
    expr.expression.name.text === 'describe'
  );
}

export type TestCall = {
  node: ts.CallExpression;
  args: readonly ts.Expression[];
  line: number;
  /** Tags on enclosing `test.describe` blocks, outermost first. */
  describeTags: readonly string[];
};

/**
 * Reads the tags off a Playwright `TestDetails` argument, if present.
 *
 * Playwright's shape is `test(title, { tag: '@x' | ['@x','@y'] }, body)`, so
 * the details object is the second argument when there are three. Returns
 * `undefined` when there is no readable details object — which callers that
 * fail closed must distinguish from "a details object with no tag", because
 * only the first is ambiguous with an ordinary two-argument call.
 */
export function readTags(args: readonly ts.Expression[]): string[] | undefined {
  if (args.length < 3) return undefined;
  const details = args[1];
  if (!ts.isObjectLiteralExpression(details)) return undefined;
  for (const prop of details.properties) {
    if (
      !ts.isPropertyAssignment(prop) ||
      !ts.isIdentifier(prop.name) ||
      prop.name.text !== 'tag'
    ) {
      continue;
    }
    const value = prop.initializer;
    if (ts.isStringLiteral(value)) return [value.text];
    if (ts.isArrayLiteralExpression(value)) {
      return value.elements.filter(ts.isStringLiteral).map((e) => e.text);
    }
    return [];
  }
  return undefined;
}

export function findTestCalls(src: string, fileName: string): TestCall[] {
  const sourceFile = ts.createSourceFile(fileName, src, ts.ScriptTarget.Latest, true);
  const calls: TestCall[] = [];
  const describeStack: string[][] = [];

  function visit(node: ts.Node): void {
    if (ts.isCallExpression(node) && isDescribeCallee(node.expression)) {
      describeStack.push(readTags(node.arguments) ?? []);
      ts.forEachChild(node, visit);
      describeStack.pop();
      return;
    }
    if (ts.isCallExpression(node) && isTestCallee(node.expression)) {
      const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
      calls.push({
        node,
        args: node.arguments,
        line: line + 1,
        describeTags: describeStack.flat(),
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return calls;
}

async function listFiles(
  absDir: string,
  relPrefix: string,
  keep: (name: string) => boolean,
): Promise<string[]> {
  const out: string[] = [];
  for (const entry of await readdir(absDir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
    const rel = relPrefix ? `${relPrefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      out.push(...(await listFiles(path.join(absDir, entry.name), rel, keep)));
    } else if (keep(entry.name)) {
      out.push(rel);
    }
  }
  // Sorted, not just filtered: `readdir` returns filesystem order, which is
  // not alphabetical on every platform and is not stable across runs. Every
  // guard here compares against a hand-written sorted allowlist with
  // `toEqual`, which an unstable order would break at random.
  return out.sort();
}

export function listSpecFiles(absDir: string, relPrefix = ''): Promise<string[]> {
  return listFiles(absDir, relPrefix, (n) => n.endsWith('.spec.ts'));
}

export function listTsFiles(absDir: string, relPrefix = ''): Promise<string[]> {
  return listFiles(absDir, relPrefix, (n) => n.endsWith('.ts'));
}

export async function readSpec(rel: string): Promise<string> {
  return readFile(path.join(E2E_ROOT, rel), 'utf8');
}
