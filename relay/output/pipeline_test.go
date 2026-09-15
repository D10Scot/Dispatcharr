package output

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is this package's trampoline: the test binary re-executed with
// RELAY_STANDIN=1 becomes the stand-in remux rather than running tests. One per
// package that spawns it (relaytest/standin.go's own doc comment).
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// standInRemux is a Remux that spawns this test binary instead of ffmpeg.
//
// BOTH LISTS ARE SUPPLIED, never just Argv, because the default for ArgvNoBSF
// when only Argv is set is Argv itself -- which is right for a stand-in with no
// filter to drop, and wrong for the test whose whole subject is that the retry
// runs a DIFFERENT command line.
func standInRemux(t *testing.T, args ...string) Remux {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(args...)
	return Remux{Command: command, Argv: argv, ArgvNoBSF: argv}
}

// sourceRing is a channel's TS ring with some bytes already in it, so the
// pipeline's writer has something to feed its child.
func sourceRing(t *testing.T, packets int) *buffer.Ring {
	t.Helper()
	r := buffer.New(buffer.Config{BudgetBytes: buffer.ChunkBytes * 8, ChunkBytes: buffer.TSPacketSize * 16})
	if _, err := r.Write(relaytest.SyntheticTS(packets, 0x100)); err != nil {
		t.Fatalf("filling the source ring: %v", err)
	}
	return r
}

// waitFor polls until cond holds or the deadline passes, and reports whether it
// held. Callers phrase their own failure, so a shared helper never produces a
// message that names nothing.
func waitFor(cond func() bool, within time.Duration) bool {
	deadline := time.Now().Add(within)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return cond()
}

func TestThePipelineFeedsTheRingToItsRemuxAndPublishesWhatComesBack(t *testing.T) {
	// The whole shape end to end: fd 0 is the channel's ring, fd 1 is scanned
	// into an init segment and fragments. The stand-in ignores what it reads --
	// the subject here is the relay's reaction to a remux, and the bytes a REAL
	// remuxer produces are TestARealRemuxProducesAnInitSegmentThenFragments's.
	remux := standInRemux(t, "--fmp4-fragments", "6", "--fmp4-interval", "0.01")
	p, err := Start(t.Context(), Config{
		ChannelID: "pipeline-basic",
		Source:    sourceRing(t, 512),
		Retention: time.Minute,
		Remux:     remux,
	})
	if err != nil {
		t.Fatalf("Start returned %v", err)
	}
	t.Cleanup(p.Stop)

	frags := p.Fragments()
	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	if err := frags.WaitInit(ctx); err != nil {
		t.Fatalf("no init segment within ten seconds: %v", err)
	}
	// Six written, five publishable: the last has no successor to bound it
	// until the child ends, and the child stays alive. Waited for BEFORE the
	// shape check, because the init segment is stored the moment the first
	// moof arrives and the fragment that moof belongs to is not publishable
	// until the NEXT one -- so a shape check taken at WaitInit sees an init
	// segment and no fragment, every time.
	if !waitFor(func() bool { return frags.Head() >= 5 }, 10*time.Second) {
		t.Fatalf("the buffer holds %d fragments after ten seconds, want at least 5 of the six the remux wrote", frags.Head())
	}
	if problem := relaytest.FMP4ShapeProblem(append(frags.Init(), fragmentBytes(frags)...)); problem != "" {
		t.Fatalf("what the pipeline published is not an init segment followed by a fragment: %s", problem)
	}
}

func TestTheRemuxIsRestartedWithoutTheBitstreamFilterOnTheAacError(t *testing.T) {
	// manager.py:373-378 and :382-431: a non-AAC source makes ffmpeg reject
	// aac_adtstoasc, and the manager restarts it with FFMPEG_REMUX_CMD_NO_BSF.
	// The first generation writes the real error line and no fragments; the
	// second writes fragments and no error. A relay that did not restart would
	// leave the buffer empty forever, and a client would get an empty 200.
	t.Setenv(relaytest.StandInEnv, "1")
	command, failing := relaytest.StandInCommand("--fmp4-bsf-error", "--fmp4-exit")
	_, working := relaytest.StandInCommand("--fmp4-fragments", "4", "--fmp4-interval", "0.01")

	p, err := Start(t.Context(), Config{
		ChannelID: "pipeline-bsf",
		Source:    sourceRing(t, 512),
		Retention: time.Minute,
		Remux:     Remux{Command: command, Argv: failing, ArgvNoBSF: working},
	})
	if err != nil {
		t.Fatalf("Start returned %v", err)
	}
	t.Cleanup(p.Stop)

	ctx, cancel := context.WithTimeout(t.Context(), 15*time.Second)
	defer cancel()
	if err := p.Fragments().WaitInit(ctx); err != nil {
		t.Fatalf("no init segment within fifteen seconds (%v): the first generation produces none, so this can only come from the no-BSF retry", err)
	}
	if !waitFor(func() bool { return p.Fragments().Head() >= 3 }, 15*time.Second) {
		t.Fatalf("the buffer holds %d fragments, want at least 3 from the retried remux", p.Fragments().Head())
	}
}

