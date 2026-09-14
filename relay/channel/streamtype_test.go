package channel

import "testing"

// detect_stream_type's five answers, from its own branches
// (apps/proxy/live_proxy/utils.py:31-69), plus the one that reads the path
// and not the query.
func TestStreamTypeOfMatchesDetectStreamType(t *testing.T) {
	for url, want := range map[string]string{
		"":                                      "unknown",
		"udp://239.0.0.1:1234":                  "udp",
		"UDP://239.0.0.1:1234":                  "udp",
		"rtsp://cam.example/live":               "rtsp",
		"rtp://cam.example/live":                "rtsp",
		"http://p/live/u/p/1.m3u8":              "hls",
		"http://p/live/u/p/1.M3U8?token=x":      "hls",
		"http://p/playlist.m3u":                 "hls",
		"http://p/hls/manifest.m3u8":            "hls",
		"http://p/hls/master.m3u":               "hls",
		"http://p/x?redirect=master.m3u8":       "hls", // endswith('.m3u8') runs over the WHOLE url, query included (utils.py:55)
		"http://p/x?redirect=master.m3u8&a=1":   "ts",  // ...but the path-word patterns read the PATH alone (utils.py:61-66)
		"http://p/live/u/p/1.ts":                "ts",
		"http://p/live/u/p/1":                   "ts",
		"http://p/playlist":                     "ts", // "playlist" without .m3u is not HLS
		"http://p/live/manifest.mpd":            "ts", // DASH is not detected; Python answers ts
		"http://user:pw@p/live/u/p/stream.m3u8": "hls",
	} {
		if got := StreamTypeOf(url); got != want {
			t.Errorf("StreamTypeOf(%q) = %q, want %q", url, got, want)
		}
	}
	if NeedsFFmpeg("http://p/1.ts") || !NeedsFFmpeg("http://p/1.m3u8") || !NeedsFFmpeg("udp://x") || !NeedsFFmpeg("rtsp://x") {
		t.Fatal("NeedsFFmpeg does not follow input/manager.py:445's (HLS, RTSP, UDP) tuple")
	}
}
