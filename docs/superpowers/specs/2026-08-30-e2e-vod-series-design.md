# G9 — VOD and Series End to End

**Date:** 2026-08-30
**Status:** Draft, ready for review
**Wave:** 4 (G1 landed at `a0c99cdd`, G2 at `c188aab6`, G4 at `6e71ca20`, G7 at `main`; G9 branches
from `main` once **G8** has landed, which in turn requires **G5**)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Verified at:** `8d6db577`. Every claim below was read out of the tree in this worktree during
this session; three were executed against `dispatcharr-testrunner` rather than only read, and say
so. Line numbers are given where a defect lives at one, and drift — the symbol name is the durable
half of every citation.

**Siblings and predecessors:**

- **G8** (`2026-08-29-e2e-xc-provider-emulation-design.md`) is G9's substrate. G9 writes no
  provider code except the small, named addendum in "What G9 needs from G8 that G8 does not have".
  It consumes `xc: true` scenarios, `vodCategories` / `seriesCategories` / `vod` / `series`,
  `seed.xcAccount`, the finite `assets/vod.mp4`, and the `range-unsupported`, `not-found` and
  `xc-auth-envelope` faults.
- **G5** (`2026-08-29-e2e-client-output-surfaces-design.md`) supplies `seed.xcUser()`, `xcQuery()`
  and the rule that client-facing surfaces are driven through Playwright's built-in `request`
  context rather than the `api` fixture (its D3). G9 inherits all three unchanged.
- **G3** (merged) owns M3U/XC **live** ingest. G9 touches no live ingest path.
- **G10** (catch-up) is disjoint in subject. The two share `e2e/COVERAGE.md`, `e2e/README.md`,
  `e2e/fixtures/types.ts` and `e2e/fixtures/seed.ts`; every G9 edit to those is additive and at the
  end of an existing list.

## Goal

Prove that an Xtream Codes catalogue becomes `VODCategory`, `Movie`, `Series` and `Episode` rows
with the right fields and the right gating; that the four XC VOD/series list actions and the two
detail actions answer correctly against **real content**; and that `vod_proxy` delivers those bytes
to a client, including Range and seek.

This is the largest untested area of the product by a wide margin. `apps/proxy/vod_proxy/` is at
35.6% unit coverage, `apps/vod/tasks.py` is 2,374 lines, and **nothing under `e2e/tests/` has ever
created a `Movie` row.** G5 could only assert that the six XC VOD paths do not error on an empty
catalogue; G8 proved one movie can be ingested and one byte read. G9 is the fidelity proof for
everything in between.

## Current state

- All eleven `G9` rows in `e2e/COVERAGE.md` are `todo`.
- `apps/vod/tests/` holds seven files, all `SimpleTestCase`/unit-level: episode payload shapes, the
  empty-category guard, `is_adult` backfill, series `provider_info` query counts, image and logo
  proxying, and detail preservation across a sync. None fetches over HTTP; none creates a
  `Movie` from a provider response.
- `apps/proxy/vod_proxy/tests/test_vod_lock_contention.py` is the only test of the streaming path,
  and it drives an in-memory `LockAwareFakeRedis` with hand-written Lua shims.
- G8 ships two VOD-adjacent plumbing proofs (catalogue ingest → rows exist; one byte read through
  `/proxy/vod/`). G9 must not restate either; both stay as G8's rows.

## Verified facts this design rests on

Cited by symbol and file; line numbers only where a defect is *located* by one. Every row was read
this session at `8d6db577`.

### Ingest

