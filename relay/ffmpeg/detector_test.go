package ffmpeg

import (
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// A clock the test advances by hand, so a fifteen-second timeout costs no
// wall clock and the "more than" at input/manager.py:1178 can be tested at
// the boundary.
type clock struct{ at time.Time }

func (c *clock) now() time.Time { return c.at }
func (c *clock) tick(d time.Duration) {
	c.at = c.at.Add(d)
}

func newDetector(c *clock, threshold float64, timeout time.Duration) *Detector {
	return &Detector{Threshold: threshold, Timeout: timeout, Now: c.now}
}

// The transitions of input/manager.py:1165-1247, one observation at a time.
// The threshold is 2.0 and the timeout 15s: NOT the defaults (1.0 and 15s
// together would let a detector that ignored Threshold and compared against a
// hard-coded 1.0 pass), so every comparison below is against a value the
// wire supplied.
func TestTheDetectorFollowsPythonsTransitions(t *testing.T) {
	c := &clock{at: time.Unix(1_789_000_000, 0)}
	d := newDetector(c, 2.0, 15*time.Second)

	if v := d.Observe(2.0); v != Steady {
		t.Fatalf("speed AT the threshold is not buffering (:1235's >=): got %s", v)
	}
	if v := d.Observe(5.0); v != Steady {
		t.Fatalf("a fast sample is steady: got %s", v)
	}
	if v := d.Observe(1.99); v != Started {
		t.Fatalf("the first sub-threshold sample starts buffering: got %s", v)
	}
	c.tick(15 * time.Second)
	if v := d.Observe(1.5); v != Continuing {
		t.Fatalf("exactly the timeout later is NOT a timeout (:1178's strict >): got %s", v)
	}
	c.tick(time.Millisecond)
	if v := d.Observe(1.5); v != TimedOut {
		t.Fatalf("more than the timeout later is a timeout: got %s", v)
	}
	// Python's failed-switch branch: nothing resets, so the next sample
	// times out again.
	if v := d.Observe(1.5); v != TimedOut {
		t.Fatalf("a further sample after an unhandled timeout times out again: got %s", v)
	}
	if v := d.Observe(2.0); v != Ended {
		t.Fatalf("recovering to the threshold ends buffering: got %s", v)
	}
	if d.Buffering() {
		t.Fatal("Buffering() still true after Ended")
	}
	if v := d.Observe(1.0); v != Started {
		t.Fatalf("a fresh dip starts a FRESH window, not a continuation of the old one: got %s", v)
	}
	c.tick(10 * time.Second)
	if v := d.Observe(1.0); v != Continuing {
		t.Fatalf("ten seconds into the fresh window is not a timeout: got %s", v)
	}
	d.Reset()
	if d.Buffering() {
		t.Fatal("Reset left the detector buffering")
	}
	if v := d.Observe(1.0); v != Started {
		t.Fatalf("after Reset (a successful switch) the next dip starts over: got %s", v)
	}
}

// Parity-matrix row 4's invariant on the captured curve: the detector never
// says "buffering" while the speed it was handed is at or above the
// threshold. Driven from the slow-trickle capture, whose speed= opens above
// 10x against a 0.25x upstream and crosses below 1.0 only after tens of
// seconds of real ffmpeg wall clock -- the cumulative-average delay that is
// ffmpeg's own behaviour, invisible in the Python and visible only in a real
// capture. The real-ffmpeg half of row 4 is channel's
// TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms; this is the half
// that costs no wall clock.
func TestTheCapturedLeadIsNeverCalledBufferingBeforeItCrosses(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("slow-trickle")
	const threshold = 1.0 // proxy_settings' default buffering_speed; the corpus was captured against it
	crossing := -1
	for idx, v := range speeds {
		if v < threshold {
			crossing = idx
			break
		}
	}
	if crossing <= 0 {
		t.Fatalf("slow-trickle no longer opens above %v and crosses below it (crossing at %d); re-derive (CAPTURE.md)", threshold, crossing)
	}
	if elapsed := relaytest.CorpusElapsed("slow-trickle", crossing); elapsed < 10 {
		t.Fatalf("the capture's own wall clock to the crossing is %.1fs, under ten seconds; "+
			"re-derive -- row 4's claim is that this delay is tens of seconds", elapsed)
	}

	c := &clock{at: time.Unix(1_789_000_000, 0)}
	d := newDetector(c, threshold, 300*time.Second)
	for idx, v := range speeds {
		verdict := d.Observe(v)
		c.tick(500 * time.Millisecond) // ffmpeg's own progress cadence
		buffering := verdict == Started || verdict == Continuing || verdict == TimedOut
		if v >= threshold && buffering {
			t.Fatalf("record %d: the detector armed while the speed was still %vx (>= %v)", idx, v, threshold)
		}
		if idx < crossing && buffering {
			t.Fatalf("record %d, before the crossing at %d: buffering %s", idx, crossing, verdict)
		}
		if idx == crossing && verdict != Started {
			t.Fatalf("record %d is the crossing (%vx) and the verdict is %s, want %s", idx, v, verdict, Started)
		}
	}
	if !d.Buffering() {
		t.Fatal("the capture ends below the threshold, so the detector must end buffering")
	}
}
