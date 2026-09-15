package buffer

import (
	"bytes"
	"context"
	"errors"
	"testing"
	"time"
)

// newFakeClock is ring_test.go's fakeClock at a fixed start, so the join and
// eviction tests below assert on a fragment's age without sleeping for it. The
// type is shared with the ring's own tests deliberately: two clocks in one
// package would be two things to keep in step.
func newFakeClock() *fakeClock {
	return &fakeClock{at: time.Date(2026, 9, 14, 12, 0, 0, 0, time.UTC)}
}

// frag builds a distinguishable fragment of n bytes whose first byte is the
// marker, so a test can say WHICH fragment it got back.
func frag(marker byte, n int) []byte {
	out := make([]byte, n)
	for i := range out {
		out[i] = marker
	}
	return out
}

func TestAFragmentIsStoredWholeAndReturnedByteForByte(t *testing.T) {
	// The reason this type is not a Ring: Ring.Write packetises at a 188-byte
	// stride into fixed-size chunks, which would split a moof from its mdat.
	// 4,097 bytes is deliberately neither a multiple of 188 nor of ChunkBytes.
	f := NewFragments(FragmentsConfig{})
	want := frag(0xAB, 4097)
	f.Put(want)

	got, next, skipped := f.Read(0)
	if len(got) != 1 {
		t.Fatalf("read returned %d fragments, want exactly the one that was published", len(got))
	}
	if !bytes.Equal(got[0], want) {
		t.Fatalf("the fragment came back %d bytes, want the %d it was published with: this buffer must not packetise", len(got[0]), len(want))
	}
	if next != 1 || skipped != 0 {
		t.Fatalf("next=%d skipped=%d, want next=1 skipped=0", next, skipped)
	}
}

func TestTheFragmentIndexStartsAtOneAndIsMonotonic(t *testing.T) {
	// Redis INCR on a missing key returns 1 (output/fmp4/buffer.py:68), so the
	// first fragment a channel ever publishes is index 1 and a client's
	// starting cursor of 0 means "everything".
	f := NewFragments(FragmentsConfig{})
	for i := range 5 {
		if got := f.Put(frag(byte(i), 32)); got != uint64(i+1) {
			t.Fatalf("fragment %d was published at index %d, want %d", i, got, i+1)
		}
	}
	if f.Head() != 5 {
		t.Fatalf("head is %d after five fragments, want 5", f.Head())
	}
}

func TestAnEmptyFragmentIsNotPublished(t *testing.T) {
	// put_fragment's own `if not data` (output/fmp4/buffer.py:63): an empty
	// write must not consume an index, or a client's cursor would advance past
	// a fragment that never existed.
	f := NewFragments(FragmentsConfig{})
	f.Put(nil)
	f.Put([]byte{})
	if f.Head() != 0 {
		t.Fatalf("head is %d after two empty puts, want 0", f.Head())
	}
}

func TestAZeroJoinWindowIsHeadMinusOneHereAndTheHeadOnTheTSRing(t *testing.T) {
	// THE DIVERGENCE THAT MAKES THIS A SECOND TYPE, asserted side by side so
	// neither rule can be "simplified" into the other.
	// output/fmp4/generator.py:248 positions a zero-window client at
	// max(0, current - 1) -- it still receives the most recent fragment --
	// where output/ts/generator.py:297-303 positions one at the buffer head,
	// which serveClient reads as Ring.Head(). With four units published the
	// two answers are 3 and 4, so a Join that returned the head would fail
	// here rather than agreeing by accident.
	f := NewFragments(FragmentsConfig{})
	// One whole TS packet per chunk, so four writes are four chunks: the ring
	// packetises at a 188-byte stride before it chunks, and a sub-packet write
	// would leave the head behind the write count for a reason that has
	// nothing to do with what this test is about.
	r := New(Config{BudgetBytes: MaxBytesPerChannel, ChunkBytes: TSPacketSize})
	for i := range 4 {
		f.Put(frag(byte(i), 32))
		if _, err := r.Write(frag(0x47, TSPacketSize)); err != nil {
			t.Fatalf("writing a packet to the ring: %v", err)
		}
	}
	if got, want := f.Join(0), uint64(3); got != want {
		t.Fatalf("Fragments.Join(0) returned %d, want head-1 = %d: a zero-window fMP4 client must still receive the newest fragment", got, want)
	}
	if got, want := r.Head(), uint64(4); got != want {
		t.Fatalf("Ring.Head() is %d, want %d: this test only means something while the TS path's zero window is still the head", got, want)
	}
}

