import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';
import { withDeadline } from './helpers';

// Regression: collectFor(ms) races pump() against a timer. When the timer
// wins, that pump()'s reader.read() is left outstanding. Read requests queue
// FIFO — an arriving chunk fulfils the *first* pending request — so a
// readPackets() that issued its own reader.read() would sit behind the
// abandoned one, waiting on a chunk after the one it needed. On a stalled
// stream that is a deadlock with the wanted bytes already in the buffer.
// pump() now memoises the single in-flight read; this test is what proves it.
//
// These two specs test streamClient's own semantics, not Dispatcharr's proxy,
// so they hit the provider directly through `control` rather than routing
// through the product.

// The streaming project has timeout: 300_000, so an unbounded await on a
// regression is a five-minute test with a useless "Test timeout exceeded"
// message. Bound the read ourselves (via the shared `withDeadline` helper in
// helpers.ts) so it fails in seconds, naming the cause: if this fires, the
// stalled-stream deadlock is back — collectFor left a reader.read()
// outstanding and the call below queued a second one behind it, so it is
// waiting on a chunk that never arrives.
const READ_DEADLINE_MS = 10_000;

test('readPackets returns promptly when collectFor timed out mid-read', async ({
  upstream,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });
  await streamClient.open(upstream.toControl(upstream.streamUrl(scenario, 1)));

  // Let bytes flow, then stall the socket with it still open.
  const flowing = await streamClient.readPackets(5);
  expectTsAligned(flowing);

  const applied = await upstream.fault(scenario, 'dead-air');
  // dead-air reaches live connections, so this must be 1. If it is 0 the
  // stream was never admitted and the rest of this test proves nothing.
  expect(applied.appliedTo).toBe(1);

  // The 200ms deadline expires with a reader.read() outstanding.
  await streamClient.collectFor(200);

  // Issue the read *before* releasing any data. readPackets must queue its
  // own reader.read() while the collectFor-abandoned one is still pending —
  // the same ordering the static-upstream original relied on, where burst 2
  // arrived only after readPackets had already been called. Awaiting this
  // later, once the fulfilling chunk has already landed, would let bytes
  // already sitting in bufferedBytes short-circuit the pump() call
  // entirely (the while loop below never even runs it) and prove nothing
  // about which reader.read() actually receives them.
  const afterPromise = withDeadline(
    streamClient.readPackets(1),
    READ_DEADLINE_MS,
    'readPackets after a timed-out collectFor'
  );

  // Simply clearing dead-air is not enough: the provider's stream is
  // endless, so a *second* chunk follows the one that fulfils the abandoned
  // read within milliseconds, and a non-memoised pump() would happily read
  // that second chunk instead — passing by luck instead of by fix. Slow the
  // scenario to a crawl first, so there is a wide window between the one
  // chunk that resuming releases and the next one the provider would
  // otherwise produce, then re-arm dead-air — and never clear it again —
  // inside that window. That reproduces the property that actually makes
  // this a regression test: one chunk, then silence forever, the same as
  // the static upstream's burstsAtMs schedule (one burst, then nothing).
  // Permanent silence is what turns a memoisation bug into a deterministic
  // hang instead of a race a second chunk could win and mask.
  await upstream.rate(scenario, 0.01);
  await upstream.clearFault(scenario, 'dead-air');
  // The provider's own dead-air poll is 100ms — give the loop a chance to
  // wake up and actually write that one chunk before re-arming, or the
  // re-arm can win the race and no chunk is ever produced at all.
  await new Promise((resolve) => setTimeout(resolve, 500));
  await upstream.fault(scenario, 'dead-air');

  const after = await afterPromise;
  expectTsAligned(after);
});

test('readPackets throws by name when the stream ends short', async ({
  upstream,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });
  await streamClient.open(upstream.toControl(upstream.streamUrl(scenario, 1)));

  // A clean EOF after a bounded number of bytes — the product logs this as
  // "HTTP stream ended", a different reconnect branch from an abrupt close.
  await upstream.fault(scenario, 'disconnect', {
    clean: true,
    afterBytes: 20 * TS_PACKET_SIZE,
  });

  await expect(
    withDeadline(streamClient.readPackets(1000), READ_DEADLINE_MS, 'readPackets past the end')
  ).rejects.toThrow(/stream ended after \d+ bytes/);
});
