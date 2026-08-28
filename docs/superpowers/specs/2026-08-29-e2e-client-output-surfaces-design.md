# G5 — Client Output Surfaces

**Date:** 2026-08-29
**Status:** Approved, ready for implementation planning
**Wave:** 2 (G1 landed at `a0c99cdd`, G2 at `c188aab6`, G4 at `6e71ca20`; G5 branches from `main` at `4a2ad2fd`)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Siblings in flight:**

- **G3** (content sources & ingest) collides on `e2e/fixtures/seed.ts`, `e2e/fixtures/types.ts`,
  `e2e/fixtures/index.ts`, `e2e/COVERAGE.md` and `e2e/README.md`. G5 adds two factories
  (`channelGroup`, `xcUser`) and G3 will add its own; every collision is additive and at the end
  of an existing list. G3 also owns "Channel groups and Channel Profiles" as a *test* row — G5
  adds only the factory, not that coverage.
- **G6** (frontend surfaces) collides on `e2e/COVERAGE.md` only.
- **G7** (deployment lifecycle, branch unmerged) edits `e2e/playwright.config.ts`,
  `.github/workflows/e2e-tests.yml` and `scripts/e2e_up.sh`. **G5 edits none of those three**
  (see D2), so the two goals overlap only on `e2e/COVERAGE.md` and `e2e/README.md`.
- **G8** (provider-side XC / VOD / catch-up emulation) does not exist yet and depends on this
  goal. The boundary between them is D1 and the Non-goals section; G8's spec should start there.

## Goal

Prove that everything Dispatcharr hands a *client* — an M3U playlist, an XMLTV guide, an
HDHomeRun lineup, an Xtream Codes catalogue — is well-formed, correctly scoped to whoever asked
for it, and actually usable: at least one advertised stream URL must deliver bytes.

This is the surface every consumer of the product touches. Plex, Jellyfin, TiviMate and every
XC client see nothing of `live_proxy` except the URL one of these four surfaces gave them. And
it is the surface where authorization is decided: the `user_level` filter is copy-pasted across
eight sites, one of them is wrong, and nothing observes any of them from outside.

## Current state

