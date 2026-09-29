package channel

import (
	"sort"
	"time"
)

// SilenceJudge is the HLS session table as ReclaimFor sees it (Phase 4a-1c).
// Both methods take only the table's own mutex, and are called with m.mu held
// (and, for StopIfSilent, c.mu read-held): the lock order m.mu -> c.mu -> st.mu.
type SilenceJudge interface {
	Silent(c *Channel, clientIDs []string) (since time.Time, ok bool)
	StopIfSilent(c *Channel, clientIDs []string) ([]StoppedClient, bool)
}

// ReclaimCase is which of the spec's three cases a reclaim took.
type ReclaimCase int

// The cases are the spec's (a), (b) and (c); ReclaimDeclined is (b) whose
// re-check refused.
const (
	ReclaimNothing  ReclaimCase = iota // (c): nothing releasing, nothing reclaimable
	ReclaimWaited                      // (a): waited on a channel already releasing
	ReclaimStopped                     // (b): stopped a reclaimable channel, then waited
	ReclaimDeclined                    // (b): the pick's channel failed the re-check
)

// String names the case, for the tune's log line and a failing assertion.
func (r ReclaimCase) String() string {
	switch r {
	case ReclaimNothing:
		return "nothing"
	case ReclaimWaited:
		return "waited"
	case ReclaimStopped:
		return "stopped"
	case ReclaimDeclined:
		return "declined"
	}
	return "unknown"
}

// Reclaim is what ReclaimFor did, for the tune's log line and for tests.
type Reclaim struct {
	Case     ReclaimCase
	Channel  string // the channel waited on, stopped or declined; "" for nothing
	Released bool   // its released closed before the wait ended
}

// ReclaimFor is a blocked tune's one reclaim (spec § Slot reclaim, step 2).
// profileIDs are next-source's capacity.profile_ids. It returns within wait of
// its call, plus StopWait when the channel it stops does not stop in time.
// The caller retries next-source once whatever it returns.
//
// The wait is bounded in REAL time by one deadline taken on entry, never by
// m.now, which is the injectable test clock. Steps 1-4 run under one hold of
// m.mu; no lock is held while waiting, stopping a channel or calling the
// control plane.
func (m *Manager) ReclaimFor(profileIDs []int, wait time.Duration) Reclaim {
	deadline := time.Now().Add(wait)
	want := make(map[int]bool, len(profileIDs))
	for _, id := range profileIDs {
		want[id] = true
	}

	m.mu.Lock()
	start := m.now()

	// (a) A channel already releasing its slot: wait for it.
	if c := m.releasingCandidateLocked(want, start, wait); c != nil {
		m.mu.Unlock()
		return Reclaim{Case: ReclaimWaited, Channel: c.id, Released: waitReleased(c, deadline)}
	}

	// (b) The channel that has been reclaimable longest.
	var picked *Channel
	var pickedSince time.Time
	for _, id := range m.sortedIDsLocked() {
		c := m.channels[id]
		if c.ring.Closed() || !want[c.Source().M3UProfileID] {
			continue
		}
		since, ok := m.reclaimable(c)
		if !ok {
			continue
		}
		if picked == nil || since.Before(pickedSince) {
			picked, pickedSince = c, since
		}
	}
	if picked == nil {
		m.mu.Unlock()
		return Reclaim{Case: ReclaimNothing}
	}

	if m.cfg.ReclaimPicked != nil {
		m.cfg.ReclaimPicked(picked)
	}
	stopped, ok := m.reclaimLocked(picked)
	if !ok {
		m.mu.Unlock()
		return Reclaim{Case: ReclaimDeclined, Channel: picked.id}
	}
	m.removeLocked(picked, "reclaim")
	m.mu.Unlock()

	picked.dropHLSClients(stopped)
	picked.setState(StateStopping, nil)
	picked.stop(m.cfg.StopWait)
	released := waitReleased(picked, deadline)
	m.log.Info("reclaimed an unwatched channel for a blocked tune",
		"channel", picked.id, "m3u_profile", picked.Source().M3UProfileID)
	return Reclaim{Case: ReclaimStopped, Channel: picked.id, Released: released}
}

