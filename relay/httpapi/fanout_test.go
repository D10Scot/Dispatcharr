package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// rigAssetPackets is how many packets the fan-out tests' upstream loops.
//
// LONG ENOUGH THAT PacketIndex NEVER WRAPS inside a test, and that is what
// makes the join-point assertion able to fail at all. The embedded index is the
// packet's position in the ASSET, so a looping upstream restarts it at zero; an
// earlier 4,096-packet asset (3.1 seconds at the nominal rate) made "how far
// behind live did this client start" compare a wrapped index against an
// unwrapped chunk count, which is large and positive whatever the relay does.
// The break-check that removed the join call entirely left the test GREEN,
// which is how this was found.
//
// 65,536 packets is 12.3 MB, 49 seconds at the nominal rate -- longer than any
// test here runs. Do not shrink it for speed.
const rigAssetPackets = 65536

// rigSettings is the full effective settings object with the rig's non-default
// chunk size, plus whatever a test overrides.
//
// Built from relaytest.EffectiveProxySettings() rather than from a literal, so
// a key a later PR starts reading appears here automatically instead of
// failing one test with an ErrSettingAbsent nobody expected.
func rigSettings(overrides map[string]any) map[string]any {
	s := relaytest.EffectiveProxySettings()
	s["BUFFER_CHUNK_SIZE"] = rigChunkBytes
	for k, v := range overrides {
		s[k] = v
	}
	return s
}

// fanRig is newRig with the long asset and the rig's settings, which is what
// every test in this file wants.
func fanRig(t *testing.T, up relaytest.Config, overrides map[string]any, opts ...rigOption) *rig {
	t.Helper()
	return fanRigWith(t, relaytest.ControlPlaneConfig{}, up, overrides, opts...)
}

// fanRigWith is fanRig with control over the fake Django as well, for the
// tests that need it slow.
func fanRigWith(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config, overrides map[string]any, opts ...rigOption) *rig {
	t.Helper()
	if up.Payload == nil {
		up.Payload = relaytest.SyntheticTS(rigAssetPackets, 0x100)
	}
	cp.Settings = rigSettings(overrides)
	return newRig(t, cp, up, opts...)
}

// tuneAs opens a stream for channelID as clientID, over the trusted path.
//
// Built on 2c-2's rig.tune rather than replacing it: that one takes a path and
// a header set and is the right primitive for the untrusted and malformed
// cases, and this is the shorthand for the common one.
func (r *rig) tuneAs(t *testing.T, channelID, clientID string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	response := r.tune(t, "/proxy/ts/stream/"+channelID, header)
	if response.StatusCode != http.StatusOK {
		_ = response.Body.Close()
		t.Fatalf("tune for %s answered %d, want 200", clientID, response.StatusCode)
	}
	return response
}

// listChannels calls GET /proxy/relay/channels with both internal headers.
func (r *rig) listChannels(t *testing.T, query string) (int, []byte) {
	t.Helper()
	path := "/proxy/relay/channels" + query
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+path, nil)
	if err != nil {
		t.Fatalf("building the list request: %v", err)
	}
	request.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
	request.Header.Set(control.HeaderInternalRequest,
		control.InternalRequestHeader(testSecret, http.MethodGet, path, nil, time.Now().Unix()))
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("listing channels: %v", err)
	}
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the list body: %v", err)
	}
	return response.StatusCode, body
}

