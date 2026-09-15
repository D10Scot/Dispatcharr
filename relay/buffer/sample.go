package buffer

// SampleChunk is one resident chunk's diagnostic shape: what
// get_detailed_channel_info's buffer-health walk reads out of Redis for each
// of the last few chunk keys (channel_status.py:235-266) without handing the
// caller the chunk's bytes.
//
// FirstByte is the `first_byte` diagnostic (:265), which for a whole TS
// packet is always 0x47. Reported rather than asserted, exactly as there:
// the diagnostic exists so an operator can see a ring that is NOT aligned.
type SampleChunk struct {
	Index     uint64
	Size      int
	FirstByte byte
}

// Sample is the n highest-indexed resident chunks, oldest first.
//
// The Redis walk it replaces iterates the index range [head-n+1, head] and
// splits it into keys_found and keys_missing (channel_status.py:243-268),
// because a chunk key can expire out from under the index. This returns only
// what is resident and lets the caller derive the missing half from head and
// n, which is the same split from the same two facts -- and the reason a
// chunk can be missing here is eviction rather than a TTL, the one
// difference spec D2 makes to this diagnostic.
func (r *Ring) Sample(n int) []SampleChunk {
	if n <= 0 {
		return nil
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	if len(r.chunks) == 0 {
		return nil
	}
	from := 0
	if len(r.chunks) > n {
		from = len(r.chunks) - n
	}
	out := make([]SampleChunk, 0, len(r.chunks)-from)
	for _, c := range r.chunks[from:] {
		sample := SampleChunk{Index: c.Index, Size: len(c.Data)}
		if len(c.Data) > 0 {
			sample.FirstByte = c.Data[0]
		}
		out = append(out, sample)
	}
	return out
}
