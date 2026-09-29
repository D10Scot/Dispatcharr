package hls

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// probeAutomatic is an automatic-mode ffprobe answer: 640x360 progressive H.264
// with no audio (so the aac rendition is filled with canned silence and the
// stand-in tests need no audio output), and two video key packets keyframeGap
// seconds apart.
func probeAutomatic(keyframeGap string) string {
	return `{"streams":[{"index":0,"codec_type":"video","codec_name":"h264","profile":"High","level":30,"pix_fmt":"yuv420p",` +
		`"width":640,"height":360,"field_order":"progressive","r_frame_rate":"25/1","id":"0x100"}],` +
		`"packets":[{"stream_index":0,"pts_time":"0.000000","flags":"K__","size":"1000"},` +
		`{"stream_index":0,"pts_time":"` + keyframeGap + `","flags":"K__","size":"1000"}]}`
}

// startAutomatic runs an automatic-mode pipeline over the harness's ring.
func (h *standInHarness) startAutomatic(probeJSON string, encoder func(Spawn) []string) *Pipeline {
	h.t.Helper()
	return h.startWith(probeJSON, func(c *Config) { c.Mode = ModeAutomatic }, encoder)
}

// gopStream is a synthetic video output: its init and one fragment per entry
// of frames (each frame 512 ticks of 12800 Hz, so 25 frames is one second),
// every fragment opening on a sync sample.
func gopStream(frames ...int) []byte {
	out := videoInit(0)
	var start uint64
	for i, n := range frames {
		d := make([]uint32, n)
		for j := range d {
			d[j] = 512
		}
		out = append(out, fragSpec{seq: uint32(i + 1), trackID: 1, start: start, durations: d, sync: true}.build()...) // #nosec G115 -- a test's small counts
		start += uint64(n) * 512
	}
	return out
}

func (s Spawn) copies() bool { return strings.Contains(joinArgs(s.Argv), "-c:v copy") }

