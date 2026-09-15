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
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/output"
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

	// Probe is the HTTP client validate_stream_url's port probes a Redirect
	// channel's provider with. Nil means one built from probeTimeout that
	// follows redirects, as requests does there.
	Probe *http.Client

	// Lifecycle is the drain flag. A tune that arrives after SIGTERM is
	// refused rather than started: D6's "stops accepting tunes". Nil is
	// never draining, which is every test that is not about the drain.
	Lifecycle *Lifecycle

	// Remux is the process an fMP4 tune spawns. Its zero value is the
	// production remux (output.RemuxCommand and output.RemuxArgv), which is
	// what main.go leaves it as; a test substitutes a stand-in. It is on
	// StreamDeps rather than on channel.ManagerConfig because it is a property
	// of what this handler serves, not of how a channel is owned -- and 2c-7's
	// Output Profile command arrives the same way.
	Remux output.Remux
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

	// The failover thresholds and the client-loop values 2c-5 reads
	// (channel.Tuning names each one's Python line).
	settingConnectionTimeout   = "CONNECTION_TIMEOUT"
	settingHealthCheckInterval = "HEALTH_CHECK_INTERVAL"
	settingInitGracePeriod     = "channel_init_grace_period"
	settingMaxRetries          = "MAX_RETRIES"
	settingRetryWindow         = "RETRY_WINDOW_SECONDS"
	settingStableThreshold     = "STABLE_CONNECTION_THRESHOLD"
	settingMaxStreamSwitches   = "MAX_STREAM_SWITCHES"
	settingStreamTimeout       = "STREAM_TIMEOUT"
	settingFailoverGrace       = "FAILOVER_GRACE_PERIOD"
	settingKeepaliveInterval   = "KEEPALIVE_INTERVAL"
	settingMaxKeepalive        = "MAX_KEEPALIVE_DURATION"
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
	if t.ConnectionTimeout, err = s.Seconds(settingConnectionTimeout); err != nil {
		return t, 0, err
	}
	if t.HealthCheckInterval, err = s.Seconds(settingHealthCheckInterval); err != nil {
		return t, 0, err
	}
	if t.InitGracePeriod, err = s.Seconds(settingInitGracePeriod); err != nil {
		return t, 0, err
	}
	if t.MaxRetries, err = s.Int(settingMaxRetries); err != nil {
		return t, 0, err
	}
	if t.RetryWindow, err = s.Seconds(settingRetryWindow); err != nil {
		return t, 0, err
	}
	if t.StableThreshold, err = s.Seconds(settingStableThreshold); err != nil {
		return t, 0, err
	}
	if t.MaxStreamSwitches, err = s.Int(settingMaxStreamSwitches); err != nil {
		return t, 0, err
	}
	// _is_timeout's total_timeout is the SUM of two settings
	// (output/ts/generator.py:585-587); both are read, one field holds it.
	streamTimeout, err := s.Seconds(settingStreamTimeout)
	if err != nil {
		return t, 0, err
	}
	failoverGrace, err := s.Seconds(settingFailoverGrace)
	if err != nil {
		return t, 0, err
	}
	t.ClientTimeout = streamTimeout + failoverGrace
	if t.KeepaliveInterval, err = s.Seconds(settingKeepaliveInterval); err != nil {
		return t, 0, err
	}
	if t.MaxKeepalive, err = s.Seconds(settingMaxKeepalive); err != nil {
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
// (`output_format or 'mpegts'`). The other one this relay serves is
// output.FormatFMP4, from 2c-6; it is named in that package because the
// pipeline that produces it is keyed on it.
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
		if deps.Lifecycle.Draining() {
			// FIRST, before the channel is even identified: a tune started
			// now would be torn down seconds later by the drain that is
			// already running, after reserving a provider slot Django would
			// then have to see released. 503 rather than 500 because the
			// condition is temporary and naming it that way is what lets a
			// client retry into the replacement process.
			w.Header().Set("Retry-After", "1")
			http.Error(w, "the relay is shutting down", http.StatusServiceUnavailable)
			return
		}
		// D5, exception 2: with no nginx there is no auth_request, and a Go
		// process cannot import authorize_stream, so the decision is asked
		// for over HTTP. On every ordinary nginx-fronted tune this returns
		// (nil, nil) without a round trip, matching the frequency of the
		// Python relay's own inline fallback -- which is to say never, in
		// production.
		decision, err := authorizeTune(r, deps, log)
		if err != nil {
			writeAuthorizeFailure(w, log, err)
			return
		}
		id, client, err := identify(r, deps.Secret, now, decision)
		if err != nil {
			writeTuneFailure(w, log, id, err)
			return
		}
		if id == "" {
			http.Error(w, "no channel in the request", http.StatusBadRequest)
			return
		}
		// request_is_internal (apps/proxy/internal_auth.py): the DVR's own
		// fetch carries the static X-Dispatcharr-Internal and no bound
		// counterpart, and views.py:461 reads it off the decision to keep a
		// Redirect channel from 302ing that header to a provider.
		internal := control.IsInternalPrincipal(deps.Secret, r.Header.Get(control.HeaderInternal))

		ch, release, err := deps.Channels.Attach(id, client, func() (channel.Started, error) {
			return startTune(r.Context(), tuneDeps{control: deps.Control, probe: deps.Probe, log: log}, id, internal)
		})
		if err != nil {
			var redirect *redirectAnswer
			if errors.As(err, &redirect) {
				// The Redirect architecture: no channel, no ring, no bytes
				// (views.py:526-540). HttpResponseRedirect's 302 for an HTTP
				// URL, a hand-built 301 for rtsp/rtp/udp, which Django's
				// redirect class refuses.
				log.Info("redirecting the client to the provider", "channel", id, "status", redirect.Status)
				w.Header().Set("Location", redirect.Location)
				w.WriteHeader(redirect.Status)
				return
			}
			writeTuneFailure(w, log, id, err)
			return
		}
		defer release()

		// From here down the request's context also ends when an admin
		// stops THIS client: DELETE /proxy/relay/channels/<id>/clients/<cid>
		// closes the signal Channel.StopClient owns, which is the in-memory
		// form of the stop key ChannelService.stop_client SETEXes and the
		// generator's loop polls (output/ts/generator.py:307-318). Applied
		// to the request rather than to one call so both output formats
		// inherit it -- one mechanism, and neither loop can be the one that
		// forgot.
		stopCtx, stopCancel := stopContext(r.Context(), client)
		defer stopCancel()
		r = r.WithContext(stopCtx)

		// views.py:765-776, BEFORE the format branch and in that order: the
		// Output Profile transcode is started (or joined) first, and the
		// buffer everything below reads is get_buffer(channel, profile) --
		// the profile's output ring when one is running, the channel's own
		// when none is. 2c-7.
		source, releaseProfile, ok := attachOutputProfile(w, ch, client, log)
		if !ok {
			return
		}
		defer releaseProfile()

		// views.py:789-818's branch, at the same point: after the channel is
		// up and the client is registered, and on the client's OWN resolved
		// format rather than on anything about the channel -- a TS viewer and
		// an fMP4 viewer share one channel, one upstream and one ring, and
		// differ only from here down.
		if client.OutputFormat == output.FormatFMP4 {
			serveFMP4(w, r, deps, ch, client, source, log)
			return
		}

		w.Header().Set("Content-Type", "video/mp2t")
		w.Header().Set("Cache-Control", "no-cache")
		w.WriteHeader(http.StatusOK)
		rc := http.NewResponseController(w)
		if err := rc.Flush(); err != nil {
			return
		}

		// client_connect, at _setup_streaming's own success point
		// (output/ts/generator.py:129-143): after the channel is up and the
		// response has begun, before the streaming loop.
		emitClientConnect(ch, client)
		serveClient(r.Context(), w, rc, ch, source, client, log)
		// client_disconnect, from the generator's cleanup (:651-667). TS
		// only -- the fMP4 generator raises none, and that asymmetry is
		// reproduced (clientevents.go).
		emitClientDisconnect(ch, client, now())
	}
}

