package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// failoverRig is a rig whose control plane knows a second stream, served by
// a second upstream: the shape every failover test needs. The primary is the
// rig's own upstream, configured by `primary`; the alternate loops the same
// asset unpaced.
func failoverRig(t *testing.T, primary relaytest.Config, overrides map[string]any) (*rig, *relaytest.Upstream) {
	t.Helper()
	alternate := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100)})
	t.Cleanup(alternate.Close)
	cp := relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}
	return fanRigWith(t, cp, primary, overrides), alternate
}

func listedStreamID(t *testing.T, r *rig) int {
	t.Helper()
	ch := listedChannel(t, r)
	id, _ := ch["stream_id"].(float64)
	return int(id)
}

// readAligned reads n packets and checks only their alignment: across a
// switch the two upstreams' packet indices do not continue one another, so
// packetRun's contiguity check does not apply here.
func readAligned(t *testing.T, body io.Reader, packets int) []byte {
	t.Helper()
	got := make([]byte, packets*buffer.TSPacketSize)
	if _, err := io.ReadFull(body, got); err != nil {
		t.Fatalf("reading %d packets: %v", packets, err)
	}
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the client received bytes that are not whole TS packets: %s", problem)
	}
	return got
}

// The e2e dead-air spec's claim, end to end at the relay: the client
// survives the failover -- still attached, still fed -- and the list shows
// the alternate. CONNECTION_TIMEOUT and HEALTH_CHECK_INTERVAL come off the
// wire compressed; the switch itself is row 2's, pinned in package channel.
func TestAFailoverKeepsTheClientAttachedAndFed(t *testing.T) {
	r, alternate := failoverRig(t,
		relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3},
		map[string]any{"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05})
	response := r.tuneAs(t, "c-failover", "client-a")
	defer func() { _ = response.Body.Close() }()

	before := packetRun(t, "the client before the dead air", response.Body, 1000)
	_ = before
	if got := listedStreamID(t, r); got != 1 {
		t.Fatalf("stream_id = %d before the failover, want 1", got)
	}

	// The rest of the primary's bytes, then the alternate's: the read spans
	// the switch, and every packet is still whole.
	readAligned(t, response.Body, 3000)
	waitFor(t, "the list to show the alternate", 10*time.Second, func() bool { return listedStreamID(t, r) == 2 })
	if n := alternate.Requests(); n != 1 {
		t.Fatalf("the alternate saw %d requests, want 1", n)
	}
	ch := listedChannel(t, r)
	if ch["client_count"] != 1.0 {
		t.Fatalf("client_count = %v after the failover, want 1: the client was dropped", ch["client_count"])
	}
	if ch["healthy"] != true {
		t.Fatalf("healthy = %v after the failover, want true: data is flowing again", ch["healthy"])
	}
	switches := r.Control.EventsOfType("stream_switch")
	waitFor(t, "the stream_switch event to reach the control plane", 5*time.Second, func() bool {
		switches = r.Control.EventsOfType("stream_switch")
		return len(switches) == 1
	})
	if switches[0].ChannelID != "c-failover" || switches[0].StreamID == nil || *switches[0].StreamID != 2 {
		t.Fatalf("stream_switch = %+v, want channel c-failover and stream 2", switches[0])
	}
}

// waitFor polls cond every 20 ms until it holds or the deadline passes.
func waitFor(t *testing.T, what string, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out after %s waiting for %s", timeout, what)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// THE DEGRADED FALLBACK (input/manager.py:2107-2112, CLAUDE.md § Operationally):
// with the control plane answering 503, a failover falls back to the
// candidate list the initial answer carried -- unenforced -- after spending
// the client's own retry: two next-source attempts, then the cached
// alternate. And once the control plane answers again, the next failover
// goes through it and raises channel_error with reason degraded_failover,
// once (:2183-2192).
//
// The primary and the first alternate each end after two chunks, so each
// is exhausted after three quick EOFs; the third candidate flows.
func TestAFailoverFallsBackToTheCachedCandidatesWhenTheControlPlaneIsDown(t *testing.T) {
	second := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), StopAfterBytes: rigChunkBytes * 2})
	t.Cleanup(second.Close)
	third := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100)})
	t.Cleanup(third.Close)
	cp := relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{
		{StreamID: 2, URL: second.URL()},
		{StreamID: 3, URL: third.URL()},
	}}
	r := fanRigWith(t, cp, relaytest.Config{StopAfterBytes: rigChunkBytes * 2}, nil)

	response := r.tuneAs(t, "c-degraded", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-degraded", 1)

	// The outage begins after the tune.
	r.Control.SetStatus(http.StatusServiceUnavailable)

	waitFor(t, "the switch to the cached second stream", 15*time.Second, func() bool { return second.Requests() >= 1 })
	calls := r.Control.RequestsTo("/next-source")
	if len(calls) != 3 {
		t.Fatalf("the control plane saw %d next-source calls, want 3: the tune and the failover's two attempts before the cache was used", len(calls))
	}
	if !strings.Contains(string(calls[1].Body), `"reason":"failover"`) || !strings.Contains(string(calls[1].Body), `"exclude_stream_ids":[1]`) {
		t.Fatalf("the failover call was %s, want reason failover excluding stream 1", calls[1].Body)
	}
	if got := listedStreamID(t, r); got != 2 {
		t.Fatalf("stream_id = %d, want the cached alternate 2", got)
	}

	// Django is back; the second stream exhausts too; the third comes from
	// the control plane, with the cached list now excluded correctly.
	r.Control.SetStatus(0)
	waitFor(t, "the switch to the third stream", 15*time.Second, func() bool { return third.Requests() >= 1 })
	calls = r.Control.RequestsTo("/next-source")
	last := calls[len(calls)-1]
	if !strings.Contains(string(last.Body), `"exclude_stream_ids":[1,2]`) {
		t.Fatalf("the second failover excluded %s, want [1,2]", last.Body)
	}
	waitFor(t, "the degraded_failover event", 5*time.Second, func() bool {
		for _, e := range r.Control.EventsOfType("channel_error") {
			if e.Details["reason"] == "degraded_failover" {
				return true
			}
		}
		return false
	})
	degraded := 0
	for _, e := range r.Control.EventsOfType("channel_error") {
		if e.Details["reason"] == "degraded_failover" {
			degraded++
		}
	}
	if degraded != 1 {
		t.Fatalf("degraded_failover raised %d times, want exactly once on recovery", degraded)
	}
	readAligned(t, response.Body, 200)
}

