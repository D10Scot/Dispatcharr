// Package channel owns a channel's lifecycle: ownership, the state machine,
// the switch coordination between the HTTP handlers and the channel's own
// goroutine, and the client registry.
//
// Empty at 2c-1. 2c-2 brings the first real type.
//
// WHAT THIS PACKAGE DELIBERATELY DOES NOT CONTAIN, because the Python relay's
// equivalents are deleted rather than ported (spec D2):
//
//   - No ownership lease. One relay process per host by construction, so
//     there is never a second writer to fence against. live:channel:{id}:owner,
//     _ensure_owner_or_stop, release_ownership's non-atomic GET-compare-DELETE
//     and extend_ownership's non-atomic GET-EXPIRE all go. Ownership becomes
//     map[uuid]*Channel behind a sync.RWMutex.
//   - No follower path and no live:events:{id} pub/sub. Those were
//     multi-worker follower-to-owner coordination; with one owner per channel
//     by construction they have no purpose.
//   - No Redis client, and no Postgres driver. The phase's two checkable
//     invariants (spec § Stage 2c, "The two invariants"). Switch coordination
//     is a Go chan; the degraded-fallback source cache, the metadata hash, the
//     stopping flag and the timing counters are all fields on the channel
//     struct.
package channel

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// Channel is one running channel: its ring buffer, its source goroutine, its
// client count and its state.
//
// There is NO OWNERSHIP LEASE here, and that is spec D2 rather than an
// omission. One relay process per host by construction means there is never a
// second writer to fence against, so live:channel:{id}:owner,
// _ensure_owner_or_stop, release_ownership's non-atomic GET-compare-DELETE and
// extend_ownership's non-atomic GET-EXPIRE are deleted rather than ported --
// together with the follower path and live:events:{id}, which existed only to
// let a non-owning worker ask the owner to act.
type Channel struct {
	id     string
	ring   *buffer.Ring
	log    *slog.Logger
	tuning Tuning

	mu      sync.RWMutex
	state   State
	lastErr error
	clients int

	cancel context.CancelFunc
	done   chan struct{}
}

// ID is the channel uuid the control plane and every client address it by.
func (c *Channel) ID() string { return c.id }

// Ring is the channel's buffer. Readers take chunks from it directly.
func (c *Channel) Ring() *buffer.Ring { return c.ring }

// Tuning is the channel-start-time settings this channel was started with.
//
// SNAPSHOTTED AT CHANNEL START, which is parity-matrix row 5 and not an
// optimisation: Python reads its thresholds in StreamManager.__init__ and a
// proxy_settings change never reaches a running channel. Serving it from here
// is also what lets a second client attach without a next-source call, since
// the settings arrive on that answer and the second client never makes one.
func (c *Channel) Tuning() Tuning { return c.tuning }

// State is the channel's current lifecycle state.
func (c *Channel) State() State {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.state
}

// Err is the error that put the channel into StateError, or nil.
func (c *Channel) Err() error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.lastErr
}

// Clients is how many readers are attached.
func (c *Channel) Clients() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.clients
}

// Done is closed once the source goroutine has returned and the ring is shut.
func (c *Channel) Done() <-chan struct{} { return c.done }

// addClient and dropClient are the only writers of c.clients. They exist as
// methods so the manager can adjust the count while holding its own lock
// without reaching into this struct -- the lock order is always manager then
// channel, and nothing takes them the other way round.
func (c *Channel) addClient() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.clients++
}

func (c *Channel) dropClient() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.clients--
	return c.clients
}

func (c *Channel) setState(state State, err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state = state
	if err != nil {
		c.lastErr = err
	}
}

// run is the source goroutine. Exactly one per channel, started by the
// manager.
//
// It does NOT remove itself from the manager's map. Manager.claim drops a
// channel whose ring has closed, and that is the only place it happens: two
// mechanisms for one property means deleting either one changes no test,
// because the other covers for it silently.
func (c *Channel) run(ctx context.Context, source Source) {
	defer close(c.done)
	defer c.ring.Close()

	c.setState(StateWaitingForClients, nil)
	go c.promoteOnFirstChunk(ctx)
	err := source.Run(ctx, c.ring)

	switch {
	case err == nil:
		// A clean upstream EOF. Python treats this as the stream ending and
		// the channel stopping; the failover that would try the next
		// candidate instead is parity-matrix rows 1-3 and 2c-5's.
		c.log.Info("upstream ended", "channel", c.id)
		c.setState(StateStopped, nil)
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		c.log.Info("channel stopped", "channel", c.id)
		c.setState(StateStopped, nil)
	default:
		// The error is logged as-is. Every error this package builds is
		// written to carry no URL, because a provider URL carries provider
		// credentials (CLAUDE.md, § Known defects).
		c.log.Error("upstream failed", "channel", c.id, "error", err)
		c.setState(StateError, err)
	}
}

// promoteOnFirstChunk moves a channel out of waiting_for_clients the moment
// its first chunk is published, mirroring the waiting_for_clients + data ->
// active half of Python's promotion (apps/proxy/live_proxy/services/
// channel_service.py:204-240's promote_channel_when_buffer_ready): "clients"
// is not a separate condition to check here the way it is there, because a
// channel in this manager never exists without at least one attached client
// -- Manager.publish always installs the first client before starting this
// goroutine (manager.go's own doc comment on publish). No parity-matrix row
// pins this transition yet; it is one to add when a later PR builds the
// status routes that expose `state`.
//
// THIS IS THE ONLY PLACE state MOVES TO active. An earlier version called an
// equivalent method (markActive) from the manager's Attach path instead --
// on a SECOND client's arrival, never the first -- which meant a channel's
// very first (and often only) client never triggered it at all, and a
// second client's call raced run()'s own concurrent write of
// waiting_for_clients so it was usually a no-op anyway: measured by review
// at 0/300 rounds ever reaching active. Two mechanisms for one transition is
// exactly the shape CLAUDE.md's Ruling R11 warns about elsewhere in this
// package -- removing the wrong one would have changed no test. There is
// now exactly one.
//
// Runs as its own goroutine, started by run() alongside the source's copy
// loop, because Ring.Wait is the ring's only "something was published"
// signal and the copy loop itself is busy blocking on the upstream read.
func (c *Channel) promoteOnFirstChunk(ctx context.Context) {
	if err := c.ring.Wait(ctx, 0); err != nil {
		// ctx.Err(): the channel stopped before any data arrived. ErrClosed:
		// the ring closed with nothing ever published (e.g. an immediate
		// upstream failure) -- Python's equivalent returns None ("no
		// promotion applies") in both cases, never active.
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state == StateWaitingForClients {
		c.state = StateActive
	}
}

// ensure the ring satisfies io.Writer where it is used as the sink.
var _ io.Writer = (*buffer.Ring)(nil)

// stop cancels the source and waits for it, bounded by wait.
func (c *Channel) stop(wait time.Duration) {
	c.cancel()
	select {
	case <-c.done:
	case <-time.After(wait):
		c.log.Warn("source goroutine did not return in time", "channel", c.id, "waited", wait)
	}
}
