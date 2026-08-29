import { test, expect } from '../../fixtures';
import type { M3uAccount } from '../../fixtures';

interface StreamPage {
  count: number;
  results: {
    id: number;
    name: string;
    url: string;
    is_catchup: boolean;
    catchup_days: number;
    stream_id: number | null;
  }[];
}

test('Dispatcharr ingests live streams from an Xtream Codes account', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const prefix = seed.generatedName('xc');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null, categoryId: 1 },
      { id: 2, name: `${prefix}-b`, tvgId: `${prefix}-b.e2e`, logo: null, categoryId: 1 },
    ],
  });

  // Arm `no-tv-archive` on channel 2 only, before the refresh, so
  // `get_live_streams` omits `tv_archive`/`tv_archive_duration` for that one
  // channel. This makes the is_catchup/catchup_days assertions below a real
  // mutation check rather than a comparison against Dispatcharr's own
  // defaults: channel 1 and channel 2 differ only in what the provider
  // advertised, so if ingestion stopped reading those fields from the
  // catalogue response, both channels would come out identical and the
  // per-channel assertions below would fail.
  await upstream.fault(scenario, 'no-tv-archive', { channel: 2 });

  const account = await seed.xcAccount(scenario);

  // m3uRefreshComplete owns the trigger. Safe here in a way it is not for a
  // standard account: `refresh_account_on_save` skips XC accounts, so nothing
  // is refreshing in the background to race with.
  const refreshed: M3uAccount = await waitFor.m3uRefreshComplete(account.id);
  expect(refreshed.status).toBe('success');

  await upstream.clearFault(scenario, 'no-tv-archive', { channel: 2 });

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    'streams created by the XC ingest'
  );

  expect(page.results.map((s) => s.name).sort()).toEqual([`${prefix}-a`, `${prefix}-b`]);

  const first = page.results.find((s) => s.name === `${prefix}-a`)!;
  // The playback URL Dispatcharr built for itself, from get_stream_url's
  // shape — proof the XC path was taken and not the M3U one.
  expect(first.url).toContain(`/live/${prefix}-user/${prefix}-pass/1.ts`);
  // Provider stream id retained. The brief specified this as
  // `custom_properties.stream_id` (a string); the product actually stores
  // it on `StreamSerializer`'s own top-level `stream_id` field
  // (apps/channels/models.py:112, an IntegerField, populated from
  // `int(stream["stream_id"])` in apps/m3u/tasks.py:1143) instead. Note this
  // is a *different* field from the one catch-up playback actually reads —
  // `_prepare_catchup_stream_attempt` (apps/timeshift/views.py:1641) reads
  // `custom_properties.stream_id`, which `apps/m3u/tasks.py:1179` does store
  // (the whole raw XC dict is kept there) but which `StreamSerializer` never
  // serializes (`apps/channels/serializers.py:123-147` omits
  // `custom_properties` from `fields` entirely) — so that value is not
  // observable through this API at all. See COVERAGE.md.
  expect(first.stream_id).toBe(1);

  // tv_archive / tv_archive_duration survived the round trip for the
  // unfaulted channel, and were genuinely omitted (not just defaulted) for
  // the faulted one — proof the provider's catalogue response drives these
  // fields rather than a Dispatcharr-side default.
  expect(first.is_catchup).toBe(true);
  expect(first.catchup_days).toBeGreaterThan(0);

  const second = page.results.find((s) => s.name === `${prefix}-b`)!;
  expect(second.is_catchup).toBe(false);
  expect(second.catchup_days).toBe(0);
});