| Fact | Source | Consequence |
|---|---|---|
| `refresh_vod_content` walks `refresh_categories` (which calls `get_vod_categories` then `get_series_categories`) → `refresh_movies` (`get_vod_streams`, no `category_id`) → `refresh_series` (`get_series`, no `category_id`) → `cleanup_orphaned_vod_content`, all inside one `XtreamCodesClient` context | `apps/vod/tasks.py`, `refresh_vod_content` | Four provider calls per refresh, never a per-category call. `get_series_info` is **not** among them |
| **`POST /api/m3u/accounts/<id>/refresh-vod/` returns `202` and fires `refresh_vod_content.delay()`**, gated on `account_type == XC` and `custom_properties['enable_vod']` (400 otherwise) | `apps/m3u/api_views.py`, `M3UAccountViewSet.refresh_vod` | An explicit, idempotent VOD-refresh trigger exists. G8's D18 reaches VOD only via the post-M3U-refresh chain; G9 uses this instead, so a VOD assertion never depends on a live refresh it did not ask for. See D2 |
| **`M3UAccountViewSet.create` runs `refresh_m3u_groups(account_id)` synchronously for an XC account, and `refresh_categories(account_id)` synchronously when `enable_vod` is true** — neither is `.delay()`d, and neither is wrapped in `try` | `apps/m3u/api_views.py:136-145` | **This refines G8's fact that "an XC account created through the API does not self-refresh."** The `post_save` receiver skips it; the *viewset* does it inline. So the POST blocks on two provider round-trips, categories already exist when it returns, and a provider error during `refresh_categories` propagates as a `500` from the create. See defect 5 |
| `refresh_categories` returns `None` — aborting the whole refresh — when the provider returns no categories of a type *and* the account already has non-`Uncategorized` relations of that type | `apps/vod/tasks.py`, `_empty_categories_should_abort` | Expressible by re-pointing an account at a second scenario with zero VOD categories. The abort surfaces only as a task return string and a WebSocket message — no row changes |
| `batch_create_categories` creates each new `M3UVODCategoryRelation` with `enabled = custom_properties['auto_enable_new_groups_vod']` (movies) / `_series` (series), **both defaulting to `True`**, even though `M3UVODCategoryRelation.enabled` defaults to `False` on the model. Relations are `bulk_create(..., ignore_conflicts=True)`, so an existing relation's `enabled` is never overwritten by a later refresh | `apps/vod/tasks.py`, `batch_create_categories`; `apps/vod/models.py` | Gating is settable at create time via the account flag, and a manual re-enable **survives** every subsequent refresh. Both halves are assertable |
| `batch_create_categories` deletes relations whose category is no longer in the provider's list (excluding `Uncategorized`), then deletes any `VODCategory` left with no relation at all | `apps/vod/tasks.py`, `batch_create_categories` | `VODCategory` is unique on `(name, category_type)` **globally**, so a category name shared with another worker is a shared row. Generated category names are mandatory, not stylistic |
| `process_movie_batch` looks the provider's `category_id` up in a **string-keyed** map; a movie whose category is present but whose `M3UVODCategoryRelation.enabled` is `False` is `continue`d; a movie whose `category_id` is absent or unknown falls through to `categories['__uncategorized__']` and is skipped only if *that* relation is disabled | `apps/vod/tasks.py`, `process_movie_batch` | Gating is a *skip at ingest*, not a filter at read. A disabled category produces no rows at all |
| `refresh_movies` and `refresh_series` each `get_or_create` the `Uncategorized` `VODCategory` **and its relation** on every refresh, with `enabled = auto_enable_new_groups_vod` / `_series` | `apps/vod/tasks.py` | The `Uncategorized` relation and its enabled state are assertable on every refresh, with no uncategorised content needed |
| `cleanup_orphaned_vod_content(account_id=…, scan_start_time=…)` deletes that account's relations whose `last_seen < scan_start_time`, then deletes **every globally orphaned** `Movie` and `Series` (`m3u_relations__isnull=True`), account filter or not | `apps/vod/tasks.py`, `cleanup_orphaned_vod_content` | Content that stops being advertised disappears entirely, which is what makes the gating rows provable. Movies and relations are created inside one `transaction.atomic()`, so there is no window in which another worker's movie is transiently orphaned |
| `Movie` and `Series` are matched across **all** accounts by TMDB → IMDB → `(name, year)`; `year` resolution reads `year`, then `releaseDate`/`release_date`, then a pattern in `name`, accepting only 1900–2030 | `apps/vod/tasks.py`, `process_movie_batch`, `extract_year_from_data`, `lookup_by_name_year` | G8's D7 aliasing hazard in full. Every G9 movie, series and category name is generated |
| `M3UMovieRelation` stores the whole `get_vod_streams` entry as `custom_properties['basic_data']` and sets `detailed_fetched: False` at create; a later list sync merges `basic_data` without dropping `detailed_info` / `movie_data` | `apps/vod/tasks.py`, `process_movie_batch` | The relation is the read-back surface for "what did the provider actually say", and `/api/vod/movies/<pk>/providers/` serialises it with `fields = '__all__'` |
| `Movie.custom_properties` is set to `custom_props or None` at ingest and carries only `youtube_trailer`, `director`, `actors`, `release_date` | `apps/vod/tasks.py`, `process_movie_batch` | A movie declared without those four keys has `custom_properties = None`. That is the precondition of defect 2 |
| `refresh_series_episodes` is called **synchronously** from `SeriesViewSet.series_info` (`GET /api/vod/series/<pk>/provider-info/`) and from `xc_get_series_info`, and forces the fetch when `episodes_fetched` or `detailed_fetched` is unset, or `last_episode_refresh` is older than 24h | `apps/vod/api_views.py`, `SeriesViewSet.series_info`; `apps/output/views.py`, `xc_get_series_info` | Both surfaces make a live provider call inside the HTTP request. A test asserts on the response, not on a poll — and both need a raised per-test timeout |
| `batch_process_episodes` accepts `episodes` as a dict keyed by season number **or** a list indexed by position, uses the key/index as the season number, and creates one `Episode` per `(series, season, episode_num)` with one `M3UEpisodeRelation` per provider `id` | `apps/vod/tasks.py`, `batch_process_episodes`; `apps/vod/models.py` `Episode.Meta.unique_together` | Both shapes and the several-streams-one-episode case are declarable and assertable |
| `refresh_movie_advanced_data` is called **synchronously** from `MovieViewSet.provider_info` and from `xc_get_vod_info`; it requires `'info' in vod_info`, reads `movie_data` separately, tolerates either as a list, and stores `detailed_info` / `movie_data` on the relation with `detailed_fetched: True` and `last_advanced_refresh = now`. It is skipped when `detailed_fetched` is set and `last_advanced_refresh` is under 24h old, unless `force_refresh` | `apps/vod/tasks.py`, `refresh_movie_advanced_data`; `apps/vod/api_views.py`, `MovieViewSet.provider_info` | `?force_refresh=true` is the lever for a second fetch; the 24h throttle is assertable by driving the endpoint twice and reading `last_advanced_refresh` off the relation |
| `clean_custom_properties({})` returns `None` | `apps/vod/tasks.py`, `clean_custom_properties` | An advanced payload carrying none of trailer/director/actors/backdrop leaves `Movie.custom_properties` at `None` after a successful refresh. Precondition of defect 2, again |
| `MovieFilter` and `SeriesFilter` expose `m3u_account` (→ `m3u_relations__m3u_account__id`), `name` (icontains), `category` (`name\|type`), `year` and, for movies, `is_adult`; `VODPagination` is 20 with `page_size` up to 100, so `count` under a filter is a **scoped** count | `apps/vod/api_views.py` | `?m3u_account=<id>&name=<generated prefix>` is the scoping tool for every ingest assertion, satisfying roadmap rule 4 |
| `VODCategoryViewSet` declares **no pagination**, and its `list()` `get_or_create`s the two `Uncategorized` categories and, for **every active XC account on the instance with `enable_vod`**, their relations | `apps/vod/api_views.py`, `VODCategoryViewSet.list` | A `GET` with side effects that reach other workers' accounts. Assert category membership with `find`/`includes`, never a length, and never assert that an account *lacks* an `Uncategorized` relation |
| `PATCH /api/m3u/accounts/<id>/group-settings/` accepts `category_settings: [{ id: <VODCategory.pk>, enabled, custom_properties }]` and upserts `M3UVODCategoryRelation` on `(m3u_account, category)` with `update_fields=["enabled", "custom_properties"]` | `apps/m3u/api_views.py`, `M3UAccountViewSet.update_group_settings` | The gating write surface. Note the key is `id`, not `category`, and — as in G3's D8 — it is a full-field upsert, so omitting `custom_properties` writes `{}` |
| `enable_vod`, `auto_enable_new_groups_vod` and `auto_enable_new_groups_series` are **write-only** `BooleanField`s on `M3UAccountSerializer` that land in `custom_properties`, and are echoed back on read by `to_representation` | `apps/m3u/serializers.py` | Settable at create through `seed.xcAccount` overrides and readable back for free |

### The XC output surface (what G9 deepens)

