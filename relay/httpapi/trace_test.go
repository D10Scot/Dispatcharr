package httpapi

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/output"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// Observability D11's trace tests, through the real handler, the fake
// control plane and telemetrytest.

const (
	// traceUUID is a channel UUID: a secret (CLAUDE.md § Auth), so no span,
	// metric label or /metrics line may carry it.
	traceUUID = "c0ffee00-1234-4abc-8def-0123456789ab"
	// The span Django's authorize request stands for (P) and the span its
	// requests client stands for on an advance (Q).
	parentTrace = "4bf92f3577b34da6a3ce929d0e0e4736"
	parentSpan  = "00f067aa0ba902b7"
	switchTrace = "0af7651916cd43dd8448eb211c80319c"
	switchSpan  = "b7ad6b7169203331"
)

func pk(n int) *int { return &n }

// tracedRig is a fan rig whose control plane names channel_pk 42.
func tracedRig(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config, overrides map[string]any, opts ...rigOption) *rig {
	t.Helper()
	cp.ChannelPK = pk(42)
	return fanRigWith(t, cp, up, overrides, opts...)
}

// trustedHeader is the authorize hop's header set, with X-Relay-Traceparent
// naming P when withParent is set.
func trustedHeader(channelID string, withParent bool) http.Header {
	h := http.Header{}
	h.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	h.Set("X-Relay-Channel", channelID)
	h.Set("X-Relay-Client", "client-a")
	h.Set("X-Relay-Client-IP", "198.51.100.4")
	h.Set("X-Relay-User", "7")
	if withParent {
		h.Set(telemetry.HeaderRelayTraceparent, telemetrytest.Traceparent(parentTrace, parentSpan))
	}
	return h
}

func spansNamed(rec *telemetrytest.Recorder, name string) []telemetrytest.Span {
	var out []telemetrytest.Span
	for _, s := range rec.Spans() {
		if s.Name == name {
			out = append(out, s)
		}
	}
	return out
}

// tuneSpan waits for relay.tune to end and returns it.
func tuneSpan(t *testing.T, rec *telemetrytest.Recorder) telemetrytest.Span {
	t.Helper()
	var span telemetrytest.Span
	waitFor(t, "relay.tune to end", 10*time.Second, func() bool {
		s, ok := rec.Span(telemetry.SpanTune)
		span = s
		return ok && s.Ended
	})
	return span
}

// noUUIDAnywhere fails if the channel UUID reached a span or a metric label.
func noUUIDAnywhere(t *testing.T, rec *telemetrytest.Recorder) {
	t.Helper()
	for _, s := range rec.Spans() {
		if strings.Contains(s.Name+s.Description, traceUUID) {
			t.Errorf("LEAK: span %q carries the channel UUID in its name or description", s.Name)
		}
		for k, v := range s.Attrs {
			if strings.Contains(fmt.Sprint(v), traceUUID) {
				t.Errorf("LEAK: span %q attribute %s carries the channel UUID", s.Name, k)
			}
		}
	}
	for _, name := range []string{"mino_relay_channels", "mino_relay_clients", "mino_relay_client_sent", "mino_relay_failovers"} {
		for _, p := range rec.Points(name) {
			for k, v := range p.Attrs {
				if strings.Contains(fmt.Sprint(v), traceUUID) {
					t.Errorf("LEAK: metric %s label %s carries the channel UUID", name, k)
				}
			}
		}
	}
}

// m3 is M3's total across every label set.
func m3(rec *telemetrytest.Recorder) float64 { return rec.Sum("mino_relay_client_sent") }

