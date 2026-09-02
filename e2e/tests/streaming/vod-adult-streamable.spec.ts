import { test, expect, xcQuery } from '../../fixtures';
import type { Movie, VodPage } from '../../fixtures';

// The non-inverted control for the test.fail() below ('an adult movie a user
// cannot list is not streamable by that user'): the premise is that a
// hide_adult_content user's get_vod_streams listing excludes the adult movie
// and includes the control movie, once both are seeded through a fresh XC
// scenario, a refresh-vod POST and the ingest wait for both movies to land.
// This file has exactly one other test — the pin below — and its entire
// seed-and-ingest sequence (upstream.scenario, the refresh-vod POST,
// waitFor.resource) sits inside that test.fail() block; no other test in
// this file performs that sequence outside one. A throw anywhere in it (a
// malformed scenario, a refresh-vod that never reaches 202, an ingest that
// times out) would be swallowed by the pin below as an "expected failure" of
// the whole test, since test.fail() is satisfied by ANY failure in its body,
// not specifically the streaming omission it exists to pin. This control
// repeats the identical two-movie setup outside test.fail() and asserts only
// the listing half, non-inverted, so a break in the seed-and-ingest premise
// surfaces here instead of vanishing into the pin's "expected failure". It
// does not stream anything — the streaming half is the pin's own subject.
test('an adult movie is unlistable for a hide_adult_content user and the control movie remains listable', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);

  const prefix = seed.generatedName('vodadultctl');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    vod: [
      {
        id: 501,
        name: `${prefix}-adult`,
        year: 2015,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
        isAdult: true,
      },
      {
        id: 502,
        name: `${prefix}-control`,
        year: 2016,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
      },
    ],
    series: 0,
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {})).status()).toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 2,
    { description: `both ${prefix} movies to be ingested`, timeoutMs: 120_000 }
  );
  const adultMovie = movies.results.find((m) => m.name === `${prefix}-adult`);
  const controlMovie = movies.results.find((m) => m.name === `${prefix}-control`);
  expect(adultMovie, `${prefix}-adult among the ingested movies`).toBeDefined();
  expect(controlMovie, `${prefix}-control among the ingested movies`).toBeDefined();

  const user = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  const listed = JSON.parse(
    await (await request.get(`/player_api.php${xcQuery(user, { action: 'get_vod_streams' })}`)).text()
  ) as { stream_id: number }[];
  expect(listed.map((s) => s.stream_id)).not.toContain(adultMovie!.id);
  expect(listed.map((s) => s.stream_id)).toContain(controlMovie!.id);
});

// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_vod_streams` and
// `xc_get_vod_info` (apps/output/views.py) filter `movie__is_adult=False`
// for a non-admin with hide_adult_content. `stream_xc_movie`,
// `stream_xc_episode` and `stream_vod` (apps/proxy/vod_proxy/views.py)
// apply no adult filter at all — so a movie this user cannot list is one
// they can still watch by asking for it by primary key.
//
// This is the VOD analogue of G5's live defect (stream_xc omitting the
// is_adult and hidden_from_output filters), on different functions with a
// different fix, so it is a separate issue: closing one does not close the
// other.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/110
//
// test.fail() caveat: it is satisfied by ANY failure in the body, guards
// included — so a broken premise, not just the intended assertion, would
// also read as "expected failure" and this test would go green while
// proving nothing. The premise below (that this user genuinely cannot list
// the adult movie, and genuinely can list the control movie) is asserted
// non-vacuously: the positive control (`toContain(controlMovie.id)`) fails
// on an empty or broken listing, so the absence assertion above it cannot
// be quietly passing on a listing that never worked at all. Verified with
// `--reporter=json` that this pin fails at the `not.toBe(200)` below, with
// both premise assertions passing — re-verify the same way after any edit
// here. This test's own body also performs the same seed-and-ingest
// sequence (the upstream scenario, the refresh-vod POST, and the ingest
// wait) that both the listing and streaming assertions below depend on —
// but inside this test.fail() block, which is satisfied by ANY failure, a
// broken seed or a stalled ingest would be swallowed as an "expected
// failure" just as readily as the intended streaming defect. The
// non-inverted control above ('an adult movie is unlistable for a
// hide_adult_content user and the control movie remains listable') repeats
// that same seed-and-ingest sequence outside test.fail() and is what
// actually guards it.
test.fail('an adult movie a user cannot list is not streamable by that user', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);

  const prefix = seed.generatedName('vodadult');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    vod: [
      {
        id: 501,
        name: `${prefix}-adult`,
        year: 2015,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
        isAdult: true,
      },
      {
        id: 502,
        name: `${prefix}-control`,
        year: 2016,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
      },
    ],
    series: 0,
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {})).status()).toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 2,
    { description: `both ${prefix} movies to be ingested`, timeoutMs: 120_000 }
  );
  const adultMovie = movies.results.find((m) => m.name === `${prefix}-adult`);
  const controlMovie = movies.results.find((m) => m.name === `${prefix}-control`);
  expect(adultMovie, `${prefix}-adult among the ingested movies`).toBeDefined();
  expect(controlMovie, `${prefix}-control among the ingested movies`).toBeDefined();

  // seed.xcUser() ignores an attempt to override xc_password, but not
  // user_level or custom_properties — this user is what the fixture calls a
  // "hide_adult_content" user.
  const user = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  // The premise, first, so a refusal below cannot mean anything else.
  const listed = JSON.parse(
    await (await request.get(`/player_api.php${xcQuery(user, { action: 'get_vod_streams' })}`)).text()
  ) as { stream_id: number }[];
  expect(listed.map((s) => s.stream_id)).not.toContain(adultMovie!.id);
  expect(listed.map((s) => s.stream_id)).toContain(controlMovie!.id);

  // Then the subject. request.get is safe here — the VOD asset is finite,
  // so an unwanted 200 downloads a few hundred kilobytes and returns, unlike
  // G5's live analogue, which had to avoid an endless TS stream. No
  // streamClient, and nothing to close.
  const res = await request.get(`/movie/${user.username}/${user.xcPassword}/${adultMovie!.id}.mp4`);
  expect(
    res.status(),
    'a movie hidden from this user by hide_adult_content must not stream'
  ).not.toBe(200);
});
