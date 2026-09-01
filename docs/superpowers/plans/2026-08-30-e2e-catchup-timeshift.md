# G10 — Catch-up / Timeshift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Dispatcharr's catch-up path end to end — that the XC ingest fields catch-up depends on reach `Channel.is_catchup` through the ingest rollup, that all four client entry points converge on the same code, that redirect mode mirrors the client's own URL layout and fetches nothing, and that proxy mode's seven-candidate cascade walks real HTTP against a real server, emits exactly four timestamp shapes, finds a live one, and caches the winner per account.

**THE ONE LIMIT THAT GOVERNS EVERY ROW.** G8's archive is **not time-addressable**: the catch-up routes serve the same looping TS whatever `start` they are given (`e2e-upstream/src/xc/router.ts`, the comment above the `serveChannelStream` call in the catch-up branch). **G10 therefore cannot prove Dispatcharr seeks to the right moment. It proves the right moment was *asked for*.** Every assertion about time is an assertion on the URL Dispatcharr sent upstream, read out of the provider's scenario log — never on the bytes that came back. This is spec decision D1. It is not a preamble: **every task below that asserts on a timestamp carries this sentence in the test's own comment**, in the words given in that task's steps. A passing G10 suite is not evidence of correct seeking, and any reader who could mistake it for that must be stopped by the comment sitting next to the assertion.

**Architecture:** No new Playwright project, no CI matrix job, no `scripts/e2e_up.sh` change, no `.github/workflows/e2e-tests.yml` change (spec D8). Six spec files land in the existing `seeded` (4 workers, 30s) and `streaming` (2 workers, 300s) projects, one appends to a file G8 already created in `streaming`, and one goes in `streaming-failover` (1 worker, 300s) because it read-modify-writes the **global** default stream profile. Three GitHub issues are filed; no line of `apps/`, `core/` or `dispatcharr/` is edited.

**Tech Stack:** TypeScript 5.7.2 (strict, `tsc --noEmit` via `npm run typecheck`), Playwright 1.62.1, Node 24, the G1 fixture set (`api`, `seed`, `waitFor`, `streamClient`, `upstream`, `asPrincipal`, built-in `request`), the G8 XC provider, Docker.

**Spec:** `docs/superpowers/specs/2026-08-30-e2e-catchup-timeshift-design.md` — read it before Task 1. Every task cites the decisions and inventory rows it implements.

**Verified at `e1616ae6`** (`origin/main`, "test(e2e): the fake upstream provider speaks Xtream Codes (G8) (#77)"). The branch this plan is written on, `docs/e2e-g9-g10-specs` (`4b094f6a`), is based on `8d6db577` and **does not yet contain G8's merge**; every `e2e/` and `e2e-upstream/` fact below was read from `origin/main`, and the implementer must be on a branch that contains `e1616ae6`. `git diff 8d6db577 origin/main -- apps/ dispatcharr/ core/` is empty, so all product-code line numbers hold at both commits. Line numbers drift; the symbol names do not — check the symbol if a line has moved.

---

## What G8 already landed, and what that changes

The spec was written and verified at `8d6db577`, before G8's implementation merged. G8's PR turned out to ship **more** than the spec assumed, and one of its plumbing proofs occupies a filename the spec's inventory assigns to G10. This section is the reconciliation. **Read it before Task 7.**

| Already on `main` | Consequence for this plan |
|---|---|
| `e2e/tests/streaming/catchup-cascade.spec.ts` exists and asserts: PATH blocked → exactly 3 PATH 404s then 1 QUERY 200, total exactly 4, arrival order pinned, **and the three PATH timestamp shapes by literal value** plus the winning QUERY shape | Spec row 9 as written is ~90% landed. Spec D3 is explicit — *"the cascade rows go beyond G8's plumbing proof, or they are not written"* — so row 9 is **re-scoped** (Task 7 Step 2) to the one thing G8 structurally cannot reach: the **fourth** shape, `%Y-%m-%d %H:%M:%S` (QUERY candidate 4, the SQL form with a literal space). `catchup-layout-404 { layout: 'path' }` stops the walk at candidate 3, so only the `not-found` fault — which forces all seven candidates — can observe it. Row 9 and row 11's `not-found` arm therefore become **one** test that asserts all seven attempts in candidate order across exactly four distinct shapes |
| `e2e/tests/streaming/catchup-path-layout.spec.ts` drives the root **PATH** XC route and asserts credentials, `/65/`, `stream_id` and an unchanged `start` | Spec row 7's genuine delta is the root **QUERY** route (`/streaming/timeshift.php`) and the proof that the client's layout does **not** change the upstream cascade. Task 6 Step 3 says so, and strengthens G8's `expect(asked.length).toBeGreaterThan(0)` to an exact count |
| `e2e/tests/seeded/xc-ingest.spec.ts` already proves the **stream-level** half of row 1: two channels, `no-tv-archive` armed on one, `Stream.is_catchup`/`catchup_days` asserted `true`/`>0` and `false`/`0` | Row 1's delta is the **channel-level** rollup. Task 2 re-scopes accordingly, and — see the next row — corrects how the spec proposed to reach it |
| `seedCatchupChannel()` and `catchupTimestamp()` live in `e2e/tests/streaming/helpers.ts` | Reused by Tasks 3, 4, 6, 7 and 9. Seeded specs import them across the project directory as `'../streaming/helpers'`; that is legal (Playwright's `testMatch` never collects `helpers.ts`) and is the alternative to a second copy that would drift |
| `seedCatchupChannel`'s own header records a mutation check: **removing its post-wiring refresh still leaves `is_catchup` set** | The spec's row 1 ("wire the stream to a channel, refresh again, assert `Channel.is_catchup`") would have proved the **signal**, not the rollup task. `ChannelSerializer.create` creates each `ChannelStream` with `.objects.create(...)`, and `update_channel_catchup_fields` (`apps/channels/signals.py:393-407`) is a `post_save`/`post_delete` receiver on `ChannelStream` that rolls the flag up synchronously. Task 2 inverts the direction so the rollup task is the *only* mechanism that can have produced the observed state |
| `UpstreamChannel` (`e2e/fixtures/upstream.ts:74-87`) has no `tvArchive` field; `renderLiveStreams` emits `tv_archive: 1, tv_archive_duration: 7` for **every** channel unless the channel-scoped `no-tv-archive` fault is armed (`e2e-upstream/src/xc/catalogue.ts`, `DEFAULT_ARCHIVE_DAYS = 7`; `src/xc/router.ts`'s `get_live_streams` dispatch) | The spec's conditional fixture addition (`tvArchive?`/`tvArchiveDays?` on `ChannelSpec`) is **not needed and must not be written**. `upstream.fault(scenario, 'no-tv-archive', { channel: N })` expresses both states with no change to either package, and `7` is the literal expected `catchup_days` everywhere in this goal. This closes the spec's last Risk row |
| `e2e/COVERAGE.md` carries **nine** Catch-up/G10 rows, not seven: G8 added two `Gap` rows assigned to G10 — the provider stream id not being observable through the REST API, and the `POST /api/catchup/sessions/` branch being unexercised | Both are resolved by work this plan already contains (Tasks 6 and 7 read the stream id out of the provider log; Tasks 4 and 6 drive the session API and play back with the minted `session_id`). Task 10 therefore adds **three** new rows, not the spec's four — the session-API row already exists |
| `e2e/COVERAGE.md`'s Upstream row on the credential-encoding skew records it as **already filed: [#61](https://github.com/D10Scot/Dispatcharr/issues/61)** | The spec's defect **C2** needs no new issue. G10 files **three** issues, not four. Spec D13 (no inventory row) stands unchanged; Task 10 records that the row stays `todo` and stays G9's |
| G8's PR **fixed** the provider's over-permissive timestamp parser in-PR (commit *"reject the eight hybrid timestamp shapes"*): `CATCHUP_TIMESTAMP_SHAPES` in `e2e-upstream/src/xc/catchup.ts` is now one regex per shape, tried in order | This is what makes Task 7 Step 2 a real proof rather than a tautology: a Dispatcharr regression emitting a hybrid shape gets a **400** from the router's `startIso === null` branch, logged as 400, before `serveChannelStream` ever sees it. The COVERAGE row describing the old permissive regex is now stale — Task 10 Step 4 corrects it |

Nothing here contradicts a spec **decision**. Where it contradicts a spec **assumption about G8**, the verified state of `origin/main` wins and the task says so in its own text.

---

## Global Constraints

Copied from the spec and the programme rules. Every task's requirements implicitly include this section.

- **The seeking limit is carried in the tests, not in this preamble.** (D1.) Every test that asserts on a timestamp, a duration or a `Location` carries a comment ending: *"This proves the right moment was asked for. It does not prove Dispatcharr seeks to it: the fake archive serves the same loop whatever `start` it is given."* The exact placement is given per task. Do not paraphrase it away; do not hoist it to a file header and delete it from the assertions.
- **Every time assertion reads the provider's scenario log, never the bytes.** `upstream.log(scenario)` → `catchupRequests(...)`. No test asserts anything about *which* moment the returned TS represents, because the provider does not encode one.
- **G10 adds no provider capability.** (D2.) Every fault and field used is one G8 ships: `catchup-layout-404 { layout }`, `no-tv-archive`, `auth-failure`, `not-found`, `non-ts-bytes`, the scenario `account.serverInfo.timezone` override, and `xc: true`. If a step tempts you to edit `e2e-upstream/`, stop — it is out of scope and belongs in a report to the controller.
- **Each test creates its own scenario, its own XC account and its own channels**, and scopes every assertion to them (roadmap rule 4). **For every cascade observation this is load-bearing, not hygiene** (D5): `_set_cached_format_index` writes `timeshift:format_idx:<account_id>` into the Django cache (Redis, DB 0) with a **3600s** TTL (`apps/timeshift/views.py:3145-3148`, `_FORMAT_CACHE_TTL = 3600`, `apps/timeshift/redis_keys.py:64-65`). A test reusing another test's account inherits its cascade winner and passes for the wrong reason. The one test that deliberately reuses an account (Task 7 Step 3) says so in a comment.
- **Product defects are asserted *correct*, marked `test.fail()`, and filed — never patched.** A `test.fail()` asserting the *buggy* behaviour goes green the wrong way and locks the defect in. Issues go to `gh issue create --repo D10Scot/Dispatcharr` — **the explicit `--repo` flag is mandatory**: this checkout is a fork of `Dispatcharr/Dispatcharr` and `gh` without it resolves to the upstream public tracker (`docs/agents/issue-tracker.md`). Add `--label needs-triage`; if that call fails because the label does not exist on the fork, re-run without it and say so in the task report.
- **No product code is modified.** Not `apps/`, not `core/`, not `dispatcharr/`, not `frontend/`. Three `test.fail()`s and three issues.
- **`e2e/playwright.config.ts` is edited exactly once, by Task 1, and only to extend a comment.** `.github/workflows/e2e-tests.yml` and `scripts/e2e_up.sh` are **not** edited (D8) — that keeps G10 clear of the zizmor ratchet.
- **`Channel.id` and `Channel.uuid` are both in play and are not interchangeable.** The root XC routes take the numeric PK (`/timeshift/<u>/<p>/<dur>/<start>/<Channel.id>.ts`, `?stream=<Channel.id>`); the native route takes the UUID (`/proxy/catchup/<Channel.uuid>`, no trailing slash — `apps/timeshift/urls.py`). Mixing them produces a 404 that looks like a catch-up failure.
- **The provider's stream id is not the Dispatcharr stream id.** Every candidate URL's final path segment / `stream=` param is `Stream.custom_properties['stream_id']` (`apps/timeshift/views.py:1641`), which `StreamSerializer` never exposes. The only source of truth in a test is the id the scenario itself declared — `seedCatchupChannel` returns it as `providerStreamId`, and it is `1` for every scenario in this goal.
- **The five-link precondition chain gives a terse 400 and no upstream contact when it breaks.** `_serve_catchup`'s preconditions (`apps/timeshift/views.py:358-371`) return before any provider contact, and three distinct causes produce the *same* body. When a streaming row fails with `400 Bad Request` and an empty provider log, suspect the chain, not the cascade — Task 3 exists to make each link independently observable and `seedCatchupChannel`'s final guard throws with a message naming them.
- **Drive client-facing surfaces with Playwright's built-in `request` fixture, not `api`.** `api` is for seeding and admin reads. `ApiClient.send` retries once through a token refresh **on any 401**, which is a status two of these rows assert on. `request` is a built-in of the extended `test`, so `async ({ request, seed }) => …` just works. The `/proxy/catchup/` native route is the exception where a Bearer header is wanted: mint it with `await api.freshAccessToken()` and pass it on the `request` (or `streamClient`) call, exactly as `catchup-cascade.spec.ts` already does.
- **The typecheck hook is blocking.** Any edit under `e2e/**/*.ts` runs `tsc --noEmit` for that package and blocks on failure. Run `cd e2e && npm ci` once before starting, or the check degrades to a loud note.
- **Never assert a global count or an unfiltered list.** Four workers share one container. `/output/m3u` and `player_api.php?action=get_live_streams` render every channel on the instance. Locate your own rows by the name `seed` generated.
- **XC passwords are generated per user and thrown away with them.** Dispatcharr logs full provider URLs including `?password=` at INFO and CI prints `docker logs dispatcharr-e2e` on failure. Never introduce a fixed XC credential.
- **Commit after every task.** Stage in one shell call, commit in the next — a `PreToolUse` hook rejects `git add` and `git commit` in the same Bash invocation.
- **Import map — every shared symbol comes from exactly one place. Never redefine one locally.**

  | Symbol | From |
  |---|---|
  | `test`, `expect`, `expectTsAligned`, `TS_PACKET_SIZE` | `'../../fixtures'` |
  | `Channel`, `Stream`, `StreamPage`, `M3uAccount`, `User`, `LogEntry`, `UpstreamScenario`, `ApiClient`, `Seeder`, `Waiter`, `UpstreamClient`, `StreamClient` (types) | `'../../fixtures'` |
  | `seedCatchupChannel`, `catchupTimestamp`, `seedXcUser`, `lockedProfile`, `newStreamClient`, `withDeadline`, **`catchupRequests`**, **`CatchupRequestRecord`** | `'./helpers'` from `tests/streaming/`, `'../streaming/helpers'` from `tests/seeded/` and `tests/streaming-failover/` |

---

## Reference: the seven candidates, once, so no task re-derives them

`build_timeshift_candidate_urls` (`apps/timeshift/helpers.py:466-498`) returns exactly seven URLs in this order, over exactly **four** distinct `strftime` shapes. `format_b` is the PATH builder (`helpers.py:424-433`), `format_a` the QUERY builder (`helpers.py:412-421`).

| # | Layout | Shape | `strftime` | Example for `2026-01-15 13:00:00` |
|---|---|---|---|---|
| 0 | PATH | colon-dash | `%Y-%m-%d:%H-%M` | `2026-01-15:13-00` |
| 1 | PATH | underscore | `%Y-%m-%d_%H-%M` | `2026-01-15_13-00` |
| 2 | PATH | colon-seconds | `%Y-%m-%d:%H:%M:%S` | `2026-01-15:13:00:00` |
| 3 | QUERY | underscore | `%Y-%m-%d_%H-%M` | `2026-01-15_13-00` |
| 4 | QUERY | **SQL** | `%Y-%m-%d %H:%M:%S` | `2026-01-15 13:00:00` |
| 5 | QUERY | colon-dash | `%Y-%m-%d:%H-%M` | `2026-01-15:13-00` |
| 6 | QUERY | colon-seconds | `%Y-%m-%d:%H:%M:%S` | `2026-01-15:13:00:00` |

Three facts that follow, and that tasks depend on:

- **Candidate 4 carries a literal space.** `format_a` percent-encodes username and password with `quote(..., safe='')` but interpolates `start` **raw** (`helpers.py:412-421`). `requests` requotes the space to `%20` in transit; G8's parser reads it back with `URLSearchParams`, so `catchupRequests` sees a real space. Only the `not-found` fault reaches this candidate.
- **The provider accepts exactly these four and rejects the eight hybrid separator/seconds combinations** (`e2e-upstream/src/xc/catchup.ts`, `CATCHUP_TIMESTAMP_SHAPES`, one regex per shape). An unrecognised shape is answered **400** by `handleXc` *before* `serveChannelStream` runs, so it is logged as 400 even when `not-found` is armed. A regression emitting a hybrid therefore surfaces as a 400 in the log, not a silent pass.
- **The client's own layout does not affect this list.** `client_timeshift_url_layout` (`helpers.py:436-446`) is consumed only by `_select_catchup_redirect_url` (`views.py:413-419`, `:1709`). `_attempt_timeshift_stream` calls `build_timeshift_candidate_urls` unconditionally (`views.py:2673`), so a request arriving on `/streaming/timeshift.php` still walks PATH candidates first.

And the cascade's outcomes (`views.py:3274-3341`):

| Provider answer | Cascade | Client sees |
|---|---|---|
| 200/206 with a TS sync byte in the first 1024 | stops, index cached | the stream |
| 200 with **no** sync (PHP/HTML error page) | `last_status = 404`, **continue** (`:3312`) | after all seven: `404 "Catch-up not available yet"` |
| 404 | continue | after all seven: `404 "Catch-up not available yet"` |
| 401 / 403 / 406 / an unfollowed 3xx | `decisive_failure = True`, **break** (`:3326`) | `400 "Provider error"` for 401 and 406 — **not** 401. `403` only maps to 403 |
| 416 | passed through verbatim (`:3274`) | 416 |

---

## File Structure

**Created:**

| Path | Responsibility | Rows |
|---|---|---|
| `e2e/tests/seeded/catchup-ingest.spec.ts` | The XC ingest → `Stream` → `Channel` rollup, both directions | 1, 2 |
| `e2e/tests/seeded/catchup-preconditions.spec.ts` | Four failure-closed preconditions, and the empty provider log | 3 |
| `e2e/tests/seeded/catchup-session-api.spec.ts` | `POST /api/catchup/sessions/` — 201, 400, 403 | 4 |
| `e2e/tests/seeded/catchup-m3u-advertisement.spec.ts` | The missing `catchup=` attribute (known-bug) and the XC asymmetry that proves it | 5 |
| `e2e/tests/streaming/catchup-proxy-mode.spec.ts` | Proxy mode end to end, both root entry points, the session-id playback, `hide_adult_content` (known-bug) | 6, 7, 8 + COVERAGE's session row |
| `e2e/tests/streaming/catchup-provider-timezone.spec.ts` | `server_info.timezone` conversion, and the seconds truncation (known-bug) | 12, 13 |
| `e2e/tests/streaming-failover/catchup-redirect.spec.ts` | Redirect mode: three entry points, two layouts, an empty provider log | 14 |

**Modified — the shared files, and which tasks touch them:**

| Path | Change | Task |
|---|---|---|
| `e2e/fixtures/types.ts` | Add `is_catchup` and `catchup_days` to `Stream`; correct the "nothing needs them" comment above it | **1 only** |
| `e2e/tests/streaming/helpers.ts` | Add `CatchupRequestRecord`, `catchupRequests()`, `catchupTimestampWithSeconds()` | **1 only** |
| `e2e/playwright.config.ts` | Extend `streaming-failover`'s `workers: 1` comment with the second global it now hosts (D8) | **1 only** |
| `e2e/tests/streaming/catchup-cascade.spec.ts` | **Append** four tests to G8's existing file; do not modify G8's test | **7 only** |
| `e2e/COVERAGE.md` | Nine G10 rows updated, three appended, one Upstream row resolved, one corrected | **10 only** |
| `e2e/README.md` | One new "Catch-up" section | **10 only** |

**Every other task creates only its own spec file and modifies nothing shared**, so Tasks 2, 3, 4, 5, 6, 8 and 9 are mutually independent and can execute in any order or in parallel once Task 1 has landed. Task 7 is independent of them but must also follow Task 1. Task 10 must run **last** — it lists the files the others create.

**Dependency order:** 1 → {2, 3, 4, 5, 6, 7, 8, 9} → 10.

---

### Task 1: Shared groundwork — the log reader, two `Stream` fields, and the config comment

Implements the spec's "Fixture additions" section and D8. Everything else in this goal reads the provider log through `catchupRequests`; writing that parse five times is how the shapes drift apart. This is the **only** task that edits `e2e/fixtures/types.ts`, `e2e/tests/streaming/helpers.ts` or `e2e/playwright.config.ts`.

**Files:**
- Modify: `e2e/fixtures/types.ts`
- Modify: `e2e/tests/streaming/helpers.ts`
- Modify: `e2e/playwright.config.ts`

**Interfaces:**
- Consumes: `LogEntry` (`e2e/fixtures/upstream.ts:171-182`) — `{ at, kind, method?, path?, status?, channelId?, bytes?, durationMs?, fault?, detail? }`, where `path` is `url.pathname + url.search` as recorded by `logRequest` (`e2e-upstream/src/server.ts:222-229`).
- Produces, from `e2e/tests/streaming/helpers.ts`:
  - `export interface CatchupRequestRecord { layout: 'path' | 'query'; path: string; status: number | undefined; username: string; password: string; streamId: string; start: string; duration: string }`
  - `export function catchupRequests(log: LogEntry[]): CatchupRequestRecord[]`
  - `export function catchupTimestampWithSeconds(date: Date): string`
- Produces, from `e2e/fixtures/types.ts`: `Stream.is_catchup: boolean`, `Stream.catchup_days: number`.

- [ ] **Step 1: Add the two `Stream` fields**

In `e2e/fixtures/types.ts`, the `Stream` type currently ends with `stream_chno`. Append:

```ts
  /**
   * `Stream.is_catchup`, rolled up onto `Channel.is_catchup` by
   * `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:1963-2014`) and by the
   * `ChannelStream` signal `update_channel_catchup_fields`
   * (`apps/channels/signals.py:393-407`). Set on XC ingest from the
   * provider's `tv_archive`, compared as `str(...) in ("1", "True")`
   * (`apps/m3u/tasks.py:1164-1165`), and on the standard-M3U path from the
   * same-named `#EXTINF` attribute (`:1383-1384`).
   */
  is_catchup: boolean;
  /**
   * `Stream.catchup_days`, from the provider's `tv_archive_duration` via
   * `int(... or 0)` (`apps/m3u/tasks.py:1167`). The fake provider declares
   * `7` for every catch-up channel (`DEFAULT_ARCHIVE_DAYS`,
   * `e2e-upstream/src/xc/catalogue.ts`), so `7` is the expected value
   * throughout G10 — and `0` when `no-tv-archive` is armed, because the
   * fields are then omitted from the catalogue entirely rather than sent as
   * zero.
   */
  catchup_days: number;
```

Then find the doc comment immediately **above** `export type Stream`, which lists the serializer fields this harness deliberately does not type. It currently names `is_catchup` and `catchup_days` among them. Remove those two names from that list and leave the rest exactly as they are. Leaving the comment stale is the failure mode this file's own header warns about.

Do **not** add `stream_id`, `is_adult`, `custom_properties` or anything else. `xc-ingest.spec.ts` declares a local interface for `stream_id`; leave it alone.

- [ ] **Step 2: Add `catchupRequests` and `catchupTimestampWithSeconds` to `e2e/tests/streaming/helpers.ts`**

Append at the end of the file. The file already imports `expect` from `@playwright/test` and a type list from `'../../fixtures'`; add `LogEntry` to that existing type import rather than writing a second import statement.

```ts
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
```

Two things to get right, because both have already cost this programme a debugging session:

1. **The `/s/<id>/` prefix is part of the path.** `scenario.internal` is `http://e2e-upstream:8080/s/<scenario-id>` (`e2e-upstream/src/server.ts:205`), and an XC `M3UAccount`'s `server_url` is that value verbatim. A regex anchored at `^/timeshift/` matches nothing.
2. **`streamId` stays a string.** The PATH form yields a path segment and the QUERY form a query param; coercing one to a number and not the other is how two tests end up asserting different things about the same value. Compare against `String(providerStreamId)`.

- [ ] **Step 3: Extend the `streaming-failover` comment in `e2e/playwright.config.ts`** (D8)

The `streaming-failover` project's `workers: 1` comment currently argues **one** invariant precisely — `failover-buffering.spec.ts` mutating the global `proxy_settings` row, and every other spec in the directory happening to drive the locked Proxy profile. G10 adds a second global to that directory, and leaving the comment as it stands would make it quietly incomplete for the next reader.

Append to that existing comment block, keeping its existing text intact:

```
      // SECOND GLOBAL, added by G10: `catchup-redirect.spec.ts`
      // read-modify-writes `stream_settings.default_stream_profile` to the
      // locked Redirect profile for the duration of its run
      // (`CoreSettings.is_default_stream_profile_redirect`,
      // `core/models.py:549-564`), because Redirect mode has no per-channel
      // override — it is a container-wide setting. Same shape as
      // `proxy_settings` above, wider blast radius: while it is flipped,
      // *every* channel in the container answers a session-less catch-up or
      // live request with a 302 to the provider instead of proxying it. The
      // single worker is what makes that safe. Two specs in this directory
      // now depend on it; do not raise it back to 2.
      //
      // Note what the single worker does NOT protect: a run that dies
      // between the write and the `finally` leaves the container on
      // Redirect for every later project too. `catchup-redirect.spec.ts`
      // guards its own next run with an up-front assertion, and that guard
      // protects that test — not the specs that would run before it.
```

- [ ] **Step 4: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.

Run: `cd e2e && npx playwright test --project=streaming --grep "candidate cascade"` against a live topology (`./scripts/e2e_up.sh`) — expect G8's existing cascade test still green. It imports from the file you edited; this is the cheapest proof you did not break it.

- [ ] **Step 5: Commit**

`test(e2e): add a catch-up provider-log reader and the two Stream catch-up fields`

---

### Task 2: Rows 1–2 — the XC ingest rollup reaches `Channel.is_catchup`, both directions

Implements inventory rows 1 and 2. **Re-scoped against what G8 landed**, and the re-scope is the substance of the task: `e2e/tests/seeded/xc-ingest.spec.ts` already proves the *stream-level* half of row 1 (two channels, `no-tv-archive` on one, `Stream.is_catchup`/`catchup_days` asserted both ways). Repeating it would be waste under spec D4.

**What is genuinely unproven, and what this task must therefore be built to prove.** `Channel.is_catchup` has **two** rollup mechanisms and they are not interchangeable:

- `update_channel_catchup_fields` (`apps/channels/signals.py:393-407`), a `post_save`/`post_delete` receiver on `ChannelStream`. `ChannelSerializer.create` creates one `ChannelStream` per stream with `.objects.create(...)`, so **wiring a channel to an already-catch-up stream sets the flag synchronously, right there.**
- `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:1963-2014`), raw Postgres SQL run at the end of every refresh (`:3853`), which is what `sync_auto_channels`' `bulk_create` (no signal) depends on — and the **only** mechanism that reacts to a `Stream`'s catch-up flags *changing* under a channel that is already wired.

The spec's row 1 ("wire the stream to a channel, refresh again, assert `Channel.is_catchup`") would have observed the **signal** and called it the rollup. `seedCatchupChannel`'s own header records the mutation check that proves it: removing its post-wiring refresh still leaves `is_catchup` correctly set. So **both tests below wire the channel while the stream's catch-up state is the opposite of what is finally asserted, and then change the stream's state via a refresh** — after which no `ChannelStream` row has been created or deleted, the signal cannot have fired, and the rollup task is the only thing that can have produced the observed row.

**Files:**
- Create: `e2e/tests/seeded/catchup-ingest.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect` from `'../../fixtures'`; types `Channel`, `Stream`, `StreamPage`, `M3uAccount` from `'../../fixtures'`; fixtures `upstream`, `seed`, `api`, `waitFor`.
- Produces: nothing shared.

**Literals this task depends on:**
- `DEFAULT_ARCHIVE_DAYS = 7` (`e2e-upstream/src/xc/catalogue.ts`) → every `catchup_days` assertion is `7`.
- `no-tv-archive` is **channel-scoped** by the provider's channel id and omits `tv_archive`/`tv_archive_duration` from `get_live_streams` entirely (`e2e-upstream/src/xc/router.ts`'s `get_live_streams` dispatch). Ingest then reads `str(stream.get("tv_archive", "0"))` → `"0"` → `False` (`apps/m3u/tasks.py:1164-1165`).
- **Ordering is guaranteed by `waitFor.m3uRefreshComplete` alone.** `rollup_channel_catchup_fields(account_id)` runs at `apps/m3u/tasks.py:3853`; the account's status is only set to `SUCCESS` afterwards, at `:3865`. A refresh reported `success` has already run the rollup. No extra poll is needed and none should be added.
- **The `POST /api/channels/channels/` response cannot be trusted for `is_catchup`.** The signal writes with `Channel.objects.filter(pk=...).update(...)`, which does not touch the in-memory instance the serializer renders. Always re-read with `GET /api/channels/channels/<id>/`.

