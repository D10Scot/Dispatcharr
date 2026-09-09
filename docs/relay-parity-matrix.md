# The relay parity matrix

Every externally-observable behaviour of the **live** relay path, the Python source it was derived
from, and what pins it.

This document is Phase 2's load-bearing artifact
(`docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` § Stage 2a, Gate 1). It is 2a's own
checklist, 2c's implementation spec — each Go PR closes a named set of rows — and 2d's cutover
checklist: every row must show a passing Go-side equivalent before nginx's live locations move.
Rows are addressed **by number** everywhere in the phase, so **an id is never reused and never
renumbered**; a retired row keeps its id and says so in its Notes.

Rows were derived by reading the source, not by cataloguing tests that happen to exist. Most rows
therefore start life with no test at all — that is the gap 2a-3 through 2a-6 exist to close, and the
`owed:` marker below is how a row says which PR owes it.

Scope is the live TS/fMP4 path only (spec D1). VOD, catch-up and `timeshift.php` stay on the Python
relay for the whole of Phase 2 and are not rows here.

Enforced by `e2e/tests/guards/parity-matrix.spec.ts`, in the `guards` Playwright project. It needs
no container: `cd e2e && npx playwright test --project=guards parity-matrix`.

<!--
  READ THIS BEFORE EDITING THE TABLE BELOW.

  Five pull requests fill in test references in this table: 2a-3, 2a-4, 2a-5
  and 2a-6 (developed in parallel — they depend only on 2a-2 and touch disjoint
  source files), plus 2b-3, which closes the last row later. The ONLY thing
  their merges contend on is this table. Four
  properties keep that contention trivial. Three of them are asserted by
  e2e/tests/guards/parity-matrix.spec.ts, because a property nobody checks is a
  property the next person to run a Markdown formatter destroys.

  1. ONE ROW IS ONE LINE. No wrapped rows, no multi-line cells. Closing a row is
     a one-line diff, so two PRs closing different rows do not conflict at all.

  2. CELLS ARE NEVER PADDED TO ALIGN COLUMNS. Every table line is exactly
     "| " + cells joined by " | " + " |", with no trailing whitespace. Padding
     means one growing cell re-aligns the whole column, all five PRs rewrite
     every line, and every merge conflicts on the entire file. THE TABLE LOOKS
     RAGGED IN RAW TEXT AND THAT IS INTENTIONAL. Do not run a Markdown table
     formatter over this file.

  3. NO STORED COUNTS. No "18 of 27 pinned" line, no per-block subtotal, no
     "last updated" stamp - every one of the five PRs would bump it and conflict
     four ways over a number the guard computes in a millisecond. The guard
     PRINTS the pinned / owed / white-box counts on every run.

  4. ROW ORDER GROUPS BY OWNING PR, NOT BY ID. The spec scatters ownership
     across the id sequence (2a-4 owns 1-6, 2a-3 owns 7-10 and 13), so id order
     interleaves the PRs' edits. Block order keeps each PR's edits contiguous.
     DO NOT SORT THIS TABLE BY ID.

     DO NOT RUN A MARKDOWN FORMATTER OVER THIS FILE. `npx prettier --write`,
     which CLAUDE.md points you at, pads pipe tables by default and rewrites
     every line here. So does format-on-save in most editors. The guard's
     "one canonical line per row" check will fail; fix the file, not the guard.

     THE `<!-- block: -->` MARKER LINES ARE NOT DECORATION. Measured: git
     conflicts on two edits ONE line apart and merges cleanly at TWO, for
     modify-vs-modify, modify-vs-delete and delete-vs-delete alike. Closing a
     row is a modify, so the last row of one block and the first row of the
     next would conflict if they were adjacent — the marker line between them
     is what makes the distance two. Deleting the markers to "tidy up"
     reintroduces exactly the conflicts the block order exists to prevent.

  5. THE TABLE ENDS AT `<!-- end of matrix -->`. Keep that line, and DO NOT PUT
     A ROW BELOW IT — a row down there is invisible to every check here, and the
     guard refuses one, naming it. Without the terminator at all, a stray line
     in the middle of the table truncates it and every check below goes blind.

     Below the terminator this file must also not contain a five-column table
     with a numeric first column, nor a fenced example of a matrix row: the
     guard cannot tell either from a stray row, and refuses both. That is a
     deliberate trade — see § Format.

  A new row takes the next free id and is appended to the end of its owning
  PR's block. An id is never reused and never renumbered: 2c PRs address rows by
  number ("closes rows 7-10, 13").
