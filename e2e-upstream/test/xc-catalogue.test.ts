import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario.js';
import {
  renderLiveCategories,
  renderLiveStreams,
  renderSeries,
  renderSeriesCategories,
  renderSeriesInfo,
  renderVodCategories,
  renderVodInfo,
  renderVodStreams,
} from '../src/xc/catalogue.js';

const xc = (overrides = {}) =>
  new ScenarioRegistry().create({ xc: true, username: 'u', password: 'p', ...overrides });

describe('category actions', () => {
  it('renders live, VOD and series categories from their own scenario field, not each other\'s', () => {
    // A mutation swapping renderVodCategories' and renderSeriesCategories'
    // bodies (or either for renderLiveCategories') must fail this: each
    // category list is asserted against a name unique to its own field, so
    // a movie category rendered as a series category (or vice versa) is
    // caught here rather than surfacing as a G9 ingest test putting movies
    // in a series's Channel Group.
    const scenario = xc({
      liveCategories: [{ id: 1, name: 'Live Cat' }],
      vodCategories: [{ id: 2, name: 'Vod Cat' }],
      seriesCategories: [{ id: 3, name: 'Series Cat' }],
    });
    expect(renderLiveCategories(scenario)).toEqual([{ category_id: '1', category_name: 'Live Cat' }]);
    expect(renderVodCategories(scenario)).toEqual([{ category_id: '2', category_name: 'Vod Cat' }]);
    expect(renderSeriesCategories(scenario)).toEqual([{ category_id: '3', category_name: 'Series Cat' }]);
  });
});

describe('live actions', () => {
  it('renders categories as { category_id, category_name }', () => {
    // apps/m3u/tasks.py, refresh_m3u_account_groups: category_id becomes
    // ChannelGroupM3UAccount.custom_properties['xc_id'] and category_name
    // becomes the ChannelGroup name. Nothing else is read.
    expect(renderLiveCategories(xc())).toEqual([{ category_id: '1', category_name: 'E2E' }]);
  });

  it('renders every field collect_xc_streams reads', () => {
    const [stream] = renderLiveStreams(xc(), null, { tvArchive: () => true }) as Record<string, unknown>[];
    expect(stream).toMatchObject({
      stream_id: 1,
      name: 'Fake Channel 1',
      category_id: '1',
      epg_channel_id: 'fake-1.e2e',
      stream_type: 'live',
      num: 1,
      is_adult: 0,
      tv_archive: 1,
      tv_archive_duration: expect.any(Number),
    });
    expect(stream).toHaveProperty('stream_icon');
    expect(stream).toHaveProperty('added');
    expect(stream).toHaveProperty('custom_sid');
  });

  it('omits tv_archive entirely when the caller says so', () => {
    // The `no-tv-archive` fault. `str(stream.get("tv_archive", "0"))` means an
    // absent key is a real "no archive", which is what the self-heal pass in
    // rollup_channel_catchup_fields reacts to.
    const [stream] = renderLiveStreams(xc(), null, { tvArchive: () => false }) as Record<string, unknown>[];
    expect(stream).not.toHaveProperty('tv_archive');
    expect(stream).not.toHaveProperty('tv_archive_duration');
  });

  it('filters live streams by category_id when one is given', () => {
    const scenario = xc({
      liveCategories: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }],
      channels: [
        { id: 1, name: 'one', tvgId: 'one.e2e', logo: null, categoryId: 1 },
        { id: 2, name: 'two', tvgId: 'two.e2e', logo: null, categoryId: 2 },
      ],
    });
    const streams = renderLiveStreams(scenario, '2', { tvArchive: () => true }) as Record<string, unknown>[];
    expect(streams).toHaveLength(1);
    expect(streams[0].stream_id).toBe(2);
  });
});

