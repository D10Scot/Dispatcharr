package relaytest

import (
	"encoding/binary"
	"fmt"
)

// Synthetic encoder output for the tests of the HLS entry path
// (Phase 4a-1b): the bytes a stand-in "ffmpeg" writes to fd 1 and fd 3, and
// the JSON a stand-in "ffprobe" writes to stdout, in the shape relay/hls
// parses. They are COPIED from relay/hls's own test helpers (helpers_test.go's
// initSpec, fragSpec, videoStream and audioStream), not moved: the relay/hls
// tests are untouched, and this package cannot import relay/hls without a
// cycle through its internal tests. hlsmedia_test.go (package
// relaytest_test) holds the copy to what relay/hls accepts.
//
// What is asserted with these is the relay's REACTION -- its playlists, its
// sessions, its lifecycle -- never what an encoder makes; the real encoder is
// relay/hls/real_test.go's and the E2E's.

// tfhd and trun flag bits, as relay/hls/fragment.go names them.
const (
	tfhdDefaultSizePresent  = 0x000010
	trunDataOffsetPresent   = 0x000001
	trunFirstSampleFlagsBit = 0x000004
	trunDurationPresent     = 0x000100
)

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

// box is a plain box: a 32-bit size, the type, the payload.
func box(typ string, payload []byte) []byte {
	out := make([]byte, 8, 8+len(payload))
	binary.BigEndian.PutUint32(out, uint32(8+len(payload))) // #nosec G115 -- every box built here is a few kilobytes
	copy(out[4:], typ)
	return append(out, payload...)
}

func fullBox(typ string, version byte, flags uint32, payload []byte) []byte {
	head := be32(flags)
	head[0] = version
	return box(typ, cat(head, payload))
}

// initSegment is a one-track init segment: ftyp and a moov with one trak.
func initSegment(trackID uint32, handler string, timescale uint32, entry []byte) []byte {
	mvhd := fullBox("mvhd", 0, 0, cat(make([]byte, 8), be32(1000), make([]byte, 4), make([]byte, 80)))
	tkhd := fullBox("tkhd", 0, 3, cat(make([]byte, 8), be32(trackID), make([]byte, 4), make([]byte, 4), make([]byte, 60)))
	mdhd := fullBox("mdhd", 0, 0, cat(make([]byte, 8), be32(timescale), make([]byte, 4), make([]byte, 4)))
	hdlr := fullBox("hdlr", 0, 0, cat(make([]byte, 4), []byte(handler), make([]byte, 12), []byte("h\x00")))
	stsd := fullBox("stsd", 0, 0, cat(be32(1), entry))
	minf := box("minf", box("stbl", stsd))
	mdia := box("mdia", cat(mdhd, hdlr, minf))
	trak := box("trak", cat(tkhd, mdia))
	trex := fullBox("trex", 0, 0, cat(be32(trackID), be32(1), be32(0), be32(0), be32(0)))
	moov := box("moov", cat(mvhd, trak, box("mvex", trex)))
	ftyp := box("ftyp", []byte("iso5\x00\x00\x02\x00iso5iso6mp41"))
	return cat(ftyp, moov)
}

// avc1Entry is a VisualSampleEntry carrying an avcC of profile 0x64, level
// 0x2a: "avc1.64002a".
func avc1Entry() []byte {
	avcC := box("avcC", []byte{1, 0x64, 0, 0x2a, 0xff, 0xe0})
	return box("avc1", cat(make([]byte, 6), []byte{0, 1}, make([]byte, 70), avcC))
}

// aacEntry is an AudioSampleEntry carrying an esds for AAC-LC: "mp4a.40.2".
func aacEntry() []byte {
	asc := []byte{2<<3 | 0x01, 0x90}
	dsi := cat([]byte{0x05, byte(len(asc))}, asc)                                                   // #nosec G115 -- two bytes
	dcd := cat([]byte{0x04, byte(13 + len(dsi)), 0x40, 0x15}, make([]byte, 11), dsi)                // #nosec G115 -- a few bytes
	es := cat([]byte{0x03, byte(3 + len(dcd) + 3)}, []byte{0, 1, 0}, dcd, []byte{0x06, 0x01, 0x02}) // #nosec G115 -- a few bytes
	esds := fullBox("esds", 0, 0, es)
	return box("mp4a", cat(make([]byte, 6), []byte{0, 1}, make([]byte, 20), esds))
}

// fragment is one moof+mdat: one sample per duration, the first a sync sample.
func fragment(seq, trackID uint32, start uint64, durations []uint32) []byte {
	tfhd := fullBox("tfhd", 0, 0x020000|tfhdDefaultSizePresent, cat(be32(trackID), be32(4)))
	tfdt := fullBox("tfdt", 1, 0, be64(start))
	var samples []byte
	for _, d := range durations {
		samples = append(samples, be32(d)...)
	}
	trun := fullBox("trun", 0, trunDataOffsetPresent|trunFirstSampleFlagsBit|trunDurationPresent,
		cat(be32(uint32(len(durations))), be32(0), be32(0x02000000), samples)) // #nosec G115 -- a few samples
	moof := box("moof", cat(fullBox("mfhd", 0, 0, be32(seq)), box("traf", cat(tfhd, tfdt, trun))))
	return cat(moof, box("mdat", make([]byte, 4*len(durations))))
}

// HLSVideoStream is a synthetic video output: a 12800 Hz H.264 init, then
// `fragments` fragments of framesPerFragment 25 fps frames each (512 ticks),
// every fragment opening on a sync sample.
func HLSVideoStream(fragments, framesPerFragment int) []byte {
	out := initSegment(1, "vide", 12800, avc1Entry())
	for i := 0; i < fragments; i++ {
		durations := make([]uint32, framesPerFragment)
		for j := range durations {
			durations[j] = 512
		}
		out = append(out, fragment(uint32(i+1), 1, uint64(i*framesPerFragment*512), durations)...) // #nosec G115 -- a test's small counts
	}
	return out
}

// HLSAACStream is a synthetic AAC-LC output: a 48 kHz init, then `fragments`
// 200 ms fragments of 1024-sample frames (9 or 10 each, so starts stay on
// frames).
func HLSAACStream(fragments int) []byte {
	out := initSegment(1, "soun", 48000, aacEntry())
	start := uint64(0)
	for i := 0; i < fragments; i++ {
		frames := 9
		if i%3 == 2 {
			frames = 10
		}
		durations := make([]uint32, frames)
		for j := range durations {
			durations[j] = 1024
		}
		out = append(out, fragment(uint32(i+1), 1, start, durations)...) // #nosec G115 -- a test's small counts
		start += uint64(frames * 1024)
	}
	return out
}

// HLSProbeJSON is an ffprobe `-show_streams -of json` answer: 640x360
// progressive H.264 at 25/1 when video is set and, when audio is, one
// qualifying AAC stereo stream.
func HLSProbeJSON(video, audio bool) []byte {
	var streams []string
	if video {
		streams = append(streams, `{"codec_type":"video","codec_name":"h264","width":640,"height":360,"field_order":"progressive","r_frame_rate":"25/1","id":"0x100"}`)
	}
	if audio {
		streams = append(streams, `{"codec_type":"audio","codec_name":"aac","channels":2,"sample_rate":"48000","id":"0x101"}`)
	}
	out := `{"streams":[`
	for i, s := range streams {
		if i > 0 {
			out += ","
		}
		out += s
	}
	return []byte(fmt.Sprintf("%s]}", out))
}
