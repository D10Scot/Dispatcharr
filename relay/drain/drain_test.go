package drain

import (
	"context"
	"sync"
	"testing"
	"time"
)

// The three budgets are Go-side constants that answer to ONE external number:
// docker/supervisord.d/relay-go.conf's stopwaitsecs=20, after which
// supervisord SIGKILLs this process. Pinned as an arithmetic relationship
// rather than as three literals, so a later change to any of them has to keep
// the sum inside the window it exists to fit.
func TestTheBudgetFitsInsideSupervisordsStopWindow(t *testing.T) {
	// docker/supervisord.d/relay-go.conf:34. Written here as a literal
	// because it lives in a file this package cannot read, and the plan's
	// docker/supervisord.d/relay-go.conf:34, which the plan's Task 8 changes
	// together with this constant when either moves.
	const supervisordStopWait = 20 * time.Second

	if DefaultBudget >= supervisordStopWait {
		t.Fatalf("DefaultBudget is %s against a stopwaitsecs of %s: the drain would be "+
			"SIGKILLed partway through, losing every release and every channel_stop",
			DefaultBudget, supervisordStopWait)
	}
	if margin := supervisordStopWait - DefaultBudget; margin < 3*time.Second {
		t.Errorf("only %s of margin between the drain budget and stopwaitsecs; supervisord's "+
			"own signalling and the process exit need room", margin)
	}
	if DefaultClientGrace+DefaultEventsBudget >= DefaultBudget {
		t.Errorf("the client grace (%s) and the events flush (%s) already exceed the whole "+
			"budget (%s), leaving nothing for the channel teardown between them",
			DefaultClientGrace, DefaultEventsBudget, DefaultBudget)
	}
}

type fakeGate struct {
	mu    sync.Mutex
	began bool
}

func (f *fakeGate) BeginDrain() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.began = true
}

func (f *fakeGate) Began() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.began
}

// recorder records the order the drain calls its dependencies in, which is
// the whole design: the gate first, the channels before the server, the
// events last.
type recorder struct {
	mu    sync.Mutex
	order []string

	stopFor  time.Duration
	closeFor time.Duration

	// gateSeenAt is what the gate had been set to when StopAll ran, which is
	// how "no new tune is accepted before anything is torn down" is asserted
	// rather than assumed.
	gate       *fakeGate
	gateAtStop bool
}

func (r *recorder) note(what string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.order = append(r.order, what)
}

func (r *recorder) Order() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]string(nil), r.order...)
}

func (r *recorder) StopAll() {
	r.note("channels")
	r.mu.Lock()
	if r.gate != nil {
		r.gateAtStop = r.gate.Began()
	}
	r.mu.Unlock()
	time.Sleep(r.stopFor)
}

func (r *recorder) Shutdown(ctx context.Context) error {
	r.note("server")
	return ctx.Err()
}

func (r *recorder) Close() {
	r.note("events")
	time.Sleep(r.closeFor)
}

// The order, and the gate being up before anything is torn down.
//
// THE CLOCK STARTS BEFORE Run IS CALLED, which is the one property a timing
// assertion here has to have: a measurement taken inside the thing being
// measured cannot see the time its own setup spent.
func TestTheDrainRaisesTheGateFirstAndFlushesTheEventsLast(t *testing.T) {
	gate := &fakeGate{}
	rec := &recorder{gate: gate}

	started := time.Now()
	elapsed := Run(Deps{
		Gate:        gate,
		Channels:    rec,
		Server:      rec,
		Events:      rec,
		ClientGrace: 20 * time.Millisecond,
		Budget:      2 * time.Second,
	})
	measured := time.Since(started)

	if !gate.Began() {
		t.Errorf("the gate was never raised: new tunes would have been accepted throughout")
	}
	if !rec.gateAtStop {
		t.Errorf("the channels were torn down before the gate went up: a tune arriving in " +
			"that window starts a channel the drain has already walked past")
	}
	want := []string{"channels", "server", "events"}
	got := rec.Order()
	if len(got) != len(want) {
		t.Fatalf("the drain called %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("the drain called %v, want %v -- the order is the design: the channels "+
				"must stop before Shutdown (a live stream is a request that never finishes) "+
				"and the events must flush last (the teardown is what raises them)", got, want)
		}
	}
	if elapsed > measured {
		t.Errorf("Run reported %s but the wall clock outside it saw only %s", elapsed, measured)
	}
}

// A dependency that never returns does not push the drain past its budget.
//
// The failure this exists to catch is the one that matters operationally: a
// channel whose source goroutine ignores its context, or a control plane that
// black-holes the events POST, must cost the deployment a warning line and
// not a SIGKILL partway through the teardown.
func TestADependencyThatHangsDoesNotOverrunTheBudget(t *testing.T) {
	rec := &recorder{stopFor: time.Hour, closeFor: time.Hour}

	// RUN ON ITS OWN GOROUTINE with a select, so an overrun fails in seconds
	// and NAMES THE MECHANISM rather than hanging until the package's
	// ten-minute test timeout -- which is what break-check 22 produced
	// before this was restructured, and a ten-minute break-check is an
	// obstacle to whoever runs it next. THE CLOCK STILL STARTS BEFORE Run.
	started := time.Now()
	type result struct{ elapsed time.Duration }
	done := make(chan result, 1)
	go func() {
		done <- result{Run(Deps{
			Gate:         &fakeGate{},
			Channels:     rec,
			Server:       rec,
			Events:       rec,
			ClientGrace:  10 * time.Millisecond,
			Budget:       300 * time.Millisecond,
			EventsBudget: time.Hour,
		})}
	}()
	var elapsed time.Duration
	select {
	case r := <-done:
		elapsed = r.elapsed
	case <-time.After(5 * time.Second):
		t.Fatalf("the drain has not returned after 5s against a 300ms budget: a hung " +
			"dependency is exactly what the shared deadline and the events-budget clamp " +
			"exist to bound, and supervisord SIGKILLs at stopwaitsecs either way")
	}
	measured := time.Since(started)

	if measured > time.Second {
		t.Fatalf("the drain took %s against a 300ms budget: a hung channel teardown is "+
			"exactly what the shared deadline exists to bound", measured)
	}
	if elapsed > 500*time.Millisecond {
		t.Errorf("Run reported %s, want something close to its 300ms budget", elapsed)
	}
	// And it still ran every step: a drain that bailed out on the first
	// timeout would leave the events unflushed, which is the case the
	// ordering above exists for.
	if got := rec.Order(); len(got) != 3 {
		t.Errorf("the drain called %v, want all three steps even when the first one hangs", got)
	}
}

// Every dependency is optional, and a partially-wired process still exits.
func TestRunWithNoDependenciesReturns(t *testing.T) {
	if elapsed := Run(Deps{ClientGrace: time.Millisecond, Budget: time.Second}); elapsed > time.Second {
		t.Fatalf("an empty drain took %s", elapsed)
	}
}
