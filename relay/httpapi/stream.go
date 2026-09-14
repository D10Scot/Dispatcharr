package httpapi

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"net"
	"net/http"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// StreamDeps is everything the live TS handler needs.
type StreamDeps struct {
	// Secret is the deployment's Django SECRET_KEY, used to verify the
	// X-Dispatcharr-Authorized marker nginx sets.
	Secret string

	// Channels owns every running channel.
	Channels *channel.Manager

	// Control calls Django's /api/relay/... routes.
	Control *control.Client

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger

	// Now is the clock a client's ConnectedAt comes from. Nil means time.Now.
	Now func() time.Time
}

// The proxy_settings keys this PR reads. Named constants rather than literals
// at the call site, so a rename on the wire is one edit and a typo is a
// compile error rather than a runtime ErrSettingAbsent.
const (
	settingChunkBytes       = "BUFFER_CHUNK_SIZE"
	settingRetention        = "redis_chunk_ttl"
	settingJoinBehind       = "new_client_behind_seconds"
	settingReadSize         = "CHUNK_SIZE"
	settingShutdownDelay    = "channel_shutdown_delay"
	settingBufferingSpeed   = "buffering_speed"
	settingBufferingTimeout = "buffering_timeout"
	settingDefaultUserAgent = "DEFAULT_USER_AGENT"
)

// tuningFrom resolves the channel-start-time settings out of a next-source
// answer, and returns the upstream read size alongside them.
//
// Every key is required. Amendment A1.4 makes Django send EFFECTIVE settings,
// so an absent key means a control plane older than this relay, and falling
// back to a Go-side default would be exactly the second copy A1.4 removes.
func tuningFrom(s control.Settings) (channel.Tuning, int, error) {
	var t channel.Tuning
	var err error

	if t.ChunkBytes, err = s.Int(settingChunkBytes); err != nil {
		return t, 0, err
	}
	if t.Retention, err = s.Seconds(settingRetention); err != nil {
		return t, 0, err
	}
	if t.JoinBehind, err = s.Seconds(settingJoinBehind); err != nil {
		return t, 0, err
	}
	if t.ShutdownDelay, err = s.Seconds(settingShutdownDelay); err != nil {
		return t, 0, err
	}
	// The buffering thresholds, read on EVERY tune including a Proxy one
	// that will never consult them: a setting is read from the wire or the
	// tune fails (Global Constraint 13), and reading them only on the
	// transcode path would leave the per-key test green against a Proxy
	// rig while a transcode tune silently defaulted.
	if t.BufferingSpeed, err = s.Float(settingBufferingSpeed); err != nil {
		return t, 0, err
	}
	if t.BufferingTimeout, err = s.Seconds(settingBufferingTimeout); err != nil {
		return t, 0, err
	}
	readSize, err := s.Int(settingReadSize)
	if err != nil {
		return t, 0, err
	}
	return t, readSize, nil
}

// OutputFormatMPEGTS is the only output format this relay serves.
//
// The value channel_status.py:567 records when no format was chosen
// (`output_format or 'mpegts'`). fMP4 is 2c-6's.
const OutputFormatMPEGTS = "mpegts"

// tuneBudget bounds a DETACHED next-source call -- see startProxyTune.
//
// control.Client's own worst case: two attempts of (ConnectTimeout,
// ReadTimeout) plus the retry delay between them. `attempts` is unexported, so
// the 2 is written here; if control ever changes it this over- or undershoots,
// which costs a longer or shorter gate wait and never correctness, because each
// attempt is still bounded by the client's own http.Client.Timeout.
const tuneBudget = 2*(control.ConnectTimeout+control.ReadTimeout) + control.RetryDelay