func waitFor(t *testing.T, what string, within time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(within)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out after %v waiting for %s", within, what)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// ---- the segmenter, with synthetic fragments at 90 kHz ----

const ticks90k = 90000

func newCopySegmenter(copied bool, target uint64, audio ...string) (*segmenter, *Store) {
	store := NewStore(time.Now)
	s := newSegmenter(store, 0, audio, nil, time.Now, time.Minute, nil)
	s.video.info, s.video.haveInit = Track{ID: 1, Timescale: ticks90k}, true
	for _, t := range s.audio {
		t.info, t.haveInit = Track{ID: 1, Timescale: 48000}, true
	}
	s.target, s.copied = target, copied
	return s, store
}

func vfrag(start, duration float64) Fragment {
	return Fragment{Data: []byte{'v'}, Start: uint64(start * ticks90k), Duration: uint64(duration * ticks90k), Sync: true}
}

// extinfs is the video playlist's EXTINF values.
func extinfs(store *Store) []string {
	playlist, _, _ := store.MediaPlaylist(RenditionVideo)
	var out []string
	for _, line := range strings.Split(string(playlist), "\n") {
		if strings.HasPrefix(line, "#EXTINF:") {
			out = append(out, strings.TrimSuffix(strings.TrimPrefix(line, "#EXTINF:"), ","))
		}
	}
	return out
}

func runToEOF(s *segmenter) {
	s.finish(RenditionVideo)
	for _, t := range s.audio {
		s.finish(t.name)
	}
	s.run()
}

// A copied generation closes before a keyframe fragment that would take the
// segment to target + 0.5 s, so a GOP a little under the grid gets one segment
// per GOP: 1.92 s GOPs at a target of 2 are 1.920 s segments, where the 2 s
// grid alone would make them 3.84 s.
func TestACopiedGenerationCutsWithinTheTargetDuration(t *testing.T) {
	t.Run("1.92 s GOPs at target 2", func(t *testing.T) {
		s, store := newCopySegmenter(true, 2)
		for i := 0; i < 5; i++ {
			s.fragment(RenditionVideo, vfrag(float64(i)*1.92, 1.92))
		}
		runToEOF(s)
		if got := strings.Join(extinfs(store), " "); got != "1.920 1.920 1.920 1.920 1.920" {
			t.Fatalf("segments %q, want five of 1.920 s and none over-long", got)
		}
		if s.Overlong() {
			t.Fatal("a 1.92 s GOP at target 2 was called over-long")
		}
	})
	t.Run("4 s GOPs at target 4", func(t *testing.T) {
		s, store := newCopySegmenter(true, 4)
		for i := 0; i < 3; i++ {
			s.fragment(RenditionVideo, vfrag(float64(i)*4, 4))
		}
		runToEOF(s)
		if got := strings.Join(extinfs(store), " "); got != "4.000 4.000 4.000" {
			t.Fatalf("segments %q, want three of 4.000 s", got)
		}
	})
	t.Run("irregular GOPs at target 2 close on the grid or before 2.5 s", func(t *testing.T) {
		s, store := newCopySegmenter(true, 2)
		start := 0.0
		for i := 0; i < 3; i++ {
			for _, d := range []float64{0.5, 0.5, 1.2, 0.4} {
				s.fragment(RenditionVideo, vfrag(start, d))
				start += d
			}
		}
		runToEOF(s)
		total := 0.0
		for _, e := range extinfs(store) {
			var d float64
			if _, err := fmt.Sscanf(e, "%f", &d); err != nil || d >= 2.5 || d <= 0 {
				t.Fatalf("segment %q: over-long or unreadable, in %v", e, extinfs(store))
			}
			total += d
		}
		if total < 7.79 || total > 7.81 {
			t.Fatalf("the segments total %.3f s, want the 7.8 s that was fed: %v", total, extinfs(store))
		}
	})
}

// A copied fragment that would take its segment to target + 0.5 s ends the
// generation: it is never published, later fragments are discarded, the
// segments cut before it publish through the normal path (with their audio),
// and onOverlong fires once. Both arrival shapes: each fragment on its own
// wake, and both queued before the segmenter's first wake (which is where a
// cleared `ready` would lose the segment already cut).
func TestAnOverLongCopiedFragmentEndsTheGeneration(t *testing.T) {
	for _, queued := range []bool{false, true} {
		name := "each fragment on its own wake"
		if queued {
			name = "both queued before the first wake"
		}
		t.Run(name, func(t *testing.T) {
			s, store := newCopySegmenter(true, 2, RenditionAAC)
			var fired atomic.Int32
			s.onOverlong = func() { fired.Add(1) }
			// The one audio track covers [0, 2.0 s) in 200 ms fragments, so the
			// 2.0 s video segment has audio and is the generation's last.
			for i := 0; i < 10; i++ {
				s.fragment(RenditionAAC, Fragment{Data: []byte{'a'}, Start: uint64(i * 9600), Duration: 9600, Sync: true})
			}
			done := make(chan struct{})
			consumed := func() bool {
				s.mu.Lock()
				defer s.mu.Unlock()
				return len(s.video.frags) == 0
			}
			if queued {
				s.fragment(RenditionVideo, vfrag(0, 2))
				s.fragment(RenditionVideo, vfrag(2, 2.5))
				go func() { defer close(done); s.run() }()
			} else {
				go func() { defer close(done); s.run() }()
				s.fragment(RenditionVideo, vfrag(0, 2))
				waitFor(t, "the first fragment to be consumed", 5*time.Second, consumed)
				s.fragment(RenditionVideo, vfrag(2, 2.5))
			}
			waitFor(t, "onOverlong", 5*time.Second, func() bool { return fired.Load() == 1 })
			if !s.Overlong() {
				t.Fatal("Overlong() is false after onOverlong fired")
			}
			// The audio has not reached the segment's end (its last fragment
			// starts at 1.8 s), so nothing publishes until it does.
			if n := len(extinfs(store)); n != 0 {
				t.Fatalf("a segment published before its audio reached its end: %v", extinfs(store))
			}
			// The encoder is killed; whatever it still wrote is discarded.
			s.fragment(RenditionVideo, vfrag(4.5, 2))
			s.finish(RenditionAAC)
			s.finish(RenditionVideo)
			select {
			case <-done:
			case <-time.After(5 * time.Second):
				t.Fatal("the segmenter did not finish after both outputs ended")
			}
			if got := strings.Join(extinfs(store), " "); got != "2.000" {
				t.Fatalf("the store holds segments %q, want exactly the 2.000 s one (a 2.500 s segment is never published, and the one already cut is not lost)", got)
			}
			if data, ok := store.Segment(RenditionAAC, 0); !ok || len(data) == 0 {
				t.Fatalf("the published segment has an empty aac part: %v %d", ok, len(data))
			}
			if fired.Load() != 1 || s.Published() != 1 {
				t.Fatalf("onOverlong fired %d times and %d segments published; want 1 and 1", fired.Load(), s.Published())
			}
		})
	}
}

// An encoded generation never takes the copy cut or the over-long check: the
// same 2.5 s fragment is published as it always was.
func TestAnEncodedGenerationIgnoresTheCopyCut(t *testing.T) {
	s, store := newCopySegmenter(false, 2)
	var fired atomic.Int32
	s.onOverlong = func() { fired.Add(1) }
	s.fragment(RenditionVideo, vfrag(0, 2))
	s.fragment(RenditionVideo, vfrag(2, 2.5))
	s.fragment(RenditionVideo, vfrag(4.5, 2))
	runToEOF(s)
	if got := strings.Join(extinfs(store), " "); got != "2.000 2.500 2.000" {
		t.Fatalf("segments %q, want 2.000 2.500 2.000 as the seed cuts them", got)
	}
	if fired.Load() != 0 || s.Overlong() {
		t.Fatalf("an encoded generation was called over-long (fired %d)", fired.Load())
	}
}

// ---- the pipeline, with stand-in processes ----

// The probe says h264 with a 2 s keyframe interval, so generation 0 copies;
// the encoder stand-in writes one 3 s fragment, which is over-long. The
// generation ends at once, and the next spawn is an encode into the declared
// family, never a copy, with the 3 s segment never listed.
func TestAnOverLongCopiedSegmentRestartsTheRunEncoded(t *testing.T) {
	h := newHarness(t)
	long := file(t, "long.mp4", gopStream(75))
	good := file(t, "good.mp4", gopStream(50, 50))
	p := h.startAutomatic(probeAutomatic("2.000000"), func(s Spawn) []string {
		if s.Generation == 0 {
			return []string{"--fd-file", relaytest.FDFileArg(1, long), "--ignore-stdin-eof"}
		}
		return []string{"--fd-file", relaytest.FDFileArg(1, good), "--wait-stdin-eof"}
	})
	feedRing(t, h)
	waitFor(t, "the second generation's spawn", 20*time.Second, func() bool { return relaytest.SpawnCount(h.spawnLog) >= 2 })
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := p.Store().WaitSegment(ctx); err != nil {
		t.Fatalf("no segment: %v\n%s", err, h.logs.String())
	}
	h.mu.Lock()
	spawns := append([]Spawn(nil), h.spawns...)
	h.mu.Unlock()
	if !spawns[0].copies() || spawns[0].Engine != EngineCopy {
		t.Fatalf("generation 0 did not copy: engine %s argv %s", spawns[0].Engine, joinArgs(spawns[0].Argv))
	}
	if spawns[1].Generation != 1 || spawns[1].copies() || !strings.Contains(joinArgs(spawns[1].Argv), "libx264") {
		t.Fatalf("generation 1 was not an encode: %+v", spawns[1])
	}
	if got := p.Engine(); got != EngineSoftware {
		t.Fatalf("Engine() = %s after the restart, want software", got)
	}
	for _, e := range extinfs(p.Store()) {
		if e == "3.000" {
			t.Fatalf("the over-long 3 s segment was published: %v", extinfs(p.Store()))
		}
	}
	if !strings.Contains(h.logs.String(), "would round above the target duration") {
		t.Fatalf("the over-long ending was not logged:\n%s", h.logs.String())
	}
}

// An over-long ending is counted in the 3-in-60 s restart bound as a death is:
// one over-long copy and two deaths after their first segment are three, and
// the output fails at the third generation, where without the count it would
// need a fourth. (The plan's "three over-long generations" cannot arise: the
// first sets forceEncode for the rest of the run, so no later generation copies.)
func TestOverLongRestartsCountTowardTheRestartBound(t *testing.T) {
	h := newHarness(t)
	long := file(t, "long.mp4", gopStream(75))
	dying := file(t, "dying.mp4", gopStream(50, 50))
	p := h.startAutomatic(probeAutomatic("2.000000"), func(s Spawn) []string {
		if s.Generation == 0 {
			return []string{"--fd-file", relaytest.FDFileArg(1, long), "--ignore-stdin-eof"}
		}
		return []string{"--fd-file", relaytest.FDFileArg(1, dying)}
	})
	feedRing(t, h)
	waitDone(t, p, 30*time.Second)
	if !errors.Is(p.Err(), ErrFailed) {
		t.Fatalf("Err = %v, want ErrFailed at the third ending\n%s", p.Err(), h.logs.String())
	}
	if n := relaytest.SpawnCount(h.spawnLog); n != 3 {
		t.Fatalf("spawned %d generations, want 3: the over-long ending must count as the first of the three", n)
	}
}

// R74: a copy generation whose two attempts both exit before their first
// segment is encoded into the declared family on the same input, and the
// channel is not marked. The stand-in fails whenever the argv copies.
func TestAFailedCopyFallsBackToAnEncode(t *testing.T) {
	h := newHarness(t)
	initOnly := file(t, "init.mp4", videoInit(0))
	good := file(t, "good.mp4", gopStream(50, 50))
	p := h.startAutomatic(probeAutomatic("2.000000"), func(s Spawn) []string {
		if s.copies() {
			return []string{"--fd-file", relaytest.FDFileArg(1, initOnly), "--exit-code", "1"}
		}
		return []string{"--fd-file", relaytest.FDFileArg(1, good), "--wait-stdin-eof"}
	})
	feedRing(t, h)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := p.Store().WaitSegment(ctx); err != nil {
		t.Fatalf("no segment: %v\n%s", err, h.logs.String())
	}
	h.mu.Lock()
	spawns := append([]Spawn(nil), h.spawns...)
	h.mu.Unlock()
	if len(spawns) != 3 {
		t.Fatalf("%d spawns, want the two copy attempts and one encode", len(spawns))
	}
	for i, want := range []struct {
		copies  bool
		engine  Engine
		attempt int
	}{{true, EngineCopy, 1}, {true, EngineCopy, 2}, {false, EngineSoftware, 3}} {
		if spawns[i].copies() != want.copies || spawns[i].Engine != want.engine || spawns[i].Attempt != want.attempt {
			t.Fatalf("spawn %d: copies=%t engine=%s attempt=%d; want copies=%t engine=%s attempt=%d\nargv %s",
				i, spawns[i].copies(), spawns[i].Engine, spawns[i].Attempt, want.copies, want.engine, want.attempt, joinArgs(spawns[i].Argv))
		}
	}
	if !strings.Contains(joinArgs(spawns[2].Argv), "libx264") {
		t.Fatalf("the fallback did not encode: %s", joinArgs(spawns[2].Argv))
	}
	if err := p.Err(); err != nil {
		t.Fatalf("Err = %v: the channel would be marked though the fallback encode works", err)
	}
	if got := p.Engine(); got != EngineSoftware {
		t.Fatalf("Engine() = %s, want software", got)
	}
	if !strings.Contains(h.logs.String(), "a copy generation exited before its first segment twice; encoding it into the declared family") {
		t.Fatalf("the fallback was not logged:\n%s", h.logs.String())
	}
}

// R74: only when the encode fails too does the generation, and so the channel's
// HLS output, fail: attempts 1 and 2 copy, 3 and 4 encode.
func TestAFailedCopyAndAFailedEncodeFailTheOutput(t *testing.T) {
	h := newHarness(t)
	initOnly := file(t, "init.mp4", videoInit(0))
	p := h.startAutomatic(probeAutomatic("2.000000"), func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, initOnly), "--exit-code", "1"}
	})
	feedRing(t, h)
	waitDone(t, p, 30*time.Second)
	if !errors.Is(p.Err(), ErrFailed) {
		t.Fatalf("Err = %v, want ErrFailed", p.Err())
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.spawns) != 4 {
		t.Fatalf("%d spawns, want 4 (copy, copy, encode, encode)", len(h.spawns))
	}
	for i, s := range h.spawns {
		if s.Attempt != i+1 || s.copies() != (i < 2) {
			t.Fatalf("spawn %d: attempt %d copies=%t", i, s.Attempt, s.copies())
		}
	}
}

