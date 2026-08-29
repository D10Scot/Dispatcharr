import { test, expect } from '../../fixtures';

interface Page<T> { count: number; results: T[] }
interface MovieRow { id: number; uuid: string; name: string }

test('a VOD stream is delivered through /proxy/vod/ with seek metadata', async ({
  upstream,
  seed,
  waitFor,
  request,
}) => {
  const prefix = seed.generatedName('vodread');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    // containerExtension/tmdbId/imdbId are required on UpstreamMovie even
    // though the provider's own door parser defaults them (see Task 9
    // report: e2e-upstream/src/scenario.ts:371-386); values match what an
    // omitting caller would get.
    vod: [{
      id: 1,
      name: `${prefix}-movie`,
      year: 2020,
      categoryId: 1,
      containerExtension: 'mp4',
      tmdbId: null,
      imdbId: null,
    }],
    series: 0,
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const movies = await waitFor.resource<Page<MovieRow>>(
    `/api/vod/movies/?search=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the VOD movie ${prefix}-movie to be ingested`, timeoutMs: 120_000 }
  );
  const uuid = movies.results[0].uuid;

  // Playwright's `request` context, not the `api` fixture: `stream_vod` is
  // AllowAny and no real client of this surface carries a bearer token. It
  // follows the session-path redirect `stream_vod` issues on a first request,
  // which is where the actual bytes come from.
  const full = await request.get(`/proxy/vod/movie/${uuid}`);
  expect(full.status()).toBe(200);
  const headers = full.headers();
  // Both come from the provider's Content-Length. Without it,
  // multi_worker_connection_manager emits neither, and every seek a client
  // attempts is unbounded.
  expect(headers['accept-ranges']).toBe('bytes');
  const total = Number(headers['content-length']);
  expect(total).toBeGreaterThan(1024);
  const body = await full.body();
  expect(body.byteLength).toBe(total);
  // The asset is a real MP4: box size, then 'ftyp'.
  expect(body.subarray(4, 8).toString('ascii')).toBe('ftyp');

  // A mid-file Range, which is the thing the finite asset exists for.
  const partial = await request.get(`/proxy/vod/movie/${uuid}`, {
    headers: { Range: `bytes=100-199` },
  });
  expect(partial.status()).toBe(206);
  expect(partial.headers()['content-range']).toBe(`bytes 100-199/${total}`);
  const slice = await partial.body();
  expect(slice.byteLength).toBe(100);
  expect(slice).toEqual(body.subarray(100, 200));

  // Proves the provider itself was reached and answered cleanly for both
  // requests above (not that Dispatcharr synthesized a response without
  // ever contacting it), and that neither leaked an unexpected status.
  const log = await upstream.log(scenario);
  const movieRequests = log.filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('/movie/')
  );
  expect(movieRequests.length).toBeGreaterThan(0);
  expect(movieRequests.every((entry) => entry.status === 200 || entry.status === 206)).toBe(true);
});
