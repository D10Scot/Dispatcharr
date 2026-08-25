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
 * reused. The **one** margin for the whole harness: `bootstrap` applies it to a
 * token it is about to hand to somebody else for the length of a run, and
 * `fixtures/api.ts` applies it to one a worker is about to use. Those were once
 * two copies of the same literal described as "deliberately separate", with
 * nothing keeping them equal — which is a drift bug waiting rather than a
 * policy. If a caller ever genuinely needs a different margin, give
 * `hasLifeLeft` a parameter; do not copy the constant.
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

/**
 * A refresh that did not produce a token, and enough to say why.
 *
 * `status` is the discriminator callers actually need: a **200** here means the
 * endpoint accepted the refresh token and answered with no usable `access`,
 * which is a different failure from a refusal and deserves a different message.
 * A **500** is the product returning the wrong status when the refresh token
 * names a deleted user (D10Scot/Dispatcharr#12 — `rest_framework_simplejwt`
 * does a bare `.get()` and lets `User.DoesNotExist` escape).
 */
export type RefreshFailure = {
  access?: undefined;
  status: number;
  detail: string;
};

export type RefreshResult = { access: string } | RefreshFailure;

/**
 * Exchange a refresh token for a new access token. **Free** — `TokenRefreshView`
 * carries no `throttle_classes` and `DEFAULT_THROTTLE_CLASSES` is empty, so this
 * spends nothing from the 3/minute login budget.
 *
 * The single implementation for the whole harness. It was three: `bootstrap`,
 * `provisionPrincipals` and `ApiClient` each posted this body and narrowed with
 * `accessTokenOf`, but disagreed on what a miss meant and on whether a
 * 200-without-`access` counted as one. Narrowing happens once, here — the same
 * split `accessTokenOf` already makes — and each caller still says what a miss
 * means for it: the setup paths fall through to a login, the workers raise.
 */
export async function refreshAccessToken(
  request: APIRequestContext,
  refreshToken: string
): Promise<RefreshResult> {
  const res = await request.post('/api/accounts/token/refresh/', {
    data: { refresh: refreshToken },
  });
  // `res.text()` after `res.json()` is safe: Playwright buffers the body, so
  // both read the same bytes rather than a consumed stream.
  if (!res.ok()) return { status: res.status(), detail: await res.text() };
  const access = accessTokenOf(await res.json());
  if (access === undefined) {
    return { status: res.status(), detail: await res.text() };
  }
  return { access };
}

/** Who an access token authenticates. */
export type Identity = { username: string; user_level: number };

/**
 * Who an access token authenticates, or null if it authenticates nobody.
 *
 * `users/me` is the one `UserViewSet` action that opts down to `Authenticated`
 * rather than `IsAdmin` (`apps/accounts/api_views.py`), so even a Streamer can
 * call it — which makes it the only honest liveness probe available for every
 * principal the harness holds, admin included. It costs nothing from the login
 * budget.
 *
 * Both fields are checked, not just the username: `user_level` is compared
 * against the roster by `provisionPrincipals`, and an absent one would compare
 * `undefined !== 0` and report a Streamer as drifted on every run.
 */
export async function whoAmI(
  request: APIRequestContext,
  access: string
): Promise<Identity | null> {
  const res = await request.get('/api/accounts/users/me/', {
    headers: { Authorization: `Bearer ${access}` },
  });
  if (!res.ok()) return null;
  const body: Partial<Identity> | null = await res.json();
  if (typeof body?.username !== 'string') return null;
  if (typeof body.user_level !== 'number') return null;
  return { username: body.username, user_level: body.user_level };
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
