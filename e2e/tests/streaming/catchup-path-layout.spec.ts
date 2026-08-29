import { test, expect } from '../../fixtures';
import { catchupTimestamp, seedCatchupChannel } from './helpers';
import { seedXcUser } from '../seeded/helpers';

/**
 * Drives the root XC PATH catch-up route — `/timeshift/<user>/<pass>/
 * <duration>/<start>/<Channel.id>.ts` — the surface a real XC/IPTV client
 * hits, and the one the URL segments below (username, password, duration,
 * start) actually belong to. `catchup-cascade.spec.ts` takes the *other*
 * catch-up entry point, `/proxy/catchup/<uuid>`, so that surface is not left
 * completely unexercised by this goal either — see that file's header.
 */
test('a catch-up request reaches the provider in the PATH layout with the right parameters', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  const xcUser = await seedXcUser(seed);

  // Two hours ago, on a whole minute — the archive is not time-addressable,
  // so the instant is arbitrary; what matters is that the provider records
  // the one we asked for.
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  // The root XC PATH route: /timeshift/<user>/<pass>/<duration>/<start>/<Channel.id>.ts
  // Note Channel.id, the numeric PK — unlike every live_proxy endpoint, which
  // is keyed by the UUID. `streamClient.open` follows the 301 this route
  // mints a session_id with on a first, session-less request (fetch's
  // default redirect: 'follow'), so the immediate 200 stream below is really
  // the second, session-bound request — invisible here, but why no manual
  // redirect handling is needed the way `vod-byte-read.spec.ts` needs it for
  // an upstream (not same-origin) redirect.
  await streamClient.open(
    `/timeshift/${xcUser.username}/${xcUser.xcPassword}/60/${start}/${channel.id}.ts`
  );
  const bytes = await streamClient.readPackets(20);
  expect(bytes[0]).toBe(0x47);
  await streamClient.close();

  const log = await upstream.log(scenario);
  const asked = log.filter((entry) => entry.path?.includes('/timeshift/'));
  expect(asked.length).toBeGreaterThan(0);
  const path = asked[0].path!;

  expect(path).toContain(`/${scenario.username}/${scenario.password}/`);
  // 60 requested + DURATION_BUFFER_MINUTES (5). Assert the derived value,
  // not the client's own 60: the product pads every client hint because
  // provider archives lag live, and asserting 60 would pass even if the
  // buffer were silently dropped.
  expect(path).toContain('/65/');
  expect(path).toMatch(new RegExp(`/${providerStreamId}\\.ts$`));
  // Unchanged, because the provider declares server_info.timezone "UTC" and
  // convert_timestamp_to_provider_tz skips conversion for exactly that
  // value — seedCatchupChannel already waited for that to land.
  expect(path).toContain(start);
});
