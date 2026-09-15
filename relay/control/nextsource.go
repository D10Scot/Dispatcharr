package control

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The three stream-profile architectures, as StreamProfileRef.Kind spells
// them. Added to the contract by 2c-1 Task 0 (Finding F1): `transcode` alone
// collapses Proxy and Redirect onto the same false, and both locked profiles
// carry an empty command, so nothing else on the wire separates them.
const (
	KindProxy     = "proxy"
	KindRedirect  = "redirect"
	KindTranscode = "transcode"
)

// Timeouts for next-source, from spec § The contract: connect 2s, read 5s,
// one retry at 0.1s -- the same numbers Python's own next-source client
// uses, at apps/proxy/control_plane.py:37 (CONNECT_TIMEOUT), :38
// (READ_TIMEOUT) and :41 (RETRY_DELAY). Pinned by TestTheTimeoutsMatchPython.
const (
	ConnectTimeout = 2 * time.Second
	ReadTimeout    = 5 * time.Second
	RetryDelay     = 100 * time.Millisecond
	attempts       = 2
)

// StreamProfileRef is the next-source answer's stream_profile object, and
// its ffmpeg_stream_profile object, which the same serializer renders.
type StreamProfileRef struct {
	ID      int    `json:"id"`
	Command string `json:"command"`
	Args    string `json:"args"`
	Kind    string `json:"kind"`

	// Argv is the argument list Django BUILT for this tune: StreamProfile.
	// build_command(url, user_agent, pk) with the command removed
	// (core/models.py:137-160 -- shlex.split of the profile's parameters,
	// then the {streamUrl}/{userAgent}/{channelId} substitutions). Spec
	// Amendment A4.1: the relay carries no word splitter and no
	// substitution table, so the argv it spawns is byte for byte the argv
	// the Python relay spawns from the same answer.
	//
	// Three states, and the difference between the last two is the whole
	// reason for ArgvPresent: a LIST is the built argv (empty for Proxy and
	// Redirect, whose build_command returns []); JSON NULL means Django
	// could not split the parameters (an unbalanced quote, which shlex
	// refuses with ValueError) and the tune cannot be served; the key
	// ABSENT means a control plane older than this relay, which is not a
	// profile problem and must not be reported as one.
	Argv []string `json:"-"`

	// ArgvPresent reports whether the answer carried the argv key at all.
	ArgvPresent bool `json:"-"`
}

// UnmarshalJSON decodes the object and records whether argv was present, a
// distinction encoding/json cannot make for a slice field on its own: an
// absent key and an explicit null both leave it nil.
func (p *StreamProfileRef) UnmarshalJSON(data []byte) error {
	type plain StreamProfileRef
	var aux struct {
		plain
		ArgvRaw json.RawMessage `json:"argv"`
	}
	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}
	*p = StreamProfileRef(aux.plain)
	p.Argv, p.ArgvPresent = nil, false
	if len(aux.ArgvRaw) == 0 {
		return nil
	}
	p.ArgvPresent = true
	if bytes.Equal(bytes.TrimSpace(aux.ArgvRaw), []byte("null")) {
		return nil
	}
	if err := json.Unmarshal(aux.ArgvRaw, &p.Argv); err != nil {
		return fmt.Errorf("stream_profile.argv is not a list of strings: %w", err) // credential-logging: ok - an encoding/json type error naming the JSON shape, never a value
	}
	if p.Argv == nil {
		p.Argv = []string{}
	}
	return nil
}

// Source is one candidate upstream.
type Source struct {
	StreamID       int              `json:"stream_id"`
	URL            string           `json:"url"`
	UserAgent      string           `json:"user_agent"`
	Transcode      bool             `json:"transcode"`
	M3UProfileID   int              `json:"m3u_profile_id"`
	SlotReserved   bool             `json:"slot_reserved"`
	StreamProfile  StreamProfileRef `json:"stream_profile"`
	ChannelName    string           `json:"channel_name"`
	StreamName     string           `json:"stream_name"`
	M3UProfileName string           `json:"m3u_profile_name"`

	// FFmpegStreamProfile is the locked "ffmpeg" profile, built for this
	// same URL, or nil when none is installed (apps/proxy/next_source.py's
	// _locked_ffmpeg_profile, Phase 2 PR 2b-1). It is what a Proxy channel
	// whose URL turns out to be HLS, RTSP or UDP is played through instead
	// (input/manager.py:445-453's force_ffmpeg).
	FFmpegStreamProfile *StreamProfileRef `json:"ffmpeg_stream_profile"`
}

