package httpapi

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

const testSecret = "phase2c1-test-secret"

// The chunk size the rig's fake control plane sends, and the unit every read
// length below is expressed in.
//
// DELIBERATELY NOT buffer.ChunkBytes. A rig that sent the default would be a
// pin that supplies the default (hollow shape 2), and it would disarm this
// whole end-to-end layer against the one property Amendment A1.4 exists to
// prove: with the wire value equal to the constant, a relay that ignored
// BUFFER_CHUNK_SIZE entirely would behave identically and every test here
// would stay green. Measured: with the default, forcing New to ignore
// cfg.ChunkBytes reddens 0 of these tests; with 700 packets it reddens them.
//
// 700 packets rather than a round number of bytes, so the chunk stays a whole
// number of TS packets as the real one is.
const rigChunkBytes = buffer.TSPacketSize * 700

// Enough ring for sixty-four of those, so a test can read several chunks
// without the writer evicting the head of what it is about to read. The
// earlier 188*4000 budget gave a capacity of TWO at the default chunk size,
// against a test that read exactly two -- no margin at all.
const rigBudgetBytes = rigChunkBytes * 64

// rig is a whole relay in front of a whole fake deployment: a fake Django, a
// fake provider, and this process's own mux served over a real socket.
//
// A REAL SERVER, not httptest.NewRecorder: the subject is a long-lived
// streaming response, and a recorder buffers the whole body and returns only
// once the handler has finished. Every assertion about a client reading while
// the upstream still runs needs a real connection.
type rig struct {
	Relay    *httptest.Server
	Upstream *relaytest.Upstream
	Control  *relaytest.ControlPlane
	Manager  *channel.Manager
	Emitter  *control.Emitter

	// Lifecycle is the drain flag the tune path and /readyz share, so a test
	// can raise it the way the SIGTERM handler does (2c-8).
	Lifecycle *Lifecycle
}

// rigOption adjusts the StreamDeps the rig is built with, for the one thing a
// test cannot express through the fake control plane or the fake provider: the
// process an fMP4 tune spawns (2c-6). A variadic option rather than a fourth
// positional parameter, so every existing call site is unchanged.
type rigOption func(*StreamDeps)

// withRemux makes an fMP4 tune spawn the stand-in instead of ffmpeg.
func withRemux(remux output.Remux) rigOption {
	return func(d *StreamDeps) { d.Remux = remux }
}

func newRig(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config, opts ...rigOption) *rig {
	t.Helper()
	return newRigWithClient(t, cp, up, control.NewHTTPClient(), opts...)
}

// newRigWithClient is newRig with the control client's transport chosen by
// the test: how the budget-shape test compresses ConnectTimeout+ReadTimeout
// to something a test can wait out.
func newRigWithClient(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config, httpClient *http.Client, opts ...rigOption) *rig {
	t.Helper()

	upstream := relaytest.NewUpstream(up)
	t.Cleanup(upstream.Close)

	if cp.SourceURL == "" {
		cp.SourceURL = upstream.URL()
	}
	if cp.Settings == nil {
		// Only when the caller has not supplied its own: the per-key required
		// test deletes a key from the full set and must keep that set.
		settings := relaytest.EffectiveProxySettings()
		settings["BUFFER_CHUNK_SIZE"] = rigChunkBytes
		cp.Settings = settings
	}
	controlPlane := relaytest.NewControlPlane(cp)
	t.Cleanup(controlPlane.Close)

	// ONE control client, as main.go builds one: the tune, the failover,
	// the release on teardown and the events all go through it, so the fake
	// sees them in one request log.
	client := &control.Client{Secret: testSecret, BaseURL: controlPlane.URL(), HTTP: httpClient}
	emitter := control.NewEmitter(client, nil)
	manager := channel.NewManager(channel.ManagerConfig{
		BudgetBytes: rigBudgetBytes,
		Events:      EventSink(emitter),
		Release:     ReleaseVia(client, nil),
	})
	// Order matters: channels stop (and release) before the emitter drains,
	// and the emitter drains before the fake closes.
	t.Cleanup(emitter.Close)
	t.Cleanup(manager.StopAll)

	lifecycle := &Lifecycle{}
	stream := StreamDeps{
		Secret:    testSecret,
		Channels:  manager,
		Control:   client,
		Lifecycle: lifecycle,
	}
	for _, opt := range opts {
		opt(&stream)
	}
	server := New(Config{
		DevRoutes: true,
		Stream:    stream,
		// THE SAME manager, not a second one. Two would give the list endpoint
		// an empty map while the tune path filled another, and every assertion
		// about what the list shows would be about the wrong object.
		Control: ControlDeps{Secret: testSecret, Channels: manager},
		Health:  HealthDeps{Channels: manager, Lifecycle: lifecycle},
	})
	relay := httptest.NewServer(server.Handler())
	t.Cleanup(relay.Close)

	return &rig{
		Relay: relay, Upstream: upstream, Control: controlPlane,
		Manager: manager, Emitter: emitter, Lifecycle: lifecycle,
	}
}