// releasingCandidateLocked is step (a)'s pick, with m.mu held: the oldest
// releasing channel on a wanted profile whose release has not landed, else the
// first channel in the map (by id) whose run ended by itself and has not
// released. A releasing entry older than StopWait + wait is dropped: its stop
// timed out and it may never release.
func (m *Manager) releasingCandidateLocked(want map[int]bool, start time.Time, wait time.Duration) *Channel {
	type entry struct {
		c  *Channel
		at time.Time
	}
	var fresh []entry
	for c, at := range m.releasing {
		if start.Sub(at) > m.cfg.StopWait+wait {
			delete(m.releasing, c)
			continue
		}
		if isReleased(c) || !want[c.Source().M3UProfileID] {
			continue
		}
		fresh = append(fresh, entry{c, at})
	}
	sort.Slice(fresh, func(i, j int) bool {
		if !fresh[i].at.Equal(fresh[j].at) {
			return fresh[i].at.Before(fresh[j].at)
		}
		return fresh[i].c.id < fresh[j].c.id
	})
	if len(fresh) > 0 {
		return fresh[0].c
	}
	for _, id := range m.sortedIDsLocked() {
		c := m.channels[id]
		if c.ring.Closed() && !isReleased(c) && want[c.Source().M3UProfileID] {
			return c
		}
	}
	return nil
}

func (m *Manager) sortedIDsLocked() []string {
	ids := make([]string, 0, len(m.channels))
	for id := range m.channels {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

// isReleased reports whether c's release has landed. A nil released, which a
// channel built without publish has, is never released.
func isReleased(c *Channel) bool {
	select {
	case <-c.released:
		return true
	default:
		return false
	}
}

// waitReleased waits for c's release until the real-time deadline, and
// reports whether it landed. A release that has already landed wins over an
// expired deadline: the two are never left to a select's random choice.
func waitReleased(c *Channel, deadline time.Time) bool {
	if isReleased(c) {
		return true
	}
	timer := time.NewTimer(time.Until(deadline))
	defer timer.Stop()
	select {
	case <-c.released:
		return true
	case <-timer.C:
		return isReleased(c)
	}
}

// reclaimable is the pick's verdict (spec D16), called with m.mu held. It
// takes c.mu and then the judge's lock one after the other, never nested.
//
// A channel with no client is reclaimable from when it went idle, unless a
// session of it is behind live and inside its grace (Phase 4a-3, ruling R82):
// the judge answers that for the empty list, and its answer is the channel's,
// lingering or in a channel_shutdown_delay countdown alike. A lingering
// channel with a TS or fMP4 client has a client, so it takes the branch below
// and is never reclaimed.
func (m *Manager) reclaimable(c *Channel) (since time.Time, ok bool) {
	ids, idleSince := c.clientState()
	if len(ids) == 0 {
		if m.cfg.Silence == nil {
			return idleSince, true
		}
		silentSince, ok := m.cfg.Silence.Silent(c, nil)
		if !ok {
			return time.Time{}, false
		}
		return later(idleSince, silentSince), true
	}
	if m.cfg.Silence == nil {
		return time.Time{}, false
	}
	return m.cfg.Silence.Silent(c, ids)
}

// reclaimLocked is the re-check and the mark (spec § Slot reclaim, (b) 3),
// called with m.mu held: c.mu read-held across the judge's own lock, so no
// client can join (addClient needs c.mu) and no request can begin (Begin
// needs st.mu) between the verdict and the STOPPED mark. Its judge call with
// an empty id list is what honours 4a-3's behind-live grace for a channel with
// no client, in step with reclaimable, so it needed no clause of its own.
func (m *Manager) reclaimLocked(c *Channel) ([]StoppedClient, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	ids := c.clientIDsLocked()
	if m.cfg.Silence == nil {
		return nil, len(ids) == 0
	}
	return m.cfg.Silence.StopIfSilent(c, ids)
}

// later is the later of two times.
func later(a, b time.Time) time.Time {
	if b.After(a) {
		return b
	}
	return a
}
