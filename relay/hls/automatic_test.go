package hls

import (
	"context"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

// copyProbe is a probe that copyEligible accepts: H.264 High 8-bit 4:2:0
// progressive, 640x360 at 25/1, two keyframes 2 s apart. A row of a table
// changes the one thing it is about.
func copyProbe(mutate func(*Probe)) Probe {
	p := Probe{
		Video: &Video{
			ID: "0x100", Codec: "h264", Profile: "High", PixFmt: "yuv420p", Level: 30,
			Width: 640, Height: 360, FrameRate: Rational{25, 1}, Field: FieldProgressive, fieldReported: true,
		},
		Audio:            []Audio{{ID: "0x101", Codec: "aac", Profile: "LC", Channels: 2, SampleRate: 48000}},
		Keyframes:        2,
		KeyframeInterval: 2 * time.Second,
		BitRate:          2_000_000,
	}
	if mutate != nil {
		mutate(&p)
	}
	return p
}

// Spec § Automatic generation: the copy rule at generation 0, on one probe.
// Every failure names the row, the reason it expected and the reason it got.
func TestTheAutomaticCopyDecision(t *testing.T) {
	rows := []struct {
		n      int
		name   string
		mutate func(*Probe)
		copy   bool
		reason string
	}{
		{1, "h264 High yuv420p progressive 640x360 25/1 K 2s", nil, true, ""},
		{2, "HEVC Main yuv420p, field_order unknown (R28, #525)", func(p *Probe) {
			p.Video.Codec, p.Video.Profile, p.Video.Field = "hevc", "Main", FieldUnknown
		}, true, ""},
		{3, "HEVC Main progressive", func(p *Probe) { p.Video.Codec, p.Video.Profile = "hevc", "Main" }, true, ""},
		{4, "h264 tt", func(p *Probe) { p.Video.Field = FieldInterlaced }, false, "field_order"},
		{5, "mpeg2video", func(p *Probe) { p.Video.Codec, p.Video.Profile = "mpeg2video", "Main" }, false, "codec"},
		{6, "HEVC Main 10 yuv420p10le", func(p *Probe) {
			p.Video.Codec, p.Video.Profile, p.Video.PixFmt = "hevc", "Main 10", "yuv420p10le"
		}, false, "bit_depth"},
		{7, "HEVC Rext", func(p *Probe) { p.Video.Codec, p.Video.Profile = "hevc", "Rext" }, false, "profile"},
		{8, "h264 High 10", func(p *Probe) { p.Video.Profile, p.Video.PixFmt = "High 10", "yuv420p10le" }, false, "profile"},
		{9, "h264 yuv422p", func(p *Probe) { p.Video.PixFmt = "yuv422p" }, false, "bit_depth"},
		{10, "K 6.0 s", func(p *Probe) { p.KeyframeInterval = 6 * time.Second }, true, ""},
		{11, "K 6.5 s", func(p *Probe) { p.KeyframeInterval = 6500 * time.Millisecond }, false, "keyframe_interval"},
		{12, "1 keyframe", func(p *Probe) { p.Keyframes, p.KeyframeInterval = 1, 0 }, false, "keyframes"},
		{13, "3840x2160", func(p *Probe) { p.Video.Width, p.Video.Height = 3840, 2160 }, false, "geometry"},
		{14, "120/1", func(p *Probe) { p.Video.FrameRate = Rational{120, 1} }, false, "frame_rate"},
		{15, "an unreadable frame rate", func(p *Probe) { p.Video.FrameRate = Rational{} }, false, "frame_rate"},
		{16, "yuvj420p is 8-bit 4:2:0", func(p *Probe) { p.Video.PixFmt = "yuvj420p" }, true, ""},
		{17, "Constrained Baseline", func(p *Probe) { p.Video.Profile = "Constrained Baseline" }, true, ""},
		{18, "H.264 High 4:2:2", func(p *Probe) { p.Video.Profile = "High 4:2:2" }, false, "profile"},
		{19, "1920x1080 at 60/1 is the limit", func(p *Probe) {
			p.Video.Width, p.Video.Height, p.Video.FrameRate = 1920, 1080, Rational{60, 1}
		}, true, ""},
	}
	for _, r := range rows {
		ok, reason := copyEligible(copyProbe(r.mutate))
		if ok != r.copy || reason != r.reason {
			t.Errorf("row %d (%s): want copy=%t reason=%q, got copy=%t reason=%q", r.n, r.name, r.copy, r.reason, ok, reason)
		}
	}
	if ok, reason := copyEligible(Probe{}); ok || reason != "codec" {
		t.Errorf("a probe with no video: copy=%t reason=%q, want false codec", ok, reason)
	}
}

// RFC 8216 § 4.3.3.1 rounds EXTINF, so the target is max(2, ceil(K - 0.1 s)):
// a 2.002 s GOP keeps a target of 2 where ceil(K) would give 3 (R61).
func TestTheAutomaticTargetDuration(t *testing.T) {
	for _, c := range []struct {
		k    time.Duration
		want int
	}{
		{1000 * time.Millisecond, 2},
		{2000 * time.Millisecond, 2},
		{2002 * time.Millisecond, 2},
		{2090 * time.Millisecond, 2},
		{2100 * time.Millisecond, 2},
		{2110 * time.Millisecond, 3},
		{3000 * time.Millisecond, 3},
		{4000 * time.Millisecond, 4},
		{5950 * time.Millisecond, 6},
		{6000 * time.Millisecond, 6},
	} {
		if got := targetFor(c.k); got != c.want {
			t.Errorf("K %v: target %d, want %d", c.k, got, c.want)
		}
	}
	if MaxTargetDuration != targetFor(MaxKeyframeInterval) {
		t.Errorf("MaxTargetDuration %d is not the target of the longest K", MaxTargetDuration)
	}
}

// A later generation copies only against the run's fixed output (R60, R75).
// The output here is from copied h264 1280x720 at 50/1 with a 4 Mb/s window,
// Target 2 and Level 42; each row changes one thing.
func TestALaterGenerationCopiesOnlyAgainstTheFixedOutput(t *testing.T) {
	gen0 := copyProbe(func(p *Probe) {
		p.Video.Width, p.Video.Height, p.Video.FrameRate = 1280, 720, Rational{50, 1}
		p.BitRate = 4_000_000
	})
	out, err := DecideFor(gen0, ModeAutomatic)
	if err != nil {
		t.Fatal(err)
	}
	if out.Target != 2 || out.Level != 42 || out.Family != FamilyH264 || out.VideoMaxrate != 5_000_000 || out.PeakRate != 5_000_000 {
		t.Fatalf("the fixed output is %+v", out)
	}
	later := func(mutate func(*Probe)) Probe {
		return copyProbe(func(p *Probe) {
			p.Video.Width, p.Video.Height, p.Video.FrameRate = 1280, 720, Rational{50, 1}
			p.BitRate = 4_000_000
			if mutate != nil {
				mutate(p)
			}
		})
	}
	rows := []struct {
		name   string
		p      Probe
		force  bool
		copy   bool
		reason string
	}{
		{"a match", later(nil), false, true, ""},
		{"1920x1080", later(func(p *Probe) { p.Video.Width, p.Video.Height = 1920, 1080 }), false, false, "geometry"},
		{"25/1", later(func(p *Probe) { p.Video.FrameRate = Rational{25, 1} }), false, false, "frame_rate"},
		{"K 4 s", later(func(p *Probe) { p.KeyframeInterval = 4 * time.Second }), false, false, "keyframe_interval"},
		{"HEVC", later(func(p *Probe) { p.Video.Codec, p.Video.Profile = "hevc", "Main" }), false, false, "family"},
		{"level 51", later(func(p *Probe) { p.Video.Level = 51 }), false, false, "level"},
		{"bitrate 10000000 against a declared peak of 5000000", later(func(p *Probe) { p.BitRate = 10_000_000 }), false, false, "bitrate"},
		{"bitrate 4500000: its average is within, its 1.25x peak (5625000) is not", later(func(p *Probe) { p.BitRate = 4_500_000 }), false, false, "bitrate"},
		{"interlaced", later(func(p *Probe) { p.Video.Field = FieldInterlaced }), false, false, "field_order"},
		{"forceEncode", later(nil), true, false, "forced"},
	}
	for _, r := range rows {
		copied, reason := out.VideoDecision(r.p, r.force)
		if copied != r.copy || reason != r.reason {
			t.Errorf("%s: want copy=%t reason=%q, got copy=%t reason=%q", r.name, r.copy, r.reason, copied, reason)
		}
	}
	// A run whose first generation was encoded may copy a later one on the
	// same conditions: its output is Decide's own, at target 2.
	encoded, _ := DecideFor(copyProbe(func(p *Probe) { p.Video.Field = FieldInterlaced }), ModeAutomatic)
	if encoded.Family != FamilyH264 || encoded.Target != 2 || encoded.Level != 42 {
		t.Fatalf("an encoded generation 0 fixed %+v", encoded)
	}
}

// DecideFor for a copy: the source's own geometry and rate, its family, the
// target from K, the level and the declared bandwidth from the probe.
func TestDecideForACopiedGenerationZero(t *testing.T) {
	p := copyProbe(func(p *Probe) {
		p.Video.Codec, p.Video.Profile, p.Video.Level = "hevc", "Main", 93
		p.Video.Width, p.Video.Height, p.Video.FrameRate = 1279, 719, Rational{30000, 1001}
		p.KeyframeInterval = 4 * time.Second
		p.BitRate = 9_000_000
	})
	out, err := DecideFor(p, ModeAutomatic)
	if err != nil {
		t.Fatal(err)
	}
	if out.Width != 1279 || out.Height != 719 || out.FrameRate != (Rational{30000, 1001}) {
		t.Errorf("a copy keeps the source's own size and rate: %dx%d %v", out.Width, out.Height, out.FrameRate)
	}
	if out.Family != FamilyHEVC || out.Target != 4 || out.Level != 123 || !out.Automatic {
		t.Errorf("family %v target %d level %d automatic %t; want hevc 4 123 true", out.Family, out.Target, out.Level, out.Automatic)
	}
	// 1.25 x 9,000,000 and 9,000,000 exceed the 720p table's 5,000,000 and 4,000,000.
	if out.PeakRate != 11_250_000 || out.AverageRate != 9_000_000 {
		t.Errorf("PeakRate %d AverageRate %d; want 11250000 and 9000000", out.PeakRate, out.AverageRate)
	}
	// Level: max(the source's, the family's).
	high := copyProbe(func(p *Probe) { p.Video.Level = 51 })
	if o, _ := DecideFor(high, ModeAutomatic); o.Level != 51 {
		t.Errorf("a level 51 source declared level %d, want 51", o.Level)
	}
	if _, err := DecideFor(Probe{}, ModeAutomatic); err == nil {
		t.Errorf("DecideFor accepted a probe with no video")
	}
}

// Transcode is unchanged: DecideFor is Decide with a target of 2 and the
// table's own rates, and never copies.
func TestDecideForKeepsTranscodeUnchanged(t *testing.T) {
	probes := []Probe{
		copyProbe(nil),
		{Video: video(1920, 1080, Rational{25, 1}, FieldInterlaced), Audio: []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6)}},
	}
	for _, p := range probes {
		want, _ := Decide(p)
		got, err := DecideFor(p, ModeTranscode)
		if err != nil {
			t.Fatal(err)
		}
		if got.Width != want.Width || got.Height != want.Height || got.FrameRate != want.FrameRate || got.GOP != want.GOP ||
			got.VideoBitrate != want.VideoBitrate || got.VideoMaxrate != want.VideoMaxrate || !slices.Equal(got.Audio, want.Audio) {
			t.Errorf("transcode's output moved: %+v, want %+v", got, want)
		}
		if got.Target != 2 || got.PeakRate != want.VideoMaxrate || got.AverageRate != want.VideoBitrate || got.Automatic || got.Family != FamilyH264 {
			t.Errorf("transcode's target/rates/flags: %+v", got)
		}
		plan := PlanGeneration(got, p, EngineSoftware)
		if plan.VideoCopy || plan.Engine != EngineSoftware {
			t.Errorf("transcode planned a copy: %+v", plan)
		}
	}
}

