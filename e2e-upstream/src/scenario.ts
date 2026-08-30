import { randomUUID } from 'node:crypto';
import { BadRequestError } from './errors.js';

export interface ChannelSpec {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
  /**
   * The XC live category this channel belongs to. Optional on input:
   * `parseScenarioRequest` defaults it to the first declared live category's
   * id (1 when `liveCategories` is not declared, which is `DEFAULT_LIVE_CATEGORY`
   * — the same category the M3U playlist's existing `group-title="E2E"` names),
   * so every pre-G8 scenario that supplies a `channels` array without a
   * `categoryId` keeps working unchanged. A caller that bypasses the parser
   * (constructs a `Scenario` via `ScenarioRegistry.create` directly with an
   * explicit `channels` array) does not get this default — only
   * `parseScenarioRequest` applies it.
   */
  categoryId?: number;
}

/**
 * A `ChannelSpec` after category resolution. Every consumer of
 * `Scenario.channels` — the playlist/XMLTV renderers and the XC route
 * handlers built in later tasks — needs a concrete `categoryId`, never
 * `undefined` silently widened to the string `"undefined"` at render time.
 * `ChannelSpec.categoryId` stays optional because that field also types the
 * *input* shape (`ScenarioRequest.channels`), where omitting it is the
 * normal case; both `parseScenarioRequest` and `ScenarioRegistry.create`
 * resolve it before it reaches a `Scenario`.
 */
export type ResolvedChannelSpec = ChannelSpec & { categoryId: number };

export interface CategorySpec {
  id: number;
  name: string;
}

export interface MovieSpec {
  id: number;
  name: string;
  /**
   * Always declared, never left to inference. With no TMDB or IMDB id,
   * `apps/vod/tasks.py` identifies a movie across *all* accounts by
   * `(name, year)` — so a null year both widens the cross-worker collision
   * and makes the row's identity depend on the ingest side's title parsing.
   */
  year: number | null;
  /**
   * `null` means "emit no `category_id` key at all" — the only way to route a
   * movie into Dispatcharr's own `Uncategorized` bucket through the product's
   * real path. `process_movie_batch` (`apps/vod/tasks.py`) looks the provider's
   * `category_id` up in a string-keyed map and falls through to
   * `categories['__uncategorized__']` when it is absent or unknown; there is no
   * other way in.
   *
   * Undefined still defaults to the first declared VOD category, exactly as
   * before — `null` is a deliberate declaration, not an omission.
   */
  categoryId: number | null;
  /** The extension in the playback URL, so it must match what we serve. */
  containerExtension: string;
  tmdbId: string | null;
  imdbId: string | null;
  /**
   * Emitted as `is_adult: 1`/`0` on the `get_vod_streams` entry, and **only
   * when declared**. `process_movie_batch` writes `Movie.is_adult` only when
   * the key is present (`apps/vod/tasks.py:534`, via
   * `parse_is_adult` in `apps/m3u/utils.py:25`), deliberately, so that a sparse
   * provider cannot clear a flag another provider set. Leaving this undefined
   * therefore reproduces a sparse provider; setting it reproduces one that
   * reports.
   */
  isAdult?: boolean;
  /**
   * **Replaces** — never merges with — the default `info` object
   * `renderVodInfo` builds for this movie. A merge could only ever *add* keys,
   * and the shape a test needs here is defined by what it *omits*: an advanced
   * payload carrying `bitrate`/`video`/`audio` and none of
   * `director`/`actors`/`youtube_trailer`/`backdrop_path` is what leaves
   * `Movie.custom_properties` at `None` after a successful advanced refresh
   * (`clean_custom_properties({})` returns `None`, `apps/vod/tasks.py:2132`).
   * `movie_data` is unaffected and still rendered from the movie entry.
   */
  vodInfo?: Record<string, unknown>;
}

export interface EpisodeSpec {
  id: number;
  title: string;
  episodeNum: number;
  containerExtension: string;
}

