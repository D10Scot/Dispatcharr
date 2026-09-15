package buffer

import (
	"context"
	"sync"
	"time"
)

// Fragments is the fMP4 output buffer: the in-memory replacement for the seven
// output_* Redis key families (spec § Stage 2c's key-family table, "fMP4 output
// state"), and the port of apps/proxy/live_proxy/output/fmp4/buffer.py's
// FMP4StreamBuffer.
//
// IT IS NOT A Ring AND MUST NOT BECOME ONE, which is the whole reason this is a
// second type rather than a mode on the first. FMP4StreamBuffer's own docstring
// says it is "functionally identical to StreamBuffer except ... no 188-byte TS
// packet alignment", and that exception is load-bearing in three ways a shared
// type could not express:
//
//   - THE WRITE UNIT IS A WHOLE FRAGMENT, variable length, never a fixed-size
//     chunk. put_fragment (buffer.py:61-82) stores exactly what it is given as
//     one Redis value. Ring packetises at a 188-byte stride into ChunkBytes
//     chunks, which would split a moof from its mdat and hand a player half a
//     fragment.
//   - A BUFFER SHORTER THAN THE JOIN WINDOW POSITIONS A NEW CLIENT AT ITS
//     OLDEST FRAGMENT, and an EMPTY one at 0. _setup_streaming
//     (output/fmp4/generator.py:239-246) falls back to index 0 -- "the oldest
//     available fragment" -- where the TS generator's equivalent falls back to
//     the live head (output/ts/generator.py:292-297). The head fallback is
//     what a client positioned past every fragment it was already promised by
//     the init segment would get.
//   - A ZERO JOIN WINDOW MEANS head-1, NOT head (generator.py:248's
//     `max(0, current - 1)`), so a client with new_client_behind_seconds = 0
//     still receives the most recent fragment. Ring.Head() means the next one.
//
// WHAT IS THE SAME, and is the same on purpose: the cursor convention (the last
// consumed index, so a read returns cursor+1 onwards), the monotonic index
// starting at 1 (Redis INCR on a missing key, buffer.py:68), the immutable
// published slice, the notify-channel wakeup, and the MaxChunksPerRead cap.
//
// THE BYTE BUDGET IS AN ADDITION, and the same one D2 already forced on Ring.
// FMP4StreamBuffer bounds itself with a Redis TTL alone (chunk_ttl on every
// SETEX, buffer.py:71-74) and lets Redis eviction absorb the consequence; with
// the fragments resident in this process a time bound is not a bound. Both
// bounds are enforced, whichever binds first, exactly as Ring does it.
//
// THE COST, STATED: an fMP4 channel holds TWO buffers -- the TS ring its
// upstream fills and this one its remux fills -- so at the same budget it costs
// roughly twice a TS-only channel's memory. Roughly rather than exactly because
// a `-c copy` remux's output is close to but not equal to its input. This is a
// consequence of reproducing Python's architecture (the remux reads the shared
// TS buffer and writes a second one), not a choice this type makes, and it is
// recorded here because spec § Risks' sizing item is stated per channel and an
// fMP4 viewer doubles it.
type Fragments struct {
	budget    int
	retention time.Duration
	now       func() time.Time

	mu sync.RWMutex
	// frags is the store, oldest first.
	frags []Fragment
	// bytes is the resident total, the quantity budget bounds.
	bytes int
	// head is the highest index ever published, monotonic for the buffer's
	// life.
	head uint64
	// init is the init segment: everything the remux emitted before its first
	// moof box. Stored once and replayed to every client before its first
	// fragment (output/fmp4/manager.py:325, generator.py:131-136).
	init []byte
	// ready is closed when init is stored, so a client waits on a channel
	// rather than polling the 0.1s loop _wait_for_fmp4_ready runs
	// (generator.py:184-194).
	ready chan struct{}
	// shut is closed by Close, so a client waiting for an init segment that
	// will now never arrive is woken with an answer rather than waiting out
	// the whole budget. Separate from `ready` so the two outcomes stay
	// distinguishable: a closed `ready` means there IS a segment.
	shut chan struct{}
	// notify is closed and replaced on every publish.
	notify chan struct{}
	closed bool
}

// Fragment is one complete fMP4 fragment: a moof box and everything up to the
// next one.
type Fragment struct {
	// Index is the fragment's position in the monotonic sequence. The first
	// is 1, matching Redis INCR on a missing key (buffer.py:68).
	Index uint64

	// At is when the fragment was published, the equivalent of the
	// chunk_timestamps sorted set (buffer.py:72).
	At time.Time

	// Data is the whole fragment. Immutable once published, and its backing
	// array is never reused, for Chunk's reason: fan-out is slice headers.
	Data []byte
}

