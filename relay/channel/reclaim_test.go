package channel

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// releaser is ManagerConfig.Release: it records every call and, when gated,
// holds each one until open. The gate is what makes "a channel whose release
// has not landed yet" a state a test can hold rather than race.
type releaser struct {
	mu    sync.Mutex
	gate  chan struct{}
	once  sync.Once
	calls []string
}

func newReleaser(gated bool) *releaser {
	r := &releaser{}
	if gated {
		r.gate = make(chan struct{})
	}
	return r
}

func (r *releaser) release(id string, _ SourceInfo) {
	r.mu.Lock()
	r.calls = append(r.calls, id)
	g := r.gate
	r.mu.Unlock()
	if g != nil {
		<-g
	}
}

// open lets every held and later release through; idempotent.
func (r *releaser) open() {
	if r.gate != nil {
		r.once.Do(func() { close(r.gate) })
	}
}

func (r *releaser) opened() bool {
	if r.gate == nil {
		return true
	}
	select {
	case <-r.gate:
		return true
	default:
		return false
	}
}

func (r *releaser) count(id string) int {
	r.mu.Lock()
	defer r.mu.Unlock()
	n := 0
	for _, c := range r.calls {
		if c == id {
			n++
		}
	}
	return n
}

// fakeJudge is a SilenceJudge whose verdicts the test writes: a channel id in
// silent is silent since that time, and one in refuseStop fails the re-check.
type fakeJudge struct {
	mu          sync.Mutex
	silent      map[string]time.Time
	refuseStop  map[string]bool
	silentCalls []string
	// silentIDs is the id list each Silent call carried, in call order (4a-3:
	// a zero-client channel asks the judge with an empty list).
	silentIDs [][]string
	stopCalls map[string][][]string
}

func newFakeJudge() *fakeJudge {
	return &fakeJudge{
		silent:     map[string]time.Time{},
		refuseStop: map[string]bool{},
		stopCalls:  map[string][][]string{},
	}
}

func (j *fakeJudge) Silent(c *Channel, ids []string) (time.Time, bool) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.silentCalls = append(j.silentCalls, c.ID())
	j.silentIDs = append(j.silentIDs, append([]string(nil), ids...))
	since, ok := j.silent[c.ID()]
	return since, ok
}

func (j *fakeJudge) StopIfSilent(c *Channel, ids []string) ([]StoppedClient, bool) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.stopCalls[c.ID()] = append(j.stopCalls[c.ID()], append([]string(nil), ids...))
	if j.refuseStop[c.ID()] {
		return nil, false
	}
	return nil, true
}

func (j *fakeJudge) stopped() []string {
	j.mu.Lock()
	defer j.mu.Unlock()
	var out []string
	for id := range j.stopCalls {
		out = append(out, id)
	}
	return out
}

// reclaimManager is a manager with the releaser and judge wired in.
func reclaimManager(t *testing.T, rel *releaser, judge SilenceJudge, mutate func(*ManagerConfig)) *Manager {
	t.Helper()
	cfg := ManagerConfig{
		BudgetBytes: buffer.TSPacketSize * 64,
		StopWait:    2 * time.Second,
		Release:     rel.release,
		Silence:     judge,
	}
	if mutate != nil {
		mutate(&cfg)
	}
	m := NewManager(cfg)
	t.Cleanup(func() {
		rel.open()
		m.StopAll()
	})
	return m
}

// attachOnProfile starts a channel on the given M3U profile with one client.
func attachOnProfile(t *testing.T, m *Manager, id, clientID string, profile int, tuning Tuning) (*Channel, func()) {
	t.Helper()
	ch, release, err := m.Attach(id, testClient(clientID), func() (Started, error) {
		return Started{
			Source: blockingSource{started: &int32Counter{}},
			Tuning: tuning,
			Info:   SourceInfo{M3UProfileID: profile},
		}, nil
	})
	if err != nil {
		t.Fatalf("Attach(%s): %v", id, err)
	}
	return ch, release
}

func inMap(m *Manager, c *Channel) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.channels[c.ID()] == c
}

func releasingHas(m *Manager, c *Channel) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	_, ok := m.releasing[c]
	return ok
}

