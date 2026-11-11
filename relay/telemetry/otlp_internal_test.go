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

	"go.opentelemetry.io/contrib/bridges/otelslog"
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
