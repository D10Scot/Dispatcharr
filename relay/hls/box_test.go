package hls

import (
	"bytes"
	"errors"
	"testing"
)

func TestParseInitReadsTheTrackAndItsCodec(t *testing.T) {
	for _, version1 := range []bool{false, true} {
		init := initSpec{trackID: 7, handler: "vide", timescale: 12800, movieTimescale: 1000,
			entry: avc1Entry(0x64, 0x00, 0x2a), trexDuration: 512, trexSize: 99, trexFlags: 0x01010000, version1: version1}.build()
		track, err := ParseInit(init)
		if err != nil {
			t.Fatalf("version1=%t: ParseInit: %v", version1, err)
		}
		want := Track{ID: 7, Handler: "vide", Timescale: 12800, Codec: "avc1.64002a",
			DefaultDuration: 512, DefaultSize: 99, DefaultFlags: 0x01010000}
		if track != want {
			t.Errorf("version1=%t: ParseInit = %+v, want %+v", version1, track, want)
		}
	}
}

func TestCodecStringsComeFromTheInitSegment(t *testing.T) {
	hvcC := box("hvcC", []byte{1, 0x01, 0x60, 0, 0, 0, 0xb0, 0, 0, 0, 0, 0, 93, 0xf0})
	cases := []struct {
		name  string
		entry []byte
		want  string
	}{
		{"H.264 High 4.2", avc1Entry(0x64, 0x00, 0x2a), "avc1.64002a"},
		{"H.264 Main 3.1", avc1Entry(0x4d, 0x40, 0x1f), "avc1.4d401f"},
		{"HEVC Main 3.1", box("hvc1", cat(make([]byte, 78), hvcC)), "hvc1.1.6.L93.B0"},
		{"AAC-LC", audioEntry("mp4a", esdsAAC(2)), "mp4a.40.2"},
		{"HE-AAC", audioEntry("mp4a", esdsAAC(5)), "mp4a.40.5"},
		{"an escaped object type", audioEntry("mp4a", esdsAAC(42)), "mp4a.40.42"},
		{"AC-3", audioEntry("ac-3", box("dac3", []byte{0x10, 0x3d, 0xe0})), "ac-3"},
		{"E-AC-3", audioEntry("ec-3", box("dec3", []byte{0x0a, 0x00, 0x20, 0x0f, 0x00})), "ec-3"},
		{"an unknown sample entry", box("mp4v", make([]byte, 78)), ""},
	}
	for _, c := range cases {
		init := initSpec{trackID: 1, handler: "soun", timescale: 48000, entry: c.entry}.build()
		track, err := ParseInit(init)
		if err != nil {
			t.Fatalf("%s: ParseInit: %v", c.name, err)
		}
		if track.Codec != c.want {
			t.Errorf("%s: CODECS = %q, want %q", c.name, track.Codec, c.want)
		}
	}
}

// ffmpeg records a track's real start as an empty edit (measured, ffmpeg
// 9.0.1); the offset is converted from the movie timescale to the media one,
// less any media_time, and never negative.
func TestStartOffsetIsTheEmptyEditInMediaTicks(t *testing.T) {
	cases := []struct {
		name      string
		movie     uint32
		emptyEdit uint32
		mediaTime int32
		want      uint64
	}{
		{"no edit list", 1000, 0, 0, 0},
		{"0.86 s at a 1000 Hz movie timescale", 1000, 860, 0, 11008},
		{"5.3 ms at a 48 kHz movie timescale", 48000, 256, 0, 68},
		{"a media_time is subtracted", 1000, 860, 1000, 10008},
		// A media_time longer than the empty edit clamps to 0, and the
		// clamp is NOT exact: the track then presents late by the
		// difference, because the edit that corrected it is stripped. That
		// is the B-frame reorder delay ffmpeg records as media_time without
		// +negative_cts_offsets (80 ms measured), which is why the video
		// output carries that flag (R31) and an AAC encoder's priming is the
		// only media_time left (a few milliseconds, presented as it is).
		{"a media_time longer than the delay clamps to 0 (the track presents late by it)", 1000, 0, 1024, 0},
	}
	for _, c := range cases {
		init := initSpec{trackID: 1, handler: "vide", timescale: 12800, movieTimescale: c.movie,
			entry: avc1Entry(0x64, 0, 0x2a), emptyEdit: c.emptyEdit, mediaTime: c.mediaTime}.build()
		track, err := ParseInit(init)
		if err != nil {
			t.Fatalf("%s: %v", c.name, err)
		}
		if track.StartOffset != c.want {
			t.Errorf("%s: StartOffset = %d, want %d", c.name, track.StartOffset, c.want)
		}
	}
}

