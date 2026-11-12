/**
 * A sign-in whose role claim no mapping names is refused (SSO spec PR S5).
 *
 * The OP authenticates the person; Mino refuses to provision them, because nothing maps
 * them to a level. The browser lands on the login page with the fixed `no_mapping` code
 * and no user is created.
 */
import { test, expect } from './fixtures';
import { listRows } from '../../setup/http';
import { assertScopedStack } from './scope';
import { createSsoProvider, retireSsoProvider, signInThroughSso, uniqueToken } from './helpers';
import type { SsoProvider, UserRow } from './helpers';
import { SSO_TESTIDS } from './testids';

test.beforeAll(() => {
  assertScopedStack();
});

const providers: SsoProvider[] = [];

test.afterEach(async ({ api }) => {
  for (const provider of providers.splice(0)) await retireSsoProvider(api, provider);
});

test(
  'an unmapped role claim lands on the login page with no_mapping and creates no user',
  { tag: '@contract' },
  async ({ page, api }) => {
    const provider = await createSsoProvider(api, 'unmapped');
    providers.push(provider);
    const username = `sso-unmapped-${uniqueToken()}`;
    await provider.queueLogin({
      sub: `sub-${uniqueToken()}`,
      preferred_username: username,
      email: `${username}@example.test`,
      roles: ['not-a-mapped-role'],
    });

    await signInThroughSso(page, provider);

    await expect(page).toHaveURL(/\/login\?sso_error=no_mapping$/, { timeout: 30_000 });
    await expect(page.getByTestId(SSO_TESTIDS.error)).toBeVisible();

    const users = listRows<UserRow>(await api.json<unknown>(await api.get('/api/accounts/users/'), 'list users'));
    expect(users.map((u) => u.username), 'no user was provisioned').not.toContain(username);

    // The OP issued a valid token: the refusal is Mino's, not the provider's.
    expect((await provider.opLog()).map((e) => `${e.endpoint}:${e.outcome}`)).toEqual([
      'authorize:accepted',
      'token:accepted',
    ]);
  }
);
