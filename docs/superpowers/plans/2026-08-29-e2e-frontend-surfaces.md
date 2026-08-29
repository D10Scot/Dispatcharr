# G6 — Frontend Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the SPA and a real backend agree — that each of nine product surfaces mounts without error and that a write driven through its UI actually reaches the server, asserted against the server's own state.

**Architecture:** Two pull requests, in order. **PR A** (`feat/frontend-page-testids`) is a product change adding eleven `data-testid` attributes across nine files — nothing else. **PR B** (`feat/e2e-frontend-surfaces-g6`) adds one new Playwright project, `frontend`, holding ten spec files and eighteen tests: nine render checks driven from one table, and nine write-or-read proofs, one per surface. Every assertion about effect goes through the `api` fixture, never through a toast.

**Tech Stack:** React 19 + Mantine 8 (product); TypeScript, Playwright 1.62.x, Node 24, the G1 fixture set (`api`, `seed`, `adminPage`, `waitFor`, `upstream`, `streamClient`), Docker.

**Spec:** `docs/superpowers/specs/2026-08-29-e2e-frontend-surfaces-design.md` — read it before Task 1. Every task below cites the decisions it implements.

## Global Constraints

Copied from the spec and the programme rules. Every task's requirements implicitly include this section.

- **PR A lands first. PR B is never merged before it.** PR B's branch is taken from PR A's branch so work can proceed in parallel; when PR A merges, PR B rebases onto `main`. If PR A is rejected outright, stop and renegotiate scope — do not quietly ship weaker tests. (Spec D1.)
- **PR A is additive attributes only.** No behaviour change, no refactor, no restructuring, no prop reordering, no formatting sweep. A reviewer must be able to confirm the whole diff is eleven added lines.
- **Test ids scope; seeded names identify; roles drive.** A `data-testid` names a *container*. The row inside it is found by the name `seed` (or `seed.generatedName`) produced. The control that acts on it is found by `getByRole`/`getByLabel`. Never add a per-row test id, and never select a control by a test id where its accessible name works. (Spec D1a, D1b.)
- **Never assert on a notification toast.** `e2e/README.md` rule 6. `api.js`'s `errorNotification` toasts *and rethrows*, and `request()` throws on any non-2xx, so a toast is equally consistent with a write that never left the browser and a write the server rejected. The assertion is always the server's state, read through `api`.
- **Never assert a global count or an unfiltered list.** Roadmap rule 4. Every assertion is scoped to the worker's own generated name.
- **One surface per test. No multi-surface journeys.** (Spec D10.)
- **One spec file per surface. This is load-bearing.** The `frontend` project runs two workers with file-level parallelism; confining backup creation and plugin installation to one file each is what makes that safe. (Spec D2, D2a.)
- **Import from `'../../fixtures'`, never from `'@playwright/test'` directly.** A spec that destructures only `page` typechecks clean and runs with no fixtures wired in — the rule exists because the typecheck cannot enforce it. Use `adminPage`, not `page`.
- **The typecheck hook is blocking.** Any edit to `e2e/**/*.ts` runs `tsc --noEmit` for that package and blocks on failure. Run `cd e2e && npm ci` first or it degrades to a loud note.
- **The zizmor hook is blocking on every finding** in an edited `.github/workflows/*.yml`, legacy included. The workflows are at zero findings; keep them there.
- **The frontend vitest hook is blocking** on `frontend/**/*.test.jsx`; the eslint hook on `frontend/**/*.jsx` is advisory and must stay advisory. PR A must leave `cd frontend && npm test` green.
- **Product defects are asserted correct, marked `test.fail()` with the defect named in a comment, and filed — never patched.** `gh issue create --repo D10Scot/Dispatcharr`. The explicit `--repo` flag is mandatory: this checkout is a fork and `gh` without it resolves to upstream's public tracker.
- **Never click the Logos page's "Cleanup Unused" button.** It deletes every unreferenced logo instance-wide and would destroy other workers' and other goals' data.
- **Never restore a backup.** Restore belongs to G7 (spec D9).
- **Never mutate a global `CoreSettings` value.** `e2e/README.md` assigns those to `pristine`; G7 already writes `system_settings.max_system_events`.
- **No new principals, no `asUser`.** The login budget is three per minute for the whole suite and the cold path spends all three. Every G6 test drives the bootstrap admin through the project's `storageState`.
- **G7 is in flight on four shared files** — `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `e2e/package.json`, `e2e/fixtures/index.ts`. Every collision is additive; whoever lands second rebases. G6 does **not** touch `scripts/e2e_up.sh` or `e2e/fixtures/seed.ts`.
- **After PR A, rebuild the E2E image before running PR B locally.** `scripts/e2e_up.sh --reset` reuses an existing `dispatcharr-e2e:local`, so a stale image serves a bundle with no test ids and every locator fails. `docker rmi dispatcharr-e2e:local` first.
- **Import map — every shared symbol comes from exactly one place.** Task code blocks below often omit import lines; this table is authoritative.

  | Symbol | From |
  |---|---|
  | `test`, `expect`, `SEEDED_USER_PASSWORD` | `'../../fixtures'` |
  | `EXPECTED_PAGE_NOISE`, type `PageNoiseEntry` | `'../../fixtures'` (defined in `e2e/fixtures/page-errors.ts`) |
  | `Channel`, `User`, `UserAgent`, `ConnectIntegration`, `Recording`, `Logo`, `PluginListEntry`, `BackupEntry` | `'../../fixtures'` (defined in `e2e/fixtures/types.ts`) |
  | `listRows` | `'../../setup/http'` |
  | `SURFACES`, `gotoSurface`, type `Surface` | `'./helpers'` — a spec in `e2e/tests/frontend/` |
  | `buildPluginZip` | `'./plugin-zip'` |
  | `TINY_PNG` | `'./assets'` |

---

## File Structure

**Created — PR A:** nothing. PR A only modifies.

**Created — PR B:**

| Path | Responsibility |
|---|---|
| `e2e/fixtures/page-errors.ts` | The `pageErrors` fixture: collects `pageerror`, `console.error` and responses ≥ 400; holds `EXPECTED_PAGE_NOISE` and `expectClean()` |
| `e2e/tests/frontend/helpers.ts` | The nine-surface table (`name`, `route`, `testId`) and `gotoSurface()` |
| `e2e/tests/frontend/assets.ts` | `TINY_PNG` — a 1×1 PNG as a `Buffer`, for the Logos upload |
| `e2e/tests/frontend/plugin-zip.ts` | `buildPluginZip()` — a stored-entry zip writer, so the plugin key can carry per-run entropy |
| `e2e/tests/frontend/render.spec.ts` | Nine render checks, one per surface |
| `e2e/tests/frontend/guide.spec.ts` | Guide: sidebar navigation and a backend-sourced row |
| `e2e/tests/frontend/users.spec.ts` | Users: create, edit, delete |
| `e2e/tests/frontend/settings.spec.ts` | Settings: create a User-Agent and prove it persisted |
| `e2e/tests/frontend/connect.spec.ts` | Connect: webhook create, toggle, delete |
| `e2e/tests/frontend/logos.spec.ts` | Logos: upload and browse |
| `e2e/tests/frontend/dvr.spec.ts` | DVR: schedule, list, cancel |
| `e2e/tests/frontend/plugins.spec.ts` | Plugins: import, enable, configure, delete |
| `e2e/tests/frontend/backups.spec.ts` | Backups: create and validate the archive |
| `e2e/tests/frontend/stats.spec.ts` | Stats: a live connection appears |

**Modified — PR A:**

| Path | Change |
|---|---|
| `frontend/src/pages/Guide.jsx` | `data-testid="guide-page"`, `data-testid="guide-grid"` |
| `frontend/src/pages/DVR.jsx` | `data-testid="dvr-page"` |
| `frontend/src/pages/Users.jsx` | `data-testid="users-page"` |
| `frontend/src/pages/Settings.jsx` | `data-testid="settings-page"` |
| `frontend/src/pages/Plugins.jsx` | `data-testid="plugins-page"` |
| `frontend/src/pages/Stats.jsx` | `data-testid="stats-page"`, `data-testid="stats-connections"` |
| `frontend/src/pages/Connect.jsx` | `data-testid="connect-page"`, `data-testid="connect-integrations"` |
| `frontend/src/pages/Logos.jsx` | `data-testid="logos-page"` |
| `frontend/src/components/backups/BackupManager.jsx` | `data-testid="backups-panel"` |

**Modified — PR B:**

| Path | Change |
|---|---|
| `e2e/fixtures/index.ts` | Register the `pageErrors` fixture; export it, `EXPECTED_PAGE_NOISE` and the new types |
| `e2e/fixtures/types.ts` | Add `UserAgent`, `ConnectIntegration`, `Recording`, `Logo`, `PluginListEntry`, `BackupEntry` |
| `e2e/playwright.config.ts` | Add the `frontend` project |
| `e2e/package.json` | Add `test:frontend`; update the bare-`test` message from five populations to six |
| `.github/workflows/e2e-tests.yml` | Add `frontend` to the matrix |
| `e2e/README.md` | Add `frontend` to the population table; state the one-file-per-surface rule; state the image-rebuild trap; **correct the stale CI section** (three jobs → six, and drop its line-number citation) |
| `e2e/COVERAGE.md` | Nine G6 rows → `done`; split the Backups row; add the Guide EPG gap note |

---

# PR A — page test ids

Branch: `feat/frontend-page-testids`, off `main`.

### Task 1: Add eleven `data-testid` attributes across nine files

Implements spec D1, D1a and the PR A table. Nine steps, one per file. Each is a single added
line in an existing JSX opening tag. **Add nothing else.** Mantine's `Box`, `Stack` and
`AppShellMain` spread unrecognised props onto the DOM element they render, so the attribute
reaches the browser unchanged.

**Files:**
- Modify: all nine files in the PR A table above.

**Interfaces:**
- Produces: the eleven test ids `guide-page`, `guide-grid`, `dvr-page`, `users-page`,
  `settings-page`, `plugins-page`, `stats-page`, `stats-connections`, `connect-page`,
  `connect-integrations`, `logos-page`, `backups-panel`. Every PR B task consumes them through
  `SURFACES` in `e2e/tests/frontend/helpers.ts`.

- [ ] **Step 1: Create the branch**

```bash
git checkout main && git pull --ff-only
git checkout -b feat/frontend-page-testids
```

- [ ] **Step 2: `frontend/src/pages/Guide.jsx` — two ids**

Find the `Guide` component's own `return (` — the one immediately followed by
`<Box ref={tvGuideRef} className="tv-guide"`. Add one line:

```jsx
    <Box
      ref={tvGuideRef}
      className="tv-guide"
      data-testid="guide-page"
```

Then find the `<Box ref={guideContainerRef}` that carries the comment
`{/* Main scrollable container for program content */}`. Add one line:

```jsx
        <Box
          ref={guideContainerRef}
          data-testid="guide-grid"
```

That container holds both the `VariableSizeList` and the "No channels match your filters"
empty state, which is exactly what lets a test tell *populated* from *empty*.

- [ ] **Step 3: `frontend/src/pages/DVR.jsx` — one id**

Find `DVRPage`'s `return (` — the one followed by `<Box p={10}>`:

```jsx
  return (
    <Box p={10} data-testid="dvr-page">
```

No container id. The section headings are real `<Title>` elements ("Currently Recording",
"Upcoming Recordings") and the recording is identified by its uniquely seeded channel name.

- [ ] **Step 4: `frontend/src/pages/Users.jsx` — one id**

In `PageContent`:

```jsx
  return (
    <Box p={10} data-testid="users-page">
      <UsersTable />
    </Box>
  );
```

- [ ] **Step 5: `frontend/src/pages/Settings.jsx` — one id**

In `SettingsPage`:

```jsx
  return (
    <Box p={10} maw={900} mx="auto" data-testid="settings-page">
```

- [ ] **Step 6: `frontend/src/pages/Plugins.jsx` — one id**

In `PluginsPage`'s `return (` — the one followed by `<AppShellMain p={16}>` (there is an
earlier `<AppShellMain p={16}>` inside `PluginsList`; take the one in `PluginsPage`, at the
bottom of the file):

```jsx
  return (
    <AppShellMain p={16} data-testid="plugins-page">
```

No container id: the plugin key carries per-run entropy, so nothing else on the page can match it.

- [ ] **Step 7: `frontend/src/pages/Stats.jsx` — two ids**

`StatsPage` returns a fragment. Put the page id on the first `<Box>` inside it:

```jsx
  return (
    <>
      <Box style={{ overflowX: 'auto' }} data-testid="stats-page">
```

Then the grid that wraps `<Connections …>`:

```jsx
          <Box
            style={{
              gap: '1rem',
              gridTemplateColumns: 'repeat(auto-fill, minmax(500px, 1fr))',
              alignContent: 'start',
            }}
            display="grid"
            p={10}
            pb={120}
            mih={'calc(100vh - 250px)'}
            data-testid="stats-connections"
          >
```

The second id is not decoration: the page also renders a fixed-position `<SystemEvents />` log
that can print the same channel name, and an event-log line must not pass for a live connection.

- [ ] **Step 8: `frontend/src/pages/Connect.jsx` — two ids**

`ConnectPage` also returns a fragment:

```jsx
    <>
      <Box p="md" pb={120} data-testid="connect-page">
```

Then the grid holding the `<IntegrationRow>` cards:

```jsx
          <Box
            style={{
              gap: '1rem',
              gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))',
              alignContent: 'start',
            }}
            display="grid"
            py={10}
            data-testid="connect-integrations"
          >
```

Same hazard as Stats: `<ConnectLogsSection>` is fixed at the bottom and prints integration names.

- [ ] **Step 9: `frontend/src/pages/Logos.jsx` — one id**

In `LogosPage`:

```jsx
  return (
    <Box data-testid="logos-page">
```

- [ ] **Step 10: `frontend/src/components/backups/BackupManager.jsx` — one id**

At the component's own `return (` — the last one in the file, followed by `<Stack gap="md">`:

```jsx
  return (
    <Stack gap="md" data-testid="backups-panel">
```

Required, not optional: `Settings.jsx` renders this section inside `<Suspense>` with a
`<Loader/>` fallback, so `settings-page` alone cannot distinguish "the Backup section mounted"
from "the spinner is still up".

- [ ] **Step 11: Verify the diff is exactly eleven added lines**

```bash
git diff --stat
git diff -U0 | grep -c '^+[^+]'
```

Expected: `11`, and `git diff --stat` shows nine files with `1` or `2` insertions each and
**zero deletions**. A deletion means a reformat crept in — revert it. (Steps 7 and 8 add the
attribute to an existing multi-line tag; if your editor rewrapped the tag, `git diff` will show
deletions. Undo the rewrap.)

- [ ] **Step 12: Commit**

```bash
git add frontend/src/pages/Guide.jsx frontend/src/pages/DVR.jsx \
  frontend/src/pages/Users.jsx frontend/src/pages/Settings.jsx \
  frontend/src/pages/Plugins.jsx frontend/src/pages/Stats.jsx \
  frontend/src/pages/Connect.jsx frontend/src/pages/Logos.jsx \
  frontend/src/components/backups/BackupManager.jsx
git commit -m "feat(frontend): add page-level data-testid handles to nine surfaces"
```

---

### Task 2: Verify PR A changes nothing, and open it

**Files:**
- Test: `frontend/src/pages/__tests__/*.test.jsx`, `frontend/src/components/backups/__tests__/BackupManager.test.jsx` (existing; not modified)

- [ ] **Step 1: Run the whole frontend suite**

```bash
cd frontend && npm install && npm test
```

Expected: PASS, 6,128 tests, the same count as before the change. A snapshot failure means a
snapshot in this repo captures the DOM including attributes — if that happens, **update the
snapshot and say so in the PR description**; do not remove the attribute. Do not run
`vitest --sequence.shuffle`: `CLAUDE.md` records that suite failing under shuffle for unrelated
reasons, and a red run there proves nothing about this change.

- [ ] **Step 2: Confirm eslint has not regressed**

```bash
cd frontend && npm run lint 2>&1 | tail -5
```

Expected: the same pre-existing error and warning counts as on `main` (`CLAUDE.md` records 112
errors / 55 warnings, disabled in CI, and the hook is advisory). Adding an attribute cannot
change them; if the numbers moved, something else got edited.

- [ ] **Step 3: Confirm the attributes reach the DOM**

The three components with the most indirection are the ones to check, because Mantine's prop
spreading is what this step is really testing. In a scratch file:

```bash
cd frontend && npx vitest run src/pages/__tests__/Stats.test.jsx src/pages/__tests__/Connect.test.jsx src/pages/__tests__/Guide.test.jsx
```

Expected: PASS. Then confirm by hand in the browser after the image rebuild in Task 3 — the
authoritative check is `page.getByTestId(...)` resolving in PR B's Task 5, and that is where a
missed spread would surface.

- [ ] **Step 4: Push and open PR A**

```bash
git push -u origin feat/frontend-page-testids
gh pr create --repo D10Scot/Dispatcharr --base main \
  --title "feat(frontend): add page-level data-testid handles to nine surfaces" \
  --body "$(cat <<'BODY'
Eleven `data-testid` attributes across nine page surfaces. No behaviour change,
no refactor: the whole diff is eleven added lines and zero deletions.

Why a product change in service of a test goal, per
`docs/superpowers/specs/2026-08-29-e2e-frontend-surfaces-design.md` D1:

- Exactly two non-test files in `frontend/src` carry `data-testid` today
  (`GuideRow.jsx`, `SuperuserForm.jsx`). No page has one, so the nine G6
  surfaces have no stable handle at all.
- The Guide grid, the Stats connections grid and the Connect integrations grid
  are unnamed Mantine/`react-window` constructs. Giving them an ARIA role
  instead would be a *larger* product change — it alters assistive-technology
  behaviour, where an inert attribute does not.
- Text selectors would couple the E2E suite to UI copy, so renaming a button
  would break tests for no product reason.
- Reviewed as a product diff, this gets reviewed. Buried in an eighteen-test
  PR, it would not.

Rule going forward: prefer `getByRole`/`getByLabel` where a role expresses the
target honestly; reserve a test id for where it does not. Every button, input
and switch the E2E suite drives is reached by its accessible name — this PR
adds ids for containers only.

Gates the G6 E2E work on `feat/e2e-frontend-surfaces-g6`, which must not merge
before this.
BODY
)"
```

The `--repo D10Scot/Dispatcharr` flag is mandatory — without it `gh` resolves to the upstream
public project.

---

# PR B — the tests

Branch: `feat/e2e-frontend-surfaces-g6`, taken from `feat/frontend-page-testids` so work can
proceed while PR A is in review. Rebase onto `main` once PR A merges.

### Task 3: Rebuild the E2E image and confirm the test ids ship

Not a code task, but everything after it depends on it, and skipping it produces eighteen
locator failures that look like bugs in the tests. (Global Constraints, "After PR A".)

**Files:** none.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/e2e-frontend-surfaces-g6 feat/frontend-page-testids
```

- [ ] **Step 2: Destroy the stale image and rebuild**

```bash
docker rmi dispatcharr-e2e:local || true
./scripts/e2e_up.sh --reset
```

`--reset` only *builds* the image when it does not exist, which is why the `rmi` comes first.
This takes minutes.

- [ ] **Step 3: Prove one test id reaches the browser**

```bash
cd e2e && npm ci && npx playwright install --with-deps chromium
```

Then, from the repository root:

```bash
curl -s http://localhost:9191/ >/dev/null && echo "container up"
```

The real proof comes in Task 5, when `render.spec.ts` resolves all nine. If Task 5 fails on
`getByTestId('stats-page')` while the other eight resolve, the cause is Mantine prop spreading
on that specific element, not the harness — fix it in PR A's branch and rebuild.

---

### Task 4: The `pageErrors` fixture and the noise allowlist

Implements spec D4. Every render check consumes it, so it lands first.

**Files:**
- Create: `e2e/fixtures/page-errors.ts`
- Modify: `e2e/fixtures/index.ts`, `e2e/fixtures/types.ts`
- Test: `e2e/tests/frontend/page-errors.spec.ts` *(deleted at the end of this task — it is a
  scaffold that proves the collector works, not a coverage row)*

**Interfaces:**
- Consumes: Playwright's `page` fixture.
- Produces:
  - `class PageErrorCollector` with
    `readonly consoleErrors: string[]`, `readonly pageErrors: string[]`,
    `readonly failedResponses: { url: string; status: number }[]`, and
    `expectClean(): void`
  - `pageErrors: PageErrorCollector` — a test-scoped fixture
  - `EXPECTED_PAGE_NOISE: readonly PageNoiseEntry[]`
  - `type PageNoiseEntry = { match: string; kind: 'console' | 'response'; reason: string }`
  - types `UserAgent`, `ConnectIntegration`, `Recording`, `Logo`, `PluginListEntry`,
    `BackupEntry` in `types.ts`

- [ ] **Step 1: Add the entity types**

Append to `e2e/fixtures/types.ts`, keeping the file's existing rule — every field carries the
evidence it came from, and nothing is guessed:

```ts
/** `core.UserAgent` via `UserAgentViewSet` (`core/api_urls.py`, `useragents`). */
export type UserAgent = {
  id: number;
  name: string;
  user_agent: string;
  description: string | null;
  is_active: boolean;
};

/** `apps.connect.Integration` via `IntegrationViewSet` (`apps/connect/api_urls.py`). */
export type ConnectIntegration = {
  id: number;
  name: string;
  type: string;
  enabled: boolean;
  config: Record<string, unknown>;
  subscriptions: { event: string; enabled: boolean }[];
};

/** `apps.channels.Recording` via `RecordingViewSet` (`apps/channels/api_urls.py`). */
export type Recording = {
  id: number;
  channel: number;
  start_time: string;
  end_time: string;
  custom_properties: Record<string, unknown> | null;
};

/** `apps.channels.Logo` via `LogoViewSet` (`apps/channels/api_urls.py`, `logos`). */
export type Logo = {
  id: number;
  name: string;
  url: string;
};

/**
 * One entry of `{"plugins": [...]}` from `GET /api/plugins/plugins/`
 * (`PluginsListAPIView`, whose body is `PluginManager.list_plugins()`).
 */
export type PluginListEntry = {
  key: string;
  name: string;
  version: string;
  enabled: boolean;
  ever_enabled: boolean;
  settings: Record<string, unknown>;
};

/** One row of `GET /api/backups/` (`apps/backups/services.py`, `list_backups`). */
export type BackupEntry = {
  name: string;
  size: number;
  created: string;
};
```

- [ ] **Step 2: Write the failing scaffold test**

Create `e2e/tests/frontend/page-errors.spec.ts`:

```ts
import { test, expect } from '../../fixtures';

// Scaffold, deleted at the end of Task 4. It proves the collector actually
// observes all three channels before nine render checks are built on it — a
// collector that silently sees nothing would make every render check pass.
test('the collector sees a console error, an uncaught error and a 4xx', async ({
  adminPage,
  pageErrors,
}) => {
  await adminPage.goto('/channels');
  await adminPage.evaluate(() => {
    console.error('scaffold-console-error');
  });
  await adminPage.evaluate(() => {
    setTimeout(() => {
      throw new Error('scaffold-page-error');
    }, 0);
  });
  await adminPage.evaluate(() => fetch('/api/does-not-exist/'));

  await expect
    .poll(() => pageErrors.consoleErrors.join('|'))
    .toContain('scaffold-console-error');
  await expect
    .poll(() => pageErrors.pageErrors.join('|'))
    .toContain('scaffold-page-error');
  await expect
    .poll(() => pageErrors.failedResponses.map((r) => r.url).join('|'))
    .toContain('/api/does-not-exist/');

  expect(() => pageErrors.expectClean()).toThrow();
});
```

- [ ] **Step 3: Run it and watch it fail**

The `frontend` project does not exist until Task 5, and every existing project's `testDir`
excludes `tests/frontend/`, so run the scaffold from the `seeded` project by pointing its
`testDir` at the file for one invocation:

```bash
cd e2e && npx playwright test --project=seeded \
  --config=<(sed 's#./tests/seeded#./tests/frontend#' playwright.config.ts) \
  2>&1 | head -20
```

If your shell does not support process substitution, copy `page-errors.spec.ts` into
`tests/seeded/` for this step and move it back afterwards. Either way:

Expected: FAIL with `Test has unknown parameter "pageErrors"`. That is the message to observe —
it proves the fixture is genuinely absent, rather than the file simply not being collected.

- [ ] **Step 4: Write the fixture**

Create `e2e/fixtures/page-errors.ts`:

```ts
/**
 * The render check's evidence, and the one place the noise allowlist lives.
 *
 * Three channels, because the product routes failures to all three and no one
 * of them is sufficient:
 *
 *  - `pageerror`      — an uncaught exception, and (in Chromium) an unhandled
 *                       promise rejection, which is what an awaited `api.js`
 *                       call that throws inside a React handler produces.
 *  - `console.error`  — React's own warnings and the app's explicit
 *                       `console.error` calls. Filtered to `type() === 'error'`
 *                       on purpose: `Connect.jsx` and `Stats.jsx` both carry a
 *                       plain `console.log`, and neither is a defect.
 *  - responses >= 400 — the only channel that sees a rejected write reliably.
 *                       `api.js`'s `errorNotification` catches, toasts and
 *                       rethrows, so whether the rejection reaches `pageerror`
 *                       depends on the call site's error handling. The response
 *                       does not.
 *
 * THE ALLOWLIST RULE. `EXPECTED_PAGE_NOISE` starts empty and grows only under
 * review. Each entry names an exact URL path or an exact message prefix —
 * never a bare substring like `/api/` — and carries a `reason` that says why
 * the noise is not a defect. **"This is a known product bug" is not an
 * admissible reason.** Roadmap rule 5 applies: assert the correct behaviour,
 * mark the test `test.fail()` naming the defect, and file it with
 * `gh issue create --repo D10Scot/Dispatcharr`. An allowlist that absorbs bugs
 * stops being a check and becomes a comment.
 */
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

export type PageNoiseEntry = {
  /** Exact URL path (for `response`) or exact message prefix (for `console`). */
  match: string;
  kind: 'console' | 'response';
  /** Why this is not a defect. Reviewed individually. */
  reason: string;
};

/**
 * Deliberately empty. Task 5 runs the render checks against a real container
 * and fills this in from what it actually observes, justifying each entry.
 * Nothing goes in here speculatively.
 */
export const EXPECTED_PAGE_NOISE: readonly PageNoiseEntry[] = [];

function isAllowed(kind: PageNoiseEntry['kind'], value: string): boolean {
  return EXPECTED_PAGE_NOISE.some(
    (entry) => entry.kind === kind && value.startsWith(entry.match)
  );
}

export class PageErrorCollector {
  readonly consoleErrors: string[] = [];
  readonly pageErrors: string[] = [];
  readonly failedResponses: { url: string; status: number }[] = [];

  constructor(page: Page) {
    page.on('console', (message) => {
      if (message.type() === 'error') this.consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => {
      this.pageErrors.push(`${error.name}: ${error.message}`);
    });
    page.on('response', (response) => {
      if (response.status() >= 400) {
        this.failedResponses.push({
          url: new URL(response.url()).pathname,
          status: response.status(),
        });
      }
    });
  }

  /**
   * Fail naming every offender, not counting them. A render check that says
   * "expected 0, got 3" costs the reader a re-run with `--debug`.
   */
  expectClean(): void {
    const offenders = [
      ...this.pageErrors.map((e) => `pageerror: ${e}`),
      ...this.consoleErrors
        .filter((e) => !isAllowed('console', e))
        .map((e) => `console.error: ${e}`),
      ...this.failedResponses
        .filter((r) => !isAllowed('response', r.url))
        .map((r) => `HTTP ${r.status} ${r.url}`),
    ];
    expect(
      offenders,
      'the page produced errors not covered by EXPECTED_PAGE_NOISE. ' +
        'Read the allowlist rule at the top of fixtures/page-errors.ts before ' +
        'adding an entry: a product defect is filed, not allowlisted.'
    ).toEqual([]);
  }
}
```

This module registers no fixture itself — `fixtures/index.ts` owns `base.extend`, and a second
`extend` here would give specs two incompatible `test` objects. Specs import `pageErrors`
through `'../../fixtures'` like every other fixture.

Note `pageErrors` is **not** allowlisted at all in `expectClean` — an uncaught exception is
never acceptable noise. Only console errors and HTTP responses can be allowed.

- [ ] **Step 5: Register the fixture**

In `e2e/fixtures/index.ts`, add to the `Fixtures` type after `adminPage`:

```ts
  pageErrors: PageErrorCollector;
```

and to `base.extend<Fixtures>({ … })`, after the `adminPage` entry:

```ts
  // Depends on `page`, not `adminPage`: they are the same object, and the
  // listeners must be attached at fixture setup, before the test body runs
  // its first `goto`. Anything attached inside the test misses the initial
  // document load, which is where a bad bundle fails.
  pageErrors: async ({ page }, use) => {
    await use(new PageErrorCollector(page));
  },
```

Add the import beside the others:

```ts
import { PageErrorCollector } from './page-errors';
```

and the exports beside the rest:

```ts
export { PageErrorCollector, EXPECTED_PAGE_NOISE } from './page-errors';
export type { PageNoiseEntry } from './page-errors';
```

Also extend the module's header inventory with a `pageErrors` entry — the header is the
harness contract and `e2e/README.md` promises it is enough to write a test without opening a
fixture:

```
 * `pageErrors: PageErrorCollector` — everything the browser reported while the
 *   test ran: `consoleErrors`, `pageErrors`, `failedResponses`, and
 *   `expectClean()`, which fails naming every offender not covered by
 *   `EXPECTED_PAGE_NOISE`. Attached at fixture setup, so it sees the initial
 *   document load. The allowlist rule is at the top of `page-errors.ts`: a
 *   product defect is filed, never allowlisted.
```

- [ ] **Step 6: Typecheck**

```bash
cd e2e && npm run typecheck
```

Expected: exit 0. (The blocking hook already ran this on each edit; this is the explicit gate.)

- [ ] **Step 7: Delete the scaffold spec**

```bash
rm e2e/tests/frontend/page-errors.spec.ts
```

It has served its purpose. Keeping it would add a nineteenth test that asserts nothing about
the product, and `render.spec.ts` exercises the same collector nine times from Task 5 onward.

- [ ] **Step 8: Commit**

```bash
git add e2e/fixtures/page-errors.ts e2e/fixtures/index.ts e2e/fixtures/types.ts
git commit -m "test(e2e): add the pageErrors fixture and the render-check noise allowlist"
```

---

### Task 5: The `frontend` project and nine render checks

Implements spec D2, D2a, D3 and inventory row 1. This is the task that first proves PR A's
attributes reach the browser, and the task that determines the allowlist's real contents.

**Files:**
- Create: `e2e/tests/frontend/helpers.ts`, `e2e/tests/frontend/render.spec.ts`
- Modify: `e2e/playwright.config.ts`, `e2e/package.json`, `e2e/README.md`,
  `e2e/fixtures/page-errors.ts` (allowlist entries, if any are justified)

**Interfaces:**
- Consumes: `pageErrors` (Task 4), the eleven test ids (Task 1).
- Produces:
  - `type Surface = { name: string; route: string; testId: string }`
  - `SURFACES: readonly Surface[]` — nine entries
  - `gotoSurface(page: Page, surface: Surface): Promise<void>`

- [ ] **Step 1: Write the surface table**

Create `e2e/tests/frontend/helpers.ts`:

```ts
/**
 * The nine surfaces G6 covers, and the one way to reach them.
 *
 * `route` is what a test navigates to. Two of them are hash routes rather than
 * router routes: `Settings.jsx` reads `useLocation().hash`, looks the id up in
 * `SETTINGS_GROUPS` (`frontend/src/config/settingsNav.js`) and renders that
 * section inside `<Suspense>`. So `/settings#backups` renders `BackupManager`
 * directly, with no sidebar click — and the Backups "surface" is a Settings
 * section, not a route of its own.
 *
 * `testId` is the container PR A added. It is what a test waits on, and
 * nothing here selects by text: text selectors couple the suite to UI copy.
 */
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

export type Surface = {
  /** Matches the `Frontend | …` row in `e2e/COVERAGE.md`. */
  name: string;
  route: string;
  testId: string;
};

export const SURFACES: readonly Surface[] = [
  { name: 'Guide', route: '/guide', testId: 'guide-page' },
  { name: 'DVR', route: '/dvr', testId: 'dvr-page' },
  { name: 'Users', route: '/users', testId: 'users-page' },
  // The bare `/settings` route renders "Select a setting from the sidebar" and
  // reads nothing from the server. The User-Agents section is a real read
  // through a real DRF ModelViewSet, which is what makes it a wiring check.
  { name: 'Settings', route: '/settings#user-agents', testId: 'settings-page' },
  { name: 'Plugins', route: '/plugins', testId: 'plugins-page' },
  { name: 'Stats', route: '/stats', testId: 'stats-page' },
  { name: 'Connect', route: '/connect', testId: 'connect-page' },
  { name: 'Logos', route: '/logos', testId: 'logos-page' },
  { name: 'Backups', route: '/settings#backups', testId: 'backups-panel' },
];

/**
 * Navigate and wait for the surface to have actually mounted.
 *
 * `waitForLoadState('networkidle')` is deliberately NOT used: the Stats page
 * polls on an interval and the WebSocket consumer reconnects, so this app
 * never reaches network idle and the wait would burn the whole test timeout.
 * The test id becoming visible is the honest barrier.
 */
export async function gotoSurface(page: Page, surface: Surface): Promise<void> {
  await page.goto(surface.route);
  await expect(page.getByTestId(surface.testId)).toBeVisible();
}
```

- [ ] **Step 2: Write the nine render checks**

Create `e2e/tests/frontend/render.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import { SURFACES, gotoSurface } from './helpers';

// Exemplar: the cheapest wiring proof in G6, and the reason the project
// exists. `frontend/src/api.js` (4,017 lines) and `WebSocket.jsx` (1,130) have
// no tests at all, and every vitest test mocks `api.js` — so nothing else in
// this repository observes a page talking to a real server. These nine tests
// assert the page mounts, throws nothing, logs no error, and issues no request
// the server refuses.
//
// They deliberately do NOT assert on content: that is each surface's own spec.
for (const surface of SURFACES) {
  test(`${surface.name} renders clean at ${surface.route}`, async ({
    adminPage,
    pageErrors,
  }) => {
    await gotoSurface(adminPage, surface);

    // A moment for deferred work — lazy chunks, the first poll, the WebSocket
    // handshake — to produce whatever it is going to produce. Bounded, and
    // short: this runs nine times.
    await adminPage.waitForTimeout(2_000);

    pageErrors.expectClean();
  });
}
```

- [ ] **Step 3: Add the project**

In `e2e/playwright.config.ts`, after the `streaming-greybox` project:

```ts
    {
      name: 'frontend',
      testDir: './tests/frontend',
      dependencies: ['bootstrap'],
      // 120s, between `seeded`'s 30s and the streaming projects' 300s, and
      // derived rather than picked: the slowest row here is the backups flow,
      // which polls a Celery task through `waitFor` (60s default budget), and
      // the Stats row, which opens a real upstream stream and then waits out
      // the page's 5s stats poll. 30s cannot hold either. 300s would turn a
      // page that never renders into a five-minute stall instead of a
      // two-minute failure.
      timeout: 120_000,
      // Two workers, and `fullyParallel` deliberately left unset so it
      // inherits `false` — files run in parallel, tests within a file do not.
      // That is not a style choice: `apps/backups/services.py`'s
      // `create_backup` derives the archive name from the clock at SECOND
      // granularity and `list_backups` globs the directory, so two concurrent
      // creates overwrite one archive with another and no name identifies
      // either. Confining backup creation to one file, and one file to one
      // worker, makes that race structurally impossible. `plugins.spec.ts`
      // gets the same protection for the plugin directory and its shared
      // `.reload_token`. `streaming` already runs exactly this shape.
      //
      // ONE SPEC FILE PER SURFACE, for the same reason. Splitting
      // `backups.spec.ts` in two would put two backup-creating files on two
      // workers and reopen the collision.
      workers: 2,
      // Required. `adminPage` is an alias of `page`; the admin identity comes
      // from this line, not from the fixture. Without it every test here runs
      // unauthenticated and lands on /login.
      use: { storageState: 'playwright/.auth/admin.json' },
    },
```

- [ ] **Step 4: Add the npm script**

In `e2e/package.json`:

```json
    "test:frontend": "playwright test --project=frontend",
```

and change the bare `test` script's message from five populations to six:

```json
    "test": "echo 'Pick a population: npm run test:pristine | test:seeded | test:streaming | test:streaming-failover | test:streaming-greybox | test:frontend — they need different container states and cannot share one invocation.' && exit 1",
```

- [ ] **Step 5: Do NOT touch the CI workflow in this task**

The matrix edit belongs to Task 15. Same reasoning G4 used: keeping the workflow untouched
until the project is complete means intermediate commits on this branch do not redden CI, and
it keeps the single zizmor-gated edit in one reviewable place.

- [ ] **Step 6: Run the render checks**

```bash
cd e2e && npx playwright test --project=frontend
```

Expected on the first attempt: **some of the nine fail**, and that is the point of this step.
Three outcomes and what each means:

1. **`getByTestId(...)` never becomes visible** for one surface → either the image is stale
   (Task 3 Step 2) or Mantine did not spread the prop onto that element. Fix in PR A's branch,
   rebuild, re-run.
2. **`expectClean()` fails on a `console.error` from React** → read it. The one already known
   is `Connect.jsx`'s `IntegrationRow`, which maps `integration.subscriptions` to `<Badge>`
   with **no `key` prop**; React reports "Each child in a list should have a unique key
   prop" through `console.error`. **This is a defect. File it, do not allowlist it.** See
   Step 8.
3. **`expectClean()` fails on a 4xx/5xx** → determine whether the request is one the app makes
   speculatively (a plugin logo that does not exist, a favicon) or one that is genuinely
   broken. Only the former is allowlist material.

- [ ] **Step 7: Fill in the allowlist, entry by entry**

For each remaining offender that is genuinely not a defect, add one entry to
`EXPECTED_PAGE_NOISE` in `e2e/fixtures/page-errors.ts`. Exact path or exact message prefix, and
a reason that would satisfy a reviewer. For example, if a plugin logo 404 turns out to be
expected:

```ts
export const EXPECTED_PAGE_NOISE: readonly PageNoiseEntry[] = [
  {
    kind: 'response',
    match: '/api/plugins/plugins/',
    reason:
      'PluginLogoAPIView returns 404 for a plugin with no logo.png, and the ' +
      'Plugins page requests one per card unconditionally. A missing optional ' +
      'asset, not a failure — apps/plugins/api_views.py, PluginLogoAPIView.',
  },
];
```

**Do not add an entry you cannot justify in a sentence naming the code.** An unexplained entry
is how this check stops being a check. If the list reaches more than three or four entries,
stop and re-read them: that is a signal the collector is too broad or the app is genuinely
noisy, and either is worth raising in the PR.

- [ ] **Step 8: File the defects you found**

For the `Connect.jsx` missing-`key` case, and anything else in category 2:

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "Connect page: subscription badges rendered without a React key" \
  --body "\`frontend/src/pages/Connect.jsx\`, \`IntegrationRow\`, maps
\`integration.subscriptions\` to \`<Badge>\` elements with no \`key\` prop, so
React logs \"Each child in a list should have a unique key prop\" through
\`console.error\` whenever an integration has an enabled subscription.

Found by G6's render check (\`e2e/tests/frontend/render.spec.ts\`), which
treats any \`console.error\` as a failure. Not patched here: the E2E programme
files product defects rather than fixing them from a test PR
(\`docs/superpowers/specs/2026-08-23-e2e-coverage-roadmap-design.md\`, rule 5)."
```

Then mark the Connect render check `test.fail()` with the defect named, until the issue is
fixed. In `render.spec.ts`, inside the loop:

```ts
    // Connect renders subscription badges without a React `key`
    // (frontend/src/pages/Connect.jsx, IntegrationRow), so React logs an error
    // whenever an integration on this instance has an enabled subscription.
    // Asserted correct and marked failing per the roadmap's rule 5; filed as
    // <issue url>. Delete this block when the product is fixed — the suite
    // then goes red the other way and tells you.
    if (surface.name === 'Connect') test.fail();
```

Place it as the first statement inside the `test()` body, not outside it: `test.fail()` outside
a test body applies to the whole file.

**If the Connect page has no integrations on a fresh container, the warning does not fire and
this test passes.** Note that in the comment — the `connect.spec.ts` write flow (Task 9) creates
an integration *with* subscriptions, which makes the defect reproducible; if the render check
runs before it on a shared container it will be green, and that is honest, not a mask.

- [ ] **Step 9: Document the project**

In `e2e/README.md`'s "Projects" table, add:

```
| `frontend` | The nine product surfaces in a browser: does the page mount, and does a write driven through its UI reach the server. Two workers, file-level parallelism, 120s |
```

Then, below the table, add a paragraph stating the two rules the project depends on:

- **One spec file per surface**, because `backups.spec.ts` and `plugins.spec.ts` each mutate
  container-wide state (the backup archive directory, whose filenames are second-granularity
  and caller-unnameable; and the plugin directory plus its shared `.reload_token`). File-level
  parallelism is what confines each to one worker; splitting either file reopens the race.
- **After a change to any `frontend/` source file, rebuild the image before running this
  project.** `./scripts/e2e_up.sh --reset` reuses an existing `dispatcharr-e2e:local`, so a
  stale image serves the old bundle and every locator fails in a way that looks like a broken
  test. `docker rmi dispatcharr-e2e:local` first.

- [ ] **Step 10: Re-run until green**

```bash
cd e2e && npx playwright test --project=frontend
```

Expected: 9 passed (or 8 passed, 1 expected-failure if the Connect defect reproduces).

- [ ] **Step 11: Commit**

```bash
git add e2e/tests/frontend/helpers.ts e2e/tests/frontend/render.spec.ts \
  e2e/fixtures/page-errors.ts e2e/playwright.config.ts e2e/package.json e2e/README.md
git commit -m "test(e2e): add the frontend project and nine render checks"
```

---

### Task 6: Guide — sidebar navigation and a backend-sourced row

Implements inventory row 2 and spec D12. Guide is a read surface: its wiring proof is that the
grid is populated from `/api/channels/channels/`.

**Files:**
- Create: `e2e/tests/frontend/guide.spec.ts`

**Interfaces:**
- Consumes: `seed.channel()`, `guide-page`, `guide-grid`.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the test**

Create `e2e/tests/frontend/guide.spec.ts`:

```ts
import { test, expect } from '../../fixtures';

// Guide has no write flow — its COVERAGE row is "renders and navigates" — so
// its wiring proof is that the grid is populated from the channel API rather
// than from anything the browser could have invented. It is also the one test
// in G6 that reaches its surface by CLICKING the sidebar instead of calling
// goto(), which is where the SPA's router wiring gets exercised at all.
test('the Guide grid is populated from the channel API, reached from the sidebar', async ({
  adminPage,
  seed,
}) => {
  const channel = await seed.channel();

  await adminPage.goto('/channels');
  await adminPage.getByRole('link', { name: 'Guide' }).click();

  await expect(adminPage).toHaveURL(/\/guide/);
  await expect(adminPage.getByTestId('guide-page')).toBeVisible();

  const grid = adminPage.getByTestId('guide-grid');
  await expect(grid).toBeVisible();

  // Scoped to the grid and filtered by the name `seed` generated: never a
  // count, never an unfiltered list. Four workers share this instance and the
  // Guide shows every channel on it.
  await expect(grid.getByText(channel.name, { exact: false })).toBeVisible({
    timeout: 30_000,
  });
});
```

- [ ] **Step 2: Run it**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/guide.spec.ts
```

- [ ] **Step 3: If the row does not appear, find out which filter excluded it**

This is the spec's one open assumption. A bare `seed.channel()` has no Channel Profile
membership, no group and no EPG data, and whether it survives the Guide's default filters has
not been verified against a live container.

If the assertion times out, do **not** loosen it. Diagnose:

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/guide.spec.ts --debug
```

In the page, check whether `guide-grid` contains "No channels match your filters" (the grid
rendered but filtered everything out) or rows for other channels but not yours (a
membership/visibility filter). Then add the missing precondition to the test — most likely
adding the channel to the default Channel Profile via `api.patch` before navigating — and say
in a comment why it was needed. If the channel is genuinely unreachable in the Guide without
EPG data, record it as a gap in `COVERAGE.md` (Task 15) rather than deleting the assertion.

- [ ] **Step 4: Verify the sidebar link name**

If `getByRole('link', { name: 'Guide' })` does not resolve, the sidebar's nav item may be a
button, or its label may be hidden behind a tooltip when the sidebar is collapsed —
`e2e/tests/seeded/authenticated-session.spec.ts` records exactly that hazard for other nav
labels. Check `frontend/src/components/Sidebar.jsx` for the element and its accessible name,
and use whichever role it actually is. Do **not** add a test id for it: PR A is closed, and the
nav item has a real accessible name.

- [ ] **Step 5: Commit**

```bash
git add e2e/tests/frontend/guide.spec.ts
git commit -m "test(e2e): Guide grid is populated from the channel API"
```

---

### Task 7: Users — create, edit, delete through the UI

Implements inventory row 4.

**Files:**
- Create: `e2e/tests/frontend/users.spec.ts`

**Interfaces:**
- Consumes: `seed.generatedName`, `SEEDED_USER_PASSWORD`, `listRows`, type `User`, `users-page`.

- [ ] **Step 1: Write the test**

Create `e2e/tests/frontend/users.spec.ts`:

```ts
import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';
import type { User } from '../../fixtures';
import { listRows } from '../../setup/http';

/** The row this test created, by the name it generated. Never a count. */
async function findUser(
  api: { get: (url: string) => Promise<import('@playwright/test').APIResponse>;
         json: <T>(res: import('@playwright/test').APIResponse, ctx: string) => Promise<T> },
  username: string
): Promise<User | undefined> {
  const body = await api.json<unknown>(
    await api.get('/api/accounts/users/'),
    'list users'
  );
  return listRows<User>(body).find((u) => u.username === username);
}

test('a user created through the Users page exists on the server, and survives edit and delete', async ({
  adminPage,
  api,
  seed,
}) => {
  const username = seed.generatedName('user');

  await adminPage.goto('/users');
  await expect(adminPage.getByTestId('users-page')).toBeVisible();

  // Roles and labels, not test ids: every control here has an accessible name.
  await adminPage.getByRole('button', { name: /add user|create user|new user/i }).click();
  await adminPage.getByLabel('Username').fill(username);
  await adminPage.getByLabel('Password', { exact: true }).fill(SEEDED_USER_PASSWORD);
  await adminPage.getByRole('button', { name: /save|create|submit/i }).click();

  // The assertion is the server's state, not a toast. `api.js`'s
  // errorNotification toasts AND rethrows, so a red toast and a green toast
  // are equally consistent with a write that never left the browser.
  await expect.poll(() => findUser(api, username), { timeout: 30_000 }).toBeDefined();
  const created = (await findUser(api, username))!;

  // Edit: raise the level through the UI and re-read from the server.
  await adminPage.getByRole('row', { name: new RegExp(username) })
    .getByRole('button', { name: /edit/i })
    .click();
  await adminPage.getByLabel(/user level/i).click();
  await adminPage.getByRole('option', { name: /standard/i }).click();
  await adminPage.getByRole('button', { name: /save|update|submit/i }).click();

  await expect
    .poll(async () => (await findUser(api, username))?.user_level, { timeout: 30_000 })
    .toBe(1);

  // Delete, and prove absence from the server rather than from the table.
  await adminPage.getByRole('row', { name: new RegExp(username) })
    .getByRole('button', { name: /delete|remove/i })
    .click();
  await adminPage.getByRole('button', { name: /confirm|delete|yes/i }).click();

  await expect.poll(() => findUser(api, username), { timeout: 30_000 }).toBeUndefined();

  // And directly, so a list-shape change cannot make absence look like success.
  const gone = await api.get(`/api/accounts/users/${created.id}/`);
  expect(gone.status()).toBe(404);
});
```

- [ ] **Step 2: Run it and fix the locators against the real DOM**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/users.spec.ts
```

The regex-alternation locators above (`/add user|create user|new user/i`) are written that way
**on purpose**: the exact button copy in `frontend/src/components/tables/UsersTable.jsx` and
`frontend/src/components/forms/User.jsx` has not been read for this plan, and guessing one
string would produce a confidently wrong locator. Run the test, read the failure — Playwright
prints the candidates it considered — and **replace each alternation with the single exact
name**. Leaving an alternation in place is a latent bug: it would silently match a different
button if the copy changed.

Do the same for the `user level` control: if it is a Mantine `Select` its trigger is an input
with a label, and its options are `role="option"` in a portal; if it is a `NativeSelect`,
`selectOption` is the right verb. Read `frontend/src/components/forms/User.jsx`.

- [ ] **Step 3: Confirm the row locator resolves**

`getByRole('row', …)` assumes `UsersTable` renders a real `<table>`. This repo has a custom
`CustomTable` component; if it renders `<div>`s, `getByRole('row')` will not resolve. In that
case scope by `getByTestId('users-page').getByText(username)` and walk up with
`.locator('xpath=ancestor::*[...]')` — or, better, assert the row is visible and drive the
action buttons scoped to the page, since the generated username makes the page-wide scope
unambiguous.

- [ ] **Step 4: Commit**

```bash
git add e2e/tests/frontend/users.spec.ts
git commit -m "test(e2e): Users page create, edit and delete reach the server"
```

---

### Task 8: Settings — create a User-Agent and prove it persisted

Implements inventory row 5 and spec D5.

**Files:**
- Create: `e2e/tests/frontend/settings.spec.ts`

**Interfaces:**
- Consumes: `seed.generatedName`, `listRows`, type `UserAgent`, `settings-page`.

- [ ] **Step 1: Write the test**

Create `e2e/tests/frontend/settings.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import type { UserAgent } from '../../fixtures';
import { listRows } from '../../setup/http';

// "Settings: change and persist", read the only way that is available on a
// shared instance. The obvious reading — change a global CoreSettings value —
// is unavailable three times over: e2e/README.md assigns global CoreSettings
// changes to the `pristine` project by name, the roadmap's rule 4 forbids
// mutating instance-wide state four workers share, and G7 already writes
// system_settings.max_system_events for its own persistence assertions.
// UiSettingsForm, the other candidate, persists only to localStorage
// (useLocalStorage for time-format/date-format/time-zone) and so proves no
// wiring at all. User-Agents is a real Settings section backed by a real DRF
// ModelViewSet, row-scoped, and touched by no other goal.
test('a User-Agent created from Settings is stored server-side and survives a reload', async ({
  adminPage,
  api,
  seed,
}) => {
  const name = seed.generatedName('userAgent');

  await adminPage.goto('/settings#user-agents');
  await expect(adminPage.getByTestId('settings-page')).toBeVisible();

  await adminPage.getByRole('button', { name: /add|new/i }).click();
  await adminPage.getByLabel(/name/i).fill(name);
  await adminPage.getByLabel(/user.?agent/i).fill('Dispatcharr-E2E/1.0');
  await adminPage.getByRole('button', { name: /save|create|submit/i }).click();

  const find = async (): Promise<UserAgent | undefined> =>
    listRows<UserAgent>(
      await api.json<unknown>(await api.get('/api/core/useragents/'), 'list user agents')
    ).find((ua) => ua.name === name);

  await expect.poll(find, { timeout: 30_000 }).toBeDefined();
  expect((await find())!.user_agent).toBe('Dispatcharr-E2E/1.0');

  // The "persist" half. A reload discards every Zustand store, so a row still
  // rendered afterwards was fetched from the server, not remembered.
  await adminPage.reload();
  await expect(adminPage.getByTestId('settings-page')).toBeVisible();
  await expect(adminPage.getByTestId('settings-page').getByText(name)).toBeVisible({
    timeout: 30_000,
  });
});
```

- [ ] **Step 2: Run it and fix the locators**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/settings.spec.ts
```

Read `frontend/src/components/tables/UserAgentsTable.jsx` and
`frontend/src/components/forms/UserAgent.jsx` and replace every regex alternation with the
exact accessible name, as in Task 7 Step 2. Note the `getByLabel(/name/i)` and
`getByLabel(/user.?agent/i)` pair is especially likely to be ambiguous if a field is labelled
"User-Agent Name" — Playwright will say `strict mode violation` and list both. Use
`{ exact: true }` with the real strings.

- [ ] **Step 3: Confirm the hash route renders the section on a cold load**

If `settings-page` is visible but the User-Agents controls are not, the `<Suspense>` fallback
may still be up, or the hash may not be read on a direct navigation. Add an explicit wait on a
control the section owns (not a `waitForTimeout`), and if the hash genuinely does not work on
a cold load, note it — that would be a product defect worth filing, since `Settings.jsx` reads
`useLocation().hash` unconditionally and is expected to.

- [ ] **Step 4: Commit**

```bash
git add e2e/tests/frontend/settings.spec.ts
git commit -m "test(e2e): a User-Agent created from Settings persists server-side"
```

---

### Task 9: Connect — webhook create, toggle, delete

Implements inventory row 8.

**Files:**
- Create: `e2e/tests/frontend/connect.spec.ts`

**Interfaces:**
- Consumes: `seed.generatedName`, `listRows`, type `ConnectIntegration`, `connect-page`,
  `connect-integrations`.

- [ ] **Step 1: Write the test**

Create `e2e/tests/frontend/connect.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import type { ConnectIntegration } from '../../fixtures';
import { listRows } from '../../setup/http';

// The Connect form's fields are labelled `Name`, `Connection Type`,
// `Webhook URL` and `Script Path` (frontend/src/components/forms/Connection.jsx),
// so this whole flow is driven by label and role. The only test id it uses
// scopes the assertion to the integration grid — the page also renders a
// fixed-position <ConnectLogsSection> that prints integration names, and a log
// line must not pass for a card.
test('a webhook integration created through the Connect page round-trips to the server', async ({
  adminPage,
  api,
  seed,
}) => {
  const name = seed.generatedName('integration');

  await adminPage.goto('/connect');
  await expect(adminPage.getByTestId('connect-page')).toBeVisible();

  await adminPage.getByRole('button', { name: 'New Connection' }).click();
  await adminPage.getByLabel('Name').fill(name);
  await adminPage.getByLabel('Connection Type').click();
  await adminPage.getByRole('option', { name: /webhook/i }).click();
  await adminPage.getByLabel('Webhook URL').fill('http://e2e-upstream:9402/does-not-matter');
  await adminPage.getByRole('button', { name: /save|create|submit/i }).click();

  const find = async (): Promise<ConnectIntegration | undefined> =>
    listRows<ConnectIntegration>(
      await api.json<unknown>(
        await api.get('/api/connect/integrations/'),
        'list connect integrations'
      )
    ).find((i) => i.name === name);

  await expect.poll(find, { timeout: 30_000 }).toBeDefined();
  const created = (await find())!;
  expect(created.type).toBe('webhook');
  expect(created.config.url).toBe('http://e2e-upstream:9402/does-not-matter');

  // The card is rendered in the integrations grid, scoped away from the log.
  const grid = adminPage.getByTestId('connect-integrations');
  await expect(grid.getByText(name)).toBeVisible({ timeout: 30_000 });

  // Toggle: the Switch is labelled `Enabled` in IntegrationRow.
  const card = grid.locator('..').getByText(name).locator('xpath=ancestor::*[self::div][1]');
  await grid.getByText(name).scrollIntoViewIfNeeded();
  await adminPage.getByLabel('Enabled').first().click();
  await expect
    .poll(async () => (await find())?.enabled, { timeout: 30_000 })
    .toBe(!created.enabled);
  void card;

  // Delete. `deleteConnection` has no confirmation dialog
  // (frontend/src/pages/Connect.jsx), so the click is the whole action.
  await adminPage.getByRole('button', { name: 'Delete' }).first().click();
  await expect.poll(find, { timeout: 30_000 }).toBeUndefined();
});
```

- [ ] **Step 2: Run it and tighten the card scoping**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/connect.spec.ts
```

The `.first()` calls on `Enabled` and `Delete` are the weak point: four workers share this
instance and other integrations may exist, so `.first()` could act on someone else's card.
**Replace them.** Read `IntegrationRow` in `frontend/src/pages/Connect.jsx` and scope both to
the card containing `name` — `grid.locator('div', { hasText: name })` narrowed until it
resolves to one element, then `.getByLabel('Enabled')` and
`.getByRole('button', { name: 'Delete' })` inside it. The `card` placeholder and its `void
card;` line above exist to mark this spot; delete both once the real scoping is in.

Getting this right matters more here than anywhere else in G6: acting on another worker's card
would delete their data mid-run and the failure would surface in an unrelated test.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/frontend/connect.spec.ts
git commit -m "test(e2e): Connect webhook create, toggle and delete round-trip"
```

---

### Task 10: Logos — upload and browse

Implements inventory row 9.

**Files:**
- Create: `e2e/tests/frontend/assets.ts`, `e2e/tests/frontend/logos.spec.ts`

**Interfaces:**
- Consumes: `seed.generatedName`, `listRows`, type `Logo`, `logos-page`.
- Produces: `TINY_PNG: Buffer`.

- [ ] **Step 1: Add the asset**

Create `e2e/tests/frontend/assets.ts`:

```ts
/**
 * A 1x1 transparent PNG, as bytes.
 *
 * In memory rather than on disk: `setInputFiles` accepts
 * `{ name, mimeType, buffer }`, so no temp file, no cleanup, and no binary
 * committed to the repository that a reader cannot inspect. The base64 below
 * is the canonical minimal PNG — an 8-byte signature, IHDR, a single IDAT and
 * IEND.
 */
export const TINY_PNG: Buffer = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk' +
    'YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64'
);
```

- [ ] **Step 2: Write the test**

Create `e2e/tests/frontend/logos.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import type { Logo } from '../../fixtures';
import { listRows } from '../../setup/http';
import { TINY_PNG } from './assets';

// NEVER click "Cleanup Unused" on this page. It calls
// /api/channels/logos/cleanup/, which deletes every unreferenced logo
// instance-wide — four workers' data and G3's seeded logos with it.
test('a logo uploaded through the Logos page is stored server-side and listed', async ({
  adminPage,
  api,
  seed,
}) => {
  const name = seed.generatedName('logo');

  await adminPage.goto('/logos');
  await expect(adminPage.getByTestId('logos-page')).toBeVisible();

  await adminPage.getByRole('button', { name: 'Add Logo' }).click();

  // Mantine's Dropzone renders a real <input type="file">, hidden. Setting
  // files on it directly is how Playwright drives a dropzone; there is no
  // need to synthesise a drag event.
  await adminPage.locator('input[type="file"]').setInputFiles({
    name: 'e2e-logo.png',
    mimeType: 'image/png',
    buffer: TINY_PNG,
  });
  await adminPage.getByLabel(/name/i).fill(name);
  await adminPage.getByRole('button', { name: /save|create|submit|upload/i }).click();

  const find = async (): Promise<Logo | undefined> =>
    listRows<Logo>(
      await api.json<unknown>(
        await api.get(`/api/channels/logos/?name=${encodeURIComponent(name)}`),
        'list logos'
      )
    ).find((l) => l.name === name);

  await expect.poll(find, { timeout: 60_000 }).toBeDefined();
  const created = (await find())!;
  expect(created.url, 'an uploaded logo should have a URL to serve it from').toBeTruthy();

  // And it is actually retrievable, which a row alone does not prove.
  const fetched = await api.get(created.url);
  expect(fetched.status()).toBe(200);

  // The browse half of the row: it is rendered in the table.
  await expect(adminPage.getByTestId('logos-page').getByText(name)).toBeVisible({
    timeout: 30_000,
  });
});
```

- [ ] **Step 3: Run it and fix the query and the locators**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/logos.spec.ts
```

Two things to confirm against the real API, neither assumed here:

- **Does `/api/channels/logos/` accept a `?name=` filter?** `LogoViewSet.get_queryset` says it
  "adds filtering"; read it. If the parameter is different (or absent), drop the query string —
  the `.find()` on the name still holds, and the list is paginated by `LogoPagination`, so if
  it is, page through or use whatever filter the viewset does support. **Do not assert on the
  first page of an unfiltered list**; that is roadmap rule 4.
- **Is `created.url` absolute or relative?** If relative, `api.get` will resolve it against
  `baseURL`, which is correct. If it is absolute and points at the container's internal
  hostname, drop that assertion and keep the row assertion.

Then replace the regex alternations with exact names from
`frontend/src/components/forms/Logo.jsx`.

- [ ] **Step 4: Commit**

```bash
git add e2e/tests/frontend/assets.ts e2e/tests/frontend/logos.spec.ts
git commit -m "test(e2e): a logo uploaded through the UI is stored and retrievable"
```

---

### Task 11: DVR — schedule, list, cancel

Implements inventory row 3 and spec D7. The fiddliest interaction in G6.

**Files:**
- Create: `e2e/tests/frontend/dvr.spec.ts`

**Interfaces:**
- Consumes: `seed.channel()`, `listRows`, type `Recording`, `dvr-page`.

- [ ] **Step 1: Write the test**

Create `e2e/tests/frontend/dvr.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import type { Recording } from '../../fixtures';
import { listRows } from '../../setup/http';

/**
 * Move a Mantine DateTimePicker one month forward and pick the 15th.
 *
 * Why not "today plus two days": `getSingleFormDefaults()`
 * (frontend/src/utils/forms/RecordingUtils.js) defaults start_time to a
 * rounded *now* and end_time to now + 60 min, so a form submitted as rendered
 * schedules a recording that `run_recording` fires immediately — the opposite
 * of what this row wants. Advancing one month and picking the 15th is
 * deterministic whatever today's date is (15 to 46 days out), exists in every
 * month, needs no arithmetic, and cannot land in the past.
 *
 * Both pickers move, because the form validates end_time > start_time.
 */
async function scheduleNextMonth(
  page: import('@playwright/test').Page,
  fieldLabel: string
): Promise<void> {
  await page.getByLabel(fieldLabel).click();
  await page.getByRole('button', { name: /next month/i }).click();
  await page.getByRole('button', { name: '15', exact: true }).click();
}

test('a recording scheduled from the DVR page exists on the server and can be cancelled', async ({
  adminPage,
  api,
  seed,
}) => {
  const channel = await seed.channel();

  await adminPage.goto('/dvr');
  await expect(adminPage.getByTestId('dvr-page')).toBeVisible();

  await adminPage.getByRole('button', { name: 'New Recording' }).click();
  await adminPage.getByLabel('Channel').click();
  await adminPage.getByRole('option', { name: new RegExp(channel.name) }).click();

  await scheduleNextMonth(adminPage, 'Start');
  await scheduleNextMonth(adminPage, 'End');

  await adminPage.getByRole('button', { name: /save|create|schedule|submit/i }).click();

  // The point of this row is the scheduling round-trip, not the recording:
  // `run_recording` never fires for a window this far out.
  const find = async (): Promise<Recording | undefined> =>
    listRows<Recording>(
      await api.json<unknown>(
        await api.get('/api/channels/recordings/'),
        'list recordings'
      )
    ).find((r) => r.channel === channel.id);

  await expect.poll(find, { timeout: 30_000 }).toBeDefined();
  const created = (await find())!;

  // The window really is in the future, which is what makes this test safe to
  // run on a shared instance: a recording starting now would spawn ffmpeg.
  expect(new Date(created.start_time).getTime()).toBeGreaterThan(
    Date.now() + 7 * 24 * 60 * 60 * 1000
  );
  expect(new Date(created.end_time).getTime()).toBeGreaterThan(
    new Date(created.start_time).getTime()
  );

  // Listed under "Upcoming Recordings", scoped to this page and identified by
  // the seeded channel's generated name.
  await expect(adminPage.getByTestId('dvr-page').getByText(channel.name)).toBeVisible({
    timeout: 30_000,
  });

  // Cancel from the card, and prove absence from the server.
  await adminPage
    .getByTestId('dvr-page')
    .getByRole('button', { name: /cancel|delete/i })
    .first()
    .click();
  await adminPage.getByRole('button', { name: /confirm|yes|delete/i }).click();

  await expect.poll(find, { timeout: 30_000 }).toBeUndefined();
  expect((await api.get(`/api/channels/recordings/${created.id}/`)).status()).toBe(404);
});
```

- [ ] **Step 2: Run it, and resolve the calendar locators against the real DOM**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/dvr.spec.ts --headed
```

`getByRole('button', { name: /next month/i })` and `getByRole('button', { name: '15' })` are
Mantine 8 rendering details this plan has not verified. Run headed, open the picker, and read
the actual DOM. Likely realities to handle:

- Mantine's month-navigation control may have an `aria-label` of "Next month" or may be an icon
  button with no name, in which case use its `data-direction="next"` attribute:
  `page.locator('[data-direction="next"]')`.
- Day cells are `<button>`s inside a `role="grid"`; if `getByRole('button', { name: '15' })` is
  ambiguous (a day from the adjacent month rendered in the same grid), scope with
  `page.getByRole('grid').getByRole('button', { name: '15', exact: true })` and, if needed,
  exclude outside days with `:not([data-outside])`.
- The `Start`/`End` labels come from `frontend/src/components/forms/Recording.jsx`; confirm them.

- [ ] **Step 3: If the picker proves intractable, record a gap — do not substitute an API create**

Give this a genuine attempt. If after resolving the DOM the interaction is still unreliable,
stop: creating the recording through `api.post` would prove nothing about the DVR page and
would be a test that looks like coverage and is not. Mark the test `test.fixme()` with the
reason, and add a gap line to the DVR row in `COVERAGE.md` (Task 15) saying the scheduling
round-trip is unproven and why.

- [ ] **Step 4: Tighten the cancel button scoping**

As in Task 9, `.first()` on the cancel button is a hazard: another worker's recording card may
be rendered too. Scope it to the card containing `channel.name` once you have read
`frontend/src/components/cards/RecordingCard.jsx`. Note that `handleDeleteClick` there may skip
the confirmation dialog for some recording states — read it and drop the confirm click if it
does not appear.

- [ ] **Step 5: Commit**

```bash
git add e2e/tests/frontend/dvr.spec.ts
git commit -m "test(e2e): a recording scheduled from the DVR page round-trips and cancels"
```

---

### Task 12: Plugins — import, enable, configure, delete

Implements inventory row 6 and spec D8.

**Files:**
- Create: `e2e/tests/frontend/plugin-zip.ts`, `e2e/tests/frontend/plugins.spec.ts`

**Interfaces:**
- Consumes: `seed.generatedName`, type `PluginListEntry`, `plugins-page`.
- Produces: `buildPluginZip(opts: { key: string; name: string }): Buffer`.

- [ ] **Step 1: Write the failing zip-builder test**

Create `e2e/tests/frontend/plugin-zip.ts` as an empty module first, then write this test as the
first block of `e2e/tests/frontend/plugins.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import { buildPluginZip } from './plugin-zip';

// The archive is built here rather than committed as a binary so the plugin
// key can carry per-run entropy. A committed zip has a fixed key, which
// collides with itself on a second run against a non-reset container:
// PluginImportAPIView defaults to non-overwrite and returns 400.
test('the plugin archive builder produces a readable zip', () => {
  const zip = buildPluginZip({ key: 'e2e_probe', name: 'E2E Probe' });

  // Local file header, and an end-of-central-directory record.
  expect(zip.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))).toBeGreaterThan(0);

  // Both members are present, under the key's directory — which is what
  // `_install_plugin_from_zip` walks to choose the plugin directory.
  expect(zip.includes('e2e_probe/plugin.json')).toBe(true);
  expect(zip.includes('e2e_probe/plugin.py')).toBe(true);
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/plugins.spec.ts
```

Expected: FAIL — `buildPluginZip` is not exported.

- [ ] **Step 3: Write the zip builder**

Create `e2e/tests/frontend/plugin-zip.ts`:

```ts
/**
 * A minimal ZIP writer, stored (uncompressed) entries only.
 *
 * Node has no zip container in its standard library, and the alternatives were
 * both worse: committing a binary archive fixes the plugin key (see the test),
 * and shelling out to `zip` adds a host dependency CI does not guarantee. A
 * stored-entry archive is ~60 lines of buffer arithmetic and Python's
 * `zipfile.ZipFile` — which is what `_install_plugin_from_zip` uses — reads
 * stored entries with no special handling.
 *
 * The plugin it builds is INERT BY CONSTRUCTION. Enabling a plugin causes
 * `PluginManager._load_plugin` to import its module into the uWSGI worker and
 * run it there, unsandboxed (CLAUDE.md, "Events and plugins"). This one
 * declares one settings field and a `run` that returns a constant.
 */

const CRC_TABLE: number[] = (() => {
  const table: number[] = [];
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

type Member = { path: string; data: Buffer };

function localHeader(member: Member, crc: number): Buffer {
  const name = Buffer.from(member.path, 'utf8');
  const head = Buffer.alloc(30);
  head.writeUInt32LE(0x04034b50, 0); // signature
  head.writeUInt16LE(20, 4); // version needed
  head.writeUInt16LE(0, 6); // flags
  head.writeUInt16LE(0, 8); // method: stored
  head.writeUInt16LE(0, 10); // mod time
  head.writeUInt16LE(0x21, 12); // mod date (1996-01-01; arbitrary and fixed)
  head.writeUInt32LE(crc, 14);
  head.writeUInt32LE(member.data.length, 18);
  head.writeUInt32LE(member.data.length, 22);
  head.writeUInt16LE(name.length, 26);
  head.writeUInt16LE(0, 28); // extra length
  return Buffer.concat([head, name]);
}

function centralHeader(member: Member, crc: number, offset: number): Buffer {
  const name = Buffer.from(member.path, 'utf8');
  const head = Buffer.alloc(46);
  head.writeUInt32LE(0x02014b50, 0);
  head.writeUInt16LE(20, 4); // version made by
  head.writeUInt16LE(20, 6); // version needed
  head.writeUInt16LE(0, 8);
  head.writeUInt16LE(0, 10); // stored
  head.writeUInt16LE(0, 12);
  head.writeUInt16LE(0x21, 14);
  head.writeUInt32LE(crc, 16);
  head.writeUInt32LE(member.data.length, 20);
  head.writeUInt32LE(member.data.length, 24);
  head.writeUInt16LE(name.length, 28);
  head.writeUInt16LE(0, 30); // extra
  head.writeUInt16LE(0, 32); // comment
  head.writeUInt16LE(0, 34); // disk number
  head.writeUInt16LE(0, 36); // internal attrs
  head.writeUInt32LE(0, 38); // external attrs
  head.writeUInt32LE(offset, 42);
  return Buffer.concat([head, name]);
}

function zipOf(members: Member[]): Buffer {
  const local: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const member of members) {
    const crc = crc32(member.data);
    const head = localHeader(member, crc);
    local.push(head, member.data);
    central.push(centralHeader(member, crc, offset));
    offset += head.length + member.data.length;
  }
  const centralBuf = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(members.length, 8);
  end.writeUInt16LE(members.length, 10);
  end.writeUInt32LE(centralBuf.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);
  return Buffer.concat([...local, centralBuf, end]);
}

/**
 * The archive `_install_plugin_from_zip` expects: a directory containing
 * `plugin.py` (which is what makes it the chosen candidate) and a
 * `plugin.json` manifest, whose `fields` are what the Plugins page renders as
 * the settings form.
 */
export function buildPluginZip(opts: { key: string; name: string }): Buffer {
  const manifest = JSON.stringify(
    {
      name: opts.name,
      version: '0.0.1',
      description: 'Inert fixture plugin for the Dispatcharr E2E suite.',
      author: 'dispatcharr-e2e',
      fields: [
        { id: 'note', label: 'Note', type: 'string', default: '' },
      ],
      actions: [],
    },
    null,
    2
  );

  const source = [
    'class Plugin:',
    `    name = ${JSON.stringify(opts.name)}`,
    '    version = "0.0.1"',
    '    description = "Inert fixture plugin for the Dispatcharr E2E suite."',
    '',
    '    fields = [',
    '        {"id": "note", "label": "Note", "type": "string", "default": ""},',
    '    ]',
    '    actions = []',
    '',
    '    def run(self, action, params, context):',
    '        return {"status": "noop"}',
    '',
  ].join('\n');

  return zipOf([
    { path: `${opts.key}/plugin.json`, data: Buffer.from(manifest, 'utf8') },
    { path: `${opts.key}/plugin.py`, data: Buffer.from(source, 'utf8') },
  ]);
}
```

- [ ] **Step 4: Run the builder test and watch it pass**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/plugins.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Add the plugin flow test**

Append to `e2e/tests/frontend/plugins.spec.ts`:

```ts
import type { PluginListEntry } from '../../fixtures';

// A plugin dropped in after boot is visible with NO restart, in every uWSGI
// worker. `PluginImportAPIView` calls `discover_plugins(force_reload=True)`,
// which touches `<plugins_dir>/.reload_token`; `PluginsListAPIView` calls
// `discover_plugins(use_cache=True)`, which reloads whenever that file's mtime
// exceeds the process's `_last_reload_token`. The token is a file on the
// shared /data volume, so it is the cross-process broadcast. The
// `worker_process_init` discovery in dispatcharr/celery.py is Celery's initial
// load, not the only path — and this is a browser row, so the web workers are
// the ones that matter.
//
// The plugin is inert by construction (see plugin-zip.ts): enabling it imports
// and runs its module in the uWSGI worker, unsandboxed. It is deleted at the
// end of the test — a leftover plugin is loaded on every subsequent discovery
// for the life of the container.
test('a plugin imported through the Plugins page lists, enables and configures', async ({
  adminPage,
  api,
  seed,
}) => {
  // Per-run entropy in the key: `_sanitize_plugin_key` lowercases and replaces
  // anything outside [a-z0-9_], so the generated name is normalised here to
  // the key the server will actually derive.
  const key = seed.generatedName('plugin').toLowerCase().replace(/[^a-z0-9_]/g, '_');
  const displayName = `E2E ${key}`;

  const list = async (): Promise<PluginListEntry | undefined> => {
    const body = await api.json<{ plugins: PluginListEntry[] }>(
      await api.get('/api/plugins/plugins/'),
      'list plugins'
    );
    return body.plugins.find((p) => p.key === key);
  };

  try {
    await adminPage.goto('/plugins');
    await expect(adminPage.getByTestId('plugins-page')).toBeVisible();

    await adminPage.getByRole('button', { name: /import/i }).click();
    await adminPage.locator('input[type="file"]').setInputFiles({
      name: `${key}.zip`,
      mimeType: 'application/zip',
      buffer: buildPluginZip({ key, name: displayName }),
    });
    await adminPage.getByRole('button', { name: /import|upload|install/i }).last().click();

    await expect.poll(list, { timeout: 60_000 }).toBeDefined();
    expect((await list())!.enabled).toBe(false);

    // Enable through the UI. The switch lives on the plugin's card; scope by
    // the generated key so it cannot be another plugin's.
    const card = adminPage.getByTestId('plugins-page').locator('div', {
      hasText: displayName,
    });
    await card.getByRole('switch').first().click();
    // The page shows a trust confirmation before enabling an untrusted plugin
    // (`onRequireTrust` in frontend/src/pages/Plugins.jsx). Accept it if it
    // appears; the locator resolution step below settles its exact copy.
    const trust = adminPage.getByRole('button', { name: /enable|trust|continue|i understand/i });
    if (await trust.isVisible().catch(() => false)) await trust.click();

    await expect.poll(async () => (await list())?.enabled, { timeout: 60_000 }).toBe(true);

    // Configure: the manifest declares one string field, `note`.
    await adminPage.getByLabel('Note').fill('configured-by-e2e');
    await adminPage.getByRole('button', { name: /save/i }).first().click();

    await expect
      .poll(async () => (await list())?.settings?.note, { timeout: 60_000 })
      .toBe('configured-by-e2e');
  } finally {
    // Always, even on failure. A leftover plugin is imported into every worker
    // on every subsequent discovery for the life of the container.
    await api.post(`/api/plugins/plugins/${key}/delete/`, {});
  }
});
```

- [ ] **Step 6: Run it and resolve the locators**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/plugins.spec.ts --headed
```

Read `frontend/src/pages/Plugins.jsx` and `frontend/src/components/cards/PluginCard.jsx` and
replace every alternation with the exact copy: the import trigger, the confirm button inside
the import modal, the enable switch's accessible name, the trust dialog's copy, and the
settings save button. The `locator('div', { hasText: displayName })` scoping needs narrowing
until it resolves to one element — Playwright's `strict mode violation` message lists the
candidates.

Confirm the delete endpoint's verb and shape against `PluginDeleteAPIView` in
`apps/plugins/api_views.py` — if it is not a bodyless POST, fix the teardown call.

- [ ] **Step 7: Confirm no restart was needed**

This is the spec's central claim about this row and it is worth checking once, explicitly:

```bash
docker exec dispatcharr-e2e ls -la /data/plugins/
docker logs dispatcharr-e2e 2>&1 | tail -30
```

Expected: the plugin directory and a `.reload_token` file are present, and the logs show no
uWSGI worker respawn around the import. If a respawn *did* happen, that is worth a line in the
PR description — but the test passing without one is the evidence that matters.

- [ ] **Step 8: Commit**

```bash
git add e2e/tests/frontend/plugin-zip.ts e2e/tests/frontend/plugins.spec.ts
git commit -m "test(e2e): a plugin imported through the UI lists, enables and configures"
```

---

### Task 13: Backups — create and validate the archive

Implements inventory row 10 and spec D9. **Create only. Never restore.**

**Files:**
- Create: `e2e/tests/frontend/backups.spec.ts`

**Interfaces:**
- Consumes: type `BackupEntry`, `backups-panel`.

- [ ] **Step 1: Write the test**

Create `e2e/tests/frontend/backups.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import type { BackupEntry } from '../../fixtures';

// CREATE ONLY. Restoring a backup replaces the database under every parallel
// worker mid-run, and under every other project sharing this container
// locally. Restore is G7's, which stands up its own instance per scenario —
// see the Lifecycle row in COVERAGE.md.
//
// This spec is the reason the `frontend` project runs file-level parallelism:
// `apps/backups/services.py`'s `create_backup` derives the archive name from
// the clock at SECOND granularity and the caller cannot name it, while
// `list_backups` globs the directory and returns everything. Two concurrent
// creates overwrite one archive with another, and nothing identifies "mine".
// The before/after set difference below is only sound because one file runs
// in one worker. Do not split this file.
test('a backup created from the Backups panel produces a complete archive', async ({
  adminPage,
  api,
}) => {
  const listBackups = async (): Promise<BackupEntry[]> =>
    api.json<BackupEntry[]>(await api.get('/api/backups/'), 'list backups');

  const before = new Set((await listBackups()).map((b) => b.name));

  await adminPage.goto('/settings#backups');
  await expect(adminPage.getByTestId('backups-panel')).toBeVisible();

  await adminPage.getByRole('button', { name: /create backup|backup now|create/i }).click();

  // POST /api/backups/create/ returns 202 with a task_id; the archive is
  // written by a Celery task. Poll, never assume.
  let created: BackupEntry | undefined;
  await expect
    .poll(
      async () => {
        const fresh = (await listBackups()).filter((b) => !before.has(b.name));
        created = fresh[0];
        return fresh.length;
      },
      { timeout: 90_000, intervals: [1_000] }
    )
    .toBe(1);

  expect(created!.name).toMatch(/^dispatcharr-backup-.*\.zip$/);
  expect(created!.size, 'an empty archive is a failed backup').toBeGreaterThan(0);

  try {
    // Structural validation without a zip parser: a complete archive begins
    // with a local file header and ends with an end-of-central-directory
    // record. Together they prove it is a zip AND that it was not truncated —
    // which a size check alone does not.
    const tokenBody = await api.json<{ token: string }>(
      await api.get(`/api/backups/${encodeURIComponent(created!.name)}/download-token/`),
      'backup download token'
    );
    const download = await api.get(
      `/api/backups/${encodeURIComponent(created!.name)}/download/` +
        `?token=${encodeURIComponent(tokenBody.token)}`
    );
    expect(download.status()).toBe(200);

    const bytes = await download.body();
    expect(bytes.length).toBe(created!.size);
    expect(bytes.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
    expect(
      bytes.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06])),
      'no end-of-central-directory record: the archive is truncated'
    ).toBeGreaterThan(0);
  } finally {
    // Every archive is a full database dump, and the container outlives the
    // run by design. Leaving them fills /data/backups.
    await api.post(
      `/api/backups/${encodeURIComponent(created!.name)}/delete/`,
      {}
    );
  }
});
```

- [ ] **Step 2: Run it and confirm the endpoint shapes**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/backups.spec.ts
```

Confirm against `apps/backups/api_views.py`:

- the `download-token` response's field name (the code above assumes `token`);
- the delete endpoint's verb — `apps/backups/api_urls.py` routes
  `<filename>/delete/` to `delete_backup`; read its `@api_view` decorator and match it.

Replace the create-button alternation with the exact copy from `BackupManager.jsx`.

- [ ] **Step 3: Confirm the timeout is enough**

90s of polling inside a 120s test timeout is tight if the dump is slow on a cold CI runner.
Time one run:

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/backups.spec.ts --reporter=list
```

If the create routinely takes more than ~40s, either raise the project timeout (and say why in
the config comment) or reduce the poll budget — but do not remove the poll. A fixed
`waitForTimeout` here would be a flake generator.

- [ ] **Step 4: Commit**

```bash
git add e2e/tests/frontend/backups.spec.ts
git commit -m "test(e2e): a backup created from the UI produces a complete archive"
```

---

### Task 14: Stats — a live connection appears

Implements inventory row 7 and spec D11. The only G6 row that needs live data.

**Files:**
- Create: `e2e/tests/frontend/stats.spec.ts`

**Interfaces:**
- Consumes: `upstream`, `seed.upstreamChannel()`, `streamClient`, `stats-page`,
  `stats-connections`, and `lockedProfile` from the streaming helpers.

- [ ] **Step 1: Write the test**

Create `e2e/tests/frontend/stats.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import { lockedProfile } from '../streaming/helpers';

// The only G6 row that needs live data, and deliberately the only one: with no
// active connections the Stats page renders an empty grid, which proves
// nothing about the wiring. The upstream provider is already running in every
// CI matrix job (scripts/e2e_up.sh brings up both containers), so this costs
// nothing in topology — but it does mean this one spec needs the full local
// two-container setup, not a bare E2E_BASE_URL run. See e2e/README.md.
test('an active stream appears as a connection on the Stats page', async ({
  adminPage,
  api,
  seed,
  upstream,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G6 Stats', tvgId: 'g6-stats.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  // Read a little so the channel is genuinely serving before the page loads;
  // an opened-but-unread connection may not have registered yet.
  await streamClient.readPackets(100);

  await adminPage.goto('/stats');
  await expect(adminPage.getByTestId('stats-page')).toBeVisible();

  // Scoped to the connections grid, NOT the page: the page also renders a
  // fixed-position <SystemEvents> log at the bottom which prints the same
  // channel name, and an event-log line must not pass for a live connection.
  //
  // The generous timeout is the page's own poll interval (5s by default,
  // `stats-refresh-interval` in localStorage) plus room for the WebSocket
  // stats broadcast, on a CI runner.
  await expect(
    adminPage.getByTestId('stats-connections').getByText(channel.name)
  ).toBeVisible({ timeout: 60_000 });

  await streamClient.close();
});
```

- [ ] **Step 2: Run it**

```bash
cd e2e && npx playwright test --project=frontend tests/frontend/stats.spec.ts
```

- [ ] **Step 3: If the connection does not appear, check what the card actually renders**

The Stats page resolves a connection's display name by fetching channels by UUID
(`API.getChannelsByUUIDs`), so the card may show the channel name, or may show the UUID while
that fetch is in flight. If the name never appears, assert on `channel.uuid` inside
`stats-connections` instead and say why in a comment — the UUID is equally worker-scoped and
equally a backend-sourced value. Do **not** widen the scope to the whole page.

- [ ] **Step 4: Commit**

```bash
git add e2e/tests/frontend/stats.spec.ts
git commit -m "test(e2e): an active stream appears as a connection on the Stats page"
```

---

### Task 15: CI matrix, coverage inventory, documentation

The last task, and the only one that touches the workflow. Nothing before it may.

**Files:**
- Modify: `.github/workflows/e2e-tests.yml`, `e2e/COVERAGE.md`, `e2e/README.md`

- [ ] **Step 1: Add `frontend` to the CI matrix**

In `.github/workflows/e2e-tests.yml`, the `test` job's matrix:

```yaml
        project: [pristine, seeded, streaming, streaming-failover, streaming-greybox, frontend]
```

That is the whole edit. Each job already gets its own container from `scripts/e2e_up.sh`, which
already starts the upstream provider, so Task 14's dependency needs nothing more. **No
branch-protection change is required**: the single required check is the aggregating
`e2e-result` job, not the matrix entries.

- [ ] **Step 2: Verify zizmor is still clean**

```bash
zizmor --version
zizmor .github/workflows/e2e-tests.yml
```

Expected: zero findings. The hook blocks on **every** finding in an edited workflow, legacy
included, and the workflows are currently at zero. If the hook warns about a version drift
against `.github/workflows/actions-lint.yml`'s pin, bump both together — never one.

- [ ] **Step 3: Update `e2e/COVERAGE.md`**

Mark the nine G6 rows. Split the Backups row per spec D9:

```
| Frontend | Guide grid renders and navigates | G6 | done |
| Frontend | DVR: schedule, list, cancel a recording | G6 | done |
| Frontend | Users: create, edit, delete | G6 | done |
| Frontend | Settings: change and persist | G6 | done |
| Frontend | Plugins: list, enable, configure | G6 | done |
| Frontend | Stats page renders live data | G6 | done |
| Frontend | Connect: webhook CRUD | G6 | done |
| Frontend | Logos: upload and browse | G6 | done |
| Frontend | Backups: create and validate the archive | G6 | done |
| Lifecycle | Backups: restore — split out of G6's Backups row. Restoring on a shared instance replaces the database under every parallel worker mid-run and under every other project sharing the container locally, so it needs an instance of its own; G7 already stands one up per scenario | G7 | todo |
```

Then add the file list below the table, in the style of the existing G1/G2/G4 blocks:

```
The nine `done` G6 rows above are covered by these specs. The nine render
checks live in one file, generated from the surface table in
`e2e/tests/frontend/helpers.ts`; each surface's write or read proof is its own
file, and **that one-file-per-surface split is load-bearing** — the `frontend`
project runs two workers with file-level parallelism, which is what confines
backup creation and plugin installation to one worker each:

- `e2e/tests/frontend/render.spec.ts` — all nine surfaces mount, throw
  nothing, log no error and issue no request the server refuses
- `e2e/tests/frontend/guide.spec.ts` — Guide grid populated from the channel
  API, reached by clicking the sidebar
- `e2e/tests/frontend/dvr.spec.ts` — DVR schedule, list, cancel
- `e2e/tests/frontend/users.spec.ts` — Users create, edit, delete
- `e2e/tests/frontend/settings.spec.ts` — Settings change and persist, via a
  User-Agent row (a global `CoreSettings` change belongs to `pristine`)
- `e2e/tests/frontend/plugins.spec.ts` — Plugins import, enable, configure
- `e2e/tests/frontend/stats.spec.ts` — Stats renders a live connection
- `e2e/tests/frontend/connect.spec.ts` — Connect webhook CRUD
- `e2e/tests/frontend/logos.spec.ts` — Logos upload and browse
- `e2e/tests/frontend/backups.spec.ts` — Backups create and validate

Gap: the Guide row proves the grid is populated from
`/api/channels/channels/`, not from real EPG programme data. Asserting a
programme in the grid needs an ingested XMLTV source, which is G3's path;
recording a programme from the Guide needs the same. Deferred rather than
attempted here.
```

If Task 6 Step 3 or Task 11 Step 3 produced a `test.fixme()`, add its reason as a gap line on
that row too, and change its status from `done` to `todo`.

- [ ] **Step 4: Correct `e2e/README.md`'s stale CI section**

It currently reads "builds the AIO image once, then runs `pristine`, `seeded` and `streaming`
as a hardcoded three-job matrix (`e2e-tests.yml:49-50`)". Two things are wrong: the matrix has
had five entries since G4 and now has six, and the line-number citation is exactly what this
documentation series forbids. Replace with a count and a symbol reference:

**Expect a conflict on this paragraph.** G3 independently decided to correct it too (its D11),
so if G3 landed first the text will already read "five" rather than "three". **G6 is
authoritative here** — G6 is the goal that adds the sixth job, so G3's five is outdated the
moment this lands. Rebase through G3's version and rewrite the count to six; do not leave the
already-corrected paragraph alone as someone else's edit.

```
`.github/workflows/e2e-tests.yml` builds the AIO image once, then runs
`pristine`, `seeded`, `streaming`, `streaming-failover`, `streaming-greybox`
and `frontend` as a hardcoded six-job matrix (the `test` job's
`strategy.matrix.project`), each against its own fresh container, each gated on
`npm run typecheck` before tests run. **If you add a seventh project to
`playwright.config.ts`, add it to that matrix too** — nothing wires new
projects in automatically, and a project missing from the matrix gets no CI
coverage and no failure signal.
```

Confirm the two `frontend`-project paragraphs from Task 5 Step 9 are still present and read
correctly alongside it.

- [ ] **Step 5: Run the whole project one final time**

```bash
cd e2e && npm run typecheck && npx playwright test --project=frontend
```

Expected: 18 tests, all passing (or passing plus any expected-failures from Task 5 Step 8).
Run it twice back to back against the same container — the second run is what catches state a
test left behind: a plugin that was not deleted, a backup archive that accumulated, a user or
integration still present.

```bash
cd e2e && npx playwright test --project=frontend
```

Expected: identical result. A second run that fails where the first passed is a cleanup bug in
whichever spec left the residue; fix the spec, not the assertion.

- [ ] **Step 6: Confirm the other projects still pass**

The only shared files G6 touched are additive, but `e2e/fixtures/index.ts` is imported by every
spec in the suite:

```bash
cd e2e && npx playwright test --project=seeded
```

Expected: unchanged from `main`.

- [ ] **Step 7: Commit and open PR B**

```bash
git add .github/workflows/e2e-tests.yml e2e/COVERAGE.md e2e/README.md
git commit -m "test(e2e): wire the frontend project into CI and record the coverage"
git push -u origin feat/e2e-frontend-surfaces-g6
```

Open the PR **only once PR A has merged and this branch has been rebased onto `main`**:

```bash
git fetch origin && git rebase origin/main
gh pr create --repo D10Scot/Dispatcharr --base main \
  --title "test(e2e): frontend surfaces (G6) — 9 rows, 18 tests, 1 CI job" \
  --body "Implements docs/superpowers/specs/2026-08-29-e2e-frontend-surfaces-design.md.
Gated on feat/frontend-page-testids, which has merged.

Nine surfaces, each with a render check (no pageerror, no console.error, no
response >= 400 against a justified allowlist) and one write or read proof
driven through the UI and asserted through the api fixture — never a toast.

One new project, \`frontend\`: two workers, file-level parallelism, 120s. The
parallelism model is chosen from apps/backups/services.py, whose archive names
are second-granularity and caller-unnameable, so concurrent creates collide.
One spec file per surface is load-bearing, not tidiness.

Backup restore is handed to G7 with the reason recorded in COVERAGE.md."
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: D1/D1a → Tasks 1–2; D1b → the Global
Constraints and every spec's scoping; D2/D2a → Task 5 Step 3; D3 → Tasks 5 and 15; D4 → Task 4
and Task 5 Steps 6–8; D5 → Task 8; D6 → no `seed.ts` task, stated in Global Constraints; D7 →
Task 11; D8 → Task 12; D9 → Task 13 and Task 15 Step 3; D10 → Global Constraints; D11 → Task
14; D12 → Task 6; D13 → Task 5 Step 8 and Global Constraints; D14 → Global Constraints. The
nine PR A files are enumerated one per step in Task 1; the ten spec files one per task in Tasks
5–14. Both the `COVERAGE.md` and CI-matrix edits the spec calls out as easy to forget are
explicit steps in Task 15.

**Placeholder scan.** The plan contains no "TBD" or "similar to Task N". It does contain
deliberate regex alternations in locators (`/save|create|submit/i`) — these are **not**
placeholders but marked work: every task that uses one carries a step naming the source file
to read and requiring the alternation be replaced with the exact accessible name, with the
reason (an alternation that survives would silently match a different control if the copy
changed). The same applies to `EXPECTED_PAGE_NOISE`, which ships empty by design and is filled
in Task 5 Step 7 from observed behaviour, with a rule stating what may and may not go in it.

**Type consistency.** `PageErrorCollector`, `EXPECTED_PAGE_NOISE` and `PageNoiseEntry` are
defined in Task 4 and used with those exact names in Tasks 4–5 and the import map. `Surface`,
`SURFACES` and `gotoSurface` are defined in Task 5 and consumed in Task 5 only. `TINY_PNG` is
defined in Task 10 and used there. `buildPluginZip({ key, name })` is defined in Task 12 Step 3
and called with exactly that shape in Steps 1 and 5. The six entity types added in Task 4 Step
1 are each used in exactly the task that needs them: `UserAgent` (8), `ConnectIntegration` (9),
`Recording` (11), `Logo` (10), `PluginListEntry` (12), `BackupEntry` (13). The eleven test ids
from Task 1 match `SURFACES` in Task 5 and every `getByTestId` call downstream.
