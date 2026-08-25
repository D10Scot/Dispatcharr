import type { ServerResponse } from 'node:http';
import { TS_PACKET_SIZE } from './ts.js';
import { LoopRewriter } from './ts-loop.js';
import type { LoadedAsset } from './asset.js';
import type { LiveConnection } from './connections.js';

export const STREAM_CONTENT_TYPE = 'video/mp2t';
/** ~7.5 KB, which at 2 Mbit is a wakeup every ~30 ms. */
export const PACKETS_PER_CHUNK = 40;

export interface StreamControl {
  scenarioRate(): number;
  onConnection(connection: LiveConnection): void;
  // Task 7 widens this to onClosed(stats: { bytes: number; durationMs: number })
  // to log connection-close events. streamLoop already tracks both `written`
  // and `startedAt` below so that widening is just a call-site change.
  onClosed(): void;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Streams `asset` on a loop to `res`, paced at the asset's own bitrate times
 * `control.scenarioRate()`.
 *
 * `connection` must already be admitted by the caller (see
 * `ConnectionRegistry.tryAcquire`) before this is called — admission has to
 * be decided before any header is written, or a rejected client has already
 * received a 200. This function attaches its live control methods to that
 * same object rather than constructing a new one, so the identity the
 * registry admitted is the identity a fault handler later calls back into.
 */
export function streamLoop(
  res: ServerResponse,
  asset: LoadedAsset,
  control: StreamControl,
  connection: LiveConnection
): Promise<void> {
  let deadAir = false;
  let rateOverride: number | null = null;
  let closing: { clean: boolean; afterBytes?: number } | undefined;
  let written = 0;
  let open = true;
  const startedAt = Date.now();

  connection.setDeadAir = (active) => {
    deadAir = active;
  };
  connection.setRate = (rate) => {
    rateOverride = rate;
  };
  connection.disconnect = (options) => {
    closing = options;
  };

  res.writeHead(200, {
    'Content-Type': STREAM_CONTENT_TYPE,
    // No Content-Length: this stream has no end, and declaring one makes
    // requests wait for bytes that never come.
    'Cache-Control': 'no-store',
  });

  control.onConnection(connection);
  res.on('close', () => {
    open = false;
    // Tracked here for Task 7's onClosed({ bytes, durationMs }); nothing
    // consumes them yet, so they aren't threaded through this call.
    void written;
    void (Date.now() - startedAt);
    control.onClosed();
  });

  const rewriter = new LoopRewriter(asset.loopDuration90k);
  const totalPackets = asset.bytes.byteLength / TS_PACKET_SIZE;

  return (async () => {
    let index = 0;

    while (open) {
      // A bare disconnect (no afterBytes) ends right away. One with
      // afterBytes only ends once that many bytes have actually gone out —
      // checking `closing` alone here, regardless of afterBytes, would end
      // the stream on the very next iteration no matter what threshold was
      // requested, making afterBytes dead code.
      if (closing && (closing.afterBytes === undefined || written >= closing.afterBytes)) {
        if (closing.clean) res.end();
        else res.destroy();
        return;
      }

      if (deadAir) {
        // Open socket, no bytes. Poll rather than await a signal so a fault
        // cleared mid-stall resumes without reconnecting.
        await sleep(100);
        continue;
      }

      const chunkPackets: Buffer[] = [];
      for (let n = 0; n < PACKETS_PER_CHUNK; n += 1) {
        const at = index * TS_PACKET_SIZE;
        chunkPackets.push(rewriter.rewrite(asset.bytes.subarray(at, at + TS_PACKET_SIZE)));

        index += 1;
        if (index >= totalPackets) {
          index = 0;
          rewriter.advanceLoop();
        }
      }

      let chunk = Buffer.concat(chunkPackets);
      let stopAfterThisChunk = false;

      if (closing?.afterBytes !== undefined && written + chunk.byteLength >= closing.afterBytes) {
        chunk = chunk.subarray(0, Math.max(0, closing.afterBytes - written));
        stopAfterThisChunk = true;
      }

      if (chunk.byteLength > 0 && !res.write(chunk)) {
        // Respect backpressure, or a slow client turns into unbounded memory
        // in this process rather than a slow stream.
        await new Promise<void>((resolve) => res.once('drain', resolve));
      }
      written += chunk.byteLength;

      if (stopAfterThisChunk) {
        if (closing!.clean) res.end();
        else res.destroy();
        return;
      }

      // Sleep against this chunk's own size, not a cumulative target, so a
      // rate changed mid-stream takes effect on the very next chunk instead
      // of being averaged away by everything already sent.
      const rate = rateOverride ?? control.scenarioRate();
      await sleep((chunk.byteLength / (asset.byteRate * rate)) * 1000);
    }
  })();
}