// FragmentsConfig is what NewFragments needs.
type FragmentsConfig struct {
	// BudgetBytes is the resident byte bound. Zero means MaxBytesPerChannel.
	BudgetBytes int

	// Retention is the age bound, from the same redis_chunk_ttl the TS ring
	// uses -- buffer.py:32 reads ConfigHelper.redis_chunk_ttl() exactly as
	// input/buffer.py does. Zero means RetentionSeconds.
	Retention time.Duration

	// Now is the clock, injectable so the join-point tests do not sleep. Nil
	// means time.Now.
	Now func() time.Time
}

// NewFragments builds an empty fMP4 buffer.
func NewFragments(cfg FragmentsConfig) *Fragments {
	budget := cfg.BudgetBytes
	if budget <= 0 {
		budget = MaxBytesPerChannel
	}
	retention := cfg.Retention
	if retention <= 0 {
		retention = RetentionSeconds * time.Second
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	return &Fragments{
		budget:    budget,
		retention: retention,
		now:       now,
		ready:     make(chan struct{}),
		shut:      make(chan struct{}),
		notify:    make(chan struct{}),
	}
}

// SetInit stores the init segment and wakes every client waiting for it. The
// first call wins; a later one is ignored, which is what a remux restarted
// without the AAC bitstream filter produces (output/fmp4/manager.py:400-431
// sets the state back to initializing and the reader stores a SECOND init
// segment over the first).
//
// KEEPING THE FIRST IS THE DIVERGENCE, and it is deliberate: Python's SETEX
// overwrites, so a client that connects after the restart gets the new init
// segment and a client already streaming keeps the fragments of both
// generations behind the old one. Overwriting here would hand an already-served
// client's successor an init segment describing a differently-configured
// stream. The restart happens only on the first stderr line of a non-AAC
// channel -- before any fragment has been produced, because the BSF error is
// what stops ffmpeg producing them -- so the two segments are the same stream
// with and without one bitstream filter, and no client has been served either.
// Recorded rather than asserted as identical.
func (f *Fragments) SetInit(data []byte) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.init != nil {
		return
	}
	f.init = data
	close(f.ready)
}

// Init is the init segment, or nil before one has been stored.
func (f *Fragments) Init() []byte {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return f.init
}

