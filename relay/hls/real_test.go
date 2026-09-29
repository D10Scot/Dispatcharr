package hls

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// The real-ffmpeg tests: the subject is what an encoder makes, so the
// encoder is ffmpeg itself, over the 4a-0 fixtures built by
// e2e-upstream/scripts/make-asset.sh. They are gated as parity row 4's pin
// is (relay/channel/source_transcode_real_test.go): skipped where ffmpeg is
// absent, and a FAILURE under CI, where go-tests.yml's build job runs them
// against the production ffmpeg 9.0 in the base image. Software encoding
// throughout: no CI runner has Quick Sync.

// requireRealFFmpeg finds ffmpeg, ffprobe and bash, refusing to skip under CI.
func requireRealFFmpeg(t *testing.T) {
	t.Helper()
	for _, tool := range []string{"ffmpeg", "ffprobe", "bash"} {
		if _, err := exec.LookPath(tool); err != nil {
			if os.Getenv("CI") != "" {
				t.Fatalf("%s is not on PATH and CI is set: the base image carries it, and these are the packager's only real-encoder pins", tool)
			}
			t.Skipf("%s is not on PATH; the packager's real-ffmpeg tests did NOT run on this host", tool)
		}
	}
}

var (
	fixtureMu  sync.Mutex
	fixtureDir string
	fixtures   = map[string][]byte{}
	// realSilence is shared by every real test, as it is by every pipeline
	// in a relay process: each canned encode runs once per test binary.
	realSilence = &SilenceCache{}
)

// fixture builds (once per test binary) the named 4a-0 fixture with the
// repository's own make-asset.sh, which probes its shape before it returns.
func fixture(t *testing.T, name string) []byte {
	t.Helper()
	fixtureMu.Lock()
	defer fixtureMu.Unlock()
	if data, ok := fixtures[name]; ok {
		return data
	}
	if fixtureDir == "" {
		dir, err := os.MkdirTemp("", "hls-fixtures-")
		if err != nil {
			t.Fatal(err)
		}
		fixtureDir = dir
	}
	script, err := filepath.Abs("../../e2e-upstream/scripts/make-asset.sh")
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(fixtureDir, name+".ts")
	// #nosec G204 -- the repository's own script and a fixed fixture name
	cmd := exec.CommandContext(t.Context(), "bash", script, out, name)
	if msg, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("make-asset.sh %s: %v\n%s", name, err, msg)
	}
	data := readFile(t, out)
	fixtures[name] = data
	return data
}

func TestMain(m *testing.M) {
	code := m.Run()
	if fixtureDir != "" {
		_ = os.RemoveAll(fixtureDir)
	}
	os.Exit(code)
}

// seconds is the first s seconds of a 20 s fixture, by byte proportion and
// cut on a packet boundary: the raw transport stream, PIDs untouched.
func seconds(data []byte, s int) []byte {
	n := len(data) * s / 20
	return data[:n-n%buffer.TSPacketSize]
}

// withoutPID drops every packet of one PID, leaving the PMT that declares it:
// a declared-but-empty audio PID (spec § Encoder argv; 4a-0's hand-off).
func withoutPID(data []byte, pid int) []byte {
	var out []byte
	for i := 0; i+buffer.TSPacketSize <= len(data); i += buffer.TSPacketSize {
		p := data[i : i+buffer.TSPacketSize]
		if int(p[1]&0x1f)<<8|int(p[2]) == pid {
			continue
		}
		out = append(out, p...)
	}
	return out
}

// realRun is one pipeline over real ffmpeg with the given sources, a
// boundary between each, the ring closed at the end, run to completion.
type realRun struct {
	p      *Pipeline
	logs   *logBuffer
	mu     sync.Mutex
	spawns []Spawn
}

func runReal(t *testing.T, sources ...[]byte) *realRun {
	t.Helper()
	return runRealWith(t, nil, sources...)
}

// runRealWith is runReal with a last word on the Config, for automatic mode's
// tests (Phase 4a-1d): the mode, and a probe wrapper that records its argv.
func runRealWith(t *testing.T, configure func(*Config), sources ...[]byte) *realRun {
	t.Helper()
	requireRealFFmpeg(t)
	src := newTestSource()
	for i, s := range sources {
		if i > 0 {
			src.mark()
		}
		src.write(t, s)
	}
	src.ring.Close()
	r := &realRun{logs: &logBuffer{}}
	cfg := Config{
		ChannelID:  "real",
		Source:     src,
		JoinBehind: time.Hour,
		// These tests feed seconds of media at once rather than in real
		// time, so after stdin closes a slow host is still encoding what it
		// has read: under amd64 emulation the 1080i generation was killed
		// mid-flush by the production 5 s grace with three of its six
		// segments published (measured while planning). The grace's own
		// behaviour is the stand-in test's subject
		// (TestAGenerationThatIgnoresItsInputClosingIsKilledAfterTheGrace);
		// here it only has to be longer than any honest flush.
		ExitGrace: 20 * time.Second,
		Detector:  &Detector{Device: filepath.Join(t.TempDir(), "renderD128"), Log: r.logs.logger()},
		Silence:   realSilence,
		Log:       r.logs.logger(),
		Command: func(s Spawn) (string, []string) {
			r.mu.Lock()
			r.spawns = append(r.spawns, s)
			r.mu.Unlock()
			return "ffmpeg", s.Argv
		},
	}
	if configure != nil {
		configure(&cfg)
	}
	p, err := Start(context.Background(), cfg)
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	t.Cleanup(p.Stop)
	select {
	case <-p.Done():
	case <-time.After(3 * time.Minute):
		t.Fatalf("the pipeline did not finish in 3 minutes:\n%s", r.logs.String())
	}
	r.p = p
	return r
}

// ok fails the test if the pipeline ended in an error, with its log.
func (r *realRun) ok(t *testing.T) {
	t.Helper()
	if err := r.p.Err(); err != nil {
		t.Fatalf("the pipeline failed: %v\n%s", err, r.logs.String())
	}
}

