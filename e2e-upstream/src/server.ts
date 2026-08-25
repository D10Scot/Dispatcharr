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

/**
 * Thrown by request-parsing helpers on bad client input. Caught in
 * `requestListener` and mapped to 400, distinct from the generic 500 for
 * everything else — every route added from here on (Tasks 3-7's
 * `POST /s/<id>/fault` and `/rate`) should read its body through
 * `readJsonObject` rather than re-deriving this.
 */
export class BadRequestError extends Error {}

async function readRawBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

/**
 * Reads and parses a JSON request body, guaranteeing the result is a plain
 * object (never null, an array, or a primitive) so callers can spread or
 * index into it without a runtime crash disguising itself as a 500. An empty
 * body is deliberately treated as `{}` — that's how `POST /scenarios` with no
 * body creates a default scenario — but any non-empty, non-object body is
 * rejected with `BadRequestError` rather than silently coerced.
 */
export async function readJsonObject(req: IncomingMessage): Promise<Record<string, unknown>> {
  const raw = await readRawBody(req);
  if (raw.length === 0) return {};

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new BadRequestError('request body is not valid JSON');
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new BadRequestError('request body must be a JSON object');
  }

  return parsed as Record<string, unknown>;
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
  // HTTP/1.1 requires Host; a request missing it is pathological, and a
  // fabricated fallback would produce a `control` URL that is silently
  // wrong — the one outcome worse than failing loudly, since the whole point
  // of the internal/control split is that the two are never interchangeable.
  const host = req.headers.host;
  if (!host) {
    throw new BadRequestError('request has no Host header');
  }

  const credentialQuery =
    scenario.username === undefined
      ? ''
      : `?username=${encodeURIComponent(scenario.username)}` +
        `&password=${encodeURIComponent(scenario.password ?? '')}`;

  return {
    internal: `${INTERNAL_ORIGIN}/s/${scenario.id}`,
    control: `http://${host}/s/${scenario.id}`,
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
    const body = await readJsonObject(req);
    const scenario = registry.create(body as ScenarioRequest);
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
      if (error instanceof BadRequestError) {
        sendJson(res, 400, { error: error.message });
      } else {
        sendJson(res, 500, { error: String(error) });
      }
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
