/**
 * The fixed, pre-provisioned non-admin principals.
 *
 * ---------------------------------------------------------------------------
 * Why these exist
 * ---------------------------------------------------------------------------
 * `POST /api/accounts/token/` is throttled at 3 requests per minute per client
 * IP (`dispatcharr/settings.py` `"login": "3/minute"`, enforced by
 * `LoginRateThrottle`, applied to `TokenObtainPairView`). The whole suite runs
 * from one IP, so **three logins per minute is the budget for everything** —
 * every worker, every project, every back-to-back re-run.
 *
 * Logging in per test, or even per worker, cannot fit in that: the cost scales
 * with `workers:` and with the number of principals a spec drives, and the
 * budget does not. The only shape that fits is to mint a *bounded* set of
 * token pairs **once, serially, before any worker starts** and hand the tokens
 * to workers as data. `bootstrap` is that serial phase — both parallel
 * projects list it in `dependencies:` — so provisioning lives here and runs
 * from there.
 *
 * The resulting steady-state cost of a full run is **0 logins**: the pairs are
 * persisted to `playwright/.auth/principals.json` (gitignored, like
 * `tokens.json`) and reused across runs, and a stale access token is renewed
 * through the *unthrottled* refresh endpoint rather than by logging in again.
 * The cold cost — first run after `./scripts/e2e_up.sh --reset`, or more than
 * `SIMPLE_JWT.REFRESH_TOKEN_LIFETIME` (1 day) since the last login — is one
 * login per principal, plus one for the admin: **3, which is exactly the
 * per-minute cap**. That is why every login `bootstrap` makes, the admin's
 * included, goes through `loginWithThrottleBackoff` (`./login.ts`) and waits a
 * window out rather than failing: this phase is serial and nothing is waiting
 * on it, so it can afford the minute. A worker cannot.
 *
 * Two things can push the cold path past 3. **Adding a principal** costs one
 * more login — add one only if no existing principal can express the case.
 * And a principal whose **password has drifted** spends a second login on the
 * repair retry. Both are absorbed by the backoff rather than failing the run,
 * at the price of a wait on the first run after a reset.
 *
 * ---------------------------------------------------------------------------
 * What they are for, and what they are not for
 * ---------------------------------------------------------------------------
 * These are **shared, read-only identities**. Four workers run against the
 * same rows concurrently, so a test that changes a principal — its
 * `user_level`, its password, its `channel_profiles`, or its existence —
 * corrupts every other test in flight, and the damage outlives the run.
 *
 * Use them to *act as* a non-admin. To have a user *row* to mutate or assert
 * on, use `seed.user()`, which generates a unique username per call for
 * exactly this reason. The two are complementary, not alternatives: seeding a
 * row is unthrottled and free, obtaining a token for it is neither.
 *
 * NOT SECRET. These passwords are committed to a public repository, for the
 * same reasons set out at length in `credentials.ts`: the container is
 * published on 127.0.0.1 only, and the file they would otherwise be persisted
 * to already holds live admin JWTs.
 */
import type { APIRequestContext } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { hasLifeLeft, loginWithThrottleBackoff } from './login';
import type { TokenPair } from './login';

export type PrincipalName = 'streamer' | 'standard';

export type Principal = {
  username: string;
  password: string;
  email: string;
  /** `User.UserLevel`: Streamer 0, Standard 1, Admin 10. */
  user_level: number;
};

/**
 * One principal per non-admin `user_level` the product distinguishes.
 * Admin is not here — it is the bootstrap account in `credentials.ts`.
 */
export const PRINCIPALS: Record<PrincipalName, Principal> = {
  streamer: {
    username: 'e2e-streamer',
    password: 'Streamer-Horse-Battery-Staple-42!',
    email: 'e2e-streamer@example.com',
    user_level: 0,
  },
  standard: {
    username: 'e2e-standard',
    password: 'Standard-Horse-Battery-Staple-42!',
    email: 'e2e-standard@example.com',
    user_level: 1,
  },
};

export const PRINCIPAL_NAMES = Object.keys(PRINCIPALS) as PrincipalName[];

/** Beside `tokens.json`, under the same gitignored directory. */
export const PRINCIPALS_FILE = 'playwright/.auth/principals.json';

