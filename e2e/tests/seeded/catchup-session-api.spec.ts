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
  // `session_id` here is the response's own value, so this half of the
  // comparison is an echo (see the note below) — this assertion's live
  // content is the `/proxy/catchup/<uuid>` route and `?session_id=` param
  // name, neither of which we supplied.
  expect(body.playback_url).toBe(`/proxy/catchup/${channel.uuid}?session_id=${body.session_id}`);
  // `channel_uuid`, `start` and `duration` below are pure echoes: each is a
  // value this test supplied in the request body, so a serializer that just
  // copied the request onto the response — persisting nothing — would pass
  // all three. They establish only that the request was parsed and echoed
  // back correctly, never that a session was actually stored; the DELETE
  // round-trip test below is what proves persistence.
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
  // The status alone doesn't attribute the refusal to `IsStandardUser` —
  // four distinct 403s exist on this path. DRF's default permission-denied
  // body (`BasePermission.message`, unset on `IsStandardUser`) names the
  // mechanism; this is the message the class actually raises, not one this
  // test constructed.
  expect(await res.text()).toContain('You do not have permission to perform this action');
});

/**
 * The tight boundary control for the Streamer-403 test above: `standard`
 * (user_level 1, the exact floor `IsStandardUser` checks) must succeed where
 * `streamer` (level 0) is refused. `admin` succeeding proves nothing about
 * where the line sits — it clears the boundary by ten levels and would still
 * pass even if `IsStandardUser` were accidentally relaxed to `IsAdmin` in
 * the wrong direction. This is a committed control, not a one-off mutation:
 * a mutation run once by the author and reverted protects nothing against a
 * future regression, while this test re-runs on every CI build.
 */
test('POST /api/catchup/sessions/ is open to a Standard user', async ({
  upstream,
  seed,
  api,
  waitFor,
  asPrincipal,
}) => {
  const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const standard = await asPrincipal('standard');

  const res = await standard.post('/api/catchup/sessions/', {
    channel_uuid: channel.uuid,
    start: catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000)),
  });
  expect(res.status()).toBe(201);
});

/**
 * Every assertion above this point is built from values the request itself
 * supplied or from the response's own `session_id` (the echoed-parameter
 * illusion) — so all of them would pass just as happily against an endpoint
 * that assembled a plausible 201 body and persisted nothing. `DELETE
 * /api/catchup/sessions/{id}/` is the only other surface that reads the
 * minted session back by id (`apps/timeshift/api_views.py:196-204`), so a
 * round trip through it is proof the session was actually stored, under
 * this id, owned by this caller:
 *   - deleting the real, just-minted id succeeds (204) — the session exists;
 *   - deleting it again 404s — it's actually gone, not merely "always ok";
 *   - deleting a fabricated id 404s with the same body — ownership/existence
 *     is checked, not merely acknowledged.
 * This never opens `playback_url` and stays well inside the 60s
 * `HANDSHAKE_TTL_SECONDS`.
 */
test('DELETE /api/catchup/sessions/{id}/ round-trips against a minted session', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const mint = await api.post('/api/catchup/sessions/', {
    channel_uuid: channel.uuid,
    start: catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000)),
  });
  expect(mint.status()).toBe(201);
  const { session_id } = await api.json<{ session_id: string }>(mint, 'catch-up session');

  const firstDelete = await api.delete(`/api/catchup/sessions/${session_id}/`);
  expect(firstDelete.status()).toBe(204);

  const secondDelete = await api.delete(`/api/catchup/sessions/${session_id}/`);
  expect(secondDelete.status()).toBe(404);
  expect(await secondDelete.text()).toContain('Session not found');

  const fabricatedDelete = await api.delete('/api/catchup/sessions/not-a-real-session-id/');
  expect(fabricatedDelete.status()).toBe(404);
  expect(await fabricatedDelete.text()).toContain('Session not found');
});
