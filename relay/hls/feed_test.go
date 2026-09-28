package hls

import (
	"bytes"
	"context"
	"errors"
	"io"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// chunkOf is one whole test chunk filled with b.
func chunkOf(b byte) []byte { return bytes.Repeat([]byte{b}, testChunk) }

// D10: a generation's writer stops AT the boundary -- the chunk at the
// boundary index is never written -- and a boundary at the generation's own
// first chunk is its start, not a reason to stop.
func TestFeedStopsAtTheNextBoundary(t *testing.T) {
	src := newTestSource()
	src.mark() // the channel's first connection: index 1
	src.write(t, chunkOf('a'))
	src.write(t, chunkOf('a'))
	boundary := src.mark()
	src.write(t, chunkOf('b'))
	var out bytes.Buffer
	var first uint64
	res := feed(context.Background(), src, 0, &out, 0, func(i uint64) { first = i })
	if res.end != feedBoundary || res.boundary != boundary || boundary != 3 {
		t.Fatalf("feed ended %v at %d, want at the boundary 3", res.end, res.boundary)
	}
	if !bytes.Equal(out.Bytes(), append(chunkOf('a'), chunkOf('a')...)) || first != 1 || res.written != 2*testChunk {
		t.Fatalf("feed wrote %d bytes from %d, want exactly the first connection's two chunks", out.Len(), first)
	}
	out.Reset()
	src.ring.Close()
	res = feed(context.Background(), src, boundary-1, &out, 0, nil)
	if res.end != feedClosed || !bytes.Equal(out.Bytes(), chunkOf('b')) {
		t.Fatalf("the next generation fed %v, %d bytes, want the second connection's chunk and then the close", res.end, out.Len())
	}
}

func TestFeedLimitStopAndWriteFailure(t *testing.T) {
	src := newTestSource()
	src.write(t, chunkOf('a'))
	src.write(t, chunkOf('a'))
	var out bytes.Buffer
	res := feed(context.Background(), src, 0, &out, testChunk+10, nil)
	if res.end != feedLimit || out.Len() != testChunk+10 {
		t.Fatalf("a limited feed ended %v after %d bytes", res.end, out.Len())
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if res := feed(ctx, src, 2, io.Discard, 0, nil); res.end != feedStopped {
		t.Fatalf("a feed with nothing to read did not stop with its context: %v", res.end)
	}
	if res := feed(context.Background(), src, 0, failingWriter{}, 0, nil); res.end != feedWriteFailed {
		t.Fatalf("a write failure ended the feed %v", res.end)
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) { return 0, errors.New("broken pipe") }

func TestArrival(t *testing.T) {
	src := newTestSource()
	at := time.Date(2026, 9, 27, 1, 2, 3, 0, time.UTC)
	ring := buffer.New(buffer.Config{BudgetBytes: 10 * testChunk, ChunkBytes: testChunk, Now: func() time.Time { return at }})
	_, _ = ring.Write(chunkOf('a'))
	later := at.Add(time.Hour)
	if got := arrival(ring, 1, func() time.Time { return later }); !got.Equal(at) {
		t.Errorf("arrival of a chunk in the ring = %v, want its publish time", got)
	}
	if got := arrival(ring, 5, func() time.Time { return later }); !got.Equal(later) {
		t.Errorf("arrival of a chunk not in the ring = %v, want now", got)
	}
	_ = src
}

// hookSource is a testSource whose first NextBoundary call runs hook just
// AFTER it has answered: a new upstream connection that begins right after a
// feed took its boundary snapshot.
type hookSource struct {
	*testSource
	once sync.Once
	hook func()
}

func (s *hookSource) NextBoundary(after uint64) (uint64, bool) {
	index, has := s.testSource.NextBoundary(after)
	s.once.Do(s.hook)
	return index, has
}

// PR #529 review (thread on feed.go:72): a boundary snapshot taken once per
// Read batch cannot let the batch carry a new connection's chunks into the
// old generation, because the snapshot is taken AFTER the Read, and a
// boundary is recorded before the first chunk at it is published
// (channel.markBoundary): every chunk the Read returned was published before
// the snapshot, so every boundary at or before those chunks is in it. Here a
// new connection begins -- its boundary recorded, two of its chunks
// published -- right after the first snapshot. The batch in hand is entirely
// the old connection's, and the next Read stops at the boundary. A snapshot
// taken BEFORE the Read would miss this boundary while the Read returned the
// new connection's chunks with the old ones.
func TestFeedNeverCarriesANewConnectionsChunksPastItsBoundary(t *testing.T) {
	base := newTestSource()
	base.mark()
	base.write(t, chunkOf('a'))
	base.write(t, chunkOf('a'))
	var boundary uint64
	src := &hookSource{testSource: base}
	src.hook = func() {
		boundary = base.mark()
		base.write(t, chunkOf('b'))
		base.write(t, chunkOf('b'))
	}
	// Bounded, so a feed that misses the boundary reads its end as a stop
	// rather than waiting for a chunk that never comes.
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	var out bytes.Buffer
	res := feed(ctx, src, 0, &out, 0, nil)
	if bytes.Contains(out.Bytes(), []byte{'b'}) || out.Len() != 2*testChunk {
		t.Fatalf("feed wrote %d bytes including the new connection's: a batch carried chunks past a boundary recorded just after its snapshot", out.Len())
	}
	if res.end != feedBoundary || res.boundary != boundary || boundary != 3 {
		t.Fatalf("feed ended %v at %d, want at the boundary 3", res.end, res.boundary)
	}
}
