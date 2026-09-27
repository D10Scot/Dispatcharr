# 8. Phase 4 reopens the programme for Apple-native live playback

Date: 2026-09-26

## Status

Accepted. Amends [ADR 0007](0007-phase-3-is-closed-because-phase-2-met-its-charter.md)
where it says the ladder ends at Phase 2. Every other part of ADR 0007 stands.

## Context

ADR 0007 closed Phase 3 and ended the programme after Phase 2. The route page
the programme was planned from (*Relay Extraction Route*, 2026-09-03) carried
one more phase, "Phase 4 · HLS for the apps", which it marked "planned if the
apps are the goal". It stayed unplanned because at the time nobody had said
the apps were the goal.

On 2026-09-26 the owner said they are. The household watches live TV on
iPhone, iPad and an Apple TV 4K, and wants a first-party app on those devices.
Android is deprioritised, and so is everything that is not live TV.

The server cannot serve that app today, and the reason is technical, not a
review rule. App Review no longer mandates HLS: guideline 2.5.7 is now
"intentionally omitted". AVPlayer, the only player that gives an app AirPlay,
Picture in Picture and the Apple TV's automatic frame-rate and dynamic-range
matching for free, plays MPEG-TS only inside HLS. The Go relay emits two
formats: MPEG-TS and progressive fMP4, each as one endless HTTP response
(`relay/httpapi/stream.go:171`, `relay/output/fmp4.go:47`, refused otherwise
at `relay/httpapi/stream.go:392-403`). It emits no HLS.

The two endless formats were probed against AVPlayer on 2026-09-26, on macOS
27 and the iOS 27 Simulator:

- Both fail on iOS. AVPlayer's opening `Range: bytes=0-1` probe gets a 200 with
  no length, and the item fails with `-11850`.
- A fake `Content-Range` total does not help: the player seeks to the fake end
  and stalls.
- HLS works with TS segments and with fMP4 segments.

The programme's own sequencing had already anticipated this: HLS needs the
relay to own its buffer in memory. ADR 0006 delivered that.

## Decision

**Phase 4 is opened, with one charter: live TV on Apple devices through
Apple's own player.** It has three deliverables, in this order:

- **4a, the server half.** The Go relay gains:
  - an HLS output for live channels;
  - the **live rewind window** (see `CONTEXT.md`): the last hour of a watched
    channel, kept by Mino itself, shared per channel, lingering after its
    last viewer leaves, and lost when the relay restarts;
  - a switch of the browser player to HLS for live.

  An Xtream client that asks for `.m3u8` gets a real playlist. Today the same
  request gets raw TS.
- **4b, the Apple app.** A first-party SwiftUI client for iOS and tvOS, with
  iOS/tvOS 27 as the floor and macOS only through "Designed for iPad". It
  covers the channel list, playback, rewind, now/next and programme markers
  on the scrub bar. The full guide grid comes later.

  It is published as a **public** App Store listing under an individual
  developer account. It carries a demo mode, because App Review cannot reach a
  server on the owner's LAN.

  It signs in with Xtream credentials, and it refuses any server that lacks
  4a. It lives in a repository of its own. This repository's Phase 4 spec is
  the contract it builds against.
- **4c, paired-device auth.** It is investigated after 4b's first playable
  build. It trades Xtream compatibility for per-device, revocable credentials
  that are specific to Mino. 4a's segment authorisation is designed not to
  care how a playlist request was authorised, so 4c does not touch the relay.

**Scope limits, recorded because each is where Phase 4 would widen:**

- **Live TV only.** VOD, catch-up and recordings are not in any 4x deliverable.
- **LAN only.** The app has no remote access built in. Away from home, it is
  reached through a VPN the household runs outside the app.
- **No Low-Latency HLS in 4a.** Plain HLS with short segments comes first.
- **No TS reader for the rewind window.** The window is format-agnostic by
  definition, but none of the household's clients would read it over TS. A
  `?behind=` parameter for TS is recorded as a known extension and built only
  when a TS client needs it.
- **Plex carries no design weight.** The household will stop using it once
  the app exists. Its surfaces, the HDHomeRun emulation and the M3U/XMLTV
  outputs, stay in the code. Deleting them is a separate question for after
  4b.
- **New identifiers are named for Mino**, the product's working name (see
  `CONTEXT.md`), or named neutrally, never for Dispatcharr. The rename itself
  is not Phase 4 work.

**Rejected: a bundled software player against today's TS.** The route page
recommended starting the app on VLCKit or an FFmpeg-based engine, so that it
never waited on relay work. With the server work now chartered, that engine
would be temporary, and it costs exactly what the app is for. It throws away
AirPlay, Picture in Picture and frame-rate matching, each of which would have
to be rebuilt by hand. It would also bring LGPL obligations into a public App
Store binary.

**Rejected: third-party Xtream apps alone.** They get native playback from 4a
for free, through `.m3u8`. But none of them can read a rewind window they do
not know exists, and none can adopt 4c.

## Consequences

- **CLAUDE.md's "the programme stops after Phase 2" is corrected** in the same
  PR as this ADR, and so are its statements that there is no HLS output, which
  become true only until 4a lands. `README.md:153` advertises "HLS Output". That
  is false today and becomes true for live at 4a.
- **The Go relay gains its first on-disk state.** The rewind window is too
  large for memory: about 3.6 GB per channel-hour at 8 Mbit/s. ADR 0006 still
  holds for everything the relay must know to serve a request, which stays in
  process memory. The segments on disk are a cache that a restart discards. It
  is not state a restart recovers.
- **4a amends ADR 0006's client registry.** ADR 0006 says the registry has
  no TTL, no heartbeat and no ghost sweep, because a client entry cannot
  outlive the goroutine that made it. An HLS viewer is a session of short
  requests. Its registry entry has no goroutine of its own, and it ends on
  an explicit leave, on a stop, or after an idle timeout. A lingering rewind
  window also keeps a channel running with no client at all. The Phase 4
  spec (§ The ADR 0006 amendment) lists every consumer of a channel's client
  count and what each does.
- **The relay gains a per-channel transcode for Apple clients.**
  [ADR 0009](0009-the-hls-output-re-encodes-by-default.md) records why.
- **Remote-access hardening stays off the critical path.** Wildcard hosts, open
  CORS, plaintext Xtream passwords and the world-open `STREAMS` ACL are exactly
  as they were. They did not become prerequisites, because the app is LAN-only.
  If remote access is ever built into the app, the hardening spec becomes a
  prerequisite to that change.
- **The skills govern the work.** Phase 4a is planned and implemented through
  `plan-review-fix`, `implement-review-escalate` and `pr-merge-gate`, like
  every phase before it.
