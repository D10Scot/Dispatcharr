package session

import (
	"slices"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
)

func TestSilentAfterIsTwoTargetDurations(t *testing.T) {
	if got := SilentAfter(2 * time.Second); got != 4*time.Second {
		t.Fatalf("SilentAfter(2 s) = %v, want 4 s", got)
	}
	if got := SilentAfter(6 * time.Second); got != 12*time.Second {
		t.Fatalf("SilentAfter(6 s) = %v, want 12 s", got)
	}
}

// silent runs the predicate the way the two exported wrappers do, under the
// table's lock, at the rig's clock.
func (r *rig) silent(o Owner, ids ...string) (time.Time, bool) {
	r.t.Helper()
	r.table.mu.Lock()
	defer r.table.mu.Unlock()
	return r.table.silentLocked(o, ids, r.clock.Now())
}

// The spec's predicate table (§ Slot reclaim, D16), one row per case, driven
// through silentLocked with a fake owner and the injected clock.
func TestSilence(t *testing.T) {
	const td = 2 * time.Second

	t.Run("1 no client ids is silent with a zero since", func(t *testing.T) {
		r := newRig(t)
		since, ok := r.silent(r.owner("c1"))
		if !ok || !since.IsZero() {
			t.Fatalf("silent(no ids) = %v, %v; want zero, true", since, ok)
		}
	})

	t.Run("2 an id with no session is not silent", func(t *testing.T) {
		r := newRig(t)
		if _, ok := r.silent(r.owner("c1"), "a-ts-client"); ok {
			t.Fatal("a client with no session was judged silent")
		}
	})

	t.Run("3 ended exactly 2 x TD ago is not silent, 4 ended 2 x TD + 1 s ago is", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.active(o, "a")
		lastEnd := r.clock.Now()
		r.clock.Advance(4 * time.Second)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("a session silent for exactly 2 x TD was judged silent; silent is STRICTLY more")
		}
		r.clock.Advance(1 * time.Second)
		since, ok := r.silent(o, "a")
		if !ok {
			t.Fatal("a session silent for 2 x TD + 1 s was judged not silent")
		}
		if want := lastEnd.Add(SilentAfter(s.TD)); !since.Equal(want) {
			t.Fatalf("since = %v, want lastEnd + 4 s = %v", since, want)
		}
	})

	t.Run("5 a reloading session is never silent", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.active(o, "a")
		for i := 0; i < 10; i++ {
			r.clock.Advance(time.Second)
			if l := r.table.Begin(s.ID); l.Outcome != Serve {
				t.Fatalf("Begin = %v, want Serve", l.Outcome)
			}
			r.table.End(s.ID)
			if _, ok := r.silent(o, "a"); ok {
				t.Fatalf("a session that reloaded every 1 s was judged silent after %d s", i+1)
			}
		}
	})

	t.Run("6 a request in flight for 60 s is not silent", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.active(o, "a")
		if l := r.table.Begin(s.ID); l.Outcome != Serve {
			t.Fatalf("Begin = %v, want Serve", l.Outcome)
		}
		r.clock.Advance(60 * time.Second)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("a session with a request in flight was judged silent")
		}
	})

	t.Run("7 an ARRIVED session is not silent at 60 s", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		r.add(o, "a", td)
		r.clock.Advance(60 * time.Second)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("an ARRIVED session was judged silent")
		}
	})

	t.Run("8 a DEPARTED session still settling is silent", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.active(o, "a")
		r.clock.Advance(IdleTimeout(s.TD))
		if d := r.table.Sweep(); len(d) != 1 {
			t.Fatalf("the sweep departed %d sessions, want 1", len(d))
		}
		if _, ok := r.silent(o, "a"); !ok {
			t.Fatal("a settling departure's client was judged not silent")
		}
	})

	t.Run("9 a DEPARTED session that is not settling is not silent", func(t *testing.T) {
		// A resume between its attach and its commit: the client id is
		// registered again while the session is DEPARTED and settled.
		r := newRig(t)
		o := r.owner("c1")
		s := r.active(o, "a")
		r.departIdle(s)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("a settled DEPARTED session's client id was judged silent")
		}
	})

	t.Run("10 one silent session and one reloading is not silent", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		r.active(o, "quiet")
		loud := r.active(o, "loud")
		for i := 0; i < 6; i++ {
			r.clock.Advance(time.Second)
			r.table.Begin(loud.ID)
			r.table.End(loud.ID)
		}
		if _, ok := r.silent(o, "quiet", "loud"); ok {
			t.Fatal("a channel with one reloading session was judged silent")
		}
		if _, ok := r.silent(o, "quiet"); !ok {
			t.Fatal("the quiet session alone was judged not silent")
		}
	})

	t.Run("11 the threshold scales with the target duration", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.add(o, "a", 6*time.Second)
		if !r.table.Activate(s.ID) {
			t.Fatal("Activate refused")
		}
		r.clock.Advance(11 * time.Second)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("at TD 6, 11 s of silence was judged silent")
		}
		r.clock.Advance(2 * time.Second)
		if _, ok := r.silent(o, "a"); !ok {
			t.Fatal("at TD 6, 13 s of silence was judged not silent")
		}
	})

	t.Run("12 another channel's session carrying a listed id does not match", func(t *testing.T) {
		r := newRig(t)
		mine, other := r.owner("mine"), r.owner("other")
		r.active(other, "a")
		r.clock.Advance(10 * time.Second)
		if _, ok := r.silent(mine, "a"); ok {
			t.Fatal("an id held only by another channel's session was matched")
		}
	})

	t.Run("13 two silent sessions report the later since", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		r.active(o, "first")
		r.clock.Advance(3 * time.Second)
		second := r.active(o, "second")
		secondEnd := r.clock.Now()
		r.clock.Advance(10 * time.Second)
		since, ok := r.silent(o, "first", "second")
		if !ok {
			t.Fatal("two silent sessions were judged not silent")
		}
		if want := secondEnd.Add(SilentAfter(second.TD)); !since.Equal(want) {
			t.Fatalf("since = %v, want the later session's %v", since, want)
		}
	})
}

