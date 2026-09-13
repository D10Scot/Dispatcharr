package buffer

import "testing"

// The Python literals this package mirrors. Typed by hand from the source
// named in each comment, never computed from the constants above -- these are
// the oracle, and a test that derived them from the subject would pass with
// every constant wrong together.
func TestConstantsMatchThePythonSource(t *testing.T) {
	// apps/proxy/config.py:15 -- BUFFER_CHUNK_SIZE = 188 * 1361
	if ChunkBytes != 255868 {
		t.Errorf("ChunkBytes = %d, want 255868 (apps/proxy/config.py:15)", ChunkBytes)
	}
	// apps/proxy/config.py:71 -- settings.get("redis_chunk_ttl", 60)
	if RetentionSeconds != 60 {
		t.Errorf("RetentionSeconds = %d, want 60 (apps/proxy/config.py:71)", RetentionSeconds)
	}
	// apps/proxy/config.py:57 -- "new_client_behind_seconds": 5
	if JoinBehindSeconds != 5 {
		t.Errorf("JoinBehindSeconds = %d, want 5 (apps/proxy/config.py:57)", JoinBehindSeconds)
	}
	// The cap, as Ruling R2 derives it.
	if MaxBytesPerChannel != 76760400 {
		t.Errorf("MaxBytesPerChannel = %d, want 76760400", MaxBytesPerChannel)
	}
}

// The cap must hold at least the full retention window at the bitrate it was
// sized for. If it does not, the cap is silently shorter than Python's
// buffer at the reference rate and every client's rewind window shrinks.
func TestCapCoversFullRetentionAtTheReferenceBitrate(t *testing.T) {
	needed := ReferenceBitrateBitsPerSecond / 8 * RetentionSeconds // 75,000,000
	if MaxBytesPerChannel < needed {
		t.Fatalf("cap %d < %d bytes needed for %ds at %d bit/s",
			MaxBytesPerChannel, needed, RetentionSeconds, ReferenceBitrateBitsPerSecond)
	}
}

// The bitrate above which the byte cap binds before the 60-second retention.
// Below it, behaviour is Python's exactly; above it, retention shortens and
// memory does not grow. 10.23 Mbit/s -- close enough to the reference rate
// that it is worth stating out loud rather than discovering in production.
func TestRetentionAndCapCrossAtTheStatedBitrate(t *testing.T) {
	const wantBitsPerSecond = 10_234_720 // 76,760,400 / 60 * 8
	got := MaxBytesPerChannel / RetentionSeconds * 8
	if got != wantBitsPerSecond {
		t.Fatalf("crossover = %d bit/s, want %d -- the plan's Ruling R2 arithmetic has moved",
			got, wantBitsPerSecond)
	}
}

// The check that actually matters. A new client starts JoinBehindSeconds
// behind live, so the cap is only safe while that much video is resident.
// The margin is an order of magnitude and this test says by how much.
func TestCapCoversTheJoinPointWithAnOrderOfMagnitudeToSpare(t *testing.T) {
	const wantCeilingBitsPerSecond = 122_816_640 // 76,760,400 / 5 * 8
	got := MaxBytesPerChannel / JoinBehindSeconds * 8
	if got != wantCeilingBitsPerSecond {
		t.Fatalf("join-point ceiling = %d bit/s, want %d", got, wantCeilingBitsPerSecond)
	}
	if got < 10*ReferenceBitrateBitsPerSecond {
		t.Fatalf("join-point ceiling %d bit/s is under 10x the reference rate; the cap is too tight", got)
	}
}

func TestChunksForBytes(t *testing.T) {
	for _, tc := range []struct {
		name   string
		budget int
		want   int
	}{
		// MaxBytesPerChannel is ITSELF MaxChunksPerChannel * ChunkBytes, so
		// dividing it back by ChunkBytes is an algebraic identity: this case
		// pins that MaxChunksPerChannel is still 300, not that the division
		// in ChunksForBytes is correct. The cases below it, with budgets
		// ChunksForBytes did not derive from, are what cover the conversion.
		{"the default cap", MaxBytesPerChannel, 300},
		{"one chunk exactly", ChunkBytes, 1},
		{"a partial chunk rounds down to one", ChunkBytes + 1, 1},
		{"below one chunk still yields one", 1, 1},
		{"two and a half chunks", ChunkBytes*2 + ChunkBytes/2, 2},
	} {
		if got := ChunksForBytes(tc.budget); got != tc.want {
			t.Errorf("%s: ChunksForBytes(%d) = %d, want %d", tc.name, tc.budget, got, tc.want)
		}
	}
}
