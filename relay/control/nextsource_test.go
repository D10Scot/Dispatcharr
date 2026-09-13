package control

import (
	"errors"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

const testSecret = "phase2c1-test-secret"

func testClient(t *testing.T, cp *relaytest.ControlPlane) *Client {
	t.Helper()
	t.Cleanup(cp.Close)
	return &Client{Secret: testSecret, BaseURL: cp.URL(), HTTP: NewHTTPClient()}
}

func TestNextSourceReadsTheAnswer(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
	answer, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{Reason: "initial"})
	if err != nil {
		t.Fatalf("NextSource: %v", err)
	}
	if answer.Source == nil {
		t.Fatal("the answer carried no source")
	}
	if answer.Source.StreamProfile.Kind != KindProxy {
		t.Fatalf("kind = %q, want %q", answer.Source.StreamProfile.Kind, KindProxy)
	}
	if got, err := answer.ProxySettings.Int("BUFFER_CHUNK_SIZE"); err != nil || got != 255868 {
		t.Fatalf("BUFFER_CHUNK_SIZE = %d, %v; want 255868, nil", got, err)
	}
}

// THE BOUND TOKEN, PINNED AGAINST A PYTHON-PRODUCED LITERAL. A test that
// recomputed the expectation with InternalRequestHeader would prove the
// function deterministic and nothing else: it would pass with the context
// string misspelled, the separator wrong, the body digest omitted, or SHA-512
// in place of SHA-256 -- every one of which 403s in production.
//
// The clock is injected so the timestamp is the one the literal was generated
// at. Regenerate the literal from Django, never from the Go.
func TestNextSourceSignsTheRequestTheWayDjangoVerifiesIt(t *testing.T) {
	const wantHeader = "v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae"
	const wantBody = `{"reason":"init"}`

	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
	client := testClient(t, cp)
	client.Now = func() time.Time { return time.Unix(1789000000, 0) }

	// The body has to be exactly the seventeen bytes the literal was signed
	// over, so this drives post directly rather than NextSource, whose body is
	// a marshalled request struct.
	if _, _, err := client.post(t.Context(), "/api/relay/channels/abc/next-source", []byte(wantBody)); err != nil {
		t.Fatalf("post: %v", err)
	}

	seen := cp.Requests()
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d requests, want 1", len(seen))
	}
	if got := seen[0].Header.Get(HeaderInternalRequest); got != wantHeader {
		t.Fatalf("%s = %s\nwant %s\n(the literal comes from apps/proxy/internal_auth.py's own "+
			"internal_request_token under SECRET_KEY=%q)", HeaderInternalRequest, got, wantHeader, testSecret)
	}
	if got := seen[0].Header.Get(HeaderInternal); got != InternalPrincipalToken(testSecret) {
		t.Fatalf("%s was not the internal-principal token", HeaderInternal)
	}
}

// A 404 is an ANSWER, not an error: the channel was deleted mid playback.
func TestNextSourceMapsA404ToANullSource(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusNotFound})
	answer, err := testClient(t, cp).NextSource(t.Context(), "gone", NextSourceRequest{})
	if err != nil {
		t.Fatalf("a 404 became an error: %v", err)
	}
	if answer.Source != nil {
		t.Fatal("a 404 answer carried a source")
	}
	if answer.Error != "identifier not found" {
		t.Fatalf("error = %q, want %q", answer.Error, "identifier not found")
	}
}

// Every other 4xx is Refused, and Refused is deliberately NOT an Unavailable:
// a 403 from a SECRET_KEY mismatch between the api and relay roles must fail
// the tune loudly rather than make every failover degrade silently forever.
func TestA403IsRefusedAndIsNotUnavailable(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusForbidden})
	_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})

	var refused *Refused
	if !errors.As(err, &refused) {
		t.Fatalf("error = %v, want a *Refused", err)
	}
	if refused.Status != http.StatusForbidden {
		t.Fatalf("Refused.Status = %d, want 403", refused.Status)
	}
	var unavailable *Unavailable
	if errors.As(err, &unavailable) {
		t.Fatal("a 403 satisfied errors.As(*Unavailable): the degraded fallback would swallow it")
	}
	if n := len(cp.Requests()); n != 1 {
		t.Fatalf("the control plane saw %d requests, want 1 -- a 4xx is not retried", n)
	}
}

// The retry budget, in both directions. Two tests would each pass with the
// loop hard-wired the wrong way, so both halves are asserted: a 5xx is
// retried and recovers, and a 3xx is not.
func TestOnlyA5xxConsumesTheRetry(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
		SourceURL: "http://provider.invalid/a.ts",
		FailFirst: 1,
	})
	answer, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})
	if err != nil {
		t.Fatalf("a single 503 was not retried: %v", err)
	}
	if answer.Source == nil {
		t.Fatal("the retried call produced no source")
	}
	if n := len(cp.Requests()); n != 2 {
		t.Fatalf("the control plane saw %d requests, want 2", n)
	}
}

