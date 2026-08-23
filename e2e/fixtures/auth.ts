import type { APIRequestContext } from '@playwright/test';
import { ApiClient } from './api';

type TokenPair = { access: string; refresh: string };

/**
 * Token pairs by username, for the life of this worker process.
 *
 * `POST /api/accounts/token/` is throttled at 3/minute per client IP
 * (`DEFAULT_THROTTLE_RATES` in dispatcharr/settings.py, applied by
 * `LoginRateThrottle`), and the whole suite runs from one IP — a budget the
 * bootstrap project is already spending from. One login per `asUser()` call
 * therefore exhausts it as soon as a spec drives more than a couple of
 * principals, which is exactly what an authorization matrix does. Caching
 * means N tests sharing a principal cost one login between them.
 *
 * Module scope is per worker process, which matches the parallelism that
 * causes the problem.
 *
 * What is cached is the token pair, never the `ApiClient`:
 * `expireAccessTokenForTest()` mutates a client's in-memory tokens, so a
 * shared instance would let one test corrupt another's. Every caller gets a
 * fresh client, and `useTokens` copies the pair in rather than aliasing it.
 *
 * A cached access token going stale needs no handling here — `ApiClient`
 * already retries through its refresh path on a 401, and the refresh token
 * outlives any run.
 */
const tokenCache = new Map<string, TokenPair>();

async function login(
  ctx: APIRequestContext,
  username: string,
  password: string
): Promise<TokenPair> {
  const res = await ctx.post('/api/accounts/token/', {
    data: { username, password },
  });
  if (!res.ok()) {
    throw new Error(
      `login as ${username} failed: ${res.status()} ${await res.text()}`
    );
  }
  const { access, refresh } = await res.json();
  return { access, refresh };
}

/**
 * An ApiClient authenticated as an arbitrary user rather than the bootstrap
 * admin. Tokens are held in memory; nothing is written to the auth files.
 */
export async function makeUserClient(
  ctx: APIRequestContext,
  username: string,
  password: string
): Promise<ApiClient> {
  // Keyed on the password too, not just the username: on a hit the password
  // argument is otherwise ignored entirely, so a caller passing the wrong
  // password for a cached username would get a working client — quietly
  // defeating any test that changes a password and asserts the old one fails.
  const key = `${username}:${password}`;
  let tokens = tokenCache.get(key);
  if (!tokens) {
    tokens = await login(ctx, username, password);
    tokenCache.set(key, tokens);
  }

  const client = new ApiClient(ctx);
  client.useTokens(tokens);
  return client;
}
