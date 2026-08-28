/**
 * The state both lifecycle specs create before their lifecycle event, and
 * assert afterwards.
 *
 * Postgres-backed rows only. Redis is excluded by construction rather than by
 * preference: AIO configures no persistence and `scripts/wait_for_redis.py`
 * calls `flushdb()` on every boot, so a Redis-backed persistence assertion
 * would be asserting a falsehood (spec D11).
 *
 * Every assertion is by id against a value recorded at creation. No counts, no
 * unfiltered lists — the roadmap's rule 4, and here it is also the only shape
 * that works: a re-run against a container that was not reset carries rows
 * from previous runs.
 */
import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import type { ApiClient, Seeder } from '../../fixtures';
import type {
  Channel,
  ChannelProfile,
  EpgSource,
  M3uAccount,
  StreamProfile,
  User,
} from '../../fixtures';
import { listRows } from '../../setup/http';
import { whoAmI } from '../../setup/login';
import { ADMIN } from '../../setup/credentials';

/**
 * Unmistakable, and nothing else in the suite uses it. The default is 100
 * (`CoreSettings.get_system_settings`), so a value read back as 100 after the
 * lifecycle event means the blob was lost and the defaults are being merged
 * back in — which is the failure this assertion exists to see.
 */
export const MAX_SYSTEM_EVENTS = 7317;

/** Nothing else exists on a fresh instance, so any number is free. */
const CHANNEL_NUMBER = 4242;

const SYSTEM_SETTINGS_KEY = 'system_settings';

type CoreSettingRow = {
  id: number;
  key: string;
  name: string;
  value: Record<string, unknown>;
};

export type DurableState = {
  channel: Channel;
  channelProfile: ChannelProfile;
  streamProfile: StreamProfile;
  m3uAccount: M3uAccount;
  epgSource: EpgSource;
  user: User;
  systemSettingsId: number;
};

async function systemSettingsRow(api: ApiClient): Promise<CoreSettingRow> {
  const res = await api.get('/api/core/settings/');
  const rows = listRows<CoreSettingRow>(
    await api.json(res, 'list core settings')
  );
  const row = rows.find((candidate) => candidate.key === SYSTEM_SETTINGS_KEY);
  expect(
    row,
    `no CoreSettings row with key "${SYSTEM_SETTINGS_KEY}". ` +
      'core/migrations/0020 creates it with update_or_create, so its absence ' +
      'is a real migration failure, not a fixture problem. Keys present: ' +
      rows.map((candidate) => candidate.key).join(', ')
  ).toBeDefined();
  return row!;
}

/**
 * Create the seven durable rows and return what a later assertion needs.
 *
 * Serial by construction — the lifecycle projects run one worker with
 * `fullyParallel: false` — which is what makes creating an M3U account and an
 * EPG source safe on a container `bootstrap` has never pre-warmed. Two
 * concurrent creates would both insert an `IntervalSchedule` row for the same
 * interval and brick the instance permanently (D10Scot/Dispatcharr#7).
 */
export async function seedDurableState(
  api: ApiClient,
  seed: Seeder
): Promise<DurableState> {
  const channel = await seed.channel({ channel_number: CHANNEL_NUMBER });
  const channelProfile = await seed.channelProfile();
  const streamProfile = await seed.streamProfile();
  const m3uAccount = await seed.m3uAccount();
  const epgSource = await seed.epgSource();
  const user = await seed.user();

  // Read-modify-write. `value` is the whole group blob, so spreading the
  // current one is not defensive style — a bare `{ max_system_events }`
  // silently drops time_zone, preferred_region, auto_import_mapped_files,
  // enable_ip_lookup and catchup_enabled.
  const row = await systemSettingsRow(api);
  const patched = await api.patch(`/api/core/settings/${row.id}/`, {
    value: { ...row.value, max_system_events: MAX_SYSTEM_EVENTS },
  });
  const written = await api.json<CoreSettingRow>(
    patched,
    'patch system_settings'
  );
  expect(
    written.value.max_system_events,
    'the PATCH response did not carry the new value back'
  ).toBe(MAX_SYSTEM_EVENTS);

  return {
    channel,
    channelProfile,
    streamProfile,
    m3uAccount,
    epgSource,
    user,
    systemSettingsId: row.id,
  };
}

