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
| Output | HDHomeRun discovery, device XML, lineup and lineup status. [#83](https://github.com/D10Scot/Dispatcharr/issues/83) (`device.xml` never reflects a configured `HDHRDevice` row, unlike `discover.json`) is filed but deliberately not pinned here: `HDHRDevice.objects.first()` is an unnamespaced singleton, and creating it — even transiently — would corrupt every concurrent test on the shared `seeded` instance, including this file's own exact-literal assertions; see `hdhr.spec.ts`'s comment for the full reasoning | G5 | done |
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
| Output | A channel name containing a double quote breaks the emitted `tvg-name`/`group-title` attributes in `/output/m3u`'s `#EXTINF` line — `apps/output/views.py:304-306` interpolates the raw name unescaped ([#80](https://github.com/D10Scot/Dispatcharr/issues/80)); asserted correct and `test.fail()`ed | G5 | known-bug |
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
| Upstream | **Gap:** the fake archive is not time-addressable — it serves the same looping TS whatever `start` it is asked for. Nothing proves Dispatcharr seeks to the right moment, only that it asks for the right one. Owned by G10, which must say so in every row it writes. G10 states the limit in `e2e/README.md`'s new Catch-up section, in each of the five spec files that assert on a timestamp, and beside the assertions themselves — and closing the gap for real means generating a distinct asset per requested instant, which is a build of its own and a new goal, not a G10 task | G8 | done |
| Upstream | The catch-up timestamp parser (`parseCatchupTimestamp`, `e2e-upstream/src/xc/catchup.ts`) now accepts exactly the four shapes `build_timeshift_candidate_urls` emits and rejects the eight hybrids with a 400 naming the offending value — G8's own PR replaced the single permissive regex this row used to describe with one regex per shape, tried in order (`CATCHUP_TIMESTAMP_SHAPES`), with an exhaustive test asserting all twelve separator/seconds combinations resolve to exactly the four accepted shapes. This is what makes `streaming/catchup-cascade.spec.ts`'s seven-candidate assertion a real proof rather than a tautology. Calendar validation is still absent (`2026-13-45:99-99` parses), which remains harmless because over-acceptance can only widen what is served | G8 | done |
| Upstream | **Known defect:** `collect_xc_streams` (`apps/m3u/tasks.py:933-936`) builds the live stream URL with raw, unencoded account credentials, unlike `build_timeshift_url_format_b` (`apps/timeshift/helpers.py:424-433`), which percent-encodes both fields with `quote(str(x), safe='')`. A credential containing `/` (or any other character `quote` would escape) therefore breaks live playback while the identical credential works for catch-up. Filed as [#61](https://github.com/D10Scot/Dispatcharr/issues/61) per spec D25 (the tracker entry costs nothing and the defect is real and verified), but per this goal's own Global Constraints — a build hands findings to the goal that will actually assert them — no `test.fail()` exists in `e2e-upstream` for it: this provider's seed helpers only generate sanitised credentials, and a hand-built unsanitised-credential request against `/live/` is a malformed URL by construction (too many path segments), so a test asserting either outcome would be vacuous. Verified reachable and demonstrated with a passing control test in `e2e-upstream/test/xc-router.test.ts` (`XC live playback — credential encoding`): the same slash-bearing credential succeeds when percent-encoded into the path, as `build_timeshift_url_format_b` does. Owned by whichever of G9/G10 first ingests a real XC account with an unsanitised (slash- or percent-bearing) credential — that task should add the seed support and the `test.fail()` this build could not | G8 | todo |
| Upstream | **Known defect (this provider, not the product):** `parseScenarioRequest`'s `xc` door check (`e2e-upstream/src/scenario.ts:591`) guards with `request.password === undefined`, not a falsy check, so `{ xc: true, username: 'u', password: '' }` passes the door despite the very next line's own comment stating "an empty password can never match the `/live/` path form" — the check the comment describes is not the check the code performs. A scenario created this way is accepted, echoed back with `password: ''`, and is then unservable the moment a real client streams from it, with no error at creation time to explain why. Found while implementing `seed.xcAccount`, which is deliberately **stricter than this door**: it throws on a falsy `scenario.password` (empty string included), not just `undefined`, specifically because this gap means the provider's own validation cannot be relied on to catch it. Not fixed here — `e2e-upstream/` is in scope for G8's own tasks, not for a fixture-consumer fix round. G9/G10 should not construct an XC scenario with an empty-string password expecting the door to reject it | G8 | todo |
| VOD | Catalogue ingest: categories, movies and series land as `VODCategory`, `Movie`, `Series` and their `M3U*Relation` rows | G9 | done |
| VOD | Category gating: `M3UVODCategoryRelation.enabled`, `auto_enable_new_groups_vod`/`_series`, and the `Uncategorized` fallback | G9 | done |
| VOD | Episode ingest on demand via `GET /api/vod/series/<pk>/provider-info/`, for both the object-keyed and array-keyed `episodes` shapes | G9 | done |
| VOD | Advanced movie data: `get_vod_info` merges into `Movie` and `M3UMovieRelation.custom_properties` without clobbering list-sync fields | G9 | done |
| VOD | XC VOD and series actions against a real catalogue (G5 covers only the empty-catalogue shape, and `get_vod_info`/`get_series_info` only as `404`) | G9 | done |
| VOD | `vod_proxy` streaming path: session mint, path redirect, byte delivery, `Content-Length` and `Accept-Ranges` | G9 | done |
| VOD | `vod_proxy` Range and seek: a mid-file Range yields 206 with the correct `Content-Range` against the full file size | G9 | done |
| VOD | `vod_proxy` against a provider that will not serve 206 (`range-unsupported` fault) ([#66](https://github.com/D10Scot/Dispatcharr/issues/66)); pinned by `vod-range.spec.ts`'s `test.fail()`, which asserts **bytes**, not status or length | G9 | known-bug |
| VOD | Root XC playback routes `/movie/<user>/<pass>/<id>.<ext>` and `/series/<user>/<pass>/<id>.<ext>` | G9 | done |
| VOD | **Characterization:** `Client.authenticate()` checks only that `user_info` is present — never `auth` or `status` — so a provider answering `200` with `auth: 0` is treated as authenticated (`xc-auth-envelope` fault). This is a provider-compatibility property of XC **account authentication**, not of VOD; the honest home for it is whichever goal owns that — G3's and G8's territory. G9 does not file it: an issue for a behaviour no test pins is one nobody can verify closed | G9 | todo |
| VOD | **Known defect:** `_validate_range_header` (`apps/proxy/vod_proxy/multi_worker_connection_manager.py:585-600`) splits `bytes=<start>-<end>` on the first `-` and treats an empty `start_str` as `start_byte = 0` — so a suffix range `bytes=-500` (RFC 9110: "the last 500 bytes") is silently reinterpreted as the prefix range `bytes=0-500`. A client asking for the tail of a file is served the head instead, with a 206 and a `Content-Range` describing the wrong slice and no error anywhere. Filed as [#64](https://github.com/D10Scot/Dispatcharr/issues/64). Pinned by `vod-range.spec.ts`'s `test.fail()` ('a suffix Range returns the tail of the file') | G9 | known-bug |
| VOD | **Known defect:** a provider's 416 is unreachable through `vod_proxy`. `response.raise_for_status()` (`:509`) raises on any upstream 4xx/5xx before the response is inspected, so an upstream 416 never reaches Dispatcharr's own client-facing response; separately, `:1303` sets `response.status_code = 206 if range_header else 200` unconditionally, regardless of what the provider actually answered. Concretely: on a session's *first* request, `content_length` is still unknown, so an unsatisfiable Range is passed to the provider verbatim and its 416 becomes an unhandled 500. Filed as [#98](https://github.com/D10Scot/Dispatcharr/issues/98). Pinned by `vod-range.spec.ts`'s `test.fail()` ('an unsatisfiable Range on a fresh session is 416, not 500'); the passing control proving an *established* session answers 416 correctly (`:1114`) sits in the same file, as a non-inverted assertion | G9 | known-bug |
| VOD | **Gap:** `handleXc` (`e2e-upstream/src/xc/router.ts`) has no method gate anywhere inside it — the only one in the whole XC surface lives in `serveChannelStream`, reached solely via `/live/`. This is one defect showing up at two call sites, not two: `POST /movie/<user>/<pass>/<id>.<ext>` gets a 200 with the full body instead of a 405 (found in G8 Task 5), and `POST /player_api.php` gets a 200 auth envelope instead of a 405 (deferred from G8 Task 2), because both fall through `handleXc` with no method check before reaching their handlers — unlike `/live/`, which 405s a non-GET/HEAD method (`server.ts:375`). Fixing `/movie/`/`/series/` and `/player_api.php` separately means writing the same method check twice, in the wrong place; the actual fix is **one guard at the top of `handleXc`**, before any route match, since every non-`/live/` XC route shares this gap. G9 declines to fix it: the fix is one guard at the seam the row below's fix already touched, but no G9 test exercises a non-GET VOD request, and a behaviour change nothing asserts is one nobody can verify closed | G9 | todo |
| VOD | **Gap:** `not-found`/`auth-failure` have no effect on `/movie/<user>/<pass>/<id>.<ext>` or `/series/<user>/<pass>/<id>.<ext>` (G8 Task 7). Both routes call `serveVodAsset` directly and never reach `serveChannelStream` — the pipeline that gives `/live/` and both catch-up routes those two faults for free — so arming either against a VOD id is silently a no-op: `200 appliedTo: 0` from `/fault`, identical to a correct arm, and the asset still serves normally. This is the same shape as the method-gate row above, not a new one: both fixes land at the same `handleXc` seam that row already names, since neither VOD route is reached through `serveChannelStream` for the same reason neither has its method checked there. **Fixed by G9 Task 2** (`e2e-upstream` commit `dbbd8666`): both faults are now checked directly in `handleXc`'s `vodMatch` branch. Scenario-wide only — a `{ channel: n }` arm still does not reach a VOD route, because a VOD id is not a channel id | G9 | done |
| VOD | **Known defect, elaborating the `range-unsupported` row above:** arming `range-unsupported` and requesting a mid-file `Range` through `/proxy/vod/movie/<uuid>` (G8 Task 10) produces a `206` with a `Content-Range` naming exactly the range the *client* asked for and a matching `Content-Length` — but the **bytes are wrong**. Verified byte-for-byte, not just by length: with a 125,585-byte asset and `Range: bytes=100-199`, the 100-byte body received was byte-identical to the file's bytes **0-99**, not 100-199, while the response claimed `Content-Range: bytes 100-199/125585`. Mechanism, confirmed in source: `multi_worker_connection_manager.py:1303` sets `response.status_code = 206 if range_header else 200` and `:1315-1332` fabricates `Content-Range`/`Content-Length` **purely from the client's requested range and the previously-known full size** — neither checks what the upstream response's own status or `Content-Range` actually was. `stream_generator()` (`:1152`) is a pure passthrough of `upstream_response.iter_content()` with no offset-skipping or truncation to match the declared length. So when the upstream ignores `Range` and answers `200` with the whole asset from byte 0, the client is handed the head of the file under headers describing the requested slice — internally consistent, spec-shaped, and silently wrong. Filed as [#66](https://github.com/D10Scot/Dispatcharr/issues/66). The byte-equality assertion asked for above now exists, as `vod-range.spec.ts`'s `test.fail()` ('a provider that ignores Range still yields the requested bytes'). No second issue — #66 already covers it | G9 | known-bug |
| VOD | **Known defect:** `VODCategoryFilter.m3u_account` (`apps/vod/api_views.py:624`) declares `NumberFilter(field_name="m3u_account__id")`, but `VODCategory` has no `m3u_account` relation — the reverse accessor is `m3u_relations` — so `GET /api/vod/categories/?m3u_account=<id>` raises `FieldError` at query time rather than filtering. `MovieFilter` and `SeriesFilter` get this right (`m3u_relations__m3u_account__id`); only `VODCategoryFilter` does not. Filed as [#96](https://github.com/D10Scot/Dispatcharr/issues/96). Pinned by `vod-ingest-fidelity.spec.ts`'s `test.fail()` | G9 | known-bug |
| VOD | **Known defect:** `xc_get_vod_info` (`apps/output/views.py:1675`) gates the whole `detailed_info` merge on `if movie.custom_properties:` and then reads the data off the *relation*'s `custom_properties` instead — the wrong object's truthiness. A movie whose provider payload carries none of trailer/director/actors/backdrop has `Movie.custom_properties = None` (`clean_custom_properties({})` returns `None`), so bitrate, video, audio, `cover_big` and the plot override never reach an XC client even though `refresh_movie_advanced_data` fetched and stored them on the relation; `/api/vod/movies/<pk>/provider-info/` reads the same relation and returns them correctly. Filed as [#97](https://github.com/D10Scot/Dispatcharr/issues/97). Pinned by `xc-vod-catalogue.spec.ts`'s `test.fail()` | G9 | known-bug |
| VOD | **Known defect:** `stream_xc_movie`/`stream_xc_episode` (`apps/proxy/vod_proxy/views.py`) return a bare `Response(...)` on wrong credentials, missing `xc_password`, and network-ACL denial — six call sites across both functions — but this file never imports `rest_framework.response.Response`, only `JsonResponse`/`HttpResponse`/`HttpResponseRedirect`/`Http404` from `django.http`. Every one of those branches raises `NameError: name 'Response' is not defined` instead of returning, so the client gets an unhandled 500 rather than the intended 401/403. **This is a wrong-status defect, not an authentication bypass** — the request never reaches the streaming code, so access is still refused; it just fails with the wrong status. Filed as [#100](https://github.com/D10Scot/Dispatcharr/issues/100). Pinned by `xc-vod-playback.spec.ts`'s `test.fail()` | G9 | known-bug |
| VOD | **Known defect:** `stream_xc_episode` (`apps/proxy/vod_proxy/views.py:1449-1454`) wraps its `M3UEpisodeRelation` lookup in `try`/`except M3UEpisodeRelation.DoesNotExist`, but the lookup uses `.filter(...).first()`, which returns `None` and never raises `DoesNotExist` — the guard is dead. The next line dereferences `episode_relation.episode`, raising `AttributeError`, so an unknown episode id is a 500 rather than a 404. `stream_xc_movie`, four functions above, does the same lookup correctly with `if not movie_relation`. Filed as [#99](https://github.com/D10Scot/Dispatcharr/issues/99). Pinned by `xc-vod-playback.spec.ts`'s `test.fail()` | G9 | known-bug |
| VOD | **Known defect:** `stream_xc_movie`/`stream_xc_episode`/`stream_vod` (`apps/proxy/vod_proxy/views.py`) apply no `is_adult` filter at all, unlike `xc_get_vod_streams`/`xc_get_vod_info` (`apps/output/views.py`), which filter `movie__is_adult=False` for a `hide_adult_content` user — so a movie that user cannot list is still streamable by asking for it by primary key. The VOD analogue of G5's live `stream_xc` defect ([#87](https://github.com/D10Scot/Dispatcharr/issues/87)), on different functions with a different fix; closing one does not close the other. Filed as [#110](https://github.com/D10Scot/Dispatcharr/issues/110). Pinned by `vod-adult-streamable.spec.ts`'s `test.fail()` | G9 | known-bug |
| VOD | **Known defect, deliberately unfiled:** an upstream failure during a VOD stream returns the provider account credential to an unauthenticated caller. Pinned by `vod-upstream-error.spec.ts`; **no public issue exists**, pending a disclosure decision by the repo owner. Do not open one from this row | G9 | known-bug |
| VOD | **Gap:** `stream_icon` → `VODLogo` ingest is unreachable from any G9 scenario. `MovieSpec` declares no image URL and `movieEntry` emits `stream_icon: ''`, so no `VODLogo` is ever created and `Movie.logo` is always `null` in these tests. Closing it is one optional `MovieSpec` field | G9 | todo |
| VOD | **Gap:** multi-provider VOD selection and priority ordering (`_order_candidates`, `_xc_fetch_priority_distinct_relations`) is unproven. Proving it needs two accounts deliberately sharing one `Movie` row — the exact aliasing hazard this goal's spec forbids everywhere else, and a failure indistinguishable from a cross-worker collision | G9 | todo |
| VOD | **Gap:** pre-stream failover between VOD providers is unproven. `_select_vod_stream` never connects — it rejects a candidate only for a missing URL, a profile at capacity, or a non-`http(s)` URL — so there is nothing to fail over *from* except a capacity rejection. Needs the two-account setup of the row above | G9 | todo |
| VOD | **Gap:** seek semantics are unproven beyond byte delivery. G9 proves the requested byte range comes back correctly; it does not prove a player can decode a container from that offset — a container question, not a proxy question | G9 | todo |
| VOD | `head_vod` (`apps/proxy/vod_proxy/urls.py`) is not routed — dead code stays dead | G9 | done |
| VOD | `vod_stats` and `stop_vod_client` are admin-only observability and unexercised: `stop_vod_client`'s stop signal is checked every 100 chunks and needs a long stream to observe | G9 | todo |
| VOD | VOD image and logo proxying, and `/api/vod/all/`, are out of scope per spec D15 | G9 | done |
| VOD | **Gap:** `batch_refresh_series_episodes` is reachable only through a Celery task with no endpoint, and its 24-hour cutoff makes it unobservable inside a test run | G9 | todo |
| VOD | The four `vod_proxy` Lua scripts and `active_streams` concurrency are not touched, not asserted, and not "fixed" under a failing test — they bypass the session metadata lock deliberately, as a real bug fix pinned by `apps/proxy/vod_proxy/tests/test_vod_lock_contention.py` | G9 | done |
| VOD | **Known defect:** `collect_xc_streams` builds live stream URLs with raw, unencoded account credentials ([#61](https://github.com/D10Scot/Dispatcharr/issues/61), owned by whichever of G9/G10 first ingests an XC account with an unsanitised credential — see the Upstream row above). **G9 declines it.** It is a *live* stream-URL construction defect in `apps/m3u/tasks.py`, which G3 owns, and it is unassertable through any VOD route regardless — the provider's `/movie/` route matches `[^/]+` per credential segment, so a slash-bearing credential is a malformed URL by construction | G9 | todo |
| Catch-up | XC live ingest fields catch-up depends on: `tv_archive`/`tv_archive_duration` → `Stream.is_catchup`/`catchup_days` → `Channel.is_catchup` via `rollup_channel_catchup_fields`, including clearing the flag when the provider stops advertising it | G10 | done |
| Catch-up | **Gap:** the provider stream id catch-up actually keys off is not observable through the REST API. `_prepare_catchup_stream_attempt` (`apps/timeshift/views.py:1641`) reads `(catchup_stream.custom_properties or {}).get("stream_id")` — and `apps/m3u/tasks.py:1179` does populate `custom_properties` with the whole raw XC catalogue dict for that stream, `stream_id` included. But `StreamSerializer` (`apps/channels/serializers.py:123-147`) never lists `custom_properties` among its `fields`, so no `GET` response can see it. The distinct top-level `Stream.stream_id` column (`apps/channels/models.py:112`, populated separately at `apps/m3u/tasks.py:1143`) is what the API *does* expose, and G8's `xc-ingest.spec.ts` asserts that one — it carries the same upstream value today, since both are parsed from the identical `stream["stream_id"]`, but it is a different field read by different code, and nothing enforces that they stay in sync. G10 cannot verify the id catch-up actually keys off by reading the stream back over the API; it needs another way in (e.g. `ScenarioLog`'s recorded catch-up request, or a DB-level check) if that id's correctness is part of what it means to prove. It is now observable the other way in: `catchupRequests` reads it off the provider's recorded request path, which is what this row itself suggested — see `e2e/tests/streaming/catchup-proxy-mode.spec.ts` | G10 | done |
| Catch-up | **Gap:** the recommended `POST /api/catchup/sessions/` branch of `_serve_catchup` is unexercised. Both G8 catch-up plumbing proofs (`catchup-path-layout.spec.ts`, `catchup-cascade.spec.ts`) drive `/proxy/catchup/<uuid>?start=&duration=` directly — the session-less, direct-auth shape that `catchup_proxy` (`apps/timeshift/views.py`) redirects to mint its own `session_id` on first play — and the root XC `/timeshift/...`/`/streaming/timeshift.php` route (`_timeshift_proxy_impl`) has no session concept at all. Neither reaches `catchup_proxy`'s `session_id` branch, which resolves a session minted by `CatchupSessionCreateAPIView` (`POST /api/catchup/sessions/`, `apps/timeshift/api_views.py`) via `resolve_catchup_playback` (`apps/timeshift/sessions.py`) — the path the endpoint's own OpenAPI description calls **recommended** for native apps. Both routes converge on the same `_serve_catchup` (`apps/timeshift/views.py:344`), so the fault/streaming behaviour it exercises is shared, but the mint-a-session-then-play flow itself has never been driven end to end. G10 should add a proof that calls `POST /api/catchup/sessions/` and plays back with the returned `session_id`. Both halves landed — the mint contract in `seeded/catchup-session-api.spec.ts`, the headerless playback in `streaming/catchup-proxy-mode.spec.ts` | G10 | done |
| Catch-up | Redirect mode: `/timeshift/...` and `/streaming/timeshift.php` each 302 in the layout the client used; `/proxy/catchup/<uuid>` defaults to PATH | G10 | done |
| Catch-up | Proxy mode end to end: bytes reach the client and the provider recorded the credentials, stream id, converted start timestamp and padded duration | G10 | done |
| Catch-up | The seven-candidate cascade: PATH shapes first, QUERY last, and the winning index cached per account (`_get_cached_format_index`) reorders the next attempt | G10 | done |
| Catch-up | Decisive failures (401/403/406) stop the cascade for that account; a soft 404 or a 200 with no TS sync does not | G10 | done |
| Catch-up | `server_info.timezone` from the account profile drives `convert_timestamp_to_provider_tz` | G10 | done |
| Catch-up | **Gap:** the generated M3U emits no `catchup=`/`catchup-source=` attribute. `#EXTINF` carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally `tvc-guide-stationid`, and `group-title` — nothing else. Catch-up is advertised only through the XC `tv_archive`/`tv_archive_duration` fields, so an M3U-only client can never discover it. It is a defect, filed as [#94](https://github.com/D10Scot/Dispatcharr/issues/94), pinned convention-agnostically by `seeded/catchup-m3u-advertisement.spec.ts`: the test asserts only that *some* `catchup` attribute is present alongside a matching `catchup-days`, because which of three incompatible M3U conventions to adopt is an unmade product decision | G10 | known-bug |
| Catch-up | Each catch-up precondition fails closed — non-catch-up channel, unparseable start, absent start, deactivated account — and none reaches the provider | G10 | done |
| Catch-up | **Known defect:** hide_adult_content is applied at 14 sites across apps/output/, apps/epg/, apps/channels/ and apps/vod/ and at none under apps/timeshift/, so an adult channel a user cannot list is still streamable through every catch-up entry point ([#95](https://github.com/D10Scot/Dispatcharr/issues/95)) | G10 | known-bug |
| Catch-up | **Known defect:** a non-UTC provider server_info.timezone truncates the requested start to the minute — convert_timestamp_to_provider_tz reformats through strftime("%Y-%m-%d:%H-%M") (apps/timeshift/helpers.py:160) before the colon-seconds candidate is derived, while "UTC" preserves the seconds ([#111](https://github.com/D10Scot/Dispatcharr/issues/111)) | G10 | known-bug |
| Frontend | Guide grid renders and navigates | G6 | done |
| Frontend | DVR: schedule, list, cancel a recording | G6 | done |
| Frontend | **Gap:** scheduling a recording creates three objects — the `Recording` row, a django-celery-beat `PeriodicTask` named `dvr-recording-<id>`, and a `ClockedSchedule` — with no DB cascade between them; `PeriodicTask` is linked to `Recording` only by that name string, written into `Recording.task_id` by `schedule_task_on_save` (`apps/channels/signals.py:361-363`/`367-369`). The sole teardown mechanism is the `post_delete` receiver `revoke_task_on_delete` (`apps/channels/signals.py:388-390`) calling `revoke_task()` (`apps/channels/signals.py:289-310`), and it hinges on `task_id` having been populated. `RecordingViewSet.destroy` (`apps/channels/api_views.py:3776`) **does** override `destroy`, and reaches the signal through its `super().destroy()` call (`:3846`) — so the teardown fires for both the UI cancel and `dvr.spec.ts`'s cleanup DELETE, but by a longer route than a default `ModelViewSet`. That override also does three further things the test never observes: it deletes the recording's file(s) from disk, emits a `recording_cancelled` WebSocket event, and backgrounds the DVR-client teardown in a thread. The gap: the test can only assert the `Recording` row is gone, because neither `PeriodicTask` nor `ClockedSchedule` has a REST surface, and none of the three side effects above has one either. If the `task_id` write were ever lost, the `PeriodicTask` would orphan invisibly — no API any test polls would show it — and eventually fire against a deleted recording. **G13 closed two of the three unobserved side effects, from the caller's side**: `recording_cancelled` now fires with the correct `was_in_progress` on both the upcoming and in-flight branches, and the upstream releases (`live` drops to 0) — see the DVR/G13 rows below. **Still unobserved**: the on-disk file/HLS-directory removal (`RecordingViewSet.destroy` deletes the `Recording` row synchronously, `api_views.py:3846`, before the background thread that removes files even starts, `:3941`, and `file()`/`hls()` both open with `get_object_or_404`, `:3385`/`:3469` — so the post-cancel `GET /file/` 404 proves the row is gone, not that anything left disk) and the `PeriodicTask`/`ClockedSchedule` deletion, neither of which has a REST surface | G6 | done |
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
| Lifecycle | Backups: restore — `backup-restore.spec.ts` on the `lifecycle-restore` project, which owns and resets its own container because `restore_backup` runs `DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;` (`_clean_postgresql_schema`) before `pg_restore --no-owner`. Takes a backup of state A, moves to state B in both directions (a channel created after the backup, a Recording deleted from before it), restores, and asserts both halves — neither is redundant: a restore that never ran passes "A is back", and one that dropped without loading passes "B is gone". Assertions poll, because `pg_restore` lands under a live connection pool. **Deliberately not asserted there: the logo bytes.** A version-2 archive holds `database.dump` and `metadata.json` and **no files** (`create_backup`), so the row returns with the dump while the bytes were never in the archive and were never removed — the assertion would pass for the wrong reason. `assertDurableState`'s `logoBytes` option exists for exactly this; the `create_backup` docstring's "and data directories" is stale | G12 | done |
| Lifecycle | Upgrade from previous release (migrations) | G7 | done |
| Lifecycle | Restart preserves channels and settings | G7 | done |
| Lifecycle | PUID/PGID honoured | G7 | done |
| Lifecycle | TLS Postgres connection | G7 | done |
| Lifecycle | Refresh-interval scheduling: `refresh-scheduling.spec.ts` on the `lifecycle-scheduling` project, which owns its container because a non-zero `refresh_interval` leaves an *enabled* hourly beat task re-refreshing that account for the life of the instance. Two tests, split on observability: one REST-only (`refresh_interval` persists; `cron_expression` round-trips — not a tautology, since both serializers rebuild it in `to_representation` from `refresh_task.crontab`; switching back to an interval clears it), one through `instance.manage(['dumpdata', …])` for `PeriodicTask.enabled`, `IntervalSchedule.every` and `_cleanup_orphaned_interval`, none of which has any REST surface. **No tick is ever waited for** — the interval branch is `get_or_create(every=max(int(interval_hours), 1) …, period=HOURS)`, so the smallest schedulable unit is an hour and every assertion is about the schedule as written. Both tests are `@characterization` because the file owns a container and is on `CONTAINER_LIFECYCLE`; the portability split (test 1 portable, test 2 coupled to django-celery-beat's tables) lives in each test's own comment. Uses intervals 8541/8542 and is the one exemption from the #7 uniqueness rule — `workers: 1`, `fullyParallel: false`, its own instance, no `bootstrap` dependency, so the race is structurally impossible rather than avoided; moving it to a shared project revokes the exemption. Note for readers of the old row: `should_be_enabled`'s `enabled` argument is **not** a constant — the signals pass `instance.is_active`, so an inactive source gets a disabled task whatever its interval | G12 | done |
| Lifecycle | Durable state across a restart and an upgrade — seven relations on top of the seven scalar rows: Channel→Streams **in order** (`toEqual`, since the order decides primary vs failover upstream), a *disabled* ChannelProfileMembership (asserting an enabled one would catch nothing — `create_profile_memberships` re-creates it at that default, so a membership that returns enabled IS the loss), EPG programme titles for the channel (titles, not a count), an XC user whose credentials still authenticate through the raw request context, a VOD movie/series/episode including `episode.series.id`, a scheduled Recording still pointing at its channel, and the logo bytes. Both mutation-checked: reversing the stream array and skipping the membership disable each fail with their own message. **`instance.restart()` stops the provider container and `ScenarioRegistry` is an in-memory `Map`, so every upstream scenario is forgotten across the event** — every assertion therefore reads Dispatcharr's own database through its own API, and the obvious extension (re-refresh the account and compare) cannot work here | G12 | done |
| Lifecycle | Bash suite triage — dead premise: `upgrade_explicit_puid` seeded "old UID 102 data" by booting `ghcr.io/dispatcharr/dispatcharr:latest`, which is no longer pre-PUID (it creates 1000:1000 with `dispatch` as bootstrap superuser and no `postgres` role), making both its assertions unreachable. The release-image path is deleted; the manual seeder (initdb as the `postgres` OS user, producing 102:104) is now the only one | G12 | done |
| Lifecycle | Bash suite triage — removed feature: PUID auto-detect was deleted from the product on purpose by `7e221720`; the suite arrived in `52ed0fc1`, the same PR that added it, and was never updated. `upgrade_auto_adapt`/`bind_mount_auto_adapt` are renamed `*_default_puid` and assert what the product does (default PUID to 1000 and migrate), plus a `check_log_absent "PUID not set"` guard so the *removal* is itself pinned | G12 | done |
| Lifecycle | Bash suite triage — host portability: all seven TLS failures were one exception. `mktemp -d` gives the certificate directory 0700 owned by the invoking user, and the app reads `/certs` as `dispatch` (UID 1000), so `settings.py` died at import with `PermissionError` on `/certs/ca.crt`. Two further instances of the same class were found only in CI: `modular_tls_key_permission` mounts a **second** `mktemp -d`, and the `alpine/openssl` container writes every file root-owned so the suite user could not read `client.key` to build its 0777 copy. Invisible on Docker Desktop, which presents bind mounts permissively and remaps ownership — this suite's certificate handling was only ever correct on a Mac | G12 | done |
| Lifecycle | Bash suite triage — pipe safety: both suites run under `set -o pipefail` and their wait loops used `docker logs … \| grep -q PATTERN`. `grep -q` exits at first match and closes the pipe; when the producer is still writing it dies of SIGPIPE and pipefail returns **141 for the whole pipeline even though grep matched**, so a successful match reads as a failure and the loop burns its entire budget. This was `pg_major_upgrade`, the one row the G12 spec could not classify — not a CI-environment defect and not a product defect. A `log_matches` helper gives the wait loops the file-capture idiom `check_log_contains` already had. Fixing it also exposed a race it had been hiding: the Celery TLS banners are printed after the marker the loop returns on, and the old loop's full-budget spin had been granting them 90–240s of unintended grace, so those two assertions had never actually verified anything | G12 | done |
| Lifecycle | **Known bug, no test reproduces it:** `_validate_tls_cert_paths` (`dispatcharr/settings.py:18`) raises a raw `PermissionError` instead of its own `ImproperlyConfigured` when the app user cannot read a certificate — `Path.is_file()` raises on `EACCES` rather than returning `False`, so an operator mounting a Kubernetes secret or a root-owned `:ro` volume gets a traceback at Django import instead of the actionable message the function exists to produce. [#128](https://github.com/D10Scot/Dispatcharr/issues/128). **Deliberately unreproduced** (D3): the bash suites have no `test.fail()`, so a scenario written to fail would put `lifecycle-tests.yml` straight back where G12 found it | G12 | known-bug |
| Lifecycle | **Known bug, no test reproduces it:** a failed `pg_upgrade` is reported as `Upgrade complete.` and the empty new cluster replaces the old data. `docker/init/02-postgres.sh:234` never checks the exit status, and the two `mv`s that swap the freshly-`initdb`'d directory into place run regardless — while the `apt install` two blocks above it *does* check, so this is a local omission, not house style. The old data survives as `db_backup_*`, recoverable only by someone who knows to look. [#129](https://github.com/D10Scot/Dispatcharr/issues/129). **Deliberately unreproduced**, same reason | G12 | known-bug |
| DVR | A scheduled recording fires through `run_recording`: `status` flips to `'recording'` at the very top of the function — before `_build_output_paths`, `get_dvr_stream_base_url()` or FFmpeg even spawns, so a bare `live === 1` read races the HLS playlist and every later check polls instead of trusting it — plays back in progress once the playlist gains a real `seg_` segment, completes, and is served as an MKV with `Content-Range`/`Accept-Ranges`. A synthetic broken-upstream run (channel pointed at an unreachable URL) confirmed a failed recording ends `interrupted`, naming the cause in `interrupted_reason` (`no_stream_data: rc=183`) rather than a bare timeout. `tests/dvr/recording-execution.spec.ts`; ~40s, measured twice in isolation (`task-4-report.md`) | G13 | done |
| DVR | An ad-hoc recording's fallback output path is `TV_Shows/<start>.mkv` with no channel subdirectory, not the documented `TV_Shows/<show>/<start>.mkv`: `_build_output_paths`'s `show = program.get('title') if isinstance(program, dict) else channel.name` (`apps/channels/tasks.py:1032-1033`) never reaches the `channel.name` fallback because `program` is always `{}` for an ad-hoc recording with no EPG match, and `_safe_name(None)` returns `""`. A passing `@characterization` premise test pins the path-root/timestamp-filename shape that holds regardless of the defect; a `test.fail()`, also `@characterization`, pins the intended shape. Filed as [#135](https://github.com/D10Scot/Dispatcharr/issues/135). `tests/dvr/recording-execution.spec.ts` | G13 | known-bug |
| DVR | Stopping an in-flight recording (`POST /stop/`) preserves `status: 'stopped'` and keeps the partial MKV. A second `POST /stop/` on an already-stopped row is idempotent and returns 200, not 409: the terminal-state guard's set is `{completed, interrupted, failed}` (`api_views.py:3549`) — `stopped` is deliberately excluded, already pinned by the unit test `test_stop_idempotent_on_already_stopped`. `tests/dvr/recording-control.spec.ts`; ~34s | G13 | done |
| DVR | Extending an in-flight recording (`POST /extend/`) raises `end_time` through a signal-bypassing `.update()` (avoiding a `pre_save` revoke of the running Celery task); the running task's 2s poll picks up the new deadline. The discrimination window runs to +40s past the *original* `end_time`: the finalisation path's HLS concat/remux (`tasks.py:~2148-2211`, a plain `ffmpeg -c copy` `subprocess.run` with no `timeout=`) is unbounded by code, and 22s was what one idle-runner observation showed, not a derived bound. `tests/dvr/recording-control.spec.ts`; ~65s | G13 | done |
| DVR | Cancelling an upcoming (not-yet-fired) recording sends `recording_cancelled` with `was_in_progress: false`; the row 404s immediately. `tests/dvr/recording-events.spec.ts`; <1s | G13 | done |
| DVR | Cancelling an in-flight recording sends `recording_cancelled` with `was_in_progress: true` and releases the upstream (`live` drops to 0). `RecordingViewSet.destroy` deletes the `Recording` row synchronously (`api_views.py:3846`) before the background thread that removes the file/HLS directory even starts (`:3941`), and `file()` opens with `get_object_or_404` (`:3385`) — so the post-cancel `GET /file/` 404 is proof the row is gone, not proof anything was removed from disk (see the updated Frontend/G6 gap row above). `tests/dvr/recording-events.spec.ts`; ~17s | G13 | done |
| DVR | A recurring rule (`POST /api/channels/recurring-rules/`) materialises 14-15 `Recording` rows synchronously on create — one per matching weekday across `[start_date, end_date]`, each asserted against its own computed weekday in the system time zone — and `purge_recurring_rule_impl` deletes them all on `DELETE`. `start_date`/`end_date` are required by the serializer on every create. `tests/dvr/recurring-rules.spec.ts`; <2s | G13 | done |
| DVR | Comskip dispatch: a completed recording with `dvr_settings.comskip_enabled` on queues `comskip_process_recording`, which reaches a terminal `custom_properties.comskip.status === 'completed'`, `skipped: true` — the synthetic `testsrc`+tone asset has no commercial structure for `detect_method=127` (`docker/comskip.ini:12`) to find, so `skipped: true` is the only terminal state reachable here, not a downgrade from a richer one. `@characterization`: pins the fixed ini path (`/app/docker/comskip.ini`) and this image's asset shape. Three runs at ~36-38s; `dvr_settings` restored byte-identical every time, including across two mid-run SIGINTs — Playwright 1.62.1's own graceful-interrupt path still ran the interrupted test's `afterEach`, stated as an observation on this Playwright version, not a guarantee. `tests/dvr/comskip.spec.ts` | G13 | done |
| DVR | **Decision, not a gap:** [#131](https://github.com/D10Scot/Dispatcharr/issues/131) (two `Recording`s at an identical `clocked_time` racing `ClockedSchedule.objects.get_or_create` — `MultipleObjectsReturned` swallowed by `schedule_task_on_save`'s blanket `except Exception` at `signals.py:383`, so the row still saves 201 with `task_id` left null and no log, no `SystemEvent`, no WebSocket message) is deliberately not reproduced, the same shape as G3's decision on [#7](https://github.com/D10Scot/Dispatcharr/issues/7) in `e2e/README.md`: provoking it needs two `Recording`s created at the exact same instant, and nothing in this API can delete the resulting duplicate `ClockedSchedule` row — the failure is permanent for that clock time on the shared container | G13 | done |
| DVR | **Known defect:** `sync_recurring_rule_impl`'s `horizon_days` branch is dead code from the REST API — `perform_create`/`perform_update` always pass `drop_existing=True` and the serializer requires `end_date`, so `if drop_existing and end_limit: end_window = end_limit` always runs and the `horizon`-bounded `else` never executes. An API-created rule with a far-future `end_date` materialises every matching day between now and then synchronously, in one request, with nothing capping it — each row firing its own `ClockedSchedule`/`PeriodicTask` create. Filed as [#138](https://github.com/D10Scot/Dispatcharr/issues/138); the recurring-rule row above deliberately uses a 14-day `end_date` rather than reproducing the unbounded case | G13 | known-bug |
| DVR | **Gap:** the `days_of_week` weekday mapping is proven only for an all-seven-day rule (the recurring-rule row above); a narrower set (e.g. weekdays only) is untested, though the same tz-aware per-row assertion would exercise it unchanged | G13 | done |
| DVR | **Gap:** a recurring rule's own materialised recording actually firing (reaching `run_recording`) is untested. `sync_recurring_rule_impl` skips any slot where `start_dt <= now`, so the earliest a rule-created `Recording` can fire is a day out — there is no bounded-time path from rule creation to execution the way the ad-hoc `POST /api/channels/recordings/` flagship has | G13 | done |
| DVR | **Gap:** series rules (`SeriesRulesAPIView`, `evaluate_series_rules`) are untested — EPG-programme-driven; names G14 | G13 | done |
| DVR | **Gap:** comskip's actual commercial-detection logic (not just dispatch and terminal-state handling) is untested — deferred, not missed. G2's synthetic asset (`lavfi testsrc` + a 440Hz tone, no logo/black/silence/scene-cut structure) gives `detect_method=127` nothing to find; a fixture with synthetic ad breaks is a provider build, fenced by the roadmap's own non-goals | G13 | done |

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

The seventeen G5 rows above — eleven `done` and six `known-bug` — are covered by these eleven
specs (several rows share a file, and each known-bug row lives beside the test that qualifies it,
following the same convention G3's `m3u-ingest.spec.ts` and `m3u-refresh-failure.spec.ts` set):

- `e2e/tests/seeded/output-m3u.spec.ts` — `/output/m3u` parses and streams end to end and
  `/output/m3u/<profile>` scopes to Channel Profile membership, plus the quote-escaping known bug
  (`#80`)
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

The twenty-two `done` and `known-bug` G9 rows above are covered by these twelve specs (several
rows share a file, and each known-bug row lives beside the test that qualifies it, following the
same convention G3's and G5's blocks set):

`seeded`:

- `e2e/tests/seeded/vod-fixture.spec.ts` — the VOD fixture helpers themselves
- `e2e/tests/seeded/vod-ingest-fidelity.spec.ts` — catalogue ingest: categories, movies and series
  land as `VODCategory`/`Movie`/`Series` and their `M3U*Relation` rows, plus the
  `VODCategoryFilter.m3u_account` known bug (`#96`)
- `e2e/tests/seeded/vod-category-gating.spec.ts` — category gating on and off, and the
  `Uncategorized` fallback
- `e2e/tests/seeded/vod-episodes.spec.ts` — on-demand episode ingest, both the object-keyed and
  array-keyed `episodes` shapes
- `e2e/tests/seeded/vod-advanced-data.spec.ts` — advanced movie data via `get_vod_info` and its
  24-hour refresh throttle
- `e2e/tests/seeded/xc-vod-catalogue.spec.ts` — the XC VOD and series actions against a real
  catalogue, plus the `xc_get_vod_info` known bug (`#97`)

`streaming`:

- `e2e/tests/streaming/vod-stream.spec.ts` — the `vod_proxy` streaming path: session mint,
  redirect, byte delivery
- `e2e/tests/streaming/xc-vod-playback.spec.ts` — the root XC `/movie/`/`/series/` routes, plus
  the `Response`-not-imported (`#100`) and episode-`DoesNotExist`-guard (`#99`) known bugs
- `e2e/tests/streaming/vod-range.spec.ts` — Range and seek, plus the range-unsupported (`#66`,
  both the capability row and its byte-level elaboration), suffix-range (`#64`) and
  fresh-session-416 (`#98`) known bugs
- `e2e/tests/streaming/vod-adult-streamable.spec.ts` — the `stream_xc_movie`/`stream_xc_episode`/
  `stream_vod` adult-filter known bug (`#110`)
- `e2e/tests/streaming/vod-upstream-error.spec.ts` — the deliberately unfiled provider-credential
  disclosure known bug

`streaming-greybox`:

- `e2e/tests/streaming-greybox/vod-redirect-profile.spec.ts` — VOD Redirect mode sends the client
  at the provider and carries no bytes

`e2e/tests/seeded/vod-catalogue-ingest.spec.ts` and `e2e/tests/streaming/vod-byte-read.spec.ts`
remain **G8's** rows and were not touched by this goal.

The twelve `done`/`known-bug` G10 Catch-up rows above are covered by these eight specs. Seven are
G10's own new files; the eighth, `catchup-cascade.spec.ts`, is G8's — G10 appends four tests to it
rather than creating its own cascade file, so its one pre-existing test (the PATH-then-QUERY
fallback) stays attributed to G8's row further up this table:

- `e2e/tests/seeded/catchup-ingest.spec.ts` — the ingest rollup, `rollup_channel_catchup_fields`,
  proved in both directions (a provider turning `tv_archive` on, and off again)
- `e2e/tests/seeded/catchup-m3u-advertisement.spec.ts` — a premise guard, the generated M3U's
  catch-up omission (`#94`), and the XC catalogue's counterpart showing the asymmetry
- `e2e/tests/seeded/catchup-preconditions.spec.ts` — a positive control, then all four catch-up
  preconditions (non-catch-up channel, unparseable start, absent start, deactivated account)
  failing closed before the provider is ever contacted
- `e2e/tests/seeded/catchup-session-api.spec.ts` — `POST /api/catchup/sessions/`'s mint contract,
  its refusal on a non-catch-up channel, the Streamer/Standard authorization split, and
  `DELETE`'s round trip and cross-user refusal
- `e2e/tests/streaming/catchup-cascade.spec.ts` — G8's PATH-then-QUERY fallback test, plus G10's
  four: the exhaustive seven-candidate walk over all four timestamp shapes, the per-account
  format-index cache (and its per-channel isolation), the decisive-401 failure class, and the
  soft-404/no-sync failure class
- `e2e/tests/streaming/catchup-provider-timezone.spec.ts` — `server_info.timezone` driving
  `convert_timestamp_to_provider_tz`, parameterised across a UTC control and a non-UTC zone, plus
  the seconds-truncation known bug (`#111`)
- `e2e/tests/streaming/catchup-proxy-mode.spec.ts` — proxy mode end to end across every entry
  point that reaches `_serve_catchup`: an exact-request-count native route, both root XC routes
  reaching the same cascade, the provider stream id read off the request log, a minted session's
  headerless playback, and the `hide_adult_content` known bug (`#95`)
- `e2e/tests/streaming-failover/catchup-redirect.spec.ts` — Redirect mode's three entry points
  (native and both root layouts), each 302ing in the client's own layout, with an empty provider
  log proving the mode fetches nothing

`e2e/tests/streaming/catchup-path-layout.spec.ts` (G8) and `catchup-cascade.spec.ts`'s original
PATH-then-QUERY test remain the plumbing proofs this goal builds on rather than replaces — neither
is touched by any G10 task.

## Guards (G11)

Static analysis in the `guards` project. No container, no browser — each of
these enforces a rule that previously lived in prose and decayed silently.
Every one is verified by mutation, recorded in its own header comment.

| Guard | Enforces | Proved by |
|---|---|---|
| `tests/guards/tags.spec.ts` | Every test declaration carries exactly one of `@contract` / `@characterization`, directly or inherited from a `describe`. Fails closed on a details object it cannot read — and that check does not wait on the warning→blocking flip | Blocking mode listed all 191 declarations; tagging one dropped it to 190; both tags reported as a conflict; a details object passed by reference failed *in warning mode* |
| `tests/guards/capabilities.spec.ts` | Four grey-box capabilities confined to `tests/guards/allowlist.ts`: the `instance` fixture, `node:child_process`, the grey-box Redis helper, and `pgrep`/`docker `/`manage.py` in string literals. Scans `tests/`, `fixtures/` and `setup/` | A real `child_process` import failed; `pgrep` in a **comment** passed; `pgrep` in a string literal failed; `instance` destructured outside the lifecycle specs failed |
| `tests/guards/testid.spec.ts` | Every `SURFACES` testId exists as a `data-testid` under `frontend/src/`. One-directional; carries a self-check so a broken scan blames itself | Renaming `stats-page` in `frontend/src/` failed naming the Stats surface |
| `tests/guards/global-mutation.spec.ts` | Any write to `/api/core/settings/` confined to an allowlist. Resolves module-level string constants, without which three of the four real writers are invisible | A real `api.patch` to the route failed; the same route in a comment passed |
| `tests/guards/pageerrors-enforcement.spec.ts` | Every test under `tests/frontend/` destructures `pageErrors` (moved here from `tests/frontend/`; verdicts unchanged) | An untagged `test({ page })` added to `stats.spec.ts` failed; reverting passed |

**Six of the eight files a `grep` flags for `pgrep`/`docker `/`manage.py` match
only in comments.** That ratio is why these guards parse with the TypeScript
compiler API instead of scanning text — a guard that fires on prose gets
loosened until it catches nothing.

Not enforced, and deliberately named as such in
`docs/adr/0003-e2e-frontend-and-shared-state-contract.md`: the "never assert a
global count or unfiltered list" and "never assert on a toast" rules remain
review-only, because neither has a reliable static signature.