// StreamHandler serves GET /proxy/ts/stream/{channelID}.
func StreamHandler(deps StreamDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	now := deps.Now
	if now == nil {
		now = time.Now
	}

	return func(w http.ResponseWriter, r *http.Request) {
		id, client, err := identify(r, deps.Secret, now)
		if err != nil {
			writeTuneFailure(w, log, id, err)
			return
		}
		if id == "" {
			http.Error(w, "no channel in the request", http.StatusBadRequest)
			return
		}

		ch, release, err := deps.Channels.Attach(id, client, func() (channel.Started, error) {
			return startTune(r.Context(), deps.Control, id)
		})
		if err != nil {
			writeTuneFailure(w, log, id, err)
			return
		}
		defer release()

		w.Header().Set("Content-Type", "video/mp2t")
		w.Header().Set("Cache-Control", "no-cache")
		w.WriteHeader(http.StatusOK)
		rc := http.NewResponseController(w)
		if err := rc.Flush(); err != nil {
			return
		}

		serveClient(r.Context(), w, rc, ch, client, log)
	}
}

// ErrUnsupportedOutput is returned when the authorize hop asked for an output
// format or an Output Profile this relay does not serve.
//
// Refused rather than served, for 2c-2's reason on stream_profile.kind: a
// relay that logged "fmp4" in its registry and then wrote MPEG-TS would be
// wrong in a way nothing on the wire says, and serving it under the label
// "mpegts" would be a lie in the payload /proxy/stats/ renders. 2c-6 brings
// fMP4 and 2c-7 the Output Profiles.
type ErrUnsupportedOutput struct {
	Format    string
	ProfileID string
}

func (e *ErrUnsupportedOutput) Error() string {
	if e.ProfileID != "" {
		return fmt.Sprintf("the Go relay serves no Output Profile yet, and this tune asked for %q", e.ProfileID)
	}
	return fmt.Sprintf("the Go relay serves only %q, not %q", OutputFormatMPEGTS, e.Format)
}

// identify resolves which channel this request is for and who is asking.
//
// The five X-Relay-* values are read ONLY when X-Dispatcharr-Authorized proves
// nginx put them there. Without that check any client could name any channel,
// any client id, any address and any user by hand and bypass whatever the
// authorize hop decided -- that marker is the entire reason
// apps/proxy/authorize.py can be the only place the decision is made. An
// untrusted request falls back to the path value and to values resolved here,
// which is the dev shape; 2c-8 brings POST /_dispatcharr/authorize-internal.
//
// One closure rather than five `if trusted` blocks: five is five chances to
// omit one, and the one omitted is the one that matters.
func identify(r *http.Request, secret string, now func() time.Time) (string, *channel.Client, error) {
	trusted := control.IsRelayTrusted(secret, r.Header.Get(control.HeaderAuthorized))

	header := func(name string) string {
		if !trusted {
			return ""
		}
		return r.Header.Get(name)
	}

	id := header("X-Relay-Channel")
	if id == "" {
		id = r.PathValue("channelID")
	}

	// Refused before anything is registered or attached, so a tune this relay
	// cannot serve never reaches the control plane.
	if profileID := header("X-Relay-Output"); profileID != "" {
		return id, nil, &ErrUnsupportedOutput{ProfileID: profileID}
	}
	if format := header("X-Relay-Output-Format"); format != "" && format != OutputFormatMPEGTS {
		return id, nil, &ErrUnsupportedOutput{Format: format}
	}

	clientID := header("X-Relay-Client")
	if clientID == "" {
		clientID = mintClientID(now())
	}

	ip := header("X-Relay-Client-IP")
	if ip == "" {
		ip = peerAddress(r)
	}

	// NOT trust-gated, deliberately: User-Agent is the client's own header on
	// every path, not an authorize-hop assertion. client_manager.py:236 reads
	// it straight off the request too, with the same "unknown" fallback.
	userAgent := r.Header.Get("User-Agent")
	if userAgent == "" {
		userAgent = "unknown"
	}

	userID := header("X-Relay-User")
	if userID == "" {
		// client_manager.py:241's fallback, on the wire as a STRING.
		userID = "0"
	}

	return id, &channel.Client{
		ID:           clientID,
		UserID:       userID,
		IPAddress:    ip,
		UserAgent:    userAgent,
		OutputFormat: OutputFormatMPEGTS,
		ConnectedAt:  now(),
	}, nil
}