| Fact | Source | Consequence |
|---|---|---|
| `xc_get_vod_streams` emits `stream_id = Movie.pk` and `category_id = VODCategory.pk` — **Dispatcharr identifiers, not the provider's** — and `xc_get_vod_info` looks its `vod_id` up as `movie_id` | `apps/output/views.py`, `xc_get_vod_streams`, `xc_get_vod_info` | The round trip closes: an id from the list action is the id the detail action takes. Anyone expecting the provider's `stream_id` will write a passing-for-the-wrong-reason test |
| `xc_get_series` emits `series_id = M3USeriesRelation.pk` (not `Series.pk`), and `xc_get_series_info` does `M3USeriesRelation.objects.get(id=series_id, m3u_account__is_active=True)` | `apps/output/views.py`, `xc_get_series`, `xc_get_series_info` | Also a closed round trip, but keyed on a *different* model from the movie pair. Both must be asserted, because the asymmetry is exactly the kind of thing a refactor breaks |
| Both list actions dedupe to one row per content id across providers, highest `m3u_account__priority` winning, via `DISTINCT ON` on PostgreSQL | `apps/output/views.py`, `_xc_fetch_priority_distinct_relations` | A movie ingested by two accounts appears once. G9 does not test multi-provider selection (Non-goals) but must not assume one relation per row |
| `xc_get_vod_streams` and `xc_get_vod_info` filter `movie__is_adult=False` for a non-admin with `hide_adult_content`; `xc_get_series` has no such filter and needs none (`Series` has no `is_adult` field) | `apps/output/views.py`; `apps/vod/models.py` | The VOD listing half of adult filtering is **correct**. The streaming half is not — see defect 4 |
| `xc_get_vod_categories` / `xc_get_series_categories` list every `VODCategory` with a relation on an **active account**, with no reference to `M3UVODCategoryRelation.enabled` | `apps/output/views.py` | Deliberate or not, gating is enforced at ingest and not at listing — so a disabled category simply has no content to list. Pinned as characterization, not asserted as a bug |

### The `vod_proxy` streaming path

| Fact | Source | Consequence |
|---|---|---|
| `/proxy/vod/` routes only `stream_vod` (four patterns), `vod_stats` and `stop_vod_client`. **`head_vod` is not routed** | `apps/proxy/vod_proxy/urls.py` | Confirms G8's D9 and CLAUDE.md. The `Range: bytes=0-1` probe lives in dead code; every Range assertion is made against `stream_vod` |
| `stream_vod` is `AllowAny`, gated only by `network_access_allowed(request, "STREAMS")`, whose default ACL is `0.0.0.0/0` | `apps/proxy/vod_proxy/views.py`, `stream_vod` | Everything below is reachable by an unauthenticated caller. That is what makes defects 1 and 4 severe rather than cosmetic |
| With no `session_id`, `stream_vod` either `302`s straight at the provider — `HttpResponseRedirect` — when the **global default Stream Profile** is the locked Redirect profile, or mints `vod_<ms>_<rand>` and returns a hand-built **`301`** to `<path>/<session_id>` | `apps/proxy/vod_proxy/views.py`, `stream_vod`, `_vod_session_path_redirect`; `core/models.py`, `CoreSettings.is_default_stream_profile_redirect` | **VOD Redirect mode is a global setting with no per-content override** — unlike live streaming, where G4 set it per stream. A Redirect test must mutate a `CoreSettings` row. See D5 |
| The mint redirect's `Location` is a **relative** path and strips `session_id` and `token` from the query | `apps/proxy/vod_proxy/views.py`, `_vod_session_path_redirect` | `fetch`'s default `redirect: 'follow'` reaches the session URL on the same origin with no rewriting, so `streamClient.open()` needs no special handling |
| `_select_vod_stream` walks relations in priority order but rejects a candidate only for a missing URL, a profile at capacity, or a non-`http(s)` URL — **it never connects**. The connection happens later in `RedisVODConnection.get_stream` | `apps/proxy/vod_proxy/views.py`, `_select_vod_stream`; `multi_worker_connection_manager.py`, `get_stream` | "Pre-stream failover only", located precisely: a provider that answers `404` is still selected, and there is no second attempt |
| `get_stream` learns `state.content_length` **only on `request_count == 1`**, from `Content-Range`'s total if present, else `Content-Length`; `_validate_range_header` therefore does nothing on a session's first request | `multi_worker_connection_manager.py`, `get_stream`, `_validate_range_header` | A first request carrying an unsatisfiable Range is passed to the provider verbatim. See defect 3 |
| The client-facing response sets `status_code = 206 if range_header else 200`, and emits `Accept-Ranges`, `Content-Length` and `Content-Range` **only** when `connection_headers['content_length']` is set. `Content-Range` is computed from the client's requested range and the stored full size, never from the provider's response | `multi_worker_connection_manager.py`, `stream_content_with_session` | Dispatcharr labels its own response, which is what makes the `range-unsupported` row (defect 6) a real assertion rather than a passthrough check |
| `Content-Type` comes from the provider's header, else is inferred from the URL extension, else `video/mp4` | `multi_worker_connection_manager.py`, `get_stream`, `infer_content_type_from_url` | The provider's `Content-Type` on `assets/vod.mp4` is load-bearing, as G8's last Risk says |
| Any exception from `get_stream` becomes `HttpResponse(f"Streaming error: {str(e)}", status=500)` | `multi_worker_connection_manager.py:1405`; the same shape at `apps/proxy/vod_proxy/views.py:845` | `requests`' `raise_for_status()` message ends `for url: <the full provider URL>` — which for XC carries the password in the path. See defect 1 |
| The root routes `movie/<user>/<pass>/<stream_id>.<ext>` and `series/<user>/<pass>/<stream_id>.<ext>` authenticate against `User.custom_properties['xc_password']` (401 on mismatch or absence, 404 on unknown username via `get_object_or_404`), resolve `movie_id` / `episode_id` — the **Dispatcharr PKs** — and delegate to `stream_vod` | `dispatcharr/urls.py`; `apps/proxy/vod_proxy/views.py`, `stream_xc_movie`, `stream_xc_episode` | Same credential model as G5's live `stream_xc`, so `seed.xcUser()` and `xcQuery()` carry over |
| The four Lua scripts (`_LUA_INCR_ACTIVE_STREAMS`, `_LUA_DECR_ACTIVE_STREAMS`, `_LUA_CLEANUP_IF_IDLE`, `_LUA_META_SAVE_IF_EXISTS`) mutate `active_streams` outside the session metadata lock, deliberately, and their header says why | `multi_worker_connection_manager.py` lines 20–85; `apps/proxy/vod_proxy/tests/test_vod_lock_contention.py` | See D12 |

### Harness

