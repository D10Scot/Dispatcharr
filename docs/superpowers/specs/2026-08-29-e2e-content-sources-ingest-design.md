# G3 — Content Sources and Ingest

**Date:** 2026-08-29
**Status:** Approved, ready for implementation planning
**Wave:** 2 (G1 landed at `a0c99cdd`, G2 at `c188aab6`, G4 at `6e71ca20`; G3 branches from `main`
at `e69f4463`)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`

**Siblings in flight.** G3 adds no Playwright project and no CI matrix job, so it never opens
`e2e/playwright.config.ts` or `.github/workflows/e2e-tests.yml` — which is what keeps it clear of
**G7**, whose branch is unmerged and edits both, plus `scripts/e2e_up.sh` and `e2e/package.json`'s
test scripts. G3 touches none of those four files, so the zizmor hook (which blocks on **every**
finding in an edited workflow) is never armed by this goal.

The surfaces G3 *does* share, all additively:

| File | Also touched by | Discipline |
|---|---|---|
| `e2e/fixtures/seed.ts` | G5, G6 | New factories appended at the end of the existing list — the discipline G4's D3 used |
| `e2e/fixtures/types.ts` | G5, G6 | New types appended; existing types extended field-by-field with evidence |
| `e2e/fixtures/index.ts` | G5, G6 | Header inventory plus re-exports |
| `e2e/fixtures/wait.ts` | G5 | One new method appended to `Waiter` |
| `e2e/fixtures/api.ts` | G5 (likely) | One new method on `ApiClient` |
| `e2e/COVERAGE.md` | G5, G6, G7 | Row edits confined to G3's own rows, plus appended new rows |
| `e2e/README.md` | G5, G6, G7 | Fixture table rows and one new section |

Every collision is small and additive; whoever lands second rebases through them.

## Goal

Prove that Dispatcharr ingests content from an upstream provider correctly, and that the entities
that ingest produces — Streams, Channel Groups, Channels, EPG data, Channel Profile membership and
Logos — can be created, associated and mutated over the API and read back faithfully.

G2 shipped a *plumbing* proof: a playlist was fetched and two Streams appeared. G3 is the
*fidelity* proof — the declared catalogue arrives intact and scoped to its account; a refresh that
fails records the failure and leaves nothing behind; XMLTV becomes guide data a specific Channel
can be shown to carry; a group relation with auto-sync enabled produces Channels inside a declared
numbering window; and the multipart logo path — the only non-JSON write surface in the whole REST
API — works.

This is the goal that makes G5 (client output surfaces) meaningful: G5 asserts what comes *out* of
`/output/m3u`, `/output/epg`, HDHomeRun and Xtream, and every one of those reads rows that only
G3's paths create.

## Current state

Two E2E specs touch ingest at all. `e2e/tests/seeded/upstream-ingest.spec.ts` creates an
`M3UAccount` pointed at the fake provider, refreshes it, and asserts two Streams appear with the
right names and a URL containing the scenario id. `e2e/tests/streaming/single-client.spec.ts`
proves bytes flow, using hand-built `is_custom` Streams that bypass ingest entirely.

Nothing else exists. All six G3 rows in `e2e/COVERAGE.md` are `todo`. No test has ever pointed a
live `EPGSource` at the fake provider's `/s/<id>/epg.xml` — `e2e-upstream/README.md` says so
explicitly. No test has ever driven `sync_auto_channels()`, `from-stream`, a Channel Profile
membership endpoint, or a multipart upload.

Backend unit coverage does not compensate. `apps/m3u` and `apps/epg` are exercised by the Django
suite only against parsed strings and mocked HTTP; the 1,323-line `fetch_schedules_direct()` and
the ~800-line `sync_auto_channels()` are the two largest functions in the repository outside the
proxy, and neither has ever run against a real HTTP upstream in any test.

## Verified facts this design rests on

Cited by symbol or filename, never by line number — line numbers in this repo drift, and an
earlier spec in this series shipped four wrong ones. Everything in this table was read out of the
code in this worktree at `e69f4463` during this session unless the row says otherwise.

### The fake provider

| Fact | Source | Consequence |
|---|---|---|
| **Every channel of every scenario is emitted with `group-title="E2E"`**, hardcoded | `e2e-upstream/src/playlist.ts`, `renderPlaylist` | There is exactly one `ChannelGroup` in play across all workers and all scenarios. "M3U refresh creates the *expected* ChannelGroup rows" can be proved for one group; a multi-group catalogue is a provider gap. See D2 |
| The default catalogue **does** carry a logo: `https://example.invalid/logo-<n>.png` per channel, emitted as `tvg-logo` unless the test passes `logo: null` | `e2e-upstream/src/scenario.ts`, `defaultChannels`; `renderPlaylist` | **This contradicts the brief's premise that the provider emits no `tvg-logo`.** `Stream.logo_url` ingest and downstream `Logo` row creation are testable at row level; only *fetching* the image is not, and `example.invalid` is RFC 2606-reserved precisely so it can never be fetched. See D8 |
| A scenario is **immutable once created**. `ScenarioRegistry` exposes `create`/`get`/`list`/`delete` and the control API has no update route | `e2e-upstream/src/scenario.ts`, `ScenarioRegistry`; `e2e-upstream/README.md` control-API table | A catalogue cannot be mutated in place. Combined with URL-derived stream identity (below), auto-sync *rename-in-place* is not expressible. See D6 |
| The XMLTV renders one `<channel id="{tvgId}">` per catalogue channel and 26 hourly `<programme>` elements per channel, spanning `now-2h` to `now+24h`, titled `` `${name} — slot ${n}` `` | `e2e-upstream/src/xmltv.ts`, `renderXmltv` | Programme titles are derived from the channel name, so a test that passes generated channel names can assert on a programme title without aliasing another worker's data |
| `not-found` and `auth-failure` are both applied to `/s/<id>/playlist.m3u` and `/s/<id>/epg.xml`, and both are "new connection only" — `appliedTo: 0` is correct | `e2e-upstream/src/faults.ts`, `e2e-upstream/src/server.ts`; `e2e-upstream/README.md` fault catalogue | A refresh-failure test arms the fault *before* the refresh and must not treat `appliedTo: 0` as a failure |
| `auth-failure` only means anything on a scenario that declared `username`/`password`; `credentialQuery` returns `''` when `username` is undefined | `e2e-upstream/src/playlist.ts`, `credentialQuery`; `parseScenarioRequest`'s password-requires-username check | The `auth-failure` test must create its scenario with credentials, or it proves nothing |

### M3U ingest

