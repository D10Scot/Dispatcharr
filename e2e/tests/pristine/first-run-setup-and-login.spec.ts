// Importing from '@playwright/test' rather than '../../fixtures' is
// deliberate here, and is not licence to do it elsewhere: the pristine
// project has no `bootstrap` dependency and no auth state, so none of the
// custom fixtures (`api`, `seed`, `ws`, …) can be constructed — they all
// need the admin tokens this test is in the middle of creating. Every spec
// outside tests/pristine/ imports from '../../fixtures'. See README,
// "Writing a test".
import { test, expect } from '@playwright/test';
import { ADMIN } from '../../setup/credentials';

// Exercises Dispatcharr's very first user-facing flow end to end, against a
// real backend: on a fresh instance there is no superuser yet, so the app
// serves the setup form instead of login. This is the one flow every
// deployment goes through exactly once, and it's fully self-contained (no
// M3U/EPG/stream data needed), which makes it a good first E2E test.
//
// The credentials come from setup/credentials.ts, the same module
// bootstrap.setup.ts uses. Declaring them here too would let the two drift,
// and this test is what decides which admin the container ends up with:
// pristine and bootstrap create *the same* account on their two containers,
// and a divergence would show up much later as a mystery 401.
const { username: USERNAME, password: PASSWORD, email: EMAIL } = ADMIN;

test('first run: create the superuser, log in, land on Channels', async ({
  page,
}) => {
  await page.goto('/');

  // Fresh instance: no superuser exists yet, so the setup form is served.
  await expect(
    page.getByText('Create your Super User Account to get started.')
  ).toBeVisible();

  await page.getByLabel('Username').fill(USERNAME);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByLabel('Email (optional)').fill(EMAIL);
  await page.getByRole('button', { name: 'Create Account' }).click();

  // Superuser now exists: the same page switches to the login form.
  await expect(
    page.getByText('Welcome back! Please log in to continue.')
  ).toBeVisible();

  await page.getByLabel('Username').fill(USERNAME);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Login' }).click();

  // A successful login redirects to the default authenticated route.
  await expect(page).toHaveURL(/\/channels/);

  // Fresh install, zero channels: the onboarding empty-state confirms we're
  // genuinely inside the authenticated app, not just past the URL redirect.
  // exact: true — the streams panel also has a disabled "Create Channel (0)"
  // button, which would otherwise make this locator ambiguous.
  await expect(
    page.getByRole('button', { name: 'Create Channel', exact: true })
  ).toBeVisible();
});
