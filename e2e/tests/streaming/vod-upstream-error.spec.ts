import { test, expect } from '../../fixtures';
import type { ApiClient, Seeder, Waiter, UpstreamClient, Movie, VodPage } from '../../fixtures';

// Provider id 501 again: the id is scenario-scoped — this test creates its own
// scenario and its own account — so reusing it across tasks is safe and
// deliberate. Only *names* must be generated, because `Movie` is matched
// across all accounts by TMDB -> IMDB -> (name, year).
async function seedVodMovie(
  upstream: UpstreamClient,
  seed: Seeder,
  api: ApiClient,
  waitFor: Waiter
) {
  const prefix = seed.generatedName('vodfault');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    vod: [
      { id: 501, name: `${prefix}-movie`, year: 2019, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    ],
    series: 0,
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {})).status()).toBe(202);

  const movies = await waitFor.resource<VodPage<Movie>>(
    `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the ${prefix} movie to be ingested`, timeoutMs: 120_000 }
  );

  return { prefix, scenario, account, movie: movies.results[0] };
}

// Asserts the behaviour Dispatcharr SHOULD have. Any exception raised while
// establishing the upstream VOD connection becomes
//     HttpResponse(f"Streaming error: {str(e)}", status=500)
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:1405, and the
// same shape at apps/proxy/vod_proxy/views.py:845). `stream_vod` is
// AllowAny and gated only by network_access_allowed(request, "STREAMS"),
// whose default ACL is 0.0.0.0/0 — so this response body reaches an
// unauthenticated caller. The account credential must not appear in it.
//
// DELIBERATELY NOT FILED as a public issue: this is a disclosure decision
// for the repo owner, recorded in the G9 task report instead. Do not open
// one from this comment.
//
// test.fail() caveat: it is satisfied by ANY failure in the body, guards
// included — so a broken premise, not just the intended assertion, would
// also read as "expected failure" and this test would go green while
// proving nothing. The premise here (that the movie was genuinely ingested,
// via `seedVodMovie`'s own `waitFor.resource` wait) has to hold before the
// fault is armed at all, or the account create itself — not the streaming
// error path — would be what fails. The fault is armed only after ingest
// completes, so a failure here can only be the streaming-error path.
test.fail('an upstream failure on the VOD stream route does not return the provider credential', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { scenario, movie } = await seedVodMovie(upstream, seed, api, waitFor);

  // Arm the fault only after the movie has ingested — arming it earlier
  // would turn the account-create call itself into the failure:
  // `M3UAccountViewSet.create` calls `refresh_m3u_groups` and
  // `refresh_categories` inline with no `try`.
  await upstream.fault(scenario, 'not-found');
  try {
    // request.get, not streamClient.open — open() throws on a non-2xx, and
    // this test's whole point is to inspect a non-2xx body.
    const res = await request.get(`/proxy/vod/movie/${movie.uuid}`);
    const body = await res.text();

    expect(
      body,
      'an upstream failure must not return the provider account credential to the caller'
    ).not.toContain(scenario.password);
    expect(res.status(), 'an upstream failure should not surface as a 500').not.toBe(500);
  } finally {
    await upstream.clearFault(scenario, 'not-found');
  }
});
