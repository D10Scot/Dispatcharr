# Stream Classification and Quality-Ordered Failover

**Date:** 2026-10-31
**Status:** Draft (review rounds 1-7 and the 2026-11-11 code-review findings addressed; see § Changelog)
**Rulings:** the owner's rulings R1-R5 and R7 of 2026-10-31 and R8-R10 of 2026-11-11 override any default
here. Appendix A restates them, so this document can be read without the conversation that produced them.
**Demo spike (R10):** before serious implementation, a throwaway demo engine is being built on branch
`spike/classification-demo`, in its own worktree and never merged, so the owner can feed real provider lists
through the parser and rate the result. Its findings may reopen § Parsing and § Region; a change there lands
as an amendment to this spec before S2's plan is written.
**Authorities:** `CLAUDE.md` (§ Video path, § State, § Known defects and traps, § Structural
constraints, § Conventions), `CONTEXT.md`, `docs/adr/0005`, `docs/adr/0006`, `docs/adr/0010`, and
`docs/relay-parity-matrix.md` for the two PRs (S1a, S1b) that touch the Go relay.
**Verified at:** `main` `149678aa`. Line numbers drift. Symbol names, setting keys, event types and
route shapes are the durable half of every citation.

Implement this spec PR by PR with subagents, per CLAUDE.md § Delegation for phase work.

## Goal

Providers (M3U and Xtream accounts) carry many groups and thousands of live streams each, named
inconsistently: `UK: Sky Sports Main Event FHD`, `SKY SPORTS MAIN EVENT UK HD`,
`|NZ| Sky Sport 1 HD`. Several providers carry the same real feed. Some names collide across
countries but are different feeds with different EPGs: Sky Arts in the UK and Sky Arts in New Zealand
must never be merged.

This spec designs four things, in the owner's order:

1. **Parse.** Every live stream becomes a normalised record: a canonical name, a region, quality hints
   (resolution tier, codec, frame rate) and markers (`backup`, `raw`, `+1`).
2. **Group.** Streams are grouped across providers into **content identities**. One identity is one
   real channel feed in one region. Deterministic rules run first. Fuzzy candidates go to an admin
   review queue. Confirmed decisions are remembered, so a re-scan is stable. R2's optional LLM assist is
   **deferred to its own spec** (ruling R5; § LLM assist).
3. **Classify quality.** Each stream gets a **quality tier**. It is derived from the name, then
   overridden by measured stream statistics captured during real playback (R1). A measurement never
   expires back to the name tier: when it reaches `measured_ttl_days`, that one stream is re-measured by a
   short, throttled, slot-reserving probe (R8, § Re-measurement at expiry). Nothing else probes a provider,
   and an unmeasured stream is never probed.
4. **Order.** Each served channel's `ChannelStream.order` is set best tier first, then by observed
   reliability within a tier (R4). The relay's existing failover then walks down in quality. Existing
   channels are reordered automatically once the owner enables it, new channels are proposed for admin
   acceptance, and admin pins override everything (R3).

The live relay is not redesigned. Its failover already reads `ChannelStream.order` (§ How the order
reaches the relay), so the whole policy can be expressed by writing that column off the tune path.
Two small relay PRs are needed (S1a, S1b). They change only what the relay reports, never what it decides.

Every stopping point in § The PRs migrates, boots and works on its own. After S3 the admin can see a
tier per stream. After S4 the admin has identities and a review queue. After S6 the headline
behaviour exists. Widening scope is the main way this fails.

## What was measured before this spec was written

| # | What | Result |
|---|---|---|
| M1 | **What writes `Stream.stream_stats` today?** Every writer in the tree was grepped. | **No automatic producer on the live playback path.** Two writers exist. (1) `core/relay_events.py:113-159` (`_apply_stream_stats`) runs when a relay posts an event of type `stream_stats` (`:203-208`). (2) The Stream REST serializer lists `stream_stats` and `stream_stats_updated_at` among its fields and does not mark them read-only (`apps/channels/serializers.py:142-149`), so an admin API client can write them by hand. The Go relay never emits a `stream_stats` event: `grep -rn '"stream_stats"' relay --include='*.go'` matches nothing outside comments and tests, and `relay/httpapi/events.go:21-29` only forwards what `relay/channel` emits. The Python relay posted it from three sites (Phase 1 spec, lines 65-69 and 1418-1420: a periodic flush, a final flush on stop, and every parsed codec line), and `relay/control/events.go:97-100` still sizes its queue for "one stats flush per thirty seconds per channel". The Go relay parses the stats (`relay/channel/stats.go:30-48`, `reportInfo` at `:59`, `reportProgress` at `:101`) and serves them from memory on `GET /proxy/relay/channels` (`relay/httpapi/channels.go:91-116`), but never posts them. R1's measured override has no automatic input until S1b lands. Whether every stored value is literally unchanged since the stage 2d-3 cutover depends on whether anything used the REST path, which this spec did not measure. |
| M2 | **Do relay events say which stream they are about?** The payloads of every `emit` call in `relay/channel/` were read. | **Mostly not.** `channel_start` carries `stream_id` (`relay/channel/manager.go:366-369`). `stream_switch` carries the **new** `stream_id` and nothing about the stream it left or why (`relay/channel/failover.go:288-291`). `channel_failover` (buffering only) carries `reason` and `duration` (`:335-338`). `channel_error` with `connection_failed` carries a redacted, truncated URL and `attempts` (`relay/channel/channel.go:604-608`). `channel_buffering` carries `speed` (`relay/channel/source_transcode.go:352`). `channel_stop` carries `runtime` and `total_bytes` (`relay/channel/channel.go:759-767`). Dead-air and connect-failure switches raise no `channel_failover` at all. The trigger is known inside the relay (`failover(ctx, why)`, `relay/channel/failover.go:190`, with `why` one of `health_monitor` at `channel.go:624`, `max_retries_exceeded` at `:635` and `buffering_timeout` at `failover.go:322`), but it is not put on the wire. Per-stream reliability cannot be attributed reliably from today's events. |
| M3 | **Can `SystemEvent` rows serve as the reliability history?** | **No.** `log_system_event` trims the table to `max_system_events`, default 100 (`core/utils.py:906-921`, `core/models.py:770`). That is minutes of history on a busy instance. |
| M4 | **Parser and fuzzy-match cost.** A throwaway prototype in the orchestrator's scratchpad (never in the repo): NFKC + casefold + one tokenising regex + dictionary lookups, over 100,000 synthetic names in eight conventions, on the planner's laptop (CPython 3.13.2). This is a scratch measurement, not reproducible from the tree. S2 and S4 re-measure. | Parse: **0.20 s** for 100k names (2.0 µs per name). SHA-1 fingerprint: **0.03 s** for 100k. `rapidfuzz==3.14.5` (the version `pyproject.toml:30` pins) `process.extract(..., scorer=token_sort_ratio, limit=5, score_cutoff=85)`: **3.09 s for 2,000 queries against 9,966 keys**, about 1.5 ms per query, unblocked. The prototype separated `UK: Sky Arts HD` (`sky arts`, GB) from `\|NZ\| Sky Arts HD` (`sky arts`, NZ). The production parser does more work per name, so budget ten times this. **Fuzzy matching must be blocked and bounded** (§ Identity resolution). |

**Not measured:** database write throughput for 100k classification rows (S3 measures it), the global
multi-account resolution workload (S4 measures it), and real provider name corpora (§ Test strategy says
how the corpus is built without one).

## Verified facts this design rests on

### How the order reaches the relay

- **The initial tune walks `ChannelStream.order`.** `Channel.get_stream()`
  (`apps/channels/models.py:554-690`) first reuses a live assignment when the relay still holds the
  channel (`:571-603`). Otherwise it iterates `self.streams.all().order_by("channelstream__order")`
  (`:610`). For each stream it tries the account's default profile, then the other active profiles,
  and reserves the first slot it can through `reserve_profile_slot` (`:637-639`, the #513 Lua script in
  `apps/m3u/connection_pool.py:266` onward). **The order is the preference order. A stream whose
  provider is full is skipped, not waited for.**
- **A failover re-reads the order on every call.** The relay's `failover()` posts to next-source with
  `Exclude` (the tried set plus the current stream), `CurrentURL` and `CurrentStreamID`
  (`relay/channel/failover.go:199-211`). Django's `resolve_source()` failover branch
  (`apps/proxy/next_source.py:1092-1112`) walks `get_alternate_streams()` (`:470-596`). That query
  reads `channel.streams.all().order_by('channelstream__order')` **fresh** (`:495`), keeps the streams
  with a profile that has capacity (`profile_available_for_channel_switch`, `:548-552`), and rotates the
  list with `order_alternates_from_current()` (`:314-339`) so that it starts right after the current
  stream and wraps around.
- **Consequence for a running channel.** Thresholds are snapshotted at channel start, off the
  next-source answer (CLAUDE.md § Video path). **The candidate order is not snapshotted.** A reorder
  written while a channel runs never moves the stream already playing, because nothing triggers a
  switch. It does take effect at that channel's **next** failover, because the failover query re-reads
  the order. The one exception is a **degraded** failover: when Django is unreachable the relay walks
  the alternates it cached from the initial answer (`pickCached`, `relay/httpapi/failover.go:85-105`;
  the list is built by `include_alternates`, `next_source.py:1063-1070`), in the order that held at
  channel start.
- **The switch goes to the next candidate, not to a chosen one.** The rotation picks the first stream
  after the current one that is not excluded, has a capacity-bearing profile and does not resolve to
  the URL already playing (`next_source.py:1098-1106`). On a list sorted best tier first, a failover
  from tier *T* tries the rest of tier *T* after the current stream, then every lower tier, and only
  then wraps to the higher tiers and the tier-*T* streams before the current one. The tried set
  shrinks to the current stream only when the run loop reaches its stable-run branch
  (`relay/channel/channel.go:573-577`, calling `noteStable` at `:727-736`). It is not a periodic reset
  during playback. A channel that dropped a tier stays there until the lower stream itself fails.
  **Nothing climbs back up on its own.** D9 keeps it that way for this programme.
- An operator switch (`Advance`, `relay/channel/advance.go:53`) and the three automatic triggers all
  reach `applySwitch` (`failover.go:262`), which raises `stream_switch`. `applySwitch` swaps the source
  and the current stream id (`:263-266`) **before** the old source's attempt is cancelled
  (`advance.go:58-65`, `failover.go:323-342`), so the old source's stderr reader can still deliver
  lines after the switch. `reportInfo` merges into one per-channel `stats` struct and never clears a
  field (`relay/channel/stats.go:57-97`). Nothing resets that struct on a switch.
- A same-source retry re-runs the same `Source` value (`relay/channel/source_transcode.go:173-181`), and
  `runAttempt` attaches the source to the channel at the start of every attempt (`channel.go:668-672`).
- The tune path's queries are pinned by `apps/proxy/tests/test_tune_path_query_ledger.py`
  (`TunePathQueryLedgerTests`, `:189`). Nothing in this spec may add a query there, and that test is
  the proof.

### What writes `ChannelStream.order` today

- The channel serializer's update rewrites the whole list from the request, as `enumerate` positions
  (`apps/channels/serializers.py:700-729`). The bulk channel edit does the same
  (`apps/channels/api_views.py:1460-1489`). Both treat membership and order as one operation. The
  frontend's drag reorder sends the full list through a `PATCH` (`frontend/src/api.js:737-756`, called
  from `frontend/src/components/tables/ChannelTableStreams.jsx`).
- Auto channel sync creates **one channel per stream** at `order=0` (`apps/m3u/tasks.py:2814-2823`).
  Auto-created channels hold one stream unless an admin adds more, so several auto-created channels
  (one per provider) commonly carry the same real feed. A stream may sit on several channels:
  `ChannelStream`'s only constraint is `unique(channel, stream)` (`apps/channels/models.py:937-943`).
  Sync never removes a foreign stream from an auto-created channel. It **deletes** an auto-created
  channel once no stream from its own account remains on it, in the default `orphan_channel_cleanup`
  mode `always` (`apps/m3u/tasks.py:3010-3037`).
- `bulk_create_channels_from_streams` (`apps/channels/tasks.py:3399`) writes `order=0` rows
  (`:3617`).
- The rehash merge (`_merge_stream_relationships`, `core/tasks.py:719-740`) moves a duplicate
  stream's `ChannelStream` rows to the surviving stream. Where both rows exist on one channel it keeps
  the lower `order` and **deletes** the other row (`:726-736`). It takes no lock.
- Nothing takes a lock around a reorder. Two writers race last-writer-wins.

### Streams, accounts, groups and EPG

- `Stream` (`apps/channels/models.py:59-158`): `name` (512), `tvg_id` (255, no uniqueness), `channel_group` (FK;
  `ChannelGroup.name` is unbounded text, globally unique, `:38-39`, so one group row is shared by every
  account that uses the title), `stream_hash` (unique, `:96-102`), `stream_id` (the provider's XC id, stable
  across credential changes, `:116-121`), `stream_stats` and `stream_stats_updated_at` (`:130-140`),
  `is_adult`, `is_stale`, `custom_properties`. Names and group titles are unrestricted provider text.
- `stream_hash` comes from `Stream.generate_hash_key` (`:163-190`). For XC accounts it uses
  `stream_id` in place of the URL. The hash keys are configurable, so the same row can get a new
  hash when its name changes. **A remembered decision cannot be keyed on `stream_hash` alone.**
- The refresh pipeline: `refresh_single_m3u_account` (`apps/m3u/tasks.py:3413-3414`,
  `time_limit=3600`). It holds `acquire_task_lock` and renews it with `TaskLockRenewer`
  (`:3416-3422`; `core/utils.py:327`), because the plain lock expires after 300 s
  (`core/utils.py:296-306`) and `release_task_lock` deletes it unconditionally (`:309-315`). Its tail
  runs `cleanup_streams` (`:3897`, with no local `try`), then `sync_auto_channels` (`:3907`, defined at
  `:2058`, in a local `try` whose failure **marks the account status ERROR**, `:3929-3958`), then
  `rollup_channel_catchup_fields` (`:3942`, in a local `try` that only logs). Batch processing uses
  `BATCH_SIZE = 1500` (`:41`) with `bulk_create`/`bulk_update` per batch (`:1278-1286`, `:1498-1502`).
  Refresh is scheduled per account by a periodic task (`apps/m3u/signals.py:58-64`).
- `M3UAccount.priority` exists (`apps/m3u/models.py:101-104`) but is documented and used only for
  VOD provider selection (`apps/output/views.py:1245`, `:1261`, `:1517`, `:1732`).
- EPG: `EPGData(tvg_id, name, epg_source)`, `unique_together = ('tvg_id', 'epg_source')`
  (`apps/epg/models.py:156-169`), so **one tvg_id can resolve to several rows from several sources**.
  `EPGSource` has `custom_properties` and `priority`.
- An EPG matcher exists already: `apps/channels/epg_matching.py`. Its exact lookup returns the first
  row (`lookup_epg_by_tvg_id`, `:268-273`), and its bulk index keeps the first row per tvg_id after a
  priority sort (`:276-303`). It has one instance-wide `preferred_region` (`core/models.py:601-602`,
  used by `match_epg_channels`, `apps/channels/tasks.py:241-274`). Its `normalize_name()` (`:102-166`)
  strips `hd`/`uhd`/`1080p` and friends (`COMMON_EXTRANEOUS_WORDS`, `:27-32`). **It is region-blind
  for tvg_id collisions, and its normaliser discards the quality tokens this spec needs.** The catalog
  therefore has its own region-aware EPG binding (§ EPG binding) and does not call the matcher.
- Auto sync rewrites `epg_data` on every auto-created channel it manages, on every run, from
  `_resolve_epg_for_stream` (`apps/m3u/tasks.py:2693-2702`). EPG refresh writes `EPGData` in bulk and
  deletes unmapped rows (`apps/epg/tasks.py:1488-1502`), so row-save signals cannot be relied on to see it.

### Events and stats

- The relay batches events to `POST /api/relay/events` (`relay/control/events.go:40-64`, at most 200
  per batch, order preserved). The wire `Event` has no timestamp and no identity (`:31-38`). The post
  goes through the shared client, which **retries** on a transport failure, a 5xx, and a 2xx whose
  body cannot be read (`relay/control/nextsource.go:429-448`, `:486-490`). A batch Django already
  applied can therefore arrive twice. `apply_event_batch` does no deduplication
  (`core/relay_events.py:185-265`). The `Emitter` posts from **one** worker goroutine, in enqueue order,
  and finishes a batch's retries before it drains the next (`relay/control/events.go:172-190`).
- `apply_event_batch` routes `stream_stats` to `_apply_stream_stats`, which merges non-null keys into
  the stored dict and refreshes `stream_stats_updated_at` (`:138-145`). It routes every other known type
  to `log_system_event`. Three types are also pushed over the WebSocket, restricted to the `_WS_FIELDS`
  whitelist (`:28-37`, `:90-110`). A new detail key reaches Connect webhooks and `SystemEvent.details`,
  but not the WebSocket unless it is added to the whitelist.
- Measured stats exist only for the subprocess architecture (FFmpeg, VLC, Streamlink). The Proxy
  and Redirect profiles have no stderr and report nothing (parity-matrix row 29). **A stream played only
  through Proxy is never measured, and keeps its name-derived tier forever.**

### Settings and authorization

- `CoreSettings` is one row per group, all instance-wide (CLAUDE.md § State). Defaults live in each
  group's getter (`get_system_settings`, `core/models.py:766-775`, through `_get_group` at `:398`).
- Channel Profile membership (`user_can_access_channel`, `apps/proxy/authorize.py:202-223`): an admin
  passes, and **a user** with no Channel Profiles passes. A user who has profiles reaches a channel
  only through an enabled membership of that channel in one of their profiles. **A channel with no
  memberships is therefore reachable only by admins and by users with no profiles.**

### Model signals on the channel tables

Every receiver on `Channel`, `ChannelOverride` and `ChannelStream` at the base is in
`apps/channels/signals.py`; no other app connects one (`git grep -n "sender=Channel\|\.connect(" 149678aa`).

