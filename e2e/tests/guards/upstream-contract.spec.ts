/**
 * `e2e-upstream/CONTRACT.md`'s declared version never drifts from
 * `e2e-upstream/package.json`'s.
 *
 * `CONTRACT.md` states, in its own "Bump policy" section, that a version bump
 * obligates an edit to that document — and that the two are "kept in sync by
 * the guard below". Without this, nothing enforces that a `package.json` bump
 * actually touched the document it is supposed to accompany: a bumped
 * version with a stale contract is worse than no contract at all, because it
 * reads as "reviewed and current" while describing an earlier provider. The
 * same reasoning `allowlist.ts` gives for `quarantine.spec.ts`'s original
 * principle applies here — a convention plus a README decays silently. This
 * does not.
 *
 * Purely syntactic, by design: this guard does not — and cannot — re-verify
 * that any guarantee or non-guarantee `CONTRACT.md` lists is still true of
 * the running provider. That is `e2e-upstream/test/*.test.ts`'s job, as
 * `CONTRACT.md`'s own "Enforcement" section says. This guard only proves the
 * two numbers agree.
 *
 * No container, no browser: both files are read straight off disk with
 * `node:fs/promises`, the same shape every other guard in this directory
 * uses.
 *
 * Verified by mutation: editing package.json's version from 1.1.0 to 1.1.1
 * failed with "e2e-upstream/CONTRACT.md declares version '1.1.0' but
 * e2e-upstream/package.json declares '1.1.1' …", naming both declared
 * versions; reverting to 1.1.0 passed.
 */
import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from './ast';

const CONTRACT_PATH = path.join(REPO_ROOT, 'e2e-upstream', 'CONTRACT.md');
const PACKAGE_JSON_PATH = path.join(REPO_ROOT, 'e2e-upstream', 'package.json');

/** `**Version:** 1.1.0` — the line CONTRACT.md's header declares its version on. */
const CONTRACT_VERSION_LINE = /^\*\*Version:\*\*\s*(\S+)\s*$/m;

function extractContractVersion(contract: string): string {
  const match = CONTRACT_VERSION_LINE.exec(contract);
  if (!match) {
    throw new Error(
      `${CONTRACT_PATH} has no line matching '**Version:** <x.y.z>' — this guard cannot read ` +
        'a version it cannot find, and a contract with no declared version is not a contract.',
    );
  }
  return match[1];
}

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, import specifiers, declared
// version strings. None of it is client-observable behaviour, and all of it
// changes shape when the suite is restructured. See
// docs/adr/0002-e2e-test-taxonomy.md.
test(
  "e2e-upstream/CONTRACT.md's declared version matches package.json's",
  { tag: '@characterization' },
  async () => {
    const [contract, packageJsonRaw] = await Promise.all([
      readFile(CONTRACT_PATH, 'utf8'),
      readFile(PACKAGE_JSON_PATH, 'utf8'),
    ]);

    const contractVersion = extractContractVersion(contract);
    const packageVersion = (JSON.parse(packageJsonRaw) as { version?: unknown }).version;

    expect(
      typeof packageVersion === 'string' && packageVersion.length > 0,
      `${PACKAGE_JSON_PATH} has no string "version" field — this guard cannot compare against a ` +
        'version that does not exist.',
    ).toBe(true);

    expect(
      contractVersion,
      `e2e-upstream/CONTRACT.md declares version '${contractVersion}' but ` +
        `e2e-upstream/package.json declares '${String(packageVersion)}'. A version bump obligates ` +
        "an edit to CONTRACT.md — see its own 'Bump policy' section — and the reverse holds too: " +
        'editing the contract for a real change obligates the matching package.json bump.',
    ).toBe(packageVersion);
  },
);
