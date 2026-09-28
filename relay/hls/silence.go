package hls

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// Silence is synthesised by the relay, never by ffmpeg (spec M8). An ffmpeg
// `anullsrc` input keeps a generation alive after its stdin closes, which
// breaks D10, and floods unpaced audio; so a rendition filled with silence
// has no output in the argv, and the segmenter writes its segments itself,
// from one canned silent frame.

// SilenceTimeout bounds the one-off canned encode.
const SilenceTimeout = 10 * time.Second

// AudioTimescale is Ta, the audio timescale every canned encode and every
// audio rendition runs at (48 kHz).
const AudioTimescale = 48000

// Canned is one (codec, declared layout)'s silent frame, as the relay
// repeats it.
type Canned struct {
	// Init is the canned encode's init segment with its edit list stripped:
	// M8 measured an AC-3 init with media_time 256 (5.3 ms), and every
	// silent rendition must present from 0 in its own timeline, aligned with
	// the video. It serves every generation's EXT-X-MAP for its rendition.
	Init []byte
	// Track is Init, parsed.
	Track Track
	// Frame is one steady-state frame. M8: every steady-state frame of a
	// silent encode is byte-identical.
	Frame []byte
	// SamplesPerFrame is spf: 1024 for AAC, 1536 for AC-3 and E-AC-3.
	SamplesPerFrame uint32
}

// SilenceArgv is the canned encode for one rendition at its declared layout:
// one second of anullsrc, at the rendition's bitrate, to fragmented MP4 on
// stdout. It is bounded twice, by -t 1 and by SilenceTimeout.
func SilenceArgv(r Rendition) []string {
	layout := "stereo"
	if r.Channels == 6 {
		layout = "5.1"
	}
	codec := map[string]string{RenditionAAC: "aac", RenditionAC3: "ac3", RenditionEAC3: "eac3"}[r.Name]
	return []string{
		"-hide_banner", "-loglevel", "error",
		"-f", "lavfi", "-i", "anullsrc=r=48000:cl=" + layout,
		"-t", "1",
		"-c:a", codec, "-ac", strconv.Itoa(r.Channels), "-b:a", strconv.Itoa(audioBitrate(r)),
		"-f", "mp4", "-movflags", fragFlags, "-frag_duration", audioFragment,
		"pipe:1",
	}
}

type cannedKey struct {
	name     string
	channels int
}

// SilenceCache runs each canned encode at the first need in the process and
// keeps the result for the life of the process (spec § Encoder argv). One is
// shared by every pipeline. A failed encode is not cached: the next
// generation that needs silence tries again.
type SilenceCache struct {
	// Command is the ffmpeg executable ("ffmpeg" when empty).
	Command string
	// Log receives a failed encode's stderr.
	Log *slog.Logger

	// run serialises the encodes and guards entries. A caller that gives
	// up waiting on it gets its context's error.
	run     ctxLock
	entries map[cannedKey]*Canned
}

// Get is rendition r's canned frame, encoding it on first use.
func (s *SilenceCache) Get(ctx context.Context, r Rendition) (*Canned, error) {
	if err := s.run.lock(ctx); err != nil {
		return nil, err
	}
	defer s.run.unlock()
	key := cannedKey{name: r.Name, channels: r.Channels}
	if c, ok := s.entries[key]; ok {
		return c, nil
	}
	c, err := s.encode(ctx, r)
	if err != nil {
		return nil, err
	}
	if s.entries == nil {
		s.entries = map[cannedKey]*Canned{}
	}
	s.entries[key] = c
	return c, nil
}

// errNoSteadyFrame is a canned encode whose middle frames differ, which would
// make "repeat one frame" a different signal from the encoder's own.
var errNoSteadyFrame = errors.New("hls: the canned silent encode has no steady-state frame")

func (s *SilenceCache) encode(ctx context.Context, r Rendition) (*Canned, error) {
	command := s.Command
	if command == "" {
		command = "ffmpeg"
	}
	log := s.Log
	if log == nil {
		log = slog.Default()
	}
	ctx, cancel := context.WithTimeout(ctx, SilenceTimeout)
	defer cancel()
	proc, err := ffmpeg.Start(ctx, command, SilenceArgv(r))
	if err != nil {
		return nil, fmt.Errorf("hls: starting the canned %s encode: %w", r.Name, redact.Error(err))
	}
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		proc.ReadStderr(func(line string) {
			log.Warn("canned silence encode stderr", "rendition", r.Name, "line", redact.Line(line))
		})
	}()
	var out bytes.Buffer
	_, copyErr := io.Copy(&out, io.LimitReader(proc.Stdout(), maxBoxBytes))
	waitErr := proc.Wait()
	<-stderrDone
	if waitErr != nil || copyErr != nil {
		return nil, fmt.Errorf("hls: the canned %s encode failed: %w", r.Name, redact.Error(errors.Join(waitErr, copyErr)))
	}
	return cannedFrom(out.Bytes())
}

// cannedFrom parses a canned encode: its init, and a steady-state frame from
// the middle of its samples, checked to be identical to its successor.
func cannedFrom(raw []byte) (*Canned, error) {
	var init []byte
	var track Track
	var frames [][]byte
	var spf uint32
	sp := splitter{
		onInit: func(b []byte) error {
			t, err := ParseInit(b)
			if err != nil {
				return err
			}
			stripped, err := StripEdits(b)
			if err != nil {
				return err
			}
			init, track = stripped, t
			return nil
		},
		onFrag: func(b []byte) error {
			samples, durations, err := fragmentSamples(b, track)
			if err != nil {
				return err
			}
			frames = append(frames, samples...)
			if spf == 0 && len(durations) > 0 {
				spf = durations[0]
			}
			return nil
		},
	}
	if err := sp.read(bytes.NewReader(raw)); err != nil {
		return nil, err
	}
	if init == nil || len(frames) < 4 || spf == 0 {
		return nil, errNoSteadyFrame
	}
	mid := len(frames) / 2
	if !bytes.Equal(frames[mid], frames[mid+1]) {
		return nil, errNoSteadyFrame
	}
	return &Canned{Init: init, Track: track, Frame: frames[mid], SamplesPerFrame: spf}, nil
}

