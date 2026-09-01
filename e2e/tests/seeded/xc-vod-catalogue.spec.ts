import { test, expect, xcQuery } from '../../fixtures';
import type {
  Movie,
  Series,
  Episode,
  VodCategory,
  M3uSeriesRelation,
  VodPage,
} from '../../fixtures';

/**
 * G9 rows 9, 10 and 20. `e2e/tests/seeded/xc-vod-catalogue-shape.spec.ts` (G5)
 * proved these six XC actions answer at all against a catalogue that may be
 * empty — this file is the fidelity half, against a real, seeded catalogue,
 * and pins one defect.
 *
 * Every XC action below goes through Playwright's built-in `request`
 * context with `xcQuery(user)`, never the `api` fixture: `ApiClient.send`
 * retries once through a token refresh on any 401, which would silently
 * spend a refresh on exactly the row asserting a 401 (the adult-filter
 * `get_vod_info` case in the second test). `api` is still used for the REST
 * setup/verification calls that have nothing to do with the XC surface.
 */

test('the XC VOD actions answer a real catalogue with Dispatcharr identities, not the provider\'s (G9 row 9)', async ({
  upstream,
  seed,
  api,
  request,
  waitFor,
}) => {
  test.setTimeout(150_000);

  const prefix = seed.generatedName('vodxc');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [
      { id: 1, name: `${prefix}-movies-a` },
      { id: 2, name: `${prefix}-movies-b` },
    ],
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    vod: [
      {
        id: 101,
        name: `${prefix}-alpha`,
        year: 1999,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
        // Feeds the provider-info guard below, which exists to cover the
        // premise of the row-20 test.fail() at the bottom of this file: that
        // /api/vod/movies/<pk>/provider-info/ actually reports bitrate.
        vodInfo: { bitrate: 4321 },
      },
      {
        id: 102,
        name: `${prefix}-beta`,
        year: 2011,
        categoryId: 2,
        containerExtension: 'mkv',
        tmdbId: null,
        imdbId: null,
      },
    ],
    series: [
      {
        id: 201,
        name: `${prefix}-show`,
        categoryId: 1,
        seasons: [
          {
            number: 1,
            episodes: [
              { id: 301, title: `${prefix}-s1e1`, episodeNum: 1, containerExtension: 'mp4' },
            ],
          },
        ],
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  const refresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(refresh.status(), 'POST refresh-vod/').toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 2,
    { description: `both ${prefix} movies to be ingested`, timeoutMs: 120_000 }
  );
  expect(movies.count, `movie rows for ${prefix} scoped to account ${account.id}`).toBe(2);
  const alpha = movies.results.find((m) => m.name === `${prefix}-alpha`);
  const beta = movies.results.find((m) => m.name === `${prefix}-beta`);
  expect(alpha, `${prefix}-alpha among the ingested movies`).toBeDefined();
  expect(beta, `${prefix}-beta among the ingested movies`).toBeDefined();

  // VODCategory is unpaginated and instance-global — locate ours by name and
  // type, never by index or length.
  const categories = await api.json<VodCategory[]>(
    await api.get('/api/vod/categories/'),
    'vod categories'
  );
  const movieCategoryA = categories.find(
    (c) => c.name === `${prefix}-movies-a` && c.category_type === 'movie'
  );
  const movieCategoryB = categories.find(
    (c) => c.name === `${prefix}-movies-b` && c.category_type === 'movie'
  );
  expect(movieCategoryA, `a movie category named ${prefix}-movies-a`).toBeDefined();
  expect(movieCategoryB, `a movie category named ${prefix}-movies-b`).toBeDefined();

  const user = await seed.xcUser();

  // --- get_vod_categories --------------------------------------------------

  const listedCategories = JSON.parse(
    await (
      await request.get(`/player_api.php${xcQuery(user, { action: 'get_vod_categories' })}`)
    ).text()
  ) as { category_id: string; category_name: string }[];

  // xc_get_vod_categories filters m3umovierelation__m3u_account__is_active,
  // so a category with no ingested movie would not appear — both of this
  // test's categories have one, so absence here would be a real defect, not
  // an artefact of the filter.
  const listedCategoryA = listedCategories.find(
    (c) => c.category_name === `${prefix}-movies-a`
  );
  expect(listedCategoryA, `${prefix}-movies-a among get_vod_categories`).toBeDefined();
  // The assertion that catches "any id" passing for the wrong reason: it
  // must be the Dispatcharr VODCategory pk, emitted as a string, not the
  // provider's own category id (which was also "1").
  expect(listedCategoryA!.category_id).toBe(String(movieCategoryA!.id));

  // --- get_vod_streams (unfiltered) ----------------------------------------

  const allStreamsRes = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_vod_streams' })}`
  );
  expect(allStreamsRes.status(), 'get_vod_streams').toBe(200);
  const allStreams = await allStreamsRes.json();

  const alphaStream = allStreams.find((s: any) => s.stream_id === alpha!.id);
  const betaStream = allStreams.find((s: any) => s.stream_id === beta!.id);
  expect(alphaStream, `${prefix}-alpha among get_vod_streams, keyed by Movie.pk`).toBeDefined();
  expect(betaStream, `${prefix}-beta among get_vod_streams, keyed by Movie.pk`).toBeDefined();

  expect(alphaStream.stream_type).toBe('movie');
  expect(alphaStream.container_extension).toBe('mp4');
  expect(alphaStream.year).toBe(1999);
  expect(alphaStream.category_id).toBe(String(movieCategoryA!.id));

  expect(betaStream.stream_type).toBe('movie');
  expect(betaStream.container_extension).toBe('mkv');
  expect(betaStream.year).toBe(2011);
  expect(betaStream.category_id).toBe(String(movieCategoryB!.id));

  // --- get_vod_streams, narrowed by category_id ----------------------------

  const narrowedRes = await request.get(
    `/player_api.php${xcQuery(user, {
      action: 'get_vod_streams',
      category_id: movieCategoryA!.id,
    })}`
  );
  expect(narrowedRes.status(), 'get_vod_streams?category_id').toBe(200);
  const narrowed = await narrowedRes.json();

  expect(
    narrowed.some((s: any) => s.stream_id === alpha!.id),
    `${prefix}-alpha present when narrowed to its own category`
  ).toBe(true);
  // The discriminating half: not merely "alpha is present", but "beta,
  // which belongs to the other category, is absent" — narrowing to []
  // containing everything would still pass the assertion above.
  expect(
    narrowed.some((s: any) => s.stream_id === beta!.id),
    `${prefix}-beta absent when narrowed to a category it does not belong to`
  ).toBe(false);

  // --- get_vod_info, and the round trip -------------------------------------

  const infoRes = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_vod_info', vod_id: alpha!.id })}`
  );
  expect(infoRes.status(), 'get_vod_info').toBe(200);
  const info = await infoRes.json();
  expect(info.info, 'get_vod_info info object').toBeTruthy();
  expect(info.movie_data, 'get_vod_info movie_data object').toBeTruthy();
  // The round trip closes: the id get_vod_streams emitted (stream_id, above)
  // is the id get_vod_info takes and echoes back — xc_get_vod_info filters
  // movie_id=vod_id.
  expect(info.movie_data.stream_id).toBe(alpha!.id);
  expect(info.movie_data.container_extension).toBe('mp4');

  // --- provider-info: the advanced-data half of the fidelity check --------
  //
  // The row-20 test.fail() below rests on the premise that
  // /api/vod/movies/<pk>/provider-info/ reports the bitrate the provider's
  // get_vod_info fetched. Nothing non-inverted asserted that anywhere in the
  // suite — the sibling vod-advanced-data.spec.ts guards the advanced fetch
  // via director/actors, not bitrate/video/audio — so a regression in the
  // bitrate half of that endpoint would leave the inverted pin silently
  // green instead of red. This assertion is what would catch it.
  const alphaProviderInfo = await api.json<{ bitrate: number }>(
    await api.get(`/api/vod/movies/${alpha!.id}/provider-info/`),
    'alpha provider-info (advanced data fetch)'
  );
  expect(alphaProviderInfo.bitrate).toBe(4321);
});

