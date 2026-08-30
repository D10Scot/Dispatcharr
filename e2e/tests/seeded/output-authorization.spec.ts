import { test, expect, xcQuery } from '../../fixtures';
import type { XcUser } from '../../fixtures';

/**
 * G5 rows 11-13 (D5, D6, D14): the XC authorization matrix, the
 * `hide_adult_content` filter, and a characterization of the three output
 * surfaces that apply no authorization at all.
 *
 * GATE (spec's Step 1), run once against a live container before this file
 * was written: `seed.xcUser({ user_level: 10 })` followed by
 * `GET /api/accounts/users/<id>/` came back `user_level: 10` — the API
 * accepts a level-10 user through the normal create path. The matrix below
 * therefore covers all three levels (0, 1, 10), not the two-level fallback.
 * Never done through the shared bootstrap admin: that identity is read-only
 * and shared across four workers.
 */

type XcStream = { stream_id: number; name: string };

async function liveStreams(
  request: { get: (url: string) => Promise<{ text(): Promise<string> }> },
  user: XcUser
): Promise<XcStream[]> {
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_live_streams' })}`
  );
  return JSON.parse(await res.text());
}

test('the XC catalogue is scoped to the requesting principal user_level', async ({
  seed,
  request,
}) => {
  const group = await seed.channelGroup();
  const levels = [0, 1, 10] as const;

  const channels = Object.fromEntries(
    await Promise.all(
      levels.map(async (level) => [
        level,
        await seed.channel({ channel_group_id: group.id, user_level: level }),
      ])
    )
  ) as Record<(typeof levels)[number], { id: number; name: string }>;

  // Seeded users, never the bootstrap admin: that identity is shared across
  // four workers and read-only. Costs zero logins — XC authentication is
  // query-string credentials against an unthrottled path, which is what makes
  // a nine-cell matrix free here where a JWT matrix would not be.
  for (const level of levels) {
    const user = await seed.xcUser({ user_level: level });
    const visible = new Set((await liveStreams(request, user)).map((s) => s.stream_id));

    // Restricted to OUR three channels. The catalogue also contains every
    // other worker's, so a set comparison against the whole response would
    // fail at 4 workers and pass at 1.
    const seen = levels.filter((l) => visible.has(channels[l].id));
    const expected = levels.filter((l) => l <= level);

    expect(seen, `a user_level ${level} principal`).toEqual(expected);
  }
});

test('a principal cannot read the EPG of a channel above its level', async ({
  seed,
  request,
}) => {
  const allowed = await seed.channel({ user_level: 0 });
  const above = await seed.channel({ user_level: 10 });
  const user = await seed.xcUser({ user_level: 0 });

  // Positive control (Task 8's ruling, reaffirmed for this task): same user,
  // same action, a channel it IS allowed to see. Without this, the 404 below
  // could mean "get_short_epg always 404s", or "this account is broken", just
  // as easily as it could mean "the level filter refused it" —
  // xc_get_epg (apps/output/views.py:785) 404s on both "channel not found"
  // and "channel not authorized" alike, so only a same-credentials success
  // proves the account and endpoint work at all.
  const controlRes = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: allowed.id })}`
  );
  expect(controlRes.status(), 'positive control: get_short_epg for an allowed channel').toBe(
    200
  );
  const controlBody = await controlRes.json();
  expect(
    Array.isArray(controlBody.epg_listings),
    'positive control: epg_listings shape'
  ).toBe(true);

  // Asserted on get_short_epg rather than on stream_xc: these channels have
  // no Stream rows, so a /live/ request would fail for two possible reasons
  // and prove neither. stream_xc's filtering is row 16's job (Task 12),
  // where there is a real upstream to succeed against.
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: above.id })}`
  );
  expect(res.status()).toBe(404);
});

test('hide_adult_content removes an adult channel from every XC listing path', async ({
  seed,
  request,
}) => {
  const clean = await seed.channel({ user_level: 0 });
  const adult = await seed.channel({ user_level: 0, is_adult: true });
  const user = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  const visible = new Set((await liveStreams(request, user)).map((s) => s.stream_id));
  expect(visible.has(clean.id), 'the non-adult channel should still be listed').toBe(true);
  expect(visible.has(adult.id), 'get_live_streams').toBe(false);

  const playlist = await (await request.get(`/get.php${xcQuery(user)}`)).text();
  expect(playlist).toContain(clean.name);
  expect(playlist, 'get.php').not.toContain(adult.name);

  const guide = await (await request.get(`/xmltv.php${xcQuery(user)}`)).text();
  // Paired: without the presence half, a 401, an error body or an empty
  // guide would all satisfy the absence half too.
  expect(guide, 'xmltv.php').toContain(clean.name);
  expect(guide, 'xmltv.php').not.toContain(adult.name);

  // The per-channel EPG action applies the same filter, so it 404s rather
  // than leaking the programme titles of a channel the user cannot list.
  //
  // Positive control on THIS endpoint (Task 8's ruling is per assertion, not
  // per file — the 200 proven in "cannot read the EPG of a channel above its
  // level" above is a different principal and a different channel, and
  // doesn't cover this test's assertion): same user, the clean channel it IS
  // allowed to list, before asserting 404 on the adult one.
  const cleanEpg = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: clean.id })}`
  );
  expect(cleanEpg.status(), 'positive control: get_short_epg for the clean channel').toBe(200);

  const epg = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: adult.id })}`
  );
  expect(epg.status(), 'get_short_epg for the adult channel').toBe(404);
});

