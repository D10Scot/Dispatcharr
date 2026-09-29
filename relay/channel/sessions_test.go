package channel

import (
	"context"
	"errors"
	"io"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// attachBlocking starts a channel whose source blocks until it is stopped, on
// the tuning the caller chose.
func attachBlocking(t *testing.T, m *Manager, id, clientID string, tuning Tuning) (*Channel, func()) {
	t.Helper()
	started := &int32Counter{}
	ch, release, err := m.Attach(id, testClient(clientID), asStarted(func() (Source, Tuning, error) {
		return blockingSource{started: started}, tuning, nil
	}))
	if err != nil {
		t.Fatalf("Attach(%s): %v", id, err)
	}
	return ch, release
}

// Row 41: a resume is registered against the very channel its session names or
// not at all. Every shape in which that channel is not the running one -- gone,
// finished, replaced under the same id, or in the middle of being started --
// answers ErrChannelAbsent, and none of them starts anything.
func TestAttachExistingNeverStartsAChannel(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})
	t.Cleanup(m.StopAll)

	starts := &int32Counter{}
	blocking := func() (Started, error) {
		starts.inc()
		return Started{Source: blockingSource{started: &int32Counter{}}, Tuning: testTuning()}, nil
	}

	t.Run("a stopped channel", func(t *testing.T) {
		ch, release, err := m.Attach("stopped", testClient("a"), blocking)
		if err != nil {
			t.Fatal(err)
		}
		release() // the last client: the channel stops
		<-ch.Done()
		if _, err := m.AttachExisting(ch, testClient("b")); !errors.Is(err, ErrChannelAbsent) {
			t.Fatalf("AttachExisting on a stopped channel = %v, want ErrChannelAbsent", err)
		}
	})

	t.Run("a channel whose ring closed but is still in the map", func(t *testing.T) {
		tuning := testTuning()
		tuning.MaxRetries = 1
		ch, release, err := m.Attach("finished", testClient("a"), asStarted(func() (Source, Tuning, error) {
			starts.inc()
			return failingSource{runs: &int32Counter{}}, tuning, nil
		}))
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(release)
		<-ch.Done()
		if m.Get("finished") != ch {
			t.Fatal("the finished channel left the map on its own; the case is not the one it names")
		}
		if _, err := m.AttachExisting(ch, testClient("b")); !errors.Is(err, ErrChannelAbsent) {
			t.Fatalf("AttachExisting on a closed-ring channel = %v, want ErrChannelAbsent", err)
		}
	})

	t.Run("a channel replaced under the same id", func(t *testing.T) {
		old, releaseOld, err := m.Attach("replaced", testClient("a"), blocking)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { old.stop(time.Second) })
		_ = releaseOld
		// The old channel leaves the map with its ring still open -- the
		// window between Manager.Stop's take and the ring's close -- and a new
		// tune puts a different *Channel there. An identity-blind lookup
		// (`m.channels[id] != nil`) would attach to the old one.
		if m.take("replaced") != old {
			t.Fatal("take returned a different channel")
		}
		fresh, releaseFresh, err := m.Attach("replaced", testClient("c"), blocking)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(releaseFresh)
		if fresh == old {
			t.Fatal("the replacement is the old channel")
		}
		before := starts.get()
		if _, err := m.AttachExisting(old, testClient("b")); !errors.Is(err, ErrChannelAbsent) {
			t.Fatalf("AttachExisting on a replaced channel = %v, want ErrChannelAbsent", err)
		}
		if starts.get() != before {
			t.Fatal("AttachExisting started a channel")
		}
		if fresh.Clients() != 1 {
			t.Fatalf("the replacement holds %d clients after a refused resume, want 1", fresh.Clients())
		}
	})

	t.Run("a channel that is being started", func(t *testing.T) {
		old, _, err := m.Attach("restarting", testClient("a"), blocking)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { old.stop(time.Second) })
		if m.take("restarting") != old {
			t.Fatal("take returned a different channel")
		}
		gate := make(chan struct{})
		entered := make(chan struct{})
		done := make(chan struct{})
		go func() {
			defer close(done)
			_, release, err := m.Attach("restarting", testClient("c"), func() (Started, error) {
				close(entered)
				<-gate
				return blocking()
			})
			if err == nil {
				t.Cleanup(release)
			}
		}()
		<-entered
		before := starts.get()
		if _, err := m.AttachExisting(old, testClient("b")); !errors.Is(err, ErrChannelAbsent) {
			t.Fatalf("AttachExisting during a start = %v, want ErrChannelAbsent", err)
		}
		if starts.get() != before {
			t.Fatal("AttachExisting started a channel")
		}
		close(gate)
		<-done
	})

	t.Run("the running channel registers the client itself", func(t *testing.T) {
		ch, release, err := m.Attach("running", testClient("a"), blocking)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(release)
		before := starts.get()
		releaseB, err := m.AttachExisting(ch, testClient("b"))
		if err != nil {
			t.Fatalf("AttachExisting on the running channel: %v", err)
		}
		if ch.Clients() != 2 {
			t.Fatalf("Clients() = %d, want 2", ch.Clients())
		}
		if _, err := m.AttachExisting(ch, testClient("b")); !errors.Is(err, ErrDuplicateClient) {
			t.Fatalf("a second AttachExisting under the same id = %v, want ErrDuplicateClient", err)
		}
		if starts.get() != before {
			t.Fatal("AttachExisting started a channel")
		}
		releaseB()
		if ch.Clients() != 1 {
			t.Fatalf("Clients() = %d after the resumed client's release, want 1", ch.Clients())
		}
	})
}