test('the XC series actions, and the series_id/Movie.pk asymmetry, and adult filtering on get_vod_streams (G9 row 10)', async ({
  upstream,
  seed,
  api,
  request,
  waitFor,
}) => {
  test.setTimeout(180_000);

  const prefix = seed.generatedName('vodxcser');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    vod: [
      {
        id: 401,
        name: `${prefix}-adult`,
        year: 2015,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
        isAdult: true,
      },
      {
        id: 402,
        name: `${prefix}-control`,
        year: 2016,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
      },
    ],
    series: [
      {
        id: 201,
        name: `${prefix}-show`,
        categoryId: 1,
        seasons: [
          {
            number: 1,
            episodes: [
              { id: 301, title: `${prefix}-s1e1`, episodeNum: 1, containerExtension: 'mp4' },
            ],
          },
        ],
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  const refresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(refresh.status(), 'POST refresh-vod/').toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 2,
    { description: `both ${prefix} movies to be ingested`, timeoutMs: 120_000 }
  );
  const adultMovie = movies.results.find((m) => m.name === `${prefix}-adult`);
  const controlMovie = movies.results.find((m) => m.name === `${prefix}-control`);
  expect(adultMovie, `${prefix}-adult among the ingested movies`).toBeDefined();
  expect(controlMovie, `${prefix}-control among the ingested movies`).toBeDefined();

  const seriesPage = await waitFor.resource<VodPage<Series>>(
    `/api/vod/series/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the series ${prefix}-show to be ingested`, timeoutMs: 120_000 }
  );
  expect(seriesPage.count).toBe(1);
  const series = seriesPage.results[0];

  const seriesRelations = await api.json<M3uSeriesRelation[]>(
    await api.get(`/api/vod/series/${series.id}/providers/`),
    'series providers'
  );
  const relation = seriesRelations.find((r) => r.m3u_account.id === account.id);
  expect(relation, `a relation to account ${account.id} for ${prefix}-show`).toBeDefined();

  // seed.xcUser() defaults user_level: 1, below the 10 that would exempt a
  // user from the adult filter below — used for the series half too.
  const user = await seed.xcUser();

  // --- get_series: series_id is the relation pk, not the Series pk --------

  const seriesListRes = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_series' })}`
  );
  expect(seriesListRes.status(), 'get_series').toBe(200);
  const seriesList = await seriesListRes.json();
  const seriesEntry = seriesList.find((s: any) => s.name === `${prefix}-show`);
  expect(seriesEntry, `${prefix}-show among get_series`).toBeDefined();

  // xc_get_series emits row['id'] — the M3USeriesRelation pk — while
  // xc_get_vod_streams (row 9, above) emits row['movie__id'] — the content
  // pk. Assert both halves of that asymmetry explicitly: it is exactly the
  // kind of thing a refactor unifies and breaks.
  expect(seriesEntry.series_id, 'series_id equals the M3USeriesRelation pk').toBe(relation!.id);
  // series_id (the M3USeriesRelation pk) and Series.pk are independent
  // Postgres sequences sharing the test database with every other suite's
  // rows, so it is possible — rare, but not impossible — for relation!.id
  // and series.id to collide by chance on a given run. When they do, the
  // negative assertion below is undecidable: relation!.id === series.id
  // would hold for both a correct implementation (which the positive
  // assertion above already proved) and the exact bug this row exists to
  // pin, so asserting inequality would fail on entirely conforming
  // behaviour. Skip only that coincidence, and record why, rather than
  // letting the run go spuriously red.
  if (relation!.id === series.id) {
    test.info().annotations.push({
      type: 'skip-reason',
      description: `relation pk (${relation!.id}) coincidentally equals series pk (${series.id}) this run; the negative series_id !== series.id check is undecidable here and was skipped`,
    });
  } else {
    expect(
      seriesEntry.series_id,
      'series_id must NOT be the Series pk (the asymmetry this row exists to pin)'
    ).not.toBe(series.id);
  }

  // --- get_series_info: episodes grouped by season, keyed by Episode.pk ---

  const seriesInfoRes = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_series_info', series_id: relation!.id })}`
  );
  expect(seriesInfoRes.status(), 'get_series_info').toBe(200);
  const seriesInfo = await seriesInfoRes.json();
  const season1 = seriesInfo.episodes?.['1'];
  expect(season1, 'season 1 present in get_series_info episodes').toBeTruthy();
  expect(season1.length).toBe(1);
  expect(season1[0].title).toBe(`${prefix}-s1e1`);

  // Second, independent read of the same row through the REST collection —
  // xc_get_series_info calls refresh_series_episodes inline, so the Episode
  // row already exists by the time this runs. Comparing against a value
  // fetched independently, rather than trusting the hand-built XC response
  // to agree with itself, is what proves `id` really is the Episode pk.
  const episodes = await api.json<VodPage<Episode>>(
    await api.get(`/api/vod/episodes/?series=${series.id}`),
    'episodes for the series'
  );
  expect(episodes.count).toBe(1);
  expect(season1[0].id).toBe(episodes.results[0].id);

  // --- adult filtering on get_vod_streams -----------------------------------

  const hiddenUser = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  const hiddenStreamsRes = await request.get(
    `/player_api.php${xcQuery(hiddenUser, { action: 'get_vod_streams' })}`
  );
  expect(hiddenStreamsRes.status(), 'get_vod_streams for the hide_adult_content user').toBe(200);
  const hiddenStreams = await hiddenStreamsRes.json();

  expect(
    hiddenStreams.some((s: any) => s.stream_id === adultMovie!.id),
    `${prefix}-adult absent from get_vod_streams for a user with hide_adult_content`
  ).toBe(false);
  // The positive control: an empty list would also satisfy the absence
  // above. The non-adult control movie must still be there.
  expect(
    hiddenStreams.some((s: any) => s.stream_id === controlMovie!.id),
    `${prefix}-control present from get_vod_streams for a user with hide_adult_content`
  ).toBe(true);

  const hiddenInfoRes = await request.get(
    `/player_api.php${xcQuery(hiddenUser, { action: 'get_vod_info', vod_id: adultMovie!.id })}`
  );
  // xc_get_vod_info adds movie__is_adult=False to its filters for this user
  // and raises Http404 when nothing matches; there is no custom handler404
  // in dispatcharr/urls.py, so the client sees Django's own 404.
  expect(hiddenInfoRes.status(), 'get_vod_info for the adult movie, hide_adult_content user').toBe(404);

  // The other direction: the FIRST user, with no hide_adult_content, must
  // still see the adult movie. Without this, the absence above could just
  // as easily be an ingest failure for that movie rather than the filter
  // actually working. This is also this goal's positive control for row 16
  // (the same movie is nonetheless streamable).
  const openStreamsRes = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_vod_streams' })}`
  );
  expect(openStreamsRes.status(), 'get_vod_streams for the user with no hide_adult_content').toBe(200);
  const openStreams = await openStreamsRes.json();
  expect(
    openStreams.some((s: any) => s.stream_id === adultMovie!.id),
    `${prefix}-adult present from get_vod_streams for a user with no hide_adult_content`
  ).toBe(true);
});

// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_vod_info`
// (apps/output/views.py:1675) gates the whole detailed_info merge on
//     if movie.custom_properties:
// and then, one line later (:1680), reads the data off the *relation*:
//     detailed_info = movie_relation.custom_properties.get('detailed_info', {})
// — the wrong object's truthiness. The commented-out :1679 shows the source
// that was intended. A movie whose provider payload carries none of
// trailer/director/actors/backdrop has Movie.custom_properties = None
// (clean_custom_properties({}) returns None, apps/vod/tasks.py:2132), so
// bitrate, video, audio, cover_big and the plot override never reach an XC
// client even though refresh_movie_advanced_data just fetched and stored
// them on the relation. /api/vod/movies/<pk>/provider-info/ reads the same
// relation and returns them correctly, which is what makes the two
// disagree.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/97
test.fail('XC get_vod_info returns the advanced data the REST API returns (G9 row 20, defect)', async ({
  upstream,
  seed,
  api,
  request,
  waitFor,
}) => {
  test.setTimeout(150_000);

  const prefix = seed.generatedName('vodsparse');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    vod: [
      {
        id: 601,
        name: `${prefix}-sparse`,
        year: 2005,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
        // Deliberately sparse: no director/actors/youtube_trailer/
        // backdrop_path anywhere in this literal. Those are the only four
        // keys ingest ever writes into Movie.custom_properties
        // (apps/vod/tasks.py, process_movie_batch), so adding any of them
        // here — a `director`, say — would make Movie.custom_properties
        // non-null and disarm the defect entirely. Do not "simplify" this.
        vodInfo: {
          plot: `${prefix}-sparse — detailed plot`,
          genre: 'E2E',
          rating: '7.5',
          duration_secs: 5,
          bitrate: 4321,
          video: { codec_name: 'h264', width: 320, height: 180 },
          audio: { codec_name: 'aac' },
        },
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  const refresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(refresh.status(), 'POST refresh-vod/').toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the sparse VOD movie named ${prefix}-sparse to be ingested`, timeoutMs: 120_000 }
  );
  const movie = movies.results[0];

  const user = await seed.xcUser();

  // Drives the advanced fetch and reads it back correctly, straight off the
  // relation.
  const restInfo = await api.json<{
    bitrate: number;
    video: Record<string, unknown>;
    audio: Record<string, unknown>;
  }>(
    await api.get(`/api/vod/movies/${movie.id}/provider-info/`),
    'movie provider-info (advanced data fetch)'
  );

  // Premise, not the defect under test: a failure on THIS line means the
  // advanced fetch never happened or the fixture is wrong, not that the
  // product is broken. test.fail() is satisfied by any failure in this
  // block, so if this were the assertion that failed, the test would still
  // report "expected failure" and tell us nothing about the actual defect —
  // guarding it first, and separately, is what makes the two distinguishable.
  expect(restInfo.bitrate).toBe(4321);

  const xcRes = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_vod_info', vod_id: movie.id })}`
  );
  expect(xcRes.status()).toBe(200);
  const xcInfo = await xcRes.json();

  // The defect: these should agree with the REST payload above (both read
  // the same relation's fetched advanced data) and do not.
  expect(xcInfo.info.bitrate).toBe(restInfo.bitrate);
  expect(xcInfo.info.video).toEqual(restInfo.video);
  expect(xcInfo.info.audio).toEqual(restInfo.audio);
});
