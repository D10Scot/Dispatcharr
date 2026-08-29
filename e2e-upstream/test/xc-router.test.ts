import { describe, it, expect, afterEach } from 'vitest';
import { startServer, registry } from '../src/server.js';

// Node's fetch typings return `Promise<unknown>` from `Response.json()`; see
// the identical helper in test/server.test.ts.
async function readJson(res: Response): Promise<any> {
  return res.json();
}

let server: Awaited<ReturnType<typeof startServer>> | undefined;
afterEach(async () => {
  await server?.close();
  server = undefined;
});

async function xcScenario(overrides: Record<string, unknown> = {}) {
  server = await startServer(0);
  const base = `http://127.0.0.1:${server.port}`;
  const created = await readJson(
    await fetch(`${base}/scenarios`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ xc: true, username: 'user', password: 'pass', ...overrides }),
    })
  );
  return { base, id: created.id as string };
}

const auth = '?username=user&password=pass';

describe('the XC route seam', () => {
  it('answers player_api.php with an authentication envelope', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('application/json');
    const body = await readJson(res);
    expect(body.user_info.auth).toBe(1);
  });

  it('rejects wrong credentials with 401', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php?username=user&password=wrong`);
    expect(res.status).toBe(401);
  });

  it('404s an XC route on a non-XC scenario, naming the missing opt-in', async () => {
    server = await startServer(0);
    const base = `http://127.0.0.1:${server.port}`;
    const created = await readJson(
      await fetch(`${base}/scenarios`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    );
    const res = await fetch(`${base}/s/${created.id}/player_api.php`);
    expect(res.status).toBe(404);
    // Naming the mistake, not just refusing: a bare 404 here is
    // indistinguishable from the `not-found` fault or a typo'd scenario id.
    expect((await readJson(res)).error).toMatch(/xc: true/);
  });

  it('leaves the pre-existing control and provider routes untouched', async () => {
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/connections`)).status).toBe(200);
    expect((await fetch(`${base}/s/${id}/log`)).status).toBe(200);
    expect((await fetch(`${base}/s/${id}/playlist.m3u${auth}`)).status).toBe(200);
    // The seam must sit after every existing branch: reached earlier, it would
    // swallow /fault, /rate, /log and /connections.
    const fault = await fetch(`${base}/s/${id}/fault`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fault: 'dead-air', active: true }),
    });
    expect(fault.status).toBe(200);
  });

  it('still 404s an unknown sub-path with a message naming it', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/nonsense`);
    expect(res.status).toBe(404);
    expect((await readJson(res)).error).toContain('/nonsense');
  });

  it('records every XC request in the scenario log, query string included', async () => {
    const { base, id } = await xcScenario();
    await fetch(`${base}/s/${id}/player_api.php${auth}`);
    const log = await (await fetch(`${base}/s/${id}/log`)).json();
    // The logged path carries the search string, not just the pathname —
    // Task 6 and Task 11 both assert on parameters like `stream=1` and
    // `username=...` inside a logged path, and this is the one place that
    // shape is produced.
    expect(log).toContainEqual(
      expect.objectContaining({
        kind: 'request',
        method: 'GET',
        status: 200,
        path: `/s/${id}/player_api.php${auth}`,
      })
    );
  });
});

describe('catalogue action dispatch', () => {
  it('passes category_id through get_live_streams to the renderer', async () => {
    const { base, id } = await xcScenario({
      liveCategories: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }],
      channels: [
        { id: 1, name: 'one', tvgId: 'one.e2e', logo: null, categoryId: 1 },
        { id: 2, name: 'two', tvgId: 'two.e2e', logo: null, categoryId: 2 },
      ],
    });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams&category_id=2`);
    expect(res.status).toBe(200);
    const streams = (await readJson(res)) as Record<string, unknown>[];
    expect(streams).toHaveLength(1);
    expect(streams[0].stream_id).toBe(2);
  });

  it('404s get_vod_info for an unknown vod_id, with a JSON body naming the field', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_vod_info&vod_id=999`);
    expect(res.status).toBe(404);
    expect(res.headers.get('content-type')).toContain('application/json');
    expect((await readJson(res)).error).toMatch(/vod_id/);
  });

  it('404s get_vod_info rather than matching an id-0 movie when vod_id is omitted', async () => {
    // Number(null) === 0 would otherwise let a request with no vod_id at
    // all match a scenario's id-0 movie.
    const { base, id } = await xcScenario({
      vod: [{ id: 0, name: 'Zero', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null }],
    });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_vod_info`);
    expect(res.status).toBe(404);
  });

  it('404s get_series_info for an unknown series_id, with a JSON body naming the field', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_series_info&series_id=999`);
    expect(res.status).toBe(404);
    expect((await readJson(res)).error).toMatch(/series_id/);
  });

  it('400s an unrecognised action, naming the valid action set', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=nonsense`);
    expect(res.status).toBe(400);
    const body = await readJson(res);
    expect(body.error).toContain('get_live_categories');
    expect(body.error).toContain('nonsense');
  });

  it('400s rather than 500s an Object.prototype member used as the action', async () => {
    // A bracket lookup on a plain object resolves Object.prototype members
    // (valueOf, hasOwnProperty, toString, constructor, ...). Before the fix,
    // ?action=valueOf threw when the resolved function was invoked with no
    // receiver, which server.ts turned into an opaque 500 carrying a
    // stringified TypeError — exactly what the validate-at-the-door ruling
    // forbids.
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=valueOf`);
    expect(res.status).toBe(400);
    expect((await readJson(res)).error).toContain('valueOf');
  });

  it('logs the status actually sent for both a successful and a rejected action', async () => {
    const { base, id } = await xcScenario();
    const ok = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_categories`);
    expect(ok.status).toBe(200);
    const rejected = await fetch(`${base}/s/${id}/player_api.php${auth}&action=nonsense`);
    expect(rejected.status).toBe(400);

    const log = (await (await fetch(`${base}/s/${id}/log`)).json()) as Record<string, unknown>[];
    // Guards the ordering fix: log() must run after the response status is
    // decided, not before, so a log entry can never claim a status that
    // differs from what the client actually received.
    expect(log).toContainEqual(
      expect.objectContaining({ kind: 'request', status: 200, path: expect.stringContaining('get_live_categories') })
    );
    expect(log).toContainEqual(
      expect.objectContaining({ kind: 'request', status: 400, path: expect.stringContaining('action=nonsense') })
    );
  });
});
