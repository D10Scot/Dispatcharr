# `e2e-upstream` contract

**Version:** 1.1.0

**An unlisted behaviour is not a guarantee.** If it isn't named below, a
consumer test must not depend on it, however consistently it happens to
behave today — see "Bump policy" for what changing it costs, and "Non-
guarantees" for the ones already known to bite.

This document is the promise; `e2e-upstream/README.md` is the how-to. Every
mechanism named here is explained there in full — routes, request/response
shapes, the fault catalogue, pacing, the two-asset split. This document does
not repeat any of that: it says what may be relied on, what may not, who
already relies on it, and what changing it costs. Read the linked README
section before writing a test against anything named here.

## Scope

Everything under `e2e-upstream/src/` reachable over HTTP: `POST`/`GET`/
`DELETE /scenarios`, the four `/s/<id>/*` control routes (`fault`, `rate`,
`log`, `connections`), the three provider-facing routes (`playlist.m3u`,
`epg.xml`, `stream/<id>.ts`), and the six XC routes (`player_api.php`,
`/live/`, `/movie/`, `/series/`, `/timeshift/`, `/streaming/timeshift.php`).
`e2e-upstream/scripts/` (asset generation) and `e2e-upstream/test/` (the
package's own vitest suite) are covered only insofar as their behaviour is
observable through those routes — the build scripts' internals and the test
suite's own assertions are not themselves part of this contract.

## Guarantees

Every item below is enforced today by `e2e-upstream/test/*.test.ts` (see
"Enforcement"), and is safe for a consumer test to depend on. Each links to
the README section that documents the mechanism.

- **Real per-scenario connection accounting.** `ConnectionRegistry.tryAcquire`
  (`src/connections.ts`) admits or rejects before any response header is
  written, so a rejected client never sees a `200` first, and a `HEAD` probe
  never consumes a slot. See "HEAD and probe connections" in the README. The
  `connection-limit` *fault* can still force a rejection irrespective of the
  true count — that is documented fault behaviour, not a break in this
  guarantee (see "Fault catalogue" below).
- **The fault catalogue behaves exactly as the README's fault table
  documents** — all twelve faults, their scoping rules (`channel` vs
  scenario-wide, and which faults reject a `channel` filter outright), and
  `appliedTo`'s meaning. See "Fault catalogue" in the README.
- **The finite VOD asset's `Range` handling is RFC-9110-shaped and honest**:
  a satisfiable `bytes=` range gets `206` with a correct `Content-Range` and
  `Content-Length`; an unsatisfiable one gets `416`; anything else gets `200`
  with a truthful `Content-Length` and (unless `range-unsupported` is armed)
  `Accept-Ranges: bytes`. See "The VOD asset" in the README.
- **The two base URLs (`internal`, `control`) are never conflated** and never
  guessed at — `scenarioUrls` (`src/server.ts`) derives `control` from the
  request's own `Host` header rather than a fabricated default. See "Two
  origins, never conflated" in the README.
- **`POST /scenarios` echoes the fully resolved scenario**, including every
  default the parser filled in (generated channel/movie/series ids,
  resolved `categoryId`s) — never just the fields the caller sent. See
  "Control API" in the README.
- **The request/connection/fault history at `GET /s/<id>/log` is complete for
  every request this provider answers or rejects**, including the ones a
  fault turns away before any route-specific logic runs, and every route
  logs before it can throw. See "Control API" in the README.
- **The catch-up request itself is provably correct**: `GET /s/<id>/log`
  records the exact `start` string, stream id, duration and credentials a
  catch-up request carried, in both layouts. See "Catch-up" below and in the
  README — this is a narrower guarantee than it may first read as; see the
  matching non-guarantee.
- **The asset's loop duration and packet count are measured, never
  hardcoded**, so a drifted build-time ffmpeg cannot silently desynchronise
  the server from the asset it serves. See "The asset" in the README. This is
  a guarantee about internal consistency, not about a *specific* duration or
  packet count — see "Non-guarantees".

## Non-guarantees

Each of these is a real, current behaviour of this provider. None of them may
be relied on by a consumer test — several exist specifically so a consumer
test can prove Dispatcharr does *not* rely on them either.

- **No calendar validation on catch-up.** `CATCHUP_TIMESTAMP_SHAPES` /
  `parseCatchupTimestamp` (`src/xc/catchup.ts`) match a `start` value against
  four fixed shapes and accept any value that fits one, impossible dates
  included — `2026-13-45:99-99` parses successfully. This provider answers
  any parseable timestamp; it never validates that the date exists.
- **No time-addressable archive.** The catch-up routes (`src/xc/router.ts`,
  the `catchup` branch) serve the same looping asset via `serveChannelStream`
  whatever `start` was asked for — there is only one archive and it plays
  identically regardless of the requested instant. This provider can prove
  Dispatcharr *asked* for the right moment (the guarantee above, via
  `GET /s/<id>/log`); it can never prove Dispatcharr *received* it. State
  this in the same words wherever a G10-descended test asserts on catch-up
  timing, so this document and that test cannot drift apart. See "Catch-up"
  in the README.
- **A requested catch-up `duration` is parsed but never enforced.**
  `CatchupRequest.durationMinutes` (`src/xc/catchup.ts`) is recorded — it
  reaches the log — but nothing in `src/xc/router.ts`'s catchup branch reads
  it back to truncate or bound the stream. A test asserting the provider
  "served for the requested duration" would be asserting something this
  provider does not do.
- **Credential validation on the non-XC routes only exists when a scenario
  declares credentials — the XC routes are stricter, not the same.**
  `credentialsMatch` (`src/server.ts`), which gates the playlist, EPG and
  plain `/s/<id>/stream/<n>.ts` routes, returns `true` unconditionally when
  `scenario.username` is `undefined`: a scenario created with no
  `username`/`password` accepts any request there, including one with no
  credentials at all. `xcCredentialsMatch` (`src/xc/router.ts`), which gates
  `player_api.php` and the `/live/`, `/movie/`, `/series/` routes, has **no
  such branch** — it always compares against `scenario.username ?? ''` and
  `scenario.password ?? ''`, so a credential-less scenario would *require*
  empty-string credentials on those routes rather than accept anything. In
  practice this difference is rarely reachable: `parseScenarioRequest`'s `xc`
  door (see the next bullet) requires both fields whenever `xc: true`, so a
  live XC scenario's `scenario.username` is essentially never `undefined`.
  `auth-failure` models something different from either of these (valid
  credentials that stop being accepted) and is not a substitute for this.
- **The XC empty-password door is a known provider defect, not a validated
  guarantee.** `parseScenarioRequest`'s `xc` check (`src/scenario.ts`) rejects
  only `password === undefined`, not a falsy value, so
  `{ xc: true, username: 'u', password: '' }` is accepted and then unservable
  the moment a real client streams from it. Documented in the README's
  "Scenario defaults and credentials" section and in `e2e/COVERAGE.md`'s G8
  known-bug row; not fixed here (out of scope per spec D10 — see "Bump
  policy"). `seed.xcAccount` is deliberately stricter than this door; a test
  that bypasses it is not protected.
- **The live TS loop never sends `Content-Length`, under any circumstance.**
  `streamLoop` (`src/stream.ts`) writes headers with no `Content-Length` at
  all — deliberate, since the stream has no end. This is unrelated to the
  VOD asset's guarantee above, which is a *different* route serving a
  *different*, finite asset.
- **`Range` is honoured only on the finite VOD asset, never on a live
  stream.** `/s/<id>/stream/<n>.ts`, `/live/...` and both catch-up routes all
  route through `streamLoop`, which has no `Range` handling of any kind — a
  `Range` header sent there is silently ignored, not rejected.
- **A multi-range or non-`bytes`-unit `Range` header is treated as no `Range`
  at all** (a silent `200` with the full body), never rejected with an error.
  `parseRange` (`src/vod-asset.ts`) understands exactly one shape:
  `bytes=<start>-<end>`, `bytes=<start>-` or `bytes=-<suffix>`.
- **No scenario, connection, fault or log state survives a process
  restart.** `ScenarioRegistry`, `ConnectionRegistry`, `FaultStore` and
  `ScenarioLog` (instantiated in `src/server.ts`) are all in-memory `Map`s
  with no persistence of any kind. `e2e/COVERAGE.md`'s G12 lifecycle row
  states the consequence directly: "`ScenarioRegistry` is an in-memory `Map`,
  so every upstream scenario is forgotten across the event."
- **Scenario ids are never stable or predictable across calls.**
  `ScenarioRegistry.create` (`src/scenario.ts`) assigns a fresh
  `randomUUID()` on every `POST /scenarios`. Only the catalogue *within* one
  already-created scenario has stable, predictable ids (channel `1` is
  always `Fake Channel 1` under the count form) — the scenario id wrapping
  it is not, and never two calls apart.
- **`appliedTo` does not mean "this fault is now armed" for nine of the
  twelve faults.** Only `dead-air`, `slow-trickle` and `disconnect` reach an
  already-open connection and can report a nonzero count; the other nine
  (`not-found`, `auth-failure`, `connection-limit`, `redirect-chain`,
  `non-ts-bytes`, `xc-auth-envelope`, `no-tv-archive`, `catchup-layout-404`,
  `range-unsupported`) can only ever affect the *next* request, so
  `appliedTo: 0` is their correct, expected result — not a sign the fault
  failed to apply. See `FaultStore.apply` (`src/faults.ts`).
- **The TS asset carries no per-stream identity (spec D6).** `getAsset()`
  (`src/server.ts`) serves one shared file to every channel and every
  scenario; the mux is built with fixed PIDs (`scripts/make-asset.sh`'s
  `-mpegts_start_pid 0x100 -streamid 0:256 -streamid 1:257`, i.e. video
  `0x100`, audio `0x101`), so no two channels' byte streams can be told
  apart by content. The burned-in frame counter is, in `make-asset.sh`'s own
  words, "a human debugging aid only … no test asserts on it" — no consumer
  test may start asserting on it either. Building per-stream identity is
  feasible under the Proxy stream profile (a dedicated marker PID injected in
  `LoopRewriter`) but not under the locked FFmpeg profile, whose
  `-c:v copy -c:a copy` remux maps exactly one video and one audio stream and
  lets the mpegts muxer rewrite PAT/PMT/PIDs itself; this is a provider
  capability nobody has built (see `e2e/COVERAGE.md`'s Streaming Gap row for
  this goal), not a guarantee this document can make today.
- **Neither generated asset's exact size, packet count or duration may be
  hardcoded anywhere.** `scripts/make-asset.sh` and `make-vod-asset.sh`
  deliberately run an unpinned Debian ffmpeg; both scripts assert only shape
  (TS-packet-aligned and sync-byte-prefixed; at least 1 KB and `ftyp`-prefixed
  respectively), not a byte-reproducible artifact. `measureLoop`
  (`src/asset.ts`) measures the loop duration from the asset at server
  startup for the same reason. A version drift in ffmpeg is expected to
  change these numbers.
- **The pacing rate is only approximate above 1×.** `streamLoop` sleeps
  per-chunk against that chunk's own size, not a cumulative target — the
  README records rate `10` measuring roughly `8.1×`, not `10×`. Assert an
  order of magnitude if a test must assert on throughput at all; never a
  precise multiplier.
- **The generated XMLTV window shifts with wall-clock time; it is not a fixed
  document.** `renderXmltv` (`src/xmltv.ts`) anchors two hours before and
  twenty-four after `new Date()` at request time — two requests made minutes
  apart can return different slot boundaries. Nothing pins the guide's
  *content* beyond structure (channel list, one programme per slot).
- **`disconnect`'s `afterBytes` is exact only against a draining client.**
  Under backpressure — a client that isn't reading — a chunk already queued
  before the cutoff is delivered in full, so the client may see more bytes
  than requested. See `ConnectionRegistry`'s `disconnect` doc comment
  (`src/connections.ts`) and "Fault catalogue" in the README.

## Known consumers

`e2e/fixtures/upstream.ts` is the one sanctioned client — see the README's
"You will not normally talk to it directly" note. Every spec file that
imports it, across `e2e/tests/{seeded,streaming,streaming-failover,
streaming-greybox,frontend}`, is a consumer of this contract transitively
through that fixture, spanning G2 through G10's rows in `e2e/COVERAGE.md`
(ingest plumbing, live and VOD streaming, failover, catch-up, and the XC
surface). None of them reads `e2e-upstream/src/` directly — that is the
point of this document existing: a consumer author works from this contract
and the README, never from the implementation.

`e2e-upstream`'s own `test/*.test.ts` (vitest) is not a consumer in this
sense — it is the thing that keeps this document honest (see "Enforcement").

## Bump policy

Semantic-ish versioning against the guarantees above, not against the code:

- **Patch** — a change that touches `src/` but does not add, remove or alter
  any guarantee or non-guarantee listed here (an internal refactor, a log
  message wording change, a new test in `test/`).
- **Minor** — a backward-compatible addition: a new fault, a new optional
  scenario field, a new route, or a guarantee this document did not
  previously make. Existing consumers keep working unmodified.
- **Major** — a breaking change to any documented guarantee: removing or
  renaming a fault, changing a response shape a consumer relies on,
  tightening validation that was previously permissive in a way a passing
  consumer test now fails against. A major bump obligates a scan of every
  known consumer above before landing.

**This landing is 1.1.0, a minor bump, moving from the unversioned baseline
of `1.0.0`.** Writing this document adds no runtime behaviour and breaks
nothing — by the rule above it could be argued a patch. It is taken as minor
anyway, deliberately: this is the *first* time any of the guarantees and
non-guarantees above have been written down as a version-addressable
document at all, which is new information a consumer can now depend on even
though no code path changed, and landing it is also the one chance to prove
the bump-and-enforce procedure itself works before any later, real bump
depends on it. Per the plan's Global Constraints (spec D10), this task adds
no `e2e-upstream/src/` change and no `/version` endpoint — the version lives
only in `package.json` and this document, kept in sync by the guard below.

## Enforcement

Two different things are enforced, at two different levels, and neither
substitutes for the other:

- **That the guarantees and non-guarantees above are actually true of the
  running provider** is enforced by `e2e-upstream/test/*.test.ts` (vitest) —
  it is the semantic check, and it existed before this document did. This
  document is a claim about what that suite (and the consumer specs that
  build on it) already prove; it does not add new runtime assertions of its
  own.
- **That this document's declared version and `package.json`'s declared
  version never drift apart** is enforced by
  `e2e/tests/guards/upstream-contract.spec.ts` (G15) — a source-scan guard in
  the `guards` Playwright project, requiring no container and no browser. It
  is purely syntactic: it does not — and cannot — re-verify that any
  guarantee above still holds. A version bump with no corresponding edit to
  this document, or a documented version that doesn't match `package.json`,
  fails it immediately. Verified by mutation; see `e2e/COVERAGE.md`'s Guards
  table for the exact mutation and its output.
