package telemetry

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"slices"
	"strings"
	"sync"
	"testing"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
)

// dump renders everything a span carries, so a leak assertion covers fields
// the test did not think to list.
func dump(s sdktrace.ReadOnlySpan) string {
	var b strings.Builder
	fmt.Fprintf(&b, "name=%s status=%v/%s scope=%s\n", s.Name(), s.Status().Code, s.Status().Description, s.InstrumentationScope().Name)
	for _, kv := range s.Attributes() {
		fmt.Fprintf(&b, "attr %s=%s\n", kv.Key, kv.Value.String())
	}
	for _, ev := range s.Events() {
		fmt.Fprintf(&b, "event %s\n", ev.Name)
		for _, kv := range ev.Attributes {
			fmt.Fprintf(&b, "  eattr %s=%s\n", kv.Key, kv.Value.String())
		}
	}
	for _, l := range s.Links() {
		fmt.Fprintf(&b, "link %s\n", l.SpanContext.SpanID())
		for _, kv := range l.Attributes {
			fmt.Fprintf(&b, "  lattr %s=%s\n", kv.Key, kv.Value.String())
		}
	}
	return b.String()
}

func redactedSpans(t *testing.T) (*sdktrace.TracerProvider, *tracetest.InMemoryExporter) {
	t.Helper()
	mem := tracetest.NewInMemoryExporter()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSyncer(newRedactingSpanExporter(mem)))
	t.Cleanup(func() { _ = tp.Shutdown(context.Background()) })
	return tp, mem
}

func TestTheSpanBoundaryDropsEverythingNotAllowlisted(t *testing.T) {
	tp, mem := redactedSpans(t)
	tr := tp.Tracer("mino/relay")

	linked := trace.NewSpanContext(trace.SpanContextConfig{
		TraceID: trace.TraceID{1}, SpanID: trace.SpanID{2}, TraceFlags: trace.FlagsSampled,
	})
	_, sp := tr.Start(context.Background(), SpanNextSource, trace.WithLinks(trace.Link{
		SpanContext: linked,
		Attributes:  []attribute.KeyValue{attribute.String("secret", sentinel)},
	}))
	sp.SetAttributes(
		attribute.Int(AttrChannelID, 42),
		attribute.String(AttrOutcome, OutcomeSource),
		attribute.String(AttrReason, ReasonTune),
		attribute.Int(AttrStatusCode, 200),
		attribute.String(AttrRoute, "GET /proxy/ts/stream/{channelID}"),
		attribute.String("url.full", "http://p/live/u/"+sentinel),
		attribute.String(AttrOutcome+".x", sentinel),
		attribute.String(AttrTrigger, sentinel),
		attribute.String(AttrOutputFormat, sentinel),
	)
	sp.AddEvent("exception", trace.WithAttributes(
		attribute.String(attrExcType, "*url.Error"),
		attribute.String("exception.message", sentinel),
		attribute.String("exception.stacktrace", sentinel),
	))
	sp.AddEvent("with secret "+sentinel, trace.WithAttributes(attribute.String("k", sentinel)))
	sp.SetStatus(codes.Error, "Get http://p/"+sentinel+": refused")
	sp.End()

	spans := mem.GetSpans()
	if len(spans) != 1 {
		t.Fatalf("exported %d spans, want 1", len(spans))
	}
	s := spans[0].Snapshot()
	out := dump(s)
	if !strings.Contains(out, "attr "+AttrChannelID+"=42") || !strings.Contains(out, "attr "+AttrOutcome+"=source") ||
		!strings.Contains(out, "attr "+AttrRoute+"=GET /proxy/ts/stream/{channelID}") {
		t.Errorf("POLICY: an allowlisted attribute was lost:\n%s", out)
	}
	if !strings.Contains(out, "status=Error/*url.Error") || !strings.Contains(out, "eattr "+attrExcType+"=*url.Error") {
		t.Errorf("POLICY: the status description should be the exception type:\n%s", out)
	}
	if len(s.Links()) != 1 {
		t.Errorf("POLICY: the link was lost")
	}
	if strings.Contains(out, sentinel) || strings.Contains(out, "url.full") || strings.Contains(out, "stacktrace") {
		t.Errorf("LEAK: a secret reached the exporter:\n%s", out)
	}
	if got := strings.Count(out, "event "); got != 1 {
		t.Errorf("events exported = %d, want only the exception", got)
	}
}