func TestReclaimForTakesTheLongestReclaimableChannelOnABlockingProfile(t *testing.T) {
	rel := newReleaser(false)
	judge := newFakeJudge()
	m := reclaimManager(t, rel, judge, nil)

	x, _ := attachOnProfile(t, m, "X", "cx", 1, testTuning())
	y, _ := attachOnProfile(t, m, "Y", "cy", 1, testTuning())
	z, _ := attachOnProfile(t, m, "Z", "cz", 2, testTuning())
	now := time.Now()
	judge.silent["X"] = now.Add(-10 * time.Second)
	judge.silent["Y"] = now.Add(-5 * time.Second)
	judge.silent["Z"] = now.Add(-20 * time.Second)

	got := m.ReclaimFor([]int{1}, 2*time.Second)
	if want := (Reclaim{Case: ReclaimStopped, Channel: "X", Released: true}); got != want {
		t.Fatalf("ReclaimFor = %+v, want %+v", got, want)
	}
	<-x.Done()
	<-x.Released()
	for _, c := range []*Channel{y, z} {
		if !inMap(m, c) || c.Ring().Closed() {
			t.Fatalf("channel %s was touched by a reclaim aimed at profile 1 and the longest-silent X", c.ID())
		}
	}
	if stopped := judge.stopped(); len(stopped) != 1 || stopped[0] != "X" {
		t.Fatalf("the judge's StopIfSilent ran for %v, want X only", stopped)
	}
}

func TestAChannelTheJudgeRefusesIsNeverReclaimed(t *testing.T) {
	rel := newReleaser(false)
	judge := newFakeJudge() // Silent answers false for every channel
	m := reclaimManager(t, rel, judge, nil)
	c, _ := attachOnProfile(t, m, "A", "ca", 1, testTuning())

	got := m.ReclaimFor([]int{1}, time.Second)
	if got.Case != ReclaimNothing || got.Channel != "" {
		t.Fatalf("ReclaimFor = %+v, want {ReclaimNothing}", got)
	}
	if !inMap(m, c) || c.Ring().Closed() {
		t.Fatal("the refused channel is no longer running in the map")
	}
	if n := rel.count("A"); n != 0 {
		t.Fatalf("the refused channel's release ran %d times", n)
	}
}

func TestADeclinedReCheckLeavesTheChannelRunning(t *testing.T) {
	rel := newReleaser(false)
	judge := newFakeJudge()
	m := reclaimManager(t, rel, judge, nil)
	c, _ := attachOnProfile(t, m, "A", "ca", 1, testTuning())
	judge.silent["A"] = time.Now().Add(-time.Minute)
	judge.refuseStop["A"] = true

	got := m.ReclaimFor([]int{1}, time.Second)
	if want := (Reclaim{Case: ReclaimDeclined, Channel: "A"}); got != want {
		t.Fatalf("ReclaimFor = %+v, want %+v", got, want)
	}
	if !inMap(m, c) || c.Ring().Closed() {
		t.Fatal("a channel that failed the re-check is no longer running in the map")
	}
}