export interface SeasonSpec {
  number: number;
  episodes: EpisodeSpec[];
}

export interface SeriesSpec {
  id: number;
  name: string;
  categoryId: number;
  seasons: SeasonSpec[];
  /**
   * When true, `get_series_info` emits `episodes` as a **JSON array** indexed
   * by position rather than an object keyed by season number — what a PHP
   * panel's `json_encode` produces when the season keys happen to be
   * contiguous from 0. `batch_process_episodes` (`apps/vod/tasks.py:1387`)
   * accepts both and uses the key *or the index* as the season number, so
   * season `0` is real under this shape and unreachable under the other.
   *
   * The door requires `seasons[i].number === i` when this is set, so the
   * declared season number and the index a client will infer can never
   * disagree.
   */
  seasonsAsArray?: boolean;
}

/**
 * Per-scenario overrides merged over the defaults in `src/xc/envelope.ts`.
 * Deliberately untyped beyond `Record<string, unknown>`: a test that wants
 * to see what Dispatcharr does with a garbage `exp_date` or an unknown
 * `timezone` must be able to send exactly that.
 */
export interface AccountOverrides {
  userInfo?: Record<string, unknown>;
  serverInfo?: Record<string, unknown>;
}

export interface ScenarioRequest {
  channels?: number | ChannelSpec[];
  username?: string;
  password?: string;
  maxConnections?: number;
  rate?: number;
  xc?: boolean;
  liveCategories?: CategorySpec[];
  vodCategories?: CategorySpec[];
  seriesCategories?: CategorySpec[];
  vod?: number | MovieSpec[];
  series?: number | SeriesSpec[];
  account?: AccountOverrides;
}

export interface Scenario {
  id: string;
  channels: ResolvedChannelSpec[];
  username?: string;
  password?: string;
  /** null = unlimited. 0 is a real limit meaning reject everything. */
  maxConnections: number | null;
  rate: number;
  /** When false, every XC route 404s for this scenario. */
  xc: boolean;
  liveCategories: CategorySpec[];
  vodCategories: CategorySpec[];
  seriesCategories: CategorySpec[];
  vod: MovieSpec[];
  series: SeriesSpec[];
  account: AccountOverrides;
}

const DEFAULT_LIVE_CATEGORY: CategorySpec = { id: 1, name: 'E2E' };
const DEFAULT_VOD_CATEGORY: CategorySpec = { id: 1, name: 'E2E Movies' };
const DEFAULT_SERIES_CATEGORY: CategorySpec = { id: 1, name: 'E2E Series' };

/**
 * Fixed, not derived from the clock: a year that changed between two runs
 * would change a movie's cross-account identity key and make a rerun against
 * a non-reset container create a second Movie row instead of matching the
 * first.
 */
const DEFAULT_MOVIE_YEAR = 2020;

// `categoryId` is always the caller's resolved `categories[0].id` — never
// the module default constants directly — so a scenario that declares its
// own `liveCategories`/`vodCategories`/`seriesCategories` and uses the count
// form (`channels: 2`, not an explicit array) still gets streams tagged with
// a category `get_live_categories`/`get_vod_categories`/`get_series_categories`
// actually advertised. Passing the module constant here silently emptied
// `collect_xc_streams`'s ingest whenever the declared categories didn't
// happen to be id 1 (see the F1 fix note in the final review).
function defaultChannels(count: number, categoryId: number): ResolvedChannelSpec[] {
  return Array.from({ length: count }, (_unused, index) => {
    const n = index + 1;
    return {
      id: n,
      name: `Fake Channel ${n}`,
      tvgId: `fake-${n}.e2e`,
      // example.invalid is reserved by RFC 2606 and can never resolve, so a
      // logo URL cannot accidentally make a real network request.
      logo: `https://example.invalid/logo-${n}.png`,
      categoryId,
    };
  });
}

