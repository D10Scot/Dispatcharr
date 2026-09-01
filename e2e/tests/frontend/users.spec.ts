import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';
import type { ApiClient, User } from '../../fixtures';
import { listRows } from '../../setup/http';
import { SURFACES, gotoSurface } from './helpers';

const usersSurface = SURFACES.find((s) => s.name === 'Users');
if (!usersSurface) {
  throw new Error('users.spec.ts: no "Users" entry in SURFACES — check helpers.ts');
}

/**
 * The row this test created, by the name it generated. Never a count.
 * Typed against the real `ApiClient` (not an inline structural stand-in) so
 * a future signature drift on the fixture is caught by `npm run typecheck`
 * here, not silently ignored — the convention `connect.spec.ts`, `logos.spec.ts`
 * and `plugins.spec.ts` all settled on; this file was written before it and
 * is the last one converted.
 */
async function findUser(api: ApiClient, username: string): Promise<User | undefined> {
  const body = await api.json<unknown>(
    await api.get('/api/accounts/users/'),
    'list users'
  );
  return listRows<User>(body).find((u) => u.username === username);
}

// The row to clean up, by the generated username this test used — never a
// remembered id. Module-level, not test-body state, and assigned the moment
// the username is generated (see the test body below) rather than derived
// from anything that could itself fail first.
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
//
// Why leaving a row behind here is worse than ordinary residue: an aborted
// run between the level-raise (a few lines down) and the UI delete step
// would otherwise orphan a working login carrying the publicly-known
// `SEEDED_USER_PASSWORD` on the shared instance, indefinitely.
let usernameToCleanup: string | undefined;

