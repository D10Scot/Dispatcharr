package channel

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is this package's trampoline (relaytest/standin.go).
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// standInSource is a TranscodeSource that spawns the stand-in with args. The
// URL is a placeholder the UDP filter reads and nothing else does.
func standInSource(t *testing.T, args ...string) *TranscodeSource {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(args...)
	return &TranscodeSource{Command: command, Argv: argv, URL: "http://provider.invalid/live.ts", UserAgent: "test/1.0"}
}

// transcodeTuning is testTuning with the two thresholds a transcode channel
// reads. NOT the defaults (1.0, 15s): 10.0 is the API's maximum
// buffering_speed (core/serializers.py:96) and the slow-trickle corpus opens
// above it and stays below it from its second record, which is what lets a
// detector test arm in milliseconds rather than after the tens of seconds a
// real cumulative average takes (row 4).
func transcodeTuning(speed float64, timeout time.Duration) Tuning {
	tuning := testTuning()
	tuning.BufferingSpeed = speed
	tuning.BufferingTimeout = timeout
	return tuning
}

func assetFile(t *testing.T, packets int) (string, []byte) {
	t.Helper()
	payload := relaytest.SyntheticTS(packets, 0x100)
	path := filepath.Join(t.TempDir(), "asset.ts")
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	return path, payload
}

// captureLog is a slog handler that keeps every line, so a test can assert
// what did and did not reach the log.
type captureLog struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (c *captureLog) logger() *slog.Logger {
	return slog.New(slog.NewTextHandler(&lockedWriter{c: c}, &slog.HandlerOptions{Level: slog.LevelDebug}))
}

func (c *captureLog) String() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.buf.String()
}

type lockedWriter struct{ c *captureLog }

func (w *lockedWriter) Write(p []byte) (int, error) {
	w.c.mu.Lock()
	defer w.c.mu.Unlock()
	return w.c.buf.Write(p)
}

func attachTranscode(t *testing.T, m *Manager, id string, source *TranscodeSource, tuning Tuning) (*Channel, func()) {
	t.Helper()
	ch, release, err := m.Attach(id, testClient("a"), func() (Started, error) {
		return Started{Source: source, Tuning: tuning}, nil
	})
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	return ch, release
}

func waitFor(t *testing.T, what string, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out after %s waiting for %s", timeout, what)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// THE TRANSCODE PATH END TO END AT THE CHANNEL: the child's fd 1 is the
// video, it reaches the ring as whole packets in order, and a child that ends
// cleanly is RETRIED exactly as a clean Proxy EOF is (input/manager.py:
// 1870-1875, then the retry loop): three runs of the same asset, then the
// source is exhausted and the channel ends in error.
func TestATranscodeProcessesFd1ReachesTheRingInOrder(t *testing.T) {
	path, payload := assetFile(t, 64)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	ch, release := attachTranscode(t, m, "transcode-1", standInSource(t, "-i", path), transcodeTuning(1.0, 15*time.Second))
	defer release()

	select {
	case <-ch.Done():
	case <-time.After(20 * time.Second):
		t.Fatal("the channel did not finish after the child copied its asset and exited three times")
	}
	if state := ch.State(); state != StateError {
		t.Fatalf("state = %q after three clean child exits, want %q (err %v)", state, StateError, ch.Err())
	}
	var exhausted *ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) || exhausted.Attempts != 3 {
		t.Fatalf("Err() = %v, want ErrSourcesExhausted after MAX_RETRIES attempts", ch.Err())
	}
	chunks, _, _ := ch.Ring().Read(0)
	got := bytes.Join(chunks, nil)
	// testTuning's chunk is four packets, so each run's last partial chunk
	// is held back by the packetiser -- and dropped by the switch-less
	// ResetPosition-free retry, which is Python's own shape: a reconnect
	// does not touch the buffer. Everything published must be the asset's
	// own packets in order, the index wrapping at each rerun.
	if len(got) == 0 || len(got) > 3*len(payload) {
		t.Fatalf("the ring holds %d bytes of a %d-byte asset run three times", len(got), len(payload))
	}
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the ring's bytes are not whole packets: %s", problem)
	}
	packets := len(payload) / buffer.TSPacketSize
	previous := -1
	for i := 0; i < len(got); i += buffer.TSPacketSize {
		idx := relaytest.PacketIndex(got[i : i+buffer.TSPacketSize])
		if idx != (previous+1)%packets && (previous < 0 || idx != 0) {
			t.Fatalf("packet at byte %d carries index %d after %d: out of order within a run", i, idx, previous)
		}
		previous = idx
	}
}

