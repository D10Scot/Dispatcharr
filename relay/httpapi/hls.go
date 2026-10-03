package httpapi

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/hls"
	"github.com/D10Scot/Dispatcharr/relay/session"
)

// The HLS output's HTTP half (Phase 4 spec D2-D5, D13; § The contract; §
// Presence and lifecycle). A tune whose format resolves to hls answers a
// multivariant playlist instead of bytes, and everything after that is a
// request under /hls/<token>/..., where the token is an opaque, relay-minted
// media-session id (control/mediasession.go) that names no channel and lives
// exactly as long as its session (relay/session).
//
// THE TOKEN AND THE SID ARE NEVER LOGGED, at any level, in any form: they are
// the whole of a session's authorization, and nginx's access log already has
// the token in it (spec § Risks). Every line here names the channel and the
// client id, never either.

// OutputFormatHLS is the format a tune asks for with ?output_format=hls (or
// m3u8) and an Xtream `.m3u8` URL forces.
const OutputFormatHLS = "hls"

// readyWaitMargin is what the entry's waits allow beyond the pipeline's own
// worst legitimate cold start.
const readyWaitMargin = 2 * time.Second

// The waits an HLS request may spend on the pipeline (spec § Entry, § Session
// resources; rulings R56 and R57). DERIVED from the pipeline's own bounds so
// they cannot drift below what a legitimate cold software start can take: the
// quick probe (3 s) and, in sequence, the re-probe (8 s), then the startup
// stall allowance a generation gets before its first fragment -- 30 s at every
// target duration up to the longest, 6 (R55, R58) -- plus a margin: 43 s. A 503
// on the multivariant fails an AVPlayer item outright, so this must not be
// shorter.
//
// The entry's wait also covers the source's start (issue #560): on a cold
// channel the probe first waits up to hls.SourceStartWait (15 s) for the
// ring's first chunk, so the entry waits 58 s, under nginx's 300 s
// proxy_read_timeout on the tune locations. A media playlist is requested only
// after its multivariant, once the source has started, so its wait keeps 43 s,
// under nginx's 60 s on /hls/.
var (
	defaultPlaylistWait = hls.QuickProbe.Analyze + hls.FullProbe.Analyze + hls.StartupStall(hls.MaxTargetDuration) + readyWaitMargin
	defaultReadyWait    = hls.SourceStartWait + defaultPlaylistWait
)

const (
	contentTypePlaylist = "application/vnd.apple.mpegurl"
	noBodyRetryAfter    = "1"

	// The one 403 body, for every way a token can be refused: a forged
	// token, an unknown session and a left one say the same thing.
	forbiddenSessionBody = `{"error": "invalid or expired media session"}`
	noVideoBody          = `{"error": "no video stream in the source"}`
	outputFailedBody     = `{"error": "HLS output failed"}`
	startFailedBody      = `{"error": "Failed to start the HLS output"}`
)

// endedBodies are the four 410 bodies of a STOPPED session, by the reason it
// records (Phase 4 spec § Session resources; R114). Both fields are kept:
// `error`, because every other JSON error body the relay writes carries one,
// and `ended` for the reason.
var endedBodies = map[session.EndReason]string{
	session.EndStreamLimit:    `{"error": "stream limit", "ended": "stream_limit"}`,
	session.EndAdminStop:      `{"error": "stopped by an administrator", "ended": "admin_stop"}`,
	session.EndChannelStopped: `{"error": "channel stopped", "ended": "channel_stopped"}`,
	session.EndOutputFailed:   `{"error": "HLS output failed", "ended": "output_failed"}`,
}

// writeEnded answers a request on a STOPPED session: 410 and the body of the
// reason it records. An empty or unknown reason is channel_stopped, which is
// what the table records when nothing else was.
func writeEnded(w http.ResponseWriter, reason session.EndReason) {
	body, ok := endedBodies[reason]
	if !ok {
		body = endedBodies[session.EndChannelStopped]
	}
	writeJSONBody(w, http.StatusGone, body)
}

