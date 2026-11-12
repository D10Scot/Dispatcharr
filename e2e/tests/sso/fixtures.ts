/**
 * The harness fixtures, with `api` re-pointed at the `sso` project's own admin pair
 * (SSO spec PR S5).
 *
 * The base `api` fixture reads the shared `playwright/.auth/tokens.json`, which belongs
 * to the shared stack's `bootstrap` project. Here `api` is built from
 * `sso-tokens.json`, which `sso.setup.ts` writes for the scoped stack, through the
 * `ApiClient` constructor that takes a pair and therefore never reads or writes
 * `tokens.json` (`fixtures/api.ts`). Everything that depends on `api` (`seed`,
 * `waitFor`, `ws`) follows it.
 */
import { test as base, ApiClient } from '../../fixtures';
import { readSsoAdminPair } from './helpers';

export const test = base.extend({
  api: async ({ request }, use) => {
    await use(new ApiClient(request, readSsoAdminPair()));
  },
});

export { expect } from '../../fixtures';