| Fact | Source | Consequence |
|---|---|---|
| At `8d6db577` the projects are `bootstrap`, `pristine`, `seeded` (4 workers, 30s), `streaming` (2 workers, 300s), `streaming-failover` (1 worker), `streaming-greybox` (1 worker), `lifecycle`, `lifecycle-upgrade`; the CI matrix is the first six minus `bootstrap` | `e2e/playwright.config.ts`; `.github/workflows/e2e-tests.yml` | **There is no `frontend` project yet** — the brief's list anticipates G6. G9 must not assume it |
| `streaming-greybox` is `workers: 1` because one spec reads a container-wide observable; its comment generalises to "a future grey-box test that mutates Redis directly" | `e2e/playwright.config.ts` | The existing home for container-wide state hazards. See D5 |
| `StreamClient.open(path, { headers, redirect })` sets arbitrary request headers and exposes `status` and `headers`; `readPackets(n)` is `takeBytes(n * 188)` and there is **no byte-granular reader** | `e2e/fixtures/stream-client.ts` | `Range` is expressible today; reading an exact byte count from an MP4 is not. See "Fixture additions" |
| `upstream.toControl(url)` rewrites a container-internal provider URL to one the Playwright host can reach, throwing on anything outside the internal origin | `e2e/fixtures/upstream.ts` | The test can fetch the same byte range **direct from the provider** and compare, so seek correctness needs no synthetic byte pattern in the asset. See D8 |
| `waitFor.resource(url, predicate)` polls any GET until a predicate holds, reporting the last body on timeout | `e2e/fixtures/wait.ts` | The mechanism for every "rows appeared" wait; no new waiter is needed |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **G9 is a consumer of G8 and writes no provider code beyond one named addendum.** Everything else it needs, G8 already ships | The programme's repeated failure has been goals that carried a build. G9's addendum is three optional fields on one existing parser (see below), each with a stated fallback if G8's implementer declines |
| D2 | **Every VOD refresh is triggered explicitly by `POST /api/m3u/accounts/<id>/refresh-vod/` and awaited with `waitFor.resource` on a filtered `/api/vod/movies/` or `/api/vod/series/` read** | G8's D18 correctly warns that `m3uRefreshComplete` says nothing about VOD. `refresh-vod` is better still: it is idempotent, needs no M3U refresh, and makes the VOD refresh the only thing the wait can be resolving. Rejected: waiting on the `vod_refresh` WebSocket message — `/ws/` is one broadcast group across four workers, and the roadmap prefers REST wherever it exposes the state |
| D3 | **Every scenario declares generated names for movies, series *and* categories** | `VODCategory` is unique on `(name, category_type)` globally and `Movie`/`Series` are matched across accounts by `(name, year)` when no external id is present. G8's D7 states the hazard; G9 is the goal that would actually trip over it. No G9 assertion is a count that is not scoped by `?m3u_account=` **and** a generated name |
| D4 | **Ingest, gating, episode, advanced-data and XC-surface rows go in `seeded`; every one raises its own timeout with `test.setTimeout()`** | They are HTTP reads and writes plus Celery-backed waits — `seeded`'s shape. But an XC account create alone blocks on two synchronous provider round-trips, and `seeded` inherits the global 30 000 ms. G3's D9 is the precedent: one line per test, reversible, and it does not slow the rest of the project |
| D5 | **The one VOD Redirect-mode row goes in `streaming-greybox`, not a new project** | `CoreSettings.is_default_stream_profile_redirect()` is global, and there is no per-movie or per-account override — the exact opposite of live streaming, where G4 passed `streamProfileId` per stream. So the row must mutate a global row and restore it in a `finally`, which is only safe under `workers: 1`. `streaming-greybox` is already serialised for precisely this class of hazard and its comment already generalises to it. Rejected: a new `vod` project — it costs a `playwright.config.ts` change, an `e2e-tests.yml` change (arming the zizmor ratchet, which blocks on **every** finding in an edited workflow), a `package.json` script and a sixth container per CI run, for one row |
| D6 | **Byte-reading rows go in `streaming`** (2 workers, 300s), following G8's D16 and G4's precedent | They need the fake provider, a long timeout and `streamClient`. Nothing else in G9 does |
| D7 | **XC surfaces are driven through Playwright's built-in `request` context with `xcQuery(seed.xcUser())`, never the `api` fixture** | G5's D3 verbatim: no real XC client carries a bearer token, and `ApiClient.send` retries on any 401, which would silently spend a refresh on the rows that assert a 401 |
| D8 | **Seek correctness is proved by differential comparison against the provider, not by a byte pattern in the asset** | `upstream.toControl()` lets the test fetch the identical `Range` straight from `assets/vod.mp4` and compare buffers. That proves Dispatcharr returned *the requested bytes* without requiring G8 to make the asset positionally self-describing, and it fails loudly if Dispatcharr silently returns the file from offset zero — which is exactly what defect 6 does |
| D9 | **Category gating is proved with the account flag, not by editing the provider's catalogue.** Create the account with `auto_enable_new_groups_vod: false`, refresh, assert zero movies; then `PATCH group-settings` with `category_settings: [{ id, enabled: true }]`, `refresh-vod`, assert the movies appear; then refresh a third time and assert `enabled` is still `true` | It exercises `batch_create_categories`'s `auto_enable_new` branch, `process_movie_batch`'s skip branch, the `group-settings` upsert, and `ignore_conflicts=True`'s "a manual enable is never re-disabled" property, in one arc — with no provider change and no second scenario. The reverse direction (enabled → disabled → content removed) is a second test in the same file and additionally pins `cleanup_orphaned_vod_content` |
| D10 | **The `Uncategorized` row asserts the relation, not a routed movie** | `refresh_movies`/`refresh_series` create the `Uncategorized` category and its relation on **every** refresh with `enabled = auto_enable_new_groups_*`, which is assertable with no special content. Routing an actually-uncategorised movie into it needs a movie with no `category_id`, which G8's `MovieSpec` cannot express (`categoryId` defaults to `1`). That half is in the addendum with a fallback of leaving it a named gap |
| D11 | **Six defects are asserted correct, marked `test.fail()` with the indicted symbol named in a comment, and filed with `gh issue create --repo D10Scot/Dispatcharr`** | Roadmap rule 5. The explicit `--repo` is mandatory: without it `gh` resolves to the upstream public tracker. Defect 1 is a credential disclosure and should be filed first, and the PR body should say so |
| D12 | **G9 does not touch the four Lua scripts in `vod_proxy`'s stream counter, or the `active_streams` accounting they implement** | They bypass the session metadata lock **on purpose** — a real bug fix for Jellyfin-style range-request churn, pinned by `apps/proxy/vod_proxy/tests/test_vod_lock_contention.py`, and documented in their own header at `multi_worker_connection_manager.py:20-22`. This is stated in the roadmap and repeated in G8's Risks so that G9 inherits the warning rather than rediscovering it under a failing test. Concretely: no G9 test asserts a concurrency property of `active_streams`, no G9 test manipulates a `vod_persistent_connection:*` hash from outside, and no G9 test that fails may be "fixed" by editing those scripts. If a G9 row appears to indict them, that is a finding to escalate, not a patch to write |
| D13 | **No new Playwright project, no CI matrix job, no `scripts/e2e_up.sh` change, and `.github/workflows/e2e-tests.yml` is not edited** | Follows D5 and D6. Keeps G9 clear of the zizmor ratchet entirely. The only `playwright.config.ts` change is one appended comment line on `streaming-greybox` naming the second reason it is serialised — no behavioural change |
| D14 | **`seed.xcAccount` gains VOD overrides rather than a new factory** | `enable_vod` and the two `auto_enable_new_groups_*` flags are ordinary write-only serializer fields. A `seed.vodAccount` would duplicate G8's factory and its "no `credentialQuery` on an XC `server_url`" warning, which is the one mistake that factory exists to prevent |
| D15 | **G9 asserts nothing about image proxying, `VODLogo` fetching, or the unified `/api/vod/all/` view** | `VODLogo` URLs point at whatever the scenario declares; the image proxy has its own unit coverage (`test_vod_image_proxy.py`, `test_vod_logo_proxy.py`); and `UnifiedContentViewSet.list` is a hand-written UNION whose pagination is its own subject. Row-level `stream_icon` → `VODLogo` ingest **is** in scope; fetching the image is not, for the same reason G3 excluded it |