func TestASpanNamedBySomethingElseTakesTheScopeName(t *testing.T) {
	tp, mem := redactedSpans(t)
	_, sp := tp.Tracer("mino/relay").Start(context.Background(), sentinel)
	sp.End()
	spans := mem.GetSpans()
	if len(spans) != 1 {
		t.Fatalf("exported %d spans", len(spans))
	}
	if got := spans[0].Name; got != "mino/relay" {
		t.Errorf("LEAK or POLICY: span name = %q, want the scope name", got)
	}
}

func TestEveryAttributeRuleRejectsItsHostileValue(t *testing.T) {
	for name, kv := range map[string]attribute.KeyValue{
		"channel id negative":      attribute.Int(AttrChannelID, -1),
		"channel id as string":     attribute.String(AttrChannelID, sentinel),
		"format":                   attribute.String(AttrOutputFormat, "avi"),
		"joined as string":         attribute.String(AttrTuneJoined, "true"),
		"outcome":                  attribute.String(AttrOutcome, sentinel),
		"reason":                   attribute.String(AttrReason, sentinel),
		"trigger":                  attribute.String(AttrTrigger, sentinel),
		"route with a query":       attribute.String(AttrRoute, "GET /live/u/p/1?password="+sentinel),
		"route holding a UUID":     attribute.String(AttrRoute, "GET /proxy/ts/stream/"+chanUUID),
		"bare XC path":             attribute.String(AttrRoute, "GET /user/"+sentinel+"/42"),
		"bare XC path, no method":  attribute.String(AttrRoute, "/user/"+sentinel+"/42"),
		"live XC path":             attribute.String(AttrRoute, "GET /live/user/"+sentinel+"/42"),
		"route not registered":     attribute.String(AttrRoute, "GET /debug/pprof/"),
		"status out of range":      attribute.Int(AttrStatusCode, 999),
		"status as string":         attribute.String(AttrStatusCode, "200"),
		"unlisted key":             attribute.String("http.url", sentinel),
		"exception type is a text": attribute.String(attrExcType, sentinel),
	} {
		if validSpanAttr(kv) {
			t.Errorf("%s: accepted %v", name, kv)
		}
	}
	for _, bad := range []string{sentinel, sentinel + " with spaces", chanUUID, "x." + chanUUID, "", "*", "url.", ".Error", "Get http://p/" + sentinel} {
		if validTypeName(bad) {
			t.Errorf("validTypeName accepted %q", bad)
		}
	}
	for _, good := range []string{"*url.Error", "*errors.errorString", "context.deadlineExceededError", "*fmt.wrapError", "*net.OpError", "*pkg.Wrapped[int]"} {
		if !validTypeName(good) {
			t.Errorf("validTypeName rejected %q", good)
		}
	}
	if !validSpanAttr(attribute.Bool(AttrTuneJoined, true)) {
		t.Error("the tune.joined bool was rejected")
	}
}

type memLogs struct {
	mu   sync.Mutex
	recs []sdklog.Record
}

func (m *memLogs) Export(_ context.Context, recs []sdklog.Record) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, r := range recs {
		m.recs = append(m.recs, r.Clone())
	}
	return nil
}
func (*memLogs) Shutdown(context.Context) error   { return nil }
func (*memLogs) ForceFlush(context.Context) error { return nil }

