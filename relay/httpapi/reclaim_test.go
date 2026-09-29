package httpapi

import (
	"io"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/session"
)

// Slot reclaim at the relay's HTTP surface (Phase 4a-1c, spec D16 and § Slot
// reclaim). The fake control plane's slot model is Django's refusal: a full
// profile answers a null source with capacity.blocked, and a release POST
// frees a slot. "Driven clock" is rig.SessionClock.Advance, which ages
// sessions and nothing else; no test here waits out a real idle timeout.

// reclaimRig is hlsRig's shape with a control plane of the test's own.
func reclaimRig(t *testing.T, f *hlsFixture, cp relaytest.ControlPlaneConfig) *rig {
	t.Helper()
	return fanRigWith(t, cp, relaytest.Config{Rate: 4}, nil, f.option())
}

// tuneTS is a TS tune of channelID as clientID over the trusted path; unlike
// tuneAs it returns whatever the relay answered.
func (r *rig) tuneTS(t *testing.T, channelID, clientID string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	return r.tune(t, "/proxy/ts/stream/"+channelID, header)
}

// tuneStatus is a TS tune's status and body, the connection closed: for a
// tune the test expects to be refused.
func (r *rig) tuneStatus(t *testing.T, channelID, clientID string) (int, string) {
	t.Helper()
	resp := r.tuneTS(t, channelID, clientID)
	defer func() { _ = resp.Body.Close() }()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 200))
	return resp.StatusCode, string(body)
}

// wantRefused fails unless the TS tune is refused 503 "no source available".
func (r *rig) wantRefused(t *testing.T, channelID, clientID string) {
	t.Helper()
	status, body := r.tuneStatus(t, channelID, clientID)
	if status != http.StatusServiceUnavailable || !strings.Contains(body, "no source available") {
		t.Fatalf("the blocked tune of %s answered %d %q, want 503 no source available", channelID, status, body)
	}
}

// nextSourceCalls is how many next-source calls the fake has answered for a
// channel.
func (r *rig) nextSourceCalls(id string) int {
	n := 0
	for _, req := range r.Control.RequestsTo("/next-source") {
		if strings.Contains(req.Path, "/channels/"+id+"/") {
			n++
		}
	}
	return n
}

// requestIndex is the position of the first recorded call whose path names
// the channel and ends with suffix, from position start; -1 when none.
func (r *rig) requestIndex(id, suffix string, start int) int {
	for i, req := range r.Control.Requests() {
		if i >= start && strings.Contains(req.Path, "/channels/"+id+"/") && strings.HasSuffix(req.Path, suffix) {
			return i
		}
	}
	return -1
}

func TestABlockedTuneReclaimsASilentHLSChannel(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := reclaimRig(t, f, relaytest.ControlPlaneConfig{Slots: map[int]int{1: 2}})

	a1 := r.session(t, "A1", "cA1")
	r.SessionClock.Advance(3 * time.Second)
	a2 := r.session(t, "A2", "cA2")
	r.SessionClock.Advance(5 * time.Second) // A1 silent 8 s, A2 5 s: both past 2 x TD

	resp := r.tuneTS(t, "B", "cB")
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("the blocked TS tune answered %d, want 200: the reclaim should have freed a slot", resp.StatusCode)
	}
	if n, err := io.ReadFull(resp.Body, make([]byte, 188)); err != nil || n != 188 {
		t.Fatalf("B's stream carried no bytes: %d, %v", n, err)
	}

	status, _, body := r.getHLS(t, a1.path("video.m3u8"))
	if status != http.StatusGone || string(body) != `{"error": "channel stopped"}` {
		t.Fatalf("the reclaimed session's next GET answered %d %q, want 410 and the body", status, body)
	}
	if status, _, _ := r.getHLS(t, a2.path("video.m3u8")); status != http.StatusOK {
		t.Fatalf("the other, less silent session's GET answered %d, want 200: it must not have been touched", status)
	}

	releases := r.Control.RequestsTo("/release")
	if len(releases) != 1 || !strings.Contains(releases[0].Path, "/channels/A1/") {
		t.Fatalf("release POSTs = %v, want exactly A1's", releases)
	}
	if got := r.nextSourceCalls("B"); got != 2 {
		t.Fatalf("B made %d next-source calls, want exactly 2 (the refusal and one retry)", got)
	}
	first := r.requestIndex("B", "/next-source", 0)
	second := r.requestIndex("B", "/next-source", first+1)
	release := r.requestIndex("A1", "/release", 0)
	if first < 0 || release <= first || second <= release {
		t.Fatalf("order of calls: B's first next-source %d, A1's release %d, B's second %d; want first < release < second", first, release, second)
	}
	waitFor(t, "A1's client_disconnect", 10*time.Second, func() bool {
		for _, e := range r.eventsOf("client_disconnect") {
			if e.ClientID == "cA1" {
				return true
			}
		}
		return false
	})
	n := 0
	for _, e := range r.eventsOf("client_disconnect") {
		if e.ClientID == "cA1" {
			n++
		}
	}
	if n != 1 {
		t.Fatalf("A1's session emitted %d client_disconnect events, want 1", n)
	}
}

