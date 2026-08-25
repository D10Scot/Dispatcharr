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
  StreamProfile,
  StreamProfileOverrides,
  User,
  UserOverrides,
} from './types';

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

  m3uAccount(overrides: M3uAccountOverrides = {}): Promise<M3uAccount> {
    const body: M3uAccountOverrides & { name: string } = {
      server_url: 'http://127.0.0.1:9/playlist.m3u',
      is_active: false,
      ...overrides,
      name: this.generatedName('m3uAccount'),
    };
    return this.create<M3uAccount>('/api/m3u/accounts/', 'm3uAccount', body);
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
}
