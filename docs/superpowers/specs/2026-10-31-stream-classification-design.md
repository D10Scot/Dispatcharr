# Stream Classification and Quality-Ordered Failover

**Date:** 2026-10-31
**Status:** Draft (review round 1 findings addressed; see § Changelog)
**Rulings:** the owner's rulings R1-R4 of 2026-10-31 override any default here. Appendix A restates
them, so this document can be read without the conversation that produced them.
**Authorities:** `CLAUDE.md` (§ Video path, § State, § Known defects and traps, § Structural
constraints, § Conventions), `CONTEXT.md`, `docs/adr/0005`, `docs/adr/0006`, `docs/adr/0010`, and
`docs/relay-parity-matrix.md` for the one PR (S1) that touches the Go relay.
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
One small relay PR is needed. It changes only what the relay reports, never what it decides (§ S1).

Every stopping point in § The PRs migrates, boots and works on its own. After S3 the admin can see a
tier per stream. After S4 the admin has identities and a review queue. After S6 the headline
behaviour exists. Widening scope is the main way this fails.

## What was measured before this spec was written

| # | What | Result |
|---|---|---|
| M1 | **What writes `Stream.stream_stats` today?** Every writer in the tree was grepped. | **No automatic producer on the live playback path.** Two writers exist. (1) `core/relay_events.py:113-159` (`_apply_stream_stats`) runs when a relay posts an event of type `stream_stats` (`:203-208`). (2) The Stream REST serializer lists `stream_stats` and `stream_stats_updated_at` among its fields and does not mark them read-only (`apps/channels/serializers.py:142-149`), so an admin API client can write them by hand. The Go relay never emits a `stream_stats` event: `grep -rn '"stream_stats"' relay --include='*.go'` matches nothing outside comments and tests, and `relay/httpapi/events.go:21-29` only forwards what `relay/channel` emits. The Python relay posted it from three sites (Phase 1 spec, lines 65-69 and 1418-1420: a periodic flush, a final flush on stop, and every parsed codec line), and `relay/control/events.go:97-100` still sizes its queue for "one stats flush per thirty seconds per channel". The Go relay parses the stats (`relay/channel/stats.go:30-48`, `reportInfo` at `:59`, `reportProgress` at `:101`) and serves them from memory on `GET /proxy/relay/channels` (`relay/httpapi/channels.go:91-116`), but never posts them. R1's measured override has no automatic input until S1 lands. Whether every stored value is literally unchanged since the stage 2d-3 cutover depends on whether anything used the REST path, which this spec did not measure. |
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
- Account credentials live in `M3UAccount.username` / `password` (`apps/m3u/models.py:90-91`), its
  `server_url`, and its `custom_properties` (`:92`). Provider text in stream names and groups can still
  contain anything, including a username.
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

### Events and stats

