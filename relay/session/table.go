package session

import (
	"context"
	"log/slog"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/hls"
)

// State is where a session is in its life.
type State int

const (
	// Arrived is an entry request that has registered its client and its
	// pipeline reference and has not yet written the multivariant. It holds
	// one request in flight, so no sweep ever departs it.
	Arrived State = iota
	// Active is a session whose multivariant was written: it holds a registry
	// entry and a pipeline reference until it ends.
	Active
	// Departed is a session the idle sweep ended: its entry and reference are
	// released, and it may resume for ResumeWindow.
	Departed
	// Stopped is a session that ended under its viewer: its channel or
	// pipeline stopped, or an admin client stop or a stream-limit termination
	// reached it. It records why (Session.ended), answers 410 with that
	// reason to every request until it is forgotten ResumeWindow after it
	// stopped, and holds no pipeline.
	Stopped
)

// EndReason is why a STOPPED session stopped: the `ended` field of its 410
// body (Phase 4 spec § Session resources; rulings R114, R120). It is recorded
// once, when the session is marked, and never overwritten.
type EndReason string

const (
	// EndStreamLimit is a stream-limit termination, which only Django's
	// attempt_stream_termination asks for (?reason=stream_limit).
	EndStreamLimit EndReason = "stream_limit"
	// EndAdminStop is an admin client stop, and every other client stop.
	EndAdminStop EndReason = "admin_stop"
	// EndChannelStopped is the channel stopping under the session, and a
	// failed resume that finds no other reason recorded.
	EndChannelStopped EndReason = "channel_stopped"
	// EndOutputFailed is the channel's HLS output failing.
	EndOutputFailed EndReason = "output_failed"
)

// Owner is the channel as the table needs it; *channel.Channel satisfies it.
// An interface so the state machine is testable without a running channel;
// identity is pointer equality through the interface.
type Owner interface {
	EmitClientConnect(cl *channel.Client)
	EmitClientDisconnect(cl *channel.Client, at time.Time)
}

// Releases are what an ARRIVED or ACTIVE session holds, run exactly once by
// whoever ends it. Output first -- the pipeline reference -- then the registry
// entry (Manager.release), which may stop the channel.
type Releases struct {
	Output, Client func()
	// BeforeClient is a test seam only, run between the two; nil in
	// production.
	BeforeClient func()
}

// Session is one viewer's media session.
type Session struct {
	// Immutable after Add, except TD and Pipeline.
	ID    string // the sid, never logged
	Owner Owner
	Key   string // the channel's HLS output key: "hls", or "hls:p<id>" for an HLS profile
	// Pipeline is under Table.mu: the STOPPED mark sets it to nil, so a
	// session the table keeps for ResumeWindow after it stopped does not pin
	// the pipeline's store. Owner is retained, as a DEPARTED session's is: a
	// resume that took its lookup before the mark reads it with no lock held.
	Pipeline *hls.Pipeline
	// TD is the session's pipeline's target duration, which every presence
	// threshold scales. Add sets it to hls.TargetDuration seconds and the
	// entry then fixes it with SetTD once the pipeline's first generation has
	// decided its own; it is fixed before Activate, and no threshold reads it
	// while the entry request is in flight.
	TD time.Duration
	// Grace is the channel's behind-live grace at entry (Phase 4a-3,
	// Tuning.BehindLiveGrace): how long after it would otherwise be silent a
	// session that was watching behind live stays unreclaimable. Immutable
	// after Add, and a resume keeps it.
	Grace time.Duration

	// Under Table.mu.
	behindLive bool            // the latest served media segment was more than BehindLiveAfter(TD) behind the newest
	client     *channel.Client // the current registry entry's client; replaced on resume
	state      State
	inFlight   int
	lastEnd    time.Time // arrival for the entry; the end of the last request after that
	departedAt time.Time
	stoppedAt  time.Time
	ended      EndReason // why the session is STOPPED; set with state
	settling   bool
	connected  bool // client_connect emitted for the current attachment
	releases   *Releases
}

// Config configures a Table.
type Config struct {
	// Now is the clock; nil means time.Now.
	Now func() time.Time
	// Tick drives the sweeper; nil means a SweepInterval ticker. Tests send on
	// it. The value sent is ignored: the sweep reads Now.
	Tick <-chan time.Time
	// Log receives the table's transitions, which name the client and never
	// the session id.
	Log *slog.Logger
}

// Table is the process-wide session table.
type Table struct {
	mu   sync.Mutex
	byID map[string]*Session
	now  func() time.Time
	tick <-chan time.Time
	log  *slog.Logger
}

// NewTable builds a table. It starts no goroutine: Run is the sweeper.
func NewTable(cfg Config) *Table {
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	return &Table{byID: map[string]*Session{}, now: now, tick: cfg.Tick, log: log}
}

