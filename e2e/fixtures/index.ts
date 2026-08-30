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
 *                                        + body prefixed by `context`. `T`
 *                                        defaults to `unknown`, not `any` —
 *                                        name the shape, e.g.
 *                                        `json<Channel>(res, 'read-back')`
 *   useTokens({ access, refresh })       re-point at another principal
 *   freshAccessToken() → Promise<string> a token with life left in it
 *   expireAccessTokenForTest()           corrupt the token, to drive the 401 path
 *   upload(url, multipart) → Promise<APIResponse>
 *                                        multipart/form-data POST, same 401
 *                                        refresh-and-retry as the verbs above.
 *                                        The one non-JSON write path here.
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
 *   xcAccount(scenario, overrides?) → M3uAccount  an `account_type: 'XC'`
 *                                m3uAccount pointed at an XC `upstream`
 *                                scenario: `server_url` is the scenario's
 *                                bare `internal` base (no `credentialQuery`
 *                                — `normalize_server_url` strips a query),
 *                                credentials go on `username`/`password`,
 *                                `is_active` true. Throws if the scenario was
 *                                not created with both `username` and
 *                                `password` (i.e. `{ xc: true, username,
 *                                password }`) rather than silently sending a
 *                                blank credential.
 *   epgSource(overrides?)        → EpgSource      /api/epg/sources/,
 *                                is_active false
 *   stream(overrides?)           → Stream         /api/channels/streams/,
 *                                is_custom true
 *   upstreamChannel(scenario, opts) → { channel: Channel, streams: Stream[] }
 *                                creates one `stream()` per `opts.channelIds`
 *                                pointed at that fake-upstream channel (via
 *                                `upstream`'s internal URL), then a `channel()`
 *                                wired to try them in that order.
 *                                `opts.channel` is `ChannelOverrides` minus
 *                                `streams`/`stream_profile_id` — the factory
 *                                owns both, so they are not writable here.
 *   upstreamM3UAccount(scenario, overrides?) → M3uAccount
 *                                creates an active account pointed at that
 *                                scenario's playlist, refreshes it, waits, and
 *                                asserts `status === 'success'`. Not for a
 *                                test that wants the refresh to fail.
 *   upstreamEpgSource(scenario, overrides?) → EpgSource
 *                                creates an active XMLTV source pointed at that
 *                                scenario's EPG and waits for its refresh. The
 *                                result has EPGData rows and ZERO ProgramData —
 *                                programmes need a channel association first.
 *   logo(overrides?)             → Logo           /api/channels/logos/upload/,
 *                                multipart, generated filename (the upload is
 *                                get_or_create'd on the path, so a fixed name
 *                                is shared across workers). The payload is
 *                                `logoPayload(name)`, unique per logo — see
 *                                `logoPayload`, also exported here, to derive
 *                                the expected served bytes for a given logo
 *                                instead of transcribing a byte count.
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
 * `pageErrors: PageErrorCollector` — everything the browser reported while the
 *   test ran: `consoleErrors`, `pageErrors`, `failedResponses` (including
 *   network-level failures — connection refused, DNS, blocked — at
 *   `status: 0`), and `expectClean()` (`async`, so `await` it), which fails
 *   naming every offender not covered by `EXPECTED_PAGE_NOISE`. Attached at
 *   fixture setup, so it sees the initial document load. **This fixture calls
 *   `expectClean()` itself at teardown, for every test that uses it** — a
 *   spec never has to remember to. A test that deliberately provokes an
 *   error to exercise the product's own handling of it should call
 *   `pageErrors.waiveAutomaticCheck('<reason>')` to skip that one check; the
 *   reason is mandatory and shows up at the call site. The allowlist rule is
 *   at the top of `page-errors.ts`: a product defect is filed, never
 *   allowlisted.
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
 *   epgRefreshComplete(sourceId, options?) → Promise<EpgSource>
 *       Polls `updated_at`, NOT a terminal status: an XMLTV refresh reaches
 *       `success` twice and the first one is premature. Triggers via
 *       `POST /api/epg/import/` with the id in the BODY; pass
 *       `trigger: async () => {}` when creation already started the refresh,
 *       and `baseline:` the create response so the wait cannot miss it.
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
 *       The socket is already subscribed when you get it — the fixture awaits
 *       `connection_established` before handing it over, so an event your test
 *       causes cannot be missed. That message is **consumed** by the fixture:
 *       there is one per socket, and waiting on it in a test will hang.
 *   close()   the fixture already does this at teardown, and a wait still
 *             pending then is **rejected** rather than left on a 30s timer
 *
 * `streamClient: StreamClient` — reads endless HTTP byte streams, which
 * Playwright's `request` fixture cannot (`APIResponse.body()` awaits the full
 * download).
 *   open(path, options?) → Promise<void>   path absolute or relative to
 *                          baseURL. `options.headers` as before;
 *                          `options.redirect` defaults to 'follow' — pass
 *                          'manual' when the response is expected to be a
 *                          redirect to a container-internal hostname (see
 *                          `upstream` below), since this process cannot
 *                          resolve it. After `open()` resolves, `status` and
 *                          `headers` hold the response's status and Headers,
 *                          so a redirect test can read `Location`.
 *   readPackets(count) → Promise<Buffer>   exactly count * 188 bytes
 *   collectFor(ms) → Promise<Buffer>       everything arriving within ms
 *   close() → Promise<void>                the fixture does this at teardown
 *
 * `upstream: UpstreamClient` — controls G2's fake upstream provider, the
 * container-based stand-in for a real IPTV provider used by streaming tests.
 *   **Two origins, never interchangeable.** Every `UpstreamScenario` carries
 *   both: `internal` (`http://e2e-upstream:8080/s/<id>`) is what Dispatcharr
 *   itself resolves — hand these URLs to `seed.m3uAccount()` /
 *   `seed.epgSource()` / a channel's stream URL. `control`
 *   (`http://127.0.0.1:9402/s/<id>`, from `E2E_UPSTREAM_CONTROL_URL`) is what
 *   this Playwright process can reach — hand these to `fetch` or
 *   `streamClient`. Handing `internal` to the test process, or `control` to
 *   the product, fails or silently talks to the wrong host.
 *   scenario(request?) → Promise<UpstreamScenario>
 *       Creates a scenario (default: one channel, no auth, no connection
 *       limit). `request.channels` is a count or an explicit array of
 *       `{ id, name, tvgId, logo, categoryId? }`. Every scenario made this
 *       way is tracked on `upstream.created` for `attachLogs`; there is
 *       **no cleanup** — scenarios live for the provider process's life,
 *       scoped only by the test that made them never reusing another test's
 *       id.
 *       `request.xc: true` (G8) declares an Xtream Codes scenario and
 *       **requires both `request.username` and `request.password`** — the
 *       provider rejects one without the other at the door. Its catalogue —
 *       `request.liveCategories`/`vodCategories`/`seriesCategories`
 *       (`{ id, name }[]`) and `request.vod`/`request.series` (a count or an
 *       explicit array) — is echoed back on the returned `UpstreamScenario`
 *       as `liveCategories`/`vodCategories`/`seriesCategories`/`vod`/`series`.
 *       Feed an XC scenario straight to `seed.xcAccount(scenario)` rather
 *       than building the `M3UAccount` by hand.
 *       **The default catalogue is identical across every scenario** —
 *       channel `1` is always named `Fake Channel 1` with `tvg-id`
 *       `fake-1.e2e`, movie `1` is always `Fake Movie 1` (year `2020`),
 *       series `1` is always `Fake Series 1` — and `seeded` runs 4 workers
 *       in parallel. For channels this means: asserting on those names, or
 *       filtering by them, aliases another worker's data.
 *       **For `vod`/`series` it is worse than aliasing — it is one shared
 *       row.** Dispatcharr's VOD ingestion matches an incoming XC movie to
 *       an existing `Movie` by TMDB id → IMDB id → **`(name, year)`**,
 *       *globally across every `M3UAccount`*, not per-account (same for
 *       `Series`, and `VODCategory` is unique on `(name, category_type)`
 *       globally too). A bare `vod: 2`/`series: 2` count therefore does not
 *       give two parallel workers two independent rows — both workers'
 *       `xcAccount`s get matched onto the *same* `Movie`/`Series` database
 *       row, because the default name+year pair is identical. This bites a
 *       test that never looks anything up by name: asserting on that movie's
 *       own category, count, or presence can observe a sibling worker's
 *       concurrent write mid-run. Always pass an explicit `vod`/`series`
 *       array with a `seed.generatedName(...)`-derived `name` — a unique
 *       `name` alone is enough, since the `(name, year)` tuple only has to
 *       differ in one half to name a different row; the year need not also
 *       be unique. The same applies to `liveCategories`/`vodCategories`/
 *       `seriesCategories` names, unique globally by `(name, category_type)`.
 *   fault(scenario, name, options?) / clearFault(scenario, name, options?)
 *       → Promise<FaultResult>   arms/disarms one of the twelve `FaultName`s.
 *       The original eight (`dead-air`, `slow-trickle`, `disconnect`,
 *       `not-found`, `auth-failure`, `connection-limit`, `redirect-chain`,
 *       `non-ts-bytes`) act on a live stream; `options.channel` scopes one to
 *       a channel id, omitted applies scenario-wide. The four G8 additions
 *       (`xc-auth-envelope`, `no-tv-archive`, `catchup-layout-404`,
 *       `range-unsupported`) act on the XC surface and are documented on
 *       `FaultName` and `FaultOptions.layout` in `upstream.ts` — two of the
 *       four (`xc-auth-envelope`, `range-unsupported`) are scenario-wide
 *       *only* and **reject** an `options.channel` with a 400, and arming
 *       `catchup-layout-404` requires `options.layout: 'path' | 'query'`.
 *       `FaultResult`'s `appliedTo` counts only *live* connections actually
 *       reached — **`not-found`, `auth-failure`, `connection-limit`,
 *       `redirect-chain` and `non-ts-bytes` can only affect the next
 *       request**, because headers are already sent on any response that is
 *       already open, so `appliedTo: 0` from those five is correct and
 *       expected, not a sign the call did nothing. "Arm `not-found` so the
 *       next reconnect fails" is a normal test with `appliedTo: 0`. Check
 *       `appliedTo` yourself when your test means to disrupt something
 *       already streaming; nothing here asserts or warns on your behalf.
 *   rate(scenario, rate) → Promise<{ rate }>   sets the scenario's own
 *       playback-speed multiplier: the provider paces each chunk against
 *       `asset.byteRate * rate`, so 1 is real-time, 2 is double speed. Has
 *       **no visible effect while `slow-trickle` is armed on the same
 *       connection** — the fault's own rate override takes priority over the
 *       scenario rate for as long as it is active, and only the fault's own
 *       `clearFault` call (not a `rate()` call) hands control back.
 *   log(scenario) → Promise<LogEntry[]>   the scenario's request/open/close/
 *       fault history; `attachLogs` (below) is usually a better way to see it.
 *   connections(scenario) → Promise<{ live, maxConnections, channels }>
 *   playlistUrl(scenario) / epgUrl(scenario) / streamUrl(scenario, channelId)
 *       → string   internal-origin URLs, credential query included, ready to
 *       hand to `seed.m3uAccount()` / `seed.epgSource()` / a channel.
 *   toControl(url) → string   rewrites an `internal`-origin URL to the
 *       equivalent `control`-origin one. Needed because Dispatcharr's
 *       Redirect profile 302s the client to the *original* upstream URL —
 *       validate_stream_url() follows redirects server-side but returns the
 *       URL it was given, so `views.py` redirects the test to
 *       `http://e2e-upstream:8080/...`, a name this process cannot resolve.
 *       A Redirect-profile test opens with `streamClient.open(url, {
 *       redirect: 'manual' })`, reads `Location`, and passes each hop through
 *       `toControl()` before following it. **Throws** on a URL not under the
 *       internal origin — it never passes an unrecognised URL through, which
 *       is how a test would end up making a real outbound request.
 *   created: UpstreamScenario[]   every scenario `scenario()` made this test.
 *   attachLogs(testInfo)   the fixture calls this itself on a failed test —
 *       you should not need to.
 *
 * `instance: Instance` — **lifecycle projects only.** Drives the container's
 * own lifecycle through `scripts/e2e_up.sh`: up/restart/recreate/down, plus
 * the `docker inspect` reads that prove the event happened and
 * `manage(argv)` for migration state. Destroys the container every other
 * project shares — read `./instance.ts`'s header before importing it.
 *
 * ---------------------------------------------------------------------------
 * HELPERS AND CONSTANTS
 * ---------------------------------------------------------------------------
 *   expectTsAligned(buffer)   asserts 188-byte-aligned MPEG-TS: whole packets,
 *                             0x47 sync byte on every boundary. This is the
 *                             assertion that makes byte-level streaming tests
 *                             tractable — reach for it before hand-rolling one.
 *   videoPidOf(buffer)        the busiest non-null PID in a TS buffer. Derives
 *                             which PID carries video rather than hard-coding
 *                             it — a re-muxed asset would otherwise silently
 *                             assert nothing.
 *   expectContiguous(buffer, pid)   asserts the 4-bit continuity counter on
 *                             `pid` advances by exactly one per payload-
 *                             bearing packet, wrapping at 16. This is what
 *                             proves nothing was lost or spliced — a byte
 *                             count alone proves only that bytes arrived, and
 *                             would pass on a stream two owners spliced
 *                             together at alternating chunk indices. Throws
 *                             (message matches `/continuity/i`) on a gap.
 *   readChannelStatus(api, channelUuid) → Promise<ChannelStatus>   reads
 *                             `GET /proxy/ts/status/<channel_id>` (admin-only,
 *                             hence `api` rather than `streamClient`). Takes
 *                             the channel's **uuid**, not its numeric id —
 *                             every `live_proxy` endpoint, this one included,
 *                             is keyed by the same UUID string used to open
 *                             `/proxy/ts/stream/<channel_id>`; the numeric id
 *                             404s. G4's primary assertion surface for owner,
 *                             state, client count and per-client detail.
 *                             Never poll the bare `/proxy/ts/status`
 *                             collection endpoint instead — it broadcasts a
 *                             `channel_stats` WebSocket event as a side
 *                             effect of being polled, which perturbs any test
 *                             waiting on `ws`.
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
import {
  StreamClient,
  expectTsAligned,
  expectContiguous,
  videoPidOf,
  TS_PACKET_SIZE,
  TS_SYNC_BYTE,
} from './stream-client';
import { UpstreamClient } from './upstream';
import { Instance } from './instance';
import { PageErrorCollector } from './page-errors';

