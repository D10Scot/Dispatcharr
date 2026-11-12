/**
 * The `sso` project runs only against a scoped stack of its own (SSO spec PR S5).
 *
 * Turning password login off is instance-wide, and ADR 0001's shared container must
 * never see it. `assertScopedStack` is the one check that keeps it off: the first
 * statement of `sso.setup.ts`, before `ensureSuperuser` sends a request, and the first
 * statement of a `test.beforeAll` in every `sso` spec, before any mutation.
 *
 * It ties the HTTP target (`E2E_BASE_URL`) to the container `instance.manage()` acts on
 * (`DISPATCHARR_E2E_CONTAINER`, read independently by `fixtures/instance.ts`):
 * `scripts/e2e_up.sh`'s own `check_scope` checks only that its variables are present,
 * not that they correspond.
 *
 * Pure: it reads the `env` it is handed and nothing else, never `playwright.config.ts`'s
 * `http://localhost:9191` default, which is why an unset `E2E_BASE_URL` is a refusal.
 * Its refusal cases are pinned in the `guards` project (`tests/guards/sso-scope.spec.ts`)
 * with no container and no browser.
 */

const SHARED_CONTAINER = 'dispatcharr-e2e';
const SHARED_PORT = '9191';
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

const STACK_VARS = [
  'DISPATCHARR_E2E_CONTAINER',
  'DISPATCHARR_E2E_VOLUME',
  'DISPATCHARR_E2E_NETWORK',
  'DISPATCHARR_E2E_PORT',
] as const;

/** Throws, naming every failing variable, unless the environment names a scoped stack. */
export function assertScopedStack(env: NodeJS.ProcessEnv = process.env): void {
  const problems: string[] = [];

  for (const name of STACK_VARS) {
    if (!env[name]) problems.push(`${name} is not set`);
  }
  const container = env.DISPATCHARR_E2E_CONTAINER;
  if (container === SHARED_CONTAINER) {
    problems.push(`DISPATCHARR_E2E_CONTAINER is the shared default '${SHARED_CONTAINER}'`);
  }
  const port = env.DISPATCHARR_E2E_PORT;
  if (port === SHARED_PORT) {
    problems.push(`DISPATCHARR_E2E_PORT is the shared default '${SHARED_PORT}'`);
  }

  const baseUrl = env.E2E_BASE_URL;
  if (!baseUrl) {
    problems.push('E2E_BASE_URL is not set (the playwright.config.ts default does not count)');
  } else {
    let parsed: URL | undefined;
    try {
      parsed = new URL(baseUrl);
    } catch {
      problems.push(`E2E_BASE_URL '${baseUrl}' is not a URL`);
    }
    if (parsed) {
      if (!LOOPBACK_HOSTS.has(parsed.hostname)) {
        problems.push(`E2E_BASE_URL host '${parsed.hostname}' is not a loopback literal`);
      }
      const urlPort = parsed.port || (parsed.protocol === 'https:' ? '443' : '80');
      if (port && urlPort !== port) {
        problems.push(`E2E_BASE_URL port '${urlPort}' differs from DISPATCHARR_E2E_PORT '${port}'`);
      }
    }
  }

  if (problems.length > 0) {
    throw new Error(
      'The sso project runs only against a scoped stack of its own (e2e/README.md, ' +
        "'The sso project'). Refusing before any request:\n  " +
        problems.join('\n  ')
    );
  }
}
