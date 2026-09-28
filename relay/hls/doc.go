// Package hls is the relay's HLS packager (Phase 4 spec,
// docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md, D6-D11;
// ADR 0009): it turns a channel's ring into fMP4/CMAF HLS renditions.
//
// One ffmpeg per GENERATION reads the channel's ring on fd 0 and writes one
// fragmented-MP4 stream per rendition on its own descriptor -- video on fd 1,
// stereo AAC on fd 3, AC-3 on fd 4, E-AC-3 on fd 5 (argv.go). A probe precedes
// every generation and reads from where that generation starts (probe.go,
// D9). A generation ends at every source boundary the channel records -- a
// failover or a same-URL reconnect -- because one encoder fed a second
// provider's PIDs silently drops it (spec M3); the next generation is probed
// there and marked by EXT-X-DISCONTINUITY and a new EXT-X-MAP (pipeline.go,
// D10). The box reader (box.go, init.go, fragment.go, reader.go) parses what
// the encoder writes with encoding/binary and nothing else; the segmenter
// (segmenter.go) cuts 2 s segments aligned across renditions; the Store
// (store.go) holds them and renders every playlist (playlist.go, D7). A
// rendition with no source this generation is relay-synthesised silence, never
// an ffmpeg input (silence.go, M8). Quick Sync is used when a one-frame
// detection encode succeeds, libx264 otherwise, and is written off for the
// process only when a failure is shown to be the device's (detect.go, D11).
//
// THE PACKAGE WAS INERT IN PHASE 4a-1a and is linked into the relay since
// 4a-1b, which attaches a Pipeline through Channel.AttachHLS and serves its
// Store under /hls/ (relay/httpapi's HLS handlers), so it is inside the Go
// coverage gate's denominator (rulings R27, R34).
//
// Everything is in process memory (ADR 0006): no Redis, no Postgres, and the
// standard library only (scripts/check_go_stdlib_only.sh).
package hls
