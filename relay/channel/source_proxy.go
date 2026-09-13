package channel

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"sync/atomic"
	"time"
)

// Source produces one channel's upstream bytes.
//
// One method, so 2c-4's ffmpeg source drops in beside this one without either
// knowing about the other. The ring buffer is the sink and is an io.Writer, so
// a source never learns what a chunk is.
type Source interface {
	// Run copies upstream bytes into sink. It returns nil on a clean upstream
	// EOF, ctx.Err() when the caller cancels, and a named error otherwise.
	Run(ctx context.Context, sink io.Writer) error
}

// ErrUpstreamIdle is returned when the upstream sent nothing for ReadTimeout.
//
// 2c-2 ENDS THE TUNE ON THIS. That is not the dead-air failover trigger, which
// is parity-matrix row 2 and 2c-5's: Python's fetch_chunk returns False on a
// CHUNK_TIMEOUT read timeout and the main loop keeps going, and only the
// separate 10-second watchdog, observed on three consecutive five-second
// health checks, calls _try_next_stream(). 2c-2 has no failover to call, so
// the honest thing is to end the copy and say why, rather than ship a
// half-detector that looks like row 2 and is not.
var ErrUpstreamIdle = errors.New("channel: upstream sent nothing within the read timeout")

// ErrUpstreamStatus is returned when the provider answered other than 200.
type ErrUpstreamStatus struct{ Status int }

func (e *ErrUpstreamStatus) Error() string {
	return fmt.Sprintf("channel: upstream answered HTTP %d", e.Status)
}

// ProxySource is the Proxy stream-profile architecture: a raw HTTP GET whose
// body goes straight into the ring buffer. No subprocess, no stderr, and --
// parity-matrix row 29 -- therefore no ffmpeg_speed, no buffering state and no
// buffering failover, however far below the threshold the upstream runs.
//
// The Python original (input/http_streamer.py) reads the response on an OS
// thread and writes it down an O_NONBLOCK pipe, which the main loop then
// reads with select, so that the Proxy and transcode paths share one
// fetch_chunk(). That whole apparatus exists to keep a blocking read off the
// gevent hub. Go's scheduler multiplexes blocking I/O onto OS threads itself,
// so the pipe, the fcntl, the select and the second thread all go and what is
// left is the copy they existed to perform.
type ProxySource struct {
	// URL is the provider URL Django's next-source answer named.
	URL string

	// UserAgent goes on the request when non-empty.
	UserAgent string

	// ChunkSize is the read size. Zero means 8192, apps/proxy/config.py:7's
	// CHUNK_SIZE, which is also HTTPStreamReader's own default parameter
	// value at apps/proxy/live_proxy/input/http_streamer.py:18. Pinned,
	// against the zero value rather than a passed-in one, by
	// TestProxySourceDefaultsMatchPython.
	ChunkSize int

	// ConnectTimeout bounds the dial and the response headers. Zero means 5
	// seconds, the first half of apps/proxy/live_proxy/input/
	// http_streamer.py:71's timeout=(5, 30). Pinned by
	// TestProxySourceDefaultsMatchPython.
	ConnectTimeout time.Duration

	// ReadTimeout bounds the gap between bytes, which is what requests' read
	// timeout means. Zero means 30 seconds, the second half of the same pair
	// at the same line. Pinned by TestProxySourceDefaultsMatchPython.
	ReadTimeout time.Duration

	// Transport overrides the HTTP transport, for tests. Nil means one built
	// from ConnectTimeout with no retries and a single connection, matching
	// HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1).
	Transport http.RoundTripper
}

// withoutURL strips the URL out of a *url.Error before it reaches a log.
//
// net/http wraps every client failure in a *url.Error whose Error() prints the
// whole URL, and its redaction covers ONLY userinfo -- it turns
// http://user:pw@host into http://user:***@host and leaves the path and query
// string untouched. Provider credentials in this deployment routinely live in
// the QUERY STRING (a provider URL is commonly
// .../live/<user>/<pass>/<id>.ts, and the M3U transform builds others with
// ?username=&password=), so %w-wrapping the error as it comes would put a
// working credential in the container log on every failed connect. What is
// left after the strip is the transport's own message -- "dial tcp
// 127.0.0.1:1: connect: connection refused" -- which names a host and a port
// and no secret.
//
// This is the Go-side instance of the rule scripts/check_credential_logging.py
// enforces on the Python side. There is no Go equivalent of that script yet;
// until there is, this function and the tests around it are the enforcement.
func withoutURL(err error) error {
	var urlErr *url.Error
	if errors.As(err, &urlErr) && urlErr.Err != nil {
		return urlErr.Err
	}
	return err
}

