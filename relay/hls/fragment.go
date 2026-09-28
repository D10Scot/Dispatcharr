package hls

import (
	"encoding/binary"
	"math"
)

// Fragment is one moof+mdat an encoder output wrote, with the timing the
// segmenter cuts on.
type Fragment struct {
	// Data is the moof and its mdat, tfdt already moved onto the
	// generation's shared timeline.
	Data []byte
	// Start is the tfdt: the first sample's decode time, in the track's
	// timescale.
	Start uint64
	// Duration is the sum of the fragment's sample durations.
	Duration uint64
	// Samples is the trun's sample count.
	Samples int
	// Sync is whether the first sample is a sync sample. A segment must
	// start with one (Apple 7.4); the segmenter checks it (spec D6).
	Sync bool
}

// End is Start plus Duration.
func (f Fragment) End() uint64 { return f.Start + f.Duration }

// trunFlags are a trun's tf_flags: which optional fields it carries.
type trunFlags uint32

const (
	trunDataOffset       trunFlags = 0x000001
	trunFirstSampleFlags trunFlags = 0x000004
	trunDuration         trunFlags = 0x000100
	trunSize             trunFlags = 0x000200
	trunFlagsPresent     trunFlags = 0x000400
	trunCTO              trunFlags = 0x000800

	tfhdBaseDataOffset  = 0x000001
	tfhdSampleDescIndex = 0x000002
	tfhdDefaultDuration = 0x000008
	tfhdDefaultSize     = 0x000010
	tfhdDefaultFlags    = 0x000020
)

// ParseFragment reads a moof+mdat for track t. It reads exactly one traf and
// one trun, which is what ffmpeg writes for a one-track output; a fragment
// for another track is an error, never silently someone else's samples.
func ParseFragment(data []byte, t Track) (Fragment, error) {
	moof, ok := child(data, 0, len(data), "moof")
	if !ok || moof.start != 0 {
		return Fragment{}, boxErr("a fragment must start with moof")
	}
	traf, ok := child(data, moof.body, moof.end, "traf")
	if !ok {
		return Fragment{}, boxErr("no traf in moof")
	}
	tfhd, ok := child(data, traf.body, traf.end, "tfhd")
	if !ok {
		return Fragment{}, boxErr("no tfhd in traf")
	}
	_, hflags, ok := fullBox(data, tfhd)
	if !ok {
		return Fragment{}, boxErr("short tfhd")
	}
	c := cursor{data: data, pos: tfhd.body + 4, end: tfhd.end}
	trackID := c.u32()
	if hflags&tfhdBaseDataOffset != 0 {
		c.take(8)
	}
	if hflags&tfhdSampleDescIndex != 0 {
		c.take(4)
	}
	duration, flags := t.DefaultDuration, t.DefaultFlags
	if hflags&tfhdDefaultDuration != 0 {
		duration = c.u32()
	}
	if hflags&tfhdDefaultSize != 0 {
		c.take(4)
	}
	if hflags&tfhdDefaultFlags != 0 {
		flags = c.u32()
	}
	if c.bad {
		return Fragment{}, boxErr("short tfhd")
	}
	if trackID != t.ID {
		return Fragment{}, boxErr("a fragment for track %d in a track-%d output", trackID, t.ID)
	}

	f := Fragment{Data: data}
	if tfdt, ok := child(data, traf.body, traf.end, "tfdt"); ok {
		version, _, ok := fullBox(data, tfdt)
		if !ok {
			return Fragment{}, boxErr("short tfdt")
		}
		tc := cursor{data: data, pos: tfdt.body + 4, end: tfdt.end}
		if version == 1 {
			f.Start = tc.u64()
		} else {
			f.Start = uint64(tc.u32())
		}
		if tc.bad {
			return Fragment{}, boxErr("short tfdt")
		}
	} else {
		return Fragment{}, boxErr("no tfdt in traf")
	}

	trun, ok := child(data, traf.body, traf.end, "trun")
	if !ok {
		return Fragment{}, boxErr("no trun in traf")
	}
	_, rflags, ok := fullBox(data, trun)
	if !ok {
		return Fragment{}, boxErr("short trun")
	}
	tf := trunFlags(rflags)
	rc := cursor{data: data, pos: trun.body + 4, end: trun.end}
	count := rc.u32()
	if tf&trunDataOffset != 0 {
		rc.take(4)
	}
	first := flags
	if tf&trunFirstSampleFlags != 0 {
		first = rc.u32()
	}
	per := 0
	for _, bit := range []trunFlags{trunDuration, trunSize, trunFlagsPresent, trunCTO} {
		if tf&bit != 0 {
			per += 4
		}
	}
	if rc.bad || uint64(count)*uint64(per) > uint64(rc.end-rc.pos) { // #nosec G115 -- rc.pos <= rc.end once rc.bad is false
		return Fragment{}, boxErr("a trun of %d samples does not fit its box", count)
	}
	f.Samples = int(count)
	for i := uint32(0); i < count; i++ {
		d := duration
		if tf&trunDuration != 0 {
			d = rc.u32()
		}
		if tf&trunSize != 0 {
			rc.take(4)
		}
		if tf&trunFlagsPresent != 0 {
			sf := rc.u32()
			if i == 0 && tf&trunFirstSampleFlags == 0 {
				first = sf
			}
		}
		if tf&trunCTO != 0 {
			rc.take(4)
		}
		f.Duration += uint64(d)
	}
	f.Sync = count > 0 && sampleIsSync(first)
	return f, nil
}

