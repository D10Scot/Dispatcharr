/**
 * `assertScopedStack` (`tests/sso/scope.ts`) refuses everything but a scoped stack of the
 * `sso` project's own (SSO spec PR S5), before any request.
 *
 * Pure, so its refusals are pinned here with an env object each: no container, no
 * browser. Each refusal case starts from a consistent scoped stack and breaks exactly
 * one thing, so the message it asserts names the one variable that broke.
 *
 * `@characterization`: this pins the harness's own safety check, which no client
 * observes (`docs/adr/0002`).
 */
import { test, expect } from '@playwright/test';
import { assertScopedStack } from '../sso/scope';

function scoped(): NodeJS.ProcessEnv {
  return {
    DISPATCHARR_E2E_CONTAINER: 'dispatcharr-e2e-sso-guard',
    DISPATCHARR_E2E_VOLUME: 'dispatcharr-e2e-sso-guard-data',
    DISPATCHARR_E2E_NETWORK: 'dispatcharr-e2e-sso-guard-net',
    DISPATCHARR_E2E_PORT: '39291',
    E2E_BASE_URL: 'http://localhost:39291',
  };
}

test.describe('assertScopedStack', () => {
  test('refuses a missing E2E_BASE_URL', { tag: '@characterization' }, () => {
    const env = scoped();
    delete env.E2E_BASE_URL;
    expect(() => assertScopedStack(env)).toThrow(/E2E_BASE_URL is not set/);
  });

  test('refuses a base URL port that differs from DISPATCHARR_E2E_PORT', { tag: '@characterization' }, () => {
    const env = { ...scoped(), E2E_BASE_URL: 'http://localhost:39292' };
    expect(() => assertScopedStack(env)).toThrow(/E2E_BASE_URL port '39292' differs from DISPATCHARR_E2E_PORT '39291'/);
  });

  test('refuses a non-loopback base URL', { tag: '@characterization' }, () => {
    const env = { ...scoped(), E2E_BASE_URL: 'http://192.168.1.10:39291' };
    expect(() => assertScopedStack(env)).toThrow(/E2E_BASE_URL host '192\.168\.1\.10' is not a loopback literal/);
  });

  test('refuses the shared container name', { tag: '@characterization' }, () => {
    const env = { ...scoped(), DISPATCHARR_E2E_CONTAINER: 'dispatcharr-e2e' };
    expect(() => assertScopedStack(env)).toThrow(/DISPATCHARR_E2E_CONTAINER is the shared default/);
  });

  test('refuses the shared port', { tag: '@characterization' }, () => {
    const env = { ...scoped(), DISPATCHARR_E2E_PORT: '9191', E2E_BASE_URL: 'http://localhost:9191' };
    expect(() => assertScopedStack(env)).toThrow(/DISPATCHARR_E2E_PORT is the shared default/);
  });

  test('refuses a stack variable that is not set', { tag: '@characterization' }, () => {
    for (const name of [
      'DISPATCHARR_E2E_CONTAINER',
      'DISPATCHARR_E2E_VOLUME',
      'DISPATCHARR_E2E_NETWORK',
      'DISPATCHARR_E2E_PORT',
    ]) {
      const env = scoped();
      delete env[name];
      expect(() => assertScopedStack(env), name).toThrow(new RegExp(`${name} is not set`));
    }
  });

  test('accepts a consistent scoped stack', { tag: '@characterization' }, () => {
    expect(() => assertScopedStack(scoped())).not.toThrow();
    for (const base of ['http://127.0.0.1:39291', 'http://[::1]:39291/']) {
      expect(() => assertScopedStack({ ...scoped(), E2E_BASE_URL: base }), base).not.toThrow();
    }
  });
});
