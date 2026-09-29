package channel

import "testing"

func TestTheHLSProfileKey(t *testing.T) {
	if got := (HLSProfile{}).Key(); got != "hls" {
		t.Fatalf("the zero profile's key is %q, want %q", got, "hls")
	}
	if got := (HLSProfile{Known: true, ID: 7, Mode: "automatic"}).Key(); got != "hls:p7" {
		t.Fatalf("profile 7's key is %q, want %q", got, "hls:p7")
	}
}

// A failover answer that reached Django refreshes the channel's HLS profile; a
// degraded one, which never called Django, carries Known false and leaves the
// channel's own choice alone. The Output Profile set is refreshed the same way
// (2c-7's Ruling R5) and this is its counterpart.
func TestAFailoverAnswerRefreshesTheHLSProfile(t *testing.T) {
	_, ch := hlsChannel(t)
	ch.mu.Lock()
	ch.hlsProfile = HLSProfile{Known: true, ID: 3, Mode: "transcode"}
	ch.mu.Unlock()

	ch.applySwitch(Resolved{HLSProfile: HLSProfile{Known: true, ID: 7, Mode: "automatic"}})
	if got := ch.HLSProfile(); got != (HLSProfile{Known: true, ID: 7, Mode: "automatic"}) {
		t.Fatalf("after a non-degraded switch the channel's HLS profile is %+v, want {true 7 automatic}", got)
	}

	ch.applySwitch(Resolved{Degraded: true})
	if got := ch.HLSProfile(); got != (HLSProfile{Known: true, ID: 7, Mode: "automatic"}) {
		t.Fatalf("a degraded switch changed the HLS profile to %+v; it must keep {true 7 automatic}", got)
	}

	// A null on a real answer (Known true, ID 0) is a change too: back to the built-in.
	ch.applySwitch(Resolved{HLSProfile: HLSProfile{Known: true}})
	if got := ch.HLSProfile(); got != (HLSProfile{Known: true}) {
		t.Fatalf("a null hls_profile left the channel on %+v, want the built-in {true 0 }", got)
	}
}

// HLSStatus reports the pipeline under the channel's CURRENT key, and, when
// none is registered there, the one with the lowest key, so hls_encoder and
// hls_generation stay one value each while a profile change drains an older
// pipeline.
func TestHLSStatusFollowsTheCurrentProfileKey(t *testing.T) {
	_, ch := hlsChannel(t)
	starter := &hlsStarter{}
	ch.mu.Lock()
	ch.hlsProfile = HLSProfile{Known: true, ID: 9, Mode: "automatic"}
	ch.mu.Unlock()

	// One pipeline under "hls:p2" only: the current key "hls:p9" has none, so
	// the lowest registered key answers.
	p2, _, release2, err := ch.AttachHLS("hls:p2", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	if _, key, ok := ch.statusEntryKey(); !ok || key != "hls:p2" {
		t.Fatalf("with only hls:p2 registered the status reports %q ok=%t, want the lowest key hls:p2", key, ok)
	}

	// With one under the current key too, that one is the answer.
	p9, _, release9, err := ch.AttachHLS("hls:p9", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	if p9 == p2 {
		t.Fatal("two keys shared one pipeline")
	}
	if _, key, ok := ch.statusEntryKey(); !ok || key != "hls:p9" {
		t.Fatalf("with hls:p2 and the current key hls:p9 registered the status reports %q ok=%t, want the current key hls:p9", key, ok)
	}
	release2()
	release9()
	doneWithin(t, p2, "hls:p2's last release")
	doneWithin(t, p9, "hls:p9's last release")
	if _, _, ok := ch.HLSStatus(); ok {
		t.Fatal("HLSStatus still reports a pipeline after every release")
	}
}
