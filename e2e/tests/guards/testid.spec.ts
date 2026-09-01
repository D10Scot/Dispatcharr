/**
 * Every surface testId the suite drives exists in the frontend source.
 *
 * `tests/frontend/helpers.ts` says testIds are "what a test waits on, and
 * nothing here selects by text: text selectors couple the suite to UI copy".
 * That makes them a contract between `frontend/src/` and this suite, with
 * nothing enforcing it: rename one in the frontend and the failure surfaces as
 * a `getByTestId` timeout that reads like a broken test rather than a broken
 * contract. `e2e/README.md` already observes exactly that and could not
 * prevent it. `docs/adr/0003-e2e-frontend-and-shared-state-contract.md` is the
 * record.
 *
 * Deliberately one-directional. It asserts every testId the suite *uses*
 * exists in the frontend, not that every `data-testid` in the frontend is
 * used: unused handles are harmless, and asserting on them would make adding
 * one to a component a failing build.
 *
 * Reads JSX with a regular expression rather than the TypeScript AST the other
 * guards use, and that inconsistency is deliberate: the target is
 * `frontend/src/**`, which is JSX this suite does not own and does not
 * typecheck, and a `data-testid` attribute has no ambiguity a parser would
 * resolve. The AST is worth it where prose and code must be told apart
 * (`capabilities.spec.ts`); here there is nothing to tell apart.
 *
 * Verified by mutation: renaming `stats-page` in `frontend/src/` failed this
 * check naming the Stats surface; restoring it passed.
 */
import { test, expect } from '@playwright/test';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from './ast';
import { SURFACES } from '../frontend/helpers';

const FRONTEND_SRC = path.join(REPO_ROOT, 'frontend', 'src');

/** Matches the JSX attribute `data-testid="x"` and the object form `'data-testid': 'x'`. */
const TESTID_PATTERN = /data-testid\s*[=:]\s*["'`]([^"'`]+)["'`]/g;

async function collectTestIds(dir: string): Promise<Set<string>> {
  const found = new Set<string>();
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      for (const id of await collectTestIds(full)) found.add(id);
    } else if (/\.(jsx?|tsx?)$/.test(entry.name)) {
      const src = await readFile(full, 'utf8');
      for (const match of src.matchAll(TESTID_PATTERN)) found.add(match[1]);
    }
  }
  return found;
}

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, import specifiers, allowlist
// membership. None of it is client-observable behaviour, and all of it changes
// shape when the suite is restructured. See docs/adr/0002-e2e-test-taxonomy.md.
test('every surface testId the suite drives exists in frontend/src', { tag: '@characterization' }, async () => {
  const inFrontend = await collectTestIds(FRONTEND_SRC);

  // Guards the guard: if the scan ever returns nothing — a moved directory, a
  // changed attribute spelling — every surface would be "missing" and the
  // failure would point at the frontend instead of at this file.
  expect(
    inFrontend.size,
    `No data-testid attributes found anywhere under ${FRONTEND_SRC}. That is this ` +
      'guard being broken, not the frontend being wrong — check the path and TESTID_PATTERN.',
  ).toBeGreaterThan(0);

  const missing = SURFACES.filter((s) => !inFrontend.has(s.testId)).map(
    (s) => `${s.name} → data-testid="${s.testId}" (${s.route})`,
  );

  expect(
    missing,
    'A surface testId in tests/frontend/helpers.ts has no matching data-testid in ' +
      'frontend/src. Either the frontend renamed it — restore it, or update SURFACES in ' +
      'the same PR — or the handle was never added. See docs/adr/0003.',
  ).toEqual([]);
});
