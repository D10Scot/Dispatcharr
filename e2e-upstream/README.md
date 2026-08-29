# e2e-upstream

A controllable fake IPTV provider for the E2E suite: an M3U playlist, an XMLTV EPG, a paced
looping MPEG-TS stream, and a control API that flips twelve fault modes mid-test.

**This is test infrastructure.** It is never built into the product image, never shipped, and has
no code path a released Dispatcharr instance can reach. It exists so `e2e/` tests can say "the
provider does X, now assert Dispatcharr does Y" without a real IPTV source.

## Running it locally

`./scripts/e2e_up.sh` (run from the repo root) builds and starts it alongside the Dispatcharr
container, on the shared `dispatcharr-e2e-net` Docker network, and waits for it to answer before
starting Dispatcharr. Its control port is published at `http://127.0.0.1:9402`.

```bash
curl http://127.0.0.1:9402/scenarios   # lists live scenarios; empty at startup
```

`./scripts/e2e_up.sh --stop` / `--reset` / `--down` cover this container the same way they cover
the Dispatcharr one. Unlike the Dispatcharr image, this one is rebuilt on **every** invocation by
default — it's small and fast to build, so there's no reason to risk serving a stale routes table
— and the container is recreated automatically whenever that rebuild actually changes the image,
so a local edit to `src/` always reaches the running container on the next `e2e_up.sh`. CI sets
`DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1` to opt out of the rebuild and run the exact image the
`build` job produced and saved into the shared artifact — see `.github/workflows/e2e-tests.yml`.

You will not normally talk to it directly: `e2e/fixtures/upstream.ts` is the sanctioned client.
This document exists for when the fixture's behaviour needs explaining, not as a replacement for
it.

## Two origins, never conflated

Every scenario yields two base URLs. There is deliberately no bare `url`:

| Field | Value | Used by |
|---|---|---|
| `internal` | `http://e2e-upstream:8080/s/<id>` | URLs handed to Dispatcharr (it resolves this on the shared Docker network) |
| `control` | `http://127.0.0.1:9402/s/<id>` | Control calls made from the Playwright host |

They exist because Dispatcharr and Playwright sit on opposite sides of the container boundary:
`e2e-upstream` resolves only inside the Docker network, and `127.0.0.1:9402` resolves only on the
host. Handing `control` to Dispatcharr would have it try to resolve itself; handing `internal` to
a `fetch` running on the host is a DNS failure.

`upstream.toControl(url)` is the **only** sanctioned way to turn one into the other — it rewrites
the origin and nothing else, and it's what you reach for when the product hands you back an
`internal` URL (for example, in a `Location` header) that you now need to fetch from the test. Do
not hand-roll a string replace at a call site; if `toControl` can't express what you need, that's
a fixture gap, not a reason to bypass it.

If a `fetch` from the host tries to resolve `e2e-upstream` and fails, the fixture throws a named
error saying so, rather than a bare DNS failure — it's a sign you meant `toControl` or
`redirect: 'manual'` on `streamClient.open()`.

## Control API

