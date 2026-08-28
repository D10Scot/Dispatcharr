# E2E Coverage Inventory

The shared worklist for all eight goals. **Update this in the same PR as the
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
| Streaming | Single client receives aligned TS | G4 | done |
| Streaming | N clients share one upstream | G4 | done |
| Streaming | Mid-stream switch does not disturb clients | G4 | done |
| Streaming | Failover: dead air | G4 | done |
| Streaming | Failover: connect failure | G4 | done |
| Streaming | Failover: buffering (ffmpeg only) | G4 | done |
| Streaming | Client teardown releases the upstream | G4 | done |
| Streaming | Stream Profile: Redirect | G4 | done |
| Streaming | Stream Profile: Proxy | G4 | done |
| Streaming | Stream Profile: FFmpeg | G4 | done |
| Streaming | Output Profile shared per (channel, profile) | G4 | done |
| Streaming | Ownership lease is fenced against a second concurrent owner — attempted by deleting `live:channel:{uuid}:owner` under a running Proxy-profile stream and polling for a second worker to claim it; confirmed empirically unprovable from outside the container: the same owning worker's own `ProxyServer._start_cleanup_thread` cleanup loop notices the missing key and calls `extend_ownership()`, re-`SET NX`-ing the identical worker id well under a second later every run (measured at ≤500ms), because that loop is the only code path with a local `StreamManager` for the channel; a follower worker never contends because `stream_ts` only lets a worker attempt ownership when channel metadata is absent too, which a bare owner-key delete does not cause — so no black-box HTTP/Redis manipulation can land a second `SET NX` in the sub-second gap. The untried lever is co-expiring `live:channel:{uuid}:metadata` with the owner key, which is what would open the metadata-gated follower path in `stream_ts`; that is a larger provocation than this row's brief allowed and needs its own scoping. See G4 task-12 report for the full trace. | G4 | todo |
| Output | /output/m3u parses, every URL is well-formed, and one is streamed end to end | G5 | todo |
| Output | /output/m3u/&lt;profile_name&gt; scopes to Channel Profile membership | G5 | todo |
| Output | /output/epg is valid XMLTV and carries programmes for the seeded channels | G5 | todo |
| Output | HDHomeRun discovery, device XML, lineup and lineup status | G5 | todo |
| Output | Xtream authentication handshake (user_info / server_info envelope) | G5 | todo |
| Output | Xtream live actions: get_live_categories, get_live_streams, get_short_epg, get_simple_data_table | G5 | todo |
| Output | Xtream VOD and series actions answer an empty catalogue without erroring | G5 | todo |
| Output | Xtream get.php and xmltv.php at the site root | G5 | todo |
| Output | Authorization matrix by user_level — Xtream only, the one output surface with a principal | G5 | todo |
| Output | hide_adult_content across the Xtream listing paths | G5 | todo |
| Output | /output/m3u, /output/epg and the HDHR lineup are unauthenticated by design, gated only by the M3U_EPG network ACL | G5 | todo |
| Accounts | Token refresh with a deleted user's token 500s instead of 401 ([#12](https://github.com/D10Scot/Dispatcharr/issues/12)); needs a `test.fail()`, and pinning it costs one login | G5 | known-bug |
| Output | XC catch-up / timeshift URLs end to end — moved here from G5. `catchup_proxy` builds its upstream URL from the account's Xtream catch-up template (`get_transformed_credentials` → `build_timeshift_candidate_urls`), so it has nothing to point at until the fake provider speaks XC | G8 | todo |
| Output | XC VOD and series actions against a real catalogue (G5 covers only the empty-catalogue shape) | G8 | todo |
| Upstream | Fake provider speaks Xtream Codes: `player_api.php`, VOD/series catalogue, catch-up URLs | G8 | todo |
| Output | **Gap:** the generated M3U emits no `catchup=`/`catchup-source=` attributes. `#EXTINF` carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally `tvc-guide-stationid`, and `group-title` — nothing else. Catch-up is advertised to clients only through the XC `tv_archive` / `tv_archive_duration` fields on `_xc_channel_entry`, so an M3U-only client can never discover it. Decide in G8 whether that is a defect to file or intended | G8 | todo |
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
- `e2e/tests/streaming/single-client.spec.ts` (stream-through plumbing proof;
  supersedes the former `upstream-through-proxy.spec.ts`, deleted in G4 — the
  same path through Dispatcharr, plus contiguity, a polled status read and
  the provider cross-check; see the G4 block below)
- `e2e/tests/streaming/upstream-to-control.spec.ts` (`toControl` conversion)
- `e2e/tests/streaming/stream-client.spec.ts` and
  `e2e/tests/streaming/stalled-stream.spec.ts`, both re-pointed at the
  provider (`e2e/support/static-upstream.ts` is deleted)

**G3 and G4 are now unblocked.** Both can seed a scenario, ingest a playlist
or stream through the provider, and drive any of the eight faults, using only
`e2e/fixtures/upstream.ts` and the fault catalogue documented in
`e2e-upstream/README.md` — without reading `e2e-upstream/src/`.

The eleven `done` G4 rows above are covered by these specs (the two
`shared-upstream.spec.ts` rows share one file; the three-way Stream Profile
split is across two — Proxy in `single-client.spec.ts`, Redirect and FFmpeg
together in `stream-profiles.spec.ts`):

- `e2e/tests/streaming/single-client.spec.ts` — single client receives aligned
  TS, and Stream Profile: Proxy (the test drives the Proxy profile directly)
- `e2e/tests/streaming/shared-upstream.spec.ts` — N clients share one
  upstream, and client teardown releases the upstream (one test each)
- `e2e/tests/streaming/stream-profiles.spec.ts` — Stream Profile: Redirect,
  and Stream Profile: FFmpeg (one test each)
- `e2e/tests/streaming-failover/mid-stream-switch.spec.ts` — mid-stream switch
  does not disturb clients
- `e2e/tests/streaming-failover/failover-dead-air.spec.ts` — failover: dead
  air
- `e2e/tests/streaming-failover/failover-connect-failure.spec.ts` — failover:
  connect failure
- `e2e/tests/streaming-failover/failover-buffering.spec.ts` — failover:
  buffering (ffmpeg only)
- `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts` — Output
  Profile shared per (channel, profile), verified both by the shared owner
  key and by counting live ffmpeg processes directly

The twelfth G4 row, the ownership-lease fencing flagship, stays `todo`: it
was built, shown to pass for a reason that says nothing about the defect
(the true owner's own cleanup loop re-acquires the key faster than any
black-box client can act), and deleted rather than kept as a false green. See
the row itself for the full trace and `e2e/tests/streaming-greybox/` history
(commit `37edae89`) for the removed spec and allowlist entry.
