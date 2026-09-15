package relaytest

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"time"
)

// EffectiveProxySettings is what Amendment A1.4 makes Django send on every
// next-source answer: the seven stored CoreSettings keys, plus every public
// plain-valued class attribute of apps/proxy/config.py's TSConfig under its
// own SCREAMING_CASE name.
//
// The values here are typed from apps/proxy/config.py BY HAND, and the Python
// side asserts the same literals independently (A1.4's value test). Deriving
// them from anything would make this fixture agree with a wrong wire format.
//
// Only the keys a Go test needs are present, because a fixture that carried
// all thirty-eight would make an "every key is required" assertion pass for
// the wrong reason: with everything present, a test cannot show that an
// ABSENT key fails. Add a key here when a Go consumer starts reading it.
func EffectiveProxySettings() map[string]any {
	return map[string]any{
		// The stored CoreSettings group (core/models.py:719-730).
		"buffering_timeout":          15,
		"buffering_speed":            1.0,
		"redis_chunk_ttl":            60,
		"channel_shutdown_delay":     0,
		"channel_init_grace_period":  60,
		"channel_client_wait_period": 5,
		"new_client_behind_seconds":  5,
		// TSConfig's class-attribute defaults, the half A1.4 adds.
		"BUFFER_CHUNK_SIZE":           255868,                     // apps/proxy/config.py:15, 188 * 1361
		"DEFAULT_USER_AGENT":          "VLC/3.0.20 LibVLC/3.0.20", // :6
		"CHUNK_SIZE":                  8192,                       // :7
		"STREAM_TIMEOUT":              20,                         // :103
		"FAILOVER_GRACE_PERIOD":       20,                         // :120
		"KEEPALIVE_INTERVAL":          0.5,                        // :97
		"MAX_KEEPALIVE_DURATION":      300,                        // :122
		"CONNECTION_TIMEOUT":          10,                         // :13
		"HEALTH_CHECK_INTERVAL":       5,                          // :104
		"MAX_RETRIES":                 3,                          // :9
		"RETRY_WINDOW_SECONDS":        1800,                       // :10
		"STABLE_CONNECTION_THRESHOLD": 30,                         // :11
		"MAX_STREAM_SWITCHES":         10,                         // :14
	}
}

