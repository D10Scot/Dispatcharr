import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';

// Exemplar: how wave 2 drives a non-admin principal. The REST API is
// deny-by-default (DEFAULT_PERMISSION_CLASSES = IsAdmin), so a Standard user
// is refused admin surfaces unless the view opts down.
test('a Standard user cannot list users', async ({ seed, asUser }) => {
  const user = await seed.user({ user_level: 1 });

  const client = await asUser(user.username, SEEDED_USER_PASSWORD);

  // Establish the principal before asserting the refusal, because the refusal
  // on its own is not evidence of anything. IsAdmin extends Authenticated
  // (apps/accounts/permissions.py), so the 403 below has three possible
  // causes: not authenticated at all, refused by the "UI" network ACL, or
  // authenticated but under user_level 10. Only the third is what this test
  // claims. `users/me` is the one action UserViewSet opts down to
  // Authenticated, i.e. it runs exactly the first two checks and not the
  // third — so a 200 here rules both of them out and leaves user_level as the
  // only remaining explanation for the 403. Asserting the identity pins which
  // principal was refused (not the bootstrap admin, whose tokens ApiClient
  // loads by default), and the level pins that it was a Standard one: a
  // Streamer is refused too, which would make this test's name a quiet lie.
  const me = await client.json<{ username: string; user_level: number }>(
    await client.get('/api/accounts/users/me/'),
    'asUser identity check'
  );
  expect(me.username).toBe(user.username);
  expect(me.user_level).toBe(1);

  const res = await client.get('/api/accounts/users/');

  expect([401, 403]).toContain(res.status());
});

test('an admin can list users', async ({ api }) => {
  const res = await api.get('/api/accounts/users/');
  expect(res.status()).toBe(200);
});
