import { test, expect } from '../../fixtures';
import type { EpgData, ProgramSearchPage } from '../../fixtures';

test('an EPG refresh creates EPGData rows and no programmes until a channel is mapped', async ({
  upstream,
  seed,
  api,
}) => {
  // A full XMLTV fetch-and-parse against the `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('epg');
  const declared = [1, 2].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: null,
  }));
  const scenario = await upstream.scenario({ channels: declared });

  const source = await seed.upstreamEpgSource(scenario);

  expect(source.updated_at).not.toBeNull();
  expect(source.epg_data_count).toBeGreaterThanOrEqual(2);
  // `parse_programs_for_source` returns early, creating zero ProgramData rows,
  // when `epg_ids_mapped_to_channels` is empty — which it always is for a
  // source nothing points at yet. This message is that early return, and it is
  // the product behaviour this row exists to pin.
  expect(source.last_message).toContain('No channels mapped to this EPG source');

  // `/api/epg/epgdata/` has no filterset and no pagination: a bare array of
  // every row in the instance. Filter client-side; never assert its length.
  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  for (const channel of declared) {
    const row = allEpgData.find((d) => d.tvg_id === channel.tvgId);
    expect(row, `no EPGData for ${channel.tvgId}`).toBeDefined();
    expect(row!.epg_source).toBe(source.id);
    expect(row!.name).toBe(channel.name);

    const programmes = await api.json<ProgramSearchPage>(
      await api.get(
        `/api/epg/programs/search/?tvg_id=${encodeURIComponent(channel.tvgId)}&page_size=1`
      ),
      `programmes for the unmapped ${channel.tvgId}`
    );
    expect(programmes.count).toBe(0);
  }
});

test('a refresh with a mapped channel returns a baseline that a later wait cannot resolve on instantly', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // Two full XMLTV fetch-and-parses (unmapped, then mapped) against the
  // `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('epgmapped');
  const declared = [{ id: 1, name: `${prefix}-ch1`, tvgId: `${prefix}-ch1.e2e`, logo: null }];
  const scenario = await upstream.scenario({ channels: declared });

  const unmapped = await seed.upstreamEpgSource(scenario);

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const epgDataRow = allEpgData.find((d) => d.tvg_id === declared[0].tvgId);
  expect(epgDataRow, `no EPGData for ${declared[0].tvgId}`).toBeDefined();

  const channel = await seed.channel({ epg_data_id: epgDataRow!.id });

  // Now that a channel is mapped, re-refreshing takes the double-write path:
  // `parse_programs_for_source` (apps/epg/tasks.py:2377-2378) writes
  // `updated_at` the moment programmes are swapped in, then
  // `_refresh_epg_data_impl`'s own final `.update()` (:523) writes it again
  // a few ms later. `unmapped` is a settled baseline (from the fix below),
  // so this must wait for the *real* second refresh, not resolve on
  // whichever of the two writes it happens to observe first.
  const mapped = await waitFor.epgRefreshComplete(unmapped.id, { baseline: unmapped });

  expect(mapped.updated_at).not.toBe(unmapped.updated_at);
  // `[\d,]+`, not `\d+`: the product formats the count with a thousands
  // separator once it reaches 1000 (`apps/epg/tasks.py:2373`).
  expect(mapped.last_message).toMatch(/^Parsed [\d,]+ programs? for 1 channels?/);

  const programmes = await api.json<ProgramSearchPage>(
    await api.get(`/api/epg/programs/search/?channel_id=${channel.id}&page_size=1`),
    `programmes for the now-mapped ${declared[0].tvgId}`
  );
  expect(programmes.count).toBeGreaterThan(0);

  // The fix under test: `mapped` must be a *settled* baseline. Reusing it
  // immediately, with no new trigger, must NOT resolve — if it did, that
  // would mean `mapped.updated_at` was the intermediate `:2377-2378` write
  // and the pending `:523` write just satisfied the diff check on its own,
  // exactly the stale-baseline hazard this fix closes. A short timeout is
  // enough: nothing is going to write `updated_at` again on its own.
  await expect(
    waitFor.epgRefreshComplete(unmapped.id, {
      baseline: mapped,
      trigger: async () => {},
      timeoutMs: 3_000,
      intervalMs: 250,
    })
  ).rejects.toThrow(/timed out/);
});

