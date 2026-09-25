package httpapi

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// OwnerUnknown is the detail endpoint's owner default: the literal string
// channel_status.py:45 substitutes when the metadata hash carries no owner
// field, where the LIST endpoint's builder passes None through
// (channel_status.py:474). That asymmetry is parity-matrix row 14 and it is
// carried, not fixed -- spec D5, and CLAUDE.md § Observing a channel records
// it as a field that misleads.
//
// With one relay process and no election there is never an owner to name, so
// this is what every channel reports here, exactly as `owner: null` is what
// every channel reports on the list.
const OwnerUnknown = "unknown"

// WorkerUnknown is the same default one level down: a detail client row's
// worker_id, which channel_status.py:181 fills with 'unknown' when the client
// hash has none. D2 deletes the worker concept outright, so it is what every
// client reports here.
const WorkerUnknown = "unknown"

// detailBufferSample is how many recent chunks the buffer-health walk looks
// at: `min(5, buffer_index)` at channel_status.py:237.
const detailBufferSample = 5

// detailClientPayload is one row of get_detailed_channel_info's clients list,
// field for field and IN DECLARATION ORDER with
// apps/proxy/relay_serializers.py's RelayDetailClientSerializer.
//
// THE FIRST SEVEN ARE ALWAYS PRESENT because channel_status.py:178-191
// assigns each with a fallback default; the last six are conditional on a key
// being in the client's hash, and WHICH of them can be is a property of the
// output format (clientstats.go). connected_at and last_active are always
// present here because client_manager.py:237-239 seeds both at registration,
// so their `if ... in client_data` guards cannot miss in a real deployment.
type detailClientPayload struct {
	ClientID        string   `json:"client_id"`
	UserAgent       string   `json:"user_agent"`
	WorkerID        string   `json:"worker_id"`
	IPAddress       string   `json:"ip_address"`
	UserID          string   `json:"user_id"`
	OutputFormat    string   `json:"output_format"`
	OutputProfileID *int     `json:"output_profile_id"`
	ConnectedAt     float64  `json:"connected_at"`
	LastActive      float64  `json:"last_active"`
	LastActiveAgo   float64  `json:"last_active_ago"`
	BytesSent       *int64   `json:"bytes_sent,omitempty"`
	AvgRateKBps     *float64 `json:"avg_rate_KBps,omitempty"`
	CurrentRateKBps *float64 `json:"current_rate_KBps,omitempty"`
}

// bufferStatsPayload is get_detailed_channel_info's buffer_stats
// (channel_status.py:229-312), which the serializer declares as a free-form
// DictField "because buffer_stats carries a diagnostics sub-dict whose keys
// depend on which Redis probe found something, and pinning it would turn a
// diagnostic into a contract".
//
// FOUR KEYS PYTHON EMITS ARE NOT HERE, and each is a Redis fact rather than a
// buffer fact, so emitting one would mean inventing a number:
//
//	latest_chunk_ttl              a TTL on a chunk key (:308-310). This ring
//	                              bounds itself by byte budget AND age (D2),
//	                              and reporting the age bound as a TTL would
//	                              name a mechanism that is not the one doing
//	                              the work.
//	diagnostics.all_buffer_keys   a SCAN of live:channel:*:input:buffer:chunk:*
//	diagnostics.total_buffer_keys (:286-300), reached only when no sampled
//	                              chunk was found -- a debugging aid for keys
//	                              that have expired out from under the index,
//	                              which cannot happen to a slice.
//	error / diagnostics.exception the Redis walk's own except arm (:302-305).
//
// keys_missing keeps its meaning and changes its cause: there, a chunk key
// that expired; here, one evicted by the byte budget or the retention bound.
type bufferStatsPayload struct {
	Chunks           uint64         `json:"chunks"`
	Diagnostics      map[string]any `json:"diagnostics"`
	AvgChunkSize     *float64       `json:"avg_chunk_size,omitempty"`
	RecentChunkSizes []int          `json:"recent_chunk_sizes,omitempty"`
	KeysFound        []uint64       `json:"keys_found,omitempty"`
	// A POINTER, alone among the four slice fields, because it is the only
	// one that can legitimately be EMPTY: channel_status.py:275 assigns
	// keys_missing inside the same `if chunk_sizes:` arm as keys_found, so a
	// fully resident sample renders "keys_missing": [] rather than omitting
	// the key. `[]uint64` with omitempty would drop it, and without
	// omitempty a nil would render null in the arm where Python omits it
	// entirely.
	KeysMissing      *[]uint64 `json:"keys_missing,omitempty"`
	TotalSampleBytes *int      `json:"total_sample_bytes,omitempty"`
	EstimatedPackets *int      `json:"estimated_ts_packets,omitempty"`
	IsTSAligned      *bool     `json:"is_ts_aligned,omitempty"`
}

