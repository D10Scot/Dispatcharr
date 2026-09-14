// Command relay-go is the Go relay. At stage 2c-1 it binds its port, answers
// /healthz and /readyz, and does nothing else: nginx routes no location to
// this process until stage 2d, and every route beyond the two health
// endpoints is behind the dev flag.
package main

import (
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/config"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/httpapi"
)

func main() {
	log.SetFlags(log.LstdFlags | log.LUTC)
	log.SetPrefix("relay-go: ")

	cfg, err := config.Load()
	if err != nil {
		// Exit rather than degrade. supervisord's startretries=20 will show
		// this line twenty times in the container log, which is the loud
		// failure a misconfigured secret deserves -- the alternative is a
		// process that serves health checks happily and 403s every internal
		// call with nothing saying why.
		log.Printf("startup failed: %v", err) // credential-logging: ok - config.Load's errors name a variable, a port, or the secret FILE's path, never the secret
		os.Exit(1)
	}

	// The secret is never logged, in any form, at any level -- not its value,
	// not its length, not a prefix. scripts/check_credential_logging.py polices
	// the Python side of this rule; there is no Go equivalent yet, so it is
	// held by hand here.
	log.Printf("starting on port %d (dev routes: %t)", cfg.Port, cfg.DevRoutes)

	// THE SAME manager, not a second one. Two would give the list endpoint
	// an empty map while the tune path filled another, and every assertion
	// about what the list shows would be about the wrong object.
	channels := channel.NewManager(channel.ManagerConfig{})
	srv := &http.Server{
		Addr: net.JoinHostPort("0.0.0.0", strconv.Itoa(cfg.Port)),
		Handler: httpapi.New(httpapi.Config{
			DevRoutes: cfg.DevRoutes,
			Stream: httpapi.StreamDeps{
				Secret:   cfg.Secret,
				Channels: channels,
				Control:  &control.Client{Secret: cfg.Secret},
			},
			Control: httpapi.ControlDeps{Secret: cfg.Secret, Channels: channels},
		}).Handler(),

		// ReadHeaderTimeout only. A read or write deadline on the whole
		// request would be wrong for this process by construction: serving
		// long-lived responses is the reason it exists, and it is why
		// docker/uwsgi.relay.ini carries no harakiri either. Bounding just
		// the header read closes the slow-header class without touching the
		// body, which is the stream.
		ReadHeaderTimeout: 10 * time.Second,

		// IdleTimeout bounds an idle KEEP-ALIVE connection -- the gap between
		// one request finishing and the next starting on the same socket. It
		// never touches a stream in flight, because a stream is one request
		// that has not finished, which is why this is safe on a process whose
		// whole purpose is long-lived responses. 120s is comfortably longer
		// than any client's gap between requests and short enough that an
		// abandoned socket does not outlive the session.
		IdleTimeout: 120 * time.Second,
	}

	// No graceful shutdown here. D6's SIGTERM drain is 2c-8's, and a
	// half-implemented drain -- one that stops accepting but does not wait for
	// anything, because there is nothing to wait for yet -- would look like
	// the feature while being the default. supervisord's stopwaitsecs=20
	// bounds the stop either way.
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Printf("server stopped: %v", err) // credential-logging: ok - a net.Listen or Serve error naming the bind address
		os.Exit(1)
	}
}