function defaultMovies(count: number, categoryId: number): MovieSpec[] {
  return Array.from({ length: count }, (_unused, index) => {
    const n = index + 1;
    return {
      id: n,
      name: `Fake Movie ${n}`,
      year: DEFAULT_MOVIE_YEAR,
      categoryId,
      containerExtension: 'mp4',
      tmdbId: null,
      imdbId: null,
    };
  });
}

function defaultSeries(count: number, categoryId: number): SeriesSpec[] {
  return Array.from({ length: count }, (_unused, index) => {
    const n = index + 1;
    return {
      id: n,
      name: `Fake Series ${n}`,
      categoryId,
      seasons: [
        {
          number: 1,
          episodes: [
            {
              id: n,
              title: `Fake Series ${n} S01E01`,
              episodeNum: 1,
              containerExtension: 'mp4',
            },
          ],
        },
      ],
    };
  });
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isChannelSpec(value: unknown): value is ChannelSpec {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    // A non-negative integer, matching `parseFaultRequest`'s `channel`. A
    // fractional or negative id renders a playlist URL like
    // `.../stream/1.5.ts`, which can never match the stream route's
    // `(\d+)\.ts` — Dispatcharr gets a 404 that fires *before* the scenario
    // is resolved, so it is not even written to the scenario log.
    isNonNegativeInteger(v.id) &&
    typeof v.name === 'string' &&
    typeof v.tvgId === 'string' &&
    (typeof v.logo === 'string' || v.logo === null) &&
    (v.categoryId === undefined || isNonNegativeInteger(v.categoryId))
  );
}

// C0 controls plus DEL. These are the characters that corrupt the
// *structure* of the M3U (a "\n" turns one channel entry into an injected
// second one) or the XMLTV (a NUL makes the document not well-formed). They
// are rejected here, at the door, rather than escaped at render time,
// because `playlist.ts` and `xmltv.ts` must stay free to emit otherwise
// ugly-but-legal content (e.g. an unescaped double quote) for tests that
// want an awkward-but-realistic upstream. A test that wants a deliberately
// malformed document needs an explicit mechanism for it, not one smuggled in
// through a channel name.
const CONTROL_CHARS = /[\x00-\x1F\x7F]/;

function assertNoControlChars(value: string, field: string): void {
  if (CONTROL_CHARS.test(value)) {
    throw new BadRequestError(
      `'${field}' must not contain control characters (e.g. newlines or NUL)`,
    );
  }
}

function parseCategories(value: unknown, field: string): CategorySpec[] {
  if (!Array.isArray(value)) {
    throw new BadRequestError(`'${field}' must be an array of { id, name }`);
  }
  if (value.length === 0) {
    // Every channel, movie and series that omits a categoryId defaults to
    // `${field}[0].id` — an explicit empty array leaves nothing to default
    // against. Without this check that indexes `[0]` on an empty array,
    // which throws a bare TypeError that `server.ts` turns into an opaque
    // 500, not a 400 naming this field.
    throw new BadRequestError(`'${field}' must declare at least one category`);
  }
  const ids = new Set<number>();
  return value.map((entry) => {
    if (typeof entry !== 'object' || entry === null) {
      throw new BadRequestError(`'${field}' entries must be objects with an id and a name`);
    }
    const v = entry as Record<string, unknown>;
    if (!isNonNegativeInteger(v.id) || typeof v.name !== 'string') {
      throw new BadRequestError(
        `'${field}' entries must each have a non-negative integer id and a string name`,
      );
    }
    if (ids.has(v.id)) {
      throw new BadRequestError(`'${field}' contains more than one entry with id ${v.id}`);
    }
    ids.add(v.id);
    assertNoControlChars(v.name, `${field}.name`);
    return { id: v.id, name: v.name };
  });
}

