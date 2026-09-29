package channel

import (
	"sort"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/hls"
)

// hlsKey is the built-in transcode's key in the HLS map, and the key of a
// channel with no HLS profile. A channel with one runs its pipeline under
// "hls:p<id>" (HLSProfile.Key), so "one ffmpeg per (channel, HLS profile)".
const hlsKey = "hls"

// HLSProfile is the channel's HLS Output Profile as the control plane last
// described it (Phase 4a-1d, spec D12): the same three-state shape as
// OutputProfiles.Known. Known false is an answer that carried no hls_profile
// key at all, a contract mismatch an HLS entry answers 502 for; Known true
// with ID 0 is "no HLS profile" (JSON null), the built-in re-encode.
type HLSProfile struct {
	Known bool
	ID    int
	Mode  string
}

// Key is the profile's pipeline key: "hls" with no profile, "hls:p<id>"
// otherwise.
func (h HLSProfile) Key() string {
	if h.ID == 0 {
		return hlsKey
	}
	return hlsKey + ":p" + strconv.Itoa(h.ID)
}

// hlsEntry is one running HLS pipeline and how many sessions hold it.
type hlsEntry struct {
	pipeline *hls.Pipeline
	refs     int
}

// lingerState is a channel's one lingering HLS pipeline (spec D15): the last
// session of a pipeline ended, and the pipeline keeps encoding, holding the
// channel, so a zap back keeps the rewind window.
type lingerState struct {
	key      string
	pipeline *hls.Pipeline
	// since is when the last session ended.
	since time.Time
	// stop cancels the linger's timer.
	stop func() bool
}

// hlsRegistry is the HLS half of the output registry: its own map, typed
// *hls.Pipeline, under the same outMu as outputs -- outputEntry.pipeline is an
// *output.Pipeline and stays so. It is embedded in outputRegistry, so its
// fields are read and written only under outMu.
type hlsRegistry struct {
	hls map[string]*hlsEntry
	// hlsFailed is the channel's mark, hlsFailedUntilBoundary (spec
	// § Encoder argv, failure), recording its REASON: hls.ErrNoVideo or
	// hls.ErrFailed. It is the channel's and never a pipeline's, so a fresh
	// pipeline cannot inherit a dead one's state; the next real source
	// boundary clears it and starts nothing.
	hlsFailed error
	// linger is the channel's one lingering HLS pipeline (Phase 4a-3, spec
	// D15), or nil. It is WRITTEN only under outMu and READ anywhere without a
	// lock, so reading it under m.mu or c.mu adds no lock-order edge.
	linger atomic.Pointer[lingerState]
	// outputsStopped is set by stopOutputs in the same critical section that
	// clears the maps, and both HLS attaches refuse once it is set. The ring's
	// closing is not the test: stopOutputs runs BEFORE the ring closes.
	outputsStopped bool
}

// ErrHLSOutputFailed is an HLS attach refused because the channel's mark is
// set. Reason is hls.ErrNoVideo or hls.ErrFailed, which the entry's 502 body
// follows.
type ErrHLSOutputFailed struct{ Reason error }

func (e ErrHLSOutputFailed) Error() string {
	if e.Reason == nil {
		return "channel: the HLS output failed"
	}
	return "channel: the HLS output failed: " + e.Reason.Error()
}

// Unwrap is the reason, so errors.Is(err, hls.ErrNoVideo) answers.
func (e ErrHLSOutputFailed) Unwrap() error { return e.Reason }

// AttachHLS returns the channel's HLS pipeline for key, starting one with
// start if none is registered, and registers the caller against it: the HLS
// counterpart of AttachOutput, with a refcount of its own.
//
// ErrHLSOutputFailed while the mark is set; ErrChannelEnding once stopOutputs
// has run. started reports that this call started the pipeline, so the caller
// starts its failure watcher. start runs under outMu and must not block
// (hls.Start returns at once, spec D9).
//
// The release func is IDENTITY-SAFE: it decrements only while the registered
// entry is the pipeline it attached to, so a stale release after a failure can
// never stop a fresh pipeline. At zero it unregisters the pipeline and stops
// it on a goroutine of its own -- Stop can wait stopJoinWait, and nothing a
// zapping viewer needs depends on it. A channel stop still stops its pipelines
// synchronously, in stopOutputs.
func (c *Channel) AttachHLS(key string, start func(src hls.Source) (*hls.Pipeline, error)) (p *hls.Pipeline, started bool, release func(), err error) {
	c.outMu.Lock()
	defer c.outMu.Unlock()
	if c.outputsStopped {
		return nil, false, nil, ErrChannelEnding
	}
	if c.hlsFailed != nil {
		return nil, false, nil, &ErrHLSOutputFailed{Reason: c.hlsFailed}
	}
	if entry, running := c.hls[key]; running {
		entry.refs++
		c.endLingerLocked(entry.pipeline)
		return entry.pipeline, false, c.hlsRelease(key, entry.pipeline), nil
	}
	p, err = start(c)
	if err != nil {
		return nil, false, nil, err
	}
	if c.hls == nil {
		c.hls = map[string]*hlsEntry{}
	}
	c.hls[key] = &hlsEntry{pipeline: p, refs: 1}
	return p, true, c.hlsRelease(key, p), nil
}

