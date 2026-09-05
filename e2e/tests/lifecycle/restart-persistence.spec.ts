/**
 * Exemplar: a spec that owns its container's lifecycle.
 *
 * COVERAGE: Lifecycle — restart preserves channels and settings (G7).
 *
 * Runs alone. `instance` destroys and replaces the container every other
 * project shares; see `e2e/fixtures/instance.ts`'s header.
 */
import {
  test,
  expect,
  ApiClient,
  Seeder,
  StreamStatusError,
  TS_PACKET_SIZE,
  Waiter,
  expectTsAligned,
} from '../../fixtures';
import { lockedProfile } from '../streaming/helpers';
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
//
// The relations `durable-state.ts` now asserts are the portable half: rows,
// orderings, foreign keys, M2M membership and file bytes surviving a container
// event is behaviour any reimplementation must preserve. The coupled half is
// unchanged, and is what the tag is for.
test('durable state and the signing key survive a container restart', { tag: '@characterization' }, async ({
  instance,
  request,
  baseURL,
  upstream,
  // Safe to take alongside the hand-built ApiClient below: the
  // `streamClient` fixture depends only on `baseURL`, so unlike
  // `api`/`seed`/`waitFor` it reads nothing from `playwright/.auth/`.
  streamClient,
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
  const state = await seedDurableState(api, seed, upstream);

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
  await assertDurableState(api, request, state);

  // Phase 1 PR 4 reshape: two uWSGI processes now live behind this one
  // container, and a restart must bring both back, not just the container's
  // own liveness. This is as far as the AIO harness can take the two-unit
  // restart the file's @characterization header warned about; the
  // restart-one-not-the-other scenario across separate containers lives in
  // docker/tests/test-puid-pgid.sh's test_role_split.
  //
  // Polled, not asserted once. supervisord reports RUNNING as soon as a
  // program has stayed alive `startsecs=5`, and both uWSGI programs run
  // through wait-for-stores.sh, so RUNNING can precede the store waits
  // finishing (docker/tests/test-puid-pgid.sh:180 says the same thing).
  await expect
    .poll(async () => (await instance.supervisorctl(['status', 'api-uwsgi'])).stdout, {
      timeout: 60_000,
      message: 'api-uwsgi did not return to RUNNING after the restart',
    })
    .toMatch(/RUNNING/);
  await expect
    .poll(async () => (await instance.supervisorctl(['status', 'relay-uwsgi'])).stdout, {
      timeout: 60_000,
      message: 'relay-uwsgi did not return to RUNNING after the restart',
    })
    .toMatch(/RUNNING/);

  // A stream re-tunes after the restart. Deliberately a *fresh* scenario and
  // channel, not durable-state.ts's pre-restart channel: that channel's
  // upstream scenario lives in the fake provider's in-memory
  // ScenarioRegistry, which `instance.restart()` also restarts. Asserting
  // against it here would be asserting against an upstream that no longer
  // exists, for a reason unrelated to whether the relay came back.
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'restart re-tune', tvgId: 'restart-retune.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  // RUNNING is not listening: nginx answers 502 while relay-uwsgi's socket
  // is still unbound. Retry the tune itself rather than trusting the status
  // line — a bare open() here is the race this reshape exists to avoid.
  //
  // Nothing is rethrown from this callback. `expect.poll` does not retry a
  // callback that throws — it fails the test on the first throw — so a
  // transient fetch failure (a connection reset while nginx and the uWSGI
  // workers finish recycling, seconds after the container comes back) would
  // end the test outright instead of being retried like the 502 beside it.
  // Every outcome becomes a string instead, so the 60s budget covers all of
  // them and the failure message prints the last one received. It has to be
  // the polled *value* that carries the reason: `expect.poll`'s `message`
  // option is typed `string`, not a callback
  // (`playwright/types/test.d.ts`, `poll<T>`), so a thunk there would not
  // compile.
  await expect
    .poll(
      async () => {
        try {
          await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
          return 'ok';
        } catch (error) {
          if (error instanceof StreamStatusError) return `HTTP ${error.status}`;
          return String(error);
        }
      },
      {
        timeout: 60_000,
        intervals: [2_000],
        message: 'the relay never served a tune after the restart',
      }
    )
    .toBe('ok');

  const packet = await streamClient.readPackets(1);
  expect(packet.byteLength).toBe(TS_PACKET_SIZE);
  expectTsAligned(packet);
});
