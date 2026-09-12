# Phase 2 — The Go Relay

**Date:** 2026-09-09
**Status:** Draft
**Parent:** *Splitting the Planes* (extraction proposal, artifact `149fb554`) and the route page it
revises, which name Phase 2 as "optionally Go."
**Predecessor:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (Phase 1, done,
closed `a948cd8a`, #198) and its ADR, `docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md`.
Phase 1 gave the relay its own process, one authorization function, an HTTP boundary for
next-source/events/status/control, and Redis keys with a single owner. This spec is what Phase 1
made possible, not what it deferred by accident: ADR 0005's canary mechanism (`X-Relay-Name`, a
nginx `map`) exists so a language change is a routing decision, and Phase 2 is the first thing to
spend it — though D3 below spends it differently than ADR 0005 imagined.
**Verified at:** `main` `a948cd8a`. Line numbers drift; route shapes, header names and Redis key
names are the durable half of every citation.

## Goal

Replace the relay's live TS/fMP4 path — and only that path — with a Go binary holding its ring
buffer in process memory, while VOD, catch-up and `timeshift.php` stay exactly where Phase 1 left
them. `CLAUDE.md` states the phase ladder as "1 extract the boundary, still Python → 2 optionally Go
→ 3 remove Redis from the data path" and warns that stopping after any phase is legitimate and that
scope-widening is the main way this fails. This spec takes Phase 2 to include the live half of what
was going to be Phase 3 — deleting Redis from the video path — because holding the ring buffer in
Go process memory from day one (D2) makes carrying it through Redis for one release and then
deleting it a wasted intermediate step, not a safer one. VOD and catch-up's Redis coupling is
untouched and stays Phase 3's problem, now a smaller one.

Four stages, two of them legitimate stopping points in their own right:

1. **2a — pin the behaviour (Python).** A parity matrix naming every externally-observable live-path
   behaviour with its source line and its pinning test, guarded so a row that is neither pinned nor
   marked `owed: <PR id>` fails CI — a row can be unpinned, never unowned (§ A6); a real-
   subprocess test harness the backend suite has never had; and coverage on the live path raised from
   a measured 43.1% to a gated ≥80% combined with the ten Phase 1 boundary modules, already at 92.1%
   (§ Stage 2a's Gate 2 has the exact module list and count).
2. **2b — complete the contract (Python).** The ORM reads Phase 1 knowingly left in the relay
   (its own § "ORM reads that remain" table) close: into the next-source payload, a new control-plane
   field, or deleted as dead. Ends with a guard test asserting zero ORM reads survive in the live
   relay.
3. **2c — build the Go relay.** A second process, port 5658, speaking the exact same
   `/proxy/relay/…` and `/api/relay/…` contract PR 6/7 already shipped, holding the ring buffer in
   memory, no third-party dependencies.
4. **2d — cut over and delete.** nginx's live locations move from `uwsgi_pass` to `proxy_pass`;
   `apps/proxy/live_proxy/` and its ~564 tests are deleted in one PR after three PRs of preparation.

**2a and 2b are pure Python, and their value survives abandoning Go entirely.** A parity matrix with
100% of its rows pinned (Gate 1, which closes in **2b-3** rather than at the end of 2a, because row
18 is a question only 2b-3 can answer — § A7), a subprocess-capable test harness, and 80% coverage
on the highest-risk, lowest-coverage code in the repo are worth having whether or not a Go relay
ever ships — `CLAUDE.md`
names stopping as a legitimate outcome, and 2a/2b are where this phase can stop and still have paid
for itself. The second legitimate stopping point is after 2b, with Go never started: the Python relay
stays, better tested and with a narrower ORM footprint than it has ever had. Not a spec: HLS output
(Phase 4), VOD/catch-up's Redis coupling (what remains of Phase 3), multi-relay/HA, signed URLs
(ADR 0005 settled that), or any new failover/quality logic. See § Non-goals.

## What the code says that the brief did not

The brief that shaped this spec was written from measurements and a reading of Phase 1's own spec;
verifying it against `a948cd8a` directly turned up several places where the tree is more precise or
different in a way that changes a decision. Each is folded into the relevant section below and
restated here as a single list, in the idiom of Phase 1's § "What the code says":

- **There are three internal HMAC contexts, not two.** Phase 1's D11 and ADR 0005 describe
  `X-Dispatcharr-Authorized` (`"relay-trust"`) and `X-Dispatcharr-Internal` (`"internal-principal"`)
  as the whole authentication surface between processes. `apps/proxy/internal_auth.py` (186 lines,
  read in full) carries a third: `INTERNAL_REQUEST_CONTEXT = b"internal-request"`, producing
  `X-Dispatcharr-Internal-Request`, a *bound* token over method, path, timestamp and a body digest,
  valid for `INTERNAL_REQUEST_WINDOW_SECONDS = 120`. `IsInternalRelay` (`apps/proxy/permissions.py`,
  27 lines) requires **both** headers on every one of the five `/proxy/relay/…` routes and both
  `/api/relay/…` routes — `request_is_internal(...) and request_is_internal_request(...)`. This
  landed after the Phase 1 spec text was written (its own "ruling 15" and "ruling 17" amendments,
  `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md:1674-1685`) and is easy to miss
  reading the spec alone. **The Go relay must produce and verify both headers, not one** — see
  § The contract.
- **`ffmpeg_speed`'s type mismatch is already half-fixed, at the wire layer.**
  `apps/proxy/live_proxy/channel_status.py:376` (`get_detailed_channel_info`) and `:599`
  (`get_basic_channel_info`) both now do `info['ffmpeg_speed'] = float(ffmpeg_speed)` — the internal
  Python dicts agree. `CLAUDE.md`'s "a string in one endpoint, a float in the other" is stale for
  `ffmpeg_speed`; Phase 1 PR 7's own ruling 4 says as much ("normalising `ffmpeg_speed` to a float").
  It is **not** stale for `source_fps`, which the current `CLAUDE.md` records as still disagreeing —
  a string on the per-channel (detail) endpoint, a float on the collection (list) one, carried and
  not fixed; a second field-type parity row alongside `owner` below.
  **`owner`'s fallback to the literal string `'unknown'` is not stale, is asymmetric, and this spec's
  first draft had the asymmetry backwards — corrected here.** Reading `channel_status.py`'s `def`
  boundaries (`class ChannelStatus` at `:13`; `get_detailed_channel_info` spans `:25`-`:401`;
  `_execute_redis_command` at `:402`; `get_basic_channel_info` spans `:419`-`:618`;
  `build_live_channel_stats_data` at module level, `:619`): line `:45`'s
  `metadata.get(ChannelMetadataField.OWNER, 'unknown')` is inside **`get_detailed_channel_info`**;
  line `:460`'s same read with **no default** (i.e. `None`) is inside **`get_basic_channel_info`**.
  Route wiring confirms which endpoint each reaches: `relay_views.py`'s `channels_view` (the **list**
  route, `GET /proxy/relay/channels`) calls `build_live_channel_stats_data`, which calls
  `get_basic_channel_info` — so **list** answers `owner: null`. `relay_views.py`'s `channel_view`
  (the **detail** route, `GET /proxy/relay/channels/<id>`) calls `get_detailed_channel_info`
  directly — so **detail** answers `owner: "unknown"`. Neither serializer supplies a `default=`
  (`relay_serializers.py:43`, `:107`), so the builder's value reaches the wire unchanged. `CLAUDE.md`'s
  "owner falls back to the literal string `'unknown'`, never null" is true of `GET /proxy/relay/
  channels/<id>` (detail — the surface `GET /proxy/ts/status/<uuid>` wraps, which is what `CLAUDE.md`'s
  sentence is actually about) and false of `GET /proxy/relay/channels` (list) — a real parity-matrix
  row, and a live trap for anyone testing the string against only one of the two endpoints.
- **A real ORM `User` read happens inside the relay process on the ordinary, nginx-authorized path —
  not only as ADR 0005's stated fallback.** `apps/proxy/authorize_views.py`'s `result_from_headers`
  (`:112-141`) runs `User.objects.filter(id=int(user_id)).first()` whenever `X-Relay-User` is a
  digit string. `resolve_authorization` (`apps/proxy/authorize_views.py:145`, called from
  `apps/proxy/live_proxy/views.py:168` inside `stream_ts`, and — a second call site this spec's first
  draft omitted — from `views.py:825` inside `stream_xc`, which then passes its own `decision` into
  `stream_ts` so the hop does not run twice for one XC tune) calls `result_from_headers` on **every**
  trusted (i.e. every normal, nginx-fronted) tune, not only when the trust marker is absent. Because
  `stream_ts`/`stream_xc` run in the relay process after Phase 1's routing, this
  `User.objects.filter(...)` runs **inside the relay**, on every tune, today — not as a rare
  inline-fallback path. ADR 0005's Consequences bullet ("It still reads both rows by primary key...
  the `User` row the relay loads from `X-Relay-User`") is correct about the read existing but locates
  it loosely; this spec locates it exactly, because 2b has to close it and 2c's Go relay cannot open
  a socket to Postgres to do the same thing. The `stream_xc`→`stream_ts` decision hand-off (no second
  hop, no second client id) is itself an externally observable behaviour and belongs in the parity
  matrix (§ Stage 2a, row 15).
- **`next_source.py` is 779 lines, not 124.** The brief, quoting the Phase 1 spec's own caveat about
  itself being stale, asked this spec to recheck the file's size after PR 6 "shrank that file from 661
  to 124 statements" (a claim about `url_utils.py`, not `next_source.py` — the two names were
  conflated in transit). `wc -l` on `a948cd8a`: `next_source.py` 779 lines, `url_utils.py` 291 lines.
  `next_source.py` holds the whole moved traversal — `get_stream_object`, `transform_url`,
  `order_alternates_from_current`, `_resolve_live_stream_url`, and the `resolve_source`/
  `release_stream` entry points the six Django-side callers and the two HTTP routes (`next-source`,
  `release`) use. `url_utils.py`'s surviving content is what stayed behind: `get_stream_info_for_switch`,
  `validate_stream_url`, and the one dead site named below.
- **`url_utils.py`'s `get_connections_left` is live, not deleted — this spec's first draft was wrong
  about this and the error is withdrawn.** `apps/proxy/live_proxy/url_utils.py:247` defines
  `get_connections_left(m3u_profile_id: int) -> int`, whose body at `:261` runs
  `M3UAccountProfile.objects.get(id=m3u_profile_id)` before reading `profile_connections:{id}` from
  Redis. It is exercised by `apps/proxy/live_proxy/tests/test_live_db_cleanup.py:167-172`
  (`test_get_connections_left_closes_db`), and `grep -rn "get_connections_left" apps/proxy/` finds no
  caller outside that one test. It is a thirteenth surviving ORM read, not a taken cleanup, and is
  added to 2b's table below rather than dropped from it. The surviving reads 2b closes are: the two
  Phase 1's own table already names — `channel_status.py:74` (`Stream`) and `:92`
  (`M3UAccountProfile`) — plus `channel_service.py:324,331,911` (`Channel`/`Stream` name fallbacks),
  `views.py:152` (`OutputProfile.objects.filter(...)` for `build_command()`), `input/manager.py:737`
  (`StreamProfile.objects.get(name='ffmpeg', locked=True)`), `url_utils.py:247`'s
  `get_connections_left`, and the `User` read above.
- **The XC live roots are already routing-distinguishable from XC VOD/catch-up, with no shared
  regex to split.** D-scope (below) asks the Go relay to serve "the XC live roots" while catch-up and
  VOD stay Python. Checking `dispatcharr/urls.py` (read in full): the 3-segment bare
  `<user>/<pass>/<id>` regex (`xc_stream_endpoint`, live-only) and the 4-segment `live/<user>/<pass>/
  <id>` (`xc_live_stream_endpoint`) are the only two XC roots matching `docker/nginx.conf`'s
  `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`; `movie/<user>/<pass>/<id>.<ext>`,
  `series/<user>/<pass>/<id>.<ext>` and `timeshift/<user>/<pass>/<duration>/<timestamp>/<id>` are
  separate `path()` routes with their own nginx `^~` prefixes already. **The cutover in 2d needs no
  new regex surgery on the XC side** — the existing 3-segment regex location, and only it, repoints
  to Go; `^~ /movie/`, `^~ /series/`, `^~ /timeshift/` and `= /streaming/timeshift.php` stay pointed
  at the Python relay unchanged.
- **`docker/nginx.conf`'s `uwsgi_buffering off` directive count is confirmed at exactly ten**, matching
  `CLAUDE.md`: nine top-level relay-bound locations (`streaming/timeshift.php`,
  `proxy/ts/stream/`, `proxy/vod/`, `proxy/catchup/`, `live/`, `movie/`, `series/`, `timeshift/`, the
  XC 3-segment regex) plus the one nested inside `^~ /api/` for `^/api/channels/recordings/\d+/
  file/$`. `grep -c "uwsgi_buffering off" docker/nginx.conf` actually returns **11** — the eleventh
  hit is the comment `# No uwsgi_buffering off: these serve short JSON, not a stream.` inside the
  `^~ /proxy/relay/` block (`:348`), which the directive is deliberately absent from; the ten real
  directives are the ones enumerated above. The greybox spec
  (`e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`, 386 lines) is a **four-test file**,
  not a single set assertion — parses `nginx -T`'s resolved output into top-level `location` blocks
  by brace depth (test 1: the nine-target buffering set; test 2: the authorize-hop wiring on the
  same nine; test 3: the trust-param blanking on thirteen Django-bound targets, `/proxy/relay/`
  included; test 4: `/proxy/relay/`'s own shape — `uwsgi_pass relay_py`, no `auth_request`, the
  blanking include, `uwsgi_read_timeout 30s`) — read in full; § Stage 2d — Cutover names all four and
  what each one's rewrite needs, not just the first.
- **`docker/uwsgi.relay.ini` is 78 lines, not 94** — corrected from this spec's first draft. Every
  fact quoted from it below is still accurate to its own line numbers; only the file's total length
  was wrong, in a sentence whose point was that the file had been read in full.
- **`docker/nginx.conf:356-360`'s `location ^~ /proxy/relay/` is a fourth live-relevant location this
  spec's first draft missed entirely.** It is `uwsgi_pass relay_py` with `uwsgi_read_timeout 30s`,
  reached by every one of `apps/proxy/relay_client.py`'s five calls — including
  `_live_connections()` (`apps/proxy/utils.py:256+`), which `check_user_stream_limits` calls from
  inside `authorize_stream` on **every live tune** (D4). Under D3's hard cutover the Go relay owns
  the live channel registry these calls ask about, so this location has to move too — detailed fully
  in § Stage 2d, which this spec's first draft never mentioned in the cutover's location table at
  all.
- **`map $relay_name $relay_upstream` (`docker/nginx.conf:36-39`) resolves to `relay_py` for every
  value `X-Relay-Name` can currently carry** — `default relay_py; py relay_py;` — because
  `authorize_views.py:139` sets `relay_name=settings.RELAY_DEFAULT_NAME`, one process-wide constant.
  `$relay_upstream` cannot hold two different values today, so a cutover snippet that writes
  `proxy_pass http://$relay_upstream;` on the three live locations and leaves the map untouched
  would send Go-relay traffic to the address the map still resolves to Python's own upstream group —
  a real gap in this spec's first draft, resolved in § Stage 2d by naming the Go upstream directly
  rather than routing it through this map.

## Verified facts this design rests on

**Coverage, measured on `a948cd8a`, 857 tests green, one process per test label exactly as
`backend-tests.yml` runs them** (`coverage run` over `apps.proxy.tests`,
`apps.proxy.live_proxy.tests` and `apps.channels.tests`, each label in its own process,
`coverage combine`d afterwards, narrowed to the ten boundary modules plus `live_proxy` — see
§ Stage 2a › Gate 2 for the exact rcfile, and for why `--include=` on the command line is **not**
what produces these numbers). **Every figure in this section is corrected in the round-6
amendments (§ A1):** an independent re-derivation at the same commit — run twice to identical
totals, with a 16-label control run that moved `live_proxy` by zero statements — supersedes this
spec's first measurement. The old figures (3,818 missed / 44%, a nine-module 1,040/87, a combined
7,870/3,905/50.4%, "~77%, about +2,250") are withdrawn wherever they appeared.

| Scope | Statements | Missed | Coverage |
|---|---|---|---|
| `apps/proxy/live_proxy/**` (non-test) | 6,830 | 3,886 | **43.1%** |
| The **ten** `apps/proxy/*.py` relay modules (`authorize.py` 93.6%, `authorize_views.py` 96.3%, `control_plane.py` 96.8%, `internal_auth.py` 100%, `internal_base_url.py` 100%, `next_source.py` 78.4%, `permissions.py` 100%, `relay_client.py` 97.3%, `relay_serializers.py` 100%, `relay_views.py` 100%) | 1,148 | 91 | **92.1%** |
| Combined denominator | 7,978 | 3,977 | **50.2%** |

`authorize_views.py` (108 statements, 4 missed) is **in** the denominator — the first draft omitted
it from this table while including it in the Gate 2 invocation, and § Stage 2a's Gate 2 records that
inconsistency as closed rather than open.

**The measurement shape is part of the number.** Running the same three labels — or the whole suite
— in a *single* process reports about **68 fewer missed statements** (`server.py` 937 rather than
977, `client_manager.py` 70 rather than 98), reproduced exactly across five run shapes. The cause is
wall-clock time, not test selection: the relay's daemon threads
(`ProxyServer._start_cleanup_thread.cleanup_task`, `_start_event_listener.event_listener`,
`ClientManager._start_heartbeat_thread.heartbeat_task` — and `apps/channels/tests/
test_ts_proxy_teardown.py` builds a real `ProxyServer` ten times) keep ticking while *unrelated*
tests run, so a 33-second single process credits lines no test asserts, while three per-label
processes of a few seconds each do not. **The gate is therefore measured one process per test label,
because that is what `backend-tests.yml` does** — a gate set against the single-process figure would
be un-meetable by the very pipeline meant to enforce it, and the 68 extra statements are not test
coverage in any case: no test asserts anything about them. Every figure here carries a
**±70-statement (~1pp) thread-timing band**; a later measurement landing at 44% is inside the noise,
not a win, and one landing at 42% is not automatically a regression.

**The gate, in exact numbers.** 80% of 7,978 is 6,382.4, so **6,383 covered statements** against
today's 4,001 — a shortfall of **2,382**. The ten `apps/proxy/*.py` files are already at 92.1% and
can contribute at most 91 more, so essentially all of the shortfall has to come from the relay
itself: **`apps/proxy/live_proxy/**` has to climb from 43.1% to 78.0%** (5,326 of 6,830, i.e. +2,382
statements), or to 76.6% if the ten are simultaneously driven to 100% — a spread too small to plan
around. `vod_proxy` and the dead `hls_proxy` are outside the denominator by design — D1 below
excludes them from scope entirely, so they should not count toward the gate that unlocks Go work on
the live path. Worst files, missed-statement count first: `server.py` 1490/977 (34.4%),
`input/manager.py` 1248/771 (38.2%), `services/channel_service.py` 500/262 (47.6%),
`output/ts/generator.py` 377/241 (36.1%), `output/fmp4/manager.py` 304/253 (16.8%),
`output/profile/manager.py` 223/185 (17.0%), `output/fmp4/generator.py` 219/195 (**11.0%**, the
lowest-covered file in the denominator), `input/buffer.py` 248/166 (33.1%), `input/http_streamer.py`
101/101 (**0.0%**), `output/fmp4/buffer.py` 116/102 (12.1%), `utils.py` 142/102 (28.2%),
`services/log_parsers.py` 235/73 (68.9%), `client_manager.py` 262/98 (62.6%), `views.py` 608/204
(66.4%), `channel_status.py` 375/76 (79.7%). The five largest gaps — `server.py`,
`input/manager.py`, `channel_service.py`, `output/ts/generator.py`, `output/fmp4/manager.py` —
total **2,504** missed statements, 63% of the whole 3,977-statement gap. **The first draft's
"closing them approximately **is** the gate" is withdrawn — the arithmetic does not survive
`server.py`'s measured reachability.** The gate needs **+2,382**; the five-file pool is 2,504, a
margin of only **122**; and `server.py` alone contributes **222** statements that are unreachable or
must not be targeted (§ Reachability below). That leaves **2,282** — **100 short of the gate**,
before anyone has measured how much of the other four files is unreachable.

**The gate is still reachable; its stated strategy is not.** The rest of `live_proxy` holds
**1,382** missed statements outside those five files, and the ten boundary modules another 91, so
there is ample headroom — it is simply not where this paragraph said to look. **2a-7 must size the
last stretch against measured per-file reachability, not against "the five biggest gaps"**, and any
PR that claims a file's whole missed count as available headroom is repeating exactly the error this
correction fixes.

**Test inventory, three buckets, all measured against `a948cd8a`.**

1. **PORTABLE** — real HTTP through nginx: **32** Playwright spec files (22 `streaming/`, 6
   `streaming-failover/`, 1 `streaming-split/`, 3 `streaming-greybox/`), ~69 `test(` occurrences —
   corrected in the round-6 amendments alongside § A1, which found `streaming-split/`
   (`process-restart.spec.ts`) omitted from the first draft's count of 31.
2. **VIEW-LEVEL** — `RequestFactory`/`Client`/`APIClient` against Python view functions: behavioural,
   but never leaves the Python process. 14 files, ~203 test functions.
3. **WHITE-BOX** — imports relay internals directly: 22 files, ~361 test functions.

**564 Python test functions cover the live path, and not one survives a rewrite into another
language.** Subtracting the 3 greybox specs 2d rewrites in place (they assert nginx configuration,
which still exists and still needs asserting, just pointed at a different upstream), roughly **63
tests** — the PORTABLE bucket minus those three — are what stands between this project and an
unverified byte-path rewrite before 2a adds anything. This is the fact that makes 2a's existence
non-optional rather than a nice-to-have, and it leads § Testing below for that reason.

**Reachability, which drives 2a's PR order — re-derived in the round-6 amendments (§ A2), because
the first draft's account was directionally right and numerically loose in a way that changes what
2a-2 has to build.** Not every missed statement costs the same to reach. `channel_service.py` is
~90% reachable by a Django test-client request driving an in-process fake upstream with real Redis —
no subprocess needed, because switch/stop/metadata logic is pure Python and Redis calls.
`output/ts/generator.py` is ~80-85% reachable the same way.

**`server.py` is NOT ~70-75% reachable, and the estimate that said so is withdrawn — it was an
estimate, and it did not survive contact with the file.** Measured region by region by 2a-5's
planner, **222 of its missed statements are unreachable or must not be targeted at all**, and they
are the two largest-looking prizes in the file:

- **`cleanup_task` (161 missed) — the single biggest block in the file, and forbidden.** It is the
  source of the coverage gate's own run-to-run variance (see § Gate 2's ratchet paragraph): it ticks
  on its own interval and samples channels mid-shutdown. **A PR chasing it would make the
  measurement less trustworthy while appearing to improve it** — the worst possible trade, because
  the damage is invisible in the number that motivated the work.
