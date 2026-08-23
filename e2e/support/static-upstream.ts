import http from 'node:http';

const TS_PACKET_SIZE = 188;
const SYNC_BYTE = 0x47;

/**
 * THROWAWAY. A minimal endless MPEG-TS source, here only so streamClient has
 * something real to read before G2's fake provider exists. Delete this file
 * when G2 lands.
 *
 * Emits well-formed 188-byte packets on PID 0x0100 with an incrementing
 * continuity counter, so alignment assertions are meaningful.
 */
function makePacket(counter: number): Buffer {
  const packet = Buffer.alloc(TS_PACKET_SIZE, 0xff);
  packet[0] = SYNC_BYTE;
  packet[1] = 0x01; // PID high bits
  packet[2] = 0x00; // PID low bits
  packet[3] = 0x10 | (counter % 16); // payload only + continuity counter
  return packet;
}

export async function startStaticUpstream(port: number) {
  let counter = 0;

  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'video/mp2t' });
    const timer = setInterval(() => {
      const burst = Buffer.concat(
        Array.from({ length: 10 }, () => makePacket(counter++))
      );
      res.write(burst);
    }, 20);
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