// 1. THE WHOLE GRAPH: relay.tune is P's child in P's trace, relay.next_source
// is relay.tune's child, the control plane received a traceparent naming
// relay.next_source, and every span shares the trace id.
func TestTheWholeGraph(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil)
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, true))
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the traced client", response.Body, 50)

	tune := tuneSpan(t, rec)
	if tune.TraceID != parentTrace || tune.ParentSpanID != parentSpan {
		t.Errorf("relay.tune is in trace %s under %s, want P's trace %s under %s", tune.TraceID, tune.ParentSpanID, parentTrace, parentSpan)
	}
	next, ok := rec.Span(telemetry.SpanNextSource)
	if !ok {
		t.Fatal("no relay.next_source span")
	}
	if next.ParentSpanID != tune.SpanID {
		t.Errorf("relay.next_source's parent is %s, want relay.tune %s", next.ParentSpanID, tune.SpanID)
	}
	seen := r.Control.RequestsTo("/next-source")
	if len(seen) != 1 {
		t.Fatalf("next-source calls = %d, want 1", len(seen))
	}
	if want := telemetrytest.Traceparent(parentTrace, next.SpanID); seen[0].Header.Get("Traceparent") != want {
		t.Errorf("the control plane received traceparent %q, want %q", seen[0].Header.Get("Traceparent"), want)
	}
	for _, s := range rec.Spans() {
		if s.TraceID != parentTrace {
			t.Errorf("span %s is in trace %s, want %s", s.Name, s.TraceID, parentTrace)
		}
	}
	if tune.Attrs["mino.channel_id"] != int64(42) || tune.Attrs["mino.output_format"] != "mpegts" ||
		tune.Attrs["mino.tune.joined"] != false || tune.Attrs["http.route"] != "GET /proxy/ts/stream/{channelID}" {
		t.Errorf("relay.tune attributes = %v", tune.Attrs)
	}
	noUUIDAnywhere(t, rec)
}

// 2. The span ends at the first byte while the viewer stays connected.
func TestTheTuneSpanEndsAtTheFirstByteWhileTheViewerStaysConnected(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil)
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, false))
	defer func() { _ = response.Body.Close() }()

	packetRun(t, "the first chunk", response.Body, 1)
	// The wrapper ends the span right after the write it delegates returns,
	// so the viewer can hold the first packet a moment before the span ends:
	// a short bound, with the viewer still connected throughout.
	deadline := time.Now().Add(2 * time.Second)
	span, ok := rec.Span(telemetry.SpanTune)
	for (!ok || !span.Ended) && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
		span, ok = rec.Span(telemetry.SpanTune)
	}
	if !ok || !span.Ended {
		t.Fatal("tune span still open after first byte")
	}
	if span.Attrs["mino.outcome"] != "streaming" || span.Attrs["http.response.status_code"] != int64(200) {
		t.Errorf("relay.tune = %v, want streaming 200", span.Attrs)
	}
	packetRun(t, "the viewer, still reading", response.Body, 200)
	if got := m3(rec); got < 201*buffer.TSPacketSize {
		t.Errorf("M3 = %v after %d bytes read, want at least that", got, 201*buffer.TSPacketSize)
	}
	points := rec.Points("mino_relay_client_sent")
	if len(points) != 1 || points[0].Attrs["channel_id"] != "42" || points[0].Attrs["format"] != "mpegts" {
		t.Errorf("M3 points = %+v, want one series labelled channel_id 42, mpegts", points)
	}
	noUUIDAnywhere(t, rec)
}

// 2a. The first byte is a keepalive: the source delivered less than one chunk
// and then went silent, so nothing reaches the ring and the first body write
// is a null packet on an unhealthy channel. The span ends at that write.
func TestTheFirstByteCanBeAKeepalive(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4, DeadAirAfterBytes: buffer.TSPacketSize * 8},
		map[string]any{"CONNECTION_TIMEOUT": 0.3, "channel_init_grace_period": 0.3, "HEALTH_CHECK_INTERVAL": 0.05, "KEEPALIVE_INTERVAL": 0.05})
	r.Control.SetDelay(6 * time.Second) // no failover feeds the client first
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, false))
	defer func() { _ = response.Body.Close() }()

	packets, _ := packetsUntil(t, response.Body, 8*time.Second, func([]byte) bool { return true })
	if len(packets) == 0 || pidOf(packets[0]) != nullPID {
		t.Fatalf("the first packet is not a keepalive (%d packets read); the case does not exercise what it names", len(packets))
	}
	// The control plane holds the failover for six seconds, so for that long
	// the viewer has had keepalives only: the span must already have ended
	// at one of them, not wait for media.
	deadline := time.Now().Add(2 * time.Second)
	span, ok := rec.Span(telemetry.SpanTune)
	for (!ok || !span.Ended) && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
		span, ok = rec.Span(telemetry.SpanTune)
	}
	if !ok || !span.Ended {
		t.Fatal("tune span still open after a keepalive was written: the first byte waited for media")
	}
	if span.Attrs["mino.outcome"] != "streaming" {
		t.Errorf("relay.tune outcome = %v, want streaming at the keepalive", span.Attrs["mino.outcome"])
	}
}

