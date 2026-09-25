"""Shared configuration between proxy types"""
import time
from django.db import connection

class BaseConfig:
    DEFAULT_USER_AGENT = 'VLC/3.0.20 LibVLC/3.0.20' # Will only be used if connection to settings fail
    CHUNK_SIZE = 8192
    CLIENT_POLL_INTERVAL = 0.1
    MAX_RETRIES = 3
    RETRY_WINDOW_SECONDS = 1800  # Reset retry counter after this long without a failure
    STABLE_CONNECTION_THRESHOLD = 30  # Seconds of uptime before switch rotation state resets
    RETRY_WAIT_INTERVAL = 0.5  # seconds to wait between retries
    CONNECTION_TIMEOUT = 10  # seconds to wait for initial connection
    MAX_STREAM_SWITCHES = 10  # Maximum number of stream switch attempts before giving up
    BUFFER_CHUNK_SIZE = 188 * 1361  # ~256KB
    BUFFERING_TIMEOUT = 15  # Seconds to wait for buffering before switching streams
    BUFFER_SPEED = 1 # What speed to condsider the stream buffering, 1x is normal speed, 2x is double speed, etc.

    # Process-local cache for proxy settings: ONE copy per process, always on
    # BaseConfig. Every method below names BaseConfig explicitly, never cls:
    # `cls._proxy_settings_cache = ...` reached through TSConfig used to create
    # a TSConfig attribute that shadowed this one, and the save-time
    # invalidation (CoreSettings.invalidate_group_cache ->
    # BaseConfig.clear_proxy_settings_cache) never cleared it (#232).
    _proxy_settings_cache = None
    _proxy_settings_cache_time = 0
    _proxy_settings_cache_ttl = 10  # Cache for 10 seconds

    @classmethod
    def clear_proxy_settings_cache(cls):
        """Drop process-local proxy settings (called on CoreSettings invalidate)."""
        BaseConfig._proxy_settings_cache = None
        BaseConfig._proxy_settings_cache_time = 0

    @classmethod
    def get_proxy_settings(cls):
        """Get proxy settings from CoreSettings JSON data with fallback to defaults (cached)"""
        # Check if cache is still valid
        now = time.time()
        cached = BaseConfig._proxy_settings_cache
        if cached is not None and (now - BaseConfig._proxy_settings_cache_time) < BaseConfig._proxy_settings_cache_ttl:
            return cached

        # Cache miss or expired - fetch from database
        try:
            from core.models import CoreSettings
            settings = CoreSettings.get_proxy_settings()
            BaseConfig._proxy_settings_cache = settings
            BaseConfig._proxy_settings_cache_time = now
            return settings

        except Exception:
            # Return defaults if database query fails
            return {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 60,
                "channel_client_wait_period": 5,
                "new_client_behind_seconds": 5,
            }

        finally:
            # Always close the connection after reading settings
            try:
                connection.close()
            except Exception:
                pass

    @classmethod
    def get_redis_chunk_ttl(cls):
        """Get Redis chunk TTL from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("redis_chunk_ttl", 60)

    @property
    def REDIS_CHUNK_TTL(self):
        return self.get_redis_chunk_ttl()

class TSConfig(BaseConfig):
    """Configuration settings for TS proxy"""

    # Buffer settings
    INITIAL_BEHIND_CHUNKS = 4  # How many chunks behind to start a client (4 chunks = ~1MB)
    CHUNK_BATCH_SIZE = 5       # How many chunks to fetch in one batch
    NEW_CLIENT_BEHIND_SECONDS = 5  # Start new clients this many seconds behind live (0 = start at live)
    KEEPALIVE_INTERVAL = 0.5   # Seconds between keepalive packets when at buffer head
    # Chunk read timeout
    CHUNK_TIMEOUT = 5        # Seconds to wait for each chunk read

    # Streaming settings
    TARGET_BITRATE = 8000000   # Target bitrate (8 Mbps)
    STREAM_TIMEOUT = 20        # Disconnect after this many seconds of no data
    HEALTH_CHECK_INTERVAL = 5  # Check stream health every N seconds

    # Resource management
    CLEANUP_INTERVAL = 60  # Check for inactive channels every 60 seconds

    # Client tracking settings
    CLIENT_RECORD_TTL = 60  # How long client records persist in Redis (seconds). Client will be considered MIA after this time.
    CLEANUP_CHECK_INTERVAL = 1  # How often to check for disconnected clients (seconds)
    CLIENT_HEARTBEAT_INTERVAL = 5  # How often to send client heartbeats (seconds)
    GHOST_CLIENT_MULTIPLIER = 10.0  # How many heartbeat intervals before client considered ghost (10 = 50s, must exceed STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD = 40s)
    CLIENT_WAIT_TIMEOUT = 60  # Seconds to wait for channel to become ready

    # Stream health and recovery settings
    MAX_HEALTH_RECOVERY_ATTEMPTS = 2     # Maximum times to attempt recovery for a single stream
    MAX_RECONNECT_ATTEMPTS = 3           # Maximum reconnects to try before switching streams
    MIN_STABLE_TIME_BEFORE_RECONNECT = 30  # Minimum seconds a stream must be stable to try reconnect
    FAILOVER_GRACE_PERIOD = 20           # Extra time (seconds) to allow for stream switching before disconnecting clients
    URL_SWITCH_TIMEOUT = 20   # Max time allowed for a stream switch operation
    MAX_KEEPALIVE_DURATION = 300         # Keepalive packets prevent _is_timeout() from firing, so without this a permanently failed stream holds clients open indefinitely.



    # Database-dependent settings with fallbacks
    @classmethod
    def get_channel_shutdown_delay(cls):
        """Get channel shutdown delay from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("channel_shutdown_delay", 0)

    @classmethod
    def get_buffering_timeout(cls):
        """Get buffering timeout from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("buffering_timeout", 15)

    @classmethod
    def get_buffering_speed(cls):
        """Get buffering speed threshold from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("buffering_speed", 1.0)

    @classmethod
    def get_channel_init_grace_period(cls):
        """Max seconds to wait for initial buffer fill during channel startup."""
        settings = cls.get_proxy_settings()
        return settings.get("channel_init_grace_period", 60)

    @classmethod
    def get_channel_client_wait_period(cls):
        """Seconds to keep a ready channel alive waiting for the first client to connect."""
        settings = cls.get_proxy_settings()
        return settings.get("channel_client_wait_period", 5)

    # Dynamic property access for these settings
    @property
    def CHANNEL_SHUTDOWN_DELAY(self):
        return self.get_channel_shutdown_delay()

    @property
    def BUFFERING_TIMEOUT(self):
        return self.get_buffering_timeout()

    @property
    def BUFFERING_SPEED(self):
        return self.get_buffering_speed()

    @property
    def CHANNEL_INIT_GRACE_PERIOD(self):
        return self.get_channel_init_grace_period()

    @property
    def CHANNEL_CLIENT_WAIT_PERIOD(self):
        return self.get_channel_client_wait_period()