- The relay batches events to `POST /api/relay/events` (`relay/control/events.go:40-64`, at most 200
  per batch, order preserved). The wire `Event` has no timestamp and no identity (`:31-38`). The post
  goes through the shared client, which **retries** on a transport failure, a 5xx, and a 2xx whose
  body cannot be read (`relay/control/nextsource.go:429-448`, `:486-490`). A batch Django already
  applied can therefore arrive twice. `apply_event_batch` does no deduplication
  (`core/relay_events.py:185-265`).
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
| **D2** | **Classification lives in side tables, never on `Stream`.** `StreamClassification` is one-to-one with `Stream` (primary key = `stream_id`, `on_delete=CASCADE`). | The refresh writes `Stream` in bulk with a fixed field list (`_bulk_update_stream_refresh_batches`, `apps/m3u/tasks.py:1080-1089`). Adding columns there would widen every refresh write, and a classification bug could corrupt ingest. A side table can be truncated and rebuilt from `Stream` at any time. It is derived state, except for D5's decisions. |
| **D3** | **A purpose-built, versioned parser, `apps/catalog/parse.py`**: pure functions, no ORM, no settings reads inside. Input `(name, group_title, tvg_id, convention)`. Output a frozen dataclass `Parsed(canonical_name, canonical_key, region, region_evidence, region_conflict, name_tier, tier_conflict, codec_hint, fps_hint, markers, variant)`. `PARSER_VERSION` is an integer bumped on any behaviour change. The algorithm is phased (§ Parsing), and every property in § Test strategy is stated against those phases. | The existing `normalize_name` reads settings and drops the tokens this spec classifies. A pure parser can be golden-tested, property-tested and benchmarked without a database. The version is part of the fingerprint (D6). |
| **D4** | **An identity is `(canonical_key, region, variant)`. Region and variant are part of identity on every automatic path, never a tiebreak.** `variant` holds feed-distinguishing markers that are not quality: `+1` / `+2` (timeshift feeds) and `east` / `west`. No automatic path (tvg_id, key, new-identity creation, proposal) ever joins two streams whose regions or variants differ. A stream with **unknown** region (`""`) or an unresolved region conflict is never placed in any identity automatically: only an admin decision places it. | This is the UK/NZ trap, structurally. "Sky Arts" GB and "Sky Arts" NZ have equal keys and different regions, so they are different identities by construction, not by a threshold. A provider reusing one tvg_id for a feed and its `+1` cannot merge them. |
| **D5** | **Decisions are keyed by a stable stream key and are single-valued per key.** The key is `xc:<account_id>:<stream_id>` when the provider gives an id, else `m3u:<account_id>:<sha1(name, group title, tvg_id)>`. There are three tables (§ Data model). `StreamAssignment` holds at most **one** row per key, either *assign to identity X* or *exclude*. `StreamRegionPin` holds at most **one** row per key. `PairRejection` holds one row per *(key, identity)*. Replacement is an upsert in one transaction, revocation is a delete, and every change re-classifies that key at once (D6). **A region pin ends that stream's region conflict**: the pinned region is used and `region_conflict` is false. | `stream_hash` changes when a hashed field changes, and the rehash task merges rows (`core/tasks.py:719`). A key derived from the provider's own id survives both. Single-valued tables make contradictory decisions unrepresentable rather than merely unlikely. If a plain-M3U provider renames the stream, the decision stops applying and the stream returns to the queue, which is the correct outcome. |
| **D6** | **Classification is incremental, and every input has an explicit invalidation.** `fingerprint = sha1(PARSER_VERSION, convention_version(account), name, group title, tvg_id)` covers the name inputs. The other inputs are each invalidated explicitly, with no provider fetch: a decision change re-classifies its key; an EPG-source region edit re-classifies streams whose tvg_id resolves into that source; a `catalog_settings` change re-runs resolution; a measurement arriving or expiring is handled by the measured-tier pass (§ Quality tier), which runs on its own beat, not only after an account refresh. | Parsing is cheap (M4) but upserting 100k rows on every refresh is not. Round 1 found that a fingerprint alone misses expiry, decisions, EPG edits and settings. Each now has its own trigger. |
| **D7** | **Ordering control is two new columns on existing tables**: `Channel.stream_order_mode` (`auto` / `manual`, default `manual`) and `ChannelStream.pinned` (bool, default false). Under `auto`, pinned streams keep their relative admin order at the top, and every other stream is placed by D8. Under `manual`, nothing in this spec writes the channel's order. **An admin reorder of an `auto` channel switches it to `manual`.** A reorder means a request that changes the relative order of streams kept on the channel. A **membership-only** edit (adding or removing streams, with the retained streams' relative order unchanged) keeps the mode, and the next reorder pass places the new streams. The response says when the mode flipped, and the UI shows the badge and a one-click "back to Auto". **Restoring a snapshot sets the channel to `manual`** under the same lock, so the next pass cannot undo it. | R3 says admin pins override everything. "Never destroy an admin's manual ordering silently" is met three ways. Every existing channel starts `manual`. A later drag is never overwritten, because it flips the channel visibly. A restore sticks. |
| **D8** | **The ordering function.** The sort key for unpinned streams on an `auto` channel is: (1) **effective tier**, best first: `UHD > FHD > HD > UNKNOWN > SD`; (2) **health band**, best first (§ Reliability); (3) `backup` marker last; (4) `fps_hint` descending; (5) the stream's **current** `order` value (then its current position), which keeps ties where they are. Inactive accounts and streams marked `is_stale` sort last. The order is written under D10's lock. | R4: tier, then reliability. `UNKNOWN` sits above `SD` and below `HD` because an unlabelled provider stream is more often 720p or 1080p than 576i (Q2 asks the owner to confirm). Key 5 is explicit rather than left to the stability of the sort, so a ties-only change of input order is a visible bug, not an invisible one. |
| **D9** | **The relay's switch policy does not change.** The failover keeps "the next candidate after the current one, wrapping" (`order_alternates_from_current`). On a tier-sorted list that already walks down in quality, and it wraps back up to the top tier only once the lower ones are exhausted. **No climb-back** (returning to a higher tier while a lower one still plays) and **no same-tier-before-lower preference** for the streams *before* the current one in its own tier. Both are non-goals (§ Non-goals). | A switch-policy change is a live-path behaviour change. It needs a parity-matrix row and a pinned E2E, and the owner did not ask for one. The headline behaviour, best first and down in quality on failure, follows from the order alone. |
| **D10** | **Every writer of `ChannelStream.order` or `pinned` takes one per-channel lock.** The lock is `select_for_update()` on the `Channel` row, inside a transaction, re-reading the channel's `ChannelStream` rows and `stream_order_mode` after locking. The writers are: the reorder task (writes only rows whose `order` differs); the serializer update (`apps/channels/serializers.py:700-729`); the bulk edit (`api_views.py:1460-1489`); proposal acceptance; snapshot restore; and the rehash merge (`core/tasks.py:719-740`). The merge also carries pins: on collision the surviving row keeps the lower `order` and `pinned = source.pinned or target.pinned`. | Without it the reorder task and an admin drag race last-writer-wins, a drag could be lost silently, and a rehash could drop a pin. The lock is per channel and held for milliseconds. None of these writers is on the tune path. |
| **D11** | **Reliability is recorded at event ingest and folded off-path, idempotently.** `apply_event_batch` sends a Django signal, `relay_event_applied`, defined in `core/relay_events.py`. `apps/catalog` connects a receiver in its `AppConfig.ready()` that inserts `StreamHealthEvent` rows with `ON CONFLICT DO NOTHING` on `(relay_boot, seq)`, the event identity S1 adds. A five-minute beat task folds the queue in one transaction per run, with open playback segments persisted in their own table (§ Reliability). | The tune path is untouched (the ledger test proves it). The event route already writes one `SystemEvent` per event. A signal keeps `core` from importing `catalog`. The event post can be retried after Django applied it (§ Events and stats), so ingest must be idempotent. `SystemEvent` cannot be the history (M3). |
| **D12** | **Everything is off until the owner turns it on, in three switches**, in a new settings group `catalog_settings`: `classify_enabled` (parse, tier, identities, review queue; it never writes a channel), `auto_order_enabled` (D8 writes for `auto` channels), and `llm_enabled` (D14). Turning `auto_order_enabled` on goes through a **preview** endpoint. The preview lists every channel whose order would change, and the owner picks which channels to set to `auto` (all, those with ≥ 2 streams, or a selection). Before the first write, each such channel's prior order is saved in `ChannelOrderSnapshot`. | R3 asks for automatic reordering of existing channels. The no-silent-destruction rule asks for it to be visible and reversible. One preview plus snapshot meets both without a per-channel prompt on every refresh. |
| **D13** | **New channels and new members are proposals, never automatic, and the target channel is always explicit.** A `ChannelProposal` has `kind` `new_channel` (no channel is bound to the identity and none is a candidate) or `add_streams` (the identity has a bound channel that lacks some of its streams). An identity's **candidate channels** are the existing channels on which more than half of the streams classify to it. They are computed and shown, never stored. Several candidates is the normal case: auto sync creates one channel per provider stream. **No proposal of kind `add_streams` is raised until an admin has bound a target channel**, either by picking one candidate (stored in `ContentIdentity.channel`) or by accepting a `new_channel` proposal. Binding changes no channel. Accepting `add_streams` **keeps the target's `stream_order_mode`**. The accept dialog offers "order this channel automatically" as an explicit checkbox, off for a `manual` channel. A channel created from `new_channel` starts `auto`, because nothing exists to destroy. | R3: propose new, admin accepts. Adding a stream to a channel changes what clients may receive, so it needs acceptance. Choosing among several candidates is a judgement about which channel the admin's clients use, and the spec must not make it. |
| **D14** | **The LLM assist is a suggestion source for the review queue, never a writer, and it sends only sanitised, allowlisted fields.** It runs only when `llm_enabled` is true **and** `MINO_CATALOG_LLM_API_KEY` is set in the environment. The key is never stored in the database or returned by any API. Outbound content is built by one function from fields that have each passed § LLM assist's sanitiser, which removes URL-, email- and credential-shaped substrings **and every known account value**. A record the sanitiser changed is **omitted, not sent**. Derived fields are recomputed from the sanitised inputs, never copied from the stored classification. What it returns becomes `IdentityMatch` rows with `source=llm`. It never crosses a known region or variant. It is sent over plain `requests` (already a dependency), so no SDK dependency is added. | R2 makes it optional and off by default, and forbids URLs and credentials. Pattern redaction alone cannot catch a bare username that a provider put in a group title, so known account values are matched literally, and anything touched is dropped rather than partially sent. |
| **D15** | **The Go relay changes in one PR (S1), and only to report.** (a) It posts `stream_stats` again at the Python cadence, **attributed by source generation**. The posted keys are only those the current source has measured, and a late line from a replaced source is never posted (§ S1). (b) It adds the attributed stream to the events that lack it: `stream_switch` gains `from_stream_id` and `trigger`, and `channel_buffering`, `channel_error` (`connection_failed`) and `channel_stop` gain the `stream_id` playing when they fire. (c) Every event gains `relay_boot` (random per process start) and `seq` (a process-wide monotonic counter assigned at emit), so Django can deduplicate a retried batch. No decision the relay makes changes, and the status endpoint's merged `stats` view is unchanged. | M1 and M2, plus round-1 finding 2: the channel's merged stats survive a switch, so posting them would label stream B with stream A's resolution. A separate per-generation measurement, used only for posting, fixes that without touching what `GET /proxy/relay/channels` shows. |
| **D16** | **Naming-convention overrides live per account** in `M3UAccount.custom_properties["catalog"]`, a validated sub-dict: `default_region`, `region_tokens` (token → ISO code or `null` to ignore, e.g. `{"AR": null}` where the provider's `AR:` means Arabic, not Argentina), `strip_prefixes` / `strip_suffixes` (literal strings), and `region_from` (an ordered subset of `["tvg_id", "epg_source", "name", "group", "default"]`). `convention_version` is a hash of that sub-dict, so editing it re-classifies only that account (D6). | Conventions are per provider, so the owner fixes them where the provider is configured. The sub-dict needs no migration, follows the account's existing JSON pattern, and is validated by a serializer, so a typo is a 400, not a silent no-op. |

## Data model

All new tables are in `apps/catalog`, except the two `apps/channels` columns. **Each table lands in the PR
named beside it, and no PR's migration references a table a later PR creates.**

**`StreamClassification`** (S3), one-to-one with `Stream`, primary key `stream`:

| Field | Type | Notes |
|---|---|---|
| `stream` | OneToOne → `dispatcharr_channels.Stream`, PK, CASCADE | |
| `stream_key` | char(80), indexed | D5's key, computed here so decisions can join on it |
| `fingerprint` | char(40), indexed | D6 |
| `canonical_name` | char(512) | display form, e.g. `Sky Sports Main Event` |
| `canonical_key` | char(512), indexed | match form, e.g. `sky sports main event`; `""` when empty (§ Parsing) |
| `region` | char(2), indexed | ISO 3166-1 alpha-2, `""` = unknown |
| `region_evidence` | char(16) | which rule set it (§ Region) |
| `region_conflict` | bool | two strong sources disagreed and no pin resolves it |
| `variant` | char(16) | `""`, `+1`, `+2`, `east`, `west` |
| `name_tier` / `measured_tier` / `effective_tier` | small int | `0` UNKNOWN, `1` SD, `2` HD, `3` FHD, `4` UHD; D8 defines the sort rank, not the integer |
| `tier_conflict` | bool | the name carried two different tier tokens |
| `tier_source` | char(8) | `name` / `measured` |
| `codec_hint`, `fps_hint`, `markers` | char / small int / JSON list | |
| `measured_at` | datetime null, indexed | the resolution observation the measured tier came from |
| `classified_at` | datetime | |

`varchar(512)` matches `Stream.name` (`apps/channels/models.py:64`). Group titles are unbounded, so they are
truncated to 512 characters *before* parsing, and the golden corpus has a line that pins it.

**S4 adds** to `StreamClassification`: `identity` (FK → `ContentIdentity`, null, SET_NULL, indexed) and
`match_state` (`decided`, `auto_tvg`, `auto_key`, `proposed`, `unmatched`, `excluded`, `conflict`). It also
adds the following tables:

- **`ContentIdentity`**: `canonical_name`, `canonical_key`, `region`, `variant`,
  `unique(canonical_key, region, variant)`; `tvg_id` (the most common non-empty tvg_id among members);
  `epg_data` (FK `epg.EPGData`, null, SET_NULL; § EPG binding); `epg_state` (`bound` / `none` /
  `ambiguous`); `channel` (FK `dispatcharr_channels.Channel`, null, SET_NULL; set **only** by an admin, D13);
  `created_at`.
- **`IdentityMatch`**, the review queue: `stream` (FK), `identity` (FK, null for a conflict row with no
  candidate), `source` (`fuzzy` / `region_conflict` / `unknown_region` / `llm`), `score` (0-100),
  `suggested_region` (char(2)), `state` (`open` / `accepted` / `rejected`), `created_at`;
  `unique(stream, identity, source)`.
- **`StreamAssignment`**: `stream_key` (**unique**), `account` (FK `m3u.M3UAccount`, CASCADE), `kind`
  (`assign` / `exclude`), `identity` (FK, CASCADE, required when `kind = assign`, null otherwise; a check
  constraint enforces it), `decided_by` (FK user, SET_NULL), `decided_at`.
- **`StreamRegionPin`**: `stream_key` (**unique**), `account` (FK, CASCADE), `region` (char(2), non-empty),
  `decided_by`, `decided_at`.
- **`PairRejection`**: `stream_key`, `identity` (FK, CASCADE), `decided_by`, `decided_at`;
  `unique(stream_key, identity)`.
- **`ChannelProposal`**: `identity` (FK), `kind` (`new_channel` / `add_streams`), `channel` (FK, null),
  `stream_ids` (JSON list), `members_hash` (sha1 of the sorted stream keys), `revision` (int),
  `state` (`open` / `accepted` / `dismissed`), `created_at`, `decided_at`, `decided_by`. A partial unique
  index allows at most one `open` row per `(identity, kind)`. A re-scan updates the open row in place and
  bumps `revision`. A **dismissed** proposal is not raised again for the same `members_hash`. It returns
  only if the identity gains a stream that was not in the dismissed set.

**S5 adds:**

- **`StreamHealthEvent`**, an append-only queue: `relay_boot` (char(16)), `seq` (bigint),
  `unique(relay_boot, seq)`; `stream_id` (int, indexed, **no FK**, so a stream deleted between ingest
  and fold cannot fail the insert); `channel_uuid`; `kind` (`start` / `switch` / `stop` / `failure` /
  `buffering`); `from_stream_id` (int, null); `trigger` (char); `at` (receipt time).
- **`StreamPlaySegment`**, the durable open-segment state: `channel_uuid` (unique), `relay_boot`,
  `stream_id`, `opened_at`, `last_event_at`. There is one row per channel currently believed to be
  playing.
- **`StreamHealth`**, one-to-one with `Stream`, CASCADE: `failures_decayed`, `exposure_s_decayed`,
  `decayed_at`, `rate`, `band` (`good` / `fair` / `poor` / `unknown`), and lifetime counters for display
  (`failovers`, `connect_failures`, `buffering_episodes`, `play_seconds`).

**S6 adds:**

- `Channel.stream_order_mode` (char(8), default `"manual"`) and `ChannelStream.pinned` (bool, default
  `False`), in `apps/channels/migrations/0040_*` (the tip at the base is
  `0039_channel_hls_output_profile.py`; the plan re-checks the number at its seed). Both have
  defaults, so the migration needs no data pass.
- **`ChannelOrderSnapshot`**: `channel` (FK, CASCADE), `stream_ids` (JSON list, in order), `pinned_ids`
  (JSON list), `reason` (`enable_auto` / `accept_proposal`), `created_at`. The last five per channel are
  kept.

## Parsing (S2)

The parser runs in fixed **phases**. Each property in § Test strategy names the phase it holds over.

1. **Normalise.** Truncate the name and the group title to 512 characters each. Apply NFKC and
   casefold, and replace `&` with ` and `. Remove the account's `strip_prefixes` / `strip_suffixes`
   (literal, case-folded, at most one of each).
2. **Tokenise.** Split on whitespace and the separators `| [ ] ( ) : - _ / ·`. Keep `+1` / `+2` as single
   tokens. Record for each token whether it was **delimited**, meaning bracketed (`[US]`, `(UK)`,
   `|NZ|`) or followed by `:` / `-` / `|` when it is the first token (`UK:`, `NZ -`).
3. **Classify decorations.** Every token is checked against the decoration classes below, in this
   order, and a decoration is removed from the word list:

   | Class | Tokens (case-folded) | Effect |
   |---|---|---|
   | tier | `8k`, `4k`, `uhd`, `2160p` → UHD; `fhd`, `fullhd`, `1080p`, `1080i` (and the two-token `full hd`) → FHD; `hd`, `720p` → HD; `sd`, `576p`, `576i`, `480p`, `lq` → SD | `name_tier` is the **highest** tier present; `tier_conflict` is set when two different tiers occur |
   | codec | `hevc`, `h265`, `x265` → hevc; `h264`, `avc` → h264 | hint only |
   | fps | `\d{2,3}fps`, `50p`, `60p` | `fps_hint` is the highest present |
   | marker | `backup`, `bk`, `raw`, `alt`, `test` | kept in `markers` (sorted, de-duplicated) |
   | variant | `+1`, `+2`, `east`, `west` | kept in `variant`; removed from the key and part of identity (D4) |

4. **Extract the region from the name.** This runs on the token list **after** decorations are removed,
   so `UK: Sky Arts FHD HEVC 50FPS` and `Sky Arts UK FHD HEVC 50FPS` both see `UK` at an edge. A
   region-table token (§ Region) counts as name evidence when it is delimited (anywhere), or when it is
   the first or last remaining token and at least one other word remains. **Protected phrases** in
   `regions.py` are matched before this phase and kept as words: `uk gold`, `uktv`, `us weekly`, and any
   the plan finds in the corpus. One region token is consumed from the name at most. If the name
   carries two different region tokens, that is a name-internal conflict (§ Region).
5. **Group fallback.** If the name gave no tier, the group title's tier tokens are used (`UK | FHD Sports`
   → FHD). The group never overrides a tier the name gave. Group region evidence is § Region's source 5.
