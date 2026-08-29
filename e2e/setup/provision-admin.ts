/**
 * Creating the superuser on an instance that has never had one.
 *
 * Extracted from `bootstrap.setup.ts` so the lifecycle specs
 * (`e2e/tests/lifecycle/`) can bootstrap containers they create themselves
 * without a second copy of the sequence — and, more to the point, without a
 * second copy of `assertMayCreateSuperuser`. `superuser-guard.ts` says it
 * plainly: a guard that only one of two creation paths consults is not a
 * guard.
 *
 * Two exports rather than one, deliberately. `bootstrap` must be able to
 * ensure the superuser exists and then *reuse* a token pair from disk;
 * folding the login into the only entry point would put a standing one-login
 * cost under every bootstrap run, against a budget of three per minute for
 * the whole suite (`POST /api/accounts/token/`, DEFAULT_THROTTLE_RATES).
 */
import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { ADMIN } from './credentials';
import { loginWithThrottleBackoff } from './login';
import type { TokenPair } from './login';
import { assertMayCreateSuperuser } from './superuser-guard';

/**
 * Ensure the instance at `baseURL` has the harness admin, creating it if not.
 *
 * Idempotent: `GET /api/accounts/initialize-superuser/` returns 200 whether or
 * not a superuser exists — it short-circuits to `superuser_exists: true`
 * before any method dispatch — so this is safe on a bootstrapped instance and
 * costs one request. Only `POST` is IP-gated to private/loopback
 * (`dispatcharr/utils.py`, `setup_ip_allowed`), which is why the guard runs
 * only on the create path.
 */
export async function ensureSuperuser(
  request: APIRequestContext,
  baseURL: string
): Promise<void> {
  const status = await request.get('/api/accounts/initialize-superuser/');
  expect(
    status.ok(),
    `initialize-superuser probe failed: ${status.status()} ${await status.text()}`
  ).toBeTruthy();

  const setupState: { superuser_exists?: boolean } = await status.json();
  if (setupState.superuser_exists) return;

  assertMayCreateSuperuser(baseURL);
  const created = await request.post('/api/accounts/initialize-superuser/', {
    data: ADMIN,
  });
  expect(
    created.ok(),
    `superuser creation failed: ${created.status()} ${await created.text()}`
  ).toBeTruthy();
}

/**
 * Ensure the admin exists and return a fresh token pair for it.
 *
 * For callers that own their instance's whole lifecycle and therefore cannot
 * reuse `playwright/.auth/` — a persisted pair points at a container that may
 * no longer exist. The login goes through `loginWithThrottleBackoff`, which
 * honours `Retry-After`, because it is not optional at three logins a minute.
 *
 * `bootstrap.setup.ts` deliberately does NOT call this: it calls
 * `ensureSuperuser` and then its own reuse-or-login path, so a warm run spends
 * no logins at all.
 */
export async function provisionAdmin(
  request: APIRequestContext,
  baseURL: string
): Promise<TokenPair> {
  await ensureSuperuser(request, baseURL);
  return loginWithThrottleBackoff(request, ADMIN);
}
