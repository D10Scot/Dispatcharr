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
 * whole settings *group* — eight of them (`stream_settings`, `dvr_settings`,
 * `backup_settings`, `proxy_settings`, `network_access`, `system_settings`,
 * `epg_settings`, `user_limit_settings`). Every one is instance-wide, so there
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
 * and is invisible to a scan of `tests/` alone.
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { GLOBAL_SETTINGS_WRITE } from './allowlist';
import { E2E_ROOT, listTsFiles, readSpec, ROOTS } from './ast';

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
  const consts = collectStringConsts(sf);
  let found = false;
  function visit(node: ts.Node): void {
    if (found) return;
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      WRITE_METHODS.has(node.expression.name.text)
    ) {
      const arg = node.arguments[0];
      // Only string-shaped arguments are inspected, so the route appearing in
      // a comment is invisible here — the same reason `capabilities.spec.ts`
      // parses instead of scanning text.
      if (arg && resolveText(arg, consts).includes(SETTINGS_PATH)) found = true;
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
    for (const rel of await listTsFiles(path.join(E2E_ROOT, dir), prefix)) {
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
