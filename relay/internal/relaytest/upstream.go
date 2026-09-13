package relaytest

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"time"
)

// WriteChunk is how much the upstream writes to the wire at a time: 50 TS
// packets, harness/upstream.py's _WRITE_CHUNK.
const WriteChunk = PacketSize * 50

// Config shapes one Upstream. The zero value is a valid unpaced upstream
// serving 512 synthetic packets on a loop, which is what most tests want.
type Config struct {
	// Payload is the asset to loop. Nil means SyntheticTS(512, 0x100).
	Payload []byte

	// Status is the response status. Zero means 200; any other value is sent
	// with a short JSON body and no stream.
	Status int

	// Rate paces the response at Rate * NominalByteRate bytes per second.
	// Zero means unpaced.
	//
	// UNPACED BY DEFAULT, and that is a DELIBERATE divergence from
	// harness/upstream.py, whose FakeUpstream defaults to 1.0. Its docstring
	// gives the reason: unpaced, it pushed ~34 MB/s into Redis and filled DB
	// 0 -- shared with the Celery broker and the Django cache -- to 2.17 GB in
	// 50 seconds, taking the test process down. Spec D2 deletes that failure
	// mode: the Go ring is bounded at MaxBytesPerChannel per channel by
	// construction, so an unpaced upstream costs a bounded 73 MiB and a much
	// faster test. Set Rate when the test's subject is throughput.
	Rate float64

	// StopAfterBytes ends the response after this many bytes. Zero means the
	// loop runs until the client goes away.
	StopAfterBytes int

	// Abrupt makes StopAfterBytes abort the response rather than end it
	// cleanly, so the reader sees a broken connection instead of EOF.
	Abrupt bool

	// DeadAir sends the 200 and the headers, then nothing at all for this
	// long -- exactly what a provider that stops producing looks like from
	// the relay's side. The failover trigger that acts on it is 2c-5's; this
	// PR only needs to not hang forever on one.
	DeadAir time.Duration
}

// Upstream is a looping TS provider on 127.0.0.1.
type Upstream struct {
	server *httptest.Server

	mu       sync.Mutex
	requests int
	headers  []http.Header
}

// NewUpstream starts an upstream. Register its Close with t.Cleanup.
func NewUpstream(cfg Config) *Upstream {
	payload := cfg.Payload
	if payload == nil {
		payload = SyntheticTS(512, 0x100)
	}
	if len(payload) == 0 {
		panic("relaytest: payload must not be empty")
	}

	u := &Upstream{}
	u.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u.mu.Lock()
		u.requests++
		u.headers = append(u.headers, r.Header.Clone())
		u.mu.Unlock()
		u.serve(w, r, cfg, payload)
	}))
	return u
}

// URL is the upstream's stream URL.
func (u *Upstream) URL() string { return u.server.URL + "/live.ts" }

// Requests is how many HTTP requests the upstream has answered. The count a
// "three clients share exactly one upstream connection" assertion reads.
func (u *Upstream) Requests() int {
	u.mu.Lock()
	defer u.mu.Unlock()
	return u.requests
}

// Headers is the header set of each request the upstream answered, in order.
// Cloned at receipt, so a test reading them races nothing.
func (u *Upstream) Headers() []http.Header {
	u.mu.Lock()
	defer u.mu.Unlock()
	return append([]http.Header(nil), u.headers...)
}

// Close stops the server and waits for its handlers.
func (u *Upstream) Close() { u.server.Close() }

func (u *Upstream) serve(w http.ResponseWriter, r *http.Request, cfg Config, payload []byte) {
	if cfg.Status != 0 && cfg.Status != http.StatusOK {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(cfg.Status)
		_, _ = w.Write([]byte(`{"error":"relaytest: configured status"}`))
		return
	}

	w.Header().Set("Content-Type", "video/mp2t")
	w.WriteHeader(http.StatusOK)
	rc := http.NewResponseController(w)
	if err := rc.Flush(); err != nil {
		return
	}

	if cfg.DeadAir > 0 {
		select {
		case <-r.Context().Done():
		case <-time.After(cfg.DeadAir):
		}
		return
	}

	var rate float64
	if cfg.Rate > 0 {
		rate = cfg.Rate * NominalByteRate
	}

	sent := 0
	at := 0
	started := time.Now()
	for {
		if cfg.StopAfterBytes > 0 && sent >= cfg.StopAfterBytes {
			if cfg.Abrupt {
				// The stdlib's own way to end a response without a clean
				// terminator. It also suppresses the server's stack trace,
				// which an ordinary panic would print over every test.
				panic(http.ErrAbortHandler)
			}
			return
		}
		if r.Context().Err() != nil {
			return
		}

		want := WriteChunk
		if cfg.StopAfterBytes > 0 && cfg.StopAfterBytes-sent < want {
			want = cfg.StopAfterBytes - sent
		}
		piece := make([]byte, 0, want)
		for len(piece) < want {
			take := min(want-len(piece), len(payload)-at)
			piece = append(piece, payload[at:at+take]...)
			at = (at + take) % len(payload)
		}

		if _, err := w.Write(piece); err != nil {
			// The relay closed its side -- an ordinary end to a tune.
			return
		}
		if err := rc.Flush(); err != nil && !errors.Is(err, http.ErrNotSupported) {
			return
		}
		sent += len(piece)

		if rate > 0 {
			due := started.Add(time.Duration(float64(sent) / rate * float64(time.Second)))
			if wait := time.Until(due); wait > 0 {
				time.Sleep(min(wait, 250*time.Millisecond))
			}
		}
	}
}