// ControlPlaneConfig shapes a fake Django.
type ControlPlaneConfig struct {
	// SourceURL is what next-source answers with. Empty means the answer
	// carries a null source.
	SourceURL string

	// Kind is the stream_profile.kind on the answer. Empty means "proxy".
	Kind string

	// Settings is the proxy_settings object. Nil means
	// EffectiveProxySettings().
	Settings map[string]any

	// Status forces a status code on every call. Zero means 200.
	Status int

	// FailFirst answers the first n calls with 503 before behaving, so a test
	// can show the retry budget being spent.
	FailFirst int

	// RedirectTo, when set, answers 302 to it.
	RedirectTo string

	// Body, when non-empty, is returned verbatim with a 200 instead of a
	// generated answer, so a test can drive the non-JSON and non-object rows
	// of the error table.
	Body string

	// Nameless sends the three name fields as empty strings, which is what
	// an answer looks like when Django resolved a Source whose rows carry no
	// name -- the state parity-matrix row 18 is about. Every producer in
	// next_source.py reads them off a loaded row, so the real shape is
	// "always present, possibly empty"; the Go relay's payload omits an
	// empty one, where Python would fall back to an ORM lookup it has no
	// way to make.
	Nameless bool

	// Authorize is what POST /_dispatcharr/authorize-internal answers with.
	// Nil means the minimal default below.
	Authorize *AuthorizeDecision

	// Delay holds every answer for this long before writing it. Zero is the
	// ordinary immediate answer. 2c-3's R11 test needs a next-source call
	// still in flight when a client disconnects, and there is no other way
	// to arrange that deterministically.
	Delay time.Duration

	// Command and Argv are the stream_profile's built command line. Empty
	// and nil render as "" and [] -- the Proxy and Redirect shape.
	Command string
	Argv    []string

	// ArgvAbsent leaves the argv key out of stream_profile entirely, the
	// shape of a control plane older than 2c-4. ArgvNull sends it as null,
	// the shape of a profile whose parameters shlex could not split. Both
	// apply to ffmpeg_stream_profile too when one is sent.
	ArgvAbsent bool
	ArgvNull   bool

	// FFmpegProfile, when set, is sent as ffmpeg_stream_profile; nil sends
	// null, which is "no locked ffmpeg profile installed".
	FFmpegProfile *ProfileConfig

	// UserAgent overrides the source's user_agent. Empty means
	// "relaytest/1.0", the fixture's usual value; BlankUserAgent sends "".
	UserAgent      string
	BlankUserAgent bool

	// Alternates are the channel's other streams, in the order Django's
	// own traversal would offer them (2c-5). SourceURL is stream 1; each
	// alternate names its own stream id and URL. A next-source call whose
	// exclude_stream_ids or current_url rules out stream 1 is answered
	// with the first alternate it does not rule out, and a call with
	// include_alternates lists the rest -- the shape resolve_source
	// (apps/proxy/next_source.py:804-960) produces. With none, the fake
	// answers a null source once stream 1 is excluded, which is Django's
	// "no candidate" answer.
	Alternates []AlternateConfig

	// SlotReserved is the source's slot_reserved flag. Nil means true, the
	// value every earlier fixture sent.
	SlotReserved *bool

	// OutputProfiles is the answer's output_profiles map, keyed by
	// stringified id (2c-7). Nil sends the empty object Django sends when no
	// profile is active -- apps/proxy/tests/test_next_source_api.py::
	// test_no_active_profiles_is_an_empty_object_not_a_missing_key pins that
	// it is an object and not a missing key.
	OutputProfiles map[string]OutputProfileConfig

	// OutputProfilesAbsent leaves the key out entirely: the shape of a
	// control plane older than Phase 2 PR 2b-2, which the relay must report
	// as a contract mismatch rather than as "no profiles are configured".
	OutputProfilesAbsent bool
}

// OutputProfileConfig is one entry of the fake's output_profiles map.
type OutputProfileConfig struct {
	// ID is the entry's id field. Zero means the map key parsed as an int.
	ID int

	// Argv is build_command() in full, COMMAND FIRST -- the shape
	// OutputProfileRefSerializer sends (apps/proxy/serializers.py:230),
	// which is not stream_profile.argv's shape.
	Argv []string

	// ArgvNull sends argv as null: a profile whose parameters shlex could
	// not split.
	ArgvNull bool
}

// AlternateConfig is one alternate stream the fake offers. Argv is the
// built argv for THIS stream's URL, as Django builds one per candidate
// (Amendment A4.1); nil renders as [] under the config's Command.
type AlternateConfig struct {
	StreamID  int
	URL       string
	UserAgent string
	Argv      []string
}

// ProfileConfig is one stream-profile object the fake sends.
type ProfileConfig struct {
	ID      int
	Command string
	Argv    []string
}

// ControlPlane is a fake Django answering POST /api/relay/... .
type ControlPlane struct {
	server *httptest.Server

	mu        sync.Mutex
	requests  []RecordedRequest
	events    []RecordedEvent
	settings  map[string]any
	status    int
	delay     time.Duration
	profiles  map[string]OutputProfileConfig
	hasProfs  bool
	authorize *AuthorizeDecision
}