// localManagerPayload is channel_status.py:315-322's local_manager: the four
// StreamManager fields only the process holding the manager can answer.
// Always present here, where Python omits the block on a worker that is not
// the owner -- with one process there is no non-owning worker to be.
type localManagerPayload struct {
	Healthy      bool    `json:"healthy"`
	Connected    bool    `json:"connected"`
	LastDataTime float64 `json:"last_data_time"`
	LastDataAge  float64 `json:"last_data_age"`
}

// detailPayload is get_detailed_channel_info, field for field and in
// RelayChannelDetailSerializer's declaration order.
//
// ffmpeg_bitrate IS THE OUTPUT BITRATE THE STDERR READER PARSES, which is
// issue #314's fix. In the Python relay it was read under one constant
// ("ffmpeg_bitrate", channel_status.py:404) and written under another
// ("ffmpeg_output_bitrate", input/manager.py:1269), so it never reached this
// payload; the Go relay held the value in channel.Stats and dropped it here.
// source_bitrate, which the serializer also declared and nothing in either
// relay ever wrote, was removed from the serializer by the same fix.
type detailPayload struct {
	ChannelID      string                `json:"channel_id"`
	State          *string               `json:"state"`
	URL            string                `json:"url"`
	StreamProfile  string                `json:"stream_profile"`
	StartedAt      float64               `json:"started_at"`
	Owner          string                `json:"owner"`
	BufferIndex    uint64                `json:"buffer_index"`
	ChannelName    string                `json:"channel_name,omitempty"`
	StreamID       *int                  `json:"stream_id,omitempty"`
	StreamName     string                `json:"stream_name,omitempty"`
	M3UProfileID   *int                  `json:"m3u_profile_id,omitempty"`
	M3UProfileName string                `json:"m3u_profile_name,omitempty"`
	StateChangedAt float64               `json:"state_changed_at"`
	StateDuration  float64               `json:"state_duration"`
	Uptime         float64               `json:"uptime"`
	TotalBytes     *uint64               `json:"total_bytes,omitempty"`
	TotalData      string                `json:"total_data,omitempty"`
	AvgBitrateKbps *float64              `json:"avg_bitrate_kbps,omitempty"`
	AvgBitrate     string                `json:"avg_bitrate,omitempty"`
	ClientCount    int                   `json:"client_count"`
	BufferStats    bufferStatsPayload    `json:"buffer_stats"`
	LocalManager   localManagerPayload   `json:"local_manager"`
	VideoCodec     string                `json:"video_codec,omitempty"`
	Resolution     string                `json:"resolution,omitempty"`
	Width          string                `json:"width,omitempty"`
	Height         string                `json:"height,omitempty"`
	VideoBitrate   string                `json:"video_bitrate,omitempty"`
	SourceFPS      string                `json:"source_fps,omitempty"`
	PixelFormat    string                `json:"pixel_format,omitempty"`
	AudioCodec     string                `json:"audio_codec,omitempty"`
	SampleRate     string                `json:"sample_rate,omitempty"`
	AudioChannels  string                `json:"audio_channels,omitempty"`
	AudioBitrate   string                `json:"audio_bitrate,omitempty"`
	FFmpegSpeed    *float64              `json:"ffmpeg_speed,omitempty"`
	FFmpegFPS      string                `json:"ffmpeg_fps,omitempty"`
	ActualFPS      string                `json:"actual_fps,omitempty"`
	FFmpegBitrate  string                `json:"ffmpeg_bitrate,omitempty"`
	StreamType     string                `json:"stream_type,omitempty"`
	Clients        []detailClientPayload `json:"clients"`
}