6. **Key.** Map the standalone tokens `one` … `ten` to `1` … `10`. Remove pure-punctuation tokens. The
   remaining words joined by single spaces are `canonical_key`. Nothing else is aliased: no stemming,
   and `sport` ≠ `sports`. **An empty key** (a name made only of decorations and a region, e.g.
   `UK HD`) yields `canonical_key = ""` and match state `unmatched`. Such a stream never binds
   automatically and appears in the review queue.

**Display name.** The canonical name is the identity members' remaining words in the most common original
casing, so `SKY SPORTS MAIN EVENT` does not win over `Sky Sports Main Event`.

**Golden cases written into the spec** (the corpus holds many more):

| Input (name / group) | key | region | variant | tier |
|---|---|---|---|---|
| `UK: Sky Sports Main Event FHD` / `Sports` | `sky sports main event` | GB | | FHD |
| `SKY SPORTS MAIN EVENT UK HD` / `Sports` | `sky sports main event` | GB | | HD |
| `\|NZ\| Sky Sport 1 HD` / `NZ Sports` | `sky sport 1` | NZ | | HD |
| `UK: Sky Arts HD` / `Entertainment` | `sky arts` | GB | | HD |
| `\|NZ\| Sky Arts HD` / `Entertainment` | `sky arts` | NZ | | HD |
| `Sky Arts UK FHD HEVC 50FPS` / `` | `sky arts` | GB | | FHD |
| `UK Gold` / `UK Entertainment` | `uk gold` | GB (group) | | UNKNOWN |
| `UK: Sky One +1 HD` / `` | `sky 1` | GB | `+1` | HD |
| `Sky Cinema 4K HD` / `` | `sky cinema` | | | UHD, `tier_conflict` |
| `ESPN` / `US \| FHD Sports` | `espn` | US (group) | | FHD (group) |
| `UK HD` / `` | `""` | GB | | HD, `unmatched` |
| `AR: MBC 1` / `` (default table) | `ar mbc 1` | | | UNKNOWN |

The `AR:` line becomes `mbc 1` with no region once the account sets `region_tokens: {"AR": null}`. The
`AR` token is then dropped as noise instead of kept as a word. The S8 golden test pins it.

## Region

**The region table** maps tokens to ISO 3166-1 alpha-2 codes: two-letter codes, a curated alias set
(`uk` → GB, `usa` → US, `aus` → AU, …), and English country names (`new zealand`, `united kingdom`).
Tokens that are also language codes or ambiguous are deliberately **absent** from the default table and
count only through an account-level `region_tokens` entry: `ar` (Arabic or Argentina), `en`,
`lat` / `latino`, `int`, `es` (Spanish or Spain) and `pt`.

**Evidence sources, strongest first.** The first source that gives a region sets it, and
`region_evidence` records which:

1. `pin`: a `StreamRegionPin` for this stream key. **A pin ends any conflict** (D5).
2. `tvg_id`: the final dot-segment of `tvg_id` is a region-table token (`SkyArts.nz`, `BBCOne.uk`).
3. `epg_source`: the region the stream's tvg_id resolves to under § EPG binding's rule. It counts only
   when that rule yields exactly one region.
4. `name`: § Parsing phase 4.
5. `group`: a region token, or a country name, in the group title.
6. `default`: the account's `default_region` (D16).
7. none: `""`.

The account's `region_from` may reorder or drop sources 2-6, but never source 1.

**Conflict rule.** Without a pin, if any two of sources 2, 3 and 4 give different regions, or the name
carries two different region tokens, the stream gets `region = ""`, `region_conflict = true` and match
state `conflict`. **A conflicted stream is review-only.** It takes part in no automatic binding, creates no
identity, and appears in no proposal. It gets one `IdentityMatch(source=region_conflict)` row per
candidate identity in each region that was claimed. The admin resolves it with a region pin or an
assignment. The "UK" prefix on an NZ-tvg_id stream is exactly the provider mistake that would otherwise
merge two Sky Arts feeds.

## EPG binding (S4)

The catalog binds an identity to an EPG row, and derives region evidence from EPG, using one rule. It
does not call `apps/channels/epg_matching.py`, which takes the first priority-ranked row for a tvg_id
whatever its region (§ Verified facts).

For a tvg_id, collect every active `EPGData` row with that tvg_id (case-insensitive). Each row's
**source region** is `EPGSource.custom_properties["region"]` when set (an optional field, edited on the EPG
form in S7), else the tvg_id's own suffix region, else unknown.

- **Region evidence** (§ Region source 3): if the rows' known source regions are all the same region,
  that region is the evidence. If they disagree, source 3 gives nothing, and the stream is flagged so
  that the conflict rule can see the disagreement.
