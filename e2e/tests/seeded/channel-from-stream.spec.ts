import { test, expect } from '../../fixtures';
import type { Channel, StreamPage } from '../../fixtures';

test('from-stream creates a channel carrying the stream’s identity', async ({
  upstream,
  seed,
  api,
}) => {
  // One refresh against the `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('fromstream');
  const declared = {
    id: 1,
    name: `${prefix}-ch1`,
    tvgId: `${prefix}-ch1.e2e`,
    logo: `https://example.invalid/${prefix}-ch1.png`,
  };
  const scenario = await upstream.scenario({ channels: [declared] });
  const account = await seed.upstreamM3UAccount(scenario);

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'ingested streams'
  );
  expect(page.count).toBe(1);
  const stream = page.results[0];

  const res = await api.post('/api/channels/channels/from-stream/', {
    stream_id: stream.id,
  });
  expect(res.status()).toBe(201);
  const channel = await api.json<Channel>(res, 'from-stream response');

  expect(channel.name).toBe(declared.name);
  expect(channel.streams).toContain(stream.id);
  expect(channel.tvg_id).toBe(declared.tvgId);
  expect(channel.channel_group_id).toBe(stream.channel_group);
  // `from_stream` does `Logo.objects.get_or_create(url=validate_logo_url(
  // stream.logo_url))` and sets `logo_id`. The provider emits `tvg-logo` for
  // every channel unless the spec passes `logo: null`, so this is the ingest
  // path for a provider-declared logo — proved at row level. The URL is under
  // example.invalid (RFC 2606), so nothing ever fetches it.
  expect(channel.logo_id).not.toBeNull();
});

test('from-stream/bulk creates a channel per stream, asynchronously', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  test.setTimeout(90_000);

  const prefix = seed.generatedName('bulkstream');
  const declared = [1, 2, 3].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: null,
  }));
  const scenario = await upstream.scenario({ channels: declared });
  const account = await seed.upstreamM3UAccount(scenario);

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'ingested streams'
  );
  expect(page.count).toBe(3);

  // 202, not 201: `from_stream_bulk` dispatches
  // `bulk_create_channels_from_streams` to Celery and returns immediately.
  // Nothing exists yet when this resolves.
  const res = await api.post('/api/channels/channels/from-stream/bulk/', {
    stream_ids: page.results.map((s) => s.id),
  });
  expect(res.status()).toBe(202);
  const accepted = await api.json<{ task_id: string; stream_count: number; status: string }>(
    res,
    'from-stream/bulk response'
  );
  expect(accepted.task_id).toBeTruthy();
  expect(accepted.stream_count).toBe(3);
  expect(accepted.status).toBe('started');

  const created = await waitFor.resource<Channel[]>(
    `/api/channels/channels/?name=${encodeURIComponent(prefix)}`,
    (channels) => channels.length === 3,
    { description: `three channels named like ${prefix}`, timeoutMs: 60_000 }
  );

  // `ChannelPagination` returns a bare array unless `page`/`page_size` is in
  // the query string, and `?name=` is an icontains filter — so this list is
  // scoped to this test's own prefix, not a global read.
  const streamIds = new Set(page.results.map((s) => s.id));
  for (const channel of created) {
    expect(channel.streams).toHaveLength(1);
    expect(streamIds.has(channel.streams[0])).toBeTruthy();
  }
  expect(new Set(created.map((c) => c.streams[0])).size).toBe(3);
});
