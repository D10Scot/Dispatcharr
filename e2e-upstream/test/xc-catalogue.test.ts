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
});
