import {
  test,
  expect,
  UpstreamClient,
  Seeder,
  ApiClient,
  type Movie,
  type Series,
  type VodCategory,
  type M3uMovieRelation,
  type M3uSeriesRelation,
  type VodPage,
  type UpstreamScenario,
  type M3uAccount,
} from '../../fixtures';

/**
 * G9 rows 1, 2 and 19. `e2e/tests/seeded/vod-catalogue-ingest.spec.ts` (G8) is
 * the plumbing proof that a movie/series/episode row appears at all after an
 * XC refresh — it is untouched here. This file asserts what those rows
 * *contain*, that categories are created correctly with the right per-account
 * relation, and pins the `VODCategoryFilter.m3u_account` fix.
 *
 * One scenario shape, declared fresh per test via `seedCatalogue()` — not
 * shared as a single seeded fixture — because Step 4 must not depend on
 * Step 2/3 having already run in the same test, and a shared `beforeEach`
 * would hide that dependency. Every name is generated:
 * `VODCategory` is unique on `(name, category_type)` **globally**, and
 * `Movie`/`Series` are matched across *all* accounts by TMDB → IMDB →
 * `(name, year)` when no external id is present — an unscoped name here
 * would collide with another worker's identically-shaped fixture.
 */

type Seeded = {
  prefix: string;
  scenario: UpstreamScenario;
  account: M3uAccount;
};

async function seedCatalogue(
  upstream: UpstreamClient,
  seed: Seeder,
  api: ApiClient
): Promise<Seeded> {
  const prefix = seed.generatedName('vodfid');
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

  return { prefix, scenario, account };
}

test('a VOD refresh records what the provider actually declared, per movie and per series', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(150_000);

  const { prefix, account } = await seedCatalogue(upstream, seed, api);

  // MovieFilter.m3u_account is m3u_relations__m3u_account__id and name is
  // icontains (apps/vod/api_views.py:53-65) — scoped by both the account and
  // the generated name, never an unfiltered count.
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

  // Everything below is read straight off G8's movieEntry renderer, not
  // guessed at: genre/rating/duration_secs are its fixed literals, description
  // is its `plot` (ingest reads description-then-plot), is_adult is false
  // because no is_adult key is declared, custom_properties is null because
  // none of director/actors/trailer/release_date is declared, and logo is
  // null because MovieSpec has no way to declare a stream_icon at all — do
  // not assert logo.url, which the spec's row 1 asks for but which no
  // provider entry here can produce.
  expect(alpha).toMatchObject({
    name: `${prefix}-alpha`,
    year: 1999,
    genre: 'E2E',
    description: `${prefix}-alpha — e2e fixture`,
    rating: '7.5',
    duration_secs: 5,
    is_adult: false,
    custom_properties: null,
    logo: null,
  });
  expect(beta).toMatchObject({
    name: `${prefix}-beta`,
    year: 2011,
    genre: 'E2E',
    description: `${prefix}-beta — e2e fixture`,
    rating: '7.5',
    duration_secs: 5,
    is_adult: false,
    custom_properties: null,
    logo: null,
  });

  // The relation is where "what the provider said" survives verbatim.
  const alphaRelations = await api.json<M3uMovieRelation[]>(
    await api.get(`/api/vod/movies/${alpha!.id}/providers/`),
    'alpha movie providers'
  );
  const alphaRelation = alphaRelations.find((r) => r.m3u_account.id === account.id);
  expect(alphaRelation, `a relation to account ${account.id} for ${prefix}-alpha`).toBeDefined();
  // M3UMovieRelation.stream_id is a CharField — '101', not 101 — while
  // basic_data is the provider's own untouched JSON, where stream_id is the
  // number the provider actually sent. Same id, deliberately different types
  // on either side of the relation.
  expect(alphaRelation!.stream_id).toBe('101');
  expect(alphaRelation!.container_extension).toBe('mp4');
  expect(alphaRelation!.category?.name).toBe(`${prefix}-movies-a`);
  const alphaBasic = alphaRelation!.custom_properties?.basic_data as Record<string, unknown>;
  expect(alphaBasic.stream_id).toBe(101);
  expect(alphaBasic.container_extension).toBe('mp4');
  expect(alphaRelation!.custom_properties?.detailed_fetched).toBe(false);

  // A single-movie assertion would not prove the category map is per-movie —
  // beta must land in the *other* declared category with its own extension.
  const betaRelations = await api.json<M3uMovieRelation[]>(
    await api.get(`/api/vod/movies/${beta!.id}/providers/`),
    'beta movie providers'
  );
  const betaRelation = betaRelations.find((r) => r.m3u_account.id === account.id);
  expect(betaRelation, `a relation to account ${account.id} for ${prefix}-beta`).toBeDefined();
  expect(betaRelation!.stream_id).toBe('102');
  expect(betaRelation!.container_extension).toBe('mkv');
  expect(betaRelation!.category?.name).toBe(`${prefix}-movies-b`);

  const series = await waitFor.resource<VodPage<Series>>(
    `/api/vod/series/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the series ${prefix}-show to be ingested`, timeoutMs: 120_000 }
  );
  expect(series.count, `series rows for ${prefix} scoped to account ${account.id}`).toBe(1);
  // process_series_batch reads cover/plot/releaseDate, not the movie keys —
  // same genre/description shape as a movie, but via a distinct code path.
  expect(series.results[0]).toMatchObject({
    name: `${prefix}-show`,
    genre: 'E2E',
    description: `${prefix}-show — e2e fixture`,
  });

  const seriesRelations = await api.json<M3uSeriesRelation[]>(
    await api.get(`/api/vod/series/${series.results[0].id}/providers/`),
    'series providers'
  );
  const seriesRelation = seriesRelations.find((r) => r.m3u_account.id === account.id);
  expect(seriesRelation, `a relation to account ${account.id} for ${prefix}-show`).toBeDefined();
  expect(seriesRelation!.external_series_id).toBe('201');
  expect(seriesRelation!.category?.name).toBe(`${prefix}-shows`);
});

