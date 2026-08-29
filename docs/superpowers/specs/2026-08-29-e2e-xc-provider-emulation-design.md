# G8 — XC Provider Emulation

**Date:** 2026-08-29
**Status:** Approved, ready for implementation planning
**Wave:** 3 (G1 landed at `a0c99cdd`, G2 at `c188aab6`, G4 at `6e71ca20`; G8 branches from `main`
at `c1e82c76` and is dispatched once G5 lands)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Siblings in flight:**

- **G5** (client output surfaces, branch `feat/e2e-output-surfaces-g5`, unmerged) is where **G8
  itself is defined**. Its branch already edits both
  `docs/superpowers/specs/2026-08-23-e2e-coverage-roadmap-design.md` and `e2e/COVERAGE.md` to add
  G8 and move the catch-up row to it. **G5 lands first; G8 rebases through it.** G8's own edit to
  those two files deliberately adds *only* G9 and G10, so the resolution is mechanical, and is
  specified once here so nobody has to re-derive it:
  1. **Goals table** — keep G5's `G8` row verbatim; keep G8's `G9` and `G10` rows; order them
     G7, G8, G9, G10. Heading reads "The ten goals".
  2. **Dependency diagram** — take **G8's version whole**. A diagram is not composable hunk-wise;
     G8's already includes G5's `G5 ─→ G8` edge, and it is the only place G8's roadmap edit names
     G8 at all.
  3. **Goal notes** — keep G5's `**G8**` paragraph *and* G8's `**G8 was itself split**`,
     `**G9**` and `**G10**` paragraphs. They do not overlap: G5's says why G8 exists, G8's says
     why it shrank.
  4. **Rule 3** — "how ten agents avoid duplicating each other" (G5 wrote "eight").
  5. **`COVERAGE.md`** — of G5's four provisional `G8` rows: re-label the catch-up row and the
     `catchup=` gap row to **G10** (and change "Decide in G8" to "Decide in G10"), re-label the
     "XC VOD and series actions against a real catalogue" row to **G9**, and **delete** the
     "Fake provider speaks Xtream Codes" row — G8's five finer-grained build rows supersede it.
     Header reads "all ten goals".
- **G3** (content sources & ingest) collides on `e2e/fixtures/seed.ts`, `e2e/fixtures/types.ts`,
  `e2e/fixtures/index.ts`, `e2e/COVERAGE.md` and `e2e/README.md`. G8 adds one seeder method
  (`seed.xcAccount`) at the end of the existing factory list; every collision is additive.
- **G6** (frontend surfaces) collides on `e2e/COVERAGE.md` only.
- **G7** (deployment lifecycle, branch unmerged) edits `e2e/playwright.config.ts`,
  `.github/workflows/e2e-tests.yml` and `scripts/e2e_up.sh`. **G8 edits none of those three**
  (D20, D21), so the two overlap only on `e2e/COVERAGE.md` and `e2e/README.md`.

## Goal

Teach the G2 fake provider to speak Xtream Codes: a `player_api.php` that answers the
authentication handshake and the seven catalogue actions `core/xtream_codes.Client` calls, a VOD
and series catalogue served as a **finite, Range-capable** file, and catch-up URLs in both
layouts `apps/timeshift/helpers.py` builds.

**G8 is a build. It ships plumbing proofs, not coverage** — exactly as G2 did. It succeeds if
G9's and G10's agents can write "the provider serves this catalogue / answers only this layout /
refuses Range, now assert Dispatcharr does Y" without reading `e2e-upstream/src/`.

The roadmap records why this shape is not negotiable: G5 was given a test goal *and* a build,
and had to be split because the build blocked a dozen cheap server-side tests behind it. G8 must
not repeat that. G2's plumbing-proof discipline is the mechanism that keeps a build shippable.

## Current state

`e2e-upstream/` is a Node HTTP server with three provider-facing routes — `/s/<id>/playlist.m3u`,
`/s/<id>/epg.xml`, `/s/<id>/stream/<channelId>.ts` — a control API, eight faults, and a paced,
endless MPEG-TS loop. It knows nothing about Xtream Codes, VOD, series or catch-up.

Consequently:

- **An `M3UAccount` of `account_type` `XC` has nothing to point at.** Every XC ingest path in
  `apps/m3u/tasks.py` and the whole of `apps/vod/tasks.py` are unobserved end to end.
- **`apps/proxy/vod_proxy/` is unobserved end to end.** It is at 35.6% unit coverage and is a
  different architecture from live streaming: `iter_content` passthrough, one upstream per
  session, session id in the URL path.
- **`apps/timeshift/` has nothing to point at.** `_stream_from_provider` walks seven candidate
  URL shapes and caches the winner per account; no test outside the unit suite has ever watched
  it choose.
- G5's XC rows assert the four VOD/series list actions return `[]` and the two detail actions
  return `404`, because a fresh instance has no catalogue. That is the honest assertion available
  without this build, and it is the ceiling G8 lifts.

## Verified facts this design rests on

Cited by symbol or filename, never by line number — line numbers in this repo drift, and an
earlier spec in this series shipped four wrong ones. Every row below was read this session.

