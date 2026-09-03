import { test, expect } from '../../fixtures';
import type { Channel, EpgData, EpgFieldCopyResponse } from '../../fixtures';

/**
 * `apps/channels/api_views.py`'s `set-names-from-epg` and `set-tvg-ids-from-epg`
 * (plus their sibling `set-logos-from-epg`, not covered here) dispatch
 * `set_channels_names_from_epg` / `set_channels_tvg_ids_from_epg`
 * (`apps/channels/tasks.py`) directly. Neither task imports anything from
 * `epg_matching.py` — there is no fuzzy scan, no tvg_id short-circuit, no ML
 * band to avoid here. The precondition these tasks need is an *existing*
 * association, made beforehand by `set-epg` (reusing G3's deterministic path
 * from `epg-ingest.spec.ts` rather than re-proving it) or by `match-epg`
 * (`epg-matching.spec.ts`). Given that association, both tasks just read
 * `channel.epg_data` and copy one field across.
 *
 * A channel that was never associated — `epg_data` is `None` — is silently
 * skipped: `if channel.epg_data and channel.epg_data.name:` (`tasks.py`) is
 * false, so the channel is never appended to `batch_updates`, never counted
 * in `updated_count`, and not counted as an error either. It simply does not
 * appear anywhere in the response. Test 12 exists to make that
 * invisible-by-default behaviour visible.
 */

test('set-names-from-epg copies the EPG name onto an associated channel, and a confirming re-run updates nothing', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  ws,
  waitFor,
}) => {
  // One XMLTV fetch-and-parse plus two field-copy task runs against the
  // `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('fieldcopyname');
  const declared = { id: 1, name: `${prefix}-epgname`, tvgId: `${prefix}-ch1.e2e`, logo: null };
  const scenario = await upstream.scenario({ channels: [declared] });
  const source = await seed.upstreamEpgSource(scenario, { refresh_interval: 0 });

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

  const res = await api.post('/api/channels/channels/set-names-from-epg/', {
    channel_ids: [channel.id],
  });
  expect(res.status()).toBe(200);
  const body = await api.json<EpgFieldCopyResponse>(res, 'set-names-from-epg response');
  expect(body.task_id).toBeTruthy();
  expect(body.channel_count).toBe(1);

  // The REST resource already exposes the field this task writes, so poll
  // it directly rather than reaching for the websocket.
  const updated = await waitFor.resource<Channel>(
    `/api/channels/channels/${channel.id}/`,
    (c) => c.name === epgData!.name,
    { description: `channel ${channel.id} renamed to ${epgData!.name}` }
  );
  expect(updated.name).toBe(epgData!.name);

  // Re-run: the channel's name now already equals the EPGData name, so
  // `set_channels_names_from_epg`'s `if channel.name != channel.epg_data.name`
  // guard never fires and `updated_count` stays 0. A read-back that still
  // matches is consistent with either a no-op or a second identical write,
  // so proving "nothing changed" needs the task's own terminal count, not
  // another poll of the resource — correlated on its `task_id`, registered
  // immediately after reading it and before any further `await`, so an
  // early-arriving progress message cannot be missed.
  const rerun = await api.post('/api/channels/channels/set-names-from-epg/', {
    channel_ids: [channel.id],
  });
  expect(rerun.status()).toBe(200);
  const rerunBody = await api.json<EpgFieldCopyResponse>(
    rerun,
    'set-names-from-epg re-run response'
  );
  const terminal = await ws.waitForMessage('epg_name_setting_progress', {
    where: (d) => d.task_id === rerunBody.task_id && d.status === 'completed',
  });
  expect(terminal.data?.updated_count).toBe(0);

  const unchanged = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channel.id}/`),
    'channel after re-run'
  );
  expect(unchanged.name).toBe(epgData!.name);
});

test('an unassociated channel is silently skipped by set-names-from-epg', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  ws,
}) => {
  // One XMLTV fetch-and-parse plus one field-copy task run against the
  // `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('fieldcopyskip');
  const declared = { id: 1, name: `${prefix}-epgname`, tvgId: `${prefix}-ch1.e2e`, logo: null };
  const scenario = await upstream.scenario({ channels: [declared] });
  const source = await seed.upstreamEpgSource(scenario, { refresh_interval: 0 });

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const epgData = allEpgData.find(
    (d) => d.tvg_id === declared.tvgId && d.epg_source === source.id
  );
  expect(epgData, `no EPGData for ${declared.tvgId}`).toBeDefined();

  const associatedChannel = await seed.channel();
  const setEpg = await api.post(`/api/channels/channels/${associatedChannel.id}/set-epg/`, {
    epg_data_id: epgData!.id,
  });
  expect(setEpg.status()).toBe(200);

  // Never associated: `epg_data_id` stays the factory default, `null`.
  const unassociatedChannel = await seed.channel();
  expect(unassociatedChannel.epg_data_id).toBeNull();
  const originalName = unassociatedChannel.name;

  const res = await api.post('/api/channels/channels/set-names-from-epg/', {
    channel_ids: [associatedChannel.id, unassociatedChannel.id],
  });
  expect(res.status()).toBe(200);
  const body = await api.json<EpgFieldCopyResponse>(res, 'set-names-from-epg response');
  expect(body.channel_count).toBe(2);

  // Registered immediately after reading `task_id`, before any further
  // `await`, so the listener cannot miss an early-arriving progress message.
  const terminal = await ws.waitForMessage('epg_name_setting_progress', {
    where: (d) => d.task_id === body.task_id && d.status === 'completed',
  });

  // The associated channel is the only one counted — `updated_count: 1`,
  // not 2 — and the skipped channel raises no error either:
  // `error_count: 0`. That silence is exactly what makes the ordering
  // dependency (a channel must go through `set-epg` or `match-epg` before
  // this endpoint can touch it) invisible in the response, and is what this
  // assertion exists to surface.
  expect(terminal.data?.updated_count).toBe(1);
  expect(terminal.data?.error_count).toBe(0);

  const [renamed, untouched] = await Promise.all([
    api.json<Channel>(
      await api.get(`/api/channels/channels/${associatedChannel.id}/`),
      'associated channel after set-names-from-epg'
    ),
    api.json<Channel>(
      await api.get(`/api/channels/channels/${unassociatedChannel.id}/`),
      'unassociated channel after set-names-from-epg'
    ),
  ]);
  expect(renamed.name).toBe(epgData!.name);
  expect(untouched.name).toBe(originalName);
});