func TestABlockedTuneNeverReclaimsAWatchedChannel(t *testing.T) {
	t.Run("ts-client", func(t *testing.T) {
		f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
		r := reclaimRig(t, f, relaytest.ControlPlaneConfig{Slots: map[int]int{1: 1}})

		watcher := r.tuneAs(t, "A", "cA")
		defer func() { _ = watcher.Body.Close() }()
		if n, err := io.ReadFull(watcher.Body, make([]byte, 188)); err != nil || n != 188 {
			t.Fatalf("A's viewer received no bytes before the blocked tune: %d, %v", n, err)
		}
		r.SessionClock.Advance(time.Minute)

		r.wantRefused(t, "B", "cB")
		if got := r.nextSourceCalls("B"); got != 2 {
			t.Fatalf("B made %d next-source calls, want 2: one retry, never a second", got)
		}
		if r.Manager.Get("A") == nil {
			t.Fatal("A's channel was reclaimed from under its TS viewer")
		}
		if n, err := io.ReadFull(watcher.Body, make([]byte, 188)); err != nil || n != 188 {
			t.Fatalf("A's TS viewer stopped receiving bytes after the blocked tune: %d, %v", n, err)
		}
	})

	t.Run("reloading", func(t *testing.T) {
		f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
		r := reclaimRig(t, f, relaytest.ControlPlaneConfig{Slots: map[int]int{1: 1}})
		a := r.session(t, "A", "cA")
		for i := 0; i < 6; i++ {
			r.SessionClock.Advance(time.Second)
			if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusOK {
				t.Fatalf("reload %d answered %d, want 200", i+1, status)
			}
		}

		r.wantRefused(t, "B", "cB")
		if r.Manager.Get("A") == nil {
			t.Fatal("a session that reloaded every second lost its channel to a blocked tune")
		}
		if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusOK {
			t.Fatalf("A's next reload answered %d, want 200", status)
		}
	})
}

// The spec's deterministic seam: ManagerConfig.ReclaimPicked runs between the
// pick and the re-check with the manager's lock held, so a test can land a
// request in exactly that window. Nothing here is timing.
func TestTheReclaimReCheckSeesARequestThatArrivedAfterThePick(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := reclaimRig(t, f, relaytest.ControlPlaneConfig{Slots: map[int]int{1: 1}})
	a := r.session(t, "A", "cA")
	r.SessionClock.Advance(5 * time.Second)

	var ran atomic.Int32
	var outcome atomic.Value
	r.onReclaimPick(func(c *channel.Channel) {
		if c.ID() != "A" {
			return
		}
		ran.Add(1)
		outcome.Store(r.Sessions.Begin(a.sid).Outcome)
	})

	r.wantRefused(t, "B", "cB")
	if got := ran.Load(); got != 1 {
		t.Fatalf("the pick hook ran %d times, want exactly 1", got)
	}
	if got, _ := outcome.Load().(session.Outcome); got != session.Serve {
		t.Fatalf("the request that landed after the pick was %v, want Serve", got)
	}
	if r.Manager.Get("A") == nil {
		t.Fatal("the channel was reclaimed with a request in flight: the re-check did not see it")
	}
	r.Sessions.End(a.sid)
	if status, _, body := r.getHLS(t, a.path("video.m3u8")); status != http.StatusOK {
		t.Fatalf("A's next GET answered %d %q, want 200, not 410", status, body)
	}
	for _, req := range r.Control.RequestsTo("/release") {
		if strings.Contains(req.Path, "/channels/A/") {
			t.Fatalf("A's slot was released (%s) though its channel was never reclaimed", req.Path)
		}
	}
}

func TestABlockedTuneRetriesOnceWhenNothingIsReleasingOrReclaimable(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := reclaimRig(t, f, relaytest.ControlPlaneConfig{BlockFirst: 1})

	resp := r.tuneTS(t, "B", "cB")
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("the retried tune answered %d, want 200", resp.StatusCode)
	}
	if got := r.nextSourceCalls("B"); got != 2 {
		t.Fatalf("B made %d next-source calls, want 2", got)
	}
}

