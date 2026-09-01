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
 *
 * Seven scalar rows and seven relations. The relations are the half a
 * migration is likelier to lose: a foreign key, an ordering, an M2M row, a
 * file on disk. A row that reads back with its own fields intact proves very
 * little if the edge that pointed at it is gone.
 *
 * **Nothing here may re-query the upstream provider.** `instance.restart()`
 * stops the provider container too, and `ScenarioRegistry` is an in-memory
 * `Map` (`e2e-upstream/src/scenario.ts`), so every scenario is forgotten
 * across the lifecycle event. Every assertion below reads Dispatcharr's own
 * database through Dispatcharr's own API. The obvious extension anyone would
 * reach for — re-refresh the account and compare — is the one thing that
 * cannot work here.
 */
import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { Waiter } from '../../fixtures';
import type { ApiClient, Seeder } from '../../fixtures';
import type {
  Channel,
  ChannelProfile,
  EpgData,
  EpgSource,
  Episode,
  Logo,
  M3uAccount,
  Movie,
  Recording,
  Series,
  Stream,
  StreamProfile,
  UpstreamClient,
  User,
  XcUser,
} from '../../fixtures';
import { logoPayload } from '../../fixtures';
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
  /** Ordered. `toEqual`, never `toContain` — see the comment at the create. */
  streams: number[];
  /** The id of the channel whose membership was *disabled*, not enabled. */
  channelProfileMembership: { profileId: number; channelId: number };
  epgProgrammeTitles: string[];
  xcUser: XcUser;
  movie: Movie;
  series: Series;
  episode: Episode;
  recording: Recording;
  logo: Logo;
};

/** One row of `/api/epg/programs/search/`. Only the title is recorded. */
type ProgrammeRow = { id: number; title: string };

type Page<T> = { count: number; results: T[] };

/**
 * An hour out, and nothing in this suite runs for anything close to that.
 *
 * The row is a durable-state relation here and nothing more — a Recording
 * that actually fires is G13's whole subject, and one firing mid-lifecycle
 * would put a `run_recording` task, an ffmpeg process and a file on disk into
 * a test that is trying to measure whether a database row survived.
 */
