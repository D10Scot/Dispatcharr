/**
 * The `sso` project's helpers (SSO spec PR S5): the admin pair `sso.setup.ts` minted,
 * the fake OpenID provider's control API (`e2e-upstream/README.md`, "Fake OpenID
 * provider"), and the provider rows the specs seed in Mino.
 *
 * Every provider is seeded as a **generic** provider with `allow_private_network: true`
 * (the fake OP is on the Docker network's private address, SSO spec 3.5) and
 * `client_secret_post`. Its client id and secret are generated per test at run time:
 * nothing here, or in the fake OP, is a stored credential.
 */
import fs from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
import type { ApiClient } from '../../fixtures';
import { UPSTREAM_CONTROL_BASE, UPSTREAM_INTERNAL_BASE } from '../../fixtures/upstream';
import { AUTH_DIR } from '../../setup/auth-files';
import type { TokenPair } from '../../setup/login';
import { tokenPairOf } from '../../setup/login';
import { ssoLoginButton } from './testids';

/** Where `sso.setup.ts` keeps this project's admin pair. Never `tokens.json`. */
export const SSO_TOKENS_FILE = path.join(AUTH_DIR, 'sso-tokens.json');

/** The admin pair `sso.setup.ts` wrote. Throws naming the setup project if it is absent. */
export function readSsoAdminPair(): TokenPair {
  let pair: TokenPair | undefined;
  try {
    pair = tokenPairOf(JSON.parse(fs.readFileSync(SSO_TOKENS_FILE, 'utf8')));
  } catch {
    pair = undefined;
  }
  if (!pair) {
    throw new Error(
      `${SSO_TOKENS_FILE} holds no admin token pair. It is written by the sso-setup ` +
        'project, which the sso project lists in dependencies: run the sso project, not a ' +
        'single file with --no-deps.'
    );
  }
  return pair;
}

/** The value a mapping turns into Admin. The specs' claims carry it or deliberately not. */
export const ADMIN_ROLE = 'mino-admin';

export type OidcFault =
  | 'wrong-iss'
  | 'wrong-aud'
  | 'bad-nonce'
  | 'expired'
  | 'alg-none'
  | 'unknown-kid'
  | 'missing-iss-param';

/** The fake OP's control API, on the host-published origin. */
async function opRequest(method: string, subPath: string, body?: unknown): Promise<unknown> {
  const res = await fetch(`${UPSTREAM_CONTROL_BASE}${subPath}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`fake OP ${method} ${subPath} answered ${res.status}: ${text}`);
  }
  return text ? JSON.parse(text) : undefined;
}

/** One entry of the fake OP's per-client log. */
export interface OpLogEntry {
  endpoint: 'authorize' | 'token';
  outcome: 'accepted' | 'refused';
  reason?: string;
  fault?: OidcFault;
}

export interface SsoProvider {
  id: number;
  slug: string;
  displayName: string;
  clientId: string;
  /** Queue the next login the fake OP will approve for this client. */
  queueLogin(claims: Record<string, unknown>, fault?: OidcFault): Promise<void>;
  /** What the fake OP accepted and refused for this client. */
  opLog(): Promise<OpLogEntry[]>;
}

/** A short, unique, lower-case token for slugs, usernames and subjects. */
export function uniqueToken(): string {
  return randomBytes(5).toString('hex');
}

/** The fake OP's two issuers: the Entra-shaped one, and one that advertises RFC 9207 `iss`. */
export type OpIssuerPath = '/oidc' | '/oidc/rfc9207';

/**
 * Seed an enabled generic provider in Mino pointed at the fake OP, and register its
 * redirect URI with the OP. One per test: the OP's queue and log are per client.
 */
export async function createSsoProvider(
  api: ApiClient,
  label: string,
  options: { issuerPath?: OpIssuerPath } = {}
): Promise<SsoProvider> {
  const token = uniqueToken();
  const slug = `e2e-${label}-${token}`;
  const displayName = `E2E ${label} ${token}`;
  const clientId = `mino-e2e-${token}`;
  const clientSecret = randomBytes(24).toString('base64url');
  const issuer = `${UPSTREAM_INTERNAL_BASE.replace(/\/+$/, '')}${options.issuerPath ?? '/oidc'}`;

  const created = await api.json<{ id: number; slug: string; redirect_uri: string | null }>(
    await api.post('/api/accounts/oidc/providers-admin/', {
      slug,
      display_name: displayName,
      kind: 'generic',
      enabled: true,
      issuer,
      client_id: clientId,
      client_secret: clientSecret,
      client_auth_method: 'client_secret_post',
      allow_private_network: true,
      scopes: 'openid profile email',
      id_token_alg: 'RS256',
      claim_path: 'roles',
      mappings: [{ value: ADMIN_ROLE, user_level: 10 }],
    }),
    `create the ${label} provider`
  );
  if (!created.redirect_uri) {
    throw new Error(
      'the provider has no redirect_uri, so public_base_url is unset: sso.setup.ts sets it ' +
        'to the stack origin, so the sso-setup project did not run against this stack.'
    );
  }

  await opRequest('POST', '/oidc/clients', {
    client_id: clientId,
    client_secret: clientSecret,
    redirect_uris: [created.redirect_uri],
  });

  return {
    id: created.id,
    slug,
    displayName,
    clientId,
    queueLogin: async (claims, fault) => {
      await opRequest('POST', `/oidc/clients/${encodeURIComponent(clientId)}/logins`, {
        claims,
        ...(fault ? { fault } : {}),
      });
    },
    opLog: async () =>
      (await opRequest('GET', `/oidc/clients/${encodeURIComponent(clientId)}/log`)) as OpLogEntry[],
  };
}

/**
 * Disable a provider the test seeded, and forget its client at the OP. Disabled rather
 * than deleted: a provider that signed someone in holds an identity, and deleting it is
 * refused (409 `provider_has_identities`). Best effort, for an `afterEach`.
 */
export async function retireSsoProvider(api: ApiClient, provider: SsoProvider): Promise<void> {
  const res = await api.patch(`/api/accounts/oidc/providers-admin/${provider.id}/`, { enabled: false });
  if (!res.ok()) {
    console.warn(`could not disable provider ${provider.slug}: ${res.status()} ${await res.text()}`);
  }
  await opRequest('DELETE', `/oidc/clients/${encodeURIComponent(provider.clientId)}`).catch((error) => {
    console.warn(`could not forget OP client ${provider.clientId}: ${String(error)}`);
  });
}

/** From the login page, click the provider's button; the fake OP auto-approves. */
export async function signInThroughSso(page: Page, provider: SsoProvider): Promise<void> {
  await page.goto('/login');
  const button = page.getByTestId(ssoLoginButton(provider.slug));
  await expect(button, `the login page offers ${provider.displayName}`).toBeVisible();
  await button.click();
}

/** A user row as `GET /api/accounts/users/` returns it, the fields these specs read. */
export interface UserRow {
  id: number;
  username: string;
  user_level: number;
}
