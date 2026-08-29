import { test, expect } from '../../fixtures';
import type { Channel } from '../../fixtures';

test('a logo uploads, assigns to a channel and serves its bytes back', async ({
  seed,
  api,
  request,
}) => {
  const logo = await seed.logo();

  expect(logo.id).toBeGreaterThan(0);
  // `url` is the on-disk path, not an HTTP URL — `Logo` has no FileField.
  expect(logo.url.startsWith('/data/logos/')).toBeTruthy();
  expect(logo.url.endsWith('.png')).toBeTruthy();
  expect(logo.url).toContain(logo.name);
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
  expect((await served.body()).length).toBeGreaterThan(0);
});
