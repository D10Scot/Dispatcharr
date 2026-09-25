package channel

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// testTuning is the channel-start-time settings every channel test runs on.
// The ten failover fields carry apps/proxy/config.py's own values -- the
// production shape, so a 2c-2 test that drives a 404 now sees three attempts
// and 0.75s of backoff, as the Python relay would. A test whose SUBJECT is
// one of these thresholds overrides it with a non-default value (hollow
// shape 2: a pin that supplies the default pins nothing).
func testTuning() Tuning {
	return Tuning{
		ChunkBytes:          buffer.TSPacketSize * 4,
		Retention:           time.Minute,
		ConnectionTimeout:   10 * time.Second,
		HealthCheckInterval: 5 * time.Second,
		InitGracePeriod:     60 * time.Second,
		MaxRetries:          3,
		RetryWindow:         1800 * time.Second,
		StableThreshold:     30 * time.Second,
		MaxStreamSwitches:   10,
		ClientTimeout:       40 * time.Second,
		KeepaliveInterval:   500 * time.Millisecond,
		MaxKeepalive:        300 * time.Second,
	}
}

// asStarted wraps a 2c-2-shaped start function in 2c-3's Started shape.
func asStarted(f func() (Source, Tuning, error)) func() (Started, error) {
	return func() (Started, error) {
		source, tuning, err := f()
		return Started{Source: source, Tuning: tuning}, err
	}
}

// testClient is a registry row with a caller-chosen id. Distinct ids matter:
// two Attach calls under ONE id are a duplicate registration and are refused
// (ErrDuplicateClient), which is parity-matrix row 13's first half and exactly
// what these tests must not accidentally exercise.
func testClient(id string) *Client {
	return &Client{ID: id, UserID: "0", OutputFormat: "mpegts"}
}

// A source that blocks until its context is done, counting how many times it
// was started.
type blockingSource struct{ started *int32Counter }

func (s blockingSource) Run(ctx context.Context, _ io.Writer) error {
	s.started.inc()
	<-ctx.Done()
	return ctx.Err()
}

type int32Counter struct {
	mu sync.Mutex
	n  int
}

func (c *int32Counter) inc() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.n++
}

func (c *int32Counter) get() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.n
}

// Two clients on one channel start ONE source, and the second never calls the
// control plane. Counted at the source, not at the manager, so it fails if
// Attach starts a second reader however it managed to.
func TestTwoClientsShareOneSource(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	started := &int32Counter{}
	starts := &int32Counter{}
	start := func() (Source, Tuning, error) {
		starts.inc()
		return blockingSource{started: started}, testTuning(), nil
	}

	first, releaseFirst, err := m.Attach("chan-1", testClient("a"), asStarted(start))
	if err != nil {
		t.Fatalf("first Attach: %v", err)
	}
	second, releaseSecond, err := m.Attach("chan-1", testClient("b"), asStarted(start))
	if err != nil {
		t.Fatalf("second Attach: %v", err)
	}
	if first != second {
		t.Fatal("the second client got a different Channel")
	}
	if got := starts.get(); got != 1 {
		t.Fatalf("the start function ran %d times, want 1 -- the second client "+
			"must not call the control plane", got)
	}
	if got := first.Clients(); got != 2 {
		t.Fatalf("Clients() = %d, want 2", got)
	}
	// The source goroutine starts after Attach returns; releasing before it
	// has called Run would count zero runs and prove nothing about sharing.
	waitFor(t, "the source to start", 5*time.Second, func() bool { return started.get() == 1 })

	releaseSecond()
	if m.Get("chan-1") == nil {
		t.Fatal("the channel stopped when the second of two clients left")
	}
	releaseFirst()
	if m.Get("chan-1") != nil {
		t.Fatal("the channel is still running after its last client left")
	}
	<-first.Done()
	if state := first.State(); state != StateStopping && state != StateStopped {
		t.Fatalf("state = %q after teardown", state)
	}
	if got := started.get(); got != 1 {
		t.Fatalf("the source ran %d times, want 1", got)
	}
}

