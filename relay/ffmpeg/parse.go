package ffmpeg

import (
	"regexp"
	"strconv"
	"strings"
)

// Info is what one parsed stderr line says about the stream: the dict
// apps/proxy/live_proxy/services/log_parsers.py's parse methods return, with a
// nil pointer wherever Python leaves the key unset. Presence matters because
// channel_service._update_stream_info_in_redis (channel_service.py:844-880)
// writes only the keys that are not None, so a later line that names the codec
// and nothing else must not blank the resolution an earlier line set.
type Info struct {
	VideoCodec   *string
	Resolution   *string
	Width        *int
	Height       *int
	SourceFPS    *float64
	PixelFormat  *string
	VideoBitrate *float64

	AudioCodec    *string
	SampleRate    *int
	AudioChannels *string
	AudioBitrate  *float64

	// InputFormat is the dict's 'stream_type' key -- "mpegts", "hls" -- which
	// channel_service stores under ChannelMetadataField.STREAM_TYPE and the
	// list endpoint renders as stream_type. The Python name is kept on the
	// wire and not here, because here it would read as the KIND of parse.
	InputFormat *string
}

// Kind is what a parser says a line is: log_parsers.py's stream_type strings,
// spelled exactly, because input/manager.py:1080 branches on them by name.
type Kind string

// The seven kinds. VLCInputFailed is the one that never carries an Info: it is
// a signal to the caller (input/manager.py:1059-1064 closes the socket on it),
// not a parse.
const (
	KindInput          Kind = "input"
	KindVideo          Kind = "video"
	KindAudio          Kind = "audio"
	KindVLCVideo       Kind = "vlc_video"
	KindVLCAudio       Kind = "vlc_audio"
	KindVLCInputFailed Kind = "vlc_input_failed"
	KindStreamlink     Kind = "streamlink"
)

// Tool names the parser that handles a command's output.
type Tool string

// The three tools, keyed by input/manager.py:797-802's command_to_parser
// mapping.
const (
	ToolFFmpeg     Tool = "ffmpeg"
	ToolVLC        Tool = "vlc"
	ToolStreamlink Tool = "streamlink"
)

// ToolFor maps a Stream Profile's command to its parser, exactly as
// input/manager.py:797-803 does: the WHOLE command string, lowercased, looked
// up in a four-entry map. "/usr/bin/ffmpeg" is therefore unknown and falls
// back to auto-detection, which is the Python behaviour and is not improved
// here.
func ToolFor(command string) (Tool, bool) {
	switch strings.ToLower(command) {
	case "ffmpeg":
		return ToolFFmpeg, true
	case "cvlc", "vlc":
		return ToolVLC, true
	case "streamlink":
		return ToolStreamlink, true
	}
	return "", false
}

// factoryOrder is LogParserFactory._parsers' insertion order
// (log_parsers.py:364-368), which is the order AutoParse tries them in.
var factoryOrder = []Tool{ToolFFmpeg, ToolVLC, ToolStreamlink}

// CanParse reports which kind of line this is for the tool, or "" when the
// tool's parser does not recognise it. The port of each parser's can_parse.
func CanParse(tool Tool, line string) Kind {
	lower := strings.ToLower(line)
	switch tool {
	case ToolFFmpeg:
		// log_parsers.py:47-62.
		if strings.HasPrefix(lower, "input #") {
			return KindInput
		}
		if strings.Contains(lower, "stream #") {
			if strings.Contains(lower, "video:") {
				return KindVideo
			} else if strings.Contains(lower, "audio:") {
				return KindAudio
			}
		}
	case ToolVLC:
		// log_parsers.py:163-186.
		if strings.Contains(lower, "unable to open the mrl") {
			return KindVLCInputFailed
		}
		if strings.Contains(lower, "ts demux debug") && strings.Contains(lower, "type=") {
			if strings.Contains(lower, "video") {
				return KindVLCVideo
			} else if strings.Contains(lower, "audio") {
				return KindVLCAudio
			}
		}
		// 'x' in line: the ORIGINAL line, case-sensitively, as the Python
		// reads `'x' in line` beside three checks against `lower`.
		if strings.Contains(lower, "decoder") &&
			(strings.Contains(lower, "channels:") || strings.Contains(lower, "samplerate:") ||
				strings.Contains(line, "x") || strings.Contains(lower, "fps")) {
			if strings.Contains(lower, "audio") || strings.Contains(lower, "channels:") || strings.Contains(lower, "samplerate:") {
				return KindVLCAudio
			}
			return KindVLCVideo
		}
		if strings.Contains(lower, "stream_out_transcode") &&
			(strings.Contains(lower, "source fps") || (strings.Contains(lower, "source ") && strings.Contains(line, "x"))) {
			return KindVLCVideo
		}
	case ToolStreamlink:
		// log_parsers.py:312-319.
		if strings.Contains(lower, "opening stream:") || strings.Contains(lower, "available streams:") {
			return KindStreamlink
		}
	}
	return ""
}