- [ ] **Step 1: Write the file header**

```ts
import { test, expect } from '../../fixtures';
import type { Channel, M3uAccount, StreamPage } from '../../fixtures';

/**
 * `Channel.is_catchup` through the **ingest rollup**, in both directions.
 *
 * `e2e/tests/seeded/xc-ingest.spec.ts` (G8) already proves the stream-level
 * half — a provider's `tv_archive` reaching `Stream.is_catchup`/
 * `catchup_days`, with `no-tv-archive` armed on a second channel as the
 * mutation check. This file does not repeat it.
 *
 * What it proves instead is the half only an E2E test can reach:
 * `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:1963-2014`), the raw
 * Postgres statement that runs at the end of every refresh (`:3853`),
 * reacting to a `Stream`'s catch-up flags changing under a channel that is
 * **already wired**.
 *
 * Both tests below wire the channel while the stream's catch-up state is the
 * OPPOSITE of what is finally asserted, then flip the provider and refresh.
 * That ordering is the whole design. `Channel.is_catchup` has a second
 * mechanism — `update_channel_catchup_fields`
 * (`apps/channels/signals.py:393-407`), a `post_save`/`post_delete` receiver
 * on `ChannelStream` that `ChannelSerializer.create` fires synchronously —
 * and a test that wires a channel to an already-catch-up stream observes
 * THAT, not the rollup, however many refreshes it runs afterwards
 * (mutation-checked in `seedCatchupChannel`'s header,
 * `e2e/tests/streaming/helpers.ts`). After the wiring below, no
 * `ChannelStream` row is created or deleted, so the signal cannot fire and
 * the rollup is the only thing left that can have changed the row.
 *
 * `waitFor.m3uRefreshComplete` returning `success` is sufficient
 * sequencing: the rollup runs at `apps/m3u/tasks.py:3853`, the status is
 * written at `:3865`.
 */
```

- [ ] **Step 2: A local seeding helper for this file**

`seedCatchupChannel` is not usable here — it seeds a channel that is *already* catch-up, which is the state these tests must start on the far side of. Write a small local helper instead, at the top of this file:

```ts
const ARCHIVE_DAYS = 7; // e2e-upstream's DEFAULT_ARCHIVE_DAYS.

async function streamsByName(
  api: import('../../fixtures').ApiClient,
  prefix: string
): Promise<Map<string, StreamPage['results'][number]>> {
  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    `streams ingested for ${prefix}`
  );
  return new Map(page.results.map((s) => [s.name, s]));
}

async function readChannel(
  api: import('../../fixtures').ApiClient,
  id: number
): Promise<Channel> {
  return api.json<Channel>(
    await api.get(`/api/channels/channels/${id}/`),
    `channel ${id}`
  );
}
```

(`StreamPage.results` is `Stream[]`, and Task 1 put `is_catchup`/`catchup_days` on `Stream`, so these read back type-checked. If `tsc` complains that `ApiClient` is not exported as a value, import the type at the top instead of inlining `import(...)` — either is fine, pick one and be consistent.)

- [ ] **Step 3: Row 1 — the aggregate pass sets the flag**

