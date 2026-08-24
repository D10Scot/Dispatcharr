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
 * suite** (one client IP, shared across every worker). Each *distinct*
 * `asUser(username, password)` principal spends one; repeats are cached and
 * free. A spec that seeds a fresh user per test blows the budget in seconds
 * and fails with a 429 that reads like a product bug. Read "The login
 * throttle" in `e2e/README.md` before writing a multi-principal test.
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
 *   channel(overrides?)          /api/channels/channels/
 *   user(overrides?)             /api/accounts/users/, user_level 1,
 *                                password = SEEDED_USER_PASSWORD
 *   channelProfile(overrides?)   /api/channels/profiles/   (see CONTEXT.md:
 *                                three different things are called "profile")
 *   streamProfile(overrides?)    /api/core/streamprofiles/
 *   m3uAccount(overrides?)       /api/m3u/accounts/, is_active false
 *   epgSource(overrides?)        /api/epg/sources/, is_active false
 *   generatedName(entity)        the naming scheme itself, for a row you
 *                                create by hand
 *
 * `asUser: (username, password) => Promise<ApiClient>` — an `ApiClient` for a
 * non-admin principal. Token pairs are cached per worker by
 * `username:password`. Costs a login on a miss — see the throttle note above.
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
 *   m3uRefreshComplete(accountId, options?) → Promise<any>
 *       Call *after* triggering the refresh — e.g. POST
 *       /api/m3u/refresh/<accountId>/ (RefreshSingleM3UAPIView), which only
 *       queues the Celery task and returns 202 immediately. Two-phase, each
 *       with its own defaults: phase 1 waits for the refresh to *start*
 *       (status fetching/parsing; 30s / 250ms, via startTimeoutMs), phase 2
 *       waits for it to *finish* (status success/error; 180s / 1s, via
 *       timeoutMs).
 *   options: { timeoutMs?, intervalMs?, description?, describeLast? }
 *       plus startTimeoutMs on m3uRefreshComplete.
 *
 * `ws: WsListener` — subscription to the single `updates` group on `/ws/`.
 * For state the REST API does not expose; prefer `waitFor` otherwise, the
 * message vocabulary is a fixed dict in the product and will drift.
 *   waitForMessage(type, timeoutMs = 30_000) → Promise<any>
 *       Matches top-level `type` or nested `data.type` — most product events
 *       arrive as `{"type": "update", "data": {"type": "<real event>"}}`, so
 *       waiting on the literal `'update'` matches every product event and is
 *       almost never what you want. See the doc comment in `ws.ts`.
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
 */
import { test as base } from '@playwright/test';
import type { Page } from '@playwright/test';
import { ApiClient } from './api';
import { Seeder } from './seed';
import { makeUserClient } from './auth';
import { Waiter } from './wait';
import { WsListener } from './ws';
import { StreamClient, expectTsAligned, TS_PACKET_SIZE, TS_SYNC_BYTE } from './stream-client';

export type Fixtures = {
  api: ApiClient;
  seed: Seeder;
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
export { makeUserClient } from './auth';
export { Waiter } from './wait';
export type { WaitOptions, M3uRefreshWaitOptions } from './wait';
export { WsListener } from './ws';
export { StreamClient, expectTsAligned, TS_PACKET_SIZE, TS_SYNC_BYTE } from './stream-client';
