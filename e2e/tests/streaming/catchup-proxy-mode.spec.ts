import { test, expect, expectTsAligned, xcLiveStreams } from '../../fixtures';
import {
  catchupRequests,
  catchupTimestamp,
  newStreamClient,
  seedCatchupChannel,
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

test('proxy mode streams a catch-up programme and asks the provider for exactly it', async ({
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

test('both root XC entry points reach the same cascade, whatever layout the client used', async ({
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

  // TWO DIFFERENT MOMENTS, and this is a correctness requirement rather than
  // variety. With no `session_id`, `_serve_catchup` looks for a pooled
  // session to adopt (views.py:387-405) with `include_busy: true`, scoring
  // client_ip (5) + client_user_agent (3) against _MATCH_SCORE_THRESHOLD = 8
  // (views.py:95) on a key of `programme_media_id(channel.id, safe_ts)`. Two
  // drives from one test share a host and a user agent, so they score 8 and
  // the SECOND WOULD ADOPT THE FIRST — reusing its upstream and making no
  // provider request at all, which is a log of length 1 against an assertion
  // of 2. A distinct `start` per drive changes `safe_ts`, changes the
  // media_id, and rules adoption out. It also strengthens the row: each entry
  // point is proved to have asked for ITS OWN moment, rather than the pair
  // having asked twice for one.
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
  // Exactly two, in the order they were driven. A length of 0 or 1 here means
  // pool adoption fired — check the two `start` values are actually distinct
  // before suspecting the routes.
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

test.fail(
  'an adult channel a user cannot list is also refused on the catch-up path',
  async ({ upstream, seed, api, waitFor, request }) => {
    // KNOWN BUG — issue #95. `hide_adult_content` is applied at twelve sites
    // across apps/output/, apps/epg/, apps/channels/ and apps/vod/, and at
    // NONE under apps/timeshift/. `_user_can_access_channel`
    // (views.py:771-786) checks user_level and Channel Profile membership
    // only. So a Standard user who cannot see an adult channel in any
    // listing can still stream its archive.
    //
    // The assertion below is the CORRECT behaviour and fails today. It is
    // deliberately status-agnostic above 400: whether the fix answers 403
    // (matching `_user_can_access_channel`'s existing refusal) or 404 is an
    // unmade choice, and pinning one would let the other go green the wrong
    // way.
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

    // FAILS TODAY: the same channel streams. `maxRedirects: 0` so the
    // session-minting 301 is observed rather than followed — today's answer
    // is that 301, which is < 400 and therefore not a refusal.
    const play = await request.get(
      `/timeshift/${viewer.username}/${viewer.xcPassword}/60/${start}/${channel.id}.ts`,
      { maxRedirects: 0 }
    );
    expect(
      play.status(),
      'a channel hidden from this user must not be streamable by them'
    ).toBeGreaterThanOrEqual(400);
  }
);

test('a session minted through the API plays back with no credentials of its own', async ({
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
