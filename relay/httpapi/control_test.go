package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// internalCall makes one signed call to a /proxy/relay/... route and returns
// the status and the body.
//
// Signed the way the real Django client signs -- the static principal token
// plus the bound per-request one over the FULL path and the body -- because
// every one of these routes is behind RequireInternal and a test that
// bypassed the gate would be testing a handler no caller can reach.
func (r *rig) internalCall(t *testing.T, method, path string, body []byte) (int, []byte) {
	t.Helper()
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	request, err := http.NewRequestWithContext(t.Context(), method, r.Relay.URL+path, reader)
	if err != nil {
		t.Fatalf("building the %s %s request: %v", method, path, err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
	request.Header.Set(control.HeaderInternalRequest,
		control.InternalRequestHeader(testSecret, method, path, body, time.Now().Unix()))
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	defer func() { _ = response.Body.Close() }()
	raw, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the %s %s body: %v", method, path, err)
	}
	return response.StatusCode, raw
}

func decodeObject(t *testing.T, raw []byte) map[string]any {
	t.Helper()
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatalf("decoding %q: %v", raw, err)
	}
	return out
}

// The detail endpoint over a RUNNING channel, not a struct literal: the
// golden pins the wire shape and this pins that the builder fills it from a
// real tune. Row 14's owner and row 17's ip_address are the two clauses this
// half can assert, and both are asserted against the LIST endpoint in the
// same test, because half a row is not a row (2c-3's own words).
func TestTheDetailEndpointRendersARunningChannel(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-detail", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)
	waitForHead(t, r, "c-detail", 1)

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-detail", nil)
	if status != http.StatusOK {
		t.Fatalf("GET the detail endpoint answered %d, want 200: %s", status, raw)
	}
	detail := decodeObject(t, raw)

	if detail["owner"] != OwnerUnknown {
		t.Errorf("owner is %v, want the literal %q (channel_status.py:45; row 14)", detail["owner"], OwnerUnknown)
	}
	if detail["channel_id"] != "c-detail" {
		t.Errorf("channel_id is %v", detail["channel_id"])
	}
	if detail["state"] == nil {
		t.Errorf("state is null on a channel that has recorded one")
	}

	clients, ok := detail["clients"].([]any)
	if !ok || len(clients) != 1 {
		t.Fatalf("the detail endpoint lists %v clients, want 1", detail["clients"])
	}
	client, ok := clients[0].(map[string]any)
	if !ok {
		t.Fatalf("the client row is not an object")
	}
	// ROW 17, on the detail endpoint: the address the authorize hop resolved
	// and carried on X-Relay-Client-IP, not the socket's peer -- which for a
	// loopback httptest server would be 127.0.0.1, so the assertion can fail.
	if client["ip_address"] != "198.51.100.4" {
		t.Errorf("ip_address is %v, want the hop's X-Relay-Client-IP", client["ip_address"])
	}
	if client["worker_id"] != WorkerUnknown {
		t.Errorf("worker_id is %v, want %q (channel_status.py:181's default; D2 deletes the worker)",
			client["worker_id"], WorkerUnknown)
	}

	// ROW 17's other half and row 14's other half, on the LIST endpoint, in
	// the same test and from the same running channel.
	listStatus, listRaw := r.listChannels(t, "?clients=all")
	if listStatus != http.StatusOK {
		t.Fatalf("the list endpoint answered %d", listStatus)
	}
	list := decodeObject(t, listRaw)
	listed, ok := list["channels"].([]any)[0].(map[string]any)
	if !ok {
		t.Fatalf("the list endpoint's first channel is not an object")
	}
	if listed["owner"] != nil {
		t.Errorf("owner on the list endpoint is %v, want null -- row 14 is an ASYMMETRY and "+
			"a test that checked one endpoint would prove nothing about the other", listed["owner"])
	}
	listedClient, ok := listed["clients"].([]any)[0].(map[string]any)
	if !ok {
		t.Fatalf("the list endpoint's first client is not an object")
	}
	if listedClient["ip_address"] != "198.51.100.4" {
		t.Errorf("ip_address on the list endpoint is %v, want the hop's", listedClient["ip_address"])
	}
}

