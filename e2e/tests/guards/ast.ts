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

/**
 * Modifiers that DECLARE a test when given a title: `test.fail('…', fn)`.
 *
 * Each also has an in-body form that declares nothing — `test.fail()` marks
 * the enclosing test, `test.skip(cond, 'reason')` skips it conditionally. The
 * two are told apart by the first argument being a string literal, not by the
 * modifier name, because the name is identical in both.
 */
const DECLARATION_MODIFIERS: ReadonlySet<string> = new Set([
  'only',
  'skip',
  'fail',
  'fixme',
]);

/**
 * `test.*` calls that are never declarations, whatever their arguments.
 *
 * Counted because getting this wrong is not academic: the suite makes 41
 * `test.setTimeout(…)` calls and one each of `use`, `step`, `slow`, `info`.
 * A walker that treats those as declarations reports 232 tests where there
 * are 190, and would demand a tag on a call that has nowhere to put one.
 */
const NON_DECLARATION_NAMES: ReadonlySet<string> = new Set([
  'use',
  'setTimeout',
  'slow',
  'step',
  'info',
  'extend',
  'describe',
  'configure',
]);

export type Classification =
  | { kind: 'declaration' }
  | { kind: 'not-a-declaration' }
  | { kind: 'unverifiable'; reason: string };

/**
 * Decides whether a `test.*` call declares a test.
 *
 * Fails closed, in the same discipline as `pageerrors-enforcement.spec.ts`: a
 * shape this function does not recognise is `unverifiable`, never silently
 * dropped. Silently dropping is how a test escapes every guard here at once.
 */
export function classifyTestCall(node: ts.CallExpression): Classification {
  const first = node.arguments[0];
  // A title is any string-shaped expression, not only a plain literal.
  // Parameterised suites are a normal pattern here — `render.spec.ts` and
  // `authorization.spec.ts` both loop and build titles with a template — and
  // treating those as unreadable would report two real declarations as holes
  // in the checker.
  const titled =
    first !== undefined && (ts.isStringLiteralLike(first) || ts.isTemplateExpression(first));

  if (ts.isIdentifier(node.expression)) {
    // Bare `test(...)`.
    if (titled) return { kind: 'declaration' };
    return {
      kind: 'unverifiable',
      reason: `test(...) whose first argument is not a string-shaped title (found ${
        first ? ts.SyntaxKind[first.kind] : 'no arguments'
      }) — inline the title, or pin this location with a reason`,
    };
  }

  if (!ts.isPropertyAccessExpression(node.expression)) {
    return { kind: 'unverifiable', reason: 'unreadable callee shape' };
  }

  const name = node.expression.name.text;
  if (NON_DECLARATION_NAMES.has(name)) return { kind: 'not-a-declaration' };
  if (DECLARATION_MODIFIERS.has(name)) {
    // `test.fail('title', fn)` declares; `test.fail()` and
    // `test.skip(cond, 'reason')` modify the enclosing test.
    return titled ? { kind: 'declaration' } : { kind: 'not-a-declaration' };
  }

  return {
    kind: 'unverifiable',
    reason: `unrecognised test.${name}(...) — add it to DECLARATION_MODIFIERS or NON_DECLARATION_NAMES in tests/guards/ast.ts`,
  };
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
  /** Why this call is unreadable, when `findTestCalls` could not classify it. */
  unverifiableReason?: string;
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
      const classification = classifyTestCall(node);
      if (classification.kind !== 'not-a-declaration') {
        const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
        calls.push({
          node,
          args: node.arguments,
          line: line + 1,
          describeTags: describeStack.flat(),
          unverifiableReason:
            classification.kind === 'unverifiable' ? classification.reason : undefined,
        });
      }
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
