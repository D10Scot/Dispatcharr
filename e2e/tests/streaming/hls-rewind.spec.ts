import { test, expect, readChannelStatus } from '../../fixtures';
import type { ApiClient, Seeder, UpstreamClient } from '../../fixtures';
import { enterHls, fragmentTiming, initSummary, leaveHls, topLevelBoxes, waitForSegments } from '../../fixtures/hls';
import { lockedProfile, slotCappedChannels, stopChannels } from './helpers';

/**
 * The live rewind window, the linger and the behind-live grace through nginx
 * (Phase 4a-3, spec D14-D16, rulings R82 and R86), at the SHIPPED DEFAULTS: a
 * 60-minute window, a 300 s linger and a 10 s behind-live grace, none of which
 * this file changes.
 *
 * `rate: 1` on every scenario: the output is RE-ENCODED, so a faster-than-real-time
 * provider would measure the encoder's backlog rather than the product. What this
 * file cannot reach is pinned in Go with an injected clock and an injected
 * filesystem: the depth sweep and its 22 s retention, the cap's eviction order, a
 * read racing an eviction and every disk failure. Every test ends by `DELETE`ing
 * the sessions it opened and stopping the channels it tuned, so no 300 s linger
 * encodes behind the next test.
 */

const tune = (uuid: string): string => `/proxy/ts/stream/${uuid}?output_format=hls`;

// Timeouts are generous and never gates: a cold software start of the encoder on a
// shared runner is the slow part.
const SEGMENTS_TIMEOUT_MS = 60_000;

async function hlsChannel(upstream: UpstreamClient, seed: Seeder, api: ApiClient, name: string) {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name, tvgId: `${name.toLowerCase().replace(/\W+/g, '-')}.e2e`, logo: null, asset: 'mpeg2-576i-mp2' }],
    rate: 1,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });
  return channel;
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

test(
  'the media playlist spans the rewind window beyond the in-memory live edge',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(300_000);
    const channel = await hlsChannel(upstream, seed, api, 'HLS Rewind');
    const entry = await enterHls(request, tune(channel.uuid));
    try {
      // More than the store's 21 in memory: only the window's playlist lists them all.
      const playlist = await waitForSegments(request, entry.token, 'video', 25, 180_000);
      expect(playlist.mediaSequence, 'the window still lists its first segment').toBe(0);
      expect(playlist.segments.length).toBeGreaterThanOrEqual(25);
      expect(playlist.text, 'a live window is not a VOD or EVENT playlist').not.toContain('EXT-X-PLAYLIST-TYPE');

      // The PDTs rise by each EXTINF, to within one frame (the window is one timeline).
      const frameMs = 1000 / Number(entry.multivariant.variants[0].frameRate ?? '25');
      for (let i = 1; i < playlist.segments.length; i++) {
        const before = playlist.segments[i - 1];
        const rise = Date.parse(playlist.segments[i].programDateTime ?? '') - Date.parse(before.programDateTime ?? '');
        expect(Math.abs(rise - before.duration * 1000), `segment ${before.seq}'s PDT to the next`).toBeLessThanOrEqual(frameMs + 2);
      }

      // Segment 0, older than the store's newest 21, is fetched from the disk and parses.
      const initUri = playlist.segments[0].map;
      expect(initUri, 'the playlist opens with an EXT-X-MAP').toBeDefined();
      const initResponse = await request.get(`/hls/${entry.token}/${initUri}`);
      expect(initResponse.status()).toBe(200);
      const initBytes = Buffer.from(await initResponse.body());
      expect(topLevelBoxes(initBytes)).toContain('moov');
      const init = initSummary(initBytes);
      const first = await request.get(`/hls/${entry.token}/${playlist.segments[0].uri}`);
      expect(first.status(), 'segment 0, from the window').toBe(200);
      const bytes = Buffer.from(await first.body());
      expect(topLevelBoxes(bytes), 'segment 0 is one fragment').toEqual(['moof', 'mdat']);
      const timing = fragmentTiming(bytes, init);
      expect(timing.durations.length, 'segment 0 carries samples').toBeGreaterThan(0);
    } finally {
      await leaveHls(request, entry.token);
      await stopChannels(api, channel.uuid);
    }
  }
);

