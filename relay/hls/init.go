package hls

import (
	"encoding/binary"
	"fmt"
	"math"
	"strings"
)

// Track is what the segmenter and the playlists need from one rendition's
// init segment.
type Track struct {
	// ID is the track_ID every fragment's tfhd names (tkhd).
	ID uint32
	// Handler is the media handler type, "vide" or "soun" (hdlr).
	Handler string
	// Timescale is the media timescale: tfdt and every sample duration are in
	// ticks of it (mdhd).
	Timescale uint32
	// Codec is the rendition's RFC 6381 CODECS value, read from the sample
	// entry's configuration box (spec D7): avcC, hvcC, esds, dac3 or dec3.
	// Empty for a codec this reader does not name.
	Codec string
	// DefaultDuration, DefaultSize and DefaultFlags are the movie-extends
	// defaults (trex), which a fragment's tfhd and trun may leave implicit.
	DefaultDuration uint32
	DefaultSize     uint32
	DefaultFlags    uint32
	// StartOffset is where the track's first sample is presented, in ticks
	// of Timescale, on the output's shared timeline (see edits).
	StartOffset uint64
}

// ParseInit reads the one track of an init segment: ftyp and a moov holding
// one trak.
//
// WHY StartOffset EXISTS. ffmpeg's mp4 muxer starts every track's tfdt at 0
// and records where the track really starts, relative to the output's zero,
// as an empty edit in the track's edit list (measured on ffmpeg 9.0.1: a
// stream joined mid-GOP gives the video an empty edit of 0.86 s and the
// copied AC-3 none, from the same ffmpeg process). Each rendition is a
// separate output file, so their tfdt timelines do NOT line up with each
// other, and an HLS player aligns renditions by tfdt; hls.js ignores edit
// lists outright. The segmenter therefore moves every fragment's tfdt by the
// track's StartOffset and serves the init with its edit list stripped, so
// every rendition of a generation is on one timeline by tfdt alone.
func ParseInit(init []byte) (Track, error) {
	top, err := children(init, 0, len(init))
	if err != nil {
		return Track{}, err
	}
	var moov span
	var found bool
	for _, s := range top {
		if s.typ == "moov" {
			moov, found = s, true
			break
		}
	}
	if !found {
		return Track{}, boxErr("no moov in a %d-byte init segment", len(init))
	}
	var t Track
	movieTimescale, ok := mvhdTimescale(init, moov)
	if !ok {
		return Track{}, boxErr("no readable mvhd")
	}
	trak, ok := child(init, moov.body, moov.end, "trak")
	if !ok {
		return Track{}, boxErr("no trak in moov")
	}
	if t.ID, ok = tkhdTrackID(init, trak); !ok {
		return Track{}, boxErr("no readable tkhd")
	}
	mdia, ok := child(init, trak.body, trak.end, "mdia")
	if !ok {
		return Track{}, boxErr("no mdia in trak")
	}
	if t.Timescale, ok = mdhdTimescale(init, mdia); !ok || t.Timescale == 0 {
		return Track{}, boxErr("no readable mdhd timescale")
	}
	if hdlr, ok := child(init, mdia.body, mdia.end, "hdlr"); ok && hdlr.body+12 <= hdlr.end {
		t.Handler = string(init[hdlr.body+8 : hdlr.body+12])
	}
	if entry, ok := sampleEntry(init, mdia); ok {
		t.Codec = codecString(init, entry)
	}
	if mvex, ok := child(init, moov.body, moov.end, "mvex"); ok {
		list, _ := children(init, mvex.body, mvex.end)
		for _, s := range list {
			if s.typ != "trex" {
				continue
			}
			c := cursor{data: init, pos: s.body + 4, end: s.end}
			id := c.u32()
			c.u32() // default_sample_description_index
			duration, size, flags := c.u32(), c.u32(), c.u32()
			if !c.bad && id == t.ID {
				t.DefaultDuration, t.DefaultSize, t.DefaultFlags = duration, size, flags
			}
		}
	}
	t.StartOffset = startOffset(init, trak, movieTimescale, t.Timescale)
	return t, nil
}

func mvhdTimescale(data []byte, moov span) (uint32, bool) {
	s, ok := child(data, moov.body, moov.end, "mvhd")
	if !ok {
		return 0, false
	}
	version, _, ok := fullBox(data, s)
	if !ok {
		return 0, false
	}
	c := cursor{data: data, pos: s.body + 4, end: s.end}
	if version == 1 {
		c.take(16)
	} else {
		c.take(8)
	}
	timescale := c.u32()
	return timescale, !c.bad
}

func mdhdTimescale(data []byte, mdia span) (uint32, bool) {
	s, ok := child(data, mdia.body, mdia.end, "mdhd")
	if !ok {
		return 0, false
	}
	version, _, ok := fullBox(data, s)
	if !ok {
		return 0, false
	}
	c := cursor{data: data, pos: s.body + 4, end: s.end}
	if version == 1 {
		c.take(16)
	} else {
		c.take(8)
	}
	timescale := c.u32()
	return timescale, !c.bad
}

