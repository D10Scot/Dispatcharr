import { test, expect, StreamStatusError } from '../../fixtures';
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
    // Two layers are under test at once. The marker is an HMAC of
    // SECRET_KEY, so a guessed value cannot match; and nginx overrides
    // every one of these five params in every relay-bound location, so
    // even a correct guess would be discarded before the relay saw it.
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
