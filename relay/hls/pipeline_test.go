package hls

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is the trampoline relaytest's stand-in runs through: this
// test binary, re-executed with RELAY_STANDIN=1, is the "ffmpeg" and the
// "ffprobe" the pipeline tests spawn (relaytest/standin.go). Every spawn is
// real; the stand-in is used where the subject is the relay's reaction to a
// process -- its bytes, its exit and its moment -- and real ffmpeg where the
// subject is what an encoder makes (real_test.go).
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// logBuffer is a logger a test can read back.
type logBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *logBuffer) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *logBuffer) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

func (l *logBuffer) logger() *slog.Logger {
	return slog.New(slog.NewTextHandler(l, &slog.HandlerOptions{Level: slog.LevelDebug}))
}

// file writes data to a file in the test's temporary directory.
func file(t *testing.T, name string, data []byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

const (
	probeVideoOnly = `{"streams":[{"codec_type":"video","codec_name":"h264","width":640,"height":360,"field_order":"progressive","r_frame_rate":"25/1","id":"0x100"}]}`
	probeWithAAC   = `{"streams":[{"codec_type":"video","codec_name":"h264","width":640,"height":360,"field_order":"progressive","r_frame_rate":"25/1","id":"0x100"},` +
		`{"codec_type":"audio","codec_name":"aac","channels":2,"sample_rate":"48000","id":"0x101"}]}`
	probeAudioOnly = `{"streams":[{"codec_type":"audio","codec_name":"aac","channels":2,"sample_rate":"48000","id":"0x101"}]}`
)

// standInHarness is one pipeline under test with stand-in processes.
type standInHarness struct {
	t        *testing.T
	src      *testSource
	logs     *logBuffer
	spawnLog string
	mu       sync.Mutex
	spawns   []Spawn
}

// cannedAAC is a synthetic canned silent AAC frame, so the stand-in tests
// never need a real ffmpeg for silence.
func cannedAAC(t *testing.T) *Canned {
	t.Helper()
	init, err := StripEdits(audioInit())
	if err != nil {
		t.Fatal(err)
	}
	track, _ := ParseInit(init)
	return &Canned{Init: init, Track: track, Frame: []byte{0x21, 0x10, 0x04, 0x60, 0x8c, 0x1c}, SamplesPerFrame: 1024}
}

// start runs a pipeline over h.src with the probe answering probeJSON and
// each encoder spawn given the stand-in arguments encoder returns.
func (h *standInHarness) start(probeJSON string, det *Detector, encoder func(Spawn) []string) *Pipeline {
	h.t.Helper()
	return h.startWith(probeJSON, func(c *Config) {
		if det != nil {
			c.Detector = det
		}
	}, encoder)
}

// startWith is start with a last word on the Config.
func (h *standInHarness) startWith(probeJSON string, configure func(*Config), encoder func(Spawn) []string) *Pipeline {
	h.t.Helper()
	h.t.Setenv(relaytest.StandInEnv, "1")
	probe := file(h.t, "probe.json", []byte(probeJSON))
	cfg := Config{
		ChannelID:  "test",
		Source:     h.src,
		JoinBehind: time.Hour,
		Detector:   &Detector{Device: filepath.Join(h.t.TempDir(), "renderD128"), Log: h.logs.logger()},
		Silence:    &SilenceCache{entries: map[cannedKey]*Canned{{RenditionAAC, 2}: cannedAAC(h.t)}},
		ExitGrace:  300 * time.Millisecond,
		Log:        h.logs.logger(),
		ProbeCommand: func(int) (string, []string) {
			return relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(1, probe))
		},
		Command: func(s Spawn) (string, []string) {
			h.mu.Lock()
			h.spawns = append(h.spawns, s)
			h.mu.Unlock()
			return relaytest.StandInCommand(append([]string{"--spawn-log", h.spawnLog}, encoder(s)...)...)
		},
	}
	configure(&cfg)
	p, err := Start(context.Background(), cfg)
	if err != nil {
		h.t.Fatalf("Start: %v", err)
	}
	h.t.Cleanup(p.Stop)
	return p
}

func newHarness(t *testing.T) *standInHarness {
	src := newTestSource()
	src.write(t, chunkOf('a'))
	return &standInHarness{t: t, src: src, logs: &logBuffer{}, spawnLog: filepath.Join(t.TempDir(), "spawns")}
}

// waitDone waits for the pipeline to end.
func waitDone(t *testing.T, p *Pipeline, within time.Duration) {
	t.Helper()
	select {
	case <-p.Done():
	case <-time.After(within):
		t.Fatalf("the pipeline did not end within %v", within)
	}
}

func (h *standInHarness) engines() []Engine {
	h.mu.Lock()
	defer h.mu.Unlock()
	var out []Engine
	for _, s := range h.spawns {
		out = append(out, s.Engine)
	}
	return out
}

// D11: a generation that exits before its first segment is retried once on
// the same engine; in software a second early exit fails the channel's HLS
// output (ErrFailed), logged at ERROR with the last stderr lines.
func TestAGenerationThatDiesBeforeItsFirstSegmentIsRetriedOnceThenFails(t *testing.T) {
	h := newHarness(t)
	initOnly := file(t, "v.mp4", videoInit(0))
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--echo-argv", "--fd-file", relaytest.FDFileArg(1, initOnly), "--exit-code", "1"}
	})
	waitDone(t, p, 10*time.Second)
	if !errors.Is(p.Err(), ErrFailed) {
		t.Fatalf("Err = %v, want ErrFailed", p.Err())
	}
	if n := relaytest.SpawnCount(h.spawnLog); n != 2 {
		t.Fatalf("spawned %d encoders, want the attempt and one retry", n)
	}
	if got := h.engines(); len(got) != 2 || got[0] != EngineSoftware || got[1] != EngineSoftware {
		t.Fatalf("engines %v, want software twice", got)
	}
	logs := h.logs.String()
	if !strings.Contains(logs, "level=ERROR") || !strings.Contains(logs, "every attempt at a generation exited before its first segment") || !strings.Contains(logs, "stand-in argv:") {
		t.Fatalf("the failure was not logged at ERROR with the encoder's last stderr lines:\n%s", logs)
	}
}