// HLSDeps is the HLS output's process-wide state and its test seams.
type HLSDeps struct {
	// Detector and Silence are process-wide: main.go builds one of each, so
	// every channel's pipeline shares the one Quick Sync detection and the
	// canned-silence cache. Nil gives each pipeline its own.
	Detector *hls.Detector
	Silence  *hls.SilenceCache

	// Rewind is the process-wide on-disk rewind store (Phase 4a-3): main.go
	// builds one. Nil means no channel keeps a window, which every test but
	// the rewind ones wants.
	Rewind *hls.Rewind

	// The rest are test seams, never set by main.go: the process a pipeline
	// spawns for its encoder and its probe, the exit grace and stall
	// watchdog, and the two waits.
	Command                 func(hls.Spawn) (string, []string)
	ProbeCommand            func(generation int) (string, []string)
	ExitGrace, StallTimeout time.Duration
	ReadyWait, PlaylistWait time.Duration
}

func (d HLSDeps) readyWait() time.Duration {
	if d.ReadyWait > 0 {
		return d.ReadyWait
	}
	return defaultReadyWait
}

func (d HLSDeps) playlistWait() time.Duration {
	if d.PlaylistWait > 0 {
		return d.PlaylistWait
	}
	return defaultPlaylistWait
}

// hlsHooks are the HLS handlers' five test seams, nil in production and set
// only by this package's own tests. Each fires at the one point a test needs
// to land a concurrent event exactly, where a sleep would only hope to.
type hlsHooks struct {
	// afterResumeLookup fires after a resume's Begin and before its attach;
	// afterResumeAttach after both attaches and before ResumeCommit.
	afterResumeLookup func()
	afterResumeAttach func()
	// afterEntryAttach fires between an entry's AttachHLS and its Add.
	afterEntryAttach func()
	// beforeLeaveClientRelease is the session's Releases.BeforeClient: it
	// fires inside a departure, after the pipeline release and before the
	// client release. The entry hands it to Table.Add because Departure's
	// fields are unexported and the leave handler cannot reach them.
	beforeLeaveClientRelease func()
	// beforeWatchMark fires in watchHLS after Done and before its FailHLS.
	beforeWatchMark func()
}

// hooksOf is deps.hooks, or the zero value when there are none, so a caller
// reads a field without a nil check on the pointer.
func hooksOf(deps StreamDeps) hlsHooks {
	if deps.hooks == nil {
		return hlsHooks{}
	}
	return *deps.hooks
}

func fire(f func()) {
	if f != nil {
		f()
	}
}

// hlsFields is the payload's hls_encoder and hls_generation for a channel:
// absent (empty and nil) with no HLS pipeline, the engine absent until the
// first generation has chosen one.
func hlsFields(c *channel.Channel) (string, *int) {
	engine, generation, ok := c.HLSStatus()
	if !ok {
		return "", nil
	}
	return engine, &generation
}

// rewindFields is the payload's three rewind fields (Phase 4a-3): when the
// channel began lingering, the span of the video playlist the pipeline lists,
// and whether its window degraded. All absent with no HLS pipeline, and the
// first absent while the channel is not lingering.
func rewindFields(c *channel.Channel) (lingeringSince, windowSeconds *float64, degraded bool) {
	since, window, ok := c.RewindStatus()
	if !ok {
		return nil, nil, false
	}
	if !since.IsZero() {
		f := unixFloat(since)
		lingeringSince = &f
	}
	return lingeringSince, &window.Seconds, window.Degraded
}

func writeJSONBody(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(body))
}

// writeRetry answers 503 with Retry-After: 1, the one answer for "not now":
// a pipeline that is not ready yet, a channel that is ending, a session that
// is settling.
func writeRetry(w http.ResponseWriter, message string) {
	w.Header().Set("Retry-After", noBodyRetryAfter)
	http.Error(w, message, http.StatusServiceUnavailable)
}

