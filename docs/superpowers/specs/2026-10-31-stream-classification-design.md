# Stream Classification and Quality-Ordered Failover

**Date:** 2026-10-31
**Status:** Draft
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
   overridden by measured `Stream.stream_stats` captured during real playback (R1). Nothing probes a
   provider.
4. **Order.** Each served channel's `ChannelStream.order` is set best tier first, then by observed
   reliability within a tier (R4). The relay's existing failover then walks down in quality. Existing
   channels are reordered automatically, new channels are proposed for admin acceptance, and admin pins
   override everything (R3).

The live relay is not redesigned. Its failover already reads `ChannelStream.order` (§ How the order
reaches the relay), so the whole policy can be expressed by writing that column off the tune path.
One small relay PR is needed, and it is a parity repair rather than new policy (§ S1).

Every PR below is a stopping point. After S3 the admin can see a tier per stream. After S6 the
headline behaviour exists for channels the admin already has. Widening scope is the main way this
fails.

## What was measured before this spec was written

| # | What | Result |
|---|---|---|
| M1 | **Who writes `Stream.stream_stats` today?** Every writer in the tree was grepped. | **Nobody, on the live path.** The only writer is `core/relay_events.py:113-159` (`_apply_stream_stats`), which runs when a relay posts an event of type `stream_stats` (`:203-208`). The Go relay never emits that type: `grep -rn '"stream_stats"' relay --include='*.go'` matches nothing outside comments and tests. The Python relay posted it from three sites (Phase 1 spec, lines 65-69 and 1418-1420: a periodic flush, a final flush on stop, and every parsed codec line), and `relay/control/events.go:97-100` still sizes its queue for "one stats flush per thirty seconds per channel". The Go relay parses the stats (`relay/channel/stats.go:30-48`, `reportInfo` at `:59`, `reportProgress` at `:101`) and serves them from memory on `GET /proxy/relay/channels` (`relay/httpapi/channels.go:91-116`), but never posts them. So since the stage 2d-3 flip put live traffic on the Go relay, `stream_stats` has only been frozen values from before it. R1's measured override has no input until S1 lands. |
| M2 | **Do relay events say which stream they are about?** The payloads of every `emit` call in `relay/channel/` were read. | **Mostly not.** `channel_start` carries `stream_id` (`relay/channel/manager.go:366-369`). `stream_switch` carries the **new** `stream_id` and nothing about the stream it left or why (`relay/channel/failover.go:288-291`). `channel_failover` (buffering only) carries `reason` and `duration` (`:335-338`). `channel_error` with `connection_failed` carries a redacted, truncated URL and `attempts` (`relay/channel/channel.go:604-608`). `channel_buffering` carries `speed` (`relay/channel/source_transcode.go:352`). `channel_stop` carries `runtime` and `total_bytes` (`relay/channel/channel.go:759-767`). Dead-air and connect-failure switches raise no `channel_failover` at all. The trigger is known inside the relay (`failover(ctx, why)`, `relay/channel/failover.go:190`, with `why` one of `health_monitor` at `channel.go:624`, `max_retries_exceeded` at `:635` and `buffering_timeout` at `failover.go:322`), but it is not put on the wire. Per-stream reliability cannot be attributed reliably from today's events. |
| M3 | **Can `SystemEvent` rows serve as the reliability history?** | **No.** `log_system_event` trims the table to `max_system_events`, default 100 (`core/utils.py:906-921`, `core/models.py:770`). That is minutes of history on a busy instance. |
| M4 | **Parser and fuzzy-match cost.** A throwaway prototype in the orchestrator's scratchpad (never in the repo): NFKC + casefold + one tokenising regex + dictionary lookups, over 100,000 synthetic names in eight conventions, on the planner's laptop (CPython 3.13.2). | Parse: **0.20 s** for 100k names (2.0 µs per name). SHA-1 fingerprint: **0.03 s** for 100k. `rapidfuzz==3.14.5` (the version `pyproject.toml:30` pins) `process.extract(..., scorer=token_sort_ratio, limit=5, score_cutoff=85)`: **3.09 s for 2,000 queries against 9,966 keys**, about 1.5 ms per query, unblocked. The prototype separated `UK: Sky Arts HD` (`sky arts`, GB) from `\|NZ\| Sky Arts HD` (`sky arts`, NZ), and gave `UK: Sky Sports Main Event FHD` and `SKY SPORTS MAIN EVENT UK HD` the same key and region. The production parser does more work per name, so budget ten times this. **Fuzzy matching must be blocked**: unblocked, 100k leftovers against 100k keys is on the order of 100k × 15 ms, about 25 minutes. |

**Not measured:** database write throughput for 100k classification rows (estimated in § Budget, to be
measured by S3 on the test container), and real provider name corpora (§ Test strategy says how the
corpus is built without one).

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
  written while a channel runs has two effects. It never moves the stream already playing, because
  nothing triggers a switch. It does take effect at that channel's **next** failover, because the
  failover query re-reads the order. The one exception is a **degraded** failover: when Django is
  unreachable the relay walks the alternates list it cached from the initial answer
  (`include_alternates`, `next_source.py:1063-1070`), in the order that held at channel start.
- **The switch goes to the next candidate, not to a chosen one.** The rotation picks the first stream
  after the current one that is not excluded, has a capacity-bearing profile and does not resolve to
  the URL already playing (`next_source.py:1098-1106`). On a list sorted best tier first, a failover
  from tier *T* tries the rest of tier *T* after the current stream, then every lower tier, and only
  then wraps to the higher tiers and the tier-*T* streams before the current one. The tried set
  shrinks to the current stream after a stable run (`noteStable`, `relay/channel/channel.go:727-736`,
  called on the stable-run reset at `:574`). So a channel that dropped a tier stays there until the
  lower stream itself fails. **Nothing climbs back up on its own.** § Decisions D9 keeps it that way for
  this programme.
- An operator switch (`Advance`, `relay/channel/advance.go:53`) and the three automatic triggers all
  reach `applySwitch` (`failover.go:262`), which raises `stream_switch`.
- The tune path's queries are pinned by `apps/proxy/tests/test_tune_path_query_ledger.py`
  (`TunePathQueryLedgerTests`, `:189`). Nothing in this spec may add a query there, and that test is
  the proof.

### What writes `ChannelStream.order` today

- The channel serializer's update rewrites the whole list from the request, as `enumerate` positions
  (`apps/channels/serializers.py:700-729`). The bulk channel edit does the same
  (`apps/channels/api_views.py:1460-1489`). The frontend's drag reorder sends the full list through a
  `PATCH` (`frontend/src/api.js:737-756`, called from `frontend/src/components/tables/ChannelTableStreams.jsx`).
- Auto channel sync creates **one channel per stream** at `order=0` (`apps/m3u/tasks.py:2814-2823`).
  Auto-created channels hold one stream unless an admin adds more. Sync never removes a foreign
  stream from an auto-created channel. It **deletes** an auto-created channel once no stream from its
  own account remains on it, in the default `orphan_channel_cleanup` mode `always`
  (`apps/m3u/tasks.py:3010-3037`).
- `bulk_create_channels_from_streams` (`apps/channels/tasks.py:3399`) writes `order=0` rows
  (`:3617`). The rehash merge keeps the lower order when two streams collapse into one
  (`core/tasks.py:719-740`).
- Nothing takes a lock around a reorder. Two writers race last-writer-wins.

### Streams, accounts, groups and EPG

- `Stream` (`apps/channels/models.py:59-158`): `name` (512), `tvg_id`, `channel_group` (FK; `ChannelGroup.name`
  is globally unique, `:38-39`, so one group row is shared by every account that uses the title),
  `stream_hash` (unique, `:96-102`), `stream_id` (the provider's XC id, stable across credential
  changes, `:116-121`), `stream_stats` and `stream_stats_updated_at` (`:130-140`), `is_adult`,
  `is_stale`, `custom_properties`.