| Fact | Source | Consequence |
|---|---|---|
| `Client` calls exactly one endpoint, `player_api.php`, with `username`/`password` and an optional `action`; the actions are `get_live_categories`, `get_live_streams` (with and without `category_id`), `get_vod_categories`, `get_vod_streams`, `get_vod_info`, `get_series_categories`, `get_series`, `get_series_info` | `core/xtream_codes.py`, `Client._make_request` and its callers | The endpoint surface is **bounded and small**. Eight action values plus the bare handshake. Anything else in the published XC "spec" is out of scope by construction |
| `_make_request` raises on any non-2xx (`raise_for_status`), on an empty body, on a body whose stripped text is `blocked`/`forbidden`/`access denied`/`unauthorized`, on invalid JSON, and on a dict with `user_info is None` **and** an `error` key | `core/xtream_codes.py`, `Client._make_request` | The provider must never send an `error` key at top level on a success, and every list action must return a JSON **array** (`isinstance(..., list)` is re-checked by each caller) |
| **`authenticate()` checks only that `user_info` is truthy.** It never reads `auth` or `status` | `core/xtream_codes.py`, `Client.authenticate` | A provider answering `200` with `{"user_info": {"auth": 0, "status": "Disabled"}}` is treated as **authenticated**. This is the `xc-auth-envelope` fault's whole point, and a characterization row for G9. See D13 |
| `get_account_info()` copies fifteen `user_info` keys and eight `server_info` keys into the profile's `custom_properties` | `core/xtream_codes.py`, `Client.get_account_info` | The auth envelope's required field set, in full. See "Required XC payload shapes" |
| `M3UAccountProfile.save()` re-parses `custom_properties['user_info']['exp_date']` on **every** save, accepting a unix timestamp (int, float, or numeric string) or an ISO string, and silently yielding `None` otherwise | `apps/m3u/models.py`, `_parse_exp_date`, `_parse_exp_date_from_custom_properties` | `exp_date` must be one of those shapes or absent. A shape like `"2026-12-31 00:00:00"` parses as neither and is dropped without a warning |
| `_prepare_catchup_stream_attempt` reads the provider timezone from the **default profile's** `custom_properties['server_info']['timezone']`, and `convert_timestamp_to_provider_tz` returns its input unchanged when that value is falsy or exactly `"UTC"`, and logs a warning and returns it unchanged for an unknown zone | `apps/timeshift/views.py`, `apps/timeshift/helpers.py` | The provider declares `timezone: "UTC"` so a test can predict the timestamp the provider will be asked for. See D12 |
| `normalize_server_url` strips query and fragment, strips a trailing path segment ending in `.php`, and **preserves the rest of the path** | `core/xtream_codes.py`, `normalize_server_url` | An XC `server_url` may carry a base path (`/s/<scenarioId>`) but **may not carry credentials in a query string**. See D3 |
| `Client.get_stream_url` / `get_vod_stream_url` / `get_episode_stream_url` produce `{server_url}/live/{user}/{pass}/{id}.ts`, `/movie/{user}/{pass}/{id}.{ext}`, `/series/{user}/{pass}/{id}.{ext}` | `core/xtream_codes.py` | Three playback route shapes the provider must serve, all under the scenario base path |
| `collect_xc_streams` builds the live URL itself as `{server_url}/live/{user}/{pass}/{stream_id}.ts` and never reads `direct_source` | `apps/m3u/tasks.py`, `collect_xc_streams` | `direct_source` may be omitted from the payload entirely |
| `refresh_account_on_save` skips the automatic refresh for `account_type == Types.XC` — `if created and instance.account_type != M3UAccount.Types.XC` | `apps/m3u/signals.py` | An XC account created through the API does **not** self-refresh. `waitFor.m3uRefreshComplete`'s own trigger is the only refresh, so there is no race with a background one. This is the opposite of the standard-M3U path G2's ingest proof used |
| An `M3UAccountProfile` named `"<account> Default"` is created by `post_save` with `is_default`, `is_active`, `search_pattern="^(.*)$"`, `replace_pattern="$1"` | `apps/m3u/models.py` | The identity transform. `get_transformed_credentials` returns the account's own URL/username/password unchanged, so no profile setup is needed |
| The XC group refresh queues `refresh_account_profiles.delay(account.id)`, which authenticates per profile and merges `get_account_info()` into `profile.custom_properties` | `apps/m3u/tasks.py`, `refresh_m3u_account_groups`, `refresh_account_profiles` | `server_info.timezone` reaches the DB **asynchronously**, after the refresh the test waited on. A catch-up test must poll the profile, not assume it |
| `ChannelGroupM3UAccount.enabled` defaults to `True`; XC categories become groups keyed by `custom_properties['xc_id']`, and only `enabled=True` groups with an `xc_id` are collected | `apps/channels/models.py`; `apps/m3u/tasks.py`, `refresh_m3u_account_groups`, `refresh_m3u_account` | A first XC refresh enables every declared category, so a two-phase refresh is not needed to see streams |
| Live stream ingest reads `stream_id`, `name`, `category_id`, `epg_channel_id`, `stream_icon`, `num`, `stream_type`, `added`, `is_adult`, `custom_sid`, and `str()`s every other key into `Stream.custom_properties` | `apps/m3u/tasks.py`, `collect_xc_streams` | `custom_properties['stream_id']` is what `_prepare_catchup_stream_attempt` later reads. It is a **string** |
| `tv_archive` is compared as `str(...) in ("1", "True")` and `tv_archive_duration` is `int(... or 0)`, on both the all-streams and per-category paths | `apps/m3u/tasks.py` | `tv_archive: 1` (int) works because it is `str()`d into `attributes` first; `tv_archive: true` (JSON bool) becomes `"True"` and also works |
| `rollup_channel_catchup_fields(account_id)` runs inside `refresh_m3u_account` and updates **every** channel holding a stream from that account, including channels created by hand through the API | `apps/m3u/tasks.py` | A channel wired to ingested XC streams gets `is_catchup` on the **next** refresh, not at creation. See D19 |
| `is_catchup` and `catchup_days` are writable fields on `ChannelSerializer` | `apps/channels/serializers.py` | A PATCH is available as a fallback, and skips the product code the row exists to exercise. See D19 |
| VOD refresh is fired as `refresh_vod_content.delay(account_id)` **after** the M3U refresh finishes, gated on `custom_properties['enable_vod']` and `account_type == XC` | `apps/m3u/tasks.py`, `refresh_m3u_account`; `apps/m3u/serializers.py` (`enable_vod` is a write-only serializer field stored in `custom_properties`) | `waitFor.m3uRefreshComplete` returning `success` says **nothing** about VOD. See D18 |
| `refresh_categories` returns `None` — aborting the whole VOD refresh — when the provider returns no categories *and* the account already has non-`Uncategorized` category relations | `apps/vod/tasks.py`, `_empty_categories_should_abort` | A scenario declaring zero VOD categories is a legitimate G9 case, not a G8 default |
| New `M3UVODCategoryRelation` rows are created `enabled=auto_enable_new_groups_vod` / `_series`, both defaulting to `True`, even though the model field defaults to `False` | `apps/vod/tasks.py`, `batch_create_categories`; `apps/vod/models.py` | The default path enables categories, so movies are not silently skipped |
| `VODCategory` is unique on `(name, category_type)` **globally**; `Movie` and `Series` are matched across all accounts by TMDB, then IMDB, then `(name, year)` | `apps/vod/models.py`; `apps/vod/tasks.py`, `process_movie_batch`, `process_series_batch`, `lookup_by_name_year` | Two parallel workers running the default catalogue share one `Movie` row with two `M3UMovieRelation`s. The aliasing hazard is **worse** than G2's. See D7 |
| `batch_process_episodes` accepts `episodes` as either a JSON object keyed by season number or a JSON array indexed by position, and reads `id`, `title`, `episode_num`, `container_extension` and a nested `info` | `apps/vod/tasks.py`, `batch_process_episodes` | Both shapes are real and both are declarable. `id` is the episode's provider stream id |
| `refresh_series_episodes` is reached synchronously from `GET /api/vod/series/<pk>/provider-info/`, never from the refresh | `apps/vod/api_views.py`; `apps/vod/tasks.py` | The episode plumbing proof drives that endpoint. It also forces the fetch when `episodes_fetched` is unset |
| `refresh_movie_advanced_data` requires `'info' in vod_info` and reads `vod_info['movie_data']` separately, tolerating either as a list | `apps/vod/tasks.py`, `refresh_movie_advanced_data` | `get_vod_info` must return `{"info": {...}, "movie_data": {...}}`, not a bare info dict |
| **`head_vod` is not routed.** `apps/proxy/vod_proxy/urls.py` maps only `stream_vod` (four patterns), `vod_stats` and `stop_vod_client` | `apps/proxy/vod_proxy/urls.py`; CLAUDE.md, "Dead or unwired" | The `Range: bytes=0-1` probe expecting a 206 with `Content-Range` lives **in `head_vod`** and is therefore dead code. See D9 — this contradicts the brief |
| On the live path, `RedisVODConnection.get_stream` sends the client's `Range` verbatim (after validating it against a known `content_length`) and learns the full file size from the response's `Content-Range`, falling back to `Content-Length` | `apps/proxy/vod_proxy/multi_worker_connection_manager.py`, `get_stream` | The finite-asset requirement stands, for a different reason than the brief gave: without `Content-Length` there is no `state.content_length`, so Range validation is skipped and the client response carries neither `Accept-Ranges` nor `Content-Range` |
| The client-facing response sets `status 206 if range_header else 200`, and emits `Accept-Ranges`/`Content-Length`/`Content-Range` **only** when `connection_headers['content_length']` is set | `apps/proxy/vod_proxy/multi_worker_connection_manager.py`, `stream_content_with_session` | Dispatcharr labels its own response 206 regardless of what the provider returned. A `range-unsupported` provider therefore produces a 206 whose body is the whole file — a G9 assertion, not a G8 one |
| `stream_vod` with no `session_id` either 301s to the provider (Redirect default profile) or mints a session and redirects to `<path>/<session_id>` | `apps/proxy/vod_proxy/views.py`, `stream_vod`, `_vod_session_path_redirect` | The VOD byte-read proof must follow a redirect before it sees any bytes |
| `M3UMovieRelation.get_stream_url` / `M3UEpisodeRelation.get_stream_url` return `None` for any non-XC account | `apps/vod/models.py` | VOD playback is XC-only. There is no standard-M3U VOD path to emulate |
| `build_timeshift_candidate_urls` returns **seven** URLs: three PATH forms (`%Y-%m-%d:%H-%M`, `%Y-%m-%d_%H-%M`, `%Y-%m-%d:%H:%M:%S`) then four QUERY forms (underscore, SQL `%Y-%m-%d %H:%M:%S`, colon-dash, colon-seconds) | `apps/timeshift/helpers.py`, `build_timeshift_candidate_urls` | Blocking the PATH layout costs three attempts before the first QUERY attempt. The provider must recognise all four timestamp shapes |
| `build_timeshift_url_format_a` URL-encodes only username and password — `start` is interpolated raw, so the SQL shape puts a literal space in the query string | `apps/timeshift/helpers.py` | The provider's query parser must tolerate a space in `start` (`requests` percent-encodes it in transit; Node's `URL` decodes `+` and `%20` differently — parse with `URLSearchParams`, never by splitting on `+`) |
| `client_timeshift_url_layout` returns `"query"` only when `timeshift.php` appears in the request path; everything else, including `/proxy/catchup/`, is `"path"` | `apps/timeshift/helpers.py` | Redirect mode mirrors the client's own shape and never cascades |
| `_stream_from_provider` accepts a candidate only on 200/206 **with a TS sync byte in the first 1024 bytes** (or a 206 answering a client `Range`); a 200 without sync is downgraded to `last_status = 404` and the walk continues; 401/403/406 and 3xx set `decisive_failure` and stop the walk; 416 is passed straight through | `apps/timeshift/views.py`, `_stream_from_provider` | Catch-up must be served as real MPEG-TS, and a 404 per layout is the correct lever for forcing the cascade |
| The winning candidate index is cached per account in the Django cache (`_set_cached_format_index` / `_get_cached_format_index`) and reordered to the front of the next walk | `apps/timeshift/views.py` | The cascade is **not** fresh per request. A cascade test must either use a fresh account or expect the reordering |
| The duration handed to the provider is the client's hint plus `DURATION_BUFFER_MINUTES` (5), capped, or the EPG programme length plus the same buffer, or `DEFAULT_DURATION_MINUTES` (120) | `apps/timeshift/helpers.py`, `client_duration_to_window`, `resolve_catchup_duration` | A test asking for `/60/` sees the provider recorded `65`. Assert the derived value, not the requested one |
| `catchup_proxy` requires an authenticated user or a valid playback `session_id`, `is_catchup_enabled`, `Channel.is_catchup`, and at least one stream with `is_catchup` on an **active XC** account | `apps/timeshift/views.py`, `catchup_proxy`, `_serve_catchup`; `apps/channels/utils.py`, `get_channel_catchup_streams`, `is_catchup_enabled` | Five preconditions, each with its own failure response. The plumbing proof must satisfy all five before it can observe a single provider request |
| `streamLoop` writes `200` with `Content-Type: video/mp2t` and **deliberately no `Content-Length`**, because the loop has no end | `e2e-upstream/src/stream.ts` | Range support cannot be retrofitted onto this path. See D8 |
| `ScenarioLog` records exactly four kinds — `request`, `open`, `close`, `fault` — from four `record()` call sites, with `request` carrying `method`, `path` and `status` | `e2e-upstream/src/log.ts`, `e2e-upstream/src/server.ts` | The catch-up "what was I asked for" assertion is a `path`/query read off `request` entries. No new log kind is needed; a fifth would break G4's existing readers |
| `parseScenarioRequest` rejects a `password` with no `username`, rejects control characters in channel names, and rejects duplicate channel ids, each with a named `BadRequestError` | `e2e-upstream/src/scenario.ts` | The validate-at-the-door house style every new field must follow |
| `credentialsMatch` returns `true` whenever `scenario.username` is undefined | `e2e-upstream/src/server.ts` | An XC scenario with no declared credentials would accept any credentials, making every auth fault untestable. See D4 |
| The `upstream` CI job runs `e2e-upstream`'s vitest with **no `needs: build`**, and the provider image is built inside the existing `build` job from `e2e-upstream/Dockerfile` | `.github/workflows/e2e-tests.yml` | New vitest files and a second builder-stage asset need **no workflow edit**. See D20 |
| Playwright projects map 1:1 to CI matrix jobs: `[pristine, seeded, streaming, streaming-failover, streaming-greybox]`; `seeded` runs 4 workers at the 30s global timeout, `streaming` runs 2 workers at 300s | `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml` | Placing the proofs in existing projects avoids a sixth container per CI run. See D16 |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **G8 is the build alone. Its consumers are G9 and G10, defined in the roadmap by this same PR and specced when scheduled** | G5 was given a build and a test goal and had to be split; G8 as first defined repeated that shape exactly. G2 is the counter-example: a build ships when it stops at plumbing proofs. Rejected: keeping the VOD and catch-up coverage in G8, which is the decision that made G5 unshippable |
| D2 | **The endpoint list comes from `core/xtream_codes.Client`; the payload shape comes from its consumers.** Never from the published Xtream "spec" | No two real providers agree on that spec, and implementing it would be unbounded work against an unverifiable target. The client bounds the surface at one endpoint and eight actions. But the *caller* is not the only reader: `apps/m3u/tasks.py` and `apps/vod/tasks.py` read fields off the returned dicts, so satisfying `Client` is necessary and not sufficient. This is the largest source of hidden work in the goal — see "Required XC payload shapes", which is the derived answer and is normative |
| D3 | **XC lives under the existing `/s/<id>` scenario prefix.** An XC scenario's `server_url` is its `internal` base, unchanged; no new origin, port, container or network | `normalize_server_url` preserves a base path, so `http://e2e-upstream:8080/s/<id>` yields `player_api.php`, `/live/...`, `/movie/...`, `/series/...` and `/timeshift/...` all under the scenario prefix — the same per-test isolation G2 chose (its D6), for free. **Consequence, stated because it is easy to get wrong: `credentialQuery` must never be appended to an XC `server_url`.** `normalize_server_url` strips the query, so the credentials would vanish; XC carries them as real `username`/`password` parameters, which is what `Client` sends anyway |
| D4 | **`xc: true` is an explicit per-scenario opt-in, and it requires `username`** | Two reasons. Opt-in: the XC routes 404 on a non-XC scenario, so a G3 or G4 test cannot accidentally reach them, and the log says which surface was asked for. Requiring credentials: `credentialsMatch` returns `true` when `username` is undefined, so an XC scenario without them would accept anything and every auth fault would pass vacuously. Enforced in `parseScenarioRequest` with a named 400, mirroring the existing "password requires username" check |
| D5 | **Live categories become first-class**: a scenario-level `liveCategories`, defaulting to `[{ id: 1, name: 'E2E' }]`, and an optional `categoryId` on `ChannelSpec` defaulting to `1` | `get_live_categories` must return stable `category_id` values, and `collect_xc_streams` filters live streams by `str(category_id)` against the enabled groups. Defaulting to the single `E2E` category leaves `renderPlaylist`'s existing `group-title="E2E"` byte-identical, so no G2/G3/G4 test changes. Rejected: deriving categories from the M3U `group-title` string, which gives no stable id and would couple two renderers |
| D6 | **VOD and series catalogues are declared exactly like channels**: `vodCategories`, `vod`, `seriesCategories`, `series`, each `number \| Spec[]` | One shape for the whole scenario request. `channels: 3` already means "give me three defaults", and a test author who has used that once knows all four |
| D7 | **The default catalogue is identical across scenarios, and the aliasing hazard is worse than G2's.** The README says so for movie titles, series names and category names, not only channel names | G2 already warns that `Fake Channel 1` aliases across four parallel workers. VOD is worse: `VODCategory` is unique on `(name, category_type)` **globally**, and `Movie`/`Series` are matched across *all* accounts by TMDB → IMDB → `(name, year)`. Two workers running the default catalogue therefore share one `Movie` row carrying two `M3UMovieRelation`s — which is correct product behaviour and a false-pass generator for any test that filters by a default name. Keeping the default identical (rather than randomising it) preserves G2's discipline: the fix is the same one G2 already teaches, "pass explicit names", and randomising would hide the hazard rather than remove it |
| D8 | **A second, finite asset and a second serving path.** `assets/vod.mp4`, built in the same Docker builder stage, served with `Content-Length`, `Accept-Ranges: bytes`, real 206 + `Content-Range`, and 416 on an unsatisfiable range | Not a parameter on the TS loop: `streamLoop` is endless and deliberately sends no `Content-Length`, and its whole pacing/fault/backpressure machinery exists for a stream with no end. Range serving is a different function with different invariants. The two share nothing but a `readFileSync`. Rejected: serving the TS loop with a fabricated `Content-Length`, which would make every seek assertion a lie |
| D9 | **Range behaviour is implemented and verified against `stream_vod`'s live path, not `head_vod`** | **This corrects the brief.** The `Range: bytes=0-1` probe expecting a 206 with `Content-Range` is in `head_vod`, which `apps/proxy/vod_proxy/urls.py` does not route — CLAUDE.md lists it under "Dead or unwired". The finite-asset requirement survives intact for a different reason: on the live path `RedisVODConnection.get_stream` learns the file size from `Content-Range`, falling back to `Content-Length`, and the client-facing response emits `Accept-Ranges`, `Content-Length` and `Content-Range` only when that size is known. A provider with no `Content-Length` therefore produces a VOD response with no seek metadata at all |
| D10 | **Catch-up answers both layouts and all four timestamp shapes, records what it was asked for, and serves the ordinary looping TS regardless** | `_stream_from_provider` requires a TS sync byte in the first 1024 bytes, so the response has to be real MPEG-TS. Making the archive time-addressable would mean generating a distinct asset per requested instant, which is a build of its own and buys nothing the recorded request parameters do not already prove. The cost is stated as a named gap, not glossed: see Non-goals |
| D11 | **`catchup-layout-404` takes a required `layout: 'path' \| 'query'`** | This is the lever that makes the cascade observable, and it is the part of catch-up most likely to be wrong. With PATH blocked, a correct cascade shows three PATH 404s and then a QUERY request that serves bytes; a broken one shows something else, loudly. A layout-less variant would be indistinguishable from the existing `not-found` fault, so it is rejected at the door with a named 400 |
| D12 | **The default auth envelope declares `server_info.timezone: "UTC"`** | `convert_timestamp_to_provider_tz` returns its input unchanged for a falsy value or exactly `"UTC"`, so the timestamp the test asks for is the timestamp the provider records. Any other zone makes every catch-up assertion depend on the date the suite happens to run (DST), and an unknown zone is silently ignored with only a log line. A scenario may override it — proving the conversion happens is a G10 row |
| D13 | **The existing `auth-failure` fault is honoured on the XC routes; the genuinely new fault is `xc-auth-envelope`, a `200` carrying `{"user_info": {"auth": 0, "status": "Disabled"}}`** | **This refines the brief's "XC auth failure".** A second 401-shaped fault would duplicate `auth-failure`, whose documented semantics ("credentials that were valid start being rejected") already fit `player_api.php` exactly, and whose 401 is what `refresh_m3u_account_groups` classifies as an auth error. What is *not* covered is the XC-native failure: real panels answer `200` with `auth: 0`, and `Client.authenticate()` never reads that field, so Dispatcharr treats the response as a successful login. That is a product characterization worth a fault of its own and a G9 inventory row. G8 does not file it — G8 hits it while building, not while testing |
| D14 | **`no-tv-archive` is a fault, not a scenario field** | As a fault it can be armed between two refreshes of the same account, which is what exercises `rollup_channel_catchup_fields`'s self-heal pass (`is_catchup` going back to `FALSE` when the provider stops advertising the archive). As a scenario field it could only ever express the initial state. New-connection-only, `appliedTo: 0` |
| D15 | **`range-unsupported` answers `200` with the whole body and no `Accept-Ranges`, ignoring the request's `Range`** | That is what a provider that does not implement Range actually does — not a 416, and not a 501. New-connection-only, `appliedTo: 0`. G9 uses it to pin what Dispatcharr does with such a provider; G8 only proves the fault is armable and observable in the log |
| D16 | **Five plumbing proofs, in the existing `seeded` and `streaming` projects.** XC live ingest and VOD catalogue ingest in `seeded`; the VOD byte read and both catch-up proofs in `streaming` | G2's precedent (its ingest proof in `seeded`, its stream-through proof in `streaming`), and the split follows the projects' actual capabilities: `seeded` is 4 workers at the 30s global timeout and does no byte reading; `streaming` is 2 workers at 300s and is where `streamClient` and the long product-defined waits already live. The catch-up cascade proof needs both a byte read and a multi-attempt provider walk, so it cannot go in `seeded` |
| D17 | **The XC ingest proof relies on `waitFor.m3uRefreshComplete` owning the trigger, and says in a comment why that is safe here** | `refresh_account_on_save` skips the auto-refresh for XC accounts, so unlike the standard-M3U path there is no background refresh to race. This is worth a comment precisely because it is the *opposite* of what G2's ingest proof relies on, and a reader who knows that file will otherwise assume the same hazard applies |
| D18 | **The VOD proof polls for rows; it does not treat `m3uRefreshComplete` as a VOD signal** | `refresh_vod_content` is a separate Celery task fired with `.delay()` after the M3U refresh returns, so the account reaches `success` before any `Movie` exists. Mechanism: `waitFor.resource` on `/api/vod/movies/?search=<generated name>` until `count` is the declared number. No new fixture — this is exactly what `waitFor.resource` is for |
| D19 | **The catch-up proofs get `Channel.is_catchup` by re-running the account refresh after the channel is wired, not by PATCHing the field** | `rollup_channel_catchup_fields` runs inside `refresh_m3u_account` and covers any channel holding a stream from that account, including one created through the API — but only on a refresh, so a channel created *after* the first refresh needs a second. `is_catchup` is writable on `ChannelSerializer`, and PATCHing it is recorded here as the fallback if the double refresh proves flaky; it is not the default because it skips the ingest code the proof is partly there to exercise |
| D20 | **No new Playwright project, no CI matrix job, and `.github/workflows/e2e-tests.yml` is not edited** | The `upstream` job already runs `e2e-upstream`'s vitest and picks up new test files automatically; the provider image is already built in `build` from `e2e-upstream/Dockerfile`, so a second builder-stage asset needs no workflow change. Not editing that file also keeps G8 clear of the zizmor ratchet, which blocks on *every* finding in an edited workflow, and clear of the unmerged G7 branch. Rejected: an `xc` project, which would buy isolation nothing here needs |
| D21 | **`scripts/e2e_up.sh` is not edited** | No new container, no new published port, no new readiness wait. The single-boot-path invariant holds unchanged, and this is the second of the three files G7 edits that G8 leaves alone |
| D22 | **The XC surface goes in new leaf modules under `e2e-upstream/src/xc/`; `server.ts` gains one delegation, not six routes** | `server.ts` is already 615 lines and ten routing branches; the XC work is roughly the same size again, and inlining it would double the one file every future provider change has to be read alongside. `server.ts` consults an XC route table before falling through to its own 404, so the existing routes are untouched and the diff is reviewable |
| D23 | **Every new field is validated at the door, in the `parseScenarioRequest`/`parseFaultRequest` style, naming the offending field** | The house style, and the reason for it is in `scenario.ts`'s own header: a silently-coerced typo produces "expected 3 movies, got 0" and sends the test author looking at Dispatcharr's parser instead of their own request body. The new surface is where that failure mode multiplies |
| D24 | **No test asserts a global count or an unfiltered list; every proof locates its own rows by a generated name** | Roadmap rule 4, and D7 makes it sharper here than anywhere else in the programme: `Movie`, `Series` and `VODCategory` are shared rows, so "there are N movies" is not a weaker assertion, it is a false one |
| D25 | **Defects found while building are recorded as G9/G10 inventory rows, not filed by G8** | Roadmap rule 5 binds *test* agents to `test.fail()` plus an issue. G8 writes no test of the behaviours it noticed (`authenticate()` ignoring `auth`; the absent `catchup=` M3U attribute), so it has nothing to mark `test.fail()`. Filing an issue for a behaviour no test pins produces an issue nobody can verify closed. The consumer goal that writes the test files the issue, with an explicit `--repo D10Scot/Dispatcharr` |

