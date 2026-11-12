/**
 * A dishonest provider is refused through the browser path (the `sso-faults` project).
 *
 * One case per fault in the fake OP's fault list. The OP authenticates the person and
 * then lies in exactly one way; Mino must refuse on the callback, land the browser on the
 * login page with a fixed `sso_error` code, store no token pair and create no user,
 * although the claims carry a role that maps to Admin.
 *
 * - The seven ID-token faults are refused at Mino's ID-token validation
 *   (`apps/accounts/oidc/flow.py`, step 7; `apps/accounts/oidc/validate.py`) as
 *   `id_token_invalid`, after a token exchange the OP accepted.
 * - `missing-iss-param` is refused before the token request (step 5, RFC 9207) as
 *   `issuer_mismatch`, on a provider seeded against the OP's `/oidc/rfc9207` issuer, which
 *   advertises the parameter and then omits it. The honest control beside it signs in
 *   through the same issuer, so the refusal is the fault's and not the issuer's.
 *
 * What a case reddens on if its check were skipped: each fault changes one property of an
 * otherwise honest token, so a product that skipped the check that fault aims at would
 * provision the Admin. The checks pinned here, one fault each: the signature
 * (`bad-signature`: published `kid`, RS256, honest claims, another key's signature), the
 * refusal of an unsigned token (`alg-none`: published `kid`, so key lookup succeeds and
 * the token reaches decoding), `aud`, `iss`, the nonce, expiry, RFC 9207's `iss`
 * parameter and key lookup (`unknown-kid`). `alg-none` does not pin algorithm pinning
 * itself: PyJWT refuses `none` with a key whatever algorithm list it is given, so a build
 * that took the algorithm from the token header still passed it (fix round 1, observed).
 * Unit-only (`apps/accounts/tests/test_oidc_flow.py`): algorithm pinning
 * (`test_alg_none_refused`, `test_hs256_signed_with_client_secret_refused`), `azp` and
 * multiple audiences, required claims and the subject's shape, the Entra tenant and
 * issuer, the JWK's own shape (`oct`, wrong family, a disagreeing `alg`, private members)
 * and the refetch on an unknown `kid`.
 *
 * Its own project on its own scoped stack, because its requests do not fit beside the
 * `sso` project's in one throttle window.
 * SSO request budget: 2 per fault case (start and callback; Mino refuses on the callback,
 * so there is no exchange) and 3 for the control (start, callback and exchange).
 * The project spends 19 a run; see e2e/README.md, "The sso-faults project".
 *
 * Spends no password request: everything goes through the admin pair `sso.setup.ts`
 * wrote and the browser's SSO flow. Order-independent: each case seeds and retires its
 * own provider and changes no setting.
 */
import { test, expect } from '../fixtures';
import { listRows } from '../../../setup/http';
import { assertScopedStack } from '../scope';
import {
  ADMIN_ROLE,
  createSsoProvider,
  retireSsoProvider,
  signInThroughSso,
  uniqueToken,
} from '../helpers';
import type { OidcFault, OpIssuerPath, SsoProvider, UserRow } from '../helpers';
import { SSO_TESTIDS } from '../testids';

test.beforeAll(() => {
  assertScopedStack();
});

const providers: SsoProvider[] = [];

test.afterEach(async ({ api }) => {
  for (const provider of providers.splice(0)) await retireSsoProvider(api, provider);
});

const ID_TOKEN_FAULTS: readonly OidcFault[] = [
  'wrong-iss',
  'wrong-aud',
  'bad-nonce',
  'expired',
  'alg-none',
  'unknown-kid',
  'bad-signature',
];

const CASES: { fault: OidcFault; issuerPath: OpIssuerPath; ssoError: string; opLog: string[] }[] = [
  ...ID_TOKEN_FAULTS.map((fault) => ({
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

      // No session: the SPA stored no token pair. That pair is the only credential a
      // browser can present: the API authenticates by bearer JWT or API key and has no
      // session authentication (DRF's DEFAULT_AUTHENTICATION_CLASSES in the settings module),
      // so a cookie-only request would answer 401 whatever the browser held and proves
      // nothing.
      const stored = await page.evaluate(() => [localStorage.getItem('accessToken'), localStorage.getItem('refreshToken')]);
      expect(stored, 'no token pair was stored').toEqual([null, null]);

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
    const users = listRows<UserRow>(await api.json<unknown>(await api.get('/api/accounts/users/'), 'list users'));
    expect(users.find((u) => u.username === username)?.user_level, 'the control was provisioned as Admin').toBe(10);
    expect((await provider.opLog()).map((e) => `${e.endpoint}:${e.outcome}`)).toEqual([
      'authorize:accepted',
      'token:accepted',
    ]);
  }
);
