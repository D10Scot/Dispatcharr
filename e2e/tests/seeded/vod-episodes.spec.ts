import { test, expect } from '../../fixtures';
import type { VodPage, Series, Episode, M3uEpisodeRelation } from '../../fixtures';

/**
 * `SeriesViewSet.series_info`'s hand-built response — not a serializer, so it
 * does not belong in `fixtures/types.ts`. `apps/vod/api_views.py:399` calls
 * `refresh_series_episodes()` inline when `episodes_fetched` or
 * `detailed_fetched` is unset, so this is synchronous: the whole episode
 * fetch happens inside the HTTP request that returns this shape.
 */
type SeriesInfoEpisode = {
  id: number; uuid: string; name: string; title: string;
  episode_number: number | null; season_number: number | null;
  container_extension: string;
};
type SeriesInfo = {
  id: number; series_id: string; name: string;
  episodes_fetched: boolean; detailed_fetched: boolean;
  episodes: Record<string, SeriesInfoEpisode[]>;
};

type EpisodeWithProviders = Episode & { providers: M3uEpisodeRelation[] };

test('Dispatcharr fetches episodes on demand for an object-keyed provider series', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // Two synchronous provider round-trips on account create, plus a
  // synchronous get_series_info inline in the provider-info call below.
  test.setTimeout(150_000);

  const prefix = seed.generatedName('vod-ep');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    series: [
      {
        id: 201,
        name: `${prefix}-show`,
        categoryId: 1,
        seasons: [
          { number: 1, episodes: [{ id: 301, title: `${prefix}-s1e1`, episodeNum: 1, containerExtension: 'mp4' }] },
          { number: 2, episodes: [{ id: 302, title: `${prefix}-s2e1`, episodeNum: 1, containerExtension: 'mkv' }] },
        ],
      },
    ],
    vod: [],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });

  const refreshRes = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(refreshRes.status()).toBe(202);

  const seriesPage = await waitFor.resource<VodPage<Series>>(
    `/api/vod/series/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the series named ${prefix}-show to be ingested`, timeoutMs: 120_000 }
  );
  const series = seriesPage.results[0];

  // --- Before state: "on demand" means not fetched until asked ------------
  // Reading episodes_fetched only after the triggering call below cannot
  // distinguish "fetched on demand" from "was already there" — assert the
  // zero state first, through both instruments the after-state uses.
  const episodesBefore = await api.json<VodPage<Episode>>(
    await api.get(`/api/vod/episodes/?series=${series.id}`),
    'episodes by series (before the on-demand fetch)'
  );
  expect(episodesBefore.count, 'no Episode rows exist before provider-info is called').toBe(0);
  const seriesInfoRequestsBefore = (await upstream.log(scenario)).filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('action=get_series_info')
  );
  expect(
    seriesInfoRequestsBefore,
    'get_series_info requests reaching the provider before provider-info is called'
  ).toHaveLength(0);

  // Episodes are NOT part of the refresh: refresh_vod_content makes exactly
  // four provider calls (get_vod_categories, get_series_categories,
  // get_vod_streams, get_series) and get_series_info is not among them. This
  // call forces the fetch inline, synchronously — assert on the response
  // directly rather than polling.
  const info = await api.json<SeriesInfo>(
    await api.get(`/api/vod/series/${series.id}/provider-info/`),
    'series provider-info'
  );

  const seriesInfoRequestsAfter = (await upstream.log(scenario)).filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('action=get_series_info')
  );
  expect(
    seriesInfoRequestsAfter,
    'get_series_info requests reaching the provider after provider-info is called'
  ).toHaveLength(1);

  expect(info.episodes_fetched).toBe(true);
  expect(info.detailed_fetched).toBe(true);
  expect(Object.keys(info.episodes).sort()).toEqual(['1', '2']);
  expect(info.episodes['1'][0]).toMatchObject({
    title: `${prefix}-s1e1`,
    episode_number: 1,
    season_number: 1,
    container_extension: 'mp4',
  });
  // The discriminating assertion: 'mp4' is also what a missing relation
  // falls back to, so agreeing with season 1 would prove nothing. 'mkv' can
  // only come from the actual per-episode container_extension surviving the
  // season grouping.
  expect(info.episodes['2'][0].container_extension).toBe('mkv');

  // Second, independent read of the same rows through the collection
  // endpoint: the provider-info response is assembled by hand and could
  // agree with itself while the stored rows are wrong.
  const episodes = await api.json<VodPage<Episode>>(
    await api.get(`/api/vod/episodes/?series=${series.id}`),
    'episodes by series'
  );
  expect(episodes.count).toBe(2);
  const pairs = episodes.results
    .map((e) => [e.season_number, e.episode_number])
    .sort((a, b) => (a[0]! - b[0]!));
  expect(pairs).toEqual([[1, 1], [2, 1]]);
});

