import { test, expect, readChannelStatus } from '../../fixtures';
import { enterHls, initSummary, leaveHls, waitForSegments } from '../../fixtures/hls';
import { lockedProfile } from './helpers';

/**
 * The automatic HLS profile (Phase 4a-1d, spec D12, § Automatic generation): a
 * channel set to the locked "HLS (Automatic)" Output Profile copies what
 * AVPlayer accepts and encodes the rest. One codec fixture per test, each a
 * real run on the CI runner: the copies cost nothing, and the one encode is the
 * software encoder. A target duration above 2, the declared-family encode and
 * the over-long-segment rule are pinned in Go only, with in-test sources
 * (relay/hls/real_test.go, relay/hls/automatic_pipeline_test.go).
 */

test(
  'an automatic channel copies HEVC and declares hvc1',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'Automatic HEVC', tvgId: 'auto-hevc.e2e', logo: null, asset: 'hevc-aac' }],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const automatic = await seed.hlsOutputProfileByName('HLS (Automatic)');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      hlsOutputProfileId: automatic.id,
    });
    expect(channel.hls_output_profile_id, 'the channel carries the automatic profile').toBe(automatic.id);

    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      const { variants } = entry.multivariant;
      expect(variants.length).toBeGreaterThan(0);
      for (const variant of variants) {
        const [video, audio] = (variant.codecs ?? '').split(',');
        expect(video, 'the video CODECS is HEVC, tagged hvc1').toMatch(/^hvc1\./);
        expect(audio, 'the AAC is copied as mp4a.40.2').toBe('mp4a.40.2');
        expect(variant.resolution).toBe('640x360');
      }

      const playlist = await waitForSegments(request, entry.token, 'video', 1, 60_000);
      expect(playlist.targetDuration, 'a 2 s GOP keeps a target duration of 2').toBe(2);

      const status = await readChannelStatus(api, channel.uuid);
      expect(status.hls_encoder, 'the video is copied, not encoded').toBe('copy');
    } finally {
      await leaveHls(request, entry.token);
    }
  }
);

test(
  'an automatic channel copies H.264 and its init carries the source\'s own codec',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'Automatic H.264', tvgId: 'auto-h264.e2e', logo: null, asset: 'h264-eac3' }],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const automatic = await seed.hlsOutputProfileByName('HLS (Automatic)');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      hlsOutputProfileId: automatic.id,
    });

    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      const { media, variants } = entry.multivariant;
      expect(media.length, 'three audio groups, as in transcode').toBe(3);
      for (const variant of variants) {
        // The family's ceiling: High at level 4.2, whatever the source's own.
        expect((variant.codecs ?? '').split(',')[0]).toBe('avc1.64002a');
      }

      const playlist = await waitForSegments(request, entry.token, 'video', 1, 60_000);
      const initUri = playlist.segments[0].map;
      expect(initUri, 'the playlist opens with an EXT-X-MAP').toBeDefined();
      const initResponse = await request.get(`/hls/${entry.token}/${initUri}`);
      expect(initResponse.status()).toBe(200);
      const init = initSummary(Buffer.from(await initResponse.body()));
      expect(init.codec, 'the init carries the source\'s own High-family string').toMatch(/^avc1\.64/);
      expect(parseInt(init.codec.slice(-2), 16), 'at the source\'s own level, below the declared 4.2').toBeLessThan(0x2a);

      const status = await readChannelStatus(api, channel.uuid);
      expect(status.hls_encoder).toBe('copy');
    } finally {
      await leaveHls(request, entry.token);
    }
  }
);

test(
  'an automatic channel encodes a 10 s GOP',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'Automatic long GOP', tvgId: 'auto-gop10.e2e', logo: null, asset: 'h264-gop10-aac' }],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const automatic = await seed.hlsOutputProfileByName('HLS (Automatic)');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      hlsOutputProfileId: automatic.id,
    });

    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      for (const variant of entry.multivariant.variants) {
        expect((variant.codecs ?? '').split(',')[0]).toBe('avc1.64002a');
      }
      await waitForSegments(request, entry.token, 'video', 1, 60_000);
      const status = await readChannelStatus(api, channel.uuid);
      // CI's runner has no Quick Sync: a GOP over 6 s is encoded, in software.
      expect(status.hls_encoder).toBe('software');
    } finally {
      await leaveHls(request, entry.token);
    }
  }
);
