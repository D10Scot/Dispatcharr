package output

import (
	"context"
	"errors"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// transcodePID is the PID the stand-in rewrites every packet to, and assetPID
// is the one sourceRing's asset carries. The rewrite is what makes "this came
// out of the transcode" observable: a pass-through stand-in copies its input,
// so without it the transcode's ring and the channel's hold the same bytes and
// nothing can tell them apart (a fixture that patches away its subject).
const (
	transcodePID = 0x1FF
	assetPID     = 0x100
)

// standInProfile is a ProfileConfig whose command is this test binary acting
// as a pass-through: `-i pipe:0` makes RunStandIn copy fd 0 to fd 1, which is
// structurally what an Output Profile does (raw TS in, TS out).
func standInProfile(t *testing.T, source *buffer.Ring, args ...string) ProfileConfig {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(
		append(args, "--ts-pid", strconv.Itoa(transcodePID), "-i", "pipe:0")...)
	return ProfileConfig{
		ChannelID: "c-profile",
		ProfileID: 3,
		Source:    source,
		Command:   command,
		Argv:      argv,
		// A JOIN WINDOW WIDER THAN THE FIXTURE, so the writer starts at the
		// ring's OLDEST chunk rather than at its head. With JoinBehind zero
		// the writer starts at the live head, which on a ring nothing is
		// still filling means it feeds the child nothing at all -- correct
		// behaviour, and a fixture that never produces a byte. The
		// production value is new_client_behind_seconds, which
		// output/profile/manager.py:180-184 reads for exactly this reason:
		// "so the buffer is pre-populated by the time the first client
		// connects".
		JoinBehind:  time.Minute,
		Retention:   time.Minute,
		ChunkBytes:  buffer.TSPacketSize * 16,
		BudgetBytes: buffer.ChunkBytes * 8,
	}
}

// THE REGISTRY KEY IS `mpegts:p<id>` WHATEVER THE CLIENT'S FORMAT, and the
// expected values are read off the Python lines rather than computed here.
//
// Two sources, deliberately: views.py:731-734 composes the key a CLIENT's
// format resolves to (`f'{fmt}:p{id}'`), and output/profile/manager.py builds
// the transcode's own namespace as the literal f"mpegts:p{self.profile_id}" at
// six sites regardless of that format. ProfileKey is the second; FormatKey is
// the first.
func TestTheProfileKeyIsMPEGTSWhateverTheClientFormat(t *testing.T) {
	if got := ProfileKey(3); got != "mpegts:p3" {
		t.Fatalf("ProfileKey(3) is %q, want output/profile/manager.py:303's mpegts:p3", got)
	}
	three := 3
	for _, tc := range []struct {
		format string
		id     *int
		want   string
	}{
		// views.py:731-734, both arms.
		{"mpegts", nil, "mpegts"},
		{"fmp4", nil, "fmp4"},
		{"mpegts", &three, "mpegts:p3"},
		{"fmp4", &three, "fmp4:p3"},
	} {
		if got := FormatKey(tc.format, tc.id); got != tc.want {
			t.Errorf("FormatKey(%q, %v) is %q, want views.py:731-734's %q", tc.format, tc.id, got, tc.want)
		}
	}
}

// THE TRANSCODE'S OUTPUT IS A SECOND RING OF MPEG-TS, realigned to 188 bytes
// by the ring itself exactly as StreamBuffer.add_chunk realigns the channel's
// own input (output/profile/manager.py:256's add_chunk).
func TestAProfileTranscodeFillsItsOwnRingFromTheChannels(t *testing.T) {
	source := sourceRing(t, 2048)
	p, err := StartProfile(t.Context(), standInProfile(t, source))
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	t.Cleanup(p.Stop)

	if p.Fragments() != nil {
		t.Fatal("an Output Profile transcode built a fragment buffer; its sink is a ring")
	}
	ring := p.Ring()
	if ring == nil {
		t.Fatal("the transcode has no output ring")
	}
	if !waitFor(func() bool { return ring.Head() >= 3 }, 15*time.Second) {
		t.Fatalf("the transcode's ring holds %d chunks after fifteen seconds, want at least 3", ring.Head())
	}

	chunks, _, _ := ring.Read(0)
	if len(chunks) == 0 {
		t.Fatal("the transcode's ring returned no chunks at its oldest cursor")
	}
	for i, chunk := range chunks {
		if problem := relaytest.AlignmentProblem(chunk); problem != "" {
			t.Fatalf("chunk %d of the transcode's ring is not a transport stream: %s", i, problem)
		}
		// AND THE BYTES CAME OUT OF THE CHILD, not out of the source ring: the
		// stand-in rewrote every packet's PID, so a pipeline that had somehow
		// copied its input into its output would carry the asset's instead.
		for offset := 0; offset < len(chunk); offset += relaytest.PacketSize {
			if got := relaytest.PacketPID(chunk[offset : offset+relaytest.PacketSize]); got != transcodePID {
				t.Fatalf("a packet in the transcode's ring carries PID %#x, want the child's %#x (the asset's is %#x)",
					got, transcodePID, assetPID)
			}
		}
	}
}

// A PROFILE WITH NO COMMAND FAILS BEFORE ANYTHING IS SPAWNED, and it does NOT
// fall back to the fMP4 remux. Config.command() returns RemuxCommand for an
// empty Command, which is why ProfileConfig does not reuse Config: an operator
// whose OutputProfile row has a blank command must get a failed tune, not an
// ffmpeg remux nobody asked for (Ruling R3).
func TestAProfileWithNoCommandIsRefusedRatherThanDefaultedToTheRemux(t *testing.T) {
	cfg := standInProfile(t, sourceRing(t, 64))
	cfg.Command = ""
	p, err := StartProfile(t.Context(), cfg)
	if p != nil {
		p.Stop()
		t.Fatal("a profile with no command started a pipeline")
	}
	if err == nil {
		t.Fatal("a profile with no command started without an error")
	}
	// errors.Is, NOT a substring. An earlier draft asserted
	// strings.Contains(err, "no command") and stayed GREEN with the guard
	// removed, because os/exec's own message for an empty Path is literally
	// "exec: no command" -- two sources for one string, which is hollow
	// shape 5, found by the break-check that was supposed to redden it.
	if !errors.Is(err, ErrProfileCommandAbsent) {
		t.Fatalf("the error is %q, want ErrProfileCommandAbsent", err)
	}
}

// THE BITSTREAM-FILTER RETRY IS THE REMUX'S ALONE. Python's
// OutputProfileManager._stderr_loop (output/profile/manager.py:270-295) logs
// every line and looks at none of them, where FMP4RemuxManager's watches for
// the aac_adtstoasc refusal and restarts without the filter
// (output/fmp4/manager.py:373-378). An operator whose Output Profile
// parameters happen to carry `-bsf:a aac_adtstoasc` therefore gets ONE dead
// process in Python, and must get one here.
//
// COUNTED IN SPAWNS, because a retry is a second spawn and nothing else in the
// pipeline's observable state distinguishes it from a process that simply
// ended. The remux's own retry is pinned the other way by
// TestTheRetryIsNotRepeatedWhenItAlsoReportsTheBitstreamFilterError, so this
// pair asserts both directions of the same switch.
func TestAProfileStderrIsNotWatchedForTheBitstreamFilterError(t *testing.T) {
	log := filepath.Join(t.TempDir(), "profile-spawns.log")
	cfg := standInProfile(t, sourceRing(t, 256), "--spawn-log", log, "--fmp4-bsf-error", "--fmp4-exit")
	p, err := StartProfile(t.Context(), cfg)
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	t.Cleanup(p.Stop)

	// THE WAIT IS NOT AN ASSERTION, and the order matters. A pipeline that
	// retried is still running when its first process has gone, so a Fatal
	// here would report "still running" where the mechanism under test is the
	// SPAWN. Fall through on the timeout so the count below names it -- the
	// break-check that patched `bsf` to true reddened on "still running"
	// before this was reordered, which is a true positive for a message that
	// does not say what happened.
	select {
	case <-p.Done():
	case <-time.After(15 * time.Second):
	}
	if got := relaytest.SpawnCount(log); got != 1 {
		t.Fatalf("the relay spawned %d transcodes for one Output Profile whose stderr named the bitstream filter, want 1: "+
			"the retry is the fMP4 remux's and output/profile/manager.py:270-295 has none", got)
	}
	// AND THE PIPELINE ENDED, which is the other half: a profile whose process
	// exited must not leave a supervisor waiting for a generation that will
	// never come.
	select {
	case <-p.Done():
	default:
		t.Fatal("the transcode is still running fifteen seconds after its only process exited")
	}
}

// STOPPING THE PIPELINE CLOSES ITS RING, which is what ends every client
// reading it -- the transcode's counterpart of the fragment buffer's close.
func TestStoppingAProfileTranscodeClosesItsRing(t *testing.T) {
	p, err := StartProfile(t.Context(), standInProfile(t, sourceRing(t, 512)))
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	ring := p.Ring()
	if !waitFor(func() bool { return ring.Head() >= 1 }, 15*time.Second) {
		t.Fatal("the transcode produced nothing before the stop")
	}
	p.Stop()
	if !ring.Closed() {
		t.Fatal("the stopped transcode's ring is still open, so a client reading it would never end")
	}
}

// A CANCELLED CONTEXT ENDS THE PIPELINE, which is what Channel.stopOutputs and
// the refcount both reach it through.
func TestACancelledContextEndsTheProfileTranscode(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	p, err := StartProfile(ctx, standInProfile(t, sourceRing(t, 512)))
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	cancel()
	select {
	case <-p.Done():
	case <-time.After(15 * time.Second):
		t.Fatal("the transcode outlived its context by fifteen seconds")
	}
}
