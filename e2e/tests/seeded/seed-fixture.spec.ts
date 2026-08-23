import { test, expect } from '../../fixtures';

test('seeded channel is retrievable and namespaced', async ({ api, seed }) => {
  const channel = await seed.channel();

  expect(channel.id).toBeTruthy();
  expect(channel.name).toMatch(/^e2e-w\d+-/);

  const res = await api.get(`/api/channels/channels/${channel.id}/`);
  expect(res.status()).toBe(200);
  expect((await res.json()).name).toBe(channel.name);
});

test('seeded names are unique within a test', async ({ seed }) => {
  const a = await seed.channel();
  const b = await seed.channel();
  expect(a.name).not.toBe(b.name);
});

test('overrides are applied', async ({ seed }) => {
  const profile = await seed.channelProfile();
  expect(profile.name).toMatch(/channelProfile/);

  const user = await seed.user({ user_level: 1 });
  expect(user.user_level).toBe(1);
});
