import { test, expect, expectTsAligned, xcLiveStreams, StreamStatusError } from '../../fixtures';
import {
  catchupRequests,
  catchupTimestamp,
  newStreamClient,
  seedCatchupChannel,
  withDeadline,
} from './helpers';

/**
 * Catch-up proxy mode, end to end, across every entry point that reaches
 * `_serve_catchup` (`apps/timeshift/views.py:344`).
 *
 * THE LIMIT THAT GOVERNS EVERY ASSERTION IN THIS FILE. G8's archive is not
 * time-addressable: the catch-up routes serve the same looping TS whatever
 * `start` they are given (`e2e-upstream/src/xc/router.ts`). So every time
 * assertion below reads the URL Dispatcharr **sent**, out of the provider's
 * scenario log, and never the bytes that came back. These tests prove the
 * right moment was ASKED FOR. They do not prove Dispatcharr seeks to it, and
 * a green run here is not evidence that it does.
 *
 * `catchup-path-layout.spec.ts` (G8) already drives the root PATH route as a
 * plumbing proof. This file goes past it: an exact request count instead of
 * `> 0`, the root QUERY route it never touched, the minted-session playback
 * nothing has driven, and the `hide_adult_content` hole.
 */

test('proxy mode streams a catch-up programme and asks the provider for exactly it', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const token = await api.freshAccessToken();

  await streamClient.open(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const asked = catchupRequests(await upstream.log(scenario));

  // EXACTLY one. G8's plumbing proof settled for `> 0`; the exact count is
  // what rules out a retry loop, a duplicated walk, or a second connection
  // opened behind the first. The session-minting 301 (views.py:1594-1602)
  // never reaches the provider, so one client request is one upstream
  // request.
  expect(asked).toHaveLength(1);
  expect(asked[0].layout).toBe('path'); // candidate 0 wins unfaulted
  expect(asked[0].status).toBe(200);
  expect(asked[0].username).toBe(scenario.username);
  expect(asked[0].password).toBe(scenario.password);

  // The PROVIDER's stream id — `Stream.custom_properties['stream_id']`
  // (views.py:1641), which `StreamSerializer` never exposes, so the log is
  // the only place it is observable at all (COVERAGE.md's Catch-up gap row).
  expect(asked[0].streamId).toBe(String(providerStreamId));

  // 60 requested + DURATION_BUFFER_MINUTES (5) = 65
  // (apps/timeshift/helpers.py:25, :197-222). Assert the derived value: 60
  // would pass even if the pad were silently dropped, and the pad is there
  // because provider archives lag live.
  expect(asked[0].duration).toBe('65');

  // Unchanged, because the scenario declares server_info.timezone "UTC" and
  // `convert_timestamp_to_provider_tz` returns its input untouched for
  // exactly that value (helpers.py:145-146) — `seedCatchupChannel` already
  // waited for it to land on the account profile, so this is a real
  // assertion and not a coincidence of a null timezone behaving the same
  // way.
  expect(asked[0].start).toBe(start);

  // This proves the right moment was asked for. It does not prove
  // Dispatcharr seeks to it: the fake archive serves the same loop whatever
  // `start` it is given.
});

