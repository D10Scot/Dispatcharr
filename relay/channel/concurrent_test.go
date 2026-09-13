package channel

import (
	"context"
	"io"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// waitForStart blocks until at least one source has entered Run, and returns
// how many had by then. A deadline rather than a sleep: a fixed wait either
// costs four hundred rounds of it or races anyway.
func waitForStart(t *testing.T, c *sourceCounter, round int) int {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, started := c.snapshot(); started > 0 {
			return started
		}
		if time.Now().After(deadline) {
			t.Fatalf("round %d: no source started within five seconds", round)
		}
		time.Sleep(100 * time.Microsecond)
	}
}

// A source that counts how many are running right now and how many ever ran.
type countingSource struct{ c *sourceCounter }

func (s countingSource) Run(ctx context.Context, _ io.Writer) error {
	s.c.enter()
	defer s.c.leave()
	<-ctx.Done()
	return ctx.Err()
}

type sourceCounter struct {
	mu      sync.Mutex
	running int
	started int
}

func (c *sourceCounter) enter() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.running++
	c.started++
}

func (c *sourceCounter) leave() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.running--
}

func (c *sourceCounter) snapshot() (running, started int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.running, c.started
}

// THE ORDERING TEST. Eight clients tune one channel at once, four hundred
// times over. The properties are all-or-nothing and none of them is a data
// race, which is exactly why this test exists: -race does not flag an
// ordering bug, and every assertion below was violated by a version of
// Attach that passed -race cleanly.
//
// What went wrong in that version: the gate closed when the START finished
// rather than when Attach returned, so a waiter woken by it raced the
// caller's own map insertion, found neither a channel nor a gate, and
// started a SECOND upstream. The visible damage was a second provider
// connection with no map entry and nothing that would ever stop it, and a
// first client whose release tore down the other client's channel.
func TestConcurrentFirstClientsStartExactlyOneSource(t *testing.T) {
	const clients = 8
	const rounds = 400

	for round := range rounds {
		counter := &sourceCounter{}
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})

		var wg sync.WaitGroup
		seen := make([]*Channel, clients)
		releases := make([]func(), clients)
		errs := make([]error, clients)
		for i := range clients {
			wg.Add(1)
			go func() {
				defer wg.Done()
				c, release, err := m.Attach("one", func() (Source, Tuning, error) {
					return countingSource{c: counter}, testTuning(), nil
				})
				seen[i], releases[i], errs[i] = c, release, err
			}()
		}
		wg.Wait()

		for i, err := range errs {
			if err != nil {
				t.Fatalf("round %d: client %d failed to attach: %v", round, i, err)
			}
		}
		for i, c := range seen {
			if c != seen[0] {
				t.Fatalf("round %d: client %d got a different *Channel from client 0: "+
					"two clients of one channel are watching two different upstreams",
					round, i)
			}
		}
		// Polled up, then bounded. publish starts the source goroutine and
		// returns without waiting for it to be scheduled, so asserting the
		// count immediately races Go's scheduler rather than the code -- which
		// this test did on round 122 of its first run, reporting zero sources
		// where the defect it hunts reports two. Wait for the first, then
		// require that there is only one.
		started := waitForStart(t, counter, round)
		if started != 1 {
			t.Fatalf("round %d: %d sources were started for one channel, want 1 -- "+
				"a second provider connection was opened", round, started)
		}
		if got := m.Get("one"); got != seen[0] {
			t.Fatalf("round %d: the map holds %v, not the channel handed to clients -- "+
				"the channel clients are watching is unreachable and nothing can stop it",
				round, got)
		}
		if n := len(m.ids()); n != 1 {
			t.Fatalf("round %d: the manager holds %d channels for one id, want 1", round, n)
		}

		for _, release := range releases {
			release()
		}

		// Every source must be gone. A source still running after the last
		// client left is a leaked provider connection holding a slot.
		deadline := time.Now().Add(5 * time.Second)
		for {
			running, _ := counter.snapshot()
			if running == 0 {
				break
			}
			if time.Now().After(deadline) {
				t.Fatalf("round %d: %d source goroutines still running after every "+
					"client released -- a leaked provider connection", round, running)
			}
			time.Sleep(time.Millisecond)
		}
		if n := len(m.ids()); n != 0 {
			t.Fatalf("round %d: the manager still holds %d channels after every client released", round, n)
		}
		m.StopAll()
	}
}
