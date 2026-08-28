import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile } from '../streaming/helpers';

test('switching the upstream mid-stream does not disturb a reading client', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'G4 Switch A', tvgId: 'g4-switch-a.e2e', logo: null },
      { id: 2, name: 'G4 Switch B', tvgId: 'g4-switch-b.e2e', logo: null },
    ],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const before = await streamClient.readPackets(200);
  expectTsAligned(before);

  const beforeStatus = await readChannelStatus(api, channel.uuid);
  expect(beforeStatus.stream_id).toBe(streams[0].id);

  // change_stream names its target explicitly; next_stream would depend on ordering.
  const res = await api.post(`/proxy/ts/change_stream/${channel.uuid}`, {
    stream_id: streams[1].id,
  });
  expect(res.status(), 'switch should be applied, not merely accepted').toBe(200);

  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
      timeout: 60_000,
    })
    .toBe(streams[1].id);

  // Taken at the earliest observable moment after the switch. buffer_index is
  // monotonic for the channel's life and is never reset by a switch — that is
  // why a switch is invisible to clients. The poll below proves forward
  // progress; only this proves the index did not regress, because a
  // reset-to-zero climbs back past the old value in ~1.4s at this rate and the
  // poll's 30s window would not notice.
  const atSwitch = await readChannelStatus(api, channel.uuid);
  expect(atSwitch.buffer_index).toBeGreaterThanOrEqual(beforeStatus.buffer_index);

  const after = await streamClient.readPackets(200);
  expectTsAligned(after);

  // The invariant that makes a switch invisible to clients: the chunk index is
  // monotonic for the channel's life and is never reset by a switch. The
  // anti-reset check above is instant; this one proves forward progress —
  // polled rather than a single instant comparison, because a chunk is
  // ~1.06MB and the fake upstream at rate 20 can complete the whole
  // switch-plus-200-packet-read above in under one chunk's worth of wall
  // time, so `buffer_index` can still read equal to `beforeStatus.buffer_index`
  // the instant we check — not because the invariant is false, but because no
  // new chunk has rolled yet.
  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).buffer_index, {
      timeout: 30_000,
    })
    .toBeGreaterThan(beforeStatus.buffer_index);

  const afterStatus = await readChannelStatus(api, channel.uuid);
  expect(afterStatus.client_count).toBe(1);

  // The provider saw the handover: channel 1 closed, channel 2 opened. The
  // provider records that `open` entry asynchronously — Dispatcharr's own
  // status confirming the switch (polled above) does not mean the provider
  // has logged the new connection yet, so a single read here races it. Poll
  // instead, like every other provider-log assertion in this suite.
  await expect
    .poll(
      async () =>
        (await upstream.log(scenario)).some((e) => e.kind === 'open' && e.channelId === 2),
      { timeout: 30_000 }
    )
    .toBe(true);
});
