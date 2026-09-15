package control

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The release body is ReleaseRequestSerializer's, every key present and null
// when unknown, exactly as control_plane.release_source sends it; the answer
// is Django's own flag.
func TestReleaseSendsAllThreeKeysAndReadsTheFlag(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	streamID := 41
	released, err := testClient(t, cp).Release(context.Background(), "c-1", ReleaseRequest{StreamID: &streamID})
	if err != nil || !released {
		t.Fatalf("Release = %v, %v; want true, nil", released, err)
	}
	seen := cp.RequestsTo("/release")
	if len(seen) != 1 || seen[0].Path != "/api/relay/channels/c-1/release" {
		t.Fatalf("the fake saw %+v", seen)
	}
	var body map[string]any
	if err := json.Unmarshal(seen[0].Body, &body); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	for _, key := range []string{"stream_id", "m3u_profile_id", "channel_pk"} {
		if _, present := body[key]; !present {
			t.Fatalf("release body %s lacks %q: control_plane.release_source sends every key", seen[0].Body, key)
		}
	}
	if body["stream_id"] != 41.0 || body["m3u_profile_id"] != nil || body["channel_pk"] != nil {
		t.Fatalf("release body = %s", seen[0].Body)
	}
	if seen[0].Header.Get(HeaderInternalRequest) == "" {
		t.Fatal("the release was not signed")
	}
}

// The disposition table applies to release as it does to next-source: a 4xx
// is a Refused and is not retried; a 5xx is retried once and is Unavailable.
func TestReleaseFollowsTheDispositionTable(t *testing.T) {
	refusing := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusNotFound})
	t.Cleanup(refusing.Close)
	_, err := testClient(t, refusing).Release(context.Background(), "c-1", ReleaseRequest{})
	var refused *Refused
	if !errors.As(err, &refused) || refused.Status != http.StatusNotFound {
		t.Fatalf("a 404 on release = %v, want a Refused carrying 404 (no 404 mapping here, unlike next-source)", err)
	}
	if n := len(refusing.Requests()); n != 1 {
		t.Fatalf("a 404 was retried: %d requests", n)
	}

	down := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusBadGateway})
	t.Cleanup(down.Close)
	_, err = testClient(t, down).Release(context.Background(), "c-1", ReleaseRequest{})
	var unavailable *Unavailable
	if !errors.As(err, &unavailable) {
		t.Fatalf("a 502 on release = %v, want an Unavailable", err)
	}
	if n := len(down.Requests()); n != 2 {
		t.Fatalf("a 502 was attempted %d times, want 2", n)
	}
}