/**
 * Checked for every live channel as well as every movie and series: a
 * channel naming an undeclared live category would otherwise be accepted
 * and then silently unlistable in Dispatcharr, which is exactly the
 * confusion this validate-at-the-door pass exists to prevent.
 */
function assertKnownCategory(categoryId: number, categories: CategorySpec[], field: string): void {
  if (!categories.some((c) => c.id === categoryId)) {
    // Falling through to Dispatcharr's "Uncategorized" bucket would make a
    // typo here read as the product's category gating misbehaving — the
    // exact confusion this validate-at-the-door pass exists to prevent.
    throw new BadRequestError(
      `'${field}' references categoryId ${categoryId}, which no declared category has`,
    );
  }
}

function parseSeasons(
  value: unknown,
  field: string,
  seriesField: string,
  episodeIds: Map<number, string>,
): SeasonSpec[] {
  if (!Array.isArray(value)) {
    throw new BadRequestError(`'${field}' must be an array of { number, episodes }`);
  }
  return value.map((entry) => {
    if (typeof entry !== 'object' || entry === null) {
      throw new BadRequestError(`'${field}' entries must be objects with a number and episodes`);
    }
    const v = entry as Record<string, unknown>;
    if (!isNonNegativeInteger(v.number)) {
      throw new BadRequestError(`'${field}' entries must each have a non-negative integer number`);
    }
    if (!Array.isArray(v.episodes)) {
      throw new BadRequestError(`'${field}[${v.number}].episodes' must be an array`);
    }
    const episodes = v.episodes.map((episodeEntry) => {
      if (typeof episodeEntry !== 'object' || episodeEntry === null) {
        throw new BadRequestError(`'${field}[${v.number}].episodes' entries must be objects`);
      }
      const e = episodeEntry as Record<string, unknown>;
      if (!isNonNegativeInteger(e.id)) {
        throw new BadRequestError(
          `'${field}[${v.number}].episodes' entries must each have a non-negative integer id`,
        );
      }
      if (episodeIds.has(e.id)) {
        throw new BadRequestError(
          `episode id ${e.id} in '${seriesField}' is already used by '${episodeIds.get(e.id)}'; episode ids must be unique across the whole scenario, not just within one series`,
        );
      }
      episodeIds.set(e.id, seriesField);
      if (typeof e.title !== 'string') {
        throw new BadRequestError(`'${field}[${v.number}].episodes' entries must each have a string title`);
      }
      assertNoControlChars(e.title, `${field}.episode.title`);
      if (!Number.isInteger(e.episodeNum)) {
        throw new BadRequestError(
          `'${field}[${v.number}].episodes' entries must each have an integer episodeNum`,
        );
      }
      if (e.containerExtension !== undefined && typeof e.containerExtension !== 'string') {
        throw new BadRequestError(
          `'${field}[${v.number}].episodes' containerExtension must be a string`,
        );
      }
      return {
        id: e.id,
        title: e.title,
        episodeNum: e.episodeNum as number,
        containerExtension: (e.containerExtension as string | undefined) ?? 'mp4',
      };
    });
    return { number: v.number, episodes };
  });
}