func TestTheLogExporterIsTheAuthoritativeSecondPass(t *testing.T) {
	mem := &memLogs{}
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(sdklog.NewSimpleProcessor(newRedactingLogExporter(mem, testRules()))))
	// Straight into the bridge, as a record that skipped SafeHandler would.
	l := slog.New(otelslog.NewHandler("mino/relay", otelslog.WithLoggerProvider(lp)))
	l.Info("fetching http://u:p@h:1/live/u/p/1.ts?token=abc "+chanUUID,
		"count", 7,
		"trigger", sentinel,
		"channel", chanUUID,
		"error", errors.New(sentinel),
		sentinel+"-key", 1,
		"format", "mpegts:p3",
	)
	// And through SafeHandler first: its derived keys must survive the exporter.
	slog.New(NewSafeHandler(otelslog.NewHandler("mino/relay", otelslog.WithLoggerProvider(lp)), testRules(), testIDs())).
		Info("safe", "channel", chanUUID, "error", errors.New(sentinel))

	if len(mem.recs) != 2 {
		t.Fatalf("exported %d records, want 2", len(mem.recs))
	}
	first := dumpLog(mem.recs[0])
	if !strings.Contains(first, "count=7") || !strings.Contains(first, "format=mpegts:p3") || !strings.Contains(first, "http://h:1/[redacted]") {
		t.Errorf("POLICY: kept fields or the scrubbed body are missing:\n%s", first)
	}
	for _, bad := range []string{sentinel, chanUUID, "token=abc", "u:p@"} {
		if strings.Contains(first, bad) {
			t.Errorf("LEAK: %q reached the log exporter:\n%s", bad, first)
		}
	}
	second := dumpLog(mem.recs[1])
	if !strings.Contains(second, "channel_id=42") || !strings.Contains(second, "error.type=*errors.errorString") {
		t.Errorf("POLICY: SafeHandler's derived keys were dropped by the exporter:\n%s", second)
	}
	if strings.Contains(second, sentinel) || strings.Contains(second, chanUUID) {
		t.Errorf("LEAK:\n%s", second)
	}
}

func dumpLog(r sdklog.Record) string {

	var b strings.Builder
	body := r.Body()
	fmt.Fprintf(&b, "body=%s\n", body.String())
	r.WalkAttributes(func(kv attribute.KeyValue) bool {
		fmt.Fprintf(&b, "%s=%s\n", kv.Key, kv.Value.String())
		return true
	})
	return b.String()
}

func TestANonStringBodyIsBlanked(t *testing.T) {
	var r sdklog.Record
	r.SetBody(attribute.Int64Value(5))
	e := newRedactingLogExporter(&memLogs{}, testRules())
	out := e.redact(&r)
	if body := out.Body(); body.String() != "" {
		t.Fatalf("body = %q", body.String())
	}
}

type memMetrics struct {
	sdkmetric.Exporter
	got *metricdata.ResourceMetrics
}

func (m *memMetrics) Export(_ context.Context, rm *metricdata.ResourceMetrics) error {
	m.got = rm
	return nil
}

func TestTheMetricExporterDropsPointsWhoseAttributesFailTheirRule(t *testing.T) {
	good := attribute.NewSet(attribute.String("channel_id", "42"), attribute.String("format", "mpegts"))
	badValue := attribute.NewSet(attribute.String("channel_id", chanUUID), attribute.String("format", "mpegts"))
	badKey := attribute.NewSet(attribute.String("url", sentinel))
	badKind := attribute.NewSet(attribute.String("kind", sentinel))
	notString := attribute.NewSet(attribute.Int("channel_id", 4))
	state := attribute.NewSet(attribute.String("state", "active"))
	out := attribute.NewSet(attribute.String("outcome", "switched"), attribute.String("trigger", "health_monitor"), attribute.String("profile_id", "3"), attribute.String("kind", "hls"))

	dp := func(set attribute.Set) metricdata.DataPoint[int64] {
		return metricdata.DataPoint[int64]{Attributes: set, Value: 1, Exemplars: []metricdata.Exemplar[int64]{{Value: 1}}}
	}
	mem := &memMetrics{}
	e := newRedactingMetricExporter(mem)
	err := e.Export(context.Background(), &metricdata.ResourceMetrics{ScopeMetrics: []metricdata.ScopeMetrics{{
		Metrics: []metricdata.Metrics{
			{Name: nameClientSent, Data: metricdata.Sum[int64]{DataPoints: []metricdata.DataPoint[int64]{dp(good), dp(badValue), dp(badKey), dp(badKind), dp(notString), dp(state), dp(out)}}},
			{Name: nameHLSSessions, Data: metricdata.Gauge[float64]{DataPoints: []metricdata.DataPoint[float64]{{Attributes: good, Value: 2}, {Attributes: badKey, Value: 3}}}},
			{Name: nameChannels, Data: metricdata.Gauge[int64]{DataPoints: []metricdata.DataPoint[int64]{dp(good)}}},
			{Name: nameProcessCPU, Data: metricdata.Sum[float64]{DataPoints: []metricdata.DataPoint[float64]{{Attributes: good, Value: 1}}}},
			{Name: nameChannels, Data: metricdata.Histogram[float64]{}},
			{Name: "uncatalogued", Data: metricdata.Gauge[int64]{DataPoints: []metricdata.DataPoint[int64]{dp(good)}}},
		},
	}}})
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	var sumPoints int
	for _, m := range mem.got.ScopeMetrics[0].Metrics {
		names = append(names, m.Name)
		if s, ok := m.Data.(metricdata.Sum[int64]); ok {
			sumPoints = len(s.DataPoints)
			for _, p := range s.DataPoints {
				if len(p.Exemplars) != 0 {
					t.Error("an exemplar was forwarded")
				}
			}
		}
	}
	if strings.Join(names, ",") != strings.Join([]string{nameClientSent, nameHLSSessions, nameChannels, nameProcessCPU}, ",") {
		t.Errorf("metrics = %v, want the histogram and the uncatalogued gauge dropped", names)
	}
	if sumPoints != 3 {
		t.Errorf("sum kept %d points, want 3 (good, state, out)", sumPoints)
	}
}

