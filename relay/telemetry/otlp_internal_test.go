package telemetry

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/trace"
)

// The log pipeline has two boundaries, and SafeHandler hides the second when
// both are in place. This drives the REAL OTLP pipeline Init builds through a
// bridge handler that skips SafeHandler, so only the redacting log exporter
// stands between the record and the wire.
func TestOTLPLogsAreRedactedByTheExporterWhenSafeHandlerIsBypassed(t *testing.T) {
	var mu sync.Mutex
	var logsBody []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		if r.URL.Path == "/v1/logs" {
			mu.Lock()
			logsBody = append(logsBody, b...)
			mu.Unlock()
		}
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	t.Setenv(envEndpoint, srv.URL)

	cfg := LoadConfig(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	tel, err := Init(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	raw := slog.New(otelslog.NewHandler(ScopeName, otelslog.WithLoggerProvider(tel.logs)))
	raw.Info("raw record http://u:p@h/live/u/"+sentinel+"/1.ts", "channel", chanUUID, "trigger", sentinel, "count", 7)
	if err := tel.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}

	mu.Lock()
	defer mu.Unlock()
	body := string(logsBody)
	if !strings.Contains(body, "raw record http://h/[redacted]") {
		t.Fatalf("POLICY: the scrubbed body did not reach the wire (%d bytes)", len(body))
	}
	for _, bad := range []string{sentinel, chanUUID, "u:p@"} {
		if strings.Contains(body, bad) {
			t.Errorf("LEAK: %q reached the OTLP log export through a bypassed SafeHandler", bad)
		}
	}
}

// otlpHarness starts a collector, points the environment at it and runs Init
// with OTLP on and a fast metric interval.
type otlpHarness struct {
	mu     sync.Mutex
	bodies map[string][]byte
	tel    *Telemetry
}

func newOTLPHarness(t *testing.T) *otlpHarness {
	t.Helper()
	h := &otlpHarness{bodies: map[string][]byte{}}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		h.mu.Lock()
		h.bodies[r.URL.Path] = append(h.bodies[r.URL.Path], b...)
		h.mu.Unlock()
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	t.Setenv(envEndpoint, srv.URL)
	t.Setenv("OTEL_METRIC_EXPORT_INTERVAL", "100")
	prev := otel.GetTracerProvider()
	t.Cleanup(func() { otel.SetTracerProvider(prev) })

	cfg := LoadConfig(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	tel, err := Init(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	h.tel = tel
	return h
}

func (h *otlpHarness) flush(t *testing.T) {
	t.Helper()
	if err := h.tel.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func (h *otlpHarness) body(path string) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return string(h.bodies[path])
}

// Spans: hostile attributes, an exception event with a message and a status
// description are put on a span of the REAL tracer Init built. Only the
// redacting span exporter stands between them and the wire.
func TestOTLPSpansAreRedactedByTheExporter(t *testing.T) {
	h := newOTLPHarness(t)
	_, sp := h.tel.tracer.Start(context.Background(), SpanTune)
	sp.SetAttributes(attribute.String("url.full", "http://p/live/u/"+sentinel), attribute.String(AttrRoute, "GET /user/"+sentinel+"/42"), attribute.Int(AttrChannelID, 7))
	sp.AddEvent("exception", trace.WithAttributes(attribute.String("exception.message", sentinel), attribute.String(attrExcType, "*url.Error")))
	sp.SetStatus(codes.Error, "Get http://p/"+sentinel)
	sp.End()
	h.flush(t)

	body := h.body("/v1/traces")
	if !strings.Contains(body, SpanTune) || !strings.Contains(body, "*url.Error") {
		t.Fatalf("POLICY: the span did not reach the wire (%d bytes)", len(body))
	}
	if strings.Contains(body, sentinel) || strings.Contains(body, "url.full") {
		t.Errorf("LEAK: a hostile span value reached the OTLP trace export")
	}
}

// Metrics: a point with a hostile attribute value on a catalogued instrument,
// recorded on the real meter provider's own meter.
func TestOTLPMetricsAreRedactedByTheExporter(t *testing.T) {
	h := newOTLPHarness(t)
	c, err := h.tel.mp.Meter(ScopeName).Int64Counter(nameClientSent)
	if err != nil {
		t.Fatal(err)
	}
	c.Add(context.Background(), 5, metric.WithAttributes(attribute.String("channel_id", sentinel)))
	h.tel.ClientSent(context.Background(), 7, FormatMPEGTS, 188)
	time.Sleep(300 * time.Millisecond)
	h.flush(t)

	body := h.body("/v1/metrics")
	if !strings.Contains(body, nameClientSent) {
		t.Fatalf("POLICY: the catalogued point did not reach the wire (%d bytes)", len(body))
	}
	if strings.Contains(body, sentinel) {
		t.Errorf("LEAK: a hostile metric attribute reached the OTLP metric export")
	}
}

// One Init is one process: the trace, metric and log resources must carry the
// SAME service.instance.id, or a backend cannot join them.
func TestOneInstanceIDAcrossTracesMetricsAndLogs(t *testing.T) {
	h := newOTLPHarness(t)
	var id string
	for _, kv := range h.tel.res.Attributes() {
		if kv.Key == "service.instance.id" {
			id = kv.Value.AsString()
		}
	}
	if id == "" {
		t.Fatal("the resource has no service.instance.id")
	}
	_, sp := h.tel.tracer.Start(context.Background(), SpanTune)
	sp.End()
	h.tel.ClientSent(context.Background(), 7, FormatMPEGTS, 188)
	raw := slog.New(otelslog.NewHandler(ScopeName, otelslog.WithLoggerProvider(h.tel.logs)))
	raw.Info("hello")
	time.Sleep(300 * time.Millisecond)
	h.flush(t)

	for _, path := range []string{"/v1/traces", "/v1/metrics", "/v1/logs"} {
		if !strings.Contains(h.body(path), id) {
			t.Errorf("%s does not carry service.instance.id %s", path, id)
		}
	}
}