// AttachHLSExisting re-attaches a resume to p only while p is key's registered
// pipeline, has not ended, and the channel's outputs have not been stopped
// (R49): a channel can outlive its HLS pipeline, and a fresh pipeline would
// restart the media sequence under the same playlist URL.
func (c *Channel) AttachHLSExisting(key string, p *hls.Pipeline) (release func(), ok bool) {
	c.outMu.Lock()
	defer c.outMu.Unlock()
	if c.outputsStopped {
		return nil, false
	}
	entry, running := c.hls[key]
	if !running || entry.pipeline != p {
		return nil, false
	}
	select {
	case <-p.Done():
		return nil, false
	default:
	}
	entry.refs++
	c.endLingerLocked(p)
	return c.hlsRelease(key, p), true
}

// hlsRelease is the release func for one attachment to p. At zero sessions the
// pipeline lingers when it is eligible (lingerEligible), and otherwise stops.
func (c *Channel) hlsRelease(key string, p *hls.Pipeline) func() {
	return sync.OnceFunc(func() {
		var stopping *hls.Pipeline
		var lingering *lingerState
		c.outMu.Lock()
		if entry, running := c.hls[key]; running && entry.pipeline == p {
			entry.refs--
			if entry.refs <= 0 {
				if c.lingerEligibleLocked(p) {
					lingering = c.startLingerLocked(key, p)
				} else {
					delete(c.hls, key)
					stopping = p
				}
			}
		}
		c.outMu.Unlock()
		if lingering != nil {
			c.log.Info("the last HLS session ended; the channel lingers for its rewind window",
				"channel", c.id, "key", key, "linger", c.tuning.RewindLinger)
		}
		if stopping != nil {
			c.log.Info("no HLS sessions remain, stopping the HLS output", "channel", c.id, "key", key)
			go stopping.Stop()
		}
	})
}

// lingerEligibleLocked is whether a pipeline whose last session just ended
// lingers (Decision 12): the rewind window and the linger are both on, the
// pipeline is ready and has not ended, the channel's outputs are not stopped and
// no other pipeline of the channel lingers already. So a leave, an admin client
// stop or stream-limit termination and an idle departure all linger, while a
// pipeline whose sessions went STOPPED (their releases are discarded) and one
// that never served its multivariant never do. Called with outMu held.
func (c *Channel) lingerEligibleLocked(p *hls.Pipeline) bool {
	if c.tuning.RewindWindow <= 0 || c.tuning.RewindLinger <= 0 || c.outputsStopped || c.linger.Load() != nil {
		return false
	}
	select {
	case <-p.Done():
		return false
	default:
	}
	return p.IsReady()
}

// startLingerLocked keeps p registered with no session and arms the linger's
// timer. Called with outMu held.
func (c *Channel) startLingerLocked(key string, p *hls.Pipeline) *lingerState {
	ls := &lingerState{key: key, pipeline: p, since: c.now()}
	ls.stop = c.schedule(c.tuning.RewindLinger, func() { c.endLinger(ls) })
	c.linger.Store(ls)
	p.SetLingering(true)
	return ls
}

// endLingerLocked ends a linger on p because a session attached to it (or the
// pipeline is going): the timer is stopped and the hold released. Called with
// outMu held; a no-op when p is not the lingering pipeline.
func (c *Channel) endLingerLocked(p *hls.Pipeline) {
	ls := c.linger.Load()
	if ls == nil || ls.pipeline != p {
		return
	}
	ls.stop()
	c.linger.Store(nil)
	p.SetLingering(false)
	c.log.Info("an HLS session arrived; the linger ends", "channel", c.id, "key", ls.key)
}

// endLinger is the linger timer's own end: the pipeline stops and the manager
// is asked its idle question, off every lock. A linger that already ended
// (a new session, a failure, the channel's stop) finds itself no longer the
// channel's and does nothing.
func (c *Channel) endLinger(ls *lingerState) {
	var stopping *hls.Pipeline
	c.outMu.Lock()
	if c.linger.Load() != ls {
		c.outMu.Unlock()
		return
	}
	c.linger.Store(nil)
	ls.pipeline.SetLingering(false)
	if entry, running := c.hls[ls.key]; running && entry.pipeline == ls.pipeline && entry.refs == 0 {
		delete(c.hls, ls.key)
		stopping = ls.pipeline
	}
	c.outMu.Unlock()
	c.log.Info("the linger ended", "channel", c.id, "key", ls.key)
	if stopping != nil {
		go stopping.Stop()
	}
	if c.onIdle != nil {
		c.onIdle(c)
	}
}

