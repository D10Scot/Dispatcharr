import { describe, it, expect, afterEach } from 'vitest';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { startServer, requestListener } from '../src/server.js';

// Node's fetch typings return `Promise<unknown>` from `Response.json()`; the
// scenario routes tests below read known response shapes off it, so this
// narrows once instead of casting at every call site.
async function readJson(res: Response): Promise<any> {
  return res.json();
}

let server: Awaited<ReturnType<typeof startServer>> | undefined;

afterEach(async () => {
  await server?.close();
  server = undefined;
});

describe('server', () => {
  it('answers GET /scenarios with an empty list', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([]);
  });

  it('answers an unknown path with 404 and a JSON body naming the path', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/nope`);
    expect(res.status).toBe(404);
    // A bare 404 is indistinguishable from the `not-found` fault. Naming the
    // path is what tells a test author "you asked for the wrong URL" rather
    // than "the fault fired".
    expect(await res.json()).toMatchObject({
      error: expect.stringContaining('/nope'),
    });
  });

  it('answers a handler failure with 500 and a JSON body', async () => {
    // `requestListener` is the exported catch wrapper around `handle()`; a
    // `url` getter that throws stands in for any failure inside `handle()`
    // itself, without needing a real malformed request to provoke one.
    const req = { method: 'GET' } as unknown as IncomingMessage;
    Object.defineProperty(req, 'url', {
      get() {
        throw new Error('boom');
      },
    });

    let status = 0;
    let body = '';
    const res = {
      headersSent: false,
      writeHead(code: number) {
        status = code;
      },
      end(payload: string) {
        body = payload;
      },
    } as unknown as ServerResponse;

    await requestListener(req, res);

    expect(status).toBe(500);
    expect(JSON.parse(body)).toMatchObject({
      error: expect.stringContaining('boom'),
    });
  });
});

describe('scenario routes', () => {
  it('creates a default scenario from an empty POST body', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`, { method: 'POST' });
    expect(res.status).toBe(201);
    const body = await readJson(res);
    expect(body.channels).toHaveLength(1);
    expect(body.maxConnections).toBeNull();
    expect(body.rate).toBe(1);
  });

  it('carries maxConnections 0 through the HTTP round trip, not just the registry', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`, {
      method: 'POST',
      body: JSON.stringify({ maxConnections: 0 }),
    });
    expect(res.status).toBe(201);
    const body = await readJson(res);
    expect(body.maxConnections).toBe(0);
  });

  it('rejects malformed JSON with 400', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`, {
      method: 'POST',
      body: 'not json',
    });
    expect(res.status).toBe(400);
    expect(await readJson(res)).toMatchObject({ error: expect.any(String) });
  });

  it('rejects a JSON array body with 400 instead of silently treating it as {}', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`, {
      method: 'POST',
      body: JSON.stringify([]),
    });
    expect(res.status).toBe(400);
    expect(await readJson(res)).toMatchObject({ error: expect.any(String) });
  });

  it('round-trips a username and password containing @, space and & through credentialQuery', async () => {
    server = await startServer(0);
    const username = 'user@host name';
    const password = 'p&ss w0rd';
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`, {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    const body = await readJson(res);
    const parsed = new URLSearchParams(body.credentialQuery);
    expect(parsed.get('username')).toBe(username);
    expect(parsed.get('password')).toBe(password);
  });

  it('lists created scenarios with internal and control on distinct origins', async () => {
    server = await startServer(0);
    await fetch(`http://127.0.0.1:${server.port}/scenarios`, { method: 'POST' });

    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`);
    expect(res.status).toBe(200);
    const [scenario] = await readJson(res);
    expect(scenario.internal.startsWith('http://e2e-upstream:8080/')).toBe(true);
    expect(scenario.control.startsWith(`http://127.0.0.1:${server.port}/`)).toBe(true);
  });

  it('deletes a scenario, then reports 404 on a second delete of the same id', async () => {
    server = await startServer(0);
    const created = await readJson(
      await fetch(`http://127.0.0.1:${server.port}/scenarios`, { method: 'POST' })
    );

    const first = await fetch(`http://127.0.0.1:${server.port}/scenarios/${created.id}`, {
      method: 'DELETE',
    });
    expect(first.status).toBe(204);

    const second = await fetch(`http://127.0.0.1:${server.port}/scenarios/${created.id}`, {
      method: 'DELETE',
    });
    expect(second.status).toBe(404);
  });
});