```ts
test('a provider turning tv_archive on sets Channel.is_catchup through the ingest rollup', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const prefix = seed.generatedName('catchup-rollup-on');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: 1, name: `${prefix}-arch`, tvgId: `${prefix}-arch.e2e`, logo: null, categoryId: 1 },
      { id: 2, name: `${prefix}-never`, tvgId: `${prefix}-never.e2e`, logo: null, categoryId: 1 },
    ],
  });

  // Both channels start WITHOUT tv_archive. Channel 2 stays that way for the
  // whole test as a negative control: if the rollup ever wrote is_catchup
  // from something other than the provider's advertisement, channel 2 would
  // move too.
  await upstream.fault(scenario, 'no-tv-archive', { channel: 1 });
  await upstream.fault(scenario, 'no-tv-archive', { channel: 2 });

  const account = await seed.xcAccount(scenario);
  const first = await waitFor.m3uRefreshComplete(account.id);
  expect(first.status, 'first XC refresh').toBe('success');

  const before = await streamsByName(api, prefix);
  expect(before.get(`${prefix}-arch`)!.is_catchup).toBe(false);
  expect(before.get(`${prefix}-arch`)!.catchup_days).toBe(0);

  // Wire the channel NOW, while the stream is not catch-up. This is what
  // makes the assertion at the end a rollup proof: the ChannelStream signal
  // fires here, with `false`, and never again.
  const created = await seed.channel({ streams: [before.get(`${prefix}-arch`)!.id] });
  const wired = await readChannel(api, created.id);
  expect(wired.is_catchup, 'the signal rolled up the stream state at wiring time').toBe(false);

  await upstream.clearFault(scenario, 'no-tv-archive', { channel: 1 });

  const second = await waitFor.m3uRefreshComplete(account.id);
  expect(second.status, 'second XC refresh').toBe('success');

  const after = await streamsByName(api, prefix);
  expect(after.get(`${prefix}-arch`)!.is_catchup).toBe(true);
  expect(after.get(`${prefix}-arch`)!.catchup_days).toBe(ARCHIVE_DAYS);
  expect(after.get(`${prefix}-never`)!.is_catchup).toBe(false);
  expect(after.get(`${prefix}-never`)!.catchup_days).toBe(0);

  // THE ROLLUP. No ChannelStream row was created or deleted between the
  // wiring above and here, so `update_channel_catchup_fields`
  // (apps/channels/signals.py:393-407) cannot have fired.
  // `rollup_channel_catchup_fields`'s aggregate pass
  // (apps/m3u/tasks.py:1978-1997, `bool_or(s.is_catchup AND a.is_active)`
  // and `MAX(s.catchup_days) FILTER (...)`) is the only mechanism left.
  const rolled = await readChannel(api, created.id);
  expect(rolled.is_catchup).toBe(true);
  expect(rolled.catchup_days).toBe(ARCHIVE_DAYS);
});
```

- [ ] **Step 4: Row 2 — the rollup clears the flag again**

Same shape, mirrored. Its own scenario and account (roadmap rule 4 — do **not** try to continue Step 3's state; `seeded` is `fullyParallel: true`, so two tests in one file run on different workers and share nothing).

```ts
test('a provider turning tv_archive off clears Channel.is_catchup on the next refresh', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const prefix = seed.generatedName('catchup-rollup-off');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: 1, name: `${prefix}-arch`, tvgId: `${prefix}-arch.e2e`, logo: null, categoryId: 1 },
    ],
  });

  const account = await seed.xcAccount(scenario);
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const before = await streamsByName(api, prefix);
  expect(before.get(`${prefix}-arch`)!.is_catchup).toBe(true);
  expect(before.get(`${prefix}-arch`)!.catchup_days).toBe(ARCHIVE_DAYS);

  const created = await seed.channel({ streams: [before.get(`${prefix}-arch`)!.id] });
  const wired = await readChannel(api, created.id);
  expect(wired.is_catchup, 'the signal set it at wiring time').toBe(true);
  expect(wired.catchup_days).toBe(ARCHIVE_DAYS);

  await upstream.fault(scenario, 'no-tv-archive', { channel: 1 });
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const after = await streamsByName(api, prefix);
  expect(after.get(`${prefix}-arch`)!.is_catchup).toBe(false);
  expect(after.get(`${prefix}-arch`)!.catchup_days).toBe(0);

  // Again the rollup, and this is the direction that matters operationally:
  // a provider that stops advertising an archive must not leave channels
  // claiming one. No ChannelStream row changed, so the signal cannot have
  // fired. Note `catchup_days` going to 0 as well as the boolean —
  // COALESCE(agg.max_days, 0) (apps/m3u/tasks.py:1993-1994) is what does it,
  // and a rollup that cleared only the boolean would leave a channel
  // advertising `tv_archive_duration: 7` on the XC surface with
  // `tv_archive: 0`.
  const rolled = await readChannel(api, created.id);
  expect(rolled.is_catchup).toBe(false);
  expect(rolled.catchup_days).toBe(0);
});
```

No fault teardown is needed in either test: `FaultStore` keys every armed fault by scenario id (`e2e-upstream/src/faults.ts`), and each scenario here is fresh and reachable by no other test.

- [ ] **Step 5: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded catchup-ingest` — expect 2 passed.

**Mutation check, and report the result.** Comment out the `clearFault` in Step 3 and re-run: the test must fail on `after.get(...).is_catchup` being `false`. If it still passes, the fault is not reaching the catalogue and the whole task is proving nothing. Restore afterwards.

- [ ] **Step 6: Commit**

`test(e2e): prove the catch-up ingest rollup sets and clears Channel.is_catchup`

---

### Task 3: Row 3 — the four preconditions fail closed, and the provider is never contacted

Implements inventory row 3 (a **new** COVERAGE row). This row exists because of the goal's sharpest risk: the five-link precondition chain gives a terse 400 and no upstream contact when it breaks, and eleven of fourteen rows sit behind it. A row that only asserts the final outcome reports `400 Bad Request` for any of five distinct causes. **The empty provider log is the first-class assertion here**, not an afterthought.

**Files:**
- Create: `e2e/tests/seeded/catchup-preconditions.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect` from `'../../fixtures'`; `seedCatchupChannel`, `catchupTimestamp`, `catchupRequests` from `'../streaming/helpers'`; fixtures `upstream`, `seed`, `api`, `waitFor`, `request`.
- Produces: nothing shared.

**The preconditions, verified in order.** `catchup_proxy` (`apps/timeshift/views.py:283-341`) then `_serve_catchup` (`:344-371`):

| # | Condition | Where | Response |
|---|---|---|---|
| 1 | `network_access_allowed(request, "STREAMS")` | `views.py:285` | `403 {"error": "Forbidden"}` — defaults to `0.0.0.0/0`, not exercised |
| 2 | no `session_id` and no authenticated user | `:321-324` | `401 {"error": "Authentication required"}` |
| 3 | channel UUID unknown | `:326-330` | `404` |
| 4 | `_user_can_access_channel` | `:332-333` | `403 "Access denied"` |
| 5 | `start` absent | `:335-336` | **`400 "Missing start parameter"`** |
| 6 | `is_catchup_enabled(user)` | `:358-361` | `403 "Catch-up is disabled"` — out of scope (D14) |
| 7 | `parse_catchup_timestamp(timestamp) is None` | `:363-364` | **`400 "Invalid timestamp"`** |
| 8 | `get_channel_catchup_streams(channel)` empty | `:366-370` | **`400 "Timeshift not supported for this channel"`** |

Condition 8 is reached two ways, and **both produce a byte-identical response**: `channel.is_catchup` false makes `get_channel_catchup_streams` return `[]` immediately (`apps/channels/utils.py:141-142`), and so does `m3u_account__is_active=True` filtering every stream out (`:144-148`). That indistinguishability *is* the finding this row records; assert both and say so.

- [ ] **Step 1: Write the file**

```ts
import { test, expect } from '../../fixtures';
import { catchupRequests, catchupTimestamp, seedCatchupChannel } from '../streaming/helpers';

/**
 * Four ways the catch-up preconditions fail closed, and the assertion that
 * gives them meaning: **the provider was never contacted**.
 *
 * `_serve_catchup`'s preconditions (`apps/timeshift/views.py:358-371`) all
 * return before any upstream request, and three distinct causes produce the
 * same `400` body. A downstream row that only checked the status would
 * report "400 Bad Request" for a broken account, a broken channel, a
 * mistyped timestamp or a genuine cascade failure alike. So this row asserts
 * the *empty* provider log as a first-class signal, and each cause
 * separately, before any streaming row in this goal runs.
 *
 * `seedCatchupChannel` imported from `../streaming/helpers`: it is
 * catch-up seeding, not streaming-specific — G8 put it there because its
 * only consumers were there. Importing across the project directory is safe
 * (`testMatch` never collects `helpers.ts`); copying it here is how the two
 * copies drift.
 */
test('every catch-up precondition fails closed without reaching the provider', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const token = await api.freshAccessToken();
  const auth = { Authorization: `Bearer ${token}` };
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  // 1. A channel that is not catch-up at all. `get_channel_catchup_streams`
  //    returns [] on `not channel.is_catchup` before it queries anything
  //    (apps/channels/utils.py:141-142).
  const plain = await seed.channel();
  const notCatchup = await request.get(
    `/proxy/catchup/${plain.uuid}?start=${encodeURIComponent(start)}`,
    { headers: auth, maxRedirects: 0 }
  );
  expect(notCatchup.status()).toBe(400);
  expect(await notCatchup.text()).toContain('Timeshift not supported for this channel');

  // 2. An unparseable timestamp. `parse_catchup_timestamp` returns None and
  //    `_serve_catchup` bails at views.py:363-364 — before
  //    `get_channel_catchup_streams`, so this is reachable on a channel that
  //    IS catch-up and is a genuinely different link in the chain.
  const badTs = await request.get(
    `/proxy/catchup/${channel.uuid}?start=not-a-time`,
    { headers: auth, maxRedirects: 0 }
  );
  expect(badTs.status()).toBe(400);
  expect(await badTs.text()).toContain('Invalid timestamp');

  // 3. No `start` at all. Caught one level up, in `catchup_proxy` itself
  //    (views.py:335-336), with a different message — which is the only
  //    reason a caller can tell "you sent nothing" apart from "you sent
  //    rubbish".
  const noTs = await request.get(`/proxy/catchup/${channel.uuid}`, {
    headers: auth,
    maxRedirects: 0,
  });
  expect(noTs.status()).toBe(400);
  expect(await noTs.text()).toContain('Missing start parameter');

  // 4. LAST, because it breaks the account for everything above. Deactivating
  //    the M3U account makes `get_channel_catchup_streams`'s
  //    `m3u_account__is_active=True` filter (apps/channels/utils.py:145)
  //    return [] for a channel whose own `is_catchup` is still True — and
  //    the response is BYTE-IDENTICAL to case 1's. That is the finding, not
  //    an accident: two unrelated misconfigurations are indistinguishable to
  //    a client, and a support report saying "Timeshift not supported for
  //    this channel" identifies neither.
  const accounts = await api.json<{ id: number; name: string }[] | { results: { id: number; name: string }[] }>(
    await api.get('/api/m3u/accounts/'),
    'M3U accounts'
  );
  const rows = Array.isArray(accounts) ? accounts : accounts.results;
  const account = rows.find((a) => a.name.includes(scenario.username!.replace(/-user$/, '')));
  expect(account, 'the account seedCatchupChannel created').toBeDefined();
  await api.patch(`/api/m3u/accounts/${account!.id}/`, { is_active: false });

  const deactivated = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}`,
    { headers: auth, maxRedirects: 0 }
  );
  expect(deactivated.status()).toBe(400);
  expect(await deactivated.text()).toContain('Timeshift not supported for this channel');

  // THE POINT OF THE ROW. Every one of the four returned before any provider
  // contact, so a break anywhere in the five-link chain can never reach —
  // or be mistaken for a failure of — the upstream.
  expect(
    catchupRequests(await upstream.log(scenario)),
    'a precondition failure must never reach the provider'
  ).toHaveLength(0);
});
```

- [ ] **Step 2: Resolve the account lookup honestly**

The account-finding code above is the one loose end: `seedCatchupChannel` creates the account internally and does not return it. Two acceptable resolutions, in order of preference:

1. **Preferred.** Do not use `seedCatchupChannel` for case 4. Inline the four steps it performs (scenario → `seed.xcAccount` → `waitFor.m3uRefreshComplete` → locate the ingested `Stream` by `${prefix}-ch` → `seed.channel({ streams: [id] })` → re-read the channel and assert `is_catchup`), keeping the account handle. Copy the sequence from `seedCatchupChannel` (`e2e/tests/streaming/helpers.ts`) — it is ~30 lines and this test needs its `account.id`.
2. If you keep `seedCatchupChannel`, locate the account by `M3UAccount.username === scenario.username` (`seed.xcAccount` puts the scenario's credentials on the model's own fields) rather than by name substring. `M3uAccount` in `e2e/fixtures/types.ts` types `username`.

**Do not** widen `CatchupChannelSetup` to return the account — that edits `e2e/tests/streaming/helpers.ts`, which Task 1 owns, and would make this task collide with Task 7's file. Whichever resolution you take, say which in the task report.

- [ ] **Step 3: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded catchup-preconditions` — expect 1 passed.

**Mutation check:** temporarily change case 2's `start=not-a-time` to the valid `start` and re-run. The test must now fail on the empty-log assertion, because a valid request *does* reach the provider. That is what proves the final assertion is load-bearing rather than vacuous. Restore afterwards, and report the result.

- [ ] **Step 4: Commit**

`test(e2e): prove catch-up preconditions fail closed with no upstream contact`

---

### Task 4: Row 4 — the native session API is the fourth surface into the same code

Implements inventory row 4 (a **new** COVERAGE row) and the first half of the existing COVERAGE Gap row *"the recommended `POST /api/catchup/sessions/` branch of `_serve_catchup` is unexercised"*. The playback half — actually opening the minted `playback_url` and reading bytes — is Task 6 Step 5; this task must not attempt it (the `seeded` project's timeout is 30s and this row is meant to be a fast contract test).

**Files:**
- Create: `e2e/tests/seeded/catchup-session-api.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect` from `'../../fixtures'`; `seedCatchupChannel`, `catchupTimestamp` from `'../streaming/helpers'`; fixtures `upstream`, `seed`, `api`, `waitFor`, `asPrincipal`.
- Produces: nothing shared.

**Verified literals:**
- Route: `POST /api/catchup/sessions/` — `apps/api/urls.py:17` mounts `apps.timeshift.api_urls` under `api/catchup/`, whose `sessions/` path is `CatchupSessionCreateAPIView` (`apps/timeshift/api_urls.py`).
- `permission_classes = [IsStandardUser]` (`apps/timeshift/api_views.py:70`). `IsStandardUser` requires `user_level >= User.UserLevel.STANDARD` (1) (`apps/accounts/permissions.py:15-20`), so the bootstrap admin (level 10) satisfies it and **this task spends zero logins** — `asPrincipal('streamer')` is a pre-provisioned token, not a login.
- Request body: `{ channel_uuid: <uuid>, start: <string>, duration?: <int 1..480> }` (`CatchupSessionCreateSerializer`, `api_views.py:30-49`; `MAX_DURATION_MINUTES = 480`).
- 201 body: `{ session_id, playback_url, expires_at, channel_uuid, start, duration }` (`CatchupSessionResponseSerializer`, `:52-64`).
- `playback_url = f"/proxy/catchup/{channel.uuid}?session_id={session_id}"` (`apps/timeshift/sessions.py:67`) — **relative, no origin, no trailing slash on the route**.
- `expires_at = now + HANDSHAKE_TTL_SECONDS`, `HANDSHAKE_TTL_SECONDS = 60` (`sessions.py:31`, `:64-66`). Unix **seconds**.
- Non-catch-up channel → `400 {"error": "Catch-up not supported for this channel"}` (`api_views.py:141-145`). Note there are **two** paths to that identical body — `not channel.is_catchup` and an empty `get_channel_catchup_streams` (`:141-151`) — the same indistinguishability Task 3 records.
- Streamer (level 0) → **403**, from the permission class, before `post()` runs.

- [ ] **Step 1: Write the file**

```ts
import { test, expect } from '../../fixtures';
import { catchupTimestamp, seedCatchupChannel } from '../streaming/helpers';

/**
 * `POST /api/catchup/sessions/` — the surface the endpoint's own OpenAPI
 * description calls **recommended** for native players, and the fourth
 * entry point into the same `_serve_catchup` (`apps/timeshift/views.py:344`).
 * Until now nothing drove it: both G8 catch-up proofs and both root XC
 * routes reach `_serve_catchup` without ever minting a session
 * (`e2e/COVERAGE.md`'s Catch-up gap row).
 *
 * This file proves the mint contract. The playback half — opening the
 * returned `playback_url` with no Authorization header and reading TS bytes
 * — is `e2e/tests/streaming/catchup-proxy-mode.spec.ts`, because it needs a
 * live provider and the 300s `streaming` budget.
 *
 * Zero logins: the bootstrap admin is `user_level: 10`, which satisfies
 * `IsStandardUser` (`apps/accounts/permissions.py:15-20`), and
 * `asPrincipal('streamer')` hands back a pre-provisioned token pair.
 */
test('POST /api/catchup/sessions/ mints a playable session for a catch-up channel', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  const before = Math.floor(Date.now() / 1000);
  const res = await api.post('/api/catchup/sessions/', {
    channel_uuid: channel.uuid,
    start,
    duration: 60,
  });
  expect(res.status()).toBe(201);
  const body = await api.json<{
    session_id: string;
    playback_url: string;
    expires_at: number;
    channel_uuid: string;
    start: string;
    duration: number | null;
  }>(res, 'catch-up session');

  expect(body.session_id).toBeTruthy();
  // Asserted as one exact string, not by parts: this URL is the entire
  // contract with a native player, and `create_catchup_session` builds it by
  // interpolation (apps/timeshift/sessions.py:67), so a change to the route
  // or the parameter name would otherwise pass here and fail in the player.
  expect(body.playback_url).toBe(`/proxy/catchup/${channel.uuid}?session_id=${body.session_id}`);
  expect(body.channel_uuid).toBe(channel.uuid);
  expect(body.start).toBe(start);
  expect(body.duration).toBe(60);

  // HANDSHAKE_TTL_SECONDS is 60 (apps/timeshift/sessions.py:31). Bounded on
  // both sides: a floor alone would pass an `expires_at` of next year, which
  // would mean the handshake deadline the description advertises does not
  // exist.
  expect(body.expires_at).toBeGreaterThan(before);
  expect(body.expires_at).toBeLessThanOrEqual(before + 60 + 5);
});

