package hls

import (
	"errors"
	"slices"
	"strings"
	"testing"
)

func video(w, h int, rate Rational, field FieldOrder) *Video {
	return &Video{Codec: "h264", Width: w, Height: h, FrameRate: rate, Field: field}
}

func aud(id, codec string, channels int) Audio {
	return Audio{ID: id, Codec: codec, Channels: channels, SampleRate: 48000}
}

// D8: geometry and frame rate are fixed at generation 0 -- at most 1920x1080,
// never upscaled, R the field rate of an interlaced source capped at 60, G
// round(2R) -- with the bitrate from the output height.
func TestDecideFixesGeometryRateAndBitrate(t *testing.T) {
	cases := []struct {
		name         string
		v            *Video
		w, h         int
		rate         Rational
		gop          int
		bitrate, max int
	}{
		{"1080i25 becomes 1080p50", video(1920, 1080, Rational{25, 1}, FieldInterlaced), 1920, 1080, Rational{50, 1}, 100, 6_000_000, 8_000_000},
		{"576i25 keeps its size", video(720, 576, Rational{25, 1}, FieldInterlaced), 720, 576, Rational{50, 1}, 100, 2_500_000, 3_000_000},
		{"720p50", video(1280, 720, Rational{50, 1}, FieldProgressive), 1280, 720, Rational{50, 1}, 100, 4_000_000, 5_000_000},
		{"1080i29.97 becomes 59.94", video(1920, 1080, Rational{30000, 1001}, FieldInterlaced), 1920, 1080, Rational{60000, 1001}, 120, 6_000_000, 8_000_000},
		{"2160p60 is scaled into 1080", video(3840, 2160, Rational{60, 1}, FieldProgressive), 1920, 1080, Rational{60, 1}, 120, 6_000_000, 8_000_000},
		{"a tall source keeps its aspect", video(1080, 1920, Rational{30, 1}, FieldProgressive), 606, 1080, Rational{30, 1}, 60, 6_000_000, 8_000_000},
		{"100p is capped at 60", video(1280, 720, Rational{100, 1}, FieldProgressive), 1280, 720, Rational{60, 1}, 120, 4_000_000, 5_000_000},
		{"odd sizes are made even", video(719, 481, Rational{25, 1}, FieldProgressive), 718, 480, Rational{25, 1}, 50, 2_500_000, 3_000_000},
		{"an unreadable rate is 25", video(640, 360, Rational{}, FieldProgressive), 640, 360, Rational{25, 1}, 50, 2_500_000, 3_000_000},
	}
	for _, c := range cases {
		o, err := Decide(Probe{Video: c.v})
		if err != nil {
			t.Fatalf("%s: %v", c.name, err)
		}
		if o.Width != c.w || o.Height != c.h || o.FrameRate != c.rate || o.GOP != c.gop || o.VideoBitrate != c.bitrate || o.VideoMaxrate != c.max {
			t.Errorf("%s: %dx%d R=%v G=%d B=%d M=%d, want %dx%d R=%v G=%d B=%d M=%d", c.name,
				o.Width, o.Height, o.FrameRate, o.GOP, o.VideoBitrate, o.VideoMaxrate, c.w, c.h, c.rate, c.gop, c.bitrate, c.max)
		}
	}
	for _, p := range []Probe{{}, {Video: video(0, 0, Rational{25, 1}, FieldProgressive)}} {
		if _, err := Decide(p); !errors.Is(err, ErrNoVideo) {
			t.Errorf("Decide(%+v) = %v, want ErrNoVideo", p, err)
		}
	}
}

func names(o Output) []string {
	var out []string
	for _, r := range o.Audio {
		out = append(out, r.Name+":"+string(rune('0'+r.Channels)))
	}
	return out
}

// Spec § Encoder argv, the rendition set and channel layouts: aac always, at
// 2.0; ac3 when generation 0 has AC-3 or E-AC-3; eac3 when it has E-AC-3;
// each at the source layout clamped to 2.0 or 5.1. Only qualifying streams
// count.
func TestTheRenditionSetComesFromGenerationZero(t *testing.T) {
	v := video(1920, 1080, Rational{25, 1}, FieldInterlaced)
	cases := []struct {
		name  string
		audio []Audio
		want  []string
	}{
		{"no audio at all", nil, []string{"aac:2"}},
		{"AAC only", []Audio{aud("0x101", "aac", 2)}, []string{"aac:2"}},
		{"MP2 only", []Audio{aud("0x201", "mp2", 2)}, []string{"aac:2"}},
		{"AAC and AC-3 5.1", []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6)}, []string{"aac:2", "ac3:6"}},
		{"E-AC-3 5.1 only (R20)", []Audio{aud("0x601", "eac3", 6)}, []string{"aac:2", "ac3:6", "eac3:6"}},
		{"E-AC-3 7.1 clamps to 5.1", []Audio{aud("0x601", "eac3", 8)}, []string{"aac:2", "ac3:6", "eac3:6"}},
		{"AC-3 mono clamps to 2.0", []Audio{aud("0x101", "ac3", 1)}, []string{"aac:2", "ac3:2"}},
		{"AC-3 5.0 clamps to 5.1", []Audio{aud("0x101", "ac3", 5)}, []string{"aac:2", "ac3:6"}},
		{"an empty AC-3 PID declares nothing", []Audio{aud("0x301", "aac", 2), {ID: "0x302", Codec: "ac3"}}, []string{"aac:2"}},
	}
	for _, c := range cases {
		o, _ := Decide(Probe{Video: v, Audio: c.audio})
		if got := names(o); !slices.Equal(got, c.want) {
			t.Errorf("%s: renditions %v, want %v", c.name, got, c.want)
		}
	}
	o, _ := Decide(Probe{Video: v, Audio: []Audio{{ID: "1", Codec: "aac", Channels: 2, SampleRate: 48000, Language: "eng"}}})
	if o.Audio[0].Language != "eng" {
		t.Errorf("the language tag was not kept: %+v", o.Audio)
	}
	if _, ok := o.Declared(RenditionEAC3); ok {
		t.Errorf("eac3 declared without E-AC-3")
	}
	if !slices.Equal(o.Renditions(), []string{"video", "aac"}) {
		t.Errorf("Renditions = %v", o.Renditions())
	}
}