func TestA5xxOnBothAttemptsIsUnavailable(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusBadGateway})
	_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})
	var unavailable *Unavailable
	if !errors.As(err, &unavailable) {
		t.Fatalf("error = %v, want an *Unavailable", err)
	}
	if n := len(cp.Requests()); n != 2 {
		t.Fatalf("the control plane saw %d requests, want 2 (the first try plus one retry)", n)
	}
}

// A redirect is never followed: following one re-sends the signed internal
// headers to whatever a stray `return 301` names. And it is not retried --
// a client built to this spec's uncorrected first draft would burn a second
// full (2s, 5s) budget, up to seven extra seconds of dead air, on a
// misconfigured deployment.
func TestARedirectIsNeitherFollowedNorRetried(t *testing.T) {
	elsewhere := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
	t.Cleanup(elsewhere.Close)
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{RedirectTo: elsewhere.URL() + "/api/relay/x"})

	_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})

	// THE LEAK CHECK COMES FIRST, and the order is load-bearing rather than
	// stylistic. Dropping CheckRedirect makes the client follow to a target
	// that answers a perfectly good 200, so NextSource returns NO error and an
	// error-type assertion placed first kills the test before the leak is ever
	// examined -- the break-check for the security property would then redden
	// on the wrong line with the wrong message. Asserting the target's request
	// count first also matches which property matters more: a followed
	// redirect re-sends the signed internal headers to whatever a stray
	// `return 301` names.
	if n := len(elsewhere.Requests()); n != 0 {
		t.Fatalf("the redirect target saw %d requests: the signed internal headers "+
			"were forwarded off this deployment", n)
	}
	var unavailable *Unavailable
	if !errors.As(err, &unavailable) {
		t.Fatalf("error = %v, want an *Unavailable", err)
	}
	if n := len(cp.Requests()); n != 1 {
		t.Fatalf("the control plane saw %d requests, want 1 -- a 3xx raises on the first pass", n)
	}
}

func TestA2xxThatIsNotAJSONObjectIsUnavailableAndNotRetried(t *testing.T) {
	for _, body := range []string{"<html>nginx</html>", `["a","list"]`, `null`} {
		cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Body: body})
		_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})
		var unavailable *Unavailable
		if !errors.As(err, &unavailable) {
			t.Errorf("body %q: error = %v, want an *Unavailable", body, err)
			continue
		}
		if n := len(cp.Requests()); n != 1 {
			t.Errorf("body %q: the control plane saw %d requests, want 1", body, n)
		}
	}
}

func TestSettingsFailLoudlyOnAnAbsentKey(t *testing.T) {
	s := Settings{"present": []byte("5")}
	if _, err := s.Int("present"); err != nil {
		t.Fatalf("a present key failed: %v", err)
	}
	var absent *ErrSettingAbsent
	if _, err := s.Int("BUFFER_CHUNK_SIZE"); !errors.As(err, &absent) {
		t.Fatalf("error = %v, want an *ErrSettingAbsent", err)
	} else if absent.Key != "BUFFER_CHUNK_SIZE" {
		t.Fatalf("ErrSettingAbsent names %q", absent.Key)
	}
	if !strings.Contains(absent.Error(), "BUFFER_CHUNK_SIZE") {
		t.Fatalf("the message does not name the key: %s", absent.Error())
	}
}

// A FloatField renders 15 as 15.0, so an integer setting has to survive
// arriving as a JSON float. Reading it straight into an int refuses it.
func TestAnIntegerSettingSurvivesArrivingAsAFloat(t *testing.T) {
	s := Settings{"STREAM_TIMEOUT": []byte("20.0")}
	got, err := s.Int("STREAM_TIMEOUT")
	if err != nil {
		t.Fatalf("Int on a JSON float failed: %v", err)
	}
	if got != 20 {
		t.Fatalf("STREAM_TIMEOUT = %d, want 20", got)
	}
}

func TestSecondsHonoursAFractionalValue(t *testing.T) {
	s := Settings{"KEEPALIVE_INTERVAL": []byte("0.5")}
	got, err := s.Seconds("KEEPALIVE_INTERVAL")
	if err != nil {
		t.Fatalf("Seconds: %v", err)
	}
	if got != 500*time.Millisecond {
		t.Fatalf("KEEPALIVE_INTERVAL = %s, want 500ms", got)
	}
}

// Global Constraint 8's ratchet, found missing by review: these three
// literals cited the spec with no file:line and nothing asserted them.
// apps/proxy/control_plane.py:37-41 is Python's own next-source client's
// CONNECT_TIMEOUT/READ_TIMEOUT/RETRY_DELAY, verified against this tree
// rather than copied from the reviewer's citation.
func TestTheTimeoutsMatchPython(t *testing.T) {
	if ConnectTimeout != 2*time.Second {
		t.Errorf("ConnectTimeout = %s, want 2s (apps/proxy/control_plane.py:37)", ConnectTimeout)
	}
	if ReadTimeout != 5*time.Second {
		t.Errorf("ReadTimeout = %s, want 5s (apps/proxy/control_plane.py:38)", ReadTimeout)
	}
	if RetryDelay != 100*time.Millisecond {
		t.Errorf("RetryDelay = %s, want 100ms (apps/proxy/control_plane.py:41)", RetryDelay)
	}
}
