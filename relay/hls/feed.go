package hls

import (
	"context"
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// Source is what a pipeline reads: the channel's ring, and where its source
// boundaries fall. *channel.Channel satisfies it; relay/hls does not import
// relay/channel, so 4a-1b can have the channel hold a pipeline without an
// import cycle.
type Source interface {
	Ring() *buffer.Ring
	// NextBoundary is the first source boundary strictly after the ring
	// index after: the index of the first chunk a new upstream connection
	// published or will publish (D10).
	NextBoundary(after uint64) (uint64, bool)
}

// feedEnd is why a feed stopped.
type feedEnd int

const (
	// feedBoundary: the next chunk belongs to a new upstream connection.
	feedBoundary feedEnd = iota
	// feedClosed: the channel's ring closed; the channel is ending.
	feedClosed
	// feedStopped: the context ended.
	feedStopped
	// feedWriteFailed: the process stopped reading its input.
	feedWriteFailed
	// feedLimit: the byte limit was reached (a probe's bound).
	feedLimit
)

// feedResult is how a feed ended.
type feedResult struct {
	end feedEnd
	// boundary is the boundary index, for feedBoundary.
	boundary uint64
	// written is how many bytes were written.
	written int
}

// feed writes the ring's chunks after start to w, stopping AT the first
// source boundary after the generation's own first chunk: the chunk at the
// boundary index is never written (D10). It is how a generation's input and
// a probe's input are both bounded to one upstream connection's bytes, which
// is the whole of D9's "reads from where that generation will start" and
// D10's "the running generation's writer stops at that index".
//
// A boundary at start+1 is the generation's own beginning and is not a
// reason to stop. Boundaries are recorded before the chunk at their index
// can be published (channel.markBoundary), so checking after each read never
// misses one. limit (0 for none) caps the bytes written; first is called
// once with the index of the first chunk written, for the PDT anchor.
func feed(ctx context.Context, src Source, start uint64, w io.Writer, limit int, first func(index uint64)) feedResult {
	ring := src.Ring()
	cursor := start
	var res feedResult
	for {
		chunks, next, _ := ring.Read(cursor)
		if len(chunks) > 0 {
			index := next - uint64(len(chunks)) + 1
			boundary, has := src.NextBoundary(start + 1)
			for _, chunk := range chunks {
				if has && index >= boundary {
					res.end, res.boundary = feedBoundary, boundary
					return res
				}
				if res.written == 0 && first != nil {
					first(index)
				}
				if limit > 0 && res.written+len(chunk) > limit {
					chunk = chunk[:limit-res.written]
				}
				if _, err := w.Write(chunk); err != nil {
					res.end = feedWriteFailed
					return res
				}
				res.written += len(chunk)
				if limit > 0 && res.written >= limit {
					res.end = feedLimit
					return res
				}
				index++
			}
			cursor = next
			continue
		}
		if err := ring.Wait(ctx, cursor); err != nil {
			if errors.Is(err, buffer.ErrClosed) {
				res.end = feedClosed
			} else {
				res.end = feedStopped
			}
			return res
		}
	}
}

// awaitInput waits until the ring holds a chunk past start, the ring closes,
// ctx ends, or within passes (issue #560). A probe runs it before spawning
// ffprobe, so the probe's own bound measures analysis and never the source's
// start: on a cold channel the pipeline starts before the ring holds a byte.
// A ring that closes is feedClosed and a context that ends is feedStopped, as
// feed reports them; within passing is feedStopped with an error of its own.
//
// It loops because Wait answers nil when Close wakes it and ErrClosed only on
// the next call, exactly as feed's Read-then-Wait loop meets it.
func awaitInput(ctx context.Context, ring *buffer.Ring, start uint64, within time.Duration) (feedResult, error) {
	wctx, cancel := context.WithTimeout(ctx, within)
	defer cancel()
	for ring.Head() <= start {
		err := ring.Wait(wctx, start)
		switch {
		case err == nil:
			continue
		case errors.Is(err, buffer.ErrClosed):
			return feedResult{end: feedClosed}, errors.New("hls: the channel's ring closed before any input arrived")
		case ctx.Err() != nil:
			return feedResult{end: feedStopped}, ctx.Err()
		}
		return feedResult{end: feedStopped}, fmt.Errorf("hls: the channel's source sent no input within %v, so the probe never ran", within)
	}
	return feedResult{}, nil
}

// arrival is the PDT anchor's clock: the ring's arrival time for a chunk,
// or now when the chunk has already left the ring.
func arrival(ring *buffer.Ring, index uint64, now func() time.Time) time.Time {
	if at, ok := ring.ArrivedAt(index); ok {
		return at
	}
	return now()
}