// NextSourceRequest is the POST body.
type NextSourceRequest struct {
	ExcludeStreamIDs  []int  `json:"exclude_stream_ids"`
	Reason            string `json:"reason"`
	CurrentURL        string `json:"current_url,omitempty"`
	TargetStreamID    *int   `json:"target_stream_id,omitempty"`
	CurrentStreamID   *int   `json:"current_stream_id,omitempty"`
	IncludeAlternates bool   `json:"include_alternates"`
}

// OutputProfileRef is one entry of the answer's output_profiles map: an
// is_active OutputProfile with its command line already built
// (apps/proxy/serializers.py:217-230's OutputProfileRefSerializer).
//
// ARGV CARRIES THE COMMAND AS ELEMENT 0, unlike StreamProfileRef.Argv, which
// has it stripped off the front. core/models.py:200-203's build_command is
// `[self.command] + shlex_split(self.parameters)` and 2b-2 sends the whole
// list, where next_source.py's _stream_profile_ref sends `command` in its own
// field and the REST in argv. The asymmetry is on the wire and is reproduced
// rather than tidied: Command() and Args() below are the only places that
// split it, and TestTheOutputProfileArgvCarriesTheCommandFirst pins it against
// the same Python lines.
//
// Argv nil with Present true is Django saying it could NOT build the list --
// shlex refused the profile's parameters (an unbalanced quote), which
// OutputProfileSerializer validates nothing against, so such a row can already
// be sitting in the database.
type OutputProfileRef struct {
	ID int `json:"id"`

	// Argv is build_command() in full, or nil when Django sent null.
	Argv []string `json:"-"`
}

// UnmarshalJSON decodes the entry, mapping an explicit null argv to a nil
// slice and an empty list to an empty non-nil one -- the same distinction
// StreamProfileRef.UnmarshalJSON makes, for the same reason.
func (p *OutputProfileRef) UnmarshalJSON(data []byte) error {
	var aux struct {
		ID      int             `json:"id"`
		ArgvRaw json.RawMessage `json:"argv"`
	}
	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}
	p.ID, p.Argv = aux.ID, nil
	if len(aux.ArgvRaw) == 0 || bytes.Equal(bytes.TrimSpace(aux.ArgvRaw), []byte("null")) {
		return nil
	}
	if err := json.Unmarshal(aux.ArgvRaw, &p.Argv); err != nil {
		return fmt.Errorf("output_profiles[].argv is not a list of strings: %w", err) // credential-logging: ok - an encoding/json type error naming the JSON shape, never a value
	}
	if p.Argv == nil {
		p.Argv = []string{}
	}
	return nil
}

// Command is the executable to spawn: argv[0]. Empty when Django could not
// build the list, or when the profile's own command field is blank.
func (p OutputProfileRef) Command() string {
	if len(p.Argv) == 0 {
		return ""
	}
	return p.Argv[0]
}

// Args is everything after the command, the way ffmpeg.StartPiped takes it.
func (p OutputProfileRef) Args() []string {
	if len(p.Argv) < 2 {
		return []string{}
	}
	return p.Argv[1:]
}