function parseMovies(value: unknown, categories: CategorySpec[], field: string): MovieSpec[] {
  if (!Array.isArray(value)) {
    throw new BadRequestError(`'${field}' must be an array of movie specs`);
  }
  const ids = new Set<number>();
  return value.map((entry) => {
    if (typeof entry !== 'object' || entry === null) {
      throw new BadRequestError(`'${field}' entries must be objects`);
    }
    const v = entry as Record<string, unknown>;
    if (!isNonNegativeInteger(v.id)) {
      throw new BadRequestError(`'${field}' entries must each have a non-negative integer id`);
    }
    if (ids.has(v.id)) {
      throw new BadRequestError(`'${field}' contains more than one entry with id ${v.id}; ids must be unique`);
    }
    ids.add(v.id);
    if (typeof v.name !== 'string') {
      throw new BadRequestError(`'${field}' entries must each have a string name`);
    }
    assertNoControlChars(v.name, `${field}.name`);

    if (v.year !== undefined && v.year !== null && !Number.isInteger(v.year)) {
      throw new BadRequestError(`'${field}' entry '${v.name}' year must be a number or null`);
    }
    const year = v.year === undefined ? null : (v.year as number | null);

    const categoryId = v.categoryId === undefined ? categories[0].id : v.categoryId;
    if (categoryId !== null) {
      if (!isNonNegativeInteger(categoryId)) {
        throw new BadRequestError(
          `'${field}' entry '${v.name}' categoryId must be a non-negative integer or null`,
        );
      }
      assertKnownCategory(categoryId, categories, `${field}.categoryId`);
    }

    if (v.containerExtension !== undefined && typeof v.containerExtension !== 'string') {
      throw new BadRequestError(`'${field}' entry '${v.name}' containerExtension must be a string`);
    }
    const containerExtension = (v.containerExtension as string | undefined) ?? 'mp4';

    if (v.tmdbId !== undefined && v.tmdbId !== null && typeof v.tmdbId !== 'string') {
      throw new BadRequestError(`'${field}' entry '${v.name}' tmdbId must be a string or null`);
    }
    const tmdbId = v.tmdbId === undefined ? null : (v.tmdbId as string | null);

    if (v.imdbId !== undefined && v.imdbId !== null && typeof v.imdbId !== 'string') {
      throw new BadRequestError(`'${field}' entry '${v.name}' imdbId must be a string or null`);
    }
    const imdbId = v.imdbId === undefined ? null : (v.imdbId as string | null);

    if (v.isAdult !== undefined && typeof v.isAdult !== 'boolean') {
      throw new BadRequestError(`'${field}' entry '${v.name}' isAdult must be a boolean`);
    }
    const isAdult = v.isAdult as boolean | undefined;

    if (
      v.vodInfo !== undefined &&
      (typeof v.vodInfo !== 'object' || v.vodInfo === null || Array.isArray(v.vodInfo))
    ) {
      throw new BadRequestError(
        `'${field}' entry '${v.name}' vodInfo must be an object; it replaces the whole 'info' payload of get_vod_info`,
      );
    }
    const vodInfo = v.vodInfo as Record<string, unknown> | undefined;

    return {
      id: v.id,
      name: v.name,
      year,
      categoryId,
      containerExtension,
      tmdbId,
      imdbId,
      ...(isAdult === undefined ? {} : { isAdult }),
      ...(vodInfo === undefined ? {} : { vodInfo }),
    };
  });
}

