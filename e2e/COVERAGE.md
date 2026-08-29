# E2E Coverage Inventory

The shared worklist for all ten goals. **Update this in the same PR as the
tests.** Status: `todo` / `done` / `known-bug` (asserted correct, marked
`test.fail()`, issue filed).

| Area | Flow | Goal | Status |
|---|---|---|---|
| Setup | First-run superuser creation and login | G1 | done |
| Harness | Authenticated session via storageState | G1 | done |
| Harness | API client survives token expiry | G1 | done |
| Harness | Namespaced seeding | G1 | done |
| Harness | Non-admin principals at two user levels (asPrincipal) | G1 | done |
| Harness | Login budget: driving a fixed principal spends no login | G1 | done |
| Harness | REST polling and WebSocket waiting | G1 | done |
| Harness | WebSocket queue semantics and event correlation | G1 | done |
| Harness | Byte-level TS stream reading | G1 | done |
| Harness | Source factories (stream profile, M3U, EPG) | G1 | done |
| Upstream | Fake upstream provider: playlist, EPG, paced TS loop | G2 | done |
| Upstream | Fault injection (eight faults, control API) | G2 | done |
| Upstream | Plumbing proof: M3U ingest → declared channels appear | G2 | done |
| Upstream | Plumbing proof: stream-through via `/proxy/ts/stream/<uuid>` | G2 | done |
| Sources | M3U account create → refresh → streams appear | G3 | todo |
| Sources | EPG source create → refresh → programme data | G3 | todo |
| Sources | Channel creation from streams | G3 | todo |
| Sources | Auto channel sync | G3 | todo |
| Sources | Channel groups and Channel Profiles | G3 | todo |
| Sources | Logo upload and assignment | G3 | todo |
| Streaming | Single client receives aligned TS | G4 | done |
| Streaming | N clients share one upstream | G4 | done |
| Streaming | Mid-stream switch does not disturb clients | G4 | done |
| Streaming | Failover: dead air | G4 | done |
| Streaming | Failover: connect failure | G4 | done |
| Streaming | Failover: buffering (ffmpeg only) | G4 | done |
| Streaming | Client teardown releases the upstream | G4 | done |
| Streaming | Stream Profile: Redirect | G4 | done |
| Streaming | Stream Profile: Proxy | G4 | done |
| Streaming | Stream Profile: FFmpeg | G4 | done |
| Streaming | Output Profile shared per (channel, profile) | G4 | done |
| Streaming | Ownership lease is fenced against a second concurrent owner — attempted by deleting `live:channel:{uuid}:owner` under a running Proxy-profile stream and polling for a second worker to claim it; confirmed empirically unprovable from outside the container: the same owning worker's own `ProxyServer._start_cleanup_thread` cleanup loop notices the missing key and calls `extend_ownership()`, re-`SET NX`-ing the identical worker id well under a second later every run (measured at ≤500ms), because that loop is the only code path with a local `StreamManager` for the channel; a follower worker never contends because `stream_ts` only lets a worker attempt ownership when channel metadata is absent too, which a bare owner-key delete does not cause — so no black-box HTTP/Redis manipulation can land a second `SET NX` in the sub-second gap. The untried lever is co-expiring `live:channel:{uuid}:metadata` with the owner key, which is what would open the metadata-gated follower path in `stream_ts`; that is a larger provocation than this row's brief allowed and needs its own scoping. See G4 task-12 report for the full trace. | G4 | todo |
| Output | /output/m3u parses, every URL is well-formed, and one is streamed end to end | G5 | todo |
| Output | /output/m3u/&lt;profile_name&gt; scopes to Channel Profile membership | G5 | todo |
| Output | /output/epg is valid XMLTV and carries programmes for the seeded channels | G5 | todo |
| Output | HDHomeRun discovery, device XML, lineup and lineup status | G5 | todo |
| Output | Xtream authentication handshake (user_info / server_info envelope) | G5 | todo |
| Output | Xtream live actions: get_live_categories, get_live_streams, get_short_epg, get_simple_data_table | G5 | todo |
| Output | Xtream VOD and series actions answer an empty catalogue without erroring | G5 | todo |
| Output | Xtream get.php and xmltv.php at the site root | G5 | todo |
| Output | Authorization matrix by user_level — Xtream only, the one output surface with a principal | G5 | todo |
| Output | hide_adult_content across the Xtream listing paths | G5 | todo |
| Output | /output/m3u, /output/epg and the HDHR lineup are unauthenticated by design, gated only by the M3U_EPG network ACL | G5 | todo |
| Accounts | Token refresh with a deleted user's token 500s instead of 401 ([#12](https://github.com/D10Scot/Dispatcharr/issues/12)); needs a `test.fail()`, and pinning it costs one login | G5 | known-bug |
| Upstream | Fake provider speaks Xtream Codes: `player_api.php` auth envelope and the seven catalogue actions `core/xtream_codes.Client` calls | G8 | todo |
| Upstream | Fake provider serves a finite VOD asset with `Content-Length`, `Accept-Ranges`, 206 + `Content-Range` and 416 | G8 | todo |
| Upstream | Fake provider answers both catch-up layouts and records the credentials, stream id, start timestamp and duration it was asked for | G8 | todo |
| Upstream | Four new faults: `xc-auth-envelope`, `no-tv-archive`, `catchup-layout-404`, `range-unsupported` | G8 | todo |
| Upstream | Plumbing proof: XC account ingest → declared live streams appear | G8 | todo |
| Upstream | Plumbing proof: VOD catalogue ingest → `Movie`, `Series` and `Episode` rows appear | G8 | todo |
| Upstream | Plumbing proof: one VOD byte read through `/proxy/vod/` | G8 | todo |
| Upstream | Plumbing proof: a catch-up URL reaches the provider in each layout | G8 | todo |
| Upstream | Plumbing proof: the candidate cascade falls back when one layout 404s | G8 | todo |
| Upstream | **Gap:** the fake archive is not time-addressable — it serves the same looping TS whatever `start` it is asked for. Nothing proves Dispatcharr seeks to the right moment, only that it asks for the right one. Owned by G10, which must say so in every row it writes | G8 | todo |
| Upstream | **Gap:** the catch-up timestamp parser (`parseCatchupTimestamp`, `e2e-upstream/src/xc/catchup.ts`) over-accepts. Its regex is `[:_ ]…[-:]…(?:[-:]\d{2})?`, built to admit the four shapes `build_timeshift_candidate_urls` (`apps/timeshift/helpers.py:466-498`) actually emits, but it also matches shapes no candidate ever produces (e.g. `2026-08-29 14-00`, mixing the SQL separator with the PATH minute separator; `2026-08-29:14:00`, missing the required minute-second separator pair) and performs no calendar validation — `2026-13-45:99-99` yields a non-null `startIso` and is served with a `200`. Safe for this provider: over-acceptance can only ever widen what's served, never produce a false cascade rejection, so it cannot make a G8 test lie. But it means **this provider can prove a candidate URL was *parseable*, never that it was *correct*** — it cannot fail a request for using the wrong strftime shape, wrong separator, or an invalid calendar date. G10's premise includes verifying the seven-candidate cascade constructs the *right* URLs in the *right* order; this provider cannot be the thing that proves that. If G10 needs shape-correctness (not just "the provider accepted something"), assert on the request as logged — `ScenarioLog`'s `request` entries carry the exact `path`/`search` Dispatcharr sent (`logRequest`, `e2e-upstream/src/server.ts`) — and check it against the literal strftime output, rather than inferring correctness from a `200` | G8 | todo |
| Upstream | **Known defect:** `collect_xc_streams` (`apps/m3u/tasks.py:933-936`) builds the live stream URL with raw, unencoded account credentials, unlike `build_timeshift_url_format_b` (`apps/timeshift/helpers.py:424-433`), which percent-encodes both fields with `quote(str(x), safe='')`. A credential containing `/` (or any other character `quote` would escape) therefore breaks live playback while the identical credential works for catch-up. Filed as [#61](https://github.com/D10Scot/Dispatcharr/issues/61) per spec D25 (the tracker entry costs nothing and the defect is real and verified), but per this goal's own Global Constraints — a build hands findings to the goal that will actually assert them — no `test.fail()` exists in `e2e-upstream` for it: this provider's seed helpers only generate sanitised credentials, and a hand-built unsanitised-credential request against `/live/` is a malformed URL by construction (too many path segments), so a test asserting either outcome would be vacuous. Verified reachable and demonstrated with a passing control test in `e2e-upstream/test/xc-router.test.ts` (`XC live playback — credential encoding`): the same slash-bearing credential succeeds when percent-encoded into the path, as `build_timeshift_url_format_b` does. Owned by whichever of G9/G10 first ingests a real XC account with an unsanitised (slash- or percent-bearing) credential — that task should add the seed support and the `test.fail()` this build could not | G8 | todo |
| Upstream | **Known defect (this provider, not the product):** `parseScenarioRequest`'s `xc` door check (`e2e-upstream/src/scenario.ts:591`) guards with `request.password === undefined`, not a falsy check, so `{ xc: true, username: 'u', password: '' }` passes the door despite the very next line's own comment stating "an empty password can never match the `/live/` path form" — the check the comment describes is not the check the code performs. A scenario created this way is accepted, echoed back with `password: ''`, and is then unservable the moment a real client streams from it, with no error at creation time to explain why. Found while implementing `seed.xcAccount`, which is deliberately **stricter than this door**: it throws on a falsy `scenario.password` (empty string included), not just `undefined`, specifically because this gap means the provider's own validation cannot be relied on to catch it. Not fixed here — `e2e-upstream/` is in scope for G8's own tasks, not for a fixture-consumer fix round. G9/G10 should not construct an XC scenario with an empty-string password expecting the door to reject it | G8 | todo |
| VOD | Catalogue ingest: categories, movies and series land as `VODCategory`, `Movie`, `Series` and their `M3U*Relation` rows | G9 | todo |
| VOD | Category gating: `M3UVODCategoryRelation.enabled`, `auto_enable_new_groups_vod`/`_series`, and the `Uncategorized` fallback | G9 | todo |
| VOD | Episode ingest on demand via `GET /api/vod/series/<pk>/provider-info/`, for both the object-keyed and array-keyed `episodes` shapes | G9 | todo |
| VOD | Advanced movie data: `get_vod_info` merges into `Movie` and `M3UMovieRelation.custom_properties` without clobbering list-sync fields | G9 | todo |
| VOD | XC VOD and series actions against a real catalogue (G5 covers only the empty-catalogue shape, and `get_vod_info`/`get_series_info` only as `404`) | G9 | todo |
| VOD | `vod_proxy` streaming path: session mint, path redirect, byte delivery, `Content-Length` and `Accept-Ranges` | G9 | todo |
| VOD | `vod_proxy` Range and seek: a mid-file Range yields 206 with the correct `Content-Range` against the full file size | G9 | todo |
| VOD | `vod_proxy` against a provider that will not serve 206 (`range-unsupported` fault) | G9 | todo |
| VOD | Root XC playback routes `/movie/<user>/<pass>/<id>.<ext>` and `/series/<user>/<pass>/<id>.<ext>` | G9 | todo |
| VOD | **Characterization:** `Client.authenticate()` checks only that `user_info` is present — never `auth` or `status` — so a provider answering `200` with `auth: 0` is treated as authenticated (`xc-auth-envelope` fault). G9 decides whether to file it | G9 | todo |
| VOD | **Known defect:** `_validate_range_header` (`apps/proxy/vod_proxy/multi_worker_connection_manager.py:585-600`) splits `bytes=<start>-<end>` on the first `-` and treats an empty `start_str` as `start_byte = 0` — so a suffix range `bytes=-500` (RFC 9110: "the last 500 bytes") is silently reinterpreted as the prefix range `bytes=0-500`. A client asking for the tail of a file is served the head instead, with a 206 and a `Content-Range` describing the wrong slice and no error anywhere. Found cross-checking this build's `parseRange`/G8 Task 5 against what the product actually parses; verified in source, not asserted here (D25 — this build hands findings to the goal that will assert them). Filed as [#64](https://github.com/D10Scot/Dispatcharr/issues/64). G9 should add a suffix-range test against the real `vod_proxy` path once this is fixed, or a `test.fail()` pinning the defect if it lands first | G9 | todo |
| VOD | **Known defect:** a provider's 416 is unreachable through `vod_proxy`. `response.raise_for_status()` (`:509`) raises on any upstream 4xx/5xx before the response is inspected, so an upstream 416 never reaches Dispatcharr's own client-facing response; separately, `:1303` sets `response.status_code = 206 if range_header else 200` unconditionally, regardless of what the provider actually answered. G8 Task 5's 416 branch (`serveFiniteAsset`, `e2e-upstream/src/vod-asset.ts`) is therefore only observable by a client that talks to the fake provider directly, never through the product — G9 should not write an assertion expecting a 416 to surface end to end until this is fixed | G9 | todo |
| VOD | **Gap:** `handleXc` (`e2e-upstream/src/xc/router.ts`) has no method gate anywhere inside it — the only one in the whole XC surface lives in `serveChannelStream`, reached solely via `/live/`. This is one defect showing up at two call sites, not two: `POST /movie/<user>/<pass>/<id>.<ext>` gets a 200 with the full body instead of a 405 (found in G8 Task 5), and `POST /player_api.php` gets a 200 auth envelope instead of a 405 (deferred from G8 Task 2), because both fall through `handleXc` with no method check before reaching their handlers — unlike `/live/`, which 405s a non-GET/HEAD method (`server.ts:375`). Fixing `/movie/`/`/series/` and `/player_api.php` separately means writing the same method check twice, in the wrong place; the actual fix is **one guard at the top of `handleXc`**, before any route match, since every non-`/live/` XC route shares this gap. Not fixed in G8 (unrequested scope for a wiring-only build); whoever in G9 picks this up should add the single guard at the seam rather than a per-route patch | G9 | todo |
| VOD | **Gap:** `not-found`/`auth-failure` have no effect on `/movie/<user>/<pass>/<id>.<ext>` or `/series/<user>/<pass>/<id>.<ext>` (G8 Task 7). Both routes call `serveVodAsset` directly and never reach `serveChannelStream` — the pipeline that gives `/live/` and both catch-up routes those two faults for free — so arming either against a VOD id is silently a no-op: `200 appliedTo: 0` from `/fault`, identical to a correct arm, and the asset still serves normally. This is the same shape as the method-gate row above, not a new one: both fixes land at the same `handleXc` seam that row already names, since neither VOD route is reached through `serveChannelStream` for the same reason neither has its method checked there. Not fixed in G8 (widening `/movie/`/`/series/` to use `serveChannelStream` was out of this task's scope); G9 should decide whether VOD-playback faults need `not-found`/`auth-failure` coverage and, if so, fix it once at the seam rather than per-route | G9 | todo |
| VOD | **Characterization, elaborating the `range-unsupported` row above:** empirically, arming `range-unsupported` and requesting a mid-file `Range` through `/proxy/vod/movie/<uuid>` (G8 Task 10) produced a normal `206` with a correct `Content-Range` and byte-correct sliced body — the fault did not surface at all through the product. Confirmed at the source: hitting the fake provider directly (control origin) with the fault armed and the same `Range` header did return the documented `200` with no `Accept-Ranges` and the full asset body, so the fault fires correctly at the provider; it is Dispatcharr's own handling that masks it. Two mechanisms combine: (1) `multi_worker_connection_manager.py:1303` sets `response.status_code = 206 if range_header else 200` **unconditionally** on the *client-facing* response, independent of what the upstream actually returned (this is the same line the task-10 brief's now-void troubleshooting note and the row two above it both cite); (2) since the ignoring provider still sends the complete asset from byte 0, Dispatcharr's own read of that response — whatever it does with the client's requested offset — reproduces the correct byte range anyway, so even the *body* comes out right, not just the status code. Net effect: a G9 test that arms `range-unsupported` and expects to observe *anything* different through `/proxy/vod/` (status, headers, or bytes) with a single whole-asset GET will not — the asset is small enough here that the entire file transits in one response either way. This does not by itself prove Dispatcharr always re-slices correctly (an asset too large to buffer whole, or a Range far past what a `range-unsupported` provider chooses to send, might behave differently) — G9 owns deciding whether that distinction is worth its own test | G9 | todo |
| Catch-up | XC live ingest fields catch-up depends on: `tv_archive`/`tv_archive_duration` → `Stream.is_catchup`/`catchup_days` → `Channel.is_catchup` via `rollup_channel_catchup_fields`, including its self-heal pass | G10 | todo |
| Catch-up | **Gap:** the provider stream id catch-up actually keys off is not observable through the REST API. `_prepare_catchup_stream_attempt` (`apps/timeshift/views.py:1641`) reads `(catchup_stream.custom_properties or {}).get("stream_id")` — and `apps/m3u/tasks.py:1179` does populate `custom_properties` with the whole raw XC catalogue dict for that stream, `stream_id` included. But `StreamSerializer` (`apps/channels/serializers.py:123-147`) never lists `custom_properties` among its `fields`, so no `GET` response can see it. The distinct top-level `Stream.stream_id` column (`apps/channels/models.py:112`, populated separately at `apps/m3u/tasks.py:1143`) is what the API *does* expose, and G8's `xc-ingest.spec.ts` asserts that one — it carries the same upstream value today, since both are parsed from the identical `stream["stream_id"]`, but it is a different field read by different code, and nothing enforces that they stay in sync. G10 cannot verify the id catch-up actually keys off by reading the stream back over the API; it needs another way in (e.g. `ScenarioLog`'s recorded catch-up request, or a DB-level check) if that id's correctness is part of what it means to prove | G10 | todo |
| Catch-up | Redirect mode: `/timeshift/...` and `/streaming/timeshift.php` each 302 in the layout the client used; `/proxy/catchup/<uuid>` defaults to PATH | G10 | todo |
| Catch-up | Proxy mode end to end: bytes reach the client and the provider recorded the credentials, stream id, converted start timestamp and padded duration | G10 | todo |
| Catch-up | The seven-candidate cascade: PATH shapes first, QUERY last, and the winning index cached per account (`_get_cached_format_index`) reorders the next attempt | G10 | todo |
| Catch-up | Decisive failures (401/403/406) stop the cascade for that account; a soft 404 or a 200 with no TS sync does not | G10 | todo |
| Catch-up | `server_info.timezone` from the account profile drives `convert_timestamp_to_provider_tz` | G10 | todo |
| Catch-up | **Gap:** the generated M3U emits no `catchup=`/`catchup-source=` attribute. `#EXTINF` carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally `tvc-guide-stationid`, and `group-title` — nothing else. Catch-up is advertised only through the XC `tv_archive`/`tv_archive_duration` fields, so an M3U-only client can never discover it. G10 decides whether that is a defect to file or intended | G10 | todo |
| Frontend | Guide grid renders and navigates | G6 | todo |
| Frontend | DVR: schedule, list, cancel a recording | G6 | todo |
| Frontend | Users: create, edit, delete | G6 | todo |
| Frontend | Settings: change and persist | G6 | todo |
| Frontend | Plugins: list, enable, configure | G6 | todo |
| Frontend | Stats page renders live data | G6 | todo |
| Frontend | Connect: webhook CRUD | G6 | todo |
| Frontend | Logos: upload and browse | G6 | todo |
| Frontend | Backups: create and restore | G6 | todo |
| Lifecycle | Upgrade from previous release (migrations) | G7 | done |
| Lifecycle | Restart preserves channels and settings | G7 | done |
| Lifecycle | PUID/PGID honoured | G7 | done |
| Lifecycle | TLS Postgres connection | G7 | done |

