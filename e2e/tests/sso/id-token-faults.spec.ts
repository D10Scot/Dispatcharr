/**
 * A dishonest provider is refused through the browser path (SSO spec PR S5, review round 1).
 *
 * One case per fault in the spec's fault list. The fake OP authenticates the person and
 * then lies in exactly one way; Mino must refuse on the callback, land the browser on the
 * login page with a fixed `sso_error` code, and create no user, although the claims carry
 * a role that maps to Admin, so a skipped check would provision one.
 *
 * - The six ID-token faults are refused at Mino's ID-token validation
 *   (`apps/accounts/oidc/flow.py`, step 7) as `id_token_invalid`, after a token exchange
 *   the OP accepted.
 * - `missing-iss-param` is refused before the token request (step 5, RFC 9207) as
 *   `issuer_mismatch`, on a provider seeded against the OP's `/oidc/rfc9207` issuer, which
 *   advertises the parameter and then omits it. The honest control beside it signs in
 *   through the same issuer, so the refusal is the fault's and not the issuer's.
 *
 * Spends no password request: everything goes through the SSO admin pair `sso.setup.ts`
 * wrote and the browser's SSO flow. Order-independent: each case seeds and retires its
 * own provider and changes no setting.
 */
import { test, expect } from './fixtures';
import { listRows } from '../../setup/http';
import { assertScopedStack } from './scope';
import {
  ADMIN_ROLE,
  createSsoProvider,
  retireSsoProvider,
  signInThroughSso,
  uniqueToken,
} from './helpers';
import type { OidcFault, OpIssuerPath, SsoProvider, UserRow } from './helpers';
import { SSO_TESTIDS } from './testids';

test.beforeAll(() => {
  assertScopedStack();
});

const providers: SsoProvider[] = [];

test.afterEach(async ({ api }) => {
  for (const provider of providers.splice(0)) await retireSsoProvider(api, provider);
});

const CASES: { fault: OidcFault; issuerPath: OpIssuerPath; ssoError: string; opLog: string[] }[] = [
  ...(['wrong-iss', 'wrong-aud', 'bad-nonce', 'expired', 'alg-none', 'unknown-kid'] as const).map((fault) => ({
    fault,
    issuerPath: '/oidc' as const,
    ssoError: 'id_token_invalid',
    opLog: ['authorize:accepted', 'token:accepted'],
  })),
  {
    fault: 'missing-iss-param',
    issuerPath: '/oidc/rfc9207',
    ssoError: 'issuer_mismatch',
    opLog: ['authorize:accepted'],
  },
];

for (const { fault, issuerPath, ssoError, opLog } of CASES) {
  test(
    `refuses an OP that sends ${fault}, as ${ssoError}, and creates no user`,
    { tag: '@contract' },
    async ({ page, api }) => {
      const provider = await createSsoProvider(api, `fault-${fault}`, { issuerPath });
      providers.push(provider);
      const username = `sso-fault-${uniqueToken()}`;
      await provider.queueLogin(
        {
          sub: `sub-${uniqueToken()}`,
          preferred_username: username,
          email: `${username}@example.test`,
          roles: [ADMIN_ROLE],
        },
        fault
      );

      await signInThroughSso(page, provider);

      await expect(page).toHaveURL(new RegExp(`/login\\?sso_error=${ssoError}$`), { timeout: 30_000 });
      await expect(page.getByTestId(SSO_TESTIDS.error)).toBeVisible();

      const users = listRows<UserRow>(await api.json<unknown>(await api.get('/api/accounts/users/'), 'list users'));
      expect(users.map((u) => u.username), 'no user was provisioned').not.toContain(username);

      const log = await provider.opLog();
      expect(log.map((e) => `${e.endpoint}:${e.outcome}`), 'the OP played its part').toEqual(opLog);
      expect(log[0]?.fault, 'the OP applied the fault').toBe(fault);
    }
  );
}

test(
  'signs in through the RFC 9207 issuer when it returns iss (control for missing-iss-param)',
  { tag: '@contract' },
  async ({ page, api }) => {
    const provider = await createSsoProvider(api, 'rfc9207', { issuerPath: '/oidc/rfc9207' });
    providers.push(provider);
    const username = `sso-rfc9207-${uniqueToken()}`;
    await provider.queueLogin({
      sub: `sub-${uniqueToken()}`,
      preferred_username: username,
      email: `${username}@example.test`,
      roles: [ADMIN_ROLE],
    });

    await signInThroughSso(page, provider);

    await expect(page).toHaveURL(/\/channels/, { timeout: 30_000 });
    expect((await provider.opLog()).map((e) => `${e.endpoint}:${e.outcome}`)).toEqual([
      'authorize:accepted',
      'token:accepted',
    ]);
  }
);
