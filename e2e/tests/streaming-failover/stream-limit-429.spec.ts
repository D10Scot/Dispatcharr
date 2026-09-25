import { test, expect, StreamStatusError, expectTsAligned } from '../../fixtures';
import type { ApiClient } from '../../fixtures';
import { lockedProfile, newStreamClient, withDeadline } from '../streaming/helpers';

/**
 * The authorize hop's 429 restoration, behaviourally (#179).
 *
 * `docker/nginx.conf`'s `@authorize_denied` location restores two statuses
 * `ngx_http_auth_request_module` cannot carry back from the `auth_request`
 * subrequest: 404 and 429, both collapsed to 403 by the subrequest and put
 * back by `if ($authorize_status = 429) { return 429; }` (and the 404
 * sibling beside it). `tests/streaming/authorize-matrix.spec.ts` exercises
 * the 404 row and says so in its own comment; nothing before this file
 * exercised the 429 row behaviourally —
 * `tests/streaming-greybox/nginx-stream-buffering.spec.ts` pins the line's
 * text statically, which proves the config was written, not that the
 * decision reaches a client.
 *
 * The 429 is reachable only through `authorize_stream`'s live branch
 * (`apps/proxy/authorize.py`), which raises it when `check_user_stream_limits`
 * (`apps/proxy/utils.py`) returns `False` for a user with `stream_limit > 0`
 * already at their limit. `check_user_stream_limits` returns `False` in
 * exactly that case only when `user_limit_settings.terminate_on_limit_exceeded`
 * is `false` — the default is `true`, which instead terminates the user's
 * oldest stream and lets the new tune through — so this test needs an
 * instance-wide `CoreSettings` write to reach the 429 at all.
 *
 * ---------------------------------------------------------------------------
 * THE GLOBAL WRITE (ADR 0003's three-part argument, `tests/guards/allowlist.ts`)
 * ---------------------------------------------------------------------------
 * Group `user_limit_settings` (seeded by
 * `core/migrations/022_default_user_limit_settings.py`, so PATCH works with
 * no prior POST), key `terminate_on_limit_exceeded` only, merged into a
 * spread copy of the row's existing `value` so every sibling key
 * (`terminate_oldest`, `prioritize_single_client_channels`,
 * `ignore_same_channel_connections`) survives unchanged.
 *
 * Why nothing else reads it in a way that matters: the flipped value only
 * changes behaviour for a user whose `stream_limit > 0` AND who is already
 * at that limit. The only other such user seeded anywhere in this suite is
 * `tests/seeded/xc-auth.spec.ts`'s `stream_limit: 3` viewer, which never
 * opens a stream at all — it only drives the `player_api.php` handshake —
 * so it can never be at its limit and this flip cannot change its outcome.
 *
 * How teardown restores it: `test.afterEach` PATCHes the exact `value`
 * captured immediately before this test's own write back, unconditionally —
 * the `tests/dvr/comskip.spec.ts` shape, because a timed-out test skips a
 * body-level `try`/`finally` but not fixture teardown. An up-front guard
 * fails loudly, naming the row, if a previous run already left it `false`,
 * rather than silently adopting a dirty value as "original" — the
 * `catchup-redirect.spec.ts`/`comskip.spec.ts` shape. `CoreSettings._get_group`
 * invalidates the whole group in Redis on `post_save`
 * (`core/signals.py`), reaching every worker immediately, so there is no
 * settling sleep before tuning below.
 *
 * `streaming-failover` is already `workers: 1` for its two other global
 * writes (`failover-buffering.spec.ts`'s `proxy_settings`,
 * `catchup-redirect.spec.ts`'s `stream_settings`); this is the third, and
 * `playwright.config.ts`'s project comment is updated to say so.
 *
 * WHY @contract, on an instance-wide write. ADR 0003's "every file on a
 * capability allowlist is `@characterization`" covers the four capabilities
 * in `tests/guards/allowlist.ts` (`CONTAINER_LIFECYCLE`, `SUBPROCESS`,
 * `GREYBOX_REDIS`, `CONTAINER_INTROSPECTION`) — `GLOBAL_SETTINGS_WRITE` is
 * not one of them, because a global settings write is not itself a fact
 * about this container's internals; it is ordinary product behaviour
 * (a settings PATCH) used to reach a state a client-facing contract needs.
 * `catchup-redirect.spec.ts`, on that same list and `@contract` at `:59`,
 * is the precedent.
 */

