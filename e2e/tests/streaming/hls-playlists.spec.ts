import { test, expect } from '../../fixtures';
import type { UpstreamAsset } from '../../fixtures/upstream';
import {
  enterHls,
  fragmentTiming,
  initSummary,
  leaveHls,
  parseMediaPlaylist,
  topLevelBoxes,
  waitForSegments,
} from '../../fixtures/hls';
import { lockedProfile } from './helpers';

/**
 * The multivariant and media playlists the live HLS output serves (Phase 4a-1b,
 * spec D7, § Session resources), one codec fixture at a time.
 *
 * Each fixture is a real re-encode on the CI runner's software encoder, so the
 * four multivariant checks run in series in ONE test rather than as four:
 * one channel and one entry each, released before the next opens, and nothing
 * here waits for more than the first init segments.
 */

interface Expectation {
  asset: UpstreamAsset;
  /** audio group -> the audio CODECS the multivariant pairs with the video's. */
  groups: Record<string, string>;
  resolution?: string;
  frameRate?: string;
  channels?: Record<string, string>;
}

const FIXTURES: Expectation[] = [
  {
    asset: 'h264-eac3',
    groups: { aac: 'mp4a.40.2', ac3: 'ac-3', eac3: 'ec-3' },
  },
  { asset: 'h264-noaudio', groups: { aac: 'mp4a.40.2' } },
  {
    asset: 'mpeg2-576i-mp2',
    groups: { aac: 'mp4a.40.2' },
    resolution: '720x576',
    frameRate: '50.000',
  },
  {
    asset: 'h264-1080i-aac-ac3',
    groups: { aac: 'mp4a.40.2', ac3: 'ac-3' },
    resolution: '1920x1080',
    frameRate: '50.000',
    channels: { ac3: '6' },
  },
];

test(
  'the multivariant declares the audio groups and codecs of each fixture',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const proxy = await lockedProfile(api, 'Proxy');
    for (const fixture of FIXTURES) {
      const scenario = await upstream.scenario({
        channels: [{ id: 1, name: `HLS ${fixture.asset}`, tvgId: `hls-${fixture.asset}.e2e`, logo: null, asset: fixture.asset }],
        rate: 1,
      });
      const { channel } = await seed.upstreamChannel(scenario, {
        channelIds: [1],
        streamProfileId: proxy.id,
      });
      const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
      try {
        const { media, variants } = entry.multivariant;
        const label = fixture.asset;

        expect(media.map((m) => m.groupId).sort(), `${label}: audio groups`).toEqual(Object.keys(fixture.groups).sort());
        expect(variants.length, `${label}: one variant per audio group`).toBe(media.length);
        for (const variant of variants) {
          const audioCodec = fixture.groups[variant.audio ?? ''];
          expect(audioCodec, `${label}: variant names a declared group`).toBeDefined();
          expect(variant.codecs, `${label}: CODECS`).toMatch(new RegExp(`^avc1\\.64002a,${audioCodec.replace('.', '\\.')}$`));
          if (fixture.resolution) expect(variant.resolution, `${label}: RESOLUTION`).toBe(fixture.resolution);
          if (fixture.frameRate) expect(variant.frameRate, `${label}: FRAME-RATE`).toBe(fixture.frameRate);
        }
        for (const [group, channels] of Object.entries(fixture.channels ?? {})) {
          expect(media.find((m) => m.groupId === group)?.channels, `${label}: CHANNELS of ${group}`).toBe(channels);
        }
      } finally {
        await leaveHls(request, entry.token);
      }
    }
  }
);

test(
  'a media playlist conforms and its init and segments parse',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'HLS Playlist', tvgId: 'hls-playlist.e2e', logo: null, asset: 'h264-eac3' }],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      const frameRate = Number(entry.multivariant.variants[0].frameRate ?? '25');
      const frame = 1 / frameRate;

      // At least 6 listed within 60 s (Apple 8.11).
      const first = await waitForSegments(request, entry.token, 'video', 6, 60_000);
      expect(first.version).toBe(7);
      expect(first.targetDuration).toBe(2);
      expect(first.independentSegments).toBe(true);
      expect(first.endlist, 'a live playlist never ends').toBe(false);
      expect(first.segments.length).toBeLessThanOrEqual(10);
      for (const segment of first.segments) {
        expect(segment.programDateTime, `segment ${segment.seq} carries EXT-X-PROGRAM-DATE-TIME`).toBeDefined();
      }

      // The media sequence advances between two reloads, with no gap.
      await new Promise((resolve) => setTimeout(resolve, 5_000));
      const second = await waitForSegments(request, entry.token, 'video', 6, 30_000);
      expect(second.mediaSequence).toBeGreaterThanOrEqual(first.mediaSequence);
      expect(second.mediaSequence, 'no gap between the two reloads').toBeLessThanOrEqual(
        first.mediaSequence + first.segments.length
      );
      expect(second.mediaSequence + second.segments.length, 'the live edge advanced').toBeGreaterThan(
        first.mediaSequence + first.segments.length
      );

      // The video init: a moov, no edit list.
      const initUri = second.segments[0].map;
      expect(initUri, 'the playlist opens with an EXT-X-MAP').toBeDefined();
      const initResponse = await request.get(`/hls/${entry.token}/${initUri}`);
      expect(initResponse.status()).toBe(200);
      const initBytes = Buffer.from(await initResponse.body());
      expect(topLevelBoxes(initBytes)).toContain('moov');
      const init = initSummary(initBytes);
      expect(init.handler).toBe('vide');
      expect(init.hasEdts, 'a served init has no edit list').toBe(false);

      // Two consecutive media segments: moof+mdat, each tfdt continuing the
      // previous, each duration within one frame of its EXTINF.
      const [one, two] = second.segments.slice(-3, -1);
      const timings = [];
      for (const segment of [one, two]) {
        const response = await request.get(`/hls/${entry.token}/${segment.uri}`);
        expect(response.status(), segment.uri).toBe(200);
        const bytes = Buffer.from(await response.body());
        expect(topLevelBoxes(bytes), `${segment.uri} is one fragment`).toEqual(['moof', 'mdat']);
        const timing = fragmentTiming(bytes, init);
        const seconds = timing.durations.reduce((a, b) => a + b, 0) / init.timescale;
        expect(Math.abs(seconds - segment.duration), `${segment.uri}: duration against its EXTINF`).toBeLessThanOrEqual(frame + 0.001);
        timings.push(timing);
      }
      expect(one.seq + 1).toBe(two.seq);
      expect(timings[1].tfdt, 'the second segment continues the first').toBe(
        timings[0].tfdt + timings[0].durations.reduce((a, b) => a + b, 0)
      );

      // The aac rendition lists the same sequence numbers.
      const aacResponse = await request.get(`/hls/${entry.token}/aac.m3u8`);
      expect(aacResponse.status()).toBe(200);
      const aac = parseMediaPlaylist(await aacResponse.text());
      const videoSeqs = new Set(second.segments.map((s) => s.seq));
      const common = aac.segments.filter((s) => videoSeqs.has(s.seq));
      expect(common.length, 'the two renditions share their sequence numbers').toBeGreaterThanOrEqual(5);
      for (const segment of aac.segments) expect(segment.uri).toBe(`aac/${segment.seq}.m4s`);
    } finally {
      await leaveHls(request, entry.token);
    }
  }
);