// pipelineEnded reports whether p's Done is closed.
func pipelineEnded(p *hls.Pipeline) bool {
	select {
	case <-p.Done():
		return true
	default:
		return false
	}
}

// startPipeline is the start func AttachHLS takes: it builds the pipeline's
// Config from the channel and the process-wide HLS state, and starts it.
func startPipeline(ctx context.Context, deps StreamDeps, ch *channel.Channel, mode hls.Mode, log *slog.Logger) func(hls.Source) (*hls.Pipeline, error) {
	return func(src hls.Source) (*hls.Pipeline, error) {
		// ctx is context.Background(), NOT the entering request's: one
		// pipeline is shared by every session on the channel, so the first
		// viewer's disconnect must not cancel what the second is reading.
		// What ends it is its refcount reaching zero, the channel's stop, or
		// its own failure, all of which are reached on every path.
		return hls.Start(ctx, hls.Config{
			ChannelID:    ch.ID(),
			Source:       src,
			Mode:         mode,
			JoinBehind:   ch.Tuning().JoinBehind,
			Detector:     deps.HLS.Detector,
			Silence:      deps.HLS.Silence,
			Rewind:       deps.HLS.Rewind,
			WindowDepth:  ch.Tuning().RewindWindow,
			Command:      deps.HLS.Command,
			ProbeCommand: deps.HLS.ProbeCommand,
			ExitGrace:    deps.HLS.ExitGrace,
			StallTimeout: deps.HLS.StallTimeout,
			Log:          log,
		})
	}
}

