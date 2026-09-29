package session

import (
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// Silent implements channel.SilenceJudge: whether every client in clientIDs
// is the client of a silent session of c, and since when the last of them
// has been silent. An empty clientIDs is silent, with a zero since.
func (t *Table) Silent(c *channel.Channel, clientIDs []string) (since time.Time, ok bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.silentLocked(c, clientIDs, t.now())
}

// StopIfSilent implements channel.SilenceJudge: Silent's verdict, re-taken,
// and StopChannel's mark, in ONE critical section of t.mu. If the verdict
// holds, every ARRIVED, ACTIVE or DEPARTED session of c is marked STOPPED
// (their releases discarded, as StopChannel does) and the client entries they
// held come back with ok true. Otherwise nothing changes and ok is false.
func (t *Table) StopIfSilent(c *channel.Channel, clientIDs []string) ([]channel.StoppedClient, bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	now := t.now()
	if _, ok := t.silentLocked(c, clientIDs, now); !ok {
		return nil, false
	}
	return t.stopLocked(func(s *Session) bool { return s.Owner == Owner(c) }, now), true
}

// silentLocked is the predicate, over an Owner so the package's own tests
// drive it with a fake owner (the stopOwner idiom).
//
// Every id in clientIDs must be the client of a session of o that is silent:
// ACTIVE with nothing in flight and STRICTLY more than SilentAfter(TD) since
// its last request ended, or DEPARTED and still settling (its idle departure
// is in the middle of dropping the client). Anything else -- a request in
// flight, a session heard from recently, an ARRIVED entry, a DEPARTED session
// that is not settling (a resume between its attach and its commit), a
// STOPPED one, or an id no session of o holds (a TS or fMP4 client) -- is not
// silent, and answers (zero, false) at once.
func (t *Table) silentLocked(o Owner, clientIDs []string, now time.Time) (time.Time, bool) {
	if len(clientIDs) == 0 {
		return time.Time{}, true
	}
	want := make(map[string]bool, len(clientIDs))
	for _, id := range clientIDs {
		want[id] = false
	}
	var since time.Time
	for _, s := range t.byID {
		if s.Owner != o || s.client == nil {
			continue
		}
		if _, listed := want[s.client.ID]; !listed {
			continue
		}
		switch {
		case s.state == Active && s.inFlight == 0 && now.Sub(s.lastEnd) > SilentAfter(s.TD):
		case s.state == Departed && s.settling:
		default:
			return time.Time{}, false
		}
		want[s.client.ID] = true
		if at := s.lastEnd.Add(SilentAfter(s.TD)); at.After(since) {
			since = at
		}
	}
	for _, matched := range want {
		if !matched {
			return time.Time{}, false
		}
	}
	return since, true
}
