package control

import (
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// A channel UUID: the identifier is a secret (CLAUDE.md § Auth) and travels
// in the next-source path, so no span may carry it.
const traceUUID = "6f1c2a9e-0b7d-4e55-9a31-2c8d4f0e7b16"

// traceparentOf returns the request's traceparent split into its trace and
// span ids.
func traceparentOf(t *testing.T, h http.Header) (traceID, spanID string) {
	t.Helper()
	parts := strings.Split(h.Get("Traceparent"), "-")
	if len(parts) != 4 {
		t.Fatalf("traceparent = %q, want a W3C traceparent", h.Get("Traceparent"))
	}
	return parts[1], parts[2]
}

// noUUIDOnAnySpan fails if the channel UUID reached a span's name, status
// description or any attribute.
func noUUIDOnAnySpan(t *testing.T, rec *telemetrytest.Recorder) {
	t.Helper()
	for _, s := range rec.Spans() {
		if strings.Contains(s.Name, traceUUID) || strings.Contains(s.Description, traceUUID) {
			t.Errorf("span %q carries the channel UUID in its name or description %q", s.Name, s.Description)
		}
		for k, v := range s.Attrs {
			if strings.Contains(fmt.Sprint(v), traceUUID) {
				t.Errorf("span %q attribute %s carries the channel UUID: %v", s.Name, k, v)
			}
		}
	}
}

// relay.next_source is owned by NextSource (D11): it is the ctx span's child,
// the control plane receives a traceparent naming it, and the bound token
// still verifies with that header present, because the HMAC binds method,
// path, timestamp and body and never a header.
func TestNextSourceOwnsItsSpanAndSendsItsTraceparent(t *testing.T) {
	rec := telemetrytest.Install(t)
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
	client := testClient(t, cp)
	now := time.Unix(1789000000, 0)
	client.Now = func() time.Time { return now }

	if _, err := client.NextSource(t.Context(), traceUUID, NextSourceRequest{Reason: "initial"}); err != nil {
		t.Fatalf("NextSource: %v", err)
	}
	span, ok := rec.Span("relay.next_source")
	if !ok || !span.Ended {
		t.Fatalf("relay.next_source = %+v, %v; want an ended span", span, ok)
	}
	for k, want := range map[string]any{
		"mino.next_source.reason":   "tune",
		"mino.outcome":              "source",
		"http.response.status_code": int64(200),
	} {
		if got := span.Attrs[k]; got != want {
			t.Errorf("%s = %#v, want %#v", k, got, want)
		}
	}

	seen := cp.Requests()
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d requests, want 1", len(seen))
	}
	traceID, spanID := traceparentOf(t, seen[0].Header)
	if traceID != span.TraceID || spanID != span.SpanID {
		t.Errorf("traceparent names %s/%s, want relay.next_source's %s/%s", traceID, spanID, span.TraceID, span.SpanID)
	}
	if !VerifyInternalRequest(testSecret, seen[0].Header.Get(HeaderInternalRequest),
		http.MethodPost, seen[0].Path, seen[0].Body, now) {
		t.Error("the bound token does not verify with the traceparent present")
	}
	noUUIDOnAnySpan(t, rec)
}

// Each disposition of the answer is its own outcome, and an error's text
// (which names the path, and so the UUID) never reaches the span.
func TestNextSourceOutcomes(t *testing.T) {
	for _, tc := range []struct {
		status  int
		outcome string
	}{
		{http.StatusNotFound, "no_source"},
		{http.StatusForbidden, "refused"},
		{http.StatusFound, "unavailable"},
	} {
		t.Run(tc.outcome, func(t *testing.T) {
			rec := telemetrytest.Install(t)
			cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: tc.status})
			_, _ = testClient(t, cp).NextSource(t.Context(), traceUUID, NextSourceRequest{Reason: "failover"})
			span, ok := rec.Span("relay.next_source")
			if !ok {
				t.Fatal("no relay.next_source span")
			}
			if got := span.Attrs["mino.outcome"]; got != tc.outcome {
				t.Errorf("outcome = %v, want %s", got, tc.outcome)
			}
			if got := span.Attrs["mino.next_source.reason"]; got != "failover" {
				t.Errorf("reason = %v, want failover", got)
			}
			if got := span.Attrs["http.response.status_code"]; got != int64(tc.status) {
				t.Errorf("status = %v, want %d", got, tc.status)
			}
			noUUIDOnAnySpan(t, rec)
		})
	}
}

// relay.authorize is owned by Authorize: allowed, denied and unavailable, the
// traceparent sent names it, and the bound token still verifies.
func TestAuthorizeOwnsItsSpanAndSendsItsTraceparent(t *testing.T) {
	for _, tc := range []struct {
		name     string
		decision *relaytest.AuthorizeDecision
		outcome  string
		status   int64
	}{
		{"allowed", &relaytest.AuthorizeDecision{Channel: traceUUID}, "allowed", 200},
		{"denied", &relaytest.AuthorizeDecision{Status: http.StatusTooManyRequests, Body: `{"error":"limit"}`}, "denied", 429},
		{"unavailable", &relaytest.AuthorizeDecision{Status: http.StatusInternalServerError}, "unavailable", 500},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := telemetrytest.Install(t)
			cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
			cp.SetAuthorize(tc.decision)
			client := testClient(t, cp)
			now := time.Unix(1789000000, 0)
			client.Now = func() time.Time { return now }

			_, _ = client.Authorize(t.Context(), AuthorizeRequest{URI: "/proxy/ts/stream/" + traceUUID, ClientIP: "192.0.2.1"})
			span, ok := rec.Span("relay.authorize")
			if !ok || !span.Ended {
				t.Fatalf("relay.authorize = %+v, %v; want an ended span", span, ok)
			}
			if got := span.Attrs["mino.outcome"]; got != tc.outcome {
				t.Errorf("outcome = %v, want %s", got, tc.outcome)
			}
			if got := span.Attrs["http.response.status_code"]; got != tc.status {
				t.Errorf("status = %v, want %d", got, tc.status)
			}
			seen := cp.RequestsTo(AuthorizePath)
			if len(seen) != 1 {
				t.Fatalf("the control plane saw %d authorize requests, want 1", len(seen))
			}
			traceID, spanID := traceparentOf(t, seen[0].Header)
			if traceID != span.TraceID || spanID != span.SpanID {
				t.Errorf("traceparent names %s/%s, want relay.authorize's %s/%s", traceID, spanID, span.TraceID, span.SpanID)
			}
			if !VerifyInternalRequest(testSecret, seen[0].Header.Get(HeaderInternalRequest),
				http.MethodPost, AuthorizePath, seen[0].Body, now) {
				t.Error("the bound token does not verify with the traceparent present")
			}
			noUUIDOnAnySpan(t, rec)
		})
	}
}
