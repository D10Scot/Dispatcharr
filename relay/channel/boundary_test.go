package channel

import (
	"context"
	"io"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// connectionSource writes six whole packets with a PID of its own per run --
// 0x100 on the first connection, 0x101 on the second -- and three stray
// bytes, then fails, so every run is a new upstream connection whose bytes
// the ring can tell apart. Its last run stays connected.
type connectionSource struct {
	runs *int32Counter
	last int
}

func (s connectionSource) Run(ctx context.Context, sink io.Writer) error {
	s.runs.inc()
	run := s.runs.get()
	if _, err := sink.Write(append(relaytest.SyntheticTS(6, 0xff+run), 0x47, 0x01, 0x02)); err != nil {
		return err
	}
	if run >= s.last {
		<-ctx.Done()
		return ctx.Err()
	}
	return &ErrUpstreamStatus{Status: 502}
}

// Phase 4 spec, D10: "a boundary is every new upstream connection: an
// applySwitch, or a reconnect of the same URL. The channel records the ring
// index of the boundary's first chunk." Three connections to one URL (two
// same-URL reconnects) give three boundaries, each the index of the first
// chunk the new connection published, with the previous connection's
// pending packets published whole before it.
func TestEveryConnectionAttemptRecordsASourceBoundary(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	runs := &int32Counter{}
	ch, release := attachWith(t, m, "boundaries", connectionSource{runs: runs, last: 3}, testTuning(), nil)
	defer release()
	// Every byte of all three connections has been written once the ring
	// has counted them: six packets and three stray bytes each.
	const perConnection = 6*buffer.TSPacketSize + 3
	waitFor(t, "the third connection's bytes", 10*time.Second, func() bool { return ch.Ring().TotalBytes() >= 3*perConnection })

	// Per connection: one 4-packet chunk on its own PID, then (at the next
	// boundary) its two pending packets as a short chunk.
	for i, want := range []struct {
		after, boundary uint64
		pid             int
	}{{0, 1, 0x100}, {1, 3, 0x101}, {3, 5, 0x102}} {
		got, ok := ch.NextBoundary(want.after)
		if !ok || got != want.boundary {
			t.Fatalf("connection %d: NextBoundary(%d) = %d, %t, want %d", i+1, want.after, got, ok, want.boundary)
		}
		chunks, _, _ := ch.Ring().Read(got - 1)
		if len(chunks) == 0 || relaytest.AlignmentProblem(chunks[0]) != "" || relaytest.PacketPID(chunks[0]) != want.pid {
			t.Fatalf("connection %d's boundary chunk %d is not its own whole packets on PID %#x", i+1, got, want.pid)
		}
	}
	if b, ok := ch.NextBoundary(5); ok {
		t.Fatalf("a fourth boundary %d with only three connections", b)
	}
	flushed, _, _ := ch.Ring().Read(1)
	if len(flushed[0]) != 2*buffer.TSPacketSize || relaytest.PacketPID(flushed[0]) != 0x100 {
		t.Fatalf("chunk 2 is %d bytes: the first connection's two pending packets were not published before the boundary", len(flushed[0]))
	}
	m.Stop("boundaries")
}

// An attempt that published nothing leaves the next attempt's boundary at the
// same index, recorded once; and the record keeps the newest maxBoundaries.
func TestTheBoundaryRecordIsStrictlyIncreasingAndBounded(t *testing.T) {
	c := &Channel{ring: buffer.New(buffer.Config{BudgetBytes: buffer.TSPacketSize * 400, ChunkBytes: buffer.TSPacketSize * 4})}
	c.markBoundary()
	c.markBoundary()
	if b, ok := c.NextBoundary(0); !ok || b != 1 {
		t.Fatalf("NextBoundary(0) = %d, %t", b, ok)
	}
	if b, ok := c.NextBoundary(1); ok {
		t.Fatalf("an attempt that published nothing recorded a second boundary %d", b)
	}
	for i := 0; i < maxBoundaries+6; i++ {
		_, _ = c.ring.Write(relaytest.SyntheticTS(1, 0x100))
		c.markBoundary()
	}
	c.boundaryMu.Lock()
	n, oldest := len(c.boundaries), c.boundaries[0]
	c.boundaryMu.Unlock()
	if n != maxBoundaries || oldest != 8 {
		t.Fatalf("the record holds %d boundaries from %d, want the newest %d from 8", n, oldest, maxBoundaries)
	}
}