// mintClientID is apps/proxy/authorize.py:145-147's mint_client_id, spelled the
// same way on the wire: client_<unix millis>_<four digits>.
//
// crypto/rand rather than math/rand: gosec reports G404 on math/rand, and the
// id is a handle an admin can stop a client by (DELETE
// /proxy/relay/channels/<id>/clients/<client_id>, 2c-8), so guessability is not
// nothing. Python's random.randint is what it is; matching the FORMAT is the
// parity requirement, matching the generator is not.
func mintClientID(at time.Time) string {
	n, err := rand.Int(rand.Reader, big.NewInt(9000))
	if err != nil {
		// crypto/rand.Reader does not fail on any platform this runs on; if it
		// somehow did, a tune must still get an id rather than a 500.
		n = big.NewInt(0)
	}
	return fmt.Sprintf("client_%d_%d", at.UnixMilli(), 1000+n.Int64())
}

// peerAddress is the untrusted-path client address: the socket's peer, which
// behind a proxy is the proxy. The trusted path carries the real one on
// X-Relay-Client-IP, resolved once by the hop with get_client_ip's
// trusted-proxy rules (parity-matrix row 17).
func peerAddress(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// ErrUnservedKind is returned when the channel's Stream Profile is one this
// relay does not serve yet: Redirect, until 2c-5. 2c-2's ErrNotProxyKind,
// renamed when the transcode kind started being served.
type ErrUnservedKind struct{ Kind string }

func (e *ErrUnservedKind) Error() string {
	return fmt.Sprintf("the Go relay does not serve the %q stream profile yet", e.Kind)
}

// ErrProfileArgvAbsent is returned when the stream profile object carries no
// argv key at all: a control plane older than 2c-4 (spec Amendment A4.1).
// Reported as a contract mismatch, the same class as an absent
// proxy_settings key, and never as a profile problem.
type ErrProfileArgvAbsent struct{ ProfileID int }

func (e *ErrProfileArgvAbsent) Error() string {
	return fmt.Sprintf("stream profile %d carries no argv: the control plane is older than this relay", e.ProfileID)
}

// ErrProfileUnbuildable is returned when Django could not build the
// profile's argv -- argv is null, because shlex refused the parameters
// (an unbalanced quote) -- or the profile has no command. Python fails at
// spawn time on the same profile (build_command raises inside
// _establish_transcode_connection, which returns False); this fails the
// tune before anything is spawned.
type ErrProfileUnbuildable struct{ ProfileID int }

func (e *ErrProfileUnbuildable) Error() string {
	return fmt.Sprintf("stream profile %d cannot be built into a command line", e.ProfileID)
}

// ErrNoFFmpegProfile is returned when a Proxy channel's URL needs ffmpeg
// (HLS, RTSP or UDP) and the answer carries no locked ffmpeg profile.
// Python falls back to the channel's own Proxy profile, whose
// build_command returns [], and spawns nothing (input/manager.py:790-795,
// then :836's posix_spawn of an empty command fails); the outcome is the
// same failed tune, reported here by name.
var ErrNoFFmpegProfile = errors.New("this channel's URL needs ffmpeg and the control plane has no locked ffmpeg profile")

// ErrNoSource is returned when next-source had no candidate.
var ErrNoSource = errors.New("the control plane has no source for this channel")

// startTune makes the one control-plane call a tune needs and builds the
// source from its answer: ProxySource for a Proxy profile, TranscodeSource
// for a transcode one, and TranscodeSource on the locked ffmpeg profile for
// a Proxy profile whose URL is HLS, RTSP or UDP (input/manager.py:445-453's
// force_ffmpeg, decided at connect time there and at tune time here, since
// the URL is known at both).
//
// IT DETACHES FROM THE CALLING CLIENT'S REQUEST CONTEXT, and that is a decision
// fan-out forces rather than a tidy-up. Manager.Attach runs start() behind a
// per-channel gate: the first client in makes the call and every later client
// for that channel waits on the gate. With the caller's own r.Context(), that
// first client closing its tab mid-call cancels next-source for ALL of them --
// they wake, find no channel, and each retries into the same failure. Harmless
// at one client, which is why 2c-2 could ship it; wrong the moment a second
// client can be waiting.
//
// PYTHON DETACHES TOO, by construction rather than by choice. Its tune calls
// generate_stream_url -> control_plane.next_source from inside the client's own
// request greenlet (views.py:340 and :390), and uWSGI does not cancel a
// greenlet when its client hangs up -- the greenlet runs to completion and only
// discovers the disconnect on a later write. So the channel starts, and the
// followers polling _channel_setup_needed attach to it. A Go relay that
// propagated cancellation would be strictly less available than the Python one
// it replaces. (2c-3's startProxyTune, renamed in 2c-4 when it grew the
// transcode branch; the detaching is unchanged.)
//
// context.WithoutCancel keeps any values on the request context while dropping
// its cancellation, and the timeout puts back a bound of the right shape: the
// control client's own worst case rather than the viewer's patience.
func startTune(parent context.Context, client *control.Client, id string) (channel.Started, error) {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(parent), tuneBudget)
	defer cancel()

	answer, err := client.NextSource(ctx, id, control.NextSourceRequest{
		ExcludeStreamIDs: []int{},
		Reason:           "initial",
	})
	if err != nil {
		return channel.Started{}, err
	}
	if answer.Source == nil {
		return channel.Started{}, ErrNoSource
	}

	tuning, readSize, err := tuningFrom(answer.ProxySettings)
	if err != nil {
		return channel.Started{}, err
	}
	// The user agent the Python relay would use: the answer's, or
	// DEFAULT_USER_AGENT when blank (input/manager.py:73's
	// `user_agent or Config.DEFAULT_USER_AGENT`). Off the wire, never a Go
	// literal, and read unconditionally so the per-key test covers it.
	defaultUserAgent, err := answer.ProxySettings.String(settingDefaultUserAgent)
	if err != nil {
		return channel.Started{}, err
	}
	userAgent := answer.Source.UserAgent
	if userAgent == "" {
		userAgent = defaultUserAgent
	}

	// KIND, NEVER TRANSCODE. `transcode` is false for Proxy AND for Redirect
	// (apps/proxy/next_source.py:504), and both locked profiles carry an empty
	// command, so a relay that branched on `transcode` would treat a Redirect
	// channel as Proxy and stream a provider URL that should have been a 302 --
	// silently, and to the wrong architecture. `kind` is the field 2c-1 Task 0
	// added for exactly this.
	var source channel.Source
	switch kind := answer.Source.StreamProfile.Kind; {
	case kind == control.KindProxy && channel.NeedsFFmpeg(answer.Source.URL):
		// force_ffmpeg: the Proxy reader cannot follow a playlist or speak
		// RTSP, so the locked ffmpeg profile plays the URL instead.
		if answer.Source.FFmpegStreamProfile == nil {
			return channel.Started{}, ErrNoFFmpegProfile
		}
		source, err = transcodeSource(answer.Source.FFmpegStreamProfile, answer.Source.URL, userAgent, readSize)
	case kind == control.KindProxy:
		// The defaulted agent here too: Python's HTTP reader sends
		// self.user_agent (input/manager.py:165), which :73 has already
		// defaulted, so a blank user_agent reaches the provider as
		// DEFAULT_USER_AGENT on both architectures. Found by review; the
		// first draft defaulted only the transcode arms, and a blank agent
		// on the Proxy path would have reached a provider as Go's own.
		source = channel.ProxySource{
			URL:       answer.Source.URL,
			UserAgent: userAgent,
			ChunkSize: readSize,
		}
	case kind == control.KindTranscode:
		source, err = transcodeSource(&answer.Source.StreamProfile, answer.Source.URL, userAgent, readSize)
	default:
		return channel.Started{}, &ErrUnservedKind{Kind: kind}
	}
	if err != nil {
		return channel.Started{}, err
	}

	return channel.Started{
		Source: source,
		Tuning: tuning,
		Info: channel.SourceInfo{
			URL:             answer.Source.URL,
			StreamProfileID: answer.Source.StreamProfile.ID,
			StreamID:        answer.Source.StreamID,
			StreamName:      answer.Source.StreamName,
			ChannelName:     answer.Source.ChannelName,
			M3UProfileID:    answer.Source.M3UProfileID,
			M3UProfileName:  answer.Source.M3UProfileName,
		},
	}, nil
}