// The parsed preamble and the last progress record reach the channel's
// stats, rounded the way Python stores them. Expected values are read off
// the corpus (the shape CAPTURE.md guarantees), never typed as digits.
func TestParsedStderrReachesTheChannelsStats(t *testing.T) {
	path, _ := assetFile(t, 8)
	speeds := relaytest.CorpusSpeeds("normal")
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	// interval 0: the whole corpus is on stderr before the stand-in exits,
	// by construction -- RunStandIn joins its stderr pump before returning
	// (break-check 22) -- so the last record is the one the channel holds
	// when it stops.
	src := standInSource(t, "-i", path, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	ch, release := attachTranscode(t, m, "transcode-stats", src, transcodeTuning(0.1, 300*time.Second))
	defer release()
	<-ch.Done()

	stats := ch.Stats()
	want := map[string]struct{ got, want any }{
		"video_codec":    {deref(stats.VideoCodec), "h264"},
		"resolution":     {deref(stats.Resolution), "320x180"},
		"source_fps":     {deref(stats.SourceFPS), 25.0},
		"pixel_format":   {deref(stats.PixelFormat), "yuv420p"},
		"audio_codec":    {deref(stats.AudioCodec), "aac"},
		"sample_rate":    {deref(stats.SampleRate), 44100},
		"audio_channels": {deref(stats.AudioChannels), "mono"},
		"audio_bitrate":  {deref(stats.AudioBitrate), 66.0},
		"stream_type":    {deref(stats.StreamType), "mpegts"},
		"ffmpeg_speed":   {deref(stats.FFmpegSpeed), ffmpeg.Round(speeds[len(speeds)-1], 3)},
	}
	for name, tc := range want {
		if tc.got != tc.want {
			t.Errorf("%s = %v, want %v", name, tc.got, tc.want)
		}
	}
	if stats.FFmpegFPS == nil || stats.ActualFPS == nil || stats.FFmpegOutputBitrate == nil {
		t.Errorf("the progress record's fps, actual fps and bitrate did not all reach the stats: %+v", stats)
	}
	if stats.VideoBitrate != nil {
		t.Errorf("video_bitrate = %v: the corpus video line carries no kb/s, so Python never sets it", *stats.VideoBitrate)
	}
}

// Stream lines AFTER the "Output #0" line are the remux's own and must not
// overwrite the input's (input/manager.py:1041-1045, :1079-1082). Driven
// with a corpus whose output video line differs from its input one.
func TestOutputPhaseStreamLinesDoNotOverwriteTheInputs(t *testing.T) {
	corpus := filepath.Join(t.TempDir(), "phases.stderr")
	// Real ffmpeg 8.1.2 lines (the corpus preamble), with the OUTPUT video
	// line's resolution changed to something a remux could never produce
	// from this input, so an overwrite is unmistakable. A stderr line
	// edited for a test is the SYNTHETIC exception harness/ffmpeg_stderr.py
	// allows, and the reason is that a real ffmpeg cannot be made to print
	// an output resolution that differs from a copied input's.
	lines := []string{
		"Input #0, mpegts, from 'http://127.0.0.1:1/live.ts':",
		"  Stream #0:0[0x100]: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 320x180 [SAR 1:1 DAR 16:9], 25 fps, 25 tbr, 90k tbn, start 1.423222",
		"Output #0, mpegts, to 'pipe:1':",
		"  Stream #0:0: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 999x999 [SAR 1:1 DAR 16:9], q=2-31, 25 fps, 25 tbr, 90k tbn",
		"",
	}
	if err := os.WriteFile(corpus, []byte(strings.Join(lines, "\n")), 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--stderr-corpus", corpus, "--stderr-interval", "0")
	ch, release := attachTranscode(t, m, "transcode-phase", src, transcodeTuning(0.1, 300*time.Second))
	defer release()
	<-ch.Done()
	if got := deref(ch.Stats().Resolution); got != "320x180" {
		t.Fatalf("resolution = %v, want the INPUT's 320x180 -- the output phase's stream line overwrote it", got)
	}
}

// PARITY-MATRIX ROW 4's invariant on the stand-in path, sampled the way the
// Python pin samples it: the channel is never labelled buffering while the
// speed it reports is still at or above the threshold. The slow-trickle
// capture replayed at 20 ms a record, at the DEFAULT buffering_speed of 1.0
// (the corpus was captured against it), with a timeout nothing reaches.
//
// STATE IS READ BEFORE STATS, and the order is load-bearing: the reader
// writes the speed and THEN the state (stderrReader.progress), so a sample
// that reads the state as buffering is guaranteed a speed at least as new
// as the one that armed it. Read the other way round, a sample could pair
// the previous record's speed with the new state and fail for a reason
// that is not the mechanism.
func TestTheCapturedLeadIsNeverLabelledBufferingBeforeItCrosses(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("slow-trickle")
	const threshold = 1.0
	crossing := -1
	for idx, v := range speeds {
		if v < threshold {
			crossing = idx
			break
		}
	}
	if crossing <= 0 {
		t.Fatalf("slow-trickle does not open above %v and cross below it; re-derive (CAPTURE.md)", threshold)
	}
	for _, v := range speeds[crossing:] {
		if v >= threshold {
			t.Fatal("the capture climbs back above the threshold after crossing; the invariant below is no longer race-free -- re-derive (CAPTURE.md)")
		}
	}

	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02")
	ch, release := attachTranscode(t, m, "row4", src, transcodeTuning(threshold, 300*time.Second))
	defer release()

	type sample struct {
		state State
		speed *float64
	}
	var samples []sample
	waitFor(t, "the channel to reach buffering", 15*time.Second, func() bool {
		state := ch.State()
		samples = append(samples, sample{state, ch.Stats().FFmpegSpeed})
		return state == StateBuffering
	})
	lead := 0
	for _, s := range samples {
		if s.speed == nil {
			continue
		}
		if *s.speed >= threshold {
			lead++
			if s.state == StateBuffering {
				t.Fatalf("the channel was buffering while its reported speed was %vx", *s.speed)
			}
		}
	}
	if lead == 0 {
		t.Fatal("never observed the lead at all; poll faster or pace the corpus slower")
	}
	m.Stop("row4")
}

// slowTrickleTail checks the capture still has the shape rows 1 and 6 lean
// on: opens above the API's maximum buffering_speed, stays below it from the
// second record, and its below-threshold tail outlasts a 1s timeout.
func slowTrickleTail(t *testing.T) {
	t.Helper()
	speeds := relaytest.CorpusSpeeds("slow-trickle")
	const apiMax = 10.0 // core/serializers.py:96's max_value
	if speeds[0] <= apiMax {
		t.Fatal("slow-trickle no longer opens above the API's maximum buffering_speed; re-derive (CAPTURE.md)")
	}
	for _, v := range speeds[1:] {
		if v >= apiMax {
			t.Fatal("slow-trickle no longer stays below the API's maximum after its first record; re-derive")
		}
	}
	if tail := time.Duration(len(speeds)-1) * 20 * time.Millisecond; tail < 1400*time.Millisecond {
		t.Fatalf("the below-threshold tail is %s, too short to outlast the 1s timeout with margin; re-derive", tail)
	}
}

// PARITY-MATRIX ROW 1: ffmpeg's reported speed below buffering_speed,
// sustained longer than buffering_timeout, switches streams
// (input/manager.py:1064-1066, :1122-1191). The lever is buffering_speed at
// the API maximum, as the Python pin uses it: the capture opens above 10 and
// every later record is below, so the detector arms on record two, and a
// 1s timeout against a 1.5s tail (replayed at 20 ms a record, looping) is
// what fires it. The resolver hands over a second stand-in, whose child is
// then the one producing bytes.
//
// The clock starts BEFORE the source does, so it can only be EARLIER than
// the detector's own `since`; the switch landing under a second of it would
// mean the detector timed out early. (2c-4's timeout test learnt this the
// hard way: a clock taken after the first poll saw buffering reddened 2 in
// 8 under -race.)
func TestASustainedSubThresholdSpeedFailsTheChannelOver(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	// The alternate's child is SILENT on stderr: with the threshold at the
	// API maximum every record of any capture is below it, so a child that
	// replayed one would put the channel straight back into buffering and
	// hide the active edge the switch itself produces (:1190-1197).
	alternate := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504")
	ran := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: countingRuns{inner: alternate, runs: ran},
		Info:   SourceInfo{URL: "http://provider.invalid/alternate.ts", StreamID: 2, M3UProfileID: 1},
	}}}
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")

	started := time.Now()
	ch, release := attachWith(t, m, "row1", src, transcodeTuning(apiMax, time.Second), resolver)
	defer release()

	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	waitFor(t, "the switch", 15*time.Second, func() bool { return ch.Source().StreamID == 2 })
	if elapsed := time.Since(started); elapsed < time.Second {
		t.Fatalf("the channel switched %s after it started, before the 1s buffering_timeout could have elapsed", elapsed)
	}
	waitFor(t, "the alternate's child to run", 10*time.Second, func() bool { return ran.get() == 1 })
	waitFor(t, "the state to leave buffering", 10*time.Second, func() bool { return ch.State() == StateActive })

	if len(events.of("channel_buffering")) == 0 {
		t.Fatal("buffering never armed: no channel_buffering event")
	}
	failovers := events.of("channel_failover")
	if len(failovers) != 1 {
		t.Fatalf("channel_failover raised %d times, want 1: %+v", len(failovers), failovers)
	}
	if reason := failovers[0].Details["reason"]; reason != "buffering_timeout" {
		t.Fatalf("channel_failover reason = %v, want buffering_timeout", reason)
	}
	if d, _ := failovers[0].Details["duration"].(float64); d < 1.0 {
		t.Fatalf("channel_failover duration = %v, want at least the 1s buffering_timeout", d)
	}
	req := resolver.requests()
	if len(req) != 1 || len(req[0].Exclude) != 1 || req[0].Exclude[0] != 1 || req[0].CurrentStreamID != 1 {
		t.Fatalf("the resolver was asked %+v, want one request excluding stream 1 and naming it as current", req)
	}
	m.Stop("row1")
}

