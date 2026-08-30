import { test, expect } from '../../fixtures';
import type { Channel, StreamPage } from '../../fixtures';

/**
 * `Channel.is_catchup` through the **ingest rollup**, in both directions.
 *
 * `e2e/tests/seeded/xc-ingest.spec.ts` (G8) already proves the stream-level
 * half — a provider's `tv_archive` reaching `Stream.is_catchup`/
 * `catchup_days`, with `no-tv-archive` armed on a second channel as the
 * mutation check. This file does not repeat it.
 *
 * What it proves instead is the half only an E2E test can reach:
 * `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:1963-2014`), the raw
 * Postgres statement that runs at the end of every refresh (`:3853`),
 * reacting to a `Stream`'s catch-up flags changing under a channel that is
 * **already wired**.
 *
 * Both tests below wire the channel while the stream's catch-up state is the
 * OPPOSITE of what is finally asserted, then flip the provider and refresh.
 * That ordering is the whole design. `Channel.is_catchup` has a second
 * mechanism — `update_channel_catchup_fields`
 * (`apps/channels/signals.py:393-407`), a `post_save`/`post_delete` receiver
 * on `ChannelStream` that `ChannelSerializer.create` fires synchronously —
 * and a test that wires a channel to an already-catch-up stream observes
 * THAT, not the rollup, however many refreshes it runs afterwards
 * (mutation-checked in `seedCatchupChannel`'s header,
 * `e2e/tests/streaming/helpers.ts`). After the wiring below, no
 * `ChannelStream` row is created or deleted, so the signal cannot fire and
 * the rollup is the only thing left that can have changed the row.
 *
 * `waitFor.m3uRefreshComplete` returning `success` is sufficient
 * sequencing: the rollup runs at `apps/m3u/tasks.py:3853`, the status is
 * written at `:3865`.
 */

const ARCHIVE_DAYS = 7; // e2e-upstream's DEFAULT_ARCHIVE_DAYS.

async function streamsByName(
  api: import('../../fixtures').ApiClient,
  prefix: string
): Promise<Map<string, StreamPage['results'][number]>> {
  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    `streams ingested for ${prefix}`
  );
  return new Map(page.results.map((s) => [s.name, s]));
}

async function readChannel(
  api: import('../../fixtures').ApiClient,
  id: number
): Promise<Channel> {
  return api.json<Channel>(
    await api.get(`/api/channels/channels/${id}/`),
    `channel ${id}`
  );
}

test('a provider turning tv_archive on sets Channel.is_catchup through the ingest rollup', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const prefix = seed.generatedName('catchup-rollup-on');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: 1, name: `${prefix}-arch`, tvgId: `${prefix}-arch.e2e`, logo: null, categoryId: 1 },
      { id: 2, name: `${prefix}-never`, tvgId: `${prefix}-never.e2e`, logo: null, categoryId: 1 },
    ],
  });

  // Both channels start WITHOUT tv_archive. Channel 2 stays that way for the
  // whole test, but its stream is never wired to a Channel row below — so it
  // is a negative control on the fault's channel-scoping and the
  // stream-level ingest path (that `no-tv-archive` on channel 1 doesn't leak
  // onto channel 2's stream), not on the rollup. The rollup only ever
  // touches channels a Stream is wired to.
  await upstream.fault(scenario, 'no-tv-archive', { channel: 1 });
  await upstream.fault(scenario, 'no-tv-archive', { channel: 2 });

  const account = await seed.xcAccount(scenario);
  const first = await waitFor.m3uRefreshComplete(account.id);
  expect(first.status, 'first XC refresh').toBe('success');

  const before = await streamsByName(api, prefix);
  expect(before.get(`${prefix}-arch`)!.is_catchup).toBe(false);
  expect(before.get(`${prefix}-arch`)!.catchup_days).toBe(0);

  // Wire the channel NOW, while the stream is not catch-up. This is what
  // makes the assertion at the end a rollup proof: the ChannelStream signal
  // fires here, with `false`, and never again.
  //
  // Read this next assertion for what it is: a BASELINE, not a proof. `false`
  // is equally what "the signal ran and wrote false", "the signal never ran"
  // and "the field defaults to false" look like, and nothing here can tell
  // them apart. Its job is to establish that the channel is not already
  // catch-up before the flip, so the `true` at the end of this test is a
  // change rather than a starting state. `after.get(`${prefix}-never`)`
  // below is the fault-scoping / stream-level control described above, not
  // a control on the rollup itself — channel 2's stream is never wired to a
  // channel, so the rollup has nothing of channel 2's to touch either way.
  const streamId = before.get(`${prefix}-arch`)!.id;
  const created = await seed.channel({ streams: [streamId] });
  const wired = await readChannel(api, created.id);
  expect(wired.is_catchup, 'the channel starts not-catch-up, before the flip').toBe(false);

  await upstream.clearFault(scenario, 'no-tv-archive', { channel: 1 });

  const second = await waitFor.m3uRefreshComplete(account.id);
  expect(second.status, 'second XC refresh').toBe('success');

  const after = await streamsByName(api, prefix);
  expect(after.get(`${prefix}-arch`)!.is_catchup).toBe(true);
  expect(after.get(`${prefix}-arch`)!.catchup_days).toBe(ARCHIVE_DAYS);
  expect(after.get(`${prefix}-never`)!.is_catchup).toBe(false);
  expect(after.get(`${prefix}-never`)!.catchup_days).toBe(0);

  // THE ROLLUP. No ChannelStream row was created or deleted between the
  // wiring above and here, so `update_channel_catchup_fields`
  // (apps/channels/signals.py:393-407) cannot have fired.
  // `rollup_channel_catchup_fields`'s aggregate pass
  // (apps/m3u/tasks.py:1978-1997, `bool_or(s.is_catchup AND a.is_active)`
  // and `MAX(s.catchup_days) FILTER (...)`) is the only mechanism left.
  const rolled = await readChannel(api, created.id);
  expect(rolled.is_catchup).toBe(true);
  expect(rolled.catchup_days).toBe(ARCHIVE_DAYS);
});