// AuthorizeDecision is what the fake answers POST
// /_dispatcharr/authorize-internal with: the seven X-Relay-* headers on a
// 200, or a status and a body on a denial.
//
// THE DEFAULT IS DELIBERATELY MINIMAL -- the channel out of the URI, and
// nothing else. Django resolves more than that on every live tune (it always
// mints a client id), and filling those in here by default would silently
// change what every untrusted rig from 2c-2 onward observes. A test that is
// ABOUT the authorize hop sets the fields it is about, which is what keeps
// the default from pinning anything.
type AuthorizeDecision struct {
	Channel      string
	Output       string
	Client       string
	User         string
	Name         string
	OutputFormat string
	ClientIP     string

	// Status, when non-zero, is answered instead of 200. Body is the JSON
	// denial that goes with it.
	Status int
	Body   string

	// NonJSONBody answers the denial with a text/html body instead, which
	// is what a proxy's own error document or a Django 500 page looks like.
	// The relay must NOT forward such a body to a viewer, and a test that
	// only ever configured a JSON one could not tell the two branches apart.
	NonJSONBody bool
}

// SetAuthorize replaces what every LATER authorize call is answered with.
func (c *ControlPlane) SetAuthorize(decision *AuthorizeDecision) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.authorize = decision
}

// AuthorizeRequest is one decoded POST to the authorize route.
type AuthorizeRequest struct {
	URI      string `json:"uri"`
	ClientIP string `json:"client_ip"`
	Internal bool   `json:"internal"`
	Headers  struct {
		Authorization *string `json:"authorization"`
		Cookie        *string `json:"cookie"`
		APIKey        *string `json:"x-api-key"`
	} `json:"headers"`
}

// AuthorizeRequests is every authorize call the fake has been sent, decoded,
// in order.
func (c *ControlPlane) AuthorizeRequests() []AuthorizeRequest {
	var out []AuthorizeRequest
	for _, r := range c.RequestsTo(AuthorizePath) {
		var decoded AuthorizeRequest
		if err := json.Unmarshal(r.Body, &decoded); err == nil {
			out = append(out, decoded)
		}
	}
	return out
}

// AuthorizePath is the route the Go relay's dev fallback calls, spelled here
// so a test naming it cannot drift from control.AuthorizePath.
const AuthorizePath = "/_dispatcharr/authorize-internal"

// SetSettings replaces the proxy_settings every LATER answer carries. It is
// how a test changes a setting between two tunes, the way an operator's
// save does, to show that a channel already running does not pick it up
// (parity-matrix row 5).
func (c *ControlPlane) SetSettings(settings map[string]any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.settings = settings
}

// SetOutputProfiles replaces the output_profiles map every LATER answer
// carries. It is how a test changes the active Output Profile set between two
// next-source calls, the way an operator editing a profile does, to show that
// a running channel picks the change up on its next answer and NOT from the
// degraded cache (2c-7's Ruling R5).
//
// A separate `hasProfs` flag rather than a nil check, for ControlPlaneConfig.
// OutputProfiles' own reason: nil means "the empty object Django sends when
// nothing is active", which a test may want to set deliberately.
func (c *ControlPlane) SetOutputProfiles(profiles map[string]OutputProfileConfig) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.profiles, c.hasProfs = profiles, true
}

// SetStatus makes every LATER call answer with status, whatever the route:
// 503 is an outage the client retries once and then degrades on, 403 a
// refusal it never degrades on. Zero restores the configured behaviour. It is
// how a test takes the control plane down AFTER a tune succeeded, which is
// the only moment the degraded fallback can be observed.
func (c *ControlPlane) SetStatus(status int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.status = status
}

// SetDelay holds every LATER answer for d before writing it, overriding the
// config's Delay: how a test makes the control plane slow AFTER a tune, so
// a failover's own budget can be watched being spent. Zero restores it.
func (c *ControlPlane) SetDelay(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.delay = d
}

// RecordedRequest is one call the fake received, and when.
type RecordedRequest struct {
	Method string
	Path   string
	Header http.Header
	Body   []byte
	At     time.Time
}

// RecordedEvent is one event out of a posted batch, decoded.
type RecordedEvent struct {
	Type        string
	ChannelID   string
	ChannelName string
	// ClientID is the second key emit_event lifts out of details to the top
	// level (control_plane.py:331-333's two-name loop). Added in 2c-8, with
	// the first events that carry one.
	ClientID string
	StreamID *int
	Details  map[string]any
}

