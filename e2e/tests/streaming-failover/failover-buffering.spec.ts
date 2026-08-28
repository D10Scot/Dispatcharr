import { test, expect, readChannelStatus } from '../../fixtures';
import type { ApiClient } from '../../fixtures';

/**
 * Settings path for the buffering detector's thresholds — read from
 * `core/api_urls.py` and `core/models.py`, not guessed:
 *
 *   `core/api_urls.py` registers `CoreSettingsViewSet` (basename
 *   `coresettings`) on the router at `settings/`, so the collection is
 *   `GET /api/core/settings/`. No `DEFAULT_PAGINATION_CLASS` is configured,
 *   so this returns a plain array of every settings row, not `{ results }`.
 *
 *   Each row is `{ id, key, name, value }` (`CoreSettingsSerializer`,
 *   `fields = "__all__"`). The row this test wants has
 *   `key === "proxy_settings"` (`PROXY_SETTINGS_KEY`, `core/models.py`).
 *   There is no lookup-by-key route — the viewset is addressed by `id`, so
 *   this test reads the row first to get it, then writes
 *   `PATCH /api/core/settings/<id>/`.
 *
 *   `value` is the *whole* settings-group JSON blob: `buffering_speed`,
 *   `buffering_timeout`, `redis_chunk_ttl`, `channel_shutdown_delay`,
 *   `channel_init_grace_period`, `channel_client_wait_period`,
 *   `new_client_behind_seconds` (`CoreSettings.get_proxy_settings` defaults,
 *   `core/models.py`). PATCHing a partial object drops the siblings, so this
 *   test does a read-modify-write and restores the exact original value
 *   afterwards — `proxy_settings` is a global row, and leaving it mutated
 *   would change behaviour for every test that runs after this one.
 *
 *   `buffering_speed` defaults to `1.0`, `buffering_timeout` to `15`
 *   (`apps/proxy/config.py`, `get_buffering_speed` / `get_buffering_timeout`).
 *   `apps/proxy/config.py`'s `BaseConfig` additionally caches this group
 *   per-process for `_proxy_settings_cache_ttl = 10` seconds; saving through
 *   the API clears the cache only in the uWSGI worker that handled the
 *   PATCH; the other three keep a stale copy for up to 10s more. And
 *   `StreamManager.__init__` snapshots thresholds once, at channel start,
 *   and never re-reads them for a running channel. So this test waits out
 *   the cache window *before* starting the channel, not merely before
 *   arming the fault.
 */

const CORE_SETTINGS_PATH = '/api/core/settings/';
const PROXY_SETTINGS_KEY = 'proxy_settings';

interface CoreSettingsRow {
  id: number;
  key: string;
  value: Record<string, unknown>;
}