// shiftStart adds delta ticks to the fragment's tfdt, in place. ffmpeg writes
// tfdt version 1 (64 bits); a version-0 tfdt that the shift would overflow
// is an error rather than a wrapped timestamp.
func shiftStart(f *Fragment, delta uint64) error {
	if delta == 0 {
		return nil
	}
	data := f.Data
	moof, _ := child(data, 0, len(data), "moof")
	traf, _ := child(data, moof.body, moof.end, "traf")
	tfdt, ok := child(data, traf.body, traf.end, "tfdt")
	if !ok {
		return boxErr("no tfdt to shift")
	}
	version, _, _ := fullBox(data, tfdt)
	at := tfdt.body + 4
	if version == 1 {
		if at+8 > tfdt.end {
			return boxErr("short tfdt")
		}
		binary.BigEndian.PutUint64(data[at:], f.Start+delta)
	} else {
		if at+4 > tfdt.end || f.Start+delta > math.MaxUint32 {
			return boxErr("a version-0 tfdt cannot hold %d", f.Start+delta)
		}
		binary.BigEndian.PutUint32(data[at:], uint32(f.Start+delta)) // #nosec G115 -- checked against MaxUint32 above
	}
	f.Start += delta
	return nil
}

// synthFragment builds one fragment of count identical samples of frame,
// each dur ticks, starting at start: one moof (mfhd, and a traf of tfhd with
// default-base-is-moof and the three defaults, tfdt version 1, and a trun
// with a data offset) and one mdat (spec § Encoder argv, silence). It is how
// the relay writes a silent rendition, and -- with count 0 -- the empty
// fragment an audio rendition gets for a segment its encoder wrote no audio
// for.
func synthFragment(seq, trackID uint32, start uint64, frame []byte, count int, dur uint32) []byte {
	mfhd := fullBoxBytes("mfhd", 0, 0, be32(seq))
	tfhd := fullBoxBytes("tfhd", 0, 0x020000|tfhdDefaultDuration|tfhdDefaultSize|tfhdDefaultFlags,
		cat(be32(trackID), be32(dur), be32(uint32(len(frame))), be32(0x02000000))) // #nosec G115 -- a canned frame is a few kilobytes
	tfdt := fullBoxBytes("tfdt", 1, 0, be64(start))
	trun := fullBoxBytes("trun", 0, uint32(trunDataOffset), cat(be32(uint32(count)), be32(0))) // #nosec G115 -- count is a segment's frames, a few hundred
	moof := box("moof", cat(mfhd, box("traf", cat(tfhd, tfdt, trun))))
	// The trun's data_offset is from the moof's first byte (default-base-is-
	// moof) to the first sample: past the moof and the mdat's header.
	offset := len(moof) - 4
	binary.BigEndian.PutUint32(moof[offset:], uint32(len(moof)+8)) // #nosec G115 -- a moof is a few dozen bytes
	payload := make([]byte, 0, len(frame)*count)
	for i := 0; i < count; i++ {
		payload = append(payload, frame...)
	}
	return cat(moof, box("mdat", payload))
}

func fullBoxBytes(typ string, version byte, flags uint32, payload []byte) []byte {
	head := be32(flags)
	head[0] = version
	return box(typ, cat(head, payload))
}

func be32(v uint32) []byte {
	b := make([]byte, 4)
	binary.BigEndian.PutUint32(b, v)
	return b
}

func be64(v uint64) []byte {
	b := make([]byte, 8)
	binary.BigEndian.PutUint64(b, v)
	return b
}

func cat(parts ...[]byte) []byte {
	n := 0
	for _, p := range parts {
		n += len(p)
	}
	out := make([]byte, 0, n)
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}
