package channel

import "sort"

// Advance is an operator's switch: ChannelService.change_stream_url's owner
// branch (services/channel_service.py:483-520) over a source Django has
// already resolved, which is what POST /proxy/relay/channels/<id>/advance
// carries (apps/proxy/relay_serializers.py:187-222, "a fully-resolved
// source (ruling 11)").
//
// resetTried is the flag relay_views.py:236-239 applies before the switch:
// /proxy/ts/change_stream/ clears the running manager's tried_stream_ids so
// an operator's manual switch does not inherit a failover's exclusion list,
// and /proxy/ts/next_stream/ does not.
//
// The return is update_url's own (input/manager.py:1462-1540): false when
// the URL is the one already playing, true when the switch was applied. The
// caller -- not this method -- is what turns a false into change_stream_url's
// `success: true`, because that layer treats an unchanged URL as a metadata
// refresh rather than a failure (channel_service.py:487-490's own comment).
//
// Serialised by switchMu with failover(), so an operator's switch and a
// buffering-triggered one cannot interleave and leave the tried set
// describing neither.
func (c *Channel) Advance(resolved Resolved, resetTried bool) bool {
	c.switchMu.Lock()
	defer c.switchMu.Unlock()

	c.mu.Lock()
	if resetTried {
		c.tried = map[int]bool{}
	}
	current := c.source
	c.mu.Unlock()

	if resolved.Info.URL == current.URL {
		// update_url's first check (:1463-1465). Logged at INFO there, and
		// the URL is a credential, so only the channel is named here.
		c.log.Info("the operator switch named the URL already playing", "channel", c.id)
		return false
	}

	c.log.Info("switching stream", "channel", c.id, "trigger", "operator", "stream", resolved.Info.StreamID, "m3u_profile", resolved.Info.M3UProfileID)

	c.mu.Lock()
	if resolved.Info.StreamID != 0 {
		// update_url:1506-1510, inside the success path and after the URL
		// check -- the one place its bookkeeping differs from failover's.
		c.tried[resolved.Info.StreamID] = true
	}
	c.mu.Unlock()

	c.applySwitch(resolved)

	// The run loop adopts the parked source when the running attempt
	// returns, exactly as a buffering-triggered switch does
	// (failoverFromBuffering). Cancelling the attempt is what makes it
	// return: update_url closes the socket or the transcode process at the
	// same point (:1481-1486).
	c.mu.Lock()
	c.pending = &resolved
	cancel := c.cancelAttempt
	c.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	return true
}

// ExcludedStreamIDs is the tried set, sorted: exactly what a failover would
// send as exclude_stream_ids (failover's own NextRequest, input/manager.py:
// 2081-2087).
//
// Exported for one reason, stated so it is not mistaken for general-purpose
// state: the tried set is only externally observable as that list, so a test
// asserting that reset_tried cleared it has nothing else to read. Reading it
// through the same derivation the failover uses is what stops the assertion
// from being about a field nobody sends.
func (c *Channel) ExcludedStreamIDs() []int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := make([]int, 0, len(c.tried))
	for id := range c.tried {
		out = append(out, id)
	}
	sort.Ints(out)
	return out
}
