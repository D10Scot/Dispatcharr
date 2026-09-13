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
