package session

import (
	"context"
	"slices"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/hls"
)

// fakeClock is the table's clock, advanced by the test.
type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func newFakeClock() *fakeClock { return &fakeClock{t: time.Unix(1_700_000_000, 0)} }

func (c *fakeClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) Advance(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

// journal is one ordered record of what a departure did, shared by the fake
// owner (its events) and the releases (the two funcs), so ORDER is assertable.
type journal struct {
	mu      sync.Mutex
	entries []string
}

func (j *journal) add(s string) {
	j.mu.Lock()
	j.entries = append(j.entries, s)
	j.mu.Unlock()
}

func (j *journal) all() []string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return slices.Clone(j.entries)
}

// fakeOwner is a channel as the table sees it. Identity is the pointer.
type fakeOwner struct {
	name string
	j    *journal
}

func (o *fakeOwner) EmitClientConnect(cl *channel.Client) { o.j.add("connect " + cl.ID) }
func (o *fakeOwner) EmitClientDisconnect(cl *channel.Client, _ time.Time) {
	o.j.add("disconnect " + cl.ID)
}

type rig struct {
	t     *testing.T
	clock *fakeClock
	table *Table
	j     *journal
	seq   int
}

func newRig(t *testing.T) *rig {
	t.Helper()
	clock := newFakeClock()
	return &rig{t: t, clock: clock, j: &journal{}, table: NewTable(Config{Now: clock.Now})}
}

func (r *rig) owner(name string) *fakeOwner { return &fakeOwner{name: name, j: r.j} }

// releases records the two funcs under the client's id.
func (r *rig) releases(clientID string) Releases {
	return Releases{
		Output: func() { r.j.add("output " + clientID) },
		Client: func() { r.j.add("client " + clientID) },
	}
}

// add registers an ARRIVED session (sid is unique per call).
func (r *rig) add(o Owner, clientID string, td time.Duration) *Session {
	r.t.Helper()
	r.seq++
	s := &Session{
		ID: "sid-" + clientID + "-" + string(rune('0'+r.seq)), Owner: o, Key: "hls",
		Pipeline: &hls.Pipeline{}, TD: td,
	}
	r.table.Add(s, &channel.Client{ID: clientID}, r.releases(clientID))
	return s
}

// active registers a session and activates it.
func (r *rig) active(o Owner, clientID string) *Session {
	r.t.Helper()
	s := r.add(o, clientID, 2*time.Second)
	if !r.table.Activate(s.ID) {
		r.t.Fatalf("Activate(%s) refused", clientID)
	}
	return s
}

// departIdle ages a session past its idle timeout, sweeps and RUNS the
// departure, so the session is DEPARTED and settled.
func (r *rig) departIdle(s *Session) {
	r.t.Helper()
	r.clock.Advance(IdleTimeout(s.TD))
	departures := r.table.Sweep()
	if len(departures) != 1 {
		r.t.Fatalf("the sweep departed %d sessions, want 1", len(departures))
	}
	departures[0].Run()
}

func TestAnEntryIsInFlightUntilActivated(t *testing.T) {
	r := newRig(t)
	s := r.add(r.owner("c1"), "a", 2*time.Second)

	r.clock.Advance(time.Hour)
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatalf("the sweep departed an ARRIVED session (an entry is in flight): %d departures", len(got))
	}
	if !r.table.Activate(s.ID) {
		t.Fatal("Activate refused an ARRIVED session")
	}
	if r.table.Activate(s.ID) {
		t.Fatal("a second Activate succeeded: only ARRIVED activates")
	}
	// ACTIVE now, with lastEnd = the activation. Idle time counts from there,
	// not from the hour-old arrival.
	r.clock.Advance(11*time.Second + 999*time.Millisecond)
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatalf("a session activated 11.999 s ago departed: idle time must count from Activate")
	}
	if r.table.Activate("no-such-sid") {
		t.Fatal("Activate succeeded for an unknown session")
	}
}

