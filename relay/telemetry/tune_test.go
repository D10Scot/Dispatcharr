package telemetry_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

const (
	chanUUID = "5e171e10-0000-4000-8000-00000000d2f0"
	traceID  = "0af7651916cd43dd8448eb211c80319c"
	spanID   = "b7ad6b7169203331"
)

func tuneRequest(trusted bool, bare bool) *http.Request {
	r := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/live/u/p/1.ts", nil)
	tp := telemetrytest.Traceparent(traceID, spanID)
	if trusted {
		r.Header.Set(telemetry.HeaderRelayTraceparent, tp)
	}
	if bare {
		r.Header.Set("traceparent", tp)
	}
	return r
}

// A body with a canned short write, for M3's returned-n rule.
type shortWriter struct {
	http.ResponseWriter
	accept int
	err    error
}

func (s *shortWriter) Write(p []byte) (int, error) { return min(s.accept, len(p)), s.err }

func TestATrustedTuneIsTheChildOfTheAuthorizeHop(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tuneRequest(true, false)
	ctx, tune := telemetry.StartTune(r.Context(), r, true)
	nctx, ns := telemetry.StartNextSource(ctx, telemetry.ReasonTune)
	ns.End()
	tune.End()

	s, ok := rec.Span(telemetry.SpanTune)
	if !ok {
		t.Fatal("no relay.tune span")
	}
	if s.TraceID != traceID || s.ParentSpanID != spanID {
		t.Errorf("tune trace/parent = %s/%s, want %s/%s", s.TraceID, s.ParentSpanID, traceID, spanID)
	}
	n, _ := rec.Span(telemetry.SpanNextSource)
	if n.ParentSpanID != s.SpanID || n.TraceID != traceID {
		t.Errorf("next_source parent = %s in %s, want the tune %s", n.ParentSpanID, n.TraceID, s.SpanID)
	}
	// The header the control plane would receive names next_source's span.
	h := http.Header{}
	telemetry.InjectTraceparent(nctx, h)
	if got := h.Get("traceparent"); !strings.Contains(got, traceID) || !strings.Contains(got, n.SpanID) {
		t.Errorf("traceparent = %q, want trace %s and span %s", got, traceID, n.SpanID)
	}
}

func TestAnUntrustedTraceContextIsIgnored(t *testing.T) {
	for name, r := range map[string]*http.Request{
		"marker missing, header present": tuneRequest(true, false),
		"bare traceparent":               tuneRequest(false, true),
		"both":                           tuneRequest(true, true),
	} {
		rec := telemetrytest.Install(t)
		_, tune := telemetry.StartTune(r.Context(), r, false)
		tune.End()
		s, _ := rec.Span(telemetry.SpanTune)
		if s.ParentSpanID != "" || s.TraceID == traceID {
			t.Errorf("%s: tune parent=%q trace=%s: a client chose a trace id", name, s.ParentSpanID, s.TraceID)
		}
	}
}

func TestTheSpanEndsAtTheFirstByteWhileTheViewerStaysConnected(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tuneRequest(false, false)
	_, tune := telemetry.StartTune(r.Context(), r, false)
	tune.SetChannelID(7)
	tune.SetOutputFormat(telemetry.FormatMPEGTS)
	tune.SetRoute("GET /proxy/ts/stream/{id}")
	tune.SetJoined(true)
	defer tune.End()

	rw := httptest.NewRecorder()
	w := telemetry.NewFirstWriteWriter(rw, tune)
	w.Arm()
	if _, err := w.Write(make([]byte, 188)); err != nil {
		t.Fatal(err)
	}
	// The handler has not returned: the viewer is still connected.
	s, _ := rec.Span(telemetry.SpanTune)
	if !s.Ended {
		t.Fatal("tune span still open after first byte")
	}
	if s.Attrs[telemetry.AttrOutcome] != "streaming" || s.Attrs[telemetry.AttrStatusCode] != int64(200) ||
		s.Attrs[telemetry.AttrChannelID] != int64(7) || s.Attrs[telemetry.AttrOutputFormat] != "mpegts" ||
		s.Attrs[telemetry.AttrTuneJoined] != true || s.Attrs[telemetry.AttrRoute] != "GET /proxy/ts/stream/{id}" {
		t.Errorf("attrs = %v", s.Attrs)
	}
	if _, err := w.Write(make([]byte, 188)); err != nil {
		t.Fatal(err)
	}
	if got := rec.Sum("mino_relay_client_sent"); got != 376 {
		t.Errorf("M3 = %v, want 376", got)
	}
	p := rec.Points("mino_relay_client_sent")
	if len(p) != 1 || p[0].Attrs["channel_id"] != "7" || p[0].Attrs["format"] != "mpegts" {
		t.Errorf("M3 labels = %+v", p)
	}
}

