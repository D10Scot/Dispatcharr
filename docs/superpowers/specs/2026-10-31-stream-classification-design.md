# Stream Classification and Quality-Ordered Failover

**Date:** 2026-10-31
**Status:** Draft (review rounds 1 and 2 addressed; see § Changelog)
**Rulings:** the owner's rulings R1-R4 of 2026-10-31 override any default here. Appendix A restates
them, so this document can be read without the conversation that produced them.
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
   review queue. Confirmed decisions are remembered, so a re-scan is stable. An optional LLM assist,
   off by default, may suggest answers for what is left (R2).
3. **Classify quality.** Each stream gets a **quality tier**. It is derived from the name, then
   overridden by measured stream statistics captured during real playback (R1). Nothing probes a
   provider.
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
- Credentials live in several places:
  - `M3UAccount.username` and `password` (`apps/m3u/models.py:90-91`), its `server_url`, and its
    `custom_properties` (`:92`).
  - `M3UAccountProfile.search_pattern` / `replace_pattern`, which rewrite stream URLs (`:266-271`), and the
    profile's nested `custom_properties` (`:273-277`, `:338-348`).
  - The stream URLs themselves. For plain M3U these may be the only place a credential appears; the pool
    extracts them from a transformed sample URL (`apps/m3u/connection_pool.py:67-91`).
  - `EPGSource.username`, `password` and `url`.

  Provider text in stream names and groups can contain any of these.
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

## Decisions

