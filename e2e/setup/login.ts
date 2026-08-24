/**
 * Logging in from the serial setup phase, under the login throttle.
 *
 * `POST /api/accounts/token/` allows 3 requests per minute per client IP, and
 * one host is one IP — so the budget is shared by every login the whole run
 * makes, including the admin's. `bootstrap` is the only phase that may spend
 * from it (see `principals.ts` for why), and it is also the only phase that
 * may *wait* for it: it is serial, nothing runs in parallel with it, and no
 * test is blocked on it. A worker can do neither, which is why the worker-side
 * login in `fixtures/auth.ts` deliberately has no backoff — a 30-second test
 * timeout cannot absorb a 60-second window, and three other workers would
 * stall behind it.
 *
 * Every login in `bootstrap` — the admin's included — goes through here. An
 * unprotected login is a 429 waiting to be reported as a product bug, and the
 * admin's is the *first* login of a cold run and the one everything else
 * depends on.
 */
import type { APIRequestContext } from '@playwright/test';

export type Credentials = { username: string; password: string };
export type TokenPair = { access: string; refresh: string };

/**
 * The `access` field of a token or refresh response, or undefined if the body
 * does not carry one as a string.
 *
 * `res.json()` is `any`, and an `any` flowing into a `TokenPair` is how a
 * malformed 200 becomes `Authorization: Bearer undefined` on every subsequent
 * request — a cascade of 401s that names neither this response nor this
 * function. Narrow once, here, and let each caller say what a miss means:
 * `bootstrap` falls back to a login, the workers raise.
 */
export function accessTokenOf(body: unknown): string | undefined {
  const access = (body as { access?: unknown } | null | undefined)?.access;
  return typeof access === 'string' ? access : undefined;
}

/** Both halves of a token response, or undefined unless both are strings. */
export function tokenPairOf(body: unknown): TokenPair | undefined {
  const access = accessTokenOf(body);
  const refresh = (body as { refresh?: unknown } | null | undefined)?.refresh;
  if (access === undefined || typeof refresh !== 'string') return undefined;
  return { access, refresh };
}

/**
 * How long to wait for a window to clear when the 429 carries no usable
 * `Retry-After`. DRF sets that header to the exact remaining time, so this
 * bound (a full window plus a second) is only ever the fallback.
 */
const DEFAULT_RETRY_AFTER_SECONDS = 61;

/**
 * One wait is a throttle window; needing a second means the budget is being
 * spent by something outside this run, which is a situation to report rather
 * than to sit through. A password repair shares this allowance rather than
 * getting its own — a login that is throttled *and* has the wrong password is
 * pathological, and the error names both.
 */
const MAX_THROTTLE_WAITS = 1;

/**
 * The longest one `loginWithThrottleBackoff` call can block, ignoring request
 * time. `playwright.config.ts` sizes the `bootstrap` project's timeout from
 * this and the roster length, so the two cannot drift apart.
 */
export const MAX_LOGIN_WAIT_MS =
  MAX_THROTTLE_WAITS * DEFAULT_RETRY_AFTER_SECONDS * 1000;

/**
 * How close to `exp` an access token may be before it is renewed rather than
 * reused. `fixtures/api.ts` applies the same 120 seconds for the same reason
 * on the worker side; this is the setup side of that policy, and the two are
 * deliberately separate because a worker refreshes a token it is about to use
 * while `bootstrap` refreshes one it is about to hand to somebody else for the
 * length of a run.
 *
 * Generous, because renewal is free (`TokenRefreshView` is unthrottled) and a
 * token that expires in a worker's hands costs a hang.
 */
export const TOKEN_EXPIRY_MARGIN_SECONDS = 120;

/** The `exp` claim in unix seconds, or undefined if this isn't a readable JWT. */
export function jwtExp(accessToken: string): number | undefined {
  try {
    const payload = accessToken.split('.')[1];
    const exp = JSON.parse(Buffer.from(payload, 'base64').toString('utf8')).exp;
    return typeof exp === 'number' ? exp : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Whether an access token has more than the margin left on it. Unreadable
 * tokens count as spent — the caller then renews, which is free, rather than
 * handing on something it cannot vouch for.
 */
export function hasLifeLeft(accessToken: string): boolean {
  const exp = jwtExp(accessToken);
  if (exp === undefined) return false;
  return exp - TOKEN_EXPIRY_MARGIN_SECONDS > Date.now() / 1000;
}

export type LoginOptions = {
  /**
   * Called once if the credentials are refused, to repair them, before one
   * retry. Must throw if the repair fails — otherwise the retry gets the same
   * 401 and this function reports the login as broken when the repair was.
   *
   * Costs whatever the repair costs, and the retried login spends a **second**
   * login from the budget for that principal. Only pass it where the repair
   * is genuinely possible: an admin resetting a non-admin's password.
   */
  repairCredentials?: () => Promise<void>;
};

/**
 * Obtain a token pair, waiting out one throttle window if the budget is spent.
 *
 * Spends 1 login, or 2 if `repairCredentials` fires.
 */
export async function loginWithThrottleBackoff(
  request: APIRequestContext,
  credentials: Credentials,
  options: LoginOptions = {}
): Promise<TokenPair> {
  const { username, password } = credentials;
  let waits = 0;
  let repaired = false;

  for (;;) {
    const res = await request.post('/api/accounts/token/', {
      data: { username, password },
    });

    if (res.ok()) {
      const tokens = tokenPairOf(await res.json());
      if (tokens) return tokens;
      throw new Error(
        `login as ${username} returned 200 with no usable token pair. The ` +
          'response was accepted but carried no string `access`/`refresh`, ' +
          'so this is the token endpoint answering something unexpected, not ' +
          'a credential or throttle failure.'
      );
    }

    if (res.status() === 429 && waits < MAX_THROTTLE_WAITS) {
      waits += 1;
      const header = Number(res.headers()['retry-after']);
      const seconds =
        Number.isFinite(header) && header > 0
          ? header + 1
          : DEFAULT_RETRY_AFTER_SECONDS;
      console.warn(
        `[bootstrap] the login for ${username} was throttled — this is the ` +
          "suite's own 3/minute budget, not a product failure. Waiting " +
          `${seconds}s for the window to clear, then retrying. See "The login ` +
          'throttle" in e2e/README.md.'
      );
      await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
      continue;
    }

    if (res.status() === 401 && options.repairCredentials && !repaired) {
      repaired = true;
      await options.repairCredentials();
      continue;
    }

    const detail =
      res.status() === 429
        ? ' — the 3/minute login throttle, after already waiting out one ' +
          'window. Something outside this run is spending the budget: another ' +
          'test run against the same instance, or a browser logging in. See ' +
          '"The login throttle" in e2e/README.md.'
        : '';
    throw new Error(
      `login as ${username} failed: ${res.status()} ${await res.text()}${detail}`
    );
  }
}
