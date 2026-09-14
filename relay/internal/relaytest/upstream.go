package relaytest

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"time"
)

// WriteChunk is how much the upstream writes to the wire at a time: 50 TS
// packets, apps/proxy/live_proxy/tests/harness/upstream.py:31's
// _WRITE_CHUNK. Pinned by TestNominalByteRateAndWriteChunkMatchThePythonHarness.
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
	// the relay's side. 2c-5's dead-air trigger (parity-matrix row 2) acts
	// on it.
	DeadAir time.Duration

	// DeadAirAfterBytes sends this many bytes and then nothing at all until
	// the client goes away: a provider that STOPPED rather than one that
	// never started, which is the shape that takes the relay past its
	// init grace period and onto CONNECTION_TIMEOUT (input/manager.py:
	// 1547-1551). Zero means no dead air. harness/standin.py's
	// --dead-air-after-bytes, on the upstream rather than the child.
	DeadAirAfterBytes int
}

// Upstream is a looping TS provider on 127.0.0.1.
type Upstream struct {
	server *httptest.Server

	mu       sync.Mutex
	requests int
	headers  []http.Header
	methods  []string
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
		u.methods = append(u.methods, r.Method)
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

// Methods is the HTTP method of each request the upstream answered, in
// order -- how a test tells a HEAD probe from a GET that would have streamed.
func (u *Upstream) Methods() []string {
	u.mu.Lock()
	defer u.mu.Unlock()
	return append([]string(nil), u.methods...)
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
		if cfg.DeadAirAfterBytes > 0 && sent >= cfg.DeadAirAfterBytes {
			// Connected, silent, and still here: the relay's watchdog is
			// what ends this, by hanging up.
			<-r.Context().Done()
			return
		}

		want := WriteChunk
		if cfg.StopAfterBytes > 0 && cfg.StopAfterBytes-sent < want {
			want = cfg.StopAfterBytes - sent
		}
		if cfg.DeadAirAfterBytes > 0 && cfg.DeadAirAfterBytes-sent < want {
			want = cfg.DeadAirAfterBytes - sent
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
			// Sleep UNTIL DUE, in steps of at most 250 ms so a client that
			// has gone is noticed within a step rather than after the whole
			// wait. An earlier form slept min(wait, 250ms) ONCE, capping the
			// total wait: any rate below ~37,600 B/s was delivered faster
			// than configured -- Rate 0.05 fixtures about three times too
			// fast, row 4's quarter-rate upstream looping every 13.5 s
			// instead of 32 s (issue #300, found by the 2c-4 review).
			for {
				wait := time.Until(due)
				if wait <= 0 || r.Context().Err() != nil {
					break
				}
				time.Sleep(min(wait, 250*time.Millisecond))
			}
		}
	}
}