## Required XC payload shapes

Derived by reading the consumers, not the caller. **This section is normative**: it is the
answer to the design's largest hidden-work risk, and an implementer who satisfies `Client` alone
will produce a provider Dispatcharr ingests as empty.

Fields are grouped as **required** (a consumer reads it and something visible breaks or silently
empties without it) and **read** (a consumer reads it, and absence is handled). Anything not
listed may be omitted.

### `player_api.php` with no `action` — the auth envelope

Required: `user_info` must be present and truthy, or `authenticate()` raises. `server_info` must
be a dict.

`get_account_info` copies these, and they land in `M3UAccountProfile.custom_properties`:

- `user_info`: `username`, `password`, `message`, `auth`, `status`, `exp_date`, `is_trial`,
  `active_cons`, `created_at`, `max_connections`, `allowed_output_formats`
- `server_info`: `url`, `port`, `https_port`, `server_protocol`, `rtmp_port`, `timezone`,
  `timestamp_now`, `time_now`

Two of those are load-bearing beyond storage: `user_info.exp_date` is re-parsed on every
`M3UAccountProfile.save()` and must be a unix timestamp or an ISO string (see the `_parse_exp_date`
row in the fact table), and
`server_info.timezone` drives `convert_timestamp_to_provider_tz` (D12). `user_info.auth` is
**not** checked by the product — that is the `xc-auth-envelope` fault (D13).