// D11 and finding 5: on Quick Sync, two early exits are followed by the same
// input in software; when that fails too the SOURCE was at fault, the
// channel's HLS output fails, and Quick Sync is NOT written off for the
// process.
func TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff(t *testing.T) {
	h := newHarness(t)
	det := &Detector{Command: lookPath(t, "true"), Device: device(t)}
	p := h.start(probeVideoOnly, det, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, file(t, "v.mp4", nil)), "--exit-code", "1"}
	})
	waitDone(t, p, 10*time.Second)
	if !errors.Is(p.Err(), ErrFailed) {
		t.Fatalf("Err = %v, want ErrFailed", p.Err())
	}
	if got := h.engines(); len(got) != 3 || got[0] != EngineQSV || got[1] != EngineQSV || got[2] != EngineSoftware {
		t.Fatalf("engines %v, want qsv, qsv, then software on the same input", got)
	}
	if got := det.Engine(context.Background()); got != EngineQSV {
		t.Fatalf("a source-caused early failure wrote Quick Sync off: the detector now answers %s", got)
	}
}

// D11: Quick Sync is written off for the process only when the software
// retry SUCCEEDS and a re-run of the detection encode FAILS; with the
// detection still passing it stays usable.
func TestQuickSyncIsWrittenOffOnlyWhenSoftwareSucceedsAndRedetectionFails(t *testing.T) {
	cases := []struct {
		name string
		// redetectFails makes the re-run of the detection fail; stopDuring
		// stops the pipeline while that re-run is still running, so its
		// answer never arrives (finding 1, plan review round 1).
		redetectFails, stopDuring bool
		want                      Engine
	}{
		{"the re-run fails", true, false, EngineSoftware},
		{"the re-run passes", false, false, EngineQSV},
		{"the pipeline stops during a re-run that would fail", true, true, EngineQSV},
	}
	for _, c := range cases {
		h := newHarness(t)
		marker := file(t, "qsv-works", nil)
		slow := filepath.Join(t.TempDir(), "slow")
		running := filepath.Join(t.TempDir(), "running")
		det := &Detector{Command: script(t, "[ -f \""+slow+"\" ] && { touch \""+running+"\"; sleep 3; }\n[ -f \""+marker+"\" ]"), Device: device(t)}
		stream := file(t, "v.mp4", videoStream(0, 3, 50))
		p := h.start(probeVideoOnly, det, func(s Spawn) []string {
			if s.Engine == EngineQSV {
				return []string{"--fd-file", relaytest.FDFileArg(1, file(t, "none", nil)), "--exit-code", "1"}
			}
			if c.redetectFails {
				_ = os.Remove(marker)
			}
			if c.stopDuring {
				_ = os.WriteFile(slow, nil, 0o600)
			}
			return []string{"--fd-file", relaytest.FDFileArg(1, stream), "--wait-stdin-eof"}
		})
		if err := p.Ready(context.Background()); err != nil {
			t.Fatalf("%s: Ready: %v", c.name, err)
		}
		if c.stopDuring {
			// Stop only once the re-run is running, so its answer is cut
			// short rather than never asked for.
			deadline := time.Now().Add(10 * time.Second)
			for {
				if _, err := os.Stat(running); err == nil {
					break
				}
				if time.Now().After(deadline) {
					t.Fatalf("%s: the re-run of the detection never started", c.name)
				}
				time.Sleep(10 * time.Millisecond)
			}
			p.Stop()
		} else {
			h.src.ring.Close()
			waitDone(t, p, 10*time.Second)
		}
		if p.Err() != nil {
			t.Fatalf("%s: the software attempt succeeded but Err = %v", c.name, p.Err())
		}
		if got := det.Engine(context.Background()); got != c.want {
			t.Fatalf("%s: the detector answers %s, want %s", c.name, got, c.want)
		}
		if p.Engine() != EngineSoftware {
			t.Fatalf("%s: the generation that succeeded ran on %s\n%s", c.name, p.Engine(), h.logs.String())
		}
	}
}

// D10: a generation still running after its input closed is killed after
// the exit grace, and the pipeline still ends.
func TestAGenerationThatIgnoresItsInputClosingIsKilledAfterTheGrace(t *testing.T) {
	h := newHarness(t)
	stream := file(t, "v.mp4", videoStream(0, 2, 50))
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, stream), "--ignore-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	h.src.ring.Close()
	waitDone(t, p, 5*time.Second)
	logs := h.logs.String()
	if !strings.Contains(logs, "still running after its input closed; killing it") {
		t.Fatalf("the generation was not killed after the grace:\n%s", logs)
	}
	if after := exitAfterInputClosed(t, logs); after < 300*time.Millisecond {
		t.Fatalf("the generation ended %v after its input closed, before the 300ms grace", after)
	}
}

var afterInputClosed = regexp.MustCompile(`after_input_closed=(\S+)`)

