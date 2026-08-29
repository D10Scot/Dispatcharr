import { expect } from '@playwright/test';
import { StreamClient } from '../../fixtures';
import type {
  ApiClient,
  Channel,
  M3uAccount,
  Seeder,
  StreamProfile,
  UpstreamClient,
  UpstreamScenario,
  User,
  UserOverrides,
  Waiter,
} from '../../fixtures';

/**
 * Local stand-in for G5's future `seed.xcUser()` — not landed as of
 * 2026-08-29 (see G8 task-11-report.md). The root XC catch-up routes
 * (`/timeshift/...`, `/streaming/timeshift.php`) authenticate through
 * `_authenticate_user` (apps/timeshift/views.py:758), which reads
 * `User.custom_properties['xc_password']` and compares it via
 * `hmac.compare_digest` against the URL's password segment — a credential
 * distinct from the Dispatcharr login password, and one no other fixture
 * factory sets.
 *
 * Deliberately not added to `e2e/fixtures/seed.ts`: when G5 lands its own
 * canonical `seed.xcUser()`, the two names would otherwise collide, and the
 * shared fixture is where every other goal's tests would then start reading
 * from. Kept local to G8's own specs instead, so G5's addition needs no
 * merge conflict — whichever lands second should delete this function and
 * repoint `catchup-path-layout.spec.ts` at the shared one. Lives alongside
 * its only consumer rather than in `tests/seeded/`, the project directory it
 * was originally filed under but never called from (task-11-review.md,
 * Minor 1).
 *
 * `user_level: 10` (admin) rather than a Streamer/Standard level wired to a
 * `ChannelProfile`: `_user_can_access_channel` grants an admin every channel
 * unconditionally, sidestepping a profile-membership concern this task does
 * not test. The generated password is run through `Seeder.generatedName`,
 * which already sanitises to `^[A-Za-z0-9._@-]+$` — the exact set
 * `UserSerializer.validate_custom_properties` requires of `xc_password`.
 */
export async function seedXcUser(
  seed: Seeder,
  overrides: UserOverrides = {}
): Promise<User & { xcPassword: string }> {
  const xcPassword = seed.generatedName('xcpass');
  const user = await seed.user({
    user_level: 10,
    ...overrides,
    // Assigned after ...overrides, and after merging in any override's own
    // custom_properties, so a caller can add other keys but can never
    // silently shadow the one property this helper exists to set.
    custom_properties: {
      ...(overrides.custom_properties ?? {}),
      xc_password: xcPassword,
    },
  });
  return { ...user, xcPassword };
}

/** Find a locked built-in Stream Profile by name. Never assert on a count. */
export async function lockedProfile(api: ApiClient, name: string): Promise<StreamProfile> {
  const page = await api.json<{ results?: StreamProfile[] } | StreamProfile[]>(
    await api.get('/api/core/streamprofiles/'),
    'stream profiles'
  );
  const all = Array.isArray(page) ? page : (page.results ?? []);
  const found = all.find((p) => p.name === name);
  expect(found, `the locked "${name}" stream profile should ship`).toBeDefined();
  return found!;
}

/**
 * A second, third, ... StreamClient. The `streamClient` fixture provides
 * exactly one per test; rows that assert on upstream *sharing* need several.
 * The caller owns closing each one.
 *
 * Takes `baseURL` rather than resolving it itself: `playwright.config.ts`
 * already resolves `E2E_BASE_URL` once (with `||`, defaulting on an empty
 * string too) into the `baseURL` fixture every test receives, and the
 * `streamClient`/`ws` fixtures in `fixtures/index.ts` consume that same
 * value. Re-deriving it here with `??` would give an empty-string
 * `E2E_BASE_URL` different behaviour depending on which of the two call sites
 * ran, and would silently drift from the config's default if that ever
 * changed. Pass the test's own `baseURL` fixture through.
 */
export function newStreamClient(baseURL: string): StreamClient {
  return new StreamClient(baseURL);
}

/**
 * Race `work` against a timeout so a hang reports a named cause in seconds
 * instead of a project-level `Test timeout of 300000ms exceeded` minutes
 * later. `readPackets` only throws when a stream *ends* — it hangs forever
 * when the stream stays open but stops delivering, which is exactly what a
 * vanished channel post-failover looks like. `ms` should sit comfortably
 * under the calling project's own timeout.
 */