// PARITY-MATRIX ROW 6, issue #221, FIXED: MAX_STREAM_SWITCHES bounds a
// buffering-triggered switch as it bounds the main loop's. With the bound at
// ZERO the buffering path never asks the control plane at all, and -- unlike
// the main loop, which ends the channel at its bound -- the channel keeps
// playing, slowly, on the source it has. Python's stderr thread never touched
// the counter (input/manager.py:1134-1138), so this switched regardless.
func TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	alternate := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504")
	ran := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: countingRuns{inner: alternate, runs: ran},
		Info:   SourceInfo{URL: "http://provider.invalid/alternate.ts", StreamID: 2, M3UProfileID: 1},
	}}}
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")
	tuning := transcodeTuning(apiMax, time.Second)
	tuning.MaxStreamSwitches = 0

	ch, release := attachWith(t, m, "row6", src, tuning, resolver)
	defer release()

	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	// Three buffering_timeouts: the defect asked, and switched, inside the
	// first one.
	time.Sleep(3 * time.Second)
	if n := len(resolver.requests()); n != 0 {
		t.Fatalf("the resolver was asked %d times under MAX_STREAM_SWITCHES = 0: the buffering path ignored the bound (#221)", n)
	}
	if ch.Source().StreamID != 1 || ran.get() != 0 {
		t.Fatalf("the channel moved to stream %d (alternate ran %d times) with no switch budget", ch.Source().StreamID, ran.get())
	}
	if n := len(events.of("channel_failover")); n != 0 {
		t.Fatalf("channel_failover raised %d times with no switch budget", n)
	}
	select {
	case <-ch.Done():
		t.Fatalf("the channel ended (%v): a spent budget refuses the switch, it does not end a source that is still delivering", ch.Err())
	default:
	}
	m.Stop("row6")
}

