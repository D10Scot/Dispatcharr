import type { ApiClient } from './api';

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

  private async create(url: string, entity: string, body: object) {
    const res = await this.api.post(url, body);
    return this.api.json(res, `seed.${entity}`);
  }

  channel(overrides: Record<string, unknown> = {}) {
    return this.create('/api/channels/channels/', 'channel', {
      ...overrides,
      name: this.generatedName('channel'),
    });
  }

  user(overrides: Record<string, unknown> = {}) {
    const username = this.generatedName('user');
    return this.create('/api/accounts/users/', 'user', {
      password: 'Seeded-Password-42!',
      email: `${username}@example.com`,
      user_level: 1,
      ...overrides,
      username,
    });
  }

  channelProfile(overrides: Record<string, unknown> = {}) {
    return this.create('/api/channels/profiles/', 'channelProfile', {
      ...overrides,
      name: this.generatedName('channelProfile'),
    });
  }

  streamProfile(overrides: Record<string, unknown> = {}) {
    return this.create('/api/core/streamprofiles/', 'streamProfile', {
      command: 'ffmpeg',
      parameters: '-i {streamUrl} -c copy -f mpegts pipe:1',
      is_active: true,
      ...overrides,
      name: this.generatedName('streamProfile'),
    });
  }

  m3uAccount(overrides: Record<string, unknown> = {}) {
    return this.create('/api/m3u/accounts/', 'm3uAccount', {
      server_url: 'http://127.0.0.1:9/playlist.m3u',
      is_active: false,
      ...overrides,
      name: this.generatedName('m3uAccount'),
    });
  }

  epgSource(overrides: Record<string, unknown> = {}) {
    return this.create('/api/epg/sources/', 'epgSource', {
      source_type: 'xmltv',
      url: 'http://127.0.0.1:9/xmltv.xml',
      is_active: false,
      ...overrides,
      name: this.generatedName('epgSource'),
    });
  }
}
