package hls

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"
)

// The probe (Phase 4 spec, D9 as amended by ruling R30): `ffprobe
// -show_streams -of json` over the bytes a generation will start from,
// decoded with encoding/json. It decides interlacing, frame rate, geometry
// and which audio streams qualify. Automatic mode's also lists the window's
// packets (ProbeArgvFor).

// ProbeBound is one probe's bound: ffprobe's -probesize and
// -analyzeduration, and the feed's own byte and wall-clock limits, which are
// the same numbers so ffprobe never waits for bytes the relay has stopped
// sending. The encoder's input analysis uses the bound its generation's probe
// succeeded with.
type ProbeBound struct {
	Bytes   int
	Analyze time.Duration
}

// QuickProbe is every generation's first probe (R30): 3 s of analysis, and
// 3,000,000 bytes, which is 3 s of an 8 Mb/s source (a faster source ends on
// bytes first). On an MPEG-TS pipe ffprobe reads to its analyze bound
// whatever it has found, so this bound IS the probe's share of the zap time
// and of the failover gap; 3 s exceeds a 2 s GOP, and the plan review
// measured every decision on the 4a-0 fixtures identical to a full probe at
// 2.5-3 s, and width, height and field order lost at 1 s.
//
// FullProbe is D9's original bound, 5 MB or 8 s, used for one re-probe only
// when the quick one found video without its geometry or field order: a GOP
// longer than 3 s, say.
var (
	QuickProbe = ProbeBound{Bytes: 3_000_000, Analyze: 3 * time.Second}
	FullProbe  = ProbeBound{Bytes: 5_000_000, Analyze: 8 * time.Second}
)

// microseconds is ffmpeg's -analyzeduration unit.
func (b ProbeBound) microseconds() string {
	return strconv.FormatInt(b.Analyze.Microseconds(), 10)
}

// ProbeArgvFor is the ffprobe argv for a bound in a mode. Transcode's is
// ProbeArgv, unchanged. Automatic mode's lists the window's packets as well
// (spec § Automatic generation, "The probe in automatic mode"; R77):
// `-show_entries packet=...` gives the keyframe count, their longest interval
// and the video's rate, and `-read_intervals %+<seconds>` makes ffprobe stop
// after that much media, because without it listing packets waits for stdin's
// EOF, which the relay's feed gives only at the byte or wall bound. It is one
// ffprobe run: every stream field of -show_streams is kept.
func ProbeArgvFor(b ProbeBound, mode Mode) []string {
	if mode != ModeAutomatic {
		return ProbeArgv(b)
	}
	return []string{
		"-hide_banner", "-loglevel", "error",
		"-probesize", strconv.Itoa(b.Bytes),
		"-analyzeduration", b.microseconds(),
		"-f", "mpegts", "-i", "pipe:0",
		"-read_intervals", "%+" + strconv.Itoa(int(b.Analyze/time.Second)),
		"-show_streams", "-show_entries", "packet=stream_index,pts_time,flags,size",
		"-of", "json",
	}
}

// ProbeArgv is the ffprobe argv for a bound.
func ProbeArgv(b ProbeBound) []string {
	return []string{
		"-hide_banner", "-loglevel", "error",
		"-probesize", strconv.Itoa(b.Bytes),
		"-analyzeduration", b.microseconds(),
		"-f", "mpegts", "-i", "pipe:0",
		"-show_streams", "-of", "json",
	}
}

// FieldOrder is ffprobe's field_order, kept as THREE states (ruling R28,
// issue #525): progressive, interlaced (tt, bb, tb or bt), and unknown.
// Unknown is what ffprobe reports for a progressive HEVC stream in a
// transport stream, because HEVC signals field coding in SEI rather than in
// the parameters ffprobe reads. It is never folded into interlaced: it is
// treated as progressive for deinterlacing here and for copy eligibility in
// 4a-1d, but it stays distinct so 4a-1d's rule, and a log line, can say
// which it was.
type FieldOrder int

// The three field orders.
const (
	// FieldUnknown is ffprobe's "unknown" or an absent field_order.
	FieldUnknown FieldOrder = iota
	// FieldProgressive is "progressive".
	FieldProgressive
	// FieldInterlaced is tt, bb, tb or bt.
	FieldInterlaced
)

func (f FieldOrder) String() string {
	switch f {
	case FieldProgressive:
		return "progressive"
	case FieldInterlaced:
		return "interlaced"
	}
	return "unknown"
}

