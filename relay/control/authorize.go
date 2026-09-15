package control

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// AuthorizePath is the dev fallback's route, spec D5 exception 2.
//
// ITS OWN PATH, not /_dispatcharr/authorize, and § The contract says why at
// length: that one is an `internal;` exact-match nginx location, so a POST to
// it is 404'd before Django sees it in every nginx-fronted deployment --
// which would turn a SECRET_KEY mismatch between the api and relay roles from
// today's silent-but-working degrade into every live tune failing.
const AuthorizePath = "/_dispatcharr/authorize-internal"

// The seven response headers a 200 carries: the five Phase 1 PR 5 defined
// plus 2b-2's two. The same seven any relay-bound nginx location sets, which
// is what makes the nginx shape and this one answer with the same material.
const (
	HeaderRelayChannel      = "X-Relay-Channel"
	HeaderRelayOutput       = "X-Relay-Output"
	HeaderRelayClient       = "X-Relay-Client"
	HeaderRelayUser         = "X-Relay-User"
	HeaderRelayName         = "X-Relay-Name"
	HeaderRelayOutputFormat = "X-Relay-Output-Format"
	HeaderRelayClientIP     = "X-Relay-Client-IP"
)

// AuthorizeHeaders is the three credential-bearing headers the authenticator
// union can consume, each null when the client sent none.
//
// THREE, NOT TWO. ApiKeyAuthentication (apps/accounts/authentication.py:
// 46-85) checks X-API-Key BEFORE falling back to an `Authorization: ApiKey
// ...` header, so a client authenticating that way would resolve to anonymous
// in this shape and to its real user in production -- the cross-shape
// divergence D5 exists to prevent.
//
// A sub-object rather than three flat fields, deliberately: a fourth
// credential header discovered later is a field, not a body-shape redesign.
type AuthorizeHeaders struct {
	Authorization *string `json:"authorization"`
	Cookie        *string `json:"cookie"`
	APIKey        *string `json:"x-api-key"`
}

// AuthorizeRequest is the question, in full, so that sha256(body) binds it.
//
// NO IDENTITY-BEARING MATERIAL TRAVELS AS A HEADER ON THIS ROUTE. The bound
// token signs exactly five fields -- the context, the method, the full path,
// the timestamp and sha256(body) -- and headers are not among them, so a
// captured X-Dispatcharr-Internal-Request for this path would otherwise stay
// valid for 120 seconds against ANY combination of forwarded headers.
type AuthorizeRequest struct {
	// URI is the full path and query string being authorized, the equivalent
	// of nginx's X-Original-URI.
	URI string `json:"uri"`

	// ClientIP is the viewer's address, which Django evaluates the STREAMS
	// ACL against (apps/proxy/authorize.py:425). Without it Django would
	// judge THIS RELAY'S address -- wrong in exactly the nginx-less
	// deployments this call exists for.
	ClientIP string `json:"client_ip"`

	// Internal is whether the CLIENT's request was internal -- the DVR's own
	// fetch, which carries the static X-Dispatcharr-Internal with no bound
	// counterpart. NEVER the transport's own header, which IsInternalRelay
	// requires this call to send and which therefore answers only "the
	// caller is part of the deployment". Django reads request_is_internal off
	// the request it is handed and returns INTERNAL_PRINCIPAL before any
	// channel flag, adult filter, profile membership or XC credential is
	// looked at, so collapsing the two questions authorizes every tune in
	// every nginx-less deployment, unconditionally.
	Internal bool `json:"internal"`

	Headers AuthorizeHeaders `json:"headers"`
}

// Decision is what a 200 carries: the seven X-Relay-* values, which are
// exactly what the trusted path reads off the request instead.
type Decision struct {
	ChannelUUID     string
	OutputProfileID string
	ClientID        string
	UserID          string
	RelayName       string
	OutputFormat    string
	ClientIP        string
}

// Denied is a refusal, carrying THE TRUE STATUS.
//
// Django's authorize_internal_view answers with authorize_error_response,
// never subrequest_error_response's 403 collapse: that shape exists only
// because ngx_http_auth_request_module can transport a 2xx, a 401 and a 403
// and nothing else, and a direct POST has no such constraint. So a 404 for an
// unknown channel and a 429 for a user over their stream limit arrive as
// themselves and reach the viewer as themselves, which is what the Python
// relay's own inline fallback already does.
type Denied struct {
	Status int

	// Body is the JSON denial AuthorizeDenialSerializer rendered --
	// {"error": "..."} -- forwarded to the viewer verbatim because that is
	// what the Python relay's inline path already returns to them
	// (resolve_authorization lets AuthorizeDenied propagate and the stream
	// view answers authorize_error_response). Nil unless the answer was
	// application/json and inside DeniedBodyLimit, so a 500 HTML page or a
	// proxy's error document can never be echoed.
	Body []byte
}