All responses are synchronous and echo effective state — a fault that reached nobody says so
immediately, never a 300s timeout.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/scenarios` | Create. Body declares catalogue, optional credentials, `maxConnections` (default unlimited), `rate` (default 1). Returns **201** with the whole resolved scenario, not just the four keys you sent: `{ id, internal, control, channels }` plus the **resolved catalogue** — `vod`, `series`, the category lists, and any defaults the parser filled in. That echo is what makes the count form usable: declare `series: 2` and the response carries the generated series and **episode** ids, which you need for `/series/.../<id>.<ext>` and cannot construct yourself. `UpstreamScenario` (`e2e/fixtures/upstream.ts`) types those fields, so they are reachable without opening `src/` |
| `GET` | `/scenarios` | List live scenarios. Also the readiness endpoint `e2e_up.sh` waits on |
| `DELETE` | `/scenarios/<id>` | Optional explicit close |
| `POST` | `/s/<id>/fault` | Apply or clear a fault. Body takes an optional `channel` filter and per-fault parameters. Returns `{ fault, active, appliedTo }` |
| `POST` | `/s/<id>/rate` | Set the pacing multiplier on a live scenario |
| `GET` | `/s/<id>/log` | Request/connection history: method, hits, opens/closes with byte counts and durations, faults applied |
| `GET` | `/s/<id>/connections` | Live connection count and the accounting behind `maxConnections` |

Provider-facing endpoints — the ones a Dispatcharr `M3UAccount`/`EPGSource`/`Stream` points at,
not ones a test calls directly: `/s/<id>/playlist.m3u`, `/s/<id>/epg.xml`,
`/s/<id>/stream/<channelId>.ts`.

**The six XC routes (G8) are provider-facing the same way, each built by a specific product
symbol** — none of the six is a URL a test constructs by hand:

| XC route | Built by |
|---|---|
| `/player_api.php` (no-`action` handshake, plus the `action=get_live_categories`\|`get_live_streams`\|`get_vod_categories`\|`get_vod_streams`\|`get_series_categories`\|`get_series`\|`get_vod_info`\|`get_series_info` actions) | `core.xtream_codes.Client.authenticate()` and its matching `get_*` methods |
| `/live/<user>/<pass>/<id>.ts` | `Client.get_stream_url(stream_id)` |
| `/movie/<user>/<pass>/<id>.<ext>` | `M3UMovieRelation.get_stream_url()` (`apps/vod/models.py`) |
| `/series/<user>/<pass>/<id>.<ext>` — `<id>` is an **episode** id (`series[].seasons[].episodes[].id`), never the series id `get_series_info` uses | `M3UEpisodeRelation.get_stream_url()` (`apps/vod/models.py`) |
| `/timeshift/<user>/<pass>/<duration>/<start>/<id>.ts` (PATH layout) | `apps.timeshift.helpers.build_timeshift_url_format_b()` |
| `/streaming/timeshift.php?...` (QUERY layout) | `apps.timeshift.helpers.build_timeshift_url_format_a()` |

**`get_vod_info`/`get_series_info` and unknown actions.** `get_vod_info`/`get_series_info` answer
`200` with a rendered payload for a `vod_id`/`series_id` the scenario declared, and `404` with a
`{ error }` body otherwise — the same door as the `/movie/`/`/series/` streaming routes, not a
shape error, since `Client.get_vod_info`/`get_series_info` require a dict either way. An
unrecognised `action` on `player_api.php` gets a `400` naming the full set of valid actions plus the
no-`action` handshake (`src/xc/router.ts:202-226`).

### XC scenario fields

`POST /scenarios` also takes (G8): `xc`, `liveCategories`, `vodCategories`, `seriesCategories`,
`vod`, `series`, `account`.

`xc: true` is the discriminant that unlocks the six routes above — a scenario that doesn't set it
404s any of them, naming the missing `xc: true`. It **requires both `username` and `password`**,
not just `username`: omitting `username` would let the non-XC routes' own `credentialsMatch`
(`server.ts`) treat "no username declared" as "accept any credentials", which would make
`auth-failure`/`xc-auth-envelope` pass vacuously. **Omitting** `password` is caught the same way —
`parseScenarioRequest`'s door check (`scenario.ts:591`) throws on `request.password === undefined`
— but that check only guards omission, not falsiness: an explicit **empty-string** `password: ''`
is not `undefined`, so it passes the door and the scenario is created successfully, then is
unservable the moment a real client streams from it, because `xcCredentialsMatch` compares it
against `scenario.password ?? ''` while the `/live/` route's `[^/]+` path segment can never match
an empty string. This is a known provider defect, not intended behaviour — see the known-defect row
in `COVERAGE.md`. `seed.xcAccount` is deliberately stricter than this door and throws on any falsy
`password`, empty string included, so a test built on it is protected in practice; a test that
bypasses `seed.xcAccount` is not.

- `liveCategories` / `vodCategories` / `seriesCategories` — arrays of `{ id, name }`. Each defaults
  to one entry (`{ id: 1, name: 'E2E' }`, `'E2E Movies'`, `'E2E Series'`) when omitted. A `channels[]`
  entry's own `categoryId` defaults to `liveCategories[0].id` when omitted (`scenario.ts:612-616`).
- `vod` / `series` — a count (materialising that many default-named entries) or an explicit array
  of movie/series specs. Default to 1 of each when `xc: true` and neither is declared, and to 0 for
  a non-XC scenario — there's no route that could serve a catalogue. The `MovieSpec`/`SeriesSpec`
  field sets (`id`, `name`, `year`, `categoryId`, `containerExtension`, `tmdbId`, `imdbId` for a
  movie; `id`, `name`, `categoryId`, `seasons[].number`, `seasons[].episodes[]` for a series) are
  mirrored with docstrings as `UpstreamMovie`/`UpstreamSeries` in `e2e/fixtures/types.ts:349-380` —
  read them there rather than `src/scenario.ts` when a test needs an explicit spec.
- `account` — `{ userInfo?, serverInfo? }`, raw overrides merged last into the `player_api.php`
  handshake's envelope. Untyped beyond `Record<string, unknown>` on purpose: a test that wants a
  garbage `exp_date` or `timezone` on the envelope needs to be able to send exactly that.

G2 shipped exactly two plumbing proofs, and both cover the M3U/streaming path
(`e2e/tests/seeded/upstream-ingest.spec.ts`,
`e2e/tests/streaming/single-client.spec.ts`, which superseded G2's original
`upstream-through-proxy.spec.ts` when G4 asserted a strict superset of it).
**Nothing has yet proved `/s/<id>/epg.xml`
against a real Dispatcharr `EPGSource` refresh** — `renderXmltv`, `epgUrl()` and its
`application/xml` content type are exercised only by this package's own vitest suite. If you're
writing G3's "EPG source → refresh → programme data" row, expect to be the first person to point
a live `EPGSource` at this endpoint.

### Scenario defaults and credentials — read before asserting on names

**The default catalogue is identical across every scenario.** With no `channels` override,
channel `1` is always `Fake Channel 1` / `fake-1.e2e`. `seeded` runs 4 workers in parallel, so
asserting on or filtering by those default names will alias another test's scenario. Pass explicit
channel names — `seed.generatedName(...)` is what the ingest proof uses — whenever a test needs to
find its own channel rather than someone else's.

**The same hazard applies to movie titles, series names and category names (G8), and it is worse
there than for channels.** With no `vod`/`series` override, movie `1` is always `Fake Movie 1` and
series `1` is always `Fake Series 1`; with no category override, the default live/VOD/series
categories are always named `E2E` / `E2E Movies` / `E2E Series`. For a channel, aliasing only risks
confusing one test's assertions with another's — every scenario's channels are that scenario's own,
never shared. VOD and category rows are not scenario-scoped in the product: `VODCategory` is
`unique_together = [('name', 'category_type')]` **globally**, not per account
(`apps/vod/models.py`), and `apps/vod/tasks.py` matches an incoming `Movie`/`Series` across **every
account** by TMDB id first, then IMDB id, then `(name, year)` — so two workers ingesting the
default catalogue at once don't just alias each other's assertions, they ingest into the *same*
`VODCategory`/`Movie`/`Series` row. Pass explicit names — and, for a movie without a TMDB/IMDB id, a
distinguishing `year` — whenever a test needs a row of its own.

**Scenario credentials are not secret from the control API or the test report.** `POST`/`GET
/scenarios` echo `password` back in the response, and every `UpstreamScenario` carries
`credentialQuery` (the same credentials, pre-formatted as a query string) so a test can build a
provider-facing URL. That's fine while credentials are invented per test and thrown away with the
scenario — but a test that attaches a scenario object to its own report output, or logs it,
publishes them the same way `attachLogs` publishes the request log. Separately: Dispatcharr itself
is known to log full provider URLs — including any `?password=` — at INFO (see the credential-
logging entry in the root `CLAUDE.md`), and `.github/workflows/e2e-tests.yml`'s failure step prints
`docker logs dispatcharr-e2e` straight into the CI log. Neither is a problem today, because these
are throwaway per-test credentials with no value outside the run — but a G5 test that starts
reusing a fixed, meaningful credential across runs should not assume either path is private.

### HEAD and probe connections

Dispatcharr's Redirect stream profile probes a stream URL before redirecting a client to it
(`validate_stream_url`). The provider answers a `HEAD` with `200`, `Content-Type: video/mp2t` and
no body, and does **not** count a `HEAD` toward `maxConnections`. The probe's method is recorded
in the log, so a probe is distinguishable from a real client there.

That validation issues a **GET**, not just a HEAD, as a fallback, and the product never explicitly
closes it. That GET does count toward `maxConnections` and can transiently hold a slot — but only
on a **Redirect**-profile channel: `validate_stream_url` is reached only from
`if stream_profile.is_redirect():` in `apps/proxy/live_proxy/views.py`, so Proxy and ffmpeg
profiles never issue it at all. A Proxy stream produces exactly one `request GET → open → close`
in the provider log; only Redirect can show the transient extra slot. Don't generalize the hazard
to every profile — it is Redirect-specific.

## Fault catalogue

`appliedTo` in the response is how many *live* connections the fault reached — not whether the
fault is now armed. Nine of the twelve faults can only affect the **next** request, because a live
response has already sent its headers by the time the fault is applied; `appliedTo: 0` is the
correct, expected result for those, not a sign nothing happened. "Arm `not-found` for the next
reconnect" is a normal test.

| Fault | Applies to | Behaviour | Drives |
|---|---|---|---|
| `dead-air` | live + new | Connection stays open, no bytes written | Dead-air failover (>10 s, 3× at 5 s) |
| `slow-trickle` | live + new | Pacing multiplier < 1 | Buffering detector — **ffmpeg profiles only**, and only arms if the rate is set *before* ffmpeg starts: `speed=` is cumulative since process start, so a trickle applied mid-stream takes ~55 s to arm and dead-air wins at ~25 s |
| `disconnect` | live | `{ clean, afterBytes? }`; default abrupt | Both reconnect branches (`RequestException` vs `"HTTP stream ended"`) |
| `not-found` | new only (`appliedTo: 0`) | 404 on the requested endpoint | Connect-failure trigger; refresh error handling |
| `auth-failure` | new only (`appliedTo: 0`) | Credentials that were valid start being rejected | Mid-refresh credential expiry |
| `connection-limit` | new only (`appliedTo: 0`) | Real per-scenario accounting; N+1th rejected, readmitted on close | Provider-slot semantics; `max_streams` disagreement |
| `redirect-chain` | new only (`appliedTo: 0`) | 302 chain of declared depth before the payload | The Redirect stream profile |
| `non-ts-bytes` | new only (`appliedTo: 0`) | 200 with an HTML error page instead of TS | `buffer.py`'s realignment defence |
| `xc-auth-envelope` | new only (`appliedTo: 0`) | `player_api.php`'s no-`action` handshake answers 200 with `user_info.auth: 0`, `status: 'Disabled'`, instead of a 401 | `Client.authenticate()` only checks `user_info` is truthy — never reads `auth` — so this is the shape the product mistakes for a successful login |
| `no-tv-archive` | new only (`appliedTo: 0`) | `get_live_streams` omits `tv_archive`/`tv_archive_duration` for the channel(s) it reaches | Whether Dispatcharr offers catch-up for a channel at all |
| `catchup-layout-404` | new only (`appliedTo: 0`) | 404s catch-up requests on one named layout (`{ layout: 'path' \| 'query' }`) while leaving the other layout serving | The seven-candidate `build_timeshift_candidate_urls` cascade — the layout most likely to be wrong |
| `range-unsupported` | new only (`appliedTo: 0`) | VOD (`/movie\|series/`) answers 200 with the whole asset and no `Accept-Ranges`, ignoring any `Range` header | `multi_worker_connection_manager`'s no-seek-metadata fallback path |

`appliedTo: 0` is correct for the nine "new only" rows above — they can only take effect on the
next connection attempt, never on one already streaming. This is not a partial failure of the
control API; it's the whole of what those faults can do.

**The four XC faults above are not scoped like the pre-existing eight.** `xc-auth-envelope` is
always scenario-wide — the handshake it changes has no channel or VOD id to narrow to.
`no-tv-archive` and `catchup-layout-404` accept the usual `channel` filter (`catchup-layout-404`'s
channel is the catch-up stream id). `range-unsupported` is **scenario-wide only**: arming it with a
`channel` filter is rejected with a `400` at the control API (`parseFaultRequest`,
`src/faults.ts:107-111`, pinned by `test/faults.test.ts:344-346` and
`test/xc-faults.test.ts:233-235`), because a VOD id is not a channel id and there is nothing for it
to mean. `xc-auth-envelope` is rejected the same way, for the same reason.

**`catchup-layout-404` requires `{ layout: 'path' | 'query' }` when arming, but not when clearing.**
A layout-less arm would be indistinguishable from `not-found` and would block both catch-up layouts
at once, making the seven-candidate cascade unobservable — so arming without a valid `layout` is a
400. Clearing (`{ fault: 'catchup-layout-404', active: false }`) needs no `layout`: `isActive` alone
decides once the fault is off, so `clearFault(scenario, 'catchup-layout-404')`'s normal no-`layout`
call shape works.

**`xc-auth-envelope` always wins over a scenario's own `account.userInfo.auth`/`status` override.**
`renderAccountEnvelope` spreads `scenario.account.userInfo` last, so without special handling a
scenario declaring its own `auth` could silently defeat the fault. The fault's rendering applies
`auth: 0`/`status: 'Disabled'` strictly after the full envelope (scenario override included) is
built, not by racing it into the same object literal — see `renderDisabledAccountEnvelope` in
`src/xc/envelope.ts`.

**`auth-failure` and `xc-auth-envelope` compose on `player_api.php` only.** `auth-failure` is
checked first, ahead of the credential check, the same order the playlist and stream routes use;
`xc-auth-envelope` is checked only after a successful credential check, and only on the no-`action`
handshake. The `/live/`, `/timeshift/` and `/streaming/timeshift.php` routes already inherit
`not-found`/`auth-failure` for free, through the same `serveChannelStream` pipeline the plain
`/stream/<n>.ts` route uses. The `/movie/` and `/series/` VOD routes do **not** — they never reach
`serveChannelStream` — so `not-found`/`auth-failure` have no effect there, unchanged from before
this fault set existed.

An armed **`slow-trickle`** overrides the scenario's own rate for the connections it reaches.
Only `clearFault('slow-trickle')` hands control back to the scenario rate — a plain `rate()` call
while the trickle is armed changes the scenario default but does not clear the override.

**`disconnect`'s `afterBytes` is byte-exact on a draining client, and a lower bound on a
backpressured one.** When the client is keeping up, the stream is cut at exactly that many bytes,
mid-TS-packet if that's where it lands — deliberately, because that's what a real provider does
when it dies mid-write. When the client is behind and the socket is backpressured, a chunk already
queued before the cutoff is honored in full before the connection closes, so the client may see a
few more bytes than requested. Don't assert byte-exact cutoff under backpressure.

## Catch-up

Both catch-up routes serve the same paced TS loop as `/live/`, through the same
`serveChannelStream` pipeline (see `auth-failure`/`xc-auth-envelope` above) — they differ only in
how the request arrives:

- **PATH layout**: `GET /timeshift/<user>/<pass>/<durationMinutes>/<start>/<streamId>.ts`
- **QUERY layout**: `GET /streaming/timeshift.php?username=<user>&password=<pass>&stream=<streamId>&start=<start>&duration=<durationMinutes>`

`start` is accepted in the four timestamp shapes `build_timeshift_candidate_urls`
(`apps/timeshift/helpers.py`) actually emits across its seven candidates — one regex
(`e2e-upstream/src/xc/catchup.ts`) covers all four:

| Shape | Example |
|---|---|
| `%Y-%m-%d:%H-%M` | `2026-08-29:14-00` |
| `%Y-%m-%d_%H-%M` | `2026-08-29_14-00` |
| `%Y-%m-%d:%H:%M:%S` | `2026-08-29:14:00:00` |
| `%Y-%m-%d %H:%M:%S` (SQL) | `2026-08-29 14:00:00` |

A `start` that matches none of the four gets a 400 naming the accepted shapes; a `start` in one of
the four shapes but a channel id the scenario never declared gets a 404. Every request the provider
accepts or rejects is recorded in `GET /s/<id>/log`: `logRequest` writes `path` as
`url.pathname + url.search` (`src/server.ts:226`), which is the request's **whole** pathname,
including the `/s/<scenarioId>` prefix the router strips before matching — so a PATH-layout
request's log entry carries `/s/<scenarioId>/timeshift/<user>/<pass>/<duration>/<start>/<id>.ts`,
not just the suffix after it, and a QUERY-layout request's carries
`/s/<scenarioId>/streaming/timeshift.php?username=...&password=...&stream=...&start=...&duration=...`.
Assert with `toContain` against the suffix you care about, not equality against the bare route —
this goal's own spec does the same (`e2e/tests/streaming/catchup-path-layout.spec.ts:49-64`).
Everything that identifies what was asked for is there either way, including credentials, stream
id, start timestamp (exactly as sent, not just the parsed ISO form) and duration.

**The archive is not time-addressable: the same loop is served whatever `start` asked for.** This
provider can prove Dispatcharr *asked* for the right moment — the exact `start`/`stream`/`duration`
it sent is right there in the log — but it can never prove Dispatcharr *received* the right moment,
because there is only one archive and it plays the same regardless of `start`. Nothing built on top
of this provider can turn that into a seek-accuracy proof.

## Pacing

The stream is served at the asset's own nominal bitrate (~2 Mbit — around 180 KB/s for this
asset, measured) times a rate multiplier. `rate: 1` is real-time and is the only setting the
ffmpeg-profile buffering detector can observe meaningfully, because `speed=` is a ratio against
wall-clock time.

**Rate is only approximate above 1.** Pacing sleeps per chunk rather than against a cumulative
target (deliberately — see below), and per-chunk sleep overhead is a larger fraction of a shorter
sleep: rate 10 measured at roughly 8.1×, not 10×. Don't assert on throughput in any test; assert
an order of magnitude if you need to assert anything at all.

**Only a test asserting on ffmpeg's `speed=` needs `rate: 1`.** Every other test should use a
higher rate to avoid waiting on real-time playback — there is no reason to make a test wait 60
real seconds for a 60-second asset to loop once when nothing in that test cares about bitrate.

The per-chunk (not cumulative) pacing is itself deliberate: a cumulative target would average a
mid-stream rate change away over the remaining stream, which defeats the entire purpose of
`slow-trickle` needing to take effect promptly.

## The asset

The TS asset is generated at Docker image build time by `scripts/make-asset.sh`, run by ffmpeg in
the image's builder stage — the runtime image carries the asset and Node, not ffmpeg. ffmpeg's
version is deliberately unpinned; the build script asserts its own output (TS-packet-aligned,
starts with the sync byte) rather than pinning a byte-reproducible artifact, and the loop's
duration and packet count are **measured from the asset at server startup**, never hardcoded. A
version drift in ffmpeg is expected to change those numbers; nothing in this codebase or in a
consuming test may assume a specific duration or packet count.

`scripts/make-asset.sh` is not runnable on macOS outside the Docker build — it uses a `drawtext`
filter that Homebrew's ffmpeg build typically lacks. It only ever runs against Debian's ffmpeg, in
the builder stage.

A frame counter is burned into the video. It is a **human debugging aid only**, for eyeballing a
captured TS artifact in a video player after a test failure — nothing in this suite decodes video
or asserts on it.

## The VOD asset

`/movie/<user>/<pass>/<id>.<ext>` and `/series/<user>/<pass>/<id>.<ext>` (G8) serve a **second,
distinct asset** — a finite MP4 — not another mode of the TS loop above. The two exist for opposite
reasons: the loop has no end and deliberately sends no `Content-Length`, because there is nothing to
report; this asset exists specifically to have an end, a `Content-Length`, and byte offsets a client
can seek to.

Generated at Docker image build time by `scripts/make-vod-asset.sh` (same builder stage as
`make-asset.sh`, same "runtime image carries the asset, not ffmpeg" split): 5 seconds of `testsrc`
video at 320x180/25fps plus a 440 Hz sine tone, H.264/AAC, muxed to MP4 with `+faststart`. Not
runnable outside the Docker build for the same reason as `make-asset.sh`. The script asserts its own
output (at least 1 KB, and starts with an `ftyp` box) rather than pinning a byte-reproducible
artifact, for the same unpinned-ffmpeg reason as the TS loop.

Serving honours `Range` (`serveFiniteAsset`, `e2e-upstream/src/vod-asset.ts`):

- No `Range`, or one this provider doesn't understand (a non-`bytes` unit, a multi-range request, a
  bare `bytes=-`): `200` with `Content-Type`, `Content-Length` and `Accept-Ranges: bytes`.
- A satisfiable `bytes=` range: `206` with `Content-Range` and a `Content-Length` matching the sliced
  body.
- An unsatisfiable range (e.g. a start at or past the asset's length, or the degenerate `bytes=-0`):
  `416` with `Content-Range: bytes */<length>` and no `Content-Type` — this provider models faults
  explicitly (`range-unsupported`), so answering 416 to something it *can* parse but can't satisfy is
  correct, not an oversight.

The `range-unsupported` fault (see the fault table above) makes this route ignore any `Range` header
and answer `200` with the whole asset and no `Accept-Ranges` — a provider that will not serve `206`
does not advertise that it will.

## Development

```bash
npm ci
npm run typecheck
npm test              # vitest; generates its own tiny synthetic TS in-process, no Docker needed
```