The ten G1 rows above are covered by these specs (the two seeding rows
share one file, as do the two principal rows):

- `e2e/tests/pristine/first-run-setup-and-login.spec.ts`
- `e2e/tests/seeded/authenticated-session.spec.ts`
- `e2e/tests/seeded/api-fixture.spec.ts`
- `e2e/tests/seeded/seed-fixture.spec.ts`
- `e2e/tests/seeded/authorization.spec.ts`
- `e2e/tests/seeded/async-wait.spec.ts`
- `e2e/tests/seeded/ws-fixture.spec.ts`
- `e2e/tests/streaming/stream-client.spec.ts`
- `e2e/tests/streaming/stalled-stream.spec.ts` (regression: read ordering
  across `collectFor` → `readPackets` on a stalled stream)

The four G2 rows above are covered by `e2e-upstream`'s own vitest suite (the
provider and its faults) plus:

- `e2e/tests/seeded/upstream-ingest.spec.ts` (ingest plumbing proof)
- `e2e/tests/streaming/single-client.spec.ts` (stream-through plumbing proof;
  supersedes the former `upstream-through-proxy.spec.ts`, deleted in G4 — the
  same path through Dispatcharr, plus contiguity, a polled status read and
  the provider cross-check; see the G4 block below)
- `e2e/tests/streaming/upstream-to-control.spec.ts` (`toControl` conversion)
- `e2e/tests/streaming/stream-client.spec.ts` and
  `e2e/tests/streaming/stalled-stream.spec.ts`, both re-pointed at the
  provider (`e2e/support/static-upstream.ts` is deleted)

