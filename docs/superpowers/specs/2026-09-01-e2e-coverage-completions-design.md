# G14 — Coverage Completions

**Date:** 2026-09-01
**Revised:** 2026-09-01, after G11 landed (`45a33a4a`)
**Status:** Draft, ready for review
**Wave:** 6 (**G11 has landed**; G12, G13 and G15 run beside this one on deliberately disjoint files)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Goal definition:** `2026-09-01-e2e-programme-review-disposition.md`, "G14 — Coverage completions"
**Verified at:** `origin/main` `45a33a4a` (`docs: record two traps that cost time this session`,
#126), which is G11's merge state — PR #123 (guards, ADRs, full-run CI) and PR #124 (every test
tagged, tag guard blocking). Cited by `file:symbol` throughout — line numbers in this repo drift
and an earlier spec in this series shipped four wrong ones.

The revision replaces every hedge about G11's mechanisms with the mechanism as it shipped, cuts
test 9 (a design error: it lands in the ML band D6 forbids — see D6 and D13), names the guards
G14 must satisfy, and states which of G14's rows the relay extraction actually depends on.

## Siblings in flight

Wave 6 is four goals in parallel, and the disposition made the file split part of the definition.
G14's side of it:

| Goal | Owns | G14's discipline |
|---|---|---|
| **G13** | `e2e/tests/frontend/dvr.spec.ts`, `run_recording`, the DVR WebSocket events | G14 touches no DVR file and asserts no `recording_*` event, even though they are the largest family in the product's WebSocket vocabulary. See D12 |
| **G12** | `e2e/tests/lifecycle/**`, `durable-state.ts`, backup restore, non-zero `refresh_interval`, the two bash suites | G14 opens nothing under `tests/lifecycle/`, edits no workflow, and holds every source it creates at `refresh_interval: 0` (G3's D10, still binding). G14 *hands* G12 one new row — the global-`CoreSettings` behavioural settings it cannot safely test on a shared instance (D10) |
| **G15** | pre-G9 `test.fail()` premise guards, `stats`/`guide`/`backups` interactions, `xc-output.spec.ts`, the failover specs, the `e2e-upstream` contract doc, the `api-fixture`/`authorization` status-only audit | **G14 does not open `e2e/tests/seeded/xc-output.spec.ts`**, even though that file's `RULING R10` header is the exact hole G14 closes. G14 adds its own COVERAGE rows and cross-references G5's rather than rewriting them. See D16 |
| **G11** | the `@contract`/`@characterization` taxonomy and `docs/adr/0002-e2e-test-taxonomy.md`; the `guards` project (`e2e/tests/guards/`) and `docs/adr/0003-e2e-frontend-and-shared-state-contract.md`; the run-everything CI mode | **Landed** at `45a33a4a`. G14 applies the taxonomy and satisfies the guards; it defines neither. See D13 for the tags and D13a for the guards |

Shared files G14 edits, all additively and all also reachable by a sibling:
`e2e/COVERAGE.md`, `e2e/README.md`, `e2e/fixtures/types.ts`, `e2e/fixtures/index.ts`,
`e2e/fixtures/api.ts` (one method signature, D15), `e2e/tests/guards/allowlist.ts` (one entry on
`GLOBAL_SETTINGS_WRITE`, D13a). **G14 does not edit `e2e/fixtures/seed.ts`,
`e2e/playwright.config.ts`, `e2e/package.json`, `scripts/e2e_up.sh` or any file under
`.github/workflows/`** — which keeps it clear of every matrix edit and arms the zizmor hook zero
times.

## Goal

Close the seven accepted coverage gaps the 2026-09-01 review left, **without buying a new
Playwright project, a new CI job, or an isolated instance for any of them.**

That last clause is the design, not a caveat. The disposition's own text assumes the ACL 403
negatives need an isolated instance, and the ledger assumes the same for anything settings-shaped.
Read against the code, neither is true, and the mechanism that replaces both is cheaper *and*
stronger: `dispatcharr/utils.py:get_client_ip` honours a client-supplied `X-Real-IP` whenever the
peer is inside the trusted set, and `dispatcharr/utils.py:network_access_allowed` defaults the
`M3U_EPG` scope to local addresses only. **A blocked-network 403 is therefore reachable on the
shared `seeded` instance by moving the apparent client IP, with no settings write at all** — and
`network_access_allowed`'s per-user branch (`user.custom_properties["allowed_networks"]`) gives
the same lever, row-scoped, for the scopes whose defaults are permissive.

So G14's shape is: **every write is row-scoped, every assertion is filtered, everything runs in
`seeded`, and one test appends to the file G6 already built for the plugin hazard.**

## Ranking, and what gets cut

The brief's own warning is that seven sub-areas in one goal is the shape that sprawls. The
ranking below is the answer, and the cut list is binding: work is dropped from the bottom, in
order, and each drop becomes a `COVERAGE.md` row naming the mechanism and the cost — never
silence.

| Rank | Sub-area | Why here | Ships as |
|---|---|---|---|
| **1** | **Blocked-network ACL 403 negatives** (#2) | Closes a hole the ledger names in G5's own row, finds a verified product defect, and turns out to be nearly free. The one sub-area whose absence is written down as a coverage hole rather than inferred | `network-acl.spec.ts`, 5 tests |
| **2** | **EPG matching / `set-*-from-epg`** (#1) | The largest deliberate gap in the ledger (G3's gap row names all five endpoints). `apps/channels/epg_matching.py` is 927 lines with no end-to-end coverage at all, and it is the highest-value migration-gate target in the goal | `epg-matching.spec.ts` (4) + `epg-field-copy.spec.ts` (3) |
| **3** | **Product WebSocket events** (#7) | Cheap, because most of it rides on rank 2 — `single_channel_epg_match`, `epg_match` and the `epg_*_setting_progress` families are emitted by calls those tests are making anyway, and the `set-*-from-epg` tasks carry the Celery `task_id` the POST returned, the first exactly-unique correlation this suite has had. Two tests earn their own file: the cheapest correlated product event in the application (`epg_data_created`), and the **admin-only filter**, which is an authorization property with zero coverage anywhere | `ws-product-events.spec.ts` (2), plus assertions inside rank 2's two files |
| **4** | **M3U filters** (half of #6) | Row-scoped, deterministic, no ML, no streaming. Closes `M3UFilterViewSet`, which G3 named in its Non-goals | `m3u-filters.spec.ts`, 3 tests |
| **5** | **Channel bulk operations and reordering** (#5) | Cheap, but the reorder endpoint shifts channel numbers **instance-wide**, so only a worker-scoped band of it is expressible. Value is real but bounded | `channel-bulk-ops.spec.ts`, 5 tests |
| **6** | **Plugin run** (half of #4) | The `run` half is one API call against G6's existing fixture plugin. The *task-fires* half needs a plugin that dispatches a product Celery task, which is the riskiest thing in the goal — it makes the fixture plugin non-inert | 1 test appended to `tests/frontend/plugins.spec.ts` |
| **7** | **Settings with behavioural effect** (#3) | Largely **discharged by ranks 1 and 4**: read against the code, the settings with behavioural effect split into row-scoped ones — the per-user `allowed_networks` ACL and `M3UFilter`, both of which ship — and global `CoreSettings` groups, which this goal has decided not to touch (D2, D10). The one row-scoped setting left over, the M3U account profile's URL rewriting, is a `streaming` test and is cut for that reason (D11), not for being global | A decision and three `COVERAGE.md` rows, not tests |

**Cut list, in cut order.** Anything below the line the goal actually reaches is dropped:

1. **`ServerGroup` credential pooling** — cut before starting. Proving it needs two M3U accounts
   sharing one credential, in one group, at `max_streams: 1`, and two concurrent real streams;
   that is a `streaming`-project test with a two-account concurrency setup, the most expensive row
   in the goal by a wide margin. Recorded as a gap with the mechanism (D11).
2. **`M3UAccountProfile.search_pattern`/`replace_pattern` URL rewriting** — cut before starting.
   It *is* observable (`apps/proxy/live_proxy/url_utils.py:transform_url` rewrites the upstream URL
   at stream time and the fake provider logs the path it was asked for), but it is a `streaming`
   test, and G14 is deliberately an API-level goal. Recorded as a gap naming the exact observable
   (D11).
3. **Plugin "task-fires"** (rank 6's second half).
4. **Channel `reorder`** (test 23).
5. **`m3u-filters.spec.ts`'s `order` test** (test 18).

**Test 9 — removed.** It is not on the cut list, because it cannot be built at all: it required a
pair scoring in `[75, 80)` on the *bulk* path, and on that path `FUZZY_MEDIUM_CONFIDENCE` is 70,
so `try_epg_name_match` reaches `get_sentence_transformer()` for every score in that range. It
violated D6 by construction. The threshold asymmetry it was going to pin is recorded as a
`COVERAGE.md` observation instead. Test numbers are otherwise unchanged.

Ranks 1–3 are must-ship. If ranks 1–3 alone land, G14 has closed the two gaps the ledger actually
names and has done so with no new infrastructure; that is a legitimate outcome, and the roadmap's
"resist widening scope" clause is what makes it one.

## Migration relevance, stated honestly

The programme exists to make the E2E suite a trustworthy gate for the relay extraction
(`CLAUDE.md`: control/data-plane split, Phase 1 the boundary). Not every G14 row serves that. Two
do; the rest are regression coverage of the control plane, which is worth having and is not the
same thing.

**Gate-relevant.**

- **Rank 1, the network ACL.** `dispatcharr/utils.py:network_access_allowed` is one function, and
  the same function gates the endpoint the extraction moves:
  `apps/proxy/live_proxy/views.py:stream_ts` calls it as `network_access_allowed(request,
  "STREAMS")` before anything else. G14 proves that function's behaviour on `M3U_EPG` and `XC_API`,
  which are the cheap scopes; a relay that reimplements or drops the check on `STREAMS` breaks a
  property these tests describe even though they do not assert it on that route. Test 1 is the
  honest caveat and is why it is `@characterization`: it pins the `X-Real-IP` trust of **this**
  nginx/uwsgi topology, and a relay serving its own socket is exactly the change that invalidates
  it. Reading it as a red `@characterization` on a `migration/*` branch is the intended outcome.
- **Test 15, the WebSocket admin-only filter.** `channel_stats` is emitted from the relay side —
  `apps/proxy/tasks.py:fetch_channel_stats` and inline from `GET /proxy/ts/status` — and
  `dispatcharr/consumers.py:ADMIN_ONLY_UPDATE_TYPES` drops it silently for a non-admin socket. When
  the relay becomes a separate process, whatever replaces that emitter must still land on a
  consumer that applies the same filter. A silent drop that stops being applied is invisible; this
  is the only test in the suite that would notice.

**Regression coverage of the control plane, not gate coverage.** EPG matching (ranks 2 and 3), the
`set-*-from-epg` field copy, M3U filters, channel bulk operations and plugin `run` are Django-side
behaviour the extraction does not touch. `apps/channels/epg_matching.py` has zero end-to-end
coverage today and 927 lines of it, so the tests are worth writing — but they will pass unchanged
across the extraction, and a green run of them says nothing about whether the relay moved
correctly.

**Where to stop if wave 6 runs long: ranks 4 to 6.** That is the honest line, and the cut list
already encodes it — `ServerGroup` pooling, `M3UAccountProfile` rewriting, plugin task-fires,
`reorder` and the `order` filter test are all at or below it. Ranks 1 to 3 are the must-ship set
for the same reason: rank 1 is gate-relevant, rank 2 closes the largest recorded gap in the ledger,
and rank 3 rides on rank 2 and carries test 15.

## Current state

Every G14 sub-area is either an explicit `todo` row in `e2e/COVERAGE.md`, a named non-goal in a
prior spec, or a demonstrated absence. Each is traced here so no claim is inferred:

| Sub-area | Where the gap is recorded |
|---|---|
| EPG fuzzy matching, `set-names-from-epg`, `set-logos-from-epg`, `set-tvg-ids-from-epg`, `get_preferred_region_code()` | `COVERAGE.md`, `Sources \| Deliberate G3 gaps: …` (`todo`), which names all five by symbol; and `2026-08-29-e2e-content-sources-ingest-design.md`, Non-goals, first two bullets. **The backend suite does not compensate**, and that is an enumeration rather than an inference: `match_channels_to_epg`, `run_single_channel_epg_match`, `try_epg_name_match`, `_compute_fuzzy_score`, `_fuzzy_scan_core`, `build_epg_matching_catalog`, `lookup_epg_by_tvg_id`, `get_preferred_region_code`, all five Celery tasks and all five endpoints have zero test references anywhere in the tree |
| ACL 403 negatives | `COVERAGE.md`, `Output \| Xtream get.php and xmltv.php at the site root — playlist/guide shape and the 401 half of bad-credential rejection; **the 403 (blocked-network) half is untested**`; and `e2e/tests/seeded/xc-output.spec.ts`'s `RULING R10` header |
| Settings with behavioural effect | `COVERAGE.md`, `Frontend \| Settings: change and persist` is `done` for a **User-Agent row created through the UI** only; `e2e/tests/seeded/settings.spec.ts`'s own header states a global `CoreSettings` change was unavailable to it |
| Plugin lifecycle | `COVERAGE.md`, `Frontend \| Plugins: list, enable, configure` is `done`; `run` is not in that row, `e2e/tests/frontend/plugins.spec.ts` never calls `/run/`, and `buildPluginZip` (`e2e/tests/frontend/plugin-zip.ts`) hardcodes `actions: []` |
| Bulk ops and reordering | Demonstrated absence: `grep -rn bulk e2e/tests` returns `from-stream/bulk/` (G3) and `profiles/<id>/channels/bulk-update/` (G3) only. No test touches `channels/edit/bulk`, `channels/bulk-delete/`, `channels/assign/` or `channels/<id>/reorder/` |
| M3U filters, profiles, server groups | `2026-08-29-e2e-content-sources-ingest-design.md`, Non-goals: "**`M3UFilterViewSet`** … are out". No test references `M3UAccountProfile` or `ServerGroup` |
| Product WebSocket events | `COVERAGE.md`'s `Harness \| WebSocket queue semantics and event correlation` is `done` for the *fixture*. `e2e/tests/seeded/ws-fixture.spec.ts`'s own header says all three tests exist to pin the fixture's queue semantics, and `playlist_created` is the only product event any test has ever named |

## Verified facts this design rests on

Read out of the tree at `cf95410e` when first written, and re-checked at `45a33a4a` for the
revision (`git diff cf95410e 45a33a4a -- apps/ core/ dispatcharr/ frontend/` touches none of the
symbols cited here; the rows that changed are the harness rows, which the revision rewrote). Cited
by symbol.

### Network access control

| Fact | Source | Consequence |
|---|---|---|
| `get_client_ip` returns `REMOTE_ADDR` **unless** that peer is inside the trusted set; when it is, `HTTP_X_REAL_IP` wins, else the right-most non-trusted hop of `HTTP_X_FORWARDED_FOR` | `dispatcharr/utils.py:get_client_ip` | A client can move its own apparent IP **iff** the peer is trusted. This is the whole mechanism. See D3 and its probe |
| With `DISPATCHARR_TRUSTED_PROXIES` unset, the trusted set is `LOCAL_NETWORK_CIDRS` (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `::1/128`, `fc00::/7`, `fe80::/10`) | `dispatcharr/utils.py:_trusted_proxy_networks`, `LOCAL_NETWORK_CIDRS` | `scripts/e2e_up.sh` sets only `DISPATCHARR_ENV` and `DISPATCHARR_LOG_LEVEL`, so the e2e container runs on the default. A published-port request reaches nginx from the Docker bridge, which is inside `172.16.0.0/12` |
| `docker/nginx.conf` serves Django through `uwsgi_pass` with a bare `include uwsgi_params`, sets the `X-Forwarded-*` family with `proxy_set_header` (which does not apply to a `uwsgi_pass` upstream), and sets **no** `uwsgi_param` for any forwarded header, and no `uwsgi_pass_request_headers off` | `docker/nginx.conf`; [#81](https://github.com/D10Scot/Dispatcharr/issues/81), which states the pass-through consequence in its own "second-order concern" | nginx neither sets nor strips these headers on the Django routes: whatever the client sends arrives. #81 is filed as a defect; G14 **uses** it as a lever and says so |
| `network_access_allowed` defaults `M3U_EPG` to `LOCAL_NETWORK_CIDRS` and every other scope to `0.0.0.0/0` + `::/0` | `dispatcharr/utils.py:network_access_allowed` | **`/output/m3u`, `/output/epg` and the HDHR endpoints deny a non-local address on a fresh instance with no configuration.** A 403 negative there costs zero writes |
| The `network_access` `CoreSettings` row ships with `value = {}`, and `CoreSettings.get_network_access_settings` is `_get_group(NETWORK_ACCESS_KEY, {})`, so an absent key and an absent row behave identically | `core/migrations/0013_default_network_access_settings.py`, `core/migrations/0020_change_coresettings_value_to_jsonfield.py`; `core/models.py:CoreSettings.get_network_access_settings` | The built-in defaults above are what is actually in force on the e2e container. No test has to arrange them |
| Four scopes exist — `M3U_EPG`, `STREAMS`, `XC_API`, `UI` — and **no backend constant enumerates them**; `network_access_allowed` accepts any string and an unknown key silently gets the defaults. The canonical list is frontend-only | `frontend/src/constants.js:NETWORK_ACCESS_OPTIONS`; every `network_access_allowed(` call site | HDHR shares `M3U_EPG` (`apps/hdhr/api_views.py:_hdhr_network_check`); there is no `HDHR` scope |
| **`UI` gates the entire REST API.** `apps/accounts/permissions.py:Authenticated` calls `network_access_allowed(request, "UI", user)`, and `IsAdmin`/`IsStandardUser` subclass it; `IsAdmin` is `DEFAULT_PERMISSION_CLASSES` | `apps/accounts/permissions.py`; `dispatcharr/settings.py` | Narrowing `UI` bricks the instance: the settings write, `/api/accounts/token/` and `/api/accounts/token/refresh/` all 403, and recovery is `manage.py reset_network_access` over `docker exec` only. **G14 never writes `UI`.** See D2 |
| **There is no server-side self-lockout guard.** `core/serializers.py:CoreSettingsSerializer.update` validates CIDR *syntax* only and never looks at the requester's IP; `create()` is unvalidated entirely | `core/serializers.py:CoreSettingsSerializer.update` | The guard is client-side and advisory: `frontend/src/components/forms/settings/NetworkAccessForm.jsx:onNetworkAccessSubmit` calls `check/` and warns only about `UI` |
| `POST /api/core/settings/check/` is a dry run that never writes, and returns `{...perScopeExcludedCidrs, "client_ip": "<what the server thinks you are>"}`. Its permission falls through to `Authenticated` | `core/api_views.py:CoreSettingsViewSet.check` | **This is the premise guard.** A test can ask the server what IP it sees, with and without the spoofed header, and assert the mechanism *before* asserting the 403 — the G9/G10 premise-guard pattern G15 is backporting |
| `network_access_allowed`'s per-user branch reads `user.custom_properties["allowed_networks"][<scope>]` as a comma-separated string; **when non-empty it is authoritative** — the user must match one of *those* CIDRs or the call returns `False`, even after the global check passed | `dispatcharr/utils.py:network_access_allowed` | A row-scoped denial lever needing no global write and no header spoofing: point a seeded user's `allowed_networks` at a CIDR that cannot contain any real client. See D4 |
| `apps/output/views.py:xc_get_user` applies `network_access_allowed(request, 'XC_API', user)` and returns **`None`** on denial. Every caller maps `None` to `401 {"error": "Unauthorized"}` | `apps/output/views.py:xc_get_user`, `:xc_get_info`, `:xc_player_api` | **A network-denied XC client is told its password is wrong.** New defect; see D5 |
| `xc_get`/`xc_xmltv` each run their own `network_access_allowed(request, 'XC_API')` — **with no `user`** — before calling `xc_get_user`, and return `403 {"error": "Forbidden"}` from it | `apps/output/views.py:xc_get`, `:xc_xmltv` | Only the *global* scope can 403 on `get.php`/`xmltv.php`. `player_api.php` and `panel_api.php` have no direct ACL check at all — their only enforcement is the one inside `xc_get_user`, which always yields 401 |
| `apps/proxy/live_proxy/views.py:stream_xc` does it correctly: ACL (with `user`) → `403 {"error": "Forbidden"}`, then credentials → `401 {"error": "Invalid credentials"}`. `apps/timeshift/views.py:_timeshift_proxy_impl` is a third shape — `HttpResponseForbidden` plain text for *both*, credentials first | those two symbols | Three call sites, three different contracts for the same two conditions. The defect report names all three |
| `network_access_allowed`'s global loop does `network_access[key].split(",")` and `ipaddress.ip_network(cidr)` with no guard; the per-user loop wraps the same call in `try/except ValueError: continue` | `dispatcharr/utils.py:network_access_allowed` | A scope stored as a list, or as `""`, is a **500 on every gated request**. G14 does not provoke this — it is a global-row mutation whose blast radius is the whole instance. Recorded as an observation, not tested |

### EPG matching

| Fact | Source | Consequence |
|---|---|---|
| `POST /api/channels/channels/match-epg/` with `{"channel_ids": [...]}` dispatches `match_selected_channels_epg`; **with the list omitted or empty it dispatches `match_epg_channels`, which matches every EPG-less channel on the instance.** Both return `202` | `apps/channels/api_views.py:ChannelViewSet.match_epg` | Every G14 call passes `channel_ids`. The bare form is forbidden on a shared instance. See D7 |
| `POST /api/channels/channels/<pk>/match-epg/` dispatches `match_single_channel_epg` and returns `202 {"message", "accepted": true, "channel_id"}` | `apps/channels/api_views.py:ChannelViewSet.match_channel_epg` | Inherently scoped |
| `is_bulk_matching = len(channels_data) > 1`, and the two threshold sets differ: bulk `{HIGH 90, SKIP_ML 80, MEDIUM 70, LAST_RESORT_MIN 50}`, single `{85, 75, 40, 20}` | `apps/channels/epg_matching.py:_get_epg_match_thresholds`, `:match_channels_to_epg` | Whether a name pair matches depends on how many channels were in the request. Both branches are worth pinning and they are cheap |
| `try_epg_name_match` returns the match immediately at `best_score >= FUZZY_HIGH_CONFIDENCE` and again at `>= FUZZY_SKIP_ML`; it calls `get_sentence_transformer()` **only** in the two bands `[MEDIUM, SKIP_ML)` and `[LAST_RESORT_MIN, MEDIUM)`, and returns `None` below `LAST_RESORT_MIN` without touching it | `apps/channels/epg_matching.py:try_epg_name_match` | **The design lever.** See D6 |
| `get_sentence_transformer()` imports `sentence_transformers` and constructs `SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", cache_folder="/data/models")`, downloading it unless `DISABLE_ML_DOWNLOADS=true`. `sentence-transformers==5.6.1` and `torch==2.13.0+cpu` are real dependencies, and the e2e container sets no such env | `apps/channels/epg_matching.py:get_sentence_transformer`; `pyproject.toml`; `scripts/e2e_up.sh` | A test landing in the ML band pulls a ~90 MB model over the public internet inside a CI job that has never taken an egress dependency. **This is the single largest hazard in the goal** |
| `use_ml=True` is hardcoded at every call site; nothing in the API can turn it off | `apps/channels/tasks.py:match_epg_channels`, `:match_selected_channels_epg`; `apps/channels/epg_matching.py:run_single_channel_epg_match` | The band discipline is the only control available |
| `build_epg_matching_catalog` walks **every `EPGData` row of every `is_active` `EPGSource` on the instance**, with a non-empty `name`, sorted by `epg_source.priority` | `apps/channels/epg_matching.py:build_epg_matching_catalog`, `:_active_epg_fuzzy_queryset` | Cross-worker aliasing: another worker's EPG rows are candidates for my channel. Assertions name *my* `epg_data_id`; generated names are what keep a foreign row's `fuzz.ratio` low |
| `normalize_name` lowercases, strips `[...]` and `(...)` (preserving a 3–5-uppercase-letter call sign matched against the **original** string), strips non-word characters, and drops `COMMON_EXTRANEOUS_WORDS` = `tv, channel, network, television, east, west, hd, uhd, 24/7, 1080p, 720p, 540p, 480p, film, movie, movies` | `apps/channels/epg_matching.py:normalize_name`, `COMMON_EXTRANEOUS_WORDS` | The score is `fuzz.ratio` over the *normalised* pair, so a name carrying `HD` scores identically to one without. Test names avoid every word on that list |
| Prefix/suffix/custom stripping is applied only when `epg_settings["epg_match_mode"] == "advanced"`, and the resolved lists are held in the module-global `_normalize_settings_cache`, cleared by `clear_normalize_settings_cache()` via `cleanup_after_matching()` | `apps/channels/epg_matching.py:normalize_name`, `:cleanup_after_matching`; `core/models.py:CoreSettings.get_epg_settings` | A real behavioural setting — and a **global** `CoreSettings` group with a process-local cache across four uWSGI workers. Out under D2/D10 |
| `get_preferred_region_code()` reads `CoreSettings.objects.get(key="preferred-region")`, a row `core/migrations/0020_change_coresettings_value_to_jsonfield.py` deletes with `CoreSettings.objects.exclude(key__in=grouped_keys).delete()`. **The same broken lookup is inlined twice more**, in `match_epg_channels` and `match_selected_channels_epg` | `apps/channels/epg_matching.py:get_preferred_region_code`; `apps/channels/tasks.py:match_epg_channels`, `:match_selected_channels_epg`; `core/migrations/0020_…` | Confirms `CLAUDE.md`'s entry and **extends it: three sites, not one.** The working accessor `CoreSettings.get_preferred_region` reads `system_settings["preferred_region"]` and nothing calls it. See D8 |
| `_compute_fuzzy_score` applies the region bonus as `+15` / `-15` on a `.xx` suffix in `tvg_id + name`, else `+10` on a bare substring | `apps/channels/epg_matching.py:_compute_fuzzy_score` | The weighting's effect is at most 15 points, which is inside the ML band for every pair that matters. Directly why D8 characterizes rather than pins |
| `set-names-from-epg`, `set-tvg-ids-from-epg` and `set-logos-from-epg` are `channel_ids`-scoped, return `200 {"message", "task_id", "channel_count"}`, and **copy from `channel.epg_data`** — they import nothing from `epg_matching.py` and run no matching | `apps/channels/api_views.py:ChannelViewSet.set_names_from_epg`, `:set_tvg_ids_from_epg`, `:set_logos_from_epg`; `apps/channels/tasks.py:set_channels_names_from_epg`, `:set_channels_tvg_ids_from_epg` | Deterministic, ML-free, and they depend on an association `set-epg` (G3) or `match-epg` (G14) made first. `set_channels_names_from_epg` writes `channel.name = channel.epg_data.name` only when the two differ |
| **A channel with `epg_data = None` is silently skipped by all three, counting toward neither `updated_count` nor `error_count`** — so a run against unmatched channels returns `{updated_count: 0, error_count: 0}`, indistinguishable from "already correct" | `apps/channels/tasks.py:set_channels_names_from_epg` | The ordering dependency is invisible in the response. Worth an explicit negative assertion, and it is one |
| All three tasks are `@shared_task(bind=True)` and set `task_id = self.request.id`; the POST returns that same `.delay()` id. The terminal payload carries `status: "completed"`, `updated_count`, `error_count`, `errors`; the failure payload carries `status: "failed"`, `progress: 0` and **no** `updated_count` | `apps/channels/tasks.py:set_channels_names_from_epg`, `:set_channels_tvg_ids_from_epg`, `:set_channels_logos_from_epg` | `where: (d) => d.task_id === body.task_id` is exact and cross-worker-safe. Key on `status`, never on the presence of `updated_count`. See D12a |
| **Neither `match-epg` form returns a task id.** The collection form returns `202 {"message"}` only; the detail form returns `202 {"message", "accepted", "channel_id"}`. Both discard `.delay()`'s result | `apps/channels/api_views.py:ChannelViewSet.match_epg`, `:match_channel_epg` | Matching has no `task_id` correlation available at all. See D12a |
| `POST /api/channels/channels/<id>/match-epg/` produces exactly one `single_channel_epg_match` on **every** path, success and failure alike, carrying `channel_id`, `matched`, `message`, and on success `epg_id`/`epg_name` and the full serialized channel | `apps/channels/epg_matching.py:send_single_channel_epg_match_result`, `:run_single_channel_epg_match` | The best correlation available for matching: `channel_id` is mine, the event is guaranteed, and `matched` is a boolean the test can assert directly instead of polling the channel row |
| The bulk terminal event `epg_match` carries `matches_count` (**changed rows only** — a re-run confirming existing matches reports `0`) and `associations: [{channel_id, epg_data_id}]`, and **no `task_id`** | `apps/channels/tasks.py:match_epg_channels`, `:match_selected_channels_epg` | The predicate is `associations.some(a => a.channel_id === mine)`; `matches_count === 1` alone would resolve on another worker's run |
| `epg_matching_progress` carries `total`, `matched`, `remaining`, `current_channel` (truncated to 50 chars, `""` on the start and end frames), `stage` and `progress_percent` — **no id of any kind** — and is throttled to `index < 5 or index % 5 == 0 or index == total - 1` | `apps/channels/epg_matching.py:send_epg_matching_progress` | Unusable as a terminal predicate on a shared broadcast. G14 does not wait on it |
| `run_single_channel_epg_match` hardcodes `is_bulk_matching = False`, and `match_channels_to_epg` derives it as `len(channels_data) > 1`. **So a collection `match-epg` with exactly one id runs the aggressive single-channel thresholds** | `apps/channels/epg_matching.py:run_single_channel_epg_match`, `:match_channels_to_epg` | A sharp edge, and **not cheap to pin after all**: any score the two branches disagree about lies in `[75, 80)`, which on the bulk path is inside `[70, 80)` and therefore calls `get_sentence_transformer()`. Recorded as an observation; the test that was going to pin it (9) is cut. See D6 |
| `ChannelViewSet.match_epg` branches on `if channel_ids:`, so an **empty list takes the instance-wide branch**, and it validates nothing — no 400 path exists on that endpoint | `apps/channels/api_views.py:ChannelViewSet.match_epg` | D7 is stricter than "pass `channel_ids`": it must be non-empty. Recorded as an observation |
| `apply_matched_epg_to_channels` writes **`Channel.epg_data` and nothing else**, via `bulk_update`, and therefore calls `_dispatch_program_parse_for_epg_assignments` explicitly because `bulk_update` bypasses `post_save`. It returns changed associations only | `apps/channels/epg_matching.py:apply_matched_epg_to_channels`, `:_dispatch_program_parse_for_epg_assignments` | Matching sets the association; it never touches `name`, `tvg_id` or `logo`. That is exactly why `set-*-from-epg` exists as a separate step, and why the two are separate files here |
| The exact-`tvg_id` and exact-gracenote (`Channel.tvc_guide_stationid`) short-circuits `continue` **before** `try_epg_name_match` is reached, and both look up the **same** `tvg_id` index — there is no gracenote column on `EPGData` | `apps/channels/epg_matching.py:match_channels_to_epg`, `:build_epg_tvg_id_index` | An ID-matched channel can never reach the ML branch whatever its name scores. The safest test shape in the goal |
| Because `get_preferred_region_code()` always returns `None` (below), `_compute_fuzzy_score` reduces to exactly `fuzz.ratio(chan_norm, epg_norm)` with no bonus term | `apps/channels/epg_matching.py:_compute_fuzzy_score` | The score is predictable in closed form, which is what makes D6's band discipline designable at all |
| Coverage of `epg_matching.py` today is `test_epg_name_normalize.py` (`normalize_name`, `build_epg_tvg_id_index`, the settings cache) and `test_epg_match_apply.py` (`apply_matched_epg_to_channels`, 2 tests). **`match_channels_to_epg`, `run_single_channel_epg_match`, `try_epg_name_match`, `_compute_fuzzy_score`, `_fuzzy_scan_core`, `build_epg_matching_catalog`, `lookup_epg_by_tvg_id`, `get_preferred_region_code`, all five tasks and all five endpoints have zero test references anywhere in the tree.** `apps/channels/tests/test_epg_matching.py` is a misleading filename — it tests `_match_epg_program_by_timeslot`, a DVR recording concern | `apps/channels/tests/`; `grep` for each symbol | The "no backend coverage compensates" claim is not an inference here; it is an enumeration |

### Bulk operations, filters, plugins

| Fact | Source | Consequence |
|---|---|---|
| `PATCH /api/channels/channels/edit/bulk/` takes a **bare list** of `{id, ...fields}` objects, validates every row before applying, and 400s on any item missing `id` | `apps/channels/api_views.py:ChannelViewSet.edit_bulk` | A list body, not an envelope. Validate-then-apply is itself worth an assertion: one bad row must leave the good rows untouched |
| `DELETE /api/channels/channels/bulk-delete/` takes `{"channel_ids": [...]}` **in the request body** and an optional `stop_stream`, and returns `Response({"message": …}, status=204)` — a 204 with a body | `apps/channels/api_views.py:BulkDeleteChannelsAPIView.delete` | `ApiClient.delete(url)` takes no body today. See D15 |
| `POST /api/channels/channels/assign/` takes `{"channel_ids": [...], "starting_number": <float>}` and writes `channel_number` on exactly those ids, incrementing by 1, inside one transaction. It performs **no collision check** | `apps/channels/api_views.py:ChannelViewSet.assign` | Scoped to the caller's ids, so it is safe on a shared instance in a worker-scoped band. G3's D3 already established that `channel_number` has no DB uniqueness |
| `POST /api/channels/channels/<pk>/reorder/` takes `{"insert_after_id": <id\|null>}` and shifts **every `Channel` on the instance** whose `channel_number` falls between the old and desired positions, with `.update(channel_number=F('channel_number') ± 1)` and no account, group or profile filter. `insert_after_id: null` targets position 1, so the shift range becomes `[1, old_number)` | `apps/channels/api_views.py:ChannelViewSet.reorder` | **`insert_after_id: null` renumbers essentially every channel on the instance.** G14 never sends it. See D9 |
| `M3UFilter` has `filter_type` ∈ `{group, name, url}`, `regex_pattern`, `exclude` (default `True`), `order`, `custom_properties`; the endpoint is the account-nested `/api/m3u/accounts/<account_id>/filters/` and `perform_create` sets `m3u_account_id` from the URL | `apps/m3u/models.py:M3UFilter`; `apps/m3u/api_urls.py`; `apps/m3u/api_views.py:M3UFilterViewSet` | Filters are **per account** — the most row-scoped behavioural setting in the product |
| `_stream_passes_m3u_filters` walks the filters in `order` and returns `not filter_obj.exclude` on the **first** match; a stream matching nothing passes. `_compile_m3u_stream_filters` sets `re.IGNORECASE` only when `custom_properties["case_sensitive"] is False` | `apps/m3u/tasks.py:_stream_passes_m3u_filters`, `:_compile_m3u_stream_filters` | First-match-wins and include-mode are both assertable. Note the double negative: the flag's *absence* means case-**sensitive** |
| Filters are applied on both ingest paths — `_refresh_single_m3u_account_impl` compiles once and hands `compiled_stream_filters` to `process_m3u_batch_direct` for the standard M3U branch *and* the XC branch | `apps/m3u/tasks.py` (both `executor.submit(process_m3u_batch_direct, …)` sites) | No XC-specific gap. G14 tests the standard path only, and says so |
| `M3UFilter.applies_to` hardcodes `re.IGNORECASE` and reads `group_name` for `filter_type == "group"` and `stream_name` otherwise — it has **no `url` branch** and disagrees with `_compile_m3u_stream_filters` on case. It has no non-test caller | `apps/m3u/models.py:M3UFilter.applies_to`; `grep -rn --include="*.py" applies_to apps/` | Dead code with divergent semantics. Recorded as an observation; not tested, not filed as a defect (nothing calls it) |
| `POST /api/plugins/plugins/<key>/run/` takes `{"action": <str>, "params": {}}` and is **synchronous in the web worker** via `PluginManager.run_action`. Checks run in order: missing `action` → `400`; no `PluginConfig` row → `404`; `not cfg.enabled` → `403 {"success": false, "error": "Plugin is disabled"}` | `apps/plugins/api_views.py:PluginRunAPIView.post` | Three negative branches and one positive, all cheap, all API-level |
| **`404` is narrower than it looks.** A `PluginConfig` row that exists but whose module will not load raises `ValueError` inside `run_action`, which the view catches as a generic exception → **`500`**, not `404` | `apps/plugins/api_views.py:PluginRunAPIView.post`; `apps/plugins/loader.py:PluginManager.run_action` | The 404 assertion must use a key with no row at all — a generated key that was never imported |
| **The result is double-wrapped.** `run_action` returns the plugin's value verbatim when it is a `dict`, else wraps it `{"status": "ok", "result": <value>}`; the view wraps that again as `{"success": true, "result": …}` | `apps/plugins/loader.py:PluginManager.run_action`; `apps/plugins/api_views.py:PluginRunAPIView.post` | A fixture plugin returning a dict yields `{"success": true, "result": {<its dict>}}` — easy to assert one level wrong |
| `PluginManager._build_context` hands `run()` exactly three keys: `settings` (the stored settings **merged with each field's declared default**), `logger` (the `apps.plugins.loader` module logger) and `actions`. There is no sandbox and no capability object | `apps/plugins/loader.py:PluginManager._build_context`, `:_merge_settings_with_defaults` | The plugin is ordinary in-process Python with the whole Django app importable — which is why D14 keeps it inert at import |
| **`GET /api/plugins/plugins/` returns the raw `PluginConfig.settings`, unmerged**, while `run()` sees the defaulted dict — so a freshly imported plugin lists `"settings": {}` and still runs with its defaults | `apps/plugins/api_views.py:PluginsListAPIView`; `apps/plugins/loader.py:_merge_settings_with_defaults` | A trap for any assertion that reads a default back from the list endpoint. G14 asserts only values it wrote |
| `buildPluginZip` writes `plugin.json` and `plugin.py` with `actions: []` and a `run` returning `{"status": "noop"}` | `e2e/tests/frontend/plugin-zip.ts:buildPluginZip` | The fixture plugin already has a `run`; it declares no action for the UI to offer. One additive option closes that. See D14 |
| `Plugins.md` documents the intended plugin idiom as dispatching **existing** product Celery tasks with `.delay()` and returning quickly, and warns that `run` executes on the uWSGI gevent hub | `Plugins.md`, "Accessing Dispatcharr APIs from Plugins", "Best Practices" | This is what "task-fires" means, and it is why that half is the goal's riskiest work |
| A runtime-imported plugin **can** `.delay()` an existing product task immediately — `.delay()` only publishes a message naming a task the Celery worker already registered through `autodiscover_tasks()`. It **cannot** define a *new* `@shared_task` an already-running worker will honour: plugins are outside `INSTALLED_APPS`, and the only import hook is `@worker_process_init` in `dispatcharr/celery.py:init_worker_process`, which runs once per forked child at start. A newly forked `--autoscale` child *does* pick it up, so the failure is nondeterministic rather than clean | `dispatcharr/celery.py:init_worker_process`; `apps/plugins/loader.py:PluginManager.discover_plugins`; `tests/test_celery_plugin_discovery.py` | Confirms the web/Celery asymmetry: `.reload_token` converges the uWSGI workers with no restart, and nothing converges the Celery workers. Recorded as an observation whether or not D14a's test ships |

### The WebSocket surface

| Fact | Source | Consequence |
|---|---|---|
| One route (`/ws/`), one group (`"updates"`), auth by a JWT access token in the **`token` query parameter only** — an anonymous socket is closed before `accept()`, so no frame arrives at all | `dispatcharr/routing.py`; `dispatcharr/consumers.py:MyWebSocketConsumer.connect`; `dispatcharr/jwt_ws_auth.py:JWTAuthMiddleware` | Matches what `e2e/fixtures/ws.ts` already documents and pins |
| **Five event types are admin-only** — `channel_stats`, `vod_stats`, `timeshift_stats`, `vod_started`, `vod_stopped` — plus `system_notification` conditionally on `data["notification"]["admin_only"]`. The filter is a **silent drop**, not an error frame, and "admin" is `user_level >= 10` | `dispatcharr/consumers.py:ADMIN_ONLY_UPDATE_TYPES`, `:user_may_receive_update` | **No test has ever driven a non-admin socket.** This is an authorization property of the product with zero coverage, and it costs one hand-built `WsListener`. See D12b |
| `channel_stats` is emitted by a beat task (`apps/proxy/tasks.py:fetch_channel_stats`, `core/tasks.py:fetch_channel_stats`) roughly once a second, and additionally inline by `GET /proxy/ts/status` | those symbols; `e2e/fixtures/ws.ts`'s `DESCRIBE_LIMIT` comment records the once-a-second rate | Two consequences: it can never be *correlated* to one request, and it is free continuous traffic — which is exactly what a negative admin-filter test needs as its control |
| `POST /api/epg/sources/` with `source_type: "dummy"` fires `epg_data_created` from a **synchronous** `post_save` receiver carrying `source_id`, `source_name` and `epg_data_id`, and dummy sources are excluded from refresh scheduling, so no Celery task is dispatched | `apps/epg/signals.py`; `apps/epg/tasks.py` | The cheapest correlated *product* WebSocket event in the whole application: one REST call, no Celery, no refresh, and an id to key on |
| `core/utils.py:log_system_event` sends **no** WebSocket message. `apps/connect/models.py:SUPPORTED_EVENTS` (17 keys) is the Connect/plugin vocabulary and `core/models.py:SystemEvent.EVENT_TYPES` (22 choices) is the DB vocabulary; the socket's vocabulary is the `send_websocket_update` call sites and overlaps neither by design | `core/utils.py:log_system_event`, `:_dispatch_system_event_integrations`; `apps/connect/utils.py:trigger_event` | **The brief's map is the wrong map.** A spec written to `SUPPORTED_EVENTS` would wait for events that are never sent. See D12 |
| `GET /api/core/system-events/` (`IsAdmin`) takes `limit` (default 100, capped 1000), `offset` and an exact `event_type`; it is hand-rolled, not DRF-paginated, and returns `{events, count, total, offset, limit}` | `core/api_views.py:get_system_events` | The only read surface for `SystemEvent`, and it is global — with the truncation above, unusable for an assertion on a shared instance |
| Three frontend `case`s have no backend sender at all — `epg_file`, `epg_channels`, `epg_sources_changed` | `frontend/src/WebSocket.jsx`; every `send_websocket_update` call site | Dead handlers. Recorded as an observation; not tested, not filed |

### Harness

| Fact | Source | Consequence |
|---|---|---|
| `seeded` runs `workers: 4`, `fullyParallel: true` and the global 30 000 ms timeout | `e2e/playwright.config.ts` | **File-level confinement does not exist in `seeded`** — two tests in one file run in two workers. Any hazard must be confined to a single *test*, not a single file |
| `streaming-failover` (`proxy_settings`) and `streaming-greybox` (`stream_settings.default_stream_profile`) both pin `workers: 1` because one spec in each mutates a global `CoreSettings` row | `e2e/playwright.config.ts`, project comments | The repo's established price for a global settings mutation is a whole single-worker project and CI job. D2 is what avoids paying it a third time |
| `e2e/README.md` rule 11: drive a client-facing output surface with the built-in `request` fixture, never `api` — `ApiClient` retries once through a token refresh on *any* 401 | `e2e/README.md`, "Writing a test" | Load-bearing for `network-acl.spec.ts`: its XC assertions are about 401 and 403, and `api` would retry one of them away |
| `ApiClient.get/post/patch/delete` are thin wrappers over a private `send(method, url, data?)`; `delete` alone omits the `data` argument | `e2e/fixtures/api.ts:ApiClient` | `bulk-delete` needs a DELETE body. One additive line. See D15 |
| `ws.waitForMessage(type, { where })` evaluates `where` against `message.data` as each message arrives and once against the queue, never retroactively — so the correlating value must exist before the wait is registered | `e2e/fixtures/ws.ts:WsListener.waitForMessage`; `e2e/README.md` | For the `task_id` correlation the POST must return first, and the events must still be arriving. Every `set-*-from-epg` task sends its first event at task start and its last at completion, and Celery latency is what makes the wait reliable — but it is a race in principle. See D12 |
| `log_system_event` writes a `SystemEvent` row, fans out to Connect integrations and plugin event hooks, and then **deletes every event beyond `max_system_events` (default 100)**. It sends no WebSocket message | `core/utils.py:log_system_event` | Two things: the WS map is `send_websocket_update()` call sites, not this; and `SystemEvent` on a shared instance is a global truncating table, so **G14 asserts no `SystemEvent` row** |
| `seed.generatedName(entity)` is the worker- and test-scoped name generator every factory uses | `e2e/fixtures/seed.ts:Seeder.generatedName` | The entropy that keeps a G14 channel name from fuzzy-matching another worker's EPG row |
| `bootstrap` pre-warms only the `(every=1, HOURS)` `IntervalSchedule`; a non-zero `refresh_interval` used from a worker must be unique per test, and leaves an *enabled* beat task | `e2e/setup/bootstrap.setup.ts:prewarmIntervalSchedule`; `e2e/README.md`, "Non-zero `refresh_interval` values" | G14 uses `refresh_interval: 0` everywhere and adds nothing to the `{0, 2, 3, 4, 8531, 8532}` set |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| **D1** | **No new Playwright project, no CI matrix entry, no isolated instance.** Twenty-two of G14's twenty-three tests land in the existing `seeded` project; the twenty-third is appended to `e2e/tests/frontend/plugins.spec.ts` | Every G14 test is an API-level read/write plus a Celery-backed wait — the same shape as G3's, which chose `seeded` for the same reason (its D1). The cost of the alternative is concrete and was priced: a project block in `playwright.config.ts`, a matrix entry in `e2e-tests.yml` (which arms the zizmor hook, a zero-findings ratchet, on a file two other wave-6 goals may also be editing), a `package.json` script, a README project row, and a whole extra container boot — for tests that would then run at `workers: 1`. D2, D3 and D4 are what make it unnecessary. Rejected: an `acl` project (buys a container nothing needs); folding into `pristine` (its requirement is "no superuser yet", which is not G14's, and `e2e/README.md` says so explicitly) |
| **D2** | **G14 mutates no global `CoreSettings` row, with exactly one named exception: `network_access["XC_API"]`, in one test, restored in `afterEach`.** `UI` is never written, under any circumstance | Rule 4 and the two single-worker projects that already exist are the precedent for how expensive a global mutation is here. The exception is admissible because **it denies nothing that exists**: narrowing `XC_API` from `0.0.0.0/0` to `LOCAL_NETWORK_CIDRS` refuses only requests carrying a spoofed non-local `X-Real-IP`, and the only client that sends one is this test. Even a leaked value — an `afterEach` that never ran — costs the container nothing, which is the argument that makes it acceptable rather than merely small. `UI` is excluded absolutely because `apps/accounts/permissions.py:Authenticated` gates every DRF endpoint on it, including the one that would undo the change: recovery would be `manage.py reset_network_access` over `docker exec`, i.e. a grey-box escape hatch inside a black-box project. **This exception is the single thing in G14 most worth a reviewer's attention.** If review declines it, the test is dropped, `get.php`'s 403 becomes a gap row, and nothing else in the goal changes |
| **D3** | **403 negatives are produced by moving the apparent client IP, not by narrowing an ACL.** `GET /output/m3u`, `/output/epg` and `/hdhr/lineup.json` with `X-Real-IP: 203.0.113.5` must 403 on an unmodified instance | The `M3U_EPG` scope defaults to `LOCAL_NETWORK_CIDRS` and the shipped row is `{}`, so the deny is the product's own out-of-the-box behaviour — the strongest possible form of this assertion, because nothing had to be arranged for it. `203.0.113.0/24` is RFC 5737 TEST-NET-3, reserved for documentation, so it cannot collide with a real deployment's address. This also, incidentally, exercises `get_client_ip`'s trusted-proxy path, which no test has ever reached |
| **D3a** | **The header-trust mechanism is proved as a premise, outside the inverted assertion, before any 403 is asserted.** `POST /api/core/settings/check/` returns `client_ip`; the test reads it twice — once plainly, once with the spoofed header — and asserts the second differs and equals the spoofed address | This is the G9/G10 premise-guard pattern (`8386825c`, `c1858c42`) that G15 is backporting, applied at design time rather than retrofitted. It converts the design's one environmental assumption into a runtime assertion with a self-naming failure: if a future `DISPATCHARR_TRUSTED_PROXIES`, an `uwsgi_param` fix for [#81](https://github.com/D10Scot/Dispatcharr/issues/81), or a different container topology removes header trust, the guard fails saying exactly that instead of the 403 assertion failing as a mysterious 200 |
| **D4** | **The per-user lever is `user.custom_properties["allowed_networks"]`, set through the ordinary admin user-update endpoint on a `seed.xcUser()`** | It is row-scoped, needs no global write, needs no header spoofing (point it at `203.0.113.0/24` and no real client can match), and costs **zero logins** — the XC surface authenticates from credentials in the URL, so no token is ever minted for that user. It is also the only way to reach `network_access_allowed`'s user branch, which no test has executed |
| **D5** | **The XC API's per-user denial returns 401, not 403, on all four endpoints — asserted correct, `test.fail()`ed, and filed** | `xc_get_user` collapses "your network is not permitted" into the same `None` it returns for a wrong password, and every caller maps that to `401 {"error": "Unauthorized"}`. `get.php`/`xmltv.php` do have a real 403, but only from the *global* check that passes no user, so the per-user branch can never produce one anywhere. `player_api.php` and `panel_api.php` additionally log no `SystemEvent`, so the denial is invisible in the events log as well as mislabelled in the response. Three call sites disagree on the contract for the same two conditions: `stream_xc` gets it right (403 then 401), `_timeshift_proxy_impl` returns plain-text 403 for both and checks credentials first. New; not #84 (which is the unknown-username 404 oracle) and not in `CLAUDE.md`. File it with `gh issue create --repo D10Scot/Dispatcharr` |
| **D6** | **Every EPG-matching test is built so `get_sentence_transformer()` is never called.** Name pairs are chosen so `fuzz.ratio` over the *normalised* strings lands either at or above `FUZZY_SKIP_ML` (a match, ML skipped) or below `FUZZY_LAST_RESORT_MIN` (no match, ML never reached). The threshold band is stated in a comment at every such assertion, with the numbers and which branch of `_get_epg_match_thresholds` applies. **The general rule, stated once so it is not re-derived: on the bulk path the only ML-free outcomes are a score at or above 80 (match) and below 50 (no match); on the single path, at or above 75 and below 20.** Everything between reaches `get_sentence_transformer()`, because `try_epg_name_match` calls it whenever `best_score >= fuzzy_medium` — 70 on the bulk path, 40 on the single path — and again in `[fuzzy_last_resort_min, fuzzy_medium)`. That rule is what removed test 9: it asked for a `[75, 80)` pair on the *bulk* path, which is squarely inside `[70, 80)` and downloads the model | `try_epg_name_match` reaches `get_sentence_transformer()` only inside `[MEDIUM, SKIP_ML)` and `[LAST_RESORT_MIN, MEDIUM)`, and that function downloads `all-MiniLM-L6-v2` into `/data/models` unless `DISABLE_ML_DOWNLOADS=true`, which the e2e container does not set. A test in the middle band would pull ~90 MB over the public internet inside a CI job that has taken no egress dependency in ten goals, on every run, before the model is cached — and on a cold container, every time. `use_ml=True` is hardcoded at every call site, so the band discipline is the only lever the API offers. Rejected: setting `DISABLE_ML_DOWNLOADS` in `scripts/e2e_up.sh` (a harness change that alters the product's behaviour under test, hiding a real code path rather than avoiding it); pre-baking the model into the image (a ~90 MB layer for one test) |
| **D6a** | **The band is asserted, not assumed.** Each matching test computes nothing itself, but its comment records the exact normalised pair and the `fuzz.ratio` the design predicts, and the test asserts the *outcome* the band implies — match or no match. The plan's first task is a probe that reads the real score out of a live container before any test is written | `fuzz.ratio` over `normalize_name`'s output is deterministic but not obvious: the function strips bracketed text, preserves an uppercase call sign matched against the *original* string, and drops fifteen common words including `hd`, `tv` and `channel`. A predicted score that is wrong by ten points silently moves a test into the ML band, and the symptom is a slow first run, not a failure. Probing first is cheaper than debugging that |
| **D7** | **`match-epg` is always called with a *non-empty* explicit `channel_ids` list, or in its detail form** | The collection form branches on `if channel_ids:`, so both an omitted list **and an empty one** dispatch `match_epg_channels`, which matches every EPG-less channel on the instance — it would rewrite other workers' and other goals' channels mid-run, and the endpoint validates nothing and has no 400 path to stop it. This is not a hazard the harness can mitigate; it is one it must never trigger. Written into `e2e/README.md`, not only here |
| **D7a** | **The detail form, `POST /api/channels/channels/<id>/match-epg/`, is the primary matching surface; the collection form is used only where a multi-channel behaviour is the subject** | Three reasons, all from the code. It is inherently scoped, so D7's hazard cannot be triggered by a typo. It emits `single_channel_epg_match` on **every** path including failures, carrying `channel_id` — the only guaranteed, exactly-correlated matching event in the product. And its payload carries `matched` as a boolean plus `epg_id`, so the assertion is one message rather than a poll on the channel row |
| **D8** | **`get_preferred_region_code()` is characterized in prose and filed as an issue — it gets no test, and specifically no `test.fail()`** | Two independent reasons, either sufficient. (i) The correct behaviour is "regional weighting changes which candidate wins", and `_compute_fuzzy_score`'s weighting is at most ±15 points, so any pair where it decides the outcome sits inside the ML band D6 exists to avoid — a `test.fail()` there would be unrunnable by construction, or would import the model download. (ii) Setting a region at all requires writing `system_settings["preferred_region"]`, a global `CoreSettings` group, which D2 forbids. So the honest encoding is a `COVERAGE.md` row and an issue, not a red test. The issue is worth filing anyway and is **new information** three times over: `CLAUDE.md` records one broken site, and there are **three** — `match_epg_channels` and `match_selected_channels_epg` each inline their own copy of the same dead lookup, so fixing the named one fixes nothing; the working accessor `CoreSettings.get_preferred_region` exists and no matcher calls it; and `CoreSettings.value` is a `JSONField` now, so even if the row survived, `.strip()` would raise `AttributeError`, which `except CoreSettings.DoesNotExist` does not catch. What makes it worth filing rather than merely noting is the user-facing half: the setting is exposed in the UI (`frontend/src/utils/forms/settings/SystemSettingsFormUtils.js`, System Settings) and persists correctly, so an operator can set a region, watch it save, and get no behavioural change at all |
| **D9** | **`reorder` is exercised only with an explicit `insert_after_id`, between three channels the test seeded into a worker-scoped four-figure `channel_number` band. `insert_after_id: null` is never sent.** The instance-wide shift is recorded as an observation, not filed | `reorder` shifts every `Channel` whose number falls between the old and desired positions, with no account, group or profile filter — and `insert_after_id: null` sets the desired position to 1, making the shift range `[1, old_number)`, which on this instance is every channel any test has ever created. Confined to three adjacent numbers the test owns, the shift is fully observable *and* fully scoped: move the third channel to sit after the first, and all three of the resulting numbers are the test's own. That proves the mechanism without touching a row the test did not create. Whether the global shift is a *defect* is genuinely arguable — channel numbers are a single-tenant global namespace and "maintain contiguous ordering" is the docstring's stated intent — so it is written down as an observation with the mechanism, and left for a maintainer rather than filed as a bug this goal cannot adjudicate. G3's D3 discipline (a high band derived from the worker index) is reused verbatim |
| **D10** | **Sub-area 3 resolves into a decision, not a test block: the behavioural settings G14 covers are the row-scoped ones — `M3UFilter` (D-rank 4), per-user `allowed_networks` (D4) — and every global `CoreSettings` group is recorded as one `COVERAGE.md` gap row, *unowned, post-wave-6*.** The gap names its most migration-relevant member explicitly: `network_access["STREAMS"]`, which gates `/proxy/ts/stream/<uuid>` | The disposition asked for "settings with behavioural effect beyond the User-Agent persistence already covered". Read against the code, the settings with behavioural effect divide cleanly: the row-scoped ones are testable on `seeded` and G14 tests them, and the rest are global JSON groups — `epg_settings.epg_match_mode` (advanced-mode normalisation, which really does change matching), `stream_settings.default_user_agent`, `proxy_settings`, `system_settings.preferred_region`, `network_access` — every one of which is instance-wide state four workers share. **This row was originally handed to G12, and G12 declined it** — its revised spec records that it does not absorb the global-`CoreSettings`-groups row, so the honest encoding is an unowned gap rather than a handoff to a goal that has said no. Two of those groups are *already* partially covered from single-worker projects (`proxy_settings` by `failover-buffering.spec.ts`, `default_stream_profile` by `vod-redirect-profile.spec.ts`), which is the precedent for how the rest should land — not in `seeded`. **The member that matters to the extraction is named in the row**: `apps/proxy/live_proxy/views.py:stream_ts` calls `network_access_allowed(request, "STREAMS")` with **no user**, so the global `STREAMS` scope is the only ACL on `/proxy/ts/stream/<uuid>` — the endpoint the relay extraction moves, and the one `CLAUDE.md` says becomes a Django-minted HMAC-signed URL. A second, cheaper observable for the same scope exists and is recorded as its own gap: `:stream_xc` passes `user`, so the per-user `allowed_networks["STREAMS"]` branch (`dispatcharr/utils.py:network_access_allowed`) is row-scoped and provable through the XC live route with **no global write at all** — work for whichever goal next owns the `streaming` projects, which G14 does not |
| **D11** | **`M3UAccountProfile` URL rewriting and `ServerGroup` credential pooling are out of scope, recorded as gaps naming the exact observable each needs** | Both are real and both are `streaming`-project work. The profile's `search_pattern`/`replace_pattern` are consumed by `apps/proxy/live_proxy/url_utils.py:transform_url` at stream time, so proving it means opening a real stream and reading the path back out of the fake provider's `ScenarioLog` — a byte-level test, in a different project, for a goal that is otherwise entirely API-level. `ServerGroup` is worse: `apps/m3u/connection_pool.py:get_enforced_server_group_for_profile` and `:group_has_capacity_for_profile` share a Redis credential counter across accounts, so proving it needs two accounts sharing one credential, both at `max_streams: 1`, and two concurrent streams whose second must be refused. Note that [#68](https://github.com/D10Scot/Dispatcharr/issues/68) already reports a case-folding defect in exactly that fingerprint, so the area is known-suspect and deserves a real test — from a goal that owns the streaming projects, which G14 does not. Both rows name the mechanism so the next owner starts from the observable, not from a rediscovery |
| **D12** | **The product's WebSocket vocabulary is the `send_websocket_update()` call sites, not `apps/connect/models.py:SUPPORTED_EVENTS`** | `core/utils.py:log_system_event` writes a `SystemEvent` row and fans out to Connect integrations and plugin event hooks, and sends **no** WebSocket message. There are three separate vocabularies in this product — `SUPPORTED_EVENTS` (17 keys, Connect and plugin hooks), `SystemEvent.EVENT_TYPES` (22 choices, the DB) and the socket's own set of `data.type` literals — and they overlap only by coincidence of naming. **The brief's map is the wrong map**, and a spec written to it would have waited for events the product never sends. Recording the correction is half of what this sub-area is worth |
| **D12a** | **Correlation predicate, in strict preference order: (1) a Celery `task_id`; (2) an id in the payload the test owns; (3) nothing — do not wait on it.** No G14 wait uses a bare type match | `/ws/` is one broadcast across four workers, so `where` is mandatory for any type a parallel test can also produce. The available keys, from the code: the three `set-*-from-epg` tasks carry the Celery `task_id` the POST returned — globally unique, known *before* the wait registers, which is exactly the ordering `WsListener.waitForMessage` requires, and the strongest predicate in the product. `single_channel_epg_match` carries `channel_id`. `epg_match` carries `associations[].channel_id`, but `matches_count` alone is not a predicate — it counts *changed* rows, so a re-run reports `0` and a concurrent worker's run satisfies any count you pick. `epg_matching_progress` carries **no id at all** and is throttled (`index < 5 or index % 5 == 0 or index == total - 1`), so it is unusable as a terminal predicate and G14 does not wait on it. `channel_stats` is emitted by a beat task about once a second and cannot be attributed to a request at all |
| **D12b** | **The one WebSocket property worth a test of its own is the admin-only filter, and it is proved as a paired positive and negative in a single window** | `dispatcharr/consumers.py:ADMIN_ONLY_UPDATE_TYPES` silently drops five types for a non-admin socket, and **no test has ever opened a non-admin socket** — this is an authorization property with zero coverage, and a silent drop is exactly the kind that rots unnoticed. It is also unusually cheap to prove, because `channel_stats` is beat-driven traffic that arrives whether or not the test does anything: open an admin socket (the `ws` fixture) and a Streamer socket (a hand-built `WsListener` from `asPrincipal('streamer')`'s token — `WsListener` is already exported, so no fixture change), collect for one window, and assert the admin saw at least one `channel_stats` and the Streamer saw none. The positive is the premise guard for the negative: if no traffic arrived at all, the test fails saying so rather than passing vacuously |
| **D12c** | **`SystemEvent` is never asserted** | `log_system_event` deletes every row beyond `max_system_events` (default 100) on **every call**, instance-wide, and the only read surface — `GET /api/core/system-events/` — is global with an exact-match `event_type` filter and no scoping to anything a test owns. On a four-worker instance a row can be evicted between the trigger and the read by traffic the test cannot see. This also means the `m3u_blocked`/`epg_blocked` rows the ACL 403 paths write are observed only as prose in D5's issue, not as an assertion |
| **D13** | **G14's default tag is `@contract`. Exactly four tests are `@characterization`, each carrying a `// @characterization: <fact>` comment immediately above its `test(` call.** The tag is Playwright's native option passed as the **second argument, an inline object literal** — `test('title', { tag: '@contract' }, async ({ … }) => { … })`, and `test.fail('title', { tag: '@contract' }, async …)` for test 5 | The taxonomy is `docs/adr/0002-e2e-test-taxonomy.md` and the enforcement is `e2e/tests/guards/tags.spec.ts`, which fails closed: every `test`/`test.only`/`test.skip`/`test.fail`/`test.fixme` declaration needs exactly one recognised tag, and a declaration whose shape it cannot read is `unverifiable` and fails. **Tags go on each `test(` call, never on a shared const**: a `test.describe` may carry the tag instead, but only if its details object is an inline literal — a by-reference object makes every enclosed test unverifiable and fails the guard. This matters concretely for `network-acl.spec.ts`, which uses `test.describe.configure({ mode: 'serial' })` and so has no tagged enclosing describe to inherit from. `KNOWN_UNVERIFIABLE` is empty at `45a33a4a` and G14 adds nothing to it. Three categories, four tests. **Test 1**, the `X-Real-IP` premise guard (D3a): it asserts a property of *this* container's nginx/uwsgi topology, and a deployment setting `DISPATCHARR_TRUSTED_PROXIES=none` would correctly fail it. **Tests 7 and 8**, the fuzzy-threshold assertions (D6): they pin two of the twelve hardcoded numbers in `_get_epg_match_thresholds` (six per branch) — the single path's `FUZZY_SKIP_ML` of 75 and the bulk path's `FUZZY_LAST_RESORT_MIN` of 50. Implementation, not contract. **Test 23**, `reorder` (D9): it pins today's global-namespace renumbering, which a scoped rewrite would legitimately change. Everything else — a filter excludes a stream, a bulk edit validates before it applies, a blocked network is refused, an action reaches a plugin, an event carries its task id — is behaviour any reimplementation must preserve. ADR-0002's tie-break applies unchanged: **ambiguity resolves to `@contract`**, because a wrongly-`@characterization` test is invisible on a migration branch while a wrongly-`@contract` one is noise someone reclassifies |
| **D13a** | **The one guard G14 has to be added to is `GLOBAL_SETTINGS_WRITE`: `tests/seeded/network-acl.spec.ts` goes on that list in `e2e/tests/guards/allowlist.ts`, with ADR-0003's required justification written into the diff.** No G14 file trips `CONTAINER_LIFECYCLE`, `SUBPROCESS`, `GREYBOX_REDIS` or `CONTAINER_INTROSPECTION` | `e2e/tests/guards/global-mutation.spec.ts` fails any `api.post/patch/put/delete` whose URL resolves to contain `core/settings` from a file not on the list, and test 3 PATCHes `/api/core/settings/<id>/`. The list is compared with `toEqual`, so the entry is mandatory rather than optional and a stale one would fail too. ADR-0003 requires the addition to say **which group it writes** (`network_access`, key `XC_API` only, `UI` never), **why nothing else reads it** (D2's blast-radius argument: the narrowed value refuses only a request carrying a spoofed non-local `X-Real-IP`, and nothing else in the suite sends one) and **how teardown restores it** (the `afterEach` that writes back the value captured before the PATCH). That is precisely the review D2 already asks for, so the two are the same argument in two places and must not drift. The other four capabilities are clear by construction: G14 destructures no `instance` fixture, imports no `node:child_process`, uses no grey-box Redis helper, and writes no `pgrep`, `docker ` or `manage.py` **string literal** into a spec — the `docker exec` probes in the plan are shell commands in the plan's own prose, which `capabilities.spec.ts` parses past because it reads literals rather than scanning text. **Tension, recorded and deliberately not resolved here:** ADR-0002 says anything on a capability allowlist is `@characterization` by construction, but the tree does not apply that — `tests/streaming-failover/failover-buffering.spec.ts` is on `GLOBAL_SETTINGS_WRITE` and tagged `@contract`. G14 follows the tree's precedent and keeps test 3 `@contract`, because its assertion — a blocked network gets 403 from `get.php` and `xmltv.php` — is client-observable behaviour any reimplementation must preserve, and the settings write is setup rather than the subject. The ADR wording is a follow-up for G11's owner; G14 does not edit an ADR it does not own |
| **D14** | **The plugin work appends one test to `e2e/tests/frontend/plugins.spec.ts` and adds one optional argument to `buildPluginZip`. It does not create a new plugin spec** | G6's one-spec-file-per-surface rule is load-bearing in the `frontend` project: file-level parallelism at `workers: 2` is what confines the plugin directory and its shared `.reload_token` to a single worker, and `e2e/README.md` says splitting the file reopens that. A `seeded` home is worse still — `fullyParallel: true` means even one file gives no confinement. So the plugin work goes where the hazard is already managed. `plugin-zip.ts` gains `actions?: {id, label}[]`, defaulting to `[]` so G6's existing test is byte-identically unaffected, and the generated `run` returns a value derived from `params` so the assertion proves the action *and* its parameters reached the plugin. The plugin stays inert **at import**: only `run()` does anything, only when this test calls it, and G6's `afterEach` already deletes it |
| **D14a** | **"Task-fires" is scoped to the plugin dispatching one existing product Celery task against the test's own `M3UAccount`, and is the third item on the cut list** | `Plugins.md` documents dispatching existing tasks with `.delay()` as the intended idiom, so that — not registering a new task — is what the row means. Registering a *new* Celery task from a runtime-imported plugin is a different and much worse question: `dispatcharr/celery.py` calls `PluginManager.discover_plugins()` in `worker_process_init`, i.e. once per forked child at startup, so a task defined by a plugin imported after boot is not in an already-running worker's registry. That asymmetry — the web workers converge through `.reload_token` with no restart, the Celery workers do not — is worth writing down and is recorded as an observation whether or not the test ships. The dispatch test itself is honest and cheap (`refresh_single_m3u_account` against the test's own account, asserted through the account's own `status`/`updated_at`), but it makes the fixture plugin import product internals, and that is the first thing to drop when the goal runs long |
| **D15** | **One additive fixture change: `ApiClient.delete(url, data?)`. No change to `e2e/fixtures/seed.ts`** | `bulk-delete` carries `channel_ids` in the DELETE body and `delete()` is the one verb that does not forward `data` to the private `send()`; the fix is passing the argument through, is backward compatible, and keeps the 401 refresh-and-retry that a raw `request` call would lose. `seed.ts` is left alone deliberately: every row G14 needs is either an existing factory or a one-line POST the test should own, and `seed.ts` is the file G12, G13 and G15 are most likely to touch |
| **D16** | **G14 adds `COVERAGE.md` rows; it does not rewrite G5's or G6's** | G5's `get.php`/`xmltv.php` row records that the 403 half is untested, and `e2e/tests/seeded/xc-output.spec.ts`'s `RULING R10` header records why. Both become partly stale when G14 lands. Rewriting either means editing a file G15 owns and a row G5 owns, for no gain: a new G14 row that names the closure and cross-references the G5 row leaves both histories intact and both readable, and is the convention G9 used when it superseded G5's shape-only VOD row |
| **D17** | **Product defects are asserted correct, marked `test.fail()` with the defect named, and filed with an explicit `--repo D10Scot/Dispatcharr`** | Roadmap rule 5, unchanged. Two candidates are known before implementation: D5 (the XC per-user 401) and D8 (the three-site region-code lookup). Neither is an existing issue — the open list was read at `cf95410e` and contains neither. Do **not** re-file [#81](https://github.com/D10Scot/Dispatcharr/issues/81) (the `proxy_set_header`/`uwsgi_param` mismatch D3 depends on), [#72](https://github.com/D10Scot/Dispatcharr/issues/72) (the `ChannelProfileMembership` race, below) or [#68](https://github.com/D10Scot/Dispatcharr/issues/68) |
| **D18** | **[#72](https://github.com/D10Scot/Dispatcharr/issues/72) is not reproduced.** The bulk-ops tests create channels and profiles, but never concurrently, and never assert on the race | #72 is a latent `IntegrityError` from two unsynchronised `bulk_create` calls — `apps/channels/signals.py:create_profile_memberships` and `apps/channels/api_views.py:ChannelViewSet.create` — racing on `ChannelProfileMembership`'s `unique_together`. Provoking it deliberately means firing a profile create and a channel create at the same instant and hoping; a reproduction that fails to fire is a green test that proves nothing, and one that fires leaves a partially-populated membership set on a shared instance. It is already filed, already understood, and already has a sibling symptom in [#86](https://github.com/D10Scot/Dispatcharr/issues/86) (a flaky `channel-profiles.spec.ts` under parallel load). G14 records that it is deliberately not reproduced — the same call G3 made for [#7](https://github.com/D10Scot/Dispatcharr/issues/7), for the same reason: the damage outlives the test |

## Project topology

```
bootstrap ──┬─→ seeded    (existing) 4 workers, fullyParallel
            │      ├── tests/seeded/network-acl.spec.ts         (new, 5 tests, serial)
            │      ├── tests/seeded/epg-matching.spec.ts        (new, 4 tests)
            │      ├── tests/seeded/epg-field-copy.spec.ts      (new, 3 tests)
            │      ├── tests/seeded/ws-product-events.spec.ts   (new, 2 tests)
            │      ├── tests/seeded/m3u-filters.spec.ts         (new, 3 tests)
            │      └── tests/seeded/channel-bulk-ops.spec.ts    (new, 5 tests)
            └─→ frontend  (existing) 2 workers, file-level, 120s
                   └── tests/frontend/plugins.spec.ts           (+1 test)
```

No change to `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `e2e/package.json`
or `scripts/e2e_up.sh`. No new CI job, no branch-protection change, and the zizmor hook is never
armed.

Two tests raise their own budget with `test.setTimeout()` — the two that pay a full M3U
fetch-and-parse refresh — following G3's D9 rather than raising the project default.

## Test inventory

Twenty-three tests across six new files plus one test appended to an existing file (test 9 was
removed after G11 landed; see the row below and D6). `Tag` is
G11's taxonomy (D13).

| # | Rank | File | Test | Tag | Mechanism | Est. |
|---|---|---|---|---|---|---|
| 1 | 1 | `network-acl.spec.ts` | the server honours a client-supplied `X-Real-IP` | `@characterization` | **Premise guard, run first.** `POST /api/core/settings/check/ {key:'network_access', value:{}}` twice through the raw `request` fixture with an `Authorization` header from `api.freshAccessToken()` — once plain, once with `X-Real-IP: 203.0.113.5`. Assert the plain `client_ip` is inside `LOCAL_NETWORK_CIDRS` and the spoofed one is exactly `203.0.113.5`. Its failure message names `DISPATCHARR_TRUSTED_PROXIES` and [#81](https://github.com/D10Scot/Dispatcharr/issues/81) | 5s |
| 2 | 1 | `network-acl.spec.ts` | the `M3U_EPG` default refuses a non-local client on every surface it gates | `@contract` | Same header against `/output/m3u`, `/output/epg`, `/hdhr/discover.json` and `/hdhr/lineup.json`, through `request` (rule 11). Each must be `403` with body `{"error": "Forbidden"}`. A control request without the header must be `200`, in the same test, so a broken instance cannot pass by 403-ing everything. **No settings write** | 10s |
| 3 | 1 | `network-acl.spec.ts` | a globally blocked network is refused by `get.php` and `xmltv.php` | `@contract` | The one D2 exception. `PATCH /api/core/settings/<id>/` narrowing **only** `network_access["XC_API"]` to `LOCAL_NETWORK_CIDRS`, restored in `afterEach`; a `seed.xcUser()`'s valid credentials plus the spoofed header must give `403 {"error": "Forbidden"}` on both, and `200` without the header. Asserts `UI` is untouched in the read-back | 15s |
| 4 | 1 | `network-acl.spec.ts` | a user whose `allowed_networks` excludes them is refused by every XC endpoint | `@contract` | `seed.xcUser()`, then `PATCH /api/accounts/users/<id>/` setting `custom_properties.allowed_networks = {"XC_API": "203.0.113.0/24"}` — **no header, no global write**. `player_api.php`, `get.php` and `xmltv.php` with valid credentials must all refuse. Asserts refusal, not the status, so it stays green whichever way D5's defect is resolved | 15s |
| 5 | 1 | `network-acl.spec.ts` | *(known bug)* a network-blocked XC user is refused as **403**, not 401 | `@contract` | `test.fail()`. Same setup as #4, asserting `403` on `player_api.php` — the correct behaviour. Premise guarded *outside* the inverted block: the setup and a control `200` (before the `allowed_networks` write) are asserted normally first, so a failed seed cannot satisfy the inversion. Files D5's issue | 10s |
| 6 | 2 | `epg-matching.spec.ts` | an exact `tvg_id` match is taken before any fuzzy scan | `@contract` | `seed.upstreamEpgSource()` over a 2-channel scenario; a channel carrying one scenario channel's `tvg_id` and a deliberately unrelated `name`. `POST channels/<id>/match-epg/` → `202 {accepted: true, channel_id}`; `ws.waitForMessage('single_channel_epg_match', { where: d => d.channel_id === channel.id })` → `matched: true` with `epg_id` equal to *my* `EPGData` row. Proves the short-circuit **and** that name distance is irrelevant to it — an ID-matched channel can never reach the ML branch at any score, which makes this the safest shape in the file | 45s |
| 7 | 2 | `epg-matching.spec.ts` | a near-identical name matches by fuzzy score, with the ML branch never reached | `@characterization` | `test.setTimeout(120_000)`. A channel with **no** `tvg_id` and no `tvc_guide_stationid`, whose normalised name is within `FUZZY_SKIP_ML` (75, single path) of a scenario channel's. Detail endpoint → `single_channel_epg_match` correlated on `channel_id`, `matched: true`. The comment records the exact normalised pair, the predicted `fuzz.ratio` and which of `_get_epg_match_thresholds`'s two branches applies (D6/D6a) | 60s |
| 8 | 2 | `epg-matching.spec.ts` | a distant name matches nothing, and the ML branch is still never reached | `@characterization` | The **bulk** form with two channels, so `FUZZY_LAST_RESORT_MIN` is 50 rather than 20 — a 30-point wider safety margin against a foreign `EPGData` row scoring higher than intended. Names built from `seed.generatedName` entropy with near-zero character overlap with any plausible EPG name. Assert on the **channel rows** — both `epg_data` still `null` — rather than on the message, because a negative cannot be exactly correlated on a broadcast; the `epg_match` frame is used only as a settle signal, and the test says so. **This is the test that would pull the model download if a score were mis-predicted**, which is why D6a probes first and why it uses the higher threshold | 60s |
| 9 | — | `epg-matching.spec.ts` | **test 9 — removed** | — | The threshold asymmetry is real — `is_bulk_matching = len(channels_data) > 1`, so a one-element collection call runs the single-channel thresholds — but demonstrating it needed a pair scoring in `[75, 80)` put through the **bulk** path, and on that path `FUZZY_MEDIUM_CONFIDENCE` is 70, so `try_epg_name_match` calls `get_sentence_transformer()` for every score in that range. The test violated D6 by construction, so it is cut permanently rather than ranked on the cut list. Recorded as a `COVERAGE.md` observation instead. Numbers 10–24 are unchanged | — |
| 10 | 2+3 | `epg-matching.spec.ts` | the bulk match's terminal `epg_match` names this test's associations | `@contract` | `where: (d) => d.associations.some(a => a.channel_id === mine)` — the ids are known before the wait registers, which is what `WsListener.waitForMessage` requires. Asserts the association's `epg_data_id` is one of my `EPGData` rows and that `matches_count` counts **changed** rows only, by re-running and asserting the second run reports `0` | 60s |
| 11 | 2 | `epg-field-copy.spec.ts` | `set-names-from-epg` copies the associated `EPGData` name onto the channel | `@contract` | Channel + `set-epg` (G3's deterministic path, reused as a precondition rather than re-proved), then `POST channels/set-names-from-epg/ {channel_ids}` → `200` with `task_id` and `channel_count: 1`. Poll the channel's `name` until it equals the `EPGData` name; re-run and assert it is unchanged and `updated_count` is `0` | 30s |
| 12 | 2 | `epg-field-copy.spec.ts` | an unassociated channel is silently skipped, counting toward neither total | `@contract` | The negative the response shape hides: a channel with `epg_data: null` in the same call yields `updated_count: 0, error_count: 0` — indistinguishable from "already correct". Asserted on the terminal WS payload, because the POST returns before the task runs. This is the assertion that makes the ordering dependency on `match-epg`/`set-epg` visible | 30s |
| 13 | 2+3 | `epg-field-copy.spec.ts` | `set-tvg-ids-from-epg` copies the `tvg_id`, and emits progress under the `task_id` the POST returned | `@contract` | The channel is seeded with a deliberately wrong `tvg_id` so the write is observable rather than a coincidence. `where: (d) => d.task_id === body.task_id` — a globally unique Celery id, known before the wait registers: the exact correlation D12a ranks first, and the one thing in this goal that no parallel worker can satisfy by accident. Asserts the terminal payload's `status: "completed"` and `updated_count` | 30s |
| 14 | 3 | `ws-product-events.spec.ts` | creating a dummy EPG source emits `epg_data_created` for that source | `@contract` | The cheapest correlated product event in the application: `POST /api/epg/sources/ {source_type: "dummy", refresh_interval: 0}` fires a **synchronous** `post_save`, no Celery, no refresh. `where: (d) => d.source_id === source.id`; assert `epg_data_id` is present and the source is deleted in `afterEach` | 15s |
| 15 | 3 | `ws-product-events.spec.ts` | `channel_stats` reaches an admin socket and is silently dropped for a Streamer | `@contract` | D12b. The `ws` fixture (admin) plus a hand-built `WsListener` from `asPrincipal('streamer')`'s `freshAccessToken()` — `WsListener` is already exported, so no fixture change. Collect for one window; assert the admin saw ≥ 1 `channel_stats` (the premise guard — beat traffic, not this test's doing) and the Streamer saw **0**. The first test in this suite to open a non-admin socket, and the only coverage `ADMIN_ONLY_UPDATE_TYPES` has ever had | 25s |
| 16 | 4 | `m3u-filters.spec.ts` | a `name` filter with `exclude: true` keeps its stream out of the catalogue | `@contract` | `test.setTimeout(120_000)`. Create the account **inactive**, `POST accounts/<id>/filters/ {filter_type:'name', regex_pattern:<one generated channel name>, exclude:true, order:0}`, then activate and refresh. Assert `?m3u_account=<id>` returns the other two and not that one — a scoped count, legitimate under G3's D13 | 60s |
| 17 | 4 | `m3u-filters.spec.ts` | `exclude: false` inverts the filter to include-only | `@contract` | Same, with `exclude: false` on a pattern matching one channel: `_stream_passes_m3u_filters` returns `not exclude` on the first match, and a stream matching nothing still passes — so the assertion is that the named stream is present *and* that the unmatched streams also survive. That the semantics are first-match-wins and not a whitelist is the whole point of the test | 60s |
| 18 | 4 | `m3u-filters.spec.ts` | the lowest `order` wins when two filters match one stream | `@contract` | Two filters over one name, `order: 0` including and `order: 1` excluding. The stream must survive. **First on the cut list within this file** | 60s |
| 19 | 5 | `channel-bulk-ops.spec.ts` | `edit/bulk` applies every valid row in one call | `@contract` | Three seeded channels, one `PATCH channels/edit/bulk/` bare list changing `user_level` and `channel_number` within the worker band; read each back by id | 15s |
| 20 | 5 | `channel-bulk-ops.spec.ts` | `edit/bulk` validates before it applies | `@contract` | The same list plus one entry with no `id` → `400` with an `errors` list, and **none** of the valid rows changed. Validate-then-apply is a real contract and the only thing distinguishing this endpoint from three PATCHes | 15s |
| 21 | 5 | `channel-bulk-ops.spec.ts` | `bulk-delete` removes exactly the ids in its body | `@contract` | Four seeded channels, `DELETE channels/bulk-delete/ {channel_ids: [three of them]}` through `api.delete(url, data)` (D15) → `204`; assert the three are gone by id and the fourth is untouched. The only DELETE in the product carrying a body | 15s |
| 22 | 5 | `channel-bulk-ops.spec.ts` | `assign` renumbers exactly the ids it was given | `@contract` | `POST channels/assign/ {channel_ids, starting_number}` in the worker band; assert consecutive numbers in list order, and that a fourth seeded channel left out of the list is untouched | 15s |
| 23 | 5 | `channel-bulk-ops.spec.ts` | `reorder` moves a channel and shifts only the ones between | `@characterization` | Three channels at *n*, *n*+1, *n*+2 in the worker band. `POST channels/<third>/reorder/ {insert_after_id: <first>}`; assert all three resulting numbers, all of which are the test's own. `insert_after_id: null` is never sent (D9). **Second on the cut list overall** | 20s |
| 24 | 6 | `plugins.spec.ts` *(appended)* | a plugin action runs, and its parameters reach the plugin | `@contract` | Reuses the file's existing import-and-enable flow and its `afterEach` delete. `POST /api/plugins/plugins/<key>/run/ {action:'echo', params:{token:<generated>}}` → `200 {success: true, result: {echoed: <token>}}` — one level of wrapping, because the plugin returns a `dict` and `run_action` passes a dict through verbatim. Then the three negatives: missing `action` → `400`; a **never-imported** generated key → `404` (a key whose row exists but whose module will not load is a 500, so the 404 assertion must use a key with no row at all); and after `POST .../enabled/ {enabled: false}` → `403` | 30s |

`network-acl.spec.ts` runs its five tests in `test.describe.configure({ mode: 'serial' })`: test 3
writes `network_access` and `seeded` is `fullyParallel`, so a file is not a worker and only serial
mode confines the write to one at a time.

Estimated added wall clock: `seeded` grows by roughly eight minutes of test time spread over four
workers — dominated by the three M3U refreshes in `m3u-filters.spec.ts` and the three EPG
refreshes in the two EPG files.

## Fixture additions

Deliberately small. One method signature, one helper option, and types.

- **`ApiClient.delete(url, data?)`** (`e2e/fixtures/api.ts`) — forward the optional body to the
  existing private `send()`, as `post`/`patch` already do. Backward compatible; every current
  caller passes one argument. Needed by `bulk-delete`, which is the only DELETE in the product
  that carries a body, and required rather than optional because a raw `request` call would lose
  `ApiClient`'s 401 refresh-and-retry.
- **`buildPluginZip({ key, name, actions? })`** (`e2e/tests/frontend/plugin-zip.ts`) — an optional
  `actions` list, written into both `plugin.json` and the generated `plugin.py`, with the
  generated `run` returning a value derived from `params` so the assertion proves the parameters
  arrived. Defaults to `[]`, so G6's existing test sees a byte-identical archive.
- **`e2e/fixtures/types.ts`** — add `M3uFilter` and `M3uFilterOverrides` (evidence:
  `M3UFilterSerializer.Meta.fields`), `NetworkAccessCheck` (evidence:
  `CoreSettingsViewSet.check`'s response), `CoreSetting` (evidence: `CoreSettingsSerializer` is
  `fields = "__all__"` over a four-column model), `PluginRunResponse` (evidence:
  `PluginRunAPIView.post`), and `EpgMatchAssociation` plus the `set-*-from-epg` response shape
  (evidence: `ChannelViewSet.set_names_from_epg` and `apps/channels/tasks.py`'s payloads). Extend
  `User`/`UserOverrides` with `custom_properties` only if it is not already writable there — that
  is checked, not assumed, in the plan's first task. Each carries the evidence note the file's
  header requires; no casts at call sites.
- **`e2e/fixtures/index.ts`** — re-export the new types and extend the header inventory with
  `api.delete`'s new argument.
- **`e2e/README.md`** — a short section on the network-ACL levers (the three defaults, the
  `X-Real-IP` mechanism and its premise guard, and the standing rule that **`UI` is never
  written**), a paragraph on the ML band discipline (D6) so the next author does not
  reintroduce a middle-band name pair, and one fixture-table line.

No change to `e2e/fixtures/seed.ts`, `wait.ts`, `ws.ts`, `upstream.ts` or `page-errors.ts`.
Test 15 needs a second, non-admin socket and builds one directly — `WsListener` is already
exported from `e2e/fixtures/index.ts`, so `new WsListener(baseURL, await streamer.freshAccessToken())`
needs no fixture change. It owns its own `close()` in a `finally`, and the test says why the
`ws` fixture could not be reused: that fixture is bound to the admin token by construction.

## `COVERAGE.md` changes

Per roadmap rule 3, in the same PR. Rows are **added**; G5's and G6's are not rewritten (D16).

Eleven new flow rows (one per test group), plus these annotation rows. G11's `COVERAGE.md` at
`45a33a4a` is a `| Area | Flow | Goal | Status |` table with a separate `## Guards (G11)` table
below it; G14 appends to the first and touches the second not at all.

- **Known bug** — the XC per-user network denial returns 401 rather than 403 on all four XC
  endpoints, and `player_api.php`/`panel_api.php` log no `SystemEvent` for it; three call sites
  disagree on the contract. Asserted correct and `test.fail()`ed. (D5)
- **Known defect, characterized without a test** — `get_preferred_region_code()` at three sites,
  with the two reasons no test can pin it and the working accessor nobody calls. (D8)
- **Observation** — `channels/<id>/reorder/` shifts `channel_number` instance-wide, and
  `insert_after_id: null` makes that shift range `[1, old_number)`. Deliberately not filed. (D9)
- **Observation** — `network_access_allowed`'s global loop is unguarded against a scope value
  stored as a list or as `""`, either of which is a 500 on every gated request; deliberately not
  provoked, because the provocation is a global-row write whose blast radius is the instance.
- **Observation** — the web workers converge on a runtime-imported plugin through
  `.reload_token`, but Celery's `worker_process_init` discovery does not, so a plugin defining a
  *new* Celery task is not in an already-running worker's registry — while a newly forked
  `--autoscale` child *does* pick it up, making the failure nondeterministic rather than clean.
  Dispatching an **existing** product task with `.delay()` works from a cold-imported plugin,
  because the consumer already registered it through `autodiscover_tasks()`. (D14a)
- **Observation** — `POST /api/channels/channels/match-epg/` branches on `if channel_ids:`, so
  an **empty list** silently takes the instance-wide branch, and the endpoint validates nothing
  and has no 400 path. Recorded because it is a foot-gun for the next author, not because G14
  triggers it. (D7)
- **Observation** — three `frontend/src/WebSocket.jsx` handlers (`epg_file`, `epg_channels`,
  `epg_sources_changed`) have no backend sender anywhere in the tree; and
  `epg_tvg_id_setting_progress` has a backend sender and no frontend handler. Dead in both
  directions; recorded, not filed.
- **Observation** — `apps/channels/tests/test_epg_matching.py` does not test
  `apps/channels/epg_matching.py`. It covers `tasks.py:_match_epg_program_by_timeslot`, a DVR
  recording concern. Recorded so the next author does not read the filename as coverage.
- **Gap — unowned, post-wave-6** — every global `CoreSettings` group with behavioural effect
  (`epg_settings.epg_match_mode` advanced normalisation, `stream_settings.default_user_agent`,
  `system_settings.preferred_region`, the `network_access` scopes beyond G14's one exception),
  with the reason: instance-wide state four workers share. **Originally handed to G12; G12's
  revised spec declines it**, so the row is unowned rather than assigned. It names its
  migration-relevant member: `network_access["STREAMS"]` is the only ACL on
  `/proxy/ts/stream/<uuid>` (`apps/proxy/live_proxy/views.py:stream_ts` calls
  `network_access_allowed(request, "STREAMS")` with no user), which is the endpoint the relay
  extraction moves and the one `CLAUDE.md` says becomes an HMAC-signed URL. (D10)
- **Gap** — the per-user `allowed_networks["STREAMS"]` branch, which is the cheaper observable for
  the same scope and needs **no global write at all**:
  `apps/proxy/live_proxy/views.py:stream_xc` passes `user` to `network_access_allowed`, so setting
  one seeded user's `custom_properties.allowed_networks.STREAMS` to a CIDR no client can match
  makes the XC live route (`/<user>/<pass>/<id>`) refuse, row-scoped. It is a `streaming`-project
  test, so it belongs to whichever goal next owns those projects, not to G14. (D10)
- **Observation** — the two threshold sets are selected by request size, not by endpoint:
  `match_channels_to_epg` derives `is_bulk_matching = len(channels_data) > 1`, so **a one-element
  collection `match-epg` runs the single-channel thresholds**, while
  `run_single_channel_epg_match` hardcodes `False`. It is **not testable without entering the ML
  band**: demonstrating the asymmetry needs a score the two branches disagree about, and on the
  bulk path every score at or above 50 and below 80 reaches `get_sentence_transformer()`. This
  observation replaces a test that was specified and then cut for exactly that reason. (D6)
- **Gap** — `M3UAccountProfile.search_pattern`/`replace_pattern`, naming
  `apps/proxy/live_proxy/url_utils.py:transform_url` and the fake provider's `ScenarioLog` as the
  observable. (D11)
- **Gap** — `ServerGroup` credential pooling, naming
  `apps/m3u/connection_pool.py:group_has_capacity_for_profile` and the two-account setup it needs,
  and cross-referencing [#68](https://github.com/D10Scot/Dispatcharr/issues/68). (D11)
- **Gap** — the fake provider's `ScenarioLog` records `method`, `path` and `status` but **no
  request headers** (`e2e-upstream/src/server.ts:logRequest`), so nothing Dispatcharr sends as a
  `User-Agent` upstream is observable; closing it is one field on the log entry, and
  `e2e-upstream`'s scope.
- **Not reproduced** — [#72](https://github.com/D10Scot/Dispatcharr/issues/72), with D18's
  reasoning, cross-referencing [#86](https://github.com/D10Scot/Dispatcharr/issues/86).

## Non-goals

Each is a `COVERAGE.md` row or note, never silence.

- **A new Playwright project, a new CI job, or an isolated instance.** D1.
- **Any global `CoreSettings` write except `network_access["XC_API"]`.** D2. `UI` absolutely never.
- **Schedules Direct.** A live external service; the roadmap's own non-goals exclude it, and
  `fetch_schedules_direct()` (1,323 lines) stays uncovered.
- **The ML-enhanced matching path.** D6. Reaching it means downloading `all-MiniLM-L6-v2` at test
  time. `try_epg_name_match`'s two ML bands, `_ml_cosine_similarities` and `release_ml_models` are
  therefore uncovered, deliberately, and the row says so.
- **`match_epg_channels`** — the bare *or empty-list* form of `match-epg`. D7.
- **`channels/<id>/reorder/` with `insert_after_id: null`.** D9.
- **A non-admin socket beyond test 15's negative.** `asPrincipal` principals are shared and
  read-only (`e2e/README.md`), so nothing here changes one, and `asUser` costs a login out of
  three a minute.
- **`m3u_profile_test`**, the one inbound WebSocket message type. `WsListener` has no send path,
  and adding one would be a `ws.ts` change for a message that never reaches the group fan-out
  (`consumers.py` replies with `self.send`).
- **Reproducing [#72](https://github.com/D10Scot/Dispatcharr/issues/72).** D18.
- **`M3UAccountProfile` URL rewriting and `ServerGroup` pooling.** D11.
- **`M3UFilter.applies_to`** — dead code with semantics divergent from the live path; recorded,
  not tested, not filed, because nothing calls it.
- **`SystemEvent` assertions.** The table is truncated instance-wide on every
  `log_system_event` call.
- **The `recording_*`, `channel_stats`, `vod_stats` and `timeshift_stats` WebSocket families.**
  G13 owns the first; the rest are streaming-project observables belonging to G4's and G9's rows.
- **Resolving ADR-0002's allowlist-implies-`@characterization` sentence.** D13a records the
  tension and follows the tree's precedent; changing the ADR is G11's owner's call, and G14 edits
  no ADR.
- **The threshold asymmetry between the bulk and single matching paths.** A test for it was
  specified (9) and cut: it cannot be shown without entering the ML band D6 forbids. Recorded as an
  observation. (D6)
- **Any change to the product.** Assert correct, `test.fail()`, file with an explicit
  `--repo D10Scot/Dispatcharr`.

## Risks

- **The `X-Real-IP` mechanism is the design's one environmental assumption, and it has not been
  run.** It rests on three separate readings — that `REMOTE_ADDR` inside the container is the
  Docker bridge address (private, therefore trusted), that nginx's bare `include uwsgi_params`
  passes client headers through, and that `DISPATCHARR_TRUSTED_PROXIES` is unset. Each is verified
  in source; none is verified in a running container from this worktree. **Mitigation:** D3a turns
  it into test 1's premise guard, so a wrong reading fails as "the server saw 172.x, not
  203.0.113.5" rather than as a mysterious 200. **Fallback if it is wrong:** tests 1–3 become a
  gap row, and tests 4 and 5 — the per-user `allowed_networks` path, which needs no header at all
  — still ship and still close the more interesting half, because that is where the defect is.
  The plan's first task probes this before anything is written.
- **A mis-predicted `fuzz.ratio` silently pulls a ~90 MB model download into CI.** The symptom is
  a very slow first run, not a failure, so it can survive review. **Mitigation:** D6a's probe
  measures the real score against a live container before the tests exist, and the comment at each
  assertion records the band and the number so a later edit to a name is visibly a threshold
  decision. **Second line of defence:** if the probe shows a pair cannot be placed cleanly outside
  the bands, the test asserts the exact-`tvg_id` path (test 6) only and the fuzzy rows become a
  gap — the model download is never worth it.
- **Test 3's `XC_API` narrowing could leak** if its `afterEach` does not run. The blast radius is
  argued to zero in D2 (the narrowed value denies only spoofed non-local addresses, which nothing
  else sends), but the argument is the mitigation, not a guarantee. Belt and braces: the restore
  runs in `afterEach`, not a body-level `finally` — Playwright tears a test down mid-`await` on
  timeout and code after that point does not reliably run, which is the reasoning
  `plugins.spec.ts` and `settings.spec.ts` already record.
- **Cross-worker EPG aliasing, and it has no clean guarantee.** `_active_epg_fuzzy_queryset`
  filters on `epg_source__is_active=True` and **nothing else** — no account, group, profile or
  user scoping — so every `EPGData` row of every active source on the instance is a candidate for
  a G14 channel, and G3's `epg-ingest.spec.ts` creates real active sources in the same project.
  The only *guarantee* would be deactivating every other fixture's source, which G14 cannot do.
  **Mitigation, which is a mitigation and not a proof:** generated names carry per-worker entropy;
  every positive assertion names *my* `epg_data_id` rather than merely asserting non-null; and the
  exposed test — the no-match one (8) — uses the **bulk** threshold (`LAST_RESORT_MIN` 50, not the
  single path's 20), buying a 30-point margin, with names chosen for near-zero character overlap.
  That margin matters more than it looks: `fuzz.ratio` is character-level, so two *unrelated*
  strings routinely score in the twenties and a 20-point floor is not a safe one. The test names
  this in a comment.
- **`seeded` is `fullyParallel`, so a file is not a confinement boundary.** This bit the design
  once already (test 3's serial mode) and is the thing most likely to be forgotten by whoever adds
  a sixth test to `network-acl.spec.ts`. The plan writes it into the file's header, not just here.
- **Six shared files collide with G12, G13 and G15** — `COVERAGE.md`, `README.md`, `types.ts`,
  `index.ts`, `api.ts` and `tests/guards/allowlist.ts`. **Mitigation:** additive only, appended at
  the end of each existing list; no reordering, no reflowing a neighbouring paragraph. G14's
  `api.ts` edit is one signature and is the only one that is not a pure append. `allowlist.ts` is
  the newest collision risk: G12 owns `tests/lifecycle/`, which is already on two capability lists,
  so both goals may append to the same file in the same wave.
- **The tag guard fails closed, and one spec shape in this goal is the shape it rejects.**
  `e2e/tests/guards/tags.spec.ts` requires exactly one recognised tag on every test declaration and
  reports anything it cannot parse as `unverifiable`, which fails. The rejected shape is a details
  object passed **by reference** — so a `const TAG = { tag: '@contract' }` hoisted to the top of a
  file to save repetition breaks every test in it. **Mitigation:** the tag is written inline on each
  `test(` call in all seven files. `network-acl.spec.ts` is the one to watch, because it already
  carries a `test.describe.configure({ mode: 'serial' })` and the temptation is to fold the tag into
  a describe alongside it; `configure` takes no tag, and a describe that did would have to carry an
  inline literal.
- **Test 3 fails `global-mutation.spec.ts` until `allowlist.ts` is edited, and the edit is the
  review.** The guard is a `toEqual` comparison, so the omission fails loudly rather than silently —
  which is the good case. The risk is the opposite one: adding the entry without ADR-0003's three
  sentences (which group, why nothing else reads it, how teardown restores it) turns a reviewable
  decision back into an edit nobody sees. D13a states them; the diff must carry them.
- **`WsListener` correlation is a race in principle.** A task that starts, runs and completes
  before the wait registers leaves nothing to consume. In practice the POST returns before Celery
  picks the task up, and the listener *queues* anything that arrived before the wait — messages
  are consumed, not replayed, but a message with no waiter is held for the next matching one — so
  the ordering holds. Tests 10, 13 and 14 still register their waits immediately after reading the
  correlating id and before any further `await`, and say why in a comment.
- **Test 15's negative can go vacuous.** It asserts a Streamer socket receives zero
  `channel_stats`, and the traffic it depends on is a beat task, not the test's own doing. If
  `fetch_channel_stats` is not running, the Streamer legitimately sees zero and so does the admin,
  and the test passes for the wrong reason. **Mitigation:** the admin socket's `>= 1` assertion is
  the premise guard and runs on the same window, so an idle instance fails the test saying "no
  `channel_stats` traffic in the window" rather than passing.
- **Test 15 owns a socket the harness did not create.** A hand-built `WsListener` is not torn down
  by fixture teardown, and a leaked one keeps a Node timer alive past the test. It closes in a
  `finally`, which is sufficient here because the test does no page work and cannot be torn down
  mid-`await` the way a browser test can.
