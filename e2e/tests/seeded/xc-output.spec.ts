import { test, expect, parseM3u, parseXmltv, xcQuery } from '../../fixtures';

/**
 * These two live at the SITE ROOT, not under /output/ — dispatcharr/urls.py
 * mounts them before the SPA catch-all. They route into the same
 * generate_m3u / generate_epg the /output/ endpoints use, but with a user, so
 * the bodies differ in ways worth pinning.
 *
 * Neither needs the ?days= cache workaround the anonymous /output/epg does:
 * the chunk-cache key contains the username, and seed.xcUser() generates a
 * fresh one per test.
 *
 * RULING R10 (task-9-report.md): the spec's row 10 wants both 401 (bad
 * credentials) *and* 403 (blocked network) proven. The 403 half needs
 * mutating the global `XC_API` network-ACL CoreSettings row, which the
 * spec's Non-goals forbid ("widening any network ACL") and which four
 * workers share — flipping it here would 403 every other worker's XC
 * traffic mid-run. So only the 401 half is proven; the 403 branch
 * (apps/output/views.py:496-508, :531-543) is untested by this suite.
 */

test('get.php renders an XC-flavoured playlist for its user', async ({
  seed,
  request,
  baseURL,
}) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const res = await request.get(`/get.php${xcQuery(user, { type: 'm3u_plus' })}`);
  expect(res.status()).toBe(200);

  const playlist = parseM3u(await res.text());

  // An XC request gets an XC guide URL, not /output/epg.
  expect(playlist.header['x-tvg-url']).toContain('/xmltv.php');

  const mine = playlist.entries.find((e) => e.attributes['tvg-name'] === channel.name);
  expect(mine, `${channel.name} should be in the XC playlist`).toBeDefined();

  // XC-style stream URL: /live/<username>/<password>/<numeric channel id>.
  // Note the numeric id here against the UUID /output/m3u emits — the same
  // channel, addressed two different ways by two different surfaces.
  //
  // The username/password segments are echoes — generate_m3u
  // (apps/output/views.py:200-201) reads xc_username/xc_password straight
  // back out of request.GET, so matching them proves nothing on its own.
  // What actually discriminates here is the `/live/` prefix (the
  // is_xc_request branch, unreachable unless `user` resolved, versus
  // `/proxy/ts/stream/` for a non-XC request) and the real `channel.id`.
  // Not a defect, just worth being explicit about so a later pass doesn't
  // "strengthen" this by adding more echo comparisons.
  expect(mine!.url).toBe(
    `${baseURL}/live/${user.username}/${user.xcPassword}/${channel.id}`
  );
});

test('xmltv.php renders a guide for its user', async ({ seed, request }) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const res = await request.get(`/xmltv.php${xcQuery(user)}`);
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/xml');

  const guide = parseXmltv(await res.text());
  expect(
    guide.channels.some((c) => c.displayNames.includes(channel.name)),
    `${channel.name} should be in the XC guide`
  ).toBe(true);
});

test('both reject bad credentials with 401', async ({ seed, request }) => {
  const user = await seed.xcUser();

  // Positive control (issue #84, same disambiguation as
  // xc-vod-catalogue-shape.spec.ts): xc_get_user (apps/output/views.py:364)
  // rejects with get_object_or_404(User, username=…), so an *unrecognised
  // username* 404s ahead of any credential check. The case below deliberately
  // reuses this exact, resolvable username with only the password wrong, so
  // it can only ever land on the password comparison
  // (custom_properties["xc_password"] != password) — but that guarantee is
  // only as good as seed.xcUser() actually producing a user the server can
  // find. Proving both endpoints return 200 for these exact credentials
  // first is what rules out a broken seed silently turning "wrong password"
  // into "unknown user" and still going green. Each endpoint gets its own
  // control — a control run against the other endpoint doesn't make this
  // one self-contained (Task 8's ruling: every rejection assertion on this
  // surface needs its own positive control).
  const good = xcQuery(user);
  const getControl = await request.get(`/get.php${good}`);
  expect(getControl.status(), 'positive control: get.php for this user').toBe(200);
  const xmltvControl = await request.get(`/xmltv.php${good}`);
  expect(xmltvControl.status(), 'positive control: xmltv.php for this user').toBe(200);

  const bad = `?username=${encodeURIComponent(user.username)}&password=wrong`;

  expect((await request.get(`/get.php${bad}`)).status()).toBe(401);
  expect((await request.get(`/xmltv.php${bad}`)).status()).toBe(401);
});
