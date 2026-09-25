# G4 — live streaming data path: progress ledger

Worktree: /Users/dion/git/Dispatcharr-g4-streaming
Branch: feat/e2e-streaming-g4, off origin/main @ d22d3378
Status: BRAINSTORMING (spec not yet written)

## Decisions taken with the user

**D-A (CI budget).** The streaming job is sharded into 2-3 parallel CI jobs so
total wall-clock stays ~10 min while the work triples. Rejected: one 25-min job;
a 10-min cap achieved by cutting scope; PR-fast/nightly-slow split. Rationale:
matches how backend-tests.yml already shards its 16 labels, and every coverage
row still gets tested honestly. Costs runner minutes, not feedback latency.

**D-B (test depth).** Grey-box, clearly quarantined. Black-box HTTP/WS by
default. A small, explicitly-named set of tests may read/write Redis through one
documented helper, to provoke and observe lease and ring-buffer internals.
Quarantine is the point: Phase 3 removes Redis from the data path, and the
extraction must be able to see exactly which tests it has to rewrite.
Rejected: black-box only (makes the lease split-brain and teardown rows
unprovable); grey-box freely (couples the whole suite to internals Phase 3
deletes).

## Open

- Buffering-trigger feasibility: CLAUDE.md says the detector needs ~55s for the
  cumulative `speed=` lead to burn off, and the ~25s dead-air watchdog wins
  first. Hypothesis to verify: G2's slow-trickle fault plus a raised
  `buffering_speed` makes it arm deterministically, since that is exactly the
  partial-degradation case it is documented to earn its keep on.
- Redirect Stream Profile: established during G2's spec review that the 302
  points at the provider's internal URL, unreachable from the host. Likely
  resolution is to assert the 302 and its Location header without following it.
- Awaiting terrain report from the g4-terrain research agent.

## Design APPROVED by the user (2026-08-28)

Three Playwright projects, one CI job each (projects already map 1:1 to jobs):
- `streaming` (existing): single client, N-client sharing, teardown, Proxy +
  Redirect profiles. ~4 min.
- `streaming-failover` (new): dead air, connect failure, buffering, mid-stream
  switch. ~7 min.
- `streaming-greybox` (new): lease split-brain, Output Profile clustering.
  This project IS the D-B quarantine — one directory, one job, one grep for the
  extraction to find and rewrite when Redis leaves the data path. ~3 min.

Four judgement calls, all approved as described:
1. Add `seed.stream()` and `seed.upstreamChannel()` to the SHARED fixtures
   (`e2e/fixtures/seed.ts`). Accepts a conflict surface with G3; the
   alternative was nine rows repeating the same five-step wiring dance.
2. Grey-box reaches Redis over a published port — one line in
   `scripts/e2e_up.sh` binding `127.0.0.1:9403:6379` — not `docker exec`.
3. Redirect row asserts the 302 and its `Location` WITHOUT following it. The
   Location is an internal hostname the Playwright host cannot resolve;
   following it would test the fake provider, not Dispatcharr.
4. The lease split-brain test is the flagship. If genuinely unprovokable,
   record a gap rather than ship a test that passes for the wrong reason.

## Facts verified this session (not assumptions)

- `POST /proxy/ts/change_stream/<id>` (explicit target) and
  `POST /proxy/ts/next_stream/<id>` (rotate) both exist, both admin-only.
- `GET /proxy/ts/status/<id>` returns stream_id, client_count, buffer_index,
  owner, and a per-client array — the primary assertion surface.
- There is NO WebSocket event for a switch, failover, or teardown.
  `channel_stats` is the only thing live_proxy emits, and its payload arrives
  as a JSON-encoded STRING. Poll `/status` via `waitFor.resource` instead.
- `/api/core/outputprofiles/` is real (`core/api_urls.py:21`,
  `OutputProfileViewSet`).
- Built-in Stream Profiles: Proxy + Redirect from `core/migrations/0007`, VLC
  from `0019`, locked flags set by `0006`/`0011`. Find by name, never count.
- BUFFERING ROW IS TESTABLE. `slow-trickle` arms cleanly only when set BEFORE
  ffmpeg starts (speed= is cumulative since process start). Pre-arming is the
  pattern G2 already built. Mid-stream trickle takes ~55s and dead-air wins at
  ~25s — that is the trap, and pre-arming avoids it.
- No `seed.stream()` factory exists today; `upstream-through-proxy.spec.ts`
  creates a custom Stream by hand. That is the dance judgement call 1 removes.
