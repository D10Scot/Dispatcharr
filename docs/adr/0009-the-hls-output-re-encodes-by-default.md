# 9. The HLS output re-encodes by default

Date: 2026-09-26

## Status

Accepted. Rests on [ADR 0008](0008-phase-4-reopens-the-programme-for-apple-native-live-playback.md).

## Context

Every live Stream Profile the relay serves today is a remux. The default
FFmpeg profile is `-c copy`
(`core/migrations/0006_set_locked_stream_profiles.py:16`), and Proxy never
decodes at all. An MPEG-TS client therefore gets the provider's codecs, its
field order and its keyframe spacing, and nothing enforces any of them.

AVPlayer does enforce them. Apple publishes the rules in the *HLS Authoring
Specification for Apple Devices* (revised 2025-04-30). Several of them were
probed on 2026-09-26, on macOS 27 and the iOS 27 Simulator:

- **HEVC must be carried in fMP4 segments** (rule 1.5). HEVC in TS segments
  fails silently: the item reports ready, audio plays, and no video frame is
  ever decoded.
- **MP2 audio is not decodable on iOS.** One MP2 track fails the whole item,
  picture included, with CoreMedia `'fmt?'`. The iOS decoder list has no MP2,
  and tvOS is expected to match. That expectation is not verified: no tvOS
  runtime was available.
- **Interlaced content must be deinterlaced** (rule 1.14). Whether AVPlayer
  deinterlaces 1080i itself could not be judged headlessly. A third-party
  engine's notes say tvOS AVPlayer does not.
- **Every segment must start with an IDR frame** (rule 7.4). A remux can
  therefore cut segments only where the provider put keyframes, so segment
  length is the provider's keyframe spacing. IPTV providers commonly send one
  every 4 to 10 seconds.
- **Latency is about three target durations plus one segment.** Measured
  behind the wall clock, it was about 8.4 s with 2-second segments and about
  24.5 s with 6-second segments. A provider with 8-second keyframes puts a
  remuxed channel about 30 s behind live, and it cannot be shortened.

The household's server has an Intel 12th-generation CPU with UHD Graphics 770,
so it has Quick Sync. At most two streams are watched at once.

## Decision

**By default, a channel's HLS output is produced by re-encoding, not by
remuxing.** There is one shared re-encode per channel, started by its first
HLS client, on Quick Sync, with the following output:

- **Video:** H.264, deinterlaced to full frame rate, with a fixed short
  keyframe interval, so every segment is the same short length whatever the
  provider sends.
- **Audio:** a stereo AAC track, which Apple requires (rule 2.3). When the
  source carries AC-3 or E-AC-3, including E-AC-3 with Atmos, that track is
  passed through untouched as a second rendition. The Apple TV plays surround,
  and the phone plays AAC.
- **Container:** fMP4 (CMAF) segments, for every channel, so that one packaging
  path serves every codec AVPlayer accepts.

**The remux is an opt-in, per channel, through an Output Profile.** A channel
whose provider already sends clean H.264 or HEVC with short keyframes can be
set to *automatic*. In that mode the relay remuxes whatever is compatible and
transcodes only what is not: MP2 audio becomes AAC, and interlaced or MPEG-2
video becomes H.264. This reuses the existing Output Profile mechanism, which
already means "a downstream transcode shared per (channel, profile)", and adds
no new one.

**The re-encode feeds HLS only.** MPEG-TS clients keep receiving the
provider's stream as it is remuxed today. The re-encode is not a Stream
Profile, and it changes nothing upstream of the ring buffer.

**Rejected: remux by default.** It is the cheaper and lossless choice, and it
is the wrong default for this household. Every incompatible channel would
show up on the Apple TV as a silent failure that no error explains: no
picture, or no playback at all. Latency would follow each provider's keyframe
spacing rather than the product's choice. Low-Latency HLS would also stay out
of reach for good, because partial segments cannot start playback any faster
than the next keyframe. The re-encode makes latency, codec and field order
Mino's decisions rather than the provider's.

## Consequences

- **A generation of lossy encoding** sits between the provider and the Apple
  devices by default. The *automatic* Output Profile is the escape hatch for a
  channel where it shows.
- **The relay container needs the GPU.** `/dev/dri` must be passed into the
  container that runs `relay-go`. The Phase 4a spec decides what a host without
  a usable Quick Sync device does, whether it encodes in software or refuses.
  This ADR does not decide that.
- **A fixed keyframe interval makes Low-Latency HLS reachable later** without
  another decision about the source. It stays out of 4a (ADR 0008).
- **A source switch on failover still interrupts the output.** The segments
  after it carry `EXT-X-DISCONTINUITY`. The encoder's output parameters stay
  constant across the switch, so the only thing that changes is timing. The
  Phase 4a spec decides whether the encoder process survives a switch or is
  restarted at it.
- **One encode per channel is shared across its HLS clients,** exactly as an
  Output Profile's transcode is today. Two devices watching one channel
  cost one encode, and two channels cost two.
