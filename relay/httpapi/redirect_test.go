package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// redirectRig is a rig whose control plane names the Redirect profile.
func redirectRig(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config) *rig {
	t.Helper()
	cp.Kind = control.KindRedirect
	return fanRigWith(t, cp, up, nil)
}

// tuneNoFollow is rig.tune with redirects NOT followed, so a 302 is the
// answer rather than a fetch of the provider.
func (r *rig) tuneNoFollow(t *testing.T, path string, header http.Header) *http.Response {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+path, nil)
	if err != nil {
		t.Fatalf("building the tune request: %v", err)
	}
	for name, values := range header {
		for _, v := range values {
			request.Header.Add(name, v)
		}
	}
	client := r.Relay.Client()
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := client.Do(request)
	if err != nil {
		t.Fatalf("tuning: %v", err)
	}
	return response
}

// THE REDIRECT ARCHITECTURE (views.py:468-540; e2e stream-profiles.spec.ts):
// the client is handed the provider URL -- the one validated, not wherever
// the probe was sent -- with a 302, no bytes traverse the relay (the
// provider sees the HEAD probe and nothing else), no channel exists for the
// list endpoint to render, and the slot the tune reserved is released
// before the answer.
func TestARedirectProfileHandsTheClientTheProviderURLAndFetchesNothing(t *testing.T) {
	r := redirectRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect", nil)
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusFound {
		t.Fatalf("a Redirect channel answered %d, want 302", response.StatusCode)
	}
	if got := response.Header.Get("Location"); got != r.Upstream.URL() {
		t.Fatalf("Location = %q, want the provider URL %q", got, r.Upstream.URL())
	}
	if methods := r.Upstream.Methods(); len(methods) != 1 || methods[0] != http.MethodHead {
		t.Fatalf("the provider saw %v, want exactly one HEAD probe and no GET", methods)
	}
	if r.Manager.Get("c-redirect") != nil {
		t.Fatal("a Redirect tune left a channel in the manager")
	}
	status, body := r.listChannels(t, "")
	if status != http.StatusOK || !strings.Contains(string(body), `"count":0`) {
		t.Fatalf("the list endpoint answered %d %s after a Redirect tune, want an empty list: nothing was initialised", status, body)
	}
	releases := r.Control.RequestsTo("/release")
	if len(releases) != 1 || !strings.Contains(string(releases[0].Body), `"stream_id":1`) {
		t.Fatalf("release calls = %+v, want one for stream 1 before the redirect", releases)
	}
}

// When the primary fails validation the cached alternates are tried in turn
// (views.py:483-514): HEAD then GET on the primary, both 404, then the
// alternate validates and is the Location.
func TestARedirectFallsThroughToACachedAlternateWhenTheProbeFails(t *testing.T) {
	alternate := relaytest.NewUpstream(relaytest.Config{})
	t.Cleanup(alternate.Close)
	r := redirectRig(t, relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}, relaytest.Config{Status: 404})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-alt", nil)
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusFound {
		t.Fatalf("answered %d, want 302", response.StatusCode)
	}
	if got := response.Header.Get("Location"); got != alternate.URL() {
		t.Fatalf("Location = %q, want the alternate %q", got, alternate.URL())
	}
	if methods := r.Upstream.Methods(); len(methods) != 2 || methods[0] != http.MethodHead || methods[1] != http.MethodGet {
		t.Fatalf("the primary saw %v, want a HEAD then a GET before it was given up on", methods)
	}
}

// Every candidate failing validation is a 502 with views.py:545-547's JSON
// body, and the slot is still released.
func TestARedirectWhoseEveryCandidateFailsValidationIs502(t *testing.T) {
	alternate := relaytest.NewUpstream(relaytest.Config{Status: 500})
	t.Cleanup(alternate.Close)
	r := redirectRig(t, relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}, relaytest.Config{Status: 404})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-none", nil)
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("answered %d, want 502", response.StatusCode)
	}
	body, _ := io.ReadAll(response.Body)
	var decoded map[string]any
	if err := json.Unmarshal(body, &decoded); err != nil || decoded["error"] != "All available streams failed validation" {
		t.Fatalf("body = %s, want {\"error\": \"All available streams failed validation\"}", body)
	}
	if len(r.Control.RequestsTo("/release")) != 1 {
		t.Fatal("the slot was not released after a failed validation")
	}
}

// THE INTERNAL-PRINCIPAL OVERRIDE (views.py:445-467, Phase 1 PR 5): a
// request carrying a valid X-Dispatcharr-Internal on a Redirect channel is
// served through the Proxy path -- a 200 with the provider's bytes -- so the
// header is never re-sent to a provider by a 302.
func TestAnInternalPrincipalOnARedirectChannelIsServedThroughProxy(t *testing.T) {
	r := redirectRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-dvr", http.Header{
		control.HeaderInternal: []string{control.InternalPrincipalToken(testSecret)},
	})
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusOK {
		t.Fatalf("an internal principal on a Redirect channel answered %d, want 200 through Proxy", response.StatusCode)
	}
	if got := response.Header.Get("Content-Type"); got != "video/mp2t" {
		t.Fatalf("Content-Type = %q", got)
	}
	packetRun(t, "the DVR", response.Body, 200)
	if methods := r.Upstream.Methods(); len(methods) != 1 || methods[0] != http.MethodGet {
		t.Fatalf("the provider saw %v, want one GET and no probe", methods)
	}
	// And a forged marker does not: the token is checked, not the header's
	// presence.
	forged := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-forged", http.Header{control.HeaderInternal: []string{"not-the-token"}})
	defer func() { _ = forged.Body.Close() }()
	if forged.StatusCode != http.StatusFound {
		t.Fatalf("a forged internal marker answered %d, want the 302 an ordinary client gets", forged.StatusCode)
	}
}

// A non-HTTP provider URL is not probed (url_utils.py:154-157) and, because
// HttpResponseRedirect refuses the scheme, is answered with a hand-built 301
// (views.py:533-538).
func TestANonHTTPRedirectTargetIsNotProbedAndAnswers301(t *testing.T) {
	r := redirectRig(t, relaytest.ControlPlaneConfig{SourceURL: "rtsp://provider.invalid:554/live/1"}, relaytest.Config{})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-rtsp", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusMovedPermanently {
		t.Fatalf("answered %d, want 301", response.StatusCode)
	}
	if got := response.Header.Get("Location"); got != "rtsp://provider.invalid:554/live/1" {
		t.Fatalf("Location = %q", got)
	}
	if n := r.Upstream.Requests(); n != 0 {
		t.Fatalf("the rig's upstream saw %d requests: an rtsp URL was probed over HTTP", n)
	}
}
