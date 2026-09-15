package httpapi

import (
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// eventsOf waits for at least n events of a type and returns them.
func eventsOf(t *testing.T, r *rig, typ string, n int) []relaytest.RecordedEvent {
	t.Helper()
	var got []relaytest.RecordedEvent
	waitFor(t, "the "+typ+" event", 10*time.Second, func() bool {
		got = r.Control.EventsOfType(typ)
		return len(got) >= n
	})
	return got
}

// channel_start, raised where server.py:832-842 raises it, with the two
// details it carries.
//
// stream_id is asserted BOTH at the top level and inside details, because
// emit_event lifts it and LEAVES it (control_plane.py:331-333), and
// core/relay_events.py's _apply_stream_stats is written around that shape --
// a relay that lifted without leaving would be a silent loss there.
func TestATuneRaisesChannelStart(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-start", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	starts := eventsOf(t, r, "channel_start", 1)
	if len(starts) != 1 {
		t.Fatalf("the control plane saw %d channel_start events, want 1", len(starts))
	}
	if starts[0].ChannelID != "c-start" {
		t.Errorf("channel_start named channel %q", starts[0].ChannelID)
	}
	if starts[0].StreamID == nil || *starts[0].StreamID != 1 {
		t.Errorf("channel_start's top-level stream_id is %v, want 1", starts[0].StreamID)
	}
	if got, ok := starts[0].Details["stream_id"].(float64); !ok || int(got) != 1 {
		t.Errorf("channel_start's details lost stream_id (%v): emit_event LEAVES it there "+
			"as well as lifting it", starts[0].Details["stream_id"])
	}
	if _, ok := starts[0].Details["stream_name"]; !ok {
		t.Errorf("channel_start carries no stream_name")
	}
}

// client_connect is raised for BOTH client types (Amendment A6.5), and
// client_disconnect for the TS one ONLY.
//
// ONE TEST FOR BOTH HALVES, and that is what makes it able to fail: a relay
// that raised client_connect for TS alone, or client_disconnect for both,
// would pass a test that looked at one client type. The fMP4 asymmetry is
// Python's -- emit_event appears exactly once in output/fmp4/generator.py,
// at :114 -- and it is reproduced, not evened out.
func TestBothClientTypesConnectAndOnlyTheTSOneDisconnects(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-events", "client-ts")
	packetRun(t, "the TS client", ts.Body, 1)
	fmp4 := r.tuneFMP4(t, "c-events", "client-fmp4")
	if got := readAtLeast(fmp4.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatalf("the fMP4 client received nothing")
	}

	connects := eventsOf(t, r, "client_connect", 2)
	seen := map[string]bool{}
	for _, e := range connects {
		seen[e.ClientID] = true
		if e.ChannelID != "c-events" {
			t.Errorf("client_connect named channel %q", e.ChannelID)
		}
		// client_id is lifted to the top level AND left in details, the same
		// two-name rule stream_id follows (control_plane.py:331-333).
		if got, _ := e.Details["client_id"].(string); got != e.ClientID {
			t.Errorf("client_connect's details carry client_id %q where the top level carries %q", got, e.ClientID)
		}
		if e.Details["client_ip"] != "198.51.100.4" {
			t.Errorf("client_connect carries client_ip %v, want the hop's address", e.Details["client_ip"])
		}
	}
	for _, want := range []string{"client-ts", "client-fmp4"} {
		if !seen[want] {
			t.Errorf("no client_connect for %s: Amendment A6.5 owes it for BOTH client types", want)
		}
	}

	// Both clients leave. Only the TS one announces it.
	_ = ts.Body.Close()
	_ = fmp4.Body.Close()
	disconnects := eventsOf(t, r, "client_disconnect", 1)
	if len(disconnects) != 1 {
		t.Fatalf("the control plane saw %d client_disconnect events, want exactly 1 -- the "+
			"fMP4 generator raises none (emit_event appears once in that file, at :114)", len(disconnects))
	}
	if disconnects[0].ClientID != "client-ts" {
		t.Errorf("client_disconnect named %q, want the TS client", disconnects[0].ClientID)
	}
	if _, ok := disconnects[0].Details["duration"].(float64); !ok {
		t.Errorf("client_disconnect carries duration %v, want a number (round(elapsed, 2))",
			disconnects[0].Details["duration"])
	}
	if _, ok := disconnects[0].Details["bytes_sent"].(float64); !ok {
		t.Errorf("client_disconnect carries bytes_sent %v, want a number",
			disconnects[0].Details["bytes_sent"])
	}
}

// Stopping a channel through the control route raises channel_stop, with the
// runtime and the byte total _collect_channel_stop_event_data snapshots.
func TestStoppingAChannelRaisesChannelStop(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-stopevent", "client-a")
	packetRun(t, "the client", response.Body, 10)
	waitForHead(t, r, "c-stopevent", 1)

	if status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-stopevent", nil); status != http.StatusOK {
		t.Fatalf("DELETE answered %d: %s", status, raw)
	}
	_ = response.Body.Close()

	// CLOSE THE EMITTER BEFORE COUNTING, and that is the whole difference
	// between "at least one" and "exactly one". eventsOf returns as soon as
	// the first event lands, so a second raise arriving a moment later is
	// invisible to a len() check that runs immediately after it -- the same
	// latch-that-fires-early hazard Constraint 55 names, relocated from a
	// wait into an assertion. Close drains the queue and waits for the
	// worker, so after it there is nothing in flight to arrive late.
	// Demonstrated: with a second c.emitStop() injected into Manager.Stop,
	// the at-least-one shape passed 6/6 and this one reddens.
	eventsOf(t, r, "channel_stop", 1)
	r.Emitter.Close()
	stops := r.Control.EventsOfType("channel_stop")
	if len(stops) != 1 {
		t.Fatalf("the control plane saw %d channel_stop events, want exactly 1: a channel "+
			"announces its ending from ONE place, run's deferred emitStop (Ruling R9)", len(stops))
	}
	if stops[0].ChannelID != "c-stopevent" {
		t.Errorf("channel_stop named %q", stops[0].ChannelID)
	}
	total, ok := stops[0].Details["total_bytes"].(float64)
	if !ok || total <= 0 {
		t.Errorf("channel_stop carries total_bytes %v, want the bytes the ring took",
			stops[0].Details["total_bytes"])
	}
}

