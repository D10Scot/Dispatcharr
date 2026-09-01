# G11 — Migration-Gate Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the E2E suite legible as a migration gate — every test tagged `@contract` or
`@characterization`, four enforcement guards that fail CI rather than rot, and a full-run CI
mode required on migration branches.

**Architecture:** A new container-free `guards` Playwright project holds four static-analysis
specs that parse the suite's own source with the TypeScript compiler API, reusing one shared
walker extracted from the existing `pageerrors-enforcement.spec.ts`. Tags use Playwright's
native `{ tag: … }` option. CI grows a cheap `guards` job, a matrix built from a `changes`-job
output so full mode can add `lifecycle-upgrade`, and a reworked `lifecycle-tests.yml` that can
report a required check.

**Tech Stack:** Playwright 1.62.1 (native test tags, added 1.42), TypeScript 5.7.2 compiler API
(already a devDependency), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-01-e2e-migration-gate-design.md`

## Global Constraints

- **Baseline is `origin/main` `76db0332`.** 77 spec files, 190 test declarations, 20
  `test.fail()` pins across 17 files, 2 files using `test.describe`. Re-derive before Task 11;
  if the numbers moved, a test PR landed and the retag scope grew.
- **Never patch the product.** `apps/`, `core/`, `dispatcharr/`, `frontend/` are out of bounds
  for this goal. Found a product bug? `gh issue create --repo D10Scot/Dispatcharr` — the
  `--repo` flag is mandatory, this checkout is a fork and `gh` otherwise files on upstream's
  public tracker.
- **Two PRs.** Tasks 1–10 are PR A (machinery). Tasks 11–15 are PR B (the retag). The tag guard
  ships **warning** in PR A and flips to **blocking** in PR B's final task.
- **Every guard is verified by mutation**, and the mutation is recorded in the guard's own
  comment. A guard nobody proved can fail is decoration.
- **Fail closed.** Every guard puts each finding in one of three buckets — pass, fail, or
  *unverifiable* — and unverifiable fails, unless pinned in a `KNOWN_UNVERIFIABLE` constant
  with a written reason. Inherited from `pageerrors-enforcement.spec.ts`; do not weaken it.
- **Workflow edits must leave the file zizmor-clean.** The repo is at zero findings and the
  `PostToolUse` hook blocks on any finding in an edited workflow. Every `uses:` stays a
  40-char SHA with a trailing version comment; every `actions/checkout` keeps
  `persist-credentials: false`.
- **Full-mode trigger is `migration/**` only**, plus a `workflow_dispatch` boolean. Not
  `relay/**` — one prefix, per the spec.
- Run `npm run typecheck` in `e2e/` after every task that touches `.ts`. It is the gate the
  hook enforces and it is not optional.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `e2e/tests/guards/ast.ts` | The one AST walker. Finds test declarations, classifies shapes, fails closed. Consumed by every guard. |
| `e2e/tests/guards/allowlist.ts` | Every capability allowlist in one place, so an escape hatch is one reviewable diff. |
| `e2e/tests/guards/tags.spec.ts` | Every test carries exactly one of the two tags. |
| `e2e/tests/guards/capabilities.spec.ts` | Grey-box capability use confined to the allowlist. Replaces `quarantine.spec.ts`. |
| `e2e/tests/guards/testid.spec.ts` | Every `SURFACES` testId exists in `frontend/src/`. |
| `e2e/tests/guards/global-mutation.spec.ts` | Writes to `/api/core/settings/` confined to the allowlist. |
| `docs/adr/0002-e2e-test-taxonomy.md` | What each tag promises. |
| `docs/adr/0003-e2e-frontend-and-shared-state-contract.md` | The testId contract and shared-instance mutation rules. |

**Moved**

| From | To | Why |
|---|---|---|
| `e2e/tests/streaming-greybox/quarantine.spec.ts` | deleted, folded into `guards/capabilities.spec.ts` | Its single-string scan becomes one row of the capability table. |
| `e2e/tests/frontend/pageerrors-enforcement.spec.ts` | `e2e/tests/guards/pageerrors-enforcement.spec.ts` | Opens no page, needs no container. Its rule is directory-scoped and survives the move. |

**Modified**

| File | Change |
|---|---|
| `e2e/playwright.config.ts` | Add the `guards` project. |
| `e2e/package.json` | Add `test:guards`; update the `test` script's message. |
| `e2e/fixtures/greybox/redis.ts` | `GREYBOX_ALLOWLIST` moves to `tests/guards/allowlist.ts`. |
| `.github/workflows/e2e-tests.yml` | `guards` job; matrix from `fromJSON`; full-mode detection. |
| `.github/workflows/lifecycle-tests.yml` | Drop PR `paths:`; drop `suites`' own `if:`; add `changes` + `Lifecycle result`. |
| `e2e/README.md` | Guards project, the taxonomy, the corrected CI rules. |
| `e2e/COVERAGE.md` | Guard rows. |
| `CLAUDE.md` | The `migration/**` convention. |
| All 77 spec files | Tags (PR B). |

---

# PR A — Machinery

### Task 1: The `guards` project and the shared AST walker

Creates the project, extracts the walker from the existing enforcement spec, and moves that
spec onto it. Deliverable: `npm run test:guards` runs, and the pageErrors rule still holds.

**Files:**
- Create: `e2e/tests/guards/ast.ts`
- Move: `e2e/tests/frontend/pageerrors-enforcement.spec.ts` → `e2e/tests/guards/pageerrors-enforcement.spec.ts`
- Modify: `e2e/playwright.config.ts`, `e2e/package.json`

**Interfaces:**
- Produces:
  - `E2E_ROOT: string`, `REPO_ROOT: string`
  - `TEST_HOOK_NAMES: ReadonlySet<string>`
  - `isTestCallee(expr: ts.Expression): boolean`
  - `isDescribeCallee(expr: ts.Expression): boolean`
  - `readTags(args: readonly ts.Expression[]): string[] | undefined`
  - `type TestCall = { node: ts.CallExpression; args: readonly ts.Expression[]; line: number; describeTags: readonly string[] }`
  - `findTestCalls(src: string, fileName: string): TestCall[]`
  - `listSpecFiles(absDir: string, relPrefix?: string): Promise<string[]>`
  - `listTsFiles(absDir: string, relPrefix?: string): Promise<string[]>`
  - `readSpec(rel: string): Promise<string>`

- [ ] **Step 1: Create the shared walker**

Create `e2e/tests/guards/ast.ts`:

```ts
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
 * `undefined` when there is no details object at all — which the caller must
 * distinguish from "a details object with no tag", because only the first is
 * ambiguous with an ordinary two-argument call.
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
```

- [ ] **Step 2: Add the `guards` project to `playwright.config.ts`**

Insert immediately after the `bootstrap` project:

```ts
    {
      // Static analysis over this repository's own source. No container, no
      // browser, no fixtures, no `dependencies` — the only project here that
      // needs no running instance, which is why it gets its own CI job rather
      // than a matrix row that would download a 3 GB image to read text files.
      //
      // Everything here enforces a rule that would otherwise live in a README
      // and rot. `docs/adr/0002` and `0003` say what they promise.
      name: 'guards',
      testDir: './tests/guards',
      // Sub-second in practice; the global 30s is already generous.
      workers: 1,
      fullyParallel: false,
    },
```

- [ ] **Step 3: Add the npm script**

In `e2e/package.json`, add `"test:guards": "playwright test --project=guards"` and add
`test:guards` to the list in the `test` script's message.

- [ ] **Step 4: Move the pageErrors spec and refactor it onto the walker**

Move it with `git mv` from `e2e/tests/frontend/` to `e2e/tests/guards/`.

Then in the moved file:
- Delete its local `TEST_HOOK_NAMES`, `isTestCallee`, and the `findOffenses` walker body.
- Import from `./ast`: `import { findTestCalls, listSpecFiles, readSpec, E2E_ROOT } from './ast';`
- Rewrite `findOffenses` to map over `findTestCalls(src, fileName)`, applying the existing
  `judge(call.args)` to each. Keep `judge`, `CallVerdict`, `Offense` and `KNOWN_UNVERIFIABLE`
  exactly as they are — this task changes where the walker lives, not any verdict.
- Point the directory walk at `tests/frontend` explicitly rather than `__dirname`, since the
  file no longer lives there: `const TARGET_DIR = 'tests/frontend';`
- **Delete `SELF_FILE` and its exclusion.** The file being scanned and the file doing the
  scanning are now in different directories, so the self-exclusion is dead. Replace its comment
  with one sentence saying the move removed the need.
- Keep the header comment. Add one paragraph recording that the walker moved to `./ast`, and
  why: three guards were about to re-derive "what is a test declaration".

- [ ] **Step 5: Verify the move changed no verdicts**

Run: `cd e2e && npx playwright test --project=guards`
Expected: PASS, 1 test — `every test() under tests/frontend/ destructures pageErrors`.

Then prove it still bites. Temporarily add to any file in `e2e/tests/frontend/`:

```ts
test('temporary guard check', async ({ page }) => { void page; });
```

Run again. Expected: FAIL, naming that file and line as `missing`.
**Revert the temporary test.**

- [ ] **Step 6: Typecheck and commit**

Run `npm run typecheck` in `e2e/`. Stage `e2e/tests/guards/ast.ts`,
`e2e/tests/guards/pageerrors-enforcement.spec.ts`, `e2e/playwright.config.ts`,
`e2e/package.json`, and the deletion of the old path. Commit as:
`test(e2e): add the container-free guards project and extract the AST walker`

---

### Task 2: The tag guard, in warning mode

**Files:**
- Create: `e2e/tests/guards/tags.spec.ts`

**Interfaces:**
- Consumes: `findTestCalls`, `readTags`, `listSpecFiles`, `readSpec`, `E2E_ROOT` from `./ast`
- Produces: `TAGS = { contract: '@contract', characterization: '@characterization' } as const`

- [ ] **Step 1: Write the guard**

Create `e2e/tests/guards/tags.spec.ts`:

```ts
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

      if (isUnreadableDetails(call.args)) {
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
```

- [ ] **Step 2: Run it and record the baseline**

Run: `cd e2e && npx playwright test --project=guards`
Expected: PASS, with a console warning reporting `0 tagged, 190 not yet tagged`.

**If the count is not 190, stop.** A test PR landed since `76db0332` and PR B's scope has
grown; re-derive the numbers in Global Constraints before continuing.

- [ ] **Step 3: Prove it can fail — mutation check**

1. Temporarily set `MODE` to `'blocking'`. Run. Expected: FAIL, listing 190 locations.
2. Temporarily tag one test `{ tag: '@contract' }`. Expected: 189 findings.
3. Temporarily tag one `{ tag: ['@contract', '@characterization'] }`. Expected: reported as
   `carries both tags`.
4. Restore `MODE` to `'warning'`, then temporarily write a test as
   `const d = { tag: '@contract' }; test('x', d, async () => {});`. Expected: **FAIL** even in
   warning mode — the unverifiable check does not wait on the flip.

**Revert all four, leaving `MODE` at `'warning'`.** Record the result in the header comment in
one sentence, naming mutation 4 specifically — it is the one that proves the checker fails
closed rather than silently passing a shape it cannot read.

- [ ] **Step 4: Typecheck and commit**

Run `npm run typecheck`. Stage `e2e/tests/guards/tags.spec.ts`. Commit as:
`test(e2e): add the test taxonomy guard, warning until the retag lands`

---

### Task 3: The capability guard

Replaces `quarantine.spec.ts`'s single-string scan with a four-dimension allowlist.

**Files:**
- Create: `e2e/tests/guards/allowlist.ts`, `e2e/tests/guards/capabilities.spec.ts`
- Delete: `e2e/tests/streaming-greybox/quarantine.spec.ts`
- Modify: `e2e/fixtures/greybox/redis.ts`

**Interfaces:**
- Produces: `type Capability = { name: string; why: string; allow: readonly string[] }`, and the
  constants `CONTAINER_LIFECYCLE`, `SUBPROCESS`, `GREYBOX_REDIS`, `CONTAINER_INTROSPECTION`,
  `FIXTURE_ALLOW`. Task 5 appends `GLOBAL_SETTINGS_WRITE` to the same file.

- [ ] **Step 1: Establish the real lists before writing them**

Run each, and use the output — not this plan's guesses — as the allowlist contents:

```bash
cd e2e
grep -rln "node:child_process\|from 'child_process'" tests fixtures setup
grep -rln "greybox/redis" tests fixtures setup
grep -rn "instance" tests --include=*.ts | grep -E "\{[^}]*\binstance\b[^}]*\}"
grep -rln "pgrep\|manage.py" tests fixtures setup
```

- [ ] **Step 2: Write the allowlist**

Create `e2e/tests/guards/allowlist.ts`:

```ts
/**
 * Every grey-box escape hatch in the suite, and exactly who may use it.
 *
 * `quarantine.spec.ts` established the principle for one of these — "a
 * convention plus a README decays silently. This does not." — and policed the
 * string `greybox/redis` only. `node:child_process` was already imported by a
 * second spec and would have been accepted silently in any new one.
 *
 * These capabilities are the ones that break when the relay moves out of the
 * Django workers, so keeping their use to a short, deliberate list is what
 * makes the rest of the suite portable. Adding a file here is a reviewable
 * decision; adding one by accident is not possible.
 *
 * NOT an import-graph check, and this is worth recording so it is not
 * re-attempted: `e2e/fixtures/index.ts` imports and re-exports `./instance`,
 * which imports `node:child_process`, and `e2e/README.md`'s "Writing a test"
 * makes importing `../../fixtures` mandatory. Every test therefore
 * *transitively* reaches subprocess execution, and a reachability guard flags
 * all 77 spec files. Use is the only thing worth policing.
 */
