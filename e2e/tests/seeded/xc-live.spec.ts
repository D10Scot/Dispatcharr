import { test, expect, xcQuery } from '../../fixtures';
import type { XcUser } from '../../fixtures';

type XcCategory = { category_id: string; category_name: string };
type XcStream = {
  num: number;
  name: string;
  stream_id: number;
  stream_type: string;
  category_id: string;
  is_adult: number;
  tv_archive: number;
};

/**
 * `get_live_streams` is the one action served as a StreamingHttpResponse
 * (`_xc_stream_live_streams` yields the array element by element). The body
 * is valid JSON, but it arrives incrementally — read it whole before parsing.
 */
async function liveStreams(
  request: { get: (url: string) => Promise<{ text(): Promise<string> }> },
  user: XcUser
): Promise<XcStream[]> {
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_live_streams' })}`
  );
  return JSON.parse(await res.text());
}

test('the XC live catalogue lists a seeded channel under its own category', async ({
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
  // only in the channel's user_level — which makes this the positive control
  // for that bug rather than an unrelated happy path.
  const profile = await seed.channelProfile();
  const user = await seed.xcUser({ user_level: 1, channel_profiles: [profile.id] });

  const categories: XcCategory[] = await (
    await request.get(`/player_api.php${xcQuery(user, { action: 'get_live_categories' })}`)
  ).json();
  expect(categories.map((c) => c.category_id)).toContain(String(group.id));

  const streams = await liveStreams(request, user);
  const mine = streams.find((s) => s.stream_id === channel.id);
  expect(mine, `channel ${channel.id} should be in get_live_streams`).toBeDefined();
  expect(mine!.name).toBe(channel.name);
  expect(mine!.stream_type).toBe('live');
  expect(mine!.category_id).toBe(String(group.id));
  expect(mine!.is_adult).toBe(0);
  expect(mine!.tv_archive).toBe(0);
});

test('panel_api.php returns the same catalogue in one envelope', async ({
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

test('get_short_epg returns programmes for a channel with no EPG source', async ({
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
  // through to generate_dummy_programs.
  expect(body.epg_listings.length).toBeGreaterThan(0);

  const first = body.epg_listings[0];
  // title and description are base64-encoded on this surface. A plain string
  // compare would silently pass against the encoded form of anything.
  expect(Buffer.from(first.title, 'base64').toString('utf8')).not.toBe('');
  expect(first.start).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  expect(first.stream_id).toBe(String(channel.id));
  expect(first).not.toHaveProperty('now_playing');
});

test('get_simple_data_table adds now_playing to the same listing shape', async ({
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

  expect(body.epg_listings.length).toBeGreaterThan(0);
  // The one field that distinguishes the two actions: short=False adds it.
  expect(body.epg_listings[0]).toHaveProperty('now_playing');
});

test('the EPG actions 404 without a stream_id', async ({ seed, request }) => {
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
// The positive control is 'the XC live catalogue lists a seeded channel under
// its own category' above: identical setup, user_level 0 channel, passes
// today. The two differ in exactly one field, which is what makes this a
// located defect rather than a guess.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/85
test.fail('a profiled user sees the category of every channel it can list', async ({
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
  const streams = await liveStreams(request, user);
  expect(streams.map((s) => s.stream_id)).toContain(channel.id);

  const categories: XcCategory[] = await (
    await request.get(`/player_api.php${xcQuery(user, { action: 'get_live_categories' })}`)
  ).json();

  expect(
    categories.map((c) => c.category_id),
    'a channel visible in get_live_streams must have a category'
  ).toContain(String(group.id));
});
