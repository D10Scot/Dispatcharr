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