test('set-epg maps a channel and its programmes follow', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // A refresh, then an asynchronous per-channel programme parse.
  test.setTimeout(120_000);

  const prefix = seed.generatedName('setepg');
  const declared = {
    id: 1,
    name: `${prefix}-ch1`,
    tvgId: `${prefix}-ch1.e2e`,
    logo: null,
  };
  const scenario = await upstream.scenario({ channels: [declared] });

  // Wait the refresh fully out before associating: `parse_programs_for_tvg_id`
  // re-queues itself with a 15s countdown while `refresh_epg_data`'s lock is
  // still held, so an eager set-epg pays that penalty silently.
  const source = await seed.upstreamEpgSource(scenario);

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const epgData = allEpgData.find(
    (d) => d.tvg_id === declared.tvgId && d.epg_source === source.id
  );
  expect(epgData, `no EPGData for ${declared.tvgId}`).toBeDefined();

  const channel = await seed.channel();
  const associated = await api.post(`/api/channels/channels/${channel.id}/set-epg/`, {
    epg_data_id: epgData!.id,
  });
  expect(associated.status()).toBe(200);
  const body = await api.json<{ task_status: string }>(associated, 'set-epg response');
  expect(body.task_status).toBe('EPG refresh queued');

  // `parse_programs_for_tvg_id` runs asynchronously off the `refresh_epg_programs`
  // post_save receiver, and touches no status field — so the only signal is the
  // rows themselves.
  const programmes = await waitFor.resource<ProgramSearchPage>(
    `/api/epg/programs/search/?channel_id=${channel.id}&page_size=5`,
    (page) => page.count > 0,
    { description: `programmes for channel ${channel.id}`, timeoutMs: 90_000 }
  );

  // The provider titles every programme `${name} — slot ${n}` (renderXmltv),
  // and the name is worker- and test-scoped, so this cannot alias another
  // worker's guide data.
  expect(programmes.results[0].title.startsWith(declared.name)).toBeTruthy();
  expect(programmes.results[0].tvg_id).toBe(declared.tvgId);
  expect(programmes.results[0].channels.map((c) => c.id)).toContain(channel.id);
});

test('batch-set-epg maps several channels in one call', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(120_000);

  const prefix = seed.generatedName('batchepg');
  const declared = [1, 2].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: null,
  }));
  const scenario = await upstream.scenario({ channels: declared });
  const source = await seed.upstreamEpgSource(scenario);

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const associations = [];
  for (const spec of declared) {
    const epgData = allEpgData.find(
      (d) => d.tvg_id === spec.tvgId && d.epg_source === source.id
    );
    expect(epgData, `no EPGData for ${spec.tvgId}`).toBeDefined();
    const channel = await seed.channel();
    associations.push({ channel_id: channel.id, epg_data_id: epgData!.id, spec });
  }

  const res = await api.post('/api/channels/channels/batch-set-epg/', {
    associations: associations.map(({ channel_id, epg_data_id }) => ({
      channel_id,
      epg_data_id,
    })),
  });
  expect(res.status()).toBe(200);
  const body = await api.json<{ success: boolean; channels_updated: number }>(
    res,
    'batch-set-epg response'
  );
  expect(body.success).toBe(true);
  expect(body.channels_updated).toBe(2);

  // `batch_set_epg` uses bulk_update, which bypasses the post_save receiver, so
  // it calls `dispatch_program_refresh_for_epg_ids` itself. This proves that
  // explicit dispatch actually happened.
  for (const { channel_id, spec } of associations) {
    const programmes = await waitFor.resource<ProgramSearchPage>(
      `/api/epg/programs/search/?channel_id=${channel_id}&page_size=5`,
      (page) => page.count > 0,
      { description: `programmes for channel ${channel_id}`, timeoutMs: 90_000 }
    );
    expect(programmes.results[0].title.startsWith(spec.name)).toBeTruthy();
  }
});
