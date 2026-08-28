# G4 — Live Streaming Data Path

**Date:** 2026-08-28
**Status:** Approved, ready for implementation planning
**Wave:** 2 (G1 landed at `a0c99cdd`, G2 at `c188aab6`; G4 branches from `main` at `d22d3378`)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Sibling in flight:** G7 (`2026-08-28-e2e-deployment-lifecycle-design.md`) — **overlapping on six
small surfaces**, not disjoint. Both goals edit `scripts/e2e_up.sh` (G4's D4 publishes a Redis port,
G7's D9 adds `--recreate` — the same `case` block), `e2e/playwright.config.ts` (G4 adds two projects,
G7 adds two), `.github/workflows/e2e-tests.yml`'s matrix, `e2e/COVERAGE.md`, `e2e/README.md` and
`e2e/package.json`'s test scripts. Every collision is additive and small, but whoever lands second
rebases through them — and the workflow edit re-runs the zizmor hook, which blocks on **every**
finding in the file. G3 additionally collides with G4 on `e2e/fixtures/seed.ts` (D3).

## Goal

Prove the live streaming data path end to end: that bytes arrive aligned and contiguous, that
many clients share one upstream, that a stream switch does not disturb a viewer, that all three
failover triggers fire, and that the three Stream Profile architectures behave as three
architectures.

The roadmap calls G4 *"the highest-value goal and the reason the programme exists."* That is
because of what comes next, not what came before: Phase 1 moves the relay out of the Django
workers, and nothing currently observes the relay's behaviour from outside. `live_proxy` is at
38.5% coverage, `log_parsers.py` — which decides a stream is buffering — is at 20.4%, and **no
test in the repository spawns a subprocess**, so ffmpeg lifecycle and stderr parsing run only
against hand-written strings.

## Current state

Four specs live in `e2e/tests/streaming/`. Three of them never touch Dispatcharr:
`stream-client.spec.ts` and `stalled-stream.spec.ts` drive the fake provider directly to prove
the harness's own read semantics, and `upstream-to-control.spec.ts` is a pure unit test of a
string conversion. Exactly one — `upstream-through-proxy.spec.ts` — puts bytes through
`/proxy/ts/stream/<uuid>`, and it asserts only that 50 packets arrive aligned and the provider
saw one connection.

All nine G4 rows in `e2e/COVERAGE.md` are `todo`. Nothing drives `next_stream`/`change_stream`,
multi-client scenarios, Output Profiles, failover, or the Redirect and ffmpeg profiles.

## Verified facts this design rests on

Cited by symbol or filename, never by line number — line numbers in this repo drift, and an
earlier spec in this series shipped four wrong ones.

