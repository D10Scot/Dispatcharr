package channel

import (
	"bytes"
	"context"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// A sink that records what the source gave it, safely under -race.
type recordingSink struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (s *recordingSink) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buf.Write(p)
}

func (s *recordingSink) Bytes() []byte {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]byte(nil), s.buf.Bytes()...)
}

func TestProxySourceCopiesTheUpstreamVerbatim(t *testing.T) {
	payload := relaytest.SyntheticTS(64, 0x100)
	up := relaytest.NewUpstream(relaytest.Config{
		Payload:        payload,
		StopAfterBytes: len(payload),
	})
	t.Cleanup(up.Close)

	sink := &recordingSink{}
	if err := (ProxySource{URL: up.URL()}).Run(t.Context(), sink); err != nil {
		t.Fatalf("Run: %v", err)
	}

	got := sink.Bytes()
	if !bytes.Equal(got, payload) {
		t.Fatalf("the source delivered %d bytes, want the upstream's %d, byte for byte",
			len(got), len(payload))
	}
}

// The provider's own view of the User-Agent. Asserted at the upstream rather
// than by the request succeeding: a test that only checked Run returned nil
// would pass with the header never set, which is the whole thing a provider
// that rejects an unknown agent cares about.
//
// A value the default could not produce (hollow shape 2): Go's own default is
// "Go-http-client/1.1", so asserting that string would pass with the
// assignment deleted.
func TestProxySourceSendsTheUserAgent(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{StopAfterBytes: 188})
	t.Cleanup(up.Close)

	const agent = "VLC/3.0.20 LibVLC/3.0.20"
	if err := (ProxySource{URL: up.URL(), UserAgent: agent}).Run(t.Context(), &recordingSink{}); err != nil {
		t.Fatalf("Run: %v", err)
	}

	seen := up.Headers()
	if len(seen) != 1 {
		t.Fatalf("the provider answered %d requests, want 1", len(seen))
	}
	if got := seen[0].Get("User-Agent"); got != agent {
		t.Fatalf("the provider saw User-Agent %q, want %q", got, agent)
	}
}

// The other direction: no UserAgent means the header is left to the transport,
// not set to an empty string, which some providers treat differently from
// absent.
func TestProxySourceLeavesTheUserAgentAloneWhenUnset(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{StopAfterBytes: 188})
	t.Cleanup(up.Close)

	if err := (ProxySource{URL: up.URL()}).Run(t.Context(), &recordingSink{}); err != nil {
		t.Fatalf("Run: %v", err)
	}
	seen := up.Headers()
	if len(seen) != 1 {
		t.Fatalf("the provider answered %d requests, want 1", len(seen))
	}
	if got := seen[0].Get("User-Agent"); got == "" {
		t.Fatal("the provider saw an empty User-Agent; with none configured the " +
			"transport's own default should stand")
	}
}

func TestProxySourceReportsANon200(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{Status: 403})
	t.Cleanup(up.Close)

	err := (ProxySource{URL: up.URL()}).Run(t.Context(), &recordingSink{})
	var status *ErrUpstreamStatus
	if !errors.As(err, &status) {
		t.Fatalf("error = %v, want an *ErrUpstreamStatus", err)
	}
	if status.Status != 403 {
		t.Fatalf("ErrUpstreamStatus.Status = %d, want 403", status.Status)
	}
}

func TestProxySourceEndsOnAnIdleUpstream(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{DeadAir: 30 * time.Second})
	t.Cleanup(up.Close)

	start := time.Now()
	err := (ProxySource{URL: up.URL(), ReadTimeout: 200 * time.Millisecond}).Run(t.Context(), &recordingSink{})
	if !errors.Is(err, ErrUpstreamIdle) {
		t.Fatalf("error = %v, want ErrUpstreamIdle", err)
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("the idle watchdog took %s to fire on a 200ms timeout", elapsed)
	}
}

// A client going away must be reported as a cancellation, NOT as an idle
// upstream: 2c-5 turns the idle signal into a failover, and failing a healthy
// stream over because a viewer closed a tab is the wrong diagnosis.
func TestProxySourceAttributesACancellationToTheCaller(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{DeadAir: 30 * time.Second})
	t.Cleanup(up.Close)

	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan error, 1)
	go func() {
		done <- ProxySource{URL: up.URL(), ReadTimeout: 30 * time.Second}.Run(ctx, &recordingSink{})
	}()
	time.Sleep(100 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want context.Canceled", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run ignored its context")
	}
}

// A provider URL is never in an error message: it carries provider
// credentials (CLAUDE.md's credential-logging rule, enforced on the Python
// side by scripts/check_credential_logging.py, which has no Go equivalent).
//
// THE CREDENTIAL IS IN THE QUERY STRING AND THE PATH, not in the userinfo, and
// that is what makes this test able to fail. net/http redacts userinfo by
// itself -- it prints http://user:***@host -- so a test that only checked a
// password in the userinfo would pass against a %w-wrapped *url.Error and
// prove nothing. The path and the query are NOT redacted, and a Dispatcharr
// provider URL puts the credential in exactly those two places.
func TestAConnectFailureNeverEchoesTheProviderURL(t *testing.T) {
	const secretURL = "http://127.0.0.1:1/live/subscriber/hunter2/9.ts?token=s3cr3t"
	err := ProxySource{URL: secretURL, ConnectTimeout: 200 * time.Millisecond}.
		Run(t.Context(), &recordingSink{})
	if err == nil {
		t.Fatal("connecting to a closed port succeeded")
	}
	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber"} {
		if strings.Contains(err.Error(), secret) {
			t.Fatalf("the error echoes %q from the provider URL: %s", secret, err)
		}
	}
	// Still useful: the transport's own reason survives the strip.
	if !strings.Contains(err.Error(), "connection refused") {
		t.Fatalf("the error lost the transport's reason: %s", err)
	}
}