- **Identity binding**: keep the rows whose source region equals the identity's region, plus rows whose
  source region is unknown only if no row has a known region. If the kept rows come from exactly one
  source, bind the highest-priority such row (`epg_state = bound`). If they come from more than one
  source and their `name`s differ after case-folding, set `epg_state = ambiguous` and leave `epg_data`
  null. The Identities tab lists ambiguous identities for the admin to pick. If no row is kept, set
  `epg_state = none`.

An accepted channel takes `epg_data` from its identity only when `epg_state = bound`. Otherwise it is
created with no EPG, and the dialog says why. The existing matcher can still be run by hand, as today.

## Quality tier (S3)

- **Name tier**: from the parser.
- **Measured tier**: from S1's `stream_stats` events only, by **height**: ≥ 2000 → UHD, ≥ 1000 → FHD
  (1080i counts; interlace is not a tier), ≥ 700 → HD, otherwise SD. Provenance is per resolution, not
  per row. S1's Django half writes `stream_stats["resolution_observed_at"]` (an ISO timestamp) **only**
  when an event carries `relay: "go"` and a `resolution` or `height` key. A merge that carries no
  resolution never refreshes it. The measured tier is used only when `resolution_observed_at` is
  present and within `measured_ttl_days` (default 30). Pre-cutover values and hand-written values
  have no such key and are never used.
- **Effective tier**: the measured tier if it is valid and fresh, otherwise the name tier.
  `tier_source` records which.
- **The measured-tier pass** (`refresh_measured_tiers`, beat every 15 minutes, bounded to 5,000 rows
  per run, continuing on the next run) selects two sets. The first is streams with
  `stream_stats_updated_at > classification.classified_at`, using the existing index on
  `stream_stats_updated_at` (`apps/channels/models.py:135-140`); for each one it re-reads
  `resolution_observed_at`. The second is classifications with `tier_source = measured` and
  `measured_at < now − measured_ttl_days` (indexed); these fall back to the name tier. A tier change
  marks the stream's channels for the next reorder pass.
- `video_bitrate` and `source_fps` are displayed but not used to rank in this programme (Q3).

## Identity resolution (S4)

**Concurrency.** One global run at a time:

- **Requesters.** A requester (a classification finishing, a decision changing, the admin "Re-run",
  or a settings change) first sets the Redis key `catalog_resolve_pending`, then tries
  `acquire_task_lock("catalog_resolve", 0)` (`core/utils.py:296`). If the lock is held, it returns.
- **The holder.** The holder starts a `TaskLockRenewer` (`core/utils.py:327`), as the refresh does. It
  then loops: `GETDEL catalog_resolve_pending`, and if the key was set, run a pass. It exits the loop
  when the key was unset.
- **Release, then check.** The holder releases the lock, **then** checks the pending key once more. If
  the key is set, it dispatches `resolve_identities.delay()`.

This ordering closes the hand-off race. A requester whose acquire failed did so while the lock was
held, so the holder's post-release check runs after that requester's set, and sees it.