func TestTheWrapperChangesNoByteHeaderOrStatus(t *testing.T) {
	telemetrytest.Install(t)
	body := []byte(strings.Repeat("x", 500))
	serve := func(w http.ResponseWriter) {
		w.Header().Set("Content-Type", "video/mp2t")
		w.WriteHeader(http.StatusPartialContent)
		_, _ = w.Write(body)
	}
	plain := httptest.NewRecorder()
	serve(plain)

	wrapped := httptest.NewRecorder()
	r := tuneRequest(false, false)
	_, tune := telemetry.StartTune(r.Context(), r, false)
	defer tune.End()
	w := telemetry.NewFirstWriteWriter(wrapped, tune)
	w.Arm()
	serve(w)

	if plain.Code != wrapped.Code || plain.Body.String() != wrapped.Body.String() || plain.Header().Get("Content-Type") != wrapped.Header().Get("Content-Type") {
		t.Fatalf("the wrapper changed the response: %d %q vs %d %q", plain.Code, plain.Header(), wrapped.Code, wrapped.Header())
	}
	if err := http.NewResponseController(w).Flush(); err != nil || !wrapped.Flushed {
		t.Fatalf("ResponseController did not reach the recorder through Unwrap: err=%v flushed=%v", err, wrapped.Flushed)
	}
}

// Disarming has its own oracle: M3 did not move. The span outcome alone cannot
// detect a wrongly armed wrapper, because Fail may come before the write.
func TestAnErrorBodyWhileDisarmedIsNeitherMediaNorCounted(t *testing.T) {
	for _, order := range []string{"fail then write", "write then fail"} {
		for name, tc := range map[string]struct {
			outcome string
			status  int
		}{
			"denial":   {telemetry.OutcomeRefused, 403},
			"draining": {telemetry.OutcomeDraining, 503},
			"fmp4":     {telemetry.OutcomeFailed, 500},
		} {
			rec := telemetrytest.Install(t)
			r := tuneRequest(false, false)
			_, tune := telemetry.StartTune(r.Context(), r, false)
			w := telemetry.NewFirstWriteWriter(httptest.NewRecorder(), tune)
			w.SetLabels(1, telemetry.FormatMPEGTS)
			if order == "fail then write" {
				tune.Fail(tc.outcome, tc.status)
				_, _ = w.Write([]byte(`{"error":"no"}`))
			} else {
				_, _ = w.Write([]byte(`{"error":"no"}`))
				tune.Fail(tc.outcome, tc.status)
			}
			tune.End()
			s, _ := rec.Span(telemetry.SpanTune)
			if s.Attrs[telemetry.AttrOutcome] != tc.outcome || s.Attrs[telemetry.AttrStatusCode] != int64(tc.status) {
				t.Errorf("%s/%s: outcome=%v status=%v, want %s/%d", name, order, s.Attrs[telemetry.AttrOutcome], s.Attrs[telemetry.AttrStatusCode], tc.outcome, tc.status)
			}
			if got := rec.Sum("mino_relay_client_sent"); got != 0 {
				t.Errorf("%s/%s: M3 counted %v error-body bytes, want 0", name, order, got)
			}
			if rec.TuneCompletions() != 1 {
				t.Errorf("%s/%s: completions = %d", name, order, rec.TuneCompletions())
			}
		}
	}
}