// ?fields=state is the tune path's own read: two fields and nothing else,
// and a 404 with the SAME two-field shape for a channel this relay does not
// hold.
//
// Both halves in one test, because the 404 body is the thing that makes
// relay_client.get_channel able to map "not running" to None rather than to
// an outage, and a test that only checked the 200 would pass with a 404 that
// answered an HTML error page.
func TestFieldsStateAnswersTwoFieldsAndA404ForAnUnknownChannel(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-state", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-state?fields=state", nil)
	if status != http.StatusOK {
		t.Fatalf("?fields=state answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if len(body) != 2 {
		t.Errorf("?fields=state rendered %d keys, want exactly 2 (channel_id and state): %s", len(body), raw)
	}
	if body["channel_id"] != "c-state" || body["state"] == nil {
		t.Errorf("?fields=state answered %s", raw)
	}

	status, raw = r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-missing?fields=state", nil)
	if status != http.StatusNotFound {
		t.Fatalf("?fields=state for an unknown channel answered %d, want 404: %s", status, raw)
	}
	body = decodeObject(t, raw)
	if body["channel_id"] != "c-missing" {
		t.Errorf("the 404 body names %v, want the identifier asked about", body["channel_id"])
	}
	if state, present := body["state"]; !present || state != nil {
		t.Errorf("the 404 body's state is %v (present=%v), want an explicit null", state, present)
	}

	// And the FULL detail endpoint 404s with the same shape, which is what
	// relay_client.get_channel maps to None.
	status, raw = r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-missing", nil)
	if status != http.StatusNotFound {
		t.Fatalf("the detail endpoint for an unknown channel answered %d, want 404: %s", status, raw)
	}
	if body := decodeObject(t, raw); body["channel_id"] != "c-missing" || body["state"] != nil {
		t.Errorf("the detail 404 body is %s", raw)
	}
}