// D16's last sentence: a channel with no client, still in its shutdown delay,
// is reclaimable, and the pick's verdict for it is the manager's own.
func TestAZeroClientChannelInItsShutdownDelayIsReclaimable(t *testing.T) {
	rel := newReleaser(false)
	judge := newFakeJudge()
	m := reclaimManager(t, rel, judge, nil)
	var mu sync.Mutex
	var sites []string
	m.afterRemove = func(_ *Channel, site string) {
		mu.Lock()
		sites = append(sites, site)
		mu.Unlock()
	}

	// A zero-client channel now asks the judge for the behind-live grace (Phase
	// 4a-3): "silent, since the zero time", so the ranking is the idle time's.
	judge.silent["A"] = time.Time{}
	tuning := testTuning()
	tuning.ShutdownDelay = time.Second
	c, release := attachOnProfile(t, m, "A", "ca", 1, tuning)
	release() // the last client: the channel waits out its ShutdownDelay
	if !inMap(m, c) {
		t.Fatal("the channel left the map before its shutdown delay ran")
	}

	got := m.ReclaimFor([]int{1}, 2*time.Second)
	if want := (Reclaim{Case: ReclaimStopped, Channel: "A", Released: true}); got != want {
		t.Fatalf("ReclaimFor = %+v, want %+v", got, want)
	}
	judge.mu.Lock()
	silentIDs, stopCalls := judge.silentIDs, judge.stopCalls["A"]
	judge.mu.Unlock()
	if len(silentIDs) != 1 || len(silentIDs[0]) != 0 {
		t.Fatalf("Silent calls = %v, want exactly one, with an empty client list (the behind-live grace's question)", silentIDs)
	}
	if len(stopCalls) != 1 || len(stopCalls[0]) != 0 {
		t.Fatalf("StopIfSilent calls = %v, want exactly one with an empty client list (the re-check still runs)", stopCalls)
	}
	if n := rel.count("A"); n != 1 {
		t.Fatalf("the release func ran %d times, want 1", n)
	}
	<-c.Released()
	m.mu.Lock()
	left := len(m.releasing)
	m.mu.Unlock()
	if left != 0 {
		t.Fatalf("the releasing set holds %d entries after the release landed", left)
	}

	// The countdown's own stopIfStillIdle fires 1 s after the release above.
	// It finds a map entry that is not c (none at all), so it deletes and
	// inserts nothing, and its c.stop returns at once on the closed done.
	time.Sleep(1500 * time.Millisecond)
	mu.Lock()
	defer mu.Unlock()
	if len(sites) != 1 || sites[0] != "reclaim" {
		t.Fatalf("removals = %v, want exactly one, from the reclaim (the late countdown must remove nothing)", sites)
	}
	if n := rel.count("A"); n != 1 {
		t.Fatalf("the release func ran %d times after the countdown, want 1", n)
	}
}

func TestReclaimForWithNoJudgeTakesOnlyAChannelWithNoClient(t *testing.T) {
	rel := newReleaser(false)
	m := reclaimManager(t, rel, nil, nil)

	// With testTuning()'s zero ShutdownDelay the last release would stop the
	// channel at once and it would leave the map; a delay keeps it there.
	tuning := testTuning()
	tuning.ShutdownDelay = time.Second

	watched, _ := attachOnProfile(t, m, "watched", "cw", 1, tuning)
	if got := m.ReclaimFor([]int{1}, time.Second); got.Case != ReclaimNothing {
		t.Fatalf("with one client and no judge, ReclaimFor = %+v, want {ReclaimNothing}", got)
	}
	if !inMap(m, watched) {
		t.Fatal("the watched channel left the map")
	}

	idle, release := attachOnProfile(t, m, "idle", "ci", 2, tuning)
	release()
	if got := m.ReclaimFor([]int{2}, 2*time.Second); got.Case != ReclaimStopped || got.Channel != "idle" {
		t.Fatalf("with no client and no judge, ReclaimFor = %+v, want a stop of idle", got)
	}
	<-idle.Done()
}

func TestReclaimForWaitsOnAReleasingChannel(t *testing.T) {
	t.Run("the release lands", func(t *testing.T) {
		rel := newReleaser(true)
		m := reclaimManager(t, rel, newFakeJudge(), nil)
		c, _ := attachOnProfile(t, m, "A", "ca", 1, testTuning())
		if !m.Stop("A") {
			t.Fatal("Stop did not find the channel")
		}
		<-c.Done() // stopped, and its release is held at the gate
		if !releasingHas(m, c) {
			t.Fatal("a stopped channel whose release has not landed is not in the releasing set")
		}

		done := make(chan Reclaim, 1)
		go func() { done <- m.ReclaimFor([]int{1}, 2*time.Second) }()
		select {
		case got := <-done:
			t.Fatalf("ReclaimFor returned %+v while the release was still held", got)
		case <-time.After(100 * time.Millisecond):
		}
		rel.open()
		got := <-done
		if want := (Reclaim{Case: ReclaimWaited, Channel: "A", Released: true}); got != want {
			t.Fatalf("ReclaimFor = %+v, want %+v", got, want)
		}
	})

	t.Run("the wait ends first", func(t *testing.T) {
		rel := newReleaser(true)
		m := reclaimManager(t, rel, newFakeJudge(), nil)
		c, _ := attachOnProfile(t, m, "A", "ca", 1, testTuning())
		m.Stop("A")
		<-c.Done()

		start := time.Now()
		got := m.ReclaimFor([]int{1}, 200*time.Millisecond)
		if want := (Reclaim{Case: ReclaimWaited, Channel: "A", Released: false}); got != want {
			t.Fatalf("ReclaimFor = %+v, want %+v", got, want)
		}
		if rel.opened() {
			t.Fatal("the gate was open when ReclaimFor returned; the wait ended for the wrong reason")
		}
		// A guard against an unbounded wait, not a latency pin: a tighter
		// real-time bound flakes under -race on a shared runner.
		if took := time.Since(start); took > 10*time.Second {
			t.Fatalf("ReclaimFor took %v against a 200 ms wait", took)
		}
	})
}