test('POST /api/catchup/sessions/ refuses a channel with no catch-up', async ({ seed, api }) => {
  const plain = await seed.channel();

  const res = await api.post('/api/catchup/sessions/', {
    channel_uuid: plain.uuid,
    start: catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000)),
  });
  expect(res.status()).toBe(400);
  expect(await res.text()).toContain('Catch-up not supported for this channel');
});

test('POST /api/catchup/sessions/ is closed to a Streamer', async ({
  upstream,
  seed,
  api,
  waitFor,
  asPrincipal,
}) => {
  const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const streamer = await asPrincipal('streamer');

  // 403, not 401: the token is valid, `IsStandardUser` simply refuses a
  // user_level below 1 (apps/accounts/permissions.py:15-20), and DRF answers
  // an authenticated-but-unpermitted request with 403.
  const res = await streamer.post('/api/catchup/sessions/', {
    channel_uuid: channel.uuid,
    start: catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000)),
  });
  expect(res.status()).toBe(403);
});
```

- [ ] **Step 2: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded catchup-session-api` — expect 3 passed.

If test 1 fails with 400 rather than 201, the channel is not catch-up — read `seedCatchupChannel`'s throw message, which names the five preconditions, before suspecting the API.

- [ ] **Step 3: Commit**

`test(e2e): prove the native catch-up session API mints a playable session`

---

### Task 5: Row 5 — the generated M3U advertises no catch-up (known-bug), and the XC surface does

Implements inventory row 5 and spec **D12**. **The ruling is already made — do not reopen it.** The plan's job is to write it, not to relitigate it.

**Why it is a defect, in the order the issue body must carry it:**

1. **Dispatcharr reads the attribute family it does not write.** `apps/m3u/tasks.py:1383-1388` parses `tv_archive` and `tv_archive_duration` out of an ingested playlist's `#EXTINF` attributes and sets `Stream.is_catchup` from them. The reader exists; the emitter (`apps/output/views.py:298-306`) has no corresponding branch at all. A codebase that consumes a signal it never produces is asymmetric with itself.
2. **There is no expression of intent anywhere.** No comment, no setting, no branch says "M3U clients do not get catch-up". By contrast the XC emitter has an explicit `catchup_allowed` gate (`apps/output/views.py:727`) — the author thought about *who* may see catch-up advertised, on the surface where it is advertised at all.
3. **The capability is complete and routed.** `dispatcharr/urls.py:45-49` and `:50-54` serve both catch-up layouts today.
4. **The consequence is a silent dead end.** An M3U-only client (Kodi/IPTV Simple, VLC, TiviMate on an M3U profile) shows no catch-up affordance for a channel with a working archive. The user's only signal is absence.

**Why the test is convention-agnostic, and why that is not a dodge.** The de-facto M3U conventions are three and mutually incompatible: `catchup="default"` with a `catchup-source=` URL template, `catchup="xc"`, and `catchup="append"` with a query suffix. Dispatcharr serves **two** upstream layouts, so which to advertise is a product decision nobody has made. A `test.fail()` pinning one convention would go green **the wrong way** if the maintainer picked another — the exact failure mode `test.fail()` exists to avoid. So the assertion is: *some* `catchup` attribute is present, and a `catchup-days` equal to `Channel.catchup_days`. Both hold under all three conventions; neither constrains the choice. **Do not add `catchup-source` to the assertion.**

**Files:**
- Create: `e2e/tests/seeded/catchup-m3u-advertisement.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect` from `'../../fixtures'`; `seedXcUser` from `'../streaming/helpers'`; fixtures `seed`, `request`.
- Produces: nothing shared. One GitHub issue.

**Verified literals:**
- `#EXTINF` is built at `apps/output/views.py:304-306` and carries exactly `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, an optional `tvc-guide-stationid`, and `group-title`, then `,<name>`. Nothing else.
- `/output/m3u` needs no authentication: `m3u_endpoint` (`apps/output/views.py:56-79`) gates only on `network_access_allowed(request, "M3U_EPG")` and is reached with `user=None`.
- `is_catchup` and `catchup_days` are **writable** on `ChannelSerializer` (`apps/channels/serializers.py:440-469`, no `read_only_fields` covering them) and are in `ChannelOverrides` (`e2e/fixtures/types.ts`). So this row needs **no XC ingest and no provider at all** — `seed.channel({ is_catchup: true, catchup_days: 7 })` is sufficient, and with `streams: []` no `ChannelStream` row exists, so `update_channel_catchup_fields` never fires to overwrite it.
- The XC half: `xc_get_user` (`apps/output/views.py:355-376`) authenticates `player_api.php` from `?username=` + `?password=` against `custom_properties["xc_password"]`. `_xc_channel_entry` sets `tv_archive = 1` and `tv_archive_duration = channel.catchup_days` when `catchup_allowed and channel.is_catchup` (`:727-732`), and emits both keys unconditionally (`:749`, `:751`).

- [ ] **Step 1: Write the file**

```ts
import { test, expect } from '../../fixtures';
import { seedXcUser } from '../streaming/helpers';

/**
 * The generated M3U advertises no catch-up, and the XC catalogue does. The
 * asymmetry is the evidence, so both halves live here — one failing, one
 * passing.
 *
 * Placement: the *surface* is `/output/m3u`, which is G5's, but the fact
 * that makes this a defect is catch-up's. G5 owns "the M3U parses and every
 * URL is well-formed"; G10 owns "the M3U advertises catch-up". Keeping this
 * out of G5's own `/output/m3u` spec is deliberate.
 *
 * No provider, no ingest: `is_catchup`/`catchup_days` are writable on
 * `ChannelSerializer` (`apps/channels/serializers.py:440-469`), and with no
 * streams wired there is no `ChannelStream` row for
 * `update_channel_catchup_fields` (`apps/channels/signals.py:393-407`) to
 * roll a `false` back over them.
 */
const CATCHUP_DAYS = 7;

function extinfFor(playlist: string, channelName: string): string {
  const line = playlist
    .split('\n')
    .find((l) => l.startsWith('#EXTINF:') && l.trimEnd().endsWith(`,${channelName}`));
  expect(line, `an #EXTINF line for "${channelName}" in /output/m3u`).toBeDefined();
  return line!;
}

test.fail(
  'the generated M3U advertises catch-up for a catch-up channel',
  async ({ seed, request }) => {
    // KNOWN BUG — see the issue linked in COVERAGE.md. This assertion is the
    // CORRECT behaviour; it fails today. Never invert it to assert the bug:
    // a test.fail() that asserts the buggy behaviour goes green the wrong way
    // and locks the defect in.
    //
    // Convention-agnostic ON PURPOSE. The three de-facto M3U catch-up
    // conventions — `catchup="default"` + `catchup-source=`, `catchup="xc"`,
    // and `catchup="append"` — are mutually incompatible, and Dispatcharr
    // serves two upstream layouts, so which one it should advertise is an
    // unmade product decision. Asserting only that SOME `catchup` attribute
    // and a matching `catchup-days` are present holds under all three and
    // constrains none of them. Do not add `catchup-source` here.
    const channel = await seed.channel({ is_catchup: true, catchup_days: CATCHUP_DAYS });

    const res = await request.get('/output/m3u');
    expect(res.status()).toBe(200);
    const extinf = extinfFor(await res.text(), channel.name);

    expect(extinf, 'an #EXTINF for a catch-up channel should carry a catchup attribute').toMatch(
      /\scatchup="[^"]+"/
    );
    expect(extinf).toContain(`catchup-days="${CATCHUP_DAYS}"`);
  }
);

test('the XC catalogue does advertise the same channel as catch-up', async ({ seed, request }) => {
  // The other half of the asymmetry, and the reason the row above is a
  // defect rather than a preference: the same channel, the same instant, on
  // the surface Dispatcharr DOES advertise catch-up on. The XC emitter even
  // has a considered `catchup_allowed` gate (apps/output/views.py:727) — the
  // author thought about who may see catch-up advertised. The M3U builder
  // (`:298-306`) does not participate at all.
  const channel = await seed.channel({ is_catchup: true, catchup_days: CATCHUP_DAYS });
  const xcUser = await seedXcUser(seed);

  const res = await request.get(
    `/player_api.php?username=${encodeURIComponent(xcUser.username)}` +
      `&password=${encodeURIComponent(xcUser.xcPassword)}&action=get_live_streams`
  );
  expect(res.status()).toBe(200);

  const streams = (await res.json()) as { stream_id: number; tv_archive: number; tv_archive_duration: number }[];
  const entry = streams.find((s) => s.stream_id === channel.id);
  expect(entry, `channel ${channel.id} in get_live_streams`).toBeDefined();
  expect(entry!.tv_archive).toBe(1);
  expect(entry!.tv_archive_duration).toBe(CATCHUP_DAYS);
});
```

- [ ] **Step 2: File the issue**

```
gh issue create --repo D10Scot/Dispatcharr --label needs-triage \
  --title "Generated M3U advertises no catchup= attribute, so M3U-only clients cannot discover working catch-up" \
  --body "$(cat <<'EOF'
`/output/m3u`'s `#EXTINF` carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, an optional `tvc-guide-stationid` and `group-title`, and nothing else (`apps/output/views.py:298-306`). There is no `catchup=`, `catchup-source=`, `catchup-days=` or `timeshift=` attribute, so an M3U-only client (Kodi/IPTV Simple, VLC, TiviMate on an M3U profile) shows no catch-up affordance for a channel with `is_catchup: true` and a working archive.

Why this reads as an omission rather than a decision:

1. Dispatcharr **reads** the attribute family it does not write. `apps/m3u/tasks.py:1383-1388` parses `tv_archive` and `tv_archive_duration` out of an ingested playlist's `#EXTINF` attributes and sets `Stream.is_catchup`/`catchup_days` from them. The reader exists; the emitter has no corresponding branch at all.
2. There is no expression of intent anywhere — no comment, no setting, no branch saying "M3U clients do not get catch-up". The XC emitter, by contrast, has an explicit `catchup_allowed` gate (`apps/output/views.py:727`): someone thought about *who* may see catch-up advertised, on the surface where it is advertised at all.
3. The capability is complete and routed. `dispatcharr/urls.py:45-49` and `:50-54` serve both catch-up layouts today. This is not a feature request for catch-up; it is the one line that tells a client the catch-up already served exists.
4. The consequence is a silent dead end. The user's only signal is absence.

**What to decide before fixing.** Three de-facto M3U conventions exist and are mutually incompatible:

- `catchup="default"` with a `catchup-source="<url template>"` carrying `${start}`/`${offset}` placeholders
- `catchup="xc"` — the client builds the Xtream `timeshift.php`/`/timeshift/` URL itself
- `catchup="append"` with a query suffix appended to the stream URL

Dispatcharr serves **two** upstream layouts (`build_timeshift_url_format_a`/`_b`, `apps/timeshift/helpers.py:412-433`), so which convention to advertise is a product decision nobody has made. Whoever fixes this is choosing, not guessing.

Pinned by `e2e/tests/seeded/catchup-m3u-advertisement.spec.ts`, with a deliberately **convention-agnostic** `test.fail()`: it asserts only that some `catchup` attribute and a matching `catchup-days` are present, which holds under all three conventions and constrains none of them. That test will start failing (as an unexpected pass) once this is fixed — remove the `test.fail()` then, and consider tightening it to whichever convention was chosen.

Found by the G10 E2E goal (`docs/superpowers/specs/2026-08-30-e2e-catchup-timeshift-design.md`, D12).
EOF
)"
```

Record the issue number; Task 10 puts it in `COVERAGE.md`, and you must also put it in the `test.fail()` block's first comment line, replacing *"see the issue linked in COVERAGE.md"* with the actual `#NN`.

- [ ] **Step 3: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded catchup-m3u-advertisement` — expect **1 passed, 1 expected failure**. A `test.fail()` reported as *passed* means the defect is fixed (or the assertion is wrong) and is itself a CI failure; investigate rather than editing the assertion.

- [ ] **Step 4: Commit**

`test(e2e): pin the missing M3U catchup attribute against the XC surface that has it`

---

### Task 6: Rows 6, 7, 8 — proxy mode end to end, both root entry points, session playback, and the adult-content bug

Implements inventory rows 6, 7 and 8, plus the playback half of the COVERAGE Gap row on the session API. Four tests, one file, one issue.

**Files:**
- Create: `e2e/tests/streaming/catchup-proxy-mode.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect`, `expectTsAligned` from `'../../fixtures'`; `seedCatchupChannel`, `seedXcUser`, `catchupTimestamp`, `catchupRequests`, `newStreamClient` from `'./helpers'`; fixtures `upstream`, `seed`, `api`, `waitFor`, `streamClient`, `request`, `baseURL`.
- Produces: nothing shared. One GitHub issue.

**Verified literals:**
- `DURATION_BUFFER_MINUTES = 5`, cap `MAX_DURATION_MINUTES = 480` (`apps/timeshift/helpers.py:25-26`). `client_duration_to_window` (`:197-222`) adds the buffer to any usable positive integer hint. **A client asking `60` produces a provider request for `65`.** Assert the derived value, never the client's own.
- `seedCatchupChannel` waits for the account profile to carry `server_info.timezone === 'UTC'`, and `convert_timestamp_to_provider_tz` returns its input unchanged for exactly `"UTC"` (`helpers.py:145-146`). So an unchanged `start` in the log is a real assertion here, not an accident.
- Session mint: with no `session_id` and no pool match, a non-Redirect default profile returns **301** to the same path with `session_id` appended, preserving the existing query (`_redirect_with_session`, `views.py:1594-1602`). `streamClient.open` follows it by default (`redirect: 'follow'`). Playwright's `request.get` follows too, unless `maxRedirects: 0`.
- The 301 happens **before** any provider contact, so an unfaulted single-candidate walk logs exactly **one** catch-up request.
- Root routes: `/timeshift/<username>/<password>/<duration>/<start>/<Channel.id>.ts` and `/streaming/timeshift.php?username=&password=&stream=<Channel.id>&start=&duration=` (`dispatcharr/urls.py:45-54`). Both authenticate through `_authenticate_user` (`views.py:758-768`), which reads `User.custom_properties['xc_password']` and compares it with `hmac.compare_digest` — **no JWT, no login spent** (D7). `seedXcUser` creates exactly that user.
- `hide_adult_content` is applied at twelve sites across `apps/output/`, `apps/epg/`, `apps/channels/` and `apps/vod/` — including `apps/output/views.py:148-160`, the XC listing filter — and at **none** under `apps/timeshift/`. `_user_can_access_channel` (`views.py:771-786`) checks `user_level` and Channel Profile membership only. That filter also only applies to `user.user_level < 10` (`:140`), so the adult-content test's user must be **Standard (1)**, not admin.

- [ ] **Step 1: File header**

```ts
import { test, expect, expectTsAligned } from '../../fixtures';
import {
  catchupRequests,
  catchupTimestamp,
  newStreamClient,
  seedCatchupChannel,
  seedXcUser,
} from './helpers';

