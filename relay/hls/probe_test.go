package hls

import (
	"strings"
	"testing"
)

// probeJSONFor is ffprobe's -show_streams JSON, trimmed to the fields ParseProbe
// reads, in the shape ffmpeg 9.0.1 printed it for the 4a-0 fixtures and for a
// transport stream whose PMT declares an AC-3 PID that carries no packets.
const probeJSONFor1080iWithAnEmptyAC3 = `{"streams": [
 {"index": 0, "codec_name": "h264", "profile": "High", "codec_type": "video", "width": 1920, "height": 1080,
  "pix_fmt": "yuv420p", "field_order": "tt", "r_frame_rate": "25/1", "avg_frame_rate": "25/1", "id": "0x300"},
 {"index": 1, "codec_name": "aac", "profile": "LC", "codec_type": "audio", "sample_rate": "48000", "channels": 2,
  "r_frame_rate": "0/0", "id": "0x301", "tags": {"language": "eng"}},
 {"index": 2, "codec_name": "ac3", "codec_type": "audio", "sample_rate": "0", "channels": 0,
  "r_frame_rate": "0/0", "id": "0x302"}
]}`

func TestParseProbeReadsTheStreams(t *testing.T) {
	p, err := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
	if err != nil {
		t.Fatalf("ParseProbe: %v", err)
	}
	want := Video{ID: "0x300", Codec: "h264", Profile: "High", PixFmt: "yuv420p", Width: 1920, Height: 1080,
		FrameRate: Rational{25, 1}, Field: FieldInterlaced, fieldReported: true}
	if p.Video == nil || *p.Video != want {
		t.Fatalf("video = %+v, want %+v", p.Video, want)
	}
	if len(p.Audio) != 2 || p.Audio[0].Language != "eng" || p.Audio[1].ID != "0x302" {
		t.Fatalf("audio = %+v", p.Audio)
	}
	if _, err := ParseProbe([]byte("{")); err == nil {
		t.Errorf("ParseProbe accepted malformed JSON")
	}
}

// Spec § Encoder argv: a PMT-declared audio stream that carries no packets is
// reported with 0 channels and a sample rate of 0, and does not qualify.
func TestADeclaredButEmptyAudioStreamDoesNotQualify(t *testing.T) {
	p, _ := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
	q := p.Qualifying()
	if len(q) != 1 || q[0].ID != "0x301" {
		t.Fatalf("qualifying = %+v, want only the AAC stream", q)
	}
	for _, a := range []Audio{
		{Codec: "", Channels: 2, SampleRate: 48000},
		{Codec: "unknown", Channels: 2, SampleRate: 48000},
		{Codec: "none", Channels: 2, SampleRate: 48000},
		{Codec: "mp2", Channels: 0, SampleRate: 48000},
		{Codec: "mp2", Channels: 2, SampleRate: 0},
	} {
		if a.Qualifies() {
			t.Errorf("%+v qualifies", a)
		}
	}
}

// Ruling R28 (Refs #525): ffprobe's field_order is kept as three states. Only
// tt, bb, tb or bt is interlaced; "unknown" -- what ffprobe reports for a
// progressive HEVC stream in a transport stream -- stays a distinct third
// state, is never folded into interlaced, and is treated as progressive:
// no deinterlace, and R is the frame rate.
func TestFieldOrderUnknownIsADistinctStateTreatedAsProgressive(t *testing.T) {
	for value, want := range map[string]FieldOrder{
		"progressive": FieldProgressive,
		"tt":          FieldInterlaced, "bb": FieldInterlaced, "tb": FieldInterlaced, "bt": FieldInterlaced,
		"unknown": FieldUnknown, "": FieldUnknown,
	} {
		if got := parseFieldOrder(value); got != want {
			t.Errorf("field_order %q = %v, want %v", value, got, want)
		}
	}
	if FieldUnknown == FieldInterlaced || FieldUnknown == FieldProgressive {
		t.Fatalf("unknown is folded into another state")
	}
	hevc := Probe{Video: &Video{Codec: "hevc", Width: 640, Height: 360, FrameRate: Rational{25, 1}, Field: FieldUnknown}}
	out, err := Decide(hevc)
	if err != nil {
		t.Fatalf("Decide: %v", err)
	}
	if out.FrameRate != (Rational{25, 1}) || out.GOP != 50 {
		t.Errorf("an unknown field order gave R=%v G=%d, want the frame rate, 25/1 and 50", out.FrameRate, out.GOP)
	}
	plan := PlanGeneration(out, hevc, EngineSoftware)
	if plan.Deinterlace || strings.Contains(strings.Join(out.Argv(plan, DefaultDevice), " "), "bwdif") {
		t.Errorf("an unknown field order was deinterlaced")
	}
	for _, s := range []FieldOrder{FieldUnknown, FieldProgressive, FieldInterlaced} {
		if s.String() == "" {
			t.Errorf("%d has no name", s)
		}
	}
}

