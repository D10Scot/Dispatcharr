/**
 * A minimal OpenID provider for Mino's SSO e2e tests (SSO spec PR S5).
 *
 * Shaped like Microsoft Entra where the difference matters to the relying party
 * (SSO spec 3.5): discovery advertises neither `code_challenge_methods_supported`
 * nor `authorization_response_iss_parameter_supported`, JWKS entries carry no
 * `alg`, and the token endpoint authenticates the client from the form body
 * (`client_secret_post`). It is nonetheless strict where a real OP is: the
 * token endpoint REQUIRES a valid PKCE `code_verifier`, although discovery does
 * not advertise PKCE, so a relying party that stopped sending it would fail.
 *
 * Two origins, never conflated (the same split `server.ts` makes for
 * scenarios). The issuer, `token_endpoint` and `jwks_uri` are on the
 * in-network origin, which Mino's server reaches; `authorization_endpoint` is on
 * the host-published control origin, which the Playwright browser reaches. Both
 * come from the environment `scripts/e2e_up.sh` starts the container with.
 *
 * Two issuers. `/oidc` is the Entra-shaped one every test uses.
 * `/oidc/rfc9207` is identical except that it advertises
 * `authorization_response_iss_parameter_supported: true` and returns `iss` on
 * the authorization response (RFC 9207), which is what gives the
 * `missing-iss-param` fault something to break. A provider advertising it while
 * omitting it cannot be expressed on one issuer that also serves the ordinary
 * case, because discovery is per issuer.
 *
 * Control API (host-side, for the tests; never reached by Mino):
 *   POST   /oidc/clients                       register {client_id, client_secret, redirect_uris}
 *   POST   /oidc/clients/<client_id>/logins    queue the next login {claims, fault?}
 *   GET    /oidc/clients/<client_id>/log       what the OP accepted and refused, and why
 *   DELETE /oidc/clients/<client_id>           forget a client
 *
 * State is in-memory, like `ScenarioRegistry`: a recreated provider forgets
 * every client, and its keys change.
 */
import type { IncomingMessage, ServerResponse } from 'node:http';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { BadRequestError } from '../errors.js';
import { jwks, publishedKey, rogueKey, s256, signRs256, unsigned } from './jwt.js';

/** The ID-token and authorization-response faults, selectable per login. */
export const OIDC_FAULTS = [
  'wrong-iss',
  'wrong-aud',
  'bad-nonce',
  'expired',
  'alg-none',
  'unknown-kid',
  'missing-iss-param',
] as const;
export type OidcFault = (typeof OIDC_FAULTS)[number];

/**
 * The fault a login gets when it names none. Undefined: an honest token. S5's
 * break-check sets this to `'wrong-aud'` and watches the happy path redden.
 */
export const DEFAULT_FAULT: OidcFault | undefined = undefined;

/** Lifetime of an authorization code. Short, as a real OP's is. */
const CODE_TTL_MS = 60_000;
/** Lifetime of an ID token. */
const ID_TOKEN_TTL_S = 600;

const ISSUER_PATHS = ['/oidc', '/oidc/rfc9207'] as const;
type IssuerPath = (typeof ISSUER_PATHS)[number];

function internalOrigin(): string {
  return process.env.UPSTREAM_INTERNAL_ORIGIN ?? 'http://e2e-upstream:8080';
}

/**
 * The host-published origin the browser reaches. The default is the shared
 * provider's published port (`scripts/e2e_up.sh`'s `UPSTREAM_PORT`), as
 * `UPSTREAM_INTERNAL_ORIGIN`'s default is the shared provider's name; a renamed
 * provider is always started with both set.
 */
function controlOrigin(): string {
  return (process.env.UPSTREAM_CONTROL_ORIGIN ?? 'http://127.0.0.1:9402').replace(/\/+$/, '');
}

export function issuerFor(path: IssuerPath): string {
  return `${internalOrigin()}${path}`;
}

/** Live Entra's discovery shape (SSO spec 3.5), plus the RFC 9207 flag on one issuer. */
export function discovery(path: IssuerPath): Record<string, unknown> {
  const doc: Record<string, unknown> = {
    issuer: issuerFor(path),
    authorization_endpoint: `${controlOrigin()}${path}/authorize`,
    token_endpoint: `${internalOrigin()}${path}/token`,
    jwks_uri: `${internalOrigin()}${path}/jwks`,
    response_types_supported: ['code'],
    response_modes_supported: ['query'],
    subject_types_supported: ['pairwise'],
    scopes_supported: ['openid', 'profile', 'email'],
    id_token_signing_alg_values_supported: ['RS256'],
    token_endpoint_auth_methods_supported: ['client_secret_post'],
    claims_supported: ['sub', 'iss', 'aud', 'exp', 'iat', 'nonce', 'preferred_username', 'email', 'name'],
  };
  if (path === '/oidc/rfc9207') doc.authorization_response_iss_parameter_supported = true;
  return doc;
}

