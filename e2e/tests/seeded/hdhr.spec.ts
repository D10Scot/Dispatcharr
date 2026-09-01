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

test('hdhr discover.json describes a tuner and points at its own lineup', { tag: '@contract' }, async ({
  seed,
  request,
  baseURL,
}) => {
  const channel = await seed.channel();

  const res = await request.get('/hdhr/discover.json');
  expect(res.status()).toBe(200);

  const device: Discover = await res.json();

  // The bare endpoint (no <channel_profile>/<output_profile_id> segment) has
  // no HDHRDevice row to fall back on in this container (verified: no
  // fixture creates one, and none of these views' CRUD route is exercised
  // elsewhere), so DiscoverAPIView takes its `if not device:` branch
  // (apps/hdhr/api_views.py:79-89), which hardcodes both literals. They only
  // become slug-derived (`dispatcharr-hdhr-<slug>` /
  // `Dispatcharr HDHomeRun - <slug>`) when a channel_profile or
  // output_profile segment is present — neither is, here.
  expect(device.FriendlyName).toBe('Dispatcharr HDHomeRun');
  expect(device.DeviceID).toBe('12345678');

  // calculate_tuner_count(minimum=1, unlimited_default=10) adds a COUNT of
  // every is_custom Stream on the WHOLE instance (apps/m3u/utils.py:85-141)
  // to a base — not scoped to this test, this worker, or even this run: the
  // count accumulates over the container's whole session (verified
  // empirically: 102 at rest before this test ran) and nothing in this
  // harness ever deletes a seeded Stream. No absolute value can be pinned,
  // but the RELATIONSHIP can: adding one custom stream must raise the
  // reported count by at least 1.
  //
  // That relationship only holds while the BASE is stable, and it is not
  // stable by default. `has_unlimited` is an instance-wide predicate — "does
  // any active profile on any active M3U account have max_streams=0" — and
  // it selects between two entirely different bases:
  //
  //     tuner_count = (10 + custom) if has_unlimited else (limited_sum + custom)
  //
  // Several other `seeded` specs create and deactivate M3U accounts
  // concurrently. If the last active one goes away between the two reads
  // below, the base drops from 10 to limited_sum (0 on this instance), and
  // `after` comes back around nine BELOW `before` — a red test with the
  // product behaving perfectly.
  //
  // So pin the predicate rather than hope: an active account of our own,
  // whose default profile post_save creates synchronously with
  // max_streams = M3UAccount.max_streams = 0, is_active=True
  // (apps/m3u/models.py:391-400). While it exists and stays active,
  // has_unlimited cannot go false, and the base is fixed at 10 for the whole
  // window. The default bogus server_url is deliberate — the create-time
  // refresh task fails against an unroutable address and ingests nothing,
  // the same pattern m3u-refresh-failure.spec.ts and async-wait.spec.ts use.
  await seed.m3uAccount({ is_active: true, max_streams: 0 });

  // Re-read AFTER pinning the predicate: `device` above was fetched before
  // the account existed, so its TunerCount may sit on the other branch.
  const before: Discover = await (await request.get('/hdhr/discover.json')).json();
  expect(before.TunerCount).toBeGreaterThanOrEqual(1); // the function's own floor
  await seed.stream();
  const after: Discover = await (await request.get('/hdhr/discover.json')).json();
  // Deliberately `>=`, not `===`: 4 workers run fullyParallel and another
  // worker's seed.stream() landing in this window would make an exact +1 an
  // occasional false failure. `>=` still fails if seeding a custom stream
  // does not increment the count at all — the wiring this assertion exists
  // to test. Do not tighten to `===`; that reintroduces the flake.
  expect(after.TunerCount).toBeGreaterThanOrEqual(before.TunerCount + 1);

  // R14 was withdrawn: this deployment has no working X-Forwarded-Host path,
  // so the origin Dispatcharr emits is exactly the client's own Host header
  // — baseURL, for a request.get() call. Exact, not just a shared prefix:
  // build_absolute_uri_with_port joins uri_parts=["hdhr"] (bare call, no
  // path params) into "/hdhr/" and rstrips the trailing slash, so BaseURL is
  // the origin with literally "/hdhr" appended and nothing else.
  expect(device.BaseURL).toBe(`${baseURL}/hdhr`);
  // Was previously a tautology: BaseURL and LineupURL are built from the
  // same base_url variable in the same dict literal (api_views.py:83-84), so
  // this equality holds by construction. It's meaningful now only because
  // BaseURL itself is pinned above to something external.
  expect(device.LineupURL).toBe(`${device.BaseURL}/lineup.json`);

  // The URL it advertises actually resolves to the lineup document, not the
  // SPA catch-all: dispatcharr/urls.py mounts the SPA index under the same
  // host, and ANY unmatched /hdhr/*.json path 200s with it too (verified:
  // GET /hdhr/BOGUS.json → 200 text/html, same as the real endpoint's status
  // alone would have let through). Content-type and shape are what a
  // status-only check can't tell apart from that page; finding the channel
  // seeded above proves the body is the real lineup, not just JSON shaped
  // like one.
  const lineupRes = await request.get(device.LineupURL);
  expect(lineupRes.status()).toBe(200);
  expect(lineupRes.headers()['content-type']).toContain('application/json');
  const lineup: LineupEntry[] = await lineupRes.json();
  expect(Array.isArray(lineup)).toBe(true);
  expect(lineup.some((entry) => entry.GuideName === channel.name)).toBe(true);
});

test('hdhr device.xml is well-formed and agrees with discover.json', { tag: '@contract' }, async ({
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

// Investigated, not pinned: HDHRDeviceXMLAPIView (api_views.py:210-233)
// hardcodes FriendlyName/DeviceID unconditionally and never reads
// HDHRDevice at all, while DiscoverAPIView (api_views.py:66-67) reads
// HDHRDevice.objects.first() and prefers its fields when a row exists. So a
// configured HDHRDevice row would make these two endpoints permanently
// disagree — a real, source-provable defect, independent of any test state.
//
// Deliberately not pinned with a live test.fail() here: HDHRDevice has no
// seed fixture, and `.objects.first()` is a single unnamespaced row with no
// per-test scoping — creating one, even transiently, would leak into every
// OTHER concurrent /hdhr/discover.json call under this project's
// `fullyParallel: true, workers: 4` (playwright.config.ts), including the
// two exact-literal assertions a few lines above in this same file. Filed
// without a live repro — https://github.com/D10Scot/Dispatcharr/issues/83 —
// on the source citations alone.


test('hdhr lineup_status.json reports a scannable cable source', { tag: '@contract' }, async ({ request }) => {
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

test('hdhr lineup.json carries a seeded channel with a proxy URL', { tag: '@contract' }, async ({
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

test('hdhr lineup scopes to a Channel Profile, and answers [] for an unknown one', { tag: '@contract' }, async ({
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
// Paired with output-authorization.spec.ts's "the anonymous output surfaces
// apply no user_level filter at all" test, whose /hdhr/lineup.json assertion
// asserts the SAME behaviour as passing (today's actual, unauthorized-by-
// design output). Both are correct descriptions of today; the day this is
// fixed, this test flips green as expected and that one's /hdhr/lineup.json
// assertion flips red as an intended false alarm — see the comment there for
// the reciprocal note.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/82
test.fail('hdhr lineup does not expose adult or above-level channels', { tag: '@contract' }, async ({
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
