import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';

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
// bootstrap can, so an occasional 429 here on a cold rerun is a harness cost,
// not a product failure. See "The login throttle" in e2e/README.md.
test.fail('refreshing a deleted user\'s token returns 401, not 500', async ({
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