// exitAfterInputClosed reads the latest "HLS generation ended after its
// input closed" line's duration.
func exitAfterInputClosed(t *testing.T, logs string) time.Duration {
	t.Helper()
	m := afterInputClosed.FindAllStringSubmatch(logs, -1)
	if len(m) == 0 {
		t.Fatalf("no generation ended after its input closed:\n%s", logs)
	}
	d, err := time.ParseDuration(m[len(m)-1][1])
	if err != nil {
		t.Fatalf("unparsable duration %q", m[len(m)-1][1])
	}
	return d
}

// A process that dies mid-fragment: every whole fragment is segmented and
// the partial one is not.
func TestEOFMidFragmentSegmentsOnlyTheWholeFragments(t *testing.T) {
	h := newHarness(t)
	whole := videoStream(0, 6, 50) // six 2 s fragments
	truncated := file(t, "v.mp4", whole[:len(whole)-5])
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, truncated), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	h.src.ring.Close()
	waitDone(t, p, 5*time.Second)
	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
	if got := strings.Count(string(playlist), "#EXTINF:2.000,"); got != 5 {
		t.Fatalf("%d 2 s segments from five whole fragments and a partial sixth:\n%s", got, playlist)
	}
	if _, ok := p.Store().Segment(RenditionVideo, 5); ok {
		t.Fatalf("the partial fragment became a segment")
	}
}

// Spec § Encoder argv, failure: a generation that dies after its first
// segment is restarted at the ring's head as at a source boundary, with a
// discontinuity; a third such death within 60 s is a total failure.
func TestDeathsAfterTheFirstSegmentRestartUntilTheThirdWithinAMinute(t *testing.T) {
	h := newHarness(t)
	stream := file(t, "v.mp4", videoStream(0, 2, 50))
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, stream)}
	})
	waitDone(t, p, 10*time.Second)
	if !errors.Is(p.Err(), ErrFailed) {
		t.Fatalf("Err = %v, want ErrFailed after three deaths", p.Err())
	}
	if n := relaytest.SpawnCount(h.spawnLog); n != 3 {
		t.Fatalf("spawned %d encoders, want three generations", n)
	}
	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
	for _, want := range []string{`video/init-0.mp4`, `video/init-1.mp4`, `video/init-2.mp4`} {
		if !strings.Contains(string(playlist), want) {
			t.Fatalf("no %s: each death starts a new generation\n%s", want, playlist)
		}
	}
	if got := strings.Count(string(playlist), "#EXT-X-DISCONTINUITY\n"); got != 2 {
		t.Fatalf("%d discontinuities, want one before each restarted generation\n%s", got, playlist)
	}
	if !strings.Contains(h.logs.String(), "its generations keep dying") {
		t.Fatalf("the total failure was not logged")
	}
}

// D9: a generation-0 probe with no video fails the HLS attach, and a probe
// that fails fails the output.
func TestAProbeWithNoVideoOrNoAnswerFails(t *testing.T) {
	h := newHarness(t)
	p := h.start(probeAudioOnly, nil, func(Spawn) []string { return nil })
	if err := p.Ready(context.Background()); !errors.Is(err, ErrNoVideo) {
		t.Fatalf("Ready = %v, want ErrNoVideo", err)
	}
	waitDone(t, p, 5*time.Second)
	if !errors.Is(p.Err(), ErrNoVideo) || relaytest.SpawnCount(h.spawnLog) != 0 {
		t.Fatalf("Err = %v with %d encoders spawned, want ErrNoVideo and none", p.Err(), relaytest.SpawnCount(h.spawnLog))
	}
	h = newHarness(t)
	p = h.start(`{"streams":[{"codec_type":"video","codec_name":"h264","width":0,"height":0,"id":"0x100"}]}`, nil, func(Spawn) []string { return nil })
	waitDone(t, p, 5*time.Second)
	if logs := h.logs.String(); !errors.Is(p.Err(), ErrNoVideo) || !strings.Contains(logs, "re-probing at the full bound") || !strings.Contains(logs, "could not be probed") {
		t.Fatalf("video with no geometry even after the re-probe: Err = %v\n%s", p.Err(), logs)
	}
	h = newHarness(t)
	p = h.start("not json", nil, func(Spawn) []string { return nil })
	waitDone(t, p, 5*time.Second)
	if !errors.Is(p.Err(), ErrFailed) {
		t.Fatalf("an unreadable probe: Err = %v, want ErrFailed", p.Err())
	}
}

// An encoder output that is not fragmented MP4 ends the generation: the
// process is killed rather than left writing into a pipe nobody reads.
func TestAnOutputThatIsNotFragmentedMP4EndsTheGeneration(t *testing.T) {
	h := newHarness(t)
	garbage := file(t, "v.mp4", cat(box("ftyp", nil), fragSpec{seq: 1, trackID: 1, durations: []uint32{1}}.build()))
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, garbage), "--ignore-stdin-eof"}
	})
	waitDone(t, p, 10*time.Second)
	if !errors.Is(p.Err(), ErrFailed) || !strings.Contains(h.logs.String(), "is not fragmented MP4") {
		t.Fatalf("Err = %v; logs:\n%s", p.Err(), h.logs.String())
	}
}