// Parse parses a line as the given kind. The port of LogParserFactory.parse:
// the kind picks the parser AND the method through each parser's
// STREAM_TYPE_METHODS, so KindVLCInputFailed -- which no parser lists --
// returns nothing, exactly as parse('vlc_input_failed', ...) does.
func Parse(kind Kind, line string) (Info, bool) {
	switch kind {
	case KindInput:
		return ffmpegInputFormat(line)
	case KindVideo:
		return ffmpegVideo(line)
	case KindAudio:
		return ffmpegAudio(line)
	case KindVLCVideo:
		return vlcVideo(line)
	case KindVLCAudio:
		return vlcAudio(line)
	case KindStreamlink:
		return streamlinkVideo(line)
	}
	return Info{}, false
}

// AutoParse tries every parser in factory order and returns the first that
// both recognises the line AND parses something out of it. The port of
// LogParserFactory.auto_parse (log_parsers.py:399-413), including its one
// consequence worth knowing: a VLC "unable to open the MRL" line is recognised
// (KindVLCInputFailed) but parses to nothing, so AutoParse moves on and never
// reports it. Only the direct route through ToolFor + CanParse sees it, which
// is why input/manager.py's socket-closing branch is reachable only when the
// command is literally "vlc" or "cvlc".
func AutoParse(line string) (Kind, Info, bool) {
	for _, tool := range factoryOrder {
		kind := CanParse(tool, line)
		if kind == "" {
			continue
		}
		if info, ok := Parse(kind, line); ok {
			return kind, info, true
		}
	}
	return "", Info{}, false
}

// The FFmpeg regexes, log_parsers.py:67-133, as RE2. Every one is expressible
// verbatim: \b is an ASCII word boundary in both engines for these inputs,
// and \d is ASCII-only here where Python's is Unicode-aware -- a difference
// no ffmpeg build produces text to exercise.
var (
	ffInputRe       = regexp.MustCompile(`Input #\d+,\s*([^,]+)`)
	ffVideoCodecRe  = regexp.MustCompile(`Video:\s*([a-zA-Z0-9_]+)`)
	ffResolutionRe  = regexp.MustCompile(`\b(\d{3,5})x(\d{3,5})\b`)
	ffFPSRe         = regexp.MustCompile(`(\d+(?:\.\d+)?)\s*fps`)
	ffPixelFormatRe = regexp.MustCompile(`Video:\s*[^,]+,\s*([^,(]+)`)
	ffKbpsRe        = regexp.MustCompile(`(\d+(?:\.\d+)?)\s*kb/s`)
	ffAudioCodecRe  = regexp.MustCompile(`Audio:\s*([a-zA-Z0-9_]+)`)
	ffSampleRateRe  = regexp.MustCompile(`(\d+)\s*Hz`)
	ffChannelsRe    = regexp.MustCompile(`(?i)\b(mono|stereo|5\.1|7\.1|quad|2\.1)\b`)
)

func ffmpegInputFormat(line string) (Info, bool) {
	m := ffInputRe.FindStringSubmatch(line)
	if m == nil {
		return Info{}, false
	}
	format := strings.TrimSpace(m[1])
	if format == "" {
		return Info{}, false
	}
	return Info{InputFormat: &format}, true
}

// resolutionWithin applies the 100..10000 bound both Python video parsers
// share (log_parsers.py:92, :210, :220).
func resolutionWithin(w, h int) bool {
	return w >= 100 && w <= 10000 && h >= 100 && h <= 10000
}