func TestAnIdleSessionDepartsAfterTheIdleTimeoutAndNotBefore(t *testing.T) {
	r := newRig(t)
	s := r.active(r.owner("c1"), "a")

	r.clock.Advance(11*time.Second + 999*time.Millisecond)
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatalf("departed at 11.999 s idle: %d departures", len(got))
	}
	r.clock.Advance(time.Millisecond)
	departures := r.table.Sweep()
	if len(departures) != 1 {
		t.Fatalf("at 12 s idle the sweep departed %d sessions, want 1", len(departures))
	}
	departures[0].Run()
	want := []string{"disconnect a", "output a", "client a"}
	if got := r.j.all(); !slices.Equal(got, want) {
		t.Fatalf("the departure did %v, want %v (client_disconnect once, then Output, then Client)", got, want)
	}
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatal("a departed session departed a second time")
	}
	if l := r.table.Begin(s.ID); l.Outcome != Resume {
		t.Fatalf("Begin on a departed, settled session = %v, want Resume", l.Outcome)
	}
}

// Spec § Session states' activity rule: a request in flight is activity, so a
// session is idle from the END of its last request, never from its arrival.
func TestARequestInFlightHoldsASessionActive(t *testing.T) {
	r := newRig(t)
	s := r.active(r.owner("c1"), "a")

	if l := r.table.Begin(s.ID); l.Outcome != Serve {
		t.Fatalf("Begin = %v, want Serve", l.Outcome)
	}
	r.clock.Advance(12 * time.Second)
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatal("a session with a request in flight departed at t + 12 s")
	}
	r.clock.Advance(47 * time.Second) // t + 59 s
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatal("a session with a request in flight departed at t + 59 s")
	}
	r.clock.Advance(time.Second) // t + 60 s: the request ends
	r.table.End(s.ID)
	r.clock.Advance(11*time.Second + 999*time.Millisecond) // t + 71.999 s
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatal("departed 11.999 s after the request ended")
	}
	r.clock.Advance(time.Millisecond) // t + 72 s
	if got := r.table.Sweep(); len(got) != 1 {
		t.Fatalf("at t + 72 s the sweep departed %d sessions, want 1", len(got))
	}
}

func TestTheIdleTimeoutScalesWithTheTargetDuration(t *testing.T) {
	if got := IdleTimeout(2 * time.Second); got != 12*time.Second {
		t.Fatalf("IdleTimeout(2 s) = %v, want 12 s", got)
	}
	if got := IdleTimeout(6 * time.Second); got != 36*time.Second {
		t.Fatalf("IdleTimeout(6 s) = %v, want 36 s", got)
	}

	r := newRig(t)
	s := r.add(r.owner("c1"), "slow", 6*time.Second)
	if !r.table.Activate(s.ID) {
		t.Fatal("Activate refused")
	}
	r.clock.Advance(35 * time.Second)
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatal("a TARGETDURATION 6 s session departed at 35 s")
	}
	r.clock.Advance(time.Second)
	if got := r.table.Sweep(); len(got) != 1 {
		t.Fatalf("a TARGETDURATION 6 s session did not depart at 36 s: %d departures", len(got))
	}
}

func TestALeaveRemovesTheSessionAndReturnsItsReleasesOnce(t *testing.T) {
	r := newRig(t)
	s := r.active(r.owner("c1"), "a")

	d := r.table.Leave(s.ID)
	if d == nil {
		t.Fatal("Leave returned no departure for a live session")
	}
	d.Run()
	want := []string{"disconnect a", "output a", "client a"}
	if got := r.j.all(); !slices.Equal(got, want) {
		t.Fatalf("the leave did %v, want %v", got, want)
	}
	if d := r.table.Leave(s.ID); d != nil {
		t.Fatal("a second Leave returned a departure: the releases would run twice")
	}
	if l := r.table.Begin(s.ID); l.Outcome != Unknown {
		t.Fatalf("Begin after a leave = %v, want Unknown", l.Outcome)
	}

	// An ARRIVED session's leave owes no client_disconnect: its connect was
	// never emitted.
	arrived := r.add(r.owner("c1"), "b", 2*time.Second)
	r.table.Leave(arrived.ID).Run()
	if got := r.j.all(); slices.Contains(got[3:], "disconnect b") {
		t.Fatalf("an ARRIVED session's leave emitted client_disconnect: %v", got)
	}
}

