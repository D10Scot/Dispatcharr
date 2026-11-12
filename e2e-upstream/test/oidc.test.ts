import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { createHash, createPublicKey, randomBytes, verify } from 'node:crypto';
import { startServer } from '../src/server.js';
import { DEFAULT_FAULT, OIDC_FAULTS, resetOidcState } from '../src/oidc/index.js';

// The fake OP behind the SSO e2e tests (SSO spec PR S5). These pin the
// strictness the e2e suite relies on: if the OP stopped refusing a missing
// PKCE verifier, a relying party that stopped sending one would still pass.

let server: Awaited<ReturnType<typeof startServer>> | undefined;
let base = '';

const CLIENT_ID = 'mino-test-client';
const CLIENT_SECRET = 'not-a-secret-test-fixture';
const REDIRECT_URI = 'http://localhost:9191/api/accounts/oidc/test/callback/';

beforeEach(async () => {
  resetOidcState();
  server = await startServer(0);
  base = `http://127.0.0.1:${server.port}`;
});

afterEach(async () => {
  await server?.close();
  server = undefined;
});

async function readJson(res: Response): Promise<any> {
  return res.json();
}

function b64urlJson(segment: string): any {
  return JSON.parse(Buffer.from(segment, 'base64url').toString('utf8'));
}

function pkcePair(): { verifier: string; challenge: string } {
  const verifier = randomBytes(32).toString('base64url');
  return { verifier, challenge: createHash('sha256').update(verifier).digest('base64url') };
}

async function register(
  clientId = CLIENT_ID,
  redirectUris: string[] = [REDIRECT_URI],
  clientSecret = CLIENT_SECRET
): Promise<void> {
  const res = await fetch(`${base}/oidc/clients`, {
    method: 'POST',
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, redirect_uris: redirectUris }),
  });
  expect(res.status).toBe(201);
}

async function queueLogin(body: Record<string, unknown> = {}): Promise<void> {
  const res = await fetch(`${base}/oidc/clients/${CLIENT_ID}/logins`, {
    method: 'POST',
    body: JSON.stringify({ claims: { sub: 'user-1', preferred_username: 'alice' }, ...body }),
  });
  expect(res.status).toBe(201);
}

interface AuthorizeOptions {
  issuer?: '/oidc' | '/oidc/rfc9207';
  challenge?: string | null;
  redirectUri?: string;
  /** Overrides on the query: a string sets the parameter, null removes it. */
  params?: Record<string, string | null>;
  clientId?: string;
}

async function authorize(opts: AuthorizeOptions = {}): Promise<Response> {
  const params = new URLSearchParams({
    client_id: opts.clientId ?? CLIENT_ID,
    redirect_uri: opts.redirectUri ?? REDIRECT_URI,
    response_type: 'code',
    scope: 'openid profile email',
    state: 'state-1',
    nonce: 'nonce-1',
  });
  if (opts.challenge !== null) {
    params.set('code_challenge', opts.challenge ?? pkcePair().challenge);
    params.set('code_challenge_method', 'S256');
  }
  for (const [name, value] of Object.entries(opts.params ?? {})) {
    if (value === null) params.delete(name);
    else params.set(name, value);
  }
  return fetch(`${base}${opts.issuer ?? '/oidc'}/authorize?${params}`, { redirect: 'manual' });
}

async function codeFrom(res: Response): Promise<URL> {
  expect(res.status).toBe(302);
  return new URL(res.headers.get('location') ?? '');
}