// A releasing entry older than StopWait + wait is one whose stop timed out; it
// may never release, so a later reclaim ignores it and drops it.
func TestAStaleReleasingEntryIsIgnored(t *testing.T) {
	var mu sync.Mutex
	clock := time.Unix(1_700_000_000, 0)
	now := func() time.Time {
		mu.Lock()
		defer mu.Unlock()
		return clock
	}
	advance := func(d time.Duration) {
		mu.Lock()
		clock = clock.Add(d)
		mu.Unlock()
	}

	rel := newReleaser(true)
	judge := newFakeJudge()
	m := reclaimManager(t, rel, judge, func(cfg *ManagerConfig) {
		cfg.Now = now
		cfg.StopWait = time.Second
	})
	a, _ := attachOnProfile(t, m, "A", "ca", 1, testTuning())
	m.Stop("A")
	<-a.Done()
	if !releasingHas(m, a) {
		t.Fatal("A is not in the releasing set")
	}
	advance(time.Second + 300*time.Millisecond + time.Second) // past StopWait + wait

	attachOnProfile(t, m, "B", "cb", 1, testTuning())
	judge.silent["B"] = now().Add(-time.Minute)

	got := m.ReclaimFor([]int{1}, 300*time.Millisecond)
	if got.Case != ReclaimStopped || got.Channel != "B" {
		t.Fatalf("ReclaimFor = %+v, want a stop of B: the stale releasing entry for A must be ignored", got)
	}
	if releasingHas(m, a) {
		t.Fatal("the stale releasing entry was not dropped")
	}
}

// The spec's four-path assertion, deterministically: afterRemove runs inside
// each removal's m.mu critical section, so the check reads the maps directly.
func TestEveryMapRemovalInsertsIntoTheReleasingSet(t *testing.T) {
	type removal struct {
		site     string
		gone     bool
		inSet    bool
		released bool
	}
	install := func(m *Manager) (removals func() []removal) {
		var mu sync.Mutex
		var seen []removal
		m.afterRemove = func(c *Channel, site string) {
			// m.mu is held by the removal, so the maps are read directly.
			_, inSet := m.releasing[c]
			r := removal{site: site, gone: m.channels[c.ID()] != c, inSet: inSet, released: isReleased(c)}
			mu.Lock()
			seen = append(seen, r)
			mu.Unlock()
		}
		return func() []removal {
			mu.Lock()
			defer mu.Unlock()
			return append([]removal(nil), seen...)
		}
	}
	check := func(t *testing.T, got []removal, site string, wantSet bool) {
		t.Helper()
		if len(got) != 1 || got[0].site != site {
			t.Fatalf("removals = %+v, want exactly one, from %q", got, site)
		}
		r := got[0]
		if !r.gone {
			t.Fatalf("site %q: the channel was still the map's entry inside the removal", site)
		}
		if wantSet && !r.inSet {
			t.Fatalf("site %q removed the channel from the map with no releasing entry and no landed release", site)
		}
		if !wantSet && r.inSet {
			t.Fatalf("site %q inserted a channel whose release had already landed", site)
		}
	}

	t.Run("take", func(t *testing.T) {
		rel := newReleaser(true)
		m := reclaimManager(t, rel, newFakeJudge(), nil)
		removals := install(m)
		attachOnProfile(t, m, "A", "ca", 1, testTuning())
		m.Stop("A")
		check(t, removals(), "take", true)
	})

	t.Run("stopIfStillIdle", func(t *testing.T) {
		rel := newReleaser(true)
		m := reclaimManager(t, rel, newFakeJudge(), nil)
		removals := install(m)
		_, release := attachOnProfile(t, m, "A", "ca", 1, testTuning())
		release()
		check(t, removals(), "stopIfStillIdle", true)
	})

	t.Run("claim", func(t *testing.T) {
		rel := newReleaser(true)
		m := reclaimManager(t, rel, newFakeJudge(), nil)
		removals := install(m)
		endedByItself(t, m, "A")
		// The release is held at the gate, so it cannot land before claim.
		attachOnProfile(t, m, "A", "cb", 1, testTuning())
		check(t, removals(), "claim", true)
	})

	t.Run("reclaim", func(t *testing.T) {
		rel := newReleaser(true)
		judge := newFakeJudge()
		m := reclaimManager(t, rel, judge, nil)
		removals := install(m)
		attachOnProfile(t, m, "A", "ca", 1, testTuning())
		judge.silent["A"] = time.Now().Add(-time.Minute)
		go func() {
			// The release stays held, so the reclaim's own wait ends by its deadline.
			m.ReclaimFor([]int{1}, 100*time.Millisecond)
		}()
		waitFor(t, "the reclaim's removal", 5*time.Second, func() bool { return len(removals()) == 1 })
		check(t, removals(), "reclaim", true)
	})

	t.Run("claim after the release landed", func(t *testing.T) {
		rel := newReleaser(false)
		m := reclaimManager(t, rel, newFakeJudge(), nil)
		removals := install(m)
		ended := endedByItself(t, m, "A")
		<-ended.Released()
		attachOnProfile(t, m, "A", "cb", 1, testTuning())
		check(t, removals(), "claim", false)
	})
}

