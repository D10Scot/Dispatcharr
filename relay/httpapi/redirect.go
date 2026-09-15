package httpapi

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The Redirect stream-profile architecture (views.py:468-547): no bytes
// through the relay and no failover after connect. The provider URL is
// probed, the cached alternates are tried in turn when it fails, the
// reserved slot is given back, and the client is handed the URL -- the one
// that VALIDATED, not wherever the probe was redirected to, because
// validate_stream_url returns the URL it was given (url_utils.py:183, :250).

// probeTimeout is the (5, 5) pair views.py:480 and :503 pass
// validate_stream_url: connect 5s, read 5s.
const probeTimeout = 5 * time.Second

// probeRedirectLimit is requests' DEFAULT_REDIRECT_LIMIT (30), which
// allow_redirects=True on the probe (url_utils.py:174, :190) is bounded by;
// past it requests raises TooManyRedirects and the URL is invalid.
const probeRedirectLimit = 30

// probeChunk is the first-chunk read of the GET probe, url_utils.py:196's
// iter_content(chunk_size=188*10).
const probeChunk = buffer.TSPacketSize * 10

// ErrRedirectValidationFailed is "All available redirect URLs failed
// validation" (views.py:542-547), answered 502 with a JSON body.
var ErrRedirectValidationFailed = errors.New("httpapi: every redirect candidate failed validation")

// redirectAnswer is the tune's outcome on a Redirect channel: not a channel
// at all, so it travels as an error out of the start function and the
// handler writes it. Status is 302 for an HTTP URL (HttpResponseRedirect)
// and 301 for rtsp/rtp/udp, which Django's redirect class refuses and
// views.py:533-538 builds by hand.
type redirectAnswer struct {
	Location string
	Status   int
}

func (r *redirectAnswer) Error() string {
	return fmt.Sprintf("httpapi: redirect the client with %d", r.Status)
}

// NewProbeClient is the client validate_stream_url's port probes with when
// StreamDeps.Probe is nil: requests' defaults, redirects followed up to
// thirty, one connection per probe.
func NewProbeClient() *http.Client {
	return &http.Client{
		Transport: &http.Transport{
			DialContext:           (&net.Dialer{Timeout: probeTimeout}).DialContext,
			ResponseHeaderTimeout: probeTimeout,
			DisableKeepAlives:     true,
		},
		CheckRedirect: func(_ *http.Request, via []*http.Request) error {
			if len(via) >= probeRedirectLimit {
				return errors.New("too many redirects")
			}
			return nil
		},
	}
}

// redirectTune is the views.py:468-547 branch. It returns a *redirectAnswer
// when a candidate validated, ErrRedirectValidationFailed when none did, and
// in either case has released the slot the initial answer reserved.
func redirectTune(ctx context.Context, deps tuneDeps, id string, answer *control.NextSourceAnswer, defaultUserAgent string) error {
	probe := deps.probe
	if probe == nil {
		probe = NewProbeClient()
	}
	source := answer.Source

	// Python passes the answer's user_agent RAW here, not the defaulted one
	// StreamManager would use (views.py:479-481 versus input/manager.py:73), so
	// a blank agent sends no User-Agent header at all.
	_ = defaultUserAgent
	valid, message := validateStreamURL(ctx, probe, source.URL, source.UserAgent)
	final := source.URL
	deps.log.Info("validated the redirect URL", "channel", id, "valid", valid, "result", message)
	if !valid {
		deps.log.Warn("the primary stream URL failed validation; trying the cached alternates", "channel", id, "result", message)
		tried := map[int]bool{source.StreamID: true}
		for i := range answer.Alternates {
			alt := &answer.Alternates[i]
			if tried[alt.StreamID] {
				continue
			}
			tried[alt.StreamID] = true
			deps.log.Info("trying an alternate stream", "channel", id, "stream", alt.StreamID)
			if valid, message = validateStreamURL(ctx, probe, alt.URL, alt.UserAgent); valid {
				final = alt.URL
				deps.log.Info("an alternate stream validated", "channel", id, "stream", alt.StreamID)
				break
			}
			deps.log.Warn("an alternate stream failed validation", "channel", id, "stream", alt.StreamID, "result", message)
		}
	}

	// views.py:516-525: the slot the initial answer reserved goes back
	// before the client is sent to the provider, because nothing here will
	// ever stream through it.
	if source.SlotReserved {
		streamID, profileID := source.StreamID, source.M3UProfileID
		released, err := deps.control.Release(ctx, id, control.ReleaseRequest{StreamID: &streamID, M3UProfileID: &profileID})
		switch {
		case err != nil:
			deps.log.Warn("could not release the slot before redirecting", "channel", id, "error", redact.Error(err))
		case !released:
			deps.log.Warn("failed to release the stream before redirecting", "channel", id)
		}
	}

	if !valid {
		return ErrRedirectValidationFailed
	}
	status := http.StatusFound
	lower := strings.ToLower(final)
	if strings.HasPrefix(lower, "rtsp://") || strings.HasPrefix(lower, "rtp://") || strings.HasPrefix(lower, "udp://") {
		status = http.StatusMovedPermanently
	}
	return &redirectAnswer{Location: final, Status: status}
}

