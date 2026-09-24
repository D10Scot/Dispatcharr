package relaytest

import "testing"

// Issue #227, the test-support half. CorpusSpeeds quotes the shipped parser's
// speed regex by copy, so the copy has to read the truncation capture's
// exponent exactly as package ffmpeg now does; a copy left at `[0-9.]+`
// would hand every caller the mantissa, about a thousandth of the value,
// while the parser under test reads the whole of it.
func TestCorpusSpeedsReadsAScientificNotationSpeedWhole(t *testing.T) {
	speeds := CorpusSpeeds("truncation")
	if len(speeds) != 1 {
		t.Fatalf("the truncation capture carries %d records, want exactly 1 (CAPTURE.md)", len(speeds))
	}
	if speeds[0] < 100 {
		t.Fatalf("CorpusSpeeds read the truncation record as %v, its mantissa: the copied regex has fallen behind package ffmpeg's (#227)", speeds[0])
	}
}