// Ruling R42 and Decision 14: the watchdog's limits follow the pipeline's own
// target, and a test override wins in the seed's order.
func TestTheStallLimitsFollowTheTargetDuration(t *testing.T) {
	for _, c := range []struct {
		target         int
		stall, startup time.Duration
	}{{2, 10 * time.Second, 30 * time.Second}, {4, 20 * time.Second, 30 * time.Second}, {6, 30 * time.Second, 30 * time.Second}} {
		if stall, startup := stallLimits(c.target); stall != c.stall || startup != c.startup {
			t.Errorf("stallLimits(%d) = %v, %v; want %v, %v", c.target, stall, startup, c.stall, c.startup)
		}
	}
	for _, c := range []struct {
		name           string
		cfg            Config
		output         *Output
		stall, startup time.Duration
	}{
		{"no output yet", Config{}, nil, 10 * time.Second, 30 * time.Second},
		{"target 6, no overrides", Config{}, &Output{Target: 6}, 30 * time.Second, 30 * time.Second},
		{"target 6, StallTimeout 300ms", Config{StallTimeout: 300 * time.Millisecond}, &Output{Target: 6}, 300 * time.Millisecond, 900 * time.Millisecond},
		{"target 6, both overrides", Config{StallTimeout: 300 * time.Millisecond, StartupStallTimeout: 5 * time.Second}, &Output{Target: 6}, 300 * time.Millisecond, 5 * time.Second},
		{"target 6, only the startup override", Config{StartupStallTimeout: 5 * time.Second}, &Output{Target: 6}, 30 * time.Second, 5 * time.Second},
	} {
		p := &Pipeline{cfg: c.cfg, output: c.output}
		if stall, startup := p.watchLimits(); stall != c.stall || startup != c.startup {
			t.Errorf("%s: watchLimits = %v, %v; want %v, %v", c.name, stall, startup, c.stall, c.startup)
		}
	}
	if got := (&Pipeline{}).TargetDuration(); got != 2*time.Second {
		t.Errorf("TargetDuration before the output is decided = %v, want 2s", got)
	}
	if got := (&Pipeline{output: &Output{Target: 6}}).TargetDuration(); got != 6*time.Second {
		t.Errorf("TargetDuration = %v, want 6s", got)
	}
}