const CORE_SETTINGS_PATH = '/api/core/settings/';
const USER_LIMIT_SETTINGS_KEY = 'user_limit_settings'; // core/models.py:214

interface CoreSettingsRow {
  id: number;
  key: string;
  value: Record<string, unknown>;
}

async function readUserLimitSettingsRow(api: ApiClient): Promise<CoreSettingsRow> {
  const rows = await api.json<CoreSettingsRow[]>(await api.get(CORE_SETTINGS_PATH), 'core settings');
  const row = rows.find((r) => r.key === USER_LIMIT_SETTINGS_KEY);
  expect(row, `the "${USER_LIMIT_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
  return row!;
}

// Module-scoped, assigned the moment the value resolves, cleared in
// `afterEach` — the `comskip.spec.ts` shape: fixture teardown always runs,
// even when a Playwright timeout abandons the test body mid-`await`, so this
// is what actually guarantees the restore. Safe as shared module state
// because `streaming-failover` is `workers: 1` with `fullyParallel`
// inherited `false` — one test runs at a time.
let settingsRowId: number | undefined;
let originalValue: Record<string, unknown> | undefined;

test.afterEach(async ({ api }) => {
  const rowId = settingsRowId;
  const original = originalValue;
  settingsRowId = undefined;
  originalValue = undefined;
  if (rowId === undefined || original === undefined) return;

  // `ApiClient.patch` never throws on a non-2xx answer, so a failed restore
  // would otherwise be silent — exactly the outcome this hook exists to
  // prevent. Checked and logged loudly, the `comskip.spec.ts` shape, rather
  // than trusted.
  const res = await api.patch(`${CORE_SETTINGS_PATH}${rowId}/`, { value: original });
  if (!res.ok()) {
    console.error(
      'stream-limit-429.spec.ts: FAILED TO RESTORE user_limit_settings — the ' +
        `shared container is left with the stream limit mutated. row id=${rowId}, ` +
        `status=${res.status()}, intended value=${JSON.stringify(original)}.`
    );
    throw new Error(`restoring user_limit_settings failed: ${res.status()} ${await res.text()}`);
  }
});

// How long a fresh open is allowed to take before this test gives up on it —
// the `process-restart.spec.ts` shape, used to bound `openOutcome` below.
const OPEN_OUTCOME_DEADLINE_MS = 30_000;

/**
 * Open a stream and report the outcome as a string, rather than throwing.
 *
 * `expect.poll` fails on the first throw from its callback instead of
 * retrying, so a transient refusal has to come back as a value, not an
 * exception, for the poll below to keep trying until the limit actually
 * clears. Copied in the smallest form that this file needs: `'ok'` on a
 * successful open, `HTTP <status>` on a `StreamStatusError`, and the error's
 * string form for anything else (`tests/streaming-split/process-restart.spec.ts`).
 */
async function openOutcome(
  client: ReturnType<typeof newStreamClient>,
  path: string
): Promise<string> {
  try {
    await withDeadline(client.open(path), OPEN_OUTCOME_DEADLINE_MS, `opening ${path}`);
    return 'ok';
  } catch (error) {
    if (error instanceof StreamStatusError) return `HTTP ${error.status}`;
    return String(error);
  }
}

/**
 * Open `path` and require an exact refusal status, copied from
 * `tests/streaming/authorize-matrix.spec.ts`'s helper of the same name and
 * the same shape: only a `StreamStatusError` of exactly `status` counts, so
 * a reset, a DNS failure, or a different status rethrows and fails the test
 * for what actually happened, rather than reading as "refused" either way.
 */
async function expectRefused(
  streamClient: { open: (p: string) => Promise<void>; close: () => Promise<void> },
  path: string,
  status: number,
  message: string
): Promise<void> {
  let refused = false;
  try {
    await streamClient.open(path);
  } catch (error) {
    if (!(error instanceof StreamStatusError) || error.status !== status) throw error;
    refused = true;
  }
  try {
    expect(refused, message).toBe(true);
  } finally {
    await streamClient.close();
  }
}

test(
  'a user at their stream limit gets 429, not 403 or 500, through the authorize hop',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient, baseURL }) => {
    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'H3 Limit Held', tvgId: 'h3-limit-held.e2e', logo: null },
        { id: 2, name: 'H3 Limit Second', tvgId: 'h3-limit-second.e2e', logo: null },
      ],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel: held } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const { channel: second } = await seed.upstreamChannel(scenario, {
      channelIds: [2],
      streamProfileId: proxy.id,
    });
    const viewer = await seed.xcUser({ user_level: 1, stream_limit: 1 });

    const row = await readUserLimitSettingsRow(api);
    expect(
      row.value.terminate_on_limit_exceeded,
      'a previous run left user_limit_settings dirty'
    ).not.toBe(false);
    settingsRowId = row.id;
    originalValue = row.value;
    // `api.json` throws on a non-2xx answer, so a failed forward write fails
    // here with its own cause rather than surfacing later as "must get 429",
    // which would name the wrong mechanism.
    await api.json(
      await api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, {
        value: { ...row.value, terminate_on_limit_exceeded: false },
      }),
      'flip terminate_on_limit_exceeded'
    );

    await streamClient.open(`/live/${viewer.username}/${viewer.xcPassword}/${held.id}`);
    // Read enough to be sure the client is registered in the relay's
    // connection count, not merely that the HTTP connection opened.
    expectTsAligned(await streamClient.readPackets(200));

    const secondPath = `/live/${viewer.username}/${viewer.xcPassword}/${second.id}`;
    const secondClient = newStreamClient(baseURL!);
    await expectRefused(
      secondClient,
      secondPath,
      429,
      'a user at stream_limit must get 429 back through @authorize_denied'
    );

    // The status alone doesn't tell nginx's own @authorize_denied page apart
    // from a 429 the relay's inline authorize path could answer as JSON
    // (relay/httpapi/authorize.go) — so this is the test's own proof that
    // the refusal came "through the authorize hop", not only the PR's
    // nginx break-check. `open()` throws before recording headers on a
    // non-ok response (fixtures/stream-client.ts), so this is a fresh probe
    // rather than a read off `secondClient`; it never reaches the relay
    // (auth_request denies it first), so it costs nothing against the limit.
    const probeRes = await fetch(new URL(secondPath, baseURL!).toString());
    expect(probeRes.status, 'the probe should also see the limit').toBe(429);
    // Positive, not negative: an absent header or a `text/plain` answer
    // would both pass a bare `not.toContain('application/json')`. nginx
    // 1.24.0's `return 429` through `error_page 403 = @authorize_denied`
    // answers its own 178-byte `text/html` page (measured), so that is what
    // this asserts.
    expect(
      probeRes.headers.get('content-type') ?? '',
      "a nginx-restored 429 answers nginx's own text/html error page, not the relay's JSON"
    ).toContain('text/html');

    await streamClient.close();
    // Control: the refusal was the limit, not a broken second channel. The
    // relay drops the client from its registry only when the connection
    // ends, so poll rather than read once.
    await expect
      .poll(
        async () =>
          openOutcome(secondClient, `/live/${viewer.username}/${viewer.xcPassword}/${second.id}`),
        { timeout: 30_000, intervals: [1_000] }
      )
      .toBe('ok');
    await secondClient.close();
  }
);
