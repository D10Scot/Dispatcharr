import http from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';

export interface RunningServer {
  close(): Promise<void>;
  port: number;
}

export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? '/', 'http://placeholder');

  if (url.pathname === '/scenarios' && req.method === 'GET') {
    sendJson(res, 200, []);
    return;
  }

  sendJson(res, 404, { error: `no route for ${req.method} ${url.pathname}` });
}

// Exported so a test can exercise the catch path directly, without needing
// `handle()` to throw over a real socket. Behaviourally identical to inlining
// this in the `createServer` callback below.
export async function requestListener(req: IncomingMessage, res: ServerResponse): Promise<void> {
  try {
    await handle(req, res);
  } catch (error: unknown) {
    // Without this the process dies on a handler throw and the container
    // restarts silently mid-test, which reads as a network flake.
    if (!res.headersSent) {
      sendJson(res, 500, { error: String(error) });
    } else {
      res.destroy();
    }
  }
}

export function startServer(port: number): Promise<RunningServer> {
  const server = http.createServer((req, res) => {
    requestListener(req, res).catch(() => {
      // requestListener above already swallows every error `handle()` can
      // throw; this is a backstop in case that swallowing logic itself
      // ever throws, so a bug there can't take the whole process down.
      res.destroy();
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '0.0.0.0', () => {
      // The `once('error', reject)` above only covers the listen attempt.
      // Once we're up, a later socket error (e.g. ECONNRESET on an
      // in-flight connection) has no listener left and would otherwise
      // crash the process — fatal today, and much more likely once
      // streaming sockets are added. Log and keep serving instead.
      server.on('error', (error: unknown) => {
        console.error('e2e-upstream server error:', error);
      });
      resolve({
        port: (server.address() as AddressInfo).port,
        close: () =>
          new Promise<void>((done, fail) =>
            server.close((err) => (err ? fail(err) : done()))
          ),
      });
    });
  });
}