func TestAZeroJoinWindowStillDeliversTheMostRecentFragment(t *testing.T) {
	// generator.py:248's max(0, current - 1), where the TS path's zero window
	// means Ring.Head() -- the NEXT chunk. A cursor of head would skip the
	// fragment that is already there, and an fMP4 client's first fragment
	// would be one keyframe interval later than Python's.
	f := NewFragments(FragmentsConfig{})
	for i := range 4 {
		f.Put(frag(byte(i), 32))
	}
	cursor := f.Join(0)
	if cursor != 3 {
		t.Fatalf("Join(0) returned %d, want head-1 = 3", cursor)
	}
	got, _, _ := f.Read(cursor)
	if len(got) != 1 || got[0][0] != 3 {
		t.Fatalf("a zero-window client received %d fragments starting %v, want exactly the newest one (marker 3)", len(got), firstBytes(got))
	}
}

func TestJoinOnAnEmptyBufferWithAZeroWindowIsStillZero(t *testing.T) {
	// max(0, current - 1) with current 0: the floor matters because a uint64
	// head of 0 minus 1 wraps to the largest possible cursor, and a client at
	// that cursor would receive nothing, ever.
	f := NewFragments(FragmentsConfig{})
	if got := f.Join(0); got != 0 {
		t.Fatalf("Join(0) on an empty buffer returned %d, want 0: head-1 must be floored, not wrapped", got)
	}
}

func TestJoinPositionsRoughlyBehindLive(t *testing.T) {
	// find_chunk_index_by_time (output/fmp4/buffer.py:119-141): the NEWEST
	// fragment at least `behind` old, minus one.
	clock := newFakeClock()
	f := NewFragments(FragmentsConfig{Now: clock.now, Retention: time.Minute})
	for i := range 10 {
		f.Put(frag(byte(i), 32))
		clock.advance(time.Second)
	}
	// Fragments 1..10 were published at t+0s .. t+9s; the clock now reads
	// t+10s. Five seconds behind is t+5s, and the newest fragment at least
	// that old is the one published at t+5s, which is index 6.
	if got := f.Join(5 * time.Second); got != 5 {
		t.Fatalf("Join(5s) returned %d, want 5 so the first fragment read is index 6, published five seconds ago", got)
	}
}

func TestJoinFallsBackToTheOldestFragmentWhenTheBufferIsShort(t *testing.T) {
	// buffer.py:134-136's ZRANGE fallback: nothing is that old, so start at the
	// oldest there is.
	clock := newFakeClock()
	f := NewFragments(FragmentsConfig{Now: clock.now, Retention: time.Minute})
	for range 3 {
		f.Put(frag(1, 32))
		clock.advance(100 * time.Millisecond)
	}
	if got := f.Join(time.Hour); got != 0 {
		t.Fatalf("Join(1h) on a 300ms buffer returned %d, want 0 (the oldest fragment, index 1, minus one)", got)
	}
}