test('set-tvg-ids-from-epg copies the tvg_id, correlated on the task id', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  ws,
}) => {
  // One XMLTV fetch-and-parse plus one field-copy task run against the
  // `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('fieldcopytvgid');
  const declared = { id: 1, name: `${prefix}-epgname`, tvgId: `${prefix}-ch1.e2e`, logo: null };
  const scenario = await upstream.scenario({ channels: [declared] });
  const source = await seed.upstreamEpgSource(scenario, { refresh_interval: 0 });

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const epgData = allEpgData.find(
    (d) => d.tvg_id === declared.tvgId && d.epg_source === source.id
  );
  expect(epgData, `no EPGData for ${declared.tvgId}`).toBeDefined();

  // A deliberately wrong tvg_id, so the write this task makes is observable
  // rather than a coincidence.
  const channel = await seed.channel({ tvg_id: `${prefix}-wrong-tvgid` });
  const setEpg = await api.post(`/api/channels/channels/${channel.id}/set-epg/`, {
    epg_data_id: epgData!.id,
  });
  expect(setEpg.status()).toBe(200);

  const res = await api.post('/api/channels/channels/set-tvg-ids-from-epg/', {
    channel_ids: [channel.id],
  });
  expect(res.status()).toBe(200);
  const body = await api.json<EpgFieldCopyResponse>(res, 'set-tvg-ids-from-epg response');
  expect(body.task_id).toBeTruthy();
  expect(body.channel_count).toBe(1);

  // A globally unique Celery id, returned synchronously in the POST response
  // and known before the wait registers — the strongest correlation
  // available anywhere in this product, and exactly the ordering
  // `WsListener.waitForMessage` requires. Registered immediately after
  // reading `task_id`, before any further `await`.
  //
  // Key on `status`, never on the presence of `updated_count`: the failure
  // payload (`tasks.py`'s `except` branch) carries `status: 'failed'`,
  // `progress: 0` and no counts at all — a predicate that instead checked
  // for `updated_count` would let a failure with no counts pass unnoticed.
  const terminal = await ws.waitForMessage('epg_tvg_id_setting_progress', {
    where: (d) => d.task_id === body.task_id && d.status === 'completed',
  });
  expect(terminal.data?.updated_count).toBe(1);

  const updated = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channel.id}/`),
    'channel after set-tvg-ids-from-epg'
  );
  expect(updated.tvg_id).toBe(epgData!.tvg_id);
});
