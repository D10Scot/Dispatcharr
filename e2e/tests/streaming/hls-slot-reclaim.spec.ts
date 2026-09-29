import { test, expect } from '../../fixtures';
import { enterHls, leaveHls, waitForSegments } from '../../fixtures/hls';
import { slotCappedChannels } from './helpers';

/**
 * Slot reclaim through nginx (Phase 4a-1c, spec D16, ruling R24), on an M3U
 * account with `max_streams: 1` whose provider also caps connections at 1, so
 * `capacity.blocked` genuinely comes from Django's slot refusal and the
 * provider's own cap confirms a first connection really closed.
 *
 * None of these waits out the idle timeout (R24): the longest wait is 5 s,
 * which is 2 x TARGETDURATION + 1 s and sits below the 12 s idle timeout. The
 * idle departure itself is pinned in Go with an injected clock.
 *
 * `rate: 1` on every scenario: the output is RE-ENCODED, so a faster-than-real-time
 * provider would measure the encoder's backlog rather than the product. Every
 * test ends by `DELETE`ing the sessions it opened, so the slot is free for the
 * next test on the same worker.
 */

const tune = (uuid: string): string => `/proxy/ts/stream/${uuid}?output_format=hls`;

// Timeouts are generous and never gates: a cold software start of the encoder
// on a shared runner is the slow part.
const SEGMENTS_TIMEOUT_MS = 60_000;

test(
  'a zap that leaves its session plays the next channel at once',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(240_000);
    const { a, b, scenario } = await slotCappedChannels(upstream, seed, api, seed.generatedName('reclaim-zap'));

    const tokens: string[] = [];
    try {
      const entryA = await enterHls(request, tune(a.uuid));
      tokens.push(entryA.token);
      expect(await leaveHls(request, entryA.token)).toBe(204);

      // Immediately: the leave answered only after its channel stopped, but
      // the channel's provider slot comes back when its release POST lands, a
      // moment later. The blocked tune waits for it rather than missing it.
      const entryB = await enterHls(request, tune(b.uuid));
      tokens.push(entryB.token);
      const playlist = await waitForSegments(request, entryB.token, 'video', 1, SEGMENTS_TIMEOUT_MS);
      expect(playlist.segments.length).toBeGreaterThanOrEqual(1);

      await expect
        .poll(async () => (await upstream.connections(scenario)).channels, { timeout: 10_000, intervals: [500] })
        .toEqual([2]);
    } finally {
      for (const token of tokens) await leaveHls(request, token);
    }
  }
);

test(
  'a session silent for more than two target durations yields its slot',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(240_000);
    const { a, b } = await slotCappedChannels(upstream, seed, api, seed.generatedName('reclaim-silent'));

    const tokens: string[] = [];
    try {
      const entryA = await enterHls(request, tune(a.uuid));
      tokens.push(entryA.token);
      // No request at all for 2 x TARGETDURATION + 1 s: silent, and well
      // below the 12 s idle timeout (R24).
      await new Promise((resolve) => setTimeout(resolve, 5_000));

      const entryB = await enterHls(request, tune(b.uuid));
      tokens.push(entryB.token);
      await waitForSegments(request, entryB.token, 'video', 1, SEGMENTS_TIMEOUT_MS);

      const gone = await request.get(`/hls/${entryA.token}/video.m3u8`);
      expect(gone.status(), "the reclaimed session's next request").toBe(410);
      expect(await gone.json()).toEqual({ error: 'channel stopped' });
    } finally {
      for (const token of tokens) await leaveHls(request, token);
    }
  }
);

test(
  'a session that keeps reloading holds its slot',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(240_000);
    const { a, b } = await slotCappedChannels(upstream, seed, api, seed.generatedName('reclaim-reload'));

    const tokens: string[] = [];
    let reloading = true;
    const statuses: number[] = [];
    let reloader: Promise<void> | undefined;
    try {
      const entryA = await enterHls(request, tune(a.uuid));
      tokens.push(entryA.token);
      await waitForSegments(request, entryA.token, 'video', 1, SEGMENTS_TIMEOUT_MS);

      // A paused player reloads its playlist about every target duration
      // (M7); a reload every second is at least that often.
      reloader = (async () => {
        while (reloading) {
          const response = await request.get(`/hls/${entryA.token}/video.m3u8`, { timeout: 30_000 });
          statuses.push(response.status());
          await new Promise((resolve) => setTimeout(resolve, 1_000));
        }
      })();
      await new Promise((resolve) => setTimeout(resolve, 5_000));

      // Django's refusal, relayed: not an upstream failure.
      const refused = await request.get(tune(b.uuid), { timeout: 60_000 });
      expect(refused.status()).toBe(503);
      expect(await refused.text()).toContain('no source available');

      await new Promise((resolve) => setTimeout(resolve, 2_000));
      reloading = false;
      await reloader;
      expect(statuses.length, 'the reloader ran').toBeGreaterThan(0);
      expect(new Set(statuses), "A's reload kept answering 200").toEqual(new Set([200]));
    } finally {
      reloading = false;
      await reloader?.catch(() => undefined);
      for (const token of tokens) await leaveHls(request, token);
    }
  }
);
