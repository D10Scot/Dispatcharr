import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import type { ApiClient, Seeder, UpstreamClient } from '../../fixtures';
import { enterHls, leaveHls } from '../../fixtures/hls';
import { lockedProfile, stopChannels } from './helpers';

/**
 * The media-session token's lifecycle from outside the container (Phase 4a-1b,
 * spec D4/D5, § Presence and lifecycle).
 *
 * What is NOT here, on purpose: the idle departure, the resume and the
 * sweeper. They are pinned in Go with an injected clock, because an E2E that
 * waited out `max(12 s, 6 x TARGETDURATION)` would measure the wait, and the
 * spec's ruling R24 has the leave, not the timeout, as the product's contract.
 */

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

const tune = (uuid: string): string => `/proxy/ts/stream/${uuid}?output_format=hls`;

/** The same token with its last character changed: a MAC that no longer verifies. */
function tampered(token: string): string {
  return token.slice(0, -1) + (token.endsWith('A') ? 'B' : 'A');
}

test(
  'a tampered token, a left session and a stopped client are refused',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const channel = await hlsChannel(upstream, seed, api, 'HLS Refusals');

    // A tampered MAC is 403 before any table lookup.
    const first = await enterHls(request, tune(channel.uuid));
    try {
      expect((await request.get(`/hls/${tampered(first.token)}/video.m3u8`)).status()).toBe(403);
      // The genuine token still works: the refusal was the tampering's.
      expect([200, 503]).toContain((await request.get(`/hls/${first.token}/video.m3u8`)).status());
    } finally {
      // A left session is refused 403 from then on.
      expect(await leaveHls(request, first.token)).toBe(204);
      await stopChannels(api, channel.uuid);
    }
    expect((await request.get(`/hls/${first.token}/video.m3u8`)).status()).toBe(403);

    // A client stopped through the admin route ends its session.
    const second = await enterHls(request, tune(channel.uuid));
    try {
      const clients = (await readChannelStatus(api, channel.uuid)).clients.filter((c) => c.output_format === 'hls');
      expect(clients, 'the one live hls client').toHaveLength(1);
      const stopped = await api.post(`/proxy/ts/stop_client/${channel.uuid}`, { client_id: clients[0].client_id });
      expect(stopped.status()).toBe(200);
      expect((await request.get(`/hls/${second.token}/video.m3u8`)).status()).toBe(403);
    } finally {
      await leaveHls(request, second.token);
      await stopChannels(api, channel.uuid);
    }
  }
);

test(
  'a session on a stopped channel is refused 410 once and 403 after',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    const channel = await hlsChannel(upstream, seed, api, 'HLS Stopped');
    const entry = await enterHls(request, tune(channel.uuid));
    try {
      const stop = await api.post(`/proxy/ts/stop/${channel.uuid}`, {});
      expect(stop.status()).toBe(200);

      const gone = await request.get(`/hls/${entry.token}/video.m3u8`);
      expect(gone.status(), 'the one 410').toBe(410);
      expect(await gone.json()).toEqual({ error: 'channel stopped' });
      expect((await request.get(`/hls/${entry.token}/video.m3u8`)).status(), 'then 403').toBe(403);
    } finally {
      // A session already forgotten is still a 204: the leave is idempotent.
      expect(await leaveHls(request, entry.token)).toBe(204);
      await stopChannels(api, channel.uuid);
    }
  }
);

test(
  'an hls client is listed while it plays and leaves at once on DELETE',
  { tag: '@contract' },
  async ({ upstream, seed, api, request, streamClient }) => {
    const channel = await hlsChannel(upstream, seed, api, 'HLS Presence');

    try {
      // A TS client keeps the channel up; the HLS session joins it.
      await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
      expectTsAligned(await streamClient.readPackets(20));
      const entry = await enterHls(request, tune(channel.uuid));

      const while_ = await readChannelStatus(api, channel.uuid);
      expect(while_.clients.map((c) => c.output_format).sort(), 'both viewers are listed').toEqual(['hls', 'mpegts']);

      expect(await leaveHls(request, entry.token)).toBe(204);
      // The very next read: the leave answered only after its side effects, so
      // no wait for the idle timeout (R24).
      const after = await readChannelStatus(api, channel.uuid);
      expect(after.clients.map((c) => c.output_format), 'only the TS client remains').toEqual(['mpegts']);
      await streamClient.close();
    } finally {
      await stopChannels(api, channel.uuid);
    }
  }
);