func TestTheAutomaticAudioFills(t *testing.T) {
	out, _ := DecideFor(copyProbe(nil), ModeAutomatic)
	audio := func(a ...Audio) Probe { return copyProbe(func(p *Probe) { p.Audio = a }) }
	rows := []struct {
		name string
		p    Probe
		want string
	}{
		{"AAC LC stereo is copied", audio(Audio{ID: "0x1", Codec: "aac", Profile: "LC", Channels: 2, SampleRate: 48000}), "copy:0x1"},
		{"AAC LC 6 channels is encoded", audio(Audio{ID: "0x1", Codec: "aac", Profile: "LC", Channels: 6, SampleRate: 48000}), "encode:0x1"},
		{"HE-AAC stereo is encoded", audio(Audio{ID: "0x1", Codec: "aac", Profile: "HE-AAC", Channels: 2, SampleRate: 48000}), "encode:0x1"},
		{"MP2 is encoded", audio(Audio{ID: "0x1", Codec: "mp2", Channels: 2, SampleRate: 48000}), "encode:0x1"},
		{"no audio is silence", audio(), "silence:"},
	}
	for _, r := range rows {
		plan := PlanAutomatic(out, r.p, EngineSoftware, 0, false)
		if got := fills(plan)["aac"]; got != r.want {
			t.Errorf("%s: aac filled %q, want %q", r.name, got, r.want)
		}
	}
	// ac3 and eac3 are PlanGeneration's, exactly.
	gen0 := Probe{Video: copyProbe(nil).Video, Keyframes: 2, KeyframeInterval: 2 * time.Second,
		Audio: []Audio{aud("0x301", "aac", 2), aud("0x302", "ac3", 6), aud("0x303", "eac3", 6)}}
	o, _ := DecideFor(gen0, ModeAutomatic)
	for _, name := range []string{"ac3", "eac3"} {
		if got, want := fills(PlanAutomatic(o, gen0, EngineSoftware, 0, false))[name], fills(PlanGeneration(o, gen0, EngineSoftware))[name]; got != want {
			t.Errorf("%s: automatic %q, transcode %q; want the same", name, got, want)
		}
	}
}

