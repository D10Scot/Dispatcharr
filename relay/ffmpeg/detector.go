package ffmpeg

import "time"

// Detector is the buffering state machine of input/manager.py:1165-1247,
// lifted out of _parse_ffmpeg_stats so it can be driven with an injected
// clock. It decides nothing about what happens on a timeout: Python calls
// _try_next_stream() there (parity-matrix row 1, 2c-5's), and the source
// that owns this detector decides what a TimedOut verdict means for it.
//
// THRESHOLDS ARE SNAPSHOTTED BY THE CALLER, not read here: Python reads
// buffering_speed and buffering_timeout once in StreamManager.__init__
// (input/manager.py:61-62, parity-matrix row 5), and this struct is built
// once per source with the values that tune's next-source answer carried.
type Detector struct {
	// Threshold is buffering_speed: a reported speed strictly below it is
	// buffering (input/manager.py:1166's `<`), at or above it is not
	// (:1235's `>=`).
	Threshold float64

	// Timeout is buffering_timeout: buffering sustained for LONGER than this
	// (:1178's `>`) is a timeout.
	Timeout time.Duration

	// Now is the clock. Nil means time.Now.
	Now func() time.Time

	buffering bool
	since     time.Time
}

// Verdict is what one observation changed.
type Verdict int

// The five verdicts. Continuing and Started both mean "the channel is
// buffering now" -- Python writes the BUFFERING state on every sub-threshold
// sample (:1232-1234), not only the first -- and are told apart because the
// first is when Python raises the channel_buffering event (:1217-1226).
const (
	// Steady: speed at or above the threshold, and it already was.
	Steady Verdict = iota
	// Started: the first sub-threshold sample after being fine.
	Started
	// Continuing: a further sub-threshold sample, within the timeout.
	Continuing
	// TimedOut: a sub-threshold sample more than Timeout after buffering
	// started. Python tries the next stream here; on success it resets
	// (Reset), on failure it stays buffering and tries again on the NEXT
	// sample (:1210), so this verdict repeats until something resets it.
	TimedOut
	// Ended: speed back at or above the threshold after buffering.
	Ended
)

func (v Verdict) String() string {
	switch v {
	case Steady:
		return "steady"
	case Started:
		return "buffering started"
	case Continuing:
		return "buffering"
	case TimedOut:
		return "buffering timeout"
	case Ended:
		return "buffering ended"
	}
	return "unknown"
}

// Observe feeds one reported speed to the detector.
func (d *Detector) Observe(speed float64) Verdict {
	now := d.Now
	if now == nil {
		now = time.Now
	}
	if speed < d.Threshold {
		if !d.buffering {
			d.buffering = true
			d.since = now()
			return Started
		}
		// input/manager.py:1174-1175's `if buffering_start_time is None`
		// arm is unreachable: the two are set together at :1213-1214 and
		// cleared together at :1185-1186 and :1240-1241. Not ported.
		if now().Sub(d.since) > d.Timeout {
			return TimedOut
		}
		return Continuing
	}
	if d.buffering {
		d.buffering = false
		d.since = time.Time{}
		return Ended
	}
	return Steady
}

// Buffering reports whether the last observation left the channel buffering.
func (d *Detector) Buffering() bool { return d.buffering }

// Reset is the successful-switch branch (:1185-1186): buffering cleared and
// the clock forgotten, so the NEXT sub-threshold sample starts a fresh
// window. 2c-5's failover calls it; nothing in 2c-4 does.
func (d *Detector) Reset() {
	d.buffering = false
	d.since = time.Time{}
}
