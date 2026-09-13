package channel

import (
	"errors"
	"runtime"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// startCounting is the start function the tests below hand to Attach: 2c-3's
// Started shape around concurrent_test.go's countingSource.
//
// sourceCounter, countingSource, waitForStart, testTuning and testClient are
// NOT redeclared here -- they are concurrent_test.go's and manager_test.go's,
// and one package gets one of each.
func startCounting(c *sourceCounter, tuning Tuning) func() (Started, error) {
	return func() (Started, error) {
		return Started{Source: countingSource{c: c}, Tuning: tuning}, nil
	}
}

// N clients on one channel start exactly one source, and the channel survives
// until the LAST of them releases. The count is read from inside the source,
// so it fails whatever route a second reader took to get started.
func TestNClientsShareOneSourceAndTheChannelOutlivesAllButTheLast(t *testing.T) {
	const clients = 6
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	releases := make([]func(), 0, clients)
	var first *Channel
	for i := range clients {
		ch, release, err := m.Attach("one", testClient(string(rune('a'+i))), startCounting(counter, testTuning()))
		if err != nil {
			t.Fatalf("client %d: Attach: %v", i, err)
		}
		if first == nil {
			first = ch
		} else if ch != first {
			t.Fatalf("client %d got a different *Channel: the clients of one channel are watching two upstreams", i)
		}
		releases = append(releases, release)
	}

	if started := waitForStart(t, counter, 0); started != 1 {
		t.Fatalf("%d sources were started for one channel, want 1 -- a second provider connection was opened", started)
	}
	if got := first.Clients(); got != clients {
		t.Fatalf("the channel reports %d clients, want %d", got, clients)
	}

	for i := range clients - 1 {
		releases[i]()
		if m.Get("one") != first {
			t.Fatalf("the channel was stopped after client %d of %d released -- only the LAST client leaving stops it", i, clients)
		}
	}
	releases[clients-1]()
	if got := m.Get("one"); got != nil {
		t.Fatalf("the channel is still running after every client released: %v", got.Describe())
	}
	if running, _ := counter.snapshot(); running != 0 {
		t.Fatalf("%d source goroutines still running -- a leaked provider connection holding a slot", running)
	}
}

// Row 13's first half: registration is idempotent per client id, and a second
// attach under an id already attached is refused rather than silently
// overwriting the first (client_manager.py:218-221, whose False becomes a 503).
func TestASecondAttachUnderAnAttachedClientIDIsRefused(t *testing.T) {
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	ch, release, err := m.Attach("one", testClient("dup"), startCounting(counter, testTuning()))
	if err != nil {
		t.Fatalf("first Attach: %v", err)
	}
	defer release()

	second, _, err := m.Attach("one", testClient("dup"), startCounting(counter, testTuning()))
	if !errors.Is(err, ErrDuplicateClient) {
		t.Fatalf("a second attach under the id \"dup\" returned %v, want ErrDuplicateClient", err)
	}
	if second != nil {
		t.Fatal("the refused attach still handed back a channel")
	}
	if got := ch.Clients(); got != 1 {
		t.Fatalf("the channel holds %d clients after a refused duplicate, want 1 -- the registry is not keyed by id", got)
	}
}

// THE ORDERING TEST FOR THE LAST-CLIENT RULE. A client arriving at the instant
// the last one leaves must keep its channel. Neither property is a data race,
// so -race is silent on both: the drop and the stop have to happen under ONE
// lock, and the arrival registers under the same one.
//
// The defect this guards against: release drops the client, sees zero
// remaining, and THEN calls Stop. A claim landing in that window is handed the
// channel and has it torn down underneath it -- a 200 with a few bytes and no
// re-tune, for as long as clients keep churning.
func TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel(t *testing.T) {
	const rounds = 400

	for round := range rounds {
		counter := &sourceCounter{}
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

		first, releaseFirst, err := m.Attach("one", testClient("a"), startCounting(counter, testTuning()))
		if err != nil {
			t.Fatalf("round %d: first Attach: %v", round, err)
		}

		var wg sync.WaitGroup
		var second *Channel
		var releaseSecond func()
		var secondErr error

		wg.Add(2)
		go func() { defer wg.Done(); releaseFirst() }()
		go func() {
			defer wg.Done()
			second, releaseSecond, secondErr = m.Attach("one", testClient("b"), startCounting(counter, testTuning()))
		}()
		wg.Wait()

		if secondErr != nil {
			t.Fatalf("round %d: the arriving client failed to attach: %v", round, secondErr)
		}
		// Either the arrival won the race and holds the ORIGINAL channel, or
		// it lost and started a fresh one. Both are correct. What is never
		// correct is holding a channel the manager has dropped: nothing could
		// stop it, and its ring is already closing under the reader.
		if got := m.Get("one"); got != second {
			t.Fatalf("round %d: the arriving client holds a channel the manager does not (%v vs %v): "+
				"it was stopped underneath a live client",
				round, second.Describe(), got)
		}
		if second == first {
			if second.Ring().Closed() {
				t.Fatalf("round %d: the arriving client was handed the leaving client's channel "+
					"after its ring closed -- it will read an empty 200 and never re-tune", round)
			}
		}
		releaseSecond()
		m.StopAll()
	}
}

// The grace window: channel_shutdown_delay > 0 keeps a channel alive for a
// reconnecting client, and the reconnect cancels the stop
// (ChannelService.cancel_pending_shutdown, channel_service.py:103-127).
func TestTheShutdownDelayKeepsAChannelForAReconnectingClient(t *testing.T) {
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	tuning := testTuning()
	// 400ms, not the default 0: a test that supplied the default could not
	// tell a working grace window from no grace window at all.
	tuning.ShutdownDelay = 400 * time.Millisecond

	ch, release, err := m.Attach("one", testClient("a"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	release()

	if got := m.Get("one"); got != ch {
		t.Fatal("the channel was stopped immediately: the shutdown delay did not apply")
	}

	back, releaseBack, err := m.Attach("one", testClient("b"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("reconnect: %v", err)
	}
	if back != ch {
		t.Fatal("the reconnecting client got a fresh channel: the grace window was not honoured")
	}

	// Past the window the original stop would have fired. It must not, because
	// a client is attached.
	time.Sleep(700 * time.Millisecond)
	if m.Get("one") != ch {
		t.Fatal("the delayed stop fired with a client attached: the reconnect did not cancel it")
	}
	waitForStart(t, counter, 0)
	if running, started := counter.snapshot(); running != 1 || started != 1 {
		t.Fatalf("%d sources running and %d ever started, want 1 and 1", running, started)
	}

	releaseBack()
	deadline := time.Now().Add(3 * time.Second)
	for m.Get("one") != nil {
		if time.Now().After(deadline) {
			t.Fatal("the channel outlived its last client by more than the grace window")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// A delayed stop must never evict a REPLACEMENT channel. By the time the timer
// fires the map can hold a different *Channel under the same id -- the first
// finished, claim dropped it, a later tune published a successor. Deleting by
// id alone strands the successor's clients on a channel nothing can stop.
func TestADelayedStopNeverEvictsAReplacementChannel(t *testing.T) {
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	tuning := testTuning()
	tuning.ShutdownDelay = 300 * time.Millisecond

	first, releaseFirst, err := m.Attach("one", testClient("a"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	releaseFirst() // arms the delayed stop for `first`

	// Finish the first channel and take it out of the map the way claim does.
	m.Stop("one")

	second, releaseSecond, err := m.Attach("one", testClient("b"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("re-tune: %v", err)
	}
	defer releaseSecond()
	if second == first {
		t.Fatal("the re-tune reused the stopped channel")
	}

	time.Sleep(600 * time.Millisecond)
	if got := m.Get("one"); got != second {
		t.Fatalf("the first channel's delayed stop evicted the replacement: the map holds %v, want the "+
			"channel the live client is watching", got)
	}
}

// Attach and release under concurrency leak no goroutine. An ordering bug in
// the gate or the release path shows up here as a source goroutine nothing can
// stop, which -race never reports.
func TestConcurrentAttachAndReleaseLeaksNoGoroutine(t *testing.T) {
	const clients = 8
	const rounds = 50

	upstream := relaytest.NewUpstream(relaytest.Config{Rate: 0.05})
	t.Cleanup(upstream.Close)

	// Poll DOWN to a target rather than waiting for two equal samples: a
	// winding-down goroutine set is briefly stable at any value, so an
	// equal-samples settle reports whatever it happened to catch. This one
	// reports the lowest count reached inside the deadline.
	settleTo := func(target int) int {
		deadline := time.Now().Add(8 * time.Second)
		best := runtime.NumGoroutine()
		for {
			now := runtime.NumGoroutine()
			best = min(best, now)
			if best <= target || time.Now().After(deadline) {
				return best
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	// Read once, before any round: the test process is quiet here, and a
	// settle loop with no reachable target would only burn its own deadline.
	before := runtime.NumGoroutine()

	for round := range rounds {
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})
		var wg sync.WaitGroup
		for i := range clients {
			wg.Add(1)
			go func() {
				defer wg.Done()
				_, release, err := m.Attach("one", testClient(string(rune('a'+i))), func() (Started, error) {
					return Started{
						Source: ProxySource{URL: upstream.URL(), ReadTimeout: time.Second},
						Tuning: testTuning(),
					}, nil
				})
				if err != nil {
					return
				}
				release()
			}()
		}
		wg.Wait()
		m.StopAll()
		if n := len(m.ids()); n != 0 {
			t.Fatalf("round %d: the manager still holds %d channels", round, n)
		}
	}

	after := settleTo(before + 20)
	// A tolerance, not a bare equality: net/http keeps idle connections and
	// their readers alive across the test. What this catches is a LEAK PER
	// ROUND -- 50 rounds x 8 clients, so anything structural is hundreds.
	if after > before+20 {
		t.Fatalf("goroutines went from %d to %d across %d rounds of %d clients -- "+
			"something started per attach is never stopped", before, after, rounds, clients)
	}
}
