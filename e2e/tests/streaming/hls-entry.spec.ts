import { test, expect, parseM3u, readChannelStatus, xcQuery } from '../../fixtures';
import { MEDIA_SESSION_TOKEN_RE, enterHls, leaveHls } from '../../fixtures/hls';
import { lockedProfile } from './helpers';

/**
 * The live HLS output's entry (Phase 4a-1b, spec D2/D3/D13/D19), through
 * nginx.
 *
 * `rate: 1` on every scenario here and in the sibling HLS specs: the output is
 * RE-ENCODED, so a faster-than-real-time provider would measure the encoder's
 * backlog rather than the product.
 *
 * Every test ends by `DELETE`ing the sessions it opened: the leave stops a
 * channel that has no other client, which frees the provider slot for the next
 * test on the same worker.
 */

test(
  'an hls tune answers a multivariant playlist on all three entry forms',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'HLS Entry', tvgId: 'hls-entry.e2e', logo: null, asset: 'mpeg2-576i-mp2' }],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const xc = await seed.xcUser({ user_level: 1 });

    const forms = [
      `/proxy/ts/stream/${channel.uuid}?output_format=hls`,
      `/live/${xc.username}/${xc.xcPassword}/${channel.id}.m3u8`,
      `/${xc.username}/${xc.xcPassword}/${channel.id}.m3u8`,
    ];
    const tokens: string[] = [];
    try {
      for (const form of forms) {
        const entry = await enterHls(request, form);
        expect(entry.headers['content-type'], form).toBe('application/vnd.apple.mpegurl');
        expect(entry.headers['cache-control'], form).toBe('no-store');
        expect(entry.multivariant.text, form).toContain('#EXT-X-STREAM-INF');
        expect(entry.multivariant.uris.length, form).toBeGreaterThan(0);
        for (const uri of entry.multivariant.uris) {
          expect(uri, `every URI in ${form}'s multivariant is under its own session`).toMatch(
            new RegExp(`^/hls/${entry.token}/`)
          );
        }
        expect(entry.token, form).toMatch(MEDIA_SESSION_TOKEN_RE);
        tokens.push(entry.token);
      }
      // A fresh token per entry.
      expect(new Set(tokens).size).toBe(3);

      const status = await readChannelStatus(api, channel.uuid);
      const hlsClients = status.clients.filter((c) => c.output_format === 'hls');
      expect(hlsClients, 'the channel lists one hls client per session').toHaveLength(3);
    } finally {
      for (const token of tokens) await leaveHls(request, token);
    }
  }
);

test(
  'a Redirect-profile channel is served over HLS through the relay',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'HLS Redirect', tvgId: 'hls-redirect.e2e', logo: null, asset: 'mpeg2-576i-mp2' }],
      rate: 1,
    });
    const redirect = await lockedProfile(api, 'Redirect');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: redirect.id,
    });

    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      expect(entry.multivariant.text).toContain('#EXT-X-STREAM-INF');
      // A 302 to the provider would have left the provider's log empty; here
      // the relay itself read the stream.
      const opens = (await upstream.log(scenario)).filter((e) => e.kind === 'open' && e.channelId === 1);
      expect(opens.length, "the provider's log shows the relay's own connection").toBeGreaterThanOrEqual(1);
    } finally {
      await leaveHls(request, entry.token);
    }
  }
);

test(
  'the Xtream API advertises m3u8 and get.php emits .m3u8 stream URLs',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'HLS Xtream', tvgId: 'hls-xtream.e2e', logo: null }],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const xc = await seed.xcUser({ user_level: 1 });

    const handshake = await request.get(`/player_api.php${xcQuery(xc)}`);
    expect(handshake.status()).toBe(200);
    const body = (await handshake.json()) as { user_info: { allowed_output_formats: string[] } };
    expect(body.user_info.allowed_output_formats).toContain('m3u8');

    // A unique query keeps this fetch off any other worker's cached playlist.
    const bust = Math.random().toString(36).slice(2);
    const playlist = await request.get(`/get.php${xcQuery(xc, { type: 'm3u_plus', output: 'm3u8', e2e: bust })}`);
    expect(playlist.status()).toBe(200);
    const mine = parseM3u(await playlist.text()).entries.find((e) => e.attributes['tvg-name'] === channel.name);
    expect(mine, `${channel.name} should be in the playlist`).toBeDefined();
    expect(mine!.url).toMatch(new RegExp(`/live/[^/]+/[^/]+/${channel.id}\\.m3u8$`));
    expect(mine!.url).not.toContain('output_format');
  }
);

test(
  'the Mino capability document answers anonymously',
  { tag: '@contract' },
  async ({ request }) => {
    // No credential of any kind: the document is public by design.
    const response = await request.get('/api/mino/capabilities/');
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({
      product: 'mino',
      api_version: 1,
      server_version: expect.stringMatching(/^\d+\.\d+\.\d+/),
      live_hls: {
        available: true,
        segment_seconds: 2,
        session_leave: true,
        rewind_window: { available: false, depth_seconds: 0 },
      },
    });
  }
);