describe('VOD actions', () => {
  it('renders every field process_movie_batch reads', () => {
    const [movie] = renderVodStreams(xc(), null) as Record<string, unknown>[];
    expect(movie).toMatchObject({
      stream_id: 1,
      name: 'Fake Movie 1',
      category_id: '1',
      container_extension: 'mp4',
      year: 2020,
    });
    // Read by process_movie_batch and stored verbatim as
    // M3UMovieRelation.custom_properties['basic_data'].
    for (const key of ['stream_icon', 'rating', 'plot', 'genre', 'duration_secs', 'added']) {
      expect(movie).toHaveProperty(key);
    }
  });

  it('omits is_adult unless it is meaningful', () => {
    // process_movie_batch only sets Movie.is_adult when the key is present,
    // deliberately, so a sparse provider cannot clear a flag another provider
    // set. Emitting a default 0 would defeat that.
    const [movie] = renderVodStreams(xc(), null) as Record<string, unknown>[];
    expect(movie).not.toHaveProperty('is_adult');
  });

  it('emits is_adult as 1/0 when the scenario declares it, and no key at all when it does not', () => {
    const scenario = xc({
      vod: [
        { id: 1, name: 'adult', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null, isAdult: true },
        { id: 2, name: 'clean', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null, isAdult: false },
        { id: 3, name: 'sparse', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
      ],
    });
    const [adult, clean, sparse] = renderVodStreams(scenario, null) as Record<string, unknown>[];
    expect(adult.is_adult).toBe(1);
    expect(clean.is_adult).toBe(0);
    // Not toBeUndefined(): that passes on both an absent key and a
    // present-but-undefined one, and only the former is what
    // process_movie_batch's "key is present" check cares about.
    expect(sparse).not.toHaveProperty('is_adult');
  });

  it('omits category_id for a categoryId: null movie, and emits it as a string otherwise', () => {
    const scenario = xc({
      vod: [
        { id: 1, name: 'uncategorized', year: 2020, categoryId: null, containerExtension: 'mp4', tmdbId: null, imdbId: null },
        { id: 2, name: 'categorized', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
      ],
    });
    const [uncategorized, categorized] = renderVodStreams(scenario, null) as Record<string, unknown>[];
    expect(uncategorized).not.toHaveProperty('category_id');
    expect(categorized.category_id).toBe('1');
  });

  it('excludes a categoryId: null movie from a category_id filter, but includes it when no filter is given', () => {
    const scenario = xc({
      vod: [
        { id: 1, name: 'uncategorized', year: 2020, categoryId: null, containerExtension: 'mp4', tmdbId: null, imdbId: null },
      ],
    });
    expect(renderVodStreams(scenario, '1')).toHaveLength(0);
    expect(renderVodStreams(scenario, null)).toHaveLength(1);
  });

  it('omits tmdb_id/imdb_id when null and includes them when the scenario declares them', () => {
    // The one field the pre-flight scan flagged as an IntegrityError risk:
    // Movie.tmdb_id/imdb_id are unique=True globally, so a shared default
    // across parallel workers would collide. A mutation dropping the
    // conditional spread (always omitting, or always emitting '') must fail
    // this test in both directions.
    const [sparse] = renderVodStreams(xc(), null) as Record<string, unknown>[];
    expect(sparse).not.toHaveProperty('tmdb_id');
    expect(sparse).not.toHaveProperty('imdb_id');

    const tagged = xc({
      vod: [
        {
          id: 1,
          name: 'Tagged Movie',
          year: 2021,
          categoryId: 1,
          containerExtension: 'mp4',
          tmdbId: 'tt123',
          imdbId: 'im456',
        },
      ],
    });
    const [movie] = renderVodStreams(tagged, null) as Record<string, unknown>[];
    expect(movie).toMatchObject({ tmdb_id: 'tt123', imdb_id: 'im456' });
  });

  it('filters vod streams by category_id when one is given', () => {
    const scenario = xc({
      vodCategories: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }],
      vod: [
        { id: 1, name: 'one', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
        { id: 2, name: 'two', year: 2020, categoryId: 2, containerExtension: 'mp4', tmdbId: null, imdbId: null },
      ],
    });
    const movies = renderVodStreams(scenario, '2') as Record<string, unknown>[];
    expect(movies).toHaveLength(1);
    expect(movies[0].stream_id).toBe(2);
  });

  it('renders vod_info with both info and movie_data', () => {
    // refresh_movie_advanced_data requires `'info' in vod_info` and reads
    // movie_data separately. A bare info dict is silently ignored.
    const info = renderVodInfo(xc(), 1)!;
    expect(info).toHaveProperty('info');
    expect(info).toHaveProperty('movie_data');
    expect((info.info as Record<string, unknown>).plot).toEqual(expect.any(String));
  });

  it('returns undefined for an unknown vod id', () => {
    expect(renderVodInfo(xc(), 999)).toBeUndefined();
  });

  it("replaces the whole default info object with a declared vodInfo, and still renders movie_data", () => {
    const vodInfo = { bitrate: 5000, video: { codec: 'h264' }, audio: { codec: 'aac' } };
    const scenario = xc({
      vod: [
        { id: 1, name: 'advanced', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null, vodInfo },
      ],
    });
    const info = renderVodInfo(scenario, 1)!;
    expect(info.info).toEqual(vodInfo);
    expect((info.movie_data as Record<string, unknown>).stream_id).toBe(1);
  });
});

describe('series actions', () => {
  it('renders every field process_series_batch reads, with the movie/series key skew', () => {
    const [series] = renderSeries(xc(), null) as Record<string, unknown>[];
    expect(series).toMatchObject({ series_id: 1, name: 'Fake Series 1', category_id: '1' });
    // Series use `cover` (not stream_icon), `plot` (not description) and
    // `releaseDate` (not release_date) first. That skew is real, and
    // reproducing it is what makes the ingest test meaningful.
    expect(series).toHaveProperty('cover');
    expect(series).toHaveProperty('plot');
    expect(series).toHaveProperty('releaseDate');
    expect(series).not.toHaveProperty('stream_icon');
  });

  it('filters series by category_id when one is given', () => {
    const scenario = xc({
      seriesCategories: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }],
      series: [
        { id: 1, name: 'one', categoryId: 1, seasons: [] },
        { id: 2, name: 'two', categoryId: 2, seasons: [] },
      ],
    });
    const series = renderSeries(scenario, '2') as Record<string, unknown>[];
    expect(series).toHaveLength(1);
    expect(series[0].series_id).toBe(2);
  });

  it('renders series_info with info and an object keyed by season number', () => {
    const info = renderSeriesInfo(xc(), 1)!;
    expect(info).toHaveProperty('info');
    const episodes = info.episodes as Record<string, unknown[]>;
    expect(Object.keys(episodes)).toEqual(['1']);
    expect(episodes['1'][0]).toMatchObject({
      id: '1',
      title: 'Fake Series 1 S01E01',
      episode_num: 1,
      container_extension: 'mp4',
    });
    expect((episodes['1'][0] as Record<string, unknown>).info).toEqual(
      expect.objectContaining({ plot: expect.any(String), duration_secs: expect.any(Number) })
    );
  });

  it('returns undefined for an unknown series id', () => {
    expect(renderSeriesInfo(xc(), 999)).toBeUndefined();
  });

  it('renders episodes as a positional array when seasonsAsArray is set, and as a keyed object otherwise', () => {
    const scenario = xc({
      series: [
        {
          id: 1,
          name: 'Array Series',
          categoryId: 1,
          seasonsAsArray: true,
          seasons: [
            { number: 0, episodes: [{ id: 1, title: 'S0E1', episodeNum: 1, containerExtension: 'mp4' }] },
            { number: 1, episodes: [{ id: 2, title: 'S1E1', episodeNum: 1, containerExtension: 'mp4' }] },
          ],
        },
      ],
    });
    const info = renderSeriesInfo(scenario, 1)!;
    // Array.isArray, not a shallow toEqual against a JSON round trip — a
    // JSON round trip would turn a contiguous-from-0 keyed object into
    // something that looks like an array too and hide the difference.
    expect(Array.isArray(info.episodes)).toBe(true);
    const episodes = info.episodes as unknown[];
    expect((episodes[0] as Record<string, unknown>[])[0]).toMatchObject({ title: 'S0E1' });
    expect((episodes[1] as Record<string, unknown>[])[0]).toMatchObject({ title: 'S1E1' });

    const keyed = renderSeriesInfo(xc(), 1)!;
    expect(Array.isArray(keyed.episodes)).toBe(false);
  });
});
