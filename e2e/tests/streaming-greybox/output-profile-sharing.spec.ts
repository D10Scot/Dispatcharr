import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile, newStreamClient } from '../streaming/helpers';
import { greyboxRedis } from '../../fixtures/greybox/redis';

const execFileAsync = promisify(execFile);

// Mirrors the container-name resolution in fixtures/greybox/redis.ts, which
// this file does not import — a process count isn't a Redis operation, and
// that module's quarantine is specifically about the Redis coupling.
const CONTAINER_NAME = process.env.DISPATCHARR_E2E_CONTAINER || 'dispatcharr-e2e';

/**
 * Count running `ffmpeg` processes inside the stack container.
 *
 * `-x` matches the process name exactly, not the command line — `pgrep -f
 * ffmpeg` would match its own `docker exec ... pgrep -f ffmpeg` invocation
 * and self-inflate the count by one, every time. `-x` returns 0 at rest with
 * no false positive.
 *
 * `pgrep` exits 1 (not 0) when nothing matches, which execFile treats as a
 * rejection rather than empty stdout — caught below and normalised to 0.
 */
async function countFfmpegProcesses(): Promise<number> {
  try {
    const { stdout } = await execFileAsync('docker', [
      'exec',
      CONTAINER_NAME,
      'pgrep',
      '-x',
      'ffmpeg',
    ]);
    return stdout.split('\n').filter((line) => line.trim().length > 0).length;
  } catch (err) {
    const e = err as { code?: number };
    if (e.code === 1) return 0;
    throw err;
  }
}

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

    // ...and there is exactly one ffmpeg transcode process for it, not two.
    // The byte stream cannot show this on its own — two ffmpegs transcoding
    // the same input produce byte-identical output — which is why this row
    // is in the quarantine and reaches into the container directly.
    //
    // This count is unambiguous only because `channel` uses the locked
    // "Proxy" stream profile (see `lockedProfile(api, 'Proxy')` above), which
    // spawns no input subprocess of its own — Proxy is a raw-HTTP-into-buffer
    // stream profile, not a subprocess one (see CLAUDE.md's Stream Profile
    // architectures). Any `ffmpeg` present in the container is therefore the
    // output transcode this test cares about. If this row is ever changed to
    // use an ffmpeg-based stream profile, that upstream-side ffmpeg would
    // also match `pgrep -x ffmpeg` and this assertion's basis breaks silently
    // — update this comment and the count if that happens.
    expect(await countFfmpegProcesses()).toBe(1);

    // The process count proves the row's literal claim; the owner lock below
    // is complementary, not redundant — it proves the *lock* correctly
    // tracks the (channel, profile) pair, and its key name is more useful in
    // a failure message than a bare process count would be.
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
