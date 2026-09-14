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
	"sort"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// ErrDuplicateClient is returned by Attach when the channel already has a
// client registered under this id.
//
// The port of client_manager.py:218-221, whose add_client returns False for an
// id already in _registered_clients; views.py:748-753 turns that False into a
// 503. One process means one registry, so what Python enforces per worker is
// enforced outright here.
var ErrDuplicateClient = errors.New("channel: a client with this id is already attached")

// SourceInfo is what the next-source answer said about the stream this channel
// is playing, kept so the status endpoints can render it without a second
// control-plane call. The fields are exactly the ones
// ChannelStatus.get_basic_channel_info reads out of the metadata hash.
type SourceInfo struct {
	// URL is the provider URL. It reaches the /proxy/relay/channels payload
	// because channel_status.py:472 puts it there and the Stats page shows it;
	// that surface is internal and HMAC-authenticated. It must never reach a
	// log line or a public response body.
	URL string

	// StreamProfileID is rendered as a STRING, because the metadata hash stores
	// str(source["stream_profile"]["id"]) (input/manager.py:2165) and the
	// serializer declares CharField.
	StreamProfileID int

	StreamID       int
	StreamName     string
	ChannelName    string
	M3UProfileID   int
	M3UProfileName string
}

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
	id        string
	ring      *buffer.Ring
	log       *slog.Logger
	tuning    Tuning
	source    SourceInfo
	startedAt time.Time

	mu      sync.RWMutex
	state   State
	lastErr error
	// clients is the registry. Guarded by mu; the manager reads its length
	// through Clients() inside its own critical section, which is what makes
	// stopIfStillIdle's re-check and claim's addClient mutually exclusive.
	clients map[string]*Client

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
//
// Never capped, matching channel_status.py:461's SCARD: the LIST is capped at
// ten without ?clients=all, the COUNT never is. The manager calls this inside
// its own lock (stopIfStillIdle), so it must never take m.mu itself.
func (c *Channel) Clients() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.clients)
}

// Done is closed once the source goroutine has returned and the ring is shut.
func (c *Channel) Done() <-chan struct{} { return c.done }

// addClient and dropClient are the only writers of c.clients. They exist as
// methods so the manager can adjust the count while holding its own lock
// without reaching into this struct -- the lock order is always manager then
// channel, and nothing takes them the other way round.
func (c *Channel) addClient(cl *Client) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, taken := c.clients[cl.ID]; taken {
		return false
	}
	c.clients[cl.ID] = cl
	return true
}

// dropClient removes one client and reports how many remain.
func (c *Channel) dropClient(id string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.clients, id)
	return len(c.clients)
}

// ClientSnapshot is every attached client, oldest connection first and ties
// broken by id.
//
// DETERMINISTIC ORDER, where Python's is arbitrary: channel_status.py:533 reads
// a Redis SET with SMEMBERS and slices the first ten of whatever order that
// returned, so no order is the contract and any deterministic one is parity. It
// is deterministic here because a golden-file comparison against the Python
// serializer needs it to be, and because "the ten clients the list shows" being
// a stable set is strictly better than a set that reshuffles between polls.
func (c *Channel) ClientSnapshot() []Client {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := make([]Client, 0, len(c.clients))
	for _, cl := range c.clients {
		out = append(out, *cl)
	}
	sort.Slice(out, func(i, j int) bool {
		if !out[i].ConnectedAt.Equal(out[j].ConnectedAt) {
			return out[i].ConnectedAt.Before(out[j].ConnectedAt)
		}
		return out[i].ID < out[j].ID
	})
	return out
}

// Source is what the next-source answer said about this channel's stream.
func (c *Channel) Source() SourceInfo { return c.source }

// StartedAt is when the channel was published.
func (c *Channel) StartedAt() time.Time { return c.startedAt }

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
		// The error is logged through redact.Error rather than as-is: every
		// error this package builds is already written to carry no URL
		// (CLAUDE.md, § Known defects), but this is also the one log call
		// relay/internal/credlint's static check can see, so it is the
		// enforcement point, not just a restatement of the rule.
		c.log.Error("upstream failed", "channel", c.id, "error", redact.Error(err))
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
