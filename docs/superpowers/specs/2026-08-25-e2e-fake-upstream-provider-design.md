# G2 — Fake Upstream Provider

**Date:** 2026-08-25
**Status:** Approved, ready for implementation planning
**Wave:** 1 (G1 landed at `a0c99cdd`; G2 branches from `main` and runs alone)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`

## Goal

Build a controllable IPTV provider that Dispatcharr can ingest from and stream through: an M3U
playlist endpoint, an XMLTV EPG endpoint, a real looping MPEG-TS stream, and a control API that
flips fault modes mid-test.

G2's output is **infrastructure plus two plumbing proofs**, not feature coverage. It succeeds if
G3's and G4's agents can express "the provider does X, now assert Dispatcharr does Y" without
writing a byte of server code.

## Current state

- G1 shipped `e2e/support/static-upstream.ts`, labelled THROWAWAY: an endless stream of
  188-byte packets on PID `0x0100` with an incrementing continuity counter, paced at 10 packets
  per 20 ms (≈750 kbit/s). It has no catalogue, no EPG, and no faults beyond a burst schedule.
- **Nothing has yet proved a Dispatcharr container can reach a test-controlled upstream.**
  Both G1 streaming exemplars point `streamClient` directly at the throwaway server; the bytes
  never traverse Dispatcharr. `scripts/e2e_up.sh` runs the container on the default bridge with
  no `--add-host`, so on Linux CI it cannot resolve `host.docker.internal` today.

## Verified facts this design rests on

Cited by symbol, not line — line numbers in this repo drift, and an earlier draft of this table
carried four wrong ones.

| Fact | Source | Consequence |
|---|---|---|
| `seed.m3uAccount()` defaults to `server_url: 'http://127.0.0.1:9/playlist.m3u'` and `is_active: false` | `e2e/fixtures/seed.ts` | G2's tests must pass **both** a scenario URL and `is_active: true`. An inactive account never starts, so both phases of `waitFor.m3uRefreshComplete` fail |
| `waitFor.m3uRefreshComplete(id)` owns the trigger by default, but accepts a `trigger` override | `e2e/fixtures/wait.ts`, `M3uRefreshWaitOptions` | Tests must not POST the refresh *and* let the helper POST it. Passing `trigger` is the supported way to drive a refresh some other way |
| **The plain M3U fetch sends `server_url` and a `User-Agent` header, nothing else.** `M3UAccount.username`/`password` are read only on Xtream paths (`get_xc_*`, `refresh_xc_*`) | `apps/m3u/tasks.py` | Credentials must be **embedded in the URL string** handed to Dispatcharr. Setting the model fields on a standard account authenticates nothing |
| **`apps/epg/tasks.py` never reads `EPGSource.username`/`password`.** The fields exist for Schedules Direct | `apps/epg/tasks.py` (no reads) | Same: EPG credentials go in `EPGSource.url` or nowhere |
| The M3U fetch rejects "non-text content" | `apps/m3u/tasks.py`, `"Server provided non-text content"` | The playlist must be served as `application/vnd.apple.mpegurl` or `text/plain`. XMLTV as `application/xml` |
| `M3UAccount.max_streams` is Dispatcharr's *declared* belief about the upstream limit | `apps/m3u/models.py`, `M3UAccount.max_streams` | Distinct from the provider's real accounting. A scenario where the two disagree is a legitimate G4 test |
| `validate_stream_url()` issues a HEAD with `allow_redirects=True`, falls back to a GET reading `188*10` bytes, and **returns the URL it was given** — not the redirect target | `apps/proxy/live_proxy/url_utils.py`, `validate_stream_url` | The Redirect profile 302s the client to the *original* upstream URL. See D16 |
| `views.py` returns `HttpResponseRedirect(final_url)` for redirect profiles | `apps/proxy/live_proxy/views.py`, `stream_ts` | Combined with the row above: the client is sent to a container-internal hostname it cannot resolve |
| **The default ffmpeg profile is `-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1` — no `-re`** | `core/migrations/0006_set_locked_stream_profiles.py` | Nothing throttles the read. See D17 |
| The Proxy profile is a bare `iter_content` loop with no pacing | `apps/proxy/live_proxy/input/http_streamer.py`, `HTTPStreamer` | Same. An unpaced provider is read at wire speed |
| A clean EOF logs `"HTTP stream ended"`; an abrupt close lands in the `RequestException` branch | `apps/proxy/live_proxy/input/http_streamer.py` | Two distinct reconnect paths, so `disconnect` must be parameterised. See D19 |
| `streamClient.open()` calls global `fetch` with no `redirect` option, i.e. `'follow'` | `e2e/fixtures/stream-client.ts` | A followed 302 to `e2e-upstream:8080` is a DNS failure on the host. See D16 |
| `input/buffer.py` realigns to 188-byte packet boundaries before writing chunks | `apps/proxy/live_proxy/input/buffer.py` | The non-TS-bytes fault targets real defensive code |
| Failover triggers: buffering (ffmpeg-only, `speed=` cumulative since process start), dead air (>10 s, 3× at 5 s), connect failure (3 in 30 min) | `CLAUDE.md`, Architecture | The buffering detector cannot arm quickly. See the fault catalogue's notes |
| `scripts/e2e_up.sh` is the single boot path — CI calls it rather than duplicating `docker run` | `.github/workflows/e2e-tests.yml` | Provider startup extends that script |
| The `build` job produces one image artifact for all three matrix jobs | `.github/workflows/e2e-tests.yml`; G1 spec D4 | Same rationale for the provider image |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Own container on a user-defined Docker network** shared with Dispatcharr | Identical on macOS and Linux CI. `host.docker.internal` is not portable between Desktop and Engine; baking into the AIO image contaminates the artifact under test |
| D2 | **Pre-baked TS loop**, with **CC, PCR *and* PTS/DTS** rewritten across the seam | PES timestamps otherwise reset on every wrap. Through `-c copy` that is a non-monotonic-DTS discontinuity each loop, which the muxer mangles and `log_parsers.py` sees on stderr |
| D3 | **Node / TypeScript**, sibling directory `e2e-upstream/` | Socket-level faults that Node's streams express directly; control-API types shared with the tests that drive them |
| D4 | **Eight faults**, frozen | The roadmap's six plus redirect chains and non-TS bytes |
| D5 | **Its own vitest suite**, run in CI independently of Dispatcharr | Without it every G4 failure is a two-body problem |
| D6 | **Isolation by scenario id in the URL path**, one container | Isolates per *test*, not per worker; no port arithmetic |
| D7 | **Built in the existing `build` job**, saved into the same artifact | One image under test, matching G1's D4 |
| D8 | **Test-declared catalogues**, with a default | G3 needs malformed lines, duplicate `tvg-id`s, missing logos, 5,000-channel playlists |
| D9 | **Exactly two Dispatcharr-facing plumbing proofs** | Cheap insurance against handing G3/G4 an undiagnosed networking failure |
| D10 | **Real per-scenario concurrency accounting**; default **unlimited**, `maxConnections: 0` = reject all | Only real counting proves the ring buffer consumes one upstream slot for ten clients |
| D11 | **No scenario eviction** | Mirrors G1's D7. TTLs and teardown ordering are the flake sources that decision avoids |
| D12 | **Synchronous control API**, echoing effective state and `appliedTo` | A fault that reached nobody must say so immediately, not time out after 300 s |
| D13 | **Per-scenario request/connection log**, attached to the report on failure | Otherwise G4's agent writes its own instrumentation, badly |
| D14 | **Credentials embedded in the URL as query parameters** | Forced by the fact table: the product sends no credentials on standard M3U or XMLTV fetches. The scenario's `internal`/`control` URLs carry them |
| D15 | **`scripts/e2e_up.sh` grows**; no compose file | Single-boot-path invariant; `docker/docker-compose.*.yml` already means "how you deploy Dispatcharr" |
| D16 | **Redirects are handled in the fixture, not the network**: `streamClient.open(url, { redirect })`, plus `upstream.toControl(url)` rewriting the internal origin to the control origin | Dispatcharr 302s to the *original* upstream URL, which is container-internal. A Redirect test asserts on `Location` and walks the chain itself |
| D17 | **The loop is served at the asset's nominal bitrate**, with a per-scenario rate multiplier settable at creation and via the control API | Nothing in the product paces the read. Unpaced, a 15 MB asset floods the Redis ring buffer at hundreds of Mbit on DB 0 — shared with the Celery broker and cache — and makes `speed=` read ~50×, so the buffering detector can never arm |
| D18 | **Faults take an optional channel filter** | Every failover trigger switches to the channel's *next* Stream row. Scenario-wide faults would take both streams down, so a test cannot distinguish "switched" from "didn't" |
| D19 | **`disconnect: { clean, afterBytes? }`, default abrupt** | Clean EOF and abrupt close reconnect via different branches, and real providers do both. `afterBytes` is also what G1's `endAfterLastBurst` case needs |
| D20 | **The provider's own vitest suite generates a tiny synthetic TS in-process** | `assets/` is gitignored and built in the Docker builder stage, and the job has no `needs: build`. Host ffmpeg would reintroduce the version skew D2 removes. The rewriter must not care what the asset is |

## Architecture

### Directory layout

```
e2e-upstream/                  sibling of e2e/, its own npm package
├── package.json               own lockfile; not part of e2e/'s install
├── Dockerfile                 multi-stage: ffmpeg builder → node runtime
├── src/
│   ├── server.ts              HTTP surface, routing by scenario id
│   ├── scenario.ts            registry, catalogue model, connection accounting
│   ├── playlist.ts            M3U generation
│   ├── xmltv.ts               EPG generation, rolling window relative to now
│   ├── ts-loop.ts             asset reader; CC, PCR and PTS/DTS rewrite; pacing
│   ├── faults.ts              the eight faults, applied per connection
│   ├── control.ts             control API
│   └── log.ts                 per-scenario request/connection log
├── assets/                    .gitignored; produced at image build
└── test/                      vitest: one file per fault, plus the seam
```

`e2e/fixtures/upstream.ts` holds only the **client**. No server code in `e2e/`.

### Two base URLs, never conflated

A scenario yields both, as distinctly named fields — there is deliberately no bare `url`:

| Field | Value | Used by |
|---|---|---|
| `internal` | `http://e2e-upstream:8080/s/<id>` | URLs handed to Dispatcharr |
| `control` | `http://127.0.0.1:<published>/s/<id>` | Control calls Playwright makes |

