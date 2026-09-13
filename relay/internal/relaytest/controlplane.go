package relaytest

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
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
		"BUFFER_CHUNK_SIZE":      255868, // apps/proxy/config.py:15, 188 * 1361
		"CHUNK_SIZE":             8192,   // :7
		"STREAM_TIMEOUT":         20,     // :103
		"FAILOVER_GRACE_PERIOD":  20,     // :120
		"KEEPALIVE_INTERVAL":     0.5,    // :97
		"MAX_KEEPALIVE_DURATION": 300,    // :122
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
}

// ControlPlane is a fake Django answering POST /api/relay/... .
type ControlPlane struct {
	server *httptest.Server

	mu       sync.Mutex
	requests []RecordedRequest
}

// RecordedRequest is one call the fake received.
type RecordedRequest struct {
	Method string
	Path   string
	Header http.Header
	Body   []byte
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
		})
		c.mu.Unlock()

		switch {
		case cfg.RedirectTo != "":
			http.Redirect(w, r, cfg.RedirectTo, http.StatusFound)
			return
		case seen < cfg.FailFirst:
			w.WriteHeader(http.StatusServiceUnavailable)
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

		settings := cfg.Settings
		if settings == nil {
			settings = EffectiveProxySettings()
		}
		kind := cfg.Kind
		if kind == "" {
			kind = "proxy"
		}

		answer := map[string]any{
			"alternates":      []any{},
			"error":           nil,
			"proxy_settings":  settings,
			"output_profiles": map[string]any{},
			"source":          nil,
		}
		if cfg.SourceURL != "" {
			answer["source"] = map[string]any{
				"stream_id":        1,
				"url":              cfg.SourceURL,
				"user_agent":       "relaytest/1.0",
				"transcode":        false,
				"m3u_profile_id":   1,
				"slot_reserved":    true,
				"channel_name":     "Test Channel",
				"stream_name":      "Test Stream",
				"m3u_profile_name": "Test Profile",
				"stream_profile": map[string]any{
					"id": 1, "command": "", "args": "", "kind": kind,
				},
				"ffmpeg_stream_profile": nil,
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(answer)
	}))
	return c
}

// URL is the base URL to hand a control.Client.
func (c *ControlPlane) URL() string { return c.server.URL }

// Requests is every call the fake has received, in order.
func (c *ControlPlane) Requests() []RecordedRequest {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]RecordedRequest(nil), c.requests...)
}

// Close stops the fake.
func (c *ControlPlane) Close() { c.server.Close() }
