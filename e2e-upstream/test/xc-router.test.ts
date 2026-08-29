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
