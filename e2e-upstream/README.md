# e2e-upstream

A controllable fake IPTV provider for the E2E suite: an M3U playlist, an XMLTV EPG, a paced
looping MPEG-TS stream, and a control API that flips eight fault modes mid-test.

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
| `POST` | `/scenarios` | Create. Body declares catalogue, optional credentials, `maxConnections` (default unlimited), `rate` (default 1). Returns `{ id, internal, control, channels }` |
| `GET` | `/scenarios` | List live scenarios. Also the readiness endpoint `e2e_up.sh` waits on |
| `DELETE` | `/scenarios/<id>` | Optional explicit close |
| `POST` | `/s/<id>/fault` | Apply or clear a fault. Body takes an optional `channel` filter and per-fault parameters. Returns `{ fault, active, appliedTo }` |
| `POST` | `/s/<id>/rate` | Set the pacing multiplier on a live scenario |
| `GET` | `/s/<id>/log` | Request/connection history: method, hits, opens/closes with byte counts and durations, faults applied |
| `GET` | `/s/<id>/connections` | Live connection count and the accounting behind `maxConnections` |

Provider-facing endpoints — the ones a Dispatcharr `M3UAccount`/`EPGSource`/`Stream` points at,
not ones a test calls directly: `/s/<id>/playlist.m3u`, `/s/<id>/epg.xml`,
`/s/<id>/stream/<channelId>.ts`.

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
fault is now armed. Five of the eight faults can only affect the **next** request, because a live
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

`appliedTo: 0` is correct for the five "new only" rows above — they can only take effect on the
next connection attempt, never on one already streaming. This is not a partial failure of the
control API; it's the whole of what those faults can do.

An armed **`slow-trickle`** overrides the scenario's own rate for the connections it reaches.
Only `clearFault('slow-trickle')` hands control back to the scenario rate — a plain `rate()` call
while the trickle is armed changes the scenario default but does not clear the override.

**`disconnect`'s `afterBytes` is byte-exact on a draining client, and a lower bound on a
backpressured one.** When the client is keeping up, the stream is cut at exactly that many bytes,
mid-TS-packet if that's where it lands — deliberately, because that's what a real provider does
when it dies mid-write. When the client is behind and the socket is backpressured, a chunk already
queued before the cutoff is honored in full before the connection closes, so the client may see a
few more bytes than requested. Don't assert byte-exact cutoff under backpressure.

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

## Development

```bash
npm ci
npm run typecheck
npm test              # vitest; generates its own tiny synthetic TS in-process, no Docker needed
```