test('a VOD refresh creates one category row per declared category, enabled for that account', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(150_000);

  const { prefix, account } = await seedCatalogue(upstream, seed, api);

  // refresh_vod_content is a separate Celery task queued by the 202 above,
  // not completed by it — poll rather than reading once. Unpaginated and
  // instance-global (no pagination_class on VODCategoryViewSet), so the read
  // must be scoped: this test deliberately does not depend on the
  // m3u_account filter the test below pins, so `name` (icontains, scoped by
  // the generated prefix no other worker's fixture can share) is used here
  // too. Wait for exactly the three
  // categories this test declared, then locate each with find rather than a
  // length or an index, and assert nothing about a category this test did
  // not declare.
  const categories = await waitFor.resource<VodCategory[]>(
    `/api/vod/categories/?name=${encodeURIComponent(prefix)}`,
    (body) => body.length === 3,
    { description: `all 3 ${prefix} categories to be created`, timeoutMs: 120_000 }
  );

  const moviesA = categories.find(
    (c) => c.name === `${prefix}-movies-a` && c.category_type === 'movie'
  );
  const moviesB = categories.find(
    (c) => c.name === `${prefix}-movies-b` && c.category_type === 'movie'
  );
  const shows = categories.find(
    (c) => c.name === `${prefix}-shows` && c.category_type === 'series'
  );
  expect(moviesA, `a movie category named ${prefix}-movies-a`).toBeDefined();
  expect(moviesB, `a movie category named ${prefix}-movies-b`).toBeDefined();
  expect(shows, `a series category named ${prefix}-shows`).toBeDefined();

  // batch_create_categories creates the relation with enabled taken from
  // custom_properties['auto_enable_new_groups_vod'/'_series'], which default
  // to True even though M3UVODCategoryRelation.enabled defaults to False on
  // the model — this is the one place that True is only true because of the
  // account-level default, not the field default.
  for (const category of [moviesA!, moviesB!, shows!]) {
    const relation = category.m3u_accounts.find((r) => r.m3u_account === account.id);
    expect(
      relation,
      `an m3u_accounts relation to account ${account.id} on ${category.name}`
    ).toBeDefined();
    expect(relation!.enabled).toBe(true);
  }
});