-->

## Format

The guard finds the table by its five column names — `#`, `Behaviour`, `Source`, `Pin`, `Notes` —
trimmed, and **refuses to run if two lines in this file name them**. So do not add a worked example
table to this section: a second header would otherwise be parsed instead of the real matrix, silently.
Quoting the header inline in a sentence is fine — the guard only considers lines that *begin* with a
pipe. Do not add, rename or reorder a column without changing
`e2e/tests/guards/parity-matrix.ts` in the same commit. The header's canonical spelling is
`| # | Behaviour | Source | Pin | Notes |`, and every table line must be canonical the same way
(see the comment above): the parser tolerates padding so that it can tell you about it, and a named
check then fails it.

- **`#`** — a decimal integer. Unique, never reused, never renumbered. **A row is never removed from
  this table**: one that stops applying is retired *in place*, keeping its id and saying so in its
  Notes. The guard asserts the ids run `1..N` with no gaps, so deleting a row fails loudly. **Not in
  ascending file order** — rows are grouped by the PR that owes them.
- **`Behaviour`** — one sentence naming the externally-observable behaviour.
- **`Source`** — one or more backticked, repo-relative citations: `` `path:line` `` or
  `` `path:start-end` ``. The guard checks that each file exists and each range lies inside it. It
  cannot check that the range is the *right* code; that is what review is for.
- **`Pin`** — exactly one of three forms:
  - a test reference, `` `path::symbol` `` — for a `.spec.ts` the symbol is the test's literal
    title; for a `.py` it is the `def` name (optionally `path::Class::method`, of which the last
    segment is checked); for a `.go` it is the `func` name. The guard resolves the symbol in the
    file, so a renamed test fails here;
  - `owed: <pr>` — no test yet, and the named PR owes one. `<pr>` is a Phase 2 PR id from the
    guard's `PRS` vocabulary. **This cell is the only place owed-ness is recorded**, so closing a
    row is one line in one file — which is the point, because five PRs close rows in this table;
  - `white-box-only` — behaviour no client can observe, recorded honestly as behaviour **the Go
    relay is not held to**. This is an allowlist, not a keyword: the row id must also appear in the
    guard's `WHITE_BOX_ONLY` list with a `why`, and the `Notes` cell must say why here too.

  Enclosing backticks are optional on the last two — `` `owed: 2a-4` `` and `owed: 2a-4` both
  parse — and required on the test reference.
- **`Notes`** — prose. Required non-empty on a `white-box-only` row.

**No cell may contain a literal `|`.** A stray pipe splits the row into six cells and the guard
fails naming the line.

**The table ends at a literal `<!-- end of matrix -->` line, and needs one.** Without a terminator a
truncation is indistinguishable from the end of the table: a stray prose line in the middle silently
ends it there and every check goes blind to everything below. With one, the walk knows it stopped
early and says which line did it — which is also how a row that lost its leading `|` is reported as
itself rather than as a missing id.

**Do not put a row below the terminator.** A row down there is invisible to every check, so the guard
refuses one. **And know what that costs**, because it is broader than "a stray matrix row": below the
terminator this file must not contain **a five-column table whose first column is numeric**, nor **a
fenced example of a matrix row**. The guard cannot tell either from a row someone appended in the
wrong place, and a numbered five-column table is an ordinary Markdown construct — a numbered list of
steps, an indexed reference table — so this is a real constraint on what else this document may say,
not a theoretical one. Four-column tables and five-column tables with a non-numeric first column are
unaffected.

