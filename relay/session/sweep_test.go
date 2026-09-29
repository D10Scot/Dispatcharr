package session

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/hls"
)

func waitUntil(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// send delivers one tick, failing with the mechanism's name when no sweeper
// takes it.
func send(t *testing.T, tick chan<- time.Time) {
	t.Helper()
	select {
	case tick <- time.Now():
	case <-time.After(2 * time.Second):
		t.Fatal("no sweeper consumed the tick: the sweep is blocked or not running")
	}
}

// settlingSessions is how many sessions still have an idle departure running:
// read under the table's own lock.
func settlingSessions(table *Table) int {
	table.mu.Lock()
	defer table.mu.Unlock()
	n := 0
	for _, s := range table.byID {
		if s.settling {
			n++
		}
	}
	return n
}

func TestTheSweeperDepartsOnItsTicks(t *testing.T) {
	clock := newFakeClock()
	tick := make(chan time.Time)
	table := NewTable(Config{Now: clock.Now, Tick: tick})
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	go table.Run(ctx)

	j := &journal{}
	owner := &fakeOwner{name: "c1", j: j}
	add := func(id string) *Session {
		s := &Session{ID: "sid-" + id, Owner: owner, Key: "hls", Pipeline: &hls.Pipeline{}, TD: 2 * time.Second}
		table.Add(s, &channel.Client{ID: id}, Releases{
			Output: func() { j.add("output " + id) },
			Client: func() { j.add("client " + id) },
		})
		table.Activate(s.ID)
		return s
	}
	first, second := add("a"), add("b")

	clock.Advance(IdleTimeout(2 * time.Second))
	send(t, tick)
	waitUntil(t, "both idle sessions to depart", func() bool { return len(j.all()) == 6 })
	// The journal's last entry is the Client release, which runs BEFORE the
	// departure settles the session (and stamps departedAt from the clock). The
	// clock must not move until both have settled, or the settle would stamp the
	// advanced time and restart the resume window.
	waitUntil(t, "both departures to settle", func() bool { return settlingSessions(table) == 0 })
	// A departed session is resumable, so it is still in the table.
	if table.Len() != 2 {
		t.Fatalf("the table holds %d sessions after two departures, want 2 (both resumable)", table.Len())
	}

	// After the window, one more tick removes them both.
	clock.Advance(ResumeWindow + time.Second)
	send(t, tick)
	waitUntil(t, "the expired sessions to be removed", func() bool { return table.Len() == 0 })
	if l := table.Begin(first.ID); l.Outcome != Unknown {
		t.Fatalf("Begin on an expired session = %v, want Unknown", l.Outcome)
	}
	_ = second
}

// R51: each idle departure runs on a goroutine of its own. A lone viewer's
// release can stop its channel and wait out StopWait; on the sweeper's own
// goroutine that would delay every other departure.
func TestASlowDepartureDoesNotDelayTheNextTick(t *testing.T) {
	clock := newFakeClock()
	tick := make(chan time.Time)
	table := NewTable(Config{Now: clock.Now, Tick: tick})
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	go table.Run(ctx)

	gate := make(chan struct{})
	var releaseGate sync.Once
	open := func() { releaseGate.Do(func() { close(gate) }) }
	t.Cleanup(open)

	var mu sync.Mutex
	released := map[string]bool{}
	owner := &fakeOwner{name: "c1", j: &journal{}}
	add := func(id string, block bool) {
		s := &Session{ID: "sid-" + id, Owner: owner, Key: "hls", Pipeline: &hls.Pipeline{}, TD: 2 * time.Second}
		table.Add(s, &channel.Client{ID: id}, Releases{Client: func() {
			if block {
				<-gate
			}
			mu.Lock()
			released[id] = true
			mu.Unlock()
		}})
		table.Activate(s.ID)
	}

	add("slow", true)
	clock.Advance(IdleTimeout(2 * time.Second))
	send(t, tick) // the slow departure starts and blocks in its Client release

	add("fast", false)
	clock.Advance(IdleTimeout(2 * time.Second))
	send(t, tick) // must be consumed although the slow departure is still running
	waitUntil(t, "the fast session's departure", func() bool {
		mu.Lock()
		defer mu.Unlock()
		return released["fast"]
	})
	mu.Lock()
	slowDone := released["slow"]
	mu.Unlock()
	if slowDone {
		t.Fatal("the slow departure finished before its gate opened; the case is not the one it names")
	}
	open()
	waitUntil(t, "the slow departure", func() bool {
		mu.Lock()
		defer mu.Unlock()
		return released["slow"]
	})
}
