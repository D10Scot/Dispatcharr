import { describe, it, expect, afterEach } from 'vitest';
import { startServer } from '../src/server';

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
});
