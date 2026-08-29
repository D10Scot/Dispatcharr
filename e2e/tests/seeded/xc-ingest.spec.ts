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
  // Explicit names, always. VODCategory is globally unique on (name, type) and
  // Movie/Series are matched across every account by (name, year) — so the
  // default catalogue aliases across the four `seeded` workers even harder
  // than the default channel catalogue does.
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

  const account = await seed.xcAccount(scenario);

  // m3uRefreshComplete owns the trigger. Safe here in a way it is not for a
  // standard account: `refresh_account_on_save` skips XC accounts, so nothing
  // is refreshing in the background to race with.
  const refreshed: M3uAccount = await waitFor.m3uRefreshComplete(account.id);
  expect(refreshed.status).toBe('success');

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
  // `int(stream["stream_id"])` in apps/m3u/tasks.py:1143) — never in
  // `custom_properties` at all. Verified against the running stack: the
  // brief's assertion could not pass against real product output.
  expect(first.stream_id).toBe(1);
  // tv_archive / tv_archive_duration survived the round trip.
  expect(first.is_catchup).toBe(true);
  expect(first.catchup_days).toBeGreaterThan(0);
});