func TestStripEditsRemovesTheEditListAndFixesTheSizes(t *testing.T) {
	init := initSpec{trackID: 1, handler: "soun", timescale: 48000, movieTimescale: 48000,
		entry: audioEntry("ac-3", box("dac3", []byte{0x10, 0x3d, 0xe0})), emptyEdit: 256}.build()
	stripped, err := StripEdits(init)
	if err != nil {
		t.Fatalf("StripEdits: %v", err)
	}
	if bytes.Contains(stripped, []byte("edts")) || bytes.Contains(stripped, []byte("elst")) {
		t.Fatalf("the stripped init still carries an edit list")
	}
	// edts (8) + elst (8 + 4 + 4) + two 12-byte entries = 48 bytes.
	if len(stripped) != len(init)-48 {
		t.Errorf("stripped %d bytes, want the 48-byte edts gone from %d", len(stripped), len(init))
	}
	track, err := ParseInit(stripped)
	if err != nil {
		t.Fatalf("the stripped init does not parse: %v", err)
	}
	if track.Codec != "ac-3" || track.StartOffset != 0 {
		t.Errorf("stripped init parses as %+v", track)
	}
	if _, err := StripEdits([]byte{0, 0, 0, 3}); err == nil {
		t.Errorf("StripEdits accepted a malformed box")
	}
}

func TestParseInitRefusesWhatIsNotAnInit(t *testing.T) {
	good := initSpec{trackID: 1, handler: "vide", timescale: 12800, entry: avc1Entry(0x64, 0, 0x2a)}.build()
	cases := map[string][]byte{
		"empty":                     nil,
		"no moov":                   box("ftyp", []byte("iso5")),
		"a moov with nothing in it": box("moov", nil),
		"a moov with only an mvhd":  box("moov", fullBoxBytes("mvhd", 0, 0, cat(make([]byte, 8), be32(1000), make([]byte, 84)))),
		"truncated":                 good[:len(good)-20],
	}
	for name, data := range cases {
		if _, err := ParseInit(data); !errors.Is(err, errBox) {
			t.Errorf("%s: ParseInit error = %v, want a malformed-box error", name, err)
		}
	}
}

func TestParseFragmentReadsTheTimingAndTheSyncSample(t *testing.T) {
	track := Track{ID: 1, Timescale: 12800, DefaultDuration: 512}
	f, err := ParseFragment(fragSpec{seq: 1, trackID: 1, start: 25600, durations: []uint32{512, 512, 256}, sync: true}.build(), track)
	if err != nil {
		t.Fatalf("ParseFragment: %v", err)
	}
	if f.Start != 25600 || f.Duration != 1280 || f.Samples != 3 || !f.Sync || f.End() != 26880 {
		t.Errorf("ParseFragment = start %d duration %d samples %d sync %t", f.Start, f.Duration, f.Samples, f.Sync)
	}
	nonSync, err := ParseFragment(fragSpec{seq: 2, trackID: 1, start: 7, durations: []uint32{512}, v0: true}.build(), track)
	if err != nil {
		t.Fatalf("ParseFragment v0: %v", err)
	}
	if nonSync.Sync || nonSync.Start != 7 {
		t.Errorf("a non-sync version-0 fragment parsed as sync=%t start=%d", nonSync.Sync, nonSync.Start)
	}
	if _, err := ParseFragment(fragSpec{seq: 1, trackID: 2, durations: []uint32{1}}.build(), track); !errors.Is(err, errBox) {
		t.Errorf("a fragment for another track was accepted: %v", err)
	}
}

// The defaults a fragment leaves implicit come from tfhd, then trex, and a
// first sample's flags from the trun's first-sample-flags or its own flags.
func TestParseFragmentFallsBackToTheDefaults(t *testing.T) {
	track := Track{ID: 1, Timescale: 48000, DefaultDuration: 1024, DefaultFlags: 0x02000000}
	tfhd := fullBoxBytes("tfhd", 0, 0x020000|tfhdBaseDataOffset|tfhdSampleDescIndex, cat(be32(1), be64(0), be32(1)))
	tfdt := fullBoxBytes("tfdt", 1, 0, be64(48000))
	trun := fullBoxBytes("trun", 0, uint32(trunDataOffset), cat(be32(3), be32(0)))
	frag := cat(box("moof", cat(fullBoxBytes("mfhd", 0, 0, be32(1)), box("traf", cat(tfhd, tfdt, trun)))), box("mdat", nil))
	f, err := ParseFragment(frag, track)
	if err != nil {
		t.Fatalf("ParseFragment: %v", err)
	}
	if f.Duration != 3072 || !f.Sync {
		t.Errorf("trex defaults not applied: duration %d sync %t", f.Duration, f.Sync)
	}
	perSample := fullBoxBytes("trun", 0, uint32(trunFlagsPresent|trunSize|trunCTO|trunDuration), cat(be32(1), be32(100), be32(4), be32(0x01010000), be32(0)))
	tfhdDefaults := fullBoxBytes("tfhd", 0, tfhdDefaultDuration|tfhdDefaultSize|tfhdDefaultFlags, cat(be32(1), be32(9), be32(4), be32(0x02000000)))
	frag = cat(box("moof", box("traf", cat(tfhdDefaults, tfdt, perSample))), box("mdat", make([]byte, 4)))
	f, err = ParseFragment(frag, track)
	if err != nil {
		t.Fatalf("ParseFragment per-sample: %v", err)
	}
	if f.Duration != 100 || f.Sync {
		t.Errorf("per-sample fields not read: duration %d sync %t", f.Duration, f.Sync)
	}
}

