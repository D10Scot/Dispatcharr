package procstat

import (
	"errors"
	"testing"
)

// scripted returns one prepared snapshot per Snapshot call, so every figure a
// test expects is exact.
type scripted struct {
	snaps [][]Proc
	n     int
	err   error
}

func (s *scripted) Snapshot() ([]Proc, error) {
	if s.err != nil {
		return nil, s.err
	}
	snap := s.snaps[s.n]
	s.n++
	return snap, nil
}
func (*scripted) TicksPerSecond() float64 { return 100 }
func (*scripted) PageSize() int           { return 4096 }

var lab = Labels{ChannelID: 7, Kind: KindSource}

func proc(pid int, start uint64, secs int, rss int64) Proc {
	return Proc{PID: pid, PGrp: 500, Start: start, CPUTicks: uint64(secs) * 100, RSSPages: rss}
}

func cpu(t *testing.T, r *Registry, l Labels) float64 {
	t.Helper()
	for _, s := range r.Collect() {
		if s.Labels == l {
			return s.CPUSeconds
		}
	}
	t.Fatalf("no sample for %+v", l)
	return 0
}

func TestOverlapReportsTheSumOfGrowth(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{proc(500, 10, 2, 0), proc(501, 11, 3, 0)},
		{proc(500, 10, 4, 0), proc(501, 11, 5, 0)},
	}}
	r := NewRegistry(src)
	r.Track(500, lab)
	if got := cpu(t, r, lab); got != 5 {
		t.Fatalf("first collection = %v, want 5", got)
	}
	if got := cpu(t, r, lab); got != 9 {
		t.Fatalf("second collection = %v, want 9", got)
	}
}

// accountingFixture runs tests 1-3's snapshots up to the point test 2 begins.
func accountingFixture() (*Registry, *scripted) {
	src := &scripted{snaps: [][]Proc{
		{proc(500, 10, 2, 0), proc(501, 11, 3, 0)},
		{proc(500, 10, 4, 0), proc(501, 11, 5, 0)},
		{proc(500, 10, 6, 0)},                      // the child departed
		{proc(500, 10, 6, 0), proc(501, 99, 1, 0)}, // pid 501 reused
	}}
	r := NewRegistry(src)
	r.Track(500, lab)
	return r, src
}

func TestADepartingChildKeepsItsAccumulatedCPU(t *testing.T) {
	r, _ := accountingFixture()
	cpu(t, r, lab)
	cpu(t, r, lab)
	// Reporting the live sum would give 6 here, a fall a backend reads as a
	// counter reset.
	if got := cpu(t, r, lab); got != 11 {
		t.Fatalf("after the child left = %v, want 11 (9 + the leader's 2)", got)
	}
}

func TestAReusedPidIsANewIdentity(t *testing.T) {
	r, _ := accountingFixture()
	cpu(t, r, lab)
	cpu(t, r, lab)
	cpu(t, r, lab)
	// 501 came back with a different starttime at 1 s. Keyed by pid alone the
	// delta would be 1 - 5 = -4.
	if got := cpu(t, r, lab); got != 12 {
		t.Fatalf("after pid reuse = %v, want 12", got)
	}
}

func TestTwoGroupsWithOneLabelSetShareAnAccumulator(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{{PID: 500, PGrp: 500, Start: 1, CPUTicks: 200}, {PID: 600, PGrp: 600, Start: 2, CPUTicks: 300}},
	}}
	r := NewRegistry(src)
	r.Track(500, lab)
	r.Track(600, lab)
	if got := cpu(t, r, lab); got != 5 {
		t.Fatalf("two groups = %v, want 5", got)
	}
}

func TestUntrackIsPinnedDirectly(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{proc(500, 10, 2, 0), proc(501, 11, 3, 0)},
		{proc(500, 10, 9, 0), proc(501, 11, 9, 0)}, // would add 13 if still read
	}}
	r := NewRegistry(src)
	untrack := r.Track(500, lab)
	if got := cpu(t, r, lab); got != 5 {
		t.Fatalf("before untrack = %v, want 5", got)
	}
	untrack()
	untrack() // harmless the second time
	if g := r.Groups(); len(g) != 0 {
		t.Fatalf("registry still holds %+v after untrack", g)
	}
	if got := cpu(t, r, lab); got != 5 {
		t.Fatalf("a further snapshot changed the figure: %v, want 5", got)
	}
	for _, s := range r.Collect() {
		if s.Labels == lab && s.Live {
			t.Fatal("an untracked label set is still reported live")
		}
	}
}

func TestRSSIsTheLiveSumAndAGauge(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{proc(500, 10, 1, 10), proc(501, 11, 1, 5)},
		{proc(500, 10, 1, 8)},
	}}
	r := NewRegistry(src)
	r.Track(500, lab)
	if got := r.Collect()[0].RSSBytes; got != 15*4096 {
		t.Fatalf("rss = %d, want %d", got, 15*4096)
	}
	if got := r.Collect()[0].RSSBytes; got != 8*4096 {
		t.Fatalf("rss after a child left = %d, want %d", got, 8*4096)
	}
}