- `stream_hash` comes from `Stream.generate_hash_key` (`:163-190`). For XC accounts it uses
  `stream_id` in place of the URL. The hash keys are configurable, so the same row can get a new
  hash when its name changes. **A remembered decision cannot be keyed on `stream_hash` alone.**
- The refresh pipeline: `refresh_single_m3u_account` (`apps/m3u/tasks.py:3413-3414`,
  `time_limit=3600`). Its tail runs `cleanup_streams` (`:3897`), then `sync_auto_channels`
  (`:3907`, defined at `:2058`), then `rollup_channel_catchup_fields` (`:3942`). Each runs in its own
  `try`, so a failure there does not fail the refresh. Batch processing uses `BATCH_SIZE = 1500`
  (`:41`) with `bulk_create`/`bulk_update` per batch (`:1278-1286`, `:1498-1502`).
- `M3UAccount.priority` exists (`apps/m3u/models.py:101-104`) but is documented and used only for
  VOD provider selection (`apps/output/views.py:1245`, `:1261`, `:1517`, `:1732`).
  `M3UAccount.custom_properties` is a free JSON dict (`:92`).
- EPG: `EPGData(tvg_id, name, epg_source)`, `unique_together = ('tvg_id', 'epg_source')`
  (`apps/epg/models.py:156-169`). `EPGSource` has `custom_properties` and `priority`.
- An EPG matcher exists already: `apps/channels/epg_matching.py`. It has `normalize_name()` (`:102-166`),
  which strips `hd`/`uhd`/`1080p` and friends (`COMMON_EXTRANEOUS_WORDS`, `:27-32`). It has a single
  instance-wide `preferred_region` (`core/models.py:601-602`, `get_preferred_region_code`
  `epg_matching.py:428-433`), used as a ±15 fuzzy bonus on `.xx` tvg_id suffixes (`:211-224`). It also has
  an optional sentence-transformer model (`:64-99`). It matches **channels** to EPG rows, not streams to
  each other, and its normaliser discards exactly the quality tokens this spec needs to keep. It is
  reused for EPG binding of accepted channels (unchanged), and its normaliser is **not** reused for
  identity keys (D3).

### Events and stats

- The relay batches events to `POST /api/relay/events` (`relay/control/events.go:40-53`, at most 200 per
  batch, order preserved, fire-and-forget). The wire `Event` has no timestamp (`:31-38`), so Django
  dates an event when it receives it.
- `core/relay_events.py:apply_event_batch` (`:185-265`) routes `stream_stats` to `_apply_stream_stats`
  and every other known type to `log_system_event`. Three types are also pushed over the WebSocket,
  restricted to the `_WS_FIELDS` whitelist (`:28-37`, `:90-110`). A new detail key reaches Connect
  webhooks and the `SystemEvent.details` JSON, but not the WebSocket unless it is added to the whitelist.
- Measured stats exist only for the subprocess architecture (FFmpeg, VLC, Streamlink). The Proxy
  and Redirect profiles have no stderr and report nothing (parity-matrix row 29). **A stream played only
  through Proxy is never measured, and keeps its name-derived tier forever.**

### Settings

- `CoreSettings` is one row per group, all instance-wide (CLAUDE.md § State). Defaults live in
  each group's getter (`get_system_settings`, `core/models.py:766-775`, through `_get_group` at `:398`). A new group is shared state that the
  E2E allowlists must know about (`docs/adr/0003`).

## Decisions

