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
   behaviour with its source line and its pinning test, guarded so an unpinned row fails CI; a real-
   subprocess test harness the backend suite has never had; and coverage on the live path raised from
   a measured 44% to a gated ≥80% combined with the nine Phase 1 boundary modules already at 92%.
2. **2b — complete the contract (Python).** The dozen ORM reads Phase 1 knowingly left in the relay
   (its own § "ORM reads that remain" table) close: into the next-source payload, a new control-plane
   field, or deleted as dead. Ends with a guard test asserting zero ORM reads survive in the live
   relay.
3. **2c — build the Go relay.** A second process, port 5658, speaking the exact same
   `/proxy/relay/…` and `/api/relay/…` contract PR 6/7 already shipped, holding the ring buffer in
   memory, no third-party dependencies.
4. **2d — cut over and delete.** nginx's live locations move from `uwsgi_pass` to `proxy_pass`;
   `apps/proxy/live_proxy/` and its ~564 tests are deleted in one PR after three PRs of preparation.

**2a and 2b are pure Python, and their value survives abandoning Go entirely.** A parity matrix with
100% of its rows pinned, a subprocess-capable test harness, and 80% coverage on the highest-risk,
lowest-coverage code in the repo are worth having whether or not a Go relay ever ships — `CLAUDE.md`
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
  Python dicts agree. `CLAUDE.md`'s "a string in one endpoint, a float in the other" is stale; Phase 1
  PR 7's own ruling 4 says as much ("normalising `ffmpeg_speed` to a float"). **`owner`'s fallback to
  the literal string `'unknown'` is not stale and is asymmetric in a way not previously written down**:
  `get_basic_channel_info` (`channel_status.py:45`) still does
  `metadata.get(ChannelMetadataField.OWNER, 'unknown')`; `get_detailed_channel_info`
  (`channel_status.py:460`) does the same read with **no default**, i.e. `None`. `CLAUDE.md`'s "owner
  falls back to the literal string `'unknown'`, never null" is true of `GET /proxy/relay/channels`
  (basic) and false of `GET /proxy/relay/channels/<id>` (detail) — a real parity-matrix row, and a
  live trap for anyone testing the string against only one of the two endpoints.
- **A real ORM `User` read happens inside the relay process on the ordinary, nginx-authorized path —
  not only as ADR 0005's stated fallback.** `apps/proxy/authorize_views.py`'s `result_from_headers`
  (`:112-141`) runs `User.objects.filter(id=int(user_id)).first()` whenever `X-Relay-User` is a
  digit string. `resolve_authorization` (`apps/proxy/authorize.py:144-155`, called from
  `apps/proxy/live_proxy/views.py:164` inside `stream_ts`) calls `result_from_headers` on **every**
  trusted (i.e. every normal, nginx-fronted) tune, not only when the trust marker is absent. Because
  `stream_ts` runs in the relay process after Phase 1's routing, this `User.objects.filter(...)` runs
  **inside the relay**, on every tune, today — not as a rare inline-fallback path. ADR 0005's
  Consequences bullet ("It still reads both rows by primary key... the `User` row the relay loads
  from `X-Relay-User`") is correct about the read existing but locates it loosely; this spec locates
  it exactly, because 2b has to close it and 2c's Go relay cannot open a socket to Postgres to do the
  same thing.
- **`next_source.py` is 779 lines, not 124.** The brief, quoting the Phase 1 spec's own caveat about
  itself being stale, asked this spec to recheck the file's size after PR 6 "shrank that file from 661
  to 124 statements" (a claim about `url_utils.py`, not `next_source.py` — the two names were
  conflated in transit). `wc -l` on `a948cd8a`: `next_source.py` 779 lines, `url_utils.py` 291 lines.
  `next_source.py` holds the whole moved traversal — `get_stream_object`, `transform_url`,
  `order_alternates_from_current`, `_resolve_live_stream_url`, and the `resolve_source`/
  `release_stream` entry points the six Django-side callers and the two HTTP routes (`next-source`,
  `release`) use. `url_utils.py`'s surviving content is what stayed behind: `get_stream_info_for_switch`,
  `validate_stream_url`, and the one dead site named below.
- **`live_proxy/url_utils.py:614`'s dead `get_connections_left` read is gone, not merely
  unreferenced.** Phase 1's own table flagged it as a one-line cleanup PR 7 "may take or leave."
  `grep -n "get_connections_left" apps/proxy/live_proxy/url_utils.py` returns nothing on `a948cd8a`:
  it was taken. The surviving `M3UAccountProfile` reads to close in 2b are the two Phase 1's table
  already names correctly — `channel_status.py:74` (`Stream`) and `:92` (`M3UAccountProfile`) — plus
  `channel_service.py:324,331,911` (`Channel`/`Stream` name fallbacks), `views.py:152`
  (`OutputProfile.objects.filter(...)` for `build_command()`), `input/manager.py:737`
  (`StreamProfile.objects.get(name='ffmpeg', locked=True)`), and the `User` read above.
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
- **`docker/nginx.conf`'s `uwsgi_buffering off` count is confirmed at exactly ten**, matching
  `CLAUDE.md`: nine top-level relay-bound locations (`streaming/timeshift.php`,
  `proxy/ts/stream/`, `proxy/vod/`, `proxy/catchup/`, `live/`, `movie/`, `series/`, `timeshift/`, the
  XC 3-segment regex) plus the one nested inside `^~ /api/` for `^/api/channels/recordings/\d+/
  file/$`. `grep -c "uwsgi_buffering off" docker/nginx.conf` → 10 on `a948cd8a`. The greybox spec
  (`e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`, 386 lines) parses `nginx -T`'s
  resolved output into top-level `location` blocks by brace depth and asserts this set — read in
  full; § Stage 2d — Cutover describes exactly what its rewrite must do.