async function readProxySettingsRow(api: ApiClient): Promise<CoreSettingsRow> {
  const rows = await api.json<CoreSettingsRow[]>(
    await api.get(CORE_SETTINGS_PATH),
    'core settings'
  );
  const row = rows.find((r) => r.key === PROXY_SETTINGS_KEY);
  expect(row, `the "${PROXY_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
  return row!;
}

function writeProxySettingsValue(
  api: ApiClient,
  row: CoreSettingsRow,
  value: Record<string, unknown>
) {
  return api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, { value });
}

// The trickle rate armed below, and the asset's own nominal pacing rate
// (`e2e-upstream/README.md`: "~2 Mbit — around 180 KB/s for this asset,
// measured", rate 1 = real-time). Used only to compute the expected
// throughput for THE DISCRIMINATOR below.
const TRICKLE_RATE = 0.3;
const ASSET_NOMINAL_KB_PER_SEC = 180;
const EXPECTED_TRICKLE_KB_PER_SEC = TRICKLE_RATE * ASSET_NOMINAL_KB_PER_SEC; // ~54 KB/s

test('a degraded but not dead upstream fails over on the buffering detector', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const settingsRow = await readProxySettingsRow(api);
  const originalValue = settingsRow.value;

  // buffering_speed defaults to 1.0. Raised above 1.0 — the documented lever
  // (CLAUDE.md, D8) — so a 0.3x trickle reads as clearly degraded rather
  // than merely at parity with the threshold.
  const BUFFERING_SPEED = 3.0;

  await writeProxySettingsValue(api, settingsRow, {
    ...originalValue,
    buffering_speed: BUFFERING_SPEED,
  });

  try {
    // Outlast the 10s process-local settings cache on all four uWSGI
    // workers before the channel starts — see the header comment.
    await new Promise((resolve) => setTimeout(resolve, 12_000));

    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'G4 Buffering A', tvgId: 'g4-buffering-a.e2e', logo: null },
        { id: 2, name: 'G4 Buffering B', tvgId: 'g4-buffering-b.e2e', logo: null },
      ],
      rate: 20,
    });

    // PRE-ARM. speed= is a cumulative average since ffmpeg starts, so a
    // trickle applied mid-stream needs ~55s to drag the average below
    // threshold and the ~25s dead-air watchdog wins first. Armed before the
    // first connection, the process never has a fast period to average
    // against.
    const armed = await upstream.fault(scenario, 'slow-trickle', {
      channel: 1,
      rate: TRICKLE_RATE,
    });
    expect(armed.appliedTo).toBe(0);

    // ffmpeg profile: the buffering detector parses ffmpeg's stderr, so it
    // is inert for Proxy and Redirect. That is a documented product trap,
    // not a limitation of this test.
    const profile = await seed.streamProfile();
    const { channel, streams } = await seed.upstreamChannel(scenario, {
      channelIds: [1, 2],
      streamProfileId: profile.id,
    });

    await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);

    await expect
      .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
        timeout: 180_000,
        intervals: [2_000],
      })
      .toBe(streams[1].id);

    // THE DISCRIMINATOR. Not a log-timestamp gap: the fake provider's
    // ScenarioLog has exactly four entry kinds (`request`, `open`, `close`,
    // `fault` — `e2e-upstream/src/log.ts`) and none is per-chunk, so a
    // sustained connection logs only one `open` and one `close`. The gap
    // between those two is always ~the connection's whole lifetime, whether
    // bytes flowed the entire time or the connection sat dead-silent before
    // closing — it cannot tell the two apart. What the `close` entry does
    // carry is real: `bytes` and `durationMs` for the connection's full
    // life. Dead air fires only when the provider stops sending; slow-trickle
    // sends continuously at a reduced rate. So if the connection's observed
    // throughput over its whole life is close to the armed trickle rate, no
    // >10s silence window ever existed — the dead-air watchdog cannot have
    // caused this switch (dead-air was never armed on this scenario either).
    // Bracketing around the expected rate, not just a floor, matters: a
    // floor alone would pass a connection that stalled for 15s and then
    // burst back to full speed, which is exactly the kind of silence this
    // check exists to rule out.
    const log = await upstream.log(scenario);
    const closed = log.find((e) => e.kind === 'close' && e.channelId === 1);
    expect(closed, 'the provider should have logged the closed connection').toBeDefined();
    expect(closed!.bytes, 'close entry should carry bytes').toBeDefined();
    expect(closed!.durationMs, 'close entry should carry durationMs').toBeDefined();

    const observedKbPerSec = closed!.bytes! / 1024 / (closed!.durationMs! / 1000);
    expect(
      observedKbPerSec,
      `observed ${observedKbPerSec.toFixed(1)} KB/s against an expected ` +
        `~${EXPECTED_TRICKLE_KB_PER_SEC} KB/s (${TRICKLE_RATE} × ${ASSET_NOMINAL_KB_PER_SEC} KB/s) — ` +
        'too far below suggests a silence the trickle should not have had, ' +
        'so the test no longer proves the buffering detector fired'
    ).toBeGreaterThan(EXPECTED_TRICKLE_KB_PER_SEC * 0.5);
    expect(
      observedKbPerSec,
      `observed ${observedKbPerSec.toFixed(1)} KB/s against an expected ` +
        `~${EXPECTED_TRICKLE_KB_PER_SEC} KB/s — too far above suggests the trickle ` +
        "wasn't actually constraining delivery for (most of) the connection's life"
    ).toBeLessThan(EXPECTED_TRICKLE_KB_PER_SEC * 2);
  } finally {
    // Restore: proxy_settings is global, and leaving buffering_speed raised
    // would alter behaviour for every later test run against this container.
    await writeProxySettingsValue(api, settingsRow, originalValue);
  }
});