## What G9 needs from G8 that G8 does not have

One addendum, three fields on `MovieSpec`, all additive and all validated at the door in
`parseScenarioRequest`'s existing style (G8's D23). If G8 has already landed, **G9 carries this
itself** as a small `e2e-upstream` change with its own vitest cases — that is test infrastructure,
not product code, and G3's Risks set the precedent for a consumer goal fixing the provider.

| Field | Why | Cost | Fallback if declined |
|---|---|---|---|
| `MovieSpec.isAdult?: boolean` | `get_vod_streams`'s `is_adult` is applied **only when the key is present** (deliberately), and `Movie.is_adult` has no writable API — `MovieViewSet` is `ReadOnlyModelViewSet`. Without it, rows 10 and 16 cannot exist | One optional key emitted into the catalogue entry | Drop row 16 and the positive half of row 10, and record "adult VOD filtering is unobservable end to end" as a `COVERAGE.md` gap. **This is a real loss** — it is the only VOD authorization property in the goal |
| `MovieSpec.categoryId: number \| null` | A `null` means "emit no `category_id`", which is the only way to route a movie to `Uncategorized` through the product's own path | One validator branch plus a conditional key | D10's fallback: assert the `Uncategorized` relation only, and record the routing half as a gap |
| `MovieSpec.vodInfo?: Record<string, unknown>` | Overrides the `info` object of `get_vod_info` for that movie, so a test can declare an advanced payload carrying `bitrate`/`video`/`audio` but no `director`/`actors`/`trailer` — the shape that leaves `Movie.custom_properties` at `None` and exposes defect 2 | A per-movie override merged into the existing default advanced payload | Row 12 becomes "unverifiable at this layer"; the defect is still **filed**, citing `apps/output/views.py:1675` and the reasoning, with a note that no E2E test pins it |

One clarification rather than a change: G8 says "the existing `auth-failure` and `not-found` faults
extend to the XC routes". Rows 15 and 17 need `not-found` to reach the **asset** routes
(`movie/…`, `series/…`), not only `player_api.php`. If G8's implementation scopes it to the API
route, that is a one-line extension of the same fault.

## Project topology

```
bootstrap ──┬─→ seeded             (existing) 4 workers, 30s   +6 spec files
            ├─→ streaming          (existing) 2 workers, 300s  +4 spec files
            └─→ streaming-greybox  (existing) 1 worker,  300s  +1 spec file
```

No new project, no new CI matrix job, no `scripts/e2e_up.sh` or `e2e-tests.yml` change (D13). The
only `playwright.config.ts` edit is an appended comment on `streaming-greybox` recording that a VOD
spec now also depends on its single worker.

## Test inventory

Eighteen tests across eleven files. Twelve assert behaviour; six are `test.fail()` rows pinning
defects. Every test creates its own scenario, its own account and its own generated names, and
scopes every assertion to them (D3).

