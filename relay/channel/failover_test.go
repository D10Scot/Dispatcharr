package channel

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// fakeResolver hands back a scripted list of answers, then ErrNoAlternate,
// recording every request and when it was made. A nil answers list is a
// resolver with nothing to offer.
type fakeResolver struct {
	mu       sync.Mutex
	answers  []Resolved
	err      error
	reqs     []NextRequest
	calledAt []time.Time
	// block, when set, holds every call until it is closed: for a test
	// that needs the channel to STAY in its pre-switch state.
	block chan struct{}
}

func (r *fakeResolver) Next(ctx context.Context, req NextRequest) (Resolved, error) {
	r.mu.Lock()
	r.reqs = append(r.reqs, req)
	r.calledAt = append(r.calledAt, time.Now())
	block := r.block
	r.mu.Unlock()
	if block != nil {
		select {
		case <-block:
		case <-ctx.Done():
			return Resolved{}, ctx.Err()
		}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.err != nil {
		return Resolved{}, r.err
	}
	if len(r.answers) == 0 {
		return Resolved{}, ErrNoAlternate
	}
	next := r.answers[0]
	r.answers = r.answers[1:]
	return next, nil
}

func (r *fakeResolver) requests() []NextRequest {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]NextRequest(nil), r.reqs...)
}

func (r *fakeResolver) firstCallAt() time.Time {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.calledAt) == 0 {
		return time.Time{}
	}
	return r.calledAt[0]
}

// callTimes is when each Next call arrived, in order: a copy taken under the
// lock, for a test that bounds the gaps between asks (#302). From #348.
func (r *fakeResolver) callTimes() []time.Time {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]time.Time(nil), r.calledAt...)
}

// eventLog is an EventSink that keeps everything, with the wall clock each
// event arrived at.
type eventLog struct {
	mu     sync.Mutex
	events []Event
	at     []time.Time
}

func (l *eventLog) Emit(e Event) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.events = append(l.events, e)
	l.at = append(l.at, time.Now())
}

func (l *eventLog) of(typ string) []Event {
	l.mu.Lock()
	defer l.mu.Unlock()
	var out []Event
	for _, e := range l.events {
		if e.Type == typ {
			out = append(out, e)
		}
	}
	return out
}

func (l *eventLog) all() []Event {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]Event(nil), l.events...)
}

// countingRuns wraps a source and counts its Runs -- the way a test tells
// that the source a resolver handed over is the one now producing bytes.
type countingRuns struct {
	inner Source
	runs  *int32Counter
}

func (s countingRuns) Run(ctx context.Context, sink io.Writer) error {
	s.runs.inc()
	return s.inner.Run(ctx, sink)
}

func (s countingRuns) attach(c *Channel) {
	if a, ok := s.inner.(attachable); ok {
		a.attach(c)
	}
}

// failingSource fails at connect time, every time, with a 404 -- Python's
// HTTPStreamReader getting a 404 and closing the pipe at once.
type failingSource struct{ runs *int32Counter }

func (s failingSource) Run(context.Context, io.Writer) error {
	s.runs.inc()
	return &ErrUpstreamStatus{Status: 404}
}

// flowingSource writes one synthetic packet every tick until cancelled.
type flowingSource struct {
	runs *int32Counter
	tick time.Duration
}

func (s flowingSource) Run(ctx context.Context, sink io.Writer) error {
	if s.runs != nil {
		s.runs.inc()
	}
	payload := relaytest.SyntheticTS(64, 0x200)
	tick := s.tick
	if tick <= 0 {
		tick = 5 * time.Millisecond
	}
	for i := 0; ; i = (i + 1) % 64 {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(tick):
		}
		if _, err := sink.Write(payload[i*buffer.TSPacketSize : (i+1)*buffer.TSPacketSize]); err != nil {
			return err
		}
	}
}