func TestTrackingASubsetOfTheGroupsIgnoresTheRest(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{{PID: 1, PGrp: 1, Start: 1, CPUTicks: 100}, {PID: 500, PGrp: 500, Start: 2, CPUTicks: 100}},
	}}
	r := NewRegistry(src)
	r.Track(500, lab)
	if got := cpu(t, r, lab); got != 1 {
		t.Fatalf("figure = %v, want 1 (only the tracked group)", got)
	}
}

func TestACollectionWithNothingTrackedReadsNothing(t *testing.T) {
	r := NewRegistry(&scripted{err: errors.New("must not be read")})
	if s := r.Collect(); s != nil {
		t.Fatalf("Collect = %+v, want nil", s)
	}
}

func TestAFailedSnapshotKeepsTheAccumulator(t *testing.T) {
	src := &scripted{snaps: [][]Proc{{proc(500, 10, 2, 0)}}}
	r := NewRegistry(src)
	r.Track(500, lab)
	cpu(t, r, lab)
	src.err = errors.New("proc unreadable")
	if got := cpu(t, r, lab); got != 2 {
		t.Fatalf("figure after a failed read = %v, want 2", got)
	}
}

func TestAnIdentityThatVanishesAndReturnsIsNotCountedTwice(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{proc(500, 10, 2, 0)},
		{}, // unreadable for one scan
		{proc(500, 10, 3, 0)},
	}}
	r := NewRegistry(src)
	r.Track(500, lab)
	cpu(t, r, lab)
	cpu(t, r, lab)
	if got := cpu(t, r, lab); got != 3 {
		t.Fatalf("figure = %v, want 3", got)
	}
}

func TestDepartedIdentitiesAreForgottenWithTheirGroup(t *testing.T) {
	src := &scripted{snaps: [][]Proc{{proc(500, 10, 2, 0)}}}
	r := NewRegistry(src)
	untrack := r.Track(500, lab)
	r.Collect()
	untrack()
	r.Collect()
	if n := len(r.seen); n != 0 {
		t.Fatalf("%d identities leaked after the group was untracked", n)
	}
}

// Three pids on the host, two in the tracked group: the sum is the two, so a
// reader that looks at the leader alone (2 s) or at the whole host (7 s) is wrong.
func TestAGroupOfThreePidsWithTwoTrackedSumsTheTwo(t *testing.T) {
	src := &scripted{snaps: [][]Proc{{
		{PID: 500, PGrp: 500, Start: 10, CPUTicks: 200},
		{PID: 501, PGrp: 500, Start: 11, CPUTicks: 300},
		{PID: 900, PGrp: 900, Start: 12, CPUTicks: 200},
	}}}
	r := NewRegistry(src)
	r.Track(500, lab)
	if got := cpu(t, r, lab); got != 5 {
		t.Fatalf("group figure = %v, want 5 (the leader and its child, not the stranger)", got)
	}
}

// Without /proc (a non-Linux build) a tracked group is never observed, and the
// instruments must have no points rather than zeros.
func TestANeverObservedLabelSetHasNoPoint(t *testing.T) {
	src := &scripted{snaps: [][]Proc{{}}} // nothing in the group's process group
	r := NewRegistry(src)
	r.Track(500, lab)
	if got := r.Collect(); len(got) != 0 {
		t.Fatalf("Collect = %+v, want no sample for a label set never observed", got)
	}
}

func TestTrackRefusesGroupZero(t *testing.T) {
	r := NewRegistry(&scripted{})
	for _, pgid := range []int{0, -1} {
		untrack := r.Track(pgid, lab)
		if g := r.Groups(); len(g) != 0 {
			t.Fatalf("Track(%d) registered %+v", pgid, g)
		}
		untrack()
	}
}

// A leader that spawns one short-lived child per collection: each child is a
// new identity seen once. The registry must not keep one per collection for
// as long as the group is tracked (round-3 nit 16), and the departed
// children's CPU must stay in the accumulator.
func TestShortLivedChildrenAreForgottenAfterTheGrace(t *testing.T) {
	const rounds = 1000
	snaps := make([][]Proc, rounds)
	for i := range snaps {
		snaps[i] = []Proc{proc(500, 10, 1, 0), proc(600+i, uint64(1000+i), 1, 0)}
	}
	r := NewRegistry(&scripted{snaps: snaps})
	r.Track(500, lab)
	var last float64
	for range rounds {
		last = cpu(t, r, lab)
	}
	if n := len(r.seen); n > forgetAfter+1 {
		t.Fatalf("%d identities held after %d collections, want at most %d: departed children are never forgotten", n, rounds, forgetAfter+1)
	}
	if want := float64(1 + rounds); last != want {
		t.Fatalf("figure = %v, want %v: a forgotten child's CPU left the accumulator", last, want)
	}
}