// realSegment is one stored segment of one rendition, parsed.
type realSegment struct {
	seq   uint64
	gen   int
	first Fragment
	data  []byte
	dur   float64
}

// segments is every stored segment of a rendition, in order, with the track
// each generation's init describes.
func (r *realRun) segments(t *testing.T, rendition string) ([]realSegment, map[int]Track) {
	t.Helper()
	s := r.p.Store()
	s.mu.Lock()
	defer s.mu.Unlock()
	tracks := map[int]Track{}
	var out []realSegment
	for _, seg := range s.segs {
		p, ok := seg.parts[rendition]
		if !ok {
			t.Fatalf("segment %d (generation %d) has no %s part: the %s rendition stopped growing", seg.seq, seg.gen, rendition, rendition)
		}
		track, ok := tracks[seg.gen]
		if !ok {
			init, found := s.inits[initKey{rendition, seg.gen}]
			if !found {
				t.Fatalf("no %s init for generation %d", rendition, seg.gen)
			}
			var err error
			if track, err = ParseInit(init); err != nil {
				t.Fatalf("%s init-%d: %v", rendition, seg.gen, err)
			}
			tracks[seg.gen] = track
		}
		first, err := ParseFragment(p.data, track)
		if err != nil {
			t.Fatalf("%s segment %d: %v", rendition, seg.seq, err)
		}
		out = append(out, realSegment{seq: seg.seq, gen: seg.gen, first: first, data: p.data, dur: p.duration})
	}
	return out, tracks
}

func (r *realRun) multivariant(t *testing.T) string {
	t.Helper()
	mv, err := r.p.Multivariant("/hls/T")
	if err != nil {
		t.Fatalf("Multivariant: %v", err)
	}
	return string(mv)
}

func (r *realRun) renditions() []string {
	o, _ := r.p.Output()
	return o.Renditions()
}

// Parity: a generation's segments are 2.000 s +/- one frame, each starting
// with a sync sample -- here on 12 s of the 1080i AAC + AC-3 fixture, on
// three renditions, with the CODECS its init segments carry.
func TestRealThe1080iFixtureGivesAligned2sSegmentsOnThreeRenditions(t *testing.T) {
	r := runReal(t, seconds(fixture(t, "h264-1080i-aac-ac3"), 12))
	r.ok(t)
	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3" {
		t.Fatalf("renditions %s, want video,aac,ac3", got)
	}
	mv := r.multivariant(t)
	for _, want := range []string{
		`CODECS="avc1.64002a,mp4a.40.2",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="aac"`,
		`CODECS="avc1.64002a,ac-3",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="ac3"`,
		`GROUP-ID="ac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6"`,
	} {
		if !strings.Contains(mv, want) {
			t.Fatalf("the multivariant lacks %s:\n%s", want, mv)
		}
	}
	video, vtracks := r.segments(t, RenditionVideo)
	if len(video) < 5 {
		t.Fatalf("%d segments from 12 s, want at least 5 whole ones", len(video))
	}
	oneFrame := 1.0 / 50
	for i, v := range video {
		if !v.first.Sync {
			t.Errorf("video segment %d does not start with a sync sample", v.seq)
		}
		if i < len(video)-1 && (v.dur < 2-oneFrame || v.dur > 2+oneFrame) {
			t.Errorf("video segment %d is %.3f s, want 2.000 s +/- one frame", v.seq, v.dur)
		}
	}
	for _, name := range []string{RenditionAAC, RenditionAC3} {
		audio, _ := r.segments(t, name)
		for i, a := range audio {
			v := video[i]
			vstart := float64(v.first.Start) / float64(vtracks[v.gen].Timescale)
			astart := float64(a.first.Start) / 48000
			// An audio fragment is -frag_duration 200 ms rounded up to whole
			// frames: 213 ms of AAC, 224 ms of AC-3. The first one starting
			// in the span is at most one fragment after the span's start.
			if astart < vstart-0.001 || astart-vstart >= 0.225 {
				t.Errorf("%s segment %d starts at %.3f s against its video at %.3f s: more than one audio fragment into the span", name, a.seq, astart, vstart)
			}
			if i < len(audio)-1 && (a.dur-v.dur > 0.25 || v.dur-a.dur > 0.25) {
				t.Errorf("%s segment %d is %.3f s against video %.3f s", name, a.seq, a.dur, v.dur)
			}
		}
	}
}

// PR #529 review (thread on segmenter.go:233): the segment grid does NOT
// need the video's StartOffset to be 0. Joined mid-GOP, the encoder's first
// frame is a keyframe at its own t = 0 and -force_key_frames puts the next
// ones 2 s apart from it (Decision 5); the relay shifts every fragment by the
// same StartOffset (Decision 3), so the keyframes stay 2 s apart, and the
// grid is anchored on the first of them after the shift (segmenter.v0). Here
// the join is 3 MB into the 1080i fixture, where the video's empty edit was
// measured at 0.86 s: the first segment starts well after 0, and every
// whole segment is still 2.000 s.
func TestRealAMidGOPJoinKeepsTheGridOnTheKeyframes(t *testing.T) {
	data := fixture(t, "h264-1080i-aac-ac3")
	cut := 3_000_000 - 3_000_000%buffer.TSPacketSize
	rest := data[cut:]
	n := len(data) * 10 / 20
	r := runReal(t, rest[:n-n%buffer.TSPacketSize])
	r.ok(t)
	video, _ := r.segments(t, RenditionVideo)
	if len(video) < 4 {
		t.Fatalf("%d segments from 10 s, want at least 4 whole ones", len(video))
	}
	if video[0].first.Start == 0 {
		t.Fatalf("the video's first fragment starts at 0 after the shift: the join is no longer mid-GOP, so this test no longer exercises a non-zero StartOffset")
	}
	oneFrame := 1.0 / 50
	for i, v := range video {
		if !v.first.Sync {
			t.Errorf("video segment %d does not start with a sync sample", v.seq)
		}
		if i < len(video)-1 && (v.dur < 2-oneFrame || v.dur > 2+oneFrame) {
			t.Errorf("video segment %d is %.3f s with the video's StartOffset at %d ticks, want 2.000 s +/- one frame: the grid drifted off the keyframes", v.seq, v.dur, video[0].first.Start)
		}
	}
}