| Receiver | Fires on | Effect |
|---|---|---|
| `update_channel_tvg_id_and_logo` (`:37-51`) | `m2m_changed` `post_add` on `Channel.streams.through` | fills an empty `tvg_id`. Fires only through `channel.streams.add()`; the channel serializer creates `ChannelStream` rows directly (`apps/channels/serializers.py:723-725`) and so does not fire it |
| `assign_compact_number_on_unhide` (`:82-130`), `release_compact_number_on_hide` (`:133-178`) | `Channel` `post_save` | return at once unless `hidden_from_output` is in `update_fields` (`:102-104`, `:150-152`) |
| `refresh_epg_programs` (`:181-196`) | `Channel` `post_save` | when `epg_data` is in `update_fields`, or a new channel has EPG: drops the XMLTV chunk cache and queues `parse_programs_for_tvg_id` |
| `cache_previous_override_epg`, `refresh_epg_programs_for_override` (`:199-232`) | `ChannelOverride` `pre_save` / `post_save` | the same EPG refresh when the override's `epg_data` changes. No receiver on `ChannelOverride` delete |
| `update_channel_catchup_fields` (`:392-406`) | `ChannelStream` `post_save` / `post_delete` | rolls the catch-up flags up onto the `Channel` row |

A queryset `.update()` or `bulk_update` fires none of them (`apps/channels/epg_matching.py:311`'s docstring
says so for the EPG one). `Channel.updated_at` is `auto_now` (`apps/channels/models.py:429-432`).

### Provider slots, and what a probe would have to respect

