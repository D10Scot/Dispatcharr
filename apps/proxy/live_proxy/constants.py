"""
Constants used throughout the TS Proxy application.
Centralizing constants makes it easier to maintain and modify them.
"""

# Redis related constants
REDIS_KEY_PREFIX = "live"
REDIS_TTL_DEFAULT = 3600  # 1 hour
REDIS_TTL_SHORT = 60      # 1 minute
REDIS_TTL_MEDIUM = 300    # 5 minutes

# ChannelState and ChannelMetadataField moved to apps/proxy/constants.py in
# Phase 2 stage 2d-1 and are re-exported here so every importer inside this
# package -- and the five test files outside it that name this path -- keeps
# working until stage 2d-4 deletes the package. Nothing new should import
# them from here.
from apps.proxy.constants import ChannelMetadataField, ChannelState  # noqa: F401

# Event types
class EventType:
    STREAM_SWITCH = "stream_switch"
    STREAM_SWITCHED = "stream_switched"
    CHANNEL_STOP = "channel_stop"
    CHANNEL_STOPPED = "channel_stopped"
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"
    CLIENT_STOP = "client_stop"
    ENSURE_OUTPUT_FORMAT = "ensure_output_format"
    ENSURE_OUTPUT_PROFILE = "ensure_output_profile"

# Stream types
class StreamType:
    HLS = "hls"
    RTSP = "rtsp"
    UDP = "udp"
    TS = "ts"
    UNKNOWN = "unknown"

# TS packet constants
TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47
NULL_PID_HIGH = 0x1F
NULL_PID_LOW = 0xFF