export type Capability = {
  /** Appears in the failure message. */
  name: string;
  /** Why it is grey-box — the sentence a reviewer needs to judge an addition. */
  why: string;
  /** Files permitted to use it, relative to `e2e/`, sorted. */
  allow: readonly string[];
};

export const CONTAINER_LIFECYCLE: Capability = {
  name: 'the `instance` fixture (container lifecycle)',
  why: 'Restarts, replaces and upgrades the container — the subject of the lifecycle projects, and meaningless once the relay is a separate process.',
  allow: [
    // Fill from Step 1.
  ],
};

export const SUBPROCESS: Capability = {
  name: 'a direct `node:child_process` import',
  why: 'Runs commands against the container host. Nothing a client can observe.',
  allow: [
    // Fill from Step 1.
  ],
};

export const GREYBOX_REDIS: Capability = {
  name: 'the grey-box Redis helper',
  why: 'Reads Redis key shapes directly. The keys are internal and the extraction is expected to change them.',
  allow: [
    // Fill from Step 1 — this is the old GREYBOX_ALLOWLIST.
  ],
};

export const CONTAINER_INTROSPECTION: Capability = {
  name: 'a container-introspection command in a string literal (`pgrep`, `docker `, `manage.py`)',
  why: 'Observes process tables, container state or Django internals rather than a client-facing surface.',
  allow: [
    // Fill from Step 1.
  ],
};

