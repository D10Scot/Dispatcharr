// Package relaytest is the Go relay's test upstream: a synthetic MPEG-TS asset
// and an HTTP server that loops it, with the handful of faults the live path's
// tests need.
//
// It is a normal package rather than a _test.go file because 2c-2 through
// 2c-7 all drive it from different packages, and Go test files are not
// importable. It sits under internal/ so nothing outside this module can
// depend on it, and main never imports it, so it is not linked into the
// binary.
//
// It is the Go counterpart of apps/proxy/live_proxy/tests/harness/asset.py and
// harness/upstream.py, and the packet layout below is byte-identical to
// synthetic_ts() so a test can compare what the two relays deliver from the
// same bytes.
//
// SYNTHETIC RATHER THAN ENCODED, for the Python harness's reason: nothing on
// the live path decodes video. The ring buffer packetises at a 188-byte stride
// and carries whatever it is given, so a structurally valid transport stream
// is exactly as useful here as a real encode, costs no ffmpeg, and is
// byte-for-byte deterministic. The Proxy stream-profile architecture 2c-2
// implements spawns no subprocess at all, so no test in this PR needs a real
// remuxer.
package relaytest

import "fmt"

const (
	// PacketSize is the MPEG-TS packet size.
	PacketSize = 188

	// SyncByte starts every transport-stream packet.
	SyncByte = 0x47

	// NominalByteRate is what a pacing Rate of 1.0 means, in bytes per
	// second: 2 Mbit/s, the bitrate e2e-upstream/scripts/make-asset.sh builds
	// its own asset at, and the figure apps/proxy/live_proxy/tests/harness/
	// upstream.py:29's NOMINAL_BYTE_RATE uses. Pinned by
	// TestNominalByteRateAndWriteChunkMatchThePythonHarness.
	NominalByteRate = 2_000_000 / 8
)

// SyntheticTS returns n transport-stream packets on pid, with a real
// continuity counter and each packet's absolute index embedded in its payload.
//
// The layout is synthetic_ts()'s, byte for byte: the sync byte, the 13-bit PID
// split across two bytes with the payload-unit-start flag clear, then
// 0x10 | (i % 16) -- adaptation field control 01, payload only, in the high
// nibble and the continuity counter in the low one -- then a 184-byte payload
// whose first four bytes are i big-endian and whose remaining 180 are the
// repeating filler (i + j) % 256.
//
// THE EMBEDDED INDEX IS WHY A POSITION TEST CAN WORK AT ALL. The continuity
// counter only cycles mod 16 and the filler repeats too, so "have I seen this
// content before" is true of every packet at some distance. PacketIndex makes a
// packet's absolute position observable at any distance, which is what the
// join-point test asserts on. harness/README.md's third trap has the history.
func SyntheticTS(n, pid int) []byte {
	if n < 1 {
		panic(fmt.Sprintf("relaytest: packets must be >= 1, got %d", n))
	}
	if pid < 0 || pid > 0x1FFF {
		panic(fmt.Sprintf("relaytest: pid must fit in 13 bits, got %d", pid))
	}
	out := make([]byte, 0, n*PacketSize)
	for i := range n {
		out = append(out,
			SyncByte,
			byte((pid>>8)&0x1F),
			byte(pid&0xFF),
			0x10|byte(i%16),
			byte(i>>24), byte(i>>16), byte(i>>8), byte(i),
		)
		for j := range PacketSize - 8 {
			out = append(out, byte((i+j)%256))
		}
	}
	return out
}

// PacketIndex reads back the index SyntheticTS embedded in one packet.
func PacketIndex(packet []byte) int {
	if len(packet) < 8 {
		panic(fmt.Sprintf("relaytest: a packet is %d bytes, got %d", PacketSize, len(packet)))
	}
	return int(packet[4])<<24 | int(packet[5])<<16 | int(packet[6])<<8 | int(packet[7])
}

// AlignmentProblem reports why data is not a whole number of TS packets each
// starting with the sync byte, or the empty string when it is.
//
// It returns a reason rather than calling t.Fatalf so the caller's failure
// message names its own subject. A helper that fails on the caller's behalf
// produces messages that all read the same, and shape 6 -- a break-check must
// name the mechanism -- is what that costs.
func AlignmentProblem(data []byte) string {
	if len(data) == 0 {
		return "no bytes at all"
	}
	if len(data)%PacketSize != 0 {
		return fmt.Sprintf("%d bytes is not a whole number of %d-byte packets", len(data), PacketSize)
	}
	for offset := 0; offset < len(data); offset += PacketSize {
		if data[offset] != SyncByte {
			// %#02x, not %#04x: Go counts the "0x" prefix OUTSIDE the width
			// where Python counts it inside, so %#04x prints 0x0000 here and
			// the Python harness's own %#04x prints 0x00. Matching the Python
			// message matters because both suites' failures are read together.
			return fmt.Sprintf("byte %d is %#02x, not the sync byte %#02x", offset, data[offset], SyncByte)
		}
	}
	return ""
}
