import type { ApiClient } from './api';
import type {
  Channel,
  ChannelOverrides,
  ChannelProfile,
  ChannelProfileOverrides,
  EpgSource,
  EpgSourceOverrides,
  EpgSourceType,
  M3uAccount,
  M3uAccountOverrides,
  Stream,
  StreamOverrides,
  StreamProfile,
  StreamProfileOverrides,
  UpstreamChannelOptions,
  User,
  UserOverrides,
} from './types';
import type { UpstreamScenario } from './upstream';

/**
 * The password `seed.user()` assigns by default. Exported so `asUser`
 * callers have one source of truth instead of re-declaring the literal —
 * a caller can still override it via `overrides.password`, in which case
 * this constant no longer describes that user.
 */
export const SEEDED_USER_PASSWORD = 'Seeded-Password-42!';

/** Usernames are validated against ^[A-Za-z0-9._@-]+$ — keep names in that set. */
function sanitise(value: string): string {
  return value.replace(/[^A-Za-z0-9._@-]/g, '-');
}

/**
 * Creates entities through the REST API with generated, worker-scoped names.
 *
 * Callers cannot pass a name: the shared instance is never empty, and a
 * hand-picked name is how two parallel workers collide. Assertions must
 * filter on the generated name, never on a global count.
 *
 * Each factory's `overrides` parameter is typed to the writable fields of
 * that endpoint's serializer *minus* the generated identity field, so a
 * misspelt or read-only key fails `npm run typecheck` instead of being
 * silently dropped by DRF (which ignores unknown keys on write). `./types.ts`
 * carries the derivation and the limits of what that compile-time check can
 * promise; the runtime rule below is what actually holds.
 */
export class Seeder {
  private counter = 0;
  private runToken = Math.random().toString(36).slice(2, 8).padEnd(6, '0');

  constructor(
    private api: ApiClient,
    private workerIndex: number,
    private testId: string
  ) {}

  /**
   * testId and workerIndex are both stable across separate invocations of
   * the same spec, so without runToken a second `npm run test:seeded`
   * against the same (non-reset) container would regenerate the exact same
   * names as the first and collide with its own previous run's rows on any
   * unique constraint. runToken is generated once per Seeder instance (one
   * per test) so every name from one test still shares it, keeping that
   * test's data visually grouped, while a re-run gets a fresh one.
   */
  generatedName(entity: string): string {
    return sanitise(
      `e2e-w${this.workerIndex}-${this.runToken}-${this.testId}-${entity}-${this.counter++}`
    );
  }

  private async create<T>(url: string, entity: string, body: object): Promise<T> {
    const res = await this.api.post(url, body);
    return this.api.json<T>(res, `seed.${entity}`);
  }

  // Every factory below spreads its generated identity field **after**
  // `...overrides`. That ordering is the enforcement: the override types omit
  // the identity field, but no type can stop a body that arrived from
  // JSON.parse, from a widened variable, or through a cast. Do not reorder.

  channel(overrides: ChannelOverrides = {}): Promise<Channel> {
    const body: ChannelOverrides & { name: string } = {
      ...overrides,
      name: this.generatedName('channel'),
    };
    return this.create<Channel>('/api/channels/channels/', 'channel', body);
  }

  user(overrides: UserOverrides = {}): Promise<User> {
    const username = this.generatedName('user');
    const body: UserOverrides & { username: string } = {
      password: SEEDED_USER_PASSWORD,
      email: `${username}@example.com`,
      user_level: 1,
      ...overrides,
      username,
    };
    return this.create<User>('/api/accounts/users/', 'user', body);
  }

  /**
   * `ChannelProfileSerializer` exposes one writable field, `name`, and this
   * factory generates it — so {@link ChannelProfileOverrides} is empty and
   * `overrides` has nothing to contribute. It is still spread, and still a
   * parameter, so that the six factories keep one shape and a future writable
   * field needs no restructuring here.
   */
  channelProfile(overrides: ChannelProfileOverrides = {}): Promise<ChannelProfile> {
    const body: { name: string } = {
      ...overrides,
      name: this.generatedName('channelProfile'),
    };
    return this.create<ChannelProfile>(
      '/api/channels/profiles/',
      'channelProfile',
      body
    );
  }

  streamProfile(overrides: StreamProfileOverrides = {}): Promise<StreamProfile> {
    const body: StreamProfileOverrides & { name: string } = {
      command: 'ffmpeg',
      parameters: '-i {streamUrl} -c copy -f mpegts pipe:1',
      is_active: true,
      ...overrides,
      name: this.generatedName('streamProfile'),
    };
    return this.create<StreamProfile>(
      '/api/core/streamprofiles/',
      'streamProfile',
      body
    );
  }