// parseFieldOrder maps ffprobe's value. Only an explicit tt, bb, tb or bt is
// interlaced (R28).
func parseFieldOrder(value string) FieldOrder {
	switch value {
	case "progressive":
		return FieldProgressive
	case "tt", "bb", "tb", "bt":
		return FieldInterlaced
	}
	return FieldUnknown
}

// Rational is a frame rate as ffprobe reports it, "25/1" or "30000/1001".
type Rational struct{ Num, Den int }

// parseRational reads "a/b"; ok is false for "0/0" and anything unparsable.
func parseRational(value string) (Rational, bool) {
	a, b, found := strings.Cut(value, "/")
	if !found {
		return Rational{}, false
	}
	num, err1 := strconv.Atoi(a)
	den, err2 := strconv.Atoi(b)
	if err1 != nil || err2 != nil || num <= 0 || den <= 0 {
		return Rational{}, false
	}
	return Rational{Num: num, Den: den}, true
}

// Float is the rate as a decimal.
func (r Rational) Float() float64 {
	if r.Den == 0 {
		return 0
	}
	return float64(r.Num) / float64(r.Den)
}

// String is "num/den", which ffmpeg's fps filter takes as it is.
func (r Rational) String() string { return fmt.Sprintf("%d/%d", r.Num, r.Den) }

// Video is the first video stream the probe found.
type Video struct {
	ID string
	// Index is ffprobe's stream index, which the packet list is keyed by.
	Index int
	// Level is ffprobe's level: 30, 42 or 51 for H.264, 63, 93, 123 or 150
	// for HEVC; 0 when unreported.
	Level     int
	Codec     string
	Profile   string
	PixFmt    string
	Width     int
	Height    int
	FrameRate Rational
	Field     FieldOrder
	// fieldReported is whether ffprobe printed a field_order at all -- it
	// omits the key until it has decoded a frame, which is different from
	// reporting "unknown".
	fieldReported bool
}

// Complete is whether the probe saw enough of the video to decide from:
// its geometry and its field order (R30's re-probe condition).
//
// HEVC is complete on its geometry alone (R28, issue #525): ffprobe's JSON
// never prints a field_order for it, not even "unknown" (measured, ffprobe
// 9.0.1), because HEVC signals field coding in SEI. Waiting for the key would
// re-probe every HEVC generation at the full bound and skip one whose feed
// ends inside the window. Its field order stays FieldUnknown, treated as
// progressive.
func (v Video) Complete() bool {
	if v.Codec == "hevc" {
		return v.Width > 0 && v.Height > 0
	}
	return v.Width > 0 && v.Height > 0 && v.fieldReported
}

// Audio is one audio stream the probe found, qualifying or not.
type Audio struct {
	// ID is the stream id ffprobe reports, the PID for a transport stream
	// ("0x301"). The argv maps a stream by it (`-map 0:i:0x301`), so a
	// stream's index can never be confused with another's.
	ID         string
	Codec      string
	Profile    string
	Channels   int
	SampleRate int
	Language   string
}

// Qualifies is spec § Encoder argv's rule: a known codec_name, channels > 0
// and sample_rate > 0. A transport stream's PMT can declare an audio PID that
// carries no packets; ffprobe then reports it with 0 channels and a sample
// rate of 0 (measured, ffmpeg 9.0.1), and mapping it makes ffmpeg fail every
// output of the generation (finding 7).
func (a Audio) Qualifies() bool {
	switch a.Codec {
	case "", "unknown", "none":
		return false
	}
	return a.Channels > 0 && a.SampleRate > 0
}

// Probe is what one probe found.
type Probe struct {
	// Video is nil when the source has no video stream, which fails the HLS
	// attach (D9).
	Video *Video
	// Audio is every audio stream, in the order ffprobe listed them.
	Audio []Audio
	// Keyframes is how many video keyframes the probe window held. Only
	// automatic mode's probe counts them (4a-1d, spec § Automatic
	// generation); 4a-1a's probe leaves it 0, and only automatic mode's
	// re-probe decision reads it (R37).
	Keyframes int
	// KeyframeInterval is the longest gap between consecutive video
	// keyframes in the window, exactly (integer microseconds), and 0 with
	// fewer than two keyframes. Automatic mode's probe only.
	KeyframeInterval time.Duration
	// BitRate is the video's rate over the window in bits per second: eight
	// times the video packets' total size over the video's pts span, and 0
	// when the span is 0. Video only, because the multivariant adds each
	// audio group's own rate. Automatic mode's probe only.
	BitRate int
}

// Qualifying is the audio streams that qualify, in order.
func (p Probe) Qualifying() []Audio {
	var out []Audio
	for _, a := range p.Audio {
		if a.Qualifies() {
			out = append(out, a)
		}
	}
	return out
}

