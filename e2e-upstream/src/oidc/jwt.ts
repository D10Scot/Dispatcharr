/**
 * The fake OP's keys and its ID-token signer, on `node:crypto` alone.
 *
 * No JOSE library: the package declares no runtime dependency (its Dockerfile's
 * runtime stage copies no `node_modules`), and RS256 is two lines of
 * `crypto.sign`. That is also why it is RS256 only — the one algorithm live
 * Entra advertises (SSO spec 3.5) and the default a provider is created with.
 *
 * Keys are generated when the process starts and never written anywhere: a
 * restarted provider has new keys, and Mino refetches the JWKS on an unknown
 * `kid` (SSO spec 3.4). Nothing here is a credential worth keeping.
 */
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import type { KeyObject } from 'node:crypto';

export interface SigningKey {
  kid: string;
  privateKey: KeyObject;
  publicKey: KeyObject;
}

function base64url(input: Buffer | string): string {
  return Buffer.from(input).toString('base64url');
}

function makeKey(): SigningKey {
  const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const jwk = publicKey.export({ format: 'jwk' });
  // A stable, opaque id derived from the modulus, the way a real OP's is opaque.
  const kid = createHash('sha256').update(String(jwk.n)).digest('base64url').slice(0, 16);
  return { kid, privateKey, publicKey };
}

let published: SigningKey | undefined;
let rogue: SigningKey | undefined;

/** The key the JWKS publishes and every ordinary ID token is signed with. */
export function publishedKey(): SigningKey {
  published ??= makeKey();
  return published;
}

/**
 * A key the JWKS never publishes. The `unknown-kid` fault signs with it under its
 * own `kid`, which no refetch of the JWKS will ever find; the `bad-signature`
 * fault signs with it under the PUBLISHED `kid`, so the token names a key the
 * relying party holds and its signature does not verify against that key.
 */
export function rogueKey(): SigningKey {
  rogue ??= makeKey();
  return rogue;
}

/**
 * The JWKS document. Entries carry no `alg` member, as Entra's do not (SSO spec
 * 3.4): Mino must take the algorithm from the provider's configuration, never
 * guess it from the key.
 */
export function jwks(): { keys: Record<string, unknown>[] } {
  const key = publishedKey();
  const jwk = key.publicKey.export({ format: 'jwk' });
  return { keys: [{ kty: jwk.kty, use: 'sig', kid: key.kid, n: jwk.n, e: jwk.e }] };
}

/**
 * A compact RS256 JWS over `payload`, signed with `key`'s private key. The
 * header's `kid` is `key`'s own unless `kid` names another, which only the
 * `bad-signature` fault does.
 */
export function signRs256(payload: Record<string, unknown>, key: SigningKey, kid: string = key.kid): string {
  const header = { alg: 'RS256', typ: 'JWT', kid };
  const signingInput = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(payload))}`;
  const signature = sign('sha256', Buffer.from(signingInput), key.privateKey);
  return `${signingInput}.${signature.toString('base64url')}`;
}

/**
 * An unsecured JWT (`alg: none`, empty signature), for the `alg-none` fault. It
 * carries `kid`, the published key's, so a relying party that resolves the key
 * first finds one and reaches its algorithm check rather than stopping at an
 * absent `kid`.
 */
export function unsigned(payload: Record<string, unknown>, kid: string): string {
  const header = { alg: 'none', typ: 'JWT', kid };
  return `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(payload))}.`;
}

/** RFC 7636 4.6: `BASE64URL(SHA256(ASCII(code_verifier)))`. */
export function s256(verifier: string): string {
  return createHash('sha256').update(verifier, 'ascii').digest('base64url');
}