**Bounded work.** Fuzzy comparison has a per-run budget, `fuzzy_max_comparisons` (default 5,000,000,
roughly 30 s at M4's rate). Streams not reached stay `proposed`-pending, and the run sets the pending
key, so the next run continues. A block larger than 2,000 identities is split by the second key token.
A block still larger is skipped for that stream, which stays `unmatched` with a review note. S4
measures one global run over a synthetic 3-account, 300k-stream corpus on the test container, and
records the result in its PR body.

**Passes**, in order. Each pass considers only streams the earlier passes left unresolved. A stream
whose match state is `conflict`, or whose region is unknown, or whose key is empty, skips passes 2-5.

1. **Decisions.** `StreamAssignment(assign)` places the stream in its identity (`decided`). `exclude`
   sets `excluded`. A region pin has already been applied in classification.
2. **Exact tvg_id.** Streams with the same non-empty case-folded tvg_id, the **same known region and
   the same variant**, join one identity (`auto_tvg`). Two streams with the same tvg_id but different
   regions or variants stay apart, and each gets an `IdentityMatch(source=region_conflict)` against the
   other's identity.
3. **Exact key.** The same `(canonical_key, region, variant)` with a known region joins one identity
   (`auto_key`).
4. **Fuzzy, blocked.** Each stream is compared only within its block: identities with the same region,
   the same variant and the same first key token. The scorer is `rapidfuzz` `token_sort_ratio` with
   `score_cutoff = fuzzy_threshold` (default 90), keeping at most three candidates. Each candidate becomes
   `IdentityMatch(source=fuzzy)`. **Fuzzy never binds.**
5. **New identity.** A stream still unresolved, with a known region and no fuzzy candidate, creates its
   own identity (`auto_key`).
6. **Unknown region.** A stream with an unknown region (and no conflict) gets
   `IdentityMatch(source=unknown_region)` against the best same-key identity in each region, or stays
   `unmatched`.
7. **LLM** (only under D14's conditions): § LLM assist.

A `PairRejection` suppresses its `IdentityMatch` in every pass. **Proposals** are recomputed for every
identity whose membership changed in the run (D13). Conflicted, unknown-region and empty-key streams
never enter a proposal.

## Reliability (S5)

**Ingest.** The `relay_event_applied` receiver handles events that carry S1's `relay_boot` and `seq`.
Events without them come from a relay older than S1; they append nothing. It inserts with
`bulk_create(ignore_conflicts=True)` on `unique(relay_boot, seq)`, so a retried batch is a no-op.

| Event | Row | Notes |
|---|---|---|
| `channel_start` (`stream_id`) | `start` | |
| `stream_switch` (`from_stream_id`, `stream_id`, `trigger`) | `switch` | the fold counts a failure for `from_stream_id` when `trigger` is `health_monitor` or `buffering_timeout` |
| `channel_error`, `error_type = connection_failed` (`stream_id`) | `failure` | weight 1.0 |
| `channel_buffering` (`stream_id`) | `buffering` | weight 0.25 |
| `channel_stop` (`stream_id`) | `stop` | |

`max_retries_exceeded` switches are **not** counted as a failure, because the `connection_failed` error
that precedes them already was. Operator switches (`trigger = operator`) only move exposure.

**Fold** (`fold_stream_health`, beat every 5 minutes, under its own task lock with a renewer). Each run is
**one database transaction**:

1. Read up to 50,000 queued rows in `(relay_boot, seq)` order, with `select_for_update(skip_locked=True)`.
2. Apply them per channel against `StreamPlaySegment`:
   - `start` closes any open segment for that channel uncredited, then opens a new one.
   - `switch` credits `at − opened_at` to the open segment's stream when that stream equals
     `from_stream_id`, otherwise closes it uncredited. It then opens a segment for `stream_id`.
   - `stop` credits and closes the segment.
   - `failure` and `buffering` touch `last_event_at` and add their weight to the named stream.
   - An event whose `relay_boot` differs from an open segment's closes that segment uncredited, because
     the relay restarted.
3. Close uncredited every segment whose `last_event_at` is more than 24 h old.
4. Update `StreamHealth` for every touched stream:

   ```
   d                  = 2 ** (-(now - decayed_at) / half_life)      # half_life = health_half_life_days, default 7
   failures_decayed   = failures_decayed   * d + Σ weight
   exposure_s_decayed = exposure_s_decayed * d + Σ credited seconds
   rate               = (failures_decayed + 0.5) / (exposure_s_decayed / 3600 + 1.0)   # failures per playback hour, smoothed
   band               = unknown if exposure_s_decayed < 900
                        else good if rate < 0.1 else fair if rate < 0.5 else poor
   ```

5. Delete the rows read in step 1.
6. Commit. A worker that dies before commit rolls back everything, so the rows are folded again by the
   next run. Nothing is credited twice and nothing is lost.

A segment that stays open across many folds is credited only when it closes, so a long viewing is
counted once. The smoothing constants give an unplayed stream a rate of 0.5/h, the fair/poor edge. It
therefore ranks below any proven stream and above a proven-bad one. The formula lives in
`apps/catalog/health.py` beside its constants, and the S5 tests pin the formula, not the numbers.

**Band hysteresis in D8.** Within a tier, only the band ranks. A stream whose rate moves within its band
never moves.

## When things run

| Task | PR | Trigger | Scope | Lock |
|---|---|---|---|---|
| `classify_account_streams(account_id)` | S3 | `.delay()` from the refresh tail after `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:3942`), in its own `try` that only logs (it never sets the account status), only if `classify_enabled` | that account's non-stale live streams with a changed fingerprint (D6) | per account, renewed |
| `refresh_measured_tiers()` | S3 | beat, every 15 minutes | § Quality tier | global |
| `resolve_identities()` | S4 | requested at the end of the above, on decision or settings changes, and by "Re-run" | § Identity resolution | global, coalescing, renewed |
| `fold_stream_health()` | S5 | beat, every 5 minutes | queued health events | global, renewed |
| `reorder_channels(channel_ids=None)` | S6 | after `resolve_identities` and `refresh_measured_tiers` (channels whose members' tiers changed), after `fold_stream_health` (channels whose members changed band), and hourly as a backstop; only if `auto_order_enabled` | `auto` channels only | D10 per channel |

A failure in any of them is logged and leaves the previous state in place. None of them is called from a
request on the tune path, and none of them raises into the refresh task.

**Budget, 100k streams in one account.** From M4, with a 10× allowance: parse ~2 s and fingerprint ~0.3 s.
Reading with `.only(...)` and `.iterator(chunk_size=2000)` is estimated at 5-10 s. Upserting 100k rows on
a first run (`bulk_create(update_conflicts=True)`, batches of 1000) is estimated at 20-60 s; **S3 measures
it on the test container**. A steady-state refresh touches the changed few percent. All of it runs on the
Celery `default` worker, never in uWSGI.

## LLM assist (S9)

Off by default (D12, D14). When it runs, it considers streams in state `unmatched` or `unknown_region`,
or with an open fuzzy match whose best score is 70-90, at most `llm_max_streams_per_run` (default 500)
per run.

**The sanitiser** (`apps/catalog/llm_payload.py`, one function, `sanitise(text, secrets) -> (text, changed)`):

- Apply NFKC to the text first.
- Then remove every substring matching:
  - a URL scheme, `[a-z][a-z0-9+.-]*://\S*`
  - `\S+:\S+@\S+`
  - an email address
  - a run of 24 or more base64- or hex-alphabet characters
- Then remove every **known secret**, matched case-insensitively. `secrets` is built once per run and
  holds every account's `name`, `username`, `password` and the host of `server_url`, plus every
  string-valued `custom_properties` entry of every `M3UAccount` and `M3UAccountProfile`, and the
  credentials parsed out of profile search and replace patterns
  (`apps/m3u/connection_pool.py:57-99`). Values shorter than four characters are left out, so that
  `HD` cannot erase every name.
- Truncate to 200 characters.
- `changed` is true if any removal happened.

**Building a request** (`build_request(streams, candidates, secrets)`):

- Each stream record is built from its raw `name`, group title and `tvg_id`, each passed through the
  sanitiser.
- **If any field of a record is `changed`, the whole record is omitted**, and only a count is logged.
- `parsed` is computed by calling the parser on the **sanitised** fields. It is never taken from the
  stored classification.
- Candidate identity records are built the same way, from their canonical name, tvg_id and bound
  `EPGData.name`, and omitted when changed.

**Exactly what leaves the box**, per request, as JSON:

```json
{"task": "match_streams_to_channels",
 "streams":    [{"ref": "s1", "name": "...", "group": "...", "tvg_id": "...",
                 "parsed": {"canonical": "...", "region": "GB|null", "variant": ""}}],
 "candidates": [{"ref": "i1", "name": "...", "region": "NZ", "variant": "", "tvg_id": "...", "epg_name": "..."}]}
```

- `ref` values are per-request opaque indices, mapped back locally. **No database id, `stream_id`,
  `stream_hash`, stream key or UUID is sent.**
- **Never sent:** `url`, `logo_url`, any account field, M3U profile data, channel UUIDs, user data,
  `stream_stats`, and EPG source names or URLs.

**Final check.** Just before sending, the serialised request bytes are scanned once more for the URL
pattern, `@`, and every known secret. A hit aborts the whole request, logs a count and the reason (never
the match), and sends nothing.

**Response handling.** The expected shape is
`[{"ref": "s1", "candidate": "i1" | null, "region": "GB" | null, "confidence": 0..1}]`. A serializer
validates it, and anything else is dropped. A candidate whose region or variant differs from the
stream's known region or variant is dropped (D4). The survivors become
`IdentityMatch(source=llm, score=confidence*100)`, **never decisions**. A region suggestion for an
unknown-region stream fills `suggested_region`.

**Transport.** One adapter, `apps/catalog/llm.py`, posts to the Anthropic Messages API with `requests`.
The model id is a setting (`llm_model`). Its default is chosen by the S9 plan from the provider's
current model list. The key comes from `MINO_CATALOG_LLM_API_KEY`. Logging records counts and status
codes only, never the request body, the response body or the key. `scripts/check_credential_logging.py`
runs on the file in the hook. The settings UI shows "key present / absent", never the key.

## Admin UX (S7, S8, S9)

Mantine 8 only. State goes in a new Zustand store, `frontend/src/store/catalog.jsx`. All HTTP goes through
new `API.*` methods in `frontend/src/api.js`. No new UI library, and no direct fetch from components
(CLAUDE.md § Frontend).

- **New page `/catalog`, "Lineup"** (`frontend/src/pages/Catalog.jsx`, route in `frontend/src/App.jsx`
  next to `/channels` at `:152`, nav entry beside Channels), with four tabs:
  - *Proposals*: one row per open `ChannelProposal`, with the identity, region, kind, member streams
    (tier and provider), the target channel, and the revision. Accept opens a dialog:
    - group, number, Channel Profiles;
    - "order this channel automatically", per D13;
    - for an auto-created target, the detach option below.

    Other actions: Dismiss, and bulk accept (each proposal is accepted on its own).
  - *Review*: open `IdentityMatch` rows grouped by stream. Each row shows a source badge (`fuzzy` /
    `region conflict` / `unknown region` / `LLM`), the score, and both sides' name, group, tvg_id and
    region. Actions: Assign, Reject pair, Pin region (prefilled from `suggested_region`), Exclude,
    and "New identity".
  - *Identities*: searchable. Opening one shows its members ordered as D8 would order them, with tier,
    tier source, health band and provider. It also shows the candidate channels with a "Bind to this
    channel" action (D13) and, for `epg_state = ambiguous`, the EPG rows to choose from.
  - *Status*: last run times, counts per state, the "Re-run" button, and the enablement switches with
    D12's preview for `auto_order_enabled`.
- **Channel streams table** (`frontend/src/components/tables/ChannelTableStreams.jsx`): a tier badge
  ("measured" or "from name"), a health-band dot, a pin toggle, a channel-level "Order: Auto / Manual"
  control, and "Restore previous order", which sets Manual (D7). After a drag on an `auto` channel, the
  toast says the channel is now Manual.
- **M3U account form** (`frontend/src/components/forms/M3U.jsx`): a "Naming convention" section for D16,
  with a live preview through `POST /api/catalog/parse-preview/` (S8).
- **EPG source form** (`frontend/src/components/forms/EPG.jsx`): an optional Region select (§ EPG
  binding).
- **Settings** (`frontend/src/pages/Settings.jsx`): a "Stream classification" section for
  `catalog_settings`. The LLM key shows only as present or absent.

**Access warning in the accept dialog.** When the admin picks no Channel Profiles, the dialog says: *"With
no Channel Profiles, this channel is visible only to admins and to users who have no Channel Profiles.
Users assigned to profiles will not see it until you add it to one of theirs."* This matches
`user_can_access_channel` (`apps/proxy/authorize.py:202-223`). No authorization filter changes.

**Auto-created targets.** Accepting `add_streams` into a channel with `auto_created = True` shows a
warning. Under the account's default `orphan_channel_cleanup = always`, auto sync deletes the channel once
its own account's stream disappears, even if other providers' streams remain
(`apps/m3u/tasks.py:3018-3037`). The dialog offers "Detach from auto-sync" (sets `auto_created = False`)
as an explicit checkbox. Its default is Q5.

**API** (`apps/catalog/api_urls.py`, mounted at `/api/catalog/`). Every endpoint has a DRF serializer and
appears in the drf-spectacular schema. All are **`IsAdmin`**, the REST default, with no opt-down.

- S3: `classifications/` (list, filter), `parse-preview/`.
- S4: `identities/` (list, retrieve; `POST {id}/bind` and `{id}/unbind` set or clear `channel`;
  `POST {id}/epg` picks an EPG row); `matches/` (list; `POST {id}/assign|reject`); `assignments/`,
  `region-pins/`, `rejections/` (list, create/upsert, delete); `proposals/` (list, read-only); `run/`.
- S6: `proposals/{id}/accept` and `proposals/{id}/dismiss`; `auto-order/preview`,
  `auto-order/enable`; `channels/{id}/order-snapshots/` (list; `POST {snapshot_id}/restore`). The
  channel serializer gains `stream_order_mode` and the nested `pinned`.

**Acceptance semantics** (S6). `accept` takes `{revision, options}`. In one transaction it:

- takes the proposal row with `select_for_update()` and requires `state = open` and a matching
  `revision`, otherwise 409 with the current revision;
- takes D10's lock on the target channel (for `add_streams`), and requires the channel to exist and to
  still be the identity's bound channel;
- drops member streams that were deleted, have gone stale, are already on the target, or no longer
  classify to the identity, and returns the dropped list;
- refuses with 409 if no member remains;
- writes a `ChannelOrderSnapshot` (`accept_proposal`) for an existing target;
- adds the members (membership-only, D7);
- sets `stream_order_mode` only when the admin ticked the option;
- marks the proposal `accepted`.

A competing second accept fails at the revision or state check.

## Coexistence

- **Manual assignment.** Untouched for `manual` channels, and every existing channel starts `manual` (D7).
  On `auto` channels, a reorder flips the channel to `manual`, and a membership-only edit keeps the mode.
- **Auto channel sync.** Sync still creates its one-stream channels. Their streams are classified like any
  others. Those channels show up as an identity's candidate channels, and the admin binds one or none
  (D13). Sync never sees `stream_order_mode` or `pinned`. Reorders write only `order`, so sync's own
  writes (`apps/m3u/tasks.py:2545`, `:2812-2823`, `:2862`) do not conflict.
- **EPG matching.** The existing matcher is unchanged and is not called by the catalog (§ EPG binding).
- **Stream rehash and merge** (`core/tasks.py:719`). D10 brings the merge under the lock and carries
  pins. Classification follows the surviving `Stream` row and is re-derived by fingerprint. Decisions
  survive because they are keyed per D5.
- **Stale and deleted streams.** `is_stale` streams sort last (D8). Deleted streams cascade out of every
  catalog table except `StreamHealthEvent` and `StreamPlaySegment`, whose fold skips and closes unknown
  ids.

## Known-defect interactions

- **Provider-slot counters (#513).** Nothing here touches `profile_connections:*` or
  `server_group_connections:*`. A tier-first order concentrates initial tunes on the best provider's
  slots. When those are full, `get_stream()` skips to the next stream, which is the intended fallback.
  No `INCR` or `DECR` is added anywhere.
- **The copied channel-authorization filter (eight functions).** This spec adds no client-facing listing
  surface and changes no filter. Every catalog endpoint is `IsAdmin`. A channel created by accepting a
  proposal is an ordinary `Channel`: `user_level` 0, `is_adult = any(member.is_adult)`, and Channel
  Profile membership chosen in the dialog, whose warning states the real rule (§ Admin UX).
- **The boot trap.** No module that `apps/channels/models.py` imports gains an import (D1).
- **CoreSettings blast radius.** `catalog_settings` is a new instance-wide group, a ninth beside the eight
  that CLAUDE.md § State counts. Its defaults live in its getter, so reads work with no row. `epg_settings`
  shows that a `PATCH` can fail before the row exists, so **S3 ships a data migration seeding the row**.
  Any E2E test that writes it joins the allowlist (`docs/adr/0003`).
- **Credential logging.** The LLM adapter and the parse-preview endpoint handle provider names. Neither
  logs a URL or a payload.
- **Rename ratchet (Mino spec PR R1).** If R1 has landed, a new file containing `dispatcharr` raises
  `scripts/product_name_allowlist.txt`. The cases are an import of the `dispatcharr` package, the
  Hypothesis profile name `dispatcharr-ci`, and the FK label `dispatcharr_channels`. Each plan lists
  every such line, and every one must be a name the rename spec keeps (C-9, C-10, C-13).

## Test strategy

**Celery in tests.** `CELERY_TASK_ALWAYS_EAGER` stays globally off (`dispatcharr/settings_test.py:29-33`;
CLAUDE.md § Conventions). Task bodies are tested by calling the function directly. Dispatch sites are
tested by patching `.delay` and asserting the call. An end-to-end task chain, where a test needs one, uses
a per-test `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)` on a test that creates no `M3UAccount` or
`EPGSource` inside the transaction.

**Corpus.** `apps/catalog/tests/fixtures/stream_names.jsonl` holds at least 400 lines of
`{name, group, tvg_id, convention, expect: {canonical_key, region, region_evidence, variant, name_tier, tier_conflict, markers}}`.
It is synthetic but real-shaped:

- every convention in § Goal and every golden case in § Parsing;
- prefix, suffix and bracket regions;
- protected phrases;
- ALL CAPS names;
- decorations after a suffix region;
- group-only regions and tiers, and tvg_id-only regions;
- the ambiguous tokens;
- a 600-character name;
- an empty-key name.

**The trap set**: for each of at least 20 brands present in two regions (Sky Arts GB/NZ, Sky News GB/NZ,
ESPN US/AU, Discovery GB/US, Nickelodeon GB/US, …), five decorations per region. No real provider URL,
account name or credential appears in the corpus, and a test asserts that no line contains `://`.

**Golden tests** (S2): every corpus line parses to its `expect`. A changed expectation is a test
modification and is listed with before and after.

**Property tests** (S2): Hypothesis, with the shared `dispatcharr-ci` profile registered byte-identically.

- `parse` is idempotent on its own canonical name.
- Inserting, deleting or reordering any tier, codec, fps or marker token anywhere **after phase 2**
  never changes `(canonical_key, region, variant)`.
- `name_tier` is invariant under any permutation of the tier tokens, because it is the maximum.
- For a name with a region token in an edge position (after decorations are removed) or a delimited one,
  `region` is that token's code, and the token is absent from `canonical_key`.
- **For every trap-set brand, and any decorations, the GB name and the NZ name yield regions GB and NZ
  respectively**. Their identity keys therefore differ by region, not by an accident of the key.

**Resolution tests** (S4):

- A UK and an NZ stream with equal keys and equal tvg_ids produce two identities and conflict rows,
  never one identity.
- Equal tvg_ids with variants `""` and `+1` produce two identities.
- A conflicted stream creates no identity and appears in no proposal.
- An unknown-region stream never binds automatically.
- A pin ends a conflict.
- At most one assignment exists per key, and replacing one re-classifies the key.
- A rejection survives a re-run and a rehash.
- Fuzzy never binds.
- An `add_streams` proposal is never raised for an identity with no bound channel.
- Dismissal persists until a new member appears.
- **Concurrency**: a request arriving during the final pass, and one arriving between the lock release
  and the final check, each lead to exactly one further run. A lock that expires mid-run is renewed:
  the test drives the renewer with an injected clock.
- **EPG**: the same tvg_id in a GB-region and an NZ-region source binds the GB identity to the GB row
  and the NZ identity to the NZ row. Two unknown-region sources with different names give `ambiguous`.

**Ordering tests** (S6):

- D8's key on hand-built cases, including a tie whose current order is deliberately **not** id order.
  That order must survive two passes, and the second pass writes nothing.
- A `manual` channel is never written.
- A reorder on an `auto` channel flips it to `manual`. A membership-only edit does not.
- A restore sets `manual`, and the next pass leaves the channel alone.
- Concurrent reorder and `PATCH` (two connections, Postgres-only): the `PATCH` wins.
- Rehash merge with a pin only on the source row, and with a pin only on the target row: the survivor
  is pinned in both cases.
- Accept: a stale revision gets 409; a deleted member is dropped; a second accept gets 409; an
  `add_streams` proposal into a `manual` channel keeps it `manual` unless the option is set.
- `get_stream()` and the failover branch of `resolve_source` pick the tier-sorted first candidate on a
  reordered channel.

**Tune-path ledger:** `apps/proxy/tests/test_tune_path_query_ledger.py` passes **unchanged** in every PR. A
change to it is a finding.

**Health tests** (S5):

- The fold formula, with an injected clock.
- Attribution from a hand-built sequence: start → switch(health_monitor) → stop.
- A duplicated batch (the same `relay_boot`/`seq`) appends once.
- A worker failure between the update and the delete (an exception injected after step 4) leaves the
  queue intact and credits nothing. The next fold credits once.
- Playback spanning three folds is credited once, at stop.
- A `relay_boot` change closes segments uncredited, and so does a segment older than 24 h.
- Events without S1 fields append nothing.
- `max_retries_exceeded` is not double-counted.

**Quality tests** (S3):

- A stream with `resolution_observed_at` older than the TTL falls back to its name tier on the next
  measured-tier pass, with no refresh.
- A `stream_stats` merge with no resolution does not refresh `resolution_observed_at`.

**LLM tests** (S9), all against a fake transport:

- Hypothesis generates names and groups that embed URLs, `user:pass@host`, emails, long tokens and the
  fixture account's own username, password, name and host.
- For every case the **whole serialised request** contains none of them, including `parsed.canonical`.
- The record carrying them is omitted, not partially sent.
- The request's key set is asserted **exactly** against an allowlist, so a field added later fails the
  test rather than leaking.
- A planted secret that slips past the builder (the test monkeypatches the builder) is caught by the
  final check, and nothing is sent.
- A response naming a cross-region or cross-variant candidate is dropped.
- With `llm_enabled` false, or the env var unset, the fake records zero calls.

**Go (S1):** see § S1. **Frontend:** vitest for each new component and store, mocking `api.js` (the
existing pattern).

## The PRs

Branches are `feature/catalog-*`, except S1, which touches the live path and is named
`migration/catalog-s1-relay-events` so the full E2E matrix runs on it (CLAUDE.md § Full E2E runs). No PR
description below carries a closing keyword. A PR that fixes a filed issue gets `Closes #N.` in its own
implementation PR, never in this spec.

**Dependencies and stopping points.** Every stopping point migrates from the previous one, boots, and
works with the features it has.

- **S1** stands alone.
- **S2** stands alone.
- **S3** needs S2. *Stopping point*: tiers visible, read-only.
- **S4** needs S3. *Stopping point*: identities, review queue, decisions, binding and read-only
  proposals. **It writes no channel.**
- **S5** needs S1 and S2 (for the app). *Stopping point*: health visible.
- **S6** needs S4 and S5. *Stopping point*: ordering and proposal acceptance. This is the headline
  behaviour, API-driven.
- **S7** needs S6. *Stopping point*: the full UI.
- **S8** needs S3.
- **S9** needs S4.

### S0 — this spec

Docs only. It cites a tracking issue with `Refs`, if one is filed.

### S1 — the relay reports which stream, and posts stream stats again (Go, reporting only)

**Changes.**

- **Event identity.** `relay/control`'s `Emitter` draws `relay_boot` (16 random hex characters) once at
  `NewEmitter`, and assigns `seq` (a `uint64`, incremented atomically) to each event as it is enqueued.
  Both are added to the event's `details`. An event dropped from a full queue still consumes a `seq`,
  which is harmless, because gaps carry no meaning.
- **Attribution.**
  - `failover()` passes `why` and the pre-switch stream id to `applySwitch`.
  - `stream_switch` gains `from_stream_id` (int, omitted when 0) and `trigger` (`health_monitor` /
    `max_retries_exceeded` / `buffering_timeout` / `operator`). `advance.go` passes `operator`.
  - `channel_buffering` (`source_transcode.go:352`), `channel_error` `connection_failed`
    (`channel.go:604`) and `channel_stop` (`channel.go:759`) gain `stream_id`, the stream current when
    they fire.
  - `emit` lifts `details["stream_id"]` to the top level (`events.go:39-41`). `channel_stop` builds its
    `Event` directly, and must set both.
- **Stats by source generation.** The `Channel` gains a `generation` counter and a second struct,
  `measured`, used **only** for posting. The existing `stats` struct and everything that reads it (the
  status endpoint) are unchanged.
  - `applySwitch`, and the initial source start, increment `generation` and reset `measured` to empty,
    under `c.mu`.
  - Each transcode source attempt captures the generation it was started for.
  - Its stderr reader passes that generation to `reportInfo`. `reportInfo` merges into `stats` exactly
    as today, and merges into `measured` **only if the line's generation equals the current one**. A
    line from a replaced source never reaches `measured`.
  - A `stream_stats` event carries `relay: "go"`, `stream_id` and `generation` (both of the current
    generation, read under the same lock as `measured`), plus only the keys `measured` holds, under the
    Python key names: `video_codec`, `resolution`, `width`, `height`, `source_fps`, `pixel_format`,
    `video_bitrate`, `audio_codec`, `sample_rate`, `audio_channels`, `audio_bitrate`, `stream_type`,
    `ffmpeg_output_bitrate`.
  - It is posted on the first info line of a generation and whenever `measured` changes (at most once
    per second), every 30 s while `measured` is non-empty, and once on stop.
  - Nothing is posted for an empty `measured`, so a source B that never reports video metadata posts no
    resolution, and stream B is never given A's.
  - This covers the subprocess architecture only (row 29 unchanged).
- **Django half** (`core/relay_events.py`). `_apply_stream_stats` keeps its merge. It also writes
  `resolution_observed_at = now` into the stored dict when the event has `relay == "go"` and carries
  `resolution` or `height`. The `relay`, `generation`, `relay_boot` and `seq` keys are not stored in
  `stream_stats`.
- `docs/relay-parity-matrix.md` gains three rows:
  - the stats emission, its cadence and its generation rule;
  - the attribution fields;
  - the event identity.

  Each row names its Go test.

**Tests.**

- `relay/channel/failover_test.go`: each trigger produces `stream_switch` with the right
  `from_stream_id` and `trigger`.
- `relay/channel/source_transcode_test.go`, using the captured stderr corpus and an injected clock:
  `stream_stats` carries the expected keys; a 30 s flush; a final flush on stop.
- **A→B with B silent**: A reports 1920×1080, then a failover to B, which reports no video metadata.
  The test asserts no event carries `stream_id = B` with a `resolution`. The variants are a buffering
  switch, an operator switch (`Advance`), and a stop issued straight after the switch.
- **Late old-source line**: after `applySwitch` to B, feed one more A info line through A's reader. It
  changes `stats` (the status view, as today) but not `measured`, and no event carries it.
- `relay/channel/source_proxy_test.go`: the Proxy profile posts no `stream_stats`.
- `relay/control` emitter test: `seq` is strictly increasing, and `relay_boot` is constant within a
  process.
- `core/tests/test_relay_events.py`: `resolution_observed_at` is set only for `relay: "go"` with a
  resolution, and the transport keys are not stored.

Coverage follows the Phase 4 floor rule (D20): the PR lists its uncovered statements and shows ≥ 85% on
its additions.

**Break-checks.**

- Drop the generation comparison in `reportInfo`. The late-line test reddens, naming the stray
  resolution on stream B.
- Drop `from_stream_id` from `applySwitch`. The failover test reddens, naming the missing key.
- Post stats from the Proxy source. The Proxy test reddens.

**Overlap.** Mino rename G1 rewrites every Go import path. Whichever PR lands second rebases mechanically.

**PR description draft:**

> The Go relay stopped posting `stream_stats` when it took over live traffic: it parses the same
> stats and serves them on `GET /proxy/relay/channels`, but never sends them to Django, so nothing
> automatic has written `Stream.stream_stats` since the cutover. This restores the posting, attributed
> by source generation so a measurement is only ever stored against the stream that produced it
> (a late line from a replaced source is dropped, and the status view is unchanged), and adds the
> attributed stream to the events that lack it (`stream_switch` gains `from_stream_id` and `trigger`;
> `channel_buffering`, `channel_error` `connection_failed` and `channel_stop` gain `stream_id`) plus
> a per-process `relay_boot` and `seq` on every event so Django can deduplicate a retried batch. No
> relay decision changes. Three new parity-matrix rows. Spec:
> `docs/superpowers/specs/2026-10-31-stream-classification-design.md`, PR S1.

### S2 — the parser (pure, inert)

**Changes.**

- The `apps/catalog/` app skeleton: `apps.py`, an empty `models.py`, and the app added to
  `INSTALLED_APPS`.
- `parse.py` (D3 and § Parsing), `regions.py` (the region table and protected phrases), and
  `conventions.py` (D16 validation and `convention_version`).
- The corpus, the golden tests and the property tests.
- `CONTEXT.md` gains **Content identity** and **Quality tier**.

The plan must confirm that `dispatcharr/test_discovery.py` and CI's label list
(`FULL_SUITE=1 python3 scripts/ci_backend_test_labels.py`) pick up the new app's label, and add a
`_PATH_ALIASES` entry if `apps/catalog/` needs one.

**Break-checks.**

- Remove `nz` from the region table. The trap property reddens, reporting region `""` for
  `|NZ| Sky Arts HD` where `NZ` was expected.
- Map `sport` to `sports`. The golden line for `|NZ| Sky Sport 1 HD` reddens.
- Run region extraction before decoration removal. The golden line for `Sky Arts UK FHD HEVC 50FPS`
  reddens on region.

**PR description draft:**

> Adds `apps/catalog` with a pure, versioned stream-name parser: canonical name and key, region
> with its evidence, tier/codec/fps hints, markers and feed variant, in fixed phases. No models, no
> tasks, nothing runs yet. A 400-line real-shaped corpus (including a two-region brand trap set) is
> golden-tested, and Hypothesis properties pin that decorations never change identity, tiers are
> order-independent, and the trap brands always extract their own region. Spec PR S2.

### S3 — classification and tiers

**Changes.**

- The `StreamClassification` model and its migration. It has no identity column yet, which S4 adds.
- `classify_account_streams` (D6), dispatched from the refresh tail behind `classify_enabled`.
- `refresh_measured_tiers`, with its beat entry.
- The `catalog_settings` getter with defaults, and a data migration seeding its row.
- Read-only `classifications/` and `parse-preview/` endpoints.
- **Measure** the first-run upsert of 100k synthetic streams on the test container, and record it in the
  PR body.

**Break-checks.**

- Drop `PARSER_VERSION` from the fingerprint. The "version bump re-classifies" test reddens.
- Read freshness from `stream_stats_updated_at` instead of `resolution_observed_at`. The
  merge-without-resolution test reddens.
- Drop the expiry selection. The TTL fall-back test reddens.

**PR description draft:**

> Classifies every live stream after an M3U refresh, behind the off-by-default `classify_enabled`
> setting: one `StreamClassification` row per stream, rebuilt only when its inputs change; quality
> tier from the name, overridden by a fresh relay-measured resolution and falling back when the
> measurement expires. Read-only admin API. Writes no channel. Measured first-run cost:
> <filled in>. Spec PR S3.

### S4 — identities, review queue, decisions and binding

**Changes.**

- The `identity` and `match_state` columns on `StreamClassification`.
- The models `ContentIdentity`, `IdentityMatch`, `StreamAssignment`, `StreamRegionPin`,
  `PairRejection` and `ChannelProposal`.
- `resolve_identities`, following § Identity resolution and § EPG binding.
- The S4 endpoints in § Admin UX. Proposals are computed and listed but **cannot be accepted until S6**.
- **Measure** the 300k-stream global run, and record it in the PR body.

**Break-checks.**

- Let the tvg_id pass ignore variant. The `+1` test reddens.
- Let pass 5 create an identity for a conflicted stream. The quarantine test reddens.
- Key assignments on `stream_hash`. The rehash-survival test reddens.
- Swap "release, then check" to "check, then release". The hand-off concurrency test reddens.

**PR description draft:**

> Groups classified streams across providers into region- and variant-scoped content identities:
> admin decisions (one assignment and one region pin per stream, plus pairwise rejections), exact
> tvg_id, exact key, and blocked, budgeted fuzzy candidates to a review queue. Region conflicts are
> review-only. Binds identities to EPG rows by a region-aware rule, lets the admin bind an identity
> to one channel, and lists proposals. Writes no channel. Spec PR S4.

### S5 — reliability

**Changes.**

- The `relay_event_applied` signal in `core/relay_events.py`. It is sent after each event is applied, and
  receiver exceptions are caught and logged, so a batch never 500s.
- The `StreamHealthEvent`, `StreamPlaySegment` and `StreamHealth` models.
- The receiver, and `fold_stream_health` with its beat entry.

**Break-checks.**

- Count `max_retries_exceeded` as a failure. The double-count test reddens.
- Drop `ignore_conflicts`. The duplicate-batch test reddens with an `IntegrityError`, or with a doubled
  count.
- Move the delete before the update, outside the transaction. The injected-failure test reddens.

**PR description draft:**

> Records per-stream reliability from the relay's events (failover away, connection failure,
> buffering, playback time) into an idempotent queue at ingest, and folds it every five minutes,
> transactionally, into a decayed failures-per-hour score and a band, with playback segments kept
> durably across folds. Nothing on the tune path changes; the query ledger is untouched. Needs S1's
> event fields. Spec PR S5.

### S6 — ordering and proposal acceptance

**Changes.**

- `Channel.stream_order_mode` and `ChannelStream.pinned`, in migration `0040`.
- `ChannelOrderSnapshot`.
- The D8 order function, and `reorder_channels` with D10's lock.
- The D10 lock on every writer listed there: serializer, bulk edit, the rehash merge with pin carry,
  accept, and restore.
- D7's flip-to-manual, with membership-only detection.
- `auto-order/preview|enable`, and snapshot restore (which sets manual).
- Proposal `accept` and `dismiss` (§ Admin UX, acceptance semantics).

**Break-checks.**

- Replace sort key 5 with the stream id. The non-id-tie test reddens, naming the moved streams.
- Remove the `manual` guard. The manual-untouched test reddens.
- Drop the lock from the serializer. The concurrency test reddens.
- Drop the pin carry in the merge. The source-only-pin test reddens.
- Let accept set `auto` unconditionally. The manual-target test reddens.

**PR description draft:**

> Orders each `auto` channel's streams best quality tier first, then by reliability band, with
> admin pins on top, so the relay's existing failover walks down in quality. Every existing channel
> starts `manual`; enabling auto-order goes through a preview and snapshots each channel's previous
> order; a reorder on an `auto` channel switches it to `manual` visibly, and a restore sticks. Every
> writer of the order, the rehash merge included, now takes one per-channel lock. Adds proposal
> acceptance, revision-checked and revalidated, which never changes an existing channel's ordering
> mode without the admin's say. The relay is unchanged. Spec PR S6.

### S7 — the Lineup page and the channel streams table

**Changes.** The § Admin UX items, except D16's form and the LLM settings. Vitest for the store and for
each new component.

**Break-checks.**

- Drop the flip-to-manual toast handling. The toast test reddens.
- Change the access-warning text to say "visible to every user". The dialog test reddens.

**PR description draft:**

> Adds the Lineup page (proposals, review queue, identities with channel and EPG binding, status and
> enablement) and tier, health, pin and order-mode controls on a channel's streams. Mantine and
> Zustand only. Spec PR S7.

### S8 — per-account naming conventions

**Changes.** D16 validation in the M3U account serializer, the form section, and the parse preview. The
golden `AR:` line.

**Break-checks.** Leave the convention out of `convention_version`. The "editing the convention
re-classifies only that account" test reddens.

**PR description draft:**

> Lets an admin teach the classifier a provider's naming convention per account (default region,
> region-token overrides such as `AR:` meaning Arabic, strip prefixes/suffixes, region-source
> order), with a live preview. Spec PR S8.

### S9 — optional LLM assist

This is security-adjacent, so the reviewer runs on `fable` from round one.

**Changes.** `apps/catalog/llm_payload.py` and `apps/catalog/llm.py` (§ LLM assist), the settings fields and
UI, and the queue badge.

**Break-checks.**

- Copy `parsed` from the stored classification instead of recomputing it. The whole-request property
  test reddens, naming a fixture secret in `parsed.canonical`.
- Remove the account-value step from the sanitiser. The whole-request test reddens on the bare
  username.
- Add `url` to the builder. The exact-key-set test reddens.
- Remove the cross-region drop. The D4 test reddens.

**PR description draft:**

> Optional, off by default, and inert without `MINO_CATALOG_LLM_API_KEY`: sends the streams the
> rules could not resolve to an LLM and shows its answers as suggestions in the review queue. Every
> outbound string is sanitised against URL, email and credential shapes and every known account
> value, any record that needed sanitising is dropped rather than sent, derived fields are recomputed
> from sanitised input, and the serialised request is checked once more before it leaves. It never
> merges anything itself. Spec PR S9.

## Non-goals

- **No active probing** of any provider (R1): no ffprobe, and no extra slot use.
- **No relay switch-policy change** (D9). Specifically, no climb-back to a higher tier while a lower one
  plays, and no "same tier before lower" for streams earlier in the current tier. If the owner later
  wants the second, the smallest change is Django-only: `order_alternates_from_current()` would rotate
  within the current stream's tier block before moving to lower blocks. It would need a parity-matrix
  row and an E2E pin of its own, and it is not designed here.
- **No ranking by bitrate, codec or measured fps** in this programme (Q3).
- **No channel preemption.** It stays unimplemented (CLAUDE.md § Known defects).
- **No change to auto channel sync**, including its orphan cleanup.
- **No change to any authorization filter.**
- **No VOD or catch-up classification.** Live streams only.

## Risks

- **A wrong deterministic merge serves the wrong region's feed.** This is mitigated structurally (D4, the
  conflict rule and quarantine) and by the trap tests. The residual case is a provider that labels an NZ
  feed `UK:` *and* gives it a `.uk` tvg_id, which no rule catches. The remedy is a region pin.
