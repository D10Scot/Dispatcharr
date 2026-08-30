import { test, expect, xcQuery } from '../../fixtures';

/**
 * `player_api.php` — the Xtream Codes authentication handshake.
 *
 * Driven with the built-in `request` fixture everywhere, never `api`:
 * `ApiClient.send` retries once through a token refresh on ANY 401, which
 * would spend a pointless refresh here and could throw a refresh error
 * instead of returning the 401 these tests exist to assert.
 *
 * The XC username IS the Django username — there is no separate
 * `xc_username` custom property anywhere in the product. `xc_get_user`,
 * `stream_xc` and timeshift's `_authenticate_user` all resolve the account
 * with `get_object_or_404(User, username=…)` and then compare
 * `custom_properties["xc_password"]`.
 */

test('player_api.php returns a user_info / server_info envelope for valid credentials', async ({
  seed,
  request,
}) => {
  const user = await seed.xcUser();

  const res = await request.get(`/player_api.php${xcQuery(user)}`);
  expect(res.status()).toBe(200);

  const body = await res.json();
  expect(body.user_info).toMatchObject({
    username: user.username,
    auth: 1,
    status: 'Active',
  });
  expect(Number(body.user_info.max_connections)).toBeGreaterThan(0);
  expect(body.user_info.allowed_output_formats).toEqual(['ts', 'mp4']);

  // server_info.timezone is what XC clients use to interpret every EPG
  // timestamp, and _build_xc_server_info pins it to UTC deliberately (a
  // mis-set Docker /etc/timezone would otherwise shift the whole guide).
  expect(body.server_info.timezone).toBe('UTC');
  expect(body.server_info.port).toBeTruthy();
  expect(Number(body.server_info.timestamp_now)).toBeGreaterThan(0);
});

test('player_api.php answers an unknown action with the same envelope', async ({
  seed,
  request,
}) => {
  // xc_player_api falls through to xc_get_info for anything it does not
  // recognise, including get_account_info. That is deliberate
  // provider-compatibility behaviour, not an oversight, so it is pinned.
  const user = await seed.xcUser();
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'no_such_action' })}`
  );
  expect(res.status()).toBe(200);
  expect((await res.json()).user_info.auth).toBe(1);
});

test('player_api.php rejects a wrong password', async ({ seed, request }) => {
  const user = await seed.xcUser();

  // Driven through `request`, not `api`: ApiClient retries once through a
  // token refresh on ANY 401, which would spend a refresh and could throw
  // instead of returning the 401 this test exists to assert.
  const res = await request.get(
    `/player_api.php?username=${encodeURIComponent(user.username)}&password=wrong`
  );
  expect(res.status()).toBe(401);
});

test('player_api.php rejects a user with no xc_password at all', async ({
  seed,
  request,
}) => {
  // seed.user(), not seed.xcUser(): an ordinary account has no XC credential,
  // and xc_get_user returns None before it ever compares anything. This is
  // the path that keeps admin accounts off the XC surface.
  const plain = await seed.user();
  const res = await request.get(
    `/player_api.php?username=${encodeURIComponent(plain.username)}&password=anything`
  );
  expect(res.status()).toBe(401);
});

// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_user` returns None
// for a wrong password — which xc_player_api turns into 401 — but calls
// `get_object_or_404(User, username=…)` first, so an unknown username escapes
// as an Http404 and Django answers 404.
//
// An unauthenticated caller can therefore tell "no such account" from "wrong
// password" by status code alone, on an endpoint that takes credentials in a
// URL. Both failures should be indistinguishable.
//
// Found while specifying G5; it is not in the original brief. See D10 in the
// design doc.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/84
test.fail('player_api.php does not distinguish an unknown user from a wrong password', async ({
  seed,
  request,
}) => {
  const user = await seed.xcUser();

  const wrongPassword = await request.get(
    `/player_api.php?username=${encodeURIComponent(user.username)}&password=wrong`
  );
  const unknownUser = await request.get(
    `/player_api.php?username=${seed.generatedName('ghost')}&password=wrong`
  );

  expect(wrongPassword.status()).toBe(401);
  expect(
    unknownUser.status(),
    'an unknown username must not be distinguishable from a wrong password'
  ).toBe(401);
});
