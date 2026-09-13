package httpapi

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
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
}

// The proxy_settings keys this PR reads. Named constants rather than literals
// at the call site, so a rename on the wire is one edit and a typo is a
// compile error rather than a runtime ErrSettingAbsent.
const (
	settingChunkBytes = "BUFFER_CHUNK_SIZE"
	settingRetention  = "redis_chunk_ttl"
	settingJoinBehind = "new_client_behind_seconds"
	settingReadSize   = "CHUNK_SIZE"
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
	readSize, err := s.Int(settingReadSize)
	if err != nil {
		return t, 0, err
	}
	return t, readSize, nil
}

// StreamHandler serves GET /proxy/ts/stream/{channelID}.
func StreamHandler(deps StreamDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}

	return func(w http.ResponseWriter, r *http.Request) {
		id := channelIDFor(r, deps.Secret)
		if id == "" {
			http.Error(w, "no channel in the request", http.StatusBadRequest)
			return
		}

		ch, release, err := deps.Channels.Attach(id, func() (channel.Source, channel.Tuning, error) {
			return startProxyTune(r.Context(), deps.Control, id)
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

		serveClient(r.Context(), w, rc, ch, log)
	}
}

// channelIDFor resolves which channel this request is for.
//
// X-Relay-Channel is the uuid the authorize hop resolved, and it is read ONLY
// when X-Dispatcharr-Authorized proves nginx put it there. Without that check
// any client could name any channel by hand and bypass whatever the hop
// decided -- that marker is the entire reason apps/proxy/authorize.py can be
// the only place the decision is made. An untrusted request falls back to the
// path value, which is the dev shape: this route is dev-gated, and 2c-8 brings
// the POST /_dispatcharr/authorize-internal fallback that authorizes it.
//
// The four other X-Relay-* headers are deliberately not read. X-Relay-Output
// and X-Relay-Output-Format select an Output Profile and an output format, and
// this PR serves MPEG-TS passthrough only (2c-6, 2c-7). X-Relay-Client and
// X-Relay-Client-IP identify a client in the registry, and this PR has no
// registry (2c-3).
func channelIDFor(r *http.Request, secret string) string {
	if control.IsRelayTrusted(secret, r.Header.Get(control.HeaderAuthorized)) {
		if resolved := r.Header.Get("X-Relay-Channel"); resolved != "" {
			return resolved
		}
	}
	return r.PathValue("channelID")
}

// ErrNotProxyKind is returned when the channel's Stream Profile is not Proxy.
type ErrNotProxyKind struct{ Kind string }

func (e *ErrNotProxyKind) Error() string {
	return fmt.Sprintf("the Go relay serves only the %q stream profile so far, not %q",
		control.KindProxy, e.Kind)
}

// ErrNoSource is returned when next-source had no candidate.
var ErrNoSource = errors.New("the control plane has no source for this channel")

// startProxyTune makes the one control-plane call a tune needs and builds the
// source from its answer.
func startProxyTune(ctx context.Context, client *control.Client, id string) (channel.Source, channel.Tuning, error) {
	answer, err := client.NextSource(ctx, id, control.NextSourceRequest{
		ExcludeStreamIDs: []int{},
		Reason:           "initial",
	})
	if err != nil {
		return nil, channel.Tuning{}, err
	}
	if answer.Source == nil {
		return nil, channel.Tuning{}, ErrNoSource
	}

	// KIND, NEVER TRANSCODE. `transcode` is false for Proxy AND for Redirect
	// (apps/proxy/next_source.py:504), and both locked profiles carry an empty
	// command, so a relay that branched on `transcode` would treat a Redirect
	// channel as Proxy and stream a provider URL that should have been a 302 --
	// silently, and to the wrong architecture. `kind` is the field 2c-1 Task 0
	// added for exactly this, and this is its first consumer.
	if kind := answer.Source.StreamProfile.Kind; kind != control.KindProxy {
		return nil, channel.Tuning{}, &ErrNotProxyKind{Kind: kind}
	}

	tuning, readSize, err := tuningFrom(answer.ProxySettings)
	if err != nil {
		return nil, channel.Tuning{}, err
	}

	return channel.ProxySource{
		URL:       answer.Source.URL,
		UserAgent: answer.Source.UserAgent,
		ChunkSize: readSize,
	}, tuning, nil
}

// writeTuneFailure turns a tune error into a status. It never echoes the error
// text to the client: a control-plane message can name a variable, and a
// source URL carries provider credentials.
func writeTuneFailure(w http.ResponseWriter, log *slog.Logger, id string, err error) {
	var notProxy *ErrNotProxyKind
	var refused *control.Refused
	var unavailable *control.Unavailable
	var misconfigured *control.ErrNotConfigured
	var absent *control.ErrSettingAbsent

	switch {
	case errors.As(err, &notProxy):
		log.Warn("refusing a tune for an unsupported stream profile", "channel", id, "kind", notProxy.Kind)
		http.Error(w, "this stream profile is not served yet", http.StatusNotImplemented)
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
		log.Error("the tune failed", "channel", id, "error", err)
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
func serveClient(
	ctx context.Context,
	w http.ResponseWriter,
	rc *http.ResponseController,
	ch *channel.Channel,
	log *slog.Logger,
) {
	tuning := ch.Tuning()
	ring := ch.Ring()

	// Positioned ONCE, at setup, exactly as output/ts/generator.py:264-302
	// positions a client. A JoinBehind of zero means the live head, which is
	// what new_client_behind_seconds = 0 means there too.
	cursor := ring.Head()
	if tuning.JoinBehind > 0 {
		cursor = ring.Join(tuning.JoinBehind)
	}

	for {
		chunks, next, skipped := ring.Read(cursor)
		if skipped > 0 {
			log.Warn("client fell behind the ring",
				"channel", ch.ID(), "skipped", skipped, "head", ring.Head())
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
