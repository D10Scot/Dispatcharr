import { test, expect } from '../../fixtures';
import type { ApiClient } from '../../fixtures';
import {
  catchupRequests,
  catchupTimestamp,
  lockedProfile,
  seedCatchupChannel,
} from '../streaming/helpers';

/**
 * Redirect mode: three entry points, two layouts, and an empty provider log.
 *
 * THIS TEST MUTATES A GLOBAL. Redirect mode is reachable only by pointing
 * `stream_settings.default_stream_profile` at the locked Redirect profile
 * (`CoreSettings.is_default_stream_profile_redirect`, `core/models.py:549-564`);
 * there is no per-channel override. While it is flipped, EVERY channel in
 * the container answers a session-less catch-up or live request with a 302
 * to the provider instead of proxying it. `streaming-failover` runs at
 * `workers: 1` for exactly this class of hazard — see the project's comment
 * in `playwright.config.ts`, which now names two globals.
 *
 * The up-front guard below catches a previous run that died between the
 * write and the `finally`: CI's `retries: 1` would otherwise read the
 * contaminated value as "original" and write it back permanently. BUT NOTE
 * WHAT IT DOES NOT DO: it protects *this* test's next run, not the tests
 * around it. Any streaming test running between an aborted run and the next
 * run of this one would silently see Redirect as the container's default and
 * would have no idea. That residual risk is the price of testing a global,
 * and it is why nothing else in this goal touches one.
 *
 * NO CACHE SLEEP. `failover-buffering.spec.ts` waits 12s after its write
 * because `apps/proxy/config.py`'s `BaseConfig` keeps a 10s PROCESS-LOCAL
 * copy of `proxy_settings` (`config.py:22-24`), so a PATCH clears it only in
 * the worker that handled it. `stream_settings` is cached in Redis with
 * signal-driven invalidation (`core/models.py:344-357`, `:372-384`) and is
 * visible to every worker at once. Do not copy the sleep.
 *
 * And the goal's standing limit: every assertion below is on the URL
 * Dispatcharr HANDED OUT, never on bytes — redirect mode fetches nothing at
 * all, which is half the definition of the mode and the last assertion in
 * this file.
 */
const CORE_SETTINGS_PATH = '/api/core/settings/';
const STREAM_SETTINGS_KEY = 'stream_settings';

interface CoreSettingsRow {
  id: number;
  key: string;
  value: Record<string, unknown>;
}

async function readStreamSettingsRow(api: ApiClient): Promise<CoreSettingsRow> {
  const rows = await api.json<CoreSettingsRow[]>(await api.get(CORE_SETTINGS_PATH), 'core settings');
  const row = rows.find((r) => r.key === STREAM_SETTINGS_KEY);
  expect(row, `the "${STREAM_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
  return row!;
}

test('redirect mode hands the client a provider URL in the layout it arrived in, and fetches nothing', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  const xcUser = await seed.xcUser();
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  const redirect = await lockedProfile(api, 'Redirect');
  const settingsRow = await readStreamSettingsRow(api);
  const originalValue = settingsRow.value;

  // THE GUARD (D10). Compared as strings because the row's JSON has carried
  // both an int and a string id in the wild, and `!==` on mixed types would
  // pass a dirty container straight through.
  expect(
    String(originalValue.default_stream_profile ?? ''),
    'a previous run left stream_settings dirty — the container is already on Redirect'
  ).not.toBe(String(redirect.id));

  await api.patch(`${CORE_SETTINGS_PATH}${settingsRow.id}/`, {
    value: { ...originalValue, default_stream_profile: redirect.id },
  });

  try {
    const token = await api.freshAccessToken();

    // 1. The native route. `client_timeshift_url_layout` returns "path" for
    //    everything that is not `timeshift.php` — `/proxy/catchup/` included
    //    (helpers.py:436-446).
    const native = await request.get(
      `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
      { headers: { Authorization: `Bearer ${token}` }, maxRedirects: 0 }
    );
    // 302, not the 301 a session mint would give (views.py:406-437): the
    // Redirect branch hands off before any session exists.
    expect(native.status()).toBe(302);
    const nativeLocation = native.headers()['location'];
    expect(nativeLocation).toContain(
      `/timeshift/${scenario.username}/${scenario.password}/65/${start}/${providerStreamId}.ts`
    );

    // 2. The root PATH route. Same layout, same shape.
    const rootPath = await request.get(
      `/timeshift/${xcUser.username}/${xcUser.xcPassword}/60/${start}/${channel.id}.ts`,
      { maxRedirects: 0 }
    );
    expect(rootPath.status()).toBe(302);
    expect(rootPath.headers()['location']).toContain(
      `/timeshift/${scenario.username}/${scenario.password}/65/${start}/${providerStreamId}.ts`
    );

    // 3. The root QUERY route — the ONLY request in this goal that produces a
    //    QUERY provider URL. `client_timeshift_url_layout` returns "query"
    //    only when `timeshift.php` is in the request path, and that choice is
    //    consumed only by `_select_catchup_redirect_url` (views.py:413-419).
    //    Proxy mode never sees it, which is why
    //    `catchup-proxy-mode.spec.ts` asserts both root routes produce a PATH
    //    upstream request.
    const rootQuery = await request.get(
      `/streaming/timeshift.php?username=${encodeURIComponent(xcUser.username)}` +
        `&password=${encodeURIComponent(xcUser.xcPassword)}` +
        `&stream=${channel.id}&start=${encodeURIComponent(start)}&duration=60`,
      { maxRedirects: 0 }
    );
    expect(rootQuery.status()).toBe(302);
    const queryLocation = rootQuery.headers()['location'];
    expect(queryLocation).toContain('/streaming/timeshift.php');
    expect(queryLocation).toContain(`username=${scenario.username}`);
    expect(queryLocation).toContain(`password=${scenario.password}`);
    expect(queryLocation).toContain(`stream=${providerStreamId}`);
    expect(queryLocation).toContain('duration=65');
    // `build_timeshift_url_format_a` interpolates `start` RAW
    // (helpers.py:412-421) and this shape has no space, so it appears
    // verbatim in the Location header.
    expect(queryLocation).toContain(`start=${start}`);

    // THE OTHER HALF OF THE DEFINITION (D9). Redirect mode hands the client a
    // URL and fetches NOTHING — the capacity check runs with reserve=False
    // (`_prepare_catchup_stream_attempt`, views.py:1618-1652) and no HTTP
    // request is made at all. Three redirects issued, zero upstream requests.
    expect(
      catchupRequests(await upstream.log(scenario)),
      'redirect mode must make no upstream request of its own'
    ).toHaveLength(0);

    // All three Locations carry `/65/` and the requested start: the right
    // moment was asked for, in the shape the client can use. Nothing here
    // proves Dispatcharr — or the provider — seeks to it.
  } finally {
    // Restore. `stream_settings` is global; leaving it on Redirect would put
    // every later test in this container on 302-handoff instead of proxying.
    await api.patch(`${CORE_SETTINGS_PATH}${settingsRow.id}/`, { value: originalValue });
  }
});