// serveHLSEntry is the HLS tune (spec § Entry): the channel is up and the
// client registered, and this either answers the multivariant playlist and
// leaves a live session behind, or answers an error and leaves nothing.
//
// release is the Attach release func. It is HANDED to the session, which runs
// it when the session ends -- and this function calls it itself on every
// failure path before the response, so a channel that this entry alone started
// is stopped by the ordinary idle rule, ShutdownDelay included.
func serveHLSEntry(w http.ResponseWriter, r *http.Request, deps StreamDeps, ch *channel.Channel, client *channel.Client, release func(), log *slog.Logger) {
	sessions := deps.Sessions
	if sessions == nil {
		release()
		log.Error("an hls tune arrived at a relay with no session table", "channel", ch.ID())
		http.Error(w, "this output is not served", http.StatusNotImplemented)
		return
	}
	hooks := hooksOf(deps)
	now := deps.Now
	if now == nil {
		now = time.Now
	}

	// 1. D12's relay half: X-Relay-Output is ignored on an hls tune. Through
	// the channel's own setter -- never by writing the field on the pointer,
	// which the status endpoints read under c.mu.
	ch.SetClientOutputProfile(client.ID, nil)

	// 1a. The channel's HLS profile (Phase 4a-1d). An answer that carried no
	// hls_profile at all -- a control plane older than 4a-1d -- or a mode this
	// relay does not know is a contract mismatch, as an absent output_profiles
	// is: 502 after the Attach release. A TS or fMP4 tune never asks.
	profile := ch.HLSProfile()
	if !profile.Known {
		release()
		log.Error("the control plane sent no usable hls_profile", "channel", ch.ID(), "client", client.ID)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
		return
	}
	key := profile.Key()
	mode := hls.ModeTranscode
	if profile.Mode == hlsModeAutomatic {
		mode = hls.ModeAutomatic
	}

	// 2. Attach to the channel's HLS pipeline for its key, starting one if
	// none runs.
	p, started, releaseOutput, err := ch.AttachHLS(key, startPipeline(context.Background(), deps, ch, mode, log))
	if err != nil {
		release()
		var failed *channel.ErrHLSOutputFailed
		switch {
		case errors.As(err, &failed):
			log.Warn("refusing an HLS entry: the channel's HLS output failed and no source boundary has cleared it",
				"channel", ch.ID(), "client", client.ID)
			writeJSONBody(w, http.StatusBadGateway, failureBody(failed.Reason))
		case errors.Is(err, channel.ErrChannelEnding):
			writeRetry(w, "the channel is ending")
		default:
			log.Error("the HLS output could not be started", "channel", ch.ID(), "client", client.ID)
			writeJSONBody(w, http.StatusInternalServerError, startFailedBody)
		}
		return
	}
	// 3. The failure watcher, once per pipeline.
	if started {
		go watchHLS(deps, ch, key, p)
	}

	// 4. The session, keyed by an id nobody else can guess.
	sid, err := control.NewMediaSessionID()
	if err != nil {
		releaseOutput()
		release()
		log.Error("no media-session id could be minted", "channel", ch.ID(), "client", client.ID)
		writeJSONBody(w, http.StatusInternalServerError, startFailedBody)
		return
	}
	token := control.MediaSessionToken(deps.Secret, sid)
	fire(hooks.afterEntryAttach)
	sessions.Add(&session.Session{
		ID: sid, Owner: ch, Key: key, Pipeline: p, TD: hls.TargetDuration * time.Second,
		Grace: ch.Tuning().BehindLiveGrace,
	}, client, session.Releases{Output: releaseOutput, Client: release, BeforeClient: hooks.beforeLeaveClientRelease})

	// abandon ends an entry that will not answer 200: the releases the table
	// still held go to us, and none when a stopper already took them.
	abandon := func() {
		if releases, held := sessions.Abandon(sid); held {
			releases.Output()
			releases.Client()
		}
	}

	// 4a. The stopped-while-attaching re-check. The two goroutines that ever
	// mark a session STOPPED fire only after these two conditions -- the
	// run-end hook after the ring closed, watchHLS after the pipeline's Done
	// -- so a session added while both are still open is seen by whichever of
	// them runs later, and one added after either has fired is refused here.
	// Without it an entry that joins a ready pipeline (whose Ready keeps
	// answering nil after a failure) and adds its session just after the
	// stopper swept would be served a frozen playlist forever.
	if ch.Ring().Closed() || pipelineEnded(p) {
		abandon()
		writeRetry(w, "the channel is ending")
		return
	}

	// 5. Wait for the pipeline's init segments.
	readyCtx, cancel := context.WithTimeout(r.Context(), deps.HLS.readyWait())
	readyErr := p.Ready(readyCtx)
	cancel()
	switch {
	case readyErr == nil:
	case r.Context().Err() != nil:
		// The viewer went away while it waited.
		abandon()
		return
	case errors.Is(readyErr, hls.ErrNoVideo), errors.Is(readyErr, hls.ErrFailed):
		// The entry marks the channel ITSELF, ahead of the watcher: Ready
		// answers the moment the pipeline calls finish, but Done closes only
		// after its store and background work have wound down, so a
		// watcher-only mark would land after this 502 and after abandon's
		// release unregistered the pipeline -- and a second entry in that
		// window would start a fresh pipeline and re-probe. FailHLS is
		// idempotent and identity-safe, so the watcher's later call is a
		// no-op.
		ch.FailHLS(key, p, readyErr)
		abandon()
		log.Warn("an HLS entry failed: the pipeline's output failed", "channel", ch.ID(), "client", client.ID)
		writeJSONBody(w, http.StatusBadGateway, failureBody(readyErr))
		return
	case errors.Is(readyErr, hls.ErrStoreClosed):
		// The pipeline stopped: its channel is ending.
		abandon()
		writeRetry(w, "the channel is ending")
		return
	default:
		// The wait's own deadline: the encoder produced no init in time.
		abandon()
		log.Warn("an HLS entry timed out waiting for the encoder's init segments", "channel", ch.ID(), "client", client.ID)
		writeRetry(w, "the HLS output is not ready")
		return
	}

	// 5a. The session's presence thresholds are its pipeline's own (R42): a
	// copied automatic run's target duration is known only now, once the first
	// generation's output is decided. The entry request is in flight, so no
	// threshold has read the placeholder Add gave it.
	sessions.SetTD(sid, p.TargetDuration())

	// 6. The multivariant, under this session's own token.
	body, err := p.Multivariant("/hls/" + token)
	if err != nil {
		// Unreachable once Ready answered nil (the pipeline renders it from
		// the same state), and answered as a failed output if it ever is.
		ch.FailHLS(key, p, hls.ErrFailed)
		abandon()
		log.Error("the HLS multivariant could not be rendered", "channel", ch.ID(), "client", client.ID)
		writeJSONBody(w, http.StatusBadGateway, outputFailedBody)
		return
	}
	if pipelineEnded(p) {
		abandon()
		writeRetry(w, "the channel is ending")
		return
	}

	// 7. client_connect, then the session goes ACTIVE. A false Activate -- the
	// channel stopped meanwhile, or an admin ended the client -- means the
	// stopper or the admin end already took the client entry and the releases,
	// and the connect just emitted is owed its disconnect, which the entry
	// emits itself: no client_disconnect ever precedes its client_connect.
	ch.EmitClientConnect(client)
	if !sessions.Activate(sid) {
		// No token was ever handed out, so nothing could be answered 410 on
		// this entry: it removes its own session rather than leave a STOPPED
		// one for the sweeper. The stopper took the releases (Abandon returns
		// none).
		sessions.Abandon(sid)
		ch.EmitClientDisconnect(client, now())
		writeRetry(w, "the session ended")
		return
	}

	// 8. The multivariant.
	w.Header().Set("Content-Type", contentTypePlaylist)
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	if _, err := w.Write(body); err == nil {
		client.Sent(len(body), now())
	}
	log.Info("an HLS session started", "channel", ch.ID(), "client", client.ID)
}