func TestADepartedSessionIsResumableForThreeHundredSeconds(t *testing.T) {
	r := newRig(t)
	s := r.active(r.owner("c1"), "a")
	r.departIdle(s)

	r.clock.Advance(299 * time.Second)
	if l := r.table.Begin(s.ID); l.Outcome != Resume {
		t.Fatalf("at +299 s Begin = %v, want Resume", l.Outcome)
	}
	r.clock.Advance(2 * time.Second)
	if l := r.table.Begin(s.ID); l.Outcome != Unknown {
		t.Fatalf("at +301 s Begin = %v, want Unknown", l.Outcome)
	}
	if r.table.Len() != 0 {
		t.Fatalf("the expired session is still in the table (%d entries)", r.table.Len())
	}
}

// Decision 5: an idle departure settles before it is resumable, or a resume
// could re-register the client id before the departure had dropped it.
func TestASettlingDepartureIsBusyNotResumable(t *testing.T) {
	r := newRig(t)
	s := r.active(r.owner("c1"), "a")
	r.clock.Advance(IdleTimeout(s.TD))
	departures := r.table.Sweep()
	if len(departures) != 1 {
		t.Fatalf("%d departures, want 1", len(departures))
	}

	if l := r.table.Begin(s.ID); l.Outcome != Busy {
		t.Fatalf("Begin during a settling departure = %v, want Busy", l.Outcome)
	}
	if r.table.ResumeCommit(s.ID, &channel.Client{ID: "a"}, Releases{}) {
		t.Fatal("ResumeCommit succeeded on a settling departure")
	}
	departures[0].Run()
	if l := r.table.Begin(s.ID); l.Outcome != Resume {
		t.Fatalf("Begin after the departure settled = %v, want Resume", l.Outcome)
	}
}

// A lazy expiry: a request that beats the sweeper to an idle session ends it
// exactly as the sweep would, and asks the caller to run the departure.
func TestABeginPastTheIdleTimeoutEndsTheSessionLazily(t *testing.T) {
	r := newRig(t)
	s := r.active(r.owner("c1"), "a")
	r.clock.Advance(IdleTimeout(s.TD))

	l := r.table.Begin(s.ID)
	if l.Depart == nil {
		t.Fatalf("Begin past the idle timeout returned no departure (outcome %v)", l.Outcome)
	}
	l.Depart.Run()
	if l := r.table.Begin(s.ID); l.Outcome != Resume {
		t.Fatalf("Begin after the lazy departure = %v, want Resume", l.Outcome)
	}
}

func TestStopChannelMarksOnlyThatChannelsSessions(t *testing.T) {
	r := newRig(t)
	c1, c2 := r.owner("c1"), r.owner("c2")

	// The DEPARTED session goes first: aging it also ages every session that
	// exists then, and departIdle expects to depart exactly one.
	departed := r.active(c1, "departed")
	r.departIdle(departed)
	arrived := r.add(c1, "arrived", 2*time.Second)
	active := r.active(c1, "active")
	other := r.active(c2, "other")
	journalBefore := len(r.j.all())

	stopped := r.table.stopOwner(c1)
	slices.SortFunc(stopped, func(a, b channel.StoppedClient) int {
		if a.ClientID < b.ClientID {
			return -1
		}
		return 1
	})
	want := []channel.StoppedClient{{ClientID: "active", Connected: true}, {ClientID: "arrived", Connected: false}}
	if !slices.Equal(stopped, want) {
		t.Fatalf("stopOwner returned %+v, want %+v (the ARRIVED and ACTIVE sessions' entries, and nothing for the DEPARTED one)", stopped, want)
	}
	if got := len(r.j.all()); got != journalBefore {
		t.Fatalf("stopping the channel ran %d release or event calls; releases are DISCARDED, the stopper drops the entries", got-journalBefore)
	}
	for _, s := range []*Session{arrived, active, departed} {
		if l := r.table.Begin(s.ID); l.Outcome != Gone {
			t.Fatalf("Begin on a stopped channel's session = %v, want Gone", l.Outcome)
		}
	}
	if l := r.table.Begin(other.ID); l.Outcome != Serve {
		t.Fatalf("the other channel's session = %v, want Serve", l.Outcome)
	}
}