func TestTheRetryIsNotRepeatedWhenItAlsoReportsTheBitstreamFilterError(t *testing.T) {
	// The bound: Python's retry runs FFMPEG_REMUX_CMD_NO_BSF, whose stderr
	// cannot carry the message because the filter is not in its argv, so a
	// second restart is unreachable there. Here BOTH lists report it, and the
	// generation bound is what stops the loop -- a pipeline that restarted on
	// every BSF line would spawn processes forever against a source it can
	// never play.
	remux := standInRemux(t, "--fmp4-bsf-error", "--fmp4-exit")
	p, err := Start(t.Context(), Config{
		ChannelID: "pipeline-bsf-twice",
		Source:    sourceRing(t, 512),
		Retention: time.Minute,
		Remux:     remux,
	})
	if err != nil {
		t.Fatalf("Start returned %v", err)
	}
	t.Cleanup(p.Stop)

	select {
	case <-p.Done():
	case <-time.After(20 * time.Second):
		t.Fatal("the pipeline was still running after twenty seconds: two generations of a child that exits at once should end it")
	}
	if !p.Fragments().Closed() {
		t.Fatal("the pipeline ended without closing its buffer, so a client waiting for an init segment would wait out the whole fifteen-second budget")
	}
}

func TestStopEndsTheRemuxAndClosesTheBuffer(t *testing.T) {
	// A client waiting on WaitInit or blocked in Wait must be woken by the
	// stop, which is what makes the refcount reaching zero end every reader
	// rather than stranding one.
	remux := standInRemux(t, "--fmp4-fragments", "2", "--fmp4-interval", "0.01")
	p, err := Start(t.Context(), Config{
		ChannelID: "pipeline-stop",
		Source:    sourceRing(t, 512),
		Retention: time.Minute,
		Remux:     remux,
	})
	if err != nil {
		t.Fatalf("Start returned %v", err)
	}

	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	if err := p.Fragments().WaitInit(ctx); err != nil {
		t.Fatalf("no init segment: %v", err)
	}

	start := time.Now()
	p.Stop()
	if took := time.Since(start); took > stopJoinWait {
		t.Fatalf("Stop took %s against a child that is only sleeping, want well under the %s join budget", took, stopJoinWait)
	}
	if !p.Fragments().Closed() {
		t.Fatal("Stop returned with the buffer still open: every client reading it would block until its own context ended")
	}
	select {
	case <-p.Done():
	default:
		t.Fatal("Stop returned before Done was closed, so the process had not been reaped")
	}
}

func TestASpawnFailureIsReportedByStartRatherThanSwallowed(t *testing.T) {
	// views.py:789-798 answers 500 when ensure_output_format fails, BEFORE the
	// StreamingHttpResponse exists. A Start that reported the failure
	// asynchronously would turn it into a 200 with an empty body -- the same
	// answer an init-segment timeout gives -- and make the two
	// indistinguishable to a client and to a log reader.
	_, err := Start(t.Context(), Config{
		ChannelID: "pipeline-nospawn",
		Source:    sourceRing(t, 8),
		Retention: time.Minute,
		Remux:     Remux{Command: "/nonexistent/dispatcharr-remux", Argv: []string{}, ArgvNoBSF: []string{}},
	})
	if err == nil {
		t.Fatal("Start returned no error for a command that does not exist")
	}
}

// fragmentBytes concatenates every resident fragment, for a shape assertion.
func fragmentBytes(f *buffer.Fragments) []byte {
	chunks, _, _ := f.Read(0)
	var out []byte
	for _, c := range chunks {
		out = append(out, c...)
	}
	return out
}
