package output

import (
	"bytes"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// seededAC3Argv is core/migrations/0024_outputprofile.py's locked
// "Media Server (AC3 Audio)" profile, exactly as build_command() would return
// it: the `command` field first, then shlex.split of `parameters`
// (core/models.py:200-203).
//
// A LITERAL READ OFF THAT MIGRATION, token for token, and NOT computed from
// anything this package holds -- an expected value the code under test
// produced cannot fail. It is also the argv a real deployment runs: the
// migration ships this row locked and active, so it is what an operator
// selecting "Media Server (AC3 Audio)" gets.
func seededAC3Argv() []string {
	return []string{
		"ffmpeg",
		"-fflags", "+discardcorrupt+genpts+nobuffer",
		"-probesize", "512K",
		"-analyzeduration", "0",
		"-i", "pipe:0",
		"-map", "0",
		"-c:v", "copy",
		"-c:a", "ac3",
		"-b:a", "384k",
		"-max_muxing_queue_size", "4096",
		"-flush_packets", "1",
		"-mpegts_flags", "+pat_pmt_at_frames+resend_headers+initial_discontinuity",
		"-f", "mpegts", "pipe:1",
	}
}

// THE ONE TEST IN THIS PR THAT DRIVES A REAL TRANSCODE, on the production argv
// of a profile the migrations actually ship.
//
// WHAT IT BUYS OVER THE STAND-IN TESTS: everything else here substitutes a
// pass-through for the child, because the subject is the relay's reaction to a
// process. This one's subject is the bytes a real ffmpeg produces from the
// relay's own fd 0 and fd 1 wiring -- that `-i pipe:0 ... -f mpegts pipe:1`
// really works when its input is the channel's ring and its output is a
// buffer.Ring, that the result is still a transport stream the ring can
// packetise, and that the audio really was re-encoded.
//
// AAC IN, AC3 OUT, which is what makes the last assertion able to fail: the
// asset is built with AAC audio and the profile asks for AC3, so a relay that
// had somehow copied its input to its output would produce a stream whose
// audio codec is still AAC. ffprobe reads the codec back -- an independent
// tool, not this package.
func TestARealAC3ProfileTranscodesTheChannelsRing(t *testing.T) {
	ffmpegPath := requireFFmpeg(t)
	asset := buildFragmentableAsset(t, ffmpegPath)

	source := buffer.New(buffer.Config{
		BudgetBytes: len(asset) * 2,
		ChunkBytes:  buffer.TSPacketSize * 64,
	})
	if _, err := source.Write(asset); err != nil {
		t.Fatalf("filling the source ring: %v", err)
	}

	argv := seededAC3Argv()
	p, err := StartProfile(t.Context(), ProfileConfig{
		ChannelID:   "c-real-profile",
		ProfileID:   1,
		Source:      source,
		Command:     argv[0],
		Argv:        argv[1:],
		JoinBehind:  time.Minute,
		Retention:   time.Minute,
		ChunkBytes:  buffer.TSPacketSize * 64,
		BudgetBytes: len(asset) * 4,
	})
	if err != nil {
		t.Fatalf("starting the real transcode: %v", err)
	}
	t.Cleanup(p.Stop)

	out := p.Ring()
	if !waitFor(func() bool { return out.Head() >= 4 }, 30*time.Second) {
		t.Fatalf("the real transcode produced %d chunks in thirty seconds, want at least 4", out.Head())
	}

	var produced []byte
	chunks, _, _ := out.Read(0)
	for _, chunk := range chunks {
		produced = append(produced, chunk...)
	}
	if problem := relaytest.AlignmentProblem(produced); problem != "" {
		t.Fatalf("what the real transcode produced is not a transport stream: %s", problem)
	}
	if bytes.HasPrefix(asset, produced) {
		t.Fatal("the transcode's output is a prefix of its input: nothing was re-encoded")
	}

	// THE AUDIO CODEC, READ BACK BY ffprobe. The assertion that makes this a
	// transcode test rather than a plumbing test, and the one thing no
	// stand-in can produce.
	probe, err := exec.LookPath("ffprobe")
	if err != nil {
		t.Skip("ffprobe is not on PATH; the codec half of this test did NOT run")
	}
	cmd := exec.CommandContext(t.Context(), probe, // #nosec G204 -- a LookPath result and fixed arguments
		"-hide_banner", "-loglevel", "error",
		"-select_streams", "a:0", "-show_entries", "stream=codec_name",
		"-of", "default=nw=1:nk=1", "-f", "mpegts", "pipe:0")
	cmd.Stdin = bytes.NewReader(produced)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	codec, err := cmd.Output()
	if err != nil {
		t.Fatalf("ffprobe could not read the transcode's output: %v: %s", err, stderr.String())
	}
	// THE FIRST LINE ONLY. `-mpegts_flags +resend_headers` makes the muxer
	// repeat the PAT/PMT, and ffprobe reports the audio stream once per
	// program it finds -- measured: two identical "ac3" lines from this argv
	// on ffmpeg 9.0.1. Every line is checked rather than only the first, so a
	// stream that carried ac3 AND something else would still fail.
	lines := strings.Fields(strings.TrimSpace(string(codec)))
	if len(lines) == 0 {
		t.Fatal("ffprobe reported no audio stream in the transcode's output")
	}
	for _, got := range lines {
		if got != "ac3" {
			t.Fatalf("the transcode's audio codec is %q, want ac3: the asset's is aac and "+
				"core/migrations/0024_outputprofile.py's locked profile asks for -c:a ac3", got)
		}
	}
}