func TestStopIfIdleHonoursTheShutdownDelayAndLeavesAWatchedChannel(t *testing.T) {
	t.Run("a channel with a client is left alone", func(t *testing.T) {
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})
		t.Cleanup(m.StopAll)
		ch, _ := attachBlocking(t, m, "watched", "ts", testTuning())
		m.StopIfIdle(ch)
		if m.Get("watched") != ch {
			t.Fatal("StopIfIdle stopped a channel that still has a client")
		}
	})

	t.Run("no client and no delay: removed at once", func(t *testing.T) {
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})
		t.Cleanup(m.StopAll)
		ch, _ := attachBlocking(t, m, "idle", "hls", testTuning())
		ch.dropClient("hls") // an HLS session's entry, dropped by the table's stopper
		m.StopIfIdle(ch)
		if m.Get("idle") != nil {
			t.Fatal("the idle channel is still in the map")
		}
		<-ch.Done()
	})

	t.Run("no client and a delay: removed after it, and a client in it keeps the channel", func(t *testing.T) {
		tuning := testTuning()
		tuning.ShutdownDelay = 300 * time.Millisecond
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})
		t.Cleanup(m.StopAll)

		ch, _ := attachBlocking(t, m, "delayed", "hls", tuning)
		ch.dropClient("hls")
		m.StopIfIdle(ch)
		if m.Get("delayed") != ch {
			t.Fatal("StopIfIdle ignored the ShutdownDelay")
		}
		waitFor(t, "the delayed stop", 5*time.Second, func() bool { return m.Get("delayed") == nil })

		kept, _ := attachBlocking(t, m, "kept", "hls", tuning)
		kept.dropClient("hls")
		m.StopIfIdle(kept)
		if _, err := m.AttachExisting(kept, testClient("back")); err != nil {
			t.Fatalf("a client arriving inside the delay was refused: %v", err)
		}
		time.Sleep(tuning.ShutdownDelay + 200*time.Millisecond)
		if m.Get("kept") != kept {
			t.Fatal("the delayed stop tore down a channel that had a client again")
		}
	})
}

func TestDroppingHLSClientsEmitsDisconnectOnlyForConnectedOnes(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64, Events: events})
	t.Cleanup(m.StopAll)

	ch, _ := attachBlocking(t, m, "drop", "connected", testTuning())
	for _, id := range []string{"never-connected", "bystander"} {
		if _, err := m.AttachExisting(ch, testClient(id)); err != nil {
			t.Fatal(err)
		}
	}

	ch.dropHLSClients([]StoppedClient{
		{ClientID: "connected", Connected: true},
		{ClientID: "never-connected", Connected: false},
		{ClientID: "not-registered", Connected: true},
	})

	if got := ch.Clients(); got != 1 {
		t.Fatalf("Clients() = %d, want only the bystander", got)
	}
	disconnects := events.of("client_disconnect")
	if len(disconnects) != 1 {
		t.Fatalf("%d client_disconnect events, want exactly one (for the connected session): %+v", len(disconnects), disconnects)
	}
	if id := disconnects[0].Details["client_id"]; id != "connected" {
		t.Fatalf("client_disconnect named %v, want connected", id)
	}
	if _, ok := disconnects[0].Details["bytes_sent"]; !ok {
		t.Fatalf("client_disconnect carries no bytes_sent: %+v", disconnects[0].Details)
	}
}