export type Fixtures = {
  api: ApiClient;
  seed: Seeder;
  asPrincipal: (name: PrincipalName) => Promise<ApiClient>;
  asUser: (username: string, password: string) => Promise<ApiClient>;
  adminPage: Page;
  pageErrors: PageErrorCollector;
  waitFor: Waiter;
  ws: WsListener;
  streamClient: StreamClient;
  upstream: UpstreamClient;
  instance: Instance;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request));
  },
  seed: async ({ api, waitFor }, use, testInfo) => {
    await use(new Seeder(api, testInfo.workerIndex, testInfo.testId, waitFor));
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
  // Depends on `page`, not `adminPage`: they are the same object, and the
  // listeners must be attached at fixture setup, before the test body runs
  // its first `goto`. Anything attached inside the test misses the initial
  // document load, which is where a bad bundle fails.
  //
  // Teardown calls `expectClean()` itself — opt-out via `waiveAutomaticCheck`,
  // not opt-in — so a spec that destructures `pageErrors` and never calls it
  // cannot pass green with a page full of errors. A failure here is
  // attributed to whichever test was running when teardown ran, same as any
  // other fixture teardown assertion.
  pageErrors: async ({ page }, use) => {
    const collector = new PageErrorCollector(page);
    await use(collector);
    if (!collector.isWaived) {
      await collector.expectClean();
    }
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
    // Awaited, not handed over raw. `consumers.py` joins the `updates` group
    // *after* accept(), so a listener given to a test before then is a socket
    // in no group yet: a test whose first act creates something races its own
    // event against the subscription, and the wait for it times out 15s later
    // naming nothing. `ready()` documents why `connection_established` is the
    // honest barrier.
    await listener.ready();
    await use(listener);
    listener.close();
  },
  streamClient: async ({ baseURL }, use) => {
    const client = new StreamClient(baseURL!);
    await use(client);
    await client.close();
  },
  upstream: async ({}, use, testInfo) => {
    const client = new UpstreamClient();
    await use(client);
    // Only on failure: a passing test's log is noise, and fetching it costs a
    // round trip per scenario.
    if (testInfo.status !== testInfo.expectedStatus) {
      await client.attachLogs(testInfo);
    }
  },
  // Lifecycle projects only — `instance.ts`'s header says why, and it is not
  // a style preference: this fixture destroys the container every other
  // project is sharing. Lazy like every fixture here, so a spec that does not
  // name it never constructs one.
  instance: async ({}, use) => {
    const inst = new Instance();
    await use(inst);
    // Teardown is a safety net, not the primary path — the upgrade spec still
    // tears down in its own `finally`, where it can capture container logs
    // first. This exists because a Playwright *timeout* abandons the test body
    // without running its `finally`, which would otherwise leave a container, a
    // volume, a network and the provider standing for the next run to trip
    // over. Fixture teardown runs even then.
    //
    // Only when this test took ownership: `up()` without `reset` adopts a
    // container that was already there — which is how the restart spec works,
    // and why a developer's instance survives `npm run test:lifecycle`.
    if (inst.owned) {
      try {
        await inst.down();
      } catch (error) {
        console.log(`instance teardown failed: ${String(error)}`);
      }
    }
  },
});

