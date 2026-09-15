package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/drain"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// readyz answers what the drain flag says, and counts what the manager holds.
//
// Three states in one test -- empty, serving, draining -- because a body that
// always said "ready, 0, 0" would pass a test that only checked the first,
// and a probe that always said "ready" is the static 200 under a new name.
func TestReadyzReportsTheChannelCountAndTheDrain(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)

	status, body := r.readyz(t)
	if status != http.StatusOK || body.Status != StatusReady || body.Channels != 0 {
		t.Fatalf("an idle relay answered %d %+v, want 200 ready with no channels", status, body)
	}

	response := r.tuneAs(t, "c-ready", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	status, body = r.readyz(t)
	if status != http.StatusOK || body.Channels != 1 || body.Clients != 1 {
		t.Fatalf("a serving relay answered %d %+v, want 200 with one channel and one client", status, body)
	}

	r.Lifecycle.BeginDrain()
	status, body = r.readyz(t)
	if status != http.StatusServiceUnavailable || body.Status != StatusDraining {
		t.Fatalf("a draining relay answered %d %+v, want 503 draining", status, body)
	}
	// The counts are still real while draining -- an operator watching a
	// rolling restart reads them to see the channels fall to zero.
	if body.Channels != 1 {
		t.Errorf("a draining relay reported %d channels, want the 1 it still holds", body.Channels)
	}

	// /healthz stays 200 THROUGHOUT, and that is the distinction: liveness
	// must not fail during a drain, or a supervisor restarts the process
	// mid-teardown and defeats it.
	if code := r.healthz(t); code != http.StatusOK {
		t.Errorf("/healthz answered %d while draining, want 200", code)
	}
}

// A tune that arrives after the gate is up is refused 503, before any
// control-plane call.
//
// BOTH halves: the status AND the absence of a next-source call, because a
// relay that reserved a provider slot and then refused the viewer would leave
// Django holding a slot nothing will release.
func TestATuneArrivingDuringTheDrainIsRefusedBeforeAnythingIsReserved(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	r.Lifecycle.BeginDrain()

	before := len(r.Control.RequestsTo("/next-source"))
	header := http.Header{}
	response := r.tune(t, "/proxy/ts/stream/c-late", header)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("a tune during the drain answered %d, want 503", response.StatusCode)
	}
	if got := response.Header.Get("Retry-After"); got == "" {
		t.Errorf("the refusal carries no Retry-After: a client has nothing to tell it to retry")
	}
	if after := len(r.Control.RequestsTo("/next-source")); after != before {
		t.Errorf("the refused tune still made %d next-source calls", after-before)
	}
}

// The whole sequence over a real manager, a real client and a real emitter.
//
// THE CLOCK STARTS BEFORE THE DRAIN DOES, which is the property this
// assertion needs: `started` is taken before Run is called, not inside it,
// so the measurement cannot miss time the drain's own setup spent.
func TestTheDrainStopsTheChannelEndsTheClientAndFlushesTheEvents(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-drain", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 10)
	waitForHead(t, r, "c-drain", 1)

	started := time.Now()
	elapsed := drain.Run(drain.Deps{
		Gate:     r.Lifecycle,
		Channels: r.Manager,
		Events:   r.Emitter,
		// No Server: the rig's httptest server is torn down by its own
		// cleanup, and Shutdown on it would race that.
		ClientGrace: 100 * time.Millisecond,
		Budget:      6 * time.Second,
	})
	measured := time.Since(started)

	if measured > 6*time.Second {
		t.Fatalf("the drain took %s against a 6s budget", measured)
	}
	if elapsed < 100*time.Millisecond {
		t.Errorf("the drain reported %s, which is less than the client grace it was given: "+
			"the grace was skipped", elapsed)
	}
	if r.Manager.Get("c-drain") != nil {
		t.Fatalf("the channel is still running after the drain")
	}

	// The client's response body ENDS rather than hanging: the ring closed,
	// serveClient returned, and the chunked response was terminated.
	done := make(chan error, 1)
	go func() {
		_, err := io.Copy(io.Discard, response.Body)
		done <- err
	}()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatalf("the client's response never ended after the drain")
	}

	// channel_stop reached the control plane, which is what the flush is
	// for: it is raised by the teardown the drain performs, so an emitter
	// closed before the teardown would lose it.
	stops := r.Control.EventsOfType("channel_stop")
	if len(stops) != 1 {
		t.Fatalf("the control plane saw %d channel_stop events, want 1: the flush runs AFTER "+
			"the teardown for exactly this reason", len(stops))
	}
	if stops[0].ChannelID != "c-drain" {
		t.Errorf("channel_stop named %q", stops[0].ChannelID)
	}
	runtime, ok := stops[0].Details["runtime"].(float64)
	if !ok || runtime < 0 {
		t.Errorf("channel_stop carries runtime %v, want the rounded seconds "+
			"_collect_channel_stop_event_data computes", stops[0].Details["runtime"])
	}
	if _, ok := stops[0].Details["total_bytes"]; !ok {
		t.Errorf("channel_stop carries no total_bytes")
	}
}

// readyz calls GET /readyz and decodes the body.
func (r *rig) readyz(t *testing.T) (int, readyPayload) {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+"/readyz", nil)
	if err != nil {
		t.Fatalf("building the readyz request: %v", err)
	}
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("GET /readyz: %v", err)
	}
	defer func() { _ = response.Body.Close() }()
	var body readyPayload
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decoding the readyz body: %v", err)
	}
	return response.StatusCode, body
}

func (r *rig) healthz(t *testing.T) int {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+"/healthz", nil)
	if err != nil {
		t.Fatalf("building the healthz request: %v", err)
	}
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("GET /healthz: %v", err)
	}
	defer func() { _ = response.Body.Close() }()
	_, _ = io.Copy(io.Discard, response.Body)
	return response.StatusCode
}
