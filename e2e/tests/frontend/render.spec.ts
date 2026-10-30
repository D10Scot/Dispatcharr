import { expect } from '@playwright/test';
import { test } from '../../fixtures';
import { SURFACES, gotoSurface } from './helpers';

// Exemplar: the cheapest wiring proof in G6, and the reason the project
// exists. `frontend/src/api.js` (4,017 lines) and `WebSocket.jsx` (1,130) have
// no tests at all, and every vitest test mocks `api.js` — so nothing else in
// this repository observes a page talking to a real server. These nine tests
// assert the page mounts, throws nothing, logs no error, and issues no request
// the server refuses.
//
// They deliberately do NOT assert on content: that is each surface's own spec.
for (const surface of SURFACES) {
  test(`${surface.name} renders clean at ${surface.route}`, { tag: '@contract' }, async ({
    adminPage,
    pageErrors,
  }) => {
    await gotoSurface(adminPage, surface);

    // A moment for deferred work — lazy chunks, the first poll, the WebSocket
    // handshake — to produce whatever it is going to produce. Bounded, and
    // short: this runs nine times.
    await adminPage.waitForTimeout(2_000);

    await pageErrors.expectClean();
  });
}

// The one place this project asserts on product copy. `helpers.ts` says the
// suite never selects by text because text couples a test to UI copy; this pin
// couples to copy on purpose, because the copy is its subject: the page title
// (`frontend/index.html`), the sidebar logo's `alt` and the sidebar brand text
// (`Sidebar.jsx`) are the three strings every user sees first, and nothing
// else in `e2e/tests/frontend/` would notice if one of them still named the
// old product. `exact` keeps the role query from also matching a longer name
// such as "Mino Logo".
test('the page title and sidebar name the product Mino', { tag: '@contract' }, async ({
  adminPage,
  pageErrors,
}) => {
  await gotoSurface(adminPage, SURFACES[0]);

  await expect(adminPage).toHaveTitle('Mino');
  await expect(adminPage.getByRole('img', { name: 'Mino', exact: true })).toBeVisible();
  await expect(adminPage.getByText('Mino', { exact: true })).toBeVisible();

  await pageErrors.expectClean();
});
