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
import type { Page, Response } from '@playwright/test';
import { expect } from '@playwright/test';
import type { ApiClient } from '../../fixtures';
import { UPSTREAM_CONTROL_BASE, UPSTREAM_INTERNAL_BASE } from '../../fixtures/upstream';
import { AUTH_DIR } from '../../setup/auth-files';
import type { TokenPair } from '../../setup/login';
import { tokenPairOf } from '../../setup/login';
import { ssoLoginButton } from './testids';

/**
 * Where a project's admin pair lives: one file per stack, so the `sso` and `sso-faults`
 * projects, each on a scoped stack of its own, never read each other's pair. Keyed by the
 * Playwright project name of the setup project that writes it or the spec project that
 * reads it. Never `tokens.json`.
 */
const SSO_TOKEN_FILES: Record<string, string> = {
  'sso-setup': 'sso-tokens.json',
  sso: 'sso-tokens.json',
  'sso-faults-setup': 'sso-faults-tokens.json',
  'sso-faults': 'sso-faults-tokens.json',
};

/** The admin-pair file for `projectName`. Throws for a project that is not an SSO project. */
export function ssoTokensFile(projectName: string): string {
  const file = SSO_TOKEN_FILES[projectName];
  if (!file) {
    throw new Error(
      `project '${projectName}' has no SSO admin-pair file: add it to SSO_TOKEN_FILES in tests/sso/helpers.ts`
    );
  }
  return path.join(AUTH_DIR, file);
}

/** The admin pair the project's setup wrote. Throws naming the setup project if it is absent. */
export function readSsoAdminPair(projectName: string): TokenPair {
  const file = ssoTokensFile(projectName);
  let pair: TokenPair | undefined;
  try {
    pair = tokenPairOf(JSON.parse(fs.readFileSync(file, 'utf8')));
  } catch {
    pair = undefined;
  }
  if (!pair) {
    throw new Error(
      `${file} holds no admin token pair. It is written by the project's setup dependency ` +
        `(sso-setup or sso-faults-setup): run the ${projectName} project, not a single file ` +
        'with --no-deps.'
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
  | 'bad-signature'
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

const THROTTLE_NOTE =
  "Mino's oidc throttle, 20 a minute per client IP over start, link/start, callback and " +
  'exchange (e2e/README.md, "The sso project")';

/** Which leg of the flow a response is, by path. */
function legOf(response: Response): 'start' | 'callback' | 'exchange' | undefined {
  const { pathname } = new URL(response.url());
  if (/^\/api\/accounts\/oidc\/[^/]+\/start\/$/.test(pathname)) return 'start';
  if (/^\/api\/accounts\/oidc\/[^/]+\/callback\/$/.test(pathname)) return 'callback';
  if (/^\/api\/accounts\/oidc\/exchange\/$/.test(pathname) && response.request().method() === 'POST') return 'exchange';
  return undefined;
}

/** Fails naming the throttle if `response` is a 429: an observation, never a retry. */
function expectNotThrottled(response: Response): void {
  expect(
    response.status(),
    `${response.request().method()} ${new URL(response.url()).pathname} answered 429: ${THROTTLE_NOTE}`
  ).not.toBe(429);
}

/**
 * From the login page, click the provider's button; the fake OP auto-approves.
 *
 * A throttled leg shows raw JSON (start, callback) or turns into `exchange_failed`
 * (exchange), and would otherwise surface as an opaque URL timeout, so each leg that
 * happens is checked for a 429 as it arrives. Nothing is retried and nothing else about
 * the responses is judged: the specs' own assertions decide the outcome.
 */
export async function signInThroughSso(page: Page, provider: SsoProvider): Promise<void> {
  await page.goto('/login');
  const button = page.getByTestId(ssoLoginButton(provider.slug));
  await expect(button, `the login page offers ${provider.displayName}`).toBeVisible();
  // Every waiter is registered before the click, so no leg can arrive unseen. A leg the
  // flow never reaches resolves to null rather than rejecting unhandled.
  const waitFor = (leg: 'start' | 'callback' | 'exchange') =>
    page.waitForResponse((r) => legOf(r) === leg, { timeout: 30_000 }).catch(() => null);
  const started = waitFor('start');
  const calledBack = waitFor('callback');
  const exchanged = waitFor('exchange');
  await button.click();

  const start = await started;
  if (!start) return;
  expectNotThrottled(start);

  const callback = await calledBack;
  if (!callback) return;
  expectNotThrottled(callback);

  // Only a callback that hands off (`/login/sso#code=…`) leads to an exchange; a refusal
  // redirects to `/login?sso_error=…` and the exchange waiter is left to lapse.
  const location = callback.headers()['location'];
  if (!location || new URL(location, callback.url()).pathname !== '/login/sso') return;
  const exchange = await exchanged;
  if (!exchange) return;
  expectNotThrottled(exchange);
}

/** A user row as `GET /api/accounts/users/` returns it, the fields these specs read. */
export interface UserRow {
  id: number;
  username: string;
  user_level: number;
}
