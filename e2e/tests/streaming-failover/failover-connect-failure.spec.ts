import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile, withDeadline } from '../streaming/helpers';

// Comfortably under the project's 300s timeout: a post-failover read against
// a channel that may have just vanished can hang forever rather than throw,
// since readPackets only rejects on a clean stream end.
const READ_DEADLINE_MS = 60_000;

test('an upstream that refuses the connection fails over before serving', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'G4 Connect A', tvgId: 'g4-connect-a.e2e', logo: null },
      { id: 2, name: 'G4 Connect B', tvgId: 'g4-connect-b.e2e', logo: null },
    ],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    streamProfileId: proxy.id,
  });

  // not-found is a "new connection only" fault: arm it BEFORE the first
  // client, and expect appliedTo: 0 — there is no live connection to apply it
  // to, which is correct rather than a failure.
  const armed = await upstream.fault(scenario, 'not-found', { channel: 1 });
  expect(armed.appliedTo).toBe(0);

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  expectTsAligned(
    await withDeadline(
      streamClient.readPackets(100),
      READ_DEADLINE_MS,
      'readPackets after the connect-failure failover'
    )
  );

  const status = await readChannelStatus(api, channel.uuid);
  expect(status.stream_id, 'should never have settled on the 404 stream').toBe(
    streams[1].id
  );

  // The provider saw the refused attempt on 1 and the successful one on 2.
  const log = await upstream.log(scenario);
  expect(log.some((e) => e.kind === 'open' && e.channelId === 2)).toBe(true);
  // The `request` log kind carries no channelId, only path and status — the
  // 404 route logs before it knows a channel was ever admitted. Match on the
  // path instead: `e2e-upstream/src/server.ts`'s stream route matches
  // `/s/<scenarioId>/stream/<channelId>.ts`, and `logRequest` records
  // `url.pathname + url.search` — so this anchors on the route ending in
  // `/stream/1.ts`, optionally followed by a query string, rather than a
  // bare `endsWith` that would break the moment this scenario declared
  // credentials or a `redirect-chain` fault appended `?chain=`.
  expect(
    log.some(
      (e) => e.kind === 'request' && e.status === 404 && /\/stream\/1\.ts(\?.*)?$/.test(e.path ?? '')
    ),
    'the provider should have refused an attempt on channel 1'
  ).toBe(true);
});
