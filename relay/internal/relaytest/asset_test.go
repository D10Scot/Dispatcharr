package relaytest

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

// THE CROSS-IMPLEMENTATION PIN. This digest was produced by the PYTHON
// harness's synthetic_ts() -- apps/proxy/live_proxy/tests/harness/asset.py --
// not by the Go above it, so it proves the two implementations agree rather
// than that this one is deterministic (hollow shape 1). Regenerate it with the
// snippet in this PR's Task, never by running the Go.
//
// It is what makes a differential test possible at all: drive the Python relay
// and the Go relay from the same bytes and compare what each client receives.
func TestSyntheticTSMatchesThePythonHarness(t *testing.T) {
	const want = "e565411f3bbe6d0ab88a4dcd45d9e2a9ca1f65e049846dc5f61a2ec162f57f89"
	data := SyntheticTS(512, 0x100)
	if len(data) != 96256 {
		t.Fatalf("SyntheticTS(512, 0x100) is %d bytes, want 96256", len(data))
	}
	sum := sha256.Sum256(data)
	if got := hex.EncodeToString(sum[:]); got != want {
		t.Fatalf("SyntheticTS(512, 0x100) hashes to %s, want %s -- the Go asset has "+
			"diverged from harness/asset.py's synthetic_ts()", got, want)
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

// Global Constraint 8's ratchet, found missing by review: NominalByteRate and
// WriteChunk named a file with no line and nothing asserted them.
// apps/proxy/live_proxy/tests/harness/upstream.py:29 (NOMINAL_BYTE_RATE) and
// :31 (_WRITE_CHUNK) are what these mirror, verified against this tree.
func TestNominalByteRateAndWriteChunkMatchThePythonHarness(t *testing.T) {
	if NominalByteRate != 250000 {
		t.Errorf("NominalByteRate = %d, want 250000 (apps/proxy/live_proxy/tests/harness/upstream.py:29)",
			NominalByteRate)
	}
	if WriteChunk != 9400 {
		t.Errorf("WriteChunk = %d, want 9400 (apps/proxy/live_proxy/tests/harness/upstream.py:31)", WriteChunk)
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
