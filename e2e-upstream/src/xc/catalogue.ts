/**
 * The eight `player_api.php` action payloads.
 *
 * The endpoint list is bounded by `core/xtream_codes.Client`. The **field
 * set** is not: it is bounded by the consumers, `apps/m3u/tasks.py`
 * (`collect_xc_streams`) and `apps/vod/tasks.py` (`process_movie_batch`,
 * `process_series_batch`, `batch_process_episodes`,
 * `refresh_movie_advanced_data`). Satisfying the client alone yields a
 * provider whose refresh reports success and creates nothing.
 *
 * Category ids are emitted as **strings** because both consumers compare them
 * with `str(...)`: `collect_xc_streams` keys `enabled_category_ids` by
 * `str(props["xc_id"])`, and `process_movie_batch` looks up
 * `str(movie_data.get('category_id'))`. Stream and movie ids are emitted as
 * **numbers**, which is what real panels send and what `int()` accepts.
 *
 * No `parent_id` on categories: nothing in Dispatcharr reads it, and
 * `CategorySpec` (Task 1) has no such field to source it from.
 */

import type { CategorySpec, MovieSpec, Scenario, SeasonSpec, SeriesSpec } from '../scenario.js';

/** Days of archive a channel advertises when `tv_archive` is on. */
export const DEFAULT_ARCHIVE_DAYS = 7;
/** Seconds; short, finite, and consistent with the VOD asset we actually serve. */
const MOVIE_DURATION_SECS = 5;

function renderCategories(categories: CategorySpec[]): unknown[] {
  return categories.map((category) => ({
    category_id: String(category.id),
    category_name: category.name,
  }));
}

export function renderLiveCategories(scenario: Scenario): unknown[] {
  return renderCategories(scenario.liveCategories);
}

export function renderVodCategories(scenario: Scenario): unknown[] {
  return renderCategories(scenario.vodCategories);
}

export function renderSeriesCategories(scenario: Scenario): unknown[] {
  return renderCategories(scenario.seriesCategories);
}

export interface LiveStreamOptions {
  /** False omits `tv_archive`/`tv_archive_duration` entirely (the `no-tv-archive` fault). */
  tvArchive(channelId: number): boolean;
}

export function renderLiveStreams(
  scenario: Scenario,
  categoryId: string | null,
  options: LiveStreamOptions
): unknown[] {
  return scenario.channels
    .filter((channel) => categoryId === null || String(channel.categoryId) === categoryId)
    .map((channel) => {
      const archive = options.tvArchive(channel.id);
      return {
        num: channel.id,
        name: channel.name,
        stream_type: 'live',
        stream_id: channel.id,
        stream_icon: channel.logo ?? '',
        epg_channel_id: channel.tvgId,
        added: '0',
        category_id: String(channel.categoryId),
        custom_sid: '',
        is_adult: 0,
        // `direct_source` is deliberately absent: collect_xc_streams builds
        // the playback URL itself from server_url and never reads it.
        ...(archive ? { tv_archive: 1, tv_archive_duration: DEFAULT_ARCHIVE_DAYS } : {}),
      };
    });
}

function movieEntry(movie: MovieSpec): Record<string, unknown> {
  return {
    num: movie.id,
    name: movie.name,
    stream_type: 'movie',
    stream_id: movie.id,
    stream_icon: '',
    rating: '7.5',
    rating_5based: 3.75,
    added: '0',
    ...(movie.categoryId === null ? {} : { category_id: String(movie.categoryId) }),
    container_extension: movie.containerExtension,
    plot: `${movie.name} — e2e fixture`,
    genre: 'E2E',
    duration_secs: MOVIE_DURATION_SECS,
    year: movie.year,
    ...(movie.tmdbId === null ? {} : { tmdb_id: movie.tmdbId }),
    ...(movie.imdbId === null ? {} : { imdb_id: movie.imdbId }),
    // `is_adult` is deliberately absent unless a scenario declares it:
    // process_movie_batch only writes Movie.is_adult when the key is present,
    // so that a sparse provider cannot clear a flag another provider set,
    // unless the scenario declares `isAdult`.
    ...(movie.isAdult === undefined ? {} : { is_adult: movie.isAdult ? 1 : 0 }),
  };
}