func tkhdTrackID(data []byte, trak span) (uint32, bool) {
	s, ok := child(data, trak.body, trak.end, "tkhd")
	if !ok {
		return 0, false
	}
	version, _, ok := fullBox(data, s)
	if !ok {
		return 0, false
	}
	c := cursor{data: data, pos: s.body + 4, end: s.end}
	if version == 1 {
		c.take(16)
	} else {
		c.take(8)
	}
	id := c.u32()
	return id, !c.bad
}

// startOffset reads the track's edit list: the empty edits that open it
// (media_time -1) delay its presentation, and the first real edit's
// media_time skips into it. Both are moved into tfdt (ParseInit), so the
// result is empty-edit time minus media_time, in media ticks, and never
// below zero -- a priming edit longer than the delay (an encoder's
// 1024-sample AAC priming with no delay before it) presents its priming
// samples rather than a negative time.
func startOffset(data []byte, trak span, movieTimescale, mediaTimescale uint32) uint64 {
	elst, ok := path(data, trak.body, trak.end, "edts", "elst")
	if !ok || movieTimescale == 0 {
		return 0
	}
	version, _, ok := fullBox(data, elst)
	if !ok {
		return 0
	}
	c := cursor{data: data, pos: elst.body + 4, end: elst.end}
	count := c.u32()
	var empty, mediaTime uint64
	for i := uint32(0); i < count && !c.bad; i++ {
		// media_time is signed, and -1 (all ones) marks an empty edit; any
		// other negative value is malformed and reads as a huge one here.
		var duration uint64
		var isEmpty bool
		if version == 1 {
			duration, mediaTime = c.u64(), c.u64()
			isEmpty = mediaTime == math.MaxUint64
		} else {
			duration, mediaTime = uint64(c.u32()), uint64(c.u32())
			isEmpty = mediaTime == math.MaxUint32
		}
		c.take(4) // media_rate
		if c.bad {
			return 0
		}
		if isEmpty {
			empty += duration
			mediaTime = 0
			continue
		}
		break
	}
	offset := empty * uint64(mediaTimescale) / uint64(movieTimescale)
	if mediaTime >= offset {
		return 0
	}
	return offset - mediaTime
}

// sampleEntry is the first entry of the track's stsd.
func sampleEntry(data []byte, mdia span) (span, bool) {
	stsd, ok := path(data, mdia.body, mdia.end, "minf", "stbl", "stsd")
	if !ok || stsd.body+8 > stsd.end {
		return span{}, false
	}
	// The stsd's version, flags and entry count, then the entries.
	entries, _ := children(data, stsd.body+8, stsd.end)
	if len(entries) == 0 {
		return span{}, false
	}
	return entries[0], true
}

// sampleEntryHeader is the fixed part of a sample entry before its child
// boxes: 8 bytes of SampleEntry, then 70 more for a VisualSampleEntry or 20
// for an AudioSampleEntry (ISO/IEC 14496-12, 12.1.3 and 12.2.3).
func sampleEntryHeader(typ string) (int, bool) {
	switch typ {
	case "avc1", "avc3", "hvc1", "hev1":
		return 78, true
	case "mp4a", "ac-3", "ec-3":
		return 28, true
	}
	return 0, false
}

// codecString is spec D7's rule: the CODECS value comes from the init
// segment, so it stays true in every mode, copy included.
func codecString(data []byte, entry span) string {
	fixed, ok := sampleEntryHeader(entry.typ)
	if !ok || entry.body+fixed > entry.end {
		return ""
	}
	from, to := entry.body+fixed, entry.end
	switch entry.typ {
	case "avc1", "avc3":
		if b, ok := child(data, from, to, "avcC"); ok && b.body+4 <= b.end {
			p := data[b.body:]
			return fmt.Sprintf("%s.%02x%02x%02x", entry.typ, p[1], p[2], p[3])
		}
	case "hvc1", "hev1":
		if b, ok := child(data, from, to, "hvcC"); ok && b.body+13 <= b.end {
			return hevcCodec(entry.typ, data[b.body:b.body+13])
		}
	case "mp4a":
		if b, ok := child(data, from, to, "esds"); ok {
			return mp4aCodec(data[b.body:b.end])
		}
	case "ac-3":
		return "ac-3"
	case "ec-3":
		return "ec-3"
	}
	return ""
}