// failureBody is the entry's 502 body for a failed output, by its reason.
func failureBody(reason error) string {
	if errors.Is(reason, hls.ErrNoVideo) {
		return noVideoBody
	}
	return outputFailedBody
}

// watchHLS is the failure watcher, one per pipeline (Decision 9): it waits
// for the pipeline to end and, when it ended in failure, marks the channel,
// stops the pipeline's sessions and asks the manager whether the channel is
// now idle. On a nil error -- a stop at refcount zero, or the channel ending
// -- it does nothing: the channel's own run-end hook covers a channel that
// ended.
func watchHLS(deps StreamDeps, ch *channel.Channel, key string, p *hls.Pipeline) {
	<-p.Done()
	err := p.Err()
	if err == nil {
		return
	}
	fire(hooksOf(deps).beforeWatchMark)
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	log.Warn("the channel's HLS output failed; its sessions are stopped", "channel", ch.ID(), "key", key)
	ch.FailHLS(key, p, err)
	stopped := deps.Sessions.StopPipeline(p)
	deps.Channels.EndHLSSessions(ch, stopped)
}

// HLSHandler serves the two GET shapes under /hls/<token>/: the media
// playlists at /hls/<token>/<rendition>.m3u8 and the init segments and media
// segments at /hls/<token>/<rendition>/<file>.
//
// It reads no X-Relay-* header and no X-Dispatcharr-Authorized: the token in
// the path is the whole authorization (ruling R13), and nginx blanks those
// headers on this location anyway.
func HLSHandler(deps StreamDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	now := deps.Now
	if now == nil {
		now = time.Now
	}
	return func(w http.ResponseWriter, r *http.Request) {
		sid, ok := control.VerifyMediaSession(deps.Secret, r.PathValue("token"))
		if !ok || deps.Sessions == nil {
			writeJSONBody(w, http.StatusForbidden, forbiddenSessionBody)
			return
		}
		lookup := deps.Sessions.Begin(sid)
		if lookup.Depart != nil {
			// A request that beat the sweeper to an idle session: the
			// departure the sweep would have run, run here, and once more.
			lookup.Depart.Run()
			lookup = deps.Sessions.Begin(sid)
		}
		switch lookup.Outcome {
		case session.Serve:
		case session.Gone:
			writeEnded(w, lookup.Reason)
			return
		case session.Busy:
			writeRetry(w, "the session is settling")
			return
		case session.Resume:
			var resumed bool
			lookup, resumed = resumeHLS(w, deps, sid, lookup, now, log)
			if !resumed {
				return
			}
		default:
			writeJSONBody(w, http.StatusForbidden, forbiddenSessionBody)
			return
		}
		defer deps.Sessions.End(sid)
		serveHLSResource(w, r, deps, lookup, now)
	}
}

