package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/hls"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The rewind window, the linger and the behind-live grace at the relay's HTTP
// surface (Phase 4a-3). "Driven clock" is rig.SessionClock.Advance plus a
// sweeper tick; "the timers" is rig.Timers, which fires only when a test says
// so. The disk is real (a temporary root) unless a test injects a failing one.

// lingerSettings is the proxy_settings override every test that lingers passes.
func lingerSettings(extra map[string]any) map[string]any {
	s := map[string]any{"rewind_linger_seconds": 300}
	for k, v := range extra {
		s[k] = v
	}
	return s
}

func rewindRig(t *testing.T, f *hlsFixture, cp relaytest.ControlPlaneConfig, overrides map[string]any, fs hls.FS) *rig {
	t.Helper()
	return fanRigWith(t, cp, relaytest.Config{Rate: 4}, overrides, f.option(), withRewind(t, fs))
}

// enoSpcFS is the real disk whose writes all fail with ENOSPC.
type enoSpcFS struct{ hls.OSFS }

func (enoSpcFS) WriteFile(string, []byte) error { return syscall.ENOSPC }

func testContext(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 60*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// pipelineOf is the channel's HLS pipeline, which a test reaches its store
// through.
func (r *rig) pipelineOf(t *testing.T, channelID string) *hls.Pipeline {
	t.Helper()
	ch := r.Manager.Get(channelID)
	if ch == nil {
		t.Fatalf("channel %s is not running", channelID)
	}
	p, ok := ch.HLSPipeline()
	if !ok {
		t.Fatalf("channel %s has no HLS pipeline", channelID)
	}
	return p
}

// detailOf is the detail endpoint's body for a channel, decoded.
func (r *rig) detailOf(t *testing.T, channelID string) map[string]any {
	t.Helper()
	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/"+channelID, nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatalf("decoding the detail: %v", err)
	}
	return out
}

// listedOf is the list endpoint's row for a channel, decoded.
func (r *rig) listedOf(t *testing.T, channelID string) map[string]any {
	t.Helper()
	status, raw := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("listing channels answered %d", status)
	}
	var list struct {
		Channels []map[string]any `json:"channels"`
	}
	if err := json.Unmarshal(raw, &list); err != nil {
		t.Fatalf("decoding the list: %v", err)
	}
	for _, ch := range list.Channels {
		if ch["channel_id"] == channelID {
			return ch
		}
	}
	t.Fatalf("channel %s is not in the list", channelID)
	return nil
}

func (r *rig) lingering(t *testing.T, channelID string) bool {
	t.Helper()
	_, present := r.detailOf(t, channelID)["lingering_since"]
	return present
}

// waitLingering waits until the channel reports its linger: a departure runs
// on its own goroutine (R51).
func (r *rig) waitLingering(t *testing.T, channelID string) {
	t.Helper()
	waitFor(t, "channel "+channelID+" to linger", 20*time.Second, func() bool { return r.lingering(t, channelID) })
}

// waitBehind waits until the channel's store holds the sequence on disk, so a
// segment served afterwards is genuinely old.
func (r *rig) waitDurable(t *testing.T, channelID string, seq uint64) {
	t.Helper()
	if err := r.pipelineOf(t, channelID).Store().WaitDurable(testContext(t), seq); err != nil {
		t.Fatalf("channel %s never wrote segment %d: %v", channelID, seq, err)
	}
}

var segmentURI = regexp.MustCompile(`video/(\d+)\.m4s`)

// newestSequence is the last segment the video playlist lists.
func (r *rig) newestSequence(t *testing.T, s hlsSession) string {
	t.Helper()
	status, _, body := r.getHLS(t, s.path("video.m3u8"))
	if status != http.StatusOK {
		t.Fatalf("the media playlist answered %d", status)
	}
	all := segmentURI.FindAllStringSubmatch(string(body), -1)
	if len(all) == 0 {
		t.Fatalf("the media playlist lists no segment:\n%s", body)
	}
	return all[len(all)-1][1]
}

func TestTuningFromReadsTheRewindSettings(t *testing.T) {
	values := relaytest.EffectiveProxySettings()
	values["rewind_window_minutes"] = 1.5
	values["rewind_linger_seconds"] = 20
	values["rewind_behind_live_grace_seconds"] = 7
	values["rewind_disk_cap_gb"] = 0.5
	settings := control.Settings{}
	for k, v := range values {
		raw, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		settings[k] = raw
	}
	tuning, _, err := tuningFrom(settings)
	if err != nil {
		t.Fatal(err)
	}
	if tuning.RewindWindow != 90*time.Second || tuning.RewindLinger != 20*time.Second ||
		tuning.BehindLiveGrace != 7*time.Second || tuning.RewindDiskCap != 536_870_912 {
		t.Fatalf("tuning = window %v, linger %v, grace %v, cap %d; want 90s, 20s, 7s, 536870912",
			tuning.RewindWindow, tuning.RewindLinger, tuning.BehindLiveGrace, tuning.RewindDiskCap)
	}
}