// The segmenter's alignment (D6, spec § Playlists): each track's tfdt is
// moved by its empty edit onto one timeline, an audio segment holds the
// fragments whose start falls in its video segment's span, and a relay-
// synthesised silent rendition matches its video segment to within one frame.
func TestSegmentsAreAlignedAcrossRenditions(t *testing.T) {
	h := newHarness(t)
	video := file(t, "v.mp4", videoStream(860, 4, 50)) // starts 0.86 s into the output
	audio := file(t, "a.mp4", audioStream(40))         // 8 s of 200 ms fragments from 0
	p := h.start(probeWithAAC, nil, func(s Spawn) []string {
		if !strings.Contains(strings.Join(s.Argv, " "), "pipe:3") || len(s.Extra) != 3 || !s.Extra[0] {
			t.Errorf("the AAC encode has no fd 3: %v", s.Extra)
		}
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	mv, err := p.Multivariant("/hls/T")
	if err != nil || !strings.Contains(string(mv), `CODECS="avc1.64002a,mp4a.40.2"`) {
		t.Fatalf("multivariant %s, %v", mv, err)
	}
	h.src.ring.Close()
	waitDone(t, p, 5*time.Second)
	vt, _ := ParseInit(videoInit(0))
	at, _ := ParseInit(audioInit())
	for seq := uint64(0); seq < 4; seq++ {
		v, ok := p.Store().Segment(RenditionVideo, seq)
		a, ok2 := p.Store().Segment(RenditionAAC, seq)
		if !ok || !ok2 {
			t.Fatalf("segment %d missing (video %t, aac %t)", seq, ok, ok2)
		}
		vf, _ := ParseFragment(v, vt)
		af, _ := ParseFragment(a, at)
		vstart := float64(vf.Start) / 12800
		astart := float64(af.Start) / 48000
		if vstart != 0.86+2*float64(seq) {
			t.Errorf("segment %d's video starts at %.3f s, want its tfdt moved by the 0.86 s empty edit", seq, vstart)
		}
		if astart < vstart || astart-vstart >= 0.2 {
			t.Errorf("segment %d's audio starts at %.3f s against video %.3f s, want within its span's first 200 ms", seq, astart, vstart)
		}
	}
	init, _ := p.Store().Init(RenditionVideo, 0)
	if bytes.Contains(init, []byte("edts")) {
		t.Errorf("the served init still carries the edit list its offset was moved out of")
	}
}

// M8: a generation with no qualifying audio writes video only, and the relay
// writes the AAC rendition from its canned frame, each silent segment as long
// as its video segment to within one audio frame.
func TestASilentRenditionIsWrittenByTheRelay(t *testing.T) {
	h := newHarness(t)
	video := file(t, "v.mp4", videoStream(0, 5, 50))
	p := h.start(probeVideoOnly, nil, func(s Spawn) []string {
		if s.Extra != nil || strings.Contains(strings.Join(s.Argv, " "), "pipe:3") {
			t.Errorf("a silent generation's argv has an audio output: %v", s.Argv)
		}
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	h.src.ring.Close()
	waitDone(t, p, 5*time.Second)
	canned := cannedAAC(t)
	if init, _ := p.Store().Init(RenditionAAC, 0); !bytes.Equal(init, canned.Init) {
		t.Fatalf("the silent rendition's init is not the canned one")
	}
	vt, _ := ParseInit(videoInit(0))
	for seq := uint64(0); seq < 5; seq++ {
		v, _ := p.Store().Segment(RenditionVideo, seq)
		a, _ := p.Store().Segment(RenditionAAC, seq)
		vf, _ := ParseFragment(v, vt)
		af, err := ParseFragment(a, canned.Track)
		if err != nil {
			t.Fatalf("silent segment %d: %v", seq, err)
		}
		vEnd := float64(vf.End()) / 12800
		aEnd := float64(af.End()) / 48000
		if d := aEnd - vEnd; d < 0 || d >= 1024.0/48000 {
			t.Errorf("silent segment %d ends %.4f s from its video, want within one frame", seq, d)
		}
	}
}

// Stop ends a running generation at once, killing it; the pipeline ends
// without an error.
func TestStopEndsTheGeneration(t *testing.T) {
	h := newHarness(t)
	stream := file(t, "v.mp4", videoStream(0, 2, 50))
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, stream), "--ignore-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	stopped := time.Now()
	p.Stop()
	if took := time.Since(stopped); took > 3*time.Second {
		t.Fatalf("Stop took %v", took)
	}
	if p.Err() != nil {
		t.Fatalf("a stopped pipeline's Err = %v", p.Err())
	}
	if p.Generation() != 0 || p.Engine() != EngineSoftware {
		t.Errorf("generation %d on %s", p.Generation(), p.Engine())
	}
	if probe, ok := p.GenerationProbe(0); !ok || probe.Video == nil {
		t.Errorf("generation 0's probe was not kept")
	}
	if o, ok := p.Output(); !ok || o.Width != 640 {
		t.Errorf("Output = %+v, %t", o, ok)
	}
}

func TestStartNeedsASourceAndMultivariantNeedsReady(t *testing.T) {
	if _, err := Start(context.Background(), Config{}); err == nil {
		t.Fatalf("Start accepted no source")
	}
	h := newHarness(t)
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, file(t, "none", nil)), "--ignore-stdin-eof"}
	})
	if _, err := p.Multivariant("/hls/T"); err == nil {
		t.Fatalf("a multivariant was rendered before the inits existed")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if err := p.Ready(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Ready with no init = %v, want the context's end", err)
	}
}

