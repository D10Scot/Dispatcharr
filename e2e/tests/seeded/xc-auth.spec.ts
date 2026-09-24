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
 * `xc_username` custom property anywhere in the product. `xc_get_user`
 * (`apps/output/views.py`) delegates the lookup and the credential compare
 * to `apps.proxy.authorize.resolve_xc_user` — the same constant-time check
 * every streaming surface uses (the live tune's `authorize_stream`, catch-up)
 * — so an unknown username and a wrong password are indistinguishable (#84,
 * fixed by #395): no `get_object_or_404` runs first.
 */

test('player_api.php returns a user_info / server_info envelope for valid credentials', { tag: '@contract' }, async ({
  seed,
  request,
  baseURL,
}) => {
  // stream_limit is seeded explicitly rather than left to its default so
  // max_connections has a knowable, per-user value: with no stream_limit,
  // xc_get_info (apps/output/views.py:416-421) falls back to
  // calculate_tuner_count(minimum=1, ...), an instance-wide accumulating
  // count floored at 1 that four workers share and that a past task found
  // sitting well above zero from other workers' residue — so `> 0` there
  // can never fail and proves nothing. stream_limit is the per-user branch
  // of the same code, and it IS what this test means to exercise.
  const user = await seed.xcUser({ stream_limit: 3 });

  const res = await request.get(`/player_api.php${xcQuery(user)}`);
  expect(res.status()).toBe(200);

  const body = await res.json();
  expect(body.user_info).toMatchObject({
    // `username` is echoed straight off `request.GET.get("username")` by
    // xc_get_info — it proves the query-string encoding round-tripped, NOT
    // that the account resolved. `auth: 1` and `status: 'Active'` are what
    // prove that; don't read more into the username match than it shows.
    //
    // `user_info.password` (not asserted here) likewise echoes the
    // plaintext password straight back — that is Xtream Codes protocol
    // behaviour, not a leak: the caller supplied that same password in the
    // query string of the very request being answered, so the response
    // discloses nothing the requester didn't already send.
    username: user.username,
    message: 'Dispatcharr XC API',
    auth: 1,
    status: 'Active',
    // max_connections is a string in the envelope, not a number.
    max_connections: '3',
    allowed_output_formats: ['ts', 'mp4'],
  });

  // server_info.timezone is what XC clients use to interpret every EPG
  // timestamp, and _build_xc_server_info pins it to UTC deliberately (a
  // mis-set Docker /etc/timezone would otherwise shift the whole guide).
  // url/server_protocol/port are all derived from the request's own Host
  // header (get_host_and_port falls back to it — see output-m3u.spec.ts),
  // which for a `request.get` against `baseURL` is `baseURL` itself, so
  // deriving the expected values from `baseURL` here is correct and
  // portable across stacks rather than a hard-coded guess.
  const origin = new URL(baseURL!);
  const expectedPort =
    origin.port || (origin.protocol === 'https:' ? '443' : '80');
  expect(body.server_info).toMatchObject({
    url: origin.hostname,
    server_protocol: origin.protocol.replace(':', ''),
    port: expectedPort,
    timezone: 'UTC',
    process: true,
  });

  // Arrives as a JSON number already, so no Number() wrap is needed. A
  // wide window (minutes, not seconds) avoids flaking on clock skew
  // between the container and the host running the test.
  const nowSeconds = Date.now() / 1000;
  expect(body.server_info.timestamp_now).toBeGreaterThan(nowSeconds - 300);
  expect(body.server_info.timestamp_now).toBeLessThan(nowSeconds + 300);
});

test('player_api.php answers an unknown action with the same envelope', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  // xc_player_api falls through to xc_get_info for anything it does not
  // recognise, including get_account_info. That is deliberate
  // provider-compatibility behaviour, not an oversight, so it is pinned.
  //
  // Asserts both halves of the envelope, not just user_info.auth: a
  // stripped response missing server_info entirely would still satisfy a
  // single auth check while contradicting this test's own name.
  const user = await seed.xcUser();
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'no_such_action' })}`
  );
  expect(res.status()).toBe(200);

  const body = await res.json();
  expect(body.user_info).toMatchObject({ auth: 1, status: 'Active' });
  expect(body.server_info.timezone).toBe('UTC');
});

test('player_api.php rejects a wrong password', { tag: '@contract' }, async ({ seed, request }) => {
  const user = await seed.xcUser();

  // Driven through `request`, not `api`: ApiClient retries once through a
  // token refresh on ANY 401, which would spend a refresh and could throw
  // instead of returning the 401 this test exists to assert.
  const res = await request.get(
    `/player_api.php?username=${encodeURIComponent(user.username)}&password=wrong`
  );
  expect(res.status()).toBe(401);
});

test('player_api.php rejects a user with no xc_password at all', { tag: '@contract' }, async ({
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

// Fixed (#84). `xc_authenticate` now delegates the credential check to
// `apps.proxy.authorize.resolve_xc_user`, which returns None for an unknown
// username, a missing xc_password, or a wrong one alike — no
// `get_object_or_404` lookup runs first, so an unknown username no longer
// escapes as an Http404. An unauthenticated caller cannot tell "no such
// account" from "wrong password" by status code alone.
test('player_api.php answers an unknown user and a wrong password identically', { tag: '@contract' }, async ({
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
