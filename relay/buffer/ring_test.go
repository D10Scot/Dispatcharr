package buffer

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// A small ring, so a test reaches eviction in a few kilobytes instead of 73
// megabytes. The chunk size is a whole number of packets, as the real one is.
const (
	testChunk  = TSPacketSize * 4 // 752 bytes
	testBudget = testChunk * 8    // eight chunks
)

func newTestRing(t *testing.T, now func() time.Time) *Ring {
	t.Helper()
	return New(Config{BudgetBytes: testBudget, ChunkBytes: testChunk, Now: now})
}

// A clock a test drives by hand, so the join-point and retention tests assert
// on time without spending any.
type fakeClock struct {
	mu sync.Mutex
	at time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.at
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.at = c.at.Add(d)
}

// drain reads everything resident from cursor and concatenates it.
func drain(r *Ring, cursor uint64) ([]byte, uint64) {
	chunks, next, _ := r.Read(cursor)
	var out []byte
	for _, c := range chunks {
		out = append(out, c...)
	}
	return out, next
}

// Parity-matrix row 9. The oracle is relaytest.SyntheticTS's embedded packet
// indices, which the ring never sees and cannot compute -- a test that asked
// the ring where its own packet boundaries were would pass with the
// packetiser deleted.
//
// The write sizes are deliberately coprime with 188 and with each other, so
// every write ends mid-packet and the carry is exercised on every one of them.
func TestWritePublishesWholePacketsInUnbrokenOrder(t *testing.T) {
	r := newTestRing(t, nil)
	// Twenty-eight packets is seven chunks, inside the eight-chunk ring, so
	// nothing is evicted and the delivered stream can be compared against the
	// source from packet zero.
	source := relaytest.SyntheticTS(28, 0x100)

	for offset := 0; offset < len(source); {
		for _, size := range []int{1, 187, 189, 63, 401} {
			if offset >= len(source) {
				break
			}
			end := min(offset+size, len(source))
			if _, err := r.Write(source[offset:end]); err != nil {
				t.Fatalf("Write: %v", err)
			}
			offset = end
		}
	}

	got, _ := drain(r, 0)
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the delivered stream is not whole TS packets: %s", problem)
	}
	for i := 0; i < len(got); i += TSPacketSize {
		want := i / TSPacketSize
		if idx := relaytest.PacketIndex(got[i : i+TSPacketSize]); idx != want {
			t.Fatalf("packet at byte %d carries index %d, want %d -- the packetiser "+
				"lost, duplicated or reordered bytes", i, idx, want)
		}
	}
	if len(got)%testChunk != 0 {
		t.Fatalf("delivered %d bytes, which is not a whole number of %d-byte chunks", len(got), testChunk)
	}
}

// The carry itself, in isolation and at its boundary: 187 bytes is one short
// of a packet and must publish nothing; the 188th byte must complete it.
func TestAPartialPacketIsCarriedIntoTheNextWrite(t *testing.T) {
	r := newTestRing(t, nil)
	packet := relaytest.SyntheticTS(1, 0x100)

	if _, err := r.Write(packet[:187]); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if head := r.Head(); head != 0 {
		t.Fatalf("head = %d after 187 bytes, want 0 -- a partial packet must not be published", head)
	}

	// Complete the first packet and supply enough to fill exactly one chunk.
	rest := relaytest.SyntheticTS(testChunk/TSPacketSize, 0x100)[187:]
	if _, err := r.Write(rest); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if head := r.Head(); head != 1 {
		t.Fatalf("head = %d, want 1", head)
	}
	got, _ := drain(r, 0)
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the carried byte was lost or misplaced: %s", problem)
	}
	if relaytest.PacketIndex(got[:TSPacketSize]) != 0 {
		t.Fatal("the first delivered packet is not the first packet written")
	}
}

// Spec D2's immutability rule. A reader holds a chunk's slice for as long as
// it takes to write it to a socket, which can outlast the chunk's residency;
// reusing a backing array would corrupt that reader silently.
//
// ASSERTS CONTENT, NOT THE RACE DETECTOR, and the distinction is the point.
// -race only reports an overlap that actually happens, so a test relying on it
// would pass or fail depending on scheduling. This one reddens deterministically.
func TestAPublishedChunkIsNeverRewritten(t *testing.T) {
	r := newTestRing(t, nil)
	// One chunk's worth, then enough more to evict it twice over.
	perChunk := testChunk / TSPacketSize
	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
		t.Fatalf("Write: %v", err)
	}

	chunks, _, _ := r.Read(0)
	if len(chunks) != 1 {
		t.Fatalf("read %d chunks, want 1", len(chunks))
	}
	held := chunks[0]
	snapshot := append([]byte(nil), held...)

	for range 20 {
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x101)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}

	for i := range snapshot {
		if held[i] != snapshot[i] {
			t.Fatalf("byte %d of a chunk a reader still holds changed from %#02x to %#02x "+
				"after later writes: a published chunk's backing array was reused",
				i, snapshot[i], held[i])
		}
	}
}