// validateStreamURL is url_utils.py:138-262's validate_stream_url: a
// non-HTTP scheme is valid unprobed; a HEAD that answers 2xx is valid; a GET
// that answers 2xx and yields at least one byte is valid; anything else is
// not, with the reason. The Content-Type is never a reason to refuse
// (:234-250, "always consider the stream valid if we got data").
func validateStreamURL(ctx context.Context, probe *http.Client, rawURL, userAgent string) (bool, string) {
	lower := strings.ToLower(rawURL)
	if strings.HasPrefix(lower, "udp://") || strings.HasPrefix(lower, "rtp://") || strings.HasPrefix(lower, "rtsp://") {
		return true, "Non-HTTP protocol (UDP/RTP/RTSP) - validation skipped"
	}

	request := func(method string) (*http.Response, error) {
		ctx, cancel := context.WithTimeout(ctx, probeTimeout)
		req, err := http.NewRequestWithContext(ctx, method, rawURL, nil)
		if err != nil {
			cancel()
			return nil, err
		}
		// requests sends the header only when it has a value; Go's client
		// sends its own default unless told to send none.
		if userAgent != "" {
			req.Header.Set("User-Agent", userAgent)
		} else {
			req.Header["User-Agent"] = nil
		}
		req.Header.Set("Connection", "close")
		response, err := probe.Do(req)
		if err != nil {
			cancel()
			return nil, err
		}
		// The read below runs under the same deadline; the body's Close
		// releases it.
		body := response.Body
		response.Body = closerFunc{Reader: body, close: func() error { cancel(); return body.Close() }}
		return response, nil
	}

	// HEAD first (:171-178); any error means "HEAD not supported", not
	// "invalid" (:175-178).
	if head, err := request(http.MethodHead); err == nil {
		status := head.StatusCode
		_ = head.Body.Close()
		if status >= 200 && status < 300 {
			return true, "Valid (HEAD request)"
		}
	}

	get, err := request(http.MethodGet)
	if err != nil {
		var netErr net.Error
		switch {
		case errors.As(err, &netErr) && netErr.Timeout():
			return false, "Timeout connecting to stream"
		case strings.Contains(err.Error(), "too many redirects"):
			return false, "Too many redirects"
		}
		return false, "Request error: " + redact.Error(err).Error()
	}
	defer func() { _ = get.Body.Close() }()
	if get.StatusCode < 200 || get.StatusCode >= 300 {
		return false, fmt.Sprintf("Invalid HTTP status: %d", get.StatusCode)
	}
	first := make([]byte, probeChunk)
	n, readErr := io.ReadFull(get.Body, first)
	switch {
	case n > 0:
		return true, fmt.Sprintf("Valid (GET request, received %d bytes)", n)
	case readErr != nil && !errors.Is(readErr, io.EOF) && !errors.Is(readErr, io.ErrUnexpectedEOF):
		var netErr net.Error
		if errors.As(readErr, &netErr) && netErr.Timeout() {
			return false, "Timeout connecting to stream"
		}
		return false, "Request error: " + redact.Error(readErr).Error()
	}
	return false, "Empty response from server"
}

type closerFunc struct {
	io.Reader
	close func() error
}

func (c closerFunc) Close() error { return c.close() }
