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
	"math"
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
	startedAt time.Time
	now       func() time.Time

	// budgetBytes is the ring's own byte budget, kept so an output pipeline's
	// fragment buffer can be sized from the same number rather than from a
	// second copy of the manager's config (2c-6).
	budgetBytes int

	// outputRegistry is 2c-6's: the fMP4 remux and, from 2c-7, the Output
	// Profile transcodes. Its own mutex, never nested with mu -- see
	// output.go's lock-order note.
	outputRegistry

	// outputProfiles is the active OutputProfile set as the control plane
	// last described it, under mu. REPLACED WHOLESALE, never mutated in
	// place, so OutputProfiles() can hand its map out without copying it.
	outputProfiles OutputProfiles
	// channelName is StreamManager.channel_name: resolved once at construction
	// (input/manager.py:41-44) and carried on every event, unchanged by a
	// failover -- the SourceInfo's name can move, this one does not.
	channelName string

	// resolver, events and release are the channel's three ways of reaching
	// the control plane, handed in by the manager (release) and the tune
	// (resolver) and never touched again. Nil resolver means no failover;
	// events is never nil.
	resolver Resolver
	events   EventSink
	release  func(id string, info SourceInfo)
	// ctx is the channel's own context, for the stderr reader's failover,
	// which has no context of its own to make the control-plane call with.
	ctx context.Context

	mu      sync.RWMutex
	state   State
	lastErr error
	// stateChangedAt is ChannelMetadataField.STATE_CHANGED_AT, set by
	// setState on every transition.
	stateChangedAt time.Time
	// source is what the channel is playing NOW. Guarded by mu since 2c-5,
	// because a failover rewrites it (input/manager.py:2160-2171's hset).
	source SourceInfo
	// stats is what a transcode process has reported (stats.go). Empty for
	// the Proxy architecture, which spawns nothing -- parity-matrix row 29.
	stats Stats
	// clients is the registry. Guarded by mu; the manager reads its length
	// through Clients() inside its own critical section, which is what makes
	// stopIfStillIdle's re-check and claim's addClient mutually exclusive.
	clients map[string]*Client

	// The health monitor's view (health.go), all under mu: StreamManager's
	// healthy, connected, last_data_time and connection_start_time, and the
	// two recovery flags it raises for the run loop. url_switching is NOT
	// here: the one thing that read it, _is_timeout's exemption, is not
	// ported (the 2c-5 plan's Ruling R14).
	healthy        bool
	connected      bool
	lastData       time.Time
	connStart      time.Time
	needsReconnect bool
	needsSwitch    bool
	// cancelAttempt ends the attempt currently running, so the health monitor
	// and the stderr reader can make the run loop act now rather than at the
	// next read. Nil between attempts.
	cancelAttempt context.CancelFunc

	// The switch bookkeeping (failover.go): tried_stream_ids,
	// current_stream_id, _failover_degraded, and the source a
	// buffering-triggered switch has adopted and parked for the run loop.
	// tried and currentStreamID are under mu; switchMu serialises failover
	// itself, whose control-plane call must not hold mu.
	switchMu         sync.Mutex
	tried            map[int]bool
	currentStreamID  int
	failoverDegraded bool
	pending          *Resolved
	failures         failureCounter
	// switches is stream_switch_attempts: the switches made since the
	// rotation last reset, bounded by Tuning.MaxStreamSwitches. A channel
	// field under mu rather than a run-loop local since issue #221's fix,
	// because the stderr reader's buffering switch counts against it too.
	switches int

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
	// The counters and the stop signal are installed HERE rather than by the
	// caller, so a Client that reached the registry always has both and one
	// that did not has neither: Sent, Touch and Stats are no-ops on a nil
	// meter, and Stopped() on a nil channel blocks for ever, which is the
	// right answer for a client nothing can stop.
	cl.meter = newClientMeter(cl.ConnectedAt)
	cl.stop = make(chan struct{})
	c.clients[cl.ID] = cl
	return true
}