// The generation's last segment -- its flushed tail -- with no audio on a
// rendition is not published: an empty fragment there stalled AVPlayer's
// E-AC-3 path on the iOS 27 Simulator (measured while planning 4a-1a).
func TestATailWithNoAudioIsNotPublished(t *testing.T) {
	h := newHarness(t)
	video := file(t, "v.mp4", videoStream(0, 3, 50)) // 6 s of video
	audio := file(t, "a.mp4", audioStream(20))       // 4 s of audio
	p := h.start(probeWithAAC, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	h.src.ring.Close()
	waitDone(t, p, 5*time.Second)
	if _, ok := p.Store().Segment(RenditionVideo, 1); !ok {
		t.Fatalf("segment 1, which has audio, was not published")
	}
	if _, ok := p.Store().Segment(RenditionVideo, 2); ok {
		t.Fatalf("the tail segment, with no audio on aac, was published")
	}
}

// Mid-generation, a segment whose audio output wrote nothing for its span is
// published after AudioWait with an empty fragment of the audio track at the
// span's start, so the video never stalls behind a stopped audio output.
func TestAStoppedAudioOutputDoesNotStallTheVideo(t *testing.T) {
	h := newHarness(t)
	video := file(t, "v.mp4", videoStream(0, 4, 50)) // 8 s of video
	audio := file(t, "a.mp4", audioStream(10))       // 2 s of audio, then nothing
	p := h.startWith(probeWithAAC, func(c *Config) { c.AudioWait = 200 * time.Millisecond }, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
	})
	if err := p.Store().WaitSegment(context.Background()); err != nil {
		t.Fatalf("WaitSegment: %v", err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, ok := p.Store().Segment(RenditionAAC, 2); ok {
			break
		}
		if time.Now().After(deadline) {
			playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
			t.Fatalf("segment 2 was never published with the audio output stopped:\n%s", playlist)
		}
		time.Sleep(20 * time.Millisecond)
	}
	at, _ := ParseInit(audioInit())
	data, _ := p.Store().Segment(RenditionAAC, 2)
	f, err := ParseFragment(data, at)
	if err != nil || f.Samples != 0 || f.Start != 4*48000 {
		t.Fatalf("segment 2's aac part = %+v, %v; want an empty fragment at 4 s", f, err)
	}
	playlist, _, _ := p.Store().MediaPlaylist(RenditionAAC)
	if !strings.Contains(string(playlist), "#EXTINF:2.000,\naac/2.m4s") {
		t.Fatalf("the empty audio segment does not carry its video's duration:\n%s", playlist)
	}
}

// D6: the segmenter accumulates video fragments until the 2 s grid is
// reached, and cuts only before a sync sample. With one-second fragments
// from a first sync fragment at 1 s the grid lines are at 3, 5 and 7 s: the
// non-sync fragment at 0 s starts nothing; 1+2 make a segment; the fragment
// on the 5 s line opens on a non-sync sample, so 3+4+5 make one; and the
// next sync fragment, at 6 s, is where the grid picks up again.
func TestSegmentsAccumulateToTheGridAndCutOnlyAtASyncSample(t *testing.T) {
	h := newHarness(t)
	second := make([]uint32, 25) // one second of 25 fps frames at 12800 Hz
	for i := range second {
		second[i] = 512
	}
	stream := videoInit(0)
	var start uint64
	for i, sync := range []bool{false, true, true, true, true, false, true, true} {
		stream = append(stream, fragSpec{seq: uint32(i + 1), trackID: 1, start: start, durations: second, sync: sync}.build()...) // #nosec G115 -- a test's small count
		start += 25 * 512
	}
	video := file(t, "v.mp4", stream)
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	h.src.ring.Close()
	waitDone(t, p, 5*time.Second)
	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
	var got []string
	for _, line := range strings.Split(string(playlist), "\n") {
		if strings.HasPrefix(line, "#EXTINF:") {
			got = append(got, strings.TrimSuffix(strings.TrimPrefix(line, "#EXTINF:"), ","))
		}
	}
	if strings.Join(got, " ") != "2.000 3.000 1.000 1.000" {
		t.Fatalf("segment durations %v, want 2.000 3.000 1.000 1.000:\n%s", got, playlist)
	}
	vt, _ := ParseInit(videoInit(0))
	for seq := uint64(0); seq < 4; seq++ {
		data, _ := p.Store().Segment(RenditionVideo, seq)
		if f, _ := ParseFragment(data, vt); !f.Sync {
			t.Fatalf("segment %d opens on a non-sync sample", seq)
		}
	}
}

// Ruling R33: a generation that writes no new video while the channel's ring
// keeps advancing is a stalled encoder, killed and counted as a death; the
// third within a minute fails the output.
func TestAStalledEncoderIsKilledAsADeath(t *testing.T) {
	h := newHarness(t)
	oneFragment := file(t, "v.mp4", videoStream(0, 1, 50))
	p := h.startWith(probeVideoOnly, func(c *Config) { c.StallTimeout = 300 * time.Millisecond }, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, oneFragment), "--ignore-stdin-eof"}
	})
	stop := make(chan struct{})
	defer close(stop)
	go func() {
		for {
			select {
			case <-stop:
				return
			case <-time.After(20 * time.Millisecond):
				_, _ = h.src.ring.Write(chunkOf('a'))
			}
		}
	}()
	waitDone(t, p, 20*time.Second)
	if !errors.Is(p.Err(), ErrFailed) {
		t.Fatalf("Err = %v, want ErrFailed after three stalled generations", p.Err())
	}
	if got := strings.Count(h.logs.String(), "killing it as a stalled encoder"); got != 3 {
		t.Fatalf("%d stalled generations killed, want 3:\n%s", got, h.logs.String())
	}
}

