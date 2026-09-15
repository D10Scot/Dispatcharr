package channel

import (
	"math"
	"sync"
	"time"
)

// ClientStats is one client's transfer counters, the in-memory form of the
// four fields output/ts/generator.py:508-519 writes into the client's Redis
// hash and get_detailed_channel_info reads back out of it
// (channel_status.py:196-213).
//
// WHICH FIELDS EXIST IS A PROPERTY OF THE OUTPUT FORMAT, not of this type,
// and that asymmetry is Python's. The TS generator writes chunks_sent,
// bytes_sent, avg_rate_KBps, current_rate_KBps and last_active
// (output/ts/generator.py:511-519). The fMP4 generator writes last_active
// and NOTHING ELSE (output/fmp4/generator.py:288-295), so an fMP4 client's
// hash never carries a byte counter and the detail endpoint's three
// `if ... in client_data` guards all miss. Sent is what a TS client calls
// and Touch is what an fMP4 client calls, so the absence has a mechanism
// here rather than a format check in the renderer.
type ClientStats struct {
	// Sends is how many times Sent has been called. Zero means no byte
	// counter was ever recorded, which is what makes BytesSent, AvgRateKBps
	// and CurrentRateKBps absent from the wire rather than zero.
	Sends int64

	// ChunksSent and BytesSent are the TS generator's own counters
	// (:480-481). A keepalive packet counts toward BytesSent there (:392)
	// and here.
	ChunksSent int64
	BytesSent  int64

	// AvgRateKBps is bytes_sent / (now - stream_start) / 1024 (:488), and
	// CurrentRateKBps is the same arithmetic over the gap since the previous
	// Sent call (:491-495). Both are rounded to one decimal place where
	// Python rounds them on the way into Redis (:515-516).
	AvgRateKBps     float64
	CurrentRateKBps float64

	// LastActive is when this client last received bytes, or ConnectedAt
	// when it has received none: client_manager.py:239 seeds the hash field
	// with connected_at at registration.
	LastActive time.Time
}

// clientMeter is the live counter behind ClientStats. One per registered
// client, installed by addClient, shared by the serving goroutine that writes
// it and the status handler that reads it -- hence the mutex, which -race
// would otherwise report on every detail request against a running channel.
type clientMeter struct {
	mu sync.Mutex

	startedAt  time.Time
	lastActive time.Time

	sends      int64
	chunks     int64
	bytes      int64
	currentKBs float64

	// lastStatsAt and lastStatsBytes are output/ts/generator.py:498-499's
	// last_stats_time and last_stats_bytes: updated on EVERY yielded chunk,
	// so current_rate is the rate over one chunk's interval rather than over
	// a sampling window.
	lastStatsAt    time.Time
	lastStatsBytes int64
}

func newClientMeter(at time.Time) *clientMeter {
	return &clientMeter{startedAt: at, lastActive: at, lastStatsAt: at}
}

// Sent records one write to a TS client's socket: n bytes, at `at`.
//
// Called once per chunk rather than once per Read, because the Python
// counter increments inside the `for chunk in chunks` loop (:477-481) and
// current_rate is derived from the gap between consecutive chunks.
func (c Client) Sent(n int, at time.Time) {
	if c.meter == nil {
		return
	}
	m := c.meter
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sends++
	m.chunks++
	m.bytes += int64(n)
	m.lastActive = at
	if elapsed := at.Sub(m.lastStatsAt); elapsed > 0 {
		m.currentKBs = float64(m.bytes-m.lastStatsBytes) / elapsed.Seconds() / 1024
	}
	m.lastStatsAt = at
	m.lastStatsBytes = m.bytes
}

// Touch records that an fMP4 client received bytes, and nothing else:
// output/fmp4/generator.py:288-295 writes last_active and no counter.
func (c Client) Touch(at time.Time) {
	if c.meter == nil {
		return
	}
	m := c.meter
	m.mu.Lock()
	defer m.mu.Unlock()
	m.lastActive = at
}

// Stats is this client's counters as of `at`.
//
// AvgRateKBps is computed at read time from the elapsed wall clock, where
// Python computes it when it writes the hash; the value is the same
// arithmetic over a slightly later `now`. CurrentRateKBps is the stored
// per-chunk rate, because it is a measurement over an interval that has
// already passed and recomputing it here would divide by the gap since the
// last chunk instead.
func (c Client) Stats(at time.Time) ClientStats {
	if c.meter == nil {
		return ClientStats{LastActive: c.ConnectedAt}
	}
	m := c.meter
	m.mu.Lock()
	defer m.mu.Unlock()
	out := ClientStats{
		Sends:           m.sends,
		ChunksSent:      m.chunks,
		BytesSent:       m.bytes,
		CurrentRateKBps: round1(m.currentKBs),
		LastActive:      m.lastActive,
	}
	if elapsed := at.Sub(m.startedAt).Seconds(); elapsed > 0 {
		out.AvgRateKBps = round1(float64(m.bytes) / elapsed / 1024)
	}
	return out
}

// round1 is Python's round(x, 1) at output/ts/generator.py:515-516. Go's
// math.Round is half-away-from-zero and Python's round() is banker's, which
// differ only on an exact .x5 of a rate computed from a byte count over a
// wall-clock interval. Recorded as a stated divergence rather than emulated:
// banker's rounding to one place would need a decimal library and this
// module is stdlib-only (Global Constraint 3).
func round1(v float64) float64 {
	return math.Round(v*10) / 10
}
