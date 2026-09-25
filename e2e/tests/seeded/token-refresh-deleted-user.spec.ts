import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';

// The control for the test below ('refreshing a deleted user's token
// returns 401, not 500'): it proves /api/accounts/token/refresh/ is a
// working route at all — a live user's refresh token is accepted and
// answered with a fresh access token. The test below is the only one in
// this file that calls this route with a *deleted* user's token; this
// control's own call, immediately above, uses a live user's token instead.
// Without this control, a broken refresh endpoint (wrong status, no
// `access` in the body, a 500 on every input) could fail the test below for
// the wrong reason. This control isolates the route itself as working, so
// the test below's 401 assertion is specifically about the deletion, not
// about the endpoint being broken in general. `asPrincipal` costs no
// login — `standard`'s tokens are pre-minted by `bootstrap` — so this
// control keeps the file's login spend at the one the test below still
// costs.
test('a live user\'s refresh token is accepted by /api/accounts/token/refresh/', { tag: '@contract' }, async ({
  asPrincipal,
  request,
}) => {
  const client = await asPrincipal('standard');
  const refresh = client.freshRefreshTokenForTest();

  const res = await request.post('/api/accounts/token/refresh/', {
    data: { refresh },
  });

  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(typeof body.access).toBe('string');
});

// Asserts the behaviour Dispatcharr now has, fixed by #12: a refresh token
// naming a user who has since been deleted gets a 401 `token_not_valid` from
// TokenRefreshView, the same response every other invalid refresh already
// gets, telling the client to log in again — not the 500 it used to. Filed
// as https://github.com/D10Scot/Dispatcharr/issues/12.
//
// **This test costs ONE login out of three per minute for the entire suite,
// and it is the only login G5 spends.** seed.user() generates a fresh
// username every call, so it is a guaranteed cache miss in asUser's per-worker
// token cache. Budget it at one per run. A run that is cold — the first after
// `--reset`, or with playwright/.auth/ deleted — has already spent the whole
// budget in bootstrap, and a worker cannot wait out a throttle window the way
// bootstrap can, so a 429 here on a cold run is a harness cost, not a
// product failure — and that is not a rare local artifact: CI is always
// cold. `.github/workflows/e2e-tests.yml`'s `test` job runs
// `./scripts/e2e_up.sh` fresh inside every matrix job, on a runner with no
// `playwright/.auth/` and no cache-restore step, and `setup/principals.ts`
// documents the cold bootstrap cost as "3, which is exactly the per-minute
// cap" — the whole budget spent before this test's own `asUser` login even
// runs. So this test's login can 429 on any CI run, not just an occasional
// local one. **Unlike before the #12 fix (#428), a 429 here now fails this
// test outright** — `asUser` throws on any non-OK login response
// (e2e/fixtures/auth.ts:115-124), where `test.fail()` used to absorb that
// throw as the "expected failure" regardless of cause. In the run that
// first exercised this test as a plain test() (36103684984, `seeded` job),
// this login landed about 69s after bootstrap's logins, well clear of the
// 3/minute window — but that margin comes from test/file execution order
// within the run, not from anything that bounds it, so it is not
// guaranteed to hold on every run. See "The login throttle" in
// e2e/README.md.
test('refreshing a deleted user\'s token returns 401, not 500', { tag: '@contract' }, async ({
  seed,
  api,
  asUser,
  request,
}) => {
  const user = await seed.user();
  const client = await asUser(user.username, SEEDED_USER_PASSWORD);
  const refresh = client.freshRefreshTokenForTest();

  expect((await api.delete(`/api/accounts/users/${user.id}/`)).status()).toBe(204);

  const res = await request.post('/api/accounts/token/refresh/', {
    data: { refresh },
  });

  expect(
    res.status(),
    'a refresh token naming a deleted user should be rejected, not crash'
  ).toBe(401);
});