// Parity-matrix row 7. reset_buffer_position clears _write_buffer and
// _partial_packet and never touches self.index, which is why a stream switch
// does not disturb a connected client.
func TestResetPositionDoesNotRewindTheChunkIndex(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize
	for range 3 {
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	before := r.Head()
	if before != 3 {
		t.Fatalf("head = %d before the switch, want 3", before)
	}

	r.ResetPosition()

	if after := r.Head(); after != before {
		t.Fatalf("head = %d after a stream switch, want %d -- the chunk index is "+
			"monotonic for the channel's life and a switch never resets it", after, before)
	}
	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x101)); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if after := r.Head(); after != before+1 {
		t.Fatalf("head = %d after the next chunk, want %d", after, before+1)
	}
}

// The other half of reset_buffer_position: the old upstream's trailing bytes
// must NOT be concatenated with the new upstream's first ones, because the
// spliced packet breaks audio decoder sync in the client.
func TestResetPositionDropsTheCarriedPartialPacket(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize

	old := relaytest.SyntheticTS(1, 0x100)
	if _, err := r.Write(old[:100]); err != nil { // 100 bytes of a packet, carried
		t.Fatalf("Write: %v", err)
	}
	r.ResetPosition()
	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x101)); err != nil {
		t.Fatalf("Write: %v", err)
	}

	got, _ := drain(r, 0)
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the switch spliced the old stream's partial packet onto the new one: %s", problem)
	}
	if got[1] != 0x01 || got[2] != 0x01 {
		t.Fatalf("the first delivered packet is on PID %#04x, not the new stream's 0x101 -- "+
			"the carried partial packet survived the switch",
			int(got[1]&0x1F)<<8|int(got[2]))
	}
}

// Parity-matrix row 8's mechanism. find_chunk_index_by_time asks for the
// NEWEST chunk at least `behind` old and positions one before it, so the
// client's first read starts at that chunk.
func TestJoinStartsRoughlyBehindLive(t *testing.T) {
	clock := &fakeClock{at: time.Unix(1_700_000_000, 0)}
	r := newTestRing(t, clock.now)
	perChunk := testChunk / TSPacketSize

	// Six chunks, one per second. The ring holds eight, so none is evicted.
	for range 6 {
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
		clock.advance(time.Second)
	}

	// Head is 6, published at t+0..t+5, and "now" is t+6. Three seconds back
	// is t+3, whose newest chunk at or before it is chunk 4 (published t+3).
	cursor := r.Join(3 * time.Second)
	if cursor != 3 {
		t.Fatalf("Join(3s) = %d, want 3 so the next read starts at chunk 4; head is %d",
			cursor, r.Head())
	}
	if cursor >= r.Head() {
		t.Fatalf("Join(3s) positioned at or past the live head (%d) -- a joining client "+
			"would get no backlog at all", r.Head())
	}
}

// The fallback inside find_chunk_index_by_time: nothing is old enough, so the
// oldest chunk in the buffer is where the client starts.
func TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort(t *testing.T) {
	clock := &fakeClock{at: time.Unix(1_700_000_000, 0)}
	r := newTestRing(t, clock.now)
	perChunk := testChunk / TSPacketSize

	for range 3 {
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
		clock.advance(100 * time.Millisecond)
	}

	if cursor := r.Join(30 * time.Second); cursor != 0 {
		t.Fatalf("Join(30s) on a 0.3s buffer = %d, want 0 (one before the oldest chunk)", cursor)
	}
}

// _setup_streaming's last resort: no timestamp data at all, start at live.
func TestJoinOnAnEmptyRingStartsAtTheHead(t *testing.T) {
	r := newTestRing(t, nil)
	if cursor := r.Join(5 * time.Second); cursor != 0 {
		t.Fatalf("Join on an empty ring = %d, want 0 (the head)", cursor)
	}
}

