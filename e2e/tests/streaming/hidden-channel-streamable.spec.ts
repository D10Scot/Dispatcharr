import { test, expect, StreamStatusError, xcLiveStreams } from '../../fixtures';
import { lockedProfile } from './helpers';

// The non-inverted control for the test.fail() below ('a channel a user
// cannot list is not streamable by that user'): the listing-absence premise
// that an adult channel is genuinely unlistable for a hide_adult_content
// user, asserted alongside its positive counterpart — the same channel IS
// listable for an admin XC user (`user_level: 10`). `_xc_live_streams_setup`
// (apps/output/views.py) branches on `user.user_level < 10`: both of the
// filtered user's sub-branches (with and without a Channel Profile) apply
// `filters["is_adult"] = False` when `hide_adult_content` is set, but the
// `user_level >= 10` branch builds its queryset with no `is_adult` key at
// all. The negative half alone could pass for a reason that has nothing to
// do with is_adult filtering — an unresolvable channel, a scenario that
// never came up, a profile membership gap that happens to exclude it — so
// this control asserts both halves against the same seeded channel, with
// its own full setup (own scenario, own seeded channel, own users): sharing
// the pin's fixtures would share the failure modes this control exists to
// separate.
//
// The pin below calls `xcLiveStreams` once, for the filtered user only,
// inside a test.fail() block, which is satisfied by ANY failure in its
// body — so a broken listing premise there would also read as "expected
// failure" and the pin would go green while proving nothing about the
// actual defect. This control is what actually guards that premise.
test('an adult channel is unlistable for a hide_adult_content user and listable for an admin', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  request,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G6 Adult Control', tvgId: 'g6-adult-control.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
    channel: { user_level: 0, is_adult: true },
  });

  const filteredUser = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });
  const adminUser = await seed.xcUser({ user_level: 10 });

  const listedForFiltered = await xcLiveStreams(
    request,
    filteredUser,
    'get_live_streams for a hide_adult_content user'
  );
  expect(listedForFiltered.map((s) => s.stream_id)).not.toContain(channel.id);

  const listedForAdmin = await xcLiveStreams(
    request,
    adminUser,
    'get_live_streams for an admin user'
  );
  expect(listedForAdmin.map((s) => s.stream_id)).toContain(channel.id);
});

// Closed by Phase 1 PR 5. Every stream surface now authorizes through
// apps/proxy/authorize.py's authorize_stream(), which applies the user's
// hide_adult_content against Channel.is_adult — the check every listing
// path already applied and stream_xc did not. The refusal is a 403 from
// the authorize hop rather than the 404 stream_xc's deleted filter would
// have produced: the channel exists, and this user may not have it.
//
// Kept in its inverted-pin shape (the try/catch that accepts only 403 or
// 404, and rethrows anything else) on purpose. A bare "expect a refusal"
// rewrite would go green on a connection reset or a 500, which is exactly
// the failure mode a security assertion must not have.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/87 — closed by
// PR 8, which references this PR.
test('a channel a user cannot list is not streamable by that user', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  request,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G5 Adult', tvgId: 'g5-adult.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
    channel: { user_level: 0, is_adult: true },
  });

  const user = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  // The premise: this user genuinely cannot list the channel. Without it a
  // refusal below could mean anything.
  //
  // xcLiveStreams asserts the listing call itself returned 200 before parsing
  // it — the positive control this premise needs. Without it, an unresolvable
  // user (issue #84 — get_object_or_404 on username) would 404 with a JSON
  // error body; JSON.parse would accept it, and `.map` on the non-array
  // result would throw a TypeError, which test.fail() also treats as an
  // expected failure. A bare parse-and-check could pass for a reason that has
  // nothing to do with is_adult filtering.
  const listed = await xcLiveStreams(request, user, 'get_live_streams for a resolvable user');
  expect(listed.map((s) => s.stream_id)).not.toContain(channel.id);

  // streamClient, not request.get(): APIResponse.body() awaits the full
  // download and would never resolve against an endless TS stream if the
  // product does serve it — which today it does. `open()` throws on a
  // non-2xx, so resolving means the bytes started flowing.
  //
  // Only a REFUSAL may set `served = false`. A bare `.catch(() => false)`
  // would collapse a connection reset, a DNS failure, an upstream that never
  // came up, a 500 or a timeout into "the product refused the stream" — and
  // under test.fail() a false `served` makes the body PASS, which Playwright
  // reports as an unexpected pass, i.e. "#87 is fixed". That is the loud
  // failure mode here, louder than a hollow red, because it claims a security
  // defect is closed. So anything that is not a refusal status rethrows,
  // failing the body and leaving the pin held — the safe direction.
  //
  // 404 first because that is what the fix produces: adding is_adult /
  // hidden_from_output to stream_xc's `filters` dict makes the lookup return
  // no channel, and that path already answers `{"error": "Not found"}` with
  // 404 (apps/proxy/live_proxy/views.py:815-816). 403 is accepted too, in
  // case the fix rejects before the lookup as the network-ACL branch does.
  let served = true;
  try {
    await streamClient.open(`/live/${user.username}/${user.xcPassword}/${channel.id}`);
  } catch (error) {
    if (!(error instanceof StreamStatusError) || ![403, 404].includes(error.status)) {
      throw error;
    }
    served = false;
  }

  try {
    expect(
      served,
      'a channel hidden from this user by hide_adult_content must not stream'
    ).toBe(false);
  } finally {
    // Abort whatever was opened, so a failing run does not leave an upstream
    // connection held for the rest of the project.
    await streamClient.close();
  }
});