// Pins the fix for #96. VODCategoryFilter (apps/vod/api_views.py) used to
// declare
//   m3u_account = NumberFilter(field_name="m3u_account__id")
// but VODCategory has no `m3u_account` relation — the reverse accessor is
// `m3u_relations`. The filter was in Meta.fields too, so it imported cleanly
// and failed only at query time with
//   FieldError: Cannot resolve keyword 'm3u_account' into field. Choices are:
//   category_type, created_at, id, m3u_relations, m3umovierelation,
//   m3useriesrelation, name, updated_at
// MovieFilter and SeriesFilter always had this right
// ("m3u_relations__m3u_account__id"); only VODCategoryFilter did not. The
// frontend never passed the filter, which is why nothing had hit it. The
// premise this test depends on (account creation succeeds, and
// GET /api/vod/categories/ without the filter returns 200 with
// correctly-related rows) is asserted directly, without inversion, in the
// category-rows test above.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/96
test('GET /api/vod/categories/ accepts an m3u_account filter', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // seedCatalogue() twice (the main account and the decoy) plus two
  // waitFor.resource calls, each with its own 120s budget: 120_000 * 2 for
  // the waiters, plus headroom for both seeds and the one-shot status check.
  // 150_000 was enough for one waiter but not two, and a test-level timeout
  // fires as Playwright's own generic message rather than either waiter's
  // "last observed" one, so a regression that reaches only the second wait
  // would lose its diagnostic text to a budget that was never the point
  // under test.
  test.setTimeout(270_000);

  const { prefix, account } = await seedCatalogue(upstream, seed, api);

  // A second, minimal account with its own category, seeded before the read
  // below and confirmed to exist first. Without it, a broken filter that
  // returns an unfiltered (or wrongly `gte`-scoped) list is caught only when
  // some OTHER seeded spec's account already happens to have a category in
  // the shared instance at read time — true under this project's normal
  // parallel load, but not guaranteed by this test on its own. Seeding it
  // here, and waiting for it before the read, makes the negative assertion
  // below deterministic regardless of what else is running.
  const decoyPrefix = seed.generatedName('vodfid-decoy');
  const decoyScenario = await upstream.scenario({
    xc: true,
    username: `${decoyPrefix}-user`,
    password: `${decoyPrefix}-pass`,
    vodCategories: [{ id: 1, name: `${decoyPrefix}-decoy` }],
  });
  const decoyAccount = await seed.xcAccount(decoyScenario, { enable_vod: true });
  const decoyRefresh = await api.post(`/api/m3u/accounts/${decoyAccount.id}/refresh-vod/`, {});
  expect(decoyRefresh.status(), 'POST refresh-vod/ (decoy account)').toBe(202);
  await waitFor.resource<VodCategory[]>(
    `/api/vod/categories/?name=${encodeURIComponent(decoyPrefix)}`,
    (body) => body.length === 1,
    { description: `the decoy ${decoyPrefix}-decoy category to exist`, timeoutMs: 120_000 }
  );

  const url = `/api/vod/categories/?m3u_account=${account.id}`;
  // A one-shot status assertion first: the filter must not 500. Without it, a
  // pre-fix regression is caught only by the waiter below timing out after a
  // deterministic 120s of HTTP 500 — which can exceed this test's own 150s
  // budget depending on how long seeding above took, losing the waiter's
  // "last observed: HTTP 500" message in favour of a generic Playwright
  // "Test timeout of 150000ms exceeded" that names no mechanism.
  expect((await api.get(url)).status(), 'the m3u_account filter must not 500').toBe(200);

  // Still not deterministic on status alone: refresh_vod_content is a
  // separate Celery task queued by the 202 above, not completed by it, so a
  // read straight after the POST can return 200 with zero rows whether the
  // filter is scoping correctly or not. Wait for the three ${prefix}
  // categories the category-rows test above declares, the same way it does,
  // but through the m3u_account filter instead of name — that is the
  // property under test. Not an exact-length predicate: VODCategoryViewSet.list()
  // (apps/vod/api_views.py) also get_or_creates a movie and a series
  // "Uncategorized" category and relation for every active XC account with
  // VOD enabled, including this one, on every call to this same endpoint —
  // so a correctly-scoped answer for this account is these three plus up to
  // two Uncategorized rows, never exactly three.
  const expectedNames = [`${prefix}-movies-a`, `${prefix}-movies-b`, `${prefix}-shows`];
  const categories = await waitFor.resource<VodCategory[]>(
    url,
    (body) => expectedNames.every((n) => body.some((c) => c.name === n)),
    { description: `all 3 ${prefix} categories via the m3u_account filter`, timeoutMs: 120_000 }
  );

  for (const name of expectedNames) {
    const category = categories.find((c) => c.name === name);
    expect(category, `${name} among the m3u_account-filtered categories`).toBeDefined();
  }
  // Every returned row must actually relate to this account, and the decoy
  // account's category must be absent — together these are guaranteed (not
  // merely likely) to fail an unfiltered list or a wrongly `gte`-scoped one,
  // because the decoy account above exists and was confirmed before this
  // read. The backend's own scoping is pinned deterministically by
  // apps.vod.tests.test_vod_category_account_filter, which seeds two
  // accounts up front and asserts the other account's category is absent —
  // this e2e pin now asserts the same shape through the live endpoint.
  for (const category of categories) {
    expect(category.m3u_accounts.some((r) => r.m3u_account === account.id)).toBe(true);
  }
  expect(
    categories.some((c) => c.name === `${decoyPrefix}-decoy`),
    `the decoy account's category must not appear under account ${account.id}'s filter`
  ).toBe(false);
});