function parseSeries(value: unknown, categories: CategorySpec[], field: string): SeriesSpec[] {
  if (!Array.isArray(value)) {
    throw new BadRequestError(`'${field}' must be an array of series specs`);
  }
  const ids = new Set<number>();
  // Episode-id uniqueness is enforced across the *whole scenario*, not per
  // series: `apps/vod/models.py:294`'s `unique_together` on
  // `M3UEpisodeRelation` is `('m3u_account', 'stream_id')` — an episode
  // stream id is unique per account, not per series — and the fake
  // provider's own `/series/<u>/<p>/<id>.<ext>` playback route
  // (`xc/router.ts`) resolves an episode id with a flat scan across every
  // series' episodes, so a cross-series duplicate would make the route's
  // answer depend on array order. Accepting one at the door would produce a
  // scenario that reads as a Dispatcharr ingest bug once refreshed, rather
  // than the fixture typo it actually is. Declared here so every series'
  // `parseSeasons` call shares one Map, rather than inside `parseSeasons`
  // where it was reset per series.
  const episodeIds = new Map<number, string>();
  return value.map((entry) => {
    if (typeof entry !== 'object' || entry === null) {
      throw new BadRequestError(`'${field}' entries must be objects`);
    }
    const v = entry as Record<string, unknown>;
    if (!isNonNegativeInteger(v.id)) {
      throw new BadRequestError(`'${field}' entries must each have a non-negative integer id`);
    }
    if (ids.has(v.id)) {
      throw new BadRequestError(`'${field}' contains more than one entry with id ${v.id}; ids must be unique`);
    }
    ids.add(v.id);
    if (typeof v.name !== 'string') {
      throw new BadRequestError(`'${field}' entries must each have a string name`);
    }
    assertNoControlChars(v.name, `${field}.name`);

    const categoryId = v.categoryId === undefined ? categories[0].id : v.categoryId;
    if (!isNonNegativeInteger(categoryId)) {
      throw new BadRequestError(`'${field}' entry '${v.name}' categoryId must be a non-negative integer`);
    }
    assertKnownCategory(categoryId, categories, `${field}.categoryId`);

    const seriesField = `${field}[${v.id}]`;
    const seasons = parseSeasons(v.seasons, `${seriesField}.seasons`, seriesField, episodeIds);

    if (v.seasonsAsArray !== undefined && typeof v.seasonsAsArray !== 'boolean') {
      throw new BadRequestError(`'${field}' entry '${v.name}' seasonsAsArray must be a boolean`);
    }
    if (v.seasonsAsArray === true) {
      seasons.forEach((season, index) => {
        if (season.number !== index) {
          // Under the array shape the *index* is the season number the client
          // infers. Accepting a mismatch would produce a scenario whose
          // declared season numbers and ingested season numbers differ for a
          // reason no failure message could explain.
          throw new BadRequestError(
            `'${field}' entry '${v.name}' declares seasonsAsArray but seasons[${index}].number is ${season.number}; under the array shape the position IS the season number, so they must match`,
          );
        }
      });
    }

    return {
      id: v.id,
      name: v.name,
      categoryId,
      seasons,
      ...(v.seasonsAsArray === undefined ? {} : { seasonsAsArray: v.seasonsAsArray as boolean }),
    };
  });
}

/**
 * Validates a parsed JSON body field-by-field before it ever reaches
 * `ScenarioRegistry.create`, naming the offending field in the thrown
 * `BadRequestError`. Without this, `{ "channels": "x" }` would fall through
 * `Array.isArray` to `defaultChannels(NaN)` and silently produce zero
 * channels — the failure mode this goal exists to eliminate: a later test
 * author sees "expected 3 channels, got 0" and suspects Dispatcharr's
 * parser rather than their own typo in the scenario request.
 */
