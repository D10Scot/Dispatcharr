package hls

import (
	"errors"
	"fmt"
	"strconv"
)

// Mode is an HLS profile's mode (spec D12). 4a-1a runs only ModeTranscode;
// ModeAutomatic exists so the probe's re-probe decision (R37) is the one
// 4a-1d will use, and is decided here.
type Mode int

const (
	// ModeTranscode is the built-in re-encode (ADR 0009's default).
	ModeTranscode Mode = iota
	// ModeAutomatic copies what is compatible (4a-1d).
	ModeAutomatic
)

// Family is a video codec family: what the multivariant's CODECS declares for
// the whole run (4a-1d, spec D12). H264 is the zero value, and the only family
// transcode mode has.
type Family int

// The two families.
const (
	FamilyH264 Family = iota
	FamilyHEVC
)

func (f Family) String() string {
	if f == FamilyHEVC {
		return "hevc"
	}
	return "h264"
}

// qsvEncoder is the family's Quick Sync encoder.
func (f Family) qsvEncoder() string {
	if f == FamilyHEVC {
		return "hevc_qsv"
	}
	return "h264_qsv"
}

// Engine is which encoder a generation runs (spec D11): a Quick Sync or
// software encoder for its family, or, in automatic mode, EngineCopy.
type Engine string

const (
	// EngineQSV is h264_qsv on Intel Quick Sync, behind hwupload.
	EngineQSV Engine = "qsv"
	// EngineSoftware is libx264, the fallback whenever Quick Sync is not
	// usable. The relay encodes in software and says so; it never refuses.
	EngineSoftware Engine = "software"
	// EngineCopy is a generation whose video is copied, not encoded
	// (automatic mode, 4a-1d): no encoder, no hardware device, and the
	// payload's hls_encoder says "copy". Its audio may still be encoded.
	EngineCopy Engine = "copy"
)

// DefaultDevice is the render node the QSV argv and the detection encode
// open.
const DefaultDevice = "/dev/dri/renderD128"

// Rendition names, which are also the path segment a playlist URI uses
// (spec § Session resources).
const (
	RenditionVideo = "video"
	RenditionAAC   = "aac"
	RenditionAC3   = "ac3"
	RenditionEAC3  = "eac3"
)

// audioOrder is every audio rendition in the order they are declared, listed
// and given descriptors: aac on fd 3, ac3 on fd 4, eac3 on fd 5 (spec D6).
// The AAC group is listed first (spec § Playlists).
var audioOrder = []string{RenditionAAC, RenditionAC3, RenditionEAC3}

// fdFor is the descriptor a rendition's encoder output is written to.
func fdFor(name string) int {
	for i, n := range audioOrder {
		if n == name {
			return 3 + i
		}
	}
	return -1
}

// Rendition is one declared audio rendition: fixed at generation 0 for the
// channel's run, as geometry is (spec § Encoder argv, the rendition set).
type Rendition struct {
	// Name is aac, ac3 or eac3.
	Name string
	// Channels is the declared layout's channel count, 2 or 6, which is the
	// multivariant's CHANNELS attribute. Every generation fills the
	// rendition at exactly this count, so CHANNELS stays true across every
	// discontinuity.
	Channels int
	// Language is the generation-0 source's language tag for this
	// rendition, emitted as LANGUAGE only when the probe reported one.
	Language string
}

// Output is what generation 0's probe fixes for the channel's run (D8): the
// geometry, the frame rate, the keyframe interval, the bitrate and the
// declared audio renditions.
type Output struct {
	Width, Height int
	// FrameRate is R: the field rate of an interlaced source, the frame rate
	// of a progressive one, capped at 60.
	FrameRate Rational
	// GOP is G = round(2 x R).
	GOP int
	// VideoBitrate and VideoMaxrate are B and M, in bits per second.
	VideoBitrate, VideoMaxrate int
	// Audio is the declared audio renditions, in audioOrder. AAC is always
	// declared.
	Audio []Rendition
}

// Declared reports the named audio rendition's declaration.
func (o Output) Declared(name string) (Rendition, bool) {
	for _, r := range o.Audio {
		if r.Name == name {
			return r, true
		}
	}
	return Rendition{}, false
}

// Renditions is every rendition the run serves: video and then the audio
// renditions in order.
func (o Output) Renditions() []string {
	out := []string{RenditionVideo}
	for _, r := range o.Audio {
		out = append(out, r.Name)
	}
	return out
}