// Add registers a session that is ARRIVED: one request in flight, its arrival
// the last time it was heard from, holding the releases of what the entry
// attached.
func (t *Table) Add(s *Session, client *channel.Client, r Releases) {
	t.mu.Lock()
	defer t.mu.Unlock()
	s.client = client
	s.state = Arrived
	s.inFlight = 1
	s.lastEnd = t.now()
	s.releases = &r
	t.byID[s.ID] = s
}

// SetTD fixes an ARRIVED session's target duration from its pipeline (Phase
// 4a-1d, R42): 2 s in transcode, up to 6 s for a copied automatic run. It is
// called once, after the pipeline is ready and before Activate. An ARRIVED
// session always holds its entry request in flight, so no idle or silence
// threshold reads TD until then, and the write is under the same lock the
// thresholds read it under. It is a no-op for anything but an ARRIVED session,
// so a late call can never move a live one's thresholds.
func (t *Table) SetTD(sid string, td time.Duration) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if s := t.byID[sid]; s != nil && s.state == Arrived {
		s.TD = td
	}
}

// NoteSegment records how far behind the newest segment the media segment a
// session was just served is (Phase 4a-3): the latest one decides whether the
// session is behind live. An ARRIVED or ACTIVE session only; a DEPARTED,
// STOPPED or unknown one is untouched.
func (t *Table) NoteSegment(sid string, behind time.Duration) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if s := t.byID[sid]; s != nil && (s.state == Arrived || s.state == Active) {
		s.behindLive = behind > BehindLiveAfter(s.TD)
	}
}

// Activate moves ARRIVED to ACTIVE once the multivariant is about to be
// written: the entry request is no longer in flight, the session has been
// heard from now, and client_connect has been emitted, so connected is true.
// False when the session is not ARRIVED -- its channel stopped, or an admin
// ended its client, while the entry waited.
func (t *Table) Activate(sid string) bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	s := t.byID[sid]
	if s == nil || s.state != Arrived {
		return false
	}
	s.state = Active
	s.inFlight--
	s.lastEnd = t.now()
	s.connected = true
	return true
}

// Abandon removes a session whose entry failed, and returns the releases the
// entry must then run: nil when the session no longer held them (a stopper
// took the client entry and the pipeline went with its channel, or an admin
// end ran them).
func (t *Table) Abandon(sid string) (*Releases, bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	s := t.byID[sid]
	if s == nil {
		return nil, false
	}
	delete(t.byID, sid)
	r := s.releases
	s.releases = nil
	return r, r != nil
}

// Outcome is what Begin decided a request is.
type Outcome int

const (
	// Unknown is a token for no session: 403, the same as a forged one.
	Unknown Outcome = iota
	// Gone is a STOPPED session's request: 410 with Lookup.Reason, on every
	// request until the entry is forgotten ResumeWindow after it stopped.
	Gone
	// Busy is a session whose idle departure is still settling: 503,
	// Retry-After 1.
	Busy
	// Resume is a DEPARTED session inside its window.
	Resume
	// Serve is an ARRIVED or ACTIVE session: the request counts as in flight
	// until End.
	Serve
)

// String names the outcome, so a failing assertion reads.
func (o Outcome) String() string {
	switch o {
	case Unknown:
		return "Unknown"
	case Gone:
		return "Gone"
	case Busy:
		return "Busy"
	case Resume:
		return "Resume"
	case Serve:
		return "Serve"
	}
	return "Outcome(?)"
}

// Lookup is Begin's answer.
type Lookup struct {
	Outcome  Outcome
	Session  *Session
	Client   *channel.Client // for Serve and Resume: the session's current client
	Pipeline *hls.Pipeline
	// Reason is why a Gone session stopped.
	Reason EndReason
	// Depart is non-nil when Begin found an ACTIVE session past its idle
	// timeout and ended it lazily, exactly as the sweep would have: the
	// caller runs it and asks Begin once more.
	Depart *Departure
}

// Begin is a GET's arrival. It applies every expiry lazily, exactly as Sweep
// would, so a request that beats the sweeper to an expired session sees what
// the sweeper would have left.
func (t *Table) Begin(sid string) Lookup {
	t.mu.Lock()
	defer t.mu.Unlock()
	s := t.byID[sid]
	if s == nil {
		return Lookup{Outcome: Unknown}
	}
	now := t.now()
	switch s.state {
	case Active:
		if s.inFlight == 0 && now.Sub(s.lastEnd) >= IdleTimeout(s.TD) {
			return Lookup{Outcome: Busy, Depart: t.departLocked(s, true)}
		}
		s.inFlight++
		return Lookup{Outcome: Serve, Session: s, Client: s.client, Pipeline: s.Pipeline}
	case Arrived:
		s.inFlight++
		return Lookup{Outcome: Serve, Session: s, Client: s.client, Pipeline: s.Pipeline}
	case Departed:
		if s.settling {
			return Lookup{Outcome: Busy}
		}
		if now.Sub(s.departedAt) > ResumeWindow {
			delete(t.byID, sid)
			return Lookup{Outcome: Unknown}
		}
		return Lookup{Outcome: Resume, Session: s, Client: s.client, Pipeline: s.Pipeline}
	case Stopped:
		if now.Sub(s.stoppedAt) > ResumeWindow {
			delete(t.byID, sid)
			return Lookup{Outcome: Unknown}
		}
		return Lookup{Outcome: Gone, Reason: s.ended}
	}
	return Lookup{Outcome: Unknown}
}