// A client the writer outran. Python discovers this through a failed read and
// jumps to find_oldest_available_chunk; the ring reports the jump instead of
// absorbing it, so the caller can log a real gap.
func TestReadReportsWhatEvictionSkipped(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize
	for range 12 { // twelve chunks into an eight-chunk ring
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}

	chunks, next, skipped := r.Read(0)
	if skipped == 0 {
		t.Fatal("Read from a cursor the ring has evicted past reported no skip")
	}
	oldest, ok := r.Oldest()
	if !ok {
		t.Fatal("the ring is empty after twelve writes")
	}
	if want := oldest - 1; skipped != want {
		t.Fatalf("skipped = %d, want %d (oldest resident is %d)", skipped, want, oldest)
	}
	if len(chunks) != 8 {
		t.Fatalf("read %d chunks, want the ring's whole capacity of 8", len(chunks))
	}
	if next != 12 {
		t.Fatalf("next = %d, want 12", next)
	}
}

// next MUST be the index of the last chunk actually appended to the returned
// slice, not r.head or r.chunks' own tail -- a forward-looking invariant
// (found while verifying this plan's own code against a reviewer's claim):
// this PR's Read has no batch cap, so today the two are numerically
// identical, and no test in this file can force them apart. The assertion
// here is structural rather than a fixed literal -- next must equal
// want+len(out)-1, computed from what Read actually handed back -- so it
// keeps holding, and failing usefully, the day a bounded Read exists and the
// two quantities diverge.
//
// THIS TEST IS UN-ARMED ON THIS TREE, stated plainly rather than left to be
// rediscovered: cursor+len(chunks) equals the ring's own tail whenever Read
// returns every resident chunk, which it always does here with no cap, so
// reverting the fix this test guards (back to r.chunks[len(r.chunks)-1]
// .Index) leaves this assertion passing -- confirmed by review's own
// break-check against 9f744890, and independently before that. The fix
// itself stays, because the day a caller batches reads is the day the two
// diverge and this assertion starts failing usefully; the code just cannot
// be made to demonstrate that divergence yet. Owner: 2c-3, whose bounded
// Read should arm this test rather than add a second one -- its own
// planner has already been pointed at this test by name.
func TestNextIsTheLastChunkActuallyReturnedNotTheRingsTail(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize
	for range 5 {
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}

	const cursor = 1
	chunks, next, _ := r.Read(cursor)
	want := cursor + uint64(len(chunks))
	if next != want {
		t.Fatalf("next = %d, want %d (cursor %d + %d chunks actually returned) -- "+
			"next must track what was handed back, not the ring's own head",
			next, want, cursor, len(chunks))
	}
}

// The byte cap binds: the ring never holds more than its capacity.
func TestTheRingNeverExceedsItsCapacity(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize
	for range 50 {
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	chunks, _, _ := r.Read(0)
	if len(chunks) > 8 {
		t.Fatalf("the ring holds %d chunks, above its capacity of 8 -- the byte cap is not enforced", len(chunks))
	}
}

// The retention bound binds independently of the byte cap: a chunk older than
// Retention goes even when the ring is nowhere near full.
func TestRetentionEvictsBeforeTheRingIsFull(t *testing.T) {
	clock := &fakeClock{at: time.Unix(1_700_000_000, 0)}
	r := New(Config{
		BudgetBytes: testBudget,
		ChunkBytes:  testChunk,
		Retention:   2 * time.Second,
		Now:         clock.now,
	})
	perChunk := testChunk / TSPacketSize

	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
		t.Fatalf("Write: %v", err)
	}
	clock.advance(10 * time.Second)
	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
		t.Fatalf("Write: %v", err)
	}

	oldest, ok := r.Oldest()
	if !ok {
		t.Fatal("the ring is empty")
	}
	if oldest != 2 {
		t.Fatalf("oldest resident chunk is %d, want 2 -- a chunk older than the "+
			"retention window survived in a ring with seven free slots", oldest)
	}
}