/**
 * Fixtures and setup are scanned too, with their own entries.
 *
 * The goal definition says `e2e/tests/**`. Scanning only that moves the hole
 * rather than closing it: a grey-box helper added under `fixtures/` and
 * imported from a test would be invisible. These are the machinery that
 * legitimately owns the capability.
 */
export const FIXTURE_ALLOW: readonly string[] = [
  // Fill from Step 1.
];
```

Every entry gets a trailing comment saying why that file legitimately holds the capability. An
entry without a reason is an entry nobody can review.

- [ ] **Step 3: Write the guard**

Create `e2e/tests/guards/capabilities.spec.ts`:

```ts
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import {
  CONTAINER_INTROSPECTION,
  CONTAINER_LIFECYCLE,
  FIXTURE_ALLOW,
  GREYBOX_REDIS,
  SUBPROCESS,
  type Capability,
} from './allowlist';
import { E2E_ROOT, findTestCalls, listTsFiles, readSpec } from './ast';

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
 * This is the distinction the whole guard turns on: `docker` appears in
 * comments in three specs today, none of them a grey-box escape. Comments are
 * trivia to the parser and this walk never reaches them.
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

function usesInstanceFixture(src: string, rel: string): boolean {
  return findTestCalls(src, rel).some((call) => {
    const body = call.args[call.args.length - 1];
    if (!body || (!ts.isArrowFunction(body) && !ts.isFunctionExpression(body))) return false;
    const param = body.parameters[0];
    if (!param || !ts.isObjectBindingPattern(param.name)) return false;
    return param.name.elements.some(
      (el) => (el.propertyName ?? el.name).getText() === 'instance',
    );
  });
}