/**
 * Catch-up proxy mode, end to end, across every entry point that reaches
 * `_serve_catchup` (`apps/timeshift/views.py:344`).
 *
 * THE LIMIT THAT GOVERNS EVERY ASSERTION IN THIS FILE. G8's archive is not
 * time-addressable: the catch-up routes serve the same looping TS whatever
 * `start` they are given (`e2e-upstream/src/xc/router.ts`). So every time
 * assertion below reads the URL Dispatcharr **sent**, out of the provider's
 * scenario log, and never the bytes that came back. These tests prove the
 * right moment was ASKED FOR. They do not prove Dispatcharr seeks to it, and
 * a green run here is not evidence that it does.
 *
 * `catchup-path-layout.spec.ts` (G8) already drives the root PATH route as a
 * plumbing proof. This file goes past it: an exact request count instead of
 * `> 0`, the root QUERY route it never touched, the minted-session playback
 * nothing has driven, and the `hide_adult_content` hole.
 */
```

- [ ] **Step 2: Row 6 — the native route, one request, every parameter**

```ts
test('proxy mode streams a catch-up programme and asks the provider for exactly it', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const token = await api.freshAccessToken();

  await streamClient.open(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const asked = catchupRequests(await upstream.log(scenario));

  // EXACTLY one. G8's plumbing proof settled for `> 0`; the exact count is
  // what rules out a retry loop, a duplicated walk, or a second connection
  // opened behind the first. The session-minting 301 (views.py:1594-1602)
  // never reaches the provider, so one client request is one upstream
  // request.
  expect(asked).toHaveLength(1);
  expect(asked[0].layout).toBe('path'); // candidate 0 wins unfaulted
  expect(asked[0].status).toBe(200);
  expect(asked[0].username).toBe(scenario.username);
  expect(asked[0].password).toBe(scenario.password);

  // The PROVIDER's stream id — `Stream.custom_properties['stream_id']`
  // (views.py:1641), which `StreamSerializer` never exposes, so the log is
  // the only place it is observable at all (COVERAGE.md's Catch-up gap row).
  expect(asked[0].streamId).toBe(String(providerStreamId));

  // 60 requested + DURATION_BUFFER_MINUTES (5) = 65
  // (apps/timeshift/helpers.py:25, :197-222). Assert the derived value: 60
  // would pass even if the pad were silently dropped, and the pad is there
  // because provider archives lag live.
  expect(asked[0].duration).toBe('65');

  // Unchanged, because the scenario declares server_info.timezone "UTC" and
  // `convert_timestamp_to_provider_tz` returns its input untouched for
  // exactly that value (helpers.py:145-146) — `seedCatchupChannel` already
  // waited for it to land on the account profile, so this is a real
  // assertion and not a coincidence of a null timezone behaving the same
  // way.
  expect(asked[0].start).toBe(start);

  // This proves the right moment was asked for. It does not prove
  // Dispatcharr seeks to it: the fake archive serves the same loop whatever
  // `start` it is given.
});
```

- [ ] **Step 3: Row 7 — both root XC entry points, and the layout that does not matter**

```ts
test('both root XC entry points reach the same cascade, whatever layout the client used', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
  baseURL,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  // No login spent: `_authenticate_user` (views.py:758-768) compares
  // `custom_properties['xc_password']` with hmac.compare_digest, so the root
  // routes need no JWT at all. The suite's whole login budget is 3/minute
  // across every worker and project.
  const xcUser = await seedXcUser(seed);
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  // PATH layout: /timeshift/<user>/<pass>/<duration>/<start>/<Channel.id>.ts
  // Channel.id, the numeric PK — unlike /proxy/catchup/, which is UUID-keyed.
  await streamClient.open(
    `/timeshift/${xcUser.username}/${xcUser.xcPassword}/60/${start}/${channel.id}.ts`
  );
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  // QUERY layout: the surface nothing in this repo has ever driven.
  const second = newStreamClient(baseURL!);
  await second.open(
    `/streaming/timeshift.php?username=${encodeURIComponent(xcUser.username)}` +
      `&password=${encodeURIComponent(xcUser.xcPassword)}` +
      `&stream=${channel.id}&start=${encodeURIComponent(start)}&duration=60`
  );
  expectTsAligned(await second.readPackets(20));
  await second.close();

  const asked = catchupRequests(await upstream.log(scenario));
  expect(asked).toHaveLength(2);

  for (const [i, entry] of asked.entries()) {
    // BOTH are `path`, and that is the point of this row rather than an
    // oversight. `client_timeshift_url_layout` (helpers.py:436-446) is read
    // ONLY by `_select_catchup_redirect_url` (views.py:413-419, :1709);
    // `_attempt_timeshift_stream` calls `build_timeshift_candidate_urls`
    // unconditionally (views.py:2673), so proxy mode walks PATH candidates
    // first no matter which shape the client arrived in. The client's layout
    // changes the REDIRECT (see catchup-redirect.spec.ts) and nothing else.
    expect(entry.layout, `request ${i} layout`).toBe('path');
    expect(entry.status).toBe(200);
    expect(entry.streamId).toBe(String(providerStreamId));
    expect(entry.duration).toBe('65');
    expect(entry.start).toBe(start);
  }

  // Same caveat as the row above: the right moment was asked for, twice.
  // Neither request proves Dispatcharr seeks to it — the fake archive serves
  // the same loop whatever `start` it is given.
});
```

- [ ] **Step 4: Row 8 — `hide_adult_content` is not applied on the catch-up path (known-bug)**

```ts
test.fail(
  'an adult channel a user cannot list is also refused on the catch-up path',
  async ({ upstream, seed, api, waitFor, request }) => {
    // KNOWN BUG — issue #NN. `hide_adult_content` is applied at twelve sites
    // across apps/output/, apps/epg/, apps/channels/ and apps/vod/, and at
    // NONE under apps/timeshift/. `_user_can_access_channel`
    // (views.py:771-786) checks user_level and Channel Profile membership
    // only. So a Standard user who cannot see an adult channel in any
    // listing can still stream its archive.
    //
    // The assertion below is the CORRECT behaviour and fails today. It is
    // deliberately status-agnostic above 400: whether the fix answers 403
    // (matching `_user_can_access_channel`'s existing refusal) or 404 is an
    // unmade choice, and pinning one would let the other go green the wrong
    // way.
    const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
    await api.patch(`/api/channels/channels/${channel.id}/`, { is_adult: true });

    // user_level 1, NOT the helper's default 10: the hide_adult_content
    // filter only applies below admin (apps/output/views.py:140).
    const viewer = await seedXcUser(seed, {
      user_level: 1,
      custom_properties: { hide_adult_content: true },
    });
    const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

    // PASSES: the listing surface does hide it (apps/output/views.py:148-160).
    const listing = await request.get(
      `/player_api.php?username=${encodeURIComponent(viewer.username)}` +
        `&password=${encodeURIComponent(viewer.xcPassword)}&action=get_live_streams`
    );
    expect(listing.status()).toBe(200);
    const streams = (await listing.json()) as { stream_id: number }[];
    expect(
      streams.some((s) => s.stream_id === channel.id),
      'an adult channel must not appear in a hide_adult_content listing'
    ).toBe(false);

    // FAILS TODAY: the same channel streams. `maxRedirects: 0` so the
    // session-minting 301 is observed rather than followed — today's answer
    // is that 301, which is < 400 and therefore not a refusal.
    const play = await request.get(
      `/timeshift/${viewer.username}/${viewer.xcPassword}/60/${start}/${channel.id}.ts`,
      { maxRedirects: 0 }
    );
    expect(
      play.status(),
      'a channel hidden from this user must not be streamable by them'
    ).toBeGreaterThanOrEqual(400);
  }
);
```

- [ ] **Step 5: The minted session plays back**

Closes the COVERAGE Gap row Task 4 opened the other half of.

```ts
test('a session minted through the API plays back with no credentials of its own', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  const minted = await api.json<{ session_id: string; playback_url: string }>(
    await api.post('/api/catchup/sessions/', {
      channel_uuid: channel.uuid,
      start,
      duration: 60,
    }),
    'catch-up session'
  );

  // NO Authorization header. That is the whole point of the recommended
  // flow: the player is headerless, and `resolve_catchup_playback`
  // (apps/timeshift/sessions.py) resolves the user, the start and the
  // duration off the session (views.py:302-319). Open it promptly —
  // HANDSHAKE_TTL_SECONDS is 60 (sessions.py:31).
  await streamClient.open(minted.playback_url);
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const asked = catchupRequests(await upstream.log(scenario));
  expect(asked).toHaveLength(1);
  expect(asked[0].streamId).toBe(String(providerStreamId));
  expect(asked[0].start).toBe(start);
  // The session's stored duration, padded the same way a URL hint is
  // (views.py:318-319 → resolve_catchup_duration, helpers.py:224-233).
  expect(asked[0].duration).toBe('65');

  // Once more, because this row is the one a native-app author will read:
  // this proves the right moment was asked for. It does not prove
  // Dispatcharr seeks to it.
});
```

- [ ] **Step 6: File the C1 issue**

```
gh issue create --repo D10Scot/Dispatcharr --label needs-triage \
  --title "hide_adult_content is not applied on the catch-up path: an adult channel is unlistable but still streamable" \
  --body "$(cat <<'EOF'
`custom_properties.hide_adult_content` filters `is_adult` channels out of every listing surface — the filter appears at twelve sites across `apps/output/`, `apps/epg/`, `apps/channels/` and `apps/vod/`, including the XC live listing at `apps/output/views.py:148-160` — and at **none** under `apps/timeshift/`.

`_user_can_access_channel` (`apps/timeshift/views.py:771-786`), the only authorization check on the catch-up path, tests `user_level` and Channel Profile membership. It does not read `hide_adult_content`.

Result: a Standard user with `hide_adult_content: true` cannot see an adult channel in `player_api.php?action=get_live_streams`, in `/output/m3u`, or in any other listing — and can still stream its archive through `/timeshift/<user>/<pass>/<duration>/<start>/<Channel.id>.ts`, `/streaming/timeshift.php`, `/proxy/catchup/<uuid>` or a session minted from `POST /api/catchup/sessions/`, all four of which converge on `_serve_catchup` (`apps/timeshift/views.py:344`).

The channel UUID or id has to come from somewhere, so this is not a discovery bypass on its own — but "hidden" is not a security boundary the product otherwise treats as advisory, and every other surface enforces it.

Note the shape is the same as the already-recorded live-path defect: `hide_adult_content` is applied in listing paths but not in `apps/proxy/live_proxy/views.py`, `apps/timeshift/views.py` or `apps/hdhr/api_views.py` (see `CLAUDE.md`, "Known defects and traps"). A fix should probably cover all three rather than catch-up alone.

Undecided and worth deciding as part of the fix: whether the refusal is `403` (matching `_user_can_access_channel`'s existing `HttpResponseForbidden("Access denied")`) or `404`. Pinned by `e2e/tests/streaming/catchup-proxy-mode.spec.ts` with a `test.fail()` asserting only `status >= 400`, deliberately, so either choice satisfies it.

Found by the G10 E2E goal (`docs/superpowers/specs/2026-08-30-e2e-catchup-timeshift-design.md`, defect C1).
EOF
)"
```

Put the returned number in place of `#NN` in Step 4's comment.

- [ ] **Step 7: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming catchup-proxy-mode` — expect **3 passed, 1 expected failure**.

If Step 3's QUERY-layout open fails with 400 `Missing required parameters`, one of the four query params is absent or empty — `timeshift_proxy_query` (`views.py:143-149`) requires all of `username`, `password`, `start`, `stream` to be truthy.

- [ ] **Step 8: Commit**

`test(e2e): drive catch-up proxy mode from all four entry points and pin the adult-content hole`

---

### Task 7: Rows 9, 10, 11 — the candidate cascade's four shapes, its per-account cache, and its three failure classes

Implements inventory rows 9, 10 and 11. **This is the long pole and the reason the goal exists**: the roadmap calls the cascade "the part most likely to be wrong and the part nothing observes today", and this is the only place in the programme where the real builder, `requests`' requoting, a strict provider parser and a live per-account Redis cache meet.

**This task APPENDS to `e2e/tests/streaming/catchup-cascade.spec.ts`, which G8 created. Do not modify or delete G8's existing test** — it is the plumbing proof that PATH-blocked falls through to QUERY, and the four tests below are the behaviour proofs on top of it. Read its header before writing; you are extending its file-level story.

**Row 9 is re-scoped, and here is exactly why.** G8's landed test already asserts three PATH 404s carrying the colon-dash, underscore and colon-seconds shapes by literal value, the winning QUERY attempt carrying the underscore shape, the total count of four, and the arrival order. Spec D3 forbids duplicating it. What G8 **cannot** reach is the fourth shape — `%Y-%m-%d %H:%M:%S`, QUERY candidate 4, the SQL form with a literal space — because `catchup-layout-404 { layout: 'path' }` lets candidate 3 win and the walk stops there, and blocking both layouts is rejected by design at the provider's door (`parseFaultRequest`, `e2e-upstream/src/faults.ts`: *"a layout-less variant is exactly `not-found`"*). Only the `not-found` fault forces all seven. So **row 9 and row 11's `not-found` arm become one test** that pins the entire seven-candidate sequence.

**Files:**
- Modify: `e2e/tests/streaming/catchup-cascade.spec.ts` (append only)

**Interfaces:**
- Consumes: `test`, `expect`, `expectTsAligned` from `'../../fixtures'`; `seedCatchupChannel`, `catchupTimestamp`, `catchupRequests` from `'./helpers'`; fixtures `upstream`, `seed`, `api`, `waitFor`, `streamClient`, `request`. The file already imports `test`, `expect`, `catchupTimestamp` and `seedCatchupChannel` — extend the existing import statements rather than adding new ones.
- Produces: nothing shared.

- [ ] **Step 1: A shared shape helper, local to this file**

Every test below needs the four `strftime` outputs for one instant. Add near the top, below G8's existing imports:

```ts
/**
 * The four timestamp shapes `build_timeshift_candidate_urls` emits across its
 * seven candidates (`apps/timeshift/helpers.py:483-498`), derived here from
 * the same instant the request itself used — not re-parsed from a response —
 * so a product change that reorders or collapses the candidate list fails
 * these tests instead of quietly passing them.
 *
 * Seconds are always "00": `catchupTimestamp` emits the colon-dash shape
 * with no seconds, and `normalize_catchup_timestamp_input` defaults an
 * absent second to "00" (`helpers.py:87`) before any shape is derived.
 * `catchup-provider-timezone.spec.ts` is where a non-zero second is driven.
 */