// partialWriter accepts the first Write whole and fails every later one, so
// one writeChunks batch is half delivered.
type partialWriter struct {
	header http.Header
	mu     sync.Mutex
	status int
	writes int
	body   bytes.Buffer
}

func (w *partialWriter) Header() http.Header {
	if w.header == nil {
		w.header = http.Header{}
	}
	return w.header
}

func (w *partialWriter) WriteHeader(code int) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.status == 0 {
		w.status = code
	}
}

// Flush is a no-op: the handler flushes through http.ResponseController and
// treats a writer that cannot flush as a gone viewer.
func (w *partialWriter) Flush() {}

func (w *partialWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.writes++
	if w.writes > 1 {
		return 0, errors.New("the viewer went away")
	}
	return w.body.Write(p)
}

// serveDirect runs the relay's handler on a writer the test controls.
func serveDirect(t *testing.T, r *rig, w http.ResponseWriter, header http.Header) {
	t.Helper()
	req := httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/proxy/ts/stream/"+traceUUID, nil)
	req.Header = header
	done := make(chan struct{})
	go func() {
		defer close(done)
		r.Relay.Config.Handler.ServeHTTP(w, req)
	}()
	select {
	case <-done:
	case <-time.After(20 * time.Second):
		t.Fatal("the handler did not return")
	}
}

// 2b. A partial batch: the first write is accepted, the second fails in the
// same writeChunks call. The span ended as streaming at the first write.
func TestAPartialBatchEndsTheSpanAtTheFirstWrite(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil)
	w := &partialWriter{}
	serveDirect(t, r, w, trustedHeader(traceUUID, false))

	span := tuneSpan(t, rec)
	if span.Attrs["mino.outcome"] != "streaming" || span.Attrs["http.response.status_code"] != int64(200) {
		t.Errorf("relay.tune = %v, want streaming 200", span.Attrs)
	}
	if got, want := m3(rec), float64(w.body.Len()); got != want || want == 0 {
		t.Errorf("M3 = %v, want the %v bytes the first write accepted", got, want)
	}
	if n := rec.TuneCompletions(); n != 1 {
		t.Errorf("completion invoked %d times, want 1", n)
	}
}

// shortWriter accepts 100 bytes of every Write and returns an error.
type shortWriter struct{ partialWriter }

func (w *shortWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	n := min(100, len(p))
	w.body.Write(p[:n])
	return n, io.ErrShortWrite
}

// 2f. M3 counts the returned n of a write that also failed, and completion
// happens exactly once even though the handler then returns through its
// deferred End.
func TestM3CountsTheReturnedNOfAFailedWriteAndCompletionHappensOnce(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil)
	w := &shortWriter{}
	serveDirect(t, r, w, trustedHeader(traceUUID, false))

	span := tuneSpan(t, rec)
	if span.Attrs["mino.outcome"] != "streaming" {
		t.Errorf("outcome = %v, want streaming: 100 bytes were accepted", span.Attrs["mino.outcome"])
	}
	if got, want := m3(rec), float64(w.body.Len()); got != want || want < 100 {
		t.Errorf("M3 = %v, want %v (the returned n of each failed write)", got, want)
	}
	if n := rec.TuneCompletions(); n != 1 {
		t.Errorf("completion invoked %d times, want 1", n)
	}
}

// 2c. Only the tail is written: every source fails and the client's only
// write is the error packet. The span ends at that write.
func TestTheErrorPacketIsTheFirstByte(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Status: 404}, nil)
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, false))
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(response.Body)
	if err != nil || len(body) != buffer.TSPacketSize {
		t.Fatalf("body = %d bytes (%v), want the one error packet", len(body), err)
	}
	span := tuneSpan(t, rec)
	if span.Attrs["mino.outcome"] != "streaming" {
		t.Errorf("outcome = %v, want streaming at the error packet's write", span.Attrs["mino.outcome"])
	}
	if got := m3(rec); got != buffer.TSPacketSize {
		t.Errorf("M3 = %v, want the one %d-byte packet", got, buffer.TSPacketSize)
	}
}