// deadAirSource writes `packets` whole packets and then produces nothing
// until cancelled -- a provider that stopped, not one that hung up. It
// records when it wrote its last byte, which is the moment the dead-air
// clock starts from.
type deadAirSource struct {
	packets   int
	lastWrite *timeCell
}

type timeCell struct {
	mu sync.Mutex
	t  time.Time
}

func (c *timeCell) set(t time.Time) { c.mu.Lock(); c.t = t; c.mu.Unlock() }
func (c *timeCell) get() time.Time  { c.mu.Lock(); defer c.mu.Unlock(); return c.t }

func (s deadAirSource) Run(ctx context.Context, sink io.Writer) error {
	payload := relaytest.SyntheticTS(s.packets, 0x100)
	// Stamped BEFORE the write, because dataClock.Write records the channel's
	// own lastData at the START of the write (health.go's dataClock) and the
	// monitor measures from THAT -- so a stamp taken afterwards is later than
	// the monitor's clock by however long the ring write took, and the
	// assertion below is a `>=` on the gap. Directional, and MEASURED NOT TO
	// BE SUFFICIENT on its own: under load this shape still drew 2 sub-400 ms
	// gaps in 60 runs against the unfixed shape's 1 in 60. The bound below is
	// what actually closes #309; this is the perturbation it was cheap to
	// remove first.
	s.lastWrite.set(time.Now())
	if _, err := sink.Write(payload); err != nil {
		return err
	}
	<-ctx.Done()
	return ctx.Err()
}

// attachWith is attachTranscode with a resolver: the shape every failover
// test needs.
func attachWith(t *testing.T, m *Manager, id string, source Source, tuning Tuning, resolver Resolver) (*Channel, func()) {
	t.Helper()
	ch, release, err := m.Attach(id, testClient("a"), func() (Started, error) {
		return Started{Source: source, Tuning: tuning, Info: SourceInfo{URL: "http://provider.invalid/primary.ts", StreamID: 1, M3UProfileID: 1, ChannelName: "Test Channel"}, Resolver: resolver}, nil
	})
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	return ch, release
}

// Global Constraint 8's ratchet for the bare literals of the retry loop and
// the health monitor: each names its Python line, and each is asserted
// against the number written there.
func TestTheFailoverLiteralsMatchPython(t *testing.T) {
	if retryBackoff(1) != 250*time.Millisecond || retryBackoff(2) != 500*time.Millisecond || retryBackoff(12) != 3*time.Second || retryBackoff(13) != 3*time.Second {
		t.Errorf("retryBackoff is not min(.25 * failures, 3) (input/manager.py:557): %s %s %s", retryBackoff(1), retryBackoff(2), retryBackoff(13))
	}
	if maxUnhealthyChecks != 3 {
		t.Errorf("maxUnhealthyChecks = %d, want 3 (input/manager.py:1556)", maxUnhealthyChecks)
	}
	if healthActionCooldown != 30*time.Second {
		t.Errorf("healthActionCooldown = %s, want 30s (input/manager.py:1557)", healthActionCooldown)
	}
	if stableReconnectAfter != 30*time.Second {
		t.Errorf("stableReconnectAfter = %s, want 30s (input/manager.py:1580's bare literal)", stableReconnectAfter)
	}
	if healthActionFor(30*time.Second) != actionReconnect || healthActionFor(29*time.Second) != actionSwitch {
		t.Error("healthActionFor: a stream stable for >= 30s reconnects in place, a younger one switches (input/manager.py:1576-1590)")
	}
}