**G3 and G4 are now unblocked.** Both can seed a scenario, ingest a playlist
or stream through the provider, and drive any of the eight faults, using only
`e2e/fixtures/upstream.ts` and the fault catalogue documented in
`e2e-upstream/README.md` — without reading `e2e-upstream/src/`.

The eleven `done` G4 rows above are covered by these specs (the two
`shared-upstream.spec.ts` rows share one file; the three-way Stream Profile
split is across two — Proxy in `single-client.spec.ts`, Redirect and FFmpeg
together in `stream-profiles.spec.ts`):

- `e2e/tests/streaming/single-client.spec.ts` — single client receives aligned
  TS, and Stream Profile: Proxy (the test drives the Proxy profile directly)
- `e2e/tests/streaming/shared-upstream.spec.ts` — N clients share one
  upstream, and client teardown releases the upstream (one test each)
- `e2e/tests/streaming/stream-profiles.spec.ts` — Stream Profile: Redirect,
  and Stream Profile: FFmpeg (one test each)
- `e2e/tests/streaming-failover/mid-stream-switch.spec.ts` — mid-stream switch
  does not disturb clients
- `e2e/tests/streaming-failover/failover-dead-air.spec.ts` — failover: dead
  air
- `e2e/tests/streaming-failover/failover-connect-failure.spec.ts` — failover:
  connect failure