// The E-AC-3 fixture gives three audio renditions (R20): AAC and AC-3
// encoded from the E-AC-3, which is copied.
func TestRealTheEAC3FixtureGivesThreeAudioRenditions(t *testing.T) {
	r := runReal(t, seconds(fixture(t, "h264-eac3"), 6))
	r.ok(t)
	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3,eac3" {
		t.Fatalf("renditions %s", got)
	}
	mv := r.multivariant(t)
	for _, want := range []string{`"avc1.64002a,mp4a.40.2"`, `"avc1.64002a,ac-3"`, `"avc1.64002a,ec-3"`, `GROUP-ID="eac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6"`} {
		if !strings.Contains(mv, want) {
			t.Fatalf("the multivariant lacks %s:\n%s", want, mv)
		}
	}
	argv := strings.Join(r.spawns[0].Argv, " ")
	for _, want := range []string{"-map 0:i:0x601 -c:a aac", "-map 0:i:0x601 -c:a ac3 -ac 6 -b:a 640000", "-map 0:i:0x601 -c:a copy", "pipe:5"} {
		if !strings.Contains(argv, want) {
			t.Fatalf("the argv lacks %s:\n%s", want, argv)
		}
	}
	for _, name := range []string{RenditionAAC, RenditionAC3, RenditionEAC3} {
		if segs, _ := r.segments(t, name); len(segs) < 2 {
			t.Fatalf("%s has %d segments", name, len(segs))
		}
	}
}

// Parity: a non-qualifying audio stream is not mapped. The AC-3 PID the PMT
// still declares carries no packets; ffprobe reports it with 0 channels, and
// mapping it would fail every output of the generation (finding 7).
func TestRealADeclaredButEmptyAudioPIDIsNotMapped(t *testing.T) {
	r := runReal(t, withoutPID(seconds(fixture(t, "h264-1080i-aac-ac3"), 6), 0x302))
	r.ok(t)
	probe, _ := r.p.GenerationProbe(0)
	if len(probe.Audio) != 2 || probe.Audio[1].Qualifies() || !probe.Audio[0].Qualifies() {
		t.Fatalf("the probe should see the declared AC-3 PID and not qualify it: %+v", probe.Audio)
	}
	if got := strings.Join(r.renditions(), ","); got != "video,aac" {
		t.Fatalf("renditions %s, want video,aac", got)
	}
	if argv := strings.Join(r.spawns[0].Argv, " "); strings.Contains(argv, "0x302") {
		t.Fatalf("the empty PID was mapped:\n%s", argv)
	}
	if segs, _ := r.segments(t, RenditionAAC); len(segs) < 2 {
		t.Fatalf("the generation produced %d segments", len(segs))
	}
}

// M8: the no-audio fixture gets a relay-synthesised silent AAC rendition.
// Its argv has no audio output, the generation exits within 1 s of stdin
// EOF, and each silent segment's duration equals its video segment's to
// within one audio frame.
func TestRealTheNoAudioFixtureGetsRelaySynthesisedSilence(t *testing.T) {
	r := runReal(t, seconds(fixture(t, "h264-noaudio"), 6))
	r.ok(t)
	if after := exitAfterInputClosed(t, r.logs.String()); after >= time.Second {
		t.Fatalf("the generation took %v to exit after its stdin closed; want < 1s", after)
	}
	s := r.spawns[0]
	if s.Extra != nil || strings.Contains(strings.Join(s.Argv, " "), "pipe:3") || strings.Contains(strings.Join(s.Argv, " "), "lavfi") {
		t.Fatalf("a no-audio generation's argv has an audio output or a lavfi input:\n%v", s.Argv)
	}
	if !strings.Contains(r.multivariant(t), `CODECS="avc1.64002a,mp4a.40.2"`) {
		t.Fatalf("the silent AAC rendition's CODECS:\n%s", r.multivariant(t))
	}
	assertSilenceMatchesVideo(t, r, RenditionAAC, 0, 1024)
}

// E-AC-3 silence, which M8 did not prototype: generation 0 on the E-AC-3
// fixture declares aac, ac3 and eac3; generation 1 on the no-audio fixture
// fills all three from canned frames, E-AC-3's included.
func TestRealEAC3SilenceAfterABoundary(t *testing.T) {
	r := runReal(t, seconds(fixture(t, "h264-eac3"), 6), seconds(fixture(t, "h264-noaudio"), 6))
	r.ok(t)
	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3,eac3" {
		t.Fatalf("renditions %s", got)
	}
	if len(r.spawns) != 2 || r.spawns[1].Extra != nil {
		t.Fatalf("generation 1 should run with no audio output: %d spawns", len(r.spawns))
	}
	for name, spf := range map[string]uint32{RenditionAAC: 1024, RenditionAC3: 1536, RenditionEAC3: 1536} {
		declared, _ := r.p.mustOutput(t).Declared(name)
		canned, err := realSilence.Get(context.Background(), declared)
		if err != nil {
			t.Fatalf("canned %s: %v", name, err)
		}
		init, _ := r.p.Store().Init(name, 1)
		if !bytes.Equal(init, canned.Init) {
			t.Fatalf("generation 1's %s init is not the canned one", name)
		}
		if name == RenditionEAC3 && canned.Track.Codec != "ec-3" {
			t.Fatalf("the canned E-AC-3 init's CODECS is %q", canned.Track.Codec)
		}
		assertSilenceMatchesVideo(t, r, name, 1, spf)
	}
}

func (p *Pipeline) mustOutput(t *testing.T) Output {
	t.Helper()
	o, ok := p.Output()
	if !ok {
		t.Fatal("no output")
	}
	return o
}

