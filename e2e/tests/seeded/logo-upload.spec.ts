import { test, expect, logoPayload } from '../../fixtures';
import type { Channel } from '../../fixtures';

test('a logo uploads, assigns to a channel and serves its bytes back', { tag: '@contract' }, async ({
  seed,
  api,
  request,
}) => {
  const logo = await seed.logo();

  expect(logo.id).toBeGreaterThan(0);
  // `url` is the on-disk path, not an HTTP URL — `Logo` has no FileField.
  expect(logo.url.startsWith('/data/logos/')).toBeTruthy();
  expect(logo.url.endsWith('.png')).toBeTruthy();
  // Exact form, not `toContain`: the fallback path (`os.path.basename` when
  // the `name` form field is ignored, `api_views.py:2843-2844`) would produce
  // `.../<name>.png.png`, which still *contains* `logo.name` — so only the
  // exact match proves the plain form field was honoured.
  expect(logo.url).toBe(`/data/logos/${logo.name}.png`);
  expect(logo.cache_url).toContain(`/api/channels/logos/${logo.id}/cache/`);

  const channel = await seed.channel();
  expect(channel.logo_id).toBeNull();

  // The writable field is `logo_id` (`PrimaryKeyRelatedField(source="logo")`);
  // there is no writable `logo`.
  const patched = await api.patch(`/api/channels/channels/${channel.id}/`, {
    logo_id: logo.id,
  });
  expect(patched.ok()).toBeTruthy();

  const readBack = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channel.id}/`),
    'channel read-back after assigning a logo'
  );
  expect(readBack.logo_id).toBe(logo.id);

  // `LogoViewSet.cache` is AllowAny, so this needs no auth header — the plain
  // `request` context is the honest way to say so.
  const served = await request.get(logo.cache_url);
  expect(served.status()).toBe(200);
  // `serve_local_or_remote_image` streams the file verbatim for a local
  // `/data` path (`core/image_proxy.py:193-209`). Every seeded logo's payload
  // is unique (`logoPayload`, keyed on its name), so comparing the served
  // bytes against exactly *this* logo's payload proves the endpoint served
  // this logo's file, not merely a same-length or same-shared-bytes file —
  // a wrong-row bug (`cache_url` resolving to another logo's `url`) would
  // pass a byte-count check but fail this.
  expect((await served.body()).equals(logoPayload(logo.name))).toBeTruthy();
  expect(served.headers()['content-type']).toContain('image');
});
