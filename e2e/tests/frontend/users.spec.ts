import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';
import type { User } from '../../fixtures';
import { listRows } from '../../setup/http';
import { SURFACES, gotoSurface } from './helpers';

const usersSurface = SURFACES.find((s) => s.name === 'Users');
if (!usersSurface) {
  throw new Error('users.spec.ts: no "Users" entry in SURFACES — check helpers.ts');
}

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
  pageErrors,
}) => {
  const username = seed.generatedName('user');

  // Failure-path cleanup: if anything below throws, this still runs and
  // deletes the row directly through the API — looked up by the generated
  // username rather than a remembered id, so it works no matter how far the
  // UI flow got before failing. An aborted run between the level-raise (a
  // few lines down) and the UI delete step would otherwise orphan a working
  // login with the publicly-known SEEDED_USER_PASSWORD on the shared
  // instance, indefinitely — worse than ordinary residue. On the normal
  // (passing) path `findUser` finds nothing here, since the test's own UI
  // delete already removed the row, and the `if` below is skipped entirely.
  try {
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
    // worst case for a leaked row (see the `try`/`finally` above) as low
    // privilege as this UI allows a created-with-a-password account to reach.
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
  } finally {
    // See the comment at the top of this test. Deletes via the API and
    // asserts the response — an earlier task in this goal shipped a
    // `finally` that POSTed to a DELETE-only endpoint and discarded the
    // result, so cleanup failed silently and left exactly the residue the
    // task forbade. A teardown whose failure is invisible is worse than
    // none.
    const leftover = await findUser(api, username);
    if (leftover) {
      const cleanup = await api.delete(`/api/accounts/users/${leftover.id}/`);
      expect(cleanup.status()).toBe(204);
    }
  }
});