export function renderVodStreams(scenario: Scenario, categoryId: string | null): unknown[] {
  return scenario.vod
    .filter(
      (movie) =>
        categoryId === null ||
        (movie.categoryId !== null && String(movie.categoryId) === categoryId),
    )
    .map(movieEntry);
}

export function renderVodInfo(
  scenario: Scenario,
  vodId: number
): Record<string, unknown> | undefined {
  const movie = scenario.vod.find((m) => m.id === vodId);
  if (!movie) return undefined;
  return {
    info: movie.vodInfo ?? {
      plot: `${movie.name} — e2e fixture, detailed`,
      genre: 'E2E',
      rating: '7.5',
      duration_secs: MOVIE_DURATION_SECS,
      releasedate: movie.year === null ? '' : `${movie.year}-01-01`,
      director: 'E2E Director',
      actors: 'E2E Actor',
      backdrop_path: [],
      youtube_trailer: '',
      ...(movie.tmdbId === null ? {} : { tmdb_id: movie.tmdbId }),
      ...(movie.imdbId === null ? {} : { imdb_id: movie.imdbId }),
    },
    movie_data: movieEntry(movie),
  };
}

function seriesEntry(series: SeriesSpec): Record<string, unknown> {
  return {
    num: series.id,
    series_id: series.id,
    name: series.name,
    // `cover`, not `stream_icon`; `plot`, not `description`; `releaseDate`
    // before `release_date`. process_series_batch reads these keys and not
    // the movie ones — the skew is the product's, and reproducing it is the
    // point.
    cover: '',
    plot: `${series.name} — e2e fixture`,
    genre: 'E2E',
    rating: '8.0',
    releaseDate: '2020-01-01',
    last_modified: '0',
    category_id: String(series.categoryId),
    episode_run_time: '5',
  };
}

export function renderSeries(scenario: Scenario, categoryId: string | null): unknown[] {
  return scenario.series
    .filter((series) => categoryId === null || String(series.categoryId) === categoryId)
    .map(seriesEntry);
}

export function renderSeriesInfo(
  scenario: Scenario,
  seriesId: number
): Record<string, unknown> | undefined {
  const series = scenario.series.find((s) => s.id === seriesId);
  if (!series) return undefined;

  function renderSeason(season: SeasonSpec): unknown[] {
    return season.episodes.map((episode) => ({
      // A string, matching real panels and matching
      // `str(episode_data.get('id'))` on the ingest side.
      id: String(episode.id),
      episode_num: episode.episodeNum,
      title: episode.title,
      container_extension: episode.containerExtension,
      info: {
        plot: `${episode.title} — e2e fixture`,
        rating: '7.0',
        duration_secs: MOVIE_DURATION_SECS,
        air_date: '2020-01-01',
        movie_image: '',
        backdrop_path: [],
      },
    }));
  }

  // Keyed by season number by default, which is what a PHP panel's
  // json_encode produces for a non-contiguous array. When the scenario
  // declares `seasonsAsArray`, batch_process_episodes also accepts a JSON
  // array indexed by position — the door (`parseSeries`) has already checked
  // `seasons[i].number === i`, so the two shapes carry the same information.
  const episodes = series.seasonsAsArray
    ? series.seasons.map(renderSeason)
    : Object.fromEntries(series.seasons.map((season) => [String(season.number), renderSeason(season)]));

  return {
    info: {
      name: series.name,
      plot: `${series.name} — e2e fixture, detailed`,
      genre: 'E2E',
      rating: '8.0',
      releaseDate: '2020-01-01',
    },
    episodes,
  };
}