// statePayload is RelayChannelStateSerializer: the two-field answer to
// ?fields=state, and the body of every 404 from this route.
//
// Its own type rather than a partial detailPayload, for the reason that
// serializer's own docstring gives: DRF renders a missing key as null on a
// field that is allow_null, so a partial render of the detail shape would put
// "url": null, "stream_profile": null and "owner": null into an answer that
// knows none of them.
type statePayload struct {
	ChannelID string  `json:"channel_id"`
	State     *string `json:"state"`
}

// ChannelHandler serves GET and DELETE on /proxy/relay/channels/{channelID}.
//
// GET is what relay_client.get_channel calls, and through it
// /proxy/ts/status/<id>, next_stream's "what is playing now" read, the DVR's
// recording-metadata capture and its client sweep. With ?fields=state it is
// the tune path's own read (relay_client.channel_snapshot), under a two-second
// budget, which is why that branch answers from two in-memory fields rather
// than building the whole payload.
//
// DELETE is relay_client.stop_channel, wrapped by /proxy/ts/stop/<id>.
func ChannelHandler(deps ControlDeps) http.HandlerFunc {
	log := controlLog(deps)
	now := controlClock(deps)

	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("channelID")
		if r.Method == http.MethodDelete {
			writeJSON(w, log, stopResponse(deps.Channels, id))
			return
		}

		ch := deps.Channels.Get(id)
		if r.URL.Query().Get("fields") == "state" {
			if ch == nil {
				writeJSONStatus(w, log, http.StatusNotFound, statePayload{ChannelID: id})
				return
			}
			state := string(ch.State())
			writeJSON(w, log, statePayload{ChannelID: id, State: &state})
			return
		}
		if ch == nil {
			// get_detailed_channel_info returns None for a channel this relay
			// holds no metadata hash for, and relay_views.py:180-194 answers
			// 404 with the narrow serializer's shape. A 404 here is an
			// ANSWER -- "this channel is not running" -- which
			// relay_client.get_channel maps to None; every other refusal
			// propagates.
			writeJSONStatus(w, log, http.StatusNotFound, statePayload{ChannelID: id})
			return
		}
		writeJSON(w, log, describeChannelDetail(ch, now()))
	}
}

