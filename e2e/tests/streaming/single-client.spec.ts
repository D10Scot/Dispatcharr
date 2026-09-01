import { test, expect, expectTsAligned, expectContiguous, videoPidOf, TS_PACKET_SIZE, readChannelStatus } from '../../fixtures';
import { lockedProfile } from './helpers';

test('one client receives aligned, contiguous TS through the Proxy profile', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Single', tvgId: 'g4-single.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const packets = await streamClient.readPackets(400);

  expect(packets.byteLength).toBe(400 * TS_PACKET_SIZE);
  expectTsAligned(packets);
  // Alignment proves framing. Contiguity proves nothing was lost or spliced —
  // which is the property the whole relay extraction rests on.
  expectContiguous(packets, videoPidOf(packets));

  const status = await readChannelStatus(api, channel.uuid);
  expect(status.client_count).toBe(1);

  // total_bytes is assigned only once the metadata field exists, so a status
  // read taken moments after start can omit it entirely. Poll rather than read
  // once — a bare read makes this a flake, not a detector.
  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).total_bytes ?? 0, {
      timeout: 30_000,
    })
    .toBeGreaterThan(0);

  // The provider agrees it served exactly one connection for this channel.
  const opens = (await upstream.log(scenario)).filter(
    (e) => e.kind === 'open' && e.channelId === 1
  );
  expect(opens).toHaveLength(1);
});