test.afterEach(async ({ api }, testInfo) => {
  if (!usernameToCleanup) return;
  const username = usernameToCleanup;
  usernameToCleanup = undefined;

  // On the normal (passing) path this lookup finds nothing — the test's own
  // UI delete already removed the row — and the block below is skipped
  // entirely. That "found nothing, did nothing" outcome is not a change from
  // this file's previous `finally`: it ran unconditionally too, on both the
  // passing and failing paths, and this preserves that rather than assuming
  // a passing body means there is nothing left to check.
  try {
    const leftover = await findUser(api, username);
    if (leftover) {
      const cleanup = await api.delete(`/api/accounts/users/${leftover.id}/`);
      if (cleanup.status() !== 204) {
        throw new Error(`user cleanup failed: DELETE returned ${cleanup.status()}`);
      }
    }
  } catch (cleanupError) {
    // Same non-masking shape plugins.spec.ts/backups.spec.ts settled on: if
    // the test itself already failed, a cleanup failure on top of it must
    // not replace that failure as the reported cause — log it and stop.
    // Only let a cleanup failure fail the test when the test body otherwise
    // passed. (An earlier version of this file's `finally` block let a POST
    // to a DELETE-only endpoint fail silently, discarding the result — a
    // teardown whose failure is invisible is worse than none; this shape
    // keeps that lesson without reintroducing the masking it also caused.)
    if (testInfo.status !== 'passed') {
      console.error(
        'users.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

test('a user created through the Users page exists on the server, and survives edit and delete', { tag: '@contract' }, async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  const username = seed.generatedName('user');
  // Assigned immediately, before any further `await` that can throw — the
  // only point between here and a mid-flow timeout where a plain assignment
  // (rather than a step that can itself throw) is guaranteed to run. See
  // `usernameToCleanup`'s own comment above.
  usernameToCleanup = username;

  // `page.goto('/users')` cannot reach this surface on a fresh load (#58) —
  // gotoSurface is the sidebar-click workaround every other spec in this
  // project uses. See its own doc comment.
  await gotoSurface(adminPage, usersSurface);

  // Roles and labels, not test ids: every control here has an accessible
  // name, confirmed by reading `UsersTable.jsx`/`User.jsx` directly rather
  // than guessing.
  await adminPage.getByRole('button', { name: 'Add User', exact: true }).click();
  await adminPage.getByLabel('Username').fill(username);

  // `PasswordInput`'s `disabled` prop (`User.jsx:221`) is bound to
  // `form.getValues().user_level == USER_LEVELS.STREAMER`, and
  // `getFormInitialValues()` (`UserUtils.js`) defaults a brand-new user to
  // `user_level: '0'` (Streamer) — so the Password field starts disabled
  // and a `.fill()` on it would hang until the actionability timeout. The
  // "User Level" control lives on the Permissions tab (only visible to an
  // admin creating someone other than themselves, which this always is),
  // so this test raises the level to Standard *before* filling the
  // password, not only in the later edit step the brief describes. The
  // edit step below then lowers Standard back down to Streamer rather than
  // raising it further — proving the same control works while keeping the
  // worst case for a leaked row (see `usernameToCleanup`'s comment above)
  // as low privilege as this UI allows a created-with-a-password account to
  // reach.
  await adminPage.getByRole('tab', { name: 'Permissions', exact: true }).click();
  await adminPage.getByRole('textbox', { name: 'User Level' }).click();
  await adminPage.getByRole('option', { name: 'Standard User', exact: true }).click();

  await adminPage.getByRole('tab', { name: 'Account', exact: true }).click();
  await adminPage.getByLabel('Password', { exact: true }).fill(SEEDED_USER_PASSWORD);
  await adminPage.getByRole('button', { name: 'Save', exact: true }).click();

  // The assertion is the server's state, not a toast. `api.js`'s
  // errorNotification toasts AND rethrows, so a red toast and a green
  // toast are equally consistent with a write that never left the
  // browser.
  await expect.poll(() => findUser(api, username), { timeout: 30_000 }).toBeDefined();
  const created = (await findUser(api, username))!;
  expect(created.user_level).toBe(1); // Standard, set during creation above.

  // `CustomTable` renders `<div class="tr">` rows, not a real `<table>`
  // (confirmed by reading `CustomTable.jsx`/`CustomTableBody.jsx`) — so
  // `getByRole('row', …)` can never resolve here. The generated username
  // makes a page-wide scope unambiguous instead. `UserRowActions`'
  // edit/delete `ActionIcon`s (`UsersTable.jsx:90-111`) are icon-only with
  // no `aria-label`/`title`, so they carry no accessible name at all — a
  // `getByRole('button', { name: /edit/i })` matches nothing, on any row.
  // Filed as #65 (SC 4.1.2 Level A — no accessible name by any route is a
  // defect regardless of what a test locator can work around, unlike an
  // `<img alt>` case such as Task 6's, which *is* the sanctioned text
  // alternative). Scoping to the row via the generated username and
  // picking the action buttons by their fixed left-to-right order (edit,
  // then delete — `UserRowActions`'s `<Group>` renders them in that
  // literal order) is the narrowest workaround that doesn't touch
  // `frontend/`. Safe by construction, not just by ordering: both clicks
  // are scoped to `row`, so no index error can reach another user's row;
  // `enableRowSelection`/pagination/virtualisation are all off
  // (`UsersTable.jsx:352-354`), so there is no checkbox column and no
  // partial render; the only other button a row can carry is
  // `XCPasswordCell`'s eye toggle, which renders only when `xc_password`
  // is truthy and never for a form-created user; and any reordering
  // degrades to a timeout rather than a wrong click, because the next step
  // is modal-scoped and `User.jsx` has no Delete button to mis-hit.
  const usersPage = adminPage.getByTestId('users-page');
  const row = usersPage.locator('.tr', { hasText: username });
  await expect(row).toBeVisible();

  // Edit: lower the level back down (Standard -> Streamer) through the UI
  // and re-read from the server.
  await row.locator('button').nth(0).click();
  await adminPage.getByRole('tab', { name: 'Permissions', exact: true }).click();
  await adminPage.getByRole('textbox', { name: 'User Level' }).click();
  await adminPage.getByRole('option', { name: 'Streamer', exact: true }).click();
  await adminPage.getByRole('button', { name: 'Save', exact: true }).click();

  await expect
    .poll(async () => (await findUser(api, username))?.user_level, { timeout: 30_000 })
    .toBe(0);

  // Delete, and prove absence from the server rather than from the table.
  await row.locator('button').nth(1).click();

  // `ConfirmationDialog`'s message (`UsersTable.jsx:463-476`) interpolates
  // `userToDelete.username` — asserting it here turns the `.nth(1)`
  // ordering above from inference into proof: if the wrong row's delete
  // button had been clicked, this would show a different username and
  // fail before anything destructive happens.
  await expect(adminPage.getByText(`Username: ${username}`)).toBeVisible();
  await adminPage.getByRole('button', { name: 'Delete', exact: true }).click();

  await expect.poll(() => findUser(api, username), { timeout: 30_000 }).toBeUndefined();

  // And directly, so a list-shape change cannot make absence look like
  // success.
  const gone = await api.get(`/api/accounts/users/${created.id}/`);
  expect(gone.status()).toBe(404);

  await pageErrors.expectClean();
});
