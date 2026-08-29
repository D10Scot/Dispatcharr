import { test, expect } from '../../fixtures';
import { catchupTimestamp, seedCatchupChannel } from './helpers';

/**
 * Drives `/proxy/catchup/<Channel.uuid>` — the **native** catch-up surface
 * (spec inventory row 5), not the root `/timeshift/...` XC route
 * `catchup-path-layout.spec.ts` already covers. Both routes end up in the
 * same shared `_serve_catchup` (apps/timeshift/views.py), which is what
 * calls `build_timeshift_candidate_urls` and runs the seven-candidate
 * cascade under test here — so the cascade behaviour itself does not differ
 * by entry point, and driving it from the native surface is what proves
 * that surface is wired end to end rather than leaving it completely
 * unexercised by this goal.
 *
 * Authenticated with the admin JWT `api` fixture already holds, not an XC
 * end-user: the native route's `authentication_classes` are
 * JWTAuthentication/ApiKeyAuthentication/QueryParamJWTAuthentication, not
 * `_authenticate_user`'s XC username/password, so no `seed.xcUser()`
 * stand-in is needed for this proof at all.
 */
test('the candidate cascade falls through to the QUERY layout when PATH 404s', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  // A FRESH account, deliberately: _set_cached_format_index caches the
  // winning candidate index per account in the Django cache, and a reused
  // account would start the walk at whatever last worked rather than at
  // candidate 0.
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });

  await upstream.fault(scenario, 'catchup-layout-404', { layout: 'path' });

  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const token = await api.freshAccessToken();

  // ?start=&duration= is the native route's own direct-auth shape
  // (apps/timeshift/views.py's catchup_proxy docstring); duration goes
  // through the identical client_duration_to_window() as the PATH route's
  // URL segment, so the same +5-minute buffer assertion below is valid here
  // too. Like the PATH route, a session-less first request gets a
  // same-origin 301 minting a session_id, which streamClient.open follows
  // automatically.
  await streamClient.open(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expect((await streamClient.readPackets(20))[0]).toBe(0x47);
  await streamClient.close();

  const log = await upstream.log(scenario);
  const attempts = log.filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('timeshift')
  );

  // build_timeshift_candidate_urls emits three PATH shapes, then four QUERY
  // shapes. With PATH blocked, a correct cascade shows all three PATH
  // attempts 404 and then a QUERY attempt succeed.
  const pathAttempts = attempts.filter((e) => e.path!.includes('/timeshift/'));
  const queryAttempts = attempts.filter((e) => e.path!.includes('timeshift.php'));

  expect(pathAttempts).toHaveLength(3);
  expect(pathAttempts.every((e) => e.status === 404)).toBe(true);
  expect(queryAttempts.length).toBeGreaterThan(0);
  expect(queryAttempts[0].status).toBe(200);
  // The QUERY attempt carried the same parameters the PATH ones did.
  expect(queryAttempts[0].path).toContain(`username=${scenario.username}`);
  expect(queryAttempts[0].path).toContain('duration=65');
});
