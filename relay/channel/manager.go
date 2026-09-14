package channel

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// ManagerConfig is what a Manager needs.
type ManagerConfig struct {
	// BudgetBytes is each channel's ring size. Zero means
	// buffer.MaxBytesPerChannel.
	BudgetBytes int

	// StopWait bounds how long Stop waits for a source goroutine.
	StopWait time.Duration

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger

	// Now is the clock handed to every ring, injectable so the join-point
	// tests do not sleep. Nil means time.Now.
	Now func() time.Time
}

// Manager owns every running channel.
//
// map[string]*Channel behind a sync.RWMutex is the whole of what the
// ownership lease used to buy (spec D2). Nothing here is in Redis, so nothing
// here can fail open the three ways server.py's lease does.
type Manager struct {
	cfg ManagerConfig
	log *slog.Logger

	mu       sync.Mutex
	channels map[string]*Channel
	// starting holds one gate per channel currently being started. A second
	// client arriving mid-start waits on the gate rather than starting a
	// second source, which is what makes "one upstream per channel" a
	// property of the code -- WITHOUT holding the manager lock across the
	// control-plane call, which is what makes one slow control plane cost one
	// tune rather than every tune.
	starting map[string]chan struct{}
}

// NewManager builds a manager. It starts no goroutines of its own.
func NewManager(cfg ManagerConfig) *Manager {
	if cfg.BudgetBytes <= 0 {
		cfg.BudgetBytes = buffer.MaxBytesPerChannel
	}
	if cfg.StopWait <= 0 {
		cfg.StopWait = 5 * time.Second
	}
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	return &Manager{
		cfg:      cfg,
		log:      log,
		channels: map[string]*Channel{},
		starting: map[string]chan struct{}{},
	}
}

// Started is what a start function hands back: the source to run, the tuning
// the channel runs on, and what the control plane said about the stream.
//
// A struct rather than a fourth return value: (Source, Tuning, SourceInfo,
// error) is where a signature stops being readable, and 2c-4's ffmpeg source
// adds a fifth.
type Started struct {
	Source Source
	Tuning Tuning
	Info   SourceInfo
}

// Attach returns the channel for id, starting it from start() if it is not
// already running, and registers one client against it.
//
// The returned release function must be called exactly once, and a deferred
// call is the only correct shape: it drops the client and, when that was the
// last one, stops the channel after ShutdownDelay.
//
// `start` is a FUNCTION rather than a value so a second client on a running
// channel never calls the control plane at all -- which is the behaviour
// views.py:712 has today, and the reason next-source runs once per channel
// while output profiles resolve once per client (2b-2's own ruling).
//
// START RUNS OUTSIDE THE MANAGER LOCK. An earlier draft called it while
// holding the lock, on the reasoning that one process needs one mutex where
// Python needs a per-channel init lock plus an ownership lease plus a
// _channels_setting_up set. That reasoning is right about correctness and
// wrong about everything else. start() makes the next-source call, whose own
// budget is two attempts of (2s, 5s) plus a retry delay, and holding the
// manager lock across it serialises every concurrent Attach, Get, Stop and
// release behind one slow control plane. Worse, a panic inside start() left
// the lock held forever: the relay then answered /healthz with 200 while
// every subsequent tune blocked. Demonstrated, and pinned by
// TestAPanickingStartDoesNotWedgeTheManager.
//
// The exclusion that actually matters is preserved by a gate: the caller that
// claims the start publishes a channel under `starting`, later callers wait on
// it and retry, and the gate is closed from a deferred call so a panic wakes
// them instead of stranding them.
func (m *Manager) Attach(id string, client *Client, start func() (Started, error)) (*Channel, func(), error) {
	var gate chan struct{}
	for {
		existing, wait, own, err := m.claim(id, client)
		if err != nil {
			return nil, nil, err
		}
		if existing != nil {
			// No markActive call here: promoteOnFirstChunk (run's own
			// goroutine) is the one mechanism for waiting_for_clients ->
			// active, and it runs regardless of which or how many clients
			// are attached, so a second client's arrival needs no separate
			// trigger.
			return existing, func() { m.release(existing, client.ID) }, nil
		}
		if own != nil {
			gate = own
			break
		}
		// Someone else is starting this channel. Wait for them and look
		// again; they may have succeeded, failed, or panicked.
		<-wait
	}

	// REGISTERED BEFORE start() IS CALLED, so it runs when Attach RETURNS --
	// which is after publish has installed the channel. The ordering is the
	// whole point and it is easy to get subtly wrong: an earlier version
	// closed the gate when the START finished, inside a helper, so a waiter
	// woken by it raced the caller's own map insertion. When the waiter won it
	// found neither a channel nor a gate, claimed a fresh one, and started a
	// SECOND upstream -- a second provider connection with no map entry and
	// nothing that would ever stop it, plus a first client whose release tore
	// down the other client's channel. Measured at 8 concurrent clients: it
	// went wrong within the first few rounds, and -race never flagged it,
	// because an ordering bug is not a data race.
	//
	// A deferred call still runs while a panic unwinds, so this also keeps the
	// panic guarantee the helper was written for.
	defer m.releaseGate(id, gate)

	started, err := start()
	if err != nil {
		// A failed start leaves no channel, and the deferred release lets the
		// next caller claim a fresh gate and try again. A tune that failed is
		// retryable; nothing here caches the failure.
		return nil, nil, err
	}

	c := m.publish(id, client, started)
	return c, func() { m.release(c, client.ID) }, nil
}

