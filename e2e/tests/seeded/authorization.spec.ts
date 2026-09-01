import {
  test,
  expect,
  PRINCIPALS,
  loginsSpentByThisWorker,
} from '../../fixtures';
import type { User } from '../../fixtures';

// Exemplar: how a later goal drives non-admin principals. The REST API is
// deny-by-default (DEFAULT_PERMISSION_CLASSES = IsAdmin), so a non-admin is
// refused admin surfaces unless the view opts down.
//
// Every test below costs **zero logins**. The principals are minted once by
// `bootstrap`, serially, before any worker starts; `asPrincipal` is a cache
// read. That is what lets an authorization matrix grow to any number of tests
// across any number of workers under a 3-logins-per-minute cap — see "The
// login throttle" in e2e/README.md.

for (const [name, principal] of Object.entries(PRINCIPALS)) {
  test(`a ${name} (user_level ${principal.user_level}) cannot list users`, { tag: '@contract' }, async ({
    asPrincipal,
  }) => {
    const client = await asPrincipal(name as keyof typeof PRINCIPALS);

    // Establish the principal before asserting the refusal, because the
    // refusal on its own is not evidence of anything. IsAdmin extends
    // Authenticated (apps/accounts/permissions.py), so the 403 below has three
    // possible causes: not authenticated at all, refused by the "UI" network
    // ACL, or authenticated but under user_level 10. Only the third is what
    // this test claims. `users/me` is the one action UserViewSet opts down to
    // Authenticated, i.e. it runs exactly the first two checks and not the
    // third — so a 200 here rules both of them out and leaves user_level as
    // the only remaining explanation for the 403. Asserting the identity pins
    // which principal was refused (not the bootstrap admin, whose tokens
    // ApiClient loads by default), and the level pins *which* non-admin level
    // it was: a test that could not tell a Streamer from a Standard user would
    // make its own name a quiet lie.
    const me = await client.json<User>(
      await client.get('/api/accounts/users/me/'),
      'asPrincipal identity check'
    );
    expect(me.username).toBe(principal.username);
    expect(me.user_level).toBe(principal.user_level);

    // Exactly 403, not [401, 403]: the `me` check above already proved this
    // principal is authenticated (IsAdmin extends Authenticated, and DRF only
    // returns 401 when authentication itself fails). A 401 here would mean
    // authentication broke between the two calls — an authentication
    // regression, not an acceptable authorization outcome — and tolerating it
    // would hide that.
    const res = await client.get('/api/accounts/users/');

    expect(res.status()).toBe(403);
  });
}

// The budget itself, pinned. This is the mechanism the whole design rests on:
// `bootstrap` writes the principal tokens and every worker pre-loads them, so
// obtaining a principal client — through `asPrincipal`, or through `asUser`
// with the same fixed credentials — makes no `POST /api/accounts/token/` call
// at all. If this fails, the suite has gone back to spending logins per worker
// and will 429 as soon as a matrix grows.
//
// The assertion is a delta, not an absolute: other tests share this worker.
test('driving a fixed principal spends no login', { tag: '@contract' }, async ({
  asPrincipal,
  asUser,
}) => {
  const before = loginsSpentByThisWorker();

  const viaPrincipal = await asPrincipal('standard');
  const viaUser = await asUser(
    PRINCIPALS.standard.username,
    PRINCIPALS.standard.password
  );

  expect(loginsSpentByThisWorker()).toBe(before);

  for (const client of [viaPrincipal, viaUser]) {
    const me = await client.json<User>(
      await client.get('/api/accounts/users/me/'),
      'fixed principal identity'
    );
    expect(me.username).toBe(PRINCIPALS.standard.username);
  }
});

test('an admin can list users', { tag: '@contract' }, async ({ api }) => {
  const res = await api.get('/api/accounts/users/');
  expect(res.status()).toBe(200);
});
