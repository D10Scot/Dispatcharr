package buffer

import (
	"context"
	"errors"
	"sync"
	"time"
)

// MaxChunksPerRead bounds how many chunks one Read hands back.
//
// The port of get_optimized_client_data's MAX_CHUNKS
// (apps/proxy/live_proxy/input/buffer.py:329), and the ONLY one of that
// function's four constants 2c-3 ports. MIN_CHUNKS, TARGET_SIZE and MAX_SIZE
// exist to amortise a Redis round trip per chunk, and an in-memory ring has
// no round trip to amortise -- 2c-2's reasoning, unchanged. MAX_CHUNKS is
// different in kind: it bounds how much a lagging reader HOLDS at one
// instant, and a held chunk's backing array stays alive after the ring has
// evicted it. Uncapped, one reader behind the head can pin a whole ring's
// worth of evicted chunks on top of the resident ring -- 2 x
// MaxBytesPerChannel, about 146 MiB, where 2c-1's sizing note states 73 MiB.
// Capped, the extra is at most 20 chunks, about 5 MiB, per DISTINCT lagging
// cursor; readers at the same cursor share one set of arrays.
//
// 20 chunks at the default chunk size is 5,117,360 bytes, which is what the
// Python cap is worth too: MAX_SIZE (2 MiB) gates only the SECOND, top-up
// fetch, never the initial min(chunks_behind, MAX_CHUNKS) one
// (input/buffer.py:348-371, read in full).
const MaxChunksPerRead = 20

// ErrClosed is returned by Write and Wait once the ring has been closed. A
// named sentinel rather than a message: callers test the condition with
// errors.Is, and a substring check on an error string pins nothing when more
// than one site can produce the text (Global Constraint, hollow shape 5).
var ErrClosed = errors.New("buffer: ring is closed")

// Chunk is one published unit of the ring.
//
// Data is IMMUTABLE once a Chunk is published and its backing array is never
// reused for a later chunk. That is what makes fan-out to N clients N slice
// headers over one backing array with no refcounting and no copy per client
// (spec D2). A reader may hold Data after the chunk has been evicted; the
// garbage collector keeps the array alive exactly as long as someone holds it.
type Chunk struct {
	// Index is the chunk's position in the channel's monotonic sequence. The
	// first chunk a channel ever publishes is 1, matching Redis INCR on a
	// missing key (apps/proxy/live_proxy/input/buffer.py:103).
	Index uint64

	// At is when the chunk was published, the Go equivalent of the
	// chunk_timestamps sorted set (input/buffer.py:109).
	At time.Time

	// Data is a whole number of 188-byte TS packets.
	Data []byte
}

// Config is what New needs. Every field has a working zero value except
// BudgetBytes, which is required, because a ring sized by accident is a ring
// nobody chose the memory profile of.
type Config struct {
	// BudgetBytes is the per-channel memory bound, converted to a chunk count
	// by ChunksForBytes. MaxBytesPerChannel is the deployment default.
	BudgetBytes int

	// Retention is the age bound. Zero means RetentionSeconds.
	Retention time.Duration

	// ChunkBytes is the ring's write unit. Zero means the ChunkBytes
	// constant.
	//
	// Configurable from 2c-2 onwards because Amendment A1.4 puts
	// BUFFER_CHUNK_SIZE on the wire: the control plane sends the effective
	// value and the relay uses it, so the constant stops being an operative
	// copy of a Python literal and becomes only the derivation input
	// MaxChunksPerChannel is computed from. The two are pinned to the same
	// number from both sides -- a Go test asserts the constant is 255868, and
	// A1.4's Python value test asserts the wire carries 188 * 1361.
	ChunkBytes int

	// Now is the clock, injectable so the join-point tests do not sleep. Nil
	// means time.Now.
	Now func() time.Time
}