func TestPlanAutomaticChoosesTheEngineAndTheFamily(t *testing.T) {
	out, _ := DecideFor(copyProbe(nil), ModeAutomatic)
	copyPlan := PlanAutomatic(out, copyProbe(nil), EngineQSV, 0, false)
	if !copyPlan.VideoCopy || copyPlan.Engine != EngineCopy || copyPlan.Deinterlace {
		t.Errorf("a copyable source planned %+v", copyPlan)
	}
	interlaced := copyProbe(func(p *Probe) { p.Video.Field = FieldInterlaced })
	encodePlan := PlanAutomatic(out, interlaced, EngineQSV, 0, false)
	if encodePlan.VideoCopy || encodePlan.Engine != EngineQSV || !encodePlan.Deinterlace {
		t.Errorf("an interlaced source planned %+v", encodePlan)
	}
	forced := PlanAutomatic(out, copyProbe(nil), EngineSoftware, 0, true)
	if forced.VideoCopy || forced.Engine != EngineSoftware {
		t.Errorf("a forced encode planned %+v", forced)
	}
}

// The copy argv: no device even when the engine passed in is Quick Sync, no
// filter, `-c:v copy`, hvc1 for HEVC only, the video output's own movflags,
// and an AAC copy through the bitstream filter.
func TestTheCopyArgv(t *testing.T) {
	hevc := copyProbe(func(p *Probe) { p.Video.Codec, p.Video.Profile = "hevc", "Main" })
	out, _ := DecideFor(hevc, ModeAutomatic)
	plan := PlanAutomatic(out, hevc, EngineQSV, 0, false)
	got := joinArgs(out.Argv(plan, DefaultDevice))
	want := "-hide_banner -loglevel warning -nostats -fflags +genpts+discardcorrupt -probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0" +
		" -map 0:v:0 -c:v copy -tag:v hvc1 -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof+negative_cts_offsets pipe:1" +
		" -map 0:i:0x101 -c:a copy -bsf:a aac_adtstoasc -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:3"
	if got != want {
		t.Errorf("the HEVC copy argv:\n got %s\nwant %s", got, want)
	}
	for _, banned := range []string{"-init_hw_device", "-vf", "-force_key_frames", "libx26"} {
		if strings.Contains(got, banned) {
			t.Errorf("the copy argv carries %q", banned)
		}
	}
	h264 := copyProbe(nil)
	o264, _ := DecideFor(h264, ModeAutomatic)
	if a := joinArgs(o264.Argv(PlanAutomatic(o264, h264, EngineSoftware, 0, false), DefaultDevice)); strings.Contains(a, "-tag:v") || !strings.Contains(a, "-c:v copy") {
		t.Errorf("the H.264 copy argv is wrong: %s", a)
	}
	// A hand-built plan that says QSV and copy still opens no device.
	if a := joinArgs(o264.Argv(Plan{Engine: EngineQSV, VideoCopy: true, Fills: map[string]Fill{}}, DefaultDevice)); strings.Contains(a, "-init_hw_device") {
		t.Errorf("a copy plan on QSV opened a device: %s", a)
	}
}