test('Dispatcharr fetches episodes on demand for an array-keyed provider series, season 0 included', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(150_000);

  // This test proves shape-acceptance, not shape-discrimination: that
  // Dispatcharr ingests the array-shaped `episodes` payload correctly, not
  // that it behaves differently from the season-keyed object shape, which it
  // provably does not. parseSeries (e2e-upstream/src/scenario.ts:517-527)
  // rejects seasonsAsArray unless seasons[i].number === i, so the array
  // shape can only ever carry the same season numbers the object shape
  // would; series_info (apps/vod/api_views.py:549-554) rebuilds its response
  // from the database, never echoing the provider's raw shape. So the two
  // shapes are byte-identical downstream by construction — that is by
  // design, not a gap this test failed to close.
  //
  // What it does protect is batch_process_episodes's array branch
  // (apps/vod/tasks.py, int(season_num) around :1407-1410): drop that
  // branch and control falls to `else: warning; return`, yielding zero
  // rows, while refresh_series_episodes still sets episodes_fetched: true
  // unconditionally (tasks.py:1376) — so this test fails at both the
  // season-1 row-count assertion and the season-0 membership assertion
  // below, which is the evidence that it is load-bearing.
  const prefix = seed.generatedName('vod-ep-arr');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    series: [
      {
        id: 202,
        name: `${prefix}-show`,
        categoryId: 1,
        seasonsAsArray: true,
        seasons: [
          { number: 0, episodes: [{ id: 401, title: `${prefix}-s0e1`, episodeNum: 1, containerExtension: 'mp4' }] },
          {
            number: 1,
            episodes: [
              { id: 402, title: `${prefix}-s1e1-a`, episodeNum: 1, containerExtension: 'mp4' },
              { id: 403, title: `${prefix}-s1e1-b`, episodeNum: 1, containerExtension: 'mkv' },
            ],
          },
        ],
      },
    ],
    vod: [],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });

  const refreshRes = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(refreshRes.status()).toBe(202);

  const seriesPage = await waitFor.resource<VodPage<Series>>(
    `/api/vod/series/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the series named ${prefix}-show to be ingested`, timeoutMs: 120_000 }
  );
  const series = seriesPage.results[0];

  const info = await api.json<SeriesInfo>(
    await api.get(`/api/vod/series/${series.id}/provider-info/`),
    'series provider-info'
  );

  // batch_process_episodes (apps/vod/tasks.py:1387-1425) accepts a dict or a
  // list and uses the key or the index as the season number; index 0 is what
  // makes season 0 reachable at all under the array shape.
  expect(Object.keys(info.episodes)).toContain('0');

  // The '0' key alone proves nothing. SeriesViewSet.series_info builds the
  // key as `str(episode.season_number if episode.season_number is not None
  // else 0)` (apps/vod/api_views.py:551-553) — so an episode whose
  // season_number is NULL, which is what a failed season mapping looks like,
  // keys as '0' too. Only the stored column tells "season zero" apart from
  // "no season at all", and toContain(0) does not match a null.
  const rows = await api.json<VodPage<Episode>>(
    await api.get(`/api/vod/episodes/?series=${series.id}`),
    'episodes by series'
  );
  expect(rows.count).toBe(2);
  expect(rows.results.map((e) => e.season_number)).toContain(0);

  // Season 1 has exactly one Episode row, not two: Episode.unique_together
  // is ('series', 'season_number', 'episode_number'), so the two provider
  // streams with the same episode_num collapse into one row.
  const season1 = rows.results.filter((e) => e.season_number === 1);
  expect(season1).toHaveLength(1);
  expect(season1[0].episode_number).toBe(1);

  // That one Episode has two M3UEpisodeRelation rows — normal provider
  // behaviour for two streams of the same episode (different languages or
  // qualities), not a duplicate. get_episodes (apps/vod/api_views.py:374) is
  // the only endpoint that surfaces both relations: EpisodeViewSet has no
  // `providers` route, and provider-info's per-episode container_extension
  // is resolved from a dict keyed by episode_id, which collapses the two
  // relations and so cannot prove they exist.
  const withProviders = await api.json<EpisodeWithProviders[]>(
    await api.get(`/api/vod/series/${series.id}/episodes/`),
    'series episodes with providers'
  );
  const s1e1 = withProviders.find((e) => e.season_number === 1 && e.episode_number === 1);
  expect(s1e1).toBeTruthy();
  // Assert the two stream ids, not just providers.length === 2 — length
  // alone would pass on two relations pointing at the wrong streams.
  // stream_id is a CharField, so these compare as strings.
  expect(s1e1!.providers.map((r) => r.stream_id).sort()).toEqual(['402', '403']);
});