| | Decision | Why |
|---|---|---|
| **D1** | **A new Django app, `apps/catalog`.** It owns the parser, the classification, identity and health tables, the Celery tasks and the admin API. `apps/channels` gains only two columns on existing tables (D7). The name is neutral, per `CONTEXT.md` § Mino. | `apps/channels` is already 17,579 lines and sits at the centre of the import mesh's one cycle (CLAUDE.md § Structural constraints). The new app imports `channels`, `m3u` and `epg`. **None of them may import `catalog` at module level.** In particular `apps/channels/models.py` must not, because of the boot trap. Catalog code reaches channels models by string FK (`"dispatcharr_channels.Stream"`; the label, not the directory) and imports them function-locally in tasks. |
| **D2** | **Classification lives in side tables, never on `Stream`.** `StreamClassification` is one-to-one with `Stream` (primary key = `stream_id`, `on_delete=CASCADE`). | The refresh writes `Stream` in bulk with a fixed field list (`_bulk_update_stream_refresh_batches`, `apps/m3u/tasks.py:1080-1089`). Adding columns there would widen every refresh write, and a classification bug could then corrupt ingest. A side table can be truncated and rebuilt from `Stream` at any time. It is derived state, except for D5's decisions. |
| **D3** | **A purpose-built, versioned parser, `apps/catalog/parse.py`**: pure functions, no ORM, no settings reads inside. The input is `(name, group_title, tvg_id, convention)`. The output is a frozen dataclass `Parsed(canonical_name, canonical_key, region, region_evidence, name_tier, codec_hint, fps_hint, markers, variant)`. `PARSER_VERSION` is an integer bumped on any behaviour change. | The existing `normalize_name` reads settings and drops the tokens this spec classifies. A pure parser can be golden-tested and property-tested, and benchmarked without a database. The version is part of the fingerprint (D6), so a parser change reclassifies everything once and then goes quiet. |
| **D4** | **An identity is `(canonical_key, region, variant)`, and region is part of identity, never a tiebreak.** `variant` holds feed-distinguishing markers that are not quality: `+1` / `+2` (timeshift feeds), `east` / `west`, and numbered feeds are already in the name. An identity with **unknown** region (`""`) never auto-merges with a known-region identity. It can join one only through an exact tvg_id match whose tvg_id carries the region, or through an admin decision. | This is the UK/NZ trap, structurally. "Sky Arts" GB and "Sky Arts" NZ have equal keys and different regions, so they are different identities by construction, not by a threshold. `+1` is a different feed an hour behind, not a worse copy, so ordering it under the live feed would be wrong. |
| **D5** | **Admin decisions are remembered in `CatalogDecision`, keyed by a stable stream key**: `xc:<account_id>:<stream_id>` when the provider gives an id, else `m3u:<account_id>:<sha1(normalised name, group title, tvg_id)>`. Verdicts: `confirm` (stream belongs to identity), `reject` (never propose this pairing again), `region` (pin the stream's region), `exclude` (never classify into any identity). | `stream_hash` changes when a hashed field changes (§ Verified facts), and the rehash task merges rows (`core/tasks.py:719`). A key derived from the provider's own id survives both. For plain M3U there is no provider id, so the decision is tied to what the admin actually saw. If the provider renames the stream, the decision stops applying and the stream returns to the queue. That is the correct outcome. |
| **D6** | **Classification is incremental through a fingerprint.** `StreamClassification.fingerprint = sha1(PARSER_VERSION, convention_version(account), name, group title, tvg_id)`. A stream whose fingerprint is unchanged is not re-parsed. Measured tier is a separate cheap pass over streams with `stream_stats_updated_at > classification.measured_at`. | M4: parsing is cheap, but upserting 100k rows on every refresh is not. A steady-state refresh changes a few percent of names. |
| **D7** | **Ordering control is two new columns on existing tables**: `Channel.stream_order_mode` (`auto` / `manual`, default `manual`) and `ChannelStream.pinned` (bool, default false). Under `auto`, pinned streams keep their relative admin order at the top, and every other stream is placed by D8. Under `manual` nothing in this spec writes the channel's order. **An admin reorder (any `PATCH` that changes the order) of an `auto` channel switches it to `manual`.** The response says so, and the UI shows the badge and a one-click "back to Auto". | R3 says admin pins override everything. The rule "never destroy an admin's manual ordering silently" is met two ways. Every existing channel starts `manual`, and the owner turns `auto` on through the enablement flow (D12). A later drag is never overwritten either, because it flips the channel to `manual` visibly. That is preferable to a background task quietly undoing the drag an hour later. |
| **D8** | **The ordering function.** The sort key for unpinned streams on an `auto` channel is: (1) **effective tier**, best first: `UHD > FHD > HD > UNKNOWN > SD`; (2) **health band**, with hysteresis (§ Reliability); (3) `backup` marker last; (4) `fps_hint` descending; (5) the stream's **current** position (a stable sort, so ties never churn). Inactive accounts and streams marked `is_stale` sort last. The whole order is written in one transaction (D10). | R4: tier, then reliability. `UNKNOWN` sits above `SD` and below `HD` because an unlabelled provider stream is more often 720p or 1080p than 576i. Q2 asks the owner to confirm. Without the stable final key a reorder pass would permute ties on every run, and every failover would then see a different list. |
| **D9** | **The relay's switch policy does not change.** The failover keeps "the next candidate after the current one, wrapping" (`order_alternates_from_current`). On a tier-sorted list that already walks down in quality, and it wraps back up to the top tier only once the lower ones are exhausted. **No climb-back** (returning to a higher tier while a lower one still plays) and **no same-tier-before-lower preference** for the streams *before* the current one in its own tier. Both are recorded as non-goals, with the minimal Django-only change that would provide the second (§ Non-goals). | A switch-policy change is a live-path behaviour change. It needs a parity-matrix row and a pinned E2E, and the owner did not ask for one. The headline behaviour, best first and down in quality on failure, follows from the order alone. |
| **D10** | **Reorders are written under a row lock, with compare-and-set.** The reorder task opens a transaction, takes `select_for_update()` on the `Channel` row, re-reads the channel's `ChannelStream` rows and `stream_order_mode`, computes D8, and writes only rows whose `order` differs. The serializer update (`apps/channels/serializers.py:700-729`) and the bulk edit (`api_views.py:1460-1489`) take the same lock before rewriting the order. | Without it the reorder task and an admin drag race last-writer-wins, and a drag could be lost silently. The lock is per channel and held for milliseconds. Neither writer is on the tune path. |
| **D11** | **Reliability is recorded at event ingest and folded off-path.** `apply_event_batch` sends a Django signal, `relay_event_applied`, defined in `core/relay_events.py`. `apps/catalog` connects a receiver in its `AppConfig.ready()` that appends one `StreamHealthEvent` row per relevant event. Every five minutes a beat task (`fold_stream_health`) folds the queue into `StreamHealth` with exponential decay and deletes what it folded. | The tune path is untouched (the ledger test proves it). The event route is already the relay's fire-and-forget channel, and it already writes one `SystemEvent` per event. A signal keeps `core` from importing `catalog`, so no new edge goes into the mesh. `SystemEvent` cannot be the history (M3). |
| **D12** | **Everything is off until the owner turns it on, in three switches**, in a new settings group `catalog_settings`: `classify_enabled` (parse, tier, identities, review queue; read-only with respect to channels), `auto_order_enabled` (D8 writes for `auto` channels), and `llm_enabled` (D14). Turning `auto_order_enabled` on goes through a **preview** endpoint. The preview lists every channel whose order would change, and the owner picks which channels to set to `auto` (all, those with ≥ 2 streams, or a selection). Before the first write, each such channel's prior order is saved in `ChannelOrderSnapshot`, so "restore previous order" is one click. | R3 asks for automatic reordering of existing channels. The no-silent-destruction rule asks for it to be visible and reversible. One preview plus snapshot meets both without a per-channel prompt for every refresh. |
| **D13** | **New channels and new members are proposals, never automatic.** A `ChannelProposal` has `kind` `new_channel` (an identity with no bound channel) or `add_streams` (an identity whose bound channel lacks some of its streams). Accepting a proposal creates or edits the channel, sets it `auto`, and runs D8 once. A channel is **bound** to an identity when an admin accepts a proposal for it, or when more than half of the channel's streams classify to that identity (computed, never stored, until an admin confirms it). | R3: propose new, admin accepts. Adding a stream to a channel changes what clients may receive, so it is a membership change, not an ordering one, and it needs acceptance too. |
| **D14** | **The LLM assist is a suggestion source for the review queue, never a writer.** It runs only when `llm_enabled` is true **and** `MINO_CATALOG_LLM_API_KEY` is set in the environment. The key is never stored in the database or returned by any API. It sees only streams left unresolved after the deterministic and fuzzy passes, capped at `llm_max_streams_per_run` (default 500). What it returns becomes `IdentityMatch` rows with `source=llm` and a confidence, shown in the queue as suggestions. It never merges across a known region. The exact payload is fixed in § LLM assist. It is sent over plain `requests` (already a dependency), so **no SDK dependency is added**. | R2 makes it optional and off by default, and requires redaction. A key in a settings group would be one more plaintext secret (CLAUDE.md § Security lists the ones already there) and would travel with every settings export. Keeping its output inside the queue means a wrong answer costs one click, not a merged UK/NZ channel. |
| **D15** | **The Go relay changes in one PR (S1), and only to report.** It posts `stream_stats` again at the Python cadence. It adds the attributed stream to the events that lack it: `stream_switch` gains `from_stream_id` and `trigger`, and `channel_buffering`, `channel_error` (`connection_failed`) and `channel_stop` gain the `stream_id` playing when they fire. No decision the relay makes changes. | M1 and M2. Without S1, R1's measured override and R4's reliability signal have no input. S1 restores a Python behaviour the cutover dropped (the stats) and adds additive keys to payloads Django already accepts as free-form `details`. |
| **D16** | **Naming-convention overrides live per account** in `M3UAccount.custom_properties["catalog"]`, a validated sub-dict: `default_region`, `region_tokens` (token → ISO code or `null` to ignore, e.g. `{"AR": null}` where the provider's `AR:` means Arabic, not Argentina), `strip_prefixes`/`strip_suffixes` (literal strings), and `region_from` (an ordered subset of `["tvg_id", "prefix", "suffix", "group", "default"]`). `convention_version` is a hash of that sub-dict, so editing it reclassifies only that account (D6). | Conventions are per provider, so the owner fixes them where the provider is configured. The sub-dict needs no migration, follows the account's existing JSON pattern, and is validated by a serializer, so a typo is a 400, not a silent no-op. |

## Data model (S3, S4, S5, S6)

All new tables are in `apps/catalog`. Field names are final unless the plan finds a collision.

**`StreamClassification`** (S3), one-to-one with `Stream`, primary key `stream`:

| Field | Type | Notes |
|---|---|---|
| `stream` | OneToOne → `dispatcharr_channels.Stream`, PK, CASCADE | |
| `fingerprint` | char(40), indexed | D6 |
| `canonical_name` | char(255) | display form, e.g. `Sky Sports Main Event` |
| `canonical_key` | char(255), indexed | match form, e.g. `sky sports main event` |
| `region` | char(2), indexed | ISO 3166-1 alpha-2, `""` = unknown |
| `region_evidence` | char(16) | which rule set it (§ Region) |
| `region_conflict` | bool | two strong sources disagreed |
| `variant` | char(16) | `""`, `+1`, `east`, … |
| `name_tier` / `measured_tier` / `effective_tier` | small int | `0` UNKNOWN, `1` SD, `2` HD, `3` FHD, `4` UHD; sort rank is D8's, not the integer |
| `tier_source` | char(8) | `name` / `measured` |
| `codec_hint`, `fps_hint`, `markers` | char / small int / JSON list | |
| `measured_at` | datetime null | `stream_stats_updated_at` the measured tier was read from |
| `identity` | FK → `ContentIdentity`, null, SET_NULL, indexed | |
| `match_state` | char(12) | `auto_tvg`, `auto_key`, `confirmed`, `proposed`, `unmatched`, `excluded` |
| `classified_at` | datetime | |

**`ContentIdentity`** (S4): `canonical_name`, `canonical_key`, `region`, `variant`,
`unique(canonical_key, region, variant)`; `tvg_id` (most common non-empty tvg_id among members);
`epg_data` (FK `epg.EPGData`, null, SET_NULL, from an exact tvg_id lookup only); `channel` (FK
`dispatcharr_channels.Channel`, null, SET_NULL; the bound channel, D13); `created_at`.

**`IdentityMatch`** (S4), the review queue: `stream` (FK), `identity` (FK), `source`
(`fuzzy` / `region_conflict` / `unknown_region` / `llm`), `score` (0-100), `state` (`open` /
`accepted` / `rejected`), `created_at`; `unique(stream, identity)`.

**`CatalogDecision`** (S4): `stream_key` (char, D5), `account` (FK `m3u.M3UAccount`, CASCADE),
`verdict` (`confirm` / `reject` / `region` / `exclude`), `identity` (FK, null, CASCADE; null for `exclude` and
`region`), `region` (char(2), for `region`), `decided_by` (FK user, SET_NULL), `decided_at`;
`unique(stream_key, verdict, identity)`.

**`ChannelProposal`** (S4): `identity` (FK), `kind` (`new_channel` / `add_streams`), `channel` (FK,
null), `stream_ids` (JSON list), `state` (`open` / `accepted` / `dismissed`), `created_at`, `decided_at`.
At most one `open` proposal per `(identity, kind)`. A re-scan updates it in place.

**`StreamHealthEvent`** (S5), an append-only queue: `stream_id` (int, indexed, **no FK**, because a
stream deleted between ingest and fold must not fail the insert), `channel_uuid`, `kind`
(`start` / `switch_in` / `switch_out` / `stop` / `failure` / `buffering`), `trigger` (char), `at`
(datetime, receipt time), `weight` (float).

**`StreamHealth`** (S5), one-to-one with `Stream`, CASCADE: `failures_decayed` (float),
`exposure_s_decayed` (float), `decayed_at` (datetime), `rate` (float, the smoothed failures per hour),
`band` (`good` / `fair` / `poor` / `unknown`), and raw lifetime counters for display (`failovers`,
`connect_failures`, `buffering_episodes`, `play_seconds`).

**`ChannelOrderSnapshot`** (S6): `channel` (FK, CASCADE), `stream_ids` (JSON list, in order),
`reason` (`enable_auto` / `accept_proposal`), `created_at`. The last five per channel are kept.

**On existing tables** (S6, D7): `Channel.stream_order_mode` (char(8), default `"manual"`) and
`ChannelStream.pinned` (bool, default `False`). Both have defaults, so the migration needs no data
pass. They land in `apps/channels/migrations/0040_*` (the current tip is
`0039_channel_hls_output_profile.py`). The plan must re-check that number at its seed.

## Parsing (S2)

**Tokenising.** NFKC, casefold, `&` → ` and `. Split on whitespace and the separators
`| [ ] ( ) : - _ /` and `·`. Keep `+1`/`+2` as single tokens. A bracketed group such as `[US]`,
`(UK)` or `|NZ|` is a region candidate in the position it occupies.

**Token classes, in order.** Each token is classified once:

| Class | Tokens (case-folded) | Effect |
|---|---|---|
| tier | `8k`, `4k`, `uhd`, `2160p` → UHD; `fhd`, `fullhd`, `full hd`, `1080p`, `1080i` → FHD; `hd`, `720p` → HD; `sd`, `576p`, `576i`, `480p`, `lq` → SD | first one wins; removed from the key |
| codec | `hevc`, `h265`, `x265` → hevc; `h264`, `avc` → h264 | hint only; removed |
| fps | `\d{2,3}fps`, `50p`, `60p` | hint only; removed |
| marker | `backup`, `bk`, `raw`, `alt`, `test` | kept in `markers`; removed |
| variant | `+1`, `+2`, `east`, `west` | kept in `variant`; removed from the key and part of identity (D4) |
| region | a token in the region table (§ Region) at a **prefix or suffix position** | region evidence; removed from the key |
| noise | the account's `strip_prefixes`/`strip_suffixes`, and pure-punctuation tokens | removed |
| word | everything else | kept, in order |

**Number words.** The standalone tokens `one` … `ten` are mapped to `1` … `10` in the key only, so `BBC One`
and `BBC 1` share a key and the display name keeps the provider's spelling. Nothing else is
aliased: no stemming, and `sport` ≠ `sports`. The cost of a missed alias is one review-queue row. The
cost of a wrong alias is a merged feed.

**Display name.** The canonical name is the remaining words in the most common original casing
among the identity's members, so `SKY SPORTS MAIN EVENT` does not win over `Sky Sports Main Event`.

## Region

**The region table** maps tokens to ISO 3166-1 alpha-2 codes: two-letter codes, a curated alias set
(`uk` → GB, `usa` → US, `nz` → NZ, `aus` → AU, …) and full country names in English (`new zealand`,
`united kingdom`). Tokens that are also language codes or ambiguous are deliberately **absent** from
the default table and need an account-level `region_tokens` entry to count: `ar` (Arabic or
Argentina), `en`, `lat`/`latino`, `int`, `es` (Spanish or Spain), `pt`. A position rule applies as
well. A region token counts only in the first two or the last two token positions, so
`Discovery Turbo UK` counts but `UK Gold Classics Movies` mid-name does not.

**Evidence, strongest first.** The first source that gives a region sets it, and `region_evidence`
records which one:

1. `decision`: a `CatalogDecision` with verdict `region` for this stream key.
2. `tvg_id`: the final dot-segment of `tvg_id` is a region-table token (`SkyArts.nz`,
   `BBCOne.uk`). This is strong because EPG providers key on it.
3. `epg_source`: `tvg_id` resolves to an `EPGData` row whose `EPGSource.custom_properties["region"]`
   is set. That is an optional per-EPG-source field, with an input on the EPG form in S7.
4. `prefix` / `suffix`: a region token in the name, in an allowed position.
5. `group`: a region token or country name in the group title (`UK | Sports`, `NEW ZEALAND`).
6. `default`: the account's `default_region` (D16).
7. none: `""`.

The account's `region_from` may reorder or drop sources 2 and 4-6, but never 1. **Conflict rule:** if
sources 2, 3 and 4 give two different regions, the stream gets the strongest one, `region_conflict = true`,
and **no automatic identity match**. It goes to the queue as `region_conflict`. The "UK" prefix
on an NZ-tvg_id stream is exactly the provider mistake that would otherwise merge two Sky Arts feeds.

## Quality tier (S3)

- **Name tier**: from the parser.
- **Measured tier**: from `Stream.stream_stats["resolution"]` (`"WxH"`; the key Python stored and S1
  restores), by the **height**: ≥ 2000 → UHD, ≥ 1000 → FHD (1080i counts; interlace is not a tier),
  ≥ 700 → HD, otherwise SD. It is used only when `stream_stats_updated_at` is within `measured_ttl_days`
  (default 30) and S1's emitter wrote it (`stream_stats` carries `relay: "go"`, see § S1). That guard
  keeps the stale pre-cutover values M1 describes from overriding anything.
- **Effective tier**: measured if present and fresh, else name. `tier_source` records which.
- `video_bitrate` and `source_fps` from the same stats are displayed but not used to rank in this
  programme (Q3).

## Identity resolution (S4)

Runs **globally** (across accounts) after classification, under one task lock
(`acquire_task_lock("catalog_resolve", 0)`, `core/utils.py:296`). If the lock is held, the run sets a
"rerun" flag and returns, and the holder re-runs once at the end, so concurrent refreshes coalesce
into at most two passes.

Passes, in order. Each pass considers only streams the earlier passes left unresolved, and a stream
with `exclude` or `region_conflict` skips passes 2 and 3:

1. **Decisions.** `confirm` binds the stream to its identity. `exclude` sets `excluded`.
2. **Exact tvg_id.** Streams with the same non-empty case-folded tvg_id, and regions that are equal or
   unknown-plus-tvg_id-carries-region, join one identity (`auto_tvg`). Two members with the same
   tvg_id and **different known regions** are not merged. Both go to the queue as `region_conflict`.
3. **Exact key.** Same `(canonical_key, region, variant)` with a known region → one identity
   (`auto_key`). An unknown region never auto-matches on key alone (D4). Such a stream goes to the queue
   as `unknown_region` against the best same-key candidate.
4. **Fuzzy, blocked.** Each remaining stream is compared only within its block, which is identities
   with the same region (or every region when the stream's is unknown) and the same first key token.
   The scorer is `rapidfuzz` `token_sort_ratio` with `score_cutoff = fuzzy_threshold` (default 90),
   and at most three candidates are kept. The candidates become `IdentityMatch(source=fuzzy)`. **Fuzzy
   never binds.**
5. **New identity.** A stream still unresolved with a known region and no candidate creates its own
   identity (`auto_key`). With an unknown region it stays `unmatched`.
6. **LLM** (only under D14's conditions): see § LLM assist.

A `reject` decision suppresses the matching `IdentityMatch` forever. **Proposals** are
recomputed for every identity whose membership changed in this run (D13).

## Reliability (S5)

**Ingest.** In the `relay_event_applied` receiver, after S1:

| Event | Row(s) appended | Weight |
|---|---|---|
| `channel_start` (`stream_id`) | `start` | — |
| `stream_switch` (`from_stream_id`, `stream_id`, `trigger`) | `switch_out` for `from_stream_id`, `switch_in` for `stream_id`; if `trigger` is `health_monitor` or `buffering_timeout`, also `failure` for `from_stream_id` | 1.0 |
| `channel_error` with `error_type = connection_failed` (`stream_id`) | `failure` | 1.0 |
| `channel_buffering` (`stream_id`) | `buffering` | 0.25 |
| `channel_stop` (`stream_id`) | `stop` | — |

`max_retries_exceeded` switches are **not** counted as a failure, because the `connection_failed` error that
precedes them already was. Operator switches (`trigger = operator`) count only as exposure
boundaries. Events without the S1 fields (a relay older than S1) append nothing. The receiver
does one `INSERT` per relevant event, inside the request that already writes one `SystemEvent` per event.

**Fold** (beat, every 5 min, under its own task lock). Rows are read in id order per channel. Exposure
for a stream is the time between its `start`/`switch_in` and the next `switch_out`/`stop` on the same
channel. A segment left open more than 24 h is closed at its last known event and is not credited.
Then, for each touched stream:

```
d                 = 2 ** (-(now - decayed_at) / half_life)        # half_life = health_half_life_days, default 7
failures_decayed  = failures_decayed  * d + Σ weight
exposure_s_decayed = exposure_s_decayed * d + Σ segment seconds
rate              = (failures_decayed + 0.5) / (exposure_s_decayed / 3600 + 1.0)   # failures per playback hour, smoothed
band              = unknown if exposure_s_decayed < 900
                    else good if rate < 0.1 else fair if rate < 0.5 else poor
```

The smoothing constants (0.5 failures, 1 hour) give an unplayed stream a rate of 0.5/h. That is the
fair/poor boundary, so it ranks below any stream that has proven itself and above one that has proven bad.
The folded rows are deleted. The deriving formula lives in `apps/catalog/health.py`, beside its constants,
and the S5 tests pin the formula, not the numbers.

**Hysteresis in D8.** Within a tier, two unpinned streams change relative order only when their bands
differ. Inside a band they keep their current relative order. A stream's rate changing within its
band therefore never moves it, and the order changes only when a stream crosses a band edge.

## When things run (S3-S6)

| Task | Trigger | Scope | Lock |
|---|---|---|---|
| `classify_account_streams(account_id)` | `.delay()` from the refresh tail, after `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:3942`), in its own `try`, only if `classify_enabled` | that account's non-stale live streams, fingerprint-changed only (D6), plus the measured-tier pass | per account |
| `resolve_identities()` | chained at the end of the above; also from the admin "re-run" button | global (§ Identity resolution) | global, coalescing |
| `fold_stream_health()` | beat, every 5 min | queued health events | global |
| `reorder_channels(channel_ids=None)` | chained after `resolve_identities` (channels whose members' tiers changed) and after `fold_stream_health` (channels whose members changed band); hourly beat as a backstop; only if `auto_order_enabled` | `auto` channels only | per channel row lock (D10) |

A failure in any of them is logged and leaves the previous state in place. None of them is called
from a request on the tune path, and none of them raises into the refresh task.

**Budget, 100k streams in one account.** From M4, with a 10× allowance: parse ~2 s and fingerprint
~0.3 s. Reading the rows with `.only(...)` and `.iterator(chunk_size=2000)`: estimate 5-10 s. On a first
run, upserting 100k `StreamClassification` rows (`bulk_create(update_conflicts=True)`, batches of 1000):
estimate 20-60 s, **to be measured in S3 on the test container and recorded in its PR body**. A steady-state
refresh touches the changed few percent. Resolution: passes 1-3 are dictionary lookups, O(n).
Fuzzy pass 4 is ~1.5 ms per stream against a 10k-key block (M4), much less in a realistic
region-and-first-token block. 10k unresolved streams cost on the order of 15 s worst case. Memory: one
account's parse results at ~300 bytes each is ~30 MB at 100k, processed per `BATCH_SIZE` chunk. All of this
runs on the Celery `default` worker, never in uWSGI.

## LLM assist (S9)

Off by default (D12, D14). When it runs, it handles streams still `unmatched`, or with an open
`IdentityMatch` whose best score is 70-90, at most `llm_max_streams_per_run` per run.

**Exactly what leaves the box**, per request (JSON):

```json
{"task": "match_streams_to_channels",
 "streams":    [{"ref": "s1", "name": "...", "group": "...", "tvg_id": "...",
                 "parsed": {"canonical": "...", "region": "GB|null", "variant": ""}}],
 "candidates": [{"ref": "i1", "name": "...", "region": "NZ", "tvg_id": "...", "epg_name": "..."}]}
```

- `name` is `Stream.name` after the redaction below. `group` is the group title. `tvg_id` is the
  stream's. `epg_name` is the bound `EPGData.name`.
- `ref` values are per-request opaque indices, mapped back locally. **No database id, `stream_id`,
  `stream_hash` or UUID is sent.**
- **Never sent:** `url`, `logo_url`, any account field (name, id, server URL, username, password,
  `custom_properties`), M3U profile data, channel UUIDs, user data, `stream_stats`, and EPG source
  name or URL.
- **Redaction applied to `name`, `group`, `tvg_id` and `epg_name`:** any substring matching a URL
  scheme (`[a-z][a-z0-9+.-]*://\S*`), `user:pass@host`, or an email address is removed. A field
  longer than 200 characters is truncated. The redaction is a single function, and a property test
  holds it (§ Test strategy).

**Response handling.** The expected shape is
`[{"ref": "s1", "candidate": "i1" | null, "region": "GB" | null, "confidence": 0..1}]`. It is validated by a
serializer, and anything else is dropped. A `candidate` whose region differs from the stream's known
region is dropped (D4). The survivors become `IdentityMatch(source=llm, score=confidence*100)`,
**never decisions**. A `region` suggestion for an unknown-region stream is shown as a suggested
region on its queue row.

**Transport.** One adapter, `apps/catalog/llm.py`, posting to the Anthropic Messages API with
`requests`. The model id is a setting (`llm_model`), defaulting to `claude-haiku-5-5`. The key comes
from `MINO_CATALOG_LLM_API_KEY`. Logging records counts and status codes only: never the request body,
the response body or the key. `scripts/check_credential_logging.py` runs on the file in the hook. The
settings UI shows "key present / absent", never the key.

## Admin UX (S7, S8, S9)

Mantine 8 only. State is in a new Zustand store, `frontend/src/store/catalog.jsx`. All HTTP goes through
new `API.*` methods in `frontend/src/api.js`. No new UI library and no direct fetch from components
(CLAUDE.md § Frontend).

- **New page `/catalog`, "Lineup"** (`frontend/src/pages/Catalog.jsx`, route in
  `frontend/src/App.jsx` next to `/channels` at `:152`, nav entry beside Channels), with four tabs:
  - *Proposals*: one row per open `ChannelProposal`. It shows the identity, region, kind, member streams with
    tier and provider, and the target channel for `add_streams`. Actions are Accept (a dialog for group, number,
    Channel Profiles and, for an auto-created target, D-note below), Dismiss, and bulk accept.
  - *Review*: open `IdentityMatch` rows, grouped by stream, with source badge (`fuzzy` /
    `region conflict` / `unknown region` / `LLM`), score, and both sides' name, group, tvg_id and region.
    Actions are Confirm, Reject, Set region, Exclude, and "New identity".
  - *Identities*: a searchable list. Opening one shows its members, ordered as D8 would order them,
    with tier, tier source, health band and provider.
  - *Status*: last run times, counts per state, the "Re-run" button, and the enablement switches with the
    D12 preview for `auto_order_enabled`.
- **Channel streams table** (`frontend/src/components/tables/ChannelTableStreams.jsx`): a tier badge
  (with "measured" or "from name"), a health-band dot, a pin toggle, a channel-level "Order: Auto / Manual"
  segmented control, and "Restore previous order" (from `ChannelOrderSnapshot`). After a drag on an
  `auto` channel the toast says the channel is now Manual (D7).
- **M3U account form** (`frontend/src/components/forms/M3U.jsx`): a "Naming convention" section for
  D16's fields, with a live preview that parses the account's first 50 stream names through
  `POST /api/catalog/parse-preview/`.
- **EPG source form** (`frontend/src/components/forms/EPG.jsx`): an optional Region select (§ Region,
  source 3).
- **Settings** (`frontend/src/pages/Settings.jsx`): a "Stream classification" section for the
  `catalog_settings` group, with the LLM key shown as present or absent.

**Note for auto-created channels.** Accepting an `add_streams` proposal whose target has
`auto_created = True` shows a warning. Under the account's default `orphan_channel_cleanup = always`,
auto sync will delete the channel once its own account's stream disappears, even though other
providers' streams remain (`apps/m3u/tasks.py:3018-3037`). The dialog offers "Detach from auto-sync"
(sets `auto_created = False`) as an explicit checkbox, off by default (Q5).

**API** (`apps/catalog/api_urls.py`, mounted at `/api/catalog/`). DRF serializers for every endpoint,
present in the drf-spectacular schema. All are **`IsAdmin`**, the REST default, with no opt-down.
Endpoints: `classifications/` (list, filter), `identities/` (list, retrieve), `matches/` (list; `POST
{id}/accept|reject`), `proposals/` (list; `POST {id}/accept|dismiss`), `decisions/` (list, create, delete),
`parse-preview/`, `run/`, `auto-order/preview/`, `auto-order/enable/`,
`channels/{id}/order-snapshots/` (list; `POST {snapshot_id}/restore`). The channel serializer gains
`stream_order_mode` and the nested `pinned`.

## Coexistence

- **Manual assignment.** It is untouched for `manual` channels, which every existing channel is (D7). For
  `auto` channels, a manual reorder flips the channel to `manual` (D7). Adding or removing a stream by hand keeps
  the mode, and the next reorder places the new stream.
- **Auto channel sync.** Sync still creates its one-stream channels. Classification classifies their
  streams like any others, and the identity they belong to is bound to them by D13's majority rule once an
  admin confirms. Sync never sees `stream_order_mode` or `pinned`, and reorders write only `order`, so
  sync's own writes (`apps/m3u/tasks.py:2545`, `:2812-2823`, `:2862`) do not conflict. A
  `new_channel` proposal is **not** raised for an identity whose only streams are already on an
  auto-created channel. An `add_streams` proposal against that channel is raised instead.
- **EPG matching.** It is unchanged. An accepted `new_channel` gets `tvg_id` and `epg_data` from the
  identity when set, and is otherwise left to the existing matcher (`match_epg_channels`,
  `apps/channels/tasks.py:233`).
- **Stream rehash and merge** (`core/tasks.py:719`). Classification follows the surviving `Stream` row and
  is re-derived by fingerprint. Decisions survive because they are keyed per D5.
- **Stale streams.** `is_stale` streams sort last (D8). Deleted streams cascade out of every catalog
  table except `StreamHealthEvent`, whose fold skips unknown ids.

## Known-defect interactions

- **Provider-slot counters (#513).** Nothing here touches `profile_connections:*` or
  `server_group_connections:*`. A tier-first order concentrates initial tunes on the best provider's
  slots. When those are full, `get_stream()` skips to the next stream (§ Verified facts), which is the
  intended fallback. No `INCR`/`DECR` is added anywhere.
- **The copied channel-authorization filter (eight functions).** This spec adds no client-facing listing
  surface. Every catalog endpoint is `IsAdmin`. A channel created by accepting a proposal is an ordinary
  `Channel`. Its `user_level` defaults to 0, it inherits `is_adult = any(member.is_adult)`, and its
  Channel Profile membership is chosen in the accept dialog. **A channel with no profile membership is
  visible to every user at its level** (`CONTEXT.md` § Profiles), and the dialog says so.
- **The boot trap.** No module that `apps/channels/models.py` imports gains an import (D1). The catalog's FKs
  to channels are string references.
- **CoreSettings blast radius.** `catalog_settings` is a new instance-wide group, a ninth beside the eight
  `*_SETTINGS_KEY` constants (`core/models.py:227-234`). Its defaults live in its getter, as
  `get_system_settings`'s do, so reads work with no row. `epg_settings` shows a `PATCH` can fail before
  the row exists (CLAUDE.md § State). **S3 ships a seeding data migration for the row** rather than
  rely on the API's create path. Any E2E test that writes it joins the allowlist (`docs/adr/0003`).
- **Credential logging.** The LLM adapter and the parse-preview endpoint are new places where provider
  names are handled. Neither logs a URL, and neither receives one.
- **Rename ratchet (Mino spec PR R1).** If R1 has landed, a new file containing the string `dispatcharr`
  (an import of the `dispatcharr` package, the Hypothesis profile name `dispatcharr-ci`, or the FK label
  `dispatcharr_channels`) raises `scripts/product_name_allowlist.txt`. The plan lists each such line, and it must be
  one of the names the rename spec keeps (C-9, C-10, C-13).

## Test strategy

- **Corpus.** `apps/catalog/tests/fixtures/stream_names.jsonl`, at least 400 lines of
  `{name, group, tvg_id, convention, expect: {canonical_key, region, variant, name_tier, markers}}`. It is
  synthetic but real-shaped: every convention in the § Goal examples; prefix, suffix and bracket regions;
  pipes, colons and dashes; ALL CAPS; trailing `FHD`, `HEVC` and `50FPS`; `(Backup)`, `RAW` and `+1`; group-only
  regions; tvg_id-only regions; and the ambiguous tokens (`AR:`, `EN`, `LAT`). It includes **the trap set**: for
  each of at least 20 brands present in two regions (Sky Arts GB/NZ, Sky News GB/NZ, ESPN US/AU,
  Discovery GB/US, Nickelodeon GB/US, …), five decorations per region. No real provider URL,
  account name or credential appears in it. A test asserts that no line contains `://`.
- **Golden tests** (S2): every corpus line parses to its `expect`. A changed expectation is a test
  modification and must be listed with before and after.
- **Property tests** (S2, Hypothesis, the shared `dispatcharr-ci` profile registered byte-identically):
  `parse` is idempotent on its own canonical name. Adding or removing any tier, codec, fps or marker token
  never changes `(canonical_key, region, variant)`. A region token never appears in `canonical_key`.
  **For any two names that differ only in a known region token and any decoration, the identity keys
  differ** (the trap, generalised). Re-ordering tier tokens never changes `name_tier`.
- **Resolution tests** (S4): a UK and an NZ stream with equal keys and equal tvg_id produce two
  identities and a `region_conflict` match, never one identity. An unknown-region stream never auto-binds
  by key. A `reject` decision survives a re-run and a rehash. Fuzzy never binds. Coalescing: a
  second call while locked runs exactly once more.
- **Ordering tests** (S6): D8's key on hand-built cases, including the stable tie (two runs, same input, no
  writes on the second). A `manual` channel is never written. A `PATCH` reorder on an `auto` channel
  flips it to `manual`. Under concurrent reorder and `PATCH` (two connections, Postgres-only), the
  `PATCH` wins. A snapshot is written before the first auto write and restore round-trips.
  `get_stream()` and the failover branch pick the tier-sorted first candidate. That one test drives
  `resolve_source` against a reordered channel and asserts the chosen `stream_id`.
- **Tune-path ledger:** `apps/proxy/tests/test_tune_path_query_ledger.py` must pass **unchanged** in
  every PR. A change to it is a finding.
- **Health tests** (S5): the fold formula with an injected clock. Attribution from a hand-built
  event sequence (start → switch(health_monitor) → stop). Events without S1 fields append nothing.
  `max_retries_exceeded` is not double-counted. An open segment older than 24 h is not credited.
- **LLM tests** (S9): a fake transport. The redaction function is property-tested so that, for any
  generated name containing a URL, credentials or email, the payload contains none of them. The payload's key
  set is asserted **exactly**, against an allowlist, so a field added later fails the test rather than leaking.
  Responses naming a cross-region candidate are dropped. With `llm_enabled` false, or the env var unset,
  no request is made: the fake asserts zero calls.
- **Go (S1):** see § S1.
- **Frontend:** vitest per new component and store, mocking `api.js` (the existing pattern).

**Break-checks**, one named wrong edit per PR, in each PR section below.

## The PRs

Branches are `feature/catalog-*`, except S1, which touches the live path and is named
`migration/catalog-s1-relay-events` so the full E2E matrix runs on it (CLAUDE.md § Full E2E runs). Every
PR description below names no closing keyword. A PR that fixes a filed issue gets `Closes #N.` in
its own implementation PR, never in this spec.

### S0 — this spec

Docs only. `Refs` the tracking issue, if one is filed.

### S1 — the relay reports which stream, and posts stream stats again (Go, parity)

**Changes.**
- `relay/channel/failover.go`: `failover()` passes `why` and the pre-switch stream id to
  `applySwitch`. `stream_switch` gains `from_stream_id` (int, omitted when 0) and `trigger`
  (`health_monitor` / `max_retries_exceeded` / `buffering_timeout` / `operator`). `advance.go`
  passes `operator`.
- `channel_buffering` (`source_transcode.go:352`), `channel_error` `connection_failed`
  (`channel.go:604`) and `channel_stop` (`channel.go:759`) gain `stream_id`, the stream current
  when they fire. Note that `emit` lifts `details["stream_id"]` to the top level (`events.go:39-41`).
  `channel_stop` builds its `Event` directly and must set both.
- **Stats emission**: a `stream_stats` event carrying the `Stats` fields under the Python key names
  (`video_codec`, `resolution`, `width`, `height`, `source_fps`, `pixel_format`, `video_bitrate`,
  `audio_codec`, `sample_rate`, `audio_channels`, `audio_bitrate`, `stream_type`,
  `ffmpeg_output_bitrate`) plus `relay: "go"` and `stream_id`. It is posted when `reportInfo` first fills or
  changes a codec field, every 30 s while the channel runs, and once on stop. That is the Python relay's three
  sites (M1), and subprocess architecture only (row 29 unchanged). `nil` fields are omitted, which
  `_apply_stream_stats` already treats as "keep" (`core/relay_events.py:139-141`).
- `docs/relay-parity-matrix.md`: two new rows. One for the stats emission and its cadence. One for the
  attribution fields, each with its Go test.
- `core/relay_events.py`: nothing, except a test that a `stream_stats` batch with `relay: "go"` is stored
  (the key is kept inside `stream_stats`, and § Quality tier relies on it).

**Tests.** `relay/channel/failover_test.go` asserts that each trigger produces `stream_switch` with the right
`from_stream_id` and `trigger`. `relay/channel/source_transcode_test.go` asserts that the captured stderr corpus produces
`stream_stats` with the expected keys, a 30 s flush under an injected clock, and a final flush on stop.
`relay/channel/source_proxy_test.go` asserts that the Proxy profile posts no `stream_stats`. Coverage is per the Phase 4 floor
rule (D20): the PR lists its uncovered statements, with at least 85% on its additions.

**Break-checks.** Drop `from_stream_id` from `applySwitch`: the failover test reddens, naming the missing key.
Post stats from the Proxy source: the Proxy test reddens.

**Overlap.** Mino rename G1 rewrites every Go import path. Whichever lands second rebases mechanically.

**PR description draft:**

> The Go relay stopped posting `stream_stats` when it took over live traffic: the Python relay
> posted it from three sites, the Go relay parses the same stats and serves them on
> `GET /proxy/relay/channels`, but never sends them to Django, so `Stream.stream_stats` has been
> frozen since the cutover. This restores the Python cadence (on codec change, every 30 s, on stop;
> subprocess profiles only) and adds the attributed stream to the events that lack it:
> `stream_switch` gains `from_stream_id` and `trigger`; `channel_buffering`, `channel_error`
> (`connection_failed`) and `channel_stop` gain `stream_id`. No relay decision changes. Two new
> parity-matrix rows. Spec: `docs/superpowers/specs/2026-10-31-stream-classification-design.md`, PR S1.

### S2 — the parser (pure, inert)

**Changes.** `apps/catalog/` app skeleton (`apps.py`, empty `models.py`, added to `INSTALLED_APPS`).
`parse.py` (D3), `regions.py` (the region table), and `conventions.py` (D16 validation and
`convention_version`). The corpus, golden tests and property tests. `CONTEXT.md` gains **Content
identity** and **Quality tier**. The plan must confirm that the new app's test label is picked up by
`dispatcharr/test_discovery.py` and by CI's label list (`FULL_SUITE=1 python3 scripts/ci_backend_test_labels.py`),
and add a `_PATH_ALIASES` entry if `apps/catalog/` needs one.

**Break-checks.** Remove `nz` from the region table: the trap property test reddens with two equal keys
for GB/NZ. Map `sport` to `sports`: a golden line for `|NZ| Sky Sport 1 HD` reddens.

**PR description draft:**

> Adds `apps/catalog` with a pure, versioned stream-name parser: canonical name and key, region
> with its evidence, tier/codec/fps hints, markers and feed variant. No models, no tasks, nothing
> runs yet. A 400-line real-shaped corpus (including a two-region brand trap set) is golden-tested,
> and Hypothesis properties pin that decorations never change identity and region never leaks into
> the key. Spec PR S2.

### S3 — classification and tiers

**Changes.** The `StreamClassification` model and migration. `classify_account_streams` (D6), dispatched from
the refresh tail behind `classify_enabled`. Measured tier (§ Quality tier). The `catalog_settings` getter
with defaults, and a data migration seeding its row. Read-only `classifications/` and `parse-preview/` endpoints. **Measure** the first-run
upsert of 100k synthetic streams on the test container and record it in the PR body.

**Break-checks.** Drop `PARSER_VERSION` from the fingerprint: the "version bump reclassifies" test
reddens. Accept stats without `relay: "go"`: the stale-stats test reddens.

**PR description draft:**

> Classifies every live stream after an M3U refresh, behind the off-by-default `classify_enabled`
> setting: one `StreamClassification` row per stream, rebuilt only when name, group, tvg_id,
> parser version or the account's convention change; quality tier from the name, overridden by
> fresh measured stats from the relay. Read-only admin API. Measured first-run cost: <filled in>.
> Spec PR S3.

### S4 — identities, the review queue and decisions

**Changes.** The `ContentIdentity`, `IdentityMatch`, `CatalogDecision` and `ChannelProposal` models.
`resolve_identities` (§ Identity resolution). The admin API for matches, decisions, proposals and identities.
Accepting a `new_channel` proposal creates the channel (one transaction; member `ChannelStream` rows in D8 order;
`stream_order_mode = auto`).

**Break-checks.** Allow an unknown-region stream to bind on key: the D4 test reddens. Key decisions on
`stream_hash`: the rehash-survival test reddens.

**PR description draft:**

> Groups classified streams across providers into region-scoped content identities: decisions,
> exact tvg_id, exact key, blocked fuzzy candidates to an admin review queue, remembered admin
> decisions keyed on the provider's own stream id. Proposes new channels and missing members;
> nothing is created without acceptance. Spec PR S4.

### S5 — reliability

**Changes.** The `relay_event_applied` signal in `core/relay_events.py` (sent after each event is applied;
receivers' exceptions are caught and logged so the batch never 500s). The `StreamHealthEvent` and `StreamHealth`
models, the receiver, and `fold_stream_health` with a beat entry.

**Break-checks.** Count `max_retries_exceeded` as a failure: the double-count test reddens. Drop the
decay: the injected-clock test reddens, naming the expected decayed value.

**PR description draft:**

> Records per-stream reliability from the relay's events (failover away, connection failure,
> buffering, playback time) into an append-only queue at ingest, and folds it every five minutes
> into a decayed failures-per-hour score and a band. Nothing on the tune path changes; the tune-path
> query ledger is untouched. Needs S1's event fields to attribute anything. Spec PR S5.

### S6 — ordering

**Changes.** `Channel.stream_order_mode`, `ChannelStream.pinned` (migration `0040`). `ChannelOrderSnapshot`.
The D8 order function. `reorder_channels` with D10's lock. The serializer and bulk-edit lock plus flip-to-manual
(D7). The `auto-order/preview|enable` endpoints and snapshot restore.

**Break-checks.** Remove the stable last key: the "second run writes nothing" test reddens. Remove the
`manual` guard: the manual-untouched test reddens. Drop the lock from the serializer: the concurrency
test reddens.

**PR description draft:**

> Orders each `auto` channel's streams best quality tier first, then by reliability band within a
> tier, with admin pins on top, so the relay's existing failover walks down in quality. Every
> existing channel starts `manual`; enabling auto-order goes through a preview and snapshots each
> channel's previous order for one-click restore; a manual drag on an `auto` channel switches it
> to `manual` visibly. The relay is unchanged. Spec PR S6.

### S7 — the Lineup page and the channel streams table

**Changes.** The § Admin UX items except D16's form and the LLM settings. Vitest for the store and
each new component.

**Break-checks.** Send the reorder without the mode flip handling: the toast test reddens.

**PR description draft:**

> Adds the Lineup page (proposals, review queue, identities, status and enablement) and tier,
> health, pin and order-mode controls on a channel's streams. Mantine and Zustand only. Spec PR S7.

### S8 — per-account naming conventions

**Changes.** D16 validation in the M3U account serializer, the form section, and the parse preview.

**Break-checks.** Skip the convention in `convention_version`: the "editing the convention reclassifies
only that account" test reddens.

**PR description draft:**

> Lets an admin teach the classifier a provider's naming convention per account (default region,
> region-token overrides such as `AR:` meaning Arabic, strip prefixes/suffixes, region-source
> order), with a live preview. Spec PR S8.

### S9 — optional LLM assist

Security-adjacent: the reviewer runs on `fable` from round one.

**Changes.** `apps/catalog/llm.py` (§ LLM assist), the settings fields and UI, and the queue badge.

**Break-checks.** Add `url` to the payload builder: the exact-key-set test reddens. Remove the
cross-region drop: the D4 test reddens.

**PR description draft:**

> Optional, off by default, and inert without `MINO_CATALOG_LLM_API_KEY`: sends the streams the
> rules could not resolve (names, group titles and tvg_ids only, redacted; never URLs, credentials,
> account or database identifiers) to an LLM and shows its answers as suggestions in the review
> queue. It never merges anything itself. Spec PR S9.

**Order and stopping points.** S1 and S2 are independent and can run in parallel. S3 needs S2. S4
needs S3. S5 needs S1 (and the S3 app). S6 needs S4 and S5. S7 needs S6. S8 needs S3. S9 needs S4. Stopping
points: after S3 (tiers visible), after S4 (identities and proposals), after S6 (the headline behaviour,
API-driven), and after S7.

## Non-goals

- **No active probing** of any provider (R1). No ffprobe, and no extra slot use.
- **No relay switch-policy change** (D9). Specifically, no climb-back to a higher tier while a
  lower one plays, and no "same tier before lower" for streams earlier in the current tier. If the owner
  later wants the second, the smallest change is Django-only: `order_alternates_from_current()` would
  rotate within the current stream's tier block before moving to lower blocks. It would get a parity-matrix row
  and an E2E pin of its own. It is not designed here.
- **No ranking by bitrate, codec or measured fps** in this programme (Q3).
- **No channel preemption** (it stays unimplemented, CLAUDE.md § Known defects).
- **No change to auto channel sync's behaviour**, including its orphan cleanup (§ Admin UX note).
- **No VOD or catch-up classification.** Live streams only.
- **No fix to the copied channel-authorization filter.** This spec adds no surface that needs it.

## Risks

- **A wrong deterministic merge serves the wrong region's feed.** This is mitigated structurally (D4,
  conflict rule) and by the trap tests. The remaining risk is a provider that labels an NZ feed `UK:` *and*
  gives it a `.uk` tvg_id. No rule catches that, and the admin's `region` decision is the remedy.
- **Order churn.** Mitigated by D8's stable key and band hysteresis. The S6 test pins "a second run writes
  nothing".
- **Stats volume.** S1 restores one `Stream` write per running channel every 30 s on the API process.
  That was the Python relay's load before the cutover. It is noted, not new.
- **The first classification of a large account** may take about a minute (§ Budget). It runs on Celery,
  after the refresh has reported success.

## Open questions for the owner

- **Q1.** Should a separate issue be filed for M1, the Go relay never posting `stream_stats`, as a
  parity defect independent of this programme? This spec fixes it in S1 either way. A filed issue lets
  S1 carry `Closes #N` and the metrics ledger record it.
- **Q2.** Where should `UNKNOWN` tier sort? D8 puts it between HD and SD. The alternative is last.
- **Q3.** Is bitrate a within-tier signal? Two FHD streams at 3 and 8 Mb/s rank only by reliability
  today.
- **Q4.** Should high-confidence LLM suggestions ever be accepted without a click, for example at a
  confidence of 0.95 or more and a same-region match? D14 says never. R2's word "resolve" could be read either way.
- **Q5.** For `add_streams` into an auto-created channel, should "Detach from auto-sync" default to
  on? Off keeps today's sync behaviour. On keeps the merged channel when its origin provider drops the stream.
- **Q6.** Should D9's non-goal (tier-block rotation) be scheduled as a follow-up once S6 has run on
  real providers for a while?

## Appendix A — owner rulings (2026-10-31)

- **R1 Quality measurement: name + passive.** Parse quality hints from stream name and group
  (UHD/4K/FHD/HD/SD/HEVC/50fps/…). They are overridden by measured `Stream.stream_stats` captured during real
  playback. No active probing: no ffprobe, and no extra provider slot use.
- **R2 Identity matching: rules + optional LLM assist.** A deterministic core (normalise name, extract
  region from prefix, group and name, match on tvg_id and EPG data). Fuzzy matches go to an admin review
  queue, and confirmed matches are remembered. An optional, off-by-default LLM may resolve ambiguous
  leftovers. It sends provider channel lists to an external API, so it must never send URLs or
  credentials and must be explicitly enabled.
- **R3 Automation: auto-order, propose new.** Existing served channels have their streams auto-reordered
  best quality first. New canonical channels are proposed for admin acceptance. Admin pins override
  everything.
- **R4 Ranking: quality tier, then reliability.** Order by quality tier, best first. Within a tier, order
  by observed health (recent failovers, buffering events and connect failures from relay events).

## Changelog

- 2026-10-31: first draft, at `149678aa`.