- **`_cleanup_local_resources` (61 missed) — unreachable**, except from `cleanup_task` itself and an
  owner-only branch. Its non-owner cleanup arm sits under `if self.am_i_owner(channel_id):`, so a
  non-owner returns before reaching the branch written to handle non-owners — filed as
  [#230](https://github.com/D10Scot/Dispatcharr/issues/230). **These 61 are unreachable rather than
  untested**, so a coverage PR aiming at them is aiming at nothing. Not to be fixed (D5, and
  unreachable code is not observable behaviour); filed so 2d's deletion pass knows it is dead rather
  than load-bearing.

The reachable remainder is real but much smaller, and lives in the event listener loop,
`initialize_channel`'s failure branches, `check_if_channel_exists` and `_clean_zombie_channel`.
**The trap this replaces is specific**: "~70-75% reachable" points a reader at the biggest numbers
in the file, and in `server.py` the two biggest numbers are the two that cannot be taken.

**The other four figures in this paragraph are still estimates and have not been measured
region-by-region.** Only `server.py` has. Treat `~90%`, `~80-85%`, `~40-50%` and `~20-30%` as
untested guidance, not as budget: the one that *was* checked turned out to be wrong in the direction
that matters, and 2a-7 must not size anything against the other four without measuring them first. `input/manager.py` is only ~40-50% reachable without a
real subprocess: the transcode connection setup, the stderr reader and the health/reconnect loops
are shaped around a real ffmpeg process's stdout/stderr, and mocking that shape teaches nothing a Go
implementer can reuse. `output/fmp4/manager.py` is only ~20-30% reachable the same way. Those two
hold **1,024 missed statements between them** — the single biggest reason 2a is not "write more
Django tests" but "build a subprocess-capable harness first, then write tests against it."
`CLAUDE.md` § Testing already records the gap this fills: "No backend unit test spawns a
subprocess," and that is **confirmed** at `a948cd8a`: grepping every `test_*.py` under `apps/`,
`core/` and `tests/` for `posix_spawn`, `subprocess.Popen`, `subprocess.run`, `subprocess.check*`
and `import subprocess` returns exactly one file, `tests/test_credential_logging_guard.py`, which
shells out to a lint script — **zero backend tests spawn a media subprocess**.

**How much of the gap is genuinely subprocess-gated: ≈827 statements, not "roughly a thousand."**
`input/manager.py`'s `_establish_transcode_connection` (110), `_read_stderr` (47),
`_log_stderr_content` (22), `_parse_ffmpeg_stats` (28), `_monitor_health` (37), `_attempt_reconnect`
(36) and `_wait_for_existing_processes_to_close` (19) total 299; all of `output/fmp4/manager.py`
(253); all of `output/profile/manager.py` (185); and ~90 in `utils.py`'s `posix_spawn_proc`/`_Proc`.
Adding the fMP4 output surface, which needs fragments a remuxer produced — `output/fmp4/generator.py`
195 plus `output/fmp4/buffer.py` 102 — gives **≈1,124**. The three `input/manager.py` regions this
section names above (transcode setup, stderr reader, health/reconnect loops) total **483-552** on
their own; the 1,024 figure is the whole of both files, and ~143 of it (`_establish_http_connection`
26, `fetch_chunk` 56, `_close_socket` 61) is the raw-HTTP Proxy-profile path, which needs a socket
or a local HTTP server, not a subprocess.

**The finding that changes 2a-2's shape: two of the three spawn sites already sit behind one
function.** `output/fmp4/manager.py:129` and `:402` and `output/profile/manager.py:88` all obtain
their process from `posix_spawn_proc(...)` (`apps/proxy/live_proxy/utils.py:130`), which returns a
`_Proc` exposing `stdin`/`stdout`/`stderr`/`poll`/`wait`/`terminate`/`kill`. Substituting an object
of that shape at that single seam makes **438** of the 827 statements unit-testable **with no
forking at all**. `input/manager.py` is the hard case: its spawn is an inline `os.posix_spawn` at
`:793` with a hand-rolled Popen-compatible wrapper class at `:813`, wired to file descriptors the
manager built itself (stdin from `/dev/null`, stdout dup2'd onto a pipe it already owns as
`self.socket`), so it shares no seam with the helper and there is nothing to patch but
`os.posix_spawn` globally.

**The consequence, stated plainly: the 80% gate is reachable, but not by pure-mock unit tests.** It
needs either **(a)** a process fake at `posix_spawn_proc` *plus* the equivalent seam extracted in
`input/manager.py`, or **(b)** real-subprocess tests admitted to the backend suite for the first
time. Option (a) implies a **production-code change inside a stage otherwise scoped to tests**. That
change is small — give `input/manager.py`'s spawn a named helper alongside the one the other two
managers already call, generalized for the file actions it needs, instead of a bare `os.posix_spawn`
at the call site — and it is explicitly **not** the "simplify this back to `Popen`" `CLAUDE.md`
forbids: `os.posix_spawn` is retained exactly as it is, only the call site moves behind a name.
**This is an open decision for 2a-2's plan, flagged to the user rather than settled here**; 2a-2's
row in § The seven PRs records it as such, and nothing downstream in this spec assumes either
answer.

**The internal contract, every route, header and timeout as shipped.** `apps/proxy/relay_client.py`
(411 lines) and `apps/proxy/control_plane.py` (337 lines), both read in full — see § The contract for
the complete table; summarized here because everything in 2c depends on it being exact:

- Django → relay, through the API role's own nginx (never a raw port — the relay has no `http =`
  listener, D5 of Phase 1): `GET /proxy/relay/channels[?clients=all]`,
  `GET /proxy/relay/channels/<id>[?fields=state]`, `DELETE /proxy/relay/channels/<id>`,
  `DELETE /proxy/relay/channels/<id>/clients/<client>`, `POST /proxy/relay/channels/<id>/advance`.
  Timeouts: `TUNE_TIMEOUT = (1, 2)`, `ADMIN_TIMEOUT = (2, 5)`, `ADVANCE_TIMEOUT = (2, 20)`. No
  retries on any of the five.
- Relay → Django: `POST /api/relay/channels/<id>/next-source`, `POST /api/relay/channels/<id>/
  release`, `POST /api/relay/events`. Timeout `(2, 5)`, `ATTEMPTS = 2` (one retry),
  `RETRY_DELAY = 0.1`.
- Every one of the eight carries `X-Dispatcharr-Internal` (static) **and**
  `X-Dispatcharr-Internal-Request` (bound, `v1.<unix-ts>.<hex>`, 120s window) — see § What the code
  says.

**`docker/uwsgi.relay.ini` (78 lines, read in full).** `socket = 0.0.0.0:$(DISPATCHARR_RELAY_PORT)`,
no `http =` listener at all, `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)` (default 1600),
`listen = 1024`, no `harakiri`. `DISPATCHARR_RELAY_PORT` defaults to 5657
(`docker/entrypoint.sh`/compose). **Port 5658 for the Go relay is therefore free** — nothing in the
tree binds it, confirmed by `grep -rn 5658 docker/ apps/` returning nothing on `a948cd8a`.

**`docker/nginx.conf`'s live-bound locations, verified in full (526 lines).** `location ^~
/proxy/ts/stream/`, `location ^~ /live/`, and `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`
(the XC 3-segment root, which only ever matches `xc_stream_endpoint`/`xc_live_stream_endpoint` per
§ What the code says) are the three locations D1 below moves to Go. Each carries `uwsgi_buffering
off`, `uwsgi_pass $relay_upstream`, and the `$relay_name`-keyed `map` from ADR 0005. `location ^~
/proxy/vod/`, `^~ /movie/`, `^~ /series/`, `^~ /timeshift/` and `= /streaming/timeshift.php` are
unaffected by this spec — they keep pointing at `relay_py` (the Python relay's `uwsgi_pass` upstream)
for the whole of Phase 2.

**Redis key families the relay itself owns, from `apps/proxy/live_proxy/redis_keys.py` (161 lines,
read in full) and `apps/proxy/live_proxy/constants.py` (125 lines, read in full) — corrected counts
from this spec's first draft, which undercounted both groups.** **Eighteen** `RedisKeys` methods
produce the `live:channel:{id}:*` family: `channel_metadata`, `buffer_index`,
`buffer_chunk`/`buffer_chunk_prefix`, `channel_stopping`, `client_stop`, `events_channel`
(`live:events:{id}` pub/sub), `switch_request`, `channel_owner`, `clients`,
`last_client_disconnect`, `connection_attempt`, `last_data`, `switch_status`,
`chunk_timestamps`, `transcode_active`, `client_metadata`, and `channel_source_cache` (the
degraded-fallback candidate cache Phase 1 PR 6 introduced) — 18, not the fourteen this spec first
counted. `worker_heartbeat(worker_id)` is keyed on a worker, not a channel, and is not part of this
family at all — this spec's first draft folded it in by mistake. **Seven**, not five, `output_*`
methods extend the same family for the fMP4 buffer: `output_buffer_index`, `output_buffer_chunk`,
`output_buffer_chunk_prefix`, `output_init`, `output_state`, `output_owner`,
`output_chunk_timestamps`. Two more, `channel_stream(channel_pk)` and `stream_profile(stream_id)`,
are explicitly documented in the module as **Django-owned**: "Written only by
`apps/channels/models.py` ... reached only through `apps/proxy/next_source.py`." Every method in
the first two groups (25 total) is a candidate for D2's "becomes memory, not Redis"; the third
group was never relay state and stays Django's. § Stage 2c's invariant walk names where each of the
25 ends up — the first draft's walk covered only about half of them, and is corrected there too.

**Build and CI versions, resolved 2026-09-09 — the resolution method is what this spec commits to,
not the pinned values, since patches land monthly:**

- Go **1.27.1**, per `https://go.dev/dl/?mode=json` (`"stable": true`, highest version listed).
- Builder stage `golang:1.27.1-bookworm@sha256:648f440f42a0958804efb24df176f806f9d353b41f1c0627f666
  428e40310f6b`, resolved with `docker buildx imagetools inspect golang:1.27.1-bookworm` against the
  official `library/golang` namespace — the same tool `CLAUDE.md` § Supply chain security prescribes
  for every other `FROM`.
- `golangci-lint` **v2.13.2**; `golangci/golangci-lint-action` **v9.3.0** @
  `ba0d7d2ec06a0ea1cb5fa41b2e4a3ab91d21278a`.
- `actions/setup-go` **v7.0.0** @ `b7ad1dad31e06c5925ef5d2fc7ad053ef454303e`; `actions/checkout`
  **v7.0.1** @ `3d3c42e5aac5ba805825da76410c181273ba90b1`. Both resolved with
  `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha` against the `actions`/`golangci` orgs — the
  publisher-first check `CLAUDE.md` requires before trusting a SHA.
- **Drift, found while resolving the above and worth fixing before a third generation of pins
  exists**: the ten hand-written workflows sit on `actions/checkout` v6.1.0, `actions/setup-node`
  v4.4.0, `actions/upload-artifact` v4.6.2, `actions/download-artifact` v4.3.0, while the five gh-aw
  `.lock.yml` files are already on v7.0.1/v7.0.0/v7.0.1/v8.0.1, because `gh aw compile` re-pins
  current versions on every run and nothing re-pins the hand-written files. Renovate would catch
  this but is not installed on the repo (`CLAUDE.md` § Build reproducibility). Worth fixing, but —
  per M14 in this spec's own fix history — **not as a PR inside this phase**: none of the user's
  decisions requires it, it touches ten zizmor-zero-findings files unrelated to Go, and a new
  workflow pinning current versions is correct regardless of what the ten existing ones pin. Flagged
  here as a recommendation for a separate `chore/` PR off `main`, or for installing Renovate (a
  repo-settings action); `go-tests.yml` (2c-1) does not depend on it.

## Decisions

| # | Decision | Why |
|---|---|---|
| **D1** | **Scope: live TS only.** The Go relay serves `/proxy/ts/stream/<id>` and the XC live roots (`live/<user>/<pass>/<id>`, bare `<user>/<pass>/<id>`). The Python relay keeps `/proxy/vod/`, `/proxy/catchup/` and `/streaming/timeshift.php`; `apps/proxy/vod_proxy/` and `apps/timeshift/` are untouched. | § What the code says confirms the XC live roots are already routing-distinguishable from VOD/catch-up with no shared regex to split, so this is a location-table decision, not a routing redesign. It also matches where the coverage and defect weight actually is: `live_proxy` is 43.1% covered and holds every failover trigger and the ownership lease; `vod_proxy` (35.6%, `CLAUDE.md`) is a separate, simpler shape — stateless, one upstream per session, no ring buffer — that gains nothing from Go's concurrency model and would only enlarge this phase. |
| **D2** | **The ring buffer lives in process memory from day one.** Live video bytes never enter Redis. Ownership becomes `map[uuid]*Channel` behind a `sync.RWMutex`; the lease, the follower path, `_ensure_owner_or_stop`, the 10-second process-local cache and the three fail-open paths (`server.py`'s `_execute_redis_command` swallowing to `None`, `release_ownership`'s non-atomic GET→compare→DELETE, `extend_ownership`'s non-atomic GET→EXPIRE) are **deleted, not ported**. | A Go relay is one process per host by construction (no gevent single-worker precedent to preserve), so there is never a second writer to fence against — the un-fenced lease `CLAUDE.md` records as a real defect (`StreamBuffer.add_chunk()` writes with no ownership check) has no analogue to carry forward. Porting a Redis-backed buffer into Go only to delete it in Phase 3 wastes a release cycle proving a data structure this design already knows it will remove. **Consequence, stated plainly**: Phase 3's live half is absorbed here. Phase 3 shrinks to deleting the Python ring-buffer code (2d does that), rewriting the greybox quarantine (2d does that too), and whatever Redis coupling VOD/catch-up still carry — unrelated to this spec, a smaller Phase 3 than the route page originally sized. |
| **D3** | **Hard cutover, no coexistence.** No per-channel canary, no second relay-name map entry live at once. One release flips the live nginx locations from `relay_py` to `relay_go`; `apps/proxy/live_proxy/` is deleted inside this phase (2d); rollback is a container image rollback, not a per-channel flag. | ADR 0005 built the `$relay_name` header and the nginx `map` explicitly so "Phase 2's canary... becomes a second map entry... not a code change on either side" — a real, ready mechanism this decision declines to use. The reason: a canary needs the *old* relay's ownership lease and ring buffer to coexist correctly with channels the *new* relay owns, on the same Redis DB, for the whole canary window — exactly the fenceless-lease and split-brain-key hazards `CLAUDE.md` already documents as live defects, now doubled by having two independent implementations of the owner-election protocol running against the same keys. D2's "buffer in memory, not Redis" makes a byte-level handoff between the two relays for one in-flight channel impossible to do safely in the time this phase has, and a channel-level canary (some channels on Python, some on Go, split by the map) still shares the provider-slot counter and the failover event stream with whichever relay is *not* serving a given channel. Cost, stated honestly: a production defect in the Go relay reverts the whole live path for every viewer, not one channel — the trade this phase makes deliberately, once, rather than carrying dual-implementation risk through a canary window of unknown length. |
| **D4** | **No live client keys need to exist in Redis at all**, because `GET /proxy/relay/channels?clients=all` already serves that need and the Go relay must implement it anyway. | `apps/proxy/utils.py:256-283`'s `_live_connections(user_id)` — the live half of `get_user_active_connections`, called by `authorize_stream` on every tune via `check_user_stream_limits` — already calls `relay_client.list_channels(all_clients=True, timeout=relay_client.TUNE_TIMEOUT)`, i.e. it already asks the relay over HTTP rather than scanning `live:channel:*:clients:*` directly; that scan was removed in Phase 1 PR 7. Verified by reading the function in full: it fails open (a relay that cannot answer contributes nothing, logged once) and is documented as deliberately so — "the relay is the only process serving live clients, so a relay that is not answering has none." The Go relay reproducing this route byte-for-byte (§ The contract) closes the loop with zero new Redis state. |
| **D5** | **Strict behavioural parity, defects included** — the three failover triggers and thresholds, threshold snapshotting at channel start, the monotonic never-reset chunk index, the ~5s-behind-live join, 188-byte TS realignment, the cumulative `speed=` average's ~55s arming delay, `MAX_STREAM_SWITCHES` not bounding buffering-triggered switches, and fMP4's `_is_timeout()` lacking the TS generator's `url_switching` exemption. These get filed as issues against the parity matrix, not fixed in transit. Two named exceptions: **(1) process-lifecycle hygiene** — Go spawns ffmpeg with `SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}`, closing the orphaned-ffmpeg-holds-a-provider-slot defect (`CLAUDE.md` § Operationally: "`os.posix_spawn` runs with no `setsid`/`PDEATHSIG`"), because no test asserts the current behaviour and it is process hygiene, not streaming behaviour a client can observe. **(2) The dev authorize path** — with no nginx, there is no `auth_request`; a Go relay cannot call `apps/proxy/authorize.py`'s `authorize_stream` in-process (it is Python). When the trust marker is absent, the Go relay makes an HTTP call to a new Django endpoint, `POST /_dispatcharr/authorize-internal` — its own path, not the existing nginx-facing one, for a reason § The contract states in full — reaching the same `authorize_stream()` decision function over HTTP instead of a Python import. **Two requirements in § The contract are load-bearing for this exception, and both fail silently rather than loudly**: the view builds every one of `authorize_stream`'s inputs from the request body and inherits nothing from the transport request (else the internal-principal question answers itself and everything authorizes), and it resolves a session principal through the session store rather than `request.user` (else a session viewer is downgraded to anonymous and still gets a 200 with bytes). | A rewrite that also changed behaviour would make every regression ambiguous between "the port is wrong" and "the fix changed something." Parity is what makes the ~63 portable tests (§ Verified facts) a meaningful safety net rather than a moving target. The two exceptions are chosen narrowly: neither is externally observable streaming behaviour a Playwright spec could assert differently, and the second is required by D2/D3's own shape (dev has no nginx, and Go has no Django import path), not a discretionary fix folded in for convenience. |
| **D6** | **Ships drain-on-SIGTERM, `/healthz`, `/readyz`, wired to supervisord `stopwaitsecs` and a Docker `HEALTHCHECK`. No Prometheus metrics.** | `CLAUDE.md` § Operationally records the current relay's shutdown as bounded-not-graceful (`die-on-term`, no drain) and the deployment as having no readiness probe at all — both real gaps this phase can close in a language where a drain loop and a health endpoint are a few dozen lines, not a gevent-compatibility exercise. Metrics are declined because nothing scrapes them today and the metrics dashboard (`metrics/curated/`) is engineering data assembled from git/CI/issue history, not a runtime target — adding a `/metrics` endpoint with no consumer is exactly the scope-widening `CLAUDE.md` warns against. |
| **D7** | **Two coverage gates, not one, and the second blocks the first line of Go code.** Gate 1: the parity matrix is 100% pinned — no row still marked `owed:` — enforced by a guard test, and met in **2b-3**, not at the end of 2a, since row 18 is a question only 2b-3 can answer (§ A6/A7). Gate 2: ≥80% statement coverage on `apps/proxy/live_proxy/**` plus the Phase 1 boundary modules (§ Stage 2a names the exact ten), measured by `scripts/coverage_live_path.sh` and enforced as a ratchet floor file, in `lint.yml`'s idiom for zizmor's zero-findings rule. **AMENDED after 2a was measured: the ratchet ships in 2a-7 at the measured 74.30%; the ≥80% threshold itself is met in `2b-4`.** Both halves still gate 2c — the ratchet from 2a-7 onward, the threshold from 2b-4 — so this decision's force is unchanged and only its schedule moved (§ Stage 2a › Gate 2, amended). **No PR in stage 2c may merge until both gates are green**, recorded as CI-enforced in 2c's own PRs, not left to review discipline. | The 63 portable tests alone are not enough to catch a subtle regression in, say, the buffering detector's cumulative-average arithmetic — `log_parsers.py` is 69% covered and 235 statements of exactly the logic a byte-for-byte port has to get right. Gating Go's *start* on coverage, not just its *finish*, is what stops "write the matrix, then start porting while coverage catches up" — a sequencing this phase's own §2a reachability numbers show is expensive to do after the fact (the two hardest files to cover, `input/manager.py` and `fmp4/manager.py`, are exactly the two a Go implementer needs most while porting). |

## Architecture

### Before (end of Phase 1)

```
                         ┌─────────────────────────────┐
        /               │  api-uwsgi (4 workers,        │
        /api/            │  gevent=400, harakiri=120s)   │◄── nginx: everything
        /output/, /hdhr/  │  Django app, urlconf shared    │     except long-lived
        /proxy/ts/status  │  with the relay process (D1,   │     streams
        /proxy/relay/*    │  Phase 1)                      │
   ┌───►│  authorize_stream() lives here                    │
   │    └─────────────────────────────┬───────────────────┘
   │                                  │ POST /api/relay/…  (control_plane.py)
nginx auth_request                    │ (next-source, release, events)
once per tune              ┌──────────▼──────────────────────────┐
                            │  relay-uwsgi (1 worker, gevent=1600, │
                            │  no harakiri) — SAME Django app       │◄── nginx: /proxy/ts/stream/,
                            │  live_proxy/ + vod_proxy/ +            │     /proxy/vod/, /proxy/catchup/,
                            │  timeshift streaming views             │     /live/, /movie/, /series/,
                            │  Ring buffer, ownership lease,          │     /timeshift/, XC roots,
                            │  client sets: ALL in Redis DB 0          │    /streaming/timeshift.php
                            └──────────┬───────────────────────────┘
                                       │ GET/DELETE/POST /proxy/relay/…  (relay_client.py)
                                       ▼
                            Redis DB 0: video bytes, lease, client sets,
                            switch_request, source_cache, output buffers —
                            all "live:channel:{id}:*", one process's private state
```

### After (end of Phase 2)

```
        /               ┌────────────────────────────┐
        /api/            │  api-uwsgi — unchanged        │
        /output/, /hdhr/  │  authorize_stream() unchanged  │
   ┌───►│  now also serves POST /_dispatcharr/            │
   │    │  authorize-internal, its own new path, for the   │
   │    │  Go relay's dev fallback (D5, § The contract)     │
   │    └────────────┬──────────────────┬─────────────────┘
   │  auth_request     │ POST /api/relay/…│ POST /api/relay/…
   │  (unchanged        │ (unchanged        │ (unchanged wire
   │  wire contract)     │ wire contract,    │  contract, now
   │                      │  Go relay is the  │  the Python relay,
   │                      │  caller)          │  narrowed scope)
   │           ┌──────────▼────────┐  ┌───────▼──────────────────┐
   │           │ relay-go, port     │  │ relay-uwsgi (unchanged    │
   │           │ 5658 (new).         │  │ process, narrowed scope): │◄ nginx: /proxy/vod/,
   │           │ Ring buffer:         │  │ vod_proxy/ + timeshift/   │  /proxy/catchup/,
   │           │ map[uuid]*Channel     │  │ streaming views; Redis    │  /movie/, /series/,
   │           │ in process memory,     │  │ coupling for those TWO    │  /timeshift/,
   │           │ sync.RWMutex. No        │  │ surfaces unchanged        │  /streaming/timeshift.php
   │           │ Postgres driver, no      │  │ (Phase 3's remaining      │
   │           │ Redis client (D2's        │  │ scope)                    │
   │           │ invariants)                 │  └────────────────────────┘
   │           └──────────┬──────────────┘
   │ auth_request           │ GET/DELETE/POST /proxy/relay/…  (byte-identical
   │ nginx: /proxy/ts/       │  JSON, same routes, same headers — § The contract)
   │ stream/, /live/,         ▼
   │ XC live roots         Nothing. relay-go's own state never touches Redis;
   └────────────────────► `live:channel:{id}:*` for the live surface is gone.
```

The two processes are peers of Django's control plane, not of each other: `relay-go` never calls
`relay-uwsgi` and vice versa, because D1 gives them disjoint URL spaces and neither surface's
failover, client list or status ever needs the other's state. The only shared fact is
`profile_connections:{id}`, which was never relay state (ADR 0005: "Slots stay in Django") and
is unaffected by which process serves a given tune.

## The contract

**Every route, header and timeout the Go relay must reproduce, verified against `a948cd8a`.**

### Relay → Django (Go relay calls Django; same shape `apps/proxy/control_plane.py` already
implements for the Python relay)

| Route | Method | Timeout | Body | Notes |
|---|---|---|---|---|
| `/api/relay/channels/<id>/next-source` | `POST` | connect 2s / read 5s, 1 retry at 0.1s | `{exclude_stream_ids, reason, current_url?, target_stream_id?, current_stream_id?, include_alternates?}` | Answers `{source, alternates, error?}`. A 404 (channel deleted mid-playback) is a mapped `{"source": null, "alternates": [], "error": "identifier not found"}`, not an error — `apps/proxy/control_plane.py:158-165`, read in full. |
| `/api/relay/channels/<id>/release` | `POST` | connect 2s / read 5s, 1 retry | `{stream_id?, m3u_profile_id?, channel_pk?}` | Answers `{released: bool}`. |
| `/api/relay/events` | `POST` | connect 2s / read 5s, 1 retry | `{events: [{type, channel_id?, channel_name?, client_id?, stream_id?, details}]}` | Fire-and-forget from the relay's side — never blocks the byte path; a failed batch logs once per outage transition, not once per event (`_events_down` module flag, `control_plane.py`). |

All three: `Content-Type: application/json`, `X-Dispatcharr-Internal: HMAC(SECRET_KEY,
"internal-principal")`, and `X-Dispatcharr-Internal-Request: v1.<unix_ts>.<hex>` — **the second
field the bound token signs is `request.get_full_path()`, the full path including the query
string, not the bare path**, corrected from this spec's first draft, which published `PATH` and
would have 403'd every call carrying one. Verified against `apps/proxy/internal_auth.py:179-185`,
whose own comment states the reasoning: "`get_full_path()`, not `path`: the query string is part
of what a caller is asking for, so it has to be part of what the token binds... They are the same
string when there is no query, which is why every call PR 6 shipped verifies unchanged." Two of the
five Django→relay routes below carry a query string (`?clients=all`, `?fields=state`), and one of
those — `?clients=all` — is the exact route D4's whole argument rests on, so this correction is not
cosmetic. The exact byte layout, from `internal_auth.py:126-162` read in full:

