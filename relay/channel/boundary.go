package channel

import "sync"

// maxBoundaries is how many source boundaries a channel remembers. A
// generation needs only the first boundary after its own start, and the ring
// holds at most 300 chunks (relay/buffer), so a boundary older than the
// oldest chunk can never be asked for again. Sixty-four is far more
// connections than a 60-second ring can span and costs 512 bytes.
const maxBoundaries = 64

// boundaryLog is the channel's record of where each upstream connection's
// bytes begin in the ring (Phase 4 spec, D10): "a boundary is every new
// upstream connection: an applySwitch, or a reconnect of the same URL. The
// channel records the ring index of the boundary's first chunk."
//
// It is embedded in Channel, as outputRegistry is, with a mutex of its own:
// the run loop writes it and relay/hls's generation writers read it, and
// neither should contend with mu, which guards the client registry and the
// switch bookkeeping.
//
// NOTHING IN THIS MODULE READS IT YET. Phase 4a-1a lands the record and
// relay/hls, which asks NextBoundary, unlinked; 4a-1b wires the two
// together. Recording costs one mutex and one append per connection attempt.
type boundaryLog struct {
	boundaryMu sync.Mutex
	// boundaries is strictly increasing: an attempt that published nothing
	// leaves the ring's head where it was, so the next attempt's boundary is
	// the same index and is not recorded twice.
	boundaries []uint64
}

// markBoundary records that a new upstream connection is about to write, at
// the index buffer.Ring.MarkBoundary returns. Called by runAttempt, on the
// run goroutine, before the Source runs -- so the index is on record before
// the first chunk at it can be published, which is what lets a reader that
// has seen that chunk trust NextBoundary to report it.
func (c *Channel) markBoundary() {
	index := c.ring.MarkBoundary()
	c.boundaryMu.Lock()
	defer c.boundaryMu.Unlock()
	if n := len(c.boundaries); n > 0 && c.boundaries[n-1] >= index {
		return
	}
	c.boundaries = append(c.boundaries, index)
	if len(c.boundaries) > maxBoundaries {
		c.boundaries = append(c.boundaries[:0], c.boundaries[len(c.boundaries)-maxBoundaries:]...)
	}
}

// NextBoundary is the first source boundary strictly after the ring index
// after, and false when there is none yet. A boundary is the index of the
// first chunk a new upstream connection published (or will publish).
func (c *Channel) NextBoundary(after uint64) (uint64, bool) {
	c.boundaryMu.Lock()
	defer c.boundaryMu.Unlock()
	for _, index := range c.boundaries {
		if index > after {
			return index, true
		}
	}
	return 0, false
}