// The other half of row 6: a buffering switch is COUNTED, so with a bound of
// one the first buffering timeout switches and the second, on the alternate,
// does not. The alternate replays the same slow capture, so it buffers too;
// the resolver holds a second answer, so only the bound can stop the ask.
func TestABufferingFailoverCountsAgainstMaxStreamSwitches(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	slow := func() *TranscodeSource {
		return standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
			"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")
	}
	resolver := &fakeResolver{answers: []Resolved{
		{Source: slow(), Info: SourceInfo{URL: "http://provider.invalid/two.ts", StreamID: 2, M3UProfileID: 1}},
		{Source: slow(), Info: SourceInfo{URL: "http://provider.invalid/three.ts", StreamID: 3, M3UProfileID: 1}},
	}}
	tuning := transcodeTuning(apiMax, time.Second)
	tuning.MaxStreamSwitches = 1

	ch, release := attachWith(t, m, "row6-count", slow(), tuning, resolver)
	defer release()

	waitFor(t, "the first switch", 15*time.Second, func() bool { return ch.Source().StreamID == 2 })
	waitFor(t, "the alternate to buffer", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	time.Sleep(3 * time.Second)
	if n := len(resolver.requests()); n != 1 {
		t.Fatalf("the resolver was asked %d times under MAX_STREAM_SWITCHES = 1, want 1: the buffering switch was not counted (#221)", n)
	}
	if id := ch.Source().StreamID; id != 2 {
		t.Fatalf("the channel is on stream %d, want 2", id)
	}
	m.Stop("row6-count")
}

