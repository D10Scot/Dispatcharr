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
	p, err := Start(context.Background(), Config{
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
	})
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