# Types a class-attribute default may have and still go on the wire. bool is
# excluded explicitly because it is a subclass of int and would otherwise be
# serialised as a number; there is none today, and this is what keeps that
# from becoming a silent wire change if one is added.
_WIRE_SCALARS = (int, float, str)


def class_attribute_defaults():
    """Every TSConfig class-attribute default, by its own name.

    This is the half of the effective proxy settings that has never been on
    the wire. The relay reads these through ConfigHelper.get(name, default),
    which is getattr(TSConfig, name, default) -- apps/proxy/live_proxy/
    config_helper.py:16 -- so they are the real defaults, and a Go relay that
    did not receive them would have to hold its own copy of every one.
    Phase 2 spec Amendment A1.4.

    TSConfig, not BaseConfig, because that is what ConfigHelper consults.
    The difference is not cosmetic: TSConfig shadows BaseConfig's plain
    BUFFERING_TIMEOUT with a @property, so walking BaseConfig would put a
    stale 15 on the wire beside the buffering_timeout stored key that
    actually supplies the live value.

    The MRO is walked base-first so a derived class wins, and a name whose
    derived binding is NOT a plain scalar -- a property, a classmethod -- is
    REMOVED rather than skipped.

    That pop excludes exactly ONE name: BUFFERING_TIMEOUT, the only case
    where a plain scalar exists on BaseConfig (= 15, :16) and a @property
    shadows it on TSConfig (:163). The other five properties --
    BUFFERING_SPEED, REDIS_CHUNK_TTL, CHANNEL_SHUTDOWN_DELAY,
    CHANNEL_INIT_GRACE_PERIOD, CHANNEL_CLIENT_WAIT_PERIOD -- have no scalar
    counterpart under the same name, so they are never added in the first
    place and the isinstance check alone keeps them out. All six are
    database-backed and already on the wire under their snake_case names.
    Measured: with the pop, 31 keys; without it, 32, the extra one being
    BUFFERING_TIMEOUT carrying a stale 15.

    vars(), not dir(): dir() on a class also reports the metaclass's
    attributes, and this walk should see exactly what is written in this
    file.
    """
    defaults = {}
    for klass in reversed(TSConfig.__mro__):
        for name, value in vars(klass).items():
            if name.startswith("_"):
                continue
            if isinstance(value, _WIRE_SCALARS) and not isinstance(value, bool):
                defaults[name] = value
            else:
                defaults.pop(name, None)
    return defaults
