import { randomUUID } from 'node:crypto';

import { test, expect, StreamStatusError, SEEDED_USER_PASSWORD } from '../../fixtures';
import type { Seeder } from '../../fixtures';
import { catchupTimestamp, lockedProfile, seedCatchupChannel } from './helpers';

/**
 * The authorize hop (Phase 1 PR 5, ADR 0005), from outside the container.
 *
 * Every relay-bound location issues `auth_request /_dispatcharr/authorize`
 * before a byte moves, so these tests exercise the same function the seven
 * stream views call inline — through nginx, which is the shape production
 * runs, and through the `error_page` mapping that puts back the statuses
 * nginx's auth_request module cannot carry.
 *
 * `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` pins the
 * config; this pins the behaviour. Neither substitutes for the other: a
 * correct location table with a broken decision passes there and fails
 * here.
 *
 * Every refusal below asserts an exact status. `>= 400` would pass on a
 * 400 from a malformed setup, a 404 from a channel that never seeded, or
 * a 500 from a broken hop — and a security contract that passes when the
 * fixture is broken proves nothing.
 */

test(
  'a channel hidden from output is refused even to an anonymous request',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'PR5 Hidden', tvgId: 'pr5-hidden.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      channel: { hidden_from_output: true },
    });

    // hidden_from_output is a property of the channel, so it needs no
    // principal — which is exactly why this row is the one that closes the
    // "unlistable yet streamable" gap for an anonymous caller holding a
    // UUID out of a stale playlist.
    await expectRefused(
      streamClient,
      `/proxy/ts/stream/${channel.uuid}`,
      403,
      'a hidden channel must not stream by UUID alone'
    );
  }
);

test(
  'an ordinary channel still streams with no credential at all',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient }) => {
    // The other half of the row above, and the reason ADR 0005 rejects
    // signed URLs: every cached playlist, tuner URL and third-party
    // integration points at a bare /proxy/ts/stream/<uuid>. If the hop
    // ever starts requiring a principal here, this fails loudly rather
    // than every user's playlist failing quietly.
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'PR5 Plain', tvgId: 'pr5-plain.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });

    await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
    const packets = await streamClient.readPackets(4);
    expect(packets[0]).toBe(0x47);
    expect(packets[188]).toBe(0x47);
    await streamClient.close();
  }
);

test(
  'a client-supplied trust marker does not authorize a hidden channel',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient }) => {
    // What this pins: a client-supplied marker cannot short-circuit the
    // hop. `resolve_authorization` does read these headers, but
    // `X-Dispatcharr-Authorized` is only trusted when it matches
    // `hmac.compare_digest(SECRET_KEY, "relay-trust")` — a forged value
    // fails that compare and falls through to the inline decision,
    // `authorize_stream`, which denies on `hidden_from_output` the same
    // as an unmarked request (unit:
    // apps/proxy/tests/test_authorize_view.py:229,
    // test_a_forged_marker_falls_through_to_the_inline_decision).
    //
    // What this does NOT pin: whether nginx would have discarded these
    // headers before the relay saw them at all — that depends on which
    // image is under test, not on this assertion. Through nginx
    // (CI's image), the `auth_request` subrequest denies the tune before
    // `uwsgi_pass` ever reaches this location, since the channel is
    // `hidden_from_output`, so the client's forged headers never reach a
    // view at all. Without nginx in front (an image predating 569d5b5f,
    // or any no-nginx deployment), the request reaches the inline path
    // directly and the forged `X-Dispatcharr-Authorized` fails the
    // constant-time compare there instead. Either path lands on the same
    // `authorize_stream` denial, which is what this test actually pins;
    // the `uwsgi_param` blanking layer on every relay-bound location is
    // pinned separately by nginx-stream-buffering.spec.ts.
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'PR5 Forge', tvgId: 'pr5-forge.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      channel: { hidden_from_output: true },
    });

    await expectRefused(
      streamClient,
      `/proxy/ts/stream/${channel.uuid}`,
      403,
      'a forged marker must not authorize anything',
      {
        'X-Dispatcharr-Authorized': '1',
        'X-Relay-Channel': channel.uuid,
        'X-Relay-User': '1',
      }
    );
  }
);

