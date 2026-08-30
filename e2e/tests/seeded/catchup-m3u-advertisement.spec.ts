import { test, expect, m3uQuery, parseM3u, xcLiveStreams } from '../../fixtures';

/**
 * The generated M3U advertises no catch-up, and the XC catalogue does. The
 * asymmetry is the evidence, so both halves live here — one failing, one
 * passing.
 *
 * Placement: the *surface* is `/output/m3u`, which is G5's, but the fact
 * that makes this a defect is catch-up's. G5 owns "the M3U parses and every
 * URL is well-formed"; G10 owns "the M3U advertises catch-up". Keeping this
 * out of G5's own `/output/m3u` spec is deliberate.
 *
 * No provider, no ingest: `is_catchup`/`catchup_days` are writable on
 * `ChannelSerializer` (`apps/channels/serializers.py:440-469`), and with no
 * streams wired there is no `ChannelStream` row for
 * `update_channel_catchup_fields` (`apps/channels/signals.py:393-407`) to
 * roll a `false` back over them.
 *
 * Both surfaces are read through G5's landed helpers — `parseM3u` for the
 * playlist, `xcLiveStreams` for the catalogue. Neither is re-implemented
 * here: `splitExtinf`'s forward attribute walk is what stops a channel name
 * containing a comma or a quote from being mis-read, and `xcLiveStreams`
 * carries the 200 assertion that a hand-rolled `player_api.php` fetch keeps
 * dropping.
 */
const CATCHUP_DAYS = 7;

test.fail(
  'the generated M3U advertises catch-up for a catch-up channel',
  async ({ seed, request }) => {
    // KNOWN BUG — see #94. This assertion is the CORRECT behaviour; it
    // fails today. Never invert it to assert the bug: a test.fail() that
    // asserts the buggy behaviour goes green the wrong way and locks the
    // defect in.
    //
    // Convention-agnostic ON PURPOSE. The three de-facto M3U catch-up
    // conventions — `catchup="default"` + `catchup-source=`, `catchup="xc"`,
    // and `catchup="append"` — are mutually incompatible, and Dispatcharr
    // serves two upstream layouts, so which one it should advertise is an
    // unmade product decision. Asserting only that SOME `catchup` attribute
    // and a matching `catchup-days` are present holds under all three and
    // constrains none of them. Do not add `catchup-source` here.
    const channel = await seed.channel({ is_catchup: true, catchup_days: CATCHUP_DAYS });

    // `m3uQuery()` is not optional: `/output/m3u` is cached for 2 seconds
    // under a key that is the same for every anonymous caller on the
    // instance, and `seeded` runs four workers, so a bare fetch can be served
    // a body rendered before this channel existed.
    const res = await request.get(`/output/m3u${m3uQuery()}`);
    expect(res.status()).toBe(200);
    const entry = parseM3u(await res.text()).entries.find((e) => e.title === channel.name);
    expect(entry, `an #EXTINF entry for "${channel.name}" in /output/m3u`).toBeDefined();

    expect(
      entry!.attributes.catchup,
      'an #EXTINF for a catch-up channel should carry a catchup attribute'
    ).toBeTruthy();
    expect(entry!.attributes['catchup-days']).toBe(String(CATCHUP_DAYS));
  }
);

test('the XC catalogue does advertise the same channel as catch-up', async ({ seed, request }) => {
  // The other half of the asymmetry, and the reason the row above is a
  // defect rather than a preference: the same channel, the same instant, on
  // the surface Dispatcharr DOES advertise catch-up on. The XC emitter even
  // has a considered `catchup_allowed` gate (apps/output/views.py:727) — the
  // author thought about who may see catch-up advertised. The M3U builder
  // (`:298-306`) does not participate at all.
  const channel = await seed.channel({ is_catchup: true, catchup_days: CATCHUP_DAYS });
  const xcUser = await seed.xcUser();

  const listed = await xcLiveStreams(request, xcUser, 'the XC catch-up catalogue');
  const entry = listed.find((s) => s.stream_id === channel.id);
  expect(entry, `channel ${channel.id} in get_live_streams`).toBeDefined();
  expect(entry!.tv_archive).toBe(1);
  // `tv_archive_duration` is the field Task 1 added to `XcStream`; without it
  // this assertion does not compile.
  expect(entry!.tv_archive_duration).toBe(CATCHUP_DAYS);
});
