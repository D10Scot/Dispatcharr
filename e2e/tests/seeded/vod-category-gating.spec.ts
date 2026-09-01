import { test, expect } from '../../fixtures';
import type { Movie, VodCategory, VodPage } from '../../fixtures';

test('gating on: a disabled category starts empty, an explicit enable admits its movies, and a later refresh does not re-disable it (G9 row 3)', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(180_000);

  const prefix = seed.generatedName('vod-gate-on');
  const categoryName = `${prefix}-cat`;
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: categoryName }],
    vod: [
      { id: 1, name: `${prefix}-movie-1`, year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
      { id: 2, name: `${prefix}-movie-2`, year: 2021, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ],
    series: 0,
  });

  // auto_enable_new_groups_vod: false — the category this test cares about is
  // brand new to this account, so it must land DISABLED. That is the
  // precondition the whole arc depends on.
  const account = await seed.xcAccount(scenario, {
    enable_vod: true,
    auto_enable_new_groups_vod: false,
  });

  const firstRefresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(firstRefresh.status()).toBe(202);

  // `waitFor.condition` resolves to void — it proves the predicate held, it
  // does not hand back the body. `waitFor.resource<T>` is the one that
  // returns the body, but it types the response as a single `T`, and this
  // endpoint answers with a bare array. So: wait, then read.
  await waitFor.condition(
    async () => {
      const all = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');
      return all.some(
        (c) => c.name === categoryName && c.m3u_accounts.some((r) => r.m3u_account === account.id)
      );
    },
    { description: 'the gated category and its relation to exist', timeoutMs: 120_000 }
  );

  const afterFirstRefresh = await api.json<VodCategory[]>(
    await api.get('/api/vod/categories/'),
    'categories'
  );
  const category = afterFirstRefresh.find((c) => c.name === categoryName)!;
  const relation = category.m3u_accounts.find((r) => r.m3u_account === account.id)!;
  // Asserted alongside the zero below rather than left implicit: a bare
  // `count === 0` is exactly what a refresh that crashed before ever writing
  // a movie also produces. This is what makes "gated" and "broken"
  // distinguishable in the failure message.
  expect(relation.enabled).toBe(false);

  const moviesWhileGated = await api.json<VodPage<Movie>>(
    await api.get(`/api/vod/movies/?m3u_account=${account.id}&name=${prefix}`),
    'movies while the category is gated'
  );
  expect(moviesWhileGated.count).toBe(0);

  // Enable it. The key is `id` — the VODCategory pk — NOT `category`; rows
  // without it are silently skipped by `update_group_settings`
  // (apps/m3u/api_views.py:552-568). `custom_properties` must be supplied
  // even though this test has nothing to put in it: the action reads raw
  // request.data and issues a bulk_create(update_fields=['enabled',
  // 'custom_properties']), so an omitted custom_properties would overwrite
  // whatever was there with `{}`.
  const enableRes = await api.patch(`/api/m3u/accounts/${account.id}/group-settings/`, {
    category_settings: [{ id: category.id, enabled: true, custom_properties: {} }],
  });
  expect(enableRes.status()).toBe(200);

  const secondRefresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(secondRefresh.status()).toBe(202);

  await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${prefix}`,
    (body) => body.count === 2,
    {
      description: `both movies in ${categoryName} to appear once its relation is enabled`,
      timeoutMs: 20_000,
    }
  );

  // A THIRD refresh, immediately after the second. `batch_create_categories`
  // re-derives every category's relation for this account as `enabled:
  // auto_enable_new` — here `false`, from the account's own flag — and
  // inserts it via `bulk_create(relations_to_create, ignore_conflicts=True)`
  // (apps/vod/tasks.py:293-360). Against a relation that already exists, the
  // unique constraint on (m3u_account, category) makes that insert a no-op:
  // the row this test enabled by hand keeps its `enabled: true`. A naive
  // reimplementation using an *upsert* (update_conflicts) instead of
  // ignore_conflicts would re-disable the relation here and
  // cleanup_orphaned_vod_content would delete both movies right back out —
  // this is the half of the arc that gets that wrong.
  const thirdRefresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(thirdRefresh.status()).toBe(202);

  // No REST signal marks a VOD-only refresh complete (unlike an M3U refresh,
  // which moves M3UAccount.status through fetching/parsing to a terminal
  // value — see `waitFor.m3uRefreshComplete`). A bare `waitFor.condition`
  // that just checks "is it still correct?" would resolve on its very first
  // poll, before the third refresh's Celery task has had any real wall-clock
  // time to run, and prove nothing at all about it. So this requires the
  // good state to hold *continuously* for SETTLE_MS before resolving — long
  // enough for refresh_vod_content to run against this local fake-provider
  // container and, if it were going to re-disable the relation and clean up
  // the movies, do so inside the window. If it does, `settledSince` resets
  // and the wait times out naming both halves, rather than passing on a
  // premature snapshot.
  const SETTLE_MS = 10_000;
  let settledSince: number | undefined;
  await waitFor.condition(
    async () => {
      const moviesNow = await api.json<VodPage<Movie>>(
        await api.get(`/api/vod/movies/?m3u_account=${account.id}&name=${prefix}`),
        'movies after the third refresh'
      );
      const categoriesNow = await api.json<VodCategory[]>(
        await api.get('/api/vod/categories/'),
        'categories after the third refresh'
      );
      const relationNow = categoriesNow
        .find((c) => c.name === categoryName)
        ?.m3u_accounts.find((r) => r.m3u_account === account.id);
      const stillGood = moviesNow.count === 2 && relationNow?.enabled === true;
      if (!stillGood) {
        settledSince = undefined;
        return false;
      }
      settledSince ??= Date.now();
      return Date.now() - settledSince >= SETTLE_MS;
    },
    {
      intervalMs: 2_000,
      timeoutMs: 60_000,
      description:
        `both movies to remain present AND the ${categoryName} relation to ` +
        `remain enabled, continuously for ${SETTLE_MS}ms after a third ` +
        `refresh — proving a manually-enabled category is not re-disabled ` +
        'by a later refresh',
    }
  );
});