func TestAStoppedSessionIs410OnceThenForgotten(t *testing.T) {
	r := newRig(t)
	c1 := r.owner("c1")
	s := r.active(c1, "a")
	r.table.stopOwner(c1)

	if l := r.table.Begin(s.ID); l.Outcome != Gone {
		t.Fatalf("first Begin on a STOPPED session = %v, want Gone", l.Outcome)
	}
	if l := r.table.Begin(s.ID); l.Outcome != Unknown {
		t.Fatalf("second Begin = %v, want Unknown (403 after the one 410)", l.Outcome)
	}

	// Unrequested for ResumeWindow: the sweep forgets it.
	quiet := r.active(c1, "quiet")
	r.table.stopOwner(c1)
	r.clock.Advance(ResumeWindow + time.Second)
	r.table.Sweep()
	if r.table.Len() != 0 {
		t.Fatalf("%d sessions remain after a STOPPED one went unrequested for %v", r.table.Len(), ResumeWindow)
	}
	if l := r.table.Begin(quiet.ID); l.Outcome != Unknown {
		t.Fatalf("Begin on a swept STOPPED session = %v, want Unknown", l.Outcome)
	}
}

func TestEndClientEndsOnlyThatClientsLiveSession(t *testing.T) {
	r := newRig(t)
	c1 := r.owner("c1")

	old := r.active(c1, "a")
	r.departIdle(old) // a DEPARTED session that once held client id "a"
	live := r.active(c1, "a")
	bystander := r.active(c1, "b")
	elsewhere := r.active(r.owner("c2"), "a")

	d := r.table.EndClient(c1, "a")
	if d == nil {
		t.Fatal("EndClient found no live session for client a on c1")
	}
	d.Run()
	if l := r.table.Begin(live.ID); l.Outcome != Unknown {
		t.Fatalf("the ended session's next request = %v, want Unknown (403)", l.Outcome)
	}
	if l := r.table.Begin(old.ID); l.Outcome != Resume {
		t.Fatalf("the DEPARTED session with the same client id = %v, want it left alone (Resume)", l.Outcome)
	}
	for name, s := range map[string]*Session{"the bystander": bystander, "another channel's": elsewhere} {
		if l := r.table.Begin(s.ID); l.Outcome != Serve {
			t.Fatalf("%s session = %v, want Serve", name, l.Outcome)
		}
	}
	if d := r.table.EndClient(c1, "a"); d != nil {
		t.Fatal("a second EndClient found a live session")
	}
}

func TestResumeCommitNeedsTheSessionStillDeparted(t *testing.T) {
	r := newRig(t)
	c1 := r.owner("c1")

	stopped := r.active(c1, "a")
	r.departIdle(stopped)
	// Between the resume's lookup and its commit, the channel stops.
	r.table.stopOwner(c1)
	if r.table.ResumeCommit(stopped.ID, &channel.Client{ID: "a"}, Releases{}) {
		t.Fatal("ResumeCommit succeeded on a session STOPPED since the lookup")
	}

	resumed := r.active(c1, "b")
	r.departIdle(resumed)
	if !r.table.ResumeCommit(resumed.ID, &channel.Client{ID: "b"}, r.releases("b")) {
		t.Fatal("ResumeCommit refused a DEPARTED, settled session")
	}
	if l := r.table.Begin(resumed.ID); l.Outcome != Serve {
		t.Fatalf("a resumed session's next request = %v, want Serve", l.Outcome)
	}
	// The resume's request is in flight until End: a sweep does not depart it.
	r.clock.Advance(time.Hour)
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatal("a resumed session with requests in flight departed")
	}
}

