/**
 * The password-login toggle and its break-glass recovery (SSO spec PR S5; spec 5.5, 5.6).
 *
 * An admin signed in through SSO switches password login off; a password login is then
 * refused. Recovery is the recovery page's first command verbatim,
 * `python manage.py password_login --enable`, after which a password login succeeds
 * again — which also leaves this stack with password login on for the next run.
 *
 * `@characterization`, per docs/adr/0002: it pins an implementation fact, the
 * `password_login` management command run inside the AIO container through
 * `instance.manage()`. An operator CLI inside the image is something a reimplementation
 * may change; the toggle's HTTP behaviour around it is what a client sees.
 *
 * The only `sso` spec that takes the `instance` fixture (allowlisted in
 * `tests/guards/allowlist.ts`'s CONTAINER_LIFECYCLE): it runs management commands
 * inside its own scoped container and never calls `up`/`restart`/`recreate`/`down`.
 *
 * Password-request budget: exactly two `POST /api/accounts/token/`, the refused probe
 * and the recovered login. The refused probe is a raw request, never retried, so a retry
 * can never turn a real 200 into a pass.
 *
 * SSO request budget: 3 of the `oidc` throttle's 20 a minute per client IP (start, callback and exchange).
 * The project spends 8 a run; see e2e/README.md, "The sso project".
 */
import { test, expect } from './fixtures';
import { ADMIN } from '../../setup/credentials';
import { loginWithThrottleBackoff } from '../../setup/login';
import { assertScopedStack } from './scope';
import {
  ADMIN_ROLE,
  createSsoProvider,
  retireSsoProvider,
  signInThroughSso,
  uniqueToken,
} from './helpers';
import type { SsoProvider } from './helpers';

test.beforeAll(() => {
  assertScopedStack();
});

const providers: SsoProvider[] = [];

// Re-enable before retiring the provider: with password login off, disabling the last
// enabled provider is refused (lockout guard), and a run that died mid-test must not
// leave the stack locked for the next one.
test.afterEach(async ({ api, request, instance }) => {
  const settings = await request.get('/api/accounts/oidc/providers/');
  const { password_login_enabled: enabled } = (await settings.json()) as { password_login_enabled?: boolean };
  if (enabled !== true) {
    const result = await instance.manage(['password_login', '--enable']);
    console.warn(`afterEach re-enabled password login: exit ${result.code}\n${result.stdout}${result.stderr}`);
  }
  for (const provider of providers.splice(0)) await retireSsoProvider(api, provider);
});

test(
  'password login switched off from an SSO admin session is refused, and break-glass restores it',
  { tag: '@characterization' },
  async ({ page, api, request, instance }) => {
    const provider = await createSsoProvider(api, 'breakglass');
    providers.push(provider);
    const username = `sso-breakglass-${uniqueToken()}`;
    await provider.queueLogin({
      sub: `sub-${uniqueToken()}`,
      preferred_username: username,
      email: `${username}@example.test`,
      roles: [ADMIN_ROLE],
    });

    await signInThroughSso(page, provider);
    await expect(page).toHaveURL(/\/channels/, { timeout: 30_000 });

    // The SSO admin's own pair (spec 5.5: only an SSO session may switch it off).
    const access = await page.evaluate(() => localStorage.getItem('accessToken'));
    expect(access, 'the SPA stored the SSO session access token').toBeTruthy();

    const off = await request.patch('/api/accounts/oidc/settings/', {
      headers: { Authorization: `Bearer ${access}` },
      data: { password_login_enabled: false },
    });
    expect(off.status(), `switching password login off: ${await off.text()}`).toBe(200);
    expect(((await off.json()) as { password_login_enabled?: boolean }).password_login_enabled).toBe(false);

    // The negative probe: raw, never retried.
    const refused = await request.post('/api/accounts/token/', {
      data: { username: ADMIN.username, password: ADMIN.password },
    });
    if (refused.status() === 429) {
      throw new Error(
        'the password-off probe was throttled (429). The sso project spends at most 3 ' +
          'password requests a run against a 3/minute budget, so something else spent it: ' +
          'another run against this stack within the last minute. Never retried, because a ' +
          'retry could turn a real 200 into a pass.'
      );
    }
    expect(refused.status(), 'a password login is refused while it is off').toBe(403);
    expect(((await refused.json()) as { code?: string }).code).toBe('password_login_disabled');

    // Break-glass: the recovery page's first command, verbatim.
    const enable = await instance.manage(['password_login', '--enable']);
    expect(enable.code, `password_login --enable: ${enable.stdout}${enable.stderr}`).toBe(0);
    expect(enable.stdout).toContain('Password login enabled.');
    expect(enable.stdout).toMatch(/Active admins with a usable password: [1-9]\d*/);

    const status = await instance.manage(['password_login', '--status']);
    expect(status.code, `password_login --status: ${status.stdout}${status.stderr}`).toBe(0);
    expect(status.stdout).toContain('Password login (stored): enabled');

    // The positive probe may wait out one throttle window; it never turns a refusal into a pass.
    const pair = await loginWithThrottleBackoff(request, ADMIN);
    expect(pair.access, 'a password login succeeds again').toBeTruthy();
  }
);