// DELETE stops the channel, and the body carries the state it was in.
//
// The stop is asserted through the MANAGER, not through the response: a
// handler that answered the right JSON and stopped nothing would pass a
// body-only check, and "the channel is gone from the map" is the thing
// /proxy/ts/stop/<id> exists to cause.
func TestDeletingAChannelStopsItAndReportsItsPreviousState(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-stop", "client-a")
	packetRun(t, "the client", response.Body, 1)
	waitForHead(t, r, "c-stop", 1)

	status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-stop", nil)
	_ = response.Body.Close()
	if status != http.StatusOK {
		t.Fatalf("DELETE answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "success" {
		t.Fatalf("DELETE answered %s, want status success", raw)
	}
	previous, ok := body["previous_state"].(map[string]any)
	if !ok || previous["state"] == nil {
		t.Errorf("previous_state is %v, want the one-key dict channel_service.py:611 builds", body["previous_state"])
	}
	if body["model_released"] != true {
		t.Errorf("model_released is %v, want true", body["model_released"])
	}
	if r.Manager.Get("c-stop") != nil {
		t.Fatalf("the channel is still in the manager after a DELETE")
	}

	// A second DELETE is the not-found shape, which the Django wrapper turns
	// into its 404. Asserted as well, because a handler that answered
	// "success" unconditionally would pass everything above.
	status, raw = r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-stop", nil)
	if status != http.StatusOK {
		t.Fatalf("the second DELETE answered %d, want 200 with an error body: %s", status, raw)
	}
	body = decodeObject(t, raw)
	if body["status"] != "error" || body["message"] != "Channel not found" {
		t.Errorf("the second DELETE answered %s, want channel_service.py:604's error shape", raw)
	}
}

// DELETE on one client disconnects that client and leaves the other one
// streaming.
//
// BOTH HALVES, because a handler that tore the whole channel down would
// satisfy "the stopped client stopped" on its own.
func TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	first := r.tuneAs(t, "c-client", "client-a")
	defer func() { _ = first.Body.Close() }()
	second := r.tuneAs(t, "c-client", "client-b")
	defer func() { _ = second.Body.Close() }()
	packetRun(t, "client-a", first.Body, 1)
	packetRun(t, "client-b", second.Body, 1)
	waitFor(t, "both clients to register", 15*time.Second, func() bool {
		ch := r.Manager.Get("c-client")
		return ch != nil && ch.Clients() == 2
	})

	status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-client/clients/client-a", nil)
	if status != http.StatusOK {
		t.Fatalf("the client DELETE answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "success" || body["locally_processed"] != true {
		t.Errorf("the client DELETE answered %s, want success with locally_processed true", raw)
	}
	if body["event_published"] != false {
		t.Errorf("event_published is %v, want false: D2 deletes the pub/sub and there is "+
			"no other worker to tell", body["event_published"])
	}

	waitFor(t, "the stopped client to leave the registry", 15*time.Second, func() bool {
		ch := r.Manager.Get("c-client")
		return ch != nil && ch.Clients() == 1
	})

	// The OTHER client is still being served. Read after the stop, so this
	// cannot pass on bytes that were already buffered before it.
	packetRun(t, "client-b", second.Body, 1)

	// An unknown client id on a running channel is still `success` with
	// locally_processed false -- channel_service.py 404s only on the
	// CHANNEL, and the Django wrapper maps only status=error to 404.
	status, raw = r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-client/clients/nobody", nil)
	if status != http.StatusOK {
		t.Fatalf("the unknown-client DELETE answered %d: %s", status, raw)
	}
	body = decodeObject(t, raw)
	if body["status"] != "success" || body["locally_processed"] != false {
		t.Errorf("an unknown client id answered %s, want success with locally_processed false", raw)
	}

	// An unknown CHANNEL is the error shape.
	status, raw = r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-nothing/clients/client-a", nil)
	if status != http.StatusOK {
		t.Fatalf("the unknown-channel client DELETE answered %d: %s", status, raw)
	}
	if body := decodeObject(t, raw); body["status"] != "error" {
		t.Errorf("an unknown channel answered %s, want the error shape", raw)
	}
}

// parkedWriters reports how many goroutines are currently ACTUALLY PARKED
// inside a writeChunks socket write, and a sample stack from one of them.
//
// THIS IS THE SECOND FORM, TIGHTENED IN THE #318 FIX ROUND: the first form
// matched only on frame names (httpapi.writeChunks plus net.(*conn).Write or
// poll.(*FD).Write) and was HOLLOW UNDER LOAD -- a review round measured it
// at 28/40 red against the unfixed tree with 12 FALSE GREEN under 28 CPU
// spinners on 14 cores, independently reproduced here (2/40 false green on a
// smaller run). The cause: those frames are also on the stack of a goroutine
// that syscall.Write has already WOKEN and is about to retry or complete --
// runtime.Stack reports it "[runnable]", not "[IO wait]" -- so under
// scheduler contention the precondition wait can observe a goroutine that
// merely PASSED THROUGH the write path a moment ago, issue the DELETE, and
// have it succeed on a still-unfixed tree exactly as the old, load-dependent
// test did. Requiring internal/poll.runtime_pollWait on the stack closes
// this: that frame is present only while the goroutine is genuinely blocked
// in the netpoller waiting for the socket to become writable, and absent
// the instant it is runnable again (still a FRAME name, so this keeps this
// package's stated preference for frame names over goroutine state text,
// which is a runtime implementation detail).
//
// REQUIRING AT LEAST TWO also closes a second hole: a detector that reports
// on the FIRST match cannot tell client-a's parked writer from client-b's,
// so a run where only one of the two ever gets to writeChunks before the
// DELETE (client-b usually lags client-a slightly, since it tunes second)
// could pass the precondition on the wrong client's goroutine. With exactly
// two clients tuned and both never reading past their first packet, "at
// least two parked" can only be true when BOTH are parked, and client-a's is
// therefore necessarily among them -- true rather than merely probable.
func parkedWriters() (n int, sample string) {
	buf := make([]byte, 1<<22)
	buf = buf[:runtime.Stack(buf, true)]
	for _, g := range strings.Split(string(buf), "\n\ngoroutine ") {
		if !strings.Contains(g, "httpapi.writeChunks") {
			continue
		}
		if !strings.Contains(g, "internal/poll.runtime_pollWait") {
			continue
		}
		n++
		if sample == "" {
			sample = g
		}
	}
	return n, sample
}

// TestStoppingAClientBlockedInAWriteRemovesItFromTheRegistry is #318's pin.
//
// TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming (above) only
// reddens under host load, and rarely (measured ~5.7%, 4/70 runs) -- a
// lottery ticket, not a pin, because it races the DELETE against the write
// filling client-a's socket buffer rather than waiting for that precondition.
// This test removes the race: it polls a goroutine dump until BOTH clients'
// serving goroutines are ACTUALLY parked inside the write syscall (client-a
// and client-b never read past their first packet each, so the rig's
// unthrottled fixture floods both connections' send buffers within tens of
// milliseconds -- fanRig uses relaytest.Config{}, which has no Rate and so
// no pacing), fails loudly if that never happens within five seconds (the
// precondition is itself part of what #318 claims: an unreachable
// precondition means the mechanism was never exercised and this run proves
// nothing about it), and only THEN issues the admin DELETE for client-a.
// Unfixed, this reddens every run, with zero false greens; fixed, it is
// green every run, including under the same load -- confirmed all three
// ways (parkedWriters's own doc comment has the measurements) before this
// test shipped in its tightened form.
func TestStoppingAClientBlockedInAWriteRemovesItFromTheRegistry(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	first := r.tuneAs(t, "c-blocked-write", "client-a")
	defer func() { _ = first.Body.Close() }()
	second := r.tuneAs(t, "c-blocked-write", "client-b")
	defer func() { _ = second.Body.Close() }()
	packetRun(t, "client-a", first.Body, 1)
	packetRun(t, "client-b", second.Body, 1)
	waitFor(t, "both clients to register", 15*time.Second, func() bool {
		ch := r.Manager.Get("c-blocked-write")
		return ch != nil && ch.Clients() == 2
	})

	// Neither client reads again from here. Wait for the precondition
	// itself -- BOTH serving goroutines actually parked in the write
	// syscall, per parkedWriters's doc comment -- rather than for a fixed
	// sleep: that is what turns this from a race into a pin, and requiring
	// both (not just one) is what makes "client-a's goroutine" a guarantee
	// rather than a probability.
	var n int
	var sample string
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if n, sample = parkedWriters(); n >= 2 {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if n < 2 {
		// Explicit here too, not just deferred: on an unfixed tree that
		// never reaches this branch there is nothing to leak, but a
		// harness change that broke the precondition without breaking the
		// fix should not also hang the rest of the package's run.
		_ = first.Body.Close()
		_ = second.Body.Close()
		t.Fatalf("PRECONDITION UNREACHABLE: only %d serving goroutine(s) parked in a write after "+
			"5s, want 2 -- #318's mechanism was never exercised, so this run proves nothing", n)
	}
	t.Logf("both serving goroutines parked in a write; one sample:\n%s", sample)

	started := time.Now()
	status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-blocked-write/clients/client-a", nil)
	if status != http.StatusOK {
		_ = first.Body.Close()
		_ = second.Body.Close()
		t.Fatalf("the client DELETE answered %d: %s", status, raw)
	}

	dropped := false
	for time.Since(started) < 5*time.Second {
		if ch := r.Manager.Get("c-blocked-write"); ch != nil && ch.Clients() == 1 {
			dropped = true
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if !dropped {
		// Close the bodies HERE, in the failure path, rather than counting
		// on the deferred close at the end of the test function: on an
		// unfixed tree this goroutine is the whole point of the test, and
		// the rig's own httptest.Server.Close() (via t.Cleanup) blocks
		// until every in-flight handler returns -- leaving it parked into
		// the rest of the package's run would turn one red test into a
		// hung test binary. Closing the response bodies here (this drops
		// the underlying connections, which the still-unfixed handler
		// eventually notices as a write error) is what keeps a genuine
		// regression a clean, fast failure instead of a CI timeout.
		n2, s2 := parkedWriters()
		_ = first.Body.Close()
		_ = second.Body.Close()
		t.Fatalf("REPRODUCED #318: client-a was still in the registry %s after the DELETE, "+
			"with %d serving goroutine(s) still parked\n%s", time.Since(started), n2, s2)
	}
	t.Logf("client-a left the registry %v after the DELETE", time.Since(started))

	// The other client is still being served, exactly as the sibling test
	// above asserts -- the fix must not disturb it.
	packetRun(t, "client-b", second.Body, 1)
}

// ROW 18, answered for the Go relay: the names come OFF THE WIRE, and when
// the answer carried none the keys are absent rather than filled.
//
// Python's get_detailed_channel_info has two ORM fallbacks here -- it looks
// the Stream and the M3UAccountProfile up by primary key when the metadata
// hash has no name (channel_status.py:71-79, :97-114) -- and 2b-1 put both
// names on the next-source answer so the hash always has them. The Go relay
// has NO fallback and can have none: those two queries are exactly what D2's
// "no Postgres driver" forbids. So the answer to row 18 here is "absent",
// and it is a stated divergence rather than parity: Python would fill the
// key from the row if the hash somehow lacked it.
//
// The populated case is asserted in the same test, so "every optional key is
// always absent" cannot be what makes this pass.
func TestTheNamesComeOffTheWireAndAreAbsentWhenTheAnswerCarriedNone(t *testing.T) {
	r := fanRigWith(t, relaytest.ControlPlaneConfig{Nameless: true}, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-nameless", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-nameless", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	detail := decodeObject(t, raw)
	for _, key := range []string{"stream_name", "m3u_profile_name", "channel_name"} {
		if value, present := detail[key]; present {
			t.Errorf("the detail payload carries %q as %v for an answer that named none: the "+
				"Go relay has no ORM fallback and must not invent one", key, value)
		}
	}
	// stream_id IS present, so "the whole answer was empty" cannot be the
	// reason the three keys above vanished.
	if _, present := detail["stream_id"]; !present {
		t.Errorf("stream_id is absent too, so the three absences above prove nothing")
	}

	// And a named answer fills all three.
	named := fanRig(t, relaytest.Config{}, nil)
	namedResponse := named.tuneAs(t, "c-named", "client-a")
	defer func() { _ = namedResponse.Body.Close() }()
	packetRun(t, "the client", namedResponse.Body, 1)
	status, raw = named.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-named", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	detail = decodeObject(t, raw)
	for _, key := range []string{"stream_name", "m3u_profile_name", "channel_name"} {
		if _, present := detail[key]; !present {
			t.Errorf("the detail payload is missing %q for an answer that carried it", key)
		}
	}
}
