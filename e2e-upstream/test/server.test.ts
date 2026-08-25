import { describe, it, expect, afterEach } from 'vitest';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { startServer, requestListener } from '../src/server.js';

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
