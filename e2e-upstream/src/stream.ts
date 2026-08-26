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
  onClosed(stats: { bytes: number; durationMs: number }): void;
}

/**
 * The dead-air/rate state to start a connection in, sourced from
 * `FaultStore.initialStateFor` in the route — see that method for why a
 * brand-new connection needs this rather than starting clean and waiting for
 * `apply` to reach it later.
 */
export interface StreamInitialState {
  deadAir?: boolean;
  rate?: number | null;
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
  connection: LiveConnection,
  initial: StreamInitialState = {}
): Promise<void> {
  let deadAir = initial.deadAir ?? false;
  let rateOverride: number | null = initial.rate ?? null;
  let closing: { clean: boolean; afterBytes?: number } | undefined;
  let written = 0;
  let open = true;
  const startedAt = Date.now();

  // Set only while parked in one of the two interruptible waits below (the
  // pacing sleep and the drain wait), so a control method called at any
  // other point in the loop is a harmless no-op — everywhere else already
  // reads fresh state on its own next iteration. It resolves whichever wait
  // is currently active exactly once — a second call before a new wait has
  // re-armed it is also a harmless no-op, which is deliberate: the loop only
  // needs telling once that *something* changed, not once per thing.
  let wake: (() => void) | null = null;

  // Interruptible pacing delay: without this, a disconnect or rate change
  // fired while parked here wouldn't be noticed until the current sleep
  // elapses naturally — seconds, at slow-trickle rates. `setRate`,
  // `disconnect` and `refreshRate` below all reach it through the same
  // `wake`. Deliberately not used for the dead-air poll below: that one is
  // already never more than 100ms from checking fresh state, so there's
  // nothing worth interrupting.
  const interruptibleSleep = (ms: number): Promise<void> =>
    new Promise<void>((resolve) => {
      const finish = () => {
        wake = null;
        resolve();
      };
      const timer = setTimeout(finish, ms);
      wake = () => {
        clearTimeout(timer);
        finish();
      };
    });

  connection.setDeadAir = (active) => {
    deadAir = active;
  };
  connection.setRate = (rate) => {
    rateOverride = rate;
    wake?.();
  };
  connection.disconnect = (options) => {
    closing = options;
    wake?.();
  };
  connection.refreshRate = () => {
    wake?.();
  };

  res.writeHead(200, {
    'Content-Type': STREAM_CONTENT_TYPE,
    // No Content-Length: this stream has no end, and declaring one makes
    // requests wait for bytes that never come.
    'Cache-Control': 'no-store',
  });
  // Node buffers response headers until the first body write (or `end()`)
  // by default. A connection that starts with dead-air already armed (see
  // `initial` above) may not write anything for a long time, or ever, which
  // without this would leave the client's own request hanging with no
  // response at all — indistinguishable from the provider never having
  // accepted the connection, rather than "connected, no bytes yet".
  res.flushHeaders();

  control.onConnection(connection);
  res.on('close', () => {
    open = false;
    control.onClosed({ bytes: written, durationMs: Date.now() - startedAt });
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

      let backpressureOutcome: 'drained' | 'terminated' | 'woken' | undefined;

      if (chunk.byteLength > 0 && !res.write(chunk)) {
        // Respect backpressure, or a slow client turns into unbounded memory
        // in this process rather than a slow stream. Racing against
        // 'close'/'error' too matters because Node never emits 'drain' on a
        // destroyed stream — a client that disconnects while backpressured
        // (routine once Task 6's disconnect faults exist) would otherwise
        // hang this promise forever even though the socket is long gone.
        // Setting `open = false` here doesn't race the outer 'close'
        // listener registered before the loop started: both run, in
        // registration order, and either one is enough to make the check
        // below true.
        //
        // `wake` covers the fourth way out: a fault's control methods
        // firing while parked here with nothing else to wake this promise.
        // The client isn't reading, so 'drain' will never come; nobody has
        // torn the socket down, so 'close'/'error' won't either. The
        // outcome is tagged, not just resolved, because 'woken' has to be
        // handled differently below: it means some *other* state changed
        // while we were stuck, so the right response is to go straight back
        // to the top of the loop and re-read everything fresh — not to fall
        // through the normal post-write bookkeeping as if this had been an
        // ordinary drain, which is what let a disconnect that arrived this
        // way sit ignored behind a freshly-scheduled sleep.
        backpressureOutcome = await new Promise<'drained' | 'terminated' | 'woken'>((resolve) => {
          const cleanup = () => {
            res.off('drain', onDrain);
            res.off('close', onTerminated);
            res.off('error', onTerminated);
            wake = null;
          };
          const onDrain = () => {
            cleanup();
            resolve('drained');
          };
          const onTerminated = () => {
            open = false;
            cleanup();
            resolve('terminated');
          };
          res.once('drain', onDrain);
          res.once('close', onTerminated);
          res.once('error', onTerminated);
          wake = () => {
            cleanup();
            resolve('woken');
          };
        });
        if (backpressureOutcome === 'terminated') return;
      }

      // Unconditional: `res.write()` already handed the chunk to Node
      // whether or not it has drained yet, so the byte count is accurate
      // regardless of why (or whether) we waited above.
      written += chunk.byteLength;

      // A wake means some control method changed `closing` or the rate
      // while we were parked above. Re-checking both at the top of the loop
      // is what the very next line of code already does on every ordinary
      // iteration — jumping there directly, rather than continuing through
      // this iteration's now-stale `stopAfterThisChunk` and pacing sleep, is
      // what makes that re-check actually happen promptly instead of after
      // whatever this iteration was already going to do next.
      if (backpressureOutcome === 'woken') continue;

      if (stopAfterThisChunk) {
        if (closing!.clean) res.end();
        else res.destroy();
        return;
      }

      // Sleep against this chunk's own size, not a cumulative target, so a
      // rate changed mid-stream takes effect on the very next chunk instead
      // of being averaged away by everything already sent.
      const rate = rateOverride ?? control.scenarioRate();
      await interruptibleSleep((chunk.byteLength / (asset.byteRate * rate)) * 1000);
    }
  })();
}
