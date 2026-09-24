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

// The first non-inverted control for the two tests below (the flipped #89
// pin, 'an upstream failure on the VOD stream route does not return the
// provider credential', and the #374 test.fail(), 'an upstream failure on
// the VOD stream route still surfaces as a 500'): its premise is that
// seedVodMovie's own scenario, account, refresh-vod POST and
// waitFor.resource ingest wait produce a movie that genuinely streams over
// /proxy/vod/movie/<uuid> when no fault is armed — the account create, the
// ingest wait and the route itself all have to work before either
// downstream test's own assertion is even reachable. No other test in this
// file requests the movie route with no fault armed: the second control
// below arms the 'not-found' fault before its first request, and both
// downstream tests' identical seedVodMovie calls are only ever requested
// with the fault already armed. A break in the seed-and-ingest sequence
// itself (not just in the credential-disclosure or status behaviour) would
// fail the flipped pin loudly on its own, but would still be swallowed by
// the #374 test.fail() as an "expected failure", since test.fail() is
// satisfied by ANY failure in its body, not specifically the regression it
// exists to pin.
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

// The second non-inverted control for the two tests below: the credential
// check (and the status check) have no meaning unless arming the
// 'not-found' fault genuinely drives the request into the connection
// manager's `except Exception` handler at
// multi_worker_connection_manager.py:1409 — or the identical handler
// wrapping it in `stream_vod` (views.py:903) — which is what produces the
// 500 both downstream tests inspect. This control asserts the shape both
// produce (a 500 whose body carries the handler's own fixed prefix), not
// which of the two fired — that distinction doesn't matter to either
// downstream test's premise, only that the fault genuinely reached one of
// them. This control arms that same fault, on its own fresh scenario,
// before making any request at all (so there is no already-open session to
// reuse from a prior clean request), then asserts the failure directly.
// Two other tests in this file now arm this same 'not-found' fault and
// inspect the result: the flipped #89 pin below (a plain test, no longer
// inside a test.fail() body) and the #374 test.fail() below it. A break
// here — the fault not reaching the upstream fetch, or some other status
// reaching the client — would fail the flipped pin loudly on its own, but
// would still be swallowed by the #374 test.fail() as an "expected
// failure", since test.fail() is satisfied by ANY failure in its body, not
// specifically the still-open defect it exists to pin.
//
// Reciprocal note (the Task 8 rule: a non-inverted control must never be
// coupled to a defect's current spelling without saying so): this control's
// `toBe(500)` characterises today's status, which #392 (the #89 fix) left
// unchanged — only the body's credential disclosure was fixed, the status
// itself is #374's open defect ("provider 4xx/5xx other than 416 still
// becomes a VOD 500"), not #89's. So this control's assertion is not a
// stand-in for a pin that will one day flip and force a re-anchor here: it
// now directly backs the #374 test.fail() below, and should be re-anchored
// to the fixed shape only when #374 itself is fixed.
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
      'the not-found fault should drive the request into the VOD error path'
    ).toBe(500);
    expect(
      await res.text(),
      "the failure body should carry the VOD error path's own prefix"
    ).toContain('Streaming error');
  } finally {
    await upstream.clearFault(scenario, 'not-found');
  }
});

// #89 fixed by #392. This used to be one test.fail() carrying two
// assertions (no credential in the body, and no 500 status) — but #392
// only fixes the first half: the body is now a fixed generic string with
// no exception detail, while the status stays 500 (a separate, still-open
// defect, #374). A single test.fail() cannot tell those apart: it is
// satisfied by ANY failure, so after #392 landed this test.fail() would
// still pass — green not because the credential leak is gone but because
// the *status* assertion alone keeps failing — and a credential leak
// reintroduced later would go undetected (the "hollow pin" rule: a pin
// covering two properties, only one of which a fix addresses, must be
// split so each property is asserted where it can actually fail on its
// own). So this is now two tests: this one, a plain `test()`, is the
// flipped #89 pin and owns the credential assertion only; the `test.fail()`
// immediately below owns the status assertion and is attributed to #374.
//
// Any exception raised while establishing the upstream VOD connection
// becomes HttpResponse("Streaming error", status=500)
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:1409, and the
// same shape at apps/proxy/vod_proxy/views.py:903). `stream_vod` is
// AllowAny and gated only by network_access_allowed(request, "STREAMS"),
// whose default ACL is 0.0.0.0/0 — so this response body reaches an
// unauthenticated caller, and the account credential must not appear in
// it — nor may any other exception detail, since the fix is a fixed
// string, not selective redaction.
//
// This test asserts an ABSENCE (the credential must not appear in the
// response) plus the concrete fixed shape the body must now be, so a
// broken premise cannot counterfeit it the way it could a bare
// `not.toContain`: seedVodMovie's own `waitFor.resource` never resolving,
// or the fault arm itself throwing, would fail this test directly (a plain
// `test()`, not test.fail()) rather than reading as an "expected failure".
// The two non-inverted controls above ('a seeded VOD movie streams
// successfully when no fault is armed' and 'the not-found fault on a VOD
// movie route produces a genuine streaming failure') still back the
// seed-and-ingest and fault-delivery premises this test depends on.
test('an upstream failure on the VOD stream route does not return the provider credential', { tag: '@contract' }, async ({
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
    expect(
      body,
      'the fixed VOD error body carries no exception detail, only the generic prefix'
    ).toBe('Streaming error');
  } finally {
    await upstream.clearFault(scenario, 'not-found');
  }
});

// #374 — "provider 4xx/5xx other than 416 still becomes a VOD 500", split
// out of the old #89 pin under the "hollow pin" rule described above: #392
// fixed the credential disclosure but left the status itself untouched, so
// the status half of the original assertion keeps its own test.fail() here
// rather than sharing one with a property #392 already fixed.
//
// test.fail() caveat, same shape as before the split: it is satisfied by
// ANY failure in the body, guards included — so a broken seed-and-ingest
// premise, not just the intended status assertion, would also read as
// "expected failure" and this test would go green while proving nothing.
// The two non-inverted controls above guard that premise the same way they
// did for the pin this test was split from: the first proves the
// seed-and-ingest sequence produces a movie that genuinely streams, and the
// second proves the 'not-found' fault genuinely reaches the streaming-error
// path (asserting the exact same `toBe(500)` this test's premise depends
// on — see the reciprocal note on that control).
test.fail('an upstream failure on the VOD stream route still surfaces as a 500 (#374)', { tag: '@contract' }, async ({
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
    expect(res.status(), 'an upstream failure should not surface as a 500').not.toBe(500);
  } finally {
    await upstream.clearFault(scenario, 'not-found');
  }
});