| Fact | Source | Consequence |
|---|---|---|
| `POST /proxy/ts/change_stream/<id>` switches to an explicit `url` or `stream_id`; `POST /proxy/ts/next_stream/<id>` rotates through `channel.streams` by `channelstream__order`. Both admin-only | `apps/proxy/live_proxy/urls.py`, `views.change_stream`, `views.next_stream` | A test can force a switch deterministically. `change_stream` is preferred — it names the target rather than depending on ordering |
| Both switch endpoints return `owner: bool` and `worker_id`, and distinguish 504 (owner never confirmed) from 502 (owner reported failure) | `apps/proxy/live_proxy/views.py` | A switch test can assert the switch was actually applied, not merely requested |
| `GET /proxy/ts/status/<id>` returns `stream_id`, `stream_name`, `url`, `state`, `owner`, `client_count`, `clients[]`, `buffer_index`, `total_bytes`, `avg_bitrate_kbps`, plus ffmpeg-derived fields for subprocess profiles | `apps/proxy/live_proxy/channel_status.py`, `ChannelStatus.get_detailed_channel_info` | This is the primary assertion surface for every G4 row. Admin-only, so tests use the `api` fixture |
| **There is no WebSocket event for a switch, a failover, or a teardown.** `channel_stats` is the only event `live_proxy` emits, and its payload arrives as a JSON-encoded *string* under `data.stats` | `apps/proxy/live_proxy/client_manager.py`, `views.channel_status`; no other `send_websocket_update` call sites in the package | Every transition is observed by polling `/status` through `waitFor.resource`. `ws.waitForMessage` is the wrong tool here and will hang |
| `GET /proxy/ts/status` with no id broadcasts `channel_stats` as a side effect of being polled | `apps/proxy/live_proxy/views.py`, `channel_status` | Polling the collection endpoint has an observable side effect on other workers' WS listeners. Prefer the per-channel form |
| `StreamProfile.is_proxy()` / `is_redirect()` test `locked and name == "Proxy"/"Redirect"`; everything else falls into the subprocess branch by exclusion | `core/models.py`, `PROXY_PROFILE_NAME`, `REDIRECT_PROFILE_NAME` | The three architectures are selected by name on a locked row. A test finds them by name and never asserts a count |
| Built-in profiles are created by migration: Proxy and Redirect in `core/migrations/0007`, VLC in `0019`; locked flags set by `0006` and `0011` | `core/migrations/` | They exist on every instance. `seed.streamProfile()` creates a *new unlocked* profile, which is a fourth instance of the subprocess architecture, not a built-in |
| `OutputProfileViewSet` is registered as `outputprofiles` | `core/api_urls.py` | `/api/core/outputprofiles/` is the create/list route. Verified this session |
| One transcode process runs per active `(channel, profile)` pair clusterwide. The TS-owning worker starts it; others build a read-only buffer over the same Redis keys | `apps/proxy/live_proxy/output/profile/manager.py`, `OutputProfileManager.start`, `_acquire_owner_lock` | "Ten AC3 clients cost one ffmpeg" is real and lock-based. Proving it requires observing the lock, not the byte stream — hence grey-box |
| The plain MPEG-TS path spawns no output-side subprocess; only `fmp4` invokes `ensure_output_format` | `apps/proxy/live_proxy/views.py`, `stream_ts` | Confirms CLAUDE.md. The Output Profile row is about an *optional* transcode, not the default path |
| `slow-trickle` arms the buffering detector cleanly **only when set before ffmpeg starts** — `speed=` is a cumulative average since process start | `e2e-upstream/README.md`; CLAUDE.md, Architecture | Mid-stream trickle needs ~55s to arm and the ~25s dead-air watchdog wins first. Pre-arming is mandatory. See D8 |
| `slow-trickle` keeps delivering bytes, at a reduced pacing multiplier | `e2e-upstream/README.md`, fault catalogue | A trickle that delivers within every 10s window makes dead air **impossible**, which is what discriminates a buffering failover from a dead-air one. See D8 |
| Five of the eight faults are "new connection only"; `appliedTo: 0` is the correct response for those | `e2e-upstream/README.md` | `not-found`, `auth-failure`, `connection-limit`, `redirect-chain`, `non-ts-bytes` must be armed before the connection they affect. A zero `appliedTo` is not a failure |
| `upstream.toControl(url)` throws on any URL not under the internal origin | `e2e/fixtures/upstream.ts` | A safety property. The Redirect row uses it to validate a `Location` header; nothing may bypass it |
| A client selects an Output Profile with the **`?output_profile=<id>` query parameter**, falling back to the requesting user's `custom_properties['output_profile']` | `apps/proxy/live_proxy/views.py`, `_resolve_output_profile` (reads `request.GET.get('output_profile')`, then the user's `custom_properties`) | Row 11 drives the query parameter, which needs no user record and no per-test user mutation. Verified this session — it was previously the only G4 mechanism not fact-backed |
| `streamClient.open()` accepts `{redirect}` and exposes `status`/`headers` after resolving | `e2e/fixtures/stream-client.ts` | `redirect: 'manual'` is how the Redirect row inspects the 302 without following it |
| There is no `seed.stream()` factory; `upstream-through-proxy.spec.ts` POSTs a custom `Stream` by hand | `e2e/fixtures/seed.ts`, `e2e/tests/streaming/upstream-through-proxy.spec.ts` | Nine rows would each repeat a five-step wiring dance. See D3 |
| `streaming` runs 2 workers with a 300 000 ms timeout and depends on `bootstrap` | `e2e/playwright.config.ts` | Long failover waits fit inside the existing timeout. A deadlocked read would burn the full 300s — bound reads with the `withDeadline()` pattern from `stalled-stream.spec.ts` |
| Playwright projects map 1:1 to CI matrix jobs | `.github/workflows/e2e-tests.yml`, matrix `[pristine, seeded, streaming]` | Sharding means adding projects, not inventing a mechanism. See D1 |
| `scripts/e2e_up.sh` is the single boot path and publishes only `127.0.0.1:9191` | `scripts/e2e_up.sh` | Redis is not reachable from the host today. See D4 |
| The ownership lease is time-bounded, not fenced: `StreamBuffer.add_chunk()` writes with no ownership check and no fencing token, and the lease fails open three ways | CLAUDE.md, Known defects; `apps/proxy/live_proxy/server.py` | Two owners can interleave chunks at alternating monotonic indices with every consistency check passing. See D11 |
| `MAX_STREAM_SWITCHES` does not bound buffering-triggered switches — they originate in the stderr greenlet, bypassing the main loop's counter | CLAUDE.md, Known defects | A candidate known-bug row in the failover shard. See D12 |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Three Playwright projects, one CI job each**: `streaming`, `streaming-failover`, `streaming-greybox` | Keeps wall-clock near 10 min while the work triples. Projects already map 1:1 to CI jobs, so this adds no mechanism. Rejected: one 25-min job; cutting scope to fit; a PR-fast/nightly-slow split, whose nightly half nobody watches |
| D2 | **`streaming-greybox` is the quarantine.** One directory, one job, one grep | Phase 3 removes Redis from the data path. The extraction must be able to find every test coupled to Redis internals as a unit and rewrite or delete it. A convention spread across files would not survive |
| D3 | **Add `seed.stream()` and `seed.upstreamChannel()` to the shared fixtures** | Nine rows otherwise repeat the same scenario→stream→channel→profile wiring. Accepts a conflict surface with G3 in `seed.ts`; the alternative was nine copies of a dance that is already wrong once (`is_custom: true` is easy to forget) |
| D4 | **Grey-box reaches Redis over a published port — contingent, and verified before anything is built on it.** If the probe fails, the fallback is `docker exec … redis-cli --json`, and the quarantine (D2) is unaffected either way | **This is the one decision here resting on an unverified assumption, and the evidence points against it.** `docker/uwsgi.ini` starts Redis as a bare `attach-daemon = redis-server` — no config file, no `--bind`, no `requirepass`. That is precisely the condition that leaves **protected mode** active, under which Redis serves loopback only and answers a published-port connection (which arrives from the bridge gateway, a non-loopback source) with `DENIED`. Publishing `127.0.0.1:9403:6379` would then connect at the Docker layer and fail at the Redis layer. **Step one of the grey-box work is to prove the connection, before any test depends on it.** Turning protected mode off is not an option: it would mean editing the shipped `uwsgi.ini`, contaminating the image under test. `redis-cli --json` gives typed output and removes most of the original objection to `docker exec`, so the fallback is cheap. The port was preferred originally because a real client gives typed replies where `docker exec redis-cli` makes every assertion a string-parse, and `127.0.0.1:9403:6379` matches the existing `127.0.0.1:9191` posture. That preference stands; only its feasibility is in doubt |
| D5 | **An allowlist meta-test enforces the quarantine.** One test asserts that the set of files importing the Redis helper equals a declared list | Convention plus a README decays silently. A failing test when someone imports it from `streaming/` does not. Cheap: one `glob` plus one `grep` |
| D6 | **Contiguity is asserted from the TS payload, not from byte counts** | G2 burns a counter into the asset and rewrites CC, PCR and PTS/DTS across the loop seam. Asserting continuity counters increment mod 16 without gaps on the video PID is what proves *no chunk was lost or spliced*; a byte count proves only that bytes arrived |
| D7 | **Switch tests assert `buffer_index` is monotonic across the switch** | The chunk index is monotonic for the channel's life and is never reset by a stream switch — that invariant is precisely why a switch does not disturb clients. Asserting it directly tests the mechanism rather than its symptom |
| D8 | **The buffering row pre-arms `slow-trickle` and discriminates against dead air by construction** | Pre-arming is mandatory (`speed=` is cumulative). The discriminator: a trickle that still delivers bytes inside every 10s window makes the dead-air watchdog *impossible* to fire, so an observed switch can only have come from the buffering detector. `buffering_speed` is raised above 1.0 to arm it in reasonable time |
| D9 | **The Redirect row asserts the 302 and its `Location` without following it** | `Location` carries a container-internal hostname the Playwright host cannot resolve, and `validate_stream_url` returns the URL it was given, not the redirect target. Following it would exercise the fake provider. `redirect: 'manual'` plus `toControl()` validates the target is the right upstream URL, and `upstream.connections()` proves no bytes traversed Dispatcharr |
| D10 | **The ffmpeg row proves a subprocess actually ran**, via the ffmpeg-derived fields on `/status` | Otherwise it is indistinguishable from the Proxy row. This is also the repository's first test of any kind that spawns a subprocess |
| D11 | **The lease split-brain test is the flagship**, and asserts *correct* behaviour | It is the defect the relay extraction most needs pinned. Mechanism: drive a channel, read `owner` from `/status`, delete the owner key, and assert that no second worker claims ownership while `total_bytes` is still advancing. Expected to fail today → `test.fail()` plus an issue, per the roadmap. If it proves genuinely unprovokable from outside, record a gap rather than ship a test that passes for the wrong reason |
| D12 | **Known defects are asserted correct, marked `test.fail()`, and filed as issues — never patched** | Roadmap rule 5. G4 is expected to hit the un-fenced lease, `MAX_STREAM_SWITCHES` not bounding buffering switches, and the fMP4 `_is_timeout()` gap. Issues go to `gh issue create --repo D10Scot/Dispatcharr` with an explicit `--repo` flag, always |
| D13 | **Every read that could hang is bounded by `withDeadline()`** | The project timeout is 300s. A deadlocked read otherwise burns five minutes and reports a timeout instead of a named failure. `stalled-stream.spec.ts` established the pattern |
| D14 | **Scenarios declare explicit channel ids and names** | Channel 1 is always "Fake Channel 1" across all scenarios. Four parallel workers sharing a `seeded`-style instance makes an implicit catalogue a cross-test collision |
| D15 | **No test asserts a global count or an unfiltered list** | Roadmap rule 4, and the harness doctrine in `e2e/README.md`. Every assertion is scoped to the worker's own seeded rows |

