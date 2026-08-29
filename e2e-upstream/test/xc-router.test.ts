import { describe, it, expect, afterEach, beforeAll } from 'vitest';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startServer, registry } from '../src/server.js';
import { makeSyntheticTs } from './helpers/synthetic-ts.js';

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

  it('400s get_live_streams for a category_id naming no declared live category', async () => {
    // Unlike vod_id/series_id, an unknown category_id fails quietly (200
    // []) — the exact symptom of a real product bug, not a scenario
    // mistake — so it gets a 400 rather than the 404 those two use.
    const { base, id } = await xcScenario({ liveCategories: [{ id: 1, name: 'A' }] });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams&category_id=999`);
    expect(res.status).toBe(400);
    const body = await readJson(res);
    expect(body.error).toMatch(/category_id/);
    expect(body.error).toContain('999');
    expect(body.error).toContain('1');
  });

  it('400s get_vod_streams for a category_id naming no declared VOD category', async () => {
    const { base, id } = await xcScenario({ vodCategories: [{ id: 1, name: 'A' }] });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_vod_streams&category_id=999`);
    expect(res.status).toBe(400);
    expect((await readJson(res)).error).toMatch(/category_id/);
  });

  it('400s get_series for a category_id naming no declared series category', async () => {
    const { base, id } = await xcScenario({ seriesCategories: [{ id: 1, name: 'A' }] });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_series&category_id=999`);
    expect(res.status).toBe(400);
    expect((await readJson(res)).error).toMatch(/category_id/);
  });

  it('still 200s an empty list for a category_id that names a real, empty category', async () => {
    // A known category with nothing in it is a legitimate 200 [], not a
    // scenario mistake — only an *unknown* category_id gets the 400 above.
    const { base, id } = await xcScenario({
      liveCategories: [{ id: 1, name: 'A' }, { id: 2, name: 'Empty' }],
      channels: [{ id: 1, name: 'one', tvgId: 'one.e2e', logo: null, categoryId: 1 }],
    });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams&category_id=2`);
    expect(res.status).toBe(200);
    expect(await readJson(res)).toEqual([]);
  });

  it('does not validate category_id for the category-listing actions, which ignore it', async () => {
    const { base, id } = await xcScenario({ liveCategories: [{ id: 1, name: 'A' }] });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_categories&category_id=999`);
    expect(res.status).toBe(200);
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

describe('XC live playback', () => {
  // Only the GET test below actually reads streamed bytes and needs a real,
  // loadable asset — same pattern as `test/server.test.ts`'s
  // "the redirect-chain fault, using the real streamed asset" block.
  beforeAll(() => {
    const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-asset-'));
    const path = join(dir, 'loop.ts');
    writeFileSync(path, makeSyntheticTs({ packets: 40, pid: 0x0100, step: 3600n }));
    process.env.UPSTREAM_ASSET = path;
  });

  it('serves TS on /live/<user>/<pass>/<id>.ts', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/live/user/pass/1.ts`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('video/mp2t');
    const reader = res.body!.getReader();
    const { value } = await reader.read();
    expect(value![0]).toBe(0x47);
    await reader.cancel();
  });

  it('rejects wrong path credentials with 401 and consumes no connection slot', async () => {
    const { base, id } = await xcScenario({ maxConnections: 1 });
    expect((await fetch(`${base}/s/${id}/live/user/wrong/1.ts`)).status).toBe(401);
    // A rejected request that had taken the slot would make every later
    // connection-limit assertion wrong for a reason that looks like broken
    // accounting.
    const live = await readJson(await fetch(`${base}/s/${id}/connections`));
    expect(live.live).toBe(0);
  });

  it('404s an unknown channel id', async () => {
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/live/user/pass/99.ts`)).status).toBe(404);
  });

  it('answers HEAD with 200 and no body, without consuming a slot', async () => {
    const { base, id } = await xcScenario({ maxConnections: 1 });
    const res = await fetch(`${base}/s/${id}/live/user/pass/1.ts`, { method: 'HEAD' });
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('video/mp2t');
    expect((await readJson(await fetch(`${base}/s/${id}/connections`))).live).toBe(0);
  });

  it('400s a malformed percent-escape in the username segment, naming the field, rather than 500ing', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/live/%ZZ/pass/1.ts`);
    expect(res.status).toBe(400);
    expect((await readJson(res)).error).toContain('username');
  });

  it('400s a malformed percent-escape in the password segment, naming the field, rather than 500ing', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/live/user/%ZZ/1.ts`);
    expect(res.status).toBe(400);
    expect((await readJson(res)).error).toContain('password');
  });

  it('logs the 400 it actually sent for a malformed percent-escape, not a fabricated status', async () => {
    // Guards the same class of bug Task 3 fixed for `action`: a route that
    // computes its response before logging can't leave the ScenarioLog
    // claiming a status the client never received.
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/live/%ZZ/pass/1.ts`);
    expect(res.status).toBe(400);
    const log = await (await fetch(`${base}/s/${id}/log`)).json();
    expect(log).toContainEqual(expect.objectContaining({ kind: 'request', status: 400 }));
  });

  it("logs the request path the client actually sent, not one rewritten to carry the scenario's credentials", async () => {
    // Pins the fix for a log-fidelity bug: serveChannelStream's credential
    // bridge must not smuggle `?username=`/`?password=` into the URL object
    // that logRequest records from, since XC's own credentials already live
    // in the path segments — a client that never sent a query string must
    // not have one fabricated into its log entry.
    const { base, id } = await xcScenario();
    await fetch(`${base}/s/${id}/live/user/pass/1.ts`, { method: 'HEAD' });
    const log = (await (await fetch(`${base}/s/${id}/log`)).json()) as Record<string, unknown>[];
    expect(log).toContainEqual(
      expect.objectContaining({ kind: 'request', method: 'HEAD', status: 200, path: `/s/${id}/live/user/pass/1.ts` })
    );
    expect(log.some((e) => typeof e.path === 'string' && e.path.includes('username='))).toBe(false);
  });
});