// Ring is one channel's in-memory buffer: the packetiser, the monotonic chunk
// index, the bounded chunk store and the reader wake-up.
//
// CONCURRENCY. One writer goroutine calls Write, ResetPosition and Close; any
// number of reader goroutines call Read, Head, Join, Oldest and Wait. Every
// field below is guarded by mu -- writers take Lock, readers take RLock. The
// only thing that leaves the lock is a Chunk's Data slice header, which is
// safe precisely because of the immutability rule on Chunk.
//
// WHAT -race SHOULD CATCH IF THIS IS WRONG. Reading head, chunks or notify
// without the lock is an unsynchronised access the detector reports directly.
// It does NOT catch the immutability rule on its own -- a writer reusing a
// published backing array only races when a reader happens to be reading that
// array at that instant -- which is why TestAPublishedChunkIsNeverRewritten
// asserts content rather than relying on the detector.
type Ring struct {
	capacity   int
	chunkBytes int
	retention  time.Duration
	now        func() time.Time

	mu sync.RWMutex
	// chunks is the store, oldest first. Its length never exceeds capacity.
	chunks []Chunk
	// head is the highest index ever published. It is MONOTONIC FOR THE
	// CHANNEL'S LIFE and ResetPosition deliberately does not touch it
	// (parity-matrix row 7).
	head uint64
	// partial is the tail of the byte stream that is not yet a whole
	// 188-byte packet, carried into the next Write (row 9).
	partial []byte
	// pending is whole packets accumulated but not yet a full chunk.
	pending []byte
	// notify is closed and replaced on every publish, so a reader can wait
	// on it inside a select alongside its own context. A sync.Cond cannot be
	// selected on, so a reader blocked in Cond.Wait could not be woken by a
	// client disconnecting -- a goroutine leak per abandoned tune.
	notify chan struct{}
	closed bool

	// total is every byte the upstream has handed this ring, including the
	// partial packet not yet published. The in-memory equivalent of the
	// metadata hash's total_bytes (apps/proxy/live_proxy/channel_status.py:510),
	// which the status endpoints render and derive avg_bitrate_kbps from.
	total uint64
}