func (e *Denied) Error() string {
	return fmt.Sprintf("control: the control plane denied the tune with %d", e.Status)
}

// DeniedBodyLimit bounds how much of a denial body is forwarded. Four
// kibibytes is three orders of magnitude more than {"error": "Stream limit
// exceeded (3 concurrent streams allowed)"} needs and small enough that a
// misconfigured upstream cannot make this relay buffer a page per tune.
const DeniedBodyLimit = 4 << 10

// Authorize asks Django to authorize one tune.
//
// ONE ATTEMPT, NO RETRY, and that is a decision rather than an oversight:
// this call is the in-process authorize_stream() call's successor, and the
// Python relay's inline path cannot fail with a 5xx because there is no wire
// between it and the decision. A retry here would add up to a second
// (ConnectTimeout + ReadTimeout) to the tune's critical path for a fault that
// a second attempt against the same misconfigured or overloaded Django will
// meet again.
func (c *Client) Authorize(ctx context.Context, req AuthorizeRequest) (*Decision, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("encoding the authorize request: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}

	base := c.BaseURL
	if base == "" {
		resolved, baseErr := BaseURL()
		if baseErr != nil {
			return nil, baseErr
		}
		base = resolved
	}
	httpClient := c.HTTP
	if httpClient == nil {
		httpClient = NewHTTPClient()
	}
	now := c.Now
	if now == nil {
		now = time.Now
	}

	request, err := http.NewRequestWithContext(ctx, http.MethodPost, base+AuthorizePath, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("building the request for %s: %w", AuthorizePath, redact.Error(err))
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(HeaderInternal, InternalPrincipalToken(c.Secret))
	request.Header.Set(HeaderInternalRequest,
		InternalRequestHeader(c.Secret, http.MethodPost, AuthorizePath, body, now().Unix()))

	response, err := httpClient.Do(request)
	if err != nil {
		return nil, &Unavailable{Path: AuthorizePath, Reason: "transport failure", Err: err}
	}
	defer func() { _ = response.Body.Close() }()

	status := response.StatusCode
	switch {
	case status >= 200 && status < 300:
	case status >= 300 && status < 400:
		return nil, &Unavailable{Path: AuthorizePath, Reason: fmt.Sprintf("answered %d; a redirect is never followed", status)}
	case status == http.StatusUnauthorized, status == http.StatusForbidden,
		status == http.StatusNotFound, status == http.StatusTooManyRequests:
		// A DECISION, not an outage: these are the four statuses
		// AuthorizeDenied is raised with (apps/proxy/authorize.py), and each
		// must reach the viewer as itself.
		return nil, &Denied{Status: status, Body: deniedBody(response)}
	case status >= 400 && status < 500:
		// Every other 4xx is the contract being wrong -- a 400 from the
		// serializer, a 403 from IsInternalRelay on a SECRET_KEY mismatch
		// between roles -- and must fail loudly rather than be reported to
		// the viewer as a refusal of their tune.
		return nil, &Refused{Path: AuthorizePath, Status: status}
	default:
		return nil, &Unavailable{Path: AuthorizePath, Reason: fmt.Sprintf("answered %d", status)}
	}

	// The decision is entirely in the headers; an undrained body keeps the
	// connection out of the pool.
	_, _ = io.Copy(io.Discard, response.Body)

	return &Decision{
		ChannelUUID:     response.Header.Get(HeaderRelayChannel),
		OutputProfileID: response.Header.Get(HeaderRelayOutput),
		ClientID:        response.Header.Get(HeaderRelayClient),
		UserID:          response.Header.Get(HeaderRelayUser),
		RelayName:       response.Header.Get(HeaderRelayName),
		OutputFormat:    response.Header.Get(HeaderRelayOutputFormat),
		ClientIP:        response.Header.Get(HeaderRelayClientIP),
	}, nil
}

// deniedBody reads the denial's JSON body, or nil.
func deniedBody(response *http.Response) []byte {
	if ct := response.Header.Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		return nil
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, DeniedBodyLimit))
	if err != nil || len(raw) == 0 {
		return nil
	}
	return raw
}