Handing `control` to Dispatcharr resolves inside the container to the container itself. The
fixture's types make the two non-interchangeable, and `upstream.toControl(url)` is the only
sanctioned conversion.

When a `fetch` from the host fails DNS resolution on an `e2e-upstream` hostname, the fixture
throws a named error saying so and pointing at `redirect: 'manual'` + `toControl` — the G1 house
style of failing by name rather than by timeout.

### Networking

`scripts/e2e_up.sh` creates a user-defined network, starts `e2e-upstream` on it with its control
port published to `127.0.0.1`, **waits for `GET /scenarios` to answer**, then starts
`dispatcharr-e2e` on the same network. `--stop`, `--down` and `--reset` cover both containers.
Container-name DNS works only on a user-defined network, which is why one is created rather than
the default bridge reused.

**The `E2E_BASE_URL` escape hatch does not extend to G2.** A remote Dispatcharr cannot reach a
local provider; G2-dependent tests require the local two-container topology.

### The TS asset

Generated at image build by ffmpeg in a builder stage: 60 s, 25 fps, fixed PIDs, ~2 Mbit. The
runtime stage carries the asset and Node, not ffmpeg. Base images are digest-pinned per the
repo's supply-chain rules.

Serving loops the file, paced at nominal bitrate (D17). The seam is the hard part — three
rewrites, per PID:

- **Continuity counters** must continue monotonically across the wrap.
- **PCR** must advance monotonically.
- **PTS/DTS** must advance monotonically. This is the one that matters end-to-end: ffmpeg's
  mpegts muxer *regenerates* CC and PCR, so the provider's CC continuity is only observable
  through the **Proxy** profile. Through ffmpeg, PTS monotonicity read from PES headers is the
  only decoder-free continuity evidence available.

The 2³³ / 90 kHz timestamp wrap (~26.5 h) is a known non-issue at these runtimes — recorded here
so nobody "fixes" it.

A frame counter is burned into the video as a **human debugging aid only**, for eyeballing a
captured TS artifact after a G4 failure. Nothing in the test runner decodes video, so no test
asserts on it.

## Control API

All responses are synchronous and echo effective state (D12).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/scenarios` | Create. Body declares catalogue, optional credentials, `maxConnections` (default unlimited), `rate` (default 1). Returns `{ id, internal, control, channels }` |
| `GET` | `/scenarios` | List live scenarios. Also the readiness endpoint `e2e_up.sh` waits on |
| `DELETE` | `/scenarios/<id>` | Optional explicit close |
| `POST` | `/s/<id>/fault` | Apply or clear a fault. Body takes an optional `channel` filter (D18) and per-fault parameters. Returns `{ fault, active, appliedTo }` |
| `POST` | `/s/<id>/rate` | Set the pacing multiplier on a live scenario |
| `GET` | `/s/<id>/log` | Request/connection history: method, hits, opens/closes with byte counts and durations, faults applied |
| `GET` | `/s/<id>/connections` | Live connection count and the accounting behind `maxConnections` |

Provider-facing endpoints: `/s/<id>/playlist.m3u`, `/s/<id>/epg.xml`,
`/s/<id>/stream/<channelId>.ts`.

### HEAD and probe connections

`validate_stream_url()` probes before streaming, so the provider must:

- answer **HEAD** with `200`, `Content-Type: video/mp2t`, no body;
- **not** count HEAD toward `maxConnections`;
- log the request method, so a probe is distinguishable from a real client.

The validation **GET** is never explicitly closed by the product, so a Redirect-profile channel
transiently holds a probe slot: a `maxConnections: 1` scenario will reject the real client until
that probe is reaped. G4 and G5 must know this, and the provider log makes it visible.

Because `validate_stream_url` follows the chain once and the test's own client follows it again,
the log will show a redirect chain walked **twice by two different clients**. That is correct
behaviour, not a bug.

## Fault catalogue

`appliedTo` reports how many live connections a fault reached. Faults that can only affect the
*next* request legitimately return `appliedTo: 0` — "arm `not-found` for the next reconnect" is a
normal test. **D12 is therefore not a fixture-level assertion**: the fixture returns the number,
the test decides what it should be.

| Fault | Applies to | Behaviour | Drives |
|---|---|---|---|
| `dead-air` | live + new | Connection stays open, no bytes written | Dead-air failover (>10 s, 3× at 5 s) |
| `slow-trickle` | live + new | Pacing multiplier < 1 | Buffering detector — **ffmpeg profiles only**, and it only arms if the rate is set *before* ffmpeg starts: `speed=` is cumulative since process start, so a trickle applied mid-stream takes ~55 s to arm and dead-air wins at ~25 s |
| `disconnect` | live | `{ clean, afterBytes? }`; default abrupt | Both reconnect branches (`RequestException` vs `"HTTP stream ended"`) |
| `not-found` | new only | 404 on the requested endpoint | Connect-failure trigger; refresh error handling |
| `auth-failure` | new only | Credentials that were valid start being rejected | Mid-refresh credential expiry |
| `connection-limit` | new only | Real per-scenario accounting; N+1th rejected, readmitted on close | Provider-slot semantics; `max_streams` disagreement |
| `redirect-chain` | new only | 301/302 chain of declared depth before the payload | The Redirect stream profile, via D16 |
| `non-ts-bytes` | new only | 200 with an HTML error page instead of TS | `buffer.py`'s realignment defence |

## Fixture contract

```ts
const scenario = await upstream.scenario({ channels: 3 });
// → { id, internal, control, channels: [...] }