// hevcCodec is ISO/IEC 14496-15 Annex E's HEVC codecs parameter, from the
// first 13 bytes of an HEVCDecoderConfigurationRecord: the profile space
// letter and profile_idc, the compatibility flags bit-reversed in hex, the
// tier letter and level_idc, then each constraint byte, trailing zero bytes
// omitted. "hvc1.1.6.L93.B0" is Main, level 3.1.
func hevcCodec(prefix string, rec []byte) string {
	space := rec[1] >> 6
	tier := (rec[1] >> 5) & 1
	profile := rec[1] & 0x1f
	compat := binary.BigEndian.Uint32(rec[2:6])
	var reversed uint32
	for i := 0; i < 32; i++ {
		if compat&(1<<i) != 0 {
			reversed |= 1 << (31 - i)
		}
	}
	var b strings.Builder
	b.WriteString(prefix)
	b.WriteByte('.')
	if space > 0 {
		b.WriteByte("ABC"[space-1])
	}
	fmt.Fprintf(&b, "%d.%X.", profile, reversed)
	if tier == 1 {
		b.WriteByte('H')
	} else {
		b.WriteByte('L')
	}
	fmt.Fprintf(&b, "%d", rec[12])
	constraints := rec[6:12]
	last := -1
	for i, c := range constraints {
		if c != 0 {
			last = i
		}
	}
	for i := 0; i <= last; i++ {
		fmt.Fprintf(&b, ".%X", constraints[i])
	}
	return b.String()
}

// mp4aCodec reads an esds FullBox's payload: the ES descriptor, its decoder
// configuration's objectTypeIndication, and the audio object type at the top
// of the decoder-specific info. "mp4a.40.2" is AAC-LC.
func mp4aCodec(esds []byte) string {
	if len(esds) < 4 {
		return ""
	}
	c := &cursor{data: esds, pos: 4, end: len(esds)}
	if tag, _ := descriptor(c); tag != 0x03 {
		return ""
	}
	c.take(2) // ES_ID
	flags := c.u8()
	if flags&0x80 != 0 {
		c.take(2)
	}
	if flags&0x40 != 0 {
		c.take(int(c.u8()))
	}
	if flags&0x20 != 0 {
		c.take(2)
	}
	if tag, _ := descriptor(c); tag != 0x04 {
		return ""
	}
	oti := c.u8()
	c.take(12)
	if c.bad {
		return ""
	}
	if tag, length := descriptor(c); tag != 0x05 || length < 1 {
		return fmt.Sprintf("mp4a.%x", oti)
	}
	first := c.u8()
	aot := int(first >> 3)
	if aot == 31 {
		second := c.u8()
		aot = 32 + (int(first&0x07)<<3 | int(second>>5))
	}
	if c.bad {
		return fmt.Sprintf("mp4a.%x", oti)
	}
	return fmt.Sprintf("mp4a.%x.%d", oti, aot)
}

// descriptor reads an MPEG-4 descriptor's tag and its variable-length size
// (up to four bytes, seven bits each).
func descriptor(c *cursor) (tag byte, length int) {
	tag = c.u8()
	for i := 0; i < 4; i++ {
		b := c.u8()
		length = length<<7 | int(b&0x7f)
		if b&0x80 == 0 {
			break
		}
	}
	if c.bad {
		return 0, 0
	}
	return tag, length
}

// StripEdits returns init with every edts box removed from every trak, and
// the sizes of the boxes that held them corrected. ParseInit's StartOffset
// is what replaces the edit list: the segmenter moves each fragment's tfdt
// by it, so an edit list left in place would apply the offset twice for a
// player that honours it and not at all for one that does not.
func StripEdits(init []byte) ([]byte, error) {
	top, err := children(init, 0, len(init))
	if err != nil {
		return nil, err
	}
	out := make([]byte, 0, len(init))
	for _, s := range top {
		if s.typ != "moov" {
			out = append(out, init[s.start:s.end]...)
			continue
		}
		moov, err := rebuild(init, s, func(inner span) ([]byte, error) {
			if inner.typ != "trak" {
				return init[inner.start:inner.end], nil
			}
			return rebuild(init, inner, func(t span) ([]byte, error) {
				if t.typ == "edts" {
					return nil, nil
				}
				return init[t.start:t.end], nil
			})
		})
		if err != nil {
			return nil, err
		}
		out = append(out, moov...)
	}
	return out, nil
}

// rebuild re-emits container box s with each child replaced by what keep
// returns for it (nil drops the child), with a fresh 32-bit header.
func rebuild(data []byte, s span, keep func(span) ([]byte, error)) ([]byte, error) {
	list, err := children(data, s.body, s.end)
	if err != nil {
		return nil, err
	}
	body := make([]byte, 0, s.end-s.body)
	for _, c := range list {
		kept, err := keep(c)
		if err != nil {
			return nil, err
		}
		body = append(body, kept...)
	}
	return box(s.typ, body), nil
}

// box is a plain box: a 32-bit size, the type, the payload.
func box(typ string, payload []byte) []byte {
	out := make([]byte, 8, 8+len(payload))
	binary.BigEndian.PutUint32(out, uint32(8+len(payload))) // #nosec G115 -- every box built here is far below 4 GiB (maxBoxBytes)
	copy(out[4:], typ)
	return append(out, payload...)
}
