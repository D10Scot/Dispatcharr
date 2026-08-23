import { test, expect } from '@playwright/test';

// Exemplar: the seeded project's storageState authenticates without ever
// touching the login form. If this fails, bootstrap wrote the wrong keys.
test('seeded project lands authenticated on /channels', async ({ page }) => {
  await page.goto('/channels');

  await expect(page).toHaveURL(/\/channels/);
  await expect(page.getByText('Please log in to continue.')).toHaveCount(0);

  // Positive assertion: an element that only exists inside the authenticated
  // app. The negative check above also passes before the SPA has rendered
  // anything at all, so on its own it can't tell "authenticated" from
  // "broken and blank" — the worst failure mode for the harness's own smoke
  // test. exact: true — the streams panel also has a disabled
  // "Create Channel (0)" button, which would otherwise make this ambiguous.
  await expect(
    page.getByRole('button', { name: 'Create Channel', exact: true })
  ).toBeVisible();
});