// Issue #302, FIXED. The failure branch of the same arm (input/manager.py:
// 1210) left Python buffering with its clock unchanged, so the very next
// progress record -- here every 20 ms -- timed out again and asked the
// control plane again. The detector now defers after a failed ask: the
// channel keeps playing and stays buffering, and consecutive asks are at
// least one buffering_timeout apart -- a LOWER BOUND ONLY.
//
// A SYNTHETIC ORDER, NOT A SYNTHETIC LINE, which the corpus rule permits with
// a reason (TestBufferingEndsWhenTheSpeedRecovers uses the same exception):
// the slow-trickle capture's own records, with its sub-threshold tail
// repeated, so the channel buffers once and stays buffering for five
// seconds. Replaying the capture with --stderr-loop instead would re-open
// every pass with a record above the threshold, end the buffering and
// restart the clock, and "still buffering" could not be asserted at all.
func TestABufferingTimeoutWithNoAlternateAsksOncePerTimeoutNotOnEveryRecord(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	const timeout = time.Second
	_, records := relaytest.SplitCorpus(relaytest.Corpus("slow-trickle"))
	body := append(append([]byte{}, records[0]...), '\r')
	for range 4 {
		for _, r := range records[1:] {
			body = append(body, r...)
			body = append(body, '\r')
		}
	}
	corpus := filepath.Join(t.TempDir(), "long-tail.stderr")
	if err := os.WriteFile(corpus, body, 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	resolver := &fakeResolver{} // every answer is ErrNoAlternate
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", corpus, "--stderr-interval", "0.02")

	ch, release := attachWith(t, m, "no-alt", src, transcodeTuning(apiMax, timeout), resolver)
	defer release()

	waitFor(t, "a third failed switch", 20*time.Second, func() bool { return len(resolver.requests()) >= 3 })
	if state := ch.State(); state != StateBuffering {
		t.Fatalf("state = %q, want buffering: a failed switch leaves the channel where it was", state)
	}
	at := resolver.callTimes()
	for i := 1; i < len(at); i++ {
		if gap := at[i].Sub(at[i-1]); gap < timeout {
			t.Fatalf("asks %d and %d were %s apart, under the %s buffering_timeout: the channel is asking on every record (#302)", i-1, i, gap, timeout)
		}
	}
	select {
	case <-ch.Done():
		t.Fatalf("the channel ended (%v): a failed buffering switch must not end the tune", ch.Err())
	default:
	}
	m.Stop("no-alt")
}

// ISSUE #299 at the channel: a transcode source whose ffmpeg is 6.x -- a
// user-supplied Stream Profile pointing at a system ffmpeg -- arms the
// buffering detector. The stand-in replays the real 6.1.1 slow-trickle
// capture with the threshold at the API maximum, above every record; before
// the fix the frame= gate dropped every record and the state never moved.
func TestAnFFmpeg6StreamCopyArmsTheBufferingDetector(t *testing.T) {
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("ffmpeg6-slow-trickle"), "--stderr-interval", "0.02")
	ch, release := attachTranscode(t, m, "ffmpeg6", src, transcodeTuning(apiMax, 300*time.Second))
	defer release()
	waitFor(t, "a speed reported off a 6.1.1 record", 10*time.Second, func() bool { return ch.Stats().FFmpegSpeed != nil })
	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	m.Stop("ffmpeg6")
}

