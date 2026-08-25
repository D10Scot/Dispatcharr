import { describe, it, expect, afterEach } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { TS_PACKET_SIZE } from '../src/ts.js';
import { measureLoop } from '../src/asset.js';
import { streamLoop, STREAM_CONTENT_TYPE } from '../src/stream.js';
import type { LoadedAsset } from '../src/asset.js';
import type { LiveConnection } from '../src/connections.js';
import { makeSyntheticTs } from './helpers/synthetic-ts.js';

const STEP = 3600n;
const PACKETS = 200;

function fakeAsset(): LoadedAsset {
  const bytes = makeSyntheticTs({ packets: PACKETS, pid: 0x0100, step: STEP });
  const { loopDuration90k, durationSeconds } = measureLoop(bytes);
  return { bytes, loopDuration90k, durationSeconds, byteRate: bytes.byteLength / durationSeconds };
}

// streamLoop takes an already-admitted connection (see the route in
// server.ts) and attaches its live control methods to it in place, so a test
// can hold this reference directly instead of capturing one out of a
// callback.
function fakeConnection(): LiveConnection {
  return {
    scenarioId: 'scenario-under-test',
    channelId: 1,
    setDeadAir: () => {},
    setRate: () => {},
    disconnect: () => {},
  };
}

let server: http.Server | undefined;

afterEach(() => {
  server?.close();
  server = undefined;
});

async function serve(rate: number, connection: LiveConnection = fakeConnection()): Promise<string> {
  const asset = fakeAsset();
  server = http.createServer((_req, res) => {
    void streamLoop(
      res,
      asset,
      {
        scenarioRate: () => rate,
        onConnection: () => {},
        onClosed: () => {},
      },
      connection
    );
  });
  await new Promise<void>((resolve) => server!.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${(server!.address() as AddressInfo).port}/`;
}

describe('streamLoop', () => {
  it('serves 188-aligned TS with the content type the product expects', async () => {
    const url = await serve(50);
    const res = await fetch(url);

    expect(res.headers.get('content-type')).toBe(STREAM_CONTENT_TYPE);

    const reader = res.body!.getReader();
    const first = await reader.read();
    await reader.cancel();

    expect(first.value![0]).toBe(0x47);
    expect(first.value!.byteLength % TS_PACKET_SIZE).toBe(0);
  });

  it('paces roughly to the asset bitrate times the rate', async () => {
    // The property that matters: an unpaced provider is read at wire speed
    // and floods Dispatcharr's Redis ring buffer. Tolerance is wide because
    // this measures real time on a shared runner; it is checking an order of
    // magnitude, not a stopwatch.
    const asset = fakeAsset();
    const url = await serve(10);
    const started = Date.now();

    const res = await fetch(url);
    const reader = res.body!.getReader();
    let read = 0;
    const want = Math.floor(asset.byteRate * 10 * 0.5); // ~0.5s of output
    while (read < want) {
      const { value, done } = await reader.read();
      if (done) break;
      read += value!.byteLength;
    }
    await reader.cancel();

    const elapsed = Date.now() - started;
    expect(elapsed).toBeGreaterThan(150);
    expect(elapsed).toBeLessThan(4000);
  });

  it('stops writing when dead air is set, without closing the connection', async () => {
    const connection = fakeConnection();
    const url = await serve(50, connection);
    const res = await fetch(url);
    const reader = res.body!.getReader();

    await reader.read(); // prove it is flowing
    connection.setDeadAir(true);

    const stalled = await Promise.race([
      reader.read().then(() => 'read' as const),
      new Promise<'silent'>((resolve) => setTimeout(() => resolve('silent'), 1000)),
    ]);
    await reader.cancel();

    expect(stalled).toBe('silent');
  });

  it('cuts off exactly at afterBytes rather than on the next poll regardless of it', async () => {
    // A regression test for a real bug in the original design: checking
    // `closing` alone at the top of the loop, with no regard for
    // `afterBytes`, ends the stream on the very next iteration no matter
    // what threshold was requested — making afterBytes dead code.
    const connection = fakeConnection();
    const url = await serve(1000, connection); // fast, so the test stays quick
    const res = await fetch(url);
    const reader = res.body!.getReader();

    const first = await reader.read();
    const afterBytes = first.value!.byteLength + TS_PACKET_SIZE * 5;
    connection.disconnect({ clean: true, afterBytes });

    let total = first.value!.byteLength;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value!.byteLength;
    }

    expect(total).toBe(afterBytes);
  });
});
