import { describe, it, expect } from 'vitest';
import { ScenarioRegistry, parseScenarioRequest } from '../src/scenario.js';
import { BadRequestError } from '../src/errors.js';

describe('ScenarioRegistry', () => {
  it('generates the requested number of channels with distinct ids and tvg-ids', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({ channels: 3 });

    expect(scenario.channels).toHaveLength(3);
    expect(new Set(scenario.channels.map((c) => c.id)).size).toBe(3);
    expect(new Set(scenario.channels.map((c) => c.tvgId)).size).toBe(3);
  });

  it('defaults to unlimited connections, rate 1, and one channel', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({});

    expect(scenario.maxConnections).toBeNull();
    expect(scenario.rate).toBe(1);
    expect(scenario.channels).toHaveLength(1);
  });

  it('treats maxConnections 0 as reject-all, not as unlimited', () => {
    const registry = new ScenarioRegistry();
    // The distinction D10 rests on: null is unlimited, 0 is a real limit of
    // zero. `request.maxConnections || null` would silently collapse them and
    // disable every connection-limit test without failing anything.
    expect(registry.create({ maxConnections: 0 }).maxConnections).toBe(0);
  });

  it('accepts explicit channel specs verbatim, defaulting a missing categoryId', () => {
    // create() is a bypass of parseScenarioRequest — this pins that it does
    // its own categoryId defaulting too, so Scenario.channels[].categoryId
    // is never undefined regardless of which path built the scenario.
    const registry = new ScenarioRegistry();
    const scenario = registry.create({
      channels: [{ id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null }],
    });

    expect(scenario.channels).toEqual([
      { id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null, categoryId: 1 },
    ]);
  });

  it('defaults categoryId against a custom liveCategories list, and preserves an explicit categoryId, when create() is called directly', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({
      liveCategories: [{ id: 9, name: 'Custom' }],
      channels: [
        { id: 1, name: 'Defaulted', tvgId: 'a.e2e', logo: null },
        { id: 2, name: 'Explicit', tvgId: 'b.e2e', logo: null, categoryId: 5 },
      ],
    });

    expect(scenario.channels.map((c) => c.categoryId)).toEqual([9, 5]);
  });

  it('tags count-form channels, movies and series with the declared category, not the module default', () => {
    // F1 regression: defaultChannels/defaultMovies/defaultSeries used to
    // hardcode the module's id-1 default category regardless of what the
    // scenario declared, so get_live_streams/get_vod_streams/get_series
    // answered a category_id collect_xc_streams never resolved from
    // get_live_categories/get_vod_categories/get_series_categories — the
    // streams were silently dropped on ingest. This scenario declares a
    // non-default (id 5) category for all three catalogues and uses the
    // count form (a number, not an explicit array) throughout, which is
    // exactly the combination the previous behaviour got wrong.
    const registry = new ScenarioRegistry();
    // Three DIFFERENT ids, deliberately: with one shared id a generator wired
    // to the wrong list — defaultMovies(..., liveCategories[0].id) — would
    // still produce the asserted value and pass.
    const scenario = registry.create({
      liveCategories: [{ id: 5, name: 'Live Five' }],
      vodCategories: [{ id: 6, name: 'VOD Six' }],
      seriesCategories: [{ id: 7, name: 'Series Seven' }],
      channels: 1,
      vod: 1,
      series: 1,
    });

    expect(scenario.channels.map((c) => c.categoryId)).toEqual([5]);
    expect(scenario.vod.map((m) => m.categoryId)).toEqual([6]);
    expect(scenario.series.map((s) => s.categoryId)).toEqual([7]);
  });

  it('gives every scenario a distinct id and does not evict', () => {
    const registry = new ScenarioRegistry();
    const a = registry.create({});
    const b = registry.create({});

    expect(a.id).not.toBe(b.id);
    expect(registry.list()).toHaveLength(2);
    expect(registry.get(a.id)).toBe(a);
  });

  it('deletes on request and reports whether anything was deleted', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({});

    expect(registry.delete(scenario.id)).toBe(true);
    expect(registry.delete(scenario.id)).toBe(false);
    expect(registry.get(scenario.id)).toBeUndefined();
  });
});

