package output

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// realAssetGOP is output_support.py:54's _PAYLOAD_GOP: at 25 fps a keyframe
// every twelve frames is one every ~0.48s, so a `-movflags frag_keyframe` remux
// produces a moof roughly twice a second rather than one for the whole asset.
//
// realAssetSeconds is EIGHT where output_support.py:53's _PAYLOAD_SECONDS is
// two, and the difference is not cosmetic. `delay_moov` holds the movie header
// until ffmpeg has seen enough of the input to write it, and MEASURED against
// ffmpeg 9.0.1: two seconds of this asset on fd 0 with the pipe held open
// produces ZERO bytes on fd 1, indefinitely, while eight seconds produces the
// init segment and fragments within about a second. The Python test does not
// hit this because harness.upstream.FakeUpstream LOOPS its payload, so its
// remux sees a continuous stream built from the same two seconds; this test
// hands the ring a finite asset once, so the asset itself has to be long
// enough. A two-second asset here fails as "no init segment within 15s",
// which reads as a broken pipeline and is not one.
const (
	realAssetSeconds = 8
	realAssetGOP     = 12
)

// requireFFmpeg finds a real ffmpeg and REFUSES TO SKIP UNDER CI, for the
// reason channel/source_transcode_real_test.go's own copy gives: a skip in CI
// turns the only test that drives a real remuxer into one that is green because
// it never ran, which is the "silence read as pass" hollow shape.
//
// A SECOND COPY, deliberately, because Go test helpers are not importable across
// packages and the alternative -- exporting it from relaytest -- would put a
// t.Skip decision into shared support where a reader of either test cannot see
// it. The two are five lines each and say the same thing about their own row.
func requireFFmpeg(t *testing.T) string {
	t.Helper()
	path, err := exec.LookPath("ffmpeg")
	if err != nil {
		if os.Getenv("CI") != "" {
			t.Fatal("ffmpeg is not on PATH and CI is set: go-tests.yml runs in the base image for exactly this test, which is the only one that drives a real remux")
		}
		t.Skip("ffmpeg is not on PATH; the real-remux test did NOT run on this host")
	}
	version, err := exec.CommandContext(t.Context(), path, "-version").Output() // #nosec G204 -- a LookPath result, "-version" only
	if err == nil {
		t.Logf("ffmpeg: %s", strings.SplitN(string(version), "\n", 2)[0])
	}
	return path
}

// buildFragmentableAsset is output_support.py's fragmentable_upstream_payload:
// a genuinely encoded two-second MPEG-TS with H.264 video and AAC audio, short
// keyframe interval, which a `-c copy` remux has real packets to carry.
//
// AAC RATHER THAN AC3, because the production argv's aac_adtstoasc filter is
// REQUIRED for AAC and errors for everything else -- so an asset with any other
// audio codec would send this test down the no-BSF retry and it would be
// testing that path instead of the one production takes first.
func buildFragmentableAsset(t *testing.T, ffmpegPath string) []byte {
	t.Helper()
	cmd := exec.CommandContext(t.Context(), ffmpegPath, // #nosec G204 -- a LookPath result and fixed arguments
		"-hide_banner", "-loglevel", "error", "-y",
		"-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=8",
		"-f", "lavfi", "-i", "sine=frequency=440:duration=8",
		"-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-b:v", "400k", "-pix_fmt", "yuv420p",
		"-c:a", "aac", "-b:a", "64k", "-f", "mpegts", "pipe:1")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	asset, err := cmd.Output()
	if err != nil {
		t.Fatalf("ffmpeg could not build the asset: %v: %s", err, stderr.String())
	}
	if problem := relaytest.AlignmentProblem(asset); problem != "" {
		t.Fatalf("the asset is not a whole number of TS packets: %s", problem)
	}
	return asset
}