// End is a GET's completion: it is no longer in flight and the session was
// heard from now. A no-op for a session removed meanwhile.
func (t *Table) End(sid string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	s := t.byID[sid]
	if s == nil {
		return
	}
	if s.inFlight > 0 {
		s.inFlight--
	}
	s.lastEnd = t.now()
}

// ResumeFailed is a resume that could not attach. It marks the session
// STOPPED with EndChannelStopped only if it is still DEPARTED: a session a
// stopper marked first keeps that stopper's reason, and one a concurrent
// request resumed (ACTIVE) is left alone. It returns the reason the session
// then records, which the request's 410 carries; EndChannelStopped for a
// session that is gone or live.
func (t *Table) ResumeFailed(sid string) EndReason {
	t.mu.Lock()
	defer t.mu.Unlock()
	s := t.byID[sid]
	if s == nil {
		return EndChannelStopped
	}
	switch s.state {
	case Departed:
		t.markStoppedLocked(s, EndChannelStopped, t.now())
	case Stopped:
		return s.ended
	}
	return EndChannelStopped
}

// RefusedReason is the reason a refused ResumeCommit answers 410 with: the one
// the session records, or EndChannelStopped when it was removed meanwhile (a
// leave or an expiry, after which further requests are 403 anyway).
func (t *Table) RefusedReason(sid string) EndReason {
	t.mu.Lock()
	defer t.mu.Unlock()
	if s := t.byID[sid]; s != nil && s.state == Stopped {
		return s.ended
	}
	return EndChannelStopped
}

// ResumeCommit is a resume's third step: the session is still DEPARTED and
// not settling, so it becomes ACTIVE again on the fresh client the resume
// registered, holding the resume's releases, with this request in flight.
// False when it is not (a stop, a leave or an expiry got there first): the
// caller then runs r and answers 410.
func (t *Table) ResumeCommit(sid string, client *channel.Client, r Releases) bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	s := t.byID[sid]
	if s == nil || s.state != Departed || s.settling {
		return false
	}
	s.client = client
	s.state = Active
	s.inFlight = 1
	s.lastEnd = t.now()
	s.connected = true
	s.releases = &r
	return true
}

// Leave is DELETE /hls/<token>: the session is removed whatever its state, and
// a Departure comes back only when it held releases (ARRIVED or ACTIVE).
func (t *Table) Leave(sid string) *Departure {
	t.mu.Lock()
	defer t.mu.Unlock()
	s := t.byID[sid]
	if s == nil {
		return nil
	}
	delete(t.byID, sid)
	return t.takeLocked(s, false)
}

// EndClient is an admin client stop or a stream-limit termination reaching a
// client that is an HLS session's: the live session of that client id on that
// channel is marked STOPPED with reason, and its Departure returned, whose
// releases the caller runs (it is not a channel stop, so the pipeline's
// linger starts as a leave's does). A DEPARTED session holding no entry, and a
// STOPPED one, are left alone.
func (t *Table) EndClient(o Owner, clientID string, reason EndReason) *Departure {
	t.mu.Lock()
	defer t.mu.Unlock()
	for _, s := range t.byID {
		if s.Owner != o || s.client == nil || s.client.ID != clientID {
			continue
		}
		if s.state != Arrived && s.state != Active {
			continue
		}
		d := t.takeLocked(s, false)
		t.markStoppedLocked(s, reason, t.now())
		return d
	}
	return nil
}

// StopChannel marks every session of c STOPPED. It implements
// channel.SessionEnder.
func (t *Table) StopChannel(c *channel.Channel) []channel.StoppedClient {
	return t.stopOwner(c)
}

func (t *Table) stopOwner(o Owner) []channel.StoppedClient {
	return t.stop(func(s *Session) bool { return s.Owner == o }, EndChannelStopped)
}

// StopPipeline marks every session of p STOPPED: its output failed.
func (t *Table) StopPipeline(p *hls.Pipeline) []channel.StoppedClient {
	return t.stop(func(s *Session) bool { return s.Pipeline == p }, EndOutputFailed)
}