test('both root XC entry points reach the same cascade, whatever layout the client used', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
  baseURL,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  // No login spent: `_authenticate_user` (views.py:758-768) compares
  // `custom_properties['xc_password']` with hmac.compare_digest, so the root
  // routes need no JWT at all. The suite's whole login budget is 3/minute
  // across every worker and project.
  const xcUser = await seed.xcUser();

  // TWO DIFFERENT MOMENTS — kept distinct for the one reason that survives
  // scrutiny, spelled out here because two others were tried and both were
  // wrong. Disconnect does NOT delete the pool entry: it runs release_cb ->
  // _make_release_once._release() -> _release_pool_session
  // (views.py:2342-2381), which with mark_pool_idle=True sets "busy": "0"
  // and re-arms the TTL — the entry survives, merely marked idle.
  // `_discard_pool_session` (views.py:2423-2440) is a different path
  // entirely, not the one disconnect takes. Nor did distinct `start` values
  // ever defeat adoption: `_find_matching_pool_session` matches on the
  // `{channel_id}_` prefix, and Node's fetch sends `user-agent: node`, so
  // the fingerprint scores the full 8 against _MATCH_SCORE_THRESHOLD
  // regardless of `start`. The decisive fact is that adopting an idle
  // pooled session still calls `_attempt_timeshift_stream`
  // (views.py:2878) — it contacts the provider either way. So a
  // provider-request COUNT cannot discriminate adoption from a fresh walk
  // at all, and no assertion in this goal infers adoption from one.
  // Distinct starts are kept anyway, for the reason that never depended on
  // any of this: each entry point is proved to have asked for ITS OWN
  // moment, rather than the pair asking twice for one — a strictly
  // stronger assertion than two drives sharing a timestamp.
  const pathStart = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const queryStart = catchupTimestamp(new Date(Date.now() - 3 * 60 * 60 * 1000));

  // PATH layout: /timeshift/<user>/<pass>/<duration>/<start>/<Channel.id>.ts
  // Channel.id, the numeric PK — unlike /proxy/catchup/, which is UUID-keyed.
  await streamClient.open(
    `/timeshift/${xcUser.username}/${xcUser.xcPassword}/60/${pathStart}/${channel.id}.ts`
  );
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  // QUERY layout: the surface nothing in this repo has ever driven.
  const second = newStreamClient(baseURL!);
  await second.open(
    `/streaming/timeshift.php?username=${encodeURIComponent(xcUser.username)}` +
      `&password=${encodeURIComponent(xcUser.xcPassword)}` +
      `&stream=${channel.id}&start=${encodeURIComponent(queryStart)}&duration=60`
  );
  expectTsAligned(await second.readPackets(20));
  await second.close();

  const asked = catchupRequests(await upstream.log(scenario));
  // Exactly two, in the order they were driven. Not evidence either way about
  // pool adoption — see the comment above: adopting an idle pooled session
  // still calls _attempt_timeshift_stream, so this count would read the same
  // whether or not adoption fired. A length of 0 or 1 here would point at the
  // routes themselves, not at adoption.
  expect(asked).toHaveLength(2);
  const expectedStarts = [pathStart, queryStart];

  for (const [i, entry] of asked.entries()) {
    // BOTH are `path`, and that is the point of this row rather than an
    // oversight. `client_timeshift_url_layout` (helpers.py:436-446) is read
    // ONLY by `_select_catchup_redirect_url` (views.py:413-419, :1709);
    // `_attempt_timeshift_stream` calls `build_timeshift_candidate_urls`
    // unconditionally (views.py:2673), so proxy mode walks PATH candidates
    // first no matter which shape the client arrived in. The client's layout
    // changes the REDIRECT (see catchup-redirect.spec.ts) and nothing else.
    expect(entry.layout, `request ${i} layout`).toBe('path');
    expect(entry.status).toBe(200);
    expect(entry.streamId).toBe(String(providerStreamId));
    expect(entry.duration).toBe('65');
    // Each entry point asked for the moment ITS OWN client requested, not the
    // other's and not one shared between them.
    expect(entry.start, `request ${i} start`).toBe(expectedStarts[i]);
  }

  // Same caveat as the row above: two different right moments were asked
  // for, one per entry point. Neither request proves Dispatcharr seeks to
  // either — the fake archive serves the same loop whatever `start` it is
  // given, and it served the same loop for both of these.
});

test('row 8 premise: a Standard viewer with hide_adult_content cannot list an adult channel', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  // Guards the premise the test.fail() below depends on, from OUTSIDE the
  // inverted block — a test.fail() body is satisfied by any failure inside
  // it, so no assertion in that body can guard its own premise. This is the
  // SAME shape of check the test.fail() below relies on (is_adult channel,
  // Standard viewer, hide_adult_content on), kept in this file rather than
  // only in `tests/seeded/output-authorization.spec.ts:92` ("hide_adult_content
  // removes an adult channel from every XC listing path"), so a change to
  // either file that unguards the pin signals here rather than only there.
  const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  await api.patch(`/api/channels/channels/${channel.id}/`, { is_adult: true });
  const viewer = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  const listed = await xcLiveStreams(request, viewer, 'the hide_adult_content listing');
  // Guards the guard: `.some(...) === false` passes vacuously on an EMPTY
  // listing too, which would unguard the premise below without ever
  // exercising it. 278 entries were measured live at seed time; assert
  // non-empty before asserting absence so a listing that came back empty for
  // any reason fails loudly here instead of silently greenlighting the pin.
  expect(listed.length, 'the XC listing must not come back empty').toBeGreaterThan(0);
  expect(
    listed.some((s) => s.stream_id === channel.id),
    'an adult channel must not appear in a hide_adult_content listing'
  ).toBe(false);
});