func TestOtelErrorsLeaveAsATypeNotText(t *testing.T) {
	var buf strings.Builder
	prev := slog.Default()
	slog.SetDefault(slog.New(NewSafeHandler(slog.NewJSONHandler(&buf, nil), DefaultRules, nil)))
	t.Cleanup(func() { slog.SetDefault(prev) })
	prevHandler := otel.GetErrorHandler()
	t.Cleanup(func() { otel.SetErrorHandler(prevHandler) })

	if _, err := Init(context.Background(), Config{SamplerRatio: 1}, WithProcRegistry(nil)); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = Current().Shutdown(context.Background()) })
	otel.Handle(errors.New("Get http://p/live/u/" + sentinel))

	if !strings.Contains(buf.String(), `"error.type":"*errors.errorString"`) {
		t.Errorf("POLICY: the SDK error should leave as its type: %s", buf.String())
	}
	if strings.Contains(buf.String(), sentinel) {
		t.Errorf("LEAK: %s", buf.String())
	}
}

func TestExportedLogKeysAreJudgedByTheSameRules(t *testing.T) {
	r := testRules()
	for _, tc := range []struct {
		key  string
		v    val
		want bool
	}{
		{"channel_id", val{k: vStr, s: "42"}, true},
		{"channel_id", val{k: vStr, s: chanUUID}, false},
		{"error.type", val{k: vStr, s: "*url.Error"}, true},
		{"error.type", val{k: vStr, s: sentinel}, false},
		{"error.type", val{k: vStr, s: sentinel + " text"}, false},
		{"other.type", val{k: vStr, s: "*url.Error"}, false},
		{"channel", val{k: vStr, s: chanUUID}, false},
		{"took", val{k: vInt, i: 5}, true},
		{"count", val{k: vInt, i: 5}, true},
		{"count", val{k: vStr, s: "5"}, false},
		{"unknown", val{k: vInt, i: 5}, false},
	} {
		if got := r.classifyExported(tc.key, tc.v); got != tc.want {
			t.Errorf("classifyExported(%q, %+v) = %v, want %v", tc.key, tc.v, got, tc.want)
		}
	}
}

// The text format has no SafeHandler in front of it, so the call site itself
// must send only the type: an export error's text carries the collector URL.
func TestOtelErrorsLeaveNoURLInTheTextFormat(t *testing.T) {
	var buf strings.Builder
	prev := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&buf, nil)))
	t.Cleanup(func() { slog.SetDefault(prev) })
	prevHandler := otel.GetErrorHandler()
	t.Cleanup(func() { otel.SetErrorHandler(prevHandler) })

	tel, err := Init(context.Background(), Config{SamplerRatio: 1})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tel.Shutdown(context.Background()) })
	otel.Handle(&url.Error{Op: "Post", URL: "https://collector.example/v1/traces?api_key=" + sentinel, Err: errors.New("dial tcp: refused")})

	out := buf.String()
	if !strings.Contains(out, "otel error") || !strings.Contains(out, "error.type=") {
		t.Errorf("POLICY: no typed error line: %s", out)
	}
	for _, bad := range []string{sentinel, "collector.example", "api_key", "refused"} {
		if strings.Contains(out, bad) {
			t.Errorf("LEAK: %q in the text-format output: %s", bad, out)
		}
	}
}

