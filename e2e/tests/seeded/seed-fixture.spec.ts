import { test, expect, Seeder } from '../../fixtures';
import type { Channel } from '../../fixtures';

test('seeded channel is retrievable and namespaced', async ({ api, seed }) => {
  const channel = await seed.channel();

  expect(channel.id).toBeTruthy();
  expect(channel.name).toMatch(/^e2e-w\d+-/);

  const res = await api.get(`/api/channels/channels/${channel.id}/`);
  expect(res.status()).toBe(200);
  // `api.json<Channel>` rather than `res.json()`: the latter is Playwright's,
  // and returns `any`. Naming the shape is how a field that stops existing
  // becomes a typecheck failure instead of a runtime `undefined`.
  const fetched = await api.json<Channel>(res, 'seeded channel read-back');
  expect(fetched.name).toBe(channel.name);
});

test('seeded names are unique within a test', async ({ seed }) => {
  const a = await seed.channel();
  const b = await seed.channel();
  expect(a.name).not.toBe(b.name);
});

test('overrides are applied', async ({ seed }) => {
  // Never a bare `profile` — CONTEXT.md's first rule. Three different things
  // in this product are called one.
  const channelProfile = await seed.channelProfile();
  expect(channelProfile.name).toMatch(/channelProfile/);

  // user_level defaults to 1 in seed.ts — override to 0 so this assertion
  // can actually fail if ...overrides stopped being applied.
  const user = await seed.user({ user_level: 0 });
  expect(user.user_level).toBe(0);
});

// The generated identity field (name, or username for user) must win over a
// caller-supplied one — this is the whole point of the fixture. A refactor
// that puts ...overrides back after the generated field would make these
// tests fail without needing a container reset to notice.
//
// Both defences are pinned here, and each `@ts-expect-error` below carries
// half of it:
//
//  - the *compile-time* half — `name` is absent from `ChannelOverrides` and
//    `username` from `UserOverrides`, so passing one is an error.
//    `@ts-expect-error` fails the typecheck if that error ever *stops*
//    happening, which is what makes these lines an assertion rather than a
//    suppression;
//  - the *runtime* half — the body below is sent anyway (the directive is a
//    compiler instruction, and Playwright transpiles without type checking),
//    so the request really does carry the caller's identity field and the
//    assertions really do prove the factory discarded it.
//
// Which is why these must not be softened to a cast: an `as` would silence
// the compiler without noticing if the type were later widened to accept the
// field, and the type would then be advertising a knob that does nothing.

test('a passed name cannot override the generated channel name', async ({
  seed,
}) => {
  // @ts-expect-error `name` is deliberately not in ChannelOverrides — see above.
  const channel = await seed.channel({ name: 'fixed-name' });
  expect(channel.name).not.toBe('fixed-name');
  expect(channel.name).toMatch(/^e2e-w\d+-/);
});

test('a passed username cannot override the generated user username', async ({
  seed,
}) => {
  // @ts-expect-error `username` is deliberately not in UserOverrides — see above.
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

// The remaining three factories, which no other spec exercises. Each ships a
// set of defaults that has to stay valid against the live API — a serializer
// gaining a required field is the failure this catches, and it would
// otherwise surface as a mystery 400 inside whichever wave-2 test first
// reached for the factory.
test('the source factories create rows with the shipped defaults', async ({
  seed,
}) => {
  const streamProfile = await seed.streamProfile();
  expect(streamProfile.id).toBeTruthy();
  expect(streamProfile.name).toMatch(/^e2e-w\d+-/);

  const m3uAccount = await seed.m3uAccount();
  expect(m3uAccount.id).toBeTruthy();
  expect(m3uAccount.name).toMatch(/^e2e-w\d+-/);

  const epgSource = await seed.epgSource();
  expect(epgSource.id).toBeTruthy();
  expect(epgSource.name).toMatch(/^e2e-w\d+-/);
});

test('seed.stream creates a custom stream with a generated name', async ({ seed }) => {
  const stream = await seed.stream({ url: 'http://127.0.0.1:9/x.ts' });

  expect(stream.id).toBeGreaterThan(0);
  expect(stream.is_custom).toBe(true);
  expect(stream.url).toBe('http://127.0.0.1:9/x.ts');
  expect(stream.name).toMatch(/^e2e-w\d+-/);
});

test('seed.stream ignores an attempt to override the generated name', async ({ seed }) => {
  // The identity field is spread AFTER overrides. A cast is the only way to
  // even attempt this, which is the point of the test: the type forbids it,
  // and the ordering enforces it for bodies that dodge the type.
  const stream = await seed.stream({ name: 'not-this' } as never);
  expect(stream.name).not.toBe('not-this');
});

test('seed.upstreamChannel wires a channel to the provider in order', async ({
  seed,
  upstream,
}) => {
  const scenario = await upstream.scenario({
    // tvgId/logo are required on UpstreamChannel; the brief's literal omitted
    // them. Values are arbitrary — this test never asserts on either.
    channels: [
      { id: 1, name: 'Primary', tvgId: 'primary.e2e', logo: null },
      { id: 2, name: 'Backup', tvgId: 'backup.e2e', logo: null },
    ],
  });

  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
  });

  expect(streams).toHaveLength(2);
  expect(streams[0].url).toBe(upstream.streamUrl(scenario, 1));
  expect(streams[1].url).toBe(upstream.streamUrl(scenario, 2));
  expect(channel.streams).toEqual([streams[0].id, streams[1].id]);
  expect(channel.uuid).toBeTruthy();
});