Must **not** carry a top-level `error` key.

### `get_live_categories`

A JSON array. Each entry: `category_id` (required — becomes
`ChannelGroupM3UAccount.custom_properties['xc_id']`), `category_name` (required — becomes the
`ChannelGroup` name).

### `get_live_streams` (with or without `category_id`)

A JSON array. Each entry:

- **Required:** `stream_id` (int or numeric string — `int()`-ed into `Stream.stream_id`, and
  interpolated into the playback URL), `category_id` (string-compared against the enabled group's
  `xc_id`; a stream whose category is not enabled is dropped), `name`.
- **Read:** `epg_channel_id` → `Stream.tvg_id`; `stream_icon` → `Stream.logo_url`; `num` →
  `Stream.stream_chno` (float-able); `is_adult` → `Stream.is_adult`; `tv_archive` →
  `Stream.is_catchup`; `tv_archive_duration` → `Stream.catchup_days`; `stream_type`, `added`,
  `custom_sid` — carried into `Stream.custom_properties` and not otherwise interpreted.
- Every other key is `str()`-ed into `Stream.custom_properties`. `direct_source` is never read.

### `get_vod_categories` / `get_series_categories`

JSON arrays of `{ category_id, category_name }`. Both are required per entry: the id keys the
provider→`VODCategory` map, the name is the `VODCategory` name and the map's lookup key.