// ErrUnsupportedOutput is returned when the authorize hop asked for an output
// format or an Output Profile this relay does not serve.
//
// Refused rather than served, for 2c-2's reason on stream_profile.kind: a
// relay that logged "fmp4" in its registry and then wrote MPEG-TS would be
// wrong in a way nothing on the wire says, and serving it under the label
// "mpegts" would be a lie in the payload /proxy/stats/ renders. 2c-6 brought
// fMP4 and 2c-7 the Output Profiles, so this now only ever names a format
// NEITHER implementation has -- `hls`, whose Python manager does not exist
// either (_OUTPUT_FORMAT_MANAGERS registers only fmp4, server.py:1352-1353).
// ProfileID is kept on the struct and is never set: it is what the 501's log
// line named for two stages and removing it would silently narrow the
// message.
type ErrUnsupportedOutput struct {
	Format    string
	ProfileID string
}

func (e *ErrUnsupportedOutput) Error() string {
	if e.ProfileID != "" {
		return fmt.Sprintf("the Go relay serves no Output Profile yet, and this tune asked for %q", e.ProfileID)
	}
	return fmt.Sprintf("the Go relay serves only %q and %q, not %q", OutputFormatMPEGTS, output.FormatFMP4, e.Format)
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
func identify(r *http.Request, secret string, now func() time.Time, decision *control.Decision) (string, *channel.Client, error) {
	trusted := control.IsRelayTrusted(secret, r.Header.Get(control.HeaderAuthorized))

	header := func(name string) string {
		// A decision from the dev fallback answers in the hop's place: the
		// same seven values, resolved by the same authorize_stream() call,
		// arriving as a response rather than as request headers. Checked
		// FIRST, so a request that carried no valid marker can never fall
		// back to reading its own headers -- the two sources are exclusive
		// by construction and never merged.
		if decision != nil {
			return decisionHeader(decision, name)
		}
		if !trusted {
			return ""
		}
		return r.Header.Get(name)
	}

	id := header("X-Relay-Channel")
	if id == "" {
		id = r.PathValue("channelID")
	}

	// 2c-7: X-Relay-Output is SERVED rather than refused. Its value is the
	// OutputProfile primary key apps/proxy/authorize.py:483-488 resolved, and
	// apps/proxy/authorize_views.py:154-162 has already rejected anything but
	// "" or a digit string with a 403 -- so a non-digit here means the
	// internal contract is broken and never reaches a deployment through
	// nginx. Refused with a 400 rather than guessed at: there is no Python
	// counterpart to reproduce, because Python's hop denies it a hop earlier.
	//
	// WHAT IS RECORDED HERE IS WHAT THE HOP ASKED FOR, not what the tune ends
	// up serving. The set that resolves it is the channel's, and the channel
	// does not exist yet; attachOutputProfile corrects this to null on the
	// one path where the two differ.
	var outputProfileID *int
	if profileID := header("X-Relay-Output"); profileID != "" {
		parsed, convErr := strconv.Atoi(profileID)
		if convErr != nil || parsed <= 0 {
			return id, nil, &ErrOutputProfileMalformed{Value: profileID}
		}
		outputProfileID = &parsed
	}
	// 2c-6: fmp4 joins mpegts. Anything else is still refused rather than
	// served under a label that is not true -- and there is no third format to
	// refuse today (_OUTPUT_FORMAT_MANAGERS registers only fmp4,
	// server.py:1352-1353, and apps/proxy/hls_proxy/ is dead and unrouted).
	outputFormat := OutputFormatMPEGTS
	if format := header("X-Relay-Output-Format"); format != "" {
		if format != OutputFormatMPEGTS && format != output.FormatFMP4 {
			return id, nil, &ErrUnsupportedOutput{Format: format}
		}
		outputFormat = format
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
		ID:              clientID,
		UserID:          userID,
		IPAddress:       ip,
		UserAgent:       userAgent,
		OutputFormat:    outputFormat,
		OutputProfileID: outputProfileID,
		ConnectedAt:     now(),
	}, nil
}

// stopContext ends when the request ends OR when an admin stops this client.
//
// A goroutine rather than context.AfterFunc because the trigger is a channel
// close, not a parent context; it returns as soon as either side fires, and
// the caller's deferred cancel guarantees the second one always does.
func stopContext(parent context.Context, client *channel.Client) (context.Context, context.CancelFunc) {
	stop := client.Stopped()
	if stop == nil {
		// A client that never reached the registry cannot be stopped by id,
		// so there is nothing to watch and no goroutine to start.
		return parent, func() {}
	}
	ctx, cancel := context.WithCancel(parent)
	go func() {
		select {
		case <-stop:
			cancel()
		case <-ctx.Done():
		}
	}()
	return ctx, cancel
}

// ErrOutputProfileMalformed is an X-Relay-Output that is not a positive
// integer on a trusted request. Unreachable through nginx -- the authorize
// hop answers 403 for it (apps/proxy/authorize_views.py:154-162) -- and
// answered 400 rather than 403 here because it is this relay saying the
// header it was handed is not a profile id, not an authorization decision.
type ErrOutputProfileMalformed struct{ Value string }

func (e *ErrOutputProfileMalformed) Error() string {
	return fmt.Sprintf("X-Relay-Output is %q, which is not an Output Profile id", e.Value)
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

// ErrUnservedKind is returned when the channel's Stream Profile kind is one
// this relay does not know: not proxy, transcode or redirect, which since
// 2c-5 are all served, so only a control plane newer than this relay can
// produce it. 2c-2's ErrNotProxyKind, renamed when the transcode kind
// started being served.
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
// tuneDeps is what startTune needs beyond the request: the control client,
// the Redirect probe and a logger.
type tuneDeps struct {
	control *control.Client
	probe   *http.Client
	log     *slog.Logger
}

func startTune(parent context.Context, deps tuneDeps, id string, internal bool) (channel.Started, error) {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(parent), tuneBudget)
	defer cancel()
	client := deps.control

	answer, err := client.NextSource(ctx, id, control.NextSourceRequest{
		ExcludeStreamIDs: []int{},
		Reason:           "initial",
		// generate_stream_url asks for the alternates on the initial call
		// (url_utils.py:55-58) and caches them for the degraded fallback and
		// the Redirect fall-through; 2c-2 did not ask, having neither.
		IncludeAlternates: true,
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
	kind := answer.Source.StreamProfile.Kind
	switch kind {
	case control.KindProxy, control.KindTranscode:
	case control.KindRedirect:
		if !internal {
			// views.py:468-547: probe, fall through the cached alternates,
			// release the slot, and hand the client the provider URL.
			return channel.Started{}, redirectTune(ctx, deps, id, answer, defaultUserAgent)
		}
		// views.py:462-467: an internal principal (the DVR) on a Redirect
		// channel is served through Proxy instead, because ffmpeg re-sends
		// its -headers line -- X-Dispatcharr-Internal included -- to
		// whatever a 302 names. `transcode` is forced False there; here the
		// kind is read as Proxy from this point on, force_ffmpeg included.
		deps.log.Info("internal principal on a Redirect-profile channel: serving via Proxy", "channel", id)
		kind = control.KindProxy
	default:
		return channel.Started{}, &ErrUnservedKind{Kind: kind}
	}

	build := sourceBuilder{kind: kind, userAgent: userAgent, readSize: readSize}
	source, err := build.source(answer.Source)
	if err != nil {
		return channel.Started{}, err
	}

	return channel.Started{
		Source:         source,
		Tuning:         tuning,
		Info:           infoFrom(answer.Source),
		OutputProfiles: outputProfilesFrom(answer),
		Resolver: &resolver{
			control:    client,
			id:         id,
			build:      build,
			alternates: answer.Alternates,
			log:        deps.log,
		},
	}, nil
}

// infoFrom is what the status endpoints render about a source.
func infoFrom(source *control.Source) channel.SourceInfo {
	return channel.SourceInfo{
		URL:             source.URL,
		StreamProfileID: source.StreamProfile.ID,
		StreamID:        source.StreamID,
		StreamName:      source.StreamName,
		ChannelName:     source.ChannelName,
		M3UProfileID:    source.M3UProfileID,
		M3UProfileName:  source.M3UProfileName,
	}
}

// sourceBuilder turns a control.Source into the Source that plays it, for
// the initial tune and for every failover candidate after it: the kind is
// the channel's profile and never changes across candidates (the answer's
// stream_profile is the channel's, apps/proxy/next_source.py:609-622), the
// user agent is defaulted once (input/manager.py:73), and force_ffmpeg is
// decided per candidate from its own URL (:445-453, on every pass of the
// main loop).
type sourceBuilder struct {
	kind      string
	userAgent string
	readSize  int
}

func (b sourceBuilder) source(candidate *control.Source) (channel.Source, error) {
	userAgent := candidate.UserAgent
	if userAgent == "" {
		userAgent = b.userAgent
	}
	switch {
	case b.kind == control.KindProxy && channel.NeedsFFmpeg(candidate.URL):
		// force_ffmpeg: the Proxy reader cannot follow a playlist or speak
		// RTSP, so the locked ffmpeg profile plays the URL instead.
		if candidate.FFmpegStreamProfile == nil {
			return nil, ErrNoFFmpegProfile
		}
		return transcodeSource(candidate.FFmpegStreamProfile, candidate.URL, userAgent, b.readSize)
	case b.kind == control.KindProxy:
		// The defaulted agent here too: Python's HTTP reader sends
		// self.user_agent (input/manager.py:165), which :73 has already
		// defaulted, so a blank user_agent reaches the provider as
		// DEFAULT_USER_AGENT on both architectures. Found by review; the
		// first draft defaulted only the transcode arms, and a blank agent
		// on the Proxy path would have reached a provider as Go's own.
		return channel.ProxySource{
			URL:       candidate.URL,
			UserAgent: userAgent,
			ChunkSize: b.readSize,
		}, nil
	case b.kind == control.KindTranscode:
		return transcodeSource(&candidate.StreamProfile, candidate.URL, userAgent, b.readSize)
	}
	return nil, &ErrUnservedKind{Kind: b.kind}
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
	var malformedProfile *ErrOutputProfileMalformed
	var refused *control.Refused
	var unavailable *control.Unavailable
	var misconfigured *control.ErrNotConfigured
	var absent *control.ErrSettingAbsent

	switch {
	case errors.Is(err, ErrRedirectValidationFailed):
		// views.py:542-547: JsonResponse({"error": ...}, status=502).
		log.Error("every redirect candidate failed validation", "channel", id)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(`{"error": "All available streams failed validation"}`))
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
	case errors.As(err, &malformedProfile):
		// The value is NOT echoed: an internal header this relay was handed
		// is not something to reflect into a response body.
		log.Error("X-Relay-Output is not an Output Profile id", "channel", id)
		http.Error(w, "malformed output profile", http.StatusBadRequest)
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

// keepaliveAfterEmptyReads is _should_send_keepalive's `consecutive_empty < 5`
// (output/ts/generator.py:546): a client at the head of an unhealthy channel
// receives keepalives only once five successive reads have found nothing.
const keepaliveAfterEmptyReads = 5

// serveClient is the client loop: position once, then read, write, wait --
// the port of _stream_data_generator (output/ts/generator.py:325-420) with
// its two health-gated mechanisms, both of which 2c-2 and 2c-3 left out
// because nothing could lower the flag they are gated on until 2c-5's
// health monitor arrived:
//
//   - KEEPALIVES (:371-389, :542-551): a client waiting at the buffer head
//     of an UNHEALTHY channel, after five empty reads, is sent one null TS
//     packet every KeepaliveInterval, each refreshing its last-yield time,
//     for at most MaxKeepalive of wall clock, after which it is dropped.
//   - THE CLIENT TIMEOUT (:583-604): a client with no yielded chunk for
//     ClientTimeout on an UNHEALTHY channel is dropped. Its url_switching
//     exemption (:593-596) is not ported -- see the branch itself for why.
//     Row 12's Notes record what this means on the TS path:
//     the keepalives refresh the very timer this reads, so on a channel
//     that is unhealthy for long enough to reach it, it is the keepalive cap
//     that actually ends the client. Ported as it is, because it is the
//     condition Python evaluates; pinned through the cap, because that is
//     the exit a client can reach.
//
// The standard wait (:400-403) sleeps min(0.1 * consecutive_empty, 1.0) and
// re-checks; here Ring.Wait is bounded by the same backoff so the health
// flag is re-read at Python's cadence, and each timeout counts as one empty
// read.
//
// THE ERROR PACKET (:235-239, utils.py:71-98): a client that has received
// NOTHING when its channel ends in error is handed one 188-byte packet
// carrying "Error: <message>" before the body closes -- what the first
// client of a channel whose every source failed sees in Python (row 3's own
// pin reads it), and what Amendment A2.5 recorded 2c-2 as not sending. A
// client already streaming when the channel errors gets a closed body and
// no packet, as _check_resources gives it (:455-459). The initialization
// timeout packet (:249-251, after CLIENT_WAIT_TIMEOUT with no ready state)
// is NOT ported: this relay has no initializing wait a client can time out
// in, and a channel whose source never delivers is ended by the health
// monitor's init grace period instead.
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
	ring *buffer.Ring,
	client *channel.Client,
	log *slog.Logger,
) {
	tuning := ch.Tuning()

	// POSITIONED ONCE, at setup, exactly as output/ts/generator.py:264-302
	// positions a client -- and this is the call parity-matrix row 8 is
	// about, because from 2c-3 onward the ring the client joins is usually
	// one ANOTHER client has been filling. A JoinBehind of zero means the
	// live head, which is what new_client_behind_seconds = 0 means there.
	cursor := ring.Head()
	if tuning.JoinBehind > 0 {
		cursor = ring.Join(tuning.JoinBehind)
	}

	var sent int
	lastYield := time.Now()
	var keepaliveStart time.Time
	empties := 0
	for {
		if ctx.Err() != nil {
			// The admin stop and the client hang-up both land here. Checked
			// at the top of every pass rather than only inside the wait,
			// because a ring that always has data never reaches the wait --
			// which is exactly the busy channel an admin is most likely to
			// be stopping a client on. Python polls its stop key here
			// (output/ts/generator.py:307-318).
			return
		}
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
			at := time.Now()
			for _, c := range chunks {
				sent += len(c)
				// ONE CALL PER CHUNK, not one per Read: current_rate_KBps is
				// the rate over the gap between consecutive chunks
				// (output/ts/generator.py:477-499 increments inside its own
				// `for chunk in chunks` loop), so batching them here would
				// report a rate over a window Python never measures.
				client.Sent(len(c), at)
			}
			lastYield = at
			keepaliveStart = time.Time{}
			empties = 0
			continue
		}

		empties++
		wait := min(time.Duration(empties)*100*time.Millisecond, time.Second)
		if !ch.Healthy() && empties >= keepaliveAfterEmptyReads {
			if keepaliveStart.IsZero() {
				keepaliveStart = time.Now()
			}
			if time.Since(keepaliveStart) > tuning.MaxKeepalive {
				log.Warn("keepalive duration exceeded with no stream recovery, disconnecting",
					"channel", ch.ID(), "client", client.ID, "max", tuning.MaxKeepalive)
				return
			}
			if !writeChunks(w, rc, [][]byte{signalPacket("")}) {
				return
			}
			sent += buffer.TSPacketSize
			// A keepalive counts toward bytes_sent (:392) and refreshes
			// last_active (:395-397), both of which Sent does.
			lastYield = time.Now()
			client.Sent(buffer.TSPacketSize, lastYield)
			wait = tuning.KeepaliveInterval
		} else if time.Since(lastYield) > tuning.ClientTimeout && !ch.Healthy() {
			// _is_timeout (:583-604) minus its url_switching exemption
			// (:593-596), which is not ported: url_switching is true only
			// inside update_url's own body (input/manager.py:1476-1540), a
			// window of at most the old process's kill-and-join, and a
			// client reprieved there is dropped on its next poll anyway.
			log.Warn("no data and the stream is unhealthy, disconnecting",
				"channel", ch.ID(), "client", client.ID, "timeout", tuning.ClientTimeout)
			return
		}

		waitCtx, cancel := context.WithTimeout(ctx, max(wait, time.Millisecond))
		err := ring.Wait(waitCtx, cursor)
		cancel()
		switch {
		case err == nil:
			continue
		case errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
			// One empty read; round again.
			continue
		case errors.Is(err, buffer.ErrClosed):
			// One last read. The writer may have published between the Read
			// above and Close, and without this the tail of a stream that
			// ended cleanly is dropped.
			if final, _, _ := ring.Read(cursor); len(final) > 0 {
				writeChunks(w, rc, final)
				sent += len(final[0])
				client.Sent(len(final[0]), time.Now())
			}
			if sent == 0 {
				if message := errorPacketMessage(ch); message != "" {
					writeChunks(w, rc, [][]byte{signalPacket(message)})
				}
			}
		}
		return
	}
}

// errorPacketMessage is the text _wait_for_initialization puts in the error
// packet for a channel that ended before the client's first byte
// (output/ts/generator.py:235-239): the error message the channel recorded,
// "Unknown error" when a stopped channel recorded none, and nothing for a
// channel that is still running.
func errorPacketMessage(ch *channel.Channel) string {
	switch ch.State() {
	case channel.StateError:
		var exhausted *channel.ErrSourcesExhausted
		if errors.As(ch.Err(), &exhausted) {
			return "Error: " + exhausted.Message()
		}
		return "Error: Unknown error"
	case channel.StateStopped, channel.StateStopping:
		return "Error: Unknown error"
	}
	return ""
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
