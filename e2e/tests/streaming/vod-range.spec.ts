import { test, expect } from '../../fixtures';
import type { ApiClient, Seeder, Waiter, UpstreamClient, Movie, VodPage } from '../../fixtures';

// Provider id 501, so `501.mp4` can be written as a literal below. The id is
// scenario-scoped — every test creates its own scenario and its own account —
// so reusing 501 across tasks is safe and deliberate. Only *names* must be
// generated, because `Movie` is matched across all accounts by
// TMDB -> IMDB -> (name, year). Do not "fix" the reuse by renumbering.
async function seedVodMovie(
  upstream: UpstreamClient,
  seed: Seeder,
  api: ApiClient,
  waitFor: Waiter
) {
  const prefix = seed.generatedName('vodrange');
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

test('Range and seek on the VOD proxy match the provider byte-for-byte', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { scenario, movie } = await seedVodMovie(upstream, seed, api, waitFor);

  // Establish the session with one FULL request first. RedisVODConnection
  // only learns state.content_length on request_count == 1
  // (multi_worker_connection_manager.py:513-531); every Range assertion
  // below depends on the size already being known.
  const full = await request.get(`/proxy/vod/movie/${movie.uuid}`);
  expect(full.status()).toBe(200);
  const total = Number(full.headers()['content-length']);

  // A mid-file range at an offset well past the head G8's proof already
  // covered (vod-byte-read.spec.ts uses bytes=100-199). The asset is
  // generated at Docker build time from unpinned ffmpeg — its length is a
  // runtime fact, not a constant — so guard the offset against the real
  // size before hardcoding anything.
  let start = 40_000;
  let end = start + 8_191;
  if (!(total > end + 1)) {
    start = Math.floor(total / 3);
    end = start + 8_191;
  }
  expect(total).toBeGreaterThan(end + 1);

  const partial = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
    headers: { Range: `bytes=${start}-${end}` },
  });
  expect(partial.status()).toBe(206);
  expect(partial.headers()['content-range']).toBe(`bytes ${start}-${end}/${total}`);
  expect(partial.headers()['content-length']).toBe('8192');

  // Differential comparison against the provider directly — the part that
  // makes this more than an internal-consistency check (spec D8). Proves
  // Dispatcharr returned the REQUESTED bytes, not merely 8192 bytes with
  // plausible headers, which is exactly what defect 6 (Step 4 below) does.
  const direct = await fetch(
    upstream.toControl(`${scenario.internal}/movie/${scenario.username}/${scenario.password}/501.mp4`),
    { headers: { Range: `bytes=${start}-${end}` } }
  );
  expect(direct.status).toBe(206);
  const expected = Buffer.from(await direct.arrayBuffer());
  expect(await partial.body()).toEqual(expected);

  // The open-ended range. _validate_range_header rewrites an empty end_str
  // to content_length - 1, and stream_content_with_session builds
  // Content-Range from the client's requested range and the stored full
  // size.
  const open = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
    headers: { Range: `bytes=${start}-` },
  });
  expect(open.status()).toBe(206);
  expect(open.headers()['content-range']).toBe(`bytes ${start}-${total - 1}/${total}`);

  // The non-inverted control for the test.fail() below ('an unsatisfiable
  // Range on a fresh session is 416, not 500'): on an ESTABLISHED session
  // (content_length already known — `full`, above, made this one), an
  // unsatisfiable Range answers 416. This used to live only inside that
  // test.fail() body, where test.fail() is satisfied by ANY failure, so a
  // regression in the control itself would have been swallowed as
  // "expected failure" and never surfaced. Asserting it here, in a passing
  // test, is what actually guards it.
  const outOfRange = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
    headers: { Range: `bytes=99999999-` },
  });
  expect(outOfRange.status()).toBe(416);
});

// Asserts the behaviour Dispatcharr SHOULD have. On a session's FIRST
// request, `state.content_length` is unset — `get_stream`
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:467) only
// validates a Range when it already knows the size, and it only learns the
// size at `request_count == 1` (:513). So an unsatisfiable Range on a fresh
// session is passed to the provider verbatim; the provider's 416 then hits
// `response.raise_for_status()` (:509) and becomes
// `HttpResponse("Streaming error: ...", status=500)` (:1405). The SAME
// request on an established session returns a correct 416
// ("Requested Range Not Satisfiable", :1114), which the non-inverted control
// assertion in the test above ('Range and seek on the VOD proxy match the
// provider byte-for-byte') proves.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/98
test.fail('an unsatisfiable Range on a fresh session is 416, not 500', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);

  // The control this test used to run inline — an ESTABLISHED session
  // answering 416 correctly — sat inside this test.fail() body, where
  // test.fail() is satisfied by ANY failure in the body: a regression in
  // the control itself would have been swallowed as "expected failure" and
  // never surfaced. It now lives as a non-inverted assertion in the test
  // above ('Range and seek on the VOD proxy match the provider
  // byte-for-byte'), which actually guards it.
  //
  // Subject: a FRESH session (own scenario/account/movie — no earlier
  // request in this test has opened it) gets an unsatisfiable Range as its
  // very first request.
  const subject = await seedVodMovie(upstream, seed, api, waitFor);
  const res = await request.get(`/proxy/vod/movie/${subject.movie.uuid}`, {
    headers: { Range: `bytes=99999999-` },
  });
  expect(res.status()).toBe(416);
});

