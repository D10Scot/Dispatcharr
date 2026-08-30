import { test, expect } from '../../fixtures';

interface Page<T> {
  count: number;
  results: T[];
}
interface MovieRow { id: number; uuid: string; name: string; year: number | null }
interface SeriesRow { id: number; uuid: string; name: string }
interface EpisodeRow { id: number; name: string; season_number: number; episode_number: number }

test('Dispatcharr ingests a VOD and series catalogue from an Xtream Codes account', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const prefix = seed.generatedName('vod');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    // The request type is `UpstreamMovie[]`/`UpstreamEpisode[]` verbatim
    // (fixtures/types.ts), which — unlike the provider's own parser in
    // e2e-upstream/src/scenario.ts — declares containerExtension/tmdbId/
    // imdbId as required rather than optional-with-defaults. The brief's
    // literals omit them and do not typecheck; supplied here with the same
    // values the provider would have defaulted to (`mp4`/`null`/`null`).
    vod: [
      {
        id: 1,
        name: `${prefix}-movie`,
        year: 2020,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
      },
    ],
    series: [
      {
        id: 1,
        name: `${prefix}-series`,
        categoryId: 1,
        seasons: [
          {
            number: 1,
            episodes: [
              { id: 1, title: `${prefix}-ep`, episodeNum: 1, containerExtension: 'mp4' },
            ],
          },
        ],
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  // The M3U refresh finishing says NOTHING about VOD: refresh_vod_content is
  // fired with .delay() *after* it returns, so the account reaches `success`
  // before any Movie exists. Poll for the rows themselves.
  const movies = await waitFor.resource<Page<MovieRow>>(
    `/api/vod/movies/?search=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the VOD movie named ${prefix}-movie to be ingested`, timeoutMs: 120_000 }
  );
  expect(movies.results[0]).toMatchObject({ name: `${prefix}-movie`, year: 2020 });

  const series = await waitFor.resource<Page<SeriesRow>>(
    `/api/vod/series/?search=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the series named ${prefix}-series to be ingested`, timeoutMs: 120_000 }
  );

  // Episodes are NOT part of the refresh. get_series_info is a separate,
  // on-demand call, and this endpoint is what reaches it — synchronously.
  // Routed through api.json rather than a bare api.get: api.get does not
  // assert res.ok() on its own, so a 5xx here would otherwise surface as an
  // opaque `toMatchObject` failure against `undefined` two calls later.
  await api.json(
    await api.get(`/api/vod/series/${series.results[0].id}/provider-info/`),
    'series provider-info refresh'
  );

  // EpisodeViewSet declares `search_fields = ['name', 'description']`
  // (apps/vod/api_views.py), so `/api/vod/episodes/?search=` is supported —
  // used as specified rather than the per-series `episodes/` route.
  const episodes = await api.json<Page<EpisodeRow>>(
    await api.get(`/api/vod/episodes/?search=${encodeURIComponent(prefix)}`),
    'episodes created by the series-info fetch'
  );
  // Matches the movie and series steps above: assert the row exists before
  // indexing into it, so a broken provider-info fetch fails here naming the
  // count rather than as an opaque toMatchObject against undefined.
  expect(episodes.count, `episode named ${prefix}-ep created by the series-info fetch`).toBe(1);
  expect(episodes.results[0]).toMatchObject({
    name: `${prefix}-ep`,
    season_number: 1,
    episode_number: 1,
  });
});
