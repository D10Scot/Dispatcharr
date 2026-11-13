/**
 * Instance-wide settings writes are confined to an allowlist.
 *
 * `playwright.config.ts` already contains this argument twice, in prose. Of
 * `failover-buffering.spec.ts` raising `buffering_speed` it says: "nothing
 * enforces that convention, so a future ffmpeg-profile spec added here without
 * reading that test's header would race the raised threshold and fail
 * silently." It makes the same observation about `vod-redirect-profile.spec.ts`
 * and `default_stream_profile`. This guard is those sentences, enforced.
 *
 * The rule is "any write to /api/core/settings/", with no key list, because
 * the data model makes that exact. `core/models.py:CoreSettings` is not one
 * row per setting: `key` is unique, `value` is a JSONField, and each row is a
 * whole settings *group* — nine of them (`stream_settings`, `dvr_settings`,
 * `backup_settings`, `proxy_settings`, `network_access`, `system_settings`,
 * `epg_settings`, `user_limit_settings`, `auth_settings`). Every one is instance-wide, so there
 * is no such thing as a scoped write, nothing to maintain, and no group
 * someone can forget to enumerate — including `epg_settings`, which has no
 * seeding migration and must be POSTed into existence before it can be
 * PATCHed.
 *
 * Serialising a project is NOT a substitute for this list.
 * `CoreSettings._get_group` caches each group in Redis for 300s, and
 * `_REDIRECT_STREAM_PROFILE_ID_CACHE_KEY` has no post_save invalidation at all
 * — it appears nowhere in `core/signals.py`. A mutation reverted in teardown
 * can still be live five minutes later, in another project, on another worker.
 * Serialisation bounds concurrency; only this list bounds blast radius.
 *
 * Verified by mutation: adding an `api.patch('/api/core/settings/1/', …)` call
 * to `tests/seeded/hdhr.spec.ts` failed; putting the same route in a comment
 * passed.
 *
 * Scans `ROOTS` (`tests/`, `fixtures/`, `setup/`), the same as
 * `capabilities.spec.ts`, for the same reason that guard gives: a write
 * hidden inside a fixture or setup helper runs on every test that imports it
 * and is invisible to a scan of `tests/` alone. It reads every TypeScript and
 * JavaScript file there (`listSourceFiles`), so a `.js` or `.mjs` helper is
 * read too, and treats `fetch(new Request(url, { method }))` as the write it is.
 *
 * What it cannot see: a URL or method built at run time from values it cannot
 * resolve statically (a function's return value, an imported constant, a
 * `Request` held in a variable), and a write through a module outside `ROOTS`.
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { GLOBAL_SETTINGS_WRITE } from './allowlist';
import { E2E_ROOT, listSourceFiles, readSpec, ROOTS } from './ast';

const WRITE_METHODS = new Set(['post', 'patch', 'put', 'delete']);
const SETTINGS_PATH = 'core/settings';

/**
 * Module-level `const NAME = '…'` bindings, so a URL assembled from one is
 * still readable.
 *
 * Not optional cleverness: three of the four files that write settings today
 * do it through a `const CORE_SETTINGS_PATH = '/api/core/settings/'` and a
 * template — `api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, …)`. A detector
 * that only reads inline literals sees none of them and reports the rule as
 * satisfied while three specs mutate global state.
 */
function collectStringConsts(sf: ts.SourceFile): Map<string, string> {
  const consts = new Map<string, string>();
  for (const st of sf.statements) {
    if (!ts.isVariableStatement(st)) continue;
    for (const decl of st.declarationList.declarations) {
      if (
        ts.isIdentifier(decl.name) &&
        decl.initializer &&
        ts.isStringLiteralLike(decl.initializer)
      ) {
        consts.set(decl.name.text, decl.initializer.text);
      }
    }
  }
  return consts;
}

/** Best-effort static text of a URL expression, resolving known constants. */
function resolveText(expr: ts.Expression, consts: Map<string, string>): string {
  if (ts.isStringLiteralLike(expr)) return expr.text;
  if (ts.isIdentifier(expr)) return consts.get(expr.text) ?? '';
  if (ts.isTemplateExpression(expr)) {
    let out = expr.head.text;
    for (const span of expr.templateSpans) {
      out += resolveText(span.expression, consts) + span.literal.text;
    }
    return out;
  }
  return '';
}

function writesGlobalSettings(sf: ts.SourceFile): boolean {
  return writesTo(sf, [SETTINGS_PATH]);
}

const READ_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/**
 * Whether a `fetch` call's options make it a write: a `method` that is not GET, HEAD or
 * OPTIONS. Playwright's `request.fetch(url, { method })` and the global
 * `fetch(url, { method })` default to GET, so no options, or options with no `method`,
 * read. Anything this cannot read statically (options held in a variable, a spread, a
 * computed or non-literal `method`) counts as a write: a guard that cannot read a shape
 * fails closed.
 */
function fetchWrites(options: ts.Expression | undefined): boolean {
  if (!options) return false;
  if (!ts.isObjectLiteralExpression(options)) return true;
  let writes = false;
  for (const prop of options.properties) {
    if (ts.isSpreadAssignment(prop)) {
      writes = true;
      continue;
    }
    const key =
      prop.name && (ts.isIdentifier(prop.name) || ts.isStringLiteral(prop.name)) ? prop.name.text : undefined;
    if (prop.name && ts.isComputedPropertyName(prop.name)) writes = true;
    if (key !== 'method') continue;
    if (!ts.isPropertyAssignment(prop) || !ts.isStringLiteralLike(prop.initializer)) {
      writes = true;
      continue;
    }
    if (!READ_METHODS.has(prop.initializer.text.toUpperCase())) writes = true;
  }
  return writes;
}