// flushRecorder is an httptest.ResponseRecorder whose writes stop the handler
// after enough bytes, so a direct ServeHTTP returns.
type flushRecorder struct {
	*httptest.ResponseRecorder
	mu    sync.Mutex
	limit int
}

func (f *flushRecorder) Write(p []byte) (int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.Body.Len() >= f.limit {
		return 0, errors.New("enough")
	}
	return f.ResponseRecorder.Write(p)
}

func (f *flushRecorder) Flush() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.ResponseRecorder.Flush()
}

// 2d. The response is unchanged: through the wrapper the status, the headers
// and the TS bytes are what the provider sent, and http.ResponseController's
// Flush still reaches the recorder.
func TestTheWrappedHandlerChangesNothingAndStillFlushes(t *testing.T) {
	telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil)
	w := &flushRecorder{ResponseRecorder: httptest.NewRecorder(), limit: rigChunkBytes}
	serveDirect(t, r, w, trustedHeader(traceUUID, false))

	if w.Code != http.StatusOK || w.Header().Get("Content-Type") != "video/mp2t" {
		t.Errorf("status %d, Content-Type %q", w.Code, w.Header().Get("Content-Type"))
	}
	if !w.Flushed {
		t.Error("Flush never reached the recorder through the wrapper")
	}
	body := w.Body.Bytes()
	if problem := relaytest.AlignmentProblem(body); problem != "" || len(body) == 0 {
		t.Fatalf("the body is not whole TS packets (%d bytes): %s", len(body), problem)
	}
	first := relaytest.PacketIndex(body[:buffer.TSPacketSize])
	for i := 0; i < len(body); i += buffer.TSPacketSize {
		if idx := relaytest.PacketIndex(body[i : i+buffer.TSPacketSize]); idx != (first+i/buffer.TSPacketSize)%rigAssetPackets {
			t.Fatalf("packet at byte %d carries index %d: the wrapper changed the bytes", i, idx)
		}
	}
}

// 2e. Four outcomes, each with its status, and M3 does not move on any
// failure: an error body written while disarmed is not media.
func TestEachTuneOutcomeAndItsStatus(t *testing.T) {
	for _, tc := range []struct {
		name    string
		setup   func(r *rig)
		opts    []rigOption
		header  func() http.Header
		outcome string
		status  int64
	}{
		{
			name: "denial",
			setup: func(r *rig) {
				r.Control.SetAuthorize(&relaytest.AuthorizeDecision{Status: 429, Body: `{"error":"limit"}`})
			},
			header:  func() http.Header { return http.Header{} },
			outcome: "refused", status: 429,
		},
		{
			name:    "draining",
			setup:   func(r *rig) { r.Lifecycle.BeginDrain() },
			header:  func() http.Header { return trustedHeader(traceUUID, false) },
			outcome: "draining", status: 503,
		},
		{
			name: "fmp4 output-start failure",
			opts: []rigOption{withRemux(output.Remux{Command: "/nonexistent/remux", Argv: []string{}, ArgvNoBSF: []string{}})},
			header: func() http.Header {
				h := trustedHeader(traceUUID, false)
				h.Set("X-Relay-Output-Format", output.FormatFMP4)
				return h
			},
			outcome: "failed", status: 500,
		},
		{
			name:    "media",
			header:  func() http.Header { return trustedHeader(traceUUID, false) },
			outcome: "streaming", status: 200,
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := telemetrytest.Install(t)
			r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil, tc.opts...)
			if tc.setup != nil {
				tc.setup(r)
			}
			response := r.tune(t, "/proxy/ts/stream/"+traceUUID, tc.header())
			readAtLeast(response.Body, buffer.TSPacketSize, 3*time.Second)
			_ = response.Body.Close()

			span := tuneSpan(t, rec)
			if span.Attrs["mino.outcome"] != tc.outcome || span.Attrs["http.response.status_code"] != tc.status {
				t.Errorf("relay.tune = %v, want %s %d", span.Attrs, tc.outcome, tc.status)
			}
			if tc.outcome != "streaming" {
				if got := m3(rec); got != 0 {
					t.Errorf("M3 counted %v error-body bytes, want 0", got)
				}
			} else if m3(rec) == 0 {
				t.Error("M3 = 0 after media was served")
			}
			noUUIDAnywhere(t, rec)
		})
	}
}

