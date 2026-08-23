import { test, expect, Seeder } from '../../fixtures';

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

  // user_level defaults to 1 (seed.ts:57) — override to 0 so this assertion
  // can actually fail if ...overrides stopped being applied.
  const user = await seed.user({ user_level: 0 });
  expect(user.user_level).toBe(0);
});

// The generated identity field (name, or username for user) must win over a
// caller-supplied one — this is the whole point of the fixture. A refactor
// that puts ...overrides back after the generated field would make these
// tests fail without needing a container reset to notice.

test('a passed name cannot override the generated channel name', async ({
  seed,
}) => {
  const channel = await seed.channel({ name: 'fixed-name' });
  expect(channel.name).not.toBe('fixed-name');
  expect(channel.name).toMatch(/^e2e-w\d+-/);
});

test('a passed username cannot override the generated user username', async ({
  seed,
}) => {
  const user = await seed.user({ username: 'fixed' });
  expect(user.username).not.toBe('fixed');
  expect(user.username).toMatch(/^e2e-w\d+-/);
});

// Pure unit check — no server round trip. testId and workerIndex are both
// stable across separate invocations of the same spec; runToken is what
// keeps two Seeder instances constructed with identical arguments from
// producing identical names, which is what let a second `npm run
// test:seeded` against a live container collide with its own previous run.
test('runToken makes names differ across Seeder instances with identical arguments', ({
  api,
}) => {
  const a = new Seeder(api, 0, 'x').generatedName('channel');
  const b = new Seeder(api, 0, 'x').generatedName('channel');

  expect(a).not.toBe(b);
  expect(a).toMatch(/^e2e-w0-/);
  expect(b).toMatch(/^e2e-w0-/);
});
