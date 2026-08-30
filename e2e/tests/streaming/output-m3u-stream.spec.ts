import { test, expect, expectTsAligned, parseM3u, TS_PACKET_SIZE } from '../../fixtures';
import { lockedProfile } from './helpers';

/**
 * ONE URL, not all of them. Streaming n URLs costs n upstream connections and
 * proves nothing the first did not: every entry in the playlist is rendered
 * by the same f-string over the same queryset, so if one resolves and
 * delivers, the construction is right. output-m3u.spec.ts validates the rest
 * structurally.
 *
 * This test is what turns that structural check into a claim about the
 * product: the URL is taken VERBATIM out of the playlist and handed to a
 * client, with nothing reconstructed. A test that rebuilt the URL from
 * `channel.uuid` would pass even if the playlist emitted a wrong one.
 *
 * The URL is opened exactly as emitted, no rewrite. R14 (which would have
 * required rewriting the origin before fetching) was withdrawn — verified
 * that `nginx.conf`'s `location /` is a `uwsgi_pass`, while `X-Forwarded-*`
 * is set via `proxy_set_header`, which only applies to `proxy_pass`; Django
 * never sees those headers and falls back to the client's own `Host`, so the
 * emitted origin equals `baseURL` exactly. See issue #81.
 */
test('a URL taken verbatim from /output/m3u delivers aligned TS', async ({
  upstream,
  seed,
  api,
  request,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G5 Output', tvgId: 'g5-output.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  // Cache-busting: /output/m3u's anonymous content cache key includes the
  // raw query string with a 2-second TTL (apps/output/views.py:128,336), so
  // two anonymous fetches within that window under parallel workers can
  // share a stale body. A unique ?e2e= param keeps this fetch off any other
  // worker's cached response.
  const bust = Math.random().toString(36).slice(2);
  const playlist = parseM3u(await (await request.get(`/output/m3u?e2e=${bust}`)).text());
  const mine = playlist.entries.find((e) => e.attributes['tvg-name'] === channel.name);
  expect(mine, `${channel.name} should be in the playlist`).toBeDefined();

  // StreamClient.open() accepts an absolute URL, so this is the playlist's
  // own string with no edit.
  await streamClient.open(mine!.url);
  const packets = await streamClient.readPackets(200);

  expect(packets.byteLength).toBe(200 * TS_PACKET_SIZE);
  expectTsAligned(packets);

  // Close before reading the log. Not because the log check needs it — it
  // filters `kind === 'open'`, which a still-open connection would not
  // affect — but because leaving a live upstream open past the end of the
  // assertions holds a provider slot for no reason. The `streamClient`
  // fixture's teardown closes unconditionally, so a forced abort above
  // cannot leak it either; this is tidiness, not correctness.
  await streamClient.close();

  const opens = (await upstream.log(scenario)).filter(
    (e) => e.kind === 'open' && e.channelId === 1
  );
  expect(opens).toHaveLength(1);
});