// NextSourceAnswer is the response body.
type NextSourceAnswer struct {
	Source     *Source  `json:"source"`
	Alternates []Source `json:"alternates"`
	// Error is a CharField(allow_null=True) on the wire, so JSON null
	// unmarshals to the empty string. Callers test Source == nil, never this.
	Error         string   `json:"error"`
	ProxySettings Settings `json:"proxy_settings"`

	// OutputProfiles is every is_active OutputProfile, keyed by stringified
	// id (apps/proxy/next_source.py's _with_output_profiles, 2b-2). The WHOLE
	// active set travels because next-source runs once per CHANNEL while the
	// profile is resolved once per CLIENT, and the second client on a running
	// channel makes no next-source call at all (views.py:712) -- 2b-2's own
	// Ruling R3, which named a Go relay caching the map per channel as what
	// closes views.py:152's ORM read.
	OutputProfiles map[string]OutputProfileRef `json:"-"`

	// OutputProfilesPresent reports whether the answer carried the key at
	// all. An ABSENT key is a control plane older than 2b-2 and is a contract
	// mismatch, not "this deployment has no profiles"; an empty OBJECT is the
	// latter, and apps/proxy/tests/test_next_source_api.py::
	// test_no_active_profiles_is_an_empty_object_not_a_missing_key pins that
	// Django sends one. encoding/json cannot tell a nil map from an absent
	// key on its own, which is why this flag exists -- StreamProfileRef.
	// ArgvPresent is the same shape for the same reason.
	OutputProfilesPresent bool `json:"-"`
}

// UnmarshalJSON decodes the answer and records whether output_profiles was
// present, which a plain map field cannot report.
func (a *NextSourceAnswer) UnmarshalJSON(data []byte) error {
	type plain NextSourceAnswer
	var aux struct {
		plain
		ProfilesRaw json.RawMessage `json:"output_profiles"`
	}
	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}
	*a = NextSourceAnswer(aux.plain)
	a.OutputProfiles, a.OutputProfilesPresent = nil, false
	if len(aux.ProfilesRaw) == 0 {
		return nil
	}
	a.OutputProfilesPresent = true
	if bytes.Equal(bytes.TrimSpace(aux.ProfilesRaw), []byte("null")) {
		return nil
	}
	if err := json.Unmarshal(aux.ProfilesRaw, &a.OutputProfiles); err != nil {
		return fmt.Errorf("output_profiles is not an object of profiles: %w", err) // credential-logging: ok - an encoding/json type error naming the JSON shape, never a value
	}
	if a.OutputProfiles == nil {
		a.OutputProfiles = map[string]OutputProfileRef{}
	}
	return nil
}

// Unavailable means the control plane could not be reached or did not answer
// like Django. Only this is retried, and only this triggers the degraded
// fallback 2c-5 adds.
type Unavailable struct {
	Path   string
	Reason string
	Err    error

	// retryable is set only on the two outcomes that consume the second
	// attempt -- a transport failure and a 5xx. It is unexported because it
	// is this package's retry bookkeeping, not something a caller decides.
	// Spec § Error handling per hop is explicit that the non-JSON, non-object
	// and 3xx outcomes raise on the FIRST pass: a client built to the
	// uncorrected table burns a second full (2, 5) budget -- up to seven
	// extra seconds of dead air -- on a misconfigured deployment.
	retryable bool
}

func (e *Unavailable) Error() string {
	if e.Err != nil {
		// Through redact.Error: Err is the transport's *url.Error on a
		// connection failure, and its message carries the control-plane
		// base URL, which DISPATCHARR_INTERNAL_API_BASE_URL may give with
		// userinfo. Found by relay/internal/credlint's first run over this
		// module (2c-4), the shape 2c-2's review found once by hand.
		return fmt.Sprintf("control plane unavailable at %s: %s: %v", e.Path, e.Reason, redact.Error(e.Err))
	}
	return fmt.Sprintf("control plane unavailable at %s: %s", e.Path, e.Reason)
}

func (e *Unavailable) Unwrap() error { return e.Err }

// Refused is a 4xx other than next-source's own 404. Deliberately NOT a
// subclass of Unavailable: a 403 from a SECRET_KEY mismatch between the api
// and relay roles must fail the tune loudly rather than make every failover on
// the deployment degrade silently forever.
type Refused struct {
	Path   string
	Status int
}

func (e *Refused) Error() string {
	return fmt.Sprintf("control plane refused %s with %d", e.Path, e.Status)
}

// Client calls Django's /api/relay/... routes.
type Client struct {
	// Secret is the deployment's Django SECRET_KEY.
	Secret string
	// HTTP is the transport. Nil means a client built from ConnectTimeout and
	// ReadTimeout that never follows a redirect.
	HTTP *http.Client
	// BaseURL overrides the resolver, for tests. Empty means BaseURL().
	BaseURL string
	// Now is the clock the bound token's timestamp comes from. Nil means
	// time.Now.
	Now func() time.Time
}