// The one upstream CONNECTION, as the provider sees it. The test above counts
// starts inside this process; this one counts HTTP requests at the provider,
// which is what parity-matrix row 10 is actually about.
func TestTwoClientsMakeOneUpstreamRequest(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{Rate: 0.05})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	start := func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}
	ch, releaseFirst, err := m.Attach("chan-2", testClient("a"), asStarted(start))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	_, releaseSecond, err := m.Attach("chan-2", testClient("b"), asStarted(start))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}

	deadline := time.Now().Add(5 * time.Second)
	for ch.Ring().Head() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if ch.Ring().Head() == 0 {
		t.Fatal("no chunk was published within five seconds")
	}
	if got := up.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1 -- two clients must share one upstream", got)
	}

	releaseSecond()
	releaseFirst()
	<-ch.Done()
}

// A CLEAN UPSTREAM EOF IS A CONNECTION FAILURE, retried and counted, not the
// stream ending: fetch_chunk reads an empty chunk as "Server closed
// connection" (input/manager.py:1870-1875), _process_stream_data returns,
// and the retry loop records a failure and reconnects (:555-563). Three of
// them exhaust the source (:534-537, parity-matrix row 3); with nothing to
// fail over to, the channel ends in error naming the attempts, and its ring
// closes so no reader blocks forever. 2c-2 ended the channel on the first
// EOF, which was the honest shape before there was a retry loop to run;
// this is the Python one.
func TestACleanUpstreamEndIsRetriedAndThenExhaustsTheSource(t *testing.T) {
	payload := relaytest.SyntheticTS(8, 0x100)
	up := relaytest.NewUpstream(relaytest.Config{Payload: payload, StopAfterBytes: len(payload)})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	ch, release, err := m.Attach("chan-3", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer release()

	select {
	case <-ch.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the source goroutine did not return after the upstream ended three times")
	}
	if got := up.Requests(); got != 3 {
		t.Fatalf("the provider saw %d requests, want MAX_RETRIES = 3: a clean EOF is reconnected, not accepted", got)
	}
	if state := ch.State(); state != StateError {
		t.Fatalf("state = %q after three clean EOFs, want %q", state, StateError)
	}
	var exhausted *ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) || exhausted.Message() != "Connection failed after 3 attempts" {
		t.Fatalf("Err() = %v, want ErrSourcesExhausted saying \"Connection failed after 3 attempts\" (input/manager.py:682)", ch.Err())
	}
	// Asked AT THE HEAD, not at cursor 0. Wait reports freshness before
	// closure, so a caught-up reader is the only one that can observe the
	// ring being shut -- a reader with a backlog is correctly told to come
	// and get it first.
	if err := ch.Ring().Wait(t.Context(), ch.Ring().Head()); !errors.Is(err, buffer.ErrClosed) {
		t.Fatalf("Wait at the head returned %v, want ErrClosed -- the ring is still "+
			"open after the source returned, and every reader would block forever", err)
	}
}

// A channel with one attached client and flowing bytes reaches active --
// found broken by review: the prior mechanism (a manager-side markActive,
// called only on a SECOND client's Attach) measured 0/300 rounds ever
// reaching it, because a channel's first client never triggered it and
// run()'s own concurrent write of waiting_for_clients usually raced a
// second client's call into a no-op. promoteOnFirstChunk is now the one
// mechanism, driven by the ring publishing its first chunk rather than by
// how many clients have attached.
func TestAChannelWithFlowingBytesBecomesActive(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{Rate: 0.2})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	ch, release, err := m.Attach("chan-active", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer release()

	deadline := time.Now().Add(5 * time.Second)
	for ch.State() != StateActive && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if state := ch.State(); state != StateActive {
		t.Fatalf("state = %q after bytes flowed for up to five seconds, want %q", state, StateActive)
	}
	if got := ch.Describe(); !strings.Contains(got, "state=active") {
		t.Fatalf("Describe() = %q, want it to report state=active", got)
	}
}