// fragmentSamples splits a fragment's mdat into its samples, with each
// sample's duration. It reads the trun's data offset relative to the moof
// (default-base-is-moof, which fragFlags asks for).
func fragmentSamples(data []byte, t Track) (samples [][]byte, durations []uint32, err error) {
	moof, ok := child(data, 0, len(data), "moof")
	if !ok {
		return nil, nil, boxErr("no moof")
	}
	traf, _ := child(data, moof.body, moof.end, "traf")
	tfhd, ok := child(data, traf.body, traf.end, "tfhd")
	if !ok {
		return nil, nil, boxErr("no tfhd")
	}
	_, hflags, _ := fullBox(data, tfhd)
	c := cursor{data: data, pos: tfhd.body + 8, end: tfhd.end}
	if hflags&tfhdBaseDataOffset != 0 {
		c.take(8)
	}
	if hflags&tfhdSampleDescIndex != 0 {
		c.take(4)
	}
	dur, size := t.DefaultDuration, t.DefaultSize
	if hflags&tfhdDefaultDuration != 0 {
		dur = c.u32()
	}
	if hflags&tfhdDefaultSize != 0 {
		size = c.u32()
	}
	trun, ok := child(data, traf.body, traf.end, "trun")
	if !ok {
		return nil, nil, boxErr("no trun")
	}
	_, rflags, _ := fullBox(data, trun)
	tf := trunFlags(rflags)
	rc := cursor{data: data, pos: trun.body + 4, end: trun.end}
	count := rc.u32()
	offset := int64(0)
	if tf&trunDataOffset != 0 {
		offset = int64(int32(rc.u32())) // #nosec G115 -- trun's data_offset is a signed 32-bit field (ISO/IEC 14496-12)
	}
	if tf&trunFirstSampleFlags != 0 {
		rc.take(4)
	}
	if c.bad || rc.bad || count > 1<<16 {
		return nil, nil, boxErr("short tfhd or trun")
	}
	pos := int64(moof.start) + offset
	for i := uint32(0); i < count; i++ {
		d, sz := dur, size
		if tf&trunDuration != 0 {
			d = rc.u32()
		}
		if tf&trunSize != 0 {
			sz = rc.u32()
		}
		if tf&trunFlagsPresent != 0 {
			rc.take(4)
		}
		if tf&trunCTO != 0 {
			rc.take(4)
		}
		if rc.bad || pos < 0 || pos+int64(sz) > int64(len(data)) {
			return nil, nil, boxErr("sample %d is outside its fragment", i)
		}
		samples = append(samples, data[pos:pos+int64(sz)])
		durations = append(durations, d)
		pos += int64(sz)
	}
	return samples, durations, nil
}

// silenceClock is one silent rendition's frame count within one generation
// (spec § Encoder argv, silence). The arithmetic is integer and absolute per
// generation: a segment's end, in ticks of the video timescale Tv measured
// from the generation's first video tfdt, becomes a frame index at the audio
// timescale Ta with a single ceiling,
//
//	ceil(end_ticks x Ta / (Tv x spf)) = (end_ticks x Ta + Tv x spf - 1) / (Tv x spf)
//
// in 64-bit integers, with no intermediate floor, so the count is exact and
// every segment's end is within one frame of its video segment's end: the
// error never accumulates.
type silenceClock struct {
	canned *Canned
	// base is the generation's first video tfdt in audio ticks, so frame 0
	// presents with the generation's first video frame. The spec counts
	// frames from that tfdt; placing them there on the shared timeline is
	// what aligns them with the video by tfdt (ParseInit).
	base uint64
	// next is the index of the next frame to write.
	next uint64
	// seq is the mfhd sequence number of the next fragment.
	seq uint32
}

// endIndex is the frame index a segment ending endRel video ticks after the
// generation's first video tfdt ends at: the single ceiling.
func (s *silenceClock) endIndex(endRel uint64, tv uint32) uint64 {
	unit := uint64(tv) * uint64(s.canned.SamplesPerFrame)
	return (endRel*uint64(s.canned.Track.Timescale) + unit - 1) / unit
}

// segment writes the silent fragment for the video segment that ends endRel
// video ticks after the generation's first video tfdt, and returns it with
// its duration in audio ticks.
func (s *silenceClock) segment(endRel uint64, tv uint32) ([]byte, uint64) {
	spf := uint64(s.canned.SamplesPerFrame)
	end := s.endIndex(endRel, tv)
	count := uint64(1)
	if end > s.next {
		count = end - s.next
	}
	// A segment shorter than one frame still gets one: the rendition must
	// have a segment at every sequence number, and the next segment's count
	// is computed from the absolute index, so the extra frame is taken back
	// there rather than accumulating.
	start := s.base + s.next*spf
	s.seq++
	data := synthFragment(s.seq, s.canned.Track.ID, start, s.canned.Frame, int(count), s.canned.SamplesPerFrame) // #nosec G115 -- count is a segment's frames, a few hundred
	s.next += count
	return data, count * spf
}