// PARITY-MATRIX ROW 3's window half (input/manager.py:183-193): failures at
// t=0, 1700 and 3400 trip a 1800-second window even though the span is 3400,
// because each gap is under the window; a gap over it resets the count.
// Driven with an injected clock, so it costs nothing and cannot flake.
func TestTheRetryWindowResetsTheCounterAfterAnIdleGap(t *testing.T) {
	var now time.Time
	clock := func() time.Time { return now }
	base := time.Date(2026, 9, 14, 12, 0, 0, 0, time.UTC)
	counter := failureCounter{window: 1800 * time.Second, now: clock}

	now = base
	if got := counter.record(); got != 1 {
		t.Fatalf("first failure counted as %d", got)
	}
	now = base.Add(1700 * time.Second)
	if got := counter.record(); got != 2 {
		t.Fatalf("a failure 1700s later counted as %d, want 2 (inside the window)", got)
	}
	now = base.Add(3400 * time.Second)
	if got := counter.record(); got != 3 {
		t.Fatalf("a failure 1700s after that counted as %d, want 3: the span is 3400s but each gap is under 1800s", got)
	}
	now = base.Add(3400*time.Second + 1801*time.Second)
	if got := counter.record(); got != 1 {
		t.Fatalf("a failure 1801s after the last counted as %d, want 1: the gap exceeded the window and the counter resets", got)
	}
	counter.clear()
	if counter.count != 0 || !counter.last.IsZero() {
		t.Fatal("clear did not reset the counter and the last-failure time")
	}
}

// PARITY-MATRIX ROW 3: MAX_RETRIES (3) consecutive connection failures
// exhaust the source and the channel asks for the next one
// (input/manager.py:50-52, :182-192, :533-538). Asserted at the source
// (three Runs), at the resolver (one request excluding stream 1 and naming
// it as current), at the events (two channel_reconnect, one channel_error
// with connection_failed and attempts 3, one stream_switch), and at the
// outcome (the alternate runs, the channel is active).
func TestThreeConnectFailuresExhaustTheSourceAndFailOver(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	primary := &int32Counter{}
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: flowingSource{runs: alternate},
		Info:   SourceInfo{URL: "http://provider.invalid/live/u/hunter2/alt.ts", StreamID: 2, M3UProfileID: 1, ChannelName: "Not The Channel"},
	}}}

	ch, release := attachWith(t, m, "row3", failingSource{runs: primary}, testTuning(), resolver)
	defer release()

	waitFor(t, "the alternate to run", 10*time.Second, func() bool { return alternate.get() == 1 })
	waitFor(t, "the channel to go active on the alternate", 10*time.Second, func() bool { return ch.State() == StateActive })

	if got := primary.get(); got != 3 {
		t.Fatalf("the primary was attempted %d times, want MAX_RETRIES = 3", got)
	}
	reqs := resolver.requests()
	if len(reqs) != 1 {
		t.Fatalf("the resolver was asked %d times, want 1", len(reqs))
	}
	if len(reqs[0].Exclude) != 1 || reqs[0].Exclude[0] != 1 || reqs[0].CurrentStreamID != 1 || reqs[0].CurrentURL != "http://provider.invalid/primary.ts" {
		t.Fatalf("the request was %+v, want exclude [1], current stream 1 and the primary URL", reqs[0])
	}
	if got := ch.Source().StreamID; got != 2 {
		t.Fatalf("Source().StreamID = %d after the switch, want 2", got)
	}

	if reconnects := events.of("channel_reconnect"); len(reconnects) != 2 {
		t.Fatalf("channel_reconnect raised %d times, want 2 (attempts 2 and 3): %+v", len(reconnects), reconnects)
	} else if reconnects[1].Details["attempt"] != 3 || reconnects[1].Details["max_attempts"] != 3 {
		t.Fatalf("the last channel_reconnect carried %+v, want attempt 3 of 3", reconnects[1].Details)
	}
	failed := events.of("channel_error")
	if len(failed) != 1 || failed[0].Details["error_type"] != "connection_failed" || failed[0].Details["attempts"] != 3 {
		t.Fatalf("channel_error = %+v, want one with error_type connection_failed and attempts 3", failed)
	}
	if url, _ := failed[0].Details["url"].(string); strings.Contains(url, "hunter2") || strings.Contains(url, "/live/") {
		t.Fatalf("channel_error carries the provider credential: %q", url)
	}
	switched := events.of("stream_switch")
	if len(switched) != 1 || switched[0].StreamID == nil || *switched[0].StreamID != 2 || switched[0].ChannelID != "row3" {
		t.Fatalf("stream_switch = %+v, want one naming stream 2 on channel row3", switched)
	}
	// channel_name is the channel's, fixed at construction (input/manager.py:
	// 41-44), not the alternate's -- whose SourceInfo here carries a name of
	// its own precisely so this can tell them apart.
	if switched[0].ChannelName != "Test Channel" {
		t.Fatalf("stream_switch channel_name = %q, want the channel's own \"Test Channel\"", switched[0].ChannelName)
	}
	if url, _ := switched[0].Details["new_url"].(string); strings.Contains(url, "hunter2") || !strings.HasPrefix(url, "http://provider.invalid/") {
		t.Fatalf("stream_switch new_url = %q: must be the redacted URL, host kept and path gone", url)
	}
}

