package session

import "time"

const (
	// ResumeWindow is how long a DEPARTED session may resume, and how long a
	// STOPPED one is kept unrequested before it is forgotten.
	ResumeWindow = 300 * time.Second

	// SweepInterval is the process-wide sweeper's tick.
	SweepInterval = time.Second

	// minIdleTimeout is the idle timeout's floor.
	minIdleTimeout = 12 * time.Second
)

// IdleTimeout is how long an ACTIVE session may go with no request in flight
// before the sweep departs it: max(12 s, 6 x TARGETDURATION) (spec § Presence
// thresholds). Six target durations is what a well-behaved player needs to
// reload a stalled playlist a few times; the 12 s floor is what one at
// TARGETDURATION 2 gets, and is what keeps a slow-network player from being
// departed between two healthy reloads.
func IdleTimeout(td time.Duration) time.Duration {
	return max(minIdleTimeout, 6*td)
}

// SilentAfter is how long an ACTIVE session may go with nothing in flight
// before a blocked tune may take its channel back: 2 x TARGETDURATION (spec
// § Presence thresholds, D16). Silent is STRICTLY MORE than this, measured from
// the end of the session's last request: 4 s at TD 2, well inside M7's 2 s
// reload cadence for a paused AVPlayer, and 12 s at TD 6.
func SilentAfter(td time.Duration) time.Duration { return 2 * td }

// BehindLiveAfter is how far behind the newest segment a served media segment
// must be for its session to count as behind live: 5 x TARGETDURATION, 10 s at
// TD 2 (spec § Presence thresholds, Phase 4a-3). A viewer that far back is
// watching the rewind window, and stopping without a leave holds its channel
// for the behind-live grace. Behind live is STRICTLY more than this.
func BehindLiveAfter(td time.Duration) time.Duration { return 5 * td }
