package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// GET /metrics is an operational endpoint like the probes (observability spec
// D4): served with the dev flag off, and answered by the handler main passes.
func TestMetricsIsServedWithoutTheDevFlag(t *testing.T) {
	rec := telemetrytest.Install(t)
	rec.T.ObserveChannels(func() map[string]int { return map[string]int{"active": 1} })
	for _, dev := range []bool{false, true} {
		srv := New(Config{DevRoutes: dev, Metrics: rec.T.Metrics()})
		w := httptest.NewRecorder()
		srv.Handler().ServeHTTP(w, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/metrics", nil))
		if w.Code != http.StatusOK {
			t.Fatalf("DevRoutes=%v: GET /metrics = %d, want 200", dev, w.Code)
		}
		if !strings.Contains(w.Body.String(), "# TYPE mino_relay_channels gauge") {
			t.Errorf("DevRoutes=%v: GET /metrics carries no catalogue family:\n%s", dev, w.Body.String())
		}
	}
}

// A nil Metrics registers nothing: the route is a 404 from the mux.
func TestANilMetricsHandlerRegistersNoRoute(t *testing.T) {
	srv := New(Config{})
	w := httptest.NewRecorder()
	srv.Handler().ServeHTTP(w, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/metrics", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("GET /metrics with no handler = %d, want 404", w.Code)
	}
}