async function usersOf(
  detect: (sf: ts.SourceFile, src: string, rel: string) => boolean,
  scanFixtures: boolean,
): Promise<string[]> {
  const roots: [string, string][] = scanFixtures
    ? [
        ['tests', 'tests'],
        ['fixtures', 'fixtures'],
        ['setup', 'setup'],
      ]
    : [['tests', 'tests']];
  const hits: string[] = [];
  for (const [dir, prefix] of roots) {
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

async function expectConfined(
  cap: Capability,
  detect: (sf: ts.SourceFile, src: string, rel: string) => boolean,
  extraAllowed: readonly string[] = [],
): Promise<void> {
  const actual = await usersOf(detect, extraAllowed.length > 0);
  const allowed = [...cap.allow, ...extraAllowed].sort();
  // `toEqual`, not `toContain`: removing a legitimate use must also be a
  // deliberate edit, or the allowlist rots in the other direction.
  expect(
    actual,
    `${cap.name} is confined to an allowlist. ${cap.why}\n` +
      'To add a file, edit tests/guards/allowlist.ts and say in the diff why it needs this. ' +
      'See docs/adr/0002 — anything here is @characterization by construction.',
  ).toEqual(allowed);
}

test('the container-lifecycle fixture is confined to the lifecycle projects', async () => {
  await expectConfined(CONTAINER_LIFECYCLE, (_sf, src, rel) => usesInstanceFixture(src, rel));
});

test('direct subprocess execution is confined to its allowlist', async () => {
  await expectConfined(
    SUBPROCESS,
    (sf) => importsModule(sf, (s) => s === 'node:child_process' || s === 'child_process'),
    FIXTURE_ALLOW,
  );
});

test('only allowlisted specs import the grey-box Redis helper', async () => {
  await expectConfined(
    GREYBOX_REDIS,
    (sf) => importsModule(sf, (s) => s.endsWith('greybox/redis')),
    FIXTURE_ALLOW,
  );
});

test('container-introspection commands are confined to their allowlist', async () => {
  await expectConfined(
    CONTAINER_INTROSPECTION,
    (sf) => hasStringLiteralContaining(sf, INTROSPECTION_MARKERS),
    FIXTURE_ALLOW,
  );
});
```

Note: `FIXTURE_ALLOW` is passed to three capabilities but each needs only its own subset. If
passing the whole list makes a guard accept a fixture that should not hold that capability,
split `FIXTURE_ALLOW` per capability rather than widening it.

- [ ] **Step 4: Reconcile against reality**

Run: `cd e2e && npx playwright test --project=guards`

The four tests will fail on first run with the actual sets. **Read each diff and decide per
file** — legitimate (add to `allowlist.ts` with a reason) or an escape that should not exist
(report it; do not silently allow it). Re-run until all four pass.

- [ ] **Step 5: Delete the old quarantine spec and relocate its constant**

Remove `e2e/tests/streaming-greybox/quarantine.spec.ts` with `git rm`. In
`e2e/fixtures/greybox/redis.ts`, delete `GREYBOX_ALLOWLIST` and leave a one-line comment
pointing at `tests/guards/allowlist.ts`. Fix any import that breaks.

- [ ] **Step 6: Prove it bites — four mutations**

1. Add `import { execSync } from 'node:child_process';` to `tests/seeded/hdhr.spec.ts` → FAIL.
2. Add `// we run pgrep here` as a **comment** to the same file → **PASS**. This is the
   regression that justifies parsing over grep.
3. Add `const cmd = 'pgrep -x ffmpeg';` as code → FAIL.
4. Destructure `instance` in a `tests/seeded/` test → FAIL.

**Revert all four.** Record mutation 2 in the header comment.

- [ ] **Step 7: Typecheck and commit**

Run `npm run typecheck`. Stage the guards directory, the deleted quarantine spec, and
`e2e/fixtures/greybox/redis.ts`. Commit as:
`test(e2e): generalise the quarantine guard to a capability allowlist`

---

### Task 4: The `data-testid` contract guard

**Files:**
- Create: `e2e/tests/guards/testid.spec.ts`

- [ ] **Step 1: Write the guard**

```ts
/**
 * Every surface testId the suite drives exists in the frontend source.
 *
 * `tests/frontend/helpers.ts` says testIds are "what a test waits on, and
 * nothing here selects by text: text selectors couple the suite to UI copy".
 * That makes the testIds a contract between `frontend/src/` and this suite,
 * with nothing enforcing it: rename one in the frontend and the failure
 * surfaces as a `getByTestId` timeout that reads like a broken test.
 * `e2e/README.md` already observes exactly that and could not prevent it.
 *
 * Deliberately one-directional. It asserts every testId the suite *uses*
 * exists in the frontend, not that every `data-testid` in the frontend is
 * used — unused handles are harmless, and asserting on them would make adding
 * one to a component a failing build.
 */
import { test, expect } from '@playwright/test';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from './ast';
import { SURFACES } from '../frontend/helpers';

const FRONTEND_SRC = path.join(REPO_ROOT, 'frontend', 'src');

async function collectTestIds(dir: string): Promise<Set<string>> {
  const found = new Set<string>();
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      for (const id of await collectTestIds(full)) found.add(id);
    } else if (/\.(jsx?|tsx?)$/.test(entry.name)) {
      const src = await readFile(full, 'utf8');
      // Matches the JSX attribute `data-testid="x"` and the object form
      // `'data-testid': 'x'` — both appear in this frontend.
      for (const m of src.matchAll(/data-testid\s*[=:]\s*["'`]([^"'`]+)["'`]/g)) {
        found.add(m[1]);
      }
    }
  }
  return found;
}

test('every surface testId the suite drives exists in frontend/src', async () => {
  const inFrontend = await collectTestIds(FRONTEND_SRC);
  const missing = SURFACES.filter((s) => !inFrontend.has(s.testId)).map(
    (s) => `${s.name} → data-testid="${s.testId}" (${s.route})`,
  );
  expect(
    missing,
    'A surface testId in tests/frontend/helpers.ts has no matching data-testid in ' +
      'frontend/src. Either the frontend renamed it — restore it, or update SURFACES in the ' +
      'same PR — or the handle was never added. See docs/adr/0003.',
  ).toEqual([]);
});
```

This guard reads JSX with a regex rather than the TS AST, deliberately: the target is
`frontend/src/**` JSX, not this suite's TypeScript, and a `data-testid` attribute has no
ambiguity a parser would resolve. Say so in the header comment so the inconsistency with the
other guards is a decision rather than an oversight.

- [ ] **Step 2: Run it**

Run: `cd e2e && npx playwright test --project=guards -g testId`
Expected: PASS, all 9 surfaces resolved.

- [ ] **Step 3: Mutation check**

Rename one `data-testid` in `frontend/src/` that the suite uses (e.g. `stats-page`). Re-run.
Expected: FAIL naming that surface. **Revert.** Record in the header comment.

- [ ] **Step 4: Typecheck and commit**

Run `npm run typecheck`. Stage `e2e/tests/guards/testid.spec.ts`. Commit as:
`test(e2e): enforce the frontend data-testid contract`

---

### Task 5: The global-mutation guard

**Files:**
- Create: `e2e/tests/guards/global-mutation.spec.ts`
- Modify: `e2e/tests/guards/allowlist.ts`

- [ ] **Step 1: Establish the allowlist from the tree**

```bash
cd e2e && grep -rn "core/settings" tests --include=*.ts
```

Expected today: `failover-buffering.spec.ts` (raises `buffering_speed` in `proxy_settings`) and
`vod-redirect-profile.spec.ts` (`default_stream_profile` in `stream_settings`). Record what is
actually found.

- [ ] **Step 2: Append the capability to `allowlist.ts`**

```ts
/**
 * Writes to `/api/core/settings/` — every one of which is instance-wide.
 *
 * `core/models.py:CoreSettings` is not one row per setting: `key` is unique,
 * `value` is a JSONField, and each row is a whole settings *group* — eight of
 * them (`stream_settings`, `dvr_settings`, `backup_settings`,
 * `proxy_settings`, `network_access`, `system_settings`, `epg_settings`,
 * `user_limit_settings`). So "any write to that endpoint" is exact, needs no
 * key list to maintain, and cannot be defeated by a group nobody enumerated.
 *
 * Serialising a project is NOT a substitute for this list.
 * `CoreSettings._get_group` caches each group in Redis for 300s, and
 * `_REDIRECT_STREAM_PROFILE_ID_CACHE_KEY` has no post_save invalidation at
 * all — it appears nowhere in `core/signals.py`. A mutation reverted in
 * teardown can still be live five minutes later, in another project, on
 * another worker. Serialisation bounds concurrency; only this list bounds
 * blast radius.
 */