// releaseGate clears the start claim and wakes everyone waiting on it. It is
// called from Attach's deferred call and nowhere else, so the close happens
// exactly once and only after the channel is reachable.
func (m *Manager) releaseGate(id string, gate chan struct{}) {
	m.mu.Lock()
	delete(m.starting, id)
	m.mu.Unlock()
	close(gate)
}

// claim inspects the map once, under the lock. It returns exactly one of: a
// running channel with this caller registered against it; a gate to wait on
// because someone else is starting; or a gate this caller now owns.
func (m *Manager) claim(id string, client *Client) (existing *Channel, wait, own chan struct{}, err error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if c, running := m.channels[id]; running {
		// A FINISHED CHANNEL IS NOT A RUNNING ONE. Once the ring is closed
		// nothing will ever be published to it again, so handing it to a new
		// client serves whatever is left in the buffer and then EOF, with no
		// re-tune and no error -- a channel whose upstream 404'd would answer
		// every later viewer with an empty 200, forever. Drop it here and fall
		// through to a fresh start.
		//
		// The ring, not c.done: the ring closes FIRST inside run's deferred
		// calls, so this covers the whole window from "nothing more will be
		// published" onward rather than just the tail of it.
		//
		// THIS IS THE ONLY PLACE A FINISHED CHANNEL IS DROPPED. An earlier
		// draft also had run() remove itself from the map, which was worse in
		// a way that is easy to miss: with two mechanisms, removing this one
		// changed no test, because the other silently covered for it. One
		// mechanism means the break-check reddens. The cost is that a finished
		// channel nobody re-tunes stays in the map until its last client
		// releases -- and release stops it, so the entry cannot outlive the
		// clients watching it.
		if !c.ring.Closed() {
			if !c.addClient(client) {
				return nil, nil, nil, ErrDuplicateClient
			}
			return c, nil, nil, nil
		}
		delete(m.channels, id)
	}
	if gate, starting := m.starting[id]; starting {
		return nil, gate, nil, nil
	}
	gate := make(chan struct{})
	m.starting[id] = gate
	return nil, nil, gate, nil
}

// publish installs the started channel and registers its first client.
func (m *Manager) publish(id string, client *Client, started Started) *Channel {
	ctx, cancel := context.WithCancel(context.Background())
	now := m.cfg.Now
	if now == nil {
		now = time.Now
	}
	c := &Channel{
		id: id,
		ring: buffer.New(buffer.Config{
			BudgetBytes: m.cfg.BudgetBytes,
			ChunkBytes:  started.Tuning.ChunkBytes,
			Retention:   started.Tuning.Retention,
			Now:         m.cfg.Now,
		}),
		log:       m.log,
		tuning:    started.Tuning,
		source:    started.Info,
		startedAt: now(),
		state:     StateInitializing,
		clients:   map[string]*Client{client.ID: client},
		cancel:    cancel,
		done:      make(chan struct{}),
	}

	m.mu.Lock()
	m.channels[id] = c
	m.mu.Unlock()

	go c.run(ctx, started.Source)
	return c
}

// Get returns a running channel, or nil.
func (m *Manager) Get(id string) *Channel {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.channels[id]
}

// Stop tears a channel down immediately, whatever its client count.
func (m *Manager) Stop(id string) bool {
	c := m.take(id)
	if c == nil {
		return false
	}
	c.setState(StateStopping, nil)
	c.stop(m.cfg.StopWait)
	return true
}

