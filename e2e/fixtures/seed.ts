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
import type { Waiter } from './wait';

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
    private testId: string,
    // Held so the `upstream*` factories below can own the whole create-and-wait
    // dance, the way `upstreamChannel()` owns the wiring dance. `Waiter` takes
    // only `api`, so this introduces no fixture cycle.
    private waitFor: Waiter
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

  /**
   * An `M3UAccount` pointed at a fake-provider scenario, refreshed, with its
   * catalogue proven to have landed. The create-refresh-wait dance, once.
   *
   * `is_active: true` is load-bearing twice over: an inactive account's
   * refresh is a silent no-op that never changes a single field (so
   * `m3uRefreshComplete` would time out saying nothing started), and
   * `StreamViewSet.get_queryset` excludes an inactive account's streams from
   * `/api/channels/streams/` entirely.
   *
   * Not for a test that *wants* the refresh to fail: this asserts `success`.
   * Arm the fault, then drive `seed.m3uAccount()` and
   * `waitFor.m3uRefreshComplete()` yourself.
   *
   * ---------------------------------------------------------------------------
   * The create-time group refresh, and why this waits it out first
   * ---------------------------------------------------------------------------
   * `post_save` on `M3UAccount` (`apps/m3u/signals.py:12-15`) unconditionally
   * queues `refresh_m3u_groups.delay(instance.id)` for every newly-created,
   * non-XC account, independent of `is_active` at signal time — it re-checks
   * `is_active` itself when the task actually runs. Since this factory
   * creates the account active (required above), that task always proceeds:
   * it fetches the same playlist, and — because it's a partial refresh
   * (`full_refresh` defaults to `False`) — settles the account at
   * `status: 'pending_setup'` on success (`apps/m3u/tasks.py:1799-1805`, a
   * `.update()` that bypasses signals but still lands in the row) or
   * `status: 'error'` on any fetch failure (every failure branch inside
   * `fetch_m3u_lines` sets it before returning, `apps/m3u/tasks.py:177+`).
   *
   * That is a *second*, independent write path to the exact two fields
   * (`status`, `last_message`) `waitFor.m3uRefreshComplete()` diffs against
   * its pre-trigger baseline to detect that a refresh has started. Call it
   * straight after creating the account and the two tasks race: if the
   * create-time task's own terminal write (most dangerously `error`, from a
   * transient fetch hiccup unrelated to this test) lands between
   * `m3uRefreshComplete`'s baseline read and the moment its own explicitly
   * *triggered* refresh is observed in flight, that write is indistinguishable
   * from the triggered refresh's outcome — `m3uRefreshComplete` returns it as
   * if it were the answer, and this method throws a spurious failure that has
   * nothing to do with the refresh it actually asked for.
   *
   * Closed here by waiting for the create-time task's own terminal
   * disposition — `error` or `pending_setup` — *before* calling
   * `m3uRefreshComplete` at all. Every path through `refresh_m3u_groups`
   * ends the account at one of those two statuses (given the account stays
   * active throughout, which nothing here changes), and it runs exactly once
   * per row (Django's `created` guard on the signal). So once status leaves
   * the row's initial `idle` for either one, that task is done — it never
   * writes `status`/`last_message` again — and the row is quiescent for
   * `m3uRefreshComplete`'s baseline read to land on cleanly.
   *
   * Verified empirically against this worktree's container, outside this
   * method, by scripting the exact sequence `m3uRefreshComplete` performs
   * (baseline GET immediately followed by the trigger POST) against a
   * freshly-created active account with a `not-found` fault armed on its
   * scenario before creation: the create-time task's `status: 'error'` write
   * is real and independently observable — it repeatedly showed up as the
   * *baseline* read itself (proving the two tasks do race the same two
   * fields, exactly as the code above predicts), and once as a transient
   * `fetching` baseline. Across 15 such runs plus 20 fault-free
   * `--repeat-each` runs of the real spec below, the baseline-diff fallback
   * this race threatens was never actually satisfied by the create-time
   * task's write — this fake provider fails fast enough, and Celery in this
   * container picks the create-time task up fast enough, that its `error`
   * write consistently lands *before* the baseline read rather than in the
   * narrow window after it. That makes the race real but, against this
   * provider, hard to force into an actual false failure — which is exactly
   * why it isn't safe to leave unclosed: the window is timing-dependent, not
   * absent. This wait removes it structurally rather than relying on that
   * timing continuing to hold.
   */
  async upstreamM3UAccount(
    scenario: UpstreamScenario,
    overrides: M3uAccountOverrides = {}
  ): Promise<M3uAccount> {
    const account = await this.m3uAccount({
      ...overrides,
      server_url: this.upstreamPlaylistUrl(scenario),
      is_active: true,
    });

    await this.waitFor.condition(
      async () => {
        const res = await this.api.get(`/api/m3u/accounts/${account.id}/`);
        const body = await this.api.json<M3uAccount>(
          res,
          `upstreamM3UAccount: polling account ${account.id} for the create-time group refresh to settle`
        );
        return body.status === 'error' || body.status === 'pending_setup';
      },
      {
        timeoutMs: 20_000,
        intervalMs: 250,
        description:
          `the create-time group refresh of M3U account ${account.id} to ` +
          `settle (status 'error' or 'pending_setup') before triggering the ` +
          `real refresh`,
      }
    );

    const refreshed = await this.waitFor.m3uRefreshComplete(account.id);
    if (refreshed.status !== 'success') {
      throw new Error(
        `seed.upstreamM3UAccount: refresh of account ${account.id} ended in ` +
          `'${refreshed.status}': ${refreshed.last_message}`
      );
    }
    return refreshed;
  }

  // Mirrors UpstreamClient.playlistUrl() in upstream.ts exactly, for the same
  // reason `upstreamStreamUrl` above is: importing UpstreamClient here would
  // create a fixture cycle. If the provider's URL shape changes, change both.
  private upstreamPlaylistUrl(scenario: UpstreamScenario): string {
    return `${scenario.internal}/playlist.m3u${scenario.credentialQuery}`;
  }
}
