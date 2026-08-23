import { test, expect } from '../../fixtures';

// Exemplar: the seeded project's storageState authenticates without ever
// touching the login form. If this fails, bootstrap wrote the wrong keys.
//
// `adminPage`, not `page`: the two are the same object in this project, but
// naming the principal is the habit the harness wants, and importing from
// '../../fixtures' is the rule (README, "Writing a test"). Typecheck only
// catches a raw '@playwright/test' import when the spec destructures a custom
// fixture — a spec using `page` alone, as this one used to, slips through.
test('seeded project lands authenticated on /channels', async ({ adminPage }) => {
  await adminPage.goto('/channels');

  await expect(adminPage).toHaveURL(/\/channels/);
  await expect(adminPage.getByText('Please log in to continue.')).toHaveCount(0);

  // Positive assertion: an element that only exists inside the authenticated
  // app. The negative check above also passes before the SPA has rendered
  // anything at all, so on its own it can't tell "authenticated" from
  // "broken and blank" — the worst failure mode for the harness's own smoke
  // test. The sidebar's notification bell (NotificationCenter.jsx,
  // aria-label="Notifications") is rendered only when `isAuthenticated`,
  // identically whether the sidebar is expanded or collapsed — unlike the
  // nav labels and the "Create Channel" onboarding button used previously,
  // neither of which is safe here: nav/username labels are hidden behind a
  // hover-only tooltip when the sidebar is collapsed, and "Create Channel"
  // is the empty-state prompt, which never renders once the shared instance
  // (this project's `seeded` container) has any channels — exactly the case
  // this suite's own seeding produces.
  await expect(
    adminPage.getByRole('button', { name: 'Notifications' })
  ).toBeVisible();
});
