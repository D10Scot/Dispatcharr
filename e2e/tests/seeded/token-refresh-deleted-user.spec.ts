import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';
import { MAX_LOGIN_WAIT_MS } from '../../setup/login';

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
// token cache. Budget it at one per run.
//
// A run that is cold — the first after `--reset`, or with playwright/.auth/
// deleted — has already spent the whole budget in bootstrap before this
// test's own `asUser` login even runs (`setup/principals.ts` documents the
// cold bootstrap cost as "3, which is exactly the per-minute cap"), and that
// is not a rare local artifact: CI is always cold.
// `.github/workflows/e2e-tests.yml`'s `test` job runs `./scripts/e2e_up.sh`
// fresh inside every matrix job, on a runner with no `playwright/.auth/` and
// no cache-restore step. So this login can land inside the throttle window on
// any run, not just an occasional local one.
//
// #474: until this fix, that 429 failed the test outright — `asUser` throws
// on any non-OK login response by default, and the only thing keeping the
// test green was how far this file happened to run from bootstrap's logins (a
// margin measured once at ~69s in run 36103684984, which comes from
// test/file execution order and bounds nothing). This call now opts into
// `{ waitForThrottle: true }` (e2e/fixtures/auth.ts), which waits out the
// server's stated `Retry-After` instead of failing on a bare 429, bounded by
// `MAX_LOGIN_WAIT_MS` (one throttle window, ~61s) — hence the widened test
// timeout below, since the suite's global 30s budget cannot absorb that wait.
// See "The login throttle" in e2e/README.md.
test('refreshing a deleted user\'s token returns 401, not 500', { tag: '@contract' }, async ({
  seed,
  api,
  asUser,
  request,
}) => {
  // Wider than the global 30s: the login below can wait out one throttle
  // window (MAX_LOGIN_WAIT_MS, ~61s) rather than failing on a bare 429. The
  // +60s margin matches the pattern `playwright.config.ts`'s `bootstrap`
  // project uses for the same wait, covering the requests around it.
  test.setTimeout(MAX_LOGIN_WAIT_MS + 60_000);

  const user = await seed.user();
  const client = await asUser(user.username, SEEDED_USER_PASSWORD, {
    waitForThrottle: true,
  });
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
