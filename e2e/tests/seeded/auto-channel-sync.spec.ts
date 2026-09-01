import { test, expect } from '../../fixtures';
import type { Channel, GroupSettingRow, M3uAccount, M3uAccountChannelGroup, StreamPage } from '../../fixtures';
import { applyGroupSettings, syncWindowFor } from './helpers';

type AccountWithGroups = M3uAccount & { channel_groups: M3uAccountChannelGroup[] };

test('enabling auto channel sync creates one channel per stream inside the declared window', { tag: '@contract' }, async ({
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
  // Default `startTimeoutMs` (30s): the review round on this task traced the
  // original flake here to a dropped trigger (D10Scot/Dispatcharr#59, fixed
  // in `waitFor.m3uRefreshComplete()` itself), not slow Celery pickup, and
  // this refresh has no preceding refresh on the same account competing for
  // its task lock — there is no standalone evidence a wider window is
  // needed here, so it stays at the shared default.
  const first = await waitFor.m3uRefreshComplete(account.id);
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
  // now sees an enabled, auto-sync group. This is the call that landed
  // inside refresh 1's still-held task lock and timed out under stress
  // before the fix — `waitFor.m3uRefreshComplete()` now re-triggers itself
  // when that happens (D10Scot/Dispatcharr#59), so the 60s widening this
  // call previously carried was a fix-round-1 workaround for the same root
  // cause and is no longer needed at the default 30s.
  const second = await waitFor.m3uRefreshComplete(account.id);
  expect(second.status).toBe('success');

  // Diagnostic, not an assertion: a review round on this file's sibling test
  // (Task 10) found this exact shape — `second.status === 'success'` with
  // zero channels afterward — under full-suite load. `last_message`'s
  // "Auto-sync:" segment (or lack of one) is baked into the poll's timeout
  // message below so a recurrence is evidence, not another from-scratch
  // investigation — but read it against what the segment can actually mean:
  //
  // `sync_auto_channels()` (apps/m3u/tasks.py:2018) opens with three local
  // imports and two assignments (:2024-2038), then wraps everything after
  // them in a `try` (:2039) whose `except` (:3018-3028) returns
  // `{"status": "error", ...}` instead of raising. So the *caller's* outer
  // `try`/`except` (:3820, :3847) — the mechanism D10Scot/Dispatcharr#70
  // describes — is unreachable in practice through this path: a
  // `sync_auto_channels()` failure surfaces as a returned status, not a
  // raised exception. (A raise from those first five statements would reach
  // the caller's handler and produce an absent segment, but they are three
  // imports, a `_meta` field lookup and a float literal.)
  // That returned `status: "error"` is rendered at :3843-3846 as a
  // *present* `" Auto-sync error: {error}."` segment, not an absent one —
  // the opposite of what #70 would predict here.
  // An absent "Auto-sync:" segment is instead the benign, routine case: the
  // all-zeros guard at :3832 (`if created or updated or deleted or failed:`)
  // skips the message whenever nothing changed. Both plausible
  // D10Scot/Dispatcharr#59 residuals land here — resolving on refresh 1
  // before auto-sync was enabled (empty `auto_sync_groups`), and an
  // idempotent duplicate refresh where `channels_updated` never increments
  // (:2673-2680).
  // A third shape exists that neither issue predicts: `" Auto-sync: N
  // failed."` with no created/updated/deleted, from window exhaustion
  // (RANGE_EXHAUSTED, :2696-2702 feeding the render at :3842) — see
  // `syncWindowFor`'s doc comment in `./helpers.ts` on why a window is a
  // budget, not an infinite resource. Observed exactly once, during Task
  // 10's verification against a container that had not been reset.
  //
  // `_refresh_single_m3u_account_impl` calls `sync_auto_channels()`
  // (apps/m3u/tasks.py:3821), which creates every new Channel via a plain
  // `Channel.objects.bulk_create()` (apps/m3u/tasks.py:2772) with no
  // `transaction.atomic()` wrapping it — an ordinary autocommitting write,
  // durable and visible to any other connection the instant it returns.
  // Only *after* `sync_auto_channels()` returns does the same function set
  // `account.status = SUCCESS` and save it (apps/m3u/tasks.py:3865-3873) — a
  // second, independent autocommitting write, strictly later in the same
  // worker process. So on the happy path this poll is expected to match on
  // its first iteration; it is kept as a bounded poll rather than a single
  // read specifically for the full-suite-load case above, where
  // `waitFor.m3uRefreshComplete()`'s own `status === 'success'` can resolve
  // on a refresh other than the one it just drove.
  const channels = await waitFor.resource<Channel[]>(
    `/api/channels/channels/?name=${encodeURIComponent(prefix)}`,
    (rows) => rows.length === declared.length,
    {
      description:
        `${declared.length} auto-created channels ` +
        `(refresh 2 last_message: ${JSON.stringify(second.last_message)})`,
    }
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

/**
 * The catalogue change is made by re-pointing the account at a SECOND
 * scenario, not by mutating the first.
 *
 * `ScenarioRegistry` has no update operation and the provider's control API
 * has no route for one, so a scenario is immutable once created. And
 * `Stream.stream_hash` is derived from the URL under the shipped default
 * `m3u_hash_key` (`core/migrations/0009_m3u_hash_settings.py`), while every
 * provider URL carries the scenario id — so a second scenario means an
 * entirely new set of Streams.
 *
 * That is enough to exercise both halves of the reconciliation: the first
 * scenario's streams stop being seen, so `sync_auto_channels` deletes their
 * auto-created channels, and the second scenario's are new, so it creates
 * fresh ones. What it cannot exercise is rename-in-place, which needs stream
 * identity held constant across a catalogue change — recorded as a provider
 * gap in COVERAGE.md rather than faked here.
 *
 * Both scenarios' channels carry the same hardcoded `group-title` ("E2E" —
 * see `UPSTREAM_GROUP_NAME` in `m3u-ingest.spec.ts`), so they land in the
 * same `ChannelGroup` row and the same `ChannelGroupM3UAccount` relation.
 * That relation is enabled for auto-sync once, before the first reconcile
 * pass, and is never touched again — the re-point in the middle of this
 * test only changes `server_url`, which carries no signal of its own
 * (`refresh_account_on_save`, `apps/m3u/signals.py:12-19`, only fires on
 * `created`), so the third refresh is driven entirely by
 * `waitFor.m3uRefreshComplete()`'s own default trigger.
 */
test('a changed catalogue deletes the departed channels and creates the new ones', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
}, testInfo) => {
  // Three full fetch-and-parse refreshes against the project's 30s default.
  test.setTimeout(180_000);

  const prefixA = seed.generatedName('mutateA');
  const prefixB = seed.generatedName('mutateB');
  const declaredA = [1, 2, 3].map((id) => ({
    id,
    name: `${prefixA}-ch${id}`,
    tvgId: `${prefixA}-ch${id}.e2e`,
    logo: null,
  }));
  const declaredB = [1, 2].map((id) => ({
    id,
    name: `${prefixB}-ch${id}`,
    tvgId: `${prefixB}-ch${id}.e2e`,
    logo: null,
  }));

  const scenarioA = await upstream.scenario({ channels: declaredA });
  const scenarioB = await upstream.scenario({ channels: declaredB });

  const account = await seed.m3uAccount({
    server_url: upstream.playlistUrl(scenarioA),
    is_active: true,
  });

  // Same guard as the first test in this file, for the same reason: creating
  // the account active queues the create-time `refresh_m3u_groups` task
  // unconditionally, a second writer of the exact fields
  // `waitFor.m3uRefreshComplete()` diffs against its pre-trigger baseline.
  await seed.waitForCreateTimeGroupRefreshToSettle(account.id);

  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const withGroups = await api.json<AccountWithGroups>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'account read-back for its group relation'
  );
  // Picked by stream_count, not `[0]` — see the first test in this file for
  // why: the create-time `refresh_m3u_groups` task always seeds a second,
  // zero-stream relation to "Default Group" ahead of whatever the playlist
  // actually declares, so indexing the array is order-dependent and wrong.
  const relation = withGroups.channel_groups.find(
    (g) => g.stream_count === declaredA.length
  );
  expect(
    relation,
    `no group relation with stream_count === ${declaredA.length} among ${JSON.stringify(withGroups.channel_groups)}`
  ).toBeDefined();

  const window = syncWindowFor(testInfo.workerIndex, 1);
  const row: GroupSettingRow = {
    channel_group: relation!.channel_group,
    enabled: true,
    auto_channel_sync: true,
    auto_sync_channel_start: window.start,
    auto_sync_channel_end: window.end,
    custom_properties: {},
  };
  // Imported from ./helpers rather than inlining the PATCH block a second
  // time in this goal — see helpers.ts's doc comment on `applyGroupSettings`.
  // It also asserts the write actually landed, which a bare `.ok()` check
  // would not: `update_group_settings` silently skips a row whose
  // `channel_group` is falsy and still returns 200.
  await applyGroupSettings(api, account.id, [row]);

  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');
  await waitFor.resource<Channel[]>(
    `/api/channels/channels/?name=${encodeURIComponent(prefixA)}`,
    (rows) => rows.length === declaredA.length,
    { description: `${declaredA.length} auto-created channels from scenario A` }
  );

  // Re-point at scenario B and refresh a third time.
  expect(
    (
      await api.patch(`/api/m3u/accounts/${account.id}/`, {
        server_url: upstream.playlistUrl(scenarioB),
      })
    ).ok()
  ).toBeTruthy();
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  // Neither poll below is racing `sync_auto_channels()`: `_refresh_single_
  // m3u_account_impl` calls it (`apps/m3u/tasks.py:3821`) and only sets the
  // account's terminal `status` afterward (`:3865-3873`), with no
  // `transaction.atomic()` anywhere in between — an ordinary sequence of
  // autocommitting writes, durable the instant each one returns. That is
  // true of the deletion half exactly as much as the creation half: within
  // the same call, scenario A's now-stale streams fall out of
  // `current_streams` (filtered on `last_seen__gte=scan_start_time`), so
  // their channels land in `channels_to_delete` and are removed via
  // `_delete_channels_stopping_streams()` — a plain, synchronous
  // `Channel.objects.filter(...).delete()` (`apps/m3u/tasks.py:2916-2917`),
  // not a task or a signal with its own timing. So by the time
  // `m3uRefreshComplete()` above resolved `'success'`, both the deletes and
  // the creates were already committed. The `waitFor.resource()` calls below
  // are kept anyway, as a defensive/readable idiom consistent with the rest
  // of this goal — not because either result is expected to need more than
  // one poll.
  const survivorsA = await waitFor.resource<Channel[]>(
    `/api/channels/channels/?name=${encodeURIComponent(prefixA)}`,
    (rows) => rows.length === 0,
    { description: 'scenario A’s auto-created channels to be deleted' }
  );
  expect(survivorsA).toHaveLength(0);

  const channelsB = await waitFor.resource<Channel[]>(
    `/api/channels/channels/?name=${encodeURIComponent(prefixB)}`,
    (rows) => rows.length === declaredB.length,
    { description: `${declaredB.length} auto-created channels from scenario B` }
  );
  for (const channel of channelsB) {
    expect(channel.auto_created).toBe(true);
    expect(channel.channel_number!).toBeGreaterThanOrEqual(window.start);
    expect(channel.channel_number!).toBeLessThanOrEqual(window.end);
  }
  expect(new Set(channelsB.map((c) => c.channel_number!)).size).toBe(declaredB.length);
});
