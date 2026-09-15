package httpapi

import (
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// An untrusted tune asks Django to authorize it, and the QUESTION travels in
// the body -- every field of it.
//
// THE HEADER ASSERTIONS ARE THE POINT, not decoration. The bound token signs
// the context, the method, the full path, the timestamp and sha256(body), and
// headers are not among them: a captured X-Dispatcharr-Internal-Request for
// this path would stay valid for 120 seconds against any combination of
// forwarded headers, so identity-bearing material reaching Django as a header
// is the authorization oracle § The contract's M-R3-1 fix exists to close.
func TestAnUntrustedTuneAsksDjangoAndSendsTheQuestionInTheBody(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)

	header := http.Header{}
	header.Set("Authorization", "Bearer a-jwt")
	header.Set("Cookie", "sessionid=abc123")
	header.Set("X-API-Key", "an-api-key")
	response := r.tune(t, "/proxy/ts/stream/c-untrusted?token=t", header)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the untrusted tune answered %d, want 200", response.StatusCode)
	}

	asked := r.Control.AuthorizeRequests()
	if len(asked) != 1 {
		t.Fatalf("the relay made %d authorize calls, want 1", len(asked))
	}
	// THE FULL PATH INCLUDING THE QUERY STRING: ?token=, ?session_id= and
	// ?output_format= are all resolved from it, and Django's own hop reads
	// X-Original-URI with its query attached.
	if asked[0].URI != "/proxy/ts/stream/c-untrusted?token=t" {
		t.Errorf("the relay asked about %q, want the full request URI with its query string", asked[0].URI)
	}
	if asked[0].ClientIP == "" {
		t.Errorf("the relay sent no client_ip: Django would evaluate the STREAMS ACL against " +
			"the RELAY's address (apps/proxy/authorize.py:425)")
	}
	if asked[0].Internal {
		t.Errorf("the relay reported internal=true for an ordinary client tune, which makes " +
			"_resolve_principal return INTERNAL_PRINCIPAL before any check runs")
	}
	for name, got := range map[string]*string{
		"authorization": asked[0].Headers.Authorization,
		"cookie":        asked[0].Headers.Cookie,
		"x-api-key":     asked[0].Headers.APIKey,
	} {
		if got == nil {
			t.Errorf("the relay sent no %q in the body: ApiKeyAuthentication checks X-API-Key "+
				"BEFORE falling back to an Authorization header, so a client authenticating "+
				"that way resolves to anonymous in this shape and to its real user in "+
				"production -- the cross-shape divergence D5 exists to prevent", name)
		}
	}

	// And NONE of the three reached Django as a header on the POST.
	calls := r.Control.RequestsTo(relaytest.AuthorizePath)
	if len(calls) != 1 {
		t.Fatalf("the fake recorded %d authorize requests", len(calls))
	}
	for _, name := range []string{"Authorization", "Cookie", "X-Api-Key"} {
		if got := calls[0].Header.Get(name); got != "" {
			t.Errorf("the authorize POST carried %s as a header (%q): the bound token signs "+
				"no header, so a captured token would be replayable against any value", name, got)
		}
	}
	// The two headers it MUST carry, because IsInternalRelay requires both.
	if calls[0].Header.Get(control.HeaderInternal) == "" || calls[0].Header.Get(control.HeaderInternalRequest) == "" {
		t.Errorf("the authorize POST is missing an internal header: it would 403 against a real Django")
	}
}

// A trusted tune asks NOTHING: the hop already decided, and the relay reads
// its seven values off the request.
//
// The counterpart of the test above, and the pair is what shows the fallback
// is a fallback rather than a second hop on every tune.
func TestATrustedTuneMakesNoAuthorizeCall(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-trusted", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	if got := r.Control.AuthorizeRequests(); len(got) != 0 {
		t.Fatalf("a trusted tune made %d authorize calls, want 0 -- this route exists for the "+
			"shape with no nginx, and calling it per tune in production would double the "+
			"control-plane load the hop already carries", len(got))
	}
}

// internal=true travels only when the CLIENT's own request carries the static
// marker -- the DVR's fetch -- and never because this call has to send one to
// satisfy IsInternalRelay.
//
// BOTH ROWS, because a relay that hard-coded either value would pass a test
// that checked one.
func TestInternalTravelsFromTheClientsMarkerAndNotTheTransports(t *testing.T) {
	for _, tc := range []struct {
		name     string
		marker   string
		internal bool
	}{
		{"an ordinary client", "", false},
		{"the DVR's own fetch", control.InternalPrincipalToken(testSecret), true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{}, nil)
			header := http.Header{}
			if tc.marker != "" {
				header.Set(control.HeaderInternal, tc.marker)
			}
			response := r.tune(t, "/proxy/ts/stream/c-internal", header)
			defer func() { _ = response.Body.Close() }()

			asked := r.Control.AuthorizeRequests()
			if len(asked) != 1 {
				t.Fatalf("the relay made %d authorize calls, want 1", len(asked))
			}
			if asked[0].Internal != tc.internal {
				t.Fatalf("the relay reported internal=%v for %s, want %v", asked[0].Internal, tc.name, tc.internal)
			}
		})
	}
}