/** `new Request(url, init)`: the method and the URL travel inside it, not in `fetch`'s own arguments. */
function asRequestObject(expr: ts.Expression | undefined): ts.NewExpression | undefined {
  return expr && ts.isNewExpression(expr) && ts.isIdentifier(expr.expression) && expr.expression.text === 'Request'
    ? expr
    : undefined;
}

/**
 * Whether `node` is a write call: `x.post|patch|put|delete(url, …)`, or a `fetch(url,
 * options)` (Playwright's `request.fetch` or the global one) whose options name a
 * mutating method (`fetchWrites`), or a `fetch(new Request(url, init))` whose `init`
 * does.
 */
function isWriteCall(node: ts.CallExpression): boolean {
  const callee = node.expression;
  if (ts.isPropertyAccessExpression(callee) && WRITE_METHODS.has(callee.name.text)) return true;
  const name = ts.isPropertyAccessExpression(callee)
    ? callee.name.text
    : ts.isIdentifier(callee)
      ? callee.text
      : undefined;
  if (name !== 'fetch') return false;
  const req = asRequestObject(node.arguments[0]);
  return fetchWrites(node.arguments[1]) || (!!req && fetchWrites(req.arguments?.[1]));
}

/** The URL argument of a write call: `fetch(new Request(url, …))`'s is inside the `Request`. */
function urlArgument(node: ts.CallExpression): ts.Expression | undefined {
  const arg = node.arguments[0];
  return asRequestObject(arg)?.arguments?.[0] ?? arg;
}

/** Whether `sf` makes a write call whose URL argument contains any of `needles`. */
function writesTo(sf: ts.SourceFile, needles: readonly string[]): boolean {
  const consts = collectStringConsts(sf);
  let found = false;
  function visit(node: ts.Node): void {
    if (found) return;
    if (ts.isCallExpression(node) && isWriteCall(node)) {
      const arg = urlArgument(node);
      // Only string-shaped arguments are inspected, so the route appearing in
      // a comment is invisible here — the same reason `capabilities.spec.ts`
      // parses instead of scanning text.
      const text = arg ? resolveText(arg, consts) : '';
      if (needles.some((needle) => text.includes(needle))) found = true;
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);
  return found;
}

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, import specifiers, allowlist
// membership. None of it is client-observable behaviour, and all of it changes
// shape when the suite is restructured. See docs/adr/0002-e2e-test-taxonomy.md.
test('instance-wide settings writes are confined to their allowlist', { tag: '@characterization' }, async () => {
  const hits: string[] = [];
  for (const [dir, prefix] of ROOTS) {
    for (const rel of await listSourceFiles(path.join(E2E_ROOT, dir), prefix)) {
      if (rel.startsWith('tests/guards/')) continue;
      const src = await readSpec(rel);
      if (writesGlobalSettings(ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true))) {
        hits.push(rel);
      }
    }
  }

  expect(
    hits.sort(),
    `${GLOBAL_SETTINGS_WRITE.name} is confined to an allowlist. ${GLOBAL_SETTINGS_WRITE.why}\n` +
      'To add a file, edit tests/guards/allowlist.ts and argue the blast radius in the ' +
      'diff: which group it writes, why nothing else reads it, and how teardown restores ' +
      'it. See docs/adr/0003.',
  ).toEqual([...GLOBAL_SETTINGS_WRITE.allow].sort());
});

/**
 * SSO spec PR S5: the OIDC configuration is instance-wide too. `auth_settings` (behind
 * `/api/accounts/oidc/settings/`: `public_base_url` and the password-login toggle) is a
 * CoreSettings group like the nine above, but is refused by `/api/core/settings/` and
 * written only through its own route; a provider row (`providers-admin/`) appears on
 * every user's login page. Both are written only by the `sso` project, which runs
 * against a scoped stack of its own (`tests/sso/scope.ts`), so the allowlist is a
 * directory rather than a file list.
 */
const OIDC_WRITE_PATHS = ['accounts/oidc/settings', 'accounts/oidc/providers-admin'] as const;
const OIDC_WRITE_DIR = 'tests/sso/';

test('instance-wide OIDC configuration writes are confined to tests/sso/', { tag: '@characterization' }, async () => {
  const hits: string[] = [];
  for (const [dir, prefix] of ROOTS) {
    for (const rel of await listSourceFiles(path.join(E2E_ROOT, dir), prefix)) {
      if (rel.startsWith('tests/guards/')) continue;
      const src = await readSpec(rel);
      if (writesTo(ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true), OIDC_WRITE_PATHS)) {
        hits.push(rel);
      }
    }
  }

  // Guards the guard: the sso project does write both, so an empty scan is this
  // detector being broken, not the suite being clean.
  expect(
    hits.length,
    'No write to the OIDC configuration found anywhere, although tests/sso/ makes them: ' +
      'this guard is broken, not the suite clean — check OIDC_WRITE_PATHS and writesTo.',
  ).toBeGreaterThan(0);
  expect(
    hits.filter((rel) => !rel.startsWith(OIDC_WRITE_DIR)).sort(),
    'A write to /api/accounts/oidc/settings/ or providers-admin/ outside tests/sso/. Both ' +
      'are instance-wide (password login off locks every password user out of the shared ' +
      'container), so they belong only to the sso project, on its own scoped stack.',
  ).toEqual([]);
});
