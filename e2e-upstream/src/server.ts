import http from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { ScenarioRegistry } from './scenario.js';
import type { Scenario, ScenarioRequest } from './scenario.js';

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

export const registry = new ScenarioRegistry();

export async function readJsonBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

/**
 * `internal` is what Dispatcharr is given; `control` is what the Playwright
 * host calls. They are never interchangeable — see "Two base URLs" in the
 * spec. INTERNAL_ORIGIN is what resolves inside the Docker network; the
 * control origin is echoed from the request's own Host header, so it is
 * correct whatever port the caller published.
 */
const INTERNAL_ORIGIN =
  process.env.UPSTREAM_INTERNAL_ORIGIN ?? 'http://e2e-upstream:8080';

function scenarioUrls(scenario: Scenario, req: IncomingMessage) {
  const credentialQuery =
    scenario.username === undefined
      ? ''
      : `?username=${encodeURIComponent(scenario.username)}` +
        `&password=${encodeURIComponent(scenario.password ?? '')}`;

  return {
    internal: `${INTERNAL_ORIGIN}/s/${scenario.id}`,
    control: `http://${req.headers.host ?? '127.0.0.1'}/s/${scenario.id}`,
    credentialQuery,
  };
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? '/', 'http://placeholder');

  if (url.pathname === '/scenarios' && req.method === 'GET') {
    sendJson(res, 200, registry.list().map((s) => ({ ...s, ...scenarioUrls(s, req) })));
    return;
  }

  if (url.pathname === '/scenarios' && req.method === 'POST') {
    const scenario = registry.create((await readJsonBody(req)) as ScenarioRequest);
    sendJson(res, 201, { ...scenario, ...scenarioUrls(scenario, req) });
    return;
  }

  const scenarioMatch = /^\/scenarios\/([^/]+)$/.exec(url.pathname);
  if (scenarioMatch && req.method === 'DELETE') {
    sendJson(res, registry.delete(scenarioMatch[1]) ? 204 : 404, {});
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
