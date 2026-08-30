import { test, expect } from '../../fixtures';
import type { ApiClient, ConnectIntegration } from '../../fixtures';
import { listRows } from '../../setup/http';
import { SURFACES, gotoSurface } from './helpers';

const connectSurface = SURFACES.find((s) => s.name === 'Connect');
if (!connectSurface) {
  throw new Error('connect.spec.ts: no "Connect" entry in SURFACES — check helpers.ts');
}

const WEBHOOK_URL = 'http://e2e-upstream:9402/does-not-matter';

/**
 * The row this test created, by the name it generated. Never a count.
 * Typed against the real `ApiClient` (not an inline structural stand-in) so
 * a future signature drift on the fixture is caught by `npm run typecheck`
 * here, not silently ignored.
 */
async function findIntegration(
  api: ApiClient,
  name: string
): Promise<ConnectIntegration | undefined> {
  const body = await api.json<unknown>(
    await api.get('/api/connect/integrations/'),
    'list connect integrations'
  );
  return listRows<ConnectIntegration>(body).find((i) => i.name === name);
}

// The row to clean up, by the generated name this test used — never a
// remembered id. Module-level, not test-body state, and assigned the moment
// the name is generated (see the test body below), before any further await
// that can throw.
//
// Why this lives outside the test body, and why in `afterEach` rather than a
// body-level `try`/`catch`/rethrow (this file's own shape until this round,
// shared with dvr.spec.ts and logos.spec.ts): a `catch` runs on a normal
// throw, but Playwright does not raise a normal exception when a test
// exceeds its timeout — it tears the test function down mid-`await`, and
// code written after that `await`, the `catch` block and everything below it
// included, does not reliably run. `afterEach` hooks are Playwright's own
// fixture-teardown machinery, run on their own budget regardless of how the
// test body ended, including a forced timeout — the same reasoning
// `plugins.spec.ts`'s `afterEach` documents, and the shape this file now
// matches. The `api` fixture used below is an `ApiClient`, wrapping an
// `APIRequestContext` independent of `page`, so it still works after a
// page-side timeout.
//
// This module-level binding is safe only because the `frontend` project pins
// `fullyParallel: false` (playwright.config.ts) — tests within one file
// never run concurrently, so one test's write here can never be read by
// another test's `afterEach`. A module-level binding under `fullyParallel:
// true` would be a cross-test race; this file relies on the pinned setting,
// not on it happening to be the default.
let nameToCleanup: string | undefined;