// finding 3(a)(b): the exported wrappers, so this package's own tests reach
// them (the gate measures coverage per package). A *channel.Channel value is
// used only as an identity, the idiom the table's tests use for *hls.Pipeline.
func TestSilentAndInFlightThroughTheTablesOwnMethods(t *testing.T) {
	r := newRig(t)
	c := &channel.Channel{}
	s := r.active(c, "a")

	r.clock.Advance(3 * time.Second)
	if _, ok := r.table.Silent(c, []string{"a"}); ok {
		t.Fatal("Silent at 3 s = true, want false")
	}
	r.clock.Advance(2 * time.Second)
	if _, ok := r.table.Silent(c, []string{"a"}); !ok {
		t.Fatal("Silent at 5 s = false, want true")
	}

	if got := r.table.InFlight("no-such-sid"); got != 0 {
		t.Fatalf("InFlight(unknown) = %d, want 0", got)
	}
	if l := r.table.Begin(s.ID); l.Outcome != Serve {
		t.Fatalf("Begin = %v, want Serve", l.Outcome)
	}
	if got := r.table.InFlight(s.ID); got != 1 {
		t.Fatalf("InFlight during a request = %d, want 1", got)
	}
	r.table.End(s.ID)
	if got := r.table.InFlight(s.ID); got != 0 {
		t.Fatalf("InFlight after End = %d, want 0", got)
	}
}

