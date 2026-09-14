package ffmpeg

import (
	"reflect"
	"strings"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

func s(v string) *string   { return &v }
func i(v int) *int         { return &v }
func f(v float64) *float64 { return &v }

// A SUPERSET of what the two Python parser test files exercise, as a table:
// apps/proxy/live_proxy/tests/test_property_log_parsers.py (Hypothesis
// round-trips on generated FFmpeg lines, represented by one concrete
// instance each) and test_vlc_streamlink_parsers.py (2b-4's literal cases
// for every named branch of the VLC and Streamlink parsers, one row per
// Python subTest, expected values copied from that file). Every FFmpeg row
// is a REAL line: the first four are taken verbatim from the captured corpus
// (see TestTheCorpusPreambleParsesAsPythonStoresIt for the proof they are).
// directDispatch names the rows whose Python counterpart calls the parse
// method directly rather than through can_parse.
var directDispatch = map[string]bool{
	"vlc alias avc": true, "vlc alias h.264": true, "vlc alias hevc": true, "vlc alias h.265": true,
	"vlc alias mpeg-2": true, "vlc alias mpeg-4": true,
	"vlc audio alias adts": true, "vlc audio alias lpcm": true,
	"vlc audio empty-result exit": true, "vlc word-form channel fallback": true,
}

func TestCanParseAndParseAgreeWithThePythonParsers(t *testing.T) {
	for _, tc := range []struct {
		name string
		tool Tool
		line string
		kind Kind
		want Info
		ok   bool
	}{
		{
			"ffmpeg input line from the corpus", ToolFFmpeg,
			"Input #0, mpegts, from 'http://127.0.0.1:33123/live.ts':",
			KindInput, Info{InputFormat: s("mpegts")}, true,
		},
		{
			"ffmpeg video line from the corpus: no kb/s, so no bitrate", ToolFFmpeg,
			"  Stream #0:0[0x100]: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 320x180 [SAR 1:1 DAR 16:9], 25 fps, 25 tbr, 90k tbn, start 1.423222",
			KindVideo, Info{VideoCodec: s("h264"), Resolution: s("320x180"), Width: i(320), Height: i(180),
				SourceFPS: f(25), PixelFormat: s("yuv420p")}, true,
		},
		{
			"ffmpeg audio line from the corpus", ToolFFmpeg,
			"  Stream #0:1[0x101]: Audio: aac (LC) ([15][0][0][0] / 0x000F), 44100 Hz, mono, fltp, 66 kb/s, start 1.400000",
			KindAudio, Info{AudioCodec: s("aac"), SampleRate: i(44100), AudioChannels: s("mono"), AudioBitrate: f(66)}, true,
		},
		{
			"ffmpeg OUTPUT video line still parses as video: phase tracking is the caller's", ToolFFmpeg,
			"  Stream #0:0: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 320x180 [SAR 1:1 DAR 16:9], q=2-31, 25 fps, 25 tbr, 90k tbn",
			KindVideo, Info{VideoCodec: s("h264"), Resolution: s("320x180"), Width: i(320), Height: i(180),
				SourceFPS: f(25), PixelFormat: s("yuv420p")}, true,
		},
		{
			"the property test's video shape, with a bitrate and a fractional fps", ToolFFmpeg,
			"  Stream #0:0: Video: hevc (High), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 4500 kb/s, 29.97 fps, 90k tbn",
			KindVideo, Info{VideoCodec: s("hevc"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080),
				SourceFPS: f(29.97), PixelFormat: s("yuv420p"), VideoBitrate: f(4500)}, true,
		},
		{
			"a resolution outside 100..10000 is dropped and the codec still parses", ToolFFmpeg,
			"  Stream #0:0: Video: h264 (High), yuv420p, 12000x1080, 25.00 fps",
			KindVideo, Info{VideoCodec: s("h264"), SourceFPS: f(25), PixelFormat: s("yuv420p")}, true,
		},
		{
			"the property test's audio shape", ToolFFmpeg,
			"  Stream #0:1(und): Audio: mp3 (LC), 48000 Hz, stereo, fltp, 128 kb/s",
			KindAudio, Info{AudioCodec: s("mp3"), SampleRate: i(48000), AudioChannels: s("stereo"), AudioBitrate: f(128)}, true,
		},
		{
			"the channel word is matched case-insensitively", ToolFFmpeg,
			"  Stream #0:1: Audio: ac3, 48000 Hz, 5.1(side), fltp, 384 kb/s",
			KindAudio, Info{AudioCodec: s("ac3"), SampleRate: i(48000), AudioChannels: s("5.1"), AudioBitrate: f(384)}, true,
		},
		{
			"a progress record is not a stream line", ToolFFmpeg,
			"frame=  150 fps=0.0 q=-1.0 size=     352KiB time=00:00:05.85 bitrate= 492.2kbits/s speed=11.5x",
			"", Info{}, false,
		},
		{
			"an Input line with nothing after the number parses to nothing", ToolFFmpeg,
			"Input #0", KindInput, Info{}, false,
		},
		{
			"vlc ts demux video by stream type", ToolVLC,
			"[00007f] ts demux debug: pid[0x100] type=0x1b es_id=0x0 -- video",
			KindVLCVideo, Info{VideoCodec: s("h264")}, true,
		},
		{
			"vlc ts demux audio by stream type", ToolVLC,
			"[00007f] ts demux debug: pid[0x101] type=0xf audio",
			KindVLCAudio, Info{AudioCodec: s("aac")}, true,
		},
		{
			"vlc decoder audio format", ToolVLC,
			"[00007f] main decoder debug: AAC channels: 2 samplerate: 48000",
			KindVLCAudio, Info{AudioChannels: s("stereo"), SampleRate: i(48000)}, true,
		},
		{
			"vlc decoder audio with an unnamed channel count is the number as a string", ToolVLC,
			"[00007f] main decoder debug: AAC channels: 3 samplerate: 44100",
			KindVLCAudio, Info{AudioChannels: s("3"), SampleRate: i(44100)}, true,
		},
		{
			"vlc transcode source fps and resolution", ToolVLC,
			"[00007f] stream_out_transcode debug: source fps 30/1, source 1280x720",
			KindVLCVideo, Info{SourceFPS: f(30), Resolution: s("1280x720"), Width: i(1280), Height: i(720)}, true,
		},
		{
			// "avcodec" contains "avc", the first pattern of the h264 tuple
			// (log_parsers.py:200), so a line that names no codec is
			// reported as h264. Verified against the Python parser before
			// this row was written; a port that tokenised would diverge.
			"vlc decoder video: the generic resolution and fps, and the avc-in-avcodec quirk", ToolVLC,
			"[00007f] avcodec decoder debug: using frame size 1920x1080 at 25 fps",
			KindVLCVideo, Info{VideoCodec: s("h264"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080), SourceFPS: f(25)}, true,
		},
		{
			"vlc input failure is recognised and parses to nothing", ToolVLC,
			"[00007f] main input error: unable to open the MRL 'http://x/y'",
			KindVLCInputFailed, Info{}, false,
		},
		{
			"streamlink named quality", ToolStreamlink,
			"[cli][info] Opening stream: 720p (hls)",
			KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("1280x720"), Width: i(1280), Height: i(720), PixelFormat: s("yuv420p")}, true,
		},
		{
			"streamlink explicit resolution", ToolStreamlink,
			"[cli][info] Opening stream: 854x480 (hls)",
			KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("854x480"), Width: i(854), Height: i(480), PixelFormat: s("yuv420p")}, true,
		},
		{
			"streamlink unknown quality DEFAULTS to 1080p -- log_parsers.py:342, reproduced not fixed", ToolStreamlink,
			"[cli][info] Available streams: 160p, 360p, 720p (best)",
			KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080), PixelFormat: s("yuv420p")}, true,
		},
		{
			"an ffmpeg line is not a vlc line", ToolVLC,
			"Input #0, mpegts, from 'http://127.0.0.1:33123/live.ts':",
			"", Info{}, false,
		},
		// The rows below are apps/proxy/live_proxy/tests/test_vlc_streamlink_
		// parsers.py's (2b-4) literal cases, one Go row per Python subTest,
		// every expected value copied from that file and none from this
		// parser. The VLC codec map is four tuples keyed by ALIAS TUPLE, ten
		// aliases against four names, and that file's own reason for one
		// row per alias applies here unchanged: a port transcribing one
		// alias per tuple passes a one-alias-per-row test.
		{"vlc alias avc", ToolVLC, "ts demux debug: pid 256 avc video", KindVLCVideo, Info{VideoCodec: s("h264")}, true},
		{"vlc alias h.264", ToolVLC, "ts demux debug: pid 256 h.264 video", KindVLCVideo, Info{VideoCodec: s("h264")}, true},
		{"vlc alias type=0x1b", ToolVLC, "ts demux debug: pid 256 type=0x1b video", KindVLCVideo, Info{VideoCodec: s("h264")}, true},
		{"vlc alias hevc", ToolVLC, "ts demux debug: pid 256 hevc video", KindVLCVideo, Info{VideoCodec: s("hevc")}, true},
		{"vlc alias h.265", ToolVLC, "ts demux debug: pid 256 h.265 video", KindVLCVideo, Info{VideoCodec: s("hevc")}, true},
		{"vlc alias type=0x24", ToolVLC, "ts demux debug: pid 256 type=0x24 video", KindVLCVideo, Info{VideoCodec: s("hevc")}, true},
		{"vlc alias mpeg-2", ToolVLC, "ts demux debug: pid 256 mpeg-2 video", KindVLCVideo, Info{VideoCodec: s("mpeg2video")}, true},
		{"vlc alias type=0x02", ToolVLC, "ts demux debug: pid 256 type=0x02 video", KindVLCVideo, Info{VideoCodec: s("mpeg2video")}, true},
		{"vlc alias mpeg-4", ToolVLC, "ts demux debug: pid 256 mpeg-4 video", KindVLCVideo, Info{VideoCodec: s("mpeg4")}, true},
		{"vlc alias type=0x10", ToolVLC, "ts demux debug: pid 256 type=0x10 video", KindVLCVideo, Info{VideoCodec: s("mpeg4")}, true},
		{"vlc audio alias type=0xf", ToolVLC, "ts demux debug: pid 257 type=0xf audio", KindVLCAudio, Info{AudioCodec: s("aac")}, true},
		{"vlc audio alias adts", ToolVLC, "ts demux debug: pid 257 adts audio", KindVLCAudio, Info{AudioCodec: s("aac")}, true},
		{"vlc audio alias type=0x03", ToolVLC, "ts demux debug: pid 257 type=0x03 audio", KindVLCAudio, Info{AudioCodec: s("mp3")}, true},
		{"vlc audio alias type=0x04", ToolVLC, "ts demux debug: pid 257 type=0x04 audio", KindVLCAudio, Info{AudioCodec: s("mp3")}, true},
		{"vlc audio alias type=0x06", ToolVLC, "ts demux debug: pid 257 type=0x06 audio", KindVLCAudio, Info{AudioCodec: s("ac3")}, true},
		{"vlc audio alias type=0x81", ToolVLC, "ts demux debug: pid 257 type=0x81 audio", KindVLCAudio, Info{AudioCodec: s("ac3")}, true},
		{"vlc audio alias type=0x0b", ToolVLC, "ts demux debug: pid 257 type=0x0b audio", KindVLCAudio, Info{AudioCodec: s("pcm")}, true},
		{"vlc audio alias lpcm", ToolVLC, "ts demux debug: pid 257 lpcm audio", KindVLCAudio, Info{AudioCodec: s("pcm")}, true},
		{"vlc source fps as a fraction", ToolVLC, "stream_out_transcode debug: source fps 30000/1001", KindVLCVideo, Info{SourceFPS: f(30000.0 / 1001.0)}, true},
		{"vlc source fps with a zero denominator is absent, not zero", ToolVLC, "stream_out_transcode debug: source fps 30/0", KindVLCVideo, Info{}, false},
		{"vlc source wxh", ToolVLC, "stream_out_transcode debug: source 1280x720", KindVLCVideo, Info{Resolution: s("1280x720"), Width: i(1280), Height: i(720)}, true},
		{"vlc source wxh upper bound is reachable only at 9999", ToolVLC, "stream_out_transcode debug: source 9999x9999", KindVLCVideo, Info{Resolution: s("9999x9999"), Width: i(9999), Height: i(9999)}, true},
		{"vlc source wxh below 100 is dropped", ToolVLC, "stream_out_transcode debug: source 0099x0099", KindVLCVideo, Info{}, false},
		// NOT prefixed "avcodec": that substring's "avc" would add the codec
		// key the Python test's expected dict does not carry.
		{"vlc generic resolution fallback with no codec", ToolVLC, "decoder debug: 1920x1080 yuv420p", KindVLCVideo, Info{Resolution: s("1920x1080"), Width: i(1920), Height: i(1080)}, true},
		{"vlc generic resolution below 100 is dropped", ToolVLC, "decoder debug: 099x099", KindVLCVideo, Info{}, false},
		{"vlc generic fps fallback", ToolVLC, "decoder debug: 29.97 fps", KindVLCVideo, Info{SourceFPS: f(29.97)}, true},
		{"vlc source fps wins over a co-occurring generic fps", ToolVLC, "stream_out_transcode debug: source fps 30/1 at 25 fps", KindVLCVideo, Info{SourceFPS: f(30)}, true},
		{"vlc video empty-result exit", ToolVLC, "ts demux debug: pid 256 type=0x99 video", KindVLCVideo, Info{}, false},
		{"vlc channels: 1", ToolVLC, "decoder debug: channels: 1", KindVLCAudio, Info{AudioChannels: s("mono")}, true},
		{"vlc channels: 2", ToolVLC, "decoder debug: channels: 2", KindVLCAudio, Info{AudioChannels: s("stereo")}, true},
		{"vlc channels: 6", ToolVLC, "decoder debug: channels: 6", KindVLCAudio, Info{AudioChannels: s("5.1")}, true},
		{"vlc channels: 8", ToolVLC, "decoder debug: channels: 8", KindVLCAudio, Info{AudioChannels: s("7.1")}, true},
		{"vlc samplerate: field", ToolVLC, "decoder debug: samplerate: 48000", KindVLCAudio, Info{SampleRate: i(48000)}, true},
		{"vlc hz form when samplerate: is absent", ToolVLC, "decoder debug: 44100 hz channels: 2", KindVLCAudio, Info{SampleRate: i(44100), AudioChannels: s("stereo")}, true},
		{"vlc samplerate: wins over a co-occurring hz form", ToolVLC, "decoder debug: samplerate: 48000 at 44100 hz", KindVLCAudio, Info{SampleRate: i(48000)}, true},
		{"vlc channels: count wins over a co-occurring word form", ToolVLC, "decoder debug: channels: 2 mono", KindVLCAudio, Info{AudioChannels: s("stereo")}, true},
		{"vlc word-form channel fallback", ToolVLC, "decoder debug: mono audio", KindVLCAudio, Info{AudioChannels: s("mono")}, true},
		{"vlc audio empty-result exit", ToolVLC, "decoder debug: nothing recognisable here channels", KindVLCAudio, Info{}, false},
		{"streamlink 2160p", ToolStreamlink, "[cli][info] Opening stream: 2160p (hls)", KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("3840x2160"), Width: i(3840), Height: i(2160), PixelFormat: s("yuv420p")}, true},
		{"streamlink 1080p", ToolStreamlink, "[cli][info] Opening stream: 1080p (hls)", KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080), PixelFormat: s("yuv420p")}, true},
		{"streamlink 480p", ToolStreamlink, "[cli][info] Opening stream: 480p (hls)", KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("854x480"), Width: i(854), Height: i(480), PixelFormat: s("yuv420p")}, true},
		{"streamlink 360p", ToolStreamlink, "[cli][info] Opening stream: 360p (hls)", KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("640x360"), Width: i(640), Height: i(360), PixelFormat: s("yuv420p")}, true},
		{"streamlink 144p falls back to 1080p", ToolStreamlink, "[cli][info] Opening stream: 144p", KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080), PixelFormat: s("yuv420p")}, true},
		{"streamlink 1600x900", ToolStreamlink, "[cli][info] Opening stream: 1600x900", KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("1600x900"), Width: i(1600), Height: i(900), PixelFormat: s("yuv420p")}, true},
		{"streamlink no match", ToolStreamlink, "[cli][info] Found matching plugin", "", Info{}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// test_vlc_streamlink_parsers.py drives parse_video_stream and
			// parse_audio_stream DIRECTLY for the rows below, so their lines
			// carry no "type=" and can_parse would not claim them; the kind
			// is the method the Python test called, and CanParse is not
			// asserted. Every other row goes through CanParse first, as
			// _log_stderr_content does.
			if !directDispatch[tc.name] {
				if kind := CanParse(tc.tool, tc.line); kind != tc.kind {
					t.Fatalf("CanParse(%s) = %q, want %q", tc.tool, kind, tc.kind)
				}
			}
			if tc.kind == "" {
				return
			}
			got, ok := Parse(tc.kind, tc.line)
			if ok != tc.ok {
				t.Fatalf("Parse ok = %v, want %v (got %s)", ok, tc.ok, describe(got))
			}
			if ok && !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("Parse =\n  %s\nwant\n  %s", describe(got), describe(tc.want))
			}
		})
	}
}

