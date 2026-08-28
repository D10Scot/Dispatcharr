import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile } from '../streaming/helpers';

test('an upstream that refuses the connection fails over before serving', async ({
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
  expectTsAligned(await streamClient.readPackets(100));

  const status = await readChannelStatus(api, channel.uuid);
  expect(status.stream_id, 'should never have settled on the 404 stream').toBe(
    streams[1].id
  );

  // The provider saw the refused attempt on 1 and the successful one on 2.
  const log = await upstream.log(scenario);
  expect(log.some((e) => e.kind === 'open' && e.channelId === 2)).toBe(true);
});
