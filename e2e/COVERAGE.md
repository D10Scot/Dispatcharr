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

G2 (the fake upstream provider that replaces `e2e/support/static-upstream.ts`)
adds no rows here — it is harness infrastructure, not a covered flow.
