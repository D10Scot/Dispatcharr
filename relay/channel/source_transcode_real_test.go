package channel

import (
	"bytes"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The asset's duration, scripts/capture_ffmpeg_stderr.py:30's ASSET_SECONDS.
const realAssetSeconds = 8

// requireFFmpeg finds a real ffmpeg, and REFUSES TO SKIP UNDER CI: a skip
// there would turn parity-matrix row 4's only real-ffmpeg pin into a test
// that is green because it never ran, which is the "silence read as pass"
// hollow shape. go-tests.yml installs ffmpeg for exactly this test.
func requireFFmpeg(t *testing.T) string {
	t.Helper()
	path, err := exec.LookPath("ffmpeg")
	if err != nil {
		if os.Getenv("CI") != "" {
			t.Fatal("ffmpeg is not on PATH and CI is set: go-tests.yml must install it, because this is row 4's only real-ffmpeg pin")
		}
		t.Skip("ffmpeg is not on PATH; row 4's real-ffmpeg pin did NOT run on this host")
	}
	version, err := exec.CommandContext(t.Context(), path, "-version").Output() // #nosec G204 -- a LookPath result, "-version" only
	if err == nil {
		t.Logf("ffmpeg: %s", strings.SplitN(string(version), "\n", 2)[0])
	}
	return path
}

// buildRealAsset is scripts/capture_ffmpeg_stderr.py:40-52's asset, built
// the same way: eight seconds of lavfi test pattern and tone, H.264 and
// AAC in MPEG-TS, so a `-c copy` remux has real packets to copy.
func buildRealAsset(t *testing.T, ffmpegPath string) []byte {
	t.Helper()
	cmd := exec.CommandContext(t.Context(), ffmpegPath, // #nosec G204 -- a LookPath result and fixed arguments
		"-hide_banner", "-loglevel", "error", "-y",
		"-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=8",
		"-f", "lavfi", "-i", "sine=frequency=440:duration=8",
		"-c:v", "libx264", "-preset", "ultrafast", "-b:v", "400k", "-pix_fmt", "yuv420p",
		"-c:a", "aac", "-b:a", "64k", "-f", "mpegts", "pipe:1")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	asset, err := cmd.Output()
	if err != nil {
		t.Fatalf("ffmpeg could not build the asset: %v: %s", err, stderr.String())
	}
	if len(asset) < 100*buffer.TSPacketSize {
		t.Fatalf("the asset is only %d bytes", len(asset))
	}
	return asset
}

// PARITY-MATRIX ROW 4, WITH A REAL FFMPEG: speed= is ffmpeg's cumulative
// average since process start, so against an upstream held to a quarter of
// real time the reported speed OPENS well above 1.0 -- the probe and the
// first burst count as media time earned in almost no wall time -- and only
// crosses below it once that lead has burned off, tens of seconds later.
// The Python pin replays a capture of that curve; this drives the curve.
//
// The command is the PRODUCTION one: core/migrations/0003's
// `-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1` with the URL
// substituted, exactly what Django's build_command produces for the locked
// ffmpeg profile, no -loglevel, so the parser sees the default verbosity.
//
// What is asserted is the SHAPE (CAPTURE.md's rule): the first reported
// speed is above the threshold; buffering is never reported while the
// speed is at or above it; and the arming takes at least ArmingFloor of
// wall clock. The floor's derivation: with a media lead L seconds and an
// upstream at rate r, the cumulative average crosses 1.0 at t = L/(1-r);
// measured on this host at r = 0.25, the crossing came 18.7s in (ffmpeg
// 9.0.1), and the capture the Python pin replays crossed at 18-20s (ffmpeg
// 8.1.2). Four seconds is a floor an instantaneous-rate detector could not
// reach -- it would arm on the first progress record, half a second in --
// and comfortably below every measurement. Widen the floor if a real
// ffmpeg ever arms slower; never lower it towards a measurement.
const armingFloor = 4 * time.Second

func TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms(t *testing.T) {
	if testing.Short() {
		t.Skip("real ffmpeg for ~20s; run without -short")
	}
	ffmpegPath := requireFFmpeg(t)
	asset := buildRealAsset(t, ffmpegPath)

	// A quarter of the asset's OWN byte rate, scripts/capture_ffmpeg_stderr
	// .py:34's slow-trickle setting, expressed in relaytest's units: Rate is
	// a multiple of NominalByteRate, not of this asset's rate.
	assetRate := float64(len(asset)) / realAssetSeconds
	up := relaytest.NewUpstream(relaytest.Config{Payload: asset, Rate: 0.25 * assetRate / relaytest.NominalByteRate})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.ChunkBytes * 16})
	t.Cleanup(m.StopAll)
	tuning := testTuning()
	tuning.ChunkBytes, tuning.Retention = buffer.ChunkBytes, time.Minute
	tuning.BufferingSpeed, tuning.BufferingTimeout = 1.0, 300*time.Second
	src := &TranscodeSource{
		Command:   "ffmpeg", // the profile's command, so ToolFor routes to the ffmpeg parser
		Argv:      []string{"-i", up.URL(), "-c:v", "copy", "-c:a", "copy", "-f", "mpegts", "pipe:1"},
		URL:       up.URL(),
		UserAgent: "VLC/3.0.20 LibVLC/3.0.20",
	}
	ch, release := attachTranscode(t, m, "row4-real", src, tuning)
	defer release()

	type sample struct {
		at    time.Time
		state State
		speed *float64
	}
	var samples []sample
	var firstSpeedAt time.Time
	deadline := time.Now().Add(90 * time.Second)
	for {
		// State BEFORE stats, for the ordering reason the stand-in test
		// gives: the reader writes the speed and then the state.
		state := ch.State()
		speed := ch.Stats().FFmpegSpeed
		samples = append(samples, sample{time.Now(), state, speed})
		if speed != nil && firstSpeedAt.IsZero() {
			firstSpeedAt = time.Now()
		}
		if state == StateBuffering {
			break
		}
		if state == StateError || state == StateStopped {
			t.Fatalf("the channel ended (%s, %v) before the detector armed; ffmpeg's stderr is in the log above", state, ch.Err())
		}
		if time.Now().After(deadline) {
			t.Fatal("the detector never armed within ninety seconds against a quarter-speed upstream")
		}
		time.Sleep(100 * time.Millisecond)
	}
	armedAt := samples[len(samples)-1].at
	m.Stop("row4-real")

	var first *float64
	for _, s := range samples {
		if s.speed != nil {
			first = s.speed
			break
		}
	}
	if first == nil || *first <= tuning.BufferingSpeed {
		t.Fatalf("the first reported speed was %v; row 4 needs a lead ABOVE %v to burn off", deref(first), tuning.BufferingSpeed)
	}
	for _, s := range samples {
		if s.speed != nil && *s.speed >= tuning.BufferingSpeed && s.state == StateBuffering {
			t.Fatalf("buffering was reported while the speed was still %vx", *s.speed)
		}
	}
	if took := armedAt.Sub(firstSpeedAt); took < armingFloor {
		t.Fatalf("the detector armed %s after the first progress record, under the %s floor: either speed= "+
			"is no longer a cumulative average or the detector is not reading it", took, armingFloor)
	}
	t.Logf("first speed %vx; armed %s after the first record", *first, armedAt.Sub(firstSpeedAt).Round(100*time.Millisecond))
}