/**
 * Assertion (a): a token minted *before* the lifecycle event still works.
 *
 * The cheapest specific proof that `/data` persisted. `DJANGO_SECRET_KEY` is
 * generated once into `/data/jwt` and reused on every subsequent boot
 * (`docker/entrypoint.sh`, `SECRET_FILE`); a regenerated key invalidates every
 * token in existence, so this fails loudly on a lost volume rather than
 * quietly re-authenticating.
 *
 * Deliberately not through `ApiClient`: it refreshes and retries once on a
 * 401, which would mask exactly this.
 */
export async function assertAdminTokenStillValid(
  request: APIRequestContext,
  access: string
): Promise<void> {
  const identity = await whoAmI(request, access);
  expect(
    identity?.username,
    'the access token minted before the lifecycle event no longer ' +
      'authenticates — /data/jwt did not survive, so DJANGO_SECRET_KEY was ' +
      'regenerated and every token in existence is now invalid'
  ).toBe(ADMIN.username);
}

/** Assertions (b) and (c): every row reads back by id, with its recorded values. */
export async function assertDurableState(
  api: ApiClient,
  state: DurableState
): Promise<void> {
  const channel = await api.json<Channel>(
    await api.get(`/api/channels/channels/${state.channel.id}/`),
    'read back channel'
  );
  expect(channel.name).toBe(state.channel.name);
  expect(channel.channel_number).toBe(state.channel.channel_number);
  expect(channel.uuid).toBe(state.channel.uuid);

  const channelProfile = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${state.channelProfile.id}/`),
    'read back channel profile'
  );
  expect(channelProfile.name).toBe(state.channelProfile.name);

  const streamProfile = await api.json<StreamProfile>(
    await api.get(`/api/core/streamprofiles/${state.streamProfile.id}/`),
    'read back stream profile'
  );
  expect(streamProfile.name).toBe(state.streamProfile.name);
  expect(streamProfile.parameters).toBe(state.streamProfile.parameters);
  expect(streamProfile.is_active).toBe(state.streamProfile.is_active);
  expect(streamProfile.locked).toBe(state.streamProfile.locked);

  const m3uAccount = await api.json<M3uAccount>(
    await api.get(`/api/m3u/accounts/${state.m3uAccount.id}/`),
    'read back M3U account'
  );
  expect(m3uAccount.name).toBe(state.m3uAccount.name);
  expect(m3uAccount.server_url).toBe(state.m3uAccount.server_url);
  expect(m3uAccount.is_active).toBe(state.m3uAccount.is_active);

  const epgSource = await api.json<EpgSource>(
    await api.get(`/api/epg/sources/${state.epgSource.id}/`),
    'read back EPG source'
  );
  expect(epgSource.name).toBe(state.epgSource.name);
  expect(epgSource.url).toBe(state.epgSource.url);
  expect(epgSource.is_active).toBe(state.epgSource.is_active);

  const user = await api.json<User>(
    await api.get(`/api/accounts/users/${state.user.id}/`),
    'read back user'
  );
  expect(user.username).toBe(state.user.username);
  expect(user.user_level).toBe(state.user.user_level);

  // (c) — read through the API, never through `get_system_settings`, which
  // merges defaults on read and would report 7317's absence as the default 100
  // only if the blob were *missing a key*; a wholly lost row would come back
  // looking healthy.
  const settings = await api.json<CoreSettingRow>(
    await api.get(`/api/core/settings/${state.systemSettingsId}/`),
    'read back system_settings'
  );
  expect(
    settings.value.max_system_events,
    'max_system_events read back as the default — the settings blob did not ' +
      'survive the lifecycle event'
  ).toBe(MAX_SYSTEM_EVENTS);
}