// R33's "while its input is advancing": an encoder starved by an upstream in
// dead air is not stalled, and the watchdog leaves it alone.
func TestAStarvedEncoderIsNotKilled(t *testing.T) {
	// Two shapes of "not advancing". An idle ring from the start never arms
	// the clock. A STUTTERING ring -- a chunk, then longer than half the
	// timeout of dead air, again and again -- arms it on every chunk, and
	// only the idle reset keeps it from reaching the timeout (round 3,
	// finding 1: the idle case alone passes with that reset removed).
	// The watchdog samples every tenth of the timeout, so it sees a chunk up
	// to one tick late and resets only at a tick at least half the timeout
	// after that: the dead air must exceed half the timeout by two ticks
	// (700 ms of a 1 s timeout) to reset every time. 850 ms does; 700 ms
	// reset or not by a scheduling hair (round 4, 2 of 10 runs in the
	// production image).
	for _, stutter := range []bool{false, true} {
		h := newHarness(t)
		oneFragment := file(t, "v.mp4", videoStream(0, 1, 50))
		stall := 300 * time.Millisecond
		if stutter {
			stall = time.Second
		}
		p := h.startWith(probeVideoOnly, func(c *Config) { c.StallTimeout = stall }, func(Spawn) []string {
			return []string{"--fd-file", relaytest.FDFileArg(1, oneFragment), "--ignore-stdin-eof"}
		})
		if err := p.Ready(context.Background()); err != nil {
			t.Fatalf("stutter=%t: Ready: %v", stutter, err)
		}
		if stutter {
			for i := 0; i < 6; i++ {
				h.src.write(t, chunkOf('s'))
				time.Sleep(850 * time.Millisecond)
			}
		}
		select {
		case <-p.Done():
			t.Fatalf("stutter=%t: the pipeline ended with the ring idle or stuttering: %v\n%s", stutter, p.Err(), h.logs.String())
		case <-time.After(1500 * time.Millisecond):
		}
		if strings.Contains(h.logs.String(), "stalled encoder") {
			t.Fatalf("stutter=%t: an encoder starved of input was killed as stalled:\n%s", stutter, h.logs.String())
		}
		p.Stop()
	}
}

// Finding 3 (plan review, round 1): a failover candidate that sends a few
// packets and drops before its generation could be probed is skipped -- the
// pipeline moves to the next boundary -- rather than failing the output.
func TestAConnectionTooShortToProbeIsSkipped(t *testing.T) {
	h := newHarness(t)
	h.src.mark()
	h.src.write(t, chunkOf('b'))
	h.src.mark()
	h.src.write(t, chunkOf('c'))
	h.t.Setenv(relaytest.StandInEnv, "1")
	withVideo := file(t, "probe-video.json", []byte(probeVideoOnly))
	withoutVideo := file(t, "probe-audio.json", []byte(probeAudioOnly))
	video := file(t, "v.mp4", videoStream(0, 2, 50))
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.ProbeCommand = func(gen int) (string, []string) {
			json := withVideo
			if gen == 1 {
				json = withoutVideo
			}
			return relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(1, json), "--wait-stdin-eof")
		}
	}, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	h.src.ring.Close()
	waitDone(t, p, 10*time.Second)
	if p.Err() != nil {
		t.Fatalf("a connection too short to probe failed the output: %v\n%s", p.Err(), h.logs.String())
	}
	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
	if !strings.Contains(string(playlist), `video/init-2.mp4`) || strings.Contains(string(playlist), `video/init-1.mp4`) {
		t.Fatalf("generation 2 did not publish after the skipped generation 1:\n%s", playlist)
	}
	if n := relaytest.SpawnCount(h.spawnLog); n != 2 {
		t.Fatalf("%d encoders spawned, want generations 0 and 2 only", n)
	}
}

// Ruling R39: generation 0 starts JoinBehind behind live, so a failover in
// the last few seconds puts a boundary in its probe window. When the old
// connection's tail is too short to probe, generation 0 moves to that
// boundary instead of answering ErrNoVideo, and keeps its number.
func TestGenerationZeroSkipsAConnectionTooShortToProbe(t *testing.T) {
	h := newHarness(t)
	h.src.mark()
	h.src.write(t, chunkOf('b'))
	h.t.Setenv(relaytest.StandInEnv, "1")
	withVideo := file(t, "probe-video.json", []byte(probeVideoOnly))
	withoutVideo := file(t, "probe-audio.json", []byte(probeAudioOnly))
	video := file(t, "v.mp4", videoStream(0, 2, 50))
	var probes int
	var mu sync.Mutex
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.ProbeCommand = func(int) (string, []string) {
			mu.Lock()
			defer mu.Unlock()
			probes++
			json := withVideo
			if probes == 1 {
				json = withoutVideo
			}
			return relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(1, json), "--wait-stdin-eof")
		}
	}, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready = %v: generation 0 did not move past a connection too short to probe\n%s", err, h.logs.String())
	}
	h.src.ring.Close()
	waitDone(t, p, 10*time.Second)
	if p.Err() != nil {
		t.Fatalf("Err = %v", p.Err())
	}
	playlist, _, _ := p.Store().MediaPlaylist(RenditionVideo)
	if !strings.Contains(string(playlist), `video/init-0.mp4`) || strings.Contains(string(playlist), `init-1`) {
		t.Fatalf("the generation after the skip is not generation 0:\n%s", playlist)
	}
}

