// Command relay-go is the Go relay. At stage 2c-1 it binds its port, answers
// /healthz and /readyz, and does nothing else: nginx routes no location to
// this process until stage 2d, and every route beyond the two health
// endpoints is behind the dev flag.
package main

import (
	"errors"
	"log"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/config"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/drain"
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
	// One control client for the tune path, the failover, the release on
	// teardown and the events; one emitter behind it, so an outage is logged
	// once for the whole process as control_plane.py's module flag does.
	client := &control.Client{Secret: cfg.Secret}
	emitter := control.NewEmitter(client, slog.Default())
	channels := channel.NewManager(channel.ManagerConfig{
		Events:  httpapi.EventSink(emitter),
		Release: httpapi.ReleaseVia(client, slog.Default()),
	})
	// ONE Lifecycle, shared by the tune path, /readyz and the drain. Two
	// would let the probe say "ready" while the handler refused every tune.
	lifecycle := &httpapi.Lifecycle{}
	srv := &http.Server{
		Addr: net.JoinHostPort("0.0.0.0", strconv.Itoa(cfg.Port)),
		Handler: httpapi.New(httpapi.Config{
			DevRoutes: cfg.DevRoutes,
			Stream: httpapi.StreamDeps{
				Secret:    cfg.Secret,
				Channels:  channels,
				Control:   client,
				Lifecycle: lifecycle,
			},
			Control: httpapi.ControlDeps{Secret: cfg.Secret, Channels: channels},
			Health:  httpapi.HealthDeps{Channels: channels, Lifecycle: lifecycle},
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

	// D6's drain. The handler is installed BEFORE ListenAndServe, so a
	// SIGTERM that arrives during startup is still drained rather than
	// killing the process with channels running -- supervisord sends one the
	// moment a `docker stop` lands, which can be inside startsecs=5.
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
	drained := make(chan struct{})
	go func() {
		defer close(drained)
		sig := <-signals
		log.Printf("received %s, draining", sig)
		drain.Run(drain.Deps{
			Gate:     lifecycle,
			Channels: channels,
			Server:   srv,
			Events:   emitter,
			Log:      slog.Default(),
		})
	}()

	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Printf("server stopped: %v", err) // credential-logging: ok - a net.Listen or Serve error naming the bind address
		os.Exit(1)
	}
	// ErrServerClosed means Shutdown was called, which only the drain does,
	// so wait for the rest of its sequence -- the emitter flush in
	// particular, which runs AFTER Shutdown returns. Exiting here would drop
	// every channel_stop of the shutdown.
	<-drained
}