func ffmpegVideo(line string) (Info, bool) {
	var info Info
	set := false
	if m := ffVideoCodecRe.FindStringSubmatch(line); m != nil {
		info.VideoCodec = ptr(m[1])
		set = true
	}
	if m := ffResolutionRe.FindStringSubmatch(line); m != nil {
		w, _ := strconv.Atoi(m[1])
		h, _ := strconv.Atoi(m[2])
		if resolutionWithin(w, h) {
			info.Resolution = ptr(m[1] + "x" + m[2])
			info.Width, info.Height = ptr(w), ptr(h)
			set = true
		}
	}
	if m := ffFPSRe.FindStringSubmatch(line); m != nil {
		if fps, err := strconv.ParseFloat(m[1], 64); err == nil {
			info.SourceFPS = ptr(fps)
			set = true
		}
	}
	if m := ffPixelFormatRe.FindStringSubmatch(line); m != nil {
		pf := strings.TrimSpace(m[1])
		// log_parsers.py:104-105 splits at '(' -- unreachable, since the
		// capture group already excludes it. Ported so the shape matches.
		if before, _, found := strings.Cut(pf, "("); found {
			pf = strings.TrimSpace(before)
		}
		info.PixelFormat = ptr(pf)
		set = true
	}
	if m := ffKbpsRe.FindStringSubmatch(line); m != nil {
		if kbps, err := strconv.ParseFloat(m[1], 64); err == nil {
			info.VideoBitrate = ptr(kbps)
			set = true
		}
	}
	return info, set
}

func ffmpegAudio(line string) (Info, bool) {
	var info Info
	set := false
	if m := ffAudioCodecRe.FindStringSubmatch(line); m != nil {
		info.AudioCodec = ptr(m[1])
		set = true
	}
	if m := ffSampleRateRe.FindStringSubmatch(line); m != nil {
		if hz, err := strconv.Atoi(m[1]); err == nil {
			info.SampleRate = ptr(hz)
			set = true
		}
	}
	if m := ffChannelsRe.FindStringSubmatch(line); m != nil {
		info.AudioChannels = ptr(m[1])
		set = true
	}
	if m := ffKbpsRe.FindStringSubmatch(line); m != nil {
		if kbps, err := strconv.ParseFloat(m[1], 64); err == nil {
			info.AudioBitrate = ptr(kbps)
			set = true
		}
	}
	return info, set
}

// The VLC codec maps, log_parsers.py:199-204 and :263-268, in their
// insertion order: Python iterates a dict and takes the FIRST tuple with any
// matching pattern, so order is behaviour.
var (
	vlcVideoCodecs = []struct {
		patterns []string
		codec    string
	}{
		{[]string{"avc", "h.264", "type=0x1b"}, "h264"},
		{[]string{"hevc", "h.265", "type=0x24"}, "hevc"},
		{[]string{"mpeg-2", "type=0x02"}, "mpeg2video"},
		{[]string{"mpeg-4", "type=0x10"}, "mpeg4"},
	}
	vlcAudioCodecs = []struct {
		patterns []string
		codec    string
	}{
		{[]string{"type=0xf", "adts"}, "aac"},
		{[]string{"type=0x03", "type=0x04"}, "mp3"},
		{[]string{"type=0x06", "type=0x81"}, "ac3"},
		{[]string{"type=0x0b", "lpcm"}, "pcm"},
	}
	vlcFPSFractionRe  = regexp.MustCompile(`source fps\s+(\d+)/(\d+)`)
	vlcSourceResRe    = regexp.MustCompile(`source\s+(\d{3,4})x(\d{3,4})`)
	vlcResolutionRe   = regexp.MustCompile(`(\d{3,4})x(\d{3,4})`)
	vlcFPSRe          = regexp.MustCompile(`(\d+\.?\d*)\s*fps`)
	vlcChannelsRe     = regexp.MustCompile(`channels:\s*(\d+)`)
	vlcSampleRateRe   = regexp.MustCompile(`samplerate:\s*(\d+)`)
	vlcHzRe           = regexp.MustCompile(`(\d+)\s*hz`)
	vlcChannelWordsRe = regexp.MustCompile(`\b(mono|stereo|5\.1|7\.1|quad|2\.1)\b`)
)