func fills(p Plan) map[string]string {
	out := map[string]string{}
	for name, f := range p.Fills {
		out[name] = f.Kind.String() + ":" + f.Source.ID
	}
	return out
}

// Spec § Encoder argv, rendition filling: every generation fills every
// declared rendition, copying only a stream of the rendition's codec at the
// declared channel count, encoding anything else qualifying, and falling
// back to silence; an undeclared source track is ignored.
func TestEveryGenerationFillsEveryDeclaredRendition(t *testing.T) {
	v := video(1920, 1080, Rational{25, 1}, FieldInterlaced)
	gen0 := Probe{Video: v, Audio: []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6)}}
	o, _ := Decide(gen0)
	cases := []struct {
		name  string
		audio []Audio
		want  map[string]string
	}{
		{"generation 0 itself", gen0.Audio, map[string]string{"aac": "encode:0x301", "ac3": "copy:0x302"}},
		{"an MP2-only source fills ac3 by encoding", []Audio{aud("0x201", "mp2", 2)}, map[string]string{"aac": "encode:0x201", "ac3": "encode:0x201"}},
		{"AC-3 2.0 into a 5.1 declaration is encoded", []Audio{aud("0x101", "ac3", 2)}, map[string]string{"aac": "encode:0x101", "ac3": "encode:0x101"}},
		{"E-AC-3 fills ac3 by encoding", []Audio{aud("0x101", "mp2", 2), aud("0x102", "eac3", 6)}, map[string]string{"aac": "encode:0x101", "ac3": "encode:0x102"}},
		{"no audio is silence everywhere", nil, map[string]string{"aac": "silence:", "ac3": "silence:"}},
	}
	for _, c := range cases {
		got := fills(PlanGeneration(o, Probe{Video: v, Audio: c.audio}, EngineSoftware))
		if len(got) != len(c.want) {
			t.Errorf("%s: fills %v, want %v", c.name, got, c.want)
			continue
		}
		for k, w := range c.want {
			if got[k] != w {
				t.Errorf("%s: %s = %s, want %s", c.name, k, got[k], w)
			}
		}
	}
	// The reverse direction: a later source that adds E-AC-3 declares nothing.
	mp2, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x201", "mp2", 2)}})
	later := PlanGeneration(mp2, Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}}, EngineSoftware)
	if _, ok := later.Fills[RenditionEAC3]; ok || len(later.Fills) != 1 {
		t.Errorf("a later E-AC-3 source changed the rendition set: %v", fills(later))
	}
	// E-AC-3 fills eac3 by copying; a mismatched layout is encoded.
	e, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}})
	if got := fills(PlanGeneration(e, Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}}, EngineSoftware)); got["eac3"] != "copy:0x601" || got["ac3"] != "encode:0x601" || got["aac"] != "encode:0x601" {
		t.Errorf("an E-AC-3 source fills %v", got)
	}
	if got := fills(PlanGeneration(e, Probe{Video: v, Audio: []Audio{aud("0x9", "eac3", 2), aud("0xa", "aac", 2)}}, EngineSoftware)); got["eac3"] != "encode:0x9" {
		t.Errorf("a 2.0 E-AC-3 into a 5.1 declaration: %v", got)
	}
	if got := fills(PlanGeneration(e, Probe{Video: v, Audio: []Audio{aud("0xa", "aac", 2)}}, EngineSoftware)); got["eac3"] != "encode:0xa" {
		t.Errorf("AAC into an eac3 declaration: %v", got)
	}
	for _, k := range []FillKind{FillSilence, FillEncode, FillCopy} {
		if k.String() == "" {
			t.Errorf("%d has no name", k)
		}
	}
}

func argvString(o Output, p Plan) string { return strings.Join(o.Argv(p, DefaultDevice), " ") }

