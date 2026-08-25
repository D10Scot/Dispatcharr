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

export function startServer(port: number): Promise<RunningServer> {
  const server = http.createServer((req, res) => {
    handle(req, res).catch((error: unknown) => {
      // Without this the process dies on a handler throw and the container
      // restarts silently mid-test, which reads as a network flake.
      if (!res.headersSent) {
        sendJson(res, 500, { error: String(error) });
      } else {
        res.destroy();
      }
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '0.0.0.0', () => {
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
