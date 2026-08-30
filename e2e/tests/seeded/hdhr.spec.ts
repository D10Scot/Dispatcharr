import { test, expect, expectWellFormedXml } from '../../fixtures';

/**
 * `/hdhr/*` — the HDHomeRun tuner emulation Plex/Emby/Jellyfin discover.
 *
 * All four views (`DiscoverAPIView`, `LineupAPIView`, `LineupStatusAPIView`,
 * `HDHRDeviceXMLAPIView`) are `permission_classes = [AllowAny]` and driven
 * with `request`, never `api` — a real tuner client carries no bearer token.
 * `lineup.json` with no `<channel_profile>` segment renders
 * `Channel.objects.all()`: every channel on the instance, across all four
 * workers. Nothing here may assert on an unfiltered list or its length —
 * every assertion locates the row(s) this test seeded by generated name.
 */

type Discover = {
  FriendlyName: string;
  DeviceID: string;
  TunerCount: number;
  BaseURL: string;
  LineupURL: string;
};

type LineupEntry = {
  GuideNumber: string;
  GuideName: string;
  URL: string;
};

test('hdhr discover.json describes a tuner and points at its own lineup', async ({
  request,
}) => {
  const res = await request.get('/hdhr/discover.json');
  expect(res.status()).toBe(200);

  const device: Discover = await res.json();
  expect(device.FriendlyName).toBeTruthy();
  expect(device.DeviceID).toBeTruthy();
  expect(device.TunerCount).toBeGreaterThan(0);
  expect(device.LineupURL).toBe(`${device.BaseURL}/lineup.json`);

  // The URL it advertises actually resolves. A discovery document naming a
  // 404 is the failure mode that makes a tuner "not work in Plex".
  const lineup = await request.get(device.LineupURL);
  expect(lineup.status()).toBe(200);
});

test('hdhr device.xml is well-formed and agrees with discover.json', async ({
  request,
  adminPage,
}) => {
  const res = await request.get('/hdhr/device.xml');
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/xml');

  const body = await res.text();
  await expectWellFormedXml(adminPage, body);

  const lineupUrl = /<LineupURL>([^<]*)<\/LineupURL>/.exec(body)?.[1];
  const discover: Discover = await (await request.get('/hdhr/discover.json')).json();
  expect(lineupUrl).toBe(discover.LineupURL);
});

test('hdhr lineup_status.json reports a scannable cable source', async ({ request }) => {
  const res = await request.get('/hdhr/lineup_status.json');
  expect(res.status()).toBe(200);

  const status = await res.json();
  expect(status).toMatchObject({
    ScanInProgress: 0,
    ScanPossible: 0,
    Source: 'Cable',
    SourceList: ['Cable'],
  });
});

test('hdhr lineup.json carries a seeded channel with a proxy URL', async ({
  seed,
  request,
  baseURL,
}) => {
  // No explicit channel_number. ChannelSerializer.create assigns one from
  // Channel.get_next_available_channel_number() when it is omitted, so a
  // seeded channel always has one — which matters here, because
  // LineupAPIView SKIPS any channel whose format_channel_number(..., empty=None)
  // is None. Hard-coding a number instead would collide with itself on a
  // second run against the same container.
  const channel = await seed.channel();
  expect(channel.channel_number, 'create should have assigned a number').not.toBeNull();

  const res = await request.get('/hdhr/lineup.json');
  expect(res.status()).toBe(200);

  const lineup: LineupEntry[] = await res.json();
  const mine = lineup.find((entry) => entry.GuideName === channel.name);
  expect(mine, `${channel.name} should be in the lineup`).toBeDefined();

  // format_channel_number renders a whole-valued float as an int, and
  // JSON.parse does the same to 9.0 — so String() over the number the API
  // returned matches on both whole and fractional values.
  expect(mine!.GuideNumber).toBe(String(channel.channel_number));
  expect(mine!.URL).toBe(`${baseURL}/proxy/ts/stream/${channel.uuid}`);
});

test('hdhr lineup scopes to a Channel Profile, and answers [] for an unknown one', async ({
  seed,
  api,
  request,
}) => {
  const profile = await seed.channelProfile();
  const included = await seed.channel();
  const excluded = await seed.channel();
  expect(
    (
      await api.patch(
        `/api/channels/profiles/${profile.id}/channels/${excluded.id}/`,
        { enabled: false }
      )
    ).status()
  ).toBe(200);

  const scoped: LineupEntry[] = await (
    await request.get(`/hdhr/${profile.name}/lineup.json`)
  ).json();
  const names = scoped.map((entry) => entry.GuideName);
  expect(names).toContain(included.name);
  expect(names).not.toContain(excluded.name);

  // LineupAPIView returns an empty lineup for a profile that does not exist,
  // where /output/m3u raises Http404 for the same mistake. Two surfaces, two
  // answers; pin both so a future unification is a deliberate change.
  const unknown = await request.get(`/hdhr/${seed.generatedName('no-such')}/lineup.json`);
  expect(unknown.status()).toBe(200);
  expect(await unknown.json()).toEqual([]);
});

// Asserts the behaviour Dispatcharr SHOULD have. It fails today, and the
// cause is structural rather than a forgotten line: the four HDHomeRun views
// in apps/hdhr/api_views.py are `permission_classes = [AllowAny]` and take no
// user at all, so LineupAPIView builds `Channel.objects.all()` and has no
// principal to filter it by. There is not one occurrence of
// `hide_adult_content` anywhere under apps/hdhr/ — and there could not be,
// because it is a per-user preference and there is no user.
//
// The only access control on this surface is the M3U_EPG network ACL (which
// defaults to private networks) and the optional <channel_profile> path
// segment. Anything the ACL admits sees every channel on the instance,
// including adult ones and ones above every user level.
//
// Filed separately from the stream_xc adult-filter defect
// (hidden-channel-streamable.spec.ts): that function HAS the principal and
// omits one filter clause, so its fix is that clause. This one has no
// principal, so its fix is a design decision about how HDHR authenticates.
// One issue would not be closed by either change alone.
//
// Paired with output-authorization.spec.ts's "lineup.json exposes a
// user_level: 10 channel to an unauthenticated caller" test, which asserts
// the SAME behaviour as passing (today's actual, unauthorized-by-design
// output). Both are correct descriptions of today; the day this is fixed,
// this test flips green as expected and that one flips red as an intended
// false alarm — see the comment there for the reciprocal note.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/82
test.fail('hdhr lineup does not expose adult or above-level channels', async ({
  seed,
  request,
}) => {
  const restricted = await seed.channel({ user_level: 10, is_adult: true });

  const lineup: LineupEntry[] = await (await request.get('/hdhr/lineup.json')).json();
  const names = lineup.map((entry) => entry.GuideName);

  expect(
    names,
    'an unauthenticated caller should not see an admin-only adult channel'
  ).not.toContain(restricted.name);
});
