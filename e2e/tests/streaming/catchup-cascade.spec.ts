import { test, expect, expectTsAligned } from '../../fixtures';
import type { Channel, StreamPage } from '../../fixtures';
import {
  catchupRequests,
  catchupTimestamp,
  newStreamClient,
  seedCatchupChannel,
} from './helpers';

/**
 * Drives `/proxy/catchup/<Channel.uuid>` — the **native** catch-up surface
 * (spec inventory row 5), not the root `/timeshift/...` XC route
 * `catchup-path-layout.spec.ts` already covers. Both routes end up in the
 * same shared `_serve_catchup` (apps/timeshift/views.py), which is what
 * calls `build_timeshift_candidate_urls` and runs the seven-candidate
 * cascade under test here — so the cascade behaviour itself does not differ
 * by entry point, and driving it from the native surface is what proves
 * that surface is wired end to end rather than leaving it completely
 * unexercised by this goal.
 *
 * Authenticated with the admin JWT `api` fixture already holds, not an XC
 * end-user: the native route's `authentication_classes` are
 * JWTAuthentication/ApiKeyAuthentication/QueryParamJWTAuthentication, not
 * `_authenticate_user`'s XC username/password, so no `seed.xcUser()`
 * stand-in is needed for this proof at all.
 */
test('the candidate cascade falls through to the QUERY layout when PATH 404s', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  // A FRESH account, deliberately: _set_cached_format_index caches the
  // winning candidate index per account in the Django cache, and a reused
  // account would start the walk at whatever last worked rather than at
  // candidate 0.
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });

  // No clearFault / teardown needed: FaultStore keys every armed fault by
  // scenario id (e2e-upstream/src/faults.ts), and `scenario` above is a
  // fresh one this test alone addresses — no other spec or worker can ever
  // reach it, so the fault cannot leak past this test.
  await upstream.fault(scenario, 'catchup-layout-404', { layout: 'path' });

  const requestInstant = new Date(Date.now() - 2 * 60 * 60 * 1000);
  const start = catchupTimestamp(requestInstant);
  const token = await api.freshAccessToken();

  // ?start=&duration= is the native route's own direct-auth shape
  // (apps/timeshift/views.py's catchup_proxy docstring); duration goes
  // through the identical client_duration_to_window() as the PATH route's
  // URL segment, so the same +5-minute buffer assertion below is valid here
  // too. Like the PATH route, a session-less first request gets a
  // same-origin 301 minting a session_id, which streamClient.open follows
  // automatically.
  await streamClient.open(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expect((await streamClient.readPackets(20))[0]).toBe(0x47);
  await streamClient.close();

  const log = await upstream.log(scenario);
  const attempts = log.filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('timeshift')
  );

  // build_timeshift_candidate_urls emits three PATH shapes, then four QUERY
  // shapes (apps/timeshift/helpers.py:466-498). With PATH blocked, a walk
  // that reaches QUERY at all could still be wrong in three ways a bare
  // count can't catch: the three PATH attempts could carry the *same*
  // timestamp shape instead of three distinct ones (a shape-derivation
  // regression would still 404 three times and fall through), QUERY could
  // be tried before PATH is exhausted, or the wrong QUERY candidate could
  // win. The assertions below pin candidate identity and order — not shape
  // *correctness*, which COVERAGE.md:63/85 assigns to G10.
  const pathAttempts = attempts.filter((e) => e.path!.includes('/timeshift/'));
  const queryAttempts = attempts.filter((e) => e.path!.includes('timeshift.php'));

  expect(pathAttempts).toHaveLength(3);
  expect(pathAttempts.every((e) => e.status === 404)).toBe(true);
  expect(queryAttempts.length).toBeGreaterThan(0);
  expect(queryAttempts[0].status).toBe(200);

  // Order: the three PATH attempts are the first three "timeshift" requests
  // logged, and the winning QUERY attempt is the fourth. `attempts` is
  // filtered but order-preserving (ScenarioLog.record appends;
  // e2e-upstream/src/log.ts:30-35), so this is a direct check on arrival
  // order, not an inference from the split-out arrays.
  expect(attempts.slice(0, 3)).toEqual(pathAttempts);
  expect(attempts[3]).toEqual(queryAttempts[0]);

  // And the cascade STOPS at the winner. Without this, a cascade that kept
  // walking candidates 4-6 after its 200, or that retried the whole list,
  // would be invisible: every assertion above is satisfied by a prefix of
  // the log. Four is the whole of it — three PATH 404s then one QUERY 200.
  expect(attempts).toHaveLength(4);

  // Identity: each PATH attempt carries a distinct strftime shape, in the
  // exact order build_timeshift_candidate_urls emits them — colon-dash,
  // underscore, then colon-seconds — and the winning QUERY attempt is
  // specifically candidate index 3 (format_a + underscore_ts), the first
  // QUERY shape in that order. Derived from the same `requestInstant` the
  // request itself used, not re-parsed from the response, so this fails if
  // the product ever reorders or collapses the candidate list.
  const pad = (n: number): string => String(n).padStart(2, '0');
  const y = requestInstant.getUTCFullYear();
  const mo = pad(requestInstant.getUTCMonth() + 1);
  const d = pad(requestInstant.getUTCDate());
  const h = pad(requestInstant.getUTCHours());
  const mi = pad(requestInstant.getUTCMinutes());
  const colonDashTs = start; // %Y-%m-%d:%H-%M — catchupTimestamp already emits this shape
  const underscoreTs = `${y}-${mo}-${d}_${h}-${mi}`; // %Y-%m-%d_%H-%M
  // Seconds are always "00" here, not requestInstant's actual seconds:
  // `start` carries no seconds (catchupTimestamp's colon-dash shape omits
  // them), and normalize_catchup_timestamp_input defaults an absent second
  // to "00" (apps/timeshift/helpers.py:94) before this shape is derived.
  const colonSecondsTs = `${y}-${mo}-${d}:${h}:${mi}:00`; // %Y-%m-%d:%H:%M:%S

  expect(pathAttempts[0].path).toContain(`/${colonDashTs}/`);
  expect(pathAttempts[1].path).toContain(`/${underscoreTs}/`);
  expect(pathAttempts[2].path).toContain(`/${colonSecondsTs}/`);

  expect(queryAttempts[0].path).toContain(`username=${scenario.username}`);
  expect(queryAttempts[0].path).toContain('duration=65');
  expect(queryAttempts[0].path).toContain(`start=${underscoreTs}`);
});