func TestEvictionHonoursBothRetentionAndTheByteBudget(t *testing.T) {
	// Both bounds, whichever binds first -- Ring's rule, applied here for D2's
	// reason: FMP4StreamBuffer bounds itself with a Redis TTL alone
	// (buffer.py:71-74) and a time bound is not a memory bound once the
	// fragments are resident in this process.
	clock := newFakeClock()

	byBudget := NewFragments(FragmentsConfig{Now: clock.now, Retention: time.Hour, BudgetBytes: 10_000})
	for range 10 {
		byBudget.Put(frag(1, 4_000))
	}
	if byBudget.Bytes() > 10_000 {
		t.Fatalf("the buffer holds %d bytes against a 10,000-byte budget: retention alone is not a memory bound", byBudget.Bytes())
	}
	if oldest, ok := byBudget.Oldest(); !ok || oldest == 1 {
		t.Fatalf("the first fragment is still resident (oldest=%d ok=%v) after ten 4,000-byte fragments into a 10,000-byte budget", oldest, ok)
	}

	byRetention := NewFragments(FragmentsConfig{Now: clock.now, Retention: 2 * time.Second, BudgetBytes: 1 << 30})
	for range 5 {
		byRetention.Put(frag(1, 32))
		clock.advance(time.Second)
	}
	// Fragments 1..5 are published at t+0s .. t+4s, and eviction runs inside
	// the last Put with the clock at t+4s: the cutoff is t+2s, so 1 and 2 go
	// and 3 stays, because a fragment exactly at the cutoff is not Before it.
	oldest, ok := byRetention.Oldest()
	if !ok || oldest != 3 {
		t.Fatalf("the oldest resident fragment is %d (ok=%v) after five one-second-apart fragments under a two-second retention, want 3: the byte budget is not the only bound", oldest, ok)
	}
}

func TestTheNewestFragmentSurvivesABudgetSmallerThanItself(t *testing.T) {
	// A fragment larger than the whole budget must still be served: published
	// and immediately evicted would leave a client with nothing at all rather
	// than with a short buffer. Python has no equivalent because Redis stores
	// the value whatever its size.
	f := NewFragments(FragmentsConfig{BudgetBytes: 100})
	f.Put(frag(9, 5_000))
	got, _, _ := f.Read(0)
	if len(got) != 1 {
		t.Fatalf("a 5,000-byte fragment into a 100-byte budget left %d fragments readable, want 1", len(got))
	}
}

func TestReadReportsFragmentsLostToEviction(t *testing.T) {
	// A client that fell behind past the budget resumes at the oldest resident
	// fragment with the gap reported, exactly as Ring.Read does.
	f := NewFragments(FragmentsConfig{BudgetBytes: 12_000})
	for range 10 {
		f.Put(frag(1, 4_000))
	}
	_, _, skipped := f.Read(0)
	if skipped == 0 {
		t.Fatal("a client at cursor 0 was told nothing was skipped, when the budget evicted the fragments it was owed")
	}
	oldest, _ := f.Oldest()
	if want := oldest - 1; skipped != want {
		t.Fatalf("skipped=%d, want %d: the gap is every index between the cursor and the oldest resident fragment", skipped, want)
	}
}

func TestReadIsCappedAndNextIsTheLastFragmentActuallyReturned(t *testing.T) {
	// MaxChunksPerRead applies here for Amendment A3.2's reason, and `next`
	// must be the last fragment HANDED OVER: a next that ran to the buffer's
	// tail would make a lagging client skip everything the cap withheld. The
	// fixture writes past the cap so the two values differ and the assertion
	// can fail.
	f := NewFragments(FragmentsConfig{})
	total := MaxChunksPerRead + 7
	for i := range total {
		f.Put(frag(byte(i), 32))
	}
	got, next, _ := f.Read(0)
	if len(got) != MaxChunksPerRead {
		t.Fatalf("read returned %d fragments, want the cap of %d", len(got), MaxChunksPerRead)
	}
	if next != uint64(MaxChunksPerRead) {
		t.Fatalf("next=%d after a capped read of %d fragments, want %d: the buffer's tail is %d and returning it would skip the difference", next, len(got), MaxChunksPerRead, f.Head())
	}
}

func TestAPublishedFragmentIsNeverRewritten(t *testing.T) {
	// The immutability rule fan-out rests on. -race cannot see this on its
	// own -- a writer reusing an array only races when a reader touches it at
	// that instant -- so the content is asserted directly.
	f := NewFragments(FragmentsConfig{})
	scratch := frag(0x11, 64)
	f.Put(scratch)
	for i := range scratch {
		scratch[i] = 0x22
	}
	got, _, _ := f.Read(0)
	if got[0][0] != 0x11 {
		t.Fatal("reusing the caller's buffer changed a fragment already published: Put must copy, or every reader holding it sees the next fragment's bytes")
	}
}

