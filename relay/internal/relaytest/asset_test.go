package relaytest

import (
	"testing"
)

// THE CROSS-IMPLEMENTATION DIGEST PIN WAS DELETED BY PHASE 2 STAGE 2d-4, AND
// THAT IS THE POINT. Its own header said what it was for: the sha256 came from
// the PYTHON harness's synthetic_ts(), "so it proves the two implementations
// agree rather than that this one is deterministic (hollow shape 1)". With
// apps/proxy/live_proxy/ deleted there is one implementation, and the digest
// would prove only that SyntheticTS is a pure function of its arguments --
// which is the hollow shape the pin was written to avoid. It was deleted
// rather than regenerated from the Go, because regenerating it is exactly the
// move its own comment forbade.
//
// What survives is the SHAPE, which still pins the asset against the e2e fake
// provider rather than against a deleted Python file: 512 packets of 188
// bytes is 96,256, and PacketSize/PacketPID below read the same bytes back.
func TestSyntheticTSHasThePacketCountAndSizeItsCallersAssume(t *testing.T) {
	data := SyntheticTS(512, 0x100)
	if want := 512 * PacketSize; len(data) != want {
		t.Fatalf("SyntheticTS(512, 0x100) is %d bytes, want %d (512 x %d)",
			len(data), want, PacketSize)
	}
}

func TestPacketIndexReadsBackEveryPosition(t *testing.T) {
	data := SyntheticTS(40, 0x100)
	for i := range 40 {
		packet := data[i*PacketSize : (i+1)*PacketSize]
		if got := PacketIndex(packet); got != i {
			t.Fatalf("packet %d reports index %d", i, got)
		}
	}
}

func TestAlignmentProblemNamesWhatIsWrong(t *testing.T) {
	for _, tc := range []struct {
		name string
		data []byte
		want string
	}{
		{"a whole asset", SyntheticTS(3, 0x100), ""},
		{"nothing at all", nil, "no bytes at all"},
		{
			"a truncated packet",
			SyntheticTS(2, 0x100)[:300],
			"300 bytes is not a whole number of 188-byte packets",
		},
		{
			"a lost sync byte",
			append(append([]byte{}, SyntheticTS(1, 0x100)...), corrupted(SyntheticTS(1, 0x100))...),
			"byte 188 is 0x00, not the sync byte 0x47",
		},
	} {
		if got := AlignmentProblem(tc.data); got != tc.want {
			t.Errorf("%s: AlignmentProblem = %q, want %q", tc.name, got, tc.want)
		}
	}
}

func corrupted(packet []byte) []byte {
	out := append([]byte(nil), packet...)
	out[0] = 0x00
	return out
}

// These two mirrored apps/proxy/live_proxy/tests/harness/upstream.py:29
// (NOMINAL_BYTE_RATE) and :31 (_WRITE_CHUNK), which stage 2d-4 deleted. The
// assertions are kept, re-anchored on the DERIVATIONS rather than the deleted
// file, so the numbers stay checkable:
//
//	NominalByteRate = 2_000_000 / 8 -- "rate 1.0" is 2 Mbit/s, the bitrate
//	e2e-upstream/scripts/make-asset.sh builds its own asset at. That file
//	survives 2d and is the right anchor.
//	WriteChunk = PacketSize * 50 -- fifty whole TS packets per write.
func TestNominalByteRateAndWriteChunkKeepTheirDerivations(t *testing.T) {
	if want := 2_000_000 / 8; NominalByteRate != want {
		t.Errorf("NominalByteRate = %d, want %d (2 Mbit/s in bytes per second, "+
			"e2e-upstream/scripts/make-asset.sh's bitrate)", NominalByteRate, want)
	}
	if want := PacketSize * 50; WriteChunk != want {
		t.Errorf("WriteChunk = %d, want %d (fifty whole TS packets)", WriteChunk, want)
	}
}

// THE PID ROUND-TRIPS, and the rewrite the stand-in performs is visible
// through it. PacketPID and --ts-pid are the mechanism the Output Profile
// tests use to tell a transcode's output from its input (2c-7), so the two
// halves are pinned against each other here rather than only inside the tests
// that depend on them.
func TestPacketPIDReadsBackWhatSyntheticTSWroteAndWhatRewritePIDSets(t *testing.T) {
	asset := SyntheticTS(4, 0x100)
	for offset := 0; offset < len(asset); offset += PacketSize {
		if got := PacketPID(asset[offset : offset+PacketSize]); got != 0x100 {
			t.Fatalf("packet at %d carries PID %#x, want the 0x100 SyntheticTS wrote", offset, got)
		}
	}

	// A VALUE THAT EXERCISES BOTH BYTES: 0x1FF needs the low five bits of
	// byte 1 as well as the whole of byte 2, so a rewrite that touched only
	// one of them would fail here and pass for any PID under 0x100.
	whole, rest := rewritePID(append([]byte(nil), asset...), 0x1FF)
	if len(rest) != 0 {
		t.Fatalf("a whole number of packets left %d bytes over", len(rest))
	}
	for offset := 0; offset < len(whole); offset += PacketSize {
		packet := whole[offset : offset+PacketSize]
		if got := PacketPID(packet); got != 0x1FF {
			t.Fatalf("packet at %d carries PID %#x after the rewrite, want 0x1FF", offset, got)
		}
		if packet[0] != SyncByte {
			t.Fatalf("the rewrite broke the sync byte at %d", offset)
		}
		if got := PacketIndex(packet); got != offset/PacketSize {
			t.Fatalf("the rewrite moved packet %d's embedded index to %d", offset/PacketSize, got)
		}
	}

	// A PARTIAL TRAILING PACKET IS CARRIED, NOT REWRITTEN: 8192-byte reads do
	// not land on 188-byte boundaries, and a rewrite that assumed they did
	// would corrupt every packet after the first short read.
	partial := append([]byte(nil), asset[:PacketSize+7]...)
	done, carry := rewritePID(partial, 0x1FF)
	if len(done) != PacketSize {
		t.Fatalf("rewritePID returned %d whole bytes, want one packet", len(done))
	}
	if len(carry) != 7 {
		t.Fatalf("rewritePID carried %d bytes, want the 7 that are not yet a packet", len(carry))
	}
}