// ToolFor is the WHOLE command lowercased, not its basename
// (input/manager.py:797-803): "/usr/bin/ffmpeg" is unknown and falls back to
// auto-detection. A port that took the basename would route a line
// differently from Python for every profile whose command is a path.
func TestToolForMatchesTheWholeCommandNotItsBasename(t *testing.T) {
	for cmd, want := range map[string]Tool{"ffmpeg": ToolFFmpeg, "FFmpeg": ToolFFmpeg, "cvlc": ToolVLC, "vlc": ToolVLC, "streamlink": ToolStreamlink} {
		if got, ok := ToolFor(cmd); !ok || got != want {
			t.Errorf("ToolFor(%q) = %q, %v; want %q", cmd, got, ok, want)
		}
	}
	for _, cmd := range []string{"/usr/bin/ffmpeg", "ffmpeg-static", ""} {
		if got, ok := ToolFor(cmd); ok {
			t.Errorf("ToolFor(%q) = %q, want unknown -- Python's map is keyed on the whole string", cmd, got)
		}
	}
}

// AutoParse tries ffmpeg, then vlc, then streamlink (LogParserFactory._parsers'
// insertion order), and reports the FIRST that parses something. The vlc
// input-failure kind is recognised by can_parse but parses to nothing, so
// auto_parse never surfaces it -- which is why the socket-closing branch in
// input/manager.py is reachable only when the command is literally vlc.
func TestAutoParseFollowsTheFactoryOrderAndNeverReportsAVLCInputFailure(t *testing.T) {
	kind, info, ok := AutoParse("  Stream #0:0: Video: h264, yuv420p, 320x180, 25 fps")
	if !ok || kind != KindVideo || info.VideoCodec == nil || *info.VideoCodec != "h264" {
		t.Fatalf("AutoParse(ffmpeg video) = %q, %s, %v", kind, describe(info), ok)
	}
	// A line BOTH the ffmpeg and vlc parsers recognise: "stream #" with
	// "video:" for ffmpeg, "decoder" with "x" for vlc. ffmpeg wins by order.
	kind, _, ok = AutoParse("Stream #0 decoder Video: h264 320x180")
	if !ok || kind != KindVideo {
		t.Fatalf("a line both parsers recognise was reported as %q; the factory tries ffmpeg first", kind)
	}
	if kind, _, ok := AutoParse("[00007f] main input error: unable to open the MRL 'http://x/y'"); ok {
		t.Fatalf("AutoParse reported %q for a VLC input failure; auto_parse returns None for it", kind)
	}
	// test_vlc_streamlink_parsers.py's claimed-but-empty case: a line
	// can_parse CLAIMS (ts demux debug + type= + video) that parses to
	// nothing must be no result, not a result with an empty Info.
	if kind, _, ok := AutoParse("ts demux debug: pid 256 type=0x99 video"); ok {
		t.Fatalf("AutoParse reported %q with an empty Info for a claimed-but-empty line", kind)
	}
	if _, ok := Parse("not_a_stream_type", "x"); ok {
		t.Fatal("Parse of an unknown kind returned a result")
	}
}

