package channel

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// Resolver is how a channel asks for its next source: the port of
// _try_next_stream's control-plane half (input/manager.py:2041-2131) behind
// one method, so this package never imports the wire package. httpapi
// implements it over control.Client, and it is where the degraded fallback
// lives -- the candidate list cached at channel start, consulted only when
// the control plane is unreachable -- because that list is wire-shaped and
// the decision "the control plane refused, never degrade" is a distinction
// only the wire client can make (spec § Error handling per hop).
//
// ONE PER CHANNEL, built by the tune that started it, because the cache it
// holds is that tune's answer.
type Resolver interface {
	// Next asks for the next source, excluding the stream ids already tried.
	// It returns ErrNoAlternate when nothing is left -- a null source from
	// Django, or an empty cache during an outage -- and any other error for
	// a refusal or a transport failure the fallback could not cover. A
	// Resolved whose Degraded flag is set came from the cache, unenforced.
	Next(ctx context.Context, req NextRequest) (Resolved, error)
}

// NextRequest is what _try_next_stream sends (input/manager.py:2081-2087):
// the tried set plus the current stream, sorted, and the URL and id being
// failed over FROM, so Django's traversal starts after it and never answers
// with the URL already playing.
type NextRequest struct {
	Exclude         []int
	CurrentURL      string
	CurrentStreamID int
}

// Resolved is a next source ready to run.
type Resolved struct {
	Source   Source
	Info     SourceInfo
	Degraded bool

	// OutputProfiles is the active set the SAME next-source answer carried
	// (2c-7). Zero -- Known false -- for a degraded resolution, which came
	// from the candidate list cached at channel start and has no answer of
	// its own, and the channel's existing set is then kept rather than
	// cleared.
	OutputProfiles OutputProfiles
}

// ErrNoAlternate is "No alternate stream available" (input/manager.py:2110).
var ErrNoAlternate = errors.New("channel: no alternate stream available")

// ErrSourcesExhausted is the error a channel ends in once every candidate has
// failed: run()'s finally block (input/manager.py:678-682), which writes
// "All N stream options failed" when any stream id was ever tried and
// "Connection failed after N attempts" otherwise. Last is the error the
// final attempt ended with, so errors.Is and errors.As still see the
// mechanism -- an ErrExited, an ErrUpstreamStatus, ErrInputFailed.
type ErrSourcesExhausted struct {
	Tried    int
	Attempts int
	Last     error
}

// Message is the text Python writes into the metadata hash's error_message,
// which a client waiting for its first byte receives in an error TS packet
// (output/ts/generator.py:229, utils.py:71-98).
func (e *ErrSourcesExhausted) Message() string {
	if e.Tried > 0 {
		return fmt.Sprintf("All %d stream options failed", e.Tried)
	}
	return fmt.Sprintf("Connection failed after %d attempts", e.Attempts)
}

func (e *ErrSourcesExhausted) Error() string {
	if e.Last != nil {
		return "channel: " + e.Message() + ": " + redact.Error(e.Last).Error()
	}
	return "channel: " + e.Message()
}

func (e *ErrSourcesExhausted) Unwrap() error { return e.Last }

// errUpstreamEnded stands in for a nil Run result in the failure accounting:
// a clean upstream EOF is "Server closed connection" (input/manager.py:
// 1868-1872), a connection failure like any other, retried and counted.
var errUpstreamEnded = errors.New("channel: the upstream ended the connection")

// The bare literals of the retry loop and the health monitor, none of which
// a setting supplies. Each is pinned by TestTheFailoverLiteralsMatchPython.
const (
	// retryBackoffStep and retryBackoffCap: `min(.25 * failures, 3)` at
	// input/manager.py:557 and :588.
	retryBackoffStep = 250 * time.Millisecond
	retryBackoffCap  = 3 * time.Second

	// maxUnhealthyChecks is the health monitor's `max_unhealthy_checks = 3`
	// (input/manager.py:1556): the number of consecutive checks that must
	// find the stream inactive before it acts (parity-matrix row 2).
	maxUnhealthyChecks = 3

	// healthActionCooldown is `action_cooldown = 30` (input/manager.py:1557).
	healthActionCooldown = 30 * time.Second

	// stableReconnectAfter is the bare `stable_time >= 30` at
	// input/manager.py:1580: a stream that was stable this long is
	// reconnected in place before it is switched. apps/proxy/config.py:119
	// names MIN_STABLE_TIME_BEFORE_RECONNECT = 30 for it and nothing reads
	// that (CLAUDE.md § Known defects, dead or unwired), so it is a literal
	// here as it is there.
	stableReconnectAfter = 30 * time.Second
)

// retryBackoff is the wait before the next attempt on the same URL.
func retryBackoff(failures int) time.Duration {
	return min(time.Duration(failures)*retryBackoffStep, retryBackoffCap)
}

// healthAction is the health monitor's decision once the checks have run
// out (input/manager.py:1576-1590): reconnect in place if the stream had
// been stable, switch streams otherwise.
type healthAction int

const (
	actionSwitch healthAction = iota
	actionReconnect
)

func healthActionFor(stableFor time.Duration) healthAction {
	if stableFor >= stableReconnectAfter {
		return actionReconnect
	}
	return actionSwitch
}

// failureCounter is _record_connection_failure and its two neighbours
// (input/manager.py:183-197): a count that resets when the gap since the
// last failure exceeds the window, so three failures at t=0, 1700 and 3400
// trip a 1800-second window even though the span is 3400 (parity-matrix
// row 3's Notes).
type failureCounter struct {
	window time.Duration
	now    func() time.Time

	count int
	last  time.Time
}