// assertSilenceMatchesVideo checks every segment of generation gen of a
// silent rendition against its video segment: the same span to within one
// frame of spf samples, never short.
func assertSilenceMatchesVideo(t *testing.T, r *realRun, name string, gen int, spf uint32) {
	t.Helper()
	video, _ := r.segments(t, RenditionVideo)
	audio, _ := r.segments(t, name)
	checked := 0
	for i, a := range audio {
		if a.gen != gen {
			continue
		}
		if a.first.Samples == 0 || a.first.Duration != uint64(a.first.Samples)*uint64(spf) {
			t.Fatalf("%s segment %d is not whole %d-sample frames: %+v", name, a.seq, spf, a.first)
		}
		frame := float64(spf) / 48000
		if d := a.dur - video[i].dur; d < -frame || d > frame {
			t.Errorf("%s segment %d is %.4f s against its video's %.4f s; want within one frame (%.4f s)", name, a.seq, a.dur, video[i].dur, frame)
		}
		checked++
	}
	if checked < 2 {
		t.Fatalf("only %d silent %s segments in generation %d", checked, name, gen)
	}
}

// Parity: a source boundary ends the generation, the next segment carries
// EXT-X-DISCONTINUITY and a new EXT-X-MAP, and the second generation is
// probed at the boundary -- its probe reports the second source. The two
// fixtures have different PIDs, the case one surviving encoder silently
// drops (M3). The later source adds E-AC-3, which declares no new rendition.
func TestRealABoundaryGivesTwoGenerationsAndADiscontinuity(t *testing.T) {
	r := runReal(t, seconds(fixture(t, "mpeg2-576i-mp2"), 6), seconds(fixture(t, "h264-eac3"), 6))
	// The probe first: a generation-1 plan made from the wrong source maps
	// PIDs its input does not have, and the pipeline fails; the probe is the
	// assertion that names why.
	if probe, ok := r.p.GenerationProbe(1); ok && (probe.Video == nil || probe.Video.Codec != "h264" || len(probe.Audio) != 1 || probe.Audio[0].Codec != "eac3") {
		t.Fatalf("generation 1's probe describes %s, want the second source (h264 + eac3): it did not read from the boundary", describe(probe))
	}
	r.ok(t)
	video, _ := r.segments(t, RenditionVideo)
	gens := map[int]int{}
	for _, v := range video {
		gens[v.gen]++
	}
	if gens[1] == 0 {
		t.Fatalf("generation 1 produced no segments after the boundary (generations: %v)", gens)
	}
	if gens[0] == 0 {
		t.Fatalf("generation 0 produced no segments before the boundary")
	}
	if _, ok := r.p.GenerationProbe(1); !ok {
		t.Fatalf("no generation 1 was probed")
	}
	for _, name := range []string{RenditionVideo, RenditionAAC} {
		playlist, _, _ := r.p.Store().MediaPlaylist(name)
		if !strings.Contains(string(playlist), fmt.Sprintf("#EXT-X-DISCONTINUITY\n#EXT-X-MAP:URI=\"%s/init-1.mp4\"", name)) {
			t.Fatalf("the %s playlist has no discontinuity and new map at the boundary:\n%s", name, playlist)
		}
	}
	if got := strings.Join(r.renditions(), ","); got != "video,aac" {
		t.Fatalf("a later E-AC-3 source changed the rendition set to %s", got)
	}
}

func describe(p Probe) string {
	if p.Video == nil {
		return "no video"
	}
	var audio []string
	for _, a := range p.Audio {
		audio = append(audio, a.Codec)
	}
	return p.Video.Codec + " + " + strings.Join(audio, ",")
}

// Rendition filling (finding 5): the rendition set is generation 0's, and
// every later generation fills every declared rendition -- after a boundary
// onto an MP2-only source the ac3 rendition keeps growing, encoded from MP2.
func TestRealTheRenditionSetSurvivesABoundaryAndIsFilled(t *testing.T) {
	r := runReal(t, seconds(fixture(t, "h264-1080i-aac-ac3"), 6), seconds(fixture(t, "mpeg2-576i-mp2"), 6))
	r.ok(t)
	ac3, tracks := r.segments(t, RenditionAC3)
	after := 0
	for _, s := range ac3 {
		if s.gen == 1 && s.first.Samples > 0 {
			after++
		}
	}
	if after < 2 {
		t.Fatalf("the ac3 rendition stopped growing at the boundary: %d gen-1 segments with audio", after)
	}
	if tracks[1].Codec != "ac-3" {
		t.Fatalf("generation 1's ac3 init is %q", tracks[1].Codec)
	}
	if argv := strings.Join(r.spawns[len(r.spawns)-1].Argv, " "); !strings.Contains(argv, "-map 0:i:0x201 -c:a ac3 -ac 6 -b:a 640000") {
		t.Fatalf("generation 1 does not encode AC-3 5.1 from the MP2:\n%s", argv)
	}
	if got := strings.Join(r.renditions(), ","); got != "video,aac,ac3" {
		t.Fatalf("renditions %s, want generation 0's video,aac,ac3", got)
	}
}

// D11: with no usable Quick Sync the detection gives software -- against the
// real ffmpeg, with a device path that opens but is no render node.
func TestRealDetectionWithoutQuickSyncGivesSoftware(t *testing.T) {
	requireRealFFmpeg(t)
	d := &Detector{Device: os.DevNull}
	if got := d.Engine(context.Background()); got != EngineSoftware {
		t.Fatalf("the detection encode against %s gave %s, want software", os.DevNull, got)
	}
}

