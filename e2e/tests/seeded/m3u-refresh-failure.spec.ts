import { test, expect } from '../../fixtures';
import type { M3uAccount, StreamPage } from '../../fixtures';

test('a 404 from the playlist leaves the account in error with no catalogue', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // Two refreshes — a failing one and a recovering one — against the `seeded`
  // project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('notfound');
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null },
      { id: 2, name: `${prefix}-b`, tvgId: `${prefix}-b.e2e`, logo: null },
    ],
  });

  // `not-found` is a "new connection only" fault, so it must be armed BEFORE
  // the refresh and `appliedTo: 0` is the correct, expected response.
  const armed = await upstream.fault(scenario, 'not-found');
  expect(armed.active).toBe(true);
  expect(armed.appliedTo).toBe(0);

  const account = await seed.m3uAccount({
    server_url: upstream.playlistUrl(scenario),
    is_active: true,
  });

  // Was a false pass without this: creating the account active queues the
  // create-time `refresh_m3u_groups` task unconditionally, and with
  // `not-found` already armed, *that* task's own fetch fails and writes
  // `status: 'error'` too — the exact value asserted below. Without waiting
  // for it to settle first, `waitFor.m3uRefreshComplete`'s baseline-diff
  // could resolve on the create-time task's write and never actually
  // observe the *triggered* refresh this test names, passing regardless of
  // whether the explicit trigger's own 404 handling works at all. See
  // `upstreamM3UAccount()`'s doc comment in seed.ts for the full mechanism.
  await seed.waitForCreateTimeGroupRefreshToSettle(account.id);

  const failed = await waitFor.m3uRefreshComplete(account.id);
  expect(failed.status).toBe('error');
  expect(failed.last_message).toBeTruthy();
  // NOT asserted: that `last_message` names the 404. See the known-bug test
  // below (D10Scot/Dispatcharr#60) — `_refresh_single_m3u_account_impl`
  // overwrites `fetch_m3u_lines`'s status-specific message with a generic one.

  const empty = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'streams after a failed refresh'
  );
  expect(empty.count).toBe(0);

  // Recovery: the failure wedged nothing. Clearing the fault and refreshing
  // again produces the full catalogue.
  await upstream.clearFault(scenario, 'not-found');
  const recovered = await waitFor.m3uRefreshComplete(account.id);
  expect(recovered.status).toBe('success');

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'streams after the recovering refresh'
  );
  expect(page.count).toBe(2);
});

test('a 401 from the playlist does not disturb an already-ingested catalogue', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // A successful refresh followed by a failing one.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('authfail');
  // `auth-failure` only means anything on a scenario that declared
  // credentials: `credentialQuery` returns '' when `username` is undefined,
  // so an anonymous scenario has nothing to reject.
  const scenario = await upstream.scenario({
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    channels: [
      { id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null },
      { id: 2, name: `${prefix}-b`, tvgId: `${prefix}-b.e2e`, logo: null },
    ],
  });

  const account = await seed.upstreamM3UAccount(scenario);
  const before = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'streams after the first, successful refresh'
  );
  expect(before.count).toBe(2);

  // A distinct race from the create-time one `upstreamM3UAccount()` already
  // closes: `_refresh_single_m3u_account_impl` writes `status: 'success'`
  // (`apps/m3u/tasks.py:3865-3873`) well before `refresh_single_m3u_account`
  // releases its own Redis task lock (`apps/m3u/tasks.py:3374`) — auto-sync,
  // catch-up rollup, a system-event log, a WS push and cache-file cleanup all
  // run in between. `upstreamM3UAccount()` returns the instant it observes
  // `success`, which can be well inside that window, so the explicit trigger
  // below could land on a still-held lock and be silently dropped
  // (`core.utils.acquire_task_lock` just logs "Lock for
  // refresh_single_m3u_account and id=<n> already acquired. Task will not
  // proceed." and the task returns without writing anything). Filed as
  // D10Scot/Dispatcharr#59: a request that did nothing is indistinguishable
  // from one that worked.
  //
  // No test-side workaround is needed here any more: `m3uRefreshComplete()`
  // (`wait.ts:351-405`) now re-fires its own trigger every
  // `M3U_RETRIGGER_INTERVAL_MS` (5s), up to `M3U_MAX_RETRIGGERS` (3) times,
  // which recovers exactly this drop. This file used to sleep 2s here as a
  // test-side workaround before that fix existed (`9eb958fa`); the sleep is
  // now redundant and has been removed.

  const armed = await upstream.fault(scenario, 'auth-failure');
  expect(armed.active).toBe(true);
  expect(armed.appliedTo).toBe(0);

  const failed = await waitFor.m3uRefreshComplete(account.id);
  expect(failed.status).toBe('error');
  expect(failed.last_message).toBeTruthy();

  // The prior catalogue is untouched: the fetch failed before any parsing, so
  // no stream-touching code path ran at all.
  const after = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'streams after the failed refresh'
  );
  expect(after.count).toBe(2);
  expect(after.results.map((s) => s.name).sort()).toEqual(
    before.results.map((s) => s.name).sort()
  );
});