## Project topology

```
bootstrap ──┬─→ streaming            (existing) ~4 min   2 workers
            ├─→ streaming-failover   (new)      ~7 min   2 workers
            └─→ streaming-greybox    (new)      ~3 min   1 worker
```

`streaming-greybox` runs one worker: it mutates shared Redis state, so parallel workers inside
it would race each other. The other two keep the existing 2-worker setting.

**Each CI matrix job runs its own container.** `e2e-tests.yml` gives every project its own
runner, which calls `scripts/e2e_up.sh` and gets a fresh AIO instance. That is what makes D2's
quarantine safe rather than merely tidy: `streaming-greybox` deleting an ownership lease cannot
reach `streaming` or `seeded`, because they are not the same Redis. Locally, where all three
projects can be run against one container, the grey-box project must be run alone — the
implementation plan should say so in `e2e/README.md`.

All three inherit `storageState: admin.json`, `dependencies: ['bootstrap']` and the 300 000 ms
timeout. Each is added to the CI matrix in `.github/workflows/e2e-tests.yml` alongside
`pristine` and `seeded`.

## Test inventory

| # | COVERAGE row | Project | Mechanism | Est. |
|---|---|---|---|---|
| 1 | Single client receives aligned TS | `streaming` | Proxy profile; `readPackets(200)`; alignment plus continuity counters on the video PID; provider log shows exactly one open | 20s |
| 2 | N clients share one upstream | `streaming` | Three clients, one channel; `upstream.connections().live === 1`; `/status.client_count === 3`; close one, assert `live` still 1 and count 2 | 40s |
| 3 | Client teardown releases the upstream | `streaming` | Open, read, close all; assert `live` falls to 0 and the channel leaves `/status` | 40s |
| 4 | Stream Profile: Proxy | `streaming` | Covered by row 1 | — |
| 5 | Stream Profile: Redirect | `streaming` | `redirect: 'manual'`; assert 302; validate `Location` via `toControl()`; assert no bytes traversed Dispatcharr. Optionally `redirect-chain` for depth | 15s |
| 6 | Stream Profile: FFmpeg | `streaming` | Locked ffmpeg profile; aligned TS plus ffmpeg-derived fields present on `/status` | 30s |
| 7 | Mid-stream switch does not disturb clients | `streaming-failover` | Two streams; client reading; `change_stream` to B; assert unbroken aligned TS across the switch, `stream_id` changed, `buffer_index` monotonic | 60s |
| 8 | Failover: dead air | `streaming-failover` | `dead-air` on A mid-stream; assert `stream_id` becomes B within ~60s; client still receiving | 90s |
| 9 | Failover: connect failure | `streaming-failover` | Pre-armed `not-found` on A; assert the channel lands on B without ever serving A | 45s |
| 10 | Failover: buffering | `streaming-failover` | ffmpeg profile; **pre-armed** `slow-trickle`; `buffering_speed` raised; assert switch, and that byte flow never gapped >10s so dead air cannot be the cause | 120s |
| 11 | Output Profile shared per (channel, profile) | `streaming-greybox` | Create via `/api/core/outputprofiles/`; two clients with `?output_profile=`; assert exactly one output owner lock | 45s |
| 12 | Ownership lease is fenced (flagship) | `streaming-greybox` | Delete the owner key mid-stream; assert no second owner claims it while bytes still advance. `test.fail()` expected | 60s |

