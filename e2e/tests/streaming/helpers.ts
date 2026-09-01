import { expect } from '@playwright/test';
import { StreamClient } from '../../fixtures';
import type {
  ApiClient,
  Channel,
  LogEntry,
  M3uAccount,
  Seeder,
  StreamProfile,
  UpstreamClient,
  UpstreamScenario,
  Waiter,
} from '../../fixtures';

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
        'not is_catchup after the account refresh. Before suspecting the candidate ' +
        "cascade, check the five preconditions: the provider channel's own " +
        'tv_archive flag, CoreSettings.get_catchup_enabled(), and the caller ' +
        "user's own custom_properties.catchup_enabled — a bare 400 from the " +
        'catch-up route downstream of this failing silently would otherwise ' +
        'look like a cascade bug.'
    );
  }

  return { scenario, channel: refreshedChannel, providerStreamId };
}

/**
 * One catch-up request Dispatcharr made, parsed into the parameters a test
 * actually asserts on. See `catchupRequests`, which produces these, for how
 * the parse works and — importantly — what it can and cannot prove.
 */
export interface CatchupRequestRecord {
  /** Which builder produced it: `format_b` (PATH) or `format_a` (QUERY). */
  layout: 'path' | 'query';
  /** The raw logged path, including the query string. For diagnostics. */
  path: string;
  status: number | undefined;
  username: string;
  password: string;
  /** The **provider's** stream id, not `Stream.id`. Kept as a string: the PATH form carries it as a path segment and the QUERY form as a param. */
  streamId: string;
  /** Decoded, exactly as Dispatcharr formatted it. Compare against a literal `strftime` output. */
  start: string;
  /** Minutes, as sent. The client's hint plus `DURATION_BUFFER_MINUTES` (5). */
  duration: string;
}

const CATCHUP_PATH_RE =
  /^\/s\/[^/]+\/timeshift\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)\/(\d+)\.ts$/;
const CATCHUP_QUERY_PATHNAME_RE = /^\/s\/[^/]+\/streaming\/timeshift\.php$/;

/**
 * Every catch-up request Dispatcharr made against this scenario, in arrival
 * order, parsed into the parameters a test actually asserts on.
 *
 * Five G10 rows read the provider log the same way, so the parse lives here
 * once. `ScenarioLog.record` appends and never reorders
 * (`e2e-upstream/src/log.ts`), and `logRequest` records
 * `url.pathname + url.search` (`e2e-upstream/src/server.ts:222-229`), so the
 * returned array is arrival-ordered and carries the query string.
 *
 * **What this can and cannot prove.** It reports what Dispatcharr *asked
 * for*. G8's archive is not time-addressable — the catch-up routes serve the
 * same looping TS whatever `start` they are given — so no assertion built on
 * this function is evidence that Dispatcharr seeks to the requested moment.
 * Do not write one that reads as if it were.
 *
 * Both layouts are parsed into one shape because both end in the same
 * `_serve_catchup` (`apps/timeshift/views.py:344`) and a test asserting on
 * "the third candidate" should not care which builder produced it. `start`
 * and the credential fields are decoded: `build_timeshift_url_format_a`
 * interpolates `start` raw (`apps/timeshift/helpers.py:412-421`), so the SQL
 * candidate carries a literal space that `requests` requotes to `%20` in
 * transit — `URLSearchParams` gives the space back, which is the value a
 * test's expected `strftime` output will match.
 */
export function catchupRequests(log: LogEntry[]): CatchupRequestRecord[] {
  const out: CatchupRequestRecord[] = [];

  for (const entry of log) {
    if (entry.kind !== 'request' || !entry.path) continue;

    // A base is required only because `entry.path` is origin-relative; the
    // host is never read.
    const url = new URL(entry.path, 'http://provider.invalid');

    const pathMatch = CATCHUP_PATH_RE.exec(url.pathname);
    if (pathMatch) {
      const [, username, password, duration, start, streamId] = pathMatch;
      out.push({
        layout: 'path',
        path: entry.path,
        status: entry.status,
        username: decodeURIComponent(username),
        password: decodeURIComponent(password),
        streamId,
        start: decodeURIComponent(start),
        duration,
      });
      continue;
    }

    if (CATCHUP_QUERY_PATHNAME_RE.test(url.pathname)) {
      out.push({
        layout: 'query',
        path: entry.path,
        status: entry.status,
        username: url.searchParams.get('username') ?? '',
        password: url.searchParams.get('password') ?? '',
        streamId: url.searchParams.get('stream') ?? '',
        start: url.searchParams.get('start') ?? '',
        duration: url.searchParams.get('duration') ?? '',
      });
    }
  }

  return out;
}

/**
 * `%Y-%m-%d:%H-%M-%S` (UTC) — the colon-dash shape *with* seconds.
 * `normalize_catchup_timestamp_input` accepts it
 * (`_CATCHUP_WALL_CLOCK_RE`, `apps/timeshift/helpers.py:31-44`, whose
 * minute/second separator may be `-` or `:`), and it is the only client
 * shape that lets a test observe whether the requested seconds survive into
 * the colon-seconds candidate. `catchupTimestamp` deliberately omits
 * seconds; this is its sibling, not its replacement.
 */
export function catchupTimestampWithSeconds(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
    `:${pad(date.getUTCHours())}-${pad(date.getUTCMinutes())}-${pad(date.getUTCSeconds())}`
  );
}