test('gating off removes the category\'s content via cleanup, not a read-time filter (G9 row 4)', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(180_000);

  const prefix = seed.generatedName('vod-gate-off');
  const categoryAName = `${prefix}-cat-a`;
  const categoryBName = `${prefix}-cat-b`;
  const movieAName = `${prefix}-movie-a`;
  const movieBName = `${prefix}-movie-b`;
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [
      { id: 1, name: categoryAName },
      { id: 2, name: categoryBName },
    ],
    vod: [
      { id: 1, name: movieAName, year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
      { id: 2, name: movieBName, year: 2021, categoryId: 2, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ],
    series: 0,
  });

  // No auto_enable_new_groups_vod override: it defaults to true on create
  // (M3UAccountSerializer.create, apps/m3u/serializers.py:357), so both
  // brand-new categories auto-enable and both movies land on the first
  // refresh.
  const account = await seed.xcAccount(scenario, { enable_vod: true });

  const firstRefresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(firstRefresh.status()).toBe(202);

  await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${prefix}`,
    (body) => body.count === 2,
    { description: 'both movies to be ingested on the first refresh', timeoutMs: 120_000 }
  );

  const categories = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');
  const categoryA = categories.find((c) => c.name === categoryAName)!;

  const disableRes = await api.patch(`/api/m3u/accounts/${account.id}/group-settings/`, {
    category_settings: [{ id: categoryA.id, enabled: false, custom_properties: {} }],
  });
  expect(disableRes.status()).toBe(200);

  const secondRefresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(secondRefresh.status()).toBe(202);

  // The mechanism this pins: `process_movie_batch` sees category A's
  // relation disabled and `continue`s past movie A entirely, leaving its
  // `M3UMovieRelation.last_seen` older than this scan's `scan_start_time`.
  // `cleanup_orphaned_vod_content(account_id, scan_start_time)`
  // (apps/vod/tasks.py:1735), run at the end of the same refresh task, then
  // deletes every relation with a stale `last_seen` for this account, and
  // finally deletes every **globally** orphaned `Movie` row (one with no
  // `M3UMovieRelation` left at all). Movie A disappears because its one
  // relation was just deleted, not because a read-time filter hid it —
  // there is no such filter on this endpoint.
  const moviesAfterDisable = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${prefix}`,
    (body) => body.count === 1,
    {
      description: `only movie B (${movieBName}) to remain once category A is disabled`,
      timeoutMs: 120_000,
    }
  );
  expect(moviesAfterDisable.results[0].name).toBe(movieBName);

  // Proves the `Movie` row itself was deleted (globally orphaned), not just
  // this account's relation to it — a read scoped by name but NOT by
  // m3u_account, safe under the "no unfiltered count" rule because the name
  // is generated and therefore unique to this test.
  const movieAGlobally = await api.json<VodPage<Movie>>(
    await api.get(`/api/vod/movies/?name=${movieAName}`),
    'movie A, unscoped by account'
  );
  expect(movieAGlobally.count).toBe(0);
});

