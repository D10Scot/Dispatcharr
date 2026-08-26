import { describe, it, expect, afterEach, beforeAll } from 'vitest';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { EventEmitter } from 'node:events';
import net from 'node:net';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startServer, requestListener, readJsonObject, scenarioLog, connections } from '../src/server.js';
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

  it('clears a scenario\'s log on delete rather than leaking it forever', async () => {
    server = await startServer(0);
    const created = await readJson(
      await fetch(`http://127.0.0.1:${server.port}/scenarios`, { method: 'POST' })
    );

    await fetch(`http://127.0.0.1:${server.port}/s/${created.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'not-found', active: true }),
    });
    const before = await readJson(
      await fetch(`http://127.0.0.1:${server.port}/s/${created.id}/log`)
    );
    expect(before.length).toBeGreaterThan(0);

    await fetch(`http://127.0.0.1:${server.port}/scenarios/${created.id}`, { method: 'DELETE' });

    // The route now 404s on an unresolved id, like every sibling `/s/<id>/*`
    // route, so it can no longer be used to observe whether the underlying
    // log storage was actually cleared — it stops at "no such scenario"
    // before ever reaching `scenarioLog.entries`. Checking the storage
    // directly is what still proves `clear()` ran rather than merely that
    // the id is gone from the registry.
    expect(scenarioLog.entries(created.id)).toEqual([]);
  });

  it('404s the log route for an unknown scenario id, like every sibling /s/<id>/* route', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/s/nope/log`);
    expect(res.status).toBe(404);
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

  it('does not reject a body delivered slowly across several chunks, as long as no single gap stalls', async () => {
    // Three chunks, each gap under the timeout, totalling well over it. A
    // wall-clock deadline measured from read-start would reject this; the
    // idle timer — reset on every chunk — must not, because nothing ever
    // stalled. This is the case a 5,000-channel scenario body on a loaded
    // CI runner looks like.
    const req = fakeIncomingMessage();
    const promise = readJsonObject(req, { timeoutMs: 30 });

    req.emit('data', Buffer.from('{"user'));
    await new Promise((resolve) => setTimeout(resolve, 20));
    req.emit('data', Buffer.from('name":"a'));
    await new Promise((resolve) => setTimeout(resolve, 20));
    req.emit('data', Buffer.from('lice"}'));
    await new Promise((resolve) => setTimeout(resolve, 20));
    req.emit('end');

    await expect(promise).resolves.toEqual({ username: 'alice' });
  });

  it('rejects a body that starts, then genuinely stalls past the idle timeout', async () => {
    const req = fakeIncomingMessage();
    const promise = readJsonObject(req, { timeoutMs: 20 });

    req.emit('data', Buffer.from('{"username":'));
    // No further data and no 'end' — only the idle timer resetting on the
    // chunk above and then firing on its own can reject this.
    await expect(promise).rejects.toThrow(/stalled/);
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
    // Routed through BadRequestError like every other validated field, with
    // the same wording as the identical check in parseFaultRequest.
    expect(await readJson(bad)).toEqual({ error: "'rate' must be a number greater than 0" });
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

  it('checks credentials on the playlist route: correct 200, wrong 401, absent 401', async () => {
    // The fixture's playlistUrl() appends the same credentialQuery the
    // stream route checks, and a refresh is exactly the request those
    // credentials are meant to gate — this route never checked them at all
    // before, so a G3 "wrong credentials" test would have passed without
    // testing anything.
    server = await startServer(0);
    const scenario = await createScenario({ username: 'alice', password: 'secret' });

    const ok = await fetch(
      `http://127.0.0.1:${server.port}/s/${scenario.id}/playlist.m3u?username=alice&password=secret`
    );
    expect(ok.status).toBe(200);

    const wrong = await fetch(
      `http://127.0.0.1:${server.port}/s/${scenario.id}/playlist.m3u?username=alice&password=wrong`
    );
    expect(wrong.status).toBe(401);

    const absent = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/playlist.m3u`);
    expect(absent.status).toBe(401);
  });

  it('checks credentials on the EPG route: correct 200, wrong 401, absent 401', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ username: 'alice', password: 'secret' });

    const ok = await fetch(
      `http://127.0.0.1:${server.port}/s/${scenario.id}/epg.xml?username=alice&password=secret`
    );
    expect(ok.status).toBe(200);

    const wrong = await fetch(
      `http://127.0.0.1:${server.port}/s/${scenario.id}/epg.xml?username=alice&password=wrong`
    );
    expect(wrong.status).toBe(401);

    const absent = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/epg.xml`);
    expect(absent.status).toBe(401);
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

  it('checks credentials on every hop, including the first, even with redirect-chain armed', async () => {
    // Credential validation runs before redirect-chain on every hop (see
    // the fixed check order in server.ts), so a wrong password 401s at hop
    // 0 and no redirect is ever attempted — "a later hop invalidates
    // credentials" is unreachable by construction and isn't what this
    // verifies.
    server = await startServer(0);
    const scenario = await createScenario({ username: 'alice', password: 'secret' });
    await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault: 'redirect-chain', active: true, depth: 1 }),
    });

    const { res, redirects } = await followChain(
      `/s/${scenario.id}/stream/1.ts?username=alice&password=wrong`
    );
    expect(res.status).toBe(401);
    expect(redirects).toBe(0);
  });
});

describe('the disconnect fault under the real server, using the real streamed asset', () => {
  beforeAll(() => {
    const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-disconnect-asset-'));
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

  async function armFault(scenarioId: string, body: Record<string, unknown>) {
    const res = await fetch(`http://127.0.0.1:${server!.port}/s/${scenarioId}/fault`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    return readJson(res);
  }

  async function armDisconnect(scenarioId: string, body: Record<string, unknown> = {}) {
    return armFault(scenarioId, { fault: 'disconnect', active: true, ...body });
  }

  async function connectionsOf(scenarioId: string) {
    return readJson(await fetch(`http://127.0.0.1:${server!.port}/s/${scenarioId}/connections`));
  }

  async function logOf(scenarioId: string) {
    return readJson(await fetch(`http://127.0.0.1:${server!.port}/s/${scenarioId}/log`));
  }

  it('ends the stream when disconnect is armed while the client is actively reading', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ rate: 50 });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    const reader = res.body!.getReader();
    await reader.read(); // prove it is flowing

    const result = await armDisconnect(scenario.id, { clean: true });
    expect(result.appliedTo).toBe(1);

    // A clean disconnect against a client draining normally ends the
    // response promptly: the reader eventually reports `done`, not a
    // network error — this is the behaviour the backpressure fix below must
    // not disturb.
    let done = false;
    for (let i = 0; i < 200 && !done; i += 1) {
      done = (await reader.read()).done;
    }
    expect(done).toBe(true);

    expect((await connectionsOf(scenario.id)).live).toBe(0);
    expect((await logOf(scenario.id)).some((e: { kind: string }) => e.kind === 'close')).toBe(
      true
    );
  });

  it('ends the stream within a bounded time even when the client has stopped reading', async () => {
    // The regression this guards: disconnect() while the loop was parked in
    // the drain wait used to just set a flag with nothing to act on it —
    // 'drain' never fires because the client isn't reading, and nothing had
    // destroyed the socket. The fault reported appliedTo: 1 while the
    // connection stayed live forever, which is exactly the two-body
    // confusion the log exists to catch, produced by the provider itself.
    server = await startServer(0);
    // A huge rate means near-zero pacing sleep, so writes queue up almost
    // immediately against a client that never reads them.
    const scenario = await createScenario({ rate: 1_000_000 });

    const client = net.connect(server.port, '127.0.0.1');
    await new Promise<void>((resolve) => client.once('connect', resolve));
    client.write(
      `GET /s/${scenario.id}/stream/1.ts HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n`
    );
    // Deliberately never read the response — leaving the socket paused lets
    // the server's write buffer back up quickly at this pacing rate.
    await new Promise((resolve) => setTimeout(resolve, 200));

    const result = await armDisconnect(scenario.id);
    expect(result.appliedTo).toBe(1);

    const deadline = Date.now() + 2000;
    let live = (await connectionsOf(scenario.id)).live;
    while (live > 0 && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
      live = (await connectionsOf(scenario.id)).live;
    }

    expect(live).toBe(0);
    expect((await logOf(scenario.id)).some((e: { kind: string }) => e.kind === 'close')).toBe(
      true
    );

    client.destroy();
  });

  it('ends the stream well inside a slow-trickle chunk sleep, not after it', async () => {
    // The sibling of the backpressure regression above: the same disconnect
    // could also get stuck behind the *pacing* sleep rather than the drain
    // wait. At a slow-trickle rate that sleep is seconds long per chunk, and
    // disconnect() firing while parked in it used to go unnoticed until the
    // sleep elapsed on its own — G5 combining slow-trickle with a disconnect
    // would see the disconnect appear to do nothing for seconds.
    server = await startServer(0);
    const scenario = await createScenario({ rate: 1 });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    const reader = res.body!.getReader();
    await reader.read(); // prove it is flowing

    // This rate turns one chunk's pacing sleep into well over a minute for
    // this tiny asset — comfortably longer than the deadline below, so
    // ending inside it proves the sleep was interrupted, not outrun.
    await armFault(scenario.id, { fault: 'slow-trickle', active: true, rate: 0.01 });
    // The scenario's own rate (1) makes the *current* chunk's sleep ~1.6s;
    // waiting past that — not just a moment — matters: disconnect merely
    // has to wait out an already-scheduled short sleep either way, fixed or
    // not, so arming it too early would pass regardless of this fix. This
    // wait lets the loop actually reach the long, slow-trickle-paced sleep
    // first, so the disconnect below can only land inside *that* one.
    await new Promise((resolve) => setTimeout(resolve, 2500));

    const result = await armDisconnect(scenario.id);
    expect(result.appliedTo).toBe(1);

    const deadline = Date.now() + 3000;
    let live = (await connectionsOf(scenario.id)).live;
    while (live > 0 && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
      live = (await connectionsOf(scenario.id)).live;
    }

    expect(live).toBe(0);
    expect((await logOf(scenario.id)).some((e: { kind: string }) => e.kind === 'close')).toBe(
      true
    );

    await reader.cancel().catch(() => {});
  });

  it('resumes promptly when /rate changes the baseline, not after the old chunk sleep elapses', async () => {
    // POST /rate only ever mutated scenario.rate and touched nothing live —
    // a live connection reads that value back through control.scenarioRate()
    // only at the moment it's about to schedule a new sleep, so a rate
    // change had no way to interrupt a sleep already in flight and just sat
    // unnoticed until that sleep elapsed on its own.
    server = await startServer(0);
    const scenario = await createScenario({ rate: 0.1 });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    const reader = res.body!.getReader();
    await reader.read(); // first chunk, sent immediately regardless of rate

    // This rate makes the *next* chunk's sleep on the order of 15s for this
    // tiny asset — comfortably longer than the deadline below, so the next
    // chunk arriving inside it proves the sleep was interrupted, not outrun.
    await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/rate`, {
      method: 'POST',
      body: JSON.stringify({ rate: 1000 }),
    });

    const outcome = await Promise.race([
      reader.read().then(() => 'arrived' as const),
      new Promise<'timed-out'>((resolve) => setTimeout(() => resolve('timed-out'), 2000)),
    ]);

    expect(outcome).toBe('arrived');
    await reader.cancel().catch(() => {});
  });

  it('ends a live stream and drops the connection when its scenario is deleted', async () => {
    // Before this fix, DELETE never touched ConnectionRegistry: a deleted
    // scenario's clients kept receiving TS indefinitely, and nothing could
    // even observe or drive them afterward, since /connections, /fault and
    // /rate all 404 on the now-gone id — checked directly against the
    // registry here for exactly that reason.
    server = await startServer(0);
    const scenario = await createScenario({ rate: 50 });

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    const reader = res.body!.getReader();
    await reader.read(); // prove it is flowing
    expect(connections.count(scenario.id)).toBe(1);

    const deleted = await fetch(`http://127.0.0.1:${server.port}/scenarios/${scenario.id}`, {
      method: 'DELETE',
    });
    expect(deleted.status).toBe(204);

    // Abrupt, not a clean end-of-stream: the reader should observe an
    // error/reset, or in the worst case just stop — either way it must not
    // keep delivering bytes forever.
    let endedOrErrored = false;
    try {
      let done = false;
      for (let i = 0; i < 200 && !done; i += 1) {
        done = (await reader.read()).done;
      }
      endedOrErrored = done;
    } catch {
      endedOrErrored = true;
    }
    expect(endedOrErrored).toBe(true);

    expect(connections.count(scenario.id)).toBe(0);
  });
});