// endedByItself starts a channel whose only source fails until it is out of
// retries, so its ring closes and its run ends while a client is still
// attached: it stays in the map, finished, until claim drops it.
func endedByItself(t *testing.T, m *Manager, id string) *Channel {
	t.Helper()
	tuning := testTuning()
	tuning.MaxRetries = 1
	ch, release, err := m.Attach(id, testClient("first-"+id), asStarted(func() (Source, Tuning, error) {
		return failingSource{runs: &int32Counter{}}, tuning, nil
	}))
	if err != nil {
		t.Fatalf("Attach(%s): %v", id, err)
	}
	t.Cleanup(release)
	<-ch.Done()
	if m.Get(id) != ch {
		t.Fatalf("the finished channel %s left the map on its own", id)
	}
	return ch
}

// A releasing entry never outlives its release: the close and the delete share
// one critical section, so once released is closed a read under m.mu finds no
// entry. Deterministic, not a poll.
func TestAReleasingEntryNeverOutlivesItsRelease(t *testing.T) {
	assertGone := func(t *testing.T, m *Manager, c *Channel) {
		t.Helper()
		<-c.Released()
		if releasingHas(m, c) {
			t.Fatal("a releasing entry outlived its channel's release")
		}
	}

	t.Run("take", func(t *testing.T) {
		m := reclaimManager(t, newReleaser(false), newFakeJudge(), nil)
		c, _ := attachOnProfile(t, m, "A", "ca", 1, testTuning())
		m.Stop("A")
		assertGone(t, m, c)
	})
	t.Run("stopIfStillIdle", func(t *testing.T) {
		m := reclaimManager(t, newReleaser(false), newFakeJudge(), nil)
		c, release := attachOnProfile(t, m, "A", "ca", 1, testTuning())
		release()
		assertGone(t, m, c)
	})
	t.Run("claim", func(t *testing.T) {
		m := reclaimManager(t, newReleaser(false), newFakeJudge(), nil)
		c := endedByItself(t, m, "A")
		// Wait for the release BEFORE the attach that triggers claim's
		// delete, so the delete meets an already-closed released. A claim
		// that preceded the release would insert and then be correctly
		// removed by m.released, which no wrong insertion could redden.
		<-c.Released()
		attachOnProfile(t, m, "A", "cb", 1, testTuning())
		assertGone(t, m, c)
	})
	t.Run("reclaim", func(t *testing.T) {
		judge := newFakeJudge()
		m := reclaimManager(t, newReleaser(false), judge, nil)
		c, _ := attachOnProfile(t, m, "A", "ca", 1, testTuning())
		judge.silent["A"] = time.Now().Add(-time.Minute)
		m.ReclaimFor([]int{1}, time.Second)
		assertGone(t, m, c)
	})
}

