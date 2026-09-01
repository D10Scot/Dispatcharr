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
 * MODE: warning. PR A ships this reporting-only so the retag can land as its
 * own reviewable diff; PR B flips `MODE` to 'blocking' in one line once every
 * test carries a tag. A guard that lands red is a guard someone disables.
 *
 * The unverifiable check below does NOT wait on that flip — see its comment.
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

const MODE: 'warning' | 'blocking' = 'warning';

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

test('every test declares @contract or @characterization', async () => {
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

  // Fails closed, and does so in BOTH modes — unlike the untagged findings
  // below, which are warnings until PR B. An unreadable shape is a hole in the
  // checker, not a retag task, so it must never wait on the flip.
  expect(
    unverifiable.sort(),
    'A test declaration passes a details argument this checker cannot read, so its tags ' +
      'cannot be verified. Inline the object literal, or pin the location in ' +
      'KNOWN_UNVERIFIABLE with a reason.',
  ).toEqual(KNOWN_UNVERIFIABLE);

  const report = findings.map((f) => `  ${f.location} — ${f.detail}`).join('\n');

  if (MODE === 'warning') {
    if (findings.length > 0) {
      console.warn(
        `[tags] ${tagged} tagged, ${findings.length} not yet tagged. ` +
          `This guard is in warning mode until PR B's retag lands.\n${report}`,
      );
    }
    expect(tagged + findings.length).toBeGreaterThan(0);
    return;
  }

  expect(
    findings,
    `Every test must declare exactly one of ${TAGS.contract} / ${TAGS.characterization}. ` +
      `${TAGS.contract} is the default and needs no justification; ` +
      `${TAGS.characterization} must say in a comment which implementation fact it pins. ` +
      `See docs/adr/0002-e2e-test-taxonomy.md.\n${report}`,
  ).toEqual([]);
});