/**
 * The four `strftime` outputs `build_timeshift_candidate_urls` emits across
 * its seven candidates (`apps/timeshift/helpers.py:466-498`), derived here
 * from the same instant the request itself used — not re-parsed from a
 * response — so a product change that reorders or collapses the candidate
 * list fails these tests instead of quietly passing them.
 *
 * Seconds are always "00": `catchupTimestamp` emits the colon-dash shape
 * with no seconds, and `normalize_catchup_timestamp_input` defaults an
 * absent second to "00" (`helpers.py:94`) before any shape is derived.
 * `catchup-provider-timezone.spec.ts` is where a non-zero second is driven.
 */
function candidateShapes(instant: Date) {
  const pad = (n: number): string => String(n).padStart(2, '0');
  const d = `${instant.getUTCFullYear()}-${pad(instant.getUTCMonth() + 1)}-${pad(instant.getUTCDate())}`;
  const h = pad(instant.getUTCHours());
  const mi = pad(instant.getUTCMinutes());
  return {
    colonDash: `${d}:${h}-${mi}`, // %Y-%m-%d:%H-%M
    underscore: `${d}_${h}-${mi}`, // %Y-%m-%d_%H-%M
    colonSeconds: `${d}:${h}:${mi}:00`, // %Y-%m-%d:%H:%M:%S
    sql: `${d} ${h}:${mi}:00`, // %Y-%m-%d %H:%M:%S — a LITERAL SPACE
  };
}

