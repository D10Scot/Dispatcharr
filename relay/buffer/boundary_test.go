package buffer

import (
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// Phase 4 spec, D10: MarkBoundary ends one upstream connection's bytes. The
// whole packets still pending are published as one short final chunk -- no
// byte a TS client was due is lost -- and the carried partial packet is
// dropped, so the chunk at the returned index is the NEXT connection's own,
// with none of the old source's packets in front of it.
func TestMarkBoundaryEndsTheOldConnectionsBytes(t *testing.T) {
	r := newTestRing(t, nil)
	old := relaytest.SyntheticTS(6, 0x100) // one 4-packet chunk and two pending
	if _, err := r.Write(append(old, 0x47, 0x01, 0x02)); err != nil {
		t.Fatal(err)
	}
	if r.Head() != 1 {
		t.Fatalf("head %d before the boundary, want 1", r.Head())
	}
	boundary := r.MarkBoundary()
	if boundary != 3 || r.Head() != 2 {
		t.Fatalf("MarkBoundary = %d with head %d, want the pending packets published as chunk 2 and the boundary at 3", boundary, r.Head())
	}
	chunks, _, _ := r.Read(1)
	if len(chunks) != 1 || len(chunks[0]) != 2*TSPacketSize || relaytest.AlignmentProblem(chunks[0]) != "" {
		t.Fatalf("chunk 2 is %d bytes, want the old connection's two pending packets, whole", len(chunks[0]))
	}
	next := relaytest.SyntheticTS(4, 0x200)
	if _, err := r.Write(next); err != nil {
		t.Fatal(err)
	}
	chunks, _, _ = r.Read(2)
	if len(chunks) != 1 || relaytest.AlignmentProblem(chunks[0]) != "" || relaytest.PacketPID(chunks[0]) != 0x200 {
		t.Fatalf("the chunk at the boundary does not open with the new connection's whole packets")
	}
	if again := r.MarkBoundary(); again != 4 || r.Head() != 3 {
		t.Fatalf("a boundary with nothing pending = %d (head %d), want 4 with nothing published", again, r.Head())
	}
}

// After a failover's ResetPosition there is nothing to publish, and a closed
// ring publishes nothing either.
func TestMarkBoundaryAfterResetOrCloseOnlyReportsTheIndex(t *testing.T) {
	r := newTestRing(t, nil)
	_, _ = r.Write(relaytest.SyntheticTS(2, 0x100))
	r.ResetPosition()
	if b := r.MarkBoundary(); b != 1 || r.Head() != 0 {
		t.Fatalf("after ResetPosition MarkBoundary = %d with head %d, want 1 and nothing published", b, r.Head())
	}
	_, _ = r.Write(relaytest.SyntheticTS(2, 0x100))
	r.Close()
	if b := r.MarkBoundary(); b != 1 || r.Head() != 0 {
		t.Fatalf("a closed ring published at a boundary: %d, head %d", b, r.Head())
	}
}

// ArrivedAt is a chunk's publish time, for relay/hls's PDT anchor (D7), and
// false for an index the ring does not hold.
func TestArrivedAt(t *testing.T) {
	clock := &fakeClock{at: time.Date(2026, 9, 27, 12, 0, 0, 0, time.UTC)}
	r := newTestRing(t, clock.now)
	if _, ok := r.ArrivedAt(1); ok {
		t.Fatal("an empty ring reported an arrival")
	}
	_, _ = r.Write(relaytest.SyntheticTS(4, 0x100))
	clock.advance(time.Second)
	_, _ = r.Write(relaytest.SyntheticTS(4, 0x100))
	if at, ok := r.ArrivedAt(2); !ok || !at.Equal(clock.now()) {
		t.Fatalf("ArrivedAt(2) = %v, %t, want the second publish's time", at, ok)
	}
	if at, ok := r.ArrivedAt(1); !ok || !at.Equal(clock.now().Add(-time.Second)) {
		t.Fatalf("ArrivedAt(1) = %v, %t", at, ok)
	}
	for _, index := range []uint64{0, 3} {
		if _, ok := r.ArrivedAt(index); ok {
			t.Fatalf("ArrivedAt(%d) reported a chunk the ring does not hold", index)
		}
	}
}
