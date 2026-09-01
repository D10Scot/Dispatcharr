/**
 * Exemplar: a spec that owns its container's lifecycle.
 *
 * COVERAGE: Lifecycle — restart preserves channels and settings (G7).
 *
 * Runs alone. `instance` destroys and replaces the container every other
 * project shares; see `e2e/fixtures/instance.ts`'s header.
 */
import { test, expect, ApiClient, Seeder, Waiter } from '../../fixtures';
import { provisionAdmin } from '../../setup/provision-admin';
import {
  assertAdminTokenStillValid,
  assertDurableState,
  seedDurableState,
} from './durable-state';

// @characterization: pins the AIO container as the unit of restart. It drives
// `instance.restart()` — `docker stop`/`docker start` against a single
// all-in-one container — and asserts the signing key and durable rows survive
// it. "State survives a restart" is portable; "the restart is this container"
// is not. Once the relay is its own process there are two units to restart and
// this test's shape, not just its assertions, has to change.
test('durable state and the signing key survive a container restart', { tag: '@characterization' }, async ({
  instance,
  request,
  baseURL,
}, testInfo) => {
  await instance.up();

  // Not the `api`/`seed` fixtures: those read `playwright/.auth/`, written by
  // `bootstrap`, which this project does not depend on and must not — a
  // persisted pair describes an instance this spec is about to restart.
  const tokens = await provisionAdmin(request, baseURL!);
  const api = new ApiClient(request, tokens);
  // Not the `waitFor` fixture: that Waiter wraps the fixture `api` (the
  // pre-restart bootstrap admin), which this spec must not touch either —
  // same reasoning as the `api`/`seed` fixtures above.
  const seed = new Seeder(api, testInfo.workerIndex, testInfo.testId, new Waiter(api));
  const state = await seedDurableState(api, seed);

  const startedBefore = await instance.startedAt();
  await instance.restart();
  const startedAfter = await instance.startedAt();

  // (d) first, deliberately. Without it, a spec that silently failed to
  // restart anything passes every other assertion in this file — and passes
  // for as long as nobody reads it.
  expect(
    startedAfter,
    'the container never restarted: .State.StartedAt did not move'
  ).not.toBe(startedBefore);

  await assertAdminTokenStillValid(request, tokens.access);
  await assertDurableState(api, state);
});