test('a provider turning tv_archive off clears Channel.is_catchup on the next refresh', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const prefix = seed.generatedName('catchup-rollup-off');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: 1, name: `${prefix}-arch`, tvgId: `${prefix}-arch.e2e`, logo: null, categoryId: 1 },
    ],
  });

  const account = await seed.xcAccount(scenario);
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const before = await streamsByName(api, prefix);
  expect(before.get(`${prefix}-arch`)!.is_catchup).toBe(true);
  expect(before.get(`${prefix}-arch`)!.catchup_days).toBe(ARCHIVE_DAYS);

  const streamId = before.get(`${prefix}-arch`)!.id;
  const created = await seed.channel({ streams: [streamId] });
  const wired = await readChannel(api, created.id);
  expect(wired.is_catchup, 'the signal set it at wiring time').toBe(true);
  expect(wired.catchup_days).toBe(ARCHIVE_DAYS);

  await upstream.fault(scenario, 'no-tv-archive', { channel: 1 });
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const after = await streamsByName(api, prefix);
  expect(after.get(`${prefix}-arch`)!.is_catchup).toBe(false);
  expect(after.get(`${prefix}-arch`)!.catchup_days).toBe(0);

  // Again the rollup, and this is the direction that matters operationally:
  // a provider that stops advertising an archive must not leave channels
  // claiming one. No ChannelStream row changed, so the signal cannot have
  // fired. Note `catchup_days` going to 0 as well as the boolean —
  // COALESCE(agg.max_days, 0) (apps/m3u/tasks.py:1993-1994) is what does it,
  // and a rollup that cleared only the boolean would leave a channel
  // advertising `tv_archive_duration: 7` on the XC surface with
  // `tv_archive: 0`.
  const rolled = await readChannel(api, created.id);
  expect(rolled.is_catchup).toBe(false);
  expect(rolled.catchup_days).toBe(0);

  // Rule out the channel having lost its wiring instead of the rollup
  // clearing it. The rollup's UPDATE is scoped through ChannelStream
  // (apps/m3u/tasks.py:1978-1997 joins channels_channelstream) — a channel
  // with zero streams falls outside it entirely, and a `false` produced that
  // way would actually come from update_channel_catchup_fields's
  // post_delete branch (apps/channels/signals.py:393-407), not the rollup.
  // Assert the SAME Stream row survived the refresh (ruling out a
  // delete-and-recreate that cascades to ChannelStream) and is still on the
  // channel.
  expect(after.get(`${prefix}-arch`)!.id, 'the refresh reused the same Stream row').toBe(
    streamId
  );
  expect(rolled.streams, 'the channel is still wired to that stream').toContain(streamId);
});
