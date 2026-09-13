// Package buffer holds the in-memory ring buffer and its chunk fan-out.
//
// At 2c-1 it holds only the sizing constants, because spec § Stage 2c's
// "Buffer depth -- an explicit open item" makes settling them this PR's job:
// "2c's first PR must resolve with a real number, not carry forward
// unresolved". The ring itself arrives in 2c-2.
//
// WHY A BOUND AT ALL. The Python relay keeps chunks in Redis under a 60
// second TTL and lets Redis's own eviction absorb the memory consequence. D2
// deletes that absorber: every live channel's buffered window becomes
// resident in this process. A time bound is then not a bound -- at twice the
// reference bitrate the same 60 seconds costs twice the memory, and nothing
// notices until the process is OOM-killed and every channel dies at once.
//
// THE DERIVATION, with every input's source:
//
//	chunk size      255,868 bytes (188 x 1361)  apps/proxy/config.py:15
//	retention       60 seconds                  apps/proxy/config.py:71
//	join point      5 seconds behind live       apps/proxy/config.py:57
//	reference rate  10 Mbit/s                   STATED, not measured -- see below
//
//	10,000,000 bit/s / 8        = 1,250,000 byte/s
//	x 60 s                      = 75,000,000 bytes per channel
//	/ 255,868                   = 293.12 chunks
//	round up                    = 300 chunks
//	x 255,868                   = 76,760,400 bytes ~= 73.2 MiB per channel
//
// The reference bitrate is an assumption, not a measurement: nothing in the
// tree records real channel bitrates (avg_bitrate_kbps is displayed and never
// thresholded). 10 Mbit/s is a realistic ceiling for the 1080p MPEG-TS remux
// the default FFmpeg profile produces. It sizes the cap; it is not a limit
// anything enforces.
//
// BOTH BOUNDS ARE ENFORCED, whichever binds first, and that is what preserves
// parity. Retention stays 60 seconds so a client's view of how far back the
// buffer reaches matches Python's. The byte cap sits behind it so memory is
// bounded regardless of bitrate. They cross at 10.23 Mbit/s: below it
// behaviour is Python's exactly, above it retention shortens and memory does
// not grow -- a deliberate divergence, in the safe direction.
//
// Aggregate, stated and not enforced: ten concurrently-owned channels at the
// cap is ~732 MiB in one process. Per the user's decision the cap is per
// channel with no host-memory check; sizing against real channel counts is
// spec § Risks' pre-deployment item, not this package's.
package buffer

const (
	// TSPacketSize is the MPEG-TS packet size every chunk is realigned to.
	// apps/proxy/live_proxy/constants.py's TS_PACKET_SIZE.
	TSPacketSize = 188

	// ChunkBytes is the ring's write unit: 188 * 1361, from
	// apps/proxy/config.py:15's BaseConfig.BUFFER_CHUNK_SIZE. Note that
	// apps/proxy/live_proxy/input/buffer.py:42 reads it with a fallback of
	// TS_PACKET_SIZE * 5644, which is an UNREACHABLE default because the
	// class attribute always exists -- the effective Python chunk is this
	// number, a quarter of what that call site looks like.
	ChunkBytes = TSPacketSize * 1361

	// RetentionSeconds is the parity half of the bound: the Redis chunk TTL
	// the Python relay applies, apps/proxy/config.py:71's default of 60.
	RetentionSeconds = 60

	// JoinBehindSeconds is how far behind live a new client starts,
	// apps/proxy/config.py:57's new_client_behind_seconds. Not a bound --
	// it is the figure the bound must stay above, asserted in the tests.
	JoinBehindSeconds = 5

	// ReferenceBitrateBitsPerSecond sizes the cap. An assumption; see above.
	ReferenceBitrateBitsPerSecond = 10_000_000

	// MaxChunksPerChannel is 293.12 rounded up to a round number.
	MaxChunksPerChannel = 300

	// MaxBytesPerChannel is the memory bound. This, not the chunk count, is
	// the thing that must not grow; the count is how it is enforced, because
	// the chunk is the ring's eviction unit.
	MaxBytesPerChannel = MaxChunksPerChannel * ChunkBytes
)

// ChunksForBytes converts a byte budget to a whole number of chunks at the
// default chunk size.
func ChunksForBytes(budget int) int {
	return chunksFor(budget, ChunkBytes)
}

// chunksFor is the one implementation, so a ring sized from a chunk size the
// control plane sent and one sized from the constant can never round
// differently. A budget below one chunk still yields one, because a
// zero-length ring would deadlock the writer.
func chunksFor(budget, chunkBytes int) int {
	if chunkBytes <= 0 || budget < chunkBytes {
		return 1
	}
	return budget / chunkBytes
}