func (f *failureCounter) record() int {
	now := f.now()
	if !f.last.IsZero() && now.Sub(f.last) > f.window {
		f.count = 0
	}
	f.last = now
	f.count++
	return f.count
}

func (f *failureCounter) clear() {
	f.count = 0
	f.last = time.Time{}
}

// failover is _try_next_stream (input/manager.py:2041-2225) minus the
// control-plane call, which is the resolver's. It records the candidate as
// tried, refuses the URL already playing (update_url's own first check,
// :1464-1466), resets the packetiser (:1515-1520, never the chunk index --
// row 7), swaps the source info, clears the failure history (:1512) and
// raises stream_switch (:1523-1532); then the degraded bookkeeping of
// :2191-2202. url_switching (set at :1476-1477, cleared at :1540) is not carried:
// its one reader, _is_timeout's exemption, is not ported (Ruling R14). It does NOT stop the running attempt -- the caller does,
// because the two callers stop it differently: the run loop has already
// seen it end, and the stderr reader cancels it after adopting the result.
//
// Serialised by switchMu, because the stderr reader and the run loop can
// both reach it, and a second switch racing the first would exclude the
// wrong stream id.
func (c *Channel) failover(ctx context.Context, why string) (Resolved, bool) {
	c.switchMu.Lock()
	defer c.switchMu.Unlock()

	if c.resolver == nil {
		c.log.Error("no alternate stream available: this channel has no resolver", "channel", c.id, "trigger", why)
		return Resolved{}, false
	}

	c.mu.RLock()
	current := c.source
	exclude := make([]int, 0, len(c.tried)+1)
	for id := range c.tried {
		exclude = append(exclude, id)
	}
	if c.currentStreamID != 0 && !c.tried[c.currentStreamID] {
		exclude = append(exclude, c.currentStreamID)
	}
	c.mu.RUnlock()
	sort.Ints(exclude)

	resolved, err := c.resolver.Next(ctx, NextRequest{Exclude: exclude, CurrentURL: current.URL, CurrentStreamID: c.currentStreamID})
	if err != nil {
		if errors.Is(err, ErrNoAlternate) {
			c.log.Error("no alternate stream available", "channel", c.id, "trigger", why)
		} else {
			c.log.Error("the failover could not be resolved", "channel", c.id, "trigger", why, "error", redact.Error(err))
		}
		return Resolved{}, false
	}

	c.mu.Lock()
	c.tried[resolved.Info.StreamID] = true
	c.mu.Unlock()

	if resolved.Info.URL == current.URL {
		// update_url returns False on the URL already playing, and
		// _try_next_stream reports the failover failed (:2143-2153).
		c.log.Error("the failover named the URL already playing", "channel", c.id, "stream", resolved.Info.StreamID)
		return Resolved{}, false
	}

	c.log.Info("switching stream", "channel", c.id, "trigger", why, "stream", resolved.Info.StreamID, "m3u_profile", resolved.Info.M3UProfileID)
	c.mu.Lock()
	c.ring.ResetPosition()
	c.source = resolved.Info
	c.currentStreamID = resolved.Info.StreamID
	c.failures.clear()
	// The Output Profile set travels on every next-source answer, so a
	// failover that reached Django refreshes it and a DEGRADED one -- which
	// never called Django -- leaves the channel-start copy in place (2c-7's
	// Ruling R5). Under the same Lock as the rest of the switch, so a client
	// attaching mid-switch reads one state or the other and never half of
	// each.
	if resolved.OutputProfiles.Known {
		c.outputProfiles = resolved.OutputProfiles
	}
	c.mu.Unlock()

	// stream_switch (:1523-1532): the URL through redact_url and cut at 100
	// characters there; through redact.Line here, which keeps less --
	// scheme and host only -- and the same cut.
	c.emit("stream_switch", map[string]any{
		"new_url":   truncate(redact.Line(resolved.Info.URL), 100),
		"stream_id": resolved.Info.StreamID,
	})

	c.mu.Lock()
	degradedBefore := c.failoverDegraded
	c.failoverDegraded = resolved.Degraded
	c.mu.Unlock()
	if !resolved.Degraded && degradedBefore {
		// Django is answering again: say, once, that an earlier failover ran
		// blind on the cached list and may have exceeded max_streams
		// (:2191-2202).
		c.emit("channel_error", map[string]any{"reason": "degraded_failover"})
	}
	return resolved, true
}

// failoverFromBuffering is the stderr reader's entry: _parse_ffmpeg_stats'
// buffering-timeout branch (input/manager.py:1178-1211, parity-matrix row
// 1), which calls _try_next_stream from the reader thread and, on success,
// clears the buffering state and raises channel_failover. It never touches
// the main loop's switch counter, which is row 6.
//
// The new source is parked for the run loop and the running attempt is
// cancelled; Run returns to the loop once this reader has returned, because
// TranscodeSource.Run waits for its stderr reader before it returns, exactly
// as Python's update_url kills the process the reader was reading.
func (c *Channel) failoverFromBuffering(bufferingFor time.Duration) bool {
	ctx := c.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	resolved, ok := c.failover(ctx, "buffering_timeout")
	if !ok {
		return false
	}
	c.mu.Lock()
	c.pending = &resolved
	cancel := c.cancelAttempt
	c.mu.Unlock()
	// :1190-1197's hset ACTIVE after the switch, through the guarded
	// recovery edge -- the one existing writer of StateActive beside
	// promoteOnFirstChunk, not a third.
	c.reportBuffering(false)
	c.emit("channel_failover", map[string]any{
		"reason":   "buffering_timeout",
		"duration": bufferingFor.Seconds(),
	})
	if cancel != nil {
		cancel()
	}
	return true
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