// error.type carries a %T the call site computed itself, so it is judged by
// shape: a type name passes, any other string (a sentinel, a URL, a UUID) drops.
func TestErrorTypeKeyKeepsTypeNamesAndDropsEverythingElse(t *testing.T) {
	r := DefaultRules
	for _, tc := range []struct {
		s    string
		want bool
	}{
		{"*url.Error", true},
		{"*errors.errorString", true},
		{sentinel, false},
		{"Get http://p/live/u/" + sentinel, false},
		{chanUUID, false},
		{"x." + chanUUID, false},
		{"http://u:p@h/x", false},
		{"", false},
	} {
		_, got, ok := r.classify("error.type", val{k: vStr, s: tc.s}, nil)
		if ok != tc.want {
			t.Errorf("classify(error.type, %q) kept=%v, want %v", tc.s, ok, tc.want)
		}
		if ok && got.s != tc.s {
			t.Errorf("classify rewrote %q to %q", tc.s, got.s)
		}
	}
}

// Every mux pattern registered in httpapi is in the closed set, and the set
// holds nothing else. A new route that is not added to RoutePatterns fails here.
//
// Limits: it reads only the string-literal registrations on s.mux in
// httpapi/server.go. A route registered another way (a variable pattern, another
// mux, another file) is not seen and must be added to RoutePatterns by hand.
func TestRoutePatternsEqualTheRegisteredMuxPatterns(t *testing.T) {
	src, err := os.ReadFile("../httpapi/server.go")
	if err != nil {
		t.Fatal(err)
	}
	re := regexp.MustCompile(`s\.mux\.Handle(?:Func)?\("([^"]+)"`)
	var found []string
	for _, m := range re.FindAllStringSubmatch(string(src), -1) {
		found = append(found, m[1])
	}
	want := slices.Clone(RoutePatterns)
	slices.Sort(want)
	slices.Sort(found)
	if !slices.Equal(found, want) {
		t.Fatalf("registered patterns differ from telemetry.RoutePatterns:\n registered: %q\n set:        %q", found, want)
	}
	if len(found) != 14 {
		t.Errorf("%d patterns, want 14", len(found))
	}
}

// Round-3 finding 5, the spec's D9 case: relay.next_source failing through the
// RoundTripper. The *url.Error carries the provider URL in its text; only the
// INNERMOST type (the transport's error, not *url.Error) leaves, as both the
// exception event's type and the status description, through the real
// redacting exporter.
func TestANextSourceFailingThroughTheRoundTripperLeavesOnlyTheInnermostType(t *testing.T) {
	tp, mem := redactedSpans(t)
	if _, err := Init(context.Background(), Config{SamplerRatio: 1}, WithTracerProvider(tp)); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = Current().Shutdown(context.Background()) })

	failing := roundTripFunc(func(*http.Request) (*http.Response, error) { return nil, errors.New("refused") })
	client := &http.Client{Transport: failing}
	ctx, ns := StartNextSource(context.Background(), ReasonTune)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://django.example/api/relay/channels/"+chanUUID+"/next-source?token="+sentinel, nil)
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Do(req) //nolint:bodyclose // the stub transport returns no body
	var uerr *url.Error
	if !errors.As(err, &uerr) || !strings.Contains(err.Error(), sentinel) {
		t.Fatalf("control: want a *url.Error carrying the URL, got %T %v", err, err)
	}
	ns.SetError(err)
	ns.End()

	spans := mem.GetSpans()
	if len(spans) != 1 {
		t.Fatalf("exported %d spans", len(spans))
	}
	out := dump(spans[0].Snapshot())
	if !strings.Contains(out, "status=Error/*errors.errorString") || !strings.Contains(out, "eattr "+attrExcType+"=*errors.errorString") {
		t.Errorf("POLICY: want the innermost type *errors.errorString (not the outermost *url.Error) as status and event:\n%s", out)
	}
	for _, bad := range []string{sentinel, chanUUID, "django.example", "*url.Error"} {
		if strings.Contains(out, bad) {
			t.Errorf("LEAK: %q reached the exporter:\n%s", bad, out)
		}
	}
}

