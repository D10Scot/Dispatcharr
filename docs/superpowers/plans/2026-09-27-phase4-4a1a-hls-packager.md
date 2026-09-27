# Plan: Phase 4a-1a, the HLS packager (inert)

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The PR's code is Appendix A, a byte-exact `git diff` verified to apply at the seed with `git apply --check --whitespace=error`; the tasks around it are the checks that prove it landed, and the break-checks that prove its tests can fail. The implementer applies the appendix and writes no code.

**Goal.** A new package, `relay/hls`, turns a channel's ring into fMP4/CMAF HLS renditions: a probe at each generation's own start (D9), an ffmpeg per generation writing video on fd 1 and one fragmented-MP4 audio rendition per descriptor from fd 3 (D6, D8), a restart at every source boundary (D10), a box reader and segmenter that cut 2 s segments aligned across renditions, relay-synthesised silence for a rendition with no source (M8), Quick Sync detection with a software fallback and a failure policy that writes Quick Sync off only on evidence against the device (D11), an `hls.Store` and every playlist (D7). `relay/ffmpeg` gains the extra-output-pipes spawn, `relay/buffer` and `relay/channel` record the ring index of every source boundary, and the Go coverage floor's header states ruling R21. **Nothing reaches the package**: no route, no Django change, no `AttachOutput` wiring. Viewers see nothing new.

**Seed.** `97675e88eebe422d1be92c0045a813ad499d313b` (`97675e88`, main on 2026-09-27, 4a-0 merged as #526). Every `file:line` below is at the seed unless it says otherwise.

**Branch.** `migration/phase4-4a1a-hls-packager` (spec D1), so the full E2E and lifecycle matrix runs on it.

**Authority.** In order of precedence:

1. The owner's rulings R1-R29 (the orchestrator's `rulings.md`). The ones this PR carries: R20 (E-AC-3-only sources get three audio renditions), R21 and R27 (the coverage rule for linked and unlinked packages), R28 (issue #525: `field_order=unknown` is a third state, treated as progressive). Models: opus only.
2. The Phase 4 spec, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`: § 4a-1a (`:1189-1250`), and everything it depends on — D6-D11 (`:215-222`), D20 (`:231`), § Encoder argv (`:434-618`, including the rendition set and filling, channel layouts, silence and its integer arithmetic, the transcode argv, detection, the failure policy), § Playlists (`:358-408`), § State the relay adds (`:284-299`), § Testing and gates (`:1035-1159`), M1-M8 (`:52-59`) and Appendix B.
3. The 4a-0 plan and fixtures on main (`docs/superpowers/plans/2026-09-27-phase4-4a0-upstream-fixtures.md`, `e2e-upstream/scripts/make-asset.sh`, `e2e-upstream/CONTRACT.md`): this PR's real-ffmpeg tests build the fixtures with `make-asset.sh <out> <name>`, as that plan's § Overlap recommends, and build the declared-but-empty audio PID source themselves, as its § What this plan does not do hands off.
4. CLAUDE.md (the Go hooks, stdlib-only, credlint, the Go coverage ratchet as amended by R21/R27), ADR 0006, the Phase 2 spec where relay packages are concerned, and `docs/relay-parity-matrix.md` (this PR adds its behaviours as pinned rows, spec § Testing).

**Issues.** Refs #525 (the probe keeps `field_order=unknown` distinct and treats it as progressive; 4a-1d's PR closes the issue). This PR closes no issue, so neither its commits nor its description carry a closing keyword.

## Global constraints

1. **Inert.** No route, no handler, no `AttachOutput` change, no Django, frontend, nginx, workflow or Dockerfile edit. `go list -deps .` from `relay/` must not list `relay/hls` (Task 5 checks it): the package is outside the shipped binary and outside the Go gate's denominator (R27).
2. **Standard library only**, and no Redis or Postgres by any route (ADR 0006; `scripts/check_go_stdlib_only.sh relay`).
3. **Every error a log or format call carries goes through `redact.Error`**, or carries a written `credential-logging: ok` reason (`scripts/check_go_credential_logging.sh relay`). Every ffmpeg stderr line is logged through `redact.Line`.
4. **Zero lint findings under three GOOS** (`golangci-lint run ./...` natively, `GOOS=linux`, `GOOS=darwin`, pinned v2.13.2), `go vet` and `go test -race` green.
5. **Test-modification rule.** No existing test's assertion changes. Existing test files are untouched; `relay/internal/relaytest/standin.go` (test support, not a test) gains three flags and their documentation, and nothing it already did changes.
6. **The linked packages' additions are fully covered** (`relay/buffer`, `relay/channel`, `relay/ffmpeg`: measured, every new statement covered), so R21 permits no rise in `missing`; the census (Task 13) confirms it in CI.
7. **Parity rows 31-35 land pinned** in a new `<!-- block: phase 4 -->`, and `HIGHEST_ROW_ID` goes 30 → 35 in the same diff (spec § Testing, parity matrix). Ids are the next free ones at the seed; if another PR takes 31-35 first, renumber at merge (spec: "Ids are assigned at merge time").

## What was measured

All of it in the planner's scratchpad (`p4a1a/`), against a scratch worktree of the seed carrying exactly Appendix A; nothing was written into the repository.

- **The code, green.** On the scratch tree (the seed plus Appendix A): `go build ./...`, `go vet ./...`, `golangci-lint run ./...` natively and under `GOOS=linux` and `GOOS=darwin` (`0 issues.` each), `scripts/check_go_stdlib_only.sh relay` (`OK`), `scripts/check_go_credential_logging.sh relay` (`credlint: 13 package(s) clean`), and `go test -count=1 -race ./...` over the whole module (every package `ok`; `relay/hls` 35 s, `relay/channel` 83 s, `relay/httpapi` 125 s on the planner's M-series Mac). The three fuzz targets ran 20 s each with no finding. `go list -deps .` from `relay/` does not list `relay/hls`. `cd e2e && npx tsc --noEmit -p . && npx playwright test --project=guards`: `tsc` 0, `49 passed`.
- **The production ffmpeg, on Linux.** The `relay/hls` test binary, cross-built without cgo, passed every run inside `lscr.io/linuxserver/ffmpeg:version-9.0-cli@sha256:47fbdc93…` (`docker/DispatcharrBase:7`'s pin, `ffmpeg version 9.0`, which carries `bash` and `ffprobe`) with `CI=1`, so no real test could skip: twelve full runs on linux/arm64 across the plan's last revisions, the last three on Appendix A's final code (the real tests 0.01-2.5 s each), and one full run on **linux/amd64 under emulation** — CI's architecture, with the amd64 build's QSV encoders present and no device — where the real tests took 0.05-26 s each. That amd64 run is what found Decision 20: with the production 5 s exit grace it killed the 1080i generation mid-flush and the test saw 3 of its 6 segments.
- **Coverage.** `relay/hls` alone, `-count=1 -race -covermode=atomic`: **93.95% — 1,454 statements, 88 uncovered** (Task 10's commands). Per file, statements / uncovered: `argv.go` 123/0, `box.go` 56/8, `detect.go` 47/0, `feed.go` 34/0, `fragment.go` 133/3, `init.go` 230/31, `pipeline.go` 342/25, `playlist.go` 12/0, `probe.go` 44/0, `reader.go` 57/1, `segmenter.go` 154/6, `silence.go` 129/14, `store.go` 93/0. What is uncovered is almost entirely malformed-box arms (`init.go`'s short-box returns, `box.go`'s 64-bit-size arm, `silence.go`'s `fragmentSamples` refusals) and process-failure arms in `pipeline.go` (a spawn that fails, a probe that cannot start, a canned encode that fails). CI's figure (Task 12) is the authoritative one. Every added statement in `relay/buffer`, `relay/channel` and `relay/ffmpeg` is covered by those packages' own tests (the R21 listing is "none"); whole-package figures 89.8%, 80.5% and 92.9%.
- **ffmpeg's own shapes**, which three decisions rest on (ffmpeg 9.0.1, the 1080i fixture cut 3 MB in, so the join is mid-GOP):
  - Each fragmented-MP4 output starts its `tfdt` at 0 and puts the track's real start in an empty edit: video 0.86 s (the first decodable keyframe), the encoded AAC a few milliseconds, the copied AC-3 none (Decision 3). With `-use_editlist 0` the offsets are simply lost, and `-copyts` moves them but keeps `tfdt` at 0.
  - Video fragments came out at 0.000, 2.000, 4.000 s of the video's own timeline: `-force_key_frames expr:gte(t,n_forced*2)` counts from the encoder's first frame (Decision 5).
  - A PMT-declared AC-3 PID with its packets removed probes as `"channels": 0, "sample_rate": "0"`; mapping it fails the whole generation (`sample rate not set … Could not write header`, exit 234) (row 35).
  - `frag_keyframe+default_base_moof` without `delay_moov` copies AC-3 cleanly; `empty_moov` refuses it (Deviation 1).
  - ffprobe on a live-paced feed reads to its 8 s analyze bound (Defect 3).
- **M3, reproduced.** BC1 (the generation's feed ignoring the boundary while the probe honours it) runs the `mpeg2-576i-mp2` → `h264-eac3` pair through one encoder: generation 0 publishes 3 segments and the second source never appears, with ffmpeg exiting cleanly.
- **The generation exits on EOF.** In `TestRealTheNoAudioFixtureGetsRelaySynthesisedSilence` the no-audio generation logged `after_input_closed=` 35-40 ms over three runs (spec: within 1 s; M8: 0.065 s). With BC5's `anullsrc` input it ran until the grace killed it.
- **AVPlayer**, macOS 27 and the iOS 27 Simulator (iPhone 18 Pro, `xcrun simctl spawn`), with the spec's own probes (Appendix B: `probe2` for ready, first frame, frames decoded and seconds behind `EXT-X-PROGRAM-DATE-TIME`, 15 s or 40 s; `probe4` for the audio format the player selected), against a scratch HTTP server (never in the repository) serving this code's `Pipeline.Multivariant("")` and `Store` over a ring fed in real time from 80 s loops of the 4a-0 fixtures, `JoinBehind` 5 s, software encoding. `?only=<group>` served a multivariant with one audio group, as M5 did.

| Source (4a-0 fixture, looped) | Player, group | Result |
|---|---|---|
| `h264-1080i-aac-ac3` (1080i → 1080p50; `aac` encoded, `ac3` copied) | macOS, whole multivariant, 15 s | ready 0.25 s, first frame 0.20 s, 736 frames, 8.60 s behind PDT |
| | iOS, whole multivariant, 15 s | ready 0.29 s, first frame 0.22 s, 734 frames, 10.04 s behind PDT |
| | macOS and iOS, `aac` only / `ac3` only | `aac ` / `ac-3` selected on both |
| `h264-eac3` (R20: `aac`, `ac3` encoded from E-AC-3, `eac3` copied) | macOS, whole, 15 s | ready 0.25 s, 368 frames (25 fps), 9.27 s behind PDT |
| | iOS, whole, 15 s | ready 0.19 s, 369 frames, 10.75 s behind PDT |
| | macOS, `eac3` only, 15 s | ready 0.20 s, 369 frames, 9.85 s behind PDT |
| | macOS and iOS, `aac` / `ac3` / `eac3` only | `aac ` / `ac-3` / `ec-3` selected on both |
| `h264-noaudio` (relay-synthesised silent AAC, M8) | macOS, 15 s | ready 0.22 s, 369 frames, 9.66 s behind PDT; `aac ` selected |
| | iOS, 15 s | ready 0.23 s, 369 frames, 11.07 s behind PDT; `aac ` selected |
| `h264-eac3` 26 s, **boundary**, `h264-noaudio` (generation 1 all silent: canned AAC, AC-3 5.1 and **E-AC-3 5.1**) | macOS, `eac3` only, 40 s across it | ready 0.23 s, 942 frames of 1,000, 11.28 s behind PDT |
| | iOS, `eac3` only, 40 s across it | ready 0.27 s, 990 frames, 9.75 s behind PDT |
| | iOS, whole multivariant, 40 s across it | ready 0.19 s, 992 frames, 9.44 s behind PDT |
| `h264-1080i-aac-ac3` 26 s, **boundary**, `mpeg2-576i-mp2` (`ac3` encoded from MP2 after it) | macOS, `ac3` only, 40 s across it | ready 0.25 s, 1,910 frames of 2,000 (50p), 10.43 s behind PDT |
| | iOS, whole multivariant, 40 s across it | ready 0.23 s, 1,911 frames, 10.90 s behind PDT |

Across the E-AC-3 → no-audio boundary the generation-0 encoder exited 24 ms after its input closed, generation 1's probe completed 7.0 s after the boundary (Defect 3), and the player fetched generation 1's first segment 11.1 s after it. **Before Decision 7** (the tail drop) the same iOS `eac3`-only run stalled for good at the boundary: 346 frames in 40 s, no `behindPDT`, and no request after the generation-0 tail's zero-sample E-AC-3 fragment; with the tail dropped, 990 frames. The matrix ran on Appendix A's code before two last edits, a doc comment on `Pipeline.Ready` and an equivalent rewrite of `sampleEntry`'s first-entry lookup (the CODECS unit and real tests cover it); a re-run on the final code gave the same picture: iOS `eac3`-only across the E-AC-3 → no-audio boundary 989 frames in 40 s (9.58 s behind PDT), macOS 1080i whole multivariant 736 frames in 15 s (8.83 s behind PDT), `ac3`-only selecting `ac-3`. No tvOS runtime was available (Q2-Q4 stay the owner's).

## Decisions the spec leaves open

Each is a choice the spec does not make. The reviewer should read them as the plan's own rulings, open to challenge.

1. **Where a boundary is recorded, and what the chunk at it holds.** `Channel.runAttempt` calls `markBoundary()` before every `Source.Run` (`relay/channel/channel.go:603-605` after the diff): every attempt is a new upstream connection, a same-URL reconnect as much as a failover (D10). `markBoundary` calls a new `buffer.Ring.MarkBoundary`, which **publishes the old connection's pending whole packets as one short final chunk and drops its partial packet**, then returns `head+1`. Without the publish, the pending bytes (up to one 255,868-byte chunk) would open the new connection's first chunk with the old source's PAT, PMT and PIDs, which is exactly the mixed input M3 shows an encoder silently dropping a source over, and which a probe at the boundary would misdescribe. Publishing rather than dropping keeps every byte a TS client was due (a failover already dropped them through `ResetPosition`, so nothing changes there; a same-URL reconnect used to glue them, and its dangling partial packet, onto the new connection's first packet). No reader assumes a chunk's length (`grep -rn ChunkBytes relay --include=*.go` outside `buffer/`). The channel keeps the newest 64 boundaries, strictly increasing (an attempt that published nothing repeats the index and is not recorded twice), and answers `NextBoundary(after)`.
2. **`relay/hls` does not import `relay/channel`.** It reads a `Source` interface (`Ring()`, `NextBoundary(after)`) that `*channel.Channel` satisfies, so 4a-1b can have the channel hold a pipeline without an import cycle.
3. **Renditions are aligned by `tfdt`, and every init's edit list is stripped — not only the canned ones.** Measured on ffmpeg 9.0.1: each fragmented-MP4 output starts its own `tfdt` at 0 and records where the track really starts, relative to the output's zero, as an **empty edit**. Joined mid-GOP (the ring cut 3 MB into the 1080i fixture), the video's empty edit was 0.86 s, the encoded AAC's a few milliseconds and the copied AC-3's none: aligned by `tfdt` the renditions were 0.86 s apart. hls.js ignores edit lists, and AVPlayer's handling of an empty edit in an HLS init is not something this plan could measure in isolation. So `ParseInit` reads the offset (empty-edit time converted from the movie to the media timescale, less any `media_time`, never negative), the segmenter moves every fragment's `tfdt` by it (`shiftStart`), and `StripEdits` removes `edts` from every init served. The spec's own edts rule (`:503-506`) is the canned-init case of this one.
4. **The silent renditions' `tfdt` starts at the generation's first video `tfdt`, in audio ticks.** The spec counts frames from the generation's first video `tfdt` (`:495-496`) and says a segment's `tfdt` is "at the first frame's start" (`:488`); frame 0 is placed where that video frame is, on the timeline of Decision 3, so the silence is aligned with the video by `tfdt` as well as by count.
5. **The 2 s grid is measured from the generation's first video `tfdt`.** A segment is cut before the first fragment that opens on a sync sample at or after the next grid line, and the next line is the first one after that fragment (`segmenter.cutLocked`). Measured: after a mid-GOP join ffmpeg's `-force_key_frames expr:gte(t,n_forced*2)` places keyframes every 2.000 s from the encoder's own first frame, so the grid and the keyframes coincide and even a generation's first segment is a full 2.000 s.
6. **An audio segment holds the fragments whose start falls in `[vstart, vend)` of its video segment** (spec `:403-404`), compared by cross-multiplying the two timescales in 64-bit integers. A cut video segment waits for each audio output to read past its end, bounded by **`AudioWait` = 2 × TARGETDURATION of wall-clock time**, not by a count of video segments: when a generation catches up its JoinBehind backlog faster than real time, the video reader can be several segments ahead of an audio reader that simply has not been scheduled (a count-based bound published audio-less segments on Linux; measured). After `AudioWait`, a mid-generation segment gets a zero-sample fragment of its own track, so a stopped audio output never stalls the video.
7. **A generation's last segment with no audio on some rendition is not published.** The flushed tail after stdin EOF can outlast the audio by a frame or two. Measured on the iOS 27 Simulator: an E-AC-3-only player stalled for good at such a tail when it carried a zero-sample E-AC-3 fragment, and played across the same boundary once the tail was dropped (§ What was measured). No sequence number is used, so the media sequence stays contiguous; the loss is at most one short segment at a source boundary.
8. **Audio is mapped by PID, `-map 0:i:<id>`**, the id ffprobe reports for the stream. An index could name a different stream in the encoder than in the probe if the two saw the PMT differently; an id cannot.
9. **Descriptors are fixed per rendition — AAC fd 3, AC-3 fd 4, E-AC-3 fd 5 — with holes.** A rendition filled with silence has no ffmpeg output and no descriptor (`StartPipedExtra` leaves a `false` entry as a closed descriptor: os/exec passes a nil `ExtraFiles` entry that way), so D6's numbering never moves.
10. **The probe's bound is enforced three ways**: `-probesize 5000000 -analyzeduration 8000000`, a feed that stops at 5 MB, and a feed that stops after 8 s of wall clock; the feed also stops at the next boundary, so a probe never reads two sources. `ffprobe` gets `ProbeWall + KillWait + 1 s` before its context kills it.
11. **Failure ends the pipeline with `ErrFailed`; the channel mark is 4a-1b's.** The spec puts `hlsFailedUntilBoundary` on the channel, read by `StreamHandler`'s entry path and cleared at the next boundary (`:566-584`). Nothing in 4a-1a reads a mark, so the pipeline logs at ERROR with the last ten stderr lines (through `redact.Line`) and ends with `Err() == ErrFailed`; 4a-1b sets the mark from that. `ErrNoVideo` is generation 0's probe finding no video (D9's 502). A **later** generation whose probe finds no video, and a probe that fails, are `ErrFailed` too (the spec defines only generation 0's case).
12. **The canned silence** is a one-second `anullsrc` encode per (codec, declared layout) through `ffmpeg.Start` with a 10 s context, split by the same box reader; the steady-state frame is the middle frame, checked byte-identical to its successor (M8's observation, asserted rather than assumed). It is cached for the process in a `SilenceCache` every pipeline shares; a failed encode is not cached. A silent segment shorter than one frame still gets one frame; the next segment's count, computed from the absolute index, takes it back.
13. **Transcode mode always encodes AAC** (copying AAC is automatic mode's, 4a-1d), and every encode's bitrate is written in bits per second (`-b:a 160000`), the same value as the spec's `160k`.
14. **`R`, `G`, geometry.** `G = round(2R)` is computed in integers as `(4·num + den) / (2·den)`. A rate ffprobe cannot read is taken as 25/1. `R` above 60 becomes exactly 60/1. Geometry keeps a source that fits 1920×1080; a larger one is scaled into it with its aspect kept; both dimensions are floored to even (4:2:0).
15. **The Store** keeps 12 segments across every rendition, bounded also at 64 MiB (a runaway guard the spec's "bounded by count and bytes" asks for), and keeps the init segments of every generation a stored segment belongs to plus the newest. `EXT-X-DISCONTINUITY` is written before the first segment of every generation after the first **even when that segment is the first one listed**, and `EXT-X-DISCONTINUITY-SEQUENCE` counts discontinuities that have left the list, so a segment's discontinuity sequence number never changes between reloads. NAME is `Stereo` for `aac` and `Surround` for `ac3` and `eac3` (different GROUP-IDs, so sharing a NAME is legal).
16. **Readiness is inits, not health.** `Pipeline.Ready` returns once every generation-0 init segment exists (real outputs' from ffmpeg, silent ones' canned), or the pipeline ends first. A pipeline that fails after that still answers `nil`; `Done` and `Err` say it ended.
17. **The API 4a-1b builds on:** `hls.Start(ctx, hls.Config{ChannelID, Source, JoinBehind, Detector, Silence, …}) (*Pipeline, error)`, `(*Pipeline).Ready`, `Multivariant(base)`, `Store()` (`MediaPlaylist(rendition) (body, lastModified, ok)`, `Segment(rendition, seq)`, `Init(rendition, gen)`, `WaitSegment(ctx)`), `Engine()`, `Generation()`, `Done()`, `Err()`, `Stop()`; process-wide `*hls.Detector` and `*hls.SilenceCache`. Test seams, none of which a production caller sets: `Config.Command`, `Config.ProbeCommand`, `Config.ExitGrace`, `Config.AudioWait`, and `relay/ffmpeg`'s `newPipe`.
18. **A generation's exit after its input closed is logged at INFO** (`after_input_closed=`), because it is the first term of Q6's failover gap and the no-audio test reads it.
19. **The stand-in gains `--fd-file N=PATH`, `--wait-stdin-eof` and `--ignore-stdin-eof`** (`relay/internal/relaytest/hls.go`): it writes each file to its descriptor, holds every descriptor open (an encoder's exit is what closes them), and exits at once, at stdin EOF, or never. The unit tests' fMP4 is built by test helpers (`relay/hls/helpers_test.go`), never captured.
20. **The real tests run with a 20 s exit grace, not the production 5 s.** They feed seconds of media at once rather than in real time, so when stdin closes a slow host is still encoding what it already read; measured under amd64 emulation, the 5 s grace killed the 1080i generation mid-flush with 3 of its 6 segments published. In production the input arrives in real time and the flush is tens of milliseconds (35-40 ms measured, M8's 65 ms), and `GenerationExitGrace` stays 5 s as D10 says; the grace itself is the stand-in test's subject. The same arithmetic is a residual risk on a weak host (§ Residual risks and follow-ups).

## Deviations from the spec's text

Each is recorded here so the reviewer rules on it; none widens scope.

1. **Break-check "Drop `delay_moov`" (`:1224`) is replaced by "swap `delay_moov` for `empty_moov`".** Measured on ffmpeg 9.0.1: `-movflags frag_keyframe+default_base_moof` (no `delay_moov`) copies the 1080i fixture's AC-3 to fragmented MP4 without error — the test stays green — while `frag_keyframe+empty_moov+default_base_moof` fails with `Cannot write moov atom before AC3 packets. Set the delay_moov flag to fix this.`, which is the error M4 recorded. The mechanism the spec's break-check names is `empty_moov` refusing AC-3; the plan's wrong edit is the one that shows it.
2. **"An audio segment is within 0.2 s of its video segment" (`:405`) is asserted as "within one audio fragment".** `-frag_duration 200000` gives fragments of at least 200 ms rounded up to whole frames: 213 ms of AAC (10 × 1024 samples) and 224 ms of AC-3 (7 × 1536). Measured on the 1080i fixture: an `ac3` segment's first fragment began 220 ms after its video segment. The real test's bound is 0.225 s. Still well inside Apple 7.7's +0.5 s.
3. **Every init's edit list is stripped and every fragment's `tfdt` moved, not only the canned inits'** (Decision 3). The spec's rule (`:503-506`) covers the canned case; without the general one, the renditions of a generation joined mid-GOP are 0.86 s apart by `tfdt` (measured).
4. **A generation's audio-less last segment is dropped** (Decision 7) — the spec says only that the last segment "may be short" (`:499-501`). Measured reason: the iOS 27 Simulator's E-AC-3 path stalled for good on a zero-sample tail.
5. **The failure mark on the channel is 4a-1b's** (Decision 11): the spec describes `hlsFailedUntilBoundary` under 4a-1a's "failure policy" scope (`:1192-1193`, `:566`), but nothing in 4a-1a can read it, and it is set and cleared by code 4a-1b writes (the entry path, the boundary). 4a-1a delivers the policy up to `ErrFailed`.

## Spec defects found (reported, not silently diverged from)

1. **`:1224`** — the break-check "Drop `delay_moov`" does not redden on ffmpeg 9.0.1 (Deviation 1). Fix: "Replace `delay_moov` with `empty_moov`".
2. **`:405`** — "within 0.2 s" should read "within one audio fragment (at most 224 ms for AC-3)" (Deviation 2).
3. **D9 (`:218`) and Q5/Q6 (`:1525-1526`)** — on an MPEG-TS pipe ffprobe reads to its `-analyzeduration` bound whatever it has found, because the demuxer is a no-header format: measured wall time for the probe over a live-paced feed of each 4a-0 fixture was 7.7 s (`h264-noaudio`, `h264-eac3`, `mpeg2-576i-mp2`) and 5.4 s for `h264-1080i-aac-ac3`, which reaches 5 MB first; ffprobe's own log reports `max_analyze_duration 8000000 reached`. So **every later generation's probe adds up to 8 s to the failover gap** (M6's 8.9 s was measured with no probe at all), and generation 0's adds up to 3 s to zap time (8 s less the 5 s JoinBehind backlog it reads at once). In the planner's AVPlayer run across a boundary the probe completed 7.0 s after it and the player fetched the new generation's first segment 11.1 s after it. The spec's 5 MB/8 s is kept as written; Q6's measurement in 4a-1b should include it, and a lower `-analyzeduration` (which a 10 s-GOP source would then fail to probe for dimensions) is a spec decision, not this plan's.
4. **`:488` with `:495-496`** — "`tfdt` at the first frame's start" with "a generation's frame index starts at 0" does not say which timeline the `tfdt` is on; read literally (tfdt = index × spf) the silence would sit 0.86 s off its video after a mid-GOP join. Decision 4 places it on the video's.
5. **§ Encoder argv is silent on the real outputs' edit lists** (`:503-506` covers only canned inits), which is where the misalignment of Decision 3 comes from.
6. **§ Testing's parity scope** (`:1073`): 4a-1a lands HLS rows while the matrix preamble still says "the live TS/fMP4 path"; the spec gives the widening to 4a-1b. Harmless (the guard does not read the sentence), but the matrix is briefly inconsistent with itself.
7. **§ Done log (`:1616-1629`)** has no PR number or merge date for the spec (#523) or 4a-0 (#526); housekeeping for the orchestrator, not this PR.

## PR 4a-1a: the HLS packager (inert)

**Files** (anchors at the seed):

- `relay/hls/` — **new**, 25 files. Production: `doc.go` (the package's map), `box.go` (box header and cursor), `init.go` (`ParseInit`, CODECS, `StartOffset`, `StripEdits`), `fragment.go` (`ParseFragment`, `shiftStart`, `synthFragment`), `reader.go` (the streaming `splitter`), `probe.go` (D9), `argv.go` (`Decide`, `PlanGeneration`, `Output.Argv`, D8), `detect.go` (D11), `silence.go` (M8), `feed.go` (the ring writer, `Source`), `segmenter.go` (D6), `store.go` (the Store and media playlists, D7), `playlist.go` (the multivariant), `pipeline.go` (generations and the failure policy, D10-D11). Tests: `helpers_test.go` (the synthetic fMP4 builders and `testSource`), and the ten other `*_test.go` of § Tests added.
- `relay/buffer/ring.go:89-91,242` — the concurrency comment names the two new methods; `MarkBoundary` and `ArrivedAt` inserted after `ResetPosition` (which ends at `:242`), before `Head`.
- `relay/channel/boundary.go` — **new**: `boundaryLog`, `markBoundary`, `NextBoundary`.
- `relay/channel/channel.go:97,599` — `boundaryLog` embedded after `outputRegistry` (`:97`); `c.markBoundary()` in `runAttempt` after its context (`:599`), before the attempt is marked connected.
- `relay/ffmpeg/spawn.go:52,95,110-113,183-196,314` — the `extra` field (`:52`); `Start` and `StartPiped` pass a nil mask (`:95`, `:110`); `StartPipedExtra` (after `:111`); `start` takes the mask and wires `ExtraFiles` (`:113`, `:183-196`); `newPipe`, `extraPipes`, `closeFiles`, `Extra` (after `:196`); `Wait` closes the extra read ends (`:314`).
- `relay/internal/relaytest/standin.go:97,139,195,256` (the flag documentation, the options, the parse, the dispatch) and **new** `relay/internal/relaytest/hls.go` — the `--fd-file`, `--wait-stdin-eof` and `--ignore-stdin-eof` flags.
- New tests outside `relay/hls/`: `relay/buffer/boundary_test.go`, `relay/channel/boundary_test.go`, `relay/ffmpeg/extra_test.go`, `relay/internal/relaytest/hls_test.go`.
- `scripts/coverage_relay_go.floor:193` — the R21/R27 paragraphs appended to "HOW TO MOVE THIS FLOOR"; no field changes (`missing=589` stays).
- `docs/relay-parity-matrix.md:156-157,200` — the "Blocks, in file order" sentence names the new block; rows 31-35 in `<!-- block: phase 4 -->` before `<!-- end of matrix -->`.
- `e2e/tests/guards/parity-matrix.ts:595` — `HIGHEST_ROW_ID` 30 → 35.

**Tasks.** Run every command from the implementation worktree (`worktree-per-change`), anchored with an absolute path or a leading `cd`. `SEED=97675e88eebe422d1be92c0045a813ad499d313b`.

1. **Pre-flight.** `set -o pipefail; git diff --stat "${SEED}" origin/main -- relay scripts/coverage_relay_go.floor docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts` prints nothing (stderr kept; a non-zero exit is a stop). `git show "${SEED}:e2e/tests/guards/parity-matrix.ts" | grep -n 'HIGHEST_ROW_ID = '` prints `595:export const HIGHEST_ROW_ID = 30;`. If main has moved any of those paths, or a row id above 30 exists on main, stop and report; do not re-derive the appendix.
2. **Apply Appendix A.** Extract it from this plan at the plan's merged SHA and apply it:
   `awk '/^<!-- appendix-A-begin -->$/{f=1; next} /^<!-- appendix-A-end -->$/{f=0} f' docs/superpowers/plans/2026-09-27-phase4-4a1a-hls-packager.md | sed '1d;$d' > "$SCRATCH/4a1a.diff" && git apply --whitespace=error "$SCRATCH/4a1a.diff"` (`$SCRATCH` is your session scratchpad). `git status --short` shows 7 modified files (`M`) and 31 new ones (`??`: the whole of `relay/hls/`, 25 files, plus `relay/buffer/boundary_test.go`, `relay/channel/boundary.go`, `relay/channel/boundary_test.go`, `relay/ffmpeg/extra_test.go`, `relay/internal/relaytest/hls.go`, `relay/internal/relaytest/hls_test.go` — shown as the directory `relay/hls/` and six paths). `git diff --stat` over the modified files matches § Files.
3. **Build, vet and lint under three GOOS.** `cd relay && go build ./... && go vet ./...`, then `golangci-lint run ./...`, `GOOS=linux golangci-lint run ./...` and `GOOS=darwin golangci-lint run ./...` (v2.13.2): each prints `0 issues.` The `PostToolUse` Go hook does not run for a `git apply`, so this task is what stands in for it.
4. **Stdlib and credential logging.** From the repo root, `scripts/check_go_stdlib_only.sh relay` prints `OK: relay depends on the standard library only.` and `scripts/check_go_credential_logging.sh relay` prints `credlint: 13 package(s) clean`.
5. **Inertness.** `cd relay && go list -deps . | grep -c 'relay/hls'` prints `0` (and exits 1): the shipped binary does not link the package, so it is outside the coverage gate's denominator (R27) and no viewer can reach it.
6. **The suite.** `cd relay && go test -count=1 -race ./...`: every package `ok`. `relay/hls` takes about 35 s on the planner's Mac (most of it spawning the re-executed stand-in) and `relay/channel`/`relay/httpapi` their usual 85 s and 125 s. The nine `TestReal*` tests need `ffmpeg`, `ffprobe` and `bash` on PATH; without them they **skip** locally (and fail under `CI`, where the base image carries them). If they skipped, say so; do not describe them as run.
7. **The real tests against the production ffmpeg 9.0, on Linux** (local evidence; CI's `build` job runs them in the base image anyway): `cd relay && GOOS=linux GOARCH=$(go env GOARCH) CGO_ENABLED=0 go test -c -o "$SCRATCH/hls.linux.test" ./hls`, then `docker run --rm -e CI=1 -v "$PWD/..":/repo -v "$SCRATCH":/s -w /repo/relay/hls --entrypoint bash lscr.io/linuxserver/ffmpeg:version-9.0-cli@sha256:47fbdc93828be04d7c52ca9a9a95f7957f887b80369f3581b8ff661873ed77a0 -c '/s/hls.linux.test -test.count=1'` prints `PASS` (measured: twelve runs on linux/arm64, and one on linux/amd64 under emulation — build with `GOARCH=amd64` and add `--platform linux/amd64` to repeat it; it takes minutes). No `-race` there: the binary is built without cgo.
8. **The e2e guards.** `cd e2e && npm ci && npx tsc --noEmit -p . && npx playwright test --project=guards`: `tsc` exits 0 and `49 passed`, the parity guard printing `parity matrix (Go): 33 of 33 pinned rows carry a Go reference; 2 row(s) are not pinnable.`
9. **Break-checks** (§ Break-checks): each applied alone, run, the message compared with the one recorded there, then reverted; `git diff --stat` afterwards is Task 2's.
10. **Coverage evidence, local.** `cd relay && go test -count=1 -race -covermode=atomic -coverprofile="$SCRATCH/hls.cover" ./hls` reports about 93.9% (measured 93.9%). The per-file table: `awk 'NR>1 {f=$1; sub(/:.*/,"",f); sub(/.*\//,"",f); t[f]+=$2; if ($3==0) m[f]+=$2} END {for (f in t) printf "%-14s %4d %4d %6.2f%%\n", f, t[f], m[f], 100*(t[f]-m[f])/t[f]}' "$SCRATCH/hls.cover" | sort`, and the uncovered blocks: `awk 'NR>1 && $3==0 {print $1, $2}' "$SCRATCH/hls.cover"`. The linked packages' additions are fully covered: run `go test -count=1 -race -covermode=atomic -coverprofile="$SCRATCH/linked.cover" ./buffer ./channel ./ffmpeg`, list the diff's added line ranges with `git diff -U0 "${SEED}" -- relay/buffer/ring.go relay/channel/channel.go relay/ffmpeg/spawn.go | grep '^@@'` plus the whole of `relay/channel/boundary.go`, and confirm no `$3==0` block of `$SCRATCH/linked.cover` falls inside them (measured: none).
11. **Push and open the PR as a draft** (`implement-review-escalate`), branch `migration/phase4-4a1a-hls-packager`, with the description below; commit messages carry no closing keyword (`Refs #525` only).
12. **Coverage evidence, CI (R27, authoritative).** From the PR's first green `Go Tests` run, download the `relay-go-coverage` artifact (`gh run download <run-id> --repo D10Scot/Dispatcharr -n relay-go-coverage -D "$SCRATCH/ci-cov"`) and compute `relay/hls`'s per-package figure and per-file listing from `relay.coverprofile` with Task 10's two `awk` commands, filtered to `/relay/hls/` (`grep -E '^(mode:|github.com/D10Scot/Dispatcharr/relay/hls/)'` first). CI's number, not the local one, goes in the PR body; it must be ≥ 85%. The coverage job's own report lists the package as `~out of scope, not counted: github.com/D10Scot/Dispatcharr/relay/hls, <n> statements`, which is correct and expected.
13. **The R21 census for the linked packages.** Dispatch `go-tests.yml` on the branch at least twelve times (`gh workflow run go-tests.yml --repo D10Scot/Dispatcharr --ref migration/phase4-4a1a-hls-packager`, one at a time: the workflow's concurrency group cancels an in-flight run on the same ref), and record every `Coverage gate` job's `this run missing=` in order, until the maximum has held for six consecutive rounds (≥ 12 total), exactly as the floor file's step 1 says. **Expected: every round ≤ 589**, because every new statement in `relay/buffer`, `relay/channel` and `relay/ffmpeg` is covered (Task 10), so the floor does not move and the PR body's R21 listing is "none". If a round exceeds 589, attribute it block by block (the floor file's `awk` diff between that round's profile and a 589 one): a block inside this PR's added ranges is listed per file and `missing` rises by exactly that count (R21, with ≥ 85% on the PR's additions); a pre-existing block is a flap and a finding for a re-measurement PR of its own — never a bump here.
14. **Q1.** If the owner can run the QSV argv on the household host (spec Q1), record the output in the PR body; otherwise the body says "QSV on the household host: first item of 4a-1b's body", and the PR does not claim QSV works (spec § Risks).

**Tests added.** Every test is new; no existing test changes (Global constraint 5). "Stand-in" tests spawn the re-executed test binary through `relay/internal/relaytest` (the subject is the relay's reaction to a process: its bytes, exit and moment); "real" tests spawn ffmpeg and ffprobe over the 4a-0 fixtures (the subject is what an encoder makes).

| File | Test | Pins |
|---|---|---|
| `relay/buffer/boundary_test.go` | `TestMarkBoundaryEndsTheOldConnectionsBytes` | Decision 1: pending whole packets published as a short chunk, the partial dropped, the boundary chunk the new connection's own; nothing published when nothing is pending |
| | `TestMarkBoundaryAfterResetOrCloseOnlyReportsTheIndex` | after `ResetPosition` (a failover) and on a closed ring, nothing is published |
| | `TestArrivedAt` | the PDT anchor's clock: a held chunk's publish time, false otherwise |
| `relay/channel/boundary_test.go` | `TestEveryConnectionAttemptRecordsASourceBoundary` | D10 and parity row 32: three connections to one URL (two same-URL reconnects) give boundaries 1, 3, 5, each the first chunk of its connection's own PID |
| | `TestTheBoundaryRecordIsStrictlyIncreasingAndBounded` | an attempt that published nothing is not recorded twice; the newest 64 are kept |
| `relay/ffmpeg/extra_test.go` | `TestStartPipedExtraGivesTheChildItsOutputPipes` | D6's spawn: fd 1 and fd 4 carry the child's bytes; fd 3, not given, is a closed descriptor in the child |
| | `TestStartPipedExtraWithoutExtrasAndOnAFailedSpawn` | a failed pipe names its descriptor; a failed spawn and a URL command are refused |
| `relay/internal/relaytest/hls_test.go` | `TestFDFileArgsParse` | the stand-in's new flags parse, and a malformed `--fd-file` fails the parse |
| `relay/hls/box_test.go` | `TestParseInitReadsTheTrackAndItsCodec` | track id, handler, timescale, trex defaults, version 0 and 1 boxes |
| | `TestCodecStringsComeFromTheInitSegment` | D7: CODECS from `avcC`, `hvcC`, `esds` (including an escaped object type), `dac3`, `dec3` |
| | `TestStartOffsetIsTheEmptyEditInMediaTicks` | Decision 3: empty edit → media ticks, less `media_time`, clamped at 0 |
| | `TestStripEditsRemovesTheEditListAndFixesTheSizes` | Decision 3 and spec `:503-506`: no `edts` in a served init, sizes rewritten |
| | `TestParseInitRefusesWhatIsNotAnInit`, `TestParseFragmentRefusesAMalformedFragment` | every length checked: malformed input is an error, never a panic |
| | `TestParseFragmentReadsTheTimingAndTheSyncSample`, `TestParseFragmentFallsBackToTheDefaults` | `tfdt` v0/v1, `trun` durations, the sync sample from first-sample flags, tfhd and trex defaults |
| | `TestShiftStartMovesTheTfdt` | Decision 3's rewrite, in place; a version-0 overflow is refused |
| | `TestSynthFragmentRoundTrips` | the silent fragment reads back as count copies of the canned frame (M8's `moof` shape) |
| `relay/hls/reader_test.go` | `TestTheSplitterHandsOnTheInitAtTheMoovAndEachMoofWithItsMdat` | the init is handed on at the moov; stray boxes dropped |
| | `TestEOFMidFragmentHandsOnOnlyWholeFragments` | EOF mid-fragment (spec § Testing): whole fragments only |
| | `TestTheSplitterRefusesWhatIsNotFragmentedMP4`, `TestTheSplitterStopsAtItsCallbacksError` | bounded boxes, no moof before a moov, size-0 boxes refused on a pipe |
| | `FuzzParseInit`, `FuzzParseFragment`, `FuzzSplitter` | spec § Testing: the box reader gets `testing.F` fuzz tests (run 20 s each while planning, no finding) |
| `relay/hls/probe_test.go` | `TestParseProbeReadsTheStreams` | D9's JSON |
| | `TestADeclaredButEmptyAudioStreamDoesNotQualify` | spec § Encoder argv's qualifying rule, row 35 |
| | `TestFieldOrderUnknownIsADistinctStateTreatedAsProgressive` | **R28 / Refs #525**: `unknown` is a third state, never interlaced, no deinterlace, R = frame rate |
| | `TestParseRational` | rates, the average-rate fallback, the first video stream wins |
| `relay/hls/argv_test.go` | `TestDecideFixesGeometryRateAndBitrate` | D8: fixed geometry (never upscaled, fit into 1080), R (field rate, capped at 60), G, the bitrate table |
| | `TestTheRenditionSetComesFromGenerationZero` | the rendition set and channel-layout clamp, R20's three renditions |
| | `TestEveryGenerationFillsEveryDeclaredRendition` | rendition filling: copy only at the declared codec and channel count; the reverse direction declares nothing |
| | `TestTheArgv` | § Encoder argv, software and QSV, flag for flag; no lavfi |
| | `TestANonQualifyingAudioStreamIsNotMapped` | row 35, at the argv |
| | `TestSilenceHasNoOutputInTheArgv` | M8: no audio output, no descriptor |
| `relay/hls/store_test.go` | `TestTheMediaPlaylist` | D7's media playlist, byte for byte: tags, maps per generation, discontinuities, PDT on every segment, no ENDLIST |
| | `TestTheDiscontinuitySequenceCountsWhatLeftTheList` | Decision 15 |
| | `TestTheStoreIsBoundedAndServesBySequence` | 12 segments, the byte bound, 404s, init eviction |
| | `TestWaitSegment` | the media-playlist wait's primitive (4a-1b bounds it at 20 s) |
| | `TestTheMultivariant` | § Playlists' multivariant, byte for byte; LANGUAGE only when probed; FRAME-RATE at 59.94 |
| `relay/hls/silence_test.go` | `TestSilenceIsExactAndNeverAccumulates` | § Encoder argv's integer arithmetic over 1,800 segments at four timescale pairs: every segment within one frame, never short |
| | `TestSilenceShortSegmentsGetOneFrame` | Decision 12 |
| | `TestCannedFromNeedsASteadyStateFrame` | Decision 12: the steady-state check, edts stripped |
| | `TestSilenceArgvIsBoundedAndHasNoOtherInput` | the canned encode's argv |
| `relay/hls/detect_test.go` | `TestDetection`, `TestDetectArgv` | D11 and row 34: missing device, passing and failing detection, caching, `MarkUnusable` |
| `relay/hls/feed_test.go` | `TestFeedStopsAtTheNextBoundary` | D10 and row 32: the writer stops **at** the boundary chunk; its own start is not a boundary |
| | `TestFeedLimitStopAndWriteFailure`, `TestArrival` | the probe's byte bound, cancellation, a dead reader, the PDT anchor |
| `relay/hls/pipeline_test.go` (stand-in) | `TestAGenerationThatDiesBeforeItsFirstSegmentIsRetriedOnceThenFails` | D11: one retry on the same engine, then `ErrFailed`, logged at ERROR with the last stderr lines |
| | `TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff` | D11, finding 5, row 34: QSV, QSV, then software on the same input; Quick Sync stays usable |
| | `TestQuickSyncIsWrittenOffOnlyWhenSoftwareSucceedsAndRedetectionFails` | D11, row 34: both halves of the write-off rule |
| | `TestAGenerationThatIgnoresItsInputClosingIsKilledAfterTheGrace` | D10's exit grace |
| | `TestEOFMidFragmentSegmentsOnlyTheWholeFragments` | spec § Testing: EOF mid-fragment, end to end |
| | `TestDeathsAfterTheFirstSegmentRestartUntilTheThirdWithinAMinute` | § Encoder argv, failure: a death restarts at the head with a discontinuity; the third in 60 s is `ErrFailed` |
| | `TestAProbeWithNoVideoOrNoAnswerFails` | D9's `ErrNoVideo`; an unreadable probe is `ErrFailed` |
| | `TestAnOutputThatIsNotFragmentedMP4EndsTheGeneration` | a malformed output kills its process rather than stalling it |
| | `TestSegmentsAreAlignedAcrossRenditions` | Decisions 3 and 6: tfdt moved by the empty edit; audio in its video span |
| | `TestASilentRenditionIsWrittenByTheRelay` | M8 end to end: canned init, every silent segment within one frame of its video |
| | `TestStopEndsTheGeneration`, `TestStartNeedsASourceAndMultivariantNeedsReady` | the lifecycle API 4a-1b calls |
| | `TestATailWithNoAudioIsNotPublished` | Decision 7 |
| | `TestAStoppedAudioOutputDoesNotStallTheVideo` | Decision 6's `AudioWait` |
| | `TestSegmentsAccumulateToTheGridAndCutOnlyAtASyncSample` | D6 and row 31: accumulation to the grid, no cut before a non-sync fragment |
| `relay/hls/real_test.go` (real ffmpeg) | `TestRealThe1080iFixtureGivesAligned2sSegmentsOnThreeRenditions` | spec § 4a-1a's first test and row 31: 12 s of `h264-1080i-aac-ac3`, three renditions, CODECS, 2.000 s ± one frame, sync starts, audio within one fragment |
| | `TestRealTheEAC3FixtureGivesThreeAudioRenditions` | R20: `aac` and `ac3` encoded from E-AC-3, `eac3` copied |
| | `TestRealADeclaredButEmptyAudioPIDIsNotMapped` | row 35: the source 4a-0 handed off, built by stripping PID 0x302 |
| | `TestRealTheNoAudioFixtureGetsRelaySynthesisedSilence` | M8: exit within 1 s of stdin EOF, no audio output, silent segments within one frame |
| | `TestRealEAC3SilenceAfterABoundary` | spec: E-AC-3 silence, which M8 did not prototype; AC-3 5.1 silence too |
| | `TestRealABoundaryGivesTwoGenerationsAndADiscontinuity` | rows 32 and 33: two fixtures, different PIDs, two generations, DISCONTINUITY + new MAP, generation 1 probed at the boundary; the reverse rendition direction |
| | `TestRealTheRenditionSetSurvivesABoundaryAndIsFilled` | finding 5's rendition filling: `ac3` keeps growing across 1080i → MPEG-2 + MP2 |
| | `TestRealDetectionWithoutQuickSyncGivesSoftware` | row 34 against the real ffmpeg |
| | `TestRealEveryCannedSilenceEncodes` | every (codec, layout) of the bitrate table encodes a steady frame |

**Break-checks.** Each wrong edit is applied alone to the tree Appendix A produced, the named test run with `cd relay && go test -count=1 -race -run '<test>' <package>`, the red message compared with the one recorded here (observed while planning on the planner's Mac with Homebrew ffmpeg 9.0.1; a line number may drift by a few lines), and the edit reverted. BC1-BC6 are the spec's six (`:1219-1228`), BC1 and BC3 in the forms § Deviations explains; BC7-BC12 are this plan's own, one for each decision a reviewer would otherwise take on trust.

- **BC1 — the encoder survives the switch** (spec: "remove the restart at a boundary"). `relay/hls/feed.go`: `if has && index >= boundary {` → `if has && index >= boundary && limit > 0 {` (only the probe's feed, which has a byte limit, still stops at a boundary; the generation's is fed straight across it). `TestRealABoundaryGivesTwoGenerationsAndADiscontinuity` reddens: `real_test.go:434: generation 1 produced no segments after the boundary (generations: map[0:3])` — M3 reproduced: one encoder fed `mpeg2-576i-mp2` then `h264-eac3` (different PIDs) silently drops the second and exits cleanly. *Why not remove boundaries from `feed` outright:* then the probe also reads across the boundary, sees both sources' streams, plans an E-AC-3 rendition from the second source's PMT, and the generation fails on `-map 0:i:0x601` matching nothing — red, but for a different reason than the one this check names.
- **BC2 — probe generation 1 from JoinBehind.** `relay/hls/pipeline.go`, in `run`: `probe, err := p.probe(ctx, gen, start)` → `probe, err := p.probe(ctx, gen, ring.Join(p.cfg.JoinBehind))`. Same test: `real_test.go:425: generation 1's probe describes mpeg2video + mp2, want the second source (h264 + eac3): it did not read from the boundary`.
- **BC3 — the moov error** (spec: "drop `delay_moov`"; see Deviation 1). `relay/hls/argv.go`: `const fragFlags = "frag_keyframe+delay_moov+default_base_moof"` → `"frag_keyframe+empty_moov+default_base_moof"`. `TestRealThe1080iFixtureGivesAligned2sSegmentsOnThreeRenditions` reddens: `real_test.go:236: the pipeline failed: hls: the HLS output failed`, its log carrying `level=WARN msg="HLS encoder stderr" … line="[mp4 @ …] Cannot write moov atom before AC3 packets. Set the delay_moov flag to fix this."` and `level=ERROR msg="the HLS output failed: every attempt at a generation exited before its first segment"`. (With `delay_moov` simply removed the test stays green on ffmpeg 9.0.1: measured.)
- **BC4 — mark QSV unusable on any early failure.** `relay/hls/pipeline.go`, in `generation`, after `p.log.Warn("an HLS generation exited before its first segment; retrying", …)` add `p.det.MarkUnusable()`. `TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff` reddens: `pipeline_test.go:205: a source-caused early failure wrote Quick Sync off: the detector now answers software`.
- **BC5 — an `anullsrc` input in the no-audio argv.** `relay/hls/argv.go`, in `Output.Argv`: after `"-f", "mpegts", "-i", "pipe:0",` add `"-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",`, and after `"-f", "mp4", "-movflags", fragFlags, "pipe:1",` add `"-map", "1:a", "-c:a", "aac", "-f", "null", "-",` (an input that is read, as M8's was). `TestRealTheNoAudioFixtureGetsRelaySynthesisedSilence` reddens, timing out: `real_test.go:338: the generation took 20.003795042s to exit after its stdin closed; want < 1s` — it never exited, and the real tests' 20 s exit grace killed it (Decision 20).
- **BC6 — rebuild the rendition set from generation 1's probe.** `relay/hls/pipeline.go`, in `run`: `first := p.output == nil` → `first := true`. `TestRealTheRenditionSetSurvivesABoundaryAndIsFilled` reddens: `real_test.go:470: segment 3 (generation 1) has no ac3 part: the ac3 rendition stopped growing`.
- **BC7 — no tfdt rewrite** (Decision 3). `relay/hls/pipeline.go`, in `attempt`'s `onFrag`: `shiftStart(&f, info.StartOffset)` → `shiftStart(&f, 0)`. `TestSegmentsAreAlignedAcrossRenditions` reddens: `pipeline_test.go:414: segment 0's video starts at 0.000 s, want its tfdt moved by the 0.86 s empty edit` (and the same for segments 1-3).
- **BC8 — silence from a running sum** (the M8 prototype's shape the spec forbids, `:499-502`). `relay/hls/silence.go`: add a field `lastEnd uint64` to `silenceClock`, and in `segment` replace `end := s.endIndex(endRel, tv)` with `end := s.next + (endRel-s.lastEnd)*uint64(s.canned.Track.Timescale)/(uint64(tv)*spf)` followed by `s.lastEnd = endRel` (a per-segment floor). `TestSilenceIsExactAndNeverAccumulates` reddens: `silence_test.go:49: AAC against 50p at 12800 Hz: after segment 1 the silence ends -0.0160 s from its video, want within one frame (0.0213 s) and never short`.
- **BC9 — publish an audio-less tail** (Decision 7). `relay/hls/segmenter.go`, in `publishOneLocked`: delete the four lines `if last { empty = append(empty, t.name); continue }`. `TestATailWithNoAudioIsNotPublished` reddens: `pipeline_test.go:531: the tail segment, with no audio on aac, was published`.
- **BC10 — fold `unknown` into interlaced** (R28, Refs #525). `relay/hls/probe.go`, in `parseFieldOrder`: `case "tt", "bb", "tb", "bt":` → `case "tt", "bb", "tb", "bt", "unknown":`. `TestFieldOrderUnknownIsADistinctStateTreatedAsProgressive` reddens: `probe_test.go:71: field_order "unknown" = interlaced, want unknown`.
- **BC11 — drop the old connection's pending packets at a boundary** (Decision 1). `relay/buffer/ring.go`, in `MarkBoundary`: `if len(r.pending) > 0 && !r.closed {` → `if false && len(r.pending) > 0 && !r.closed {`. Run `-run 'MarkBoundary|Boundary' ./buffer ./channel`: `boundary_test.go:26: MarkBoundary = 2 with head 1, want the pending packets published as chunk 2 and the boundary at 3` (buffer), and in `relay/channel` `boundary_test.go:60: connection 2: NextBoundary(1) = 2, true, want 3` and `boundary_test.go:97: the record holds 18 boundaries from 1, want the newest 64 from 8`.
- **BC12 — record no boundary at a connection attempt.** `relay/channel/channel.go`, in `runAttempt`: delete `c.markBoundary()`. `TestEveryConnectionAttemptRecordsASourceBoundary` reddens: `boundary_test.go:60: connection 1: NextBoundary(0) = 0, false, want 1`.

**PR description draft** (fill the `<…>` slots from Tasks 12-14; no closing keyword anywhere):

> **Phase 4a-1a: the HLS packager (inert).** Adds `relay/hls`, which turns a channel's ring into fMP4/CMAF HLS renditions. A probe (at each generation's own start) decides deinterlacing, geometry and which audio streams qualify. One ffmpeg per generation writes video, stereo AAC and AC-3/E-AC-3 on separate pipes, and a segmenter cuts 2-second segments and renders playlists. The encoder restarts at every source boundary, because a surviving encoder silently drops a source with different PIDs (spec M3). Quick Sync when the one-frame detection succeeds, libx264 otherwise, and QSV is only written off for the process when the failure is shown to be the device's. A rendition with no source is relay-synthesised silence, never an ffmpeg input (M8). No route reaches it yet: `go list -deps .` does not list `relay/hls`. Spec D6-D11; ADR 0009. Plan: `docs/superpowers/plans/2026-09-27-phase4-4a1a-hls-packager.md` at `<plan PASS SHA>`.
>
> Also: `relay/ffmpeg` gains `StartPipedExtra` (output pipes from fd 3); `relay/buffer` gains `Ring.MarkBoundary`/`ArrivedAt` and `relay/channel` records the ring index of every source boundary (every connection attempt); the Go coverage floor's "HOW TO MOVE" header states ruling R21/R27; parity rows 31-35 land pinned in a new `phase 4` block. Refs #525 (the probe keeps `field_order=unknown` a third state, treated as progressive; 4a-1d's PR closes it).
>
> **Coverage.** `relay/hls` is unlinked (R27): CI-measured `<n>%` (`-count=1 -race -covermode=atomic`, from the `relay-go-coverage` artifact of run `<id>`), uncovered statements per file: `<file: count (blocks)>`. Linked packages (`relay/buffer`, `relay/channel`, `relay/ffmpeg`): every added statement covered, R21 listing **none**; census `<twelve or more rounds, in order>`, max `<589>`, `missing` unchanged at 589.
>
> **Break-checks:** `<BC1-BC12, one line each: the wrong edit, the test, the red message>`.
>
> **AVPlayer** (planner's scratch run of this code, macOS 27 and the iOS 27 Simulator): see the plan's § What was measured. **QSV on the household host:** `<result, or "first item of 4a-1b's body">`.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## Residual risks and follow-ups

- **The probe's share of the failover gap** (Defect 3): up to 8 s per later generation, and up to 3 s of zap time at generation 0. Q6 (4a-1b's E2E) should record it; changing D9's bound is a spec decision.
- **A host that cannot encode in real time** keeps flushing after stdin closes; at a boundary the 5 s `GenerationExitGrace` then kills the generation and its last segments are lost (Decision 20). Only the old generation's tail is affected, never the channel. R29 already gives 4a-1b the 1080i-on-CI real-time measurement; the same run shows whether this bites.
- **The zero-sample mid-generation audio fragment** (Decision 6) is unmeasured on AVPlayer: only the tail case was (Decision 7). It is reached only when an audio output stops for a whole `AudioWait`; if 4a-1b's manual gate shows a stall there, dropping is the same one-line choice Decision 7 made.
- **Q1**: the QSV argv has not run on Quick Sync (spec § Risks); no QSV claim is made until the owner's run.
- **tvOS** (Q2-Q4) was not available to the planner.
- **Housekeeping, not this PR**: the spec's Done log rows for #523 and #526 (Defect 7); the parity preamble's scope sentence (Defect 6, 4a-1b).

## Overlap

No sibling Phase 4 plan is open. 4a-0 (#526) is merged and is only read (its `make-asset.sh` builds the fixtures). 4a-1b is the first consumer: it constructs `hls.Pipeline` through `Channel.AttachOutput`, serves `Store`, sets the channel's `hlsFailedUntilBoundary` mark from `ErrFailed`, links `relay/hls` (re-baselining `packages=` per R27, with this plan's per-file listing as the first of its two amounts), widens the parity matrix's scope sentence to HLS, and records Q1. The API it builds on is listed in § Decisions, 17.

## Review changelog

- Round 0 (this draft): written against the seed `97675e88`.

## Appendix A — the diff

Apply at the seed with `git apply --whitespace=error`. It creates `relay/hls/` (25 files), `relay/channel/boundary.go`, `relay/internal/relaytest/hls.go` and four test files outside `relay/hls/`, and modifies seven files.

<!-- appendix-A-begin -->
```diff
diff --git a/docs/relay-parity-matrix.md b/docs/relay-parity-matrix.md
index 8c66be19..3ef2fdbd 100644
--- a/docs/relay-parity-matrix.md
+++ b/docs/relay-parity-matrix.md
@@ -154,7 +154,9 @@ content everywhere is the consistent choice, and this constraint is its price.
 ## The matrix
 
 Blocks, in file order: rows owed by 2a-4, then 2a-3, 2a-6, 2a-5 and 2b-3, then the rows already
-pinned, then the `white-box-only` rows. Add a row to the end of its own block, and keep the
+pinned, then the `white-box-only` rows, then Phase 4's rows (`<!-- block: phase 4 -->`, spec
+`docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` § Testing and gates, each
+landing pinned in the PR that makes its behaviour). Add a row to the end of its own block, and keep the
 `<!-- block: … -->` line above it — it is what puts two lines between one PR's last row and the next
 PR's first, which is the distance git needs to merge them cleanly.
 
@@ -197,4 +199,10 @@ PR's first, which is the distance git needs to merge them cleanly.
 | 27 | Not held to: `_execute_redis_command` swallows every Redis exception to `None` after one reconnect attempt, so a caller cannot distinguish "key absent" from "Redis unreachable" | retired: `_execute_redis_command` swallowing every Redis exception to None, deleted with apps/proxy/live_proxy/ in stage 2d-4; spec D2 removes Redis from the live path, so there is no analogous call in the Go relay to cite | `white-box-only` | Deleted, not ported: spec D2 removes Redis from the live path entirely, so there is no analogous call in the Go relay to swallow anything. One of the three fail-open paths `CLAUDE.md` records as a live defect |
 | 29 | The buffering failover detector is ffmpeg-exclusive: on the Proxy and Redirect Stream Profiles `buffering_speed` and `buffering_timeout` are read and then never consulted — no `ffmpeg_speed` is ever written, `state` never becomes `buffering`, and no `channel_buffering` event is raised, however far below the threshold the upstream runs | `relay/channel/source_proxy.go:40-55`, `relay/channel/stats.go:10-25`, `relay/channel/channel.go:120-135` | `relay/httpapi/transcode_test.go::TestTheProxyProfileStreamsWithNoFfmpegAndNoStats` | Found by 2a-4, which wrote the test and recorded that the row was 2a-7's to add; inherited here rather than absorbed. Externally observable — an operator who raises `buffering_speed` on a Proxy channel gets no failover and no indication the setting did nothing, and nothing in the UI says so. D5 is strict parity, so the Go relay reproduces the inertness. The Go pin is 2c-4's, the first PR in which both architectures exist and the row can fail: buffering_speed at the API maximum on a Proxy tune, no speed reported, state never buffering, none of the seven ffmpeg-derived keys on the payload. |
 | 30 | A credential an authenticator explicitly REJECTS (a malformed Bearer JWT, an unknown API key) is refused 401; a credential merely DECLINED — no header presented at all — falls through to the anonymous principal, which still streams an ordinary channel by UUID | `apps/proxy/authorize.py:258-259` (`except AuthenticationFailed: raise AuthorizeDenied(401, ...)`) vs `apps/proxy/authorize.py:260-265` (`except APIException: return None`, and the no-match fall-through), over the authenticator set at `apps/proxy/authorize.py:93-97` | `relay/httpapi/authorize_test.go::TestADenialReachesTheViewerWithItsOwnStatus` | Found by 2a-5, recorded as a porting hazard in a docstring only; inherited by 2a-7 and pinned here. A port that flattens both exits to "anonymous" fails no other test in the suite, and the failure it introduces is silent — a request carrying a credential the control plane rejected streams anyway. **The pin is driven at `GET /_dispatcharr/authorize`, not at `/proxy/ts/stream/<uuid>` directly** — `stream_ts` is `@api_view` with no `authentication_classes` override, so DRF's own `dispatch()` runs the project `DEFAULT_AUTHENTICATION_CLASSES` (`JWTAuthentication`, `ApiKeyAuthentication`) and refuses a rejected Bearer token or API key with DRF's own body shape *before* `resolve_authorization()`/`_drf_user()` ever runs — verified for both credential types by driving each directly at the stream URL and reading the response body, not assumed. A Go relay that faithfully ports this module and is then driven at a bare streaming URL with no `auth_request` in front of it would diverge from Python's behaviour there not because the port got `authorize.py` wrong, but because Python itself never runs `_drf_user`'s disposition logic on that path for these two credential types — a D5 parity fact about which surface makes this decision, not a footnote. Filed as [#247](https://github.com/D10Scot/Dispatcharr/issues/247), a 2c carry-forward in the same shape as #235, for the implementer who is not reading this table row by row. The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
+<!-- block: phase 4 -->
+| 31 | An HLS generation's segments are 2.000 s plus or minus one frame, each starting with a sync sample: the segmenter accumulates the encoder's fragments until the 2 s grid from the generation's first video frame is reached and cuts only before a fragment that opens on a sync sample | `relay/hls/segmenter.go:227-264`, `relay/hls/argv.go:313-358` | `relay/hls/real_test.go::TestRealThe1080iFixtureGivesAligned2sSegmentsOnThreeRenditions`, `relay/hls/pipeline_test.go::TestSegmentsAccumulateToTheGridAndCutOnlyAtASyncSample` | Phase 4a-1a (spec D6, D8). The real pin runs 12 s of the 4a-0 `h264-1080i-aac-ac3` fixture through the software transcode (`-force_key_frames expr:gte(t,n_forced*2)`, `-g` and `-keyint_min` at round(2R)) and checks every segment but the generation's flushed last one. The stand-in pin feeds one-second fragments, a non-sync one on a grid line included, so the accumulation and the sync rule are held without a real encoder. Inert until 4a-1b serves the store. |
+| 32 | A source boundary (every new upstream connection: a failover or a same-URL reconnect) ends the HLS generation at the boundary's first chunk, and the next generation's first segment carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` while the media sequence continues | `relay/channel/boundary.go:38-63`, `relay/channel/channel.go:603-605`, `relay/hls/feed.go:61-104`, `relay/hls/store.go:119-148`, `relay/hls/store.go:221-253` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity`, `relay/channel/boundary_test.go::TestEveryConnectionAttemptRecordsASourceBoundary` | Phase 4a-1a (spec D10, M3). The real pin feeds two 4a-0 fixtures with different PIDs across a recorded boundary; one encoder fed straight across it silently drops the second source, which is the break-check. `buffer.Ring.MarkBoundary` publishes the old connection's pending whole packets before the boundary, so the chunk at the boundary index is the new connection's own. |
+| 33 | Each HLS generation is probed where it starts: the first from the join point behind live, every later one from its boundary index, so the second generation's probe describes the second source | `relay/hls/pipeline.go:289-370`, `relay/hls/pipeline.go:390-430` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity` | Phase 4a-1a (spec D9). The probe's feed stops at the next boundary as the generation's does, and is bounded at 5 MB or 8 s; on an MPEG-TS pipe ffprobe reads to the 8 s bound (measured), which is the probe's share of the failover gap (Q6). |
+| 34 | With no usable Quick Sync the HLS encoder runs in software and never refuses: a missing render node, a failing one-frame detection encode or its timeout selects libx264, and Quick Sync is written off for the process only when a software retry succeeds where it failed and the detection encode, re-run, fails | `relay/hls/detect.go:79-140`, `relay/hls/pipeline.go:455-487` | `relay/hls/detect_test.go::TestDetection`, `relay/hls/real_test.go::TestRealDetectionWithoutQuickSyncGivesSoftware`, `relay/hls/pipeline_test.go::TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff`, `relay/hls/pipeline_test.go::TestQuickSyncIsWrittenOffOnlyWhenSoftwareSucceedsAndRedetectionFails` | Phase 4a-1a (spec D11, finding 5). The QSV argv itself has not run on Quick Sync hardware (Q1); these pins hold the selection and the write-off rule, not the device. |
+| 35 | An audio stream that does not qualify (no known codec, 0 channels or a 0 sample rate, which is what a PMT-declared PID carrying no packets probes as) declares no HLS rendition and is never mapped into the encoder's argv | `relay/hls/probe.go:135-141`, `relay/hls/argv.go:112-142`, `relay/hls/argv.go:245-279` | `relay/hls/real_test.go::TestRealADeclaredButEmptyAudioPIDIsNotMapped`, `relay/hls/argv_test.go::TestANonQualifyingAudioStreamIsNotMapped` | Phase 4a-1a (spec § Encoder argv, finding 7). Mapping such a stream fails every output of the generation (ffmpeg 9.0.1: `sample rate not set`). The real pin strips the AC-3 PID's packets from the 4a-0 1080i fixture and keeps its PMT entry. |
 <!-- end of matrix -->
diff --git a/e2e/tests/guards/parity-matrix.ts b/e2e/tests/guards/parity-matrix.ts
index 89898176..a76bdc8a 100644
--- a/e2e/tests/guards/parity-matrix.ts
+++ b/e2e/tests/guards/parity-matrix.ts
@@ -592,7 +592,7 @@ export const WHITE_BOX_ONLY: readonly WhiteBoxRow[] = [
  * close a row** — rows are added only by a deliberate extension of the matrix,
  * which is exactly the edit that should take two places and a stated reason.
  */
-export const HIGHEST_ROW_ID = 30;
+export const HIGHEST_ROW_ID = 35;
 
 /**
  * Gate 1's own switch. Flipped to `true` by the PR that closes the last owed
diff --git a/relay/buffer/boundary_test.go b/relay/buffer/boundary_test.go
new file mode 100644
index 00000000..8d093ff6
--- /dev/null
+++ b/relay/buffer/boundary_test.go
@@ -0,0 +1,83 @@
+package buffer
+
+import (
+	"testing"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
+)
+
+// Phase 4 spec, D10: MarkBoundary ends one upstream connection's bytes. The
+// whole packets still pending are published as one short final chunk -- no
+// byte a TS client was due is lost -- and the carried partial packet is
+// dropped, so the chunk at the returned index is the NEXT connection's own,
+// with none of the old source's packets in front of it.
+func TestMarkBoundaryEndsTheOldConnectionsBytes(t *testing.T) {
+	r := newTestRing(t, nil)
+	old := relaytest.SyntheticTS(6, 0x100) // one 4-packet chunk and two pending
+	if _, err := r.Write(append(old, 0x47, 0x01, 0x02)); err != nil {
+		t.Fatal(err)
+	}
+	if r.Head() != 1 {
+		t.Fatalf("head %d before the boundary, want 1", r.Head())
+	}
+	boundary := r.MarkBoundary()
+	if boundary != 3 || r.Head() != 2 {
+		t.Fatalf("MarkBoundary = %d with head %d, want the pending packets published as chunk 2 and the boundary at 3", boundary, r.Head())
+	}
+	chunks, _, _ := r.Read(1)
+	if len(chunks) != 1 || len(chunks[0]) != 2*TSPacketSize || relaytest.AlignmentProblem(chunks[0]) != "" {
+		t.Fatalf("chunk 2 is %d bytes, want the old connection's two pending packets, whole", len(chunks[0]))
+	}
+	next := relaytest.SyntheticTS(4, 0x200)
+	if _, err := r.Write(next); err != nil {
+		t.Fatal(err)
+	}
+	chunks, _, _ = r.Read(2)
+	if len(chunks) != 1 || relaytest.AlignmentProblem(chunks[0]) != "" || relaytest.PacketPID(chunks[0]) != 0x200 {
+		t.Fatalf("the chunk at the boundary does not open with the new connection's whole packets")
+	}
+	if again := r.MarkBoundary(); again != 4 || r.Head() != 3 {
+		t.Fatalf("a boundary with nothing pending = %d (head %d), want 4 with nothing published", again, r.Head())
+	}
+}
+
+// After a failover's ResetPosition there is nothing to publish, and a closed
+// ring publishes nothing either.
+func TestMarkBoundaryAfterResetOrCloseOnlyReportsTheIndex(t *testing.T) {
+	r := newTestRing(t, nil)
+	_, _ = r.Write(relaytest.SyntheticTS(2, 0x100))
+	r.ResetPosition()
+	if b := r.MarkBoundary(); b != 1 || r.Head() != 0 {
+		t.Fatalf("after ResetPosition MarkBoundary = %d with head %d, want 1 and nothing published", b, r.Head())
+	}
+	_, _ = r.Write(relaytest.SyntheticTS(2, 0x100))
+	r.Close()
+	if b := r.MarkBoundary(); b != 1 || r.Head() != 0 {
+		t.Fatalf("a closed ring published at a boundary: %d, head %d", b, r.Head())
+	}
+}
+
+// ArrivedAt is a chunk's publish time, for relay/hls's PDT anchor (D7), and
+// false for an index the ring does not hold.
+func TestArrivedAt(t *testing.T) {
+	clock := &fakeClock{at: time.Date(2026, 9, 27, 12, 0, 0, 0, time.UTC)}
+	r := newTestRing(t, clock.now)
+	if _, ok := r.ArrivedAt(1); ok {
+		t.Fatal("an empty ring reported an arrival")
+	}
+	_, _ = r.Write(relaytest.SyntheticTS(4, 0x100))
+	clock.advance(time.Second)
+	_, _ = r.Write(relaytest.SyntheticTS(4, 0x100))
+	if at, ok := r.ArrivedAt(2); !ok || !at.Equal(clock.now()) {
+		t.Fatalf("ArrivedAt(2) = %v, %t, want the second publish's time", at, ok)
+	}
+	if at, ok := r.ArrivedAt(1); !ok || !at.Equal(clock.now().Add(-time.Second)) {
+		t.Fatalf("ArrivedAt(1) = %v, %t", at, ok)
+	}
+	for _, index := range []uint64{0, 3} {
+		if _, ok := r.ArrivedAt(index); ok {
+			t.Fatalf("ArrivedAt(%d) reported a chunk the ring does not hold", index)
+		}
+	}
+}
diff --git a/relay/buffer/ring.go b/relay/buffer/ring.go
index 707e9535..a3bf65a1 100644
--- a/relay/buffer/ring.go
+++ b/relay/buffer/ring.go
@@ -86,11 +86,12 @@ type Config struct {
 // Ring is one channel's in-memory buffer: the packetiser, the monotonic chunk
 // index, the bounded chunk store and the reader wake-up.
 //
-// CONCURRENCY. One writer goroutine calls Write, ResetPosition and Close; any
-// number of reader goroutines call Read, Head, Join, Oldest and Wait. Every
-// field below is guarded by mu -- writers take Lock, readers take RLock. The
-// only thing that leaves the lock is a Chunk's Data slice header, which is
-// safe precisely because of the immutability rule on Chunk.
+// CONCURRENCY. One writer goroutine calls Write, ResetPosition, MarkBoundary
+// and Close; any number of reader goroutines call Read, Head, Join, Oldest,
+// ArrivedAt and Wait. Every field below is guarded by mu -- writers take
+// Lock, readers take RLock. The only thing that leaves the lock is a Chunk's
+// Data slice header, which is safe precisely because of the immutability
+// rule on Chunk.
 //
 // WHAT -race SHOULD CATCH IF THIS IS WRONG. Reading head, chunks or notify
 // without the lock is an unsynchronised access the detector reports directly.
@@ -240,6 +241,62 @@ func (r *Ring) ResetPosition() {
 	r.pending = nil
 }
 
+// MarkBoundary ends the byte stream of one upstream connection and returns
+// the index the NEXT connection's first chunk will be published at: a source
+// boundary (Phase 4 spec, D10). The channel calls it as each connection
+// attempt starts, so that relay/hls can stop a generation's input exactly
+// where one provider's bytes end and another's begin.
+//
+// THE OLD CONNECTION'S WHOLE PACKETS ARE PUBLISHED, NOT DROPPED. Bytes still
+// in pending would otherwise be prepended to the new connection's first
+// chunk, so the chunk at the returned index would open with the old source's
+// PAT, PMT and PIDs -- exactly the mixed input an encoder silently drops a
+// source over (spec M3), and what a probe at the boundary would misdescribe.
+// Publishing them as one short final chunk keeps every byte a TS client was
+// going to receive, and makes the chunk at the returned index the new
+// connection's own. A chunk shorter than chunkBytes is harmless to every
+// reader: nothing in this module assumes a chunk's length.
+//
+// THE CARRIED PARTIAL PACKET IS DROPPED, as ResetPosition drops it: fewer
+// than 188 bytes that the old connection never finished can only corrupt the
+// new connection's first packet. After a failover ResetPosition has already
+// cleared both, so this publishes nothing.
+//
+// Like ResetPosition it never rewinds head (parity-matrix row 7).
+func (r *Ring) MarkBoundary() uint64 {
+	r.mu.Lock()
+	defer r.mu.Unlock()
+	r.partial = nil
+	if len(r.pending) > 0 && !r.closed {
+		data := make([]byte, len(r.pending))
+		copy(data, r.pending)
+		r.pending = r.pending[:0]
+		r.head++
+		r.evictLocked()
+		r.chunks = append(r.chunks, Chunk{Index: r.head, At: r.now(), Data: data})
+		close(r.notify)
+		r.notify = make(chan struct{})
+	}
+	return r.head + 1
+}
+
+// ArrivedAt is when the chunk at index was published, and false when that
+// chunk is not (or no longer) in the ring. relay/hls anchors a generation's
+// EXT-X-PROGRAM-DATE-TIME on it (spec D7): the arrival of the generation's
+// first chunk, never the moment the encoder got round to it.
+func (r *Ring) ArrivedAt(index uint64) (time.Time, bool) {
+	r.mu.RLock()
+	defer r.mu.RUnlock()
+	if len(r.chunks) == 0 {
+		return time.Time{}, false
+	}
+	oldest := r.chunks[0].Index
+	if index < oldest || index > r.head {
+		return time.Time{}, false
+	}
+	return r.chunks[index-oldest].At, true
+}
+
 // Head is the highest index published so far, 0 before the first chunk.
 func (r *Ring) Head() uint64 {
 	r.mu.RLock()
diff --git a/relay/channel/boundary.go b/relay/channel/boundary.go
new file mode 100644
index 00000000..4270387e
--- /dev/null
+++ b/relay/channel/boundary.go
@@ -0,0 +1,63 @@
+package channel
+
+import "sync"
+
+// maxBoundaries is how many source boundaries a channel remembers. A
+// generation needs only the first boundary after its own start, and the ring
+// holds at most 300 chunks (relay/buffer), so a boundary older than the
+// oldest chunk can never be asked for again. Sixty-four is far more
+// connections than a 60-second ring can span and costs 512 bytes.
+const maxBoundaries = 64
+
+// boundaryLog is the channel's record of where each upstream connection's
+// bytes begin in the ring (Phase 4 spec, D10): "a boundary is every new
+// upstream connection: an applySwitch, or a reconnect of the same URL. The
+// channel records the ring index of the boundary's first chunk."
+//
+// It is embedded in Channel, as outputRegistry is, with a mutex of its own:
+// the run loop writes it and relay/hls's generation writers read it, and
+// neither should contend with mu, which guards the client registry and the
+// switch bookkeeping.
+//
+// NOTHING IN THIS MODULE READS IT YET. Phase 4a-1a lands the record and
+// relay/hls, which asks NextBoundary, unlinked; 4a-1b wires the two
+// together. Recording costs one mutex and one append per connection attempt.
+type boundaryLog struct {
+	boundaryMu sync.Mutex
+	// boundaries is strictly increasing: an attempt that published nothing
+	// leaves the ring's head where it was, so the next attempt's boundary is
+	// the same index and is not recorded twice.
+	boundaries []uint64
+}
+
+// markBoundary records that a new upstream connection is about to write, at
+// the index buffer.Ring.MarkBoundary returns. Called by runAttempt, on the
+// run goroutine, before the Source runs -- so the index is on record before
+// the first chunk at it can be published, which is what lets a reader that
+// has seen that chunk trust NextBoundary to report it.
+func (c *Channel) markBoundary() {
+	index := c.ring.MarkBoundary()
+	c.boundaryMu.Lock()
+	defer c.boundaryMu.Unlock()
+	if n := len(c.boundaries); n > 0 && c.boundaries[n-1] >= index {
+		return
+	}
+	c.boundaries = append(c.boundaries, index)
+	if len(c.boundaries) > maxBoundaries {
+		c.boundaries = append(c.boundaries[:0], c.boundaries[len(c.boundaries)-maxBoundaries:]...)
+	}
+}
+
+// NextBoundary is the first source boundary strictly after the ring index
+// after, and false when there is none yet. A boundary is the index of the
+// first chunk a new upstream connection published (or will publish).
+func (c *Channel) NextBoundary(after uint64) (uint64, bool) {
+	c.boundaryMu.Lock()
+	defer c.boundaryMu.Unlock()
+	for _, index := range c.boundaries {
+		if index > after {
+			return index, true
+		}
+	}
+	return 0, false
+}
diff --git a/relay/channel/boundary_test.go b/relay/channel/boundary_test.go
new file mode 100644
index 00000000..9439feb0
--- /dev/null
+++ b/relay/channel/boundary_test.go
@@ -0,0 +1,99 @@
+package channel
+
+import (
+	"context"
+	"io"
+	"testing"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/buffer"
+	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
+)
+
+// connectionSource writes six whole packets with a PID of its own per run --
+// 0x100 on the first connection, 0x101 on the second -- and three stray
+// bytes, then fails, so every run is a new upstream connection whose bytes
+// the ring can tell apart. Its last run stays connected.
+type connectionSource struct {
+	runs *int32Counter
+	last int
+}
+
+func (s connectionSource) Run(ctx context.Context, sink io.Writer) error {
+	s.runs.inc()
+	run := s.runs.get()
+	if _, err := sink.Write(append(relaytest.SyntheticTS(6, 0xff+run), 0x47, 0x01, 0x02)); err != nil {
+		return err
+	}
+	if run >= s.last {
+		<-ctx.Done()
+		return ctx.Err()
+	}
+	return &ErrUpstreamStatus{Status: 502}
+}
+
+// Phase 4 spec, D10: "a boundary is every new upstream connection: an
+// applySwitch, or a reconnect of the same URL. The channel records the ring
+// index of the boundary's first chunk." Three connections to one URL (two
+// same-URL reconnects) give three boundaries, each the index of the first
+// chunk the new connection published, with the previous connection's
+// pending packets published whole before it.
+func TestEveryConnectionAttemptRecordsASourceBoundary(t *testing.T) {
+	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
+	t.Cleanup(m.StopAll)
+	runs := &int32Counter{}
+	ch, release := attachWith(t, m, "boundaries", connectionSource{runs: runs, last: 3}, testTuning(), nil)
+	defer release()
+	// Every byte of all three connections has been written once the ring
+	// has counted them: six packets and three stray bytes each.
+	const perConnection = 6*buffer.TSPacketSize + 3
+	waitFor(t, "the third connection's bytes", 10*time.Second, func() bool { return ch.Ring().TotalBytes() >= 3*perConnection })
+
+	// Per connection: one 4-packet chunk on its own PID, then (at the next
+	// boundary) its two pending packets as a short chunk.
+	for i, want := range []struct {
+		after, boundary uint64
+		pid             int
+	}{{0, 1, 0x100}, {1, 3, 0x101}, {3, 5, 0x102}} {
+		got, ok := ch.NextBoundary(want.after)
+		if !ok || got != want.boundary {
+			t.Fatalf("connection %d: NextBoundary(%d) = %d, %t, want %d", i+1, want.after, got, ok, want.boundary)
+		}
+		chunks, _, _ := ch.Ring().Read(got - 1)
+		if len(chunks) == 0 || relaytest.AlignmentProblem(chunks[0]) != "" || relaytest.PacketPID(chunks[0]) != want.pid {
+			t.Fatalf("connection %d's boundary chunk %d is not its own whole packets on PID %#x", i+1, got, want.pid)
+		}
+	}
+	if b, ok := ch.NextBoundary(5); ok {
+		t.Fatalf("a fourth boundary %d with only three connections", b)
+	}
+	flushed, _, _ := ch.Ring().Read(1)
+	if len(flushed[0]) != 2*buffer.TSPacketSize || relaytest.PacketPID(flushed[0]) != 0x100 {
+		t.Fatalf("chunk 2 is %d bytes: the first connection's two pending packets were not published before the boundary", len(flushed[0]))
+	}
+	m.Stop("boundaries")
+}
+
+// An attempt that published nothing leaves the next attempt's boundary at the
+// same index, recorded once; and the record keeps the newest maxBoundaries.
+func TestTheBoundaryRecordIsStrictlyIncreasingAndBounded(t *testing.T) {
+	c := &Channel{ring: buffer.New(buffer.Config{BudgetBytes: buffer.TSPacketSize * 400, ChunkBytes: buffer.TSPacketSize * 4})}
+	c.markBoundary()
+	c.markBoundary()
+	if b, ok := c.NextBoundary(0); !ok || b != 1 {
+		t.Fatalf("NextBoundary(0) = %d, %t", b, ok)
+	}
+	if b, ok := c.NextBoundary(1); ok {
+		t.Fatalf("an attempt that published nothing recorded a second boundary %d", b)
+	}
+	for i := 0; i < maxBoundaries+6; i++ {
+		_, _ = c.ring.Write(relaytest.SyntheticTS(1, 0x100))
+		c.markBoundary()
+	}
+	c.boundaryMu.Lock()
+	n, oldest := len(c.boundaries), c.boundaries[0]
+	c.boundaryMu.Unlock()
+	if n != maxBoundaries || oldest != 8 {
+		t.Fatalf("the record holds %d boundaries from %d, want the newest %d from 8", n, oldest, maxBoundaries)
+	}
+}
diff --git a/relay/channel/channel.go b/relay/channel/channel.go
index 29bf6c62..39a42fd8 100644
--- a/relay/channel/channel.go
+++ b/relay/channel/channel.go
@@ -95,6 +95,9 @@ type Channel struct {
 	// Profile transcodes. Its own mutex, never nested with mu -- see
 	// output.go's lock-order note.
 	outputRegistry
+	// boundaryLog is Phase 4a-1a's: the ring index where each upstream
+	// connection's bytes begin (boundary.go).
+	boundaryLog
 
 	// outputProfiles is the active OutputProfile set as the control plane
 	// last described it, under mu. REPLACED WHOLESALE, never mutated in
@@ -597,6 +600,10 @@ func (c *Channel) runAttempt(ctx context.Context, source Source) error {
 	attemptCtx, cancel := context.WithCancel(ctx)
 	defer cancel()
 
+	// Every attempt is a new upstream connection, a same-URL reconnect as
+	// much as a failover, and so a source boundary (Phase 4 spec, D10).
+	c.markBoundary()
+
 	c.mu.Lock()
 	now := c.now()
 	c.connected = true
diff --git a/relay/ffmpeg/extra_test.go b/relay/ffmpeg/extra_test.go
new file mode 100644
index 00000000..fea3ba7d
--- /dev/null
+++ b/relay/ffmpeg/extra_test.go
@@ -0,0 +1,100 @@
+package ffmpeg
+
+import (
+	"bytes"
+	"errors"
+	"io"
+	"os"
+	"path/filepath"
+	"strings"
+	"testing"
+
+	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
+)
+
+// Phase 4 spec, D6: the HLS encoder's spawn gives the child an output pipe at
+// fd 3+i for every true entry of extra, readable through Extra(i), with the
+// same process group, stdin pipe and exit mapping as StartPiped. A false
+// entry is a descriptor the child does not have: writing to it fails in the
+// child, and the numbering of the others does not move.
+func TestStartPipedExtraGivesTheChildItsOutputPipes(t *testing.T) {
+	t.Setenv(relaytest.StandInEnv, "1")
+	dir := t.TempDir()
+	video := filepath.Join(dir, "video")
+	audio := filepath.Join(dir, "audio")
+	if err := os.WriteFile(video, []byte("video on fd 1"), 0o600); err != nil {
+		t.Fatal(err)
+	}
+	if err := os.WriteFile(audio, []byte("ac-3 on fd 4"), 0o600); err != nil {
+		t.Fatal(err)
+	}
+	command, argv := relaytest.StandInCommand(
+		"--fd-file", relaytest.FDFileArg(1, video),
+		"--fd-file", relaytest.FDFileArg(4, audio),
+		"--wait-stdin-eof")
+	p, err := StartPipedExtra(t.Context(), command, argv, []bool{false, true})
+	if err != nil {
+		t.Fatalf("StartPipedExtra: %v", err)
+	}
+	if p.Extra(0) != nil || p.Extra(2) != nil || p.Extra(-1) != nil {
+		t.Fatalf("Extra returned a pipe the child was not given")
+	}
+	got := make(chan []byte, 2)
+	go func() { b, _ := io.ReadAll(p.Stdout()); got <- b }()
+	go func() { b, _ := io.ReadAll(p.Extra(1)); got <- b }()
+	if _, err := p.Stdin().Write([]byte("input")); err != nil {
+		t.Fatalf("writing fd 0: %v", err)
+	}
+	p.CloseStdin()
+	outputs := []string{string(<-got), string(<-got)}
+	if err := p.Wait(); err != nil {
+		t.Fatalf("Wait: %v", err)
+	}
+	joined := strings.Join(outputs, "|")
+	if !strings.Contains(joined, "video on fd 1") || !strings.Contains(joined, "ac-3 on fd 4") {
+		t.Fatalf("the child's outputs arrived as %q, want fd 1's and fd 4's bytes", outputs)
+	}
+
+	// fd 3 was not given, so a child writing to it fails.
+	command, argv = relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(3, audio))
+	p, err = StartPipedExtra(t.Context(), command, argv, []bool{false, true})
+	if err != nil {
+		t.Fatalf("StartPipedExtra: %v", err)
+	}
+	var stderr bytes.Buffer
+	p.ReadStderr(func(line string) { stderr.WriteString(line) })
+	var exited *ErrExited
+	if err := p.Wait(); !errors.As(err, &exited) || exited.Code != 2 || !strings.Contains(stderr.String(), "fd 3") {
+		t.Fatalf("a write to an fd the child was not given: Wait = %v, stderr %q", err, stderr.String())
+	}
+}
+
+// Nothing is opened for an empty mask; a pipe that cannot be made fails the
+// spawn naming its descriptor; and a spawn that fails closes every pipe it
+// made.
+func TestStartPipedExtraWithoutExtrasAndOnAFailedSpawn(t *testing.T) {
+	calls := 0
+	newPipe = func() (*os.File, *os.File, error) {
+		calls++
+		if calls == 2 {
+			return nil, nil, errors.New("too many open files")
+		}
+		return os.Pipe()
+	}
+	t.Cleanup(func() { newPipe = os.Pipe })
+	if _, err := StartPipedExtra(t.Context(), "ffmpeg", nil, []bool{true, true}); err == nil || !strings.Contains(err.Error(), "fd 4") {
+		t.Fatalf("a failed pipe for fd 4: %v", err)
+	}
+	newPipe = os.Pipe
+
+	read, write, err := extraPipes(nil)
+	if err != nil || read != nil || write != nil {
+		t.Fatalf("extraPipes(nil) = %v, %v, %v", read, write, err)
+	}
+	if _, err := StartPipedExtra(t.Context(), filepath.Join(t.TempDir(), "no-such-ffmpeg"), nil, []bool{true}); err == nil {
+		t.Fatal("a missing executable started")
+	}
+	if _, err := StartPipedExtra(t.Context(), "http://provider.invalid/x", nil, []bool{true}); !errors.Is(err, ErrCommandIsAURL) {
+		t.Fatalf("a URL command: %v", err)
+	}
+}
diff --git a/relay/ffmpeg/spawn.go b/relay/ffmpeg/spawn.go
index 8bf98e1f..0beeff70 100644
--- a/relay/ffmpeg/spawn.go
+++ b/relay/ffmpeg/spawn.go
@@ -49,7 +49,11 @@ type Process struct {
 	// stdin is non-nil only for a process started by StartPiped: the
 	// output-side remux, whose fd 0 is the relay's own ring rather than
 	// /dev/null (output/fmp4/manager.py:36's `-i pipe:0`).
-	stdin     io.WriteCloser
+	stdin io.WriteCloser
+	// extra is the read end of each output pipe beyond fd 2, indexed from
+	// fd 3; a nil entry is a descriptor the child was not given. Non-empty
+	// only for a process started by StartPipedExtra.
+	extra     []*os.File
 	closeOnce sync.Once
 	cancel    context.CancelFunc
 	// ended is closed by Wait once the process has been reaped.
@@ -92,7 +96,7 @@ func (e *ErrExited) Error() string {
 // input-side transcode reads its upstream over the network and never from the
 // relay; a writable stdin here would be a pipe nobody fills.
 func Start(ctx context.Context, command string, argv []string) (*Process, error) {
-	return start(ctx, command, argv, false)
+	return start(ctx, command, argv, false, nil)
 }
 
 // StartPiped is Start with a WRITABLE fd 0, for the output-side remux, whose
@@ -107,10 +111,31 @@ func Start(ctx context.Context, command string, argv []string) (*Process, error)
 // second implementation of the truth" warns about. The ONLY difference is
 // fd 0, and it is one parameter.
 func StartPiped(ctx context.Context, command string, argv []string) (*Process, error) {
-	return start(ctx, command, argv, true)
+	return start(ctx, command, argv, true, nil)
 }
 
-func start(ctx context.Context, command string, argv []string, pipeStdin bool) (*Process, error) {
+// StartPipedExtra is StartPiped with output pipes beyond fd 2: entry i of
+// extra says whether the child gets a pipe at fd 3+i, whose read end Extra(i)
+// returns. It is the HLS encoder's spawn (Phase 4 spec, D6): one ffmpeg reads
+// the channel's ring on fd 0 and writes video on fd 1 and one fragmented-MP4
+// audio rendition per descriptor from fd 3 (`pipe:3`, `pipe:4`, `pipe:5`).
+// A false entry is a descriptor the child does NOT have -- a rendition the
+// relay fills with its own silence this generation -- so the numbering of
+// the others never moves.
+//
+// THE SAME SPAWN, NOT A THIRD ONE, for StartPiped's own reason: the process
+// group, Pdeathsig, the SIGKILL cancel, KillWait and the exit mapping are
+// the contract this package holds once. The pipes are the parent's own
+// os.Pipe pairs, as stderr's is (#304): cmd.Wait never closes an
+// *os.File it did not create, so a reader draining one to EOF cannot have
+// it closed underneath it by a Wait on another goroutine. The parent's write
+// ends close as soon as the child holds its copies, so each reader's EOF is
+// exactly the child's last byte on that descriptor.
+func StartPipedExtra(ctx context.Context, command string, argv []string, extra []bool) (*Process, error) {
+	return start(ctx, command, argv, true, extra)
+}
+
+func start(ctx context.Context, command string, argv []string, pipeStdin bool, extra []bool) (*Process, error) {
 	if strings.Contains(command, "://") {
 		return nil, ErrCommandIsAURL
 	}
@@ -181,9 +206,20 @@ func start(ctx context.Context, command string, argv []string, pipeStdin bool) (
 		return nil, fmt.Errorf("ffmpeg: opening the stderr pipe: %w", err) // credential-logging: ok - an os.Pipe failure, no URL anywhere in it
 	}
 	cmd.Stderr = stderrWrite
+	extraRead, extraWrite, err := extraPipes(extra)
+	if err != nil {
+		closeFiles([]*os.File{stderrRead, stderrWrite})
+		cancel()
+		return nil, err
+	}
+	if len(extraWrite) > 0 {
+		cmd.ExtraFiles = extraWrite
+	}
 	if err := cmd.Start(); err != nil {
 		_ = stderrRead.Close()
 		_ = stderrWrite.Close()
+		closeFiles(extraRead)
+		closeFiles(extraWrite)
 		cancel()
 		// exec.Error carries the command NAME (refused above if it were a
 		// URL); a *fs.PathError carries the executable's path. Neither
@@ -193,7 +229,54 @@ func start(ctx context.Context, command string, argv []string, pipeStdin bool) (
 	// The child holds its own copy now, so the parent's must go or the reader
 	// never sees EOF (#304).
 	_ = stderrWrite.Close()
-	return &Process{cmd: cmd, stdout: stdout, stderr: stderrRead, stdin: stdin, cancel: cancel, ended: make(chan struct{})}, nil
+	closeFiles(extraWrite)
+	return &Process{cmd: cmd, stdout: stdout, stderr: stderrRead, stdin: stdin, extra: extraRead, cancel: cancel, ended: make(chan struct{})}, nil
+}
+
+// newPipe is os.Pipe, a variable so a test can make the extra pipes' own
+// failure path run: an os.Pipe that fails is descriptor exhaustion, which no
+// test can arrange for one call without arranging it for the whole process.
+var newPipe = os.Pipe
+
+// extraPipes makes one pipe per true entry of want, returning the read and
+// write ends indexed as want is, with nil for a false entry. os/exec hands a
+// nil ExtraFiles entry to the child as a closed descriptor.
+func extraPipes(want []bool) (read, write []*os.File, err error) {
+	if len(want) == 0 {
+		return nil, nil, nil
+	}
+	read = make([]*os.File, len(want))
+	write = make([]*os.File, len(want))
+	for i, wanted := range want {
+		if !wanted {
+			continue
+		}
+		r, w, pipeErr := newPipe()
+		if pipeErr != nil {
+			closeFiles(append(read, write...))
+			return nil, nil, fmt.Errorf("ffmpeg: opening the pipe for fd %d: %w", 3+i, pipeErr) // credential-logging: ok - an os.Pipe failure, no URL anywhere in it
+		}
+		read[i], write[i] = r, w
+	}
+	return read, write, nil
+}
+
+// closeFiles closes every non-nil file in files.
+func closeFiles(files []*os.File) {
+	for _, f := range files {
+		if f != nil {
+			_ = f.Close()
+		}
+	}
+}
+
+// Extra is the read end of the output pipe at fd 3+i, and nil when the
+// process was not given one there (StartPipedExtra).
+func (p *Process) Extra(i int) io.Reader {
+	if i < 0 || i >= len(p.extra) || p.extra[i] == nil {
+		return nil
+	}
+	return p.extra[i]
 }
 
 // Stdin is the write end of a StartPiped process's fd 0, and nil for one
@@ -312,6 +395,11 @@ func (p *Process) Wait() error {
 	default:
 	}
 	_ = p.stdout.Close()
+	// The extra output pipes close for stdout's reason: a child still
+	// writing to one after its reader has stopped gets EPIPE rather than
+	// blocking on a full pipe nobody drains. Their readers are the caller's,
+	// and like stdout's they must have finished before Wait is called.
+	closeFiles(p.extra)
 	err := p.cmd.Wait()
 	// exec.CommandContext reports the context's own error once it has
 	// killed the process, which would make "we cancelled it" and "it died
diff --git a/relay/hls/argv.go b/relay/hls/argv.go
new file mode 100644
index 00000000..0ad52dba
--- /dev/null
+++ b/relay/hls/argv.go
@@ -0,0 +1,403 @@
+package hls
+
+import (
+	"errors"
+	"fmt"
+	"strconv"
+)
+
+// Engine is which H.264 encoder a generation runs (spec D11).
+type Engine string
+
+const (
+	// EngineQSV is h264_qsv on Intel Quick Sync, behind hwupload.
+	EngineQSV Engine = "qsv"
+	// EngineSoftware is libx264, the fallback whenever Quick Sync is not
+	// usable. The relay encodes in software and says so; it never refuses.
+	EngineSoftware Engine = "software"
+)
+
+// DefaultDevice is the render node the QSV argv and the detection encode
+// open.
+const DefaultDevice = "/dev/dri/renderD128"
+
+// Rendition names, which are also the path segment a playlist URI uses
+// (spec § Session resources).
+const (
+	RenditionVideo = "video"
+	RenditionAAC   = "aac"
+	RenditionAC3   = "ac3"
+	RenditionEAC3  = "eac3"
+)
+
+// audioOrder is every audio rendition in the order they are declared, listed
+// and given descriptors: aac on fd 3, ac3 on fd 4, eac3 on fd 5 (spec D6).
+// The AAC group is listed first (spec § Playlists).
+var audioOrder = []string{RenditionAAC, RenditionAC3, RenditionEAC3}
+
+// fdFor is the descriptor a rendition's encoder output is written to.
+func fdFor(name string) int {
+	for i, n := range audioOrder {
+		if n == name {
+			return 3 + i
+		}
+	}
+	return -1
+}
+
+// Rendition is one declared audio rendition: fixed at generation 0 for the
+// channel's run, as geometry is (spec § Encoder argv, the rendition set).
+type Rendition struct {
+	// Name is aac, ac3 or eac3.
+	Name string
+	// Channels is the declared layout's channel count, 2 or 6, which is the
+	// multivariant's CHANNELS attribute. Every generation fills the
+	// rendition at exactly this count, so CHANNELS stays true across every
+	// discontinuity.
+	Channels int
+	// Language is the generation-0 source's language tag for this
+	// rendition, emitted as LANGUAGE only when the probe reported one.
+	Language string
+}
+
+// Output is what generation 0's probe fixes for the channel's run (D8): the
+// geometry, the frame rate, the keyframe interval, the bitrate and the
+// declared audio renditions.
+type Output struct {
+	Width, Height int
+	// FrameRate is R: the field rate of an interlaced source, the frame rate
+	// of a progressive one, capped at 60.
+	FrameRate Rational
+	// GOP is G = round(2 x R).
+	GOP int
+	// VideoBitrate and VideoMaxrate are B and M, in bits per second.
+	VideoBitrate, VideoMaxrate int
+	// Audio is the declared audio renditions, in audioOrder. AAC is always
+	// declared.
+	Audio []Rendition
+}
+
+// Declared reports the named audio rendition's declaration.
+func (o Output) Declared(name string) (Rendition, bool) {
+	for _, r := range o.Audio {
+		if r.Name == name {
+			return r, true
+		}
+	}
+	return Rendition{}, false
+}
+
+// Renditions is every rendition the run serves: video and then the audio
+// renditions in order.
+func (o Output) Renditions() []string {
+	out := []string{RenditionVideo}
+	for _, r := range o.Audio {
+		out = append(out, r.Name)
+	}
+	return out
+}
+
+// Fixed geometry and rate bounds (D8).
+const (
+	maxWidth     = 1920
+	maxHeight    = 1080
+	maxFrameRate = 60
+)
+
+// ErrNoVideo is a generation-0 probe that found no video stream (D9): the
+// HLS attach fails with 502 and the channel's TS clients are unaffected.
+var ErrNoVideo = errors.New("hls: no video stream in the source")
+
+// Decide fixes the run's Output from generation 0's probe.
+func Decide(p Probe) (Output, error) {
+	if p.Video == nil || p.Video.Width <= 0 || p.Video.Height <= 0 {
+		return Output{}, ErrNoVideo
+	}
+	var o Output
+	o.Width, o.Height = fit(p.Video.Width, p.Video.Height)
+	o.FrameRate = outputRate(*p.Video)
+	o.GOP = (4*o.FrameRate.Num + o.FrameRate.Den) / (2 * o.FrameRate.Den)
+	switch {
+	case o.Height >= 1080:
+		o.VideoBitrate, o.VideoMaxrate = 6_000_000, 8_000_000
+	case o.Height >= 720:
+		o.VideoBitrate, o.VideoMaxrate = 4_000_000, 5_000_000
+	default:
+		o.VideoBitrate, o.VideoMaxrate = 2_500_000, 3_000_000
+	}
+
+	qualifying := p.Qualifying()
+	aac := Rendition{Name: RenditionAAC, Channels: 2}
+	if len(qualifying) > 0 {
+		aac.Language = qualifying[0].Language
+	}
+	o.Audio = append(o.Audio, aac)
+	if src, ok := firstOf(qualifying, "ac3", "eac3"); ok {
+		o.Audio = append(o.Audio, Rendition{Name: RenditionAC3, Channels: clampLayout(src.Channels), Language: src.Language})
+	}
+	if src, ok := firstOf(qualifying, "eac3"); ok {
+		o.Audio = append(o.Audio, Rendition{Name: RenditionEAC3, Channels: clampLayout(src.Channels), Language: src.Language})
+	}
+	return o, nil
+}
+
+// fit is D8's geometry: the source's own size when it fits in 1920x1080
+// (never upscaled), otherwise scaled down into it with the aspect kept;
+// both dimensions even, as 4:2:0 requires.
+func fit(w, h int) (int, int) {
+	if w > maxWidth || h > maxHeight {
+		if w*maxHeight >= h*maxWidth {
+			w, h = maxWidth, h*maxWidth/w
+		} else {
+			w, h = w*maxHeight/h, maxHeight
+		}
+	}
+	return max(2, w&^1), max(2, h&^1)
+}
+
+// outputRate is R: 1080i at 25 frames (50 fields) a second becomes 50p; a
+// progressive or unknown field order keeps its frame rate (R28: unknown is
+// progressive); either is capped at 60. A rate the probe could not read is
+// taken as 25, the broadcast rate of the fixtures and of most of Europe.
+func outputRate(v Video) Rational {
+	r := v.FrameRate
+	if r.Num <= 0 || r.Den <= 0 {
+		r = Rational{Num: 25, Den: 1}
+	}
+	if v.Field == FieldInterlaced {
+		r.Num *= 2
+	}
+	if r.Num > maxFrameRate*r.Den {
+		r = Rational{Num: maxFrameRate, Den: 1}
+	}
+	return r
+}
+
+// clampLayout is spec § Encoder argv's channel-layout clamp: mono and 2.0
+// become 2.0, and anything with more than two channels 5.1 (AC-3 cannot
+// carry 7.1, and the bitrate table has only these two).
+func clampLayout(channels int) int {
+	if channels > 2 {
+		return 6
+	}
+	return 2
+}
+
+// firstOf is the first stream whose codec is one of codecs, preferring
+// codecs[0] over codecs[1] and so on.
+func firstOf(streams []Audio, codecs ...string) (Audio, bool) {
+	for _, codec := range codecs {
+		for _, s := range streams {
+			if s.Codec == codec {
+				return s, true
+			}
+		}
+	}
+	return Audio{}, false
+}
+
+// FillKind is how one generation fills one declared rendition.
+type FillKind int
+
+const (
+	// FillSilence has no ffmpeg output at all: the relay writes the
+	// rendition's segments from a canned silent frame (M8).
+	FillSilence FillKind = iota
+	// FillEncode encodes a source stream at the declared layout.
+	FillEncode
+	// FillCopy copies a source stream whose codec and channel count already
+	// match the declaration.
+	FillCopy
+)
+
+func (k FillKind) String() string {
+	switch k {
+	case FillEncode:
+		return "encode"
+	case FillCopy:
+		return "copy"
+	}
+	return "silence"
+}
+
+// Fill is one rendition's source for one generation.
+type Fill struct {
+	Kind   FillKind
+	Source Audio
+}
+
+// Plan is one generation's argv decisions: the engine, whether to
+// deinterlace, and how each declared rendition is filled. The Output it
+// runs against never changes; the Plan is made again from each generation's
+// own probe (D9, D10).
+type Plan struct {
+	Engine      Engine
+	Deinterlace bool
+	Fills       map[string]Fill
+}
+
+// PlanGeneration fills every declared rendition from this generation's
+// probe (spec § Encoder argv, rendition filling). A source stream is copied
+// only when its codec is the rendition's and its channel count equals the
+// declared one; anything else qualifying is encoded at the declared layout;
+// with nothing qualifying the rendition is silence. Undeclared source tracks
+// are ignored: a later source that adds E-AC-3 declares nothing new.
+func PlanGeneration(o Output, p Probe, engine Engine) Plan {
+	plan := Plan{Engine: engine, Fills: map[string]Fill{}}
+	if p.Video != nil {
+		plan.Deinterlace = p.Video.Field == FieldInterlaced
+	}
+	qualifying := p.Qualifying()
+	for _, r := range o.Audio {
+		var src Audio
+		var ok bool
+		switch r.Name {
+		case RenditionAAC:
+			// Transcode mode always encodes AAC; copying AAC is automatic
+			// mode's (4a-1d).
+			if len(qualifying) > 0 {
+				src, ok = qualifying[0], true
+			}
+		case RenditionAC3:
+			src, ok = firstOf(qualifying, "ac3", "eac3")
+		case RenditionEAC3:
+			src, ok = firstOf(qualifying, "eac3")
+		}
+		if !ok && len(qualifying) > 0 && r.Name != RenditionAAC {
+			src, ok = qualifying[0], true
+		}
+		switch {
+		case !ok:
+			plan.Fills[r.Name] = Fill{Kind: FillSilence}
+		case r.Name != RenditionAAC && src.Codec == r.Name && src.Channels == r.Channels:
+			plan.Fills[r.Name] = Fill{Kind: FillCopy, Source: src}
+		default:
+			plan.Fills[r.Name] = Fill{Kind: FillEncode, Source: src}
+		}
+	}
+	return plan
+}
+
+// Extra is StartPipedExtra's descriptor mask for this plan: a pipe at fd
+// 3+i for every audio rendition in audioOrder that has an ffmpeg output this
+// generation. A declared rendition filled with silence, and an undeclared
+// one, get no descriptor.
+func (o Output) Extra(plan Plan) []bool {
+	extra := make([]bool, len(audioOrder))
+	used := false
+	for i, name := range audioOrder {
+		if f, declared := plan.Fills[name]; declared && f.Kind != FillSilence {
+			extra[i] = true
+			used = true
+		}
+	}
+	if !used {
+		return nil
+	}
+	return extra
+}
+
+// fragFlags is D6's movflags for every output: fragments at keyframes,
+// the moov written once the first packets are known -- `empty_moov` refuses
+// AC-3 passthrough ("Cannot write moov atom before AC3 packets", M4) -- and
+// moof-relative data offsets.
+const fragFlags = "frag_keyframe+delay_moov+default_base_moof"
+
+// audioFragment is -frag_duration for the audio outputs: 200 ms fragments,
+// so an audio segment is within 0.2 s of its video segment (Apple 7.7).
+const audioFragment = "200000"
+
+// Argv is the generation's ffmpeg argv (spec § Encoder argv, transcode
+// generation). It carries no input but pipe:0: no lavfi source, nothing that
+// could keep the process alive after its stdin closes (D10, M8).
+func (o Output) Argv(plan Plan, device string) []string {
+	a := []string{"-hide_banner", "-loglevel", "warning", "-nostats"}
+	if plan.Engine == EngineQSV {
+		a = append(a, "-init_hw_device", "qsv=hw:"+device, "-filter_hw_device", "hw")
+	}
+	a = append(a,
+		"-fflags", "+genpts+discardcorrupt",
+		"-f", "mpegts", "-i", "pipe:0",
+		"-map", "0:v:0",
+		"-vf", o.filter(plan),
+	)
+	g := strconv.Itoa(o.GOP)
+	b, m := strconv.Itoa(o.VideoBitrate), strconv.Itoa(o.VideoMaxrate)
+	if plan.Engine == EngineQSV {
+		a = append(a,
+			"-c:v", "h264_qsv", "-preset", "veryfast", "-profile:v", "high", "-level", "42",
+			"-b:v", b, "-maxrate", m, "-bufsize", m,
+			"-g", g, "-idr_interval", "0", "-forced_idr", "1",
+		)
+	} else {
+		a = append(a,
+			"-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
+			"-profile:v", "high", "-level:v", "4.2",
+			"-b:v", b, "-maxrate", m, "-bufsize", m,
+			"-g", g, "-keyint_min", g, "-sc_threshold", "0",
+		)
+	}
+	a = append(a,
+		"-force_key_frames", "expr:gte(t,n_forced*2)",
+		"-f", "mp4", "-movflags", fragFlags, "pipe:1",
+	)
+	for _, name := range audioOrder {
+		r, declared := o.Declared(name)
+		fill, planned := plan.Fills[name]
+		if !declared || !planned || fill.Kind == FillSilence {
+			continue
+		}
+		a = append(a, "-map", "0:i:"+fill.Source.ID)
+		a = append(a, audioCodecArgs(r, fill)...)
+		a = append(a,
+			"-f", "mp4", "-movflags", fragFlags, "-frag_duration", audioFragment,
+			fmt.Sprintf("pipe:%d", fdFor(name)),
+		)
+	}
+	return a
+}
+
+// filter is the -vf chain: deinterlace when this generation's probe says
+// interlaced, then scale, pad and fps to the run's fixed output, then the
+// pixel format the encoder takes -- nv12 uploaded to the device for QSV,
+// yuv420p for libx264.
+func (o Output) filter(plan Plan) string {
+	f := ""
+	if plan.Deinterlace {
+		f = "bwdif=mode=send_field:deint=interlaced,"
+	}
+	f += fmt.Sprintf("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,fps=%s,",
+		o.Width, o.Height, o.Width, o.Height, o.FrameRate)
+	if plan.Engine == EngineQSV {
+		return f + "format=nv12,hwupload=extra_hw_frames=64"
+	}
+	return f + "format=yuv420p"
+}
+
+// audioCodecArgs is one rendition's codec arguments: copy, or an encode at
+// the declared layout with the bitrate table's rate.
+func audioCodecArgs(r Rendition, fill Fill) []string {
+	if fill.Kind == FillCopy {
+		return []string{"-c:a", "copy"}
+	}
+	codec := map[string]string{RenditionAAC: "aac", RenditionAC3: "ac3", RenditionEAC3: "eac3"}[r.Name]
+	return []string{"-c:a", codec, "-ac", strconv.Itoa(r.Channels), "-b:a", strconv.Itoa(audioBitrate(r))}
+}
+
+// audioBitrate is the bitrate table: AAC 160 kb/s stereo; AC-3 640 kb/s at
+// 5.1 and 192 kb/s at 2.0; E-AC-3 640 kb/s at 5.1 and 256 kb/s at 2.0.
+func audioBitrate(r Rendition) int {
+	switch r.Name {
+	case RenditionAC3:
+		if r.Channels == 6 {
+			return 640_000
+		}
+		return 192_000
+	case RenditionEAC3:
+		if r.Channels == 6 {
+			return 640_000
+		}
+		return 256_000
+	}
+	return 160_000
+}
diff --git a/relay/hls/argv_test.go b/relay/hls/argv_test.go
new file mode 100644
index 00000000..d93ca9f6
--- /dev/null
+++ b/relay/hls/argv_test.go
@@ -0,0 +1,258 @@
+package hls
+
+import (
+	"errors"
+	"slices"
+	"strings"
+	"testing"
+)
+
+func video(w, h int, rate Rational, field FieldOrder) *Video {
+	return &Video{Codec: "h264", Width: w, Height: h, FrameRate: rate, Field: field}
+}
+
+func aud(id, codec string, channels int) Audio {
+	return Audio{ID: id, Codec: codec, Channels: channels, SampleRate: 48000}
+}
+
+// D8: geometry and frame rate are fixed at generation 0 -- at most 1920x1080,
+// never upscaled, R the field rate of an interlaced source capped at 60, G
+// round(2R) -- with the bitrate from the output height.
+func TestDecideFixesGeometryRateAndBitrate(t *testing.T) {
+	cases := []struct {
+		name         string
+		v            *Video
+		w, h         int
+		rate         Rational
+		gop          int
+		bitrate, max int
+	}{
+		{"1080i25 becomes 1080p50", video(1920, 1080, Rational{25, 1}, FieldInterlaced), 1920, 1080, Rational{50, 1}, 100, 6_000_000, 8_000_000},
+		{"576i25 keeps its size", video(720, 576, Rational{25, 1}, FieldInterlaced), 720, 576, Rational{50, 1}, 100, 2_500_000, 3_000_000},
+		{"720p50", video(1280, 720, Rational{50, 1}, FieldProgressive), 1280, 720, Rational{50, 1}, 100, 4_000_000, 5_000_000},
+		{"1080i29.97 becomes 59.94", video(1920, 1080, Rational{30000, 1001}, FieldInterlaced), 1920, 1080, Rational{60000, 1001}, 120, 6_000_000, 8_000_000},
+		{"2160p60 is scaled into 1080", video(3840, 2160, Rational{60, 1}, FieldProgressive), 1920, 1080, Rational{60, 1}, 120, 6_000_000, 8_000_000},
+		{"a tall source keeps its aspect", video(1080, 1920, Rational{30, 1}, FieldProgressive), 606, 1080, Rational{30, 1}, 60, 6_000_000, 8_000_000},
+		{"100p is capped at 60", video(1280, 720, Rational{100, 1}, FieldProgressive), 1280, 720, Rational{60, 1}, 120, 4_000_000, 5_000_000},
+		{"odd sizes are made even", video(719, 481, Rational{25, 1}, FieldProgressive), 718, 480, Rational{25, 1}, 50, 2_500_000, 3_000_000},
+		{"an unreadable rate is 25", video(640, 360, Rational{}, FieldProgressive), 640, 360, Rational{25, 1}, 50, 2_500_000, 3_000_000},
+	}
+	for _, c := range cases {
+		o, err := Decide(Probe{Video: c.v})
+		if err != nil {
+			t.Fatalf("%s: %v", c.name, err)
+		}
+		if o.Width != c.w || o.Height != c.h || o.FrameRate != c.rate || o.GOP != c.gop || o.VideoBitrate != c.bitrate || o.VideoMaxrate != c.max {
+			t.Errorf("%s: %dx%d R=%v G=%d B=%d M=%d, want %dx%d R=%v G=%d B=%d M=%d", c.name,
+				o.Width, o.Height, o.FrameRate, o.GOP, o.VideoBitrate, o.VideoMaxrate, c.w, c.h, c.rate, c.gop, c.bitrate, c.max)
+		}
+	}
+	for _, p := range []Probe{{}, {Video: video(0, 0, Rational{25, 1}, FieldProgressive)}} {
+		if _, err := Decide(p); !errors.Is(err, ErrNoVideo) {
+			t.Errorf("Decide(%+v) = %v, want ErrNoVideo", p, err)
+		}
+	}
+}
+
+func names(o Output) []string {
+	var out []string
+	for _, r := range o.Audio {
+		out = append(out, r.Name+":"+string(rune('0'+r.Channels)))
+	}
+	return out
+}
+
+// Spec § Encoder argv, the rendition set and channel layouts: aac always, at
+// 2.0; ac3 when generation 0 has AC-3 or E-AC-3; eac3 when it has E-AC-3;
+// each at the source layout clamped to 2.0 or 5.1. Only qualifying streams
+// count.
+func TestTheRenditionSetComesFromGenerationZero(t *testing.T) {
+	v := video(1920, 1080, Rational{25, 1}, FieldInterlaced)
+	cases := []struct {
+		name  string
+		audio []Audio
+		want  []string
+	}{
+		{"no audio at all", nil, []string{"aac:2"}},
+		{"AAC only", []Audio{aud("0x101", "aac", 2)}, []string{"aac:2"}},
+		{"MP2 only", []Audio{aud("0x201", "mp2", 2)}, []string{"aac:2"}},
+		{"AAC and AC-3 5.1", []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6)}, []string{"aac:2", "ac3:6"}},
+		{"E-AC-3 5.1 only (R20)", []Audio{aud("0x601", "eac3", 6)}, []string{"aac:2", "ac3:6", "eac3:6"}},
+		{"E-AC-3 7.1 clamps to 5.1", []Audio{aud("0x601", "eac3", 8)}, []string{"aac:2", "ac3:6", "eac3:6"}},
+		{"AC-3 mono clamps to 2.0", []Audio{aud("0x101", "ac3", 1)}, []string{"aac:2", "ac3:2"}},
+		{"AC-3 5.0 clamps to 5.1", []Audio{aud("0x101", "ac3", 5)}, []string{"aac:2", "ac3:6"}},
+		{"an empty AC-3 PID declares nothing", []Audio{aud("0x301", "aac", 2), {ID: "0x302", Codec: "ac3"}}, []string{"aac:2"}},
+	}
+	for _, c := range cases {
+		o, _ := Decide(Probe{Video: v, Audio: c.audio})
+		if got := names(o); !slices.Equal(got, c.want) {
+			t.Errorf("%s: renditions %v, want %v", c.name, got, c.want)
+		}
+	}
+	o, _ := Decide(Probe{Video: v, Audio: []Audio{{ID: "1", Codec: "aac", Channels: 2, SampleRate: 48000, Language: "eng"}}})
+	if o.Audio[0].Language != "eng" {
+		t.Errorf("the language tag was not kept: %+v", o.Audio)
+	}
+	if _, ok := o.Declared(RenditionEAC3); ok {
+		t.Errorf("eac3 declared without E-AC-3")
+	}
+	if !slices.Equal(o.Renditions(), []string{"video", "aac"}) {
+		t.Errorf("Renditions = %v", o.Renditions())
+	}
+}
+
+func fills(p Plan) map[string]string {
+	out := map[string]string{}
+	for name, f := range p.Fills {
+		out[name] = f.Kind.String() + ":" + f.Source.ID
+	}
+	return out
+}
+
+// Spec § Encoder argv, rendition filling: every generation fills every
+// declared rendition, copying only a stream of the rendition's codec at the
+// declared channel count, encoding anything else qualifying, and falling
+// back to silence; an undeclared source track is ignored.
+func TestEveryGenerationFillsEveryDeclaredRendition(t *testing.T) {
+	v := video(1920, 1080, Rational{25, 1}, FieldInterlaced)
+	gen0 := Probe{Video: v, Audio: []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6)}}
+	o, _ := Decide(gen0)
+	cases := []struct {
+		name  string
+		audio []Audio
+		want  map[string]string
+	}{
+		{"generation 0 itself", gen0.Audio, map[string]string{"aac": "encode:0x301", "ac3": "copy:0x302"}},
+		{"an MP2-only source fills ac3 by encoding", []Audio{aud("0x201", "mp2", 2)}, map[string]string{"aac": "encode:0x201", "ac3": "encode:0x201"}},
+		{"AC-3 2.0 into a 5.1 declaration is encoded", []Audio{aud("0x101", "ac3", 2)}, map[string]string{"aac": "encode:0x101", "ac3": "encode:0x101"}},
+		{"E-AC-3 fills ac3 by encoding", []Audio{aud("0x101", "mp2", 2), aud("0x102", "eac3", 6)}, map[string]string{"aac": "encode:0x101", "ac3": "encode:0x102"}},
+		{"no audio is silence everywhere", nil, map[string]string{"aac": "silence:", "ac3": "silence:"}},
+	}
+	for _, c := range cases {
+		got := fills(PlanGeneration(o, Probe{Video: v, Audio: c.audio}, EngineSoftware))
+		if len(got) != len(c.want) {
+			t.Errorf("%s: fills %v, want %v", c.name, got, c.want)
+			continue
+		}
+		for k, w := range c.want {
+			if got[k] != w {
+				t.Errorf("%s: %s = %s, want %s", c.name, k, got[k], w)
+			}
+		}
+	}
+	// The reverse direction: a later source that adds E-AC-3 declares nothing.
+	mp2, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x201", "mp2", 2)}})
+	later := PlanGeneration(mp2, Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}}, EngineSoftware)
+	if _, ok := later.Fills[RenditionEAC3]; ok || len(later.Fills) != 1 {
+		t.Errorf("a later E-AC-3 source changed the rendition set: %v", fills(later))
+	}
+	// E-AC-3 fills eac3 by copying; a mismatched layout is encoded.
+	e, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}})
+	if got := fills(PlanGeneration(e, Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}}, EngineSoftware)); got["eac3"] != "copy:0x601" || got["ac3"] != "encode:0x601" || got["aac"] != "encode:0x601" {
+		t.Errorf("an E-AC-3 source fills %v", got)
+	}
+	if got := fills(PlanGeneration(e, Probe{Video: v, Audio: []Audio{aud("0x9", "eac3", 2), aud("0xa", "aac", 2)}}, EngineSoftware)); got["eac3"] != "encode:0x9" {
+		t.Errorf("a 2.0 E-AC-3 into a 5.1 declaration: %v", got)
+	}
+	if got := fills(PlanGeneration(e, Probe{Video: v, Audio: []Audio{aud("0xa", "aac", 2)}}, EngineSoftware)); got["eac3"] != "encode:0xa" {
+		t.Errorf("AAC into an eac3 declaration: %v", got)
+	}
+	for _, k := range []FillKind{FillSilence, FillEncode, FillCopy} {
+		if k.String() == "" {
+			t.Errorf("%d has no name", k)
+		}
+	}
+}
+
+func argvString(o Output, p Plan) string { return strings.Join(o.Argv(p, DefaultDevice), " ") }
+
+// Spec § Encoder argv: the transcode generation's argv, software and QSV.
+func TestTheArgv(t *testing.T) {
+	v := video(1920, 1080, Rational{25, 1}, FieldInterlaced)
+	probe := Probe{Video: v, Audio: []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6)}}
+	o, _ := Decide(probe)
+
+	sw := PlanGeneration(o, probe, EngineSoftware)
+	got := argvString(o, sw)
+	for _, want := range []string{
+		"-hide_banner -loglevel warning -nostats -fflags +genpts+discardcorrupt -f mpegts -i pipe:0 -map 0:v:0",
+		"-vf bwdif=mode=send_field:deint=interlaced,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=50/1,format=yuv420p",
+		"-c:v libx264 -preset veryfast -tune zerolatency -profile:v high -level:v 4.2 -b:v 6000000 -maxrate 8000000 -bufsize 8000000 -g 100 -keyint_min 100 -sc_threshold 0",
+		"-force_key_frames expr:gte(t,n_forced*2) -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof pipe:1",
+		"-map 0:i:0x301 -c:a aac -ac 2 -b:a 160000 -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:3",
+		"-map 0:i:0x302 -c:a copy -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:4",
+	} {
+		if !strings.Contains(got, want) {
+			t.Errorf("the software argv lacks %q:\n%s", want, got)
+		}
+	}
+	for _, never := range []string{"lavfi", "anullsrc", "init_hw_device", "h264_qsv", "pipe:5"} {
+		if strings.Contains(got, never) {
+			t.Errorf("the software argv carries %q:\n%s", never, got)
+		}
+	}
+	if !slices.Equal(o.Extra(sw), []bool{true, true, false}) {
+		t.Errorf("Extra = %v, want fd 3 and fd 4", o.Extra(sw))
+	}
+
+	qsv := PlanGeneration(o, probe, EngineQSV)
+	got = argvString(o, qsv)
+	for _, want := range []string{
+		"-init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw -fflags",
+		",fps=50/1,format=nv12,hwupload=extra_hw_frames=64",
+		"-c:v h264_qsv -preset veryfast -profile:v high -level 42 -b:v 6000000 -maxrate 8000000 -bufsize 8000000 -g 100 -idr_interval 0 -forced_idr 1",
+	} {
+		if !strings.Contains(got, want) {
+			t.Errorf("the QSV argv lacks %q:\n%s", want, got)
+		}
+	}
+
+	progressive := Probe{Video: video(640, 360, Rational{25, 1}, FieldProgressive), Audio: []Audio{aud("0x601", "eac3", 2)}}
+	e, _ := Decide(progressive)
+	got = argvString(e, PlanGeneration(e, progressive, EngineSoftware))
+	for _, want := range []string{"-vf scale=640:360", "-map 0:i:0x601 -c:a ac3 -ac 2 -b:a 192000", "-map 0:i:0x601 -c:a copy", "pipe:5"} {
+		if !strings.Contains(got, want) {
+			t.Errorf("the E-AC-3 2.0 argv lacks %q:\n%s", want, got)
+		}
+	}
+	e6, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}})
+	got = argvString(e6, PlanGeneration(e6, Probe{Video: v, Audio: []Audio{aud("0x9", "mp2", 2)}}, EngineSoftware))
+	for _, want := range []string{"-c:a ac3 -ac 6 -b:a 640000", "-c:a eac3 -ac 6 -b:a 640000"} {
+		if !strings.Contains(got, want) {
+			t.Errorf("the 5.1 encode argv lacks %q:\n%s", want, got)
+		}
+	}
+	e2, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 2)}})
+	if got := argvString(e2, PlanGeneration(e2, Probe{Video: v, Audio: []Audio{aud("0x9", "mp2", 2)}}, EngineSoftware)); !strings.Contains(got, "-c:a eac3 -ac 2 -b:a 256000") {
+		t.Errorf("the 2.0 E-AC-3 encode argv:\n%s", got)
+	}
+}
+
+// Parity: a non-qualifying audio stream is not mapped. The declared-but-empty
+// AC-3 PID declares no rendition and appears nowhere in the argv.
+func TestANonQualifyingAudioStreamIsNotMapped(t *testing.T) {
+	probe, _ := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
+	o, _ := Decide(probe)
+	got := argvString(o, PlanGeneration(o, probe, EngineSoftware))
+	if strings.Contains(got, "0x302") || strings.Count(got, "-map") != 2 {
+		t.Errorf("the empty AC-3 PID was mapped:\n%s", got)
+	}
+}
+
+// M8: a rendition filled with silence has no output in the argv at all, and
+// no descriptor.
+func TestSilenceHasNoOutputInTheArgv(t *testing.T) {
+	v := video(640, 360, Rational{25, 1}, FieldProgressive)
+	o, _ := Decide(Probe{Video: v})
+	plan := PlanGeneration(o, Probe{Video: v}, EngineSoftware)
+	got := argvString(o, plan)
+	if strings.Contains(got, "pipe:3") || strings.Contains(got, "-map 0:i") || strings.Contains(got, "lavfi") {
+		t.Errorf("a silent generation's argv has an audio output:\n%s", got)
+	}
+	if o.Extra(plan) != nil {
+		t.Errorf("a silent generation asks for descriptors: %v", o.Extra(plan))
+	}
+	if fdFor("nope") != -1 {
+		t.Errorf("fdFor of an unknown rendition")
+	}
+}
diff --git a/relay/hls/box.go b/relay/hls/box.go
new file mode 100644
index 00000000..27a832b7
--- /dev/null
+++ b/relay/hls/box.go
@@ -0,0 +1,163 @@
+package hls
+
+import (
+	"encoding/binary"
+	"errors"
+	"fmt"
+)
+
+// The box reader (Phase 4 spec, D6): ISO BMFF parsing for exactly what the
+// segmenter and the playlists need, with stdlib encoding/binary and nothing
+// else. It reads the boxes ffmpeg's mp4 muxer writes under
+// `-movflags frag_keyframe+delay_moov+default_base_moof`: one track per
+// output, an init segment (ftyp, moov) and then moof+mdat fragments.
+//
+// EVERY LENGTH IS CHECKED BEFORE IT IS USED. The input is an encoder's pipe,
+// which is trusted as far as it goes, but a truncated or corrupt box must end
+// a generation with an error rather than panic the relay that carries every
+// live viewer; FuzzParseInit and FuzzParseFragment hold that.
+
+// errBox is every malformed-box error, so a caller can tell a parse failure
+// from an I/O one.
+var errBox = errors.New("hls: malformed box")
+
+func boxErr(format string, args ...any) error {
+	return fmt.Errorf("%w: "+format, append([]any{errBox}, args...)...)
+}
+
+// maxBoxBytes bounds any single box the reader will hold: a video fragment
+// of a 2 s segment at D8's top rate is about 2 MB, and a copied fragment
+// (4a-1d) of a 6 s GOP at a high provider rate a few tens; 64 MiB is the
+// same ceiling relay/output's fragment scanner uses.
+const maxBoxBytes = 64 << 20
+
+// boxHeader reads the header of the box at off in data: its total size
+// (header included), its four-character type, and the header's length (8, or
+// 16 with a 64-bit largesize). A size of 0 means "to the end of data". ok is
+// false when the header or the size does not fit.
+func boxHeader(data []byte, off int) (size int, typ string, hdr int, ok bool) {
+	if off < 0 || off+8 > len(data) {
+		return 0, "", 0, false
+	}
+	size32 := binary.BigEndian.Uint32(data[off:])
+	typ = string(data[off+4 : off+8])
+	remaining := len(data) - off
+	switch size32 {
+	case 0:
+		return remaining, typ, 8, true
+	case 1:
+		if remaining < 16 {
+			return 0, "", 0, false
+		}
+		large := binary.BigEndian.Uint64(data[off+8:])
+		if large < 16 || large > uint64(remaining) { // #nosec G115 -- remaining >= 16 here
+			return 0, "", 0, false
+		}
+		return int(large), typ, 16, true // #nosec G115 -- large <= remaining, an int
+	default:
+		if size32 < 8 || int64(size32) > int64(remaining) {
+			return 0, "", 0, false
+		}
+		return int(size32), typ, 8, true
+	}
+}
+
+// span is one box inside a byte slice: [start, end) is the whole box and
+// body is where its payload starts.
+type span struct {
+	typ        string
+	start, end int
+	body       int
+}
+
+// children lists the boxes laid end to end in data[from:to], stopping with
+// an error at the first that does not fit.
+func children(data []byte, from, to int) ([]span, error) {
+	var out []span
+	for off := from; off < to; {
+		size, typ, hdr, ok := boxHeader(data[:to], off)
+		if !ok {
+			return out, boxErr("a box at offset %d does not fit in %d bytes", off, to-off)
+		}
+		out = append(out, span{typ: typ, start: off, end: off + size, body: off + hdr})
+		off += size
+	}
+	return out, nil
+}
+
+// child finds the first box of type typ directly inside data[from:to].
+func child(data []byte, from, to int, typ string) (span, bool) {
+	list, _ := children(data, from, to)
+	for _, s := range list {
+		if s.typ == typ {
+			return s, true
+		}
+	}
+	return span{}, false
+}
+
+// path follows a chain of container types from data[from:to], each the first
+// of its type inside the previous one.
+func path(data []byte, from, to int, types ...string) (span, bool) {
+	var s span
+	for _, typ := range types {
+		found, ok := child(data, from, to, typ)
+		if !ok {
+			return span{}, false
+		}
+		s, from, to = found, found.body, found.end
+	}
+	return s, true
+}
+
+// fullBox reads a FullBox's version and flags at the start of s's payload.
+func fullBox(data []byte, s span) (version byte, flags uint32, ok bool) {
+	if s.body+4 > s.end {
+		return 0, 0, false
+	}
+	return data[s.body], uint32(data[s.body+1])<<16 | uint32(data[s.body+2])<<8 | uint32(data[s.body+3]), true
+}
+
+// cursor reads big-endian integers from data[pos:end], remembering the first
+// short read so a parser can check once at the end.
+type cursor struct {
+	data []byte
+	pos  int
+	end  int
+	bad  bool
+}
+
+func (c *cursor) take(n int) []byte {
+	if c.bad || n < 0 || c.pos+n > c.end {
+		c.bad = true
+		return nil
+	}
+	b := c.data[c.pos : c.pos+n]
+	c.pos += n
+	return b
+}
+
+func (c *cursor) u8() uint8 {
+	if b := c.take(1); b != nil {
+		return b[0]
+	}
+	return 0
+}
+
+func (c *cursor) u32() uint32 {
+	if b := c.take(4); b != nil {
+		return binary.BigEndian.Uint32(b)
+	}
+	return 0
+}
+
+func (c *cursor) u64() uint64 {
+	if b := c.take(8); b != nil {
+		return binary.BigEndian.Uint64(b)
+	}
+	return 0
+}
+
+// sampleIsSync reads ISO/IEC 14496-12's sample_flags: a sample is a sync
+// sample when sample_is_non_sync_sample (bit 16) is clear.
+func sampleIsSync(flags uint32) bool { return flags&0x00010000 == 0 }
diff --git a/relay/hls/box_test.go b/relay/hls/box_test.go
new file mode 100644
index 00000000..2473cf28
--- /dev/null
+++ b/relay/hls/box_test.go
@@ -0,0 +1,258 @@
+package hls
+
+import (
+	"bytes"
+	"errors"
+	"testing"
+)
+
+func TestParseInitReadsTheTrackAndItsCodec(t *testing.T) {
+	for _, version1 := range []bool{false, true} {
+		init := initSpec{trackID: 7, handler: "vide", timescale: 12800, movieTimescale: 1000,
+			entry: avc1Entry(0x64, 0x00, 0x2a), trexDuration: 512, trexSize: 99, trexFlags: 0x01010000, version1: version1}.build()
+		track, err := ParseInit(init)
+		if err != nil {
+			t.Fatalf("version1=%t: ParseInit: %v", version1, err)
+		}
+		want := Track{ID: 7, Handler: "vide", Timescale: 12800, Codec: "avc1.64002a",
+			DefaultDuration: 512, DefaultSize: 99, DefaultFlags: 0x01010000}
+		if track != want {
+			t.Errorf("version1=%t: ParseInit = %+v, want %+v", version1, track, want)
+		}
+	}
+}
+
+func TestCodecStringsComeFromTheInitSegment(t *testing.T) {
+	hvcC := box("hvcC", []byte{1, 0x01, 0x60, 0, 0, 0, 0xb0, 0, 0, 0, 0, 0, 93, 0xf0})
+	cases := []struct {
+		name  string
+		entry []byte
+		want  string
+	}{
+		{"H.264 High 4.2", avc1Entry(0x64, 0x00, 0x2a), "avc1.64002a"},
+		{"H.264 Main 3.1", avc1Entry(0x4d, 0x40, 0x1f), "avc1.4d401f"},
+		{"HEVC Main 3.1", box("hvc1", cat(make([]byte, 78), hvcC)), "hvc1.1.6.L93.B0"},
+		{"AAC-LC", audioEntry("mp4a", esdsAAC(2)), "mp4a.40.2"},
+		{"HE-AAC", audioEntry("mp4a", esdsAAC(5)), "mp4a.40.5"},
+		{"an escaped object type", audioEntry("mp4a", esdsAAC(42)), "mp4a.40.42"},
+		{"AC-3", audioEntry("ac-3", box("dac3", []byte{0x10, 0x3d, 0xe0})), "ac-3"},
+		{"E-AC-3", audioEntry("ec-3", box("dec3", []byte{0x0a, 0x00, 0x20, 0x0f, 0x00})), "ec-3"},
+		{"an unknown sample entry", box("mp4v", make([]byte, 78)), ""},
+	}
+	for _, c := range cases {
+		init := initSpec{trackID: 1, handler: "soun", timescale: 48000, entry: c.entry}.build()
+		track, err := ParseInit(init)
+		if err != nil {
+			t.Fatalf("%s: ParseInit: %v", c.name, err)
+		}
+		if track.Codec != c.want {
+			t.Errorf("%s: CODECS = %q, want %q", c.name, track.Codec, c.want)
+		}
+	}
+}
+
+// ffmpeg records a track's real start as an empty edit (measured, ffmpeg
+// 9.0.1); the offset is converted from the movie timescale to the media one,
+// less any media_time, and never negative.
+func TestStartOffsetIsTheEmptyEditInMediaTicks(t *testing.T) {
+	cases := []struct {
+		name      string
+		movie     uint32
+		emptyEdit uint32
+		mediaTime int32
+		want      uint64
+	}{
+		{"no edit list", 1000, 0, 0, 0},
+		{"0.86 s at a 1000 Hz movie timescale", 1000, 860, 0, 11008},
+		{"5.3 ms at a 48 kHz movie timescale", 48000, 256, 0, 68},
+		{"a media_time is subtracted", 1000, 860, 1000, 10008},
+		{"a priming edit longer than the delay is clamped to 0", 1000, 0, 1024, 0},
+	}
+	for _, c := range cases {
+		init := initSpec{trackID: 1, handler: "vide", timescale: 12800, movieTimescale: c.movie,
+			entry: avc1Entry(0x64, 0, 0x2a), emptyEdit: c.emptyEdit, mediaTime: c.mediaTime}.build()
+		track, err := ParseInit(init)
+		if err != nil {
+			t.Fatalf("%s: %v", c.name, err)
+		}
+		if track.StartOffset != c.want {
+			t.Errorf("%s: StartOffset = %d, want %d", c.name, track.StartOffset, c.want)
+		}
+	}
+}
+
+func TestStripEditsRemovesTheEditListAndFixesTheSizes(t *testing.T) {
+	init := initSpec{trackID: 1, handler: "soun", timescale: 48000, movieTimescale: 48000,
+		entry: audioEntry("ac-3", box("dac3", []byte{0x10, 0x3d, 0xe0})), emptyEdit: 256}.build()
+	stripped, err := StripEdits(init)
+	if err != nil {
+		t.Fatalf("StripEdits: %v", err)
+	}
+	if bytes.Contains(stripped, []byte("edts")) || bytes.Contains(stripped, []byte("elst")) {
+		t.Fatalf("the stripped init still carries an edit list")
+	}
+	// edts (8) + elst (8 + 4 + 4) + two 12-byte entries = 48 bytes.
+	if len(stripped) != len(init)-48 {
+		t.Errorf("stripped %d bytes, want the 48-byte edts gone from %d", len(stripped), len(init))
+	}
+	track, err := ParseInit(stripped)
+	if err != nil {
+		t.Fatalf("the stripped init does not parse: %v", err)
+	}
+	if track.Codec != "ac-3" || track.StartOffset != 0 {
+		t.Errorf("stripped init parses as %+v", track)
+	}
+	if _, err := StripEdits([]byte{0, 0, 0, 3}); err == nil {
+		t.Errorf("StripEdits accepted a malformed box")
+	}
+}
+
+func TestParseInitRefusesWhatIsNotAnInit(t *testing.T) {
+	good := initSpec{trackID: 1, handler: "vide", timescale: 12800, entry: avc1Entry(0x64, 0, 0x2a)}.build()
+	cases := map[string][]byte{
+		"empty":                     nil,
+		"no moov":                   box("ftyp", []byte("iso5")),
+		"a moov with nothing in it": box("moov", nil),
+		"a moov with only an mvhd":  box("moov", fullBoxBytes("mvhd", 0, 0, cat(make([]byte, 8), be32(1000), make([]byte, 84)))),
+		"truncated":                 good[:len(good)-20],
+	}
+	for name, data := range cases {
+		if _, err := ParseInit(data); !errors.Is(err, errBox) {
+			t.Errorf("%s: ParseInit error = %v, want a malformed-box error", name, err)
+		}
+	}
+}
+
+func TestParseFragmentReadsTheTimingAndTheSyncSample(t *testing.T) {
+	track := Track{ID: 1, Timescale: 12800, DefaultDuration: 512}
+	f, err := ParseFragment(fragSpec{seq: 1, trackID: 1, start: 25600, durations: []uint32{512, 512, 256}, sync: true}.build(), track)
+	if err != nil {
+		t.Fatalf("ParseFragment: %v", err)
+	}
+	if f.Start != 25600 || f.Duration != 1280 || f.Samples != 3 || !f.Sync || f.End() != 26880 {
+		t.Errorf("ParseFragment = start %d duration %d samples %d sync %t", f.Start, f.Duration, f.Samples, f.Sync)
+	}
+	nonSync, err := ParseFragment(fragSpec{seq: 2, trackID: 1, start: 7, durations: []uint32{512}, v0: true}.build(), track)
+	if err != nil {
+		t.Fatalf("ParseFragment v0: %v", err)
+	}
+	if nonSync.Sync || nonSync.Start != 7 {
+		t.Errorf("a non-sync version-0 fragment parsed as sync=%t start=%d", nonSync.Sync, nonSync.Start)
+	}
+	if _, err := ParseFragment(fragSpec{seq: 1, trackID: 2, durations: []uint32{1}}.build(), track); !errors.Is(err, errBox) {
+		t.Errorf("a fragment for another track was accepted: %v", err)
+	}
+}
+
+// The defaults a fragment leaves implicit come from tfhd, then trex, and a
+// first sample's flags from the trun's first-sample-flags or its own flags.
+func TestParseFragmentFallsBackToTheDefaults(t *testing.T) {
+	track := Track{ID: 1, Timescale: 48000, DefaultDuration: 1024, DefaultFlags: 0x02000000}
+	tfhd := fullBoxBytes("tfhd", 0, 0x020000|tfhdBaseDataOffset|tfhdSampleDescIndex, cat(be32(1), be64(0), be32(1)))
+	tfdt := fullBoxBytes("tfdt", 1, 0, be64(48000))
+	trun := fullBoxBytes("trun", 0, uint32(trunDataOffset), cat(be32(3), be32(0)))
+	frag := cat(box("moof", cat(fullBoxBytes("mfhd", 0, 0, be32(1)), box("traf", cat(tfhd, tfdt, trun)))), box("mdat", nil))
+	f, err := ParseFragment(frag, track)
+	if err != nil {
+		t.Fatalf("ParseFragment: %v", err)
+	}
+	if f.Duration != 3072 || !f.Sync {
+		t.Errorf("trex defaults not applied: duration %d sync %t", f.Duration, f.Sync)
+	}
+	perSample := fullBoxBytes("trun", 0, uint32(trunFlagsPresent|trunSize|trunCTO|trunDuration), cat(be32(1), be32(100), be32(4), be32(0x01010000), be32(0)))
+	tfhdDefaults := fullBoxBytes("tfhd", 0, tfhdDefaultDuration|tfhdDefaultSize|tfhdDefaultFlags, cat(be32(1), be32(9), be32(4), be32(0x02000000)))
+	frag = cat(box("moof", box("traf", cat(tfhdDefaults, tfdt, perSample))), box("mdat", make([]byte, 4)))
+	f, err = ParseFragment(frag, track)
+	if err != nil {
+		t.Fatalf("ParseFragment per-sample: %v", err)
+	}
+	if f.Duration != 100 || f.Sync {
+		t.Errorf("per-sample fields not read: duration %d sync %t", f.Duration, f.Sync)
+	}
+}
+
+func TestParseFragmentRefusesAMalformedFragment(t *testing.T) {
+	track := Track{ID: 1}
+	good := fragSpec{seq: 1, trackID: 1, durations: []uint32{1, 1}}.build()
+	tfhd := fullBoxBytes("tfhd", 0, 0, be32(1))
+	tfdt := fullBoxBytes("tfdt", 1, 0, be64(0))
+	trun := fullBoxBytes("trun", 0, 0, be32(1))
+	cases := map[string][]byte{
+		"not a moof":        box("mdat", nil),
+		"no traf":           box("moof", nil),
+		"no tfhd":           box("moof", box("traf", nil)),
+		"a short tfhd":      box("moof", box("traf", fullBoxBytes("tfhd", 0, 0, nil))),
+		"no tfdt":           box("moof", box("traf", tfhd)),
+		"a short tfdt":      box("moof", box("traf", cat(tfhd, fullBoxBytes("tfdt", 1, 0, be32(0))))),
+		"no trun":           box("moof", box("traf", cat(tfhd, tfdt))),
+		"a trun that lies":  box("moof", box("traf", cat(tfhd, tfdt, fullBoxBytes("trun", 0, uint32(trunDuration), be32(1000))))),
+		"a short trun":      box("moof", box("traf", cat(tfhd, tfdt, box("trun", []byte{0})))),
+		"a truncated frag":  good[:40],
+		"a sample-less run": box("moof", box("traf", cat(tfhd, tfdt, trun))),
+	}
+	for name, data := range cases {
+		if name == "a sample-less run" {
+			if _, err := ParseFragment(data, track); err != nil {
+				t.Errorf("%s: %v", name, err)
+			}
+			continue
+		}
+		if _, err := ParseFragment(data, track); !errors.Is(err, errBox) {
+			t.Errorf("%s: ParseFragment error = %v, want a malformed-box error", name, err)
+		}
+	}
+}
+
+func TestShiftStartMovesTheTfdt(t *testing.T) {
+	track := Track{ID: 1, Timescale: 12800}
+	f, _ := ParseFragment(fragSpec{seq: 1, trackID: 1, start: 100, durations: []uint32{512}, sync: true}.build(), track)
+	if err := shiftStart(&f, 11008); err != nil {
+		t.Fatalf("shiftStart: %v", err)
+	}
+	again, err := ParseFragment(f.Data, track)
+	if err != nil || again.Start != 11108 || f.Start != 11108 {
+		t.Errorf("after the shift the fragment starts at %d (parsed %d, %v), want 11108", f.Start, again.Start, err)
+	}
+	if err := shiftStart(&f, 0); err != nil {
+		t.Errorf("a zero shift failed: %v", err)
+	}
+	v0, _ := ParseFragment(fragSpec{seq: 1, trackID: 1, start: 5, durations: []uint32{512}, v0: true}.build(), track)
+	if err := shiftStart(&v0, 10); err != nil || v0.Start != 15 {
+		t.Errorf("a version-0 shift: start %d, %v", v0.Start, err)
+	}
+	if err := shiftStart(&v0, 1<<32); !errors.Is(err, errBox) {
+		t.Errorf("a version-0 tfdt was allowed to overflow: %v", err)
+	}
+	noTfdt := Fragment{Data: box("moof", box("traf", nil)), Start: 1}
+	if err := shiftStart(&noTfdt, 1); !errors.Is(err, errBox) {
+		t.Errorf("a fragment with no tfdt was shifted: %v", err)
+	}
+}
+
+// A synthesised fragment is exactly what the box reader reads back: count
+// copies of the frame, each dur ticks, at start.
+func TestSynthFragmentRoundTrips(t *testing.T) {
+	frame := []byte{0xde, 0xad, 0xbe, 0xef, 0x01, 0x02}
+	data := synthFragment(9, 1, 96000, frame, 94, 1024)
+	track := Track{ID: 1, Timescale: 48000}
+	f, err := ParseFragment(data, track)
+	if err != nil {
+		t.Fatalf("ParseFragment: %v", err)
+	}
+	if f.Start != 96000 || f.Samples != 94 || f.Duration != 94*1024 || !f.Sync {
+		t.Errorf("synthesised fragment parses as %+v", f)
+	}
+	samples, durations, err := fragmentSamples(data, track)
+	if err != nil || len(samples) != 94 {
+		t.Fatalf("fragmentSamples: %d samples, %v", len(samples), err)
+	}
+	for i, s := range samples {
+		if !bytes.Equal(s, frame) || durations[i] != 1024 {
+			t.Fatalf("sample %d is %x (%d ticks), want the frame", i, s, durations[i])
+		}
+	}
+	empty, err := ParseFragment(synthFragment(1, 1, 0, nil, 0, 1024), track)
+	if err != nil || empty.Samples != 0 || empty.Sync {
+		t.Errorf("an empty synthesised fragment parses as %+v, %v", empty, err)
+	}
+}
diff --git a/relay/hls/detect.go b/relay/hls/detect.go
new file mode 100644
index 00000000..bd8ca869
--- /dev/null
+++ b/relay/hls/detect.go
@@ -0,0 +1,140 @@
+package hls
+
+import (
+	"context"
+	"log/slog"
+	"os"
+	"sync"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
+	"github.com/D10Scot/Dispatcharr/relay/redact"
+)
+
+// DetectTimeout bounds the one-frame detection encode (spec D11).
+const DetectTimeout = 10 * time.Second
+
+// DetectArgv is the detection encode: one black 256x144 frame through
+// hwupload and h264_qsv to the null muxer. Exit 0 means Quick Sync is usable.
+func DetectArgv(device string) []string {
+	return []string{
+		"-hide_banner", "-loglevel", "error",
+		"-init_hw_device", "qsv=hw:" + device, "-filter_hw_device", "hw",
+		"-f", "lavfi", "-i", "color=c=black:s=256x144:r=25",
+		"-frames:v", "1", "-vf", "format=nv12,hwupload",
+		"-c:v", "h264_qsv", "-f", "null", "-",
+	}
+}
+
+// Detector is the process-wide answer to "is Quick Sync usable?" (D11). It
+// runs the detection encode at the first HLS attach in the process and
+// caches the answer; the pipelines of every channel share one.
+//
+// QSV IS WRITTEN OFF FOR THE PROCESS ONLY ON EVIDENCE THAT THE DEVICE FAILED
+// (finding 5): a generation that failed twice on QSV must then succeed in
+// software AND a re-run of the detection encode must fail. A channel whose
+// source is bad fails in software too, and never reaches MarkUnusable.
+type Detector struct {
+	// Command is the ffmpeg executable ("ffmpeg" when empty).
+	Command string
+	// Device is the render node (DefaultDevice when empty). A device that
+	// does not exist is software without running anything.
+	Device string
+	// Timeout bounds each detection encode (DetectTimeout when zero).
+	Timeout time.Duration
+	// Log receives the one WARNING a fallback is logged with.
+	Log *slog.Logger
+
+	mu       sync.Mutex
+	checked  bool
+	usable   bool
+	unusable bool
+	warned   bool
+}
+
+func (d *Detector) command() string {
+	if d.Command != "" {
+		return d.Command
+	}
+	return "ffmpeg"
+}
+
+func (d *Detector) device() string {
+	if d.Device != "" {
+		return d.Device
+	}
+	return DefaultDevice
+}
+
+func (d *Detector) log() *slog.Logger {
+	if d.Log != nil {
+		return d.Log
+	}
+	return slog.Default()
+}
+
+// Engine is the engine a new generation should start on: QSV when the
+// cached detection passed and nothing has written it off, software
+// otherwise. The first call runs the detection; later calls return at once.
+func (d *Detector) Engine(ctx context.Context) Engine {
+	d.mu.Lock()
+	defer d.mu.Unlock()
+	if !d.checked {
+		d.usable = d.detect(ctx)
+		d.checked = true
+	}
+	if d.usable && !d.unusable {
+		return EngineQSV
+	}
+	if !d.warned {
+		d.warned = true
+		d.log().Warn("Quick Sync is not usable; HLS encodes in software", "device", d.device())
+	}
+	return EngineSoftware
+}
+
+// Recheck runs the detection encode again and reports whether it passed.
+// It does not change the cached answer; MarkUnusable does.
+func (d *Detector) Recheck(ctx context.Context) bool {
+	return d.detect(ctx)
+}
+
+// MarkUnusable writes Quick Sync off for the rest of the process.
+func (d *Detector) MarkUnusable() {
+	d.mu.Lock()
+	defer d.mu.Unlock()
+	if !d.unusable {
+		d.log().Warn("Quick Sync failed where software succeeded, and its detection encode now fails; HLS encodes in software for the rest of the process", "device", d.device())
+	}
+	d.unusable = true
+	d.warned = true
+}
+
+// detect is the detection encode itself: a missing device, any non-zero
+// exit, a spawn failure or the timeout all mean "not usable".
+func (d *Detector) detect(ctx context.Context) bool {
+	if _, err := os.Stat(d.device()); err != nil {
+		return false
+	}
+	timeout := d.Timeout
+	if timeout <= 0 {
+		timeout = DetectTimeout
+	}
+	ctx, cancel := context.WithTimeout(ctx, timeout)
+	defer cancel()
+	proc, err := ffmpeg.Start(ctx, d.command(), DetectArgv(d.device()))
+	if err != nil {
+		d.log().Info("the Quick Sync detection encode could not start", "error", redact.Error(err))
+		return false
+	}
+	done := make(chan struct{})
+	go func() {
+		defer close(done)
+		proc.ReadStderr(func(line string) {
+			d.log().Debug("detection encode stderr", "line", redact.Line(line))
+		})
+	}()
+	err = proc.Wait()
+	<-done
+	return err == nil && ctx.Err() == nil
+}
diff --git a/relay/hls/detect_test.go b/relay/hls/detect_test.go
new file mode 100644
index 00000000..1db112d3
--- /dev/null
+++ b/relay/hls/detect_test.go
@@ -0,0 +1,76 @@
+package hls
+
+import (
+	"context"
+	"os"
+	"os/exec"
+	"path/filepath"
+	"testing"
+)
+
+// lookPath finds a POSIX utility the detection tests use as their "encoder":
+// true passes, false fails. Neither reads its argv, which is the point -- the
+// subject is the relay's reading of the exit status, not the encode.
+func lookPath(t *testing.T, name string) string {
+	t.Helper()
+	path, err := exec.LookPath(name)
+	if err != nil {
+		t.Fatalf("%s is not on PATH: %v", name, err)
+	}
+	return path
+}
+
+// device is a file that exists, standing in for /dev/dri/renderD128.
+func device(t *testing.T) string {
+	t.Helper()
+	path := filepath.Join(t.TempDir(), "renderD128")
+	if err := os.WriteFile(path, nil, 0o600); err != nil {
+		t.Fatal(err)
+	}
+	return path
+}
+
+// D11: with no render node the relay encodes in software, without running
+// anything; a detection encode that exits 0 means Quick Sync; any failure
+// means software; and the answer is cached for the process.
+func TestDetection(t *testing.T) {
+	missing := &Detector{Command: filepath.Join(t.TempDir(), "never-run"), Device: filepath.Join(t.TempDir(), "renderD128")}
+	if got := missing.Engine(context.Background()); got != EngineSoftware {
+		t.Errorf("a missing device gave %s, want software", got)
+	}
+	passing := &Detector{Command: lookPath(t, "true"), Device: device(t)}
+	if got := passing.Engine(context.Background()); got != EngineQSV {
+		t.Errorf("a passing detection encode gave %s, want qsv", got)
+	}
+	passing.Command = lookPath(t, "false")
+	if got := passing.Engine(context.Background()); got != EngineQSV {
+		t.Errorf("the answer was not cached: %s", got)
+	}
+	if passing.Recheck(context.Background()) {
+		t.Errorf("a failing re-run of the detection passed")
+	}
+	failing := &Detector{Command: lookPath(t, "false"), Device: device(t)}
+	if got := failing.Engine(context.Background()); got != EngineSoftware {
+		t.Errorf("a failing detection encode gave %s, want software", got)
+	}
+	unstartable := &Detector{Command: filepath.Join(t.TempDir(), "no-such-ffmpeg"), Device: device(t)}
+	if got := unstartable.Engine(context.Background()); got != EngineSoftware {
+		t.Errorf("an encoder that cannot start gave %s, want software", got)
+	}
+	passing.MarkUnusable()
+	passing.MarkUnusable()
+	if got := passing.Engine(context.Background()); got != EngineSoftware {
+		t.Errorf("MarkUnusable did not write Quick Sync off: %s", got)
+	}
+	var defaults Detector
+	if defaults.command() != "ffmpeg" || defaults.device() != DefaultDevice || defaults.log() == nil {
+		t.Errorf("the zero Detector's defaults")
+	}
+}
+
+func TestDetectArgv(t *testing.T) {
+	want := "-hide_banner -loglevel error -init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw -f lavfi -i color=c=black:s=256x144:r=25 -frames:v 1 -vf format=nv12,hwupload -c:v h264_qsv -f null -"
+	if got := joinArgs(DetectArgv(DefaultDevice)); got != want {
+		t.Errorf("DetectArgv = %q, want %q", got, want)
+	}
+}
diff --git a/relay/hls/doc.go b/relay/hls/doc.go
new file mode 100644
index 00000000..fa8e11bc
--- /dev/null
+++ b/relay/hls/doc.go
@@ -0,0 +1,29 @@
+// Package hls is the relay's HLS packager (Phase 4 spec,
+// docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md, D6-D11;
+// ADR 0009): it turns a channel's ring into fMP4/CMAF HLS renditions.
+//
+// One ffmpeg per GENERATION reads the channel's ring on fd 0 and writes one
+// fragmented-MP4 stream per rendition on its own descriptor -- video on fd 1,
+// stereo AAC on fd 3, AC-3 on fd 4, E-AC-3 on fd 5 (argv.go). A probe precedes
+// every generation and reads from where that generation starts (probe.go,
+// D9). A generation ends at every source boundary the channel records -- a
+// failover or a same-URL reconnect -- because one encoder fed a second
+// provider's PIDs silently drops it (spec M3); the next generation is probed
+// there and marked by EXT-X-DISCONTINUITY and a new EXT-X-MAP (pipeline.go,
+// D10). The box reader (box.go, init.go, fragment.go, reader.go) parses what
+// the encoder writes with encoding/binary and nothing else; the segmenter
+// (segmenter.go) cuts 2 s segments aligned across renditions; the Store
+// (store.go) holds them and renders every playlist (playlist.go, D7). A
+// rendition with no source this generation is relay-synthesised silence, never
+// an ffmpeg input (silence.go, M8). Quick Sync is used when a one-frame
+// detection encode succeeds, libx264 otherwise, and is written off for the
+// process only when a failure is shown to be the device's (detect.go, D11).
+//
+// THE PACKAGE IS INERT IN PHASE 4a-1a. Nothing in the relay imports it, so it
+// is outside the shipped binary and outside the Go coverage gate's
+// denominator (ruling R27); 4a-1b attaches a Pipeline through
+// Channel.AttachOutput and serves its Store under /hls/.
+//
+// Everything is in process memory (ADR 0006): no Redis, no Postgres, and the
+// standard library only (scripts/check_go_stdlib_only.sh).
+package hls
diff --git a/relay/hls/feed.go b/relay/hls/feed.go
new file mode 100644
index 00000000..901b5534
--- /dev/null
+++ b/relay/hls/feed.go
@@ -0,0 +1,113 @@
+package hls
+
+import (
+	"context"
+	"errors"
+	"io"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/buffer"
+)
+
+// Source is what a pipeline reads: the channel's ring, and where its source
+// boundaries fall. *channel.Channel satisfies it; relay/hls does not import
+// relay/channel, so 4a-1b can have the channel hold a pipeline without an
+// import cycle.
+type Source interface {
+	Ring() *buffer.Ring
+	// NextBoundary is the first source boundary strictly after the ring
+	// index after: the index of the first chunk a new upstream connection
+	// published or will publish (D10).
+	NextBoundary(after uint64) (uint64, bool)
+}
+
+// feedEnd is why a feed stopped.
+type feedEnd int
+
+const (
+	// feedBoundary: the next chunk belongs to a new upstream connection.
+	feedBoundary feedEnd = iota
+	// feedClosed: the channel's ring closed; the channel is ending.
+	feedClosed
+	// feedStopped: the context ended.
+	feedStopped
+	// feedWriteFailed: the process stopped reading its input.
+	feedWriteFailed
+	// feedLimit: the byte limit was reached (the probe's 5 MB).
+	feedLimit
+)
+
+// feedResult is how a feed ended.
+type feedResult struct {
+	end feedEnd
+	// boundary is the boundary index, for feedBoundary.
+	boundary uint64
+	// written is how many bytes were written.
+	written int
+}
+
+// feed writes the ring's chunks after start to w, stopping AT the first
+// source boundary after the generation's own first chunk: the chunk at the
+// boundary index is never written (D10). It is how a generation's input and
+// a probe's input are both bounded to one upstream connection's bytes, which
+// is the whole of D9's "reads from where that generation will start" and
+// D10's "the running generation's writer stops at that index".
+//
+// A boundary at start+1 is the generation's own beginning and is not a
+// reason to stop. Boundaries are recorded before the chunk at their index
+// can be published (channel.markBoundary), so checking after each read never
+// misses one. limit (0 for none) caps the bytes written; first is called
+// once with the index of the first chunk written, for the PDT anchor.
+func feed(ctx context.Context, src Source, start uint64, w io.Writer, limit int, first func(index uint64)) feedResult {
+	ring := src.Ring()
+	cursor := start
+	var res feedResult
+	for {
+		chunks, next, _ := ring.Read(cursor)
+		if len(chunks) > 0 {
+			index := next - uint64(len(chunks)) + 1
+			boundary, has := src.NextBoundary(start + 1)
+			for _, chunk := range chunks {
+				if has && index >= boundary {
+					res.end, res.boundary = feedBoundary, boundary
+					return res
+				}
+				if res.written == 0 && first != nil {
+					first(index)
+				}
+				if limit > 0 && res.written+len(chunk) > limit {
+					chunk = chunk[:limit-res.written]
+				}
+				if _, err := w.Write(chunk); err != nil {
+					res.end = feedWriteFailed
+					return res
+				}
+				res.written += len(chunk)
+				if limit > 0 && res.written >= limit {
+					res.end = feedLimit
+					return res
+				}
+				index++
+			}
+			cursor = next
+			continue
+		}
+		if err := ring.Wait(ctx, cursor); err != nil {
+			if errors.Is(err, buffer.ErrClosed) {
+				res.end = feedClosed
+			} else {
+				res.end = feedStopped
+			}
+			return res
+		}
+	}
+}
+
+// arrival is the PDT anchor's clock: the ring's arrival time for a chunk,
+// or now when the chunk has already left the ring.
+func arrival(ring *buffer.Ring, index uint64, now func() time.Time) time.Time {
+	if at, ok := ring.ArrivedAt(index); ok {
+		return at
+	}
+	return now()
+}
diff --git a/relay/hls/feed_test.go b/relay/hls/feed_test.go
new file mode 100644
index 00000000..89e521ad
--- /dev/null
+++ b/relay/hls/feed_test.go
@@ -0,0 +1,80 @@
+package hls
+
+import (
+	"bytes"
+	"context"
+	"errors"
+	"io"
+	"testing"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/buffer"
+)
+
+// chunkOf is one whole test chunk filled with b.
+func chunkOf(b byte) []byte { return bytes.Repeat([]byte{b}, testChunk) }
+
+// D10: a generation's writer stops AT the boundary -- the chunk at the
+// boundary index is never written -- and a boundary at the generation's own
+// first chunk is its start, not a reason to stop.
+func TestFeedStopsAtTheNextBoundary(t *testing.T) {
+	src := newTestSource()
+	src.mark() // the channel's first connection: index 1
+	src.write(t, chunkOf('a'))
+	src.write(t, chunkOf('a'))
+	boundary := src.mark()
+	src.write(t, chunkOf('b'))
+	var out bytes.Buffer
+	var first uint64
+	res := feed(context.Background(), src, 0, &out, 0, func(i uint64) { first = i })
+	if res.end != feedBoundary || res.boundary != boundary || boundary != 3 {
+		t.Fatalf("feed ended %v at %d, want at the boundary 3", res.end, res.boundary)
+	}
+	if !bytes.Equal(out.Bytes(), append(chunkOf('a'), chunkOf('a')...)) || first != 1 || res.written != 2*testChunk {
+		t.Fatalf("feed wrote %d bytes from %d, want exactly the first connection's two chunks", out.Len(), first)
+	}
+	out.Reset()
+	src.ring.Close()
+	res = feed(context.Background(), src, boundary-1, &out, 0, nil)
+	if res.end != feedClosed || !bytes.Equal(out.Bytes(), chunkOf('b')) {
+		t.Fatalf("the next generation fed %v, %d bytes, want the second connection's chunk and then the close", res.end, out.Len())
+	}
+}
+
+func TestFeedLimitStopAndWriteFailure(t *testing.T) {
+	src := newTestSource()
+	src.write(t, chunkOf('a'))
+	src.write(t, chunkOf('a'))
+	var out bytes.Buffer
+	res := feed(context.Background(), src, 0, &out, testChunk+10, nil)
+	if res.end != feedLimit || out.Len() != testChunk+10 {
+		t.Fatalf("a limited feed ended %v after %d bytes", res.end, out.Len())
+	}
+	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
+	defer cancel()
+	if res := feed(ctx, src, 2, io.Discard, 0, nil); res.end != feedStopped {
+		t.Fatalf("a feed with nothing to read did not stop with its context: %v", res.end)
+	}
+	if res := feed(context.Background(), src, 0, failingWriter{}, 0, nil); res.end != feedWriteFailed {
+		t.Fatalf("a write failure ended the feed %v", res.end)
+	}
+}
+
+type failingWriter struct{}
+
+func (failingWriter) Write([]byte) (int, error) { return 0, errors.New("broken pipe") }
+
+func TestArrival(t *testing.T) {
+	src := newTestSource()
+	at := time.Date(2026, 9, 27, 1, 2, 3, 0, time.UTC)
+	ring := buffer.New(buffer.Config{BudgetBytes: 10 * testChunk, ChunkBytes: testChunk, Now: func() time.Time { return at }})
+	_, _ = ring.Write(chunkOf('a'))
+	later := at.Add(time.Hour)
+	if got := arrival(ring, 1, func() time.Time { return later }); !got.Equal(at) {
+		t.Errorf("arrival of a chunk in the ring = %v, want its publish time", got)
+	}
+	if got := arrival(ring, 5, func() time.Time { return later }); !got.Equal(later) {
+		t.Errorf("arrival of a chunk not in the ring = %v, want now", got)
+	}
+	_ = src
+}
diff --git a/relay/hls/fragment.go b/relay/hls/fragment.go
new file mode 100644
index 00000000..b32d2c55
--- /dev/null
+++ b/relay/hls/fragment.go
@@ -0,0 +1,246 @@
+package hls
+
+import (
+	"encoding/binary"
+	"math"
+)
+
+// Fragment is one moof+mdat an encoder output wrote, with the timing the
+// segmenter cuts on.
+type Fragment struct {
+	// Data is the moof and its mdat, tfdt already moved onto the
+	// generation's shared timeline.
+	Data []byte
+	// Start is the tfdt: the first sample's decode time, in the track's
+	// timescale.
+	Start uint64
+	// Duration is the sum of the fragment's sample durations.
+	Duration uint64
+	// Samples is the trun's sample count.
+	Samples int
+	// Sync is whether the first sample is a sync sample. A segment must
+	// start with one (Apple 7.4); the segmenter checks it (spec D6).
+	Sync bool
+}
+
+// End is Start plus Duration.
+func (f Fragment) End() uint64 { return f.Start + f.Duration }
+
+// trunFlags are a trun's tf_flags: which optional fields it carries.
+type trunFlags uint32
+
+const (
+	trunDataOffset       trunFlags = 0x000001
+	trunFirstSampleFlags trunFlags = 0x000004
+	trunDuration         trunFlags = 0x000100
+	trunSize             trunFlags = 0x000200
+	trunFlagsPresent     trunFlags = 0x000400
+	trunCTO              trunFlags = 0x000800
+
+	tfhdBaseDataOffset  = 0x000001
+	tfhdSampleDescIndex = 0x000002
+	tfhdDefaultDuration = 0x000008
+	tfhdDefaultSize     = 0x000010
+	tfhdDefaultFlags    = 0x000020
+)
+
+// ParseFragment reads a moof+mdat for track t. It reads exactly one traf and
+// one trun, which is what ffmpeg writes for a one-track output; a fragment
+// for another track is an error, never silently someone else's samples.
+func ParseFragment(data []byte, t Track) (Fragment, error) {
+	moof, ok := child(data, 0, len(data), "moof")
+	if !ok || moof.start != 0 {
+		return Fragment{}, boxErr("a fragment must start with moof")
+	}
+	traf, ok := child(data, moof.body, moof.end, "traf")
+	if !ok {
+		return Fragment{}, boxErr("no traf in moof")
+	}
+	tfhd, ok := child(data, traf.body, traf.end, "tfhd")
+	if !ok {
+		return Fragment{}, boxErr("no tfhd in traf")
+	}
+	_, hflags, ok := fullBox(data, tfhd)
+	if !ok {
+		return Fragment{}, boxErr("short tfhd")
+	}
+	c := cursor{data: data, pos: tfhd.body + 4, end: tfhd.end}
+	trackID := c.u32()
+	if hflags&tfhdBaseDataOffset != 0 {
+		c.take(8)
+	}
+	if hflags&tfhdSampleDescIndex != 0 {
+		c.take(4)
+	}
+	duration, flags := t.DefaultDuration, t.DefaultFlags
+	if hflags&tfhdDefaultDuration != 0 {
+		duration = c.u32()
+	}
+	if hflags&tfhdDefaultSize != 0 {
+		c.take(4)
+	}
+	if hflags&tfhdDefaultFlags != 0 {
+		flags = c.u32()
+	}
+	if c.bad {
+		return Fragment{}, boxErr("short tfhd")
+	}
+	if trackID != t.ID {
+		return Fragment{}, boxErr("a fragment for track %d in a track-%d output", trackID, t.ID)
+	}
+
+	f := Fragment{Data: data}
+	if tfdt, ok := child(data, traf.body, traf.end, "tfdt"); ok {
+		version, _, ok := fullBox(data, tfdt)
+		if !ok {
+			return Fragment{}, boxErr("short tfdt")
+		}
+		tc := cursor{data: data, pos: tfdt.body + 4, end: tfdt.end}
+		if version == 1 {
+			f.Start = tc.u64()
+		} else {
+			f.Start = uint64(tc.u32())
+		}
+		if tc.bad {
+			return Fragment{}, boxErr("short tfdt")
+		}
+	} else {
+		return Fragment{}, boxErr("no tfdt in traf")
+	}
+
+	trun, ok := child(data, traf.body, traf.end, "trun")
+	if !ok {
+		return Fragment{}, boxErr("no trun in traf")
+	}
+	_, rflags, ok := fullBox(data, trun)
+	if !ok {
+		return Fragment{}, boxErr("short trun")
+	}
+	tf := trunFlags(rflags)
+	rc := cursor{data: data, pos: trun.body + 4, end: trun.end}
+	count := rc.u32()
+	if tf&trunDataOffset != 0 {
+		rc.take(4)
+	}
+	first := flags
+	if tf&trunFirstSampleFlags != 0 {
+		first = rc.u32()
+	}
+	per := 0
+	for _, bit := range []trunFlags{trunDuration, trunSize, trunFlagsPresent, trunCTO} {
+		if tf&bit != 0 {
+			per += 4
+		}
+	}
+	if rc.bad || uint64(count)*uint64(per) > uint64(rc.end-rc.pos) { // #nosec G115 -- rc.pos <= rc.end once rc.bad is false
+		return Fragment{}, boxErr("a trun of %d samples does not fit its box", count)
+	}
+	f.Samples = int(count)
+	for i := uint32(0); i < count; i++ {
+		d := duration
+		if tf&trunDuration != 0 {
+			d = rc.u32()
+		}
+		if tf&trunSize != 0 {
+			rc.take(4)
+		}
+		if tf&trunFlagsPresent != 0 {
+			sf := rc.u32()
+			if i == 0 && tf&trunFirstSampleFlags == 0 {
+				first = sf
+			}
+		}
+		if tf&trunCTO != 0 {
+			rc.take(4)
+		}
+		f.Duration += uint64(d)
+	}
+	f.Sync = count > 0 && sampleIsSync(first)
+	return f, nil
+}
+
+// shiftStart adds delta ticks to the fragment's tfdt, in place. ffmpeg writes
+// tfdt version 1 (64 bits); a version-0 tfdt that the shift would overflow
+// is an error rather than a wrapped timestamp.
+func shiftStart(f *Fragment, delta uint64) error {
+	if delta == 0 {
+		return nil
+	}
+	data := f.Data
+	moof, _ := child(data, 0, len(data), "moof")
+	traf, _ := child(data, moof.body, moof.end, "traf")
+	tfdt, ok := child(data, traf.body, traf.end, "tfdt")
+	if !ok {
+		return boxErr("no tfdt to shift")
+	}
+	version, _, _ := fullBox(data, tfdt)
+	at := tfdt.body + 4
+	if version == 1 {
+		if at+8 > tfdt.end {
+			return boxErr("short tfdt")
+		}
+		binary.BigEndian.PutUint64(data[at:], f.Start+delta)
+	} else {
+		if at+4 > tfdt.end || f.Start+delta > math.MaxUint32 {
+			return boxErr("a version-0 tfdt cannot hold %d", f.Start+delta)
+		}
+		binary.BigEndian.PutUint32(data[at:], uint32(f.Start+delta)) // #nosec G115 -- checked against MaxUint32 above
+	}
+	f.Start += delta
+	return nil
+}
+
+// synthFragment builds one fragment of count identical samples of frame,
+// each dur ticks, starting at start: one moof (mfhd, and a traf of tfhd with
+// default-base-is-moof and the three defaults, tfdt version 1, and a trun
+// with a data offset) and one mdat (spec § Encoder argv, silence). It is how
+// the relay writes a silent rendition, and -- with count 0 -- the empty
+// fragment an audio rendition gets for a segment its encoder wrote no audio
+// for.
+func synthFragment(seq, trackID uint32, start uint64, frame []byte, count int, dur uint32) []byte {
+	mfhd := fullBoxBytes("mfhd", 0, 0, be32(seq))
+	tfhd := fullBoxBytes("tfhd", 0, 0x020000|tfhdDefaultDuration|tfhdDefaultSize|tfhdDefaultFlags,
+		cat(be32(trackID), be32(dur), be32(uint32(len(frame))), be32(0x02000000))) // #nosec G115 -- a canned frame is a few kilobytes
+	tfdt := fullBoxBytes("tfdt", 1, 0, be64(start))
+	trun := fullBoxBytes("trun", 0, uint32(trunDataOffset), cat(be32(uint32(count)), be32(0))) // #nosec G115 -- count is a segment's frames, a few hundred
+	moof := box("moof", cat(mfhd, box("traf", cat(tfhd, tfdt, trun))))
+	// The trun's data_offset is from the moof's first byte (default-base-is-
+	// moof) to the first sample: past the moof and the mdat's header.
+	offset := len(moof) - 4
+	binary.BigEndian.PutUint32(moof[offset:], uint32(len(moof)+8)) // #nosec G115 -- a moof is a few dozen bytes
+	payload := make([]byte, 0, len(frame)*count)
+	for i := 0; i < count; i++ {
+		payload = append(payload, frame...)
+	}
+	return cat(moof, box("mdat", payload))
+}
+
+func fullBoxBytes(typ string, version byte, flags uint32, payload []byte) []byte {
+	head := be32(flags)
+	head[0] = version
+	return box(typ, cat(head, payload))
+}
+
+func be32(v uint32) []byte {
+	b := make([]byte, 4)
+	binary.BigEndian.PutUint32(b, v)
+	return b
+}
+
+func be64(v uint64) []byte {
+	b := make([]byte, 8)
+	binary.BigEndian.PutUint64(b, v)
+	return b
+}
+
+func cat(parts ...[]byte) []byte {
+	n := 0
+	for _, p := range parts {
+		n += len(p)
+	}
+	out := make([]byte, 0, n)
+	for _, p := range parts {
+		out = append(out, p...)
+	}
+	return out
+}
diff --git a/relay/hls/helpers_test.go b/relay/hls/helpers_test.go
new file mode 100644
index 00000000..d2a813e7
--- /dev/null
+++ b/relay/hls/helpers_test.go
@@ -0,0 +1,239 @@
+package hls
+
+import (
+	"os"
+	"sync"
+	"testing"
+
+	"github.com/D10Scot/Dispatcharr/relay/buffer"
+)
+
+// testChunk is the test ring's chunk: 64 packets, so a boundary lands within
+// 12 KB of where a test puts it rather than within a production chunk's
+// 255 KB.
+const testChunk = buffer.TSPacketSize * 64
+
+// testSource is a channel as a pipeline sees it: a ring, and the boundaries
+// a test marks on it exactly as channel.markBoundary does.
+type testSource struct {
+	ring *buffer.Ring
+	mu   sync.Mutex
+	b    []uint64
+}
+
+func newTestSource() *testSource {
+	return &testSource{ring: buffer.New(buffer.Config{BudgetBytes: 512 << 20, ChunkBytes: testChunk})}
+}
+
+func (s *testSource) Ring() *buffer.Ring { return s.ring }
+
+func (s *testSource) NextBoundary(after uint64) (uint64, bool) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	for _, b := range s.b {
+		if b > after {
+			return b, true
+		}
+	}
+	return 0, false
+}
+
+// mark records a source boundary: the next byte written starts a new
+// upstream connection.
+func (s *testSource) mark() uint64 {
+	index := s.ring.MarkBoundary()
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	s.b = append(s.b, index)
+	return index
+}
+
+// write puts b into the ring.
+func (s *testSource) write(t *testing.T, b []byte) {
+	t.Helper()
+	if _, err := s.ring.Write(b); err != nil {
+		t.Fatalf("writing the ring: %v", err)
+	}
+}
+
+// readFile is os.ReadFile with a test failure.
+func readFile(t *testing.T, path string) []byte {
+	t.Helper()
+	b, err := os.ReadFile(path) // #nosec G304 -- a test fixture path
+	if err != nil {
+		t.Fatalf("reading %s: %v", path, err)
+	}
+	return b
+}
+
+// initSpec describes a synthetic one-track init segment.
+type initSpec struct {
+	trackID        uint32
+	handler        string // "vide" or "soun"
+	timescale      uint32 // mdhd
+	movieTimescale uint32 // mvhd
+	entry          []byte // the stsd sample entry, whole box
+	// emptyEdit and mediaTime, when emptyEdit or mediaTime is non-zero,
+	// give the trak an edts: an empty edit of emptyEdit movie ticks, then a
+	// media edit starting at mediaTime.
+	emptyEdit uint32
+	mediaTime int32
+	// trexDuration, trexSize and trexFlags are the mvex defaults.
+	trexDuration, trexSize, trexFlags uint32
+	version1                          bool // mvhd, tkhd and mdhd version 1
+}
+
+func (s initSpec) build() []byte {
+	movie := s.movieTimescale
+	if movie == 0 {
+		movie = 1000
+	}
+	var mvhd, tkhd, mdhd []byte
+	if s.version1 {
+		mvhd = fullBoxBytes("mvhd", 1, 0, cat(make([]byte, 16), be32(movie), make([]byte, 8), make([]byte, 80)))
+		tkhd = fullBoxBytes("tkhd", 1, 3, cat(make([]byte, 16), be32(s.trackID), make([]byte, 4), make([]byte, 8), make([]byte, 60)))
+		mdhd = fullBoxBytes("mdhd", 1, 0, cat(make([]byte, 16), be32(s.timescale), make([]byte, 8), make([]byte, 4)))
+	} else {
+		mvhd = fullBoxBytes("mvhd", 0, 0, cat(make([]byte, 8), be32(movie), make([]byte, 4), make([]byte, 80)))
+		tkhd = fullBoxBytes("tkhd", 0, 3, cat(make([]byte, 8), be32(s.trackID), make([]byte, 4), make([]byte, 4), make([]byte, 60)))
+		mdhd = fullBoxBytes("mdhd", 0, 0, cat(make([]byte, 8), be32(s.timescale), make([]byte, 4), make([]byte, 4)))
+	}
+	hdlr := fullBoxBytes("hdlr", 0, 0, cat(make([]byte, 4), []byte(s.handler), make([]byte, 12), []byte("h\x00")))
+	stsd := fullBoxBytes("stsd", 0, 0, cat(be32(1), s.entry))
+	stbl := box("stbl", stsd)
+	minf := box("minf", stbl)
+	mdia := box("mdia", cat(mdhd, hdlr, minf))
+	trakBody := tkhd
+	if s.emptyEdit != 0 || s.mediaTime != 0 {
+		var entries []byte
+		count := uint32(0)
+		if s.emptyEdit != 0 {
+			entries = append(entries, cat(be32(s.emptyEdit), be32(0xffffffff), be32(0x00010000))...)
+			count++
+		}
+		entries = append(entries, cat(be32(0), be32(uint32(s.mediaTime)), be32(0x00010000))...) // #nosec G115 -- a test's small media time
+		count++
+		trakBody = cat(trakBody, box("edts", fullBoxBytes("elst", 0, 0, cat(be32(count), entries))))
+	}
+	trak := box("trak", cat(trakBody, mdia))
+	trex := fullBoxBytes("trex", 0, 0, cat(be32(s.trackID), be32(1), be32(s.trexDuration), be32(s.trexSize), be32(s.trexFlags)))
+	moov := box("moov", cat(mvhd, trak, box("mvex", trex)))
+	ftyp := box("ftyp", []byte("iso5\x00\x00\x02\x00iso5iso6mp41"))
+	return cat(ftyp, moov)
+}
+
+// avc1Entry is a VisualSampleEntry carrying an avcC of the given profile,
+// constraint and level bytes.
+func avc1Entry(profile, constraint, level byte) []byte {
+	fixed := make([]byte, 70)
+	avcC := box("avcC", []byte{1, profile, constraint, level, 0xff, 0xe0})
+	return box("avc1", cat(make([]byte, 6), []byte{0, 1}, fixed, avcC))
+}
+
+// audioEntry is an AudioSampleEntry of type typ with child boxes.
+func audioEntry(typ string, children ...[]byte) []byte {
+	fixed := make([]byte, 20)
+	return box(typ, cat(append([][]byte{make([]byte, 6), {0, 1}, fixed}, children...)...))
+}
+
+// esdsAAC is an esds for MPEG-4 audio object type aot.
+func esdsAAC(aot byte) []byte {
+	asc := []byte{aot<<3 | 0x01, 0x90}
+	if aot >= 32 {
+		// escape: 31 in the top five bits, then six bits of aot-32
+		ext := aot - 32
+		asc = []byte{31<<3 | ext>>3, ext << 5, 0x00}
+	}
+	dsi := cat([]byte{0x05, byte(len(asc))}, asc)
+	dcd := cat([]byte{0x04, byte(13 + len(dsi)), 0x40, 0x15}, make([]byte, 11), dsi)
+	es := cat([]byte{0x03, byte(3 + len(dcd) + 3)}, []byte{0, 1, 0}, dcd, []byte{0x06, 0x01, 0x02})
+	return fullBoxBytes("esds", 0, 0, es)
+}
+
+// videoInit and audioInit are the synthetic inits the pipeline tests' stand-in
+// encoders write: a 12800 Hz H.264 video track and a 48 kHz AAC track.
+func videoInit(emptyEdit uint32) []byte {
+	return initSpec{trackID: 1, handler: "vide", timescale: 12800, movieTimescale: 1000, entry: avc1Entry(0x64, 0, 0x2a), emptyEdit: emptyEdit}.build()
+}
+
+func audioInit() []byte {
+	return initSpec{trackID: 1, handler: "soun", timescale: 48000, movieTimescale: 1000, entry: audioEntry("mp4a", esdsAAC(2))}.build()
+}
+
+// fragSpec describes one synthetic fragment.
+type fragSpec struct {
+	seq       uint32
+	trackID   uint32
+	start     uint64
+	durations []uint32 // one per sample, in trun
+	sync      bool     // the first sample's flags
+	v0        bool     // tfdt version 0
+}
+
+func (f fragSpec) build() []byte {
+	firstFlags := uint32(0x01010000) // depends on others, non-sync
+	if f.sync {
+		firstFlags = 0x02000000
+	}
+	tfhd := fullBoxBytes("tfhd", 0, 0x020000|tfhdDefaultSize, cat(be32(f.trackID), be32(4)))
+	var tfdt []byte
+	if f.v0 {
+		tfdt = fullBoxBytes("tfdt", 0, 0, be32(uint32(f.start))) // #nosec G115 -- a test's small start
+	} else {
+		tfdt = fullBoxBytes("tfdt", 1, 0, be64(f.start))
+	}
+	var samples []byte
+	for _, d := range f.durations {
+		samples = append(samples, be32(d)...)
+	}
+	trun := fullBoxBytes("trun", 0, uint32(trunDataOffset|trunFirstSampleFlags|trunDuration),
+		cat(be32(uint32(len(f.durations))), be32(0), be32(firstFlags), samples)) // #nosec G115 -- a test's few samples
+	moof := box("moof", cat(fullBoxBytes("mfhd", 0, 0, be32(f.seq)), box("traf", cat(tfhd, tfdt, trun))))
+	return cat(moof, box("mdat", make([]byte, 4*len(f.durations))))
+}
+
+// videoStream is a synthetic video output: its init, then n fragments of
+// perFrag 25 fps frames each (512 ticks at 12800 Hz), every fragment opening
+// on a sync sample.
+func videoStream(emptyEdit uint32, n, perFrag int) []byte {
+	out := videoInit(emptyEdit)
+	for i := 0; i < n; i++ {
+		d := make([]uint32, perFrag)
+		for j := range d {
+			d[j] = 512
+		}
+		out = append(out, fragSpec{seq: uint32(i + 1), trackID: 1, start: uint64(i * perFrag * 512), durations: d, sync: true}.build()...) // #nosec G115 -- a test's small counts
+	}
+	return out
+}
+
+// audioStream is a synthetic AAC output: its init, then n 200 ms fragments
+// of 1024-sample frames (9 or 10 frames each, so the starts stay on frames).
+func audioStream(n int) []byte {
+	out := audioInit()
+	start := uint64(0)
+	for i := 0; i < n; i++ {
+		frames := 9
+		if i%3 == 2 {
+			frames = 10
+		}
+		d := make([]uint32, frames)
+		for j := range d {
+			d[j] = 1024
+		}
+		out = append(out, fragSpec{seq: uint32(i + 1), trackID: 1, start: start, durations: d, sync: true}.build()...) // #nosec G115 -- a test's small counts
+		start += uint64(frames * 1024)
+	}
+	return out
+}
+
+func joinArgs(argv []string) string {
+	out := ""
+	for i, a := range argv {
+		if i > 0 {
+			out += " "
+		}
+		out += a
+	}
+	return out
+}
diff --git a/relay/hls/init.go b/relay/hls/init.go
new file mode 100644
index 00000000..721f68b4
--- /dev/null
+++ b/relay/hls/init.go
@@ -0,0 +1,433 @@
+package hls
+
+import (
+	"encoding/binary"
+	"fmt"
+	"math"
+	"strings"
+)
+
+// Track is what the segmenter and the playlists need from one rendition's
+// init segment.
+type Track struct {
+	// ID is the track_ID every fragment's tfhd names (tkhd).
+	ID uint32
+	// Handler is the media handler type, "vide" or "soun" (hdlr).
+	Handler string
+	// Timescale is the media timescale: tfdt and every sample duration are in
+	// ticks of it (mdhd).
+	Timescale uint32
+	// Codec is the rendition's RFC 6381 CODECS value, read from the sample
+	// entry's configuration box (spec D7): avcC, hvcC, esds, dac3 or dec3.
+	// Empty for a codec this reader does not name.
+	Codec string
+	// DefaultDuration, DefaultSize and DefaultFlags are the movie-extends
+	// defaults (trex), which a fragment's tfhd and trun may leave implicit.
+	DefaultDuration uint32
+	DefaultSize     uint32
+	DefaultFlags    uint32
+	// StartOffset is where the track's first sample is presented, in ticks
+	// of Timescale, on the output's shared timeline (see edits).
+	StartOffset uint64
+}
+
+// ParseInit reads the one track of an init segment: ftyp and a moov holding
+// one trak.
+//
+// WHY StartOffset EXISTS. ffmpeg's mp4 muxer starts every track's tfdt at 0
+// and records where the track really starts, relative to the output's zero,
+// as an empty edit in the track's edit list (measured on ffmpeg 9.0.1: a
+// stream joined mid-GOP gives the video an empty edit of 0.86 s and the
+// copied AC-3 none, from the same ffmpeg process). Each rendition is a
+// separate output file, so their tfdt timelines do NOT line up with each
+// other, and an HLS player aligns renditions by tfdt; hls.js ignores edit
+// lists outright. The segmenter therefore moves every fragment's tfdt by the
+// track's StartOffset and serves the init with its edit list stripped, so
+// every rendition of a generation is on one timeline by tfdt alone.
+func ParseInit(init []byte) (Track, error) {
+	top, err := children(init, 0, len(init))
+	if err != nil {
+		return Track{}, err
+	}
+	var moov span
+	var found bool
+	for _, s := range top {
+		if s.typ == "moov" {
+			moov, found = s, true
+			break
+		}
+	}
+	if !found {
+		return Track{}, boxErr("no moov in a %d-byte init segment", len(init))
+	}
+	var t Track
+	movieTimescale, ok := mvhdTimescale(init, moov)
+	if !ok {
+		return Track{}, boxErr("no readable mvhd")
+	}
+	trak, ok := child(init, moov.body, moov.end, "trak")
+	if !ok {
+		return Track{}, boxErr("no trak in moov")
+	}
+	if t.ID, ok = tkhdTrackID(init, trak); !ok {
+		return Track{}, boxErr("no readable tkhd")
+	}
+	mdia, ok := child(init, trak.body, trak.end, "mdia")
+	if !ok {
+		return Track{}, boxErr("no mdia in trak")
+	}
+	if t.Timescale, ok = mdhdTimescale(init, mdia); !ok || t.Timescale == 0 {
+		return Track{}, boxErr("no readable mdhd timescale")
+	}
+	if hdlr, ok := child(init, mdia.body, mdia.end, "hdlr"); ok && hdlr.body+12 <= hdlr.end {
+		t.Handler = string(init[hdlr.body+8 : hdlr.body+12])
+	}
+	if entry, ok := sampleEntry(init, mdia); ok {
+		t.Codec = codecString(init, entry)
+	}
+	if mvex, ok := child(init, moov.body, moov.end, "mvex"); ok {
+		list, _ := children(init, mvex.body, mvex.end)
+		for _, s := range list {
+			if s.typ != "trex" {
+				continue
+			}
+			c := cursor{data: init, pos: s.body + 4, end: s.end}
+			id := c.u32()
+			c.u32() // default_sample_description_index
+			duration, size, flags := c.u32(), c.u32(), c.u32()
+			if !c.bad && id == t.ID {
+				t.DefaultDuration, t.DefaultSize, t.DefaultFlags = duration, size, flags
+			}
+		}
+	}
+	t.StartOffset = startOffset(init, trak, movieTimescale, t.Timescale)
+	return t, nil
+}
+
+func mvhdTimescale(data []byte, moov span) (uint32, bool) {
+	s, ok := child(data, moov.body, moov.end, "mvhd")
+	if !ok {
+		return 0, false
+	}
+	version, _, ok := fullBox(data, s)
+	if !ok {
+		return 0, false
+	}
+	c := cursor{data: data, pos: s.body + 4, end: s.end}
+	if version == 1 {
+		c.take(16)
+	} else {
+		c.take(8)
+	}
+	timescale := c.u32()
+	return timescale, !c.bad
+}
+
+func mdhdTimescale(data []byte, mdia span) (uint32, bool) {
+	s, ok := child(data, mdia.body, mdia.end, "mdhd")
+	if !ok {
+		return 0, false
+	}
+	version, _, ok := fullBox(data, s)
+	if !ok {
+		return 0, false
+	}
+	c := cursor{data: data, pos: s.body + 4, end: s.end}
+	if version == 1 {
+		c.take(16)
+	} else {
+		c.take(8)
+	}
+	timescale := c.u32()
+	return timescale, !c.bad
+}
+
+func tkhdTrackID(data []byte, trak span) (uint32, bool) {
+	s, ok := child(data, trak.body, trak.end, "tkhd")
+	if !ok {
+		return 0, false
+	}
+	version, _, ok := fullBox(data, s)
+	if !ok {
+		return 0, false
+	}
+	c := cursor{data: data, pos: s.body + 4, end: s.end}
+	if version == 1 {
+		c.take(16)
+	} else {
+		c.take(8)
+	}
+	id := c.u32()
+	return id, !c.bad
+}
+
+// startOffset reads the track's edit list: the empty edits that open it
+// (media_time -1) delay its presentation, and the first real edit's
+// media_time skips into it. Both are moved into tfdt (ParseInit), so the
+// result is empty-edit time minus media_time, in media ticks, and never
+// below zero -- a priming edit longer than the delay (an encoder's
+// 1024-sample AAC priming with no delay before it) presents its priming
+// samples rather than a negative time.
+func startOffset(data []byte, trak span, movieTimescale, mediaTimescale uint32) uint64 {
+	elst, ok := path(data, trak.body, trak.end, "edts", "elst")
+	if !ok || movieTimescale == 0 {
+		return 0
+	}
+	version, _, ok := fullBox(data, elst)
+	if !ok {
+		return 0
+	}
+	c := cursor{data: data, pos: elst.body + 4, end: elst.end}
+	count := c.u32()
+	var empty, mediaTime uint64
+	for i := uint32(0); i < count && !c.bad; i++ {
+		// media_time is signed, and -1 (all ones) marks an empty edit; any
+		// other negative value is malformed and reads as a huge one here.
+		var duration uint64
+		var isEmpty bool
+		if version == 1 {
+			duration, mediaTime = c.u64(), c.u64()
+			isEmpty = mediaTime == math.MaxUint64
+		} else {
+			duration, mediaTime = uint64(c.u32()), uint64(c.u32())
+			isEmpty = mediaTime == math.MaxUint32
+		}
+		c.take(4) // media_rate
+		if c.bad {
+			return 0
+		}
+		if isEmpty {
+			empty += duration
+			mediaTime = 0
+			continue
+		}
+		break
+	}
+	offset := empty * uint64(mediaTimescale) / uint64(movieTimescale)
+	if mediaTime >= offset {
+		return 0
+	}
+	return offset - mediaTime
+}
+
+// sampleEntry is the first entry of the track's stsd.
+func sampleEntry(data []byte, mdia span) (span, bool) {
+	stsd, ok := path(data, mdia.body, mdia.end, "minf", "stbl", "stsd")
+	if !ok || stsd.body+8 > stsd.end {
+		return span{}, false
+	}
+	// The stsd's version, flags and entry count, then the entries.
+	entries, _ := children(data, stsd.body+8, stsd.end)
+	if len(entries) == 0 {
+		return span{}, false
+	}
+	return entries[0], true
+}
+
+// sampleEntryHeader is the fixed part of a sample entry before its child
+// boxes: 8 bytes of SampleEntry, then 70 more for a VisualSampleEntry or 20
+// for an AudioSampleEntry (ISO/IEC 14496-12, 12.1.3 and 12.2.3).
+func sampleEntryHeader(typ string) (int, bool) {
+	switch typ {
+	case "avc1", "avc3", "hvc1", "hev1":
+		return 78, true
+	case "mp4a", "ac-3", "ec-3":
+		return 28, true
+	}
+	return 0, false
+}
+
+// codecString is spec D7's rule: the CODECS value comes from the init
+// segment, so it stays true in every mode, copy included.
+func codecString(data []byte, entry span) string {
+	fixed, ok := sampleEntryHeader(entry.typ)
+	if !ok || entry.body+fixed > entry.end {
+		return ""
+	}
+	from, to := entry.body+fixed, entry.end
+	switch entry.typ {
+	case "avc1", "avc3":
+		if b, ok := child(data, from, to, "avcC"); ok && b.body+4 <= b.end {
+			p := data[b.body:]
+			return fmt.Sprintf("%s.%02x%02x%02x", entry.typ, p[1], p[2], p[3])
+		}
+	case "hvc1", "hev1":
+		if b, ok := child(data, from, to, "hvcC"); ok && b.body+13 <= b.end {
+			return hevcCodec(entry.typ, data[b.body:b.body+13])
+		}
+	case "mp4a":
+		if b, ok := child(data, from, to, "esds"); ok {
+			return mp4aCodec(data[b.body:b.end])
+		}
+	case "ac-3":
+		return "ac-3"
+	case "ec-3":
+		return "ec-3"
+	}
+	return ""
+}
+
+// hevcCodec is ISO/IEC 14496-15 Annex E's HEVC codecs parameter, from the
+// first 13 bytes of an HEVCDecoderConfigurationRecord: the profile space
+// letter and profile_idc, the compatibility flags bit-reversed in hex, the
+// tier letter and level_idc, then each constraint byte, trailing zero bytes
+// omitted. "hvc1.1.6.L93.B0" is Main, level 3.1.
+func hevcCodec(prefix string, rec []byte) string {
+	space := rec[1] >> 6
+	tier := (rec[1] >> 5) & 1
+	profile := rec[1] & 0x1f
+	compat := binary.BigEndian.Uint32(rec[2:6])
+	var reversed uint32
+	for i := 0; i < 32; i++ {
+		if compat&(1<<i) != 0 {
+			reversed |= 1 << (31 - i)
+		}
+	}
+	var b strings.Builder
+	b.WriteString(prefix)
+	b.WriteByte('.')
+	if space > 0 {
+		b.WriteByte("ABC"[space-1])
+	}
+	fmt.Fprintf(&b, "%d.%X.", profile, reversed)
+	if tier == 1 {
+		b.WriteByte('H')
+	} else {
+		b.WriteByte('L')
+	}
+	fmt.Fprintf(&b, "%d", rec[12])
+	constraints := rec[6:12]
+	last := -1
+	for i, c := range constraints {
+		if c != 0 {
+			last = i
+		}
+	}
+	for i := 0; i <= last; i++ {
+		fmt.Fprintf(&b, ".%X", constraints[i])
+	}
+	return b.String()
+}
+
+// mp4aCodec reads an esds FullBox's payload: the ES descriptor, its decoder
+// configuration's objectTypeIndication, and the audio object type at the top
+// of the decoder-specific info. "mp4a.40.2" is AAC-LC.
+func mp4aCodec(esds []byte) string {
+	if len(esds) < 4 {
+		return ""
+	}
+	c := &cursor{data: esds, pos: 4, end: len(esds)}
+	if tag, _ := descriptor(c); tag != 0x03 {
+		return ""
+	}
+	c.take(2) // ES_ID
+	flags := c.u8()
+	if flags&0x80 != 0 {
+		c.take(2)
+	}
+	if flags&0x40 != 0 {
+		c.take(int(c.u8()))
+	}
+	if flags&0x20 != 0 {
+		c.take(2)
+	}
+	if tag, _ := descriptor(c); tag != 0x04 {
+		return ""
+	}
+	oti := c.u8()
+	c.take(12)
+	if c.bad {
+		return ""
+	}
+	if tag, length := descriptor(c); tag != 0x05 || length < 1 {
+		return fmt.Sprintf("mp4a.%x", oti)
+	}
+	first := c.u8()
+	aot := int(first >> 3)
+	if aot == 31 {
+		second := c.u8()
+		aot = 32 + (int(first&0x07)<<3 | int(second>>5))
+	}
+	if c.bad {
+		return fmt.Sprintf("mp4a.%x", oti)
+	}
+	return fmt.Sprintf("mp4a.%x.%d", oti, aot)
+}
+
+// descriptor reads an MPEG-4 descriptor's tag and its variable-length size
+// (up to four bytes, seven bits each).
+func descriptor(c *cursor) (tag byte, length int) {
+	tag = c.u8()
+	for i := 0; i < 4; i++ {
+		b := c.u8()
+		length = length<<7 | int(b&0x7f)
+		if b&0x80 == 0 {
+			break
+		}
+	}
+	if c.bad {
+		return 0, 0
+	}
+	return tag, length
+}
+
+// StripEdits returns init with every edts box removed from every trak, and
+// the sizes of the boxes that held them corrected. ParseInit's StartOffset
+// is what replaces the edit list: the segmenter moves each fragment's tfdt
+// by it, so an edit list left in place would apply the offset twice for a
+// player that honours it and not at all for one that does not.
+func StripEdits(init []byte) ([]byte, error) {
+	top, err := children(init, 0, len(init))
+	if err != nil {
+		return nil, err
+	}
+	out := make([]byte, 0, len(init))
+	for _, s := range top {
+		if s.typ != "moov" {
+			out = append(out, init[s.start:s.end]...)
+			continue
+		}
+		moov, err := rebuild(init, s, func(inner span) ([]byte, error) {
+			if inner.typ != "trak" {
+				return init[inner.start:inner.end], nil
+			}
+			return rebuild(init, inner, func(t span) ([]byte, error) {
+				if t.typ == "edts" {
+					return nil, nil
+				}
+				return init[t.start:t.end], nil
+			})
+		})
+		if err != nil {
+			return nil, err
+		}
+		out = append(out, moov...)
+	}
+	return out, nil
+}
+
+// rebuild re-emits container box s with each child replaced by what keep
+// returns for it (nil drops the child), with a fresh 32-bit header.
+func rebuild(data []byte, s span, keep func(span) ([]byte, error)) ([]byte, error) {
+	list, err := children(data, s.body, s.end)
+	if err != nil {
+		return nil, err
+	}
+	body := make([]byte, 0, s.end-s.body)
+	for _, c := range list {
+		kept, err := keep(c)
+		if err != nil {
+			return nil, err
+		}
+		body = append(body, kept...)
+	}
+	return box(s.typ, body), nil
+}
+
+// box is a plain box: a 32-bit size, the type, the payload.
+func box(typ string, payload []byte) []byte {
+	out := make([]byte, 8, 8+len(payload))
+	binary.BigEndian.PutUint32(out, uint32(8+len(payload))) // #nosec G115 -- every box built here is far below 4 GiB (maxBoxBytes)
+	copy(out[4:], typ)
+	return append(out, payload...)
+}
diff --git a/relay/hls/pipeline.go b/relay/hls/pipeline.go
new file mode 100644
index 00000000..1b8aaf74
--- /dev/null
+++ b/relay/hls/pipeline.go
@@ -0,0 +1,675 @@
+package hls
+
+import (
+	"context"
+	"errors"
+	"fmt"
+	"io"
+	"log/slog"
+	"strings"
+	"sync"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
+	"github.com/D10Scot/Dispatcharr/relay/redact"
+)
+
+// GenerationExitGrace is how long a generation may keep running after its
+// stdin closed before it is killed (spec D10). ffmpeg.KillWait stays the
+// reap budget after the kill.
+const GenerationExitGrace = 5 * time.Second
+
+// The restart bound (spec § Encoder argv, failure): a generation that dies
+// after its first segment is restarted as at a source boundary, but a third
+// such death within deathWindow is a total failure.
+const (
+	deathWindow = 60 * time.Second
+	maxDeaths   = 3
+)
+
+// stopJoinWait bounds Stop's wait for the pipeline to wind down: the exit
+// grace, the reap budget and a margin.
+const stopJoinWait = GenerationExitGrace + ffmpeg.KillWait + 2*time.Second
+
+// stderrTail is how many of a generation's last stderr lines a total
+// failure's ERROR carries.
+const stderrTail = 10
+
+// ErrFailed is a pipeline that gave up (spec § Encoder argv, failure): every
+// attempt at a generation exited before its first segment, a later
+// generation's probe found no video, or generations kept dying. 4a-1b turns
+// it into the channel's hlsFailedUntilBoundary mark.
+var ErrFailed = errors.New("hls: the HLS output failed")
+
+// Spawn is one encoder process the pipeline is about to start: which
+// generation and attempt, on which engine, and the argv it built.
+type Spawn struct {
+	Generation int
+	Attempt    int
+	Engine     Engine
+	Argv       []string
+	Extra      []bool
+}
+
+// Config is one pipeline's configuration.
+type Config struct {
+	// ChannelID names the channel in logs.
+	ChannelID string
+	// Source is the channel: its ring and its boundaries.
+	Source Source
+	// JoinBehind is how far behind live generation 0 starts (and is probed
+	// from), the fMP4 remux's own join point. Zero starts at the ring's
+	// head.
+	JoinBehind time.Duration
+	// Detector and Silence are process-wide; nil gives the pipeline its own.
+	Detector *Detector
+	Silence  *SilenceCache
+	// FFmpeg and FFprobe are the executables ("ffmpeg" and "ffprobe" when
+	// empty). Device is the QSV render node (DefaultDevice when empty).
+	FFmpeg  string
+	FFprobe string
+	Device  string
+	// ExitGrace overrides GenerationExitGrace, and AudioWait the segmenter's
+	// AudioWait, for tests.
+	ExitGrace time.Duration
+	AudioWait time.Duration
+	// Command maps a Spawn to the command and argv actually run. Nil runs
+	// FFmpeg with the built argv; the stand-in tests replace it.
+	Command func(Spawn) (string, []string)
+	// ProbeCommand maps a probe to the command and argv run, by generation.
+	// Nil runs FFprobe with ProbeArgv.
+	ProbeCommand func(generation int) (string, []string)
+	// Log and Now are the logger and the clock.
+	Log *slog.Logger
+	Now func() time.Time
+}
+
+// Pipeline is one channel's HLS output (spec § State): the current
+// generation -- an ffmpeg child, its probe, its fixed output parameters --
+// and the Store its segmenter publishes into. It is started by Start and runs
+// until Stop, the channel's ring closing, or ErrFailed.
+//
+// IT IS INERT IN 4a-1a. Nothing in the relay constructs one: 4a-1b's HLS
+// entry path attaches it through Channel.AttachOutput and serves its Store.
+type Pipeline struct {
+	cfg    Config
+	log    *slog.Logger
+	store  *Store
+	det    *Detector
+	sil    *SilenceCache
+	now    func() time.Time
+	cancel context.CancelFunc
+	done   chan struct{}
+
+	readyOnce sync.Once
+	readyCh   chan struct{}
+	// background is the goroutines a pipeline starts beyond its generation:
+	// the re-run of the detection encode (D11). run waits for them.
+	background sync.WaitGroup
+
+	mu       sync.Mutex
+	err      error
+	readyErr error
+	output   *Output
+	codecs   map[string]string
+	engine   Engine
+	gen      int
+	probes   map[int]Probe
+}
+
+// Start begins a pipeline. It returns at once: the probe (up to 8 s) and the
+// wait for generation 0's init segments (bounded by the caller, 20 s in
+// 4a-1b) run outside it, so a caller holding a lock -- AttachOutput's outMu
+// -- is never held behind them (D9). Ready is the wait.
+func Start(ctx context.Context, cfg Config) (*Pipeline, error) {
+	if cfg.Source == nil || cfg.Source.Ring() == nil {
+		return nil, errors.New("hls: a pipeline needs a source ring")
+	}
+	log := cfg.Log
+	if log == nil {
+		log = slog.Default()
+	}
+	now := cfg.Now
+	if now == nil {
+		now = time.Now
+	}
+	det := cfg.Detector
+	if det == nil {
+		det = &Detector{Command: cfg.FFmpeg, Device: cfg.Device, Log: log}
+	}
+	sil := cfg.Silence
+	if sil == nil {
+		sil = &SilenceCache{Command: cfg.FFmpeg, Log: log}
+	}
+	ctx, cancel := context.WithCancel(ctx)
+	p := &Pipeline{
+		cfg:     cfg,
+		log:     log.With("channel", cfg.ChannelID, "format", "hls"),
+		store:   NewStore(now),
+		det:     det,
+		sil:     sil,
+		now:     now,
+		cancel:  cancel,
+		done:    make(chan struct{}),
+		readyCh: make(chan struct{}),
+		probes:  map[int]Probe{},
+	}
+	go p.run(ctx)
+	return p, nil
+}
+
+// Store is the pipeline's segments and playlists.
+func (p *Pipeline) Store() *Store { return p.store }
+
+// Done is closed when the pipeline has ended.
+func (p *Pipeline) Done() <-chan struct{} { return p.done }
+
+// Err is why the pipeline ended: ErrFailed or ErrNoVideo, or nil for a stop
+// or the channel's ring closing.
+func (p *Pipeline) Err() error {
+	p.mu.Lock()
+	defer p.mu.Unlock()
+	return p.err
+}
+
+// Engine is the engine the current generation runs on, for 4a-1b's
+// hls_encoder payload field.
+func (p *Pipeline) Engine() Engine {
+	p.mu.Lock()
+	defer p.mu.Unlock()
+	return p.engine
+}
+
+// Generation is the current generation number, for hls_generation.
+func (p *Pipeline) Generation() int {
+	p.mu.Lock()
+	defer p.mu.Unlock()
+	return p.gen
+}
+
+// GenerationProbe is what a generation's probe found.
+func (p *Pipeline) GenerationProbe(gen int) (Probe, bool) {
+	p.mu.Lock()
+	defer p.mu.Unlock()
+	probe, ok := p.probes[gen]
+	return probe, ok
+}
+
+// Output is the run's fixed output, once generation 0's probe has decided it.
+func (p *Pipeline) Output() (Output, bool) {
+	p.mu.Lock()
+	defer p.mu.Unlock()
+	if p.output == nil {
+		return Output{}, false
+	}
+	return *p.output, true
+}
+
+// Ready waits until every generation-0 init segment exists (the multivariant
+// waits for them, D7), the pipeline ends first, or ctx ends. It reports
+// readiness, not health: a pipeline that fails after its inits exist still
+// answers nil here, and Done and Err are what say it ended.
+func (p *Pipeline) Ready(ctx context.Context) error {
+	select {
+	case <-ctx.Done():
+		return ctx.Err()
+	case <-p.readyCh:
+		p.mu.Lock()
+		defer p.mu.Unlock()
+		return p.readyErr
+	}
+}
+
+// Multivariant renders the multivariant playlist under base, once Ready.
+func (p *Pipeline) Multivariant(base string) ([]byte, error) {
+	select {
+	case <-p.readyCh:
+	default:
+		return nil, errors.New("hls: the multivariant is not ready")
+	}
+	p.mu.Lock()
+	defer p.mu.Unlock()
+	if p.readyErr != nil {
+		return nil, p.readyErr
+	}
+	return Multivariant(*p.output, p.codecs, base), nil
+}
+
+// Stop ends the pipeline and waits, bounded, for its generation to go.
+func (p *Pipeline) Stop() {
+	p.cancel()
+	select {
+	case <-p.done:
+	case <-time.After(stopJoinWait):
+		p.log.Warn("the HLS pipeline did not stop in time")
+	}
+}
+
+func (p *Pipeline) markReady(err error) {
+	p.readyOnce.Do(func() {
+		p.mu.Lock()
+		p.readyErr = err
+		p.mu.Unlock()
+		close(p.readyCh)
+	})
+}
+
+// noteInit records a rendition's init segment, and generation 0's CODECS
+// values, and marks the pipeline ready once generation 0 has every one.
+func (p *Pipeline) noteInit(name string, gen int, data []byte, codec string) {
+	p.store.SetInit(name, gen, data)
+	if gen != 0 {
+		return
+	}
+	p.mu.Lock()
+	if p.codecs == nil {
+		p.codecs = map[string]string{}
+	}
+	p.codecs[name] = codec
+	out := p.output
+	p.mu.Unlock()
+	if out != nil && p.store.hasInits(0, out.Renditions()) {
+		p.markReady(nil)
+	}
+}
+
+func (p *Pipeline) finish(err error) {
+	p.mu.Lock()
+	p.err = err
+	p.mu.Unlock()
+	if err == nil {
+		err = ErrStoreClosed
+	}
+	p.markReady(err)
+}
+
+// run is the generation loop (D10): probe where the generation starts, run
+// it with the failure policy, and at a source boundary or a death start the
+// next one.
+func (p *Pipeline) run(ctx context.Context) {
+	defer close(p.done)
+	defer p.background.Wait()
+	defer p.store.Close()
+
+	ring := p.cfg.Source.Ring()
+	start := ring.Head()
+	if p.cfg.JoinBehind > 0 {
+		start = ring.Join(p.cfg.JoinBehind)
+	}
+	var deaths []time.Time
+	for gen := 0; ; gen++ {
+		if ctx.Err() != nil {
+			p.finish(nil)
+			return
+		}
+		probe, err := p.probe(ctx, gen, start)
+		if ctx.Err() != nil {
+			p.finish(nil)
+			return
+		}
+		if err != nil {
+			p.log.Error("the HLS probe failed", "generation", gen, "error", redact.Error(err))
+			p.finish(ErrFailed)
+			return
+		}
+		p.mu.Lock()
+		p.probes[gen] = probe
+		delete(p.probes, gen-16)
+		p.gen = gen
+		first := p.output == nil
+		p.mu.Unlock()
+		if first {
+			out, err := Decide(probe)
+			if err != nil {
+				p.log.Error("the HLS source has no video stream", "generation", gen)
+				p.finish(ErrNoVideo)
+				return
+			}
+			p.mu.Lock()
+			p.output = &out
+			p.mu.Unlock()
+		} else if probe.Video == nil {
+			p.log.Error("a later HLS generation's source has no video stream", "generation", gen)
+			p.finish(ErrFailed)
+			return
+		}
+		p.logProbe(gen, probe)
+
+		result := p.generation(ctx, gen, start, probe)
+		switch result.outcome {
+		case outcomeStopped:
+			p.finish(nil)
+			return
+		case outcomeFailed:
+			p.log.Error("the HLS output failed: every attempt at a generation exited before its first segment",
+				"generation", gen, "stderr", strings.Join(result.tail, " | "))
+			p.finish(ErrFailed)
+			return
+		case outcomeBoundary:
+			p.log.Info("source boundary: the HLS generation ended and the next starts there", "generation", gen, "boundary", result.boundary)
+			start = result.boundary - 1
+		case outcomeDied:
+			now := p.now()
+			kept := deaths[:0]
+			for _, at := range deaths {
+				if now.Sub(at) < deathWindow {
+					kept = append(kept, at)
+				}
+			}
+			deaths = append(kept, now)
+			if len(deaths) >= maxDeaths {
+				p.log.Error("the HLS output failed: its generations keep dying",
+					"generation", gen, "deaths", len(deaths), "within", deathWindow, "stderr", strings.Join(result.tail, " | "))
+				p.finish(ErrFailed)
+				return
+			}
+			p.log.Warn("an HLS generation died after its first segment; restarting at the ring's head, as at a source boundary", "generation", gen)
+			start = ring.Head()
+		}
+	}
+}
+
+// logProbe logs the probe's audio decisions, including a choice between
+// several qualifying streams (spec § Encoder argv).
+func (p *Pipeline) logProbe(gen int, probe Probe) {
+	var streams []string
+	for _, a := range probe.Audio {
+		streams = append(streams, fmt.Sprintf("%s %s %dch %dHz qualifies=%t", a.ID, a.Codec, a.Channels, a.SampleRate, a.Qualifies()))
+	}
+	video := "none"
+	if probe.Video != nil {
+		video = fmt.Sprintf("%s %dx%d %s %s", probe.Video.Codec, probe.Video.Width, probe.Video.Height, probe.Video.FrameRate, probe.Video.Field)
+	}
+	p.log.Info("HLS generation probed", "generation", gen, "video", video, "audio", strings.Join(streams, "; "))
+	if q := probe.Qualifying(); len(q) > 1 {
+		p.log.Info("more than one qualifying audio stream; the first fills aac, and ac3/eac3 prefer their own codec", "generation", gen, "chosen", q[0].ID)
+	}
+}
+
+// probe runs D9's probe over the bytes the generation will start from.
+func (p *Pipeline) probe(ctx context.Context, gen int, start uint64) (Probe, error) {
+	command, argv := p.cfg.FFprobe, ProbeArgv()
+	if command == "" {
+		command = "ffprobe"
+	}
+	if p.cfg.ProbeCommand != nil {
+		command, argv = p.cfg.ProbeCommand(gen)
+	}
+	pctx, cancel := context.WithTimeout(ctx, ProbeWall+ffmpeg.KillWait+time.Second)
+	defer cancel()
+	proc, err := ffmpeg.StartPiped(pctx, command, argv)
+	if err != nil {
+		return Probe{}, fmt.Errorf("hls: starting the probe: %w", redact.Error(err))
+	}
+	stderrDone := make(chan struct{})
+	go func() {
+		defer close(stderrDone)
+		proc.ReadStderr(func(line string) {
+			p.log.Debug("HLS probe stderr", "line", redact.Line(line))
+		})
+	}()
+	feedCtx, stopFeed := context.WithTimeout(pctx, ProbeWall)
+	fed := make(chan struct{})
+	go func() {
+		defer close(fed)
+		defer proc.CloseStdin()
+		feed(feedCtx, p.cfg.Source, start, proc.Stdin(), ProbeBytes, nil)
+	}()
+	out, readErr := io.ReadAll(io.LimitReader(proc.Stdout(), 4<<20))
+	stopFeed()
+	<-fed
+	<-stderrDone
+	waitErr := proc.Wait()
+	if ctx.Err() != nil {
+		return Probe{}, ctx.Err()
+	}
+	if waitErr != nil || readErr != nil {
+		return Probe{}, fmt.Errorf("hls: the probe failed: %w", redact.Error(errors.Join(waitErr, readErr)))
+	}
+	return ParseProbe(out)
+}
+
+type outcome int
+
+const (
+	outcomeStopped outcome = iota
+	outcomeBoundary
+	outcomeEarly
+	outcomeDied
+	outcomeFailed
+)
+
+type genResult struct {
+	outcome  outcome
+	boundary uint64
+	tail     []string
+}
+
+// generation runs one generation with D11's failure policy. An attempt that
+// exits before its first segment is retried once on the same engine; if
+// that was Quick Sync and it fails again, the same input is tried in
+// software, and Quick Sync is written off for the process only when that
+// software attempt succeeds AND a re-run of the detection encode fails.
+// Anything else that fails every attempt fails this channel's HLS output
+// alone.
+func (p *Pipeline) generation(ctx context.Context, gen int, start uint64, probe Probe) genResult {
+	engine := p.det.Engine(ctx)
+	r := p.attempt(ctx, gen, 1, start, probe, engine, nil)
+	if r.outcome != outcomeEarly {
+		return r
+	}
+	p.log.Warn("an HLS generation exited before its first segment; retrying", "generation", gen, "engine", engine)
+	r = p.attempt(ctx, gen, 2, start, probe, engine, nil)
+	if r.outcome != outcomeEarly {
+		return r
+	}
+	if engine == EngineQSV {
+		p.log.Warn("an HLS generation failed twice on Quick Sync; trying the same input in software", "generation", gen)
+		r = p.attempt(ctx, gen, 3, start, probe, EngineSoftware, func() {
+			// Software got a segment out of the input Quick Sync could
+			// not. Whether that was the device is the detection encode's
+			// to say, on its own goroutine so the segmenter never waits
+			// for it; run waits for it before the pipeline is Done.
+			p.background.Add(1)
+			go func() {
+				defer p.background.Done()
+				if !p.det.Recheck(ctx) {
+					p.det.MarkUnusable()
+				}
+			}()
+		})
+		if r.outcome != outcomeEarly {
+			return r
+		}
+	}
+	r.outcome = outcomeFailed
+	return r
+}
+
+// attempt is one encoder process: its spawn, its input writer, its stderr,
+// its output readers and its segmenter, joined before it returns.
+func (p *Pipeline) attempt(ctx context.Context, gen, n int, start uint64, probe Probe, engine Engine, onFirst func()) genResult {
+	p.mu.Lock()
+	out := *p.output
+	p.engine = engine
+	p.mu.Unlock()
+	plan := PlanGeneration(out, probe, engine)
+
+	silence := map[string]*silenceClock{}
+	var encoded []string
+	for _, r := range out.Audio {
+		switch plan.Fills[r.Name].Kind {
+		case FillSilence:
+			canned, err := p.sil.Get(ctx, r)
+			if err != nil {
+				p.log.Error("the canned silence for an HLS rendition could not be made", "rendition", r.Name, "error", redact.Error(err))
+				return genResult{outcome: outcomeEarly}
+			}
+			silence[r.Name] = &silenceClock{canned: canned}
+			p.noteInit(r.Name, gen, canned.Init, canned.Track.Codec)
+		default:
+			encoded = append(encoded, r.Name)
+		}
+		p.log.Info("HLS rendition", "generation", gen, "attempt", n, "rendition", r.Name, "fill", plan.Fills[r.Name].Kind, "source", plan.Fills[r.Name].Source.ID)
+	}
+
+	spawn := Spawn{Generation: gen, Attempt: n, Engine: engine, Argv: out.Argv(plan, p.device()), Extra: out.Extra(plan)}
+	command, argv := p.cfg.FFmpeg, spawn.Argv
+	if command == "" {
+		command = "ffmpeg"
+	}
+	if p.cfg.Command != nil {
+		command, argv = p.cfg.Command(spawn)
+	}
+	actx, acancel := context.WithCancel(ctx)
+	defer acancel()
+	proc, err := ffmpeg.StartPipedExtra(actx, command, argv, spawn.Extra)
+	if err != nil {
+		p.log.Error("the HLS encoder could not start", "generation", gen, "error", redact.Error(err))
+		return genResult{outcome: outcomeEarly}
+	}
+
+	seg := newSegmenter(p.store, gen, encoded, silence, p.now, p.cfg.AudioWait, onFirst)
+	var tailMu sync.Mutex
+	var tail []string
+	stderrDone := make(chan struct{})
+	go func() {
+		defer close(stderrDone)
+		proc.ReadStderr(func(line string) {
+			line = redact.Line(line)
+			p.log.Warn("HLS encoder stderr", "generation", gen, "line", line)
+			tailMu.Lock()
+			tail = append(tail, line)
+			if len(tail) > stderrTail {
+				tail = tail[len(tail)-stderrTail:]
+			}
+			tailMu.Unlock()
+		})
+	}()
+
+	readersDone := make(chan struct{})
+	var readers sync.WaitGroup
+	read := func(name string, r io.Reader) {
+		readers.Add(1)
+		go func() {
+			defer readers.Done()
+			defer seg.finish(name)
+			var info Track
+			sp := splitter{
+				onInit: func(b []byte) error {
+					t, err := ParseInit(b)
+					if err != nil {
+						return err
+					}
+					stripped, err := StripEdits(b)
+					if err != nil {
+						return err
+					}
+					info = t
+					seg.init(name, t)
+					p.noteInit(name, gen, stripped, t.Codec)
+					return nil
+				},
+				onFrag: func(b []byte) error {
+					f, err := ParseFragment(b, info)
+					if err != nil {
+						return err
+					}
+					if err := shiftStart(&f, info.StartOffset); err != nil {
+						return err
+					}
+					seg.fragment(name, f)
+					return nil
+				},
+			}
+			if err := sp.read(r); err != nil {
+				p.log.Error("an HLS encoder output is not fragmented MP4; ending the generation", "generation", gen, "rendition", name, "error", redact.Error(err))
+				proc.Kill()
+				_, _ = io.Copy(io.Discard, r)
+			}
+		}()
+	}
+	read(RenditionVideo, proc.Stdout())
+	for i, name := range audioOrder {
+		if r := proc.Extra(i); r != nil {
+			read(name, r)
+		}
+	}
+	go func() {
+		readers.Wait()
+		close(readersDone)
+	}()
+	segDone := make(chan struct{})
+	go func() {
+		defer close(segDone)
+		seg.run()
+	}()
+
+	var fed feedResult
+	var inputClosed time.Time
+	fedDone := make(chan struct{})
+	ring := p.cfg.Source.Ring()
+	go func() {
+		defer close(fedDone)
+		fed = feed(actx, p.cfg.Source, start, proc.Stdin(), 0, func(index uint64) {
+			seg.setAnchor(arrival(ring, index, p.now))
+		})
+		proc.CloseStdin()
+		if fed.end == feedBoundary || fed.end == feedClosed {
+			inputClosed = time.Now()
+			// D10: the generation exits on its own at stdin EOF (M8: 0.065 s);
+			// one still running after the grace is killed.
+			select {
+			case <-readersDone:
+			case <-time.After(p.exitGrace()):
+				p.log.Warn("an HLS generation was still running after its input closed; killing it", "generation", gen, "grace", p.exitGrace())
+				proc.Kill()
+			}
+		}
+	}()
+
+	<-readersDone
+	acancel()
+	_ = proc.Wait()
+	exited := time.Now()
+	<-fedDone
+	<-stderrDone
+	<-segDone
+	if !inputClosed.IsZero() {
+		// D10 and M8: a generation exits on its own once its input closes.
+		// Logged for Q6, the failover gap, whose first term this is.
+		p.log.Info("HLS generation ended after its input closed", "generation", gen, "attempt", n,
+			"after_input_closed", exited.Sub(inputClosed), "segments", seg.Published())
+	}
+
+	tailMu.Lock()
+	result := genResult{tail: tail}
+	tailMu.Unlock()
+	switch {
+	case ctx.Err() != nil:
+		result.outcome = outcomeStopped
+	case fed.end == feedBoundary:
+		result.outcome, result.boundary = outcomeBoundary, fed.boundary
+	case fed.end == feedClosed:
+		result.outcome = outcomeStopped
+	case seg.Published() == 0:
+		result.outcome = outcomeEarly
+	default:
+		result.outcome = outcomeDied
+	}
+	return result
+}
+
+func (p *Pipeline) device() string {
+	if p.cfg.Device != "" {
+		return p.cfg.Device
+	}
+	return DefaultDevice
+}
+
+func (p *Pipeline) exitGrace() time.Duration {
+	if p.cfg.ExitGrace > 0 {
+		return p.cfg.ExitGrace
+	}
+	return GenerationExitGrace
+}
diff --git a/relay/hls/pipeline_test.go b/relay/hls/pipeline_test.go
new file mode 100644
index 00000000..28d3c570
--- /dev/null
+++ b/relay/hls/pipeline_test.go
@@ -0,0 +1,615 @@
+package hls
+
+import (
+	"bytes"
+	"context"
+	"errors"
+	"log/slog"
+	"os"
+	"path/filepath"
+	"regexp"
+	"strings"
+	"sync"
+	"testing"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
+)
+
+// TestStandIn is the trampoline relaytest's stand-in runs through: this
+// test binary, re-executed with RELAY_STANDIN=1, is the "ffmpeg" and the
+// "ffprobe" the pipeline tests spawn (relaytest/standin.go). Every spawn is
+// real; the stand-in is used where the subject is the relay's reaction to a
+// process -- its bytes, its exit and its moment -- and real ffmpeg where the
+// subject is what an encoder makes (real_test.go).
+func TestStandIn(_ *testing.T) {
+	if os.Getenv(relaytest.StandInEnv) != "1" {
+		return
+	}
+	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
+}
+
+// logBuffer is a logger a test can read back.
+type logBuffer struct {
+	mu sync.Mutex
+	b  bytes.Buffer
+}
+
+func (l *logBuffer) Write(p []byte) (int, error) {
+	l.mu.Lock()
+	defer l.mu.Unlock()
+	return l.b.Write(p)
+}
+
+func (l *logBuffer) String() string {
+	l.mu.Lock()
+	defer l.mu.Unlock()
+	return l.b.String()
+}
+
+func (l *logBuffer) logger() *slog.Logger {
+	return slog.New(slog.NewTextHandler(l, &slog.HandlerOptions{Level: slog.LevelDebug}))
+}
+
+// file writes data to a file in the test's temporary directory.
+func file(t *testing.T, name string, data []byte) string {
+	t.Helper()
+	path := filepath.Join(t.TempDir(), name)
+	if err := os.WriteFile(path, data, 0o600); err != nil {
+		t.Fatal(err)
+	}
+	return path
+}
+
+const (
+	probeVideoOnly = `{"streams":[{"codec_type":"video","codec_name":"h264","width":640,"height":360,"field_order":"progressive","r_frame_rate":"25/1","id":"0x100"}]}`
+	probeWithAAC   = `{"streams":[{"codec_type":"video","codec_name":"h264","width":640,"height":360,"field_order":"progressive","r_frame_rate":"25/1","id":"0x100"},` +
+		`{"codec_type":"audio","codec_name":"aac","channels":2,"sample_rate":"48000","id":"0x101"}]}`
+	probeAudioOnly = `{"streams":[{"codec_type":"audio","codec_name":"aac","channels":2,"sample_rate":"48000","id":"0x101"}]}`
+)
+
+// standInHarness is one pipeline under test with stand-in processes.
+type standInHarness struct {
+	t        *testing.T
+	src      *testSource
+	logs     *logBuffer
+	spawnLog string
+	mu       sync.Mutex
+	spawns   []Spawn
+}
+
+// cannedAAC is a synthetic canned silent AAC frame, so the stand-in tests
+// never need a real ffmpeg for silence.
+func cannedAAC(t *testing.T) *Canned {
+	t.Helper()
+	init, err := StripEdits(audioInit())
+	if err != nil {
+		t.Fatal(err)
+	}
+	track, _ := ParseInit(init)
+	return &Canned{Init: init, Track: track, Frame: []byte{0x21, 0x10, 0x04, 0x60, 0x8c, 0x1c}, SamplesPerFrame: 1024}
+}
+
+// start runs a pipeline over h.src with the probe answering probeJSON and
+// each encoder spawn given the stand-in arguments encoder returns.
+func (h *standInHarness) start(probeJSON string, det *Detector, encoder func(Spawn) []string) *Pipeline {
+	h.t.Helper()
+	return h.startWith(probeJSON, func(c *Config) {
+		if det != nil {
+			c.Detector = det
+		}
+	}, encoder)
+}
+
+// startWith is start with a last word on the Config.
+func (h *standInHarness) startWith(probeJSON string, configure func(*Config), encoder func(Spawn) []string) *Pipeline {
+	h.t.Helper()
+	h.t.Setenv(relaytest.StandInEnv, "1")
+	probe := file(h.t, "probe.json", []byte(probeJSON))
+	cfg := Config{
+		ChannelID:  "test",
+		Source:     h.src,
+		JoinBehind: time.Hour,
+		Detector:   &Detector{Device: filepath.Join(h.t.TempDir(), "renderD128"), Log: h.logs.logger()},
+		Silence:    &SilenceCache{entries: map[cannedKey]*Canned{{RenditionAAC, 2}: cannedAAC(h.t)}},
+		ExitGrace:  300 * time.Millisecond,
+		Log:        h.logs.logger(),
+		ProbeCommand: func(int) (string, []string) {
+			return relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(1, probe))
+		},
+		Command: func(s Spawn) (string, []string) {
+			h.mu.Lock()
+			h.spawns = append(h.spawns, s)
+			h.mu.Unlock()
+			return relaytest.StandInCommand(append([]string{"--spawn-log", h.spawnLog}, encoder(s)...)...)
+		},
+	}
+	configure(&cfg)
+	p, err := Start(context.Background(), cfg)
+	if err != nil {
+		h.t.Fatalf("Start: %v", err)
+	}
+	h.t.Cleanup(p.Stop)
+	return p
+}
+
+func newHarness(t *testing.T) *standInHarness {
+	src := newTestSource()
+	src.write(t, chunkOf('a'))
+	return &standInHarness{t: t, src: src, logs: &logBuffer{}, spawnLog: filepath.Join(t.TempDir(), "spawns")}
+}
+
+// waitDone waits for the pipeline to end.
+func waitDone(t *testing.T, p *Pipeline, within time.Duration) {
+	t.Helper()
+	select {
+	case <-p.Done():
+	case <-time.After(within):
+		t.Fatalf("the pipeline did not end within %v", within)
+	}
+}
+
+func (h *standInHarness) engines() []Engine {
+	h.mu.Lock()
+	defer h.mu.Unlock()
+	var out []Engine
+	for _, s := range h.spawns {
+		out = append(out, s.Engine)
+	}
+	return out
+}
+
+// D11: a generation that exits before its first segment is retried once on
+// the same engine; in software a second early exit fails the channel's HLS
+// output (ErrFailed), logged at ERROR with the last stderr lines.
+func TestAGenerationThatDiesBeforeItsFirstSegmentIsRetriedOnceThenFails(t *testing.T) {
+	h := newHarness(t)
+	initOnly := file(t, "v.mp4", videoInit(0))
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--echo-argv", "--fd-file", relaytest.FDFileArg(1, initOnly), "--exit-code", "1"}
+	})
+	waitDone(t, p, 10*time.Second)
+	if !errors.Is(p.Err(), ErrFailed) {
+		t.Fatalf("Err = %v, want ErrFailed", p.Err())
+	}
+	if n := relaytest.SpawnCount(h.spawnLog); n != 2 {
+		t.Fatalf("spawned %d encoders, want the attempt and one retry", n)
+	}
+	if got := h.engines(); len(got) != 2 || got[0] != EngineSoftware || got[1] != EngineSoftware {
+		t.Fatalf("engines %v, want software twice", got)
+	}
+	logs := h.logs.String()
+	if !strings.Contains(logs, "level=ERROR") || !strings.Contains(logs, "every attempt at a generation exited before its first segment") || !strings.Contains(logs, "stand-in argv:") {
+		t.Fatalf("the failure was not logged at ERROR with the encoder's last stderr lines:\n%s", logs)
+	}
+}
+
+// D11 and finding 5: on Quick Sync, two early exits are followed by the same
+// input in software; when that fails too the SOURCE was at fault, the
+// channel's HLS output fails, and Quick Sync is NOT written off for the
+// process.
+func TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff(t *testing.T) {
+	h := newHarness(t)
+	det := &Detector{Command: lookPath(t, "true"), Device: device(t)}
+	p := h.start(probeVideoOnly, det, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, file(t, "v.mp4", nil)), "--exit-code", "1"}
+	})
+	waitDone(t, p, 10*time.Second)
+	if !errors.Is(p.Err(), ErrFailed) {
+		t.Fatalf("Err = %v, want ErrFailed", p.Err())
+	}
+	if got := h.engines(); len(got) != 3 || got[0] != EngineQSV || got[1] != EngineQSV || got[2] != EngineSoftware {
+		t.Fatalf("engines %v, want qsv, qsv, then software on the same input", got)
+	}
+	if got := det.Engine(context.Background()); got != EngineQSV {
+		t.Fatalf("a source-caused early failure wrote Quick Sync off: the detector now answers %s", got)
+	}
+}
+
+// D11: Quick Sync is written off for the process only when the software
+// retry SUCCEEDS and a re-run of the detection encode FAILS; with the
+// detection still passing it stays usable.
+func TestQuickSyncIsWrittenOffOnlyWhenSoftwareSucceedsAndRedetectionFails(t *testing.T) {
+	for _, redetectFails := range []bool{true, false} {
+		h := newHarness(t)
+		marker := file(t, "qsv-works", nil)
+		script := file(t, "detect.sh", []byte("#!/bin/sh\n[ -f \""+marker+"\" ]\n"))
+		if err := os.Chmod(script, 0o700); err != nil { // #nosec G302 -- a test's own script must be executable
+			t.Fatal(err)
+		}
+		det := &Detector{Command: script, Device: device(t)}
+		stream := file(t, "v.mp4", videoStream(0, 3, 50))
+		p := h.start(probeVideoOnly, det, func(s Spawn) []string {
+			if s.Engine == EngineQSV {
+				return []string{"--fd-file", relaytest.FDFileArg(1, file(t, "none", nil)), "--exit-code", "1"}
+			}
+			if redetectFails {
+				_ = os.Remove(marker)
+			}
+			return []string{"--fd-file", relaytest.FDFileArg(1, stream), "--wait-stdin-eof"}
+		})
+		if err := p.Ready(context.Background()); err != nil {
+			t.Fatalf("redetectFails=%t: Ready: %v", redetectFails, err)
+		}
+		h.src.ring.Close()
+		waitDone(t, p, 10*time.Second)
+		if p.Err() != nil {
+			t.Fatalf("redetectFails=%t: the software attempt succeeded but Err = %v", redetectFails, p.Err())
+		}
+		want := EngineQSV
+		if redetectFails {
+			want = EngineSoftware
+		}
+		if got := det.Engine(context.Background()); got != want {
+			t.Fatalf("redetectFails=%t: the detector answers %s, want %s", redetectFails, got, want)
+		}
+		if p.Engine() != EngineSoftware {
+			t.Fatalf("the generation that succeeded ran on %s\n%s", p.Engine(), h.logs.String())
+		}
+	}
+}
+
+// D10: a generation still running after its input closed is killed after
+// the exit grace, and the pipeline still ends.
+func TestAGenerationThatIgnoresItsInputClosingIsKilledAfterTheGrace(t *testing.T) {
+	h := newHarness(t)
+	stream := file(t, "v.mp4", videoStream(0, 2, 50))
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, stream), "--ignore-stdin-eof"}
+	})
+	if err := p.Ready(context.Background()); err != nil {
+		t.Fatalf("Ready: %v", err)
+	}
+	h.src.ring.Close()
+	waitDone(t, p, 5*time.Second)
+	logs := h.logs.String()
+	if !strings.Contains(logs, "still running after its input closed; killing it") {
+		t.Fatalf("the generation was not killed after the grace:\n%s", logs)
+	}
+	if after := exitAfterInputClosed(t, logs); after < 300*time.Millisecond {
+		t.Fatalf("the generation ended %v after its input closed, before the 300ms grace", after)
+	}
+}
+
+var afterInputClosed = regexp.MustCompile(`after_input_closed=(\S+)`)
+
+// exitAfterInputClosed reads the latest "HLS generation ended after its
+// input closed" line's duration.
+func exitAfterInputClosed(t *testing.T, logs string) time.Duration {
+	t.Helper()
+	m := afterInputClosed.FindAllStringSubmatch(logs, -1)
+	if len(m) == 0 {
+		t.Fatalf("no generation ended after its input closed:\n%s", logs)
+	}
+	d, err := time.ParseDuration(m[len(m)-1][1])
+	if err != nil {
+		t.Fatalf("unparsable duration %q", m[len(m)-1][1])
+	}
+	return d
+}
+
+// A process that dies mid-fragment: every whole fragment is segmented and
+// the partial one is not.
+func TestEOFMidFragmentSegmentsOnlyTheWholeFragments(t *testing.T) {
+	h := newHarness(t)
+	whole := videoStream(0, 6, 50) // six 2 s fragments
+	truncated := file(t, "v.mp4", whole[:len(whole)-5])
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, truncated), "--wait-stdin-eof"}
+	})
+	if err := p.Ready(context.Background()); err != nil {
+		t.Fatalf("Ready: %v", err)
+	}
+	h.src.ring.Close()
+	waitDone(t, p, 5*time.Second)
+	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
+	if got := strings.Count(string(playlist), "#EXTINF:2.000,"); got != 5 {
+		t.Fatalf("%d 2 s segments from five whole fragments and a partial sixth:\n%s", got, playlist)
+	}
+	if _, ok := p.Store().Segment(RenditionVideo, 5); ok {
+		t.Fatalf("the partial fragment became a segment")
+	}
+}
+
+// Spec § Encoder argv, failure: a generation that dies after its first
+// segment is restarted at the ring's head as at a source boundary, with a
+// discontinuity; a third such death within 60 s is a total failure.
+func TestDeathsAfterTheFirstSegmentRestartUntilTheThirdWithinAMinute(t *testing.T) {
+	h := newHarness(t)
+	stream := file(t, "v.mp4", videoStream(0, 2, 50))
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, stream)}
+	})
+	waitDone(t, p, 10*time.Second)
+	if !errors.Is(p.Err(), ErrFailed) {
+		t.Fatalf("Err = %v, want ErrFailed after three deaths", p.Err())
+	}
+	if n := relaytest.SpawnCount(h.spawnLog); n != 3 {
+		t.Fatalf("spawned %d encoders, want three generations", n)
+	}
+	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
+	for _, want := range []string{`video/init-0.mp4`, `video/init-1.mp4`, `video/init-2.mp4`} {
+		if !strings.Contains(string(playlist), want) {
+			t.Fatalf("no %s: each death starts a new generation\n%s", want, playlist)
+		}
+	}
+	if got := strings.Count(string(playlist), "#EXT-X-DISCONTINUITY\n"); got != 2 {
+		t.Fatalf("%d discontinuities, want one before each restarted generation\n%s", got, playlist)
+	}
+	if !strings.Contains(h.logs.String(), "its generations keep dying") {
+		t.Fatalf("the total failure was not logged")
+	}
+}
+
+// D9: a generation-0 probe with no video fails the HLS attach, and a probe
+// that fails fails the output.
+func TestAProbeWithNoVideoOrNoAnswerFails(t *testing.T) {
+	h := newHarness(t)
+	p := h.start(probeAudioOnly, nil, func(Spawn) []string { return nil })
+	if err := p.Ready(context.Background()); !errors.Is(err, ErrNoVideo) {
+		t.Fatalf("Ready = %v, want ErrNoVideo", err)
+	}
+	waitDone(t, p, 5*time.Second)
+	if !errors.Is(p.Err(), ErrNoVideo) || relaytest.SpawnCount(h.spawnLog) != 0 {
+		t.Fatalf("Err = %v with %d encoders spawned, want ErrNoVideo and none", p.Err(), relaytest.SpawnCount(h.spawnLog))
+	}
+	h = newHarness(t)
+	p = h.start("not json", nil, func(Spawn) []string { return nil })
+	waitDone(t, p, 5*time.Second)
+	if !errors.Is(p.Err(), ErrFailed) {
+		t.Fatalf("an unreadable probe: Err = %v, want ErrFailed", p.Err())
+	}
+}
+
+// An encoder output that is not fragmented MP4 ends the generation: the
+// process is killed rather than left writing into a pipe nobody reads.
+func TestAnOutputThatIsNotFragmentedMP4EndsTheGeneration(t *testing.T) {
+	h := newHarness(t)
+	garbage := file(t, "v.mp4", cat(box("ftyp", nil), fragSpec{seq: 1, trackID: 1, durations: []uint32{1}}.build()))
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, garbage), "--ignore-stdin-eof"}
+	})
+	waitDone(t, p, 10*time.Second)
+	if !errors.Is(p.Err(), ErrFailed) || !strings.Contains(h.logs.String(), "is not fragmented MP4") {
+		t.Fatalf("Err = %v; logs:\n%s", p.Err(), h.logs.String())
+	}
+}
+
+// The segmenter's alignment (D6, spec § Playlists): each track's tfdt is
+// moved by its empty edit onto one timeline, an audio segment holds the
+// fragments whose start falls in its video segment's span, and a relay-
+// synthesised silent rendition matches its video segment to within one frame.
+func TestSegmentsAreAlignedAcrossRenditions(t *testing.T) {
+	h := newHarness(t)
+	video := file(t, "v.mp4", videoStream(860, 4, 50)) // starts 0.86 s into the output
+	audio := file(t, "a.mp4", audioStream(40))         // 8 s of 200 ms fragments from 0
+	p := h.start(probeWithAAC, nil, func(s Spawn) []string {
+		if !strings.Contains(strings.Join(s.Argv, " "), "pipe:3") || len(s.Extra) != 3 || !s.Extra[0] {
+			t.Errorf("the AAC encode has no fd 3: %v", s.Extra)
+		}
+		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
+	})
+	if err := p.Ready(context.Background()); err != nil {
+		t.Fatalf("Ready: %v", err)
+	}
+	mv, err := p.Multivariant("/hls/T")
+	if err != nil || !strings.Contains(string(mv), `CODECS="avc1.64002a,mp4a.40.2"`) {
+		t.Fatalf("multivariant %s, %v", mv, err)
+	}
+	h.src.ring.Close()
+	waitDone(t, p, 5*time.Second)
+	vt, _ := ParseInit(videoInit(0))
+	at, _ := ParseInit(audioInit())
+	for seq := uint64(0); seq < 4; seq++ {
+		v, ok := p.Store().Segment(RenditionVideo, seq)
+		a, ok2 := p.Store().Segment(RenditionAAC, seq)
+		if !ok || !ok2 {
+			t.Fatalf("segment %d missing (video %t, aac %t)", seq, ok, ok2)
+		}
+		vf, _ := ParseFragment(v, vt)
+		af, _ := ParseFragment(a, at)
+		vstart := float64(vf.Start) / 12800
+		astart := float64(af.Start) / 48000
+		if vstart != 0.86+2*float64(seq) {
+			t.Errorf("segment %d's video starts at %.3f s, want its tfdt moved by the 0.86 s empty edit", seq, vstart)
+		}
+		if astart < vstart || astart-vstart >= 0.2 {
+			t.Errorf("segment %d's audio starts at %.3f s against video %.3f s, want within its span's first 200 ms", seq, astart, vstart)
+		}
+	}
+	init, _ := p.Store().Init(RenditionVideo, 0)
+	if bytes.Contains(init, []byte("edts")) {
+		t.Errorf("the served init still carries the edit list its offset was moved out of")
+	}
+}
+
+// M8: a generation with no qualifying audio writes video only, and the relay
+// writes the AAC rendition from its canned frame, each silent segment as long
+// as its video segment to within one audio frame.
+func TestASilentRenditionIsWrittenByTheRelay(t *testing.T) {
+	h := newHarness(t)
+	video := file(t, "v.mp4", videoStream(0, 5, 50))
+	p := h.start(probeVideoOnly, nil, func(s Spawn) []string {
+		if s.Extra != nil || strings.Contains(strings.Join(s.Argv, " "), "pipe:3") {
+			t.Errorf("a silent generation's argv has an audio output: %v", s.Argv)
+		}
+		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
+	})
+	if err := p.Ready(context.Background()); err != nil {
+		t.Fatalf("Ready: %v", err)
+	}
+	h.src.ring.Close()
+	waitDone(t, p, 5*time.Second)
+	canned := cannedAAC(t)
+	if init, _ := p.Store().Init(RenditionAAC, 0); !bytes.Equal(init, canned.Init) {
+		t.Fatalf("the silent rendition's init is not the canned one")
+	}
+	vt, _ := ParseInit(videoInit(0))
+	for seq := uint64(0); seq < 5; seq++ {
+		v, _ := p.Store().Segment(RenditionVideo, seq)
+		a, _ := p.Store().Segment(RenditionAAC, seq)
+		vf, _ := ParseFragment(v, vt)
+		af, err := ParseFragment(a, canned.Track)
+		if err != nil {
+			t.Fatalf("silent segment %d: %v", seq, err)
+		}
+		vEnd := float64(vf.End()) / 12800
+		aEnd := float64(af.End()) / 48000
+		if d := aEnd - vEnd; d < 0 || d >= 1024.0/48000 {
+			t.Errorf("silent segment %d ends %.4f s from its video, want within one frame", seq, d)
+		}
+	}
+}
+
+// Stop ends a running generation at once, killing it; the pipeline ends
+// without an error.
+func TestStopEndsTheGeneration(t *testing.T) {
+	h := newHarness(t)
+	stream := file(t, "v.mp4", videoStream(0, 2, 50))
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, stream), "--ignore-stdin-eof"}
+	})
+	if err := p.Ready(context.Background()); err != nil {
+		t.Fatalf("Ready: %v", err)
+	}
+	stopped := time.Now()
+	p.Stop()
+	if took := time.Since(stopped); took > 3*time.Second {
+		t.Fatalf("Stop took %v", took)
+	}
+	if p.Err() != nil {
+		t.Fatalf("a stopped pipeline's Err = %v", p.Err())
+	}
+	if p.Generation() != 0 || p.Engine() != EngineSoftware {
+		t.Errorf("generation %d on %s", p.Generation(), p.Engine())
+	}
+	if probe, ok := p.GenerationProbe(0); !ok || probe.Video == nil {
+		t.Errorf("generation 0's probe was not kept")
+	}
+	if o, ok := p.Output(); !ok || o.Width != 640 {
+		t.Errorf("Output = %+v, %t", o, ok)
+	}
+}
+
+func TestStartNeedsASourceAndMultivariantNeedsReady(t *testing.T) {
+	if _, err := Start(context.Background(), Config{}); err == nil {
+		t.Fatalf("Start accepted no source")
+	}
+	h := newHarness(t)
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, file(t, "none", nil)), "--ignore-stdin-eof"}
+	})
+	if _, err := p.Multivariant("/hls/T"); err == nil {
+		t.Fatalf("a multivariant was rendered before the inits existed")
+	}
+	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
+	defer cancel()
+	if err := p.Ready(ctx); !errors.Is(err, context.DeadlineExceeded) {
+		t.Fatalf("Ready with no init = %v, want the context's end", err)
+	}
+}
+
+// The generation's last segment -- its flushed tail -- with no audio on a
+// rendition is not published: an empty fragment there stalled AVPlayer's
+// E-AC-3 path on the iOS 27 Simulator (measured while planning 4a-1a).
+func TestATailWithNoAudioIsNotPublished(t *testing.T) {
+	h := newHarness(t)
+	video := file(t, "v.mp4", videoStream(0, 3, 50)) // 6 s of video
+	audio := file(t, "a.mp4", audioStream(20))       // 4 s of audio
+	p := h.start(probeWithAAC, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
+	})
+	if err := p.Ready(context.Background()); err != nil {
+		t.Fatalf("Ready: %v", err)
+	}
+	h.src.ring.Close()
+	waitDone(t, p, 5*time.Second)
+	if _, ok := p.Store().Segment(RenditionVideo, 1); !ok {
+		t.Fatalf("segment 1, which has audio, was not published")
+	}
+	if _, ok := p.Store().Segment(RenditionVideo, 2); ok {
+		t.Fatalf("the tail segment, with no audio on aac, was published")
+	}
+}
+
+// Mid-generation, a segment whose audio output wrote nothing for its span is
+// published after AudioWait with an empty fragment of the audio track at the
+// span's start, so the video never stalls behind a stopped audio output.
+func TestAStoppedAudioOutputDoesNotStallTheVideo(t *testing.T) {
+	h := newHarness(t)
+	video := file(t, "v.mp4", videoStream(0, 4, 50)) // 8 s of video
+	audio := file(t, "a.mp4", audioStream(10))       // 2 s of audio, then nothing
+	p := h.startWith(probeWithAAC, func(c *Config) { c.AudioWait = 200 * time.Millisecond }, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
+	})
+	if err := p.Store().WaitSegment(context.Background()); err != nil {
+		t.Fatalf("WaitSegment: %v", err)
+	}
+	deadline := time.Now().Add(5 * time.Second)
+	for {
+		if _, ok := p.Store().Segment(RenditionAAC, 2); ok {
+			break
+		}
+		if time.Now().After(deadline) {
+			playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
+			t.Fatalf("segment 2 was never published with the audio output stopped:\n%s", playlist)
+		}
+		time.Sleep(20 * time.Millisecond)
+	}
+	at, _ := ParseInit(audioInit())
+	data, _ := p.Store().Segment(RenditionAAC, 2)
+	f, err := ParseFragment(data, at)
+	if err != nil || f.Samples != 0 || f.Start != 4*48000 {
+		t.Fatalf("segment 2's aac part = %+v, %v; want an empty fragment at 4 s", f, err)
+	}
+	playlist, _, _ := p.Store().MediaPlaylist(RenditionAAC)
+	if !strings.Contains(string(playlist), "#EXTINF:2.000,\naac/2.m4s") {
+		t.Fatalf("the empty audio segment does not carry its video's duration:\n%s", playlist)
+	}
+}
+
+// D6: the segmenter accumulates video fragments until the 2 s grid is
+// reached, and cuts only before a sync sample. With one-second fragments
+// from a first sync fragment at 1 s the grid lines are at 3, 5 and 7 s: the
+// non-sync fragment at 0 s starts nothing; 1+2 make a segment; the fragment
+// on the 5 s line opens on a non-sync sample, so 3+4+5 make one; and the
+// next sync fragment, at 6 s, is where the grid picks up again.
+func TestSegmentsAccumulateToTheGridAndCutOnlyAtASyncSample(t *testing.T) {
+	h := newHarness(t)
+	second := make([]uint32, 25) // one second of 25 fps frames at 12800 Hz
+	for i := range second {
+		second[i] = 512
+	}
+	stream := videoInit(0)
+	var start uint64
+	for i, sync := range []bool{false, true, true, true, true, false, true, true} {
+		stream = append(stream, fragSpec{seq: uint32(i + 1), trackID: 1, start: start, durations: second, sync: sync}.build()...) // #nosec G115 -- a test's small count
+		start += 25 * 512
+	}
+	video := file(t, "v.mp4", stream)
+	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
+	})
+	if err := p.Ready(context.Background()); err != nil {
+		t.Fatalf("Ready: %v", err)
+	}
+	h.src.ring.Close()
+	waitDone(t, p, 5*time.Second)
+	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
+	var got []string
+	for _, line := range strings.Split(string(playlist), "\n") {
+		if strings.HasPrefix(line, "#EXTINF:") {
+			got = append(got, strings.TrimSuffix(strings.TrimPrefix(line, "#EXTINF:"), ","))
+		}
+	}
+	if strings.Join(got, " ") != "2.000 3.000 1.000 1.000" {
+		t.Fatalf("segment durations %v, want 2.000 3.000 1.000 1.000:\n%s", got, playlist)
+	}
+	vt, _ := ParseInit(videoInit(0))
+	for seq := uint64(0); seq < 4; seq++ {
+		data, _ := p.Store().Segment(RenditionVideo, seq)
+		if f, _ := ParseFragment(data, vt); !f.Sync {
+			t.Fatalf("segment %d opens on a non-sync sample", seq)
+		}
+	}
+}
diff --git a/relay/hls/playlist.go b/relay/hls/playlist.go
new file mode 100644
index 00000000..70005145
--- /dev/null
+++ b/relay/hls/playlist.go
@@ -0,0 +1,46 @@
+package hls
+
+import (
+	"fmt"
+	"strings"
+)
+
+// renditionNames is each audio group's NAME. The groups differ by GROUP-ID,
+// so two may share a NAME.
+var renditionNames = map[string]string{
+	RenditionAAC:  "Stereo",
+	RenditionAC3:  "Surround",
+	RenditionEAC3: "Surround",
+}
+
+// Multivariant renders the multivariant playlist (spec § Playlists): one
+// EXT-X-MEDIA audio group per declared audio rendition, AAC first, and one
+// EXT-X-STREAM-INF per group, each naming the one video media playlist.
+// base is the absolute path every URI hangs from -- "/hls/<token>" in 4a-1b
+// -- because the multivariant references media playlists by absolute path
+// (D3). codecs is each rendition's CODECS value, read from generation 0's
+// init segments (D7).
+//
+// BANDWIDTH is the video maxrate plus the group's audio bitrate, and
+// AVERAGE-BANDWIDTH the video bitrate plus it: transcode mode's rule. The
+// copied-rendition rule (1.25x the ring's measured rate) is automatic
+// mode's, and lands with it in 4a-1d.
+func Multivariant(o Output, codecs map[string]string, base string) []byte {
+	var b strings.Builder
+	b.WriteString("#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-INDEPENDENT-SEGMENTS\n")
+	for _, r := range o.Audio {
+		fmt.Fprintf(&b, "#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=%q,NAME=%q,", r.Name, renditionNames[r.Name])
+		if r.Language != "" {
+			fmt.Fprintf(&b, "LANGUAGE=%q,", r.Language)
+		}
+		fmt.Fprintf(&b, "DEFAULT=YES,AUTOSELECT=YES,CHANNELS=\"%d\",URI=\"%s/%s.m3u8\"\n", r.Channels, base, r.Name)
+	}
+	for _, r := range o.Audio {
+		rate := audioBitrate(r)
+		fmt.Fprintf(&b, "#EXT-X-STREAM-INF:BANDWIDTH=%d,AVERAGE-BANDWIDTH=%d,CODECS=\"%s,%s\",RESOLUTION=%dx%d,FRAME-RATE=%.3f,AUDIO=%q\n",
+			o.VideoMaxrate+rate, o.VideoBitrate+rate, codecs[RenditionVideo], codecs[r.Name],
+			o.Width, o.Height, o.FrameRate.Float(), r.Name)
+		fmt.Fprintf(&b, "%s/%s.m3u8\n", base, RenditionVideo)
+	}
+	return []byte(b.String())
+}
diff --git a/relay/hls/probe.go b/relay/hls/probe.go
new file mode 100644
index 00000000..62437776
--- /dev/null
+++ b/relay/hls/probe.go
@@ -0,0 +1,213 @@
+package hls
+
+import (
+	"encoding/json"
+	"fmt"
+	"strconv"
+	"strings"
+	"time"
+)
+
+// The probe (Phase 4 spec, D9): `ffprobe -show_streams -of json` over the
+// bytes a generation will start from, bounded to 5 MB or 8 s, decoded with
+// encoding/json. It decides interlacing, frame rate, geometry and which audio
+// streams qualify.
+
+// ProbeBytes and ProbeWall are D9's bound: the probe is fed at most this
+// many bytes of the ring, for at most this long.
+const (
+	ProbeBytes = 5_000_000
+	ProbeWall  = 8 * time.Second
+)
+
+// ProbeArgv is the ffprobe argv. -probesize and -analyzeduration are the
+// same 5 MB and 8 s as the feed's own bound, so ffprobe never waits for
+// bytes the relay has stopped sending.
+func ProbeArgv() []string {
+	return []string{
+		"-hide_banner", "-loglevel", "error",
+		"-probesize", strconv.Itoa(ProbeBytes),
+		"-analyzeduration", "8000000",
+		"-f", "mpegts", "-i", "pipe:0",
+		"-show_streams", "-of", "json",
+	}
+}
+
+// FieldOrder is ffprobe's field_order, kept as THREE states (ruling R28,
+// issue #525): progressive, interlaced (tt, bb, tb or bt), and unknown.
+// Unknown is what ffprobe reports for a progressive HEVC stream in a
+// transport stream, because HEVC signals field coding in SEI rather than in
+// the parameters ffprobe reads. It is never folded into interlaced: it is
+// treated as progressive for deinterlacing here and for copy eligibility in
+// 4a-1d, but it stays distinct so 4a-1d's rule, and a log line, can say
+// which it was.
+type FieldOrder int
+
+// The three field orders.
+const (
+	// FieldUnknown is ffprobe's "unknown" or an absent field_order.
+	FieldUnknown FieldOrder = iota
+	// FieldProgressive is "progressive".
+	FieldProgressive
+	// FieldInterlaced is tt, bb, tb or bt.
+	FieldInterlaced
+)
+
+func (f FieldOrder) String() string {
+	switch f {
+	case FieldProgressive:
+		return "progressive"
+	case FieldInterlaced:
+		return "interlaced"
+	}
+	return "unknown"
+}
+
+// parseFieldOrder maps ffprobe's value. Only an explicit tt, bb, tb or bt is
+// interlaced (R28).
+func parseFieldOrder(value string) FieldOrder {
+	switch value {
+	case "progressive":
+		return FieldProgressive
+	case "tt", "bb", "tb", "bt":
+		return FieldInterlaced
+	}
+	return FieldUnknown
+}
+
+// Rational is a frame rate as ffprobe reports it, "25/1" or "30000/1001".
+type Rational struct{ Num, Den int }
+
+// parseRational reads "a/b"; ok is false for "0/0" and anything unparsable.
+func parseRational(value string) (Rational, bool) {
+	a, b, found := strings.Cut(value, "/")
+	if !found {
+		return Rational{}, false
+	}
+	num, err1 := strconv.Atoi(a)
+	den, err2 := strconv.Atoi(b)
+	if err1 != nil || err2 != nil || num <= 0 || den <= 0 {
+		return Rational{}, false
+	}
+	return Rational{Num: num, Den: den}, true
+}
+
+// Float is the rate as a decimal.
+func (r Rational) Float() float64 {
+	if r.Den == 0 {
+		return 0
+	}
+	return float64(r.Num) / float64(r.Den)
+}
+
+// String is "num/den", which ffmpeg's fps filter takes as it is.
+func (r Rational) String() string { return fmt.Sprintf("%d/%d", r.Num, r.Den) }
+
+// Video is the first video stream the probe found.
+type Video struct {
+	ID        string
+	Codec     string
+	Profile   string
+	PixFmt    string
+	Width     int
+	Height    int
+	FrameRate Rational
+	Field     FieldOrder
+}
+
+// Audio is one audio stream the probe found, qualifying or not.
+type Audio struct {
+	// ID is the stream id ffprobe reports, the PID for a transport stream
+	// ("0x301"). The argv maps a stream by it (`-map 0:i:0x301`), so a
+	// stream's index can never be confused with another's.
+	ID         string
+	Codec      string
+	Channels   int
+	SampleRate int
+	Language   string
+}
+
+// Qualifies is spec § Encoder argv's rule: a known codec_name, channels > 0
+// and sample_rate > 0. A transport stream's PMT can declare an audio PID that
+// carries no packets; ffprobe then reports it with 0 channels and a sample
+// rate of 0 (measured, ffmpeg 9.0.1), and mapping it makes ffmpeg fail every
+// output of the generation (finding 7).
+func (a Audio) Qualifies() bool {
+	switch a.Codec {
+	case "", "unknown", "none":
+		return false
+	}
+	return a.Channels > 0 && a.SampleRate > 0
+}
+
+// Probe is what one probe found.
+type Probe struct {
+	// Video is nil when the source has no video stream, which fails the HLS
+	// attach (D9).
+	Video *Video
+	// Audio is every audio stream, in the order ffprobe listed them.
+	Audio []Audio
+}
+
+// Qualifying is the audio streams that qualify, in order.
+func (p Probe) Qualifying() []Audio {
+	var out []Audio
+	for _, a := range p.Audio {
+		if a.Qualifies() {
+			out = append(out, a)
+		}
+	}
+	return out
+}
+
+// probeJSON is the part of ffprobe's -show_streams JSON this package reads.
+type probeJSON struct {
+	Streams []struct {
+		ID           string            `json:"id"`
+		CodecType    string            `json:"codec_type"`
+		CodecName    string            `json:"codec_name"`
+		Profile      string            `json:"profile"`
+		PixFmt       string            `json:"pix_fmt"`
+		FieldOrder   string            `json:"field_order"`
+		Width        int               `json:"width"`
+		Height       int               `json:"height"`
+		RFrameRate   string            `json:"r_frame_rate"`
+		AvgFrameRate string            `json:"avg_frame_rate"`
+		SampleRate   string            `json:"sample_rate"`
+		Channels     int               `json:"channels"`
+		Tags         map[string]string `json:"tags"`
+	} `json:"streams"`
+}
+
+// ParseProbe decodes ffprobe's JSON.
+func ParseProbe(raw []byte) (Probe, error) {
+	var doc probeJSON
+	if err := json.Unmarshal(raw, &doc); err != nil {
+		return Probe{}, fmt.Errorf("hls: the probe's JSON: %w", err) // credential-logging: ok - a JSON syntax error over ffprobe's stream list, which carries no URL
+	}
+	var p Probe
+	for _, s := range doc.Streams {
+		switch s.CodecType {
+		case "video":
+			if p.Video != nil {
+				continue
+			}
+			rate, ok := parseRational(s.RFrameRate)
+			if !ok {
+				rate, _ = parseRational(s.AvgFrameRate)
+			}
+			p.Video = &Video{
+				ID: s.ID, Codec: s.CodecName, Profile: s.Profile, PixFmt: s.PixFmt,
+				Width: s.Width, Height: s.Height, FrameRate: rate,
+				Field: parseFieldOrder(s.FieldOrder),
+			}
+		case "audio":
+			rate, _ := strconv.Atoi(s.SampleRate)
+			p.Audio = append(p.Audio, Audio{
+				ID: s.ID, Codec: s.CodecName, Channels: s.Channels, SampleRate: rate,
+				Language: s.Tags["language"],
+			})
+		}
+	}
+	return p, nil
+}
diff --git a/relay/hls/probe_test.go b/relay/hls/probe_test.go
new file mode 100644
index 00000000..40902953
--- /dev/null
+++ b/relay/hls/probe_test.go
@@ -0,0 +1,109 @@
+package hls
+
+import (
+	"strings"
+	"testing"
+)
+
+// probeJSONFor is ffprobe's -show_streams JSON, trimmed to the fields ParseProbe
+// reads, in the shape ffmpeg 9.0.1 printed it for the 4a-0 fixtures and for a
+// transport stream whose PMT declares an AC-3 PID that carries no packets.
+const probeJSONFor1080iWithAnEmptyAC3 = `{"streams": [
+ {"index": 0, "codec_name": "h264", "profile": "High", "codec_type": "video", "width": 1920, "height": 1080,
+  "pix_fmt": "yuv420p", "field_order": "tt", "r_frame_rate": "25/1", "avg_frame_rate": "25/1", "id": "0x300"},
+ {"index": 1, "codec_name": "aac", "profile": "LC", "codec_type": "audio", "sample_rate": "48000", "channels": 2,
+  "r_frame_rate": "0/0", "id": "0x301", "tags": {"language": "eng"}},
+ {"index": 2, "codec_name": "ac3", "codec_type": "audio", "sample_rate": "0", "channels": 0,
+  "r_frame_rate": "0/0", "id": "0x302"}
+]}`
+
+func TestParseProbeReadsTheStreams(t *testing.T) {
+	p, err := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
+	if err != nil {
+		t.Fatalf("ParseProbe: %v", err)
+	}
+	want := Video{ID: "0x300", Codec: "h264", Profile: "High", PixFmt: "yuv420p", Width: 1920, Height: 1080,
+		FrameRate: Rational{25, 1}, Field: FieldInterlaced}
+	if p.Video == nil || *p.Video != want {
+		t.Fatalf("video = %+v, want %+v", p.Video, want)
+	}
+	if len(p.Audio) != 2 || p.Audio[0].Language != "eng" || p.Audio[1].ID != "0x302" {
+		t.Fatalf("audio = %+v", p.Audio)
+	}
+	if _, err := ParseProbe([]byte("{")); err == nil {
+		t.Errorf("ParseProbe accepted malformed JSON")
+	}
+}
+
+// Spec § Encoder argv: a PMT-declared audio stream that carries no packets is
+// reported with 0 channels and a sample rate of 0, and does not qualify.
+func TestADeclaredButEmptyAudioStreamDoesNotQualify(t *testing.T) {
+	p, _ := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
+	q := p.Qualifying()
+	if len(q) != 1 || q[0].ID != "0x301" {
+		t.Fatalf("qualifying = %+v, want only the AAC stream", q)
+	}
+	for _, a := range []Audio{
+		{Codec: "", Channels: 2, SampleRate: 48000},
+		{Codec: "unknown", Channels: 2, SampleRate: 48000},
+		{Codec: "none", Channels: 2, SampleRate: 48000},
+		{Codec: "mp2", Channels: 0, SampleRate: 48000},
+		{Codec: "mp2", Channels: 2, SampleRate: 0},
+	} {
+		if a.Qualifies() {
+			t.Errorf("%+v qualifies", a)
+		}
+	}
+}
+
+// Ruling R28 (Refs #525): ffprobe's field_order is kept as three states. Only
+// tt, bb, tb or bt is interlaced; "unknown" -- what ffprobe reports for a
+// progressive HEVC stream in a transport stream -- stays a distinct third
+// state, is never folded into interlaced, and is treated as progressive:
+// no deinterlace, and R is the frame rate.
+func TestFieldOrderUnknownIsADistinctStateTreatedAsProgressive(t *testing.T) {
+	for value, want := range map[string]FieldOrder{
+		"progressive": FieldProgressive,
+		"tt":          FieldInterlaced, "bb": FieldInterlaced, "tb": FieldInterlaced, "bt": FieldInterlaced,
+		"unknown": FieldUnknown, "": FieldUnknown,
+	} {
+		if got := parseFieldOrder(value); got != want {
+			t.Errorf("field_order %q = %v, want %v", value, got, want)
+		}
+	}
+	if FieldUnknown == FieldInterlaced || FieldUnknown == FieldProgressive {
+		t.Fatalf("unknown is folded into another state")
+	}
+	hevc := Probe{Video: &Video{Codec: "hevc", Width: 640, Height: 360, FrameRate: Rational{25, 1}, Field: FieldUnknown}}
+	out, err := Decide(hevc)
+	if err != nil {
+		t.Fatalf("Decide: %v", err)
+	}
+	if out.FrameRate != (Rational{25, 1}) || out.GOP != 50 {
+		t.Errorf("an unknown field order gave R=%v G=%d, want the frame rate, 25/1 and 50", out.FrameRate, out.GOP)
+	}
+	plan := PlanGeneration(out, hevc, EngineSoftware)
+	if plan.Deinterlace || strings.Contains(strings.Join(out.Argv(plan, DefaultDevice), " "), "bwdif") {
+		t.Errorf("an unknown field order was deinterlaced")
+	}
+	for _, s := range []FieldOrder{FieldUnknown, FieldProgressive, FieldInterlaced} {
+		if s.String() == "" {
+			t.Errorf("%d has no name", s)
+		}
+	}
+}
+
+func TestParseRational(t *testing.T) {
+	for value, ok := range map[string]bool{"25/1": true, "30000/1001": true, "0/0": false, "25": false, "a/b": false, "-1/2": false} {
+		if _, got := parseRational(value); got != ok {
+			t.Errorf("parseRational(%q) ok = %t, want %t", value, got, ok)
+		}
+	}
+	if (Rational{}).Float() != 0 || (Rational{30000, 1001}).String() != "30000/1001" {
+		t.Errorf("Rational formatting")
+	}
+	p, _ := ParseProbe([]byte(`{"streams":[{"codec_type":"video","width":2,"height":2,"r_frame_rate":"0/0","avg_frame_rate":"50/1"},{"codec_type":"video","width":4}]}`))
+	if p.Video.FrameRate != (Rational{50, 1}) || p.Video.Width != 2 {
+		t.Errorf("the average rate is the fallback and the first video stream wins: %+v", p.Video)
+	}
+}
diff --git a/relay/hls/reader.go b/relay/hls/reader.go
new file mode 100644
index 00000000..df4fd082
--- /dev/null
+++ b/relay/hls/reader.go
@@ -0,0 +1,138 @@
+package hls
+
+import (
+	"encoding/binary"
+	"errors"
+	"io"
+)
+
+// readSize is how much the reader asks each pipe for at once, relay/output's
+// figure.
+const readSize = 65536
+
+// maxInitBytes bounds the boxes held before the moov, relay/output's figure
+// for the same init segment.
+const maxInitBytes = 10 << 20
+
+// errNoInit is an output that wrote a fragment before any init segment.
+var errNoInit = errors.New("hls: an encoder output wrote a moof before its moov")
+
+// splitter cuts one encoder output's byte stream into its init segment and
+// its fragments, as the bytes arrive (spec D6). The init segment is every box
+// up to and including the moov -- ftyp and moov, which `delay_moov` writes
+// only once the first packets are known -- and it is handed on the moment
+// the moov is complete, so the multivariant can be answered before the first
+// 2 s fragment exists. A fragment is a moof and the mdat after it. Any other
+// top-level box after the moov (an mfra at the end of the output, say)
+// belongs to neither and is dropped.
+type splitter struct {
+	buf      []byte
+	init     []byte
+	haveInit bool
+	pending  []byte // a moof waiting for its mdat
+	onInit   func([]byte) error
+	onFrag   func([]byte) error
+}
+
+// read drains r to EOF through the splitter. It returns nil at a clean EOF,
+// even one that cut a box short: a generation's flushed tail is complete, and
+// a process that died mid-fragment has already said so through its exit
+// status, so a partial box is simply not a fragment.
+func (s *splitter) read(r io.Reader) error {
+	chunk := make([]byte, readSize)
+	for {
+		n, err := r.Read(chunk)
+		if n > 0 {
+			s.buf = append(s.buf, chunk[:n]...)
+			if perr := s.drain(); perr != nil {
+				return perr
+			}
+		}
+		if err != nil {
+			if errors.Is(err, io.EOF) {
+				return nil
+			}
+			return err
+		}
+	}
+}
+
+// drain takes every whole box off the front of the buffer.
+func (s *splitter) drain() error {
+	for len(s.buf) >= 8 {
+		declared := declaredSize(s.buf)
+		largesize := binary.BigEndian.Uint32(s.buf) == 1
+		switch {
+		case declared > maxBoxBytes:
+			return boxErr("a %q box declares more than %d bytes", string(s.buf[4:8]), maxBoxBytes)
+		case declared < 0:
+			return nil // a 64-bit size not yet complete
+		case declared < 8 || (largesize && declared < 16):
+			return boxErr("a %q box declares %d bytes, less than its own header", string(s.buf[4:8]), declared)
+		case declared > int64(len(s.buf)):
+			return nil // the rest of the box has not arrived yet
+		}
+		size := int(declared)
+		typ := string(s.buf[4:8])
+		b := s.buf[:size:size]
+		s.buf = append([]byte(nil), s.buf[size:]...)
+		if err := s.box(typ, b); err != nil {
+			return err
+		}
+	}
+	return nil
+}
+
+// declaredSize is the size a box header claims, whether or not the box has
+// arrived yet: -1 while a 64-bit size is itself incomplete, and past
+// maxBoxBytes for a size of 0 ("to the end of the file", which on a pipe is
+// a box that never ends) or anything else too large to hold.
+func declaredSize(b []byte) int64 {
+	size := int64(binary.BigEndian.Uint32(b))
+	switch size {
+	case 0:
+		return maxBoxBytes + 1
+	case 1:
+		if len(b) < 16 {
+			return -1
+		}
+		large := binary.BigEndian.Uint64(b[8:16])
+		if large > maxBoxBytes {
+			return maxBoxBytes + 1
+		}
+		return int64(large)
+	}
+	return size
+}
+
+func (s *splitter) box(typ string, b []byte) error {
+	if !s.haveInit {
+		if typ == "moof" {
+			return errNoInit
+		}
+		s.init = append(s.init, b...)
+		if len(s.init) > maxInitBytes {
+			return boxErr("no moov in the first %d bytes of an encoder output", maxInitBytes)
+		}
+		if typ != "moov" {
+			return nil
+		}
+		s.haveInit = true
+		init := s.init
+		s.init = nil
+		return s.onInit(init)
+	}
+	switch typ {
+	case "moof":
+		s.pending = b
+	case "mdat":
+		if s.pending == nil {
+			return nil
+		}
+		frag := make([]byte, 0, len(s.pending)+len(b))
+		frag = append(append(frag, s.pending...), b...)
+		s.pending = nil
+		return s.onFrag(frag)
+	}
+	return nil
+}
diff --git a/relay/hls/reader_test.go b/relay/hls/reader_test.go
new file mode 100644
index 00000000..5413ad05
--- /dev/null
+++ b/relay/hls/reader_test.go
@@ -0,0 +1,140 @@
+package hls
+
+import (
+	"bytes"
+	"errors"
+	"io"
+	"testing"
+	"testing/iotest"
+)
+
+// collect runs a splitter over data, read a few bytes at a time so every box
+// boundary lands mid-read somewhere, and returns what it handed on.
+func collect(t *testing.T, data []byte) (inits, frags [][]byte, err error) {
+	t.Helper()
+	sp := splitter{
+		onInit: func(b []byte) error { inits = append(inits, b); return nil },
+		onFrag: func(b []byte) error { frags = append(frags, b); return nil },
+	}
+	err = sp.read(iotest.OneByteReader(bytes.NewReader(data)))
+	return inits, frags, err
+}
+
+func TestTheSplitterHandsOnTheInitAtTheMoovAndEachMoofWithItsMdat(t *testing.T) {
+	init := videoInit(0)
+	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
+	f2 := fragSpec{seq: 2, trackID: 1, start: 512, durations: []uint32{512}, sync: true}.build()
+	stray := box("free", []byte("x"))
+	mfra := box("mfra", make([]byte, 8))
+	inits, frags, err := collect(t, cat(init, f1, stray, f2, mfra))
+	if err != nil {
+		t.Fatalf("read: %v", err)
+	}
+	if len(inits) != 1 || !bytes.Equal(inits[0], init) {
+		t.Fatalf("the init handed on is %d bytes, want the %d-byte ftyp+moov", len(inits[0]), len(init))
+	}
+	if len(frags) != 2 || !bytes.Equal(frags[0], f1) || !bytes.Equal(frags[1], f2) {
+		t.Fatalf("got %d fragments, want the two moof+mdat pairs and nothing else", len(frags))
+	}
+}
+
+// A process that dies mid-fragment leaves a partial box on its pipe: every
+// whole fragment before it is handed on, and the partial one is not.
+func TestEOFMidFragmentHandsOnOnlyWholeFragments(t *testing.T) {
+	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
+	f2 := fragSpec{seq: 2, trackID: 1, start: 512, durations: []uint32{512}, sync: true}.build()
+	_, frags, err := collect(t, cat(videoInit(0), f1, f2[:len(f2)-3]))
+	if err != nil {
+		t.Fatalf("a clean EOF mid-fragment is not an error: %v", err)
+	}
+	if len(frags) != 1 || !bytes.Equal(frags[0], f1) {
+		t.Fatalf("got %d fragments, want only the whole one", len(frags))
+	}
+	// A moof whose mdat never arrived is not a fragment either.
+	moofOnly := f2[:bytes.Index(f2, []byte("mdat"))-4]
+	_, frags, _ = collect(t, cat(videoInit(0), f1, moofOnly))
+	if len(frags) != 1 {
+		t.Fatalf("a moof with no mdat was handed on")
+	}
+}
+
+func TestTheSplitterRefusesWhatIsNotFragmentedMP4(t *testing.T) {
+	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
+	if _, _, err := collect(t, cat(box("ftyp", nil), f1)); !errors.Is(err, errNoInit) {
+		t.Errorf("a moof before any moov: %v, want errNoInit", err)
+	}
+	huge := cat(be32(maxBoxBytes+1), []byte("mdat"))
+	if _, _, err := collect(t, cat(videoInit(0), huge)); !errors.Is(err, errBox) {
+		t.Errorf("a box past the ceiling: %v, want a malformed-box error", err)
+	}
+	if _, _, err := collect(t, cat(videoInit(0), be32(3), []byte("moof"))); !errors.Is(err, errBox) {
+		t.Errorf("a box smaller than its header: %v, want a malformed-box error", err)
+	}
+	if _, _, err := collect(t, cat(be32(0), []byte("mdat"))); !errors.Is(err, errBox) {
+		t.Errorf("a to-the-end box on a pipe: %v, want a malformed-box error", err)
+	}
+	large := cat(be32(1), []byte("mdat"), be64(1<<62))
+	if _, _, err := collect(t, large); !errors.Is(err, errBox) {
+		t.Errorf("a 64-bit size past the ceiling: %v, want a malformed-box error", err)
+	}
+	fine := cat(be32(1), []byte("free"), be64(20), []byte("abcd"), videoInit(0))
+	if inits, _, err := collect(t, fine); err != nil || len(inits) != 1 {
+		t.Errorf("a 64-bit-sized box before the moov was not skipped: %v", err)
+	}
+	var tooMuch []byte
+	for len(tooMuch) <= maxInitBytes {
+		tooMuch = append(tooMuch, box("free", make([]byte, 1<<20))...)
+	}
+	if _, _, err := collect(t, tooMuch); !errors.Is(err, errBox) {
+		t.Errorf("an init that never ends: %v, want a malformed-box error", err)
+	}
+}
+
+func TestTheSplitterStopsAtItsCallbacksError(t *testing.T) {
+	stop := errors.New("stop")
+	sp := splitter{onInit: func([]byte) error { return stop }, onFrag: func([]byte) error { return nil }}
+	if err := sp.read(bytes.NewReader(videoInit(0))); !errors.Is(err, stop) {
+		t.Errorf("an onInit error was not returned: %v", err)
+	}
+	sp = splitter{onInit: func([]byte) error { return nil }, onFrag: func([]byte) error { return stop }}
+	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
+	if err := sp.read(bytes.NewReader(cat(videoInit(0), f1))); !errors.Is(err, stop) {
+		t.Errorf("an onFrag error was not returned: %v", err)
+	}
+	broken := iotest.ErrReader(io.ErrClosedPipe)
+	if err := (&splitter{}).read(broken); !errors.Is(err, io.ErrClosedPipe) {
+		t.Errorf("a read error was not returned: %v", err)
+	}
+}
+
+// The box reader never panics and never reads out of bounds, whatever an
+// encoder's pipe holds (spec § Testing: the box reader gets fuzz tests).
+func FuzzParseInit(f *testing.F) {
+	f.Add(videoInit(860))
+	f.Add(audioInit())
+	f.Add(initSpec{trackID: 1, handler: "soun", timescale: 48000, entry: audioEntry("ec-3", box("dec3", []byte{1, 2, 3}))}.build())
+	f.Fuzz(func(_ *testing.T, data []byte) {
+		_, _ = ParseInit(data)
+		_, _ = StripEdits(data)
+	})
+}
+
+func FuzzParseFragment(f *testing.F) {
+	f.Add(fragSpec{seq: 1, trackID: 1, start: 99, durations: []uint32{512, 512}, sync: true}.build())
+	f.Add(synthFragment(1, 1, 0, []byte{1, 2, 3}, 4, 1024))
+	f.Fuzz(func(_ *testing.T, data []byte) {
+		track := Track{ID: 1, Timescale: 12800, DefaultDuration: 512}
+		if frag, err := ParseFragment(data, track); err == nil {
+			_ = shiftStart(&frag, 1)
+		}
+		_, _, _ = fragmentSamples(data, track)
+	})
+}
+
+func FuzzSplitter(f *testing.F) {
+	f.Add(cat(videoInit(0), fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()))
+	f.Fuzz(func(_ *testing.T, data []byte) {
+		sp := splitter{onInit: func([]byte) error { return nil }, onFrag: func([]byte) error { return nil }}
+		_ = sp.read(bytes.NewReader(data))
+	})
+}
diff --git a/relay/hls/real_test.go b/relay/hls/real_test.go
new file mode 100644
index 00000000..30b9131b
--- /dev/null
+++ b/relay/hls/real_test.go
@@ -0,0 +1,528 @@
+package hls
+
+import (
+	"bytes"
+	"context"
+	"fmt"
+	"os"
+	"os/exec"
+	"path/filepath"
+	"strings"
+	"sync"
+	"testing"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/buffer"
+)
+
+// The real-ffmpeg tests: the subject is what an encoder makes, so the
+// encoder is ffmpeg itself, over the 4a-0 fixtures built by
+// e2e-upstream/scripts/make-asset.sh. They are gated as parity row 4's pin
+// is (relay/channel/source_transcode_real_test.go): skipped where ffmpeg is
+// absent, and a FAILURE under CI, where go-tests.yml's build job runs them
+// against the production ffmpeg 9.0 in the base image. Software encoding
+// throughout: no CI runner has Quick Sync.
+
+// requireRealFFmpeg finds ffmpeg, ffprobe and bash, refusing to skip under CI.
+func requireRealFFmpeg(t *testing.T) {
+	t.Helper()
+	for _, tool := range []string{"ffmpeg", "ffprobe", "bash"} {
+		if _, err := exec.LookPath(tool); err != nil {
+			if os.Getenv("CI") != "" {
+				t.Fatalf("%s is not on PATH and CI is set: the base image carries it, and these are the packager's only real-encoder pins", tool)
+			}
+			t.Skipf("%s is not on PATH; the packager's real-ffmpeg tests did NOT run on this host", tool)
+		}
+	}
+}
+
+var (
+	fixtureMu  sync.Mutex
+	fixtureDir string
+	fixtures   = map[string][]byte{}
+	// realSilence is shared by every real test, as it is by every pipeline
+	// in a relay process: each canned encode runs once per test binary.
+	realSilence = &SilenceCache{}
+)
+
+// fixture builds (once per test binary) the named 4a-0 fixture with the
+// repository's own make-asset.sh, which probes its shape before it returns.
+func fixture(t *testing.T, name string) []byte {
+	t.Helper()
+	fixtureMu.Lock()
+	defer fixtureMu.Unlock()
+	if data, ok := fixtures[name]; ok {
+		return data
+	}
+	if fixtureDir == "" {
+		dir, err := os.MkdirTemp("", "hls-fixtures-")
+		if err != nil {
+			t.Fatal(err)
+		}
+		fixtureDir = dir
+	}
+	script, err := filepath.Abs("../../e2e-upstream/scripts/make-asset.sh")
+	if err != nil {
+		t.Fatal(err)
+	}
+	out := filepath.Join(fixtureDir, name+".ts")
+	// #nosec G204 -- the repository's own script and a fixed fixture name
+	cmd := exec.CommandContext(t.Context(), "bash", script, out, name)
+	if msg, err := cmd.CombinedOutput(); err != nil {
+		t.Fatalf("make-asset.sh %s: %v\n%s", name, err, msg)
+	}
+	data := readFile(t, out)
+	fixtures[name] = data
+	return data
+}
+
+func TestMain(m *testing.M) {
+	code := m.Run()
+	if fixtureDir != "" {
+		_ = os.RemoveAll(fixtureDir)
+	}
+	os.Exit(code)
+}
+
+// seconds is the first s seconds of a 20 s fixture, by byte proportion and
+// cut on a packet boundary: the raw transport stream, PIDs untouched.
+func seconds(data []byte, s int) []byte {
+	n := len(data) * s / 20
+	return data[:n-n%buffer.TSPacketSize]
+}
+
+// withoutPID drops every packet of one PID, leaving the PMT that declares it:
+// a declared-but-empty audio PID (spec § Encoder argv; 4a-0's hand-off).
+func withoutPID(data []byte, pid int) []byte {
+	var out []byte
+	for i := 0; i+buffer.TSPacketSize <= len(data); i += buffer.TSPacketSize {
+		p := data[i : i+buffer.TSPacketSize]
+		if int(p[1]&0x1f)<<8|int(p[2]) == pid {
+			continue
+		}
+		out = append(out, p...)
+	}
+	return out
+}
+
+// realRun is one pipeline over real ffmpeg with the given sources, a
+// boundary between each, the ring closed at the end, run to completion.
+type realRun struct {
+	p      *Pipeline
+	logs   *logBuffer
+	mu     sync.Mutex
+	spawns []Spawn
+}
+
+func runReal(t *testing.T, sources ...[]byte) *realRun {
+	t.Helper()
+	requireRealFFmpeg(t)
+	src := newTestSource()
+	for i, s := range sources {
+		if i > 0 {
+			src.mark()
+		}
+		src.write(t, s)
+	}
+	src.ring.Close()
+	r := &realRun{logs: &logBuffer{}}
+	p, err := Start(context.Background(), Config{
+		ChannelID:  "real",
+		Source:     src,
+		JoinBehind: time.Hour,
+		// These tests feed seconds of media at once rather than in real
+		// time, so after stdin closes a slow host is still encoding what it
+		// has read: under amd64 emulation the 1080i generation was killed
+		// mid-flush by the production 5 s grace with three of its six
+		// segments published (measured while planning). The grace's own
+		// behaviour is the stand-in test's subject
+		// (TestAGenerationThatIgnoresItsInputClosingIsKilledAfterTheGrace);
+		// here it only has to be longer than any honest flush.
+		ExitGrace: 20 * time.Second,
+		Detector:  &Detector{Device: filepath.Join(t.TempDir(), "renderD128"), Log: r.logs.logger()},
+		Silence:   realSilence,
+		Log:       r.logs.logger(),
+		Command: func(s Spawn) (string, []string) {
+			r.mu.Lock()
+			r.spawns = append(r.spawns, s)
+			r.mu.Unlock()
+			return "ffmpeg", s.Argv
+		},
+	})
+	if err != nil {
+		t.Fatalf("Start: %v", err)
+	}
+	t.Cleanup(p.Stop)
+	select {
+	case <-p.Done():
+	case <-time.After(3 * time.Minute):
+		t.Fatalf("the pipeline did not finish in 3 minutes:\n%s", r.logs.String())
+	}
+	r.p = p
+	return r
+}
+
+// ok fails the test if the pipeline ended in an error, with its log.
+func (r *realRun) ok(t *testing.T) {
+	t.Helper()
+	if err := r.p.Err(); err != nil {
+		t.Fatalf("the pipeline failed: %v\n%s", err, r.logs.String())
+	}
+}
+
+// realSegment is one stored segment of one rendition, parsed.
+type realSegment struct {
+	seq   uint64
+	gen   int
+	first Fragment
+	data  []byte
+	dur   float64
+}
+
+// segments is every stored segment of a rendition, in order, with the track
+// each generation's init describes.
+func (r *realRun) segments(t *testing.T, rendition string) ([]realSegment, map[int]Track) {
+	t.Helper()
+	s := r.p.Store()
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	tracks := map[int]Track{}
+	var out []realSegment
+	for _, seg := range s.segs {
+		p, ok := seg.parts[rendition]
+		if !ok {
+			t.Fatalf("segment %d (generation %d) has no %s part: the %s rendition stopped growing", seg.seq, seg.gen, rendition, rendition)
+		}
+		track, ok := tracks[seg.gen]
+		if !ok {
+			init, found := s.inits[initKey{rendition, seg.gen}]
+			if !found {
+				t.Fatalf("no %s init for generation %d", rendition, seg.gen)
+			}
+			var err error
+			if track, err = ParseInit(init); err != nil {
+				t.Fatalf("%s init-%d: %v", rendition, seg.gen, err)
+			}
+			tracks[seg.gen] = track
+		}
+		first, err := ParseFragment(p.data, track)
+		if err != nil {
+			t.Fatalf("%s segment %d: %v", rendition, seg.seq, err)
+		}
+		out = append(out, realSegment{seq: seg.seq, gen: seg.gen, first: first, data: p.data, dur: p.duration})
+	}
+	return out, tracks
+}
+
+func (r *realRun) multivariant(t *testing.T) string {
+	t.Helper()
+	mv, err := r.p.Multivariant("/hls/T")
+	if err != nil {
+		t.Fatalf("Multivariant: %v", err)
+	}
+	return string(mv)
+}
+
+func (r *realRun) renditions() []string {
+	o, _ := r.p.Output()
+	return o.Renditions()
+}
+
+// Parity: a generation's segments are 2.000 s +/- one frame, each starting
+// with a sync sample -- here on 12 s of the 1080i AAC + AC-3 fixture, on
+// three renditions, with the CODECS its init segments carry.
+func TestRealThe1080iFixtureGivesAligned2sSegmentsOnThreeRenditions(t *testing.T) {
+	r := runReal(t, seconds(fixture(t, "h264-1080i-aac-ac3"), 12))
+	r.ok(t)
+	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3" {
+		t.Fatalf("renditions %s, want video,aac,ac3", got)
+	}
+	mv := r.multivariant(t)
+	for _, want := range []string{
+		`CODECS="avc1.64002a,mp4a.40.2",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="aac"`,
+		`CODECS="avc1.64002a,ac-3",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="ac3"`,
+		`GROUP-ID="ac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6"`,
+	} {
+		if !strings.Contains(mv, want) {
+			t.Fatalf("the multivariant lacks %s:\n%s", want, mv)
+		}
+	}
+	video, vtracks := r.segments(t, RenditionVideo)
+	if len(video) < 5 {
+		t.Fatalf("%d segments from 12 s, want at least 5 whole ones", len(video))
+	}
+	oneFrame := 1.0 / 50
+	for i, v := range video {
+		if !v.first.Sync {
+			t.Errorf("video segment %d does not start with a sync sample", v.seq)
+		}
+		if i < len(video)-1 && (v.dur < 2-oneFrame || v.dur > 2+oneFrame) {
+			t.Errorf("video segment %d is %.3f s, want 2.000 s +/- one frame", v.seq, v.dur)
+		}
+	}
+	for _, name := range []string{RenditionAAC, RenditionAC3} {
+		audio, _ := r.segments(t, name)
+		for i, a := range audio {
+			v := video[i]
+			vstart := float64(v.first.Start) / float64(vtracks[v.gen].Timescale)
+			astart := float64(a.first.Start) / 48000
+			// An audio fragment is -frag_duration 200 ms rounded up to whole
+			// frames: 213 ms of AAC, 224 ms of AC-3. The first one starting
+			// in the span is at most one fragment after the span's start.
+			if astart < vstart-0.001 || astart-vstart >= 0.225 {
+				t.Errorf("%s segment %d starts at %.3f s against its video at %.3f s: more than one audio fragment into the span", name, a.seq, astart, vstart)
+			}
+			if i < len(audio)-1 && (a.dur-v.dur > 0.25 || v.dur-a.dur > 0.25) {
+				t.Errorf("%s segment %d is %.3f s against video %.3f s", name, a.seq, a.dur, v.dur)
+			}
+		}
+	}
+}
+
+// The E-AC-3 fixture gives three audio renditions (R20): AAC and AC-3
+// encoded from the E-AC-3, which is copied.
+func TestRealTheEAC3FixtureGivesThreeAudioRenditions(t *testing.T) {
+	r := runReal(t, seconds(fixture(t, "h264-eac3"), 6))
+	r.ok(t)
+	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3,eac3" {
+		t.Fatalf("renditions %s", got)
+	}
+	mv := r.multivariant(t)
+	for _, want := range []string{`"avc1.64002a,mp4a.40.2"`, `"avc1.64002a,ac-3"`, `"avc1.64002a,ec-3"`, `GROUP-ID="eac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6"`} {
+		if !strings.Contains(mv, want) {
+			t.Fatalf("the multivariant lacks %s:\n%s", want, mv)
+		}
+	}
+	argv := strings.Join(r.spawns[0].Argv, " ")
+	for _, want := range []string{"-map 0:i:0x601 -c:a aac", "-map 0:i:0x601 -c:a ac3 -ac 6 -b:a 640000", "-map 0:i:0x601 -c:a copy", "pipe:5"} {
+		if !strings.Contains(argv, want) {
+			t.Fatalf("the argv lacks %s:\n%s", want, argv)
+		}
+	}
+	for _, name := range []string{RenditionAAC, RenditionAC3, RenditionEAC3} {
+		if segs, _ := r.segments(t, name); len(segs) < 2 {
+			t.Fatalf("%s has %d segments", name, len(segs))
+		}
+	}
+}
+
+// Parity: a non-qualifying audio stream is not mapped. The AC-3 PID the PMT
+// still declares carries no packets; ffprobe reports it with 0 channels, and
+// mapping it would fail every output of the generation (finding 7).
+func TestRealADeclaredButEmptyAudioPIDIsNotMapped(t *testing.T) {
+	r := runReal(t, withoutPID(seconds(fixture(t, "h264-1080i-aac-ac3"), 6), 0x302))
+	r.ok(t)
+	probe, _ := r.p.GenerationProbe(0)
+	if len(probe.Audio) != 2 || probe.Audio[1].Qualifies() || !probe.Audio[0].Qualifies() {
+		t.Fatalf("the probe should see the declared AC-3 PID and not qualify it: %+v", probe.Audio)
+	}
+	if got := strings.Join(r.renditions(), ","); got != "video,aac" {
+		t.Fatalf("renditions %s, want video,aac", got)
+	}
+	if argv := strings.Join(r.spawns[0].Argv, " "); strings.Contains(argv, "0x302") {
+		t.Fatalf("the empty PID was mapped:\n%s", argv)
+	}
+	if segs, _ := r.segments(t, RenditionAAC); len(segs) < 2 {
+		t.Fatalf("the generation produced %d segments", len(segs))
+	}
+}
+
+// M8: the no-audio fixture gets a relay-synthesised silent AAC rendition.
+// Its argv has no audio output, the generation exits within 1 s of stdin
+// EOF, and each silent segment's duration equals its video segment's to
+// within one audio frame.
+func TestRealTheNoAudioFixtureGetsRelaySynthesisedSilence(t *testing.T) {
+	r := runReal(t, seconds(fixture(t, "h264-noaudio"), 6))
+	r.ok(t)
+	if after := exitAfterInputClosed(t, r.logs.String()); after >= time.Second {
+		t.Fatalf("the generation took %v to exit after its stdin closed; want < 1s", after)
+	}
+	s := r.spawns[0]
+	if s.Extra != nil || strings.Contains(strings.Join(s.Argv, " "), "pipe:3") || strings.Contains(strings.Join(s.Argv, " "), "lavfi") {
+		t.Fatalf("a no-audio generation's argv has an audio output or a lavfi input:\n%v", s.Argv)
+	}
+	if !strings.Contains(r.multivariant(t), `CODECS="avc1.64002a,mp4a.40.2"`) {
+		t.Fatalf("the silent AAC rendition's CODECS:\n%s", r.multivariant(t))
+	}
+	assertSilenceMatchesVideo(t, r, RenditionAAC, 0, 1024)
+}
+
+// E-AC-3 silence, which M8 did not prototype: generation 0 on the E-AC-3
+// fixture declares aac, ac3 and eac3; generation 1 on the no-audio fixture
+// fills all three from canned frames, E-AC-3's included.
+func TestRealEAC3SilenceAfterABoundary(t *testing.T) {
+	r := runReal(t, seconds(fixture(t, "h264-eac3"), 6), seconds(fixture(t, "h264-noaudio"), 6))
+	r.ok(t)
+	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3,eac3" {
+		t.Fatalf("renditions %s", got)
+	}
+	if len(r.spawns) != 2 || r.spawns[1].Extra != nil {
+		t.Fatalf("generation 1 should run with no audio output: %d spawns", len(r.spawns))
+	}
+	for name, spf := range map[string]uint32{RenditionAAC: 1024, RenditionAC3: 1536, RenditionEAC3: 1536} {
+		declared, _ := r.p.mustOutput(t).Declared(name)
+		canned, err := realSilence.Get(context.Background(), declared)
+		if err != nil {
+			t.Fatalf("canned %s: %v", name, err)
+		}
+		init, _ := r.p.Store().Init(name, 1)
+		if !bytes.Equal(init, canned.Init) {
+			t.Fatalf("generation 1's %s init is not the canned one", name)
+		}
+		if name == RenditionEAC3 && canned.Track.Codec != "ec-3" {
+			t.Fatalf("the canned E-AC-3 init's CODECS is %q", canned.Track.Codec)
+		}
+		assertSilenceMatchesVideo(t, r, name, 1, spf)
+	}
+}
+
+func (p *Pipeline) mustOutput(t *testing.T) Output {
+	t.Helper()
+	o, ok := p.Output()
+	if !ok {
+		t.Fatal("no output")
+	}
+	return o
+}
+
+// assertSilenceMatchesVideo checks every segment of generation gen of a
+// silent rendition against its video segment: the same span to within one
+// frame of spf samples, never short.
+func assertSilenceMatchesVideo(t *testing.T, r *realRun, name string, gen int, spf uint32) {
+	t.Helper()
+	video, _ := r.segments(t, RenditionVideo)
+	audio, _ := r.segments(t, name)
+	checked := 0
+	for i, a := range audio {
+		if a.gen != gen {
+			continue
+		}
+		if a.first.Samples == 0 || a.first.Duration != uint64(a.first.Samples)*uint64(spf) {
+			t.Fatalf("%s segment %d is not whole %d-sample frames: %+v", name, a.seq, spf, a.first)
+		}
+		frame := float64(spf) / 48000
+		if d := a.dur - video[i].dur; d < -frame || d > frame {
+			t.Errorf("%s segment %d is %.4f s against its video's %.4f s; want within one frame (%.4f s)", name, a.seq, a.dur, video[i].dur, frame)
+		}
+		checked++
+	}
+	if checked < 2 {
+		t.Fatalf("only %d silent %s segments in generation %d", checked, name, gen)
+	}
+}
+
+// Parity: a source boundary ends the generation, the next segment carries
+// EXT-X-DISCONTINUITY and a new EXT-X-MAP, and the second generation is
+// probed at the boundary -- its probe reports the second source. The two
+// fixtures have different PIDs, the case one surviving encoder silently
+// drops (M3). The later source adds E-AC-3, which declares no new rendition.
+func TestRealABoundaryGivesTwoGenerationsAndADiscontinuity(t *testing.T) {
+	r := runReal(t, seconds(fixture(t, "mpeg2-576i-mp2"), 6), seconds(fixture(t, "h264-eac3"), 6))
+	// The probe first: a generation-1 plan made from the wrong source maps
+	// PIDs its input does not have, and the pipeline fails; the probe is the
+	// assertion that names why.
+	if probe, ok := r.p.GenerationProbe(1); ok && (probe.Video == nil || probe.Video.Codec != "h264" || len(probe.Audio) != 1 || probe.Audio[0].Codec != "eac3") {
+		t.Fatalf("generation 1's probe describes %s, want the second source (h264 + eac3): it did not read from the boundary", describe(probe))
+	}
+	r.ok(t)
+	video, _ := r.segments(t, RenditionVideo)
+	gens := map[int]int{}
+	for _, v := range video {
+		gens[v.gen]++
+	}
+	if gens[1] == 0 {
+		t.Fatalf("generation 1 produced no segments after the boundary (generations: %v)", gens)
+	}
+	if gens[0] == 0 {
+		t.Fatalf("generation 0 produced no segments before the boundary")
+	}
+	if _, ok := r.p.GenerationProbe(1); !ok {
+		t.Fatalf("no generation 1 was probed")
+	}
+	for _, name := range []string{RenditionVideo, RenditionAAC} {
+		playlist, _, _ := r.p.Store().MediaPlaylist(name)
+		if !strings.Contains(string(playlist), fmt.Sprintf("#EXT-X-DISCONTINUITY\n#EXT-X-MAP:URI=\"%s/init-1.mp4\"", name)) {
+			t.Fatalf("the %s playlist has no discontinuity and new map at the boundary:\n%s", name, playlist)
+		}
+	}
+	if got := strings.Join(r.renditions(), ","); got != "video,aac" {
+		t.Fatalf("a later E-AC-3 source changed the rendition set to %s", got)
+	}
+}
+
+func describe(p Probe) string {
+	if p.Video == nil {
+		return "no video"
+	}
+	var audio []string
+	for _, a := range p.Audio {
+		audio = append(audio, a.Codec)
+	}
+	return p.Video.Codec + " + " + strings.Join(audio, ",")
+}
+
+// Rendition filling (finding 5): the rendition set is generation 0's, and
+// every later generation fills every declared rendition -- after a boundary
+// onto an MP2-only source the ac3 rendition keeps growing, encoded from MP2.
+func TestRealTheRenditionSetSurvivesABoundaryAndIsFilled(t *testing.T) {
+	r := runReal(t, seconds(fixture(t, "h264-1080i-aac-ac3"), 6), seconds(fixture(t, "mpeg2-576i-mp2"), 6))
+	r.ok(t)
+	ac3, tracks := r.segments(t, RenditionAC3)
+	after := 0
+	for _, s := range ac3 {
+		if s.gen == 1 && s.first.Samples > 0 {
+			after++
+		}
+	}
+	if after < 2 {
+		t.Fatalf("the ac3 rendition stopped growing at the boundary: %d gen-1 segments with audio", after)
+	}
+	if tracks[1].Codec != "ac-3" {
+		t.Fatalf("generation 1's ac3 init is %q", tracks[1].Codec)
+	}
+	if argv := strings.Join(r.spawns[len(r.spawns)-1].Argv, " "); !strings.Contains(argv, "-map 0:i:0x201 -c:a ac3 -ac 6 -b:a 640000") {
+		t.Fatalf("generation 1 does not encode AC-3 5.1 from the MP2:\n%s", argv)
+	}
+	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3" {
+		t.Fatalf("renditions %s, want generation 0's video,aac,ac3", got)
+	}
+}
+
+// D11: with no usable Quick Sync the detection gives software -- against the
+// real ffmpeg, with a device path that opens but is no render node.
+func TestRealDetectionWithoutQuickSyncGivesSoftware(t *testing.T) {
+	requireRealFFmpeg(t)
+	d := &Detector{Device: os.DevNull}
+	if got := d.Engine(context.Background()); got != EngineSoftware {
+		t.Fatalf("the detection encode against %s gave %s, want software", os.DevNull, got)
+	}
+}
+
+// The canned encodes (spec § Encoder argv, silence): every (codec, layout)
+// the bitrate table names gives an init with no edit list and a steady-state
+// frame of its codec's frame size.
+func TestRealEveryCannedSilenceEncodes(t *testing.T) {
+	requireRealFFmpeg(t)
+	for _, r := range []Rendition{
+		{Name: RenditionAAC, Channels: 2},
+		{Name: RenditionAC3, Channels: 6}, {Name: RenditionAC3, Channels: 2},
+		{Name: RenditionEAC3, Channels: 6}, {Name: RenditionEAC3, Channels: 2},
+	} {
+		c, err := realSilence.Get(context.Background(), r)
+		if err != nil {
+			t.Fatalf("%s %d.0: %v", r.Name, r.Channels, err)
+		}
+		want := map[string]uint32{RenditionAAC: 1024, RenditionAC3: 1536, RenditionEAC3: 1536}[r.Name]
+		if c.SamplesPerFrame != want || c.Track.Timescale != AudioTimescale || bytes.Contains(c.Init, []byte("edts")) || len(c.Frame) == 0 {
+			t.Fatalf("%s %d.0: spf %d, timescale %d, %d-byte frame", r.Name, r.Channels, c.SamplesPerFrame, c.Track.Timescale, len(c.Frame))
+		}
+		again, _ := realSilence.Get(context.Background(), r)
+		if again != c {
+			t.Fatalf("%s: the canned frame was encoded twice", r.Name)
+		}
+	}
+	bad := &SilenceCache{Command: filepath.Join(t.TempDir(), "no-ffmpeg")}
+	if _, err := bad.Get(context.Background(), Rendition{Name: RenditionAAC, Channels: 2}); err == nil {
+		t.Fatalf("a canned encode with no ffmpeg succeeded")
+	}
+}
diff --git a/relay/hls/segmenter.go b/relay/hls/segmenter.go
new file mode 100644
index 00000000..1204977b
--- /dev/null
+++ b/relay/hls/segmenter.go
@@ -0,0 +1,386 @@
+package hls
+
+import (
+	"sync"
+	"time"
+)
+
+// track is one encoder output of one generation, as its reader fills it.
+type track struct {
+	name     string
+	info     Track
+	haveInit bool
+	// frags is the queue of fragments read but not yet in a segment, tfdt
+	// already on the generation's shared timeline.
+	frags []Fragment
+	// maxStart is the latest fragment start ever read, so "has this track
+	// reached time t" survives the queue being consumed.
+	maxStart uint64
+	seen     bool
+	eof      bool
+}
+
+// videoSegment is a cut but unpublished video segment: [start, end) in video
+// ticks, the fragments that make it, and when it was cut.
+type videoSegment struct {
+	frags      []Fragment
+	start, end uint64
+	cut        time.Time
+}
+
+// AudioWait bounds how long a cut video segment waits for an audio rendition
+// that has not yet read past its end: two target durations. The audio
+// outputs normally run ahead of the video (200 ms fragments against 2 s
+// ones), so the wait is only ever reached by an audio output that stopped,
+// and the video must not stall behind it. It is wall-clock time, deliberately
+// not a count of video segments: when a generation catches up its JoinBehind
+// backlog faster than real time, the video reader can be several segments
+// ahead of an audio reader that simply has not been scheduled yet.
+const AudioWait = 2 * TargetDuration * time.Second
+
+// segmenter cuts one generation's outputs into segments and publishes them
+// (spec D6). The video fragments are accumulated until the 2 s grid is
+// reached, and a segment is only ever cut before a fragment whose first
+// sample is a sync sample, so every segment starts with one (Apple 7.4) --
+// which is also what makes a stray non-IDR keyframe from the encoder harmless
+// (Q1). Each audio rendition's segment holds the audio fragments whose start
+// falls in its video segment's span; a silent rendition's is written from its
+// canned frame.
+//
+// Readers call init, fragment and finish from their own goroutines; run is
+// the one goroutine that cuts and publishes.
+type segmenter struct {
+	store *Store
+	gen   int
+	// anchor is the ring arrival time of the generation's first chunk (D7):
+	// EXT-X-PROGRAM-DATE-TIME is the anchor plus the segment's media time.
+	anchorMu   sync.Mutex
+	anchor     time.Time
+	haveAnchor bool
+	now        func() time.Time
+	// audioWait is AudioWait unless a test shortened it.
+	audioWait time.Duration
+	// onFirst is called once, on the segmenter's goroutine and so before
+	// the attempt returns, when the first segment is published. It must not
+	// block.
+	onFirst func()
+
+	mu      sync.Mutex
+	changed chan struct{}
+	video   *track
+	audio   []*track
+	silence map[string]*silenceClock
+
+	// The fields below belong to run alone.
+	v0        uint64
+	haveV0    bool
+	grid      uint64 // the index of the next 2 s grid line, from v0
+	pending   []Fragment
+	ready     []videoSegment
+	tailDone  bool
+	published int
+}
+
+func newSegmenter(store *Store, gen int, audio []string, silence map[string]*silenceClock, now func() time.Time, audioWait time.Duration, onFirst func()) *segmenter {
+	if audioWait <= 0 {
+		audioWait = AudioWait
+	}
+	s := &segmenter{
+		store:     store,
+		gen:       gen,
+		now:       now,
+		audioWait: audioWait,
+		onFirst:   onFirst,
+		changed:   make(chan struct{}),
+		video:     &track{name: RenditionVideo},
+		silence:   silence,
+	}
+	for _, name := range audio {
+		s.audio = append(s.audio, &track{name: name})
+	}
+	return s
+}
+
+func (s *segmenter) notifyLocked() {
+	close(s.changed)
+	s.changed = make(chan struct{})
+}
+
+func (s *segmenter) track(name string) *track {
+	if name == RenditionVideo {
+		return s.video
+	}
+	for _, t := range s.audio {
+		if t.name == name {
+			return t
+		}
+	}
+	return nil
+}
+
+// setAnchor records the arrival time of the first chunk the generation was
+// fed.
+func (s *segmenter) setAnchor(at time.Time) {
+	s.anchorMu.Lock()
+	defer s.anchorMu.Unlock()
+	if !s.haveAnchor {
+		s.anchor, s.haveAnchor = at, true
+	}
+}
+
+func (s *segmenter) pdtAnchor() time.Time {
+	s.anchorMu.Lock()
+	defer s.anchorMu.Unlock()
+	if s.haveAnchor {
+		return s.anchor
+	}
+	return s.now()
+}
+
+// init records a track's parsed init segment.
+func (s *segmenter) init(name string, info Track) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	if t := s.track(name); t != nil {
+		t.info, t.haveInit = info, true
+	}
+	s.notifyLocked()
+}
+
+// fragment queues one fragment.
+func (s *segmenter) fragment(name string, f Fragment) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	if t := s.track(name); t != nil {
+		t.frags = append(t.frags, f)
+		if !t.seen || f.Start > t.maxStart {
+			t.maxStart, t.seen = f.Start, true
+		}
+	}
+	s.notifyLocked()
+}
+
+// finish marks a track's output at EOF.
+func (s *segmenter) finish(name string) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	if t := s.track(name); t != nil {
+		t.eof = true
+	}
+	s.notifyLocked()
+}
+
+// Published is how many segments the generation has published.
+func (s *segmenter) Published() int {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	return s.published
+}
+
+// run cuts and publishes until every output is at EOF and everything cut
+// has been published.
+func (s *segmenter) run() {
+	for {
+		s.mu.Lock()
+		s.cutLocked()
+		progressed, wake := s.publishLocked()
+		finished := s.video.eof && len(s.ready) == 0 && s.audioAtEOFLocked()
+		ch := s.changed
+		s.mu.Unlock()
+		switch {
+		case finished:
+			return
+		case progressed:
+		case wake > 0:
+			timer := time.NewTimer(wake)
+			select {
+			case <-ch:
+			case <-timer.C:
+			}
+			timer.Stop()
+		default:
+			<-ch
+		}
+	}
+}
+
+func (s *segmenter) audioAtEOFLocked() bool {
+	for _, t := range s.audio {
+		if !t.eof {
+			return false
+		}
+	}
+	return true
+}
+
+// gridTicks is one target duration in video ticks.
+func (s *segmenter) gridTicks() uint64 {
+	return uint64(TargetDuration) * uint64(s.video.info.Timescale)
+}
+
+// cutLocked moves queued video fragments into cut segments. A segment is
+// closed before a sync fragment that starts at or after the next grid line,
+// measured from the generation's first video tfdt, and the next grid line is
+// then the first one after that fragment's start. At EOF the pending
+// fragments become the generation's last segment, whose end is its last
+// fragment's tfdt plus its sample durations -- never an assumed 2 s.
+func (s *segmenter) cutLocked() {
+	v := s.video
+	for len(v.frags) > 0 {
+		f := v.frags[0]
+		v.frags = v.frags[1:]
+		if !s.haveV0 {
+			if !f.Sync {
+				// Nothing before the first sync sample can start a
+				// segment; an encoder's output always opens with one.
+				continue
+			}
+			s.v0, s.haveV0, s.grid = f.Start, true, 1
+			s.pending = []Fragment{f}
+			for _, clock := range s.silence {
+				clock.base = f.Start * uint64(clock.canned.Track.Timescale) / uint64(v.info.Timescale)
+			}
+			continue
+		}
+		if f.Sync && f.Start >= s.v0+s.grid*s.gridTicks() {
+			s.closeLocked(f.Start)
+			s.grid = (f.Start-s.v0)/s.gridTicks() + 1
+			s.pending = []Fragment{f}
+			continue
+		}
+		s.pending = append(s.pending, f)
+	}
+	if v.eof && !s.tailDone {
+		s.tailDone = true
+		if len(s.pending) > 0 {
+			s.closeLocked(s.pending[len(s.pending)-1].End())
+		}
+	}
+}
+
+func (s *segmenter) closeLocked(end uint64) {
+	s.ready = append(s.ready, videoSegment{frags: s.pending, start: s.pending[0].Start, end: end, cut: time.Now()})
+	s.pending = nil
+}
+
+// reached reports whether audio track t has read past video time vend, or
+// can read no further.
+func (s *segmenter) reached(t *track, vend uint64) bool {
+	if t.eof {
+		return true
+	}
+	if !t.haveInit || !t.seen {
+		return false
+	}
+	return t.maxStart*uint64(s.video.info.Timescale) >= vend*uint64(t.info.Timescale)
+}
+
+// publishLocked publishes every cut segment whose audio is complete, or has
+// waited AudioWait for it. It returns whether it published anything, and
+// otherwise how long until the oldest waiting segment stops waiting.
+func (s *segmenter) publishLocked() (bool, time.Duration) {
+	progressed := false
+	for len(s.ready) > 0 {
+		seg := s.ready[0]
+		waited := time.Since(seg.cut)
+		for _, t := range s.audio {
+			if !s.reached(t, seg.end) && waited < s.audioWait {
+				return progressed, s.audioWait - waited
+			}
+		}
+		s.ready = s.ready[1:]
+		s.publishOneLocked(seg, s.tailDone && len(s.ready) == 0)
+		progressed = true
+	}
+	return progressed, 0
+}
+
+func (s *segmenter) publishOneLocked(seg videoSegment, last bool) {
+	tv := uint64(s.video.info.Timescale)
+	parts := map[string]part{}
+	var video []byte
+	for _, f := range seg.frags {
+		video = append(video, f.Data...)
+	}
+	parts[RenditionVideo] = part{data: video, duration: ticksToSeconds(seg.end-seg.start, tv)}
+
+	var empty []string
+	for _, t := range s.audio {
+		ta, id := uint64(t.info.Timescale), t.info.ID
+		if !t.haveInit {
+			// An output that never wrote its init within AudioWait: its
+			// placeholder fragment is at the timescale and track every
+			// audio output here has.
+			ta, id = AudioTimescale, 1
+		}
+		var data []byte
+		var ticks uint64
+		for len(t.frags) > 0 {
+			f := t.frags[0]
+			if f.Start*tv < seg.start*ta {
+				t.frags = t.frags[1:]
+				continue
+			}
+			if f.Start*tv >= seg.end*ta {
+				break
+			}
+			data = append(data, f.Data...)
+			ticks += f.Duration
+			t.frags = t.frags[1:]
+		}
+		duration := ticksToSeconds(ticks, ta)
+		if len(data) == 0 {
+			if last {
+				empty = append(empty, t.name)
+				continue
+			}
+			// Mid-generation, the encoder wrote no audio for this span:
+			// its audio output stopped, and publishLocked waited AudioWait
+			// for it. The rendition still needs a segment at this
+			// sequence number, and the video must not stall behind it, so
+			// it gets an empty fragment of its own track at the span's
+			// start: a gap a player plays through.
+			data = synthFragment(1, id, seg.start*ta/tv, nil, 0, 1024)
+			duration = parts[RenditionVideo].duration
+		}
+		parts[t.name] = part{data: data, duration: duration}
+	}
+	if len(empty) > 0 {
+		// The generation's last segment -- its flushed tail after stdin
+		// EOF, whose final video frames outlast the audio -- has no audio
+		// on some rendition. An empty fragment there stalled AVPlayer's
+		// E-AC-3 path on the iOS 27 Simulator at the discontinuity
+		// (measured; dropping the tail cured it), so the tail is not
+		// published at all: no sequence number is used, and what is lost
+		// is at most one short segment at a source boundary.
+		return
+	}
+	for name, clock := range s.silence {
+		data, ticks := clock.segment(seg.end-s.v0, s.video.info.Timescale)
+		parts[name] = part{data: data, duration: ticksToSeconds(ticks, uint64(clock.canned.Track.Timescale))}
+	}
+
+	pdt := s.pdtAnchor().Add(ticksToDuration(seg.start, tv))
+	s.store.publish(s.gen, pdt, parts)
+	s.published++
+	if s.published == 1 && s.onFirst != nil {
+		s.onFirst()
+	}
+}
+
+func ticksToSeconds(ticks, timescale uint64) float64 {
+	if timescale == 0 {
+		return 0
+	}
+	return float64(ticks) / float64(timescale)
+}
+
+// ticksToDuration converts without the overflow ticks*1e9 would hit after a
+// day of 90 kHz ticks.
+func ticksToDuration(ticks, timescale uint64) time.Duration {
+	if timescale == 0 {
+		return 0
+	}
+	whole, rem := ticks/timescale, ticks%timescale
+	return time.Duration(whole)*time.Second + time.Duration(rem*uint64(time.Second)/timescale) // #nosec G115 -- rem < timescale, so rem*1e9 fits
+}
diff --git a/relay/hls/silence.go b/relay/hls/silence.go
new file mode 100644
index 00000000..d9fe3044
--- /dev/null
+++ b/relay/hls/silence.go
@@ -0,0 +1,307 @@
+package hls
+
+import (
+	"bytes"
+	"context"
+	"errors"
+	"fmt"
+	"io"
+	"log/slog"
+	"strconv"
+	"sync"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
+	"github.com/D10Scot/Dispatcharr/relay/redact"
+)
+
+// Silence is synthesised by the relay, never by ffmpeg (spec M8). An ffmpeg
+// `anullsrc` input keeps a generation alive after its stdin closes, which
+// breaks D10, and floods unpaced audio; so a rendition filled with silence
+// has no output in the argv, and the segmenter writes its segments itself,
+// from one canned silent frame.
+
+// SilenceTimeout bounds the one-off canned encode.
+const SilenceTimeout = 10 * time.Second
+
+// AudioTimescale is Ta, the audio timescale every canned encode and every
+// audio rendition runs at (48 kHz).
+const AudioTimescale = 48000
+
+// Canned is one (codec, declared layout)'s silent frame, as the relay
+// repeats it.
+type Canned struct {
+	// Init is the canned encode's init segment with its edit list stripped:
+	// M8 measured an AC-3 init with media_time 256 (5.3 ms), and every
+	// silent rendition must present from 0 in its own timeline, aligned with
+	// the video. It serves every generation's EXT-X-MAP for its rendition.
+	Init []byte
+	// Track is Init, parsed.
+	Track Track
+	// Frame is one steady-state frame. M8: every steady-state frame of a
+	// silent encode is byte-identical.
+	Frame []byte
+	// SamplesPerFrame is spf: 1024 for AAC, 1536 for AC-3 and E-AC-3.
+	SamplesPerFrame uint32
+}
+
+// SilenceArgv is the canned encode for one rendition at its declared layout:
+// one second of anullsrc, at the rendition's bitrate, to fragmented MP4 on
+// stdout. It is bounded twice, by -t 1 and by SilenceTimeout.
+func SilenceArgv(r Rendition) []string {
+	layout := "stereo"
+	if r.Channels == 6 {
+		layout = "5.1"
+	}
+	codec := map[string]string{RenditionAAC: "aac", RenditionAC3: "ac3", RenditionEAC3: "eac3"}[r.Name]
+	return []string{
+		"-hide_banner", "-loglevel", "error",
+		"-f", "lavfi", "-i", "anullsrc=r=48000:cl=" + layout,
+		"-t", "1",
+		"-c:a", codec, "-ac", strconv.Itoa(r.Channels), "-b:a", strconv.Itoa(audioBitrate(r)),
+		"-f", "mp4", "-movflags", fragFlags, "-frag_duration", audioFragment,
+		"pipe:1",
+	}
+}
+
+type cannedKey struct {
+	name     string
+	channels int
+}
+
+// SilenceCache runs each canned encode at the first need in the process and
+// keeps the result for the life of the process (spec § Encoder argv). One is
+// shared by every pipeline. A failed encode is not cached: the next
+// generation that needs silence tries again.
+type SilenceCache struct {
+	// Command is the ffmpeg executable ("ffmpeg" when empty).
+	Command string
+	// Log receives a failed encode's stderr.
+	Log *slog.Logger
+
+	mu      sync.Mutex
+	entries map[cannedKey]*Canned
+}
+
+// Get is rendition r's canned frame, encoding it on first use.
+func (s *SilenceCache) Get(ctx context.Context, r Rendition) (*Canned, error) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	key := cannedKey{name: r.Name, channels: r.Channels}
+	if c, ok := s.entries[key]; ok {
+		return c, nil
+	}
+	c, err := s.encode(ctx, r)
+	if err != nil {
+		return nil, err
+	}
+	if s.entries == nil {
+		s.entries = map[cannedKey]*Canned{}
+	}
+	s.entries[key] = c
+	return c, nil
+}
+
+// errNoSteadyFrame is a canned encode whose middle frames differ, which would
+// make "repeat one frame" a different signal from the encoder's own.
+var errNoSteadyFrame = errors.New("hls: the canned silent encode has no steady-state frame")
+
+func (s *SilenceCache) encode(ctx context.Context, r Rendition) (*Canned, error) {
+	command := s.Command
+	if command == "" {
+		command = "ffmpeg"
+	}
+	log := s.Log
+	if log == nil {
+		log = slog.Default()
+	}
+	ctx, cancel := context.WithTimeout(ctx, SilenceTimeout)
+	defer cancel()
+	proc, err := ffmpeg.Start(ctx, command, SilenceArgv(r))
+	if err != nil {
+		return nil, fmt.Errorf("hls: starting the canned %s encode: %w", r.Name, redact.Error(err))
+	}
+	stderrDone := make(chan struct{})
+	go func() {
+		defer close(stderrDone)
+		proc.ReadStderr(func(line string) {
+			log.Warn("canned silence encode stderr", "rendition", r.Name, "line", redact.Line(line))
+		})
+	}()
+	var out bytes.Buffer
+	_, copyErr := io.Copy(&out, io.LimitReader(proc.Stdout(), maxBoxBytes))
+	waitErr := proc.Wait()
+	<-stderrDone
+	if waitErr != nil || copyErr != nil {
+		return nil, fmt.Errorf("hls: the canned %s encode failed: %w", r.Name, redact.Error(errors.Join(waitErr, copyErr)))
+	}
+	return cannedFrom(out.Bytes())
+}
+
+// cannedFrom parses a canned encode: its init, and a steady-state frame from
+// the middle of its samples, checked to be identical to its successor.
+func cannedFrom(raw []byte) (*Canned, error) {
+	var init []byte
+	var track Track
+	var frames [][]byte
+	var spf uint32
+	sp := splitter{
+		onInit: func(b []byte) error {
+			t, err := ParseInit(b)
+			if err != nil {
+				return err
+			}
+			stripped, err := StripEdits(b)
+			if err != nil {
+				return err
+			}
+			init, track = stripped, t
+			return nil
+		},
+		onFrag: func(b []byte) error {
+			samples, durations, err := fragmentSamples(b, track)
+			if err != nil {
+				return err
+			}
+			frames = append(frames, samples...)
+			if spf == 0 && len(durations) > 0 {
+				spf = durations[0]
+			}
+			return nil
+		},
+	}
+	if err := sp.read(bytes.NewReader(raw)); err != nil {
+		return nil, err
+	}
+	if init == nil || len(frames) < 4 || spf == 0 {
+		return nil, errNoSteadyFrame
+	}
+	mid := len(frames) / 2
+	if !bytes.Equal(frames[mid], frames[mid+1]) {
+		return nil, errNoSteadyFrame
+	}
+	return &Canned{Init: init, Track: track, Frame: frames[mid], SamplesPerFrame: spf}, nil
+}
+
+// fragmentSamples splits a fragment's mdat into its samples, with each
+// sample's duration. It reads the trun's data offset relative to the moof
+// (default-base-is-moof, which fragFlags asks for).
+func fragmentSamples(data []byte, t Track) (samples [][]byte, durations []uint32, err error) {
+	moof, ok := child(data, 0, len(data), "moof")
+	if !ok {
+		return nil, nil, boxErr("no moof")
+	}
+	traf, _ := child(data, moof.body, moof.end, "traf")
+	tfhd, ok := child(data, traf.body, traf.end, "tfhd")
+	if !ok {
+		return nil, nil, boxErr("no tfhd")
+	}
+	_, hflags, _ := fullBox(data, tfhd)
+	c := cursor{data: data, pos: tfhd.body + 8, end: tfhd.end}
+	if hflags&tfhdBaseDataOffset != 0 {
+		c.take(8)
+	}
+	if hflags&tfhdSampleDescIndex != 0 {
+		c.take(4)
+	}
+	dur, size := t.DefaultDuration, t.DefaultSize
+	if hflags&tfhdDefaultDuration != 0 {
+		dur = c.u32()
+	}
+	if hflags&tfhdDefaultSize != 0 {
+		size = c.u32()
+	}
+	trun, ok := child(data, traf.body, traf.end, "trun")
+	if !ok {
+		return nil, nil, boxErr("no trun")
+	}
+	_, rflags, _ := fullBox(data, trun)
+	tf := trunFlags(rflags)
+	rc := cursor{data: data, pos: trun.body + 4, end: trun.end}
+	count := rc.u32()
+	offset := int64(0)
+	if tf&trunDataOffset != 0 {
+		offset = int64(int32(rc.u32())) // #nosec G115 -- trun's data_offset is a signed 32-bit field (ISO/IEC 14496-12)
+	}
+	if tf&trunFirstSampleFlags != 0 {
+		rc.take(4)
+	}
+	if c.bad || rc.bad || count > 1<<16 {
+		return nil, nil, boxErr("short tfhd or trun")
+	}
+	pos := int64(moof.start) + offset
+	for i := uint32(0); i < count; i++ {
+		d, sz := dur, size
+		if tf&trunDuration != 0 {
+			d = rc.u32()
+		}
+		if tf&trunSize != 0 {
+			sz = rc.u32()
+		}
+		if tf&trunFlagsPresent != 0 {
+			rc.take(4)
+		}
+		if tf&trunCTO != 0 {
+			rc.take(4)
+		}
+		if rc.bad || pos < 0 || pos+int64(sz) > int64(len(data)) {
+			return nil, nil, boxErr("sample %d is outside its fragment", i)
+		}
+		samples = append(samples, data[pos:pos+int64(sz)])
+		durations = append(durations, d)
+		pos += int64(sz)
+	}
+	return samples, durations, nil
+}
+
+// silenceClock is one silent rendition's frame count within one generation
+// (spec § Encoder argv, silence). The arithmetic is integer and absolute per
+// generation: a segment's end, in ticks of the video timescale Tv measured
+// from the generation's first video tfdt, becomes a frame index at the audio
+// timescale Ta with a single ceiling,
+//
+//	ceil(end_ticks x Ta / (Tv x spf)) = (end_ticks x Ta + Tv x spf - 1) / (Tv x spf)
+//
+// in 64-bit integers, with no intermediate floor, so the count is exact and
+// every segment's end is within one frame of its video segment's end: the
+// error never accumulates.
+type silenceClock struct {
+	canned *Canned
+	// base is the generation's first video tfdt in audio ticks, so frame 0
+	// presents with the generation's first video frame. The spec counts
+	// frames from that tfdt; placing them there on the shared timeline is
+	// what aligns them with the video by tfdt (ParseInit).
+	base uint64
+	// next is the index of the next frame to write.
+	next uint64
+	// seq is the mfhd sequence number of the next fragment.
+	seq uint32
+}
+
+// endIndex is the frame index a segment ending endRel video ticks after the
+// generation's first video tfdt ends at: the single ceiling.
+func (s *silenceClock) endIndex(endRel uint64, tv uint32) uint64 {
+	unit := uint64(tv) * uint64(s.canned.SamplesPerFrame)
+	return (endRel*uint64(s.canned.Track.Timescale) + unit - 1) / unit
+}
+
+// segment writes the silent fragment for the video segment that ends endRel
+// video ticks after the generation's first video tfdt, and returns it with
+// its duration in audio ticks.
+func (s *silenceClock) segment(endRel uint64, tv uint32) ([]byte, uint64) {
+	spf := uint64(s.canned.SamplesPerFrame)
+	end := s.endIndex(endRel, tv)
+	count := uint64(1)
+	if end > s.next {
+		count = end - s.next
+	}
+	// A segment shorter than one frame still gets one: the rendition must
+	// have a segment at every sequence number, and the next segment's count
+	// is computed from the absolute index, so the extra frame is taken back
+	// there rather than accumulating.
+	start := s.base + s.next*spf
+	s.seq++
+	data := synthFragment(s.seq, s.canned.Track.ID, start, s.canned.Frame, int(count), s.canned.SamplesPerFrame) // #nosec G115 -- count is a segment's frames, a few hundred
+	s.next += count
+	return data, count * spf
+}
diff --git a/relay/hls/silence_test.go b/relay/hls/silence_test.go
new file mode 100644
index 00000000..df5a0003
--- /dev/null
+++ b/relay/hls/silence_test.go
@@ -0,0 +1,110 @@
+package hls
+
+import (
+	"bytes"
+	"errors"
+	"testing"
+)
+
+func testCanned(spf uint32) *Canned {
+	return &Canned{Track: Track{ID: 1, Timescale: 48000}, Frame: []byte{1, 2, 3, 4, 5, 6}, SamplesPerFrame: spf}
+}
+
+// Spec § Encoder argv, silence: each silent segment ends at frame index
+// ceil(end_ticks x Ta / (Tv x spf)), computed absolutely from the generation's
+// first video tfdt in 64-bit integers, so every segment's end is within one
+// frame of its video segment's end and the error never accumulates -- over
+// an hour of 2 s segments as over one.
+func TestSilenceIsExactAndNeverAccumulates(t *testing.T) {
+	cases := []struct {
+		name    string
+		tv      uint32
+		segment uint64 // video ticks per segment
+		spf     uint32
+	}{
+		{"AAC against 50p at 12800 Hz", 12800, 25600, 1024},
+		{"AC-3 against 50p at 12800 Hz", 12800, 25600, 1536},
+		{"AAC against 59.94p at 60000 Hz (2.002 s)", 60000, 120120, 1024},
+		{"E-AC-3 against 25p at 90000 Hz", 90000, 180000, 1536},
+	}
+	for _, c := range cases {
+		clock := &silenceClock{canned: testCanned(c.spf), base: 5000}
+		var frames uint64
+		for i := uint64(1); i <= 1800; i++ {
+			end := i * c.segment
+			data, ticks := clock.segment(end, c.tv)
+			f, err := ParseFragment(data, clock.canned.Track)
+			if err != nil {
+				t.Fatalf("%s: segment %d does not parse: %v", c.name, i, err)
+			}
+			if f.Start != 5000+frames*uint64(c.spf) {
+				t.Fatalf("%s: segment %d starts at %d, want where the previous one ended", c.name, i, f.Start)
+			}
+			frames += ticks / uint64(c.spf)
+			// |audio end - video end| < one frame, in cross-multiplied ticks.
+			audioEnd := frames * uint64(c.spf) * uint64(c.tv)
+			videoEnd := end * 48000
+			frame := uint64(c.spf) * uint64(c.tv)
+			if audioEnd < videoEnd || audioEnd-videoEnd >= frame {
+				t.Fatalf("%s: after segment %d the silence ends %+.4f s from its video, want within one frame (%.4f s) and never short",
+					c.name, i, (float64(audioEnd)-float64(videoEnd))/float64(uint64(c.tv)*48000), float64(c.spf)/48000)
+			}
+		}
+	}
+}
+
+// A segment shorter than one frame still gets one, and the next segment's
+// count, computed from the absolute index, takes it back.
+func TestSilenceShortSegmentsGetOneFrame(t *testing.T) {
+	clock := &silenceClock{canned: testCanned(1024)}
+	for i, end := range []uint64{1, 2} {
+		if _, ticks := clock.segment(end, 12800); ticks != 1024 {
+			t.Fatalf("one-tick segment %d got %d samples, want one frame", i, ticks)
+		}
+	}
+	data, _ := clock.segment(25600, 12800) // to 2.000 s: frame 94
+	f, _ := ParseFragment(data, clock.canned.Track)
+	if f.Start != 2*1024 || f.Samples != 92 {
+		t.Fatalf("the next segment is %d frames from frame %d, want 92 from 2", f.Samples, f.Start/1024)
+	}
+}
+
+func TestCannedFromNeedsASteadyStateFrame(t *testing.T) {
+	track := initSpec{trackID: 1, handler: "soun", timescale: 48000, entry: audioEntry("mp4a", esdsAAC(2)), emptyEdit: 21}.build()
+	steady := []byte{9, 9, 9}
+	var frags []byte
+	for i := 0; i < 6; i++ {
+		frags = append(frags, synthFragment(uint32(i+1), 1, uint64(i*1024), steady, 1, 1024)...) // #nosec G115 -- a test's small counts
+	}
+	c, err := cannedFrom(cat(track, frags))
+	if err != nil {
+		t.Fatalf("cannedFrom: %v", err)
+	}
+	if !bytes.Equal(c.Frame, steady) || c.SamplesPerFrame != 1024 || bytes.Contains(c.Init, []byte("edts")) || c.Track.Codec != "mp4a.40.2" {
+		t.Errorf("canned = %+v", c)
+	}
+	var varying []byte
+	for i := 0; i < 6; i++ {
+		varying = append(varying, synthFragment(uint32(i+1), 1, uint64(i*1024), []byte{byte(i)}, 1, 1024)...) // #nosec G115 -- a test's small counts
+	}
+	if _, err := cannedFrom(cat(track, varying)); !errors.Is(err, errNoSteadyFrame) {
+		t.Errorf("frames that differ gave %v, want errNoSteadyFrame", err)
+	}
+	if _, err := cannedFrom(track); !errors.Is(err, errNoSteadyFrame) {
+		t.Errorf("an encode with no frames gave %v", err)
+	}
+	if _, err := cannedFrom(box("moof", nil)); err == nil {
+		t.Errorf("an encode with no init was accepted")
+	}
+}
+
+func TestSilenceArgvIsBoundedAndHasNoOtherInput(t *testing.T) {
+	argv := SilenceArgv(Rendition{Name: RenditionEAC3, Channels: 6})
+	want := "-hide_banner -loglevel error -f lavfi -i anullsrc=r=48000:cl=5.1 -t 1 -c:a eac3 -ac 6 -b:a 640000 -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:1"
+	if got := joinArgs(argv); got != want {
+		t.Errorf("SilenceArgv = %q, want %q", got, want)
+	}
+	if got := joinArgs(SilenceArgv(Rendition{Name: RenditionAAC, Channels: 2})); got != "-hide_banner -loglevel error -f lavfi -i anullsrc=r=48000:cl=stereo -t 1 -c:a aac -ac 2 -b:a 160000 -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:1" {
+		t.Errorf("SilenceArgv(aac) = %q", got)
+	}
+}
diff --git a/relay/hls/store.go b/relay/hls/store.go
new file mode 100644
index 00000000..6d1ae3a8
--- /dev/null
+++ b/relay/hls/store.go
@@ -0,0 +1,253 @@
+package hls
+
+import (
+	"context"
+	"errors"
+	"fmt"
+	"strings"
+	"sync"
+	"time"
+)
+
+// StoreSegments and StoreBytes bound an hls.Store: 12 segments per rendition
+// (spec § State; about 26 MB per channel at D8's top rate, computed), and a
+// byte ceiling well above that which only a runaway would reach. LiveEdge is
+// how many of them a media playlist lists (D7); the two kept beyond it are
+// still fetchable by a player that loaded the previous playlist.
+const (
+	StoreSegments = 12
+	StoreBytes    = 64 << 20
+	LiveEdge      = 10
+	// TargetDuration is transcode mode's EXT-X-TARGETDURATION, in seconds.
+	TargetDuration = 2
+)
+
+// ErrStoreClosed is a wait on a store whose pipeline has ended.
+var ErrStoreClosed = errors.New("hls: the pipeline has ended")
+
+// part is one rendition's piece of one segment.
+type part struct {
+	data []byte
+	// duration is the EXTINF value, in seconds.
+	duration float64
+}
+
+// segment is one media sequence number across every rendition. All
+// renditions share it: an audio segment holds the audio whose start falls in
+// its video segment's span (spec § Playlists).
+type segment struct {
+	seq           uint64
+	gen           int
+	discontinuity bool
+	pdt           time.Time
+	published     time.Time
+	parts         map[string]part
+	bytes         int
+}
+
+type initKey struct {
+	rendition string
+	gen       int
+}
+
+// Store is one HLS pipeline's segments: per rendition, keyed by media
+// sequence, with each generation's init segments and discontinuity markers
+// (spec § State). Everything a 4a-1b handler serves comes from it, and it
+// renders every playlist (D7).
+type Store struct {
+	mu      sync.Mutex
+	changed chan struct{}
+	segs    []*segment
+	bytes   int
+	nextSeq uint64
+	// discontinuitiesGone counts discontinuity-carrying segments that have
+	// left the store, for EXT-X-DISCONTINUITY-SEQUENCE.
+	discontinuitiesGone uint64
+	lastGen             int
+	published           bool
+	inits               map[initKey][]byte
+	closed              bool
+	now                 func() time.Time
+}
+
+// NewStore is an empty store. now is the clock for Last-Modified (nil means
+// time.Now).
+func NewStore(now func() time.Time) *Store {
+	if now == nil {
+		now = time.Now
+	}
+	return &Store{changed: make(chan struct{}), inits: map[initKey][]byte{}, now: now}
+}
+
+func (s *Store) notifyLocked() {
+	close(s.changed)
+	s.changed = make(chan struct{})
+}
+
+// SetInit records a generation's init segment for a rendition.
+func (s *Store) SetInit(rendition string, gen int, data []byte) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	s.inits[initKey{rendition, gen}] = data
+	s.notifyLocked()
+}
+
+// Init is a generation's init segment for a rendition.
+func (s *Store) Init(rendition string, gen int) ([]byte, bool) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	data, ok := s.inits[initKey{rendition, gen}]
+	return data, ok
+}
+
+// hasInits reports whether every named rendition has generation gen's init.
+func (s *Store) hasInits(gen int, renditions []string) bool {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	for _, r := range renditions {
+		if _, ok := s.inits[initKey{r, gen}]; !ok {
+			return false
+		}
+	}
+	return true
+}
+
+// publish appends one segment across every rendition. The first segment of
+// a generation other than the previous segment's carries a discontinuity
+// (D10), so the media sequence continues across generations and a player is
+// told where a new EXT-X-MAP and timeline begin.
+func (s *Store) publish(gen int, pdt time.Time, parts map[string]part) uint64 {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	seg := &segment{
+		seq:           s.nextSeq,
+		gen:           gen,
+		discontinuity: s.published && gen != s.lastGen,
+		pdt:           pdt,
+		published:     s.now(),
+		parts:         parts,
+	}
+	for _, p := range parts {
+		seg.bytes += len(p.data)
+	}
+	s.nextSeq++
+	s.lastGen, s.published = gen, true
+	s.segs = append(s.segs, seg)
+	s.bytes += seg.bytes
+	for len(s.segs) > StoreSegments || (s.bytes > StoreBytes && len(s.segs) > 1) {
+		gone := s.segs[0]
+		if gone.discontinuity {
+			s.discontinuitiesGone++
+		}
+		s.bytes -= gone.bytes
+		s.segs = s.segs[1:]
+	}
+	s.evictInitsLocked()
+	s.notifyLocked()
+	return seg.seq
+}
+
+// evictInitsLocked drops the init segments of generations no stored segment
+// refers to, except the newest generation's, which the next segment will.
+func (s *Store) evictInitsLocked() {
+	live := map[int]bool{s.lastGen: true}
+	for _, seg := range s.segs {
+		live[seg.gen] = true
+	}
+	for key := range s.inits {
+		if !live[key.gen] && key.gen < s.lastGen {
+			delete(s.inits, key)
+		}
+	}
+}
+
+// Close marks the store ended and wakes every waiter.
+func (s *Store) Close() {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	if !s.closed {
+		s.closed = true
+		s.notifyLocked()
+	}
+}
+
+// Segment is one rendition's segment at seq, and false when seq is outside
+// the store (a 404, spec § Session resources).
+func (s *Store) Segment(rendition string, seq uint64) ([]byte, bool) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	for _, seg := range s.segs {
+		if seg.seq == seq {
+			p, ok := seg.parts[rendition]
+			return p.data, ok
+		}
+	}
+	return nil, false
+}
+
+// WaitSegment blocks until the store holds at least one segment, the context
+// ends, or the pipeline does (D7: a media playlist request waits for its
+// rendition's first segment; 4a-1b bounds the wait at 20 s).
+func (s *Store) WaitSegment(ctx context.Context) error {
+	for {
+		s.mu.Lock()
+		have, closed, ch := len(s.segs) > 0, s.closed, s.changed
+		s.mu.Unlock()
+		switch {
+		case have:
+			return nil
+		case closed:
+			return ErrStoreClosed
+		}
+		select {
+		case <-ctx.Done():
+			return ctx.Err()
+		case <-ch:
+		}
+	}
+}
+
+// MediaPlaylist renders one rendition's live-edge media playlist (spec
+// § Playlists) and the newest segment's publish time, which is the response's
+// Last-Modified (Apple 8.24). ok is false while the store holds no segment.
+//
+// The last LiveEdge segments are listed. EXT-X-PROGRAM-DATE-TIME is on every
+// segment; EXT-X-MAP opens each generation's run and carries that
+// generation's init; EXT-X-DISCONTINUITY precedes the first segment of every
+// generation after the first, including when that segment is the first one
+// listed, so a segment's discontinuity sequence number never changes between
+// reloads; EXT-X-DISCONTINUITY-SEQUENCE counts the discontinuities that have
+// left the list. EXT-X-ENDLIST is never written.
+func (s *Store) MediaPlaylist(rendition string) ([]byte, time.Time, bool) {
+	s.mu.Lock()
+	defer s.mu.Unlock()
+	if len(s.segs) == 0 {
+		return nil, time.Time{}, false
+	}
+	first := max(0, len(s.segs)-LiveEdge)
+	listed := s.segs[first:]
+	gone := s.discontinuitiesGone
+	for _, seg := range s.segs[:first] {
+		if seg.discontinuity {
+			gone++
+		}
+	}
+	var b strings.Builder
+	b.WriteString("#EXTM3U\n#EXT-X-VERSION:7\n")
+	fmt.Fprintf(&b, "#EXT-X-TARGETDURATION:%d\n", TargetDuration)
+	fmt.Fprintf(&b, "#EXT-X-MEDIA-SEQUENCE:%d\n", listed[0].seq)
+	fmt.Fprintf(&b, "#EXT-X-DISCONTINUITY-SEQUENCE:%d\n", gone)
+	b.WriteString("#EXT-X-INDEPENDENT-SEGMENTS\n")
+	for i, seg := range listed {
+		if seg.discontinuity {
+			b.WriteString("#EXT-X-DISCONTINUITY\n")
+		}
+		if i == 0 || seg.gen != listed[i-1].gen {
+			fmt.Fprintf(&b, "#EXT-X-MAP:URI=\"%s/init-%d.mp4\"\n", rendition, seg.gen)
+		}
+		fmt.Fprintf(&b, "#EXT-X-PROGRAM-DATE-TIME:%s\n", seg.pdt.UTC().Format("2006-01-02T15:04:05.000Z"))
+		fmt.Fprintf(&b, "#EXTINF:%.3f,\n", seg.parts[rendition].duration)
+		fmt.Fprintf(&b, "%s/%d.m4s\n", rendition, seg.seq)
+	}
+	return []byte(b.String()), listed[len(listed)-1].published, true
+}
diff --git a/relay/hls/store_test.go b/relay/hls/store_test.go
new file mode 100644
index 00000000..15e88979
--- /dev/null
+++ b/relay/hls/store_test.go
@@ -0,0 +1,208 @@
+package hls
+
+import (
+	"context"
+	"errors"
+	"fmt"
+	"strings"
+	"testing"
+	"time"
+)
+
+var t0 = time.Date(2026, 9, 27, 12, 0, 0, 0, time.UTC)
+
+func publishN(s *Store, gen, n int, from time.Time) {
+	for i := 0; i < n; i++ {
+		s.publish(gen, from.Add(time.Duration(i)*2*time.Second), map[string]part{
+			RenditionVideo: {data: []byte(fmt.Sprintf("v%d", i)), duration: 2},
+			RenditionAAC:   {data: []byte(fmt.Sprintf("a%d", i)), duration: 1.984},
+		})
+	}
+}
+
+// D7 / spec § Playlists: the media playlist's tags, the live edge of 10, a
+// map per generation, a discontinuity before every later generation's first
+// segment, PDT on every segment, and no ENDLIST.
+func TestTheMediaPlaylist(t *testing.T) {
+	clock := t0
+	s := NewStore(func() time.Time { return clock })
+	if _, _, ok := s.MediaPlaylist(RenditionVideo); ok {
+		t.Fatalf("an empty store rendered a playlist")
+	}
+	publishN(s, 0, 4, t0)
+	publishN(s, 1, 3, t0.Add(10*time.Second))
+	clock = t0.Add(time.Minute)
+	publishN(s, 2, 1, t0.Add(20*time.Second))
+	got, modified, ok := s.MediaPlaylist(RenditionVideo)
+	if !ok {
+		t.Fatalf("no playlist")
+	}
+	want := `#EXTM3U
+#EXT-X-VERSION:7
+#EXT-X-TARGETDURATION:2
+#EXT-X-MEDIA-SEQUENCE:0
+#EXT-X-DISCONTINUITY-SEQUENCE:0
+#EXT-X-INDEPENDENT-SEGMENTS
+#EXT-X-MAP:URI="video/init-0.mp4"
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:00.000Z
+#EXTINF:2.000,
+video/0.m4s
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:02.000Z
+#EXTINF:2.000,
+video/1.m4s
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:04.000Z
+#EXTINF:2.000,
+video/2.m4s
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:06.000Z
+#EXTINF:2.000,
+video/3.m4s
+#EXT-X-DISCONTINUITY
+#EXT-X-MAP:URI="video/init-1.mp4"
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:10.000Z
+#EXTINF:2.000,
+video/4.m4s
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:12.000Z
+#EXTINF:2.000,
+video/5.m4s
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:14.000Z
+#EXTINF:2.000,
+video/6.m4s
+#EXT-X-DISCONTINUITY
+#EXT-X-MAP:URI="video/init-2.mp4"
+#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:20.000Z
+#EXTINF:2.000,
+video/7.m4s
+`
+	if string(got) != want {
+		t.Fatalf("media playlist:\n%s\nwant:\n%s", got, want)
+	}
+	if !modified.Equal(t0.Add(time.Minute)) {
+		t.Errorf("Last-Modified = %v, want the newest segment's publish time", modified)
+	}
+	audio, _, _ := s.MediaPlaylist(RenditionAAC)
+	if !strings.Contains(string(audio), "#EXTINF:1.984,\naac/7.m4s\n") || !strings.Contains(string(audio), `#EXT-X-MAP:URI="aac/init-2.mp4"`) {
+		t.Errorf("the audio playlist lists its own durations and maps:\n%s", audio)
+	}
+	if strings.Contains(string(got), "ENDLIST") {
+		t.Errorf("a live playlist carries EXT-X-ENDLIST")
+	}
+}
+
+// A discontinuity that has left the list is counted in
+// EXT-X-DISCONTINUITY-SEQUENCE, and one on the first listed segment is still
+// written, so a segment's discontinuity sequence never changes between
+// reloads.
+func TestTheDiscontinuitySequenceCountsWhatLeftTheList(t *testing.T) {
+	s := NewStore(nil)
+	publishN(s, 0, 2, t0)
+	publishN(s, 1, 2, t0)
+	publishN(s, 2, 8, t0) // 12 stored; the first two are past the live edge
+	got, _, _ := s.MediaPlaylist(RenditionVideo)
+	if !strings.Contains(string(got), "#EXT-X-MEDIA-SEQUENCE:2\n#EXT-X-DISCONTINUITY-SEQUENCE:0\n") {
+		t.Fatalf("the edge starts on generation 1's first segment, whose discontinuity is still listed:\n%s", got)
+	}
+	if !strings.HasPrefix(strings.SplitN(string(got), "#EXT-X-INDEPENDENT-SEGMENTS\n", 2)[1], "#EXT-X-DISCONTINUITY\n#EXT-X-MAP:URI=\"video/init-1.mp4\"") {
+		t.Errorf("the first listed segment lost its discontinuity:\n%s", got)
+	}
+	publishN(s, 2, 1, t0) // generation 1's first segment leaves the list
+	got, _, _ = s.MediaPlaylist(RenditionVideo)
+	if !strings.Contains(string(got), "#EXT-X-MEDIA-SEQUENCE:3\n#EXT-X-DISCONTINUITY-SEQUENCE:1\n") {
+		t.Fatalf("a discontinuity that left the list is not counted:\n%s", got)
+	}
+	publishN(s, 2, 12, t0) // everything but generation 2 leaves the store
+	got, _, _ = s.MediaPlaylist(RenditionVideo)
+	if !strings.Contains(string(got), "#EXT-X-DISCONTINUITY-SEQUENCE:2\n") {
+		t.Fatalf("a discontinuity evicted from the store is not counted:\n%s", got)
+	}
+}
+
+// The store keeps 12 segments (two past the live edge) and the init
+// segments of the generations they belong to; anything else is a 404.
+func TestTheStoreIsBoundedAndServesBySequence(t *testing.T) {
+	s := NewStore(nil)
+	s.SetInit(RenditionVideo, 0, []byte("init0"))
+	publishN(s, 0, 1, t0)
+	s.SetInit(RenditionVideo, 1, []byte("init1"))
+	publishN(s, 1, 13, t0)
+	if _, ok := s.Segment(RenditionVideo, 1); ok {
+		t.Errorf("segment 1 is still stored past the 12-segment bound")
+	}
+	if data, ok := s.Segment(RenditionVideo, 2); !ok || string(data) != "v1" {
+		t.Errorf("segment 2 = %q, %t", data, ok)
+	}
+	if _, ok := s.Segment(RenditionAC3, 5); ok {
+		t.Errorf("a rendition the segment lacks was served")
+	}
+	if _, ok := s.Segment(RenditionVideo, 99); ok {
+		t.Errorf("a future sequence number was served")
+	}
+	if _, ok := s.Init(RenditionVideo, 0); ok {
+		t.Errorf("generation 0's init outlived its segments")
+	}
+	if data, ok := s.Init(RenditionVideo, 1); !ok || string(data) != "init1" {
+		t.Errorf("generation 1's init = %q, %t", data, ok)
+	}
+	big := NewStore(nil)
+	for i := 0; i < 3; i++ {
+		big.publish(0, t0, map[string]part{RenditionVideo: {data: make([]byte, StoreBytes/2+1)}})
+	}
+	if _, ok := big.Segment(RenditionVideo, 1); ok {
+		t.Errorf("the byte bound kept more than one oversized segment")
+	}
+	if _, ok := big.Segment(RenditionVideo, 2); !ok {
+		t.Errorf("the byte bound dropped the newest segment")
+	}
+}
+
+func TestWaitSegment(t *testing.T) {
+	s := NewStore(nil)
+	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
+	defer cancel()
+	if err := s.WaitSegment(ctx); !errors.Is(err, context.DeadlineExceeded) {
+		t.Errorf("an empty store's wait = %v, want the context's end", err)
+	}
+	done := make(chan error, 1)
+	go func() { done <- s.WaitSegment(context.Background()) }()
+	time.Sleep(10 * time.Millisecond)
+	publishN(s, 0, 1, t0)
+	if err := <-done; err != nil {
+		t.Errorf("the wait did not end on the first segment: %v", err)
+	}
+	closed := NewStore(nil)
+	go closed.Close()
+	if err := closed.WaitSegment(context.Background()); !errors.Is(err, ErrStoreClosed) {
+		t.Errorf("a closed store's wait = %v, want ErrStoreClosed", err)
+	}
+	closed.Close()
+}
+
+// Spec § Playlists: one audio group per declared rendition, AAC first,
+// CHANNELS the declared layout, LANGUAGE only when the probe had one, and
+// one EXT-X-STREAM-INF per group with CODECS from the init segments.
+func TestTheMultivariant(t *testing.T) {
+	o := Output{Width: 1920, Height: 1080, FrameRate: Rational{50, 1}, GOP: 100, VideoBitrate: 6_000_000, VideoMaxrate: 8_000_000,
+		Audio: []Rendition{{Name: "aac", Channels: 2, Language: "eng"}, {Name: "ac3", Channels: 6}, {Name: "eac3", Channels: 6}}}
+	codecs := map[string]string{"video": "avc1.64002a", "aac": "mp4a.40.2", "ac3": "ac-3", "eac3": "ec-3"}
+	got := string(Multivariant(o, codecs, "/hls/TOKEN"))
+	want := `#EXTM3U
+#EXT-X-VERSION:7
+#EXT-X-INDEPENDENT-SEGMENTS
+#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",NAME="Stereo",LANGUAGE="eng",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="2",URI="/hls/TOKEN/aac.m3u8"
+#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="ac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6",URI="/hls/TOKEN/ac3.m3u8"
+#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="eac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6",URI="/hls/TOKEN/eac3.m3u8"
+#EXT-X-STREAM-INF:BANDWIDTH=8160000,AVERAGE-BANDWIDTH=6160000,CODECS="avc1.64002a,mp4a.40.2",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="aac"
+/hls/TOKEN/video.m3u8
+#EXT-X-STREAM-INF:BANDWIDTH=8640000,AVERAGE-BANDWIDTH=6640000,CODECS="avc1.64002a,ac-3",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="ac3"
+/hls/TOKEN/video.m3u8
+#EXT-X-STREAM-INF:BANDWIDTH=8640000,AVERAGE-BANDWIDTH=6640000,CODECS="avc1.64002a,ec-3",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="eac3"
+/hls/TOKEN/video.m3u8
+`
+	if got != want {
+		t.Fatalf("multivariant:\n%s\nwant:\n%s", got, want)
+	}
+	fractional := Output{Width: 1280, Height: 720, FrameRate: Rational{60000, 1001}, VideoBitrate: 4_000_000, VideoMaxrate: 5_000_000,
+		Audio: []Rendition{{Name: "aac", Channels: 2}}}
+	if got := string(Multivariant(fractional, codecs, "")); !strings.Contains(got, "FRAME-RATE=59.940") || !strings.Contains(got, "BANDWIDTH=5160000") {
+		t.Errorf("a 59.94 output:\n%s", got)
+	}
+}
diff --git a/relay/internal/relaytest/hls.go b/relay/internal/relaytest/hls.go
new file mode 100644
index 00000000..f0b8f7c1
--- /dev/null
+++ b/relay/internal/relaytest/hls.go
@@ -0,0 +1,90 @@
+package relaytest
+
+import (
+	"fmt"
+	"io"
+	"os"
+	"strconv"
+	"strings"
+	"time"
+)
+
+// fdFile is one --fd-file N=PATH: the bytes the stand-in writes to fd N.
+type fdFile struct {
+	fd   int
+	path string
+}
+
+// parseFDFile reads "N=PATH". N is 1 (stdout) or 3 and up; fd 0 is the
+// relay's input and fd 2 its stderr reader, neither of which an output file
+// belongs on.
+func parseFDFile(value string) (fdFile, bool) {
+	number, path, found := strings.Cut(value, "=")
+	if !found || path == "" {
+		return fdFile{}, false
+	}
+	fd, err := strconv.Atoi(number)
+	if err != nil || fd == 0 || fd == 2 || fd < 0 {
+		return fdFile{}, false
+	}
+	return fdFile{fd: fd, path: path}, true
+}
+
+// FDFileArg is the --fd-file value for fd and path, so a test never spells
+// the flag's syntax itself.
+func FDFileArg(fd int, path string) string {
+	return fmt.Sprintf("%d=%s", fd, path)
+}
+
+// runFDFileStandIn is the stand-in as relay/hls sees an encoder or a probe:
+// it writes each --fd-file's bytes to its descriptor, in the order given,
+// holds every descriptor open, and then ends as it was told to; its exit is
+// what closes them.
+//
+// fd 0 is drained in the background from the start, as a real ffmpeg reads
+// its input continuously; a stand-in that did not would block a relay
+// writing into a full pipe and make every test a deadlock that looked like a
+// slow one (runFMP4StandIn's reason). By default it exits once the files are
+// written, which is a process that ENDED on its own: before its first
+// segment when the files carry none, after it when they do. --wait-stdin-eof
+// holds the exit until fd 0 reaches EOF, which is a generation the relay
+// ended by closing its input at a source boundary. --ignore-stdin-eof never
+// exits, which is a generation the relay has to kill.
+func runFDFileStandIn(o standInOptions) int {
+	eof := make(chan struct{})
+	go func() {
+		defer close(eof)
+		_, _ = io.Copy(io.Discard, os.Stdin)
+	}()
+	for _, f := range o.fdFiles {
+		raw, err := os.ReadFile(f.path) // #nosec G304 -- a fixture path the test itself chose
+		if err != nil {
+			fmt.Fprintf(os.Stderr, "stand-in: reading %s: %v\n", f.path, err) // credential-logging: ok - an *fs.PathError over a test fixture path
+			return 2
+		}
+		out := os.Stdout
+		if f.fd != 1 {
+			out = os.NewFile(uintptr(f.fd), fmt.Sprintf("fd%d", f.fd))
+		}
+		if out == nil {
+			fmt.Fprintf(os.Stderr, "stand-in: fd %d is not open\n", f.fd)
+			return 2
+		}
+		if _, err := out.Write(raw); err != nil {
+			fmt.Fprintf(os.Stderr, "stand-in: writing fd %d: %v\n", f.fd, err) // credential-logging: ok - a pipe write error, no URL anywhere in it
+			return 2
+		}
+		// Not closed: an encoder holds its outputs open until it exits, so
+		// a reader's EOF is the process's end, exactly as with ffmpeg.
+	}
+	switch {
+	case o.ignoreStdinEOF:
+		// A sleep loop rather than select{}, for RunStandIn's stated reason.
+		for {
+			time.Sleep(time.Second)
+		}
+	case o.waitStdinEOF:
+		<-eof
+	}
+	return o.exitCode
+}
diff --git a/relay/internal/relaytest/hls_test.go b/relay/internal/relaytest/hls_test.go
new file mode 100644
index 00000000..5ddb3c3e
--- /dev/null
+++ b/relay/internal/relaytest/hls_test.go
@@ -0,0 +1,25 @@
+package relaytest
+
+import "testing"
+
+// --fd-file takes N=PATH for fd 1 or fd 3 and up; fd 0 is the relay's input
+// and fd 2 its stderr reader, and a malformed value is a parse failure the
+// stand-in reports rather than a flag it silently ignores.
+func TestFDFileArgsParse(t *testing.T) {
+	if f, ok := parseFDFile(FDFileArg(4, "/tmp/a.mp4")); !ok || f.fd != 4 || f.path != "/tmp/a.mp4" {
+		t.Fatalf("FDFileArg(4, ...) parses as %+v, %t", f, ok)
+	}
+	for _, bad := range []string{"0=/x", "2=/x", "-1=/x", "x=/x", "3=", "3"} {
+		if _, ok := parseFDFile(bad); ok {
+			t.Errorf("--fd-file %q was accepted", bad)
+		}
+	}
+	o := parseStandIn([]string{"--fd-file", "7"})
+	if o.fatalParseFlag != "--fd-file" {
+		t.Errorf("a malformed --fd-file did not fail the parse: %+v", o.fatalParseFlag)
+	}
+	o = parseStandIn([]string{"--fd-file", "1=/p", "--fd-file", "3=/a", "--wait-stdin-eof", "--ignore-stdin-eof"})
+	if len(o.fdFiles) != 2 || !o.waitStdinEOF || !o.ignoreStdinEOF {
+		t.Errorf("the --fd-file flags parse as %+v", o)
+	}
+}
diff --git a/relay/internal/relaytest/standin.go b/relay/internal/relaytest/standin.go
index 142b9590..add03094 100644
--- a/relay/internal/relaytest/standin.go
+++ b/relay/internal/relaytest/standin.go
@@ -95,6 +95,20 @@ import (
 //	                         processes were STARTED, and a log says that
 //	                         directly where a count of survivors says it only
 //	                         indirectly.
+//	--fd-file N=PATH         (repeatable) ignore the copy loop: write PATH's
+//	                         bytes to fd N (1 for stdout, 3 and up for the
+//	                         extra output pipes relay/hls's encoder is given),
+//	                         holding each open until it exits, then exit.
+//	                         What an HLS generation or an ffprobe
+//	                         looks like from the relay's side: the subject is
+//	                         the relay's reaction to the bytes, the exit and
+//	                         its moment, which a real encoder cannot be made to
+//	                         produce exactly on demand (hls.go).
+//	--wait-stdin-eof         with --fd-file: after writing, drain fd 0 and exit
+//	                         only at its EOF -- a generation that ends because
+//	                         the relay closed its input
+//	--ignore-stdin-eof       with --fd-file: after writing, stay alive whatever
+//	                         fd 0 does -- a generation that will not exit
 
 // StandInEnv is the environment variable that turns the re-executed test
 // binary into the stand-in.
@@ -137,6 +151,9 @@ type standInOptions struct {
 	tsPID          int
 	haveTSPID      bool
 	stdinPIDLog    string
+	fdFiles        []fdFile
+	waitStdinEOF   bool
+	ignoreStdinEOF bool
 	haveExitAfter  bool
 	haveDeadAir    bool
 	positional     []string
@@ -193,6 +210,16 @@ func parseStandIn(args []string) standInOptions {
 			o.haveTSPID = true
 		case "--stdin-pid-log":
 			o.stdinPIDLog = next()
+		case "--fd-file":
+			if f, ok := parseFDFile(next()); ok {
+				o.fdFiles = append(o.fdFiles, f)
+			} else {
+				o.fatalParseFlag = a
+			}
+		case "--wait-stdin-eof":
+			o.waitStdinEOF = true
+		case "--ignore-stdin-eof":
+			o.ignoreStdinEOF = true
 		case "--spawn-log":
 			o.spawnLog = next()
 		case "-i":
@@ -254,6 +281,9 @@ func RunStandIn(args []string) int {
 	if o.haveFMP4 {
 		return runFMP4StandIn(o)
 	}
+	if len(o.fdFiles) > 0 {
+		return runFDFileStandIn(o)
+	}
 
 	if o.input == "" {
 		fmt.Fprintln(os.Stderr, "stand-in: no input; expected `-i <url>` or a positional")
diff --git a/scripts/coverage_relay_go.floor b/scripts/coverage_relay_go.floor
index 5fbc1520..62019d8c 100644
--- a/scripts/coverage_relay_go.floor
+++ b/scripts/coverage_relay_go.floor
@@ -190,6 +190,33 @@
 #      JUST took and cannot know it is the Nth of a campaign.
 #   5. Re-run --gate and confirm it exits 0 against the new floor before
 #      committing.
+#
+# A PR MAY RAISE `missing` BY ITS OWN UNCOVERED CODE, AND BY NOTHING ELSE
+# (owner ruling R21, 2026-09-27; Phase 4 spec D20; CLAUDE.md § Testing). This
+# amends the ratchet: before it, no PR moved `missing` except a
+# re-measurement. Now a Go PR may raise it, but only by the uncovered
+# statements of its own new or changed code, and only when all of these hold:
+#   - its body lists those statements per file, block by block, read off a CI
+#     coverage artifact with the awk command above;
+#   - its statement coverage on its own additions is >= 85%;
+#   - it ran the >=12-round CI census of steps 1-2, and the census maximum is
+#     the old `missing` plus exactly the listed count;
+#   - the reviewer checked the listing against the artifact.
+# A draw above the floor that the listing does not explain is still a finding,
+# and still gets a re-measurement PR of its own, never a bump.
+#
+# A PACKAGE THAT IS NOT YET LINKED (ruling R27) is outside this file's
+# denominator, so the PR that adds it cannot move `missing` for it. That PR
+# shows the package's own per-package coverage instead: >= 85%, CI-measured
+# with this gate's flags (-count=1 -race -covermode=atomic; the package's
+# blocks are in the same CI artifact, reported "out of scope"), with a
+# per-file uncovered listing. The PR that first LINKS it re-baselines
+# `packages=` and `package_count` (steps 3-4) and may raise `missing` by
+# exactly two listed amounts: the package's uncovered statements as its
+# introducing PR listed them, re-measured; plus that PR's own new or changed
+# uncovered statements under the rule above. Phase 4a-1a is the first PR
+# under this rule: it adds relay/hls unlinked (4a-1b links it) and lists its
+# own additions to the linked packages.
 shape=go-race-per-package/v1
 statements=3696
 missing=589
```
<!-- appendix-A-end -->