func TestATuneSetsTheProcessDiskCap(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{}, map[string]any{"rewind_disk_cap_gb": 2}, hls.OSFS{})
	if r.Rewind.Cap() != math.MaxInt64 {
		t.Fatalf("Cap() = %d before any tune, want unlimited", r.Rewind.Cap())
	}
	resp := r.tuneAs(t, "A", "cA")
	defer func() { _ = resp.Body.Close() }()
	if got := r.Rewind.Cap(); got != 2<<30 {
		t.Fatalf("Cap() = %d after one tune, want 2 GiB", got)
	}
}

// Row ⟨G⟩: a segment older than the store's in-memory 21 is served, and the
// window's playlist lists it.
func TestAnOldSegmentIsServedFromDisk(t *testing.T) {
	f := newHLSFixture(t, modeLong, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{}, nil, hls.OSFS{})
	s := r.session(t, "A", "cA")
	r.waitDurable(t, "A", 24)

	status, _, body := r.getHLS(t, s.path("video.m3u8"))
	if status != http.StatusOK {
		t.Fatalf("the media playlist answered %d", status)
	}
	if !strings.Contains(string(body), "#EXT-X-MEDIA-SEQUENCE:0\n") || strings.Count(string(body), "#EXTINF:") < 25 {
		t.Fatalf("the window's playlist does not list from segment 0 across more than the live edge:\n%s", body)
	}
	status, _, seg := r.getHLS(t, s.path("video/0.m4s"))
	if status != http.StatusOK || len(seg) < 8 || !bytes.Equal(seg[4:8], []byte("moof")) {
		t.Fatalf("segment 0 answered %d with %d bytes, want a fragment (moof)", status, len(seg))
	}
	if r.Rewind.Bytes() == 0 {
		t.Fatal("nothing is accounted on disk")
	}
}

// Row ⟨E⟩: the last session's leave lingers the channel with no client.
func TestALeftSessionsChannelLingersWithNoClient(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{}, lingerSettings(nil), hls.OSFS{})
	s := r.session(t, "A", "cA")
	if r.lingering(t, "A") {
		t.Fatal("a channel with a live session reports a linger")
	}
	if got := r.leave(t, s.token); got != http.StatusNoContent {
		t.Fatalf("DELETE answered %d, want 204", got)
	}
	if r.Manager.Get("A") == nil {
		t.Fatal("the channel stopped when its last session left")
	}
	d := r.detailOf(t, "A")
	if _, present := d["lingering_since"]; !present || d["client_count"] != float64(0) {
		t.Fatalf("detail = lingering_since %v, client_count %v; want a linger with no client", d["lingering_since"], d["client_count"])
	}
	if clients, _ := r.listedOf(t, "A")["clients"].([]any); len(clients) != 0 {
		t.Fatalf("the list shows %d clients for a lingering channel", len(clients))
	}
	pending := r.Timers.Pending()
	if len(pending) != 1 || pending[0].d != 300*time.Second {
		t.Fatalf("armed timers = %d, want the linger's 300 s alone", len(pending))
	}
	r.Timers.Fire(pending[0])
	waitFor(t, "the lingering channel to stop", 20*time.Second, channelGone(r, "A"))
}

// A resume during the linger re-attaches to the very pipeline that lingers.
func TestAResumeDuringTheLingerKeepsTheWindow(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{}, lingerSettings(nil), hls.OSFS{})
	s := r.session(t, "A", "cA")
	before := r.pipelineOf(t, "A")

	r.SessionClock.Advance(12 * time.Second) // the idle timeout at TARGETDURATION 2
	r.tick(t)
	r.waitLingering(t, "A")
	if len(r.Timers.Pending()) != 1 {
		t.Fatalf("%d timers pending, want the linger's", len(r.Timers.Pending()))
	}
	var status int
	waitFor(t, "the resume's answer once the departure has settled", 20*time.Second, func() bool {
		status, _, _ = r.getHLS(t, s.path("video.m3u8"))
		return status != http.StatusServiceUnavailable
	})
	if status != http.StatusOK {
		t.Fatalf("the resume answered %d, want 200", status)
	}
	if r.pipelineOf(t, "A") != before {
		t.Fatal("the resume attached to a different pipeline")
	}
	if r.lingering(t, "A") || len(r.Timers.Pending()) != 0 {
		t.Fatalf("the linger did not end: lingering %t, %d timers pending", r.lingering(t, "A"), len(r.Timers.Pending()))
	}
}

