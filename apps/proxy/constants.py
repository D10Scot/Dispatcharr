"""Channel state and metadata-field names shared by Django and the relay.

Moved here from the deleted apps/proxy/live_proxy/constants.py in Phase 2
stage 2d-1 (spec Amendment A10.3). Importers today: apps/proxy/relay_client.py
(ChannelState), apps/timeshift/views.py and apps/timeshift/stats.py
(ChannelMetadataField, and ChannelState in views.py), and
apps/channels/tasks.py function-locally. apps/channels/models.py no longer
imports anything from here: stage 2d-4 deleted its ChannelMetadataField
import with issue #190's five ranges.

THIS MODULE MUST STAY A LEAF -- no imports, at all, for the reason
``apps/proxy/redis_keys.py``'s docstring gives.

Only the two names surviving code needs moved here. The rest of the old
module went with apps/proxy/live_proxy/ at stage 2d-4. #461 trimmed
ChannelMetadataField further, to the 24 names a non-test caller still
reads, the same precedent #407 set for RedisKeys's dead builders.
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


# The catch-up (timeshift) metadata hash's field names -- still a Redis
# hash, written by apps/timeshift/views.py and read by
# apps/timeshift/stats.py -- plus the relay detail payload keys
# apps/channels/tasks.py's recording capture reads by the same names.
# #461 deleted the 29 names with no `ChannelMetadataField.<NAME>`
# reference in CODE anywhere outside this module -- a comment or doc
# mention does not count (a fix round found one: STATE_CHANGED_AT was
# named only in relay/channel/channel.go comments, not read anywhere).
# Every surviving name has a non-test reader in apps/timeshift/stats.py,
# apps/timeshift/views.py or apps/channels/tasks.py.
class ChannelMetadataField:
    # Basic fields
    URL = "url"
    STATE = "state"
    STREAM_ID = "stream_id"
    CHANNEL_NAME = "channel_name"
    STREAM_NAME = "stream_name"
    CHANNEL_ID = "channel_id"
    CHANNEL_UUID = "channel_uuid"
    LOGO_ID = "logo_id"

    # Profile fields
    M3U_PROFILE = "m3u_profile"

    # Status and error fields
    INIT_TIME = "init_time"

    # Buffer and data tracking
    TOTAL_BYTES = "total_bytes"

    # Video stream info
    VIDEO_CODEC = "video_codec"
    RESOLUTION = "resolution"
    WIDTH = "width"
    HEIGHT = "height"
    SOURCE_FPS = "source_fps"
    PIXEL_FORMAT = "pixel_format"
    VIDEO_BITRATE = "video_bitrate"

    # Audio stream info
    AUDIO_CODEC = "audio_codec"
    SAMPLE_RATE = "sample_rate"
    AUDIO_CHANNELS = "audio_channels"
    AUDIO_BITRATE = "audio_bitrate"

    # Stream format info
    STREAM_TYPE = "stream_type"
    # Stream info timestamp
    STREAM_INFO_UPDATED = "stream_info_updated"