export type PrincipalTokens = {
  username: string;
  user_level: number;
  access: string;
  refresh: string;
};

export type PrincipalsFile = Partial<Record<PrincipalName, PrincipalTokens>>;

/** Whatever `principals.json` holds, or `{}` if it is missing or unreadable. */
function readStored(): PrincipalsFile {
  try {
    const parsed = JSON.parse(fs.readFileSync(PRINCIPALS_FILE, 'utf8'));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Write through a temp file and rename. Nothing else writes this file — it is
 * produced serially by `bootstrap` and only ever read afterwards — but a
 * reader must still never catch a half-written file if a run is interrupted
 * here and the next one starts.
 */
function writeStored(tokens: PrincipalsFile): void {
  fs.mkdirSync(path.dirname(PRINCIPALS_FILE), { recursive: true });
  const temp = path.join(
    path.dirname(PRINCIPALS_FILE),
    `.principals.${process.pid}.${Date.now()}.tmp`
  );
  fs.writeFileSync(temp, JSON.stringify(tokens, null, 2) + os.EOL);
  fs.renameSync(temp, PRINCIPALS_FILE);
}

type Identity = { username: string; user_level: number };

/**
 * Who an access token authenticates, or null if it authenticates nobody.
 *
 * `users/me` is the one `UserViewSet` action that opts down to `Authenticated`
 * rather than `IsAdmin` (`apps/accounts/api_views.py`), so a Streamer can call
 * it — which makes it the only honest liveness probe available for these
 * principals. It costs nothing from the login budget.
 */
async function whoAmI(
  request: APIRequestContext,
  access: string
): Promise<Identity | null> {
  const res = await request.get('/api/accounts/users/me/', {
    headers: { Authorization: `Bearer ${access}` },
  });
  if (!res.ok()) return null;
  const body = await res.json();
  if (typeof body?.username !== 'string') return null;
  return { username: body.username, user_level: body.user_level };
}

/** The user row for `username`, or null. The users list is unpaginated. */
async function findUser(
  request: APIRequestContext,
  headers: Record<string, string>,
  username: string
): Promise<{ id: number; username: string; user_level: number } | null> {
  const res = await request.get('/api/accounts/users/', { headers });
  if (!res.ok()) {
    throw new Error(
      `listing users failed: ${res.status()} ${await res.text()}`
    );
  }
  const body = await res.json();
  const users = Array.isArray(body) ? body : (body?.results ?? []);
  return users.find((user: { username?: string }) => user.username === username) ?? null;
}

/**
 * Create the principal's user row if it is missing, and correct its
 * `user_level` if something moved it. Both are admin writes — unthrottled and
 * free — so this runs unconditionally rather than being made conditional on a
 * token miss: a principal whose level has drifted is a silently wrong
 * authorization test, which is worse than the two requests this costs.
 *
 * Returns true when the row was created, i.e. when any stored token for this
 * name describes a user that no longer exists.
 */
async function ensureUserRow(
  request: APIRequestContext,
  headers: Record<string, string>,
  principal: Principal
): Promise<boolean> {
  const existing = await findUser(request, headers, principal.username);

  if (!existing) {
    const created = await request.post('/api/accounts/users/', {
      headers,
      data: {
        username: principal.username,
        password: principal.password,
        email: principal.email,
        user_level: principal.user_level,
      },
    });
    if (!created.ok()) {
      throw new Error(
        `creating principal ${principal.username} failed: ` +
          `${created.status()} ${await created.text()}`
      );
    }
    return true;
  }

  if (existing.user_level !== principal.user_level) {
    const patched = await request.patch(`/api/accounts/users/${existing.id}/`, {
      headers,
      data: { user_level: principal.user_level },
    });
    if (!patched.ok()) {
      throw new Error(
        `restoring user_level for ${principal.username} failed: ` +
          `${patched.status()} ${await patched.text()}`
      );
    }
  }
  return false;
}

/**
 * Reset a principal's password to the committed constant, so a login that was
 * refused can be retried.
 *
 * Throws rather than returning quietly on failure: `loginWithThrottleBackoff`
 * retries once after this, so a silent no-op would make that retry collect the
 * same 401 and report the *login* as broken when the repair was.
 */
async function resetPassword(
  request: APIRequestContext,
  headers: Record<string, string>,
  principal: Principal
): Promise<void> {
  const existing = await findUser(request, headers, principal.username);
  if (!existing) {
    throw new Error(
      `cannot repair the password for ${principal.username}: its login was ` +
        'refused and the user row has vanished since it was ensured a moment ' +
        'ago, so something outside this run is deleting principals.'
    );
  }
  const patched = await request.patch(`/api/accounts/users/${existing.id}/`, {
    headers,
    data: { password: principal.password },
  });
  if (!patched.ok()) {
    throw new Error(
      `repairing the password for ${principal.username} failed: ` +
        `${patched.status()} ${await patched.text()}. Its login was refused ` +
        'before this, so the password has drifted and cannot be restored.'
    );
  }
}

/**
 * Exchange a refresh token for a new access token. Not throttled, so free.
 *
 * Null on any failure, including the 500 the product returns when the refresh
 * token names a user that has been deleted (D10Scot/Dispatcharr#12 —
 * `rest_framework_simplejwt` does a bare `.get()` and lets `User.DoesNotExist`
 * escape). Callers fall through to a login, which is the right answer for all
 * of them.
 */
async function refresh(
  request: APIRequestContext,
  refreshToken: string
): Promise<string | null> {
  const res = await request.post('/api/accounts/token/refresh/', {
    data: { refresh: refreshToken },
  });
  if (!res.ok()) return null;
  const body = await res.json();
  return typeof body?.access === 'string' ? body.access : null;
}

/**
 * Make sure every principal in `PRINCIPALS` exists and has a usable token pair
 * on disk. Serial by construction, and called from `bootstrap` only.
 *
 * The order below is the login budget, cheapest first:
 *   1. the stored access token has life left *and* authenticates the right
 *      user — 0 logins;
 *   2. the stored refresh token mints a new access token — 0 logins, and this
 *      is the branch that covers the 30-minute access lifetime, i.e. most
 *      re-runs of a day-old container;
 *   3. log in — 1, and only on a genuinely cold path. A principal whose
 *      password has drifted spends a **second** one on the repair retry, which
 *      is the one way the cold path can exceed `1 + roster` logins; the
 *      backoff in `loginWithThrottleBackoff` absorbs it.
 *
 * The file is rewritten after **each** principal, not once at the end: a
 * failure on the second principal must not discard the login just spent on the
 * first, or the retry starts cold inside the window it emptied. Entries for
 * principals still in the roster are carried forward for the same reason;
 * entries for names no longer in it are dropped.
 */
export async function provisionPrincipals(
  request: APIRequestContext,
  adminAccess: string
): Promise<void> {
  const headers = { Authorization: `Bearer ${adminAccess}` };
  const stored = readStored();

  const next: PrincipalsFile = {};
  for (const name of PRINCIPAL_NAMES) {
    if (stored[name]) next[name] = stored[name];
  }

  for (const name of PRINCIPAL_NAMES) {
    const principal = PRINCIPALS[name];
    const recreated = await ensureUserRow(request, headers, principal);
    const previous = recreated ? undefined : stored[name];

    let tokens: TokenPair | null = null;

    // `hasLifeLeft` and not merely "does it still authenticate": a token with
    // two seconds on it passes a probe and then expires in a worker's hands.
    // Renewing early is free.
    if (previous?.access && previous.refresh && hasLifeLeft(previous.access)) {
      const identity = await whoAmI(request, previous.access);
      if (identity?.username === principal.username) {
        tokens = { access: previous.access, refresh: previous.refresh };
      }
    }

    if (!tokens && previous?.refresh) {
      const access = await refresh(request, previous.refresh);
      if (access) {
        const identity = await whoAmI(request, access);
        if (identity?.username === principal.username) {
          tokens = { access, refresh: previous.refresh };
        }
      }
    }

    if (!tokens) {
      tokens = await loginWithThrottleBackoff(request, principal, {
        repairCredentials: () => resetPassword(request, headers, principal),
      });
    }

    next[name] = {
      username: principal.username,
      user_level: principal.user_level,
      ...tokens,
    };
    writeStored(next);
  }
}
