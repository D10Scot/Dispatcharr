import { describe, it, expect, afterEach, beforeAll } from 'vitest';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startServer } from '../src/server.js';
import { makeSyntheticTs } from './helpers/synthetic-ts.js';

// Node's fetch typings return `Promise<unknown>` from `Response.json()`; see
// the identical helper in test/server.test.ts and test/xc-router.test.ts.
async function readJson(res: Response): Promise<any> {
  return res.json();
}

// The catch-up tests below serve a real channel loop through
// serveChannelStream, which needs a loadable UPSTREAM_ASSET — same pattern
// as test/xc-router.test.ts's "XC live playback" block. Loaded once, module
// scope: getAsset() in server.ts caches on first read and never re-reads.
beforeAll(() => {
  const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-asset-'));
  const path = join(dir, 'loop.ts');
  writeFileSync(path, makeSyntheticTs({ packets: 40, pid: 0x0100, step: 3600n }));
  process.env.UPSTREAM_ASSET = path;
});

let server: Awaited<ReturnType<typeof startServer>> | undefined;
afterEach(async () => {
  await server?.close();
  server = undefined;
  // Same reset as test/xc-router.test.ts's "XC VOD" blocks: the
  // 'range-unsupported' block below points this at a fresh temp file, and
  // leaving it set would leak into whichever test runs after this file.
  delete process.env.UPSTREAM_VOD_ASSET;
});

// Copied from test/xc-router.test.ts rather than exported from it, per the
// brief: each test file stands alone.
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

// Same synthetic-asset helper as test/xc-router.test.ts's "XC VOD playback"
// block, copied for the same stand-alone-file reason as xcScenario above.
function syntheticVodAsset(): string {
  const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-vod-'));
  const path = join(dir, 'vod.mp4');
  writeFileSync(path, Buffer.from(Array.from({ length: 1000 }, (_u, i) => i % 251)));
  return path;
}

const auth = '?username=user&password=pass';

/** POSTs to `/s/<id>/fault`, the one control route every fault goes through. */
async function arm(base: string, id: string, body: Record<string, unknown>): Promise<Response> {
  return fetch(`${base}/s/${id}/fault`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

describe('xc-auth-envelope', () => {
  it('answers 200 with auth 0 rather than 401', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'xc-auth-envelope', active: true });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}`);
    // 200, deliberately. Client.authenticate() checks only that user_info is
    // truthy, so this is the shape the product mistakes for a successful
    // login — which is the whole point of the fault.
    expect(res.status).toBe(200);
    const body = await readJson(res);
    expect(body.user_info.auth).toBe(0);
    expect(body.user_info.status).toBe('Disabled');
  });

  it('wins over a scenario.account.userInfo override that also sets auth/status', async () => {
    // renderAccountEnvelope spreads scenario.account.userInfo last, so a
    // scenario declaring its own `auth`/`status` could otherwise silently
    // defeat the fault — see renderDisabledAccountEnvelope's precedence
    // comment. This scenario sets both to the opposite of what the fault
    // asserts, so the test only passes if the fault's own override runs
    // strictly after the scenario's.
    const { base, id } = await xcScenario({
      account: { userInfo: { auth: 1, status: 'Active' } },
    });
    await arm(base, id, { fault: 'xc-auth-envelope', active: true });
    const body = await readJson(await fetch(`${base}/s/${id}/player_api.php${auth}`));
    expect(body.user_info.auth).toBe(0);
    expect(body.user_info.status).toBe('Disabled');
  });

  it('clears back to a normal envelope', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'xc-auth-envelope', active: true });
    await arm(base, id, { fault: 'xc-auth-envelope', active: false });
    const body = await readJson(await fetch(`${base}/s/${id}/player_api.php${auth}`));
    expect(body.user_info.auth).toBe(1);
    expect(body.user_info.status).toBe('Active');
  });

  it('400s a channel filter over the wire, naming the field (fix round 1)', async () => {
    // xc-auth-envelope has no channel to narrow to — arming it with one
    // would previously store under that channel's scope, which the router
    // never reads, and come back 200/appliedTo:0: byte-identical to a
    // correctly armed fault that just hasn't reached a live connection yet.
    // Proven at the actual /fault route, not just parseFaultRequest, since
    // this is the door a real test author calls through.
    const { base, id } = await xcScenario();
    const res = await arm(base, id, { fault: 'xc-auth-envelope', active: true, channel: 1 });
    expect(res.status).toBe(400);
    expect((await readJson(res)).error).toMatch(/channel/);
  });
});

describe('auth-failure on the XC surface', () => {
  it('401s player_api.php', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'auth-failure', active: true });
    expect((await fetch(`${base}/s/${id}/player_api.php${auth}`)).status).toBe(401);
  });

  it('clears back to the normal 200', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'auth-failure', active: true });
    await arm(base, id, { fault: 'auth-failure', active: false });
    expect((await fetch(`${base}/s/${id}/player_api.php${auth}`)).status).toBe(200);
  });
});

describe('no-tv-archive', () => {
  it('omits tv_archive from get_live_streams', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'no-tv-archive', active: true });
    const [stream] = await readJson(
      await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams`)
    );
    expect(stream).not.toHaveProperty('tv_archive');
  });

  it('scopes to one channel when a channel filter is given', async () => {
    const { base, id } = await xcScenario({ channels: 2 });
    await arm(base, id, { fault: 'no-tv-archive', active: true, channel: 2 });
    const streams = await readJson(
      await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams`)
    );
    expect(streams[0]).toHaveProperty('tv_archive');
    expect(streams[1]).not.toHaveProperty('tv_archive');
  });

  it('clears back to advertising tv_archive', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'no-tv-archive', active: true });
    await arm(base, id, { fault: 'no-tv-archive', active: false });
    const [stream] = await readJson(
      await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams`)
    );
    expect(stream).toHaveProperty('tv_archive');
  });
});