// Fixed geometry and rate bounds (D8).
const (
	maxWidth     = 1920
	maxHeight    = 1080
	maxFrameRate = 60
)

// ErrNoVideo is a generation-0 probe that found no video stream (D9): the
// HLS attach fails with 502 and the channel's TS clients are unaffected.
var ErrNoVideo = errors.New("hls: no video stream in the source")

// Decide fixes the run's Output from generation 0's probe.
func Decide(p Probe) (Output, error) {
	if p.Video == nil || p.Video.Width <= 0 || p.Video.Height <= 0 {
		return Output{}, ErrNoVideo
	}
	var o Output
	o.Width, o.Height = fit(p.Video.Width, p.Video.Height)
	o.FrameRate = outputRate(*p.Video)
	o.GOP = (4*o.FrameRate.Num + o.FrameRate.Den) / (2 * o.FrameRate.Den)
	switch {
	case o.Height >= 1080:
		o.VideoBitrate, o.VideoMaxrate = 6_000_000, 8_000_000
	case o.Height >= 720:
		o.VideoBitrate, o.VideoMaxrate = 4_000_000, 5_000_000
	default:
		o.VideoBitrate, o.VideoMaxrate = 2_500_000, 3_000_000
	}

	qualifying := p.Qualifying()
	aac := Rendition{Name: RenditionAAC, Channels: 2}
	if len(qualifying) > 0 {
		aac.Language = qualifying[0].Language
	}
	o.Audio = append(o.Audio, aac)
	if src, ok := firstOf(qualifying, "ac3", "eac3"); ok {
		o.Audio = append(o.Audio, Rendition{Name: RenditionAC3, Channels: clampLayout(src.Channels), Language: src.Language})
	}
	if src, ok := firstOf(qualifying, "eac3"); ok {
		o.Audio = append(o.Audio, Rendition{Name: RenditionEAC3, Channels: clampLayout(src.Channels), Language: src.Language})
	}
	return o, nil
}

// fit is D8's geometry: the source's own size when it fits in 1920x1080
// (never upscaled), otherwise scaled down into it with the aspect kept;
// both dimensions even, as 4:2:0 requires.
func fit(w, h int) (int, int) {
	if w > maxWidth || h > maxHeight {
		if w*maxHeight >= h*maxWidth {
			w, h = maxWidth, h*maxWidth/w
		} else {
			w, h = w*maxHeight/h, maxHeight
		}
	}
	return max(2, w&^1), max(2, h&^1)
}

// outputRate is R: 1080i at 25 frames (50 fields) a second becomes 50p; a
// progressive or unknown field order keeps its frame rate (R28: unknown is
// progressive); either is capped at 60. A rate the probe could not read is
// taken as 25, the broadcast rate of the fixtures and of most of Europe.
func outputRate(v Video) Rational {
	r := v.FrameRate
	if r.Num <= 0 || r.Den <= 0 {
		r = Rational{Num: 25, Den: 1}
	}
	if v.Field == FieldInterlaced {
		r.Num *= 2
	}
	if r.Num > maxFrameRate*r.Den {
		r = Rational{Num: maxFrameRate, Den: 1}
	}
	return r
}

// clampLayout is spec § Encoder argv's channel-layout clamp: mono and 2.0
// become 2.0, and anything with more than two channels 5.1 (AC-3 cannot
// carry 7.1, and the bitrate table has only these two).
func clampLayout(channels int) int {
	if channels > 2 {
		return 6
	}
	return 2
}

// firstOf is the first stream whose codec is one of codecs, preferring
// codecs[0] over codecs[1] and so on.
func firstOf(streams []Audio, codecs ...string) (Audio, bool) {
	for _, codec := range codecs {
		for _, s := range streams {
			if s.Codec == codec {
				return s, true
			}
		}
	}
	return Audio{}, false
}

// FillKind is how one generation fills one declared rendition.
type FillKind int

const (
	// FillSilence has no ffmpeg output at all: the relay writes the
	// rendition's segments from a canned silent frame (M8).
	FillSilence FillKind = iota
	// FillEncode encodes a source stream at the declared layout.
	FillEncode
	// FillCopy copies a source stream whose codec and channel count already
	// match the declaration.
	FillCopy
)