// 3. Failure before the first byte: next-source answers 403, the viewer gets
// the existing status, and relay.tune ends refused at it with no media.
func TestARefusedNextSourceEndsTheTuneRefused(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{Status: http.StatusForbidden}, relaytest.Config{}, nil)
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, false))
	_, _ = io.ReadAll(response.Body)
	_ = response.Body.Close()

	span := tuneSpan(t, rec)
	if span.Attrs["mino.outcome"] != "refused" || span.Attrs["http.response.status_code"] != int64(response.StatusCode) {
		t.Errorf("relay.tune = %v, want refused at the viewer's status %d", span.Attrs, response.StatusCode)
	}
	if got := m3(rec); got != 0 {
		t.Errorf("M3 = %v on a refused tune, want 0", got)
	}
	noUUIDAnywhere(t, rec)
}

// 4. Untrusted context is ignored: X-Relay-Traceparent without the marker,
// and a bare traceparent with it, both leave relay.tune a root.
func TestUntrustedTraceContextIsIgnored(t *testing.T) {
	for _, tc := range []struct {
		name   string
		header func() http.Header
	}{
		{"x-relay-traceparent without the marker", func() http.Header {
			h := http.Header{}
			h.Set(telemetry.HeaderRelayTraceparent, telemetrytest.Traceparent(parentTrace, parentSpan))
			return h
		}},
		{"a bare traceparent with the marker", func() http.Header {
			h := trustedHeader(traceUUID, false)
			h.Set("Traceparent", telemetrytest.Traceparent(parentTrace, parentSpan))
			return h
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := telemetrytest.Install(t)
			r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil)
			response := r.tune(t, "/proxy/ts/stream/"+traceUUID, tc.header())
			readAtLeast(response.Body, buffer.TSPacketSize, 3*time.Second)
			_ = response.Body.Close()
			span := tuneSpan(t, rec)
			if span.ParentSpanID != "" || span.TraceID == parentTrace {
				t.Errorf("relay.tune is under %s in trace %s: the untrusted context %s was inherited", span.ParentSpanID, span.TraceID, parentTrace)
			}
		})
	}
}

// advanceWithTraceparent is internalCall with a traceparent naming Q.
func (r *rig) advanceWithTraceparent(t *testing.T, path string, body []byte, signed bool) int {
	t.Helper()
	req, err := http.NewRequestWithContext(t.Context(), http.MethodPost, r.Relay.URL+path, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Traceparent", telemetrytest.Traceparent(switchTrace, switchSpan))
	if signed {
		req.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
		req.Header.Set(control.HeaderInternalRequest, control.InternalRequestHeader(testSecret, http.MethodPost, path, body, time.Now().Unix()))
	}
	resp, err := r.Relay.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	return resp.StatusCode
}

// 5. An operator switch: relay.stream_switch's parent is Q, its one link is
// the tune T that published the channel, and it ends applied. A request
// without valid internal headers is refused before any span starts.
func TestAnOperatorSwitchIsTheRequestsChildAndLinksTheTune(t *testing.T) {
	rec := telemetrytest.Install(t)
	r, alternate := failoverRig(t, relaytest.Config{}, nil)
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, true))
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client before the switch", response.Body, 50)
	tune := tuneSpan(t, rec)

	path := "/proxy/relay/channels/" + traceUUID + "/advance"
	if status := r.advanceWithTraceparent(t, path, advanceBody(t, alternate.URL(), 2, true), false); status == http.StatusOK {
		t.Fatalf("an unsigned advance answered 200")
	}
	if got := spansNamed(rec, telemetry.SpanStreamSwitch); len(got) != 0 {
		t.Fatalf("an unsigned advance started %d relay.stream_switch spans, want 0", len(got))
	}
	if status := r.advanceWithTraceparent(t, path, advanceBody(t, alternate.URL(), 2, true), true); status != http.StatusOK {
		t.Fatalf("the signed advance answered %d", status)
	}
	got := spansNamed(rec, telemetry.SpanStreamSwitch)
	if len(got) != 1 || !got[0].Ended {
		t.Fatalf("relay.stream_switch spans = %+v, want one ended", got)
	}
	s := got[0]
	if s.TraceID != switchTrace || s.ParentSpanID != switchSpan {
		t.Errorf("relay.stream_switch is in %s under %s, want Q's %s under %s", s.TraceID, s.ParentSpanID, switchTrace, switchSpan)
	}
	if len(s.Links) != 1 || s.Links[0] != tune.SpanID {
		t.Errorf("relay.stream_switch links %v, want only the tune %s", s.Links, tune.SpanID)
	}
	if s.Attrs["mino.outcome"] != "applied" {
		t.Errorf("relay.stream_switch outcome = %v, want applied", s.Attrs["mino.outcome"])
	}
	noUUIDAnywhere(t, rec)
}