test(
  'a hidden channel is refused on the native catch-up route to a JWT viewer',
  { tag: '@contract' },
  async ({ upstream, seed, api, asPrincipal, streamClient }) => {
    // The native catch-up surface, /proxy/catchup/<uuid>, which no other
    // test in this file reaches: the flipped #95 pin drives the XC
    // timeshift root instead, and the two entry points share
    // _serve_catchup but not their prologues.
    //
    // The principal is the pre-provisioned `standard` roster entry
    // (user_level 1), whose access token `bootstrap` minted before any
    // worker started. asPrincipal is free; POST /api/accounts/token/
    // would spend one of the three logins the whole run is allowed.
    // Nothing here mutates the principal, which is what that roster
    // requires.
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'PR5 Catchup Hidden', tvgId: 'pr5-catchup-hidden.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      channel: { hidden_from_output: true },
    });

    const standard = await asPrincipal('standard');
    const token = await standard.freshAccessToken();
    const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

    // `start` is supplied so a 400 ("Missing start parameter") cannot be
    // mistaken for the refusal under test: the hop answers before the
    // view ever looks at it, so the only 403 available here is the
    // hop's.
    await expectRefused(
      streamClient,
      `/proxy/catchup/${channel.uuid}?token=${token}&start=${start}`,
      403,
      'a hidden channel must not serve its archive to a non-admin'
    );
  }
);

test(
  'a hidden channel is refused on the XC live root to an ordinary XC user',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient }) => {
    // hidden_from_output on an XC root form. The flipped #87 pin covers
    // is_adult on this same route, so between them both flags are
    // asserted on the XC live surface with a credentialed principal.
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'PR5 XC Hidden', tvgId: 'pr5-xc-hidden.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      channel: { hidden_from_output: true },
    });
    const viewer = await seed.xcUser({ user_level: 1 });

    await expectRefused(
      streamClient,
      `/live/${viewer.username}/${viewer.xcPassword}/${channel.id}`,
      403,
      'a hidden channel must not stream to an XC client'
    );
  }
);

test(
  'an adult channel is refused on the XC catch-up root to a hide_adult_content viewer',
  { tag: '@contract' },
  async ({ upstream, seed, api, waitFor, streamClient }) => {
    // Seeded through seedCatchupChannel, not seed.upstreamChannel with
    // is_catchup patched on: that helper exists because a Channel flagged
    // is_catchup with no catch-up-advertising Stream behind it has no
    // provider stream id for _prepare_catchup_stream_attempt, and the
    // request then fails with "Cannot build timeshift URL" (400) — which
    // an exact-403 assertion catches and a `>= 400` one would not.
    const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
    await api.patch(`/api/channels/channels/${channel.id}/`, { is_adult: true });
    const viewer = await seed.xcUser({
      user_level: 1,
      custom_properties: { hide_adult_content: true },
    });
    const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

    await expectRefused(
      streamClient,
      `/timeshift/${viewer.username}/${viewer.xcPassword}/60/${start}/${channel.id}.ts`,
      403,
      'an adult channel must not serve its archive to a filtered viewer'
    );
  }
);

/**
 * A single Standard-level user with `hide_adult_content` set, shared by the
 * two native-route `is_adult` tests below.
 *
 * Seeding is unthrottled (`seed.user()` is a plain POST), but minting a JWT
 * for it is not: `POST /api/accounts/token/` is capped at 3/minute for the
 * whole suite (e2e/README.md "The login throttle"), and the pre-provisioned
 * `standard`/`streamer` roster principals may not be mutated — a
 * `hide_adult_content` write on a shared row would corrupt any other test
 * driving it concurrently. `makeUserClient`'s own guidance is "budget it at
 * one per run"; memoizing the seed here and asking `asUser` for the exact
 * same credentials from both tests keeps this file's login cost at one,
 * since `fixtures/auth.ts`'s token cache is keyed on username+password and
 * both tests in this file run in the same worker (the `streaming` project
 * leaves `fullyParallel` at its inherited `false`, so one spec file never
 * splits across workers) — the second `asUser` call is a cache hit, not a
 * second login.
 */
let adultHiderCredentials: Promise<{ username: string; password: string }> | undefined;
function adultHiderUser(seed: Seeder): Promise<{ username: string; password: string }> {
  if (!adultHiderCredentials) {
    adultHiderCredentials = seed
      .user({ user_level: 1, custom_properties: { hide_adult_content: true } })
      .then((user) => ({ username: user.username, password: SEEDED_USER_PASSWORD }));
  }
  return adultHiderCredentials;
}