### `get_vod_streams`

A JSON array. Each entry:

- **Required:** `stream_id` (→ `M3UMovieRelation.stream_id`, `str()`-ed and unique per account),
  `name`, `category_id`.
- **Load-bearing:** `container_extension` (default `'mp4'`) — it is the file extension in the
  playback URL `M3UMovieRelation.get_stream_url` builds, so it must match what the provider
  actually serves.
- **Read:** `tmdb_id`/`tmdb` and `imdb_id`/`imdb` (`''`, `0` and `'0'` are normalised to `None`);
  `description` or `plot`; `rating` or `vote_average`; `genre` or `category_name`; `duration_secs`
  or `duration`; `trailer` or `youtube_trailer`; `director`; `actors` or `cast` (string or array);
  `release_date` or `releasedate`; `stream_icon` (→ `VODLogo`, ignored above 500 characters);
  `is_adult` (**only applied when the key is present**, deliberately); `year`.
- Year resolution order: `year`, then `releaseDate`/`release_date`, then a `(YYYY)`/`- YYYY`/
  trailing-`YYYY` pattern in `name`. Only 1900–2030 is accepted. Since `(name, year)` is the
  fallback identity key across accounts, **a declared movie should carry an explicit `year`**.
- The whole entry is stored verbatim as `M3UMovieRelation.custom_properties['basic_data']`.

