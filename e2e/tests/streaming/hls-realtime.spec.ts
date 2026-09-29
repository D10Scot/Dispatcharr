import { test, expect } from '../../fixtures';
import { enterHls, leaveHls, parseMediaPlaylist, waitForSegments } from '../../fixtures/hls';
import { lockedProfile, stopChannels } from './helpers';

/**
 * Whether the SOFTWARE transcode of the worst fixture keeps up with real time
 * (Phase 4a-1b, ruling R29). A characterization, not a contract: it records a
 * measurement and asserts only that segments appear.
 *
 * `h264-1080i-aac-ac3` is a 1080i broadcast source; the output is 1080p50
 * through libx264. Once its first segment is listed, this polls the video
 * playlist every second for 40 s and sums the EXTINF of every segment listed
 * for the first time: that sum over the wall clock is the fraction of real
 * time the encoder sustained (1.0 is real time). The `streaming` project runs
 * two workers, so the figure is taken under whatever the other worker runs,
 * and the log line says so.
 *
 * A ratio below 1.0 is a finding for the orchestrator (R53), never a lowered
 * assertion. Hardware measurements never gate (R45), and this is software on a
 * CI runner.
 */

const WINDOW_MS = 40_000;

test(
  'the software transcode of the 1080i fixture is measured against real time',
  { tag: '@characterization' },
  async ({ upstream, seed, api, request }, testInfo) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'HLS Realtime', tvgId: 'hls-realtime.e2e', logo: null, asset: 'h264-1080i-aac-ac3' }],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      const first = await waitForSegments(request, entry.token, 'video', 1, 120_000);
      const seen = new Set(first.segments.map((s) => s.seq));

      let listed = 0;
      const started = Date.now();
      while (Date.now() - started < WINDOW_MS) {
        await new Promise((resolve) => setTimeout(resolve, 1_000));
        const response = await request.get(`/hls/${entry.token}/video.m3u8`);
        if (response.status() !== 200) continue;
        for (const segment of parseMediaPlaylist(await response.text()).segments) {
          if (!seen.has(segment.seq)) {
            seen.add(segment.seq);
            listed += segment.duration;
          }
        }
      }
      const ratio = listed / ((Date.now() - started) / 1000);

      testInfo.annotations.push({ type: 'r29-1080i-realtime-ratio', description: ratio.toFixed(3) });
      // eslint-disable-next-line no-console
      console.log(
        `r29-1080i-realtime-ratio=${ratio.toFixed(3)} (${listed.toFixed(1)} s of segments over a ${WINDOW_MS / 1000} s window, ` +
          'software libx264, under the streaming project\'s two workers)'
      );
      expect(seen.size, 'segments appear').toBeGreaterThan(first.segments.length);
    } finally {
      await leaveHls(request, entry.token);
      await stopChannels(api, channel.uuid);
    }
  }
);
