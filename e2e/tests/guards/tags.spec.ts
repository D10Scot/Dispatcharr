/**
 * Every test declares whether it is portable behaviour or a pin on this
 * implementation.
 *
 * The suite exists to be the gate for extracting the streaming relay out of
 * the Django workers (`CLAUDE.md`). On that branch both kinds of test go red
 * together — `@contract` because something broke, `@characterization` because
 * something moved, which is the point of the branch. Without a per-test
 * declaration the two are indistinguishable and the suite is not a gate.
 *
 * `docs/adr/0002-e2e-test-taxonomy.md` states what each tag promises and what
 * a `@characterization` test owes in its comment.
 *
 * Blocking. Every test declaration in the suite carries a tag; an untagged one
 * fails this check. It shipped in warning mode for exactly one pull request so
 * the 196-tag retag could land as its own reviewable diff — a guard that lands
 * red is a guard someone disables — and flipped when the retag landed.
 *
 * Verified by mutation. Setting MODE to 'blocking' failed listing all 191
 * declarations; tagging one dropped it to 190; tagging one with both tags
 * reported it as "carries both tags"; and passing a details object by
 * reference — `const d = { tag: '@contract' }; test('…', d, fn)` — failed
 * **in warning mode**, which is the check that matters: a hole in the checker
 * is not a retag task and must not wait on the flip.
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { E2E_ROOT, findTestCalls, listSpecFiles, readSpec, readTags } from './ast';

export const TAGS = {
  contract: '@contract',
  characterization: '@characterization',
} as const;

const VALID = new Set<string>([TAGS.contract, TAGS.characterization]);

/**
 * Locations this checker cannot read, each pinned with a reason.
 *
 * Empty, and it should stay that way. An entry here is a test whose tag
 * nobody can verify — acceptable only when the shape is genuinely unreadable
 * and the reason says so. `pageerrors-enforcement.spec.ts` carries the same
 * construct for the same reason.
 */
const KNOWN_UNVERIFIABLE: string[] = [];

type Finding = { location: string; detail: string };

/**
 * Distinguishes "no details object" from "a details object this checker
 * cannot read".
 *
 * `readTags` returns `undefined` for both, which is fine for counting tags and
 * wrong for failing closed: `test(title, someSharedDetails, body)` — a details
 * object built elsewhere and passed by reference — is a three-argument call
 * whose tags are genuinely unknowable by static reading, and it must fail
 * rather than be reported as merely untagged.
 */
function isUnreadableDetails(args: readonly ts.Expression[]): boolean {
  return args.length >= 3 && !ts.isObjectLiteralExpression(args[1]);
}

// @characterization: every test in this file asserts facts about this
// repository's own source tree — file paths, import specifiers, allowlist
// membership. None of it is client-observable behaviour, and all of it changes
// shape when the suite is restructured. See docs/adr/0002-e2e-test-taxonomy.md.
test('every test declares @contract or @characterization', { tag: '@characterization' }, async () => {
  const files = await listSpecFiles(path.join(E2E_ROOT, 'tests'), 'tests');
  const findings: Finding[] = [];
  const unverifiable: string[] = [];
  let tagged = 0;

  for (const rel of files) {
    for (const call of findTestCalls(await readSpec(rel), rel)) {
      const location = `${rel}:${call.line}`;

      // Two independent ways a declaration can be unreadable: the walker could
      // not classify the call at all, or the call is a three-argument form
      // whose details object is not an inline literal.
      if (call.unverifiableReason !== undefined || isUnreadableDetails(call.args)) {
        unverifiable.push(location);
        continue;
      }

      const own = readTags(call.args);
      const all = [...(own ?? []), ...call.describeTags];
      const recognised = all.filter((t) => VALID.has(t));

      if (all.length === 0) {
        findings.push({
          location,
          detail: 'no tag, and none inherited from an enclosing describe',
        });
      } else if (recognised.length === 0) {
        findings.push({
          location,
          detail: `tags ${JSON.stringify(all)} include neither ${TAGS.contract} nor ${TAGS.characterization}`,
        });
      } else if (recognised.length > 1) {
        findings.push({
          location,
          detail: `carries both tags (${recognised.join(', ')}); a test is one or the other`,
        });
      } else {
        tagged++;
      }
    }
  }

  // Fails closed on a shape the checker cannot read, separately from the
  // untagged findings below. This assertion was live even while the guard was
  // in warning mode: an unreadable shape is a hole in the checker, not a retag
  // task, and never waited on the flip.
  expect(
    unverifiable.sort(),
    'A test declaration, or an enclosing describe, passes a details argument this checker ' +
      'cannot read, so its tags cannot be verified. Inline the object literal, or pin the ' +
      'location in KNOWN_UNVERIFIABLE with a reason.',
  ).toEqual(KNOWN_UNVERIFIABLE);

  const report = findings.map((f) => `  ${f.location} — ${f.detail}`).join('\n');

  // Guards the guard: a walker that silently found nothing would pass this
  // test while enforcing nothing at all.
  expect(
    tagged + findings.length,
    'No test declarations found anywhere under tests/. That is this guard being ' +
      'broken, not the suite being untagged — check listSpecFiles and findTestCalls.',
  ).toBeGreaterThan(150);

  expect(
    findings,
    `Every test must declare exactly one of ${TAGS.contract} / ${TAGS.characterization}. ` +
      `${TAGS.contract} is the default and needs no justification; ` +
      `${TAGS.characterization} must say in a comment which implementation fact it pins. ` +
      `See docs/adr/0002-e2e-test-taxonomy.md.\n${report}`,
  ).toEqual([]);
});