### `get_series`

A JSON array. Each entry:

- **Required:** `series_id` (→ `M3USeriesRelation.external_series_id`), `name`, `category_id`.
- **Read:** `plot`, `rating`, `genre`, `cover` (→ `VODLogo`), `releaseDate` or `release_date`
  (→ year), `tmdb`/`tmdb_id`, `imdb`/`imdb_id`.
- Copied into `Series.custom_properties` when non-empty: `backdrop_path`, `poster_path`,
  `original_name`, `first_air_date`, `last_air_date`, `episode_run_time`, `status`, `type`,
  `cast`, `director`, `country`, `language`, `releaseDate`, `youtube_trailer`, `category_id`,
  `age`, `seasons`.
- Note the key skew against movies, which is real and must be reproduced: series use `cover` (not
  `stream_icon`), `plot` (not `description`), `releaseDate` (not `release_date`) first, and
  `tmdb`/`imdb` before `tmdb_id`/`imdb_id`.

### `get_series_info&series_id=<id>`

A JSON **object** (`isinstance(..., dict)` is checked):

- `info`: read for `plot`, `rating`, `genre`, and a year via `year`/`releaseDate`/`release_date`.
  Only fills fields that are currently empty on the `Series`.
- `episodes`: either an object keyed by season number (`{"1": [...]}`) or an array indexed by
  position. Each episode entry:
  - **Required:** `id` (→ `M3UEpisodeRelation.stream_id`, and the id in the playback URL),
    `episode_num`, `title`.
  - **Load-bearing:** `container_extension` (default `'mp4'`) — same reason as movies.
  - **Read**, under a nested `info` object: `plot` or `overview`, `rating`, `duration_secs`,
    `tmdb_id`, `imdb_id`, `crew`, `movie_image`, `backdrop_path`, and a date via `air_date`,
    `releasedate` or `release_date`.
  - `Episode` is unique per `(series, season_number, episode_number)`; several stream ids may map
    to one episode, which is normal and worth one declarable case for G9.

### `get_vod_info&vod_id=<id>`

A JSON **object** containing **both** `info` and `movie_data` (`refresh_movie_advanced_data`
requires `'info' in vod_info` and reads `movie_data` separately; either may legitimately be a
list, and the product takes the first element — a declarable variant for G9).

`info` is read for `plot`, `rating`, `genre`, `duration_secs`, `releasedate`/`release_date`,
`tmdb_id`, `imdb_id`, `trailer`/`youtube_trailer`, `backdrop_path`, `actors`/`cast`, `director`.
Both dicts are stored on `M3UMovieRelation.custom_properties` as `detailed_info` and `movie_data`.

## Playback and catch-up route shapes

All under the scenario base `/s/<id>`:

| Route | Built by | Serves |
|---|---|---|
| `player_api.php` | `Client._make_request` | JSON, per the section above |
| `live/<user>/<pass>/<streamId>.ts` | `Client.get_stream_url`, `collect_xc_streams` | The paced TS loop — the same `streamLoop` the existing `/stream/<id>.ts` route uses |
| `movie/<user>/<pass>/<streamId>.<ext>` | `M3UMovieRelation.get_stream_url` | The finite VOD asset, Range-capable (D8) |
| `series/<user>/<pass>/<streamId>.<ext>` | `M3UEpisodeRelation.get_stream_url` | The finite VOD asset, Range-capable |
| `timeshift/<user>/<pass>/<duration>/<start>/<streamId>.ts` | `build_timeshift_url_format_b` | The paced TS loop |
| `streaming/timeshift.php?username=&password=&stream=&start=&duration=` | `build_timeshift_url_format_a` | The paced TS loop |