| Fact | Source | Consequence |
|---|---|---|
| `GET /api/channels/streams/` unconditionally applies `qs.exclude(m3u_account__is_active=False)`, and is **always paginated** (`StreamPagination`, page_size 50) | `apps/channels/api_views.py`, `StreamViewSet.get_queryset`, `StreamPagination` | An account must be `is_active: true` for its streams to be visible at all. `seed.m3uAccount()` defaults to `false` |
| `StreamFilter.m3u_account` is a `BaseInFilter` on `m3u_account__id` — a comma-separated id list | `apps/channels/api_views.py`, `StreamFilter` | `?m3u_account=<id>` is the correct account scoping. A `count` under that filter is a *scoped* count, not a global one, so rule 4 is satisfied |
| `StreamSerializer.Meta.fields` includes `m3u_account`, `logo_url`, `tvg_id`, `channel_group`, `is_custom`, `last_seen`, `is_stale`, `stream_chno`, `stream_hash` | `apps/channels/serializers.py`, `StreamSerializer` | The fidelity assertions have a real read-back surface. `e2e/fixtures/types.ts`'s `Stream` type carries only four of these and must be extended |
| `M3UAccount.Status` is `idle`/`fetching`/`parsing`/`error`/`success`/`pending_setup`/`disabled` | `apps/m3u/models.py`, `M3UAccount.Status` | Already typed correctly as `M3uAccountStatus` in `e2e/fixtures/types.ts` |
| On a 404 or 401 from the playlist URL, `fetch_m3u_lines` writes a status-code-specific `last_message`, and `_refresh_single_m3u_account_impl` then **overwrites it** with the generic `"Failed to refresh M3U groups - download failed or other error"` | `apps/m3u/tasks.py`, `fetch_m3u_lines`, `refresh_m3u_groups`, `_refresh_single_m3u_account_impl`, `_set_m3u_account_status` | A test **cannot** assert `last_message` names the HTTP status. The specific message survives only to the WebSocket and the log. See D4 |
| On a fetch failure no `Stream` row is created, updated or deleted — the failure occurs before parsing, and every stream-touching call site sits downstream | `apps/m3u/tasks.py`, `fetch_m3u_lines` returning `(None, False)`; `refresh_m3u_groups`'s early return | "Leaves no partial catalogue" is provable, and provable *strongly*: not merely no new rows, but the previous catalogue intact |
| The catalogue replacement is **not** transactional. Per-batch `transaction.atomic()` only, with `except Exception: logger.error(...)` swallowing a failed batch, followed by an unwrapped stale-mark and two unwrapped `delete()` calls | `apps/m3u/tasks.py`, `process_m3u_batch_direct`, `cleanup_streams` | There is no "atomically replace the catalogue" semantic to test. Do not write an assertion that assumes one |
| `M3UAccount.updated_at` is `null=True, blank=True` with **no `auto_now`**, and is bumped only on the terminal success write | `apps/m3u/models.py`; `apps/m3u/tasks.py` | Confirms the reasoning already recorded in `Waiter.m3uRefreshComplete`'s doc comment |

### EPG ingest

| Fact | Source | Consequence |
|---|---|---|
| The refresh trigger is **`POST /api/epg/import/`** with the id in the **JSON body** (`{"id": …, "force": …}`), returning `202`. There is no `/api/epg/sources/<id>/refresh/` | `apps/epg/api_urls.py`; `apps/epg/api_views.py`, `EPGImportAPIView` | `waitFor.epgRefreshComplete` cannot be a copy of `m3uRefreshComplete`'s URL shape |
| `trigger_refresh_on_new_epg_source` (`post_save`) fires `refresh_epg_data.delay()` when `created and is_active and source_type != 'dummy'` — **no countdown** | `apps/epg/signals.py` | Creating an active XMLTV source *starts a refresh by itself*. A waiter that also POSTs `/api/epg/import/` races the auto-refresh: the second task finds the `refresh_epg_data` lock held, returns without touching status, and a status-based waiter hangs. See D5 |
| `_refresh_epg_data_impl` returns on `if not source.is_active` **before any status write**, and `_ensure_epg_refresh_terminal_status` only forces `error` from `fetching`/`parsing` | `apps/epg/tasks.py` | An inactive source's refresh is a silent no-op with no status change — exactly the M3U hazard already documented in `wait.ts`. `seed.epgSource()` defaults `is_active: false` |
| `parse_channels_only` sets `status='success'`, `last_message="Successfully parsed N channels"` **before** `parse_programs_for_source` runs, and nothing sets it back to `parsing` | `apps/epg/tasks.py`, `parse_channels_only` | **A refresh reaches `success` twice.** A wait for a terminal status resolves mid-refresh, with zero programmes present. See D5 |
| `EPGSource.updated_at` is `null=True, blank=True`, no `auto_now`, and is set only by `parse_programs_for_source`'s success path and `_refresh_epg_data_impl`'s final `.update()` after both parse phases returned truthy | `apps/epg/models.py`; `apps/epg/tasks.py` | `updated_at` is a monotonic completion marker, and it is `null` on a freshly created source. This is the correct thing for `epgRefreshComplete` to poll. See D5 |
| `parse_programs_for_source` computes `mapped_epg_ids = _epg_ids_mapped_to_channels(epg_source)` and **returns early creating zero `ProgramData` rows** when nothing is mapped, with `last_message = "No channels mapped to this EPG source (N entries available)"` | `apps/epg/tasks.py`, `parse_programs_for_source`; `apps/channels/managers.py`, `epg_ids_mapped_to_channels` | **This contradicts the brief's ordering.** "EPGSource → refresh → `Program` rows" is impossible on its own: programmes arrive only *after* a Channel points at an `EPGData` row. See D5 |
| "Mapped" means `Channel.epg_data_id` **or** `ChannelOverride.epg_data_id` referencing an `EPGData` of that source | `apps/channels/managers.py`, `epg_ids_mapped_to_channels` | `set-epg` on an ordinary Channel is sufficient to map |
| The models are `EPGData` (one per `<channel>`, `unique_together ('tvg_id','epg_source')`) and **`ProgramData`** — not `Program` | `apps/epg/models.py` | Name things correctly: `ProgramData`, per the roadmap's rule 2 |
| `POST /api/channels/channels/<pk>/set-epg/` takes `{"epg_data_id": <int>}`, does `channel.save(update_fields=["epg_data"])`, returns `200` with `task_status: "EPG refresh queued"` | `apps/channels/api_views.py`, `ChannelViewSet.set_epg` | Deterministic — an explicit PK, no matching. `task_status` is a cheap confirmation that dispatch happened |
| `refresh_epg_programs` (`post_save` on `Channel`) fires on update when `'epg_data' in update_fields`, **and also on create when `instance.epg_data` is set**; it dispatches `parse_programs_for_tvg_id.delay(epg_data.id)` | `apps/channels/signals.py` | Both `set-epg` and a create carrying `epg_data_id` map-and-parse in one step |
| `parse_programs_for_tvg_id` reads the **cached file on disk** (`extracted_file_path or file_path`, falling back to `get_cache_file()`), re-fetching only if it is missing; nothing deletes that file except a source delete or the next `fetch_xmltv` | `apps/epg/tasks.py`, `parse_programs_for_tvg_id`, `fetch_xmltv`, `EPGSource.get_cache_file`; no `cached_epg` sweeper in `CELERY_BEAT_SCHEDULE` | The set-epg step is cheap and does not re-download. No TTL race between the refresh and the association |
| `parse_programs_for_tvg_id` defers itself by `countdown=15` while the `refresh_epg_data` lock is held, up to 480 times | `apps/epg/tasks.py`, `_defer_parse_programs_for_tvg_id` | Associate **after** the refresh has genuinely completed, or pay 15s per bounce |
| `POST /api/channels/channels/batch-set-epg/` takes `{"associations":[{"channel_id","epg_data_id"}]}`, bulk-updates inside `transaction.atomic()`, calls `dispatch_program_refresh_for_epg_ids` explicitly (because `bulk_update` bypasses signals), returns `200 {"success", "channels_updated", "programs_refreshed"}` | `apps/channels/api_views.py`, `ChannelViewSet.batch_set_epg`; `apps/epg/tasks.py`, `dispatch_program_refresh_for_epg_ids` | Deterministic. Caveat: `epg_data_id` is not validated, so a bogus id is an FK `IntegrityError` (500), not a 400 |
| **`GET /api/epg/grid/` takes no query parameters, is global, is windowed to `now-1h .. now+24h`, and its real programme entries carry `tvg_id` only — no `channel_id`, no `epg` key.** Dummy synthesised entries *do* carry an `epg` object | `apps/epg/api_views.py`, `EPGGridAPIView` | **The brief's chosen assertion surface is wrong for this purpose.** It performs no channel join and asserting on it would be an unfiltered global read, breaking rule 4. See D5 |
| `GET /api/epg/programs/search/?channel_id=<id>` filters `Q(epg__channels__id=…)` — the reverse of `Channel.epg_data` — and is paginated (`ProgramSearchPagination`, page_size 50, `page_size` param). Results carry `channels: [{id,name,channel_number,channel_group,tvg_id}]` | `apps/epg/api_views.py`, `ProgramViewSet.search`, `ProgramSearchPagination`; `apps/epg/serializers.py`, `ProgramSearchResultSerializer` | This is the correct assertion surface: it traverses the association, is scoped to one channel, and returns a scoped `count`. `IsStandardUser`, so the admin `api` fixture is fine |
| `EPGSourceSerializer.epg_data_count` is `obj.epgs.count()` — the number of `EPGData` (channel) rows, not programmes. There is no programme count on any serializer | `apps/epg/serializers.py`, `EPGSourceSerializer` | Scoped, pollable proof that `parse_channels_only` ran |
| `GET /api/epg/epgdata/` declares no filterset and no pagination, so `?epg_source=`/`?tvg_id=` are silently ignored and it returns every row | `apps/epg/api_views.py`, `EPGDataViewSet` | Retrieving an `EPGData` id means fetching the full list and filtering client-side. Acceptable at E2E scale, but never assert its length |
| `EPGSource.source_type` choices are `xmltv`, `schedules_direct`, `dummy`; there is no `api_key` field (removed by `epg/migrations/0024_…`) | `apps/epg/models.py` | Already typed correctly as `EpgSourceType` |

