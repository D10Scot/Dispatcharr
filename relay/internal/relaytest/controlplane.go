package relaytest

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
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

	mu       sync.Mutex
	requests []RecordedRequest
	events   []RecordedEvent
	settings map[string]any
	status   int
	delay    time.Duration
}

// SetSettings replaces the proxy_settings every LATER answer carries. It is
// how a test changes a setting between two tunes, the way an operator's
// save does, to show that a channel already running does not pick it up
// (parity-matrix row 5).
func (c *ControlPlane) SetSettings(settings map[string]any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.settings = settings
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
	StreamID    *int
	Details     map[string]any
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
		c.events = append(c.events, RecordedEvent{Type: e.Type, ChannelID: e.ChannelID, ChannelName: e.ChannelName, StreamID: e.StreamID, Details: e.Details})
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
	render := func(cand candidate) map[string]any {
		return map[string]any{
			"stream_id":             cand.id,
			"url":                   cand.url,
			"user_agent":            cand.userAgent,
			"transcode":             kind == "transcode",
			"m3u_profile_id":        1,
			"slot_reserved":         slotReserved,
			"channel_name":          "Test Channel",
			"stream_name":           "Test Stream",
			"m3u_profile_name":      "Test Profile",
			"stream_profile":        profile(1, cfg.Command, cand.argv),
			"ffmpeg_stream_profile": ffmpegProfile,
		}
	}

	answer := map[string]any{
		"alternates":      []any{},
		"error":           nil,
		"proxy_settings":  settings,
		"output_profiles": map[string]any{},
		"source":          nil,
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