// recordingEnder is a SessionEnder that records when the manager asked it to
// stop a channel, in the one log the channel's source also writes to.
type recordingEnder struct {
	mu    *sync.Mutex
	log   *[]string
	owned []StoppedClient
}

func (e recordingEnder) StopChannel(*Channel) []StoppedClient {
	e.mu.Lock()
	defer e.mu.Unlock()
	*e.log = append(*e.log, "StopChannel")
	return e.owned
}

// loggedSource blocks until stopped and records the moment it was told to.
type loggedSource struct {
	mu      *sync.Mutex
	log     *[]string
	running *int32Counter
}

func (s loggedSource) Run(ctx context.Context, _ io.Writer) error {
	s.running.inc()
	<-ctx.Done()
	s.mu.Lock()
	*s.log = append(*s.log, "source cancelled")
	s.mu.Unlock()
	return ctx.Err()
}

func TestAManagerStopMarksTheSessionsBeforeTheChannelStops(t *testing.T) {
	var mu sync.Mutex
	var log []string
	ender := recordingEnder{mu: &mu, log: &log, owned: []StoppedClient{{ClientID: "hls", Connected: true}}}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64, Sessions: ender})
	t.Cleanup(m.StopAll)

	running := &int32Counter{}
	ch, _, err := m.Attach("order", testClient("hls"), func() (Started, error) {
		return Started{Source: loggedSource{mu: &mu, log: &log, running: running}, Tuning: testTuning()}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	// A stop before the source goroutine has called Run would cancel a context
	// nobody waits on, and the log would say nothing about the order.
	waitFor(t, "the source to start", 5*time.Second, func() bool { return running.get() == 1 })
	if !m.Stop("order") {
		t.Fatal("Stop found no channel")
	}
	<-ch.Done()
	// The run-ended hook sweeps once more on its own goroutine.
	waitFor(t, "the run-ended sweep", 5*time.Second, func() bool {
		mu.Lock()
		defer mu.Unlock()
		return len(log) >= 3
	})

	mu.Lock()
	defer mu.Unlock()
	if len(log) < 3 || log[0] != "StopChannel" || log[1] != "source cancelled" || log[2] != "StopChannel" {
		t.Fatalf("order of events = %v, want StopChannel (the manager's sweep) before source cancelled, then StopChannel (the run-ended hook's)", log)
	}
	if ch.Clients() != 0 {
		t.Fatalf("the sweep left %d client entries on the stopped channel", ch.Clients())
	}
}

// The two client transitions carry what both generators carried: the agent cut
// at 100 characters (null when absent), the user id (null for an anonymous
// one), and the address and id.
func TestClientEventDetailsCutTheAgentAndNullTheAnonymousUser(t *testing.T) {
	long := &Client{ID: "c1", IPAddress: "198.51.100.4", UserAgent: repeatByte('u', 150), UserID: "7"}
	got := clientEventDetails(long)
	if agent, _ := got["user_agent"].(string); len(agent) != userAgentEventLimit {
		t.Errorf("a 150-character agent is %d characters on the event, want %d", len(agent), userAgentEventLimit)
	}
	if got["user_id"] != "7" || got["client_id"] != "c1" || got["client_ip"] != "198.51.100.4" {
		t.Errorf("details = %+v", got)
	}
	for _, anonymous := range []string{"", "0"} {
		got := clientEventDetails(&Client{ID: "c2", UserAgent: "", UserID: anonymous})
		if got["user_id"] != nil || got["user_agent"] != nil {
			t.Errorf("user id %q and no agent gave %+v, want both null", anonymous, got)
		}
	}
}

func repeatByte(b byte, n int) string {
	out := make([]byte, n)
	for i := range out {
		out[i] = b
	}
	return string(out)
}

func TestEmitClientConnectRaisesTheEventWithTheClientsDetails(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64, Events: events})
	t.Cleanup(m.StopAll)
	ch, _ := attachBlocking(t, m, "connect", "ts", testTuning())
	ch.EmitClientConnect(&Client{ID: "viewer", IPAddress: "203.0.113.5", UserAgent: "Player/1", UserID: "9"})
	got := events.of("client_connect")
	if len(got) != 1 || got[0].ClientID != "viewer" || got[0].Details["user_agent"] != "Player/1" {
		t.Fatalf("client_connect events = %+v", got)
	}
}