// resumeHLS is a DEPARTED session's resume (spec § Resume never starts a
// channel): it re-attaches the session to the channel and the pipeline it
// already had, and to nothing else. It returns the lookup to serve from, and
// false when it has already answered.
//
// The three steps, each of which can lose a race to a stop and each of which
// undoes the ones before it:
//
//  1. register a fresh client against the session's own *Channel, only while
//     that channel is the running one -- never through Attach, which would
//     start one;
//  2. re-attach to the session's own running pipeline (R49: a fresh pipeline
//     would restart the media sequence under the same playlist URL);
//  3. commit, only if the session is still DEPARTED.
func resumeHLS(w http.ResponseWriter, deps StreamDeps, sid string, lookup session.Lookup, now func() time.Time, log *slog.Logger) (session.Lookup, bool) {
	hooks := hooksOf(deps)
	fire(hooks.afterResumeLookup)

	ch, isChannel := lookup.Session.Owner.(*channel.Channel)
	if !isChannel || lookup.Client == nil {
		writeEnded(w, deps.Sessions.ResumeFailed(sid))
		return lookup, false
	}
	fresh := *lookup.Client
	fresh.ConnectedAt = now()

	releaseClient, err := deps.Channels.AttachExisting(ch, &fresh)
	switch {
	case errors.Is(err, channel.ErrChannelAbsent):
		writeEnded(w, deps.Sessions.ResumeFailed(sid))
		return lookup, false
	case errors.Is(err, channel.ErrDuplicateClient):
		// Unreachable once a departure has settled (Decision 5): the old
		// entry is gone before the session is resumable. The session is left
		// DEPARTED, for the player's retry.
		writeRetry(w, "the client is still registered")
		return lookup, false
	case err != nil:
		log.Error("an HLS resume could not register its client", "channel", ch.ID())
		writeJSONBody(w, http.StatusInternalServerError, startFailedBody)
		return lookup, false
	}

	releaseOutput, ok := ch.AttachHLSExisting(lookup.Session.Key, lookup.Pipeline)
	if !ok {
		releaseClient()
		writeEnded(w, deps.Sessions.ResumeFailed(sid))
		return lookup, false
	}
	fire(hooks.afterResumeAttach)

	if !deps.Sessions.ResumeCommit(sid, &fresh, session.Releases{Output: releaseOutput, Client: releaseClient}) {
		releaseOutput()
		releaseClient()
		writeEnded(w, deps.Sessions.RefusedReason(sid))
		return lookup, false
	}
	ch.EmitClientConnect(&fresh)
	log.Info("an HLS session resumed", "channel", ch.ID(), "client", fresh.ID)
	lookup.Outcome, lookup.Client = session.Serve, &fresh
	return lookup, true
}