The two catch-up routes accept all four timestamp shapes `build_timeshift_candidate_urls`
produces and record `username`, `stream`, `start` and `duration` — plus which layout was used —
in the scenario log's existing `request` entry (`path` already carries the PATH form's segments,
and the QUERY form's search string is appended to it). **No new `LogEntry` kind**: G4 already
reads this log and a fifth kind would break its readers.

The live and catch-up routes share `streamLoop` and therefore share `maxConnections` accounting,
`dead-air`, `slow-trickle` and `disconnect`. That is deliberate — a G10 test that wants a
catch-up stream to stall uses the faults it already knows.

## Scenario declaration

Additions to `ScenarioRequest`, all optional, all validated at the door (D23):

```ts
xc?: boolean;                              // default false; requires `username` (D4)
liveCategories?: CategorySpec[];           // default [{ id: 1, name: 'E2E' }]
vodCategories?: CategorySpec[];            // default [{ id: 1, name: 'E2E Movies' }]
seriesCategories?: CategorySpec[];         // default [{ id: 1, name: 'E2E Series' }]
vod?: number | MovieSpec[];                // default 1 when xc, 0 otherwise
series?: number | SeriesSpec[];            // default 1 when xc, 0 otherwise
account?: Partial<AccountEnvelope>;        // overrides on user_info / server_info
```

`ChannelSpec` gains `categoryId?: number` (default `1`). `CategorySpec` is `{ id, name }`.
`MovieSpec` is `{ id, name, year?, categoryId?, containerExtension?, tmdbId?, imdbId? }`.
`SeriesSpec` is `{ id, name, categoryId?, seasons: [{ number, episodes: [{ id, title,
episodeNum, containerExtension? }] }] }`.

Defaults mirror `Fake Channel 1`: `Fake Movie 1` and `Fake Series 1`, one season, one episode
`Fake Series 1 S01E01`. **D7's hazard applies to all three names**, and the README says so
alongside G2's existing channel-name warning rather than in a new section — a test author reading
about aliasing should meet all of it at once.

`POST /scenarios` echoes the catalogue back alongside `channels`, so a test never has to
reconstruct ids it did not declare.

## Fault catalogue additions

Four new faults, following G2's conventions exactly — per-channel scoping where it means
something, `appliedTo` counting only connections actually reached, and the new-connection-only
faults documented as `appliedTo: 0` being correct rather than a partial failure.

| Fault | Applies to | Behaviour | Drives |
|---|---|---|---|
| `xc-auth-envelope` | new only (`appliedTo: 0`) | `player_api.php` answers `200` with `user_info.auth = 0`, `status = "Disabled"` | The product's unchecked `auth` field (D13) — a G9 characterization |
| `no-tv-archive` | new only (`appliedTo: 0`) | `get_live_streams` omits `tv_archive` and `tv_archive_duration` | `rollup_channel_catchup_fields`'s self-heal pass; catch-up unavailability |
| `catchup-layout-404` | new only (`appliedTo: 0`) | 404s the named `layout` (`'path'` or `'query'`; required) on the catch-up routes | The seven-candidate cascade (D11) |
| `range-unsupported` | new only (`appliedTo: 0`) | The VOD asset routes ignore `Range` and answer `200` with the whole body and no `Accept-Ranges` | What Dispatcharr does with a provider that will not serve 206 — a G9 row |

The existing `auth-failure` and `not-found` faults extend to the XC routes with their existing
semantics; `dead-air`, `slow-trickle` and `disconnect` reach the live and catch-up routes because
those share `streamLoop`. `connection-limit`, `redirect-chain` and `non-ts-bytes` behave on the
new routes as they do on the old.

`e2e-upstream/README.md`'s fault table grows by four rows in the same PR, and its "Provider-facing
endpoints" list grows by the six routes above. That is a deliverable, not a follow-up: the
definition of done is that a G9 or G10 agent never opens `src/`.

## Project topology

```
bootstrap ──┬─→ seeded      (existing) +2 specs   4 workers, 30s
            └─→ streaming   (existing) +3 specs   2 workers, 300s
```

No new project, no new CI job, no `e2e_up.sh` change (D16, D20, D21). `e2e-upstream`'s own vitest
suite grows by roughly one file per new module and is already wired into the `upstream` CI job
with no `needs: build`.

## Test inventory

Five Dispatcharr-facing plumbing proofs. Each proves *wiring*, and each is written so that its
failure names the wire that broke.

| # | COVERAGE row | Project | Mechanism | Est. |
|---|---|---|---|---|
| 1 | Plumbing proof: XC account ingest → declared live streams appear | `seeded` | XC scenario with two explicitly named channels in one named category; `seed.xcAccount()` at `scenario.internal`; `waitFor.m3uRefreshComplete` owns the trigger (D17); assert both streams by generated name, `custom_properties.stream_id` matching what was declared, and `is_catchup`/`catchup_days` derived from `tv_archive` | 45s |
| 2 | Plumbing proof: VOD catalogue ingest → `Movie`, `Series` and `Episode` rows appear | `seeded` | Same account with `enable_vod: true`; after the refresh, `waitFor.resource` on `/api/vod/movies/?search=<name>` and `/api/vod/series/?search=<name>` (D18); then `GET /api/vod/series/<pk>/provider-info/` and assert the declared episode exists with its season and episode numbers | 90s |
| 3 | Plumbing proof: one VOD byte read through `/proxy/vod/` | `streaming` | `GET /proxy/vod/movie/<movie.uuid>` following the session redirect; read bytes; assert `Content-Length` and `Accept-Ranges: bytes` are present and the body prefix matches the asset; then one mid-file `Range` and assert `206` with a `Content-Range` naming the full size | 60s |
| 4 | Plumbing proof: a catch-up URL reaches the provider in each layout | `streaming` | Channel wired to an ingested catch-up stream, `is_catchup` set by a second refresh (D19); drive the root PATH route and `streaming/timeshift.php` with the same start; assert the provider log records a request under each layout carrying the account credentials, the declared `stream_id`, the start timestamp unchanged (D12) and the client hint plus 5 minutes | 120s |
| 5 | Plumbing proof: the cascade falls back when one layout 404s | `streaming` | A **fresh** account (the winning index is cached per account); arm `catchup-layout-404 { layout: 'path' }`; drive `/proxy/catchup/<uuid>`; assert the log shows three PATH requests answered `404` followed by a QUERY request answered `200`, and that the client received TS-aligned bytes | 120s |

Rows 1–5 are the five `Upstream` plumbing-proof rows this PR adds to `COVERAGE.md`. The four
provider-capability rows above them (XC surface, finite asset, both catch-up layouts, four new
faults) are covered by `e2e-upstream`'s own vitest suite, exactly as G2's first two rows are.