await upstream.fault(scenario, 'dead-air', { channel: scenario.channels[0].id });
// → { fault: 'dead-air', active: true, appliedTo: 1 }

await upstream.rate(scenario, 0.2);            // slow-trickle
await upstream.clearFault(scenario, 'dead-air');
await upstream.log(scenario);                  // connection/request history
upstream.toControl(scenario.internal + '/stream/1.ts');
```

`upstream` is worker-scoped; scenarios are test-scoped. The fixture attaches the scenario log to
the Playwright report on failure (D13).

## Deliverables

- [ ] `e2e-upstream/` — server, control API, eight faults, paced TS loop with CC/PCR/PTS seam rewrite
- [ ] Multi-stage `Dockerfile`, digest-pinned, ffmpeg confined to the builder stage
- [ ] vitest suite: one test per fault; the seam's per-PID PTS monotonicity assertion; an
      `appliedTo === 0` test applying a fault with no connections open. Asset synthesised
      in-process (D20)
- [ ] `e2e/fixtures/upstream.ts` + export from `fixtures/index.ts`, incl. `toControl`
- [ ] `streamClient.open()` gains a `redirect` option and the named DNS-failure error
- [ ] `scripts/e2e_up.sh` extended: network, both containers, readiness wait, all four modes
- [ ] `.github/workflows/e2e-tests.yml`: provider built in `build`, both images in one artifact;
      new `upstream` job for the vitest suite — **no `needs: build`**, so it reports without
      waiting on a 45-minute AIO build
- [ ] G1's two streaming exemplars rewritten onto the provider, **hitting it directly via
      `control`** — they test `streamClient`'s own semantics, not the proxy
- [ ] `e2e/support/static-upstream.ts` **deleted**
- [ ] Two plumbing proofs: ingest, in **`seeded`** (seed account at a scenario URL → refresh →
      declared channels appear); stream-through, in **`streaming`** (proxy the provider's TS via
      `/proxy/ts/stream/<uuid>`, assert alignment). `pristine` gains nothing
- [ ] `e2e/COVERAGE.md` updated; `CONTEXT.md` gains "scenario", "fault", "upstream provider"
- [ ] `e2e-upstream/README.md` — fault catalogue, control API, local run

### Definition of done

A G4 agent can write "put channel 1 into dead air, assert Dispatcharr fails over to channel 1's
next stream within N seconds, assert the client's byte stream stayed 188-aligned across the
switch" using only the fixture contract and the fault catalogue, without reading
`e2e-upstream/src/`.

## Non-goals

- **Xtream Codes API, VOD catalogue, catch-up archive.** Deferred to G5, which builds them on
  this foundation. Implementing them here is what would make G2 unshippable.
- Schedules Direct emulation. Third-party API, out of scope for every goal.
- Feature coverage. G2 ships two plumbing proofs; the areas belong to G3 and G4.
- Fixing product bugs found while building — file them (`gh issue create --repo D10Scot/Dispatcharr`).

## Risks

| Risk | Mitigation |
|---|---|
| The CC/PCR/PTS seam rewrite is subtler than budgeted | It is the first task, with its own vitest assertion. If it slips, the fallback is a loop long enough that no test crosses the seam — degraded, but shippable |
| Pacing at nominal bitrate makes streaming tests slow | `rate > 1` exists for tests that want bytes fast and do not care about the buffering detector. Only tests asserting on `speed=` need rate 1 |
| Adding a second container to `e2e_up.sh` breaks `pristine` | `pristine` does not use the provider; it being present but unused changes nothing those tests observe. Verify explicitly |
| The workflow edit trips the zizmor hook, held at zero findings | Expected. Any new step is written clean first time; the hook blocks on every finding in the edited file |
| Container-name DNS differs between Docker Desktop and Engine | The reason D1 was chosen. Verified on both in task 1, before anything is built on it |
| `appliedTo` silently reports 1 when the fault reached nobody | Its own vitest test (see deliverables) |