## Verified facts this design rests on

**Coverage, measured on `a948cd8a`, 857 tests green** (`coverage run --source=apps/proxy` over
`apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests`):

| Scope | Statements | Missed | Coverage |
|---|---|---|---|
| `apps/proxy/live_proxy/**` | 6,830 | 3,818 | **44%** |
| The nine Phase 1 boundary modules (`authorize.py` 94%, `control_plane.py` 97%, `internal_auth.py` 100%, `internal_base_url.py` 100%, `next_source.py` 78%, `permissions.py` 100%, `relay_client.py` 97%, `relay_serializers.py` 100%, `relay_views.py` 100%) | 1,040 | 87 | **92%** |
| Combined denominator | 7,870 | 3,905 | **50.4%** |

The combined figure is flattered by the boundary modules; **the gate's real target is `live_proxy`
itself, which has to climb from 44% to ~77%** (about +2,250 statements) for the combined ≥80% to
hold. `vod_proxy` and the dead `hls_proxy` are outside the denominator by design — D1 below excludes
them from scope entirely, so they should not count toward the gate that unlocks Go work on the live
path. Worst files, missed-statement count first: `server.py` 1490/937 (37%), `input/manager.py`
1248/771 (38%), `services/channel_service.py` 500/262 (48%), `output/ts/generator.py` 377/241 (36%),
`output/fmp4/manager.py` 304/253 (17%), `output/profile/manager.py` 223/185 (17%),
`output/fmp4/generator.py` 219/195 (11%), `input/buffer.py` 248/166 (33%), `input/http_streamer.py`
101/101 (**0%**), `output/fmp4/buffer.py` 116/102 (12%), `utils.py` 142/102 (28%),
`services/log_parsers.py` 235/73 (69%), `client_manager.py` 262/70 (73%), `views.py` 608/204 (66%),
`channel_status.py` 375/76 (80%). The five largest gaps — `server.py`, `input/manager.py`,
`channel_service.py`, `output/ts/generator.py`, `output/fmp4/manager.py` — total 2,464 missed
statements; closing them approximately **is** the gate.

**Test inventory, three buckets, all measured against `a948cd8a`.**

1. **PORTABLE** — real HTTP through nginx: 31 Playwright spec files (22 `streaming/`, 6
   `streaming-failover/`, 3 `streaming-greybox/`), ~67 `test(` occurrences.
2. **VIEW-LEVEL** — `RequestFactory`/`Client`/`APIClient` against Python view functions: behavioural,
   but never leaves the Python process. 14 files, ~203 test functions.
3. **WHITE-BOX** — imports relay internals directly: 22 files, ~361 test functions.

**564 Python test functions cover the live path, and not one survives a rewrite into another
language.** Subtracting the 3 greybox specs 2d rewrites in place (they assert nginx configuration,
which still exists and still needs asserting, just pointed at a different upstream), roughly **61
tests** — the PORTABLE bucket minus those three — are what stands between this project and an
unverified byte-path rewrite before 2a adds anything. This is the fact that makes 2a's existence
non-optional rather than a nice-to-have, and it leads § Testing below for that reason.

**Reachability, which drives 2a's PR order.** Not every missed statement costs the same to reach.
`channel_service.py` is ~90% reachable by a Django test-client request driving an in-process fake
upstream with real Redis — no subprocess needed, because switch/stop/metadata logic is pure Python
and Redis calls. `output/ts/generator.py` is ~80-85% reachable the same way. `server.py` is
~70-75% reachable — bring-up, the event listener loop and zombie detection are Redis- and
Django-test-client-shaped; only the parts that spawn ffmpeg are not. `input/manager.py` is only
~40-50% reachable without a real subprocess: the transcode connection setup, the stderr reader and
the health/reconnect loops are shaped around a real ffmpeg process's stdout/stderr, and mocking that
shape teaches nothing a Go implementer can reuse. `output/fmp4/manager.py` is only ~20-30% reachable
the same way. Those last two hold roughly **1,024 missed statements between them** — the single
biggest reason 2a is not "write more Django tests" but "build a subprocess-capable harness first, then
write tests against it." `CLAUDE.md` § Testing already records the gap this fills: "No backend unit
test spawns a subprocess."

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

**`docker/uwsgi.relay.ini` (94 lines, read in full).** `socket = 0.0.0.0:$(DISPATCHARR_RELAY_PORT)`,
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
read in full) and `apps/proxy/live_proxy/constants.py` (125 lines, read in full).** Fourteen
`RedisKeys` methods produce the `live:channel:{id}:*` family: `channel_metadata`, `buffer_index`,
`buffer_chunk`/`buffer_chunk_prefix`, `channel_stopping`, `client_stop`, `events_channel`
(`live:events:{id}` pub/sub), `switch_request`, `channel_owner`, `clients`,
`last_client_disconnect`, `connection_attempt`, `last_data`, `switch_status`, `worker_heartbeat`,
`chunk_timestamps`, `transcode_active`, `client_metadata`, five `output_*` methods for the fMP4
buffer family, and `channel_source_cache` (the degraded-fallback candidate cache Phase 1 PR 6
introduced). Two more, `channel_stream(channel_pk)` and `stream_profile(stream_id)`, are explicitly
documented in the module as **Django-owned**: "Written only by `apps/channels/models.py` ...
reached only through `apps/proxy/next_source.py`." Every one of the first group is a candidate for
D2's "becomes memory, not Redis"; the second group was never relay state and stays Django's.

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
  this but is not installed on the repo (`CLAUDE.md` § Build reproducibility). PR 2c-0 brings the ten
  hand-written workflows current before `go-tests.yml` adds a third generation of pins that would
  make the spread worse, not better.

## Decisions

