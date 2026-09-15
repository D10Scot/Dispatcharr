package httpapi

import (
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// pythonFloat renders what Python's str(round(x, n)) renders.
//
// THE EXPECTED VALUES ARE PYTHON'S OWN OUTPUT, printed by a python3 in the
// repo's test container and pasted here, not computed by Go -- an expected
// value the code under test computes cannot fail (hollow shape 1). The
// command:
//
//	docker exec <container> python3 -c "
//	for v, n in [(25.0,2),(29.97,2),(4500.0,1),(128.0,1),(24.456,1),
//	             (1.02,3),(0.0,1),(23.976,2),(1000000.0,1),(0.5,1)]:
//	    print(repr(str(round(v, n))))"
//
// THE ROWS THAT MATTER ARE THE WHOLE NUMBERS. Python's float repr always
// carries a decimal point -- str(25.0) is "25.0" -- where Go's shortest form
// is "25", so a status payload reporting source_fps "25" where the Python
// relay reports "25.0" is a wire difference on a field parity-matrix row 14
// is about. The rounding itself is already done by channel.Stats, which
// stores each value rounded the way its writer rounds it; this is the str()
// half alone, which is why the inputs below are the ROUNDED values.
func TestPythonFloatRendersWhatPythonsStrRoundRenders(t *testing.T) {
	for _, tc := range []struct {
		in   float64
		want string
	}{
		{25.0, "25.0"},
		{29.97, "29.97"},
		{4500.0, "4500.0"},
		{128.0, "128.0"},
		{24.5, "24.5"},
		{1.02, "1.02"},
		{0.0, "0.0"},
		{23.98, "23.98"},
		{1000000.0, "1000000.0"},
		{0.5, "0.5"},
	} {
		if got := pythonFloat(tc.in); got != tc.want {
			t.Errorf("pythonFloat(%v) = %q, want %q (Python's str(round(...)))", tc.in, got, tc.want)
		}
	}
}

// describeBufferStats over a REAL ring, because the golden pins the encoder
// and not this walk: break-checks 2 and 3 of this PR removed the decimal
// point and the keys_missing assignment and the golden test stayed GREEN,
// since its fixture is a struct literal that supplies both.
//
// THREE SHAPES: an empty ring, a fully resident sample, and one whose oldest
// sampled indices have been evicted.
func TestDescribeBufferStatsWalksTheRing(t *testing.T) {
	// 1. An empty ring: chunks 0, an empty diagnostics object, and none of
	// the sample keys -- channel_status.py:235's `if buffer_index > 0`.
	empty := buffer.New(buffer.Config{BudgetBytes: 10 * buffer.ChunkBytes, ChunkBytes: buffer.TSPacketSize * 2})
	stats := describeBufferStats(empty)
	if stats.Chunks != 0 || stats.KeysFound != nil || stats.KeysMissing != nil || stats.AvgChunkSize != nil {
		t.Fatalf("an empty ring produced %+v, want chunks 0 and no sample", stats)
	}
	if stats.Diagnostics == nil {
		t.Errorf("diagnostics is nil, where channel_status.py:231 seeds an empty dict")
	}

	// 2. A ring holding more than the sample: every sampled index is
	// resident, so keys_missing is PRESENT AND EMPTY -- the state the
	// serializer renders as [] and the Go encoder would drop with omitempty
	// on a plain slice.
	full := buffer.New(buffer.Config{BudgetBytes: 100 * buffer.TSPacketSize * 2, ChunkBytes: buffer.TSPacketSize * 2})
	for range 10 {
		if _, err := full.Write(make([]byte, buffer.TSPacketSize*2)); err != nil {
			t.Fatalf("writing to the ring: %v", err)
		}
	}
	stats = describeBufferStats(full)
	if stats.Chunks != full.Head() {
		t.Errorf("chunks is %d, want the head %d", stats.Chunks, full.Head())
	}
	if len(stats.KeysFound) != detailBufferSample {
		t.Errorf("keys_found holds %d indices, want the %d channel_status.py:237 samples",
			len(stats.KeysFound), detailBufferSample)
	}
	if stats.KeysMissing == nil {
		t.Fatalf("keys_missing is absent on a fully resident sample: channel_status.py:275 " +
			"assigns it inside the same arm as keys_found, so it renders as [] there")
	}
	if len(*stats.KeysMissing) != 0 {
		t.Errorf("keys_missing is %v on a fully resident sample", *stats.KeysMissing)
	}
	if stats.IsTSAligned == nil || !*stats.IsTSAligned {
		t.Errorf("is_ts_aligned is %v for chunks that are whole TS packets", stats.IsTSAligned)
	}
	first, ok := stats.Diagnostics["first_chunk"].(map[string]any)
	if !ok {
		t.Fatalf("diagnostics has no first_chunk: %v", stats.Diagnostics)
	}
	if first["first_byte"] != byte(0x00) {
		// The synthetic writes above are zero bytes, so this asserts the
		// field is the chunk's own first byte rather than a hard-coded 0x47.
		t.Errorf("first_byte is %v, want the chunk's own first byte", first["first_byte"])
	}

	// 3. A ring whose capacity is smaller than the sample window: the
	// oldest sampled indices have been evicted, so keys_missing NAMES THEM.
	// The cause differs from Python's -- eviction here, an expired key there
	// -- and the field's meaning does not.
	small := buffer.New(buffer.Config{BudgetBytes: 3 * buffer.TSPacketSize * 2, ChunkBytes: buffer.TSPacketSize * 2})
	for range 10 {
		if _, err := small.Write(make([]byte, buffer.TSPacketSize*2)); err != nil {
			t.Fatalf("writing to the small ring: %v", err)
		}
	}
	stats = describeBufferStats(small)
	if stats.KeysMissing == nil || len(*stats.KeysMissing) == 0 {
		t.Fatalf("keys_missing is %v on a ring that has evicted part of the sample window",
			stats.KeysMissing)
	}
	if len(stats.KeysFound)+len(*stats.KeysMissing) != detailBufferSample {
		t.Errorf("keys_found (%d) and keys_missing (%d) do not cover the %d-index window",
			len(stats.KeysFound), len(*stats.KeysMissing), detailBufferSample)
	}
}

// humanBytes is channel_status.py:141-149's total_data, across all four
// arms and at both sides of one boundary.
func TestHumanBytesMatchesTheFourArms(t *testing.T) {
	for _, tc := range []struct {
		in   uint64
		want string
	}{
		{0, "0 B"},
		{1023, "1023 B"},
		{1024, "1.00 KB"},
		{1024*1024 - 1, "1024.00 KB"},
		{1024 * 1024, "1.00 MB"},
		{9_999_888, "9.54 MB"},
		{1024 * 1024 * 1024, "1.00 GB"},
	} {
		if got := humanBytes(tc.in); got != tc.want {
			t.Errorf("humanBytes(%d) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

// unixFloat is the seconds-since-epoch float every timestamp on these
// payloads is, and a zero time reports 0 rather than the year-1 epoch.
func TestUnixFloatReportsZeroForAZeroTime(t *testing.T) {
	if got := unixFloat(time.Time{}); got != 0 {
		t.Errorf("unixFloat(zero) = %v, want 0", got)
	}
	at := time.Unix(1_789_000_000, 500_000_000)
	if got := unixFloat(at); got != 1_789_000_000.5 {
		t.Errorf("unixFloat(%v) = %v, want 1789000000.5", at, got)
	}
}