test(
  'an adult channel a user cannot list is also refused on the catch-up path', { tag: '@contract' },
  async ({ upstream, seed, api, waitFor, request, streamClient }) => {
    // Closed by Phase 1 PR 5. Every stream surface now authorizes through
    // apps/proxy/authorize.py's authorize_stream(), which applies the
    // user's hide_adult_content against Channel.is_adult before a byte
    // moves — the check every listing path already applied and the
    // apps/timeshift/ catch-up path did not. Following the
    // session-minting redirect all the way through now refuses rather
    // than serving TS-aligned packets: the strong form of the bug is
    // closed, not just the 301.
    //
    // The hop's status is not an open choice: `_apply_channel_checks`
    // raises exactly 403 for `is_adult` + `hide_adult_content`
    // (apps/proxy/authorize.py:383-386), so only 403 counts as the
    // refusal below. A 500 from a broken hop, a 400 from a malformed seed
    // or a 401 from an unresolvable XC user must all still fail this
    // test rather than read as "refused".
    //
    // Issue: https://github.com/D10Scot/Dispatcharr/issues/95 — closed by
    // PR 8, which references this PR.
    const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
    await api.patch(`/api/channels/channels/${channel.id}/`, { is_adult: true });

    // user_level 1, stated explicitly because it is load-bearing: the
    // hide_adult_content filter only applies below admin
    // (apps/output/views.py:140), so an admin viewer would see the channel in
    // the listing and the first half of this test would fail for a reason
    // that has nothing to do with the defect. `seed.xcUser()` already
    // defaults to 1 (seed.ts:114) — it is written out so the next reader
    // knows the value matters rather than that it happened to be the default.
    const viewer = await seed.xcUser({
      user_level: 1,
      custom_properties: { hide_adult_content: true },
    });
    const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

    // PASSES: the listing surface does hide it (apps/output/views.py:148-160).
    const listed = await xcLiveStreams(request, viewer, 'the hide_adult_content listing');
    expect(
      listed.some((s) => s.stream_id === channel.id),
      'an adult channel must not appear in a hide_adult_content listing'
    ).toBe(false);

    // FAILS TODAY: follow the redirect through to the served stream, rather
    // than stopping at the 301 that mints the session — that 301 decides
    // nothing, `_serve_catchup` does. `request.get()` would hang here: the
    // archive is an unbounded live stream and Playwright's request fixture
    // awaits the full body before resolving. StreamClient reads it
    // incrementally instead, and `open()`'s default is to follow redirects.
    let refusedAtOpen = false;
    try {
      await streamClient.open(
        `/timeshift/${viewer.username}/${viewer.xcPassword}/60/${start}/${channel.id}.ts`
      );
    } catch (err) {
      // Only a StreamStatusError carrying exactly 403 IS the correct
      // behaviour. Anything else — a DNS failure, a reset, a 500 from a
      // broken hop, a 400 from a malformed catch-up seed, a 401 from an
      // unresolvable XC user — is not evidence of a fix and must still
      // fail this test, not read as "refused".
      if (!(err instanceof StreamStatusError) || err.status !== 403) throw err;
      refusedAtOpen = true;
    }

    // The pin's inversion made this necessary: with the fix in place
    // open() throws, refusedAtOpen is true, and the block below is
    // skipped — so without this line the test would pass having asserted
    // nothing. The block stays for the case where a future regression
    // serves the archive again: it then proves no playable packets reach
    // this viewer, which is the strong form of the bug.
    expect(
      refusedAtOpen,
      'an adult channel must be refused to a hide_adult_content viewer at open'
    ).toBe(true);

    if (!refusedAtOpen) {
      // withDeadline so a stall reads as a named cause instead of the
      // project's 300s timeout.
      const packets = await withDeadline(
        streamClient.readPackets(20),
        30_000,
        'the archive read a hide_adult_content viewer should have been refused'
      );
      // CORRECT behaviour: no playable TS packets ever reach this viewer.
      // TODAY they do — expectTsAligned passes on them, which is the bug —
      // so this assertion fails now and stops failing only once the archive
      // is actually withheld.
      expect(
        () => expectTsAligned(packets),
        'a channel hidden from this user must not receive playable archive bytes'
      ).toThrow();
      await streamClient.close();
    }
  }
);

test('a session minted through the API plays back with no credentials of its own', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  const minted = await api.json<{ session_id: string; playback_url: string }>(
    await api.post('/api/catchup/sessions/', {
      channel_uuid: channel.uuid,
      start,
      duration: 60,
    }),
    'catch-up session'
  );

  // NO Authorization header. That is the whole point of the recommended
  // flow: the player is headerless, and `resolve_catchup_playback`
  // (apps/timeshift/sessions.py) resolves the user, the start and the
  // duration off the session (views.py:302-319). Open it promptly —
  // HANDSHAKE_TTL_SECONDS is 60 (sessions.py:31).
  await streamClient.open(minted.playback_url);
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const asked = catchupRequests(await upstream.log(scenario));
  expect(asked).toHaveLength(1);
  expect(asked[0].streamId).toBe(String(providerStreamId));
  expect(asked[0].start).toBe(start);
  // The session's stored duration, padded the same way a URL hint is
  // (views.py:318-319 → resolve_catchup_duration, helpers.py:224-233).
  expect(asked[0].duration).toBe('65');

  // Once more, because this row is the one a native-app author will read:
  // this proves the right moment was asked for. It does not prove
  // Dispatcharr seeks to it.
});