| # | Decision | Why |
|---|---|---|
| **D1** | **Scope: live TS only.** The Go relay serves `/proxy/ts/stream/<id>` and the XC live roots (`live/<user>/<pass>/<id>`, bare `<user>/<pass>/<id>`). The Python relay keeps `/proxy/vod/`, `/proxy/catchup/` and `/streaming/timeshift.php`; `apps/proxy/vod_proxy/` and `apps/timeshift/` are untouched. | § What the code says confirms the XC live roots are already routing-distinguishable from VOD/catch-up with no shared regex to split, so this is a location-table decision, not a routing redesign. It also matches where the coverage and defect weight actually is: `live_proxy` is 44% covered and holds every failover trigger and the ownership lease; `vod_proxy` (35.6%, `CLAUDE.md`) is a separate, simpler shape — stateless, one upstream per session, no ring buffer — that gains nothing from Go's concurrency model and would only enlarge this phase. |
| **D2** | **The ring buffer lives in process memory from day one.** Live video bytes never enter Redis. Ownership becomes `map[uuid]*Channel` behind a `sync.RWMutex`; the lease, the follower path, `_ensure_owner_or_stop`, the 10-second process-local cache and the three fail-open paths (`server.py`'s `_execute_redis_command` swallowing to `None`, `release_ownership`'s non-atomic GET→compare→DELETE, `extend_ownership`'s non-atomic GET→EXPIRE) are **deleted, not ported**. | A Go relay is one process per host by construction (no gevent single-worker precedent to preserve), so there is never a second writer to fence against — the un-fenced lease `CLAUDE.md` records as a real defect (`StreamBuffer.add_chunk()` writes with no ownership check) has no analogue to carry forward. Porting a Redis-backed buffer into Go only to delete it in Phase 3 wastes a release cycle proving a data structure this design already knows it will remove. **Consequence, stated plainly**: Phase 3's live half is absorbed here. Phase 3 shrinks to deleting the Python ring-buffer code (2d does that), rewriting the greybox quarantine (2d does that too), and whatever Redis coupling VOD/catch-up still carry — unrelated to this spec, a smaller Phase 3 than the route page originally sized. |
| **D3** | **Hard cutover, no coexistence.** No per-channel canary, no second relay-name map entry live at once. One release flips the live nginx locations from `relay_py` to `relay_go`; `apps/proxy/live_proxy/` is deleted inside this phase (2d); rollback is a container image rollback, not a per-channel flag. | ADR 0005 built the `$relay_name` header and the nginx `map` explicitly so "Phase 2's canary... becomes a second map entry... not a code change on either side" — a real, ready mechanism this decision declines to use. The reason: a canary needs the *old* relay's ownership lease and ring buffer to coexist correctly with channels the *new* relay owns, on the same Redis DB, for the whole canary window — exactly the fenceless-lease and split-brain-key hazards `CLAUDE.md` already documents as live defects, now doubled by having two independent implementations of the owner-election protocol running against the same keys. D2's "buffer in memory, not Redis" makes a byte-level handoff between the two relays for one in-flight channel impossible to do safely in the time this phase has, and a channel-level canary (some channels on Python, some on Go, split by the map) still shares the provider-slot counter and the failover event stream with whichever relay is *not* serving a given channel. Cost, stated honestly: a production defect in the Go relay reverts the whole live path for every viewer, not one channel — the trade this phase makes deliberately, once, rather than carrying dual-implementation risk through a canary window of unknown length. |
| **D4** | **No live client keys need to exist in Redis at all**, because `GET /proxy/relay/channels?clients=all` already serves that need and the Go relay must implement it anyway. | `apps/proxy/utils.py:256-283`'s `_live_connections(user_id)` — the live half of `get_user_active_connections`, called by `authorize_stream` on every tune via `check_user_stream_limits` — already calls `relay_client.list_channels(all_clients=True, timeout=relay_client.TUNE_TIMEOUT)`, i.e. it already asks the relay over HTTP rather than scanning `live:channel:*:clients:*` directly; that scan was removed in Phase 1 PR 7. Verified by reading the function in full: it fails open (a relay that cannot answer contributes nothing, logged once) and is documented as deliberately so — "the relay is the only process serving live clients, so a relay that is not answering has none." The Go relay reproducing this route byte-for-byte (§ The contract) closes the loop with zero new Redis state. |
| **D5** | **Strict behavioural parity, defects included** — the three failover triggers and thresholds, threshold snapshotting at channel start, the monotonic never-reset chunk index, the ~5s-behind-live join, 188-byte TS realignment, the cumulative `speed=` average's ~55s arming delay, `MAX_STREAM_SWITCHES` not bounding buffering-triggered switches, and fMP4's `_is_timeout()` lacking the TS generator's `url_switching` exemption. These get filed as issues against the parity matrix, not fixed in transit. Two named exceptions: **(1) process-lifecycle hygiene** — Go spawns ffmpeg with `SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}`, closing the orphaned-ffmpeg-holds-a-provider-slot defect (`CLAUDE.md` § Operationally: "`os.posix_spawn` runs with no `setsid`/`PDEATHSIG`"), because no test asserts the current behaviour and it is process hygiene, not streaming behaviour a client can observe. **(2) The dev authorize path** — with no nginx, there is no `auth_request`; a Go relay cannot call `apps/proxy/authorize.py`'s `authorize_stream` in-process (it is Python). When the trust marker is absent, the Go relay makes an HTTP call to a new Django endpoint, `POST /_dispatcharr/authorize` — the same view nginx's subrequest hits — with the original request URI, so it is still exactly one decision function, reached over HTTP instead of a Python import. | A rewrite that also changed behaviour would make every regression ambiguous between "the port is wrong" and "the fix changed something." Parity is what makes the ~61 portable tests (§ Verified facts) a meaningful safety net rather than a moving target. The two exceptions are chosen narrowly: neither is externally observable streaming behaviour a Playwright spec could assert differently, and the second is required by D2/D3's own shape (dev has no nginx, and Go has no Django import path), not a discretionary fix folded in for convenience. |
| **D6** | **Ships drain-on-SIGTERM, `/healthz`, `/readyz`, wired to supervisord `stopwaitsecs` and a Docker `HEALTHCHECK`. No Prometheus metrics.** | `CLAUDE.md` § Operationally records the current relay's shutdown as bounded-not-graceful (`die-on-term`, no drain) and the deployment as having no readiness probe at all — both real gaps this phase can close in a language where a drain loop and a health endpoint are a few dozen lines, not a gevent-compatibility exercise. Metrics are declined because nothing scrapes them today and the metrics dashboard (`metrics/curated/`) is engineering data assembled from git/CI/issue history, not a runtime target — adding a `/metrics` endpoint with no consumer is exactly the scope-widening `CLAUDE.md` warns against. |
| **D7** | **Two coverage gates, not one, and the second blocks the first line of Go code.** Gate 1: the parity matrix is 100% pinned, enforced by a guard test. Gate 2: ≥80% statement coverage on `apps/proxy/live_proxy/**` plus the nine Phase 1 boundary modules, measured by `scripts/coverage_live_path.sh` and enforced as a ratchet floor file, in `lint.yml`'s idiom for zizmor's zero-findings rule. **No PR in stage 2c may merge until both gates are green**, recorded as CI-enforced in 2c's own PRs, not left to review discipline. | The 61 portable tests alone are not enough to catch a subtle regression in, say, the buffering detector's cumulative-average arithmetic — `log_parsers.py` is 69% covered and 235 statements of exactly the logic a byte-for-byte port has to get right. Gating Go's *start* on coverage, not just its *finish*, is what stops "write the matrix, then start porting while coverage catches up" — a sequencing this phase's own §2a reachability numbers show is expensive to do after the fact (the two hardest files to cover, `input/manager.py` and `fmp4/manager.py`, are exactly the two a Go implementer needs most while porting). |

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
   ┌───►│  now also calls POST /_dispatcharr/authorize   │
   │    │  itself when the Go relay's dev fallback needs  │
   │    │  it (D5)                                         │
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
"internal-principal")`, `X-Dispatcharr-Internal-Request: v1.<unix_ts>.HMAC(SECRET_KEY,
"internal-request\n"+METHOD+"\n"+PATH+"\n"+str(ts)+"\n"+sha256(body).hexdigest())` (exact byte
layout: `internal_auth.py`'s `internal_request_token`, newline-joined fields, hex digest of a
SHA-256 over the fields, itself HMAC'd — the Go implementation must replicate the join order
exactly or every call 403s). `allow_redirects=False` semantics must be reproduced too: a 3xx is
treated as an outage, never followed, because following would re-send the signed internal headers
to whatever a stray `return 301` names.

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

- **`owner`**: `'unknown'` string default on the list endpoint (`RelayChannelSerializer`), `null`
  default on the detail endpoint (`RelayChannelDetailSerializer`) — asymmetric, verified above, and
  not something to "fix while we're in there."
- **`ffmpeg_speed`**: a float on the wire on both endpoints (already true in Python; § What the code
  says). **Do not** reintroduce the historical string/float split reading `CLAUDE.md`'s stale
  wording literally.
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

New route, Django side: `POST /_dispatcharr/authorize` (distinct from the existing `GET/HEAD`
`= /_dispatcharr/authorize` nginx-facing view, which `apps/proxy/authorize_views.py`'s
`authorize_view` already serves) — same `authorize_stream()` call, reached over HTTP because a Go
process cannot import Python. Used only when `request_is_relay_trusted()`'s Go equivalent finds no
valid `X-Dispatcharr-Authorized` marker, i.e. only in `dev`/`debug` or any nginx-less deployment
shape — on every ordinary nginx-fronted tune this route is never called, matching the Python relay's
own inline-fallback frequency today.

## Stage 2a — pin the behaviour (Python, the gate)

### Gate 1 — the parity matrix, 100% pinned

New `docs/relay-parity-matrix.md`: one row per externally-observable live-path behaviour, each
naming the behaviour, the Python source it was derived from (`file:line`), and the test that pins
it. Rows are derived by reading the source, not by cataloguing tests that happen to exist already —
several of the rows below have no current test and are recorded as gaps 2a must close, not rows
already checked off. Enumerated here; the PR that lands the matrix fills in the remaining rows this
spec's authors did not have time to individually trace, each still required to carry a `file:line`
and a test reference before the guard test (below) passes.

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
| 12 | fMP4 `_is_timeout()` lacks TS generator's `url_switching` exemption; fMP4 viewers can drop at 40s during a slow failover | `output/fmp4/generator.py` vs `output/ts/generator.py` | New — filed as issue, reproduced |
| 13 | Client registration and the ghost-client cases | `client_manager.py`, `ClientManager.remove_ghost_clients` | Partial existing (`test_ts_proxy_ghost_clients`) — extend |
| 14 | Status payload exact field set/types incl. `owner` string-vs-null split, `ffmpeg_speed` float on both endpoints | `channel_status.py` | New, unit-level (view-level bucket is fine here) |
| 15-22 | Every row of the Phase 1 authorize matrix (`docs/superpowers/specs/2026-09-04-…md`, § "The authorize matrix", 7 principal rows × 6 columns) | `apps/proxy/authorize.py` | Existing (`streaming`, `@contract`, PR 5) — matrix cites them, does not re-test |

Behaviour **not** observable from outside is marked white-box-only and honestly recorded as
behaviour the Go relay is **not** held to — e.g. the exact greenlet/thread topology inside
`server.py`, or `_execute_redis_command`'s specific exception-swallowing shape, both deleted outright
by D2 rather than reproduced.

A guard test under `e2e/tests/guards/` (new file, `parity-matrix.spec.ts`, following the same
"assertion, not convention" pattern `allowlist.ts`/`capabilities.spec.ts` already use for the Redis
importer allowlist) parses `docs/relay-parity-matrix.md`'s table and fails, naming the offending row,
if any row lacks both a `file:line` citation and a test reference. This matrix is the load-bearing
artifact of the whole phase: 2a's own checklist, 2c's implementation spec (each Go PR closes a named
set of rows), and 2d's cutover checklist (every row must show a passing Go-side equivalent before the
nginx flip). PR 2c-9 replaces the matrix's Python test-reference column with a Go one, once every row
has one.

### Gate 2 — 80% statement coverage

New `scripts/coverage_live_path.sh`, run by a new CI job (folded into `backend-tests.yml` rather than
a new workflow, since it needs the same Postgres/Redis fixtures every other backend job already has):
runs `coverage run --source=apps/proxy/live_proxy,apps/proxy/authorize,apps/proxy/authorize_views,
apps/proxy/control_plane,apps/proxy/next_source,apps/proxy/relay_client,apps/proxy/relay_serializers,
apps/proxy/relay_views,apps/proxy/permissions,apps/proxy/internal_auth,apps/proxy/internal_base_url`
over the same three labels used to measure today's 44%/50.4% baseline, and writes a floor file,
`scripts/coverage_live_path.floor` — a ratchet in `lint.yml`'s zizmor idiom: CI fails if coverage
drops below the floor, and the floor only ever moves up, committed in the same PR that earns the
increase. `vod_proxy` and `hls_proxy` are outside `--source`, matching D1's scope line. **No PR in
stage 2c may merge until this job reports ≥80% and Gate 1's guard test is green** — stated as a CI
precondition on 2c's first PR, not review discretion.

### The subprocess harness — 2a's named deliverable

`channel_service.py` (~90% reachable), `output/ts/generator.py` (~80-85%) and most of `server.py`
(~70-75%) close mainly with Django-test-client requests against real Redis and an in-process fake
upstream — no new capability needed. `input/manager.py` (~40-50% reachable) and
`output/fmp4/manager.py` (~20-30%) do not: their uncovered code is shaped around a real subprocess's
stdout/stderr, and `CLAUDE.md` § Testing records the backend suite as never having had this
capability at all ("No backend unit test spawns a subprocess"). **2a's PR 3 builds a harness that
spawns real subprocesses and serves real TS bytes from an in-process fake upstream** — a small,
canned-content Python HTTP server (`socketserver`/`http.server`, no external dependency), *not* a
reuse of the `e2e-upstream` Docker image: the backend test runner is itself a container, and nested
Docker is a poor trade for a unit test that should run in milliseconds, not spin up a sibling
container per test. `e2e-upstream`'s twelve-fault vocabulary (`e2e-upstream/src/faults.ts`) stays
serving e2e unchanged; the harness borrows its *vocabulary* (dead-air, slow-start, mid-stream
truncation, malformed TS, …) as Python fixtures, not its Docker image. **This harness is not
throwaway**: the Go relay needs an equivalent in its own suite (2c's own fault-injection fixtures),
and having already named the fault vocabulary in Python fixtures gives the Go author a spec to copy
rather than invent from `input/manager.py`'s prose alone.

**Composition rule for every 2a test, stated because it is the difference between a test that helps
2c and one that only moves a number:** write tests that drive the relay through its **HTTP surface**
against **real dependencies** — the fake upstream, real Redis, real ffmpeg — never against mocks of
`server.py`'s or `input/manager.py`'s internals. Such tests run under `coverage` (so they count toward
Gate 2) and, because their assertions are about observable behaviour (bytes received, a status field's
value, a failover firing), they port to Go tests row-for-row against the parity matrix. A test that
mocks `StreamManager` and asserts an internal call count inflates coverage and teaches the Go
implementer nothing about what the relay is actually supposed to do.

## Stage 2b — complete the contract (Python)

Phase 1 took the relay to zero ORM *writes*. It did not reach zero *reads* — its own § "ORM reads
that remain in the relay after PR 7" table names twelve surviving sites and states plainly that "a Go
relay cannot execute any row in this table." Re-derived here against `a948cd8a`, not copied from
Phase 1's table (written forward-looking at PR 4, now three PRs stale per the brief's own caveat):

| Site | Model | 2b's fix |
|---|---|---|
| `input/manager.py:737`, `StreamProfile.objects.get(name='ffmpeg', locked=True)` on the force-ffmpeg reconnect path | `StreamProfile` | Fold the locked ffmpeg profile's `{id, command, args}` into the `next-source` response, alongside the existing `stream_profile` payload — `POST /api/relay/channels/<id>/next-source` already carries a `stream_profile` object (§ The contract's Python precedent, `control_plane.py`'s `next_source()`), so this is a second key on an existing response, not a new route. |
| `services/channel_service.py:324,331,911`, `Channel`/`Stream` name fallbacks used when no name was supplied at init or after a switch | `Channel`, `Stream` | Both names are already resolved during `next-source`/`advance` — Django has them at hand when it builds the response. Add `channel_name`/`stream_name` as non-optional fields on both response bodies so the relay never has to guess. |
| `channel_status.py:74`, `Stream` name fallback when Redis has no stream name | `Stream` | After 2b's channel_name/stream_name addition above, the metadata hash is written with a name at channel-start time and never needs a fallback read at status time — delete the read, not move it. |
| `channel_status.py:92`, `M3UAccountProfile` name fallback | `M3UAccountProfile` | Same shape: carry `m3u_profile_name` in the metadata hash from channel-start, written once from the `next-source` response's own profile data instead of read again at status time. |
| `views.py:152`, `OutputProfile.objects.filter(id=..., is_active=True).first()` so `build_command()` can be called | `OutputProfile` | Phase 1's Amendment S3 left this in deliberately — "the header contract cannot carry a built ffmpeg command." A control-plane **response body** can, unlike a header: 2b adds the built command (and its args list) as a field on a new lightweight `GET /api/relay/output-profiles/<id>/command` route, or — preferred, one fewer round trip — folds it into `next-source`'s response when `X-Relay-Output` names a profile, since next-source already runs once per tune and already has the ORM open. This spec's PR-level bullet (2b-2) decides between the two shapes; either closes the read. |
| `apps/proxy/authorize_views.py:112-141`'s `User.objects.filter(id=int(user_id)).first()` inside `result_from_headers`, run on **every** trusted tune inside the relay process (§ What the code says) | `User` | The relay never needs the `User` row itself — only `user.custom_properties.get('output_format')` (`_resolve_output_format`, `live_proxy/views.py:112-131`) and the value `add_client` stores for display. Carry `output_format` as a resolved string on the trusted response — a sixth `X-Relay-*` header, `X-Relay-Output-Format`, set by `authorize_view` (which already resolved the `User` row to answer `output_profile_id`) — and store the raw `user_id` string for display/registration without ever re-querying it. Closes the last ORM read on the ordinary tune path. |

**Also folded into the contract, not a read but the trap that motivates finishing this table:**
`proxy_settings` (`apps/proxy/config.py`'s `BaseConfig._proxy_settings_cache`, 10-second
process-local TTL) is why a buffering-threshold change today takes over 10 seconds to reach the
owning worker, on top of `StreamManager.__init__`'s own snapshot (`CLAUDE.md` § Known defects: "a
threshold change needs >10s to reach the owning worker and must land before the channel starts"). 2b
moves `proxy_settings` onto the `next-source` response (channel-start-time values only, matching D5's
"thresholds snapshotted at channel start" parity row) so the Go relay never reads `CoreSettings`
directly and the 10-second staleness window collapses to zero for every value that matters at
channel-start.

**2b ends with a guard test, `apps/proxy/live_proxy/tests/test_zero_orm_reads.py`, asserting**
`grep -rn "\.objects\." apps/proxy/live_proxy/ | grep -v tests` **returns nothing** — the same grep
shape Phase 1's own Done criteria already use for its Redis-key greps, applied here to the ORM. Any
site the table above missed fails this test by name, the same way the parity guard fails naming an
unpinned row.

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
driver.* This falls out of 2b entirely — once the contract carries everything 2b's table names, the
Go relay has no ORM-shaped question left to ask, so there is nothing to import a driver for. *The Go
binary links no Redis client.* Walked key-family by key-family against `apps/proxy/live_proxy/
redis_keys.py` (§ Verified facts lists all fourteen `live:channel:{id}:*` methods plus the two output
ones): the ring buffer and its index/timestamp keys become D2's in-memory structure; `client_stop`,
`clients`, `client_metadata` become the control API's in-memory client registry, served over
`/proxy/relay/…` exactly as today (D4); `channel_owner`/the ownership lease is deleted outright (D2 —
there is nothing to own when there is one process); `switch_request`/`switch_status` become an
in-process channel (Go `chan`) between the HTTP handler and the channel's own goroutine; `events_channel`
(`live:events:{id}` pub/sub) was follower-to-owner coordination for a multi-worker Python relay and
has no purpose once there is one owner per channel by construction — deleted; `channel_source_cache`
(the degraded-fallback candidate list) becomes an in-memory field on the channel struct;
`proxy_settings` arrives over the contract (2b). **If any family is found, during implementation, not
to fit this walk cleanly, the implementing PR says so honestly rather than asserting the invariant
met** — this spec states the walk as reasoning, not as a guarantee that survives contact with code
not yet written.

**It serves:** `GET /proxy/ts/stream/<id>`, the XC live roots, all five `/proxy/relay/…` control
routes (§ The contract, byte-identical JSON), `/healthz`, `/readyz` (D6). **It calls:** `next-source`,
`release`, `events` (§ The contract, exact timeouts and both HMAC headers), with the degraded
fallback to the channel-start-cached candidate list on an unreachable control plane (D5's parity
list — "the degraded next-source fallback is unenforced by design," carried forward unchanged from
Phase 1's own § Risks).

### The nine PRs

| PR | Branch | What it does | Gate | Depends on |
|---|---|---|---|---|
| 2c-0 | `migration/phase2c-workflow-drift` | Bring the ten hand-written workflows' action pins current (§ Verified facts' drift finding) before `go-tests.yml` adds a third generation. Docs/CI only, no Go code. | `Backend result`, `Frontend result`, `E2E result`, `Lifecycle result` green (nothing else changes) | Gate 1 + Gate 2 green (2a/2b merged) |
| 2c-1 | `migration/phase2c-skeleton` | `relay/` skeleton: module init, `main.go`, `httpapi`/`control`/`channel`/`buffer`/`ffmpeg` package stubs, `docker/supervisord.d/relay-go.conf`, the Dockerfile builder stage, `go-tests.yml` (build + lint + `go vet`, no coverage gate yet — nothing to cover), `/healthz`/`/readyz` returning static 200s, a dev-only route flag so this PR is inert in every non-dev deployment. | `go build ./...`, `golangci-lint run`, `go vet ./...` all green; zizmor clean on `go-tests.yml` from its first commit | 2c-0 |
| 2c-2 | `migration/phase2c-vertical-slice` | The Proxy stream-profile architecture only (no ffmpeg spawn yet): one client, in-memory ring buffer, MPEG-TS passthrough for a single upstream. Proves the buffer/fan-out shape end to end before ffmpeg complexity is added. | New Go tests pass with `-race`; parity matrix rows 7, 9 (chunk monotonicity, 188-byte realignment) get a Go column | 2c-1 |
| 2c-3 | `migration/phase2c-fanout` | Multi-client fan-out, join-5s-behind, the client registry, `?clients=all` on `GET /proxy/relay/channels` | Rows 8, 10, 13 get a Go column | 2c-2 |
| 2c-4 | `migration/phase2c-ffmpeg` | ffmpeg spawn via `os/exec` + `syscall.SysProcAttr{Setpgid, Pdeathsig}` (D5 exception 1), the `log_parsers.py` port | Row 4 (the `speed=` arming delay) gets a Go column with its own real-ffmpeg test, mirroring 2a's harness | 2c-3 |
| 2c-5 | `migration/phase2c-failover` | The three failover triggers, control-plane client (`next-source`/`release`/`events`, both HMAC headers, the exact timeout table), the degraded fallback to the cached candidate list | Rows 1, 2, 3, 5, 6 get a Go column | 2c-4 |
| 2c-6 | `migration/phase2c-fmp4` | fMP4 output format, including row 12's known timeout gap, reproduced not fixed | Row 12 gets a Go column | 2c-5 |
| 2c-7 | `migration/phase2c-output-profile` | Output Profile shared transcode per `(channel, profile)` | Row 11 gets a Go column | 2c-6 |
| 2c-8 | `migration/phase2c-control-drain` | Remaining control routes (single-channel `GET`/`DELETE`, `advance`), SIGTERM drain (D6), the dev-only `POST /_dispatcharr/authorize` fallback (D5 exception 2) | Every remaining un-Go'd matrix row gets a column | 2c-7 |
| 2c-9 | `migration/phase2c-go-coverage-gate` | `go test ./... -race -cover` wired into `go-tests.yml`'s own ratchet floor, raised to ≥80%; parity matrix's Python test-reference column gains its Go counterpart on every row | `Go result` aggregate green (§ Verified facts' CI shape) | 2c-8, matrix 100% Go-columned |

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

**Per-location change, at cutover, for exactly the three D1-scoped locations** (`location ^~
/proxy/ts/stream/`, `location ^~ /live/`, `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`):

```nginx
# before (uwsgi_pass, Python relay):
uwsgi_buffering off;
uwsgi_pass $relay_upstream;