// NewHTTPClient is the transport Client uses when none is supplied.
//
// CheckRedirect refuses every redirect rather than following it, reproducing
// requests' allow_redirects=False: a followed redirect re-sends the signed
// internal headers to whatever a stray `return 301` names.
func NewHTTPClient() *http.Client {
	return &http.Client{
		Timeout: ConnectTimeout + ReadTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}

// NextSource asks Django which stream to play. identifier is the channel uuid
// or a stream hash, exactly as the Python relay passes it.
//
// A 404 is mapped to an answer with a nil Source and the error string
// "identifier not found", NOT to an error: the channel was deleted mid
// playback, which is an answer (apps/proxy/control_plane.py:158-165).
func (c *Client) NextSource(ctx context.Context, identifier string, req NextSourceRequest) (*NextSourceAnswer, error) {
	path := "/api/relay/channels/" + identifier + "/next-source"
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("encoding the next-source request: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}

	raw, status, err := c.post(ctx, path, body)
	if err != nil {
		var refused *Refused
		if errors.As(err, &refused) && status == http.StatusNotFound {
			return &NextSourceAnswer{Alternates: []Source{}, Error: "identifier not found"}, nil
		}
		return nil, err
	}

	var answer NextSourceAnswer
	if err := json.Unmarshal(raw, &answer); err != nil {
		return nil, &Unavailable{Path: path, Reason: "2xx body did not decode as a next-source answer", Err: err}
	}
	return &answer, nil
}

// post is the disposition table from spec § Error handling per hop, in full.
// Only a 5xx or a transport failure consumes the second attempt; every other
// non-2xx outcome raises on the first pass.
func (c *Client) post(ctx context.Context, path string, body []byte) ([]byte, int, error) {
	base := c.BaseURL
	if base == "" {
		resolved, err := BaseURL()
		if err != nil {
			return nil, 0, err
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

	var last error
	for attempt := range attempts {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return nil, 0, ctx.Err()
			case <-time.After(RetryDelay):
			}
		}

		raw, status, err := c.attempt(ctx, httpClient, now, base, path, body)
		if err == nil {
			return raw, status, nil
		}
		var unavailable *Unavailable
		if !errors.As(err, &unavailable) || !unavailable.retryable {
			return nil, status, err
		}
		last = err
	}
	return nil, 0, last
}

func (c *Client) attempt(
	ctx context.Context,
	httpClient *http.Client,
	now func() time.Time,
	base, path string,
	body []byte,
) ([]byte, int, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, base+path, bytes.NewReader(body))
	if err != nil {
		return nil, 0, fmt.Errorf("building the request for %s: %w", path, redact.Error(err))
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(HeaderInternal, InternalPrincipalToken(c.Secret))
	// The bound token signs the FULL path, query string included. There is no
	// query string on this route today; passing path rather than a bare path
	// constant is what keeps that true when one is added.
	request.Header.Set(HeaderInternalRequest,
		InternalRequestHeader(c.Secret, http.MethodPost, path, body, now().Unix()))

	response, err := httpClient.Do(request)
	if err != nil {
		return nil, 0, &Unavailable{Path: path, Reason: "transport failure", Err: err, retryable: true}
	}
	defer func() { _ = response.Body.Close() }()

	status := response.StatusCode
	switch {
	case status >= 300 && status < 400:
		return nil, status, &Unavailable{Path: path, Reason: fmt.Sprintf("answered %d; a redirect is never followed", status)}
	case status >= 400 && status < 500:
		return nil, status, &Refused{Path: path, Status: status}
	case status >= 500:
		return nil, status, &Unavailable{Path: path, Reason: fmt.Sprintf("answered %d", status), retryable: true}
	}

	raw, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, status, &Unavailable{Path: path, Reason: "2xx body could not be read", Err: err, retryable: true}
	}
	var probe any
	if err := json.Unmarshal(raw, &probe); err != nil {
		return nil, status, &Unavailable{Path: path, Reason: "2xx body is not JSON", Err: err}
	}
	if _, isObject := probe.(map[string]any); !isObject {
		return nil, status, &Unavailable{Path: path, Reason: "2xx body is JSON but not an object"}
	}
	return raw, status, nil
}