async function redeem(
  code: string,
  verifier: string | null,
  extra: {
    issuer?: string;
    secret?: string;
    headers?: Record<string, string>;
    /** Overrides on the form: a string sets the field, null removes it. */
    form?: Record<string, string | null>;
  } = {}
): Promise<Response> {
  const form = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: REDIRECT_URI,
    client_id: CLIENT_ID,
    client_secret: extra.secret ?? CLIENT_SECRET,
  });
  if (verifier !== null) form.set('code_verifier', verifier);
  for (const [name, value] of Object.entries(extra.form ?? {})) {
    if (value === null) form.delete(name);
    else form.set(name, value);
  }
  return fetch(`${base}${extra.issuer ?? '/oidc'}/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...(extra.headers ?? {}) },
    body: form.toString(),
  });
}

/** A full login, returning the decoded ID token's header and payload. */
async function login(fault?: string, issuer: '/oidc' | '/oidc/rfc9207' = '/oidc') {
  await register();
  await queueLogin(fault ? { fault } : {});
  const { verifier, challenge } = pkcePair();
  const location = await codeFrom(await authorize({ issuer, challenge }));
  const res = await redeem(location.searchParams.get('code') ?? '', verifier, { issuer });
  expect(res.status).toBe(200);
  const idToken: string = (await readJson(res)).id_token;
  const [h, p, s] = idToken.split('.');
  return { location, idToken, header: b64urlJson(h), payload: b64urlJson(p), signature: s };
}

describe('fake OIDC provider: discovery and keys', () => {
  it('serves an Entra-shaped discovery document that advertises neither PKCE nor the iss parameter', async () => {
    const doc = await readJson(await fetch(`${base}/oidc/.well-known/openid-configuration`));
    expect(doc.issuer).toBe('http://e2e-upstream:8080/oidc');
    expect(doc.token_endpoint).toBe('http://e2e-upstream:8080/oidc/token');
    expect(doc.jwks_uri).toBe('http://e2e-upstream:8080/oidc/jwks');
    expect(doc.authorization_endpoint).toBe('http://127.0.0.1:9402/oidc/authorize');
    expect(doc.token_endpoint_auth_methods_supported).toEqual(['client_secret_post']);
    expect(doc.id_token_signing_alg_values_supported).toEqual(['RS256']);
    expect(doc).not.toHaveProperty('code_challenge_methods_supported');
    expect(doc).not.toHaveProperty('authorization_response_iss_parameter_supported');
  });

  it('serves a second issuer that advertises the RFC 9207 iss parameter', async () => {
    const doc = await readJson(await fetch(`${base}/oidc/rfc9207/.well-known/openid-configuration`));
    expect(doc.issuer).toBe('http://e2e-upstream:8080/oidc/rfc9207');
    expect(doc.authorization_response_iss_parameter_supported).toBe(true);
  });

  it('publishes JWKS entries with no alg member', async () => {
    const { keys } = await readJson(await fetch(`${base}/oidc/jwks`));
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatchObject({ kty: 'RSA', use: 'sig' });
    expect(keys[0]).not.toHaveProperty('alg');
  });

  it('issues honest tokens by default', () => {
    // The S5 break-check flips this to 'wrong-aud'; this pin keeps the
    // committed value from drifting there silently.
    expect(DEFAULT_FAULT).toBeUndefined();
  });
});

describe('fake OIDC provider: the happy path', () => {
  it('issues an RS256 ID token verifiable against the published JWKS', async () => {
    const { location, idToken, header, payload } = await login();
    expect(location.searchParams.get('state')).toBe('state-1');
    expect(location.searchParams.has('iss')).toBe(false);
    expect(header.alg).toBe('RS256');
    expect(payload).toMatchObject({
      iss: 'http://e2e-upstream:8080/oidc',
      aud: CLIENT_ID,
      sub: 'user-1',
      nonce: 'nonce-1',
      preferred_username: 'alice',
    });
    expect(payload.exp).toBeGreaterThan(Date.now() / 1000);

    const { keys } = await readJson(await fetch(`${base}/oidc/jwks`));
    const jwk = keys.find((k: { kid: string }) => k.kid === header.kid);
    expect(jwk).toBeDefined();
    const [h, p, s] = idToken.split('.');
    const ok = verify(
      'sha256',
      Buffer.from(`${h}.${p}`),
      createPublicKey({ key: jwk, format: 'jwk' }),
      Buffer.from(s, 'base64url')
    );
    expect(ok).toBe(true);
  });

  it('returns iss on the authorization response from the RFC 9207 issuer', async () => {
    const { location, payload } = await login(undefined, '/oidc/rfc9207');
    expect(location.searchParams.get('iss')).toBe('http://e2e-upstream:8080/oidc/rfc9207');
    expect(payload.iss).toBe('http://e2e-upstream:8080/oidc/rfc9207');
  });

  it('records what it accepted in the client log', async () => {
    await login();
    const log = await readJson(await fetch(`${base}/oidc/clients/${CLIENT_ID}/log`));
    expect(log.map((e: { endpoint: string; outcome: string }) => `${e.endpoint}:${e.outcome}`)).toEqual([
      'authorize:accepted',
      'token:accepted',
    ]);
  });
});

describe('fake OIDC provider: refusals', () => {
  it('refuses a token request with no PKCE verifier', async () => {
    await register();
    await queueLogin();
    const location = await codeFrom(await authorize());
    const res = await redeem(location.searchParams.get('code') ?? '', null);
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error: 'invalid_grant' });
  });

  it('refuses a token request whose PKCE verifier does not match the challenge', async () => {
    await register();
    await queueLogin();
    const location = await codeFrom(await authorize());
    const res = await redeem(location.searchParams.get('code') ?? '', pkcePair().verifier);
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error: 'invalid_grant' });
    const log = await readJson(await fetch(`${base}/oidc/clients/${CLIENT_ID}/log`));
    expect(log.at(-1)).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'pkce_mismatch' });
  });

  it('refuses an authorization request with no PKCE challenge, by redirect', async () => {
    await register();
    await queueLogin();
    const location = await codeFrom(await authorize({ challenge: null }));
    expect(location.searchParams.get('error')).toBe('invalid_request');
    expect(location.searchParams.has('code')).toBe(false);
  });

  it('answers an unregistered redirect URI itself rather than redirecting to it', async () => {
    await register();
    await queueLogin();
    const res = await authorize({ redirectUri: 'http://evil.example/cb' });
    expect(res.status).toBe(400);
    expect(res.headers.get('location')).toBeNull();
  });

  it('denies a login nobody queued', async () => {
    await register();
    const location = await codeFrom(await authorize());
    expect(location.searchParams.get('error')).toBe('access_denied');
  });

  it('spends a code on its first presentation', async () => {
    await register();
    await queueLogin();
    const { verifier, challenge } = pkcePair();
    const location = await codeFrom(await authorize({ challenge }));
    const code = location.searchParams.get('code') ?? '';
    expect((await redeem(code, verifier)).status).toBe(200);
    const again = await redeem(code, verifier);
    expect(again.status).toBe(400);
    expect(await readJson(again)).toEqual({ error: 'invalid_grant' });
  });

  it('refuses a wrong client secret', async () => {
    await register();
    await queueLogin();
    const { verifier, challenge } = pkcePair();
    const location = await codeFrom(await authorize({ challenge }));
    const res = await redeem(location.searchParams.get('code') ?? '', verifier, { secret: 'wrong' });
    expect(res.status).toBe(401);
    expect(await readJson(res)).toEqual({ error: 'invalid_client' });
  });

  it('refuses client authentication by Authorization header (not client_secret_post)', async () => {
    await register();
    await queueLogin();
    const { verifier, challenge } = pkcePair();
    const location = await codeFrom(await authorize({ challenge }));
    const basic = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64');
    const res = await redeem(location.searchParams.get('code') ?? '', verifier, {
      headers: { Authorization: `Basic ${basic}` },
    });
    expect(res.status).toBe(401);
  });

  it('rejects an unknown fault name when queueing a login', async () => {
    await register();
    const res = await fetch(`${base}/oidc/clients/${CLIENT_ID}/logins`, {
      method: 'POST',
      body: JSON.stringify({ claims: { sub: 'x' }, fault: 'no-such-fault' }),
    });
    expect(res.status).toBe(400);
  });
});

describe('fake OIDC provider: faults', () => {
  it('names exactly the eight faults', () => {
    expect([...OIDC_FAULTS].sort()).toEqual(
      [
        'alg-none',
        'bad-nonce',
        'bad-signature',
        'expired',
        'missing-iss-param',
        'unknown-kid',
        'wrong-aud',
        'wrong-iss',
      ].sort()
    );
  });

  it('wrong-iss signs a token whose iss is not the issuer', async () => {
    const { payload } = await login('wrong-iss');
    expect(payload.iss).not.toBe('http://e2e-upstream:8080/oidc');
  });

  it('wrong-aud signs a token whose aud is not the client', async () => {
    const { payload } = await login('wrong-aud');
    expect(payload.aud).not.toBe(CLIENT_ID);
  });

  it('bad-nonce signs a token whose nonce is not the request nonce', async () => {
    const { payload } = await login('bad-nonce');
    expect(payload.nonce).not.toBe('nonce-1');
  });

  it('expired signs a token whose exp is in the past', async () => {
    const { payload } = await login('expired');
    expect(payload.exp).toBeLessThan(Date.now() / 1000);
  });

  it('alg-none issues an unsigned token under the published kid', async () => {
    const { header, signature } = await login('alg-none');
    expect(header.alg).toBe('none');
    expect(signature).toBe('');
    // The published kid, so a relying party's key lookup succeeds and only its
    // algorithm check can refuse the token.
    const { keys } = await readJson(await fetch(`${base}/oidc/jwks`));
    expect(keys.map((k: { kid: string }) => k.kid)).toEqual([header.kid]);
  });

  it('bad-signature signs honest claims under the published kid with a key that does not verify', async () => {
    const { idToken, header, payload } = await login('bad-signature');
    expect(header.alg).toBe('RS256');
    const { keys } = await readJson(await fetch(`${base}/oidc/jwks`));
    expect(keys.map((k: { kid: string }) => k.kid)).toEqual([header.kid]);
    // Every claim is honest, so the signature is the only thing wrong with it.
    expect(payload).toMatchObject({ iss: 'http://e2e-upstream:8080/oidc', aud: CLIENT_ID, nonce: 'nonce-1' });
    expect(payload.exp).toBeGreaterThan(Date.now() / 1000);
    const [h, p, s] = idToken.split('.');
    expect(s.length, 'a real RS256 signature, not an empty or truncated one').toBe(342);
    const ok = verify(
      'sha256',
      Buffer.from(`${h}.${p}`),
      createPublicKey({ key: keys[0], format: 'jwk' }),
      Buffer.from(s, 'base64url')
    );
    expect(ok, 'the signature does not verify against the published key').toBe(false);
  });

  it('unknown-kid signs with a key the JWKS never publishes', async () => {
    const { header } = await login('unknown-kid');
    const { keys } = await readJson(await fetch(`${base}/oidc/jwks`));
    expect(keys.map((k: { kid: string }) => k.kid)).not.toContain(header.kid);
  });

  it('missing-iss-param omits iss from the RFC 9207 issuer while it still advertises it', async () => {
    const { location } = await login('missing-iss-param', '/oidc/rfc9207');
    expect(location.searchParams.has('iss')).toBe(false);
  });
});

// Every refusal branch in src/oidc/ is held by a case that reddens when the branch is
// removed (SSO S5 fix round 1). Each asserts the client-visible answer and, where the OP
// knows the client, the fixed reason in its log, so a removed branch cannot pass by
// falling through to a neighbouring refusal.

async function lastLog(clientId = CLIENT_ID): Promise<Record<string, unknown> | undefined> {
  return (await readJson(await fetch(`${base}/oidc/clients/${clientId}/log`))).at(-1);
}

/** Register, queue one login and authorize, returning the code and its verifier. */
async function issueCode(opts: AuthorizeOptions = {}): Promise<{ code: string; verifier: string }> {
  await register();
  await queueLogin();
  const { verifier, challenge } = pkcePair();
  const location = await codeFrom(await authorize({ challenge, ...opts }));
  const code = location.searchParams.get('code');
  expect(code, `authorize issued a code: ${location}`).toBeTruthy();
  return { code: code ?? '', verifier };
}

describe('fake OIDC provider: token endpoint refusals', () => {
  it('refuses a token request with no client_secret', async () => {
    const { code, verifier } = await issueCode();
    const res = await redeem(code, verifier, { form: { client_secret: null } });
    expect(res.status).toBe(401);
    expect(await readJson(res)).toEqual({ error: 'invalid_client' });
    expect(await lastLog()).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'bad_client_secret' });
  });

  it('refuses a token request whose redirect_uri differs from the one the code was issued for', async () => {
    const other = 'http://localhost:9191/api/accounts/oidc/other/callback/';
    await register(CLIENT_ID, [REDIRECT_URI, other]);
    await queueLogin();
    const { verifier, challenge } = pkcePair();
    const code = (await codeFrom(await authorize({ challenge }))).searchParams.get('code') ?? '';
    const res = await redeem(code, verifier, { form: { redirect_uri: other } });
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error: 'invalid_grant' });
    expect(await lastLog()).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'redirect_uri_mismatch' });
  });

  it('refuses a code presented by a client other than the one it was issued to', async () => {
    const { code, verifier } = await issueCode();
    const second = 'second-test-client';
    await register(second, [REDIRECT_URI], 'second-not-a-secret');
    const res = await redeem(code, verifier, { form: { client_id: second }, secret: 'second-not-a-secret' });
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error: 'invalid_grant' });
    expect(await lastLog(second)).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'unknown_code' });
  });

  it('refuses a token request from an unregistered client', async () => {
    const { code, verifier } = await issueCode();
    const res = await redeem(code, verifier, { form: { client_id: 'nobody' } });
    expect(res.status).toBe(401);
    expect(await readJson(res)).toEqual({ error: 'invalid_client' });
  });

  it('refuses a grant type other than authorization_code', async () => {
    const { code, verifier } = await issueCode();
    const res = await redeem(code, verifier, { form: { grant_type: 'refresh_token' } });
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error: 'unsupported_grant_type' });
    expect(await lastLog()).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'grant_type' });
  });

  it('refuses a code it never issued', async () => {
    const { verifier } = await issueCode();
    const res = await redeem('never-issued', verifier);
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error: 'invalid_grant' });
    expect(await lastLog()).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'unknown_code' });
  });

  it('refuses a code presented after it expired', async () => {
    const { code, verifier } = await issueCode();
    // Only Date is faked: the server's sockets and timers stay real.
    vi.useFakeTimers({ toFake: ['Date'] });
    try {
      vi.setSystemTime(Date.now() + 61_000);
      const res = await redeem(code, verifier);
      expect(res.status).toBe(400);
      expect(await readJson(res)).toEqual({ error: 'invalid_grant' });
      expect(await lastLog()).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'code_expired' });
    } finally {
      vi.useRealTimers();
    }
  });

  it('refuses a malformed verifier even when it hashes to the challenge', async () => {
    const short = 'too-short-to-be-a-verifier';
    const challenge = createHash('sha256').update(short).digest('base64url');
    await register();
    await queueLogin();
    const code = (await codeFrom(await authorize({ challenge }))).searchParams.get('code') ?? '';
    const res = await redeem(code, short);
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error: 'invalid_grant' });
    expect(await lastLog()).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'pkce_mismatch' });
  });

  it('logs the missing-verifier refusal by its own reason', async () => {
    const { code } = await issueCode();
    const res = await redeem(code, null);
    expect(res.status).toBe(400);
    expect(await lastLog()).toMatchObject({ endpoint: 'token', outcome: 'refused', reason: 'pkce_verifier_missing' });
  });
});

describe('fake OIDC provider: authorization endpoint refusals', () => {
  it('answers an unregistered client itself rather than redirecting', async () => {
    const res = await authorize({ clientId: 'nobody' });
    expect(res.status).toBe(400);
    expect(res.headers.get('location')).toBeNull();
    expect(await readJson(res)).toEqual({ error: 'invalid_request', reason: 'unknown_client' });
  });

  for (const [name, params, error, reason] of [
    ['a response_type other than code', { response_type: 'token' }, 'unsupported_response_type', 'response_type'],
    ['a scope without openid', { scope: 'profile email' }, 'invalid_scope', 'no_openid_scope'],
    ['a request with no nonce', { nonce: null }, 'invalid_request', 'no_nonce'],
    ['a plain PKCE challenge method', { code_challenge_method: 'plain' }, 'invalid_request', 'pkce_required'],
  ] as const) {
    it(`refuses ${name}, by redirect`, async () => {
      await register();
      await queueLogin();
      const location = await codeFrom(await authorize({ params }));
      expect(location.searchParams.get('error')).toBe(error);
      expect(location.searchParams.get('state')).toBe('state-1');
      expect(location.searchParams.has('code')).toBe(false);
      expect(await lastLog()).toMatchObject({ endpoint: 'authorize', outcome: 'refused', reason });
    });
  }

  it('logs the no-challenge refusal by its own reason', async () => {
    await register();
    await queueLogin();
    await codeFrom(await authorize({ challenge: null }));
    expect(await lastLog()).toMatchObject({ endpoint: 'authorize', outcome: 'refused', reason: 'pkce_required' });
  });

  it('logs the unregistered-redirect refusal by its own reason', async () => {
    await register();
    await queueLogin();
    expect((await authorize({ redirectUri: 'http://evil.example/cb' })).status).toBe(400);
    expect(await lastLog()).toMatchObject({
      endpoint: 'authorize',
      outcome: 'refused',
      reason: 'redirect_uri_not_registered',
    });
  });

  it('logs the nothing-queued refusal by its own reason', async () => {
    await register();
    await codeFrom(await authorize());
    expect(await lastLog()).toMatchObject({ endpoint: 'authorize', outcome: 'refused', reason: 'no_login_queued' });
  });
});

describe('fake OIDC provider: control API refusals', () => {
  async function postClient(body: Record<string, unknown>): Promise<Response> {
    return fetch(`${base}/oidc/clients`, { method: 'POST', body: JSON.stringify(body) });
  }
  const good = { client_id: 'c1', client_secret: 's1', redirect_uris: [REDIRECT_URI] };

  async function expect400(res: Response, error: string): Promise<void> {
    expect(res.status).toBe(400);
    expect(await readJson(res)).toEqual({ error });
  }

  it('refuses a client id outside [A-Za-z0-9._-]', async () => {
    await expect400(await postClient({ ...good, client_id: 'has space' }), "'client_id' must be 1-128 characters of [A-Za-z0-9._-]");
  });

  it('refuses an empty client secret', async () => {
    await expect400(await postClient({ ...good, client_secret: '' }), "'client_secret' must be a non-empty string");
  });

  it('refuses redirect URIs that are not a non-empty list of http(s) URLs', async () => {
    const error = "'redirect_uris' must be a non-empty list of http(s) URLs";
    await expect400(await postClient({ ...good, redirect_uris: [] }), error);
    await expect400(await postClient({ ...good, redirect_uris: ['javascript:alert(1)'] }), error);
  });

  it('refuses a queued login whose claims are not an object', async () => {
    await register();
    const res = await fetch(`${base}/oidc/clients/${CLIENT_ID}/logins`, {
      method: 'POST',
      body: JSON.stringify({ claims: ['sub'] }),
    });
    await expect400(res, "'claims' must be a JSON object");
  });

  it('refuses a queued login with no sub', async () => {
    await register();
    const res = await fetch(`${base}/oidc/clients/${CLIENT_ID}/logins`, {
      method: 'POST',
      body: JSON.stringify({ claims: { preferred_username: 'alice' } }),
    });
    await expect400(res, "'claims.sub' must be a non-empty string");
  });

  it('answers 404 for a client it does not know', async () => {
    const res = await fetch(`${base}/oidc/clients/nobody/log`);
    expect(res.status).toBe(404);
    expect(await readJson(res)).toEqual({ error: 'no client nobody' });
  });

  it('answers 404 for a path under /oidc it does not serve', async () => {
    for (const p of ['/oidc/token', '/oidc/nowhere']) {
      // A short client-side timeout: with no catch-all the request would hang, and the
      // abort names that rather than the suite's generic timeout.
      const res = await fetch(`${base}${p}`, { signal: AbortSignal.timeout(2000) });
      expect(res.status, p).toBe(404);
      expect(await readJson(res)).toEqual({ error: `no route for GET ${p}` });
    }
  });
});