# after (proxy_pass, Go relay):
proxy_buffering off;
proxy_request_buffering off;
proxy_http_version 1.1;
proxy_pass http://$relay_upstream;
```

The five `uwsgi_param HTTP_X_RELAY_*`/marker lines (`X-Dispatcharr-Authorized`,
`X-Relay-Channel`, `X-Relay-Output`, `X-Relay-Client`, `X-Relay-User`, plus 2b's new
`X-Relay-Output-Format`) become `proxy_set_header X-Relay-* $relay_*;` — the client-header-override
guarantee (Phase 1 D11's "nginx overrides what the client sent") survives cutover by a different
nginx mechanism (`proxy_set_header` unconditionally sets the outgoing header, same as the `HTTP_`-
prefixed `uwsgi_param` rule did) but the **mechanism changed**, so the E2E test that sends a forged
marker and a forged `X-Relay-Channel` for a hidden channel (Phase 1 PR 5's `@contract` test) must be
re-pointed at the new location and re-verified to still 403, not assumed to carry over because the
outcome used to be the same.

**`e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` (386 lines) rewrite, precisely.** The
spec parses `nginx -T`'s resolved output into top-level `location` blocks by brace depth and asserts
every one of the ten `uwsgi_buffering off` occurrences (§ Verified facts — nine top-level plus the
one nested under `^~ /api/`). After cutover, three of those ten locations no longer carry
`uwsgi_buffering off` at all — they carry `proxy_buffering off` instead, under a different directive
name the spec's current assertion does not check for. The rewrite must: (1) split the assertion into
two — an `uwsgi_buffering off` set (now seven top-level plus the one nested, for the surfaces that
stayed on `relay_py`) and a `proxy_buffering off` set (the three that moved); (2) assert
`proxy_request_buffering off` and `proxy_http_version 1.1` on the same three, since those have no
`uwsgi_*` analogue to have been asserting already and a spec that checks `proxy_buffering off` alone
could pass while request buffering or HTTP/1.0 chunked-transfer quirks reintroduce exactly the
spooling class of bug this file exists to catch; (3) keep the brace-depth `parseLocationBlocks`
parser unchanged — it is directive-agnostic already, so only the assertion list changes, not the
parsing mechanism.

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
3. **`migration/phase2d-nginx-flip`** — the `proxy_pass` table above, plus the greybox spec rewrite,
   landed together (the spec must not go green before the flip it is asserting, nor red after). Gate:
   `E2E result` green including the rewritten buffering spec and the re-pointed forged-marker test.
4. **`migration/phase2d-delete-live-proxy`** — delete `apps/proxy/live_proxy/` and its ~564 tests
   wholesale; rewrite the two remaining greybox specs (multi-client sharing, output-profile sharing)
   that imported relay internals directly rather than going through HTTP, since those internals no
   longer exist; update `e2e/COVERAGE.md` and `e2e/tests/guards/allowlist.ts`'s `GREYBOX_REDIS` entry
   (the live half of what it guarded is gone; the VOD/catch-up half stays). Gate: `Backend result`
   green with 15 labels instead of 16 (`apps.proxy.live_proxy.tests` no longer exists to run),
   `E2E result` green.
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
| The live relay performs zero ORM reads. | **Met.** § Stage 2b's table plus its guard test. | 2b PRs |
| No live client keys exist in Redis. | **Met, and already half-true before this phase started** — `_live_connections` already asks the relay over HTTP (D4). | 2c-3 |
| The Go binary links no Postgres driver, no Redis client. | **Met by construction**, walked family-by-family in § Stage 2c; recorded honestly as a walk, not a guarantee, until 2c-9 confirms it against the finished `go.sum` (which should still be empty). | 2c-9 |
| Strict behavioural parity on every externally-observable live-path behaviour, defects included. | **Met**, by the parity matrix reaching 100% Go-columned rows in 2c-9, with the two named D5 exceptions recorded as deliberate, not accidental, divergence. | 2c-9 |
| The ownership lease's un-fenced write path is closed. | **Met, by elimination rather than by fencing.** D2 deletes the lease outright; there is no analogous defect in a single-owner-per-process design. `CLAUDE.md`'s carried defect is retired, not fixed in place. | 2c-2 |
| A drain on shutdown, a readiness probe, a health check. | **Met**, new capability the Python relay never had (D6). | 2c-8 |
| Third-party Go dependencies: none. | **Met**, `go.sum` verified empty at 2c-9. | 2c-1..2c-9 |
| Coverage on the live path: ≥80% before Go starts, transferring to Go at ≥80%. | **Met**, Gate 2 (2a) and the Go ratchet (2c-9). | 2a's ratchet PR, 2c-9 |
| nginx's live-bound locations carry the correct buffering directive for their protocol. | **Met**, and the specific historical trap is named and guarded against explicitly (§ Stage 2d). | 2d PR 3 |

## Testing

- **The parity matrix's guard test** (`e2e/tests/guards/parity-matrix.spec.ts`, 2a) — fails naming any
  row lacking a `file:line` citation or a test reference; the single test whose passing status is this
  phase's own definition of "the behaviour is pinned."
- **The subprocess harness's own tests** (2a PR 3 onward) — real ffmpeg, real fake-upstream HTTP
  server, real Redis; these are what move `input/manager.py` and `output/fmp4/manager.py` off their
  20-50% floor and are the tests 2c's Go implementer reads first.
- **`scripts/coverage_live_path.sh`'s ratchet** (2a, then 2c-9's Go equivalent) — CI-enforced floor,
  not a report.
- **Existing coverage this spec relies on rather than re-proves**: Phase 1's own § Testing list
  (TTFB, SPA-three-segment routing, the modular role split, the authorize matrix, failover-produces-
  events, Django-down/bounded-relay-restart) — none of it changes shape in this phase except the three
  nginx locations 2d's flip touches, and those get their own re-pointed tests rather than an assumed
  carry-over.
- **The forged-marker `@contract` test** (Phase 1 PR 5) — re-pointed at the post-flip location in 2d
  PR 3, verified to still 403 under `proxy_pass`, not assumed.
- **`nginx-stream-buffering.spec.ts`'s rewrite** (2d PR 3) — the two-directive-family assertion
  described in § Stage 2d, verbatim.
- **Go tests, `go test ./... -race -cover`** (2c-1 onward) — `-race` is not optional given the
  concurrency model change from gevent-cooperative to OS-thread-parallel goroutines; a data race the
  Python implementation's single-OS-thread execution model made structurally impossible becomes
  possible for the first time in this phase, and `-race` is the cheapest available check for exactly
  that new failure class.

## Documentation

- `docs/relay-parity-matrix.md` — created in 2a's first PR, updated by every PR in 2a and 2c that
  closes a row.
- `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (this document) — PR 0, this branch,
  docs-only.
