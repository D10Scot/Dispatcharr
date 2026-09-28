package hls

import (
	"fmt"
	"strings"
)

// renditionNames is each audio group's NAME. The groups differ by GROUP-ID,
// so two may share a NAME.
var renditionNames = map[string]string{
	RenditionAAC:  "Stereo",
	RenditionAC3:  "Surround",
	RenditionEAC3: "Surround",
}

// Multivariant renders the multivariant playlist (spec § Playlists): one
// EXT-X-MEDIA audio group per declared audio rendition, AAC first, and one
// EXT-X-STREAM-INF per group, each naming the one video media playlist.
// base is the absolute path every URI hangs from -- "/hls/<token>" in 4a-1b
// -- because the multivariant references media playlists by absolute path
// (D3). codecs is each rendition's CODECS value, read from the init
// segments of the first generation that writes a complete set (D7; R41).
//
// BANDWIDTH is the video maxrate plus the group's audio bitrate, and
// AVERAGE-BANDWIDTH the video bitrate plus it: transcode mode's rule. The
// copied-rendition rule (1.25x the ring's measured rate) is automatic
// mode's, and lands with it in 4a-1d.
func Multivariant(o Output, codecs map[string]string, base string) []byte {
	var b strings.Builder
	b.WriteString("#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-INDEPENDENT-SEGMENTS\n")
	for _, r := range o.Audio {
		fmt.Fprintf(&b, "#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=%q,NAME=%q,", r.Name, renditionNames[r.Name])
		if r.Language != "" {
			fmt.Fprintf(&b, "LANGUAGE=%q,", r.Language)
		}
		fmt.Fprintf(&b, "DEFAULT=YES,AUTOSELECT=YES,CHANNELS=\"%d\",URI=\"%s/%s.m3u8\"\n", r.Channels, base, r.Name)
	}
	for _, r := range o.Audio {
		rate := audioBitrate(r)
		fmt.Fprintf(&b, "#EXT-X-STREAM-INF:BANDWIDTH=%d,AVERAGE-BANDWIDTH=%d,CODECS=\"%s,%s\",RESOLUTION=%dx%d,FRAME-RATE=%.3f,AUDIO=%q\n",
			o.VideoMaxrate+rate, o.VideoBitrate+rate, codecs[RenditionVideo], codecs[r.Name],
			o.Width, o.Height, o.FrameRate.Float(), r.Name)
		fmt.Fprintf(&b, "%s/%s.m3u8\n", base, RenditionVideo)
	}
	return []byte(b.String())
}