// THE ONE TEST IN THIS PR THAT DRIVES A REAL REMUXER, and the reason it exists
// is the rule harness/README.md states and output_support.py repeats: the
// stand-in wherever the subject is the relay's REACTION to a process, real
// ffmpeg wherever the subject is the bytes a remuxer produces.
//
// Everything else here is driven from relaytest's synthetic box chain, which is
// deterministic and version-independent and proves the scanner agrees with
// ITSELF about where a fragment ends. Only this proves it agrees with ffmpeg:
// that `-movflags frag_keyframe+delay_moov+default_base_moof` really does put
// the ftyp and moov in front of the first moof, that a fragment really is
// moof-then-mdat, and that the production argv really produces fragmented MP4
// from an MPEG-TS on fd 0.
//
// It is the Go counterpart of
// test_fmp4_output.py::test_an_fmp4_client_receives_an_init_segment_and_fragments,
// and it asserts the same shape through a deliberately independent box walker
// (relaytest.MP4Boxes, never the scanner) for that test's stated reason.
func TestARealRemuxProducesAnInitSegmentThenFragments(t *testing.T) {
	if testing.Short() {
		t.Skip("real ffmpeg; run without -short")
	}
	ffmpegPath := requireFFmpeg(t)
	asset := buildFragmentableAsset(t, ffmpegPath)

	// The whole asset in the ring before the pipeline starts, so the remux is
	// never waiting on an upstream: what is being measured is the remux and
	// the scanner, not a pacing.
	source := buffer.New(buffer.Config{BudgetBytes: len(asset) * 4, ChunkBytes: buffer.TSPacketSize * 200})
	if _, err := source.Write(asset); err != nil {
		t.Fatalf("filling the source ring: %v", err)
	}

	// THE PRODUCTION COMMAND AND ARGV, with no substitution at all: a zero
	// Remux is RemuxCommand and RemuxArgv(). A test that supplied its own
	// argument list here would prove that SOME ffmpeg invocation fragments,
	// not that the one output/fmp4/manager.py:32 ships does.
	p, err := Start(t.Context(), Config{
		ChannelID: "real-remux",
		Source:    source,
		Retention: time.Minute,
		// A join window as long as the retention, so the writer starts at the
		// OLDEST resident chunk rather than at the head. It matters here and
		// not in production for a reason worth stating: the writer positions
		// itself once, the way manager.py:208-212 does, and this ring is
		// already full and no longer growing -- a head-positioned writer would
		// wait forever for a chunk that is never coming, and the failure would
		// read as "the remux produced nothing" rather than "it was fed
		// nothing". A live channel's ring is still being written to, so the
		// same positioning reaches bytes within JoinBehind.
		JoinBehind: time.Minute,
	})
	if err != nil {
		t.Fatalf("Start returned %v: the production remux could not be spawned", err)
	}
	t.Cleanup(p.Stop)

	frags := p.Fragments()
	ctx, cancel := context.WithTimeout(t.Context(), InitSegmentTimeout)
	defer cancel()
	if err := frags.WaitInit(ctx); err != nil {
		t.Fatalf("no init segment within %s: %v. The remux's own stderr is in the log above", InitSegmentTimeout, err)
	}

	// Two fragments, not one: one proves a moof was found, two prove a
	// BOUNDARY was found, and the boundary is what the scanner is for.
	if !waitFor(func() bool { return frags.Head() >= 2 }, 20*time.Second) {
		t.Fatalf("the buffer holds %d fragments after twenty seconds against a %ds asset at a %d-frame keyframe interval, want at least 2",
			frags.Head(), realAssetSeconds, realAssetGOP)
	}

	init := frags.Init()
	if len(init) == 0 {
		t.Fatal("the init segment is empty")
	}
	// The init segment on its own is ftyp then moov and nothing else: a
	// scanner that split one byte late would carry the first moof into it, and
	// a player handed that would see a fragment before it had a movie header.
	_, _, initTypes := relaytest.MP4Boxes(init)
	if len(initTypes) < 2 || initTypes[0] != "ftyp" || initTypes[1] != "moov" {
		t.Fatalf("the init segment's boxes are %v, want ftyp then moov", initTypes)
	}
	for _, boxType := range initTypes {
		if boxType == "moof" || boxType == "mdat" {
			t.Fatalf("the init segment carries a %s box: the split ran past the first moof, and every client is handed a fragment ahead of the header that describes it", boxType)
		}
	}

	// And each published fragment is moof then mdat, on its own, which is what
	// a player appends to the init segment.
	published, _, _ := frags.Read(0)
	for i, fragment := range published {
		_, _, types := relaytest.MP4Boxes(fragment)
		if len(types) < 2 || types[0] != "moof" || types[1] != "mdat" {
			t.Fatalf("published fragment %d's boxes are %v, want moof then mdat", i, types)
		}
	}

	// Finally the whole shape a client receives: the init segment followed by
	// the fragments, through the same helper the Python suite's
	// assert_fmp4_init_then_fragment applies to a real tune's body.
	whole := append(append([]byte(nil), init...), fragmentBytes(frags)...)
	if problem := relaytest.FMP4ShapeProblem(whole); problem != "" {
		t.Fatalf("what a client would receive is not playable fragmented MP4: %s", problem)
	}
	t.Logf("%d-byte init segment, %d fragments from a %d-byte asset", len(init), frags.Head(), len(asset))
}
