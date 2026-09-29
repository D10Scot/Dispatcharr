package httpapi

import (
	"errors"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/hls"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// Phase 4a-1d at the relay's HTTP surface: the channel's HLS profile from
// next-source keys its pipeline, an entry without one is a contract mismatch,
// and a session's presence thresholds are its pipeline's own target duration.
// The encoder and the probe are stand-ins (the subject is the relay's
// reaction); the real encoder is relay/hls/real_test.go's.

// automaticProbe is an ffprobe answer the automatic decision copies: H.264
// High 8-bit progressive with AAC-LC stereo, and two video key packets gap
// apart, so the run's target duration is targetFor(gap).
func automaticProbe(gap string) []byte {
	return []byte(`{"streams":[` +
		`{"index":0,"codec_type":"video","codec_name":"h264","profile":"High","level":30,"pix_fmt":"yuv420p","width":640,"height":360,` +
		`"field_order":"progressive","r_frame_rate":"25/1","id":"0x100"},` +
		`{"index":1,"codec_type":"audio","codec_name":"aac","profile":"LC","channels":2,"sample_rate":"48000","id":"0x101"}],` +
		`"packets":[{"stream_index":0,"pts_time":"0.000000","flags":"K__","size":"1000"},` +
		`{"stream_index":0,"pts_time":"` + gap + `","flags":"K__","size":"1000"}]}`)
}

func hlsRigFor(t *testing.T, f *hlsFixture, cp relaytest.ControlPlaneConfig) *rig {
	t.Helper()
	return fanRigWith(t, cp, relaytest.Config{Rate: 4}, nil, f.option())
}

func automaticControlPlane() relaytest.ControlPlaneConfig {
	return relaytest.ControlPlaneConfig{HLSProfile: &relaytest.HLSProfileConfig{ID: 7, Mode: "automatic"}}
}

// A channel whose next-source answer names HLS profile 7 in automatic mode
// runs its pipeline under "hls:p7", in automatic mode (a transcode would never
// pass -c:v copy), and a second entry shares it.
func TestAnAutomaticChannelEntersUnderItsProfilesKey(t *testing.T) {
	f := newHLSFixture(t, modeGood, automaticProbe("6.000000"))
	r := hlsRigFor(t, f, automaticControlPlane())

	r.session(t, "c-auto", "client-a")
	ch := r.Manager.Get("c-auto")
	if ch == nil {
		t.Fatal("the channel is not running after an HLS entry")
	}
	if got := ch.HLSProfile(); !got.Known || got.ID != 7 || got.Mode != "automatic" {
		t.Fatalf("the channel's HLS profile is %+v, want {true 7 automatic}", got)
	}
	// A pipeline is registered under "hls:p7", and none under the built-in "hls".
	_, isNew, release, err := ch.AttachHLS("hls:p7", func(hls.Source) (*hls.Pipeline, error) {
		return nil, errors.New("a second pipeline was started under hls:p7")
	})
	if err != nil || isNew {
		t.Fatalf("no pipeline is registered under hls:p7 (new=%t, err=%v)", isNew, err)
	}
	release()
	if f.encoderSpawns() != 1 {
		t.Fatalf("%d encoders spawned for one entry, want 1", f.encoderSpawns())
	}
	if engine, _, ok := ch.HLSStatus(); !ok || engine != string(hls.EngineCopy) {
		t.Fatalf("HLSStatus reports engine %q ok=%t, want %q: the automatic probe said copy", engine, ok, hls.EngineCopy)
	}

	r.session(t, "c-auto", "client-b")
	if f.encoderSpawns() != 1 {
		t.Fatalf("a second entry spawned another encoder (%d): the pipeline is per (channel, profile)", f.encoderSpawns())
	}
}

// An hls tune whose next-source answer carried no hls_profile key is a
// contract mismatch, 502 after the Attach release; a TS tune on the same stub
// is unaffected.
func TestAnHLSEntryWithoutAnHLSProfileKeyIs502(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRigFor(t, f, relaytest.ControlPlaneConfig{HLSProfileAbsent: true})

	status, _, body := r.enter(t, "c-absent", "client-a")
	if status != http.StatusBadGateway || strings.TrimSpace(string(body)) != "control plane contract mismatch" {
		t.Fatalf("the entry answered %d %q, want 502 control plane contract mismatch", status, body)
	}
	waitFor(t, "the refused entry's client to be released", 10*time.Second, func() bool {
		return len(r.listedClients(t, "c-absent")) == 0
	})
	if f.encoderSpawns() != 0 {
		t.Fatalf("a refused entry spawned %d encoders", f.encoderSpawns())
	}

	ts := r.tuneAs(t, "c-absent", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	if ts.StatusCode != http.StatusOK {
		t.Fatalf("a TS tune on the same stub answered %d, want 200", ts.StatusCode)
	}
}

func TestAnUnknownHLSProfileModeIs502(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRigFor(t, f, relaytest.ControlPlaneConfig{HLSProfile: &relaytest.HLSProfileConfig{ID: 7, Mode: "turbo"}})
	status, _, body := r.enter(t, "c-mode", "client-a")
	if status != http.StatusBadGateway || strings.TrimSpace(string(body)) != "control plane contract mismatch" {
		t.Fatalf("the entry answered %d %q, want 502 control plane contract mismatch", status, body)
	}
}

// A profile change reaches a NEW entry on its new key while the pipeline
// already running keeps its own (one ffmpeg per (channel, HLS profile)), and
// null is the built-in re-encode under "hls".
func TestANullHLSProfileRunsTheBuiltInTranscodeUnderTheBuiltInKey(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRigFor(t, f, relaytest.ControlPlaneConfig{})
	r.session(t, "c-null", "client-a")
	ch := r.Manager.Get("c-null")
	_, isNew, release, err := ch.AttachHLS("hls", func(hls.Source) (*hls.Pipeline, error) {
		return nil, errors.New("a second pipeline was started under hls")
	})
	if err != nil || isNew {
		t.Fatalf("no pipeline is registered under hls (new=%t, err=%v)", isNew, err)
	}
	release()
	if got := ch.HLSProfile(); !got.Known || got.ID != 0 {
		t.Fatalf("the channel's HLS profile is %+v, want Known with no id", got)
	}
}

// departAfter drives the session clock one second at a time, sweeping after
// each step, and returns the second at which client-ts alone is left (the
// session's client was departed), or 0 when it never was within limit seconds.
func departAfter(t *testing.T, r *rig, channelID string, limit int) int {
	t.Helper()
	for second := 1; second <= limit; second++ {
		r.SessionClock.Advance(time.Second)
		// Two ticks: the second is accepted only once the sweeper has finished
		// the first sweep, so the registry read below sees its departure.
		r.tick(t)
		r.tick(t)
		if sameIDs(clientIDs(r.listedClients(t, channelID)), "client-ts") {
			return second
		}
	}
	return 0
}

// The session's idle timeout is max(12 s, 6 x its pipeline's TARGETDURATION):
// 36 s for a copied automatic run whose keyframes are 6 s apart, and 12 s for
// the built-in transcode. The failure names the second of the first departure.
func TestAnAutomaticSessionTakesItsPipelinesTargetDuration(t *testing.T) {
	t.Run("automatic, K 6 s", func(t *testing.T) {
		f := newHLSFixture(t, modeGood, automaticProbe("6.000000"))
		r := hlsRigFor(t, f, automaticControlPlane())
		ts := r.tuneAs(t, "c-td6", "client-ts") // holds the channel while the session departs
		defer func() { _ = ts.Body.Close() }()
		r.session(t, "c-td6", "client-a")
		if got := departAfter(t, r, "c-td6", 60); got != 36 {
			t.Fatalf("the automatic session's first departure was at +%d s, want +36 s (max(12 s, 6 x 6 s))", got)
		}
	})
	t.Run("built-in transcode control", func(t *testing.T) {
		f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
		r := hlsRigFor(t, f, relaytest.ControlPlaneConfig{})
		ts := r.tuneAs(t, "c-td2", "client-ts")
		defer func() { _ = ts.Body.Close() }()
		r.session(t, "c-td2", "client-a")
		if got := departAfter(t, r, "c-td2", 60); got != 12 {
			t.Fatalf("the transcode session's first departure was at +%d s, want +12 s", got)
		}
	})
}

// The spec's TD = 6 presence row, end to end: a session of a copied automatic
// run is silent only STRICTLY after 2 x its own target duration (12 s), and a
// player that reloads every 6 s is never silent. The control is the built-in
// transcode, silent at 4.1 s.
func TestAnAutomaticSessionIsSilentOnlyAfterTwoOfItsTargetDurations(t *testing.T) {
	t.Run("automatic, K 6 s", func(t *testing.T) {
		f := newHLSFixture(t, modeGood, automaticProbe("6.000000"))
		r := hlsRigFor(t, f, automaticControlPlane())
		a := r.session(t, "c-sil6", "client-a")
		ch := r.Manager.Get("c-sil6")
		silent := func() bool { _, ok := r.Sessions.Silent(ch, []string{"client-a"}); return ok }

		// While reloading every 6 s, sampled every second for 60 s: never silent.
		for second := 1; second <= 60; second++ {
			r.SessionClock.Advance(time.Second)
			if silent() {
				t.Fatalf("a TD 6 session reloading every 6 s was reported silent at +%d s", second)
			}
			if second%6 == 0 {
				if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusOK {
					t.Fatalf("the reload at +%d s answered %d", second, status)
				}
			}
		}
		// The requests stop. The last one ended when the clock last moved 6 s.
		r.SessionClock.Advance(11900 * time.Millisecond)
		if silent() {
			t.Fatal("reported silent 11.9 s after the last request; silent is strictly more than 2 x 6 s")
		}
		r.SessionClock.Advance(200 * time.Millisecond)
		if !silent() {
			t.Fatal("not silent 12.1 s after the last request")
		}
	})
	t.Run("built-in transcode control", func(t *testing.T) {
		f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
		r := hlsRigFor(t, f, relaytest.ControlPlaneConfig{})
		r.session(t, "c-sil2", "client-a")
		ch := r.Manager.Get("c-sil2")
		r.SessionClock.Advance(4100 * time.Millisecond)
		if _, ok := r.Sessions.Silent(ch, []string{"client-a"}); !ok {
			t.Fatal("a transcode session was not silent 4.1 s after its entry")
		}
	})
}

// The entry's waits cover the longest target's cold start, derived and not
// hand-added: quick probe + re-probe + the startup allowance at target 6 + the
// margin, 43 s, under nginx's 60 s.
func TestTheEntryWaitsCoverTheLongestTargetDuration(t *testing.T) {
	floor := hls.QuickProbe.Analyze + hls.FullProbe.Analyze + hls.StartupStall(hls.MaxTargetDuration)
	for name, got := range map[string]time.Duration{
		"ReadyWait":    HLSDeps{}.readyWait(),
		"PlaylistWait": HLSDeps{}.playlistWait(),
	} {
		if got < floor {
			t.Errorf("the default %s is %v, below the longest target's cold start %v", name, got, floor)
		}
		if got >= 60*time.Second {
			t.Errorf("the default %s is %v: readyWait %v is not under nginx's 60 s", name, got, got)
		}
		if got != 43*time.Second {
			t.Errorf("the default %s is %v, want 43s", name, got)
		}
	}
}