- **Order churn.** Mitigated by D8's explicit key 5 and by band-only ranking. S6 pins "a second pass
  writes nothing".
- **Stats volume.** S1 restores roughly one `Stream` write per running subprocess channel every 30 s,
  plus one at each change. That matches the Python relay's load before the cutover.
- **First classification of a large account** may take about a minute (§ Budget). It runs on Celery, after
  the refresh has reported its status.
- **The LLM sanitiser cannot know a secret it was not given.** A credential typed into a stream name
  that matches no account value and no pattern would be sent. This is why the feature is off by default,
  and why D14 drops changed records rather than redacting them.

## Open questions for the owner

- **Q1.** Should a separate issue be filed for M1, the Go relay never posting `stream_stats`, as a parity
  defect independent of this programme? S1 fixes it either way. A filed issue lets S1 carry
  `Closes #N`, and the metrics ledger record it.
- **Q2.** Where should `UNKNOWN` tier sort? D8 puts it between HD and SD. The alternative is last.
- **Q3.** Is bitrate a within-tier signal? Two FHD streams at 3 and 8 Mb/s rank only by reliability today.
- **Q4.** Should high-confidence LLM suggestions ever be accepted without a click, for example at a
  confidence of 0.95 or more with a same-region, same-variant match? D14 says never. R2's word "resolve"
  could be read either way.
