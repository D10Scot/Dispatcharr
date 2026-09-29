import { test, expect, readChannelStatus } from '../../fixtures';
import type { ApiClient, Seeder, UpstreamClient } from '../../fixtures';
import { enterHls, leaveHls, waitForSegments } from '../../fixtures/hls';
import { lockedProfile, stopChannels } from '../streaming/helpers';

/**
 * A channel lingers with no client after its last HLS viewer leaves, and stops
 * when its linger ends (Phase 4a-3, spec D15, parity-matrix row for the linger).
 *
 * ---------------------------------------------------------------------------
 * THE GLOBAL WRITE (ADR 0003's three-part argument, `tests/guards/allowlist.ts`)
 * ---------------------------------------------------------------------------
 * Group `proxy_settings`, key `rewind_linger_seconds` only, set to 20 s for this
 * test's run: a channel snapshots its settings when it starts, so only a channel
 * started during this run lingers 20 s instead of 300 s, and the value is merged
 * into a spread copy of the row's existing `value` so every sibling survives.
 *
 * Why nothing else reads it in a way that matters: `streaming-failover` is
 * `workers: 1`, so no other spec of this project runs during this one, and the
 * other HLS viewer in the project (`stream-limit-429.spec.ts`'s leave-and-zap test)
 * runs before or after, never during. Teardown restores it in an unconditional
 * `afterEach` (a timed-out test skips a body-level `finally` but not fixture
 * teardown): it PATCHes the captured original `value` with `rewind_linger_seconds`
 * set to the value in force before the write, which is the stored one, or 300
 * (`get_proxy_settings`' default) when the row lacked the key, because a save merges
 * over the stored group and a bare verbatim restore of a row that lacked the key would
 * leave the 20 behind. An up-front guard fails loudly, naming the row, if a previous
 * run left it at 20. `CoreSettings._get_group` invalidates the group in Redis on
 * `post_save`, and next-source reads it through that cache, so there is no settling
 * sleep before tuning.
 *
 * `@contract`, on an instance-wide write, for the reason `stream-limit-429.spec.ts`
 * gives: a settings PATCH is ordinary product behaviour used to reach a state a
 * client-facing contract needs.
 */

const CORE_SETTINGS_PATH = '/api/core/settings/';
const PROXY_SETTINGS_KEY = 'proxy_settings'; // core/models.py
const DEFAULT_LINGER_SECONDS = 300; // CoreSettings.get_proxy_settings()'s default
const TEST_LINGER_SECONDS = 20;

interface CoreSettingsRow {
  id: number;
  key: string;
  value: Record<string, unknown>;
}

async function readProxySettingsRow(api: ApiClient): Promise<CoreSettingsRow> {
  const rows = await api.json<CoreSettingsRow[]>(await api.get(CORE_SETTINGS_PATH), 'core settings');
  const row = rows.find((r) => r.key === PROXY_SETTINGS_KEY);
  expect(row, `the "${PROXY_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
  return row!;
}

// Module-scoped, assigned the moment the value resolves, cleared in `afterEach` (the
// `stream-limit-429.spec.ts` shape). Safe as shared state because this project runs
// one worker.
let settingsRowId: number | undefined;
let originalValue: Record<string, unknown> | undefined;
let capturedLinger: number | undefined;
let tunedChannel: string | undefined;

test.afterEach(async ({ api }) => {
  const rowId = settingsRowId;
  const original = originalValue;
  const linger = capturedLinger;
  const channel = tunedChannel;
  settingsRowId = originalValue = capturedLinger = tunedChannel = undefined;
  if (channel !== undefined) await stopChannels(api, channel);
  if (rowId === undefined || original === undefined || linger === undefined) return;

  const res = await api.patch(`${CORE_SETTINGS_PATH}${rowId}/`, {
    value: { ...original, rewind_linger_seconds: linger },
  });
  if (!res.ok()) {
    console.error(
      'hls-linger.spec.ts: FAILED TO RESTORE proxy_settings — the shared container is left with ' +
        `rewind_linger_seconds at ${TEST_LINGER_SECONDS}. row id=${rowId}, status=${res.status()}, ` +
        `intended linger=${linger}.`
    );
    throw new Error(`restoring proxy_settings failed: ${res.status()} ${await res.text()}`);
  }
});

async function hlsChannel(upstream: UpstreamClient, seed: Seeder, api: ApiClient, name: string) {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name, tvgId: `${name.toLowerCase().replace(/\W+/g, '-')}.e2e`, logo: null, asset: 'mpeg2-576i-mp2' }],
    rate: 1,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });
  return channel;
}

test(
  'a channel lingers with no client and stops when its linger ends',
  { tag: '@contract' },
  async ({ upstream, seed, api, request }) => {
    test.setTimeout(240_000);
    const channel = await hlsChannel(upstream, seed, api, seed.generatedName('linger-end'));

    const row = await readProxySettingsRow(api);
    expect(
      row.value.rewind_linger_seconds,
      'a previous run left proxy_settings dirty'
    ).not.toBe(TEST_LINGER_SECONDS);
    settingsRowId = row.id;
    originalValue = row.value;
    capturedLinger = Number(row.value.rewind_linger_seconds ?? DEFAULT_LINGER_SECONDS);
    await api.json(
      await api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, {
        value: { ...row.value, rewind_linger_seconds: TEST_LINGER_SECONDS },
      }),
      'set rewind_linger_seconds'
    );
    tunedChannel = channel.uuid;

    const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
    try {
      await waitForSegments(request, entry.token, 'video', 1, 60_000);
      expect(await leaveHls(request, entry.token)).toBe(204);

      // Running with no client, and saying so.
      const lingering = await readChannelStatus(api, channel.uuid);
      expect(lingering.client_count, 'a lingering channel has no client').toBe(0);
      expect(typeof lingering.lingering_since, 'the status names the linger').toBe('number');

      // 10 s later it is still there, and it is the same linger.
      await new Promise((resolve) => setTimeout(resolve, 10_000));
      const later = await readChannelStatus(api, channel.uuid);
      expect(later.client_count).toBe(0);
      expect(later.lingering_since, 'the same linger, not a new one').toBe(lingering.lingering_since);

      // Within the linger's 20 s and the idle stop after it, the channel is gone.
      await expect
        .poll(async () => (await api.get(`/proxy/ts/status/${channel.uuid}`)).status(), {
          timeout: 60_000,
          intervals: [1_000],
          message: 'the channel stops when its linger ends',
        })
        .toBe(404);
    } finally {
      await leaveHls(request, entry.token);
    }
  }
);