function candidateShapes(instant: Date) {
  const pad = (n: number): string => String(n).padStart(2, '0');
  const d = `${instant.getUTCFullYear()}-${pad(instant.getUTCMonth() + 1)}-${pad(instant.getUTCDate())}`;
  const h = pad(instant.getUTCHours());
  const mi = pad(instant.getUTCMinutes());
  return {
    colonDash: `${d}:${h}-${mi}`, // %Y-%m-%d:%H-%M
    underscore: `${d}_${h}-${mi}`, // %Y-%m-%d_%H-%M
    colonSeconds: `${d}:${h}:${mi}:00`, // %Y-%m-%d:%H:%M:%S
    sql: `${d} ${h}:${mi}:00`, // %Y-%m-%d %H:%M:%S — a LITERAL SPACE
  };
}
```

- [ ] **Step 2: Rows 9 + 11a — all seven candidates, in order, over exactly four shapes**

```ts
test('an all-404 provider draws out all seven candidates, in order, over exactly four shapes', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  // A FRESH account, and this is load-bearing rather than hygiene:
  // `_set_cached_format_index` writes `timeshift:format_idx:<account_id>`
  // into the Django cache (Redis, DB 0) with a 3600s TTL
  // (views.py:3145-3148). A reused account would start the walk at whatever
  // last worked and this test would observe a rotation, not the canonical
  // order.
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });

  // `not-found`, not `catchup-layout-404`: the layout fault lets QUERY
  // candidate 3 win, so the walk stops there and candidates 4-6 are never
  // sent. `catchup-cascade`'s G8 test above covers that shape of walk. This
  // one needs every candidate on the wire, and only an all-404 provider
  // produces that — the layout fault deliberately refuses to block both
  // layouts (`parseFaultRequest`, e2e-upstream/src/faults.ts).
  await upstream.fault(scenario, 'not-found');

  const instant = new Date(Date.now() - 2 * 60 * 60 * 1000);
  const start = catchupTimestamp(instant);
  const shapes = candidateShapes(instant);
  const token = await api.freshAccessToken();

  const res = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );

  // Exhaustion with `last_status == 404` maps to a client 404
  // (views.py:3335-3337).
  expect(res.status()).toBe(404);
  expect(await res.text()).toContain('Catch-up not available yet');

  const asked = catchupRequests(await upstream.log(scenario));
  expect(asked, 'seven candidates, all attempted').toHaveLength(7);

  // THE FOUR SHAPES, in the exact candidate order
  // `build_timeshift_candidate_urls` emits them
  // (apps/timeshift/helpers.py:490-498). This is the assertion G8's
  // plumbing proof structurally could not make: it stops at candidate 3, so
  // candidate 4 — the SQL shape, the only one carrying a literal space — has
  // never been observed on the wire by anything in this repo.
  expect(asked.map((a) => [a.layout, a.start])).toEqual([
    ['path', shapes.colonDash],
    ['path', shapes.underscore],
    ['path', shapes.colonSeconds],
    ['query', shapes.underscore],
    ['query', shapes.sql],
    ['query', shapes.colonDash],
    ['query', shapes.colonSeconds],
  ]);

  // ALL 404 — and that is a second, independent assertion, not a
  // restatement. The provider validates the timestamp shape in `handleXc`
  // BEFORE `serveChannelStream` ever sees the `not-found` fault
  // (e2e-upstream/src/xc/router.ts), answering an unrecognised shape with a
  // 400 that names it. G8's parser accepts exactly these four and rejects
  // the eight hybrid separator/seconds combinations, so a Dispatcharr
  // regression that emitted e.g. `2026-08-30 14-00` would show up here as a
  // 400 in this list rather than as a silent pass.
  expect(asked.map((a) => a.status)).toEqual([404, 404, 404, 404, 404, 404, 404]);

  // Every candidate carried the same requested instant, in four
  // spellings. This proves the right moment was asked for, seven times over.
  // It does not prove Dispatcharr seeks to it: the fake archive serves the
  // same loop whatever `start` it is given — and here it served nothing at
  // all.
});
```

- [ ] **Step 3: Row 10 — the winning index is cached, and the cache is per account**

```ts
test('the winning candidate index is cached per account and promoted on the next walk', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
  baseURL,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  await upstream.fault(scenario, 'catchup-layout-404', { layout: 'path' });

  const instant = new Date(Date.now() - 2 * 60 * 60 * 1000);
  const start = catchupTimestamp(instant);
  const shapes = candidateShapes(instant);
  const token = await api.freshAccessToken();
  const url = `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`;

  // Walk 1: three PATH 404s, then QUERY candidate 3 wins and is cached.
  await streamClient.open(url, { headers: { Authorization: `Bearer ${token}` } });
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const afterFirst = catchupRequests(await upstream.log(scenario));
  expect(afterFirst).toHaveLength(4);

  // Walk 2: the SAME account, deliberately — the one place in this goal
  // where reusing an account is the assertion rather than the hazard.
  // `_set_cached_format_index(account_id, winning_index)` (views.py:3330)
  // stored 3 under `timeshift:format_idx:<account_id>`, and
  // `_stream_from_provider` reorders the walk to put it first
  // (views.py:3218-3229).
  const again = newStreamClient(baseURL!);
  await again.open(url, { headers: { Authorization: `Bearer ${token}` } });
  expectTsAligned(await again.readPackets(20));
  await again.close();

  const secondWalk = catchupRequests(await upstream.log(scenario)).slice(4);
  expect(secondWalk, 'the cached winner is tried first and wins immediately').toHaveLength(1);
  expect(secondWalk[0].layout).toBe('query');
  expect(secondWalk[0].start).toBe(shapes.underscore);
  expect(secondWalk[0].status).toBe(200);

  // PER ACCOUNT, not per scenario or per channel. A second XC account
  // against the SAME provider scenario must start its own walk at candidate
  // 0 — the cache key is the account id and nothing else
  // (apps/timeshift/redis_keys.py:64-65). Without this, a cache that was
  // accidentally global would still satisfy every assertion above.
  const secondAccount = await seed.xcAccount(scenario);
  expect((await waitFor.m3uRefreshComplete(secondAccount.id)).status).toBe('success');

  const page = await api.json<import('../../fixtures').StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(scenario.username!.replace(/-user$/, ''))}`),
    'streams from both accounts'
  );
  const mine = page.results.find((s) => s.m3u_account === secondAccount.id);
  expect(mine, 'a Stream belonging to the second account').toBeDefined();
  const secondChannel = await seed.channel({ streams: [mine!.id] });

  const third = newStreamClient(baseURL!);
  await third.open(
    `/proxy/catchup/${secondChannel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expectTsAligned(await third.readPackets(20));
  await third.close();

  const thirdWalk = catchupRequests(await upstream.log(scenario)).slice(5);
  expect(thirdWalk[0].layout).toBe('path');
  expect(thirdWalk[0].start).toBe(shapes.colonDash);
});
```

Two implementation notes for this step, both of which will otherwise cost an hour:

1. **`seed.channel({ streams: [...] })` on the second account only works if the second refresh actually created a distinct `Stream` row.** `Stream.generate_hash_key` includes `m3u_id` (`apps/m3u/tasks.py:1160-1163`), so two accounts ingesting the same provider catalogue produce two rows with the same `name` — locate yours by `m3u_account === secondAccount.id`, never by name alone.
2. **Re-read the second channel before driving it** (`GET /api/channels/channels/<id>/`) and assert `is_catchup` is true, exactly as `seedCatchupChannel` does and for the same reason: the `POST` response is rendered from an instance the `ChannelStream` signal's `.update()` never touched. If you skip this and the flag is false, the drive answers `400 "Timeshift not supported for this channel"` and looks like a cascade bug.

- [ ] **Step 4: Row 11b — a decisive failure stops the cascade after one attempt**

```ts
test('a provider 401 is decisive: one attempt, and the client gets 400, not 401', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  await upstream.fault(scenario, 'auth-failure');

  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const token = await api.freshAccessToken();

  const res = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );

  // 400, NOT 401. `_stream_from_provider` maps exhaustion by `last_status`:
  // 404 → 404, 403 → 403, and EVERYTHING ELSE → 400 "Provider error"
  // (views.py:3335-3341). A provider 401 therefore reaches the client as a
  // 400. That is deliberate per the code's own comment, not a defect — but
  // it is exactly the kind of thing a test that asserted the "obvious" 401
  // would have got wrong.
  expect(res.status()).toBe(400);
  expect(await res.text()).toContain('Provider error');

  const asked = catchupRequests(await upstream.log(scenario));
  // ONE. `code in (401, 403, 406)` sets `decisive_failure` and breaks
  // (views.py:3323-3326) — the remaining six candidates are not tried,
  // because an account whose credentials are refused will refuse them in
  // every URL shape too.
  expect(asked).toHaveLength(1);
  expect(asked[0].status).toBe(401);
});
```

- [ ] **Step 5: Row 11c — a 200 with no TS sync is soft, and the walk continues**

```ts
test('a 200 carrying no TS sync is downgraded to a soft 404 and the whole walk continues', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  // `non-ts-bytes` answers 200 with an HTML error page
  // (e2e-upstream/src/server.ts's serveChannelStream, fault 5) — which is
  // what a real provider's PHP actually sends when it is unhappy, and the
  // single most useful failure mode in this file.
  await upstream.fault(scenario, 'non-ts-bytes');

  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  const token = await api.freshAccessToken();

  const res = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expect(res.status()).toBe(404);
  expect(await res.text()).toContain('Catch-up not available yet');

  const asked = catchupRequests(await upstream.log(scenario));
  // Seven attempts, every one answered 200. `find_ts_sync` finds no sync
  // byte in the first 1024, so `last_status` is forced to 404 and the loop
  // CONTINUES (views.py:3301-3312) — a 200 is not evidence of success on
  // this path. Asserting the statuses as well as the count is what
  // distinguishes this from the all-404 row: same count, opposite provider
  // behaviour, same client outcome.
  expect(asked).toHaveLength(7);
  expect(asked.every((a) => a.status === 200)).toBe(true);
});
```

- [ ] **Step 6: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming catchup-cascade` — expect **5 passed** (G8's plus the four above). Record the wall clock: these four are roughly six minutes of the goal's ~17 and are the slowest thing G10 adds.

**If Step 2 reports a 400 among the seven statuses**, do not adjust the expected shapes — read the response body from the provider, which names the offending timestamp and lists the four accepted shapes. A 400 there means Dispatcharr emitted a shape `build_timeshift_candidate_urls` is not supposed to produce, which is the regression this test exists to catch. Report it rather than accommodating it.

**If Step 3's second walk shows 4 requests instead of 1**, the format cache did not take: check that both walks used the same account (not the same *channel* — the key is the account id) and that Redis is the configured Django cache backend rather than a locmem fallback.

- [ ] **Step 7: Commit**

`test(e2e): pin the seven-candidate cascade's shapes, its per-account cache and its failure classes`

---

### Task 8: Rows 12–13 — `server_info.timezone` drives the conversion, and truncates the seconds (known-bug)

Implements inventory rows 12 and 13, spec **D6** and **D11**, and files defect **C3**.

**Files:**
- Create: `e2e/tests/streaming/catchup-provider-timezone.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect`, `expectTsAligned` from `'../../fixtures'`; `catchupRequests`, `catchupTimestampWithSeconds` from `'./helpers'`; fixtures `upstream`, `seed`, `api`, `waitFor`, `streamClient`, `request`.
- Produces: nothing shared. One GitHub issue.

**`seedCatchupChannel` cannot be used here, and this is the task's main hazard.** It waits for the account profile to carry `server_info.timezone === 'UTC'` (hard-coded), which a Brussels scenario will never satisfy — the helper would time out and the failure would point at the profile refresh rather than at the test. Inline its sequence with the zone as a parameter.

**Verified literals:**
- Declaring the zone: `upstream.scenario({ xc: true, ..., account: { serverInfo: { timezone: 'Europe/Brussels' } } })`. The provider merges `scenario.account.serverInfo` over its defaults, whose `timezone` is `'UTC'` (`e2e-upstream/src/xc/envelope.ts:56-67`).
- **D6 — the poll is a precondition, not a convenience.** `refresh_account_profiles` is a separate `.delay()`'d task fired after the main refresh; the timezone lands on `M3UAccountProfile.custom_properties.server_info.timezone` on its own schedule. And `convert_timestamp_to_provider_tz` treats a **missing** value *identically* to `"UTC"` (`helpers.py:145-146`) — so a test that reads too early still passes, for the wrong reason. Poll until the value is exactly `'Europe/Brussels'` before asserting anything.
- The zone is read from the **default** profile's `server_info`, even when a non-default profile wins the capacity walk (`views.py:1657-1664`).
- **D11 — a fixed January date.** `Europe/Brussels` is `+01:00` in January (CET) and `+02:00` in July (CEST). `2026-01-15:12-00` → `2026-01-15:13-00`. Pinning the date makes the expected value a constant instead of a function of the day the suite runs. **Do not** use `new Date()` anywhere in these two tests' timestamps.
- `convert_timestamp_to_provider_tz` returns `local_dt.strftime("%Y-%m-%d:%H-%M")` (`helpers.py:160`) — **dropping seconds**. `build_timeshift_candidate_urls` then re-derives the colon-seconds shape from that already-truncated value, so candidate 2 always carries `:00`. Under `"UTC"` the same start keeps its seconds, because the function returns its input unchanged. That inconsistency is defect **C3**.

- [ ] **Step 1: The local seeding helper**

```ts
import { test, expect, expectTsAligned } from '../../fixtures';
import type { Channel, M3uAccount, StreamPage, UpstreamScenario } from '../../fixtures';
import { catchupRequests, catchupTimestampWithSeconds } from './helpers';

/**
 * `server_info.timezone` from the provider's own handshake drives
 * `convert_timestamp_to_provider_tz` (`apps/timeshift/helpers.py:134-160`),
 * and drops the seconds while it is at it.
 *
 * THE LIMIT: every assertion here reads the URL Dispatcharr **sent**, out of
 * the provider's scenario log. G8's archive is not time-addressable, so
 * these tests prove the right moment was ASKED FOR — never that Dispatcharr
 * seeks to it.
 *
 * A FIXED JANUARY DATE, deliberately: Europe/Brussels is +01:00 in January
 * and +02:00 in July, so a `new Date()` here would make the expected
 * provider timestamp a function of the day the suite runs. Do not
 * "modernise" these literals.
 *
 * `seedCatchupChannel` is not usable: it waits for the profile timezone to
 * be exactly `'UTC'`. That wait is the important part of it, so it is
 * reproduced below with the zone as a parameter rather than skipped.
 */
async function seedCatchupChannelInZone(
  fx: {
    upstream: import('../../fixtures').UpstreamClient;
    seed: import('../../fixtures').Seeder;
    api: import('../../fixtures').ApiClient;
    waitFor: import('../../fixtures').Waiter;
  },
  timezone: string
): Promise<{ scenario: UpstreamScenario; channel: Channel; providerStreamId: number }> {
  const { upstream, seed, api, waitFor } = fx;
  const prefix = seed.generatedName('catchup-tz');
  const providerStreamId = 1;

  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: providerStreamId, name: `${prefix}-ch`, tvgId: `${prefix}-ch.e2e`, logo: null, categoryId: 1 },
    ],
    account: { serverInfo: { timezone } },
  });

  const account = await seed.xcAccount(scenario);
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    `streams ingested for ${prefix}`
  );
  const ingested = page.results.find((s) => s.name === `${prefix}-ch`);
  if (!ingested) throw new Error(`no ingested Stream named "${prefix}-ch" — the XC ingest is broken, not catch-up`);

  const created = await seed.channel({ streams: [ingested.id] });

  // D6: THE POLL IS A PRECONDITION, NOT A CONVENIENCE.
  // `refresh_account_profiles` is a separate `.delay()`'d task fired after
  // the refresh awaited above. Reading too early sees null — and
  // `convert_timestamp_to_provider_tz` treats null EXACTLY like "UTC"
  // (helpers.py:145-146), so a timestamp assertion made before this lands
  // passes whether or not any conversion happened. That is the failure mode
  // this wait exists to close.
  await waitFor.resource<M3uAccount>(
    `/api/m3u/accounts/${account.id}/`,
    (body) =>
      body.profiles.some(
        (p) =>
          (p.custom_properties as { server_info?: { timezone?: string } } | null)?.server_info
            ?.timezone === timezone
      ),
    { description: `the XC account profile to carry server_info.timezone ${timezone}` }
  );

  const channel = await api.json<Channel>(
    await api.get(`/api/channels/channels/${created.id}/`),
    `channel ${created.id} after wiring`
  );
  if (!channel.is_catchup) {
    throw new Error(
      `channel ${channel.id} is not is_catchup after the refresh — check the five ` +
        'preconditions before suspecting the timezone conversion.'
    );
  }

  return { scenario, channel, providerStreamId };
}
```

- [ ] **Step 2: Row 12 — the conversion happens, and the provider records the local time**

```ts
// 2026-01-15 is a WINTER date: Europe/Brussels is CET, +01:00. In July it
// would be CEST, +02:00, and this constant would be wrong for half the year.
const WINTER_START_UTC = '2026-01-15:12-00';
const WINTER_START_BRUSSELS = '2026-01-15:13-00';

test('the provider server_info.timezone converts the requested start before it is sent', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannelInZone(
    { upstream, seed, api, waitFor },
    'Europe/Brussels'
  );

  await streamClient.open(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(WINTER_START_UTC)}&duration=60`,
    { headers: { Authorization: `Bearer ${await api.freshAccessToken()}` } }
  );
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const asked = catchupRequests(await upstream.log(scenario));
  expect(asked).toHaveLength(1);
  expect(asked[0].streamId).toBe(String(providerStreamId));

  // +01:00. The client asked for 12:00 UTC; the provider indexes its archive
  // in its own local time, so Dispatcharr asks it for 13:00
  // (`convert_timestamp_to_provider_tz`, helpers.py:157-160, reading the
  // DEFAULT profile's server_info even when another profile wins the
  // capacity walk — views.py:1657-1664).
  expect(asked[0].start).toBe(WINTER_START_BRUSSELS);

  // This proves the right moment was asked for, in the provider's own
  // clock. It does not prove Dispatcharr seeks to it: the fake archive
  // serves the same loop whatever `start` it is given, and it would have
  // served identical bytes for a wrong conversion.
});
```

- [ ] **Step 3: Row 13 — the seconds are truncated (known-bug), with the UTC control in the same test**

```ts
test.fail(
  'a requested start keeps its seconds whatever the provider timezone is',
  async ({ upstream, seed, api, waitFor, request }) => {
    // KNOWN BUG — issue #NN (defect C3). Under a non-UTC provider timezone,
    // `convert_timestamp_to_provider_tz` reformats through
    // `strftime("%Y-%m-%d:%H-%M")` (helpers.py:160) and drops the seconds,
    // BEFORE `build_timeshift_candidate_urls` re-derives the colon-seconds
    // shape from the truncated value. Under "UTC" the same start keeps them,
    // because the function returns its input unchanged (helpers.py:145-146).
    // The precision of the moment Dispatcharr asks for therefore depends on a
    // field the provider declares.
    //
    // The UTC control runs FIRST and PASSES, in this same test, so the
    // finding recorded here is the INCONSISTENCY between the two zones — not
    // truncation on its own, which someone could reasonably defend as a
    // minute-resolution product.
    //
    // The `catchup-layout-404 { layout: 'path' }` fault is what makes
    // candidate 2 observable at all: unfaulted, candidate 0 wins and the
    // colon-seconds shape is never sent.
    const startUtc = '2026-01-15:12-00-45';
    const token = await api.freshAccessToken();

    const utc = await seedCatchupChannelInZone({ upstream, seed, api, waitFor }, 'UTC');
    await upstream.fault(utc.scenario, 'catchup-layout-404', { layout: 'path' });
    await request.get(
      `/proxy/catchup/${utc.channel.uuid}?start=${encodeURIComponent(startUtc)}&duration=60`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const utcAsked = catchupRequests(await upstream.log(utc.scenario));
    expect(utcAsked.length, 'three PATH candidates under UTC').toBeGreaterThanOrEqual(3);
    // PASSES: candidate 2, %Y-%m-%d:%H:%M:%S, keeps the requested :45.
    expect(utcAsked[2].start, 'UTC preserves the requested seconds').toBe('2026-01-15:12:00:45');

    const brussels = await seedCatchupChannelInZone(
      { upstream, seed, api, waitFor },
      'Europe/Brussels'
    );
    await upstream.fault(brussels.scenario, 'catchup-layout-404', { layout: 'path' });
    await request.get(
      `/proxy/catchup/${brussels.channel.uuid}?start=${encodeURIComponent(startUtc)}&duration=60`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const bxlAsked = catchupRequests(await upstream.log(brussels.scenario));
    expect(bxlAsked.length, 'three PATH candidates under Europe/Brussels').toBeGreaterThanOrEqual(3);
    // FAILS TODAY: this is the CORRECT value. The actual value is
    // '2026-01-15:13:00:00'. Never invert this to assert the :00 — a
    // test.fail() that asserts the bug goes green the wrong way and locks
    // the defect in.
    expect(
      bxlAsked[2].start,
      'a non-UTC provider timezone must not truncate the requested seconds'
    ).toBe('2026-01-15:13:00:45');
  }
);
```

Note the two `request.get` calls above deliberately ignore their responses: with PATH blocked the walk falls through to QUERY and succeeds, so the client gets a stream body this test does not read. Do not use `streamClient` here — nothing needs the bytes, and an unread open would have to be closed.

- [ ] **Step 4: File the C3 issue**

```
gh issue create --repo D10Scot/Dispatcharr --label needs-triage \
  --title "A non-UTC provider server_info.timezone silently truncates the requested catch-up start to the minute" \
  --body "$(cat <<'EOF'
`convert_timestamp_to_provider_tz` (`apps/timeshift/helpers.py:134-160`) returns its input **unchanged** when the provider declares no timezone or exactly `"UTC"` (`:145-146`), and otherwise returns `local_dt.strftime("%Y-%m-%d:%H-%M")` (`:160`) — a shape with no seconds.

`build_timeshift_candidate_urls` (`:466-498`) then re-parses that already-truncated value and derives all four shapes from it, including `%Y-%m-%d:%H:%M:%S` (PATH candidate 2, QUERY candidate 6) — the colon-seconds form some providers require. Under a non-UTC zone that candidate therefore always carries `:00`, whatever the client asked for; under `"UTC"` (or a missing timezone) the same request keeps its seconds.

Reproduction, with `?start=2026-01-15:12-00-45` on `/proxy/catchup/<uuid>`:

| Provider `server_info.timezone` | Colon-seconds candidate |
|---|---|
| `UTC` (or absent) | `2026-01-15:12:00:45` |
| `Europe/Brussels` | `2026-01-15:13:00:00` — the `:45` is gone |

The finding is the **inconsistency**, not the truncation alone: minute resolution would be a defensible product decision, but it is not one that should depend on a field the *provider* declares. Two Dispatcharr instances asking two providers for the same programme ask with different precision.

The fix is presumably to carry seconds through the conversion — `strftime("%Y-%m-%d:%H-%M-%S")` would round-trip through `normalize_catchup_timestamp_input`'s `_CATCHUP_WALL_CLOCK_RE` (`:31-44`), whose minute/second separator may be `-` or `:` — but note that the *return shape* of `convert_timestamp_to_provider_tz` is also what feeds `build_timeshift_redirect_url` (`:449-464`), so redirect mode would change with it.

Pinned by `e2e/tests/streaming/catchup-provider-timezone.spec.ts`, whose `test.fail()` asserts the correct value and carries the passing UTC control in the same test so the inconsistency is visible in one place.

Found by the G10 E2E goal (`docs/superpowers/specs/2026-08-30-e2e-catchup-timeshift-design.md`, defect C3).
EOF
)"
```

Put the returned number in place of `#NN`.

- [ ] **Step 5: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming catchup-provider-timezone` — expect **1 passed, 1 expected failure**.

**If row 12 fails with `asked[0].start === '2026-01-15:12-00'`** (unconverted), the timezone had not landed when the request was made — which should be impossible given the poll, so check that the poll is comparing against `'Europe/Brussels'` and not `'UTC'`, and that `account: { serverInfo: { timezone } }` reached the scenario (`GET <control>/s/<id>` is not a route; read the account profile instead).

- [ ] **Step 6: Commit**

`test(e2e): prove the provider timezone drives the catch-up conversion, and pin its seconds truncation`

---

### Task 9: Row 14 — redirect mode mirrors the client's layout and fetches nothing

Implements inventory row 14, spec **D8**, **D9** and **D10**. This is the only test in the goal that mutates a **global**, and the only reason it lives in `streaming-failover`.

**Files:**
- Create: `e2e/tests/streaming-failover/catchup-redirect.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect` from `'../../fixtures'`; `seedCatchupChannel`, `seedXcUser`, `catchupTimestamp`, `catchupRequests`, `lockedProfile` from `'../streaming/helpers'`; fixtures `upstream`, `seed`, `api`, `waitFor`, `request`.
- Produces: nothing shared. No issue.

**Why here, and the honest cost.** Redirect mode is reachable only by flipping the **global** `stream_settings.default_stream_profile` to the locked Redirect profile (`CoreSettings.is_default_stream_profile_redirect`, `core/models.py:549-564`, comparing `get_default_stream_profile_id()` at `:507-508` against `get_redirect_stream_profile_id()` at `:522`). There is no per-channel override. The repo's established answer to a spec that mutates a global is a `workers: 1` project, and of the two, `streaming-greybox` is reserved for container-wide process observation while `streaming-failover` already hosts exactly this pattern. A new `catchup` project was **rejected**: it would require editing `.github/workflows/e2e-tests.yml`, which arms the zizmor ratchet on every legacy finding in that file, for the benefit of one row.

**Two things that differ from `failover-buffering.spec.ts`, and getting either wrong wastes an afternoon:**

1. **Do NOT copy its 12-second sleep.** That sleep exists because `apps/proxy/config.py`'s `BaseConfig` keeps a **process-local** copy of `proxy_settings` for `_proxy_settings_cache_ttl = 10` seconds (`config.py:22-24`), so a PATCH clears the cache only in the uWSGI worker that handled it. `stream_settings` has no such cache: `CoreSettings._get_group` caches in **Redis**, and the `post_save` signal bumps the group's cache version for every worker at once (`core/models.py:344-357`, `:372-384`). The flip is visible immediately. A sleep here would add 12s of nothing to a 300s budget.
2. **The guard protects *this* test's next run, not the tests around it.** If this test dies between the write and the `finally`, the container stays on Redirect for **every** later project and every later run — and CI's `retries: 1` would then read the mutated value as "original" and write it back permanently on the retry. The up-front assertion catches that on this test's *next* execution and turns silent corruption into a loud failure. It does nothing for a streaming test that runs in between. Say so in the test's own header, because the next person to add a spec to this directory needs to know it.

**Verified literals:**
- Settings: `GET /api/core/settings/` returns a plain array of `{ id, key, name, value }` (no pagination configured). The row is `key === 'stream_settings'`. Write with `PATCH /api/core/settings/<id>/ { value }`, and **read-modify-write the whole `value` blob** — `stream_settings` holds `default_user_agent`, `default_stream_profile`, `m3u_hash_key`, `default_output_format`, `hdhr_output_profile_id` (`core/models.py:426-434`), and PATCHing a partial object drops the siblings.
- The locked profile's name is the literal `"Redirect"` (`REDIRECT_PROFILE_NAME`, `core/models.py:47`), matched with `locked=True` (`:511-519`). Use `lockedProfile(api, 'Redirect')`.
- Redirect branch: `views.py:406-437`. With no `session_id` and no pool match, `is_default_stream_profile_redirect()` true → `_select_catchup_redirect_url(..., layout=client_timeshift_url_layout(request), ...)` → `HttpResponseRedirect(provider_url)`, which is a **302**. Otherwise a 301 with a minted session.
- `client_timeshift_url_layout` returns `"query"` **only** when `timeshift.php` appears in the request path; everything else — `/timeshift/...` and `/proxy/catchup/...` alike — is `"path"` (`helpers.py:436-446`).
- The `Location` targets `scenario.internal`, a container-only hostname. **Do not follow it.** Assert on substrings.

- [ ] **Step 1: Write the file**

```ts
import { test, expect } from '../../fixtures';
import type { ApiClient } from '../../fixtures';
import {
  catchupRequests,
  catchupTimestamp,
  lockedProfile,
  seedCatchupChannel,
  seedXcUser,
} from '../streaming/helpers';

/**
 * Redirect mode: three entry points, two layouts, and an empty provider log.
 *
 * THIS TEST MUTATES A GLOBAL. Redirect mode is reachable only by pointing
 * `stream_settings.default_stream_profile` at the locked Redirect profile
 * (`CoreSettings.is_default_stream_profile_redirect`, `core/models.py:549-564`);
 * there is no per-channel override. While it is flipped, EVERY channel in
 * the container answers a session-less catch-up or live request with a 302
 * to the provider instead of proxying it. `streaming-failover` runs at
 * `workers: 1` for exactly this class of hazard — see the project's comment
 * in `playwright.config.ts`, which now names two globals.
 *
 * The up-front guard below catches a previous run that died between the
 * write and the `finally`: CI's `retries: 1` would otherwise read the
 * contaminated value as "original" and write it back permanently. BUT NOTE
 * WHAT IT DOES NOT DO: it protects *this* test's next run, not the tests
 * around it. Any streaming test running between an aborted run and the next
 * run of this one would silently see Redirect as the container's default and
 * would have no idea. That residual risk is the price of testing a global,
 * and it is why nothing else in this goal touches one.
 *
 * NO CACHE SLEEP. `failover-buffering.spec.ts` waits 12s after its write
 * because `apps/proxy/config.py`'s `BaseConfig` keeps a 10s PROCESS-LOCAL
 * copy of `proxy_settings` (`config.py:22-24`), so a PATCH clears it only in
 * the worker that handled it. `stream_settings` is cached in Redis with
 * signal-driven invalidation (`core/models.py:344-357`, `:372-384`) and is
 * visible to every worker at once. Do not copy the sleep.
 *
 * And the goal's standing limit: every assertion below is on the URL
 * Dispatcharr HANDED OUT, never on bytes — redirect mode fetches nothing at
 * all, which is half the definition of the mode and the last assertion in
 * this file.
 */
const CORE_SETTINGS_PATH = '/api/core/settings/';
const STREAM_SETTINGS_KEY = 'stream_settings';

interface CoreSettingsRow {
  id: number;
  key: string;
  value: Record<string, unknown>;
}

async function readStreamSettingsRow(api: ApiClient): Promise<CoreSettingsRow> {
  const rows = await api.json<CoreSettingsRow[]>(await api.get(CORE_SETTINGS_PATH), 'core settings');
  const row = rows.find((r) => r.key === STREAM_SETTINGS_KEY);
  expect(row, `the "${STREAM_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
  return row!;
}

test('redirect mode hands the client a provider URL in the layout it arrived in, and fetches nothing', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannel({
    upstream,
    seed,
    api,
    waitFor,
  });
  const xcUser = await seedXcUser(seed);
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  const redirect = await lockedProfile(api, 'Redirect');
  const settingsRow = await readStreamSettingsRow(api);
  const originalValue = settingsRow.value;

  // THE GUARD (D10). Compared as strings because the row's JSON has carried
  // both an int and a string id in the wild, and `!==` on mixed types would
  // pass a dirty container straight through.
  expect(
    String(originalValue.default_stream_profile ?? ''),
    'a previous run left stream_settings dirty — the container is already on Redirect'
  ).not.toBe(String(redirect.id));

  await api.patch(`${CORE_SETTINGS_PATH}${settingsRow.id}/`, {
    value: { ...originalValue, default_stream_profile: redirect.id },
  });

  try {
    const token = await api.freshAccessToken();

    // 1. The native route. `client_timeshift_url_layout` returns "path" for
    //    everything that is not `timeshift.php` — `/proxy/catchup/` included
    //    (helpers.py:436-446).
    const native = await request.get(
      `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
      { headers: { Authorization: `Bearer ${token}` }, maxRedirects: 0 }
    );
    // 302, not the 301 a session mint would give (views.py:406-437): the
    // Redirect branch hands off before any session exists.
    expect(native.status()).toBe(302);
    const nativeLocation = native.headers()['location'];
    expect(nativeLocation).toContain(
      `/timeshift/${scenario.username}/${scenario.password}/65/${start}/${providerStreamId}.ts`
    );

    // 2. The root PATH route. Same layout, same shape.
    const rootPath = await request.get(
      `/timeshift/${xcUser.username}/${xcUser.xcPassword}/60/${start}/${channel.id}.ts`,
      { maxRedirects: 0 }
    );
    expect(rootPath.status()).toBe(302);
    expect(rootPath.headers()['location']).toContain(
      `/timeshift/${scenario.username}/${scenario.password}/65/${start}/${providerStreamId}.ts`
    );

    // 3. The root QUERY route — the ONLY request in this goal that produces a
    //    QUERY provider URL. `client_timeshift_url_layout` returns "query"
    //    only when `timeshift.php` is in the request path, and that choice is
    //    consumed only by `_select_catchup_redirect_url` (views.py:413-419).
    //    Proxy mode never sees it, which is why
    //    `catchup-proxy-mode.spec.ts` asserts both root routes produce a PATH
    //    upstream request.
    const rootQuery = await request.get(
      `/streaming/timeshift.php?username=${encodeURIComponent(xcUser.username)}` +
        `&password=${encodeURIComponent(xcUser.xcPassword)}` +
        `&stream=${channel.id}&start=${encodeURIComponent(start)}&duration=60`,
      { maxRedirects: 0 }
    );
    expect(rootQuery.status()).toBe(302);
    const queryLocation = rootQuery.headers()['location'];
    expect(queryLocation).toContain('/streaming/timeshift.php');
    expect(queryLocation).toContain(`username=${scenario.username}`);
    expect(queryLocation).toContain(`password=${scenario.password}`);
    expect(queryLocation).toContain(`stream=${providerStreamId}`);
    expect(queryLocation).toContain('duration=65');
    // `build_timeshift_url_format_a` interpolates `start` RAW
    // (helpers.py:412-421) and this shape has no space, so it appears
    // verbatim in the Location header.
    expect(queryLocation).toContain(`start=${start}`);

    // THE OTHER HALF OF THE DEFINITION (D9). Redirect mode hands the client a
    // URL and fetches NOTHING — the capacity check runs with reserve=False
    // (`_prepare_catchup_stream_attempt`, views.py:1618-1652) and no HTTP
    // request is made at all. Three redirects issued, zero upstream requests.
    expect(
      catchupRequests(await upstream.log(scenario)),
      'redirect mode must make no upstream request of its own'
    ).toHaveLength(0);

    // All three Locations carry `/65/` and the requested start: the right
    // moment was asked for, in the shape the client can use. Nothing here
    // proves Dispatcharr — or the provider — seeks to it.
  } finally {
    // Restore. `stream_settings` is global; leaving it on Redirect would put
    // every later test in this container on 302-handoff instead of proxying.
    await api.patch(`${CORE_SETTINGS_PATH}${settingsRow.id}/`, { value: originalValue });
  }
});
```

- [ ] **Step 2: Verify**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming-failover` — expect the whole project green, **five tests**, including the four pre-existing failover specs. Running the whole project rather than just this file is the point: it is the cheapest evidence the global was actually restored.