| # | COVERAGE row | Project | File | Mechanism | Est. |
|---|---|---|---|---|---|
| 1 | Catalogue ingest → `VODCategory`, `Movie`, `Series`, relations | `seeded` | `vod-catalogue-ingest.spec.ts` | XC scenario with two generated movie categories, two named movies (explicit `year`, distinct `containerExtension`), one series category and one series. `seed.xcAccount(scenario, { enable_vod: true })`, `POST refresh-vod`, `waitFor.resource` on `/api/vod/movies/?m3u_account=<id>` for `count === 2`. Assert each movie's `name`, `year`, `genre`, `description`, `logo.url`; then `/api/vod/movies/<pk>/providers/` for `stream_id`, `container_extension`, `category.name` and `custom_properties.basic_data` equal to what was declared. Same for the series via `/api/vod/series/?m3u_account=<id>` | 90s |
| 2 | (same row) categories land with the declared names and types | `seeded` | `vod-catalogue-ingest.spec.ts` | `GET /api/vod/categories/` (unpaginated, global — `find` by generated name, never a length). Assert both movie categories and the series category exist with the right `category_type`, and that each carries an `m3u_accounts` entry for this account with `enabled: true` | 60s |
| 3 | Category gating: `auto_enable_new_groups_vod`, `M3UVODCategoryRelation.enabled` | `seeded` | `vod-category-gating.spec.ts` | D9's arc. Create with `enable_vod: true, auto_enable_new_groups_vod: false`; `refresh-vod`; assert `/api/vod/movies/?m3u_account=<id>` is `count 0` **and** the category exists with `enabled: false` (so the zero is gating, not a failed refresh). `PATCH group-settings` `{category_settings:[{id, enabled:true, custom_properties:{}}]}`; `refresh-vod`; assert the movies appear. Third `refresh-vod`; assert `enabled` is still `true` | 150s |
| 4 | (same row) disabling a category removes its content | `seeded` | `vod-category-gating.spec.ts` | Two categories, one movie each, both enabled. Disable one via `group-settings`; `refresh-vod`; assert that movie is gone from `?m3u_account=` and the other survives — `cleanup_orphaned_vod_content` deleting the stale relation and then the globally orphaned `Movie` | 150s |
| 5 | (same row) the `Uncategorized` fallback | `seeded` | `vod-category-gating.spec.ts` | D10. Assert `Uncategorized` exists for both `movie` and `series` with a relation on this account whose `enabled` matches the account's `auto_enable_new_groups_*`, created by the refresh itself. **With the addendum**, additionally declare a movie with `categoryId: null` and assert it lands in `Uncategorized` | 90s |
| 6 | Episode ingest on demand, object-keyed `episodes` | `seeded` | `vod-episodes.spec.ts` | Series with two seasons declared as `{"1":[…],"2":[…]}`. After ingest, `GET /api/vod/series/<pk>/provider-info/`; assert `episodes_fetched` and `detailed_fetched` are `true`, `episodes` is keyed `"1"`/`"2"`, and each episode carries the declared `title`, `episode_number`, `season_number` and `container_extension`. Cross-check `/api/vod/episodes/?series=<pk>` | 120s |
| 7 | (same row) array-keyed `episodes`, and several streams for one episode | `seeded` | `vod-episodes.spec.ts` | Season list emitted as a JSON array (index becomes the season number, so season `0` is real), and one season declaring two entries with different provider `id`s but the same `episode_num`. Assert **one** `Episode` and **two** `M3UEpisodeRelation`s — `Episode` is unique on `(series, season, episode)` and this is normal provider behaviour, not a duplicate | 120s |
| 8 | Advanced movie data merges without clobbering list-sync fields | `seeded` | `vod-advanced-data.spec.ts` | `GET /api/vod/movies/<pk>/provider-info/`; assert the response carries the advanced payload and the relation now has `custom_properties.detailed_info`, `custom_properties.movie_data`, `detailed_fetched: true` and a non-null `last_advanced_refresh`. Call it again and assert `last_advanced_refresh` is **unchanged** (24h throttle); call it with `?force_refresh=true` and assert it moved. Then `refresh-vod` again and assert `detailed_info` survived the list sync | 120s |
| 9 | XC VOD actions against a real catalogue | `seeded` | `xc-vod-catalogue.spec.ts` | Built-in `request` context with `xcQuery(seed.xcUser())`. `get_vod_categories` contains this test's category with `category_id === String(VODCategory.pk)`; `get_vod_streams` contains both movies with `stream_id === Movie.pk`, `stream_type: "movie"`, the declared `container_extension`, `year`, and `category_id` matching; `get_vod_streams&category_id=<pk>` narrows to one; `get_vod_info&vod_id=<Movie.pk>` returns `info` and `movie_data` for that movie | 90s |
| 10 | (same row) series actions, and `hide_adult_content` on the VOD listing | `seeded` | `xc-vod-catalogue.spec.ts` | `get_series` contains the series with **`series_id === M3USeriesRelation.pk`** (not `Series.pk`); `get_series_info&series_id=<that>` returns `episodes` grouped by season with `id === Episode.pk`. Then, with `MovieSpec.isAdult`, a second XC user with `custom_properties.hide_adult_content: true`: assert the adult movie is absent from `get_vod_streams` and `get_vod_info` for it returns `404`, while the non-adult one is present — the positive control for row 16 | 120s |
| 11 | `vod_proxy`: session mint, path redirect, byte delivery | `streaming` | `vod-stream.spec.ts` | `streamClient.open('/proxy/vod/movie/<Movie.uuid>', { redirect: 'manual' })`; assert `301` and a `Location` ending `/vod_<digits>_<digits>`. Re-open following redirects; assert `200`, `Accept-Ranges: bytes`, a `Content-Length` equal to the asset's, a `Content-Type` matching the declared `container_extension`, and that the first bytes equal the asset's first bytes fetched through `upstream.toControl()`. Assert the provider log records exactly one request for the movie route | 90s |
| 12 | (same row) episode and series entry points | `streaming` | `vod-stream.spec.ts` | `/proxy/vod/episode/<Episode.uuid>` delivers bytes; `/proxy/vod/series/<Series.uuid>` resolves to the **first** episode by `(season, episode)` ordering and delivers the same bytes. Assert the provider was asked for the `series/…` route with the declared episode stream id | 90s |
| 13 | Range and seek | `streaming` | `vod-range.spec.ts` | Establish a session with one full request (so `state.content_length` is known), then a mid-file `Range: bytes=<n>-<n+8191>`: assert `206`, `Content-Range: bytes <n>-<n+8191>/<full>`, `Content-Length: 8192`, and that the 8 192 bytes are **byte-identical** to the same range fetched direct from the provider (D8). Then an open-ended `Range: bytes=<n>-` and assert `Content-Range` ends at `<full>-1` | 120s |
| 14 | Root XC playback routes | `streaming` | `xc-vod-playback.spec.ts` | `GET /movie/<user>/<pass>/<Movie.pk>.mp4` delivers bytes through the same session-mint path; a wrong password returns `401`; an unknown username returns `404`; an unknown movie id returns `404`. Same for `/series/<user>/<pass>/<Episode.pk>.mp4` on the happy path | 120s |
| **15** | **Known bug (defect 1):** an upstream error echoes the provider password to an unauthenticated client | `streaming` | `vod-upstream-error.spec.ts` | Arm `not-found` on the asset routes; open `/proxy/vod/movie/<uuid>`. Assert the response body does **not** contain the account password and the status is not `500`. `test.fail()` — today it is `500 "Streaming error: 404 Client Error: … for url: http://…/movie/<user>/<password>/<id>.mp4"` (`multi_worker_connection_manager.py:1405`) | 90s |
| **16** | **Known bug (defect 4):** an adult movie is unlistable but streamable | `streaming` | `vod-adult-streamable.spec.ts` | An adult movie and an XC user with `hide_adult_content: true`. Assert it is absent from `get_vod_streams` **and** that `/movie/<user>/<pass>/<Movie.pk>.mp4` refuses. `test.fail()` — `stream_xc_movie` applies no `is_adult` filter, and neither does `stream_vod`. The VOD analogue of G5's defect 2, on different functions, so a separate issue | 120s |
| **17** | **Known bug (defect 3):** an unsatisfiable Range on a fresh session is `500`, not `416` | `streaming` | `vod-range.spec.ts` | First request of a new session carries `Range: bytes=<beyond EOF>-`. Assert `416`. `test.fail()` — `state.content_length` is unset on `request_count == 1`, so `_validate_range_header` is skipped, the provider's `416` reaches `raise_for_status()`, and the client gets a `500` (which also leaks the URL, per defect 1 — this test asserts the status, row 15 asserts the body) | 90s |
| **18** | **Known bug (defect 6):** a `range-unsupported` provider yields a lying `206` | `streaming` | `vod-range.spec.ts` | Arm `range-unsupported`; establish a session; request a mid-file range. Assert the returned bytes equal that range of the asset. `test.fail()` — Dispatcharr sets `206`, a `Content-Range` and a shortened `Content-Length` from the *request*, while the body is the whole file from offset zero | 120s |
| **19** | **Known bug (defect 5):** `/api/vod/categories/?m3u_account=<id>` is a `500` | `seeded` | `vod-catalogue-ingest.spec.ts` | Assert the filter returns `200` and only this account's categories. `test.fail()` — `apps/vod/api_views.py:624` declares `field_name="m3u_account__id"` on a model with no such relation, so the query raises `FieldError`. Executed against `dispatcharr-testrunner` this session: `Cannot resolve keyword 'm3u_account' into field. Choices are: category_type, created_at, id, m3u_relations, m3umovierelation, m3useriesrelation, name, updated_at` | 20s |
| **20** | **Known bug (defect 2):** `get_vod_info` drops advanced data when `Movie.custom_properties` is empty | `seeded` | `xc-vod-catalogue.spec.ts` | **Requires the `vodInfo` addendum.** Declare a movie whose advanced payload carries `bitrate`/`video`/`audio` and none of trailer/director/actors/backdrop. Drive `/api/vod/movies/<pk>/provider-info/` (which returns them) and XC `get_vod_info` (which does not). Assert both agree. `test.fail()` — `apps/output/views.py:1675` gates the whole `detailed_info` merge on `if movie.custom_properties:`, while reading the data off the *relation* one line later | 60s |
| **21** | Redirect mode: the client is sent at the provider and no bytes traverse Dispatcharr | `streaming-greybox` | `vod-redirect-profile.spec.ts` | Read the current `default_stream_profile` from `CoreSettings`, set it to the locked Redirect profile, and restore it in `finally`. `streamClient.open('/proxy/vod/movie/<uuid>', { redirect: 'manual' })`; assert **`302`** — `HttpResponseRedirect`, unlike the session-mint path's hand-built `301`, so the status alone distinguishes "sent at the provider" from "sent to your own session URL" — plus a `Location` that `upstream.toControl()` accepts, and `upstream.connections(scenario).live === 0`. The spec header must state that it mutates a global row and why that needs `workers: 1` | 120s |