// A denial reaches the viewer as ITSELF, with its own status and its own
// body.
//
// FOUR STATUSES, because the whole reason this route answers with
// authorize_error_response rather than subrequest_error_response is that a
// direct POST has no auth_request module to collapse them for: a 404 for an
// unknown channel and a 429 for a user over their stream limit would
// otherwise reach a viewer as 403. A test that checked only 403 would pass
// against the collapsed shape.
func TestADenialReachesTheViewerWithItsOwnStatus(t *testing.T) {
	// BOTH BRANCHES OF writeAuthorizeFailure, because they are two different
	// lines: a denial that carried a JSON body is forwarded verbatim, and one
	// that carried none answers with the status text. Break-check 10 patched
	// the second branch and stayed GREEN until the body-less rows were added
	// -- every row had a body.
	for _, tc := range []struct {
		status   int
		body     string
		bodyless bool
	}{
		{status: http.StatusUnauthorized, body: `{"error":"Invalid credentials"}`},
		{status: http.StatusForbidden, body: `{"error":"Forbidden"}`},
		{status: http.StatusNotFound, body: `{"error":"Not found"}`},
		{status: http.StatusTooManyRequests, body: `{"error":"Stream limit exceeded (3 concurrent streams allowed)"}`},
		{status: http.StatusUnauthorized, bodyless: true},
		{status: http.StatusNotFound, bodyless: true},
		{status: http.StatusTooManyRequests, bodyless: true},
	} {
		r := fanRig(t, relaytest.Config{}, nil)
		r.Control.SetAuthorize(&relaytest.AuthorizeDecision{
			Status: tc.status, Body: tc.body, NonJSONBody: tc.bodyless,
		})
		response := r.tune(t, "/proxy/ts/stream/c-denied", http.Header{})
		body := readAtLeast(response.Body, 1, 5*time.Second)
		_ = response.Body.Close()

		if response.StatusCode != tc.status {
			t.Errorf("a %d denial (bodyless=%v) reached the viewer as %d",
				tc.status, tc.bodyless, response.StatusCode)
		}
		if !tc.bodyless && string(body) != tc.body {
			t.Errorf("a %d denial's body reached the viewer as %q, want %q", tc.status, body, tc.body)
		}
		if tc.bodyless && strings.Contains(string(body), "relaytest") {
			t.Errorf("a %d denial echoed the control plane's own non-JSON body to the viewer: %q",
				tc.status, body)
		}
		// And nothing was tuned.
		if got := len(r.Control.RequestsTo("/next-source")); got != 0 {
			t.Errorf("a %d denial still made %d next-source calls", tc.status, got)
		}
	}
}

// A control plane that cannot answer is a 502, and never a denial.
//
// The distinction matters operationally: a viewer told 403 stops retrying and
// an operator looks for a permissions problem, where the real fault is that
// Django is down. 502 is what the relay says about itself.
func TestAnUnreachableControlPlaneIsA502AndNotADenial(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	r.Control.SetAuthorize(&relaytest.AuthorizeDecision{Status: http.StatusInternalServerError})

	response := r.tune(t, "/proxy/ts/stream/c-broken", http.Header{})
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("a 500 from the control plane reached the viewer as %d, want 502", response.StatusCode)
	}
}

// The decision's values are what the tune uses -- all six of them -- where a
// trusted tune uses the headers.
//
// The channel is the one that can fail loudest: a relay that used the PATH
// would stream a channel Django did not authorize, which is exactly what
// X-Relay-Channel exists to prevent on the trusted path.
func TestTheDecisionsValuesAreUsedRatherThanThePathAndTheSocket(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	r.Control.SetAuthorize(&relaytest.AuthorizeDecision{
		Channel:  "c-from-django",
		Client:   "client-from-django",
		User:     "42",
		ClientIP: "203.0.113.7",
	})

	response := r.tune(t, "/proxy/ts/stream/c-from-the-path", http.Header{})
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the tune answered %d", response.StatusCode)
	}
	packetRun(t, "the client", response.Body, 1)

	if got := r.Control.RequestsTo("/next-source"); len(got) != 1 ||
		!containsString(got[0].Path, "c-from-django") {
		t.Fatalf("the tune asked next-source about %v, want the channel Django resolved", got)
	}
	ch := r.Manager.Get("c-from-django")
	if ch == nil {
		t.Fatalf("the relay is running %v, not the channel Django named", runningIDs(r))
	}
	clients := ch.ClientSnapshot()
	if len(clients) != 1 {
		t.Fatalf("the channel has %d clients", len(clients))
	}
	if clients[0].ID != "client-from-django" {
		t.Errorf("the client id is %q, want the one Django minted -- a relay that minted its "+
			"own would give an admin a handle Django never issued", clients[0].ID)
	}
	if clients[0].UserID != "42" {
		t.Errorf("the client's user_id is %q, want 42", clients[0].UserID)
	}
	if clients[0].IPAddress != "203.0.113.7" {
		t.Errorf("the client's ip_address is %q, want the address Django resolved -- this "+
			"response is the dev shape's ONLY source for it (parity-matrix row 17)", clients[0].IPAddress)
	}
}

func containsString(haystack, needle string) bool {
	return len(haystack) >= len(needle) && (func() bool {
		for i := 0; i+len(needle) <= len(haystack); i++ {
			if haystack[i:i+len(needle)] == needle {
				return true
			}
		}
		return false
	})()
}

// runningIDs names the channels the manager holds, for a failure message: a
// []*channel.Channel prints as pointers and says nothing.
//
// Defined here rather than in xc_test.go (Task 7), where the plan's own
// appendix places it: this file (Task 6) needs it first and Task 7's
// xc_test.go, written afterward in this same tree, does not redefine it.
func runningIDs(r *rig) []string {
	var out []string
	for _, c := range r.Manager.Snapshot() {
		out = append(out, c.ID())
	}
	return out
}