// probeJSON is the part of ffprobe's -show_streams JSON this package reads.
type probeJSON struct {
	Streams []struct {
		Index        int               `json:"index"`
		ID           string            `json:"id"`
		CodecType    string            `json:"codec_type"`
		CodecName    string            `json:"codec_name"`
		Profile      string            `json:"profile"`
		Level        int               `json:"level"`
		PixFmt       string            `json:"pix_fmt"`
		FieldOrder   *string           `json:"field_order"`
		Width        int               `json:"width"`
		Height       int               `json:"height"`
		RFrameRate   string            `json:"r_frame_rate"`
		AvgFrameRate string            `json:"avg_frame_rate"`
		SampleRate   string            `json:"sample_rate"`
		Channels     int               `json:"channels"`
		Tags         map[string]string `json:"tags"`
	} `json:"streams"`
	Packets []struct {
		StreamIndex int    `json:"stream_index"`
		PtsTime     string `json:"pts_time"`
		Flags       string `json:"flags"`
		Size        string `json:"size"`
	} `json:"packets"`
}

// ParseProbe decodes ffprobe's JSON.
func ParseProbe(raw []byte) (Probe, error) {
	var doc probeJSON
	if err := json.Unmarshal(raw, &doc); err != nil {
		return Probe{}, fmt.Errorf("hls: the probe's JSON: %w", err) // credential-logging: ok - a JSON syntax error over ffprobe's stream list, which carries no URL
	}
	var p Probe
	for _, s := range doc.Streams {
		switch s.CodecType {
		case "video":
			if p.Video != nil {
				continue
			}
			rate, ok := parseRational(s.RFrameRate)
			if !ok {
				rate, _ = parseRational(s.AvgFrameRate)
			}
			v := &Video{
				ID: s.ID, Index: s.Index, Level: max(0, s.Level), Codec: s.CodecName, Profile: s.Profile, PixFmt: s.PixFmt,
				Width: s.Width, Height: s.Height, FrameRate: rate,
			}
			if s.FieldOrder != nil {
				v.Field, v.fieldReported = parseFieldOrder(*s.FieldOrder), true
			}
			p.Video = v
		case "audio":
			rate, _ := strconv.Atoi(s.SampleRate)
			p.Audio = append(p.Audio, Audio{
				ID: s.ID, Codec: s.CodecName, Profile: s.Profile, Channels: s.Channels, SampleRate: rate,
				Language: s.Tags["language"],
			})
		}
	}
	if p.Video != nil {
		p.countPackets(doc)
	}
	return p, nil
}

// countPackets fills Keyframes, KeyframeInterval and BitRate from the first
// video stream's packets. Every time is integer microseconds, so the interval
// of a 2.1 s GOP is exactly 2.1 s and never the float difference 2.0999...
func (p *Probe) countPackets(doc probeJSON) {
	var keys []int64
	var total, first, last int64
	seen := false
	for _, pkt := range doc.Packets {
		if pkt.StreamIndex != p.Video.Index {
			continue
		}
		at, ok := parseMicroseconds(pkt.PtsTime)
		if !ok {
			continue
		}
		if size, err := strconv.ParseInt(pkt.Size, 10, 64); err == nil {
			total += size
		}
		if !seen || at < first {
			first = at
		}
		if !seen || at > last {
			last = at
		}
		seen = true
		if strings.Contains(pkt.Flags, "K") {
			keys = append(keys, at)
		}
	}
	p.Keyframes = len(keys)
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	for i := 1; i < len(keys); i++ {
		p.KeyframeInterval = max(p.KeyframeInterval, time.Duration(keys[i]-keys[i-1])*time.Microsecond)
	}
	if span := last - first; seen && span > 0 {
		p.BitRate = int(8 * total * 1_000_000 / span)
	}
}

// parseMicroseconds reads ffprobe's six-decimal seconds ("1.480000") as
// integer microseconds without going through a float. "N/A" and anything else
// unparsable is not ok.
func parseMicroseconds(value string) (int64, bool) {
	whole, frac, _ := strings.Cut(value, ".")
	negative := strings.HasPrefix(whole, "-")
	seconds, err := strconv.ParseInt(strings.TrimPrefix(whole, "-"), 10, 64)
	if err != nil {
		return 0, false
	}
	frac = (frac + "000000")[:6]
	micros, err := strconv.ParseInt(frac, 10, 64)
	if err != nil {
		return 0, false
	}
	total := seconds*1_000_000 + micros
	if negative {
		total = -total
	}
	return total, true
}