// A source that fails to start leaves the channel in error, and the failure
// reaches the caller rather than becoming a channel that streams nothing.
func TestAnUpstreamFailurePutsTheChannelInError(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{Status: 404})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	ch, release, err := m.Attach("chan-4", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer release()

	select {
	case <-ch.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the source goroutine did not return after three 404s")
	}
	if state := ch.State(); state != StateError {
		t.Fatalf("state = %q after an upstream 404, want %q", state, StateError)
	}
	// Three attempts (MAX_RETRIES) before the source is exhausted, and the
	// last attempt's error still visible through the exhaustion wrapper.
	if got := up.Requests(); got != 3 {
		t.Fatalf("the provider saw %d requests, want 3", got)
	}
	var status *ErrUpstreamStatus
	if !errors.As(ch.Err(), &status) || status.Status != 404 {
		t.Fatalf("Err() = %v, want an *ErrUpstreamStatus carrying 404 inside the exhaustion error", ch.Err())
	}
}

// B1. A panic inside start() must not leave the manager locked. Before the
// gate-and-defer restructure this wedged the relay permanently: /healthz kept
// answering 200 while every later Attach blocked forever on a mutex nobody
// would release.
func TestAPanickingStartDoesNotWedgeTheManager(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	func() {
		defer func() {
			if recover() == nil {
				t.Error("the panic did not propagate to the caller")
			}
		}()
		_, _, _ = m.Attach("boom", testClient("a"), asStarted(func() (Source, Tuning, error) {
			panic("the control plane exploded")
		}))
	}()

	done := make(chan struct{})
	go func() {
		defer close(done)
		_, release, err := m.Attach("after", testClient("a"), asStarted(func() (Source, Tuning, error) {
			return blockingSource{started: &int32Counter{}}, testTuning(), nil
		}))
		if err != nil {
			t.Errorf("the Attach after the panic failed: %v", err)
			return
		}
		release()
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("the Attach after a panicking start blocked: the manager lock was " +
			"never released, and every tune on this process is now stuck")
	}
}

// The same property for the channel that panicked: its gate must have been
// closed, or a second client for THAT id waits on it forever.
func TestAPanickingStartReleasesItsGate(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	func() {
		defer func() { _ = recover() }()
		_, _, _ = m.Attach("boom", testClient("a"), asStarted(func() (Source, Tuning, error) { panic("boom") }))
	}()

	done := make(chan struct{})
	go func() {
		defer close(done)
		_, release, err := m.Attach("boom", testClient("a"), asStarted(func() (Source, Tuning, error) {
			return blockingSource{started: &int32Counter{}}, testTuning(), nil
		}))
		if err != nil {
			t.Errorf("retrying the panicked channel failed: %v", err)
			return
		}
		release()
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("a second client for the panicked channel waited on a gate that was never closed")
	}
}