// An identity whose ticks go backwards (a /proc read racing a counter, never
// seen for one identity) adds nothing rather than wrapping a uint64.
func TestTicksGoingBackwardsAddNothing(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{proc(500, 10, 5, 0)},
		{proc(500, 10, 3, 0)},
	}}
	r := NewRegistry(src)
	r.Track(500, lab)
	cpu(t, r, lab)
	if got := cpu(t, r, lab); got != 5 {
		t.Fatalf("figure = %v, want 5: a backwards step must add zero", got)
	}
}

// absentFor returns n successful snapshots in which only the leader is listed.
func absentFor(n int) [][]Proc {
	out := make([][]Proc, n)
	for i := range out {
		out[i] = []Proc{proc(500, 10, 1, 0)}
	}
	return out
}

func child(secs int) Proc { return proc(501, 20, secs, 0) }

func collectAll(t *testing.T, src *scripted) *Registry {
	t.Helper()
	r := NewRegistry(src)
	r.Track(500, lab)
	for range len(src.snaps) - 1 {
		r.Collect()
	}
	return r
}

// The reviewer's round-4 probe, literally: a child with one CPU-hour absent
// from seven successful snapshots and back unchanged is counted once, and
// one absent from eight is forgotten. Together they pin the grace at eight.
func TestAnIdentityAbsentSevenTimesIsKeptAndEightTimesIsForgotten(t *testing.T) {
	snaps := [][]Proc{{proc(500, 10, 1, 0), child(hour)}}
	snaps = append(snaps, absentFor(7)...)
	snaps = append(snaps, []Proc{proc(500, 10, 1, 0), child(hour + 1)})
	src := &scripted{snaps: snaps}
	r := collectAll(t, src)
	if got := cpu(t, r, lab); got != 1+hour+1 {
		t.Fatalf("after 7 absences: figure = %v s, want %v: the child was forgotten and its hour counted again", got, 1+hour+1)
	}

	snaps = [][]Proc{{proc(500, 10, 1, 0), child(hour)}}
	snaps = append(snaps, absentFor(8)...)
	r = collectAll(t, &scripted{snaps: snaps})
	cpu(t, r, lab)
	if _, held := r.seen[identity{501, 20}]; held {
		t.Fatalf("after 8 absences the child is still held: the grace is longer than %d", forgetAfter)
	}
}

// A failed snapshot between absences ages nothing: seven absences, a failed
// read, then the child back unchanged is still counted once.
func TestAFailedSnapshotAgesNothing(t *testing.T) {
	snaps := [][]Proc{{proc(500, 10, 1, 0), child(hour)}}
	snaps = append(snaps, absentFor(7)...)
	src := &scripted{snaps: append(snaps, []Proc{proc(500, 10, 1, 0), child(hour)})}
	r := NewRegistry(src)
	r.Track(500, lab)
	for range 8 {
		r.Collect()
	}
	src.err = errors.New("proc unreadable")
	r.Collect()
	src.err = nil
	if got := cpu(t, r, lab); got != 1+hour {
		t.Fatalf("figure = %v s, want %v: a failed snapshot aged the child out", got, 1+hour)
	}
}

// Absences must be consecutive: seven, a reappearance, seven more and back
// again is fourteen in total but never eight in a row.
func TestAbsencesMustBeConsecutive(t *testing.T) {
	snaps := [][]Proc{{proc(500, 10, 1, 0), child(hour)}}
	snaps = append(snaps, absentFor(7)...)
	snaps = append(snaps, []Proc{proc(500, 10, 1, 0), child(hour)})
	snaps = append(snaps, absentFor(7)...)
	snaps = append(snaps, []Proc{proc(500, 10, 1, 0), child(hour)})
	r := collectAll(t, &scripted{snaps: snaps})
	if got := cpu(t, r, lab); got != 1+hour {
		t.Fatalf("figure = %v s, want %v: a reappearance did not reset the absence count", got, 1+hour)
	}
}

// A child that leaves its group (setpgid) for longer than the grace and
// rejoins still exists throughout, so its hour is counted once.
func TestAChildThatLeavesItsGroupAndRejoinsIsNotCountedTwice(t *testing.T) {
	away := proc(501, 20, hour, 0)
	away.PGrp = 900
	snaps := [][]Proc{{proc(500, 10, 1, 0), child(hour)}}
	for range 10 {
		snaps = append(snaps, []Proc{proc(500, 10, 1, 0), away})
	}
	snaps = append(snaps, []Proc{proc(500, 10, 1, 0), child(hour)})
	r := collectAll(t, &scripted{snaps: snaps})
	if got := cpu(t, r, lab); got != 1+hour {
		t.Fatalf("figure = %v s, want %v: a process outside its group aged out and was counted again on rejoining", got, 1+hour)
	}
}
