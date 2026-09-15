package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// Drives the real mux and asserts what a client would see. A test that built
// its own http.HandlerFunc and asserted it was called would pass with this
// whole package deleted.
// The two endpoints answer 200 and they answer DIFFERENTLY, which is 2c-8's
// change to 2c-1's shape: /healthz is still liveness and still the literal
// "ok", and /readyz now reports something real (spec D6).
func TestHealthEndpointsAnswer200(t *testing.T) {
	srv := New(Config{DevRoutes: false})

	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/healthz", nil))
	if rec.Code != http.StatusOK {
		t.Errorf("GET /healthz = %d, want 200", rec.Code)
	}
	if got := rec.Body.String(); got != "ok\n" {
		t.Errorf("GET /healthz body = %q, want %q", got, "ok\n")
	}

	rec = httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/readyz", nil))
	if rec.Code != http.StatusOK {
		t.Errorf("GET /readyz = %d, want 200", rec.Code)
	}
	var body struct {
		Status   string `json:"status"`
		Channels int    `json:"channels"`
		Clients  int    `json:"clients"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("GET /readyz body %q is not JSON: %v", rec.Body.String(), err)
	}
	if body.Status != StatusReady {
		t.Errorf("GET /readyz status = %q, want %q", body.Status, StatusReady)
	}
	// Asserted as well as the status, because a body that reported only
	// "ready" would be the static 200 under a new name -- which is exactly
	// what 2c-1 refused to wire a HEALTHCHECK to.
	if body.Channels != 0 || body.Clients != 0 {
		t.Errorf("GET /readyz counted %d channels and %d clients on an empty relay", body.Channels, body.Clients)
	}
}

// The health endpoints must not depend on the dev flag: a deployment with the
// flag off still needs to be probeable, and that is the shape stage 2d relies
// on.
func TestHealthEndpointsIgnoreTheDevFlag(t *testing.T) {
	for _, dev := range []bool{true, false} {
		srv := New(Config{DevRoutes: dev})
		rec := httptest.NewRecorder()
		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/healthz", nil))
		if rec.Code != http.StatusOK {
			t.Errorf("DevRoutes=%v: GET /healthz = %d, want 200", dev, rec.Code)
		}
	}
}

// The flag's whole purpose: with it off, a stream URL is a 404 from the mux,
// not a 501 from a registered handler. 404 and 501 are different answers and
// the difference is the assertion -- a test that only checked "not 200" would
// pass with the route registered and the handler erroring.
func TestStreamRouteIsUnregisteredWithoutTheDevFlag(t *testing.T) {
	srv := New(Config{DevRoutes: false})

	// EVERY GATED ROUTE, not just the first one. 2c-8 adds six -- the two XC
	// live roots and the four control routes -- and one of them,
	// GET /{username}/{password}/{channelID}, is the broadest pattern this
	// relay has ever registered: three bare wildcards at the site root. The
	// plan's opening claim is that this PR is inert in every deployment, and
	// a test that checks one path of seven cannot carry it.
	for _, tc := range []struct {
		method, path string
	}{
		{http.MethodGet, "/proxy/ts/stream/abc"},
		{http.MethodGet, "/live/user/pass/12345"},
		{http.MethodGet, "/user/pass/12345"},
		{http.MethodGet, "/proxy/relay/channels"},
		{http.MethodGet, "/proxy/relay/channels/abc"},
		{http.MethodDelete, "/proxy/relay/channels/abc/clients/client-a"},
		{http.MethodPost, "/proxy/relay/channels/abc/advance"},
	} {
		rec := httptest.NewRecorder()
		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), tc.method, tc.path, nil))
		if rec.Code != http.StatusNotFound {
			t.Errorf("%s %s with DevRoutes=false = %d, want 404 (the route must not be registered at all)",
				tc.method, tc.path, rec.Code)
		}
	}

	// And the two operational endpoints are still served, so "the mux is
	// empty" cannot be what makes the seven above pass.
	for _, path := range []string{"/healthz", "/readyz"} {
		rec := httptest.NewRecorder()
		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, path, nil))
		if rec.Code != http.StatusOK {
			t.Errorf("GET %s with DevRoutes=false = %d, want 200", path, rec.Code)
		}
	}
}

// ServeMux's method matching, asserted because it is doing real work here:
// without the "GET " prefix on the pattern, this is a 200 and any client can
// POST to the health endpoints.
func TestHealthEndpointsRejectNonGET(t *testing.T) {
	srv := New(Config{DevRoutes: false})
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodPost, "/healthz", nil))
	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST /healthz = %d, want 405", rec.Code)
	}
}

func TestUnknownPathIs404(t *testing.T) {
	srv := New(Config{DevRoutes: true})
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/anything-else", nil))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("GET /anything-else = %d, want 404", rec.Code)
	}
}