// The canned encodes (spec § Encoder argv, silence): every (codec, layout)
// the bitrate table names gives an init with no edit list and a steady-state
// frame of its codec's frame size.
func TestRealEveryCannedSilenceEncodes(t *testing.T) {
	requireRealFFmpeg(t)
	for _, r := range []Rendition{
		{Name: RenditionAAC, Channels: 2},
		{Name: RenditionAC3, Channels: 6}, {Name: RenditionAC3, Channels: 2},
		{Name: RenditionEAC3, Channels: 6}, {Name: RenditionEAC3, Channels: 2},
	} {
		c, err := realSilence.Get(context.Background(), r)
		if err != nil {
			t.Fatalf("%s %d.0: %v", r.Name, r.Channels, err)
		}
		want := map[string]uint32{RenditionAAC: 1024, RenditionAC3: 1536, RenditionEAC3: 1536}[r.Name]
		if c.SamplesPerFrame != want || c.Track.Timescale != AudioTimescale || bytes.Contains(c.Init, []byte("edts")) || len(c.Frame) == 0 {
			t.Fatalf("%s %d.0: spf %d, timescale %d, %d-byte frame", r.Name, r.Channels, c.SamplesPerFrame, c.Track.Timescale, len(c.Frame))
		}
		again, _ := realSilence.Get(context.Background(), r)
		if again != c {
			t.Fatalf("%s: the canned frame was encoded twice", r.Name)
		}
	}
	bad := &SilenceCache{Command: filepath.Join(t.TempDir(), "no-ffmpeg")}
	if _, err := bad.Get(context.Background(), Rendition{Name: RenditionAAC, Channels: 2}); err == nil {
		t.Fatalf("a canned encode with no ffmpeg succeeded")
	}
}

// presentationStart is the earliest presentation time in a fragment's first
// moof, in track ticks: min over its samples of decode time plus composition
// offset (signed in a version-1 trun), and whether any sample carries a
// composition offset at all -- that is, whether the encoder reordered.
// Test-only: the relay itself never needs a sample's composition offset.
func presentationStart(t *testing.T, data []byte, track Track) (int64, bool) {
	t.Helper()
	moof, _ := child(data, 0, len(data), "moof")
	traf, _ := child(data, moof.body, moof.end, "traf")
	tfhd, _ := child(data, traf.body, traf.end, "tfhd")
	_, hflags, _ := fullBox(data, tfhd)
	hc := cursor{data: data, pos: tfhd.body + 8, end: tfhd.end}
	if hflags&tfhdBaseDataOffset != 0 {
		hc.take(8)
	}
	if hflags&tfhdSampleDescIndex != 0 {
		hc.take(4)
	}
	dur := track.DefaultDuration
	if hflags&tfhdDefaultDuration != 0 {
		dur = hc.u32()
	}
	f, err := ParseFragment(data, track)
	if err != nil {
		t.Fatal(err)
	}
	trun, _ := child(data, traf.body, traf.end, "trun")
	version, rflags, _ := fullBox(data, trun)
	tf := trunFlags(rflags)
	c := cursor{data: data, pos: trun.body + 4, end: trun.end}
	count := c.u32()
	if tf&trunDataOffset != 0 {
		c.take(4)
	}
	if tf&trunFirstSampleFlags != 0 {
		c.take(4)
	}
	dts := int64(f.Start) // #nosec G115 -- a test's small timestamps
	earliest := int64(1) << 62
	reordered := false
	for i := uint32(0); i < count; i++ {
		d := dur
		if tf&trunDuration != 0 {
			d = c.u32()
		}
		if tf&trunSize != 0 {
			c.take(4)
		}
		if tf&trunFlagsPresent != 0 {
			c.take(4)
		}
		var cto int64
		if tf&trunCTO != 0 {
			raw := c.u32()
			if version == 1 {
				cto = int64(int32(raw)) // #nosec G115 -- a version-1 trun's offset is signed
			} else {
				cto = int64(raw)
			}
		}
		earliest = min(earliest, dts+cto)
		reordered = reordered || cto != 0
		dts += int64(d)
	}
	if c.bad {
		t.Fatal("short trun")
	}
	return earliest, reordered
}