// Finding 1 of round 2: a pipeline stopped while an attempt waits for the
// canned silence -- behind another channel's encode, or its own first one --
// stops; it does not end as ErrFailed, which 4a-1b turns into a 502 for every
// new HLS entry until the next source boundary.
func TestAStopDuringTheSilenceWaitIsAStopNotAFailure(t *testing.T) {
	h := newHarness(t)
	sil := &SilenceCache{entries: map[cannedKey]*Canned{{RenditionAAC, 2}: cannedAAC(t)}}
	if err := sil.run.lock(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer sil.run.unlock()
	p := h.startWith(probeVideoOnly, func(c *Config) { c.Silence = sil }, func(Spawn) []string { return nil })
	// Stop only once the probe is done, so the attempt is the thing waiting
	// on the held lock when the stop lands.
	deadline := time.Now().Add(10 * time.Second)
	for !strings.Contains(h.logs.String(), "HLS generation probed") {
		if time.Now().After(deadline) {
			t.Fatalf("the probe never finished:\n%s", h.logs.String())
		}
		time.Sleep(10 * time.Millisecond)
	}
	time.Sleep(200 * time.Millisecond)
	p.Stop()
	if err := p.Err(); err != nil {
		t.Fatalf("Err after a Stop during the silence wait = %v, want nil: a stop is not a failure\n%s", err, h.logs.String())
	}
	if strings.Contains(h.logs.String(), "level=ERROR") {
		t.Fatalf("a stop was logged as an error:\n%s", h.logs.String())
	}
}

// Finding 2 of round 3: a pipeline stopped while waiting behind another
// channel's Quick Sync detection gets software on its dead context, has no
// silence to wait for when every rendition is encoded, and reaches the
// encoder spawn with its context ended. That is a stop, not ErrFailed.
func TestAStopDuringTheDetectionWaitIsAStopNotAFailure(t *testing.T) {
	h := newHarness(t)
	det := &Detector{Command: lookPath(t, "true"), Device: device(t), Log: h.logs.logger()}
	if err := det.run.lock(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer det.run.unlock()
	p := h.startWith(probeWithAAC, func(c *Config) { c.Detector = det }, func(Spawn) []string { return nil })
	deadline := time.Now().Add(10 * time.Second)
	for !strings.Contains(h.logs.String(), "HLS generation probed") {
		if time.Now().After(deadline) {
			t.Fatalf("the probe never finished:\n%s", h.logs.String())
		}
		time.Sleep(10 * time.Millisecond)
	}
	time.Sleep(200 * time.Millisecond)
	p.Stop()
	if err := p.Err(); err != nil {
		t.Fatalf("Err after a Stop during the detection wait = %v, want nil: a stop is not a failure\n%s", err, h.logs.String())
	}
	if strings.Contains(h.logs.String(), "level=ERROR") {
		t.Fatalf("a stop was logged as an error:\n%s", h.logs.String())
	}
}

// Ruling R40: when the channel's ring closes under a probe that then fails,
// the channel is ending; the pipeline stops, it does not fail.
func TestARingThatClosesDuringAProbeIsAStop(t *testing.T) {
	h := newHarness(t)
	h.t.Setenv(relaytest.StandInEnv, "1")
	withVideo := file(t, "probe-video.json", []byte(probeVideoOnly))
	video := file(t, "v.mp4", videoStream(0, 2, 50))
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.ProbeCommand = func(gen int) (string, []string) {
			if gen == 0 {
				return relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(1, withVideo))
			}
			// What ffprobe does on a closed, near-empty pipe: no streams,
			// a non-zero exit once its input ends.
			return relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(1, file(t, "empty.json", nil)), "--wait-stdin-eof", "--exit-code", "1")
		}
	}, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	h.src.mark()
	h.src.write(t, chunkOf('z'))
	time.Sleep(300 * time.Millisecond)
	h.src.ring.Close()
	waitDone(t, p, 10*time.Second)
	if err := p.Err(); err != nil {
		t.Fatalf("Err after the ring closed under a probe = %v, want nil: the channel is ending\n%s", err, h.logs.String())
	}
	if strings.Contains(h.logs.String(), "level=ERROR") {
		t.Fatalf("a ring closing under a probe was logged as an error:\n%s", h.logs.String())
	}
}

// Ruling R41: Ready fires on the first generation that writes every init,
// not only generation 0. Here generation 0 ends at a boundary having written
// none, and generation 1 serves.
func TestReadyFiresOnTheFirstGenerationWithEveryInit(t *testing.T) {
	h := newHarness(t)
	h.src.mark()
	h.src.write(t, chunkOf('b'))
	video := file(t, "v.mp4", videoStream(0, 2, 50))
	nothing := file(t, "none.mp4", nil)
	p := h.start(probeVideoOnly, nil, func(s Spawn) []string {
		if s.Generation == 0 {
			return []string{"--fd-file", relaytest.FDFileArg(1, nothing), "--wait-stdin-eof"}
		}
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
	})
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := p.Ready(ctx); err != nil {
		t.Fatalf("Ready = %v: a generation 0 that wrote no init held Ready while generation 1 served\n%s", err, h.logs.String())
	}
	mv, err := p.Multivariant("/hls/T")
	if err != nil || !strings.Contains(string(mv), `CODECS="avc1.64002a,mp4a.40.2"`) {
		t.Fatalf("multivariant %s, %v", mv, err)
	}
	if _, ok := p.Store().Init(RenditionVideo, 1); !ok {
		t.Fatalf("generation 1's init is not stored")
	}
}

// Plan review, round 4, finding 1: completeness is judged from the codecs
// noteInit records, never from the store. Here the aac reader has stored its
// init but not yet recorded its codec when the video reader's noteInit runs
// -- the interleaving that advertised CODECS="avc1.64002a," -- so Ready must
// wait for the aac reader's own noteInit.
func TestReadyWaitsForEveryCodecNotOnlyEveryStoredInit(t *testing.T) {
	out, err := Decide(Probe{Video: video(640, 360, Rational{25, 1}, FieldProgressive)})
	if err != nil {
		t.Fatal(err)
	}
	p := &Pipeline{store: NewStore(time.Now), readyCh: make(chan struct{}), output: &out}
	p.store.SetInit(RenditionAAC, 0, []byte("aac init"))
	p.noteInit(RenditionVideo, 0, []byte("video init"), "avc1.64002a")
	select {
	case <-p.readyCh:
		mv, _ := p.Multivariant("/hls/T")
		t.Fatalf("Ready fired before the aac reader recorded its codec: the store held every init but the codecs lacked aac\n%s", mv)
	default:
	}
	p.noteInit(RenditionAAC, 0, []byte("aac init"), "mp4a.40.2")
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := p.Ready(ctx); err != nil {
		t.Fatalf("Ready = %v once every codec was recorded", err)
	}
	mv, err := p.Multivariant("/hls/T")
	if err != nil || !strings.Contains(string(mv), `CODECS="avc1.64002a,mp4a.40.2"`) {
		t.Fatalf("multivariant %s, %v: want the aac codec in every variant", mv, err)
	}
}

