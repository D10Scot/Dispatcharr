package httpapi

import (
	"errors"
	"net/http"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/session"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
)

// statusRecorder remembers the status a handler answered with, so a failure
// branch that writes its own response (an HLS entry, an Output Profile that
// would not start, the fMP4 remux's 500) still ends relay.tune with that
// status. It changes nothing it forwards, and Unwrap keeps
// http.ResponseController's Flush and deadlines reaching the real writer.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	if s.status == 0 {
		s.status = code
	}
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(p []byte) (int, error) {
	if s.status == 0 {
		s.status = http.StatusOK
	}
	return s.ResponseWriter.Write(p)
}

func (s *statusRecorder) Unwrap() http.ResponseWriter { return s.ResponseWriter }

// arm marks the end of a tune's setup: from here the FirstWriteWriter in w's
// chain treats the first accepted byte as the tune's first byte and counts M3
// (observability D11). It is called at exactly three points, each
// immediately before the first media-path write: the top of serveClient, the
// fMP4 handler after its 200, and the HLS entry before the multivariant. A
// writer with no FirstWriteWriter (a test driving serveClient directly) is
// left alone.
func arm(w http.ResponseWriter) {
	for w != nil {
		if fw, ok := w.(*telemetry.FirstWriteWriter); ok {
			fw.Arm()
			return
		}
		u, ok := w.(interface{ Unwrap() http.ResponseWriter })
		if !ok {
			return
		}
		w = u.Unwrap()
	}
}

// tuneFailureOutcome is relay.tune's mino.outcome for a tune error
// writeTuneFailure answered: refused when the tune was declined (by the
// control plane, by this relay's own contract with the request, or because
// nothing could serve it), failed when something broke.
func tuneFailureOutcome(err error) string {
	var refused *control.Refused
	var denied *control.Denied
	var unserved *ErrUnservedKind
	var unsupported *ErrUnsupportedOutput
	var malformed *ErrOutputProfileMalformed
	switch {
	case errors.As(err, &refused), errors.As(err, &denied),
		errors.As(err, &unserved), errors.As(err, &unsupported), errors.As(err, &malformed),
		errors.Is(err, ErrNoSource), errors.Is(err, channel.ErrDuplicateClient):
		return telemetry.OutcomeRefused
	}
	return telemetry.OutcomeFailed
}

// authorizeFailureOutcome is the outcome for an authorize-hop failure: a
// denial is a refusal at the denial's own status, anything else a failure.
func authorizeFailureOutcome(err error) string {
	var denied *control.Denied
	if errors.As(err, &denied) {
		return telemetry.OutcomeRefused
	}
	return telemetry.OutcomeFailed
}

// sessionChannel is the channel an HLS session belongs to, when it has one.
func sessionChannel(lookup session.Lookup) (*channel.Channel, bool) {
	if lookup.Session == nil {
		return nil, false
	}
	ch, ok := lookup.Session.Owner.(*channel.Channel)
	return ch, ok
}