func TestStopIfSilentMarksOnlyWhenStillSilent(t *testing.T) {
	r := newRig(t)
	c, other := &channel.Channel{}, &channel.Channel{}

	// The DEPARTED session goes first: the sweep ages every session that
	// exists then. Its departure is not run (the zero Channel cannot emit),
	// so it stays DEPARTED and settling, a session StopChannel also marks.
	departed := r.active(c, "departed")
	r.clock.Advance(IdleTimeout(departed.TD))
	if d := r.table.Sweep(); len(d) != 1 {
		t.Fatalf("the sweep departed %d sessions, want 1", len(d))
	}
	quiet := r.active(c, "quiet")
	bystander := r.active(other, "bystander")
	r.clock.Advance(5 * time.Second)

	stopped, ok := r.table.StopIfSilent(c, []string{"quiet"})
	if !ok {
		t.Fatal("StopIfSilent refused a silent channel")
	}
	want := []channel.StoppedClient{{ClientID: "quiet", Connected: true}}
	if !slices.Equal(stopped, want) {
		t.Fatalf("StopIfSilent returned %+v, want %+v", stopped, want)
	}
	for _, s := range []*Session{quiet, departed} {
		if l := r.table.Begin(s.ID); l.Outcome != Gone {
			t.Fatalf("Begin on a reclaimed channel's session = %v, want Gone", l.Outcome)
		}
	}
	if l := r.table.Begin(bystander.ID); l.Outcome != Serve {
		t.Fatalf("another channel's session = %v, want Serve (untouched)", l.Outcome)
	}
}

func TestStopIfSilentLeavesANonSilentChannelAlone(t *testing.T) {
	r := newRig(t)
	c := &channel.Channel{}
	loud := r.active(c, "loud")
	r.clock.Advance(3 * time.Second)
	if l := r.table.Begin(loud.ID); l.Outcome != Serve {
		t.Fatalf("Begin = %v, want Serve", l.Outcome)
	}
	// A request in flight: not silent.
	stopped, ok := r.table.StopIfSilent(c, []string{"loud"})
	if ok || stopped != nil {
		t.Fatalf("StopIfSilent = %+v, %v; want nil, false", stopped, ok)
	}
	r.table.mu.Lock()
	defer r.table.mu.Unlock()
	if loud.state != Active || !loud.stoppedAt.IsZero() || loud.releases == nil {
		t.Fatalf("the refused stop changed the session: state=%v stoppedAt=%v releases=%v", loud.state, loud.stoppedAt, loud.releases)
	}
}

// behindLive activates a session of o whose latest served segment was far
// behind the newest, with the given grace.
func (r *rig) behindLive(o Owner, clientID string, grace time.Duration) *Session {
	r.t.Helper()
	s := r.add(o, clientID, 2*time.Second)
	s.Grace = grace
	if !r.table.Activate(s.ID) {
		r.t.Fatalf("Activate(%s) refused", clientID)
	}
	r.table.NoteSegment(s.ID, time.Minute)
	return s
}

