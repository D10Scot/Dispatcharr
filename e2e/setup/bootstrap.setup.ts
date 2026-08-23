import { test as setup, expect } from '@playwright/test';
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

/** The access token's `exp` claim, in unix seconds. */
function jwtExp(accessToken: string): number {
  const payload = accessToken.split('.')[1];
  return JSON.parse(Buffer.from(payload, 'base64').toString('utf8')).exp;
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

  const tokenRes = await request.post('/api/accounts/token/', {
    data: { username: ADMIN.username, password: ADMIN.password },
  });
  expect(
    tokenRes.ok(),
    `login failed: ${tokenRes.status()} ${await tokenRes.text()}`
  ).toBeTruthy();
  const { access, refresh } = await tokenRes.json();

  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.writeFileSync(
    TOKENS_FILE,
    JSON.stringify({ access, refresh, ...ADMIN }, null, 2)
  );

  // Three keys, exactly these names. frontend/src/store/auth.jsx:186-190 is
  // the only writer; api.js:192 clears a `token` key nothing ever sets.
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
