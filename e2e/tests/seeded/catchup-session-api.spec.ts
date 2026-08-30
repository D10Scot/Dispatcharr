import { test, expect } from '../../fixtures';
import { catchupTimestamp, seedCatchupChannel } from '../streaming/helpers';

/**
 * `POST /api/catchup/sessions/` — the surface the endpoint's own OpenAPI
 * description calls **recommended** for native players, and the fourth
 * entry point into the same `_serve_catchup` (`apps/timeshift/views.py:344`).
 * Until now nothing drove it: both G8 catch-up proofs and both root XC
 * routes reach `_serve_catchup` without ever minting a session
 * (`e2e/COVERAGE.md`'s Catch-up gap row).
 *
 * This file proves the mint contract. The playback half — opening the
 * returned `playback_url` with no Authorization header and reading TS bytes
 * — is `e2e/tests/streaming/catchup-proxy-mode.spec.ts`, because it needs a
 * live provider and the 300s `streaming` budget.
 *
 * Zero logins: the bootstrap admin is `user_level: 10`, which satisfies
 * `IsStandardUser` (`apps/accounts/permissions.py:15-20`), and
 * `asPrincipal('streamer')` hands back a pre-provisioned token pair.
 */
test('POST /api/catchup/sessions/ mints a playable session for a catch-up channel', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  const before = Math.floor(Date.now() / 1000);
  const res = await api.post('/api/catchup/sessions/', {
    channel_uuid: channel.uuid,
    start,
    duration: 60,
  });
  expect(res.status()).toBe(201);
  const body = await api.json<{
    session_id: string;
    playback_url: string;
    expires_at: number;
    channel_uuid: string;
    start: string;
    duration: number | null;
  }>(res, 'catch-up session');

  expect(body.session_id).toBeTruthy();
  // Asserted as one exact string, not by parts: this URL is the entire
  // contract with a native player, and `create_catchup_session` builds it by
  // interpolation (apps/timeshift/sessions.py:67), so a change to the route
  // or the parameter name would otherwise pass here and fail in the player.
  expect(body.playback_url).toBe(`/proxy/catchup/${channel.uuid}?session_id=${body.session_id}`);
  expect(body.channel_uuid).toBe(channel.uuid);
  expect(body.start).toBe(start);
  expect(body.duration).toBe(60);

  // HANDSHAKE_TTL_SECONDS is 60 (apps/timeshift/sessions.py:31). Bounded on
  // both sides: a floor alone would pass an `expires_at` of next year, which
  // would mean the handshake deadline the description advertises does not
  // exist.
  expect(body.expires_at).toBeGreaterThan(before);
  expect(body.expires_at).toBeLessThanOrEqual(before + 60 + 5);
});

test('POST /api/catchup/sessions/ refuses a channel with no catch-up', async ({ seed, api }) => {
  const plain = await seed.channel();

  const res = await api.post('/api/catchup/sessions/', {
    channel_uuid: plain.uuid,
    start: catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000)),
  });
  expect(res.status()).toBe(400);
  expect(await res.text()).toContain('Catch-up not supported for this channel');
});

test('POST /api/catchup/sessions/ is closed to a Streamer', async ({
  upstream,
  seed,
  api,
  waitFor,
  asPrincipal,
}) => {
  const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const streamer = await asPrincipal('streamer');

  // 403, not 401: the token is valid, `IsStandardUser` simply refuses a
  // user_level below 1 (apps/accounts/permissions.py:15-20), and DRF answers
  // an authenticated-but-unpermitted request with 403.
  const res = await streamer.post('/api/catchup/sessions/', {
    channel_uuid: channel.uuid,
    start: catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000)),
  });
  expect(res.status()).toBe(403);
});
