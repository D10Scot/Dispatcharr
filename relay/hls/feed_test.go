package hls

import (
	"bytes"
	"context"
	"errors"
	"io"
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