/**
 * NOT a `test.fail()`. This pins the product's ACTUAL authorization model for
 * three of its four output surfaces, and that model is deliberate: the
 * /output/ URLconf passes only `profile_name` (so `generate_m3u` and
 * `generate_epg` run with `user = None` and no filter at all), and the four
 * HDHomeRun views are `permission_classes = [AllowAny]` with no principal.
 * The only gate is the M3U_EPG network ACL, which defaults to loopback and
 * private ranges.
 *
 * **If this test goes red, the product changed and THIS TEST needs updating**
 * — the opposite of every `test.fail()` row in this suite, where red means
 * the product was fixed. Say so to whoever is reading the failure.
 *
 * R13 — the reciprocal half of a matched pair. `hdhr.spec.ts`'s
 * `test.fail('hdhr lineup does not expose adult or above-level channels', ...)`
 * asserts a `user_level: 10, is_adult: true` channel is ABSENT from
 * `/hdhr/lineup.json`; the `/hdhr/lineup.json` assertion below asserts the
 * opposite — that an unauthenticated caller CAN see a `user_level: 10`
 * channel — because that is what today's code actually does. Both are
 * correct descriptions of today. The day
 * https://github.com/D10Scot/Dispatcharr/issues/82 is fixed, `hdhr.spec.ts`'s
 * test flips green as expected and this one's `/hdhr/lineup.json` assertion
 * flips red as an intended false alarm — a matched pair, not one
 * unexplained failure.
 */
test('the anonymous output surfaces apply no user_level filter at all', async ({
  seed,
  request,
}, testInfo) => {
  const restricted = await seed.channel({ user_level: 10 });

  // Cache-busting for the same reason as the `?days=` below, but a different
  // mechanism: generate_m3u (apps/output/views.py:109-136) keys its own
  // Redis cache on `f"{profile}:{user}:{request.GET.urlencode()}:origin=..."`
  // with NO per-channel invalidation, so a bare, unparameterized
  // `/output/m3u` is the SAME cache key for every anonymous caller on the
  // instance — including output-m3u.spec.ts's own unparameterized request.
  // Its TTL is only 2 seconds, not 300, but under this project's
  // `fullyParallel: true, workers: 4` that is still enough real contention to
  // fail intermittently: reproduced twice in a row against this stack before
  // this param was added (this test's own anonymous GET primed the cache
  // moments before output-m3u.spec.ts's channel existed, or vice versa), and
  // zero times in three repeats after. `e2e` is not one of the params
  // generate_m3u reads (`cachedlogos`, `direct`, `output_profile`,
  // `output_format`/`output`, `tvg_id_source`) so it changes the cache key
  // without changing the rendered content.
  const bust = Math.random().toString(36).slice(2);
  const playlist = await (await request.get(`/output/m3u?e2e=${bust}`)).text();
  expect(playlist, '/output/m3u').toContain(restricted.name);

  // A ?days= nothing else will reuse, for the same reason output-epg.spec.ts
  // has one: /output/epg is served from a 300-second Redis chunk cache whose
  // key contains `days` but NOT the raw query string, and creating a channel
  // does not invalidate it. A value fixed per worker would collide with this
  // same test's previous run inside that window. See D7 in the design doc.
  //
  // Deliberately 1-30, not the wider 1-365 the `days` clamp alone would
  // allow — matching output-epg.spec.ts's uniqueDays(), for the same reason
  // documented there: generate_epg gives every EPG-less channel on the
  // instance 6 programmes/day, for every channel any seeded test has ever
  // left behind, not just this one's. Confirmed against this stack: a
  // `?days=365` fetch here threw `Cannot create a string longer than
  // 0x1fffffe8 characters` — a real overflow, not just slow — before this
  // was narrowed to match.
  //
  // Accepted risk, shared with output-epg.spec.ts's own uniqueDays(): both
  // draw from the same 30 buckets against the same anonymous EPG cache key
  // (no username segment for a request with no XC credentials) inside the
  // same 300-second TTL, so a same-bucket collision between this test and
  // that one — or two runs of this file inside the window — is possible.
  // Fail-safe, not silent: a collision serves a body from before THIS
  // channel existed, so it fails this assertion (never a false pass). If
  // this test goes red on `/output/epg` alone with no obvious cause, a
  // bucket collision is the first thing to check before suspecting the
  // product.
  const days = 1 + ((testInfo.workerIndex * 89 + Math.floor(Math.random() * 300)) % 30);
  const guide = await (await request.get(`/output/epg?days=${days}`)).text();
  expect(guide, '/output/epg').toContain(restricted.name);

  const lineup = await (await request.get('/hdhr/lineup.json')).json();
  expect(
    lineup.map((entry: { GuideName: string }) => entry.GuideName),
    '/hdhr/lineup.json'
  ).toContain(restricted.name);
});