// slotSetup is the reclaim tests' common start: one slot, a long run, a
// lingering channel A and its first session, with segment 24 on disk so that
// segment 0 is far behind the newest.
func slotSetup(t *testing.T) (*rig, hlsSession) {
	t.Helper()
	f := newHLSFixture(t, modeLong, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{Slots: map[int]int{1: 1}}, lingerSettings(nil), hls.OSFS{})
	a := r.session(t, "A", "cA")
	r.waitDurable(t, "A", 24)
	return r, a
}

// wantServed fails unless the TS tune is served and carries bytes.
func (r *rig) wantServed(t *testing.T, channelID, clientID string) {
	t.Helper()
	resp := r.tuneTS(t, channelID, clientID)
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 200))
		t.Fatalf("the tune of %s answered %d %q, want 200", channelID, resp.StatusCode, body)
	}
	if n, err := io.ReadFull(resp.Body, make([]byte, 188)); err != nil || n != 188 {
		t.Fatalf("%s's stream carried no bytes: %d, %v", channelID, n, err)
	}
}

// Row ⟨F⟩ (R82): a viewer far behind live that stops without a leave holds its
// slot for 2 x TARGETDURATION plus the grace after its last request.
func TestABehindLiveSessionThatGoesSilentHoldsItsSlotForTheGrace(t *testing.T) {
	r, a := slotSetup(t)
	if status, _, _ := r.getHLS(t, a.path("video/0.m4s")); status != http.StatusOK {
		t.Fatalf("the old segment answered %d", status)
	}
	// As a player reloads its playlist after a fetch: not a segment, so it
	// does not clear the behind-live mark.
	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusOK {
		t.Fatalf("the playlist answered %d", status)
	}

	r.SessionClock.Advance(5 * time.Second)
	r.wantRefused(t, "B", "cB")

	r.SessionClock.Advance(8 * time.Second) // 13 s: A departs idle at 12 s
	r.tick(t)
	r.waitLingering(t, "A")
	r.wantRefused(t, "B", "cB")

	r.SessionClock.Advance(1500 * time.Millisecond) // 14.5 s, past 4 s + the 10 s grace
	r.wantServed(t, "B", "cB")
	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusGone {
		t.Fatalf("A's next request answered %d, want 410", status)
	}
}

// R25: an explicit leave has no grace.
func TestABehindLiveSessionThatLeavesIsReclaimableAtOnce(t *testing.T) {
	r, a := slotSetup(t)
	if status, _, _ := r.getHLS(t, a.path("video/0.m4s")); status != http.StatusOK {
		t.Fatalf("the old segment answered %d", status)
	}
	if got := r.leave(t, a.token); got != http.StatusNoContent {
		t.Fatalf("DELETE answered %d", got)
	}
	r.wantServed(t, "B", "cB")
}

// A viewer at the live edge is silent at 4a-1c's 2 x TARGETDURATION.
func TestALiveEdgeSessionHasNoGrace(t *testing.T) {
	r, a := slotSetup(t)
	newest := r.newestSequence(t, a)
	if status, _, _ := r.getHLS(t, a.path("video/"+newest+".m4s")); status != http.StatusOK {
		t.Fatalf("the newest segment answered %d", status)
	}
	if seq, _ := strconv.Atoi(newest); seq < 20 {
		t.Fatalf("the newest listed segment is %d, want one near the live edge", seq)
	}
	r.SessionClock.Advance(5 * time.Second)
	r.wantServed(t, "B", "cB")
}

// The spec's break-check oracle, on the real session table: a lingering channel
// that still has a TS client is never reclaimed.
func TestALingeringChannelWithATSClientIsNeverReclaimed(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{Slots: map[int]int{1: 1}}, lingerSettings(nil), hls.OSFS{})

	watcher := r.tuneAs(t, "A", "cTS")
	defer func() { _ = watcher.Body.Close() }()
	if n, err := io.ReadFull(watcher.Body, make([]byte, 188)); err != nil || n != 188 {
		t.Fatalf("A's TS viewer received no bytes: %d, %v", n, err)
	}
	a := r.session(t, "A", "cA")
	if got := r.leave(t, a.token); got != http.StatusNoContent {
		t.Fatalf("DELETE answered %d", got)
	}
	d := r.detailOf(t, "A")
	if _, lingering := d["lingering_since"]; !lingering || d["client_count"] != float64(1) {
		t.Fatalf("A: lingering %t, client_count %v; want lingering with the one TS client", lingering, d["client_count"])
	}

	r.SessionClock.Advance(time.Minute)
	r.wantRefused(t, "B", "cB")
	if r.Manager.Get("A") == nil || !r.lingering(t, "A") {
		t.Fatal("A's lingering channel was reclaimed from under its TS viewer")
	}
	if n, err := io.ReadFull(watcher.Body, make([]byte, 188)); err != nil || n != 188 {
		t.Fatalf("A's TS viewer stopped receiving bytes after the blocked tune: %d, %v", n, err)
	}
}