1. `message = b"\n".join([b"internal-request", METHOD.upper().encode(), FULL_PATH.encode(), str(int(timestamp)).encode(), sha256(BODY or b"").hexdigest().encode()])` — five fields, joined on the literal byte `\n`, where `FULL_PATH` is the caller's full path **with its query string**, `BODY` is the raw request body (an empty body hashes as `sha256(b"")`, not an empty string), and `timestamp` is the Unix time in seconds.
2. `token = hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()` — the outer HMAC, over UTF-8 `SECRET_KEY`.
3. The header value is `f"v1.{timestamp}.{token}"` — a literal version prefix `v1`, then the same timestamp, then the hex digest, joined on ASCII `.`.
4. The verifier splits the header on `.` into **exactly three** parts, rejects anything else, checks `parts[0] == "v1"`, and accepts a timestamp **symmetrically** within the window — `abs(now - timestamp) > 120` rejects, so a token up to 120s in the *future* is accepted too, not only one up to 120s old.

`allow_redirects=False` semantics must be reproduced too: a 3xx is treated as an outage, never
followed, because following would re-send the signed internal headers to whatever a stray
`return 301` names.

### Django → relay (Django calls Go; same shape `apps/proxy/relay_client.py` already implements
for the Python relay, over the API role's own nginx, never a raw port)

| Route | Method | Timeout | Query/Body | Replaces |
|---|---|---|---|---|
| `/proxy/relay/channels` | `GET` | `ADMIN_TIMEOUT` (2, 5) | `?clients=all` optional | `fetch_channel_stats`, `/proxy/stats/` |
| `/proxy/relay/channels/<id>` | `GET` | `TUNE_TIMEOUT` (1, 2) for `?fields=state`; `ADMIN_TIMEOUT` otherwise | `?fields=state` optional | `channel_status`'s Redis reads |
| `/proxy/relay/channels/<id>` | `DELETE` | `ADMIN_TIMEOUT` (2, 5) | — | `stop_channel` |
| `/proxy/relay/channels/<id>/clients/<client_id>` | `DELETE` | `ADMIN_TIMEOUT` (2, 5) | — | `stop_client` |
| `/proxy/relay/channels/<id>/advance` | `POST` | `ADVANCE_TIMEOUT` (2, 20) | `{url, user_agent?, stream_id?, m3u_profile_id?, stream_name?, reset_tried?}` | `change_stream`/`next_stream` |