// The HEVC-family encode, in full: what an HEVC run's later generation is
// encoded with. The QSV literal is unrun on hardware (Q1); the software one
// was measured on ffmpeg 9.0.1.
func TestTheHEVCFamilyArgv(t *testing.T) {
	hevc := copyProbe(func(p *Probe) { p.Video.Codec, p.Video.Profile = "hevc", "Main" })
	out, _ := DecideFor(hevc, ModeAutomatic)
	mpeg2 := copyProbe(func(p *Probe) { p.Video.Codec, p.Video.Profile = "mpeg2video", "Main" })
	prefix := "-hide_banner -loglevel warning -nostats "
	in := "-fflags +genpts+discardcorrupt -probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0 -map 0:v:0 "
	tail := " -force_key_frames expr:gte(t,n_forced*2) -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof+negative_cts_offsets pipe:1" +
		" -map 0:i:0x101 -c:a copy -bsf:a aac_adtstoasc -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:3"
	software := prefix + in + "-vf scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,fps=25/1,format=yuv420p" +
		" -c:v libx265 -preset ultrafast -x265-params keyint=50:min-keyint=50:scenecut=0:level-idc=4.1:log-level=error -b:v 2500000 -maxrate 3000000 -bufsize 3000000 -tag:v hvc1" + tail
	if got := joinArgs(out.Argv(PlanAutomatic(out, mpeg2, EngineSoftware, 1, false), DefaultDevice)); got != software {
		t.Errorf("the libx265 argv:\n got %s\nwant %s", got, software)
	}
	qsv := prefix + "-init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw " + in +
		"-vf scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,fps=25/1,format=nv12,hwupload=extra_hw_frames=64" +
		" -c:v hevc_qsv -preset veryfast -profile:v main -level 41 -b:v 2500000 -maxrate 3000000 -bufsize 3000000 -g 50 -idr_interval 0 -forced_idr 1 -tag:v hvc1" + tail
	if got := joinArgs(out.Argv(PlanAutomatic(out, mpeg2, EngineQSV, 1, false), DefaultDevice)); got != qsv {
		t.Errorf("the hevc_qsv argv:\n got %s\nwant %s", got, qsv)
	}
	if strings.Contains(software, "libx264") || strings.Contains(qsv, "h264_qsv") {
		t.Fatal("the literals name an H.264 encoder")
	}
}

