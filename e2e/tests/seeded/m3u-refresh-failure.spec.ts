import { test, expect } from '../../fixtures';
import type { StreamPage } from '../../fixtures';

test('a 404 from the playlist leaves the account in error with no catalogue', async ({
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

  const failed = await waitFor.m3uRefreshComplete(account.id);
  expect(failed.status).toBe('error');
  expect(failed.last_message).toBeTruthy();
  // NOT asserted: that `last_message` names the 404. See the known-bug test in
  // Task 4 — `_refresh_single_m3u_account_impl` overwrites `fetch_m3u_lines`'s
  // status-specific message with a generic one.

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

test('a 401 from the playlist does not disturb an already-ingested catalogue', async ({
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
  // `success`, which can be well inside that window. Triggering another
  // refresh for the same account while the lock is still held is silently
  // dropped (`core.utils.acquire_task_lock` just logs "Lock for
  // refresh_single_m3u_account and id=<n> already acquired. Task will not
  // proceed." and the task returns without writing anything) — reproduced
  // directly against this container's logs, which is what caused this test
  // to intermittently time out in `waitFor.m3uRefreshComplete` below before
  // this wait was added. Not filed: no observable harm to a real caller
  // beyond this test's own back-to-back triggering, and there is no
  // API-visible signal to poll for "lock released" instead of a fixed delay.
  await new Promise((resolve) => setTimeout(resolve, 2_000));

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