// The corpus preamble, driven the way _log_stderr_content drives it: every
// line through the ffmpeg parser, and the union of what parses is exactly
// the stream info Python's status endpoint would carry for this capture.
// Read from the same fixture the Python tests read, never from a copy.
func TestTheCorpusPreambleParsesAsPythonStoresIt(t *testing.T) {
	preamble, _ := relaytest.SplitCorpus(relaytest.Corpus("normal"))
	var merged Info
	parsed := 0
	for _, line := range strings.Split(string(preamble), "\n") {
		kind := CanParse(ToolFFmpeg, strings.TrimSpace(line))
		if kind == "" {
			continue
		}
		info, ok := Parse(kind, strings.TrimSpace(line))
		if !ok {
			continue
		}
		parsed++
		merged = mergeForTest(merged, info)
	}
	if parsed < 3 {
		t.Fatalf("only %d preamble lines parsed; the corpus has an Input line, a video Stream line and an audio Stream line", parsed)
	}
	want := Info{
		InputFormat: s("mpegts"),
		VideoCodec:  s("h264"), Resolution: s("320x180"), Width: i(320), Height: i(180),
		SourceFPS: f(25), PixelFormat: s("yuv420p"),
		AudioCodec: s("aac"), SampleRate: i(44100), AudioChannels: s("mono"), AudioBitrate: f(66),
	}
	if !reflect.DeepEqual(merged, want) {
		t.Fatalf("the merged preamble is\n  %s\nwant\n  %s -- re-derive against the capture (CAPTURE.md) before touching the parser",
			describe(merged), describe(want))
	}
}