// A pre-flight scan flagged a credential-encoding disagreement between two
// Dispatcharr call sites that both build XC playback URLs from the same
// account fields: `collect_xc_streams` (apps/m3u/tasks.py:933-936) builds
// the live URL with raw, unencoded credentials, while
// `build_timeshift_url_format_b` (apps/timeshift/helpers.py:424-433)
// percent-encodes both fields with `quote(str(x), safe='')`. This provider
// places no character restriction on `username`/`password` beyond "string"
// (scenario.ts), so a scenario can declare a credential containing '/' —
// making the disagreement reachable. Filed as
// https://github.com/D10Scot/Dispatcharr/issues/61 and tracked in
// e2e/COVERAGE.md rather than asserted here with a `test.fail()`: a request
// built the way `collect_xc_streams` builds it (raw interpolation) is
// genuinely a malformed URL — too many path segments to match
// `/live/<user>/<pass>/<id>.ts` at all — so a test asserting it 404s would
// pass whether or not the real defect exists, and one asserting it succeeds
// can never flip red or green from anything this provider controls. Only
// the encoded side (this provider's actual contract) is worth pinning here.
describe('XC live playback — credential encoding (known Dispatcharr defect)', () => {
  it('serves the stream when a slash-bearing credential is percent-encoded into the path, as build_timeshift_url_format_b does', async () => {
    const { base, id } = await xcScenario({ username: 'a/b', password: 'pass' });
    const res = await fetch(`${base}/s/${id}/live/${encodeURIComponent('a/b')}/pass/1.ts`);
    expect(res.status).toBe(200);
  });
});

/**
 * The vitest suite never sees the real assets — `assets/` is gitignored and
 * produced by the Docker builder stage. A recognisable byte pattern is all
 * the Range assertions need, and using one keeps this suite runnable with
 * `npm test` alone, no Docker.
 */
function syntheticVodAsset(): string {
  const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-vod-'));
  const path = join(dir, 'vod.mp4');
  writeFileSync(path, Buffer.from(Array.from({ length: 1000 }, (_u, i) => i % 251)));
  return path;
}

describe('XC VOD playback', () => {
  it('serves the whole asset with Content-Length and Accept-Ranges', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-length')).toBe('1000');
    expect(res.headers.get('accept-ranges')).toBe('bytes');
    expect(res.headers.get('content-type')).toBe('video/mp4');
    expect((await res.arrayBuffer()).byteLength).toBe(1000);
  });

  it('answers a Range with 206 and a Content-Range naming the full size', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`, {
      headers: { Range: 'bytes=100-199' },
    });
    expect(res.status).toBe(206);
    expect(res.headers.get('content-range')).toBe('bytes 100-199/1000');
    expect(res.headers.get('content-length')).toBe('100');
    const body = Buffer.from(await res.arrayBuffer());
    expect(body).toHaveLength(100);
    expect(body[0]).toBe(100 % 251);
  });

  it('answers an unsatisfiable Range with 416 and a Content-Range naming the size', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`, {
      headers: { Range: 'bytes=5000-' },
    });
    expect(res.status).toBe(416);
    expect(res.headers.get('content-range')).toBe('bytes */1000');
  });

  it('serves an episode on /series/<user>/<pass>/<id>.<ext>', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/series/user/pass/1.mp4`)).status).toBe(200);
  });

  it('404s an unknown movie or episode id, and 401s wrong credentials', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/movie/user/pass/99.mp4`)).status).toBe(404);
    expect((await fetch(`${base}/s/${id}/movie/user/wrong/1.mp4`)).status).toBe(401);
  });
});

describe('XC VOD asset cache', () => {
  // Every case above uses byte-identical synthetic assets (same length, same
  // pattern), which can't distinguish a cache keyed on the resolved path
  // from a bare "have we loaded one yet" flag — the two behave identically
  // whenever every test happens to reuse the same bytes. This test uses two
  // deliberately different-length assets to pin the real contract: a
  // changed UPSTREAM_VOD_ASSET must invalidate the cache, not be silently
  // ignored by whichever file loaded first in this module instance.
  it('serves the newly set asset, not one cached from an earlier UPSTREAM_VOD_ASSET', async () => {
    const dirA = mkdtempSync(join(tmpdir(), 'e2e-upstream-vod-cachecheck-'));
    process.env.UPSTREAM_VOD_ASSET = join(dirA, 'a.mp4');
    writeFileSync(process.env.UPSTREAM_VOD_ASSET, Buffer.alloc(1000, 1));
    const first = await xcScenario();
    const resA = await fetch(`${first.base}/s/${first.id}/movie/user/pass/1.mp4`);
    expect(resA.headers.get('content-length')).toBe('1000');

    const dirB = mkdtempSync(join(tmpdir(), 'e2e-upstream-vod-cachecheck-'));
    process.env.UPSTREAM_VOD_ASSET = join(dirB, 'b.mp4');
    writeFileSync(process.env.UPSTREAM_VOD_ASSET, Buffer.alloc(500, 2));
    const second = await xcScenario();
    const resB = await fetch(`${second.base}/s/${second.id}/movie/user/pass/1.mp4`);
    expect(resB.headers.get('content-length')).toBe('500');
  });
});
