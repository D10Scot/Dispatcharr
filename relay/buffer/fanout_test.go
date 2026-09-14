package buffer

import (
	"bytes"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

const (
	fanChunk  = TSPacketSize * 4 // 752 bytes
	fanBudget = fanChunk * 64    // sixty-four chunks, well past the read cap
)

func fanRing() *Ring {
	return New(Config{BudgetBytes: fanBudget, ChunkBytes: fanChunk})
}

// One Read hands back at most MaxChunksPerRead chunks, and `next` is the last
// chunk RETURNED rather than the ring's head -- the two stopped being the same
// thing when the cap went in, and a `next` that ran ahead of the delivered
// bytes would make a lagging client skip everything it did not receive.
func TestReadIsCappedAndItsCursorFollowsTheBytes(t *testing.T) {
	r := fanRing()
	// Forty chunks: twice the cap, inside the sixty-four-chunk ring so
	// nothing is evicted and the arithmetic below is about the cap alone.
	source := relaytest.SyntheticTS(40*4, 0x100)
	if _, err := r.Write(source); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := r.Head(); got != 40 {
		t.Fatalf("the ring published %d chunks, want 40 -- the fixture is wrong, not the cap", got)
	}

	chunks, next, skipped := r.Read(0)
	if len(chunks) != MaxChunksPerRead {
		t.Fatalf("one Read returned %d chunks with 40 resident, want %d -- a lagging reader "+
			"can pin a whole ring's worth of evicted chunks", len(chunks), MaxChunksPerRead)
	}
	if skipped != 0 {
		t.Fatalf("skipped = %d with nothing evicted", skipped)
	}
	// next's contract -- the index of the last chunk actually returned, never
	// the ring's tail -- is 2c-2's own invariant, armed by this cap (2c-3).
	// This test does not check next's numeric value directly; it uses next
	// to drive the second Read below and checks the RESULT is exactly the
	// remaining twenty chunks in order, which fails if next ran ahead
	// (a gap) or behind (a duplicate) just as surely as a bare equality
	// check would. That makes it a second assertion of the same property
	// from a different fixture -- forty chunks in a sixty-four-chunk ring,
	// read from cursor 0 -- not a second mechanism: both this test and
	// TestNextIsTheLastChunkActuallyReturnedNotTheRingsTail (ring_test.go)
	// exercise the same `next = c.Index` line in Read.

	// The rest arrives on the following calls, in order and with no gap.
	rest, _, _ := r.Read(next)
	if len(rest) != 40-MaxChunksPerRead {
		t.Fatalf("the second Read returned %d chunks, want %d", len(rest), 40-MaxChunksPerRead)
	}
	// Position, not shape: the two reads concatenated must be the source from
	// packet zero.
	got := append(flatten(chunks), flatten(rest)...)
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the two reads do not concatenate into whole TS packets: %s", problem)
	}
	for i := 0; i < len(got); i += TSPacketSize {
		want := i / TSPacketSize
		if idx := relaytest.PacketIndex(got[i : i+TSPacketSize]); idx != want {
			t.Fatalf("packet at byte %d carries index %d, want %d -- the cap dropped, "+
				"duplicated or reordered a chunk", i, idx, want)
		}
	}
}

// D2's immutability rule, at the fan-out that makes it matter. 2c-2 asserted it
// with one reader; 2c-3 adds the readers that share the array, and the
// assertion is still on CONTENT because -race cannot see it: two goroutines
// writing different bytes of one array is not a race on any address, and one
// goroutine writing a chunk nobody is reading at that instant is not a race at
// all.
func TestAChunkIsUnchangedAfterEveryClientHasServedIt(t *testing.T) {
	const readers = 8
	r := fanRing()
	source := relaytest.SyntheticTS(8, 0x100) // two chunks

	if _, err := r.Write(source); err != nil {
		t.Fatalf("Write: %v", err)
	}
	held := make([][][]byte, readers)
	snapshots := make([][]byte, readers)
	for i := range readers {
		chunks, _, _ := r.Read(0)
		if len(chunks) == 0 {
			t.Fatalf("reader %d read nothing", i)
		}
		held[i] = chunks
		snapshots[i] = bytes.Clone(chunks[0])
	}

	// Every reader holds a slice of the SAME array -- that is the design, and
	// if it were not, this test would be checking nothing.
	if &held[0][0][0] != &held[readers-1][0][0] {
		t.Fatal("two readers were handed different backing arrays for one chunk: " +
			"the fan-out is copying, which is not what spec D2 specifies")
	}

	// Force the ring well past what the readers hold.
	for range 40 {
		if _, err := r.Write(relaytest.SyntheticTS(4, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}

	for i := range readers {
		for at := range snapshots[i] {
			if held[i][0][at] != snapshots[i][at] {
				t.Fatalf("byte %d of a chunk reader %d still holds changed from %#02x to %#02x "+
					"after later writes: a published chunk's backing array was reused, and every "+
					"other reader of that chunk saw it change too",
					at, i, snapshots[i][at], held[i][0][at])
			}
		}
	}
}

// N readers and one writer, with -race as the oracle for the lock discipline.
// 2c-2 drove four readers; the shape here is the same and the point is that
// every reader path 2c-3 adds -- ClientSnapshot's callers included -- goes
// through these five methods.
func TestManyConcurrentReadersAndOneWriter(t *testing.T) {
	const readers = 16
	r := fanRing()
	stop := make(chan struct{})

	var wg sync.WaitGroup
	for range readers {
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
				_ = len(chunks)
				_ = r.Head()
				_, _ = r.Oldest()
				_ = r.Join(2 * time.Second)
				_ = r.TotalBytes()
			}
		}()
	}

	for range 200 {
		if _, err := r.Write(relaytest.SyntheticTS(4, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	close(stop)
	wg.Wait()
}

func flatten(chunks [][]byte) []byte {
	var out []byte
	for _, c := range chunks {
		out = append(out, c...)
	}
	return out
}