// The declared CODECS is the family's ceiling: an H.264 string becomes High at
// the higher of its level and the declared one, an HEVC string keeps every
// field but a level raised to the declared one, and anything else is left.
func TestTheDeclaredVideoCodecIsTheFamilyCeiling(t *testing.T) {
	h264, hevc := Output{Level: 42}, Output{Level: 123}
	for _, c := range []struct {
		codec string
		out   Output
		want  string
	}{
		{"avc1.4d401e", h264, "avc1.64002a"},
		{"avc1.640033", h264, "avc1.640033"},
		{"avc1.42c01f", h264, "avc1.64002a"},
		{"hvc1.1.6.L93.B0", hevc, "hvc1.1.6.L123.B0"},
		{"hvc1.1.6.L150.90", hevc, "hvc1.1.6.L150.90"},
		{"hvc1.1.6.H93.B0", hevc, "hvc1.1.6.H123.B0"},
		{"hvc1.1.6.L93", hevc, "hvc1.1.6.L123"},
		{"mp4a.40.2", h264, "mp4a.40.2"},
		{"garbage", h264, "garbage"},
		{"avc1.zz", h264, "avc1.zz"},
		{"avc1.6400zz", h264, "avc1.6400zz"},
		{"hvc1.1.6", hevc, "hvc1.1.6"},
		{"hvc1.1.6.Lxx", hevc, "hvc1.1.6.Lxx"},
		{"hvc1.1.6.X93", hevc, "hvc1.1.6.X93"},
	} {
		if got := declaredVideoCodec(c.codec, c.out); got != c.want {
			t.Errorf("declaredVideoCodec(%q, level %d) = %q, want %q", c.codec, c.out.Level, got, c.want)
		}
	}
	for _, unreadable := range []string{"mp4a.40.2", "garbage", "avc1.zz", "hvc1.1.6"} {
		if _, ok := ceilingCodec(unreadable, h264); ok {
			t.Errorf("ceilingCodec read %q", unreadable)
		}
	}
}

