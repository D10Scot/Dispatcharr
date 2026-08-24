/**
 * The harness contract. Everything a test may use is exported here.
 *
 * Read this file, the root `CONTEXT.md` and `e2e/COVERAGE.md` and you have
 * enough to write a test without opening a fixture. `e2e/README.md` has the
 * rules and the reasoning; this header is the reference.
 *
 * ---------------------------------------------------------------------------
 * READ FIRST — the login throttle
 * ---------------------------------------------------------------------------
 * `POST /api/accounts/token/` is capped at **3 logins per minute for the whole
 * suite** (one client IP, shared across every worker and across back-to-back
 * runs). A full run must therefore spend a number of logins that does not grow
 * with `workers:` or with the number of tests — so it spends **none**:
 * `bootstrap` mints a fixed roster of principal tokens serially, before any
 * worker starts, and hands them to workers as data.
 *
 * **To act as a non-admin, call `asPrincipal('streamer' | 'standard')`. It is
 * free.** `asUser(username, password)` still exists for a user whose own
 * properties are the subject of the test, and costs one login per distinct
 * principal per worker — see its entry below before you reach for it.
 *
 * ---------------------------------------------------------------------------
 * FIXTURES
 * ---------------------------------------------------------------------------
 * `api: ApiClient` — authed HTTP as the bootstrap admin. Refreshes and retries
 * once on a 401, so a suite outliving the 30-minute access token is fine.
 *   get(url) / delete(url) → Promise<APIResponse>
 *   post(url, data) / patch(url, data) → Promise<APIResponse>
 *   json<T>(res, context) → Promise<T>   asserts res.ok(), throws with status
 *                                        + body prefixed by `context`
 *   useTokens({ access, refresh })       re-point at another principal
 *   freshAccessToken() → Promise<string> a token with life left in it
 *   expireAccessTokenForTest()           corrupt the token, to drive the 401 path
 * The verbs return a raw `APIResponse` — nothing is asserted for you. Assert
 * the status yourself, or hand it to `json()` when only the body matters.
 *
 * `seed: Seeder` — creates entities over the REST API under generated,
 * worker-scoped names. Every factory takes optional `overrides` and returns
 * the created row; a caller-supplied `name`/`username` is deliberately
 * ignored, so filter assertions on the returned name.
 *   channel(overrides?)          → Channel        /api/channels/channels/
 *   user(overrides?)             → User           /api/accounts/users/,
 *                                user_level 1, password = SEEDED_USER_PASSWORD
 *   channelProfile(overrides?)   → ChannelProfile /api/channels/profiles/
 *                                (see CONTEXT.md: three different things are
 *                                called "profile")
 *   streamProfile(overrides?)    → StreamProfile  /api/core/streamprofiles/
 *   m3uAccount(overrides?)       → M3uAccount     /api/m3u/accounts/,
 *                                is_active false
 *   epgSource(overrides?)        → EpgSource      /api/epg/sources/,
 *                                is_active false
 *   generatedName(entity)        the naming scheme itself, for a row you
 *                                create by hand
 *   `overrides` is typed per entity — `ChannelOverrides`, `UserOverrides`, …
 *   all exported here — so `seed.channel({ nmae: 'x' })` fails `npm run
 *   typecheck` rather than being silently dropped by DRF. The identity field
 *   is **absent from those types**: it is generated and spread after the
 *   overrides, so passing one does nothing. `channelProfile` has no writable
 *   field left at all, which is why `ChannelProfileOverrides` is empty.
 *   `fixtures/types.ts` says where every field came from and how to add one.
 *
 * `asPrincipal: (name) => Promise<ApiClient>` — an `ApiClient` for one of the
 * pre-provisioned principals, `'streamer'` (user_level 0) or `'standard'`
 * (user_level 1). **Free**: the tokens were minted by `bootstrap` before any
 * worker started, so this is a cache read whatever the worker count.
 *   The roster is `PRINCIPALS`, also exported here — `PRINCIPALS.standard.username`
 *   and `.user_level` are the values to assert against.
 *   These identities are **shared and read-only**: four workers hold them at
 *   once, so nothing may change a principal's level, password,
 *   `channel_profiles` or existence. Need a user row to mutate or delete?
 *   That is `seed.user()`, which is unthrottled and free.
 *
 * `asUser: (username, password) => Promise<ApiClient>` — an `ApiClient` for an
 * arbitrary principal. Token pairs are cached per worker by
 * `username:password`, and the cache is pre-loaded with the fixed principals.
 *   **Costs one login on a miss**, out of three per minute for the whole run,
 *   and a `seed.user()` username is a guaranteed miss every time. It is for
 *   the user no fixed principal can express — one whose own properties the
 *   test is about. Budget at most one such test per run and say so at the call
 *   site; it logs a warning naming the cost when it fires.
 *
 * `adminPage: Page` — a Playwright `Page` already authenticated as the
 * bootstrap admin. Use it, not `page`: it states which principal the test
 * drives, and importing `page` from `@playwright/test` is how a spec ends up
 * bypassing this module entirely.
 *
 * `waitFor: Waiter` — polling. The default way to wait for Celery-backed work.
 *   condition(predicate, options?) → Promise<void>
 *       predicate: () => Promise<boolean>
 *       Defaults: timeoutMs 60s, intervalMs 1s.
 *   resource<T>(url, predicate, options?) → Promise<T>
 *       polls GET url, resolves with the body that satisfied `predicate`
 *       Defaults: timeoutMs 60s, intervalMs 1s.
 *       `T` has no default — supply it (`resource<Channel>(…)`) so the
 *       predicate is checked against the body it will actually receive.
 *   m3uRefreshComplete(accountId, options?) → Promise<M3uAccount>
 *       Triggers the refresh itself — do not POST it yourself first. It
 *       reads the account's current status as a baseline, *then* POSTs
 *       /api/m3u/refresh/<accountId>/ (RefreshSingleM3UAPIView; override via
 *       options.trigger for a non-REST trigger, e.g. a UI click), which only
 *       queues the Celery task and returns 202 immediately. That ordering
 *       (baseline before trigger) is why the method must own the trigger —
 *       reading the baseline after an externally-triggered refresh would
 *       race it. Waits for the refresh to *start* (status fetching/parsing,
 *       30s/250ms via startTimeoutMs) — or, if it fails fast enough that the
 *       in-flight status is missed between polls, for a *terminal* status
 *       that already differs from the baseline, which is proof enough it
 *       ran. Only once genuinely in-flight does it go on to wait for it to
 *       *finish* (status success/error; 180s / 1s, via timeoutMs). See the
 *       doc comment in wait.ts for why `updated_at` can't be used for this
 *       (only bumped on success) and the one gap this doesn't close
 *       (identical back-to-back terminal failures on the same account).
 *   options: { timeoutMs?, intervalMs?, description?, describeLast? }
 *       plus startTimeoutMs and trigger on m3uRefreshComplete.
 *
 * `ws: WsListener` — subscription to the single `updates` group on `/ws/`.
 * For state the REST API does not expose; prefer `waitFor` otherwise — the
 * message vocabulary is unregistered string literals at
 * `send_websocket_update()` call sites (not the `SUPPORTED_EVENTS` dict in
 * `apps/connect/models.py`, which is the *SystemEvent* vocabulary), and will
 * drift.
 *   waitForMessage(type, options?) → Promise<WsMessage>
 *       options: { where?: (data, message) => boolean, timeoutMs? = 30_000 }
 *       `WsMessage` is `{ type?, data? }` and **both halves are optional** —
 *       the product sends messages with no top-level `type`, and events with
 *       no `data`. Read the payload as `message.data?.x`. Its values are
 *       `unknown` on purpose: the event vocabulary is unregistered string
 *       literals at `send_websocket_update()` call sites and will drift, and
 *       they still compare (`data.playlist_id === account.id` typechecks).
 *       Matches top-level `type` or nested `data.type` — most product events
 *       arrive as `{"type": "update", "data": {"type": "<real event>"}}`, so
 *       waiting on the literal `'update'` matches every product event and is
 *       almost never what you want.
 *       Messages are **consumed**: two sequential waits for one type return
 *       two different messages, and a wait that times out is deregistered and
 *       cannot swallow a later wait's event.
 *       `/ws/` is one broadcast group and `seeded` runs 4 workers, so your
 *       socket sees every worker's events. **A bare type match is unsafe for
 *       any event a parallel test could also trigger** — correlate with
 *       `where`, which is handed `message.data`:
 *           const account = await seed.m3uAccount();
 *           await ws.waitForMessage('playlist_created', {
 *             where: (data) => data.playlist_id === account.id,
 *           });
 *       `where` runs when the message arrives, so get the id *before* you
 *       wait. See the doc comment in `ws.ts`.
 *   close()   the fixture already does this at teardown
 *
 * `streamClient: StreamClient` — reads endless HTTP byte streams, which
 * Playwright's `request` fixture cannot (`APIResponse.body()` awaits the full
 * download).
 *   open(path, headers?) → Promise<void>   path absolute or relative to baseURL
 *   readPackets(count) → Promise<Buffer>   exactly count * 188 bytes
 *   collectFor(ms) → Promise<Buffer>       everything arriving within ms
 *   close() → Promise<void>                the fixture does this at teardown
 *
 * ---------------------------------------------------------------------------
 * HELPERS AND CONSTANTS
 * ---------------------------------------------------------------------------
 *   expectTsAligned(buffer)   asserts 188-byte-aligned MPEG-TS: whole packets,
 *                             0x47 sync byte on every boundary. This is the
 *                             assertion that makes byte-level streaming tests
 *                             tractable — reach for it before hand-rolling one.
 *   TS_PACKET_SIZE   188      TS_SYNC_BYTE   0x47
 *   SEEDED_USER_PASSWORD      the password `seed.user()` assigns; import it
 *                             rather than repeating the literal
 *   expect                    re-exported from @playwright/test
 *
 * ---------------------------------------------------------------------------
 * TYPES
 * ---------------------------------------------------------------------------
 * The entity shapes (`Channel`, `User`, `ChannelProfile`, `StreamProfile`,
 * `M3uAccount`, `EpgSource`) and their `*Overrides` counterparts are exported
 * from here and defined in `fixtures/types.ts`. They are **not** the DRF
 * serializers: they are the subset this harness verified against the live API
 * and the model definitions, and nothing more. Missing a field you need? Add
 * it there with the same evidence — never cast. Read the header of that file
 * before you do; it also states the one thing these types cannot promise
 * (excess-property checking fires on object *literals* only, which is why the
 * runtime identity spread in `seed.ts` is still what enforces the rule).
 */
