import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';
import type { Channel, StreamProfile } from '../../fixtures';

interface StreamProfilePage {
  count: number;
  results: StreamProfile[];
}

test('Dispatcharr proxies the fake upstream to a client', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });

  // The Proxy profile is raw HTTP passthrough — no subprocess — so what the
  // client receives is the provider's own bytes. That makes a failure here a
  // statement about the network path, not about ffmpeg.
  const profiles = await api.json<StreamProfilePage | StreamProfile[]>(
    await api.get('/api/core/streamprofiles/'),
    'locked stream profiles'
  );
  const all = Array.isArray(profiles) ? profiles : profiles.results;
  const proxyProfile = all.find((p) => p.name === 'Proxy');
  expect(proxyProfile, 'the locked "Proxy" stream profile should ship').toBeDefined();

  // No seed.stream() factory exists; generatedName is exported for exactly
  // this case — a row created by hand that still respects the naming scheme.
  const stream = await api.json<{ id: number }>(
    await api.post('/api/channels/streams/', {
      name: seed.generatedName('stream'),
      url: upstream.streamUrl(scenario, 1),
      is_custom: true,
    }),
    'custom stream pointing at the fake upstream'
  );

  const channel: Channel = await seed.channel({
    streams: [stream.id],
    stream_profile_id: proxyProfile!.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const packets = await streamClient.readPackets(50);

  expect(packets.byteLength).toBe(50 * TS_PACKET_SIZE);
  expectTsAligned(packets);

  // The provider agrees it served exactly one connection for this channel.
  const seen = await upstream.log(scenario);
  expect(seen.some((entry) => entry.kind === 'open' && entry.channelId === 1)).toBe(true);
});
