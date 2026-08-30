import { test, expect, parseM3u } from '../../fixtures';

/**
 * `/output/m3u[/<profile>]` — the client-facing M3U playlist surface.
 *
 * Driven with the built-in `request` fixture everywhere, never `api`: this is
 * how TiviMate, Plex and every other real client fetch a playlist, with no
 * bearer token. The `api` fixture is reserved here for seeding and for the
 * one profile-membership PATCH, which is an admin write, not a client read.
 *
 * Four workers share one instance and `generate_m3u` with no profile in the
 * URL renders every channel that exists — so nothing here may assert a
 * playlist length or an unfiltered entry list. Every assertion locates the
 * row(s) this test seeded by the generated name and checks only those.
 */

test('/output/m3u renders a parseable playlist with a well-formed proxy URL', async ({
  seed,
  request,
  baseURL,
}) => {
  const channel = await seed.channel();

  // No bearer token: this is how a real client fetches a playlist, and it is
  // what makes the assertion meaningful. `request` is Playwright's built-in
  // context; the `api` fixture would add an Authorization header no TiviMate
  // or Plex install has.
  const res = await request.get('/output/m3u');
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
});

test('/output/m3u/<profile> renders only the channels enabled in that profile', async ({
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

test('/output/m3u/<profile> 404s on a profile that does not exist', async ({
  seed,
  request,
}) => {
  // generate_m3u raises Http404 for an unknown profile name rather than
  // returning an empty playlist — worth pinning, because the HDHR lineup
  // makes the opposite choice for the same mistake (it returns []).
  const res = await request.get(`/output/m3u/${seed.generatedName('no-such-profile')}`);
  expect(res.status()).toBe(404);
});

/**
 * `apps/output/views.py:304-306` interpolates the raw channel name into
 * `tvg-name="{tvg_name}"` (and `group-title="{group_title}"`) with no
 * quote-escaping. A channel whose name contains a `"` therefore breaks the
 * EXTINF line: the embedded quote closes the attribute early and the rest of
 * the value spills out as unquoted text, so no parser — including this
 * suite's own `parseM3u` — can round-trip the name back out of the response.
 *
 * `seed.channel()` always overwrites `name` with its generated value (Task 1
 * pins this), so a quote can't be seeded through the factory. This PATCHes
 * the name after creation instead — an admin write via `api`, not a
 * client-facing surface, so it doesn't violate the request-fixture rule
 * above.
 *
 * Asserts the CORRECT behaviour (a well-formed EXTINF line whose `tvg-name`
 * round-trips) and is expected to fail until the product escapes the value.
 * Filed as https://github.com/D10Scot/Dispatcharr/issues/80. Do not patch
 * the product from this harness; do not file a duplicate issue.
 */
test.fail(
  'a channel name containing a double quote still produces a well-formed EXTINF line (#80)',
  async ({ seed, api, request }) => {
    const channel = await seed.channel();
    const quotedName = `${channel.name}-"quoted"`;

    const patched = await api.patch(`/api/channels/channels/${channel.id}/`, {
      name: quotedName,
    });
    expect(patched.status()).toBe(200);

    const res = await request.get('/output/m3u');
    expect(res.status()).toBe(200);

    const playlist = parseM3u(await res.text());
    const mine = playlist.entries.find((e) => e.attributes['tvg-name'] === quotedName);
    expect(mine, `the renamed channel ${quotedName} should round-trip through the playlist`).toBeDefined();
  }
);