// PR #529 review (thread on pipeline.go:758): a Stop ends an encoder that
// ignores stdin EOF. The feed then ends feedStopped, which runs no exit
// grace, but the process was started on the attempt's context, a child of
// the pipeline's, and exec.CommandContext kills the whole process group when
// it ends (relay/ffmpeg's Cancel): the pipes close, the readers return, and
// Stop does not have to give up on its bounded wait.
func TestAStopKillsAnEncoderThatIgnoresStdinEOF(t *testing.T) {
	h := newHarness(t)
	video := file(t, "v.mp4", videoStream(0, 1, 50))
	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--ignore-stdin-eof"}
	})
	if err := p.Ready(context.Background()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
	stopped := make(chan struct{})
	go func() {
		defer close(stopped)
		p.Stop()
	}()
	select {
	case <-p.Done():
	case <-time.After(3 * time.Second):
		t.Fatalf("the pipeline did not end within 3s of Stop: an encoder ignoring stdin EOF outlived the stop\n%s", h.logs.String())
	}
	<-stopped
	if err := p.Err(); err != nil {
		t.Fatalf("Err after a Stop = %v, want nil", err)
	}
	if strings.Contains(h.logs.String(), "did not stop in time") {
		t.Fatalf("Stop gave up waiting:\n%s", h.logs.String())
	}
}

// PR #529 review (thread on pipeline.go:731): an audio output that goes
// silent for good while the video keeps flowing does not wedge the
// generation. Its reader blocks in Read, but the video is published past it
// (Decision 6: an empty fragment after AudioWait), and the generation ends
// the ordinary way -- stdin EOF ends the encoder, whose exit closes every
// pipe, the silent one included -- with no kill and no watchdog.
func TestASilentAudioPipeDoesNotWedgeTheGeneration(t *testing.T) {
	h := newHarness(t)
	video := file(t, "v.mp4", videoStream(0, 4, 50)) // 8 s of video
	audio := file(t, "a.mp4", audioStream(10))       // 2 s of audio, then a pipe held open and silent
	// The exit grace is 3 s, not the harness's 300 ms: under -race the
	// stand-in is a race-instrumented binary, whose runtime sleeps a second
	// at exit (GORACE atexit_sleep_ms), and this test asserts that no kill
	// was needed.
	p := h.startWith(probeWithAAC, func(c *Config) { c.AudioWait, c.ExitGrace = 200*time.Millisecond, 3*time.Second }, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
	})
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, ok := p.Store().Segment(RenditionAAC, 2); ok {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the video was not published past the silent audio pipe\n%s", h.logs.String())
		}
		time.Sleep(20 * time.Millisecond)
	}
	h.src.ring.Close()
	waitDone(t, p, 6*time.Second)
	if err := p.Err(); err != nil {
		t.Fatalf("Err = %v, want nil: the channel ended", err)
	}
	logs := h.logs.String()
	if strings.Contains(logs, "killing it") || !strings.Contains(logs, "HLS generation ended after its input closed") {
		t.Fatalf("the generation did not end on its own at stdin EOF with an audio pipe silent:\n%s", logs)
	}
}

// PR #529 review (thread on segmenter.go:354): the empty fragment a
// mid-generation span gets when its audio output wrote nothing starts at the
// span's start in audio ticks rounded UP, as the silence clock rounds
// (silence.go), so it never starts before its span. Here the first video
// fragment is at tfdt 1, so segment 2 starts at 51201 video ticks: 192003.75
// audio ticks.
func TestAnEmptyAudioFragmentNeverStartsBeforeItsSpan(t *testing.T) {
	h := newHarness(t)
	second := make([]uint32, 25)
	for i := range second {
		second[i] = 512
	}
	stream := videoInit(0)
	for i := 0; i < 8; i++ {
		stream = append(stream, fragSpec{seq: uint32(i + 1), trackID: 1, start: 1 + uint64(i)*12800, durations: second, sync: true}.build()...) // #nosec G115 -- a test's small count
	}
	video := file(t, "v.mp4", stream)
	audio := file(t, "a.mp4", audioStream(10)) // 2 s of audio, then nothing
	p := h.startWith(probeWithAAC, func(c *Config) { c.AudioWait = 200 * time.Millisecond }, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--fd-file", relaytest.FDFileArg(3, audio), "--wait-stdin-eof"}
	})
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, ok := p.Store().Segment(RenditionAAC, 2); ok {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("segment 2 was never published\n%s", h.logs.String())
		}
		time.Sleep(20 * time.Millisecond)
	}
	at, _ := ParseInit(audioInit())
	data, _ := p.Store().Segment(RenditionAAC, 2)
	f, err := ParseFragment(data, at)
	if err != nil || f.Samples != 0 {
		t.Fatalf("segment 2's aac part = %+v, %v; want an empty fragment", f, err)
	}
	if f.Start != 192004 {
		t.Fatalf("the empty fragment starts at %d audio ticks, want 192004: its span starts at 192003.75, and a truncated tfdt starts it before its span", f.Start)
	}
}