Rows 15–20 are six `test.fail()`s, which is a lot for one goal. Each must carry the indicted symbol
in a comment and a filed issue number; G5's Risks say why, and it applies here with more force
because two of the six are security findings.

**Reconciliation with `e2e/COVERAGE.md`.** The eleven existing G9 rows are all addressed. Rows 15,
16, 17, 18, 19 and 20 have **no row today**: G9 adds six, status `known-bug`, each carrying its
issue link, in the same PR as the tests (rule 3). The existing "Characterization: `Client.authenticate()`
checks only `user_info`" row is **not** implemented as a test and is re-labelled with its reason —
see Non-goals.

## Fixture additions

Additive, at the end of each existing list.

- **`streamClient.readBytes(n): Promise<Buffer>`** (`e2e/fixtures/stream-client.ts`) — the exact
  `readPackets` loop without the 188-byte multiplier, over the existing private `takeBytes`. VOD is
  not MPEG-TS and `readPackets` is the wrong tool for it. **G8's byte-read proof needs this too**;
  if G8 has landed it, G9 uses it unchanged and this bullet is dropped.
- **`M3uAccountOverrides`** gains `enable_vod`, `auto_enable_new_groups_vod`,
  `auto_enable_new_groups_series` (`e2e/fixtures/types.ts`), each with
  `apps/m3u/serializers.py`'s write-only declaration named in a comment, per that file's convention.
- **`Movie`, `Series`, `Episode`, `VodCategory`, `M3uMovieRelation`, `M3uSeriesRelation`,
  `M3uEpisodeRelation`** types (`e2e/fixtures/types.ts`), each naming the serializer it came from.
  All three relation serializers use `fields = '__all__'`, so the types are the model fields.
- **`e2e/README.md`** — a short "VOD" section stating: `refresh-vod` is the trigger (D2); movie,
  series and **category** names must be generated (D3); `GET /api/vod/categories/` is unpaginated
  *and writes rows for every worker's XC accounts*; and D12's Lua warning in one sentence, where
  someone debugging a VOD test will read it.

No new `Seeder` method, no new `Waiter` method, and nothing registered on `test.extend`.

## Candidate product defects

Six, all found while writing this spec, none in `CLAUDE.md`'s catalogue. Filed as issues by the
implementing PR with an explicit `--repo D10Scot/Dispatcharr` (D11), never patched.

1. **Provider credentials disclosed to an unauthenticated client.** *Verified by reading.* Any
   upstream failure during a VOD stream becomes
   `HttpResponse(f"Streaming error: {str(e)}", status=500)`
   (`apps/proxy/vod_proxy/multi_worker_connection_manager.py:1405`, and the same shape at
   `apps/proxy/vod_proxy/views.py:845`). `requests`' `raise_for_status()` message ends
   `for url: <url>`, and the XC VOD URL is
   `{server}/movie/{username}/{password}/{id}.{ext}`. `stream_vod` is `AllowAny` and the `STREAMS`
   ACL defaults to `0.0.0.0/0`. Related, and in the same family as CLAUDE.md's existing INFO-log
   findings: `views.py:811` logs the same URL at INFO, and `views.py:630` logs the entire client
   header dict — including `Authorization` — at INFO. **File this one first.**
2. **`get_vod_info` silently drops all advanced data when `Movie.custom_properties` is empty.**
   *Verified by reading.* `apps/output/views.py:1675` gates the merge on `if movie.custom_properties:`
   and then reads `movie_relation.custom_properties['detailed_info']` inside it — the wrong object's
   truthiness. A movie whose provider payload carries none of trailer/director/actors/release_date
   has `custom_properties = None` (`clean_custom_properties({})` returns `None`), so `bitrate`,
   `video`, `audio`, `cover_big` and the `plot` override never reach an XC client even though
   `refresh_movie_advanced_data` just fetched and stored them. The commented-out line 1679 shows the
   intended source.
3. **An unsatisfiable Range on a session's first request is `500`, not `416`.** *Verified by
   reading.* `get_stream` sets `state.content_length` only when `request_count == 1`, so
   `_validate_range_header` is a no-op on that request; the provider's `416` then hits
   `raise_for_status()`. The same request on an established session returns a correct `416`.
4. **An adult movie is unlistable but streamable.** *Verified by reading.* `xc_get_vod_streams` and
   `xc_get_vod_info` filter `movie__is_adult=False` for a `hide_adult_content` user;
   `stream_xc_movie`, `stream_xc_episode` and `stream_vod` apply no adult filter at all. The VOD
   analogue of G5's defect 2, on different functions with a different fix, so a separate issue —
   G5's D11 sets the precedent for splitting these.
5. **`GET /api/vod/categories/?m3u_account=<id>` returns `500`.** *Verified by execution.*
   `apps/vod/api_views.py:624` declares `m3u_account = NumberFilter(field_name="m3u_account__id")`,
   but `VODCategory` has no such relation — the reverse accessor is `m3u_relations`. Run against
   `dispatcharr-testrunner`: `FieldError: Cannot resolve keyword 'm3u_account' into field`. The
   filter is declared in `Meta.fields` too, which is why it imports cleanly and fails only at query
   time. The frontend calls the endpoint without the filter, so nothing has hit it.
