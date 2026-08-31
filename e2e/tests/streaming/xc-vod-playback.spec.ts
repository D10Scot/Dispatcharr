import { test, expect } from '../../fixtures';
import type {
  ApiClient, Seeder, Waiter, UpstreamClient,
  Episode, Movie, Series, VodPage,
} from '../../fixtures';

// The movie's provider id is 501 and the series' is 201 in every file that
// copies this block, so `501.mp4` and `201` can be written as literals in the
// assertions below. Task 7 also declares a movie with provider id 501: that is
// deliberate and safe, because a provider id is scenario-scoped — each test
// creates its own scenario and its own account. Only *names* have to be
// generated, because `Movie` and `Series` are matched across all accounts by
// TMDB -> IMDB -> (name, year) and `VODCategory` is unique on
// (name, category_type) globally. Do not "fix" the reuse by renumbering.
async function seedVodContent(
  upstream: UpstreamClient,
  seed: Seeder,
  api: ApiClient,
  waitFor: Waiter
) {
  const prefix = seed.generatedName('vodplay');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    vod: [
      { id: 501, name: `${prefix}-movie`, year: 2019, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ],
    series: [
      {
        id: 201,
        name: `${prefix}-show`,
        categoryId: 1,
        // Two episodes, so "the series route resolves the FIRST episode" is a
        // real claim in Step 3 rather than the only option available.
        seasons: [
          { number: 1, episodes: [
            { id: 301, title: `${prefix}-s1e1`, episodeNum: 1, containerExtension: 'mp4' },
            { id: 302, title: `${prefix}-s1e2`, episodeNum: 2, containerExtension: 'mp4' },
          ] },
        ],
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {})).status()).toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the ${prefix} movie to be ingested`, timeoutMs: 120_000 }
  );
  const seriesPage = await waitFor.resource<VodPage<Series>>(
    `/api/vod/series/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the ${prefix} series to be ingested`, timeoutMs: 120_000 }
  );
  const series = seriesPage.results[0];

  // Episodes are NOT part of `refresh-vod` — `refresh_vod_content` makes four
  // provider calls and `get_series_info` is not among them. This read is what
  // creates them: `SeriesViewSet.series_info` calls `refresh_series_episodes`
  // synchronously, inside the request.
  expect((await api.get(`/api/vod/series/${series.id}/provider-info/`)).status()).toBe(200);
  const episodes = await api.json<VodPage<Episode>>(
    await api.get(`/api/vod/episodes/?series=${series.id}&ordering=episode_number`),
    'ingested episodes'
  );
  expect(episodes.count).toBe(2);

  return { prefix, scenario, account, movie: movies.results[0], series, episodes: episodes.results };
}

// The routes are mounted at the site root (dispatcharr/urls.py:57-64):
//   movie/<username>/<password>/<stream_id>.<extension>   -> stream_xc_movie
//   series/<username>/<password>/<stream_id>.<extension>  -> stream_xc_episode
// <stream_id> is the Dispatcharr primary key (Movie.pk / Episode.pk), not the
// provider's. Credentials are the Django username and
// User.custom_properties['xc_password'] — same model as G5's live stream_xc.
//
// request.get() throughout: streamClient.open() throws on any non-2xx, and
// these rows are mostly about non-2xx statuses.
test('the root XC movie and series routes authenticate and deliver bytes by Dispatcharr primary key (G9 row 14)', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { scenario, movie, episodes } = await seedVodContent(upstream, seed, api, waitFor);
  const user = await seed.xcUser();

  // 1. The movie route, keyed by Movie.pk, delivers the asset's bytes.
  const movieRes = await request.get(`/movie/${user.username}/${user.xcPassword}/${movie.id}.mp4`);
  expect(movieRes.status()).toBe(200);
  const movieBody = await movieRes.body();
  const directMovie = await fetch(
    upstream.toControl(`${scenario.internal}/movie/${scenario.username}/${scenario.password}/501.mp4`)
  );
  const movieAssetBytes = Buffer.from(await directMovie.arrayBuffer());
  expect(movieBody).toEqual(movieAssetBytes);

  // 2. Wrong password is asserted in its own test.fail() below, not here — a
  // deliberate departure from the brief (which has it inline as a passing
  // 401 assertion). It is not a 401 today: `stream_xc_movie`'s
  // credential-mismatch branch (apps/proxy/vod_proxy/views.py:1407) returns
  // a bare `Response(...)`, and this file never imports
  // `rest_framework.response.Response` — only `JsonResponse`,
  // `HttpResponse`, `HttpResponseRedirect` and `Http404` from `django.http`.
  // Every wrong-password (and missing-xc_password, and network-ACL-Forbidden)
  // branch in both `stream_xc_movie` and `stream_xc_episode` raises
  // `NameError: name 'Response' is not defined`, so the client gets an
  // unhandled 500. Discovered writing this test, not in the brief; filed as
  // https://github.com/D10Scot/Dispatcharr/issues/100, distinct from the
  // episode-404 defect below. Keeping it inline here would make this
  // "passing" test red for a reason unrelated to what it exists to prove.

  // 3. Unknown username -> 404, from get_object_or_404(User, username=...).
  const unknownUserRes = await request.get(`/movie/${user.username}-does-not-exist/${user.xcPassword}/${movie.id}.mp4`);
  expect(unknownUserRes.status()).toBe(404);

  // 4. Unknown movie id -> 404. Derived from the id this test created, never
  // a fixed literal (which could collide with a real row on a warm instance)
  // and never Number.MAX_SAFE_INTEGER (which overflows the 32-bit `id`
  // column and raises a different error for the wrong reason). Movie.id is
  // one global sequence, so an id a million above a row this test created
  // moments ago cannot exist, and is still comfortably inside int32. Same
  // derivation, and the same reasoning, as the missing episode id in the
  // second test below.
  const missingMovieId = movie.id + 1_000_000;
  const missingMovieRes = await request.get(`/movie/${user.username}/${user.xcPassword}/${missingMovieId}.mp4`);
  expect(missingMovieRes.status()).toBe(404);
  expect((await missingMovieRes.json()).error).toBe('Movie not found');

  // 5. The series route, keyed by Episode.pk, also delivers bytes.
  const firstEpisode = episodes[0];
  const episodeRes = await request.get(`/series/${user.username}/${user.xcPassword}/${firstEpisode.id}.mp4`);
  expect(episodeRes.status()).toBe(200);
  const episodeBody = await episodeRes.body();
  const directEpisode = await fetch(
    upstream.toControl(`${scenario.internal}/series/${scenario.username}/${scenario.password}/301.mp4`)
  );
  const episodeAssetBytes = Buffer.from(await directEpisode.arrayBuffer());
  expect(episodeBody).toEqual(episodeAssetBytes);
});

// Asserts the behaviour Dispatcharr SHOULD have. `stream_xc_movie`'s
// credential-mismatch branch (apps/proxy/vod_proxy/views.py:1407):
//     if custom_properties["xc_password"] != password:
//         return Response({"error": "Invalid credentials"}, status=401)
// looks correct, but `Response` (rest_framework.response.Response) is never
// imported anywhere in this file — only `JsonResponse`, `HttpResponse`,
// `HttpResponseRedirect` and `Http404` from `django.http`, plus DRF's
// `api_view`/`permission_classes` decorators and `AllowAny`. The name
// resolves to nothing, so the branch raises `NameError` instead of
// returning, and the client gets an unhandled 500. The identical pattern is
// duplicated in `stream_xc_episode` (:1441, :1444) and in both functions'
// network-ACL `Forbidden` branches (:1399, :1436) — six call sites, one
// missing import.
//
// Not in the brief: found writing this file, distinct from the episode-404
// defect below (that one is a dead exception guard; this one is a bare
// NameError, and it also breaks the *movie* route the other defect never
// touches). This departs from the task-9 plan, which specified this
// assertion as an inline, passing part of the test above.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/100
//
// test.fail() caveat: it is satisfied by ANY failure in the body, guards
// included — so a broken premise would also read as "expected failure" and
// this test would go green while proving nothing. The premise (that the
// route, a real movie id, and a real username all work) is proven separately
// by assertion 1 of the passing test above, so nothing here needs to
// re-guard it. Verified with --reporter=json that this pin fails at the
// `toBe(401)` assertion below, not before it — re-verify the same way after
// any edit here.
test.fail('wrong XC credentials against the movie route are a 401, not a 500', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { movie } = await seedVodContent(upstream, seed, api, waitFor);
  const user = await seed.xcUser();

  const res = await request.get(`/movie/${user.username}/not-${user.xcPassword}/${movie.id}.mp4`);
  expect(res.status()).toBe(401);
});

// Asserts the behaviour Dispatcharr SHOULD have. `stream_xc_episode`
// (apps/proxy/vod_proxy/views.py:1449-1454) wraps its lookup in
//     try: episode_relation = M3UEpisodeRelation.objects.filter(...).first()
//     except M3UEpisodeRelation.DoesNotExist: return 404
// but `.first()` returns None and never raises DoesNotExist, so the guard is
// dead: the next line dereferences `episode_relation.episode`, raising
// AttributeError, and the client gets a 500. `stream_xc_movie`, four
// functions above, does the same lookup and correctly checks `if not
// movie_relation` before returning 404. One guard clause closes it, and this
// test goes green when it lands.
//
// Deliberate departure from the plan: the spec asked to fold this into row
// 14's assertions while also saying row 14 "will go green on the fix" — both
// cannot be true if row 14 must fail today. Splitting it here keeps row 14
// (above) green and still pins the defect, at the cost of one more
// test.fail() in the goal.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/99
//
// test.fail() caveat: it is satisfied by ANY failure in the body, guards
// included — so a broken premise, not just the intended assertion, would
// also read as "expected failure" and this test would go green while proving
// nothing. The premise (that the route, credentials, and a real episode id
// all work) is proven separately by assertion 5 of the passing test above,
// so nothing here needs to re-guard it. Verified with --reporter=json that
// this pin fails at the `toBe(404)` assertion below, not before it —
// re-verify the same way after any edit here.
test.fail('an unknown episode id on the XC series route is a 404, not a 500', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { episodes } = await seedVodContent(upstream, seed, api, waitFor);
  const user = await seed.xcUser();

  // Same derivation, and the same reasoning, as the missing movie id above:
  // Episode.id is one global sequence, so an id a million above a row this
  // test created moments ago cannot exist, and is still comfortably inside
  // int32. Do NOT read the maximum from `?ordering=-id`:
  // EpisodeViewSet.ordering_fields is
  // ['name','season_number','episode_number','created_at']
  // (apps/vod/api_views.py:314), so DRF's OrderingFilter silently drops `id`
  // and falls back to ['series__name','season_number','episode_number'] — the
  // row that comes back is an arbitrary episode, not the newest one.
  const missingEpisodeId = Math.max(...episodes.map((e) => e.id)) + 1_000_000;

  const res = await request.get(`/series/${user.username}/${user.xcPassword}/${missingEpisodeId}.mp4`);
  expect(res.status()).toBe(404);
});