export const GLOBAL_SETTINGS_WRITE: Capability = {
  name: 'a write to /api/core/settings/ (instance-wide)',
  why: 'Every CoreSettings row is a settings group affecting the whole instance, and two of them are read through caches that outlive the test that wrote them.',
  allow: [
    // Fill from Step 1. Each entry names the group it writes and why the
    // blast radius is acceptable.
  ],
};
```

- [ ] **Step 3: Write the guard**

```ts
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { GLOBAL_SETTINGS_WRITE } from './allowlist';
import { E2E_ROOT, listTsFiles, readSpec } from './ast';

const WRITE_METHODS = new Set(['post', 'patch', 'put', 'delete']);
const SETTINGS_PATH = 'core/settings';

/**
 * A write is `api.<method>('…core/settings…', …)`, or the same through the
 * built-in `request` fixture. Detected as a call whose callee names a write
 * method and whose first argument is a string or template literal mentioning
 * the settings route — so a GET is not a write, and the route named in a
 * comment is not a write either.
 */
function writesGlobalSettings(sf: ts.SourceFile): boolean {
  let found = false;
  function visit(node: ts.Node): void {
    if (found) return;
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      WRITE_METHODS.has(node.expression.name.text)
    ) {
      const arg = node.arguments[0];
      if (arg) {
        const text =
          ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)
            ? arg.text
            : ts.isTemplateExpression(arg)
              ? arg.head.text + arg.templateSpans.map((s) => s.literal.text).join('')
              : '';
        if (text.includes(SETTINGS_PATH)) found = true;
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);
  return found;
}

test('instance-wide settings writes are confined to their allowlist', async () => {
  const hits: string[] = [];
  for (const rel of await listTsFiles(path.join(E2E_ROOT, 'tests'), 'tests')) {
    if (rel.startsWith('tests/guards/')) continue;
    const src = await readSpec(rel);
    if (writesGlobalSettings(ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true))) {
      hits.push(rel);
    }
  }
  expect(
    hits.sort(),
    `${GLOBAL_SETTINGS_WRITE.name} is confined to an allowlist. ${GLOBAL_SETTINGS_WRITE.why}\n` +
      'To add a file, edit tests/guards/allowlist.ts and argue the blast radius in the diff: ' +
      'which group, why nothing else reads it, and how teardown restores it. See docs/adr/0003.',
  ).toEqual([...GLOBAL_SETTINGS_WRITE.allow].sort());
});
```

- [ ] **Step 4: Run, mutate, revert**

Run: `cd e2e && npx playwright test --project=guards -g settings`
Expected: PASS.

Mutations: add `await api.patch('/api/core/settings/1/', { value: {} });` to
`tests/seeded/hdhr.spec.ts` → FAIL. Add the same route inside a comment → PASS.
**Revert both.** Record in the header comment.

- [ ] **Step 5: Typecheck and commit**

Run `npm run typecheck`. Stage both files. Commit as:
`test(e2e): confine instance-wide settings writes to an allowlist`

---

### Task 6: ADR 0002 — the taxonomy

**Files:**
- Create: `docs/adr/0002-e2e-test-taxonomy.md`

- [ ] **Step 1: Read the existing ADR first**

Read `docs/adr/0001-e2e-shared-api-seeded-container.md` and match its headings and tone.

- [ ] **Step 2: Write it**

Required content:

- **Context:** the relay extraction; on a migration branch both kinds of test go red together;
  project boundaries and prose are not per-test, and the split already leaks —
  `restart-persistence.spec.ts` mixes portable and AIO-specific assertions in one file.
- **Decision:** two tags, Playwright-native `{ tag: … }`; `@contract` is the default and needs
  no justification; `@characterization` obliges a comment naming the implementation fact it
  pins.
- **The tie-break, and why it is asymmetric:** ambiguity resolves to `@contract`. A test wrongly
  marked `@characterization` is *invisible* on a migration branch; wrongly marked `@contract` it
  is a false alarm someone reads. Silence in one direction, noise in the other — that decides
  it.
- **What a migration branch does with each:** a red `@contract` blocks; a red
  `@characterization` is read, and its comment says what moved. State that such a branch is
  expected to update or delete characterization tests, not "fix" them.
- **Enforcement:** `tests/guards/tags.spec.ts`, fail-closed, `KNOWN_UNVERIFIABLE`, and that it
  shipped in warning mode for exactly one PR.
- **Consequences:** every new test picks a side; wave 6 goals tag their own; a third tag is out
  of scope, because `@slow`/`@flaky` become a taxonomy nobody maintains.

- [ ] **Step 3: Commit**

Stage and commit as: `docs(adr): record the E2E test taxonomy`

---

### Task 7: ADR 0003 — the frontend and shared-state contract

**Files:**
- Create: `docs/adr/0003-e2e-frontend-and-shared-state-contract.md`

- [ ] **Step 1: Write it**

Promote from `e2e/README.md` and `e2e/tests/frontend/helpers.ts`, keeping their wording where it
is already good:

- **The testId contract:** testIds are the frontend↔suite interface; text selectors are banned
  because they couple to UI copy; `SURFACES` is the register; `backups-panel` deliberately
  breaks the `<surface>-page` pattern and must not be "fixed". Enforced by
  `tests/guards/testid.spec.ts`.
- **Shared-instance mutation rules:** never assert a global count or unfiltered list — filter on
  the name `seed` generated; never assert on a toast; instance-wide settings writes are
  allowlisted and argued.
- **Say plainly which rules are enforced and which are not.** The settings-write rule is
  enforced by `tests/guards/global-mutation.spec.ts`; the count and toast rules are review-only.
  Implying all are enforced would be the same failure this goal exists to fix.
- **Why the caches make this stricter than serialisation:** the 300s group cache and the
  un-invalidated redirect-profile cache, as in Task 5.

- [ ] **Step 2: Commit**

Stage and commit as: `docs(adr): record the data-testid and shared-instance contracts`

---

### Task 8: `e2e-tests.yml` — guards job, dynamic matrix, full mode

**Files:**
- Modify: `.github/workflows/e2e-tests.yml`

- [ ] **Step 1: Add the dispatch input**

```yaml
  workflow_dispatch:
    inputs:
      full:
        description: 'Run every project, including lifecycle-upgrade'
        type: boolean
        default: false