describe('catchup-layout-404', () => {
  it('404s only the named layout', async () => {
    const { base, id } = await xcScenario();
    const start = '2026-08-29:14-00';
    await arm(base, id, { fault: 'catchup-layout-404', active: true, layout: 'path' });

    expect((await fetch(`${base}/s/${id}/timeshift/user/pass/65/${start}/1.ts`)).status).toBe(404);

    const query = `username=user&password=pass&stream=1&start=${encodeURIComponent(start)}&duration=65`;
    const ok = await fetch(`${base}/s/${id}/streaming/timeshift.php?${query}`);
    expect(ok.status).toBe(200);
    await ok.body!.cancel();
  });

  it('clears without a layout, restoring both', async () => {
    // The controller's ruling: clearFault(scenario, 'catchup-layout-404')
    // sends no `layout`. If the validator required one here it would 400,
    // and this fault could be armed but never cleared through the normal
    // clearFault call shape.
    const { base, id } = await xcScenario();
    const start = '2026-08-29:14-00';
    await arm(base, id, { fault: 'catchup-layout-404', active: true, layout: 'path' });
    expect((await fetch(`${base}/s/${id}/timeshift/user/pass/65/${start}/1.ts`)).status).toBe(404);

    const clearRes = await arm(base, id, { fault: 'catchup-layout-404', active: false });
    expect(clearRes.status).toBe(200);

    const restored = await fetch(`${base}/s/${id}/timeshift/user/pass/65/${start}/1.ts`);
    expect(restored.status).toBe(200);
    await restored.body!.cancel();
  });
});

describe('range-unsupported', () => {
  it('answers 200 with the whole body and no Accept-Ranges', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'range-unsupported', active: true });
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`, {
      headers: { Range: 'bytes=100-199' },
    });
    expect(res.status).toBe(200);
    expect(res.headers.get('accept-ranges')).toBeNull();
    expect((await res.arrayBuffer()).byteLength).toBe(1000);
  });

  it('clears back to honouring Range', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'range-unsupported', active: true });
    await arm(base, id, { fault: 'range-unsupported', active: false });
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`, {
      headers: { Range: 'bytes=100-199' },
    });
    expect(res.status).toBe(206);
    expect(res.headers.get('accept-ranges')).toBe('bytes');
  });

  it('400s a channel filter over the wire, naming the field (fix round 1)', async () => {
    // A VOD id is not a channel id — same door check as xc-auth-envelope
    // above, and the same silent-no-op this closes: without it, `{ channel:
    // 1 }` would validate and store under a scope the router never reads
    // for this fault.
    const { base, id } = await xcScenario();
    const res = await arm(base, id, { fault: 'range-unsupported', active: true, channel: 1 });
    expect(res.status).toBe(400);
    expect((await readJson(res)).error).toMatch(/channel/);
  });
});

describe('not-found and auth-failure on the VOD playback routes', () => {
  // Default xcScenario() already declares exactly one movie (id 1) and one
  // series with one season and one episode (id 1) — see defaultMovies and
  // defaultSeries in scenario.ts — so no overrides are needed to get "one
  // movie and one series with one episode".

  it('404s /movie/ with the fault body when armed scenario-wide', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'not-found', active: true });
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`);
    expect(res.status).toBe(404);
    expect(await readJson(res)).toEqual({ error: 'fault: not-found' });
    const log = (await readJson(await fetch(`${base}/s/${id}/log`))) as Record<string, unknown>[];
    expect(log).toContainEqual(expect.objectContaining({ kind: 'request', status: 404 }));
  });

  it('404s /series/ with the fault body when armed scenario-wide', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'not-found', active: true });
    const res = await fetch(`${base}/s/${id}/series/user/pass/1.mp4`);
    expect(res.status).toBe(404);
    expect(await readJson(res)).toEqual({ error: 'fault: not-found' });
  });

  it('401s /movie/ with the fault body when auth-failure is armed, even with correct credentials', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'auth-failure', active: true });
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`);
    expect(res.status).toBe(401);
    expect(await readJson(res)).toEqual({ error: 'fault: auth-failure' });
  });

  it('a channel-scoped not-found is invisible to /movie/, which still 200s', async () => {
    // not-found (unlike xc-auth-envelope/range-unsupported) is not in
    // SCENARIO_WIDE_ONLY_FAULTS, so `{ channel: 1 }` validates and stores
    // under scope 1 — but the VOD route's isActive check passes no channel,
    // so it only ever reads scope '*' and never sees this entry. Asserted
    // explicitly rather than left implicit: it's the one surprising
    // consequence of the scoping, and a test author arming it this way
    // would otherwise see a silent no-op.
    //
    // The arm's own response is asserted first (fix round 1, F1): without
    // it, a world where `not-found` gets added to SCENARIO_WIDE_ONLY_FAULTS
    // — so `{ channel: 1 }` is rejected with a 400, same as the
    // range-unsupported case above — would leave nothing armed at all, and
    // /movie/ would 200 for a completely different reason. A bare 200 from
    // /movie/ can't tell "stored under a scope the check ignores" apart
    // from "never stored". Asserting 200 here (not 400) is what pins the
    // former.
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    const armRes = await arm(base, id, { fault: 'not-found', active: true, channel: 1 });
    expect(armRes.status).toBe(200);
    expect(await readJson(armRes)).toEqual({ fault: 'not-found', active: true, appliedTo: 0 });

    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`);
    expect(res.status).toBe(200);
    expect((await res.arrayBuffer()).byteLength).toBe(1000);
  });
});