// PARITY-MATRIX ROW 2: no data for longer than the inactivity threshold,
// observed on three consecutive health checks, switches streams
// (input/manager.py:1547-1551, :1553-1609, :414-438) -- the unstable branch,
// the same one the Python pin drives, because the stable branch needs 30
// seconds of wall clock (row 2's Notes). Thresholds compressed off the
// tuning: 300 ms of silence, checked every 50 ms.
//
// THE THREE CHECKS ARE THE ASSERTION, not the switch alone. The source
// records when it wrote its last byte; the resolver records when it was
// asked; the gap must be at least the threshold plus two more intervals. A
// port that acted on the first inactive check would ask at ~300-350 ms and
// redden. And no connection failure is counted: Python leaves the retry loop
// on the flag before its failure accounting (:505-507).
func TestDeadAirOnAYoungConnectionSwitchesStreams(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	lastWrite := &timeCell{}
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: flowingSource{runs: alternate},
		Info:   SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2, M3UProfileID: 1},
	}}}
	tuning := testTuning()
	tuning.ConnectionTimeout = 300 * time.Millisecond
	tuning.HealthCheckInterval = 50 * time.Millisecond

	ch, release := attachWith(t, m, "row2", deadAirSource{packets: 8, lastWrite: lastWrite}, tuning, resolver)
	defer release()

	sawUnhealthy := false
	waitFor(t, "the switch to the alternate", 10*time.Second, func() bool {
		if !ch.Healthy() {
			sawUnhealthy = true
		}
		return alternate.get() == 1
	})
	if !sawUnhealthy {
		t.Fatal("the channel was never observed unhealthy before it switched")
	}
	asked, wrote := resolver.firstCallAt(), lastWrite.get()
	// THE CLAIM IS THREE CHECKS AND IT IS NOT WEAKENED; what moves is the
	// clock tolerance, and #309 is why.
	//
	// The monitor's first unhealthy check is the first TICK whose inactivity
	// exceeds CONNECTION_TIMEOUT, and the tick grid is phased on the monitor's
	// start rather than on the last byte. Instrumented on this tree, the six
	// ticks to 300 ms land at 301.093 ms -- 1.09 ms past, that overshoot being
	// the ticker's accumulated drift -- and the third unhealthy check two ticks
	// later at ~400.6 ms. So the margin above a floor of exactly
	// CONNECTION_TIMEOUT + 2 intervals is the DRIFT ALONE, about a
	// millisecond, not the 50 ms interval it looks like. Any sub-millisecond
	// perturbation breaches it: measured at 399.966, 399.960 and 399.995 ms on
	// a loaded host, with and without the stamp fix above alike.
	//
	// A tenth of an interval -- 5 ms here -- is two orders of magnitude below
	// the 50 ms that separates this from acting one check early, so the test
	// still reddens on a monitor that acts on the second check (~350.6 ms
	// measured) or the first (~301 ms), which is what it exists to catch.
	// Measured with this bound: 30 loaded runs, zero failures, minimum gap
	// 399.989 ms -- 5 ms of real margin where the old bound had 40 microseconds.
	floor := tuning.ConnectionTimeout + 2*tuning.HealthCheckInterval - tuning.HealthCheckInterval/10
	if gap := asked.Sub(wrote); gap < floor {
		t.Fatalf("the resolver was asked %s after the last byte, under CONNECTION_TIMEOUT + two more checks less a tenth of an interval (%s): the monitor did not wait for three consecutive checks", gap, floor)
	} else if gap > 3*time.Second {
		t.Fatalf("the resolver was asked %s after the last byte: the dead air was not acted on", gap)
	}
	if len(events.of("stream_switch")) != 1 {
		t.Fatalf("stream_switch raised %d times, want 1", len(events.of("stream_switch")))
	}
	if errs := events.of("channel_error"); len(errs) != 0 {
		t.Fatalf("channel_error raised %+v: a health-requested switch records no connection failure", errs)
	}
	waitFor(t, "health to be restored on the alternate", 5*time.Second, ch.Healthy)
}

