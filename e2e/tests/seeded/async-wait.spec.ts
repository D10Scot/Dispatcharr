import { test, expect } from '../../fixtures';

// Exemplar: polling is the default way to wait for backend state. Prefer it
// over the WebSocket unless the state is only observable there.
test('waitFor.resource polls until a created channel appears', async ({
  api,
  seed,
  waitFor,
}) => {
  const channel = await seed.channel();

  const found = await waitFor.resource(
    `/api/channels/channels/${channel.id}/`,
    (body) => body.name === channel.name
  );

  expect(found.id).toBe(channel.id);
});

// Exemplar: the WebSocket fixture, for state the REST API does not expose.
// Every socket receives connection_established on connect.
test('ws fixture receives the connection handshake', async ({ ws }) => {
  const message = await ws.waitForMessage('connection_established');
  expect(message.data.success).toBe(true);
});

// Regression: waitFor.m3uRefreshComplete used to poll for an in-flight
// `fetching`/`parsing` status before accepting a terminal one. A refresh
// that fails fast enough — a connection refused, say — can go
// idle -> error inside a single 250ms poll interval, so phase 1 never
// observed the in-flight status and burned its entire startTimeoutMs
// budget waiting for something that had already happened, then reported a
// start-timeout for a refresh that in fact ran and failed. See the doc
// comment on Waiter.m3uRefreshComplete in fixtures/wait.ts for the fix and
// why `updated_at` can't be used to detect this instead.
test('waitFor.m3uRefreshComplete resolves promptly on a fast failure', async ({
  seed,
  waitFor,
}) => {
  // seed.m3uAccount()'s default server_url (the discard port) refuses the
  // connection fast enough to reproduce the race above — measured at ~20ms
  // from trigger to `error`, comfortably inside one 250ms poll interval.
  // refresh_interval must be distinct from every other M3U account this
  // harness creates concurrently: a collision on IntervalSchedule bricks
  // the container (issue #7).
  const account = await seed.m3uAccount({ is_active: true, refresh_interval: 8531 });

  const start = Date.now();
  const result = await waitFor.m3uRefreshComplete(account.id, { startTimeoutMs: 5_000 });
  const elapsed = Date.now() - start;

  expect(result.status).toBe('error');
  // An unfixed phase 1 would burn the entire startTimeoutMs budget (5s
  // here) and throw instead of returning. Resolving well under that bound
  // proves both that it was fast *and* that it returned normally.
  expect(elapsed).toBeLessThan(3_000);
});
