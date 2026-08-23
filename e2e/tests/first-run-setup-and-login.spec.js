import { test, expect } from '@playwright/test';

// Exercises Dispatcharr's very first user-facing flow end to end, against a
// real backend: on a fresh instance there is no superuser yet, so the app
// serves the setup form instead of login. This is the one flow every
// deployment goes through exactly once, and it's fully self-contained (no
// M3U/EPG/stream data needed), which makes it a good first E2E test.
const USERNAME = 'e2e-admin';
const PASSWORD = 'Correct-Horse-Battery-Staple-42!';
const EMAIL = 'e2e-admin@example.com';

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
