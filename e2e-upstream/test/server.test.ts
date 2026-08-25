import { describe, it, expect, afterEach, beforeAll } from 'vitest';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { EventEmitter } from 'node:events';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startServer, requestListener, readJsonObject } from '../src/server.js';
import { BadRequestError } from '../src/errors.js';
import { makeSyntheticTs } from './helpers/synthetic-ts.js';

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
    // The `&` is load-bearing: @ and space alone would still parse back
    // correctly through URLSearchParams even with no encoding at all, so
    // this test is non-vacuous only because `&` is a query-string separator
    // and would silently truncate the password if left unencoded.
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

describe('request body limits', () => {
  // Exercised directly against readJsonObject with tiny overrides rather
  // than a real 1 MB/10 s HTTP request: the behaviour under test is the cap
  // and timeout logic itself, and driving it through a fake EventEmitter
  // proves that without actually waiting 10 real seconds or allocating a
  // real 1 MB buffer for every test run.
  function fakeIncomingMessage(): IncomingMessage {
    // A real `stream.destroy()` called with no argument (as readRawBody
    // does — it reports the failure itself via `finish`) does not emit
    // 'error'; it only emits 'close'. A no-op destroy matches that.
    const emitter = new EventEmitter() as unknown as IncomingMessage;
    (emitter as { destroy: () => IncomingMessage }).destroy = () => emitter;
    return emitter;
  }

  it('rejects a body larger than the configured cap, naming the limit', async () => {
    const req = fakeIncomingMessage();
    const promise = readJsonObject(req, { maxBytes: 4 });
    req.emit('data', Buffer.from('{"channels":10}'));

    await expect(promise).rejects.toThrow(BadRequestError);
    await expect(promise).rejects.toThrow(/4 bytes/);
  });

  it('rejects a body that never finishes within the configured timeout', async () => {
    const req = fakeIncomingMessage();
    await expect(readJsonObject(req, { timeoutMs: 20 })).rejects.toThrow(/20ms/);
  });

  it('enforces the cap end to end over a real socket on POST /scenarios', async () => {
    server = await startServer(0);
    const oversized = JSON.stringify({ username: 'x'.repeat(1024 * 1024 + 1) });
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`, {
      method: 'POST',
      body: oversized,
    });
    expect(res.status).toBe(400);
    expect(await readJson(res)).toMatchObject({ error: expect.stringContaining('bytes') });
  });
});

describe('fault and rate control routes', () => {
  async function createScenario(body: Record<string, unknown> = {}) {
    const res = await fetch(`http://127.0.0.1:${server!.port}/scenarios`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    return readJson(res);
  }

  it('404s a fault request for an unknown scenario', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/s/nope/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'dead-air', active: true }),
    });
    expect(res.status).toBe(404);
  });

  it('400s an unknown fault name, listing the valid set', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'dead-ait', active: true }),
    });
    expect(res.status).toBe(400);
    expect(await readJson(res)).toMatchObject({ error: expect.stringContaining('dead-air') });
  });

  it('arms a new-request-only fault and reports appliedTo 0 with no live connections', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'not-found', active: true }),
    });
    expect(res.status).toBe(200);
    expect(await readJson(res)).toEqual({ fault: 'not-found', active: true, appliedTo: 0 });
  });

  it('updates the scenario rate and rejects a non-positive one', async () => {
    server = await startServer(0);
    const scenario = await createScenario();

    const ok = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/rate`, {
      method: 'POST',
      body: JSON.stringify({ rate: 3 }),
    });
    expect(ok.status).toBe(200);
    expect(await readJson(ok)).toEqual({ rate: 3 });

    const bad = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/rate`, {
      method: 'POST',
      body: JSON.stringify({ rate: 0 }),
    });
    expect(bad.status).toBe(400);
  });

  it('404s a rate request for an unknown scenario', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/s/nope/rate`, {
      method: 'POST',
      body: JSON.stringify({ rate: 2 }),
    });
    expect(res.status).toBe(404);
  });
});

describe('faults on the stream, playlist and EPG routes', () => {
  async function createScenario(body: Record<string, unknown> = {}) {
    const res = await fetch(`http://127.0.0.1:${server!.port}/scenarios`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    return readJson(res);
  }

  async function armFault(scenarioId: string, body: Record<string, unknown>) {
    await fetch(`http://127.0.0.1:${server!.port}/s/${scenarioId}/fault`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  it('404s the stream route when not-found is armed, without leaking the connection slot', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ maxConnections: 1 });
    await armFault(scenario.id, { fault: 'not-found', active: true });

    const first = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(first.status).toBe(404);
    expect(await readJson(first)).toMatchObject({ error: 'fault: not-found' });

    // If the rejected request above had consumed the scenario's one
    // connection slot, this would come back 429 instead — the leak this
    // fault-before-tryAcquire ordering exists to prevent.
    const second = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(second.status).toBe(404);
  });

  it('401s the stream route when auth-failure is armed', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await armFault(scenario.id, { fault: 'auth-failure', active: true });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(res.status).toBe(401);
  });

  it('lets not-found win when it and auth-failure are both armed, per the fixed check order', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await armFault(scenario.id, { fault: 'auth-failure', active: true });
    await armFault(scenario.id, { fault: 'not-found', active: true });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(res.status).toBe(404);
  });

  it('lets auth-failure win when it and connection-limit are both armed', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await armFault(scenario.id, { fault: 'auth-failure', active: true });
    await armFault(scenario.id, { fault: 'connection-limit', active: true });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(res.status).toBe(401);
  });

  it('429s the stream route when connection-limit is armed as a fault, regardless of the real count', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await armFault(scenario.id, { fault: 'connection-limit', active: true });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(res.status).toBe(429);
  });

  it('serves an HTML error body with a 200 when non-ts-bytes is armed', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await armFault(scenario.id, { fault: 'non-ts-bytes', active: true });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('text/html');
    expect(await res.text()).toContain('502');
  });

  it('scopes a fault to the named channel, leaving the other channel unaffected', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ channels: 2 });
    await armFault(scenario.id, { fault: 'not-found', active: true, channel: 1 });

    const targeted = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    expect(targeted.status).toBe(404);

    const other = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/2.ts`, {
      method: 'HEAD',
    });
    expect(other.status).toBe(200);
  });

  it('a HEAD probe also 404s when not-found is armed, matching a real dead URL', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await armFault(scenario.id, { fault: 'not-found', active: true });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`, {
      method: 'HEAD',
    });
    expect(res.status).toBe(404);
  });

  it('404s the playlist and EPG routes when a scenario-wide not-found is armed', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await armFault(scenario.id, { fault: 'not-found', active: true });

    const playlist = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/playlist.m3u`);
    expect(playlist.status).toBe(404);

    const epg = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/epg.xml`);
    expect(epg.status).toBe(404);
  });

  it('leaves the playlist and EPG routes unaffected by a fault armed for one channel only', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ channels: 2 });
    await armFault(scenario.id, { fault: 'not-found', active: true, channel: 1 });

    const playlist = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/playlist.m3u`);
    expect(playlist.status).toBe(200);
  });
});

describe('the redirect-chain fault, using the real streamed asset', () => {
  // Only this block needs a real, loadable asset: every other fault check
  // in the stream route runs (and returns) before getAsset() is ever
  // called. This is the one fault whose contract — the chain must terminate
  // on a URL that actually serves the payload — can't be verified without
  // letting a client follow it all the way to real bytes.
  beforeAll(() => {
    const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-asset-'));
    const path = join(dir, 'loop.ts');
    writeFileSync(path, makeSyntheticTs({ packets: 40, pid: 0x0100, step: 3600n }));
    process.env.UPSTREAM_ASSET = path;
  });

  async function createScenario(body: Record<string, unknown> = {}) {
    const res = await fetch(`http://127.0.0.1:${server!.port}/scenarios`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    return readJson(res);
  }

  // The Location header points at the internal origin — what Dispatcharr,
  // running inside the Docker network, would resolve (`e2e-upstream:8080`
  // by default; see INTERNAL_ORIGIN in server.ts). This test process isn't
  // on that network, so it follows each hop manually, keeping only the path
  // and query from Location and re-issuing the request against this test
  // server's real loopback address — the property under test is that the
  // path/query construction is correct and terminates on real content, not
  // that the hostname happens to be resolvable from here.
  async function followChain(pathAndQuery: string): Promise<{ res: Response; redirects: number }> {
    let redirects = 0;
    let current = pathAndQuery;
    for (;;) {
      const res = await fetch(`http://127.0.0.1:${server!.port}${current}`, { redirect: 'manual' });
      if (res.status !== 302) return { res, redirects };
      redirects += 1;
      const location = new URL(res.headers.get('location')!);
      current = location.pathname + location.search;
    }
  }

  it('redirects the configured depth, then serves real TS bytes on the final hop', async () => {
    server = await startServer(0);
    const scenario = await createScenario();
    await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'redirect-chain', active: true, depth: 2 }),
    });

    const { res, redirects } = await followChain(`/s/${scenario.id}/stream/1.ts`);
    expect(redirects).toBe(2);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('video/mp2t');

    const reader = res.body!.getReader();
    const first = await reader.read();
    await reader.cancel();
    expect(first.value![0]).toBe(0x47);
  });

  it('carries the credential query through every redirect hop', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ username: 'alice', password: 'secret' });
    await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'redirect-chain', active: true, depth: 2 }),
    });

    const { res } = await followChain(
      `/s/${scenario.id}/stream/1.ts?username=alice&password=secret`
    );
    expect(res.status).toBe(200);
    const reader = res.body!.getReader();
    await reader.cancel();
  });

  it('rejects credentials that changed mid-chain, even after the first hop validated them', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ username: 'alice', password: 'secret' });
    await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'redirect-chain', active: true, depth: 1 }),
    });

    const { res } = await followChain(
      `/s/${scenario.id}/stream/1.ts?username=alice&password=wrong`
    );
    expect(res.status).toBe(401);
  });
});
