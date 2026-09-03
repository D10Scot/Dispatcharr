import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';

// The non-inverted control for the test.fail() below ('refreshing a deleted
// user's token returns 401, not 500'): the premise that /api/accounts/token/
// refresh/ is a working route at all — a live user's refresh token is
// accepted and answered with a fresh access token. The pin below remains
// the only test in this file that calls this route with a *deleted* user's
// token, inside a test.fail() block — this control's own call, immediately
// above, uses a live user's token in a non-inverted body instead.
// A broken refresh endpoint (wrong status, no `access` in the body, a 500 on
// every input) would be swallowed by the pin below as an "expected
// failure", since test.fail() is satisfied by ANY failure in its body, not
// specifically the 401-vs-500 regression it exists to pin. `asPrincipal`
// costs no login — `standard`'s tokens are pre-minted by `bootstrap` — so
// this control keeps the file's login spend at the one the pin below still
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

// Asserts the behaviour Dispatcharr SHOULD have. A refresh token naming a
// user who has since been deleted gets a 500 from TokenRefreshView, not the
// 401 that would tell a client to log in again. Filed as
// https://github.com/D10Scot/Dispatcharr/issues/12.
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
// runs. So this pin's login can 429 on any CI run, not just an occasional
// local one. See "The login throttle" in e2e/README.md.
//
// test.fail() caveat: it is satisfied by ANY failure in the body, guards
// included — including the delete's own `toBe(204)` premise below and the
// seed-and-login machinery above it, neither of which the control above
// touches. The route premise IS now guarded: the non-inverted control above
// ('a live user's refresh token is accepted by /api/accounts/token/refresh/')
// already exercises that route and would go red on its own if a broken
// refresh endpoint were the cause, so a broken endpoint can no longer green
// this pin by accident. What remains unguarded is the seed-and-login half
// above, including that `toBe(204)` premise — a cold-run 429 from `asUser`
// reads as "expected failure" without ever reaching the refresh call this
// test exists to exercise, and that is a harness cost (the shared login
// throttle), not a product signal the control could meaningfully assert.
// Verified with `--reporter=json` that this pin fails at the `toBe(401)`
// below, with the premise `toBe(204)` passing — re-verify the same way
// after any edit here.
test.fail('refreshing a deleted user\'s token returns 401, not 500', { tag: '@contract' }, async ({
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