test.afterEach(async ({ api }, testInfo) => {
  if (!nameToCleanup) return;
  const name = nameToCleanup;
  nameToCleanup = undefined;

  try {
    const leftover = await findIntegration(api, name);
    if (leftover) {
      const cleanup = await api.delete(`/api/connect/integrations/${leftover.id}/`);
      if (cleanup.status() !== 204) {
        throw new Error(`integration cleanup failed: DELETE returned ${cleanup.status()}`);
      }
    }
  } catch (cleanupError) {
    // Same non-masking shape plugins.spec.ts/backups.spec.ts settled on: if
    // the test itself already failed, a cleanup failure on top of it must
    // not replace that failure as the reported cause — log it and stop.
    // Only let a cleanup failure fail the test when the test body otherwise
    // passed. (An earlier version of this file's cleanup gave the delete
    // failure different treatment from the lookup failure — never swallowing
    // it, even on an already-failed test, on the reasoning that a leaked row
    // on the shared instance matters regardless of cause. That asymmetry is
    // gone in this shape: it had the same masking risk it was trying to
    // avoid — an unconditional throw here would silently replace a real
    // test failure already in flight with this cleanup failure instead,
    // exactly the outcome the lookup-failure half of the old code was
    // written to prevent. Uniform non-masking treatment for the whole
    // cleanup step is what plugins.spec.ts and backups.spec.ts already do.)
    if (testInfo.status !== 'passed') {
      console.error(
        'connect.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

// The Connect form's fields are labelled `Name`, `Connection Type`,
// `Webhook URL` and `Script Path` (frontend/src/components/forms/Connection.jsx),
// so this whole flow is driven by label and role. The only test id it uses
// scopes the assertion to the integration grid — the page also renders a
// fixed-position <ConnectLogsSection> that prints integration names, and a log
// line must not pass for a card.
//
// This test deliberately enables one event trigger (`Channel Started`,
// SUBSCRIPTION_EVENTS.channel_start in frontend/src/constants.js) rather than
// leaving Event Triggers untouched, for two reasons: an integration with no
// live trigger is not a realistic webhook, and it is what surfaces #62 (see
// below) — the very case the brief's literal flow, which never opens that
// tab, cannot exercise.
test('a webhook integration created through the Connect page round-trips to the server, toggles and deletes', async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  const name = seed.generatedName('integration');
  // Assigned immediately, before any further `await` that can throw — the
  // only point between here and a mid-flow timeout where a plain assignment
  // (rather than a step that can itself throw) is guaranteed to run. See
  // `nameToCleanup`'s own comment above.
  nameToCleanup = name;

  // `page.goto('/connect')` cannot reach this surface on a fresh load
  // (#58) — gotoSurface is the sidebar-click workaround every spec in this
  // project uses.
  await gotoSurface(adminPage, connectSurface);

  await adminPage.getByRole('button', { name: 'New Connection', exact: true }).click();
  await adminPage.getByLabel('Name').fill(name);

  // `getByLabel('Connection Type')` is a strict-mode violation — the
  // Mantine `Select`'s options listbox also carries `aria-labelledby`
  // back to the same label, so it resolves both the input and the
  // (initially hidden) listbox div. Same class of collision Task 8 found
  // on the Settings modal title; scoping to `getByRole('textbox', …)`
  // only matches the form control.
  const typeField = adminPage.getByRole('textbox', { name: 'Connection Type' });

  // "Webhook" is already the form's default, so clicking straight to it
  // would re-select the option that is already selected. Mantine's
  // `Select` defaults `allowDeselect` to `true`: clicking an
  // already-selected option *clears* the field instead of reaffirming it
  // (confirmed empirically — re-running the brief's literal single-click
  // flow left `type` as `''`, which then hid the "Webhook URL" field
  // behind the else-branch "Script Path" field and hung the next `.fill()`
  // for the full test timeout). Not filed: the form's own `isNotEmpty`
  // validator on `type` would reject a genuinely empty submission, so
  // nothing is silently corrupted — this is Mantine's documented default
  // behaviour, not a Connect-specific defect, and a real user has no
  // reason to click an option that already shows as selected. Worked
  // around, and turned into a real assertion, by making an actual
  // transition: Webhook -> Custom Script -> Webhook, checking the
  // type-dependent field swaps each time.
  await typeField.click();
  await adminPage.getByRole('option', { name: 'Custom Script', exact: true }).click();
  await expect(adminPage.getByLabel('Script Path')).toBeVisible();

  await typeField.click();
  await adminPage.getByRole('option', { name: 'Webhook', exact: true }).click();
  await adminPage.getByLabel('Webhook URL').fill(WEBHOOK_URL);

  await adminPage.getByRole('tab', { name: 'Event Triggers', exact: true }).click();
  await adminPage
    .getByRole('checkbox', { name: 'Channel Started', exact: true })
    .check();

  // The submit button's real label is "Save" — the brief's own
  // `/save|create|submit/i` was a placeholder regex; read from
  // `Connection.jsx` directly rather than kept as a loose match.
  await adminPage.getByRole('button', { name: 'Save', exact: true }).click();

  // The assertion is the server's state, not a toast. `api.js`'s
  // errorNotification toasts AND rethrows, so a red toast and a green
  // toast are equally consistent with a write that never left the
  // browser. Poll for the *subscription* landing too, not just the row's
  // existence — creation (POST /api/connect/integrations/) and setting
  // subscriptions (PUT .../subscriptions/set/) are two separate requests
  // from `ConnectionForm.onSubmit`, and reading right after the first
  // would race the second.
  let created: ConnectIntegration | undefined;
  await expect
    .poll(
      async () => {
        const found = await findIntegration(api, name);
        if (found && found.subscriptions.some((s) => s.enabled)) created = found;
        return created;
      },
      { timeout: 30_000 }
    )
    .toBeDefined();

  expect(created!.type).toBe('webhook');
  expect(created!.config.url).toBe(WEBHOOK_URL);
  const enabledEvents = created!.subscriptions
    .filter((s) => s.enabled)
    .map((s) => s.event);
  expect(enabledEvents).toEqual(['channel_start']);

  // The card is rendered in the integrations grid, scoped away from the
  // log. `connect-integrations` sits on `{!isLoading && …}` (Connect.jsx),
  // so it only proves presence, never "still loading" — visibility of the
  // grid plus the poll above already establish the row is really there.
  const grid = adminPage.getByTestId('connect-integrations');

  // Card scoping: `IntegrationRow` (Connect.jsx) renders a Mantine `Card`
  // per integration, and both the name and the Edit/Delete buttons live
  // inside that one Card — Mantine gives every component's root element a
  // stable `mantine-<Component>-root` class for exactly this kind of
  // targeting (the project already relies on `.mantine-Loader-root` in
  // helpers.ts), so `.mantine-Card-root` selects one element per
  // integration, never an ancestor container. Filtering by the generated
  // name then narrows to exactly this worker's row — never `.first()`,
  // since four workers share this instance and another integration could
  // sort earlier. Asserting the count before acting is the point: getting
  // this wrong here means deleting another worker's data mid-run.
  const card = grid.locator('.mantine-Card-root').filter({ hasText: name });
  await expect(card).toHaveCount(1);
  await card.scrollIntoViewIfNeeded();

  // Toggle: the Switch is labelled `Enabled` in IntegrationRow, scoped to
  // this card. Mantine's `Switch` renders the real `<input
  // type="checkbox">` visually hidden (opacity/position, screen-reader
  // pattern) behind a styled track — `getByLabel('Enabled')` resolves the
  // input itself, and Playwright's actionability check then refuses to
  // click it ("element is not visible"), hanging for the full test
  // timeout rather than failing fast (confirmed empirically: the first
  // full run timed out here with the switch still showing `checked`).
  // The `<label for=…>` Mantine wraps around the track *and* the visible
  // "Enabled" text is what a real click lands on; clicking it fires the
  // associated input exactly as a user's click would.
  const wasEnabled = created!.enabled;
  await card.locator('label', { hasText: 'Enabled' }).click();
  await expect
    .poll(async () => (await findIntegration(api, name))?.enabled, { timeout: 30_000 })
    .toBe(!wasEnabled);

  // #62 (frontend/src/pages/Connect.jsx:205-212) — the subscription
  // badges this card renders (one enabled trigger, from above) have no
  // React `key`. This is the first test in the goal to create an
  // integration with an enabled subscription, so it was expected to be
  // the first to trigger React's "Each child in a list should have a
  // unique key prop" console warning. **It does not fire here — observed,
  // not assumed.** Checked twice against a real run: once with one
  // enabled subscription (this test's own shape) and once, isolated,
  // with two, in case the warning needed more than one keyless sibling to
  // trip — `pageErrors.consoleErrors` was `[]` both times. Root cause:
  // `docker/Dockerfile:22` builds the frontend the e2e image serves with
  // plain `npm run build` (Vite production mode), and React's dev-only
  // warnings — including this one — are `process.env.NODE_ENV`-gated and
  // compiled out entirely in a production bundle. So this class of
  // defect is structurally invisible to `pageErrors`' console channel in
  // this harness, independent of what any test does — not something a
  // different subscription count or a different flow would surface. #62
  // itself is unaffected (the missing `key` is still there in source, and
  // still a real reconciliation risk); this is a fact about what this
  // E2E environment can and cannot observe. No waiver is used below
  // because there is nothing to waive — waiving a check that was never
  // going to fire would misrepresent this as "handled" rather than "does
  // not apply here", and would silently start suppressing a *real* future
  // console error on this page if the image's build mode ever changed.
  await pageErrors.expectClean();

  // Delete. `deleteConnection` has no confirmation dialog
  // (frontend/src/pages/Connect.jsx), so the click is the whole action.
  await card.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect.poll(() => findIntegration(api, name), { timeout: 30_000 }).toBeUndefined();
});