// StopClient signals one client to disconnect: ChannelService.stop_client's
// stop key (services/channel_service.py:665-673), which the generator's loop
// polls and answers by returning.
//
// IT DOES NOT REMOVE THE CLIENT FROM THE REGISTRY, deliberately. The serving
// goroutine's deferred release is the one mechanism by which a client leaves
// (Global Constraint 18), and removing it here would be a second one --
// which matters more than it sounds, because release is also what decides
// whether the channel was left idle. Python removes it here AND lets the
// generator's own cleanup remove it again (`if self.client_id in
// client_manager.clients`, output/ts/generator.py:643), so the registry is
// the same shape either way; only the number of mechanisms differs.
//
// Reports whether a client of that id was registered, which is
// stop_client's locally_processed.
func (c *Channel) StopClient(id string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	cl, registered := c.clients[id]
	if !registered || cl.stop == nil {
		return false
	}
	select {
	case <-cl.stop:
		// Already signalled. Closing twice panics, and a second DELETE for
		// the same client is an ordinary thing for an admin to do.
	default:
		close(cl.stop)
	}
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

// OutputProfiles is the active OutputProfile set from the most recent
// next-source answer this channel received.
//
// PER CHANNEL, NOT PER CLIENT, and that is 2b-2's Ruling R3 rather than a
// simplification here: next-source runs once per channel while Python resolves
// the profile once per client (views.py:605 and :712 re-read the row), so the
// whole active set travels on every answer and the relay serves every later
// client from this copy. The divergence that leaves is stated in the 2c-7
// plan's Ruling R5 and is bounded by the refresh below: a profile edited
// between two next-source calls reaches a new client only after the next one.
//
// The returned map is the one the channel holds. It is never mutated in place
// -- setOutputProfiles replaces it -- so a reader that keeps it keeps a
// consistent snapshot.
func (c *Channel) OutputProfiles() OutputProfiles {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.outputProfiles
}

// SetClientOutputProfile records which Output Profile this client is actually
// being served under, once the handler has resolved it against the set above.
//
// A SECOND WRITE RATHER THAN A LATER FIRST ONE, because the resolution needs
// the channel and Attach is what creates it: identify() records the id the
// authorize hop asked for, and this corrects it to null on the one path where
// the two differ -- a profile deactivated between the hop and the tune, which
// Python reproduces by re-reading the row with is_active=True and getting None
// (views.py:150-155), then registering the client with that None
// (views.py:751).
func (c *Channel) SetClientOutputProfile(clientID string, profileID *int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if client, attached := c.clients[clientID]; attached {
		client.OutputProfileID = profileID
	}
}

// Resolver is the channel's own resolver, the one its tune built. Exported
// so the operator-switch handler can reuse the SAME source builder the tune
// and every failover use, rather than assembling a second one out of the
// request: Python's update_url keeps the manager's own transcode flag and
// stream profile across a switch (input/manager.py:1462-1540), so a second
// builder here would be free to disagree with it.
//
// Nil for a channel with no failover, which is a test shape.
func (c *Channel) Resolver() Resolver { return c.resolver }

// Source is what the next-source answer said about this channel's stream --
// the CURRENT one, after any failover.
func (c *Channel) Source() SourceInfo {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.source
}

// StartedAt is when the channel was published.
func (c *Channel) StartedAt() time.Time { return c.startedAt }

func (c *Channel) setState(state State, err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if state != c.state {
		// state_changed_at (ChannelMetadataField.STATE_CHANGED_AT), written
		// beside every state hset and read by the detail endpoint
		// (channel_status.py:124-127). On a CHANGE only: Python writes the
		// pair together, so a re-assertion of the same state moves it there
		// too -- but every Python writer asserts a state it is entering,
		// never one it is already in, so the two agree on every reachable
		// path and this guard makes the field mean what its name says.
		c.stateChangedAt = c.now()
	}
	c.state = state
	if err != nil {
		c.lastErr = err
	}
}

// StateChangedAt is when State last changed, for the detail endpoint's
// state_changed_at and state_duration (channel_status.py:124-127).
func (c *Channel) StateChangedAt() time.Time {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.stateChangedAt
}

// Local is the detail endpoint's local_manager block
// (channel_status.py:315-322): the four StreamManager fields the answering
// process can only report because it holds the manager. This relay always
// holds it for a channel in its map, so the block is never absent here where
// Python omits it on a non-owning worker.
type Local struct {
	Healthy   bool
	Connected bool
	LastData  time.Time
}

// Local is a snapshot of those four fields.
func (c *Channel) Local() Local {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return Local{Healthy: c.healthy, Connected: c.connected, LastData: c.lastData}
}

// attachable is the optional interface a Source implements to be handed the
// channel it runs on, for stats and state. TranscodeSource does; ProxySource
// has nothing to report and does not. Checked once, in run, so a source is
// attached to exactly the channel whose goroutine runs it.
type attachable interface{ attach(*Channel) }

// run is the channel's supervisor goroutine, the port of StreamManager.run
// (input/manager.py:384-709). Exactly one per channel, started by the
// manager.
//
// THE SHAPE IS PYTHON'S, loop for loop. The outer loop is one source at a
// time and is bounded by MaxStreamSwitches; the inner loop is one attempt at
// a time on that source and is bounded by MaxRetries. An attempt is one
// Source.Run: it ends on a clean EOF, an error, or a cancellation the health
// monitor or the stderr reader asked for. EVERY end that is not a stop is a
// connection failure, a clean EOF included -- "Server closed connection",
// :1870-1875 -- counted and retried with backoff (:555-563), until the
// counter reaches MaxRetries and the source is exhausted (:534-537,
// parity-matrix row 3), at which point the resolver is asked for the next
// one (:596-611). The health monitor's switch request is honoured after the
// attempt it ended (:505-507, :428-438); its RECONNECT request is cleared
// inside the inner loop and falls through to the failure accounting
// (:521-534), so the reconnect is simply the next attempt on the same URL.
// The outer loop's own reconnect branch (:414-426, _attempt_reconnect) is
// NOT ported, because it is unreachable in Python: the monitor sets the flag
// only while connected (:1565), and :527 clears it on every pass of the
// inner loop before the outer loop's top can see it. The stderr reader's
// buffering switch is adopted between attempts too (failover.go). Out of
// sources, the channel ends in error naming the count (:678-682).
//
// It does NOT remove itself from the manager's map. Manager.claim drops a
// channel whose ring has closed, and that is the only place it happens: two
// mechanisms for one property means deleting either one changes no test,
// because the other covers for it silently.
func (c *Channel) run(ctx context.Context, first Source) {
	defer c.releaseSlot()
	defer close(c.done)
	// BEFORE close(c.done), and that ordering is load-bearing: stop() returns
	// the moment done closes, so an emit after it would race the SIGTERM
	// drain's own emitter flush and lose the last channel_stop of a
	// shutdown -- the one it most matters to keep.
	defer c.emitStop()
	defer c.ring.Close()
	// stop_all_output_formats (server.py:1771), in the one place a channel
	// ends. Deferred calls run last-in first-out, so this runs BEFORE the ring
	// closes: a remux still draining the ring sees its stop the way any stopped
	// one does rather than racing the close.
	defer c.stopOutputs()

	c.setState(StateWaitingForClients, nil)
	go c.promoteOnFirstChunk(ctx)
	go c.monitorHealth(ctx)

	source := first
	var last error
	for ctx.Err() == nil && c.switchCount() <= c.tuning.MaxStreamSwitches {
		urlFailed := false
		for ctx.Err() == nil && c.failures.count < c.tuning.MaxRetries && !urlFailed && !c.flagSet(&c.needsSwitch) {
			attempt := c.failures.count + 1
			if attempt > 1 {
				// :486-496, on a retry. Python raises it once the connection
				// is established; a Source has no such moment, so it is
				// raised as the attempt starts -- a transcode spawn that
				// fails at once will have announced a reconnect it never
				// made, which Python would not have. Stated, not hidden.
				c.emit("channel_reconnect", map[string]any{"attempt": attempt, "max_attempts": c.tuning.MaxRetries})
			}
			c.log.Info("connection attempt", "channel", c.id, "attempt", attempt, "max", c.tuning.MaxRetries)

			startedAt := c.now()
			err := c.runAttempt(ctx, source)
			if ctx.Err() != nil {
				break
			}
			if resolved := c.takePending(); resolved != nil {
				// The stderr reader switched on a buffering timeout
				// (:1178-1211) and has already cleared the failure history,
				// as update_url does, and counted the switch (issue #221,
				// row 6) -- or an operator's Advance parked it, which is
				// not counted.
				source = resolved.Source
				break
			}
			if c.flagSet(&c.needsSwitch) {
				// :505-507: leave for the switch without counting a failure.
				c.log.Info("stream needs to switch", "channel", c.id, "after", c.now().Sub(startedAt).Round(100*time.Millisecond))
				break
			}
			if duration := c.now().Sub(startedAt); duration >= c.tuning.StableThreshold {
				// :508-513: a stable run resets the rotation.
				c.log.Info("stream was stable; resetting the switch rotation", "channel", c.id, "duration", duration.Round(time.Second))
				c.noteStable()
				c.resetSwitches()
			}
			if c.takeFlag(&c.needsReconnect) {
				// :521-531: the monitor asked for a same-URL reconnect on a
				// stream that had been stable. The flag is CLEARED HERE, on
				// every pass, and the attempt it ended falls through to the
				// failure accounting below -- "Repeated health reconnects
				// count toward max_retries like any other URL failure" -- so
				// the reconnect is the next attempt, announced by the
				// channel_reconnect above like any retry. Clearing it
				// anywhere else leaves the monitor's own `if not
				// needs_reconnect` guard (:1581) shut, and a second stall on
				// the same stream is never acted on; the 2c-5 plan's
				// reviewer reproduced exactly that against an earlier shape
				// of this loop.
				c.log.Info("health monitor requested reconnect", "channel", c.id)
			}

			if err == nil {
				err = errUpstreamEnded
			}
			last = err
			failures := c.failures.record()
			if failures >= c.tuning.MaxRetries {
				urlFailed = true
				c.log.Warn("maximum retry attempts reached for this URL", "channel", c.id, "attempts", c.tuning.MaxRetries, "error", redact.Error(err))
				// :541-551.
				c.emit("channel_error", map[string]any{
					"error_type": "connection_failed",
					"url":        truncate(redact.Line(c.Source().URL), 100),
					"attempts":   c.tuning.MaxRetries,
				})
				continue
			}
			wait := retryBackoff(failures)
			c.log.Info("reconnecting after a connection failure", "channel", c.id, "in", wait, "attempt", failures, "max", c.tuning.MaxRetries, "error", redact.Error(err))
			select {
			case <-ctx.Done():
			case <-time.After(wait):
			}
		}
		if ctx.Err() != nil {
			break
		}

		if c.takeFlag(&c.needsSwitch) {
			// :428-438: the health monitor's switch.
			if resolved, ok := c.failover(ctx, "health_monitor"); ok {
				c.countSwitch()
				source = resolved.Source
				continue
			}
			// "Continue with normal flow": the same URL, retried.
			c.failures.clear()
			continue
		}
		if urlFailed {
			// :596-611.
			if resolved, ok := c.failover(ctx, "max_retries_exceeded"); ok {
				c.countSwitch()
				source = resolved.Source
				continue
			}
			c.log.Error("no alternative stream after the switch attempts", "channel", c.id, "switches", c.switchCount())
			break
		}
	}

	switch {
	case ctx.Err() != nil:
		c.log.Info("channel stopped", "channel", c.id)
		c.setState(StateStopped, nil)
	default:
		// :678-682: the ERROR state and its message, for the client waiting
		// on its first byte.
		c.mu.RLock()
		tried := len(c.tried)
		c.mu.RUnlock()
		err := &ErrSourcesExhausted{Tried: tried, Attempts: c.tuning.MaxRetries, Last: last}
		// Through redact.Error, which is what relay/internal/credlint holds
		// every error-typed log argument in this module to: a provider URL
		// carries provider credentials (CLAUDE.md, § Known defects).
		c.log.Error("upstream failed", "channel", c.id, "error", redact.Error(err))
		c.setState(StateError, err)
	}
}

// runAttempt is one connection: one Source.Run, under a context the health
// monitor and the stderr reader can cancel, with the channel marked
// connected and healthy for its duration (input/manager.py:1314-1315,
// :1320).
func (c *Channel) runAttempt(ctx context.Context, source Source) error {
	if a, ok := source.(attachable); ok {
		a.attach(c)
	}
	attemptCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	c.mu.Lock()
	now := c.now()
	c.connected = true
	c.healthy = true
	c.connStart = now
	c.lastData = now
	c.cancelAttempt = cancel
	c.mu.Unlock()

	err := source.Run(attemptCtx, dataClock{c: c})

	c.mu.Lock()
	c.connected = false
	c.cancelAttempt = nil
	c.mu.Unlock()
	return err
}

// switchCount, countSwitch and resetSwitches are the switch counter's three
// operations, under mu because the run loop and the stderr reader both reach
// it (issue #221).
func (c *Channel) switchCount() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.switches
}