func (r *rig) tune(t *testing.T, path string, header http.Header) *http.Response {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+path, nil)
	if err != nil {
		t.Fatalf("building the tune request: %v", err)
	}
	for name, values := range header {
		for _, v := range values {
			request.Header.Add(name, v)
		}
	}
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("tuning: %v", err)
	}
	return response
}

// THE VERTICAL SLICE, end to end: a request reaches the relay, the relay asks
// the control plane, the control plane names a Proxy source, the relay
// connects to it, and the client receives the provider's bytes as whole,
// in-order TS packets.
func TestATuneDeliversTheProvidersBytes(t *testing.T) {
	payload := relaytest.SyntheticTS(4096, 0x100) // ~770 KB, three default chunks
	rig := newRig(t,
		relaytest.ControlPlaneConfig{},
		relaytest.Config{Payload: payload},
	)

	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("tune = %d, want 200", response.StatusCode)
	}
	if got := response.Header.Get("Content-Type"); got != "video/mp2t" {
		t.Fatalf("Content-Type = %q, want video/mp2t", got)
	}

	// Two chunks' worth. The client is positioned five seconds behind live and
	// the buffer is younger than that, so it starts at the oldest chunk --
	// meaning what arrives is the head of the provider's own payload.
	want := rigChunkBytes * 2
	got := make([]byte, want)
	if _, err := io.ReadFull(response.Body, got); err != nil {
		t.Fatalf("reading the stream: %v", err)
	}

	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the client received bytes that are not whole TS packets: %s", problem)
	}
	first := relaytest.PacketIndex(got[:buffer.TSPacketSize])
	for i := 0; i < len(got); i += buffer.TSPacketSize {
		want := (first + i/buffer.TSPacketSize) % 4096
		if idx := relaytest.PacketIndex(got[i : i+buffer.TSPacketSize]); idx != want {
			t.Fatalf("packet at byte %d carries index %d, want %d -- the stream is out of order or has gaps",
				i, idx, want)
		}
	}
	if n := rig.Upstream.Requests(); n != 1 {
		t.Fatalf("the provider saw %d requests for one tune, want 1", n)
	}
}

// A1.4's payoff, asserted where it can actually be seen. Making the rig send a
// non-default BUFFER_CHUNK_SIZE is necessary but NOT sufficient: every other
// test here reads a byte stream, and a relay that ignored the wire value and
// used the constant would still deliver correct, aligned, in-order TS -- just
// in differently sized pieces no HTTP client can observe. Measured: with the
// rig alone, forcing New to ignore cfg.ChunkBytes reddens 0 of these tests.
//
// This one looks at the ring the tune actually built. It is the only test in
// the package that reaches past the response body, and that is the point:
// chunk size is invisible from outside by construction, so an end-to-end
// assertion on it has to go one layer in or not exist.
func TestTheRingUsesTheChunkSizeTheControlPlaneSent(t *testing.T) {
	payload := relaytest.SyntheticTS(4096, 0x100)
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Payload: payload})

	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if _, err := io.ReadFull(response.Body, make([]byte, rigChunkBytes)); err != nil {
		t.Fatalf("reading the stream: %v", err)
	}

	ch := rig.Manager.Get("a-channel-uuid")
	if ch == nil {
		t.Fatal("the channel is not in the manager after a successful tune")
	}
	chunks, _, _ := ch.Ring().Read(0)
	if len(chunks) == 0 {
		t.Fatal("the ring holds no chunks after the client read a chunk's worth")
	}
	if got := len(chunks[0]); got != rigChunkBytes {
		t.Fatalf("the ring's chunk is %d bytes, want %d -- the relay used its own "+
			"constant instead of the BUFFER_CHUNK_SIZE the control plane sent, "+
			"which is the second copy Amendment A1.4 removes", got, rigChunkBytes)
	}
}