// Round-3 finding 5: with no exception event the status description is empty,
// whatever was set, so the "never kept" rule is what stops the text here.
func TestAStatusDescriptionWithNoExceptionEventIsNeverKept(t *testing.T) {
	tp, mem := redactedSpans(t)
	_, sp := tp.Tracer("mino/relay").Start(context.Background(), SpanNextSource)
	sp.SetStatus(codes.Error, "Get http://p/live/u/"+sentinel)
	sp.End()
	spans := mem.GetSpans()
	if len(spans) != 1 {
		t.Fatalf("exported %d spans", len(spans))
	}
	s := spans[0].Snapshot()
	if s.Status().Code != codes.Error {
		t.Errorf("POLICY: the error code was lost: %v", s.Status())
	}
	if d := s.Status().Description; d != "" {
		t.Errorf("LEAK: a description with no exception event was kept: %q", d)
	}
}

// Round-3 nit 10. The SDK's cardinality-limit overflow point carries
// otel.metric.overflow=true and must reach OTLP as it reaches /metrics; any
// other shape of that key is still refused.
func TestTheOverflowSeriesPassesTheMetricBoundary(t *testing.T) {
	for _, tc := range []struct {
		set  attribute.Set
		want bool
	}{
		{attribute.NewSet(attribute.Bool(overflowKey, true)), true},
		{attribute.NewSet(attribute.Bool(overflowKey, false)), false},
		{attribute.NewSet(attribute.String(overflowKey, "true")), false},
		{attribute.NewSet(attribute.Bool(overflowKey, true), attribute.String("channel_id", sentinel)), false},
		{attribute.NewSet(attribute.Bool("other", true)), false},
	} {
		if got := validMetricAttrs(tc.set); got != tc.want {
			t.Errorf("%v: valid = %v, want %v", tc.set.ToSlice(), got, tc.want)
		}
	}
}

// Round-5 nit 1. build itself reaches otel.Handle: sdkmetric.WithResource
// reads OTEL_RESOURCE_ATTRIBUTES and NewMeterProvider reads
// OTEL_GO_X_CARDINALITY_LIMIT, and each hands a malformed value's text to the
// error handler. So the handler must be ours before build runs, or that text
// reaches whatever handler was installed (by default, stderr).
func TestTheErrorHandlerIsInstalledBeforeBuildReadsTheEnvironment(t *testing.T) {
	for name, v := range map[string]string{
		"OTEL_RESOURCE_ATTRIBUTES":    sentinel + "-no-equals",
		"OTEL_GO_X_CARDINALITY_LIMIT": sentinel,
	} {
		t.Run(name, func(t *testing.T) {
			var buf strings.Builder
			prev := slog.Default()
			slog.SetDefault(slog.New(NewSafeHandler(slog.NewJSONHandler(&buf, nil), DefaultRules, nil)))
			t.Cleanup(func() { slog.SetDefault(prev) })
			prevHandler := otel.GetErrorHandler()
			t.Cleanup(func() { otel.SetErrorHandler(prevHandler) })
			var got []string
			otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) { got = append(got, err.Error()) }))
			t.Setenv(name, v)

			tel, err := Init(context.Background(), Config{}, WithProcRegistry(nil))
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = tel.Shutdown(context.Background()) })
			if len(got) != 0 {
				t.Errorf("LEAK: build reported %q to the handler installed before Init: ours was installed after build", got)
			}
			if !strings.Contains(buf.String(), `"error.type"`) || strings.Contains(buf.String(), sentinel) {
				t.Errorf("POLICY: want the SDK error logged as its type only: %s", buf.String())
			}
		})
	}
}
