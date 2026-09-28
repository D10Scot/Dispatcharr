package channel

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/hls"
)

// hlsStarter is the start func AttachHLS takes, counting its calls. The
// pipeline it builds is a REAL one whose probe is a process that sleeps: these
// tests are about the channel's registry and refcount, so the pipeline only
// has to exist, be stoppable and report Done -- what an encoder makes is
// relay/hls's own tests' and the E2E's.
type hlsStarter struct {
	calls   int32Counter
	started []*hls.Pipeline
}

func (s *hlsStarter) start(src hls.Source) (*hls.Pipeline, error) {
	s.calls.inc()
	p, err := hls.Start(context.Background(), hls.Config{
		ChannelID:    "test",
		Source:       src,
		ProbeCommand: func(int) (string, []string) { return "sleep", []string{"60"} },
	})
	if err == nil {
		s.started = append(s.started, p)
	}
	return p, err
}

func hlsChannel(t *testing.T) (*Manager, *Channel) {
	t.Helper()
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})
	t.Cleanup(m.StopAll)
	ch, _ := attachBlocking(t, m, "hls-chan", "ts", testTuning())
	// The run loop marks its first connection's boundary as it starts. Wait
	// for it, so a mark a test sets is not cleared by that first boundary.
	waitFor(t, "the channel's first boundary", 5*time.Second, func() bool {
		ch.boundaryMu.Lock()
		defer ch.boundaryMu.Unlock()
		return len(ch.boundaries) > 0
	})
	return m, ch
}

func doneWithin(t *testing.T, p *hls.Pipeline, what string) {
	t.Helper()
	select {
	case <-p.Done():
	case <-time.After(10 * time.Second):
		t.Fatalf("the pipeline did not stop within 10s: %s", what)
	}
}

