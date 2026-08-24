import type { APIRequestContext } from '@playwright/test';
import fs from 'node:fs';
import { ApiClient } from './api';
import {
  PRINCIPALS,
  PRINCIPALS_FILE,
  PRINCIPAL_NAMES,
} from '../setup/principals';
import type { PrincipalName, PrincipalsFile } from '../setup/principals';

type TokenPair = { access: string; refresh: string };

/**
 * Token pairs by `username:password`, for the life of this worker process.
 *
 * `POST /api/accounts/token/` is throttled at 3/minute per client IP
 * (`DEFAULT_THROTTLE_RATES` in dispatcharr/settings.py, applied by
 * `LoginRateThrottle`), and the whole suite runs from one IP. Module scope is
 * *per worker process*, so this cache alone cannot fix that: N workers driving
 * the same principal still spend N logins, and `seeded` runs 4 workers. The
 * cache makes repeats within one worker free; it does not bound the run.
 *
 * What bounds the run is the block below: `bootstrap` mints a fixed roster of
 * principal token pairs serially, before any worker exists, and this cache is
 * pre-loaded from the file it writes. Every `asPrincipal()` call in every
 * worker is therefore a hit, and the run's steady-state login cost is **0**
 * whatever `workers:` is set to. `e2e/setup/principals.ts` has the accounting.
 *
 * What is cached is the token pair, never the `ApiClient`:
 * `expireAccessTokenForTest()` mutates a client's in-memory tokens, so a
 * shared instance would let one test corrupt another's. Every caller gets a
 * fresh client, and `useTokens` copies the pair in rather than aliasing it.
 *
 * A cached access token going stale needs no handling here — `ApiClient`
 * already retries through its refresh path on a 401, which is unthrottled, and
 * the refresh token outlives any run.
 */
const tokenCache = new Map<string, TokenPair>();

/** Cache key. The password is part of it — see `makeUserClient`. */
function cacheKey(username: string, password: string): string {
  return `${username}:${password}`;
}

let principalsLoaded = false;

/**
 * Seed the cache from `playwright/.auth/principals.json`, once per worker.
 *
 * Lazy rather than at module load, so that *importing* the harness contract
 * never depends on `bootstrap` having run — a project without that dependency
 * can still use `makeUserClient`, which needs no roster. A missing file is
 * therefore not an error here; `makePrincipalClient` is where it becomes one,
 * and it says what to do about it.
 */
function loadPrincipals(): void {
  if (principalsLoaded) return;
  principalsLoaded = true;

  let stored: PrincipalsFile;
  try {
    stored = JSON.parse(fs.readFileSync(PRINCIPALS_FILE, 'utf8'));
  } catch {
    return;
  }

  for (const name of PRINCIPAL_NAMES) {
    const tokens = stored[name];
    if (!tokens?.access || !tokens?.refresh) continue;
    const { username, password } = PRINCIPALS[name];
    tokenCache.set(cacheKey(username, password), {
      access: tokens.access,
      refresh: tokens.refresh,
    });
  }
}

let loginsSpent = 0;

/**
 * How many `POST /api/accounts/token/` requests this **worker process** has
 * made. The budget the number is spent against is global (3/minute for the
 * whole run), so this is a lower bound on the run's spend, not the total.
 *
 * Exported so a test can assert that a code path is free rather than assuming
 * it: assert the *delta* across the call, never the absolute value, because
 * other tests share the worker.
 */
export function loginsSpentByThisWorker(): number {
  return loginsSpent;
}

async function login(
  ctx: APIRequestContext,
  username: string,
  password: string
): Promise<TokenPair> {
  loginsSpent += 1;

  // Said out loud, at the point it happens, because this is the one thing in
  // the harness that consumes a scarce global resource: three per minute for
  // the whole run, shared with every other worker. A run that prints this more
  // than once or twice is on its way to a 429 that will read like a product
  // bug. `asPrincipal()` never prints it.
  console.warn(
    `[auth] spending a login for ${username} — the suite's budget is ` +
      '3/minute across all workers and both back-to-back runs. Prefer ' +
      'asPrincipal(); see "The login throttle" in e2e/README.md.'
  );

  const res = await ctx.post('/api/accounts/token/', {
    data: { username, password },
  });
  if (!res.ok()) {
    const detail =
      res.status() === 429
        ? ' — this is the 3/minute login throttle, i.e. the harness budget ' +
          'rather than a product failure. See "The login throttle" in ' +
          'e2e/README.md.'
        : '';
    throw new Error(
      `login as ${username} failed: ${res.status()} ${await res.text()}${detail}`
    );
  }
  const { access, refresh } = await res.json();
  return { access, refresh };
}

/**
 * An `ApiClient` for one of the pre-provisioned principals.
 *
 * **Free.** The token pair was minted by `bootstrap` before any worker
 * started, so this is a cache read. Call it as often as you like, from as many
 * workers as you like.
 *
 * The principals are **shared and read-only** — four workers hold the same two
 * identities at once. Do not change a principal's `user_level`, password,
 * `channel_profiles` or existence; seed a user with `seed.user()` when you
 * need a row to mutate. `e2e/setup/principals.ts` has the reasoning.
 */
export async function makePrincipalClient(
  ctx: APIRequestContext,
  name: PrincipalName
): Promise<ApiClient> {
  loadPrincipals();

  const principal = PRINCIPALS[name];
  if (!principal) {
    throw new Error(
      `unknown principal "${name}"; known: ${PRINCIPAL_NAMES.join(', ')}`
    );
  }
  if (!tokenCache.has(cacheKey(principal.username, principal.password))) {
    throw new Error(
      `no token for principal "${name}" in ${PRINCIPALS_FILE}. That file is ` +
        'written by the bootstrap project, so a project calling asPrincipal() ' +
        "must list `dependencies: ['bootstrap']` in playwright.config.ts."
    );
  }
  return makeUserClient(ctx, principal.username, principal.password);
}

/**
 * An `ApiClient` authenticated as an arbitrary user rather than the bootstrap
 * admin. Tokens are held in memory; nothing is written to the auth files.
 *
 * **COSTS ONE LOGIN** per distinct `username:password` per worker, out of the
 * three per minute the entire run shares — and `seed.user()` generates a fresh
 * username on every call, so a seeded principal is a guaranteed cache miss
 * every time. Four such tests spread over four workers is four logins and a
 * 429 on the fourth, raised here as a hard failure.
 *
 * Reach for `asPrincipal('streamer' | 'standard')` instead. This function is
 * for the case no fixed principal can express: a user whose *properties* are
 * the subject of the test (its `channel_profiles`, a password being changed),
 * which therefore cannot be shared with three other workers. When you use it,
 * budget it — at most one such test per run, and say so in a comment at the
 * call site.
 */
export async function makeUserClient(
  ctx: APIRequestContext,
  username: string,
  password: string
): Promise<ApiClient> {
  loadPrincipals();

  // Keyed on the password too, not just the username: on a hit the password
  // argument is otherwise ignored entirely, so a caller passing the wrong
  // password for a cached username would get a working client — quietly
  // defeating any test that changes a password and asserts the old one fails.
  const key = cacheKey(username, password);
  let tokens = tokenCache.get(key);
  if (!tokens) {
    tokens = await login(ctx, username, password);
    tokenCache.set(key, tokens);
  }

  const client = new ApiClient(ctx);
  client.useTokens(tokens);
  return client;
}