// The health flag comes back on its own when data resumes before the third
// check (input/manager.py:1594-1601), and nothing is switched. A source that
// pauses for one threshold and a half, against a threshold of 300 ms
// checked every 200 ms: the check at 400 ms finds it inactive, the one at
// 600 ms finds data 100 ms old.
func TestHealthIsRestoredWhenDataResumesBeforeTheThirdCheck(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	resolver := &fakeResolver{}
	tuning := testTuning()
	tuning.ConnectionTimeout = 300 * time.Millisecond
	tuning.HealthCheckInterval = 200 * time.Millisecond

	source := pausingSource{pause: 450 * time.Millisecond}
	ch, release := attachWith(t, m, "restore", source, tuning, resolver)
	defer release()

	waitFor(t, "the channel to be marked unhealthy during the pause", 3*time.Second, func() bool { return !ch.Healthy() })
	waitFor(t, "health to be restored once data resumes", 3*time.Second, ch.Healthy)
	if got := len(resolver.requests()); got != 0 {
		t.Fatalf("the resolver was asked %d times: a pause shorter than three checks must not switch", got)
	}
	m.Stop("restore")
}

// pausingSource writes, stops for `pause`, then writes forever.
type pausingSource struct{ pause time.Duration }

func (s pausingSource) Run(ctx context.Context, sink io.Writer) error {
	payload := relaytest.SyntheticTS(8, 0x100)
	if _, err := sink.Write(payload); err != nil {
		return err
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(s.pause):
	}
	return flowingSource{}.Run(ctx, sink)
}

// Out of candidates, the channel ends in error carrying Python's own message
// (input/manager.py:679-682): "All N stream options failed" when any stream
// id was tried -- the initial one counts -- and the last attempt's error
// still reachable through it.
func TestAnExhaustedChannelEndsInErrorNamingTheCount(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	ch, release := attachWith(t, m, "exhausted", failingSource{runs: &int32Counter{}}, testTuning(), &fakeResolver{})
	defer release()
	<-ch.Done()
	if ch.State() != StateError {
		t.Fatalf("state = %q, want error", ch.State())
	}
	var exhausted *ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) || exhausted.Message() != "All 1 stream options failed" {
		t.Fatalf("Err() = %v, want \"All 1 stream options failed\"", ch.Err())
	}
	var status *ErrUpstreamStatus
	if !errors.As(ch.Err(), &status) || status.Status != 404 {
		t.Fatalf("the last attempt's error is not reachable through the exhaustion error: %v", ch.Err())
	}
}