import { test as base } from '@playwright/test';
import type { Page } from '@playwright/test';
import { ApiClient } from './api';
import { Seeder } from './seed';
import { makePrincipalClient, makeUserClient } from './auth';
import type { PrincipalName } from '../setup/principals';
import { Waiter } from './wait';
import { WsListener } from './ws';
import { StreamClient, expectTsAligned, TS_PACKET_SIZE, TS_SYNC_BYTE } from './stream-client';

export type Fixtures = {
  api: ApiClient;
  seed: Seeder;
  asPrincipal: (name: PrincipalName) => Promise<ApiClient>;
  asUser: (username: string, password: string) => Promise<ApiClient>;
  adminPage: Page;
  waitFor: Waiter;
  ws: WsListener;
  streamClient: StreamClient;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request));
  },
  seed: async ({ api }, use, testInfo) => {
    await use(new Seeder(api, testInfo.workerIndex, testInfo.testId));
  },
  asPrincipal: async ({ request }, use) => {
    await use((name: PrincipalName) => makePrincipalClient(request, name));
  },
  asUser: async ({ request }, use) => {
    await use((username: string, password: string) =>
      makeUserClient(request, username, password)
    );
  },
  // The seeded project already applies the admin storageState to `page`, so
  // this is an alias. It exists because the fixture contract names it, and
  // because a spec that says `adminPage` states its intent — a later project
  // could hand `page` a different principal without touching the tests.
  adminPage: async ({ page }, use) => {
    await use(page);
  },
  waitFor: async ({ api }, use) => {
    await use(new Waiter(api));
  },
  // Depends on `api` for the token rather than reading tokens.json: a
  // WebSocket's auth is a query parameter fixed at connect time, so the
  // listener cannot refresh itself, and the file holds the bootstrap token
  // for the whole run. `freshAccessToken()` refreshes when it is close to
  // expiry — which costs nothing from the login budget, TokenRefreshView is
  // not throttled.
  ws: async ({ baseURL, api }, use) => {
    const listener = new WsListener(baseURL!, await api.freshAccessToken());
    await use(listener);
    listener.close();
  },
  streamClient: async ({ baseURL }, use) => {
    const client = new StreamClient(baseURL!);
    await use(client);
    await client.close();
  },
});

export { expect } from '@playwright/test';
export { ApiClient } from './api';
export { Seeder, SEEDED_USER_PASSWORD } from './seed';
export {
  loginsSpentByThisWorker,
  makePrincipalClient,
  makeUserClient,
} from './auth';
export { PRINCIPALS } from '../setup/principals';
export type { PrincipalName, Principal } from '../setup/principals';
export { Waiter } from './wait';
export type { WaitOptions, M3uRefreshWaitOptions } from './wait';
export { WsListener } from './ws';
export type {
  MessagePredicate,
  WaitForMessageOptions,
  WsMessage,
  WsPayload,
} from './ws';
export { StreamClient, expectTsAligned, TS_PACKET_SIZE, TS_SYNC_BYTE } from './stream-client';
export type {
  Channel,
  ChannelOverrides,
  ChannelProfile,
  ChannelProfileOverrides,
  EpgSource,
  EpgSourceOverrides,
  EpgSourceStatus,
  EpgSourceType,
  M3uAccount,
  M3uAccountOverrides,
  M3uAccountStatus,
  StreamProfile,
  StreamProfileOverrides,
  User,
  UserOverrides,
} from './types';
