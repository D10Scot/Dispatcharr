package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

// Drives the real mux and asserts what a client would see. A test that built
// its own http.HandlerFunc and asserted it was called would pass with this
// whole package deleted.
func TestHealthEndpointsAnswer200(t *testing.T) {
	srv := New(Config{DevRoutes: false})
	for _, path := range []string{"/healthz", "/readyz"} {
		rec := httptest.NewRecorder()
		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, path, nil))
		if rec.Code != http.StatusOK {
			t.Errorf("GET %s = %d, want 200", path, rec.Code)
		}
		if got := rec.Body.String(); got != "ok\n" {
			t.Errorf("GET %s body = %q, want %q", path, got, "ok\n")
		}
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
