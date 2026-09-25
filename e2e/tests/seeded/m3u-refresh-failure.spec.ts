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
  // Credentialed so the create-time refresh can be made to fail on a
  // DIFFERENT fault (401) than the one this test actually exercises (404).
  const scenario = await upstream.scenario({
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    channels: [
      { id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null },
      { id: 2, name: `${prefix}-b`, tvgId: `${prefix}-b.e2e`, logo: null },
    ],
  });

  // The create-time refresh (queued unconditionally on account creation,
  // `apps/m3u/signals.py:18-19`) must fail on `auth-failure` first, not on
  // `not-found`. D10Scot/Dispatcharr#60 is fixed: each refresh's own
  // specific message now survives instead of being overwritten with a
  // generic one, so `waitFor.m3uRefreshComplete`'s baseline-diff
  // (`fixtures/wait.ts:377-397`) can only detect the *explicitly triggered*
  // refresh below if its outcome differs from the create-time refresh's own
  // baseline. Arming the SAME fault for both would leave the account at an
  // identical `(status, last_message)` pair before and after the trigger,
  // and the wait would time out — this is what a real CI run caught once
  // #60 landed. Arming a DIFFERENT fault first, then swapping it for the
  // one this test names, guarantees a real difference.
  const preArmed = await upstream.fault(scenario, 'auth-failure');
  expect(preArmed.active).toBe(true);

  const account = await seed.m3uAccount({
    server_url: upstream.playlistUrl(scenario),
    is_active: true,
  });

  // Waits for the create-time refresh (failing on `auth-failure`) to reach
  // its own terminal state before swapping the fault. See
  // `upstreamM3UAccount()`'s doc comment in seed.ts for the race this
  // closes.
  await seed.waitForCreateTimeGroupRefreshToSettle(account.id);

  // `not-found` is a "new connection only" fault, so it must be armed BEFORE
  // the refresh this test actually exercises, and `appliedTo: 0` is the
  // correct, expected response.
  await upstream.clearFault(scenario, 'auth-failure');
  const armed = await upstream.fault(scenario, 'not-found');
  expect(armed.active).toBe(true);
  expect(armed.appliedTo).toBe(0);

  const failed = await waitFor.m3uRefreshComplete(account.id);
  expect(failed.status).toBe('error');
  expect(failed.last_message).toBeTruthy();
  // D10Scot/Dispatcharr#60 is fixed: the specific HTTP-status message now
  // reaches the account row, not just the WebSocket and the log. The
  // 401-then-404 arrangement above is what makes this assertion meaningful
  // — it proves THIS refresh's outcome, not the create-time one's.
  expect(failed.last_message).toContain('(404)');

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
 * Fixed: D10Scot/Dispatcharr#60. `fetch_m3u_lines` writes a
 * status-code-specific `last_message` ("M3U file not found (404) at URL: …")
 * and marks the account ERROR before returning; `_refresh_single_m3u_account_impl`
 * used to overwrite it unconditionally with the generic "Failed to refresh
 * M3U groups - download failed or other error", identically for 404, 401,
 * 403, 500 and a connection refusal. It now checks whether the account's
 * current status is already ERROR -- meaning the failing step already
 * recorded its own message -- and leaves it alone in that case, only falling
 * back to the generic text when nothing more specific was recorded. Also
 * referenced by #56, which tracks the shared `(message, None)` return-shape
 * conflation behind all three related findings (#59, #60, #56 itself).
 */
test('a failed refresh keeps the HTTP-status-specific message', { tag: '@contract' }, async ({
  upstream,
  seed,
  waitFor,
  api,
}) => {
  // A successful create-time ingest, then a failing triggered refresh,
  // against the `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('message');
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null }],
  });

  // A SUCCESSFUL create-time refresh first, so the baseline
  // `waitFor.m3uRefreshComplete` reads below is `(success, <no error>)` --
  // deterministically different from the `error` this test's own trigger
  // produces. Arming `not-found` before creation (as this test used to)
  // makes the create-time refresh ALSO fail with the exact same specific
  // message D10Scot/Dispatcharr#60 now preserves, which leaves the baseline
  // and the triggered outcome byte-identical and the wait times out -- a
  // real CI run caught exactly this once #60 landed. This is a defect in
  // this test's own arrangement, not in the product: see
  // `waitFor.m3uRefreshComplete`'s doc comment (`fixtures/wait.ts:258-265`)
  // on why a repeated identical failure is otherwise undetectable to it.
  const account = await seed.upstreamM3UAccount(scenario);
  await upstream.fault(scenario, 'not-found');

  const failed = await waitFor.m3uRefreshComplete(account.id);

  // D10Scot/Dispatcharr#60 is fixed: the caller no longer overwrites the
  // specific message `fetch_m3u_lines` already recorded on the account. A
  // 1s settle-read confirms the persisted state agrees with the value
  // `m3uRefreshComplete` returned, in case a later write superseded it.
  await new Promise((resolve) => setTimeout(resolve, 1_000));
  const settled = await api.json<M3uAccount>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'settled account state after the refresh finished'
  );

  expect(failed.status).toBe('error');
  expect(settled.status).toBe('error');
  expect(settled.last_message).toContain('404');
});
