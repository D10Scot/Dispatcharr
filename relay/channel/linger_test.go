package channel

import (
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/hls"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// fakeTimers is ManagerConfig.AfterFunc as a test wants it: every timer is
// recorded and none fires until the test says so.
type fakeTimers struct {
	mu     sync.Mutex
	timers []*fakeTimer
}

type fakeTimer struct {
	d       time.Duration
	f       func()
	stopped bool
	fired   bool
	owner   *fakeTimers
}

func (ft *fakeTimers) afterFunc(d time.Duration, f func()) func() bool {
	ft.mu.Lock()
	defer ft.mu.Unlock()
	t := &fakeTimer{d: d, f: f, owner: ft}
	ft.timers = append(ft.timers, t)
	return func() bool {
		ft.mu.Lock()
		defer ft.mu.Unlock()
		was := !t.stopped && !t.fired
		t.stopped = true
		return was
	}
}

// pending are the timers neither stopped nor fired.
func (ft *fakeTimers) pending() []*fakeTimer {
	ft.mu.Lock()
	defer ft.mu.Unlock()
	var out []*fakeTimer
	for _, t := range ft.timers {
		if !t.stopped && !t.fired {
			out = append(out, t)
		}
	}
	return out
}

// fire runs the timer's function on the test's goroutine, as its own would.
func (t *fakeTimer) fire() {
	t.owner.mu.Lock()
	t.fired = true
	t.owner.mu.Unlock()
	t.f()
}

func (t *fakeTimer) wasStopped() bool {
	t.owner.mu.Lock()
	defer t.owner.mu.Unlock()
	return t.stopped
}

// tsSource is a source that keeps writing whole TS packets until it is
// stopped, so an HLS pipeline's probe has bytes to read.
type tsSource struct{}

func (tsSource) Run(ctx context.Context, w io.Writer) error {
	packets := bytes.Repeat(append([]byte{0x47}, make([]byte, buffer.TSPacketSize-1)...), 4)
	for {
		if _, err := w.Write(packets); err != nil {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(20 * time.Millisecond):
		}
	}
}

// readyStarter is AttachHLS's start func for a pipeline that becomes READY: its
// probe answers and its encoder writes both inits and a run of fragments, as
// httpapi's hlsFixture's good mode does (the seed's hlsStarter never becomes
// ready: its probe sleeps).
type readyStarter struct {
	t       *testing.T
	dir     string
	calls   int32Counter
	mu      sync.Mutex
	started []*hls.Pipeline
}

func newReadyStarter(t *testing.T) *readyStarter {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	s := &readyStarter{t: t, dir: t.TempDir()}
	for name, data := range map[string][]byte{
		"probe.json": relaytest.HLSProbeJSON(true, true),
		"vfull.mp4":  relaytest.HLSVideoStream(20, 50),
		"afull.mp4":  relaytest.HLSAACStream(200),
	} {
		if err := os.WriteFile(filepath.Join(s.dir, name), data, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	t.Cleanup(func() {
		s.mu.Lock()
		defer s.mu.Unlock()
		for _, p := range s.started {
			p.Stop()
		}
	})
	return s
}

func (s *readyStarter) start(src hls.Source) (*hls.Pipeline, error) {
	s.calls.inc()
	p, err := hls.Start(context.Background(), hls.Config{
		ChannelID: "test",
		Source:    src,
		ExitGrace: 300 * time.Millisecond,
		ProbeCommand: func(int) (string, []string) {
			return relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(1, filepath.Join(s.dir, "probe.json")))
		},
		Command: func(hls.Spawn) (string, []string) {
			return relaytest.StandInCommand(
				"--fd-file", relaytest.FDFileArg(1, filepath.Join(s.dir, "vfull.mp4")),
				"--fd-file", relaytest.FDFileArg(3, filepath.Join(s.dir, "afull.mp4")),
				"--wait-stdin-eof")
		},
	})
	if err == nil {
		s.mu.Lock()
		s.started = append(s.started, p)
		s.mu.Unlock()
	}
	return p, err
}

func lingerTuning() Tuning {
	tuning := testTuning()
	tuning.RewindWindow = 60 * time.Minute
	tuning.RewindLinger = 300 * time.Second
	return tuning
}

// lingerRig is a manager on the fake timers with a releaser and a removal log.
type lingerRig struct {
	t      *testing.T
	m      *Manager
	timers *fakeTimers
	rel    *releaser
	mu     sync.Mutex
	sites  []string
}

func newLingerRig(t *testing.T, mutate func(*ManagerConfig)) *lingerRig {
	t.Helper()
	g := &lingerRig{t: t, timers: &fakeTimers{}, rel: newReleaser(false)}
	cfg := ManagerConfig{
		BudgetBytes: buffer.TSPacketSize * 400,
		StopWait:    2 * time.Second,
		Release:     g.rel.release,
		AfterFunc:   g.timers.afterFunc,
	}
	if mutate != nil {
		mutate(&cfg)
	}
	g.m = NewManager(cfg)
	g.m.afterRemove = func(_ *Channel, site string) {
		g.mu.Lock()
		g.sites = append(g.sites, site)
		g.mu.Unlock()
	}
	t.Cleanup(g.m.StopAll)
	return g
}

func (g *lingerRig) removals() []string {
	g.mu.Lock()
	defer g.mu.Unlock()
	return append([]string(nil), g.sites...)
}

// attach registers a client on the channel, starting it on a source that
// writes TS.
func (g *lingerRig) attach(id, clientID string, tuning Tuning) (*Channel, func()) {
	g.t.Helper()
	ch, release, err := g.m.Attach(id, testClient(clientID), func() (Started, error) {
		return Started{Source: tsSource{}, Tuning: tuning, Info: SourceInfo{M3UProfileID: 1}}, nil
	})
	if err != nil {
		g.t.Fatalf("Attach(%s): %v", id, err)
	}
	return ch, release
}

// session is one HLS session as a departure runs it: the pipeline reference
// (the output release) and the registry entry (the Attach release), in that
// order.
type session struct {
	pipeline   *hls.Pipeline
	releaseOut func()
	releaseCli func()
}

func (s *session) end() {
	s.releaseOut()
	s.releaseCli()
}

func (g *lingerRig) session(ch *Channel, clientID, key string, starter *readyStarter) *session {
	g.t.Helper()
	release := func() {}
	if clientID != "" {
		var err error
		var c *Channel
		c, release, err = g.m.Attach(ch.ID(), testClient(clientID), nil)
		if err != nil || c != ch {
			g.t.Fatalf("Attach(%s) to the running channel: %v", clientID, err)
		}
	}
	p, _, out, err := ch.AttachHLS(key, starter.start)
	if err != nil {
		g.t.Fatalf("AttachHLS(%s): %v", key, err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := p.Ready(ctx); err != nil {
		g.t.Fatalf("the pipeline never became ready: %v", err)
	}
	return &session{pipeline: p, releaseOut: out, releaseCli: release}
}

// firstSession starts a channel with its first client and an HLS pipeline.
func (g *lingerRig) firstSession(tuning Tuning, starter *readyStarter) (*Channel, *session) {
	g.t.Helper()
	ch, release := g.attach("chan", "s1", tuning)
	p, _, out, err := ch.AttachHLS("hls", starter.start)
	if err != nil {
		g.t.Fatalf("AttachHLS: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := p.Ready(ctx); err != nil {
		g.t.Fatalf("the pipeline never became ready: %v", err)
	}
	return ch, &session{pipeline: p, releaseOut: out, releaseCli: release}
}

func hlsEntryRefs(c *Channel, key string) (refs int, ok bool) {
	c.outMu.Lock()
	defer c.outMu.Unlock()
	entry, running := c.hls[key]
	if !running {
		return 0, false
	}
	return entry.refs, true
}

func pipelineDone(t *testing.T, p *hls.Pipeline, what string) {
	t.Helper()
	select {
	case <-p.Done():
	case <-time.After(15 * time.Second):
		t.Fatalf("the pipeline did not stop within 15 s: %s", what)
	}
}

func notDone(t *testing.T, p *hls.Pipeline, what string) {
	t.Helper()
	select {
	case <-p.Done():
		t.Fatalf("the pipeline stopped: %s", what)
	default:
	}
}

// Row ⟨E⟩: the last session's end lingers the pipeline and holds the channel.
func TestTheLastSessionsEndLingersThePipelineAndHoldsTheChannel(t *testing.T) {
	g := newLingerRig(t, nil)
	ch, s := g.firstSession(lingerTuning(), newReadyStarter(t))
	s.end()

	if refs, ok := hlsEntryRefs(ch, "hls"); !ok || refs != 0 {
		t.Fatalf("the pipeline's entry: registered %t with %d refs, want registered with none", ok, refs)
	}
	notDone(t, s.pipeline, "it should linger")
	if _, ok := ch.Lingering(); !ok {
		t.Fatal("the channel is not lingering")
	}
	pending := g.timers.pending()
	if len(pending) != 1 || pending[0].d != 300*time.Second {
		t.Fatalf("armed timers = %d, want exactly the linger's 300 s", len(pending))
	}
	if !inMap(g.m, ch) || ch.ring.Closed() || ch.Clients() != 0 {
		t.Fatalf("channel in map %t, ring closed %t, clients %d: want held open with no client", inMap(g.m, ch), ch.ring.Closed(), ch.Clients())
	}
}

// A new session, or a resume, ends the linger on the same pipeline.
func TestANewSessionEndsTheLingerOnTheSamePipeline(t *testing.T) {
	g := newLingerRig(t, nil)
	starter := newReadyStarter(t)
	ch, s := g.firstSession(lingerTuning(), starter)
	s.end()
	linger := g.timers.pending()[0]

	_, cliRelease, err := g.m.Attach("chan", testClient("s2"), nil)
	if err != nil {
		t.Fatal(err)
	}
	p, started, out2, err := ch.AttachHLS("hls", starter.start)
	if err != nil || started || p != s.pipeline {
		t.Fatalf("a second AttachHLS: pipeline reused %t, started %t, err %v; want the lingering pipeline and started false", p == s.pipeline, started, err)
	}
	if !linger.wasStopped() {
		t.Fatal("the timer's stop was not called")
	}
	if _, ok := ch.Lingering(); ok {
		t.Fatal("Lingering() is still true under a live session")
	}
	linger.fire() // the stale timer: it finds itself no longer the channel's linger
	notDone(t, s.pipeline, "a stale timer stopped a pipeline with a session")
	if !inMap(g.m, ch) {
		t.Fatal("a stale timer removed the channel")
	}

	// The same through a resume.
	out2()
	cliRelease()
	if _, ok := ch.Lingering(); !ok {
		t.Fatal("the channel did not linger a second time")
	}
	second := g.timers.pending()
	if len(second) != 1 {
		t.Fatalf("%d timers pending after the second linger, want 1", len(second))
	}
	release, ok := ch.AttachHLSExisting("hls", s.pipeline)
	if !ok {
		t.Fatal("AttachHLSExisting refused the lingering pipeline")
	}
	if !second[0].wasStopped() {
		t.Fatal("a resume left the linger's timer armed")
	}
	if _, ok := ch.Lingering(); ok {
		t.Fatal("a resume left the channel lingering")
	}
	release()
}

func TestTheLingersEndStopsThePipelineAndAnIdleChannel(t *testing.T) {
	g := newLingerRig(t, nil)
	ch, s := g.firstSession(lingerTuning(), newReadyStarter(t))
	s.end()
	g.timers.pending()[0].fire()

	pipelineDone(t, s.pipeline, "the linger ended")
	if _, ok := hlsEntryRefs(ch, "hls"); ok {
		t.Fatal("the pipeline's entry survived the linger's end")
	}
	if inMap(g.m, ch) {
		t.Fatal("the idle channel stayed in the map")
	}
	if sites := g.removals(); len(sites) != 1 || sites[0] != "stopIfStillIdle" {
		t.Fatalf("removals = %v, want exactly stopIfStillIdle", sites)
	}
	<-ch.Released()
	if n := g.rel.count("chan"); n != 1 {
		t.Fatalf("the release func ran %d times, want 1", n)
	}
}

// A TS client attached during the linger outlives it.
func TestATSClientOutlivesTheLinger(t *testing.T) {
	g := newLingerRig(t, nil)
	ch, s := g.firstSession(lingerTuning(), newReadyStarter(t))
	s.end()
	_, releaseTS, err := g.m.Attach("chan", testClient("ts"), nil)
	if err != nil {
		t.Fatal(err)
	}
	g.timers.pending()[0].fire()
	pipelineDone(t, s.pipeline, "the linger ended")
	if !inMap(g.m, ch) || ch.Clients() != 1 {
		t.Fatalf("channel in map %t with %d clients: the TS client must keep it", inMap(g.m, ch), ch.Clients())
	}
	releaseTS()
	if inMap(g.m, ch) {
		t.Fatal("the TS client's release did not stop the channel")
	}
}

func TestNoLingerWithTheWindowOrTheLingerOff(t *testing.T) {
	for name, mutate := range map[string]func(*Tuning){
		"the window off": func(tu *Tuning) { tu.RewindWindow = 0 },
		"the linger off": func(tu *Tuning) { tu.RewindLinger = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			g := newLingerRig(t, nil)
			tuning := lingerTuning()
			mutate(&tuning)
			ch, s := g.firstSession(tuning, newReadyStarter(t))
			s.end()
			pipelineDone(t, s.pipeline, "no linger is configured")
			if _, ok := hlsEntryRefs(ch, "hls"); ok {
				t.Fatal("the entry survived the last session")
			}
			if n := len(g.timers.pending()); n != 0 {
				t.Fatalf("%d timers armed, want none", n)
			}
		})
	}
}

// Decision 13: the countdown starts only when the client count and the hold are
// both zero.
func TestTheShutdownDelayCountdownStartsOnlyAfterTheLinger(t *testing.T) {
	g := newLingerRig(t, nil)
	tuning := lingerTuning()
	tuning.ShutdownDelay = 60 * time.Second
	ch, s := g.firstSession(tuning, newReadyStarter(t))
	s.end()
	pending := g.timers.pending()
	if len(pending) != 1 || pending[0].d != 300*time.Second {
		t.Fatalf("after the last session's releases %d timers are armed, want exactly the linger's 300 s", len(pending))
	}
	pending[0].fire()
	pending = g.timers.pending()
	if len(pending) != 1 || pending[0].d != 60*time.Second {
		t.Fatalf("after the linger %d timers are armed, want exactly the 60 s countdown", len(pending))
	}
	if !inMap(g.m, ch) {
		t.Fatal("the channel left the map before its countdown ran")
	}
	pending[0].fire()
	if inMap(g.m, ch) {
		t.Fatal("the countdown did not stop the channel")
	}
}

// Decision 13, stopIfStillIdle's own re-check: a countdown armed when an earlier
// linger ended finds a later linger holding the channel.
func TestAStaleCountdownDoesNotStopALingeringChannel(t *testing.T) {
	g := newLingerRig(t, nil)
	tuning := lingerTuning()
	tuning.ShutdownDelay = 60 * time.Second
	starter := newReadyStarter(t)
	ch, first := g.firstSession(tuning, starter)
	first.end()
	g.timers.pending()[0].fire() // the first linger ends; the 60 s countdown is armed
	countdown := g.timers.pending()
	if len(countdown) != 1 || countdown[0].d != 60*time.Second {
		t.Fatalf("%d timers pending after the first linger, want the one 60 s countdown", len(countdown))
	}

	second := g.session(ch, "s2", "hls", starter)
	if second.pipeline == first.pipeline {
		t.Fatal("the second session reused the stopped pipeline")
	}
	second.end()
	pending := g.timers.pending()
	if len(pending) != 2 {
		t.Fatalf("%d timers pending, want the stale countdown and the second linger", len(pending))
	}
	countdown[0].fire()
	if !inMap(g.m, ch) {
		t.Fatalf("the channel left the map when the stale countdown fired (removals %v)", g.removals())
	}
	if _, ok := ch.Lingering(); !ok {
		t.Fatal("the stale countdown ended the second linger")
	}
	notDone(t, second.pipeline, "the stale countdown stopped the lingering pipeline")
	if sites := g.removals(); len(sites) != 0 {
		t.Fatalf("removals = %v, want none", sites)
	}
	var linger *fakeTimer
	for _, tm := range g.timers.pending() {
		if tm.d == 300*time.Second {
			linger = tm
		}
	}
	linger.fire()
	for _, tm := range g.timers.pending() {
		tm.fire()
	}
	if inMap(g.m, ch) {
		t.Fatal("the second linger's end did not stop the channel")
	}
}

func TestAnUnreadyOrEndedPipelineNeverLingers(t *testing.T) {
	g := newLingerRig(t, nil)
	ch, release := g.attach("chan", "s1", lingerTuning())
	unready := &hlsStarter{}
	p, _, out, err := ch.AttachHLS("hls", unready.start)
	if err != nil {
		t.Fatal(err)
	}
	out()
	defer release()
	pipelineDone(t, p, "a pipeline that never became ready must not linger")
	if _, ok := hlsEntryRefs(ch, "hls"); ok {
		t.Fatal("an unready pipeline's entry was kept")
	}
	if n := len(g.timers.pending()); n != 0 {
		t.Fatalf("%d timers armed for a pipeline that never became ready", n)
	}

	// A ready pipeline that has already ended.
	starter := newReadyStarter(t)
	s := g.session(ch, "s2", "hls", starter)
	s.pipeline.Stop()
	s.end()
	if _, ok := hlsEntryRefs(ch, "hls"); ok {
		t.Fatal("an ended pipeline's entry was kept")
	}
	if n := len(g.timers.pending()); n != 0 {
		t.Fatalf("%d timers armed for an ended pipeline", n)
	}
}

func TestAFailedOrStoppedPipelineEndsItsLinger(t *testing.T) {
	t.Run("FailHLS", func(t *testing.T) {
		g := newLingerRig(t, nil)
		ch, s := g.firstSession(lingerTuning(), newReadyStarter(t))
		s.end()
		linger := g.timers.pending()[0]
		ch.FailHLS("hls", s.pipeline, hls.ErrFailed)
		if !linger.wasStopped() {
			t.Fatal("a failure left the linger's timer armed")
		}
		if _, ok := ch.Lingering(); ok {
			t.Fatal("a failed pipeline is still lingering")
		}
	})
	t.Run("stopOutputs", func(t *testing.T) {
		g := newLingerRig(t, nil)
		ch, s := g.firstSession(lingerTuning(), newReadyStarter(t))
		s.end()
		linger := g.timers.pending()[0]
		ch.stopOutputs()
		if !linger.wasStopped() {
			t.Fatal("the channel's stop left the linger's timer armed")
		}
		if _, ok := ch.Lingering(); ok {
			t.Fatal("a stopped channel is still lingering")
		}
	})
}

// The hold is not a client.
func TestTheLingerHoldIsNotAClient(t *testing.T) {
	g := newLingerRig(t, nil)
	ch, s := g.firstSession(lingerTuning(), newReadyStarter(t))
	s.end()
	if ch.Clients() != 0 || len(ch.ClientSnapshot()) != 0 {
		t.Fatalf("a lingering channel counts %d clients (%d in its snapshot), want none", ch.Clients(), len(ch.ClientSnapshot()))
	}
	since, ok := ch.Lingering()
	got, window, statusOK := ch.RewindStatus()
	if !ok || !statusOK || !got.Equal(since) || time.Since(since) > time.Minute {
		t.Fatalf("RewindStatus = %v, %t (linger since %v, %t)", got, statusOK, since, ok)
	}
	if window.Enabled {
		t.Fatalf("a pipeline built with no rewind store reports a window: %+v", window)
	}
	if p, ok := ch.HLSPipeline(); !ok || p != s.pipeline {
		t.Fatal("HLSPipeline is not the lingering pipeline")
	}
	bare := &Channel{}
	if _, _, ok := bare.RewindStatus(); ok {
		t.Fatal("a channel with no HLS pipeline reported a rewind status")
	}
	if _, ok := bare.HLSPipeline(); ok {
		t.Fatal("a channel with no HLS pipeline reported one")
	}
}

// A channel lingers at most one pipeline, and the hold reached through
// StopIfIdle is the one mechanism.
func TestOneLingerPerChannel(t *testing.T) {
	g := newLingerRig(t, nil)
	tuning := lingerTuning()
	tuning.ShutdownDelay = 60 * time.Second
	starter := newReadyStarter(t)
	ch, first := g.firstSession(tuning, starter)
	second := g.session(ch, "s2", "hls:p7", starter)

	first.end() // s1: pipeline one lingers; s2 still holds a client
	if _, ok := ch.Lingering(); !ok {
		t.Fatal("the first pipeline did not linger")
	}
	second.releaseOut() // a second pipeline reaching zero while one lingers stops at once
	pipelineDone(t, second.pipeline, "only one pipeline may linger")
	if _, ok := hlsEntryRefs(ch, "hls:p7"); ok {
		t.Fatal("the second pipeline's entry was kept")
	}
	second.releaseCli()
	if pending := g.timers.pending(); len(pending) != 1 || pending[0].d != 300*time.Second {
		t.Fatalf("%d timers pending, want only the first linger's", len(pending))
	}

	// The hold, reached through StopIfIdle: a third pipeline fails, and the
	// manager is asked its idle question with the first still lingering.
	third, _, _, err := ch.AttachHLS("hls:p8", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	ch.FailHLS("hls:p8", third, hls.ErrFailed)
	g.m.EndHLSSessions(ch, nil)
	if !inMap(g.m, ch) {
		t.Fatal("the failure's idle question stopped a lingering channel")
	}
	if _, ok := ch.Lingering(); !ok {
		t.Fatal("the first pipeline stopped lingering")
	}
	if pending := g.timers.pending(); len(pending) != 1 || pending[0].d != 300*time.Second {
		t.Fatalf("%d timers pending, want only the linger's: a countdown was armed under the hold", len(pending))
	}
}

func TestALingerTimerWithoutAManagerUsesTheRealClock(t *testing.T) {
	c := &Channel{}
	fired := make(chan struct{})
	stop := c.schedule(time.Millisecond, func() { close(fired) })
	select {
	case <-fired:
	case <-time.After(10 * time.Second):
		t.Fatal("a channel built without an AfterFunc never fired its timer")
	}
	if stop() {
		t.Fatal("stop reported a fired timer as pending")
	}
}