// describeChannelDetail renders one channel the way get_detailed_channel_info
// does.
func describeChannelDetail(c *channel.Channel, at time.Time) detailPayload {
	state := string(c.State())
	info := c.Source()
	uptime := at.Sub(c.StartedAt()).Seconds()

	out := detailPayload{
		ChannelID:     c.ID(),
		State:         &state,
		URL:           info.URL,
		StreamProfile: strconv.Itoa(info.StreamProfileID),
		StartedAt:     unixFloat(c.StartedAt()),
		// :45's literal default, and row 14's asymmetry with the list
		// endpoint's null.
		Owner:       OwnerUnknown,
		BufferIndex: c.Ring().Head(),
		ChannelName: info.ChannelName,
		StreamName:  info.StreamName,
		// :126-127 and :133, both unconditional here: Python guards each on
		// its metadata key being present, and both keys are written at
		// channel init, so neither guard can miss on a running channel.
		StateChangedAt: unixFloat(c.StateChangedAt()),
		StateDuration:  at.Sub(c.StateChangedAt()).Seconds(),
		Uptime:         uptime,
	}
	if info.M3UProfileID != 0 {
		id := info.M3UProfileID
		out.M3UProfileID = &id
		out.M3UProfileName = info.M3UProfileName
	}
	if info.StreamID != 0 {
		id := info.StreamID
		out.StreamID = &id
	}

	// :138-160: the byte total, its human-readable form, and the average
	// bitrate only once uptime is positive.
	if total := c.Ring().TotalBytes(); total > 0 {
		out.TotalBytes = &total
		out.TotalData = humanBytes(total)
		if uptime > 0 {
			kbps := float64(total) * 8 / uptime / 1000
			out.AvgBitrateKbps = &kbps
			if kbps > 1000 {
				out.AvgBitrate = fmt.Sprintf("%.2f Mbps", kbps/1000)
			} else {
				out.AvgBitrate = fmt.Sprintf("%.2f Kbps", kbps)
			}
		}
	}

	clients := c.ClientSnapshot()
	out.ClientCount = len(clients)
	out.Clients = make([]detailClientPayload, 0, len(clients))
	for _, cl := range clients {
		out.Clients = append(out.Clients, describeDetailClient(cl, at))
	}

	out.BufferStats = describeBufferStats(c.Ring())
	local := c.Local()
	out.LocalManager = localManagerPayload{
		Healthy:      local.Healthy,
		Connected:    local.Connected,
		LastDataTime: unixFloat(local.LastData),
		LastDataAge:  at.Sub(local.LastData).Seconds(),
	}

	// The stream-info and ffmpeg-performance fields, each only when the
	// reader set it (:325-410), and each spelled the way Python spells it in
	// the hash: str(round(x, n)) for a float, str(x) for an int.
	stats := c.Stats()
	if stats.VideoCodec != nil {
		out.VideoCodec = *stats.VideoCodec
	}
	if stats.Resolution != nil {
		out.Resolution = *stats.Resolution
	}
	if stats.Width != nil {
		out.Width = strconv.Itoa(*stats.Width)
	}
	if stats.Height != nil {
		out.Height = strconv.Itoa(*stats.Height)
	}
	if stats.VideoBitrate != nil {
		out.VideoBitrate = pythonFloat(*stats.VideoBitrate)
	}
	if stats.SourceFPS != nil {
		// A STRING here and a float on the list endpoint: row 14's third
		// clause, carried rather than fixed.
		out.SourceFPS = pythonFloat(*stats.SourceFPS)
	}
	if stats.PixelFormat != nil {
		out.PixelFormat = *stats.PixelFormat
	}
	if stats.AudioCodec != nil {
		out.AudioCodec = *stats.AudioCodec
	}
	if stats.SampleRate != nil {
		out.SampleRate = strconv.Itoa(*stats.SampleRate)
	}
	if stats.AudioChannels != nil {
		out.AudioChannels = *stats.AudioChannels
	}
	if stats.AudioBitrate != nil {
		out.AudioBitrate = pythonFloat(*stats.AudioBitrate)
	}
	// ffmpeg_speed is the one performance field the detail endpoint renders
	// as a FLOAT (:387-394's float() with its own except arm), and it agrees
	// with the list endpoint -- row 14's second clause, fixed by Phase 1 PR 7
	// and held fixed here.
	out.FFmpegSpeed = stats.FFmpegSpeed
	if stats.FFmpegFPS != nil {
		out.FFmpegFPS = pythonFloat(*stats.FFmpegFPS)
	}
	if stats.ActualFPS != nil {
		out.ActualFPS = pythonFloat(*stats.ActualFPS)
	}
	if stats.FFmpegOutputBitrate != nil {
		out.FFmpegBitrate = pythonFloat(*stats.FFmpegOutputBitrate)
	}
	if stats.StreamType != nil {
		out.StreamType = *stats.StreamType
	}
	return out
}

// describeDetailClient renders one client row.
func describeDetailClient(cl channel.Client, at time.Time) detailClientPayload {
	stats := cl.Stats(at)
	row := detailClientPayload{
		ClientID:        cl.ID,
		UserAgent:       cl.UserAgent,
		WorkerID:        WorkerUnknown,
		IPAddress:       cl.IPAddress,
		UserID:          cl.UserID,
		OutputFormat:    cl.OutputFormat,
		OutputProfileID: cl.OutputProfileID,
		ConnectedAt:     unixFloat(cl.ConnectedAt),
		LastActive:      unixFloat(stats.LastActive),
		LastActiveAgo:   at.Sub(stats.LastActive).Seconds(),
	}
	// :202-213's three guards, all on a key the TS generator writes and the
	// fMP4 generator does not. Sends is what makes the absence a mechanism:
	// a client that has received no chunk has no counter, and an fMP4 client
	// never gets one however much it receives.
	if stats.Sends > 0 {
		bytesSent := stats.BytesSent
		avg := stats.AvgRateKBps
		current := stats.CurrentRateKBps
		row.BytesSent = &bytesSent
		row.AvgRateKBps = &avg
		row.CurrentRateKBps = &current
	}
	return row
}