/**
 * Known bug: D10Scot/Dispatcharr#60. `fetch_m3u_lines` writes a
 * status-code-specific `last_message` ("M3U file not found (404) at URL: …"),
 * and `_refresh_single_m3u_account_impl` then overwrites it with the generic
 * "Failed to refresh M3U groups - download failed or other error", identically
 * for 404, 401, 403, 500 and a connection refusal. The specific text reaches
 * only the WebSocket and the log. Also referenced by #56, which tracks the
 * shared `(message, None)` return-shape conflation behind all three related
 * findings (#59, #60, #56 itself).
 *
 * Asserts the CORRECT behaviour and is expected to fail until #60 is fixed.
 */
test.fail('a failed refresh keeps the HTTP-status-specific message', { tag: '@contract' }, async ({
  upstream,
  seed,
  waitFor,
  api,
}) => {
  // A create-time settle plus a triggered refresh against the `seeded`
  // project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('message');
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null }],
  });
  await upstream.fault(scenario, 'not-found');

  const account = await seed.m3uAccount({
    server_url: upstream.playlistUrl(scenario),
    is_active: true,
  });

  // Closes the same create-time-refresh race `upstreamM3UAccount()` closes
  // (see its doc comment in seed.ts) — without this, `m3uRefreshComplete`'s
  // baseline read can capture the create-time task's own terminal write
  // instead of the triggered refresh's.
  await seed.waitForCreateTimeGroupRefreshToSettle(account.id);
  const failed = await waitFor.m3uRefreshComplete(account.id);

  // A second, narrower race, internal to the *triggered* refresh itself:
  // `_refresh_single_m3u_account_impl` writes the specific message (via
  // `fetch_m3u_lines`, called synchronously) and then, milliseconds later,
  // overwrites it with the generic one — that overwrite is #60 itself.
  // `waitFor.m3uRefreshComplete`'s second phase returns on the *first*
  // terminal status it observes once the refresh is confirmed in flight,
  // with no check that a later write hasn't superseded it, so it can
  // occasionally return that fleeting first write instead of the settled
  // one. Verified empirically against this container: a 1s settle-read after
  // `m3uRefreshComplete` resolves showed the generic (overwritten) message in
  // 25/25 runs — including the runs where the immediate return above had
  // already (incorrectly) surfaced the specific one. Re-reading here rather
  // than changing `wait.ts`'s own polling semantics, which is shared with
  // G5/G6 and outside this task.
  await new Promise((resolve) => setTimeout(resolve, 1_000));
  const settled = await api.json<M3uAccount>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'settled account state after the refresh finished'
  );

  expect(failed.status).toBe('error');
  expect(settled.status).toBe('error');
  expect(settled.last_message).toContain('404');
});