// A resolver that names the URL already playing is refused, as update_url
// refuses it (input/manager.py:1464-1466), and the failover reports failure.
func TestAFailoverThatNamesTheURLAlreadyPlayingIsRefused(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	resolver := &fakeResolver{answers: []Resolved{{Source: flowingSource{}, Info: SourceInfo{URL: "http://provider.invalid/primary.ts", StreamID: 7}}}}
	ch, release := attachWith(t, m, "same-url", failingSource{runs: &int32Counter{}}, testTuning(), resolver)
	defer release()
	<-ch.Done()
	if ch.State() != StateError || ch.Source().StreamID != 1 {
		t.Fatalf("state = %q, stream %d: the switch to the URL already playing went through", ch.State(), ch.Source().StreamID)
	}
	if len(resolver.requests()) != 1 {
		t.Fatalf("the resolver was asked %d times, want 1", len(resolver.requests()))
	}
}

// PARITY-MATRIX ROW 7 ACROSS A SWITCH: the chunk index is monotonic for the
// channel's life and a switch never rewinds it or empties the ring
// (CLAUDE.md § Architecture) -- what the packetiser holds is dropped
// (ResetPosition, input/buffer.py's reset_buffer_position), so the old
// upstream's partial trailing packet is never glued to the new one's first
// bytes. The primary writes eight whole packets and three stray bytes before
// failing; the alternate's packets must arrive aligned, after the primary's,
// with the head still climbing.
func TestTheChunkIndexIsMonotonicAcrossAFailover(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: flowingSource{runs: alternate},
		Info:   SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2},
	}}}
	tuning := testTuning()
	tuning.MaxRetries = 1 // one failure exhausts the primary, so the ring holds one copy of its packets
	ch, release := attachWith(t, m, "row7", raggedSource{}, tuning, resolver)
	defer release()

	waitFor(t, "the primary's chunks", 5*time.Second, func() bool { return ch.Ring().Head() >= 2 })
	headBefore := ch.Ring().Head()
	waitFor(t, "the alternate to run", 10*time.Second, func() bool { return alternate.get() == 1 })
	waitFor(t, "the alternate's chunks", 10*time.Second, func() bool { return ch.Ring().Head() >= headBefore+2 })

	chunks, _, skipped := ch.Ring().Read(0)
	if skipped != 0 || len(chunks) < 4 {
		t.Fatalf("the ring holds %d chunks from index 0 with %d skipped: the switch emptied it", len(chunks), skipped)
	}
	for i, chunk := range chunks {
		if problem := relaytest.AlignmentProblem(chunk); problem != "" {
			t.Fatalf("chunk %d is not whole packets: %s -- the stray bytes were glued to the new upstream's first packet", i, problem)
		}
	}
	// The primary's packets first (pid 0x100), the alternate's after (pid
	// 0x200), and never the other way round.
	seenAlternate := false
	for i, chunk := range chunks {
		pid := int(chunk[1]&0x1f)<<8 | int(chunk[2])
		switch {
		case pid == 0x200:
			seenAlternate = true
		case pid == 0x100 && seenAlternate:
			t.Fatalf("chunk %d carries the primary's packets after the alternate's: the index rewound", i)
		}
	}
	if !seenAlternate {
		t.Fatal("no chunk from the alternate reached the ring")
	}
	m.Stop("row7")
}

// raggedSource writes eight whole packets and three stray bytes, then fails.
type raggedSource struct{}

func (raggedSource) Run(_ context.Context, sink io.Writer) error {
	payload := relaytest.SyntheticTS(8, 0x100)
	if _, err := sink.Write(append(payload, 0x47, 0x01, 0x02)); err != nil {
		return err
	}
	return &ErrUpstreamStatus{Status: 502}
}

