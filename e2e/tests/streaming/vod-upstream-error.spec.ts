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

// The first non-inverted control for the test.fail() below ('an upstream
// failure on the VOD stream route does not return the provider
// credential'): its premise is that seedVodMovie's own scenario, account,
// refresh-vod POST and waitFor.resource ingest wait produce a movie that
// genuinely streams over /proxy/vod/movie/<uuid> when no fault is armed —
// the account create, the ingest wait and the route itself all have to work
// before the pin's credential check is even reachable. No other test in
// this file requests the movie route with no fault armed: the second
// control below arms the 'not-found' fault before its first request, and
// the pin's identical seedVodMovie call sits inside its test.fail(...)
// body, only ever requested with the fault already armed. A break in the
// seed-and-ingest sequence itself (not just in the credential-disclosure
// behaviour) would be swallowed by the pin below as an "expected failure",
// since test.fail() is satisfied by ANY failure in its body, not
// specifically the regression it exists to pin.
test('a seeded VOD movie streams successfully when no fault is armed', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { movie } = await seedVodMovie(upstream, seed, api, waitFor);

  const res = await request.get(`/proxy/vod/movie/${movie.uuid}`);
  expect([200, 206]).toContain(res.status());
  expect(
    (await res.body()).byteLength,
    'a clean VOD stream must return a non-empty body'
  ).toBeGreaterThan(0);
});

// The second non-inverted control for the test.fail() below: the pin's
// credential check has no meaning unless arming the 'not-found' fault
// genuinely drives the request into the connection manager's
// `except Exception` handler at
// multi_worker_connection_manager.py:1405 — the only place that returns
// `HttpResponse(f"Streaming error: {str(e)}", status=500)`. This control
// arms that same fault, on its own fresh scenario, before making any
// request at all (so there is no already-open session to reuse from a
// prior clean request), then asserts the failure directly: a 500 status
// and a body carrying the handler's own "Streaming error:" prefix. No
// other test in this file arms the 'not-found' fault and checks the
// resulting response outside a test.fail() block: the control above never
// arms a fault, and the pin's identical upstream.fault(scenario,
// 'not-found') call sits inside its test.fail(...) body. A break here —
// the fault not reaching the upstream fetch, or some other status
// reaching the client — would be swallowed by the pin below as an
// "expected failure", since test.fail() is satisfied by ANY failure in
// its body, not specifically the credential-disclosure regression it
// exists to pin.
test('the not-found fault on a VOD movie route produces a genuine streaming failure', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { scenario, movie } = await seedVodMovie(upstream, seed, api, waitFor);

  await upstream.fault(scenario, 'not-found');
  try {
    const res = await request.get(`/proxy/vod/movie/${movie.uuid}`);
    expect(
      res.status(),
      "the not-found fault should drive the request into the connection manager's exception handler"
    ).toBe(500);
    expect(
      await res.text(),
      "the failure body should carry the connection manager's own error prefix"
    ).toContain('Streaming error:');
  } finally {
    await upstream.clearFault(scenario, 'not-found');
  }
});

// Asserts the behaviour Dispatcharr SHOULD have. Any exception raised while
// establishing the upstream VOD connection becomes
//     HttpResponse(f"Streaming error: {str(e)}", status=500)
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:1405, and the
// same shape at apps/proxy/vod_proxy/views.py:845). `stream_vod` is
// AllowAny and gated only by network_access_allowed(request, "STREAMS"),
// whose default ACL is 0.0.0.0/0 — so this response body reaches an
// unauthenticated caller. The account credential must not appear in it.
//
// KNOWN BUG — see #89. This assertion is the CORRECT behaviour; it fails
// today, on both halves: the credential does appear in the 500 body, and
// the failure does surface as a 500.
//
// test.fail() caveat: it is satisfied by ANY failure in the body, guards
// included — so a broken premise, not just the intended assertion, would
// also read as "expected failure" and this test would go green while
// proving nothing. This pin asserts an ABSENCE (the credential must not
// appear in the response), and an absence is exactly the shape an
// unguarded premise can counterfeit: any failure before the credential
// check even runs — seedVodMovie's own `waitFor.resource` never resolving,
// the fault arm itself throwing — reads as the same "expected failure" as
// the credential genuinely leaking, and this test would go green having
// verified a security property that was never checked. The two
// non-inverted controls above ('a seeded VOD movie streams successfully
// when no fault is armed' and 'the not-found fault on a VOD movie route
// produces a genuine streaming failure') are what actually guard it: the
// first proves the seed-and-ingest sequence produces a movie that
// genuinely streams, and the second proves the 'not-found' fault genuinely
// reaches the streaming-error path this pin's premise depends on.
test.fail('an upstream failure on the VOD stream route does not return the provider credential', { tag: '@contract' }, async ({
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