// WaitInit blocks until the init segment is stored, the buffer closes, or ctx
// is done. It returns nil when there is an init segment to send, ErrClosed when
// the remux ended without producing one, and ctx.Err() otherwise.
//
// The port of _wait_for_fmp4_ready (output/fmp4/generator.py:175-200), whose
// three outcomes are the same three: the key exists (go), the channel is
// stopping (give up), the deadline passed (give up). The caller supplies the
// deadline; this method does not own it, because the 15-second budget is the
// client loop's constant and not the buffer's.
func (f *Fragments) WaitInit(ctx context.Context) error {
	f.mu.RLock()
	ready, shut := f.ready, f.shut
	f.mu.RUnlock()

	// Checked before the blocking select, so a buffer that already holds an
	// init segment AND is already closed answers nil: the remux ended, but the
	// fragments and the segment it produced are still there to serve, which is
	// what Python's _fetch_init_segment does with a key that still exists.
	select {
	case <-ready:
		return nil
	default:
	}
	select {
	case <-ready:
		return nil
	case <-shut:
		return ErrClosed
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Put publishes one complete fragment and returns its index.
//
// The port of put_fragment (buffer.py:61-82): INCR the index, store the
// fragment whole, timestamp it, evict what has aged out, wake the readers. An
// empty fragment is dropped rather than published, as put_fragment's own
// `if not data` does.
func (f *Fragments) Put(data []byte) uint64 {
	if len(data) == 0 {
		return f.Head()
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.closed {
		return f.head
	}
	// A copy, so the caller's scanning buffer can be reused for the next
	// fragment without corrupting every reader already holding this one.
	// Ring.Write allocates per chunk for the same reason; the comment there
	// is the authority.
	stored := make([]byte, len(data))
	copy(stored, data)

	f.head++
	f.frags = append(f.frags, Fragment{Index: f.head, At: f.now(), Data: stored})
	f.bytes += len(stored)
	f.evictLocked()

	close(f.notify)
	f.notify = make(chan struct{})
	return f.head
}

// evictLocked drops fragments until both bounds hold, oldest first. Callers
// hold mu.
//
// THE NEWEST FRAGMENT IS NEVER EVICTED, whatever the budget says: a single
// fragment larger than the whole budget would otherwise be published and
// dropped in the same call, and the buffer would serve nothing at all rather
// than serving badly. Python has no equivalent because Redis stores the value
// whatever its size.
func (f *Fragments) evictLocked() {
	cutoff := f.now().Add(-f.retention)
	for len(f.frags) > 1 && f.frags[0].At.Before(cutoff) {
		f.bytes -= len(f.frags[0].Data)
		f.frags = append(f.frags[:0], f.frags[1:]...)
	}
	for len(f.frags) > 1 && f.bytes > f.budget {
		f.bytes -= len(f.frags[0].Data)
		f.frags = append(f.frags[:0], f.frags[1:]...)
	}
}

// Head is the highest index published so far, 0 before the first fragment.
func (f *Fragments) Head() uint64 {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return f.head
}

// Oldest is the lowest index still resident, and false when the buffer is
// empty.
func (f *Fragments) Oldest() (uint64, bool) {
	f.mu.RLock()
	defer f.mu.RUnlock()
	if len(f.frags) == 0 {
		return 0, false
	}
	return f.frags[0].Index, true
}

// Bytes is the resident total, for the sizing test.
func (f *Fragments) Bytes() int {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return f.bytes
}

// Read returns every resident fragment after cursor, capped at
// MaxChunksPerRead, with the cursor to pass next and how many indices were lost
// to eviction before the first one returned.
//
// get_chunks (buffer.py:84-117) has NO cap: it pipelines a GET for every index
// from start_index+1 to the head. The cap is ported here for the reason
// Amendment A3.2 gives for the TS ring's: it bounds how much a lagging reader
// HOLDS at one instant, and a held fragment's backing array outlives eviction.
// What a client receives is identical either way -- the loop comes straight
// back for the rest -- so no parity row covers the difference.
//
// `next` is the index of the last fragment ACTUALLY RETURNED, never the
// buffer's tail, for Ring.Read's reason: a next that ran ahead of what was
// handed over would make a capped read a silent content gap.
func (f *Fragments) Read(cursor uint64) (out [][]byte, next uint64, skipped uint64) {
	f.mu.RLock()
	defer f.mu.RUnlock()

	if len(f.frags) == 0 {
		return nil, cursor, 0
	}
	oldest := f.frags[0].Index
	want := cursor + 1
	if want < oldest {
		skipped = oldest - want
		want = oldest
	}
	if want > f.head {
		return nil, cursor, skipped
	}

	out = make([][]byte, 0, min(len(f.frags), MaxChunksPerRead))
	next = cursor
	for _, frag := range f.frags {
		if frag.Index < want {
			continue
		}
		if len(out) == MaxChunksPerRead {
			break
		}
		out = append(out, frag.Data)
		next = frag.Index
	}
	return out, next, skipped
}

// Join returns the cursor a new client starts from, so that its first read
// begins roughly `behind` behind live.
//
// The port of _setup_streaming's else branch (output/fmp4/generator.py:221-252)
// together with find_chunk_index_by_time (buffer.py:119-141), and it differs
// from Ring.Join in BOTH fallbacks -- the whole reason this is not a shared
// method:
//
//	behind > 0, a fragment old enough exists   that fragment's index - 1   (buffer.py:138)
//	behind > 0, nothing is that old            the oldest fragment - 1     (buffer.py:134-136)
//	behind > 0, the buffer is EMPTY            0                           (generator.py:239-241)
//	behind <= 0                                head - 1, floored at 0      (generator.py:248)
//
// Ring.Join's empty case returns the live head, and serveClient reads Head()
// directly for a zero window (output/ts/generator.py:297-303), so the TS
// answers are head and head.
//
// ONLY THE ZERO-WINDOW DIFFERENCE IS OBSERVABLE HERE, and saying so is more
// useful than claiming two. The empty case needs a non-zero head with nothing
// resident, which is reachable in Redis -- the timestamps zset is pruned by
// score while the index key survives -- and is NOT reachable here, because
// evictLocked never drops the last fragment, so an empty store means a head of
// 0 and both rules answer 0. The fallback is written as Python writes it
// regardless, so the two stay comparable if eviction ever changes.
func (f *Fragments) Join(behind time.Duration) uint64 {
	f.mu.RLock()
	defer f.mu.RUnlock()

	if behind <= 0 {
		// generator.py:248's max(0, current - 1): the most recent fragment is
		// still delivered, where the TS path's zero window means the next one.
		if f.head == 0 {
			return 0
		}
		return f.head - 1
	}
	if len(f.frags) == 0 {
		// generator.py:239-241: "not enough buffer - start at oldest available
		// fragment", which with nothing resident is everything from the first.
		return 0
	}
	cutoff := f.now().Add(-behind)
	for i := len(f.frags) - 1; i >= 0; i-- {
		if !f.frags[i].At.After(cutoff) {
			return f.frags[i].Index - 1
		}
	}
	return f.frags[0].Index - 1
}

// Wait blocks until a fragment past cursor exists, the buffer closes, or ctx is
// done. Ring.Wait's contract exactly, including taking the caller's cursor to
// close the lost-wakeup window its own comment describes.
func (f *Fragments) Wait(ctx context.Context, cursor uint64) error {
	f.mu.RLock()
	ch := f.notify
	closed := f.closed
	fresh := f.head > cursor
	f.mu.RUnlock()

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

// Closed reports whether the buffer is shut.
func (f *Fragments) Closed() bool {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return f.closed
}

// Close wakes every waiter, including one blocked in WaitInit, and refuses
// further fragments. Idempotent.
func (f *Fragments) Close() {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.closed {
		return
	}
	f.closed = true
	close(f.notify)
	// The init waiters too: a remux that died before producing an init segment
	// must not leave a client blocked for the whole 15-second budget when the
	// answer is already known.
	close(f.shut)
}
