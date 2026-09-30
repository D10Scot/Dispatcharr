package hls

import (
	"fmt"
	"strings"
	"testing"
	"time"
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

// THE AUTOMATIC PROBE'S ARGV IS ONE LITERAL PER CASE, never the function under
// test's own output: it adds -read_intervals (so ffprobe stops after that much
// media instead of waiting for stdin's EOF, R77) and the packet entries to the
// transcode probe, and transcode's stays byte for byte what it was.
func TestTheAutomaticProbeArgvListsVideoPackets(t *testing.T) {
	quick := "-hide_banner -loglevel error -probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0 -read_intervals %+3 -show_streams -show_entries packet=stream_index,pts_time,flags,size -of json"
	if got := joinArgs(ProbeArgvFor(QuickProbe, ModeAutomatic)); got != quick {
		t.Errorf("the quick automatic probe's argv = %q, want %q", got, quick)
	}
	full := "-hide_banner -loglevel error -probesize 5000000 -analyzeduration 8000000 -f mpegts -i pipe:0 -read_intervals %+8 -show_streams -show_entries packet=stream_index,pts_time,flags,size -of json"
	if got := joinArgs(ProbeArgvFor(FullProbe, ModeAutomatic)); got != full {
		t.Errorf("the full automatic probe's argv = %q, want %q", got, full)
	}
	transcode := "-hide_banner -loglevel error -probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0 -show_streams -of json"
	if got := joinArgs(ProbeArgvFor(QuickProbe, ModeTranscode)); got != transcode {
		t.Errorf("transcode's probe argv changed: %q, want %q", got, transcode)
	}
}

const probeJSONWithPackets = `{"streams": [
 {"index": 0, "codec_name": "hevc", "profile": "Main", "level": 123, "codec_type": "video", "width": 640, "height": 360,
  "pix_fmt": "yuv420p", "r_frame_rate": "25/1", "id": "0x100"},
 {"index": 1, "codec_name": "aac", "profile": "LC", "codec_type": "audio", "sample_rate": "48000", "channels": 2,
  "id": "0x101"}],
 "packets": [
 {"stream_index": 0, "pts_time": "1.480000", "flags": "K__", "size": "400000"},
 {"stream_index": 1, "pts_time": "1.500000", "flags": "K__", "size": "500000"},
 {"stream_index": 0, "pts_time": "5.480000", "flags": "K__", "size": "300000"},
 {"stream_index": 0, "pts_time": "9.480000", "flags": "K__", "size": "200000"},
 {"stream_index": 0, "pts_time": "9.480000", "flags": "___", "size": "100000"},
 {"stream_index": 0, "pts_time": "N/A", "flags": "K__", "size": "1"}
]}`

// A literal window: video key packets at 1.48, 5.48 and 9.48 s plus one non-key
// packet at 9.48 s, 1,000,000 video bytes over an 8.0 s span, and 500,000 audio
// bytes that count in neither total. 8 x 1,000,000 / 8.0 s is 1,000,000 b/s.
func TestParseProbeCountsKeyframesTheirLongestIntervalAndTheRate(t *testing.T) {
	p, err := ParseProbe([]byte(probeJSONWithPackets))
	if err != nil {
		t.Fatalf("ParseProbe: %v", err)
	}
	if p.Keyframes != 3 {
		t.Errorf("Keyframes = %d, want 3 (the audio key packet and the packet with no pts are not counted)", p.Keyframes)
	}
	if p.KeyframeInterval != 4*time.Second {
		t.Errorf("KeyframeInterval = %v, want 4s", p.KeyframeInterval)
	}
	if p.BitRate != 1_000_000 {
		t.Errorf("BitRate = %d, want 1000000 (video only: the 500000 audio bytes are excluded)", p.BitRate)
	}

	// The interval is integer microseconds: a 2.1 s GOP is exactly 2100 ms,
	// where a float difference is 2.0999999...s and would round the wrong way
	// in targetFor.
	two, _ := ParseProbe([]byte(`{"streams":[{"index":0,"codec_type":"video","width":2,"height":2}],"packets":[
 {"stream_index":0,"pts_time":"0.000000","flags":"K__","size":"10"},
 {"stream_index":0,"pts_time":"2.100000","flags":"K__","size":"10"}]}`))
	if two.KeyframeInterval != 2100*time.Millisecond {
		t.Errorf("KeyframeInterval = %v, want exactly 2.1s", two.KeyframeInterval)
	}
	// One keyframe has no interval; no video packets and no span give no rate.
	one, _ := ParseProbe([]byte(`{"streams":[{"index":0,"codec_type":"video","width":2,"height":2}],"packets":[{"stream_index":0,"pts_time":"0.000000","flags":"K__","size":"10"}]}`))
	if one.Keyframes != 1 || one.KeyframeInterval != 0 || one.BitRate != 0 {
		t.Errorf("one keyframe over a zero span gave %+v, want 1, 0, 0", one)
	}
	// A negative pts (a B-frame before its keyframe) is read, not dropped.
	neg, _ := ParseProbe([]byte(`{"streams":[{"index":0,"codec_type":"video","width":2,"height":2}],"packets":[
 {"stream_index":0,"pts_time":"-0.040000","flags":"__","size":"1000"},
 {"stream_index":0,"pts_time":"0.960000","flags":"K__","size":"1000"}]}`))
	if neg.BitRate != 16000 {
		t.Errorf("a window from -0.04 s to 0.96 s of 2000 bytes gave %d b/s, want 16000", neg.BitRate)
	}
	// A transcode probe has no packets and leaves the counts at zero.
	plain, _ := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
	if plain.Keyframes != 0 || plain.KeyframeInterval != 0 || plain.BitRate != 0 {
		t.Errorf("a probe with no packets gave %+v, want zero counts", plain)
	}
	for value, want := range map[string]int64{"1.480000": 1_480_000, "2": 2_000_000, "0.5": 500_000, "-0.040000": -40_000, "1.2345678": 1_234_567} {
		if got, ok := parseMicroseconds(value); !ok || got != want {
			t.Errorf("parseMicroseconds(%q) = %d, %t; want %d", value, got, ok, want)
		}
	}
	for _, value := range []string{"N/A", "", "x.5", "1.x"} {
		if _, ok := parseMicroseconds(value); ok {
			t.Errorf("parseMicroseconds(%q) was ok", value)
		}
	}
}

func TestParseProbeReadsLevelIndexAndAudioProfile(t *testing.T) {
	p, err := ParseProbe([]byte(probeJSONWithPackets))
	if err != nil {
		t.Fatal(err)
	}
	if p.Video.Level != 123 || p.Video.Index != 0 {
		t.Errorf("Video.Level, Index = %d, %d; want 123, 0", p.Video.Level, p.Video.Index)
	}
	if len(p.Audio) != 1 || p.Audio[0].Profile != "LC" {
		t.Errorf("Audio = %+v, want profile LC", p.Audio)
	}
	unreported, _ := ParseProbe([]byte(`{"streams":[{"index":3,"codec_type":"video","level":-99,"width":2,"height":2}]}`))
	if unreported.Video.Level != 0 || unreported.Video.Index != 3 {
		t.Errorf("a level of -99 (unreported) gave Level %d, Index %d; want 0, 3", unreported.Video.Level, unreported.Video.Index)
	}
}

// R81 (issue #525): ffprobe 9.0.1's JSON for the hevc-aac fixture, captured
// as printed, carries NO field_order key at all for the HEVC stream. The probe
// is complete on its geometry, its field order is FieldUnknown (treated as
// progressive), and it is not deinterlaced. The exception is HEVC's alone.
const probeJSONHEVCFixture = `{"streams": [{"index": 0, "codec_name": "hevc", "profile": "Main", "codec_type": "video", "width": 640, "height": 360, "pix_fmt": "yuv420p", "level": 63, "id": "0x400", "r_frame_rate": "25/1", "avg_frame_rate": "25/1"}, {"index": 1, "codec_name": "aac", "profile": "LC", "codec_type": "audio", "id": "0x401", "r_frame_rate": "0/0", "avg_frame_rate": "0/0", "sample_rate": "48000", "channels": 2}]}`

func TestAnHEVCProbeWithNoFieldOrderIsCompleteAndProgressive(t *testing.T) {
	p, err := ParseProbe([]byte(probeJSONHEVCFixture))
	if err != nil {
		t.Fatal(err)
	}
	if !p.Video.Complete() {
		t.Fatal("an HEVC probe with geometry and no field_order key is incomplete: every HEVC generation would re-probe")
	}
	if p.Video.Field != FieldUnknown {
		t.Fatalf("Field = %v, want FieldUnknown", p.Video.Field)
	}
	o, _ := Decide(p)
	if PlanGeneration(o, p, EngineSoftware).Deinterlace {
		t.Fatal("an HEVC probe with no field_order was deinterlaced")
	}
	if needsFullProbe(p, feedResult{end: feedLimit}, ModeTranscode) {
		t.Fatal("a complete HEVC probe asked for a re-probe")
	}

	// The exception is scoped to HEVC: the same JSON as H.264 is still
	// incomplete, because ffprobe omits the key until it has decoded a frame.
	h264, _ := ParseProbe([]byte(strings.Replace(probeJSONHEVCFixture, `"hevc"`, `"h264"`, 1)))
	if h264.Video.Complete() {
		t.Fatal("an H.264 probe with no field_order was judged complete")
	}
	if !needsFullProbe(h264, feedResult{end: feedLimit}, ModeTranscode) {
		t.Fatal("an H.264 probe with no field_order did not ask for a re-probe")
	}
}

// Ruling R94 (issue #553): an interlaced source's rate is its avg_frame_rate,
// with r_frame_rate only when avg_frame_rate is missing or 0/0, because
// ffprobe reports an H.264 PAFF stream's r_frame_rate as its FIELD rate (50/1
// for 1080i25), which outputRate doubles again and caps at 60. A progressive
// source, and an unknown field order (R28), keep r_frame_rate first. The
// fallback rows use 29.97, not 25: a missing rate becomes 25 in outputRate,
// so a 25/1 fallback row would pass with the fallback deleted.
func TestAnInterlacedSourcesRateIsItsAverageFrameRate(t *testing.T) {
	cases := []struct {
		name, field, r, avg string
		probed, rate        Rational
		gop                 int
	}{
		{"1080i25 PAFF, r_frame_rate the field rate", "tt", "50/1", "25/1", Rational{25, 1}, Rational{50, 1}, 100},
		{"1080i29.97 PAFF, r_frame_rate the field rate", "bb", "60000/1001", "30000/1001", Rational{30000, 1001}, Rational{60000, 1001}, 120},
		{"1080i25 as the fixtures report it", "tt", "25/1", "25/1", Rational{25, 1}, Rational{50, 1}, 100},
		{"1080i29.97, r_frame_rate the frame rate", "tt", "30000/1001", "30000/1001", Rational{30000, 1001}, Rational{60000, 1001}, 120},
		{"interlaced, avg_frame_rate 0/0", "tt", "30000/1001", "0/0", Rational{30000, 1001}, Rational{60000, 1001}, 120},
		{"interlaced, avg_frame_rate absent", "tt", "30000/1001", "", Rational{30000, 1001}, Rational{60000, 1001}, 120},
		{"progressive keeps r_frame_rate first", "progressive", "50/1", "25/1", Rational{50, 1}, Rational{50, 1}, 100},
		{"an unknown field order keeps r_frame_rate first", "", "50/1", "25/1", Rational{50, 1}, Rational{50, 1}, 100},
	}
	for _, c := range cases {
		stream := `"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "id": "0x300", "r_frame_rate": "` + c.r + `"`
		if c.avg != "" {
			stream += `, "avg_frame_rate": "` + c.avg + `"`
		}
		if c.field != "" {
			stream += `, "field_order": "` + c.field + `"`
		}
		p, err := ParseProbe([]byte(`{"streams": [{` + stream + `}]}`))
		if err != nil {
			t.Fatalf("%s: ParseProbe: %v", c.name, err)
		}
		out, err := Decide(p)
		if err != nil {
			t.Fatalf("%s: Decide: %v", c.name, err)
		}
		if p.Video.FrameRate != c.probed || out.FrameRate != c.rate || out.GOP != c.gop {
			t.Errorf("%s: probed %v, R=%v G=%d; want probed %v, R=%v G=%d",
				c.name, p.Video.FrameRate, out.FrameRate, out.GOP, c.probed, c.rate, c.gop)
			continue
		}
		argv := joinArgs(out.Argv(PlanGeneration(out, p, EngineSoftware), DefaultDevice))
		if !strings.Contains(argv, "fps="+c.rate.String()+",") || !strings.Contains(argv, fmt.Sprintf(" -g %d ", c.gop)) {
			t.Errorf("%s: the argv does not carry fps=%v and -g %d: %q", c.name, c.rate, c.gop, argv)
		}
	}
}