describe('parseScenarioRequest', () => {
  it('rejects a non-numeric channels field, naming it, rather than silently producing zero channels', () => {
    expect(() => parseScenarioRequest({ channels: 'x' })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ channels: 'x' })).toThrow(/channels/);
  });

  it('rejects a channel spec object missing required fields, naming the field', () => {
    expect(() => parseScenarioRequest({ channels: [{}] })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ channels: [{}] })).toThrow(/channels/);
  });

  it('rejects a newline in a channel name, naming the field', () => {
    // A "\n" in `name` would inject an extra line into the rendered M3U,
    // which Dispatcharr would parse as an additional, attacker-controlled
    // channel entry.
    const request = { channels: [{ id: 1, name: 'x\n#EXTINF:-1,Injected', tvgId: 'x.e2e', logo: null }] };
    expect(() => parseScenarioRequest(request)).toThrow(BadRequestError);
    expect(() => parseScenarioRequest(request)).toThrow(/name/);
  });

  it('rejects a NUL byte in a channel tvgId, naming the field', () => {
    // A NUL would make the rendered XMLTV not well-formed.
    const request = { channels: [{ id: 1, name: 'x', tvgId: 'x\x00.e2e', logo: null }] };
    expect(() => parseScenarioRequest(request)).toThrow(BadRequestError);
    expect(() => parseScenarioRequest(request)).toThrow(/tvgId/);
  });

  it('rejects a negative maxConnections, naming the field', () => {
    expect(() => parseScenarioRequest({ maxConnections: -1 })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ maxConnections: -1 })).toThrow(/maxConnections/);
  });

  it('rejects a zero or negative rate, naming the field', () => {
    expect(() => parseScenarioRequest({ rate: 0 })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ rate: 0 })).toThrow(/rate/);
  });

  it('rejects a non-string username, naming the field', () => {
    expect(() => parseScenarioRequest({ username: 5 })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ username: 5 })).toThrow(/username/);
  });

  it('accepts the boundary values a careless validator breaks: maxConnections 0 and rate 0.5', () => {
    expect(parseScenarioRequest({ maxConnections: 0 }).maxConnections).toBe(0);
    expect(parseScenarioRequest({ rate: 0.5 }).rate).toBe(0.5);
  });
});

describe('parseScenarioRequest — channel id and credential validation', () => {
  const spec = (over = {}) => ({ id: 1, name: 'A', tvgId: 'a.e2e', logo: null, ...over });

  it('rejects a fractional channel id', () => {
    // `.../stream/1.5.ts` can never match the stream route's (\d+)\.ts, so
    // Dispatcharr 404s before the scenario is even resolved — the request
    // never reaches the scenario log, which makes it invisible to debug.
    expect(() => parseScenarioRequest({ channels: [spec({ id: 1.5 })] })).toThrow(
      /non-negative integer id/,
    );
  });

  it('rejects a negative channel id', () => {
    expect(() => parseScenarioRequest({ channels: [spec({ id: -1 })] })).toThrow(
      /non-negative integer id/,
    );
  });

  it('rejects duplicate channel ids, naming the offending id', () => {
    expect(() =>
      parseScenarioRequest({ channels: [spec({ id: 2 }), spec({ id: 2, name: 'B' })] }),
    ).toThrow(/more than one entry with id 2/);
  });

  it('accepts id 0 and distinct ids', () => {
    // 0 is a legitimate id and must survive: the same ?? vs || trap that
    // maxConnections has.
    const parsed = parseScenarioRequest({
      channels: [spec({ id: 0 }), spec({ id: 1, name: 'B', tvgId: 'b.e2e' })],
    });
    expect((parsed.channels as { id: number }[]).map((c) => c.id)).toEqual([0, 1]);
  });

  it('rejects a password with no username', () => {
    // credentialQuery returns '' without a username, so this would silently
    // create an unauthenticated scenario — and a test asserting that wrong
    // credentials are rejected would pass against a provider checking none.
    expect(() => parseScenarioRequest({ password: 'p' })).toThrow(/requires 'username'/);
  });

  it('accepts a username with no password', () => {
    // The mirror case is legitimate: an empty password is a real provider
    // configuration, and credentialQuery already emits password=''.
    expect(parseScenarioRequest({ username: 'u' }).username).toBe('u');
  });
});