- **Q5.** For `add_streams` into an auto-created channel, should "Detach from auto-sync" default to on?
  Off keeps today's sync behaviour. On keeps the merged channel when its origin provider drops the
  stream.
- **Q6.** Should D9's non-goal (tier-block rotation) be scheduled as a follow-up once S6 has run on real
  providers for a while?

## Appendix A — owner rulings (2026-10-31)

- **R1 Quality measurement: name + passive.** Parse quality hints from stream name and group
  (UHD/4K/FHD/HD/SD/HEVC/50fps/…), overridden by measured `Stream.stream_stats` captured during real
  playback. No active probing: no ffprobe, and no extra provider slot use.
- **R2 Identity matching: rules + optional LLM assist.** A deterministic core: normalise the name,
  extract the region from prefix, group and name, and match on tvg_id and EPG data. Fuzzy matches go
  to an admin review queue, and confirmed matches are remembered. An optional, off-by-default LLM may
  resolve ambiguous leftovers. It sends provider channel lists to an external API, so it must never
  send URLs or credentials and must be explicitly enabled.
- **R3 Automation: auto-order, propose new.** Existing served channels have their streams
  auto-reordered best quality first. New canonical channels are proposed for admin acceptance. Admin
  pins override everything.
- **R4 Ranking: quality tier, then reliability.** Order by quality tier, best first. Within a tier,
  order by observed health (recent failovers, buffering events and connect failures from relay events).