// Lingering is when the channel's HLS pipeline began lingering, and whether it
// is.
func (c *Channel) Lingering() (since time.Time, ok bool) {
	if ls := c.linger.Load(); ls != nil {
		return ls.since, true
	}
	return time.Time{}, false
}

// lingerHeld is whether the channel is held by a linger: the hold the
// manager's idle decision honours before any channel_shutdown_delay countdown
// starts. It is not a client, and no client count or list includes it.
func (c *Channel) lingerHeld() bool { return c.linger.Load() != nil }

// schedule runs f after d: through the manager's injectable AfterFunc, or
// time.AfterFunc for a channel built without one. stop cancels it.
func (c *Channel) schedule(d time.Duration, f func()) (stop func() bool) {
	if c.afterFunc != nil {
		return c.afterFunc(d, f)
	}
	return time.AfterFunc(d, f).Stop
}

// FailHLS marks the channel (err non-nil) and unregisters p, but ONLY while p
// is still key's registered pipeline. Idempotent and identity-safe: the entry
// that saw Ready fail and the watcher that saw Done close may both call it for
// one failure, and the second finds p already gone and does nothing. That
// identity gate is what keeps a LATE call harmless -- the watcher's lands
// after finish, the store's close and any background work, seconds later on
// the Quick Sync fallback path, by which time the next source boundary may
// have cleared the mark and a fresh pipeline may be serving; a stale call must
// not re-mark the channel under it. It never stops p: a pipeline that failed
// is finishing on its own.
func (c *Channel) FailHLS(key string, p *hls.Pipeline, err error) {
	c.outMu.Lock()
	defer c.outMu.Unlock()
	if entry, running := c.hls[key]; running && entry.pipeline == p {
		delete(c.hls, key)
		c.endLingerQuietLocked(p)
		if err != nil {
			c.hlsFailed = err
		}
	}
}

// endLingerQuietLocked ends a linger on p that is going away, with no log line
// of a session's arrival. Called with outMu held.
func (c *Channel) endLingerQuietLocked(p *hls.Pipeline) {
	if ls := c.linger.Load(); ls != nil && ls.pipeline == p {
		ls.stop()
		c.linger.Store(nil)
	}
}

// HLSFailed is the mark's reason, or nil.
func (c *Channel) HLSFailed() error {
	c.outMu.Lock()
	defer c.outMu.Unlock()
	return c.hlsFailed
}

// clearHLSFailed is the next real source boundary's whole effect on the mark.
func (c *Channel) clearHLSFailed() {
	c.outMu.Lock()
	c.hlsFailed = nil
	c.outMu.Unlock()
}

// HLSStatus is a registered pipeline's encoder engine and generation, for the
// payload's hls_encoder and hls_generation. It reports the pipeline registered
// under the channel's current key, else the one with the lowest key, so the
// payload's two fields stay one value each while a profile change drains an
// older pipeline. ok is false with no pipeline; the engine is empty until the
// first generation has chosen one.
//
// The key is read through HLSProfile (c.mu) BEFORE outMu is taken, never with
// the two held together (lock order: outMu is never nested with c.mu).
func (c *Channel) HLSStatus() (engine string, generation int, ok bool) {
	entry, _, ok := c.statusEntryKey()
	if !ok {
		return "", 0, false
	}
	return string(entry.pipeline.Engine()), entry.pipeline.Generation(), true
}

// statusEntryKey is the registry entry HLSStatus reports and its key: the one
// under the channel's current key, else the lowest key's.
func (c *Channel) statusEntryKey() (*hlsEntry, string, bool) {
	key := c.HLSProfile().Key()
	c.outMu.Lock()
	defer c.outMu.Unlock()
	if entry, running := c.hls[key]; running {
		return entry, key, true
	}
	keys := make([]string, 0, len(c.hls))
	for k := range c.hls {
		keys = append(keys, k)
	}
	if len(keys) == 0 {
		return nil, "", false
	}
	sort.Strings(keys)
	return c.hls[keys[0]], keys[0], true
}

// HLSPipeline is the pipeline HLSStatus reports, under the same key. The rig
// tests reach a channel's store through it.
func (c *Channel) HLSPipeline() (*hls.Pipeline, bool) {
	entry, _, ok := c.statusEntryKey()
	if !ok {
		return nil, false
	}
	return entry.pipeline, true
}

// RewindStatus is when the channel began lingering (zero while it is not) and
// the rewind window of the pipeline HLSStatus reports; ok is false with no
// pipeline.
func (c *Channel) RewindStatus() (lingeringSince time.Time, window hls.WindowStatus, ok bool) {
	entry, _, ok := c.statusEntryKey()
	if !ok {
		return time.Time{}, hls.WindowStatus{}, false
	}
	since, _ := c.Lingering()
	return since, entry.pipeline.Store().WindowStatus(), true
}