func TestAbandonReturnsTheReleasesOnlyWhileTheSessionHoldsThem(t *testing.T) {
	r := newRig(t)
	c1 := r.owner("c1")

	held := r.add(c1, "held", 2*time.Second)
	rel, ok := r.table.Abandon(held.ID)
	if !ok || rel == nil || rel.Output == nil || rel.Client == nil {
		t.Fatalf("Abandon on an ARRIVED session returned (%v, %t), want its releases", rel, ok)
	}

	// The stopper took the client entry: the session is STOPPED and holds no
	// releases, so the entry has nothing to run.
	taken := r.add(c1, "taken", 2*time.Second)
	r.table.stopOwner(c1)
	if rel, ok := r.table.Abandon(taken.ID); ok || rel != nil {
		t.Fatalf("Abandon on a STOPPED session returned (%v, %t), want none", rel, ok)
	}
	if rel, ok := r.table.Abandon("no-such-sid"); ok || rel != nil {
		t.Fatal("Abandon on an unknown session returned releases")
	}
}

func TestOutcomeNamesReadInFailureMessages(t *testing.T) {
	for outcome, want := range map[Outcome]string{
		Unknown: "Unknown", Gone: "Gone", Busy: "Busy", Resume: "Resume", Serve: "Serve", Outcome(99): "Outcome(?)",
	} {
		if got := outcome.String(); got != want {
			t.Errorf("Outcome(%d).String() = %q, want %q", int(outcome), got, want)
		}
	}
}

// A table built with no clock and no logger uses the real clock: a session it
// admits is served, and left, exactly as one on an injected clock.
func TestATableWithNoConfigUsesTheRealClock(t *testing.T) {
	table := NewTable(Config{})
	j := &journal{}
	owner := &fakeOwner{name: "c1", j: j}
	s := &Session{ID: "sid-real", Owner: owner, Key: "hls", Pipeline: &hls.Pipeline{}, TD: 2 * time.Second}
	table.Add(s, &channel.Client{ID: "a"}, Releases{Client: func() { j.add("client a") }})
	if !table.Activate(s.ID) {
		t.Fatal("Activate refused")
	}
	if l := table.Begin(s.ID); l.Outcome != Serve {
		t.Fatalf("Begin = %v, want Serve", l.Outcome)
	}
	table.End(s.ID)
	table.Leave(s.ID).Run()
	if got := j.all(); !slices.Equal(got, []string{"disconnect a", "client a"}) {
		t.Fatalf("the leave did %v", got)
	}
}

// An ARRIVED session's request counts as in flight from its arrival: a GET on
// it is served, and holds it in flight until End.
func TestABeginOnAnArrivedSessionServesAndHoldsItInFlight(t *testing.T) {
	r := newRig(t)
	s := r.add(r.owner("c1"), "a", 2*time.Second)
	if l := r.table.Begin(s.ID); l.Outcome != Serve || l.Client == nil || l.Client.ID != "a" || l.Pipeline != s.Pipeline {
		t.Fatalf("Begin on an ARRIVED session = %+v, want Serve with its client and pipeline", l)
	}
	r.table.End(s.ID)
	r.clock.Advance(time.Hour)
	if got := r.table.Sweep(); len(got) != 0 {
		t.Fatal("an ARRIVED session departed although its entry has not activated it")
	}
}

func TestAStoppedSessionUnrequestedPastTheWindowIsUnknownNotGone(t *testing.T) {
	r := newRig(t)
	c1 := r.owner("c1")
	s := r.active(c1, "a")
	r.table.stopOwner(c1)
	r.clock.Advance(ResumeWindow + time.Second)
	if l := r.table.Begin(s.ID); l.Outcome != Unknown {
		t.Fatalf("Begin on a STOPPED session 301 s later = %v, want Unknown (its one 410 is long past)", l.Outcome)
	}
	if r.table.Len() != 0 {
		t.Fatal("the expired STOPPED session is still in the table")
	}
}

func TestEndAndResumeFailedOnAnUnknownSessionChangeNothing(t *testing.T) {
	r := newRig(t)
	keep := r.active(r.owner("c1"), "a")
	r.table.End("no-such-sid")
	r.table.ResumeFailed("no-such-sid")
	if r.table.Len() != 1 {
		t.Fatalf("the table holds %d sessions after two calls on an unknown sid, want 1", r.table.Len())
	}
	r.table.ResumeFailed(keep.ID)
	if r.table.Len() != 0 {
		t.Fatal("ResumeFailed left the session in the table")
	}
}

