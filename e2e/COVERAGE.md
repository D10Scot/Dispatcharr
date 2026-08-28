# E2E Coverage Inventory

The shared worklist for all seven goals. **Update this in the same PR as the
tests.** Status: `todo` / `done` / `known-bug` (asserted correct, marked
`test.fail()`, issue filed).

| Area | Flow | Goal | Status |
|---|---|---|---|
| Setup | First-run superuser creation and login | G1 | done |
| Harness | Authenticated session via storageState | G1 | done |
| Harness | API client survives token expiry | G1 | done |
| Harness | Namespaced seeding | G1 | done |
| Harness | Non-admin principals at two user levels (asPrincipal) | G1 | done |
| Harness | Login budget: driving a fixed principal spends no login | G1 | done |
| Harness | REST polling and WebSocket waiting | G1 | done |
| Harness | WebSocket queue semantics and event correlation | G1 | done |
| Harness | Byte-level TS stream reading | G1 | done |
| Harness | Source factories (stream profile, M3U, EPG) | G1 | done |
| Upstream | Fake upstream provider: playlist, EPG, paced TS loop | G2 | done |
| Upstream | Fault injection (eight faults, control API) | G2 | done |
| Upstream | Plumbing proof: M3U ingest → declared channels appear | G2 | done |
| Upstream | Plumbing proof: stream-through via `/proxy/ts/stream/<uuid>` | G2 | done |
| Sources | M3U account create → refresh → streams appear | G3 | todo |
| Sources | EPG source create → refresh → programme data | G3 | todo |
| Sources | Channel creation from streams | G3 | todo |
| Sources | Auto channel sync | G3 | todo |
| Sources | Channel groups and Channel Profiles | G3 | todo |
| Sources | Logo upload and assignment | G3 | todo |
| Streaming | Single client receives aligned TS | G4 | todo |
| Streaming | N clients share one upstream | G4 | todo |
| Streaming | Mid-stream switch does not disturb clients | G4 | todo |
| Streaming | Failover: dead air | G4 | todo |
| Streaming | Failover: connect failure | G4 | todo |
| Streaming | Failover: buffering (ffmpeg only) | G4 | todo |
| Streaming | Client teardown releases the upstream | G4 | todo |
| Streaming | Stream Profile: Redirect / Proxy / FFmpeg | G4 | todo |
| Streaming | Output Profile shared per (channel, profile) | G4 | todo |
| Streaming | Ownership lease is fenced against a second concurrent owner — attempted by deleting `live:channel:{uuid}:owner` under a running Proxy-profile stream and polling for a second worker to claim it; confirmed empirically unprovable from outside the container: the same owning worker's own `ProxyServer._start_cleanup_thread` cleanup loop notices the missing key and calls `extend_ownership()`, re-`SET NX`-ing the identical worker id well under a second later every run (measured at ≤500ms), because that loop is the only code path with a local `StreamManager` for the channel; a follower worker never contends because `stream_ts` only lets a worker attempt ownership when channel metadata is absent too, which a bare owner-key delete does not cause — so no black-box HTTP/Redis manipulation can land a second `SET NX` in the sub-second gap. See G4 task-12 report for the full trace. | G4 | todo |
| Output | /output/m3u parses and every URL streams | G5 | todo |
| Output | /output/epg is valid XMLTV | G5 | todo |
| Output | HDHomeRun discovery and lineup | G5 | todo |
| Output | Xtream player_api actions | G5 | todo |
| Output | Catch-up / timeshift URLs | G5 | todo |
| Output | Authorization matrix by user_level | G5 | todo |
| Output | hide_adult_content across all listing paths | G5 | todo |
| Accounts | Token refresh with a deleted user's token 500s instead of 401 ([#12](https://github.com/D10Scot/Dispatcharr/issues/12)); needs a `test.fail()`, and pinning it costs one login | G5 | known-bug |
| Frontend | Guide grid renders and navigates | G6 | todo |
| Frontend | DVR: schedule, list, cancel a recording | G6 | todo |
| Frontend | Users: create, edit, delete | G6 | todo |
| Frontend | Settings: change and persist | G6 | todo |
| Frontend | Plugins: list, enable, configure | G6 | todo |
| Frontend | Stats page renders live data | G6 | todo |
| Frontend | Connect: webhook CRUD | G6 | todo |
| Frontend | Logos: upload and browse | G6 | todo |
| Frontend | Backups: create and restore | G6 | todo |
| Lifecycle | Upgrade from previous release (migrations) | G7 | todo |
| Lifecycle | Restart preserves channels and settings | G7 | todo |
| Lifecycle | PUID/PGID honoured | G7 | todo |
| Lifecycle | TLS Postgres connection | G7 | todo |

The ten G1 rows above are covered by these specs (the two seeding rows
share one file, as do the two principal rows):

- `e2e/tests/pristine/first-run-setup-and-login.spec.ts`
- `e2e/tests/seeded/authenticated-session.spec.ts`
- `e2e/tests/seeded/api-fixture.spec.ts`
- `e2e/tests/seeded/seed-fixture.spec.ts`
- `e2e/tests/seeded/authorization.spec.ts`
- `e2e/tests/seeded/async-wait.spec.ts`
- `e2e/tests/seeded/ws-fixture.spec.ts`
- `e2e/tests/streaming/stream-client.spec.ts`
- `e2e/tests/streaming/stalled-stream.spec.ts` (regression: read ordering
  across `collectFor` → `readPackets` on a stalled stream)

The four G2 rows above are covered by `e2e-upstream`'s own vitest suite (the
provider and its faults) plus:

- `e2e/tests/seeded/upstream-ingest.spec.ts` (ingest plumbing proof)
- `e2e/tests/streaming/upstream-through-proxy.spec.ts` (stream-through
  plumbing proof)
- `e2e/tests/streaming/upstream-to-control.spec.ts` (`toControl` conversion)
- `e2e/tests/streaming/stream-client.spec.ts` and
  `e2e/tests/streaming/stalled-stream.spec.ts`, both re-pointed at the
  provider (`e2e/support/static-upstream.ts` is deleted)

**G3 and G4 are now unblocked.** Both can seed a scenario, ingest a playlist
or stream through the provider, and drive any of the eight faults, using only
`e2e/fixtures/upstream.ts` and the fault catalogue documented in
`e2e-upstream/README.md` — without reading `e2e-upstream/src/`.