// stop marks every ARRIVED, ACTIVE or DEPARTED session that matches STOPPED,
// DISCARDS their releases -- whoever stops the channel or the pipeline drops
// the client entries itself, and the pipeline goes with its channel or its
// failure -- and returns the client entries the sessions held.
func (t *Table) stop(match func(*Session) bool, reason EndReason) []channel.StoppedClient {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.stopLocked(match, reason, t.now())
}

// stopLocked is stop's body, for a caller that already holds t.mu and has
// read the clock (StopIfSilent takes its verdict and its mark in one
// critical section).
func (t *Table) stopLocked(match func(*Session) bool, reason EndReason, now time.Time) []channel.StoppedClient {
	var stopped []channel.StoppedClient
	for _, s := range t.byID {
		if s.state == Stopped || !match(s) {
			continue
		}
		if s.releases != nil && !s.settling {
			stopped = append(stopped, channel.StoppedClient{ClientID: s.client.ID, Connected: s.connected})
		}
		t.markStoppedLocked(s, reason, now)
	}
	return stopped
}

// markStoppedLocked is the one STOPPED mark: it discards whatever releases the
// session still holds (a caller that wants them took them first), records why,
// and drops the pipeline so the entry the table keeps for ResumeWindow holds no
// store. Callers have checked the session is not already STOPPED, which is what
// keeps the first reason.
func (t *Table) markStoppedLocked(s *Session, reason EndReason, now time.Time) {
	s.releases = nil
	s.state = Stopped
	s.stoppedAt = now
	s.ended = reason
	s.Pipeline = nil
}

// takeLocked takes a live session's releases into a Departure, or returns nil
// when it holds none.
func (t *Table) takeLocked(s *Session, idle bool) *Departure {
	if s.releases == nil || s.settling {
		return nil
	}
	d := &Departure{
		table: t, session: s, owner: s.Owner, client: s.client,
		connected: s.connected, releases: *s.releases, idle: idle,
	}
	s.releases = nil
	return d
}

// departLocked ends an ACTIVE session idle: it takes the releases, becomes
// DEPARTED with settling true, and the Departure runs outside the lock and
// settles it.
func (t *Table) departLocked(s *Session, idle bool) *Departure {
	d := t.takeLocked(s, idle)
	s.state = Departed
	s.settling = true
	s.connected = false
	return d
}

// Sweep is one tick's work, under the lock: every ACTIVE session with nothing
// in flight past its idle timeout departs, and every DEPARTED or STOPPED one
// past ResumeWindow is forgotten. It returns the departures; the caller runs
// each on a goroutine of its own (R51).
func (t *Table) Sweep() []*Departure {
	t.mu.Lock()
	defer t.mu.Unlock()
	now := t.now()
	var out []*Departure
	for sid, s := range t.byID {
		switch s.state {
		case Active:
			if s.inFlight == 0 && now.Sub(s.lastEnd) >= IdleTimeout(s.TD) {
				if d := t.departLocked(s, true); d != nil {
					out = append(out, d)
				}
			}
		case Departed:
			if !s.settling && now.Sub(s.departedAt) > ResumeWindow {
				delete(t.byID, sid)
			}
		case Stopped:
			if now.Sub(s.stoppedAt) > ResumeWindow {
				delete(t.byID, sid)
			}
		}
	}
	return out
}

// Run is the process-wide sweeper: every tick, Sweep, then each departure on a
// goroutine of its own. A departure can wait out a channel's stop
// (Manager.StopWait), and on the sweeper's goroutine that wait would delay
// every other session's departure past "one idle timeout plus one tick".
func (t *Table) Run(ctx context.Context) {
	tick := t.tick
	if tick == nil {
		ticker := time.NewTicker(SweepInterval)
		defer ticker.Stop()
		tick = ticker.C
	}
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick:
			for _, d := range t.Sweep() {
				go d.Run()
			}
		}
	}
}

// Len is how many sessions the table holds, for tests.
func (t *Table) Len() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return len(t.byID)
}

// InFlight is how many requests of the session are in flight, for tests; 0
// for an unknown sid.
func (t *Table) InFlight(sid string) int {
	t.mu.Lock()
	defer t.mu.Unlock()
	if s := t.byID[sid]; s != nil {
		return s.inFlight
	}
	return 0
}

// settle ends an idle departure's settling: it is now resumable, and its
// window starts. It NEVER writes the state: the departure's own Client release
// can stop the channel, which marks this very session STOPPED while the
// departure is still running, and a settle that wrote Departed would turn that
// STOPPED session back into a resumable one.
func (t *Table) settle(s *Session) {
	t.mu.Lock()
	defer t.mu.Unlock()
	s.settling = false
	if s.state == Departed {
		s.departedAt = t.now()
	}
}