interface Client {
  clientId: string;
  clientSecret: string;
  redirectUris: string[];
}

interface QueuedLogin {
  claims: Record<string, unknown>;
  fault?: OidcFault;
}

interface IssuedCode {
  clientId: string;
  issuerPath: IssuerPath;
  redirectUri: string;
  nonce: string;
  codeChallenge: string;
  login: QueuedLogin;
  expiresAt: number;
  used: boolean;
}

export interface OidcLogEntry {
  at: string;
  endpoint: 'authorize' | 'token';
  outcome: 'accepted' | 'refused';
  /** A fixed reason, e.g. `pkce_mismatch`; never a secret or a token. */
  reason?: string;
  fault?: OidcFault;
}

const clients = new Map<string, Client>();
const pending = new Map<string, QueuedLogin[]>();
const codes = new Map<string, IssuedCode>();
const logs = new Map<string, OidcLogEntry[]>();

/** Test hook for the package's own suite: forget every client, code and log. */
export function resetOidcState(): void {
  clients.clear();
  pending.clear();
  codes.clear();
  logs.clear();
}

function record(clientId: string, entry: Omit<OidcLogEntry, 'at'>): void {
  const list = logs.get(clientId) ?? [];
  list.push({ at: new Date().toISOString(), ...entry });
  logs.set(clientId, list);
}

function randomToken(bytes = 32): string {
  return randomBytes(bytes).toString('base64url');
}

function secretsEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

export interface OidcContext {
  req: IncomingMessage;
  res: ServerResponse;
  url: URL;
  readRawBody: () => Promise<string>;
  readJsonObject: () => Promise<Record<string, unknown>>;
  sendJson: (status: number, body: unknown) => void;
}

/** Whether `pathname` belongs to this module. `server.ts` routes on it. */
export function isOidcPath(pathname: string): boolean {
  return pathname === '/oidc' || pathname.startsWith('/oidc/');
}

function parseIssuerRoute(pathname: string): { issuerPath: IssuerPath; rest: string } | undefined {
  // Longest issuer first, so `/oidc/rfc9207/token` is not read as `/oidc` + `/rfc9207/token`.
  for (const issuerPath of [...ISSUER_PATHS].sort((a, b) => b.length - a.length)) {
    if (pathname.startsWith(`${issuerPath}/`)) {
      return { issuerPath, rest: pathname.slice(issuerPath.length) };
    }
  }
  return undefined;
}

