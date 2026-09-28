package hls

import (
	"bytes"
	"errors"
	"testing"
)

func testCanned(spf uint32) *Canned {
	return &Canned{Track: Track{ID: 1, Timescale: 48000}, Frame: []byte{1, 2, 3, 4, 5, 6}, SamplesPerFrame: spf}
}

// Spec § Encoder argv, silence: each silent segment ends at frame index
// ceil(end_ticks x Ta / (Tv x spf)), computed absolutely from the generation's
// first video tfdt in 64-bit integers, so every segment's end is within one
// frame of its video segment's end and the error never accumulates -- over
// an hour of 2 s segments as over one.
func TestSilenceIsExactAndNeverAccumulates(t *testing.T) {
	cases := []struct {
		name    string
		tv      uint32
		segment uint64 // video ticks per segment
		spf     uint32
	}{
		{"AAC against 50p at 12800 Hz", 12800, 25600, 1024},
		{"AC-3 against 50p at 12800 Hz", 12800, 25600, 1536},
		{"AAC against 59.94p at 60000 Hz (2.002 s)", 60000, 120120, 1024},
		{"E-AC-3 against 25p at 90000 Hz", 90000, 180000, 1536},
	}
	for _, c := range cases {
		clock := &silenceClock{canned: testCanned(c.spf), base: 5000}
		var frames uint64
		for i := uint64(1); i <= 1800; i++ {
			end := i * c.segment
			data, ticks := clock.segment(end, c.tv)
			f, err := ParseFragment(data, clock.canned.Track)
			if err != nil {
				t.Fatalf("%s: segment %d does not parse: %v", c.name, i, err)
			}
			if f.Start != 5000+frames*uint64(c.spf) {
				t.Fatalf("%s: segment %d starts at %d, want where the previous one ended", c.name, i, f.Start)
			}
			frames += ticks / uint64(c.spf)
			// |audio end - video end| < one frame, in cross-multiplied ticks.
			audioEnd := frames * uint64(c.spf) * uint64(c.tv)
			videoEnd := end * 48000
			frame := uint64(c.spf) * uint64(c.tv)
			if audioEnd < videoEnd || audioEnd-videoEnd >= frame {
				t.Fatalf("%s: after segment %d the silence ends %+.4f s from its video, want within one frame (%.4f s) and never short",
					c.name, i, (float64(audioEnd)-float64(videoEnd))/float64(uint64(c.tv)*48000), float64(c.spf)/48000)
			}
		}
	}
}

// A segment shorter than one frame still gets one, and the next segment's
// count, computed from the absolute index, takes it back.
func TestSilenceShortSegmentsGetOneFrame(t *testing.T) {
	clock := &silenceClock{canned: testCanned(1024)}
	for i, end := range []uint64{1, 2} {
		if _, ticks := clock.segment(end, 12800); ticks != 1024 {
			t.Fatalf("one-tick segment %d got %d samples, want one frame", i, ticks)
		}
	}
	data, _ := clock.segment(25600, 12800) // to 2.000 s: frame 94
	f, _ := ParseFragment(data, clock.canned.Track)
	if f.Start != 2*1024 || f.Samples != 92 {
		t.Fatalf("the next segment is %d frames from frame %d, want 92 from 2", f.Samples, f.Start/1024)
	}
}

func TestCannedFromNeedsASteadyStateFrame(t *testing.T) {
	track := initSpec{trackID: 1, handler: "soun", timescale: 48000, entry: audioEntry("mp4a", esdsAAC(2)), emptyEdit: 21}.build()
	steady := []byte{9, 9, 9}
	var frags []byte
	for i := 0; i < 6; i++ {
		frags = append(frags, synthFragment(uint32(i+1), 1, uint64(i*1024), steady, 1, 1024)...) // #nosec G115 -- a test's small counts
	}
	c, err := cannedFrom(cat(track, frags))
	if err != nil {
		t.Fatalf("cannedFrom: %v", err)
	}
	if !bytes.Equal(c.Frame, steady) || c.SamplesPerFrame != 1024 || bytes.Contains(c.Init, []byte("edts")) || c.Track.Codec != "mp4a.40.2" {
		t.Errorf("canned = %+v", c)
	}
	var varying []byte
	for i := 0; i < 6; i++ {
		varying = append(varying, synthFragment(uint32(i+1), 1, uint64(i*1024), []byte{byte(i)}, 1, 1024)...) // #nosec G115 -- a test's small counts
	}
	if _, err := cannedFrom(cat(track, varying)); !errors.Is(err, errNoSteadyFrame) {
		t.Errorf("frames that differ gave %v, want errNoSteadyFrame", err)
	}
	if _, err := cannedFrom(track); !errors.Is(err, errNoSteadyFrame) {
		t.Errorf("an encode with no frames gave %v", err)
	}
	if _, err := cannedFrom(box("moof", nil)); err == nil {
		t.Errorf("an encode with no init was accepted")
	}
}

func TestSilenceArgvIsBoundedAndHasNoOtherInput(t *testing.T) {
	argv := SilenceArgv(Rendition{Name: RenditionEAC3, Channels: 6})
	want := "-hide_banner -loglevel error -f lavfi -i anullsrc=r=48000:cl=5.1 -t 1 -c:a eac3 -ac 6 -b:a 640000 -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:1"
	if got := joinArgs(argv); got != want {
		t.Errorf("SilenceArgv = %q, want %q", got, want)
	}
	if got := joinArgs(SilenceArgv(Rendition{Name: RenditionAAC, Channels: 2})); got != "-hide_banner -loglevel error -f lavfi -i anullsrc=r=48000:cl=stereo -t 1 -c:a aac -ac 2 -b:a 160000 -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:1" {
		t.Errorf("SilenceArgv(aac) = %q", got)
	}
}