// New builds a ring. BudgetBytes below one chunk still yields a one-chunk
// ring, because a zero-length ring would deadlock the writer.
func New(cfg Config) *Ring {
	retention := cfg.Retention
	if retention <= 0 {
		retention = RetentionSeconds * time.Second
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	chunkBytes := cfg.ChunkBytes
	if chunkBytes <= 0 {
		chunkBytes = ChunkBytes
	}
	capacity := chunksFor(cfg.BudgetBytes, chunkBytes)
	return &Ring{
		capacity:   capacity,
		chunkBytes: chunkBytes,
		retention:  retention,
		now:        now,
		chunks:     make([]Chunk, 0, capacity),
		notify:     make(chan struct{}),
	}
}

// Write packetises p and publishes whole chunks. It implements io.Writer so
// the upstream reader is an io.Copy into the ring.
//
// THE PACKETISATION IS A STRIDE, NOT A SYNC-BYTE SEARCH, and that is parity,
// not an oversight. input/buffer.py:79-91 takes the largest multiple of 188 in
// (carried partial + new data) and carries the remainder forward; it never
// scans for 0x47. A Go implementation that searched for the sync byte would
// resynchronise a stream Python passes through unchanged, which is a
// divergence a client can see. Do not "improve" this.
func (r *Ring) Write(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed {
		return 0, ErrClosed
	}

	// The carry is the accumulator: r.partial's own array is extended, then
	// immediately replaced below, so no reader ever sees an intermediate state.
	combined := append(r.partial, p...)
	complete := (len(combined) / TSPacketSize) * TSPacketSize
	if complete == 0 {
		r.total += uint64(len(p))
		r.partial = combined
		return len(p), nil
	}
	r.total += uint64(len(p))
	r.pending = append(r.pending, combined[:complete]...)
	// Copy rather than reslice: combined's backing array is r.partial's, and
	// holding a tail of it would pin the whole accumulated buffer alive for
	// as long as the partial packet lives.
	r.partial = append(make([]byte, 0, TSPacketSize), combined[complete:]...)

	published := false
	for len(r.pending) >= r.chunkBytes {
		// A fresh allocation per chunk. Reusing one array across chunks would
		// corrupt every reader already holding the previous chunk, silently.
		data := make([]byte, r.chunkBytes)
		copy(data, r.pending[:r.chunkBytes])
		r.pending = append(r.pending[:0], r.pending[r.chunkBytes:]...)

		r.head++
		r.evictLocked()
		r.chunks = append(r.chunks, Chunk{Index: r.head, At: r.now(), Data: data})
		published = true
	}

	if published {
		close(r.notify)
		r.notify = make(chan struct{})
	}
	return len(p), nil
}

// evictLocked drops chunks until there is room for one more, under BOTH
// bounds, whichever binds first (Ruling R2 of the 2c-1 plan). Callers hold mu.
func (r *Ring) evictLocked() {
	cutoff := r.now().Add(-r.retention)
	for len(r.chunks) > 0 && r.chunks[0].At.Before(cutoff) {
		r.chunks = append(r.chunks[:0], r.chunks[1:]...)
	}
	for len(r.chunks) >= r.capacity {
		r.chunks = append(r.chunks[:0], r.chunks[1:]...)
	}
}

// ResetPosition clears the packetiser for a clean stream transition, exactly
// as input/buffer.py:136-168 does on a failover: the carried partial packet
// and the not-yet-published bytes go, so the old upstream's trailing bytes are
// never concatenated with the new upstream's first ones into a corrupt packet.
//
// It does NOT touch head, and that omission is the behaviour parity-matrix
// row 7 pins: the chunk index is monotonic for the channel's life, which is
// why a stream switch does not disturb a connected client.
func (r *Ring) ResetPosition() {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.partial = nil
	r.pending = nil
}

// Head is the highest index published so far, 0 before the first chunk.
func (r *Ring) Head() uint64 {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.head
}

// TotalBytes is every byte the upstream has written to this ring.
func (r *Ring) TotalBytes() uint64 {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.total
}

// Oldest is the lowest index still resident, and false when the ring is empty.
func (r *Ring) Oldest() (uint64, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	if len(r.chunks) == 0 {
		return 0, false
	}
	return r.chunks[0].Index, true
}

// Read returns every resident chunk after cursor.
//
// cursor is the LAST CONSUMED index, Python's local_index convention
// (output/ts/generator.py), so the first chunk returned is cursor+1 when it is
// still resident. next is the cursor to pass to the following call, and
// skipped is how many indices were lost to eviction before the first chunk
// returned -- the in-memory equivalent of find_oldest_available_chunk's jump
// (input/buffer.py:407-452), reported rather than silently absorbed so a
// caller can log a real gap.
//
// Python's get_optimized_client_data batching (3..20 chunks, a 1 MB target and
// a 2 MB cap, input/buffer.py:302-372) is deliberately NOT ported: it amortises
// a Redis round trip per chunk, and an in-memory ring has no round trip to
// amortise. What a client receives is identical; only the size of each write
// to its socket differs, which no parity row covers.
func (r *Ring) Read(cursor uint64) (chunks [][]byte, next uint64, skipped uint64) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if len(r.chunks) == 0 {
		return nil, cursor, 0
	}
	oldest := r.chunks[0].Index
	want := cursor + 1
	if want < oldest {
		skipped = oldest - want
		want = oldest
	}
	if want > r.head {
		return nil, cursor, skipped
	}

	// Selected by comparing indices rather than by converting (want - oldest)
	// to an int offset. The offset form is provably in range -- want is at
	// least oldest and at most head -- but gosec cannot see the proof and
	// reports G115, integer overflow conversion uint64 -> int. Suppressing it
	// would have been the smaller diff and the worse answer: this form needs
	// no #nosec, costs one pass over at most `capacity` slice headers, and is
	// correct without relying on the chunks being contiguous.
	//
	// next IS THE INDEX OF THE LAST CHUNK ACTUALLY APPENDED TO out, tracked as
	// the loop goes, NOT r.chunks[len(r.chunks)-1].Index. The two are
	// numerically identical today because this call always returns every
	// resident chunk from want through head -- there is no batch cap in this
	// PR. That equivalence is an accident of this PR's shape, not a property
	// of the method: the day a caller batches reads (2c-3's own plan already
	// names get_optimized_client_data's 3-to-20-chunk cap as the Python
	// precedent this in-memory ring does not need), returning the RING's tail
	// index while having handed back fewer chunks would silently advance the
	// caller's cursor past chunks it was never given -- an invisible content
	// gap, since Read reports skipped only for chunks lost to eviction
	// BEFORE want, never for ones withheld after it. Computing next from what
	// was actually appended costs nothing today and is correct regardless of
	// whether a future cap exists.
	out := make([][]byte, 0, min(len(r.chunks), MaxChunksPerRead))
	next = cursor
	for _, c := range r.chunks {
		if c.Index < want {
			continue
		}
		// The cap. next keeps tracking the last chunk APPENDED, which is
		// 2c-2's contract and is what makes a capped read correct rather than
		// a silent gap: a next that ran ahead to the ring's tail would make a
		// lagging client skip everything this call did not hand it.
		if len(out) == MaxChunksPerRead {
			break
		}
		out = append(out, c.Data)
		next = c.Index
	}
	return out, next, skipped
}