| | Decision | Why |
|---|---|---|
| **D1** | **A new Django app, `apps/catalog`.** It owns the parser, the classification, identity, decision and health tables, the Celery tasks and the admin API. `apps/channels` gains only two columns on existing tables (D7). The name is neutral, per `CONTEXT.md` § Mino. | `apps/channels` is already 17,579 lines and sits at the centre of the import mesh's one cycle (CLAUDE.md § Structural constraints). The new app imports `channels`, `m3u` and `epg`. **None of them may import `catalog` at module level.** In particular `apps/channels/models.py` must not, because of the boot trap. Catalog code reaches channels models by string FK (`"dispatcharr_channels.Stream"`; the label, not the directory) and imports them function-locally in tasks. |
| **D2** | **Classification lives in side tables, never on `Stream`.** `StreamClassification` is one-to-one with `Stream` (primary key = `stream_id`, `on_delete=CASCADE`). It stores only what the **parser** derives from the stream's own text. Everything that depends on other inputs (decisions, measurements, health, EPG) is applied when it is read or resolved, never stored on this row. | The refresh writes `Stream` in bulk with a fixed field list (`_bulk_update_stream_refresh_batches`, `apps/m3u/tasks.py:1080-1089`); widening it would put classification on the ingest path. Keeping the row a pure function of the stream's text is what makes D6's invalidation one fingerprint. |
| **D3** | **A purpose-built, versioned parser, `apps/catalog/parse.py`**: pure functions, no ORM, no settings reads inside. Input `(name, group_title, tvg_id, convention)`. Output a frozen dataclass `Parsed(canonical_name, canonical_key, region, region_evidence, region_conflict, name_tier, tier_conflict, codec_hint, fps_hint, markers, variant, variant_conflict)`. `PARSER_VERSION` is an integer bumped on any behaviour change. The algorithm is phased (§ Parsing). | The existing `normalize_name` reads settings and drops the tokens this spec classifies. A pure parser can be golden-tested, property-tested and benchmarked without a database. |
| **D4** | **An identity is `(canonical_key, region, variant)`. Region and variant are part of identity on every automatic path, never a tiebreak.** `variant` holds feed-distinguishing markers that are not quality: `+1` / `+2` (timeshift feeds) and `east` / `west`. No automatic path (tvg_id, key, new-identity creation, proposal) ever joins two streams whose regions or variants differ. A stream with **unknown** region (`""`), an unresolved region conflict, a variant conflict or an empty key is never placed in any identity automatically: only an admin decision places it. | This is the UK/NZ trap, structurally. "Sky Arts" GB and "Sky Arts" NZ have equal keys and different regions, so they are different identities by construction, not by a threshold. A provider reusing one tvg_id for a feed and its `+1` cannot merge them. |
| **D5** | **Decisions are keyed by a stable stream key and are single-valued per key.** The key is `xc:<account_id>:<stream_id>` when the provider gives an id, else `m3u:<account_id>:<sha1(name, group title, tvg_id)>`. `StreamAssignment` holds at most **one** row per key, either *assign to identity X* or *exclude*. `StreamRegionPin` holds at most **one** row per key. `PairRejection` holds one row per *(key, identity)*. Replacement is an upsert in one transaction, and revocation is a delete. Every change **requests a resolve run** (§ Identity resolution), and the resolver applies decisions on every run. **A region pin ends that stream's region conflict**: the resolver uses the pinned region. | `stream_hash` changes when a hashed field changes, and the rehash task merges rows (`core/tasks.py:719`). A key derived from the provider's own id survives both. Single-valued tables make contradictory decisions unrepresentable. Applying decisions in the resolver, not in classification, means a decision never needs a re-parse. |
| **D6** | **Invalidation is "parse when the text changes, derive everything else on every run".** The only cached computation is the parse. `fingerprint = sha1(PARSER_VERSION, convention_version(account), name, group title, tvg_id)`. Identities, conflicts, EPG binding and proposals are recomputed by every resolve run from the current inputs. The effective tier and the health band are computed when they are **read** (by the reorder pass and the API), from their stored raw inputs and the current settings. So a TTL change, a measurement expiring, an EPG refresh, a decision, or a settings edit needs no invalidation of its own. Each only needs a resolve run or a reorder pass to happen, and both have triggers plus a beat backstop (§ When things run). | Round 2 found that a growing list of per-input invalidations kept missing cases (TTL increase after expiry, EPG bulk writes that bypass signals). Removing the cached derived state removes that class of bug. Recomputing identities per run is affordable: passes 1-3 are dictionary work over the classification rows (§ Budget). |
| **D7** | **Ordering control is two new columns on existing tables**: `Channel.stream_order_mode` (`auto` / `manual`, default `manual`) and `ChannelStream.pinned` (bool, default false). Under `auto`, pinned streams keep their relative admin order at the top, and every other stream is placed by D8. Under `manual`, nothing in this spec writes the channel's order. **An admin reorder of an `auto` channel switches it to `manual`.** A reorder means a request that changes the relative order of streams kept on the channel. A **membership-only** edit (adding or removing streams, with the retained streams' relative order unchanged) keeps the mode, and the next reorder pass places the new streams. The response says when the mode flipped, and the UI shows the badge and a one-click "back to Auto". **Restoring a snapshot sets the channel to `manual`** under the same lock, so the next pass cannot undo it. | R3 says admin pins override everything. "Never destroy an admin's manual ordering silently" is met three ways. Every existing channel starts `manual`. A later drag is never overwritten, because it flips the channel visibly. A restore sticks. |
| **D8** | **The ordering function.** The sort key for unpinned streams on an `auto` channel is: (1) **effective tier**, best first: `UHD > FHD > HD > UNKNOWN > SD`; (2) **health band**, in the order `good > fair > unknown > poor` (§ Reliability); (3) `backup` marker last; (4) `fps_hint` descending; (5) the stream's **current** `order` value (then its current position), which keeps ties where they are. Inactive accounts and streams marked `is_stale` sort last. The order is written under D10's lock. | R4: tier, then reliability. `UNKNOWN` sits above `SD` and below `HD` because an unlabelled provider stream is more often 720p or 1080p than 576i (Q2 asks the owner to confirm). An untried stream ranks above a proven-poor one and below a proven-good one. Key 5 is explicit rather than left to the stability of the sort. |
| **D9** | **The relay's switch policy does not change.** The failover keeps "the next candidate after the current one, wrapping" (`order_alternates_from_current`). On a tier-sorted list that already walks down in quality, and it wraps back up to the top tier only once the lower ones are exhausted. **No climb-back** (returning to a higher tier while a lower one still plays) and **no same-tier-before-lower preference** for the streams *before* the current one in its own tier. Both are non-goals (§ Non-goals). | A switch-policy change is a live-path behaviour change. It needs a parity-matrix row and a pinned E2E, and the owner did not ask for one. The headline behaviour, best first and down in quality on failure, follows from the order alone. |
| **D10** | **Every writer of `ChannelStream.order` or `pinned` takes one per-channel lock.** The lock is `select_for_update()` on the `Channel` row, inside a transaction, re-reading the channel's `ChannelStream` rows and `stream_order_mode` after locking. The writers are: the reorder task (writes only rows whose `order` differs); the serializer update (`apps/channels/serializers.py:700-729`); the bulk edit (`api_views.py:1460-1489`); proposal acceptance; snapshot restore; and the rehash merge (`core/tasks.py:719-740`). The merge also carries pins: on collision the surviving row keeps the lower `order` and `pinned = source.pinned or target.pinned`. | Without it the reorder task and an admin drag race last-writer-wins, a drag could be lost silently, and a rehash could drop a pin. The lock is per channel and held for milliseconds. None of these writers is on the tune path. |
| **D11** | **Reliability is counted per exposure, at ingest, with no queue and no playback segments.** An **exposure** is a stream being started (`channel_start`) or switched in (`stream_switch`). A **failure** is a failover away from it, or a connection failure on it, plus a quarter-weight for each buffering episode. A receiver on the `relay_event_applied` signal updates `StreamHealth` directly, in one short transaction per event: two exponentially decayed counters (exposures and failures) and the time they were last decayed. Duplicate deliveries are refused by a **per-relay-process watermark** (`RelayEventWatermark`, one row per `relay_boot`, holding the highest `seq` applied, locked `FOR UPDATE`). An event is applied only if its `seq` is above the watermark. The band is computed when it is read, so an untouched stream's evidence ages without any job. | Round 2 showed that exposure-seconds accounting needed segments, ordering across relay restarts, and a stale-segment rule that counted quiet long playback as death. Counting exposures needs none of that, and R4 asks only for "observed health (recent failovers, buffering events, connect failures)". The relay posts batches from **one** worker in enqueue order, and retries a batch before sending the next (`relay/control/events.go:172-190`, `relay/control/nextsource.go:429-448`). So `seq` arrives in increasing order per process, and a watermark is a complete deduplication record that never needs pruning beyond one row per relay start. |
| **D12** | **Everything is off until the owner turns it on, in three switches**, in a new settings group `catalog_settings`: `classify_enabled` (parse, tier, identities, review queue; it never writes a channel), `auto_order_enabled` (D8 writes for `auto` channels), and `llm_enabled` (D14). Turning `classify_enabled` on **backfills**: it dispatches `classify_account_streams` for every active account, then one resolve. Turning `auto_order_enabled` on goes through a **preview** endpoint. The preview lists every channel whose order would change, and the owner picks which channels to set to `auto` (all, those with ≥ 2 streams, or a selection). Before the first write, each such channel's prior order is saved in `ChannelOrderSnapshot`. | R3 asks for automatic reordering of existing channels. The no-silent-destruction rule asks for it to be visible and reversible. |
| **D13** | **New channels and new members are proposals, never automatic, and the target channel is always explicit.** A `ChannelProposal` has `kind` `new_channel` (the identity has no bound channel) or `add_streams` (the identity has a bound channel that lacks some of its members). An identity's **candidate channels** are the existing channels on which more than half of the streams belong to it. They are computed and shown, never stored. Several candidates is the normal case: auto sync creates one channel per provider stream. **Binding is an explicit admin act** (`ContentIdentity.channel`), and changes no channel. Accepting `add_streams` **keeps the target's `stream_order_mode`**, with "order this channel automatically" as an explicit checkbox. A channel created from `new_channel` starts `auto`, because nothing exists to destroy. Every operation that reads or writes a binding or a proposal follows **one lock order**: `ContentIdentity` row, then `ChannelProposal` row, then `Channel` row (§ Proposals). | R3: propose new, admin accepts. Adding a stream to a channel changes what clients may receive, so it needs acceptance. Choosing among several candidates is a judgement about which channel the admin's clients use, and the spec must not make it. |
| **D14** | **The LLM assist sends only parser-derived key tokens, never raw text, and drops any record that touches a known secret.** It runs only when `llm_enabled` is true **and** `MINO_CATALOG_LLM_API_KEY` is set in the environment. The key is never stored in the database or returned by any API. Per stream it sends the tokens of `canonical_key`, recomputed from the raw name by the parser, plus the region, variant and name tier. It never sends raw names, group titles, tvg_ids or EPG names. Before sending, a record is **omitted** if its raw name or group title matches a URL, email or credential shape, or if any of its outbound tokens equals a token of any known secret, with **no minimum secret length**. What it returns becomes `IdentityMatch` rows with `source=llm`, never a decision, and it never crosses a known region or variant. It uses plain `requests`, so no SDK dependency is added. | R2 forbids sending URLs and credentials. Raw names and group titles are unrestricted provider text, and no redaction of free text can be proven complete. Tokens the parser already produced are a closed, inspectable vocabulary. Comparing them for equality with every known secret's tokens has no length cut-off and no substring false negatives. Matching by equality also keeps a one-character password from wiping out every record by substring. Since S9 is optional and last, giving the model less context is an acceptable price (§ LLM assist says what is lost). |
| **D15** | **The Go relay changes in two small PRs (S1a, S1b), and only to report.** S1a: every event gains `relay_boot` (random per process start) and `seq` (assigned in enqueue order). `stream_switch` gains `from_stream_id` and `trigger`. `channel_buffering`, `channel_error` (`connection_failed`) and `channel_stop` gain the attributed `stream_id`. All attribution comes from one **immutable per-attempt report context** (§ S1a). S1b: `stream_stats` is posted again, only from the current attempt's own measurements, through the same context. No decision the relay makes changes, and the status endpoint's merged `stats` view is unchanged. | M1 and M2. Round 2 showed that reading the channel's *current* stream or generation from a reader goroutine misattributes across a switch, a same-source retry or a late line. A context built once by the run loop, from the source it is about to run, and handed to that attempt's reader, cannot change underneath it. Splitting S1 lets the attribution land and be reviewed before the stats emitter is built on it. |
| **D16** | **Naming-convention overrides live per account** in `M3UAccount.custom_properties["catalog"]`, a validated sub-dict: `default_region`, `region_tokens` (token → ISO code, or `null` to treat it as noise, e.g. `{"AR": null}` where the provider's `AR:` means Arabic, not Argentina), `strip_prefixes` / `strip_suffixes` (literal strings), and `region_from` (an ordered subset of `["tvg_id", "name", "group", "default"]`). `convention_version` is a hash of that sub-dict, so editing it re-parses only that account. | Conventions are per provider, so the owner fixes them where the provider is configured. The sub-dict needs no migration and is validated by a serializer, so a typo is a 400, not a silent no-op. |

## Data model

All new tables are in `apps/catalog`, except the two `apps/channels` columns. **Each table lands in the PR named
beside it, and no PR's migration references a table a later PR creates.**

**S3**

- **`StreamClassification`**, one-to-one with `Stream` (PK `stream`, CASCADE). It holds the parser's output and
  nothing derived from other inputs (D2): `stream_key` (char(80), indexed; D5's key), `fingerprint` (char(40)),
  `canonical_name` and `canonical_key` (char(512); § Parsing bounds them), `region` (char(2), `""` = unknown),
  `region_evidence`, `region_conflict`, `variant`, `variant_conflict`, `name_tier` (small int: `0` UNKNOWN,
  `1` SD, `2` HD, `3` FHD, `4` UHD; D8 defines the rank, not the integer), `tier_conflict`, `codec_hint`,
  `fps_hint`, `markers`, `classified_at`.
- **`MeasuredResolution`**, one-to-one with `Stream` (CASCADE): `height` (int), `width` (int, null),
  `observed_at` (datetime, indexed). It is written **only** by the catalog's receiver for a `stream_stats`
  event with `relay: "go"` that carries a resolution (§ Quality tier). No REST serializer exposes it as writable.
- The **`relay_event_applied`** signal in `core/relay_events.py`. It is sent after each event, **including
  `stream_stats`**, carrying the validated event dict. Receiver exceptions are caught and logged, so a batch
  never 500s.

**S4**

- **`ContentIdentity`**: `canonical_name`, `canonical_key`, `region`, `variant`,
  `unique(canonical_key, region, variant)`; `tvg_id`; `epg_data` (FK `epg.EPGData`, null, SET_NULL);
  `epg_state` (`bound` / `none` / `ambiguous` / `pinned`); `channel` (FK `dispatcharr_channels.Channel`, null,
  SET_NULL; set **only** by an admin, D13); `created_at`.
- **`IdentityMember`**: `stream` (OneToOne, CASCADE), `identity` (FK, CASCADE), `how` (`decided` / `auto_tvg` /
  `auto_key`). It is rewritten by each resolve run. Streams with no row are unplaced, and the API reports why:
  `conflict`, `unknown_region`, `empty_key`, `excluded` or `unmatched`.
- **`IdentityMatch`**, the review queue: `stream` (FK), `identity` (FK, null for a conflict row with no
  candidate), `source` (`fuzzy` / `region_conflict` / `unknown_region` / `llm`), `score` (0-100),
  `suggested_region`, `state` (`open` / `accepted` / `rejected`), `created_at`; `unique(stream, identity, source)`.
- **`StreamAssignment`** (`stream_key` **unique**, `account`, `kind` `assign`/`exclude`, `identity` required
  iff `assign` by a check constraint), **`StreamRegionPin`** (`stream_key` **unique**, `account`, `region`), and
  **`PairRejection`** (`unique(stream_key, identity)`), each with `decided_by` and `decided_at`.
- **`IdentityEpgPin`**: `identity` (OneToOne, CASCADE), `epg_data` (FK, CASCADE, **null meaning "no EPG"**),
  `decided_by`, `decided_at`.
- **`ChannelProposal`**: `identity` (FK), `kind`, `channel` (FK, null), `stream_ids` (JSON list),
  `members_hash` (sha1 of the sorted stream keys), `revision` (int), `state` (`open` / `accepted` / `dismissed` /
  `withdrawn`), `created_at`, `decided_at`, `decided_by`. A partial unique index allows at most one `open` row
  per `(identity, kind)`.
- **`CatalogResolveState`**, a single row: `requested` (bigint), `completed` (bigint), `fuzzy_cursor` (int,
  the last stream id the fuzzy pass reached), `last_run_at`.

**S5**

- **`StreamHealth`**, one-to-one with `Stream` (CASCADE): `exposures` (float, decayed), `failures` (float,
  decayed), `decayed_at` (datetime), and lifetime integer counters for display (`starts`, `failovers_away`,
  `connect_failures`, `buffering_episodes`).
- **`RelayEventWatermark`**: `relay_boot` (char(16), unique), `max_seq` (bigint), `updated_at`. Rows older than
  30 days are deleted by the S5 beat entry. A relay process lives far longer than its 2-attempt retry window,
  and a row is needed only while that process can still retry.

**S6**

- `Channel.stream_order_mode` (char(8), default `"manual"`) and `ChannelStream.pinned` (bool, default `False`),
  in `apps/channels/migrations/0040_*` (the tip at the base is `0039_channel_hls_output_profile.py`; the plan
  re-checks the number at its seed). Both have defaults, so the migration needs no data pass.
- **`ChannelOrderSnapshot`**: `channel` (FK, CASCADE), `stream_ids` (JSON list, in order), `pinned_ids`,
  `reason` (`enable_auto` / `accept_proposal`), `created_at`. The last five per channel are kept.

## Parsing (S2)

The parser runs in fixed **phases**.

1. **Normalise.** Apply NFKC and casefold. Replace `&` with ` and `. Remove the account's `strip_prefixes` /
   `strip_suffixes` (literal, case-folded, at most one of each). No truncation happens here, so expansion
   cannot push a later field past its bound.
2. **Tokenise.** Split on whitespace and the separators `| [ ] ( ) : - _ / ·`. Keep `+1` / `+2` as single
   tokens. Record for each token whether it was **delimited**, meaning bracketed (`[US]`, `(UK)`, `|NZ|`) or,
   as the first token, followed by `:` / `-` / `|` (`UK:`, `NZ -`).
3. **Classify decorations.** Each token is checked against these classes, and a decoration is removed from
   the word list:

   | Class | Tokens (case-folded) | Effect |
   |---|---|---|
   | tier | `8k`, `4k`, `uhd`, `2160p` → UHD; `fhd`, `fullhd`, `1080p`, `1080i` (and the two-token `full hd`) → FHD; `hd`, `720p` → HD; `sd`, `576p`, `576i`, `480p`, `lq` → SD | `name_tier` is the **highest** present; `tier_conflict` when two different tiers occur |
   | codec | `hevc`, `h265`, `x265` → hevc; `h264`, `avc` → h264 | hint only |
   | fps | `\d{2,3}fps`, `50p`, `60p` | `fps_hint` is the highest present |
   | marker | `backup`, `bk`, `raw`, `alt`, `test` | kept in `markers` (sorted, de-duplicated) |
   | variant | `+1`, `+2`, `east`, `west` | kept in `variant`; two different ones set `variant_conflict` |

4. **Extract the region from the name.** This runs on the tokens left **after** phase 3. **Protected
   phrases** in `regions.py` (`uk gold`, `uktv`, and any the plan finds in the corpus) are kept as words.
   A region-table token is consumed as region evidence when it is delimited (anywhere), or when it sits at
   the first or last position **and at least one other word remains**. A lone remaining region token is
   kept as a word. One region token is consumed at most. Two different region tokens that both qualify set
   `region_conflict`.
5. **Group fallback.** If the name gave no tier, tier tokens in the group title are used (`UK | FHD Sports`
   gives FHD). Group region evidence is § Region's source 4.
6. **Key.** Map the standalone tokens `one` … `ten` to `1` … `10`. Drop pure-punctuation tokens. Join the
   remaining words with single spaces. Nothing else is aliased: no stemming, and `sport` ≠ `sports`.
   - **Empty key.** If no word remains (`HD`), `canonical_key = ""`, and the stream is never placed
     automatically (D4).
   - **Overflow.** If the key exceeds 512 characters, it becomes its first 495 characters, then `~`, then
     the first 16 hex digits of the full key's SHA-1. Two different long keys therefore never collide by
     truncation. `canonical_name` uses the same rule.

**Display name.** The members' remaining words in the most common original casing.

**Stability properties, stated exactly.** These hold for the canonical key only. Region, variant and tier are
deliberately not carried in the canonical name.

- `parse(canonical_name).canonical_key == canonical_key`.
- Decorations inserted or removed after phase 2 never change `(canonical_key, region, variant)`.
- `name_tier` is invariant under permutation of tier tokens.

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

With `region_tokens: {"AR": null}`, `AR: MBC 1` becomes `mbc 1` with no region. The S8 golden test pins it.

## Region

**The region table** maps tokens to ISO 3166-1 alpha-2 codes: two-letter codes, a curated alias set
(`uk` → GB, `usa` → US, `aus` → AU, …), and English country names (`new zealand`, `united kingdom`). Tokens that
are also language codes or ambiguous are deliberately **absent** from the default table, and count only through
an account's `region_tokens`: `ar`, `en`, `lat` / `latino`, `int`, `es`, `pt`.

**Parsed evidence, strongest first** (the account's `region_from` may reorder or drop any of these):

1. `tvg_id`: the final dot-segment of `tvg_id` is a region-table token (`SkyArts.nz`, `BBCOne.uk`).
2. `name`: § Parsing phase 4.
3. `group`: a region token, or a country name, in the group title.
4. `default`: the account's `default_region`.

**Conflict.** If `tvg_id` and `name` give different regions, or the name holds two qualifying region tokens, the
parse sets `region = ""` and `region_conflict = true`.

**At resolve time**, a `StreamRegionPin` overrides all of this and clears the conflict (D5). A conflicted stream
without a pin is **review-only**. It takes part in no automatic binding, creates no identity, and appears in no
proposal. It gets one `IdentityMatch(source=region_conflict)` per same-key identity in each claimed region.

EPG data is **not** region evidence. It is used only for binding, below. This removes the EPG-disagreement case
round 2 found undefined, and means EPG refreshes never change a stream's parse.

## EPG binding (S4)

The catalog does not call `apps/channels/epg_matching.py`, which takes the first priority-ranked row for a tvg_id
whatever its region (§ Verified facts). Every resolve run recomputes each identity's EPG, unless it is pinned.

1. **Pin.** If an `IdentityEpgPin` exists, use it (`epg_state = pinned`). A pin with `epg_data = null` means "no
   EPG". If the pinned `EPGData` row is deleted, the pin cascades away and derivation resumes. Revoking a pin is a
   delete.
2. **No tvg_id.** If the identity has no tvg_id, `epg_state = none`.
3. **Collect.** `R` is every active `EPGData` row with that tvg_id (case-insensitive). Each row's region is
   `EPGSource.custom_properties["region"]` when set (an optional field on the EPG form, S7), else the tvg_id's
   suffix region, else unknown.
4. **Region filter.** Keep the rows whose region equals the identity's region. If there are none, and the
   identity's region is known, keep the rows whose region is unknown.
5. **Select.**

   | Kept rows | Result |
   |---|---|
   | none | `none` |
   | one or more, all from **one** source | that source's row, `bound` |
   | from several sources, **at least one with a known region** | the row from the highest `EPGSource.priority`, ties broken by lowest `EPGSource.id`, `bound` |
   | from several sources, **all of unknown region** | `ambiguous`, with no `epg_data`; listed for the admin to pin |

   Identical or differing names make no difference: the selection reads region, source and priority only.

## Quality tier (S3)

- **Name tier**: from the parse.
- **Measured tier**: read from `MeasuredResolution` (D2, written only by the relay's stats events), by
  **height**: ≥ 2000 → UHD, ≥ 1000 → FHD (1080i counts), ≥ 700 → HD, otherwise SD.
- **Effective tier**, computed when read: the measured tier if `observed_at` is within `measured_ttl_days`
  (default 30), otherwise the name tier. The API reports which one it used.

A REST write to `Stream.stream_stats` (`apps/channels/serializers.py:142-149`) cannot touch `MeasuredResolution`.
A TTL change or an expiry takes effect at the next read, with no invalidation. New measurements reach channel
order at the next reorder pass, which runs hourly and after each resolve run (§ When things run).
`video_bitrate` and `source_fps` are displayed but not used to rank (Q3).

## Identity resolution (S4)

**Concurrency: a Postgres session advisory lock, not the Redis task lock.** `acquire_task_lock` stores a shared
literal and releases unconditionally (`core/utils.py:296-315`), and its renewer checks and extends without
ownership (`:327-367`). CLAUDE.md § Known defects says never to carry an unfenced lease forward. Postgres
advisory locks belong to the database session. They have no TTL, need no renewal, cannot be released by another
session, and are freed if the session dies.

**Requesters.** A classification finishing, a decision changing, a `catalog_settings` save, an EPG refresh
completing, the admin "Re-run", or the beat backstop (every 30 minutes):

1. Increments `CatalogResolveState.requested` in its own committed transaction.
2. Dispatches `resolve_identities.delay()`.

**The task:**

1. Calls `SELECT pg_try_advisory_lock(<catalog_resolve key>)` on its connection, outside any atomic block. If it
   gets `false`, it returns.
2. Loops, at most three passes per invocation:
   - Reads `target = requested`.
   - Runs one pass.
   - Inside the pass's final transaction, first confirms it still holds the lock (one `pg_locks` row for this
     backend), then sets `completed = target`.
   - Continues while `requested > completed`.
3. Unlocks in `finally`.
4. **After unlocking**, if `requested > completed`, dispatches itself again.

The ownership check is the fence. A pass whose session died has lost the lock, so its final transaction aborts,
and `completed` is not advanced. Every pass recomputes derived state from current inputs, so a pass that aborted
part-way leaves nothing a later pass cannot overwrite.

**Crash recovery** is the durable counter. A crash leaves `requested > completed`, and any later request or the
backstop runs it. Nothing is consumed before it is done, so no request can be lost the way a cleared Redis key
could.

**Bounded fuzzy work.** The fuzzy pass resumes from `fuzzy_cursor`. It stops after `fuzzy_max_comparisons`
(default 5,000,000, about 30 s at M4's rate), saves the cursor, and increments `requested` so that work
continues in a later pass or invocation. A full sweep resets the cursor to 0. A block larger than 2,000
identities is split by the second key token. A block still larger is skipped for that stream, which stays
unplaced as `unmatched`. Each invocation is therefore bounded to three passes, each with bounded fuzzy work. S4
measures one pass over a synthetic three-account, 300k-stream corpus on the test container and records it.

**Passes**, in order. A stream is skipped from pass 2 onward if, with its pin applied, its region is unknown or
in conflict, its variant is in conflict, or its key is empty.

1. **Decisions.** Assignments place or exclude streams (`decided`). Pins set the effective region.
2. **Exact tvg_id.** Same non-empty case-folded tvg_id, **same known region and same variant**: one identity
   (`auto_tvg`). The same tvg_id with a different region or variant stays apart, and each side gets an
   `IdentityMatch(source=region_conflict)`.
3. **Exact key.** Same `(canonical_key, region, variant)`, region known: one identity (`auto_key`).
4. **Fuzzy, blocked and budgeted.** Within identities of the same region, variant and first key token,
   `rapidfuzz` `token_sort_ratio` at `fuzzy_threshold` (default 90), at most three candidates, each becoming
   `IdentityMatch(source=fuzzy)`. **Fuzzy never binds.**
5. **New identity.** A stream still unplaced, region known, no fuzzy candidate: its own identity (`auto_key`).
6. **Unknown region.** `IdentityMatch(source=unknown_region)` against the same-key identity in each region.
7. **EPG binding** for every identity (§ EPG binding).
8. **Proposals** (§ Proposals).
9. **LLM**, only under D14's conditions.

`PairRejection` suppresses its match in every pass. An identity left with no member is deleted, unless it has
a bound channel or an EPG pin. Such an identity is kept, and shown as empty.

## Proposals (S4 computes, S6 accepts)

**Lock order, everywhere.** Lock the `ContentIdentity` row, then the `ChannelProposal` row, then the `Channel`
row, each with `select_for_update()`. Every operation that reads or writes a binding or a proposal follows this
order:

- bind
- unbind
- the resolver's proposal step
- accept
- dismiss

**Recompute** (resolver step 8, per identity, holding that identity's lock):

- **The wanted proposal.**
  - With no bound channel, it is a `new_channel` proposal whose members are every member stream.
  - With a bound channel, it is an `add_streams` proposal whose members are the member streams not already
    on that channel.
  - Nothing is wanted if the member set is empty.
- **Withdraw.** An open proposal whose kind or channel no longer matches the wanted one is marked
  `withdrawn`. Binding withdraws `new_channel`, and unbinding withdraws `add_streams`.
- **Update in place.** An open proposal of the right kind has its members updated. Its **`revision` is bumped
  only when `members_hash` or `channel` changes**, so an unchanged rescan never invalidates an admin's open
  dialog.
- **Dismissed sets stay dismissed.** If the latest proposal for this identity and kind was dismissed with the
  same `members_hash`, no new one is opened. A new member opens one.

**Bind and unbind** (`POST identities/{id}/bind`, `/unbind`) lock the identity row, set or clear `channel`, and
run the recompute step for that identity in the same transaction.

**Accept** (`POST proposals/{id}/accept`, S6, body `{revision, options}`), in one transaction:

1. Lock the identity, then the proposal, then the target channel for `add_streams`.
2. Require `state = open` and a matching `revision`. Otherwise answer 409 with the current revision.
3. For `add_streams`, require that `identity.channel` is still the proposal's channel. For `new_channel`,
   require that the identity is still unbound.
4. Drop members that were deleted, have gone stale, are already on the target, or are no longer members, and
   return them. If none remain, answer 409.
5. For an existing target, write a `ChannelOrderSnapshot` (`accept_proposal`).
6. Add the members (a membership-only edit under D7).
7. Set `stream_order_mode` only when the admin opted in.
8. For `new_channel`, create the channel and set `identity.channel`.
9. Mark the proposal `accepted`.

A competing accept, bind or unbind waits on the identity lock, then fails at step 2 or step 3.

**EPG on accepted channels.** The catalog writes `epg_data` only on a channel with `auto_created = False`, and
only when the identity's `epg_state` is `bound` or `pinned`. Auto sync rewrites `epg_data` on every channel it
manages (`apps/m3u/tasks.py:2693-2702`). So the catalog leaves EPG on an auto-created target to sync, and the
dialog says so. If the admin ticks "Detach from auto-sync" (the default is Q5), the channel becomes catalog-managed
and receives the identity's EPG in the same transaction.

## Reliability (S5)

**Ingest.** The `relay_event_applied` receiver handles events carrying S1a's `relay_boot` and `seq`. Events
without them come from a relay older than S1a, and are ignored. Each relevant event gets its own
`transaction.atomic()`, so the watermark and the counters commit together:

1. `select_for_update` the `RelayEventWatermark` row for `relay_boot`, creating it if missing. If
   `seq <= max_seq`, stop: this event is a duplicate. Otherwise set `max_seq = seq`.
2. Apply the event to `StreamHealth` (locked with `select_for_update`, created if missing). Decay first:
   multiply both counters by `d = 2 ** (-(now - decayed_at) / half_life)` and set `decayed_at = now`. Then add:

   | Event | Stream | exposures | failures |
   |---|---|---|---|
   | `channel_start` | `stream_id` | +1 | |
   | `stream_switch` | `stream_id` (switched in) | +1 | |
   | `stream_switch`, `trigger` ∈ {`health_monitor`, `buffering_timeout`} | `from_stream_id` | | +1 |
   | `channel_error`, `error_type = connection_failed` | `stream_id` | | +1 |
   | `channel_buffering` | `stream_id` | | +0.25 |

`max_retries_exceeded` switches are not counted, because the preceding `connection_failed` was. Operator switches
count only the exposure. `channel_stop` changes nothing. A long, quiet, successful viewing is one exposure and no
failure, which is exactly a healthy stream. Events whose stream no longer exists are skipped.

**The band**, computed when read (the API and the reorder pass), after decaying to `now`:

```
unknown  if exposures + failures < 1
poor     if exposures < 1 and failures >= 1           # failure-only evidence
rate     = failures / exposures
good     if rate < 0.05
fair     if rate < 0.20
poor     otherwise
order:   good > fair > unknown > poor                  (D8)
```

`half_life = health_half_life_days` (default 7). An untouched stream's counters decay at read time, so an old
band ages out with no job. The formula and its constants live in `apps/catalog/health.py`, and the S5 tests pin
the formula, not the numbers. The read surface is the `health` object on `GET /api/catalog/classifications/`
(band, decayed counters, lifetime counters), added in S5.

## When things run

| Task | PR | Trigger | Concurrency |
|---|---|---|---|
| `classify_account_streams(account_id)` | S3 | `.delay()` from the refresh tail after `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:3942`), in its own `try` that only logs and never sets the account status; and the D12 backfill | advisory lock keyed by `(catalog_classify, account_id)` |
| `resolve_identities()` | S4 | requests listed in § Identity resolution. S4 adds the request at the end of `classify_account_streams` and at the end of the EPG refresh task. | advisory lock (§ Identity resolution) |
| `reorder_channels(channel_ids=None)` | S6 | after each resolve run; hourly as a backstop (this picks up measurement and health changes, which are computed when read); only if `auto_order_enabled` | D10 per channel |
| `prune_relay_watermarks()` | S5 | daily | none needed |

**Dispatch is wired only in the PR that adds its destination.** S3 does not request a resolve, because S4 adds
the resolver. A failure in any task is logged and leaves the previous state. None of these tasks runs on the
tune path.

**Budget, 100k streams in one account.** From M4, with a 10× allowance: parse ~2 s, fingerprint ~0.3 s.
Reading with `.only(...)` and `.iterator(chunk_size=2000)` takes 5-10 s (estimated). A first-run upsert of 100k
rows takes 20-60 s (estimated; **S3 measures it**). A resolve pass loads the classification rows of every
account and does dictionary work: an estimated 10-20 s per 300k rows plus the bounded fuzzy budget. **S4 measures
it.** Everything runs on the Celery `default` worker.

## LLM assist (S9)

Off by default (D12, D14). It considers unplaced streams (`unmatched`, `unknown_region`) and open fuzzy matches
scored 70-90, at most `llm_max_streams_per_run` (default 500).

**Known secrets** (`collect_secrets()`, built once per run, local only). Every value below is taken whole and
also split with the parser's tokeniser (§ Parsing phases 1-2) into **secret tokens**, with no minimum length:

- Every `M3UAccount`'s `name`, `username`, `password` and `server_url` (scheme removed; userinfo, host, each
  host label, each path segment, each query value).
- Every `M3UAccountProfile`'s `name`, `search_pattern` and `replace_pattern`. Also the profile's transformed
  form of **every distinct URL prefix** among its account's streams, run through `transform_url`
  (`apps/proxy/next_source.py:271`); the scheme-and-host-and-first-two-path-segment prefixes are deduplicated,
  so the cost is per prefix, not per stream. Each transformed URL is split exactly like `server_url`, and
  `extract_credentials_from_stream_url` (`apps/m3u/connection_pool.py:57-64`) is applied as well.
- Every string leaf, at any depth, of `M3UAccount.custom_properties` and `M3UAccountProfile.custom_properties`
  whose key path contains `user`, `pass`, `token`, `key`, `secret`, `auth` or `url`.
- Every `EPGSource`'s `username`, `password` and `url`, split like `server_url`.

**Building a record** (`build_request(streams, candidates, secrets)`, a pure function):

- **Omit the record** if its raw name or group title matches any of these patterns: a URL scheme
  (`[a-z][a-z0-9+.-]*://`), `@`, an email shape, or a run of 24 or more base64- or hex-alphabet characters.
- Otherwise parse the raw name with the account's convention. **Omit the record** if any token of the
  resulting key equals a secret token, or if the joined key contains any whole multi-token secret value.
- Otherwise emit
  `{"ref": "s<n>", "tokens": [...key tokens], "region": "GB"|null, "variant": "", "tier": "FHD"}`.
- A candidate identity is emitted as `{"ref": "i<n>", "tokens": [...], "region": ..., "variant": ...}`, under
  the same omission rule.
- `ref` values are per-request indices, mapped back locally.
- **Nothing else is sent**: no raw name, group title, tvg_id, EPG name, URL, account or profile field, database
  id, stream key or UUID.

**Final guard.** This is separate from the builder, and runs just before sending. The serialised request is
re-tokenised. If any token equals a secret token, or the bytes contain `://` or `@`, the request is not sent, and
only a count and the reason category are logged.

**What is lost.** The model sees the same words the parser kept: no group title context and no tvg_id. That is
enough for the leftovers this targets (spelling variants, word-order differences, abbreviations). Q4 is
unchanged.

**Response handling.** The expected shape is
`[{"ref": "s1", "candidate": "i1" | null, "region": "GB" | null, "confidence": 0..1}]`. It is validated by a
serializer, and anything else is dropped. A candidate whose region or variant differs from the stream's known
region or variant is dropped. The survivors become `IdentityMatch(source=llm)`, never decisions.

**Transport.** One adapter, `apps/catalog/llm.py`: `requests` to the Anthropic Messages API, with the model id
in the `llm_model` setting (its default is chosen by the S9 plan from the provider's current list), and the key
from `MINO_CATALOG_LLM_API_KEY`. It logs counts and status codes only. The settings UI shows only whether the key
is present.

## Admin UX (S7)

Mantine 8 only. State goes in a new Zustand store, `frontend/src/store/catalog.jsx`. All HTTP goes through new
`API.*` methods in `frontend/src/api.js`. No new UI library, and no direct fetch from components.

- **New page `/catalog`, "Lineup"** (`frontend/src/pages/Catalog.jsx`, route in `frontend/src/App.jsx` next to
  `/channels` at `:152`, nav entry beside Channels), with four tabs:
  - *Proposals*: one row per open proposal, showing identity, region, kind, members (tier and provider),
    target channel and revision. **Accept** opens a dialog with:
    - group and channel number;
    - Channel Profiles;
    - "order this channel automatically" (D13);
    - for an auto-created target, the detach option and its EPG note (§ Proposals).

    Other actions: **Dismiss**, and **bulk accept** (each proposal is accepted on its own).
  - *Review*: open `IdentityMatch` rows grouped by stream, each with a source badge (`fuzzy` /
    `region conflict` / `unknown region` / `LLM`). Actions: Assign, Reject pair, Pin region (prefilled from
    `suggested_region`), Exclude, New identity.
  - *Identities*: searchable. Each identity shows its members in D8 order, with tier, tier source, health band
    and provider. It also shows the candidate channels with **Bind**, and an EPG chooser that writes an
    `IdentityEpgPin`. An `ambiguous` identity is flagged.
  - *Status*: run times, counts per state, **Re-run**, and the enablement switches with D12's preview.
- **Channel streams table** (`frontend/src/components/tables/ChannelTableStreams.jsx`):
  - a tier badge, marked "measured" or "from name";
  - a health-band dot;
  - a pin toggle;
  - an "Order: Auto / Manual" control;
  - "Restore previous order", which sets Manual (D7). After a drag on an `auto` channel, the toast says the
    channel is now Manual.
- **EPG source form** (`frontend/src/components/forms/EPG.jsx`): an optional Region select (§ EPG binding).
- **Settings** (`frontend/src/pages/Settings.jsx`): "Stream classification", for `catalog_settings`.
- S8 adds the M3U account form's "Naming convention" section. S9 adds the LLM settings fields and the `LLM` badge.

**Access warning in the accept dialog.** When no Channel Profile is picked, the dialog says: *"With no Channel
Profiles, this channel is visible only to admins and to users who have no Channel Profiles. Users assigned to
profiles will not see it until you add it to one of theirs."* This matches `user_can_access_channel`
(`apps/proxy/authorize.py:202-223`). No authorization filter changes.

**API** (`apps/catalog/api_urls.py`, at `/api/catalog/`). Each endpoint has a DRF serializer, appears in the
drf-spectacular schema, and is `IsAdmin` with no opt-down.

- S3: `classifications/` (list and filter, with the effective tier and its source) and `parse-preview/`.
- S4: `identities/` (list and retrieve, `bind`, `unbind`, `epg-pin`), `matches/` (`assign`, `reject`),
  `assignments/`, `region-pins/` and `rejections/` (list, upsert, delete), `proposals/` (read-only), and `run/`.
- S5: `health` on `classifications/`.
- S6: `proposals/{id}/accept`, `proposals/{id}/dismiss`, `auto-order/preview`, `auto-order/enable`, and
  `channels/{id}/order-snapshots/` with `restore`. The channel serializer gains `stream_order_mode` and `pinned`.

## Coexistence

- **Manual assignment.** Untouched on `manual` channels, which is every existing channel at the start (D7). On
  `auto` channels, a reorder flips the channel to `manual`, and a membership-only edit keeps the mode.
- **Auto channel sync.**
  - Sync's one-stream channels appear as candidate channels, and the admin binds one or none (D13).
  - Sync never sees `stream_order_mode` or `pinned`, and reorders write only `order`.
  - The catalog never writes `epg_data` on an auto-created channel (§ Proposals), so sync's EPG rewrite
    (`apps/m3u/tasks.py:2693-2702`) and the catalog never disagree on one channel.
- **Stream rehash and merge** (`core/tasks.py:719`). D10 brings the merge under the lock and carries pins.
  Decisions survive because they are keyed per D5.
- **Stale and deleted streams.** Stale streams sort last (D8). Deleted streams cascade out of every catalog
  table. Health events for a deleted stream are skipped.

## Known-defect interactions

- **Provider-slot counters (#513).** This spec touches no provider-slot counter and adds no `INCR` or `DECR`.
  A tier-first order concentrates initial tunes on the best provider. When that provider is full,
  `get_stream()` skips to the next stream.
- **The copied channel-authorization filter.** Untouched. No client-facing surface is added, and the
  access-warning prose states the real rule.
- **Unfenced leases** (CLAUDE.md § Known defects, the ownership lease). The resolver and the classifier use
  Postgres advisory locks rather than the Redis task lock.
- **The boot trap.** No module that `apps/channels/models.py` imports gains an import (D1).
- **CoreSettings blast radius.** `catalog_settings` is a ninth instance-wide group. S3 ships a data migration
  seeding its row, because `epg_settings` shows a `PATCH` can fail before the row exists. Any E2E test that
  writes it joins the allowlist (`docs/adr/0003`).
- **Credential logging.** The LLM adapter and the parse-preview endpoint log no URL and no payload.
- **Rename ratchet (Mino spec PR R1).** If R1 has landed, a new file containing `dispatcharr` raises
  `scripts/product_name_allowlist.txt`. That includes the package import, the `dispatcharr-ci` profile and the
  `dispatcharr_channels` label. Each plan lists every such line, and each must be one the rename spec keeps
  (C-9, C-10, C-13).

## Test strategy

**Celery in tests.** `CELERY_TASK_ALWAYS_EAGER` stays globally off (`dispatcharr/settings_test.py:29-33`). Tests
call task bodies directly, and patch `.delay` where they assert a dispatch.

**Stopping-point smoke check, in every PR from S3 on**, as a backend test in the PR's own label. It checks that
the PR's migrations apply on top of the previous stopping point's schema with no pending migration, and runs one
request against each endpoint the PR adds.

**Corpus** (`apps/catalog/tests/fixtures/stream_names.jsonl`). At least 400 lines with expected parses, covering:

- every golden case above;
- prefix, suffix and bracket regions;
- protected phrases;
- ALL CAPS;
- decorations after a suffix region;
- group-only tiers and regions;
- tvg_id-only regions;
- the ambiguous tokens;
- an expansion overflow;
- an empty key;
- a variant conflict.

**The trap set**: at least 20 brands present in two regions, five decorations each. Nothing in the corpus is a
real URL or credential, and a test asserts no line contains `://`.

**Property tests** (S2, the shared `dispatcharr-ci` profile, registered byte-identically):

- the three stability properties in § Parsing;
- an edge or delimited region token yields its code and is absent from the key;
- for every trap brand and any decorations, the GB and NZ names yield GB and NZ.

**Resolution tests** (S4):

- UK and NZ streams with an equal key and an equal tvg_id produce two identities and conflict rows.
- A tvg_id shared by a feed and its `+1` produces two identities.
- Conflicted, unknown-region, variant-conflict and empty-key streams are never placed or proposed.
- A pin ends a conflict.
- At most one assignment exists per key.
- A rejection survives a re-run and a rehash.
- Fuzzy never binds.
- **Lock** tests (two database connections, Postgres-only):
  - a second resolver gets `false` and returns;
  - killing the holder's connection mid-pass (`pg_terminate_backend` from the test) leaves `completed`
    unchanged and frees the lock;
  - a request made during the final pass, and one made after unlock but before the post-unlock check, each
    produce exactly one further pass;
  - an exhausted fuzzy budget resumes from the cursor in the next pass.
- **EPG**:
  - the same tvg_id in a GB-region and an NZ-region source binds each identity to its own row;
  - two unknown-region sources give `ambiguous`;
  - a pin survives re-runs, and a deleted pinned row resumes derivation;
  - a GB/NZ tvg_id collision on an auto-created channel survives a following `sync_auto_channels` run, with
    the catalog writing nothing to that channel's EPG.
- **Proposals**:
  - an unchanged rescan keeps the revision;
  - binding withdraws `new_channel`;
  - a concurrent bind and accept: one wins, the other gets 409;
  - dismissal persists until a new member appears.

**Ordering tests** (S6):

- A tie whose current order is deliberately not id order survives two passes, and the second pass writes nothing.
- A `manual` channel is never written.
- A reorder on an `auto` channel flips it to `manual`, and a membership-only edit does not.
- A restore sets `manual`, and the next pass leaves the channel alone.
- A concurrent reorder and `PATCH`: the `PATCH` wins.
- A rehash with a pin only on the source row, and with a pin only on the target row: the pin survives either way.
- Accept with a stale revision, with a deleted member, as a second accept, and into a `manual` target.
- `get_stream()` and the failover branch choose the tier-sorted first stream.

**Tune-path ledger**: `apps/proxy/tests/test_tune_path_query_ledger.py` passes unchanged in every PR.

**Quality tests** (S3):

- A REST write of `stream_stats` with a resolution after a valid Go measurement leaves `MeasuredResolution` and
  the effective tier unchanged.
- A measurement older than the TTL yields the name tier.
- Raising the TTL brings it back at the next read.
- A `stream_stats` event without `relay: "go"` writes no `MeasuredResolution`.

**Health tests** (S5):

- The decay formula, with an injected clock.
- The table of contributions.
- A duplicated batch applies once.
- **A batch replayed after it was applied, and after other events from the same boot** applies nothing.
- Two boots interleaved in either lexical order each apply once.
- A failure-only stream bands `poor` and sorts below `unknown`.
- An untouched stream's band ages at read time with no write.
- Events without S1a fields change nothing.

**LLM tests** (S9) test the builder and the final guard **separately**:

- **Builder, exact output.** The fixture account has a two-character username, a three-character password,
  and credentials present only in its stream URLs (none in `username`/`password`), plus one **clean** stream
  and one stream whose name contains each secret as a bare word.
  - The builder's returned structure (asserted before any guard runs) contains exactly the clean stream's
    record, with tokens equal to `parse(raw_name).canonical_key.split()`.
  - Every poisoned stream is omitted.
- **Builder, stored classification ignored.** The clean stream's stored `StreamClassification.canonical_key` is
  overwritten with a secret. The builder output still equals the parse of the raw name.
- **Final guard alone.** A hand-built request containing a secret token, or `://`, is refused, and the fake
  transport records zero calls.
- A cross-region or cross-variant answer is dropped.
- With the feature disabled or the key unset, zero calls are made.

**Frontend**: vitest for each new component and store, with `api.js` mocked.

## The PRs

Branches are `feature/catalog-*`, except S1a and S1b, which touch the live path and are named
`migration/catalog-s1a-…` / `-s1b-…` so the full E2E matrix runs (CLAUDE.md § Full E2E runs). No PR description
below carries a closing keyword.

**Dependencies and stopping points.** Each stopping point passes its smoke check (§ Test strategy), and works with
what it has.

| PR | Needs | Stopping point |
|---|---|---|
| S1a | none | events carry identity and attribution |
| S1b | S1a | `stream_stats` posted again |
| S2 | none | parser, inert |
| S3 | S2 | tiers visible, read-only (name-only until S1b data arrives) |
| S4 | S3 | identities, review queue, decisions, binding, read-only proposals; **writes no channel** |
| S5 | S3 (settings, signal), S1a (data) | health visible on `classifications/` |
| S6 | S4, S5 | ordering and acceptance: the headline behaviour, API-driven |
| S7 | S6 | the full UI |
| S8 | S3 (backend), S7 (UI section) | naming conventions |
| S9 | S4 (backend), S7 (UI) | the optional LLM assist |

### S0 — this spec

Docs only. It cites a tracking issue with `Refs`, if one is filed.

### S1a — attribution and event identity (Go, reporting only)

**Changes.**

- **Report context.** It is defined in `relay/channel` as `type report struct{ streamID int; attempt uint64 }`.
  - **Where it is built.** `runAttempt` (`relay/channel/channel.go:668`) builds it once per attempt, from the
    stream id the run loop paired with the `source` it is about to run. The loop keeps that pairing locally:
    `first`'s stream id at start, and the `Resolved.Info.StreamID` of whatever it adopts (a pending switch or a
    failover result). The context is never read from `c.currentStreamID`.
  - **The attempt counter.** `c.attempt` is incremented under `c.mu`.
  - **Handing it over.** It is passed to the source through `attach` (`:482`'s interface gains the parameter).
    `TranscodeSource` stores it per attempt, and its stderr reader copies it once at creation
    (`source_transcode.go:192`).
  - **Who emits with it.** Everything that reader emits is attributed by its copy, never by the channel's
    current stream. That covers `channel_buffering`, and it is the hook S1b uses for stats.
- **Attribution.**
  - `stream_switch` gains `from_stream_id` (the stream id of the attempt being replaced) and `trigger`
    (`health_monitor` / `max_retries_exceeded` / `buffering_timeout` / `operator`).
  - `channel_error` `connection_failed` (`channel.go:604`) gains the stream id of the source that failed.
  - `channel_stop` (`:759`) gains the last attempt's stream id, and sets both `details["stream_id"]` and the
    top-level field, because it builds its `Event` directly (`events.go:39-41` lifts it for the others).
- **Event identity.** `Emitter` (`relay/control/events.go`) draws `relay_boot` (16 random hex characters) at
  `NewEmitter`, and assigns `seq` from an atomic counter at enqueue. Both go into `details`. A full queue that
  drops an event leaves a gap, which is harmless.
- `docs/relay-parity-matrix.md` gains two rows: attribution, and event identity, each naming its Go test.

**Tests.**

- Each trigger's `stream_switch` carries the right `from_stream_id` and `trigger`.
- **A switch decided before the next attempt starts** (an operator `Advance` racing `runAttempt`): the new
  attempt's context names B, and the old reader's events name A.
- **Same-source retry**: two attempts on stream A get attempt numbers n and n+1, both stream A.
- **Late buffering line**: after a switch to B, a speed line fed to A's reader emits `channel_buffering` with
  `stream_id` A.
- The emitter's `seq` strictly increases, and `relay_boot` is constant within a process.

Coverage follows the Phase 4 floor rule (D20).

**Break-checks.**

- Read the stream id from `c.currentStreamID` in the stderr reader. The late-buffering test reddens, naming B.
- Drop `from_stream_id`. The trigger test reddens.

**PR description draft:**

> Adds attribution the reliability work needs, without changing any relay decision: every event carries a
> per-process `relay_boot` and an increasing `seq` (so Django can refuse a retried batch), and
> `stream_switch` gains `from_stream_id` and `trigger`, `channel_error` `connection_failed`,
> `channel_buffering` and `channel_stop` gain the stream they are about. Attribution comes from an
> immutable per-attempt context built by the run loop, so a line from a replaced source is still credited
> to that source. Two parity-matrix rows. Spec PR S1a.

### S1b — `stream_stats` posted again (Go, reporting only)

**Changes.**

- **The `measured` struct.** `Channel` gains a struct, `measured`, used only for posting. `runAttempt` resets
  it at the start of **every** attempt, same-source retries included, and records the attempt's context.
- **Merging.** `reportInfo` and `reportProgress` take the reader's context. They merge into the existing `stats`
  exactly as today (the status view is unchanged). They merge into `measured` only when
  `ctx.attempt == c.attempt`.
- **When it is posted.**
  - The event carries `relay: "go"`, `stream_id` from the context, and only the keys present in `measured`,
    under the Python names: `video_codec`, `resolution`, `width`, `height`, `source_fps`, `pixel_format`,
    `video_bitrate`, `audio_codec`, `sample_rate`, `audio_channels`, `audio_bitrate`, `stream_type`,
    `ffmpeg_output_bitrate`.
  - It is posted on the first change in an attempt (then at most once per second on further changes), every
    30 s from a ticker the attempt owns, and once when the attempt ends.
  - `runAttempt` defers both the stop and the final flush, so a switch, a retry and a channel stop all flush the
    ending attempt's own measurement.
  - An empty `measured` is never posted.
- **Scope.** Subprocess architecture only (row 29 unchanged).
- **Django.** No change beyond what S3 adds. `_apply_stream_stats` keeps writing the display copy on `Stream`.
- **Parity matrix.** One row: the cadence and the per-attempt rule.

**Tests.**

- With an injected clock and the stderr corpus: the keys, the 30 s flush, and the end-of-attempt flush.
- **A then B, with B silent**: no event names B with a resolution. Variants: a buffering switch, an operator
  switch, a stop straight after the switch, and a switch decided before B's attempt starts.
- **Same-source silent retry**: the retry posts nothing that the first attempt measured.
- **A late A line after the switch** changes `stats` but posts nothing.
- **Proxy** posts nothing.

**Break-checks.**

- Skip the reset on a same-source retry. The silent-retry test reddens.
- Drop the attempt comparison. The late-line test reddens, naming B.

**PR description draft:**

> Restores the posting of `stream_stats`, which the Go relay parsed and served on
> `GET /proxy/relay/channels` but never sent to Django after the cutover. Each post carries only what the
> current connection attempt itself measured, attributed through S1a's per-attempt context, so a
> measurement is never stored against a stream that did not produce it; the status view is unchanged. One
> parity-matrix row. Spec PR S1b.

### S2 — the parser (pure, inert)

**Changes.**

- The `apps/catalog/` skeleton, added to `INSTALLED_APPS`.
- `parse.py`, `regions.py` (the table and protected phrases) and `conventions.py` (D16 validation and
  `convention_version`).
- The corpus, golden tests and property tests.
- `CONTEXT.md` gains **Content identity** and **Quality tier**.

The plan confirms that `dispatcharr/test_discovery.py` and `FULL_SUITE=1 python3 scripts/ci_backend_test_labels.py`
pick up the new label, and adds a `_PATH_ALIASES` entry if needed.

**Break-checks.**

- Remove `nz` from the table. The trap property reddens, reporting region `""` where NZ was expected.
- Run region extraction before decoration removal. The `Sky Arts UK FHD HEVC 50FPS` golden line reddens on
  region.
- Truncate before normalising. The overflow golden line reddens on length.

**PR description draft:**

> Adds `apps/catalog` with a pure, versioned stream-name parser: canonical key, region and its evidence,
> tier/codec/fps hints, markers and feed variant, in fixed phases, with bounded output. Nothing runs yet. A
> 400-line real-shaped corpus with a two-region brand trap set is golden-tested; Hypothesis pins key
> stability, decoration independence and region extraction. Spec PR S2.

### S3 — classification, measured resolution and tiers

**Changes.**

- The `StreamClassification` and `MeasuredResolution` models.
- The `relay_event_applied` signal, and the catalog receiver for `stream_stats`.
- `classify_account_streams`, with the refresh-tail dispatch and the D12 backfill.
- The `catalog_settings` getter, and a data migration seeding its row.
- `classifications/` and `parse-preview/`.
- The smoke check.
- A measurement of the 100k first-run upsert, recorded in the PR.

**Break-checks.**

- Read the measured tier from `Stream.stream_stats`. The REST-write test reddens.
- Store the effective tier at classification time. The TTL-raise test reddens.
- Drop `PARSER_VERSION` from the fingerprint. The version-bump test reddens.

**PR description draft:**

> Classifies every live stream after an M3U refresh, behind the off-by-default `classify_enabled` setting
> (enabling it backfills every account): a parse row per stream, rebuilt only when its text changes, and a
> catalog-owned measured resolution written only from the relay's stats events. The effective tier is
> computed when read, so expiry and TTL changes need no invalidation, and a REST edit of `stream_stats`
> cannot fake a measurement. Writes no channel. Spec PR S3.

### S4 — identities, review queue, decisions, EPG binding and proposals

**Changes.**

- The S4 models.
- `resolve_identities`, with its advisory lock, durable request counter and fuzzy cursor.
- EPG binding and its pins.
- Proposal computation, under the lock order.
- The S4 endpoints.
- The requests from classification and from the EPG refresh tail.
- The smoke check.
- A measurement of the 300k global pass.

**Break-checks.**

- Let the tvg_id pass ignore variant. The `+1` test reddens.
- Advance `completed` without the ownership check. The killed-connection test reddens.
- Bump `revision` on every rescan. The unchanged-rescan test reddens.
- Let the catalog write `epg_data` on an auto-created channel. The sync-collision test reddens.

**PR description draft:**

> Groups classified streams across providers into region- and variant-scoped content identities: admin
> decisions, exact tvg_id, exact key, and blocked, budgeted fuzzy candidates to a review queue; region
> conflicts are review-only. Binds identities to EPG by a region-aware rule with admin pins, lets the
> admin bind an identity to one channel, and computes proposals under one lock order. The resolver is
> serialised by a Postgres advisory lock with a durable request counter, so a crash loses nothing. Writes
> no channel. Spec PR S4.

### S5 — reliability

**Changes.**

- The `StreamHealth` and `RelayEventWatermark` models.
- The ingest receiver.
- `prune_relay_watermarks`.
- `health` on `classifications/`.
- The smoke check.

**Break-checks.**

- Compare `seq` without the row lock. The concurrent-duplicate test reddens.
- Count `max_retries_exceeded` as a failure. The double-count test reddens.
- Band failure-only evidence as `unknown`. The failure-only test reddens.

**PR description draft:**

> Records per-stream reliability as decayed exposures (tunes and switch-ins) and failures (failovers
> away, connection failures, buffering) at event ingest, deduplicated by a per-relay-process watermark,
> with the band computed when read so stale evidence ages on its own. No queue, no background fold,
> nothing on the tune path. Spec PR S5.

### S6 — ordering and proposal acceptance

**Changes.**

- The `0040` migration and `ChannelOrderSnapshot`.
- D8 and `reorder_channels`.
- The D10 lock on every listed writer, including the rehash merge with pin carry.
- D7's flip to `manual`.
- The auto-order preview and enable endpoints.
- Restore, which sets the channel to `manual`.
- Accept and dismiss (§ Proposals).
- The smoke check.

**Break-checks.**

- Replace key 5 with the stream id. The non-id tie test reddens.
- Remove the `manual` guard.
- Drop the serializer lock.
- Drop the pin carry.
- Let accept set `auto` unconditionally.

Each of the last four reddens its named test (§ Test strategy).

**PR description draft:**

> Orders each `auto` channel's streams best quality tier first, then by reliability band, with admin pins
> on top, so the relay's existing failover walks down in quality. Every channel starts `manual`; enabling
> goes through a preview with snapshots; a reorder on an `auto` channel flips it to `manual` visibly and a
> restore sticks. Every writer of the order, the rehash merge included, takes one per-channel lock.
> Accepting a proposal is revision-checked under the identity → proposal → channel lock order and never
> changes an existing channel's mode without the admin's say. The relay is unchanged. Spec PR S6.

### S7 — the Lineup page and the channel streams table

**Changes.** § Admin UX, except S8's and S9's items. Vitest for each component and the store.

**Break-checks.**

- Drop the flip-to-manual toast. The toast test reddens.
- Reword the access warning to say "visible to every user". The dialog test reddens.

**PR description draft:**

> Adds the Lineup page (proposals, review queue, identities with channel and EPG binding, status and
> enablement) and tier, health, pin and order-mode controls on a channel's streams. Mantine and Zustand
> only. Spec PR S7.

### S8 — per-account naming conventions

**Changes.** D16 validation in the M3U account serializer, the form section and live preview, and the `AR:`
golden line.

**Break-checks.** Leave the convention out of `convention_version`. The re-parse test reddens.

**PR description draft:**

> Lets an admin teach the classifier a provider's naming convention per account (default region,
> region-token overrides such as `AR:` meaning Arabic, strip prefixes/suffixes, region-source order),
> with a live preview. Spec PR S8.

### S9 — optional LLM assist

This is security-adjacent, so the reviewer runs on `fable` from round one.

**Changes.** `collect_secrets`, `build_request`, the final guard, the adapter, the settings fields and the `LLM`
badge.

**Break-checks.**

- Drop the URL-derived secrets from `collect_secrets`. The builder exact-output test reddens on the URL-only
  credential.
- Add a three-character minimum to secret tokens. The builder test reddens on the two-character username.
- Take the tokens from the stored classification. The stored-classification test reddens.
- Disable the final guard's token check. The final-guard test reddens.

**PR description draft:**

> Optional, off by default, inert without `MINO_CATALOG_LLM_API_KEY`: sends the streams the rules could not
> place to an LLM and shows its answers as review-queue suggestions. Only parser-derived key tokens,
> region, variant and tier leave the box; a record whose raw text looks like a URL or credential, or whose
> tokens equal any token of any known account, profile, URL-derived or EPG credential, is dropped; a
> separate final guard re-checks the serialised request. It never merges anything itself. Spec PR S9.

## Non-goals

- **No active probing** (R1).
- **No relay switch-policy change** (D9). That rules out climb-back, and rules out "same tier before lower" for
  streams earlier in the current tier. If the owner wants the second later, the smallest change is
  Django-only: `order_alternates_from_current()` would rotate within the current tier block before the lower
  blocks. It would need a parity row and an E2E pin of its own.
- **No ranking by bitrate, codec or measured fps** (Q3).
- **No channel preemption.**
- **No change to auto channel sync** or to any authorization filter.
- **No VOD or catch-up classification.**
- **No playback-time weighting in health.** Exposures are counted, not timed (D11).

## Risks

- **A wrong deterministic merge serves the wrong region's feed.** Mitigated structurally (D4, the conflict
  rule, quarantine). The residual case is a provider that labels an NZ feed `UK:` and gives it a `.uk`
  tvg_id. The remedy is a region pin.
- **Order churn.** Mitigated by D8's key 5 and by ranking on band only. S6 pins "a second pass writes nothing".
- **Stats volume.** S1b restores about one `Stream` write per running subprocess channel every 30 s, as the
  Python relay did.
- **Health ingest adds two locked row updates per relevant event** on the API process. Relevant events are tune
  and failure transitions, not bytes. That is a small fraction of the existing one `SystemEvent` insert per
  event.
- **The LLM sees less context** than a raw-name design would give it (D14).

## Open questions for the owner

- **Q1.** Should a separate issue be filed for M1, the Go relay never posting `stream_stats`, as a parity defect
  independent of this programme? S1b fixes it either way. A filed issue lets S1b carry `Closes #N`, and lets
  the metrics ledger record it.
- **Q2.** Where should `UNKNOWN` tier sort? D8 puts it between HD and SD. The alternative is last.
- **Q3.** Is bitrate a within-tier signal? Today two FHD streams at 3 and 8 Mb/s rank only by reliability.
- **Q4.** Should a high-confidence LLM suggestion ever be accepted without a click, for example at confidence
  0.95 or more with the same region and variant? D14 says never. R2's word "resolve" could be read either way.
- **Q5.** For `add_streams` into an auto-created channel, should "Detach from auto-sync" default to on? Off
  keeps today's sync behaviour, with EPG managed by sync. On keeps the merged channel when its origin provider
  drops the stream, and gives the catalog the EPG.
- **Q6.** Should D9's non-goal (tier-block rotation) be scheduled as a follow-up once S6 has run on real
  providers for a while?

## Appendix A — owner rulings (2026-10-31)

- **R1 Quality measurement: name + passive.** Parse quality hints from stream name and group
  (UHD/4K/FHD/HD/SD/HEVC/50fps/…), overridden by measured `Stream.stream_stats` captured during real
  playback. No active probing: no ffprobe, and no extra provider slot use.
- **R2 Identity matching: rules + optional LLM assist.** A deterministic core normalises the name, extracts the
  region from prefix, group and name, and matches on tvg_id and EPG data. Fuzzy matches go to an admin review
  queue, and confirmed matches are remembered. An optional, off-by-default LLM may resolve ambiguous
  leftovers. It sends provider channel lists to an external API, so it must never send URLs or credentials,
  and it must be explicitly enabled.
- **R3 Automation: auto-order, propose new.** Existing served channels have their streams auto-reordered,
  best quality first. New canonical channels are proposed for admin acceptance. Admin pins override
  everything.
- **R4 Ranking: quality tier, then reliability.** Order by quality tier, best first. Within a tier, order by
  observed health (recent failovers, buffering events and connect failures from relay events).

R1's "overridden by measured `Stream.stream_stats`" is met by `MeasuredResolution`. That table is written from
the same `stream_stats` events that feed `Stream.stream_stats`, and REST cannot forge it (§ Quality tier).

## Changelog

- 2026-10-31: first draft, at `149678aa` (head `09e4d103`).
- 2026-10-31: review round 1 (FAIL, 2 blocking, 13 should-fix, 1 nit). Every finding addressed (head
  `14534539`).
- 2026-10-31: review round 2 (FAIL, 1 blocking, 13 should-fix). **Simplified, rather than adding mechanism**:
  - **Health**: exposure seconds, the queue, the fold and playback segments are removed. Health is now decayed
    exposure and failure counts, updated at ingest and deduplicated by a per-process watermark. The band is
    computed when read. (Findings 8, 9, 10.)
  - **Classification row**: holds only the parse. The effective tier is computed when read, from a
    catalog-owned `MeasuredResolution`. EPG is no longer region evidence. Every resolve run recomputes the
    derived state. (Findings 3, 5, 7.)
  - **Resolver**: uses a Postgres advisory lock and a durable request counter instead of the Redis task lock.
    (Finding 11.)
  - **LLM**: sends parser tokens only, matched by equality against secrets collected from every credential
    source, with no minimum length. (Finding 1.) The builder and the guard are tested separately. (Finding 14.)
  - **S1**: split into S1a (an immutable per-attempt context, attribution and event identity) and S1b (stats).
    (Finding 2.)
  - **Proposals**: one lock order, withdrawals, and revisions bumped only on a real change. (Finding 12.)
  - **EPG**: a complete selection table with pins; no EPG write on auto-created channels. (Findings 5, 6.)
  - **Parser**: the `UK HD` case is reconciled, idempotence is scoped to the key, and an overflow hash is
    added. (Finding 4.)
  - **PRs**: the dependency table is corrected, with a smoke check per stopping point. (Finding 13.)
