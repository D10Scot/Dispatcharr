import { test, expect } from '../../fixtures';
import type { M3uAccount } from '../../fixtures';

interface StreamPage {
  count: number;
  results: { id: number; name: string; url: string }[];
}

test('Dispatcharr ingests a playlist from the fake upstream', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // Names are worker- and test-scoped so the ?search= below is a filtered
  // query, not an assertion about global state. The default catalogue's
  // "Fake Channel 1" would collide across parallel tests.
  const prefix = seed.generatedName('upstreamChannel');
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null },
      { id: 2, name: `${prefix}-b`, tvgId: `${prefix}-b.e2e`, logo: null },
    ],
  });

  const account = await seed.m3uAccount({
    server_url: upstream.playlistUrl(scenario),
    // Both overrides are load-bearing: the factory defaults to an inactive
    // account on a dead port, and an inactive account never starts a refresh.
    is_active: true,
  });

  // m3uRefreshComplete triggers the refresh itself. Do not POST it first.
  const refreshed: M3uAccount = await waitFor.m3uRefreshComplete(account.id);
  expect(refreshed.status).toBe('success');

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    'streams created by the upstream ingest'
  );

  expect(page.count).toBe(2);
  expect(page.results.map((s) => s.name).sort()).toEqual([`${prefix}-a`, `${prefix}-b`]);
  // The URL survived the round trip, which is what proves the playlist was
  // parsed rather than merely fetched.
  expect(page.results[0].url).toContain(scenario.id);
});
