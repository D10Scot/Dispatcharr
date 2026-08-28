import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile } from '../streaming/helpers';

test('a dead upstream fails over to the next stream', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'G4 DeadAir A', tvgId: 'g4-deadair-a.e2e', logo: null },
      { id: 2, name: 'G4 DeadAir B', tvgId: 'g4-deadair-b.e2e', logo: null },
    ],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  expectTsAligned(await streamClient.readPackets(100));

  // dead-air applies to live connections as well as new ones, so this reaches
  // the connection already open. The watchdog is >10s, sampled 3x at 5s — call
  // it ~25s before it fires, and allow generous headroom over that.
  await upstream.fault(scenario, 'dead-air', { channel: 1 });

  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
      timeout: 120_000,
      intervals: [2_000],
    })
    .toBe(streams[1].id);

  // The client survived the failover: it is still attached and still fed.
  const after = await streamClient.readPackets(100);
  expectTsAligned(after);
  expect((await readChannelStatus(api, channel.uuid)).client_count).toBe(1);
});
