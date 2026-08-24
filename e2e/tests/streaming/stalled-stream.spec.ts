import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';
import { startStaticUpstream, PACKETS_PER_BURST } from '../../support/static-upstream';

// Regression: collectFor(ms) races pump() against a timer. When the timer
// wins, that pump()'s reader.read() is left outstanding. Read requests queue
// FIFO — an arriving chunk fulfils the *first* pending request — so a
// readPackets() that issued its own reader.read() would sit behind the
// abandoned one, waiting on a chunk after the one it needed. On a stalled
// stream that is a deadlock with the wanted bytes already in the buffer.
// pump() now memoises the single in-flight read; this test is what proves it.
//
// See the exemplar in stream-client.spec.ts for the port-derivation rule.
const UPSTREAM_BASE_PORT = 9411;

// The streaming project has timeout: 300_000, so an unbounded await on a
// regression is a five-minute test with a useless "Test timeout exceeded"
// message. Bound the read ourselves so it fails in seconds, naming the cause.
const READ_DEADLINE_MS = 10_000;

async function withDeadline<T>(work: Promise<T>, ms: number, what: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const guard = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () =>
        reject(
          new Error(
            `${what} did not settle within ${ms}ms. The stalled-stream deadlock is back: ` +
              `collectFor left a reader.read() outstanding and this call queued a second ` +
              `one behind it, so it is waiting on a chunk that never arrives.`
          )
        ),
      ms
    );
  });
  try {
    return await Promise.race([work, guard]);
  } finally {
    clearTimeout(timer);
  }
}

test('readPackets returns promptly when collectFor timed out mid-read', async ({
  streamClient,
}, testInfo) => {
  // Burst at t=0, burst at t=600ms, silence thereafter with the socket open.
  const upstream = await startStaticUpstream(UPSTREAM_BASE_PORT + testInfo.workerIndex, {
    burstsAtMs: [0, 600],
  });

  try {
    await streamClient.open(`${upstream.url}/stalls.ts`);

    // Burst 1 lands at once; the 200ms deadline then expires with a
    // reader.read() outstanding, and collectFor drains the buffer.
    const collected = await streamClient.collectFor(200);
    expect(collected.byteLength).toBe(PACKETS_PER_BURST * TS_PACKET_SIZE);

    // Burst 2 fulfils that outstanding read and lands in the buffer. The
    // stream has not ended, and the bytes asked for are present — so
    // returning them is the only correct outcome here. Throwing would be
    // wrong: readPackets only throws when the stream *ends* short, and this
    // one is merely silent.
    const packets = await withDeadline(
      streamClient.readPackets(PACKETS_PER_BURST),
      READ_DEADLINE_MS,
      'readPackets'
    );
    expect(packets.byteLength).toBe(PACKETS_PER_BURST * TS_PACKET_SIZE);
    expectTsAligned(packets);
  } finally {
    await streamClient.close();
    await upstream.close();
  }
});

test('readPackets still throws naming the shortfall when the stream ends short', async ({
  streamClient,
}, testInfo) => {
  const upstream = await startStaticUpstream(UPSTREAM_BASE_PORT + 10 + testInfo.workerIndex, {
    burstsAtMs: [0],
    endAfterLastBurst: true,
  });

  try {
    await streamClient.open(`${upstream.url}/short.ts`);

    const wanted = PACKETS_PER_BURST * 3;
    await expect(
      withDeadline(streamClient.readPackets(wanted), READ_DEADLINE_MS, 'readPackets')
    ).rejects.toThrow(
      `stream ended after ${PACKETS_PER_BURST * TS_PACKET_SIZE} bytes, wanted ${
        wanted * TS_PACKET_SIZE
      }`
    );
  } finally {
    await streamClient.close();
    await upstream.close();
  }
});