// waitForHead blocks until the channel's ring has published at least n chunks.
func waitForHead(t *testing.T, r *rig, id string, n uint64) uint64 {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for {
		if ch := r.Manager.Get(id); ch != nil {
			if head := ch.Ring().Head(); head >= n {
				return head
			}
		}
		if time.Now().After(deadline) {
			t.Fatalf("channel %s never published %d chunks within fifteen seconds", id, n)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// packetRun reads n whole packets and reports the index of the first, after
// checking that every packet follows the one before it.
//
// The oracle is relaytest.PacketIndex, an index the fixture embeds and no code
// under test reads or produces. A helper that checked only alignment would pass
// on a stream with gaps.
func packetRun(t *testing.T, who string, body io.Reader, packets int) int {
	t.Helper()
	got := make([]byte, packets*buffer.TSPacketSize)
	if _, err := io.ReadFull(body, got); err != nil {
		t.Fatalf("%s: reading %d packets: %v", who, packets, err)
	}
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("%s received bytes that are not whole TS packets: %s", who, problem)
	}
	first := relaytest.PacketIndex(got[:buffer.TSPacketSize])
	for i := 0; i < len(got); i += buffer.TSPacketSize {
		want := (first + i/buffer.TSPacketSize) % rigAssetPackets
		if idx := relaytest.PacketIndex(got[i : i+buffer.TSPacketSize]); idx != want {
			t.Fatalf("%s: packet at byte %d carries index %d, want %d -- its stream has a gap, "+
				"a duplicate or a reordering", who, i, idx, want)
		}
	}
	return first
}

// THE FAN-OUT TEST. N clients on one channel: one upstream connection, one
// *Channel, and every client's byte stream is an unbroken run of the writer's
// packets from wherever it joined.
//
// Every client tunes FIRST, synchronously, so all six are attached before any
// reads. Tuning inside the goroutines would let one client attach after another
// had already released, which is a different property.
func TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint(t *testing.T) {
	const clients = 6
	const packets = 900

	r := fanRig(t, relaytest.Config{Rate: 6}, nil)

	bodies := make([]io.ReadCloser, clients)
	for i := range clients {
		response := r.tuneAs(t, "c-fanout", fmt.Sprintf("client-%d", i))
		defer func() { _ = response.Body.Close() }()
		bodies[i] = response.Body
	}

	var wg sync.WaitGroup
	firsts := make([]int, clients)
	for i := range clients {
		wg.Add(1)
		go func() {
			defer wg.Done()
			firsts[i] = packetRun(t, fmt.Sprintf("client %d", i), bodies[i], packets)
		}()
	}
	wg.Wait()

	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests for one channel, want 1 -- parity-matrix row 10: "+
			"every client on a channel shares one upstream connection", got)
	}
	ch := r.Manager.Get("c-fanout")
	if ch == nil {
		t.Fatal("the manager holds no channel while six clients are reading it")
	}
	if got := ch.Clients(); got != clients {
		t.Fatalf("the channel reports %d clients, want %d", got, clients)
	}

	// Every client's run came from the same writer, so their join points are
	// all inside the window the ring held -- at most the ring's capacity apart.
	// Deliberately loose about WHERE each joined: a tighter bound would pin the
	// scheduler. What is strict is the provider's request count above and each
	// run being unbroken, which packetRun checks packet by packet.
	lowest, highest := firsts[0], firsts[0]
	for _, f := range firsts {
		lowest = min(lowest, f)
		highest = max(highest, f)
	}
	if span, maxSpan := highest-lowest, rigBudgetBytes/buffer.TSPacketSize; span > maxSpan {
		t.Fatalf("the clients' join points span %d packets, more than the %d-packet ring: "+
			"they are not reading one writer's stream", span, maxSpan)
	}
}

// Parity-matrix row 8, at the case the row is actually about: a client joining
// a channel ALREADY RUNNING for somebody else starts roughly
// new_client_behind_seconds behind live, not at the newest chunk.
//
// new_client_behind_seconds is sent as 3, not the default 5, so a relay
// ignoring the wire value is visible (hollow shape 2).
func TestASecondClientJoinsBehindLiveAndNotAtTheHead(t *testing.T) {
	const behindSeconds = 3
	// 1.0x nominal is 250,000 byte/s, so three seconds is 750,000 bytes --
	// about 5.7 chunks at rigChunkBytes, comfortably more than one and
	// comfortably less than the sixty-four-chunk ring.
	r := fanRig(t, relaytest.Config{Rate: 1},
		map[string]any{"new_client_behind_seconds": behindSeconds})

	first := r.tuneAs(t, "c-join", "client-a")
	defer func() { _ = first.Body.Close() }()
	packetRun(t, "the first client", first.Body, 200)

	head := waitForHead(t, r, "c-join", 12)

	second := r.tuneAs(t, "c-join", "client-b")
	defer func() { _ = second.Body.Close() }()
	secondStart := packetRun(t, "the second client", second.Body, 100)

	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1", got)
	}

	// The live head at the moment the second client joined, in packets.
	livePackets := int(head) * rigChunkBytes / buffer.TSPacketSize
	behindPackets := livePackets - secondStart
	if behindPackets <= 0 {
		t.Fatalf("the second client started at packet %d with the live head at packet %d: "+
			"it joined AT live, not behind it -- new_client_behind_seconds was ignored",
			secondStart, livePackets)
	}
	// Three seconds at the nominal rate is 750,000 bytes, 3,989 packets. A
	// generous window either side, because the claim is "behind by about the
	// configured window", not a stopwatch: the ring's 700-packet chunk
	// granularity and the scheduler both move the true figure. What is strict
	// is the check above -- a client that joined AT live fails outright.
	const wantPackets = behindSeconds * relaytest.NominalByteRate / buffer.TSPacketSize
	if behindPackets < wantPackets/4 || behindPackets > wantPackets*4 {
		t.Fatalf("the second client started %d packets behind live, want roughly %d "+
			"(%ds at the nominal rate) -- the join point is not the configured window",
			behindPackets, wantPackets, behindSeconds)
	}
}