// Recovery: a speed back at the threshold moves buffering to active, and
// only from buffering. Driven with the normal capture, whose records all sit
// between 0.1 and 10, first with the threshold above them (buffering from
// record one) and then a second source with the threshold below them.
func TestBufferingEndsWhenTheSpeedRecovers(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("normal")
	// A detector run entirely at the channel level: its Observe is unit
	// tested in package ffmpeg, so this asserts only the state edge.
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	// Threshold between the first record and the rest: buffering on record
	// two, and recovery never, because every later record is below it.
	// Then a second corpus pass with the threshold below everything.
	minimum, maximum := speeds[0], speeds[0]
	for _, v := range speeds {
		minimum = min(minimum, v)
		maximum = max(maximum, v)
	}
	corpus := filepath.Join(t.TempDir(), "recovery.stderr")
	// The capture's own records, then the capture's own FIRST record again:
	// a real line, re-ordered so the curve recovers. A synthetic ORDER, not
	// a synthetic line, which the corpus rule permits with a reason: real
	// ffmpeg's cumulative average never climbs back over a threshold it
	// has crossed, so no capture can show a recovery.
	_, records := relaytest.SplitCorpus(relaytest.Corpus("normal"))
	var body []byte
	for _, r := range records {
		body = append(body, r...)
		body = append(body, '\r')
	}
	body = append(body, records[0]...)
	body = append(body, '\r')
	if err := os.WriteFile(corpus, body, 0o600); err != nil {
		t.Fatal(err)
	}
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504", "--stderr-corpus", corpus, "--stderr-interval", "0.02")
	threshold := (minimum + maximum) / 2
	ch, release := attachTranscode(t, m, "recovery", src, transcodeTuning(threshold, 300*time.Second))
	defer release()
	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	waitFor(t, "recovery to active", 10*time.Second, func() bool { return ch.State() == StateActive })
	m.Stop("recovery")
}