func vlcVideo(line string) (Info, bool) {
	lower := strings.ToLower(line)
	var info Info
	set := false
	for _, entry := range vlcVideoCodecs {
		if containsAny(lower, entry.patterns) {
			info.VideoCodec = ptr(entry.codec)
			set = true
			break
		}
	}
	if m := vlcFPSFractionRe.FindStringSubmatch(lower); m != nil {
		num, _ := strconv.Atoi(m[1])
		den, _ := strconv.Atoi(m[2])
		if den > 0 {
			info.SourceFPS = ptr(float64(num) / float64(den))
			set = true
		}
	}
	if m := vlcSourceResRe.FindStringSubmatch(lower); m != nil {
		w, _ := strconv.Atoi(m[1])
		h, _ := strconv.Atoi(m[2])
		if resolutionWithin(w, h) {
			info.Resolution = ptr(m[1] + "x" + m[2])
			info.Width, info.Height = ptr(w), ptr(h)
			set = true
		}
	} else if m := vlcResolutionRe.FindStringSubmatch(line); m != nil {
		// The fallback runs against the ORIGINAL line, log_parsers.py:216.
		w, _ := strconv.Atoi(m[1])
		h, _ := strconv.Atoi(m[2])
		if resolutionWithin(w, h) {
			info.Resolution = ptr(m[1] + "x" + m[2])
			info.Width, info.Height = ptr(w), ptr(h)
			set = true
		}
	}
	if info.SourceFPS == nil {
		if m := vlcFPSRe.FindStringSubmatch(lower); m != nil {
			// "25." parses as 25 in both languages; a bare "." does not
			// parse in either and Python's except drops the whole line.
			fps, err := strconv.ParseFloat(m[1], 64)
			if err != nil {
				return Info{}, false
			}
			info.SourceFPS = ptr(fps)
			set = true
		}
	}
	return info, set
}

func vlcAudio(line string) (Info, bool) {
	lower := strings.ToLower(line)
	var info Info
	set := false
	for _, entry := range vlcAudioCodecs {
		if containsAny(lower, entry.patterns) {
			info.AudioCodec = ptr(entry.codec)
			set = true
			break
		}
	}
	if strings.Contains(lower, "channels:") {
		if m := vlcChannelsRe.FindStringSubmatch(lower); m != nil {
			n, _ := strconv.Atoi(m[1])
			name, known := map[int]string{1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}[n]
			if !known {
				name = strconv.Itoa(n)
			}
			info.AudioChannels = ptr(name)
			set = true
		}
	}
	if strings.Contains(lower, "samplerate:") {
		if m := vlcSampleRateRe.FindStringSubmatch(lower); m != nil {
			hz, _ := strconv.Atoi(m[1])
			info.SampleRate = ptr(hz)
			set = true
		}
	}
	if m := vlcHzRe.FindStringSubmatch(lower); m != nil && info.SampleRate == nil {
		hz, _ := strconv.Atoi(m[1])
		info.SampleRate = ptr(hz)
		set = true
	}
	if info.AudioChannels == nil {
		if m := vlcChannelWordsRe.FindStringSubmatch(lower); m != nil {
			info.AudioChannels = ptr(m[1])
			set = true
		}
	}
	return info, set
}

var streamlinkQualityRe = regexp.MustCompile(`(\d+p|\d+x\d+)`)

// streamlinkResolutions is log_parsers.py:335-341's table, and its default
// -- 1920x1080 for any quality not listed, "160p" included -- is the Python
// behaviour, reproduced rather than corrected.
var streamlinkResolutions = map[string][3]int{
	"2160p": {3840, 2160},
	"1080p": {1920, 1080},
	"720p":  {1280, 720},
	"480p":  {854, 480},
	"360p":  {640, 360},
}

func streamlinkVideo(line string) (Info, bool) {
	m := streamlinkQualityRe.FindStringSubmatch(line)
	if m == nil {
		return Info{}, false
	}
	quality := m[1]
	var w, h int
	var resolution string
	if strings.Contains(quality, "x") {
		resolution = quality
		ws, hs, _ := strings.Cut(quality, "x")
		w, _ = strconv.Atoi(ws)
		h, _ = strconv.Atoi(hs)
	} else {
		dims, known := streamlinkResolutions[quality]
		if !known {
			dims = [3]int{1920, 1080}
		}
		w, h = dims[0], dims[1]
		resolution = strconv.Itoa(w) + "x" + strconv.Itoa(h)
	}
	return Info{
		VideoCodec:  ptr("h264"),
		Resolution:  ptr(resolution),
		Width:       ptr(w),
		Height:      ptr(h),
		PixelFormat: ptr("yuv420p"),
	}, true
}

func containsAny(s string, patterns []string) bool {
	for _, p := range patterns {
		if strings.Contains(s, p) {
			return true
		}
	}
	return false
}

func ptr[T any](v T) *T { return &v }