// 6. A failover: a forced health_monitor failover gives relay.failover a root
// linked to the tune, owning a relay.next_source child; M4 counts it.
func TestAFailoverIsARootLinkedToTheTune(t *testing.T) {
	rec := telemetrytest.Install(t)
	alternate := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100)})
	t.Cleanup(alternate.Close)
	r := tracedRig(t, relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}},
		relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3},
		map[string]any{"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05})
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, true))
	defer func() { _ = response.Body.Close() }()
	tune := tuneSpan(t, rec)

	var failover telemetrytest.Span
	waitFor(t, "relay.failover to end", 15*time.Second, func() bool {
		got := spansNamed(rec, telemetry.SpanFailover)
		if len(got) == 0 || !got[0].Ended {
			return false
		}
		failover = got[0]
		return true
	})
	if failover.ParentSpanID != "" || failover.TraceID == tune.TraceID {
		t.Errorf("relay.failover is under %s in the tune's trace: want a root", failover.ParentSpanID)
	}
	if len(failover.Links) != 1 || failover.Links[0] != tune.SpanID {
		t.Errorf("relay.failover links %v, want the tune %s", failover.Links, tune.SpanID)
	}
	if failover.Attrs["mino.failover.trigger"] != "health_monitor" || failover.Attrs["mino.outcome"] != "switched" || failover.Attrs["mino.channel_id"] != int64(42) {
		t.Errorf("relay.failover attributes = %v", failover.Attrs)
	}
	var child bool
	for _, s := range spansNamed(rec, telemetry.SpanNextSource) {
		if s.ParentSpanID == failover.SpanID {
			child = true
		}
	}
	if !child {
		t.Error("no relay.next_source is relay.failover's child")
	}
	points := rec.Points("mino_relay_failovers")
	if len(points) != 1 || points[0].Attrs["channel_id"] != "42" || points[0].Attrs["outcome"] != "switched" || points[0].Attrs["trigger"] != "health_monitor" {
		t.Errorf("M4 = %+v", points)
	}
	noUUIDAnywhere(t, rec)
}

// The gauges and /metrics, through a running tune: channel_id is the numeric
// id, and the body the scrape serves never carries the channel UUID.
func TestTheGaugesAndTheScrapeNameTheChannelByNumericID(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tracedRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, nil)
	rec.T.ObserveChannels(r.Manager.ChannelStates)
	rec.T.ObserveClients(r.Manager.ClientCounts)
	response := r.tune(t, "/proxy/ts/stream/"+traceUUID, trustedHeader(traceUUID, false))
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the viewer", response.Body, 50)

	clients := rec.Points("mino_relay_clients")
	if len(clients) != 1 || clients[0].Attrs["channel_id"] != "42" || clients[0].Value != 1 {
		t.Errorf("M2 = %+v, want one client on channel_id 42", clients)
	}
	scrape := httptest.NewRecorder()
	rec.T.Metrics().ServeHTTP(scrape, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/metrics", nil))
	body := scrape.Body.String()
	if !strings.Contains(body, `mino_relay_clients{channel_id="42",format="mpegts",profile_id="0"} 1`) {
		t.Errorf("the scrape lacks the client series by numeric id:\n%s", body)
	}
	if strings.Contains(body, traceUUID) {
		t.Errorf("LEAK: /metrics carries the channel UUID:\n%s", body)
	}
	noUUIDAnywhere(t, rec)
}
