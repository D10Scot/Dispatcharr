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
  expect(mapped.last_message).toMatch(/^Parsed \d+ programs? for 1 channels?/);

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
