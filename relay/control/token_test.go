package control

import (
	"testing"
	"time"
)

// Every expected value below was produced by Django, by running
// apps/proxy/internal_auth.py under SECRET_KEY="phase2c1-test-secret"
// (Task 4 Step 1's generator). They are literals on purpose: a test that
// re-derives its expectation by calling the code under test passes with the
// context string, the separator, the digest algorithm and the body hash all
// wrong, and each of those 403s every internal call in production.
const pySecret = "phase2c1-test-secret"

func TestRelayTrustTokenMatchesPython(t *testing.T) {
	const want = "2bb01b0c4f053b1787d3356fb836282b162002848523b130103c33f9cf7d901c"
	if got := RelayTrustToken(pySecret); got != want {
		t.Fatalf("relay-trust token = %s, want %s", got, want)
	}
}

func TestInternalPrincipalTokenMatchesPython(t *testing.T) {
	const want = "19d4b08667108eb1a38fa11d1bbe7646cb90bc017aad605b302add137818ae7a"
	if got := InternalPrincipalToken(pySecret); got != want {
		t.Fatalf("internal-principal token = %s, want %s", got, want)
	}
}

// The two contexts must produce different digests. Without this, both
// functions could share one context string and every test above still pass
// individually -- and a marker leaked through a config file nginx reads
// would be replayable as an internal principal, which is the exact reason
// internal_auth.py separates them.
func TestTheTwoStaticContextsDiffer(t *testing.T) {
	if RelayTrustToken(pySecret) == InternalPrincipalToken(pySecret) {
		t.Fatal("relay-trust and internal-principal produced the same digest")
	}
}

func TestInternalRequestHeaderWithBodyMatchesPython(t *testing.T) {
	const want = "v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae"
	got := InternalRequestHeader(pySecret, "POST",
		"/api/relay/channels/abc/next-source", []byte(`{"reason":"init"}`), 1789000000)
	if got != want {
		t.Fatalf("header = %s, want %s", got, want)
	}
}

// The query string is inside what the token binds. A Go client built against
// the bare path produces a different digest here and 403s every
// ?clients=all call -- which is every call apps/proxy/utils.py's
// _live_connections makes on every XC handshake.
func TestInternalRequestTokenBindsTheQueryString(t *testing.T) {
	const want = "16c32b6499ba30786464bfb130d785fbc3a8b817c7cc5a0e0d73316a60fd702c"
	got := InternalRequestToken(pySecret, "GET",
		"/proxy/relay/channels?clients=all", nil, 1789000000)
	if got != want {
		t.Fatalf("token = %s, want %s", got, want)
	}

	bare := InternalRequestToken(pySecret, "GET", "/proxy/relay/channels", nil, 1789000000)
	if bare == got {
		t.Fatal("the query string did not change the digest; it is not being bound")
	}
}

// An empty body hashes as sha256 of zero bytes, not as an omitted field.
func TestInternalRequestTokenWithEmptyBodyMatchesPython(t *testing.T) {
	const want = "6d24abde774fa01f0c94981f04c77f0b714398dffc379a09c580ac5e00c816d1"
	got := InternalRequestToken(pySecret, "POST", "/api/relay/events", nil, 1789000000)
	if got != want {
		t.Fatalf("token = %s, want %s", got, want)
	}
	if InternalRequestToken(pySecret, "POST", "/api/relay/events", []byte{}, 1789000000) != want {
		t.Fatal("nil and empty-slice bodies produced different digests")
	}
}

func TestVerifyAcceptsWhatWeProduce(t *testing.T) {
	now := time.Unix(1789000000, 0)
	header := InternalRequestHeader(pySecret, "POST", "/api/relay/events", []byte("{}"), now.Unix())
	if !VerifyInternalRequest(pySecret, header, "POST", "/api/relay/events", []byte("{}"), now) {
		t.Fatal("a header this package produced did not verify")
	}
}

// The window is symmetric: internal_auth.py checks abs(now - ts) > 120, so a
// token 60s in the FUTURE is valid. A one-sided check would reject a peer
// whose clock runs slightly fast, intermittently and unreproducibly.
func TestVerifyWindowIsSymmetric(t *testing.T) {
	issued := int64(1789000000)
	header := InternalRequestHeader(pySecret, "GET", "/proxy/relay/channels", nil, issued)

	for _, tc := range []struct {
		name   string
		now    int64
		accept bool
	}{
		{"60s in the past", issued + 60, true},
		{"60s in the future", issued - 60, true},
		{"exactly 120s old", issued + 120, true},
		{"121s old", issued + 121, false},
		{"121s in the future", issued - 121, false},
	} {
		got := VerifyInternalRequest(pySecret, header, "GET", "/proxy/relay/channels", nil, time.Unix(tc.now, 0))
		if got != tc.accept {
			t.Errorf("%s: verify = %v, want %v", tc.name, got, tc.accept)
		}
	}
}

func TestVerifyRejectsMalformedHeaders(t *testing.T) {
	now := time.Unix(1789000000, 0)
	valid := InternalRequestHeader(pySecret, "GET", "/x", nil, now.Unix())

	for _, tc := range []struct{ name, header string }{
		{"empty", ""},
		{"two parts", "v1.1789000000"},
		{"four parts", valid + ".extra"},
		{"wrong version", "v2" + valid[2:]},
		{"non-numeric timestamp", "v1.abc.deadbeef"},
	} {
		if VerifyInternalRequest(pySecret, tc.header, "GET", "/x", nil, now) {
			t.Errorf("%s: %q verified and must not have", tc.name, tc.header)
		}
	}
}

func TestVerifyRejectsAnotherDeploymentsSecret(t *testing.T) {
	now := time.Unix(1789000000, 0)
	header := InternalRequestHeader("some-other-deployment", "GET", "/x", nil, now.Unix())
	if VerifyInternalRequest(pySecret, header, "GET", "/x", nil, now) {
		t.Fatal("a token signed with a different SECRET_KEY verified")
	}
}
