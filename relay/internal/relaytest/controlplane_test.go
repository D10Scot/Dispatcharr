package relaytest

import (
	"bytes"
	"encoding/json"
	"net/http"
	"slices"
	"testing"
	"time"
)

// post sends one JSON body to the fake and decodes the object it answers.
func post(t *testing.T, cp *ControlPlane, path string, body string) map[string]any {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodPost, cp.URL()+path, bytes.NewBufferString(body))
	if err != nil {
		t.Fatalf("building POST %s: %v", path, err)
	}
	request.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("POST %s: %v", path, err)
	}
	defer func() { _ = resp.Body.Close() }()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("POST %s: decoding the answer: %v", path, err)
	}
	return out
}

const initialBody = `{"reason":"initial","exclude_stream_ids":[]}`

func nextSource(t *testing.T, cp *ControlPlane, channel string) map[string]any {
	t.Helper()
	return post(t, cp, "/api/relay/channels/"+channel+"/next-source", initialBody)
}

func TestTheSlotModelBlocksReleasesAndHolds(t *testing.T) {
	t.Run("a full profile blocks the next channel, a release frees it", func(t *testing.T) {
		cp := NewControlPlane(ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts", Slots: map[int]int{1: 1}})
		t.Cleanup(cp.Close)

		if nextSource(t, cp, "a")["source"] == nil {
			t.Fatal("the first channel on a one-slot profile was blocked")
		}
		blocked := nextSource(t, cp, "b")
		if blocked["source"] != nil {
			t.Fatal("a second channel on a full profile got a source")
		}
		if blocked["error"] != allProfilesFull {
			t.Fatalf("error = %v, want the all-profiles-full reason", blocked["error"])
		}
		capacity, _ := blocked["capacity"].(map[string]any)
		if capacity["blocked"] != true || !slices.Equal(toInts(capacity["profile_ids"]), []int{1}) {
			t.Fatalf("capacity = %v, want blocked with profile_ids [1]", blocked["capacity"])
		}
		if got := cp.Holders(1); !slices.Equal(got, []string{"a"}) {
			t.Fatalf("Holders(1) = %v, want [a]", got)
		}
		if nextSource(t, cp, "a")["source"] == nil {
			t.Fatal("the holder's own repeat call was blocked; it must reuse its slot")
		}
		if got := cp.Holders(1); !slices.Equal(got, []string{"a"}) {
			t.Fatalf("Holders(1) after a reuse = %v, want [a]", got)
		}

		post(t, cp, "/api/relay/channels/a/release", `{}`)
		if got := cp.Holders(1); len(got) != 0 {
			t.Fatalf("Holders(1) after a's release = %v, want none", got)
		}
		if nextSource(t, cp, "b")["source"] == nil {
			t.Fatal("b was still blocked after the slot was released")
		}
	})

	t.Run("HoldReleases holds a release until open", func(t *testing.T) {
		cp := NewControlPlane(ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts", Slots: map[int]int{1: 1}})
		t.Cleanup(cp.Close)
		nextSource(t, cp, "a")
		open := cp.HoldReleases()
		t.Cleanup(open)

		done := make(chan struct{})
		go func() {
			post(t, cp, "/api/relay/channels/a/release", `{}`)
			close(done)
		}()
		deadline := time.Now().Add(5 * time.Second)
		for len(cp.RequestsTo("/release")) == 0 {
			if time.Now().After(deadline) {
				t.Fatal("the release was never recorded")
			}
			time.Sleep(time.Millisecond)
		}
		select {
		case <-done:
			t.Fatal("a held release was answered before open")
		default:
		}
		if got := cp.Holders(1); !slices.Equal(got, []string{"a"}) {
			t.Fatalf("a held release freed its slot early: Holders(1) = %v", got)
		}
		open()
		open() // idempotent
		<-done
		if got := cp.Holders(1); len(got) != 0 {
			t.Fatalf("Holders(1) after open = %v, want none", got)
		}
	})

	t.Run("BlockFirst blocks the first call and no other", func(t *testing.T) {
		cp := NewControlPlane(ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts", BlockFirst: 1, ProfileOf: map[string]int{"a": 7}})
		t.Cleanup(cp.Close)
		first := nextSource(t, cp, "a")
		if first["source"] != nil {
			t.Fatal("the first call was not blocked")
		}
		capacity, _ := first["capacity"].(map[string]any)
		if !slices.Equal(toInts(capacity["profile_ids"]), []int{7}) {
			t.Fatalf("capacity = %v, want profile_ids [7] (ProfileOf)", first["capacity"])
		}
		if nextSource(t, cp, "a")["source"] == nil {
			t.Fatal("the second call was blocked")
		}
	})

	t.Run("the zero config is unlimited on profile 1", func(t *testing.T) {
		cp := NewControlPlane(ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
		t.Cleanup(cp.Close)
		for _, id := range []string{"a", "b", "c"} {
			answer := nextSource(t, cp, id)
			source, _ := answer["source"].(map[string]any)
			if source == nil {
				t.Fatalf("channel %s was blocked on the zero config", id)
			}
			if source["m3u_profile_id"] != float64(1) {
				t.Fatalf("m3u_profile_id = %v, want 1", source["m3u_profile_id"])
			}
			if _, present := answer["capacity"]; present {
				t.Fatalf("an answered tune carried a capacity key: %v", answer["capacity"])
			}
		}
	})
}

func toInts(v any) []int {
	list, _ := v.([]any)
	out := make([]int, 0, len(list))
	for _, item := range list {
		if f, ok := item.(float64); ok {
			out = append(out, int(f))
		}
	}
	return out
}
