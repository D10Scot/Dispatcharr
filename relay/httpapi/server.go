// Package httpapi serves the relay's public HTTP surface: the live TS stream
// routes, the XC live roots, and the operational endpoints.
//
// At 2c-1 it serves the two operational endpoints and one gated stub. Nothing
// routes to this process from nginx until stage 2d, and the stub is behind
// the dev flag as well, so this PR is inert in every deployment shape twice
// over.
package httpapi

import (
	"fmt"
	"net/http"
)

// Config is what the server needs to build its routing table.
type Config struct {
	// DevRoutes gates every route that is not an operational endpoint.
	DevRoutes bool

	// Stream is what the live TS handler needs. Only read when DevRoutes is
	// set.
	Stream StreamDeps

	// Control is what the internal control routes need. Only read when
	// DevRoutes is set.
	Control ControlDeps
}

// Server owns the routing table. One per process.
//
// Deliberately holds no copy of its Config: `New` reads cfg.DevRoutes to
// decide the table and nothing reads it afterwards, so storing it would be
// a field with no reader. 2c-2 adds whatever state it actually needs;
// keeping an unread field here in anticipation is how `unused` findings
// and stale duplicates of the truth both start.
type Server struct {
	mux *http.ServeMux
}

// New builds the routing table from cfg. The table is fixed at construction:
// no route is added or removed after this returns, so the mux is read-only
// for the life of the process and needs no lock.
func New(cfg Config) *Server {
	s := &Server{mux: http.NewServeMux()}

	// Always served, in every shape. D6: the Python relay has neither a
	// health endpoint nor a readiness probe, and both are a few lines here.
	//
	// Both are a static 200 at 2c-1, which is what this PR's row specifies.
	// /readyz becomes meaningful in 2c-8, when the SIGTERM drain gives it
	// something to report -- and that is also why this PR adds no Docker
	// HEALTHCHECK: a probe wired to a static 200 reports healthy through
	// every failure it exists to catch.
	s.mux.HandleFunc("GET /healthz", ok)
	s.mux.HandleFunc("GET /readyz", ok)

	if cfg.DevRoutes {
		// The dev-only route flag spec line 1795 names.
		s.mux.Handle("GET /proxy/ts/stream/{channelID}", StreamHandler(cfg.Stream))
		// Gated with the rest: nginx routes nothing to this process until
		// stage 2d, and Django still calls the Python relay's copy of these
		// routes. All five of § The contract's Django-to-relay table are here
		// as of 2c-8; the collection GET landed in 2c-3.
		//
		// ONE GATE PER ROUTE rather than a wrapper around the mux: the two
		// health endpoints must stay ungated (a probe holds no SECRET_KEY),
		// and a middleware with an exception list is one edit away from
		// exempting a route it should not.
		internal := func(h http.HandlerFunc) http.Handler {
			return RequireInternal(cfg.Control.Secret, cfg.Control.Now, h)
		}
		s.mux.Handle("GET /proxy/relay/channels", internal(ChannelsHandler(cfg.Control)))
		s.mux.Handle("GET /proxy/relay/channels/{channelID}", internal(ChannelHandler(cfg.Control)))
		s.mux.Handle("DELETE /proxy/relay/channels/{channelID}", internal(ChannelHandler(cfg.Control)))
		s.mux.Handle("DELETE /proxy/relay/channels/{channelID}/clients/{clientID}", internal(ClientHandler(cfg.Control)))
		s.mux.Handle("POST /proxy/relay/channels/{channelID}/advance", internal(AdvanceHandler(cfg.Control)))
	}

	return s
}

// Handler returns the routing table as an http.Handler, for ListenAndServe
// and for tests. Tests drive this, never a hand-built handler: a test that
// builds its own handler asserts that net/http calls functions.
func (s *Server) Handler() http.Handler { return s.mux }

func ok(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	// The error is discarded deliberately, and `_, _ =` rather than a bare
	// call so errcheck can see that it was a decision: a failed write to a
	// health probe means the prober hung up mid-response. There is nothing
	// to recover and nobody to tell, and logging it would turn a flapping
	// probe into log spam. Every other write path in this module handles
	// its error.
	_, _ = fmt.Fprintln(w, "ok")
}
