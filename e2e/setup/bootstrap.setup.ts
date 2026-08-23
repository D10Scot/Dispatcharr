import { test as setup, expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

export const ADMIN = {
  username: 'e2e-admin',
  password: 'Correct-Horse-Battery-Staple-42!',
  email: 'e2e-admin@example.com',
};

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

  const probe = await request.get('/api/accounts/users/me/', {
    headers: { Authorization: `Bearer ${stored.access}` },
  });
  if (!probe.ok()) return null;

  // A 200 only proves the token authenticates *someone*. Both files below
  // describe the pair as the admin's — admin.json becomes the seeded
  // project's storageState, and tokens.json is written beside a spread
  // ...ADMIN — so adopting another principal's token would silently run every
  // spec as that principal, surfacing as unexplained 403s across the suite
  // rather than as a setup failure.
  const who = await probe.json();
  if (who.username !== ADMIN.username) return null;

  return { access: stored.access, refresh: stored.refresh };
}

setup('create the superuser and persist admin auth state', async ({
  request,
  baseURL,
}) => {
  const status = await request.get('/api/accounts/initialize-superuser/');
  expect(status.ok()).toBeTruthy();

  if (!(await status.json()).superuser_exists) {
    // POST is IP-gated to private/loopback (dispatcharr/utils.py:142). Fine
    // from CI and from localhost; a public E2E_BASE_URL needs
    // DISPATCHARR_SETUP_ALLOWED_IP set on the instance.
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
