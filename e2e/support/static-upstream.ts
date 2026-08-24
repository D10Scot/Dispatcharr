/**
 * THROWAWAY. A minimal endless MPEG-TS source, here only so streamClient has
 * something real to read before G2's fake provider exists. Delete this file
 * when G2 lands.
 *
 * Emits well-formed 188-byte packets on PID 0x0100 with an incrementing
 * continuity counter, so alignment assertions are meaningful.
 */
import http from 'node:http';

const TS_PACKET_SIZE = 188;
const SYNC_BYTE = 0x47;

export const PACKETS_PER_BURST = 10;

export interface StaticUpstreamOptions {
  /**
   * Emit one burst at each of these millisecond offsets and nothing after —
   * the connection stays open, silent. Omit for the default endless cadence.
   * A stalled stream is what the streamClient read-ordering test needs.
   */
  burstsAtMs?: number[];
  /** With `burstsAtMs`, end the response after the last burst instead of
   *  falling silent — a stream that genuinely runs short. */
  endAfterLastBurst?: boolean;
}

function makePacket(counter: number): Buffer {
  const packet = Buffer.alloc(TS_PACKET_SIZE, 0xff);
  packet[0] = SYNC_BYTE;
  packet[1] = 0x01; // PID high bits
  packet[2] = 0x00; // PID low bits
  packet[3] = 0x10 | (counter % 16); // payload only + continuity counter
  return packet;
}

export async function startStaticUpstream(
  port: number,
  options: StaticUpstreamOptions = {}
) {
  let counter = 0;
  const burst = () =>
    Buffer.concat(Array.from({ length: PACKETS_PER_BURST }, () => makePacket(counter++)));

  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'video/mp2t' });

    if (options.burstsAtMs) {
      const last = options.burstsAtMs.length - 1;
      const timers = options.burstsAtMs.map((at, i) =>
        setTimeout(() => {
          res.write(burst());
          if (i === last && options.endAfterLastBurst) res.end();
        }, at)
      );
      res.on('close', () => timers.forEach(clearTimeout));
      return;
    }

    const timer = setInterval(() => res.write(burst()), 20);
    res.on('close', () => clearInterval(timer));
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', (err) =>
      reject(new Error(`static upstream failed to listen on port ${port}: ${err.message}`))
    );
    server.listen(port, '127.0.0.1', resolve);
  });

  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}