- A tune reserves through `reserve_profile_slot(profile, redis_client)` (`apps/m3u/connection_pool.py:412-435`),
  called from `Channel.get_stream()` for each active profile, the default first (`apps/channels/models.py:620-639`).
  It runs the `reserve` op of `_SLOT_SCRIPT` (`:266` onward) with `ARGV` `(profile max, credential max)`: the
  op refuses when `count + 1 > max`, writes nothing on a refusal, and treats a max of `0` as "not counted"
  (`:296-316`). `release_profile_slot` runs `release` (`:438-447`). These are the only sanctioned writers of
  the counters (CLAUDE.md § Known defects, #513).
- The URL and user agent a tune uses come from `_resolve_live_stream_url(stream, account, profile)`
  (`apps/proxy/next_source.py:47`, applying the profile's `transform_url`, `:271`) and
  `M3UAccount.get_user_agent_string()` (`:435`).
- The #513 reconciler (`apps/proxy/slot_reconciler.py`) counts as holders only the relay's channels and the
  live VOD and catch-up records. A reservation it cannot see is safe only while it is younger than the widest
  **in-flight window** (`in_flight_windows()`; live is `2 × (2 + 5) + 0.1` ≈ 14 s from
  `apps/proxy/control_plane.py:37-41`, VOD is `2 × (10 + 10)` = 40 s from
  `apps/proxy/vod_proxy/multi_worker_connection_manager.py:104-105`), because runs are spaced at least twice
  that apart (`run_spacing_seconds()`, 80 s at the base) and every reserve and release moves the counter's
  version. A reservation older than that whose holder is invisible is treated as leaked and given back.
- `ffprobe` is in the runtime image: the base is `lscr.io/linuxserver/ffmpeg:version-9.0.2-cli`
  (`docker/DispatcharrBase:115`), and the DVR already runs it (`apps/channels/tasks.py:2975-2985`). Since
  ffmpeg 9.0 it verifies the provider's TLS certificate by default (CLAUDE.md § Test hooks).
- The `default` Celery worker is prefork (`docker/supervisord.d/celery-default.conf`, queue `celery`) and not
  monkey-patched, so the gevent `posix_spawn` rule does not bind it. The `dvr` worker runs threads ×20 for
  recordings and is not used here.
- `subprocess.TimeoutExpired` and `CalledProcessError` render the full command line in `str()`, so an argv
  carrying a provider URL leaks it through any log of the exception.

## Decisions

| | Decision | Why |
|---|---|---|
| **D1** | **A new Django app, `apps/catalog`.** It owns the parser, the classification, identity, decision and health tables, the Celery tasks and the admin API. `apps/channels` gains only two columns on existing tables (D7). The name is neutral, per `CONTEXT.md` § Mino. | `apps/channels` is already 17,579 lines and sits at the centre of the import mesh's one cycle (CLAUDE.md § Structural constraints). The new app imports `channels`, `m3u` and `epg`. **None of them may import `catalog` at module level.** In particular `apps/channels/models.py` must not, because of the boot trap. Catalog code reaches channels models by string FK (`"dispatcharr_channels.Stream"`; the label, not the directory) and imports them function-locally in tasks. |
| **D2** | **Classification lives in side tables, never on `Stream`.** `StreamClassification` is one-to-one with `Stream` (primary key = `stream_id`, `on_delete=CASCADE`). It stores only what the **parser** derives from the stream's own text. Everything that depends on other inputs (decisions, measurements, health, EPG) is applied when it is read or resolved, never stored on this row. | The refresh writes `Stream` in bulk with a fixed field list (`_bulk_update_stream_refresh_batches`, `apps/m3u/tasks.py:1080-1089`). Widening it would put classification on the ingest path. Keeping the row a pure function of the stream's text is what makes D6's invalidation one fingerprint. |
| **D3** | **A purpose-built, versioned parser, `apps/catalog/parse.py`**: pure functions, no ORM, no settings reads inside. Input `(name, group_title, tvg_id, convention)`. Output a frozen dataclass `Parsed(canonical_name, canonical_key, region, region_evidence, region_conflict, name_tier, tier_conflict, codec_hint, fps_hint, markers, variant, variant_conflict)`. `PARSER_VERSION` is an integer bumped on any behaviour change. The algorithm is phased (§ Parsing). | The existing `normalize_name` reads settings and drops the tokens this spec classifies. A pure parser can be golden-tested, property-tested and benchmarked without a database. |
| **D4** | **Region and variant are part of every identity, never a tiebreak.** `variant` holds feed-distinguishing markers that are not quality: `+1` / `+2` (timeshift feeds) and `east` / `west`. No automatic path ever joins two streams whose regions or variants differ. A stream is never placed automatically, only by an admin decision, if it has any of: an unknown region (`""`), an unresolved region conflict, a variant conflict, or an empty key. | This is the UK/NZ trap, structurally. "Sky Arts" GB and "Sky Arts" NZ differ by region, so they are different identities by construction, not by a threshold. |
| **D5** | **Decisions are keyed by a stable stream key and are single-valued per key.** The key is `xc:<account_id>:<stream_id>` when the provider gives an id. Otherwise it is `m3u:<account_id>:<sha1(canonical_key, region, variant)>`, from the stream's own parse **before** any pin, so a cosmetic rename (a tier or codec token, a prefix style, a group move) keeps it. A stream whose `canonical_key` is empty falls back to `m3u:<account_id>:raw:<sha1(name, group title, tvg_id)>`. Two entries in one account that parse to the same key share one decision, deliberately: same name, region and variant in one account are one feed for decision purposes. **Re-keying.** When classification changes a stream's key (a parser or convention change), a decision on the old key moves to the new key in the same transaction, if no current stream still holds the old key and no decision holds the new one. **Pruning.** Every decision row carries `last_seen_at`, refreshed (at most daily, one batched `UPDATE`) while some current stream holds its key. A daily task deletes decisions unseen for `decision_prune_days` (default 30), which also releases the `PROTECT` hold they place on an empty identity. `StreamAssignment` holds at most **one** row per key: either *assign to identity X* or *exclude*. `StreamRegionPin` holds at most **one** row per key. `PairRejection` holds one row per *(key, identity)*, and `IdentityPairRejection` one per unordered *(identity, identity)*. Replacing a decision is an upsert in one transaction, and revoking it is a delete. Every change **requests a resolve run**, and the resolver applies decisions on every run. **A region pin ends that stream's region conflict.** | `stream_hash` changes when a hashed field changes, and the rehash task merges rows (`core/tasks.py:719`). An XC key from the provider's own id survives both. A plain M3U entry has no provider id, and its hash defaults to including the name, so a rename gives a new `Stream` row; the parse tuple is the most stable thing it has. A key on the raw text (the earlier design) orphaned every decision on the first cosmetic rename and pinned its identity forever through `PROTECT`. Single-valued tables make contradictory decisions unrepresentable. |
| **D6** | **Invalidation is "parse when the text changes, derive everything else on every run".** The only cached computation is the parse: `fingerprint = sha1(PARSER_VERSION, convention_version(account), name, group title, tvg_id)`. Classification is idempotent and needs no provider download: it reads `Stream` rows and skips unchanged fingerprints. It runs (a) after each provider refresh, (b) when an account's naming convention is saved, (c) on the admin **Re-run**, and (d) on a **daily backstop** over every active account. Identities, conflicts, EPG binding and proposals are recomputed by every resolve run. The effective tier and the health band are computed when they are **read**. | Removing the cached derived state removes the class of missed invalidations rounds 1 and 2 found. Round 3 found that a fingerprint is checked only when classification runs. (b)-(d) make sure it runs without depending on the next provider refresh, and a failed run is simply retried by the next trigger. |
| **D7** | **Ordering control is two new columns on existing tables**: `Channel.stream_order_mode` (`auto` / `manual`, default `manual`) and `ChannelStream.pinned` (bool, default false). Under `auto`, pinned streams keep their relative admin order at the top, and every other stream is placed by D8. Under `manual`, nothing in this spec writes the channel's order. **An admin reorder of an `auto` channel switches it to `manual`.** A reorder is a request that changes the relative order of the streams kept on the channel. A **membership-only** edit (adding or removing streams, with the retained streams' relative order unchanged) keeps the mode. The response says when the mode flipped, and the UI shows the badge and a one-click "back to Auto". **Restoring a snapshot sets the channel to `manual`** under the same lock. | R3 says admin pins override everything. "Never destroy an admin's manual ordering silently" is met three ways. Every existing channel starts `manual`. A later drag is never overwritten, because it flips the channel visibly. A restore sticks. |
| **D8** | **The ordering function, `rank_members(channel)`**, is shared by the reorder pass and by acceptance (§ Proposals). The sort key for unpinned streams is: (1) **effective tier**, best first: `UHD > FHD > HD > UNKNOWN > SD`; (2) **health band**: `good > fair > unknown > poor` (§ Reliability); (3) `backup` marker last; (4) `fps_hint` descending; (5) the stream's current `order` value, then its current position. Inactive accounts and stale streams sort last. | R4: tier, then reliability. `UNKNOWN` sits above `SD` and below `HD` because an unlabelled provider stream is more often 720p or 1080p than 576i (confirmed by R7). Key 5 is explicit rather than left to the stability of the sort. |
| **D9** | **The relay's switch policy does not change.** The failover keeps "the next candidate after the current one, wrapping" (`order_alternates_from_current`). On a tier-sorted list that already walks down in quality, and it wraps back up to the top tier only once the lower ones are exhausted. **No climb-back** (returning to a higher tier while a lower one still plays) and **no same-tier-before-lower preference** for the streams *before* the current one in its own tier. Both are non-goals (§ Non-goals). | A switch-policy change is a live-path behaviour change. It needs a parity-matrix row and a pinned E2E, and the owner did not ask for one. The headline behaviour, best first and down in quality on failure, follows from the order alone. |
| **D10** | **Catalog writes are short, never queue behind other writers, and lose most contention: best effort, not a guarantee.** No existing writer changes its locking. **Admin-triggered catalog actions** (accept, restore, a pin toggle, auto-order enable, detach, bind, unbind, dismiss) and **the reorder pass** each run one short transaction, for one channel and one identity:<br>(1) `SET LOCAL lock_timeout = '100ms'`.<br>(2) Lock every row the action will write or reference, up front, with `NOWAIT`. Catalog rows come first (`ContentIdentity`, then `ChannelProposal`), then non-catalog rows in a fixed order: the `Channel` row (`FOR NO KEY UPDATE`, or `FOR KEY SHARE` when bind only references it), its `ChannelStream` rows (`FOR UPDATE`, id order), the `ChannelOverride` row for detach, and the `Stream` rows of added members (`FOR KEY SHARE`, id order).<br>(3) Write. **One rule for the receivers in § Model signals: database effects run inside the transaction, external effects (Redis, the Celery broker) run only from `transaction.on_commit`.** The catalog writes `Channel` columns with `QuerySet.update()`, which fires no receiver, and then states each receiver's effect itself:<br>- `refresh_epg_programs`: whenever the action writes `epg_data` (accept onto a manual target, a new channel with EPG, a detach fold that carries an override's EPG), it registers one `on_commit` callback that calls `invalidate_epg_chunk_cache()` (`apps/output/streaming_chunk_cache.py:245`) and `dispatch_program_refresh_for_epg_ids({epg_id})` (`apps/epg/tasks.py:2477`, the helper sync's bulk path already uses). The task therefore runs only after the mapping is committed, so `is_epg_mapped_to_channel` (`apps/epg/tasks.py:1672-1676`) sees it; a rollback (409, deadlock) drops the callback; and no Redis scan or broker publish happens while channel locks are held.<br>- A new channel is created with `save()` **without** `epg_data`, so its `post_save` does nothing external (the compact-number receivers return on `created`, and `refresh_epg_programs` sees no EPG); `epg_data` is then set by `.update()` under the rule above.<br>- The two compact-number receivers: nothing to do, because the catalog never writes `hidden_from_output`.<br>- `update_channel_catchup_fields`: a member is added by creating its `ChannelStream` row, as the channel serializer does. That fires this receiver synchronously, which is correct under the rule: its whole effect is one `.update()` on the `Channel` row the action already holds.<br>- `update_channel_tvg_id_and_logo` (`m2m_changed`): not fired, as on the serializer's path; a new channel takes its `tvg_id` from the identity.<br>- The `ChannelOverride` receivers: detach deletes the override, which has no delete receiver, and the fold writes the channel's own columns, so neither fires; any EPG effect follows the first bullet.<br>Order-only changes use `bulk_update(["order", "pinned"])`, because no receiver reads either column.<br>**The resolver** locks catalog rows one identity per transaction, waits for them normally, and holds nothing else, so it cannot close a cycle.<br>On `LockNotAvailable` (55P03) or `DeadlockDetected` (40P01), a catalog transaction rolls back. A background pass retries the channel next pass. An admin action answers 409 `{"busy": true}`, and the UI says "busy, retry".<br>**The reorder pass also skips any channel saved within the last `reorder_quiet_seconds` (default 60), judged by `Channel.updated_at` (`auto_now`, `apps/channels/models.py:429`).** This is a recent-`Channel.save()` heuristic, not a recent-edit signal. A `PATCH` that changes only streams or overrides can skip `Channel.save()` (`apps/channels/serializers.py:640`, `:663-669`), and then does not move `updated_at`. `NOWAIT` remains the actual protection. The catalog's own channel writes do not move `updated_at` either, because `QuerySet.update()` never applies `auto_now`; S6's signals test pins it.<br>**Rehash takes no new lock.** It only carries pins on collision (`core/tasks.py:726-736`). | **Who waits on whom.** Catalog actions never wait at acquisition. After acquisition they wait only through the 100 ms backstop, on locks they could not name in advance. Examples: a unique-index check when an existing writer has an uncommitted insert of the same `(channel, stream)` (`apps/channels/models.py:939-942`, `serializers.py:723-725`), or an FK key-share on a referenced group, logo or profile row. Existing writers can wait on catalog rows: deleting a channel runs `SET_NULL` onto `ContentIdentity.channel` and `ChannelProposal.channel`, and cascades onto `ChannelOrderSnapshot` (`apps/channels/api_views.py:919-933`). A catalog action holding those rows never waits beyond the backstop, so such a wait is short.<br>**A deadlock is still possible**, during a backstop wait, and **Postgres may choose either side as the victim**. Whichever backend's `deadlock_timeout` expires first runs the check and aborts. The catalog side catches it and retries or answers 409. An existing writer chosen as the victim fails exactly as a deadlock between two concurrent admin edits can make it fail today. The base handles `DeadlockDetected` nowhere: `git grep -n "DeadlockDetected\|40P01" 149678aa -- '*.py'` matches only tests. So an API request answers 500 and the admin retries, and a Celery task fails that run and the next scheduled run redoes it. The short transactions, `NOWAIT` and the quiet-period skip make this rare, not impossible. Round 6 showed that a timing argument cannot promise more. |
| **D11** | **Reliability is counted per exposure, at ingest, deduplicated per event.** An **exposure** is a stream being started (`channel_start`) or switched in (`stream_switch`). A **failure** is a failover away from it or a connection failure on it, plus a quarter-weight for each buffering episode. A receiver on the `relay_event_applied` signal handles each relevant event in its own transaction. It first inserts a `RelayEventReceipt(relay_boot, seq)`, which is unique. **Only if the insert succeeds** does it decay and update the stream's two counters. Receipts are kept for 30 days. The band is computed when it is read. | Round 3 showed a high-water mark is unsafe: a batch whose HTTP attempts timed out can still be applied by Django **after** a later batch, so a watermark would discard it. A unique receipt per event is order-free. Exposure counting needs no playback segments, and R4 asks only for "observed health (recent failovers, buffering events, connect failures)". |
| **D12** | **Everything is off until the owner turns it on, in three switches**, in a new settings group `catalog_settings`: `classify_enabled` (parse, tier, identities, review queue; it never writes a channel), `auto_order_enabled` (D8 writes for `auto` channels) and `remeasure_enabled` (D17's probes; it needs `classify_enabled`). Turning `classify_enabled` on **backfills**: it dispatches classification for every active account, then one resolve. Turning `auto_order_enabled` on goes through a **preview** endpoint. The preview lists every channel whose order would change, and the owner picks which channels to set to `auto`. Before the first write, each chosen channel's prior order is saved in `ChannelOrderSnapshot`. | R3 asks for automatic reordering of existing channels. The no-silent-destruction rule asks for it to be visible and reversible. |
| **D13** | **New channels and new members are proposals, never automatic, and the target channel is always explicit.** A `ChannelProposal` has `kind` `new_channel` (the identity has no bound channel) or `add_streams` (the identity has a bound channel that lacks some of its members). Several existing channels can belong to one identity: these **candidate channels** are computed and shown, never stored. **Binding the identity to one channel is an explicit admin act**, and changes no channel. Accepting `add_streams` **keeps the target's `stream_order_mode`**, unless the admin ticks "order this channel automatically". A channel created from `new_channel` starts `auto`, and is ranked by D8 **before acceptance commits**. Adult content is propagated conservatively (§ Proposals). | R3: propose new, admin accepts. Adding a stream to a channel changes what clients may receive, so it needs acceptance. Choosing among several candidates is a judgement about which channel the admin's clients use, and the spec must not make it. |
| **D14** | **R2's optional LLM assist is deferred to its own spec** (ruling R5). This spec builds no part of it: no settings, no env var, no payload, no PR. The resolver passes leave a plain list of unplaced streams and open fuzzy matches. A later spec can read that list without changes here. | Rounds 2 and 3 each found a credential path through a sanitiser. The owner ruled that the LLM gets its own design and review, after this lands. |
| **D15** | **The Go relay changes in two small PRs (S1a, S1b), and only to report.** Both attribute what they report to the **source an attempt actually runs**, captured once when that attempt starts. S1a adds `relay_boot` and `seq` to every event. It adds `from_stream_id` and `trigger` to `stream_switch`, and the attributed `stream_id` to `channel_buffering`, `channel_error` (`connection_failed`) and `channel_stop`. S1b posts `stream_stats` again, from storage owned by the attempt. **When a pending source is adopted does not change** (§ S1a). Nothing the relay decides changes, and the status endpoint's `stats` view is unchanged. | M1 and M2. A pending switch (an operator `Advance` parked during retry backoff) is still adopted only after the running attempt returns (`relay/channel/channel.go:555-566`). Until then the running source is the one producing lines. Attributing to the source being run is therefore exactly right, and needs no change to adoption. |
| **D16** | **Naming-convention overrides live per account** in `M3UAccount.custom_properties["catalog"]`, a validated sub-dict: `default_region`, `region_tokens` (token → ISO code, or `null` to treat it as noise, e.g. `{"AR": null}`, where the provider's `AR:` means Arabic, not Argentina), `strip_prefixes` / `strip_suffixes` (literal strings), and `region_from` (an ordered subset of `["tvg_id", "name", "group", "default"]`). `convention_version` is a hash of that sub-dict. Saving it dispatches classification for that account (D6). **The backend (validation, `convention_version`, the save trigger) ships in S3**, settable through the account API, so a single-country provider with no region prefixes gets `default_region` before S4 starts refusing unknown-region streams. S8 adds only the form section and live preview. | Conventions are per provider, so the owner fixes them where the provider is configured. The sub-dict needs no migration, and is validated by a serializer, so a typo is a 400, not a silent no-op. |
| **D17** | **A measurement never expires back to the name tier; it is re-measured at expiry (R8).** The effective tier is the measured tier whenever a `MeasuredResolution` row exists, whatever its age. `measured_ttl_days` (default 30) is the age at which a measurement is **due**. A due stream that is a member of at least one channel is re-measured by one short probe (§ Re-measurement at expiry), reserving its provider slot through the #513 script with one slot of headroom. A successful probe replaces the measurement, which may move the tier up or down. A refused, failed or timed-out probe leaves the last measured tier standing and is retried with backoff, up to `remeasure_max_failures`. Only due streams are probed. **An unmeasured stream is never probed, and nothing probes in bulk**: R1 otherwise stands. Off by default (`remeasure_enabled = false`). | R8 narrows R1. Reverting to the name tier on expiry let a `4K`-named SD feed climb back to the top every TTL period (2026-11-11 finding 5). Keeping the old measurement forever would freeze a feed the provider has since upgraded. A probe is the only way to learn which, and limiting it to streams that were already measured keeps R1's bound on provider traffic: the probed set never grows beyond what playback already reached. Off by default because a probe is a provider connection nobody asked to watch, and some providers penalise those; with it off, the last measurement simply stands. |

## Data model

All new tables are in `apps/catalog`, except the two `apps/channels` columns. **Each table lands in the PR named
beside it, and no PR's migration references a table a later PR creates.**

**S3**

- **`StreamClassification`**, one-to-one with `Stream` (PK `stream`, CASCADE). It holds the parser's output only:
  - `stream_key` (char(80), indexed; D5's key) and `fingerprint` (char(40));
  - `canonical_name` and `canonical_key` (char(512), bounded by § Parsing);
  - `region` (char(2); `""` means unknown), `region_evidence`, `region_conflict`;
  - `variant`, `variant_conflict`;
  - `name_tier` (small int: `0` UNKNOWN, `1` SD, `2` HD, `3` FHD, `4` UHD; D8 sets the rank, not the integer),
    `tier_conflict`;
  - `codec_hint`, `fps_hint`, `markers`, `classified_at`.
- **`MeasuredResolution`**, one-to-one with `Stream` (CASCADE): `height`, `width` (null), `observed_at`
  (indexed) and `source` (`playback` / `probe`). It is written **only** by the catalog's receiver for a
  `stream_stats` event with `relay: "go"` that carries a resolution (`source = playback`), and from S3b by the
  re-measurement probe (`source = probe`). No REST serializer exposes it as writable.
- The **D16 convention backend**: validation of `custom_properties["catalog"]` in the M3U account serializer,
  `convention_version`, and the save trigger.
- The **`relay_event_applied`** signal in `core/relay_events.py`. It is sent after each event, including
  `stream_stats`, and carries the validated event dict. Receiver exceptions are caught and logged, so a batch
  never 500s.

**S3b**

- Two columns on `MeasuredResolution`: `remeasure_failures` (small int, default 0) and `next_remeasure_at`
  (null, indexed). A playback measurement resets both. Defaults only, so the migration needs no data pass.

**S4**

- **`ContentIdentity`**: `anchor` (char(600); see § Identity resolution), `region`, `variant`,
  `unique(anchor, region, variant)`; `display_name`; `tvg_id` (null); `epg_data` (FK `epg.EPGData`, null,
  SET_NULL); `epg_state` (`bound` / `none` / `ambiguous` / `pinned`); `channel` (FK
  `dispatcharr_channels.Channel`, null, SET_NULL; set **only** by an admin, D13); `created_at`.
- **`IdentityMember`**: `stream` (OneToOne, CASCADE), `identity` (FK, CASCADE), `how` (`decided` / `auto_tvg` /
  `auto_key`). Each resolve run **diffs** it against the wanted placement and writes only what changed (§ Writes).
  A stream with no row is unplaced, and the API gives the reason: `conflict`, `unknown_region`, `empty_key`,
  `excluded`, `ambiguous_key`, `fuzzy_pending` or `review`.
- **`IdentityMatch`**, the review queue: `stream` (FK), `identity` (FK, null), `related_key` (char, null; the
  near-matching key when no identity holds it), `source` (`fuzzy` / `region_conflict` / `unknown_region` /
  `same_key`), `match_key` (char, not null: `"<source>:<identity id or ''>:<related_key or ''>"`), `score`
  (0-100), `suggested_region`, `created_at`; `unique(stream, match_key)`. The non-null `match_key` carries the
  natural key, so no unique constraint over nullable columns is needed. A row exists exactly while the
  resolver wants the suggestion; admin decisions live in the decision tables, never on this row (§ Writes).
- **`FuzzyBlockResult`**: `region`, `variant`, `first_token`, `signature`, `pairs` (JSON list of
  `[key_a, key_b, score]`, one per near-matching pair, with `key_a < key_b`), `checked_at`;
  `unique(region, variant, first_token)`. `signature` is the sha1 of the block's sorted key set **plus**
  `fuzzy_threshold`, the scorer name and `FUZZY_VERSION`, a constant bumped whenever blocking or scoring
  changes.
- **`StreamAssignment`** (`stream_key` **unique**, `account`, `kind` `assign`/`exclude`, and `identity`, which
  a check constraint requires when `kind = assign`), **`StreamRegionPin`** (`stream_key` **unique**, `account`,
  `region`), **`PairRejection`** (`unique(stream_key, identity)`) and **`IdentityPairRejection`** (`identity_a`,
  `identity_b`, a check constraint `identity_a_id < identity_b_id`, `unique(identity_a, identity_b)`). Each
  records `decided_by` and `decided_at`; the three stream-keyed tables also carry `last_seen_at` (D5's
  pruning). **Their identity FKs are `PROTECT`** (see the deletion rule in § Identity resolution).
- **`IdentityEpgPin`**: `identity` (OneToOne, PROTECT from the identity side), `epg_data` (FK, CASCADE; null
  means "no EPG"), `decided_by`, `decided_at`.
- **`ChannelProposal`**: `identity` (FK), `kind`, `channel` (FK, null), `stream_ids` (JSON list),
  `members_hash`, `revision`, `state` (`open` / `accepted` / `dismissed` / `withdrawn`), `created_at`,
  `decided_at`, `decided_by`. A partial unique index allows at most one `open` row per `(identity, kind)`.
- **`CatalogResolveState`**, a single row: `requested` (bigint), `completed` (bigint), `last_run_at`.

**S5**

- **`StreamHealth`**, one-to-one with `Stream` (CASCADE): `exposures` and `failures` (floats, decayed),
  `decayed_at`, and lifetime counters for display (`starts`, `failovers_away`, `connect_failures`,
  `buffering_episodes`).
- **`RelayEventReceipt`**: `relay_boot` (char(16)), `seq` (bigint), `received_at` (indexed),
  `unique(relay_boot, seq)`. It is written only for health-relevant events, so a handful of rows per tune. Rows
  older than 30 days are pruned daily. That is far longer than any retry: the relay makes at most two attempts per
  batch (`relay/control/nextsource.go:429-448`).

**S6**

- `Channel.stream_order_mode` (char(8), default `"manual"`), `Channel.sync_detached` (bool, default `False`;
  § Proposals, Detach) and `ChannelStream.pinned` (bool, default `False`), in
  `apps/channels/migrations/0040_*`. The tip at the base is `0039_channel_hls_output_profile.py`, and the plan
  re-checks the number at its seed. All three columns have defaults, so the migration needs no data pass.
- **`ChannelOrderSnapshot`**: `channel` (FK, CASCADE), `stream_ids`, `pinned_ids`, `reason` (`enable_auto` /
  `accept_proposal`), `created_at`. The last five per channel are kept.

## Parsing (S2)

The parser runs in fixed **phases**.

1. **Normalise.** Apply NFKC and casefold. Replace `&` with ` and `. Remove the account's `strip_prefixes` /
   `strip_suffixes` (literal and case-folded, at most one of each). Nothing is truncated here.
2. **Tokenise.** Split on whitespace and the separators `| [ ] ( ) : - _ / ·`. Keep `+1` / `+2` as single
   tokens. Record for each token whether it was **delimited**: bracketed (`[US]`, `(UK)`, `|NZ|`), or, as the
   first token, followed by `:` / `-` / `|` (`UK:`, `NZ -`).
3. **Classify decorations.** First, the **unconditional** decorations are marked: tier, codec and fps tokens and
   `+1` / `+2`, which are decorations wherever they appear. Then **protected phrases** in `regions.py` are matched
   on the **projection** of the token sequence with those unconditional decorations removed, so a quality label
   inside a phrase cannot break it: `WWE HD Raw` projects to `wwe raw` and `UK FHD Gold` to `uk gold`. A matched
   phrase's tokens are words wherever they sit: `uk gold`, `uktv`, `wwe raw`, and any others the plan or the R10
   demo finds. Then each remaining token is checked against these classes, and a decoration is removed from the
   word list. Tier, codec and fps tokens, and `+1` / `+2`, are decorations wherever they appear. The
   **word-shaped** marker and variant tokens (`backup`, `bk`, `raw`, `alt`, `test`, `east`, `west`) are
   decorations only when **delimited**, or when they sit in the name's **trailing run**: the longest suffix of
   tokens each of which is a decoration of another class, `+1` / `+2`, a word-shaped marker or variant, or a
   region token that phase 4 could consume undelimited. Anywhere else they are words, so `Test Match Special`
   keeps `test` and `West Ham TV` keeps `west`.

   | Class | Tokens (case-folded) | Effect |
   |---|---|---|
   | tier | `8k`, `4k`, `uhd`, `2160p` → UHD; `fhd`, `fullhd`, `1080p`, `1080i` (and the two-token `full hd`) → FHD; `hd`, `720p` → HD; `sd`, `576p`, `576i`, `480p`, `lq` → SD | `name_tier` is the **highest** present; `tier_conflict` when two different tiers occur |
   | codec | `hevc`, `h265`, `x265` → hevc; `h264`, `avc` → h264 | hint only |
   | fps | `\d{2,3}fps`, `50p`, `60p` | `fps_hint` is the highest present |
   | marker | `backup`, `bk`, `raw`, `alt`, `test` | kept in `markers` (sorted, de-duplicated) |
   | variant | `+1`, `+2`, `east`, `west` | kept in `variant`; two different ones set `variant_conflict` |

4. **Extract the region from the name.** This works on the tokens left after phase 3; protected-phrase tokens
   are words. A region-table token is consumed as region evidence when it is delimited (anywhere), or when it is
   first or last **and at least one other word remains and it is not a word-shaped code** (§ Region). A lone
   remaining region token is kept as a word. At most one region token is consumed. Two different qualifying
   region tokens set `region_conflict`.
5. **Group fallback.** If the name gave no tier, tier tokens in the group title are used. Group region evidence
   is § Region's source 3.
6. **Key.** Map the standalone tokens `one` … `ten` to `1` … `10`. Drop pure-punctuation tokens, then join the
   remaining words with single spaces. Nothing else is aliased: no stemming, and `sport` ≠ `sports`.
   - **Empty key**: if no word remains (`HD`), `canonical_key = ""` (D4).
   - **Overflow**: if the key exceeds 512 characters, it becomes its first 495 characters, then `~`, then the
     first 16 hex digits of the full key's SHA-1. `canonical_name` uses the same rule.

**Stability properties, stated exactly.** These hold for the canonical key only:

- `parse(canonical_name).canonical_key == canonical_key`.
- Inserting or removing a tier, codec or fps token anywhere (inside a protected phrase included), or a marker token that is delimited or inside the
  trailing run, never changes `(canonical_key, region, variant)`. (A word-shaped token outside the trailing run
  is a word by design, and a variant token changes `variant` by definition, so the property claims neither.)
- `name_tier` is the same whatever order the tier tokens appear in.

**Golden cases written into the spec** (the corpus holds many more):

| Input (name / group) | key | region | variant | tier / flags |
|---|---|---|---|---|
| `UK: Sky Sports Main Event FHD` / `Sports` | `sky sports main event` | GB | | FHD |
| `SKY SPORTS MAIN EVENT UK HD` / `Sports` | `sky sports main event` | GB | | HD |
| `\|NZ\| Sky Sport 1 HD` / `NZ Sports` | `sky sport 1` | NZ | | HD |
| `UK: Sky Arts HD` / `Entertainment` | `sky arts` | GB | | HD |
| `\|NZ\| Sky Arts HD` / `Entertainment` | `sky arts` | NZ | | HD |
| `Sky Arts UK FHD HEVC 50FPS` / `` | `sky arts` | GB | | FHD |
| `UK Gold` / `UK Entertainment` | `uk gold` | GB (group) | | UNKNOWN |
| `UK: Sky One +1 HD` / `` | `sky 1` | GB | `+1` | HD |
| `Sky One +1 +2` / `` | `sky 1` | | | UNKNOWN, `variant_conflict` |
| `Sky Cinema 4K HD` / `` | `sky cinema` | | | UHD, `tier_conflict` |
| `ESPN` / `US \| FHD Sports` | `espn` | US (group) | | FHD (group) |
| `UK HD` / `` | `uk` | | | HD (lone `uk` kept as a word) |
| `HD` / `` | `""` | | | HD, empty key |
| `AR: MBC 1` / `` (default table) | `ar mbc 1` | | | UNKNOWN |
| `A & E` repeated to 600 chars | hashed-overflow key, ≤ 512 | | | |
| `Apple TV` / `` | `apple tv` | | | UNKNOWN (`tv` is word-shaped, not Tuvalu) |
| `At The Races` / `` | `at the races` | | | UNKNOWN (`at` is not Austria) |
| `Capital FM` / `` | `capital fm` | | | UNKNOWN |
| `Me TV` / `` | `me tv` | | | UNKNOWN |
| `UK: Apple TV` / `` | `apple tv` | GB | | UNKNOWN, **no** `region_conflict` |
| `\|CH\| SRF 1 HD` / `` | `srf 1` | CH (delimited) | | HD |
| `UK: Sky News` / ``, tvg_id `skynews.tv` | `sky news` | GB | | UNKNOWN, **no** `region_conflict` (`.tv` is not evidence) |
| `WWE Raw HD` / `` | `wwe raw` | | | HD (protected phrase; no `raw` marker) |
| `WWE HD Raw` / `` | `wwe raw` | | | HD (phrase matched on the projection) |
| `UK FHD Gold` / `UK Entertainment` | `uk gold` | GB (group) | | FHD (phrase matched on the projection) |
| `Test Match Special` / `` | `test match special` | | | UNKNOWN (no `test` marker) |
| `West Ham TV` / `` | `west ham tv` | | | UNKNOWN (no `west` variant) |
| `Discovery East UK HD` / `` | `discovery` | GB | `east` | HD (trailing run) |
| `CNN Backup` / `` | `cnn` | | | UNKNOWN, markers `backup` |

With `region_tokens: {"AR": null}`, `AR: MBC 1` becomes `mbc 1` with no region. S2's golden test pins it,
since the parser takes the convention as input; S3 makes it settable (D16).

## Region

**The region table** maps tokens to ISO 3166-1 alpha-2 codes: two-letter codes, a curated alias set (`uk` → GB,
`usa` → US, `aus` → AU, …), and English country names. Tokens that are also language codes or are ambiguous are
**absent** from the default table, and count only through an account's `region_tokens`. These are `ar`, `en`,
`lat` / `latino`, `int`, `es` and `pt`.

**Word-shaped codes.** Many two-letter codes are also common words or broadcast terms. `regions.py` carries
them as one named list, `WORD_CODES`: at least `am`, `at`, `be`, `by`, `ch`, `co`, `do`, `fm`, `go`, `hi`, `id`,
`in`, `io`, `is`, `it`, `la`, `me`, `mo`, `my`, `no`, `pa`, `so`, `to` and `tv`, plus any the R10 demo finds. A
word-shaped code counts as region evidence **only when delimited** in the name or group (`CH:`, `[IT]`,
`|NO|`). It never counts as an undelimited edge token and never as a tvg_id suffix. `us` is deliberately not
in the list: `ESPN US` is far more common in live lineups than a title ending in "us", and a region pin fixes the
exception. An account can still map any token through `region_tokens`.

**Parsed evidence, strongest first.** The account's `region_from` may reorder or drop any of these sources:

1. `tvg_id`: the final dot-segment of `tvg_id` is a region-table token that is not a word-shaped code
   (`skynews.tv`, `x.co` and `y.me` give no region).
2. `name`: § Parsing phase 4.
3. `group`: a region token or a country name in the group title.
4. `default`: the account's `default_region`.

**Conflict.** If `tvg_id` and `name` give different regions, or the name holds two qualifying region tokens, the
parse sets `region = ""` and `region_conflict = true`.

**At resolve time**, a `StreamRegionPin` overrides all of the above and clears the conflict. A conflicted stream
without a pin is **review-only**. It gets one `IdentityMatch(source=region_conflict)` for each identity with the
same key in each region that was claimed.

EPG data is **not** region evidence. It is used only for binding, below.

## EPG binding (S4)

The catalog does not call `apps/channels/epg_matching.py`, which takes the first row for a tvg_id in priority
order whatever its region (§ Verified facts). Each resolve run recomputes the EPG binding of every identity that
is not pinned:

1. **Pin.** An `IdentityEpgPin` wins (`epg_state = pinned`). A pin with `epg_data = null` means "no EPG". If the
   pinned `EPGData` row is deleted, the pin cascades away and derivation resumes.
2. **No tvg_id.** An identity without a tvg_id gets `epg_state = none`.
3. **Collect.** Take every active `EPGData` row with that tvg_id (case-insensitive). Each row's region is
   `EPGSource.custom_properties["region"]` when that is set (an optional field on the EPG form, S7), else the
   tvg_id's suffix region, else unknown.
4. **Filter.** Keep the rows whose region equals the identity's region. If there are none and the identity's
   region is known, keep the rows of unknown region instead.
5. **Select.**

   | Kept rows | Result |
   |---|---|
   | none | `none` |
   | all from **one** source | that source's row, `bound` |
   | several sources, **at least one with a known region** | highest `EPGSource.priority`, ties to the lowest `EPGSource.id`, `bound` |
   | several sources, **all of unknown region** | `ambiguous`, no `epg_data`; listed for the admin to pin |

## Quality tier (S3)

- **Name tier**: from the parse.
- **Measured tier**: read from `MeasuredResolution` (written only from the relay's stats events, and from S3b by
  the re-measurement probe), by **height**: ≥ 2000 → UHD, ≥ 1000 → FHD (1080i counts), ≥ 700 → HD,
  otherwise SD.
- **Effective tier**: computed when it is read. It is the measured tier whenever a `MeasuredResolution` row
  exists, **whatever its age** (D17, R8), otherwise the name tier. The API reports which one it used, the
  measurement's `source` and age, and `due` when the age exceeds `measured_ttl_days` (default 30).

A REST write to `Stream.stream_stats` cannot touch `MeasuredResolution`. Nothing reverts to the name tier on
expiry: a due measurement keeps its tier until a newer measurement, from playback or from S3b's probe, replaces
it. At the S3 stopping point, before S3b exists, a measurement therefore stands indefinitely, which is the state
`remeasure_enabled = false` keeps afterwards. New measurements reach a channel's order at the next reorder
pass. `video_bitrate` and `source_fps` are displayed but not used to rank (R7; a bitrate tiebreak is a possible later
follow-up, not in scope).

## Re-measurement at expiry (S3b, R8)

The one exception to R1's "no active probing". It is deliberately small: one task, one subprocess per probe,
and the existing slot script.

**What is probed.** A stream is a **candidate** when all of these hold: `remeasure_enabled` and
`classify_enabled` are on; it has a `MeasuredResolution` whose `observed_at` is older than `measured_ttl_days`;
`next_remeasure_at` is null or past; `remeasure_failures < remeasure_max_failures` (default 4); it is not stale;
its account is active; it is a member of at least one channel; and **no channel it is on has Redirect as its
effective stream profile** (`Channel.get_stream_profile()`, `apps/channels/models.py:493`). **A stream with no
measurement is never a candidate**, so the probed set is a subset of what playback already reached, and nothing
is probed in bulk.

**A playing stream is not probed.** Under a subprocess profile, S1b posts its stats every 30 s with the
resolution, so its `observed_at` never ages past the TTL and it never becomes a candidate. A stream that was
measured once and now plays through **Proxy** can age while playing; the relay registers Proxy channels, so
before each probe the task asks the relay for its channel list (`relay_client`, as the #513 reconciler does) and
skips the candidate if the relay lists it as a channel's current `stream_id` (`relay/httpapi/channels.go:207-233`).
If the relay cannot answer, the run starts no further probe. **Redirect is excluded by the channel rule above,
not by the list**: Redirect playback registers no channel (`relay/httpapi/stream.go:282-290`), so the list
cannot see it.

**Where and when.** `remeasure_expired()` is a Celery task on the `celery` queue, consumed by the default
prefork worker (`docker/supervisord.d/celery-default.conf:2`; not monkey-patched, so a plain `subprocess.run`
is correct; never the `dvr` queue), from a beat entry every 10 minutes. It takes
`pg_try_advisory_lock(catalog_remeasure)` and returns if another run holds it. It walks candidates oldest
`observed_at` first, **at most one per account**, and **starts at most `remeasure_max_per_run` (default 10)
probes per run**. A refusal costs one script call and no provider connection, so it does not count against
that budget; the walk stops after `10 × remeasure_max_per_run` candidates. Probes run **one after another**, so
at most one probe is open on the whole instance at any moment.

**Each probe.**

1. **Re-check, then fix the generation.** Immediately before the probe, re-read the candidate's
   `MeasuredResolution` and re-evaluate every candidate condition above, the relay check included. If any fails
   (playback measured it since selection, a channel moved to Redirect, the stream went stale), skip it with
   outcome `skipped`. Otherwise remember the row's `observed_at` as the **selected generation**.
2. Pick the profile as a tune would (`apps/channels/models.py:620-631`): the account's active default profile,
   then its other active profiles. **Skip any profile with `max_streams = 1`** (see headroom).
3. Build the URL with `_resolve_live_stream_url(stream, account, profile)` and the user agent with
   `account.get_user_agent_string()`, both before reserving, so the slot is held only for the subprocess. This
   path, and the reservation's own fingerprint derivation, both reach `transform_url`, which is credential-safe
   only after prerequisite **P1** (§ Credentials).
4. **Reserve with one slot of headroom**: `reserve_profile_slot` gains an optional `headroom=0` argument and
   passes `max(profile.max_streams - headroom, 0)` and `max(cred_max - headroom, 0)` to the unchanged `reserve`
   op. The probe passes `headroom=1`, so the reserve succeeds only if, after the probe takes its slot, at least
   one more remains on both the profile and the credential counter. The Lua script does not change, so the
   fake-parity tests (`apps/m3u/tests/test_slot_script.py`) still hold it. A max of `1` would become `0`, which
   the script reads as "not counted", which is why step 2 skips such profiles: probing would need their only
   slot. A profile with `max_streams = 0` is unlimited, and the probe is uncounted there exactly as a tune is.
   A refusal on every profile is **refused**: the Lua writes nothing, and the catalog sets
   `next_remeasure_at = now + 1 h` on that candidate, conditional on the selected generation, **without**
   counting a failure. The deferral is what lets later accounts' candidates through when an older one sits on a
   permanently full provider.
5. Run `timeout -k 2 15 ffprobe -v error -rw_timeout 5000000 -analyzeduration 5000000 -probesize 5000000
   -user_agent <ua> -select_streams v:0 -show_entries stream=width,height -of json <url>` with
   `subprocess.run(argv, stdout=PIPE, stderr=DEVNULL, timeout=20)`. **The wall-clock bound does not depend on
   the Python parent**: coreutils `timeout` is its own process, puts itself and `ffprobe` in their own process
   group, sends `SIGTERM` at 15 s and `SIGKILL` at 17 s, and keeps doing so if the Celery child is killed
   (`SIGKILL` from a hard time limit, an OOM kill), because nothing kills it with its parent. `ffprobe`'s own
   `-rw_timeout` and analysis limits usually end it within about five seconds. The runtime image is
   Ubuntu-based (`docker/DispatcharrBase:24-41` installs from Ubuntu's keyserver and a PPA keyed on
   `lsb_release`), where coreutils is an Essential package, and S3b's smoke test asserts that `timeout` and
   `ffprobe` both resolve in the CI base image. This is the Python counterpart of the relay's `Pdeathsig`
   rule (CLAUDE.md § Known defects: a provider-reading subprocess must not outlive its parent).
6. In `finally`, `release_profile_slot(profile.id)`. The probe is then one more holder on that profile for at
   most `PROBE_HOLD_SECONDS = 20` (the 17 s kill bound plus margin), with exactly the release-pointer behaviour
   two viewers on one profile already have (#356, covered by the reconciler's carry rule).
7. **Write the result only onto the selected generation.** Two writers touch this row: the S3 playback receiver
   (unconditional, because a playback measurement is newer truth) and this task. Every probe write is one
   `UPDATE … WHERE stream_id = <id> AND observed_at = <selected generation>`; zero rows updated means playback
   superseded the selection while the probe ran, and the result is discarded with outcome `superseded`.
   - **Success** (exit 0 and a positive `height`): `height`, `width`, `observed_at = now`, `source = probe`,
     `remeasure_failures = 0`, `next_remeasure_at = null`. The tier may go up or down.
   - **Failure** (non-zero exit, timeout, no video stream, unparsable output): the measurement is unchanged,
     `remeasure_failures += 1`, `next_remeasure_at = now + 6 h × 2^(failures − 1)`. At
     `remeasure_max_failures` the stream stops being a candidate until playback measures it again (a playback
     measurement resets both columns). **The last measured tier stands throughout.** A probe failure does not
     feed health (§ Reliability counts relay events only).

**Headroom, stated exactly.** A probe never takes a slot when fewer than two are free on its profile and its
credential counter. It can still occupy one of the free slots for up to 20 s, so a second viewer arriving in
that window on a profile that had exactly two free may be refused there; `get_stream()` then skips to that
channel's next stream rather than waiting (§ Verified facts). That is the whole cost, and it is why the default
is off and only one probe is ever open.

**The #513 reconciler.** A probe's reservation is not in the reconciler's holder set. It is safe for the same
reason a tune's reservation is safe before the relay lists the channel: it is an **in-flight** reservation, and
every reserve and release moves the counter's version, so no pair of reconciler runs spaced
`run_spacing_seconds()` apart can see an unchanged version across a live probe. The argument needs a real upper
bound on the provider connection, and step 5 gives one that holds even if the worker dies: the connection is
gone by 17 s. S3b makes the invariant checked: `in_flight_windows()` gains `probe = PROBE_HOLD_SECONDS` (a
function-local import, like its others), so the spacing stays at least twice the probe's hold. At 20 s against
VOD's 40 s it changes nothing today. A probe whose worker dies before `finally` leaks one counted slot, which the
reconciler gives back like any dead holder's, at least two runs (over 80 s) later, long after `timeout` has
killed the connection.

**Credentials.** The URL and user agent never reach a log, an exception message or the database. The task logs
only the stream id, the profile id and an outcome word (`ok`, `refused`, `failed`, `timeout`, `skipped`,
`superseded`). `subprocess` exceptions are caught by type and never logged or re-raised with their text,
because their `str()` carries the argv (§ Verified facts). `ffprobe`'s stderr goes to `DEVNULL`.
**The probe also reaches existing helpers that are not credential-safe today**, and this is a defect on the
tune path as well, not one S3b introduces: `transform_url` (`apps/proxy/next_source.py:271-311`) logs the raw
search pattern at WARNING when it does not match (`:304`), the raw search, replace and safe-replace patterns at
DEBUG (`:286`, `:292-293`), and the regex exception text at ERROR (`:310`). The frontend's XC "simple" mode
builds those patterns from the old and new username and password (`applyXcSimplePatterns`,
`frontend/src/utils/forms/M3uProfileUtils.js:138-149`). `transform_url` is reached from the tune
(`next_source.py:71`), from slot fingerprinting on every pooled M3U reserve
(`apps/m3u/connection_pool.py:83`) and from the profile preview (`dispatcharr/consumers.py:163`).
`scripts/check_credential_logging.py` misses it because the names are `*_pattern` and because it does not model
exception text (`:95-98`). **S3b therefore depends on P1, the transform_url pattern-logging fix (issue to be filed by the owner)**: `transform_url` never logs a
pattern or replacement, says only that the profile's pattern did not match (naming the profile id where the
caller has one), and logs only the exception type; `_fingerprint_from_profile_stream_url`'s DEBUG line
(`connection_pool.py:92-97`) logs only the exception type. P1's tests call the real helpers with
credential-bearing XC-simple patterns under DEBUG logging, for a match, a no-match and a malformed pattern, and
assert no record contains either username or password. S3b's own credentials test then runs the whole probe
path, reservation included, under DEBUG.

**Honest limits.**

- **Proxy and Redirect.** A stream only ever played through Proxy or Redirect has no measurement, so it has
  nothing to expire and is never probed. A mislabelled `4K` name there keeps its name tier forever, as before
  R8. Probing it would be bulk probing of unmeasured streams, which R1 still forbids. The admin's remedy is a pin
  or a `manual` channel.
- **Redirect occupancy is unsupported, not solved.** A stream on a Redirect channel is never probed, so a
  Redirect viewer of *that* stream never shares its provider with a probe of it. What remains: a Redirect
  viewer holds a real provider connection that no counter records, because the relay releases the tune's slot
  before sending the 302 (`relay/httpapi/redirect.go:111-133`). On an account that also serves Redirect
  channels, the counters therefore under-count real connections, and the probe's headroom is only as good as
  those counters, exactly as an ordinary tune's capacity check is today. A provider limit can be exceeded by one
  probe there. This spec does not track Redirect viewers; doing so would be a relay change.
- **Profile changes mid-probe.** A channel switched to Redirect after step 1's re-check is not noticed by a
  probe already running; the probe ends within 17 s.
- **TLS.** `ffprobe` 9.0 verifies the provider's certificate, and the probe ignores Stream Profiles, so a
  provider that plays only through a custom profile with `-tls_verify 0` fails every probe and stops at
  `remeasure_max_failures`. Its last measurement stands.
- **A dead stream** is probed at most `remeasure_max_failures` times, over about 2 days at the defaults, and
  then never again until playback measures it.

## Identity resolution (S4)

**Concurrency: a Postgres session advisory lock**, not the Redis task lock. `acquire_task_lock` stores a shared
literal and releases unconditionally (`core/utils.py:296-315`), and its renewer extends without checking
ownership (`:327-367`). A session advisory lock has no TTL, cannot be released by another session, and is
freed if its session dies. Celery runs plain PostgreSQL (CLAUDE.md § Architecture) and closes connections only
at task boundaries.

**Requesters** are: a classification finishing, a decision changing, a `catalog_settings` save, an EPG refresh
completing, the admin **Re-run**, and a 30-minute beat backstop. Each one:

1. Increments `CatalogResolveState.requested`, in its own committed transaction.
2. Dispatches `resolve_identities.delay()`.

**The task:**

1. Calls `pg_try_advisory_lock(<key>)` outside any atomic block. If it does not get the lock, it returns.
2. Loops, at most three passes per invocation:
   - reads `target = requested`;
   - runs one pass;
   - in the pass's final transaction, confirms it still holds the lock (one `pg_locks` row for its backend),
     then sets `completed = target`;
   - repeats while `requested > completed`.
3. Unlocks in `finally`.
4. **After unlocking, and only if every pass of this invocation succeeded**, if `requested > completed`,
   dispatches itself again with `countdown=30` and a `chain` argument one higher than its own. At `chain = 10`
   it does not re-dispatch, and the next requester or the backstop picks the work up.

**A pass that raises** is logged, the lock is released in `finally`, and the task does **not** re-dispatch
itself: a deterministic failure (a bad row, a `PROTECT` error) would otherwise re-queue at once and repeat a
full pass forever. The work waits for the next requester or the 30-minute backstop, so a persistent failure
costs at most one pass per trigger. A pass that lost its session fails its final transaction, so `completed`
does not advance. Every pass recomputes from current inputs, so a partial pass leaves nothing a later pass
cannot overwrite. A crash leaves `requested > completed`, and the next trigger or the backstop finishes the
work.

**Identity anchors.** Membership is a pure function of the current classifications and decisions **at
quiescence**, meaning once no fuzzy block awaits a re-check (pass 4). A reversed or incremental build then gives
the same result as a clean rebuild. Existing identity rows never influence which streams are eligible; they are
found by their anchor and reused. An identity's natural key is `(anchor, region, variant)`:

- **`tvg:<tvg_id>`**, with the tvg_id case-folded, for streams that have a tvg_id. Streams sharing a tvg_id, a
  known region and a variant are one identity, **whatever their names** (R2: match on tvg_id).
- **`key:<canonical_key>`** for streams without a tvg_id, **unless** exactly one `tvg:` identity with the same
  region and variant has a member with that key. In that case the stream joins the `tvg:` identity.

An anchor changes only when a stream's own tvg_id or key changes. Adding or removing other streams never renames
an identity, so bindings and decisions keep pointing at the same row.

The derived **display fields** are chosen without regard to input order:

- `display_name` is the most common `canonical_name` among the members, with ties going to the lexicographic
  minimum.
- `tvg_id` is the anchor's tvg_id, or null.

**Passes**, in order. From pass 2 on, a stream is skipped if, with its pin applied, its region is unknown or in
conflict, its variant is in conflict, or its key is empty.

1. **Decisions.** Assignments place streams (`decided`) or exclude them. Region pins set the effective region.
2. **tvg anchors.** Every stream with a tvg_id joins `(tvg:<id>, region, variant)` (`auto_tvg`). The same
   tvg_id under a different region or variant is a separate identity (D4).
   - **A different region** is suspicious (the UK/NZ trap), so both sides get an
     `IdentityMatch(source=region_conflict)` against the other identity.
   - **The same region and a different variant raises no match.** Providers routinely copy a base channel's
     tvg_id onto its `+1` or regional `east`/`west` feed, and D4 already keeps those apart by construction, so a
     suggestion there would only be noise.
   - An `IdentityPairRejection` between the two identities suppresses every match between their members in one
     admin act ("these are different feeds"), however many streams either side has or later gains.
3. **Key groups.** Group the remaining streams that have no tvg_id by `(canonical_key, region, variant)`.
   - A group whose key is held by **exactly one** `tvg:` identity of the same region and variant joins it
     (`auto_key`).
   - A group whose key is held by several such identities stays unplaced (`ambiguous_key`), with an
     `IdentityMatch(source=same_key)` against each.
   - Every other group is a **candidate key group**.
4. **Fuzzy eligibility, order-independent and budgeted.** Blocks are `(region, variant, first key token)`. A
   block's **comparison set** is the keys of every candidate key group plus the member keys of every `tvg:`
   identity in that block. It is built from current streams only: undecided ones, and never existing identity
   rows.
   - **Computing a block.** One `rapidfuzz` `process.cdist` with `token_sort_ratio` over the set gives every
     pair of distinct keys scoring at or above `fuzzy_threshold` (default 90). **A pair whose keys' digit tokens
     differ, as multisets, is dropped**: `sky sport 1` / `sky sport 2` scores 90.9 and `bein sports 1` /
     `bein sports 2` scores 92.3, yet numbered siblings are different channels, and without this rule every
     numbered family without a tvg_id would sit in review permanently. `sky sport 1` / `sky sports 1` keeps the
     same digits and stays a pair. The rule is part of `FUZZY_VERSION`. Each remaining pair is stored with its
     score in `FuzzyBlockResult.pairs`. A key is **near** if it appears in any pair.
   - **Re-checking.** A block is recomputed only when its signature changes. The signature includes the
     threshold, the scorer and `FUZZY_VERSION`, so a settings change or a code change re-checks every affected
     block with no stream changing. Changed blocks are taken in
     signature order until the pass's budget (`fuzzy_max_comparisons`, default 5,000,000) is spent. If any
     changed block is left, `requested` is incremented, so the next pass continues.
   - **Oversized blocks.** A block over 2,000 keys is split by the second key token. One still over that has
     every key treated as near (review), with no pairs.
   - **Placing a candidate key group.** It depends on its block's result:
     - **Current result, key not near**: its streams join `(key:<k>, region, variant)` (`auto_key`).
       The row is created if missing, and reused by anchor if present.
     - **Current result, key near**: its streams stay unplaced (`review`), until an admin decides. For **each
       pair** containing its key, each stream gets an `IdentityMatch(source=fuzzy, score=<pair score>)`. The
       match points at the identity holding the pair's other key, or carries that key as `related_key` when no
       identity holds it. Suggestions come only from the stored pairs, so a warm pass rebuilds exactly the rows a
       cold pass would. This applies **both ways**: `sky arts` and `sky art` both go to review, whichever
       arrived first.
     - **No current result** (its block changed and awaits a re-check): its streams stay unplaced
       (`fuzzy_pending`), even if they were placed before.

   **Fuzzy never binds.** Eligibility depends only on the current comparison set, never on arrival order or on
   which identities already exist. A new near-match therefore also moves the earlier group's streams to review.
   Their identity row keeps any binding or decision, and is kept while referenced (§ Deletion). The admin
   resolves the pair by assigning one side's streams (to an existing identity, or to a new one through **New
   identity**) or by excluding them. A pair rejection only hides a suggestion and does not make a group eligible.
   **Decided streams leave the comparison set**, so once one side is decided the other side's group becomes
   eligible again.
5. **Same key across tvg identities.** When two `tvg:` identities in the same region and variant share a member
   key, each of their streams gets an `IdentityMatch(source=same_key)` against the other identity. This is a
   suggestion, never a merge.
6. **Unknown region.** An `IdentityMatch(source=unknown_region)` against the same-key identity in each region.
7. **EPG binding** for every identity.
8. **Proposals** (§ Proposals).

`PairRejection` and `IdentityPairRejection` suppress their matches in every pass.

**Writes.** Every pass computes the wanted `IdentityMember` and `IdentityMatch` sets, then **diffs** them against
the stored rows by natural key (`stream` for a member; `(stream, match_key)` for a match). It inserts the
missing rows, updates a row only when `identity`, `how`, `score` or `suggested_region` changed, and deletes the
rows no longer wanted. `ContentIdentity` display fields are written only when they change. **A pass whose
inputs did not change writes no row** to any of these tables; only `CatalogResolveState` advances. A match row
keeps its id and `created_at` for as long as it is wanted. **Admin actions are keyed on natural keys, never on a
match id**: Assign posts `(stream, identity)` to `assignments/`, Reject posts `(stream, identity)` to
`rejections/`, and "different feeds" posts `(identity, identity)` to `identity-rejections/`. A pass that removed
the suggestion in the meantime therefore cannot make the action fail or land on another row; the decision is
recorded and applies from the next pass.

**Deletion.** An identity left with no members is deleted only if nothing references it: no assignment,
rejection, EPG pin or bound channel. The decision FKs are `PROTECT`, which enforces this. A referenced empty
identity is kept and shown as empty. Its anchor is stable, so when the stream comes back (same stream key, same
tvg_id or key) it rejoins the same row, and the decision still applies. A decision whose key no stream has held
for `decision_prune_days` is pruned (D5), after which its empty identity can go at the next pass.

S4 measures one pass over a synthetic three-account, 300k-stream corpus, both cold (every block computed) and
warm (unchanged signatures), and records both.

## Proposals (S4 computes, S6 accepts)

**Locking** follows D10.

- Admin actions (bind, unbind, dismiss, accept and restore) take every row up front with `NOWAIT`: catalog rows
  first, then non-catalog rows. Bind and unbind take the channel `FOR KEY SHARE`, because they only reference
  it.
- Any action that meets a held lock answers 409 `busy` and writes nothing.
- The resolver's proposal step locks one identity per transaction, waits normally, and holds nothing else.

**Recompute** (resolver step 8, per identity, holding that identity's lock):

1. Work out the wanted proposal.
   - With no bound channel, it is a `new_channel` proposal whose members are every member stream.
   - With a bound channel, it is an `add_streams` proposal whose members are the member streams not already
     on that channel.
   - If the wanted member set is empty, no proposal is wanted.
2. An open proposal of the wrong kind or channel is marked `withdrawn`.
3. An open proposal of the right kind has its members updated in place. Its **`revision` is bumped only when
   `members_hash` or `channel` changes**.
4. A dismissed member set stays dismissed: it is reopened only if a new member appears.

**Bind and unbind** lock the identity row, set or clear `channel`, and run the recompute for that identity in the
same transaction.

**Accept** (`POST proposals/{id}/accept`, S6, body `{revision, options}`) runs as one transaction:

1. Take the locks as above (D10). If the answer is 409 `busy`, nothing has been written.
2. Require `state = open` and a matching `revision`. Otherwise answer 409 with the current revision.
3. Check the binding. For `add_streams`, require that `identity.channel` is still the proposal's channel. For
   `new_channel`, require that the identity is still unbound. Otherwise answer 409.
4. Drop members that were deleted, have gone stale, are already on the target, or are no longer members, and
   return them. If none remain, answer 409.
5. **Adult content.** A new channel is created with `is_adult = any(member.is_adult)`. This is the same rule
   single-stream creation applies (`apps/channels/api_views.py:2023-2030`). For adult members added to an
   existing non-adult channel, `options.adult` must be `mark_channel_adult` or `skip_adult_members`, and the
   request fails with 400 if it is missing. The dialog asks the question.
6. For an existing target, write a `ChannelOrderSnapshot` (`accept_proposal`).
7. Add the members. This is a membership-only edit under D7.
8. **Ranking.** If the channel is new, or the admin ticked "order this channel automatically", set it to `auto`
   and apply `rank_members` (D8) to the whole channel, all before commit. Otherwise the new members are appended
   at the end.
9. For `new_channel`, set `identity.channel` to the new channel.
10. Mark the proposal `accepted`.

The first tune after acceptance therefore already sees the ranked order (`apps/channels/models.py:610`). A
competing accept, bind or unbind waits on the identity lock, then fails at step 2 or step 3.

**EPG on accepted channels.** The catalog writes `epg_data` only on a channel with `auto_created = False`, and
only when the identity's `epg_state` is `bound` or `pinned`. Auto sync rewrites `epg_data` on every channel it
manages (`apps/m3u/tasks.py:2693-2702`), so on an auto-created target the catalog leaves EPG to sync, and the
dialog says so.

**Detach** ("Detach from auto-sync", **ticked by default** under R7, and the admin can untick it). It runs inside
the accept transaction, after the locks, as one atomic step:

1. **Fold the override.** For each field in `OVERRIDABLE_FIELDS` (`apps/channels/managers.py:16-25`) whose
   `ChannelOverride` value is non-null, write that value to the channel's own column. Effective values resolve
   override-first (`with_effective_values`, `:28-55`; `Channel._resolve_effective_fk`,
   `apps/channels/models.py:460-486`). Folding therefore leaves every effective value, and so every output
   (M3U, EPG, XC, HDHR), unchanged.
2. **Retire the override row** (delete it). Nothing customised is lost, because step 1 moved it. The manual-channel
   rule that rejects override edits (`apps/channels/serializers.py:644-659`) and the form that hides override
   controls on manual channels (`frontend/src/components/forms/Channel.jsx:1319-1333`) then describe the channel
   correctly: it has no override, and its own columns hold the values.
3. **Mark it detached**: `auto_created = False`, `sync_detached = True`. This happens under D10's never-wait
   locks on the channel and its override. Orphan cleanup only considers `auto_created = True` channels
   (`apps/m3u/tasks.py:3018-3037`), so the channel survives its origin provider dropping the stream. § Sync
   changes stops a later sync run from overwriting, stopping, deleting or duplicating it. They also cover a run
   already in progress, apart from the windows listed there.
4. **EPG.** If the folded override had set `epg_data`, that is the admin's choice. The channel keeps it, the
   catalog writes no EPG to this channel, and the dialog says the override's EPG was kept. Otherwise the
   catalog writes the identity's EPG when `epg_state` is `bound` or `pinned`.

Unticked, the channel stays auto-created and sync keeps managing it, EPG included.

**Sync changes (S6). These are the only edits to `apps/m3u/tasks.py`.** They revalidate at write time, without
coordinating with the catalog, and keep sync's batching. Each one is a filter, or one batched query, placed
immediately before a write sync already makes. `SYNCED` stands for the filter
`auto_created=True, sync_detached=False`.

| Site at the base | Change |
|---|---|
| `_delete_channels_stopping_streams`, `:57-79`. Used only by sync, from `:2455`, `:2577`, `:2957` and `:3034`. | Re-read `channel_ids` as `Channel.objects.filter(id__in=..., SYNCED).values_list("id")`. Stop only those. Delete with `Channel.objects.filter(id__in=channel_ids, SYNCED).delete()`. Return the number deleted. |
| Renumber, `:2545` | `Channel.objects.bulk_update(` becomes `Channel.objects.filter(SYNCED).bulk_update(`. |
| Existing-channel update, `:2862` | Same change as the renumber. |
| Profile membership reconcile, `:2884-2930` | The flip uses `ChannelProfileMembership.objects.filter(channel__auto_created=True, channel__sync_detached=False).bulk_update(`. **Immediately before** the `bulk_create` at `:2928-2930`, re-read the channel ids through `SYNCED` in one query, and drop the rows for channels that are no longer in it. |
| New-channel branch, `:2651-2655` | Skip a stream that is already on a `sync_detached` channel. |
| Pending-channel creation, **immediately before** the `bulk_create` at `:2809-2812` | One batched query, `ChannelStream.objects.filter(stream_id__in=<pending stream ids>, channel__sync_detached=True).values_list("stream_id")`. Drop every pending pair whose stream it returns, so that a stream detached after the per-stream branch is not given a second channel. |

**What the filters guarantee.** `QuerySet.bulk_update` issues `UPDATE … WHERE pk IN (…)` on the queryset it is
called on, one statement per batch of 500. The `SYNCED` predicate is therefore part of each statement, and under
READ COMMITTED Postgres re-evaluates it on the latest row version. A channel detached before a statement reaches
it is skipped. The plan verifies this predicate behaviour against the installed Django (6.0.8,
`pyproject.toml:9`) with a test, not by reading the source.

**What remains open**, each accepted as a documented risk (ruling of review round 6):

- **Delete collector.** The window runs from the collector's filtered read to its `DELETE`, inside one `.delete()`
  call. A detach that commits there is lost, and the channel is deleted.
- **Stop.** `relay_client.stop_channels` (`apps/proxy/relay_client.py:359`) stops the re-read ids one after
  another, sending one request per channel, each with a `(2, 5)` second timeout (`:78`).
  - **What a detach during the loop does.** It does not take a channel off the list. A channel still ahead of the
    loop **may be stopped**, disconnecting its viewers once. It may not be stopped, because a transport failure,
    or a misconfigured relay address, ends the loop early (`:409-431`). Either way the delete filter then excludes it, so it survives.
  - **How long the window lasts.** As long as the loop runs. That depends on the relay's responses and on how
    many channels are in the list. A transport failure cuts it short, and a slow relay that keeps answering
    stretches it.
- **Pending creation.** The window runs from the batched query to the `bulk_create` batches that follow it
  (batches of 500, each its own statement). A detach that commits there can still give a stream one duplicate
  auto channel. That channel is an ordinary auto channel, and the admin can delete it.
- **Membership flip.** The flip is one filtered `bulk_update` statement per batch. Its window is that statement's
  own execution: a detach committing while the statement runs, after it has passed that row, can have one
  membership flipped to the group's setting.
- **Membership insertion.** The window runs from the re-read of channel ids to the `bulk_create` that follows it.
  A detach committing there can have a membership for the group's profile added to the detached channel. The
  admin can remove it.

Closing these would need sync to lock channel rows before it writes their children. That reverses the order the
deletion collector uses everywhere else, and would create a new deadlock path with admin deletion.

## Reliability (S5)

**Ingest.** The `relay_event_applied` receiver handles the events listed below that carry S1a's `relay_boot` and
`seq`. Events without them come from a relay older than S1a, and are ignored. Each event gets its own
`transaction.atomic()`:

1. In a savepoint, insert `RelayEventReceipt(relay_boot, seq)`. On `IntegrityError` the event is a duplicate, so
   stop. A concurrent duplicate blocks on the unique index until the first commits, then raises.
2. `select_for_update` (or create) the stream's `StreamHealth`. Decay both counters by
   `d = 2 ** (-(now - decayed_at) / half_life)`, set `decayed_at = now`, then add:

   | Event | Stream | exposures | failures |
   |---|---|---|---|
   | `channel_start` | `stream_id` | +1 | |
   | `stream_switch` | `stream_id` (switched in) | +1 | |
   | `stream_switch`, `trigger` ∈ {`health_monitor`, `buffering_timeout`} | `from_stream_id` | | +1 |
   | `channel_error`, `error_type = connection_failed` | `stream_id` | | +1 |
   | `channel_buffering` | `stream_id` | | +0.25 |

`max_retries_exceeded` switches are not counted, because the preceding `connection_failed` already was. Operator
switches count only their exposure. `channel_stop` changes nothing. An event whose stream no longer exists is
skipped, and its receipt is still kept.

**The band** is computed when it is read, after decaying to `now`:

```
if exposures + failures < 0.25:  unknown      # no evidence left
rate = failures / max(exposures, 1.0)
good   if rate < 0.05
fair   if rate < 0.20
poor   otherwise
order: good > fair > unknown > poor           (D8)
```

The evidence threshold is 0.25. With `half_life = health_half_life_days` (default 7), a **single successful
exposure** (1.0, no failures) is `good` from the first second until it decays below 0.25, which is exactly two
half-lives (14 days by default), and is `unknown` after that. A single failure with no exposure is `poor` for the
same period. The formula and constants live in `apps/catalog/health.py`, and the S5 tests pin the formula, not the
numbers. The read surface is the `health` object on `GET /api/catalog/classifications/`.

## When things run

| Task | PR | Trigger | Concurrency |
|---|---|---|---|
| `classify_account_streams(account_id)` | S3 | `.delay()` from the refresh tail after `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:3942`), in its own `try` that only logs and never sets the account status; the D12 backfill; Re-run; a daily backstop over every active account; a convention save (D16). | advisory lock on `(catalog_classify, account_id)` |
| `remeasure_expired()` | S3b | beat, every 10 minutes. Runs only if `remeasure_enabled` and `classify_enabled`. | advisory lock `catalog_remeasure`; probes one at a time |
| `resolve_identities(chain=0)` | S4 | the requesters in § Identity resolution. S4 adds the request at the end of classification and of the EPG refresh. | advisory lock; self-dispatch only after success, `countdown=30`, capped at `chain = 10` |
| `prune_catalog_decisions()` | S4 | daily | none |
| `reorder_channels(channel_ids=None)` | S6 | after each resolve run, and hourly. The hourly run picks up measurement and health changes, which are only computed when read. Runs only if `auto_order_enabled`. | D10 |
| `prune_relay_event_receipts()` | S5 | daily | none |

**Dispatch is wired only in the PR that adds its destination.** A failure is logged and leaves the previous state.
Nothing here runs on the tune path.

**Budget, 100k streams in one account.**

- Parse: about 2 s. Fingerprint: about 0.3 s. Both come from M4 with a 10× allowance.
- Reading the streams: an estimated 5-10 s.
- First-run upsert: an estimated 20-60 s. **S3 measures it.**
- A no-change backstop run reads and compares fingerprints only, with no writes.
- A resolve pass is dictionary work over every account's classification rows: an estimated 10-20 s per 300k
  rows, plus the bounded fuzzy budget. **S4 measures it.**

## LLM assist (deferred)

Ruling R5 defers R2's optional, off-by-default LLM assist to **a separate spec**, with its own design and review,
written after this one lands. This spec adds no setting, environment variable, payload, task or PR for it. The
deferred spec inherits one requirement: **secret safety must hold by construction, not by a sanitiser.** Whatever
leaves the box must come from a source that cannot contain a credential or account identifier, rather than from
provider text filtered after the fact. Rounds 2 and 3 of this spec's review each found a credential path through
a sanitiser.

## Admin UX (S7)

Mantine 8 only. State goes in a new Zustand store, `frontend/src/store/catalog.jsx`. All HTTP goes through new
`API.*` methods in `frontend/src/api.js`. No new UI library, and no direct fetch from components.

- **New page `/catalog`, "Lineup"** (`frontend/src/pages/Catalog.jsx`, route in `frontend/src/App.jsx` next to
  `/channels` at `:152`). It has four tabs:
  - *Proposals*: one row per open proposal. **Accept** opens a dialog with:
    - group, number and Channel Profiles;
    - "order this channel automatically" (D13);
    - the adult-content choice when it applies;
    - for an auto-created target, the detach option (ticked by default, R7). The dialog lists the override values it
      will fold into the channel, and says when an override's EPG will be kept.

    The tab also has **Dismiss** and **bulk accept** (each proposal is accepted on its own).
  - *Review*: `IdentityMatch` rows, grouped by stream, each with a source badge. Actions: Assign, Reject
    pair, Pin region, Exclude, New identity, and on a `region_conflict` group "Different feeds" (an
    `IdentityPairRejection`). Every action posts natural keys (§ Identity resolution, Writes).
  - *Identities*: searchable. Shows the members in D8 order, with tier, tier source, health band and provider,
    the candidate channels with **Bind**, and an EPG chooser that writes an `IdentityEpgPin`.
  - *Status*: run times, counts per state (including `fuzzy_pending`, and `unknown_region` per account, as a
    hint to set that account's `default_region`), the number of due measurements and the last re-measurement
    run's outcomes, **Re-run**, and the enablement switches with D12's preview.
- **Channel streams table** (`frontend/src/components/tables/ChannelTableStreams.jsx`):
  - a tier badge, marked "measured", "measured, due" or "from name";
  - a health-band dot;
  - a pin toggle;
  - "Order: Auto / Manual";
  - "Restore previous order", which sets Manual.

  After a drag on an `auto` channel, a toast says the channel is now Manual. Any catalog action answered 409
  `busy` shows "This channel is busy; try again", and changes nothing.
- **EPG source form** (`frontend/src/components/forms/EPG.jsx`): an optional Region select.
- **Settings** (`frontend/src/pages/Settings.jsx`): "Stream classification", for `catalog_settings`.
- S8 adds the M3U account form's "Naming convention" section.

**Access warning in the accept dialog.** When no Channel Profile is picked, the dialog says: *"With no Channel
Profiles, this channel is visible only to admins and to users who have no Channel Profiles. Users assigned to
profiles will not see it until you add it to one of theirs."* This matches `user_can_access_channel`
(`apps/proxy/authorize.py:202-223`). No authorization filter changes.

**API** (`apps/catalog/api_urls.py`, at `/api/catalog/`). Every endpoint has a DRF serializer, appears in the
drf-spectacular schema, and is `IsAdmin` with no opt-down.

- **S3**: `classifications/` (with the effective tier, its source, and the measurement's age and `due` flag),
  `parse-preview/`, and `run/` (classify every account, then resolve once S4 exists). The M3U account
  serializer accepts and validates `custom_properties["catalog"]` (D16).
- **S4**:
  - `identities/`, with the `bind`, `unbind` and `epg-pin` actions;
  - `matches/`, read-only;
  - `assignments/`, `region-pins/`, `rejections/` and `identity-rejections/`, each written by natural key;
  - `proposals/`, read-only.
- **S5**: `health` on `classifications/`.
- **S6**: `proposals/{id}/accept|dismiss`, `auto-order/preview|enable`, and `channels/{id}/order-snapshots/`
  with `restore`. The channel serializer gains `stream_order_mode` and `pinned`.

## Coexistence

- **Manual assignment.** It is untouched on `manual` channels (D7). On `auto` channels, a reorder flips the
  channel to `manual`, and a membership-only edit keeps the mode.
- **Auto channel sync.**
  - Sync's channels appear as candidates, and the admin binds one or none.
  - Sync never sees `stream_order_mode` or `pinned`. Its only changes are the write-time filters in § Sync
    changes.
  - The catalog never writes `epg_data` on an auto-created channel.
- **Stream rehash and merge.** No new lock (D10). The merge carries pins on the rows it already writes. A
  catalog transaction that meets a rehash lock rolls back and retries. Decisions survive because they are keyed per D5.
- **Stale and deleted streams.** Stale streams sort last (D8). Deleted streams cascade out of every
  stream-keyed catalog table. Identities follow the deletion rule.

## Known-defect interactions

- **Provider-slot counters (#513).** No `INCR`, `DECR` or `SET` is added, and the Lua script is unchanged. S3b's
  probe reserves and releases only through `reserve_profile_slot` (with its new `headroom` argument, default 0)
  and `release_profile_slot`, and is covered by the reconciler as an in-flight reservation (§ Re-measurement at
  expiry).
- **Catalog channel writes and signals.** Every receiver in § Model signals is accounted for explicitly (D10
  step 3): database effects inside the transaction, the EPG cache invalidation and programme-refresh dispatch
  only from `on_commit`.
- **The copied channel-authorization filter.** Untouched. No client-facing surface is added. Adult status is
  propagated (§ Proposals), so `authorize_stream`'s `hide_adult_content` check
  (`apps/proxy/authorize.py:471-474`) sees the right flag on catalog-created channels.
- **Unfenced leases** (CLAUDE.md § Known defects). Catalog work uses Postgres advisory locks, not the Redis task
  lock.
- **The boot trap.** No module that `apps/channels/models.py` imports gains an import (D1).
- **CoreSettings blast radius.** `catalog_settings` is a ninth instance-wide group. S3 ships a data migration
  seeding its row. Any E2E test that writes it joins the allowlist (`docs/adr/0003`).
- **Credential logging.** The parse-preview endpoint logs no URL and no payload. S3b's probe builds a provider URL
  and handles it as § Re-measurement at expiry's Credentials paragraph says. The helpers it shares with the tune
  path log credential-bearing profile patterns today; prerequisite P1 fixes that for both.
- **Rename ratchet (Mino spec PR R1).** If R1 has landed, a new file containing `dispatcharr` (the package
  import, the `dispatcharr-ci` profile, the `dispatcharr_channels` label) raises
  `scripts/product_name_allowlist.txt`. Each plan lists such lines, and each must be a name the rename spec
  keeps (C-9, C-10, C-13).

## Test strategy

**Celery in tests.** `CELERY_TASK_ALWAYS_EAGER` stays globally off (`dispatcharr/settings_test.py:29-33`). Tests
call task bodies directly, and patch `.delay` to assert dispatches.

**Stopping-point smoke check, in every PR from S3 on.** A backend test in the PR's own label checks that its
migrations apply on top of the previous stopping point's schema with no pending migration, and makes one request
against each endpoint it adds.

**Corpus** (`apps/catalog/tests/fixtures/stream_names.jsonl`): at least 400 lines with expected parses. It
covers:

- every golden case above;
- region prefixes, suffixes and brackets;
- protected phrases;
- ALL CAPS;
- decorations after a suffix region;
- group-only tiers and regions;
- tvg_id-only regions;
- the ambiguous tokens;
- an overflow;
- an empty key;
- a variant conflict;
- **the trap set**: at least 20 brands present in two regions, five decorations each;
- **the word-trap set** (2026-11-11 findings 1 and 3): every `WORD_CODES` entry as an undelimited first and last
  token of a plausible channel name (`Apple TV`, `Sky TV`, `At The Races`, `Me TV`, `Capital FM`, `Smooth FM`,
  `Box Hits It`, …) parsing with no region, the same entries delimited (`[IT] Rai 1`) parsing with their
  region, tvg_ids ending in each entry giving no region, and every word-shaped marker or variant as a leading
  or middle word (`Test Match Special`, `Alt Rock TV`, `East Enders Classics`, `West Ham TV`, `Raw Travel`)
  staying in the key, plus every protected phrase with a tier, codec or fps token inserted between its words
  (`WWE HD Raw`, `UK FHD Gold`) parsing exactly as the bare phrase does;
- **the numbered-family set** (finding 2): `Sky Sport 1` … `Sky Sport 9`, `beIN Sports 1` … `beIN Sports 15`,
  `Sky Sports Main Event` / `Sky Sports Premier League`, for S4's fuzzy tests.

Nothing in the corpus is a real URL or credential, and a test asserts no line contains `://`.

**Property tests** (S2, using the shared `dispatcharr-ci` profile, registered byte-identically):

- the three stability properties;
- a delimited region token, or an undelimited edge token that is not in `WORD_CODES`, yields its region code and
  is absent from the key;
- a `WORD_CODES` token as an undelimited edge token, or as a tvg_id suffix, never yields a region and never
  raises `region_conflict`;
- for every trap brand, under any decorations, the GB name yields GB and the NZ name yields NZ.

**Convention golden** (S2): `AR: MBC 1` with and without `region_tokens: {"AR": null}`; a prefix-less name with
`default_region: "GB"` yields GB from source 4.

**Resolution tests** (S4):

- **Determinism.** Each of these produces the same identities, members and display fields as a clean rebuild:
  - a reversed input order;
  - an incremental build (accounts classified and resolved one at a time);
  - a build where the streams arrive in a random order over three runs.

  Bindings and decisions made between runs survive.
- **The UK/NZ trap.** A UK and an NZ stream with an equal key and an equal tvg_id produce two identities and
  conflict rows.
- **Variants.** A tvg_id shared by a feed and its `+1` produces two identities and **no** `IdentityMatch` row
  for either (finding 4). The same tvg_id under GB and NZ still produces `region_conflict` rows, and one
  `IdentityPairRejection` clears every one of them, including for a stream added to either side afterwards.
- **Writes** (finding 10). A second pass with no input change performs no `INSERT`, `UPDATE` or `DELETE` on
  `IdentityMember`, `IdentityMatch` or `ContentIdentity` (asserted with `CaptureQueriesContext`). A match that is
  still wanted keeps its id and `created_at` across passes. An Assign posted by natural key after a pass deleted
  the suggestion succeeds and applies at the next pass.
- **Self-dispatch** (finding 7). A pass that raises does not re-dispatch (`.delay` and `.apply_async` patched,
  asserting no call). A successful invocation with `requested > completed` re-dispatches once with
  `countdown=30` and `chain + 1`, and at `chain = 10` does not.
- **M3U stream keys** (finding 8). A plain M3U stream renamed from `UK: Sky Arts HD` to `UK: Sky Arts FHD` and
  moved to another group keeps its key, so its exclusion and region pin still apply. So do `WWE Raw HD` renamed
  to `WWE HD Raw`, and `UK Gold` renamed to `UK FHD Gold` in the same group (round 8 finding 7). A parser-version change
  that alters a key moves the decision to the new key. A decision unseen for `decision_prune_days` is pruned,
  and its empty identity is deleted at the next pass. Two empty-key streams in one account have different keys.
- **Unplaceable streams.** Conflicted, unknown-region, variant-conflict and empty-key streams are never placed or
  proposed.
- **Decisions.**
  - A pin ends a conflict.
  - At most one assignment exists per key.
  - A rejection survives a re-run and a rehash.
  - A **decided stream that disappears and returns** (same stream key) rejoins the same identity before any
    channel exists.
  - A referenced empty identity is not deleted.
- **Fuzzy.**
  - Fuzzy never binds.
  - **Arrival order.** Use two GB no-tvg streams, `UK: Sky Arts HD` and `UK: Sky Art HD`. Arts then Art, Art then
    Arts, and both together each end with both groups in `review` and identical `IdentityMatch` rows.
  - **Intervening binding.** Arts arrives alone, gets `key:sky arts`, and an admin binds it to a channel. Art then
    arrives. Both groups go to review, and the identity is kept, empty and still bound. The admin assigns the Art
    stream to `key:sky arts`, and the Arts group rejoins it. The final state equals a clean rebuild with the same
    decision.
  - **Deferred check.** A near-match in a block left unchecked by the budget stays `fuzzy_pending` and creates no
    identity until its block is re-checked.
  - **Signatures.** A block whose signature is unchanged is not recomputed.
  - **Threshold change, no stream change.** The `sky arts` / `sky art` block is checked at 90, and both groups go
    to review. Setting `fuzzy_threshold` to 100 changes the signature, and the next pass re-checks the block.
    Both groups get their own identities, which equals a clean rebuild at 100.
  - **Two disjoint pairs in one block.** `sky arts` / `sky art` and `sky atlantic` / `sky atlantik` produce exactly
    two pairs of suggestions, with no cross suggestions. A cold pass and a warm pass (with an unchanged
    signature) produce identical `IdentityMatch` rows, scores included.
  - **Numbered siblings** (finding 2). GB no-tvg `Sky Sport 1` … `Sky Sport 9` and `beIN Sports 1` …
    `beIN Sports 15` each get their own `key:` identity with no `IdentityMatch` row, while `Sky Sport 1` /
    `Sky Sports 1` still goes to review.
- **Locks** (Postgres-only, two connections):
  - a second resolver returns;
  - terminating the holder's connection mid-pass leaves `completed` unchanged;
  - a request made during the final pass, or after unlock but before the post-unlock check, produces exactly one
    further pass;
  - an exhausted budget is resumed by the next pass.
- **EPG.**
  - GB- and NZ-region sources with the same tvg_id bind each identity to its own row.
  - Unknown-region rows from several sources give `ambiguous`.
  - A pin survives re-runs.
  - A deleted pinned row resumes derivation.
  - A GB/NZ collision on an auto-created channel survives a following `sync_auto_channels` run, with the catalog
    writing no EPG there.
- **Proposals.**
  - An unchanged rescan keeps the revision.
  - Binding withdraws `new_channel`.
  - With a concurrent bind and accept, exactly one succeeds.
  - Dismissal persists until a new member appears.

**Ordering and acceptance tests** (S6):

- **Ties.** A tie whose current order is not id order survives two passes, and the second pass writes nothing.
- **Modes.**
  - A `manual` channel is never written.
  - A reorder flips the channel to `manual`; a membership-only edit does not.
  - A restore sets `manual`, and the next pass leaves the channel alone.
  - A concurrent reorder and `PATCH`: the `PATCH` wins.
- **Contention semantics** (Postgres-only, two connections, real signals). In every case the losing side writes
  nothing, the other side completes, and the data is consistent afterwards: no duplicate `(channel, stream)`, the
  order and pins are either all from before or all from after, and the catch-up rollup is correct.
  - **The catalog backs off.** An admin channel delete is paused by a hook while it holds C's rows. A reorder of C
    returns "skipped" **before the hook releases the delete**, and an accept on C answers 409 `busy`. After the
    delete commits, the next pass has nothing to do.
  - **Either side may lose.** An admin `PATCH` inserts `(C, S)`, and is held in the catch-up signal waiting for C,
    which an accept holds, paused by a hook. The test then lets the accept insert the same `(C, S)`, so a real
    cycle forms. It runs twice: once with the `PATCH` session's `deadlock_timeout` set low, so the `PATCH` is the
    victim, and once with it set high, so the accept's backstop gives up first.
    - When the accept loses: it answers 409 and wrote nothing.
    - When the `PATCH` loses: it fails with 40P01, as it can today against another admin edit.
    - Either way, `(C, S)` exists exactly once after the winner commits, and a retry of the loser succeeds.
  - **Reorder against rehash with an out-of-batch partner.** The catalog side skips C and retries successfully.
  - **Channel delete against a catalog-held identity.** The delete's `SET_NULL` onto `ContentIdentity.channel`
    waits briefly. The catalog action fails `NOWAIT` on C, or finishes first. Afterwards `identity.channel` is
    null, and the next resolve pass recomputes the proposal.
  - **Bind against a channel being deleted.** The bind answers 409 `busy`.
  - **Quiet period, a recent-`Channel.save()` heuristic.** A channel saved 10 s ago is skipped by the reorder pass,
    and reordered once `reorder_quiet_seconds` has passed. A **streams-only `PATCH`**, which skips
    `Channel.save()`, does not move `updated_at`. The test pins that the reorder is **not** skipped after one, so
    the heuristic's limit stays visible.
  - **Fixture ageing (plan obligation).** Every contention-test fixture sets `Channel.updated_at` older than
    `reorder_quiet_seconds` before the test runs. That way the quiet-period skip cannot be the reason a reorder
    returns "skipped", and it cannot mask the locking break-check.
  - **Performance target only, not a correctness claim.** Reorder and accept on a 500-member channel complete
    within 250 ms on the test container.
- **Rehash pins.** A pin only on the source row, or only on the target row, survives.
- **Detach** (on an auto-created target that has a `ChannelOverride` setting the name, number, logo and
  `epg_data`).
  - The effective values (`with_effective_values`) and the channel's generated M3U and XMLTV entries are
    identical before and after acceptance.
  - The override row is gone, and the override's EPG is kept: the catalog writes none of the identity's.
  - An ordinary `PATCH` of the name then succeeds, and a non-empty `override` `PATCH` is refused, as on any
    manual channel.
  - A following `sync_auto_channels` run creates no new channel for the origin stream and deletes nothing.
  - **Sync already running, paused after mapping** (`:2293-2306`, with C in its map). Detach commits, then sync
    resumes. C's name, number, EPG and logo are not overwritten, and its profile memberships are not flipped.
  - **Sync already running, paused after orphan collection** (`:3033`, with C in `orphan_list`). Detach commits,
    then sync resumes. C is neither stopped nor deleted.
  - **Sync already running, paused after pending construction and before the `bulk_create`** (at `:2809`, with
    stream S pending). An accept adds S to a detached channel and commits, then sync resumes. No second channel
    is created for S.
  - A detached channel in a sync `bulk_update` batch is not updated, which confirms that the installed Django keeps
    the queryset predicate.
  - Unticked, the channel stays auto-created and the catalog writes no EPG.
- **First tune after acceptance.** Members are presented worst tier first. `get_stream()` immediately after the
  accept commits returns the best-tier stream.
- **Adult content.** A new channel with one adult member is adult. Through `authorize_stream`
  (`apps/proxy/authorize.py:479`), a user with `hide_adult_content` is refused it and a user without that
  setting is allowed. Adding an adult member to a non-adult channel without `options.adult` returns 400. With
  `skip_adult_members`, the channel stays non-adult and the adult member is not added.
- **Failover order.** `get_stream()` and the failover branch choose the tier-sorted first stream.
- **Signals** (finding 6; Postgres-only, `TransactionTestCase`, so commits are real). The cache invalidation and
  the refresh dispatch are wrapped to record, at the moment each runs, three facts: whether the connection is
  in an atomic block, whether a second connection's `is_epg_mapped_to_channel(epg)` is true, and the call
  itself.
  - **Commit visibility.** Accepting onto a manual target with a `bound` identity, and accepting a new channel
    with EPG, each run both effects exactly once, outside any atomic block, with the mapping already visible
    to the second connection.
  - **Rollback suppression.** An accept forced to fail after its `epg_data` write (a hook raising
    `LockNotAvailable` before commit) runs neither effect.
  - **No external work under locks.** Neither effect runs while the accept's transaction is open: a hook
    paused just before commit observes zero calls.
  - A reorder and an accept leave `Channel.updated_at` unchanged, and neither compact-number receiver writes.

**Tune-path ledger:** `apps/proxy/tests/test_tune_path_query_ledger.py` passes unchanged in every PR.

**Quality tests** (S3):

- A REST write of `stream_stats` after a valid Go measurement leaves `MeasuredResolution` and the effective tier
  unchanged.
- A measurement older than the TTL still yields the measured tier, reported `due` (R8). Before: it yielded the
  name tier. A newer measurement replaces it at the next read.
- A `stream_stats` event without `relay: "go"` writes nothing.
- A daily backstop on an unchanged account writes nothing.
- **Conventions in S3** (finding 9). Saving `default_region: "GB"` on an account through the account API
  dispatches classification for that account, and its prefix-less streams then classify as GB. An invalid
  sub-dict answers 400.

**Re-measurement tests** (S3b). Redis is the test container's real one (the slot script must run as Lua). The
module invokes `ffprobe` and `timeout` by absolute paths held in two module constants, never by `PATH` lookup,
so a test that points the `ffprobe` constant at a fake script cannot fall through to the real tool; the suite
first asserts the constant is the fake. The smoke test asserts that the real `timeout` and `ffprobe` resolve in
the CI base image.

- **Selection.** Only a due, channel-member, measured stream is probed. An unmeasured stream on the same channel
  is never probed, nor a stale one, nor one on an inactive account, nor one the relay lists as playing, nor one
  on any channel whose effective stream profile is Redirect. With the relay unreachable, no probe starts. With
  `remeasure_enabled` off, nothing runs.
- **Bounds.** With twelve due streams on three accounts and `remeasure_max_per_run = 10`, one run probes three
  (one per account). A second concurrent run returns at once on the advisory lock.
- **Fair progress** (round 8 finding 6). `remeasure_max_per_run = 1`; account A's candidate is older and its
  only profile is full; account B's is younger and has room. One run is refused on A, defers A's candidate by
  1 h with `remeasure_failures` unchanged, and probes B. The next run within the hour does not try A.
- **Fencing** (round 8 finding 3). (a) Playback measures the selected stream after selection and before
  launch: the re-check skips it, no slot is reserved and no subprocess runs. (b) Playback measures it while the
  fake probe is blocked: the probe's success write updates zero rows, the playback measurement and its
  `source = playback` survive, and the outcome is `superseded`. (c) As (b) with a failing fake: no failure is
  counted and no backoff is set.
- **Parent death** (round 8 finding 2). In a child Python process, run one probe against a fake `ffprobe`
  that records its pid and sleeps 300 s, with the bounds shortened through the module constants
  (`timeout -k 1 2`). `SIGKILL` the child process once the fake's pid file appears. The fake's pid is gone
  within 3 s plus a 2 s margin, with no Python parent left to enforce anything.
- **Headroom.** On a profile with `max_streams = 3` and two slots held, the probe is refused and writes nothing,
  counter and version unchanged. With one slot held it reserves, and both counters are back to one afterwards.
  A `max_streams = 1` profile is never reserved. `reserve_profile_slot` with the default `headroom=0` behaves
  exactly as before (the existing pool tests pass unchanged).
- **Outcomes.** A success at 576 lines on a stream measured at 1080 moves it to SD and resets the failure count.
  A non-zero exit, a timeout and a no-video answer each keep the old measurement and tier, increment
  `remeasure_failures` and set the backoff. After `remeasure_max_failures` the stream is no longer a candidate,
  and a playback measurement makes it one again later.
- **Release.** The slot is released when the fake hangs past the timeout and when it exits non-zero.
- **Credentials.** Under DEBUG logging, with an M3U profile whose XC-simple patterns carry a username and
  password, and a provider URL carrying them too, no log record from the whole path (URL resolution through
  the real `_resolve_live_stream_url` and `transform_url`, the reservation with its fingerprint derivation, a
  refusal, a success, a failure, a timeout, and a malformed pattern) contains `://`, the username or the
  password. This test passes only on top of P1.
- **Reconciler.** `run_spacing_seconds()` is at least `2 × PROBE_HOLD_SECONDS`, and `in_flight_windows()` has
  a `probe` entry.

**Health tests** (S5):

- The decay formula, with an injected clock.
- The contributions table.
- A duplicate batch applies once.
- **A batch whose HTTP attempts timed out, applied after a later batch from the same boot,** applies all of its
  events once (simulated by calling the ingest out of order).
- Two concurrent deliveries of one event apply once.
- **A single exposure** is `good` at 1 s, still `good` just before two half-lives, and `unknown` just after.
- A failure with no exposure is `poor`.
- An untouched stream ages at read time with no write.
- Events without S1a fields change nothing.
- The prune task deletes only receipts older than 30 days.

**Frontend:** vitest for each new component and the store, with `api.js` mocked.

## The PRs

Branches are `feature/catalog-*`, except S1a and S1b, which touch the live path and are named
`migration/catalog-s1a-…` / `-s1b-…` so that the full E2E matrix runs. No PR description below carries a
closing keyword.

| PR | Needs | Stopping point |
|---|---|---|
| P1 (the transform_url pattern-logging fix; issue to be filed by the owner) | none | `transform_url` and slot fingerprinting log no pattern, replacement or exception text (a pre-existing tune-path defect; § Re-measurement at expiry, Credentials) |
| S1a | none | events carry identity and attribution |
| S1b | S1a | `stream_stats` posted again |
| S2 | none | parser, inert |
| S3 | S2 | tiers visible, read-only (name-only until S1b's data arrives); conventions settable by API; a measurement never reverts |
| S3b | S3, S1b, P1 | due measurements re-measured by probe, off by default |
| S4 | S3 | identities, review queue, decisions, binding, read-only proposals; **writes no channel** |
| S5 | S3 (settings, signal), S1a (data) | health visible on `classifications/` |
| S6 | S4, S5 | ordering and acceptance, the headline behaviour (API-driven) |
| S7 | S6 | the full UI |
| S8 | S7 | the naming-convention form section |

Each stopping point passes its smoke check (§ Test strategy). S3b is independent of S4-S8: it can land any time
after S3, S1b and P1, and a stopping point without it simply keeps every measurement. P1 is a small fix PR on
its own branch; its issue is to be filed by the owner, and this spec cites it only with `Refs`. It is worth landing whether or not S3b follows.

### S0 — this spec

Docs only. It cites a tracking issue with `Refs`, if one is filed.

### P1 — `transform_url` logs no credential (prerequisite fix)

A fix for a pre-existing defect on the tune path, found while reviewing S3b (§ Re-measurement at expiry,
Credentials). The issue is to be filed by the owner; P1 runs on its own branch, and any closing keyword for that
issue belongs only in P1's own PR description, never in this spec.

**Changes.** In `apps/proxy/next_source.py`'s `transform_url`: delete the three DEBUG lines that print the
search, replace and safe-replace patterns; make the no-match WARNING say only that the pattern did not match
(the caller may pass a profile id to name); make the ERROR log only `type(e).__name__`. In
`apps/m3u/connection_pool.py`'s `_fingerprint_from_profile_stream_url`, log only the exception type.

**Tests.** The real helpers, under `assertLogs` at DEBUG, with XC-simple patterns built as the frontend builds
them (`olduser/oldpass` → `newuser/newpass`): a matching URL, a non-matching URL, and a malformed pattern. No
record contains `olduser`, `oldpass`, `newuser` or `newpass`. The transformed URL is unchanged from today in the
matching case.

**Break-checks.** Restore the no-match WARNING's pattern. The no-match test reddens naming `oldpass`. For the
ERROR line, the plan first pins a malformed pattern whose `regex` exception text quotes a credential fragment (a
replacement naming a missing group, `$<oldpass>`, is the first candidate to try); restoring `{e}` then reddens
the malformed-pattern test naming `oldpass`.

### S1a — attribution and event identity (Go, reporting only)

**Changes.**

- **The run loop keeps a local `sourceStream`** beside its local `source`. It is set wherever the loop already
  sets `source`:
  - `first` at start;
  - `resolved.Source` / `resolved.Info.StreamID` at each existing adoption point (`relay/channel/channel.go:559-566`
    and the failover branches at `:611-640`).

  No adoption point moves, and **when a parked `Advance` is consumed is unchanged**: still after the running
  attempt returns.
- **`runAttempt(ctx, source, sourceStream)`** (`:668`) builds an immutable
  `report{streamID int; stats *attemptStats}` at the start of each attempt, and hands it to the source through
  `attach` (the interface at `:482` gains the parameter). `TranscodeSource`'s stderr reader copies it once at
  creation (`source_transcode.go:192`). Everything that reader emits is attributed by its copy:
  `channel_buffering` now, and stats in S1b.
- **Events.**
  - `stream_switch` gains `from_stream_id` (the `sourceStream` being left) and `trigger`. The trigger is
    `health_monitor`, `max_retries_exceeded` or `buffering_timeout`, passed in from `failover(ctx, why)`, or
    `operator` from `Advance`.
  - `channel_error` `connection_failed` (`:604`) gains `sourceStream`.
  - `channel_stop` (`:759`) gains the last `sourceStream`. It sets both `details["stream_id"]` and the top-level
    field, because it builds its `Event` directly.
- **Event identity.** `Emitter` (`relay/control/events.go`) draws `relay_boot` (16 random hex characters) once,
  and assigns `seq` from an atomic counter at enqueue. Both go into `details`.
- `docs/relay-parity-matrix.md` gains two rows, each naming its Go test.

**Tests.**

- Each trigger's `stream_switch` carries the right `from_stream_id` and `trigger`.
- **Advance during backoff:** `Advance(B)` while A is in retry backoff. The next attempt still runs A and reports
  A. B is adopted after that attempt returns, and its first attempt reports B. This pins the existing adoption
  timing.
- **Advance mid-attempt:** after `applySwitch(B)` but before A's attempt returns, a speed line on A's reader
  emits `channel_buffering` with `stream_id` A. That is correct, because A is still the source being run.
- **Same-source retry:** two attempts on A both report A.
- `seq` strictly increases, and `relay_boot` stays constant within one process.

Coverage follows the Phase 4 floor rule (D20).

**Break-checks.**

- Read the stream from `c.currentStreamID` in the stderr reader. The mid-attempt test reddens, naming B.
- Adopt a parked `Advance` before the next attempt. The backoff test reddens.

**PR description draft:**

> Adds the attribution the reliability work needs, without changing any relay decision or when a pending
> switch is adopted: every event carries a per-process `relay_boot` and an increasing `seq`, and
> `stream_switch` gains `from_stream_id` and `trigger`, while `channel_error` `connection_failed`,
> `channel_buffering` and `channel_stop` gain the stream they are about. Attribution is to the source an
> attempt actually runs, captured when the attempt starts. Two parity-matrix rows. Spec PR S1a.

### S1b — `stream_stats` posted again (Go, reporting only)

**Changes.**

- **Per-attempt storage.** Each attempt owns an `attemptStats`, created by `runAttempt` and reached through the
  report context. `reportInfo` and `reportProgress` take the reader's context, and merge into the channel's
  `stats` exactly as today, so the status view is unchanged. They also merge into **their own attempt's**
  `attemptStats`. No other attempt's storage is reachable from a reader, so no comparison or reset is needed.
- **Cadence.**
  - An **input-metadata change** posts at once: `reportInfo` adding or changing a codec, resolution,
    dimensions, fps, pixel format, sample rate, channels or stream type.
  - **Progress-only values** (`ffmpeg_output_bitrate`, speed-derived fps) are never posted on their own. They
    ride the 30-second ticker.
  - The ticker is a goroutine started by `runAttempt`. When the attempt's source returns, `runAttempt` stops the
    ticker **and waits for it to exit**, then posts one final flush from the same `attemptStats`. The next
    attempt creates fresh storage.
  - Steady state is therefore one post per 30 s per running subprocess channel, plus one at each input-metadata
    change and one at each attempt end.
- **Payload.** Each post carries `relay: "go"`, the context's `stream_id`, and only the keys present, under the
  Python names: `video_codec`, `resolution`, `width`, `height`, `source_fps`, `pixel_format`, `video_bitrate`,
  `audio_codec`, `sample_rate`, `audio_channels`, `audio_bitrate`, `stream_type`, `ffmpeg_output_bitrate`.
  Empty storage is never posted. Subprocess architecture only (row 29 unchanged).
- One parity-matrix row.

**Tests.**

- With the stderr corpus and an injected clock:
  - an input-metadata change posts once;
  - a run of progress lines alone posts nothing until the 30 s tick;
  - the attempt-end flush.
- **A then B, with B silent:** no post names B with a resolution. Variants: a buffering switch, an operator
  switch, and a stop straight after the switch.
- **A same-source silent retry** posts nothing the first attempt measured.
- **Ticker join:** under `-race`, the final flush never runs concurrently with a tick.
- **Proxy** posts nothing.

**Break-checks.**

- Make storage channel-wide instead of per-attempt. The silent-B test reddens, naming B.
- Post on every progress line. The cadence test reddens on the post count.

**PR description draft:**

> Restores posting `stream_stats`, which the Go relay parsed and served on `GET /proxy/relay/channels` but
> never sent after the cutover. Each post carries only what the attempt that produced it measured, attributed
> through S1a's context; input-metadata changes post at once and progress values ride a 30-second flush, so
> steady-state traffic is one post per running channel per 30 s. The status view is unchanged. One
> parity-matrix row. #619 (planned in PR S1b). Spec PR S1b.

### S2 — the parser (pure, inert)

**Changes.**

- The `apps/catalog/` skeleton.
- `parse.py`, `regions.py` and `conventions.py`.
- The corpus, golden tests and property tests.
- `CONTEXT.md` gains **Content identity** and **Quality tier**.

The plan confirms that the new test label is picked up by `dispatcharr/test_discovery.py` and by
`FULL_SUITE=1 python3 scripts/ci_backend_test_labels.py`.

**Break-checks.**

- Remove `nz` from the table. The trap property reddens, reporting region `""` where NZ was expected.
- Extract the region before removing decorations. The `Sky Arts UK FHD HEVC 50FPS` golden case reddens.
- Truncate before normalising. The overflow golden case reddens.
- Match protected phrases on the raw token sequence instead of the projection. The `WWE HD Raw` golden case
  reddens with key `wwe` and marker `raw`.

**PR description draft:**

> Adds `apps/catalog` with a pure, versioned stream-name parser: canonical key, region and its evidence,
> tier/codec/fps hints, markers and feed variant, in fixed phases, with bounded output. Nothing runs yet. A
> 400-line real-shaped corpus with a two-region brand trap set is golden-tested; Hypothesis pins key
> stability, decoration independence and region extraction. Spec PR S2.

### S3 — classification, measured resolution and tiers

**Changes.**

- `StreamClassification` (with D5's parse-tuple `stream_key`) and `MeasuredResolution`.
- The `relay_event_applied` signal and the `stream_stats` receiver.
- `classify_account_streams`, with its triggers: the refresh tail, the backfill, Re-run, the daily backstop and
  a convention save.
- The D16 backend: the account serializer's validation of `custom_properties["catalog"]`, `convention_version`,
  and the save dispatch (moved here from S8, finding 9).
- The `catalog_settings` getter, and a seeding migration.
- `classifications/`, `parse-preview/` and `run/`.
- The smoke check.
- A measurement of the 100k first run.

**Break-checks.**

- Read the measured tier from `Stream.stream_stats`. The REST-write test reddens.
- Revert to the name tier once `observed_at` is older than the TTL. The expired-measurement test reddens,
  reporting the name tier.
- Make the backstop write every row. The unchanged-account test reddens.
- Leave the convention out of `convention_version`. The `default_region` save test reddens: the streams stay
  unknown-region.
- Drop the save dispatch. The same test reddens with no classification dispatched.

**PR description draft:**

> Classifies every live stream behind the off-by-default `classify_enabled` setting: a parse row per
> stream, rebuilt only when its text changes, run after each provider refresh, on enablement, on demand, on
> a naming-convention save and by a daily backstop that needs no provider download; plus a catalog-owned
> measured resolution written only from the relay's stats events, which never reverts to the name tier on
> age. Per-account naming conventions (default region, region-token overrides) are settable through the
> account API. The effective tier is computed when read. Writes no channel. Spec PR S3.

### S3b — re-measurement at expiry (R8)

**Changes.**

- The two `MeasuredResolution` columns.
- `reserve_profile_slot`'s optional `headroom` argument (default 0; the Lua script is unchanged).
- `apps/catalog/remeasure.py` and the `remeasure_expired` task with its beat entry, per § Re-measurement at
  expiry.
- `catalog_settings` keys `remeasure_enabled` (default `false`), `remeasure_max_per_run` (10) and
  `remeasure_max_failures` (4).
- The `probe` entry in `apps/proxy/slot_reconciler.py`'s `in_flight_windows()`.
- The due count and last-run outcomes on `classifications/` and the Status payload.
- The smoke check.

**Break-checks.**

- Pass the profile's own max to the reserve (no headroom). The headroom test reddens: the probe reserves the
  second-to-last slot.
- Drop the "has a measurement" filter. The selection test reddens, probing the unmeasured stream.
- Move the release out of `finally`. The release test reddens on the timeout case, with the counter left at two.
- Log the caught `TimeoutExpired`. The credentials test reddens, finding `://` in the record.
- Clear the measurement on failure. The outcomes test reddens, reporting the name tier.
- Run `ffprobe` without the `timeout` wrapper. The parent-death test reddens: the fake's pid is still alive
  after the bound.
- Write the result without the `observed_at` condition. The fencing test (b) reddens: the playback measurement
  is overwritten with `source = probe`.
- Skip the deferral on refusal. The fair-progress test reddens: B is never probed.
- Drop the Redirect-channel condition. The selection test reddens, probing the stream on the Redirect channel.

**PR description draft:**

> Owner ruling R8: when a stream's quality measurement reaches its TTL, re-measure that one stream rather than
> let it fall back to its name. Behind an off-by-default switch, a throttled task probes only streams that were
> already measured by playback and sit on a channel, one probe at a time across the instance and at most one
> per account per run, never on a Redirect channel, with `ffprobe` under coreutils `timeout` so it dies within
> 17 s even if the worker does. Each probe re-checks eligibility just before it runs, reserves its provider
> slot through the existing slot script with one slot of headroom, so it never takes the last free slot, and
> releases it in `finally`; the reconciler covers it as an in-flight reservation. Results are written only onto
> the measurement that was selected, so playback always wins a race. A failed probe keeps the last measured
> tier and backs off; a refused one defers so other accounts get their turn. No provider URL or credential is
> logged (on top of P1). Spec PR S3b.

### S4 — identities, review queue, decisions, EPG binding and proposals

**Changes.**

- The S4 models, `IdentityPairRejection` and the decision tables' `last_seen_at` included.
- `resolve_identities`, with its advisory lock, durable counter, success-only capped self-dispatch, anchors,
  order-independent fuzzy eligibility (`FuzzyBlockResult`) with the digit-token rule, and diffed writes.
- D5's re-keying in classification, the `last_seen_at` refresh and `prune_catalog_decisions`.
- EPG binding and pins.
- Proposal computation.
- The endpoints.
- The requests from classification and from the EPG refresh.
- The smoke check.
- A measurement of the 300k pass.

**Break-checks.**

- Let a budget-deferred stream create an identity. The deferred-check test reddens.
- Let a group whose `key:` identity already exists skip the eligibility check. The arrival-order test reddens,
  with Arts placed in one order and in review in the other.
- Leave the threshold out of the signature. The threshold-change test reddens.
- Cache the union of near keys instead of the pairs. The disjoint-pairs test reddens on cross suggestions.
- Use the first-seen name as `display_name`. The reversed-order determinism test reddens.
- Make the decision FKs `CASCADE`. The disappear-and-return test reddens.
- Advance `completed` without the ownership check. The killed-connection test reddens.
- Drop the digit-token rule. The numbered-siblings test reddens with `sky sport 1` / `sky sport 2` in review.
- Raise a match for a variant-only tvg_id difference. The variants test reddens with `IdentityMatch` rows.
- Delete and re-insert every match each pass. The no-change writes test reddens on the captured `DELETE`.
- Self-dispatch in `finally`. The self-dispatch test reddens on the failing pass.
- Key M3U decisions on the raw text. The rename test reddens with the exclusion lost.

**PR description draft:**

> Groups classified streams across providers into region- and variant-scoped content identities anchored on
> tvg_id or, without one, on the canonical key, so membership is a pure function of current inputs and
> identities survive incremental builds. Admin decisions, blocked and budgeted fuzzy suggestions (only a
> checked stream may found an identity), review-only conflicts, region-aware EPG binding with pins, explicit
> channel binding, and proposals (catalog rows before channel rows). The resolver is serialised by a Postgres advisory lock
> with a durable request counter. Writes no channel. Spec PR S4.

### S5 — reliability

**Changes.**

- `StreamHealth` and `RelayEventReceipt`.
- The ingest receiver and the prune task.
- `health` on `classifications/`.
- The smoke check.

**Break-checks.**

- Replace receipts with a per-boot maximum. The out-of-order batch test reddens.
- Update the counters before the receipt insert. The concurrent-duplicate test reddens.
- Set the evidence threshold at 1. The single-exposure test reddens at 1 s.

**PR description draft:**

> Records per-stream reliability as decayed exposures (tunes, switch-ins) and failures (failovers away,
> connection failures, buffering) at event ingest, deduplicated by a unique per-event receipt so retried or
> late batches apply exactly once in any order, with the band computed when read. Nothing on the tune path.
> Spec PR S5.

### S6 — ordering and acceptance

**Changes.**

- The `0040` migration and `ChannelOrderSnapshot`.
- `rank_members` and `reorder_channels`.
- D10's never-wait transaction shape for every catalog writer, the 409 `busy` answer, and the pin carry in the
  rehash merge (no new lock in rehash).
- Detach (§ Proposals): fold the override, retire it, set `sync_detached`.
- § Sync changes: the write-time `SYNCED` filters at the five listed sites.
- D7's flip to `manual`.
- The auto-order preview and enable endpoints.
- Restore.
- Accept and dismiss, with adult propagation and pre-commit ranking.
- The smoke check.

**Break-checks.**

- Replace key 5 with the stream id. The non-id tie test reddens.
- Remove the whole non-waiting protection: every `NOWAIT` and the `lock_timeout`. The catalog-backs-off test
  reddens. The reorder is still blocked when the hook releases the paused delete. The test checks this ordering,
  not a duration.
- Remove the batched check before the pending `bulk_create`. The paused-after-pending-construction test reddens
  with two channels for S.
- Delete the override without folding it. The detach effective-output test reddens.
- Drop the `SYNCED` filter at `:2862`. The paused-after-mapping test reddens on the overwritten name.
- Drop the re-read in `_delete_channels_stopping_streams`. The paused-after-orphan-collection test reddens.
- Skip the pre-commit ranking. The first-tune test reddens.
- Create the channel non-adult. The `authorize_stream` adult test reddens.
- Let accept set `auto` unconditionally. The manual-target test reddens.
- Write the accepted channel's `epg_data` with `save(update_fields=["epg_data"])` and drop the `on_commit`
  callback. The no-external-work test reddens: the receiver dispatches inside the open transaction.
- Run the callback's two calls inline instead of from `on_commit`. The rollback-suppression test reddens with
  one dispatch on a rolled-back accept.

**PR description draft:**

> Orders each `auto` channel's streams best quality tier first, then by reliability band, with admin pins on
> top, so the relay's existing failover walks down in quality. Every channel starts `manual`; enabling goes
> through a preview with snapshots; a reorder flips an `auto` channel to `manual` visibly and a restore
> sticks. Catalog writes are short and lock up front with NOWAIT, backing off (retry next pass, or 409 busy)
> on contention; a deadlock with an existing writer stays possible but rare, and either side may be its
> victim, as with concurrent admin edits today. Accepting a proposal is
> revision-checked, ranks an Auto channel before it commits, propagates adult status and asks before adding
> adult streams to a non-adult channel; detaching folds any override into the channel so nothing visible
> changes, and sync revalidates at its write sites so later runs leave a detached channel alone and a run in
> progress does so outside the documented windows. The relay is unchanged. Spec PR S6.

### S7 — the Lineup page and the channel streams table

**Changes.** § Admin UX, except S8's section. Vitest for each component and the store.

**Break-checks.**

- Drop the flip-to-manual toast. The toast test reddens.
- Reword the access warning to say "visible to every user". The dialog test reddens.

**PR description draft:**

> Adds the Lineup page (proposals, review queue, identities with channel and EPG binding, status and
> enablement) and tier, health, pin and order-mode controls on a channel's streams. Mantine and Zustand
> only. Spec PR S7.

### S8 — the naming-convention form

**Changes.** The M3U account form's "Naming convention" section and its live preview (through
`parse-preview/`), writing the D16 sub-dict that S3 already validates and acts on. Vitest for the section.

**Break-checks.**

- Leave `default_region` out of the posted sub-dict. The form test reddens on the payload it posts.
- Drop the preview's convention argument. The preview test reddens: `AR: MBC 1` keeps `ar` in its canonical key
  (`ar mbc 1`), where the convention gives `mbc 1`.

**PR description draft:**

> Adds the form for per-account naming conventions (default region, region-token overrides such as `AR:`
> meaning Arabic, strip prefixes/suffixes, region-source order), with a live preview. The backend has been
> settable through the account API since S3; this is the UI. Spec PR S8.

## Non-goals

- **No active probing** (R1), **with one exception**: R8's re-measurement of a stream whose measurement is due
  (D17, S3b). An unmeasured stream is never probed, nothing is probed in bulk, and the probe is off by default.
- **No LLM assist in this spec** (R5; § LLM assist).
- **No relay switch-policy change** (D9). That rules out climb-back, and also "same tier before lower" for streams
  that sit earlier in the current tier. The smallest later change would be Django-only: rotate within the
  current tier block in `order_alternates_from_current()`. It would need its own parity row and E2E pin. R7
  scheduled it as a separate follow-up, #620, which is out of scope here.
- **No ranking by bitrate, codec or measured fps** (R7). A bitrate tiebreak within a tier is a possible later
  follow-up.
- **No channel preemption.**
- **No change to auto channel sync**, except § Sync changes' write-time filters. **No change** to any
  authorization filter.
- **No VOD or catch-up classification.**
- **No playback-time weighting in health** (D11).

## Risks

- **A wrong deterministic merge serves the wrong region's feed.** This is mitigated structurally (D4, conflicts,
  quarantine). The residual case is a provider that labels an NZ feed `UK:` and also gives it a `.uk` tvg_id.
  The remedy is a region pin.
- **A provider reusing one tvg_id for unrelated channels** merges them under one `tvg:` anchor (R2's tvg_id
  matching). The remedy is an exclusion or reassignment. The Identities tab lists `tvg:` identities whose member
  keys differ, so this is easy to spot.
- **Order churn.** This is mitigated by D8's key 5 and by banding.
- **Stats volume.** S1b posts one event per 30 s per running subprocess channel, plus one per input-metadata change.
- **Contention.** A catalog write and an existing writer can still deadlock, and Postgres may choose the existing
  writer as the victim (D10). That is rare, by design, but possible.
- **Sync windows.** § Sync changes lists the race windows that remain against a sync run already in progress.
- **Health ingest** adds one receipt insert and one locked row update per relevant event, on the API process.
- **Re-measurement probes** (S3b) open provider connections nobody is watching. Some providers count or penalise
  those. Bounded: off by default, one probe open instance-wide, at most one per account per 10-minute run,
  never the last two free slots, at most 20 s each, and only for streams playback already measured. A second
  viewer arriving inside a probe's 20 s on a profile with exactly two free slots is served that channel's next
  stream instead.
- **Word-shaped codes and phrases** are curated lists (`WORD_CODES`, protected phrases). A provider whose
  convention the lists miss either loses a region (fixed by `default_region` or `region_tokens`) or keeps a
  marker in the key (fixed by a protected phrase in a parser bump). The R10 demo exists to find these before S2.
- **M3U decision sharing.** Two entries in one account that parse to the same key share one decision (D5).

## Resolved questions (ruling R7)

The owner accepted the defaults on every open question (ruling R7, 2026-10-31). Nothing is left open.

- **Q1, M1 as its own issue: yes.** Filed as #619 (the Go relay never posts `stream_stats`). It is
  planned in PR S1b, whose description draft refers to it as such. This spec carries no closing keyword.
- **Q2, where `UNKNOWN` sorts: between HD and SD,** as D8 has it.
- **Q3, bitrate as a within-tier tiebreak: no.** It is out of scope here and recorded only as a possible later
  follow-up.
- **Q4** was removed with the LLM assist (R5).
- **Q5, "Detach from auto-sync" when adding streams to an auto-created channel: ticked by default.** The admin
  can untick it. Ticked, the merged channel survives its origin provider dropping the stream, and the catalog
  manages its EPG. Unticked, today's sync behaviour holds.
- **Q6, tier-block rotation (D9's non-goal): yes, as a separate Django-only follow-up,** filed as #620. It is out
  of scope for this spec.

## Appendix A — owner rulings (2026-10-31 and 2026-11-11)

- **R1 Quality measurement: name + passive.** Parse quality hints from stream name and group
  (UHD/4K/FHD/HD/SD/HEVC/50fps/…), overridden by measured `Stream.stream_stats` captured during real playback.
  No active probing: no ffprobe and no extra provider slot use.
- **R2 Identity matching: rules + optional LLM assist.** A deterministic core: normalise the name, extract the
  region from prefix, group and name, and match on tvg_id and EPG data. Fuzzy matches go to an admin review
  queue, and confirmed matches are remembered. An optional, off-by-default LLM may resolve ambiguous leftovers.
  It must never send URLs or credentials, and it must be explicitly enabled.
- **R3 Automation: auto-order, propose new.** Existing served channels have their streams auto-reordered, best
  quality first. New canonical channels are proposed for admin acceptance. Admin pins override everything.
- **R4 Ranking: quality tier, then reliability.** Order by quality tier, best first. Within a tier, order by
  observed health (recent failovers, buffering events and connect failures from relay events).
- **R5 (review round 3): defer the LLM assist.** R2's optional LLM assist gets its own separate spec, design and
  review after this one lands. This spec removes it entirely, leaving only § LLM assist's stub and its one
  inherited requirement.
- **R6** (process: the planner stays on Opus) has no bearing on the design.
- **R7 (2026-10-31): the open questions are resolved to their defaults.** See § Resolved questions.
- **R8 (2026-11-11): quality re-measurement at expiry.** When a stream's measured resolution reaches
  `measured_ttl_days`, do not silently revert to the name tier. Re-measure the stream at that point to see
  whether anything changed, and let the fresh result move it up (or keep it down). This is a narrow,
  deliberate exception to R1's "no active probing": only streams whose measurement is expiring are probed,
  never unmeasured streams in bulk. Until the re-measurement completes, the last measured tier stands.
- **R9 (2026-11-11): the ten code-review findings on `5bcd5944` are accepted**, and the spec is reopened for a
  fix round. Finding 5 (measurement expiry reverting to the name tier) is resolved by R8.
- **R10 (2026-11-11): a demo first.** Before serious implementation, build a demo categorisation engine the
  owner can feed a provider list into and rate the categorisation. A throwaway spike in a separate worktree,
  not merged (branch `spike/classification-demo`).

R1's "overridden by measured `Stream.stream_stats`" is met by `MeasuredResolution`, which is written from the same
`stream_stats` events. R8 narrows R1's "no active probing" to D17 and S3b and to nothing else.

## Changelog

- 2026-10-31: first draft, at `149678aa` (head `09e4d103`).
- 2026-10-31: review round 1 (FAIL, 2 blocking, 13 should-fix, 1 nit). All findings addressed (head `14534539`).
- 2026-10-31: review round 2 (FAIL, 1 blocking, 13 should-fix). Simplified rather than extended (head
  `61af7549`).
- 2026-10-31: review round 3 (FAIL, 2 blocking, 11 should-fix). Owner ruling R5 deferred the LLM assist, which
  closes findings 1 and 2. Then:
  - **Deduplication**: per-event receipts replace the watermark (finding 3).
  - **Relay attribution**: to the source actually run, with existing adoption points preserved and storage owned
    by the attempt (finding 4).
  - **Stats cadence**: input-metadata changes post at once; progress values coalesce into the 30 s flush
    (finding 5).
  - **Fuzzy budget**: only a checked stream creates an identity, and deferred ones stay `fuzzy_pending`
    (finding 6).
  - **Identities**: tvg/key anchors give deterministic, order-independent identities and display fields
    (finding 7).
  - **Deletion**: referenced identities are never auto-deleted, enforced by `PROTECT` (finding 8).
  - **Locking**: one Stream-first order, and rehash takes no Channel lock (finding 9).
  - **Classification triggers**: convention-save dispatch, Re-run, and a daily fingerprint backstop
    (finding 10).
  - **Adult content**: propagation, and an explicit choice when adding adult streams to a non-adult channel
    (finding 11).
  - **First tune**: pre-commit ranking on acceptance (finding 12).
  - **Health**: an explicit 0.25 evidence threshold, with single-exposure behaviour pinned (finding 13).
- 2026-10-31: owner ruling R7 resolved Q1, Q2, Q3, Q5 and Q6 to their defaults. Q1 filed as #619 (planned in
  PR S1b). Q6 filed as #620 (out of scope). § Open questions became § Resolved questions.
- 2026-10-31: review round 4 (FAIL, 0 blocking, 3 should-fix).
  - **Fuzzy eligibility** is now order-independent: computed per block over the current key groups, never existing
    rows, and cached by block signature (finding 1).
  - **One transaction-scoped advisory lock** serialises every membership writer, including each rehash batch,
    with its out-of-batch partners and signal writes (finding 2).
  - **Detach folds any override into the channel**, retires it, and keeps an override's EPG. A one-line sync guard
    found while verifying finding 3 stops the next refresh creating a duplicate channel for the detached stream
    (finding 3).
- 2026-10-31: review round 5 (FAIL, 0 blocking, 4 should-fix).
  - **Locking** (findings 1 and 4). The global advisory lock is dropped, rehash included. Catalog writers now
    never wait: catalog rows first, then `NOWAIT` on every non-catalog row, with a 100 ms backstop, and a
    rollback and retry, or a 409, on conflict.
  - **Sync** revalidates at write time through `SYNCED` filters on its five write sites. The residual windows
    are stated.
  - **Fuzzy cache** (findings 2 and 3). The signature includes the threshold, the scorer and `FUZZY_VERSION`. The
    cache stores scored neighbour pairs.
- 2026-10-31: review round 6 (FAIL, 0 blocking, 2 should-fix, 1 nit). The two disclosed windows are accepted as
  documented risks.
  - **Contention** (finding 1). D10 is restated as best effort. Postgres may choose either side as the deadlock
    victim, and the spec says what happens to each. Catalog-row FK effects (`SET_NULL`, cascades, bind) are
    covered, as is the quiet-period skip. The tests now assert semantics, not timing.
  - **Sync** (finding 2). There is a batched check before the pending-channel `bulk_create` and before the
    membership inserts. The stop loop and the remaining windows are described accurately, and the unconditional
    claims are removed.
  - **Break-check** (finding 3). It now removes the whole non-waiting protection, with an ordering oracle.
- 2026-10-31: review round 7 (PASS, two nits applied at head `5bcd5944`).
- 2026-11-11: owner rulings R8-R10, and ten `/code-review` findings on `5bcd5944` accepted as R9. Then:
  - **Region** (finding 1). Word-shaped two-letter codes (`tv`, `fm`, `at`, `me`, …) count only when delimited,
    never as an undelimited edge token or a tvg_id suffix. Golden and corpus trap cases added.
  - **Fuzzy** (finding 2). A pair whose digit tokens differ is never near, so numbered siblings are not
    sent to review.
  - **Markers** (finding 3). Word-shaped marker and variant tokens are decorations only when delimited or in the
    trailing run; protected phrases (`wwe raw`) are matched first. The stability property is restated exactly.
  - **tvg_id variants** (finding 4). A variant-only difference under one tvg_id raises no match;
    `IdentityPairRejection` clears a region conflict between two identities in one act.
  - **Measurement expiry** (finding 5, by R8). A measurement never reverts to the name tier; D17 and PR S3b
    re-measure due streams with a throttled, headroom-gated probe through the #513 slot script, off by default.
  - **Signals** (finding 6). Catalog `Channel` writes go through `save(update_fields=...)`, with every receiver
    on the channel tables listed (§ Model signals); `updated_at` is still not moved.
  - **Self-dispatch** (finding 7). Only after a successful invocation, with a 30 s countdown and a chain cap of 10.
  - **M3U keys** (finding 8). Keyed on the parse tuple, re-keyed on a parser or convention change, and pruned
    after `decision_prune_days`.
  - **Conventions** (finding 9). The D16 backend moves to S3; S8 is the form only.
  - **Writes** (finding 10). The resolver diffs and upserts by natural key and writes nothing when unchanged;
    admin actions post natural keys.
  - **R10.** The demo engine on `spike/classification-demo` may reopen § Parsing and § Region before S2.
- 2026-11-11: review round 8 (FAIL, 0 blocking, 7 should-fix, 2 nit). Findings 1, 2, 4, 5, 7, 8, 9 and 10 of
  the code review were confirmed resolved. Then:
  - **EPG side effects** (finding 1). Catalog `Channel` writes use `.update()`, and every receiver's effect is
    stated: database effects in the transaction, the EPG cache invalidation and refresh dispatch from
    `on_commit` only. Tests for commit visibility, rollback suppression and no external work under locks.
  - **Probe lifetime** (finding 2). `ffprobe` runs under coreutils `timeout -k 2 15`, a bound that holds if the
    worker dies. A parent-death test.
  - **Fencing** (finding 3). Eligibility is re-checked just before each probe, and every probe write is
    conditional on the selected `observed_at`; a superseded result is discarded. The false "no other writer"
    claim is corrected.
  - **Redirect** (finding 4). Streams on a Redirect channel are never probed; the remaining under-count of
    Redirect viewers is stated as unsupported.
  - **Credentials** (finding 5). A pre-existing tune-path leak in `transform_url` (raw patterns at WARNING and
    DEBUG, exception text at ERROR) is reported, and S3b now depends on a prerequisite fix PR, P1.
  - **Starvation** (finding 6). A refusal defers that candidate by 1 h without counting a failure, and does not
    spend the run's probe budget.
  - **Protected phrases** (finding 7). Matched on a projection without unconditional decorations, so
    `WWE HD Raw` and `UK FHD Gold` parse as the bare phrases.
  - **Nits.** The task's queue is `celery`; S8's break-check asserts `ar` kept in the key.
