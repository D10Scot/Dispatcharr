"""
Utilities for handling stream URLs and transformations.
"""

import json

from django.db import close_old_connections
from apps.m3u.models import M3UAccountProfile
from .redis_keys import RedisKeys
from .utils import get_logger
from dispatcharr.utils import redact_url
import requests

logger = get_logger()

# The implementations moved to apps/proxy/next_source.py in Phase 1 PR 6,
# because resolving a source is Django's job now.
#
# These two re-exports are PERMANENT. get_stream_object: input/manager.py
# :727, views.py:190 and authorize.py:330 still look a channel or stream
# up by identifier, and the spec's § ORM reads table keeps that read in
# the relay. transform_url: apps/m3u/connection_pool.py:81 and
# dispatcharr/consumers.py:116 both import it from here, function-locally,
# and neither should have to learn that it moved.
#
# The other three are TRANSITIONAL aliases. views.py:32-34,
# input/manager.py:19 and services/channel_service.py:16 import them at
# module level today; Tasks 7 and 8 rewrite those call sites and Task 8's
# last step deletes these three lines. Without them, every commit between
# here and there leaves the package unimportable.
from apps.proxy.next_source import get_stream_object, transform_url  # noqa: F401
from apps.proxy.next_source import (  # noqa: F401  transitional, deleted in Task 8
    get_alternate_streams,
    get_stream_info_for_switch,
    order_alternates_from_current,
)


def generate_stream_url(channel_id):
    """Ask Django what to play. Same 6-tuple every caller already reads.

    Phase 1 PR 6: the resolution runs in the API process now
    (apps/proxy/next_source.py). The alternates that come back are cached
    in Redis so a failover during a Django outage has something to fall
    back to — unenforced, no reservation, exactly as the spec's degraded
    fallback states.
    """
    from apps.proxy import control_plane

    try:
        answer = control_plane.next_source(
            channel_id, reason="initial", include_alternates=True
        )
    except control_plane.ControlPlaneRefused as exc:
        # Django said no — a deleted channel, a token fault. Distinct from
        # an outage so a refusal never looks like one (ruling 15).
        logger.error(
            f"Control plane refused the tune for channel {channel_id}: "
            f"{exc.status}"
        )
        return None, None, False, None, False, "Control plane refused this channel"
    except control_plane.ControlPlaneUnavailable as exc:
        logger.error(f"Control plane unreachable for channel {channel_id}: {exc}")
        return None, None, False, None, False, "Control plane unreachable"

    source = answer.get("source")
    if source is None:
        return None, None, False, None, False, answer.get("error")

    _cache_alternates(channel_id, answer.get("alternates") or [])
    return (
        source["url"],
        source["user_agent"],
        source["transcode"],
        source["stream_profile"]["id"],
        source["slot_reserved"],
        None,
    )


def _cache_alternates(channel_id, alternates):
    """Store resolved candidates for the degraded failover path.

    In Redis, not on any object: four uWSGI workers and no channel state
    in Python memory. TTL matches the metadata hash's REDIS_TTL_DEFAULT,
    so a dead channel's cache expires on its own like every other key
    (D15 — nothing flushes Redis).
    """
    if not alternates:
        return
    try:
        from core.utils import RedisClient
        from .constants import REDIS_TTL_DEFAULT

        client = RedisClient.get_client()
        if client:
            client.set(
                RedisKeys.channel_source_cache(channel_id),
                json.dumps(alternates),
                ex=REDIS_TTL_DEFAULT,
            )
    except Exception as exc:
        logger.debug(f"Could not cache alternates for {channel_id}: {exc}")


def read_cached_alternates(channel_id):
    """Read back what _cache_alternates wrote for the redirect-alternates
    loop (views.py's stream_ts). Never raises: a missing, expired or
    corrupt cache is an empty candidate list, not a stream failure.
    """
    try:
        from core.utils import RedisClient

        client = RedisClient.get_client()
        if not client:
            return []
        raw = client.get(RedisKeys.channel_source_cache(channel_id))
        if not raw:
            return []
        alternates = json.loads(raw)
        if not isinstance(alternates, list):
            return []
        return alternates
    except Exception as exc:
        logger.debug(f"Could not read cached alternates for {channel_id}: {exc}")
        return []