// StopChannel and StopPipeline are the two entry points the channel package
// and the failure watcher call; both mark by identity.
func TestStopChannelAndStopPipelineMarkByIdentity(t *testing.T) {
	r := newRig(t)
	ch := &channel.Channel{}
	p := &hls.Pipeline{}

	byChannel := &Session{ID: "sid-ch", Owner: ch, Key: "hls", Pipeline: &hls.Pipeline{}, TD: 2 * time.Second}
	r.table.Add(byChannel, &channel.Client{ID: "on-channel"}, r.releases("on-channel"))
	r.table.Activate(byChannel.ID)
	byPipeline := &Session{ID: "sid-p", Owner: r.owner("other"), Key: "hls", Pipeline: p, TD: 2 * time.Second}
	r.table.Add(byPipeline, &channel.Client{ID: "on-pipeline"}, r.releases("on-pipeline"))
	r.table.Activate(byPipeline.ID)

	got := r.table.StopChannel(ch)
	if want := []channel.StoppedClient{{ClientID: "on-channel", Connected: true}}; !slices.Equal(got, want) {
		t.Fatalf("StopChannel = %+v, want %+v", got, want)
	}
	got = r.table.StopPipeline(p)
	if want := []channel.StoppedClient{{ClientID: "on-pipeline", Connected: true}}; !slices.Equal(got, want) {
		t.Fatalf("StopPipeline = %+v, want %+v", got, want)
	}
	for _, s := range []*Session{byChannel, byPipeline} {
		if l := r.table.Begin(s.ID); l.Outcome != Gone {
			t.Fatalf("Begin on a stopped session = %v, want Gone", l.Outcome)
		}
	}
}

// A leave of a session whose releases are not held -- DEPARTED and settled, or
// DEPARTED and still settling -- has nothing to run, and never runs them twice.
func TestALeaveOfADepartedSessionHasNothingToRun(t *testing.T) {
	r := newRig(t)
	settled := r.active(r.owner("c1"), "settled")
	r.departIdle(settled)
	if d := r.table.Leave(settled.ID); d != nil {
		t.Fatal("a leave of a DEPARTED session returned a departure: its releases would run twice")
	}

	settling := r.active(r.owner("c2"), "settling")
	r.clock.Advance(IdleTimeout(settling.TD))
	departures := r.table.Sweep()
	if len(departures) != 1 {
		t.Fatalf("%d departures, want 1", len(departures))
	}
	if d := r.table.Leave(settling.ID); d != nil {
		t.Fatal("a leave during a settling departure returned a second departure")
	}
	before := len(r.j.all())
	departures[0].Run() // the one departure runs its releases once
	if got := r.j.all()[before:]; !slices.Equal(got, []string{"disconnect settling", "output settling", "client settling"}) {
		t.Fatalf("the departure did %v", got)
	}
}

func TestADepartureRunsBeforeClientBetweenTheTwoReleases(t *testing.T) {
	r := newRig(t)
	o := r.owner("c1")
	s := &Session{ID: "sid-hook", Owner: o, Key: "hls", Pipeline: &hls.Pipeline{}, TD: 2 * time.Second}
	rel := r.releases("a")
	rel.BeforeClient = func() { r.j.add("before client a") }
	r.table.Add(s, &channel.Client{ID: "a"}, rel)
	r.table.Activate(s.ID)
	r.table.Leave(s.ID).Run()
	want := []string{"disconnect a", "output a", "before client a", "client a"}
	if got := r.j.all(); !slices.Equal(got, want) {
		t.Fatalf("the departure did %v, want %v", got, want)
	}
}

// With no injected tick the sweeper runs on its own one-second ticker, and it
// returns when its context ends.
func TestTheSweeperRunsOnItsOwnTickerAndStopsWithItsContext(t *testing.T) {
	table := NewTable(Config{})
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() {
		defer close(done)
		table.Run(ctx)
	}()
	cancel()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("Run did not return after its context ended")
	}
}