Same two headers as above on every request; no retry on any of the five (`relay_client.py`'s own
comment: "a retried advance switches twice, a retried stop doubles an admin's wait"). Response
bodies must be **byte-identical JSON** to what `apps/proxy/relay_serializers.py`'s six serializers
produce today (`RelayChannelListSerializer`, `RelayChannelDetailSerializer`,
`RelayChannelStateSerializer`, `RelayStopResponseSerializer`, `RelayAdvanceRequestSerializer`,
`RelayAdvanceResponseSerializer`, all read in full above) — Django's own wrappers
(`live_proxy/views.py`'s `channel_status`, `stop_channel`, `stop_client`, `change_stream`) and the
frontend's `api.js` must not notice which language answered. Notable field-level quirks the Go
relay must reproduce exactly, per D5:

- **`owner`**: `null` default on the **list** endpoint (`GET /proxy/relay/channels`,
  `RelayChannelSerializer` over `get_basic_channel_info`), the literal string `'unknown'` default
  on the **detail** endpoint (`GET /proxy/relay/channels/<id>`, `RelayChannelDetailSerializer` over
  `get_detailed_channel_info`) — asymmetric, verified above (this direction, corrected from this
  spec's first draft, which had list and detail swapped), and not something to "fix while we're in
  there."
- **`ffmpeg_speed`**: a float on the wire on both endpoints (already true in Python; § What the code
  says). **Do not** reintroduce the historical string/float split reading `CLAUDE.md`'s stale
  wording literally.
- **`source_fps`**: the opposite of `ffmpeg_speed` — **still** a string on the detail endpoint and a
  float on the list endpoint, per `CLAUDE.md` § Observing a channel ("`source_fps` still disagrees —
  a string on the per-channel endpoint, a float on the collection one — and is carried, not fixed").
  Parity holds this one exactly as split as it is today; do not "fix" it to match `ffmpeg_speed`'s
  now-unified shape.
- **`state`**: `null`, never the string `'unknown'`, on both endpoints (Phase 1 PR 7 fixed this;
  parity holds it fixed).
- Optional fields are **absent from the JSON entirely** when the source dict never set them, not
  present as `null` — `relay_serializers.py`'s own docstring: fields are declared `required=False`
  with **no** `default=`, so DRF's `Field.get_attribute` raises `SkipField` for a genuinely missing
  key. A Go JSON encoder must use pointer/omitempty semantics field-by-field to match, not a single
  "encode the struct" pass, because several fields are `allow_null=True` (rendered as `null` when
  present-but-None) while sitting beside others that must vanish entirely when absent — the same
  distinction `RelayChannelStateSerializer`'s own docstring calls out as a DRF-specific trap
  (`get_attribute` checks `default`, then `allow_null`, before `required`).

### The dev fallback (D5, exception 2)

New route, Django side: **`POST /_dispatcharr/authorize-internal`** — its own path, not
`/_dispatcharr/authorize`, corrected in this fix round (§ NM4 in the round-2 review: reusing the
existing path would have been silently unreachable in every nginx-fronted deployment, see below) —
same `authorize_stream()` call, reached over HTTP because a Go process cannot import Python. Used
only when the Go equivalent of `request_is_relay_trusted()` finds no valid `X-Dispatcharr-Authorized`
marker, i.e. only in `dev`/`debug` or any nginx-less deployment shape — on every ordinary
nginx-fronted tune this route is never called, matching the Python relay's own inline-fallback
frequency today. This spec's first draft under-specified what the call needs;
`authorize_stream` (`apps/proxy/authorize.py`) takes far more than a URI, and each gap below is a
real hole if left unaddressed, not a simplification:

**Why the distinct path matters, and what it protects.** `docker/nginx.conf:116` declares
`location = /_dispatcharr/authorize { internal; ... }` — an **exact-match** location, which wins
outright over every prefix and regex location (`nginx.conf:58-61`'s own comment states the rule),
and `internal;` makes it unreachable to any external client, pinned by
`nginx-stream-buffering.spec.ts:273-276`. A `POST` to the *same path* is 404'd by nginx before
Django ever sees it, in every nginx-fronted deployment — the method does not matter, only the
location match does. That is harmless for the fallback's intended use (nginx-less dev has no nginx
to 404 it). It is not harmless for the failure mode Phase 1 deliberately made safe: when nginx's
rendered `RELAY_TRUST_TOKEN` and a relay's own derived token disagree — a `SECRET_KEY` mismatch
between roles, or `/data/jwt` rotated under a non-idempotent `03-init-dispatcharr.sh` restart —
`request_is_relay_trusted()` returns `False` and, today, the Python relay's tune falls through to an
inline `authorize_stream` call, warning once per process
(`apps/proxy/authorize_views.py`'s `_TRUST_MISMATCH_WARNED`). The outcome today is fail-safe but
silent: streams keep working. Reusing `/_dispatcharr/authorize` for the Go fallback would turn that
same mismatch into every live tune failing outright post-cutover (the Go relay's own HTTP fallback
would also 404), trading a currently-degraded mode for a total outage on a fault the repo has
already named a flag for. A distinct, non-`internal` path sidesteps the shadowing entirely and lets
the Go relay's fallback work in every shape exactly as designed, preserving today's degrade behaviour
rather than spending it. `2c-8`'s scope (§ Stage 2c) names this route explicitly, and § Risks records
the trust-mismatch failure mode as a risk this fix closes rather than leaves open.

- **The network ACL is evaluated against the request's own address** (`authorize.py:425`,
  `network_access_allowed(http_request, _acl_key(surface), user)`). If the Go relay POSTs from its
  own process, Django would evaluate the STREAMS ACL against the *relay's* address, not the
  client's — wrong in exactly the deployments (nginx-less dev) this fallback exists for, since there
  is no `auth_request` subrequest inheriting the original request's headers to save it. The client's
  real address travels as `client_ip` in the signed request body — see below, not as a header —
  mirroring what `docker/nginx.conf`'s server block already gives the normal path for free.
- **The principal is resolved from the request itself, and every piece of it belongs in the signed
  request body, not in a header — corrected in this fix round (§ M-R3-1 in the round-3 review).**
  ADR 0005's accepted set (Xtream credentials, JWT, API key, query-param JWT, session, or anonymous)
  lives in the `Authorization` header, cookies, the query string, or the URL path today; the Go
  relay's first draft of this call forwarded those as literal headers on the internal POST. **That is
  a real hole, not a simplification**: the bound token (`internal_auth.py:126-152`,
  `internal_request_token`) signs exactly five fields — the literal context, method, path, timestamp,
  and `sha256(body)` — and headers are not among them. A single captured
  `X-Dispatcharr-Internal-Request` token for `POST /_dispatcharr/authorize-internal` would have
  stayed valid for 120 seconds against **any** combination of forwarded headers, since only the
  outer envelope (method + path + timestamp + an empty body's hash) was ever bound — swap the
  `Authorization` header or the URI on a replayed request and the signature does not notice, because
  none of that material was ever inside what `sha256(body)` covers. That is the same authorization
  oracle the gating bullet below exists to prevent, reintroduced one layer down through an unsigned
  side-channel.

  **Fix: no identity-bearing material may travel as a header on this route. The question being
  asked is the POST body, in full, so `sha256(body)` binds it.** Body shape — **two fields added in
  a second correction this same fix round (§ round-4 review), both load-bearing, not polish**:

  ```json
  {
    "uri": "/live/user/pass/12345?token=...",
    "client_ip": "203.0.113.7",
    "internal": false,
    "headers": {
      "authorization": "Bearer ...",
      "cookie": "sessionid=...",
      "x-api-key": null
    }
  }
  ```

  `uri` is the equivalent of `X-Original-URI` — the full path, query string included, that
  `authorize_view`'s nginx-facing form already resolves a surface from (`_surface_for`,
  `authorize_views.py`); `client_ip` is the address the ACL and, in production, `X-Relay-Client-IP`
  both need. `headers` carries every credential-bearing header `authorize_stream`'s authenticator
  union can consume — **not two, but three: `authorization`, `cookie`, and `x-api-key`**, corrected
  from this round's first pass, which named only the first two and missed that
  `ApiKeyAuthentication` (`apps/accounts/authentication.py:46-85`) checks `X-API-Key` **before**
  falling back to an `Authorization: ApiKey …` header — a client authenticating that way would
  silently resolve to anonymous in the nginx-less shape and to its real user in production, the
  exact cross-shape divergence D5 exists to prevent. Shaping it as a `headers` sub-object rather
  than three flat fields is deliberate: a fourth credential header discovered later is a field, not
  a body-shape redesign. Every field in `headers` is `null`, not absent, when the client sent
  nothing for it.

  **`internal` is the fifth field, and it closes a BLOCKING finding, not a stylistic one — reusing
  the transport's own `X-Dispatcharr-Internal` header to answer "is this an internal principal" is a
  total authorization bypass, verified against `authorize.py`.** `authorize_stream`
  (`authorize.py:417-419`) reads `is_internal = request_is_internal(http_request)` off **the same
  request object it is handed**, and `_resolve_principal`'s first two lines (`:309-310`) are
  `if is_internal: return INTERNAL_PRINCIPAL` — before any credential, channel flag or stream limit
  is even looked at (`_apply_channel_checks` returns immediately for an internal principal,
  `authorize.py:376-377`; the stream-limit block never runs because `user` is `None`,
  `authorize.py:436-442`; the XC credential check is never reached). `IsInternalRelay` **requires**
  the Go relay to send `X-Dispatcharr-Internal` on this very POST — it is one of the two headers the
  gating bullet below mandates. If the Django view then calls `authorize_stream` with the incoming
  request unchanged, `request_is_internal` reads that same header and returns `True` for **every**
  tune in **every** nginx-less deployment, unconditionally — `hidden_from_output`,
  `hide_adult_content`, channel-profile membership and the XC credential check all vanish, silently,
  because everything simply authorizes. The header answers two different questions in Phase 1's own
  design — "this caller is part of the deployment" (the static token) and "this *request*, from the
  *client*, is internal" (what `authorize_stream` actually asks) — and this route, by construction,
  collapses them onto one transport header that can only ever answer the first.

  **Fix: the internal-principal question travels in the body too, and the view must build the
  request it hands to `authorize_stream` from the body's `internal` field, never pass its own
  incoming request through unchanged.** The Go relay sets `internal: true` only when it is relaying
  the DVR's own request (the DVR's `run_recording` fetch already carries the static
  `X-Dispatcharr-Internal` header with no bound counterpart, per ADR 0005 — `internal_auth.py:45-49`
  — and the Go relay, which verifies that header the same way `request_is_relay_trusted`-equivalent
  logic does elsewhere in this design, can tell), and `false` for every ordinary client tune. The
  view constructs a request (or a lightweight object presenting the same `.META` interface) whose
  `HTTP_X_DISPATCHARR_INTERNAL` is set from `internal_principal_token()` when the body says `true`
  and is **absent** when it says `false` — never copied from the transport request's own header,
  which exists only to satisfy `IsInternalRelay` and must never leak into the question
  `authorize_stream` answers. Being in the body, `internal` is inside `sha256(body)`, so it inherits
  the same replay binding as `uri`/`client_ip`/`headers` — a captured token cannot be replayed to
  turn a client tune into an internal one, closing the same class of hole `M-R3-1`'s fix closed for
  the rest of the question.

  **Consolidating this and the two bullets above (round-5 review, MINOR 1): the view builds the
  entire request it hands to `authorize_stream` from the body, and inherits nothing from the
  transport request.** `REMOTE_ADDR` comes from `client_ip`; the path and query string
  `_surface_for` resolves the surface from — and that `authorize_views.py:299` also reads
  `session_id` off of, for the catch-up surface — come from `uri`; the three credential headers
  come from `headers`; `HTTP_X_DISPATCHARR_INTERNAL` comes from `internal`. Every one of
  `authorize_stream`'s inputs is a body field, none is read off the incoming POST — adjusting only
  the one field named above and passing the rest of the transport request through unchanged would
  silently reopen the ACL bullet's own hole (`REMOTE_ADDR` back to the Go relay's own address) even
  after the internal-principal bypass is closed, which is exactly the partial fix this sentence
  exists to rule out.
- **The session principal must be resolved from the session store, never from `request.user` — and
  getting this wrong is a silent authorization downgrade, not an error.** This is a requirement on
  2b, not an implementation detail; the previous draft demoted it to one and that demotion is
  withdrawn. `authorize_view` carries `@authentication_classes([])` (`authorize_views.py:241`) and
  **DRF authenticates anyway**: `@api_view`'s own `dispatch()` runs `perform_authentication`
  regardless, setting `request.user` to `AnonymousUser` before `authorize_stream` is ever called.
  That is exactly why `_session_user` (`authorize.py:268-287`) calls
  `django.contrib.auth.get_user(http_request)` instead of reading `http_request.user`, and why
  `_drf_user` (`:227-265`) restores `http_request.user` on a miss — both functions say so in their
  own docstrings, and are otherwise inexplicable. **So the synthesised request needs Django's
  session machinery run over the body's `cookie` value**, and the resolution must go through the
  session store.

  **The failure signature is what makes this dangerous.** A view that forwards the cookie but
  resolves the principal from `request.user` turns a session viewer into an anonymous one. Nothing
  errors. A `hidden_from_output` channel still 403s, so the visible half of authorization looks
  correct — while an ordinary channel **streams: a 200, with real bytes**. The only thing that has
  changed is that `user_level`, Channel Profile membership, adult filtering and the per-user stream
  limit have quietly stopped applying. This is the same collapse as the internal-principal bypass
  two bullets above, one level down — "DRF authenticated this request" is not "the decision function
  knows who the caller is", just as "this caller is part of the deployment" is not "this request is
  internal" — and it lands in the same place, the fallback's request synthesis.

  **2b's test for this asserts the resolved identity, never a status code.** A status-only assertion
  cannot detect the downgrade, because the downgraded path returns the same 200. The assertion is on
  the decision's own output — `X-Relay-User` carrying the expected user id. 2a-5's row-23 test is
  built with exactly that property, so 2b inherits a test that already fails if the fallback gets
  this wrong; it should be run against the new endpoint rather than replaced.
- **The route must be gated, not open — and gating it is now the *only* protection it has, since it
  no longer sits behind nginx's `internal;` location the way the existing GET/HEAD view does.**
  `authorize_view` today is `AllowAny` but is reachable only through nginx's `internal;` location —
  there is no client path to it at all in production. The new `POST /_dispatcharr/authorize-internal`
  has no such nginx shield by design (that is the whole point of giving it a distinct path — see
  above), so a route with no permission class would be a real authorization oracle: anyone who can
  reach Django could enumerate which channel UUIDs exist and which are hidden or adult, by probing it
  directly. It is gated by `IsInternalRelay` — the same two-header check (`X-Dispatcharr-Internal` +
  `X-Dispatcharr-Internal-Request`) the `/proxy/relay/…`/`/api/relay/…` contract already uses, and
  which 2c's Go relay implements from its first PR regardless — so this route costs no new
  authentication mechanism, only a new permission-class assignment, but that assignment is load-
  bearing in a way it would not have been on the shielded path, which is exactly why the body-signing
  fix above matters: `IsInternalRelay` alone proves "a deployment insider is calling," not "calling
  about the question they claim to be calling about" — the bound token has to cover both.
- **Registration is unconditional, not dev-gated.** The route is registered in every deployment
  shape (there is no code-level way to know at Django's boot time whether the *relay* it will talk
  to has nginx in front of it), and is simply never called in practice once nginx is present, because
  the Go relay's own `request_is_relay_trusted()`-equivalent check short-circuits before this call is
  made.
- **The response, fully specified — added in this fix round (§ M-R3-2 in the round-3 review; this
  spec's earlier draft left it unstated entirely).** Two shapes, matching `authorize_view`'s own two
  outcomes exactly, because this route is the inline path's HTTP successor, not the nginx-subrequest
  path's:
  - **200 (authorized):** the same `X-Relay-*` response headers `authorize_view` already sets
    (`authorize_views.py:307-311` — `HEADER_RELAY_CHANNEL`, `_OUTPUT`, `_CLIENT`, `_USER`, `_NAME`),
    plus 2b-2's two additions, `X-Relay-Output-Format` and `X-Relay-Client-IP` — seven headers total,
    the same seven any relay-bound nginx location carries after 2b-2. This is also the dev shape's
    only source for `ip_address` (closing parity row 17's stated gap: there is no hop-set header to
    read in this shape otherwise, so `X-Relay-Client-IP` on *this* response is where it comes from).
    **A 200 does not by itself mean authorization ran on the right principal.** `X-Relay-User` is
    the field that says so: empty on a request that forwarded a session cookie means the principal
    was downgraded to anonymous, and the tune is served anyway. See the session-resolution
    requirement in the `headers` bullet above — that is what 2b's test asserts, and a status-only
    check cannot see it.
  - **Denial: the true status, not the collapsed one — `authorize_error_response`
    (`authorize_views.py:76-80`), never `subrequest_error_response` (`:82-100`).** Phase 1's own
    spec is explicit about why the two exist and do not converge: `subrequest_error_response`'s
    403-collapse-plus-`X-Authorize-Status` shape (Amendment S7,
    `docs/superpowers/specs/2026-09-04-…md`) exists **only** because
    `ngx_http_auth_request_module` can transport a 2xx, a 401 or a 403 and nothing else, so a 404 or
    a 429 has to travel as 403 with the real code recovered by `error_page 403 = @authorize_denied`.
    A direct POST has no such transport constraint — nothing is asking `auth_request` to carry
    anything — so collapsing here would be inventing a limitation that does not exist and handing
    the Go relay a 403 where production would answer 404 (an unknown channel in a cached playlist)
    or 429 (over the stream limit), a real parity violation under D5. `authorize_error_response`'s
    true-status shape is what the *existing* inline fallback already uses today
    (`resolve_authorization`'s non-trusted branch calls `authorize_stream` directly and lets
    `AuthorizeDenied` propagate with its real status), so this is not a new choice — it is the one
    this route already implies by being the inline path's successor, made explicit.

### Error handling per hop

Added in this fix round (this spec's first draft named only the `next-source` 404 mapping and the
timeout table; the full 4xx/5xx split below is load-bearing for the Go client and was missing).
Verified against `apps/proxy/control_plane.py:73-201` and `apps/proxy/relay_client.py:96-330`, both
read in full.

**Relay → Django (`control_plane.py`'s `_post`, used by `next_source`/`release_source`/
`post_events`):**

| Response | Outcome | Retried? |
|---|---|---|
| 2xx, valid JSON object body | Success | — |
| 2xx, non-JSON body | `ControlPlaneUnavailable` | **No — corrected in this fix round** |
| 2xx, JSON but not an object (a list, string, `null`) | `ControlPlaneUnavailable` | **No — corrected in this fix round** |
| 3xx | `ControlPlaneUnavailable` — **never followed** (`allow_redirects=False`) | **No — corrected in this fix round** |
| 4xx, and it is `next-source`'s 404 specifically | Mapped to `{"source": null, "alternates": [], "error": "identifier not found"}` — **not an error** (channel deleted mid-playback) | — |
| 4xx, every other case (a 400, or a 403 from a `SECRET_KEY` mismatch between the api and relay roles) | `ControlPlaneRefused(status, path)` — **not a subclass of `ControlPlaneUnavailable`**; `except ControlPlaneUnavailable` must not catch it | **No** — "a 404... or a 403... must fail the switch loudly instead of making every failover on the deployment degrade silently forever" |
| 5xx, or a transport exception (`requests.RequestException`) | `ControlPlaneUnavailable` | Yes |
| 200 with a non-dict `source` or non-list `alternates` (`next_source`'s own validation, after `_post` already returned a dict) | `ControlPlaneUnavailable` | — (validation runs after `_post` returns; no further HTTP attempt) |

**Only a 5xx or a transport exception consumes the retry budget's second attempt; every other
non-2xx outcome raises immediately on the first.** Corrected in this fix round — this spec's first
draft marked the non-JSON, non-object and 3xx rows "Yes" (the 3xx row hedged "Yes, but pointless"),
reading the code's own comment about *why* retrying a 3xx is pointless and then recording the
opposite of what the code actually does with that reasoning. Verified against
`apps/proxy/control_plane.py:83-146`: only the transport-exception branch (`:99-100`, catching
`requests.RequestException`) and the 5xx branch (`:139`) assign `last = …` and fall through to the
loop's `time.sleep(RETRY_DELAY)` at `:141-143`. The non-JSON-2xx raise (`:102-110`), the
non-object-2xx raise (`:111-119`) and the 3xx raise (`:121-127`) all `raise` directly inside the
`for attempt in range(ATTEMPTS)` loop, exiting it on the first pass. A Go client built to the
uncorrected table would burn a second full `(2, 5)` budget — up to 7 extra seconds of dead air —
on a misconfigured deployment before falling back; the corrected table is what 2c-5 implements.

Only `ControlPlaneUnavailable` triggers the degraded, unenforced fallback to the channel-start-cached
candidate list (§ Stage 2c); `ControlPlaneRefused` must propagate and fail the switch. `release_source`
additionally catches `ImproperlyConfigured` (a misconfigured `DISPATCHARR_INTERNAL_API_BASE_URL`)
itself, logs once per call naming only the responsible variable, and returns `False` rather than
raising — aborting a channel-stop cleanup cannot fix a bad config and would only leak the channel's
state. `post_events` never raises at all: all three exception shapes (`ControlPlaneUnavailable`,
`ControlPlaneRefused`, `ImproperlyConfigured`) are swallowed, with a module-level `_events_down` flag
that logs once on the transition into an outage and once on recovery, not once per event.

**Django → relay (`relay_client.py`'s `_request`, used by `list_channels`/`get_channel`/
`stop_channel`/`stop_client`/`advance`):**

| Response | Outcome | `transport` flag |
|---|---|---|
| 2xx, valid JSON object (or empty body) | Success | — |
| 2xx, non-JSON or non-object body | `RelayUnavailable` | `False` |
| 3xx | `RelayUnavailable` — never followed | `False` |
| 4xx | `RelayRefused(status, path)` | n/a (not a `RelayUnavailable`) |
| 5xx | `RelayUnavailable` | `False` |
| `requests.ConnectionError` (`ConnectTimeout` included — a narrower, first-checked branch) | `RelayUnavailable` | **`True`** |
| Every other `requests.RequestException` (e.g. `ReadTimeout`) | `RelayUnavailable` | `False` |

`transport=True` means the relay could not be reached at all — the only case where a whole batch
(`stop_channels()`, called on a bulk M3U delete of hundreds of channels) is worth aborting early,
because every remaining identifier would fail identically. Every other outcome, including
`RelayRefused` and a non-transport `RelayUnavailable`, is per-request and the loop continues — a
single stuck channel past `ADMIN_TIMEOUT`'s 5s read budget says nothing about the next one.
`get_channel` maps a 404 `RelayRefused` specifically to `None` ("this channel is not running" — an
answer, not an outage); every other `RelayRefused` propagates. `_live_connections`
(`apps/proxy/utils.py`) catches both `RelayUnavailable` and `RelayRefused` and returns an empty
list — the one call site that fails open by design, because "the relay is the only process serving
live clients, so a relay that is not answering has none."

## Stage 2a — pin the behaviour (Python, the gate)

### Gate 1 — the parity matrix, 100% pinned

New `docs/relay-parity-matrix.md`: one row per externally-observable live-path behaviour, each
naming the behaviour, the Python source it was derived from (`file:line`), and the test that pins
it. Rows are derived by reading the source, not by cataloguing tests that happen to exist already —
several of the rows below have no current test and are recorded as gaps 2a must close, not rows
already checked off. Enumerated here; the PR that lands the matrix fills in the remaining rows this
spec's authors did not have time to individually trace, each still required to carry a `file:line`
citation immediately and a test reference **eventually** — an unpinned row stands as `owed: <PR id>`
until the PR that owns it lands the test, which is what lets the guard be green at 2a-1 and still
mean something (see the guard test below, corrected in the round-6 amendments, § A6; the first
draft's "before the guard test passes" made 2a-1's own gate unmeetable).

| # | Behaviour | Source | Test (2a target) |
|---|---|---|---|
| 1 | Buffering trigger: `speed=` < `buffering_speed` sustained > `buffering_timeout` (15s default) | `services/log_parsers.py`, `input/manager.py`'s health monitor | New, real-ffmpeg harness test |
| 2 | Dead-air trigger: no data > 10s, 3× at 5s intervals | `input/manager.py` health monitor | New, real-upstream harness test |
| 3 | Connect-failure trigger: 3 failures in 30 min | `input/manager.py` | New |
| 4 | `speed=` is a cumulative average since process start, taking ~55s to arm | `services/log_parsers.py` | New — the highest-risk single behaviour in the phase (§ Risks) |
| 5 | Thresholds snapshotted in `StreamManager.__init__`; a settings change mid-stream does not reach a running channel | `input/manager.py` | New |
| 6 | `MAX_STREAM_SWITCHES` does not bound buffering-triggered switches (they come from the stderr greenlet, bypassing the main-loop counter) | `input/manager.py` | New — filed as issue, reproduced, not fixed |
| 7 | Chunk index is monotonic for the channel's life, never reset by a switch | `input/buffer.py` | New |
| 8 | New client joins ~5s behind live via the timestamp zset | `input/buffer.py`, `chunk_timestamps` key | New |
| 9 | 188-byte TS packet realignment before a chunk is written | `input/buffer.py` | New |
| 10 | Multi-client upstream sharing (one ffmpeg, N client readers) | `server.py`, `client_manager.py` | Existing (`streaming` project) — cite exact spec file in matrix PR |
| 11 | Output Profile process sharing per `(channel, profile)` | `output/profile/manager.py` | Existing — cite exact spec file |
| 12 | fMP4 `_is_timeout()` lacks TS generator's `url_switching` exemption; fMP4 viewers can drop at 40s during a slow failover | `output/fmp4/generator.py:339` vs `output/ts/generator.py:574-585` | New — filed as issue, reproduced. **Owned by 2a-6, not 2a-4** (round-6 amendments, § A5) |
| 13 | Client registration and the ghost-client cases | `client_manager.py`, `ClientManager.remove_ghost_clients` | Partial existing (`test_ts_proxy_ghost_clients`) — extend |
| 14 | Status payload exact field set/types: `owner` is `null` on the **list** endpoint and the string `'unknown'` on the **detail** endpoint (not the reverse); `ffmpeg_speed` a float on both; `source_fps` a string on detail and a float on list (unlike `ffmpeg_speed`, still split, carried not fixed) | `channel_status.py` | New, unit-level (view-level bucket is fine here) |
| 15 | `stream_xc` authorizes once and hands its `decision` into `stream_ts` so the tune is not re-authorized and a second client id is not minted for the same connection | `apps/proxy/live_proxy/views.py:161-165` (comment), `:825` (the call) | New — this spec's first draft missed this second call site entirely |
| 16 | `/proxy/ts/stream/<stream_hash>` (no channel at all — the admin single-stream preview) applies the STREAMS ACL and the per-user stream limit when a principal resolved, and **no channel check of any kind**, because there is no channel to check | `apps/proxy/next_source.py:69-79` `get_stream_object`'s `Stream.stream_hash` fallback; ADR 0005 Consequences | New — a distinct authorization shape from every other row, currently unaddressed by 2b's contract (§ Stage 2b) |
| 17 | `ip_address` on both status endpoints is the real client address, not nginx's own or empty — derived, in every deployment shape, from `X-Relay-Client-IP` set by whichever authorize response the Go relay trusted (nginx's `auth_request` hop in production; the direct `POST /_dispatcharr/authorize-internal` response in the nginx-less dev shape — § The contract's response spec), never from `REMOTE_ADDR`/`X-Forwarded-For` read directly at the relay, because the flipped production locations' own `proxy_set_header` lines discard the server-level forwarding headers those would otherwise need (§ Stage 2d) | `dispatcharr/utils.py:342-370` `get_client_ip`; `client_manager.py:215-230`; `relay_serializers.py:29`, `:79` | New — no current test isolates `ip_address` from the rest of the client-registration payload |
| 18 | What the status payload's `stream_name`/`m3u_profile_name` contain when the metadata hash was never written one — phrased as a question 2b-3 must answer, not an assumed "always present," so whatever 2b-3's inspection concludes (§ Stage 2b, § NM2/Q3 in the round-2 review), 2c is held to the same answer | `channel_status.py:74`, `:92`; `zero_orm_allowlist.py` once 2b-3 lands | New — 2b-3 records the answer as part of closing this row, not before |
| 19 | Authorize matrix, **Internal** principal (DVR, and any caller with a valid `X-Dispatcharr-Internal`): STREAMS ACL applied; `user_level`, profile membership, `hidden_from_output`, `is_adult`/`hide_adult_content` and the stream limit all **bypassed**; never redirected | `apps/proxy/authorize.py:309-310`, `:376-377`, `:436-442`; Phase 1 spec § "The authorize matrix" (`docs/superpowers/specs/2026-09-04-…md:705-713`) | **New** — no `e2e/tests/` spec pins this row (round-6 amendments, § A4). `dvr/recording-execution.spec.ts` drives the internal principal's happy path but asserts bytes, not one bypass column |
| 20 | Authorize matrix, **Admin** (`user_level >= 10`, any authenticator): ACL applied, every channel check bypassed, **stream limit enforced** | `apps/proxy/authorize.py`; Phase 1 matrix row 2 | **New** — no `e2e/tests/` spec pins this row (§ A4). The "bypasses everything *except* the stream limit" asymmetry is the whole content of the row and is untested |
| 21 | Authorize matrix, **XC credentials** (`<user>/<pass>` path segments, `hmac.compare_digest`): everything enforced, 403 on `hidden_from_output` and on adult-vs-`hide_adult_content` | `apps/proxy/authorize.py`'s `resolve_xc_user`; Phase 1 matrix row 3 | Existing — `e2e/tests/streaming/authorize-matrix.spec.ts` (`@contract`, PR 5); matrix cites, does not re-test |
| 22 | Authorize matrix, **JWT / API key / query-param JWT** (non-admin): as row 21 | `apps/proxy/authorize.py`; Phase 1 matrix row 4 | Existing — `authorize-matrix.spec.ts` (`@contract`, PR 5); matrix cites, does not re-test |
| 23 | Authorize matrix, **Session** (non-admin, `request.user` when authenticated): as row 21, resolved from the session rather than a header — and `_session_user` reads the session directly, not `http_request.user` | `apps/proxy/authorize.py:268-276`; Phase 1 matrix row 5 | **New** — no `e2e/tests/` spec pins this row (§ A4); it is also the row the dev fallback's `cookie` body field exists to serve (§ The contract) |
| 24 | Authorize matrix, **Anonymous** (bare `/proxy/ts/stream/<uuid>`): ACL applied, ordinary channel still streams, `hidden_from_output` **403s** | `apps/proxy/authorize.py`; Phase 1 matrix row 6 | Existing — `authorize-matrix.spec.ts`'s first two tests (`@contract`, PR 5) |
| 25 | Authorize matrix, **stream-by-hash** (`/proxy/ts/stream/<stream_hash>`, any principal): ACL applied, **no channel check of any kind**, stream limit enforced when a principal resolved | `apps/proxy/next_source.py:69-79`; Phase 1 matrix row 7 | **New** — no `e2e/tests/` spec pins this row (§ A4). Distinct from row 16, which states the *shape*; this row is the matrix cell that has to stay true after 2b extends `next-source`'s identifier resolution |
| 26 | **White-box-only, not held to parity:** the exact greenlet/thread topology inside `server.py` — 27 `threading.Thread`s sharing one OS thread under gevent's monkey-patch | `server.py` | **None, deliberately** — D2 replaces it with goroutines; recorded so the guard test sees a decision, not an omission |
| 27 | **White-box-only, not held to parity:** `_execute_redis_command`'s specific exception-swallowing shape (one of the lease's three fail-open paths) | `server.py`'s `_execute_redis_command` | **None, deliberately** — deleted outright by D2 rather than reproduced |

**Twenty-seven rows, not twenty-four — corrected in the round-6 amendments (§ A3).** The first
draft's table ran 1-18 plus a collapsed `19-26` standing for the Phase 1 authorize matrix's *seven*
principal rows: eight ids for seven rows, and 18 + 7 = 25 regardless of how they are numbered. The
seven are expanded above, one row each, against the Phase 1 spec's own authorize matrix
(`2026-09-04-phase1-process-split-design.md:705-713`), which has exactly seven; and the two
white-box-only rows this section's own prose already named are now rows in the table rather than
prose beside it, since the guard test parses the table and prose is invisible to it. **Behaviour not
observable from outside is a row that says so**, naming what the Go relay is deliberately **not**
held to, rather than an absence the guard cannot distinguish from an oversight.

A guard test under `e2e/tests/guards/` (new file, `parity-matrix.spec.ts`, following the same
"assertion, not convention" pattern `allowlist.ts`/`capabilities.spec.ts` already use for the Redis
importer allowlist) parses `docs/relay-parity-matrix.md`'s table and fails, naming the offending row,
if any row lacks both a `file:line` citation and a test reference. **A row explicitly marked
white-box-only (rows 26 and 27) satisfies the test-reference half by carrying that marker** —
added in the round-6 amendments alongside § A3, since those rows are now in the table and a guard
that cannot tell "deliberately not held to parity" from "nobody wrote the test yet" would either
fail forever or have to be weakened for every row.

**A row not yet pinned carries `owed: <PR id>` in place of its test reference, and that is the third
thing the guard accepts** — stated here in the round-6 amendments (§ A6) because the spec previously
required a test reference on every row "before the guard test passes" while also making 2a-1's gate
"guard test green", which cannot both be true of a PR that lands twenty-odd rows nothing has tested
yet. The guard therefore fails a row that carries **none** of the three (a test reference, the
white-box-only marker, an `owed:` marker), and fails an `owed:` marker naming a PR outside this
phase's own vocabulary — so a row can be unpinned but never unowned, which is exactly the property
§ A4's roll-call establishes and the guard is what keeps true. **Gate 1 is met when no `owed:` row
remains**, which — row 18 being 2b-3's — happens in 2b-3 and not before (§ A7).

This matrix is the load-bearing
artifact of the whole phase: 2a's own checklist, 2c's implementation spec (each Go PR closes a named
set of rows), and 2d's cutover checklist (every row must show a passing Go-side equivalent before the
nginx flip). PR 2c-9 replaces the matrix's Python test-reference column with a Go one, once every row
that is held to parity has one.

### Gate 2 — 80% statement coverage

> **AMENDED after stage 2a was executed and measured. Stage 2a does not reach 80%, and the
> requirement moves rather than being lowered or dropped.**
>
> Measured on the tree carrying all seven 2a PRs, under `COVERAGE_CORE=sysmon`, per-container
> per-label isolation (shape `per-container/v1-sysmon`), denominator **7,978** on every round:
> **2,016-2,050 missing over 15 CI rounds → 74.30% at the floor**, against the 1,595 the gate allows.
> **Shortfall: 455 statements.** (A 21-round LOCAL census first gave 2,003-2,044 → 74.38%; the first
> CI run on the merge-ready tree measured 2,045, so the floor was re-measured in the environment that
> enforces it. Same tree, same shape, different scheduler — see `scripts/coverage_live_path.floor`.) An independent measurement of the merged tree before 2a-7's own two
> rows gave 2,048 over 24 rounds — the four-statement difference is exactly what rows 29 and 30
> bought, not a re-run of one figure.
>
> **What 2a-7 ships is the ratchet, not the number.** The floor file is written at the measured
> worst-of-21 and enforced in `backend-tests.yml`; coverage may not regress from here. **The ≥80%
> requirement is retained in full and reassigned to `2b-4`** (§ Stage 2b's PR table), so **D7 still
> blocks every 2c PR**. 2a-7 turns the ratchet on; it does not turn the blocker off.
>
> **Why the number was not reached, and why it was not bought.** Every reachability estimate in this
> document was checked during 2a and none survived — three checked, three wrong, two pessimistic and
> one optimistic. Closing 455 statements from where 2a ends means 2-4 further PRs against a pool
> whose marginal statement is a fault-injected `except Exception: logger.error(...)` arm.
>
> **Denominator exclusion was considered and declined.** The defensible candidates —
> `_cleanup_local_resources` (62), `_check_orphaned_channels` (24), #231's manager cluster (~62) —
> total ~148 statements, about 1.4 percentage points against an eight-point gap. It cannot reach the
> gate and therefore cannot be justified as a way of reaching it. Two further reasons stand on their
> own: `_cleanup_local_resources` is itself one of the measured run-to-run variance regions, so
> excluding it would improve the number by making the gate blind to a flapping region; and any other
> justification for excluding those statements is a different PR's argument, made in daylight, not
> folded into the PR that sets the number they flatter.
>
> **D7's stated purpose is met at 74.30%, which is a different claim from its number being met.** The
> reason D7 gives for Gate 2 is catching a subtle regression in the buffering detector's
> cumulative-average arithmetic. That was discharged in **2a-4**, whose rows 1-6 and 28 are
> mutation-tested against exactly that logic. The gate's purpose and the gate's threshold came apart
> under measurement, and this amendment records which one 2a delivered.


**Corrected in this fix round: the first draft's `coverage` invocation was not runnable, and its
denominator did not match its own published baseline.** `coverage run --source=` takes package
names or directories, not bare file-stems with no extension — `apps/proxy/authorize` etc. are none
of those; the files are `apps/proxy/authorize.py` and so on, addressable only as the dotted module
`apps.proxy.authorize` or via an `--include=` glob. Separately, the first draft's `--source` list
added `apps/proxy/authorize_views` — the module holding `result_from_headers` and
`resolve_authorization`, exactly what correction (iii) (§ What the code says) is about — to a
ten-entry list, while § Verified facts' baseline table names only **nine** Phase 1 boundary modules
and does not include `authorize_views.py` at all. The published 44%/92%/50.4% figures were therefore
not what the gate as first specified would have computed. **Closed in the round-6 amendments
(§ A1): the module is measured, the denominator is ten everywhere, and the figures § Verified facts
now publishes are the ones this exact invocation produces** — `authorize_views.py` is 108
statements, 4 missed, **96.3%**; the ten together are 1,148 / 91 / **92.1%**; the combined
denominator is 7,978 / 3,977 / **50.2%**. There is no longer an open item here.

**Corrected again, by 2a-2's planning pass — which ran the invocation rather than reading it —
because the "corrected shape" below was still not the shape that produces the numbers above.** Written as a bare `coverage run --include=…` and
executed from the repository root — the only place `manage.py` resolves — coverage auto-discovers
`./.coveragerc`, whose `source = apps, core, dispatcharr` (`.coveragerc:4`) makes it **ignore
`--include` at measurement time** and say so:

```
coverage/inorout.py:513: CoverageWarning: --include is ignored because --source is set
  (include-ignored)
```

The resulting data file holds **212 files / 38,418 statements / 30%**, not 7,978 / 3,977 / 50.2%.
The published figures were reproducible only by accident of two things the snippet never mentions:
`.coveragerc`'s own `omit = */tests/*`, which kept the twenty test modules out of the measurement,
and a **report**-time `--include` filter, which is where the ten-module narrowing actually happened.
The figures are right; the command under them never computed them.

**The shape Gate 2 actually specifies is a self-contained rcfile, and `scripts/coverage_live_path.sh`
(2a-2) owns it.** It must not depend on an ambient `./.coveragerc`, which also sets a `data_file`
and a `[json] output` this gate does not want:

```ini
# scripts/coverage_live_path.coveragerc
[run]
source = apps/proxy
omit =
    */tests/*
parallel = True
data_file = ${COVERAGE_LIVE_PATH_DATA_DIR}/.coverage

[report]
include =
    apps/proxy/live_proxy/*
    apps/proxy/authorize.py
    apps/proxy/authorize_views.py
    apps/proxy/control_plane.py
    apps/proxy/next_source.py
    apps/proxy/relay_client.py
    apps/proxy/relay_serializers.py
    apps/proxy/relay_views.py
    apps/proxy/permissions.py
    apps/proxy/internal_auth.py
    apps/proxy/internal_base_url.py
omit =
    */tests/*
skip_empty = True
```

driven one label per process and combined:

```bash
for L in apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests; do
  redis-cli flushall >/dev/null 2>&1 || true
  python -m coverage run --rcfile=scripts/coverage_live_path.coveragerc manage.py test --keepdb "$L"
done
python -m coverage combine --rcfile=scripts/coverage_live_path.coveragerc
python -m coverage report  --rcfile=scripts/coverage_live_path.coveragerc
```

Measured at `a948cd8a` in the backend test container on 2026-09-10: **7,978 statements, 3,977
missed, 50.150413637503135%**, zero coverage warnings, 15.2 s wall for all three labels — matching
§ Verified facts to the statement and every per-file row with it.

**`source` is load-bearing and `include` cannot replace it — this is a fact about what Gate 2
measures, not a stylistic preference.** Measured at the same commit: with `[run] include =` and no
`source`, the combined total is **7,877 / 3,876**, one hundred and one statements short. The 101 are
`apps/proxy/live_proxy/input/http_streamer.py`, which no test imports. `source` triggers coverage's
walk over source files that never executed and reports such a file at 0%; a measurement-time
`include` filter only records files that actually execute, so a completely untested file drops out
of the **denominator** rather than dragging the percentage down. A floor built that way rewards
deleting the last test that imports a module, and would have quietly excluded the single worst file
in this phase's own worst-file list. `--include` at **report** time is fine — the rcfile above uses
it there — because by then every file `source` walked is already in the data.

`authorize_views.py` is in the denominator (ten boundary modules, not nine) because it is a real
part of the internal contract 2c must reproduce, and it is **measured**, at 96.3% (§ A1). `vod_proxy`
and `hls_proxy` stay outside the `[report] include` list, matching D1's scope line — and outside
`[run] source` too, which is `apps/proxy` rather than `apps` for that reason. **The target
§ Verified facts now states — `live_proxy` from 43.1% to 78.0%, +2,382 statements against a
7,978-statement denominator — is arithmetic against the ten-module baseline this exact rcfile
produces**, not against a nine-module one. 2a-2's first run of the script reproduced it exactly
(7,978 / 3,977 / 50.150413637503135%), and on a tree with no tune in it that exactness is expected:
**the number to check is the denominator, 7,978, which is a property of the rcfile and moves only
if the module list does.** The `missing` count is a different kind of quantity — see the ratchet
paragraph below — and once stage 2a's harness exists it varies by a couple of dozen statements
between identical runs. **Do not read a small divergence in `missing` as a defect**: an early
implementer lost time chasing a seven-statement gap that was ordinary teardown timing. A changed
denominator is a finding; a changed `missing` is a question, and the answer is usually per-file
attribution.

**Also corrected: running the three labels together in one `coverage run` is the one configuration
`CLAUDE.md` § Testing documents as historically unreliable** — "CI never runs the suite in one
process... The full in-process run has historically failed with a different set each time while
every failure passed in its shard... A green CI run does not mean a green suite." A coverage gate
that reproduces exactly that failure mode would block Go PRs on flakes unrelated to the PR being
reviewed. **The gate instead runs per-label, in the existing per-label matrix jobs
`backend-tests.yml` already runs, each with `coverage run --rcfile=scripts/coverage_live_path.coveragerc`
(whose `[run] parallel = True` supplies the parallel-mode suffix), and combines the resulting
`.coverage.*` files with `coverage combine` in an aggregate step**. **§ A1 supplies
a second, independent reason for the same shape**: a single process gives the relay's daemon threads
~33 seconds of loop iterations while unrelated tests run, and coverage then credits ~68 statements no
test asserts — so the single-process number is both flakier *and* higher, and a floor set against it
could not be met by the per-label pipeline enforcing it. This is the same shape
`Backend result` already aggregates by, rather than a fourth, separate in-process run.

The result writes a floor file, `scripts/coverage_live_path.floor` — a ratchet in `lint.yml`'s
zizmor idiom, but with an explicit monotonicity check this spec's first draft left unstated: the CI
job recomputes coverage, fails if it drops below the committed floor, and separately fails if a PR's
diff lowers the floor file's own committed value without also proving (in the same run) that the
newly-computed percentage supports it — i.e. the floor can rise in the same PR that earns the rise,
but can never simply be edited down. `scripts/coverage_live_path.sh`'s exit code is 1 on either
failure, with the failing percentage and the floor both printed.

**The shape guard stands, and it is not a tolerance.** The script refuses to write or compare a
floor produced by any other measurement shape — a single-process run reports ~68 fewer missed
statements and would silently ratchet the floor to a number the per-label pipeline could never
reach again. That ruling is unaffected by everything below: a wrong *shape* is a different problem
from run-to-run variance, with a different cause and a different remedy.

**But the round-6 ruling that the ratchet needs *no tolerance at all* is withdrawn: it was measured
on a suite in which no test tunes a channel, and stage 2a ends that by construction.** The claim
was that within the per-label shape the measurement is *exactly* reproducible — "three runs across
three different label sets agreed to the statement" — and that was true of the tree it was taken
on. Once the subprocess harness exists, four unchanged runs of the same gate against one unmodified
tree state (same image, same container, Redis flushed between runs) gave missed counts spanning
**27 statements**, with the denominator identical every time and all three labels green every time.
The variance is real, it is not a shape error, and a zero-tolerance ratchet sitting on top of it
turns an unrelated PR red at random.

**The attribution is what makes this bounded rather than alarming, and 2a-7 must reproduce it rather
than inherit it.** In the measurement above the movement was confined to **two files —
`input/manager.py` and `server.py` — in a handful of regions, every one of them inside the
stop/teardown window of a tune.** Nothing moved in the tune path, the ring buffer, either
generator, the client manager, or any of the ten Phase 1 boundary modules. Two causes, of which
only the second is irreducible:

1. **The harness racing its own teardown** — a fixture whose stderr cadence lands its last records
   near the end of a short tune, so a counter crosses a warm-up threshold or does not. This is a
   harness defect, is fixable, and must be fixed rather than tolerated: a test that measures
   something different on alternate runs is not measuring anything.
2. **The relay's own cleanup thread sampling a channel mid-shutdown.** It ticks on its own interval
   (`CLEANUP_CHECK_INTERVAL`), independent of any test, so whether a tick lands inside a teardown
   window is genuinely not controllable from a test. This is relay behaviour, not test flakiness.

**So 2a-7's ratchet carries a small tolerance, and three constraints on it.** (i) It is sized to the
*measured residual* after the harness's own races are removed — not to § A1's ±70-statement band,
which is an order of magnitude larger and describes a different phenomenon entirely (measurement
shape, not teardown timing); reusing that number here would be a coincidence of arithmetic, not an
argument. (ii) It is **justified by per-file attribution, not picked**: the PR that sets it shows
which files move and why, exactly as the measurement above does, so a later widening has to make
the same case. (iii) A movement **outside** it is a finding to investigate, not noise to absorb —
the tolerance exists to stop random reddening, not to hide a regression. **This spec deliberately
states no number**: the residual belongs to the tree 2a-7 measures on, and a figure written here
would be quoted long after it stopped being true. **A disputed figure also must not be written in
its most arresting form, and must not be relayed without its flag** — both halves, because this
document has been wrong in both: a contested number was made the memorable sentence of a section,
and was then repeated onward in exactly the form that stripped the hedge. A hedge that does not
survive quotation is not a hedge. **What it must be sized against is a measurement
under `COVERAGE_CORE=sysmon`, whose spread is wider than the C tracer's** — 63 statements across
twelve runs, against the C tracer's 19. That is not a regression and the cause is understood: the C
tracer systematically drops statements executing after a `gevent.sleep()`, and in doing so was also
flattening the visible difference between the relay's background housekeeping firing during a run or
not. Recovering those statements makes pre-existing timing variance visible, it does not create it —
per-file diffs confine the extra spread to the sources § above already names. **2a-7 sizes against
63, not 19** — and against a tree loaded with stage 2a's own tests, not the base: the spread is 2 on
the base suite, 10 with 2a-3's tests, and **51** once 2a-6's probes are in, because the
fMP4/Output-Profile managers start background loops of their own. The figure grows with the tests
the gate is measured over, so 2a-7 measures it on the tree it will actually gate.

#### Whether ≥80% is reachable by 2a-3 … 2a-6 as scoped — an open question for the user

**The gate, stated as a count rather than a percentage.** 80% of the 7,978-statement denominator
requires 6,383 covered, so the **maximum permitted `missing` is 1,595** (1,595 missing → 80.008%;
1,596 → 79.995%). **This number is independent of coverage core and of every measurement below**,
because the denominator is a property of the rcfile. Stating it as a count is deliberate: percentages
are what hid the error this section records.

**Every other figure here was taken under the C tracer and is pending re-measurement under sysmon.
They are labelled, and they are not mixed** — a sum spanning two cores is exactly what the shape
guard exists to refuse, and it would be a poor thing to commit into the spec that describes it.

| Input | C-tracer value | Status |
|---|---|---|
| Distance to close | **3,035 → 1,440** (post-2a-3) | pending sysmon re-measurement |
| 2a-4 `input/manager.py` | 498 missed; its planner predicts 60-120 | pending |
| 2a-5 `server.py` | 840 missed, **222 forbidden-or-unreachable**; reachable remainder disputed at **150 / 217 / 618** | pending, and the dispute is unresolved |
| 2a-6 `fmp4/manager.py` + `profile/manager.py` + `fmp4/generator.py` | **unmeasured**; ≤633 by their pre-harness sum | never measured post-harness |
| 2a-5's authorize rows | **counted as zero** | see below |

**2a-5's rows 14-17, 19, 20, 23 and 25 are authorize/view-level**, so their coverage lands in
`authorize.py`, `authorize_views.py`, `views.py`, `channel_status.py` and `next_source.py` — inside
the denominator but **outside `server.py`**. That yield is real, unmeasured, and counted as zero in
every scenario below. It is the one input that could move the answer favourably without re-scoping
anything.

**WITHDRAWN, and visibly rather than silently, because an earlier revision of this section was
published saying it.** That revision claimed the absolute ceiling was **"1,439 against 1,440 — short
by a single statement"**, and concluded that the gate might be unreachable *even in the impossible
case*. **Both are false.** The claim rested on reading `server.py`'s reachable remainder as **217**,
a figure obtained by summing the rows of a table that was later shown to be a **subset** of the
module — it never enumerated all of it, and the accompanying "there is no ninth region" was written
with no basis. An exhaustive AST walk mapping every missed line to its innermost enclosing `def`
now supersedes it. The retraction is left standing here rather than deleted: the wrong number was
published, and a withdrawn claim that vanishes is worse than one visibly retracted.

**`server.py`, measured exhaustively (C-tracer basis, 844 missed — the buckets sum to the total
exactly):** blocked-or-must-not-target **175**, unreachable or white-box-only **108**, 2a-6's Output
Profile surface **142**, 2a-5's surfaces **269**, reachable-but-expensive **150**. So
**blocked-or-unreachable is 283** — 61 more than the 222 previously carried, because
`_check_orphaned_metadata` (26), `_execute_redis_command` (14), `_check_orphaned_channels` (7, and
**no callers anywhere** — new dead code) and `_recover_stuck_channel_stops` (14) had been named in
prose as noise but never counted — and **reachable is 561**, not 217 and not 618. The 142 stays in
the pool: it is reachable through the ordinary tune path and 2a-6 moves it as a side effect.

**SUPERSEDED IN TURN, by measurement rather than by argument.** The bracket published above rested
on this spec's own "~20-30% reachable" estimate for the fmp4/Output-Profile group. **That group is
the cheapest in the denominator, not the dearest.** Two probe tests of 0.72 s and 0.76 s — an
ordinary tune carrying `?output_format=fmp4`, and another carrying `?output_profile=<id>` — move it
by **483 of 735 statements (66%)**, and move the whole gate **3,204 → 2,629**, a **−575** from two
tests. So the "realistic, short by 569-719" rows are withdrawn, and the decisive bound framed around
`input/manager.py` is no longer the binding constraint.

**Why it is that cheap, recorded for 2a-6.** Both managers are selected by a plain query parameter
on an ordinary tune — `_resolve_output_format` (`views.py:113-134`) → `ensure_output_format`
(`server.py:1290`), and `resolve_output_profile` (`authorize.py:201`) → `ensure_output_profile`
(`server.py:1402`). No trusted header, no second worker, no nginx. And `FFMPEG_REMUX_CMD`'s `argv[0]`
is the bare string `"ffmpeg"`, so 2a-2's `PATH` stand-in reaches it untouched: **the seam decision
paying off in a file group nobody chose it for.**

**The bracket, on sysmon throughout — measured, not converted.** Three runs per configuration,
denominator 7,978 in all nine, allowance 1,595:

| Configuration | missing (3 runs) | mid | spread | distance |
|---|---|---|---|---|
| base | 3,114 / 3,115 / 3,116 | 3,115 | 2 | 1,520 |
| + 2a-3's five tests | 2,970 / 2,976 / 2,980 | 2,976 | 10 | 1,381 |
| + the two 2a-6 probes | 2,512 / 2,540 / 2,563 | 2,540 | **51** | **945** |

**The two cores agree on the deltas** — −577/−481 under sysmon against −575/−483 under the C tracer
— while their absolute levels differ by about 90. That is the expected shape and it is independent
support for stating this gate in relative terms wherever possible: a tracer that drops statements
after a greenlet switch drops them from *both* sides of a comparison.

**But the agreement has a stated condition, and it has now been demonstrated rather than assumed:
the cores agree on deltas EXCEPT where the newly-covered lines are themselves in the disputed set.**
2a-5 reported `server.py` moving **−88** under the C tracer against a review measurement of
**−122** — below its plan's own 100-140 band — with every test passing as designed. The two are the
same work measured twice, and the demonstration is a set-difference on one tree, one run per core:
**34 of the 34 divergent lines fall inside the two functions the cores disagree about**, none
scattered — 12 at `299-332` in `event_listener`'s `STREAM_SWITCH` branch, which is precisely what
2a-5's own switch tests exercise, and 22 at `1906-2137` in `cleanup_task`, the background daemon.
The disagreement runs both ways but not symmetrically: 17 lines go the other direction, 10 of them
in `_recover_stuck_channel_stops` and `refresh_channel_registry`'s skip-mid-shutdown branch — both
already on this section's named-variance list — and 7 scattered singletons, i.e. ordinary noise in
both tracers rather than a second mechanism.

**So `server.py` is the special case *because* its delta sits in the sleepers**, and 2a-3's is not,
because its targets lie outside them. The general rule keeps its force; it now carries the condition
under which it fails, which is more useful than the unconditional version was.

**And the arithmetic alone could not have settled this, which is the transferable part.** Writing
`gap(t)` for the lines the C tracer fails to credit, `delta_sysmon − delta_C ≡ gap(after) −
gap(base)` **identically** — so "the two deltas differ by 34" says only that the gap grew by 34, and
is equally true if the tests had simply moved 34 fewer statements. **A quantity that is true under a
hypothesis and under its negation is not evidence for either.** Only locating the 34 lines decided
it, and the method was the same set-difference that settled the Output-Profile bucket: **diff the
missed-line sets, do not difference the totals.**

**Remaining supply, sysmon.** Two figures are carried for `server.py`, for two different questions,
and they must not be interchanged: **257** is the reachable *pool* (what could be taken, and the
right number for "can 80% be reached at all"), **124** is 2a-5's *target* (what its tasks intend to
close, and the right number for "what will its diff move"). The gap is deliberate:
`initialize_channel` (51) and `handle_client_disconnect` (47) are reachable and **left on the table**
as teardown- and timing-adjacent, on the principle that leaving statements beats a test whose answer
depends on which thread wins.

| Term | Realistic | Pool |
|---|---|---|
| 2a-4 `input/manager.py` | 60-120 *(its own prediction)* | 247 reachable of 474 |
| 2a-5 | 213-282 *(124 target + 89-158 rows)* | 346-415 *(257 + 89-158)* |
| 2a-6 group residual | ~30-50% of the harder 254 | 254 |
| `http_streamer.py` | — *(no PR owns it)* | 101 |
| `server.py` expensive tail | — | 146 *(cost judgement, not measured)* |

| Scenario against a distance of 945 | Total | Result |
|---|---|---|
| PRs as scoped, low | 349 | short **596** |
| PRs as scoped, high | 529 | short **416** |
| full reachable pools | 789 | short **156** |
| + the 146 expensive tail | 935 | short **10** — *inside the 51-statement spread* |
| + `http_streamer.py`'s 101 | 1,036 | **closes +91** |
| + the 98 left on the table | 1,134 | closes +189 |

**So, plainly, and in both directions. The ≥80% gate closes — on the optimistic branch of every
remaining estimate, plus one file no PR owns. On the PRs' own predictions it falls 416-596 short.**
The row that matters most is the fourth: full pools plus the soft expensive tail lands **10
statements short of a distance whose own measurement range is 917-968**, i.e. **indistinguishable
from closing**. Adding `http_streamer.py` — 101 statements, a whole file nothing imports, in nobody's
scope — clears it decisively. That is a much narrower question than "widen into a ~900-statement
pool": it is *"does 2a-6 also take `http_streamer.py`, and do 2a-4 and 2a-5 take their full
reachable sets rather than their planned targets?"*

**The 142 question is settled, pessimistically, by set-difference rather than inference.**
`server.py` goes 796 → ~723 across the probe runs, and diffing the missed-line *sets* shows **135
source lines** becoming covered — at `1284-1417`, `1450-1562`, `1941-2003` and `2154-2183`, which
**is** `ensure_output_format`/`ensure_output_profile` and the teardown paths that stop output
managers. Not a neighbouring region warming up: the bucket itself. **2a-5's safe supply is 257, and
411 would double-count.**

**A second already-banked figure, recorded because it looks like supply and is not.** 2a-3's
re-measurement found `client_manager.py` at **92 → 52**, a 40-statement move nobody predicted or
itemised. It is **already inside the 2,976**: 2a-3's five tests moved the whole gate by −139, of
which only −47 was itemised to `ts/generator.py` and `channel_service.py`, leaving −92 unattributed,
and this is part of it. **It explains where 2a-3's delta went; it adds nothing to the supply**, and a
bracket row for it would double-count exactly as `server.py`'s 142 would. Since this is the second
instance, state the rule: **a correctly-measured per-file delta is not supply if the run it came
from is already the run the distance is measured from.**

**Two corrections to figures quoted earlier in this section.** 2a-3's `channel_service.py`
contribution is **169 → 145 (−24)** under sysmon, not the −55 its C-tracer pair suggested — anything
crediting −55 is 31 too generous. And the authorize-row estimate is **89-158, centre ≈124**, its top
end corrected down by its own author; **no part of it lies in `apps/proxy/utils.py`**, which is
outside the `[report] include` list and was therefore costed at zero, correctly — work there earns
nothing toward this gate. Whether the ten boundary modules *should* include it is a separate
question this spec has not asked: `apps/proxy/utils.py` holds the live half of
`get_user_active_connections`, which D4 makes part of the contract the Go relay reproduces.

**Variance is not uniform, and 2a-7 must size against the loaded tree.** Base spread **2**, with
2a-3's tests **10**, with the probe configuration **51**. The variance arrives *with* the
fMP4/Output-Profile managers, which start background loops of their own — `channel_service.py`
swinging 169 → 201 → 169 across three runs is its visible edge, in the teardown window. **2a-7 will
set its tolerance on a tree containing 2a-6's work, so the figure to size against is the loaded one
— not the base's 2, and not necessarily the 63 measured on a tree without it.**

**And the finding that outlives every total here: no reachability estimate in this spec has survived
measurement.** Three of the five have now been checked — `server.py` was badly optimistic, and its
error hid the two largest-looking prizes being the two that cannot be taken; `input/manager.py` was
optimistic; the fmp4/Output-Profile group was badly **pessimistic**, by a factor of about three, in
the direction that made the whole picture look worse than it is. **Two wrong pessimistically, one
optimistically, none right.** That is the argument for measuring the mid-sized pool before deciding
how much of it to take, rather than estimating it as this spec estimated the other five.

**A partial sysmon re-measurement exists and is deliberately NOT folded into the sums above**:
total missed **3,105** (61.08%), giving a distance of **1,510**, with `input/manager.py` at **474**
(≈178 unreachable, ≈49 must-not-target, ≈247 reachable — the buckets sum exactly). Restating the
bracket needs `server.py` and the fmp4/profile group re-taken on the same core. **Mixing them would
be the one error this document must not contain, being the document that explains why cores must not
be mixed** — and the cores disagree about *which* lines, not merely how many: `server.py:1828-1831`
is covered under sysmon and missed under the C tracer. Note also that the harness has already banked
roughly a third of the original 2,382 shortfall, so the finding is "closer than this spec says, and
may still not close", not "far away".

**Sysmon's ~90 recovered statements probably do not move this, and the reason is worth stating
because it is counter-intuitive.** Both sides of the subtraction move together: recovering a
statement lowers the total (shrinking the distance) *and* lowers an in-scope file's missed count
(shrinking the supply). **The margin changes only by the portion recovered *outside* the four PRs'
scope.** The one region identified so far is `input/manager.py:942-985` (`_read_stderr` /
`_parse_ffmpeg_stats`) — squarely inside 2a-4's scope — so the expected improvement is small. To be
re-derived from measurement, not assumed.

**Five errors of one family, which outlive every number above.** The first four are quantities that
read as one kind of thing while being another; the fifth is the same failure on a different surface,
mechanisms asserted from reading. Together they are the reason this section exists at all:

1. **A sum mistaken for a budget.** The withdrawn claim that *"closing the five largest gaps
   approximately **is** the gate"* was **count-derived** — 2,504 was a sum of missed statements —
   and therefore read as arithmetic. What it silently required was that **every missed statement be
   closeable**, and the reachability percentages that would have falsified it sat beside it as
   commentary, never connected to it. **A sum of missed statements is not a budget until each term
   is known to be reachable.**
2. **A subset presented as a whole.** The region table whose rows summed to 217 never enumerated the
   module, and carried an explicit "there is no ninth region" written with no basis.
3. **A target dressed as a measurement.** The figure "~150" was never reachability at all — it was
   *what a set of tasks intended to close* — quoted in a sentence whose subject was reachability,
   and it survived several rounds in that costume, including one reappearance under the heading
   "reachable-and-safe" written by the same person who had just documented the error. Of the four
   this is the worst, and the reason is worth stating: **a subset table looks like a subset if you
   check the sum; a target dressed as a measurement does not look like anything.**
4. **A figure asserted stale that was current.** The four fmp4/Output-Profile files were assumed to
   have moved under the harness, on the reasoning that the other three had. They had moved by
   **exactly zero** — no harness test passes `?output_format=fmp4` or attaches an Output Profile, so
   nothing in that group is reachable from anything 2a-2 shipped, and its pre-harness figures were
   simultaneously its current ones. The error was reasoning from what the harness *does* to what it
   must have *touched*, without checking. **Demanding the measurement rather than accepting the
   correction is why that is known rather than assumed.**

**A fifth caution, on the same family's other surface: mechanisms asserted from reading.** The four
above are quantities that read as one kind of thing while being another. This one is a *claim about
what the code does*, formed by reading it, that execution contradicts. Three instances arrived in a
single plan, each plausible on the page and each false in the run: a row's assertion that stayed
green when the behaviour it names was deliberately broken (the client stalls, the renumbered index
overtakes, the later assertion passes anyway); a byte-count explanation that did not match the logs;
and a set of fallback branches credited for coverage they never receive, because the function above
them never returns the value that would reach them — every log line reads
`Time-based positioning: 5s behind -> index 0`, and the fallback message never appears.

**Reading establishes a hypothesis; only running establishes a fact — and there are two tiers of
running, with different costs. State both, because conflating them gets the cheap check done and the
expensive one skipped, which is precisely how the row-7 defect survived.**

- **A claim about which branch a test *reaches* is worth an `INFO` grep.** `INFO` prints the branch
  taken, so one run answers it in seconds. Two of the three instances above — the byte-count
  explanation and the never-reached fallbacks — fall here.
- **A claim about what a test would *catch* is worth a break check.** No log distinguishes "the index
  never rewound" from "it rewound and the read hid it"; only mutating the code and re-running
  answers that. Minutes, not seconds. **Row 7 was in this tier**, which is why grepping would never
  have found it.

**A break check that passes is not evidence until you have confirmed the break applied.** The attempt
to reproduce row 7's defect failed *silently*: the patch script printed nothing, the run came back
green, and it was nearly reported as "cannot reproduce" — on a defect that was real, leaving the row
both pinned and apparently second-sourced. The cheap habit is to `sed -n` the patched lines back out
before running.

**Better still, enforce it in the plan rather than the instruction: a plan step that says "watch it
fail" is weaker than one that says what the failure reads.** A step quoting the expected failure text
cannot be satisfied by an unapplied break, because the green run does not produce that text. That
generalises past this stage and is worth carrying into every plan's Step 2.

**And the limit of arithmetic checking, learned here.** Cross-checking the numbers caught (2): the
rows did not sum to the stated total. It could not have caught (3) or (4), because a mislabelled or
wrongly-attributed quantity is internally perfectly consistent — 150 is a real number that adds up
fine. **Arithmetic checking catches a quantity that is inconsistent; only provenance checking
catches one that is consistent and mislabelled.** A reader who has seen all three should start asking *where did this number come from
and what does it count*, not only *do these numbers agree* — which is the habit that would have
prevented every error in this section, including the published one.

**Hard versus soft, stated because the soft part is load-bearing.** Measured or mechanically
derived: the 283, the bucket boundaries, both caller claims (grepped), `input/manager.py`'s
178/49/247 split, and #230's unreachability (verified by indentation). **A judgement, not a
measurement:** the line between "reachable" and "reachable but expensive" — the 150-statement tail
of roughly 28 functions whose bodies are `except Exception: logger.error(...)` arms needing fault
injection. **That 150 is what the corrected ceiling leans on hardest**, so its softness is not a
footnote: if the tail is dearer than judged, every row above moves the wrong way.

**What would narrow the range**, in priority order — **revised twice, and the revisions are the
point**: (i) **the mid-sized pool measured rather than estimated**, since it is what the gate now
turns on and it is the one group no PR owns; (ii) **2a-5's authorize-row yield**, counted as zero in
every row; (iii) `server.py` re-taken under sysmon so the whole bracket can sit on one core, and
with it whether the 142 Output-Profile bucket is spent — that single number decides between "short
184" and "short 43". **Done, and no longer open:** `server.py`'s reachability (561 of 844),
`input/manager.py`'s (247 of 474), and the fmp4/Output-Profile group's (66% of 735 from two probes)
— the last of which headed this list in the published revision as the dominant unknown.

**The options, for the user to choose between — this spec states them and recommends none.**
Widen the coverage PRs into the mid-sized files that lie outside their current scope — `views.py`,
`channel_status.py`, `client_manager.py`, `input/buffer.py`, `log_parsers.py`, `utils.py`,
`url_utils.py` — which hold several hundred missed statements between them and belong to no PR.
**The pool is already smaller than a file-level count suggests: 2a-3 spends roughly 53 of it without
naming either file in its gate** — `client_manager.py` 92 → 52 (zero spread on both sides) and
`input/buffer.py` ~99 → ~86 — so it stands at **~898, not 951**, before anyone widens anything. That
makes the option slightly cheaper and any margin computed against the full 951 slightly optimistic.
**This is the third instance of the already-banked shape and the first caught before it entered a
sum** rather than after. Nine of that 40 arrived as a side effect of a *correctness* fix — raising
`GHOST_MULTIPLIER` so the sweep runs several passes, making a pin actually pin — which hints the pool
may be more reachable than a file-level percentage implies. **A hypothesis, and this stage has
established what becomes of those.**
**The measured bracket narrows this option considerably**: full pools plus the soft tail land 10
short, so the concrete question is whether 2a-6 also takes **`http_streamer.py` (101 statements,
whole file, nothing imports it)** and whether 2a-4 and 2a-5 take their full reachable sets rather
than their planned targets — not an open-ended widening. Lower the gate to a measured achievable
figure; or add a PR. **The gate's value is
not changed here and no replacement is proposed.**

**Two things this finding is not.** It does **not** invalidate 2a-3 … 2a-6: their other half —
pinning parity-matrix rows so the behaviour survives a rewrite into Go — is untouched by coverage
arithmetic, and § Goal already names 2a and 2b as legitimate stopping points whose value survives
abandoning Go entirely. The gate is a precondition on **2c**, not on the work in flight. And it is
not a failure of the plan: **stage 2a's ordering exists precisely so that a gate nobody can meet is
discovered before a line of Go is written rather than after.** A mis-scoped gate surfacing here, with
four PRs still unimplemented and the decision still open, is that ordering paying off.

**No PR in stage 2c may merge until
this job reports ≥80% and Gate 1 is met** — the latter meaning *no row still carries an `owed:`
marker*, not merely that the guard test is green, which it is from 2a-1 onward by design (§ A6).
Stated as a CI precondition on 2c's first PR, not review discretion; 2b-3 is the PR that satisfies
it, being the owner of the last owed row.

### The subprocess harness — 2a's named deliverable

`channel_service.py` (~90% reachable), `output/ts/generator.py` (~80-85%) and most of `server.py`
(~70-75%) close mainly with Django-test-client requests against real Redis and an in-process fake
upstream — no new capability needed. `input/manager.py` (~40-50% reachable) and
`output/fmp4/manager.py` (~20-30%) do not: their uncovered code is shaped around a real subprocess's
stdout/stderr, and `CLAUDE.md` § Testing records the backend suite as never having had this
capability at all ("No backend unit test spawns a subprocess"). **2a-2 builds a harness that
spawns real subprocesses and serves real TS bytes from an in-process fake upstream** — a small,
canned-content Python HTTP server (`socketserver`/`http.server`, no external dependency), *not* a
reuse of the `e2e-upstream` Docker image: the backend test runner is itself a container, and nested
Docker is a poor trade for a unit test that should run in milliseconds, not spin up a sibling
container per test. `e2e-upstream`'s twelve-fault vocabulary (`e2e-upstream/src/faults.ts`) stays
serving e2e unchanged; the harness borrows its *vocabulary* (dead-air, slow-start, mid-stream
truncation, malformed TS, …) as Python fixtures, not its Docker image. **Eight of the twelve port;
the other four (`xc-auth-envelope`, `no-tv-archive`, `catchup-layout-404`, `range-unsupported`)
belong to surfaces D1 leaves in Python and are recorded as not ported rather than dropped.**

**The harness also carries a captured real-ffmpeg stderr corpus, and 2a-2's capture measured row 4's
arming delay rather than estimating it.** Driving the production command
(`ffmpeg -i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`, default `info` logging) with ffmpeg
**8.1.2** against an upstream held to **0.25x real time**, the cumulative `speed=` starts above 10x,
first dips below 1.0 after **~18 seconds** of wall clock and stays below from **~20 seconds** on,
ending below 0.9x. (A capture is a timing measurement: the shape reproduces, the digits do not, so
nothing may hardcode one — 2a-2's tests derive every literal from the corpus they captured.) That is
the "front-loaded lead must burn off" behaviour row 4 names, observed; it
independently corroborates the ~55 s figure `CLAUDE.md` quotes, and it is **the reason a live ffmpeg
cannot drive rows 1 and 4 inside a test budget** — those rows replay the captured records at a
cadence the test chooses. **Every stderr line the stand-in emits is a real capture**; a hand-written
progress line is legitimate only for a shape real ffmpeg cannot be made to emit on demand, and
carries its reason. This matters more than it looks: ffmpeg 8.1.2 appends an `elapsed=` field after
`speed=`, uses `Lsize=` on the final record, space-pads a short speed (`speed= 1.1x`), separates
records with a carriage return rather than a newline **except the last when the process exits
normally**, and emits scientific notation (`speed=…e+03x`) — four of which a hand-written fixture
would have got wrong, and the fifth of which is a real defect the capture found (parity-matrix
row 28, issue #227). **This harness is not
throwaway**: the Go relay needs an equivalent in its own suite (2c's own fault-injection fixtures),
and having already named the fault vocabulary in Python fixtures gives the Go author a spec to copy
rather than invent from `input/manager.py`'s prose alone.

**What the harness must decide, and it is 2a-2's decision to make, not this spec's — the round-6
amendments' § A2.** "Real subprocess" is one of two ways to reach the ≈827 subprocess-gated
statements, and the reachability analysis in § Verified facts shows the other one is cheaper for
**438** of them: `output/fmp4/manager.py` and `output/profile/manager.py` both obtain their process
from `posix_spawn_proc(...)` (`apps/proxy/live_proxy/utils.py:130`), so a fake exposing
`stdin`/`stdout`/`stderr`/`poll`/`wait`/`terminate` at that one seam covers both files with no fork
at all. `input/manager.py` has no such seam — an inline `os.posix_spawn` at `:793` with its own
`_SpawnedProcess` wrapper at `:813` — so it is reachable only by a real subprocess, by patching
`os.posix_spawn` globally, or by **extracting the same seam**, which is a production-code change
inside a stage otherwise scoped to tests (small, `posix_spawn` retained, not the `Popen`
simplification `CLAUDE.md` forbids). **2a-2's plan chooses among the three and says why**; this spec
records that the 80% gate is unreachable by pure-mock unit tests under any of them, which is the
part that does not depend on the choice. Whichever way 2a-2 goes, the harness still has to spawn a
real process for the ffmpeg-stderr rows the parity matrix names (rows 1-6), so its existence is not
in question — only how much of `input/manager.py`, `fmp4/manager.py` and `profile/manager.py` it is
asked to carry.

**Composition rule for every 2a test, stated because it is the difference between a test that helps
2c and one that only moves a number:** write tests that drive the relay through its **HTTP surface**
against **real dependencies** — the fake upstream, real Redis, real ffmpeg — never against mocks of
`server.py`'s or `input/manager.py`'s internals. Such tests run under `coverage` (so they count toward
Gate 2) and, because their assertions are about observable behaviour (bytes received, a status field's
value, a failover firing), they port to Go tests row-for-row against the parity matrix. A test that
mocks `StreamManager` and asserts an internal call count inflates coverage and teaches the Go
implementer nothing about what the relay is actually supposed to do.

### The seven PRs

**Added in this fix round.** This spec's first draft enumerated PRs for 2c and 2d but left 2a and
2b — one of them a legitimate stopping point, both of them the gate everything else depends on — as
prose forward-references with no branch, scope, gate or dependency order. Corrected here in 2c's own
table shape.

| PR | Branch | What it does | Gate | Depends on |
|---|---|---|---|---|
| 2a-1 | `migration/phase2a-parity-matrix` | `docs/relay-parity-matrix.md` (Gate 1's **27** rows above — corrected from 24 in the round-6 amendments, § A3 — and any further rows found while writing it) plus `e2e/tests/guards/parity-matrix.spec.ts`, the guard test that fails naming any row lacking a `file:line` citation or a test reference, and which accepts the white-box-only marker on rows 26-27, or an `owed: <PR id>` marker on a row not yet pinned, in place of a test reference. | Guard test green — **which is not Gate 1**: at 2a-1 most rows stand as `owed:`, deliberately, and the guard is asserting that every one of them is owned, cited and syntactically well-formed (§ A6) | — |
| 2a-2 | `migration/phase2a-subprocess-harness` | The real-subprocess, real-fake-upstream test harness (§ "The subprocess harness" above); no relay tests yet, just the harness and a smoke test proving it spawns a real process and serves real bytes. **Also, corrected in this fix round (§ NM3 in the round-2 review): `scripts/coverage_live_path.sh` itself** — the runnable per-label invocation from Gate 2, together with `scripts/coverage_live_path.coveragerc`, with no floor file and no CI-blocking wiring yet — so 2a-3…2a-6 have a real, reproducible command to quote a number from instead of an ad-hoc local run each. **This PR's plan carried an open decision, and settled it** (it was: reach the ≈827 subprocess-gated statements by a process fake at `posix_spawn_proc` plus an extracted seam in `input/manager.py`, or by real subprocesses throughout). **Settled as real subprocesses throughout, with no production-code change and no extracted seam** — because a real subprocess need not be a real ffmpeg. `input/manager.py`'s command comes from a `StreamProfile` row (`core/models.py:137-160`) and `output/fmp4/manager.py:32`'s `FFMPEG_REMUX_CMD` starts with the bare string `"ffmpeg"`, which `posix_spawn_proc` resolves through `shutil.which` (`utils.py:152`), so a scripted stand-in installed on `PATH` as `ffmpeg` reaches every spawn site untouched — measured at 6.5-8.1 ms per spawn. The fake was declined because it makes `posix_spawn_proc`, `_Proc` and `_SpawnedProcess` unreachable by construction, and because a stand-in on `PATH` is language-agnostic: 2c's Go relay spawns it unchanged. | Harness's own smoke test green under `coverage`; `scripts/coverage_live_path.sh` runs, prints a percentage, and reproduces § Verified facts' denominator of 7,978 exactly — the denominator is the check, not the `missing` count, which varies run to run once a tune exists (see the ratchet paragraph in Gate 2); the seam decision recorded in the PR description either way | 2a-1 (so new tests can cite matrix rows as they land) |
| 2a-3 | `migration/phase2a-ts-generator-coverage` | Tests against `output/ts/generator.py` and `services/channel_service.py`'s switch/stop paths, using the harness; closes matrix rows 7-10, 13. | `coverage_live_path.sh` (created in 2a-2) shows a measured increase on these two files; and matrix rows 7-10 and 13 each carry a test reference the parity-matrix guard accepts (round-6 amendments, § A6) | 2a-2 |
| 2a-4 | `migration/phase2a-manager-coverage` | Tests against `input/manager.py`'s transcode connection setup, stderr reader and health/reconnect loops — 771 of the ~1,024-missed-statement pair, of which 299 are strictly subprocess-gated and ~143 (the raw-HTTP Proxy path) need only a socket; closes matrix rows **1-6** — **row 12 moves to 2a-6** (round-6 amendments, § A5), since row 12 is fMP4's `_is_timeout` and this PR's subject is `input/manager.py`. | `coverage_live_path.sh` shows a measured increase on `input/manager.py`; and matrix rows 1-6 each carry a test reference the parity-matrix guard accepts (§ A6) | 2a-2 |
| 2a-5 | `migration/phase2a-server-and-authorize-coverage` | Tests against `server.py`'s bring-up, event listener loop and zombie detection — **plus the eight matrix rows no other PR owns, assigned here in the round-6 amendments (§ A4)**: rows **14-17** (the status payload's exact field set and types; the `stream_xc`→`stream_ts` decision hand-off; the stream-by-hash authorization shape; `ip_address`'s provenance) and rows **19, 20, 23, 25** (the Internal, Admin, Session and stream-by-hash authorize-matrix principals, none of which any `e2e/tests/` spec pins today). Rows 14-17 and 19-25 are view-level and authorize-shaped rather than byte-path, which is why they land beside `server.py`'s bring-up work rather than in a harness-heavy PR — and 2a-5 is correspondingly **the largest of the four coverage PRs, not the smallest**, which the first draft implied by giving it no rows at all. | `coverage_live_path.sh` shows a measured increase on `server.py`; matrix rows 14, 15, 16, 17, 19, 20, 23 and 25 — all eight, enumerated rather than ranged, since this is the gate the 2a-8 question turned on — each carry a test reference the guard test accepts | 2a-2 |
| 2a-6 | `migration/phase2a-fmp4-coverage` | Tests against `output/fmp4/manager.py`, `output/profile/manager.py` **and `output/fmp4/generator.py`** — closes matrix rows 11 **and 12**. ~~the least-reachable, least-covered group~~ **Withdrawn at `78695f45`: measurement put this group at 66% reachable against an estimate of ~20-30%, making it the *cheapest* group in 2a, not the dearest. The description survived here after the claim it rests on was withdrawn elsewhere in this document — a reader who reaches this table first would still be misled, so it is struck in place rather than deleted.** **`output/fmp4/generator.py` is added to this PR's scope in the round-6 amendments (§ A5): at 195 missed of 219 (11.0%) it is the lowest-covered file in the whole Gate 2 denominator, and the first draft named it in no 2a PR at all** — a file owned by nobody, in a stage whose gate is a coverage number. Row 12's fix belongs here too, since `_is_timeout` lives in that file (`output/fmp4/generator.py:339`). | `coverage_live_path.sh` shows a measured increase on **all three** files; and matrix rows 11 and 12 each carry a test reference the parity-matrix guard accepts (§ A6) | 2a-4 (shares harness patterns with the manager work) |
| 2a-7 | `migration/phase2a-coverage-gate` | The floor file, the `backend-tests.yml` per-label `coverage run --parallel-mode` + `coverage combine` CI wiring around the script 2a-2 already created (Gate 2 above), and the gate turning green and CI-blocking at ≥80%. | The gate itself, green and enforced in CI — this is the phase's first hard blocker turning off | 2a-3, 2a-4, 2a-5, 2a-6 |

**Every row is owned, and the roll-call is part of the amendment (round-6, § A4/A5) because "owned
by nobody" was the actual defect it fixed:** rows **1-6** → 2a-4; **7-10, 13** → 2a-3; **11, 12** →
2a-6; **14-17, 19, 20, 23, 25** → 2a-5; **18** → 2b-3 (the row is phrased as a question 2b-3
answers); **21, 22, 24** → existing `authorize-matrix.spec.ts` tests the matrix cites rather than
re-tests; **26, 27** → nothing, deliberately, being white-box-only. Twenty-seven rows, seven owners,
no gaps. The same rule applies to files: `output/fmp4/generator.py` was in the Gate 2 denominator
and in no PR's scope until § A5 put it in 2a-6's, and any future row or file added to this spec
carries an owner in the same edit.

**2a's own legitimate stopping point** (§ Goal) is after 2a-7: the matrix is pinned on every row
except **18**, which is phrased as a question 2b-3 answers and cannot close earlier; the subprocess
harness exists as a durable capability; and coverage sits at ≥80%. **Gate 1 itself closes in 2b-3**
— value that survives never starting 2c. **Corrected in the round-6 amendments (§ A7): the first
draft said "the matrix is 100% pinned" here, which was never reachable at 2a-7 under any assignment
of rows, since row 18 is `owed: 2b-3` in this spec's own roll-call.** The stopping point is real
either way — twenty-six of twenty-seven rows pinned, the harness built, the coverage floor
enforced — but it is one row short of Gate 1, and a stage that claims a gate it cannot reach makes
the gate unfalsifiable rather than met.

## Stage 2b — complete the contract (Python)

Phase 1 took the relay to zero ORM *writes*. It did not reach zero *reads* — its own § "ORM reads
that remain in the relay after PR 7" table names twelve surviving sites and states plainly that "a Go
relay cannot execute any row in this table." Re-derived here against `a948cd8a`, not copied from
Phase 1's table (written forward-looking at PR 4, now three PRs stale per the brief's own caveat):

| Site | Model | 2b's fix |
|---|---|---|
| `input/manager.py:737`, `StreamProfile.objects.get(name='ffmpeg', locked=True)` on the force-ffmpeg reconnect path | `StreamProfile` | Fold the locked ffmpeg profile's `{id, command, args}` into the `next-source` response, alongside the existing `stream_profile` payload — `POST /api/relay/channels/<id>/next-source` already carries a `stream_profile` object (§ The contract's Python precedent, `control_plane.py`'s `next_source()`), so this is a second key on an existing response, not a new route. |
| `services/channel_service.py:324,331,911`, `Channel`/`Stream` name fallbacks used when no name was supplied at init or after a switch | `Channel`, `Stream` | Both names are already resolved during `next-source`/`advance` — Django has them at hand when it builds the response. Add `channel_name`/`stream_name` as non-optional fields on both response bodies so the relay never has to guess. |
| `channel_status.py:74`, `Stream` name fallback when Redis has no stream name; `channel_status.py:106`, `M3UAccountProfile` name fallback | `Stream`, `M3UAccountProfile` | **Corrected in this fix round — not a confident deletion.** This spec's first draft claimed the metadata hash would always carry a name after the `channel_name`/`stream_name` addition above, making these fallbacks unreachable and safe to delete outright. That claim was never verified against `channel_service.py`'s actual write paths (does *every* channel-init and every switch write a name, with no code path that leaves the hash without one?), and asserting it without that proof is exactly the failure mode the review flagged elsewhere in this document (§ M18 in the review this fix round responds to): a third, undeclared parity exception arriving quietly inside "contract completion." The honest fix: **carry the names on the response as above, and leave the Redis-hash fallback reads in place as a defensive read for whatever path does not (yet, provably) always write one.** This still closes 2b's goal for the *common* case (the hash has a name, and the read is now redundant with the response the relay already received) without asserting a global invariant the tree does not yet prove. **This is compatible with 2c's "no Postgres driver" invariant, and it is worth one sentence saying why (§ Q3 in the round-2 review): the surviving fallback, if any, is Python code that is deleted wholesale in `migration/phase2d-delete-live-proxy`, not a shape the Go relay reimplements — the Go relay has the name in memory from 2b-1's `next-source` response and never needs a "Redis has no name, ask the DB" branch at all, so a Python-side fallback surviving to the end of 2b says nothing about what the Go binary links at the end of 2c.** What it *can* mean, if the fallback is ever actually exercised, is that Python and Go answer the status payload's `stream_name`/`m3u_profile_name` differently on that path — a genuine parity question, not an ORM-invariant risk, and it is parity-matrix row 18's job to hold 2c to whatever 2b-3 finds rather than leave it silently unaddressed. The zero-ORM guard test below (now with its allowlist, § NM2) is scoped to catch the ORM-read half specifically if any read is not, in fact, closed by the time 2b's PR lands. **2b-3's answer (Ruling R7, parity row 18): absence is the contract.** Neither fallback is reachable in a same-version deployment, and that is not what settles the question — the key is absent from the status payload entirely, not null, not `''`, when the metadata hash was never written a name, because `RelayChannelDetailSerializer` already declares both `stream_name`/`m3u_profile_name` `required=False`. The ORM read is best-effort enrichment on top of a contract that already permits absence, not a load-bearing repair; the Go relay, having no database, always leaves the key absent, which is inside the contract. Also `channel_status.py:92` was never the right line at this tree's revision — 2b-1 inserted a seven-line comment above it, moving the second fallback to `:106`; the spec and the matrix both carried the stale citation until 2b-3 fixed it in the same PR that answered the row. |
| `url_utils.py:247`, `get_connections_left(m3u_profile_id)` — `M3UAccountProfile.objects.get(id=m3u_profile_id)` | `M3UAccountProfile` | **New row, added in this fix round** — this spec's first draft incorrectly claimed this function was already deleted (§ What the code says). `grep -rn "get_connections_left" apps/proxy/` finds no caller outside `test_live_db_cleanup.py:167-172`'s own test. 2b's fix: delete the function and its test unless a real caller surfaces during 2b's own audit, in which case fold its answer into the `next-source`/`advance` response the same way as the `StreamProfile` row above. |
| `next_source.py:69-79`'s `get_stream_object`, `Stream.objects.select_related(...).get(stream_hash=id)` fallback used by the single-stream admin-preview surface (parity matrix row 16) | `Stream` | **New row, added in this fix round** (§ M15 in the review). `/proxy/ts/stream/<stream_hash>` has no `Channel` to resolve via `next-source`'s existing channel-uuid path. 2b extends `next-source`'s identifier resolution to accept either shape and answer the same payload either way — the relay already sends whatever identifier arrived in the URL; Django's resolution (`Channel` first, `Stream.stream_hash` fallback) is exactly what `get_stream_object` already does, moved to the contract side unchanged. |
| `views.py:152`, `OutputProfile.objects.filter(id=..., is_active=True).first()` so `build_command()` can be called | `OutputProfile` | Phase 1's Amendment S3 left this in deliberately — "the header contract cannot carry a built ffmpeg command." A control-plane **response body** can, unlike a header. **Decided in this fix round** (this spec's first draft left two shapes open with no decision, an implementer-facing gap flagged in review as m23): fold the built command into `next-source`'s response rather than a separate route — `next-source` already runs once per tune with the ORM open, and a separate `GET /api/relay/output-profiles/<id>/command` route would be a second round trip for data available at the same moment. **Corrected 2026-09-12, during 2b-2's own planning, and the "when `X-Relay-Output` names a profile" half of that decision is withdrawn: the response carries EVERY `is_active=True` profile, keyed by stringified id, as `{"id": int, "argv": [str, ...]}`.** `next-source` is a per-**channel** call (initial tune, failover, resume — `live_proxy/url_utils.py:56`, `input/manager.py:2076`, `services/channel_service.py:154`), while the Output Profile is resolved per **client** (`live_proxy/views.py:605` on the owner's init path, `:712` on every other client), and the second client on an already-running channel makes no `next-source` call at all. One profile per request therefore answers no client's question but the first's. The Go relay caches the map at tune and serves every later client from memory. **The Python relay does not consume the field** — `views.py:152`'s `OutputProfile.objects.filter(...)` survives 2b-2 deliberately, because closing it in Python would need a cache whose staleness semantics nothing here specifies (today an `OutputProfile` edit reaches the next client; cached, it would reach only the next tune), and it is Python that 2d deletes wholesale — the same reasoning this table already applies to the `channel_status.py` fallback rows above. 2b-3 records it in `zero_orm_allowlist.py` with this paragraph as its citation. |
| `apps/proxy/authorize_views.py:112-141`'s `User.objects.filter(id=int(user_id)).first()` inside `result_from_headers`, run on **every** trusted tune inside the relay process, from both `stream_ts` (`views.py:168`) and `stream_xc` (`views.py:825`) (§ What the code says) | `User` | The relay never needs the `User` row itself — only `user.custom_properties.get('output_format')` (`_resolve_output_format`, `live_proxy/views.py:112-131`) and the value `add_client` stores for display. Carry `output_format` as a resolved string on the trusted response — a sixth `X-Relay-*` header, `X-Relay-Output-Format`, set by `authorize_view` (which already resolved the `User` row to answer `output_profile_id`) — and store the raw `user_id` string for display/registration without ever re-querying it. Closes the last ORM read on the ordinary tune path. **Blast radius, named explicitly (§ M10 in the review):** this sixth header touches `docker/dispatcharr_api_params.conf` (currently exactly five `uwsgi_param HTTP_X_… "";` lines — becomes six), all nine relay-bound `docker/nginx.conf` locations (each needs a sixth `auth_request_set`/`uwsgi_param` pair, or `proxy_set_header` post-2d-flip on the three that move), `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`'s `AUTH_REQUEST_SET_VARS` set (six today — five `$relay_*` plus `$authorize_status` — becomes seven), and `apps/proxy/authorize_views.py`'s `result_from_headers` docstring/`internal_auth.py`'s `HEADER_RELAY_*`/`META_RELAY_*` pairs (a sixth name each). All four are part of this 2b PR's file list, not a follow-up. **A seventh header, `X-Relay-Client-IP`, joins it in the same PR** — found later in this fix round (§ Stage 2d's NB1 finding): the Go relay cannot derive the true client address from `REMOTE_ADDR`/forwarded headers the way the Python relay can, so `authorize_view` resolves it once via `get_client_ip(request)` and carries it the same way as `X-Relay-Output-Format`, in the same four files, bringing every one of this row's counts up by one more (seven `uwsgi_param`/`auth_request_set` lines, eight `AUTH_REQUEST_SET_VARS` entries). Bundled here rather than into 2d because it is a contract addition like the others, even though only the Go relay reads it — the Python relay ignores it exactly as it ignores today's five. |

**Also folded into the contract, not a read but the trap that motivates finishing this table:**
`proxy_settings` (`apps/proxy/config.py`'s `BaseConfig._proxy_settings_cache`, 10-second
process-local TTL) is why a buffering-threshold change today takes over 10 seconds to reach the
owning worker, on top of `StreamManager.__init__`'s own snapshot (`CLAUDE.md` § Known defects: "a
threshold change needs >10s to reach the owning worker and must land before the channel starts"). 2b
moves `proxy_settings` onto the `next-source` response (channel-start-time values only, matching D5's
"thresholds snapshotted at channel start" parity row) so the Go relay never reads `CoreSettings`
directly and the 10-second staleness window collapses to zero for every value that matters at
channel-start.

**2b ends with a guard test, `apps/proxy/live_proxy/tests/test_zero_orm_reads.py` — corrected in this
fix round, because a directory grep cannot see the relay's actual ORM exposure.** This spec's first
draft proposed `grep -rn "\.objects\." apps/proxy/live_proxy/ | grep -v tests` returns nothing, but
the relay reaches the ORM through `apps/proxy/next_source.py` — outside that directory — via
in-process imports: `input/manager.py:731` calls `get_stream_object(...)`, imported at
`url_utils.py:25` (`from apps.proxy.next_source import get_stream_object, transform_url`); the same
shape recurs at `views.py:900`, `:1250` (`from apps.proxy.next_source import resolve_source`) and
`services/channel_service.py:397`. None of these calls contains the literal substring `.objects.`
at its call site — only inside `next_source.py`'s own function bodies, outside the grep's directory
— so the naive grep would report success while the relay still executes ORM queries in-process on
every tune. **Corrected guard, two parts, with an explicit allowlist — a third correction in this
fix round, because the two-part guard as first specified could not pass while 2b-3 also,
deliberately, leaves a read in place (§ Stage 2b's `channel_status.py:74`/`:92` row; see NM2 in the
round-2 review).** (1) A static check that greps `apps/proxy/live_proxy/**` **and** every function
`next_source.py` exports that `live_proxy` still imports in-process, failing if any such function
contains `.objects.` or `get_object_or_404(` (the second grep shape the naive pattern also misses)
— **unless the exact `file:line` is named in a comment-cited allowlist**,
`apps/proxy/live_proxy/tests/zero_orm_allowlist.py`, the same shape
`e2e/tests/guards/allowlist.ts` already uses for the Redis importer allowlist: each entry names the
site, cites the PR and reasoning that left it in place, and the guard fails on any **new** site
while tolerating the ones already on the list. An empty allowlist is the target; a non-empty one is
not a failure of this PR, only an honestly-recorded fact for whoever next touches that file. (2) A
runtime check — a test that monkeypatches the Django DB connection to raise on any query and drives
**both** a full tune **and a status read** (`GET /proxy/relay/channels/<id>` without `?fields=state`,
which is what actually reaches `get_detailed_channel_info` and the two fallback reads in question)
end to end through the relay's HTTP surface using 2a's subprocess harness, asserting each completes
without the DB ever being touched *except* for sites named in the same allowlist. Corrected from
this spec's first draft, which drove only a tune — the fallback reads under discussion are on the
**status** path, not the tune path, so a tune-only runtime check would never execute them regardless
of whether they survive. The runtime check is the one that actually proves "zero ORM reads" (net of
the allowlist) rather than "the ORM happens not to appear on this line"; the static check is a fast
first pass that can be wrong in either direction on its own.

**2b-3 built an AST scan, not the grep this section describes, because issue #253 records that the grep fails in BOTH directions, not only the under-count already corrected above.** It also counts a docstring that quotes the ORM line it replaced — `ast` sees a docstring as a `Constant` and never as an `Attribute`, so that shape cannot arise, where a line-based grep would have to stop quoting the old code to pass, making the tree less legible to satisfy a check. **Ruling R1 states plainly what the static half does and does not prove, in its own module docstring**: it is a ratchet against a new textual ORM site or a new in-process import edge, never evidence of zero ORM reads on its own. Three classes stay invisible by construction — descriptor/property access (`stream.m3u_account`), dynamic dispatch (`getattr(obj, name)()`), and anything more than one import hop out of the package, transitive only within the module it lands in. The runtime half is what carries the proof, exactly as this section already says; a green static run alone must never be reported as it.

**Three ORM reads live in the relay that no 2b PR above removes are recorded separately, in
[issue #253](https://github.com/D10Scot/Dispatcharr/issues/253), rather than folded into the table.**
The most consequential is `channel.get_stream_profile()` (`live_proxy/views.py:430`,
`input/manager.py:741`/`:744`): its call site contains neither `.objects.` nor `get_object_or_404(`,
so it is invisible to the static half of the guard just described, and only the runtime check can
catch it.

**2b-3 settled two of #253's own open questions, one of them the other way from how the issue left it.** `resolve_source` is NOT dead in the relay — the issue's own "looks like API-process or dead code; they were read, not executed" caveat is withdrawn. It is called in-process on the operator switch paths: `views.py`'s `change_stream` and `next_stream`, and `services/channel_service.py`'s pub/sub-driven switch listener. Its reachable subtree carries roughly three dozen further ORM sites (`get_stream_info_for_switch`'s `get_object_or_404` chain, `_source_from_info`'s `StreamProfile.objects.get`, and the rest of `resolve_source`'s own helpers), all allowlisted with `POST /api/relay/channels/<id>/next-source`'s `target_stream_id` parameter — already on the contract — as what closes them; 2c-8 owns wiring the Go relay to make that call instead of importing the function. Separately, the AST scanner the corrected guard now runs (rather than the grep this section still describes) found a **fourth** ORM read the Stage 2b table and issue #253 both omit: `views.py`'s `_resolve_output_format` calls `CoreSettings.get_default_output_format()` directly, on the trusted branch, when `decision.output_format` is falsy. Structurally unreached by every drive 2b-3's own guard drives — 2b-2 always sets `X-Relay-Output-Format` on a trusted tune — it survives as a defensive fallback for a relay talking to a pre-2b-2 hop, and is allowlisted on that basis rather than deleted.

### The four PRs

**Added in this fix round**, matching 2c's PR-table shape (§ B7 in the review this responds to).

| PR | Branch | What it does | Gate | Depends on |
|---|---|---|---|---|
| 2b-1 | `migration/phase2b-names-and-profiles` | `channel_name`/`stream_name`/`m3u_profile_name` on `next-source`'s response and `advance`'s **request** body (`RelayAdvanceRequestSerializer`, `relay_serializers.py:187`) — both directions point Django's names at the relay, never the reverse; the `StreamProfile` fallback folded into `next-source`; `get_connections_left` deleted (or folded in, if a caller surfaces); `next-source`'s identifier resolution extended to accept a `stream_hash` (parity row 16); `proxy_settings` added to `next-source`'s response. | 2b's own zero-ORM guard test (part 1, static) shows a measured reduction in surviving sites | 2a-7 (Gate 2 must be green before 2c starts, and 2b's own coverage matters to that number too) |
| 2b-2 | `migration/phase2b-output-profile-and-user` | `OutputProfile.build_command()`'s output folded into `next-source`'s response as an `output_profiles` map of every active profile (see the Stage 2b table's corrected `views.py:152` row); the new `X-Relay-Output-Format` **and** `X-Relay-Client-IP` headers end to end (`authorize_view`, `dispatcharr_api_params.conf`, all nine nginx locations, the greybox spec's `AUTH_REQUEST_SET_VARS`, `internal_auth.py`'s name pairs) — the full blast-radius file list from the table above, both headers in one PR since they touch the same files. | Existing forged-header `@contract` test still 403s with both headers in place; `nginx-stream-buffering.spec.ts`'s test 2 updated and green | 2b-1 |
| 2b-3 | `migration/phase2b-zero-orm-guard` | The two-part guard test (static + runtime) plus `zero_orm_allowlist.py`; deletes whichever `channel_status.py:74`/`:92` fallback reads turn out, on inspection during this PR, to be provably unreachable — and, for whichever do not, adds them to the allowlist with a comment citing this decision rather than leaving them to fail the guard silently. **Corrected in this fix round (§ NM2 in the round-2 review): the previous gate — "both guard-test parts green" — could not be met by a PR whose own scope keeps a read in place, since the static guard would fail on it by construction. The allowlist is what makes "leave a read in place, deliberately" and "the guard passes" compatible.** | Both guard-test parts green **against the allowlist** — an empty allowlist is the best outcome but not the gate; a non-empty, comment-cited one still passes; **and Gate 1 is met** — `e2e/tests/guards/parity-matrix.spec.ts` reports no row still marked `owed:`. **Added in the round-6 amendments (§ A6) because no PR's gate was Gate 1**: 2a-1's is "guard green" (which is green by design with rows still owed), 2a-3 through 2a-6's are coverage increases plus their own rows, and 2a-7's is Gate 2 — even though D7 makes Gate 1 a hard precondition on every 2c PR. 2b-3 owns row 18, the last owed row in the phase, so it is necessarily the PR that turns Gate 1 off; a precondition no PR is required to reach is not a precondition | 2b-1, 2b-2 |
| 2b-4 | `migration/phase2b-coverage-80` | **Closes Gate 2's ≥80% requirement, reassigned here from 2a-7 (§ Stage 2a › Gate 2, amended).** Stage 2a ends measured at **74.30%** — 2,050 missing of 7,978, worst of 15 CI rounds — with the ratchet floor live in `backend-tests.yml`. This PR closes the remaining **455** statements and moves the floor to the 1,595 the gate allows. Scope it from a *measured* per-file reachability pass, not from an estimate: no reachability estimate in this document survived contact with stage 2a. | The floor file records ≤1,595 missing and `backend-tests.yml`'s `coverage-gate` job is green at it; **D7 blocks every 2c PR until then** | 2a-7 (the ratchet and the measurement it rests on) |

## Stage 2c — build the Go relay

**Process.** One binary, `relay-go`, a new supervisord program
(`docker/supervisord.d/relay-go.conf`), started by `DISPATCHARR_ROLE` `all` and `relay` (alongside,
not instead of, `relay-uwsgi` — both run throughout 2c; D1's scope split means neither is idle).
Binds `0.0.0.0:$(DISPATCHARR_RELAY_GO_PORT)`, default **5658** (§ Verified facts confirms this port
is free). Reads `SECRET_KEY` from `/data/jwt` exactly as `docker/entrypoint.sh` does for every other
role, for both HMAC contexts it needs to produce (`relay-trust` is never produced by the relay — only
verified — since nginx is the one that sets `X-Dispatcharr-Authorized`; the Go relay verifies it the
same way `internal_auth.request_is_relay_trusted` does) and both it needs to consume/produce for the
`/proxy/relay/…`/`/api/relay/…` contract (`internal-principal`, `internal-request` — see § The
contract's exact byte layout for the bound token, which the Go implementation must replicate exactly
or every internal call 403s).

**Concurrency.** One goroutine per client connection, one per upstream reader, one per ffmpeg stderr
reader — the direct translation of the relay's 27 `threading.Thread`s (currently greenlets sharing
one OS thread under gevent's monkey-patch) into native goroutines, which need no monkey-patch
equivalent because Go's runtime scheduler already multiplexes blocking I/O onto OS threads
transparently. Ring buffer in memory: chunks are immutable once written, so fan-out to N clients is N
slice headers over one backing array, no refcounting and no copy per client.

**Buffer depth — an explicit open item, not inherited.** The Python ring buffer's chunk size is
`TS_PACKET_SIZE * 5644` (~1.06 MB, `input/buffer.py`'s `target_chunk_size`, `CLAUDE.md` § Architecture)
with a 60-second Redis TTL absorbing memory pressure into Redis's own eviction. D2 removes that
absorber: **every** live channel's buffered window becomes resident in the relay process itself.
Sizing calculation, stated plainly as an open item 2c's first PR must resolve with a real number, not
carry forward unresolved: a 10 Mbps channel at 60 seconds of buffer is `10,000,000 bits/s ÷ 8 × 60s ≈
75 MB` resident per channel; ten concurrently-owned channels at that bitrate is ~750 MB in one
process, before per-client fan-out overhead (which D2's "N slice headers over one backing array"
design makes cheap but not free — each client's read cursor holds a reference that can pin an
otherwise-rotatable chunk). The buffer depth needs an explicit bound (a fixed chunk count or a fixed
byte budget per channel, whichever the sizing calculation in the implementing PR settles on) rather
than the inherited 60-second TTL, because a TTL measured in wall-clock time against an unbounded
memory budget is not a bound at all once channel count or bitrate exceeds what was measured.

**Repo layout.** `relay/` at the repo root, module `github.com/D10Scot/Dispatcharr/relay`, packages
split by concern — `channel` (ownership, lifecycle, state machine), `buffer` (the ring buffer and
chunk fan-out), `ffmpeg` (spawn, stderr parsing, the port of `log_parsers.py`), `control` (the
`/proxy/relay/…` server and the `/api/relay/…` client), `httpapi` (the public `/proxy/ts/stream/`
and XC handlers) — deliberately **not** mirroring `apps/proxy/live_proxy/`'s file layout, whose
largest file (`server.py`, 2,569 lines) is exactly the shape a from-scratch Go design should avoid
reproducing.

**Third-party Go dependencies: none.** stdlib only — `net/http`, `crypto/hmac`, `crypto/sha256`,
`os/exec`, `syscall.SysProcAttr`. `go.sum` stays empty through 2c. This is a rule to defend, not an
accident: every dependency added is a supply-chain surface `CLAUDE.md` § Supply chain security
otherwise has to extend Trivy/Grype/OSV-Scanner/Scorecard coverage to, and the relay's actual job —
proxy bytes, parse ffmpeg stderr with regexes, speak two small JSON contracts — needs nothing an HTTP
server and an HMAC library the stdlib doesn't already provide.

**The two invariants, the phase's checkable success criteria.** *The Go binary links no Postgres
driver.* This falls out of 2b **conditionally, not unconditionally — a qualification added in this
fix round (§ m-R3-2 in the round-3 review, catching a sentence this spec's own 2b-3 allowlist had
already made imprecise)**: once the contract carries everything 2b's table names *and every site 2b-3's
allowlist still names has either a contract field or a written reason the Go relay never needs to ask
it*, the Go relay has no ORM-shaped question left to ask, so there is nothing to import a driver for.
A non-empty `zero_orm_allowlist.py` at the end of 2b is therefore not a loose end 2c can ignore — it
is a punch list `2c-1` must clear (a contract field for each allowlisted site, or a documented reason
it needs none) **before** its first line of Go, stated as an explicit precondition on 2c-1 below, not
left implicit in a bare dependency on 2b-3, which a non-empty allowlist already satisfies — both
gates can be green with the punch list untouched. *The Go
binary links no Redis client.* Walked key-family by key-family against `apps/proxy/live_proxy/
redis_keys.py` — **corrected in this fix round to cover all 25 methods** (§ Verified facts: 18
`live:channel:{id}:*` methods plus 7 `output_*` ones; the first draft's walk covered roughly half
and undercounted the family itself as fourteen-plus-five):

| Key family | Method(s) | Becomes |
|---|---|---|
| Ring buffer + index/timestamps | `buffer_index`, `buffer_chunk`/`_prefix`, `chunk_timestamps`, and the seven `output_*` fMP4-buffer equivalents | D2's in-memory ring buffer struct |
| Client registry | `clients`, `client_metadata`, `client_stop` | The control API's in-memory client map, served over `/proxy/relay/…` (D4) |
| Ownership lease | `channel_owner` | **Deleted outright** — nothing to own with one process (D2) |
| Switch coordination | `switch_request`, `switch_status` | An in-process Go `chan` between the HTTP handler and the channel's own goroutine |
| Follower pub/sub | `events_channel` (`live:events:{id}`) | **Deleted** — was multi-worker follower-to-owner coordination; no purpose with one owner per channel by construction |
| Degraded-fallback cache | `channel_source_cache` | An in-memory field on the channel struct |
| Metadata hash | `channel_metadata` | The in-memory channel struct's own fields |
| Channel lifecycle flag | `channel_stopping` | An in-memory state-machine field |
| Timing/telemetry | `last_client_disconnect`, `connection_attempt`, `last_data`, `transcode_active` | In-memory fields on the channel struct, read by the status handler exactly as today's Redis reads are |
| fMP4 output state | `output_state`, `output_owner` | The fMP4 manager's own in-memory state (`output_owner` deleted with the ownership lease, same reasoning) |
| Settings | `proxy_settings` | Arrives over the contract (2b) |

`worker_heartbeat(worker_id)` is not part of this family (it is keyed on a worker, not a channel) and
has no Go relay analogue at all — a single relay process needs no heartbeat to announce itself to
other workers that no longer exist. `channel_stream(channel_pk)`/`stream_profile(stream_id)` are
Django-owned (§ Verified facts) and were never relay state to begin with. **If any family is found,
during implementation, not to fit this walk cleanly, the implementing PR says so honestly rather
than asserting the invariant met** — this spec states the walk as reasoning, not as a guarantee that
survives contact with code not yet written.

**It serves:** `GET /proxy/ts/stream/<id>`, the XC live roots, all five `/proxy/relay/…` control
routes (§ The contract, byte-identical JSON), `/healthz`, `/readyz` (D6). **It calls:** `next-source`,
`release`, `events` (§ The contract, exact timeouts and both HMAC headers), with the degraded
fallback to the channel-start-cached candidate list on an unreachable control plane (D5's parity
list — "the degraded next-source fallback is unenforced by design," carried forward unchanged from
Phase 1's own § Risks).

### The nine PRs

**The workflow-drift maintenance work (§ Verified facts) is deliberately not one of these nine — a
correction from this spec's first draft, which listed it as `2c-0` and made it a hard dependency of
everything else.** None of the user's decisions requires it; it is scope creep wearing a phase-2
branch name, on ten files this phase does not otherwise touch. It is recorded as a standing
recommendation (a separate `chore/` PR off `main`, or installing Renovate) and 2c-1 below does not
depend on it — `go-tests.yml` pinning current versions on its own first commit is correct regardless
of what the ten pre-existing workflows pin.

| PR | Branch | What it does | Gate | Depends on |
|---|---|---|---|---|
| 2c-1 | `migration/phase2c-skeleton` | `relay/` skeleton: module init, `main.go`, `httpapi`/`control`/`channel`/`buffer`/`ffmpeg` package stubs, `docker/supervisord.d/relay-go.conf`, the Dockerfile builder stage, `go-tests.yml` (build + lint + `go vet`, no coverage gate yet — nothing to cover), `/healthz`/`/readyz` returning static 200s, a dev-only route flag so this PR is inert in every non-dev deployment. **Precondition, added in this fix round (§ m-R3-2): if `zero_orm_allowlist.py` is non-empty, this PR's own description names, for every entry, either the contract field that closes it or the written reason the Go relay never asks that question — the "no Postgres driver" invariant is conditional on this, not automatic (§ Stage 2c's invariant text). Stated plainly rather than left to imply more rigour than exists (round-4 review, nm-R4-2): unlike D7's coverage gates, this precondition is enforced by the PR description and its reviewer, not by CI — deciding whether a written reason for skipping a contract field is a *good* reason is not a grep, so no mechanical check for it is proposed here. The mechanical backstop is downstream, at 2c-9: a driver import would still fail the build/`go.sum`-empty check regardless of whether this precondition was honoured, which is why an unmechanised precondition here is an accepted gap rather than a silent one.** | `go build ./...`, `golangci-lint run`, `go vet ./...` all green; zizmor clean on `go-tests.yml` from its first commit; the allowlist reconciliation above stated explicitly, not silently assumed; **and, added in this fix round, the Go toolchain and action pins are re-resolved at PR time, not carried forward from this spec's 2026-09-09 values** — `go.dev/dl`, `docker buildx imagetools inspect` against the current `golang` tag, and fresh `gh api .../commits/<tag> --jq .sha` lookups for `golangci-lint-action`/`setup-go`/`checkout`, committed with whatever the tool returns on the day this PR is opened | 2b-3 — which is where **both** gates are finally satisfied: Gate 2 went green at 2a-7 and stays green, and Gate 1 closes here with row 18 (§ A6/A7) — **and** the allowlist reconciliation above |
| 2c-2 | `migration/phase2c-vertical-slice` | The Proxy stream-profile architecture only (no ffmpeg spawn yet): one client, in-memory ring buffer, MPEG-TS passthrough for a single upstream. Proves the buffer/fan-out shape end to end before ffmpeg complexity is added. | New Go tests pass with `-race`; parity matrix rows 7, 9 (chunk monotonicity, 188-byte realignment) get a Go column | 2c-1 |
| 2c-3 | `migration/phase2c-fanout` | Multi-client fan-out, join-5s-behind, the client registry, `?clients=all` on `GET /proxy/relay/channels` | Rows 8, 10, 13 get a Go column | 2c-2 |
| 2c-4 | `migration/phase2c-ffmpeg` | ffmpeg spawn via `os/exec` + `syscall.SysProcAttr{Setpgid, Pdeathsig}` (D5 exception 1), the `log_parsers.py` port | Row 4 (the `speed=` arming delay) gets a Go column with its own real-ffmpeg test, mirroring 2a's harness | 2c-3 |
| 2c-5 | `migration/phase2c-failover` | The three failover triggers, control-plane client (`next-source`/`release`/`events`, both HMAC headers, the exact timeout table), the degraded fallback to the cached candidate list | Rows 1, 2, 3, 5, 6 get a Go column | 2c-4 |
| 2c-6 | `migration/phase2c-fmp4` | fMP4 output format, including row 12's known timeout gap, reproduced not fixed | Row 12 gets a Go column | 2c-5 |
| 2c-7 | `migration/phase2c-output-profile` | Output Profile shared transcode per `(channel, profile)` | Row 11 gets a Go column | 2c-6 |
| 2c-8 | `migration/phase2c-control-drain` | Remaining control routes (single-channel `GET`/`DELETE`, `advance`), SIGTERM drain (D6), the dev-only `POST /_dispatcharr/authorize-internal` fallback (D5 exception 2, now fully specified — § The contract, including why it needs its own nginx-unshielded path and `IsInternalRelay` gating) | Every remaining un-Go'd matrix row gets a column | 2c-7 |
| 2c-9 | `migration/phase2c-go-coverage-gate` | `go test ./... -race -cover` wired into a new `scripts/coverage_live_path_go.floor` ratchet, raised to ≥80%; parity matrix's Python test-reference column gains its Go counterpart on every row | A new `go-tests.yml` **`Go result`** aggregate green, built in the four-part shape `CLAUDE.md` § Testing prescribes for every requireable check (no `paths:` filter on `pull_request`, a cheap always-running change detector, an `if: always()` aggregate with the three branches, a skipped heavy job on a required run failing the aggregate) — **note, added in this fix round, that making `Go result` an actually-required check on the Main ruleset is a repo-settings action, the same class this spec already flags for Renovate elsewhere, not something this PR's commit alone accomplishes** | 2c-8, matrix 100% Go-columned |

## Stage 2d — cutover, and its trap

**The historical bug this stage exists to not repeat.** Every live-bound nginx location today carries
`uwsgi_buffering off`, because `uwsgi_pass` is the directive family in play; `CLAUDE.md` records a
past incident where the wrong directive family (`proxy_buffering off`, which does nothing under
`uwsgi_pass`) let nginx silently spool live TS to disk. The Go relay speaks plain HTTP, not the uwsgi
wire protocol, so the live locations move from `uwsgi_pass` to `proxy_pass` — and `uwsgi_buffering
off` is **inert** under `proxy_pass`; the directive that actually matters there is `proxy_buffering
off`. This is precisely the trap CLAUDE.md's incident already describes, arriving from the opposite
direction: getting the *right* directive for the *old* protocol was the past bug; getting the *wrong*
protocol's directive for the *new* protocol is this cutover's version of the same mistake, and it is
worth naming exactly this bluntly because it is easy to paste the working `uwsgi_*` block and change
only `_pass` while porting a location by hand.

**Per-location change, at cutover, for four locations, not three — corrected in this fix round.**
This spec's first draft named only the three D1-scoped byte-path locations (`location ^~
/proxy/ts/stream/`, `location ^~ /live/`, `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`) and
missed `location ^~ /proxy/relay/` (`docker/nginx.conf:356-360`) entirely. That location is how
Django's `apps/proxy/relay_client.py` reaches **all five** control routes — including
`_live_connections()`, which `check_user_stream_limits` calls from inside `authorize_stream` on
**every live tune** (D4). Under D3's hard cutover the Go relay owns the live channel registry these
calls ask about, so `/proxy/relay/` has to move too, or Django keeps asking the Python relay for a
client list it no longer has and every live stream-limit check fails open forever.

The three byte-path locations:

```nginx
# before (uwsgi_pass, Python relay):
uwsgi_buffering off;
uwsgi_pass $relay_upstream;

# after (proxy_pass, Go relay):
proxy_buffering off;
proxy_request_buffering off;
proxy_http_version 1.1;
proxy_pass http://relay_go;
```

`/proxy/relay/`, which carries no `uwsgi_buffering off` today (it serves short JSON, not a stream)
and needs none after the flip either:

```nginx
# before:
include /etc/nginx/dispatcharr_api_params.conf;
uwsgi_read_timeout 30s;
uwsgi_pass relay_py;

# after:
include /etc/nginx/dispatcharr_api_params_proxy.conf;   # new file, see below
proxy_read_timeout 30s;
proxy_pass http://relay_go;
```

**`$relay_upstream` cannot be reused for this — a second gap this spec's first draft had, corrected
here.** `map $relay_name $relay_upstream { default relay_py; py relay_py; }`
(`docker/nginx.conf:36-39`) resolves to `relay_py` for every value `X-Relay-Name` can currently
carry, because `authorize_views.py:139` sets one process-wide constant,
`settings.RELAY_DEFAULT_NAME`. Writing `proxy_pass http://$relay_upstream;` on the three flipped
locations would send their traffic to the same upstream group the five VOD/catch-up locations still
use — the map has no way to say "these three locations resolve differently than those five." This
spec chooses the simpler of the two options ADR 0005's own canary machinery would otherwise suggest,
consistent with D3's "no per-channel canary, no second map entry live at once": **hardcode
`proxy_pass http://relay_go;`** on the four locations that move, and leave the `map`,
`RELAY_DEFAULT_NAME` and `relay_py` completely untouched for the five that don't. A new upstream
block, mirroring `nginx.conf:8-23`'s treatment of `RELAY_UPSTREAM`:

```nginx
upstream relay_go {
    server RELAY_GO_UPSTREAM;   # sed'd at boot by docker/init/03-init-dispatcharr.sh,
                                 # exactly like RELAY_UPSTREAM and NGINX_PORT --
                                 # 127.0.0.1:5658 outside modular, <relay host>:5658 in modular.
}
```

nginx resolves this name **once, at config load** — the same warning `nginx.conf`'s own comment on
`RELAY_UPSTREAM` already carries: a modular `web` container started with no `relay` container in
DNS fails config load outright ("host not found in upstream"), which is why
`docker/docker-compose.yml` gives `web` a `depends_on` on `relay` already, and unchanged by this
addition since the Go relay runs inside the same `relay` container/role as the Python one (§ Stage
2c's "Process").

`docker/dispatcharr_api_params.conf` is a **`uwsgi_param`** file — five `uwsgi_param HTTP_X_… "";`
lines plus `include uwsgi_params;` — and every line in it is a no-op under `proxy_pass`. A third gap
this spec's first draft had: it never named this file at all in the cutover, and the guarantee it
states in its own header comment ("a client-supplied `X-Relay-*` header never reaches the relay on
this path") would silently stop being true on the four flipped locations unless a `proxy_set_header`
twin exists. New file, `docker/dispatcharr_api_params_proxy.conf`:

```nginx
proxy_set_header X-Dispatcharr-Authorized "";
proxy_set_header X-Relay-Channel "";
proxy_set_header X-Relay-Output "";
proxy_set_header X-Relay-Client "";
proxy_set_header X-Relay-User "";
proxy_set_header X-Relay-Output-Format "";   # 2b's sixth header
proxy_set_header X-Relay-Client-IP "";       # 2b's seventh header (NB1, this fix round)
```

used only by `/proxy/relay/`, which is Django-bound but no longer `uwsgi_pass`. The three byte-path
locations don't need this file at all — they *set* the marker plus four (six, after 2b-2) `X-Relay-*`
headers from `auth_request_set` variables via `proxy_set_header X-Relay-* $relay_*;` — corrected
count in this fix round (§ m-R3-3 in the round-3 review): the trust marker is not itself one of the
`X-Relay-*` family, so the two counts (`auth_request_set` variables, six today and eight after
2b-2's two headers, since `$relay_name` is `auth_request_set`-only and never forwarded; and the
forwarded `X-Relay-*` params, four today and six after) differ by one throughout this section. They
don't blank them; the
client-header-override guarantee there survives cutover by the same nginx mechanism
(`proxy_set_header` unconditionally sets the outgoing header, same as the `HTTP_`-prefixed
`uwsgi_param` rule did), but the **mechanism changed**, so the E2E test that sends a forged marker
and a forged `X-Relay-Channel` for a hidden channel (Phase 1 PR 5's `@contract` test) must be
re-pointed at the new location and re-verified to still 403, not assumed to carry over because the
outcome used to be the same.

**A second consequence of that same `proxy_set_header` array-directive rule — found in this fix
round, and it is precisely the class of trap § Stage 2d exists to catch, arriving through the very
mechanism this section just used to fix B4/B6.** `docker/nginx.conf`'s `server` block declares six
`proxy_set_header` directives at `:51-56` (`X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Host`,
`X-Forwarded-Proto`, `Host`, `X-Forwarded-Port`). The moment any of the three byte-path locations
declares its own `proxy_set_header X-Relay-Channel $relay_channel;` (which this design requires),
**all six server-level ones are discarded for that location** — the identical replace-not-merge
inheritance rule `docker/dispatcharr_api_params.conf`'s own header comment already documents for
`uwsgi_param` ("a location that declares any `uwsgi_param` of its own inherits none from the
enclosing level"), one rule with two directive-family faces, not two coincidences. The Go relay then
sees `Host: relay_go`, no `X-Real-IP`, no `X-Forwarded-For`.

That is a parity break, not just hygiene, because the client IP is externally observable:
`apps/proxy/live_proxy/views.py:195`'s `client_ip = get_client_ip(request)` →
`client_manager.py:215-230`'s `add_client(..., client_ip, ...)` → `"ip_address": client_ip` → the
wire on **both** status endpoints (`relay_serializers.py:29`, `RelayChannelClientSerializer
.ip_address`; `:79`, `RelayDetailClientSerializer.ip_address`). `get_client_ip`
(`dispatcharr/utils.py:342-370`) honours `X-Real-IP`/`X-Forwarded-For` only when `REMOTE_ADDR` is a
trusted proxy (`LOCAL_NETWORK_CIDRS`/`DISPATCHARR_TRUSTED_PROXIES`); today, under `uwsgi_pass`,
`REMOTE_ADDR` already carries the real client address (`proxy_set_header` has no effect on
`uwsgi_pass` at all), so the forwarded headers are irrelevant and this never bites. After the flip,
nginx *is* the Go relay's peer, so the client's address can only arrive in a forwarded header —
exactly the headers the location just discarded. Uncaught, `ip_address` silently becomes nginx's own
address (or empty) for every live client on both status endpoints, while VOD/catch-up (still
`uwsgi_pass`) keep reporting correctly — invisible in dev, invisible in a smoke test, wrong in
production.

**Fix, two parts.** (1) Each of the **three byte-path** flipped locations re-declares all six
server-level `proxy_set_header` lines alongside its own `X-Relay-*` ones — the `proxy_pass` twin of
the `include uwsgi_params;` repetition `nginx.conf` already performs per location for the same
reason. **`/proxy/relay/`, the fourth flipped location, deliberately needs none of the six** — added
in this fix round, since the same replace-not-merge rule applies to it too and the exemption is
otherwise unstated: its client is Django, not a viewer, and the Go control API reads neither a
forwarded address nor a forwarded `Host` from that location; losing `Host: $host` on a JSON API
between two internal processes is inert. (2) For `ip_address` specifically, rather than teaching the Go relay `get_client_ip`'s trusted-proxy
semantics (a second configuration surface — `LOCAL_NETWORK_CIDRS`/`DISPATCHARR_TRUSTED_PROXIES` —
the Go process would need to read and keep in sync with Django's), **the authorize hop resolves it
once, the same way it already resolves `output_format` for 2b**: a seventh `X-Relay-*` header,
`X-Relay-Client-IP`, set by `authorize_view` from `get_client_ip(request)` and carried through
exactly like the other six — one more line in the same four files 2b-2 already touches for
`X-Relay-Output-Format`, not a new mechanism. Parity-matrix row 17, new in this fix round: `ip_address`
on both status endpoints, sourced from `X-Relay-Client-IP` rather than `REMOTE_ADDR` post-cutover.
Other simple (non-array) directives — `client_max_body_size 0;` (`:49`), `proxy_read_timeout 300;`
(`:48`) — inherit normally and need no re-declaration; naming which directive family is and is not
affected is what stops an implementer over-correcting by repeating directives that were never at
risk.

**`e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` (386 lines) is a four-test file, and
this spec's first draft's account of it was wrong in two ways: it described a single set assertion
where there are four separate tests, and it named none of the three that actually break at
cutover.** Corrected, per test:

- **Test 1** (`'every relay-bound location keeps uwsgi_buffering off'`) asserts an exact nine-entry
  set, `RELAY_BOUND_TARGETS` — `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/live/`,
  `/movie/`, `/series/`, `/timeshift/`, `/streaming/timeshift.php`, and the XC regex — via
  `toEqual([...RELAY_BOUND_TARGETS].sort())`, a set-equality vacuous-pass guard. `/proxy/relay/` was
  never in this set (it carries no buffering directive at all). **Rewrite**: split into a **six**-
  target `uwsgi_buffering off` set (`/proxy/vod/`, `/proxy/catchup/`, `/movie/`, `/series/`,
  `/timeshift/`, `/streaming/timeshift.php` — unchanged) and a **three**-target `proxy_buffering
  off` set (`/proxy/ts/stream/`, `/live/`, the XC regex — flipped), each still a `toEqual` on a
  sorted array so the vacuous-pass guard survives on both halves.
- **Test 2** (`'every relay-bound location authorizes through the hop'`) asserts, on the same nine
  blocks, `auth_request /_dispatcharr/authorize;`, the six `AUTH_REQUEST_SET_VARS` as they stand
  today (`$relay_name`, `$relay_channel`, `$relay_output`, `$relay_client`, `$relay_user`,
  `$authorize_status`) — 2b-2's two new headers (`X-Relay-Output-Format`, `X-Relay-Client-IP`) make
  this **eight** by the time this PR runs, since 2b precedes 2d in the phase's own dependency order;
  not a change this rewrite performs, but confirmation the array 2b-2 edited already carries both
  before this test's own edits land — a line matching `/uwsgi_param\s+HTTP_X_DISPATCHARR_AUTHORIZED/`
  whose
  value matches `/"[0-9a-f]{64}"/`, and `error_page 403 = @authorize_denied;`. The three flipped
  locations no longer carry a `uwsgi_param` line at all. **Rewrite**: split the marker assertion by
  directive family — `uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED` on the six staying locations,
  `proxy_set_header X-Dispatcharr-Authorized` on the three flipped ones, both still matching
  `/"[0-9a-f]{64}"/`; `auth_request_set` and `error_page` are directive-family-agnostic and need no
  change on either half.
- **Test 3** (`'every location outside the hop blanks the trust params'`) enumerates thirteen
  Django-bound targets, **`/proxy/relay/` among them**, and asserts each includes
  `dispatcharr_api_params.conf` and runs no `auth_request`. **Rewrite**: remove `/proxy/relay/` from
  this list — after the flip it is Go-relay-bound, not Django-bound, and belongs to test 4 instead;
  the other twelve targets are untouched.
- **Test 4** — `/proxy/relay/`'s own shape: today, `uwsgi_pass relay_py` present, `internal;`
  absent, `auth_request` absent, the blanking include present, `uwsgi_read_timeout 30s` present.
  **Rewrite**: `proxy_pass http://relay_go;` present, `internal;` still absent (Django still dials
  it as an ordinary client — D9's reasoning is unaffected by the language change), `auth_request`
  still absent, `dispatcharr_api_params_proxy.conf`'s include present, `proxy_read_timeout 30s`
  present.

The brace-depth `parseLocationBlocks` parser itself is unchanged across all four rewrites — it is
already directive-agnostic; only what each test asserts on the parsed blocks changes.

### Deletion order — one PR each

1. **`migration/phase2d-boot-trap-relocation`** — relocate `RedisKeys` and `ChannelMetadataField` out
   of `apps/proxy/live_proxy/`. `apps/channels/models.py:6-7` imports both at module level, loaded by
   every migration and management command (`CLAUDE.md` § Structural constraints: "one import added to
   `live_proxy/constants.py` and Django stops booting"). Gate: `manage.py check` green, every backend
   label green.
2. **`migration/phase2d-admin-wrappers`** — move `live_proxy/views.py`'s Django-side `IsAdmin`
   wrappers (`channel_status`, `stop_channel`, `stop_client`, `change_stream`, `next_stream`) to
   `apps/proxy/`, keeping URLs, names and permission classes unchanged so `frontend/src/api.js` never
   notices. Gate: existing frontend Stats/admin-UI tests unchanged and green.
3. **`migration/phase2d-nginx-flip`** — the four-location `proxy_pass` change (three byte-path
   locations plus `/proxy/relay/`), the new `upstream relay_go`/`RELAY_GO_UPSTREAM` sed, the new
   `docker/dispatcharr_api_params_proxy.conf`, and the greybox spec's four-test rewrite, landed
   together (the spec must not go green before the flip it is asserting, nor red after). Gate:
   `E2E result` green including the rewritten buffering spec and the re-pointed forged-marker test.
4. **`migration/phase2d-delete-live-proxy`** — delete `apps/proxy/live_proxy/` and its ~564 tests
   wholesale; rewrite the two remaining greybox specs (multi-client sharing, output-profile sharing)
   that imported relay internals directly rather than going through HTTP, since those internals no
   longer exist; update `e2e/COVERAGE.md` and `e2e/tests/guards/allowlist.ts`'s `GREYBOX_REDIS` entry
   (the live half of what it guarded is gone; the VOD/catch-up half stays); **added in this fix
   round** — remove `dispatcharr/test_discovery.py`'s `_PATH_ALIASES` entry
   `("apps/proxy/live_proxy/", ("apps.proxy.live_proxy", "apps.channels"))`, which this spec's first
   draft never named despite its own gate depending on exactly this file, and update
   `tests/test_ci_test_routing.py`, which `CLAUDE.md` § Testing records as pinning "all of it" — one
   edit, two pinning tests, since `_SHARED_PATH_PREFIXES` and the commit gate both derive labels from
   the same `scripts/ci_backend_test_labels.py`. Gate: `Backend result` green with 15 labels instead
   of 16 (`apps.proxy.live_proxy.tests` no longer exists to run), `tests/test_ci_test_routing.py`
   green, `E2E result` green.
5. **`migration/phase2d-docs`** — `CLAUDE.md` (the relay is now two processes across two languages;
   every `apps/proxy/live_proxy/` reference in § Architecture, § Known defects, § Testing rewritten
   or removed), `CONTEXT.md`, a new ADR for the Go boundary (recording D2/D3's reasoning as durable
   decision history the way ADR 0005 recorded ADR-worthy Phase 1 reasoning), the parity matrix's
   Python column fully replaced by its Go column, `metrics/curated/` updated in the same PR per
   `docs/agents/metrics.md`'s standing rule. Gate: `python -m metrics.build --validate-only` green.

`docker/uwsgi.relay.ini` and the Python relay process **stay**, narrowed to VOD and catch-up for the
remainder of Phase 3.

## Requirements this phase meets or carries

| Requirement | Status | Where |
|---|---|---|
| The live relay performs zero ORM reads. | **Met**, with the honesty caveat § Stage 2b's own table states: some of the deleted fallback reads may turn out on inspection to still be needed, and the guard test — not the table's row count — is the actual close criterion. | 2b-1, 2b-2, 2b-3 |
| No live client keys exist in Redis. | **Met, and already half-true before this phase started** — `_live_connections` already asks the relay over HTTP (D4). | 2c-3 |
| The Go binary links no Postgres driver, no Redis client. | **Met by construction**, walked family-by-family in § Stage 2c; recorded honestly as a walk, not a guarantee, until 2c-9 confirms it against the finished `go.sum` (which should still be empty). | 2c-9 |
| Strict behavioural parity on every externally-observable live-path behaviour, defects included. | **Met**, by the parity matrix reaching 100% Go-columned rows in 2c-9, with the two named D5 exceptions recorded as deliberate, not accidental, divergence. | 2c-9 |
| The ownership lease's un-fenced write path is closed. | **Met, by elimination rather than by fencing.** D2 deletes the lease outright; there is no analogous defect in a single-owner-per-process design. `CLAUDE.md`'s carried defect is retired, not fixed in place. | 2c-2 |
| A drain on shutdown, a readiness probe, a health check. | **Met**, new capability the Python relay never had (D6). | 2c-8 |
| Third-party Go dependencies: none. | **Met**, `go.sum` verified empty at 2c-9. | 2c-1..2c-9 |
| Coverage on the live path: ≥80% before Go starts, transferring to Go at ≥80%. | **Met**, Gate 2 (2a-7) and the Go ratchet (2c-9). | 2a-7, 2c-9 |
| nginx's live-bound locations, all four of them, carry the correct buffering directive (or none) for their protocol. | **Met**, and the specific historical trap is named and guarded against explicitly (§ Stage 2d) — corrected in this fix round to cover `/proxy/relay/` alongside the three byte-path locations, not just the three. | `migration/phase2d-nginx-flip` |

## Testing

- **The parity matrix's guard test** (`e2e/tests/guards/parity-matrix.spec.ts`, 2a) — fails naming any
  row lacking a `file:line` citation, and any row carrying none of a test reference, the
  white-box-only marker or an `owed: <PR id>` marker naming a PR in this phase. **Its green/red
  status is not Gate 1** (§ A6): it is green from 2a-1 onward, and what closes Gate 1 is the guard
  reporting *no owed row left*, which happens in 2b-3. The distinction is the difference between
  "every behaviour is owned" and "every behaviour is pinned," and this phase needs both, in that
  order.
- **The subprocess harness's own tests** (2a-2 onward) — real ffmpeg, real fake-upstream HTTP
  server, real Redis; these are what move `input/manager.py` and `output/fmp4/manager.py` off their
  20-50% floor and are the tests 2c's Go implementer reads first.
- **`scripts/coverage_live_path.sh`'s ratchet** (2a-7, then 2c-9's Go equivalent) — CI-enforced,
  per-label-plus-`coverage combine` floor (§ Stage 2a's Gate 2 correction), not a report.
- **The zero-ORM guard's two parts** (2b-3) — the static grep-plus-`next_source.py`-entry-point check,
  and the runtime DB-connection-raises check; both must be green, not just the static one.
- **Existing coverage this spec relies on rather than re-proves**: Phase 1's own § Testing list
  (TTFB, SPA-three-segment routing, the modular role split, the authorize matrix, failover-produces-
  events, Django-down/bounded-relay-restart) — none of it changes shape in this phase except the four
  nginx locations `migration/phase2d-nginx-flip` touches, and those get their own re-pointed tests
  rather than an assumed carry-over.
- **The forged-marker `@contract` test** (Phase 1 PR 5) — re-pointed at the post-flip location in
  `migration/phase2d-nginx-flip`, verified to still 403 under `proxy_pass`, not assumed.
- **`nginx-stream-buffering.spec.ts`'s rewrite** (`migration/phase2d-nginx-flip`) — all four tests
  named in § Stage 2d, not a single set assertion.
- **Go tests, `go test ./... -race -cover`** (2c-1 onward) — `-race` is not optional given the
  concurrency model change from gevent-cooperative to OS-thread-parallel goroutines; a data race the
  Python implementation's single-OS-thread execution model made structurally impossible becomes
  possible for the first time in this phase, and `-race` is the cheapest available check for exactly
  that new failure class.

## Documentation

- `docs/relay-parity-matrix.md` — created in `migration/phase2a-parity-matrix` (2a-1), updated by
  every PR in 2a, **2b** and 2c that closes a row — **`2b` corrected in the round-6 amendments
  (§ A7)**: row 18 is 2b-3's, so 2b-3 both edits this file and is the PR whose `owed:` removal
  closes Gate 1. A list naming only 2a and 2c reads as if the matrix were finished when 2a is.
- `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (this document) — PR 0, this branch,
  docs-only.
- Per-PR `CLAUDE.md` corrections are listed where each PR changes something CLAUDE.md currently
  states as fact; `migration/phase2d-docs` is the consolidation pass, not the only place corrections
  land — a PR that changes a fact CLAUDE.md states should correct it in the same PR, per the
  project's standing convention (Phase 1 spec's own per-PR correction bullets, followed here
  identically).
- `e2e/COVERAGE.md` — new rows for every 2a/2c Playwright addition, updated in the same PR as the
  test per the standing rule (`e2e/README.md`, `CLAUDE.md` § Testing).
- A new ADR for the Go boundary — `migration/phase2d-docs`, recording D2 (memory not Redis) and D3
  (hard cutover, no canary despite ADR 0005's mechanism existing) as the two decisions worth a
  durable record, in ADR 0005's own idiom (Context / Decision / Consequences).
- `metrics/curated/` — updated in `migration/phase2d-docs` per `docs/agents/metrics.md`'s standing
  rule: a `phase-start` milestone for `phase2` (this spec's own commit) and a `phase-done` milestone
  added by whoever merges the final PR (a merge commit cannot name itself, the same constraint Phase
  1's spec recorded).

## Done log

Filled in as PRs merge; this spec lands as its own PR 0.

| Item | PR | Merged |
|---|---|---|
| This spec | — | — |

## Risks

- **A `SECRET_KEY`/`/data/jwt` mismatch between roles is a real, previously-seen fault this phase
  must not turn into a harder failure than it is today — found and closed in the round-2 fix
  (§ The contract's dev-fallback section).** Today, a trust-marker mismatch degrades the Python
  relay to its inline `authorize_stream` fallback silently — streams keep working, one WARNING is
  logged. This phase's dev fallback originally reused the existing `/_dispatcharr/authorize` path,
  which nginx's `internal;` location shadows in every nginx-fronted deployment — meaning the same
  mismatch would have made the Go relay's own fallback 404 and every live tune fail outright,
  trading a silent degrade for a total outage. Closed by giving the fallback its own
  `/_dispatcharr/authorize-internal` path, gated by `IsInternalRelay` instead of nginx's `internal;`
  shield. Recorded here because it is exactly the class of regression this phase's parity discipline
  (D5) exists to prevent, and it was found only by re-deriving the nginx location-matching rules
  against the actual config rather than assuming the new route "just works" the way the old one did.
- **2a can stall the phase, and it is the least rewarding stage to work on** — writing tests against
  code nobody is about to delete feels like overhead when the destination is a rewrite. Mitigated
  structurally, not by discipline: 2a's value survives abandoning Go entirely (§ Goal), so the risk is
  schedule, not waste.
- **`log_parsers.py` is the highest-risk single port in the whole phase.** 235 statements at 69%
  coverage today, deciding whether a stream is buffering from a cumulative `speed=` average with a
  ~55-second arming delay — subtle floating-point accumulation logic that is slow to observe when
  wrong (a bug here shows up as "failover feels sluggish sometimes," not a crash or a clear test
  failure). Given its own parity-matrix row and its own real-ffmpeg test in 2a and 2c-4, not folded
  into a larger PR where a quiet regression could hide.
- **Memory profile changes shape, not just size.** Sixty seconds of every live channel's video
  becomes resident in one process instead of living in Redis with its own eviction. The failure mode
  Redis used to absorb — a spike in concurrent channels or bitrate pushing memory pressure — becomes
  an OOM kill of the relay process itself, taking every channel down at once rather than degrading
  one channel's buffer depth. § Stage 2c's sizing calculation is a starting point, not a solved
  problem; the implementing PR must revisit it against real measured channel counts before this
  phase's first production deployment.
- **`fmp4/manager.py` and `output/profile/manager.py`, both at 17% coverage today, are the
  least-understood code in the phase** and are deliberately ported last (2c-6, 2c-7) so the harness
  and the porting patterns are proven on better-understood code first.
- **Rollback is the container image, not a channel.** D3's hard-cutover trade means a Go relay defect
  found in production reverts the whole live path for every viewer simultaneously, not one channel —
  stated once here as the single largest operational risk this phase accepts, and accepted because
  the alternative (a canary) was assessed in D3 as carrying comparable-or-worse risk of its own via
  dual-implementation ownership-protocol conflicts.
- **Upstream divergence for the live data path becomes permanent.** Once `apps/proxy/live_proxy/` is
  deleted (`migration/phase2d-delete-live-proxy`), this fork can no longer take an upstream
  `live_proxy` change for the live surface — only re-implement it in Go by hand. VOD and catch-up,
  staying Python, keep taking upstream changes normally; this is a live-path-only cost.
- **Twenty-four PRs across four stages** (7 in 2a, 3 in 2b, 9 in 2c, 5 in 2d) **is a long queue under
  the Main ruleset's strict up-to-date policy**, the same shape Phase 0 and Phase 1 both accepted for
  the same reason: fewer, larger PRs were rejected because each stage's own gate (parity matrix
  completeness, coverage floor, Go coverage floor) needs to be independently checkable, and a PR
  combining stages would blur which gate failed. **2b's own honesty caveat compounds this risk
  slightly**: if the `channel_status.py:74`/`:92` fallback reads turn out not to be provably
  unreachable (§ Stage 2b), 2b's PR count could grow by one to actually close them, rather than
  leaving them as a documented, deliberate carry-forward — a decision for whoever executes 2b-3 to
  make explicitly, not something this spec can settle without the tree in front of it.

## Non-goals — deliberately out of scope, each a temptation being resisted

- **VOD, catch-up and `timeshift.php`.** Stay Python, D1. Their Redis coupling is what remains of
  Phase 3 after this phase absorbs the live half.
- **HLS output.** `_OUTPUT_FORMAT_MANAGERS` still registers only `fmp4`; `apps/proxy/hls_proxy/` stays
  dead and unrouted — Phase 4, per `CLAUDE.md`'s own phase ladder.
- **New failover logic, quality measurement, adaptive bitrate.** D5's strict parity is the opposite of
  an invitation to improve failover while porting it; `CLAUDE.md`'s "no continuity-counter, PCR-gap or
  discontinuity checks" stays true of the Go relay too.
- **Prometheus metrics.** D6 — nothing scrapes them today, and the metrics dashboard is engineering
  data, not a runtime target.
- **Multi-relay, HA, a fenced lease.** One relay per host; D2 deletes the lease rather than fencing it
  because there is no second writer to fence against in this design. If HA returns, it returns once,
  fenced, in a later phase that has to design for a second writer from the start — not a retrofit onto
  this one.
- **Signed stream URLs.** ADR 0005 settled this for Phase 1 and nothing in this phase reopens it —
  cached playlists still make a short-lived signed URL unworkable, regardless of implementation
  language.
- **Role-scoped urlconfs.** Phase 1's D1 keeps one urlconf everywhere on the Python side; this phase
  doesn't touch Django's urlconf shape at all except the one new route § The contract names
  (`POST /_dispatcharr/authorize-internal`, the dev fallback) and the URL-preserving relocation § Stage 2d's
  deletion order performs.
- **HDHomeRun authorization.** `apps/hdhr/api_views.py`'s separate, still-unfixed defect (`CLAUDE.md`
  § Known defects) — untouched, a different surface than anything this phase moves.
- **Remote-access hardening** (wildcard hosts, CORS, CSRF, TLS, XC password hashing at rest) — same
  "still carried" rows Phase 1's own Requirements table named, unchanged here.
- **Channel preemption revival.** Deleted in Phase 1, not resurrected.
- **The published Postgres port on `5436`.** Repeated for emphasis, as Phase 1's spec repeated it:
  untouched by this phase's Dockerfile or compose changes.