**What these five deliberately do not assert**, because they are G9's and G10's:
category-enable gating, the `Uncategorized` fallback, advanced movie data, seek correctness,
`range-unsupported` behaviour, the decisive-failure classes, the cached-format-index reordering,
and redirect mode. G8 proves each is *reachable*; proving each is *right* is the consumer goal's
job, and a G8 that starts asserting them is a G8 that does not ship.

## Fixture additions

- **`seed.xcAccount(scenario, overrides?)`** — an `M3UAccount` with `account_type: 'XC'`,
  `server_url: scenario.internal`, `username`/`password` from the scenario, and `is_active: true`.
  Its doc comment must say **why it is not `seed.m3uAccount({ account_type: 'XC' })`**: the
  server URL must be the bare `internal` base with **no** `credentialQuery` (D3), and the
  credentials go on the model fields rather than in the URL — the exact inverse of the standard
  M3U path G2 documented, and the single mistake this factory exists to prevent.
- **`upstream.xcUrl(scenario)`** on `UpstreamClient` — returns `scenario.internal`, typed and
  named so a call site cannot reach for `playlistUrl()` by muscle memory. Its comment states the
  no-query rule once, where it is enforced.
- **`UpstreamScenario` gains `username?: string` and `password?: string`.** The provider already
  echoes both from `POST /scenarios` (`{ ...scenario, ...scenarioUrls(...) }`), but the fixture's
  type omits them, so today the only typed handle on a scenario's credentials is the
  pre-formatted `credentialQuery` — which is exactly the thing an XC account must *not* use (D3).
  `seed.xcAccount` needs the two values separately. `e2e-upstream/README.md`'s existing warning
  that scenario credentials are not secret from the control API or the test report covers them
  unchanged.
- **`e2e/fixtures/types.ts`** — `CategorySpec`, `MovieSpec`, `SeriesSpec`, `AccountEnvelope`, and
  the `xc`/catalogue fields on `ScenarioRequest`, each with the consumer it was derived from named
  in a comment, per that file's existing convention.
- **`upstream.fault()`'s `FaultName` union and `FaultOptions`** gain the four new faults and
  `layout`.

No new Playwright fixture is registered on `test.extend`: everything above is a `Seeder` method,
an `UpstreamClient` method, or a type.

## Non-goals

- **Everything G9 and G10 own.** VOD ingest depth, the XC VOD/series actions against real
  content, the `vod_proxy` streaming path beyond one byte read, catch-up correctness, redirect
  mode, the cascade's cached index, the decisive-failure classes. G8 ships the five proofs in the
  inventory above and stops.
- **A time-addressable archive.** The catch-up routes serve the same looping TS whatever `start`
  they are given. Stated plainly because it bounds what G10 can ever claim: **nothing proves
  Dispatcharr seeks to the right moment — only that it asks for the right one.** The recorded
  request parameters are the whole of the evidence. Making this real would mean generating a
  distinct asset per requested instant and is a build of its own; if G10 decides it needs one,
  that is a new goal, not a G10 task.
- **Series playback beyond a single-episode plumbing proof.** One episode, one byte read. Season
  packs, multi-stream episodes and container variety are declarable and are G9's to exercise.
- **Any product change.** Per roadmap rule 5, a defect found is asserted correct, marked
  `test.fail()` and filed with an explicit `--repo D10Scot/Dispatcharr`. G8 writes no test of the
  behaviours it noticed, so it files nothing and hands them to G9/G10 as inventory rows (D25).
- **Emulating the published Xtream Codes API.** Only what `core/xtream_codes.Client` calls and
  what `apps/m3u/tasks.py` and `apps/vod/tasks.py` read (D2).
- **Schedules Direct.** Third-party API, out of scope for every goal in this programme.

## Risks

- **The payload shape is the largest hidden cost, and it is easy to underestimate.** Satisfying
  `Client` is a morning's work; satisfying `apps/vod/tasks.py` is not. The failure mode is
  quiet — a refresh that reports `success` and creates zero rows, or rows missing the one field
  a later test filters on. Mitigation: "Required XC payload shapes" above is normative and was
  derived by reading the consumers, and the two ingest proofs assert *fields*, not row counts, so
  a sparse payload fails by name.
- **The build roughly doubles `e2e-upstream`.** `src/` is ~1,900 lines across thirteen modules
  today; expect it to land near twice that, plus a second asset pipeline and a second serving
  path, plus a comparable growth in `test/`. Mitigation: D22's module split keeps
  `server.ts` near its current size; the XC surface, the catalogue model, the VOD asset and
  catch-up are four independently testable units, each with its own vitest file, so the goal can
  be paused between them and still be shippable.
- **`Movie`, `Series` and `VODCategory` are shared rows across parallel workers** (D7). This is
  the sharpest instance of roadmap rule 4 in the programme. Mitigation: explicit names in every
  proof, the README warning extended to VOD titles, series names and category names, and no proof
  asserting a count that is not scoped to a generated name.
- **The four Lua scripts in `vod_proxy`'s stream counter bypass the metadata lock on purpose.**
  That is a real bug fix, pinned by `apps/proxy/vod_proxy/tests/test_vod_lock_contention.py`. G8
  does not touch them and neither should G9 — flagged here so the VOD goal inherits the warning
  rather than rediscovering it under a failing test.
- **The catch-up preconditions are a five-link chain** (authenticated user, `is_catchup_enabled`,
  `Channel.is_catchup`, a stream with `is_catchup` on an active XC account, and a parseable
  timestamp), and a break anywhere gives a terse HTTP error with no provider request at all.
  Mitigation: proofs 4 and 5 assert each precondition as it is established rather than only at
  the end, so a failure names the link.
- **`refresh_account_profiles` is asynchronous**, so `server_info.timezone` reaches the DB after
  the refresh completes. A catch-up proof that reads it too early sees `None` and — because
  `convert_timestamp_to_provider_tz` treats falsy exactly like `"UTC"` — still passes. Mitigation:
  the proofs poll the profile's `custom_properties` before asserting on a timestamp, so the pass
  is not for the wrong reason.
- **The winning candidate index is cached per account.** A cascade test run twice against the same
  account sees a different attempt order the second time. Mitigation: proof 5 uses a fresh account
  and says so; G10 inherits the constraint as a `COVERAGE.md` row of its own.
- **`Content-Type` on the VOD asset matters more than it looks.** `stream_vod` takes the
  provider's `Content-Type` if present and otherwise infers from the URL extension. Serving the
  right extension and the right type is what keeps the two paths from disagreeing; a mismatch
  surfaces as a client-side playback question nobody in this suite can answer.