// The tune makes exactly one next-source call, signed with both internal
// headers. A client that could reach the relay without them would be talking
// to a relay that had not asked Django anything.
func TestATuneMakesOneSignedControlPlaneCall(t *testing.T) {
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("tune = %d, want 200", response.StatusCode)
	}
	// Read a little so the tune has certainly gone through.
	if _, err := io.ReadFull(response.Body, make([]byte, rigChunkBytes)); err != nil {
		t.Fatalf("reading the stream: %v", err)
	}

	seen := rig.Control.RequestsTo("/next-source")
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d next-source calls, want 1", len(seen))
	}
	if !strings.HasSuffix(seen[0].Path, "/a-channel-uuid/next-source") {
		t.Fatalf("the call went to %s", seen[0].Path)
	}
	if got := seen[0].Header.Get(control.HeaderInternal); got != control.InternalPrincipalToken(testSecret) {
		t.Fatalf("%s was not the internal-principal token", control.HeaderInternal)
	}
	if seen[0].Header.Get(control.HeaderInternalRequest) == "" {
		t.Fatalf("%s was absent: the call would 403 against a real Django", control.HeaderInternalRequest)
	}
}

// The relay refuses a kind it does not know loudly rather than falling
// through. `kind` is what it branches on: `transcode` is false for Redirect
// as well as Proxy, so a relay that read that field would serve a Redirect
// channel's provider URL through the Proxy path silently. All three kinds
// are served since 2c-5 (2c-2 listed transcode and redirect here), so the
// kind that can reach this arm is one a newer control plane invents.
func TestATuneRefusesAKindItDoesNotServe(t *testing.T) {
	for _, kind := range []string{"hls-passthrough"} {
		t.Run(kind, func(t *testing.T) {
			rig := newRig(t, relaytest.ControlPlaneConfig{Kind: kind}, relaytest.Config{})
			response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusNotImplemented {
				t.Fatalf("a %q channel tuned with %d, want 501", kind, response.StatusCode)
			}
			if n := rig.Upstream.Requests(); n != 0 {
				t.Fatalf("the provider was contacted %d times for a %q channel", n, kind)
			}
		})
	}
}

// Amendment A1.4's contract, enforced at runtime. An older control plane that
// sends only the seven stored keys fails the tune with a named key, rather
// than the relay quietly substituting a Go-side default.
func TestATuneRefusesIncompleteProxySettings(t *testing.T) {
	stored := map[string]any{
		"buffering_timeout":          15,
		"buffering_speed":            1.0,
		"redis_chunk_ttl":            60,
		"channel_shutdown_delay":     0,
		"channel_init_grace_period":  60,
		"channel_client_wait_period": 5,
		"new_client_behind_seconds":  5,
	}
	rig := newRig(t, relaytest.ControlPlaneConfig{Settings: stored}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("a pre-A1.4 control plane tuned with %d, want 502", response.StatusCode)
	}
	if n := rig.Upstream.Requests(); n != 0 {
		t.Fatal("the provider was contacted despite incomplete settings")
	}
}

// EVERY key is required, one at a time. The test above only proves that SOME
// key is required: with seven of them missing at once, defaulting any one in
// code still leaves six others to fail the tune, so it stays green against a
// relay that has quietly reintroduced a Go-side default. Found by running
// exactly that break-check and watching it not redden.
//
// Each subtest removes ONE key from an otherwise complete answer, so the only
// thing that can fail the tune is that key's own absence.
func TestEveryProxySettingThisRelayReadsIsRequired(t *testing.T) {
	for _, key := range []string{
		settingChunkBytes, settingRetention, settingJoinBehind, settingReadSize, settingShutdownDelay,
		settingBufferingSpeed, settingBufferingTimeout, settingDefaultUserAgent,
		settingConnectionTimeout, settingHealthCheckInterval, settingInitGracePeriod, settingMaxRetries,
		settingRetryWindow, settingStableThreshold, settingMaxStreamSwitches, settingStreamTimeout,
		settingFailoverGrace, settingKeepaliveInterval, settingMaxKeepalive,
	} {
		t.Run(key, func(t *testing.T) {
			settings := relaytest.EffectiveProxySettings()
			if _, present := settings[key]; !present {
				t.Fatalf("the fixture does not carry %q, so removing it proves nothing", key)
			}
			delete(settings, key)

			rig := newRig(t, relaytest.ControlPlaneConfig{Settings: settings}, relaytest.Config{})
			response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusBadGateway {
				t.Fatalf("an answer missing only %q tuned with %d, want 502 -- the relay "+
					"substituted a default of its own", key, response.StatusCode)
			}
		})
	}
}