export { expect } from '@playwright/test';
export { ApiClient } from './api';
export type { MultipartValue } from './api';
export { Seeder, SEEDED_USER_PASSWORD, logoPayload } from './seed';
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
export {
  StreamClient,
  expectTsAligned,
  expectContiguous,
  videoPidOf,
  TS_PACKET_SIZE,
  TS_SYNC_BYTE,
} from './stream-client';
export type { StreamOpenOptions } from './stream-client';
export { readChannelStatus } from './channel-status';
export { UpstreamClient, UPSTREAM_CONTROL_BASE, UPSTREAM_INTERNAL_BASE } from './upstream';
export type {
  FaultName,
  FaultOptions,
  FaultResult,
  LogEntry,
  NonXcScenarioRequest,
  ScenarioRequest,
  UpstreamChannel,
  UpstreamScenario,
  XcScenarioRequest,
} from './upstream';
export type {
  BackupEntry,
  Channel,
  ChannelGroup,
  ChannelOverrides,
  ChannelProfile,
  ChannelProfileOverrides,
  ChannelStatus,
  ChannelStatusClient,
  ConnectIntegration,
  EpgData,
  EpgSource,
  EpgSourceOverrides,
  EpgSourceStatus,
  EpgSourceType,
  GroupSettingRow,
  Logo,
  LogoOverrides,
  M3uAccount,
  M3uAccountChannelGroup,
  M3uAccountOverrides,
  M3uAccountProfile,
  M3uAccountStatus,
  PluginListEntry,
  ProgramSearchPage,
  ProgramSearchResult,
  Recording,
  Stream,
  StreamOverrides,
  StreamPage,
  StreamProfile,
  StreamProfileOverrides,
  UpstreamCategory,
  UpstreamChannelOptions,
  UpstreamEpisode,
  UpstreamMovie,
  UpstreamSeason,
  UpstreamSeries,
  User,
  UserAgent,
  UserOverrides,
} from './types';
export { Instance } from './instance';
export type { UpOptions, ManageResult } from './instance';
export { PageErrorCollector, EXPECTED_PAGE_NOISE } from './page-errors';
export type { PageNoiseEntry } from './page-errors';