// The list endpoint: every attached client, with ?clients=all lifting the
// ten-client cap that relay_client.live_connections would otherwise under-count
// behind (spec D4).
func TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked(t *testing.T) {
	const clients = 13
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)

	for i := range clients {
		response := r.tuneAs(t, "c-list", fmt.Sprintf("client-%02d", i))
		defer func() { _ = response.Body.Close() }()
	}

	for _, tc := range []struct {
		query string
		want  int
	}{
		{"", DefaultClientLimit},
		{"?clients=all", clients},
	} {
		status, body := r.listChannels(t, tc.query)
		if status != http.StatusOK {
			t.Fatalf("%q answered %d, want 200", tc.query, status)
		}
		var payload struct {
			Channels []struct {
				ClientCount int              `json:"client_count"`
				Clients     []map[string]any `json:"clients"`
			} `json:"channels"`
			Count int `json:"count"`
		}
		if err := json.Unmarshal(body, &payload); err != nil {
			t.Fatalf("%q: decoding the list body: %v", tc.query, err)
		}
		if payload.Count != 1 || len(payload.Channels) != 1 {
			t.Fatalf("%q: the relay listed %d channels, want 1", tc.query, payload.Count)
		}
		if got := len(payload.Channels[0].Clients); got != tc.want {
			t.Fatalf("%q listed %d clients, want %d -- the cap is %d and ?clients=all lifts it",
				tc.query, got, tc.want, DefaultClientLimit)
		}
		// client_count is a SCARD in Python and is NEVER capped.
		if got := payload.Channels[0].ClientCount; got != clients {
			t.Fatalf("%q reported client_count %d, want %d -- the COUNT is never capped, "+
				"only the list is", tc.query, got, clients)
		}
	}
}

// An unsigned or missigned call is refused, and the refusal names nothing. The
// bound token signs the FULL path, so a token minted for the bare path does not
// authorise ?clients=all -- which is the exact route spec D4's whole argument
// rests on, and the correction the spec's section The contract records.
func TestTheListEndpointRefusesAnUnsignedOrMissignedCall(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)
	response := r.tuneAs(t, "c-auth", "client-a")
	defer func() { _ = response.Body.Close() }()

	for _, tc := range []struct {
		name   string
		path   string
		header func(http.Header)
	}{
		{"no headers at all", "/proxy/relay/channels", func(http.Header) {}},
		{"the principal header only", "/proxy/relay/channels", func(h http.Header) {
			h.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
		}},
		{"a token signed for the bare path, sent with a query string", "/proxy/relay/channels?clients=all", func(h http.Header) {
			h.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
			h.Set(control.HeaderInternalRequest, control.InternalRequestHeader(
				testSecret, http.MethodGet, "/proxy/relay/channels", nil, time.Now().Unix()))
		}},
		{"a token signed with the wrong secret", "/proxy/relay/channels", func(h http.Header) {
			h.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
			h.Set(control.HeaderInternalRequest, control.InternalRequestHeader(
				"not-the-deployment-secret", http.MethodGet, "/proxy/relay/channels", nil, time.Now().Unix()))
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+tc.path, nil)
			if err != nil {
				t.Fatalf("building the request: %v", err)
			}
			tc.header(request.Header)
			answer, err := r.Relay.Client().Do(request)
			if err != nil {
				t.Fatalf("calling the list endpoint: %v", err)
			}
			defer func() { _ = answer.Body.Close() }()
			if answer.StatusCode != http.StatusForbidden {
				t.Fatalf("answered %d, want 403 -- the internal surface authorised a call "+
					"that did not carry a valid bound token", answer.StatusCode)
			}
		})
	}
}

