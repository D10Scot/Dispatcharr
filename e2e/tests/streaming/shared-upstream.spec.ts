import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile, newStreamClient } from './helpers';

test('three clients share exactly one upstream connection', async ({
  upstream,
  seed,
  api,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Shared', tvgId: 'g4-shared.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  const clients = [newStreamClient(), newStreamClient(), newStreamClient()];
  try {
    for (const c of clients) {
      await c.open(`/proxy/ts/stream/${channel.uuid}`);
      expectTsAligned(await c.readPackets(20));
    }

    await expect
      .poll(async () => (await readChannelStatus(api, channel.uuid)).client_count, {
        timeout: 20_000,
      })
      .toBe(3);

    // The point of the row: three clients, one upstream.
    const live = await upstream.connections(scenario);
    expect(live.live).toBe(1);

    await clients[0].close();
    await expect
      .poll(async () => (await readChannelStatus(api, channel.uuid)).client_count, {
        timeout: 20_000,
      })
      .toBe(2);
    expect((await upstream.connections(scenario)).live).toBe(1);
  } finally {
    await Promise.all(clients.map((c) => c.close().catch(() => {})));
  }
});

test('closing every client releases the upstream', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Teardown', tvgId: 'g4-teardown.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  expectTsAligned(await streamClient.readPackets(20));
  expect((await upstream.connections(scenario)).live).toBe(1);

  await streamClient.close();

  // The channel does not stop the instant the last client leaves — the owner
  // notices on its next main-loop iteration. Poll rather than assert once.
  await expect
    .poll(async () => (await upstream.connections(scenario)).live, { timeout: 60_000 })
    .toBe(0);
});