export function parseScenarioRequest(body: Record<string, unknown>): ScenarioRequest {
  const request: ScenarioRequest = {};

  // Categories are parsed first: channels, movies and series below all
  // validate their `categoryId` against these, and default to the first
  // declared category when they don't supply one. Falling back to the
  // module defaults keeps that default reachable even when the caller
  // declares no categories at all — `ScenarioRegistry.create` applies the
  // same fallback for callers that bypass the parser entirely.
  const liveCategories =
    body.liveCategories !== undefined
      ? parseCategories(body.liveCategories, 'liveCategories')
      : [DEFAULT_LIVE_CATEGORY];
  if (body.liveCategories !== undefined) request.liveCategories = liveCategories;

  const vodCategories =
    body.vodCategories !== undefined
      ? parseCategories(body.vodCategories, 'vodCategories')
      : [DEFAULT_VOD_CATEGORY];
  if (body.vodCategories !== undefined) request.vodCategories = vodCategories;

  const seriesCategories =
    body.seriesCategories !== undefined
      ? parseCategories(body.seriesCategories, 'seriesCategories')
      : [DEFAULT_SERIES_CATEGORY];
  if (body.seriesCategories !== undefined) request.seriesCategories = seriesCategories;

  if (body.channels !== undefined) {
    if (Array.isArray(body.channels)) {
      if (!body.channels.every(isChannelSpec)) {
        throw new BadRequestError(
          "'channels' array entries must each have a non-negative integer id, string name, string tvgId, a logo that is a string or null, and (if present) a non-negative integer categoryId",
        );
      }
      // Duplicate ids emit two #EXTINF entries pointing at one stream URL,
      // and a later `channel: n` fault then applies to both — so the
      // scenario cannot express "fault one channel, leave its sibling
      // alone", which is what every failover test needs.
      const ids = new Set<number>();
      const channels: ResolvedChannelSpec[] = [];
      for (const channel of body.channels as ChannelSpec[]) {
        if (ids.has(channel.id)) {
          throw new BadRequestError(
            `'channels' contains more than one entry with id ${channel.id}; ids must be unique`,
          );
        }
        ids.add(channel.id);
        assertNoControlChars(channel.name, 'channels.name');
        assertNoControlChars(channel.tvgId, 'channels.tvgId');
        // Every pre-G8 scenario supplies channels without a categoryId; it
        // defaults to the first declared live category (1, unmodified) so
        // the M3U's `group-title="E2E"` stays what it always was.
        const categoryId = channel.categoryId ?? liveCategories[0].id;
        assertKnownCategory(categoryId, liveCategories, 'channels.categoryId');
        channels.push({ ...channel, categoryId });
      }
      request.channels = channels;
    } else if (isNonNegativeInteger(body.channels)) {
      request.channels = body.channels;
    } else {
      throw new BadRequestError(
        "'channels' must be a non-negative integer or an array of channel specs",
      );
    }
  }

  if (body.maxConnections !== undefined) {
    if (!isNonNegativeInteger(body.maxConnections)) {
      throw new BadRequestError("'maxConnections' must be a non-negative integer");
    }
    request.maxConnections = body.maxConnections;
  }

  if (body.rate !== undefined) {
    if (typeof body.rate !== 'number' || !(body.rate > 0)) {
      throw new BadRequestError("'rate' must be a number greater than 0");
    }
    request.rate = body.rate;
  }

  if (body.username !== undefined) {
    if (typeof body.username !== 'string') {
      throw new BadRequestError("'username' must be a string");
    }
    request.username = body.username;
  }

  if (body.password !== undefined) {
    if (typeof body.password !== 'string') {
      throw new BadRequestError("'password' must be a string");
    }
    request.password = body.password;
  }

  // `credentialQuery` returns '' when username is undefined, so a password
  // on its own would silently produce an unauthenticated scenario — and a
  // test asserting "wrong credentials are rejected" would pass against a
  // provider that never checks any.
  if (request.password !== undefined && request.username === undefined) {
    throw new BadRequestError("'password' requires 'username'; a password alone is never used");
  }

  if (body.vod !== undefined) {
    if (isNonNegativeInteger(body.vod)) {
      request.vod = body.vod;
    } else if (Array.isArray(body.vod)) {
      request.vod = parseMovies(body.vod, vodCategories, 'vod');
    } else {
      throw new BadRequestError("'vod' must be a non-negative integer or an array of movie specs");
    }
  }

  if (body.series !== undefined) {
    if (isNonNegativeInteger(body.series)) {
      request.series = body.series;
    } else if (Array.isArray(body.series)) {
      request.series = parseSeries(body.series, seriesCategories, 'series');
    } else {
      throw new BadRequestError("'series' must be a non-negative integer or an array of series specs");
    }
  }

  if (body.account !== undefined) {
    if (typeof body.account !== 'object' || body.account === null || Array.isArray(body.account)) {
      throw new BadRequestError("'account' must be an object with optional userInfo and serverInfo");
    }
    const account = body.account as Record<string, unknown>;
    if (
      account.userInfo !== undefined &&
      (typeof account.userInfo !== 'object' || account.userInfo === null || Array.isArray(account.userInfo))
    ) {
      throw new BadRequestError("'account.userInfo' must be an object");
    }
    if (
      account.serverInfo !== undefined &&
      (typeof account.serverInfo !== 'object' || account.serverInfo === null || Array.isArray(account.serverInfo))
    ) {
      throw new BadRequestError("'account.serverInfo' must be an object");
    }
    request.account = account as AccountOverrides;
  }

  if (body.xc !== undefined) {
    if (typeof body.xc !== 'boolean') {
      throw new BadRequestError("'xc' must be a boolean");
    }
    request.xc = body.xc;
  }

  // `credentialsMatch` treats an undefined username as "accept anything", so
  // an XC scenario without credentials would authenticate every request and
  // make `auth-failure` and `xc-auth-envelope` pass vacuously against it.
  // Both fields, not just `username`: `xcCredentialsMatch` compares the
  // password against `scenario.password ?? ''`, so an omitted password is
  // accepted at the door as "empty password" — but the `/live/` route's path
  // form (`[^/]+`) can never match an empty segment, so that scenario would
  // be unservable the moment a real client tried to stream from it. Validate
  // both requirements at the door, not discover the second one at the route.
  if (request.xc && (request.username === undefined || request.password === undefined)) {
    throw new BadRequestError(
      "'xc' requires both 'username' and 'password'; an XC provider with no credentials cannot reject any, and an empty password can never match the /live/ path form"
    );
  }

  return request;
}