func TestABlockedTuneWaitsForAReleaseInFlight(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := reclaimRig(t, f, relaytest.ControlPlaneConfig{Slots: map[int]int{1: 1}})
	open := r.Control.HoldReleases()
	t.Cleanup(open)

	a := r.session(t, "A", "cA")
	if status := r.leave(t, a.token); status != http.StatusNoContent {
		t.Fatalf("A's leave answered %d, want 204", status)
	}
	// A's channel has stopped; its release POST is on its way and held.
	type answer struct {
		status int
		body   string
	}
	answered := make(chan answer, 1)
	go func() {
		status, _, body := r.enter(t, "B", "cB")
		answered <- answer{status, string(body)}
	}()
	waitFor(t, "B's refused first next-source", 10*time.Second, func() bool { return r.nextSourceCalls("B") >= 1 })
	waitFor(t, "A's release POST to be held", 10*time.Second, func() bool { return len(r.Control.RequestsTo("/release")) == 1 })
	select {
	case got := <-answered:
		t.Fatalf("B's entry answered %d before A's release was let through: it must wait for it", got.status)
	case <-time.After(300 * time.Millisecond):
	}
	if got := r.Control.Holders(1); len(got) != 1 || got[0] != "A" {
		t.Fatalf("Holders(1) = %v while A's release was held, want [A]", got)
	}

	open()
	got := <-answered
	if got.status != http.StatusOK {
		t.Fatalf("B's entry answered %d %q after the release, want 200", got.status, got.body)
	}
	if calls := r.nextSourceCalls("B"); calls != 2 {
		t.Fatalf("B made %d next-source calls, want exactly 2", calls)
	}
}

func TestAnInFlightRequestHoldsAChannelAgainstReclaim(t *testing.T) {
	t.Run("entry", func(t *testing.T) {
		f := newHLSFixture(t, modeGatedInit, relaytest.HLSProbeJSON(true, true))
		r := reclaimRig(t, f, relaytest.ControlPlaneConfig{})
		done := make(chan int, 1)
		go func() {
			status, _, _ := r.enter(t, "A", "cA")
			done <- status
		}()
		waitFor(t, "A's entry to register its session", 10*time.Second, func() bool { return r.Sessions.Len() == 1 })
		r.SessionClock.Advance(5 * time.Second)
		if got := r.Manager.ReclaimFor([]int{1}, time.Second); got.Case != channel.ReclaimNothing {
			t.Fatalf("ReclaimFor with an entry held in its init wait = %+v, want {ReclaimNothing}", got)
		}

		f.touch(f.gate)
		if status := <-done; status != http.StatusOK {
			t.Fatalf("the released entry answered %d, want 200", status)
		}
		r.SessionClock.Advance(5 * time.Second)
		if got := r.Manager.ReclaimFor([]int{1}, 5*time.Second); got.Case != channel.ReclaimStopped || got.Channel != "A" {
			t.Fatalf("ReclaimFor once the entry was answered and silent = %+v, want a stop of A", got)
		}
	})

	t.Run("long-poll", func(t *testing.T) {
		f := newHLSFixture(t, modeGatedSegments, relaytest.HLSProbeJSON(true, true))
		r := reclaimRig(t, f, relaytest.ControlPlaneConfig{})
		a := r.session(t, "A", "cA")
		done := make(chan int, 1)
		go func() {
			status, _, _ := r.getHLS(t, a.path("video.m3u8"))
			done <- status
		}()
		waitFor(t, "the playlist request to be in flight", 10*time.Second, func() bool { return r.Sessions.InFlight(a.sid) == 1 })
		r.SessionClock.Advance(5 * time.Second)
		if got := r.Manager.ReclaimFor([]int{1}, time.Second); got.Case != channel.ReclaimNothing {
			t.Fatalf("ReclaimFor with a playlist long-polling = %+v, want {ReclaimNothing}", got)
		}

		f.touch(f.gate)
		if status := <-done; status != http.StatusOK {
			t.Fatalf("the released playlist request answered %d, want 200", status)
		}
		r.SessionClock.Advance(5 * time.Second)
		if got := r.Manager.ReclaimFor([]int{1}, 5*time.Second); got.Case != channel.ReclaimStopped || got.Channel != "A" {
			t.Fatalf("ReclaimFor once the playlist was answered and silent = %+v, want a stop of A", got)
		}
	})
}
