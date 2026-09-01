# G10 — Catch-up / Timeshift End to End

**Date:** 2026-08-30
**Status:** Approved, ready for implementation planning
**Wave:** 4 (dispatched once G8's provider build has landed)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Depends on:** `2026-08-29-e2e-xc-provider-emulation-design.md` (G8). G10 is a **consumer**: it
adds no provider capability and specifies no test that needs one G8 does not ship.
**Verified against:** `8d6db577`. Line numbers are cited because a reader should be able to check
them; they drift, so check the symbol if the line has moved.

**Siblings in flight.**

| File | Also touched by | Discipline |
|---|---|---|
| `e2e/COVERAGE.md` | G5, G6, G7, G8, G9 | G10 edits only its own seven rows and appends four new ones |
| `e2e/README.md` | G5, G6, G7, G8, G9 | One new section; no existing text rewritten |
| `e2e/fixtures/types.ts` | G8, G9 | Two optional fields appended to types G8 introduces |
| `e2e/tests/streaming-failover/` | — | One new spec, plus **one required edit** to that project's header comment in `playwright.config.ts` (D8) |

`e2e/playwright.config.ts` is the one shared file G10 must edit, and only to extend a comment.
`.github/workflows/e2e-tests.yml` and `scripts/e2e_up.sh` are **not** edited (D8), which keeps
G10 clear of the zizmor ratchet and of G7's unmerged branch.

## Goal

Prove that Dispatcharr's catch-up path works end to end: that the XC ingest fields catch-up
depends on actually reach `Channel.is_catchup`; that all three client entry points reach the same
code; that redirect mode mirrors the client's own URL layout; and that proxy mode's seven-candidate
cascade walks real HTTP against a real server, finds a live shape, and caches it per account.

**The hard constraint, stated once here and repeated in every affected row.** G8's archive is not
time-addressable — the catch-up routes serve the same looping TS whatever `start` they are given
(G8, "Non-goals"). **G10 therefore cannot prove Dispatcharr seeks to the right moment. It proves
the right moment was *asked for*.** Every assertion about time is an assertion on the URL and the
timestamp Dispatcharr sent upstream, read out of the provider's scenario log — never on the bytes
that came back. A passing G10 suite is not evidence of correct seeking, and any row that could be
misread that way says so in its own text.

## Current state

Nothing in `e2e/` touches catch-up. All seven G10 rows in `e2e/COVERAGE.md` are `todo`, and the
`catchup=` row is still phrased as a decision G10 owes (this spec pays it: D12).

The backend unit suite is the *highest*-coverage package in the repo at 78.7%, and that is
genuinely misleading about where the risk sits. What it covers well:

- **Timestamp shapes.** `apps/timeshift/tests/test_helpers.py` has 40 tests over
  `normalize_catchup_timestamp_input`, the four reshapers, `convert_timestamp_to_provider_tz`
  (including Brussels summer/winter and day rollover), duration resolution and stream ordering.
- **Candidate ordering.** `CandidateOrderingTests` (`test_helpers.py:199`) asserts every PATH
  candidate precedes every QUERY candidate and that the first is the colon-dash PATH form.
- **The cascade's control flow.** `StreamFromProviderStatusMappingTests`
  (`apps/timeshift/tests/test_views.py:115`) covers all-404, the 403 short-circuit, the
  PHP-error-200 downgrade, the 416 passthrough, and — at `test_views.py:361` — that a winning
  index is cached and promoted to the front of the next walk.
- **The rollup.** `RollupSelfHealDbTests` (`test_views.py:5535`) covers the aggregate pass, the
  self-heal pass, and its account scoping.
- **Redirect layout selection.** `apps/timeshift/tests/test_catchup_redirect.py` covers
  `client_timeshift_url_layout`, both redirect builders, and the view's redirect/mint branch.

What none of it covers, and what only an E2E test can reach:

1. **The seam between the builder and the walker.** `StreamFromProviderStatusMappingTests.setUp`
   hands `_stream_from_provider` **three hand-written URL strings** — not the seven
   `build_timeshift_candidate_urls` produces. No test in the repo has ever run the real builder's
   output through the real walker.
2. **The seam between the emitted URL and a server that has to parse it.** `_open_upstream` is
   mocked in every unit test, so no candidate URL has ever been through `requests`' URL
   requoting — which matters, because `build_timeshift_url_format_a` interpolates `start` **raw**
   (`helpers.py:412-421`) and the SQL shape therefore puts a literal space in a query string.
3. **The ingest half.** `rollup_channel_catchup_fields` is well tested as a function; nothing
   tests that a provider payload carrying `tv_archive` traverses `collect_xc_streams` →
   `Stream.is_catchup` → the rollup fired from inside `refresh_m3u_account`
   (`apps/m3u/tasks.py:3853`) → a `Channel.is_catchup` a client can read.
4. **The three entry points as routes.** The unit tests call `_serve_catchup` and the view
   functions directly; nothing has ever driven `dispatcharr/urls.py:46` or `:51` over HTTP.
5. **The per-account format cache as a live Redis-backed Django cache.** The one unit test that
   exercises it (`test_views.py:357`) overrides `CACHES` to `LocMemCache` precisely to avoid the
   real one.

A row that re-asserts a timestamp reshape is waste. Every row below is on one of those five seams.

## Verified facts this design rests on

Every row read this session at `8d6db577`.

| Fact | Source | Consequence |
|---|---|---|
| All three client entry points converge on `_serve_catchup(request, user, channel, timestamp, client_duration_hint)` | `apps/timeshift/views.py:130` (PATH), `:151` (QUERY), `:338` (native) | One code path, three routes. The roadmap's claim is exact |
| `client_timeshift_url_layout` returns `"query"` **only** when `timeshift.php` is in the request path; everything else, `/proxy/catchup/` included, is `"path"` | `apps/timeshift/helpers.py:436-446` | Redirect mode mirrors the client's shape. Three routes, two layouts |
| The layout choice is consumed **only** by `_select_catchup_redirect_url` | `views.py:413-419`, `:1742-1748` | Proxy mode never sees it. `_attempt_timeshift_stream` calls `build_timeshift_candidate_urls` unconditionally (`views.py:2673`) |
| `build_timeshift_candidate_urls` returns seven URLs: three PATH forms then four QUERY forms, over exactly **four** distinct `strftime` shapes — `%Y-%m-%d:%H-%M`, `%Y-%m-%d_%H-%M`, `%Y-%m-%d:%H:%M:%S`, `%Y-%m-%d %H:%M:%S` | `apps/timeshift/helpers.py:466-498` | The SQL shape appears in QUERY only. G8's provider accepts these four and rejects the eight hybrids, so a regression that emitted a hybrid fails loudly |
| `build_timeshift_url_format_a` percent-encodes username and password but interpolates `start` **raw** | `helpers.py:412-421` | The SQL candidate carries a literal space; `requests` requotes it to `%20` in transit. G8's parser uses `URLSearchParams` for exactly this |
| A candidate is accepted on 200/206 only with a TS sync byte in the first 1024 bytes; a 200 without sync is downgraded to `last_status = 404` and the walk continues; 401/403/406 (and a 3xx that `requests` did not follow) set `decisive_failure` and `break`; 416 is passed through verbatim | `views.py:3274-3327` | `not-found` → seven attempts; `non-ts-bytes` → seven attempts; `auth-failure` → one. Three distinct, countable log signatures |
| On exhaustion, `last_status == 404` → client 404, `== 403` → 403, **everything else → 400** | `views.py:3336-3341` | A provider 401 reaches the client as `400 "Provider error"`. Deliberate per the code comment, not a defect — but assert 400, not 401 |
| The winning index is cached per account for 3600s under `timeshift:format_idx:<account_id>` in the **Django cache** (Redis, DB 0) and promoted to the front of the next walk | `views.py:3135-3148`, `:3218-3230`, `apps/timeshift/redis_keys.py:64-65` | A cascade test must use a fresh account for the first observation, and can then use the *same* account to observe the promotion |
| The provider timezone is read from the **default** profile's `custom_properties['server_info']['timezone']`, even when a non-default profile wins the capacity walk | `views.py:1657-1664` | The scenario's declared timezone reaches the code through `refresh_account_profiles`, asynchronously |
| `convert_timestamp_to_provider_tz` returns its input unchanged for a falsy value or exactly `"UTC"`, warns and returns unchanged for an unknown zone, and otherwise returns `strftime("%Y-%m-%d:%H-%M")` — **dropping seconds** | `helpers.py:134-160` | Under UTC the client's seconds survive into the colon-seconds candidate; under any other zone they are silently truncated to `:00`. See D11 and defect **C3** |
| `resolve_catchup_duration` prefers the client hint, then EPG, then 120; the hint gets `DURATION_BUFFER_MINUTES = 5` added and is capped at 480 | `helpers.py:21-26`, `:197-233` | A client asking for `/60/` produces a provider request for `65`. Assert the derived value |
| `_serve_catchup`'s preconditions, in order: `is_catchup_enabled(user)` → 403; unparseable timestamp → 400 `"Invalid timestamp"`; no catch-up streams → 400 `"Timeshift not supported for this channel"` | `views.py:353-365` | Each failure returns before any provider contact, so "no request in the log" is the assertion that separates them |
| `get_channel_catchup_streams` returns `[]` unless `channel.is_catchup`, and filters `is_catchup=True, m3u_account__is_active=True` | `apps/channels/utils.py:136-148` | Deactivating the account is a clean way to reach the same 400 without touching a channel |
| `_prepare_catchup_stream_attempt` skips a stream whose account is not `account_type == "XC"` or whose `custom_properties['stream_id']` is absent, and requires an **active default** profile | `views.py:1637-1652` | The four ingest-side preconditions, all satisfied by G8's `seed.xcAccount` plus one refresh |
| With no `session_id` and no pool match: Redirect default profile → **302** to a provider URL; otherwise **301** to the same path with a minted `session_id` | `views.py:406-437` | Proxy mode costs one extra round trip. `StreamClient` follows the 301 by default; the redirect test must open with `redirect: 'manual'` |
| `CoreSettings.is_default_stream_profile_redirect()` compares the **global** `stream_settings.default_stream_profile` against the locked Redirect profile id | `core/models.py:549-564`, `:507-508` | Redirect mode is a container-wide setting with no per-channel override. This is the whole of D8 |
| `tv_archive` is compared as `str(...) in ("1", "True")` and `tv_archive_duration` as `int(... or 0)`, on both the XC path and the standard-M3U `#EXTINF` attribute path | `apps/m3u/tasks.py:1164-1169` (XC), `:1383-1388` (M3U) | Dispatcharr **reads** catch-up advertising off an ingested M3U. It never writes it. See D12 |
| `rollup_channel_catchup_fields(account_id)` runs inside `_refresh_single_m3u_account_impl` after auto-sync, and covers every channel holding a stream from that account | `apps/m3u/tasks.py:3853`, `:1963-2014` | A channel wired after the first refresh needs a second refresh. G8's D19 already established this |
| `/output/m3u`'s `#EXTINF` carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, an optional `tvc-guide-stationid`, and `group-title` — and nothing else | `apps/output/views.py:298-306` | No `catchup=`, `catchup-source=`, `catchup-days=` or `timeshift=`. D12 |
| XC `get_live_streams` emits `tv_archive` / `tv_archive_duration` from `channel.is_catchup` / `catchup_days`, gated on `is_catchup_enabled(user)` | `apps/output/views.py:727-751` | The advertisement exists on the XC surface and only there. The asymmetry is the evidence for D12 |
| `_user_can_access_channel` checks `user_level` and Channel Profile membership. `hide_adult_content` appears at **twelve** sites across `apps/output/`, `apps/epg/`, `apps/channels/` and `apps/vod/`, and **nowhere** under `apps/timeshift/` | `views.py:771-786`; `grep -rn hide_adult_content apps/` | Verified defect **C1**. An adult catch-up channel is unlistable and still streamable |
| The root PATH/QUERY routes authenticate against `user.custom_properties['xc_password']` with `hmac.compare_digest`, not JWT | `views.py:758-768` | Two of the three entry points **spend no login budget**. `seed.user({ custom_properties: { xc_password } })` is enough |
| `xc_password` must match `^[A-Za-z0-9._@-]+$`, and is stripped from self-service PATCHes | `apps/accounts/serializers.py:16`, `:110-116`; `apps/accounts/api_views.py:294` | Seed it as admin at creation; do not try to set it as the user |
| `POST /api/catchup/sessions/` is `IsStandardUser`, requires `channel.is_catchup` **and** a non-empty `get_channel_catchup_streams`, and returns `playback_url = /proxy/catchup/<uuid>?session_id=<id>` | `apps/timeshift/api_views.py:67-69`, `:141-151`; `apps/timeshift/sessions.py:67` | The fourth reachable surface into the same code, and the one the OpenAPI description calls "recommended" |
| Playwright projects map 1:1 to CI matrix jobs `[pristine, seeded, streaming, streaming-failover, streaming-greybox, lifecycle]`, each booting its own container | `.github/workflows/e2e-tests.yml:167-172`; `e2e/playwright.config.ts` | A global settings mutation is contained within one project. `streaming-failover` and `streaming-greybox` are `workers: 1` for exactly this reason |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Every time assertion is read off the provider's scenario log, never off the bytes.** Each such row's text names the limit | G8's archive is not time-addressable. This is the roadmap's binding constraint and the single most important thing about this goal. The alternative — a time-addressable archive — is a build of its own and a new goal, not a G10 task |
| D2 | **G10 adds no provider capability.** Every fault and field it uses is one G8 ships: `catchup-layout-404 { layout }`, `no-tv-archive`, `auth-failure`, `not-found`, `non-ts-bytes`, the scenario `account.server_info.timezone` override, and `xc: true` | The wave-4 contract. If a row needed more, it would be named as a G8 change with its cost; none does |
| D3 | **The cascade rows go beyond G8's plumbing proof 5, or they are not written.** G8 already proves "PATH blocked → three PATH 404s → a QUERY 200". G10 adds the four *timestamp shapes*, the *cached index*, its *per-account scoping*, and the three *failure classes* | Duplicating a plumbing proof is the cheapest way to make this goal look bigger than it is |
| D4 | **No row asserts a URL string shape that `test_helpers.py` already asserts.** G10 asserts what the *provider recorded*, which is the same information arrived at through the real builder, `requests`' requoting, and a real parser | 78.7% coverage means the string algebra is done. The seams are not |
| D5 | **Each test creates its own XC account**, and the cascade test says in a comment that this is load-bearing | `timeshift:format_idx:<account_id>` persists for an hour in a Redis shared with everything else. A test reusing another test's account inherits its cascade winner and passes for the wrong reason |
| D6 | **The provider timezone is polled off the account profile before any timestamp is asserted** | `refresh_account_profiles` is a separate Celery task; the profile reaches `server_info.timezone` after the refresh the test waited on. And `convert_timestamp_to_provider_tz` treats a missing value *identically* to `"UTC"` — so a test that reads it too early still passes, for the wrong reason. G8 flagged this; G10 is where it bites |
| D7 | **The two root entry points are driven with `xc_password` auth, not JWT** | `views.py:758-768` authenticates them that way, `seed.user` creates the row for free, and the suite's whole login budget is 3/minute across every worker and project. Two of the three entry points costing zero logins is a real saving, not a stylistic one |
| D8 | **Redirect mode goes in `streaming-failover`, and that project's header comment gains a second global. No new project, no CI matrix job, no workflow edit** | Redirect mode is only reachable by flipping the **global** `stream_settings.default_stream_profile` (`core/models.py:549`), and the repo's established answer to a spec that mutates a global is a `workers: 1` project. Of the two, `streaming-greybox` is reserved for container-wide process observation; `streaming-failover` already hosts the global-mutation pattern (`failover-buffering.spec.ts` read-modify-writes `proxy_settings` and restores it). **Rejected: a new `catchup` project** — it would require editing `.github/workflows/e2e-tests.yml`, which arms the zizmor ratchet on every legacy finding in that file and collides with G7's unmerged branch, for the benefit of two rows. G8's D20 and D21 made the same call. The cost is honest and must be paid in the diff: `streaming-failover`'s config comment currently argues *one* invariant precisely, and adding a second global without extending it would leave the next reader with a comment that is quietly incomplete |
| D9 | **The redirect rows assert the `Location` header and the provider log's *silence*** | Redirect mode hands the client a URL and fetches nothing. "Dispatcharr made no upstream request" is half the definition of the mode and costs one log read |
| D10 | **The global default stream profile is restored in a `finally`, and the test asserts up front that it was not already Redirect** | Exactly `failover-buffering.spec.ts`'s pattern (`e2e/tests/streaming-failover/failover-buffering.spec.ts:100-112`), and for its stated reason: a timed-out prior attempt plus CI's `retries: 1` would otherwise bake the mutated value in permanently |
| D11 | **The timezone row uses a fixed winter start date** | `Europe/Brussels` is `+01:00` in January and `+02:00` in July. Pinning the date makes the expected provider timestamp a constant instead of a function of the day the suite runs |
| D12 | **The missing `catchup=` M3U attribute is a defect. G10 files it, and pins it with a convention-agnostic `test.fail()`** | See "The `catchup=` ruling" below |
| D13 | **The credential-encoding skew gets no inventory row.** It is filed as a defect (**C2**) and named in Non-goals | See "The credential-encoding ruling" below |
| D14 | **Global kill switches are out of scope.** `system_settings.catchup_enabled` and per-user `catchup_enabled` are unit-tested (`apps/channels/tests/test_catchup_utils.py`) and would cost a second container-wide mutation to pin | The programme's failure mode is goals that grow. One global mutation in this goal, not two |

## The `catchup=` ruling

**It is a defect. G10 files it on the fork and pins it with a `test.fail()`.** Four reasons, in
descending weight:

1. **Dispatcharr reads the attribute family it does not write.** `apps/m3u/tasks.py:1383-1388`
   parses `tv_archive` and `tv_archive_duration` out of an ingested playlist's `#EXTINF`
   attributes and sets `Stream.is_catchup` from them. The reader exists; the writer
   (`apps/output/views.py:298-306`) has no corresponding branch at all. A codebase that can
   consume a signal it never produces is asymmetric with itself, and that is the strongest
   available evidence of an omission rather than a decision.
2. **There is no expression of intent anywhere.** No comment, no setting, no branch says "M3U
   clients do not get catch-up". By contrast the XC emitter has an explicit, considered
   `catchup_allowed` gate (`apps/output/views.py:727`) — the author thought about *who* may see
   catch-up advertised, on the surface where it is advertised at all. The M3U builder simply does
   not participate.
3. **The capability is complete and routed.** `dispatcharr/urls.py:46` and `:51` serve both
   layouts today. This is not a feature request for catch-up; it is the one line that tells a
   client the catch-up it already serves exists.
4. **The consequence is a silent dead end.** For a channel with `is_catchup: true` and a working
   archive, an M3U-only client (Kodi/IPTV Simple, VLC, TiviMate on an M3U profile) shows no
   catch-up affordance. The user's only signal is absence.

**Why the test is convention-agnostic, and why that is not a dodge.** The de-facto M3U conventions
are three and mutually incompatible: `catchup="default"` with a `catchup-source=` URL template,
`catchup="xc"`, and `catchup="append"` with a query suffix. Dispatcharr serves *two* upstream
layouts, so which one it should advertise is a product decision nobody has made. A `test.fail()`
asserting one convention would pin an arbitrary choice and would go green **the wrong way** if the
maintainer picked another — the exact failure mode `test.fail()` exists to avoid. So the assertion
is: for a channel with `is_catchup: true`, the `#EXTINF` carries *some* `catchup` attribute, and a
`catchup-days` equal to `Channel.catchup_days`. Both hold under all three conventions; neither
constrains the choice. The issue body carries the three candidates and this reasoning, so whoever
fixes it is choosing, not guessing.

**Placement.** The row is G10's — `e2e/COVERAGE.md:83` already assigns it here, and the fact that
makes it a defect is catch-up's, not output's. The *surface* is `/output/m3u`, which is G5's, so
the test goes in a G10-named file (`catchup-m3u-advertisement.spec.ts`) and **not** in whatever
G5 names its `/output/m3u` spec. G5 owns "the M3U parses and every URL is well-formed"; G10 owns
"the M3U advertises catch-up".

## The credential-encoding ruling

`collect_xc_streams` builds the live playback URL by raw interpolation —
`f"{server_url}/live/{username}/{password}/"` at `apps/m3u/tasks.py:933-936` — while
`build_timeshift_url_format_b` percent-encodes both with `quote(..., safe='')`
(`helpers.py:424-433`). The skew is real. **It gets no inventory row.** Three reasons:

1. **It is unobservable for almost every credential.** A space requotes to `%20` on both paths; a
   `+` is literal in a path segment either way; `%` normalises the same. The skew only becomes
   visible for `/`, `?` and `#` — characters that are structural in a URL path.
2. **Where it *is* visible, catch-up is the correct side.** For `?` and `#` the raw live URL is
   the broken one. A row here would be asserting a defect in the *live* path, which is G4's
   territory, not catch-up's.
3. **A third builder disagrees with both.** `get_transformed_credentials`
   (`apps/m3u/tasks.py:3067-3103`) rebuilds a synthetic `/live/{user}/{pass}/1234.ts` URL and
   recovers the credentials by splitting the transformed path on `/` — so a credential containing
   `/` breaks credential *extraction* before either builder runs. A test would be asserting
   against three interacting defects with no single correct answer, and would need a G8 scenario
   parser change to declare such credentials in the first place.

Filed as **C2** below: one issue naming all three builders and asking for one encoding policy.

## Project topology

```
bootstrap ──┬─→ seeded              (existing) +3 specs   4 workers,  30s
            ├─→ streaming           (existing) +3 specs   2 workers, 300s
            └─→ streaming-failover  (existing) +1 spec    1 worker,  300s
```

No new project, no new CI matrix job, no `scripts/e2e_up.sh` change (D8).

## Test inventory

Fourteen tests across seven files. Every test creates its own scenario, its own XC account and its
own channels, and scopes every assertion to them (roadmap rule 4).

| # | COVERAGE row | File / project | Mechanism | Est. |
|---|---|---|---|---|
| 1 | Catch-up / XC live ingest fields | `seeded/catchup-ingest.spec.ts` | XC scenario, two named channels, one declaring `tv_archive: 1, tv_archive_duration: 7` and one declaring neither. `seed.xcAccount` + `waitFor.m3uRefreshComplete`. Assert `Stream.is_catchup`/`catchup_days` are `true`/`7` and `false`/`0` respectively, located by generated name. Wire the catch-up stream to a channel, refresh again (D19 of G8), assert `Channel.is_catchup` and `catchup_days === 7` | 60s |
| 2 | (same row) self-heal | `seeded/catchup-ingest.spec.ts` | With row 1's state established, arm `no-tv-archive` and refresh a third time. Assert the stream's `is_catchup` is `false` and the **channel's** is back to `false` with `catchup_days === 0` — the self-heal pass of `rollup_channel_catchup_fields` reached from ingest, not called directly | 55s |
| 3 | *(new row)* Catch-up preconditions each fail closed with no upstream contact | `seeded/catchup-preconditions.spec.ts` | Four `GET /proxy/catchup/<uuid>` calls against one scenario: a channel with `is_catchup: false` → 400 `"Timeshift not supported for this channel"`; a valid channel with `?start=not-a-time` → 400 `"Invalid timestamp"`; with `start` omitted → 400 `"Missing start parameter"`; a valid catch-up channel whose account has been PATCHed `is_active: false` → 400. Then assert the scenario log contains **zero** catch-up requests. The zero is the point: a break in the five-link chain must not reach the provider | 45s |
| 4 | *(new row)* The native session API is the fourth surface into the same code | `seeded/catchup-session-api.spec.ts` | `POST /api/catchup/sessions/` for a catch-up channel → 201; assert `playback_url === '/proxy/catchup/<uuid>?session_id=' + session_id` and `expires_at` is in the future. Same call for a non-catch-up channel → 400 `"Catch-up not supported for this channel"`. Same call as the `streamer` principal (level 0) → 403, from `IsStandardUser` | 30s |
| 5 | Catch-up / **Gap:** no `catchup=` in the generated M3U → **known-bug** | `seeded/catchup-m3u-advertisement.spec.ts` | `test.fail()`. For a channel with `is_catchup: true, catchup_days: 7`, assert its `#EXTINF` in `/output/m3u` carries *some* `catchup` attribute and `catchup-days="7"` (D12: convention-agnostic on purpose). Then, **passing**, assert the same channel in `player_api.php?action=get_live_streams` carries `tv_archive: 1` and `tv_archive_duration: 7` — the asymmetry that makes the first half a defect rather than a preference | 30s |
| 6 | Catch-up / Proxy mode end to end | `streaming/catchup-proxy-mode.spec.ts` | `GET /proxy/catchup/<uuid>?start=<UTC>&duration=60`; `StreamClient` follows the 301 that mints the session (`views.py:437`). Assert TS-aligned bytes with `expectTsAligned`. Then assert the scenario log holds exactly one catch-up request carrying the account's credentials, the declared provider `stream_id`, the start **unchanged** (the scenario declares `timezone: "UTC"`), and duration **65** — the client's 60 plus `DURATION_BUFFER_MINUTES`. **This proves the right moment was asked for. It does not prove Dispatcharr seeks to it: the fake archive serves the same loop whatever `start` it is given** | 90s |
| 7 | (same row) both root entry points reach the same code | `streaming/catchup-proxy-mode.spec.ts` | `seed.user({ custom_properties: { xc_password } })` — no login spent (D7). Drive `/timeshift/<u>/<p>/60/<start>/<channel.id>.ts` and `/streaming/timeshift.php?username=&password=&stream=<channel.id>&start=&duration=60`. Both stream TS-aligned bytes; both record a provider catch-up request for the same `stream_id` and duration `65`. Same caveat as row 6 | 100s |
| 8 | *(new row)* `hide_adult_content` is not applied in `apps/timeshift/views.py` → **known-bug** | `streaming/catchup-proxy-mode.spec.ts` | `test.fail()`. A Standard user with `hide_adult_content: true` and an `xc_password`, against a catch-up channel with `is_adult: true`. Assert the channel is absent from that user's `player_api.php?action=get_live_streams` (passes — `apps/output/views.py:148-160`), then assert `/timeshift/<u>/<p>/…` is **refused** — the correct behaviour. It currently streams. Defect **C1** | 60s |
| 9 | Catch-up / The seven-candidate cascade | `streaming/catchup-cascade.spec.ts` | A **fresh** account (D5). Arm `catchup-layout-404 { layout: 'path' }`. Drive `/proxy/catchup/<uuid>`. Assert the log shows exactly three PATH requests answered 404 — carrying `%Y-%m-%d:%H-%M`, `%Y-%m-%d_%H-%M` and `%Y-%m-%d:%H:%M:%S` in that order — then one QUERY request answered 200, and that the client received TS-aligned bytes. The four shapes are asserted here and nowhere else: G8's provider rejects the eight hybrid separator combinations, so a Dispatcharr regression that emitted one shows up as a 400, not a silent pass | 110s |
| 10 | (same row) the cached index, and its account scoping | `streaming/catchup-cascade.spec.ts` | Immediately re-drive row 9's account with the fault still armed; assert the log for the second request holds **one** request, the QUERY winner, tried first — `timeshift:format_idx:<account_id>` promoting it (`views.py:3218-3230`). Then create a **second** account against the same scenario and drive it: assert its first attempt is the colon-dash PATH form again, proving the cache is per-account and not per-scenario | 110s |
| 11 | Catch-up / Decisive failures stop the cascade; soft ones do not | `streaming/catchup-cascade.spec.ts` | Three arms on fresh accounts. `auth-failure` → exactly **one** catch-up request in the log, client `400` (`views.py:3341`; a 401 is *not* mapped through — assert 400, not 401). `not-found` → exactly **seven**, client `404 "Catch-up not available yet"`. `non-ts-bytes` → exactly **seven**, all answered 200, client `404` — the "200 with no TS sync is downgraded to a soft 404" branch (`views.py:3312`), which is the one a real provider's PHP error page hits | 130s |
| 12 | Catch-up / `server_info.timezone` drives the conversion | `streaming/catchup-provider-timezone.spec.ts` | Scenario declares `account.server_info.timezone: 'Europe/Brussels'`. **Poll the account profile's `custom_properties.server_info.timezone` until it is that value before asserting anything** (D6 — `refresh_account_profiles` is async, and a missing value behaves identically to `"UTC"`, so an early read passes for the wrong reason). Drive a fixed **January** start of `2026-01-15:12-00` (D11); assert the provider recorded `2026-01-15:13-00`, `+01:00`. Again: the moment asked for, not sought to | 90s |
| 13 | *(new row)* A non-UTC provider timezone truncates the requested start to the minute → **known-bug** | `streaming/catchup-provider-timezone.spec.ts` | `test.fail()`. Same Brussels scenario, start `2026-01-15:12-00-45`. Assert the colon-seconds candidate the provider records carries `:45`. It carries `:00`: `convert_timestamp_to_provider_tz` reformats through `strftime("%Y-%m-%d:%H-%M")` (`helpers.py:160`), dropping seconds before `build_timeshift_candidate_urls` re-derives the colon-seconds shape from it. Under `"UTC"` the same start keeps its seconds — the row asserts that half **passing**, in the same test, so the inconsistency is the finding rather than the truncation alone. Defect **C3** | 70s |
| 14 | Catch-up / Redirect mode mirrors the client's layout | `streaming-failover/catchup-redirect.spec.ts` | Read `/api/core/settings/`, find `key === 'stream_settings'`, assert `default_stream_profile` is **not** already the locked Redirect id (D10), read-modify-write it to Redirect, restore in `finally`. Open all three entry points with `redirect: 'manual'`. Assert: `/proxy/catchup/<uuid>` → 302 with a **PATH** `Location`; the root `/timeshift/...` → 302 PATH; `/streaming/timeshift.php` → 302 **QUERY**. Each `Location` carries the account credentials, the provider `stream_id` and duration `65`. Finally assert the scenario log holds **no** catch-up request at all (D9) — redirect mode hands off and fetches nothing | 120s |

Seven of G10's `COVERAGE.md` rows are addressed. **Four rows are added** in the same PR (rule 3):
the preconditions row, the session-API row, the `hide_adult_content` known-bug row, and the
seconds-truncation known-bug row. The `catchup=` row moves from `todo` to `known-bug` with its
issue link, and the four `test.fail()` rows carry theirs.

## Fixture additions

Deliberately small: G8 ships the machinery, G10 consumes it.

- **`e2e/fixtures/types.ts`** — `ScenarioRequest`'s `account?: Partial<AccountEnvelope>` (G8) is
  already sufficient for the timezone override, so nothing new is needed for it. Add
  `tvArchive?: boolean` and `tvArchiveDays?: number` to G8's `ChannelSpec` **only if** G8 does not
  already expose them; check before writing, and if G8 declares `tv_archive` on every XC channel
  unconditionally, rows 1 and 2 need the fields and this is the one G8 gap G10 may close itself
  (it is a scenario field, not a provider behaviour).
- **`e2e/tests/streaming/helpers.ts`** — one exported `catchupRequests(log, scenarioId)` that
  filters `LogEntry[]` to `kind === 'request'` entries on the two catch-up routes and parses out
  `layout`, `username`, `stream`, `start` and `duration`. Five of the fourteen rows read the log
  the same way; writing that parse five times is how the shapes drift apart.
- **`playwright.config.ts`** — no new project. The `streaming-failover` header comment gains the
  second global it now hosts (D8). This is a required deliverable, not a nicety: the existing
  comment argues one invariant precisely and would otherwise become quietly wrong.
- **`e2e/README.md`** — one new section, "Catch-up", stating the archive limit (D1) in the same
  place a test author meets the fault catalogue, and the per-account format-cache hazard (D5).

No new Playwright fixture is registered on `test.extend`.

## Candidate product defects

Filed on the fork with an explicit `--repo D10Scot/Dispatcharr` (roadmap rule 5 and
`docs/agents/issue-tracker.md`). **G10 files; G10 does not patch.**

- **C1 — verified. `hide_adult_content` is not applied on the catch-up path.** The filter appears
  at twelve sites across `apps/output/`, `apps/epg/`, `apps/channels/` and `apps/vod/`, and at
  none under `apps/timeshift/`. `_user_can_access_channel` (`views.py:771-786`) checks
  `user_level` and Channel Profile membership only. A Standard user with
  `hide_adult_content: true` cannot list an adult channel through any output surface and can
  still stream its archive. Already recorded in `CLAUDE.md`; pinned by row 8.
- **C2 — verified. Three builders disagree on credential encoding.**
  `apps/m3u/tasks.py:933-936` interpolates the provider username and password raw into the live
  playback URL; `apps/timeshift/helpers.py:424-433` percent-encodes them; and
  `apps/m3u/tasks.py:3067-3103` recovers them by splitting a synthetic path on `/`, which a
  credential containing `/` breaks outright. Observable only for `/`, `?` and `#`, and the *live*
  path is the broken side. Filed, not tested (D13).
- **C3 — verified. A non-UTC provider timezone silently truncates the requested start to the
  minute.** `convert_timestamp_to_provider_tz` reformats through `strftime("%Y-%m-%d:%H-%M")`
  (`helpers.py:160`), so the colon-seconds candidate — one of the seven, and the one some
  providers require — always carries `:00`. Under `"UTC"` the same start keeps its seconds
  (`helpers.py:145-146` returns the input unchanged). The precision of the moment Dispatcharr asks
  for therefore depends on a field the provider declares. Pinned by row 13.
- **C4 — suspected, and deliberately not tested.** `catchup_proxy` calls
  `network_access_allowed(request, "STREAMS")` with **no user** (`views.py:285`), while
  `_timeshift_proxy_impl` passes it (`views.py:166`, `"XC_API"`) and
  `CatchupSessionCreateAPIView` passes it (`api_views.py:110`). A user restricted by
  `custom_properties.allowed_networks['STREAMS']` can therefore mint a session from a permitted
  network and play it from a forbidden one. Structural rather than an oversight — at that point in
  the view the principal is not yet resolved — and it matches `stream_ts`'s documented, deliberate
  concession (`CLAUDE.md`, "Auth — two opposite defaults"). Recorded here so the next reader does
  not have to re-derive it; **no row, no issue** unless a maintainer disagrees with the precedent.

## Non-goals

- **Proving Dispatcharr seeks to the requested moment.** G8's archive is not time-addressable.
  This is the goal's defining limit (D1), it is stated in every affected row, and closing it means
  generating a distinct asset per requested instant — a new goal, not a G10 task.
- **Global catch-up kill switches.** `system_settings.catchup_enabled` and per-user
  `catchup_enabled` are covered by `apps/channels/tests/test_catchup_utils.py` and would cost a
  second container-wide mutation (D14).
- **The catch-up session *pool*.** `_find_matching_pool_session`, fingerprint adoption, scrub
  displacement, EOF probes, presentation windows, `final_url` CDN caching, and the stats client —
  roughly 1,500 lines of `views.py` and the subject of nine unit-test classes. It is a
  reconnect-behaviour surface, not a catch-up-correctness one, and pinning it E2E would double
  this goal. Named here so its absence reads as a decision.
- **Range and seek on the catch-up path.** `_parse_client_range`, `_build_downstream_length_headers`
  and the 416 passthrough are unit-tested and, against a `Content-Length`-less looping archive,
  are not meaningfully observable. Range against a *finite* asset is G9's, on the VOD path.
- **`xmltv.php`'s catch-up lookback and `has_archive`.** `resolve_xc_epg_prev_days`
  (`apps/channels/utils.py:83-115`), the per-channel `catchup_days` expansion
  (`apps/output/views.py:892-898`) and the `has_archive` flag (`:985-988`) are catch-up-driven,
  unit-tested, and sit on a surface `COVERAGE.md:52` assigns to G5. Worth a later row; not G10's.
- **The credential-encoding skew** (D13, C2).
- **Any product change.** Four `test.fail()`s and four issues; not one line of `apps/` is edited.

## Risks

- **The five-link precondition chain gives a terse error and no upstream contact when it breaks**
  (G8 flagged this; it is sharper here because eleven of fourteen rows sit behind it). A row that
  only asserts the final outcome reports "400 Bad Request" for any of five distinct causes.
  Mitigation: rows 1–4 establish and assert each link independently before any streaming row runs,
  and row 3 asserts the *empty log* as a first-class signal.
- **`refresh_account_profiles` is asynchronous, and a missing timezone behaves exactly like
  `"UTC"`.** Row 12 would pass without the conversion ever happening. Mitigation: D6 makes the
  poll a precondition of the assertion, not a convenience.
- **The format cache outlives the test.** `timeshift:format_idx:<account_id>` has a 3600s TTL in
  the shared Django cache. Mitigation: D5 — a fresh account per cascade observation, and row 10
  turns the hazard into the assertion.
- **The global default stream profile is the widest blast radius in this goal.** A test that dies
  between the write and the restore leaves every subsequent channel in the container on Redirect,
  and CI's `retries: 1` would then read the mutated value as the original and write it back
  permanently. Mitigation: D10's up-front guard plus a `finally`, copied from
  `failover-buffering.spec.ts` rather than reinvented — and `streaming-failover` is its own
  container in CI, so the damage cannot cross a project.
- **`rollup_channel_catchup_fields` is raw Postgres SQL** (`bool_or`, `FILTER`, two statements —
  `apps/m3u/tasks.py:1978-2014`). It cannot run under the `TEST_USE_SQLITE=1` fallback, which is
  irrelevant to E2E but relevant to anyone who tries to reproduce rows 1–2 as a unit test.
- **Rows 9–11 are the long pole**, at roughly six minutes of the goal's ~17. They are also the
  reason the goal exists: the roadmap calls the cascade "the part most likely to be wrong and the
  part nothing observes today", and rows 9–11 are the only place in the programme where a real
  builder, `requests`' requoting, a strict parser and a live per-account cache meet.
- **G10 may find that G8's `ChannelSpec` does not let a scenario declare a channel *without*
  `tv_archive`.** Rows 1 and 2 need both states. If so, that is a two-field scenario addition, not
  a provider behaviour — the one G8 gap G10 closes itself rather than escalating (see Fixture
  additions).