// Asserts the behaviour Dispatcharr SHOULD have. With `range-unsupported`
// armed, the provider ignores Range and answers 200 with the whole asset
// from offset zero. `stream_content_with_session`
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:1303) then sets
// `status_code = 206 if range_header else 200` regardless of what the
// upstream actually answered, and :1312-1377 fabricates Content-Range and a
// shortened Content-Length purely from the client's requested range and the
// previously-known full size. `stream_generator()` (:1152) is a pure
// passthrough with no offset skipping. So the client gets the HEAD of the
// file under headers describing the slice it asked for — internally
// consistent, spec-shaped, and silently wrong.
//
// Filed as https://github.com/D10Scot/Dispatcharr/issues/66. Do not file a
// second issue for this.
test.fail('a provider that ignores Range still yields the requested bytes', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { scenario, movie } = await seedVodMovie(upstream, seed, api, waitFor);

  // Establish the session with a full request first, so content_length is
  // known and Content-Range can be fabricated at all.
  const full = await request.get(`/proxy/vod/movie/${movie.uuid}`);
  expect(full.status()).toBe(200);
  const total = Number(full.headers()['content-length']);

  const start = Math.floor(total / 3);
  const end = start + 8_191;
  expect(total).toBeGreaterThan(end + 1);

  // Read the asset directly from the provider, through toControl, BEFORE
  // arming the fault — this is the ground truth for the mid-file range.
  const direct = await fetch(
    upstream.toControl(`${scenario.internal}/movie/${scenario.username}/${scenario.password}/501.mp4`),
    { headers: { Range: `bytes=${start}-${end}` } }
  );
  expect(direct.status).toBe(206);
  const expectedBytes = Buffer.from(await direct.arrayBuffer());

  try {
    // Scenario-wide only — a channel is rejected with 400, since a VOD id
    // is not a channel id.
    await upstream.fault(scenario, 'range-unsupported');

    const partial = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
      headers: { Range: `bytes=${start}-${end}` },
    });

    // Assert the BYTES, not the length and not the headers. COVERAGE.md's
    // G8 row records the measured symptom precisely: with a 125,585-byte
    // asset and Range: bytes=100-199, the 100-byte body was byte-identical
    // to bytes 0-99 while the response claimed
    // Content-Range: bytes 100-199/125585. A length-only assertion passes
    // today.
    expect(await partial.body()).toEqual(expectedBytes);
  } finally {
    // range-unsupported is scenario-scoped and the scenario outlives the
    // test; leaving it armed makes the next test in the file read the
    // wrong thing if the file is ever reordered.
    await upstream.clearFault(scenario, 'range-unsupported');
  }
});

// Asserts the behaviour Dispatcharr SHOULD have. RFC 9110's `bytes=-500`
// means "the last 500 bytes". `_validate_range_header`
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:580-612) splits
// on the first '-' and treats an empty start_str as `start_byte = 0`, then
// rewrites the header to `bytes=0-500` — the client asking for the tail of a
// file is served the head, with a 206 and a Content-Range describing the
// wrong slice, and no error anywhere. The provider's own `parseRange`
// (e2e-upstream/src/vod-asset.ts) implements the suffix form correctly, so
// the upstream is not the source of this.
//
// Filed as https://github.com/D10Scot/Dispatcharr/issues/64. Do not file a
// second issue for this.
test.fail('a suffix Range returns the tail of the file', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  test.setTimeout(180_000);
  const { scenario, movie } = await seedVodMovie(upstream, seed, api, waitFor);

  // The rewrite happens in _validate_range_header, which only runs once
  // content_length is known — on a fresh session the suffix header would
  // reach the provider unmodified and succeed, which would make this test
  // pass for the wrong reason. So establish the session with a full request
  // first.
  const full = await request.get(`/proxy/vod/movie/${movie.uuid}`);
  expect(full.status()).toBe(200);
  const total = Number(full.headers()['content-length']);

  expect(total).toBeGreaterThan(500);
  const direct = await fetch(
    upstream.toControl(`${scenario.internal}/movie/${scenario.username}/${scenario.password}/501.mp4`)
  );
  expect(direct.status).toBe(200);
  const assetBytes = Buffer.from(await direct.arrayBuffer());
  expect(assetBytes.byteLength).toBe(total);

  const res = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
    headers: { Range: `bytes=-500` },
  });
  expect(res.status()).toBe(206);
  const body = await res.body();
  expect(body.byteLength).toBe(500);
  expect(body).toEqual(assetBytes.subarray(total - 500));
});
