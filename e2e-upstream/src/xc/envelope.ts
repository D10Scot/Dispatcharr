import type { Scenario } from '../scenario.js';

const ONE_YEAR_SECONDS = 365 * 24 * 60 * 60;

/** XC panels emit `YYYY-MM-DD HH:MM:SS` for `time_now`. */
function sqlDateTime(date: Date): string {
  return date.toISOString().replace('T', ' ').slice(0, 19);
}

/**
 * The `player_api.php` handshake body.
 *
 * The key set is not a guess: it is exactly what
 * `core/xtream_codes.Client.get_account_info()` copies into
 * `M3UAccountProfile.custom_properties`. Two entries are load-bearing beyond
 * storage — `user_info.exp_date`, which `M3UAccountProfile.save()` re-parses
 * on every save as a unix timestamp or an ISO string, and
 * `server_info.timezone`, which drives `convert_timestamp_to_provider_tz` in
 * `apps/timeshift/helpers.py`.
 *
 * `user_info.auth` is emitted as 1 but is **never read by the product**:
 * `Client.authenticate()` checks only that `user_info` is truthy. The
 * `xc-auth-envelope` fault exists to make that observable.
 *
 * No top-level `error` key, ever: `_make_request` raises on a dict that has
 * an `error` key and no `user_info`, and a stray one on a success path is an
 * authentication failure with no obvious cause.
 */
export function renderAccountEnvelope(
  scenario: Scenario,
  now: Date,
  host: string
): Record<string, unknown> {
  const nowSeconds = Math.floor(now.getTime() / 1000);
  const [hostname, port = '8080'] = host.split(':');

  return {
    user_info: {
      username: scenario.username ?? '',
      password: scenario.password ?? '',
      message: 'dispatcharr-e2e-upstream',
      auth: 1,
      status: 'Active',
      exp_date: String(nowSeconds + ONE_YEAR_SECONDS),
      is_trial: '0',
      active_cons: '0',
      created_at: String(nowSeconds - ONE_YEAR_SECONDS),
      // Mirrors the scenario's real limit so a G9 test can make
      // M3UAccount.max_streams and the provider's declared limit disagree on
      // purpose. `null` (unlimited) has no XC spelling; 1 is the honest
      // default for a scenario that never declared one.
      max_connections: String(scenario.maxConnections ?? 1),
      allowed_output_formats: ['ts', 'm3u8'],
      ...(scenario.account.userInfo ?? {}),
    },
    server_info: {
      url: hostname,
      port,
      https_port: '443',
      server_protocol: 'http',
      rtmp_port: '0',
      // "UTC" and a falsy value are the only two values
      // convert_timestamp_to_provider_tz treats as "no conversion".
      timezone: 'UTC',
      timestamp_now: nowSeconds,
      time_now: sqlDateTime(now),
      ...(scenario.account.serverInfo ?? {}),
    },
  };
}

/**
 * The `xc-auth-envelope` fault's rendering: a 200 whose `user_info` describes
 * a disabled account (`auth: 0`, `status: 'Disabled'`) instead of a 401 —
 * deliberately, since `Client.authenticate()` checks only that `user_info`
 * is truthy, so this is the shape the product actually mistakes for a
 * successful login. That's the whole point of the fault.
 *
 * Built by rendering the normal envelope — `scenario.account.userInfo`
 * overrides included — and then applying `auth`/`status` on top of the
 * *result*, not by spreading them into the object literal `renderAccountEnvelope`
 * builds. `renderAccountEnvelope` spreads `scenario.account.userInfo` last,
 * so a scenario that itself sets `user_info.auth` would otherwise silently
 * defeat the fault: whichever key was spread most recently would win, and a
 * scenario-level override is spread after any fixed default. Applying the
 * fault's override strictly after the full render — including that spread —
 * makes it win unconditionally, regardless of what the scenario declares. See
 * `test/xc-faults.test.ts`'s precedence test, which arms this fault on a
 * scenario whose `account.userInfo` also sets `auth`/`status`.
 */
export function renderDisabledAccountEnvelope(
  scenario: Scenario,
  now: Date,
  host: string
): Record<string, unknown> {
  const envelope = renderAccountEnvelope(scenario, now, host);
  const userInfo = envelope.user_info as Record<string, unknown>;
  return {
    ...envelope,
    user_info: { ...userInfo, auth: 0, status: 'Disabled' },
  };
}