func TestParseRational(t *testing.T) {
	for value, ok := range map[string]bool{"25/1": true, "30000/1001": true, "0/0": false, "25": false, "a/b": false, "-1/2": false} {
		if _, got := parseRational(value); got != ok {
			t.Errorf("parseRational(%q) ok = %t, want %t", value, got, ok)
		}
	}
	if (Rational{}).Float() != 0 || (Rational{30000, 1001}).String() != "30000/1001" {
		t.Errorf("Rational formatting")
	}
	p, _ := ParseProbe([]byte(`{"streams":[{"codec_type":"video","width":2,"height":2,"r_frame_rate":"0/0","avg_frame_rate":"50/1"},{"codec_type":"video","width":4}]}`))
	if p.Video.FrameRate != (Rational{50, 1}) || p.Video.Width != 2 {
		t.Errorf("the average rate is the fallback and the first video stream wins: %+v", p.Video)
	}
}

// Ruling R30: every generation is probed at 3 s / 3,000,000 bytes first, and
// the encoder's input analysis matches the bound its probe succeeded with.
func TestTheProbeBoundsAndTheEncodersInputAnalysis(t *testing.T) {
	if got := joinArgs(ProbeArgv(QuickProbe)); got != "-hide_banner -loglevel error -probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0 -show_streams -of json" {
		t.Errorf("the quick probe's argv = %q", got)
	}
	if got := joinArgs(ProbeArgv(FullProbe)); got != "-hide_banner -loglevel error -probesize 5000000 -analyzeduration 8000000 -f mpegts -i pipe:0 -show_streams -of json" {
		t.Errorf("the full probe's argv = %q", got)
	}
	v := video(640, 360, Rational{25, 1}, FieldProgressive)
	o, _ := Decide(Probe{Video: v})
	plan := PlanGeneration(o, Probe{Video: v}, EngineSoftware)
	plan.Input = FullProbe
	if got := joinArgs(o.Argv(plan, DefaultDevice)); !strings.Contains(got, "-probesize 5000000 -analyzeduration 8000000 -f mpegts -i pipe:0") {
		t.Errorf("an encoder after a full re-probe does not analyse its input at the full bound:\n%s", got)
	}
}

// R30's re-probe decision: only video found without its geometry or its
// field order, and only when more bytes were there to read -- never at a
// boundary or the ring's close, where a longer probe reads the same bytes.
func TestTheReprobeDecision(t *testing.T) {
	complete, _ := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
	noGeometry, _ := ParseProbe([]byte(`{"streams":[{"codec_type":"video","codec_name":"h264","width":0,"height":0,"id":"0x100"}]}`))
	noField, _ := ParseProbe([]byte(`{"streams":[{"codec_type":"video","codec_name":"h264","width":640,"height":360,"id":"0x100"}]}`))
	hevcUnknown, _ := ParseProbe([]byte(`{"streams":[{"codec_type":"video","codec_name":"hevc","width":640,"height":360,"field_order":"unknown","id":"0x400"}]}`))
	noVideo, _ := ParseProbe([]byte(probeAudioOnly))
	cases := []struct {
		name  string
		probe Probe
		end   feedEnd
		want  bool
	}{
		{"complete video", complete, feedLimit, false},
		{"no width or height, bound reached", noGeometry, feedLimit, true},
		{"no field order, ffprobe finished first", noField, feedWriteFailed, true},
		{"no field order, wall-clock bound reached", noField, feedStopped, true},
		{"HEVC reporting unknown is complete (R28)", hevcUnknown, feedLimit, false},
		{"incomplete, but the feed ended at a boundary", noGeometry, feedBoundary, false},
		{"incomplete, but the ring closed", noField, feedClosed, false},
		{"no video at all", noVideo, feedLimit, false},
	}
	for _, c := range cases {
		for _, mode := range []Mode{ModeTranscode, ModeAutomatic} {
			want := c.want
			if mode == ModeAutomatic && c.probe.Video != nil && c.end != feedBoundary && c.end != feedClosed {
				want = true // automatic mode also re-probes on fewer than two keyframes (none counted here)
			}
			if got := needsFullProbe(c.probe, feedResult{end: c.end}, mode); got != want {
				t.Errorf("%s, mode %d: needsFullProbe = %t, want %t", c.name, mode, got, want)
			}
		}
	}
	// Ruling R37: automatic mode re-probes a complete video with fewer than
	// two keyframes in the window, so a keyframe interval above 3 s (the
	// copy rule allows 6 s) is still seen; the default re-encode never does.
	oneKeyframe, twoKeyframes := complete, complete
	oneKeyframe.Keyframes, twoKeyframes.Keyframes = 1, 2
	for _, c := range []struct {
		name  string
		probe Probe
		mode  Mode
		want  bool
	}{
		{"automatic, one keyframe", oneKeyframe, ModeAutomatic, true},
		{"automatic, two keyframes", twoKeyframes, ModeAutomatic, false},
		{"transcode, one keyframe", oneKeyframe, ModeTranscode, false},
	} {
		if got := needsFullProbe(c.probe, feedResult{end: feedLimit}, c.mode); got != c.want {
			t.Errorf("%s: needsFullProbe = %t, want %t", c.name, got, c.want)
		}
	}
}
