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

    // The assertion is the server's state, not a toast (rule 6).
    await expect.poll(find, { timeout: 30_000 }).toBeDefined();
    expect((await find())!.user_agent).toBe('Dispatcharr-E2E/1.0');

    // The "persist" half. A reload discards every Zustand store (confirmed:
    // `store/userAgents.jsx` has no `persist` middleware, and its data is
    // populated only via `fetchUserAgents()`, called from `store/auth.jsx`
    // during sign-in initialization — never from `UserAgentsTable` itself),
    // so a row still visible afterwards was re-fetched from the server, not
    // remembered client-side.
    //
    // `adminPage.reload()` is itself a fresh full page load, so it lands in
    // exactly the same race `gotoSurface`'s own doc comment describes for
    // #58: confirmed empirically — with a bare `reload()` +
    // `getByTestId('settings-page')`, the run above landed on `/channels`
    // (the hardcoded catch-all default), not back on
    // `/settings#user-agents`, because the catch-all's `<Navigate replace>`
    // fires before `isInitialized` resolves and destroys the URL the reload
    // asked for. This is the same defect, not a new one — #58 is filed and
    // is not re-filed here. The workaround is the same one `gotoSurface`
    // already applies to every other surface: after the reload has done its
    // job of wiping client memory, drive back to the section through the
    // sidebar rather than trusting the URL to survive the reload by itself.
    await adminPage.reload();
    await gotoSurface(adminPage, settingsSurface);
    await expect(adminPage.getByTestId('settings-page').getByText(name)).toBeVisible({
      timeout: 30_000,
    });
  } finally {
    const leftover = await find();
    if (leftover) {
      const cleanup = await api.delete(`/api/core/useragents/${leftover.id}/`);
      expect(cleanup.status()).toBe(204);
    }
  }
});
