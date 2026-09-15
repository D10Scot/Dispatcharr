package httpapi

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
)

// DefaultClientLimit caps the clients list when ?clients=all is absent.
//
// apps/proxy/relay_views.py:57's DEFAULT_CLIENT_LIMIT: what the Stats page and
// /proxy/stats/ have always shown. client_count is NEVER capped
// (channel_status.py:461 is a SCARD), which is what makes ?clients=all
// necessary for relay_client.live_connections and merely cosmetic elsewhere.
const DefaultClientLimit = 10

// ControlDeps is what the internal control routes need.
type ControlDeps struct {
	Secret   string
	Channels *channel.Manager
	Log      *slog.Logger
	Now      func() time.Time
}

// clientPayload is one row of the `clients` list, field for field and IN
// DECLARATION ORDER with apps/proxy/relay_serializers.py's
// RelayChannelClientSerializer, because DRF renders in declaration order and
// so does encoding/json.
//
// PRESENCE IS PER FIELD and is the part that is easy to get wrong. DRF
// declares each of these required=False with NO default=, so
// Field.get_attribute raises SkipField for a key the source dict never set and
// the key vanishes from the JSON entirely rather than rendering as null. Which
// keys ChannelStatus.get_basic_channel_info sets unconditionally and which it
// sets inside an `if` is therefore the contract:
//
//	client_id          always            (:565)
//	user_agent         always, NULLABLE  (:566 -- hmget returns None)
//	output_format      always            (:567, `or 'mpegts'`)
//	output_profile_id  always, NULLABLE  (:579-582, set on BOTH branches)
//	ip_address         only if truthy    (:570-571)
//	connected_at       only if truthy    (:573-574)
//	user_id            only if truthy    (:576-577)
type clientPayload struct {
	ClientID        string  `json:"client_id"`
	UserAgent       *string `json:"user_agent"`
	OutputFormat    string  `json:"output_format"`
	OutputProfileID *int    `json:"output_profile_id"`
	IPAddress       string  `json:"ip_address,omitempty"`
	ConnectedAt     float64 `json:"connected_at,omitempty"`
	UserID          string  `json:"user_id,omitempty"`
}

// channelPayload is get_basic_channel_info, field for field and in
// RelayChannelSerializer's declaration order.
//
// Nine fields are set unconditionally there and are therefore always present
// here: channel_id, state, url, stream_profile, owner, buffer_index,
// client_count, uptime, started_at -- three of them nullable. The rest are
// conditional, hence the pointers and the omitempty.
//
// ONE CONDITIONAL FIELD IS STILL ABSENT after 2c-5, with a reason rather
// than a gap:
//
//	logo_id        NEVER EMITTED BY PYTHON EITHER. ChannelMetadataField.LOGO_ID
//	               is written only into the timeshift key family
//	               (apps/timeshift/views.py:2984), never into the live hash
//	               channel_status.py:486 reads, so the `if not raw: continue`
//	               always continues. Exact parity by doing nothing.
//
// healthy arrived in 2c-5 with the health monitor: channel_status.py:527-529
// sets it only when the answering process holds the channel's StreamManager
// -- which the single relay process always does for a channel in its map --
// so it is present on every channel this relay lists, true from the tune
// until the monitor sees no data for the inactivity threshold.
//
// The seven ffmpeg-derived fields -- video_codec, resolution, source_fps,
// ffmpeg_speed, audio_codec, audio_channels, stream_type -- arrive in 2c-4
// from channel.Stats, each present only when the transcode process reported
// it (channel_status.py:605-627 assigns each inside an `if`), and never on
// the Proxy architecture, which spawns nothing: parity-matrix row 29.
// source_fps is a FLOAT here and a STRING on the detail endpoint, row 14's
// asymmetry, which 2c-8 carries with that endpoint.
type channelPayload struct {
	ChannelID      string   `json:"channel_id"`
	State          *string  `json:"state"`
	URL            string   `json:"url"`
	StreamProfile  string   `json:"stream_profile"`
	Owner          *string  `json:"owner"`
	BufferIndex    uint64   `json:"buffer_index"`
	ClientCount    int      `json:"client_count"`
	Uptime         float64  `json:"uptime"`
	StartedAt      *float64 `json:"started_at"`
	ChannelName    string   `json:"channel_name,omitempty"`
	M3UProfileID   *int     `json:"m3u_profile_id,omitempty"`
	StreamID       *int     `json:"stream_id,omitempty"`
	StreamName     string   `json:"stream_name,omitempty"`
	TotalBytes     *uint64  `json:"total_bytes,omitempty"`
	AvgBitrateKbps *float64 `json:"avg_bitrate_kbps,omitempty"`
	AvgBitrate     string   `json:"avg_bitrate,omitempty"`
	Healthy        *bool    `json:"healthy,omitempty"`
	VideoCodec     string   `json:"video_codec,omitempty"`
	Resolution     string   `json:"resolution,omitempty"`
	SourceFPS      *float64 `json:"source_fps,omitempty"`
	FFmpegSpeed    *float64 `json:"ffmpeg_speed,omitempty"`
	AudioCodec     string   `json:"audio_codec,omitempty"`
	AudioChannels  string   `json:"audio_channels,omitempty"`
	StreamType     string   `json:"stream_type,omitempty"`

	// Clients is ALWAYS PRESENT, never omitted: channel_status.py:587 assigns
	// it on every path, so an empty channel renders "clients": [] and not an
	// absent key. Never nil here for the same reason.
	Clients []clientPayload `json:"clients"`
}