Rows 4-6 are the single "Stream Profile: Redirect / Proxy / FFmpeg" row in `e2e/COVERAGE.md`,
split because they are three architectures and deserve three tests. **Row 12 is not in
`COVERAGE.md` today** — G4 adds it as a new row, status `known-bug`, in the same PR as the
tests. Rule 3 of the roadmap requires the inventory move with the tests.

## Fixture additions

- `seed.stream({url, name?})` — POSTs to `/api/channels/streams/` with `is_custom: true` and a
  generated name. Returns the created row.
- `seed.upstreamChannel(scenario, {channelIds, streamProfileId?})` — creates one `Stream` per
  upstream channel id and a `Channel` wired to them in order. Returns the channel plus its
  streams. This is the five-step dance, once.
- `e2e/fixtures/greybox/redis.ts` — a `redis` fixture over the published port. Its header states
  plainly that it is coupled to internals Phase 3 deletes, and names the allowlist.
- `expectContiguous(buffer, pid)` — continuity-counter assertion alongside the existing
  `expectTsAligned`.

## Non-goals

- VOD, catch-up and Xtream streaming. VOD is a deliberately different architecture
  (`iter_content` passthrough, no ring buffer); catch-up and Xtream belong to G5.
- The fMP4 output format beyond noting its `_is_timeout()` defect. There is no HLS output at all
  and `apps/proxy/hls_proxy/` is dead — neither is worth a test.
