"""Channel state and metadata-field names shared by Django and the relay.

Moved here from ``apps/proxy/live_proxy/constants.py`` in Phase 2 stage 2d-1
(spec Amendment A10.3). ``apps/channels/models.py`` imports
``ChannelMetadataField`` at module level, and the catch-up surface --
``apps/timeshift/views.py`` and ``apps/timeshift/stats.py``, which stage 2d
KEEPS -- imports both names; neither may be left pointing at a directory
stage 2d-4 deletes.

THIS MODULE MUST STAY A LEAF -- no imports, at all, for the reason
``apps/proxy/redis_keys.py``'s docstring gives.

Only the two names surviving code needs are here. ``EventType``,
``StreamType``, ``REDIS_TTL_*``, ``REDIS_KEY_PREFIX`` and the TS packet
constants stay in ``apps/proxy/live_proxy/constants.py``: nothing outside
that package imports them, and 2d-4 deletes them with it.
"""

# Channel states
class ChannelState:
    INITIALIZING = "initializing"
    CONNECTING = "connecting"
    WAITING_FOR_CLIENTS = "waiting_for_clients"
    ACTIVE = "active"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"
    BUFFERING = "buffering"

    # States before a channel is fully active. Used by the stream manager
    # finally block to decide whether a failed stream can write ERROR.
    PRE_ACTIVE = frozenset([INITIALIZING, CONNECTING, BUFFERING, WAITING_FOR_CLIENTS])


# Channel metadata field names stored in Redis
class ChannelMetadataField:
    # Basic fields
    URL = "url"
    USER_AGENT = "user_agent"
    STATE = "state"
    OWNER = "owner"
    STREAM_ID = "stream_id"
    CHANNEL_NAME = "channel_name"
    STREAM_NAME = "stream_name"
    CHANNEL_ID = "channel_id"
    CHANNEL_UUID = "channel_uuid"
    LOGO_ID = "logo_id"

    # Profile fields
    STREAM_PROFILE = "stream_profile"
    M3U_PROFILE = "m3u_profile"
    M3U_PROFILE_NAME = "m3u_profile_name"
    # The locked ffmpeg StreamProfile, JSON-encoded {"id", "command", "args"},
    # written from the next-source answer so input/manager.py's force-ffmpeg
    # path (HLS/RTSP/UDP upstreams) needs no StreamProfile query in the relay
    # process. Phase 2 PR 2b-1.
    FFMPEG_STREAM_PROFILE = "ffmpeg_stream_profile"

    # Status and error fields
    ERROR_MESSAGE = "error_message"
    ERROR_TIME = "error_time"
    STATE_CHANGED_AT = "state_changed_at"
    INIT_TIME = "init_time"
    CONNECTION_READY_TIME = "connection_ready_time"

    # Buffer and data tracking
    BUFFER_CHUNKS = "buffer_chunks"
    TOTAL_BYTES = "total_bytes"

    # Stream switching
    STREAM_SWITCH_TIME = "stream_switch_time"
    STREAM_SWITCH_REASON = "stream_switch_reason"

    # FFmpeg performance metrics
    FFMPEG_SPEED = "ffmpeg_speed"
    FFMPEG_FPS = "ffmpeg_fps"
    ACTUAL_FPS = "actual_fps"
    FFMPEG_OUTPUT_BITRATE = "ffmpeg_output_bitrate"
    FFMPEG_BITRATE = "ffmpeg_bitrate"
    FFMPEG_STATS_UPDATED = "ffmpeg_stats_updated"

    # Video stream info
    VIDEO_CODEC = "video_codec"
    RESOLUTION = "resolution"
    WIDTH = "width"
    HEIGHT = "height"
    SOURCE_FPS = "source_fps"
    PIXEL_FORMAT = "pixel_format"
    VIDEO_BITRATE = "video_bitrate"
    SOURCE_BITRATE = "source_bitrate"

    # Audio stream info
    AUDIO_CODEC = "audio_codec"
    SAMPLE_RATE = "sample_rate"
    AUDIO_CHANNELS = "audio_channels"
    AUDIO_BITRATE = "audio_bitrate"

    # Stream format info
    STREAM_TYPE = "stream_type"
    # Stream info timestamp
    STREAM_INFO_UPDATED = "stream_info_updated"

    # Client metadata fields
    CONNECTED_AT = "connected_at"
    LAST_ACTIVE = "last_active"
    OUTPUT_FORMAT = "output_format"
    BYTES_SENT = "bytes_sent"
    AVG_RATE_KBPS = "avg_rate_KBps"
    CURRENT_RATE_KBPS = "current_rate_KBps"
    IP_ADDRESS = "ip_address"
    WORKER_ID = "worker_id"
    CHUNKS_SENT = "chunks_sent"
    STATS_UPDATED_AT = "stats_updated_at"