// Ruling R31 (plan review, round 1, finding 2): a B-frame encode stays in
// sync with its audio. The production software argv runs libx264 with
// -tune zerolatency, which has no B-frames, so this test drops the tune to
// make the encoder reorder, as h264_qsv's defaults do. From a keyframe-
// aligned start the first video frame and the copied E-AC-3 both present at
// the source's zero; without +negative_cts_offsets the muxer moves the
// video's reorder delay into an edit list the relay strips, and the video
// would present late by it.
func TestRealABFrameEncodeStaysInSyncWithItsAudio(t *testing.T) {
	requireRealFFmpeg(t)
	src := newTestSource()
	src.write(t, seconds(fixture(t, "h264-eac3"), 6))
	src.ring.Close()
	r := &realRun{logs: &logBuffer{}}
	p, err := Start(context.Background(), Config{
		ChannelID: "bframes", Source: src, JoinBehind: time.Hour, ExitGrace: 20 * time.Second,
		Detector: &Detector{Device: filepath.Join(t.TempDir(), "renderD128"), Log: r.logs.logger()},
		Silence:  realSilence, Log: r.logs.logger(),
		Command: func(s Spawn) (string, []string) {
			var argv []string
			for i := 0; i < len(s.Argv); i++ {
				if s.Argv[i] == "-tune" {
					i++
					continue
				}
				argv = append(argv, s.Argv[i])
				if s.Argv[i] == "libx264" {
					argv = append(argv, "-bf", "2")
				}
			}
			return "ffmpeg", argv
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(p.Stop)
	<-p.Done()
	r.p = p
	r.ok(t)
	video, vtracks := r.segments(t, RenditionVideo)
	audio, atracks := r.segments(t, RenditionEAC3)
	v, reordered := presentationStart(t, video[0].data, vtracks[0])
	vf, _ := ParseFragment(video[0].data, vtracks[0])
	vs := float64(v) / float64(vtracks[0].Timescale)
	as := float64(audio[0].first.Start) / float64(atracks[0].Timescale)
	t.Logf("first video presentation %.4f s (decode %.4f s, B-frames reordered: %t), first E-AC-3 %.4f s", vs, float64(vf.Start)/float64(vtracks[0].Timescale), reordered, as)
	if !reordered {
		t.Fatalf("the encode has no composition offsets: this test did not make the encoder use B-frames")
	}
	out, _ := p.Output()
	frame := float64(out.FrameRate.Den) / float64(out.FrameRate.Num)
	if d := vs - as; d > frame/2 || d < -frame/2 {
		t.Fatalf("the B-frame video presents %+.3f s from its audio, want within half a frame (%.3f s): the reorder delay was stripped with the edit list", d, frame/2)
	}
}

// Ruling R30: every generation is probed at 3 s first, and re-probed once at
// the full 8 s bound when that found video without its geometry or field
// order. The 10 s-GOP fixture joined 3 s in has no keyframe -- and so no SPS
// -- for 7 s: the quick probe sees the video stream but not its size, the
// re-probe reaches the keyframe at 10 s, and the encoder, analysing its input
// at the same full bound, produces the run.
func TestRealALongGOPIsReprobedAtTheFullBound(t *testing.T) {
	data := fixture(t, "h264-gop10-aac")
	from := len(data) * 3 / 20
	from -= from % buffer.TSPacketSize
	r := runReal(t, data[from:])
	r.ok(t)
	logs := r.logs.String()
	if !strings.Contains(logs, "re-probing at the full bound") {
		t.Fatalf("a 10 s GOP joined mid-GOP was not re-probed:\n%s", logs)
	}
	if o, _ := r.p.Output(); o.Width != 640 || o.Height != 360 {
		t.Fatalf("the output is %dx%d, want the fixture's 640x360 from the re-probe", o.Width, o.Height)
	}
	if !strings.Contains(strings.Join(r.spawns[0].Argv, " "), "-probesize 5000000 -analyzeduration 8000000 -f mpegts -i pipe:0") {
		t.Fatalf("the encoder does not analyse its input at the bound its probe needed:\n%v", r.spawns[0].Argv)
	}
	if video, _ := r.segments(t, RenditionVideo); len(video) < 2 {
		t.Fatalf("%d segments after the re-probe", len(video))
	}
}

// ---- automatic mode (Phase 4a-1d), over real ffmpeg ----

// automatic makes runRealWith run in automatic mode.
func automatic(c *Config) { c.Mode = ModeAutomatic }

// spawnsOf is the spawns of one generation, in order.
func (r *realRun) spawnsOf(gen int) []Spawn {
	r.mu.Lock()
	defer r.mu.Unlock()
	var out []Spawn
	for _, s := range r.spawns {
		if s.Generation == gen {
			out = append(out, s)
		}
	}
	return out
}

// initCodec is the codec a generation's video init segment declares.
func (r *realRun) initCodec(t *testing.T, gen int) string {
	t.Helper()
	data, ok := r.p.Store().Init(RenditionVideo, gen)
	if !ok {
		t.Fatalf("no video init for generation %d", gen)
	}
	track, err := ParseInit(data)
	if err != nil {
		t.Fatalf("the generation %d video init: %v", gen, err)
	}
	return track.Codec
}

// videoCODECS is the video half of the multivariant's first CODECS attribute.
func videoCODECS(t *testing.T, mv string) string {
	t.Helper()
	i := strings.Index(mv, `CODECS="`)
	if i < 0 {
		t.Fatalf("no CODECS in the multivariant:\n%s", mv)
	}
	codecs, _, _ := strings.Cut(mv[i+len(`CODECS="`):], `"`)
	video, _, _ := strings.Cut(codecs, ",")
	return video
}

// assertEXTINFsWithinTarget is RFC 8216 § 4.3.3.1: every EXTINF, rounded to the
// nearest integer, is at most the playlist's TARGETDURATION (R88).
func assertEXTINFsWithinTarget(t *testing.T, r *realRun) {
	t.Helper()
	target := int(r.p.TargetDuration() / time.Second)
	video, _ := r.segments(t, RenditionVideo)
	for _, v := range video {
		if got := int(v.dur + 0.5); got > target {
			t.Errorf("segment %d (generation %d) is EXTINF %.3f, which rounds to %d over TARGETDURATION %d", v.seq, v.gen, v.dur, got, target)
		}
	}
}

// assertSegmentsAre checks every segment but the generation's last (the
// flushed tail) is want seconds, within one frame, and starts on a sync sample.
func assertSegmentsAre(t *testing.T, r *realRun, want, frame float64) {
	t.Helper()
	video, _ := r.segments(t, RenditionVideo)
	if len(video) < 2 {
		t.Fatalf("%d video segments, want at least two", len(video))
	}
	for i, v := range video {
		if !v.first.Sync {
			t.Errorf("video segment %d does not start with a sync sample", v.seq)
		}
		if i < len(video)-1 && (v.dur < want-frame || v.dur > want+frame) {
			t.Errorf("video segment %d is %.3f s, want %.3f s +/- one frame", v.seq, v.dur, want)
		}
	}
}

// R28 and issue #525: ffprobe reports field_order=unknown for the progressive
// HEVC fixture, and automatic mode copies it, tagged hvc1, with the AAC copied
// through the bitstream filter. The multivariant declares the family's
// ceiling (level 4.1 at least) while the init carries the source's own string.
func TestRealAutomaticCopiesTheHEVCFixture(t *testing.T) {
	r := runRealWith(t, automatic, seconds(fixture(t, "hevc-aac"), 8))
	r.ok(t)
	probe, ok := r.p.GenerationProbe(0)
	if !ok || probe.Video == nil || probe.Video.Field != FieldUnknown {
		t.Fatalf("generation 0's probe = %+v: the fixture is expected to report field_order unknown (#525)", probe.Video)
	}
	spawns := r.spawnsOf(0)
	if len(spawns) == 0 {
		t.Fatalf("no generation 0 spawn:\n%s", r.logs.String())
	}
	argv := strings.Join(spawns[0].Argv, " ")
	for _, want := range []string{"-c:v copy", "-tag:v hvc1", "-c:a copy -bsf:a aac_adtstoasc"} {
		if !strings.Contains(argv, want) {
			t.Fatalf("the argv has no %q: the HEVC fixture was not copied:\n%s\n%s", want, argv, r.logs.String())
		}
	}
	if !strings.HasPrefix(r.initCodec(t, 0), "hvc1.1.") {
		t.Fatalf("the video init's codec is %q, want hvc1.1.…", r.initCodec(t, 0))
	}
	declared := videoCODECS(t, r.multivariant(t))
	fields := strings.Split(declared, ".")
	if !strings.HasPrefix(declared, "hvc1.1.") || len(fields) < 4 || fields[3] < "L123" && len(fields[3]) == 4 {
		t.Fatalf("the multivariant's video CODECS is %q, want hvc1.1.… at level L123 or higher", declared)
	}
	audio, _ := r.segments(t, RenditionAAC)
	if len(audio) == 0 {
		t.Fatal("no aac segments")
	}
	if track, err := ParseInit(mustInit(t, r, RenditionAAC, 0)); err != nil || track.Codec != "mp4a.40.2" {
		t.Fatalf("the copied aac init's codec is %q (%v), want mp4a.40.2", track.Codec, err)
	}
	assertSegmentsAre(t, r, 2, 1.0/25)
	assertEXTINFsWithinTarget(t, r)
	if got := r.p.TargetDuration(); got != 2*time.Second {
		t.Errorf("TargetDuration = %v, want 2s", got)
	}
	if got := r.p.Engine(); got != EngineCopy {
		t.Errorf("Engine = %s, want copy", got)
	}
}

func mustInit(t *testing.T, r *realRun, rendition string, gen int) []byte {
	t.Helper()
	data, ok := r.p.Store().Init(rendition, gen)
	if !ok {
		t.Fatalf("no %s init for generation %d", rendition, gen)
	}
	return data
}

// The interlaced fixture cannot be copied: its video is encoded, with the
// reason logged as field_order; its AAC is copied and its AC-3 is copied as
// in transcode.
func TestRealAutomaticEncodesTheInterlacedFixtureAndCopiesItsAudio(t *testing.T) {
	r := runRealWith(t, automatic, seconds(fixture(t, "h264-1080i-aac-ac3"), 6))
	r.ok(t)
	argv := strings.Join(r.spawnsOf(0)[0].Argv, " ")
	if !strings.Contains(argv, "libx264") || strings.Contains(argv, "-c:v copy") {
		t.Fatalf("the interlaced video was not encoded:\n%s", argv)
	}
	if !strings.Contains(argv, "-c:a copy -bsf:a aac_adtstoasc") {
		t.Fatalf("the AAC was not copied through the bitstream filter:\n%s", argv)
	}
	if strings.Count(argv, "-c:a copy") != 2 {
		t.Fatalf("want the AAC and the AC-3 copied (two `-c:a copy`):\n%s", argv)
	}
	if !strings.Contains(r.logs.String(), "reason=field_order") {
		t.Fatalf("the decision's reason was not logged:\n%s", r.logs.String())
	}
	if got := r.p.Engine(); got != EngineSoftware {
		t.Errorf("Engine = %s, want software", got)
	}
}

// A 10 s-GOP source joined 3 s in has one keyframe in the 8 s window (at
// 10.08 s), so it is encoded with the reason `keyframes`, after the quick
// probe's incomplete video (no SPS) forced the re-probe. The probe wrapper
// records ffprobe's argv: the second carries the full bound and its
// read interval.
func TestRealAutomaticEncodesTheLongGOPFixtureJoinedMidGOP(t *testing.T) {
	requireRealFFmpeg(t)
	data := fixture(t, "h264-gop10-aac")
	from := len(data) * 3 / 20
	from -= from % buffer.TSPacketSize
	logFile := filepath.Join(t.TempDir(), "ffprobe-argv")
	wrapper := filepath.Join(t.TempDir(), "ffprobe-wrapper.sh")
	body := "#!/bin/sh\necho \"$@\" >> " + logFile + "\nexec ffprobe \"$@\"\n"
	if err := os.WriteFile(wrapper, []byte(body), 0o700); err != nil { // #nosec G306 -- a test's own script must be executable
		t.Fatal(err)
	}
	r := runRealWith(t, func(c *Config) { automatic(c); c.FFprobe = wrapper }, data[from:])
	r.ok(t)
	probes := strings.Split(strings.TrimSpace(string(readFile(t, logFile))), "\n")
	if len(probes) != 2 {
		t.Fatalf("ffprobe ran %d times, want the quick probe and the full re-probe:\n%v\n%s", len(probes), probes, r.logs.String())
	}
	if !strings.Contains(probes[1], "-analyzeduration 8000000") || !strings.Contains(probes[1], "-read_intervals %+8") {
		t.Fatalf("the second probe is not at the full bound: %s", probes[1])
	}
	if !strings.Contains(r.logs.String(), "reason=keyframes") {
		t.Fatalf("the decision's reason was not `keyframes`:\n%s", r.logs.String())
	}
	if got := r.p.TargetDuration(); got != 2*time.Second {
		t.Errorf("TargetDuration = %v, want 2s for an encoded run", got)
	}
	if argv := strings.Join(r.spawnsOf(0)[0].Argv, " "); !strings.Contains(argv, "libx264") || strings.Contains(argv, "-c:v copy") {
		t.Fatalf("the long-GOP video was not encoded:\n%s", argv)
	}
}

// fourSecondGOPSource is 16 s of testsrc2 at 25 fps with a keyframe every 4 s
// and AAC stereo, as MPEG-TS, built once by the test's own ffmpeg.
func fourSecondGOPSource(t *testing.T) []byte {
	t.Helper()
	requireRealFFmpeg(t)
	fixtureMu.Lock()
	defer fixtureMu.Unlock()
	if data, ok := fixtures["4s-gop"]; ok {
		return data
	}
	if fixtureDir == "" {
		dir, err := os.MkdirTemp("", "hls-fixtures-")
		if err != nil {
			t.Fatal(err)
		}
		fixtureDir = dir
	}
	out := filepath.Join(fixtureDir, "4s-gop.ts")
	cmd := exec.CommandContext(t.Context(), "ffmpeg", "-hide_banner", "-loglevel", "error", // #nosec G204 -- a fixed argv
		"-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=16",
		"-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=16",
		"-c:v", "libx264", "-preset", "veryfast", "-g", "100", "-keyint_min", "100", "-sc_threshold", "0", "-b:v", "1500k", "-pix_fmt", "yuv420p",
		"-c:a", "aac", "-ac", "2", "-b:a", "128k", "-f", "mpegts", "-y", out)
	if msg, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("building the 4 s GOP source: %v\n%s", err, msg)
	}
	data := readFile(t, out)
	if len(data) <= QuickProbe.Bytes {
		t.Fatalf("the 4 s GOP source is %d bytes, not over the quick probe's %d: the byte bound would cut the window, not the media time", len(data), QuickProbe.Bytes)
	}
	fixtures["4s-gop"] = data
	return data
}

// The R37 wiring test: a 4 s GOP shows one keyframe in the quick probe's 3 s
// window, so automatic mode re-probes at 8 s, sees two (K = 4 s), copies, and
// its target duration is 4, in the playlist too.
func TestRealAutomaticCopiesAFourSecondGOPAtTargetDurationFour(t *testing.T) {
	r := runRealWith(t, automatic, fourSecondGOPSource(t))
	r.ok(t)
	if !strings.Contains(r.logs.String(), "re-probing at the full bound") {
		t.Fatalf("the quick probe's single keyframe did not trigger R37's re-probe:\n%s", r.logs.String())
	}
	if argv := strings.Join(r.spawnsOf(0)[0].Argv, " "); !strings.Contains(argv, "-c:v copy") {
		t.Fatalf("the 4 s GOP source was not copied:\n%s\n%s", argv, r.logs.String())
	}
	if got := r.p.TargetDuration(); got != 4*time.Second {
		t.Fatalf("TargetDuration = %v, want 4s", got)
	}
	playlist, _, ok := r.p.Store().MediaPlaylist(RenditionVideo)
	if !ok || !strings.Contains(string(playlist), "#EXT-X-TARGETDURATION:4\n") {
		t.Fatalf("the media playlist does not carry TARGETDURATION 4:\n%s", playlist)
	}
	assertSegmentsAre(t, r, 4, 1.0/25)
}

// A run declared HEVC encodes its later, uncopyable generation into HEVC:
// libx265 at level-idc 4.1 (no Quick Sync here), never libx264, tagged hvc1,
// scaled and rated to the run's fixed 640x360 at 25.
func TestRealAnHEVCRunEncodesItsMPEG2GenerationAsHEVC(t *testing.T) {
	r := runRealWith(t, automatic, seconds(fixture(t, "hevc-aac"), 6), seconds(fixture(t, "mpeg2-576i-mp2"), 6))
	r.ok(t)
	spawns := r.spawnsOf(1)
	if len(spawns) == 0 {
		t.Fatalf("no generation 1 spawn:\n%s", r.logs.String())
	}
	argv := strings.Join(spawns[0].Argv, " ")
	if !strings.Contains(argv, "libx265") || !strings.Contains(argv, "level-idc=4.1") || strings.Contains(argv, "libx264") {
		t.Fatalf("generation 1 was not encoded as HEVC:\n%s", argv)
	}
	if !strings.HasPrefix(r.initCodec(t, 1), "hvc1.") {
		t.Fatalf("generation 1's init codec is %q, want hvc1.…", r.initCodec(t, 1))
	}
	mv := r.multivariant(t)
	if !strings.Contains(mv, "RESOLUTION=640x360") || !strings.Contains(mv, "FRAME-RATE=25.000") {
		t.Fatalf("the multivariant changed with the later generation:\n%s", mv)
	}
	assertEXTINFsWithinTarget(t, r)
	video, _ := r.segments(t, RenditionVideo)
	checked := 0
	for i, v := range video {
		if v.gen != 1 || i == len(video)-1 {
			continue
		}
		checked++
		if v.dur < 2-1.0/25 || v.dur > 2+1.0/25 {
			t.Errorf("generation 1 segment %d is %.3f s, want 2.000 s +/- one frame", v.seq, v.dur)
		}
	}
	if checked < 1 {
		t.Fatalf("generation 1 produced no whole segments: %d video segments", len(video))
	}
}

// An H.264 run copies its first source and encodes an interlaced later one as
// H.264: libx264, scaled to the fixed 640x360 at the fixed 25/1, with an
// avc1 High init.
func TestRealAnH264CopyRunEncodesItsInterlacedGenerationAsH264(t *testing.T) {
	r := runRealWith(t, automatic, seconds(fixture(t, "h264-eac3"), 6), seconds(fixture(t, "h264-1080i-aac-ac3"), 6))
	r.ok(t)
	if argv := strings.Join(r.spawnsOf(0)[0].Argv, " "); !strings.Contains(argv, "-c:v copy") {
		t.Fatalf("generation 0 was not copied:\n%s", argv)
	}
	spawns := r.spawnsOf(1)
	if len(spawns) == 0 {
		t.Fatalf("no generation 1 spawn:\n%s", r.logs.String())
	}
	argv := strings.Join(spawns[0].Argv, " ")
	if !strings.Contains(argv, "libx264") || !strings.Contains(argv, "scale=640:360") || !strings.Contains(argv, "fps=25/1") || strings.Contains(argv, "-c:v copy") {
		t.Fatalf("generation 1 was not encoded to the fixed output:\n%s", argv)
	}
	if !strings.HasPrefix(r.initCodec(t, 1), "avc1.64") {
		t.Fatalf("generation 1's init codec is %q, want avc1.64…", r.initCodec(t, 1))
	}
}
