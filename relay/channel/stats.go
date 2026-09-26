package channel

import (
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
)

// Stats is the stream information a transcode process has told this
// channel: the in-memory equivalent of the metadata hash's stream-info
// fields (ChannelMetadataField.VIDEO_CODEC ... STREAM_TYPE, written by
// channel_service.py:844-880 -- these survive as ChannelMetadataField names
// because apps/timeshift/stats.py and apps/channels/tasks.py's recording
// capture still read them) and its ffmpeg-performance fields -- the deleted
// Python relay's "ffmpeg_speed", "ffmpeg_fps", "actual_fps",
// "ffmpeg_output_bitrate" and "ffmpeg_stats_updated" metadata-hash keys,
// five in all, written together by input/manager.py:1250-1275. #461
// deleted those five, plus "ffmpeg_bitrate" (a sixth ffmpeg-performance
// name, not written by that range), from ChannelMetadataField since
// nothing reads any of them any more; only the first four exist as this
// struct's fields below -- "ffmpeg_stats_updated" and "ffmpeg_bitrate"
// were never struct fields at all.
//
// A nil pointer is a field the hash never had, which the status endpoints
// render by OMITTING the key (channel_status.py:605-627 assigns each only
// inside an `if`). The Proxy architecture spawns nothing and so never sets
// any of them -- parity-matrix row 29.
//
// EVERY VALUE IS ROUNDED THE WAY PYTHON STORES IT, at the moment it is
// applied: Python writes str(round(x, n)) into the hash and reads the string
// back as a float, so the rounded value is what the wire carries.
type Stats struct {
	VideoCodec    *string
	Resolution    *string
	Width         *int
	Height        *int
	SourceFPS     *float64 // round(fps, 2), channel_service.py:858
	PixelFormat   *string
	VideoBitrate  *float64 // round(kbps, 1), :864
	AudioCodec    *string
	SampleRate    *int
	AudioChannels *string
	AudioBitrate  *float64 // round(kbps, 1), :877
	StreamType    *string  // the probed input format, :879

	FFmpegSpeed         *float64 // round(speed, 3), input/manager.py:1260
	FFmpegFPS           *float64 // round(fps, 1), :1263
	ActualFPS           *float64 // round(fps / speed, 1), :1266
	FFmpegOutputBitrate *float64 // round(kbps, 1), :1269
}

// Stats is a snapshot of what the transcode process has reported so far.
func (c *Channel) Stats() Stats {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.stats
}

// reportInfo merges one parsed stream-info line, with hset semantics: a
// field the line did not carry leaves the earlier value standing.
func (c *Channel) reportInfo(info ffmpeg.Info) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if info.VideoCodec != nil {
		c.stats.VideoCodec = info.VideoCodec
	}
	if info.Resolution != nil {
		c.stats.Resolution = info.Resolution
	}
	if info.Width != nil {
		c.stats.Width = info.Width
	}
	if info.Height != nil {
		c.stats.Height = info.Height
	}
	if info.SourceFPS != nil {
		c.stats.SourceFPS = rounded(*info.SourceFPS, 2)
	}
	if info.PixelFormat != nil {
		c.stats.PixelFormat = info.PixelFormat
	}
	if info.VideoBitrate != nil {
		c.stats.VideoBitrate = rounded(*info.VideoBitrate, 1)
	}
	if info.AudioCodec != nil {
		c.stats.AudioCodec = info.AudioCodec
	}
	if info.SampleRate != nil {
		c.stats.SampleRate = info.SampleRate
	}
	if info.AudioChannels != nil {
		c.stats.AudioChannels = info.AudioChannels
	}
	if info.AudioBitrate != nil {
		c.stats.AudioBitrate = rounded(*info.AudioBitrate, 1)
	}
	if info.InputFormat != nil {
		c.stats.StreamType = info.InputFormat
	}
}

// reportProgress applies one progress record's four values.
func (c *Channel) reportProgress(p ffmpeg.Progress) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if p.Speed != nil {
		c.stats.FFmpegSpeed = rounded(*p.Speed, 3)
	}
	if p.FPS != nil {
		c.stats.FFmpegFPS = rounded(*p.FPS, 1)
	}
	if p.ActualFPS != nil {
		c.stats.ActualFPS = rounded(*p.ActualFPS, 1)
	}
	if p.OutputBitrateKbps != nil {
		c.stats.FFmpegOutputBitrate = rounded(*p.OutputBitrateKbps, 1)
	}
}

// reportBuffering moves the channel into and out of the buffering state,
// the port of input/manager.py:1232-1234 (hset BUFFERING on a sub-threshold
// sample) and :1244-1247 (hset ACTIVE on recovery).
//
// RECOVERY MOVES TO ACTIVE ONLY FROM BUFFERING. Python's hset is unguarded
// -- it writes ACTIVE whatever the state was -- and promoteOnFirstChunk is
// the one mechanism for waiting_for_clients -> active in this package
// (channel.go), so a second path that could set active from any state would
// be the two-mechanism shape 2c-2's review found and removed. A channel that
// is stopping or has errored stays that way too, on both edges; Python's
// stderr thread can race its own teardown into a stale BUFFERING write,
// and that is a divergence in the safe direction.
func (c *Channel) reportBuffering(on bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	switch {
	case on && (c.state == StateWaitingForClients || c.state == StateActive || c.state == StateInitializing):
		c.state = StateBuffering
	case !on && c.state == StateBuffering:
		c.state = StateActive
	}
}

func rounded(x float64, places int) *float64 {
	v := ffmpeg.Round(x, places)
	return &v
}
