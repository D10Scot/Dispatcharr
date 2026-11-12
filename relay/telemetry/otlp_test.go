package telemetry_test

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/otel"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
)

// A collector that records every OTLP/HTTP body by path.
type collector struct {
	mu     sync.Mutex
	bodies map[string][]byte
}

func (c *collector) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	b, _ := io.ReadAll(r.Body)
	c.mu.Lock()
	c.bodies[r.URL.Path] = append(c.bodies[r.URL.Path], b...)
	c.mu.Unlock()
	w.Header().Set("Content-Type", "application/x-protobuf")
	w.WriteHeader(http.StatusOK)
}

func (c *collector) body(path string) string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return string(c.bodies[path])
}

func TestOTLPOnExportsAllThreeSignalsAndNoSecret(t *testing.T) {
	col := &collector{bodies: map[string][]byte{}}
	srv := httptest.NewServer(col)
	t.Cleanup(srv.Close)
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", srv.URL)
	t.Setenv("OTEL_METRIC_EXPORT_INTERVAL", "100")
	t.Setenv("MINO_LOG_FORMAT", "json")

	prev := otel.GetTracerProvider()
	t.Cleanup(func() { otel.SetTracerProvider(prev) })

	cfg := telemetry.LoadConfig(nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if !cfg.OTLP || !cfg.Traces || !cfg.Metrics || !cfg.Logs {
		t.Fatalf("config = %+v", cfg)
	}
	tel, err := telemetry.Init(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}

	var stderr bytes.Buffer
	log := slog.New(tel.LogHandler(&stderr, slog.NewTextHandler(io.Discard, nil)))

	r := tuneRequest(false, false)
	ctx, tune := telemetry.StartTune(r.Context(), r, false)
	tune.SetChannelID(7)
	nctx, ns := telemetry.StartNextSource(ctx, telemetry.ReasonTune)
	ns.SetError(io.ErrUnexpectedEOF)
	ns.End()
	_ = nctx
	log.InfoContext(ctx, "tuned http://u:p@h/live/u/"+sentinel+"/1.ts", "channel", chanUUID, "bogus", sentinel)
	tel.ClientSent(ctx, 7, "mpegts", 188)
	tune.FirstByte()
	tune.End()

	time.Sleep(300 * time.Millisecond) // one metric export interval
	flush, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := tel.Shutdown(flush); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}
	if err := tel.Shutdown(flush); err != nil {
		t.Fatalf("a second Shutdown must be harmless: %v", err)
	}

	for path, want := range map[string]string{
		"/v1/traces":  "relay.tune",
		"/v1/metrics": "mino_relay_client_sent",
		"/v1/logs":    "tuned http://h/[redacted]",
	} {
		body := col.body(path)
		if !strings.Contains(body, want) {
			t.Errorf("POLICY: %s carried no %q (%d bytes)", path, want, len(body))
		}
		for _, bad := range []string{sentinel, chanUUID, "u:p@"} {
			if strings.Contains(body, bad) {
				t.Errorf("LEAK: %s carried %q", path, bad)
			}
		}
	}
	if !strings.Contains(col.body("/v1/traces"), "mino-relay") {
		t.Error("the resource's service.name is missing from the trace export")
	}
	if strings.Contains(stderr.String(), sentinel) {
		t.Errorf("LEAK on stdout JSON: %s", stderr.String())
	}
}
