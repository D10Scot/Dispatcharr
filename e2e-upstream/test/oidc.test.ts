import { describe, it, expect, afterEach, beforeEach } from 'vitest';
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

async function register(): Promise<void> {
  const res = await fetch(`${base}/oidc/clients`, {
    method: 'POST',
    body: JSON.stringify({ client_id: CLIENT_ID, client_secret: CLIENT_SECRET, redirect_uris: [REDIRECT_URI] }),
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
}

async function authorize(opts: AuthorizeOptions = {}): Promise<Response> {
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
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
  return fetch(`${base}${opts.issuer ?? '/oidc'}/authorize?${params}`, { redirect: 'manual' });
}

async function codeFrom(res: Response): Promise<URL> {
  expect(res.status).toBe(302);
  return new URL(res.headers.get('location') ?? '');
}

async function redeem(
  code: string,
  verifier: string | null,
  extra: { issuer?: string; secret?: string; headers?: Record<string, string> } = {}
): Promise<Response> {
  const form = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: REDIRECT_URI,
    client_id: CLIENT_ID,
    client_secret: extra.secret ?? CLIENT_SECRET,
  });
  if (verifier !== null) form.set('code_verifier', verifier);
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
  it('names exactly the seven faults', () => {
    expect([...OIDC_FAULTS].sort()).toEqual(
      ['alg-none', 'bad-nonce', 'expired', 'missing-iss-param', 'unknown-kid', 'wrong-aud', 'wrong-iss'].sort()
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

  it('alg-none issues an unsigned token', async () => {
    const { header, signature } = await login('alg-none');
    expect(header.alg).toBe('none');
    expect(signature).toBe('');
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