const RECORDING_STARTS_IN_MS = 60 * 60 * 1000;

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
  seed: Seeder,
  upstream: UpstreamClient
): Promise<DurableState> {
  // `Seeder` holds its own `Waiter` privately, and both call sites build the
  // Seeder from this same `api`, so this is the same Waiter they already have.
  const waitFor = new Waiter(api);
  const prefix = seed.generatedName('durable');
  // One scenario carries everything: two live channels for the Channel →
  // Streams ordering, and the VOD/series catalogue. Named from
  // `generatedName` so every search below is runToken-scoped (rule 6).
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    channels: [
      { id: 1, name: `${prefix}-ch1`, tvgId: `${prefix}-ch1.e2e`, logo: null },
      { id: 2, name: `${prefix}-ch2`, tvgId: `${prefix}-ch2.e2e`, logo: null },
    ],
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    // containerExtension/tmdbId/imdbId are declared required by the fixture
    // types even though the provider's parser defaults them; supplied with
    // the values it would have defaulted to. Same note as
    // vod-catalogue-ingest.spec.ts.
    vod: [
      {
        id: 1,
        name: `${prefix}-movie`,
        year: 2020,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
      },
    ],
    series: [
      {
        id: 1,
        name: `${prefix}-series`,
        categoryId: 1,
        seasons: [
          {
            number: 1,
            episodes: [
              { id: 1, title: `${prefix}-ep`, episodeNum: 1, containerExtension: 'mp4' },
            ],
          },
        ],
      },
    ],
  });

  // Two streams, not one. `Channel.streams` is ordered through
  // `ChannelStream`, and that order decides which upstream is primary and
  // which is the failover target. A single-stream channel cannot distinguish
  // "the link survived" from "the ordering survived", and the ordering is the
  // half a migration is likelier to lose.
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    channel: { channel_number: CHANNEL_NUMBER },
  });
  // The later read-back compares against whatever the create returned, so
  // without this the "explicit channel_number" the design calls for would be
  // unverified: an API that ignored or re-assigned the override would still
  // produce a passing test, comparing a value to itself.
  expect(
    channel.channel_number,
    'the seeded channel did not take the explicit channel_number'
  ).toBe(CHANNEL_NUMBER);

  // After the channel, deliberately. `create_profile_memberships` is a
  // `post_save` receiver on ChannelProfile that bulk-creates a membership for
  // every channel that exists when the profile is created, so a profile made
  // first would not enrol this channel at all.
  const channelProfile = await seed.channelProfile();
  // The durable relation recorded here is a DISABLED membership.
  // `ChannelProfileSerializer.channels` lists the ids of *enabled*
  // memberships, and the receiver above defaults every one of them to
  // enabled — so asserting an enabled membership survived would catch
  // nothing: losing the M2M row and re-running the receiver reproduces it
  // exactly. A membership that comes back enabled is the loss.
  await api.json(
    await api.patch(
      `/api/channels/profiles/${channelProfile.id}/channels/${channel.id}/`,
      { enabled: false }
    ),
    'disable the channel profile membership'
  );

  const streamProfile = await seed.streamProfile();
  const m3uAccount = await seed.m3uAccount();
  const user = await seed.user();

  // `seed.upstreamEpgSource` returns a source with EPGData rows and ZERO
  // ProgramData: `parse_programs_for_source` gates on a Channel pointing at
  // an EPGData row, so the association below is what creates the programmes.
  // It waits the refresh fully out first — `parse_programs_for_tvg_id`
  // re-queues itself with a 15s countdown while `refresh_epg_data`'s lock is
  // still held, so an eager set-epg pays that penalty silently.
  const epgSource = await seed.upstreamEpgSource(scenario);

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const epgData = allEpgData.find(
    (d) => d.tvg_id === `${prefix}-ch1.e2e` && d.epg_source === epgSource.id
  );
  expect(epgData, `no EPGData for ${prefix}-ch1.e2e`).toBeDefined();

  await api.json(
    await api.post(`/api/channels/channels/${channel.id}/set-epg/`, {
      epg_data_id: epgData!.id,
    }),
    'associate the channel with the EPG source'
  );

  // The titles, not a count: a count survives losing every ProgramData row
  // and gaining the same number back from a later parse.
  const programmes = await waitFor.resource<Page<ProgrammeRow>>(
    `/api/epg/programs/search/?channel_id=${channel.id}&page_size=5`,
    (page) => page.count > 0,
    { description: `programmes for channel ${channel.id}`, timeoutMs: 90_000 }
  );
  const epgProgrammeTitles = programmes.results.map((row) => row.title);

  // The XC username IS the Django username — there is no `xc_username`
  // custom property. `UserSerializer` does not return `custom_properties`,
  // which is why `xcPassword` rides on the object seed.xcUser() returns
  // rather than being read back.
  const xcUser = await seed.xcUser();

  const xcAccount = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await waitFor.m3uRefreshComplete(xcAccount.id)).status).toBe('success');

  // The M3U refresh reaching `success` says NOTHING about VOD:
  // `refresh_vod_content` is fired with `.delay()` after it returns. Poll for
  // the rows themselves, on the budget vod-catalogue-ingest.spec.ts uses.
  const movies = await waitFor.resource<Page<Movie>>(
    `/api/vod/movies/?search=${encodeURIComponent(prefix)}`,
    (page) => page.count > 0,
    { description: `the VOD movie named ${prefix}-movie`, timeoutMs: 120_000 }
  );
  const seriesPage = await waitFor.resource<Page<Series>>(
    `/api/vod/series/?search=${encodeURIComponent(prefix)}`,
    (page) => page.count > 0,
    { description: `the series named ${prefix}-series`, timeoutMs: 120_000 }
  );
  const series = seriesPage.results[0];

  // Episodes are NOT part of the refresh: provider-info is a separate,
  // synchronous, on-demand call that creates them. Routed through `api.json`
  // so a 5xx surfaces here rather than two calls later.
  await api.json(
    await api.get(`/api/vod/series/${series.id}/provider-info/`),
    'series provider-info refresh'
  );
  const episodes = await api.json<Page<Episode>>(
    await api.get(`/api/vod/episodes/?search=${encodeURIComponent(prefix)}`),
    'episodes created by the series-info fetch'
  );
  expect(episodes.count, `episode named ${prefix}-ep`).toBe(1);

  const recording = await api.json<Recording>(
    await api.post('/api/channels/recordings/', {
      channel: channel.id,
      // Explicit offsets: `RecordingSerializer.validate` makes naive
      // datetimes aware, and sending them already aware avoids the question.
      start_time: new Date(Date.now() + RECORDING_STARTS_IN_MS).toISOString(),
      end_time: new Date(Date.now() + RECORDING_STARTS_IN_MS + 30 * 60 * 1000).toISOString(),
    }),
    'schedule a recording'
  );

  const logo = await seed.logo();

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
    streams: streams.map((stream: Stream) => stream.id),
    channelProfileMembership: { profileId: channelProfile.id, channelId: channel.id },
    epgProgrammeTitles,
    xcUser,
    movie: movies.results[0],
    series,
    episode: episodes.results[0],
    recording,
    logo,
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