// Spec § Encoder argv: the transcode generation's argv, software and QSV.
func TestTheArgv(t *testing.T) {
	v := video(1920, 1080, Rational{25, 1}, FieldInterlaced)
	probe := Probe{Video: v, Audio: []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6)}}
	o, _ := Decide(probe)

	sw := PlanGeneration(o, probe, EngineSoftware)
	got := argvString(o, sw)
	for _, want := range []string{
		"-hide_banner -loglevel warning -nostats -fflags +genpts+discardcorrupt -probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0 -map 0:v:0",
		"-vf bwdif=mode=send_field:deint=interlaced,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=50/1,format=yuv420p",
		"-c:v libx264 -preset veryfast -tune zerolatency -profile:v high -level:v 4.2 -b:v 6000000 -maxrate 8000000 -bufsize 8000000 -g 100 -keyint_min 100 -sc_threshold 0",
		"-force_key_frames expr:gte(t,n_forced*2) -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof+negative_cts_offsets pipe:1",
		"-map 0:i:0x301 -c:a aac -ac 2 -b:a 160000 -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:3",
		"-map 0:i:0x302 -c:a copy -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:4",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("the software argv lacks %q:\n%s", want, got)
		}
	}
	for _, never := range []string{"lavfi", "anullsrc", "init_hw_device", "h264_qsv", "pipe:5"} {
		if strings.Contains(got, never) {
			t.Errorf("the software argv carries %q:\n%s", never, got)
		}
	}
	if !slices.Equal(o.Extra(sw), []bool{true, true, false}) {
		t.Errorf("Extra = %v, want fd 3 and fd 4", o.Extra(sw))
	}

	qsv := PlanGeneration(o, probe, EngineQSV)
	got = argvString(o, qsv)
	for _, want := range []string{
		"-init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw -fflags",
		",fps=50/1,format=nv12,hwupload=extra_hw_frames=64",
		"-c:v h264_qsv -preset veryfast -profile:v high -level 42 -b:v 6000000 -maxrate 8000000 -bufsize 8000000 -g 100 -idr_interval 0 -forced_idr 1",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("the QSV argv lacks %q:\n%s", want, got)
		}
	}

	progressive := Probe{Video: video(640, 360, Rational{25, 1}, FieldProgressive), Audio: []Audio{aud("0x601", "eac3", 2)}}
	e, _ := Decide(progressive)
	got = argvString(e, PlanGeneration(e, progressive, EngineSoftware))
	for _, want := range []string{"-vf scale=640:360", "-map 0:i:0x601 -c:a ac3 -ac 2 -b:a 192000", "-map 0:i:0x601 -c:a copy", "pipe:5"} {
		if !strings.Contains(got, want) {
			t.Errorf("the E-AC-3 2.0 argv lacks %q:\n%s", want, got)
		}
	}
	e6, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 6)}})
	got = argvString(e6, PlanGeneration(e6, Probe{Video: v, Audio: []Audio{aud("0x9", "mp2", 2)}}, EngineSoftware))
	for _, want := range []string{"-c:a ac3 -ac 6 -b:a 640000", "-c:a eac3 -ac 6 -b:a 640000"} {
		if !strings.Contains(got, want) {
			t.Errorf("the 5.1 encode argv lacks %q:\n%s", want, got)
		}
	}
	e2, _ := Decide(Probe{Video: v, Audio: []Audio{aud("0x601", "eac3", 2)}})
	if got := argvString(e2, PlanGeneration(e2, Probe{Video: v, Audio: []Audio{aud("0x9", "mp2", 2)}}, EngineSoftware)); !strings.Contains(got, "-c:a eac3 -ac 2 -b:a 256000") {
		t.Errorf("the 2.0 E-AC-3 encode argv:\n%s", got)
	}
}

// Parity: a non-qualifying audio stream is not mapped. The declared-but-empty
// AC-3 PID declares no rendition and appears nowhere in the argv.
func TestANonQualifyingAudioStreamIsNotMapped(t *testing.T) {
	probe, _ := ParseProbe([]byte(probeJSONFor1080iWithAnEmptyAC3))
	o, _ := Decide(probe)
	got := argvString(o, PlanGeneration(o, probe, EngineSoftware))
	if strings.Contains(got, "0x302") || strings.Count(got, "-map") != 2 {
		t.Errorf("the empty AC-3 PID was mapped:\n%s", got)
	}
}

// M8: a rendition filled with silence has no output in the argv at all, and
// no descriptor.
func TestSilenceHasNoOutputInTheArgv(t *testing.T) {
	v := video(640, 360, Rational{25, 1}, FieldProgressive)
	o, _ := Decide(Probe{Video: v})
	plan := PlanGeneration(o, Probe{Video: v}, EngineSoftware)
	got := argvString(o, plan)
	if strings.Contains(got, "pipe:3") || strings.Contains(got, "-map 0:i") || strings.Contains(got, "lavfi") {
		t.Errorf("a silent generation's argv has an audio output:\n%s", got)
	}
	if o.Extra(plan) != nil {
		t.Errorf("a silent generation asks for descriptors: %v", o.Extra(plan))
	}
	if fdFor("nope") != -1 {
		t.Errorf("fdFor of an unknown rendition")
	}
}
