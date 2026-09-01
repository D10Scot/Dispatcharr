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