test(
  'a lingering window gives its slot to a blocked tune at once',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(240_000);
    const { a, b } = await slotCappedChannels(upstream, seed, api, seed.generatedName('linger-slot'));

    const tokens: string[] = [];
    try {
      const entryA = await enterHls(request, tune(a.uuid));
      tokens.push(entryA.token);
      await waitForSegments(request, entryA.token, 'video', 1, SEGMENTS_TIMEOUT_MS);
      expect(await leaveHls(request, entryA.token)).toBe(204);

      // A keeps running with no client, and says so.
      const lingering = await readChannelStatus(api, a.uuid);
      expect(lingering.client_count, 'a lingering channel has no client').toBe(0);
      expect(typeof lingering.lingering_since, 'the status names the linger').toBe('number');

      // B's blocked tune reclaims it.
      const entryB = await enterHls(request, tune(b.uuid));
      tokens.push(entryB.token);
      await waitForSegments(request, entryB.token, 'video', 1, SEGMENTS_TIMEOUT_MS);

      await expect
        .poll(async () => (await api.get(`/proxy/ts/status/${a.uuid}`)).status(), { timeout: 10_000, intervals: [500] })
        .toBe(404);
    } finally {
      for (const token of tokens) await leaveHls(request, token);
      await stopChannels(api, a.uuid, b.uuid);
    }
  }
);

/** The listed segment `back` places behind the newest, as a path under the session. */
function olderSegment(playlist: { segments: { uri: string }[] }, back: number): string {
  return playlist.segments[playlist.segments.length - 1 - back].uri;
}

test(
  'a behind-live viewer that leaves is reclaimable at once',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(240_000);
    const { a, b } = await slotCappedChannels(upstream, seed, api, seed.generatedName('behind-leave'));

    const tokens: string[] = [];
    try {
      const entryA = await enterHls(request, tune(a.uuid));
      tokens.push(entryA.token);
      const playlist = await waitForSegments(request, entryA.token, 'video', 9, SEGMENTS_TIMEOUT_MS);
      // Seven segments back is 14 s behind the newest: more than 5 x TARGETDURATION.
      const old = await request.get(`/hls/${entryA.token}/${olderSegment(playlist, 7)}`);
      expect(old.status()).toBe(200);
      expect(await leaveHls(request, entryA.token)).toBe(204);

      // An explicit leave has no grace (R25): B is served at once.
      const entryB = await enterHls(request, tune(b.uuid));
      tokens.push(entryB.token);
      const served = await waitForSegments(request, entryB.token, 'video', 1, SEGMENTS_TIMEOUT_MS);
      expect(served.segments.length).toBeGreaterThanOrEqual(1);
    } finally {
      for (const token of tokens) await leaveHls(request, token);
      await stopChannels(api, a.uuid, b.uuid);
    }
  }
);

test(
  'a behind-live viewer that goes silent holds its slot for the grace',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(300_000);
    const { a, b } = await slotCappedChannels(upstream, seed, api, seed.generatedName('behind-silent'));

    const tokens: string[] = [];
    try {
      const entryA = await enterHls(request, tune(a.uuid));
      tokens.push(entryA.token);
      const playlist = await waitForSegments(request, entryA.token, 'video', 9, SEGMENTS_TIMEOUT_MS);
      const old = await request.get(`/hls/${entryA.token}/${olderSegment(playlist, 7)}`);
      expect(old.status()).toBe(200);
      // A's last request has ended. It sends nothing more: no reload, no leave.
      const lastRequest = Date.now();

      // 5 s on: past 2 x TARGETDURATION (4 s), inside the 10 s grace.
      await sleep(Math.max(0, lastRequest + 5_000 - Date.now()));
      const refused = await request.get(tune(b.uuid), { timeout: 60_000 });
      expect(refused.status(), "B is refused while A's grace runs").toBe(503);
      expect(await refused.text()).toContain('no source available');

      // 16 s on (2 x TARGETDURATION + the 10 s grace + 2 s): B is served, A is gone. This
      // waits past the 12 s idle timeout by construction, because the grace ends at 14 s;
      // R24's rule is about zaps, not about this.
      await sleep(Math.max(0, lastRequest + 16_000 - Date.now()));
      const entryB = await enterHls(request, tune(b.uuid));
      tokens.push(entryB.token);
      const served = await waitForSegments(request, entryB.token, 'video', 1, SEGMENTS_TIMEOUT_MS);
      expect(served.segments.length).toBeGreaterThanOrEqual(1);

      const gone = await request.get(`/hls/${entryA.token}/video.m3u8`);
      expect(gone.status(), "the reclaimed session's next request").toBe(410);
    } finally {
      for (const token of tokens) await leaveHls(request, token);
      await stopChannels(api, a.uuid, b.uuid);
    }
  }
);