// describeBufferStats is the buffer-health walk (channel_status.py:228-312)
// over the in-memory ring.
func describeBufferStats(ring *buffer.Ring) bufferStatsPayload {
	head := ring.Head()
	out := bufferStatsPayload{Chunks: head, Diagnostics: map[string]any{}}
	if head == 0 {
		// :235's `if info['buffer_index'] > 0`: nothing sampled, and the
		// diagnostics stay the empty dict :231 seeded.
		return out
	}

	sample := ring.Sample(detailBufferSample)
	// The index range Python walks: [head-min(5,head)+1, head] (:237, :243).
	want := uint64(detailBufferSample)
	if head < want {
		want = head
	}
	resident := map[uint64]bool{}
	sizes := make([]int, 0, len(sample))
	found := make([]uint64, 0, len(sample))
	total := 0
	aligned := true
	// NO INDEX FILTER HERE, and its absence is deliberate rather than an
	// omission: Ring.Sample(n) already returns at most n chunks and always
	// the newest ones, so every chunk it hands back is inside the window
	// [head-want+1, head] by construction. A guard for the other case was
	// written first and break-check 3b showed it could not be reached --
	// dead code a test cannot pin, so it is gone rather than kept.
	for _, chunk := range sample {
		resident[chunk.Index] = true
		sizes = append(sizes, chunk.Size)
		found = append(found, chunk.Index)
		total += chunk.Size
		if chunk.Size%buffer.TSPacketSize != 0 {
			aligned = false
		}
		if len(found) == 1 {
			// :258-266's first_chunk block, for the first chunk FOUND rather
			// than the first walked -- `if len(chunk_keys_found) == 1`.
			out.Diagnostics["first_chunk"] = map[string]any{
				"index":      chunk.Index,
				"size":       chunk.Size,
				"ts_packets": chunk.Size / buffer.TSPacketSize,
				"aligned":    chunk.Size%buffer.TSPacketSize == 0,
				"first_byte": chunk.FirstByte,
			}
		}
	}
	missing := make([]uint64, 0, want)
	for i := head - want + 1; i <= head; i++ {
		if !resident[i] {
			missing = append(missing, i)
		}
	}
	if len(sizes) == 0 {
		// :285-300's else arm is a Redis key scan with no analogue, and it
		// sets NEITHER keys_found NOR keys_missing -- both live inside the
		// `if chunk_sizes:` arm above it -- so the walk reports what it
		// found: nothing.
		return out
	}
	avg := float64(total) / float64(len(sizes))
	packets := total / buffer.TSPacketSize
	out.AvgChunkSize = &avg
	out.RecentChunkSizes = sizes
	out.KeysFound = found
	out.KeysMissing = &missing
	out.TotalSampleBytes = &total
	out.EstimatedPackets = &packets
	out.IsTSAligned = &aligned
	return out
}

// humanBytes is channel_status.py:141-149's total_data: bytes below 1 KiB,
// then KB, MB and GB to two decimal places, each over the 1024 boundary and
// each with Python's own unit spelling.
func humanBytes(total uint64) string {
	switch {
	case total < 1024:
		return fmt.Sprintf("%d B", total)
	case total < 1024*1024:
		return fmt.Sprintf("%.2f KB", float64(total)/1024)
	case total < 1024*1024*1024:
		return fmt.Sprintf("%.2f MB", float64(total)/(1024*1024))
	default:
		return fmt.Sprintf("%.2f GB", float64(total)/(1024*1024*1024))
	}
}

// unixFloat is the seconds-since-epoch float every timestamp on these
// payloads is: Python stores str(time.time()) and reads it back with float().
func unixFloat(t time.Time) float64 {
	if t.IsZero() {
		return 0
	}
	return float64(t.UnixNano()) / float64(time.Second)
}

// pythonFloat is str(round(x, n)) for the fields the detail endpoint renders
// as STRINGS because Python passes the hash's raw bytes through.
//
// The rounding is already done -- channel.Stats stores each value rounded the
// way its writer rounds it -- so this is only the str() half, and the one
// thing it has to get right is that PYTHON'S FLOAT REPR ALWAYS CARRIES A
// DECIMAL POINT: str(25.0) is "25.0", where Go's shortest form is "25". A
// status payload reporting a source_fps of "25" where the Python relay
// reports "25.0" is a wire difference on a field parity-matrix row 14 is
// about.
//
// The exponent forms Python switches to (1e+16 and below 1e-4) are out of
// range for every field here -- a frame rate, a sample rate and three
// bitrates in kbps -- and are not reproduced.
func pythonFloat(v float64) string {
	s := strconv.FormatFloat(v, 'f', -1, 64)
	if strings.ContainsRune(s, '.') {
		return s
	}
	return s + ".0"
}
