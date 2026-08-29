import { test, expect } from '../../fixtures';
import type { UserAgent } from '../../fixtures';
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
test('a User-Agent created from Settings is stored server-side and survives a reload', async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  const name = seed.generatedName('userAgent');

  const find = async (): Promise<UserAgent | undefined> =>
    listRows<UserAgent>(
      await api.json<unknown>(await api.get('/api/core/useragents/'), 'list user agents')
    ).find((ua) => ua.name === name);

  try {
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
  } finally {
    const leftover = await find();
    if (leftover) {
      const cleanup = await api.delete(`/api/core/useragents/${leftover.id}/`);
      expect(cleanup.status()).toBe(204);
    }
  }
});
