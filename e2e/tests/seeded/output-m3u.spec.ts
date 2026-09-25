import { test, expect, decodeXmlEntities, m3uQuery, parseM3u } from '../../fixtures';
import type { Channel } from '../../fixtures';

/**
 * `/output/m3u[/<profile>]` — the client-facing M3U playlist surface.
 *
 * Driven with the built-in `request` fixture everywhere, never `api`: this is
 * how TiviMate, Plex and every other real client fetch a playlist, with no
 * bearer token. The `api` fixture is reserved here for seeding and for admin
 * writes — the profile-membership PATCH and the channel rename in the first
 * test — never for a client read.
 *
 * Four workers share one instance and `generate_m3u` with no profile in the
 * URL renders every channel that exists — so nothing here may assert a
 * playlist length or an unfiltered entry list. Every assertion locates the
 * row(s) this test seeded by the generated name and checks only those.
 */

test('/output/m3u renders a parseable playlist with a well-formed proxy URL', { tag: '@contract' }, async ({
  seed,
  api,
  request,
  baseURL,
}) => {
  const channel = await seed.channel();

  // No bearer token: this is how a real client fetches a playlist, and it is
  // what makes the assertion meaningful. `request` is Playwright's built-in
  // context; the `api` fixture would add an Authorization header no TiviMate
  // or Plex install has.
  //
  // `m3uQuery()` for the cache key, not the token: a bare `/output/m3u` is one
  // 2-second cache entry shared by every anonymous caller on the instance, so
  // a parallel worker's fetch can hand this one a body rendered before
  // `seed.channel()` ran. See the helper for the reproduction.
  const res = await request.get(`/output/m3u${m3uQuery()}`);
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('audio/x-mpegurl');

  const playlist = parseM3u(await res.text());

  // The header points clients at the guide. Both spellings are emitted
  // because different clients read different ones.
  expect(playlist.header['x-tvg-url']).toContain('/output/epg');
  expect(playlist.header['url-tvg']).toBe(playlist.header['x-tvg-url']);

  // NEVER assert on playlist.entries.length. Four workers share this
  // container and the playlist renders every channel on the instance.
  const mine = playlist.entries.find((e) => e.attributes['tvg-name'] === channel.name);
  expect(mine, `the seeded channel ${channel.name} should be in the playlist`).toBeDefined();

  // Checked empirically rather than assumed: `get_host_and_port`
  // (core/utils.py:999) prefers `X-Forwarded-Host`, but on this deployment
  // that header isn't what actually lands — `docker exec`'ing into the
  // container and sending a request straight to nginx's internal :9191 with
  // a hand-set `Host: internaltest:1234` came back with
  // `http://internaltest:1234/...` in the body, which only happens via the
  // function's Host-header fallback path, not the X-Forwarded-Host branch.
  // So in THIS container, the origin Dispatcharr emits is whatever `Host`
  // the request arrived with — which for a `request.get` against `baseURL`
  // is `baseURL` itself. That makes the exact match below correct here, even
  // though it would need path-only assertion + a rewrite on a deployment
  // where X-Forwarded-Host does take effect.
  expect(mine!.url).toBe(`${baseURL}/proxy/ts/stream/${channel.uuid}`);
  expect(mine!.title).toBe(channel.name);
  // `toBe`, not `toBeTruthy`: the emitter has two different defaults and only
  // one of them is correct here. `ChannelSerializer.create` auto-assigns a
  // group literally named "Default Group" when none is given
  // (apps/channels/serializers.py:578), and the emitter renders
  // `effective_group.name` — but falls back to the *different* string
  // "Default" when a channel has no group at all (apps/output/views.py:269).
  // A truthiness check passes for either, so it cannot see the case that
  // matters: a channel whose auto-assignment silently did not happen.
  expect(mine!.attributes['group-title']).toBe('Default Group');

  // Rename round-trip. The quote-escaping pin below (#80) PATCHes this same
  // route, `/api/channels/channels/<id>/`, with a name — but inside its own
  // test.fail() block, where a regression in the PATCH-and-persist mechanism
  // itself (not just in quote escaping) would be swallowed as "expected
  // failure" and never surface. This proves the mechanism for an ordinary
  // name, with no quote character, through the API alone: the PATCH is
  // accepted, and the rename actually persists on a read-back. No second
  // `/output/m3u` fetch here — that route's 2-second anonymous cache (see the
  // `m3uQuery()` note at the top of this test) would make a second fetch a
  // source of flake, and the API alone already proves the rename.
  const newName = seed.generatedName('output-m3u-renamed');
  const renamed = await api.patch(`/api/channels/channels/${channel.id}/`, {
    name: newName,
  });
  expect(renamed.status()).toBe(200);

  const readBack = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channel.id}/`),
    'channel read-back after renaming'
  );
  expect(readBack.name).toBe(newName);
});

test('/output/m3u/<profile> renders only the channels enabled in that profile', { tag: '@contract' }, async ({
  seed,
  api,
  request,
}) => {
  const profile = await seed.channelProfile();
  const included = await seed.channel();
  const excluded = await seed.channel();

  // A channel created through the API joins EVERY Channel Profile, enabled,
  // unless channel_profile_ids says otherwise (ChannelViewSet.create) — and a
  // profile created first picks up every existing channel the same way
  // (create_profile_memberships). So both channels are already members here;
  // the test disables one.
  //
  // That also means this profile contains every OTHER worker's channels.
  // Assert on membership of the two we seeded, never on the profile's size.
  const patch = await api.patch(
    `/api/channels/profiles/${profile.id}/channels/${excluded.id}/`,
    { enabled: false }
  );
  expect(patch.status()).toBe(200);

  const res = await request.get(`/output/m3u/${profile.name}`);
  expect(res.status()).toBe(200);

  const names = parseM3u(await res.text()).entries.map((e) => e.attributes['tvg-name']);
  expect(names).toContain(included.name);
  expect(names).not.toContain(excluded.name);
});

test('/output/m3u/<profile> 404s on a profile that does not exist', { tag: '@contract' }, async ({
  seed,
  request,
}) => {
  // generate_m3u raises Http404 for an unknown profile name rather than
  // returning an empty playlist — worth pinning, because the HDHR lineup
  // makes the opposite choice for the same mistake (it returns []).
  const res = await request.get(`/output/m3u/${seed.generatedName('no-such-profile')}`);
  expect(res.status()).toBe(404);
});

// Fixed (#80). `apps.output.views._m3u_attr` now escapes `"` (to `&quot;`)
// in every quoted #EXTINF attribute value, so a channel or group name
// containing a double quote no longer closes the attribute early and
// spills the rest of the value out as unquoted text. `&` is left literal
// on purpose: players and Dispatcharr's own importer read M3U attributes
// verbatim. `seed.channel()` always overwrites `name` with its generated
// value (Task 1 pins this), so the quote is introduced with a PATCH after
// creation — an admin write via `api`, not a client-facing surface, so it
// doesn't violate the request-fixture rule above. The entry is located by
// URL, not by `tvg-name`, so the locator works whether or not the value is
// escaped.
test(
  'a channel name containing a double quote still produces a well-formed EXTINF line (#80)', { tag: '@contract' },
  async ({ seed, api, request }) => {
    const channel = await seed.channel();
    const quotedName = `${channel.name}-"quoted"`;

    const patched = await api.patch(`/api/channels/channels/${channel.id}/`, {
      name: quotedName,
    });
    expect(patched.status()).toBe(200);

    // Same shared 2-second anonymous cache key as the first test in this
    // file. Without a buster a stale hit makes `mine` undefined, and under
    // test.fail() that reads as the pin holding for a reason that has nothing
    // to do with quote escaping.
    const res = await request.get(`/output/m3u${m3uQuery()}`);
    expect(res.status()).toBe(200);

    const playlist = parseM3u(await res.text());
    const mine = playlist.entries.find((e) => e.url.includes(channel.uuid));
    expect(
      mine,
      `the renamed channel ${quotedName} should still have an entry in the playlist`
    ).toBeDefined();

    expect(
      mine!.wellFormed,
      `the EXTINF line for ${quotedName} should end its attribute list at the title comma`
    ).toBe(true);
    expect(decodeXmlEntities(mine!.attributes['tvg-name'] ?? '')).toBe(quotedName);
    expect(decodeXmlEntities(mine!.title)).toBe(quotedName);
  }
);
