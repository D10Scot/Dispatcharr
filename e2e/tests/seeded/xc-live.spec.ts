import { test, expect, xcLiveStreams, xcQuery } from '../../fixtures';

type XcCategory = { category_id: string; category_name: string };

test('the XC live catalogue lists a seeded channel under its own category', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  // Own group, not the shared "Default Group" ChannelSerializer.create
  // auto-assigns: get_live_categories returns groups, and four workers all
  // writing into one group makes any category assertion meaningless.
  const group = await seed.channelGroup();
  const channel = await seed.channel({ channel_group_id: group.id, user_level: 0 });

  // One Channel Profile assigned, and a user_level 0 channel. This is
  // deliberately the exact shape the known-bug test below uses, differing
  // only in the channel's user_level — a contrast case for that bug, not a
  // positive control for it: at user_level 0 the has-profiles branch's
  // exact-match filter and get_live_streams' __lte filter agree by
  // construction, so this shape alone cannot confirm the level-1 half of
  // that other test's premise. See its doc comment, and the control above
  // it, for what does.
  const profile = await seed.channelProfile();
  const user = await seed.xcUser({ user_level: 1, channel_profiles: [profile.id] });

  // ChannelSerializer.create always assigns channel_number via
  // get_next_available_channel_number() (apps/channels/models.py); a
  // creation without an explicit override never leaves it null. Asserted
  // before use so the assertions below fail here, not with a confusing
  // `null !== 834` further down. Same premise hdhr.spec.ts:161 relies on.
  expect(channel.channel_number, 'create should have assigned a number').not.toBeNull();

  const categories: XcCategory[] = await (
    await request.get(`/player_api.php${xcQuery(user, { action: 'get_live_categories' })}`)
  ).json();
  expect(categories.map((c) => c.category_id)).toContain(String(group.id));

  const streams = await xcLiveStreams(request, user);
  const mine = streams.find((s) => s.stream_id === channel.id);
  expect(mine, `channel ${channel.id} should be in get_live_streams`).toBeDefined();
  expect(mine!.name).toBe(channel.name);
  expect(mine!.stream_type).toBe('live');
  expect(mine!.category_id).toBe(String(group.id));
  expect(mine!.is_adult).toBe(0);
  expect(mine!.tv_archive).toBe(0);
  // `num`/`epg_channel_id` are a collision-free integer built from every
  // channel's effective_channel_number (_xc_live_streams_setup), not a
  // straight passthrough of channel_number — but with an unshared,
  // freshly-created channel_number there is nothing for it to collide with,
  // so it resolves to channel_number itself. category_ids is the numeric
  // (not stringified) sibling of category_id.
  expect(mine!.num).toBe(channel.channel_number);
  expect(mine!.epg_channel_id).toBe(String(channel.channel_number));
  expect(mine!.category_ids).toEqual([group.id]);
});

test('panel_api.php returns the same catalogue in one envelope', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  const group = await seed.channelGroup();
  const channel = await seed.channel({ channel_group_id: group.id, user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const body = await (await request.get(`/panel_api.php${xcQuery(user)}`)).json();

  expect(body.user_info.auth).toBe(1);
  expect(body.categories.live.map((c: XcCategory) => c.category_id)).toContain(
    String(group.id)
  );
  // available_channels is keyed by stream_id, which is the numeric Channel PK.
  expect(body.available_channels[String(channel.id)]?.name).toBe(channel.name);
});

test('get_short_epg returns programmes for a channel with no EPG source', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  // stream_id is the numeric Channel PK, NOT the UUID. xc_get_epg raises
  // Http404 without it — the /proxy/ts/ routes are the UUID-keyed ones.
  const body = await (
    await request.get(
      `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: channel.id })}`
    )
  ).json();

  // A channel with no epg_data still yields listings: xc_get_epg falls
  // through to generate_dummy_programs(channel_id, effective_name,
  // epg_source=None) (apps/output/views.py) with no num_days/
  // program_length_hours passed, so both take their defaults (num_days=1,
  // program_length_hours=4 — apps/output/epg.py:134-135) and that branch
  // does not apply `short`'s limit/end_time slicing at all, unlike the
  // stored-programs branches above it. One day at a 4-hour cadence is
  // exactly 24 / 4 = 6 programs (range(0, 24, 4)).
  expect(body.epg_listings.length).toBe(6);

  const first = body.epg_listings[0];
  // `stream_id` (asserted below) is `f"{channel_id}"` — request.GET's own
  // `stream_id` parameter echoed straight back (apps/output/views.py:788,
  // :982). It proves the server received our query string, not that this
  // listing belongs to our channel. `title` is the field that actually ties
  // the response to the seeded channel: generate_dummy_programs sets
  // `"title": channel_name` verbatim (apps/output/epg.py:251), and
  // `channel_name` here is `channel.effective_name`, which falls back to
  // `channel.name` with no per-user override in play
  // (ChannelSerializer.get_effective_name). title and description are
  // base64-encoded on this surface, so decode before comparing — a plain
  // string compare would silently pass against the encoded form of
  // anything.
  expect(Buffer.from(first.title, 'base64').toString('utf8')).toBe(channel.name);
  expect(first.start).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  expect(first.stream_id).toBe(String(channel.id));
  expect(first).not.toHaveProperty('now_playing');
});