// Capacity comes from the CONFIGURED chunk size, not the package constant.
// Amendment A1.4 puts BUFFER_CHUNK_SIZE on the wire, and a ring that divided
// the budget by the constant would size itself from a value the control plane
// may have changed.
func TestCapacityUsesTheConfiguredChunkSize(t *testing.T) {
	// A chunk size a quarter of the default gives four times the chunks. The
	// default could not produce this count, so the test fails if the config
	// field is ignored (hollow shape 2).
	r := New(Config{BudgetBytes: ChunkBytes * 4, ChunkBytes: ChunkBytes / 4})
	perChunk := (ChunkBytes / 4) / TSPacketSize
	for range 40 {
		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	chunks, _, _ := r.Read(0)
	if len(chunks) != 16 {
		t.Fatalf("the ring holds %d chunks, want 16 (a %d-byte budget at %d bytes a chunk)",
			len(chunks), ChunkBytes*4, ChunkBytes/4)
	}
}

func TestWaitWakesOnAPublish(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize

	woke := make(chan error, 1)
	go func() { woke <- r.Wait(t.Context(), 0) }()

	// Give the waiter a moment to block, then publish.
	time.Sleep(20 * time.Millisecond)
	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
		t.Fatalf("Write: %v", err)
	}

	select {
	case err := <-woke:
		if err != nil {
			t.Fatalf("Wait returned %v, want nil", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Wait did not return after a chunk was published")
	}
}

func TestWaitWakesOnClose(t *testing.T) {
	r := newTestRing(t, nil)
	woke := make(chan error, 1)
	go func() { woke <- r.Wait(t.Context(), 0) }()
	time.Sleep(20 * time.Millisecond)
	r.Close()

	select {
	case err := <-woke:
		// Either outcome is correct: a waiter already blocked sees the closed
		// channel and returns nil, and one that arrives afterwards sees the
		// flag and returns ErrClosed. What must NOT happen is blocking.
		if err != nil && !errors.Is(err, ErrClosed) {
			t.Fatalf("Wait returned %v, want nil or ErrClosed", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Wait did not return after Close -- every reader would leak")
	}
	if err := r.Wait(t.Context(), 0); !errors.Is(err, ErrClosed) {
		t.Fatalf("Wait after Close returned %v, want ErrClosed", err)
	}
	r.Close() // idempotent; a second close must not panic
}

func TestWaitReturnsWhenTheClientGoesAway(t *testing.T) {
	r := newTestRing(t, nil)
	ctx, cancel := context.WithCancel(t.Context())
	woke := make(chan error, 1)
	go func() { woke <- r.Wait(ctx, 0) }()
	time.Sleep(20 * time.Millisecond)
	cancel()

	select {
	case err := <-woke:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Wait returned %v, want context.Canceled", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Wait ignored its context -- a disconnected viewer would leak a goroutine")
	}
}

// The lock discipline, under -race. One writer and several readers, all
// touching head, chunks and notify at once. This is the test the race detector
// IS the oracle for: an unguarded read of any of those three is reported
// directly, with both stacks.
func TestConcurrentReadersAndOneWriter(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize
	payload := relaytest.SyntheticTS(perChunk, 0x100)

	var wg sync.WaitGroup
	stop := make(chan struct{})
	for range 4 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			var cursor uint64
			for {
				select {
				case <-stop:
					return
				default:
				}
				chunks, next, _ := r.Read(cursor)
				cursor = next
				for _, c := range chunks {
					if len(c) != testChunk {
						t.Errorf("a reader saw a %d-byte chunk, want %d", len(c), testChunk)
						return
					}
				}
				_ = r.Head()
				_, _ = r.Oldest()
				_ = r.Join(time.Second)
			}
		}()
	}

	for range 200 {
		if _, err := r.Write(payload); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	close(stop)
	wg.Wait()
}

// The lost wakeup, deterministically. A reader reads, finds nothing, and only
// THEN waits; a publish landing in that window closes the notify channel the
// reader has not looked at yet and installs a fresh one. A cursorless Wait
// blocks on a chunk that is already resident, and the client stalls until the
// next publish -- seconds, at a trickle, and forever on a stream that has just
// ended.
//
// The window is forced rather than raced: the Write happens between the Read
// and the Wait on one goroutine, which is exactly the interleaving the client
// loop can hit and a timing test could not reliably produce.
func TestWaitReturnsImmediatelyWhenAChunkArrivedDuringTheGap(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize

	chunks, _, _ := r.Read(0)
	if len(chunks) != 0 {
		t.Fatal("the ring is not empty at the start of the test")
	}
	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
		t.Fatalf("Write: %v", err)
	}

	woke := make(chan error, 1)
	go func() { woke <- r.Wait(t.Context(), 0) }()
	select {
	case err := <-woke:
		if err != nil {
			t.Fatalf("Wait returned %v, want nil", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Wait blocked although chunk 1 is resident: the publish that landed " +
			"between the caller's Read and its Wait was lost")
	}
}

// The other half: a cursor that is already caught up must still block, or the
// client loop spins on a ring with nothing new in it.
func TestWaitBlocksWhenTheCursorIsCaughtUp(t *testing.T) {
	r := newTestRing(t, nil)
	perChunk := testChunk / TSPacketSize
	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
		t.Fatalf("Write: %v", err)
	}

	ctx, cancel := context.WithTimeout(t.Context(), 300*time.Millisecond)
	defer cancel()
	if err := r.Wait(ctx, r.Head()); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Wait at the head returned %v, want DeadlineExceeded -- a caught-up "+
			"reader must block, not spin", err)
	}
}
