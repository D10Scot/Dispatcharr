import { test, expect } from '../../fixtures';

/**
 * The `ws` fixture's queue semantics. `async-wait.spec.ts` is the exemplar
 * for *using* the socket (and for preferring `waitFor` over it); this file
 * pins the three behaviours that make waiting on a shared broadcast honest:
 *
 *  1. a message is consumed by the wait that takes it, so two sequential
 *     waits for one type return two different messages;
 *  2. a wait that times out is deregistered, so it cannot swallow the event
 *     a later wait is waiting for;
 *  3. `where` correlates a wait to the event this test caused, rather than
 *     the first event of that type from any of the four parallel workers.
 *
 * All three drive real product events: creating an M3U account makes
 * `apps/m3u/api_views.py:131` push
 * `{"type": "update", "data": {"type": "playlist_created", "playlist_id": N}}`
 * to the shared `updates` group. Nothing here mocks the socket — a test
 * against a fake socket would prove nothing about this fixture.
 *
 * ---------------------------------------------------------------------------
 * Why every seed here passes an explicit `refresh_interval`
 * ---------------------------------------------------------------------------
 * Creating an M3U account runs `create_or_update_periodic_task()`
 * (`core/scheduling.py:121`) in a `post_save` signal, which does
 * `IntervalSchedule.objects.get_or_create(every=<refresh_interval or 1>,
 * period=HOURS)` on a table with no unique constraint. Two accounts created
 * *concurrently* with the same `refresh_interval` therefore insert two
 * identical rows, and from then on every M3U and EPG source creation on that
 * instance returns 500 for good — D10Scot/Dispatcharr#7, found by an earlier
 * revision of this file doing exactly that from four parallel workers.
 *
 * Giving each test its own `refresh_interval` puts each one on its own
 * `IntervalSchedule` row, and the two creations inside a test are sequential,
 * so nothing here ever creates the same row twice at once. Other specs use
 * the shipped default (which maps to `every=1`), so they do not collide with
 * these either. Pick an unused number if you add a test here, and do not
 * remove the argument: without it this file bricks the container it runs
 * against roughly every other run.
 */

test('two sequential waits for one type return two different messages', async ({
  ws,
  seed,
}) => {
  // Both events are fired before either wait is registered, so both are
  // queued and the waits consume them from the queue. If `waitForMessage`
  // replayed instead of consuming (the defect this pins), the second wait
  // would return the first message again and the ids would be equal.
  await seed.m3uAccount({ refresh_interval: 2 });
  await seed.m3uAccount({ refresh_interval: 2 });

  const one = await ws.waitForMessage('playlist_created', { timeoutMs: 15_000 });
  const two = await ws.waitForMessage('playlist_created', { timeoutMs: 15_000 });

  expect(one.data?.type).toBe('playlist_created');
  expect(two.data?.type).toBe('playlist_created');
  // Deliberately not asserting *which* ids: /ws/ is a broadcast and a
  // parallel worker's playlist_created can be interleaved with these two.
  // That is exactly why the next test needs `where` — and why "different"
  // is the strongest thing a bare type match can assert here.
  expect(two).not.toBe(one);
  expect(two.data?.playlist_id).not.toBe(one.data?.playlist_id);
});

test('a wait that timed out does not swallow a later wait\'s event', async ({
  ws,
  seed,
}) => {
  // A predicate that can never match guarantees the first wait times out
  // regardless of what the other workers are broadcasting — the scenario
  // has to be deterministic, and "no playlist was created anywhere in the
  // instance for 500ms" is not something this test can guarantee.
  //
  // It also doubles as a probe: it counts how many times it is evaluated
  // *after* its wait has already rejected. A waiter left registered would
  // be handed the next matching message and evaluate it; a deregistered one
  // cannot. So `evaluationsAfterTimeout` observes the removal directly
  // rather than inferring it.
  let timedOut = false;
  let evaluationsAfterTimeout = 0;
  const doomed = ws.waitForMessage('playlist_created', {
    timeoutMs: 500,
    where: () => {
      if (timedOut) evaluationsAfterTimeout++;
      return false;
    },
  });

  await expect(doomed).rejects.toThrow(/timed out after 500ms/);
  timedOut = true;

  // The retry, registered *before* the event that should satisfy it — the
  // ordering that hung. Under the old implementation the timed-out waiter was
  // still in the list, matched this event on type, was spliced out and
  // "resolved" (a no-op on an already-rejected promise), and this wait then
  // sat there until its own timeout with the event consumed and discarded.
  // Measured: it failed with "timed out after 8000ms ... received:
  // [connection_established, playlist_created]" — the event it wanted, listed
  // in the diagnostic of the wait that never got it.
  //
  // Registering first is also why this cannot be a `where` wait: the id to
  // correlate on does not exist until the POST returns, and a waiter is
  // matched when the message arrives, not re-scanned afterwards. A type-only
  // wait can in principle resolve on a parallel worker's playlist_created —
  // that is fine here, because either way it proves the dead waiter did not
  // swallow the delivery. `evaluationsAfterTimeout` is what pins the removal.
  const retry = ws.waitForMessage('playlist_created', { timeoutMs: 15_000 });
  const account = await seed.m3uAccount({ refresh_interval: 3 });
  const message = await retry;

  expect(message.data?.type).toBe('playlist_created');
  expect(account.id).toBeTruthy();
  expect(evaluationsAfterTimeout).toBe(0);
});

test('a `where` wait resolves on its own event, not the first to arrive', async ({
  ws,
  seed,
}) => {
  const first = await seed.m3uAccount({ refresh_interval: 4 });
  const second = await seed.m3uAccount({ refresh_interval: 4 });

  // `first`'s event is queued ahead of `second`'s, so a type-only wait would
  // return it. The predicate must skip past it.
  const forSecond = await ws.waitForMessage('playlist_created', {
    timeoutMs: 15_000,
    where: (data) => data.playlist_id === second.id,
  });
  expect(forSecond.data?.playlist_id).toBe(second.id);

  // And skipping past it must not consume it: the message a predicate
  // declined is still there for the next wait.
  const forFirst = await ws.waitForMessage('playlist_created', {
    timeoutMs: 15_000,
    where: (data) => data.playlist_id === first.id,
  });
  expect(forFirst.data?.playlist_id).toBe(first.id);
});