func (k FillKind) String() string {
	switch k {
	case FillEncode:
		return "encode"
	case FillCopy:
		return "copy"
	}
	return "silence"
}

// Fill is one rendition's source for one generation.
type Fill struct {
	Kind   FillKind
	Source Audio
}

// Plan is one generation's argv decisions: the engine, whether to
// deinterlace, and how each declared rendition is filled. The Output it
// runs against never changes; the Plan is made again from each generation's
// own probe (D9, D10).
type Plan struct {
	Engine      Engine
	Deinterlace bool
	Fills       map[string]Fill
	// Input is the encoder's own input analysis bound: the bound the
	// generation's probe succeeded with (R30), QuickProbe when zero.
	Input ProbeBound
}

// PlanGeneration fills every declared rendition from this generation's
// probe (spec § Encoder argv, rendition filling). A source stream is copied
// only when its codec is the rendition's and its channel count equals the
// declared one; anything else qualifying is encoded at the declared layout;
// with nothing qualifying the rendition is silence. Undeclared source tracks
// are ignored: a later source that adds E-AC-3 declares nothing new.
func PlanGeneration(o Output, p Probe, engine Engine) Plan {
	plan := Plan{Engine: engine, Fills: map[string]Fill{}}
	if p.Video != nil {
		plan.Deinterlace = p.Video.Field == FieldInterlaced
	}
	qualifying := p.Qualifying()
	for _, r := range o.Audio {
		var src Audio
		var ok bool
		switch r.Name {
		case RenditionAAC:
			// Transcode mode always encodes AAC; copying AAC is automatic
			// mode's (4a-1d).
			if len(qualifying) > 0 {
				src, ok = qualifying[0], true
			}
		case RenditionAC3:
			src, ok = firstOf(qualifying, "ac3", "eac3")
		case RenditionEAC3:
			src, ok = firstOf(qualifying, "eac3")
		}
		if !ok && len(qualifying) > 0 && r.Name != RenditionAAC {
			src, ok = qualifying[0], true
		}
		switch {
		case !ok:
			plan.Fills[r.Name] = Fill{Kind: FillSilence}
		case r.Name != RenditionAAC && src.Codec == r.Name && src.Channels == r.Channels:
			plan.Fills[r.Name] = Fill{Kind: FillCopy, Source: src}
		default:
			plan.Fills[r.Name] = Fill{Kind: FillEncode, Source: src}
		}
	}
	return plan
}

// Extra is StartPipedExtra's descriptor mask for this plan: a pipe at fd
// 3+i for every audio rendition in audioOrder that has an ffmpeg output this
// generation. A declared rendition filled with silence, and an undeclared
// one, get no descriptor.
func (o Output) Extra(plan Plan) []bool {
	extra := make([]bool, len(audioOrder))
	used := false
	for i, name := range audioOrder {
		if f, declared := plan.Fills[name]; declared && f.Kind != FillSilence {
			extra[i] = true
			used = true
		}
	}
	if !used {
		return nil
	}
	return extra
}

// fragFlags is D6's movflags for every output: fragments at keyframes,
// the moov written once the first packets are known -- `empty_moov` refuses
// AC-3 passthrough ("Cannot write moov atom before AC3 packets", M4) -- and
// moof-relative data offsets.
const fragFlags = "frag_keyframe+delay_moov+default_base_moof"

// videoFragFlags adds negative_cts_offsets to the video output's movflags
// (ruling R31). With B-frames -- h264_qsv's default, and any copied source's
// -- the mp4 muxer otherwise shifts the whole track by its reorder delay and
// records the shift as the edit list's media_time; measured on ffmpeg 9.0.1
// with libx264 -bf 2 from a keyframe-aligned start, elst [(0, 1024)] at
// 12800 Hz, 80 ms. The relay strips edit lists (ParseInit, StripEdits), so
// that shift would present the video 80 ms late for the whole generation.
// With negative composition offsets (trun version 1) the muxer needs no
// media_time at all (measured: elst [(0, 0)]), and the empty-edit start
// offset is exact.
const videoFragFlags = fragFlags + "+negative_cts_offsets"

// audioFragment is -frag_duration for the audio outputs: 200 ms fragments,
// so an audio segment is within 0.2 s of its video segment (Apple 7.7).
const audioFragment = "200000"