// THE PROVIDER URL NEVER REACHES THE LOG, and the secret has exactly one
// source: the argv the stand-in echoes back on stderr, which is where a
// real ffmpeg's "Input #0, mpegts, from '<url>':" line puts it. The host is
// asserted PRESENT so the pass is redaction, not a log that dropped the
// line.
func TestAProviderURLInStderrNeverReachesTheLog(t *testing.T) {
	const secretURL = "http://provider.example:8080/live/subscriber/hunter2/9.ts?token=s3cr3t"
	path, _ := assetFile(t, 8)
	logs := &captureLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Log: logs.logger()})
	t.Cleanup(m.StopAll)

	src := standInSource(t, "-i", path, "--echo-argv", "-user_agent", "test/1.0", "-headers", "Referer: "+secretURL, "-x", secretURL)
	src.URL = secretURL
	ch, release := attachTranscode(t, m, "redact", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()

	got := logs.String()
	if !strings.Contains(got, "stand-in argv:") {
		t.Fatalf("the echoed argv line never reached the log, so nothing was redacted:\n%s", got)
	}
	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber", "token="} {
		if strings.Contains(got, secret) {
			t.Fatalf("the log carries %q from the provider URL:\n%s", secret, got)
		}
	}
	if !strings.Contains(got, "provider.example:8080") {
		t.Fatalf("the host was redacted too; an operator can no longer tell providers apart:\n%s", got)
	}
}

// A command that cannot be found ends the channel in error with a message
// that names the executable and nothing from argv.
func TestAMissingCommandFailsTheChannelWithoutEchoingArgv(t *testing.T) {
	logs := &captureLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Log: logs.logger()})
	t.Cleanup(m.StopAll)
	src := &TranscodeSource{Command: "relay-no-such-executable-2c4", Argv: []string{"-i", "http://p/live/u/hunter2/1.ts"}, URL: "http://p/live/u/hunter2/1.ts"}
	ch, release := attachTranscode(t, m, "missing", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()
	if ch.State() != StateError || ch.Err() == nil {
		t.Fatalf("state = %q, err = %v", ch.State(), ch.Err())
	}
	if strings.Contains(logs.String(), "hunter2") {
		t.Fatalf("the failure log echoes argv:\n%s", logs.String())
	}
	if !strings.Contains(ch.Err().Error(), "relay-no-such-executable-2c4") {
		t.Fatalf("the error lost the executable's name: %v", ch.Err())
	}
}

// The UDP filter, input/manager.py:808-812: on a udp:// upstream every
// argument carrying the user agent, or "user-agent"/"user_agent" in any
// case, is dropped; on any other upstream nothing is.
func TestTheUDPFilterDropsUserAgentArguments(t *testing.T) {
	argv := []string{"-user_agent", "VLC/3.0.20", "-headers", "User-Agent: VLC/3.0.20", "-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}
	udp := &TranscodeSource{Argv: argv, URL: "udp://239.0.0.1:1234", UserAgent: "VLC/3.0.20"}
	// "-headers" SURVIVES: the filter drops the arguments that carry the
	// user agent, not the flags that introduced them, so Python spawns a
	// dangling -headers whose value becomes the next argument (-i). A defect
	// of the Python relay's own, reproduced per D5 and recorded rather than
	// tidied; an earlier draft of this test expected the flag gone too.
	want := []string{"-headers", "-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}
	if got := udp.argv(); strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("UDP argv = %q, want %q", got, want)
	}
	http := &TranscodeSource{Argv: argv, URL: "http://p/1.ts", UserAgent: "VLC/3.0.20"}
	if got := http.argv(); strings.Join(got, " ") != strings.Join(argv, " ") {
		t.Fatalf("HTTP argv was filtered: %q", got)
	}
}

// The argv Django built is what the child receives, verbatim and in order:
// the stand-in echoes what it was given, and the log carries it. No URL in
// this argv, so nothing is redacted and the comparison is exact.
func TestTheBuiltArgvIsSpawnedVerbatim(t *testing.T) {
	path, _ := assetFile(t, 8)
	logs := &captureLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Log: logs.logger()})
	t.Cleanup(m.StopAll)
	extra := []string{"-user_agent", "VLC/3.0.20 LibVLC/3.0.20", "-c:v", "copy", "-metadata", "title=a b", "-f", "mpegts", "pipe:1"}
	args := append([]string{"-i", path, "--echo-argv"}, extra...)
	src := standInSource(t, args...)
	ch, release := attachTranscode(t, m, "argv", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()
	want := "stand-in argv: " + strings.Join(args, " ")
	if !strings.Contains(logs.String(), want) {
		t.Fatalf("the child did not receive the argv verbatim; want a log line carrying %q in:\n%s", want, logs.String())
	}
}

