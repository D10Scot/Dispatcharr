package ffmpeg

import (
	"regexp"
	"strconv"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The whole speed field, exponent included -- what the production regex
// declines to read. The gap between the two is parity-matrix row 28.
var fullSpeedRe = regexp.MustCompile(`speed=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)x?`)

// PINS A DEFECT: issue #227, parity-matrix row 28. Do not "fix" this.
//
// The truncation capture's one record reads speed=<mantissa>e+03x on a real
// ffmpeg 8.1.2. The production regex stops at the 'e' and reports the
// mantissa, a roughly thousandfold under-report; D5 is strict parity, defects
// included, so this asserts the WRONG value. It fails if someone widens the
// character class to read the exponent, which is exactly the change that must
// not be made without changing the Python side and the row together.
func TestAScientificNotationSpeedIsUnderReportedAsItsMantissa(t *testing.T) {
	_, records := relaytest.SplitCorpus(relaytest.Corpus("truncation"))
	if len(records) != 1 {
		t.Fatalf("the truncation capture carries %d records, want exactly 1 (CAPTURE.md)", len(records))
	}
	record := string(records[0])
	actual, _ := strconv.ParseFloat(fullSpeedRe.FindStringSubmatch(record)[1], 64)
	mantissa, _ := strconv.ParseFloat(speedRe.FindStringSubmatch(record)[1], 64)
	if actual/mantissa < 100 {
		t.Fatalf("the truncation capture no longer carries a scientific-notation speed=; "+
			"re-derive this test against the new capture (CAPTURE.md): %q", record)
	}

	p, ok := ParseProgress(record)
	if !ok || p.Speed == nil {
		t.Fatalf("the record did not parse as progress: %q", record)
	}
	if *p.Speed != mantissa {
		t.Fatalf("Speed = %v, want the mantissa %v", *p.Speed, mantissa)
	}
	if *p.Speed >= actual/100 {
		t.Fatalf("the parser reported the true speed %v; #227 appears to have been fixed, "+
			"which makes this row a parity CHANGE, not a pin", *p.Speed)
	}
}

// Every shape CAPTURE.md names as one a hand-written line would have got
// wrong, against the parser: the space-padded speed, the Lsize= final record,
// the elapsed= trailer, plus the unit scaling and the actual-fps derivation.
func TestParseProgressReadsTheRealRecordShapes(t *testing.T) {
	for _, tc := range []struct {
		name         string
		line         string
		speed, fps   float64
		kbps, actual float64
	}{
		{"padded short speed", "frame=  174 fps=171 q=-1.0 size=     421KiB time=00:00:06.89 bitrate= 500.3kbits/s speed= 6.8x elapsed=0:00:01.01    ", 6.8, 171, 500.3, 171 / 6.8},
		{"three-space-padded integer speed", "frame=   12 fps=0.0 q=-1.0 size=      30KiB time=00:00:00.48 bitrate= 512.0kbits/s speed=   1x", 1, 0, 512, 0},
		{"the Lsize final record", "frame=  819 fps= 21 q=-1.0 Lsize=    2016KiB time=00:00:32.67 bitrate= 505.5kbits/s speed=0.848x elapsed=0:00:38.52    ", 0.848, 21, 505.5, 21 / 0.848},
		{"megabits are scaled to kilobits", "frame=1 fps=25 q=-1.0 size=1KiB time=00:00:00.04 bitrate=  2.5Mbits/s speed=1.0x", 1, 25, 2500, 25},
		{"gigabits too", "frame=1 fps=25 q=-1.0 size=1KiB time=00:00:00.04 bitrate=  1.5Gbits/s speed=2x", 2, 25, 1_500_000, 12.5},
	} {
		t.Run(tc.name, func(t *testing.T) {
			p, ok := ParseProgress(tc.line)
			if !ok {
				t.Fatalf("did not parse: %q", tc.line)
			}
			if p.Speed == nil || *p.Speed != tc.speed {
				t.Errorf("Speed = %v, want %v", deref(p.Speed), tc.speed)
			}
			if p.FPS == nil || *p.FPS != tc.fps {
				t.Errorf("FPS = %v, want %v", deref(p.FPS), tc.fps)
			}
			if p.OutputBitrateKbps == nil || *p.OutputBitrateKbps != tc.kbps {
				t.Errorf("OutputBitrateKbps = %v, want %v", deref(p.OutputBitrateKbps), tc.kbps)
			}
			if tc.actual == 0 {
				// fps=0.0 with a positive speed still divides: 0/1 = 0,
				// and Python computes it (actual_fps = 0/1.0 = 0.0).
				if p.ActualFPS == nil || *p.ActualFPS != 0 {
					t.Errorf("ActualFPS = %v, want 0", deref(p.ActualFPS))
				}
				return
			}
			if p.ActualFPS == nil || *p.ActualFPS != tc.actual {
				t.Errorf("ActualFPS = %v, want %v", deref(p.ActualFPS), tc.actual)
			}
		})
	}
}

// A captured number that float() would refuse drops the WHOLE line, as
// input/manager.py:1249's except does -- not the one field. "1.2.3" is what
// `[0-9.]+` captures from a corrupted record; a partial parse would feed the
// buffering detector a speed Python never saw.
func TestAnUnparseableNumberDropsTheWholeRecord(t *testing.T) {
	if p, ok := ParseProgress("frame=1 fps=25 q=-1.0 bitrate= 500kbits/s speed=1.2.3x"); ok {
		t.Fatalf("a record with speed=1.2.3x parsed as %+v; Python drops the line", p)
	}
	// The frame= gate is the CALLER's (input/manager.py:993 and :1017
	// check it before calling _parse_ffmpeg_stats), which is why it is a
	// separate predicate rather than folded into ParseProgress.
	if IsProgressLine("fps=25 speed=1.0x") {
		t.Fatal("a line without frame= is not a progress record (input/manager.py:993)")
	}
	if !IsProgressLine("frame=  150 fps=0.0 q=-1.0 speed=11.5x") {
		t.Fatal("a frame= line is a progress record")
	}
	if _, ok := ParseProgress("frame=1 q=-1.0"); ok {
		t.Fatal("a frame= line carrying none of the three fields parsed as progress")
	}
}

// Round is Python's round(): correctly rounded on the exact binary value.
// Every expected value below was produced by `python3 -c 'print(round(x, n))'`
// rather than reasoned about, because the two examples that look like ties
// are not: 2.675 is 2.67499999... in binary and rounds DOWN, and 1.0005 is
// 1.00049999... and rounds DOWN, where 0.0005 is 0.00050000000000000001 and
// rounds UP. A naive math.Round(x*1000)/1000 gets 1.0005 wrong.
func TestRoundMatchesPythonsRound(t *testing.T) {
	for _, tc := range []struct {
		x      float64
		places int
		want   float64
	}{
		{0.8485, 3, 0.849},
		{11.5, 3, 11.5},
		{2.675, 2, 2.67},
		{0.5, 0, 0}, // ties to even
		{1.5, 0, 2},
		{171.0 / 6.8, 1, 25.1},
		{499.4, 1, 499.4},
		{0.0005, 3, 0.001},
		{1.0005, 3, 1.0},
	} {
		if got := Round(tc.x, tc.places); got != tc.want {
			t.Errorf("Round(%v, %d) = %v, want %v", tc.x, tc.places, got, tc.want)
		}
	}
}

func deref(p *float64) any {
	if p == nil {
		return nil
	}
	return *p
}