// NewControlPlane starts a fake control plane. Register Close with t.Cleanup.
func NewControlPlane(cfg ControlPlaneConfig) *ControlPlane {
	c := &ControlPlane{}
	c.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body := make([]byte, 0)
		if r.Body != nil {
			buf := make([]byte, 1<<16)
			for {
				n, err := r.Body.Read(buf)
				body = append(body, buf[:n]...)
				if err != nil {
					break
				}
			}
		}
		c.mu.Lock()
		seen := len(c.requests)
		c.requests = append(c.requests, RecordedRequest{
			Method: r.Method,
			// RequestURI, not URL.Path: the bound token signs the FULL path
			// including the query string, so a test that needs to verify the
			// signature needs the full path back.
			Path:   r.RequestURI,
			Header: r.Header.Clone(),
			Body:   body,
			At:     time.Now(),
		})
		forced := c.status
		delay := c.delay
		c.mu.Unlock()

		if delay == 0 {
			delay = cfg.Delay
		}
		if delay > 0 {
			time.Sleep(delay)
		}

		switch {
		case cfg.RedirectTo != "":
			http.Redirect(w, r, cfg.RedirectTo, http.StatusFound)
			return
		case seen < cfg.FailFirst:
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		case forced != 0 && forced != http.StatusOK:
			w.WriteHeader(forced)
			_, _ = w.Write([]byte(`{"detail":"relaytest: status set by the test"}`))
			return
		case cfg.Status != 0 && cfg.Status != http.StatusOK:
			w.WriteHeader(cfg.Status)
			_, _ = w.Write([]byte(`{"detail":"relaytest: configured status"}`))
			return
		case cfg.Body != "":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(cfg.Body))
			return
		}

		// The authorize route is answered AFTER the three forced-failure arms
		// above, deliberately: a test that forces a 503 on the control plane
		// is testing an outage, and an outage takes the authorize call down
		// with everything else.
		if strings.HasSuffix(r.URL.Path, AuthorizePath) {
			c.writeAuthorize(w, cfg)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "/release"):
			// apps/proxy/api_views.py:96-100: ReleaseResponseSerializer.
			_ = json.NewEncoder(w).Encode(map[string]any{"released": true})
		case strings.HasSuffix(r.URL.Path, "/events"):
			c.recordEvents(body)
			var batch struct {
				Events []json.RawMessage `json:"events"`
			}
			_ = json.Unmarshal(body, &batch)
			_ = json.NewEncoder(w).Encode(map[string]any{"accepted": len(batch.Events), "rejected": 0})
		default:
			_ = json.NewEncoder(w).Encode(c.nextSourceAnswer(cfg, body))
		}
	}))
	return c
}

func (c *ControlPlane) recordEvents(body []byte) {
	var batch struct {
		Events []struct {
			Type        string         `json:"type"`
			ChannelID   string         `json:"channel_id"`
			ChannelName string         `json:"channel_name"`
			ClientID    string         `json:"client_id"`
			StreamID    *int           `json:"stream_id"`
			Details     map[string]any `json:"details"`
		} `json:"events"`
	}
	if err := json.Unmarshal(body, &batch); err != nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, e := range batch.Events {
		c.events = append(c.events, RecordedEvent{
			Type: e.Type, ChannelID: e.ChannelID, ChannelName: e.ChannelName,
			ClientID: e.ClientID, StreamID: e.StreamID, Details: e.Details,
		})
	}
}