describe('dead-air and slow-trickle applying to connections opened after they are armed', () => {
  // Both faults are documented as applying to "live + new" connections.
  // `FaultStore.apply` only reaches connections that are already open at
  // the instant it runs; without a second entry point at connect time, a
  // fault armed first and connected to second does nothing — the
  // regression these two tests exist to pin. Assertions are on observed
  // bytes/timing, not on `appliedTo`, since `appliedTo` is legitimately 0
  // in both the correct and the broken case (there's no live connection to
  // reach yet).
  beforeAll(() => {
    const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-prearm-asset-'));
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

  async function armFault(scenarioId: string, body: Record<string, unknown>) {
    const res = await fetch(`http://127.0.0.1:${server!.port}/s/${scenarioId}/fault`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    return readJson(res);
  }

  it('applies a pre-armed dead-air fault to a connection opened after it', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ rate: 50 });

    // No live connections exist yet, so appliedTo: 0 here is correct — this
    // is exactly the case a warning on it would have wrongly flagged.
    const armed = await armFault(scenario.id, { fault: 'dead-air', active: true });
    expect(armed.appliedTo).toBe(0);

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    const reader = res.body!.getReader();

    // The asset's whole loop fits in one chunk, so a healthy connection at
    // any rate writes it synchronously on the very first read — a stall on
    // this very first read is only possible if dead-air took effect from
    // the start.
    const outcome = await Promise.race([
      reader.read().then(() => 'read' as const),
      new Promise<'silent'>((resolve) => setTimeout(() => resolve('silent'), 500)),
    ]);
    await reader.cancel().catch(() => {});

    expect(outcome).toBe('silent');
  });

  it('applies a pre-armed slow-trickle fault to a connection opened after it', async () => {
    server = await startServer(0);
    const scenario = await createScenario({ rate: 50 });

    const armed = await armFault(scenario.id, { fault: 'slow-trickle', active: true, rate: 0.01 });
    expect(armed.appliedTo).toBe(0);

    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
    const reader = res.body!.getReader();

    await reader.read(); // the first chunk writes synchronously regardless of rate

    // At the scenario's own rate (50x) the next chunk's pacing sleep is a
    // few milliseconds; at the pre-armed slow-trickle rate (0.01x) it's
    // minutes. Stalling well past the scenario's own rate, but nowhere near
    // slow-trickle's, is only possible if the new connection actually
    // started at the armed rate instead of the scenario's fast one.
    const outcome = await Promise.race([
      reader.read().then(() => 'read' as const),
      new Promise<'stalled'>((resolve) => setTimeout(() => resolve('stalled'), 500)),
    ]);
    await reader.cancel().catch(() => {});

    expect(outcome).toBe('stalled');
  });
});