Nothing under `e2e/tests/` touches `/output/`, `/hdhr/` or any XC endpoint. Every G5 row in
`e2e/COVERAGE.md` — eleven, after the G8 split re-scoped the original seven — is `todo`, and the
one `known-bug` row assigned to G5 (issue
[#12](https://github.com/D10Scot/Dispatcharr/issues/12), token refresh returning 500 instead of
401 for a deleted user) is unpinned.

Backend unit coverage exists — `apps/output/tests/test_views.py` exercises the XC actions
against a test database — but it never renders a playlist a client then fetches, never checks
that an emitted URL resolves, and never crosses the container boundary. `apps/hdhr` has no test
file at all under `e2e/` and its lineup has never been fetched by anything.

## Verified facts this design rests on

Cited by symbol or filename, never by line number — line numbers in this repo drift, and an
earlier spec in this series shipped four wrong ones. Every row below was read out of the tree at
`4a2ad2fd`.

| Fact | Source | Consequence |
|---|---|---|
| `/output/m3u` and `/output/epg` both accept an **optional trailing profile name**: `re_path(r"^m3u(?:/(?P<profile_name>[^/]+))?/?$")` and the same for `epg` | `apps/output/urls.py` | `/output/m3u/<name>` is a real route, and an unknown name raises `Http404` rather than returning an empty playlist |
| **`m3u_endpoint` and `epg_endpoint` are never called with a user.** The URLconf passes only `profile_name`; the `user=None` parameter has exactly one non-default caller each — `xc_get` and `xc_xmltv` | `apps/output/urls.py`, `apps/output/views.py` (`xc_get`, `xc_xmltv`) | `/output/m3u` and `/output/epg` are **anonymous and unfiltered**: `base_qs = Channel.objects.select_related(...)`, no `user_level`, no adult filter. There is no authorization matrix to test on these two routes. See D6 |
| The four HDHomeRun views are `permission_classes = [AllowAny]` and take no user. `LineupAPIView` builds `Channel.objects.all()` for the bare route, or a Channel-Profile-scoped queryset for `/hdhr/<channel_profile>/lineup.json` | `apps/hdhr/api_views.py` (`DiscoverAPIView`, `LineupAPIView`, `LineupStatusAPIView`, `HDHRDeviceXMLAPIView`) | HDHR has **no principal at all**, so it can apply no per-user filter of any kind. Not a missing `hide_adult_content` clause — a missing principal. See D11 |
| **There is not one occurrence of `hide_adult_content` anywhere under `apps/hdhr/`.** It is honoured in `apps/output/views.py`, `apps/output/epg.py`, `apps/epg/serializers.py`, `apps/epg/api_views.py`, `apps/channels/api_views.py` and `apps/vod/api_views.py` | grep over `apps/` | Confirms the CLAUDE.md entry, and locates it: the gap is structural, not a forgotten line |
| `network_access_allowed(request, "M3U_EPG")` defaults to `LOCAL_NETWORK_CIDRS` — `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `::1/128`, `fc00::/7`, `fe80::/10`. Every other key defaults to `0.0.0.0/0` | `dispatcharr/utils.py` (`network_access_allowed`, `LOCAL_NETWORK_CIDRS`) | The Docker bridge and loopback are both inside that default, so **no test needs to widen an ACL**. Mutating that global `CoreSettings` row from `seeded` would be a cross-worker hazard; it is unnecessary |
| **There is no `xc_username` custom property.** `xc_get_user` does `get_object_or_404(User, username=…)` and then compares `custom_properties["xc_password"] != password`. `stream_xc` and `apps/timeshift/views.py`'s `_authenticate_user` do the same | `apps/output/views.py` (`xc_get_user`), `apps/proxy/live_proxy/views.py` (`stream_xc`), `apps/timeshift/views.py` | The XC username **is** the Django username. `seed.xcUser()` sets one custom property, not two. The `xc_username` locals in `apps/timeshift/views.py` are *provider* credentials from `get_transformed_credentials`, unrelated |
| XC authentication is **query-string credentials with no token**, and is not throttled | `apps/output/views.py` (`xc_get_user`), `dispatcharr/settings.py` login throttle scope | The whole XC authorization matrix costs **zero logins**. This is what makes D5's "no new principals" affordable rather than merely tidy |
| `xc_get_user` returns `None` for a wrong password (→ `401`) but lets `get_object_or_404` raise for an **unknown username** (→ `404`) | `apps/output/views.py` (`xc_get_user`) | The two failures are distinguishable to an unauthenticated caller. See D10, defect 5 |
| `xc_get_live_categories` filters `"channels__user_level": 0` in its has-profiles branch, while its no-profiles branch and its admin branch both use `channels__user_level__lte=user.user_level` | `apps/output/views.py` (`xc_get_live_categories`) | Reachable only by a **non-admin with at least one Channel Profile assigned**. Symptom: a channel visible in `get_live_streams` whose category is missing from `get_live_categories`. See D10, defect 1 |
| `stream_xc` applies `user_level__lte` and Channel Profile membership but **no `is_adult` and no `hidden_from_output` filter**, then calls `stream_ts(request._request, str(channel.uuid), user, …)` | `apps/proxy/live_proxy/views.py` (`stream_xc`) | A channel a `hide_adult_content` user cannot list is still streamable at `/live/<user>/<pass>/<id>`. This is CLAUDE.md's "unlistable yet still streamable", located precisely. See D10, defect 2 |
| Every listing path excludes hidden channels with `.exclude(hidden_from_output=True)`; `stream_xc` does not | `apps/output/views.py`, `apps/output/epg.py`, `apps/hdhr/api_views.py` vs `apps/proxy/live_proxy/views.py` | A second, adjacent gap in the same function. Recorded, not tested — see Non-goals |
| `xc_player_api` dispatches ten actions and falls through to `xc_get_info` for anything else, including `get_account_info` and unknown actions | `apps/output/views.py` (`xc_player_api`) | An unknown action returns the `user_info`/`server_info` envelope with `200`, not an error. Deliberate provider-compatibility behaviour, worth pinning |
| `get_live_streams` returns a `StreamingHttpResponse` with `content_type="application/json"`, streamed from `_xc_stream_live_streams`; the other nine actions return `JsonResponse` | `apps/output/views.py` (`xc_player_api`, `_xc_stream_live_streams`) | The body is still valid JSON, but it arrives incrementally. Read the whole body before parsing |
| `get_short_epg` and `get_simple_data_table` both route to `xc_get_epg`, which raises `Http404` when `stream_id` is missing or non-integer | `apps/output/views.py` (`xc_get_epg`) | Both actions **require** `?stream_id=<channel.id>` — the numeric Channel PK, not the UUID |
| `xc_get_epg` base64-encodes `title` and `description`, and returns `{"epg_listings": [...]}` with `start`/`end` as `%Y-%m-%d %H:%M:%S` UTC strings plus `start_timestamp`/`stop_timestamp` | `apps/output/views.py` (`xc_get_epg`) | The title assertion is a base64 decode, not a string compare |
| **A channel with no `epg_data` still produces programmes.** `generate_epg` routes it to `dummy_program_list` → `generate_dummy_programs`, and `xc_get_epg` does the same in its `else` branch | `apps/output/epg.py` (`generate_epg`, `generate_dummy_programs`), `apps/output/views.py` (`xc_get_epg`) | The EPG rows need **no EPG source and no G3 ingest**. A plain `seed.channel()` yields `<programme>` elements and a non-empty `epg_listings` |
| `get_vod_categories`, `get_vod_streams`, `get_series_categories` and `get_series` all return a list, empty on a fresh instance | `apps/output/views.py` | Four actions assert `[]`. See D12 |
| `get_series_info` and `get_vod_info` raise `Http404` when their id is missing or unknown — `if not series_id: raise Http404()`, and `M3UMovieRelation…first()` falling through to `raise Http404()` | `apps/output/views.py` (`xc_get_series_info`, `xc_get_vod_info`) | These two return **404, not `[]`**. Asserting an empty body would fail. See D12 |
| `generate_m3u` caches its rendered body in the Django cache for **2 seconds**, keyed on `profile:username:request.GET.urlencode():origin` | `apps/output/views.py` (`generate_m3u`) | Any distinct query parameter busts it, and unknown parameters are ignored by the generator. Low risk, but real |
| `generate_epg` caches through `stream_cached_response` with `DEFAULT_CACHE_TTL = 300`, keyed on `profile:username:d=:p=:logos=:tvgid=:origin=` — **the raw query string is not in the key** | `apps/output/epg.py` (`generate_epg`), `apps/output/streaming_chunk_cache.py` | A five-minute Redis chunk cache stands between a newly seeded channel and `/output/epg`. This is the single biggest correctness hazard in G5. See D7 |
| That cache is invalidated only when a channel's **`epg_data`** changes (`refresh_epg_programs`, `cache_previous_override_epg`) or an EPG import runs. Creating a plain channel invalidates nothing | `apps/channels/signals.py`, `apps/epg/tasks.py` | Seeding a channel does **not** make `/output/epg` fresh. Confirms D7 is mandatory, not defensive |
| `ChannelSerializer.create` auto-assigns a **"Default Group"** when `channel_group` is omitted | `apps/channels/serializers.py` | Every `seed.channel()` today lands in one group shared by all four workers. A category-level assertion needs its own group. See D9 |
| `ChannelProfile` creation adds a membership for every existing channel (`create_profile_memberships`), and `ChannelViewSet` create adds the new channel to **all** profiles unless `channel_profile_ids` is passed. `ChannelProfileMembership.enabled` defaults to `True` | `apps/channels/signals.py`, `apps/channels/api_views.py`, `apps/channels/models.py` | Either creation order works, and no explicit membership wiring is needed. It also means a seeded Channel Profile contains **every other worker's channels** — never assert its size |
| `build_absolute_uri_with_port` derives host and port from `X-Forwarded-Host`/`X-Forwarded-Port`, falling back to the `Host` header; no `CoreSettings` override participates | `core/utils.py` (`build_absolute_uri_with_port`, `get_host_and_port`) | Emitted URLs carry the host the test used, so a URL taken out of the M3U is fetchable from the test process |
| The M3U `#EXTINF` line carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally `tvc-guide-stationid`, and `group-title` — and **nothing else**. There is no `catchup=` attribute | `apps/output/views.py` (`generate_m3u`) | Catch-up is advertised only through XC `tv_archive` on `_xc_channel_entry`. Recorded as a G8 gap in `COVERAGE.md` |
| `ApiClient.send` retries once through a token refresh **on any 401** | `e2e/fixtures/api.ts` | XC rejects bad credentials with 401, so driving XC through `api` triggers a pointless refresh and can throw on a refresh failure instead of returning the 401 under test. See D3 |
| `StreamClient.open(path)` accepts an absolute URL (`path.startsWith('http')`) as well as a path | `e2e/fixtures/stream-client.ts` | A URL lifted verbatim out of the M3U can be streamed without reconstruction — which is the point of the row |
| `ChannelOverrides` already carries `is_adult`, `user_level`, `hidden_from_output`, `channel_group_id` and `is_catchup`; `UserOverrides` already carries `custom_properties` and `channel_profiles` | `e2e/fixtures/types.ts` | Both known-bug scenarios and the whole matrix are expressible with the existing override types. Only two new factories are needed |
| `/api/channels/groups/` is registered as `channel-group`, and `ChannelGroupSerializer` exposes exactly one writable field, `name` | `apps/channels/api_urls.py`, `apps/channels/serializers.py` | `seed.channelGroup()` is a three-line factory with an empty overrides type, mirroring `channelProfile()` |
| `e2e/package.json` has no XML parser and no M3U parser; its runtime deps are `@playwright/test`, `@types/node`, `@types/ws`, `typescript`, `ws` | `e2e/package.json` | Parsing is hand-rolled, and XMLTV well-formedness is proved with the browser's own `DOMParser`. See D8 |
| `.github/workflows/e2e-tests.yml`'s matrix is `[pristine, seeded, streaming, streaming-failover, streaming-greybox]` — already five, one per project in `playwright.config.ts` | `.github/workflows/e2e-tests.yml`, `e2e/playwright.config.ts` | G5 adds no project, so it adds no matrix entry and touches no workflow. (`e2e/README.md`'s CI section still says "three-job matrix" — stale since G4; G5 corrects that line.) |
| `seeded` runs 4 workers against one shared container; `streaming` runs 2 | `e2e/playwright.config.ts` | Every M3U, EPG and lineup a G5 test fetches contains **every other worker's channels**. Roadmap rule 4 is not advisory here, it is the whole design constraint |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **G5 is server-side output surfaces only. The XC / VOD / catch-up provider emulation, and every test that needs it, become G8.** | The roadmap gave G5 a test goal *and* a build. Only the catch-up row needed the build: `catchup_proxy` constructs its upstream URL from the account's Xtream catch-up template, so it has nothing to point at until the fake provider speaks XC. G2 was the programme's longest goal precisely because it was a build; folding a second one into G5 would repeat that and block a dozen cheap server-side tests behind it. The line: **G5 asserts what Dispatcharr emits from its own database; G8 asserts what it does with an upstream that speaks XC.** Rejected: keeping the build in G5 and cutting the server-side rows to fit — that trades the goal's whole value for its hardest row |
| D2 | **No new Playwright project and no CI matrix job.** Listing and authorization rows go in the existing `seeded` project; the two rows that need bytes go in the existing `streaming` project | Everything except two rows is fast HTTP against seeded database rows — exactly what `seeded` is for, at 4 workers. Consequence, stated explicitly because it is the point: **G5 edits neither `e2e/playwright.config.ts` nor `.github/workflows/e2e-tests.yml`.** It therefore raises no zizmor-hook exposure (that hook blocks on *every* finding in an edited workflow, legacy included) and does not collide with the unmerged G7 branch, which edits both. Rejected: an `output` project, which would buy isolation nothing here needs and cost a sixth container per CI run |
| D3 | **Client-facing output surfaces are driven through Playwright's built-in `request` context, not the `api` fixture.** `api` is used only for seeding and for admin reads | Two reasons, and the second is a live trap. Fidelity: no real client of these surfaces carries a bearer token — Plex and TiviMate authenticate with a URL, which is exactly why `stream_ts` is `AllowAny` — so a test that sends one is not testing what ships. Correctness: `ApiClient.send` retries once through a token refresh **on any 401**, and XC answers bad credentials with 401, so the "bad credentials are rejected" row would silently spend a refresh and could throw a refresh error instead of returning the 401 it is asserting on |
| D4 | **`seed.xcUser()` sets one custom property, `xc_password`, and the XC username is the Django username** | There is no `xc_username` property anywhere in the product. `xc_get_user`, `stream_xc` and timeshift's `_authenticate_user` all look the user up by `username` and then compare `custom_properties["xc_password"]` with `!=`. A fixture inventing an `xc_username` key would create a credential the product never reads, and the tests would pass by coincidence or fail opaquely |
| D5 | **No new principals.** `asPrincipal` provides `user_level` 0 and 1, the bootstrap admin is 10, and that is the entire JWT matrix. Every XC principal is a `seed.xcUser()` | Adding a principal costs a login from a budget of three per minute that the cold bootstrap path already spends in full, and it costs it on **every** run forever. The XC matrix needs no principals at all: XC authentication is query-string credentials against an unthrottled endpoint, so the whole matrix costs zero logins at any worker count. The single JWT login G5 spends is issue #12's, budgeted at one per run and commented at the call site as `e2e/README.md` requires |
| D6 | **The `user_level` authorization matrix is asserted on the Xtream surface only, because it is the only output surface with a principal.** `/output/m3u`, `/output/epg` and the HDHR lineup get a *characterization* test instead, pinning that they are unauthenticated and unfiltered by design | The roadmap said "the matrix across all four surfaces". Three of the four have no user: the `/output/*` URLconf passes only `profile_name`, and the HDHR views are `AllowAny`. Writing a matrix against them would assert a filter that does not exist and cannot be made to exist without a principal. The honest replacement is a test that says so out loud — which also goes red the day someone adds authentication or narrows the `M3U_EPG` default, both of which are changes a reader would want announced |
| D7 | **Every `/output/epg` assertion varies a cache-key input.** The anonymous route passes a per-test `?days=<n>`; the XC route (`xmltv.php`) needs nothing, because the key already contains the username and `seed.xcUser()` generates a fresh one per test | `stream_cached_response` caches the rendered XMLTV in Redis for **300 seconds**, and the key contains `profile:username:d=:p=:logos=:tvgid=:origin=` — *not* the raw query string, so an arbitrary `?e2e=` parameter does not bust it. Creating a channel invalidates that cache only when `epg_data` is involved, which a plain seeded channel is not. Without this a test seeds a channel and reads a five-minute-old body that predates it — failing, or worse, poisoning every later EPG test in the run. `days` is clamped to 0–365 and only widens the programme window, so it is a safe key to vary. Rejected: polling until fresh (the `seeded` timeout is 30s, the cache is 300s) and giving the seeded channel EPG data to force invalidation (that is G3's ingest path, not G5's) |
| D8 | **XMLTV well-formedness is proved once with the browser's `DOMParser` via `adminPage`; element extraction is a hand-rolled parser in `e2e/fixtures/parse.ts`** | `e2e/package.json` has no XML dependency, and adding one is a supply-chain decision disproportionate to reading a handful of elements. A regex parser cannot honestly support the claim "valid XMLTV", but the `seeded` project already has a browser: `page.evaluate` on `new DOMParser().parseFromString(text, 'application/xml')` and a check for `parsererror` is a real well-formedness verdict from a real XML parser. Everything after that — `<channel id>`, `<display-name>`, `<programme channel=>` — is extracted by the shallow parser, whose limits are stated in its own header |
| D9 | **G5 adds `seed.channelGroup()`** | `ChannelSerializer.create` auto-assigns a shared "Default Group" when none is given, so every worker's channels land in one group. `get_live_categories` returns groups, and its known-bug row asserts that a specific group is present or absent — impossible against a group four workers are writing into. This is a factory G3 would otherwise add; landing it here first shrinks nobody's work and both goals gain it |
| D10 | **Five product defects are asserted correct, marked `test.fail()` with the defect named in a comment, and filed with `gh issue create --repo D10Scot/Dispatcharr` — never patched** | Roadmap rule 5. The five: (1) `xc_get_live_categories`'s exact-match `"channels__user_level": 0`; (2) `stream_xc` omitting the adult filter, so an unlistable channel is streamable; (3) the HDHomeRun endpoints applying no authorization at all; (4) inherited issue [#12](https://github.com/D10Scot/Dispatcharr/issues/12); (5) XC distinguishing an unknown username (404) from a wrong password (401). Defect 5 was found while writing this spec and is not in the agreed brief — it is included because rule 5 applies to what the tests hit, and the XC handshake row hits it directly; strike it if the programme wants a narrower G5 |
| D11 | **Defects 2 and 3 are two issues, not one** | They read as halves of CLAUDE.md's "hidden channels are unlistable yet still streamable", but they have different mechanisms and different fixes. `stream_xc` **has** the principal in hand and applies `user_level` and Channel Profile membership to it; it omits one filter clause, and the fix is that clause. The HDHomeRun views have **no principal at all** — they are `AllowAny` and take no user — so `hide_adult_content`, a per-user preference, is not merely missing there but inapplicable; the fix is a design decision about how HDHR should authenticate, or an explicit statement that the `M3U_EPG` ACL and the `<channel_profile>` path segment are the whole of its access control. Filing them together would produce an issue no single change closes. The tests, the issues and `COVERAGE.md` all follow this split |
| D12 | **The four XC list actions assert `[]`; the two XC detail actions assert `404`** | `get_vod_categories`, `get_vod_streams`, `get_series_categories` and `get_series` return lists that are empty on a fresh instance. `get_series_info` and `get_vod_info` raise `Http404` for a missing or unknown id — asserting an empty body against those would fail. An empty catalogue is the state every fresh instance is in, so this is a real assertion about six code paths not erroring, not a placeholder; G8 deepens all six once there is content |
| D13 | **XC credentials are generated per test from the seeder's run token and thrown away with the user** | `e2e-upstream/README.md` warns, in a note written for this goal, that a fixed meaningful credential reused across runs must not assume privacy on either side: Dispatcharr logs full provider URLs including `?password=` at INFO, and `.github/workflows/e2e-tests.yml`'s failure step prints `docker logs dispatcharr-e2e` into the CI log. G5 introduces credentials that travel in query strings across four surfaces, so it is exactly the goal that warning anticipated. A per-test generated password has no value outside the run that made it, which keeps both paths harmless. It also makes D7's XC cache-key uniqueness free |
| D14 | **No assertion on a global count or an unfiltered list.** Every assertion locates the worker's own seeded rows by the name `seed` generated | Roadmap rule 4, and the constraint that shapes this goal more than any other. Four workers share one container, a seeded Channel Profile automatically contains every other worker's channels, and the M3U, the XMLTV guide and the HDHR lineup each render **every channel on the instance**. "The playlist has N entries" is not a weaker assertion here, it is a false one |
| D15 | **One M3U-advertised URL is streamed, not all of them** | Streaming *n* URLs costs *n* upstream connections and proves nothing the first did not: the URLs are rendered by one f-string over one queryset, so if one resolves and delivers, the construction is right. The remaining URLs are validated structurally — origin, `/proxy/ts/stream/` prefix, a UUID matching the channel the test seeded. That single byte-level test lives in `streaming`, where the long timeout and the fake provider already are |