  stream(overrides: StreamOverrides = {}): Promise<Stream> {
    const body: StreamOverrides & { name: string } = {
      url: 'http://127.0.0.1:9/stream.ts',
      is_custom: true,
      ...overrides,
      name: this.generatedName('stream'),
    };
    return this.create<Stream>('/api/channels/streams/', 'stream', body);
  }

  m3uAccount(overrides: M3uAccountOverrides = {}): Promise<M3uAccount> {
    const body: M3uAccountOverrides & { name: string } = {
      server_url: 'http://127.0.0.1:9/playlist.m3u',
      is_active: false,
      ...overrides,
      name: this.generatedName('m3uAccount'),
    };
    return this.create<M3uAccount>('/api/m3u/accounts/', 'm3uAccount', body);
  }

  /**
   * An Xtream Codes `M3UAccount` pointed at an XC scenario.
   *
   * Not `m3uAccount({ account_type: 'XC' })`, because two things are the
   * inverse of the standard-M3U path and both are easy to get wrong:
   *
   * 1. `server_url` is the scenario's **bare** internal base. No
   *    `credentialQuery`: `normalize_server_url` strips the query before use,
   *    so appending one deletes the credentials.
   * 2. The credentials go on the model's `username`/`password` fields, which
   *    the XC client actually reads — unlike a standard M3U refresh, which
   *    reads neither and needs them embedded in the URL.
   *
   * `is_active: true` is required for the same reason as `m3uAccount`: an
   * inactive account never starts a refresh. Unlike a standard account,
   * creating this one starts **no** background refresh —
   * `refresh_account_on_save` skips XC — so `waitFor.m3uRefreshComplete`'s own
   * trigger is the only one, and there is nothing to race.
   *
   * Throws rather than falling back to `null`/`''` when `scenario.username`
   * or `scenario.password` is missing. `refresh_m3u_account_groups` hard-fails
   * an account missing either with "Missing username or password for
   * Xtream Codes account" — a failure that would point at the *account*, not
   * at the scenario that omitted them, obscuring the actual mistake. Create
   * the scenario with `{ xc: true, username, password }`; the provider itself
   * already requires both together at that door.
   */
  xcAccount(
    scenario: UpstreamScenario,
    overrides: M3uAccountOverrides = {}
  ): Promise<M3uAccount> {
    if (!scenario.username || !scenario.password) {
      throw new Error(
        `seed.xcAccount: scenario ${scenario.id} is missing ` +
          `${!scenario.username ? 'a username' : 'a password'} — create it with ` +
          `upstream.scenario({ xc: true, username, password }) before seeding an XC account.`
      );
    }
    return this.m3uAccount({
      account_type: 'XC',
      username: scenario.username,
      password: scenario.password,
      is_active: true,
      ...overrides,
      server_url: scenario.internal,
    });
  }

  epgSource(overrides: EpgSourceOverrides = {}): Promise<EpgSource> {
    const body: EpgSourceOverrides & {
      name: string;
      source_type: EpgSourceType;
    } = {
      source_type: 'xmltv',
      url: 'http://127.0.0.1:9/xmltv.xml',
      is_active: false,
      ...overrides,
      name: this.generatedName('epgSource'),
    };
    return this.create<EpgSource>('/api/epg/sources/', 'epgSource', body);
  }

  /**
   * The five-step wiring every streaming test needs, once: one Stream per
   * provider channel id, then a Channel pointing at them in that order.
   *
   * Streams are created serially rather than with Promise.all. The order of
   * `channel.streams` decides which upstream is primary and which is the
   * failover target, and a concurrent create gives the API no reason to
   * preserve it.
   */
  async upstreamChannel(
    scenario: UpstreamScenario,
    opts: UpstreamChannelOptions
  ): Promise<{ channel: Channel; streams: Stream[] }> {
    const streams: Stream[] = [];
    for (const channelId of opts.channelIds) {
      streams.push(await this.stream({ url: this.upstreamStreamUrl(scenario, channelId) }));
    }

    const channel = await this.channel({
      ...opts.channel,
      streams: streams.map((s) => s.id),
      stream_profile_id: opts.streamProfileId ?? null,
    });

    return { channel, streams };
  }

  // Mirrors UpstreamClient.streamUrl() in upstream.ts exactly. Duplicated
  // rather than imported: importing UpstreamClient here would create a
  // fixture cycle (upstream.ts's fixture wiring would need seed.ts and
  // vice versa). If the provider's URL shape changes, change both.
  private upstreamStreamUrl(scenario: UpstreamScenario, channelId: number): string {
    return `${scenario.internal}/stream/${channelId}.ts${scenario.credentialQuery}`;
  }
}