// X-Relay-Channel is authoritative ONLY when the trust marker proves nginx put
// it there. Without the marker a hand-crafted header must be ignored and the
// path value used, or any client could name any channel and skip the hop.
func TestXRelayChannelIsIgnoredWithoutTheTrustMarker(t *testing.T) {
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/from-the-path", http.Header{
		"X-Relay-Channel": []string{"from-the-header"},
	})
	defer func() { _ = response.Body.Close() }()

	seen := rig.Control.RequestsTo("/next-source")
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d next-source calls, want 1", len(seen))
	}
	if !strings.Contains(seen[0].Path, "from-the-path") {
		t.Fatalf("the tune asked about %s: an unverified X-Relay-Channel was believed", seen[0].Path)
	}
}

func TestXRelayChannelIsUsedWithTheTrustMarker(t *testing.T) {
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/from-the-path", http.Header{
		control.HeaderAuthorized: []string{control.RelayTrustToken(testSecret)},
		"X-Relay-Channel":        []string{"from-the-header"},
	})
	defer func() { _ = response.Body.Close() }()

	seen := rig.Control.RequestsTo("/next-source")
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d next-source calls, want 1", len(seen))
	}
	if !strings.Contains(seen[0].Path, "from-the-header") {
		t.Fatalf("the tune asked about %s: the authorize hop's resolved channel was ignored", seen[0].Path)
	}
}

// The dev flag still gates the whole route, as 2c-1 built it.
func TestTheStreamRouteIsUnregisteredWithoutTheDevFlag(t *testing.T) {
	server := New(Config{DevRoutes: false})
	rec := httptest.NewRecorder()
	server.Handler().ServeHTTP(rec,
		httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/proxy/ts/stream/abc", nil))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("GET a stream with DevRoutes=false = %d, want 404 (the route must not be registered at all)", rec.Code)
	}
}

// A stream that ends cleanly is RECONNECTED, three times, before the source
// is exhausted (input/manager.py:1870-1875 and the retry loop; 2c-2 ended
// the tune on the first EOF, before there was a loop) -- and only then does
// the client's response end rather than hang, with every byte the provider
// sent across the three connections. With no alternate on the fake control
// plane, the failover finds nothing and the channel errors.
func TestAStreamThatEndsClosesTheClientsResponse(t *testing.T) {
	payload := relaytest.SyntheticTS(4096, 0x100)
	rig := newRig(t,
		relaytest.ControlPlaneConfig{},
		relaytest.Config{Payload: payload, StopAfterBytes: len(payload)},
	)

	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	done := make(chan []byte, 1)
	go func() {
		body, _ := io.ReadAll(response.Body)
		done <- body
	}()

	select {
	case body := <-done:
		if len(body) == 0 {
			t.Fatal("the client received nothing at all")
		}
		if problem := relaytest.AlignmentProblem(body); problem != "" {
			t.Fatalf("the delivered stream is not whole TS packets: %s", problem)
		}
	case <-time.After(20 * time.Second):
		t.Fatal("the client's response never ended after the upstream stopped")
	}
	if n := rig.Upstream.Requests(); n != 3 {
		t.Fatalf("the provider saw %d requests, want MAX_RETRIES = 3: a clean EOF is reconnected before the source is given up", n)
	}
	// The failover asked the control plane, which had nothing left once
	// stream 1 was excluded.
	if calls := rig.Control.RequestsTo("/next-source"); len(calls) != 2 || !strings.Contains(string(calls[1].Body), `"reason":"failover"`) {
		t.Fatalf("the control plane saw %d next-source calls, want the tune and one failover: %+v", len(calls), calls)
	}
}
