// Package drain is the relay's SIGTERM shutdown: spec D6's "drain-on-SIGTERM,
// /healthz, /readyz, wired to supervisord stopwaitsecs and a Docker
// HEALTHCHECK".
//
// WHAT IT IMPROVES ON, DELIBERATELY. The Python relay runs uWSGI's
// `die-on-term` with no drain at all, so "every deploy still drops every
// viewer" (CLAUDE.md § Operationally). D6 names that as a real gap this phase
// closes in a language where a drain loop is a few dozen lines, so this is a
// STATED DIVERGENCE FROM PARITY rather than a port -- the one place in stage
// 2c where the Go relay is meant to behave differently from the Python one,
// and D5's parity rule does not cover it because D6 supersedes it here.
//
// THE BUDGET, DERIVED RATHER THAN CHOSEN. docker/supervisord.d/relay-go.conf
// carries stopwaitsecs=20 at priority=205, the SAME priority group as
// relay-uwsgi (whose stopwaitsecs is also 20). supervisord signals one
// priority group at a time and waits out that group's longest stopwaitsecs
// before moving on, so this group costs max(20, 20) = 20s and the container's
// whole stop budget is 155s against docker-compose's 160s
// stop_grace_period. Twenty seconds is therefore the hard ceiling on
// everything below, and DefaultBudget leaves five of them as margin for
// supervisord's own signalling and the process's exit.
package drain

import (
	"context"
	"log/slog"
	"time"
)

// The budget and its two sub-budgets. Every one of them is a Go-side
// constant rather than a setting on the wire, and that is the one place
// Global Constraint 13 does not apply: these describe THIS PROCESS'S
// shutdown against THIS DEPLOYMENT'S supervisord configuration, which is in
// the image beside the binary, not a value an operator changes in the UI.
const (
	// DefaultBudget bounds the whole sequence. 15s against
	// stopwaitsecs=20, leaving 5s of margin.
	DefaultBudget = 15 * time.Second

	// DefaultClientGrace is how long connected viewers keep being served
	// after the signal, while no new tune is accepted. This is D6's "lets
	// running clients finish or cuts them at a bound" -- a live stream never
	// finishes, so the bound is the operative half, and what the grace buys
	// is five more seconds of a player's buffer across a rolling restart
	// rather than an instant cut.
	DefaultClientGrace = 5 * time.Second

	// DefaultEventsBudget bounds the emitter flush. Deliberately SHORTER
	// than control.Client's own worst case for one batch (two attempts of
	// (2s, 5s) plus the retry delay, ~14.1s): exiting inside the supervisord
	// window matters more than the last batch of events, and an event lost
	// to a shutdown is the behaviour control_plane.py already has ("an event
	// raised while the control plane is down is LOST, not queued").
	DefaultEventsBudget = 3 * time.Second
)

// Server is the http.Server half: everything this package needs of it.
type Server interface {
	Shutdown(ctx context.Context) error
}

// Channels is the manager half.
type Channels interface {
	// StopAll tears every channel down and returns when they are all done.
	StopAll()
}

// Events is the emitter half.
type Events interface {
	// Close stops the worker once the queue has drained.
	Close()
}

// Gate is the lifecycle flag: what makes new tunes stop being accepted and
// /readyz start answering 503.
type Gate interface {
	BeginDrain()
}

// Deps is everything Run needs. Every field except Log and Now is required;
// a nil one is skipped rather than panicked on, so a partially-wired process
// still exits.
type Deps struct {
	Gate     Gate
	Channels Channels
	Server   Server
	Events   Events

	Log *slog.Logger
	Now func() time.Time

	// Budget, ClientGrace and EventsBudget default to the three constants
	// above when zero.
	Budget       time.Duration
	ClientGrace  time.Duration
	EventsBudget time.Duration
}