// A REFUSAL NEVER DEGRADES (spec § Error handling per hop; input/manager.py:
// 2095-2106): a 403 -- a SECRET_KEY mismatch between roles -- fails the
// switch loudly, the cached alternate is never touched, and the channel ends
// in error rather than streaming a candidate nobody reserved.
func TestARefusedFailoverNeverUsesTheCache(t *testing.T) {
	r, alternate := failoverRig(t, relaytest.Config{StopAfterBytes: rigChunkBytes * 2}, nil)
	response := r.tuneAs(t, "c-refused", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-refused", 1)
	ch := r.Manager.Get("c-refused")

	r.Control.SetStatus(http.StatusForbidden)
	select {
	case <-ch.Done():
	case <-time.After(15 * time.Second):
		t.Fatal("the channel did not end after a refused failover")
	}
	// The channel ended in error -- run()'s own exhaustion error, as Python's
	// finally block writes it; the refusal itself is logged at the switch
	// (input/manager.py:2101-2105) and is not what the channel records -- and
	// the client's release then moved it to stopping.
	var exhausted *channel.ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) {
		t.Fatalf("Err() = %v (state %q), want the exhaustion error", ch.Err(), ch.State())
	}
	if n := alternate.Requests(); n != 0 {
		t.Fatalf("the alternate saw %d requests: a refusal degraded onto the cache", n)
	}
	calls := r.Control.RequestsTo("/next-source")
	if len(calls) != 2 {
		t.Fatalf("the control plane saw %d next-source calls, want 2: a 403 is not retried", len(calls))
	}
}

// THE TIMING SHAPE of the fallback: "after up to ~14 s per control-plane
// call" (CLAUDE.md § Operationally) is two attempts of (ConnectTimeout,
// ReadTimeout) plus the retry delay, spent before the cache is read. Here the
// client's transport times out at 300 ms and the control plane answers after
// 400 ms, so each attempt is a transport failure; the fake's own request log
// shows the second attempt at least 400 ms after the first (timeout plus the
// 100 ms retry delay), and the alternate is not contacted until after both.
// A client that skipped the retry, or one that read the cache before its
// first attempt failed, reddens this.
func TestTheDegradedFallbackSpendsTheClientsRetryBudgetFirst(t *testing.T) {
	alternate := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100)})
	t.Cleanup(alternate.Close)
	cp := relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}
	cp.Settings = rigSettings(nil)
	slow := control.NewHTTPClient()
	slow.Timeout = 300 * time.Millisecond
	r := newRigWithClient(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), StopAfterBytes: rigChunkBytes * 2}, slow)

	response := r.tuneAs(t, "c-budget", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-budget", 1)
	r.Control.SetDelay(400 * time.Millisecond)

	waitFor(t, "the cached alternate to be contacted", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
	calls := r.Control.RequestsTo("/next-source")
	if len(calls) != 3 {
		t.Fatalf("the control plane saw %d next-source calls, want 3: the tune and two failover attempts", len(calls))
	}
	first, second := calls[1].At, calls[2].At
	if gap := second.Sub(first); gap < 400*time.Millisecond {
		t.Fatalf("the second attempt came %s after the first, under the 300 ms timeout plus the 100 ms retry delay", gap)
	}
	if gap := second.Sub(first); gap > 3*time.Second {
		t.Fatalf("the second attempt came %s after the first: the budget was not the client's", gap)
	}
}

// The provider slot goes back when the channel's source goroutine returns,
// with the ids of the stream it was playing THEN: after a failover, the
// alternate's. Observed at the fake, which records the release body.
func TestTheSlotIsReleasedWithTheCurrentStreamWhenTheChannelEnds(t *testing.T) {
	r, alternate := failoverRig(t, relaytest.Config{StopAfterBytes: rigChunkBytes * 2}, nil)
	response := r.tuneAs(t, "c-release", "client-a")
	waitFor(t, "the switch to the alternate", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
	_ = response.Body.Close()
	waitFor(t, "the release", 10*time.Second, func() bool { return len(r.Control.RequestsTo("/release")) == 1 })
	release := r.Control.RequestsTo("/release")[0]
	var body map[string]any
	if err := json.Unmarshal(release.Body, &body); err != nil {
		t.Fatalf("decoding the release body: %v", err)
	}
	if body["stream_id"] != 2.0 || body["m3u_profile_id"] != 1.0 {
		t.Fatalf("release body = %s, want stream 2 on profile 1", release.Body)
	}
	if _, present := body["channel_pk"]; !present || body["channel_pk"] != nil {
		t.Fatalf("release body = %s, want channel_pk present and null", release.Body)
	}
	if release.Header.Get(control.HeaderInternalRequest) == "" {
		t.Fatal("the release was not signed")
	}
}