test(
  'an adult channel is refused on the native stream route to a hide_adult_content JWT viewer',
  { tag: '@contract' },
  async ({ upstream, seed, api, asUser, streamClient }) => {
    // The native counterpart to the XC-live is_adult row above (#87): the
    // spec (design.md:1353-1354) requires is_adult 403 on
    // /proxy/ts/stream/<uuid> as well as on the XC roots, and until this
    // test existed only the XC surfaces were covered.
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'PR5 Adult Native', tvgId: 'pr5-adult-native.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
      channel: { is_adult: true },
    });

    const { username, password } = await adultHiderUser(seed);
    const viewer = await asUser(username, password);
    const token = await viewer.freshAccessToken();

    await expectRefused(
      streamClient,
      `/proxy/ts/stream/${channel.uuid}?token=${token}`,
      403,
      'an adult channel must not stream to a hide_adult_content viewer by UUID'
    );
  }
);

test(
  'an adult channel is refused on the native catch-up route to a hide_adult_content JWT viewer',
  { tag: '@contract' },
  async ({ upstream, seed, api, waitFor, asUser, streamClient }) => {
    // The native counterpart to the XC-timeshift is_adult row above: same
    // spec requirement, /proxy/catchup/<uuid> instead of /proxy/ts/stream/.
    const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
    await api.patch(`/api/channels/channels/${channel.id}/`, { is_adult: true });

    const { username, password } = await adultHiderUser(seed);
    const viewer = await asUser(username, password);
    const token = await viewer.freshAccessToken();
    const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

    await expectRefused(
      streamClient,
      `/proxy/catchup/${channel.uuid}?token=${token}&start=${start}`,
      403,
      'an adult channel must not serve its archive to a hide_adult_content viewer'
    );
  }
);

test(
  'an unknown channel is refused as 404, not 500, through the hop',
  { tag: '@contract' },
  async ({ streamClient }) => {
    // I1 (final-review.md § 3): S7 collapses every hop-side 404/429 denial
    // to 403 + X-Authorize-Status precisely because
    // ngx_http_auth_request_module treats any other subrequest status as
    // an error and answers the client 500; error_page 403 =
    // @authorize_denied is what puts the real code back. Every other test
    // in this file asserts 403, so a config that dropped that mapping
    // entirely would still pass all of them — this is the one row that
    // actually exercises the restoration, on the one status a stale
    // playlist's unknown UUID must produce.
    await expectRefused(
      streamClient,
      `/proxy/ts/stream/${randomUUID()}`,
      404,
      'an unknown channel must be 404, not 500, through the hop'
    );
  }
);

test(
  'an unknown channel id on the XC live root is refused as 404, not 500, through the hop',
  { tag: '@contract' },
  async ({ seed, streamClient }) => {
    // The XC three-segment root form of the same I1 gap: a valid XC
    // principal but a channel id nothing resolves to.
    const viewer = await seed.xcUser({ user_level: 1 });

    await expectRefused(
      streamClient,
      `/live/${viewer.username}/${viewer.xcPassword}/999999999`,
      404,
      'an unknown channel id must be 404, not 500, through the hop'
    );
  }
);

/**
 * Open `path` and require an exact refusal status.
 *
 * Only a StreamStatusError of exactly `status` counts. A reset, a DNS
 * failure, a 500 or a different 4xx rethrows, so a broken fixture fails
 * the test instead of reading as "the product refused it" — the failure
 * mode that matters most in a file whose whole subject is refusals.
 */
async function expectRefused(
  streamClient: { open: (p: string, o?: { headers?: Record<string, string> }) => Promise<void>; close: () => Promise<void> },
  path: string,
  status: number,
  message: string,
  headers?: Record<string, string>
): Promise<void> {
  let refused = false;
  try {
    await streamClient.open(path, headers ? { headers } : {});
  } catch (error) {
    if (!(error instanceof StreamStatusError) || error.status !== status) throw error;
    refused = true;
  }
  try {
    expect(refused, message).toBe(true);
  } finally {
    // Abort whatever was opened, so a failing run does not leave an
    // upstream connection held for the rest of the project.
    await streamClient.close();
  }
}
