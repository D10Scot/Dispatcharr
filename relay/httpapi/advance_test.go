package httpapi

import (
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// advanceBody is what change_stream and next_stream send: the fully-resolved
// source, plus the stream_profile 2c-8 adds so the relay has an argv to
// spawn (it builds no command line, Amendment A4.1).
func advanceBody(t *testing.T, url string, streamID int, resetTried bool) []byte {
	t.Helper()
	body, err := json.Marshal(map[string]any{
		"url":              url,
		"user_agent":       "Dispatcharr/1.0",
		"stream_id":        streamID,
		"m3u_profile_id":   3,
		"stream_name":      "The Alternate",
		"channel_name":     "BBC One HD",
		"m3u_profile_name": "Premium",
		"reset_tried":      resetTried,
		"transcode":        false,
		"stream_profile": map[string]any{
			"id":      1,
			"command": "",
			"args":    "",
			"kind":    "proxy",
			"argv":    []string{},
		},
	})
	if err != nil {
		t.Fatalf("encoding the advance body: %v", err)
	}
	return body
}

// An operator's switch moves the channel to the named URL, keeps the client
// attached and raises the stream_switch event update_url raises.
//
// FOUR THINGS TOGETHER, because any three are satisfiable without the
// switch: the alternate upstream is contacted, the listed stream_id moves,
// the client is still attached and still fed, and the event names the new
// stream.
func TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed(t *testing.T) {
	r, alternate := failoverRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-advance", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client before the switch", response.Body, 100)
	if got := listedStreamID(t, r); got != 1 {
		t.Fatalf("stream_id = %d before the advance, want 1", got)
	}

	status, raw := r.internalCall(t, http.MethodPost,
		"/proxy/relay/channels/c-advance/advance", advanceBody(t, alternate.URL(), 2, true))
	if status != http.StatusOK {
		t.Fatalf("the advance answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "success" || body["success"] != true {
		t.Fatalf("the advance answered %s, want status success and success true", raw)
	}
	if body["direct_update"] != true {
		t.Errorf("direct_update is %v, want true: one process is always the owner", body["direct_update"])
	}

	// WAIT ON THE ALTERNATE, NOT ON THE LISTED STREAM ID. `applySwitch` sets
	// the channel's SourceInfo on the handler's own goroutine, so
	// listedStreamID flips the instant the advance returns -- before the run
	// loop has picked up the parked source and dialled anything. Waiting on
	// that and then asserting the upstream was contacted is a race the
	// assertion loses about half the time without `-race` to slow it down
	// (measured: 8/8 green under -race, 2/3 without). The alternate being
	// contacted is what this test is about, so it is what the wait is on;
	// the listed id is asserted afterwards, when it is no longer a latch
	// that fires early.
	waitFor(t, "the alternate to be contacted", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
	if n := alternate.Requests(); n != 1 {
		t.Fatalf("the alternate saw %d requests, want 1", n)
	}
	if got := listedStreamID(t, r); got != 2 {
		t.Fatalf("stream_id = %d after the advance, want 2", got)
	}
	// The client is still attached and still receiving whole packets from
	// the NEW upstream: readAligned rather than packetRun, because the two
	// upstreams' packet indices do not continue one another.
	readAligned(t, response.Body, 100)
	if ch := listedChannel(t, r); ch["client_count"] != 1.0 {
		t.Fatalf("client_count = %v after the advance, want 1", ch["client_count"])
	}

	var switches []relaytest.RecordedEvent
	waitFor(t, "the stream_switch event", 10*time.Second, func() bool {
		switches = r.Control.EventsOfType("stream_switch")
		return len(switches) == 1
	})
	if switches[0].StreamID == nil || *switches[0].StreamID != 2 {
		t.Fatalf("stream_switch = %+v, want stream 2", switches[0])
	}
}

// The three refusals, each with its own answer.
//
// A body with no url and a body with no stream_profile are both 400 -- what
// DRF's own payload.is_valid(raise_exception=True) answers -- and an unknown
// channel is the 200-with-an-error-body shape the Django wrapper turns into
// its 404. Asserting all three together is what stops a handler that
// answered one status for everything from passing.
func TestAnAdvanceRefusesAMalformedBodyAndAnUnknownChannel(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-refuse", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	noURL := []byte(`{"user_agent":"x","stream_profile":{"id":1,"command":"","args":"","kind":"proxy","argv":[]}}`)
	if status, raw := r.internalCall(t, http.MethodPost, "/proxy/relay/channels/c-refuse/advance", noURL); status != http.StatusBadRequest {
		t.Errorf("an advance with no url answered %d, want 400: %s", status, raw)
	}

	noProfile := []byte(`{"url":"http://provider.invalid/x.ts"}`)
	if status, raw := r.internalCall(t, http.MethodPost, "/proxy/relay/channels/c-refuse/advance", noProfile); status != http.StatusBadRequest {
		t.Errorf("an advance with no stream_profile answered %d, want 400 -- the relay "+
			"builds no command line and cannot spawn without one: %s", status, raw)
	}

	status, raw := r.internalCall(t, http.MethodPost,
		"/proxy/relay/channels/c-nothing/advance", advanceBody(t, "http://provider.invalid/x.ts", 2, false))
	if status != http.StatusOK {
		t.Fatalf("an advance for an unknown channel answered %d, want 200 with an error body: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "error" || body["message"] != "Channel not found" {
		t.Errorf("an unknown channel answered %s, want channel_service.py:478-482's shape", raw)
	}
	diagnostics, ok := body["diagnostics"].(map[string]any)
	if !ok || diagnostics["in_local_managers"] != false {
		t.Errorf("diagnostics is %v, want in_local_managers false", body["diagnostics"])
	}
}

// An advance naming the URL already playing is reported as SUCCESS and
// switches nothing.
//
// update_url returns False for an unchanged URL (input/manager.py:1463-1465)
// and change_stream_url still reports success, because that layer treats it
// as a metadata refresh -- ":487-490 -- update_url() returns False for same
// URL; still success so metadata refreshes". Both halves are asserted: the
// answer AND the absence of a second upstream connection.
func TestAnAdvanceToTheURLAlreadyPlayingSucceedsAndSwitchesNothing(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-same", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 100)
	before := r.Upstream.Requests()

	current := r.Manager.Get("c-same").Source().URL
	if current == "" {
		t.Fatalf("the channel has no source URL to repeat")
	}
	status, raw := r.internalCall(t, http.MethodPost,
		"/proxy/relay/channels/c-same/advance", advanceBody(t, current, 1, false))
	if status != http.StatusOK {
		t.Fatalf("the advance answered %d: %s", status, raw)
	}
	if body := decodeObject(t, raw); body["success"] != true {
		t.Errorf("an advance to the URL already playing answered %s, want success true", raw)
	}

	// Nothing switched: the upstream was not reconnected, and no
	// stream_switch was raised. Both, because either alone could be true for
	// the wrong reason.
	time.Sleep(500 * time.Millisecond)
	if after := r.Upstream.Requests(); after != before {
		t.Errorf("the upstream saw %d requests after an unchanged-URL advance, want the %d it had", after, before)
	}
	if got := r.Control.EventsOfType("stream_switch"); len(got) != 0 {
		t.Errorf("an unchanged-URL advance raised %d stream_switch events, want 0", len(got))
	}
}

// reset_tried clears the exclusion list an automatic failover built, which is
// what /proxy/ts/change_stream/ asks for and /proxy/ts/next_stream/ does not.
//
// Asserted through the NEXT-SOURCE REQUEST that follows, not through an
// internal field: the tried set is only observable as the exclude_stream_ids
// the relay sends, which is also the only thing it is for.
func TestResetTriedClearsTheExclusionListAndOmittingItDoesNot(t *testing.T) {
	for _, tc := range []struct {
		name       string
		resetTried bool
		wantStream int
	}{
		// With reset_tried, stream 1 is excluded again only because the
		// advance itself records stream 2 -- so the list the relay sends
		// next holds exactly the one stream the advance named.
		{"reset_tried clears it", true, 2},
		// Without it, stream 1 stays in the set the tune put it in.
		{"without reset_tried", false, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, alternate := failoverRig(t, relaytest.Config{}, nil)
			response := r.tuneAs(t, "c-tried", "client-a")
			defer func() { _ = response.Body.Close() }()
			packetRun(t, "the client", response.Body, 10)

			status, raw := r.internalCall(t, http.MethodPost,
				"/proxy/relay/channels/c-tried/advance", advanceBody(t, alternate.URL(), 2, tc.resetTried))
			if status != http.StatusOK {
				t.Fatalf("the advance answered %d: %s", status, raw)
			}
			// The alternate again, for the reason above: the listed id flips
			// on the handler's goroutine and the dial happens later.
			waitFor(t, "the alternate to be contacted", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
			if got := listedStreamID(t, r); got != 2 {
				t.Fatalf("stream_id = %d after the advance, want 2", got)
			}

			excluded := excludedStreamIDs(t, r)
			if tc.resetTried {
				if len(excluded) != 1 || excluded[0] != tc.wantStream {
					t.Fatalf("after reset_tried the relay would exclude %v, want just [%d]", excluded, tc.wantStream)
				}
				return
			}
			if !containsInt(excluded, tc.wantStream) {
				t.Fatalf("without reset_tried the relay would exclude %v, which has lost stream %d", excluded, tc.wantStream)
			}
		})
	}
}

// excludedStreamIDs is the tried set, read the only way it is observable:
// the exclude_stream_ids a failover would send.
func excludedStreamIDs(t *testing.T, r *rig) []int {
	t.Helper()
	ch := r.Manager.Get("c-tried")
	if ch == nil {
		t.Fatalf("the channel is not running")
	}
	return ch.ExcludedStreamIDs()
}

func containsInt(haystack []int, needle int) bool {
	for _, v := range haystack {
		if v == needle {
			return true
		}
	}
	return false
}