// Join returns the cursor a new client starts from, so that its first read
// begins roughly behind seconds behind live.
//
// It collapses three Python call sites into one function, and the collapse is
// exact rather than approximate:
//
//   - find_chunk_index_by_time (input/buffer.py:479-512) asks the
//     chunk_timestamps sorted set for the NEWEST chunk at least `behind` old
//     and returns its index minus one.
//   - the same function's own fallback takes the oldest chunk in the set when
//     nothing is that old -- "the buffer is shorter than the window".
//   - _setup_streaming (output/ts/generator.py:264-302) falls back to the live
//     head when there is no timestamp data at all, i.e. when the ring is empty.
//
// The Redis version also has a branch for "the timestamps key exists but the
// chunks have expired out from under it". A ring evicts the timestamp and the
// chunk together, by construction, so that state cannot arise here.
func (r *Ring) Join(behind time.Duration) uint64 {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if len(r.chunks) == 0 {
		return r.head
	}
	cutoff := r.now().Add(-behind)
	for i := len(r.chunks) - 1; i >= 0; i-- {
		if !r.chunks[i].At.After(cutoff) {
			return r.chunks[i].Index - 1
		}
	}
	return r.chunks[0].Index - 1
}

// Wait blocks until a chunk past cursor exists, the ring closes, or ctx is
// done. It returns ctx.Err() on cancellation, ErrClosed once the ring is
// closed with nothing left past cursor, and nil when there is data to read.
//
// IT TAKES THE CALLER'S CURSOR, and that is what closes a lost wakeup rather
// than a nicety. A reader calls Read, finds nothing, then calls Wait; a
// publish landing between the two closes the notify channel the reader has not
// looked at yet and installs a fresh one, so a cursorless Wait blocks on a
// chunk that is already resident and the client stalls until the NEXT publish
// -- seconds, at a trickle. Reading head and notify under the same RLock is
// what makes the check and the subscription atomic with respect to Write,
// which takes the write lock for both.
func (r *Ring) Wait(ctx context.Context, cursor uint64) error {
	r.mu.RLock()
	ch := r.notify
	closed := r.closed
	fresh := r.head > cursor
	r.mu.RUnlock()

	// Freshness first, so a ring that closed with residual chunks still hands
	// them over: the caller reads, comes back, and gets ErrClosed then.
	if fresh {
		return nil
	}
	if closed {
		return ErrClosed
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-ch:
		return nil
	}
}

// Closed reports whether the ring is shut, i.e. whether anything will ever be
// published to it again. The manager reads it to tell a running channel from a
// finished one.
func (r *Ring) Closed() bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.closed
}

// Close wakes every waiter and refuses further writes. It is idempotent.
func (r *Ring) Close() {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed {
		return
	}
	r.closed = true
	close(r.notify)
}