## Project topology

```
bootstrap ──┬─→ seeded      (existing) 4 workers   +9 specs
            └─→ streaming   (existing) 2 workers   +2 specs
```

No new project, no new CI matrix job, no change to `e2e/playwright.config.ts`,
`.github/workflows/e2e-tests.yml` or `scripts/e2e_up.sh`.

The two `streaming` specs are there for one reason each: they need real bytes through
`/proxy/ts/stream/`, which needs the fake upstream provider and a timeout longer than `seeded`'s
30 seconds. Everything else is a JSON or text body over HTTP and belongs where the other fast
tests are.

## Test inventory

Nineteen tests across eleven files: fourteen asserting behaviour, five `test.fail()` rows
pinning defects.

| # | COVERAGE row | Project | File | Mechanism |
|---|---|---|---|---|
| 1 | `/output/m3u` parses | `seeded` | `output-m3u.spec.ts` | `parseM3u` the body; assert the `#EXTM3U` header carries `x-tvg-url` and `url-tvg` pointing at `/output/epg`; locate the seeded channel by its generated name; assert its URL is `<origin>/proxy/ts/stream/<channel.uuid>` |
| 2 | `/output/m3u/<profile_name>` scopes to membership | `seeded` | `output-m3u.spec.ts` | Two seeded channels, one disabled in the profile via `PATCH /api/channels/profiles/<profile_id>/channels/<channel_id>/` with `{enabled: false}` (`UpdateChannelMembershipAPIView`); assert the enabled one is present and the disabled one absent; an unknown profile name returns 404 |
| 3 | `/output/epg` is valid XMLTV | `seeded` | `output-epg.spec.ts` | Per-test `?days=`; `DOMParser` well-formedness via `adminPage`; a `<channel>` for the seeded channel and at least one `<programme>` referencing that id, from the dummy generator |
| 4 | HDHomeRun discovery and device XML | `seeded` | `hdhr.spec.ts` | `discover.json` carries `FriendlyName`, `DeviceID`, `TunerCount` and a `LineupURL` that resolves; `device.xml` parses as XML and its `<LineupURL>` agrees; `lineup_status.json` has the four documented keys |
| 5 | HDHomeRun lineup | `seeded` | `hdhr.spec.ts` | The seeded channel appears with `GuideNumber`, `GuideName` and a `/proxy/ts/stream/<uuid>` URL; `/hdhr/<channel_profile>/lineup.json` scopes to membership; an unknown profile returns `[]`, not 404 |
| 6 | Xtream authentication handshake | `seeded` | `xc-auth.spec.ts` | Valid credentials return `user_info` (`auth: 1`, `status: "Active"`, `max_connections`, `allowed_output_formats`) and `server_info` (`url`, `port`, `timezone: "UTC"`, `timestamp_now`); wrong password → 401; a user with no `xc_password` → 401; an unknown action returns the same envelope with 200 |
| 7 | Xtream live catalogue | `seeded` | `xc-live.spec.ts` | `get_live_categories` contains the seeded group; `get_live_streams` (streamed JSON — read the whole body) contains the seeded channel with `stream_id === channel.id`, `stream_type: "live"`, `category_id` equal to the group id; `panel_api.php` returns the same catalogue under `categories.live` and `available_channels`. **This is also row 15's positive control**, so drive it with an XC user that has one Channel Profile assigned and a `user_level: 0` channel — the exact shape row 15 fails on, differing only in the channel's level |
| 8 | Xtream short EPG and data table | `seeded` | `xc-live.spec.ts` | `get_short_epg?stream_id=<channel.id>` returns `epg_listings` with base64 `title` decoding to the dummy programme's; `get_simple_data_table` returns the same shape plus `now_playing`; omitting `stream_id` returns 404 |
| 9 | Xtream VOD and series on an empty catalogue | `seeded` | `xc-vod-empty.spec.ts` | `get_vod_categories`, `get_vod_streams`, `get_series_categories`, `get_series` each return `[]` with 200; `get_vod_info` and `get_series_info` return 404 for a missing and for an unknown id. Six paths, none of them 500 |
| 10 | `get.php` and `xmltv.php` | `seeded` | `xc-output.spec.ts` | `get.php` returns an M3U whose entries carry XC-style `/live/<username>/<password>/<channel.id>` URLs and whose `x-tvg-url` points at `xmltv.php`; `xmltv.php` returns XMLTV for that user's channels. Both reject bad credentials with 401 and a blocked network with 403 |
| 11 | Authorization matrix by `user_level` | `seeded` | `output-authorization.spec.ts` | Three channels at `user_level` 0, 1 and 10; three seeded XC users at the same three levels; assert each principal's `get_live_streams`, restricted to the three seeded `stream_id`s, is exactly the set at or below its level, and that `get_short_epg` for a channel above its level returns 404. The refusal is asserted on `get_short_epg`, not on `stream_xc`: these channels have no `Stream` rows, so a `stream_xc` request would fail for two possible reasons and prove neither. `stream_xc`'s filtering is row 16's job, where there is a real upstream to succeed against |
| 12 | `hide_adult_content` across the XC listing paths | `seeded` | `output-authorization.spec.ts` | One adult and one non-adult seeded channel; an XC user with `custom_properties.hide_adult_content: true`; assert the adult channel is absent from `get_live_streams`, from `get.php`'s M3U, from `xmltv.php`'s guide, and that `get_short_epg` for it returns 404 |
| 13 | The three unauthenticated surfaces, characterized | `seeded` | `output-authorization.spec.ts` | `/output/m3u`, `/output/epg` and `/hdhr/lineup.json` all return the `user_level` 10 channel from row 11 to a caller with no credentials of any kind. Pins the actual model; goes red if authentication is ever added |
| 14 | One advertised URL delivers bytes | `streaming` | `output-m3u-stream.spec.ts` | Seed an upstream-backed channel with `seed.upstreamChannel`; fetch `/output/m3u`; take **its** entry's URL verbatim; `streamClient.open(url)`; `expectTsAligned(await readPackets(200))`; assert the provider logged exactly one open |
| **15** | **Known bug:** category of a visible channel is missing | `seeded` | `xc-live.spec.ts` | Own group, one channel at `user_level: 1`, an XC user at level 1 with one Channel Profile assigned. Assert the group appears in `get_live_categories` while the channel appears in `get_live_streams`. `test.fail()` — `xc_get_live_categories`'s has-profiles branch matches `user_level` exactly. Row 7 is the positive control: same shape, `user_level: 0` channel, passes today |
| **16** | **Known bug:** hidden channel is streamable | `streaming` | `hidden-channel-streamable.spec.ts` | Adult, upstream-backed channel; XC user with `hide_adult_content: true`. Assert it is absent from `get_live_streams` **and** that `/live/<user>/<pass>/<id>` refuses. `test.fail()` — `stream_xc` applies no `is_adult` filter, so today it streams |
| **17** | **Known bug:** HDHR applies no authorization | `seeded` | `hdhr.spec.ts` | A `user_level: 10`, `is_adult: true` channel appears in the bare `/hdhr/lineup.json` to an unauthenticated caller. Assert it does not. `test.fail()` — the HDHR views are `AllowAny` with no principal. Distinct issue from row 16 (D11) |
| **18** | **Known bug:** [#12](https://github.com/D10Scot/Dispatcharr/issues/12) | `seeded` | `token-refresh-deleted-user.spec.ts` | `seed.user()`, `asUser` to mint a pair, delete the user, refresh. Assert 401. `test.fail()` — it is 500 today. **Costs exactly one login out of three per minute**; the call site says so in a comment, and this is the only such test in G5 |
| **19** | **Known bug:** XC distinguishes unknown user from wrong password | `seeded` | `xc-auth.spec.ts` | `player_api.php` with a username that does not exist returns 404 (`get_object_or_404` inside `xc_get_user`), while a wrong password returns 401. Assert 401 for both. `test.fail()`. Found while writing this spec, not in the agreed brief — see D10 |

Row 4 covers three of the four HDHomeRun endpoints and row 5 the fourth, split because the
lineup is the only one that reads the database.

**The inventory and `COVERAGE.md` are not one-to-one, and the plan must reconcile them.** Rows 1
and 14 together satisfy the single "/output/m3u parses, every URL is well-formed, and one is
streamed end to end" row. Rows 15, 16, 17 and 19 have **no row in `COVERAGE.md` today** — G5 adds
four, status `known-bug`, each carrying its issue link, in the same PR as the tests, per roadmap
rule 3. Row 18's row already exists.

Row 11 seeds XC users at `user_level` 0, 1 and 10. It must never mutate or borrow the bootstrap
admin — that identity is shared across four workers and is read-only. Whether
`POST /api/accounts/users/` accepts `user_level: 10` is unverified; the plan proves it in a
step before the matrix depends on it, and if it does not, the matrix drops to two levels and
says so in `COVERAGE.md` rather than reaching for the shared admin.

## Fixture additions

Additive, and all at the end of an existing list — G3 is in flight on the same three files.

- **`seed.channelGroup(overrides?): Promise<ChannelGroup>`** — POSTs to `/api/channels/groups/`
  with a generated name. `ChannelGroupOverrides` is `Record<string, never>`: `name` is the
  serializer's only writable field, and the factory owns it, exactly as `channelProfile()` does.
- **`seed.xcUser(overrides?): Promise<XcUser>`** — a `seed.user()` carrying
  `custom_properties.xc_password`, with the password generated per user from the seeder's run
  token and returned on the result as `xcPassword` (D13). The doc comment must say plainly that
  the XC *username* is the Django username and that no `xc_username` property exists, because
  that is the mistake the fixture is shaped to prevent.
- **`xcQuery(user: XcUser): string`** — `?username=…&password=…`, URL-encoded once, in
  `e2e/fixtures/parse.ts` or alongside `xcUser`. Every XC row builds this string; four surfaces
  hand-rolling it is four places to get the encoding wrong.
- **`e2e/fixtures/parse.ts`** — `parseM3u(text): { header: Record<string, string>; entries:
  M3uEntry[] }` and `parseXmltv(text): { channels: XmltvChannel[]; programmes: XmltvProgramme[] }`.
  Deliberately shallow, and its header says so: it reads the attributes these tests assert on and
  is not an M3U or XMLTV validator. Well-formedness is D8's `DOMParser` check, not this file's job.
- **`e2e/fixtures/types.ts`** — `ChannelGroup`, `ChannelGroupOverrides`, `XcUser`, `M3uEntry`,
  `XmltvChannel`, `XmltvProgramme`, each with the serializer or generator it was derived from
  named in a comment, per the file's existing convention.

No new fixture is registered on `test.extend`: everything above is either a `Seeder` method or a
plain function, and G5's HTTP goes through the built-in `request` context (D3).

## Non-goals

- **Catch-up and timeshift.** G8. `catchup_proxy` builds its upstream URL from the account's
  Xtream catch-up template, so there is nothing to point it at until the fake provider speaks XC.
- **VOD and series with real content.** G8. G5 asserts only that the six code paths answer an
  empty catalogue without erroring (D12), and that `/movie/…` and `/series/…` exist as routes.
- **SSDP / UPnP discovery.** There is no SSDP implementation in the product at all — the
  HDHomeRun emulation is the four HTTP endpoints and nothing more. Nothing to test.
- **The frontend.** G6. G5 uses `adminPage` for exactly one thing, D8's `DOMParser` verdict.
- **`stream_xc` not excluding `hidden_from_output`.** Real, and adjacent to defect 2 — every
  listing path excludes hidden channels and `stream_xc` does not, so a channel hidden from output
  is also still streamable. It is a second symptom of the same missing-filter shape and belongs in
  whichever issue defect 2 produces; G5 records it here rather than adding a nineteenth test that
  would go green the moment defect 2 is fixed properly.
- **Fixing any product defect.** Assert correct, `test.fail()`, file the issue.
- **Widening any network ACL.** The `M3U_EPG` default already admits loopback and the Docker
  bridge. Mutating that global `CoreSettings` row from `seeded` would reach every parallel worker.
- **Performance.** This programme establishes correctness only.

## Risks

- **The 300-second `/output/epg` chunk cache is the most likely way this goal ships a lying
  test.** A body cached before the test's channel existed omits it, and the failure looks like a
  missing channel rather than a stale cache. D7's per-test `?days=` is the mitigation, and the
  implementation plan makes proving it a distinct step: seed a channel, fetch twice with the
  *same* `days`, and confirm the second read is the cached body — so the mechanism is demonstrated
  rather than assumed.
- **Credentials in query strings, across four surfaces.** `e2e-upstream/README.md` warns that
  Dispatcharr logs full provider URLs including `?password=` at INFO, and that the CI workflow's
  failure step prints `docker logs dispatcharr-e2e` straight into the log. G5 is the goal that
  warning was written for. Per-test generated passwords (D13) keep both paths harmless — but the
  moment anyone introduces a *fixed* XC credential here, both become publication channels. Say so
  in `seed.xcUser`'s header, where the next person will read it.
- **Five `test.fail()` rows is a lot for one goal**, and each one is a claim that the product is
  wrong. Every one must carry the symbol it indicts in a comment and a filed issue number; a
  `test.fail()` without those is indistinguishable from a broken test somebody gave up on.
- **Row 13 pins behaviour that is arguably wrong.** It asserts that three surfaces are
  unauthenticated, which is the product's real posture and a deliberate one — but if HDHR or
  `/output/*` ever gains a principal, row 13 goes red as a *false alarm*. Its comment must say
  that going red means "update this test", not "fix the product", which is the opposite of what
  every `test.fail()` row in the same suite means.
- **`seed.ts`, `types.ts` and `index.ts` collide with G3.** Additive changes only, appended to
  the existing factory list; whoever lands second rebases through three small conflicts.
- **The `seeded` project's shared instance is the standing hazard.** Every body G5 fetches
  contains every other worker's channels, and a seeded Channel Profile automatically contains
  them too. D14 is not a style rule here; a count assertion would pass locally at one worker and
  fail in CI at four.
- **Issue #12's test is the only login G5 spends.** A run that is cold — first after `--reset`,
  or with `playwright/.auth/` deleted — has already spent the full three-per-minute budget in
  bootstrap, and a worker cannot wait out a throttle window the way bootstrap can. Budget it at
  one per run and expect the occasional 429 on a cold rerun, which is a harness cost, not a
  product failure.