describe('XC scenario declaration', () => {
  it('defaults to a non-XC scenario with no VOD or series catalogue', () => {
    const scenario = new ScenarioRegistry().create({});
    expect(scenario.xc).toBe(false);
    expect(scenario.vod).toEqual([]);
    expect(scenario.series).toEqual([]);
  });

  it('gives an XC scenario one movie, one series with one episode, and one category of each kind', () => {
    const scenario = new ScenarioRegistry().create({
      xc: true,
      username: 'u',
      password: 'p',
    });

    expect(scenario.liveCategories).toEqual([{ id: 1, name: 'E2E' }]);
    expect(scenario.vodCategories).toEqual([{ id: 1, name: 'E2E Movies' }]);
    expect(scenario.seriesCategories).toEqual([{ id: 1, name: 'E2E Series' }]);
    expect(scenario.vod).toHaveLength(1);
    expect(scenario.vod[0]).toMatchObject({ id: 1, name: 'Fake Movie 1', containerExtension: 'mp4' });
    expect(scenario.series).toHaveLength(1);
    expect(scenario.series[0].seasons).toEqual([
      {
        number: 1,
        episodes: [
          { id: 1, title: 'Fake Series 1 S01E01', episodeNum: 1, containerExtension: 'mp4' },
        ],
      },
    ]);
  });

  it('gives every default movie an explicit year', () => {
    // Movie identity across accounts falls back to (name, year) when there is
    // no TMDB or IMDB id, so a null year would make two workers' default
    // movies collide on (name, None) *and* would make the collision depend on
    // ingest-side year inference from the title. Declared, not inferred.
    const scenario = new ScenarioRegistry().create({ xc: true, username: 'u', password: 'p' });
    expect(scenario.vod[0].year).toEqual(expect.any(Number));
  });

  it('places every default channel in live category 1', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    expect(scenario.channels.map((c) => c.categoryId)).toEqual([1, 1]);
  });

  it('rejects xc: true without a username', () => {
    // credentialsMatch() returns true whenever username is undefined, so an
    // XC scenario with no credentials accepts anything — and every auth fault
    // written against it passes vacuously.
    expect(() => parseScenarioRequest({ xc: true })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ xc: true })).toThrow(/username/);
  });

  it('rejects xc: true with a username but no password', () => {
    // xcCredentialsMatch compares the password against `scenario.password ??
    // ''`, so an omitted password would be silently accepted at the door as
    // "empty password" — but the /live/ route's path form (`[^/]+`) can never
    // match an empty segment, so that scenario would be unservable the
    // moment a real client tried to stream from it.
    expect(() => parseScenarioRequest({ xc: true, username: 'u' })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ xc: true, username: 'u' })).toThrow(/password/);
  });

  it('rejects a duplicate movie id, series id, episode id or category id by name', () => {
    const dupes: [Record<string, unknown>, RegExp][] = [
      [{ vod: [{ id: 1, name: 'a' }, { id: 1, name: 'b' }] }, /vod/],
      [{ series: [{ id: 2, name: 'a', seasons: [] }, { id: 2, name: 'b', seasons: [] }] }, /series/],
      [{ vodCategories: [{ id: 3, name: 'a' }, { id: 3, name: 'b' }] }, /vodCategories/],
      [
        {
          series: [
            {
              id: 1,
              name: 'a',
              seasons: [
                { number: 1, episodes: [{ id: 9, title: 'x', episodeNum: 1 }] },
                { number: 2, episodes: [{ id: 9, title: 'y', episodeNum: 1 }] },
              ],
            },
          ],
        },
        /episode/,
      ],
    ];
    for (const [body, pattern] of dupes) {
      expect(() => parseScenarioRequest(body)).toThrow(pattern);
    }
  });

  it('rejects a duplicate episode id within one series, naming the series', () => {
    // Pins the existing within-a-series case (previously only covered by
    // the generic /episode/ pattern above) with an exact message, since the
    // message naming the collision is the point of this validation pass.
    expect(() =>
      parseScenarioRequest({
        series: [
          {
            id: 1,
            name: 'a',
            seasons: [
              { number: 1, episodes: [{ id: 9, title: 'x', episodeNum: 1 }] },
              { number: 2, episodes: [{ id: 9, title: 'y', episodeNum: 1 }] },
            ],
          },
        ],
      })
    ).toThrow("episode id 9 in 'series[1]' is already used by 'series[1]'");
  });

  it('rejects a duplicate episode id across two different series, naming both', () => {
    // apps/vod/models.py:294's unique_together on M3UEpisodeRelation is
    // ('m3u_account', 'stream_id') — unique per account, not per series —
    // and router.ts resolves playback with a flat scan across every
    // series' episodes, so a cross-series duplicate must be rejected too.
    expect(() =>
      parseScenarioRequest({
        series: [
          {
            id: 1,
            name: 'a',
            seasons: [{ number: 1, episodes: [{ id: 9, title: 'x', episodeNum: 1 }] }],
          },
          {
            id: 2,
            name: 'b',
            seasons: [{ number: 1, episodes: [{ id: 9, title: 'y', episodeNum: 1 }] }],
          },
        ],
      })
    ).toThrow("episode id 9 in 'series[2]' is already used by 'series[1]'");
  });

  it('rejects a movie or series whose categoryId names no declared category', () => {
    // Silently falling through to Uncategorized would make a typo'd
    // categoryId look like Dispatcharr's category gating misbehaving.
    expect(() =>
      parseScenarioRequest({ vodCategories: [{ id: 1, name: 'a' }], vod: [{ id: 1, name: 'm', categoryId: 7 }] })
    ).toThrow(/categoryId 7/);
  });

  it('rejects control characters in a movie, series, episode or category name', () => {
    expect(() => parseScenarioRequest({ vod: [{ id: 1, name: 'a\nb' }] })).toThrow(
      /control characters/
    );
  });

  // Ruling 1: a channels array through the *parser* (not create() called
  // directly) must default a missing categoryId to the first declared live
  // category — pinning the exact shape e2e/tests/seeded/upstream-ingest.spec.ts
  // sends, which predates G8 and supplies no categoryId at all.
  it('defaults a channel categoryId to the first declared live category via the parser', () => {
    const request = parseScenarioRequest({
      channels: [
        { id: 1, name: 'a', tvgId: 'a.e2e', logo: null },
        { id: 2, name: 'b', tvgId: 'b.e2e', logo: null },
      ],
    });
    expect((request.channels as { categoryId: number }[]).map((c) => c.categoryId)).toEqual([1, 1]);
  });

  it('preserves an explicit channel categoryId when it names a declared live category', () => {
    const request = parseScenarioRequest({
      liveCategories: [{ id: 1, name: 'a' }, { id: 2, name: 'b' }],
      channels: [{ id: 1, name: 'x', tvgId: 'x.e2e', logo: null, categoryId: 2 }],
    });
    expect((request.channels as { categoryId: number }[])[0].categoryId).toBe(2);
  });

  // Ruling 2: assertKnownCategory must also gate live channels, not only
  // movies and series.
  it('rejects a channel whose categoryId names no declared live category', () => {
    expect(() =>
      parseScenarioRequest({
        liveCategories: [{ id: 1, name: 'a' }],
        channels: [{ id: 1, name: 'x', tvgId: 'x.e2e', logo: null, categoryId: 9 }],
      })
    ).toThrow(/categoryId 9/);
  });

  // Ruling 3: the default categories must be reachable from the parser even
  // when nothing declares them — these are the happy paths that never throw,
  // so they exercise categoryId resolution and the year/containerExtension/
  // tmdbId/imdbId defaults that every other vod/series test bypasses by
  // throwing first.
  it('parses a movie with defaults for year, categoryId, containerExtension, tmdbId and imdbId', () => {
    const request = parseScenarioRequest({ vod: [{ id: 5, name: 'Solo Movie' }] });
    expect(request.vod).toEqual([
      { id: 5, name: 'Solo Movie', year: null, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ]);
  });

  it('parses a movie with every field explicit, validated against a declared vodCategory', () => {
    const request = parseScenarioRequest({
      vodCategories: [{ id: 1, name: 'Action' }, { id: 2, name: 'Comedy' }],
      vod: [
        { id: 1, name: 'Full', year: 1999, categoryId: 2, containerExtension: 'mkv', tmdbId: 'tt1', imdbId: 'im1' },
      ],
    });
    expect(request.vod).toEqual([
      { id: 1, name: 'Full', year: 1999, categoryId: 2, containerExtension: 'mkv', tmdbId: 'tt1', imdbId: 'im1' },
    ]);
  });

  it('parses a series with a default categoryId, one season and one episode', () => {
    const request = parseScenarioRequest({
      series: [
        {
          id: 1,
          name: 'S',
          seasons: [{ number: 1, episodes: [{ id: 1, title: 'E1', episodeNum: 1 }] }],
        },
      ],
    });
    expect(request.series).toEqual([
      {
        id: 1,
        name: 'S',
        categoryId: 1,
        seasons: [{ number: 1, episodes: [{ id: 1, title: 'E1', episodeNum: 1, containerExtension: 'mp4' }] }],
      },
    ]);
  });

  it('accepts a well-formed account override and rejects a malformed one', () => {
    expect(parseScenarioRequest({ account: { userInfo: { timezone: 'UTC' } } }).account).toEqual({
      userInfo: { timezone: 'UTC' },
    });
    expect(() => parseScenarioRequest({ account: 'nope' })).toThrow(/account/);
    expect(() => parseScenarioRequest({ account: { userInfo: 'nope' } })).toThrow(/account\.userInfo/);
  });

  it('rejects a non-boolean xc, naming the field', () => {
    expect(() => parseScenarioRequest({ xc: 'yes' })).toThrow(/xc/);
  });

  it('rejects an empty category array rather than crashing when something defaults against it', () => {
    // parseCategories used to accept [], and liveCategories[0]/categories[0]
    // then threw a bare TypeError indexing an empty array — a 500, not a 400
    // naming the field. Rejected unconditionally, whether or not anything
    // ends up defaulting against it.
    expect(() =>
      parseScenarioRequest({
        liveCategories: [],
        channels: [{ id: 1, name: 'a', tvgId: 'a.e2e', logo: null }],
      })
    ).toThrow(/liveCategories/);
    expect(() =>
      parseScenarioRequest({ vodCategories: [], vod: [{ id: 1, name: 'm' }] })
    ).toThrow(/vodCategories/);
    expect(() => parseScenarioRequest({ seriesCategories: [] })).toThrow(/seriesCategories/);
  });
});