function parseClientRequest(body: Record<string, unknown>): Client {
  const { client_id: clientId, client_secret: clientSecret, redirect_uris: redirectUris } = body;
  if (typeof clientId !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(clientId)) {
    throw new BadRequestError("'client_id' must be 1-128 characters of [A-Za-z0-9._-]");
  }
  if (typeof clientSecret !== 'string' || clientSecret.length === 0) {
    throw new BadRequestError("'client_secret' must be a non-empty string");
  }
  if (
    !Array.isArray(redirectUris) ||
    redirectUris.length === 0 ||
    !redirectUris.every((u) => typeof u === 'string' && /^https?:\/\//.test(u))
  ) {
    throw new BadRequestError("'redirect_uris' must be a non-empty list of http(s) URLs");
  }
  return { clientId, clientSecret, redirectUris: redirectUris as string[] };
}

function parseLoginRequest(body: Record<string, unknown>): QueuedLogin {
  const { claims, fault } = body;
  if (typeof claims !== 'object' || claims === null || Array.isArray(claims)) {
    throw new BadRequestError("'claims' must be a JSON object");
  }
  const sub = (claims as Record<string, unknown>).sub;
  if (typeof sub !== 'string' || sub.length === 0) {
    throw new BadRequestError("'claims.sub' must be a non-empty string");
  }
  if (fault !== undefined && !OIDC_FAULTS.includes(fault as OidcFault)) {
    throw new BadRequestError(`'fault' must be one of ${OIDC_FAULTS.join(', ')}`);
  }
  return { claims: claims as Record<string, unknown>, fault: fault as OidcFault | undefined };
}

/** RFC 6749 4.1.2.1: send an error back to a redirect URI already validated as registered. */
function redirectError(
  res: ServerResponse,
  redirectUri: string,
  error: string,
  state: string | null
): void {
  const target = new URL(redirectUri);
  target.searchParams.set('error', error);
  if (state !== null) target.searchParams.set('state', state);
  res.writeHead(302, { Location: target.toString() });
  res.end();
}

/** Auto-approves, consuming the client's next queued login. */
function authorize(ctx: OidcContext, issuerPath: IssuerPath): void {
  const { url, res, sendJson } = ctx;
  const params = url.searchParams;
  const clientId = params.get('client_id') ?? '';
  const redirectUri = params.get('redirect_uri') ?? '';
  const state = params.get('state');
  const client = clients.get(clientId);

  // An unknown client or an unregistered redirect URI is answered here, never
  // redirected: sending an error to an unvetted URI is the open redirect a real
  // OP refuses too.
  if (!client) {
    sendJson(400, { error: 'invalid_request', reason: 'unknown_client' });
    return;
  }
  if (!client.redirectUris.includes(redirectUri)) {
    record(clientId, { endpoint: 'authorize', outcome: 'refused', reason: 'redirect_uri_not_registered' });
    sendJson(400, { error: 'invalid_request', reason: 'redirect_uri_not_registered' });
    return;
  }

  const refuse = (error: string, reason: string) => {
    record(clientId, { endpoint: 'authorize', outcome: 'refused', reason });
    redirectError(res, redirectUri, error, state);
  };
  if (params.get('response_type') !== 'code') return refuse('unsupported_response_type', 'response_type');
  if (!(params.get('scope') ?? '').split(' ').includes('openid')) return refuse('invalid_scope', 'no_openid_scope');
  const nonce = params.get('nonce');
  if (!nonce) return refuse('invalid_request', 'no_nonce');
  const codeChallenge = params.get('code_challenge');
  if (!codeChallenge || params.get('code_challenge_method') !== 'S256') {
    return refuse('invalid_request', 'pkce_required');
  }
  const login = pending.get(clientId)?.shift();
  if (!login) return refuse('access_denied', 'no_login_queued');

  const fault = login.fault ?? DEFAULT_FAULT;
  const code = randomToken();
  codes.set(code, {
    clientId,
    issuerPath,
    redirectUri,
    nonce,
    codeChallenge,
    login: { ...login, fault },
    expiresAt: Date.now() + CODE_TTL_MS,
    used: false,
  });
  record(clientId, { endpoint: 'authorize', outcome: 'accepted', fault });

  const target = new URL(redirectUri);
  target.searchParams.set('code', code);
  if (state !== null) target.searchParams.set('state', state);
  // RFC 9207: an issuer that advertises the parameter returns it, unless the
  // fault says to omit it while still advertising it.
  if (issuerPath === '/oidc/rfc9207' && fault !== 'missing-iss-param') {
    target.searchParams.set('iss', issuerFor(issuerPath));
  }
  res.writeHead(302, { Location: target.toString() });
  res.end();
}

/** The ID token for a redeemed code, with its fault applied. */
function idTokenFor(issued: IssuedCode): string {
  const now = Math.floor(Date.now() / 1000);
  const fault = issued.login.fault;
  const issuer = issuerFor(issued.issuerPath);
  const payload: Record<string, unknown> = {
    ...issued.login.claims,
    // The protocol claims are set after the spread, so a test's claims cannot
    // weaken them by accident; only a named fault changes one.
    iss: fault === 'wrong-iss' ? `${issuer}-wrong` : issuer,
    aud: fault === 'wrong-aud' ? `not-${issued.clientId}` : issued.clientId,
    nonce: fault === 'bad-nonce' ? randomToken(16) : issued.nonce,
    iat: fault === 'expired' ? now - 2 * 3600 : now,
    exp: fault === 'expired' ? now - 3600 : now + ID_TOKEN_TTL_S,
  };
  if (fault === 'alg-none') return unsigned(payload);
  return signRs256(payload, fault === 'unknown-kid' ? rogueKey() : publishedKey());
}

/** RFC 6749 4.1.3, with `client_secret_post` client authentication and PKCE required. */
async function token(ctx: OidcContext): Promise<void> {
  const { req, sendJson } = ctx;
  const form = new URLSearchParams(await ctx.readRawBody());
  const clientId = form.get('client_id') ?? '';
  const client = clients.get(clientId);

  const refuse = (status: number, error: string, reason: string) => {
    if (client) record(clientId, { endpoint: 'token', outcome: 'refused', reason });
    sendJson(status, { error });
  };

  // Client authentication first, from the form body only. A request
  // authenticating any other way (an Authorization header) is not
  // client_secret_post and is refused, as Entra refuses a mismatched method.
  if (!client) return refuse(401, 'invalid_client', 'unknown_client');
  if (req.headers.authorization !== undefined) return refuse(401, 'invalid_client', 'not_client_secret_post');
  const secret = form.get('client_secret');
  if (secret === null || !secretsEqual(secret, client.clientSecret)) {
    return refuse(401, 'invalid_client', 'bad_client_secret');
  }
  if (form.get('grant_type') !== 'authorization_code') {
    return refuse(400, 'unsupported_grant_type', 'grant_type');
  }

  const code = form.get('code') ?? '';
  const issued = codes.get(code);
  if (!issued || issued.clientId !== clientId) return refuse(400, 'invalid_grant', 'unknown_code');
  // Single use: a code is spent by its first presentation, whatever follows.
  if (issued.used) return refuse(400, 'invalid_grant', 'code_reused');
  issued.used = true;
  if (Date.now() > issued.expiresAt) return refuse(400, 'invalid_grant', 'code_expired');
  if (form.get('redirect_uri') !== issued.redirectUri) {
    return refuse(400, 'invalid_grant', 'redirect_uri_mismatch');
  }

  // PKCE is required although discovery does not advertise it (Entra's shape).
  const verifier = form.get('code_verifier');
  if (verifier === null) return refuse(400, 'invalid_grant', 'pkce_verifier_missing');
  if (!/^[A-Za-z0-9._~-]{43,128}$/.test(verifier) || s256(verifier) !== issued.codeChallenge) {
    return refuse(400, 'invalid_grant', 'pkce_mismatch');
  }

  record(clientId, { endpoint: 'token', outcome: 'accepted', fault: issued.login.fault });
  sendJson(200, {
    access_token: randomToken(),
    token_type: 'Bearer',
    expires_in: 3600,
    scope: 'openid profile email',
    id_token: idTokenFor(issued),
  });
}

/**
 * Handles every `/oidc` route. `server.ts` calls this only for a path
 * `isOidcPath` accepts, and every path under it is answered here.
 */
export async function handleOidc(ctx: OidcContext): Promise<void> {
  const { req, url, sendJson } = ctx;
  const method = req.method ?? 'GET';

  // ---- control API -------------------------------------------------------
  if (url.pathname === '/oidc/clients' && method === 'POST') {
    const client = parseClientRequest(await ctx.readJsonObject());
    clients.set(client.clientId, client);
    pending.set(client.clientId, []);
    logs.set(client.clientId, []);
    sendJson(201, {
      client_id: client.clientId,
      redirect_uris: client.redirectUris,
      issuers: { entra_shaped: issuerFor('/oidc'), rfc9207: issuerFor('/oidc/rfc9207') },
    });
    return;
  }
  const clientMatch = /^\/oidc\/clients\/([^/]+)(\/logins|\/log)?$/.exec(url.pathname);
  if (clientMatch) {
    const clientId = decodeURIComponent(clientMatch[1]);
    if (!clients.has(clientId)) {
      sendJson(404, { error: `no client ${clientId}` });
      return;
    }
    if (clientMatch[2] === '/logins' && method === 'POST') {
      const login = parseLoginRequest(await ctx.readJsonObject());
      const queue = pending.get(clientId) ?? [];
      queue.push(login);
      pending.set(clientId, queue);
      sendJson(201, { queued: queue.length });
      return;
    }
    if (clientMatch[2] === '/log' && method === 'GET') {
      sendJson(200, logs.get(clientId) ?? []);
      return;
    }
    if (clientMatch[2] === undefined && method === 'DELETE') {
      clients.delete(clientId);
      pending.delete(clientId);
      logs.delete(clientId);
      for (const [code, issued] of codes) if (issued.clientId === clientId) codes.delete(code);
      sendJson(204, {});
      return;
    }
  }

  // ---- the provider itself -----------------------------------------------
  const route = parseIssuerRoute(url.pathname);
  if (route) {
    const { issuerPath, rest } = route;
    if (rest === '/.well-known/openid-configuration' && method === 'GET') {
      sendJson(200, discovery(issuerPath));
      return;
    }
    if (rest === '/jwks' && method === 'GET') {
      sendJson(200, jwks());
      return;
    }
    if (rest === '/authorize' && method === 'GET') {
      authorize(ctx, issuerPath);
      return;
    }
    if (rest === '/token' && method === 'POST') {
      await token(ctx);
      return;
    }
  }

  sendJson(404, { error: `no route for ${method} ${url.pathname}` });
}
