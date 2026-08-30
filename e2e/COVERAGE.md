# E2E Coverage Inventory

The shared worklist for all ten goals. **Update this in the same PR as the
tests.** Status: `todo` / `done` / `known-bug` (asserted correct, marked
`test.fail()`, issue filed) — for a Flow row, meaning the test itself.

A **Gap**/**Observation** row isn't a flow under test, so its Status tracks
the finding instead: `done` once the note is written and, where relevant,
confirmed against the code or a live run, with no further action expected
here; `todo` when the row is a live open question left for a later goal to
resolve (see the G8/G10 Gap rows).

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
| Sources | M3U account create → refresh → streams appear | G3 | done |
| Sources | EPG source create → refresh → programme data | G3 | done |
| Sources | Channel creation from streams | G3 | done |
| Sources | Auto channel sync | G3 | done |
| Sources | Channel groups and Channel Profiles | G3 | done |
| Sources | Logo upload and assignment | G3 | done |
| Sources | M3U refresh failure records the error and leaves no partial catalogue | G3 | done |
| Sources | `M3UAccount.locked` is writable over the API — `read_only_fields` is declared on the serializer class instead of `Meta` ([#15](https://github.com/D10Scot/Dispatcharr/issues/15)); asserted correct and `test.fail()`ed | G3 | known-bug |
| Sources | A failed M3U refresh discards the HTTP-status-specific message: `fetch_m3u_lines` writes "M3U file not found (404) at URL: …" and `_refresh_single_m3u_account_impl` overwrites it with a generic string, identically for 404, 401, 403, 500 and a connection refusal ([#60](https://github.com/D10Scot/Dispatcharr/issues/60)); asserted correct and `test.fail()`ed | G3 | known-bug |
| Sources | Deliberate G3 gaps: EPG fuzzy auto-matching (`match-epg`, `set-names-from-epg`, `set-logos-from-epg`, `set-tvg-ids-from-epg`, `fetch_schedules_direct()`) and the permanently-broken `get_preferred_region_code()` are out of scope, not missed; auto-sync **rename-in-place** is not expressible because `ScenarioRegistry` has no update operation and `Stream.stream_hash` derives from a URL carrying the scenario id, so the mutation test proves create-and-delete instead (see `auto-channel-sync.spec.ts`'s second test); **multi-group catalogues** are not expressible because `renderPlaylist` hardcodes `group-title="E2E"`; logo *image fetching* is out because the provider's `tvg-logo` points at RFC 2606-reserved `example.invalid`, though row-level logo ingest is covered; and [#7](https://github.com/D10Scot/Dispatcharr/issues/7) (the `IntervalSchedule` duplicate-create race) is **deliberately not reproduced** — provoking it poisons the shared container permanently for every remaining test in the run, with no API or UI able to repair it, so every G3 source uses the pre-warmed `refresh_interval: 0`. The first three would be closed by a provider `PATCH /scenarios/<id>` and a `group` field on `ChannelSpec` — `e2e-upstream`'s scope, a later goal | G3 | todo |
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
| Streaming | Ownership lease is fenced against a second concurrent owner — attempted by deleting `live:channel:{uuid}:owner` under a running Proxy-profile stream and polling for a second worker to claim it; confirmed empirically unprovable from outside the container: the same owning worker's own `ProxyServer._start_cleanup_thread` cleanup loop notices the missing key and calls `extend_ownership()`, re-`SET NX`-ing the identical worker id well under a second later every run (measured at ≤500ms), because that loop is the only code path with a local `StreamManager` for the channel; a follower worker never contends because `stream_ts` only lets a worker attempt ownership when channel metadata is absent too, which a bare owner-key delete does not cause — so no black-box HTTP/Redis manipulation can land a second `SET NX` in the sub-second gap. The untried lever is co-expiring `live:channel:{uuid}:metadata` with the owner key, which is what would open the metadata-gated follower path in `stream_ts`; that is a larger provocation than this row's brief allowed and needs its own scoping. | G4 | todo |
| Output | /output/m3u parses, every URL is well-formed, and one is streamed end to end; also pins that a channel name containing a double quote breaks the emitted `tvg-name`/`group-title` attributes ([#80](https://github.com/D10Scot/Dispatcharr/issues/80)), asserted correct and `test.fail()`ed in the same file | G5 | done |
| Output | /output/m3u/&lt;profile_name&gt; scopes to Channel Profile membership, and 404s on a profile name that does not exist | G5 | done |
| Output | /output/epg is valid XMLTV and carries programmes for the seeded channels | G5 | done |
| Output | HDHomeRun discovery, device XML, lineup and lineup status. [#83](https://github.com/D10Scot/Dispatcharr/issues/83) (`HDHRDevice` row vs `discover.json`) is filed but deliberately not pinned here: `HDHRDevice.objects.first()` is an unnamespaced singleton, and creating it — even transiently — would corrupt every concurrent test on the shared `seeded` instance, including this file's own exact-literal assertions; see `hdhr.spec.ts`'s comment for the full reasoning | G5 | done |
| Output | Xtream authentication handshake (user_info / server_info envelope) | G5 | done |
| Output | Xtream live actions: get_live_categories, get_live_streams, get_short_epg, get_simple_data_table | G5 | done |
| Output | Xtream VOD and series list actions (get_vod_categories, get_vod_streams, get_series_categories, get_series) answer 200 with a well-formed array — shape only, checked against however many rows the shared instance happens to hold at run time now that G8 seeds a real catalogue in the same project; catalogue *content* is G9's row — and the two detail actions (get_vod_info, get_series_info) 404 on an unknown id without erroring | G5 | done |
| Output | Xtream get.php and xmltv.php at the site root — playlist/guide shape and the 401 half of bad-credential rejection; the 403 (blocked-network) half is untested — proving it needs mutating the shared `XC_API` network ACL, which is out of scope and shared by four workers | G5 | done |
| Output | Authorization matrix by user_level — Xtream only, the one output surface with a principal. Landed at all three levels (0, 1, 10): `POST /api/accounts/users/` was proven, before the matrix was written, to accept `user_level: 10` through the normal create path | G5 | done |
| Output | hide_adult_content across the Xtream listing paths (get_live_streams, get.php, xmltv.php) — the filter itself is correct on every listing path; the same channel is nonetheless still streamable through stream_xc once unlisted (see the known-bug row below, [#87](https://github.com/D10Scot/Dispatcharr/issues/87)) | G5 | done |
| Output | /output/m3u, /output/epg and the HDHR lineup are unauthenticated by design, gated only by the M3U_EPG network ACL. The `/hdhr/lineup.json` half of this assertion is the positive-behaviour mirror of the HDHomeRun-authorization known-bug row below ([#82](https://github.com/D10Scot/Dispatcharr/issues/82)) — both describe today's behaviour correctly; the day #82 is fixed, that row's pin flips green as expected and this assertion flips red as an intended false alarm; see the reciprocal comments in both spec files | G5 | done |
| Output | `xc_get_live_categories` filters `user_level` exactly rather than `__lte` for a user with at least one Channel Profile, so a channel that user can list via get_live_streams can belong to no category at all ([#85](https://github.com/D10Scot/Dispatcharr/issues/85)); asserted correct and `test.fail()`ed | G5 | known-bug |
| Output | A channel hidden from a user by hide_adult_content is unlisted everywhere but still streamable through stream_xc, which applies user_level and Channel Profile membership but no adult filter ([#87](https://github.com/D10Scot/Dispatcharr/issues/87)); asserted correct and `test.fail()`ed | G5 | known-bug |
| Output | The HDHomeRun endpoints apply no authorization at all — all four views are AllowAny with no principal to filter by, so hide_adult_content and user_level are both unenforceable there by construction ([#82](https://github.com/D10Scot/Dispatcharr/issues/82)); asserted correct and `test.fail()`ed | G5 | known-bug |
| Output | player_api.php distinguishes an unknown username (404, via get_object_or_404) from a wrong password (401) on an unauthenticated, credentials-in-the-URL endpoint — an account-enumeration oracle ([#84](https://github.com/D10Scot/Dispatcharr/issues/84)); asserted correct and `test.fail()`ed | G5 | known-bug |
| Accounts | Token refresh with a deleted user's token 500s instead of 401 ([#12](https://github.com/D10Scot/Dispatcharr/issues/12)); asserted correct and `test.fail()`ed, at the cost of one login | G5 | known-bug |
| Upstream | Fake provider speaks Xtream Codes: `player_api.php` auth envelope and the eight catalogue actions `core/xtream_codes.Client` calls | G8 | done |
| Upstream | Fake provider serves a finite VOD asset with `Content-Length`, `Accept-Ranges`, 206 + `Content-Range` and 416 | G8 | done |
| Upstream | Fake provider answers both catch-up layouts and records the credentials, stream id, start timestamp and duration it was asked for | G8 | done |
| Upstream | Four new faults: `xc-auth-envelope`, `no-tv-archive`, `catchup-layout-404`, `range-unsupported` | G8 | done |
| Upstream | Plumbing proof: XC account ingest → declared live streams appear | G8 | done |
| Upstream | Plumbing proof: VOD catalogue ingest → `Movie`, `Series` and `Episode` rows appear | G8 | done |
| Upstream | Plumbing proof: one VOD byte read through `/proxy/vod/` | G8 | done |
| Upstream | Plumbing proof: a catch-up URL reaches the provider in each layout | G8 | done |
| Upstream | Plumbing proof: the candidate cascade falls back when one layout 404s | G8 | done |
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
| VOD | **Known defect, elaborating the `range-unsupported` row above:** arming `range-unsupported` and requesting a mid-file `Range` through `/proxy/vod/movie/<uuid>` (G8 Task 10) produces a `206` with a `Content-Range` naming exactly the range the *client* asked for and a matching `Content-Length` — but the **bytes are wrong**. Verified byte-for-byte, not just by length: with a 125,585-byte asset and `Range: bytes=100-199`, the 100-byte body received was byte-identical to the file's bytes **0-99**, not 100-199, while the response claimed `Content-Range: bytes 100-199/125585`. Mechanism, confirmed in source: `multi_worker_connection_manager.py:1303` sets `response.status_code = 206 if range_header else 200` and `:1315-1332` fabricates `Content-Range`/`Content-Length` **purely from the client's requested range and the previously-known full size** — neither checks what the upstream response's own status or `Content-Range` actually was. `stream_generator()` (`:1152`) is a pure passthrough of `upstream_response.iter_content()` with no offset-skipping or truncation to match the declared length. So when the upstream ignores `Range` and answers `200` with the whole asset from byte 0, the client is handed the head of the file under headers describing the requested slice — internally consistent, spec-shaped, and silently wrong. This is not a harness limitation; it's a real defect in the product's Range handling, reachable by any real provider that doesn't honor `Range` (RFC 9110 permits ignoring it and returning `200`). Filed as [#66](https://github.com/D10Scot/Dispatcharr/issues/66). G9 should add a byte-equality assertion (not just status/length) to whatever `range-unsupported` test it writes, and decide whether to pin this with `test.fail()` before the fix lands | G9 | todo |
| Catch-up | XC live ingest fields catch-up depends on: `tv_archive`/`tv_archive_duration` → `Stream.is_catchup`/`catchup_days` → `Channel.is_catchup` via `rollup_channel_catchup_fields`, including its self-heal pass | G10 | todo |
| Catch-up | **Gap:** the provider stream id catch-up actually keys off is not observable through the REST API. `_prepare_catchup_stream_attempt` (`apps/timeshift/views.py:1641`) reads `(catchup_stream.custom_properties or {}).get("stream_id")` — and `apps/m3u/tasks.py:1179` does populate `custom_properties` with the whole raw XC catalogue dict for that stream, `stream_id` included. But `StreamSerializer` (`apps/channels/serializers.py:123-147`) never lists `custom_properties` among its `fields`, so no `GET` response can see it. The distinct top-level `Stream.stream_id` column (`apps/channels/models.py:112`, populated separately at `apps/m3u/tasks.py:1143`) is what the API *does* expose, and G8's `xc-ingest.spec.ts` asserts that one — it carries the same upstream value today, since both are parsed from the identical `stream["stream_id"]`, but it is a different field read by different code, and nothing enforces that they stay in sync. G10 cannot verify the id catch-up actually keys off by reading the stream back over the API; it needs another way in (e.g. `ScenarioLog`'s recorded catch-up request, or a DB-level check) if that id's correctness is part of what it means to prove | G10 | todo |
| Catch-up | **Gap:** the recommended `POST /api/catchup/sessions/` branch of `_serve_catchup` is unexercised. Both G8 catch-up plumbing proofs (`catchup-path-layout.spec.ts`, `catchup-cascade.spec.ts`) drive `/proxy/catchup/<uuid>?start=&duration=` directly — the session-less, direct-auth shape that `catchup_proxy` (`apps/timeshift/views.py`) redirects to mint its own `session_id` on first play — and the root XC `/timeshift/...`/`/streaming/timeshift.php` route (`_timeshift_proxy_impl`) has no session concept at all. Neither reaches `catchup_proxy`'s `session_id` branch, which resolves a session minted by `CatchupSessionCreateAPIView` (`POST /api/catchup/sessions/`, `apps/timeshift/api_views.py`) via `resolve_catchup_playback` (`apps/timeshift/sessions.py`) — the path the endpoint's own OpenAPI description calls **recommended** for native apps. Both routes converge on the same `_serve_catchup` (`apps/timeshift/views.py:344`), so the fault/streaming behaviour it exercises is shared, but the mint-a-session-then-play flow itself has never been driven end to end. G10 should add a proof that calls `POST /api/catchup/sessions/` and plays back with the returned `session_id` | G10 | todo |
| Catch-up | Redirect mode: `/timeshift/...` and `/streaming/timeshift.php` each 302 in the layout the client used; `/proxy/catchup/<uuid>` defaults to PATH | G10 | todo |
| Catch-up | Proxy mode end to end: bytes reach the client and the provider recorded the credentials, stream id, converted start timestamp and padded duration | G10 | todo |
| Catch-up | The seven-candidate cascade: PATH shapes first, QUERY last, and the winning index cached per account (`_get_cached_format_index`) reorders the next attempt | G10 | todo |
| Catch-up | Decisive failures (401/403/406) stop the cascade for that account; a soft 404 or a 200 with no TS sync does not | G10 | todo |
| Catch-up | `server_info.timezone` from the account profile drives `convert_timestamp_to_provider_tz` | G10 | todo |
| Catch-up | **Gap:** the generated M3U emits no `catchup=`/`catchup-source=` attribute. `#EXTINF` carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally `tvc-guide-stationid`, and `group-title` — nothing else. Catch-up is advertised only through the XC `tv_archive`/`tv_archive_duration` fields, so an M3U-only client can never discover it. G10 decides whether that is a defect to file or intended | G10 | todo |
| Frontend | Guide grid renders and navigates | G6 | done |
| Frontend | DVR: schedule, list, cancel a recording | G6 | done |
| Frontend | **Gap:** scheduling a recording creates three objects — the `Recording` row, a django-celery-beat `PeriodicTask` named `dvr-recording-<id>`, and a `ClockedSchedule` — with no DB cascade between them; `PeriodicTask` is linked to `Recording` only by that name string, written into `Recording.task_id` by `schedule_task_on_save` (`apps/channels/signals.py:361-363`/`367-369`). The sole teardown mechanism is the `post_delete` receiver `revoke_task_on_delete` (`apps/channels/signals.py:388-390`) calling `revoke_task()` (`apps/channels/signals.py:289-310`), and it hinges on `task_id` having been populated. `RecordingViewSet.destroy` (`apps/channels/api_views.py:3776`) **does** override `destroy`, and reaches the signal through its `super().destroy()` call (`:3846`) — so the teardown fires for both the UI cancel and `dvr.spec.ts`'s cleanup DELETE, but by a longer route than a default `ModelViewSet`. That override also does three further things the test never observes: it deletes the recording's file(s) from disk, emits a `recording_cancelled` WebSocket event, and backgrounds the DVR-client teardown in a thread. The gap: the test can only assert the `Recording` row is gone, because neither `PeriodicTask` nor `ClockedSchedule` has a REST surface, and none of the three side effects above has one either. If the `task_id` write were ever lost, the `PeriodicTask` would orphan invisibly — no API any test polls would show it — and eventually fire against a deleted recording | G6 | done |
| Frontend | Users: create, edit, delete | G6 | done |
| Frontend | Settings: change and persist | G6 | done |
| Frontend | Plugins: list, enable, configure | G6 | done |
| Frontend | **Observation:** `plugins.spec.ts`'s comment on the plugin-visibility mechanism (`.reload_token` mtime, no restart needed) is a claim the assertions alone don't prove — a uWSGI respawn would satisfy them identically. Out-of-band check during a mutation run: `docker logs` showed no uWSGI respawn across the import, only `apps.plugins.loader` discovery lines | G6 | done |
| Frontend | Stats page renders live data | G6 | done |
| Frontend | Connect: webhook CRUD | G6 | done |
| Frontend | Logos: upload and browse | G6 | done |
| Frontend | **Gap:** `apps.channels.Logo.url` is a discriminator-free polymorphic field — a remote URL or, for a local upload, a raw server-side filesystem path (`/data/logos/<name>`) — and every consumer tells the two apart with its own copy-pasted `startsWith('http')`/`startsWith(('http://', 'https://'))` check: `apps/output/views.py:290` (`tvg-logo`), the XC `stream_icon` field, `LogosTable.jsx`'s URL column. All four agree today, so this is not filed as a defect — but it is the same shape as the eight-site channel-authorization filter in the root `CLAUDE.md`'s defect list, where the eighth copy was wrong. A fifth site that forgets the check would not fail cleanly either: a bare `url` handed to an HTTP client collides with the XC live-stream route (`<str:username>/<str:password>/<str:channel_id>`, three path segments matches `/data/logos/<file>` exactly) and 404s from an unrelated "no such user" lookup, which sends whoever debugs it looking in the wrong subsystem entirely. Confirmed empirically, not assumed, by G6 task 10 (`logos.spec.ts`) | G6 | done |
| Frontend | Backups: create and validate the archive | G6 | done |
| Frontend | **Gap:** development-mode-only diagnostics — not just React's key-prop warning, but anything gated behind `__DEV__`/`import.meta.env.DEV` (Mantine's own dev checks, React Router's, etc.) — are invisible to the `pageErrors` fixture in this harness. `docker/Dockerfile:22`'s `npm run build`, which is what `scripts/e2e_up.sh:138` builds the e2e image from, is a Vite production build: it resolves the production `react/jsx-runtime` with `NODE_ENV="production"`, so dev-only checks (React's `validateChildKeys` among them) are compiled out of the bundle entirely, not merely suppressed at runtime. Production error reporting is unaffected — `pageerror` and `console.error` from real app/library code still reach the collector, so this is not a hole in error detection generally, only in this one class of dev-time-only diagnostic. A later task that needs to assert a dev-only diagnostic must verify it against a development build directly, or assert the underlying behaviour rather than the diagnostic message. First hit: G6 task 9 (`connect.spec.ts`), trying to reproduce [#62](https://github.com/D10Scot/Dispatcharr/issues/62) | G6 | done |
| Lifecycle | Backups: restore — split out of G6's Backups row. Restoring on a shared instance replaces the database under every parallel worker mid-run and under every other project sharing the container locally, so it needs an instance of its own; G7 already stands one up per scenario | G7 | todo |
| Lifecycle | Upgrade from previous release (migrations) | G7 | done |
| Lifecycle | Restart preserves channels and settings | G7 | done |
| Lifecycle | PUID/PGID honoured | G7 | done |
| Lifecycle | TLS Postgres connection | G7 | done |
| Lifecycle | Refresh-interval scheduling: a **non-zero** `refresh_interval` on an `M3UAccount` or `EPGSource` — the enabled-`PeriodicTask` branch of `create_or_update_periodic_task` (`should_be_enabled = enabled and (use_cron or interval_hours > 0)`), the `IntervalSchedule` row it creates, `cron_expression`, and `_cleanup_orphaned_interval` on delete. **Uncovered as a direct cost of G3's D10**, which pins every source to `refresh_interval: 0`: a non-zero interval leaves an *enabled* hourly beat task re-refreshing that account for the life of the container, mutating rows under whatever test runs an hour later — which the shared `seeded` instance cannot tolerate. G7's scenario-specific jobs each stand up their own instance and can. Whoever takes it must also extend `bootstrap`'s pre-warm to the intervals it picks, from `bootstrap` and never from a worker ([#7](https://github.com/D10Scot/Dispatcharr/issues/7)) | G7 | todo |

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
or stream through the provider, and drive any of the twelve faults, using only
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

The `done` G3 rows above are covered by these specs (several rows share a
file; the two known-bug rows live beside the tests they qualify):

- `e2e/tests/seeded/m3u-ingest.spec.ts` — catalogue fidelity and group wiring,
  plus the `M3UAccount.locked` known bug (#15)
- `e2e/tests/seeded/m3u-refresh-failure.spec.ts` — `not-found` and
  `auth-failure`, plus the discarded-message known bug (#60)
- `e2e/tests/seeded/epg-ingest.spec.ts` — refresh → `EPGData` with zero
  `ProgramData`, a mapped-channel refresh whose baseline a later wait cannot
  resolve on instantly, then `set-epg` and `batch-set-epg`
- `e2e/tests/seeded/channel-from-stream.spec.ts` — `from-stream/` and the
  asynchronous `from-stream/bulk/`
- `e2e/tests/seeded/auto-channel-sync.spec.ts` — enable and create; a changed
  catalogue deletes and creates
- `e2e/tests/seeded/channel-profiles.spec.ts` — single and bulk membership
- `e2e/tests/seeded/logo-upload.spec.ts` — multipart upload and assignment

`e2e/tests/seeded/upstream-ingest.spec.ts` is untouched: it is G2's plumbing
proof and the G2 row still means what it meant.

The nine G6 flow rows above are covered by these specs (the Gap/Observation
annotation rows carry no spec of their own). The nine render
checks live in one file, generated from the surface table in
`e2e/tests/frontend/helpers.ts`; each surface's write or read proof is its own
file, and **that one-file-per-surface split is load-bearing** — the `frontend`
project runs two workers with file-level parallelism, which is what confines
backup creation and plugin installation to one worker each:

- `e2e/tests/frontend/render.spec.ts` — all nine surfaces mount, throw
  nothing, log no error and issue no request the server refuses
- `e2e/tests/frontend/guide.spec.ts` — Guide grid populated from the channel
  API, reached by clicking the sidebar
- `e2e/tests/frontend/dvr.spec.ts` — DVR schedule, list, cancel
- `e2e/tests/frontend/users.spec.ts` — Users create, edit, delete
- `e2e/tests/frontend/settings.spec.ts` — Settings change and persist, via a
  User-Agent row (a global `CoreSettings` change belongs to `pristine`)
- `e2e/tests/frontend/plugins.spec.ts` — Plugins import, enable, configure
- `e2e/tests/frontend/stats.spec.ts` — Stats renders a live connection
- `e2e/tests/frontend/connect.spec.ts` — Connect webhook CRUD
- `e2e/tests/frontend/logos.spec.ts` — Logos upload and browse
- `e2e/tests/frontend/backups.spec.ts` — Backups create and validate

Two further files in the same directory run but are not tied to a coverage
row above, the same way `streaming-greybox/quarantine.spec.ts` isn't tied to
a G4 row: `e2e/tests/frontend/pageerrors-enforcement.spec.ts` is a meta-test
that source-scans every `test()` under `tests/frontend/` for a destructured
`pageErrors` parameter, and the zip-builder unit test at the top of
`plugins.spec.ts` checks `buildPluginZip`'s output is a readable archive
before any test relies on it.

Gap: the Guide row proves the grid is populated from
`/api/channels/channels/`, not from real EPG programme data. Asserting a
programme in the grid needs an ingested XMLTV source, which is G3's path;
recording a programme from the Guide needs the same. Deferred rather than
attempted here.

The four `done` G7 rows above are covered by (the fifth, refresh-interval
scheduling, stays `todo` — see the row itself):

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

The nine `done` G8 rows above are covered across two layers: `e2e-upstream`'s own vitest suite
proves the provider's XC/VOD/catch-up behaviour in isolation, and `e2e/tests/{seeded,streaming}`
proves each surface's plumbing against the real product.

`e2e-upstream` vitest (provider correctness):

- `test/xc-envelope.test.ts`, `test/xc-catalogue.test.ts` and `test/xc-router.test.ts` — the
  `player_api.php` auth envelope and the catalogue actions
- `test/vod-asset.test.ts` and `test/xc-router.test.ts`'s VOD-playback describes — the finite VOD
  asset (`Content-Length`, `Accept-Ranges`, 206, 416)
- `test/xc-catchup.test.ts` and `test/xc-router.test.ts`'s catch-up describe — both catch-up
  layouts and all four timestamp shapes
- `test/xc-faults.test.ts` — the four new faults (`xc-auth-envelope`, `no-tv-archive`,
  `catchup-layout-404`, `range-unsupported`)

Plumbing proofs against the real product:

- `e2e/tests/seeded/xc-ingest.spec.ts` — XC account ingest → declared live streams appear
- `e2e/tests/seeded/vod-catalogue-ingest.spec.ts` — VOD catalogue ingest → `Movie`/`Series`/
  `Episode` rows appear
- `e2e/tests/streaming/vod-byte-read.spec.ts` — one VOD byte read through `/proxy/vod/`
- `e2e/tests/streaming/catchup-path-layout.spec.ts` — a catch-up URL reaches the provider in each
  layout
- `e2e/tests/streaming/catchup-cascade.spec.ts` — the candidate cascade falls back when one layout
  404s

**G9 and G10 are now unblocked the same way G3/G4 were for G2**: both can declare an XC scenario,
seed a VOD catalogue or an `M3UAccount`, and drive any of the twelve faults using only
`e2e-upstream/README.md` and `e2e/fixtures/upstream.ts`/`seed.ts` — without reading
`e2e-upstream/src/`. The time-addressability gap and the Upstream/VOD/Catch-up gap-and-defect rows
this build filed while implementing it stay `todo`, each naming the goal that owns picking it up.

The eleven G5 rows above are covered by these specs (several rows share a file, and the four
known-bug rows live beside the tests they qualify, following the same convention G3's
`m3u-ingest.spec.ts` and `m3u-refresh-failure.spec.ts` set):

- `e2e/tests/seeded/output-m3u.spec.ts` — `/output/m3u` parses and streams end to end and
  `/output/m3u/<profile>` scopes to Channel Profile membership, plus the standalone `#80`
  quote-escaping pin
- `e2e/tests/seeded/output-epg.spec.ts` — `/output/epg` is valid XMLTV with programmes
- `e2e/tests/seeded/hdhr.spec.ts` — HDHomeRun discovery, device XML, lineup and lineup status,
  plus the HDHR-has-no-authorization known bug (`#82`)
- `e2e/tests/seeded/xc-auth.spec.ts` — the `player_api.php` authentication handshake, plus the
  unknown-user-vs-wrong-password enumeration known bug (`#84`)
- `e2e/tests/seeded/xc-live.spec.ts` — `get_live_categories`, `get_live_streams`,
  `get_short_epg` and `get_simple_data_table`, plus the profiled-user category known bug (`#85`)
- `e2e/tests/seeded/xc-vod-catalogue-shape.spec.ts` — the four XC VOD/series list actions
  (shape, not content) and the two detail actions' 404s
- `e2e/tests/seeded/xc-output.spec.ts` — `get.php` and `xmltv.php` at the site root
- `e2e/tests/seeded/output-authorization.spec.ts` — the user_level authorization matrix,
  `hide_adult_content` across the Xtream listing paths, and the anonymous/unauthenticated output
  surfaces
- `e2e/tests/streaming/output-m3u-stream.spec.ts` — one URL taken verbatim from `/output/m3u`
  delivers bytes end to end
- `e2e/tests/streaming/hidden-channel-streamable.spec.ts` — the `stream_xc`
  `hide_adult_content` known bug (`#87`)
- `e2e/tests/seeded/token-refresh-deleted-user.spec.ts` — the pre-existing `#12` known bug
  (refreshing a deleted user's token 500s instead of 401)
