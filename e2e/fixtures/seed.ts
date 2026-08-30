import type { ApiClient } from './api';
import type {
  Channel,
  ChannelGroup,
  ChannelGroupOverrides,
  ChannelOverrides,
  ChannelProfile,
  ChannelProfileOverrides,
  EpgSource,
  EpgSourceOverrides,
  EpgSourceType,
  Logo,
  LogoOverrides,
  M3uAccount,
  M3uAccountOverrides,
  Stream,
  StreamOverrides,
  StreamProfile,
  StreamProfileOverrides,
  UpstreamChannelOptions,
  User,
  UserOverrides,
  XcUser,
} from './types';
import type { UpstreamScenario } from './upstream';
import type { WaitOptions, Waiter } from './wait';

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
    //
    // Required, deliberately, not defaulted: an optional `Waiter` would fail
    // at runtime, inside `upstreamM3UAccount()`, the first time a caller that
    // omitted it reached a wait — instead of at compile time, here. If adding
    // this parameter breaks a `new Seeder(...)` call site elsewhere in the
    // tree, pass the `Waiter` that call site already has rather than making
    // this optional.
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

  /**
   * `ChannelGroupSerializer` exposes one writable field, `name`, and this
   * factory generates it — so {@link ChannelGroupOverrides} is empty, exactly
   * as `channelProfile()`'s is.
   *
   * Reach for this whenever a test asserts on an Xtream *category* or an M3U
   * `group-title`. `seed.channel()` with no `channel_group_id` is
   * auto-assigned a shared "Default Group" by `ChannelSerializer.create`, and
   * four parallel workers all writing into that one group makes any
   * category-level assertion meaningless.
   */
  channelGroup(overrides: ChannelGroupOverrides = {}): Promise<ChannelGroup> {
    const body: { name: string } = {
      ...overrides,
      name: this.generatedName('channelGroup'),
    };
    return this.create<ChannelGroup>(
      '/api/channels/groups/',
      'channelGroup',
      body
    );
  }

  /**
   * A user who can authenticate against the Xtream Codes surface.
   *
   * The password is generated per user and thrown away with the run. That is
   * deliberate and load-bearing, not incidental tidiness: XC credentials
   * travel in query strings across four surfaces, Dispatcharr logs full
   * provider URLs including `?password=` at INFO, and
   * `.github/workflows/e2e-tests.yml`'s failure step prints
   * `docker logs dispatcharr-e2e` straight into the CI log. A throwaway
   * credential makes both of those harmless. **Do not introduce a fixed XC
   * password here.**
   *
   * `xc_password` is spread after the caller's `custom_properties` so a
   * caller cannot substitute one — the same ordering rule the generated
   * identity fields use. Other custom properties (`hide_adult_content`,
   * `epg_days`) pass through untouched.
   *
   * `generatedName` sanitises to `^[A-Za-z0-9._@-]+$`, which is exactly what
   * `SAFE_CREDENTIAL_RE` (`apps/accounts/serializers.py:16`) requires of
   * `xc_password` (`:110-113`) — swap the generator for something that
   * produces other characters and this factory starts failing with a 400
   * from `UserSerializer`, not from here.
   */
  async xcUser(overrides: UserOverrides = {}): Promise<XcUser> {
    const xcPassword = this.generatedName('xc-secret');
    const user = await this.user({
      ...overrides,
      custom_properties: {
        ...(overrides.custom_properties ?? {}),
        xc_password: xcPassword,
      },
    });
    return { ...user, xcPassword };
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
   * `post_save` on `M3UAccount` (`apps/m3u/signals.py:12-20`) unconditionally
   * queues `refresh_m3u_groups.delay(instance.id)` for every newly-created,
   * non-XC account, independent of `is_active` at signal time — it re-checks
   * `is_active` itself when the task actually runs. Since this factory
   * creates the account active (required above), that task always proceeds
   * down `refresh_m3u_groups`'s normal path: it fetches the same playlist,
   * and — because it's a partial refresh (`full_refresh` defaults to
   * `False`) — settles the account at `status: 'pending_setup'` on success
   * (`apps/m3u/tasks.py:1808-1811`, a `.update()` that bypasses signals but
   * still lands in the row) or `status: 'error'` on any fetch failure (every
   * failure branch inside `fetch_m3u_lines` sets it before returning,
   * `apps/m3u/tasks.py:177+`).
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
   * Closed here by waiting, via `waitForCreateTimeGroupRefreshToSettle()`
   * below, for the create-time task's own terminal disposition *before*
   * calling `m3uRefreshComplete` at all — see that method's doc comment for
   * exactly what this does and does not guarantee about `refresh_m3u_groups`
   * always reaching one of those two statuses.
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

    await this.waitForCreateTimeGroupRefreshToSettle(account.id);

    const refreshed = await this.waitFor.m3uRefreshComplete(account.id);
    if (refreshed.status !== 'success') {
      throw new Error(
        `seed.upstreamM3UAccount: refresh of account ${account.id} ended in ` +
          `'${refreshed.status}': ${refreshed.last_message}`
      );
    }
    return refreshed;
  }

  /**
   * Waits for the create-time `refresh_m3u_groups` task (queued
   * unconditionally by `post_save` for every newly-created, active, non-XC
   * `M3UAccount` — see `upstreamM3UAccount()`'s doc comment for the full
   * race this exists to close) to reach its own terminal disposition —
   * `status: 'error'` or `'pending_setup'` — before the caller triggers a
   * real refresh and reads the row as a baseline.
   *
   * ---------------------------------------------------------------------------
   * The exact claim, and its limit
   * ---------------------------------------------------------------------------
   * This does **not** claim `{error, pending_setup}` is the exhaustive set of
   * outcomes `refresh_m3u_groups` (`apps/m3u/tasks.py:1536`) can ever reach —
   * it claims that set is what every path *reachable by this factory*
   * reaches, and that anything else is treated as a hang, not a pass.
   * `refresh_m3u_groups` has three paths that leave the row at a
   * **non-terminal** status forever rather than settling at either one:
   *
   *  1. its own task lock (`"refresh_m3u_account_groups"`) already held by
   *     another execution against the same account id (`:1544-1546`) —
   *     returns immediately, writing nothing;
   *  2. the account is not found, or **inactive at execution time**
   *     (`:1552-1556`, the `M3UAccount.DoesNotExist` branch — the query
   *     filters `is_active=True`) — same, no write;
   *  3. an uncaught exception after `fetch_m3u_lines` succeeds but before
   *     `process_groups`/the final `.update()` runs, in the non-XC branch,
   *     which has no broad `except` around it — the row is left at whatever
   *     `fetch_m3u_lines` set (`fetching`) with nothing left to move it on.
   *
   * None of these three is reachable through `upstreamM3UAccount()`'s normal
   * path (a freshly-created, active account whose lock nothing else holds,
   * fetching a well-formed fake playlist) — but this method makes no attempt
   * to distinguish "genuinely stuck" from "just slow", and doesn't need to:
   * either way it **fails loud**. `waitFor.condition` below throws a timeout
   * naming the account and what it was waiting for, rather than silently
   * returning early against a status that was never terminal — so hitting
   * gap 1, 2 or 3 surfaces as an attributable timeout here, not as a
   * mysterious failure three calls later inside `m3uRefreshComplete`.
   *
   * Gap 2 is exercised directly, deterministically, in
   * `m3u-ingest.spec.ts`'s `waitForCreateTimeGroupRefreshToSettle times out
   * rather than passing silently when the account never settles` test: an
   * account created with `is_active: false` guarantees this exact
   * `DoesNotExist` branch (no fault, no timing race — the create-time task's
   * one-shot `is_active=True` check simply never passes), so the wait can
   * only ever time out, never resolve. That test pins the *contract* this
   * method must keep — resolve on a genuine terminal write, time out loudly
   * otherwise — deterministically. It does not, on its own, prove
   * `upstreamM3UAccount()` still calls this method; I looked for a
   * comparably deterministic way to pin that specific call site and
   * concluded there isn't one available at this layer — see the fix report
   * for the reasoning.
   */
  // Not `private`: `m3u-ingest.spec.ts`'s regression test below calls this
  // directly to pin its timeout contract deterministically — see the doc
  // comment above for why that couldn't be done through `upstreamM3UAccount`
  // itself. Primarily an internal helper; `upstreamM3UAccount` is still the
  // one path a normal test should reach for.
  async waitForCreateTimeGroupRefreshToSettle(
    accountId: number,
    options: WaitOptions = {}
  ): Promise<void> {
    await this.waitFor.condition(
      async () => {
        const res = await this.api.get(`/api/m3u/accounts/${accountId}/`);
        const body = await this.api.json<M3uAccount>(
          res,
          `waitForCreateTimeGroupRefreshToSettle: polling account ${accountId}`
        );
        return body.status === 'error' || body.status === 'pending_setup';
      },
      {
        timeoutMs: 20_000,
        intervalMs: 250,
        description:
          `the create-time group refresh of M3U account ${accountId} to ` +
          `settle (status 'error' or 'pending_setup') before triggering the ` +
          `real refresh`,
        ...options,
      }
    );
  }

  // Mirrors UpstreamClient.playlistUrl() in upstream.ts exactly, for the same
  // reason `upstreamStreamUrl` above is: importing UpstreamClient here would
  // create a fixture cycle. If the provider's URL shape changes, change both.
  private upstreamPlaylistUrl(scenario: UpstreamScenario): string {
    return `${scenario.internal}/playlist.m3u${scenario.credentialQuery}`;
  }

  /**
   * An `EPGSource` pointed at a fake-provider scenario, refreshed and waited
   * out. The create-and-wait dance, once.
   *
   * No explicit trigger: `trigger_refresh_on_new_epg_source` fires
   * `refresh_epg_data.delay()` on the `post_save` of an active non-dummy
   * source, so the refresh is already running by the time this returns from
   * the create. The create response is the baseline (its `updated_at` is
   * guaranteed `null`), which is what closes the race a later baseline read
   * would open.
   *
   * The returned source has `EPGData` rows and **zero `ProgramData`**: the
   * mapping gate in `parse_programs_for_source` means programmes only arrive
   * once a Channel points at an `EPGData` row. Associate with
   * `POST /api/channels/channels/<id>/set-epg/` and poll
   * `/api/epg/programs/search/?channel_id=` for them.
   */
  async upstreamEpgSource(
    scenario: UpstreamScenario,
    overrides: EpgSourceOverrides = {}
  ): Promise<EpgSource> {
    const source = await this.epgSource({
      ...overrides,
      source_type: 'xmltv',
      url: this.upstreamEpgUrl(scenario),
      is_active: true,
    });
    return this.waitFor.epgRefreshComplete(source.id, {
      baseline: source,
      trigger: async () => {},
    });
  }

  // Mirrors UpstreamClient.epgUrl(); see the note on upstreamStreamUrl.
  private upstreamEpgUrl(scenario: UpstreamScenario): string {
    return `${scenario.internal}/epg.xml${scenario.credentialQuery}`;
  }

  /**
   * A `Logo` uploaded through the multipart endpoint.
   *
   * The generated filename is load-bearing, not cosmetic:
   * `LogoViewSet.upload` writes to `/data/logos/<basename>` (directory
   * components stripped by `safe_upload_path`) and then does
   * `Logo.objects.get_or_create(url=<that path>)`, so two workers uploading
   * `logo.png` share one row and race each other's assertions.
   *
   * The payload is a few bytes in memory rather than a file on disk:
   * `validate_logo_file` checks only the declared `content_type` and the size,
   * never the magic bytes.
   *
   * This helper deliberately does not delete the uploaded file, and no caller
   * of it should delete the `Logo` row without also deleting the file
   * (`?delete_file=true` on the delete endpoint). A file left behind with its
   * row is inert — the row keeps it out of `scan-files`'s way. A row deleted
   * *without* the file is the one bad state: the `scan-files` beat walks
   * `/data/logos` every 20s and, once the upload's Redis `processed_file:`
   * key expires (3-day TTL, or sooner on a flush), resurrects the orphan as a
   * new `Logo` row under the filename's stem (`core/tasks.py:350`) — for a
   * seeded logo that stem is identical to the name the upload originally gave
   * it, which is the whole reason the row is indistinguishable from the one
   * that was deleted. Keep both, or delete both.
   *
   * The payload is unique per logo, not a fixed constant: see
   * {@link logoPayload}. That is what lets a test assert it read back *this*
   * logo's bytes, not merely *a* seeded logo's bytes.
   */
  async logo(overrides: LogoOverrides = {}): Promise<Logo> {
    const { mimeType = 'image/png', extension = 'png' } = overrides;
    const name = this.generatedName('logo');
    const res = await this.api.upload('/api/channels/logos/upload/', {
      name,
      file: {
        name: `${name}.${extension}`,
        mimeType,
        buffer: logoPayload(name),
      },
    });
    const logo = await this.api.json<Logo>(res, 'seed.logo');
    // Own the identity check rather than borrowing it. Every field a caller
    // can see — `id`, `name`, `url`, `cache_url` — comes from this response,
    // and `get_cache_url` (`apps/channels/serializers.py:60-72`) builds the
    // URL from the same object, so they are self-consistent whichever row
    // came back. Today a *wrong* row is impossible for a product reason, not
    // a test one: `upload` does `get_or_create(url=file_path)`
    // (`apps/channels/api_views.py:2845-2850`), `Logo.url` is `unique=True`
    // (`apps/channels/models.py:1154`), and `file_path` derives from this
    // per-run-unique name. Key the row on anything else — content-hash
    // de-duplication is the plausible change — and that guarantee vanishes
    // silently, with every byte assertion downstream still passing because
    // it would compute the *other* logo's payload from the *other* logo's
    // name. `name` is the one value this function knows independently, so
    // this is the only place the check can be made.
    if (logo.name !== name) {
      throw new Error(
        `seed.logo: uploaded "${name}" but the server returned the row ` +
          `named "${logo.name}" (id ${logo.id}). Every other field is ` +
          `self-consistent with whichever row this is, so nothing further ` +
          `downstream can detect the substitution.`
      );
    }
    return logo;
  }
}

/**
 * The fixed 8-byte PNG signature every `seed.logo()` upload begins with.
 * Exported alongside {@link logoPayload} as the one source of truth for it.
 */
export const PNG_SIGNATURE = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
]);

/**
 * The exact bytes `seed.logo()` uploads for a logo named `name`: the PNG
 * signature followed by the name itself. Every seeded logo therefore carries
 * a different payload — `validate_logo_file` checks only the declared
 * `content_type` and size, never the magic bytes
 * (`dispatcharr/utils.py:51-57`), so the trailing bytes are free. Nothing
 * downstream parses them either: the serving path guesses a type from the
 * file *extension* (`mimetypes.guess_type` reads no bytes) and then streams
 * the file verbatim. That uniqueness is what a test needs to
 * assert the serving path returned *this* logo's file rather than any
 * seeded logo's file, which a byte *count* (or a comparison against one
 * shared constant) cannot distinguish. Exported so a spec derives the
 * expected bytes from the name it gets back (`logoPayload(logo.name)`)
 * instead of transcribing a length that could drift from this function
 * independently.
 */
export function logoPayload(name: string): Buffer {
  return Buffer.concat([PNG_SIGNATURE, Buffer.from(name, 'utf8')]);
}
