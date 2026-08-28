import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile, newStreamClient } from '../streaming/helpers';
import { greyboxRedis } from '../../fixtures/greybox/redis';

test('two clients on one output profile share a single transcode', async ({
  upstream,
  seed,
  api,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Output', tvgId: 'g4-output.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  const output = await api.json<{ id: number }>(
    await api.post('/api/core/outputprofiles/', {
      name: seed.generatedName('outputProfile'),
      command: 'ffmpeg',
      parameters: '-i pipe:0 -c copy -f mpegts pipe:1',
      is_active: true,
    }),
    'output profile'
  );

  const clients = [newStreamClient(), newStreamClient()];
  try {
    for (const c of clients) {
      await c.open(`/proxy/ts/stream/${channel.uuid}?output_profile=${output.id}`);
      expectTsAligned(await c.readPackets(20));
    }

    // Both clients are attached to the same output profile...
    const status = await readChannelStatus(api, channel.uuid);
    expect(status.client_count).toBe(2);
    expect(status.clients.every((c) => c.output_profile_id === output.id)).toBe(true);

    // ...and exactly one worker owns the transcode. The byte stream cannot
    // show this: two ffmpegs would produce byte-identical output. Only the
    // owner lock distinguishes "shared" from "duplicated", which is why this
    // row is in the quarantine.
    //
    // `RedisKeys.output_owner(channel_id, fmt)` (apps/proxy/live_proxy/redis_keys.py)
    // builds `live:channel:{channel_id}:output:{fmt}:owner`. The output
    // profile manager (apps/proxy/live_proxy/output/profile/manager.py)
    // namespaces its format as `mpegts:p{profile_id}`, and — like every
    // live_proxy endpoint — `channel_id` here is the channel's UUID string,
    // never its numeric DB id (confirmed via `stream_ts`'s
    // `<str:channel_id>` route and `OutputProfileManager`'s own
    // `channel_id[:8]` log slicing, which only makes sense for a UUID). The
    // owner key is a single CAS'd string (`SET NX`), not a per-worker set, so
    // this is an exact key, not a wildcard: KEYS on it can only ever return 0
    // or 1 result. Length 1 says a manager holds the lock; length 0 would
    // mean the transcode never started or the key shape above is wrong.
    const ownerKey = `live:channel:${channel.uuid}:output:mpegts:p${output.id}:owner`;
    const owners = await greyboxRedis().keys(ownerKey);
    expect(owners).toHaveLength(1);
  } finally {
    await Promise.all(clients.map((c) => c.close().catch(() => {})));
  }
});