// The trust marker gates EVERY X-Relay-* value, not just the channel. An
// untrusted request naming a client id, an address and a user must have all
// three ignored: nginx is the only thing that may assert who is asking, and
// apps/proxy/authorize.py is the only place that decision is made.
//
// Read off the LIST ENDPOINT rather than off the tune, because what a believed
// header would corrupt is the registry -- the client id an admin stops by, the
// address row 17 pins, and the user id the stream limit counts.
func TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)

	// Every X-Relay-* value a trusted request carries, and NO trust marker.
	header := http.Header{}
	header.Set("X-Relay-Channel", "somebody-elses-channel")
	header.Set("X-Relay-Client", "an-id-i-chose")
	header.Set("X-Relay-Client-IP", "192.0.2.200")
	header.Set("X-Relay-User", "10")
	header.Set("User-Agent", "curl/8.0")

	response := r.tune(t, "/proxy/ts/stream/c-untrusted", header)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the untrusted tune answered %d, want 200 -- an unmarked request is the dev "+
			"shape and still streams", response.StatusCode)
	}

	calls := r.Control.Requests()
	if len(calls) != 1 {
		t.Fatalf("the relay made %d control-plane calls, want 1", len(calls))
	}
	if got := calls[0].Path; got != "/api/relay/channels/c-untrusted/next-source" {
		t.Fatalf("the tune asked about %s: an unverified X-Relay-Channel was believed", got)
	}

	waitForHead(t, r, "c-untrusted", 1)

	_, body := r.listChannels(t, "?clients=all")
	var payload struct {
		Channels []struct {
			Clients []map[string]any `json:"clients"`
		} `json:"channels"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("decoding the list body: %v", err)
	}
	if len(payload.Channels) != 1 || len(payload.Channels[0].Clients) != 1 {
		t.Fatalf("the list shows %d channels", len(payload.Channels))
	}
	client := payload.Channels[0].Clients[0]

	if client["client_id"] == "an-id-i-chose" {
		t.Fatal("an unverified X-Relay-Client was believed: the client registered under an id " +
			"it chose, which is the handle an admin stops a client by")
	}
	if client["ip_address"] == "192.0.2.200" {
		t.Fatal("an unverified X-Relay-Client-IP was believed: parity-matrix row 17's address " +
			"is whatever the client claimed")
	}
	if client["user_id"] != nil && client["user_id"] != "0" {
		t.Fatalf("an unverified X-Relay-User was believed: the client counts against user %v "+
			"for the stream limit", client["user_id"])
	}
	// The User-Agent is the client's OWN header on every path and is believed
	// deliberately -- it is not an authorize-hop assertion.
	if client["user_agent"] != "curl/8.0" {
		t.Fatalf("user_agent is %v, want \"curl/8.0\": the request's own header is not an "+
			"X-Relay-* assertion and is read on both paths", client["user_agent"])
	}
}

// An output this relay does not serve is refused 501 rather than served as
// MPEG-TS under a label that is not true, and the refusal happens BEFORE the
// control plane is asked.
func TestAnOutputThisRelayDoesNotServeIsRefused(t *testing.T) {
	for _, tc := range []struct {
		name   string
		header string
		value  string
	}{
		{"an output format it does not serve", "X-Relay-Output-Format", "fmp4"},
		{"an Output Profile", "X-Relay-Output", "7"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{Rate: 4}, nil)
			header := http.Header{}
			header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
			header.Set("X-Relay-Channel", "c-output")
			header.Set(tc.header, tc.value)

			response := r.tune(t, "/proxy/ts/stream/c-output", header)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusNotImplemented {
				t.Fatalf("a tune asking for %s=%s answered %d, want 501",
					tc.header, tc.value, response.StatusCode)
			}
			if got := len(r.Control.Requests()); got != 0 {
				t.Fatalf("the relay made %d control-plane calls for a tune it cannot serve, "+
					"want 0 -- the refusal must happen before anything is reserved", got)
			}
			if got := r.Upstream.Requests(); got != 0 {
				t.Fatalf("the provider saw %d requests for a tune the relay refused", got)
			}
		})
	}
}

// A second tune under a client id already attached to the channel is refused
// 503, not silently allowed to overwrite the first. Parity-matrix row 13's
// first half, at the HTTP layer: client_manager.py:218-221 returns False and
// views.py:748-753 turns that into this status.
func TestADuplicateClientIDIsRefusedAtTheTuneSurface(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)

	first := r.tuneAs(t, "c-dup", "the-same-id")
	defer func() { _ = first.Body.Close() }()
	waitForHead(t, r, "c-dup", 1)

	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", "c-dup")
	header.Set("X-Relay-Client", "the-same-id")
	second := r.tune(t, "/proxy/ts/stream/c-dup", header)
	defer func() { _ = second.Body.Close() }()

	if second.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("a second tune under an attached client id answered %d, want 503",
			second.StatusCode)
	}
	if got := r.Manager.Get("c-dup").Clients(); got != 1 {
		t.Fatalf("the channel holds %d clients after a refused duplicate, want 1 -- "+
			"the registry is not keyed by id", got)
	}
}

// The two constants Global Constraint 8 names, pinned to the Python literals
// they mirror.
//
// A VALUE TEST, not a behaviour test, and both are needed. Changing
// DefaultClientLimit from 10 to 13 leaves the cap test green -- its expected
// value IS the constant, which is the tautological oracle -- and changing
// MaxChunksPerRead from 20 to 40 leaves the buffer cap test green for the same
// reason. Only a literal written down from the Python side can fail.
func TestTheTwoPortedConstantsMatchTheirPythonLiterals(t *testing.T) {
	if DefaultClientLimit != 10 {
		t.Errorf("DefaultClientLimit is %d, want 10 -- apps/proxy/relay_views.py:57's "+
			"DEFAULT_CLIENT_LIMIT, what the Stats page and /proxy/stats/ have always shown",
			DefaultClientLimit)
	}
	if buffer.MaxChunksPerRead != 20 {
		t.Errorf("buffer.MaxChunksPerRead is %d, want 20 -- "+
			"apps/proxy/live_proxy/input/buffer.py:329's MAX_CHUNKS, the bound on how much "+
			"a lagging reader holds at one instant", buffer.MaxChunksPerRead)
	}
}

// THE TUNING CLIENT MAY LEAVE AND THE TUNE MUST SURVIVE IT.
//
// Manager.Attach runs start() behind a per-channel gate: the first client in
// makes the next-source call and every later client for that channel waits on
// the gate. If that call used the first client's r.Context(), the first client
// closing its tab would cancel next-source for everyone waiting -- they wake,
// find no channel, and each retries into the same failure.
//
// Python detaches by construction: its tune calls next_source from inside the
// client's own request greenlet (views.py:340, :390) and uWSGI does not cancel
// a greenlet when its client hangs up, so the channel starts and the followers
// attach to it. This asserts the Go relay does the same.
//
// The control plane is held for 1.5s so the disconnect lands squarely inside
// the call. The second client tunes 250ms in -- while the first is still
// waiting -- so it is genuinely on the gate rather than arriving afterwards.
//
// WHICH ASSERTION DISCRIMINATES, measured rather than assumed. Against the
// attached-context version the SECOND client still gets its 200 and its bytes:
// the cancelled start returns an error, Attach's deferred releaseGate opens the
// gate, and the waiter re-claims and makes its own call, which succeeds. The
// damage is therefore a WASTED control-plane round trip per departing tuner --
// plus a failed response for the client that left, and a real failure for the
// waiter whenever that retry also fails -- and the request-count assertion at
// the end is the one that sees it. The status and bytes assertions are kept
// because a 200 with an empty body is the same failure wearing a better number,
// but they are not what fails first.
func TestTheTuningClientLeavingDoesNotFailTheTuneForEveryoneElse(t *testing.T) {
	// channel_shutdown_delay is 2s, NOT the default 0, and that is what makes
	// this test deterministic rather than a coin flip. Two independent things
	// can make the second client cause a second next-source call, and only one
	// of them is what this test is about:
	//
	//   1. the context -- the first client's cancellation aborts the call, so
	//      no channel is ever published and the waiter must tune afresh; and
	//   2. the TEARDOWN RACE -- the call completes and the channel publishes,
	//      but the first client's release runs before the waiter has re-claimed,
	//      sees zero clients, and stops the channel underneath it.
	//
	// The second is real behaviour, not a test artefact, and with the default
	// zero delay it fires often enough to redden this test at roughly one run
	// in three -- measured. A non-zero grace window closes it: the first
	// client's release schedules a stop instead of taking one, the waiter
	// re-claims inside the window, and stopIfStillIdle then sees a client and
	// no-ops. What is left varying is exactly the property under test.
	r := fanRigWith(t,
		relaytest.ControlPlaneConfig{Delay: 1500 * time.Millisecond},
		relaytest.Config{Rate: 4},
		map[string]any{"channel_shutdown_delay": 2})

	// The first client, on a context this test cancels mid-call.
	firstCtx, dropFirst := context.WithCancel(t.Context())
	firstDone := make(chan struct{})
	go func() {
		defer close(firstDone)
		request, err := http.NewRequestWithContext(firstCtx, http.MethodGet,
			r.Relay.URL+"/proxy/ts/stream/c-detach", nil)
		if err != nil {
			return
		}
		request.Header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
		request.Header.Set("X-Relay-Channel", "c-detach")
		request.Header.Set("X-Relay-Client", "client-leaving")
		response, err := r.Relay.Client().Do(request)
		if err == nil {
			_ = response.Body.Close()
		}
	}()

	// The second client joins while the first is still inside next-source, so
	// it is parked on the gate when the first goes away. It reads its own bytes
	// in its own goroutine and reports an outcome, rather than handing the
	// response back over a channel: a *http.Response that crosses a channel is
	// a body bodyclose cannot follow, and reading here is also what makes the
	// assertion "it got a working stream" rather than "it got a status".
	type outcome struct {
		status int
		err    error
	}
	second := make(chan outcome, 1)
	go func() {
		time.Sleep(250 * time.Millisecond)
		request, err := http.NewRequestWithContext(t.Context(), http.MethodGet,
			r.Relay.URL+"/proxy/ts/stream/c-detach", nil)
		if err != nil {
			second <- outcome{err: err}
			return
		}
		request.Header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
		request.Header.Set("X-Relay-Channel", "c-detach")
		request.Header.Set("X-Relay-Client", "client-staying")
		response, err := r.Relay.Client().Do(request)
		if err != nil {
			second <- outcome{err: err}
			return
		}
		defer func() { _ = response.Body.Close() }()
		if response.StatusCode != http.StatusOK {
			second <- outcome{status: response.StatusCode}
			return
		}
		// Bytes, not just a status: a 200 with an empty body would be the same
		// failure wearing a better number.
		got := make([]byte, 40*buffer.TSPacketSize)
		if _, err := io.ReadFull(response.Body, got); err != nil {
			second <- outcome{status: response.StatusCode, err: err}
			return
		}
		if problem := relaytest.AlignmentProblem(got); problem != "" {
			second <- outcome{status: response.StatusCode, err: errors.New(problem)}
			return
		}
		second <- outcome{status: response.StatusCode}
	}()

	time.Sleep(600 * time.Millisecond)
	dropFirst()
	<-firstDone

	select {
	case got := <-second:
		if got.err != nil {
			t.Fatalf("the second client's tune failed after the first left: %v -- the "+
				"next-source call was cancelled by a client that is not the only one waiting",
				got.err)
		}
		if got.status != http.StatusOK {
			t.Fatalf("the second client got %d after the first client left mid-tune, want 200 -- "+
				"startProxyTune is still bound to the first client's request context", got.status)
		}
	case <-time.After(20 * time.Second):
		t.Fatal("the second client neither started nor failed within twenty seconds")
	}

	if got := r.Control.Requests(); len(got) != 1 {
		t.Fatalf("the relay made %d next-source calls, want 1 -- the first client's disconnect "+
			"cancelled next-source for the client waiting behind it, which then had to call again", len(got))
	}
}
