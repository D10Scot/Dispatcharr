/**
 * The harness fixtures, with `api` re-pointed at the SSO project's own admin pair and
 * the browser context counted against the project's `oidc` budget (SSO spec PR S5).
 *
 * The base `api` fixture reads the shared `playwright/.auth/tokens.json`, which belongs
 * to the shared stack's `bootstrap` project. Here `api` is built from the pair the
 * project's own setup wrote for its scoped stack (`ssoTokensFile`), through the
 * `ApiClient` constructor that takes a pair and therefore never reads or writes
 * `tokens.json` (`fixtures/api.ts`). Everything that depends on `api` (`seed`,
 * `waitFor`, `ws`) follows it.
 *
 * `context` records every browser request to a route the `oidc` throttle counts in the
 * project's ledger, and after the test fails if the run has spent more than
 * `OIDC_BUDGET` declares (`tests/sso/budget.ts`). Every spec under `tests/sso/` imports
 * `test` from here, which `tests/guards/sso-budget.spec.ts` holds.
 */
import { test as base, ApiClient } from '../../fixtures';
import { AUTH_DIR } from '../../setup/auth-files';
import { OidcLedger } from './budget';
import { readSsoAdminPair } from './helpers';

export const test = base.extend({
  api: async ({ request }, use, testInfo) => {
    await use(new ApiClient(request, readSsoAdminPair(testInfo.project.name)));
  },
  context: async ({ context }, use, testInfo) => {
    const ledger = new OidcLedger(testInfo.project.name, AUTH_DIR);
    context.on('request', (request) => ledger.observe(request.url(), testInfo.title));
    await use(context);
    ledger.assertWithinBudget();
  },
});

export { expect } from '../../fixtures';