## Changelog

- 2026-10-31: first draft, at `149678aa` (head `09e4d103`).
- 2026-10-31: review round 1 (FAIL, 2 blocking, 13 should-fix, 1 nit). Each finding is addressed:
  - 1: the LLM payload (D14, § LLM assist).
  - 2: S1 stats by source generation, and per-resolution provenance (D15, § S1, § Quality tier).
  - 3: variant on every automatic path, and conflict quarantine (D4, § Region, § Identity resolution).
  - 4: region-aware EPG binding (§ EPG binding).
  - 5: phased parser, max-tier rule, group fallback, empty and oversized keys, and golden cases
    (§ Parsing).
  - 6: invalidation and the measured-tier pass (D6, § Quality tier).
  - 7: single-valued decisions (D5, § Data model).
  - 8: idempotent ingest and transactional fold with durable segments (D11, § Reliability, D15c).
  - 9: renewed lock, release-then-check hand-off, bounded fuzzy work (§ Identity resolution).
  - 10: explicit channel binding and acceptance semantics (D13, § Admin UX).
  - 11: mode preserved on accept; restore sets manual (D7, D13).
  - 12: rehash merge under the lock with pin carry (D10).
  - 13: PRs restaged, every stopping point standalone (§ The PRs).
  - 14: break-checks and Celery test setup (§ Test strategy, § The PRs).
  - 15: Channel Profile prose corrected (§ Settings and authorization, § Admin UX).
  - 16: M1 qualified, and refresh-tail failure behaviour stated accurately.