// nextSourceAnswer picks a candidate the way Django's resolve_source does:
// the first of stream 1 and the alternates, in order, that the request's
// exclude_stream_ids does not name and whose URL is not the current_url
// (apps/proxy/next_source.py:242-368's own "already playing" rejection),
// or a null source.
func (c *ControlPlane) nextSourceAnswer(cfg ControlPlaneConfig, body []byte) map[string]any {
	var req struct {
		Exclude           []int  `json:"exclude_stream_ids"`
		CurrentURL        string `json:"current_url"`
		IncludeAlternates bool   `json:"include_alternates"`
	}
	_ = json.Unmarshal(body, &req)
	excluded := map[int]bool{}
	for _, id := range req.Exclude {
		excluded[id] = true
	}

	c.mu.Lock()
	settings := c.settings
	c.mu.Unlock()
	if settings == nil {
		settings = cfg.Settings
	}
	if settings == nil {
		settings = EffectiveProxySettings()
	}
	kind := cfg.Kind
	if kind == "" {
		kind = "proxy"
	}
	profile := func(id int, command string, argv []string) map[string]any {
		object := map[string]any{"id": id, "command": command, "args": "", "kind": kind}
		switch {
		case cfg.ArgvAbsent:
		case cfg.ArgvNull:
			object["argv"] = nil
		case argv == nil:
			object["argv"] = []string{}
		default:
			object["argv"] = argv
		}
		return object
	}
	var ffmpegProfile any
	if cfg.FFmpegProfile != nil {
		ffmpegProfile = profile(cfg.FFmpegProfile.ID, cfg.FFmpegProfile.Command, cfg.FFmpegProfile.Argv)
	}
	userAgent := "relaytest/1.0"
	if cfg.UserAgent != "" {
		userAgent = cfg.UserAgent
	}
	if cfg.BlankUserAgent {
		userAgent = ""
	}
	slotReserved := true
	if cfg.SlotReserved != nil {
		slotReserved = *cfg.SlotReserved
	}

	type candidate struct {
		id        int
		url       string
		userAgent string
		argv      []string
	}
	var candidates []candidate
	if cfg.SourceURL != "" {
		candidates = append(candidates, candidate{1, cfg.SourceURL, userAgent, cfg.Argv})
	}
	for _, alt := range cfg.Alternates {
		ua := alt.UserAgent
		if ua == "" {
			ua = userAgent
		}
		candidates = append(candidates, candidate{alt.StreamID, alt.URL, ua, alt.Argv})
	}
	names := func(value string) string {
		if cfg.Nameless {
			return ""
		}
		return value
	}
	render := func(cand candidate) map[string]any {
		return map[string]any{
			"stream_id":             cand.id,
			"url":                   cand.url,
			"user_agent":            cand.userAgent,
			"transcode":             kind == "transcode",
			"m3u_profile_id":        1,
			"slot_reserved":         slotReserved,
			"channel_name":          names("Test Channel"),
			"stream_name":           names("Test Stream"),
			"m3u_profile_name":      names("Test Profile"),
			"stream_profile":        profile(1, cfg.Command, cand.argv),
			"ffmpeg_stream_profile": ffmpegProfile,
		}
	}

	answer := map[string]any{
		"alternates":     []any{},
		"error":          nil,
		"proxy_settings": settings,
		"source":         nil,
	}
	c.mu.Lock()
	liveProfiles, overridden := c.profiles, c.hasProfs
	c.mu.Unlock()
	configured := cfg.OutputProfiles
	if overridden {
		configured = liveProfiles
	}
	if !cfg.OutputProfilesAbsent {
		profiles := map[string]any{}
		for key, entry := range configured {
			id := entry.ID
			if id == 0 {
				id, _ = strconv.Atoi(key)
			}
			object := map[string]any{"id": id}
			switch {
			case entry.ArgvNull:
				object["argv"] = nil
			case entry.Argv == nil:
				object["argv"] = []string{}
			default:
				object["argv"] = entry.Argv
			}
			profiles[key] = object
		}
		answer["output_profiles"] = profiles
	}
	chosen := -1
	for i, cand := range candidates {
		if excluded[cand.id] || (req.CurrentURL != "" && cand.url == req.CurrentURL) {
			continue
		}
		chosen = i
		break
	}
	if chosen < 0 {
		return answer
	}
	answer["source"] = render(candidates[chosen])
	if req.IncludeAlternates {
		alternates := []any{}
		for i, cand := range candidates {
			if i != chosen {
				alternates = append(alternates, render(cand))
			}
		}
		answer["alternates"] = alternates
	}
	return answer
}

