package channel

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// ManagerConfig is what a Manager needs.
type ManagerConfig struct {
	// BudgetBytes is each channel's ring size. Zero means
	// buffer.MaxBytesPerChannel.
	BudgetBytes int

	// ShutdownDelay is how long a channel with no clients stays up, the
	// channel_shutdown_delay setting, which defaults to 0.
	ShutdownDelay time.Duration

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
func (m *Manager) Attach(id string, start func() (Source, Tuning, error)) (*Channel, func(), error) {
	var gate chan struct{}
	for {
		existing, wait, own := m.claim(id)
		if existing != nil {
			existing.markActive()
			return existing, func() { m.release(existing) }, nil
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

	built, tuning, err := start()
	if err != nil {
		// A failed start leaves no channel, and the deferred release lets the
		// next caller claim a fresh gate and try again. A tune that failed is
		// retryable; nothing here caches the failure.
		return nil, nil, err
	}

	c := m.publish(id, built, tuning)
	return c, func() { m.release(c) }, nil
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
func (m *Manager) claim(id string) (existing *Channel, wait, own chan struct{}) {
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
			c.addClient()
			return c, nil, nil
		}
		delete(m.channels, id)
	}
	if gate, starting := m.starting[id]; starting {
		return nil, gate, nil
	}
	gate := make(chan struct{})
	m.starting[id] = gate
	return nil, nil, gate
}

// publish installs the started channel and registers its first client.
func (m *Manager) publish(id string, source Source, tuning Tuning) *Channel {
	ctx, cancel := context.WithCancel(context.Background())
	c := &Channel{
		id: id,
		ring: buffer.New(buffer.Config{
			BudgetBytes: m.cfg.BudgetBytes,
			ChunkBytes:  tuning.ChunkBytes,
			Retention:   tuning.Retention,
			Now:         m.cfg.Now,
		}),
		log:     m.log,
		tuning:  tuning,
		state:   StateInitializing,
		clients: 1,
		cancel:  cancel,
		done:    make(chan struct{}),
	}

	m.mu.Lock()
	m.channels[id] = c
	m.mu.Unlock()

	go c.run(ctx, source)
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

func (m *Manager) release(c *Channel) {
	if remaining := c.dropClient(); remaining > 0 {
		return
	}
	if m.cfg.ShutdownDelay <= 0 {
		m.Stop(c.id)
		return
	}
	time.AfterFunc(m.cfg.ShutdownDelay, func() {
		if c.Clients() == 0 {
			m.Stop(c.id)
		}
	})
}

// Describe is a one-line state summary, for logs and for the 2c-8 status
// routes to build on.
func (c *Channel) Describe() string {
	return fmt.Sprintf("channel %s state=%s clients=%d head=%d", c.id, c.State(), c.Clients(), c.ring.Head())
}