// The degraded bookkeeping of _try_next_stream (input/manager.py:2191-2202):
// a switch resolved from the cache sets the flag and raises nothing; the next
// switch the control plane answers raises channel_error with
// reason degraded_failover, once.
func TestAFailoverFromTheCacheRaisesDegradedFailoverOnRecovery(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)
	second := &int32Counter{}
	third := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{
		{Source: failingSource{runs: second}, Info: SourceInfo{URL: "http://provider.invalid/2.ts", StreamID: 2}, Degraded: true},
		{Source: flowingSource{runs: third}, Info: SourceInfo{URL: "http://provider.invalid/3.ts", StreamID: 3}},
	}}
	tuning := testTuning()
	tuning.MaxRetries = 1
	ch, release := attachWith(t, m, "degraded", failingSource{runs: &int32Counter{}}, tuning, resolver)
	defer release()

	waitFor(t, "the third source to run", 10*time.Second, func() bool { return third.get() == 1 })
	if got := ch.Source().StreamID; got != 3 {
		t.Fatalf("Source().StreamID = %d, want 3", got)
	}
	var degraded []Event
	for _, e := range events.of("channel_error") {
		if e.Details["reason"] == "degraded_failover" {
			degraded = append(degraded, e)
		}
	}
	if len(degraded) != 1 {
		t.Fatalf("degraded_failover raised %d times, want exactly 1, on the recovery: %+v", len(degraded), events.all())
	}
	// Ordered: the degraded_failover event follows the second stream_switch,
	// never the first.
	var switches, degradedAt int
	for i, e := range events.all() {
		if e.Type == "stream_switch" {
			switches++
		}
		if e.Type == "channel_error" && e.Details["reason"] == "degraded_failover" {
			degradedAt = i
			if switches != 2 {
				t.Fatalf("degraded_failover was raised after %d switches, want 2", switches)
			}
		}
	}
	_ = degradedAt
	m.Stop("degraded")
}

// The other half of row 6: MAX_STREAM_SWITCHES DOES bound a main-loop
// switch. With the bound at zero, `stream_switch_attempts <= 0` admits the
// first pass, the connect-failure switch happens, and the loop then exits
// without ever running the new source (input/manager.py:388-402) -- the
// channel errors although its alternate would have flowed. Together with
// TestABufferingFailoverIgnoresMaxStreamSwitches this pins the asymmetry.
func TestMaxStreamSwitchesBoundsAMainLoopSwitch(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{Source: flowingSource{runs: alternate}, Info: SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2}}}}
	tuning := testTuning()
	tuning.MaxRetries = 1
	tuning.MaxStreamSwitches = 0
	ch, release := attachWith(t, m, "bound", failingSource{runs: &int32Counter{}}, tuning, resolver)
	defer release()
	<-ch.Done()
	if ch.State() != StateError {
		t.Fatalf("state = %q, want error: the bound of zero ends the loop after its first switch", ch.State())
	}
	if len(resolver.requests()) != 1 {
		t.Fatalf("the resolver was asked %d times, want 1: the switch itself happens", len(resolver.requests()))
	}
	if alternate.get() != 0 {
		t.Fatal("the alternate ran: the main loop ignored MAX_STREAM_SWITCHES")
	}
}

// The provider slot is released exactly once, when the source goroutine
// returns, with the CURRENT source's ids -- after a failover, the
// alternate's -- and on a stop as much as on an exhaustion.
func TestTheSlotIsReleasedOnceWhenTheSourceGoroutineReturns(t *testing.T) {
	var mu sync.Mutex
	var released []SourceInfo
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Release: func(_ string, info SourceInfo) {
		mu.Lock()
		defer mu.Unlock()
		released = append(released, info)
	}})
	t.Cleanup(m.StopAll)
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{Source: flowingSource{runs: alternate}, Info: SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2, M3UProfileID: 5}}}}
	tuning := testTuning()
	tuning.MaxRetries = 1
	ch, release := attachWith(t, m, "release", failingSource{runs: &int32Counter{}}, tuning, resolver)
	waitFor(t, "the alternate to run", 10*time.Second, func() bool { return alternate.get() == 1 })
	mu.Lock()
	n := len(released)
	mu.Unlock()
	if n != 0 {
		t.Fatalf("released %d times while the channel was still running", n)
	}
	release()
	<-ch.Done()
	waitFor(t, "the release", 5*time.Second, func() bool { mu.Lock(); defer mu.Unlock(); return len(released) == 1 })
	mu.Lock()
	defer mu.Unlock()
	if released[0].StreamID != 2 || released[0].M3UProfileID != 5 {
		t.Fatalf("released %+v, want the alternate's stream 2 on profile 5", released[0])
	}
}