// Argv is the generation's ffmpeg argv (spec § Encoder argv, transcode
// generation). It carries no input but pipe:0: no lavfi source, nothing that
// could keep the process alive after its stdin closes (D10, M8).
func (o Output) Argv(plan Plan, device string) []string {
	a := []string{"-hide_banner", "-loglevel", "warning", "-nostats"}
	if plan.Engine == EngineQSV {
		a = append(a, "-init_hw_device", "qsv=hw:"+device, "-filter_hw_device", "hw")
	}
	in := plan.Input
	if in.Bytes == 0 {
		in = QuickProbe
	}
	a = append(a,
		"-fflags", "+genpts+discardcorrupt",
		// The encoder analyses its input as the probe did (R30): ffmpeg's
		// default ~5 s would otherwise become the next term of the zap time
		// and the failover gap once the probe's is 3 s.
		"-probesize", strconv.Itoa(in.Bytes), "-analyzeduration", in.microseconds(),
		"-f", "mpegts", "-i", "pipe:0",
		"-map", "0:v:0",
		"-vf", o.filter(plan),
	)
	g := strconv.Itoa(o.GOP)
	b, m := strconv.Itoa(o.VideoBitrate), strconv.Itoa(o.VideoMaxrate)
	if plan.Engine == EngineQSV {
		a = append(a,
			"-c:v", "h264_qsv", "-preset", "veryfast", "-profile:v", "high", "-level", "42",
			"-b:v", b, "-maxrate", m, "-bufsize", m,
			"-g", g, "-idr_interval", "0", "-forced_idr", "1",
		)
	} else {
		a = append(a,
			"-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
			"-profile:v", "high", "-level:v", "4.2",
			"-b:v", b, "-maxrate", m, "-bufsize", m,
			"-g", g, "-keyint_min", g, "-sc_threshold", "0",
		)
	}
	a = append(a,
		"-force_key_frames", "expr:gte(t,n_forced*2)",
		"-f", "mp4", "-movflags", videoFragFlags, "pipe:1",
	)
	for _, name := range audioOrder {
		r, declared := o.Declared(name)
		fill, planned := plan.Fills[name]
		if !declared || !planned || fill.Kind == FillSilence {
			continue
		}
		a = append(a, "-map", "0:i:"+fill.Source.ID)
		a = append(a, audioCodecArgs(r, fill)...)
		a = append(a,
			"-f", "mp4", "-movflags", fragFlags, "-frag_duration", audioFragment,
			fmt.Sprintf("pipe:%d", fdFor(name)),
		)
	}
	return a
}

// filter is the -vf chain: deinterlace when this generation's probe says
// interlaced, then scale, pad and fps to the run's fixed output, then the
// pixel format the encoder takes -- nv12 uploaded to the device for QSV,
// yuv420p for libx264.
func (o Output) filter(plan Plan) string {
	f := ""
	if plan.Deinterlace {
		f = "bwdif=mode=send_field:deint=interlaced,"
	}
	f += fmt.Sprintf("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,fps=%s,",
		o.Width, o.Height, o.Width, o.Height, o.FrameRate)
	if plan.Engine == EngineQSV {
		return f + "format=nv12,hwupload=extra_hw_frames=64"
	}
	return f + "format=yuv420p"
}

// audioCodecArgs is one rendition's codec arguments: copy, or an encode at
// the declared layout with the bitrate table's rate.
func audioCodecArgs(r Rendition, fill Fill) []string {
	if fill.Kind == FillCopy {
		return []string{"-c:a", "copy"}
	}
	codec := map[string]string{RenditionAAC: "aac", RenditionAC3: "ac3", RenditionEAC3: "eac3"}[r.Name]
	return []string{"-c:a", codec, "-ac", strconv.Itoa(r.Channels), "-b:a", strconv.Itoa(audioBitrate(r))}
}

// audioBitrate is the bitrate table: AAC 160 kb/s stereo; AC-3 640 kb/s at
// 5.1 and 192 kb/s at 2.0; E-AC-3 640 kb/s at 5.1 and 256 kb/s at 2.0.
func audioBitrate(r Rendition) int {
	switch r.Name {
	case RenditionAC3:
		if r.Channels == 6 {
			return 640_000
		}
		return 192_000
	case RenditionEAC3:
		if r.Channels == 6 {
			return 640_000
		}
		return 256_000
	}
	return 160_000
}