test('an all-404 provider draws out all seven candidates, in order, over exactly four shapes', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  // A FRESH account, and this is load-bearing rather than hygiene:
  // `_set_cached_format_index` writes `timeshift:format_idx:<account_id>`
  // into the Django cache (Redis, DB 0) with a 3600s TTL
  // (views.py:3145-3148). A reused account would start the walk at whatever
  // last worked and this test would observe a rotation, not the canonical
  // order.
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });

  // `not-found`, not `catchup-layout-404`: the layout fault lets QUERY
  // candidate 3 win, so the walk stops there and candidates 4-6 are never
  // sent. `catchup-cascade`'s G8 test above covers that shape of walk. This
  // one needs every candidate on the wire, and only an all-404 provider
  // produces that — the layout fault deliberately refuses to block both
  // layouts (`parseFaultRequest`, e2e-upstream/src/faults.ts).
  await upstream.fault(scenario, 'not-found');

  const instant = new Date(Date.now() - 2 * 60 * 60 * 1000);
  const start = catchupTimestamp(instant);
  const shapes = candidateShapes(instant);
  const token = await api.freshAccessToken();

  const res = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );

  // Exhaustion with `last_status == 404` maps to a client 404
  // (views.py:3335-3337).
  expect(res.status()).toBe(404);
  expect(await res.text()).toContain('Catch-up not available yet');

  const asked = catchupRequests(await upstream.log(scenario));
  // Subsumed by the seven-element `toEqual` below; kept anyway so a wrong
  // count fails with "seven candidates, all attempted" instead of a diff
  // against a seven-element array.
  expect(asked, 'seven candidates, all attempted').toHaveLength(7);

  // THE FOUR SHAPES, in the exact candidate order
  // `build_timeshift_candidate_urls` emits them
  // (apps/timeshift/helpers.py:490-498). This is the assertion G8's
  // plumbing proof structurally could not make: it stops at candidate 3, so
  // candidate 4 — the SQL shape, the only one carrying a literal space — has
  // never been observed on the wire by anything in this repo.
  expect(asked.map((a) => [a.layout, a.start])).toEqual([
    ['path', shapes.colonDash],
    ['path', shapes.underscore],
    ['path', shapes.colonSeconds],
    ['query', shapes.underscore],
    ['query', shapes.sql],
    ['query', shapes.colonDash],
    ['query', shapes.colonSeconds],
  ]);

  // ALL 404 — and that is a second, independent assertion, not a
  // restatement. The provider validates the timestamp shape in `handleXc`
  // BEFORE `serveChannelStream` ever sees the `not-found` fault
  // (e2e-upstream/src/xc/router.ts), answering an unrecognised shape with a
  // 400 that names it. G8's parser accepts exactly these four and rejects
  // the eight hybrid separator/seconds combinations, so a Dispatcharr
  // regression that emitted e.g. `2026-08-30 14-00` would show up here as a
  // 400 in this list rather than as a silent pass.
  expect(asked.map((a) => a.status)).toEqual([404, 404, 404, 404, 404, 404, 404]);

  // Every candidate carried the same requested instant, in four
  // spellings. This proves the right moment was asked for, seven times over.
  // It does not prove Dispatcharr seeks to it: the fake archive serves the
  // same loop whatever `start` it is given — and here it served nothing at
  // all.
});