func TestM3CountsTheReturnedNAndCompletionHappensOnce(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tuneRequest(false, false)
	_, tune := telemetry.StartTune(r.Context(), r, false)
	tune.SetChannelID(3)
	tune.SetOutputFormat(telemetry.FormatFMP4)
	sw := &shortWriter{ResponseWriter: httptest.NewRecorder(), accept: 100, err: errors.New("client went away")}
	w := telemetry.NewFirstWriteWriter(sw, tune)
	w.Arm()
	for range 2 {
		if n, err := w.Write(make([]byte, 188)); n != 100 || err == nil {
			t.Fatalf("stub writer: n=%d err=%v", n, err)
		}
	}
	if got := rec.Sum("mino_relay_client_sent"); got != 200 {
		t.Fatalf("M3 = %v, want 200", got)
	}
	tune.Fail(telemetry.OutcomeFailed, 500) // a late Fail
	tune.End()                              // the deferred End
	s, _ := rec.Span(telemetry.SpanTune)
	if s.Attrs[telemetry.AttrOutcome] != "streaming" {
		t.Errorf("outcome = %v, want streaming", s.Attrs[telemetry.AttrOutcome])
	}
	if got := rec.TuneCompletions(); got != 1 {
		t.Errorf("completion invoked %d times, want 1", got)
	}
}

func TestAnAbandonedTuneEndsAsAbandoned(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tuneRequest(false, false)
	_, tune := telemetry.StartTune(r.Context(), r, false)
	tune.End()
	s, _ := rec.Span(telemetry.SpanTune)
	if !s.Ended || s.Attrs[telemetry.AttrOutcome] != "abandoned" {
		t.Fatalf("span = %+v", s)
	}
	if _, has := s.Attrs[telemetry.AttrStatusCode]; has {
		t.Error("an abandoned tune has no status")
	}
}

func TestAWriterWithNoTuneCountsM3UnderItsOwnLabels(t *testing.T) {
	rec := telemetrytest.Install(t)
	w := telemetry.NewFirstWriteWriter(httptest.NewRecorder(), nil)
	_, _ = w.Write([]byte("before arming"))
	w.Arm()
	w.SetLabels(9, telemetry.FormatHLS)
	_, _ = w.Write(make([]byte, 40))
	p := rec.Points("mino_relay_client_sent")
	if len(p) != 1 || p[0].Value != 40 || p[0].Attrs["channel_id"] != "9" || p[0].Attrs["format"] != "hls" {
		t.Fatalf("M3 = %+v", p)
	}
	// A format outside the closed set is not recorded at all.
	w.SetLabels(9, "avi")
	_, _ = w.Write(make([]byte, 40))
	if got := rec.Sum("mino_relay_client_sent"); got != 40 {
		t.Fatalf("an unknown format was recorded: %v", got)
	}
}

func TestAFailoverIsARootLinkedToTheTuneAndOwnsItsNextSource(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tuneRequest(false, false)
	_, tune := telemetry.StartTune(r.Context(), r, false)
	ref := tune.Ref()
	tune.End()

	ctx, fo := telemetry.StartFailover(context.Background(), ref)
	fo.SetChannelID(5)
	fo.SetTrigger(telemetry.TriggerHealthMonitor)
	_, ns := telemetry.StartNextSource(ctx, telemetry.ReasonFailover)
	ns.SetError(errors.New("secret " + chanUUID))
	ns.SetOutcome(telemetry.OutcomeUnavailable)
	ns.End()
	fo.SetOutcome(telemetry.OutcomeSwitched)
	fo.End()
	fo.End() // twice is harmless
	rec.T.Failover(ctx, 5, telemetry.TriggerHealthMonitor, telemetry.OutcomeSwitched)

	tuneSpan, _ := rec.Span(telemetry.SpanTune)
	f, _ := rec.Span(telemetry.SpanFailover)
	n, _ := rec.Span(telemetry.SpanNextSource)
	if f.ParentSpanID != "" || f.TraceID == tuneSpan.TraceID {
		t.Errorf("failover should be a new root: parent=%q", f.ParentSpanID)
	}
	if len(f.Links) != 1 || f.Links[0] != tuneSpan.SpanID {
		t.Errorf("failover links = %v, want the tune %s", f.Links, tuneSpan.SpanID)
	}
	if n.ParentSpanID != f.SpanID {
		t.Errorf("next_source is not the failover's child")
	}
	if n.Status != "error" || n.Description != "*errors.errorString" || strings.Contains(n.Description, chanUUID) {
		t.Errorf("status = %s %q: only the type may leave", n.Status, n.Description)
	}
	if f.Attrs[telemetry.AttrTrigger] != "health_monitor" || f.Attrs[telemetry.AttrOutcome] != "switched" || f.Attrs[telemetry.AttrChannelID] != int64(5) {
		t.Errorf("failover attrs = %v", f.Attrs)
	}
	p := rec.Points("mino_relay_failovers")
	if len(p) != 1 || p[0].Value != 1 || p[0].Attrs["trigger"] != "health_monitor" || p[0].Attrs["outcome"] != "switched" {
		t.Errorf("M4 = %+v", p)
	}
	// Out-of-set labels are not recorded.
	rec.T.Failover(ctx, 5, "nonsense", telemetry.OutcomeSwitched)
	rec.T.Failover(ctx, 5, telemetry.TriggerHealthMonitor, "nonsense")
	if got := rec.Sum("mino_relay_failovers"); got != 1 {
		t.Errorf("M4 sum = %v after out-of-set recordings", got)
	}
	// An invalid ref links nothing.
	_, fo2 := telemetry.StartFailover(context.Background(), telemetry.SpanRef{})
	fo2.End()
	if spans := rec.Spans(); len(spans[len(spans)-1].Links) != 0 {
		t.Error("a zero SpanRef produced a link")
	}
}