The alternative — teaching the scanner about fenced blocks — is **deliberately not taken**. The
duplicate-header refusal relies on a header inside a fenced block being visible: that is what stops a
worked example in this very section being parsed as the matrix. Treating fenced content as real
content everywhere is the consistent choice, and this constraint is its price.

## The matrix

Blocks, in file order: rows owed by 2a-4, then 2a-3, 2a-6, 2a-5 and 2b-3, then the rows already
pinned, then the `white-box-only` rows. Add a row to the end of its own block, and keep the
`<!-- block: … -->` line above it — it is what puts two lines between one PR's last row and the next
PR's first, which is the distance git needs to merge them cleanly.

| # | Behaviour | Source | Pin | Notes |
|---|---|---|---|---|
<!-- block: owed by 2a-4 -->
| 1 | Buffering failover trigger: ffmpeg's reported `speed=` below `buffering_speed`, sustained longer than `buffering_timeout` (15s default), calls `_try_next_stream()` | `apps/proxy/live_proxy/input/manager.py:1064-1066`, `apps/proxy/live_proxy/input/manager.py:1122-1191` | `owed: 2a-4` | `_parse_ffmpeg_stats` parses `speed=` and runs the buffering check in the same method (`input/manager.py:1058-1204`); the two citations are the extraction and the comparison/timeout logic within it |
| 2 | Dead-air failover trigger: no data for longer than the inactivity threshold, observed on three consecutive 5-second health checks | `apps/proxy/live_proxy/input/manager.py:1503-1507`, `apps/proxy/live_proxy/input/manager.py:1509-1560` | `owed: 2a-4` | `health_check_interval` defaults to 5s, `_health_inactivity_threshold()` defaults to 10s; the flag `_monitor_health` sets is consumed by the main loop's `_try_next_stream()` call, not called directly here |
| 3 | Connect-failure trigger: `MAX_RETRIES` (3) connection failures inside `RETRY_WINDOW_SECONDS` (1800) exhausts the source; the counter resets after a window with no failure | `apps/proxy/live_proxy/input/manager.py:50-52`, `apps/proxy/live_proxy/input/manager.py:182-192`, `apps/proxy/config.py:9-10` | `owed: 2a-4` | `_record_connection_failure()` is the window-reset logic; `MAX_RETRIES`/`RETRY_WINDOW_SECONDS` are the defaults `ConfigHelper.max_retries()`/`retry_window_seconds()` read |
| 4 | `speed=` is ffmpeg's cumulative average since process start, not an instantaneous rate, so a front-loaded lead must burn off before the buffering detector can arm — roughly 55 seconds measured | `apps/proxy/live_proxy/input/manager.py:1064-1066`, `apps/proxy/live_proxy/input/manager.py:1122` | `owed: 2a-4` | The cumulative-average behaviour is ffmpeg's own, not visible in this Python code; ~55s measured for a front-loaded lead to burn off before the comparison at `:1122` can trip, versus the ~25s dead-air watchdog which usually wins the race |
| 5 | Buffering thresholds are snapshotted in `StreamManager.__init__`; changing `proxy_settings` mid-stream does not reach a running channel | `apps/proxy/live_proxy/input/manager.py:60-61` | `owed: 2a-4` | The two `self.` assignments run once, in `__init__`; a `proxy_settings` change while a channel is running does not reach them |
| 6 | `MAX_STREAM_SWITCHES` does not bound buffering-triggered switches: those come from the stderr reader, which calls `_try_next_stream()` without passing through the main loop's counter | `apps/proxy/live_proxy/input/manager.py:388-402`, `apps/proxy/live_proxy/input/manager.py:1134-1138` | `owed: 2a-4` | Filed as [#221](https://github.com/D10Scot/Dispatcharr/issues/221) and reproduced, not fixed, per spec D5 (preserve known defects rather than silently fix during the port); also recorded in CLAUDE.md's Known defects. The stderr-path call at `:1134-1138` never touches `stream_switch_attempts`, the counter the main loop at `:388-402` checks |
<!-- block: owed by 2a-3 -->
| 7 | The chunk index is monotonic for the channel's life and is never reset by a stream switch, which is why a switch does not disturb connected clients | `apps/proxy/live_proxy/input/buffer.py:65-133`, `apps/proxy/live_proxy/input/buffer.py:136-168` | `owed: 2a-3` | `add_chunk` advances the index with a Redis `INCR`; `reset_buffer_position()`, called on a stream switch, clears only `_write_buffer`/`_partial_packet` and never touches `self.index` |
| 8 | A new client joins roughly 5 seconds behind live, positioned through the `chunk_timestamps` sorted set rather than at the newest chunk | `apps/proxy/live_proxy/input/buffer.py:478-513`, `apps/proxy/live_proxy/output/ts/generator.py:255-270` | `owed: 2a-3` | `new_client_behind_seconds` defaults to 5. Positioning happens once, at client setup; a separate, unrelated mechanism elsewhere in the same file recovers a client whose next expected chunk has already expired, and is not part of this behaviour |
| 9 | Data is realigned to 188-byte TS packet boundaries before a chunk is written; a partial trailing packet is carried into the next chunk | `apps/proxy/live_proxy/input/buffer.py:79-91`, `apps/proxy/live_proxy/constants.py:122` | `owed: 2a-3` | `TS_PACKET_SIZE = 188`; the arithmetic computes the largest multiple of 188 in the combined buffer and carries the remainder forward as `_partial_packet` |
| 13 | Client registration is idempotent per client id, and a client whose heartbeat stops for `GHOST_CLIENT_MULTIPLIER` × the heartbeat interval is removed as a ghost | `apps/proxy/live_proxy/client_manager.py:215-221`, `apps/proxy/live_proxy/client_manager.py:100-126`, `apps/proxy/live_proxy/client_manager.py:434-469` | `owed: 2a-3` | Extends the existing `apps/channels/tests/test_ts_proxy_ghost_clients.py`, which is the partial cover the spec records |
<!-- block: owed by 2a-6 -->
| 12 | The fMP4 generator's `_is_timeout()` lacks the TS generator's `url_switching` exemption, so an fMP4 viewer can be dropped mid-failover while a TS viewer on the same channel is not | `apps/proxy/live_proxy/output/fmp4/generator.py:339-346`, `apps/proxy/live_proxy/output/ts/generator.py:574-595` | `owed: 2a-6` | Filed as [#222](https://github.com/D10Scot/Dispatcharr/issues/222) and reproduced, not fixed, per spec D5 (preserve known defects rather than silently fix during the port); also recorded in CLAUDE.md's Known defects. The TS generator's version checks `stream_manager.url_switching` (`:585`) before disconnecting; the fMP4 version has no equivalent check |
<!-- block: owed by 2a-5 -->
| 14 | Status payload field types differ by endpoint: `owner` is `null` on the list endpoint and the literal string `unknown` on the detail endpoint, `ffmpeg_speed` is a float on both, and `source_fps` is a float on list but a string on detail | `apps/proxy/live_proxy/channel_status.py:45`, `apps/proxy/live_proxy/channel_status.py:460`, `apps/proxy/live_proxy/channel_status.py:339`, `apps/proxy/live_proxy/channel_status.py:595`, `apps/proxy/relay_serializers.py:59`, `apps/proxy/relay_serializers.py:129` | `owed: 2a-5` | Neither serializer supplies a `default=`, so the builder's value reaches the wire unchanged. A test that checks the string against only one of the two endpoints proves nothing about the other |
| 15 | `stream_xc` authorizes once and passes its `decision` into `stream_ts`, so an XC tune is not authorized twice and does not mint a second client id for one connection | `apps/proxy/live_proxy/views.py:162-166`, `apps/proxy/live_proxy/views.py:825`, `apps/proxy/live_proxy/views.py:845-851` | `owed: 2a-5` | `stream_ts`'s `if decision is None:` guard only re-runs `resolve_authorization` when called directly, not via `stream_xc`; `stream_xc` calls `resolve_authorization` itself and passes the result straight through |
| 16 | `/proxy/ts/stream/<stream_hash>` — the admin single-stream preview, with no channel at all — applies the STREAMS ACL and the per-user stream limit when a principal resolved, and no channel check of any kind, because there is no channel to check | `apps/proxy/next_source.py:69-79`, `apps/proxy/authorize.py:340-349`, `apps/proxy/authorize.py:425-442` | `owed: 2a-5` | `_resolve_channel` returns `(None, True)` for the hash case, since `get_stream_object` returns a `Stream`, not a `Channel`; the caller only runs `_apply_channel_checks` when `channel is not None`, so the hash case skips it entirely while the ACL check and stream-limit check above it still run unconditionally |
| 17 | `ip_address` on both status endpoints is the client address resolved by `get_client_ip(request)`, called once at `apps/proxy/live_proxy/views.py:195` before either `add_client()` site, reading `REMOTE_ADDR` and honouring `X-Real-IP`/`X-Forwarded-For` only when `REMOTE_ADDR` is a trusted proxy | `dispatcharr/utils.py:342-370`, `apps/proxy/live_proxy/views.py:195`, `apps/proxy/live_proxy/client_manager.py:215-230`, `apps/proxy/relay_serializers.py:29`, `apps/proxy/relay_serializers.py:79` | `owed: 2a-5` | 2b-2 replaces that source with `X-Relay-Client-IP`, set by the authorize hop; the invariant this row pins is that `ip_address` stays the real client address across that change |
| 19 | Authorize matrix — **Internal** principal (DVR, any caller with a valid `X-Dispatcharr-Internal`): the STREAMS ACL applies; `user_level`, profile membership, `hidden_from_output`, adult filtering and the stream limit are all bypassed | `apps/proxy/authorize.py:309-310`, `apps/proxy/authorize.py:376-377`, `apps/proxy/authorize.py:436-442` | `owed: 2a-5` | No `e2e/tests/` spec pins this principal — see ruling 13 |
| 20 | Authorize matrix — **Admin** (`user_level >= 10`, any authenticator): ACL applies, every channel check bypassed, the stream limit still enforced | `apps/proxy/authorize.py:379-385`, `apps/proxy/authorize.py:436-442` | `owed: 2a-5` | No `e2e/tests/` spec pins this principal — see ruling 13 |
| 23 | Authorize matrix — **Session**, non-admin: every check enforced | `apps/proxy/authorize.py:268-276` | `owed: 2a-5` | No `e2e/tests/` spec pins this principal — see ruling 13. `_session_user` reads the session directly rather than `http_request.user`, for the reason its own docstring gives |
| 25 | Authorize matrix — **Stream-by-hash** (`/proxy/ts/stream/<stream_hash>`), any principal: the ACL applies and the stream limit is enforced when a principal resolved; no channel check applies | `apps/proxy/next_source.py:69-79` | `owed: 2a-5` | No `e2e/tests/` spec pins this principal — see ruling 13 |
<!-- block: owed by 2b-3 -->
| 18 | What the status payload's `stream_name` and `m3u_profile_name` contain when the channel metadata hash was never written one | `apps/proxy/live_proxy/channel_status.py:74`, `apps/proxy/live_proxy/channel_status.py:92` | `owed: 2b-3` | Phrased as a question 2b-3 must answer, not an assumed "always present"; whatever 2b-3 concludes when it deletes these reads is the answer 2c is then held to |
<!-- block: already pinned -->
| 10 | Multi-client upstream sharing: three clients on one channel share exactly one upstream connection, and closing every client releases it | `apps/proxy/live_proxy/client_manager.py:215-221`, `apps/proxy/live_proxy/server.py:497-536` | `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection`, `e2e/tests/streaming/shared-upstream.spec.ts::closing every client releases the upstream` | The row asserts two things, so it cites both tests in the same file: the first proves the sharing, the second proves the release |
| 11 | One transcode process runs per active `(channel, profile)` pair across the cluster: a second client on the same Output Profile attaches to the existing process's buffer instead of spawning its own | `apps/proxy/live_proxy/output/profile/manager.py:67-122`, `apps/proxy/live_proxy/output/profile/manager.py:312-321` | `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts::two clients on one output profile share a single transcode` | Ten AC3 clients cost one ffmpeg. 2a-6 may re-pin this to a harness test; the existing e2e spec stands until it does |
| 21 | Authorize matrix — **XC credentials** (`<user>/<pass>` path segments, compared with `hmac.compare_digest`): every check enforced; `hidden_from_output` and adult filtering answer 403 | `apps/proxy/authorize.py:148-174` | `e2e/tests/streaming/authorize-matrix.spec.ts::a hidden channel is refused on the XC live root to an ordinary XC user`, `e2e/tests/streaming/authorize-matrix.spec.ts::an adult channel is refused on the XC catch-up root to a hide_adult_content viewer` | `resolve_xc_user` is the constant-time comparison CLAUDE.md's Known defects section already names |
| 22 | Authorize matrix — **JWT / API key / query-param JWT**, non-admin: every check enforced | `apps/proxy/authorize.py:227-265` | `e2e/tests/streaming/authorize-matrix.spec.ts::a hidden channel is refused on the native catch-up route to a JWT viewer` | `_drf_user` runs the DRF authenticator set explicitly rather than relying on the calling view's own `authentication_classes` |
| 24 | Authorize matrix — **Anonymous** (a bare channel UUID): the ACL applies, `hidden_from_output` answers 403, and every user-scoped check is inapplicable — an anonymous request with a valid UUID still streams an ordinary channel | `apps/proxy/authorize.py:316`, `apps/proxy/authorize.py:325-327`, `apps/proxy/authorize.py:386-389` | `e2e/tests/streaming/authorize-matrix.spec.ts::a channel hidden from output is refused even to an anonymous request`, `e2e/tests/streaming/authorize-matrix.spec.ts::an ordinary channel still streams with no credential at all` | `hidden_from_output` is checked with no principal at all, which is why it is the one check anonymous also fails |
<!-- block: white-box-only -->
| 26 | Not held to: the greenlet and OS-thread topology inside `server.py` — three `threading.Thread(daemon=True)` supervisors sharing one OS thread with the request greenlets, and `_spawn_on_hub`'s cross-thread scheduling onto the gevent hub | `apps/proxy/live_proxy/server.py:161-171`, `apps/proxy/live_proxy/server.py:467`, `apps/proxy/live_proxy/server.py:851`, `apps/proxy/live_proxy/server.py:2192` | `white-box-only` | Deleted, not ported: the Go relay's concurrency model is goroutines and a `sync.RWMutex` (spec D2), and no client can observe which greenlet did what |
| 27 | Not held to: `_execute_redis_command` swallows every Redis exception to `None` after one reconnect attempt, so a caller cannot distinguish "key absent" from "Redis unreachable" | `apps/proxy/live_proxy/server.py:138-159` | `white-box-only` | Deleted, not ported: spec D2 removes Redis from the live path entirely, so there is no analogous call in the Go relay to swallow anything. One of the three fail-open paths `CLAUDE.md` records as a live defect |
<!-- end of matrix -->