// The 4a-1a r5 hand-off: no attempt's noteInit may complete a codec set with a
// string an earlier attempt recorded before it failed. Attempt 1 writes a video
// init (avc1.4d401e) and exits with no audio init and no segment; attempt 2
// writes its aac init first and holds its video until the test has seen that
// init stored, and only then writes a video init of avc1.64002a. Without the
// reset attempt 2's aac init completes the map with attempt 1's stale video
// string and Ready adopts it. (Transcode mode: no ceiling rewrites a string.)
func TestEachAttemptStartsWithNoCodecsFromTheLastOne(t *testing.T) {
	h := newHarness(t)
	dir := t.TempDir()
	stale := filepath.Join(dir, "stale.mp4")
	fresh := filepath.Join(dir, "fresh.mp4")
	aacInit := filepath.Join(dir, "aac.mp4")
	release := filepath.Join(dir, "release")
	staleInit := initSpec{trackID: 1, handler: "vide", timescale: 12800, movieTimescale: 1000, entry: avc1Entry(0x4d, 0x40, 0x1e)}.build()
	for path, data := range map[string][]byte{stale: staleInit, fresh: append(videoInit(0), gopStream(50, 50)[len(videoInit(0)):]...), aacInit: audioInit()} {
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	var attempt atomic.Int32
	p := h.startWith(probeWithAAC, func(c *Config) {
		c.Command = func(Spawn) (string, []string) {
			if attempt.Add(1) == 1 {
				return "sh", []string{"-c", "cat " + stale + "; exit 1"}
			}
			return "sh", []string{"-c", "cat " + aacInit + " >&3; until [ -e " + release + " ]; do sleep 0.02; done; cat " + fresh + "; sleep 60"}
		}
	}, func(Spawn) []string { return nil })
	feedRing(t, h)
	waitFor(t, "attempt 2's aac init to be stored", 20*time.Second, func() bool {
		_, ok := p.Store().Init(RenditionAAC, 0)
		return ok
	})
	if err := os.WriteFile(release, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := p.Ready(ctx); err != nil {
		t.Fatalf("Ready: %v\n%s", err, h.logs.String())
	}
	mv, err := p.Multivariant("/hls/T")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(mv), "avc1.4d401e") || !strings.Contains(string(mv), "avc1.64002a") {
		t.Fatalf("CODECS carries avc1.4d401e from a failed attempt, or lacks avc1.64002a:\n%s", mv)
	}
}

// The copied rendition's bandwidth is the maximum, never the replacement: the
// table's video rate stays the floor.
func TestTheMultivariantBandwidthCoversACopiedRendition(t *testing.T) {
	out := Output{
		Width: 640, Height: 360, FrameRate: Rational{25, 1},
		VideoMaxrate: 8_000_000, VideoBitrate: 6_000_000,
		PeakRate: 12_500_000, AverageRate: 10_000_000,
		Audio: []Rendition{{Name: RenditionAAC, Channels: 2}},
	}
	codecs := map[string]string{RenditionVideo: "avc1.64002a", RenditionAAC: "mp4a.40.2"}
	line := func(o Output) string {
		for _, l := range strings.Split(string(Multivariant(o, codecs, "/hls/T")), "\n") {
			if strings.HasPrefix(l, "#EXT-X-STREAM-INF:") {
				return l
			}
		}
		return ""
	}
	if got := line(out); !strings.Contains(got, "BANDWIDTH=12660000,AVERAGE-BANDWIDTH=10160000,") {
		t.Errorf("a copied 10 Mb/s window: %s", got)
	}
	out.PeakRate, out.AverageRate = 5_000_000, 4_000_000
	if got := line(out); !strings.Contains(got, "BANDWIDTH=8160000,AVERAGE-BANDWIDTH=6160000,") {
		t.Errorf("a window under the table must not lower it: %s", got)
	}
	out.PeakRate, out.AverageRate = 0, 0
	if got := line(out); !strings.Contains(got, "BANDWIDTH=8160000,AVERAGE-BANDWIDTH=6160000,") {
		t.Errorf("an output with no rates keeps the seed's figures: %s", got)
	}
}

var targetLine = regexp.MustCompile(`#EXT-X-TARGETDURATION:(\d+)`)

func TestTheMediaPlaylistCarriesThePipelinesTargetDuration(t *testing.T) {
	for _, c := range []struct {
		set  int
		want string
	}{{0, "2"}, {6, "6"}, {4, "4"}} {
		store := NewStore(time.Now)
		if c.set != 0 {
			store.SetTargetDuration(c.set)
		}
		store.publish(0, time.Now(), map[string]part{RenditionVideo: {data: []byte{1}, duration: 2}})
		playlist, _, _ := store.MediaPlaylist(RenditionVideo)
		if m := targetLine.FindStringSubmatch(string(playlist)); m == nil || m[1] != c.want {
			t.Errorf("SetTargetDuration(%d): %v in\n%s\nwant %s", c.set, m, playlist, c.want)
		}
	}
}

// The byte ceiling scales with the target: at 6, twenty-one 9 MiB segments
// (189 MiB) are all kept; at the default target the same run keeps only the
// newest 7 (63 MiB, under 64 MiB).
func TestTheByteCeilingScalesWithTheTargetDuration(t *testing.T) {
	publish := func(store *Store) {
		for i := 0; i < 21; i++ {
			store.publish(0, time.Now(), map[string]part{RenditionVideo: {data: make([]byte, 9<<20), duration: 2}})
		}
	}
	scaled := NewStore(time.Now)
	scaled.SetTargetDuration(6)
	publish(scaled)
	if n := len(scaled.segs); n != 21 {
		t.Errorf("at target 6 the store kept %d segments, want all 21", n)
	}
	plain := NewStore(time.Now)
	publish(plain)
	if n := len(plain.segs); n != 7 {
		t.Errorf("at the default target the store kept %d segments, want the newest 7", n)
	}
}