func TestWaitInitReturnsOnceTheInitSegmentIsStored(t *testing.T) {
	f := NewFragments(FragmentsConfig{})
	go func() {
		time.Sleep(10 * time.Millisecond)
		f.SetInit([]byte("ftyp-and-moov"))
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := f.WaitInit(ctx); err != nil {
		t.Fatalf("WaitInit returned %v, want nil once the segment was stored", err)
	}
	if string(f.Init()) != "ftyp-and-moov" {
		t.Fatalf("Init() is %q, want the segment that was stored", f.Init())
	}
}

func TestWaitInitEndsPromptlyWhenTheRemuxProducedNone(t *testing.T) {
	// _wait_for_fmp4_ready polls for INIT_SEGMENT_TIMEOUT (15s) and gives up
	// early only if the channel-stopping key appears (generator.py:190-192).
	// Close is that key: a client must not wait out the whole budget for a
	// segment that can no longer arrive.
	f := NewFragments(FragmentsConfig{})
	go func() {
		time.Sleep(10 * time.Millisecond)
		f.Close()
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	start := time.Now()
	err := f.WaitInit(ctx)
	if !errors.Is(err, ErrClosed) {
		t.Fatalf("WaitInit returned %v, want ErrClosed for a buffer that closed with no init segment", err)
	}
	if took := time.Since(start); took > time.Second {
		t.Fatalf("WaitInit took %s to notice the close, want well under the context's own second", took)
	}
}

func TestWaitInitStillSucceedsForAClosedBufferThatHasASegment(t *testing.T) {
	// A remux that produced an init segment and some fragments and THEN ended
	// still has something to serve: _fetch_init_segment reads the key, which
	// outlives the manager until cleanup (generator.py:260-266).
	f := NewFragments(FragmentsConfig{})
	f.SetInit([]byte("init"))
	f.Put(frag(1, 32))
	f.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := f.WaitInit(ctx); err != nil {
		t.Fatalf("WaitInit returned %v for a closed buffer that HAS an init segment, want nil", err)
	}
}

func TestTheFirstInitSegmentWins(t *testing.T) {
	// The stated divergence: Python's SETEX overwrites on the no-BSF restart
	// (manager.py:400-431 stores a second segment), and this keeps the first.
	f := NewFragments(FragmentsConfig{})
	f.SetInit([]byte("first"))
	f.SetInit([]byte("second"))
	if string(f.Init()) != "first" {
		t.Fatalf("Init() is %q after a second SetInit, want %q", f.Init(), "first")
	}
}

func TestWaitWakesOnAPublishAndOnAClose(t *testing.T) {
	f := NewFragments(FragmentsConfig{})
	go func() {
		time.Sleep(10 * time.Millisecond)
		f.Put(frag(1, 32))
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := f.Wait(ctx, 0); err != nil {
		t.Fatalf("Wait returned %v, want nil once a fragment was published", err)
	}

	f.Close()
	if err := f.Wait(ctx, f.Head()); !errors.Is(err, ErrClosed) {
		t.Fatalf("Wait on a closed buffer returned %v, want ErrClosed", err)
	}
}

func TestWaitTakesTheCallersCursorSoAPublishBetweenReadAndWaitIsNotLost(t *testing.T) {
	// Ring.Wait's lost-wakeup rule, which this type inherits: a publish landing
	// between a caller's Read and its Wait closes a notify channel the caller
	// has not subscribed to yet, so a cursorless Wait would block on a fragment
	// that is already resident.
	f := NewFragments(FragmentsConfig{})
	f.Put(frag(1, 32))
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	if err := f.Wait(ctx, 0); err != nil {
		t.Fatalf("Wait(cursor=0) returned %v with fragment 1 already resident, want nil immediately", err)
	}
}

func firstBytes(chunks [][]byte) []byte {
	out := make([]byte, 0, len(chunks))
	for _, c := range chunks {
		if len(c) > 0 {
			out = append(out, c[0])
		}
	}
	return out
}