func (c *Channel) countSwitch() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.switches++
}

func (c *Channel) resetSwitches() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.switches = 0
}

// takePending hands the run loop a source the stderr reader adopted.
func (c *Channel) takePending() *Resolved {
	c.mu.Lock()
	defer c.mu.Unlock()
	resolved := c.pending
	c.pending = nil
	return resolved
}

// noteStable is _note_stable_connection (input/manager.py:199-204): the
// tried set shrinks to the current stream.
func (c *Channel) noteStable() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.tried = map[int]bool{}
	if c.currentStreamID != 0 {
		c.tried[c.currentStreamID] = true
	}
}

// emitStop is channel_stop (live_proxy/server.py:1568-1601): the runtime and
// the byte total, snapshotted as the channel ends.
//
// RAISED FROM THE ONE PLACE A CHANNEL ENDS, where Python raises it from
// ProxyServer.stop_channel's owner branch (:1827, :1842) -- which the admin
// stop, the last-client disconnect sweep and the orphan sweep all reach, and
// which a channel whose sources are exhausted reaches through the cleanup
// thread. One mechanism here, several there, and the set of endings that
// announce themselves is the same or slightly larger: a stated divergence in
// the safe direction, since an ending that raised nothing would be a missing
// event rather than a spurious one.
//
// channel_name falls back to the channel's id exactly as
// _collect_channel_stop_event_data's `or str(channel_id)` does (:1570).
func (c *Channel) emitStop() {
	name := c.channelName
	if name == "" {
		name = c.id
	}
	// round(time.time() - init_time, 2) at :1577.
	runtime := math.Round(c.now().Sub(c.startedAt).Seconds()*100) / 100
	c.events.Emit(Event{
		Type:        "channel_stop",
		ChannelID:   c.id,
		ChannelName: name,
		Details: map[string]any{
			"runtime":     runtime,
			"total_bytes": c.ring.TotalBytes(),
		},
	})
}

// releaseSlot gives the provider slot back once the source goroutine has
// returned: the one place this relay releases, where the Python relay
// releases from the stop path's _release_stream_resources
// (live_proxy/server.py:2335-2385). Once per channel by construction, which
// is what the metadata hdels CLAUDE.md records under #190 exist to
// guarantee against a duplicate release, and why they have no analogue here.
func (c *Channel) releaseSlot() {
	if c.release == nil {
		return
	}
	c.release(c.id, c.Source())
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