test('an uncategorised movie or series falls back to the Uncategorized category, gated by its own account flag (G9 row 5)', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(150_000);

  const prefix = seed.generatedName('vod-gate-uncat');
  const categoryName = `${prefix}-cat`;
  const seriesCategoryName = `${prefix}-scat`;
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: categoryName }],
    seriesCategories: [{ id: 1, name: seriesCategoryName }],
    vod: [
      { id: 1, name: `${prefix}-movie`, year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ],
    series: [
      {
        id: 1,
        name: `${prefix}-series`,
        categoryId: 1,
        seasons: [{ number: 1, episodes: [{ id: 1, title: `${prefix}-ep`, episodeNum: 1, containerExtension: 'mp4' }] }],
      },
    ],
  });

  // Both auto-enable flags false: refresh_movies/refresh_series always
  // get_or_create the Uncategorized category AND relation on every refresh
  // (apps/vod/tasks.py:183-210), with `enabled = auto_enable_new_groups_vod`
  // / `_series`. With both false on this account, `enabled: false` below is
  // a real assertion about THIS account's flags — not a coincidence of
  // whatever the defaults happen to be — which is the whole reason this test
  // sets them false rather than leaving the (true) defaults.
  const account = await seed.xcAccount(scenario, {
    enable_vod: true,
    auto_enable_new_groups_vod: false,
    auto_enable_new_groups_series: false,
  });

  const refreshRes = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(refreshRes.status()).toBe(202);

  // Waits for the refresh to have run by polling for its OWN generated
  // category's relation — a state that starts absent and only appears once
  // the refresh has processed this account, so this is a genuine
  // wait-for-completion signal, unlike a re-check of already-true state.
  await waitFor.condition(
    async () => {
      const all = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');
      return all.some(
        (c) => c.name === categoryName && c.m3u_accounts.some((r) => r.m3u_account === account.id)
      );
    },
    { description: 'the refresh to have run for this account', timeoutMs: 120_000 }
  );

  const categories = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');

  // Hazard 1: `GET /api/vod/categories/` itself get_or_creates these two
  // Uncategorized relations for every enable_vod XC account
  // (`VODCategoryViewSet.list`, apps/vod/api_views.py:647), with
  // `defaults={'enabled': auto_enable_new}` — so this assertion holds
  // whether the refresh above created the relation or this very GET did.
  // Nothing here claims the refresh was what created it.
  const uncategorizedMovieCat = categories.find(
    (c) => c.name === 'Uncategorized' && c.category_type === 'movie'
  )!;
  expect(uncategorizedMovieCat).toBeTruthy();
  const movieRelation = uncategorizedMovieCat.m3u_accounts.find((r) => r.m3u_account === account.id)!;
  // Hazard 2: never assert the ABSENCE of this relation for any account —
  // any other worker's own `GET /api/vod/categories/` call would create one
  // for its own account, but never for this one (the relation is scoped by
  // m3u_account), so only presence is safe to assert here.
  expect(movieRelation).toBeTruthy();
  expect(movieRelation.enabled).toBe(false);

  const uncategorizedSeriesCat = categories.find(
    (c) => c.name === 'Uncategorized' && c.category_type === 'series'
  )!;
  expect(uncategorizedSeriesCat).toBeTruthy();
  const seriesRelation = uncategorizedSeriesCat.m3u_accounts.find((r) => r.m3u_account === account.id)!;
  expect(seriesRelation).toBeTruthy();
  expect(seriesRelation.enabled).toBe(false);

  // Second half: a movie with no category at all must land in Uncategorized
  // and survive there. That needs `auto_enable_new_groups_vod: true` on ITS
  // account (`process_movie_batch` skips a movie whose Uncategorized
  // relation is disabled, same as any other disabled category) — a separate
  // account rather than flipping the first account's flag mid-test, so the
  // row-3-shaped "does this ever flip back" question never applies here.
  const prefix2 = seed.generatedName('vod-gate-uncat-b');
  const scenarioB = await upstream.scenario({
    xc: true,
    username: `${prefix2}-user`,
    password: `${prefix2}-pass`,
    vod: [
      { id: 1, name: `${prefix2}-movie`, year: 2020, categoryId: null, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ],
    series: 0,
  });
  const accountB = await seed.xcAccount(scenarioB, { enable_vod: true });

  const refreshBRes = await api.post(`/api/m3u/accounts/${accountB.id}/refresh-vod/`, {});
  expect(refreshBRes.status()).toBe(202);

  const moviesB = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${accountB.id}&name=${prefix2}`,
    (body) => body.count === 1,
    { description: `the uncategorised movie for account ${accountB.id} to be ingested`, timeoutMs: 120_000 }
  );
  const movieBId = moviesB.results[0].id;

  const providers = await api.json<Array<{ m3u_account: { id: number }; category: VodCategory | null }>>(
    await api.get(`/api/vod/movies/${movieBId}/providers/`),
    'movie providers'
  );
  const providerRelation = providers.find((p) => p.m3u_account.id === accountB.id)!;
  expect(providerRelation).toBeTruthy();
  expect(providerRelation.category?.name).toBe('Uncategorized');
});
