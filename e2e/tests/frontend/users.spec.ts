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
  // `user_level: '0'` (Streamer) — so the Password field starts disabled and
  // a `.fill()` on it would hang until the actionability timeout. The
  // "User Level" control lives on the Permissions tab (only visible to an
  // admin creating someone other than themselves, which this always is), so
  // this test raises the level to Standard *before* filling the password,
  // not only in the later edit step the brief describes. That still leaves
  // "edit" doing real work below: it raises Standard back to Admin, not
  // Streamer to Standard, and the mutation check (see below) proves it.
  await adminPage.getByRole('tab', { name: 'Permissions', exact: true }).click();
  await adminPage.getByRole('textbox', { name: 'User Level' }).click();
  await adminPage.getByRole('option', { name: 'Standard User', exact: true }).click();

  await adminPage.getByRole('tab', { name: 'Account', exact: true }).click();
  await adminPage.getByLabel('Password', { exact: true }).fill(SEEDED_USER_PASSWORD);
  await adminPage.getByRole('button', { name: 'Save', exact: true }).click();

  // The assertion is the server's state, not a toast. `api.js`'s
  // errorNotification toasts AND rethrows, so a red toast and a green toast
  // are equally consistent with a write that never left the browser.
  await expect.poll(() => findUser(api, username), { timeout: 30_000 }).toBeDefined();
  const created = (await findUser(api, username))!;
  expect(created.user_level).toBe(1); // Standard, set during creation above.

  // `CustomTable` renders `<div class="tr">` rows, not a real `<table>`
  // (confirmed by reading `CustomTable.jsx`/`CustomTableBody.jsx`) — so
  // `getByRole('row', …)` can never resolve here. The generated username
  // makes a page-wide scope unambiguous instead. `UserRowActions`'
  // edit/delete `ActionIcon`s (`UsersTable.jsx:88-113`) are icon-only with no
  // `aria-label`/`title`, so they carry no accessible name at all — a
  // `getByRole('button', { name: /edit/i })` matches nothing, on any row.
  // That's a real gap (worth an accessibility issue on its own), but it
  // isn't a defect in the create/edit/delete flow this test is proving, so
  // it isn't filed here — same call Task 6 made for Guide's name-only-in-alt
  // rendering. Scoping to the row via the generated username and picking the
  // action buttons by their fixed left-to-right order (edit, then delete —
  // `UserRowActions`' `<Group>` renders them in that literal order) is the
  // narrowest workaround that doesn't touch `frontend/`.
  const usersPage = adminPage.getByTestId('users-page');
  const row = usersPage.locator('.tr', { hasText: username });
  await expect(row).toBeVisible();

  // Edit: raise the level again (Standard -> Admin) through the UI and
  // re-read from the server.
  await row.locator('button').nth(0).click();
  await adminPage.getByRole('tab', { name: 'Permissions', exact: true }).click();
  await adminPage.getByRole('textbox', { name: 'User Level' }).click();
  await adminPage.getByRole('option', { name: 'Admin', exact: true }).click();
  await adminPage.getByRole('button', { name: 'Save', exact: true }).click();

  await expect
    .poll(async () => (await findUser(api, username))?.user_level, { timeout: 30_000 })
    .toBe(10);

  // Delete, and prove absence from the server rather than from the table.
  await row.locator('button').nth(1).click();
  await adminPage.getByRole('button', { name: 'Delete', exact: true }).click();

  await expect.poll(() => findUser(api, username), { timeout: 30_000 }).toBeUndefined();

  // And directly, so a list-shape change cannot make absence look like success.
  const gone = await api.get(`/api/accounts/users/${created.id}/`);
  expect(gone.status()).toBe(404);

  await pageErrors.expectClean();
});
