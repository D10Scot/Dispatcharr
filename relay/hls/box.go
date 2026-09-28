package hls

import (
	"encoding/binary"
	"errors"
	"fmt"
)

// The box reader (Phase 4 spec, D6): ISO BMFF parsing for exactly what the
// segmenter and the playlists need, with stdlib encoding/binary and nothing
// else. It reads the boxes ffmpeg's mp4 muxer writes under
// `-movflags frag_keyframe+delay_moov+default_base_moof`: one track per
// output, an init segment (ftyp, moov) and then moof+mdat fragments.
//
// EVERY LENGTH IS CHECKED BEFORE IT IS USED. The input is an encoder's pipe,
// which is trusted as far as it goes, but a truncated or corrupt box must end
// a generation with an error rather than panic the relay that carries every
// live viewer; FuzzParseInit and FuzzParseFragment hold that.

// errBox is every malformed-box error, so a caller can tell a parse failure
// from an I/O one.
var errBox = errors.New("hls: malformed box")

func boxErr(format string, args ...any) error {
	return fmt.Errorf("%w: "+format, append([]any{errBox}, args...)...)
}

// maxBoxBytes bounds any single box the reader will hold: a video fragment
// of a 2 s segment at D8's top rate is about 2 MB, and a copied fragment
// (4a-1d) of a 6 s GOP at a high provider rate a few tens; 64 MiB is the
// same ceiling relay/output's fragment scanner uses.
const maxBoxBytes = 64 << 20

// boxHeader reads the header of the box at off in data: its total size
// (header included), its four-character type, and the header's length (8, or
// 16 with a 64-bit largesize). A size of 0 means "to the end of data". ok is
// false when the header or the size does not fit.
func boxHeader(data []byte, off int) (size int, typ string, hdr int, ok bool) {
	if off < 0 || off+8 > len(data) {
		return 0, "", 0, false
	}
	size32 := binary.BigEndian.Uint32(data[off:])
	typ = string(data[off+4 : off+8])
	remaining := len(data) - off
	switch size32 {
	case 0:
		return remaining, typ, 8, true
	case 1:
		if remaining < 16 {
			return 0, "", 0, false
		}
		large := binary.BigEndian.Uint64(data[off+8:])
		if large < 16 || large > uint64(remaining) { // #nosec G115 -- remaining >= 16 here
			return 0, "", 0, false
		}
		return int(large), typ, 16, true // #nosec G115 -- large <= remaining, an int
	default:
		if size32 < 8 || int64(size32) > int64(remaining) {
			return 0, "", 0, false
		}
		return int(size32), typ, 8, true
	}
}

// span is one box inside a byte slice: [start, end) is the whole box and
// body is where its payload starts.
type span struct {
	typ        string
	start, end int
	body       int
}

// children lists the boxes laid end to end in data[from:to], stopping with
// an error at the first that does not fit.
func children(data []byte, from, to int) ([]span, error) {
	var out []span
	for off := from; off < to; {
		size, typ, hdr, ok := boxHeader(data[:to], off)
		if !ok {
			return out, boxErr("a box at offset %d does not fit in %d bytes", off, to-off)
		}
		out = append(out, span{typ: typ, start: off, end: off + size, body: off + hdr})
		off += size
	}
	return out, nil
}

// child finds the first box of type typ directly inside data[from:to].
func child(data []byte, from, to int, typ string) (span, bool) {
	list, _ := children(data, from, to)
	for _, s := range list {
		if s.typ == typ {
			return s, true
		}
	}
	return span{}, false
}

// path follows a chain of container types from data[from:to], each the first
// of its type inside the previous one.
func path(data []byte, from, to int, types ...string) (span, bool) {
	var s span
	for _, typ := range types {
		found, ok := child(data, from, to, typ)
		if !ok {
			return span{}, false
		}
		s, from, to = found, found.body, found.end
	}
	return s, true
}

// fullBox reads a FullBox's version and flags at the start of s's payload.
func fullBox(data []byte, s span) (version byte, flags uint32, ok bool) {
	if s.body+4 > s.end {
		return 0, 0, false
	}
	return data[s.body], uint32(data[s.body+1])<<16 | uint32(data[s.body+2])<<8 | uint32(data[s.body+3]), true
}

// cursor reads big-endian integers from data[pos:end], remembering the first
// short read so a parser can check once at the end.
type cursor struct {
	data []byte
	pos  int
	end  int
	bad  bool
}

func (c *cursor) take(n int) []byte {
	if c.bad || n < 0 || c.pos+n > c.end {
		c.bad = true
		return nil
	}
	b := c.data[c.pos : c.pos+n]
	c.pos += n
	return b
}

func (c *cursor) u8() uint8 {
	if b := c.take(1); b != nil {
		return b[0]
	}
	return 0
}

func (c *cursor) u32() uint32 {
	if b := c.take(4); b != nil {
		return binary.BigEndian.Uint32(b)
	}
	return 0
}

func (c *cursor) u64() uint64 {
	if b := c.take(8); b != nil {
		return binary.BigEndian.Uint64(b)
	}
	return 0
}

// sampleIsSync reads ISO/IEC 14496-12's sample_flags: a sample is a sync
// sample when sample_is_non_sync_sample (bit 16) is clear.
func sampleIsSync(flags uint32) bool { return flags&0x00010000 == 0 }