test('get_simple_data_table adds now_playing to the same listing shape', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const body = await (
    await request.get(
      `/player_api.php${xcQuery(user, {
        action: 'get_simple_data_table',
        stream_id: channel.id,
      })}`
    )
  ).json();

  // Same generator, same defaults as the get_short_epg test above: 6.
  expect(body.epg_listings.length).toBe(6);
  // The first dummy program starts at "now" rounded down to the hour and
  // runs `program_length_hours` (4h) from there (apps/output/epg.py:157-159,
  // 227-230), so at request time it always straddles `now`:
  // start <= now <= end. now_playing = 1 is therefore deterministic here,
  // not merely present — asserting the value, not just the key, is what
  // distinguishes this action from get_short_epg beyond the key's existence.
  expect(body.epg_listings[0].now_playing).toBe(1);
});

test('the EPG actions 404 without a stream_id', { tag: '@contract' }, async ({ seed, request }) => {
  const user = await seed.xcUser({ user_level: 1 });

  for (const action of ['get_short_epg', 'get_simple_data_table']) {
    const res = await request.get(`/player_api.php${xcQuery(user, { action })}`);
    expect(res.status(), `${action} with no stream_id`).toBe(404);
  }
});

// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_live_categories` in
// apps/output/views.py has three branches. The no-profiles branch and the
// admin branch both filter `channels__user_level__lte=user.user_level`. The
// has-profiles branch — the one a user with at least one Channel Profile
// takes — filters `"channels__user_level": 0`, an exact match.
//
// Symptom, and what this test asserts against: a channel at user_level 1 is
// listed by get_live_streams (which uses __lte everywhere) but its category
// is missing from get_live_categories, so an XC client shows a stream that
// belongs to no category.
//
// 'the XC live catalogue lists a seeded channel under its own category'
// above is not a positive control for this test, despite the matching
// setup: it shares this test's profiled-user shape
// (`channel_profiles: [profile.id]`) but at channel user_level 0, where
// get_live_categories' has-profiles exact-match filter
// (channels__user_level == 0) and get_live_streams' __lte filter agree by
// construction — it cannot confirm the level-1 half of this test's premise.
// It is a contrast case: the two tests differ in exactly one field (the
// channel's user_level), which is what makes this a located defect rather
// than a guess.
//
// This test's own body already performs the premise sequence — asserting
// that get_live_streams lists a profiled level-1 user's level-1 channel —
// but inside this test.fail() block, which is satisfied by ANY failure, so
// a regression in that listing itself (not just in category assignment)
// would be swallowed as "expected failure" and never surface. The
// non-inverted control immediately above ('a profiled level-1 user lists a
// level-1 channel') is what actually guards it.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/85

// The non-inverted control for the test.fail() below ('a profiled user sees
// the category of every channel it can list'): get_live_streams filters
// `user_level__lte=user.user_level` in every branch, so it should
// list a level-1 channel for a profiled level-1 user — the pin's own
// premise assertion, currently reachable only inside its test.fail() body.
// The test at the top of the file ('the XC live catalogue lists a seeded
// channel under its own category') also calls xcLiveStreams with a
// profiled user, but against a user_level 0 channel, so it does not
// exercise this at level-1 — and no other test in this file calls
// xcLiveStreams at all. A break in this listing (not just in category
// assignment) would be swallowed by the pin below as an "expected failure",
// since test.fail() is satisfied by ANY failure in its body, not
// specifically the category defect it exists to pin.
test('a profiled level-1 user lists a level-1 channel', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  const group = await seed.channelGroup();
  const channel = await seed.channel({ channel_group_id: group.id, user_level: 1 });
  const profile = await seed.channelProfile();
  const user = await seed.xcUser({ user_level: 1, channel_profiles: [profile.id] });

  const streams = await xcLiveStreams(request, user);
  expect(
    streams.map((s) => s.stream_id),
    'a profiled level-1 user should list a level-1 channel'
  ).toContain(channel.id);
});

test.fail('a profiled user sees the category of every channel it can list', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  const group = await seed.channelGroup();
  const channel = await seed.channel({ channel_group_id: group.id, user_level: 1 });
  const profile = await seed.channelProfile();
  const user = await seed.xcUser({ user_level: 1, channel_profiles: [profile.id] });

  // Establish the premise before asserting the defect: the channel really is
  // visible to this user. Without this, a missing category could equally mean
  // the channel was filtered out for an unrelated reason, and the test would
  // indict the wrong line.
  const streams = await xcLiveStreams(request, user);
  expect(streams.map((s) => s.stream_id)).toContain(channel.id);

  const categories: XcCategory[] = await (
    await request.get(`/player_api.php${xcQuery(user, { action: 'get_live_categories' })}`)
  ).json();

  expect(
    categories.map((c) => c.category_id),
    'a channel visible in get_live_streams must have a category'
  ).toContain(String(group.id));
});