func TestAnOperatorSwitchHasTheRequestsSpanAsParentAndTheTuneAsLink(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tuneRequest(false, false)
	_, tune := telemetry.StartTune(r.Context(), r, false)
	ref := tune.Ref()
	tune.End()

	q := http.Header{}
	q.Set("traceparent", telemetrytest.Traceparent(traceID, spanID))
	ctx := telemetry.ExtractTraceparent(context.Background(), q)
	_, sw := telemetry.StartStreamSwitch(ctx, ref)
	sw.SetChannelID(2)
	sw.SetOutcome(telemetry.OutcomeApplied)
	sw.End()

	tuneSpan, _ := rec.Span(telemetry.SpanTune)
	s, _ := rec.Span(telemetry.SpanStreamSwitch)
	if s.ParentSpanID != spanID || s.TraceID != traceID {
		t.Errorf("stream_switch parent=%s trace=%s, want Q's", s.ParentSpanID, s.TraceID)
	}
	if len(s.Links) != 1 || s.Links[0] != tuneSpan.SpanID {
		t.Errorf("links = %v, want the tune", s.Links)
	}
	if s.Attrs[telemetry.AttrOutcome] != "applied" {
		t.Errorf("attrs = %v", s.Attrs)
	}
	// Out-of-set values are ignored by the typed setters.
	_, a := telemetry.StartAuthorize(context.Background())
	a.SetOutcome("S3NT1NEL")
	a.SetStatusCode(12345)
	a.SetOutcome(telemetry.OutcomeAllowed)
	a.End()
	as, _ := rec.Span(telemetry.SpanAuthorize)
	if as.Attrs[telemetry.AttrOutcome] != "allowed" {
		t.Errorf("authorize attrs = %v", as.Attrs)
	}
	if _, bad := as.Attrs[telemetry.AttrStatusCode]; bad {
		t.Error("an out-of-range status was recorded")
	}
}

func TestNilSpansAndInertTelemetryAreSafe(t *testing.T) {
	var s *telemetry.Span
	s.SetChannelID(1)
	s.SetError(errors.New("x"))
	s.End()
	if s.Ref().Valid() {
		t.Error("a nil span has a valid ref")
	}
	// No telemetry installed: spans are non-recording and nothing panics.
	ctx, sp := telemetry.StartFailover(context.Background(), telemetry.SpanRef{})
	sp.End()
	h := http.Header{}
	telemetry.InjectTraceparent(ctx, h)
	if h.Get("traceparent") != "" {
		t.Errorf("OTLP off: traceparent injected %q", h.Get("traceparent"))
	}
	r := tuneRequest(false, false)
	_, tune := telemetry.StartTune(r.Context(), r, false)
	tune.FirstByte()
	telemetry.Current().ClientSent(ctx, 1, "mpegts", 5)
}