// A TS client's detail row carries the three byte counters and an fMP4
// client's does not.
//
// THE ASYMMETRY IS THE ASSERTION, and both halves are in one test: a relay
// that recorded bytes for every client would satisfy "the TS client has
// counters" on its own, and one that recorded none would satisfy "the fMP4
// client has none".
func TestOnlyATSClientsDetailRowCarriesTheByteCounters(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-counters", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	packetRun(t, "the TS client", ts.Body, 100)
	fmp4 := r.tuneFMP4(t, "c-counters", "client-fmp4")
	defer func() { _ = fmp4.Body.Close() }()
	// PAST THE INIT SEGMENT, deliberately: serveFMP4 writes the init BEFORE
	// the fragment loop starts, so a read that stopped there would query the
	// detail endpoint before the loop had run once -- and an fMP4 row with
	// no counters would then prove nothing, since a client that had sent
	// nothing would have none either way. Break-check 9 stayed GREEN until
	// this read was widened.
	want := len(relaytest.SyntheticFMP4Init()) + 2*len(relaytest.SyntheticFMP4Fragment(0))
	if got := readAtLeast(fmp4.Body, want, 15*time.Second); len(got) < want {
		t.Fatalf("the fMP4 client received %d bytes, want at least %d -- past the init "+
			"segment and into the fragment loop", len(got), want)
	}

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-counters", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	rows, ok := decodeObject(t, raw)["clients"].([]any)
	if !ok || len(rows) != 2 {
		t.Fatalf("the detail endpoint lists %v clients, want 2", len(rows))
	}
	byID := map[string]map[string]any{}
	for _, row := range rows {
		client, ok := row.(map[string]any)
		if !ok {
			t.Fatalf("a client row is not an object")
		}
		id, _ := client["client_id"].(string)
		byID[id] = client
	}

	tsRow, fmp4Row := byID["client-ts"], byID["client-fmp4"]
	if tsRow == nil || fmp4Row == nil {
		t.Fatalf("the detail endpoint listed %v, want both clients", byID)
	}
	for _, key := range []string{"bytes_sent", "avg_rate_KBps", "current_rate_KBps"} {
		if _, present := tsRow[key]; !present {
			t.Errorf("the TS client's row has no %q: output/ts/generator.py:511-519 writes it", key)
		}
		if _, present := fmp4Row[key]; present {
			t.Errorf("the fMP4 client's row carries %q as %v: output/fmp4/generator.py writes "+
				"last_active and nothing else (:288-295)", key, fmp4Row[key])
		}
	}
	if sent, _ := tsRow["bytes_sent"].(float64); sent <= 0 {
		t.Errorf("the TS client's bytes_sent is %v after 100 packets", tsRow["bytes_sent"])
	}
	// Both rows DO carry last_active, so "the fMP4 row is empty" cannot be
	// what makes the absences above pass.
	for id, row := range map[string]map[string]any{"client-ts": tsRow, "client-fmp4": fmp4Row} {
		if _, present := row["last_active"]; !present {
			t.Errorf("%s has no last_active, which both generators write", id)
		}
	}
}