// mergeForTest is the hset semantics: a later non-nil field overwrites, a
// nil one leaves the earlier value standing.
func mergeForTest(into, from Info) Info {
	if from.VideoCodec != nil {
		into.VideoCodec = from.VideoCodec
	}
	if from.Resolution != nil {
		into.Resolution = from.Resolution
	}
	if from.Width != nil {
		into.Width = from.Width
	}
	if from.Height != nil {
		into.Height = from.Height
	}
	if from.SourceFPS != nil {
		into.SourceFPS = from.SourceFPS
	}
	if from.PixelFormat != nil {
		into.PixelFormat = from.PixelFormat
	}
	if from.VideoBitrate != nil {
		into.VideoBitrate = from.VideoBitrate
	}
	if from.AudioCodec != nil {
		into.AudioCodec = from.AudioCodec
	}
	if from.SampleRate != nil {
		into.SampleRate = from.SampleRate
	}
	if from.AudioChannels != nil {
		into.AudioChannels = from.AudioChannels
	}
	if from.AudioBitrate != nil {
		into.AudioBitrate = from.AudioBitrate
	}
	if from.InputFormat != nil {
		into.InputFormat = from.InputFormat
	}
	return into
}

func describe(info Info) string {
	var parts []string
	add := func(name string, v any) {
		switch p := v.(type) {
		case *string:
			if p != nil {
				parts = append(parts, name+"="+*p)
			}
		case *int:
			if p != nil {
				parts = append(parts, name+"="+strings.TrimSpace(strings.Repeat(" ", 0)+itoa(*p)))
			}
		case *float64:
			if p != nil {
				parts = append(parts, name+"="+ftoa(*p))
			}
		}
	}
	add("video_codec", info.VideoCodec)
	add("resolution", info.Resolution)
	add("width", info.Width)
	add("height", info.Height)
	add("source_fps", info.SourceFPS)
	add("pixel_format", info.PixelFormat)
	add("video_bitrate", info.VideoBitrate)
	add("audio_codec", info.AudioCodec)
	add("sample_rate", info.SampleRate)
	add("audio_channels", info.AudioChannels)
	add("audio_bitrate", info.AudioBitrate)
	add("stream_type", info.InputFormat)
	if len(parts) == 0 {
		return "{}"
	}
	return "{" + strings.Join(parts, " ") + "}"
}