// Row ⟨F⟩ (spec D15, D16; R82): a behind-live session's silence point is its
// last request's end plus 2 x TD plus the grace.
func TestTheBehindLiveGrace(t *testing.T) {
	const grace = 10 * time.Second

	t.Run("1 to 3 an ACTIVE behind-live session is silent strictly after 14 s", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		r.behindLive(o, "a", grace)
		lastEnd := r.clock.Now()
		r.clock.Advance(5 * time.Second)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("(1) a behind-live session silent for 5 s was judged silent")
		}
		r.clock.Advance(9 * time.Second)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("(2) a behind-live session silent for exactly 14 s was judged silent; silent is STRICTLY more")
		}
		r.clock.Advance(time.Millisecond)
		since, ok := r.silent(o, "a")
		if !ok {
			t.Fatal("(3) a behind-live session silent for 14.001 s was judged not silent")
		}
		if want := lastEnd.Add(14 * time.Second); !since.Equal(want) {
			t.Fatalf("(3) since = %v, want lastEnd + 14 s = %v", since, want)
		}
	})

	t.Run("4 a settling departure with its client listed waits out the grace", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.behindLive(o, "a", grace)
		r.clock.Advance(IdleTimeout(s.TD))
		if d := r.table.Sweep(); len(d) != 1 {
			t.Fatalf("the sweep departed %d sessions, want 1", len(d))
		}
		r.clock.Advance(500 * time.Millisecond)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("a behind-live departure settling at 12.5 s was judged silent inside its grace")
		}
	})

	t.Run("5 a settled departure holds an empty-list verdict until its silence point", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.behindLive(o, "a", grace)
		lastEnd := r.clock.Now()
		r.departIdle(s)
		r.clock.Advance(time.Second) // 13 s
		if _, ok := r.silent(o); ok {
			t.Fatal("an empty list at 13 s was judged silent while a behind-live departure was inside its grace")
		}
		r.clock.Advance(2 * time.Second) // 15 s
		since, ok := r.silent(o)
		if !ok {
			t.Fatal("an empty list at 15 s was judged not silent past the grace")
		}
		if want := lastEnd.Add(14 * time.Second); !since.Equal(want) {
			t.Fatalf("since = %v, want lastEnd + 14 s = %v", since, want)
		}
	})

	t.Run("6 with no grace a behind-live session is silent at 4a-1c's 4 s", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		r.behindLive(o, "a", 0)
		r.clock.Advance(4 * time.Second)
		if _, ok := r.silent(o, "a"); ok {
			t.Fatal("silent at exactly 4 s")
		}
		r.clock.Advance(time.Millisecond)
		if _, ok := r.silent(o, "a"); !ok {
			t.Fatal("a zero-grace behind-live session was not silent past 4 s")
		}
	})

	t.Run("7 a session that is not behind live has no grace", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		s := r.add(o, "a", 2*time.Second)
		s.Grace = grace
		r.table.Activate(s.ID)
		r.table.NoteSegment(s.ID, 10*time.Second) // exactly 5 x TD: not behind
		r.clock.Advance(5 * time.Second)
		if _, ok := r.silent(o, "a"); !ok {
			t.Fatal("a session at the live edge kept a grace")
		}
	})

	t.Run("8 two departures, one inside its grace, are not silent", func(t *testing.T) {
		r := newRig(t)
		o := r.owner("c1")
		early := r.behindLive(o, "early", grace)
		r.clock.Advance(3 * time.Second)
		r.behindLive(o, "late", grace)
		r.clock.Advance(IdleTimeout(early.TD) - 3*time.Second) // early idles out
		departures := r.table.Sweep()
		if len(departures) != 1 {
			t.Fatalf("the sweep departed %d sessions, want 1 (the early one)", len(departures))
		}
		departures[0].Run()
		r.clock.Advance(3 * time.Second)
		departures = r.table.Sweep()
		if len(departures) != 1 {
			t.Fatalf("the sweep departed %d sessions, want the late one", len(departures))
		}
		departures[0].Run()
		// early is 15 s past its last request, past its silence point at 14 s; late is 12 s
		// past its own, inside its silence point at 17 s
		if _, ok := r.silent(o); ok {
			t.Fatal("an empty list was judged silent with one departure inside its grace")
		}
		r.clock.Advance(3 * time.Second)
		if _, ok := r.silent(o); !ok {
			t.Fatal("an empty list was not silent once both departures were past their graces")
		}
	})

	t.Run("9 another channel's behind-live departure is ignored", func(t *testing.T) {
		r := newRig(t)
		mine, other := r.owner("mine"), r.owner("other")
		s := r.behindLive(other, "a", grace)
		r.departIdle(s)
		if _, ok := r.silent(mine); !ok {
			t.Fatal("another channel's grace held this channel")
		}
	})
}

func TestStopIfSilentHonoursTheGrace(t *testing.T) {
	r := newRig(t)
	c := &channel.Channel{}
	s := r.behindLive(c, "a", 10*time.Second)
	// Departed and settling: the zero Channel cannot emit, so it is not run.
	r.clock.Advance(IdleTimeout(s.TD))
	if d := r.table.Sweep(); len(d) != 1 {
		t.Fatalf("the sweep departed %d sessions, want 1", len(d))
	}
	if stopped, ok := r.table.StopIfSilent(c, nil); ok || stopped != nil {
		t.Fatalf("StopIfSilent inside the grace = %+v, %v; want nil, false", stopped, ok)
	}
	if l := r.table.Begin(s.ID); l.Outcome != Busy {
		t.Fatalf("the refused stop marked the session: Begin = %v, want Busy (still settling)", l.Outcome)
	}
	r.clock.Advance(3 * time.Second) // 15 s, past lastEnd + 14 s
	if _, ok := r.table.StopIfSilent(c, nil); !ok {
		t.Fatal("StopIfSilent past the grace refused")
	}
	if l := r.table.Begin(s.ID); l.Outcome != Gone {
		t.Fatalf("Begin after the stop = %v, want Gone", l.Outcome)
	}
}