// A malformed URL never echoes the provider's credential either -- found by
// review, not by this plan. http.NewRequestWithContext returns net/url's own
// parse error UNWRAPPED on a bad URL, and that error IS already a *url.Error
// whose Error() prints the whole string verbatim: "parse \"<url>\": <reason>".
// A control byte (\x7f) is what makes net/url actually refuse to parse --
// the credential is again in the path and the query, not the userinfo, which
// is the one substring net/http's own formatting would otherwise redact on
// its own. This is the ONE source of the string in this test: withoutURL is
// the only thing that can remove it, so a pass here is not an accident of
// some other redaction.
func TestAMalformedSourceURLNeverEchoesTheProviderCredential(t *testing.T) {
	const secretURL = "http://provider.example/live/subscriber/hunter2/9.ts?token=s3cr3t\x7f"
	err := ProxySource{URL: secretURL}.Run(t.Context(), &recordingSink{})
	if err == nil {
		t.Fatal("a URL with a raw control character parsed successfully")
	}
	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber", secretURL} {
		if strings.Contains(err.Error(), secret) {
			t.Fatalf("the error echoes %q from the malformed source URL: %s", secret, err)
		}
	}
	// Still useful: the reason net/url actually gave survives the strip.
	if !strings.Contains(err.Error(), "invalid control character") {
		t.Fatalf("the error lost net/url's own reason: %s", err)
	}
}

// Run builds a fresh *http.Transport every call, and that transport carries
// no IdleConnTimeout -- its zero value is "no limit", not "the default" --
// so a connection left idle by a clean upstream EOF (the body drains, the
// socket is reusable, keep-alive applies) is never expired on its own. Every
// tune building a new, never-reused Transport turns that into a leak: one
// goroutine and one open socket to the provider per completed tune, forever,
// unless Run tells its client to close what it pooled before returning.
//
// Observed at the SERVER, not the client: a client-side assertion can only
// ask its own Transport what it thinks happened, which is exactly the
// component under test and therefore not independent evidence. Server-side
// http.ConnState is the provider's own view of the socket, unaffected by
// anything this package gets right or wrong about its own bookkeeping.
func TestRunClosesIdleConnectionsWhenItReturns(t *testing.T) {
	var mu sync.Mutex
	last := map[net.Conn]http.ConnState{}

	// NewUnstartedServer, not NewServer: NewServer starts serving
	// immediately, on a goroutine that reads Config.ConnState from its very
	// first accepted connection onward. Setting the field afterwards races
	// that read -- confirmed under -race, "Read at ... net/http.(*conn)
	// .setState()" against "Previous write at ... ConnState = func(...)" on
	// this test's own assignment line. The field must be set before Start.
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "video/mp2t")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(relaytest.SyntheticTS(4, 0x100))
		// Handler returns here: a clean EOF the client can pool as idle.
	}))
	srv.Config.ConnState = func(c net.Conn, state http.ConnState) {
		mu.Lock()
		last[c] = state
		mu.Unlock()
	}
	srv.Start()
	defer srv.Close()

	if err := (ProxySource{URL: srv.URL + "/live.ts"}).Run(t.Context(), &recordingSink{}); err != nil {
		t.Fatalf("Run: %v", err)
	}

	// The transport returns a drained connection to its idle pool on a
	// background goroutine, not synchronously with the handler returning --
	// bounded polling rather than a fixed sleep, both directions.
	deadline := time.Now().Add(2 * time.Second)
	for {
		mu.Lock()
		idle := 0
		for _, s := range last {
			if s == http.StateIdle {
				idle++
			}
		}
		mu.Unlock()
		if idle == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the server still sees %d idle connection(s) two seconds after Run returned -- "+
				"the client's transport was never told to close what it pooled", idle)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// Global Constraint 8's ratchet, found missing by review: ChunkSize,
// ConnectTimeout and ReadTimeout's zero-value defaults were never exercised,
// because every other test in this file supplies an explicit value.
// Constructed with the ZERO VALUE here, not a passed-in one, so this test
// fails if a default silently changes rather than passing regardless.
//
// apps/proxy/live_proxy/input/http_streamer.py:18's chunk_size=8192 default
// parameter and :71's timeout=(5, 30) are what these three mirror, verified
// against this tree.
func TestProxySourceDefaultsMatchPython(t *testing.T) {
	var s ProxySource
	if got := s.chunkSize(); got != 8192 {
		t.Errorf("chunkSize() = %d, want 8192 (apps/proxy/live_proxy/input/http_streamer.py:18)", got)
	}
	if got := s.connectTimeout(); got != 5*time.Second {
		t.Errorf("connectTimeout() = %s, want 5s (apps/proxy/live_proxy/input/http_streamer.py:71)", got)
	}
	if got := s.readTimeout(); got != 30*time.Second {
		t.Errorf("readTimeout() = %s, want 30s (apps/proxy/live_proxy/input/http_streamer.py:71)", got)
	}
}
