import { test, expect } from '../../fixtures';
import type {
  ApiClient, Seeder, Waiter, UpstreamClient,
  Episode, Movie, Series, VodPage,
} from '../../fixtures';

// The movie's provider id is 501 and the series' is 201 in every file that
// copies this block, so `501.mp4` and `201` can be written as literals in the
// assertions below. Task 7 also declares a movie with provider id 501: that is
// deliberate and safe, because a provider id is scenario-scoped — each test
// creates its own scenario and its own account. Only *names* have to be
// generated, because `Movie` and `Series` are matched across all accounts by
// TMDB -> IMDB -> (name, year) and `VODCategory` is unique on
// (name, category_type) globally. Do not "fix" the reuse by renumbering.
async function seedVodContent(
  upstream: UpstreamClient,
  seed: Seeder,
  api: ApiClient,
  waitFor: Waiter
) {
  const prefix = seed.generatedName('vodplay');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    vod: [
      { id: 501, name: `${prefix}-movie`, year: 2019, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ],
    series: [
      {
        id: 201,
        name: `${prefix}-show`,
        categoryId: 1,
        // Two episodes, so "the series route resolves the FIRST episode" is a
        // real claim in Step 3 rather than the only option available.
        seasons: [
          { number: 1, episodes: [
            { id: 301, title: `${prefix}-s1e1`, episodeNum: 1, containerExtension: 'mp4' },
            { id: 302, title: `${prefix}-s1e2`, episodeNum: 2, containerExtension: 'mp4' },
          ] },
        ],
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {})).status()).toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the ${prefix} movie to be ingested`, timeoutMs: 120_000 }
  );
  const seriesPage = await waitFor.resource<VodPage<Series>>(
    `/api/vod/series/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the ${prefix} series to be ingested`, timeoutMs: 120_000 }
  );
  const series = seriesPage.results[0];

  // Episodes are NOT part of `refresh-vod` — `refresh_vod_content` makes four
  // provider calls and `get_series_info` is not among them. This read is what
  // creates them: `SeriesViewSet.series_info` calls `refresh_series_episodes`
  // synchronously, inside the request.
  expect((await api.get(`/api/vod/series/${series.id}/provider-info/`)).status()).toBe(200);
  const episodes = await api.json<VodPage<Episode>>(
    await api.get(`/api/vod/episodes/?series=${series.id}&ordering=episode_number`),
    'ingested episodes'
  );
  expect(episodes.count).toBe(2);

  return { prefix, scenario, account, movie: movies.results[0], series, episodes: episodes.results };
}

test('a VOD movie URL mints a session, redirects, and delivers bytes matching the provider (G9 row 11)', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
  streamClient,
}) => {
  test.setTimeout(180_000);
  const { scenario, movie } = await seedVodContent(upstream, seed, api, waitFor);

  // 301, not 302: with no session_id and the default Stream Profile not
  // Redirect, stream_vod mints a session and hand-builds a 301 whose Location
  // is a relative path carrying the session_id — as opposed to the 302
  // straight at the provider that row 21 (the Redirect profile) covers.
  await streamClient.open(`/proxy/vod/movie/${movie.uuid}`, { redirect: 'manual' });
  expect(streamClient.status).toBe(301);
  const location = streamClient.headers!.get('location')!;
  expect(location).toMatch(/\/vod_\d+_\d+$/);

  // Re-open following redirects and read the body with request.get — the
  // asset is finite, so APIResponse.body() resolves (unlike live TS, where it
  // never would).
  const res = await request.get(`/proxy/vod/movie/${movie.uuid}`);
  expect(res.status()).toBe(200);
  const headers = res.headers();
  expect(headers['accept-ranges']).toBe('bytes');
  // From the provider's own Content-Type header (loadFiniteAsset in
  // e2e-upstream/src/server.ts), not just "some content-type present".
  expect(headers['content-type']).toBe('video/mp4');

  // Compare the first bytes against the provider directly. toControl rewrites
  // the container-internal origin to one this process can reach, and throws
  // on anything outside it — which is what stops this from making a real
  // outbound request by accident.
  const direct = await fetch(
    upstream.toControl(`${scenario.internal}/movie/${scenario.username}/${scenario.password}/501.mp4`)
  );
  const assetBytes = Buffer.from(await direct.arrayBuffer());
  const served = await res.body();
  expect(served.byteLength).toBe(Number(headers['content-length']));
  expect(served.subarray(0, 1024)).toEqual(assetBytes.subarray(0, 1024));

  // Correlate with the provider log: the movie was actually fetched from the
  // provider, and every hit answered cleanly. Not asserting an exact count —
  // the direct fetch above also lands in this log, and the session may
  // reconnect.
  const log = await upstream.log(scenario);
  const movieRequests = log.filter((e) => e.kind === 'request' && e.path?.includes(`/movie/`) && e.path?.includes('501.'));
  expect(movieRequests.length).toBeGreaterThan(0);
  expect(movieRequests.every((e) => e.status === 200 || e.status === 206)).toBe(true);
});

test('the episode and series VOD entry points deliver bytes, and the series route resolves the first episode (G9 row 12)', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { scenario, series, episodes } = await seedVodContent(upstream, seed, api, waitFor);

  // episodes is ordered by episode_number, so [0] is s1e1, provider id 301 —
  // the first of the two episodes Step 1 declared.
  const firstEpisode = episodes[0];
  expect(firstEpisode.episode_number).toBe(1);

  const episodeRes = await request.get(`/proxy/vod/episode/${firstEpisode.uuid}`);
  expect(episodeRes.status()).toBe(200);
  const episodeBody = await episodeRes.body();

  // Compared against the provider through toControl, as in row 11, using the
  // fake upstream's own /series/<user>/<pass>/<episodeStreamId>.<ext> route —
  // that is how the provider itself serves episode assets.
  const directEpisode = await fetch(
    upstream.toControl(`${scenario.internal}/series/${scenario.username}/${scenario.password}/301.mp4`)
  );
  const episodeAssetBytes = Buffer.from(await directEpisode.arrayBuffer());
  expect(episodeBody).toEqual(episodeAssetBytes);

  // The series route resolves to the same content: stream_vod's `series`
  // content type picks the first episode by (season_number, episode_number).
  const seriesRes = await request.get(`/proxy/vod/series/${series.uuid}`);
  expect(seriesRes.status()).toBe(200);
  const seriesBody = await seriesRes.body();
  expect(seriesBody).toEqual(episodeBody);

  // Prove it through the provider log, not just a byte match — a byte
  // coincidence between two 1-second fixture assets would say nothing. With
  // two declared episodes (301 and 302), asserting "301 was requested, 302
  // never was" is a real claim about which one the series route picked.
  const log = await upstream.log(scenario);
  const assetRequests = log.filter(
    (e) => e.kind === 'request' && e.path?.includes('/series/') && (e.path?.includes('301.') || e.path?.includes('302.'))
  );
  expect(assetRequests.some((e) => e.path?.includes('301.'))).toBe(true);
  expect(assetRequests.some((e) => e.path?.includes('302.'))).toBe(false);
});