// fakeClock is an injectable time.Now for the manager, so a "stable for 31
// seconds" stream costs no wall clock.
type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

// stallingSource writes two chunks' worth, reports it, then writes again on
// every resume signal and reports each, blocking until cancelled: a provider
// that goes quiet after a stable run, twice over. Every Run counts.
type stallingSource struct {
	runs   *int32Counter
	resume chan struct{}
	wrote  chan struct{}
}

func (s stallingSource) Run(ctx context.Context, sink io.Writer) error {
	s.runs.inc()
	payload := relaytest.SyntheticTS(8, 0x100)
	if _, err := sink.Write(payload); err != nil {
		return err
	}
	s.wrote <- struct{}{}
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-s.resume:
			if _, err := sink.Write(payload[:4*buffer.TSPacketSize]); err != nil {
				return err
			}
			s.wrote <- struct{}{}
		}
	}
}

// THE RECONNECT FLAG IS CLEARED ON EVERY PASS OF THE INNER LOOP
// (input/manager.py:521-531), and a shape that cleared it only at the outer
// loop's top left it set after the first reconnect: the monitor's own guard
// (`if not self.needs_reconnect`, :1581) then never cancelled again, and a
// SECOND stall on a stable stream was logged and never acted on -- the 2c-5
// plan's reviewer reproduced that against an earlier loop. Two stable stalls
// with an injected clock (31 s of stability, then 35 s of silence, twice):
// each must cancel the attempt and start the next, so the source runs three
// times, and channel_reconnect is raised for attempts 2 and 3 with no
// `reason: health_monitor` shape, which is the outer branch Python cannot
// reach (Ruling R4).
func TestASecondStableStallIsActedOnAfterAHealthReconnect(t *testing.T) {
	clock := &fakeClock{t: time.Date(2026, 9, 14, 12, 0, 0, 0, time.UTC)}
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Now: clock.now, Events: events})
	t.Cleanup(m.StopAll)

	runs := &int32Counter{}
	src := stallingSource{runs: runs, resume: make(chan struct{}), wrote: make(chan struct{})}
	tuning := testTuning()
	tuning.HealthCheckInterval = 20 * time.Millisecond
	ch, release := attachWith(t, m, "stall-twice", src, tuning, &fakeResolver{})
	defer release()

	for stall := 1; stall <= 2; stall++ {
		<-src.wrote                     // this attempt's first bytes: the ring holds a chunk
		clock.advance(31 * time.Second) // stable past stableReconnectAfter
		src.resume <- struct{}{}
		<-src.wrote                     // lastData is now 31 s after connStart
		clock.advance(35 * time.Second) // silence past CONNECTION_TIMEOUT, past the cooldown
		want := stall + 1
		deadline := time.Now().Add(5 * time.Second)
		for runs.get() != want && time.Now().Before(deadline) {
			time.Sleep(10 * time.Millisecond)
		}
		if runs.get() != want {
			t.Fatalf("stall %d: the source ran %d times, want %d -- needsReconnect stayed set after the first reconnect and the monitor never cancelled again", stall, runs.get(), want)
		}
	}
	reconnects := events.of("channel_reconnect")
	if len(reconnects) != 2 || reconnects[0].Details["attempt"] != 2 || reconnects[1].Details["attempt"] != 3 {
		t.Fatalf("channel_reconnect = %+v, want attempts 2 and 3", reconnects)
	}
	for _, e := range reconnects {
		if e.Details["reason"] == "health_monitor" {
			t.Fatalf("channel_reconnect carried reason health_monitor: the outer-loop branch is unreachable in Python and is not ported")
		}
	}
	if ch.State() != StateActive {
		t.Fatalf("state = %q after two reconnects, want active", ch.State())
	}
	m.Stop("stall-twice")
}