- `e2e/tests/streaming-failover/failover-buffering.spec.ts` — failover:
  buffering (ffmpeg only)
- `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts` — Output
  Profile shared per (channel, profile), verified both by the shared owner
  key and by counting live ffmpeg processes directly

The twelfth G4 row, the ownership-lease fencing flagship, stays `todo`: it
was built, shown to pass for a reason that says nothing about the defect
(the true owner's own cleanup loop re-acquires the key faster than any
black-box client can act), and deleted rather than kept as a false green. See
the row itself for the full trace and `e2e/tests/streaming-greybox/` history
(commit `37edae89`) for the removed spec and allowlist entry.

The four G7 rows above are covered by:

- `e2e/tests/lifecycle/upgrade-migrations.spec.ts` (upgrade from previous
  release)
- `e2e/tests/lifecycle/restart-persistence.spec.ts` (restart preserves
  channels and settings)
- `docker/tests/test-puid-pgid.sh`, run by
  `.github/workflows/lifecycle-tests.yml` (PUID/PGID honoured)
- `docker/tests/test-tls-postgres.sh`, run by
  `.github/workflows/lifecycle-tests.yml` (TLS Postgres connection)

The PUID/PGID and TLS Postgres rows are wired but have not yet executed a
full run in CI: `lifecycle-tests.yml` is not on the default branch yet, so it
has not run and could not have. One scenario (`test-puid-pgid.sh`'s
`puid_test_fresh_def`) has been run by hand and passed, 13/13 assertions,
exit 0; `test-tls-postgres.sh` has not been run at all. If the first
post-merge run of `lifecycle-tests.yml` is red, these two rows come back to
`todo`.
