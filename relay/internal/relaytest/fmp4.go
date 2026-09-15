package relaytest

import (
	"encoding/binary"
	"fmt"
	"math"
)

// The synthetic fragmented-MP4 asset: an init segment and a sequence of
// fragments, structurally valid box chains with no real media in them.
//
// SYNTHETIC RATHER THAN A CAPTURED CORPUS, for exactly the reason SyntheticTS
// is synthetic rather than an encode. Nothing on this path decodes: the fMP4
// pipeline reads a four-byte big-endian length and a four-byte type, splits the
// stream where a `moof` box begins, and carries whatever is between. A
// structurally valid box chain exercises every one of those decisions, costs no
// ffmpeg, and is byte-for-byte identical on every host and every ffmpeg
// version -- where a capture would drift with the encoder and would have to be
// regenerated in an image nobody runs locally.
//
// IT IS NOT A SUBSTITUTE FOR THE REAL ONE, and the split is the same one
// harness/README.md states for the stand-in: the stand-in wherever the subject
// is the relay's REACTION to what a process produced, real ffmpeg wherever the
// subject is the bytes a remuxer produces. So the scanner, the client loop, the
// refcount and parity-matrix row 12 are driven from these bytes, and
// relay/output's real-ffmpeg test drives the scanner from an actual `-c copy`
// remux of an actual encode. Neither covers the other.

// FMP4FragmentPayload is how many filler bytes each synthetic fragment's mdat
// box carries: large enough that a fragment is not mistaken for a stray header
// and small enough that a test's buffer holds hundreds of them.
const FMP4FragmentPayload = 4096

// MP4Box builds one box: a four-byte big-endian length covering the whole box,
// a four-byte type, then the payload. Exported so a test can build a box the
// scanner must SKIP or resynchronise past, which is a shape no synthetic
// fragment carries.
func MP4Box(boxType string, payload []byte) []byte {
	if len(boxType) != 4 {
		panic(fmt.Sprintf("relaytest: a box type is four bytes, got %q", boxType))
	}
	// The explicit ceiling is what lets the conversion below be written
	// without a #nosec: gosec's G115 cannot prove an int fits in a uint32 on
	// its own, and it accepts a guard that says so. No box this package builds
	// is anywhere near it; the check is for the linter and for a future caller.
	size := 8 + len(payload)
	if size > math.MaxUint32 {
		panic(fmt.Sprintf("relaytest: a %d-byte box does not fit an MP4 length field", size))
	}
	out := make([]byte, size)
	binary.BigEndian.PutUint32(out[0:4], uint32(size))
	copy(out[4:8], boxType)
	copy(out[8:], payload)
	return out
}

// SyntheticFMP4Init is the init segment: an `ftyp` box then a `moov` box, the
// two the fMP4 scanner must keep in front of the first `moof`.
func SyntheticFMP4Init() []byte {
	ftyp := MP4Box("ftyp", []byte("isom\x00\x00\x02\x00isomiso2avc1mp41"))
	moov := MP4Box("moov", make([]byte, 256))
	return append(ftyp, moov...)
}

// SyntheticFMP4Fragment is one fragment: a `moof` box carrying index in its
// first four payload bytes, then an `mdat` box of filler.
//
// THE EMBEDDED INDEX IS WHY A POSITION TEST CAN WORK, for SyntheticTS's reason:
// the filler repeats, so "have I seen this fragment before" is true of every
// fragment at some distance, and a join-point assertion needs a fragment's
// absolute position to be observable.
func SyntheticFMP4Fragment(index int) []byte {
	if index < 0 {
		panic(fmt.Sprintf("relaytest: a fragment index must be >= 0, got %d", index))
	}
	if index > math.MaxUint32 {
		panic(fmt.Sprintf("relaytest: a fragment index must fit 32 bits, got %d", index))
	}
	head := make([]byte, 8)
	binary.BigEndian.PutUint32(head[0:4], uint32(index))
	moof := MP4Box("moof", head)
	mdat := make([]byte, FMP4FragmentPayload)
	for i := range mdat {
		mdat[i] = byte((index + i) % 256)
	}
	return append(moof, MP4Box("mdat", mdat)...)
}

// FMP4FragmentIndex reads back the index SyntheticFMP4Fragment embedded, or -1
// when data does not begin with a synthetic `moof`.
func FMP4FragmentIndex(data []byte) int {
	if len(data) < 12 || string(data[4:8]) != "moof" {
		return -1
	}
	return int(binary.BigEndian.Uint32(data[8:12]))
}

// MP4Boxes walks the top-level box chain and returns each box's offset, size
// and type, stopping at the first malformed length.
//
// A DELIBERATE RE-IMPLEMENTATION of the walk, never a call into the production
// scanner, and the Go counterpart of output_support.py's mp4_boxes, whose own
// docstring states the rule: a test that parses with the code under test proves
// the code agrees with itself, not that the code is right.
func MP4Boxes(data []byte) (offsets []int, sizes []int, types []string) {
	for offset := 0; offset+8 <= len(data); {
		size := int(binary.BigEndian.Uint32(data[offset : offset+4]))
		if size < 8 {
			break
		}
		offsets = append(offsets, offset)
		sizes = append(sizes, size)
		types = append(types, string(data[offset+4:offset+8]))
		offset += size
	}
	return offsets, sizes, types
}

// FMP4ShapeProblem reports why data is not an init segment followed by at least
// one moof/mdat pair, or the empty string when it is -- the Go counterpart of
// output_support.py's assert_fmp4_init_then_fragment, returning a reason for
// AlignmentProblem's stated reason.
func FMP4ShapeProblem(data []byte) string {
	_, _, types := MP4Boxes(data)
	if len(types) == 0 {
		return fmt.Sprintf("no parsable MP4 box at all in %d bytes: %x", len(data), data[:min(32, len(data))])
	}
	if types[0] != "ftyp" {
		return fmt.Sprintf("the stream does not start with ftyp: got %v", types[:min(5, len(types))])
	}
	var sawMoov bool
	for _, t := range types {
		if t == "moov" {
			sawMoov = true
		}
	}
	if !sawMoov {
		return fmt.Sprintf("no moov box: got %v", types)
	}
	for i, t := range types {
		if t != "moof" {
			continue
		}
		if i+1 >= len(types) || types[i+1] != "mdat" {
			return fmt.Sprintf("the moof at box %d is not followed by mdat: got %v", i, types)
		}
		return ""
	}
	return fmt.Sprintf("no moof (fragment) box: got %v", types)
}
