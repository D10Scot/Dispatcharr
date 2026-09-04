/**
 * Grey-box escape hatches are confined to an explicit allowlist.
 *
 * Replaces `tests/streaming-greybox/quarantine.spec.ts`, which policed one
 * string (`greybox/redis`) and whose principle this inherits verbatim: "a
 * convention plus a README decays silently. This does not." The problem was
 * only its reach — `node:child_process` was already imported by a second spec
 * and would have been accepted silently in any new one.
 *
 * Four capabilities, four allowlists, in `./allowlist.ts`. Everything on those
 * lists is normally `@characterization`: they are the calls that stop meaning
 * anything once the relay is its own process. The one exception documents
 * itself in-file — see `tests/streaming-greybox/nginx-stream-buffering.spec.ts`'s
 * own header for why it's `@contract` despite being `SUBPROCESS`-listed.
 *
 * Verified by mutation, and one of those mutations is the whole argument for
 * parsing over grep: adding `// we run pgrep here` as a **comment** to
 * `tests/seeded/hdhr.spec.ts` must PASS, while `const c = 'pgrep -x ffmpeg';`
 * as code must FAIL. Three specs mention `docker` in prose today and none is
 * an escape.
 *
 * `usesInstanceFixture` also verified by mutation: adding
 * `test.beforeAll(async ({ instance }) => { await instance.restart(); });` to
 * `tests/seeded/hdhr.spec.ts` failed the container-lifecycle check, naming
 * that file — `findTestCalls` is called with `{ includeHooks: true }` here
 * specifically so a hook, not just a test, can be caught destructuring
 * `instance`.
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import {
  CONTAINER_INTROSPECTION,
  CONTAINER_LIFECYCLE,
  GREYBOX_REDIS,
  SUBPROCESS,
  type Capability,
} from './allowlist';
import { E2E_ROOT, findTestCalls, listTsFiles, readSpec, ROOTS } from './ast';

const INTROSPECTION_MARKERS = ['pgrep', 'docker ', 'manage.py'];

function importsModule(sf: ts.SourceFile, pred: (spec: string) => boolean): boolean {
  return sf.statements.some(
    (st) =>
      ts.isImportDeclaration(st) &&
      ts.isStringLiteral(st.moduleSpecifier) &&
      pred(st.moduleSpecifier.text),
  );
}

/**
 * Only string and template literals — never comments.
 *
 * This is the distinction the guard turns on. `docker` appears in comments in
 * three specs today, none of them a grey-box escape; a text scan flags all
 * three, and a guard that fires on prose gets loosened until it catches
 * nothing. Comments are trivia to the parser, and this walk never reaches
 * them.
 */
function hasStringLiteralContaining(sf: ts.SourceFile, markers: readonly string[]): boolean {
  let found = false;
  function visit(node: ts.Node): void {
    if (found) return;
    if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    ) {
      if (markers.some((m) => node.text.includes(m))) found = true;
      return;
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);
  return found;
}

/**
 * A test — or a lifecycle hook — that names `instance` in its destructured
 * fixture parameter. Hooks are included here (unlike the tag guards) because
 * this is the only detector that reads fixture parameters, and
 * `test.beforeAll(async ({ instance }) => instance.restart())` is exactly the
 * kind of container-lifecycle escape this guard exists to catch.
 */
function usesInstanceFixture(src: string, rel: string): boolean {
  return findTestCalls(src, rel, { includeHooks: true }).some((call) => {
    const body = call.args[call.args.length - 1];
    if (!body || (!ts.isArrowFunction(body) && !ts.isFunctionExpression(body))) return false;
    const param = body.parameters[0];
    if (!param || !ts.isObjectBindingPattern(param.name)) return false;
    return param.name.elements.some(
      (el) => (el.propertyName ?? el.name).getText() === 'instance',
    );
  });
}

type Detector = (sf: ts.SourceFile, src: string, rel: string) => boolean;

async function usersOf(detect: Detector): Promise<string[]> {
  const hits: string[] = [];
  for (const [dir, prefix] of ROOTS) {
    for (const rel of await listTsFiles(path.join(E2E_ROOT, dir), prefix)) {
      // This directory's own source names every marker it polices.
      if (rel.startsWith('tests/guards/')) continue;
      const src = await readSpec(rel);
      const sf = ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true);
      if (detect(sf, src, rel)) hits.push(rel);
    }
  }
  return hits.sort();
}

async function expectConfined(cap: Capability, detect: Detector): Promise<void> {
  const actual = await usersOf(detect);
  // `toEqual`, not `toContain`: removing a legitimate use must also be a
  // deliberate edit, or the allowlist rots in the other direction.
  expect(
    actual,
    `${cap.name} is confined to an allowlist. ${cap.why}\n` +
      'To add a file, edit tests/guards/allowlist.ts and say in the diff why it needs this. ' +
      'See docs/adr/0002-e2e-test-taxonomy.md — anything on these lists is ' +
      '@characterization by construction.',
  ).toEqual([...cap.allow].sort());
}

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, import specifiers, allowlist
// membership. None of it is client-observable behaviour, and all of it changes
// shape when the suite is restructured. See docs/adr/0002-e2e-test-taxonomy.md.
test('the container-lifecycle fixture is confined to the lifecycle projects', { tag: '@characterization' }, async () => {
  await expectConfined(CONTAINER_LIFECYCLE, (_sf, src, rel) => usesInstanceFixture(src, rel));
});

test('direct subprocess execution is confined to its allowlist', { tag: '@characterization' }, async () => {
  await expectConfined(SUBPROCESS, (sf) =>
    importsModule(sf, (s) => s === 'node:child_process' || s === 'child_process'),
  );
});

test('only allowlisted specs import the grey-box Redis helper', { tag: '@characterization' }, async () => {
  await expectConfined(GREYBOX_REDIS, (sf) =>
    importsModule(sf, (s) => s.endsWith('greybox/redis')),
  );
});

test('container-introspection commands are confined to their allowlist', { tag: '@characterization' }, async () => {
  await expectConfined(CONTAINER_INTROSPECTION, (sf) =>
    hasStringLiteralContaining(sf, INTROSPECTION_MARKERS),
  );
});