export class ScenarioRegistry {
  private scenarios = new Map<string, Scenario>();

  create(request: ScenarioRequest): Scenario {
    // Computed before `channels`/`vod`/`series` below: a caller that
    // bypasses `parseScenarioRequest` and passes an explicit `channels`
    // array straight to `create` still needs every channel's `categoryId`
    // resolved, on pain of `Scenario.channels[].categoryId` being
    // `undefined` despite its type saying `number`. The count form
    // (`defaultChannels`/`defaultMovies`/`defaultSeries` below) needs the
    // same resolved list, for the same reason `parseScenarioRequest`
    // resolves `categoryId` against declared categories rather than the
    // module defaults — `categories[0].id` is by construction a member of
    // `categories`, so no `assertKnownCategory` call is needed for these
    // generated entries the way it is for caller-supplied ones.
    const liveCategories = request.liveCategories ?? [DEFAULT_LIVE_CATEGORY];
    const vodCategories = request.vodCategories ?? [DEFAULT_VOD_CATEGORY];
    const seriesCategories = request.seriesCategories ?? [DEFAULT_SERIES_CATEGORY];

    const channels: ResolvedChannelSpec[] = Array.isArray(request.channels)
      ? request.channels.map((channel) => ({
          ...channel,
          categoryId: channel.categoryId ?? liveCategories[0].id,
        }))
      : defaultChannels(request.channels ?? 1, liveCategories[0].id);

    const xc = request.xc ?? false;

    const scenario: Scenario = {
      id: randomUUID(),
      channels,
      username: request.username,
      password: request.password,
      // `?? null`, never `|| null`: 0 is a real limit and must survive.
      maxConnections: request.maxConnections ?? null,
      rate: request.rate ?? 1,
      xc,
      liveCategories,
      vodCategories,
      seriesCategories,
      // A non-XC scenario has no route that could serve a catalogue, so
      // materialising one by default would only be a way to trip over it
      // later.
      vod: Array.isArray(request.vod)
        ? request.vod
        : defaultMovies(request.vod ?? (xc ? 1 : 0), vodCategories[0].id),
      series: Array.isArray(request.series)
        ? request.series
        : defaultSeries(request.series ?? (xc ? 1 : 0), seriesCategories[0].id),
      account: request.account ?? {},
    };

    this.scenarios.set(scenario.id, scenario);
    return scenario;
  }

  get(id: string): Scenario | undefined {
    return this.scenarios.get(id);
  }

  list(): Scenario[] {
    return [...this.scenarios.values()];
  }

  delete(id: string): boolean {
    return this.scenarios.delete(id);
  }
}
