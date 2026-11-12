package telemetry

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	sdklog "go.opentelemetry.io/otel/sdk/log"
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

// otlpLogs starts a collector, Inits with OTLP on in the given log format and
// a channel id mapped, and returns the telemetry and a reader for /v1/logs.
func otlpLogs(t *testing.T, format string, extraEnv map[string]string) (*Telemetry, func() string, func() string) {
	t.Helper()
	var mu sync.Mutex
	bodies := map[string][]byte{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		bodies[r.URL.Path] = append(bodies[r.URL.Path], b...)
		mu.Unlock()
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	t.Setenv(envEndpoint, srv.URL)
	t.Setenv(envLogFormat, format)
	for k, v := range extraEnv {
		t.Setenv(k, v)
	}
	prev := otel.GetTracerProvider()
	t.Cleanup(func() { otel.SetTracerProvider(prev) })
	cfg := LoadConfig(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if !cfg.OTLP || !cfg.Logs || cfg.LogFormat != format {
		t.Fatalf("config = %+v", cfg)
	}
	tel, err := Init(context.Background(), cfg, WithChannelIDs(testIDs()))
	if err != nil {
		t.Fatal(err)
	}
	read := func(path string) func() string {
		return func() string {
			mu.Lock()
			defer mu.Unlock()
			return string(bodies[path])
		}
	}
	return tel, read("/v1/logs"), read("/v1/metrics")
}

// channelIDKV is the protobuf encoding of the OTLP KeyValue
// {key: "channel_id", value: {string_value: "42"}}: field 1 (key) of length
// 10, then field 2 (AnyValue) of length 4 holding field 1 (string) "42".
const channelIDKV = "\x0a\x0achannel_id\x12\x04\x0a\x0242"

// Round-3 finding 7. The otelslog bridge sits INSIDE SafeHandler in both
// formats, so an OTLP log record carries the same channel_id mapping as the
// JSON line and never the UUID. Without SafeHandler in front, the log
// exporter's second pass drops the raw channel key and channel_id is lost.
func TestOTLPLogsCarryTheMappedChannelIDInBothFormats(t *testing.T) {
	for _, format := range []string{LogFormatText, LogFormatJSON} {
		t.Run(format, func(t *testing.T) {
			tel, logs, _ := otlpLogs(t, format, nil)
			var stdout bytes.Buffer
			log := slog.New(tel.LogHandler(&stdout, slog.NewTextHandler(io.Discard, nil)))
			log.Error("tune failed", "channel", chanUUID, "error", &url.Error{Op: "Get", URL: "http://p/" + sentinel, Err: errors.New("x")})
			if err := tel.Shutdown(context.Background()); err != nil {
				t.Fatal(err)
			}
			body := logs()
			if !strings.Contains(body, "tune failed") {
				t.Fatalf("POLICY: the record did not reach /v1/logs (%d bytes)", len(body))
			}
			if !strings.Contains(body, channelIDKV) {
				t.Errorf("POLICY: the OTLP record lacks channel_id=42: the bridge is not behind SafeHandler")
			}
			if !strings.Contains(body, "error.type") || !strings.Contains(body, "*errors.errorString") {
				t.Errorf("POLICY: the OTLP record lacks error.type")
			}
			for _, bad := range []string{chanUUID, sentinel} {
				if strings.Contains(body, bad) {
					t.Errorf("LEAK: %q reached /v1/logs", bad)
				}
			}
		})
	}
}

// Round-3 nit 15. The OTel error handler's own line goes to stdout but never
// to the OTLP log sink, so a failing log export cannot queue a record about
// itself.
func TestTheOTelErrorLineSkipsTheOTLPLogSink(t *testing.T) {
	tel, logs, _ := otlpLogs(t, LogFormatJSON, nil)
	var stdout bytes.Buffer
	prev := slog.Default()
	slog.SetDefault(slog.New(tel.LogHandler(&stdout, slog.NewTextHandler(io.Discard, nil))))
	t.Cleanup(func() { slog.SetDefault(prev) })
	otel.Handle(errors.New("export failed"))
	slog.Info("ordinary line")
	if err := tel.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(stdout.String(), `"msg":"otel error"`) {
		t.Fatalf("control: the error line did not reach stdout: %s", stdout.String())
	}
	body := logs()
	if !strings.Contains(body, "ordinary line") {
		t.Fatalf("control: an ordinary line did not reach /v1/logs (%d bytes)", len(body))
	}
	if strings.Contains(body, "otel error") {
		t.Error("the OTel error line was queued for OTLP export")
	}
}

// Round-3 nit 13. When the last step of startOTLP fails, Init returns the
// error AND stops what it had started: the meter provider's periodic reader,
// whose shutdown flushes one final export, and no global tracer provider is
// left installed. The interval is an hour, so only that flush can export.
func TestAFailedStartOTLPShutsDownWhatInitStarted(t *testing.T) {
	prevExp := newOTLPLogExporter
	newOTLPLogExporter = func(context.Context) (sdklog.Exporter, error) { return nil, errors.New("no log exporter") }
	t.Cleanup(func() { newOTLPLogExporter = prevExp })
	before := otel.GetTracerProvider()

	var mu sync.Mutex
	var metrics []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		if r.URL.Path == "/v1/metrics" {
			mu.Lock()
			metrics = append(metrics, b...)
			mu.Unlock()
		}
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	t.Setenv(envEndpoint, srv.URL)
	t.Setenv("OTEL_METRIC_EXPORT_INTERVAL", "3600000")
	cfg := LoadConfig(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))

	tel, err := Init(context.Background(), cfg)
	if err == nil || tel != nil {
		t.Fatalf("Init = %v, %v; want the log exporter's error", tel, err)
	}
	if otel.GetTracerProvider() != before {
		t.Error("a failed Init left its tracer provider installed as the global")
	}
	if Current() == nil || Current().Config().OTLP {
		t.Error("a failed Init was installed as Current")
	}
	mu.Lock()
	defer mu.Unlock()
	if len(metrics) == 0 {
		t.Error("the meter provider was not shut down: its periodic reader is still running")
	}
}

// skipMarked's own Handle check, for a caller that does not ask Enabled
// first (Fanout does; a direct caller need not): a marked record must still
// not reach the OTLP sink.
func TestSkipMarkedDropsAMarkedRecordEvenWithoutEnabled(t *testing.T) {
	var buf bytes.Buffer
	h := skipMarked{slog.NewTextHandler(&buf, nil)}
	r := slog.NewRecord(time.Now(), slog.LevelError, "otel error", 0)
	if err := h.Handle(withoutOTLPLogs(context.Background()), r); err != nil || buf.Len() != 0 {
		t.Fatalf("a marked record reached the sink: %q, %v", buf.String(), err)
	}
	if err := h.Handle(context.Background(), r); err != nil || !strings.Contains(buf.String(), "otel error") {
		t.Fatalf("an unmarked record was dropped: %q, %v", buf.String(), err)
	}
}
