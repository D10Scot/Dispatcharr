import { test, expect } from '../../fixtures';
import type { Channel } from '../../fixtures';

// Exemplar: polling is the default way to wait for backend state. Prefer it
// over the WebSocket unless the state is only observable there.
test('waitFor.resource polls until a created channel appears', async ({
  api,
  seed,
  waitFor,
}) => {
  const channel = await seed.channel();

  // The type argument is not decoration: `resource` has no default for it,
  // so `(body) => body.nmae === …` is a compile error rather than a poll
  // that can never succeed.
  const found = await waitFor.resource<Channel>(
    `/api/channels/channels/${channel.id}/`,
    (body) => body.name === channel.name
  );

  expect(found.id).toBe(channel.id);
});

// Exemplar: the WebSocket fixture, for state the REST API does not expose.
//
// This waits on an event caused *after* the fixture handed the socket over,
// which makes it an assertion about the fixture and not only about the
// product. `dispatcharr/consumers.py` calls accept(), then group_add(), then
// sends connection_established — so a listener handed over the moment `new
// WebSocket(...)` returns is a socket in no group yet. The create below would
// broadcast to a group this socket had not joined, and this wait would time
// out. The `ws` fixture awaits `ready()` to close that window; it consumes the
// handshake message doing so, which is why this test no longer waits on that
// message. There is exactly one per socket and the fixture has taken it.
//
// `where` and not a bare type match: /ws/ is one broadcast group and `seeded`
// runs four workers, so this socket sees every worker's playlist_created too.
test('ws fixture is subscribed before a test can act', async ({ ws, seed }) => {
  // A refresh_interval no other concurrent spec uses, per the IntervalSchedule
  // race in issue #7 — see the header of ws-fixture.spec.ts.
  const account = await seed.m3uAccount({ refresh_interval: 8532 });

  const message = await ws.waitForMessage('playlist_created', {
    where: (data) => data.playlist_id === account.id,
  });

  // `data?.` and not `data.`: the product sends messages with no payload at
  // all, so `WsMessage.data` is optional. A missing one fails this assertion
  // as `undefined !== …` rather than throwing a TypeError.
  expect(message.data?.playlist_id).toBe(account.id);
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