export async function withDeadline<T>(work: Promise<T>, ms: number, what: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const guard = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${what} did not settle within ${ms}ms.`)),
      ms
    );
  });
  try {
    return await Promise.race([work, guard]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Formats a `Date` as `%Y-%m-%d:%H-%M` (UTC) — the "XC colon-dash" shape
 * `normalize_catchup_timestamp_input` (apps/timeshift/helpers.py) accepts
 * from a client, and one of the seven shapes `build_timeshift_candidate_urls`
 * re-emits toward the provider. UTC, not local time: the seeded scenario's
 * `server_info.timezone` is `UTC` (`seedCatchupChannel` waits for it), and
 * `convert_timestamp_to_provider_tz` skips conversion for exactly that
 * value — so a test that formats in UTC and later asserts the same string
 * survived unchanged is asserting something real, not an accident of the
 * local machine's timezone.
 */
export function catchupTimestamp(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
    `:${pad(date.getUTCHours())}-${pad(date.getUTCMinutes())}`
  );
}

export interface CatchupChannelSetup {
  scenario: UpstreamScenario;
  /** Wired to a Stream ingested from `scenario`, with `is_catchup: true`. */
  channel: Channel;
  /**
   * The provider's own channel id — what `_prepare_catchup_stream_attempt`
   * (apps/timeshift/views.py:1618) reads back off
   * `Stream.custom_properties.stream_id` and interpolates as the final path
   * segment / `stream=` param of every candidate URL. Not read back from the
   * API: `StreamSerializer` never exposes `custom_properties`
   * (xc-ingest.spec.ts), so the id this helper itself declared to the
   * provider is the only source of truth for it.
   */
  providerStreamId: number;
}

interface CatchupSeedFixtures {
  upstream: UpstreamClient;
  seed: Seeder;
  api: ApiClient;
  waitFor: Waiter;
}

interface StreamSearchPage {
  count: number;
  results: { id: number; name: string }[];
}

/**
 * An XC account whose ingested streams advertise catch-up, and a Channel
 * wired to them with `Channel.is_catchup` actually set.
 *
 * `Channel.is_catchup` has two rollup mechanisms, and this helper exercises
 * only one: `ChannelSerializer.create()` (`apps/channels/serializers.py:567`)
 * creates one `ChannelStream` per stream via `.objects.create(...)`, and the
 * `post_save`/`post_delete` signal `update_channel_catchup_fields`
 * (`apps/channels/signals.py:393-394`) rolls `is_catchup` up onto the channel
 * synchronously, right there — no refresh needed. The other mechanism,
 * `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:1963`), is what the
 * bulk SQL update `sync_auto_channels` relies on for its own
 * `ChannelStream.objects.bulk_create(...)` (which fires no signal) — the
 * path a channel created by *auto* channel sync depends on. No channel built
 * by this helper ever takes that path, so a second refresh here would only
 * re-run the SQL rollup over a row the signal has already fixed, proving
 * nothing. Verified by mutation check (task-11-report.md): removing the
 * refresh below still leaves `is_catchup` set correctly.
 *
 * The final guard (`if (!refreshedChannel.is_catchup) throw`) is what
 * matters regardless of which mechanism is in play — mutation-checked
 * separately by wiring no stream to the channel at all, which does throw
 * with this message (task-11-report.md). PATCHing the field directly is
 * possible (`ChannelSerializer` exposes it) and would be the fallback if
 * this proves flaky, but it skips the ingest path these proofs exist to
 * exercise.
 */
export async function seedCatchupChannel(
  fx: CatchupSeedFixtures
): Promise<CatchupChannelSetup> {
  const { upstream, seed, api, waitFor } = fx;
  const prefix = seed.generatedName('catchup');
  const providerStreamId = 1;

  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      {
        id: providerStreamId,
        name: `${prefix}-ch`,
        tvgId: `${prefix}-ch.e2e`,
        logo: null,
        categoryId: 1,
      },
    ],
  });

  const account = await seed.xcAccount(scenario);

  const firstRefresh = await waitFor.m3uRefreshComplete(account.id);
  expect(
    firstRefresh.status,
    `seedCatchupChannel: first XC refresh for account ${account.id} (${prefix})`
  ).toBe('success');

  const page = await api.json<StreamSearchPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    'streams ingested by seedCatchupChannel'
  );
  const ingested = page.results.find((s) => s.name === `${prefix}-ch`);
  if (!ingested) {
    throw new Error(
      `seedCatchupChannel: no ingested Stream named "${prefix}-ch" after the ` +
        `first refresh of account ${account.id} — the XC ingest itself is ` +
        'broken, not catch-up.'
    );
  }

  const channel = await seed.channel({ streams: [ingested.id] });

  // server_info.timezone lands on the default profile via a .delay()'d task
  // (refresh_account_profiles), fired after the first refresh awaited above —
  // a separate async step, not a side effect of it completing. Reading it
  // too early would see null, and because convert_timestamp_to_provider_tz
  // treats null exactly like "UTC", a timestamp assertion in a caller could
  // then pass whether or not this actually landed — proving nothing.
  await waitFor.resource<M3uAccount>(
    `/api/m3u/accounts/${account.id}/`,
    (body) =>
      body.profiles.some(
        (profile) =>
          (profile.custom_properties as { server_info?: { timezone?: string } } | null)
            ?.server_info?.timezone === 'UTC'
      ),
    { description: 'the XC account profile to carry server_info.timezone' }
  );

  const refreshedChannel = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channel.id}/`),
    `channel ${channel.id} after the catch-up rollup refresh`
  );
  if (!refreshedChannel.is_catchup) {
    throw new Error(
      `seedCatchupChannel: channel ${channel.id} (${refreshedChannel.name}) is ` +
        'not is_catchup after two refreshes. Before suspecting the candidate ' +
        "cascade, check the five preconditions: the provider channel's own " +
        'tv_archive flag, CoreSettings.get_catchup_enabled(), and the caller ' +
        "user's own custom_properties.catchup_enabled — a bare 400 from the " +
        'catch-up route downstream of this failing silently would otherwise ' +
        'look like a cascade bug.'
    );
  }

  return { scenario, channel: refreshedChannel, providerStreamId };
}