// transcodeSource builds the transcode architecture's source from a profile
// object whose argv Django built. The three states of argv are the three
// outcomes: a list is spawned, null cannot be built, and an absent key is a
// control plane older than this relay (control.StreamProfileRef).
func transcodeSource(profile *control.StreamProfileRef, url, userAgent string, readSize int) (channel.Source, error) {
	if !profile.ArgvPresent {
		return nil, &ErrProfileArgvAbsent{ProfileID: profile.ID}
	}
	if profile.Argv == nil || profile.Command == "" {
		return nil, &ErrProfileUnbuildable{ProfileID: profile.ID}
	}
	return &channel.TranscodeSource{
		Command:   profile.Command,
		Argv:      profile.Argv,
		URL:       url,
		UserAgent: userAgent,
		ChunkSize: readSize,
	}, nil
}

// writeTuneFailure turns a tune error into a status. It never echoes the error
// text to the client: a control-plane message can name a variable, and a
// source URL carries provider credentials.
func writeTuneFailure(w http.ResponseWriter, log *slog.Logger, id string, err error) {
	var unserved *ErrUnservedKind
	var argvAbsent *ErrProfileArgvAbsent
	var unbuildable *ErrProfileUnbuildable
	var unsupported *ErrUnsupportedOutput
	var refused *control.Refused
	var unavailable *control.Unavailable
	var misconfigured *control.ErrNotConfigured
	var absent *control.ErrSettingAbsent

	switch {
	case errors.As(err, &unserved):
		log.Warn("refusing a tune for an unsupported stream profile", "channel", id, "kind", unserved.Kind)
		http.Error(w, "this stream profile is not served yet", http.StatusNotImplemented)
	case errors.As(err, &argvAbsent):
		// The same class as an absent proxy_settings key, and the same
		// status: the control plane predates this relay.
		log.Error("the control plane sent a stream profile with no argv", "channel", id, "profile", argvAbsent.ProfileID)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
	case errors.As(err, &unbuildable):
		log.Error("the stream profile cannot be built into a command line", "channel", id, "profile", unbuildable.ProfileID)
		http.Error(w, "stream profile cannot be built", http.StatusServiceUnavailable)
	case errors.Is(err, ErrNoFFmpegProfile):
		log.Error("the channel's URL needs ffmpeg and no locked ffmpeg profile is installed", "channel", id)
		http.Error(w, "no ffmpeg profile for this stream", http.StatusServiceUnavailable)
	case errors.As(err, &unsupported):
		log.Warn("refusing a tune for an unsupported output",
			"channel", id, "format", unsupported.Format, "output_profile", unsupported.ProfileID)
		http.Error(w, "this output is not served yet", http.StatusNotImplemented)
	case errors.Is(err, channel.ErrDuplicateClient):
		// views.py:748-753's 503: a client id already attached to this channel
		// is a client that never released, not a new viewer.
		log.Warn("refusing a duplicate client id", "channel", id)
		http.Error(w, "failed to register client", http.StatusServiceUnavailable)
	case errors.Is(err, ErrNoSource):
		log.Info("no source available", "channel", id)
		http.Error(w, "no source available", http.StatusServiceUnavailable)
	case errors.As(err, &absent):
		log.Error("the control plane sent incomplete proxy_settings", "channel", id, "key", absent.Key)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
	case errors.As(err, &misconfigured):
		// The variable name only, never the value: a control-plane URL can
		// carry userinfo.
		log.Error("the control-plane address is misconfigured", "variable", misconfigured.Variable)
		http.Error(w, "control plane misconfigured", http.StatusInternalServerError)
	case errors.As(err, &refused):
		log.Error("the control plane refused the tune", "channel", id, "status", refused.Status)
		http.Error(w, "control plane refused", http.StatusBadGateway)
	case errors.As(err, &unavailable):
		log.Error("the control plane is unreachable", "channel", id, "reason", unavailable.Reason)
		http.Error(w, "control plane unreachable", http.StatusBadGateway)
	default:
		log.Error("the tune failed", "channel", id, "error", redact.Error(err))
		http.Error(w, "tune failed", http.StatusInternalServerError)
	}
}

