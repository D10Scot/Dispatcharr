# E2E Coverage Inventory

The shared worklist for all ten goals. **Update this in the same PR as the
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
| Upstream | Fake provider speaks Xtream Codes: `player_api.php` auth envelope and the seven catalogue actions `core/xtream_codes.Client` calls | G8 | todo |
| Upstream | Fake provider serves a finite VOD asset with `Content-Length`, `Accept-Ranges`, 206 + `Content-Range` and 416 | G8 | todo |
| Upstream | Fake provider answers both catch-up layouts and records the credentials, stream id, start timestamp and duration it was asked for | G8 | todo |
| Upstream | Four new faults: `xc-auth-envelope`, `no-tv-archive`, `catchup-layout-404`, `range-unsupported` | G8 | todo |
| Upstream | Plumbing proof: XC account ingest → declared live streams appear | G8 | todo |
| Upstream | Plumbing proof: VOD catalogue ingest → `Movie`, `Series` and `Episode` rows appear | G8 | todo |
| Upstream | Plumbing proof: one VOD byte read through `/proxy/vod/` | G8 | todo |
| Upstream | Plumbing proof: a catch-up URL reaches the provider in each layout | G8 | todo |
| Upstream | Plumbing proof: the candidate cascade falls back when one layout 404s | G8 | todo |
| Upstream | **Gap:** the fake archive is not time-addressable — it serves the same looping TS whatever `start` it is asked for. Nothing proves Dispatcharr seeks to the right moment, only that it asks for the right one. Owned by G10, which must say so in every row it writes | G8 | todo |
| VOD | Catalogue ingest: categories, movies and series land as `VODCategory`, `Movie`, `Series` and their `M3U*Relation` rows | G9 | todo |
| VOD | Category gating: `M3UVODCategoryRelation.enabled`, `auto_enable_new_groups_vod`/`_series`, and the `Uncategorized` fallback | G9 | todo |
| VOD | Episode ingest on demand via `GET /api/vod/series/<pk>/provider-info/`, for both the object-keyed and array-keyed `episodes` shapes | G9 | todo |
| VOD | Advanced movie data: `get_vod_info` merges into `Movie` and `M3UMovieRelation.custom_properties` without clobbering list-sync fields | G9 | todo |
| VOD | XC VOD and series actions against a real catalogue (G5 covers only the empty-catalogue shape, and `get_vod_info`/`get_series_info` only as `404`) | G9 | todo |
| VOD | `vod_proxy` streaming path: session mint, path redirect, byte delivery, `Content-Length` and `Accept-Ranges` | G9 | todo |
| VOD | `vod_proxy` Range and seek: a mid-file Range yields 206 with the correct `Content-Range` against the full file size | G9 | todo |
| VOD | `vod_proxy` against a provider that will not serve 206 (`range-unsupported` fault) | G9 | todo |
| VOD | Root XC playback routes `/movie/<user>/<pass>/<id>.<ext>` and `/series/<user>/<pass>/<id>.<ext>` | G9 | todo |
| VOD | **Characterization:** `Client.authenticate()` checks only that `user_info` is present — never `auth` or `status` — so a provider answering `200` with `auth: 0` is treated as authenticated (`xc-auth-envelope` fault). G9 decides whether to file it | G9 | todo |
| Catch-up | XC live ingest fields catch-up depends on: `tv_archive`/`tv_archive_duration` → `Stream.is_catchup`/`catchup_days` → `Channel.is_catchup` via `rollup_channel_catchup_fields`, including its self-heal pass | G10 | todo |
| Catch-up | Redirect mode: `/timeshift/...` and `/streaming/timeshift.php` each 302 in the layout the client used; `/proxy/catchup/<uuid>` defaults to PATH | G10 | todo |
| Catch-up | Proxy mode end to end: bytes reach the client and the provider recorded the credentials, stream id, converted start timestamp and padded duration | G10 | todo |
| Catch-up | The seven-candidate cascade: PATH shapes first, QUERY last, and the winning index cached per account (`_get_cached_format_index`) reorders the next attempt | G10 | todo |
| Catch-up | Decisive failures (401/403/406) stop the cascade for that account; a soft 404 or a 200 with no TS sync does not | G10 | todo |
| Catch-up | `server_info.timezone` from the account profile drives `convert_timestamp_to_provider_tz` | G10 | todo |
| Catch-up | **Gap:** the generated M3U emits no `catchup=`/`catchup-source=` attribute. `#EXTINF` carries `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally `tvc-guide-stationid`, and `group-title` — nothing else. Catch-up is advertised only through the XC `tv_archive`/`tv_archive_duration` fields, so an M3U-only client can never discover it. G10 decides whether that is a defect to file or intended | G10 | todo |
| Frontend | Guide grid renders and navigates | G6 | done |
| Frontend | DVR: schedule, list, cancel a recording | G6 | done |
| Frontend | **Gap:** scheduling a recording creates three objects — the `Recording` row, a django-celery-beat `PeriodicTask` named `dvr-recording-<id>`, and a `ClockedSchedule` — with no DB cascade between them; `PeriodicTask` is linked to `Recording` only by that name string, written into `Recording.task_id` by `schedule_task_on_save` (`apps/channels/signals.py:361-363`/`367-369`). The sole teardown mechanism is the `post_delete` receiver `revoke_task_on_delete` (`apps/channels/signals.py:388-390`) calling `revoke_task()` (`apps/channels/signals.py:289-310`), and it hinges on `task_id` having been populated. `RecordingViewSet.destroy` (`apps/channels/api_views.py:3776`) **does** override `destroy`, and reaches the signal through its `super().destroy()` call (`:3846`) — so the teardown fires for both the UI cancel and `dvr.spec.ts`'s cleanup DELETE, but by a longer route than a default `ModelViewSet`. That override also does three further things the test never observes: it deletes the recording's file(s) from disk, emits a `recording_cancelled` WebSocket event, and backgrounds the DVR-client teardown in a thread. The gap: the test can only assert the `Recording` row is gone, because neither `PeriodicTask` nor `ClockedSchedule` has a REST surface, and none of the three side effects above has one either. If the `task_id` write were ever lost, the `PeriodicTask` would orphan invisibly — no API any test polls would show it — and eventually fire against a deleted recording | G6 | done |
| Frontend | Users: create, edit, delete | G6 | done |
| Frontend | Settings: change and persist | G6 | done |
| Frontend | Plugins: list, enable, configure | G6 | done |
| Frontend | **Observation:** `plugins.spec.ts`'s comment on the plugin-visibility mechanism (`.reload_token` mtime, no restart needed) is a claim the assertions alone don't prove — a uWSGI respawn would satisfy them identically. Out-of-band check during a mutation run: `docker logs` showed no uWSGI respawn across the import, only `apps.plugins.loader` discovery lines | G6 | done |
| Frontend | Stats page renders live data | G6 | done |
| Frontend | Connect: webhook CRUD | G6 | done |
| Frontend | Logos: upload and browse | G6 | done |
| Frontend | **Gap:** `apps.channels.Logo.url` is a discriminator-free polymorphic field — a remote URL or, for a local upload, a raw server-side filesystem path (`/data/logos/<name>`) — and every consumer tells the two apart with its own copy-pasted `startsWith('http')`/`startsWith(('http://', 'https://'))` check: `apps/output/views.py:290` (`tvg-logo`), the XC `stream_icon` field, `LogosTable.jsx`'s URL column. All four agree today, so this is not filed as a defect — but it is the same shape as the eight-site channel-authorization filter in the root `CLAUDE.md`'s defect list, where the eighth copy was wrong. A fifth site that forgets the check would not fail cleanly either: a bare `url` handed to an HTTP client collides with the XC live-stream route (`<str:username>/<str:password>/<str:channel_id>`, three path segments matches `/data/logos/<file>` exactly) and 404s from an unrelated "no such user" lookup, which sends whoever debugs it looking in the wrong subsystem entirely. Confirmed empirically, not assumed, by G6 task 10 (`logos.spec.ts`) | G6 | done |
| Frontend | Backups: create and validate the archive | G6 | done |
| Lifecycle | Backups: restore — split out of G6's Backups row. Restoring on a shared instance replaces the database under every parallel worker mid-run and under every other project sharing the container locally, so it needs an instance of its own; G7 already stands one up per scenario | G7 | todo |
| Frontend | **Gap:** development-mode-only diagnostics — not just React's key-prop warning, but anything gated behind `__DEV__`/`import.meta.env.DEV` (Mantine's own dev checks, React Router's, etc.) — are invisible to the `pageErrors` fixture in this harness. `docker/Dockerfile:22`'s `npm run build`, which is what `scripts/e2e_up.sh:138` builds the e2e image from, is a Vite production build: it resolves the production `react/jsx-runtime` with `NODE_ENV="production"`, so dev-only checks (React's `validateChildKeys` among them) are compiled out of the bundle entirely, not merely suppressed at runtime. Production error reporting is unaffected — `pageerror` and `console.error` from real app/library code still reach the collector, so this is not a hole in error detection generally, only in this one class of dev-time-only diagnostic. A later task that needs to assert a dev-only diagnostic must verify it against a development build directly, or assert the underlying behaviour rather than the diagnostic message. First hit: G6 task 9 (`connect.spec.ts`), trying to reproduce [#62](https://github.com/D10Scot/Dispatcharr/issues/62) | G6 | done |
| Lifecycle | Upgrade from previous release (migrations) | G7 | done |
| Lifecycle | Restart preserves channels and settings | G7 | done |
| Lifecycle | PUID/PGID honoured | G7 | done |
| Lifecycle | TLS Postgres connection | G7 | done |

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

The nine `done` G6 rows above are covered by these specs. The nine render
checks live in one file, generated from the surface table in
`e2e/tests/frontend/helpers.ts`; each surface's write or read proof is its own
file, and **that one-file-per-surface split is load-bearing** — the `frontend`
project runs two workers with file-level parallelism, which is what confines
backup creation and plugin installation to one worker each:

- `e2e/tests/frontend/render.spec.ts` — all nine surfaces mount, throw
  nothing, log no error and issue no request the server refuses
- `e2e/tests/frontend/guide.spec.ts` — Guide grid populated from the channel
  API, reached by clicking the sidebar
- `e2e/tests/frontend/dvr.spec.ts` — DVR schedule, list, cancel
- `e2e/tests/frontend/users.spec.ts` — Users create, edit, delete
- `e2e/tests/frontend/settings.spec.ts` — Settings change and persist, via a
  User-Agent row (a global `CoreSettings` change belongs to `pristine`)
- `e2e/tests/frontend/plugins.spec.ts` — Plugins import, enable, configure
- `e2e/tests/frontend/stats.spec.ts` — Stats renders a live connection
- `e2e/tests/frontend/connect.spec.ts` — Connect webhook CRUD
- `e2e/tests/frontend/logos.spec.ts` — Logos upload and browse
- `e2e/tests/frontend/backups.spec.ts` — Backups create and validate

Two further files in the same directory run but are not tied to a coverage
row above, the same way `streaming-greybox/quarantine.spec.ts` isn't tied to
a G4 row: `e2e/tests/frontend/pageerrors-enforcement.spec.ts` is a meta-test
that source-scans every `test()` under `tests/frontend/` for a destructured
`pageErrors` parameter, and the zip-builder unit test at the top of
`plugins.spec.ts` checks `buildPluginZip`'s output is a readable archive
before any test relies on it.

Gap: the Guide row proves the grid is populated from
`/api/channels/channels/`, not from real EPG programme data. Asserting a
programme in the grid needs an ingested XMLTV source, which is G3's path;
recording a programme from the Guide needs the same. Deferred rather than
attempted here.

The four G7 rows above are covered by:

- `e2e/tests/lifecycle/upgrade-migrations.spec.ts` (upgrade from previous
  release)
- `e2e/tests/lifecycle/restart-persistence.spec.ts` (restart preserves
  channels and settings)
- `docker/tests/test-puid-pgid.sh`, run by
  `.github/workflows/lifecycle-tests.yml` (PUID/PGID honoured)
- `docker/tests/test-tls-postgres.sh`, run by
  `.github/workflows/lifecycle-tests.yml` (TLS Postgres connection)

The PUID/PGID and TLS Postgres rows are wired but have not yet executed a
full run in CI: `lifecycle-tests.yml` is not on the default branch yet, so it
has not run and could not have. One scenario (`test-puid-pgid.sh`'s
`puid_test_fresh_def`) has been run by hand and passed, 13/13 assertions,
exit 0; `test-tls-postgres.sh` has not been run at all. If the first
post-merge run of `lifecycle-tests.yml` is red, these two rows come back to
`todo`.