```

- [ ] **Step 2: Extend the `changes` job**

Add to its `outputs:`:

```yaml
      full: ${{ steps.filter.outputs.full }}
      projects: ${{ steps.filter.outputs.projects }}
```

Replace the `filter` step's script with:

```yaml
      - name: Decide whether the E2E suite needs to run, and at what breadth
        id: filter
        env:
          EVENT_NAME: ${{ github.event_name }}
          HEAD_REF: ${{ github.head_ref }}
          REF_NAME: ${{ github.ref_name }}
          DISPATCH_FULL: ${{ inputs.full }}
        run: |
          # Full mode: every project, no path gating. Required on migration
          # branches — see CLAUDE.md. `github.head_ref` is set on pull_request
          # and empty elsewhere, so fall back to ref_name for push/dispatch.
          branch="${HEAD_REF:-$REF_NAME}"
          full=false
          case "$branch" in
            migration/*) full=true ;;
          esac
          if [ "$DISPATCH_FULL" = "true" ]; then
            full=true
          fi
          echo "full=$full" >> "$GITHUB_OUTPUT"

          projects='["pristine","seeded","streaming","streaming-failover","streaming-greybox","lifecycle","frontend"]'
          if [ "$full" = "true" ]; then
            projects='["pristine","seeded","streaming","streaming-failover","streaming-greybox","lifecycle","frontend","lifecycle-upgrade"]'
          fi
          echo "projects=$projects" >> "$GITHUB_OUTPUT"

          if [ "$full" = "true" ] || [ "$EVENT_NAME" != "pull_request" ]; then
            echo "e2e=true" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          changed=$(git diff --name-only HEAD^1 HEAD)
          printf 'Changed files:\n%s\n' "$changed"
          pattern='^(apps/|core/|dispatcharr/|frontend/|docker/|scripts/|e2e/|e2e-upstream/|pyproject\.toml$|uv\.lock$|version\.py$|manage\.py$|\.github/workflows/e2e-tests\.yml$)'
          if printf '%s\n' "$changed" | grep -qE "$pattern"; then
            echo "e2e=true" >> "$GITHUB_OUTPUT"
          else
            echo "e2e=false" >> "$GITHUB_OUTPUT"
          fi
```

Update the comment above the job: it now decides breadth as well as necessity.

- [ ] **Step 3: Make the matrix dynamic**

```yaml
      matrix:
        project: ${{ fromJSON(needs.changes.outputs.projects) }}
```

Keep `fail-fast: false`. Add a comment noting the list lives in the `changes` job now, and that
a new project must be added there — this is the line G13 will edit to add `dvr`.

- [ ] **Step 4: Add the `guards` job**

Place it beside `upstream`, a sibling of `build` without `needs: build`:

```yaml
  # Static analysis over the suite's own source. No image, no container, no
  # browser — so it is a sibling of `build` rather than a matrix row, and it
  # reports in under a minute instead of after the AIO build's 45-minute
  # budget. `npx playwright install` is deliberately absent: no test in this
  # project uses the `page` fixture, so no browser is ever launched.
  guards:
    name: guards
    runs-on: ubuntu-latest
    needs: changes
    if: needs.changes.outputs.e2e == 'true'
    timeout-minutes: 10
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Setup Node.js
        uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
        with:
          node-version: '24'

      - name: Install E2E dependencies
        working-directory: ./e2e
        run: npm ci

      - name: Typecheck
        working-directory: ./e2e
        run: npm run typecheck

      - name: Run the guards
        working-directory: ./e2e
        run: npx playwright test --project=guards
```

Verify the two action SHAs against the ones already in this file — do not type them from this
plan without checking.

- [ ] **Step 5: Add `guards` to the aggregate**

In `e2e-result`: add `guards` to `needs:`, add `GUARDS_RESULT: ${{ needs.guards.result }}` to
the env block, echo it in the diagnostic line, and extend the failure condition to include it.

- [ ] **Step 6: Verify**

```bash
zizmor --min-severity=low .github/workflows/e2e-tests.yml
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/e2e-tests.yml'))"
```

Expected: zizmor clean, YAML parses. **The `PostToolUse` hook blocks on any zizmor finding in
this file** — fix findings rather than suppressing them.

- [ ] **Step 7: Commit**

Stage and commit as: `ci(e2e): add the guards job and a full-run mode for migration branches`

---

### Task 9: `lifecycle-tests.yml` — make it capable of reporting a required check

This task reverses a rule the file's own header and `e2e/README.md` both state emphatically.
Rewrite both in this task, or the repository contradicts itself.

**Files:**
- Modify: `.github/workflows/lifecycle-tests.yml`

- [ ] **Step 1: Drop the PR path filter, add the dispatch input**

Replace the `pull_request:` block's `paths:` list with a bare `branches: [main]`. Add the same
`workflow_dispatch.inputs.full` boolean as Task 8.

- [ ] **Step 2: Add a `changes` job**

It reproduces the *old* path filter — so `upgrade-migrations` still runs only on
migration-shaped PRs — and computes full mode:

```yaml
  changes:
    name: Detect relevant changes
    runs-on: ubuntu-latest
    timeout-minutes: 5
    outputs:
      lifecycle: ${{ steps.filter.outputs.lifecycle }}
      full: ${{ steps.filter.outputs.full }}
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false
          fetch-depth: 2

      - name: Decide what this event needs
        id: filter
        env:
          EVENT_NAME: ${{ github.event_name }}
          HEAD_REF: ${{ github.head_ref }}
          REF_NAME: ${{ github.ref_name }}
          DISPATCH_FULL: ${{ inputs.full }}
        run: |
          branch="${HEAD_REF:-$REF_NAME}"
          full=false
          case "$branch" in
            migration/*) full=true ;;
          esac
          if [ "$DISPATCH_FULL" = "true" ]; then
            full=true
          fi
          echo "full=$full" >> "$GITHUB_OUTPUT"

          if [ "$EVENT_NAME" != "pull_request" ] || [ "$full" = "true" ]; then
            echo "lifecycle=true" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          # The pull_request paths filter this file used to carry, verbatim.
          changed=$(git diff --name-only HEAD^1 HEAD)
          printf 'Changed files:\n%s\n' "$changed"
          pattern='(migrations/|models\.py$|^\.github/workflows/lifecycle-tests\.yml$|^e2e/tests/lifecycle/|^e2e/fixtures/instance\.ts$|^scripts/e2e_up\.sh$)'
          if printf '%s\n' "$changed" | grep -qE "$pattern"; then
            echo "lifecycle=true" >> "$GITHUB_OUTPUT"
          else
            echo "lifecycle=false" >> "$GITHUB_OUTPUT"
          fi
```

- [ ] **Step 3: Re-gate the three existing jobs**

- `build`: add `needs: changes` and
  `if: needs.changes.outputs.lifecycle == 'true' || needs.changes.outputs.full == 'true'`
- `upgrade-migrations`: add `changes` to `needs`, same `if`.
- `suites`: add `changes` to `needs`, and **replace** its
  `if: github.event_name != 'pull_request'` with:

```yaml
    # Was `if: github.event_name != 'pull_request'` — a gate independent of
    # the (now removed) path filter, and the reason these two suites had never
    # run in CI on a pull request even once. Full mode is what lets a
    # migration branch see them.
    if: github.event_name != 'pull_request' || needs.changes.outputs.full == 'true'
```

- [ ] **Step 4: Add the `Lifecycle result` aggregate**

```yaml
  # The check that can be required, on the same reasoning as `E2E result` in
  # e2e-tests.yml: gated jobs cannot be required directly, because a job
  # skipped before expansion never reports, and a required check that never
  # reports blocks the merge forever. This runs unconditionally and passes when
  # everything it depends on either succeeded or was deliberately skipped.
  #
  # NOT yet in the Main ruleset, deliberately: the two bash suites are
  # currently red, and had never run on a pull request at all before this
  # change. G12 triages them. Adding this check before G12 lands would block
  # every migration branch on a pre-existing failure.
  lifecycle-result:
    name: Lifecycle result
    runs-on: ubuntu-latest
    needs: [changes, suites, upgrade-migrations]
    if: always()
    timeout-minutes: 5
    steps:
      - name: Verify the lifecycle outcome
        env:
          CHANGES_RESULT: ${{ needs.changes.result }}
          SUITES_RESULT: ${{ needs.suites.result }}
          UPGRADE_RESULT: ${{ needs.upgrade-migrations.result }}
        run: |
          echo "changes=$CHANGES_RESULT suites=$SUITES_RESULT upgrade=$UPGRADE_RESULT"
          if [ "$CHANGES_RESULT" != "success" ]; then
            echo "Change detection itself failed — cannot prove these suites were unnecessary."
            exit 1
          fi
          for result in "$SUITES_RESULT" "$UPGRADE_RESULT"; do
            case "$result" in
              success|skipped) ;;
              *) echo "A lifecycle job did not succeed."; exit 1 ;;
            esac
          done
          echo "Lifecycle jobs passed or were deliberately skipped."
```

- [ ] **Step 5: Rewrite the header comment**

The existing header says nothing here should become a required check. Replace that paragraph
with: this workflow now always triggers on pull requests and gates internally, exactly as
`e2e-tests.yml` does; `Lifecycle result` is the only check here that may ever be required; and
it must not be added to the ruleset until G12 leaves both bash suites green.

- [ ] **Step 6: Verify**

```bash
zizmor --min-severity=low .github/workflows/lifecycle-tests.yml
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/lifecycle-tests.yml'))"
```

- [ ] **Step 7: Commit**

Stage and commit as: `ci(lifecycle): gate internally so a required check can report`

---

### Task 10: Documentation, and open PR A

**Files:**
- Modify: `e2e/README.md`, `e2e/COVERAGE.md`, `CLAUDE.md`

- [ ] **Step 1: `CLAUDE.md` — the branch convention**

Add to the **Testing** section:

> **Full E2E runs.** A branch named `migration/**` runs every Playwright project, including
> `lifecycle-upgrade`, plus both bash suites in `lifecycle-tests.yml` — the path filters are
> bypassed. Any other branch gets the seven-project matrix gated on changed paths.
> `workflow_dispatch` with `full: true` does the same on any branch. **Name the
> relay-extraction branches `migration/…`** so the gate applies. See
> `docs/superpowers/specs/2026-09-01-e2e-migration-gate-design.md`.

- [ ] **Step 2: `e2e/README.md`**

Three edits:

1. **Projects:** add `guards` — what it is, that it needs no container, that it is the home for
   every enforcement spec, and that `pageerrors-enforcement.spec.ts` moved there.
2. **CI:** correct it. The matrix is no longer hardcoded (it comes from the `changes` job);
   `guards` is a separate job, not a matrix row; `lifecycle-tests.yml` no longer carries a PR
   path filter and *can* now be a required check, though it is not one yet, and why.
   **Delete the claim that it must never be required** — it is now false, and a stale
   instruction of exactly the kind this goal exists to eliminate.
3. **Writing a test:** add an item — pick a tag; `@contract` unless you can name the
   implementation fact you are pinning; see ADR-0002.

- [ ] **Step 3: `e2e/COVERAGE.md`**

Add a `Guards` section with a row per guard, each naming what it enforces and the mutation that
proved it fails.

- [ ] **Step 4: Full local verification**

```bash
cd e2e && npm run typecheck && npx playwright test --project=guards
```

Expected: every guard passes; the tag guard warns about 190 untagged tests.

- [ ] **Step 5: Commit, push, open PR A**

Commit as `docs(e2e): document the guards project, the taxonomy and full-run mode`, push
`feat/e2e-migration-gate-g11`, and open the PR with `gh pr create --repo D10Scot/Dispatcharr`.

The PR body must state:
- the tag guard is in **warning** mode and PR B flips it;
- `pageerrors-enforcement.spec.ts` — a G6-owned file — is refactored onto the shared walker and
  moved, and why;
- `lifecycle-tests.yml`'s "never required" rule is **deliberately reversed**, with both
  documents rewritten in the same change;
- `Lifecycle result` must not join the Main ruleset until G12 lands;
- wave 6 rebases onto this: G13's `dvr` project edits the same matrix line.

---

# PR B — The retag

Branch from PR A's head: `feat/e2e-migration-gate-g11-retag`.

### Task 11: Re-derive the scope

- [ ] **Step 1: Count**

```bash
cd e2e
find tests -name '*.spec.ts' | wc -l                          # expect 77
grep -rhoE '^\s*test(\.(fail|skip|only))?\(' tests | wc -l    # expect 190
```

**If either differs, stop and report.** A test PR landed after `76db0332`; the extra tests need
tags, and the guard will fail on them at Task 15.

- [ ] **Step 2: Record the actual numbers** for the PR description. No commit.

---

### Tasks 12–14: Apply the tags

Each of these three tasks follows the same shape:

1. Add `{ tag: '@contract' }` as the second argument to every `test(…)` / `test.fail(…)` in the
   task's files.
2. For anything that is *not* portable, use `{ tag: '@characterization' }` **and add a comment
   directly above naming the implementation fact it pins.** No exceptions — the comment is the
   deliverable, not the tag.
3. Run `npm run typecheck`.
4. Run `npx playwright test --project=guards` — the warning count must drop by exactly the
   number of tests in the task's files. If it drops by fewer, a declaration was missed.
5. Commit.

**Task 12 — `tests/seeded/**` and `tests/pristine/**`.** Expect all `@contract`: every assertion
is at a REST or client-facing surface. If you find one that is not, that is a finding — tag it
`@characterization` and call it out in the PR body.

**Task 13 — `tests/streaming/**`, `tests/streaming-failover/**`, `tests/streaming-greybox/**`.**
Expect `@contract` throughout except:
- `output-profile-sharing.spec.ts` — whole file `@characterization`; it counts container
  processes with `pgrep -x ffmpeg`.
- `vod-redirect-profile.spec.ts` — judge **per test**. The Redirect-mode behaviour is contract;
  the global `stream_settings` manipulation around it is machinery.

**Task 14 — `tests/frontend/**`, `tests/lifecycle/**`, `tests/guards/**`.**
- `tests/frontend/**`: `@contract` — they drive a browser against rendered UI.
- `tests/guards/**`: whole-file `@characterization` — they assert facts about this repository's
  own source tree.
- `tests/lifecycle/**`: **mixed, and this is the pair of files the taxonomy exists for.** In
  `upgrade-migrations.spec.ts` and `restart-persistence.spec.ts`, `manage.py showmigrations`
  assertions and container-layout assertions are `@characterization`; "the rows are still there
  afterwards" is `@contract`. Split per test, not per file. Where a single test asserts both,
  tag it `@characterization` and say so in the comment — the pin is what makes it fragile.

---

### Task 15: Flip the guard to blocking

- [ ] **Step 1: Flip**

In `e2e/tests/guards/tags.spec.ts`, change `MODE` to `'blocking'` and delete the warning branch
and its `console.warn`.

- [ ] **Step 2: Run**

```bash
cd e2e && npx playwright test --project=guards
```

Expected: PASS with zero findings. **If any test is listed, it was missed in Tasks 12–14** —
fix it there, never by adding to `KNOWN_UNVERIFIABLE`.

- [ ] **Step 3: Mutation check**

Remove one tag. Re-run. Expected: FAIL naming that location. **Restore it.**

- [ ] **Step 4: Update the header comment**

Delete the "MODE: warning" paragraph; replace with one line stating the guard is blocking and
every test carries a tag.

- [ ] **Step 5: Commit, push, open PR B**

Run `npm run typecheck`. Commit as `test(e2e): require a taxonomy tag on every test`, push
`feat/e2e-migration-gate-g11-retag`, open the PR.

PR B's description states the final counts, **lists every `@characterization` test with a
one-line reason** — this is the document a migration branch reads first — and names the merge
order: PR A, then PR B, then wave 6 rebases.

---

## Notes for whoever executes this

- **Wave 6 rebases onto this, not the other way round.** G13 adds a `dvr` project with its own
  matrix job and will collide with Task 8's `fromJSON` change. G15 touches many of the files
  Tasks 12–14 retag. Both land after both PRs here.
- **If a guard is hard to satisfy, that is a finding, not an obstacle.** The temptation at Tasks
  3 and 5 is to widen an allowlist until the guard passes. Widening is a decision with a written
  reason, or it is a bug being hidden.
- **The comments are the deliverable.** Tags without justifications produce a suite that
  *claims* to be classified. On the migration branch, someone reads those comments to decide
  whether to ship.