6. **A `range-unsupported` provider produces a `206` whose headers contradict its body.** *Verified
   by reading.* `stream_content_with_session` sets `206`, `Content-Range` and a shortened
   `Content-Length` from the client's *request* whenever a `Range` header was present, regardless of
   what the provider returned; a provider that ignores `Range` sends the whole file from offset
   zero. G8's D15 anticipated this as "a G9 assertion"; the sharper finding is that
   `Content-Length` is wrong too, so a conforming client truncates mid-file.

**Suspected, not verified, and deliberately not tested** (recorded so the next reader does not
re-derive them):

- `M3UAccountViewSet.create` runs `refresh_categories(account_id)` with no `try`, so an XC create
  with `enable_vod: true` against an erroring provider returns `500` **after** committing the
  account row. Reachable by arming `auth-failure` before the create — but the test would have to
  own the create rather than use `seed.xcAccount`, and the failure mode is a partially-created
  account that then poisons the rest of the spec. Recorded, not tested.
- `M3UAccountViewSet.update` reads `instance.custom_properties` from the pre-`super().update()`
  instance, so a single PATCH carrying both `enable_vod: true` and
  `auto_enable_new_groups_vod: false` creates the `Uncategorized` relations with the *old* flag.
  Small, and it self-corrects on the next refresh.
- `xc_get_series_info` does `M3USeriesRelation.objects.get(id=series_id, …)`, which raises
  `ValueError` rather than `Http404` for a non-numeric `series_id`. G5 owns the shape of that
  endpoint's error contract; G9 does not open it.
- `stream_xc_episode` catches `M3UEpisodeRelation.DoesNotExist` after a `.first()` that never
  raises it (`views.py:1450-1454`), so an unknown episode id is an `AttributeError` → `500`, where
  `stream_xc_movie` correctly returns `404`. Verified by reading; **folded into row 14's assertions
  rather than given its own `test.fail()`**, because six is already too many and the fix is one
  guard clause that row 14 will go green on.

## Non-goals

Each is recorded as a note in `e2e/COVERAGE.md`, never as silence.

- **The four Lua scripts and `active_streams` concurrency** (D12). Not touched, not asserted, not
  "fixed" under a failing test.
- **The `xc-auth-envelope` characterization.** The existing `COVERAGE.md` row says G9 decides
  whether to file it. **G9 does not**: `Client.authenticate()` ignoring `auth`/`status` is a
  *provider-compatibility* property of XC ingest, not of VOD, and the honest home for it is
  whichever goal owns XC account authentication — which is G3's and G8's territory, not G9's. G9
  re-labels the row with that reasoning and leaves it `todo`. Filing an issue for a behaviour no
  test pins produces an issue nobody can verify closed (G8's D25).
- **Multi-provider VOD selection and priority ordering.** `_order_candidates` and
  `_xc_fetch_priority_distinct_relations` both exist and both are real, but proving them needs two
  accounts deliberately sharing one `Movie` row — the exact aliasing hazard D3 forbids everywhere
  else, and a test that would be indistinguishable from a cross-worker collision when it failed.
  Named gap.
- **Pre-stream failover between providers.** `_select_vod_stream` never connects, so there is
  nothing to fail over *from* except a capacity rejection. Proving it needs the two-account setup
  above.
- **Seek *semantics*.** G9 proves the requested byte range comes back; it does not prove a player
  can decode from that offset. That is a container question, not a proxy question.
- **`head_vod`.** Not routed (`apps/proxy/vod_proxy/urls.py`). Dead code stays dead; G9 records it
  rather than adding a route to test.
- **`vod_stats` and `stop_vod_client`.** Admin-only observability endpoints. `stop_vod_client`'s
  stop-signal path is checked every 100 chunks and would need a long stream to observe. Named gap.
- **VOD image and logo proxying, and `/api/vod/all/`** (D15). Row-level `stream_icon` → `VODLogo`
  ingest is in scope; fetching or proxying the image is not.
- **`batch_refresh_series_episodes`.** Reachable only through a task with no endpoint, and its
  24-hour cutoff makes it unobservable inside a test run.
- **Any product change.** Assert correct, `test.fail()`, file with `--repo D10Scot/Dispatcharr`.

## Risks

- **`Movie`, `Series` and `VODCategory` are shared rows across four parallel workers, and G9 is the
  goal that creates them.** G8's D7 warns; G9 is where it bites. Worse than G8's case: a
  category name collision means two workers share a `VODCategory`, and `batch_create_categories`
  deletes a category once its last relation goes. Mitigation: D3, enforced by convention plus the
  README section, and no assertion that is not scoped by `?m3u_account=` **and** a generated name.
- **`GET /api/vod/categories/` writes rows.** `VODCategoryViewSet.list` `get_or_create`s
  `Uncategorized` relations for *every* active XC account with `enable_vod` on the instance —
  including other workers'. Rows 2 and 5 both call it. Consequence, stated because it would
  otherwise be discovered as a flake: **no G9 test may assert that an account lacks an
  `Uncategorized` relation**, because any other worker's category listing creates one.
- **An XC account create blocks on two synchronous provider round-trips**
  (`refresh_m3u_groups` and, with `enable_vod`, `refresh_categories`), inside the request. Every
  `seeded` row therefore needs `test.setTimeout()` (D4), and a provider fault armed before a create
  turns the create itself into the failure — which is why row 15's fault is armed *after* the
  account exists.
- **Row 21 mutates a global `CoreSettings` row.** `streaming-greybox`'s single worker makes it safe
  within the project, and the restore is in a `finally` — but a crashed run leaves the instance's
  default Stream Profile on Redirect, which breaks every subsequent live-streaming test in that
  container until it is reset. The spec header must say so, and the restore must not be conditional
  on any assertion passing.
- **Six `test.fail()` rows.** Each is a claim that the product is wrong. Two are security findings.
  A `test.fail()` without the indicted symbol in a comment and a filed issue number is
  indistinguishable from a test somebody gave up on.
- **The addendum is a dependency, not a nice-to-have.** Without `MovieSpec.isAdult` there is no
  adult-VOD row at all, and rows 10 and 16 vanish. It should be agreed before implementation
  planning, not discovered during it.
- **`refresh_vod_content` swallows everything.** Its outer `except Exception` logs a traceback and
  returns a string; nothing is written to the account row. A refresh that fails for a reason G9 did
  not anticipate looks exactly like a refresh that found nothing — a `waitFor.resource` timeout
  reporting `count: 0`. Mitigation: every gating row asserts the *category's* state alongside the
  zero (row 3), so "gated" and "broken" are distinguishable in the failure message.
- **`assets/vod.mp4`'s size and `Content-Type` are load-bearing for rows 11, 13 and 18**, and G9
  learns both from `e2e-upstream/README.md` rather than from `src/` — which is G8's stated
  definition of done. If that documentation is missing, the first G9 task is to add it, not to read
  the source.
