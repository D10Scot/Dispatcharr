/**
 * The `sso-setup` and `sso-faults-setup` projects: the own bootstrap of the `sso` and
 * `sso-faults` projects (SSO spec PR S5), one file run by both, each against its own
 * scoped stack.
 *
 * It never reads the shared `playwright/.auth/tokens.json` or `principals.json`; the
 * pair it mints is the scoped stack's, in the file `ssoTokensFile` names for the running
 * project (`sso-tokens.json` or `sso-faults-tokens.json`), so neither project ever reads
 * the other stack's pair. Password-request budget:
 * **0** on a warm run (the stored refresh token is renewed through the unthrottled
 * refresh endpoint), **1** on a cold one.
 */
import { test as setup, expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import fs from 'node:fs';
import { ADMIN } from '../../setup/credentials';
import { loginWithThrottleBackoff, refreshAccessToken, tokenPairOf, whoAmI } from '../../setup/login';
import type { TokenPair } from '../../setup/login';
import { ensureSuperuser } from '../../setup/provision-admin';
import { writeAuthFileAtomically } from '../../setup/auth-files';
import { assertScopedStack } from './scope';
import { ssoTokensFile } from './helpers';

/** The stored pair, renewed, if it still names the admin; otherwise null. Spends no login. */
async function reusablePair(request: APIRequestContext, tokensFile: string): Promise<TokenPair | null> {
  let stored: TokenPair | undefined;
  try {
    stored = tokenPairOf(JSON.parse(fs.readFileSync(tokensFile, 'utf8')));
  } catch {
    return null;
  }
  if (!stored) return null;
  const refreshed = await refreshAccessToken(request, stored.refresh);
  const access = refreshed.access;
  if (access === undefined) return null;
  const identity = await whoAmI(request, access);
  if (identity?.username !== ADMIN.username || identity.user_level !== 10) return null;
  return { access, refresh: stored.refresh };
}

setup('create the scoped stack admin and persist its pair', async ({ request, baseURL }) => {
  // First statement: nothing below may reach a stack that is not this project's own.
  assertScopedStack();

  const tokensFile = ssoTokensFile(setup.info().project.name);
  await ensureSuperuser(request, baseURL!);

  const providers = await request.get('/api/accounts/oidc/providers/');
  expect(providers.ok(), `GET /api/accounts/oidc/providers/: ${providers.status()}`).toBeTruthy();
  const { password_login_enabled: passwordLoginEnabled } = (await providers.json()) as {
    password_login_enabled?: boolean;
  };
  if (passwordLoginEnabled !== true) {
    throw new Error(
      'Password login is off on this stack, so a previous sso run died mid-test (the ' +
        'break-glass spec leaves it on when it finishes). Recreate the stack with the same ' +
        'variables exported that it was started with: the scoped stack ' +
        '(DISPATCHARR_E2E_CONTAINER, _VOLUME, _NETWORK, _PORT, _IMAGE, E2E_BASE_URL and ' +
        'E2E_OIDC_ALLOW_HTTP=1) and, for a private provider, its upstream variables ' +
        '(_UPSTREAM_CONTAINER, _UPSTREAM_PORT, _UPSTREAM_IMAGE, E2E_UPSTREAM_CONTROL_URL and ' +
        'E2E_UPSTREAM_INTERNAL_URL), or --reset acts on the default provider name, e2e-upstream: ' +
        'scripts/e2e_up.sh --reset'
    );
  }

  const pair = (await reusablePair(request, tokensFile)) ?? (await loginWithThrottleBackoff(request, ADMIN));
  writeAuthFileAtomically(tokensFile, JSON.stringify(pair, null, 2));

  // A provider's redirect URI is built from public_base_url, which a fresh stack leaves
  // unset. The stack's own loopback origin is accepted without MINO_OIDC_ALLOW_HTTP
  // (SSO spec 5.1). Written only when it differs, so a warm run writes nothing.
  const origin = new URL(baseURL!).origin;
  const headers = { Authorization: `Bearer ${pair.access}` };
  const settings = await request.get('/api/accounts/oidc/settings/', { headers });
  expect(settings.ok(), `GET /api/accounts/oidc/settings/: ${settings.status()}`).toBeTruthy();
  const { public_base_url: current } = (await settings.json()) as { public_base_url?: string };
  if (current !== origin) {
    const patched = await request.patch('/api/accounts/oidc/settings/', {
      headers,
      data: { public_base_url: origin },
    });
    expect(
      patched.ok(),
      `PATCH public_base_url to ${origin}: ${patched.status()} ${await patched.text()}`
    ).toBeTruthy();
  }
});