// serveHLSResource writes one resource of a live session. Every body written
// feeds the session's client meter, so bytes_sent counts HLS bytes.
func serveHLSResource(w http.ResponseWriter, r *http.Request, deps StreamDeps, lookup session.Lookup, now func() time.Time) {
	p := lookup.Pipeline
	output, ready := p.Output()
	if !ready {
		writeRetry(w, "the HLS output is not ready")
		return
	}
	write := func(body []byte) {
		if _, err := w.Write(body); err == nil && lookup.Client != nil {
			lookup.Client.Sent(len(body), now())
		}
	}

	rendition, file := r.PathValue("rendition"), r.PathValue("file")
	if rendition == "" {
		// /hls/<token>/<rendition>.m3u8
		name, isPlaylist := strings.CutSuffix(file, ".m3u8")
		if !isPlaylist || !declared(output, name) {
			http.NotFound(w, r)
			return
		}
		waitCtx, cancel := context.WithTimeout(r.Context(), deps.HLS.playlistWait())
		err := p.Store().WaitSegment(waitCtx)
		cancel()
		if err != nil {
			if r.Context().Err() == nil {
				writeRetry(w, "the first segment is not ready")
			}
			return
		}
		body, published, found := p.Store().MediaPlaylist(name)
		if !found {
			writeRetry(w, "the first segment is not ready")
			return
		}
		w.Header().Set("Content-Type", contentTypePlaylist)
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Last-Modified", published.UTC().Format(http.TimeFormat))
		w.WriteHeader(http.StatusOK)
		write(body)
		return
	}

	// /hls/<token>/<rendition>/init-<gen>.mp4 and /<seq>.m4s
	if !declared(output, rendition) {
		http.NotFound(w, r)
		return
	}
	var body []byte
	var found bool
	switch {
	case strings.HasPrefix(file, "init-") && strings.HasSuffix(file, ".mp4"):
		gen, err := strconv.Atoi(strings.TrimSuffix(strings.TrimPrefix(file, "init-"), ".mp4"))
		if err != nil || gen < 0 {
			http.NotFound(w, r)
			return
		}
		body, found = p.Store().Init(rendition, gen)
	case strings.HasSuffix(file, ".m4s"):
		seq, err := strconv.ParseUint(strings.TrimSuffix(file, ".m4s"), 10, 64)
		if err != nil {
			http.NotFound(w, r)
			return
		}
		var behind time.Duration
		body, behind, found = p.Store().SegmentAt(rendition, seq)
		if found && lookup.Session != nil {
			// The latest served segment decides whether the session is
			// behind live (Phase 4a-3); a playlist, an init or a 404 moves
			// nothing.
			deps.Sessions.NoteSegment(lookup.Session.ID, behind)
		}
	}
	if !found {
		http.NotFound(w, r)
		return
	}
	contentType := "audio/mp4"
	if rendition == hls.RenditionVideo {
		contentType = "video/mp4"
	}
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Cache-Control", "private, max-age=86400")
	w.WriteHeader(http.StatusOK)
	write(body)
}

// declared reports whether rendition is one this run's output declares.
func declared(output hls.Output, rendition string) bool {
	for _, name := range output.Renditions() {
		if name == rendition {
			return true
		}
	}
	return false
}

// HLSLeaveHandler serves DELETE /hls/<token>: the explicit leave (spec
// § Session resources). The session ends at once and the 204 is written only
// AFTER its side effects have run -- the client_disconnect, the pipeline
// release and the client release -- so a zap that tunes B the instant A's
// DELETE returns finds A's registry entry already gone from the registry the
// stream-limit hop counts. The pipeline release is only a refcount decrement
// here: at zero it stops the pipeline on a goroutine of its own.
//
// Idempotent: an unknown or already-ended session answers 204 too. A token
// that fails its MAC is the one 403.
func HLSLeaveHandler(deps StreamDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		sid, ok := control.VerifyMediaSession(deps.Secret, r.PathValue("token"))
		if !ok || deps.Sessions == nil {
			writeJSONBody(w, http.StatusForbidden, forbiddenSessionBody)
			return
		}
		if departure := deps.Sessions.Leave(sid); departure != nil {
			departure.Run()
		}
		w.WriteHeader(http.StatusNoContent)
	}
}