func TestParseFragmentRefusesAMalformedFragment(t *testing.T) {
	track := Track{ID: 1}
	good := fragSpec{seq: 1, trackID: 1, durations: []uint32{1, 1}}.build()
	tfhd := fullBoxBytes("tfhd", 0, 0, be32(1))
	tfdt := fullBoxBytes("tfdt", 1, 0, be64(0))
	trun := fullBoxBytes("trun", 0, 0, be32(1))
	cases := map[string][]byte{
		"not a moof":        box("mdat", nil),
		"no traf":           box("moof", nil),
		"no tfhd":           box("moof", box("traf", nil)),
		"a short tfhd":      box("moof", box("traf", fullBoxBytes("tfhd", 0, 0, nil))),
		"no tfdt":           box("moof", box("traf", tfhd)),
		"a short tfdt":      box("moof", box("traf", cat(tfhd, fullBoxBytes("tfdt", 1, 0, be32(0))))),
		"no trun":           box("moof", box("traf", cat(tfhd, tfdt))),
		"a trun that lies":  box("moof", box("traf", cat(tfhd, tfdt, fullBoxBytes("trun", 0, uint32(trunDuration), be32(1000))))),
		"a short trun":      box("moof", box("traf", cat(tfhd, tfdt, box("trun", []byte{0})))),
		"a truncated frag":  good[:40],
		"a sample-less run": box("moof", box("traf", cat(tfhd, tfdt, trun))),
	}
	for name, data := range cases {
		if name == "a sample-less run" {
			if _, err := ParseFragment(data, track); err != nil {
				t.Errorf("%s: %v", name, err)
			}
			continue
		}
		if _, err := ParseFragment(data, track); !errors.Is(err, errBox) {
			t.Errorf("%s: ParseFragment error = %v, want a malformed-box error", name, err)
		}
	}
}

func TestShiftStartMovesTheTfdt(t *testing.T) {
	track := Track{ID: 1, Timescale: 12800}
	f, _ := ParseFragment(fragSpec{seq: 1, trackID: 1, start: 100, durations: []uint32{512}, sync: true}.build(), track)
	if err := shiftStart(&f, 11008); err != nil {
		t.Fatalf("shiftStart: %v", err)
	}
	again, err := ParseFragment(f.Data, track)
	if err != nil || again.Start != 11108 || f.Start != 11108 {
		t.Errorf("after the shift the fragment starts at %d (parsed %d, %v), want 11108", f.Start, again.Start, err)
	}
	if err := shiftStart(&f, 0); err != nil {
		t.Errorf("a zero shift failed: %v", err)
	}
	v0, _ := ParseFragment(fragSpec{seq: 1, trackID: 1, start: 5, durations: []uint32{512}, v0: true}.build(), track)
	if err := shiftStart(&v0, 10); err != nil || v0.Start != 15 {
		t.Errorf("a version-0 shift: start %d, %v", v0.Start, err)
	}
	if err := shiftStart(&v0, 1<<32); !errors.Is(err, errBox) {
		t.Errorf("a version-0 tfdt was allowed to overflow: %v", err)
	}
	noTfdt := Fragment{Data: box("moof", box("traf", nil)), Start: 1}
	if err := shiftStart(&noTfdt, 1); !errors.Is(err, errBox) {
		t.Errorf("a fragment with no tfdt was shifted: %v", err)
	}
}

// A synthesised fragment is exactly what the box reader reads back: count
// copies of the frame, each dur ticks, at start.
func TestSynthFragmentRoundTrips(t *testing.T) {
	frame := []byte{0xde, 0xad, 0xbe, 0xef, 0x01, 0x02}
	data := synthFragment(9, 1, 96000, frame, 94, 1024)
	track := Track{ID: 1, Timescale: 48000}
	f, err := ParseFragment(data, track)
	if err != nil {
		t.Fatalf("ParseFragment: %v", err)
	}
	if f.Start != 96000 || f.Samples != 94 || f.Duration != 94*1024 || !f.Sync {
		t.Errorf("synthesised fragment parses as %+v", f)
	}
	samples, durations, err := fragmentSamples(data, track)
	if err != nil || len(samples) != 94 {
		t.Fatalf("fragmentSamples: %d samples, %v", len(samples), err)
	}
	for i, s := range samples {
		if !bytes.Equal(s, frame) || durations[i] != 1024 {
			t.Fatalf("sample %d is %x (%d ticks), want the frame", i, s, durations[i])
		}
	}
	empty, err := ParseFragment(synthFragment(1, 1, 0, nil, 0, 1024), track)
	if err != nil || empty.Samples != 0 || empty.Sync {
		t.Errorf("an empty synthesised fragment parses as %+v, %v", empty, err)
	}
}
