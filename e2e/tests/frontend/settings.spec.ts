import { test, expect } from '../../fixtures';
import type { ApiClient, UserAgent } from '../../fixtures';
import { listRows } from '../../setup/http';
import { SURFACES, gotoSurface } from './helpers';

const settingsSurface = SURFACES.find((s) => s.name === 'Settings');
if (!settingsSurface) {
  throw new Error('settings.spec.ts: no "Settings" entry in SURFACES — check helpers.ts');
}

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

// The row to clean up, by the generated name this test used — never a
// remembered id. Module-level, not test-body state, and assigned the moment
// the name is generated (see the test body below) rather than derived from
// anything that could itself fail first.
//
// Why this lives outside the test body, and why in `afterEach` rather than a
// body-level `try`/`finally` (this file's own shape until this round): a
// `finally` runs on a normal throw, but Playwright does not raise a normal
// exception when a test exceeds its timeout — it tears the test function
// down mid-`await`, and code written after that `await`, `finally` block
// included, does not reliably run. `afterEach` hooks are Playwright's own
// fixture-teardown machinery, run on their own budget regardless of how the
// test body ended, including a forced timeout — the same reasoning
// `plugins.spec.ts`'s `afterEach` documents, and the shape this file now
// matches. The `api` fixture used below wraps an `APIRequestContext`,
// independent of `page`, so it still works after a page-side timeout.
//
// This module-level binding is safe only because the `frontend` project's
// block in playwright.config.ts leaves `fullyParallel` unset, and its own
// comment there says so deliberately — it inherits Playwright's default of
// `false`, not a project-level override, so tests within one file never run
// concurrently and one test's write here can never be read by another
// test's `afterEach`. A module-level binding under `fullyParallel: true`
// would be a cross-test race; this file relies on that inherited default
// holding, not on it happening to be pinned some other way.
let nameToCleanup: string | undefined;

async function findUserAgent(api: ApiClient, name: string): Promise<UserAgent | undefined> {
  return listRows<UserAgent>(
    await api.json<unknown>(await api.get('/api/core/useragents/'), 'list user agents')
  ).find((ua) => ua.name === name);
}

test.afterEach(async ({ api }, testInfo) => {
  if (!nameToCleanup) return;
  const name = nameToCleanup;
  nameToCleanup = undefined;

  try {
    const leftover = await findUserAgent(api, name);
    if (leftover) {
      const cleanup = await api.delete(`/api/core/useragents/${leftover.id}/`);
      if (cleanup.status() !== 204) {
        throw new Error(`user-agent cleanup failed: DELETE returned ${cleanup.status()}`);
      }
    }
  } catch (cleanupError) {
    // Same non-masking shape plugins.spec.ts/backups.spec.ts/users.spec.ts
    // settled on: if the test itself already failed, a cleanup failure on
    // top of it must not replace that failure as the reported cause — log
    // it and stop. Only let a cleanup failure fail the test when the test
    // body otherwise passed.
    if (testInfo.status !== 'passed') {
      console.error(
        'settings.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

test('a User-Agent created from Settings is stored server-side and survives a reload', async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  const name = seed.generatedName('userAgent');
  // Assigned immediately, before any further `await` that can throw — the
  // only point between here and a mid-flow timeout where a plain assignment
  // (rather than a step that can itself throw) is guaranteed to run. See
  // `nameToCleanup`'s own comment above.
  nameToCleanup = name;

  const find = async (): Promise<UserAgent | undefined> => findUserAgent(api, name);

  // `page.goto('/settings#user-agents')` cannot reach this surface on a
  // fresh load (#58) — gotoSurface clicks through the sidebar instead. See
  // its own doc comment.
  await gotoSurface(adminPage, settingsSurface);

  // Roles and labels, confirmed against `UserAgentsTable.jsx`/`UserAgent.jsx`
  // directly rather than guessed: the add button reads "Add User-Agent",
  // the two text fields are labelled exactly "Name" and "User-Agent" (no
  // "User-Agent Name" ambiguity — but a real one anyway: Mantine's
  // `<Modal title="User-Agent">` wires `aria-labelledby` from its title
  // onto the whole dialog `<section>`, which also has accessible name
  // "User-Agent" — so `getByLabel('User-Agent')` is a strict-mode
  // violation between that section and the actual input (confirmed by
  // running this test and reading the failure, not guessed in advance).
  // `getByRole('textbox', …)` only matches form controls, so it sidesteps
  // the collision), and the submit control reads "Submit", not
  // "Save"/"Create".
  await adminPage.getByRole('button', { name: 'Add User-Agent', exact: true }).click();
  await adminPage.getByRole('textbox', { name: 'Name', exact: true }).fill(name);
  await adminPage
    .getByRole('textbox', { name: 'User-Agent', exact: true })
    .fill('Dispatcharr-E2E/1.0');
  await adminPage.getByRole('button', { name: 'Submit', exact: true }).click();

  // The assertion is the server's state, not a toast (rule 6). Captured
  // from inside the poll itself rather than re-calling `find()` afterward
  // — `expect.poll` already re-invokes the callback on every attempt, so a
  // second, separate call after it settles would be a redundant extra
  // round trip to read the same field.
  let created: UserAgent | undefined;
  await expect
    .poll(
      async () => {
        created = await find();
        return created;
      },
      { timeout: 30_000 }
    )
    .toBeDefined();
  expect(created!.user_agent).toBe('Dispatcharr-E2E/1.0');

  // The "persist" half. The store this row lives in client-side
  // (`store/userAgents.jsx`) has no `persist` middleware and is populated
  // only via `fetchUserAgents()`, called from `store/auth.jsx` during
  // sign-in initialization — never from `UserAgentsTable` itself — so a
  // row still visible after the client memory holding it is wiped can only
  // have been re-fetched from the server.
  //
  // `gotoSurface`'s own first act is `page.goto('/channels')`
  // (`helpers.ts`) — itself a fresh full document load, which already
  // wipes the store — so a separate, explicit `adminPage.reload()` before
  // it would add nothing beyond what that navigation already does; doing
  // so was tried and confirmed redundant. What *doesn't* work is a bare
  // `reload()` (or any other fresh full-page load) followed by asserting
  // `settings-page` directly with no further navigation: that lands on
  // `/channels` (the hardcoded catch-all default), not back on
  // `/settings#user-agents`, because `App.jsx`'s catch-all `<Navigate
  // replace>` fires before `isInitialized` resolves on *every* fresh page
  // load, reload included — the same #58 race `gotoSurface`'s own doc
  // comment describes for an initial navigation, confirmed empirically
  // here too. Not a new defect, not re-filed; `gotoSurface` is already the
  // workaround this goal uses for it everywhere else, including here.
  await gotoSurface(adminPage, settingsSurface);
  await expect(adminPage.getByTestId('settings-page').getByText(name)).toBeVisible({
    timeout: 30_000,
  });

  await pageErrors.expectClean();
});
