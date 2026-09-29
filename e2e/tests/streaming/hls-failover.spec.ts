import { test, expect, readChannelStatus } from '../../fixtures';
import { enterHls, leaveHls, parseMediaPlaylist, waitForSegments } from '../../fixtures/hls';
import { lockedProfile, stopChannels } from './helpers';

/**
 * A failover under a live HLS session (Phase 4a-1b, spec D10, parity-matrix
 * row 32's E2E pin): the channel moves to an alternate whose stream is a
 * different codec fixture, and the HLS output starts a NEW GENERATION behind
 * `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` while the media sequence
 * continues and the multivariant's CODECS stay what they were (spec D8: the
 * output's shape is fixed for the run).
 *
 * The failover gap (spec Q6) is MEASURED here and never asserted: the seconds
 * from the first status poll that names the alternate to the first video
 * playlist poll that lists a segment after the discontinuity, at the polls'
 * 250 ms resolution. It is an upper bound on "boundary to the new generation's
 * first segment" by the time the relay spent retrying the first URL before
 * switching, which the log line reports as the time from the fault to the flip.
 * Recorded as an annotation and one console line, for the PR body and
 * e2e/COVERAGE.md; on a software encoder in CI it says nothing about Quick Sync
 * (ruling R45: hardware measurements never gate).
 */

const POLL_MS = 250;

test(
  'a failover to a different asset starts a new generation behind EXT-X-DISCONTINUITY',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }, testInfo) => {
    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'HLS Failover A', tvgId: 'hls-failover-a.e2e', logo: null, asset: 'h264-1080i-aac-ac3' },
        { id: 2, name: 'HLS Failover B', tvgId: 'hls-failover-b.e2e', logo: null, asset: 'mpeg2-576i-mp2' },
      ],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel, streams } = await seed.upstreamChannel(scenario, {
      channelIds: [1, 2],
      streamProfileId: proxy.id,
    });

    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      // The session plays generation 0.
      const before = await waitForSegments(request, entry.token, 'video', 2, 90_000);
      expect(before.segments.some((s) => s.discontinuity)).toBe(false);
      expect((await readChannelStatus(api, channel.uuid)).stream_id).toBe(streams[0].id);

      // not-found first, so every reconnect to stream 1 is refused; then
      // disconnect closes the live connection. not-found reaches no live
      // connection (appliedTo 0), disconnect reaches the open one.
      const notFound = await upstream.fault(scenario, 'not-found', { channel: 1 });
      expect(notFound.appliedTo).toBe(0);
      const faultAt = Date.now();
      const disconnect = await upstream.fault(scenario, 'disconnect', { channel: 1 });
      expect(disconnect.appliedTo).toBeGreaterThanOrEqual(1);

      // The channel switches to stream 2: the first status poll to say so.
      let flippedAt = 0;
      await expect
        .poll(
          async () => {
            const id = (await readChannelStatus(api, channel.uuid)).stream_id;
            if (id === streams[1].id && flippedAt === 0) flippedAt = Date.now();
            return id;
          },
          { timeout: 90_000, intervals: [POLL_MS] }
        )
        .toBe(streams[1].id);

      // The first video playlist poll that lists a segment after a
      // discontinuity, whose EXT-X-MAP names generation 1's init.
      let listedAt = 0;
      let after = before;
      await expect
        .poll(
          async () => {
            const response = await request.get(`/hls/${entry.token}/video.m3u8`);
            if (response.status() !== 200) return false;
            after = parseMediaPlaylist(await response.text());
            const index = after.segments.findIndex((s) => s.discontinuity);
            if (index === -1) return false;
            if (listedAt === 0) listedAt = Date.now();
            return true;
          },
          { timeout: 90_000, intervals: [POLL_MS] }
        )
        .toBe(true);

      const discontinuous = after.segments.findIndex((s) => s.discontinuity);
      expect(after.text).toContain('#EXT-X-DISCONTINUITY');
      expect(after.segments[discontinuous].map, 'a new EXT-X-MAP behind the discontinuity').toMatch(/init-1\.mp4$/);
      expect(after.segments[0].map ?? after.segments[discontinuous].map).toBeDefined();
      expect(after.mediaSequence, 'the media sequence continues, never restarts').toBeGreaterThanOrEqual(before.mediaSequence);

      // The multivariant is fixed for the run: a fresh entry declares the same
      // CODECS the first did.
      const fresh = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
      try {
        expect(fresh.multivariant.variants.map((v) => v.codecs)).toEqual(entry.multivariant.variants.map((v) => v.codecs));
      } finally {
        await leaveHls(request, fresh.token);
      }

      // Q6, recorded and never asserted.
      const gap = (listedAt - flippedAt) / 1000;
      const retrying = (flippedAt - faultAt) / 1000;
      testInfo.annotations.push({ type: 'q6-failover-gap-seconds', description: gap.toFixed(2) });
      // eslint-disable-next-line no-console
      console.log(
        `q6-failover-gap-seconds=${gap.toFixed(2)} (status flip to the first segment after the discontinuity, ${POLL_MS} ms polls; ` +
          `the fault-to-flip time was ${retrying.toFixed(2)} s)`
      );
    } finally {
      await leaveHls(request, entry.token);
      await stopChannels(api, channel.uuid);
    }
  }
);