// URL is the base URL to hand a control.Client.
func (c *ControlPlane) URL() string { return c.server.URL }

// Requests is every call the fake has received, in order.
func (c *ControlPlane) Requests() []RecordedRequest {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]RecordedRequest(nil), c.requests...)
}

// RequestsTo is every call whose path ends with suffix, in order: "/release",
// "/events" or "/next-source".
func (c *ControlPlane) RequestsTo(suffix string) []RecordedRequest {
	var out []RecordedRequest
	for _, r := range c.Requests() {
		if strings.HasSuffix(strings.SplitN(r.Path, "?", 2)[0], suffix) {
			out = append(out, r)
		}
	}
	return out
}

// Events is every event the fake has been posted, in order.
func (c *ControlPlane) Events() []RecordedEvent {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]RecordedEvent(nil), c.events...)
}

// EventsOfType is Events filtered to one type.
func (c *ControlPlane) EventsOfType(typ string) []RecordedEvent {
	var out []RecordedEvent
	for _, e := range c.Events() {
		if e.Type == typ {
			out = append(out, e)
		}
	}
	return out
}

// Close stops the fake. A relay whose control plane has been closed sees a
// transport failure on its next call, which is the other shape of
// control.Unavailable beside SetStatus's 5xx.
func (c *ControlPlane) Close() { c.server.Close() }

// writeAuthorize answers the dev fallback.
func (c *ControlPlane) writeAuthorize(w http.ResponseWriter, cfg ControlPlaneConfig) {
	c.mu.Lock()
	decision := c.authorize
	c.mu.Unlock()
	if decision == nil {
		decision = cfg.Authorize
	}
	if decision == nil {
		// The minimal default: the channel the URI named, so a relay that
		// believed an unverified X-Relay-Channel is still caught, and
		// nothing else.
		decision = &AuthorizeDecision{Channel: channelFromURI(c.lastAuthorizedURI())}
	}
	if decision.Status != 0 && decision.Status != http.StatusOK {
		if decision.NonJSONBody {
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.WriteHeader(decision.Status)
			_, _ = w.Write([]byte("<html>relaytest: a non-JSON denial</html>"))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(decision.Status)
		body := decision.Body
		if body == "" {
			body = `{"error":"relaytest: configured denial"}`
		}
		_, _ = w.Write([]byte(body))
		return
	}
	w.Header().Set("X-Relay-Channel", decision.Channel)
	w.Header().Set("X-Relay-Output", decision.Output)
	w.Header().Set("X-Relay-Client", decision.Client)
	w.Header().Set("X-Relay-User", decision.User)
	w.Header().Set("X-Relay-Name", decision.Name)
	w.Header().Set("X-Relay-Output-Format", decision.OutputFormat)
	w.Header().Set("X-Relay-Client-IP", decision.ClientIP)
	w.WriteHeader(http.StatusOK)
}

// lastAuthorizedURI is the uri field of the most recent authorize call.
func (c *ControlPlane) lastAuthorizedURI() string {
	seen := c.AuthorizeRequests()
	if len(seen) == 0 {
		return ""
	}
	return seen[len(seen)-1].URI
}

// channelFromURI is the last path segment of a tune URI, which for
// /proxy/ts/stream/<uuid> is the channel -- the same thing Django's resolver
// pulls out of the URL pattern.
func channelFromURI(uri string) string {
	path := strings.SplitN(uri, "?", 2)[0]
	idx := strings.LastIndex(path, "/")
	if idx < 0 {
		return path
	}
	return path[idx+1:]
}