// A non-zero exit reaches the channel as an error carrying the child's own
// code (input/manager.py's returncode).
func TestANonZeroExitPutsTheChannelInError(t *testing.T) {
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--exit-after-bytes", "752", "--exit-code", "3")
	ch, release := attachTranscode(t, m, "exit3", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()
	var exited *ffmpeg.ErrExited
	if !errors.As(ch.Err(), &exited) || exited.Code != 3 {
		t.Fatalf("Err() = %v, want ErrExited{Code: 3}", ch.Err())
	}
	if ch.State() != StateError {
		t.Fatalf("state = %q, want %q", ch.State(), StateError)
	}
}

// VLC's "unable to open the MRL" ends the source (input/manager.py:1059-1064
// closes the socket on it), and only when the command is literally vlc:
// the stand-in is reached through a symlink named vlc first on PATH, which
// is how ToolFor sees "vlc" and routes the line directly.
func TestAVLCInputFailureEndsTheSource(t *testing.T) {
	dir := t.TempDir()
	if err := os.Symlink(os.Args[0], filepath.Join(dir, "vlc")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	corpus := filepath.Join(dir, "vlc.stderr")
	// VLC's own message (modules/... "unable to open the MRL"), the one
	// line log_parsers.py:170 matches. No VLC capture exists in the corpus;
	// this is the SYNTHETIC exception with its reason: it is a VLC line and
	// the corpus rule is about ffmpeg's.
	if err := os.WriteFile(corpus, []byte("[00007f] main input error: unable to open the MRL 'http://p/x'\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	t.Setenv(relaytest.StandInEnv, "1")
	_, argv := relaytest.StandInCommand("-i", path, "--dead-air-after-bytes", "1504", "--stderr-corpus", corpus, "--stderr-interval", "0")
	src := &TranscodeSource{Command: "vlc", Argv: argv, URL: "http://provider.invalid/live.ts", UserAgent: "x"}
	ch, release := attachTranscode(t, m, "vlc", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	select {
	case <-ch.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the source did not end on VLC's input failure")
	}
	if !errors.Is(ch.Err(), ErrInputFailed) {
		t.Fatalf("Err() = %v, want ErrInputFailed", ch.Err())
	}
}

// Cancelling the channel (a stop) kills the child and reports the
// cancellation, not the SIGKILL's exit status.
func TestStoppingTheChannelKillsTheChild(t *testing.T) {
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504", "--ignore-sigterm")
	ch, release := attachTranscode(t, m, "stop", src, transcodeTuning(1.0, 15*time.Second))
	waitFor(t, "the first chunk", 10*time.Second, func() bool { return ch.Ring().Head() >= 1 })
	release()
	select {
	case <-ch.Done():
	case <-time.After(5 * time.Second):
		t.Fatal("the channel did not stop within five seconds: the child was not killed")
	}
	if ch.State() != StateStopped {
		t.Fatalf("state = %q after a stop, want %q (err %v)", ch.State(), StateStopped, ch.Err())
	}
}

func deref(v any) any {
	switch p := v.(type) {
	case *string:
		if p != nil {
			return *p
		}
	case *int:
		if p != nil {
			return *p
		}
	case *float64:
		if p != nil {
			return *p
		}
	}
	return nil
}

// Global Constraint 8's ratchet for the one default this source carries.
func TestTranscodeSourceDefaultsMatchPython(t *testing.T) {
	var s TranscodeSource
	if got := s.chunkSize(); got != 8192 {
		t.Errorf("chunkSize() = %d, want 8192 (apps/proxy/config.py:7's CHUNK_SIZE, input/manager.py:1843)", got)
	}
	if ffmpeg.KillWait != 500*time.Millisecond {
		t.Errorf("ffmpeg.KillWait = %s, want 500ms (input/manager.py:1746's wait(timeout=0.5))", ffmpeg.KillWait)
	}
}

var _ = context.Background
