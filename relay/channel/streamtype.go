package channel

import (
	"net/url"
	"strings"
)

// StreamTypeOf classifies an upstream URL the way
// apps/proxy/live_proxy/utils.py:31-69's detect_stream_type does, because
// the answer decides an architecture: a Proxy profile whose URL is HLS, RTSP
// or UDP is played through ffmpeg regardless (input/manager.py:445-453's
// force_ffmpeg), since the raw-HTTP reader cannot follow a playlist or
// speak RTSP.
//
// The five answers are Python's strings: "udp", "rtsp", "hls", "ts" and
// "unknown" for an empty URL. Ported by reading the function, not the
// docstring, which lists four.
func StreamTypeOf(rawURL string) string {
	if rawURL == "" {
		return "unknown"
	}
	lower := strings.ToLower(rawURL)
	if strings.HasPrefix(lower, "udp://") {
		return "udp"
	}
	if strings.HasPrefix(lower, "rtsp://") || strings.HasPrefix(lower, "rtp://") {
		return "rtsp"
	}
	if strings.HasSuffix(lower, ".m3u8") || strings.Contains(lower, ".m3u8?") || strings.Contains(lower, "/playlist.m3u") {
		return "hls"
	}
	// The additional patterns are checked on the PATH alone (utils.py:61-66),
	// so a query string mentioning "manifest" does not count.
	if parsed, err := url.Parse(rawURL); err == nil {
		path := strings.ToLower(parsed.Path)
		m3u := strings.Contains(path, ".m3u") || strings.Contains(path, ".m3u8")
		for _, word := range []string{"playlist", "manifest", "master"} {
			if strings.Contains(path, word) && m3u {
				return "hls"
			}
		}
	}
	return "ts"
}

// NeedsFFmpeg reports whether a URL's stream type forces the transcode path
// on a Proxy profile: input/manager.py:445's (HLS, RTSP, UDP) tuple.
func NeedsFFmpeg(rawURL string) bool {
	switch StreamTypeOf(rawURL) {
	case "hls", "rtsp", "udp":
		return true
	}
	return false
}
