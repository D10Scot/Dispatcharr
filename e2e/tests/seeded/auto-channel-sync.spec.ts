import { test, expect } from '../../fixtures';
import type { Channel, GroupSettingRow, M3uAccount, M3uAccountChannelGroup, StreamPage } from '../../fixtures';
import { applyGroupSettings, syncWindowFor } from './helpers';

type AccountWithGroups = M3uAccount & { channel_groups: M3uAccountChannelGroup[] };

test('enabling auto channel sync creates one channel per stream inside the declared window', async ({
  upstream,
  seed,
  api,
  waitFor,
}, testInfo) => {
  // Two full fetch-and-parse refreshes against the project's 30s default.
  test.setTimeout(150_000);

  const prefix = seed.generatedName('autosync');
  const declared = [1, 2, 3, 4].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: null,
  }));
  const scenario = await upstream.scenario({ channels: declared });

  const account = await seed.m3uAccount({
    server_url: upstream.playlistUrl(scenario),
    is_active: true,
  });

  // Creating the account active queues the create-time `refresh_m3u_groups`
  // task unconditionally (`post_save`, apps/m3u/signals.py:12-15) — a second,
  // independent writer of the exact `status`/`last_message` fields
  // `waitFor.m3uRefreshComplete()` diffs against its pre-trigger baseline.
  // `seed.upstreamM3UAccount()` cannot be reused here (this test needs the
  // group left un-synced after refresh 1, which that factory does not
  // expose), so this closes the same race the same way it does internally:
  // wait for the create-time task's own terminal disposition before reading
  // any baseline. Skipping this is not hypothetical — it reproduced as a
  // spurious `first.status === 'error'` under 4-worker parallel load in this
  // task's own verification run (see the report).
  await seed.waitForCreateTimeGroupRefreshToSettle(account.id);

  // Refresh 1: creates the ChannelGroup, the ChannelGroupM3UAccount relation
  // and the Streams. `process_groups` never sets `auto_channel_sync`, so it is
  // always false after the first refresh and no channel is created.
  //
  // `startTimeoutMs` widened past the 30s default (phase 1: waiting for the
  // refresh to *start*): under sustained heavy parallel load in this task's
  // own repeated stress runs (--repeat-each=8 at 4 workers, well beyond what
  // `seeded`'s normal 4-worker run does concurrently), this container's
  // Celery pickup occasionally took longer than 30s to move an account past
  // its pre-trigger baseline at all — a real, load-dependent hazard, not a
  // logic bug (see the report for the reproduction). 150s of test.setTimeout
  // budget comfortably absorbs a wider phase 1 here.
  const first = await waitFor.m3uRefreshComplete(account.id, { startTimeoutMs: 60_000 });
  expect(first.status).toBe('success');

  const noChannelsYet = await api.json<Channel[]>(
    await api.get(`/api/channels/channels/?name=${encodeURIComponent(prefix)}`),
    'channels after the first refresh'
  );
  expect(noChannelsYet).toHaveLength(0);

  const withGroups = await api.json<AccountWithGroups>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'account read-back for its group relation'
  );
  // The brief this task started from asserted `toHaveLength(1)` here — false.
  // The create-time group refresh (`apps/m3u/tasks.py:1559`,
  // `groups = {"Default Group": {}}`) always seeds a "Default Group" entry
  // before merging in whatever the playlist actually declares, so a brand
  // new account carries a *second*, zero-stream relation to "Default Group"
  // in addition to the one for the playlist's real group ("E2E", per
  // `m3u-ingest.spec.ts`'s `UPSTREAM_GROUP_NAME`). Picking the relation by
  // `stream_count === declared.length` is what actually distinguishes ours
  // from the placeholder — a length assertion on the array would have been
  // true today only because this scenario declares exactly one non-default
  // group, and false the moment a scenario declared two.
  const relation = withGroups.channel_groups.find(
    (g) => g.stream_count === declared.length
  );
  expect(
    relation,
    `no group relation with stream_count === ${declared.length} among ${JSON.stringify(withGroups.channel_groups)}`
  ).toBeDefined();
  expect(relation!.auto_channel_sync).toBe(false);

  const window = syncWindowFor(testInfo.workerIndex, 0);
  const row: GroupSettingRow = {
    channel_group: relation!.channel_group,
    enabled: true,
    auto_channel_sync: true,
    auto_sync_channel_start: window.start,
    auto_sync_channel_end: window.end,
    // Sent explicitly: `update_group_settings` is a full-field upsert and an
    // omitted key is written as `{}`, not merged.
    custom_properties: {},
  };
  await applyGroupSettings(api, account.id, [row]);

  const readBack = await api.json<AccountWithGroups>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'account read-back after group-settings'
  );
  const updated = readBack.channel_groups.find(
    (g) => g.channel_group === relation!.channel_group
  );
  expect(updated?.auto_channel_sync).toBe(true);
  expect(updated?.auto_sync_channel_start).toBe(window.start);
  expect(updated?.auto_sync_channel_end).toBe(window.end);

  // Refresh 2: `sync_auto_channels` runs synchronously inside the refresh and
  // now sees an enabled, auto-sync group. Same `startTimeoutMs` widening as
  // refresh 1, for the same reason — this is the call that actually timed
  // out in this task's own stress runs.
  const second = await waitFor.m3uRefreshComplete(account.id, { startTimeoutMs: 60_000 });
  expect(second.status).toBe('success');

  // No poll here — a direct read is not raced. `_refresh_single_m3u_account_impl`
  // calls `sync_auto_channels()` (apps/m3u/tasks.py:3821), which creates every
  // new Channel via a plain `Channel.objects.bulk_create()`
  // (apps/m3u/tasks.py:2772) with no `transaction.atomic()` wrapping it — an
  // ordinary autocommitting write, durable and visible to any other connection
  // the instant it returns. Only *after* `sync_auto_channels()` returns does
  // the same function set `account.status = SUCCESS` and save it
  // (apps/m3u/tasks.py:3865-3873) — a second, independent autocommitting write,
  // strictly later in the same worker process. `waitFor.m3uRefreshComplete()`
  // above already polled until it observed that second write, so by the time
  // `second.status === 'success'` resolves, the channel rows were committed
  // before this test process ever asked. A `waitFor.resource()` retry loop
  // here would only be re-proving something already true through a slower,
  // flakier-looking path — worth avoiding on a 150s test.
  const channels = await api.json<Channel[]>(
    await api.get(`/api/channels/channels/?name=${encodeURIComponent(prefix)}`),
    'auto-created channels'
  );
  expect(channels).toHaveLength(declared.length);

  const streams = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'ingested streams'
  );
  expect(streams.count).toBe(declared.length);

  for (const channel of channels) {
    expect(channel.auto_created).toBe(true);
    expect(channel.streams).toHaveLength(1);
    expect(channel.channel_number).not.toBeNull();
    expect(channel.channel_number!).toBeGreaterThanOrEqual(window.start);
    expect(channel.channel_number!).toBeLessThanOrEqual(window.end);
  }

  // Relative, never absolute (see syncWindowFor): the reservation set is
  // global, so another worker's channel inside this window shifts the packing.
  // What the product promises is that the window is honoured and that the
  // catalogue's order is preserved — that is what this asserts.
  const numbers = channels.map((c) => c.channel_number!);
  expect(new Set(numbers).size).toBe(numbers.length);

  const inCatalogueOrder = declared.map(
    (spec) => channels.find((c) => c.name === spec.name)!.channel_number!
  );
  const ascending = [...inCatalogueOrder].sort((a, b) => a - b);
  expect(inCatalogueOrder).toEqual(ascending);
});