test('the winning candidate index is cached per account and promoted on the next walk', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
  baseURL,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  await upstream.fault(scenario, 'catchup-layout-404', { layout: 'path' });

  // FOUR DIFFERENT INSTANTS, one per drive — kept distinct for the one
  // reason that survives scrutiny, not to dodge pool adoption. Disconnect
  // does NOT delete the pool entry: it runs release_cb ->
  // _make_release_once._release() -> _release_pool_session
  // (views.py:2342-2381), which with mark_pool_idle=True sets "busy": "0"
  // and re-arms the TTL — the entry survives, merely marked idle.
  // `_discard_pool_session` (views.py:2423-2440) is a different path, not
  // the one disconnect takes. Nor did distinct `start` values ever defeat
  // adoption: `_find_matching_pool_session` matches on the
  // `{channel_id}_` prefix, and Node's fetch sends `user-agent: node`, so
  // the fingerprint scores the full 8 against _MATCH_SCORE_THRESHOLD = 8
  // (views.py:95) regardless of `start`. The decisive fact is that adopting
  // an idle pooled session still calls `_attempt_timeshift_stream`
  // (views.py:2878) — it contacts the provider either way, so a
  // provider-request count cannot discriminate adoption from a fresh walk
  // at all, and no assertion in this test infers adoption from one. Distinct
  // `start` values are kept anyway, for the reason that never depended on
  // any of this: they prove each walk asked for its *own* moment rather than
  // several walks repeating one — a stronger property than reusing a single
  // `start` would give this test. It costs the cache proof nothing:
  // `timeshift:format_idx:<account_id>` (apps/timeshift/redis_keys.py:64-65)
  // has no timestamp in the key.
  const firstInstant = new Date(Date.now() - 2 * 60 * 60 * 1000);
  const secondInstant = new Date(Date.now() - 3 * 60 * 60 * 1000);
  const thirdInstant = new Date(Date.now() - 4 * 60 * 60 * 1000);
  const fourthInstant = new Date(Date.now() - 5 * 60 * 60 * 1000);
  const secondShapes = candidateShapes(secondInstant);
  const thirdShapes = candidateShapes(thirdInstant);
  const token = await api.freshAccessToken();
  const urlFor = (uuid: string, instant: Date): string =>
    `/proxy/catchup/${uuid}?start=${encodeURIComponent(catchupTimestamp(instant))}&duration=60`;

  // Walk 1: three PATH 404s, then QUERY candidate 3 wins and is cached.
  await streamClient.open(urlFor(channel.uuid, firstInstant), {
    headers: { Authorization: `Bearer ${token}` },
  });
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const afterFirst = catchupRequests(await upstream.log(scenario));
  expect(afterFirst).toHaveLength(4);

  // Walk 2: the SAME account, deliberately — the one place in this goal
  // where reusing an account is the assertion rather than the hazard.
  // `_set_cached_format_index(account_id, winning_index)` (views.py:3330)
  // stored 3 under `timeshift:format_idx:<account_id>`, and
  // `_stream_from_provider` reorders the walk to put it first
  // (views.py:3218-3229).
  const again = newStreamClient(baseURL!);
  await again.open(urlFor(channel.uuid, secondInstant), {
    headers: { Authorization: `Bearer ${token}` },
  });
  expectTsAligned(await again.readPackets(20));
  await again.close();

  const secondWalk = catchupRequests(await upstream.log(scenario)).slice(4);
  expect(secondWalk, 'the cached winner is tried first and wins immediately').toHaveLength(1);
  expect(secondWalk[0].layout).toBe('query');
  expect(secondWalk[0].start).toBe(secondShapes.underscore);
  expect(secondWalk[0].status).toBe(200);
  // The second walk asked for its own moment, in the cached shape. This
  // proves the right moment was asked for. It does not prove Dispatcharr
  // seeks to it: the fake archive serves the same loop whatever `start` it is
  // given.

  // A DIFFERENT Channel, but the SAME account, driven with its own instant.
  // Walk 3 below changes the account AND the channel together, so on its
  // own it can only rule out a GLOBAL cache — it cannot tell "keyed per
  // account" apart from "keyed per channel", since both predict the same
  // outcome there. Wiring a second Channel to the same ingested Stream
  // isolates the channel variable: same account, same underlying Stream, a
  // fresh Channel row and uuid. `format_cache` keys solely on `account_id`
  // (apps/timeshift/redis_keys.py:64-65) with no channel in the key, so
  // this drive should hit the cache exactly like walk 2 did.
  const createdSameAccount = await seed.channel({ streams: [channel.streams[0]] });
  const sameAccountChannel = await api.json<Channel>(
    await api.get(`/api/channels/channels/${createdSameAccount.id}/`),
    `channel ${createdSameAccount.id} after wiring the first account's stream a second time`
  );
  expect(
    sameAccountChannel.is_catchup,
    'a second channel on the same account is catch-up before it is driven'
  ).toBe(true);

  const sameAccountDrive = newStreamClient(baseURL!);
  await sameAccountDrive.open(urlFor(sameAccountChannel.uuid, fourthInstant), {
    headers: { Authorization: `Bearer ${token}` },
  });
  expectTsAligned(await sameAccountDrive.readPackets(20));
  await sameAccountDrive.close();

  const sameAccountWalk = catchupRequests(await upstream.log(scenario)).slice(5);
  expect(
    sameAccountWalk,
    'a different channel on the same account still hits the cached winner'
  ).toHaveLength(1);
  expect(sameAccountWalk[0].layout).toBe('query');
  // As everywhere in this goal: this drive asked for its own moment. It
  // does not prove Dispatcharr seeks to it — the fake archive serves the
  // same loop whatever `start` it is given.

  // NOT GLOBAL, either. A second XC account against the SAME provider
  // scenario must start its own walk at candidate 0 — together with the
  // drive above, this pins the cache key as account-scoped and nothing
  // coarser (not global) or finer (not tied to a particular Channel row).
  const secondAccount = await seed.xcAccount(scenario);
  expect((await waitFor.m3uRefreshComplete(secondAccount.id)).status).toBe('success');

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(scenario.username!.replace(/-user$/, ''))}`),
    'streams from both accounts'
  );
  const mine = page.results.find((s) => s.m3u_account === secondAccount.id);
  expect(mine, 'a Stream belonging to the second account').toBeDefined();

  // Re-read, do not trust the POST response. The `ChannelStream` signal
  // (`update_channel_catchup_fields`, apps/channels/signals.py:393-407)
  // writes with `Channel.objects.filter(pk=...).update(...)`, which never
  // touches the in-memory instance the serializer rendered. Skip this and a
  // false flag surfaces below as `400 "Timeshift not supported for this
  // channel"`, which reads as a cascade bug and is not one.
  const createdSecond = await seed.channel({ streams: [mine!.id] });
  const secondChannel = await api.json<Channel>(
    await api.get(`/api/channels/channels/${createdSecond.id}/`),
    `channel ${createdSecond.id} after wiring the second account's stream`
  );
  expect(
    secondChannel.is_catchup,
    'the second account\'s channel is catch-up before it is driven'
  ).toBe(true);

  const third = newStreamClient(baseURL!);
  await third.open(urlFor(secondChannel.uuid, thirdInstant), {
    headers: { Authorization: `Bearer ${token}` },
  });
  expectTsAligned(await third.readPackets(20));
  await third.close();

  const thirdWalk = catchupRequests(await upstream.log(scenario)).slice(6);
  // FOUR, asserted before anything is indexed. The second account has no
  // cached index, so it restarts at candidate 0 and walks the full
  // PATH-blocked route — three 404s then the QUERY winner, exactly as walk 1
  // did. Asserting the length first is what turns an empty walk into a named
  // failure instead of `TypeError: Cannot read properties of undefined`.
  expect(thirdWalk, 'a fresh account restarts the walk at candidate 0').toHaveLength(4);
  expect(thirdWalk[0].layout).toBe('path');
  expect(thirdWalk[0].start).toBe(thirdShapes.colonDash);
  // As everywhere in this goal: the third walk asked for its own moment in
  // the canonical first shape. It does not prove Dispatcharr seeks to it —
  // the fake archive serves the same loop whatever `start` it is given.
});

