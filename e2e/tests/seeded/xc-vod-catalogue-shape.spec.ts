import { test, expect, xcQuery } from '../../fixtures';

/**
 * RULING R1 (see task-8-report.md): this file was originally
 * `xc-vod-empty.spec.ts`, written against a catalogue that no longer exists.
 * G8 (`e2e/tests/seeded/vod-catalogue-ingest.spec.ts`) seeds a real movie,
 * series and episode into the *same* `seeded` project via `seed.xcAccount`
 * with `enable_vod: true` (`account_type: 'XC'`, `is_active: true`) — exactly
 * the two conditions the four list views below filter on
 * (`apps/output/views.py:1174-1176`, `:1190`, `:1266-1268`, `:1285`) — and
 * nothing in `e2e/tests/seeded/` tears that down. So `toEqual([])` for those
 * four actions is not a description of a reachable state on a shared
 * instance; under parallel workers it is an ordering race against G8, not an
 * assertion.
 *
 * What this row is actually for, and can still prove on a catalogue that may
 * be empty, partially seeded, or fully seeded depending on run order: that
 * these six code paths — the ones every XC client asks on its first
 * connect — all answer, none of them 500, and the four list payloads are
 * well-formed. That's still real: an untested code path on a fresh instance
 * most often fails by 500ing, not by returning the wrong shape, and a
 * per-element key check over `body.entries()` is vacuously true against zero
 * rows, so it costs nothing when the catalogue happens to be empty and
 * catches a broken row shape when it isn't. G9 owns the assertions that the
 * *content* of a seeded catalogue is correct (see `COVERAGE.md`'s G9 row:
 * "G5 covers only the shape"). Because "vacuously true against zero rows" is
 * silent about which happened, the row count actually checked is recorded
 * as a test annotation rather than left for the reader to guess.
 *
 * Expected key sets below are read directly off the dict literals each view
 * function builds — these are hand-built dicts, not DRF serializers, so
 * there is no serializer class to derive from:
 *   - xc_get_vod_categories    apps/output/views.py:1180-1183
 *   - xc_get_vod_streams       apps/output/views.py:1222-1253
 *   - xc_get_series_categories apps/output/views.py:1272-1275
 *   - xc_get_series            apps/output/views.py:1311-1345
 *
 * The two detail actions are unaffected by R1 — `xc_get_series_info` and
 * `xc_get_vod_info` both `raise Http404()` for a missing or unknown id
 * regardless of what else is in the catalogue (apps/output/views.py:1619,
 * :1630, :1356, :1365) — and are asserted exactly as the original brief
 * specified.
 *
 * That 404 is ambiguous on this instance, though (issue #84):
 * `xc_get_user` (apps/output/views.py:364) resolves the account with
 * `get_object_or_404(User, username=...)` *before* any action-specific code
 * runs, so an unrecognised username 404s from every action, list actions
 * included, not just the two detail ones. A test that only ever asserts 404
 * here cannot tell "no such vod/series id" from "no such user" — if
 * `seed.xcUser` ever produced a user the server couldn't find, every case
 * below would go green without `xc_get_vod_info`/`xc_get_series_info` having
 * run at all. The detail-action test below asserts a positive control with
 * the same credentials first, precisely to rule that out. Any future test
 * asserting 404 on this surface needs the same disambiguation.
 */

const CATEGORY_KEYS = ['category_id', 'category_name', 'parent_id'];

const VOD_STREAM_KEYS = [
  'num', 'name', 'stream_type', 'stream_id', 'stream_icon', 'rating',
  'rating_5based', 'added', 'is_adult', 'tmdb_id', 'imdb_id', 'trailer',
  'plot', 'genre', 'year', 'director', 'cast', 'release_date',
  'category_id', 'category_ids', 'container_extension', 'custom_sid',
  'direct_source',
];

const SERIES_KEYS = [
  'num', 'name', 'series_id', 'cover', 'plot', 'cast', 'director', 'genre',
  'release_date', 'releaseDate', 'last_modified', 'rating', 'rating_5based',
  'backdrop_path', 'youtube_trailer', 'episode_run_time', 'category_id',
  'category_ids', 'tmdb_id', 'imdb_id',
];

const LIST_ACTIONS: Array<[action: string, expectedKeys: string[]]> = [
  ['get_vod_categories', CATEGORY_KEYS],
  ['get_vod_streams', VOD_STREAM_KEYS],
  ['get_series_categories', CATEGORY_KEYS],
  ['get_series', SERIES_KEYS],
];

test('the four XC list actions answer 200 with a well-formed array', { tag: '@contract' }, async ({
  seed,
  request,
}, testInfo) => {
  const user = await seed.xcUser({ user_level: 1 });

  for (const [action, expectedKeys] of LIST_ACTIONS) {
    const res = await request.get(`/player_api.php${xcQuery(user, { action })}`);
    expect(res.status(), action).toBe(200);

    const body = await res.json();
    expect(Array.isArray(body), `${action} body`).toBe(true);

    // Recorded rather than left implicit: "0 rows, key check never ran" and
    // "36 rows, key check ran 36 times" both make this assertion pass, and
    // look identical in a green run without this. Not an assertion — an
    // assertion that the array is non-empty would reintroduce the ordering
    // race against G8 that R1 removed toEqual([]) to avoid.
    testInfo.annotations.push({
      type: 'info',
      description: `${action}: checked ${body.length} row(s)`,
    });

    // Not optional: Array.isArray alone passes against [] AND against
    // garbage rows. Checking every present element's key set is what makes
    // this still fail on a malformed payload once the catalogue is seeded —
    // the whole point of keeping this assertion instead of `toEqual([])`.
    for (const [index, item] of body.entries()) {
      expect(
        Object.keys(item).sort(),
        `${action} row ${index}`
      ).toEqual([...expectedKeys].sort());
    }
  }
});

test('the two XC detail actions 404 rather than erroring', { tag: '@contract' }, async ({ seed, request }) => {
  const user = await seed.xcUser({ user_level: 1 });

  // Positive control (issue #84): `xc_get_user` resolves the username with
  // get_object_or_404 before any action runs, so an unrecognised username
  // 404s from every action — list actions included. Without this, a broken
  // `seed.xcUser` producing a user the server can't find would make every
  // case below pass while never reaching xc_get_vod_info/xc_get_series_info.
  // Proving this exact user gets a 200 from a list action first is what
  // turns "these 404" into "these 404 while this user resolves".
  const control = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_vod_categories' })}`
  );
  expect(control.status(), 'positive control: get_vod_categories for this user').toBe(200);

  const cases: Array<[string, Record<string, string | number>]> = [
    ['get_vod_info', {}],
    ['get_vod_info', { vod_id: 999999999 }],
    ['get_series_info', {}],
    ['get_series_info', { series_id: 999999999 }],
  ];

  for (const [action, extra] of cases) {
    const res = await request.get(
      `/player_api.php${xcQuery(user, { action, ...extra })}`
    );
    // 404, not 500. The distinction is the whole test: a 500 here is an
    // unhandled exception reaching a client, and it is what an untested code
    // path on a fresh instance most often produces.
    expect(res.status(), `${action} ${JSON.stringify(extra)}`).toBe(404);
  }
});