// SF4. A channel whose source has returned is finished: its ring is closed and
// nothing will ever be published to it again. Handing it to a new client
// serves the residual buffer and then EOF, with no re-tune and no error -- so
// a channel whose upstream 404'd would answer every later viewer with an empty
// 200, forever.
func TestAFinishedChannelIsNotHandedToANewClient(t *testing.T) {
	dead := relaytest.NewUpstream(relaytest.Config{Status: 404})
	t.Cleanup(dead.Close)
	live := relaytest.NewUpstream(relaytest.Config{Rate: 0.05})
	t.Cleanup(live.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	first, releaseFirst, err := m.Attach("chan-5", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: dead.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("first Attach: %v", err)
	}
	<-first.Done()
	if first.State() != StateError {
		t.Fatalf("state = %q after a 404, want %q", first.State(), StateError)
	}

	// The first client is still attached, which is the case that matters: a
	// release would have stopped the channel anyway.
	second, releaseSecond, err := m.Attach("chan-5", testClient("b"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: live.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("second Attach: %v", err)
	}
	defer releaseSecond()
	defer releaseFirst()

	if second == first {
		t.Fatal("the second client was handed the finished channel: it would read the " +
			"residual buffer and then EOF, with no re-tune")
	}
	// Polled, not asserted immediately: the source goroutine starts after
	// Attach returns, so a bare assertion here would race the dial rather
	// than test the re-tune.
	deadline := time.Now().Add(5 * time.Second)
	for live.Requests() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if got := live.Requests(); got != 1 {
		t.Fatalf("the live provider saw %d requests, want 1 -- the second client did not re-tune", got)
	}
}

// A downstream reviewer's claim, verified here before being trusted: the
// last client's release() and a concurrent Attach on the same id are not
// mutually exclusive unless the "am I still idle" re-check runs under the
// SAME lock claim() holds across its own map-read-and-addClient. Confirmed
// real against the pre-fix code -- a plain c.Clients() == 0 check taken
// outside m.mu -- at roughly one race in several thousand rounds: the
// arriving client's claim() would see the channel still in the map, add
// itself, and be handed a *Channel that the releasing goroutine's Stop then
// tore down anyway, because its decision was made from a snapshot the
// arriving client had already invalidated.
func TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined(t *testing.T) {
	const rounds = 20000
	for round := range rounds {
		counter := &int32Counter{}
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})

		_, releaseFirst, err := m.Attach("shared", testClient("a"), asStarted(func() (Source, Tuning, error) {
			return blockingSource{started: counter}, testTuning(), nil
		}))
		if err != nil {
			t.Fatalf("round %d: first Attach: %v", round, err)
		}

		var wg sync.WaitGroup
		var second *Channel
		var releaseSecond func()
		var secondErr error
		start := make(chan struct{})
		wg.Add(2)
		go func() {
			defer wg.Done()
			<-start
			releaseFirst()
		}()
		go func() {
			defer wg.Done()
			<-start
			second, releaseSecond, secondErr = m.Attach("shared", testClient("b"), asStarted(func() (Source, Tuning, error) {
				return blockingSource{started: counter}, testTuning(), nil
			}))
		}()
		close(start)
		wg.Wait()

		if secondErr != nil {
			t.Fatalf("round %d: second Attach: %v", round, secondErr)
		}
		if second == nil {
			t.Fatalf("round %d: second Attach returned a nil channel with no error", round)
		}
		// THE PROPERTY: whichever channel the second client was handed --
		// the first's, if it won the race, or a freshly started one, if the
		// first's had already been removed -- it must not be a channel that
		// is stopping or stopped out from under a client that just arrived.
		if state := second.State(); state == StateStopping || state == StateStopped {
			t.Fatalf("round %d: the second client was handed a %s channel", round, state)
		}
		releaseSecond()

		// After both releases, exactly the sources this round started must
		// have stopped -- no leaked goroutine still holding a "started" slot
		// this manager no longer has a map entry for.
		deadline := time.Now().Add(5 * time.Second)
		for len(m.ids()) != 0 {
			if time.Now().After(deadline) {
				t.Fatalf("round %d: the manager still holds %d channel(s) after both clients released",
					round, len(m.ids()))
			}
			time.Sleep(time.Millisecond)
		}
	}
}

// ISSUE #233's relay half: a channel tuned by a STREAM HASH -- the admin
// single-stream preview, /proxy/ts/stream/<stream_hash> -- names that hash,
// verbatim, as the ChannelID of every event it raises. core/relay_events.py
// tells a hash from a channel UUID by parsing it, the rule next_source.py's
// get_stream_object applies, and records it as details["stream_hash"]; that
// only works if the relay passes the identifier through untouched, which is
// what this pins. The relay holds no rule of its own about identifiers.
func TestAStreamHashTuneNamesItsHashAsTheEventChannelID(t *testing.T) {
	const streamHash = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)
	ch, release := attachWith(t, m, streamHash, flowingSource{runs: &int32Counter{}}, testTuning(), nil)
	defer release()
	m.Stop(streamHash)
	<-ch.Done()

	for _, typ := range []string{"channel_start", "channel_stop"} {
		got := events.of(typ)
		if len(got) != 1 {
			t.Fatalf("%d %s events, want 1", len(got), typ)
		}
		if got[0].ChannelID != streamHash {
			t.Fatalf("%s named channel %q, want the stream hash it was tuned by, verbatim", typ, got[0].ChannelID)
		}
	}
}