// take removes a channel from the map and returns it, or nil.
func (m *Manager) take(id string) *Channel {
	m.mu.Lock()
	defer m.mu.Unlock()
	c, running := m.channels[id]
	if !running {
		return nil
	}
	delete(m.channels, id)
	return c
}

// StopAll tears every channel down. The SIGTERM drain that calls it in
// anger is 2c-8's; this exists so a test and a shutdown path have one way to
// do it.
func (m *Manager) StopAll() {
	for _, id := range m.ids() {
		m.Stop(id)
	}
}

func (m *Manager) ids() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	ids := make([]string, 0, len(m.channels))
	for id := range m.channels {
		ids = append(ids, id)
	}
	return ids
}

// 2c-3 changes exactly two things here and preserves everything else: the drop
// names a client, and the delay comes off the channel's own Tuning rather than
// the manager's config (it is a channel-start-time setting, parity-matrix row
// 5). The drop stays OUTSIDE m.mu and the decision stays inside
// stopIfStillIdle, which is 2c-2's fix and is correct with a registry for the
// same reason it is correct with a counter: claim's addClient and
// stopIfStillIdle's re-check are both under m.mu, so whichever runs first is
// the one acted on and the other sees the consequence.
func (m *Manager) release(c *Channel, clientID string) {
	if remaining := c.dropClient(clientID); remaining > 0 {
		return
	}
	if c.tuning.ShutdownDelay <= 0 {
		m.stopIfStillIdle(c)
		return
	}
	time.AfterFunc(c.tuning.ShutdownDelay, func() {
		m.stopIfStillIdle(c)
	})
}

// stopIfStillIdle re-checks c's client count and, if it is still zero,
// removes c from the map and tears it down -- both under m.mu, in the same
// critical section claim() uses to read the map and call addClient.
//
// THE RE-CHECK MUST HAPPEN UNDER m.mu, and that is the whole fix (found by a
// downstream reviewer, verified here before being trusted): dropClient()
// above only touches c.mu, so the moment between it returning zero and this
// method's own lock acquisition is a window in which claim() can run to
// completion -- see the map, find the ring not yet closed, and addClient()
// -- entirely unaware that the caller that dropped to zero already decided
// to stop this channel. Re-reading Clients() here, under the same lock
// claim() holds across its own check-and-addClient, makes the two mutually
// exclusive: whichever runs first is the one whose view of "is this channel
// idle" is the one that is acted on, and the other sees the consequence
// (either the channel is already gone from the map, or Clients() is back
// above zero and this call is a no-op). Demonstrated at roughly one race in
// several thousand rounds by TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined
// against the pre-fix code (a plain c.Clients() == 0 check taken outside the
// lock): a client attaching at that exact instant was handed a channel that
// stopIfStillIdle then tore down anyway, in the same round.
//
// The identity check (`existing == c`) guards a narrower case than the race
// above: by the time this runs, id's map entry might already be a DIFFERENT,
// newer channel (this one's ring closed on its own and a fresh tune
// replaced it in claim() before this call ever got the lock). Deleting the
// map entry unconditionally in that case would remove the wrong channel.
// Tearing down c itself is still correct and safe either way -- c.stop is
// idempotent-ish (context.CancelFunc more than once is a no-op, and a select
// on an already-closed c.done returns immediately) -- so this always runs it
// once Clients() reads zero, and only touches the map when c is still the
// entry it names.
func (m *Manager) stopIfStillIdle(c *Channel) {
	stop := func() bool {
		m.mu.Lock()
		defer m.mu.Unlock()
		if c.Clients() != 0 {
			return false
		}
		if existing, ok := m.channels[c.id]; ok && existing == c {
			delete(m.channels, c.id)
		}
		return true
	}()
	if !stop {
		return
	}
	c.setState(StateStopping, nil)
	c.stop(m.cfg.StopWait)
}

// Snapshot is every channel the manager holds, in id order.
//
// The list endpoint's source. Ordered so the payload is stable between polls;
// build_live_channel_stats_data's own order is a Redis SCAN's, which is
// arbitrary and not a contract.
func (m *Manager) Snapshot() []*Channel {
	m.mu.Lock()
	out := make([]*Channel, 0, len(m.channels))
	for _, c := range m.channels {
		out = append(out, c)
	}
	m.mu.Unlock()
	sort.Slice(out, func(i, j int) bool { return out[i].id < out[j].id })
	return out
}

// Describe is a one-line state summary, for logs and for the 2c-8 status
// routes to build on.
func (c *Channel) Describe() string {
	return fmt.Sprintf("channel %s state=%s clients=%d head=%d", c.id, c.State(), c.Clients(), c.ring.Head())
}