// Run performs the drain and reports how long it took.
//
// THE ORDER IS THE WHOLE DESIGN, and every step is there because the step
// after it would be wrong without it:
//
//  1. Raise the gate. New tunes answer 503 and /readyz answers 503, so
//     nothing new is started and, at stage 2d, nginx stops routing here.
//  2. Serve the connected viewers for ClientGrace. The upstream is still
//     running and the ring is still filling, so this is the only step that
//     is FOR the viewer rather than for the deployment.
//  3. Stop every channel, concurrently. This is what ends the client
//     goroutines: each channel's ring closes, every serveClient loop sees
//     ErrClosed and returns, each output pipeline is stopped by run's own
//     defers, and each provider slot is released through the control plane
//     by Channel.releaseSlot. WITHOUT THIS STEP Shutdown BELOW WOULD BLOCK
//     FOR EVER -- a live stream is one request that never finishes, and
//     http.Server.Shutdown waits for in-flight requests.
//  4. Shut the server down. By now the handlers have returned, so this
//     closes the listener and the idle connections and returns at once.
//  5. Flush the emitter. LAST, because steps 3 and 4 are what RAISE the
//     events this flush exists to deliver -- one channel_stop per channel
//     and one client_disconnect per TS viewer.
//
// Steps 2 to 4 share one deadline -- each gets what the ones before it left --
// and step 5's budget is RESERVED out of the total rather than being whatever
// is left, so a slow teardown costs the shutdown its wait and never costs the
// events their delivery.
func Run(d Deps) time.Duration {
	log := d.Log
	if log == nil {
		log = slog.Default()
	}
	now := d.Now
	if now == nil {
		now = time.Now
	}
	budget, grace, eventsBudget := d.Budget, d.ClientGrace, d.EventsBudget
	if budget <= 0 {
		budget = DefaultBudget
	}
	if grace <= 0 {
		grace = DefaultClientGrace
	}
	if eventsBudget <= 0 {
		eventsBudget = DefaultEventsBudget
	}

	// THE EVENTS FLUSH IS RESERVED, not left whatever the earlier steps
	// happen to leave. A channel teardown that used the whole budget would
	// otherwise reach the flush with nothing left and exit having raised a
	// channel_stop per channel and delivered none of them -- which is the
	// one thing the flush is for. Clamped to a third of the budget so a
	// caller cannot reserve more than it has.
	if eventsBudget > budget/3 {
		eventsBudget = budget / 3
	}
	started := now()
	deadline := started.Add(budget)
	// What the gate, the grace, the teardown and the shutdown share.
	teardownDeadline := deadline.Add(-eventsBudget)

	if d.Gate != nil {
		d.Gate.BeginDrain()
	}
	log.Info("draining", "budget", budget, "client_grace", grace)

	// 2. The grace, bounded by the teardown deadline as everything before
	// the flush is.
	if remaining := teardownDeadline.Sub(now()); remaining > 0 {
		wait := min(grace, remaining)
		timer := time.NewTimer(wait)
		<-timer.C
		timer.Stop()
	}

	// 3. Stop every channel. Bounded by the manager's own per-channel
	// StopWait, which the concurrent sweep makes a single wait rather than
	// N of them; the select is the backstop for a channel whose source
	// goroutine ignores its context entirely.
	if d.Channels != nil {
		waitFor(log, "the channels to stop", teardownDeadline.Sub(now()), d.Channels.StopAll)
	}

	// 4. Close the listener and the idle connections.
	if d.Server != nil {
		ctx, cancel := context.WithDeadline(context.Background(), teardownDeadline)
		if err := d.Server.Shutdown(ctx); err != nil {
			// A deadline here means a request is still in flight after every
			// channel was stopped -- worth a line, and never a reason not to
			// flush the events below.
			log.Warn("the HTTP server did not shut down inside the drain budget", "error", err) // credential-logging: ok - http.Server.Shutdown returns the context's own error
		}
		cancel()
	}

	// 5. Flush the events raised by steps 3 and 4.
	if d.Events != nil {
		waitFor(log, "the relay events to flush", eventsBudget, d.Events.Close)
	}

	elapsed := now().Sub(started)
	log.Info("drained", "elapsed", elapsed)
	return elapsed
}

// waitFor runs fn on its own goroutine and waits at most `within` for it.
//
// A goroutine rather than a direct call because every step here has to be
// bounded by the shared deadline, and none of the three underlying calls
// takes a context: Manager.StopAll waits on its own per-channel timers and
// Emitter.Close waits on a worker that may be inside a control-plane call.
// A goroutine that outlives the wait is deliberate and costs nothing -- the
// process is about to exit, and the alternative is blocking past the
// supervisord window and being SIGKILLed with the rest of the drain undone.
func waitFor(log *slog.Logger, what string, within time.Duration, fn func()) {
	done := make(chan struct{})
	go func() {
		defer close(done)
		fn()
	}()
	if within <= 0 {
		log.Warn("no time left in the drain budget", "for", what)
		return
	}
	timer := time.NewTimer(within)
	defer timer.Stop()
	select {
	case <-done:
	case <-timer.C:
		log.Warn("the drain budget ran out", "waiting_for", what, "waited", within)
	}
}