test('a provider 401 is decisive: one attempt, and the client gets 400, not 401', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  await upstream.fault(scenario, 'auth-failure');

  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const token = await api.freshAccessToken();

  const res = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );

  // 400, NOT 401. `_stream_from_provider` maps exhaustion by `last_status`:
  // 404 → 404, 403 → 403, and EVERYTHING ELSE → 400 "Provider error"
  // (views.py:3335-3341). A provider 401 therefore reaches the client as a
  // 400. That is deliberate per the code's own comment, not a defect — but
  // it is exactly the kind of thing a test that asserted the "obvious" 401
  // would have got wrong.
  expect(res.status()).toBe(400);
  expect(await res.text()).toContain('Provider error');

  const asked = catchupRequests(await upstream.log(scenario));
  // ONE. `code in (401, 403, 406)` sets `decisive_failure` and breaks
  // (views.py:3323-3326) — the remaining six candidates are not tried,
  // because an account whose credentials are refused will refuse them in
  // every URL shape too.
  expect(asked).toHaveLength(1);
  expect(asked[0].status).toBe(401);
});

test('a 200 carrying no TS sync is downgraded to a soft 404 and the whole walk continues', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  // `non-ts-bytes` answers 200 with an HTML error page
  // (e2e-upstream/src/server.ts's serveChannelStream, fault 5) — which is
  // what a real provider's PHP actually sends when it is unhappy, and the
  // single most useful failure mode in this file.
  await upstream.fault(scenario, 'non-ts-bytes');

  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const token = await api.freshAccessToken();

  const res = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expect(res.status()).toBe(404);
  expect(await res.text()).toContain('Catch-up not available yet');

  const asked = catchupRequests(await upstream.log(scenario));
  // Seven attempts, every one answered 200. `find_ts_sync` finds no sync
  // byte in the first 1024, so `last_status` is forced to 404 and the loop
  // CONTINUES (views.py:3301-3312) — a 200 is not evidence of success on
  // this path. Asserting the statuses as well as the count is what
  // distinguishes this from the all-404 row: same count, opposite provider
  // behaviour, same client outcome.
  expect(asked).toHaveLength(7);
  expect(asked.every((a) => a.status === 200)).toBe(true);
});