Then run it a **second** time without resetting the container. If the guard fires on the second run, the `finally` did not restore and the bug is in this test, not in the product — fix it before committing, and do not weaken the guard.

- [ ] **Step 3: Commit**

`test(e2e): prove redirect mode mirrors the client layout and makes no upstream request`

---

### Task 10: Coverage inventory and documentation

**Must run last** — it lists the files the other tasks create, and needs the three issue numbers they filed.

**Files:**
- Modify: `e2e/COVERAGE.md`
- Modify: `e2e/README.md`

- [ ] **Step 1: Update the nine existing Catch-up / G10 rows**

They are contiguous in the table, under `| Catch-up |`. Set each Status, keeping the Flow text as-is unless noted:

| Flow (abbreviated) | New status | Note |
|---|---|---|
| XC live ingest fields → `Stream` → `Channel` via `rollup_channel_catchup_fields`, including its self-heal pass | `done` | Reword the tail: the test proves the **aggregate** pass in both directions, and the plan's Task 2 explains why the self-heal statement in the second SQL block cannot fire independently for a channel the aggregate already covers (both are restricted to the same `account_channels` set, `apps/m3u/tasks.py:1971-2014`). Say "including clearing the flag when the provider stops advertising it" rather than claiming the self-heal statement itself was exercised |
| **Gap:** the provider stream id is not observable through the REST API | `done` | It is now observable **the other way in**: `catchupRequests` reads it off the provider's recorded request path, which is what the row itself suggested. Append one sentence naming `e2e/tests/streaming/catchup-proxy-mode.spec.ts` |
| **Gap:** the recommended `POST /api/catchup/sessions/` branch is unexercised | `done` | Both halves landed — the mint contract in `seeded/catchup-session-api.spec.ts`, the headerless playback in `streaming/catchup-proxy-mode.spec.ts` |
| Redirect mode: the two root routes 302 in the client's layout; `/proxy/catchup/` defaults to PATH | `done` | |
| Proxy mode end to end | `done` | |
| The seven-candidate cascade: PATH first, QUERY last, winning index cached | `done` | |
| Decisive failures stop the cascade; a soft 404 or a sync-less 200 does not | `done` | |
| `server_info.timezone` drives `convert_timestamp_to_provider_tz` | `done` | |
| **Gap:** the generated M3U emits no `catchup=` … *G10 decides whether that is a defect to file or intended* | `known-bug` | **Rewrite the tail.** The decision is made: it is a defect, filed as `[#NN](https://github.com/D10Scot/Dispatcharr/issues/NN)`, pinned convention-agnostically by `seeded/catchup-m3u-advertisement.spec.ts`. Say that the test asserts only *some* `catchup` attribute plus a matching `catchup-days`, because which of three incompatible M3U conventions to adopt is an unmade product decision |