// Row ⟨H⟩: a failing disk degrades the window and touches nothing else.
func TestADiskFailureNeverFailsTheLiveOutput(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{}, nil, enoSpcFS{})
	ts := r.tuneAs(t, "A", "cTS")
	defer func() { _ = ts.Body.Close() }()
	s := r.session(t, "A", "cA")
	if err := r.pipelineOf(t, "A").Store().WaitDegraded(testContext(t)); err != nil {
		t.Fatal(err)
	}

	for _, name := range []string{"video.m3u8", "aac.m3u8"} {
		if status, _, _ := r.getHLS(t, s.path(name)); status != http.StatusOK {
			t.Fatalf("%s answered %d after the degradation, want 200", name, status)
		}
	}
	if d := r.detailOf(t, "A"); d["rewind_degraded"] != true {
		t.Fatalf("detail rewind_degraded = %v, want true", d["rewind_degraded"])
	}
	if n, err := io.ReadFull(ts.Body, make([]byte, 188*8)); err != nil || n != 188*8 {
		t.Fatalf("the TS client stopped receiving bytes: %d, %v", n, err)
	}
}

func TestTheChannelPayloadsCarryTheRewindFields(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{}, lingerSettings(nil), hls.OSFS{})
	s := r.session(t, "A", "cA")
	r.waitDurable(t, "A", 2)
	for name, payload := range map[string]map[string]any{"list": r.listedOf(t, "A"), "detail": r.detailOf(t, "A")} {
		if _, present := payload["lingering_since"]; present {
			t.Errorf("%s: a channel with a live session carries lingering_since", name)
		}
		if seconds, _ := payload["rewind_window_seconds"].(float64); seconds <= 0 {
			t.Errorf("%s: rewind_window_seconds = %v, want the listed span", name, payload["rewind_window_seconds"])
		}
	}
	if got := r.leave(t, s.token); got != http.StatusNoContent {
		t.Fatalf("DELETE answered %d", got)
	}
	for name, payload := range map[string]map[string]any{"list": r.listedOf(t, "A"), "detail": r.detailOf(t, "A")} {
		since, present := payload["lingering_since"].(float64)
		if !present || math.Abs(float64(time.Now().UnixNano())/1e9-since) > 30 {
			t.Errorf("%s: lingering_since = %v, want a Unix time within seconds of now", name, payload["lingering_since"])
		}
		if seconds, _ := payload["rewind_window_seconds"].(float64); seconds <= 0 {
			t.Errorf("%s: rewind_window_seconds = %v, want > 0", name, payload["rewind_window_seconds"])
		}
		if _, degraded := payload["rewind_degraded"]; degraded {
			t.Errorf("%s: a healthy window carries rewind_degraded", name)
		}
	}
}

// R84 holds with the session STOPPED rather than removed: an admin client stop
// of the last session lingers its pipeline with no grace.
func TestAnAdminClientStopOfTheLastSessionLingersTheChannel(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := rewindRig(t, f, relaytest.ControlPlaneConfig{}, lingerSettings(nil), hls.OSFS{})
	s := r.session(t, "A", "cA")
	if status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/A/clients/cA", nil); status != http.StatusOK {
		t.Fatalf("the client stop answered %d: %s", status, raw)
	}
	// The session's own release drops its client entry and the pipeline
	// reference; an EndClient that discarded them would leave both held.
	waitFor(t, "the stopped session's client entry to be dropped", 10*time.Second, func() bool {
		return !slices.Contains(clientIDs(r.listedClients(t, "A")), "cA")
	})
	r.waitLingering(t, "A")
	d := r.detailOf(t, "A")
	if d["client_count"] != float64(0) {
		t.Fatalf("client_count = %v, want 0 for a lingering channel", d["client_count"])
	}
	if status, _, body := r.getHLS(t, s.path("video.m3u8")); status != http.StatusGone || !strings.Contains(string(body), `"ended": "admin_stop"`) {
		t.Fatalf("the stopped session's GET answered %d %q, want 410 admin_stop", status, body)
	}
}
