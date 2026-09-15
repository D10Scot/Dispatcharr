package httpapi

import (
	"log/slog"
	"net/http"
	"sync/atomic"

	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// Lifecycle is the one bit of process state the health endpoints and the
// tune path share: whether this relay is draining.
//
// One flag, read from three places -- /readyz, the tune handler and the
// drain's own sequence -- rather than a flag per reader, because the whole
// point of D6's drain is that "stop accepting tunes" and "tell the load
// balancer to stop sending them" are the same decision made once.
type Lifecycle struct{ draining atomic.Bool }

// BeginDrain marks the process as draining. Idempotent.
func (l *Lifecycle) BeginDrain() { l.draining.Store(true) }

// Draining reports whether the drain has begun.
func (l *Lifecycle) Draining() bool { return l != nil && l.draining.Load() }

// HealthDeps is what the two operational endpoints need.
//
// Both were static 200s from 2c-1 through 2c-7, and 2c-1's own comment said
// why: "/readyz becomes meaningful in 2c-8, when the SIGTERM drain gives it
// something to report -- and that is also why this PR adds no Docker
// HEALTHCHECK: a probe wired to a static 200 reports healthy through every
// failure it exists to catch."
type HealthDeps struct {
	// Channels is what the readiness body counts. Nil reports zero, which is
	// what a process with no manager honestly has.
	Channels *channel.Manager

	// Lifecycle is the drain flag. Nil is never draining.
	Lifecycle *Lifecycle

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger
}

// readyPayload is what /readyz answers with.
//
// The counts are what makes it a real report rather than a second liveness
// probe: an operator watching a rolling restart can see the channel count
// fall to zero, and a readiness probe that only ever says "ok" cannot tell a
// relay that is serving from one that is about to stop.
type readyPayload struct {
	Status   string `json:"status"`
	Channels int    `json:"channels"`
	Clients  int    `json:"clients"`
}

// StatusReady and StatusDraining are readyPayload's two values.
const (
	StatusReady    = "ready"
	StatusDraining = "draining"
)

// ReadyHandler serves GET /readyz.
//
// WHAT "READY" MEANS HERE IS DELIBERATELY NARROW: this process is serving and
// is not draining. It does NOT probe the control plane, and that is a
// decision rather than an omission. A relay that marked itself unready during
// a Django outage would be taken out of nginx's rotation at stage 2d -- and
// a running stream needs nothing from Django at all once it is running
// (CLAUDE.md § Operationally: stopping api-uwsgi "does not disturb a running
// stream"), so deregistering would turn a degraded new-tune path into a total
// outage for viewers who were fine. The control plane's reachability is
// reported where it belongs, in the emitter's one-line-per-transition log.
//
// /healthz stays a static 200 and stays LIVENESS: it answers 200 throughout
// the drain, because a supervisor that restarted the process mid-drain would
// defeat the drain.
func ReadyHandler(deps HealthDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	return func(w http.ResponseWriter, _ *http.Request) {
		body := readyPayload{Status: StatusReady}
		if deps.Channels != nil {
			for _, c := range deps.Channels.Snapshot() {
				body.Channels++
				body.Clients += c.Clients()
			}
		}
		status := http.StatusOK
		if deps.Lifecycle.Draining() {
			body.Status = StatusDraining
			status = http.StatusServiceUnavailable
		}
		writeJSONStatus(w, log, status, body)
	}
}
