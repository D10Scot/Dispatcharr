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