- [ ] **Step 2: Resolve the Upstream time-addressability row**

The Upstream/G8 row reading *"**Gap:** the fake archive is not time-addressable … Owned by G10, which must say so in every row it writes"* moves to `done`. Append: G10 states the limit in `e2e/README.md`'s new Catch-up section, in each of the five spec files that assert on a timestamp, and beside the assertions themselves — and closing the gap for real means generating a distinct asset per requested instant, which is a build of its own and a new goal, not a G10 task.

- [ ] **Step 3: Append three new rows**

The spec called for four; the session-API row already exists as a G8-filed Gap row (Step 1), so three are new:

```
| Catch-up | Each catch-up precondition fails closed — non-catch-up channel, unparseable start, absent start, deactivated account — and none reaches the provider | G10 | done |
| Catch-up | **Known defect:** hide_adult_content is applied at twelve sites across apps/output/, apps/epg/, apps/channels/ and apps/vod/ and at none under apps/timeshift/, so an adult channel a user cannot list is still streamable through every catch-up entry point ([#NN](https://github.com/D10Scot/Dispatcharr/issues/NN)) | G10 | known-bug |
| Catch-up | **Known defect:** a non-UTC provider server_info.timezone truncates the requested start to the minute — convert_timestamp_to_provider_tz reformats through strftime("%Y-%m-%d:%H-%M") (apps/timeshift/helpers.py:160) before the colon-seconds candidate is derived, while "UTC" preserves the seconds ([#NN](https://github.com/D10Scot/Dispatcharr/issues/NN)) | G10 | known-bug |
```

- [ ] **Step 4: Correct the now-stale Upstream row about the timestamp parser**

The Upstream/G8 row beginning *"**Gap:** the catch-up timestamp parser (`parseCatchupTimestamp` …) over-accepts. Its regex is `[:_ ]…[-:]…(?:[-:]\d{2})?` …"* describes state that **no longer exists**: G8's own PR replaced that single permissive regex with one regex per shape, tried in order (`CATCHUP_TIMESTAMP_SHAPES`, `e2e-upstream/src/xc/catchup.ts`), with an exhaustive test asserting all twelve separator/seconds combinations resolve to exactly the four accepted shapes. Leaving it would mislead the next reader of the exact file G10's cascade proof depends on.

Set it to `done` and replace the body with a short, accurate note: the parser now accepts exactly the four shapes `build_timeshift_candidate_urls` emits and rejects the eight hybrids with a 400 naming the offending value, which is what makes `streaming/catchup-cascade.spec.ts`'s seven-candidate assertion a real proof rather than a tautology; calendar validation is still absent (`2026-13-45:99-99` parses), which remains harmless because over-acceptance can only widen what is served.

**This edits a row this plan does not own.** If it conflicts with a concurrent G9 edit, drop the change, leave the row alone, and say so in the task report rather than resolving the conflict by hand.

- [ ] **Step 5: Leave the credential-encoding row alone, and say why**

The Upstream row on `collect_xc_streams`' raw credential interpolation is already filed as **#61** and is assigned to *"whichever of G9/G10 first ingests a real XC account with an unsanitised (slash- or percent-bearing) credential"*. G10 ingests only sanitised credentials — `seed.generatedName` produces `^[A-Za-z0-9._@-]+$` — and spec **D13** declines the row for three reasons: the skew is unobservable for almost every credential; where it *is* visible (`/`, `?`, `#`) the *live* path is the broken side, which is G4's territory; and a third builder (`get_transformed_credentials`, `apps/m3u/tasks.py:3067-3103`) recovers credentials by splitting a synthetic path on `/`, so a `/`-bearing credential breaks extraction before either builder runs. **Leave the row `todo` and owned by G9.** File no second issue: #61 already covers all three builders.

- [ ] **Step 6: List the spec files under the G10 rows**

Follow the format the G1/G2/G4/G8 blocks at the bottom of the file use — a prose sentence saying which rows share which file, then the list. Name all seven G10 spec files plus the appended-to `catchup-cascade.spec.ts`, and state plainly that G8's `catchup-path-layout.spec.ts` and its cascade test remain the plumbing proofs G10 builds on rather than replaces.

- [ ] **Step 7: Add a "Catch-up" section to `e2e/README.md`**

Place it immediately after **"The fake upstream provider — a second, local-only container"**, so a test author meets it in the same place as the fault catalogue. Four paragraphs, no existing text rewritten:

1. **The archive is not time-addressable.** The catch-up routes serve the same looping TS whatever `start` they are given. So every catch-up assertion about time reads the provider's scenario log (`upstream.log(scenario)` → `catchupRequests`, `e2e/tests/streaming/helpers.ts`) and never the bytes. **A catch-up test can prove the right moment was asked for. It cannot prove Dispatcharr seeks to it.** Say this in the test, next to the assertion — not only in a file header — because that is where the next reader will be when they draw the wrong conclusion.
2. **The format cache outlives your test.** `_set_cached_format_index` writes `timeshift:format_idx:<account_id>` into the Django cache (Redis, DB 0) with a 3600s TTL. **Every cascade observation needs its own XC account.** A test reusing another's inherits its cascade winner and passes for the wrong reason. `streaming/catchup-cascade.spec.ts` turns that hazard into an assertion; everything else avoids it by construction.
3. **The provider timezone lands late, and its absence looks identical to `"UTC"`.** `refresh_account_profiles` is a separate `.delay()`'d task, and `convert_timestamp_to_provider_tz` returns its input unchanged for both a missing value and exactly `"UTC"`. Poll `M3UAccountProfile.custom_properties.server_info.timezone` for the value you declared **before** asserting on any converted timestamp; `seedCatchupChannel` does this for `'UTC'`, and `catchup-provider-timezone.spec.ts` shows the parameterised form.
4. **Redirect mode is a global.** It is reachable only through `stream_settings.default_stream_profile`, so `streaming-failover/catchup-redirect.spec.ts` read-modify-writes that row and restores it in a `finally` — the second global that project now hosts, and the reason it stays at `workers: 1`. Unlike `proxy_settings`, `stream_settings` needs no cache-settling wait.

Also add one line to the fixture documentation naming `catchupRequests(log)` and `catchupTimestampWithSeconds(date)` alongside the existing `catchupTimestamp`/`seedCatchupChannel` mentions, so they are discoverable without reading the spec files.

- [ ] **Step 8: Verify the whole goal**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh --reset` then, in order:
- `cd e2e && npx playwright test --project=seeded` — expect every G10 seeded spec green, with **one** expected failure (the M3U advertisement row).
- `npx playwright test --project=streaming` — expect green, with **two** expected failures (adult content, seconds truncation).
- `npx playwright test --project=streaming-failover` — expect all five green.

Record the wall clock for each project and compare against what it took before G10. G10 adds seven tests to `seeded`, nine to `streaming` and one to `streaming-failover`; the `streaming` increase should be roughly six to eight minutes, dominated by `catchup-cascade.spec.ts`. Report any increase materially beyond that rather than quietly accepting it.

- [ ] **Step 9: Commit**

`docs(e2e): record G10 catch-up coverage`

---

## Self-Review

**Spec coverage.** D1 → the plan's second paragraph, Global Constraints, and a named comment in Tasks 6, 7, 8, 9 and in the README section from Task 10 — carried into the assertions, never only into a preamble. D2 → Global Constraints, and the "What G8 already landed" table's ruling that the conditional `ChannelSpec` addition is unnecessary; no task touches `e2e-upstream/`. D3 → the row-9 re-scope, argued in "What G8 already landed" and executed in Task 7 Step 2. D4 → Task 2's re-scope away from `xc-ingest.spec.ts`'s stream-level assertions, and Task 6 Step 3's note on what G8's PATH proof already covers. D5 → Global Constraints, Task 7 Steps 2 and 3 (with the comment saying it is load-bearing), Task 10 Step 7 paragraph 2. D6 → Task 8 Step 1's poll, with the reason it is a precondition rather than a convenience. D7 → Task 6 Step 3. D8 → Task 1 Step 3 and Task 9's placement and header. D9 → Task 9's final assertion. D10 → Task 9's guard, `finally`, and the paragraph stating what the guard does *not* protect. D11 → Task 8's fixed January constants and the instruction not to modernise them. D12 → Task 5 in full. D13 → Task 10 Step 5. D14 → not implemented, by design; no task touches `system_settings.catchup_enabled` or the per-user flag.

**Test inventory rows → tasks.** 1, 2 → Task 2. 3 → Task 3. 4 → Task 4. 5 → Task 5. 6, 7, 8 → Task 6. 9, 10, 11 → Task 7 (9 merged into 11's `not-found` arm; see below). 12, 13 → Task 8. 14 → Task 9. The two G8-filed COVERAGE Gap rows assigned to G10 → Tasks 4 and 6 (session API) and Tasks 6 and 7 (the provider stream id).

**Deviations from the spec, each stated where it happens and why.**

1. **Row 9 is merged into row 11's `not-found` arm.** G8's landed cascade test already asserts everything row 9 specified except the SQL shape, and `catchup-layout-404` structurally cannot reach it. Spec D3 forbids duplicating a plumbing proof, so the row becomes the exhaustive seven-candidate assertion instead. Fourteen tests become thirteen; the coverage is strictly larger, not smaller.
2. **Row 1's mechanism is inverted.** The spec's "wire, refresh, assert" sequence would have observed the `ChannelStream` signal, not the rollup task — `seedCatchupChannel`'s own mutation check proves it. Task 2 wires the channel in the opposite state first so the rollup is the only remaining explanation.
3. **No `types.ts` change to `ChannelSpec`.** The spec made this conditional on checking G8 first. Checked: the channel-scoped `no-tv-archive` fault expresses both states with no change to either package. `types.ts` is still edited, but for a different and better-evidenced reason — `Stream.is_catchup`/`catchup_days` are what rows 1 and 2 assert on and are absent from the shared type.
4. **Three issues, not four.** C2 is already filed as #61 (recorded in `COVERAGE.md` by G8). Filing a second would fragment the discussion.
5. **Three new COVERAGE rows, not four.** The session-API row already exists as a G8-filed Gap row.
6. **Task 10 Step 4 edits an Upstream row this goal does not own**, because that row now describes a parser G8 replaced within the same PR and it is the exact file Task 7's central proof depends on. The step says to abandon the edit rather than resolve a conflict with G9.

**Things the plan asks an implementer to derive rather than assume, and what to do if the derivation fails.** Task 3 Step 2 leaves the account handle unresolved with two named resolutions and a rule about which files may not be touched to get it. Task 7 Step 3 names the two ways the second-account walk goes wrong and how to tell. Task 8 Step 5 names the single symptom that means the timezone poll is comparing the wrong value. Task 9 Step 2 requires a second consecutive run to prove the `finally` restored, and forbids weakening the guard if it does not. All four are "run this and write down what it says" steps, not placeholders.

**File-disjointness.** Task 1 owns all three shared fixture/config files. Task 7 is the only task that touches `catchup-cascade.spec.ts`. Task 10 is the only task that touches `COVERAGE.md` or `README.md`. Tasks 2, 3, 4, 5, 6, 8 and 9 each create exactly one file and modify nothing. After Task 1 lands, eight tasks can execute in parallel; Task 10 must be last.

**Import consistency.** `catchupRequests`, `CatchupRequestRecord` and `catchupTimestampWithSeconds` are defined in Task 1 and used from Tasks 3, 6, 7, 8 and 9 with one signature throughout. `seedCatchupChannel`, `catchupTimestamp`, `seedXcUser`, `lockedProfile` and `newStreamClient` come from G8's `e2e/tests/streaming/helpers.ts` and are never redefined — Task 8's `seedCatchupChannelInZone` is a deliberate local parameterisation, declared as such in its own comment, because the shared helper's `'UTC'` wait is the thing that must vary. `candidateShapes` is local to `catchup-cascade.spec.ts` and is not promoted, because its only other plausible consumer (`catchup-provider-timezone.spec.ts`) needs a non-zero seconds field this version deliberately hard-codes to `00`.

**What this plan does not deliver, so its absence reads as a decision.** The catch-up session *pool* (fingerprint adoption, scrub displacement, EOF probes, presentation windows, `final_url` CDN caching, the stats client — roughly 1,500 lines of `views.py` and nine unit-test classes). Range and seek on the catch-up path, which against a `Content-Length`-less looping archive is not meaningfully observable. `xmltv.php`'s catch-up lookback and `has_archive`, which sit on a G5 surface. The global and per-user catch-up kill switches (D14). Defect **C4** — `catchup_proxy` calling `network_access_allowed(request, "STREAMS")` with no user (`views.py:285`) while both sibling entry points pass one — which the spec records, files no issue for, and writes no row for, because it matches `stream_ts`'s documented deliberate concession and the principal is genuinely not resolved at that point in the view. And any product change at all: three `test.fail()`s and three issues, not one line of `apps/`.