// serveClient is the client loop: position once, then read, write, wait.
//
// NO KEEPALIVE PACKETS AND NO CLIENT TIMEOUT, and both omissions are parity
// rather than scope-cutting. Python sends a keepalive only when
// _should_send_keepalive says so, and that requires the owner's
// stream_manager.healthy to be FALSE (output/ts/generator.py:546-551);
// _is_timeout likewise disconnects only when the same flag is false (:592).
// Nothing lowers that flag except the health monitor and the failover
// machinery, which are 2c-5's. The error packets at :209-250 are the other
// half of the same story: every one of them is inside
// _wait_for_initialization, the path a follower takes while another worker
// elects itself owner -- deleted outright by D2, not ported.
//
// AND NO GHOST-CLIENT DISCONNECT. output/ts/generator.py:579-581's
// _is_ghost_client needs consecutive_empty > 100 AND the buffer 50 chunks
// ahead of the client at the same instant -- a client 50 chunks behind whose
// chunks exist is fed on its next read, which resets consecutive_empty, so the
// two conditions are mutually exclusive outside the expiry window
// find_oldest_available_chunk already recovers from. Not ported, and the
// reason is that it is unreachable rather than that it is 2c-5's.
func serveClient(
	ctx context.Context,
	w http.ResponseWriter,
	rc *http.ResponseController,
	ch *channel.Channel,
	client *channel.Client,
	log *slog.Logger,
) {
	tuning := ch.Tuning()
	ring := ch.Ring()

	// POSITIONED ONCE, at setup, exactly as output/ts/generator.py:264-302
	// positions a client -- and this is the call parity-matrix row 8 is
	// about, because from 2c-3 onward the ring the client joins is usually
	// one ANOTHER client has been filling. A JoinBehind of zero means the
	// live head, which is what new_client_behind_seconds = 0 means there.
	cursor := ring.Head()
	if tuning.JoinBehind > 0 {
		cursor = ring.Join(tuning.JoinBehind)
	}

	for {
		chunks, next, skipped := ring.Read(cursor)
		if skipped > 0 {
			// The jump find_oldest_available_chunk performs
			// (input/buffer.py:407-452): the client fell behind past
			// retention, so it resumes at the oldest resident chunk with a gap
			// in its stream. Logged, never a disconnect -- Python does not
			// disconnect such a client either.
			log.Warn("client fell behind the ring",
				"channel", ch.ID(), "client", client.ID,
				"skipped", skipped, "head", ring.Head())
		}
		if len(chunks) > 0 {
			cursor = next
			if !writeChunks(w, rc, chunks) {
				return
			}
			continue
		}

		err := ring.Wait(ctx, cursor)
		if err == nil {
			continue
		}
		if errors.Is(err, buffer.ErrClosed) {
			// One last read. The writer may have published between the Read
			// above and Close, and without this the tail of a stream that
			// ended cleanly is dropped.
			if final, _, _ := ring.Read(cursor); len(final) > 0 {
				writeChunks(w, rc, final)
			}
		}
		return
	}
}

// writeChunks writes and flushes, reporting whether the client is still there.
// A write error is an ordinary client disconnect and is not logged: one line
// per viewer leaving would bury everything else.
func writeChunks(w http.ResponseWriter, rc *http.ResponseController, chunks [][]byte) bool {
	for _, data := range chunks {
		// #nosec G705 -- this is the video path. gosec's taint analysis sees
		// bytes from an outbound HTTP response reaching w.Write and reports a
		// cross-site-scripting risk; the bytes are an MPEG-TS stream served as
		// video/mp2t, the response carries no HTML context, and copying
		// provider bytes to a viewer is the only thing this process exists to
		// do. Re-linted after adding this: no further rule fires on the line,
		// unlike the G304/G703 pair in 2c-1's secret reader.
		if _, err := w.Write(data); err != nil {
			return false
		}
	}
	return rc.Flush() == nil
}
