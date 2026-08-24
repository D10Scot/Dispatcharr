import { test as setup, expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { ADMIN } from './credentials';
import { provisionPrincipals } from './principals';
import { assertMayCreateSuperuser } from './superuser-guard';

const AUTH_DIR = 'playwright/.auth';
const STATE_FILE = path.join(AUTH_DIR, 'admin.json');
const TOKENS_FILE = path.join(AUTH_DIR, 'tokens.json');

type TokenPair = { access: string; refresh: string };

/** The access token's `exp` claim, in unix seconds. */
function jwtExp(accessToken: string): number {
  const payload = accessToken.split('.')[1];
  return JSON.parse(Buffer.from(payload, 'base64').toString('utf8')).exp;
}

/**
 * The previous run's tokens, if the access token still authenticates.
 *
 * `POST /api/accounts/token/` is throttled at 3/minute per client IP
 * (`DEFAULT_THROTTLE_RATES` in dispatcharr/settings.py). Logging in
 * unconditionally here put a standing one-per-minute floor under the entire
 * suite, so two runs inside a minute used to 429 in *setup*, before a single
 * test executed. `users/me` is the one `UserViewSet` action that opts down to
 * `Authenticated` (apps/accounts/api_views.py), which makes it the cheapest
 * honest liveness check for a token — and it costs nothing from the login
 * budget.
 *
 * Returns null on anything unexpected so the caller falls back to a fresh
 * login: a missing or malformed file, and equally a token left over from a
 * container that has since been reset, whose user no longer exists.
 */
async function reusableTokens(
  request: APIRequestContext
): Promise<TokenPair | null> {
  let stored: Partial<TokenPair>;
  try {
    stored = JSON.parse(fs.readFileSync(TOKENS_FILE, 'utf8'));
  } catch {
    return null;
  }
  if (!stored.access || !stored.refresh) return null;

  let access = stored.access;
  let probe = await request.get('/api/accounts/users/me/', {
    headers: { Authorization: `Bearer ${access}` },
  });

  // An access token expires after 30 minutes and a refresh token after a day
  // (`SIMPLE_JWT`), and `TokenRefreshView` is not throttled — so a run more
  // than half an hour after the last one can renew for free instead of
  // spending one of the three logins a minute buys. Without this, any gap
  // longer than the access lifetime made bootstrap cold again.
  if (!probe.ok()) {
    const refreshed = await request.post('/api/accounts/token/refresh/', {
      data: { refresh: stored.refresh },
    });
    if (!refreshed.ok()) return null;
    const body = await refreshed.json();
    if (typeof body?.access !== 'string') return null;
    access = body.access;
    probe = await request.get('/api/accounts/users/me/', {
      headers: { Authorization: `Bearer ${access}` },
    });
  }
  if (!probe.ok()) return null;

  // A 200 only proves the token authenticates *someone*. Both files below
  // describe the pair as the admin's — admin.json becomes the seeded
  // project's storageState, and tokens.json is written beside a spread
  // ...ADMIN — so adopting another principal's token would silently run every
  // spec as that principal, surfacing as unexplained 403s across the suite
  // rather than as a setup failure.
  const who = await probe.json();
  if (who.username !== ADMIN.username) return null;

  return { access, refresh: stored.refresh };
}

/**
 * The M3U account this file leaves behind, permanently, on every instance the
 * suite bootstraps. Named to say so: deleting it re-opens the race below.
 */
const PREWARM_ACCOUNT_NAME = 'e2e-harness-interval-prewarm-do-not-delete';

/**
 * Create the default `IntervalSchedule` row once, serially, before any
 * parallel worker can race for it.
 *
 * `core/scheduling.py:121` does
 * `IntervalSchedule.objects.get_or_create(every=…, period=HOURS)` from an
 * `M3UAccount` post_save receiver (`apps/m3u/signals.py:58`), and
 * `django_celery_beat.IntervalSchedule` has no unique constraint on
 * `(every, period)` — verified: `unique_together` is `()` and `constraints`
 * is `[]`. Two concurrent creates therefore both miss the SELECT and both
 * INSERT, after which the SELECT inside every later `get_or_create` returns 2
 * rows and raises `MultipleObjectsReturned`. Every M3U account and EPG source
 * creation on that instance returns 500 from then on, permanently: nothing in
 * the UI or the API can delete the duplicate.
 * D10Scot/Dispatcharr#7 has the full traceback.
 *
 * `refresh_interval` defaults to 0 (`apps/m3u/models.py:91`), which that
 * expression maps to `every=1, period=HOURS`, and `EPGSource.refresh_interval`
 * defaults to 0 and lands on the same row — so every default-shaped create in
 * the suite contends for one row. Creating it here, from the `bootstrap`
 * project that both parallel projects list in `dependencies:`, means it
 * already exists by the time worker 1 starts and every later `get_or_create`
 * is a plain SELECT hit. That covers any creation path, including a test
 * driving the UI, not just `seed.m3uAccount()`.
 *
 * The account must survive: deleting it runs `_cleanup_orphaned_interval`,
 * which removes the row again once nothing references it. Its `refresh_task`
 * is what pins the row in place.
 *
 * This protects the default interval only. A test that creates accounts with
 * a *non*-default `refresh_interval` concurrently can still race for that
 * interval's row; pre-warm it the same way if you write one.
 *
 * Both branches below end in a write that runs the receiver, because the
 * second half of this function's job is to *detect* a container that is
 * already poisoned and say so once, here, rather than let four unrelated
 * tests fail later with an opaque 500.
 */
async function prewarmIntervalSchedule(
  request: APIRequestContext,
  access: string
): Promise<void> {
  const headers = { Authorization: `Bearer ${access}` };

  const listed = await request.get('/api/m3u/accounts/', { headers });
  expect(
    listed.ok(),
    `listing M3U accounts failed: ${listed.status()} ${await listed.text()}`
  ).toBeTruthy();
  const body = await listed.json();
  const accounts: Array<{ id?: number; name?: string }> = Array.isArray(body)
    ? body
    : (body?.results ?? []);
  const existing = accounts.find(
    (account) => account.name === PREWARM_ACCOUNT_NAME
  );

  // Finding the account by name is NOT proof the row is warm, and returning
  // early here made the detector one-shot. A create that 500s still commits
  // its M3UAccount row: the receiver raises *after* the INSERT, and
  // ATOMIC_REQUESTS is off, so the row lands with refresh_task_id NULL. On a
  // poisoned container that means run 1 creates the row and reports the
  // poisoning correctly, and every run after it finds the name, returns, and
  // reports nothing — exactly the failure this function exists to prevent,
  // starting from the most likely next thing anybody does (re-run without
  // resetting). So probe it instead: the same post_save receiver runs on
  // update, so a PATCH 500s on a poisoned container and is otherwise cheap.
  // `refresh_task` is not in the list serializer's fields, so "null task
  // means poisoned" is not available over the API as a shortcut.
  if (existing) {
    const probed = await request.patch(`/api/m3u/accounts/${existing.id}/`, {
      headers,
      data: { refresh_interval: 0 },
    });
    if (probed.status() === 500) throw poisonedContainerError('updating');
    expect(
      probed.ok(),
      `IntervalSchedule pre-warm probe failed: ${probed.status()} ${await probed.text()}`
    ).toBeTruthy();
    return;
  }

  const created = await request.post('/api/m3u/accounts/', {
    headers,
    data: {
      name: PREWARM_ACCOUNT_NAME,
      // Deliberately unroutable, and inactive: nothing should ever fetch it.
      server_url: 'http://127.0.0.1:9/prewarm.m3u',
      is_active: false,
      refresh_interval: 0,
    },
  });

  if (created.status() === 500) throw poisonedContainerError('creating');
  expect(
    created.ok(),
    `IntervalSchedule pre-warm failed: ${created.status()} ${await created.text()}`
  ).toBeTruthy();
}

/** The one thing worth saying when the pre-warm write returns a 500. */
function poisonedContainerError(verb: 'creating' | 'updating'): Error {
  return new Error(
    `This container is already poisoned: ${verb} an M3U account returned ` +
      '500. Almost certainly duplicate IntervalSchedule rows from a ' +
      'concurrent-create race (D10Scot/Dispatcharr#7) — every M3U account ' +
      'and EPG source creation on this instance will fail from now on, and ' +
      'there is no API or UI that can repair it. Rebuild the container: ' +
      './scripts/e2e_up.sh --reset'
  );
}

setup('create the superuser and persist admin auth state', async ({
  request,
  baseURL,
}) => {
  const status = await request.get('/api/accounts/initialize-superuser/');
  expect(
    status.ok(),
    `initialize-superuser probe failed: ${status.status()} ${await status.text()}`
  ).toBeTruthy();

  if (!(await status.json()).superuser_exists) {
    assertMayCreateSuperuser(baseURL!);
    // POST is IP-gated to private/loopback (dispatcharr/utils.py,
    // setup_ip_allowed). Fine from CI and from localhost; a public
    // E2E_BASE_URL needs DISPATCHARR_SETUP_ALLOWED_IP set on the instance —
    // read superuser-guard.ts before you do that.
    const created = await request.post('/api/accounts/initialize-superuser/', {
      data: ADMIN,
    });
    expect(
      created.ok(),
      `superuser creation failed: ${created.status()} ${await created.text()}`
    ).toBeTruthy();
  }

  let tokens = await reusableTokens(request);
  if (!tokens) {
    const tokenRes = await request.post('/api/accounts/token/', {
      data: { username: ADMIN.username, password: ADMIN.password },
    });
    expect(
      tokenRes.ok(),
      `login failed: ${tokenRes.status()} ${await tokenRes.text()}`
    ).toBeTruthy();
    const body = await tokenRes.json();
    tokens = { access: body.access, refresh: body.refresh };
  }
  const { access, refresh } = tokens;

  await prewarmIntervalSchedule(request, access);

  // Mint the non-admin principals here, serially, because this is the only
  // phase of a run that can afford a login: `POST /api/accounts/token/` allows
  // three per minute for the whole suite and `seeded` runs four workers, so
  // anything that logs in from a worker scales the cost with `workers:` while
  // the budget stays at three. Steady state is 0 logins — the pairs are reused
  // from disk and renewed through the unthrottled refresh endpoint. See
  // `principals.ts`.
  await provisionPrincipals(request, access);

  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.writeFileSync(
    TOKENS_FILE,
    JSON.stringify({ access, refresh, ...ADMIN }, null, 2)
  );

  // Three keys, exactly these names. frontend/src/store/auth.jsx:186-190 is
  // the only writer; api.js:192 clears a `token` key nothing ever sets.
  // tokenExpiration must be the exp of whichever access token we just wrote,
  // reused or freshly minted.
  fs.writeFileSync(
    STATE_FILE,
    JSON.stringify(
      {
        cookies: [],
        origins: [
          {
            origin: new URL(baseURL!).origin,
            localStorage: [
              { name: 'accessToken', value: access },
              { name: 'refreshToken', value: refresh },
              { name: 'tokenExpiration', value: String(jwtExp(access)) },
            ],
          },
        ],
      },
      null,
      2
    )
  );
});
