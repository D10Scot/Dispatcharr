"""Helper module to access configuration values with proper defaults.

Moved here from the deleted ``apps/proxy/live_proxy/config_helper.py`` in
Phase 2 stage 2d-1 (spec Amendment A10.3). Two surfaces call it --
catch-up (``apps/timeshift/views.py``, four call sites, imported at module
level) and the DVR retry window (``apps/channels/tasks.py:1125``) -- so it
cannot stay in a directory stage 2d-4 deletes.

Unlike ``apps/proxy/redis_keys.py`` and ``apps/proxy/constants.py`` this
module is NOT a leaf: it imports ``apps.proxy.config``, whose own
module-level imports are ``time`` and ``django.db.connection`` and nothing
first-party. That is boot-safe, and it is safe only for that reason --
``apps/channels/models.py`` does not import this module, so it is not on
the migration-loader path, but the same "no first-party import" discipline
applies to anything added here.

Stage 2d-4 deleted ``apps/proxy/live_proxy/config_helper.py``, the
re-export shim that stood here until then.
"""

from apps.proxy.config import TSConfig as Config

class ConfigHelper:
    """
    Helper class for accessing configuration values with sensible defaults.
    This simplifies code and ensures consistent defaults across the application.
    """

    @staticmethod
    def get(name, default=None):
        """Get a configuration value with a default fallback"""
        return getattr(Config, name, default)

    # Commonly used configuration values
    @staticmethod
    def connection_timeout():
        """Get connection timeout in seconds"""
        return ConfigHelper.get('CONNECTION_TIMEOUT', 10)

    @staticmethod
    def client_wait_timeout():
        """Get client wait timeout in seconds"""
        return ConfigHelper.get('CLIENT_WAIT_TIMEOUT', 30)

    @staticmethod
    def stream_timeout():
        """Get stream timeout in seconds"""
        return ConfigHelper.get('STREAM_TIMEOUT', 60)

    @staticmethod
    def channel_shutdown_delay():
        """Get channel shutdown delay in seconds"""
        return Config.get_channel_shutdown_delay()

    @staticmethod
    def initial_behind_chunks():
        """Get number of chunks to start behind"""
        return ConfigHelper.get('INITIAL_BEHIND_CHUNKS', 4)

    @staticmethod
    def new_client_behind_seconds():
        """Get number of seconds behind live to start new clients.
        0 means start at live (buffer head).
        Loaded from DB proxy_settings so users can change it at runtime."""
        from apps.proxy.config import TSConfig
        settings = TSConfig.get_proxy_settings()
        return settings.get('new_client_behind_seconds', 5)

    @staticmethod
    def keepalive_interval():
        """Get keepalive interval in seconds"""
        return ConfigHelper.get('KEEPALIVE_INTERVAL', 0.5)

    @staticmethod
    def cleanup_check_interval():
        """Get cleanup check interval in seconds"""
        return ConfigHelper.get('CLEANUP_CHECK_INTERVAL', 3)

    @staticmethod
    def redis_chunk_ttl():
        """Get Redis chunk TTL in seconds"""
        return Config.get_redis_chunk_ttl()

    @staticmethod
    def chunk_size():
        """Get chunk size in bytes"""
        return ConfigHelper.get('CHUNK_SIZE', 8192)

    @staticmethod
    def max_retries():
        """Get maximum retry attempts"""
        return ConfigHelper.get('MAX_RETRIES', 3)

    @staticmethod
    def retry_window_seconds():
        """Reset the retry counter after this many seconds without a failure."""
        return ConfigHelper.get('RETRY_WINDOW_SECONDS', 1800)

    @staticmethod
    def stable_connection_threshold():
        """Seconds of stable playback before switch rotation state resets."""
        return ConfigHelper.get('STABLE_CONNECTION_THRESHOLD', 30)

    @staticmethod
    def max_stream_switches():
        """Get maximum number of stream switch attempts"""
        return ConfigHelper.get('MAX_STREAM_SWITCHES', 10)

    @staticmethod
    def retry_wait_interval():
        """Get wait interval between connection retries in seconds"""
        return ConfigHelper.get('RETRY_WAIT_INTERVAL', 0.5)  # Default to 0.5 second

    @staticmethod
    def url_switch_timeout():
        """Get URL switch timeout in seconds (max time allowed for a stream switch operation)"""
        return ConfigHelper.get('URL_SWITCH_TIMEOUT', 20)  # Default to 20 seconds

    @staticmethod
    def failover_grace_period():
        """Get extra time (in seconds) to allow for stream switching before disconnecting clients"""
        return ConfigHelper.get('FAILOVER_GRACE_PERIOD', 20)  # Default to 20 seconds

    @staticmethod
    def buffering_timeout():
        """Get buffering timeout in seconds"""
        return Config.get_buffering_timeout()

    @staticmethod
    def buffering_speed():
        """Get buffering speed threshold"""
        return Config.get_buffering_speed()

    @staticmethod
    def channel_init_grace_period():
        """Max seconds to wait for initial buffer fill during channel startup."""
        return Config.get_channel_init_grace_period()

    @staticmethod
    def channel_client_wait_period():
        """Seconds to keep a ready channel alive waiting for the first client to connect."""
        return Config.get_channel_client_wait_period()

    @staticmethod
    def chunk_timeout():
        """
        Get chunk timeout in seconds (used for both socket and HTTP read timeouts).
        This controls how long we wait for each chunk before timing out.
        Set this higher (e.g., 30s) for slow providers that may have intermittent delays.
        """
        return ConfigHelper.get('CHUNK_TIMEOUT', 5)  # Default 5 seconds