- Fixing any product defect. Assert correct, `test.fail()`, file the issue.
- Performance or throughput measurement. This programme establishes correctness only.
- Channel preemption — `_pick_channel_to_preempt()` is dead code with its `return` commented out,
  so there is no behaviour to test.

## Risks

- **The split-brain may be unprovokable from outside.** Deleting the owner key may simply cause
  the original owner to re-acquire it. Mitigation: it is one test in the quarantine project;
  if it cannot be made to discriminate, it becomes a documented gap, not a passing test.
- **The buffering row is the most likely to flake.** It depends on `speed=` crossing a threshold
  under a paced trickle. Mitigation: D8's discriminator means a *false pass* is impossible even
  if timing drifts — dead air cannot be the cause — so flake presents as a timeout, not a wrong
  result.
- **Failover timings are product-defined and may drift.** The 10s dead-air threshold and the
  3×-at-5s sampling are read from settings snapshotted at `StreamManager.__init__`, so a UI
  change does not affect a running channel. Tests set what they depend on rather than assuming.
- **`seed.ts` conflicts with G3.** Both goals are in flight against the same file. Mitigation:
  additive changes only, at the end of the existing factory list.
- **Publishing Redis on loopback widens the local surface.** Bound to `127.0.0.1`, matching the
  existing `9191` posture, and only in the E2E boot path — never in a shipped compose file.