func TestOneHLSPipelinePerKeyStopsAtZero(t *testing.T) {
	_, ch := hlsChannel(t)
	starter := &hlsStarter{}

	p1, started1, release1, err := ch.AttachHLS("hls", starter.start)
	if err != nil || !started1 {
		t.Fatalf("first AttachHLS: started %t, err %v", started1, err)
	}
	p2, started2, release2, err := ch.AttachHLS("hls", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	if p1 != p2 || started2 {
		t.Fatalf("second AttachHLS: same pipeline %t, started %t; want the shared pipeline and started false", p1 == p2, started2)
	}
	if starter.calls.get() != 1 {
		t.Fatalf("the start func ran %d times, want 1", starter.calls.get())
	}

	release1()
	select {
	case <-p1.Done():
		t.Fatal("the pipeline stopped while a session still held it")
	case <-time.After(200 * time.Millisecond):
	}
	if _, _, ok := ch.HLSStatus(); !ok {
		t.Fatal("HLSStatus reports no pipeline while one is registered")
	}
	release2()
	doneWithin(t, p1, "its last release")
	if _, _, ok := ch.HLSStatus(); ok {
		t.Fatal("HLSStatus still reports a pipeline after the last release")
	}
	release2() // exactly once: a second call must not disturb anything
}

// Decision 3: a release only ever decrements the pipeline it attached to. p1
// failed and was unregistered, p2 took its key; p1's session releases late,
// and p2 must not lose a reference to it.
func TestAStaleHLSReleaseCannotStopAFreshPipeline(t *testing.T) {
	_, ch := hlsChannel(t)
	starter := &hlsStarter{}

	p1, _, release1, err := ch.AttachHLS("hls", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	// p1 fails and is unregistered; the mark is cleared as the next boundary
	// does, so the next entry starts a fresh pipeline.
	ch.FailHLS("hls", p1, hls.ErrFailed)
	ch.clearHLSFailed()

	p2, started, release2, err := ch.AttachHLS("hls", starter.start)
	if err != nil || !started || p2 == p1 {
		t.Fatalf("the second entry: started %t, same pipeline %t, err %v; want a fresh one", started, p2 == p1, err)
	}

	release1() // stale: p1 is no longer key "hls"'s
	select {
	case <-p2.Done():
		t.Fatal("a stale release stopped the fresh pipeline")
	case <-time.After(300 * time.Millisecond):
	}
	if _, _, ok := ch.HLSStatus(); !ok {
		t.Fatal("the fresh pipeline was unregistered by a stale release")
	}
	release2()
	doneWithin(t, p2, "its own release")
	p1.Stop()
}

func TestTheMarkRefusesUntilTheNextBoundaryAndTheBoundaryStartsNothing(t *testing.T) {
	_, ch := hlsChannel(t)
	starter := &hlsStarter{}

	p, _, release, err := ch.AttachHLS("hls", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	ch.FailHLS("hls", p, hls.ErrNoVideo)
	release()
	p.Stop()
	if starter.calls.get() != 1 {
		t.Fatalf("setup started %d pipelines, want 1", starter.calls.get())
	}

	var failed *ErrHLSOutputFailed
	_, _, _, err = ch.AttachHLS("hls", starter.start)
	if !errors.As(err, &failed) || !errors.Is(err, hls.ErrNoVideo) {
		t.Fatalf("AttachHLS while marked = %v, want an ErrHLSOutputFailed carrying hls.ErrNoVideo", err)
	}
	if !errors.Is(ch.HLSFailed(), hls.ErrNoVideo) {
		t.Fatalf("HLSFailed() = %v, want the recorded reason", ch.HLSFailed())
	}
	if starter.calls.get() != 1 {
		t.Fatal("a refused attach still ran the start func")
	}

	// The next REAL source boundary: bytes were published, then a new
	// connection marks where its own begin. A connection that published
	// nothing is not one, and leaves the mark.
	ch.markBoundary()
	if ch.HLSFailed() == nil {
		t.Fatal("a connection that published nothing cleared the mark")
	}
	if _, err := ch.Ring().Write(make([]byte, buffer.TSPacketSize*8)); err != nil {
		t.Fatal(err)
	}
	ch.markBoundary()
	if ch.HLSFailed() != nil {
		t.Fatalf("the boundary did not clear the mark: %v", ch.HLSFailed())
	}
	if starter.calls.get() != 1 {
		t.Fatal("the boundary started a pipeline: a TS-only channel must trigger no encode (R19)")
	}
	if _, _, ok := ch.HLSStatus(); ok {
		t.Fatal("the boundary registered a pipeline")
	}

	p2, started, release2, err := ch.AttachHLS("hls", starter.start)
	if err != nil || !started {
		t.Fatalf("the entry after the boundary: started %t, err %v", started, err)
	}
	release2()
	doneWithin(t, p2, "its release")
}

// Decision 11, driving the exact window: stopOutputs has run and the ring is
// still open (it closes later in run's defers). Both attaches refuse, and
// nothing is registered.
func TestAttachHLSRefusesAnEndingChannel(t *testing.T) {
	_, ch := hlsChannel(t)
	starter := &hlsStarter{}

	p, _, release, err := ch.AttachHLS("hls", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	ch.stopOutputs()
	doneWithin(t, p, "stopOutputs")
	if ch.Ring().Closed() {
		t.Fatal("the ring closed with stopOutputs; the window this test names does not exist")
	}

	if _, _, _, err := ch.AttachHLS("hls", starter.start); !errors.Is(err, ErrChannelEnding) {
		t.Fatalf("AttachHLS after stopOutputs = %v, want ErrChannelEnding", err)
	}
	if _, ok := ch.AttachHLSExisting("hls", p); ok {
		t.Fatal("AttachHLSExisting succeeded after stopOutputs")
	}
	if _, _, ok := ch.HLSStatus(); ok {
		t.Fatal("a pipeline is registered on an ending channel: nothing will ever stop it")
	}
	if starter.calls.get() != 1 {
		t.Fatalf("the start func ran %d times, want 1 (the refused attach must not start one)", starter.calls.get())
	}
	release()
}

// FailHLS is identity-gated: a LATE call for a pipeline that is no longer the
// registered one (the watcher's, landing after finish and the store's close,
// by which time the next boundary may have cleared the mark and a fresh
// pipeline may be serving) must not re-mark the channel under it.
func TestAStaleFailHLSCannotReMarkAChannelWithAFreshPipeline(t *testing.T) {
	_, ch := hlsChannel(t)
	starter := &hlsStarter{}

	p1, _, release1, err := ch.AttachHLS("hls", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	ch.FailHLS("hls", p1, hls.ErrFailed) // the entry's own call: p1 is registered, so it marks
	if ch.HLSFailed() == nil {
		t.Fatal("the first FailHLS, while p1 was registered, did not mark the channel")
	}
	release1()
	ch.clearHLSFailed() // the next source boundary

	p2, started, release2, err := ch.AttachHLS("hls", starter.start)
	if err != nil || !started {
		t.Fatalf("the entry after the boundary: started %t, err %v", started, err)
	}
	ch.FailHLS("hls", p1, hls.ErrFailed) // the watcher's late call for p1
	if ch.HLSFailed() != nil {
		t.Fatalf("a stale FailHLS re-marked the channel (%v) although its fresh pipeline is serving", ch.HLSFailed())
	}
	joined, startedAgain, release3, err := ch.AttachHLS("hls", starter.start)
	if err != nil || startedAgain || joined != p2 {
		t.Fatalf("a new entry after the stale call: err %v, started %t, joined the fresh pipeline %t", err, startedAgain, joined == p2)
	}
	release3()
	release2()
	doneWithin(t, p2, "its last release")
	p1.Stop()
}
