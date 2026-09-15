package httpapi

import (
	"context"
	"errors"
	"log/slog"
	"net/http"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// authorizeTune is the dev fallback (spec D5, exception 2): when nginx did
// not authorize this request, ask Django to, over HTTP.
//
// Returns (nil, nil) on a trusted request, which is every tune in every
// nginx-fronted deployment -- the same frequency at which the Python relay
// takes its own inline path (resolve_authorization's non-trusted branch,
// apps/proxy/authorize_views.py:183-196).
//
// WHAT TRAVELS AND WHAT DOES NOT. Everything identity-bearing goes in the
// BODY, because the bound token signs sha256(body) and signs no header: a
// captured X-Dispatcharr-Internal-Request for this path would otherwise stay
// valid for 120 seconds against any combination of forwarded headers. In
// particular `internal` is a body field read off the CLIENT's own static
// marker, never the transport's own X-Dispatcharr-Internal, which this call
// must send to satisfy IsInternalRelay and which answers a different question
// ("the caller is part of the deployment", not "this request is internal").
func authorizeTune(r *http.Request, deps StreamDeps, log *slog.Logger) (*control.Decision, error) {
	if control.IsRelayTrusted(deps.Secret, r.Header.Get(control.HeaderAuthorized)) {
		return nil, nil
	}
	if deps.Control == nil {
		// A rig with no control plane. Nothing to ask, so nothing is
		// asserted about the request: the caller falls through to the path
		// value and to values resolved locally, which is what 2c-2 through
		// 2c-7 did on every untrusted tune.
		return nil, nil
	}

	ctx, cancel := context.WithTimeout(r.Context(), control.ConnectTimeout+control.ReadTimeout)
	defer cancel()

	decision, err := deps.Control.Authorize(ctx, control.AuthorizeRequest{
		// RequestURI(), not Path: the query string carries ?token=,
		// ?session_id= and ?output_format=, and Django's own hop resolves
		// the surface from X-Original-URI with its query attached.
		URI:      r.URL.RequestURI(),
		ClientIP: peerAddress(r),
		Internal: control.IsInternalPrincipal(deps.Secret, r.Header.Get(control.HeaderInternal)),
		Headers: control.AuthorizeHeaders{
			Authorization: headerOrNil(r, "Authorization"),
			Cookie:        headerOrNil(r, "Cookie"),
			APIKey:        headerOrNil(r, "X-API-Key"),
		},
	})
	if err != nil {
		return nil, err
	}
	log.Debug("the control plane authorized an untrusted tune", "channel", decision.ChannelUUID)
	return decision, nil
}

// headerOrNil is the header's value, or nil when the client sent none.
//
// nil rather than "": Django's serializer declares each of the three
// allow_null, and "this client sent no Authorization header" and "this
// client sent an empty one" are different facts to an authenticator union
// that rejects a malformed credential with a 401 and declines a missing one
// (parity-matrix row 30).
func headerOrNil(r *http.Request, name string) *string {
	value, present := r.Header[http.CanonicalHeaderKey(name)]
	if !present || len(value) == 0 {
		return nil
	}
	v := value[0]
	return &v
}

// decisionHeader maps one X-Relay-* name to the decision's own field, so
// identify() reads its five values through ONE closure whichever source
// answered. A name this map does not know returns "", which is what an
// absent header does.
func decisionHeader(decision *control.Decision, name string) string {
	switch name {
	case control.HeaderRelayChannel:
		return decision.ChannelUUID
	case control.HeaderRelayOutput:
		return decision.OutputProfileID
	case control.HeaderRelayClient:
		return decision.ClientID
	case control.HeaderRelayUser:
		return decision.UserID
	case control.HeaderRelayOutputFormat:
		return decision.OutputFormat
	case control.HeaderRelayClientIP:
		return decision.ClientIP
	}
	return ""
}

// writeAuthorizeFailure turns an authorize error into the viewer's answer.
//
// A DENIAL REACHES THE VIEWER AS ITSELF -- 401, 403, 404 or 429 -- because
// that is what the Python relay's inline path does: resolve_authorization
// lets AuthorizeDenied propagate and the stream view answers
// authorize_error_response, whose status is the exception's own. The 403
// collapse belongs to the nginx subrequest form and to nothing else.
//
// Everything else is 502: the control plane could not be reached, refused
// this relay's own credentials, or is misconfigured. Never the error's text,
// which can name a variable or a URL.
func writeAuthorizeFailure(w http.ResponseWriter, log *slog.Logger, err error) {
	var denied *control.Denied
	if errors.As(err, &denied) {
		if len(denied.Body) > 0 {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(denied.Status)
			_, _ = w.Write(denied.Body)
			return
		}
		http.Error(w, http.StatusText(denied.Status), denied.Status)
		return
	}
	log.Error("the tune could not be authorized", "error", redact.Error(err))
	http.Error(w, "the tune could not be authorized", http.StatusBadGateway)
}