def validate_stream_url(url, user_agent=None, timeout=(5, 5)):
    """
    Validate if a stream URL is accessible without downloading the full content.

    Note: UDP/RTP/RTSP streams are automatically considered valid as they cannot
    be validated via HTTP methods.

    Args:
        url (str): The URL to validate
        user_agent (str): User agent to use for the request
        timeout (tuple): Connection and read timeout in seconds

    Returns:
        tuple: (is_valid, final_url, status_code, message)
    """
    # Check if URL uses non-HTTP protocols (UDP/RTP/RTSP)
    # These cannot be validated via HTTP methods, so we skip validation
    if url.startswith(('udp://', 'rtp://', 'rtsp://')):
        logger.info(f"Skipping HTTP validation for non-HTTP protocol: {redact_url(url)}")
        return True, url, 200, "Non-HTTP protocol (UDP/RTP/RTSP) - validation skipped"

    try:
        # Create session with proper headers
        session = requests.Session()
        headers = {
            'User-Agent': user_agent,
            'Connection': 'close'  # Don't keep connection alive
        }
        session.headers.update(headers)

        # Make HEAD request first as it's faster and doesn't download content
        head_request_success = True
        try:
            head_response = session.head(
                url,
                timeout=timeout,
                allow_redirects=True
            )
        except requests.exceptions.RequestException as e:
            head_request_success = False
            logger.warning(f"Request error (HEAD), assuming HEAD not supported: {str(e)}")

        # If HEAD not supported, server will return 405 or other error
        if head_request_success and (200 <= head_response.status_code < 300):
            # HEAD request successful
            return True, url, head_response.status_code, "Valid (HEAD request)"

        # Try a GET request with stream=True to avoid downloading all content
        get_response = session.get(
            url,
            stream=True,
            timeout=timeout,
            allow_redirects=True
        )

        # IMPORTANT: Check status code first before checking content
        if not (200 <= get_response.status_code < 300):
            logger.warning(f"Stream validation failed with HTTP status {get_response.status_code}")
            return False, url, get_response.status_code, f"Invalid HTTP status: {get_response.status_code}"

        # Only check content if status code is valid
        try:
            chunk = next(get_response.iter_content(chunk_size=188*10))
            is_valid = len(chunk) > 0
            message = f"Valid (GET request, received {len(chunk)} bytes)"
        except StopIteration:
            is_valid = False
            message = "Empty response from server"

        # Check content type for additional validation
        content_type = get_response.headers.get('Content-Type', '').lower()

        # Expanded list of valid content types for streaming media
        valid_content_types = [
            'video/',
            'audio/',
            'mpegurl',
            'octet-stream',
            'mp2t',
            'mp4',
            'mpeg',
            'dash+xml',
            'application/mp4',
            'application/mpeg',
            'application/x-mpegurl',
            'application/vnd.apple.mpegurl',
            'application/ogg',
            'm3u',
            'playlist',
            'binary/',
            'rtsp',
            'rtmp',
            'hls',
            'ts'
        ]

        content_type_valid = any(type_str in content_type for type_str in valid_content_types)

        # Always consider the stream valid if we got data, regardless of content type
        # But add content type info to the message for debugging
        if content_type:
            content_type_msg = f" (Content-Type: {content_type}"
            if content_type_valid:
                content_type_msg += ", recognized as valid stream format)"
            else:
                content_type_msg += ", unrecognized but may still work)"
            message += content_type_msg

        # Clean up connection
        get_response.close()

        # If we have content, consider it valid even with unrecognized content type
        return is_valid, url, get_response.status_code, message

    except requests.exceptions.Timeout:
        return False, url, 0, "Timeout connecting to stream"
    except requests.exceptions.TooManyRedirects:
        return False, url, 0, "Too many redirects"
    except requests.exceptions.RequestException as e:
        return False, url, 0, f"Request error: {str(e)}"
    except Exception as e:
        return False, url, 0, f"Validation error: {str(e)}"
    finally:
        if 'session' in locals():
            session.close()

def get_connections_left(m3u_profile_id: int) -> int:
    """
    Get the number of available connections left for an M3U profile.

    Args:
        m3u_profile_id: The ID of the M3U profile

    Returns:
        int: Number of connections available (0 if none available)
    """
    try:
        from core.utils import RedisClient

        # Get the M3U profile
        m3u_profile = M3UAccountProfile.objects.get(id=m3u_profile_id)

        # If max_streams is 0, it means unlimited
        if m3u_profile.max_streams == 0:
            return 999999  # Return a large number to indicate unlimited

        # Get Redis client
        redis_client = RedisClient.get_client()
        if not redis_client:
            logger.warning("Redis not available, assuming connections available")
            return max(0, m3u_profile.max_streams - 1)  # Conservative estimate

        # Check current connections for this specific profile
        profile_connections_key = f"profile_connections:{m3u_profile_id}"
        current_connections = int(redis_client.get(profile_connections_key) or 0)

        # Calculate available connections
        connections_left = max(0, m3u_profile.max_streams - current_connections)

        logger.debug(f"M3U profile {m3u_profile_id}: {current_connections}/{m3u_profile.max_streams} used, {connections_left} available")

        return connections_left

    except M3UAccountProfile.DoesNotExist:
        logger.error(f"M3U profile {m3u_profile_id} not found")
        return 0
    except Exception as e:
        logger.error(f"Error getting connections left for M3U profile {m3u_profile_id}: {e}")
        return 0
    finally:
        close_old_connections()
