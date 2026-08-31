import {
  test,
  expect,
  type Movie,
  type M3uMovieRelation,
  type VodPage,
} from '../../fixtures';

/**
 * G9 row 8: advanced movie data, the 24-hour refresh throttle, and survival
 * across a list sync.
 *
 * The movie is declared `containerExtension: 'mkv'` deliberately.
 * `MovieViewSet.provider_info` returns `movie_data.get('container_extension',
 * 'mp4')` (`apps/vod/api_views.py:243`) — `'mp4'` is the literal default when
 * `movie_data` is absent entirely, so an assertion of `'mp4'` here could not
 * fail and would prove nothing. `'mkv'` only appears if the stored
 * `movie_data` was actually read.
 */

interface ProviderInfo {
  director: string;
  actors: string;
  container_extension: string;
}

test('advanced movie data is fetched, throttled for 24h, and survives a list sync', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(180_000);

  const prefix = seed.generatedName('vodadv');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    vod: [
      {
        id: 501,
        name: `${prefix}-movie`,
        year: 2015,
        categoryId: 1,
        containerExtension: 'mkv',
        tmdbId: null,
        imdbId: null,
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  const refresh = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(refresh.status(), 'POST refresh-vod/').toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the VOD movie named ${prefix}-movie to be ingested`, timeoutMs: 120_000 }
  );
  expect(movies.count, `movie row for ${prefix} scoped to account ${account.id}`).toBe(1);
  const movie = movies.results[0];

  // --- Step 1: baseline, before any advanced fetch has happened -----------

  const before = (
    await api.json<M3uMovieRelation[]>(
      await api.get(`/api/vod/movies/${movie.id}/providers/`),
      'relation before the advanced fetch'
    )
  ).find((r) => r.m3u_account.id === account.id)!;
  expect(before, `relation for account ${account.id}`).toBeDefined();
  expect(before.custom_properties?.detailed_fetched).toBe(false);
  expect(before.last_advanced_refresh).toBeNull();

  // --- Step 2: drive the advanced fetch ------------------------------------

  const info = await api.json<ProviderInfo>(
    await api.get(`/api/vod/movies/${movie.id}/provider-info/`),
    'movie provider-info (initial fetch)'
  );

  // G8's renderVodInfo defaults, proving the `info` half of the payload
  // landed.
  expect(info.director).toBe('E2E Director');
  expect(info.actors).toBe('E2E Actor');
  // Proves the `movie_data` half landed too — see the file header for why
  // 'mkv' (not the 'mp4' default) is the only value that discriminates this.
  expect(info.container_extension).toBe('mkv');

  const afterFirstFetch = (
    await api.json<M3uMovieRelation[]>(
      await api.get(`/api/vod/movies/${movie.id}/providers/`),
      'relation after the advanced fetch'
    )
  ).find((r) => r.m3u_account.id === account.id)!;
  expect(afterFirstFetch.custom_properties?.detailed_fetched).toBe(true);
  expect(afterFirstFetch.custom_properties?.detailed_info).toBeTruthy();
  expect(afterFirstFetch.custom_properties?.movie_data).toBeTruthy();
  expect(afterFirstFetch.last_advanced_refresh).not.toBeNull();

  // --- Step 3: the 24-hour throttle ----------------------------------------

  // A second unforced call must be a no-op: `needs_refresh` re-evaluates to
  // false (detailed_fetched is true, last_advanced_refresh is fresh), so the
  // task never runs and the timestamp does not move.
  await api.json(
    await api.get(`/api/vod/movies/${movie.id}/provider-info/`),
    'movie provider-info (second, unforced call)'
  );
  const afterSecondCall = (
    await api.json<M3uMovieRelation[]>(
      await api.get(`/api/vod/movies/${movie.id}/providers/`),
      'relation after the second, unforced call'
    )
  ).find((r) => r.m3u_account.id === account.id)!;
  expect(afterSecondCall.last_advanced_refresh).toBe(afterFirstFetch.last_advanced_refresh);

  // The unmoved timestamp above cannot tell "the refresh was suppressed"
  // from "the refresh ran and its result happened to be identical" — two
  // redundant gates (the view's needs_refresh check and the task's own
  // throttle guard) would both produce that same observable if either one,
  // alone, were broken. Only the fake provider's own request log can
  // distinguish them: across the initial fetch and this second, unforced
  // call, exactly one get_vod_info request should have reached it.
  const vodInfoRequests = (await upstream.log(scenario)).filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('action=get_vod_info')
  );
  expect(
    vodInfoRequests,
    'get_vod_info requests reaching the provider across the initial and second unforced calls'
  ).toHaveLength(1);

  // Proves the throttle is actually gating a fetch that *can* still happen —
  // not merely that no fetch happened, which a broken "never refreshes"
  // implementation would also produce. `force_refresh=true` (the literal
  // string) must bypass the throttle and move the timestamp forward.
  await api.json(
    await api.get(`/api/vod/movies/${movie.id}/provider-info/?force_refresh=true`),
    'movie provider-info (forced refresh)'
  );
  const afterForcedRefresh = (
    await api.json<M3uMovieRelation[]>(
      await api.get(`/api/vod/movies/${movie.id}/providers/`),
      'relation after the forced refresh'
    )
  ).find((r) => r.m3u_account.id === account.id)!;
  expect(afterForcedRefresh.last_advanced_refresh).not.toBeNull();
  expect(
    new Date(afterForcedRefresh.last_advanced_refresh!).getTime(),
    'forced refresh must move last_advanced_refresh strictly forward'
  ).toBeGreaterThan(new Date(afterSecondCall.last_advanced_refresh!).getTime());

  // --- Step 4: the merge survives a list sync -------------------------------

  const lastSeenBeforeResync = afterForcedRefresh.last_seen;

  const resync = await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {});
  expect(resync.status(), 'POST refresh-vod/ (second sync)').toBe(202);

  // No count change to hang on: the movie already exists. `last_seen` is what
  // `cleanup_orphaned_vod_content` itself relies on to know a relation was
  // touched by this scan, so it is the honest signal that the resync landed.
  await waitFor.condition(
    async () => {
      const relation = (
        await api.json<M3uMovieRelation[]>(
          await api.get(`/api/vod/movies/${movie.id}/providers/`),
          'relation while waiting for the resync to settle'
        )
      ).find((r) => r.m3u_account.id === account.id)!;
      return relation.last_seen !== lastSeenBeforeResync;
    },
    {
      description: `relation last_seen to advance past ${lastSeenBeforeResync} after the resync`,
      timeoutMs: 120_000,
    }
  );

  const afterResync = (
    await api.json<M3uMovieRelation[]>(
      await api.get(`/api/vod/movies/${movie.id}/providers/`),
      'relation after the list resync'
    )
  ).find((r) => r.m3u_account.id === account.id)!;
  // The property this row exists to pin: process_movie_batch merges
  // basic_data into the existing custom_properties dict rather than
  // replacing it, so the advanced-fetch payload must still be present
  // alongside the freshly-written basic_data.
  expect(afterResync.custom_properties?.basic_data).toBeTruthy();
  expect(afterResync.custom_properties?.detailed_info).toBeTruthy();
  expect(afterResync.custom_properties?.movie_data).toBeTruthy();
  expect(afterResync.custom_properties?.detailed_fetched).toBe(true);
});
