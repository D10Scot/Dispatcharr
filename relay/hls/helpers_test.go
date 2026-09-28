package hls

import (
	"os"
	"sync"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// testChunk is the test ring's chunk: 64 packets, so a boundary lands within
// 12 KB of where a test puts it rather than within a production chunk's
// 255 KB.
const testChunk = buffer.TSPacketSize * 64

// testSource is a channel as a pipeline sees it: a ring, and the boundaries
// a test marks on it exactly as channel.markBoundary does.
type testSource struct {
	ring *buffer.Ring
	mu   sync.Mutex
	b    []uint64
}

func newTestSource() *testSource {
	return &testSource{ring: buffer.New(buffer.Config{BudgetBytes: 512 << 20, ChunkBytes: testChunk})}
}

func (s *testSource) Ring() *buffer.Ring { return s.ring }

func (s *testSource) NextBoundary(after uint64) (uint64, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, b := range s.b {
		if b > after {
			return b, true
		}
	}
	return 0, false
}

// mark records a source boundary: the next byte written starts a new
// upstream connection.
func (s *testSource) mark() uint64 {
	index := s.ring.MarkBoundary()
	s.mu.Lock()
	defer s.mu.Unlock()
	s.b = append(s.b, index)
	return index
}

// write puts b into the ring.
func (s *testSource) write(t *testing.T, b []byte) {
	t.Helper()
	if _, err := s.ring.Write(b); err != nil {
		t.Fatalf("writing the ring: %v", err)
	}
}

// readFile is os.ReadFile with a test failure.
func readFile(t *testing.T, path string) []byte {
	t.Helper()
	b, err := os.ReadFile(path) // #nosec G304 -- a test fixture path
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	return b
}

// initSpec describes a synthetic one-track init segment.
type initSpec struct {
	trackID        uint32
	handler        string // "vide" or "soun"
	timescale      uint32 // mdhd
	movieTimescale uint32 // mvhd
	entry          []byte // the stsd sample entry, whole box
	// emptyEdit and mediaTime, when emptyEdit or mediaTime is non-zero,
	// give the trak an edts: an empty edit of emptyEdit movie ticks, then a
	// media edit starting at mediaTime.
	emptyEdit uint32
	mediaTime int32
	// trexDuration, trexSize and trexFlags are the mvex defaults.
	trexDuration, trexSize, trexFlags uint32
	version1                          bool // mvhd, tkhd and mdhd version 1
}

func (s initSpec) build() []byte {
	movie := s.movieTimescale
	if movie == 0 {
		movie = 1000
	}
	var mvhd, tkhd, mdhd []byte
	if s.version1 {
		mvhd = fullBoxBytes("mvhd", 1, 0, cat(make([]byte, 16), be32(movie), make([]byte, 8), make([]byte, 80)))
		tkhd = fullBoxBytes("tkhd", 1, 3, cat(make([]byte, 16), be32(s.trackID), make([]byte, 4), make([]byte, 8), make([]byte, 60)))
		mdhd = fullBoxBytes("mdhd", 1, 0, cat(make([]byte, 16), be32(s.timescale), make([]byte, 8), make([]byte, 4)))
	} else {
		mvhd = fullBoxBytes("mvhd", 0, 0, cat(make([]byte, 8), be32(movie), make([]byte, 4), make([]byte, 80)))
		tkhd = fullBoxBytes("tkhd", 0, 3, cat(make([]byte, 8), be32(s.trackID), make([]byte, 4), make([]byte, 4), make([]byte, 60)))
		mdhd = fullBoxBytes("mdhd", 0, 0, cat(make([]byte, 8), be32(s.timescale), make([]byte, 4), make([]byte, 4)))
	}
	hdlr := fullBoxBytes("hdlr", 0, 0, cat(make([]byte, 4), []byte(s.handler), make([]byte, 12), []byte("h\x00")))
	stsd := fullBoxBytes("stsd", 0, 0, cat(be32(1), s.entry))
	stbl := box("stbl", stsd)
	minf := box("minf", stbl)
	mdia := box("mdia", cat(mdhd, hdlr, minf))
	trakBody := tkhd
	if s.emptyEdit != 0 || s.mediaTime != 0 {
		var entries []byte
		count := uint32(0)
		if s.emptyEdit != 0 {
			entries = append(entries, cat(be32(s.emptyEdit), be32(0xffffffff), be32(0x00010000))...)
			count++
		}
		entries = append(entries, cat(be32(0), be32(uint32(s.mediaTime)), be32(0x00010000))...) // #nosec G115 -- a test's small media time
		count++
		trakBody = cat(trakBody, box("edts", fullBoxBytes("elst", 0, 0, cat(be32(count), entries))))
	}
	trak := box("trak", cat(trakBody, mdia))
	trex := fullBoxBytes("trex", 0, 0, cat(be32(s.trackID), be32(1), be32(s.trexDuration), be32(s.trexSize), be32(s.trexFlags)))
	moov := box("moov", cat(mvhd, trak, box("mvex", trex)))
	ftyp := box("ftyp", []byte("iso5\x00\x00\x02\x00iso5iso6mp41"))
	return cat(ftyp, moov)
}

// avc1Entry is a VisualSampleEntry carrying an avcC of the given profile,
// constraint and level bytes.
func avc1Entry(profile, constraint, level byte) []byte {
	fixed := make([]byte, 70)
	avcC := box("avcC", []byte{1, profile, constraint, level, 0xff, 0xe0})
	return box("avc1", cat(make([]byte, 6), []byte{0, 1}, fixed, avcC))
}

// audioEntry is an AudioSampleEntry of type typ with child boxes.
func audioEntry(typ string, children ...[]byte) []byte {
	fixed := make([]byte, 20)
	return box(typ, cat(append([][]byte{make([]byte, 6), {0, 1}, fixed}, children...)...))
}

// esdsAAC is an esds for MPEG-4 audio object type aot.
func esdsAAC(aot byte) []byte {
	asc := []byte{aot<<3 | 0x01, 0x90}
	if aot >= 32 {
		// escape: 31 in the top five bits, then six bits of aot-32
		ext := aot - 32
		asc = []byte{31<<3 | ext>>3, ext << 5, 0x00}
	}
	dsi := cat([]byte{0x05, byte(len(asc))}, asc)
	dcd := cat([]byte{0x04, byte(13 + len(dsi)), 0x40, 0x15}, make([]byte, 11), dsi)
	es := cat([]byte{0x03, byte(3 + len(dcd) + 3)}, []byte{0, 1, 0}, dcd, []byte{0x06, 0x01, 0x02})
	return fullBoxBytes("esds", 0, 0, es)
}

// videoInit and audioInit are the synthetic inits the pipeline tests' stand-in
// encoders write: a 12800 Hz H.264 video track and a 48 kHz AAC track.
func videoInit(emptyEdit uint32) []byte {
	return initSpec{trackID: 1, handler: "vide", timescale: 12800, movieTimescale: 1000, entry: avc1Entry(0x64, 0, 0x2a), emptyEdit: emptyEdit}.build()
}

func audioInit() []byte {
	return initSpec{trackID: 1, handler: "soun", timescale: 48000, movieTimescale: 1000, entry: audioEntry("mp4a", esdsAAC(2))}.build()
}

// fragSpec describes one synthetic fragment.
type fragSpec struct {
	seq       uint32
	trackID   uint32
	start     uint64
	durations []uint32 // one per sample, in trun
	sync      bool     // the first sample's flags
	v0        bool     // tfdt version 0
}

func (f fragSpec) build() []byte {
	firstFlags := uint32(0x01010000) // depends on others, non-sync
	if f.sync {
		firstFlags = 0x02000000
	}
	tfhd := fullBoxBytes("tfhd", 0, 0x020000|tfhdDefaultSize, cat(be32(f.trackID), be32(4)))
	var tfdt []byte
	if f.v0 {
		tfdt = fullBoxBytes("tfdt", 0, 0, be32(uint32(f.start))) // #nosec G115 -- a test's small start
	} else {
		tfdt = fullBoxBytes("tfdt", 1, 0, be64(f.start))
	}
	var samples []byte
	for _, d := range f.durations {
		samples = append(samples, be32(d)...)
	}
	trun := fullBoxBytes("trun", 0, uint32(trunDataOffset|trunFirstSampleFlags|trunDuration),
		cat(be32(uint32(len(f.durations))), be32(0), be32(firstFlags), samples)) // #nosec G115 -- a test's few samples
	moof := box("moof", cat(fullBoxBytes("mfhd", 0, 0, be32(f.seq)), box("traf", cat(tfhd, tfdt, trun))))
	return cat(moof, box("mdat", make([]byte, 4*len(f.durations))))
}

// videoStream is a synthetic video output: its init, then n fragments of
// perFrag 25 fps frames each (512 ticks at 12800 Hz), every fragment opening
// on a sync sample.
func videoStream(emptyEdit uint32, n, perFrag int) []byte {
	out := videoInit(emptyEdit)
	for i := 0; i < n; i++ {
		d := make([]uint32, perFrag)
		for j := range d {
			d[j] = 512
		}
		out = append(out, fragSpec{seq: uint32(i + 1), trackID: 1, start: uint64(i * perFrag * 512), durations: d, sync: true}.build()...) // #nosec G115 -- a test's small counts
	}
	return out
}

// audioStream is a synthetic AAC output: its init, then n 200 ms fragments
// of 1024-sample frames (9 or 10 frames each, so the starts stay on frames).
func audioStream(n int) []byte {
	out := audioInit()
	start := uint64(0)
	for i := 0; i < n; i++ {
		frames := 9
		if i%3 == 2 {
			frames = 10
		}
		d := make([]uint32, frames)
		for j := range d {
			d[j] = 1024
		}
		out = append(out, fragSpec{seq: uint32(i + 1), trackID: 1, start: start, durations: d, sync: true}.build()...) // #nosec G115 -- a test's small counts
		start += uint64(frames * 1024)
	}
	return out
}

func joinArgs(argv []string) string {
	out := ""
	for i, a := range argv {
		if i > 0 {
			out += " "
		}
		out += a
	}
	return out
}
