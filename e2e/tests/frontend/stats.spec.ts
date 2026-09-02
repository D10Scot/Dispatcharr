import { test, expect } from '../../fixtures';
import { lockedProfile, withDeadline } from '../streaming/helpers';
import { SURFACES, gotoSurface } from './helpers';

const statsSurface = SURFACES.find((s) => s.name === 'Stats');
if (!statsSurface) {
  throw new Error('stats.spec.ts: no "Stats" entry in SURFACES — check helpers.ts');
}

// The only G6 row that needs live data, and deliberately the only one: with no
// active connections the Stats page renders an empty grid, which proves
// nothing about the wiring. This spec needs the full local two-container
// setup (scripts/e2e_up.sh), not a bare E2E_BASE_URL run — see e2e/README.md.
// The `frontend` project is wired into the matrix job's `project` list in
// `.github/workflows/e2e-tests.yml`, alongside `pristine, seeded, streaming,
// streaming-failover, streaming-greybox, lifecycle`, so this spec runs in CI
// like every other row in this directory, and gets the same
// `scripts/e2e_up.sh`-brought-up upstream every other CI job does.
//
// Teardown: no `test.afterEach` here, unlike plugins.spec.ts/backups.spec.ts.
// Those clean up a resource (a plugin key, a backup archive) that has no
// dedicated fixture teardown of its own — the DELETE has to happen somewhere,
// and a body-level `finally`/`try` does not survive a Playwright-forced
// timeout (Task 12), so it goes in `afterEach`. The resource this test needs
// released — the live connection holding a provider slot — is different: it
// is exactly what the `streamClient` fixture itself tears down
// (fixtures/index.ts's `streamClient` fixture calls `client.close()` after
// `use()`), and that fixture teardown is documented (fixtures/index.ts, the
// `instance` fixture's comment) to run even after a forced timeout, unlike a
// test-body `finally`. A second `test.afterEach` calling `streamClient.close()`
// would run strictly before that guaranteed fixture teardown and add no
// robustness — `close()` is idempotent, so it would just be a no-op call.
// `seed.upstreamChannel()` and `upstream.scenario()` need no cleanup either:
// scenarios are documented to live for the provider process's life with no
// cleanup path, and a leftover channel row is inert without a live connection
// to it — it cannot appear in `stats-connections` on its own.
test('an active stream appears as a connection on the Stats page', { tag: '@contract' }, async ({
  adminPage,
  api,
  seed,
  upstream,
  streamClient,
  pageErrors,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G6 Stats', tvgId: 'g6-stats.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  // Read a little so the channel is genuinely serving before the page loads;
  // an opened-but-unread connection may not have registered yet. Bounded via
  // withDeadline: readPackets() only throws when the stream *ends*, so a
  // stalled upstream would otherwise hang silently to the 120s project
  // timeout instead of failing here with a diagnostic cause.
  await withDeadline(streamClient.readPackets(100), 30_000, 'readPackets(100)');

  // Not `adminPage.goto('/stats')`, which the brief's Step 1 draft used: a
  // direct load of any protected route other than `/channels` hits #58 (see
  // `gotoSurface`'s own doc comment in helpers.ts) — the async auth-init race
  // sends it back to `/channels` before the route ever mounts, so the "Stats"
  // sidebar link would still be visible but the main content would silently
  // stay the Channels page. Confirmed against a real run of the brief's
  // literal draft: it failed with `stats-page` never appearing, snapshotting
  // the Channels grid instead. `gotoSurface` is every other G6 spec's
  // workaround and already asserts `stats-page` visible on the way out.
  await gotoSurface(adminPage, statsSurface);

  // Scoped to the connections grid, NOT the page: the page also renders a
  // fixed-position <SystemEvents> log at the bottom which prints the same
  // channel name, and an event-log line must not pass for a live connection.
  //
  // The generous timeout is the page's own poll interval (5s by default,
  // `stats-refresh-interval` in localStorage) plus room for the WebSocket
  // stats broadcast, on a CI runner.
  await expect(
    adminPage.getByTestId('stats-connections').getByText(channel.name)
  ).toBeVisible({ timeout: 60_000 });

  await pageErrors.expectClean();
});

// A second G6 wiring test gets its own upstream/channel/streamClient rather
// than reusing the test above's: every Playwright fixture is per-test, so
// there is nothing shared here to protect and nothing to gain by sharing.
test('the Refresh Now button re-reads the connection list', { tag: '@contract' }, async ({
  adminPage,
  api,
  seed,
  upstream,
  streamClient,
  pageErrors,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G6 Stats Refresh', tvgId: 'g6-stats-refresh.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  // Same reasoning as the sibling test above: prove the channel is actually
  // serving before either fixture is exercised.
  await withDeadline(streamClient.readPackets(100), 30_000, 'readPackets(100)');

  // Turn the page's own 5s poll off before the first load, not by driving
  // the "Refresh Interval (seconds)" `NumberInput` after the fact. Two
  // reasons this has to happen before `gotoSurface`, not after:
  //
  // 1. `useLocalStorage` (`frontend/src/hooks/useLocalStorage.jsx`) reads
  //    `stats-refresh-interval` in a lazy `useState` initializer, i.e. only
  //    once, at mount — a value set after the page has already rendered
  //    would need the `NumberInput` interaction this replaces anyway.
  // 2. `gotoSurface` begins with a real `page.goto`, which is the one
  //    moment `addInitScript` reruns.
  //
  // `stats-refresh-interval` is a page-local `useLocalStorage` key
  // (Stats.jsx), not a `CoreSettings` row, so setting it here does not touch
  // `/api/core/settings/` (global constraint GLOBAL_SETTINGS_WRITE). Stats
  // "Always fetch[es] once on mount, regardless of polling interval
  // setting" (Stats.jsx's own comment on that effect), so disabling the poll
  // up front does not stop the connection from appearing below — that first
  // fetch still happens.
  await adminPage.addInitScript(() => {
    localStorage.setItem('stats-refresh-interval', '0');
  });

  await gotoSurface(adminPage, statsSurface);

  const statsPage = adminPage.getByTestId('stats-page');
  const connections = adminPage.getByTestId('stats-connections');

  await expect(connections.getByText(channel.name)).toBeVisible({ timeout: 60_000 });
  await expect(statsPage.getByText('Refreshing disabled')).toBeVisible();

  await streamClient.close();

  const refreshNow = statsPage.getByRole('button', { name: 'Refresh Now', exact: true });

  // What actually proves the click does something: `ClientManager.remove_client`
  // (apps/proxy/live_proxy/client_manager.py) fires its own WebSocket
  // `channel_stats` broadcast the moment the server notices the client is
  // gone, and `WebSocket.jsx`'s `channel_stats` handler calls `setChannelStats`
  // completely unconditionally — no page gating, no dependency on the poll
  // interval or on anything this test clicks. With that broadcast in play, a
  // "the connection disappeared" assertion taken alone is satisfied whether
  // or not `Refresh Now` is wired to anything: the connection would clear on
  // its own once the server-side cleanup and broadcast land, which a
  // generous wait cannot tell apart from the click. What the click actually,
  // exclusively causes is the GET request `fetchAllStats`'s `onClick` fires
  // (Stats.jsx) — `combined_stats` (apps/proxy/stats_views.py), routed at
  // `/proxy/stats/` (apps/proxy/urls.py) — so that request, not a DOM
  // change, is what this test asserts against the click.
  const [response] = await Promise.all([
    adminPage.waitForResponse(
      (r) => r.url().includes('/proxy/stats/') && r.request().method() === 'GET',
      { timeout: 10_000 }
    ),
    refreshNow.click(),
  ]);
  expect(response.ok()).toBe(true);
  const body = await response.json();
  expect(body).toHaveProperty('live');

  // No separate "the connection eventually clears" assertion here. It would
  // prove nothing about the click either way (see above), and tried against
  // a real run it did not resolve inside a 30s wait — plausibly because
  // `ClientManager`'s ghost-client scan, the fallback for a client whose
  // stream generator never got a clean `GeneratorExit`, only fires after
  // `heartbeat_interval * GHOST_CLIENT_MULTIPLIER`
  // (`apps/proxy/live_proxy/client_manager.py`), which `apps/proxy/config.py`
  // sets to 5s * 10.0 = 50s by default (`CLIENT_HEARTBEAT_INTERVAL`,
  // `GHOST_CLIENT_MULTIPLIER`) — longer than the 30s this test tried, and
  // eating most of what's left of this project's 120s per-test timeout on
  // top of everything already spent above it. Better to assert only what
  // this test can back up.
  await pageErrors.expectClean();
});