### Channels, groups, profiles, logos

| Fact | Source | Consequence |
|---|---|---|
| `POST /api/channels/channels/from-stream/` is **synchronous**, takes `{stream_id, name?, channel_number?, channel_profile_ids?}` and returns `201` with the serialized Channel | `apps/channels/api_views.py`, `ChannelViewSet.from_stream` | One call, one assertion |
| It copies `tvg_id`, `is_adult` and `tvc_guide_stationid`; reuses `stream.channel_group`; auto-links `EPGData` on a matching `tvg_id`; and does `Logo.objects.get_or_create(url=validate_logo_url(stream.logo_url))`, setting `logo_id` | `apps/channels/api_views.py`, `ChannelViewSet.from_stream`; `apps/channels/tasks.py`, `validate_logo_url` | Combined with the provider's `tvg-logo`, this makes logo *ingest* assertable. See D8 |
| `POST /api/channels/channels/from-stream/bulk/` (**trailing slash**) is **asynchronous**: `202` with `{task_id, stream_count, status: "started"}`, work done by `bulk_create_channels_from_streams` | `apps/channels/api_views.py`, `ChannelViewSet.from_stream_bulk`; `apps/channels/tasks.py`; `frontend/src/api.js`, `createChannelsFromStreamsAsync` | **Contradicts the brief's implicit synchronicity.** The bulk test must poll. See D7 |
| `ChannelFilter` supports `?name=` (`icontains`); `ChannelPagination` returns an **unpaginated array** unless `page`/`page_size` is present; `visibility_filter` defaults to `active` (excludes `hidden_from_output`) | `apps/channels/api_views.py`, `ChannelFilter`, `ChannelPagination`, `ChannelViewSet.get_queryset` | `?name=<generated prefix>` is the scoping tool for every channel assertion |
| `ChannelGroup` has exactly one field, `name` (unique). `GET /api/channels/groups/` has no filterset and no pagination | `apps/channels/models.py`; `apps/channels/api_views.py`, `ChannelGroupViewSet` | Assert membership with `includes`, never a count |
| `M3UAccountSerializer.channel_groups` is `ChannelGroupM3UAccountSerializer(source="channel_group", many=True)`, exposing `channel_group` (the group's PK), `enabled`, `auto_channel_sync`, `auto_sync_channel_start`, `auto_sync_channel_end`, `stream_count`, `is_stale`, `last_seen` | `apps/m3u/serializers.py`; `apps/channels/serializers.py`, `ChannelGroupM3UAccountSerializer` | `GET /api/m3u/accounts/<id>/` is a **scoped** way to find the group id and to read back auto-sync settings — no global groups list needed |
| `ChannelProfileMembership` has `enabled = BooleanField(default=True)` and `unique_together ("channel_profile","channel")` | `apps/channels/models.py` | Membership is opt-out, matching `CONTEXT.md`'s "zero profiles means unrestricted" note |
| **`create_profile_memberships` (`post_save` on `ChannelProfile`) bulk-creates a membership for every existing Channel** when a profile is created, with `enabled` at its `True` default. There is **no** `post_save` on `Channel` that creates memberships | `apps/channels/signals.py` | **Contradicts the brief's implied direction.** A freshly created profile already contains every channel in the instance, enabled. A test must seed its channel *before* the profile, and must assert with `includes`/`not.includes`, never on `channels.length` |
| `PATCH /api/channels/profiles/<profile_id>/channels/<channel_id>/` takes `{"enabled": bool}`, creates a missing membership at `enabled=False` first, returns `200 {"channel", "enabled"}`. Permission `Authenticated`, scoped by queryset — a foreign profile 404s | `apps/channels/api_urls.py`; `apps/channels/api_views.py`, `UpdateChannelMembershipAPIView`; `apps/channels/tests/test_channel_membership_auth.py` | PATCH only. No GET/POST |
| `PATCH /api/channels/profiles/<profile_id>/channels/bulk-update/` takes **`{"channels":[{"channel_id","enabled"}]}`** (`allow_empty=False`) and returns `200 {"status","updated","created","invalid_channels"}` | `apps/channels/api_views.py`, `BulkUpdateChannelMembershipAPIView`, `BulkChannelProfileMembershipSerializer`; `frontend/src/api.js`, `updateProfileChannels` | Not a bare list. `PATCH`, not `POST` |
| `ChannelProfileSerializer.channels` is a `SerializerMethodField` returning the ids of **enabled** memberships | `apps/channels/serializers.py` | One read-back proves both directions of a membership toggle |
| `LogoViewSet` declares `parser_classes = (MultiPartParser, FormParser, JSONParser)` and exposes **two** create paths: `POST /api/channels/logos/` (JSON `name` + `url`, no file) and `POST /api/channels/logos/upload/` (multipart, file field `file`, optional `name`) | `apps/channels/api_views.py`, `LogoViewSet`, `LogoViewSet.upload` | The multipart path is the separate `upload` action, not the ViewSet's `create` |
| `Logo` has exactly two fields, `name` and `url` (`TextField(unique=True)`). An upload writes to `/data/logos/<basename>` and stores that **filesystem path** in `url`, via `get_or_create(url=file_path)` | `apps/channels/models.py`; `apps/channels/api_views.py`, `LogoViewSet.upload`; `core/utils.py`, `safe_upload_path` | There is no `file` field. Two workers uploading the same filename get the **same row** — filenames must be generated per test |
| `validate_logo_file` checks only `file.content_type` (JPEG/PNG/GIF/WebP/SVG) and `size <= 5MB` — no magic-byte inspection | `dispatcharr/utils.py`, `validate_logo_file` | A few bytes with `mimeType: 'image/png'` is a valid upload. No fixture image file on disk is needed |
| `LogoSerializer` returns `id`, `name`, `url`, `cache_url` (absolute, `…/api/channels/logos/<id>/cache/?v=<hash>`), `channel_count`, `is_used`, `channel_names`. `LogoViewSet.cache` is `AllowAny` | `apps/channels/serializers.py`, `LogoSerializer`; `apps/channels/api_views.py`, `LogoViewSet.cache` | The uploaded bytes can be read back over HTTP |
| The writable channel field is **`logo_id`** (`PrimaryKeyRelatedField(source="logo")`); there is no writable `logo` | `apps/channels/serializers.py`, `ChannelSerializer` | Already typed correctly in `ChannelOverrides` |

### Auto channel sync

| Fact | Source | Consequence |
|---|---|---|
| `sync_auto_channels(account_id, scan_start_time=None)` has exactly one production call site: **synchronously inside `_refresh_single_m3u_account_impl`**, after `cleanup_streams`. Nothing dispatches it standalone and no endpoint triggers it | `apps/m3u/tasks.py` | Auto-sync is observed only through an M3U refresh. There is no way to run it on demand |
| It selects `ChannelGroupM3UAccount.objects.filter(m3u_account=account, enabled=True, auto_channel_sync=True)` | `apps/m3u/tasks.py`, `sync_auto_channels` | Both flags must be true |
| `process_groups` creates the through-row during a refresh with `auto_channel_sync` **never set** — it always starts `False` | `apps/m3u/tasks.py`, `process_groups` | The first refresh creates zero auto channels, always. The test needs refresh → enable → refresh |
| **The only endpoint that writes `auto_channel_sync` is `PATCH /api/m3u/accounts/<id>/group-settings/`.** `M3UAccountSerializer.update` pops the nested `channel_group` payload and applies **`enabled` only** | `apps/m3u/api_views.py`, `M3UAccountViewSet.update_group_settings`; `apps/m3u/serializers.py`, `M3UAccountSerializer.update`; `frontend/src/api.js`, `updateM3UGroupSettings` | **Contradicts the plausible nested-PATCH reading.** A `PATCH /api/m3u/accounts/<id>/` carrying `channel_groups` silently discards the auto-sync fields |
| `update_group_settings` reads raw `request.data`, bypasses `ChannelGroupM3UAccountSerializer` entirely, and does a `bulk_create(update_conflicts=True, update_fields=[enabled, auto_channel_sync, auto_sync_channel_start, auto_sync_channel_end, custom_properties])` — a **full-field upsert**. Omitting `custom_properties` writes `{}` | `apps/m3u/api_views.py`, `M3UAccountViewSet.update_group_settings` | Every field must be sent on every call. It is also an upsert, so the row can be pre-created |
| `ChannelGroupM3UAccount` has `auto_sync_channel_start` and `auto_sync_channel_end`, both `FloatField(null=True, blank=True)` | `apps/channels/models.py` | The window is real, and both ends are settable |
| The default numbering mode is **`fixed`**: `channel_numbering_mode = "fixed"` when `custom_properties` carries no override. `_pick_target_number` in `fixed` mode returns `_next_available_number(used_numbers, fixed_cursor, end=end_number)` | `apps/m3u/tasks.py`, `_pick_target_number`, `_next_available_number` | Because `group-settings` wipes `custom_properties` to `{}`, the mode is `fixed` and the window applies. Packing works with **no** opt-in |
| **`apps/channels/compact_numbering.py` is the opt-in `compact_numbering` repack module, not the sync-time packer.** `is_compact_group` reads `custom_properties["compact_numbering"]`, default off; `repack_group` runs only for opted-in groups | `apps/channels/compact_numbering.py`, `is_compact_group`, `repack_group`; `apps/m3u/tasks.py`, `sync_auto_channels` | **Refines the brief's attribution.** The window packing G3 tests comes from `_pick_target_number`; `compact_numbering.py` is out of scope |
| The global reservation is real, from **two** independent sites: `build_reserved_set` filters `Channel.objects.exclude(channel_number__isnull=True)` with no account/group filter, and `sync_auto_channels` seeds `used_numbers` from `Channel.objects.exclude(auto_created=True, auto_created_by=account, hidden_from_output=False)` — a three-condition `exclude` that removes only *this* account's visible auto channels | `apps/channels/compact_numbering.py`, `build_reserved_set`; `apps/m3u/tasks.py`, `sync_auto_channels` | **Confirms the brief.** Another worker's channel inside the window is skipped, so packing must be asserted relatively. See D3 |
| Every `Channel` create/update/delete in `sync_auto_channels` is filtered on `auto_created=True` + `auto_created_by=account`; the refresh lock is `task_lock_refresh_single_m3u_account_<account_id>`, per-account, with **no global lock** | `apps/m3u/tasks.py`, `sync_auto_channels`; `core/utils.py`, `acquire_task_lock` | Confirms the brief's no-cross-worker-*write*-hazard claim **for channel ownership** |
| **But `used_numbers` is a point-in-time snapshot and `Channel` has no `Meta`, so `channel_number` has no DB uniqueness.** Two accounts syncing concurrently can both pick the same free number and both commit it; `Channel.clean()` is never called by `bulk_create`/`bulk_update` | `apps/m3u/tasks.py`, `sync_auto_channels`; `apps/channels/models.py`, `Channel` | **Refines the brief's "no write hazard".** There *is* a narrow silent-duplicate-number race. It is another reason never to assert an exact number. See D3 |
| A stream absent from the current refresh (its `last_seen` not advanced) has its auto-created channel **deleted on the next refresh**, skipping `hidden_from_output=True` ones; a stream whose row survives is **updated in place** on a dirty-field diff | `apps/m3u/tasks.py`, `sync_auto_channels`, `_delete_channels_stopping_streams` | Delete semantics are testable. Update-in-place requires stable stream identity across a catalogue change — which the provider cannot give. See D6 |
| Stream identity is `Stream.stream_hash`, built by `Stream.generate_hash_key` from the `m3u_hash_key` setting, whose shipped default is **`"url"`** | `apps/channels/models.py`, `Stream.generate_hash_key`; `core/migrations/0009_m3u_hash_settings.py` | The scenario id is inside every provider URL, so a different scenario means entirely different Streams |
| `sync_auto_channels` invokes **no** fuzzy EPG matching. It builds `{tvg_id: EPGData}` and does exact dict lookups; `match_channels_to_epg` is reachable only from `apps/channels/api_views.py` | `apps/m3u/tasks.py`, `_resolve_epg_for_stream`; `apps/channels/epg_matching.py` | The auto-sync row does not drag the excluded fuzzy matcher into scope |
| Work is bulk-oriented — `bulk_create`/`bulk_update` at `batch_size=500`, O(1) queries per group, no per-channel `save()` | `apps/m3u/tasks.py`, `sync_auto_channels` | At E2E scale (one group, single-digit streams) sync itself is milliseconds; the cost is the two or three HTTP fetch-and-parse refreshes around it |

### Harness

| Fact | Source | Consequence |
|---|---|---|
| The `seeded` project runs `workers: 4`, `fullyParallel: true`, and inherits the **global 30 000 ms** test timeout | `e2e/playwright.config.ts` | A test doing two or three refreshes will exceed it. See D9 |
| The CI matrix is `[pristine, seeded, streaming, streaming-failover, streaming-greybox]`, and `e2e/package.json` has a script per project | `.github/workflows/e2e-tests.yml`; `e2e/package.json` | `seeded` is already wired. G3 adds nothing. (`e2e/README.md`'s CI section still says "a hardcoded three-job matrix" — stale since G4. See D11) |
| `bootstrap` pre-warms only the `(every=1, HOURS)` `IntervalSchedule` row, via an `M3UAccount` with `refresh_interval: 0` | `e2e/setup/bootstrap.setup.ts`, `prewarmIntervalSchedule` | Covers `refresh_interval: 0` for both `M3UAccount` and `EPGSource`. See D10 |
| `create_or_update_periodic_task` computes `should_be_enabled = enabled and (use_cron or interval_hours > 0)`, so `refresh_interval: 0` yields a **disabled** `PeriodicTask` | `core/scheduling.py` | A default-interval source is never re-refreshed by beat mid-run. A non-zero interval would be |
| `ApiClient.send` passes Playwright's `data` option and retries once through a token refresh on 401. Multipart needs the distinct `multipart` option | `e2e/fixtures/api.ts`, `ApiClient.send` | The multipart path must live in `ApiClient` or it loses the 401 retry. See D8 |
| `Seeder` is constructed with `(api, workerIndex, testId)` and `Waiter` with `(api)`; neither imports the other | `e2e/fixtures/seed.ts`; `e2e/fixtures/wait.ts` | Giving `Seeder` a `Waiter` introduces no cycle |
| **Issue #15 is open and its title already names both fields**: `read_only_fields` on the serializer class instead of `Meta`, so `M3UAccount.locked`/`.updated_at` and `EPGSource.updated_at` are writable | `gh issue list --repo D10Scot/Dispatcharr`; `apps/m3u/serializers.py`; `apps/epg/serializers.py`; and it is already cited in `e2e/fixtures/types.ts` | Assert correct, `test.fail()`, reference #15. **Do not file a duplicate** |
| The same misplaced declaration appears a third time in `StreamSerializer` (class body, not `Meta`), which is why `seed.stream({is_custom: true})` works at all | `apps/channels/serializers.py`, `StreamSerializer` | The harness already depends on one instance of this bug. Note it; do not test it |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Everything lands in the existing `seeded` project.** No new Playwright project, no CI matrix job, therefore no edit to `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `scripts/e2e_up.sh` or `e2e/package.json` | Every G3 test is an API-level read/write plus Celery-backed waits — the same shape as `upstream-ingest.spec.ts`, which already lives there. It keeps G3 entirely clear of G7's pending matrix edit, and raises **zero** zizmor-hook exposure, since the hook only fires on `.github/workflows/*.yml`, `action.yml` and `dependabot.yml`. The cost is D9's per-test timeout, which is one line and reversible. Rejected: a `sources` project — it would buy nothing but a sixth CI job, a sixth container boot, and a three-way collision with G7 |
| D2 | **Group assertions are written against the single `E2E` group, not against per-test groups** | `renderPlaylist` hardcodes `group-title="E2E"` for every channel of every scenario. The M3U row therefore proves the `group-title` → `ChannelGroup` → `ChannelGroupM3UAccount` path exists and is wired to *this* account — read from `GET /api/m3u/accounts/<id>/`'s `channel_groups`, which is account-scoped — and asserts group **membership** with `includes`, never a count or an exclusivity claim. A per-test group name would need a provider change (`ChannelSpec.group`), which belongs to whoever next owns `e2e-upstream`. Recorded as a provider gap, not silently dropped |
| D3 | **Auto-sync numbering is asserted relatively, never absolutely.** Each auto-sync test declares its own disjoint `[auto_sync_channel_start, auto_sync_channel_end]` window — derived from the Playwright worker index plus a per-test offset, in a high band (four figures) well clear of the numbers `seed.channel()` and `from-stream` auto-assign from 1 upward and asserts: every auto-created channel's number lies inside the window; the numbers are distinct; and their ascending order matches the catalogue order the provider declared | The reservation set is genuinely global from two sites (`build_reserved_set` and `sync_auto_channels`'s `used_numbers` seed), so another worker's channel inside the window shifts the packing. Worse, `used_numbers` is a point-in-time snapshot and `channel_number` has no DB uniqueness, so concurrent syncs can produce a genuine silent duplicate — an absolute assertion would flake on a real product race and be read as a harness bug. Relative assertions still prove the mechanism: *the window is honoured and order is preserved*, which is the whole of what the feature promises |
| D4 | **The refresh-failure row asserts `status === 'error'`, an intact prior catalogue and a non-empty `last_message` — but explicitly does not assert the message names the HTTP status.** The diagnostic loss is filed as its own issue and pinned with one additional `test.fail()` test | `fetch_m3u_lines` composes a precise per-status-code message and `_refresh_single_m3u_account_impl` then overwrites it with `"Failed to refresh M3U groups - download failed or other error"`, identically for 404, 401 and a connection refusal. The specific text reaches only the WebSocket and the log, so an operator reading the account row cannot tell a wrong URL from wrong credentials. That is a real defect on G3's surface, it is not #15, and it is not in `CLAUDE.md`'s catalogue — so roadmap rule 5 applies in full: assert the correct behaviour, `test.fail()`, file it. Rejected: asserting the generic string, which would pin the bug as intended behaviour and go green when it is fixed |
| D5 | **The EPG rows are re-ordered: refresh proves `EPGData` and *zero* `ProgramData`; association is what produces programmes; and the assertion surface is `/api/epg/programs/search/?channel_id=`, not `/api/epg/grid/`** | Three verified facts force this. (a) `parse_programs_for_source` returns early creating zero rows when nothing is mapped — so "create → refresh → programme data" cannot succeed on its own, and a test written to the brief's ordering would have been permanently unpassable, the same class of error as G4's first draft of D8. (b) `parse_channels_only` sets `status='success'` before programme parsing, so a refresh reaches `success` **twice** and a status-polling waiter resolves mid-refresh. (c) `/api/epg/grid/` performs no channel join — its real entries carry `tvg_id` only — is globally unfiltered and time-windowed, so asserting on it would break rule 4 and prove nothing about *this* channel. The replacement chain is fully scoped: poll `epg_data_count > 0` on the source; assert `last_message` starts `"No channels mapped to this EPG source"` (which proves zero programmes without a second call); `set-epg`; then poll `programs/search/?channel_id=<id>&page_size=1` for `count > 0` and check the returned programme's `channels[0].id` and its title prefix |
| D6 | **The auto-sync mutation test asserts create-and-delete by re-pointing the account at a second scenario. Rename-in-place is recorded as a gap, not attempted** | A scenario is immutable (`ScenarioRegistry` has no update) and `Stream.stream_hash` derives from the URL, which embeds the scenario id. So the only expressible catalogue mutation replaces every Stream: the first scenario's streams stop being seen and their auto-created channels are deleted, the second scenario's are new and produce new channels. That genuinely exercises both `_delete_channels_stopping_streams` and the create path, in one refresh. Holding a Stream's identity constant while changing its name would need either a provider `PATCH /scenarios/<id>` or a global `m3u_hash_key` change — the first is `e2e-upstream`'s scope, the second is a global `CoreSettings` mutation forbidden in `seeded`. Both are recorded as named gaps |
| D7 | **`from-stream/bulk/` is polled, not read from its response** | It returns `202` with a `task_id` and does its work in `bulk_create_channels_from_streams`. The test asserts the 202 shape, then polls `/api/channels/channels/?name=<prefix>` until the expected channels exist. A `where`-correlated WebSocket wait on `bulk_channel_creation_progress` was rejected: `/ws/` is one broadcast group across four workers, and the roadmap's own guidance prefers `waitFor` wherever REST exposes the state |
| D8 | **Two fixture additions for multipart, not one: `api.upload(url, multipart)` carries the transport, `seed.logo()` carries the identity.** And `tvg-logo` ingest moves *into* scope | `ApiClient.send` is the single place that knows about the 401-refresh-and-retry, and Playwright's `multipart` is a different request option from `data` — putting multipart anywhere else would either duplicate that retry or silently lose it. `seed.logo()` on top matters independently: an upload does `get_or_create(url=/data/logos/<basename>)`, so two workers uploading `logo.png` share one row, and only a generated filename makes the factory worker-safe. Separately, the provider **does** emit `tvg-logo` (`https://example.invalid/logo-<n>.png`, RFC 2606-reserved so it can never be fetched), so `Stream.logo_url` and `from-stream`'s `Logo.get_or_create` are assertable at row level — the brief's premise that this was a provider gap was wrong, and only image *fetching* remains out of scope |
| D9 | **Every test that pays for more than one refresh raises its own budget with `test.setTimeout()`, one line per test** | The `seeded` project inherits the global 30 000 ms timeout. Tests 3, 4, 11 and 12 pay two or three full fetch-and-parse cycles each; the per-test value is the row's estimate in the inventory rounded up to a comfortable multiple, not a shared constant, so a single slow row cannot silently raise the ceiling for the others. A per-test override keeps D1's topology decision reversible in one line and does not slow the 90% of `seeded` that is fast. Rejected: raising the project timeout (it would mask a genuinely hung test everywhere) and a new long-timeout project (D1) |
| D10 | **G3 declares that every account and source it creates uses `refresh_interval: 0`, and the `bootstrap` pre-warm is therefore left unchanged.** No G3 test may deliberately race two concurrent creates | `bootstrap` already pre-warms `(every=1, HOURS)`, which is what `refresh_interval: 0` maps to for both `M3UAccount` and `EPGSource`, so the set G3 uses is already covered and extending the pre-warm would add a permanent unused account for no gain. **This is a deviation from the brief, which anticipated an extension.** A second reason to stay at `0`: `create_or_update_periodic_task` only enables the `PeriodicTask` when `interval_hours > 0`, so a non-zero interval would leave an *enabled* hourly beat task re-refreshing the account for the rest of the container's life. The declaration is enforced by convention plus a README paragraph, and `COVERAGE.md` records that #7 is deliberately not reproduced — provoking it poisons the shared container permanently for every remaining test in the run, and no assertion is worth that |
| D11 | **G3 corrects `e2e/README.md`'s stale CI paragraph while it is editing that file, and does nothing else outside its own surface** | The README still describes "a hardcoded three-job matrix (`e2e-tests.yml:49-50`)"; the matrix has five entries and the line reference is wrong. G3 has to edit this file anyway to document its new fixtures, and leaving a false statement two paragraphs away from a true one is worse than a one-line fix. It touches no workflow, so no hook fires. This is the limit — no other drive-by corrections |
| D12 | **Known defects are asserted correct, marked `test.fail()`, and referenced or filed — never patched** | Roadmap rule 5. #15 is already open and already cited in `e2e/fixtures/types.ts`: reference it, do not file a duplicate. D4's message-overwrite defect is new: file it with `gh issue create --repo D10Scot/Dispatcharr`, explicit `--repo` flag, always |
| D13 | **Every assertion is scoped, and the two scoped-count exceptions are named** | Rule 4 and the harness doctrine. `?m3u_account=<id>` on the streams list and `?channel_id=<id>` on the programme search are *filtered* queries whose `count` describes only this test's rows, so asserting on them is legitimate; `GET /api/channels/groups/`, `GET /api/epg/epgdata/` and `ChannelProfile.channels` are global and unpaginated, so those are asserted with `includes`/`not.includes` only |

## Project topology

```
bootstrap ──→ seeded  (existing)  4 workers, fullyParallel
                 ├── tests/seeded/…            (existing G1/G2 specs, untouched)
                 └── tests/seeded/…            (7 new G3 spec files)
```

No new project. No new CI job. No change to `playwright.config.ts`, `e2e-tests.yml`,
`scripts/e2e_up.sh` or `e2e/package.json`.

All seven new spec files live in `e2e/tests/seeded/` and inherit that project's
`storageState: admin.json`, its `dependencies: ['bootstrap']` and its four parallel workers. The
three tests that pay for more than one refresh raise their own timeout in-file (D9).

The existing `e2e/tests/seeded/upstream-ingest.spec.ts` stays exactly as it is: it is G2's
plumbing proof and `COVERAGE.md` records it as such. G3's `m3u-ingest.spec.ts` is a superset in
what it asserts but not a replacement for what that row means.

## Test inventory

Fifteen tests across seven files. Every test creates its own scenario, its own account or source,
and its own channels, and scopes every assertion to them.

| # | COVERAGE row | File | Mechanism | Est. |
|---|---|---|---|---|
| 1 | Sources / M3U account create → refresh → streams appear | `m3u-ingest.spec.ts` | `seed.upstreamM3UAccount()` over a 3-channel scenario with generated names, tvg-ids and logos. Assert `?m3u_account=<id>` returns exactly those 3, each with the declared `name`, `tvg_id`, `logo_url` and a `url` containing the scenario id and channel id; every stream's `channel_group` is one id; that id appears in the account's own `channel_groups`; and `GET /api/channels/groups/` **includes** a group named `E2E` | 25s |
| 2 | *(new row)* `M3UAccount.locked` and `EPGSource.updated_at` are writable over the API (issue #15) | `m3u-ingest.spec.ts` | `test.fail()`. PATCH a seeded account with `{locked: true}` and assert the read-back is still `false` — the *correct* behaviour. References https://github.com/D10Scot/Dispatcharr/issues/15; files nothing | 5s |
| 3 | *(new row)* Sources / M3U refresh failure records the error and leaves no partial catalogue | `m3u-refresh-failure.spec.ts` | `not-found` armed **before** the refresh (`appliedTo: 0` expected). Assert `status === 'error'`, `last_message` non-empty, `?m3u_account=<id>` count 0. Then clear the fault, refresh again, assert `success` and the full catalogue — the recovery half is what proves the failure left nothing wedged | 30s |
| 4 | (same row) | `m3u-refresh-failure.spec.ts` | Same shape with `auth-failure` on a scenario carrying `username`/`password`. Also asserts a *previously successful* account's catalogue survives a later failed refresh | 35s |
| 5 | *(new row)* A failed M3U refresh discards the HTTP-status-specific message (issue filed during implementation, per D4) | `m3u-refresh-failure.spec.ts` | `test.fail()`. Assert `last_message` mentions the status code the provider returned — the correct behaviour. Expected red today | 20s |
| 6 | Sources / EPG source create → refresh → programme data | `epg-ingest.spec.ts` | `seed.upstreamEpgSource()` over a 2-channel scenario. Assert `updated_at` non-null, `epg_data_count >= 2`, `last_message` starts `"No channels mapped to this EPG source"`; find both `EPGData` rows by `tvg_id` in `/api/epg/epgdata/`; assert `programs/search/?tvg_id=<id>` count is 0. **The zero is the point** — it pins the mapping gate as product behaviour | 30s |
| 7 | Sources / EPG explicit association (`set-epg`) | `epg-ingest.spec.ts` | Channel + `POST channels/<id>/set-epg/ {epg_data_id}` → `200`, `task_status === 'EPG refresh queued'`. Poll `programs/search/?channel_id=<id>&page_size=1` for `count > 0`; assert the first result's `channels[0].id === channel.id` and its `title` starts with the scenario channel's generated name | 40s |
| 8 | (same row) `batch-set-epg` | `epg-ingest.spec.ts` | Two channels, one `POST channels/batch-set-epg/ {associations:[…]}` → `200`, `channels_updated === 2`. Poll each channel's programme count > 0 | 45s |
| 9 | Sources / Channel creation from streams (`from-stream/`) | `channel-from-stream.spec.ts` | `201`; channel `name` equals the stream's, `streams` includes the stream id, `tvg_id` copied, `channel_group_id` equals the stream's group, `logo_id` non-null — the last from the provider's `tvg-logo` (D8) | 25s |
| 10 | (same row) `from-stream/bulk/` | `channel-from-stream.spec.ts` | `202` with `task_id` and `stream_count`; poll `?name=<prefix>` until all three channels exist; assert each is wired to its own stream (D7) | 35s |
| 11 | Sources / Auto channel sync — enable and create | `auto-channel-sync.spec.ts` | `test.setTimeout(150_000)`. Refresh #1 → assert zero auto channels for this account. Read the group id from the account's `channel_groups`. `PATCH accounts/<id>/group-settings/` with a **disjoint** window and `auto_channel_sync: true`, sending every upsert field (the endpoint is a full-field upsert). Refresh #2 → assert 4 channels with `auto_created: true`, numbers inside the window, distinct, ascending in catalogue order (D3). Read the settings back from `channel_groups` | 110s |
| 12 | (same row) — delete and create on a changed catalogue | `auto-channel-sync.spec.ts` | `test.setTimeout(180_000)`. As above with 3 channels, then `PATCH` the account's `server_url` to a **second scenario**'s playlist (2 channels, different generated names) and refresh #3. Assert the 3 first-scenario channels are gone and the 2 second-scenario channels exist, `auto_created: true`, inside the same window (D6) | 150s |
| 13 | Sources / Channel groups and Channel Profiles | `channel-profiles.spec.ts` | Seed a channel **first**, then `seed.channelProfile()`. Assert `profile.channels` **includes** the channel (the `create_profile_memberships` signal). `PATCH profiles/<p>/channels/<c>/ {enabled:false}` → `200`; assert `not.includes`. `PATCH` back to `true`; assert `includes` again. Never asserts `channels.length` | 20s |
| 14 | (same row) bulk membership | `channel-profiles.spec.ts` | Two seeded channels, one profile, `PATCH profiles/<p>/channels/bulk-update/ {channels:[{channel_id,enabled}]}` → `200` with `updated`/`created`/`invalid_channels: []`; assert both memberships landed via `profile.channels` | 20s |
| 15 | Sources / Logo upload and assignment | `logo-upload.spec.ts` | `seed.logo()` (multipart, generated filename, tiny PNG buffer, `mimeType: 'image/png'`) → `201`; `url` ends with the generated filename under `/data/logos/`; `cache_url` present. `PATCH channels/<id>/ {logo_id}` → read back `logo_id`. `GET cache_url` → `200` with the uploaded bytes | 20s |

Fifteen tests, seven files. Rows 2, 5, 11 and 12 are the ones worth reading before writing
anything else.

Six existing `COVERAGE.md` rows are addressed. Four rows are **added** in the same PR (rule 3):
the M3U refresh-failure row, the #15 known-bug row, the D4 known-bug row, and a gaps note
covering everything under Non-goals below.

## Fixture additions

All additive, all at the end of their existing lists.

- **`api.upload(url, multipart)` → `Promise<APIResponse>`** (`e2e/fixtures/api.ts`). Playwright's
  `multipart` request option, routed through the same 401-refresh-and-retry as `send()`. This is
  the only non-JSON write path in the harness; its header says so.
- **`seed.logo(overrides?)` → `Promise<Logo>`** (`e2e/fixtures/seed.ts`). POSTs
  `/api/channels/logos/upload/` with a generated `<name>.png` filename and a small inline PNG
  buffer. The generated filename is load-bearing: `LogoViewSet.upload` does
  `get_or_create(url=/data/logos/<basename>)`, so a fixed name is shared across workers.
- **`seed.upstreamM3UAccount(scenario, overrides?)` → `Promise<M3uAccount>`**. Creates the account
  with `is_active: true` and `server_url = upstream.playlistUrl(scenario)`, triggers and waits for
  the refresh through `waitFor.m3uRefreshComplete`, asserts `status === 'success'`, returns the
  refreshed row. The refresh-failure tests deliberately do **not** use it — they want an `error`
  outcome and must own the trigger themselves.
- **`seed.upstreamEpgSource(scenario, overrides?)` → `Promise<EpgSource>`**. Creates with
  `is_active: true` and `url = upstream.epgUrl(scenario)`, then waits through
  `waitFor.epgRefreshComplete` **with the create response as the explicit baseline and a no-op
  trigger** — the `post_save` receiver has already started the refresh, and a second
  `/api/epg/import/` would find the lock held and return without touching status.
- **`Seeder` gains a `Waiter`** in its constructor, so the two `upstream*` factories can own the
  full create-and-wait dance the way `upstreamChannel()` owns the wiring dance. `Waiter` takes only
  `api`, so there is no cycle.
- **`waitFor.epgRefreshComplete(sourceId, options?)` → `Promise<EpgSource>`**
  (`e2e/fixtures/wait.ts`). Deliberately **not** a copy of `m3uRefreshComplete`:
  - It polls **`updated_at` changing from a baseline**, not a terminal status, because
    `parse_channels_only` makes `success` arrive twice and the first one is premature (D5).
    `updated_at` is `null` on create and is written only when both parse phases returned truthy.
  - It also resolves on `status === 'error'` **when `status` or `last_message` differs from the
    baseline** — the same guard `m3uRefreshComplete` uses so a pre-existing error state cannot
    resolve the wait instantly.
  - `options.baseline?: EpgSource` lets a caller supply a baseline read strictly before the
    trigger — required for the create path, where the refresh may already be running by the time
    the fixture could read one.
  - `options.trigger?: () => Promise<unknown>` defaults to `POST /api/epg/import/ {id}`. Pass a
    no-op for the create-auto-refresh path.
  - Its doc comment must state the inactive-source hazard (a refresh of an inactive source never
    changes any field, so the wait times out saying nothing started) exactly as
    `m3uRefreshComplete` does.
- **`e2e/fixtures/types.ts`**: extend `Stream` with `m3u_account`, `logo_url`, `tvg_id`,
  `channel_group`, `last_seen`, `is_stale`, `stream_chno` (evidence: `StreamSerializer.Meta.fields`
  plus the model's nullability). Add `Logo`, `LogoOverrides`, `EpgData`, `ChannelGroup`,
  `ChannelGroupM3UAccountSettings` (the `group-settings` request row), `ProgramSearchPage` and
  `ProgramSearchResult`. Every addition carries the same evidence note the file's header demands.
- **`e2e/fixtures/index.ts`**: re-export the new types and extend the header inventory —
  `api.upload`, the three new `seed` factories, `waitFor.epgRefreshComplete`.
- **`e2e/README.md`**: fixture-table rows for the above; a short section stating D10's
  `refresh_interval: 0` rule and why; a sentence on D3's relative numbering assertions; and D11's
  one-line CI-matrix correction.

No change to `e2e/setup/bootstrap.setup.ts` (D10).

## Non-goals

Each of these is recorded as a row or a note in `e2e/COVERAGE.md`, never as silence.

- **Fuzzy EPG auto-matching.** `channels/match-epg/`, `channels/<id>/match-epg/`,
  `set-names-from-epg/`, `set-logos-from-epg/` and `set-tvg-ids-from-epg/` are all out, as is the
  1,323-line `fetch_schedules_direct()`. G3 proves the deterministic association path only.
- **`get_preferred_region_code()`.** `core/migrations/0020` deleted the row it reads, so it can
  never succeed and EPG matching runs with no regional weighting, silently. Deliberately not
  pinned: it belongs to the fuzzy matcher, which is out.
- **Auto-sync rename-in-place / update semantics.** Not expressible — the provider's scenarios are
  immutable and `Stream` identity derives from a URL carrying the scenario id (D6). Closing it
  needs a provider `PATCH /scenarios/<id>`, which is `e2e-upstream`'s scope.
- **Multi-group catalogues.** `renderPlaylist` hardcodes `group-title="E2E"` (D2). Closing it needs
  a `group` field on `ChannelSpec` — again `e2e-upstream`'s scope.
- **Logo image *fetching*.** The provider's `tvg-logo` points at `example.invalid`, RFC 2606-
  reserved so it can never resolve. Row-level ingest **is** in scope (D8); only downloading and
  caching the remote image is not.
- **Reproducing #7** (the `IntervalSchedule` duplicate-create race). Provoking it poisons the
  shared container permanently for the rest of the run, with no API or UI able to repair it. D10.
- **Refresh-interval scheduling — and this one is a cost D10 incurs, not a pre-existing gap.**
  Declaring `refresh_interval: 0` for every G3 source means nothing in this programme exercises a
  *non-zero* interval: not `create_or_update_periodic_task`'s
  `should_be_enabled = enabled and (use_cron or interval_hours > 0)` branch, not the
  `IntervalSchedule` row it creates for that interval, not `cron_expression`, and not
  `_cleanup_orphaned_interval` on delete. The reason is exactly D10's second argument: a non-zero
  interval leaves an **enabled** hourly beat task re-refreshing that account for the life of the
  container, mutating rows under whatever test happens to be running an hour later — which a
  shared `seeded` instance cannot tolerate. **Assigned to G7**, whose scenario-specific jobs each
  stand up their own instance and can therefore afford an enabled beat task, and which is already
  the home for everything that cannot share the ordinary `seeded` container. It also needs the
  pre-warm extended to whichever intervals it picks, from `bootstrap` and never from a worker.
- **`M3UFilterViewSet`**, Xtream/XC provider accounts (G5), DVR and recordings (G6), the
  `compact_numbering` opt-in repack path, `repack-group/`, and `Channel` preemption.
- **Fixing any product defect.** Assert correct, `test.fail()`, reference or file the issue.

## Risks

- **The EPG path has never been exercised end to end.** No test has pointed a live `EPGSource` at
  `/s/<id>/epg.xml`; `renderXmltv` is proved only by `e2e-upstream`'s own vitest. Budget for
  discovering that the XMLTV needs shape adjustments. The most likely failure is the parser
  rejecting or silently dropping the document rather than a wrong assertion, so it fails loudly.
  **Fallback if the shape is wrong:** fix `renderXmltv` in `e2e-upstream/src/` (it is test
  infrastructure, not the product, and its own vitest suite pins the change) and note the fix in
  the PR. If the problem is the product's parser rather than the document, that is a defect —
  `test.fail()` plus an issue, per D12. Do **not** work around it by hand-writing an XMLTV file
  into the harness: that would prove the parser against a document no provider emits.
- **Auto-sync tests are the longest in `seeded` by a wide margin.** Test 12 pays three full
  fetch-and-parse refreshes and is budgeted at 150s against a 30 000 ms project default. The
  mitigation is `test.setTimeout()` per test (D9) — one line, reversible, and it keeps D1's
  topology decision cheap to revisit. If the real numbers come in far worse than budgeted, moving
  `auto-channel-sync.spec.ts` to its own project is a config addition, not a rewrite; but that
  addition collides with G7 and should not be made speculatively.
- **`seed.ts`, `types.ts`, `index.ts`, `COVERAGE.md` and `README.md` all conflict with G5 and G6.**
  Mitigation: additive only, appended at the end of the existing list in each file; no
  reformatting, no reordering, no reflowing an existing paragraph while editing next to it.
- **`update_group_settings` is a full-field upsert that wipes `custom_properties` to `{}` when the
  field is omitted.** For an M3U-account group relation that map is normally empty, but a test
  that reads the relation, edits one field and PATCHes back a partial row will silently clear the
  rest. Every call must send every upsert field.
- **A silent duplicate `channel_number` is possible** when two accounts sync concurrently
  (`used_numbers` is a snapshot; `channel_number` has no DB uniqueness). D3's relative assertions
  are chosen so this cannot present as a false failure — but if it *is* observed, it is a genuine
  product defect and gets an issue, not a retry.
- **`parse_programs_for_tvg_id` defers 15s at a time while the source refresh lock is held.** A
  test that associates too eagerly pays that penalty silently and looks like a slow poll. The
  fixture's create-and-wait ordering is what prevents it; do not `set-epg` before
  `epgRefreshComplete` has returned.
