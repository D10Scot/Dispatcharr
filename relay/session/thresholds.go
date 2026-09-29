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