// hevc_qsv has its own one-frame detection and is written off on its own
// evidence: a stand-in Command records which encoder each detection named.
func TestHEVCDetectionIsItsOwnAnswer(t *testing.T) {
	record := filepath.Join(t.TempDir(), "encoders")
	d := &Detector{
		Device:  device(t),
		Command: script(t, `for a in "$@"; do case "$a" in h264_qsv|hevc_qsv) echo "$a" >> `+record+`;; esac; done; exit 0`),
	}
	ctx := context.Background()
	encoders := func() string { return strings.Join(strings.Fields(string(readFile(t, record))), " ") }

	if got := d.EngineFor(ctx, FamilyHEVC); got != EngineQSV {
		t.Fatalf("EngineFor(HEVC) = %s, want qsv from a passing detection", got)
	}
	if got := encoders(); got != "hevc_qsv" {
		t.Fatalf("the HEVC detection ran %q, want one hevc_qsv encode", got)
	}
	if got := d.Engine(ctx); got != EngineQSV {
		t.Fatalf("Engine = %s, want qsv", got)
	}
	if got := encoders(); got != "hevc_qsv h264_qsv" {
		t.Fatalf("after the H.264 answer the detections ran %q, want hevc_qsv then h264_qsv", got)
	}
	// Cached: neither family detects again.
	d.EngineFor(ctx, FamilyHEVC)
	d.Engine(ctx)
	if got := encoders(); got != "hevc_qsv h264_qsv" {
		t.Fatalf("a cached answer ran the detection again: %q", got)
	}
	// Written off on its own evidence: HEVC's failure leaves H.264's answer.
	d.MarkUnusableFor(FamilyHEVC)
	if got := d.EngineFor(ctx, FamilyHEVC); got != EngineSoftware {
		t.Errorf("a written-off hevc_qsv answered %s, want software", got)
	}
	if got := d.Engine(ctx); got != EngineQSV {
		t.Errorf("writing hevc_qsv off wrote h264_qsv off too: %s", got)
	}
	if usable, conclusive := d.RecheckFor(ctx, FamilyHEVC); !usable || !conclusive {
		t.Errorf("RecheckFor(HEVC) = %t, %t; want the stand-in's passing answer", usable, conclusive)
	}
	if got := DetectArgvFor(DefaultDevice, "hevc_qsv"); !slices.Contains(got, "hevc_qsv") || slices.Contains(got, "h264_qsv") {
		t.Errorf("DetectArgvFor(hevc_qsv) = %v", got)
	}
}