// The spec's "or run ended (ring closed)" releasing class: a channel whose
// source returned on its own, still in the map for its attached client, with
// its release not landed. A blocked tune waits on it.
func TestReclaimForWaitsOnARunThatEndedByItself(t *testing.T) {
	rel := newReleaser(true)
	m := reclaimManager(t, rel, newFakeJudge(), nil)
	ended := endedByItself(t, m, "A")
	// endedByItself's channel carries no M3U profile; reach the wanted one
	// through its source info, as a next-source answer would have.
	ended.mu.Lock()
	ended.source.M3UProfileID = 1
	ended.mu.Unlock()

	done := make(chan Reclaim, 1)
	go func() { done <- m.ReclaimFor([]int{1}, 2*time.Second) }()
	select {
	case got := <-done:
		t.Fatalf("ReclaimFor returned %+v while the release was still held", got)
	case <-time.After(100 * time.Millisecond):
	}
	rel.open()
	got := <-done
	if want := (Reclaim{Case: ReclaimWaited, Channel: "A", Released: true}); got != want {
		t.Fatalf("ReclaimFor = %+v, want %+v", got, want)
	}

	for c, want := range map[ReclaimCase]string{
		ReclaimNothing: "nothing", ReclaimWaited: "waited",
		ReclaimStopped: "stopped", ReclaimDeclined: "declined",
	} {
		if c.String() != want {
			t.Fatalf("ReclaimCase(%d).String() = %q, want %q", int(c), c.String(), want)
		}
	}
}

// Row ⟨F⟩ (spec D15, D16; R82): a lingering channel with no client asks the
// judge for the behind-live grace, and is reclaimed only once the judge says
// it is past it.
func TestALingeringChannelIsReclaimedOnlyPastItsGrace(t *testing.T) {
	judge := newFakeJudge()
	g := newLingerRig(t, func(cfg *ManagerConfig) { cfg.Silence = judge })
	ch, release := g.attach("A", "ca", lingerTuning())
	starter := newReadyStarter(t)
	p, _, out, err := ch.AttachHLS("hls", starter.start)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := p.Ready(ctx); err != nil {
		t.Fatal(err)
	}
	out()
	release()
	if _, ok := ch.Lingering(); !ok || ch.Clients() != 0 {
		t.Fatalf("the channel is not lingering with no client")
	}
	linger := g.timers.pending()[0]

	if got := g.m.ReclaimFor([]int{1}, time.Second); got.Case != ReclaimNothing {
		t.Fatalf("ReclaimFor with the judge inside the grace = %+v, want nothing", got)
	}
	judge.mu.Lock()
	ids := judge.silentIDs
	judge.mu.Unlock()
	if len(ids) != 1 || len(ids[0]) != 0 {
		t.Fatalf("Silent calls = %v, want exactly one, with an empty client list", ids)
	}
	if !inMap(g.m, ch) {
		t.Fatal("a channel inside its grace was removed")
	}

	judge.mu.Lock()
	judge.silent["A"] = time.Time{}
	judge.mu.Unlock()
	got := g.m.ReclaimFor([]int{1}, 5*time.Second)
	if got.Case != ReclaimStopped || got.Channel != "A" {
		t.Fatalf("ReclaimFor past the grace = %+v, want stopped A", got)
	}
	if !linger.wasStopped() {
		t.Fatal("the reclaim left the linger's timer armed")
	}
	pipelineDone(t, p, "the reclaim stopped the channel")
}

func TestLaterIsTheLaterOfTwoTimes(t *testing.T) {
	early := time.Unix(1_000, 0)
	late := time.Unix(2_000, 0)
	if got := later(early, late); !got.Equal(late) {
		t.Fatalf("later(early, late) = %v, want the late one", got)
	}
	if got := later(late, early); !got.Equal(late) {
		t.Fatalf("later(late, early) = %v, want the late one", got)
	}
}
