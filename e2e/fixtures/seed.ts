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

  constructor(
    private api: ApiClient,
    private workerIndex: number,
    private testId: string
  ) {}

  generatedName(entity: string): string {
    return sanitise(
      `e2e-w${this.workerIndex}-${this.testId}-${entity}-${this.counter++}`
    );
  }

  private async create(url: string, entity: string, body: object) {
    const res = await this.api.post(url, body);
    return this.api.json(res, `seed.${entity}`);
  }

  channel(overrides: Record<string, unknown> = {}) {
    return this.create('/api/channels/channels/', 'channel', {
      name: this.generatedName('channel'),
      ...overrides,
    });
  }

  user(overrides: Record<string, unknown> = {}) {
    const username = this.generatedName('user');
    return this.create('/api/accounts/users/', 'user', {
      username,
      password: 'Seeded-Password-42!',
      email: `${username}@example.com`,
      user_level: 1,
      ...overrides,
    });
  }

  channelProfile(overrides: Record<string, unknown> = {}) {
    return this.create('/api/channels/profiles/', 'channelProfile', {
      name: this.generatedName('channelProfile'),
      ...overrides,
    });
  }

  streamProfile(overrides: Record<string, unknown> = {}) {
    return this.create('/api/core/streamprofiles/', 'streamProfile', {
      name: this.generatedName('streamProfile'),
      command: 'ffmpeg',
      parameters: '-i {streamUrl} -c copy -f mpegts pipe:1',
      is_active: true,
      ...overrides,
    });
  }

  m3uAccount(overrides: Record<string, unknown> = {}) {
    return this.create('/api/m3u/accounts/', 'm3uAccount', {
      name: this.generatedName('m3uAccount'),
      server_url: 'http://127.0.0.1:9/playlist.m3u',
      is_active: false,
      ...overrides,
    });
  }

  epgSource(overrides: Record<string, unknown> = {}) {
    return this.create('/api/epg/sources/', 'epgSource', {
      name: this.generatedName('epgSource'),
      source_type: 'xmltv',
      url: 'http://127.0.0.1:9/xmltv.xml',
      is_active: false,
      ...overrides,
    });
  }
}