type channelListPayload struct {
	Channels []channelPayload `json:"channels"`
	Count    int              `json:"count"`
}

// ChannelsHandler serves GET /proxy/relay/channels[?clients=all].
//
// The route relay_client.list_channels calls, and through it
// relay_client.live_connections -- which authorize_stream reaches on EVERY
// tune for a stream-limited user (spec D4). Those two read only channel_id and
// the clients list; /proxy/stats/ and the channel_stats WebSocket message read
// the rest.
func ChannelsHandler(deps ControlDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	now := deps.Now
	if now == nil {
		now = time.Now
	}

	return func(w http.ResponseWriter, r *http.Request) {
		limit := DefaultClientLimit
		if r.URL.Query().Get("clients") == "all" {
			limit = -1
		}

		channels := deps.Channels.Snapshot()
		payload := channelListPayload{
			Channels: make([]channelPayload, 0, len(channels)),
			Count:    len(channels),
		}
		for _, c := range channels {
			payload.Channels = append(payload.Channels, describeChannel(c, limit, now()))
		}

		body, err := json.Marshal(payload)
		if err != nil {
			// Unreachable: every field is a plain type. Answering 500 rather
			// than a half-written 200 if it ever happens.
			log.Error("encoding the channel list failed", "error", err) // credential-logging: ok - an encoding/json error over plain struct fields; the URL it could name is one this payload carries on purpose (Ruling R7 of the 2c-3 plan)
			http.Error(w, "internal error", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(body)
	}
}

// describeChannel renders one channel the way get_basic_channel_info does.
func describeChannel(c *channel.Channel, limit int, at time.Time) channelPayload {
	state := string(c.State())
	// OWNER IS ALWAYS NULL, and that is spec D2 rather than a missing value.
	// The metadata hash's owner field is the elected worker id; with one
	// process and no election there is no worker to name, and
	// channel_status.py:474's own default for "nobody owns this" is None. No
	// consumer reads it: grepped across frontend/src (zero hits) and across
	// relay_client's two readers, which take channel_id and clients.
	// Note the ASYMMETRY parity-matrix row 14 pins -- the DETAIL endpoint
	// defaults owner to the literal string 'unknown' -- is 2c-8's to carry.
	var owner *string

	info := c.Source()
	head := c.Ring().Head()
	uptime := at.Sub(c.StartedAt()).Seconds()
	startedAt := float64(c.StartedAt().UnixNano()) / float64(time.Second)

	clients := c.ClientSnapshot()
	out := channelPayload{
		ChannelID:     c.ID(),
		State:         &state,
		URL:           info.URL,
		StreamProfile: strconv.Itoa(info.StreamProfileID),
		Owner:         owner,
		BufferIndex:   head,
		ClientCount:   len(clients),
		Uptime:        uptime,
		StartedAt:     &startedAt,
		ChannelName:   info.ChannelName,
		StreamName:    info.StreamName,
		Clients:       make([]clientPayload, 0, len(clients)),
	}
	if info.M3UProfileID != 0 {
		id := info.M3UProfileID
		out.M3UProfileID = &id
	}
	if info.StreamID != 0 {
		id := info.StreamID
		out.StreamID = &id
	}

	// total_bytes and the two bitrate fields, exactly as channel_status.py
	// :510-524 derives them: the byte counter first, then avg_bitrate_kbps
	// only when uptime is positive, then the display string in Mbps above
	// 1000 Kbps and Kbps at or below it, both to two decimal places.
	if total := c.Ring().TotalBytes(); total > 0 {
		out.TotalBytes = &total
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

	// healthy (:527-529): the health monitor's flag, on every channel this
	// process holds.
	healthy := c.Healthy()
	out.Healthy = &healthy

	// The ffmpeg-derived fields, exactly the seven get_basic_channel_info
	// copies out of the hash (:605-627), each only when the reader set it.
	// A stream_type of "" (channel_service writes str(input_format), never
	// empty) and a codec of "" would be dropped by omitempty where Python's
	// `if video_codec:` drops them too.
	stats := c.Stats()
	if stats.VideoCodec != nil {
		out.VideoCodec = *stats.VideoCodec
	}
	if stats.Resolution != nil {
		out.Resolution = *stats.Resolution
	}
	out.SourceFPS = stats.SourceFPS
	out.FFmpegSpeed = stats.FFmpegSpeed
	if stats.AudioCodec != nil {
		out.AudioCodec = *stats.AudioCodec
	}
	if stats.AudioChannels != nil {
		out.AudioChannels = *stats.AudioChannels
	}
	if stats.StreamType != nil {
		out.StreamType = *stats.StreamType
	}

	for i, cl := range clients {
		if limit >= 0 && i >= limit {
			break
		}
		userAgent := cl.UserAgent
		row := clientPayload{
			ClientID:        cl.ID,
			UserAgent:       &userAgent,
			OutputFormat:    cl.OutputFormat,
			OutputProfileID: cl.OutputProfileID,
			IPAddress:       cl.IPAddress,
			ConnectedAt:     float64(cl.ConnectedAt.UnixNano()) / float64(time.Second),
			UserID:          cl.UserID,
		}
		out.Clients = append(out.Clients, row)
	}
	return out
}

// RequireInternal gates a handler on the two internal headers, the same pair
// apps/proxy/permissions.py's IsInternalRelay checks: the static
// X-Dispatcharr-Internal and the per-request X-Dispatcharr-Internal-Request,
// which binds method, FULL path (query string included), body and a
// 120-second window.
//
// Not IsAdmin and no principal: these hops must not need a resolved User.
// A refusal answers 403 with a fixed body and names nothing.
func RequireInternal(secret string, now func() time.Time, next http.HandlerFunc) http.HandlerFunc {
	if now == nil {
		now = time.Now
	}
	return func(w http.ResponseWriter, r *http.Request) {
		if !control.IsInternalPrincipal(secret, r.Header.Get(control.HeaderInternal)) {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		// The bound token signs r.URL.RequestURI(), which is Django's
		// get_full_path(): the escaped path plus the query string. This route
		// is reached WITH a query string (?clients=all) and without, and the
		// two sign differently -- the correction spec section The contract
		// records, and the reason it is not cosmetic.
		if !control.VerifyInternalRequest(
			secret, r.Header.Get(control.HeaderInternalRequest),
			r.Method, r.URL.RequestURI(), nil, now(),
		) {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next(w, r)
	}
}