func (s ProxySource) chunkSize() int {
	if s.ChunkSize > 0 {
		return s.ChunkSize
	}
	return 8192
}

func (s ProxySource) connectTimeout() time.Duration {
	if s.ConnectTimeout > 0 {
		return s.ConnectTimeout
	}
	return 5 * time.Second
}

func (s ProxySource) readTimeout() time.Duration {
	if s.ReadTimeout > 0 {
		return s.ReadTimeout
	}
	return 30 * time.Second
}

func (s ProxySource) transport() http.RoundTripper {
	if s.Transport != nil {
		return s.Transport
	}
	return &http.Transport{
		DialContext:           (&net.Dialer{Timeout: s.connectTimeout()}).DialContext,
		ResponseHeaderTimeout: s.connectTimeout(),
		MaxIdleConns:          1,
		MaxConnsPerHost:       1,
		DisableCompression:    true,
	}
}

// Run connects and copies until the upstream ends, the upstream goes idle, or
// ctx is done.
func (s ProxySource) Run(parent context.Context, sink io.Writer) error {
	// The derived context is the watchdog's lever. `parent` is kept under its
	// own name so a cancellation can be attributed correctly below: without
	// it, a client that disconnects at the same moment the watchdog fires
	// would be reported as an idle upstream, which is the wrong diagnosis on
	// the one signal 2c-5 turns into a failover.
	ctx, cancel := context.WithCancel(parent)
	defer cancel()

	request, err := http.NewRequestWithContext(ctx, http.MethodGet, s.URL, nil)
	if err != nil {
		// The URL came from the control plane, so a bad one is a control-plane
		// answer this relay cannot use. The URL itself is NEVER in the message:
		// it carries provider credentials (CLAUDE.md, credential logging).
		// NewRequestWithContext returns url.Parse's own error unwrapped on a
		// malformed URL, which is already a *url.Error printing the whole
		// string verbatim -- withoutURL strips it here exactly as it does at
		// the connect-failure site below; a bare %w was found by review to
		// leak it into channel.go's "upstream failed" log line.
		return fmt.Errorf("channel: the source URL is not usable: %w", withoutURL(err))
	}
	if s.UserAgent != "" {
		request.Header.Set("User-Agent", s.UserAgent)
	}

	client := &http.Client{Transport: s.transport()}
	// A fresh *http.Transport per Run and no IdleConnTimeout set on it means
	// an idle keep-alive connection this transport pools is never expired on
	// its own -- IdleConnTimeout's zero value is "no limit", not "the
	// default". Every tune builds a new one, so a clean upstream EOF (which
	// leaves the connection reusable, not closed) would leak one goroutine
	// and one open socket to the provider per completed tune, forever, with
	// nothing ever reusing the pool that held it. CloseIdleConnections is
	// this http.Client's own method and is a safe no-op if s.Transport was
	// overridden with a RoundTripper that does not implement it.
	defer client.CloseIdleConnections()
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("channel: connecting to the upstream: %w", withoutURL(err))
	}
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusOK {
		return &ErrUpstreamStatus{Status: response.StatusCode}
	}

	// The idle watchdog. requests' read timeout is the gap BETWEEN bytes, and
	// Go has no transport-level equivalent, so the deadline is enforced here:
	// a timer re-armed on every successful read, cancelling the request
	// context when it expires, which makes the in-flight Read return.
	var idled atomic.Bool
	watchdog := time.AfterFunc(s.readTimeout(), func() {
		idled.Store(true)
		cancel()
	})
	defer watchdog.Stop()

	buf := make([]byte, s.chunkSize())
	for {
		n, readErr := response.Body.Read(buf)
		if n > 0 {
			watchdog.Reset(s.readTimeout())
			if _, writeErr := sink.Write(buf[:n]); writeErr != nil {
				return fmt.Errorf("channel: writing upstream bytes to the buffer: %w", writeErr)
			}
		}
		if readErr == nil {
			continue
		}
		if errors.Is(readErr, io.EOF) {
			return nil
		}
		if parentErr := parent.Err(); parentErr != nil {
			return parentErr
		}
		if idled.Load() {
			return ErrUpstreamIdle
		}
		if ctxErr := ctx.Err(); ctxErr != nil {
			return ctxErr
		}
		return fmt.Errorf("channel: reading the upstream: %w", readErr)
	}
}