/**
 * Assertions (b) and (c): every row reads back by id, with its recorded
 * values, and every relation still points where it pointed.
 *
 * `request` is the raw context, needed for the two assertions that must not
 * go through `ApiClient`: the XC credential check (which `ApiClient` would
 * mask by refreshing on a 401) and the logo bytes.
 */
export async function assertDurableState(
  api: ApiClient,
  request: APIRequestContext,
  state: DurableState,
  opts: { logoBytes?: boolean } = {}
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

  // --- the seven relations -------------------------------------------------

  // Order-sensitive by construction: `toEqual` on the array, never `toContain`
  // on its members. Losing the ordering swaps primary and failover upstream,
  // which no membership check would notice.
  expect(
    channel.streams,
    'the channel’s streams changed order or membership — ChannelStream’s ' +
      'ordering decides which upstream is primary and which is the failover ' +
      'target'
  ).toEqual(state.streams);

  const membershipProfile = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${state.channelProfileMembership.profileId}/`),
    'read back channel profile membership'
  );
  expect(
    membershipProfile.channels,
    'the disabled membership came back enabled: the ChannelProfileMembership ' +
      'row was lost and `create_profile_memberships` re-created it at its ' +
      'default. The enabled state is the receiver’s doing, not the database’s'
  ).not.toContain(state.channelProfileMembership.channelId);

  const programmes = await api.json<Page<ProgrammeRow>>(
    await api.get(
      `/api/epg/programs/search/?channel_id=${state.channel.id}&page_size=100`
    ),
    'read back EPG programmes'
  );
  const titles = programmes.results.map((row) => row.title);
  for (const title of state.epgProgrammeTitles) {
    expect(
      titles,
      `the EPG programme "${title}" no longer resolves for channel ` +
        `${state.channel.id} — the ProgramData rows or their channel ` +
        'association did not survive'
    ).toContain(title);
  }

  // The raw `request`, not `api`: `ApiClient` refreshes and retries once on a
  // 401, which would mask exactly the failure this is looking for — the same
  // reason `assertAdminTokenStillValid` bypasses it.
  const xcAuth = await request.get(
    `/player_api.php?username=${encodeURIComponent(state.xcUser.username)}` +
      `&password=${encodeURIComponent(state.xcUser.xcPassword)}`
  );
  const xcBody = (await xcAuth.json()) as { user_info?: { auth?: number } };
  expect(
    xcBody.user_info?.auth,
    'the XC user’s credentials no longer authenticate — the User row or its ' +
      'xc_password custom property did not survive'
  ).toBe(1);

  const movie = await api.json<Movie>(
    await api.get(`/api/vod/movies/${state.movie.id}/`),
    'read back VOD movie'
  );
  expect(movie.name).toBe(state.movie.name);

  const series = await api.json<Series>(
    await api.get(`/api/vod/series/${state.series.id}/`),
    'read back series'
  );
  expect(series.name).toBe(state.series.name);

  const episode = await api.json<Episode>(
    await api.get(`/api/vod/episodes/${state.episode.id}/`),
    'read back episode'
  );
  expect(episode.name).toBe(state.episode.name);
  // The foreign key is the relation. Reading the episode row alone would pass
  // with the series link severed or repointed.
  expect(
    episode.series.id,
    'the episode no longer belongs to its series — the row survived but the ' +
      'foreign key did not'
  ).toBe(state.series.id);

  const recording = await api.json<Recording>(
    await api.get(`/api/channels/recordings/${state.recording.id}/`),
    'read back recording'
  );
  expect(
    recording.channel,
    'the scheduled recording no longer points at its channel'
  ).toBe(state.channel.id);

  const logo = await api.json<Logo>(
    await api.get(`/api/channels/logos/${state.logo.id}/`),
    'read back logo row'
  );
  expect(logo.name).toBe(state.logo.name);

  // The only assertion in this file that leaves the database, and the only
  // one the restore spec must switch off. A version-2 backup archive holds
  // `database.dump` and `metadata.json` and no files at all
  // (`create_backup`, apps/backups/services.py) — the docstring's "and data
  // directories" is stale. So across a restore the Logo *row* comes back with
  // the dump while these bytes were never in the archive and were never
  // removed: the assertion would pass for entirely the wrong reason, and would
  // start failing the day backups learn to carry files. Across a restart or an
  // upgrade it is exactly right, because there the question is whether /data
  // survived.
  if (opts.logoBytes ?? true) {
    const served = await request.get(state.logo.cache_url);
    expect(
      (await served.body()).equals(logoPayload(state.logo.name)),
      'the logo bytes did not survive: /data/logos did not persist, or ' +
        'cache_url resolved to a different row'
    ).toBeTruthy();
  }
}
