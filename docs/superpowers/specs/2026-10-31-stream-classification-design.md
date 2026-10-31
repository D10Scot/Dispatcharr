# Stream Classification and Quality-Ordered Failover

**Date:** 2026-10-31
**Status:** Draft (review rounds 1-3 addressed; see § Changelog)
**Rulings:** the owner's rulings R1-R5 and R7 of 2026-10-31 override any default here. Appendix A restates
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
   review queue. Confirmed decisions are remembered, so a re-scan is stable. R2's optional LLM assist is
   **deferred to its own spec** (ruling R5; § LLM assist).
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
| **D2** | **Classification lives in side tables, never on `Stream`.** `StreamClassification` is one-to-one with `Stream` (primary key = `stream_id`, `on_delete=CASCADE`). It stores only what the **parser** derives from the stream's own text. Everything that depends on other inputs (decisions, measurements, health, EPG) is applied when it is read or resolved, never stored on this row. | The refresh writes `Stream` in bulk with a fixed field list (`_bulk_update_stream_refresh_batches`, `apps/m3u/tasks.py:1080-1089`). Widening it would put classification on the ingest path. Keeping the row a pure function of the stream's text is what makes D6's invalidation one fingerprint. |
| **D3** | **A purpose-built, versioned parser, `apps/catalog/parse.py`**: pure functions, no ORM, no settings reads inside. Input `(name, group_title, tvg_id, convention)`. Output a frozen dataclass `Parsed(canonical_name, canonical_key, region, region_evidence, region_conflict, name_tier, tier_conflict, codec_hint, fps_hint, markers, variant, variant_conflict)`. `PARSER_VERSION` is an integer bumped on any behaviour change. The algorithm is phased (§ Parsing). | The existing `normalize_name` reads settings and drops the tokens this spec classifies. A pure parser can be golden-tested, property-tested and benchmarked without a database. |
| **D4** | **Region and variant are part of every identity, never a tiebreak.** `variant` holds feed-distinguishing markers that are not quality: `+1` / `+2` (timeshift feeds) and `east` / `west`. No automatic path ever joins two streams whose regions or variants differ. A stream is never placed automatically, only by an admin decision, if it has any of: an unknown region (`""`), an unresolved region conflict, a variant conflict, or an empty key. | This is the UK/NZ trap, structurally. "Sky Arts" GB and "Sky Arts" NZ differ by region, so they are different identities by construction, not by a threshold. |
| **D5** | **Decisions are keyed by a stable stream key and are single-valued per key.** The key is `xc:<account_id>:<stream_id>` when the provider gives an id, else `m3u:<account_id>:<sha1(name, group title, tvg_id)>`. `StreamAssignment` holds at most **one** row per key: either *assign to identity X* or *exclude*. `StreamRegionPin` holds at most **one** row per key. `PairRejection` holds one row per *(key, identity)*. Replacing a decision is an upsert in one transaction, and revoking it is a delete. Every change **requests a resolve run**, and the resolver applies decisions on every run. **A region pin ends that stream's region conflict.** | `stream_hash` changes when a hashed field changes, and the rehash task merges rows (`core/tasks.py:719`). A key derived from the provider's own id survives both. Single-valued tables make contradictory decisions unrepresentable. |
| **D6** | **Invalidation is "parse when the text changes, derive everything else on every run".** The only cached computation is the parse: `fingerprint = sha1(PARSER_VERSION, convention_version(account), name, group title, tvg_id)`. Classification is idempotent and needs no provider download: it reads `Stream` rows and skips unchanged fingerprints. It runs (a) after each provider refresh, (b) when an account's naming convention is saved, (c) on the admin **Re-run**, and (d) on a **daily backstop** over every active account. Identities, conflicts, EPG binding and proposals are recomputed by every resolve run. The effective tier and the health band are computed when they are **read**. | Removing the cached derived state removes the class of missed invalidations rounds 1 and 2 found. Round 3 found that a fingerprint is checked only when classification runs. (b)-(d) make sure it runs without depending on the next provider refresh, and a failed run is simply retried by the next trigger. |
| **D7** | **Ordering control is two new columns on existing tables**: `Channel.stream_order_mode` (`auto` / `manual`, default `manual`) and `ChannelStream.pinned` (bool, default false). Under `auto`, pinned streams keep their relative admin order at the top, and every other stream is placed by D8. Under `manual`, nothing in this spec writes the channel's order. **An admin reorder of an `auto` channel switches it to `manual`.** A reorder is a request that changes the relative order of the streams kept on the channel. A **membership-only** edit (adding or removing streams, with the retained streams' relative order unchanged) keeps the mode. The response says when the mode flipped, and the UI shows the badge and a one-click "back to Auto". **Restoring a snapshot sets the channel to `manual`** under the same lock. | R3 says admin pins override everything. "Never destroy an admin's manual ordering silently" is met three ways. Every existing channel starts `manual`. A later drag is never overwritten, because it flips the channel visibly. A restore sticks. |
| **D8** | **The ordering function, `rank_members(channel)`**, is shared by the reorder pass and by acceptance (§ Proposals). The sort key for unpinned streams is: (1) **effective tier**, best first: `UHD > FHD > HD > UNKNOWN > SD`; (2) **health band**: `good > fair > unknown > poor` (§ Reliability); (3) `backup` marker last; (4) `fps_hint` descending; (5) the stream's current `order` value, then its current position. Inactive accounts and stale streams sort last. | R4: tier, then reliability. `UNKNOWN` sits above `SD` and below `HD` because an unlabelled provider stream is more often 720p or 1080p than 576i (confirmed by R7). Key 5 is explicit rather than left to the stability of the sort. |
| **D9** | **The relay's switch policy does not change.** The failover keeps "the next candidate after the current one, wrapping" (`order_alternates_from_current`). On a tier-sorted list that already walks down in quality, and it wraps back up to the top tier only once the lower ones are exhausted. **No climb-back** (returning to a higher tier while a lower one still plays) and **no same-tier-before-lower preference** for the streams *before* the current one in its own tier. Both are non-goals (§ Non-goals). | A switch-policy change is a live-path behaviour change. It needs a parity-matrix row and a pinned E2E, and the owner did not ask for one. The headline behaviour, best first and down in quality on failure, follows from the order alone. |
| **D10** | **One lock order for everything that writes channel membership or order: member `Stream` rows first (`FOR KEY SHARE`, in id order), then catalog rows (identity, then proposal), then the `Channel` row (`FOR UPDATE`), then that channel's `ChannelStream` rows.** The writers that take the Channel lock are: the reorder pass, the serializer update (`apps/channels/serializers.py:700-729`), the bulk edit (`api_views.py:1460-1489`), acceptance, and snapshot restore. Each writer that inserts a `ChannelStream` row first key-share-locks the referenced streams. **The rehash merge takes no Channel lock.** It already holds `FOR UPDATE` on its batch of `Stream` rows (`core/tasks.py:561-568`, `skip_locked=True`, batches of 1,000), and updates the `ChannelStream` rows it moves in place, so it already follows the Stream-first order. Its one change is that a collision keeps `pinned = source.pinned or target.pinned` on the surviving row (`core/tasks.py:726-736`). | Round 3 found that putting a Channel lock inside rehash's Stream-locked batch inverts the order acceptance uses, and holds Channel locks for a whole batch. With Stream rows first everywhere, no writer waits on a Stream while holding a Channel or `ChannelStream` row that rehash needs. Rehash skips streams a writer has key-share-locked (`skip_locked`), and they are picked up on its next run. An order rehash leaves out of rank is corrected by the next reorder pass. |
| **D11** | **Reliability is counted per exposure, at ingest, deduplicated per event.** An **exposure** is a stream being started (`channel_start`) or switched in (`stream_switch`). A **failure** is a failover away from it or a connection failure on it, plus a quarter-weight for each buffering episode. A receiver on the `relay_event_applied` signal handles each relevant event in its own transaction. It first inserts a `RelayEventReceipt(relay_boot, seq)`, which is unique. **Only if the insert succeeds** does it decay and update the stream's two counters. Receipts are kept for 30 days. The band is computed when it is read. | Round 3 showed a high-water mark is unsafe: a batch whose HTTP attempts timed out can still be applied by Django **after** a later batch, so a watermark would discard it. A unique receipt per event is order-free. Exposure counting needs no playback segments, and R4 asks only for "observed health (recent failovers, buffering events, connect failures)". |
| **D12** | **Everything is off until the owner turns it on, in two switches**, in a new settings group `catalog_settings`: `classify_enabled` (parse, tier, identities, review queue; it never writes a channel) and `auto_order_enabled` (D8 writes for `auto` channels). Turning `classify_enabled` on **backfills**: it dispatches classification for every active account, then one resolve. Turning `auto_order_enabled` on goes through a **preview** endpoint. The preview lists every channel whose order would change, and the owner picks which channels to set to `auto`. Before the first write, each chosen channel's prior order is saved in `ChannelOrderSnapshot`. | R3 asks for automatic reordering of existing channels. The no-silent-destruction rule asks for it to be visible and reversible. |
| **D13** | **New channels and new members are proposals, never automatic, and the target channel is always explicit.** A `ChannelProposal` has `kind` `new_channel` (the identity has no bound channel) or `add_streams` (the identity has a bound channel that lacks some of its members). Several existing channels can belong to one identity: these **candidate channels** are computed and shown, never stored. **Binding the identity to one channel is an explicit admin act**, and changes no channel. Accepting `add_streams` **keeps the target's `stream_order_mode`**, unless the admin ticks "order this channel automatically". A channel created from `new_channel` starts `auto`, and is ranked by D8 **before acceptance commits**. Adult content is propagated conservatively (§ Proposals). | R3: propose new, admin accepts. Adding a stream to a channel changes what clients may receive, so it needs acceptance. Choosing among several candidates is a judgement about which channel the admin's clients use, and the spec must not make it. |
| **D14** | **R2's optional LLM assist is deferred to its own spec** (ruling R5). This spec builds no part of it: no settings, no env var, no payload, no PR. The resolver passes leave a plain list of unplaced streams and open fuzzy matches. A later spec can read that list without changes here. | Rounds 2 and 3 each found a credential path through a sanitiser. The owner ruled that the LLM gets its own design and review, after this lands. |
| **D15** | **The Go relay changes in two small PRs (S1a, S1b), and only to report.** Both attribute what they report to the **source an attempt actually runs**, captured once when that attempt starts. S1a adds `relay_boot` and `seq` to every event. It adds `from_stream_id` and `trigger` to `stream_switch`, and the attributed `stream_id` to `channel_buffering`, `channel_error` (`connection_failed`) and `channel_stop`. S1b posts `stream_stats` again, from storage owned by the attempt. **When a pending source is adopted does not change** (§ S1a). Nothing the relay decides changes, and the status endpoint's `stats` view is unchanged. | M1 and M2. A pending switch (an operator `Advance` parked during retry backoff) is still adopted only after the running attempt returns (`relay/channel/channel.go:555-566`). Until then the running source is the one producing lines. Attributing to the source being run is therefore exactly right, and needs no change to adoption. |
| **D16** | **Naming-convention overrides live per account** in `M3UAccount.custom_properties["catalog"]`, a validated sub-dict: `default_region`, `region_tokens` (token → ISO code, or `null` to treat it as noise, e.g. `{"AR": null}`, where the provider's `AR:` means Arabic, not Argentina), `strip_prefixes` / `strip_suffixes` (literal strings), and `region_from` (an ordered subset of `["tvg_id", "name", "group", "default"]`). `convention_version` is a hash of that sub-dict. Saving it dispatches classification for that account (D6). | Conventions are per provider, so the owner fixes them where the provider is configured. The sub-dict needs no migration, and is validated by a serializer, so a typo is a 400, not a silent no-op. |

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
- **`MeasuredResolution`**, one-to-one with `Stream` (CASCADE): `height`, `width` (null), and `observed_at`
  (indexed). It is written **only** by the catalog's receiver for a `stream_stats` event with `relay: "go"` that
  carries a resolution. No REST serializer exposes it as writable.
- The **`relay_event_applied`** signal in `core/relay_events.py`. It is sent after each event, including
  `stream_stats`, and carries the validated event dict. Receiver exceptions are caught and logged, so a batch
  never 500s.

**S4**

- **`ContentIdentity`**: `anchor` (char(600); see § Identity resolution), `region`, `variant`,
  `unique(anchor, region, variant)`; `display_name`; `tvg_id` (null); `epg_data` (FK `epg.EPGData`, null,
  SET_NULL); `epg_state` (`bound` / `none` / `ambiguous` / `pinned`); `channel` (FK
  `dispatcharr_channels.Channel`, null, SET_NULL; set **only** by an admin, D13); `created_at`.
- **`IdentityMember`**: `stream` (OneToOne, CASCADE), `identity` (FK, CASCADE), `how` (`decided` / `auto_tvg` /
  `auto_key`). Each resolve run rewrites it. A stream with no row is unplaced, and the API gives the reason:
  `conflict`, `unknown_region`, `empty_key`, `excluded`, `ambiguous_key`, `fuzzy_pending` or `review`.
- **`IdentityMatch`**, the review queue: `stream` (FK), `identity` (FK, null), `source` (`fuzzy` /
  `region_conflict` / `unknown_region` / `same_key`), `score` (0-100), `suggested_region`, `state` (`open` /
  `accepted` / `rejected`), `created_at`; `unique(stream, identity, source)`.
- **`StreamAssignment`** (`stream_key` **unique**, `account`, `kind` `assign`/`exclude`, and `identity`, which
  a check constraint requires when `kind = assign`), **`StreamRegionPin`** (`stream_key` **unique**, `account`,
  `region`) and **`PairRejection`** (`unique(stream_key, identity)`). Each records `decided_by` and
  `decided_at`. **Their identity FKs are `PROTECT`** (see the deletion rule in § Identity resolution).
- **`IdentityEpgPin`**: `identity` (OneToOne, PROTECT from the identity side), `epg_data` (FK, CASCADE; null
  means "no EPG"), `decided_by`, `decided_at`.
- **`ChannelProposal`**: `identity` (FK), `kind`, `channel` (FK, null), `stream_ids` (JSON list),
  `members_hash`, `revision`, `state` (`open` / `accepted` / `dismissed` / `withdrawn`), `created_at`,
  `decided_at`, `decided_by`. A partial unique index allows at most one `open` row per `(identity, kind)`.
- **`CatalogResolveState`**, a single row: `requested` (bigint), `completed` (bigint), `fuzzy_cursor` (int),
  `last_run_at`.

**S5**

- **`StreamHealth`**, one-to-one with `Stream` (CASCADE): `exposures` and `failures` (floats, decayed),
  `decayed_at`, and lifetime counters for display (`starts`, `failovers_away`, `connect_failures`,
  `buffering_episodes`).
- **`RelayEventReceipt`**: `relay_boot` (char(16)), `seq` (bigint), `received_at` (indexed),
  `unique(relay_boot, seq)`. It is written only for health-relevant events, so a handful of rows per tune. Rows
  older than 30 days are pruned daily. That is far longer than any retry: the relay makes at most two attempts per
  batch (`relay/control/nextsource.go:429-448`).

**S6**

- `Channel.stream_order_mode` (char(8), default `"manual"`) and `ChannelStream.pinned` (bool, default `False`), in
  `apps/channels/migrations/0040_*`. The tip at the base is `0039_channel_hls_output_profile.py`, and the plan
  re-checks the number at its seed. Both columns have defaults, so the migration needs no data pass.
- **`ChannelOrderSnapshot`**: `channel` (FK, CASCADE), `stream_ids`, `pinned_ids`, `reason` (`enable_auto` /
  `accept_proposal`), `created_at`. The last five per channel are kept.

## Parsing (S2)

The parser runs in fixed **phases**.

1. **Normalise.** Apply NFKC and casefold. Replace `&` with ` and `. Remove the account's `strip_prefixes` /
   `strip_suffixes` (literal and case-folded, at most one of each). Nothing is truncated here.
2. **Tokenise.** Split on whitespace and the separators `| [ ] ( ) : - _ / ·`. Keep `+1` / `+2` as single
   tokens. Record for each token whether it was **delimited**: bracketed (`[US]`, `(UK)`, `|NZ|`), or, as the
   first token, followed by `:` / `-` / `|` (`UK:`, `NZ -`).
3. **Classify decorations.** Each token is checked against these classes, and a decoration is removed from the
   word list:

   | Class | Tokens (case-folded) | Effect |
   |---|---|---|
   | tier | `8k`, `4k`, `uhd`, `2160p` → UHD; `fhd`, `fullhd`, `1080p`, `1080i` (and the two-token `full hd`) → FHD; `hd`, `720p` → HD; `sd`, `576p`, `576i`, `480p`, `lq` → SD | `name_tier` is the **highest** present; `tier_conflict` when two different tiers occur |
   | codec | `hevc`, `h265`, `x265` → hevc; `h264`, `avc` → h264 | hint only |
   | fps | `\d{2,3}fps`, `50p`, `60p` | `fps_hint` is the highest present |
   | marker | `backup`, `bk`, `raw`, `alt`, `test` | kept in `markers` (sorted, de-duplicated) |
   | variant | `+1`, `+2`, `east`, `west` | kept in `variant`; two different ones set `variant_conflict` |

4. **Extract the region from the name.** This works on the tokens left after phase 3. **Protected phrases** in
   `regions.py` (`uk gold`, `uktv`, and any others the plan finds in the corpus) are kept as words. A
   region-table token is consumed as region evidence when it is delimited (anywhere), or when it is first or last
   **and at least one other word remains**. A lone remaining region token is kept as a word. At most one region
   token is consumed. Two different qualifying region tokens set `region_conflict`.
5. **Group fallback.** If the name gave no tier, tier tokens in the group title are used. Group region evidence
   is § Region's source 3.
6. **Key.** Map the standalone tokens `one` … `ten` to `1` … `10`. Drop pure-punctuation tokens, then join the
   remaining words with single spaces. Nothing else is aliased: no stemming, and `sport` ≠ `sports`.
   - **Empty key**: if no word remains (`HD`), `canonical_key = ""` (D4).
   - **Overflow**: if the key exceeds 512 characters, it becomes its first 495 characters, then `~`, then the
     first 16 hex digits of the full key's SHA-1. `canonical_name` uses the same rule.

**Stability properties, stated exactly.** These hold for the canonical key only:

- `parse(canonical_name).canonical_key == canonical_key`.
- Inserting or removing a decoration after phase 2 never changes `(canonical_key, region, variant)`.
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

With `region_tokens: {"AR": null}`, `AR: MBC 1` becomes `mbc 1` with no region. The S8 golden test pins it.

## Region

**The region table** maps tokens to ISO 3166-1 alpha-2 codes: two-letter codes, a curated alias set (`uk` → GB,
`usa` → US, `aus` → AU, …), and English country names. Tokens that are also language codes or are ambiguous are
**absent** from the default table, and count only through an account's `region_tokens`. These are `ar`, `en`,
`lat` / `latino`, `int`, `es` and `pt`.

**Parsed evidence, strongest first.** The account's `region_from` may reorder or drop any of these sources:

1. `tvg_id`: the final dot-segment of `tvg_id` is a region-table token.
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
- **Measured tier**: read from `MeasuredResolution` (written only from the relay's stats events), by **height**:
  ≥ 2000 → UHD, ≥ 1000 → FHD (1080i counts), ≥ 700 → HD, otherwise SD.
- **Effective tier**: computed when it is read. It is the measured tier if `observed_at` is within
  `measured_ttl_days` (default 30), otherwise the name tier. The API reports which one it used.

A REST write to `Stream.stream_stats` cannot touch `MeasuredResolution`. A change to the TTL, or an expired
measurement, takes effect the next time the tier is read. New measurements reach a channel's order at the next
reorder pass. `video_bitrate` and `source_fps` are displayed but not used to rank (R7; a bitrate tiebreak is a possible later
follow-up, not in scope).

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
4. **After unlocking**, if `requested > completed`, dispatches itself again.

A pass that lost its session fails its final transaction, so `completed` does not advance. Every pass recomputes
from current inputs, so a partial pass leaves nothing a later pass cannot overwrite. A crash leaves
`requested > completed`, and the next trigger or the backstop finishes the work.

**Identity anchors.** Membership is a pure function of the current classifications and decisions, so a reversed
or incremental build gives the same result as a clean rebuild. An identity's natural key is
`(anchor, region, variant)`:

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
   tvg_id under a different region or variant is a separate identity, and both sides get an
   `IdentityMatch(source=region_conflict)`.
3. **Key anchors.** A stream without a tvg_id joins the single `tvg:` identity holding its key, if there is
   exactly one. If there are several, it stays unplaced (`ambiguous_key`), with an `IdentityMatch(source=same_key)`
   against each. Otherwise it joins `(key:<k>, region, variant)` (`auto_key`) **only if pass 4 has checked it**
   (below).
4. **Fuzzy, blocked and budgeted.** This pass only produces suggestions. Every stream that pass 3 would place
   under a **new** `key:` identity (that is, its key matches no existing identity) is first compared within its
   block: identities with the same region, variant and first key token. The scorer is `rapidfuzz`
   `token_sort_ratio` at `fuzzy_threshold` (default 90).
   - **Checked, with no candidate**: the stream is placed under its new `key:` identity.
   - **Checked, with candidates**: the stream stays unplaced (`review`), and each candidate becomes an
     `IdentityMatch(source=fuzzy)`.
   - **Not checked**, because the budget (`fuzzy_max_comparisons`, default 5,000,000) ran out: the stream stays
     unplaced (`fuzzy_pending`). The cursor is saved and `requested` is incremented, so a later pass resumes.

   **Fuzzy never binds, and only a checked stream may create an identity.** Two streams with the same key in
   one run share the check, because the first one checked creates the identity the second then joins. A block
   over 2,000 identities is split by the second key token. One still over that is skipped, and its stream stays
   `review`.
5. **Same key across tvg identities.** When two `tvg:` identities in the same region and variant share a member
   key, each of their streams gets an `IdentityMatch(source=same_key)` against the other identity. This is a
   suggestion, never a merge.
6. **Unknown region.** An `IdentityMatch(source=unknown_region)` against the same-key identity in each region.
7. **EPG binding** for every identity.
8. **Proposals** (§ Proposals).

`PairRejection` suppresses its match in every pass.

**Deletion.** An identity left with no members is deleted only if nothing references it: no assignment,
rejection, EPG pin or bound channel. The decision FKs are `PROTECT`, which enforces this. A referenced empty
identity is kept and shown as empty. Its anchor is stable, so when the stream comes back (same stream key, same
tvg_id or key) it rejoins the same row, and the decision still applies.

S4 measures one pass over a synthetic three-account, 300k-stream corpus and records the result.

## Proposals (S4 computes, S6 accepts)

**Lock order** (D10): member `Stream` rows (`FOR KEY SHARE`, id order), then `ContentIdentity`, then
`ChannelProposal`, then `Channel`, then its `ChannelStream` rows. Every one of these operations follows it:

- bind and unbind;
- the resolver's proposal step;
- accept;
- dismiss.

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

1. Take the locks in D10's order.
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
dialog says so. "Detach from auto-sync" is **ticked by default** (R7). The admin can untick it. If it stays ticked, the channel becomes
catalog-managed and gets the identity's EPG in the same transaction.

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
| `classify_account_streams(account_id)` | S3 | `.delay()` from the refresh tail after `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:3942`), in its own `try` that only logs and never sets the account status; the D12 backfill; Re-run; a daily backstop over every active account. S8 adds the convention-save trigger. | advisory lock on `(catalog_classify, account_id)` |
| `resolve_identities()` | S4 | the requesters in § Identity resolution. S4 adds the request at the end of classification and of the EPG refresh. | advisory lock |
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
    - for an auto-created target, the detach option (ticked by default, R7) and its EPG note.

    The tab also has **Dismiss** and **bulk accept** (each proposal is accepted on its own).
  - *Review*: open `IdentityMatch` rows, grouped by stream, each with a source badge. Actions: Assign, Reject
    pair, Pin region, Exclude, New identity.
  - *Identities*: searchable. Shows the members in D8 order, with tier, tier source, health band and provider,
    the candidate channels with **Bind**, and an EPG chooser that writes an `IdentityEpgPin`.
  - *Status*: run times, counts per state (including `fuzzy_pending`), **Re-run**, and the enablement switches
    with D12's preview.
- **Channel streams table** (`frontend/src/components/tables/ChannelTableStreams.jsx`):
  - a tier badge, marked "measured" or "from name";
  - a health-band dot;
  - a pin toggle;
  - "Order: Auto / Manual";
  - "Restore previous order", which sets Manual.

  After a drag on an `auto` channel, a toast says the channel is now Manual.
- **EPG source form** (`frontend/src/components/forms/EPG.jsx`): an optional Region select.
- **Settings** (`frontend/src/pages/Settings.jsx`): "Stream classification", for `catalog_settings`.
- S8 adds the M3U account form's "Naming convention" section.

**Access warning in the accept dialog.** When no Channel Profile is picked, the dialog says: *"With no Channel
Profiles, this channel is visible only to admins and to users who have no Channel Profiles. Users assigned to
profiles will not see it until you add it to one of theirs."* This matches `user_can_access_channel`
(`apps/proxy/authorize.py:202-223`). No authorization filter changes.

**API** (`apps/catalog/api_urls.py`, at `/api/catalog/`). Every endpoint has a DRF serializer, appears in the
drf-spectacular schema, and is `IsAdmin` with no opt-down.

- **S3**: `classifications/` (with the effective tier and its source), `parse-preview/`, and `run/` (classify
  every account, then resolve once S4 exists).
- **S4**:
  - `identities/`, with the `bind`, `unbind` and `epg-pin` actions;
  - `matches/`, with `assign` and `reject`;
  - `assignments/`, `region-pins/` and `rejections/`;
  - `proposals/`, read-only.
- **S5**: `health` on `classifications/`.
- **S6**: `proposals/{id}/accept|dismiss`, `auto-order/preview|enable`, and `channels/{id}/order-snapshots/`
  with `restore`. The channel serializer gains `stream_order_mode` and `pinned`.

## Coexistence

- **Manual assignment.** It is untouched on `manual` channels (D7). On `auto` channels, a reorder flips the
  channel to `manual`, and a membership-only edit keeps the mode.
- **Auto channel sync.**
  - Sync's channels appear as candidates, and the admin binds one or none.
  - Sync never sees `stream_order_mode` or `pinned`.
  - The catalog never writes `epg_data` on an auto-created channel.
- **Stream rehash and merge.** D10: rehash keeps its Stream-first locking and carries pins on the rows it
  already writes. Decisions survive because they are keyed per D5.
- **Stale and deleted streams.** Stale streams sort last (D8). Deleted streams cascade out of every
  stream-keyed catalog table. Identities follow the deletion rule.

## Known-defect interactions

- **Provider-slot counters (#513).** Untouched. No `INCR` or `DECR` is added.
- **The copied channel-authorization filter.** Untouched. No client-facing surface is added. Adult status is
  propagated (§ Proposals), so `authorize_stream`'s `hide_adult_content` check
  (`apps/proxy/authorize.py:471-474`) sees the right flag on catalog-created channels.
- **Unfenced leases** (CLAUDE.md § Known defects). Catalog work uses Postgres advisory locks, not the Redis task
  lock.
- **The boot trap.** No module that `apps/channels/models.py` imports gains an import (D1).
- **CoreSettings blast radius.** `catalog_settings` is a ninth instance-wide group. S3 ships a data migration
  seeding its row. Any E2E test that writes it joins the allowlist (`docs/adr/0003`).
- **Credential logging.** The parse-preview endpoint logs no URL and no payload.
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
- **the trap set**: at least 20 brands present in two regions, five decorations each.

Nothing in the corpus is a real URL or credential, and a test asserts no line contains `://`.

**Property tests** (S2, using the shared `dispatcharr-ci` profile, registered byte-identically):

- the three stability properties;
- an edge or delimited region token yields its region code and is absent from the key;
- for every trap brand, under any decorations, the GB name yields GB and the NZ name yields NZ.

**Resolution tests** (S4):

- **Determinism.** Each of these produces the same identities, members and display fields as a clean rebuild:
  - a reversed input order;
  - an incremental build (accounts classified and resolved one at a time);
  - a build where the streams arrive in a random order over three runs.

  Bindings and decisions made between runs survive.
- **The UK/NZ trap.** A UK and an NZ stream with an equal key and an equal tvg_id produce two identities and
  conflict rows.
- **Variants.** A tvg_id shared by a feed and its `+1` produces two identities.
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
  - **A near-match deferred by the budget stays `fuzzy_pending`**, and creates no identity, until a later pass
    checks it.
  - A checked stream with no candidate creates its identity.
- **Locks** (Postgres-only, two connections):
  - a second resolver returns;
  - terminating the holder's connection mid-pass leaves `completed` unchanged;
  - a request made during the final pass, or after unlock but before the post-unlock check, produces exactly one
    further pass;
  - the fuzzy cursor resumes.
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
- **Rehash.**
  - A pin only on the source row, or only on the target row, survives.
  - **Rehash against acceptance, concurrently on a shared stream**: both complete with no deadlock (the test
    fails on `DeadlockDetected`). The streams rehash skipped are merged on its next run.
- **Accept.**
  - A stale revision is refused.
  - A deleted member is dropped.
  - A second accept is refused.
  - A `manual` target keeps its mode.
- **First tune after acceptance.** Members are presented worst tier first. `get_stream()` immediately after the
  accept commits returns the best-tier stream.
- **Adult content.** A new channel with one adult member is adult. Through `authorize_stream`
  (`apps/proxy/authorize.py:479`), a user with `hide_adult_content` is refused it and a user without that
  setting is allowed. Adding an adult member to a non-adult channel without `options.adult` returns 400. With
  `skip_adult_members`, the channel stays non-adult and the adult member is not added.
- **Failover order.** `get_stream()` and the failover branch choose the tier-sorted first stream.

**Tune-path ledger:** `apps/proxy/tests/test_tune_path_query_ledger.py` passes unchanged in every PR.

**Quality tests** (S3):

- A REST write of `stream_stats` after a valid Go measurement leaves `MeasuredResolution` and the effective tier
  unchanged.
- A measurement older than the TTL yields the name tier, and raising the TTL brings it back at the next read.
- A `stream_stats` event without `relay: "go"` writes nothing.
- A daily backstop on an unchanged account writes nothing.

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
| S1a | none | events carry identity and attribution |
| S1b | S1a | `stream_stats` posted again |
| S2 | none | parser, inert |
| S3 | S2 | tiers visible, read-only (name-only until S1b's data arrives) |
| S4 | S3 | identities, review queue, decisions, binding, read-only proposals; **writes no channel** |
| S5 | S3 (settings, signal), S1a (data) | health visible on `classifications/` |
| S6 | S4, S5 | ordering and acceptance, the headline behaviour (API-driven) |
| S7 | S6 | the full UI |
| S8 | S3 (backend), S7 (UI section) | naming conventions |

Each stopping point passes its smoke check (§ Test strategy).

### S0 — this spec

Docs only. It cites a tracking issue with `Refs`, if one is filed.

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

**PR description draft:**

> Adds `apps/catalog` with a pure, versioned stream-name parser: canonical key, region and its evidence,
> tier/codec/fps hints, markers and feed variant, in fixed phases, with bounded output. Nothing runs yet. A
> 400-line real-shaped corpus with a two-region brand trap set is golden-tested; Hypothesis pins key
> stability, decoration independence and region extraction. Spec PR S2.

### S3 — classification, measured resolution and tiers

**Changes.**

- `StreamClassification` and `MeasuredResolution`.
- The `relay_event_applied` signal and the `stream_stats` receiver.
- `classify_account_streams`, with its triggers: the refresh tail, the backfill, Re-run and the daily backstop.
- The `catalog_settings` getter, and a seeding migration.
- `classifications/`, `parse-preview/` and `run/`.
- The smoke check.
- A measurement of the 100k first run.

**Break-checks.**

- Read the measured tier from `Stream.stream_stats`. The REST-write test reddens.
- Store the effective tier. The TTL-raise test reddens.
- Make the backstop write every row. The unchanged-account test reddens.

**PR description draft:**

> Classifies every live stream behind the off-by-default `classify_enabled` setting: a parse row per
> stream, rebuilt only when its text changes, run after each provider refresh, on enablement, on demand and
> by a daily backstop that needs no provider download; plus a catalog-owned measured resolution written
> only from the relay's stats events. The effective tier is computed when read. Writes no channel. Spec PR S3.

### S4 — identities, review queue, decisions, EPG binding and proposals

**Changes.**

- The S4 models.
- `resolve_identities`, with its advisory lock, durable counter, anchors and checked-only identity creation.
- EPG binding and pins.
- Proposal computation.
- The endpoints.
- The requests from classification and from the EPG refresh.
- The smoke check.
- A measurement of the 300k pass.

**Break-checks.**

- Let a budget-deferred stream create an identity. The `fuzzy_pending` test reddens.
- Use the first-seen name as `display_name`. The reversed-order determinism test reddens.
- Make the decision FKs `CASCADE`. The disappear-and-return test reddens.
- Advance `completed` without the ownership check. The killed-connection test reddens.

**PR description draft:**

> Groups classified streams across providers into region- and variant-scoped content identities anchored on
> tvg_id or, without one, on the canonical key, so membership is a pure function of current inputs and
> identities survive incremental builds. Admin decisions, blocked and budgeted fuzzy suggestions (only a
> checked stream may found an identity), review-only conflicts, region-aware EPG binding with pins, explicit
> channel binding, and proposals under one lock order. The resolver is serialised by a Postgres advisory lock
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
- D10's lock order on every listed writer, and the pin carry in the rehash merge.
- D7's flip to `manual`.
- The auto-order preview and enable endpoints.
- Restore.
- Accept and dismiss, with adult propagation and pre-commit ranking.
- The smoke check.

**Break-checks.**

- Replace key 5 with the stream id. The non-id tie test reddens.
- Take a Channel lock inside the rehash batch. The rehash-versus-accept test reddens with `DeadlockDetected`.
- Skip the pre-commit ranking. The first-tune test reddens.
- Create the channel non-adult. The `authorize_stream` adult test reddens.
- Let accept set `auto` unconditionally. The manual-target test reddens.

**PR description draft:**

> Orders each `auto` channel's streams best quality tier first, then by reliability band, with admin pins on
> top, so the relay's existing failover walks down in quality. Every channel starts `manual`; enabling goes
> through a preview with snapshots; a reorder flips an `auto` channel to `manual` visibly and a restore
> sticks. All membership and order writers follow one Stream-first lock order. Accepting a proposal is
> revision-checked, ranks an Auto channel before it commits, propagates adult status and asks before adding
> adult streams to a non-adult channel. The relay is unchanged. Spec PR S6.

### S7 — the Lineup page and the channel streams table

**Changes.** § Admin UX, except S8's section. Vitest for each component and the store.

**Break-checks.**

- Drop the flip-to-manual toast. The toast test reddens.
- Reword the access warning to say "visible to every user". The dialog test reddens.

**PR description draft:**

> Adds the Lineup page (proposals, review queue, identities with channel and EPG binding, status and
> enablement) and tier, health, pin and order-mode controls on a channel's streams. Mantine and Zustand
> only. Spec PR S7.

### S8 — per-account naming conventions

**Changes.**

- D16 validation in the M3U account serializer.
- Classification dispatched when the convention is saved.
- The form section and the live preview.
- The `AR:` golden case.

**Break-checks.**

- Leave the convention out of `convention_version`. The re-parse test reddens.
- Drop the save dispatch. The "an edit reclassifies without a refresh" test reddens.

**PR description draft:**

> Lets an admin teach the classifier a provider's naming convention per account (default region,
> region-token overrides such as `AR:` meaning Arabic, strip prefixes/suffixes, region-source order), with a
> live preview; saving it reclassifies that account at once. Spec PR S8.

## Non-goals

- **No active probing** (R1).
- **No LLM assist in this spec** (R5; § LLM assist).
- **No relay switch-policy change** (D9). That rules out climb-back, and also "same tier before lower" for streams
  that sit earlier in the current tier. The smallest later change would be Django-only: rotate within the
  current tier block in `order_alternates_from_current()`. It would need its own parity row and E2E pin. R7
  scheduled it as a separate follow-up, #620, which is out of scope here.
- **No ranking by bitrate, codec or measured fps** (R7). A bitrate tiebreak within a tier is a possible later
  follow-up.
- **No channel preemption.**
- **No change to auto channel sync** or to any authorization filter.
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
- **Health ingest** adds one receipt insert and one locked row update per relevant event, on the API process.

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

## Appendix A — owner rulings (2026-10-31)

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

R1's "overridden by measured `Stream.stream_stats`" is met by `MeasuredResolution`, which is written from the same
`stream_stats` events.

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