- Per-PR `CLAUDE.md` corrections are listed where each PR changes something CLAUDE.md currently
  states as fact; 2d PR 5 is the consolidation pass, not the only place corrections land — a PR that
  changes a fact CLAUDE.md states should correct it in the same PR, per the project's standing
  convention (Phase 1 spec's own per-PR correction bullets, followed here identically).
- `e2e/COVERAGE.md` — new rows for every 2a/2c Playwright addition, updated in the same PR as the
  test per the standing rule (`e2e/README.md`, `CLAUDE.md` § Testing).
- A new ADR for the Go boundary — 2d PR 5, recording D2 (memory not Redis) and D3 (hard cutover, no
  canary despite ADR 0005's mechanism existing) as the two decisions worth a durable record, in
  ADR 0005's own idiom (Context / Decision / Consequences).
- `metrics/curated/` — updated in 2d PR 5 per `docs/agents/metrics.md`'s standing rule: a
  `phase-start` milestone for `phase2` (this spec's own commit) and a `phase-done` milestone added by
  whoever merges the final PR (a merge commit cannot name itself, the same constraint Phase 1's spec
  recorded).

## Done log

Filled in as PRs merge; this spec lands as its own PR 0.

| Item | PR | Merged |
|---|---|---|
| This spec | — | — |

## Risks

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
  deleted (2d PR 4), this fork can no longer take an upstream `live_proxy` change for the live surface
  — only re-implement it in Go by hand. VOD and catch-up, staying Python, keep taking upstream changes
  normally; this is a live-path-only cost.
- **Twenty-four PRs across four stages is a long queue under the Main ruleset's strict up-to-date
  policy**, the same shape Phase 0 and Phase 1 both accepted for the same reason: fewer, larger PRs
  were rejected because each stage's own gate (parity matrix completeness, coverage floor, Go
  coverage floor) needs to be independently checkable, and a PR combining stages would blur which
  gate failed.

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
  doesn't touch Django's urlconf shape at all except the two new routes § The contract and § Stage 2d
  name.
- **HDHomeRun authorization.** `apps/hdhr/api_views.py`'s separate, still-unfixed defect (`CLAUDE.md`
  § Known defects) — untouched, a different surface than anything this phase moves.
- **Remote-access hardening** (wildcard hosts, CORS, CSRF, TLS, XC password hashing at rest) — same
  "still carried" rows Phase 1's own Requirements table named, unchanged here.
- **Channel preemption revival.** Deleted in Phase 1, not resurrected.
- **The published Postgres port on `5436`.** Repeated for emphasis, as Phase 1's spec repeated it:
  untouched by this phase's Dockerfile or compose changes.
