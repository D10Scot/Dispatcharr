# apps/m3u/utils.py
import codecs
import regex
import threading
import logging
from django.db import models

from dispatcharr.utils import redact_url

lock = threading.Lock()
# Dictionary to track usage: {m3u_account_id: current_usage}
active_streams_map = {}
logger = logging.getLogger(__name__)

# Per-search bound for operator-authored stream filter regexes (#262). A
# nested-quantifier or alternation pattern can otherwise stall a refresh for
# minutes across a large stream count. The rename path
# (apps/m3u/tasks.py's rename_regex_timeout), the URL transform
# (apps/proxy/next_source.py's URL_TRANSFORM_REGEX_TIMEOUT) and the
# WebSocket preview (dispatcharr/consumers.py's
# _M3U_PROFILE_TEST_REGEX_TIMEOUT) each carry the same 0.1s value
# independently; this is the first one shared as a named constant.
M3U_FILTER_REGEX_TIMEOUT = 0.1


class _BoundedFilterPattern:
    """Wrap a compiled ``regex`` pattern so every ``.search()`` is time-bounded.

    A stream filter's pattern is operator-authored and can carry catastrophic
    backtracking that survives ``regex``'s own optimizer. Once a search times
    out, the pattern trips: it logs once (naming the pattern) and returns
    non-matching (``None``) for the rest of this compiled set, i.e. for the
    rest of that refresh, instead of paying the timeout cost again for every
    remaining stream. A timed-out *exclude* filter therefore lets streams
    through (fail-open), matching the rename path's policy.
    """

    def __init__(self, compiled_pattern, timeout=M3U_FILTER_REGEX_TIMEOUT):
        self._compiled = compiled_pattern
        self._timeout = timeout
        self.tripped = False

    @property
    def pattern(self):
        return self._compiled.pattern

    def search(self, target):
        if self.tripped:
            return None
        try:
            return self._compiled.search(target, timeout=self._timeout)
        except TimeoutError:
            self.tripped = True
            logger.warning(
                "Stream filter pattern %r timed out after %.2fs; treating "
                "as non-matching for the rest of this refresh",
                self.pattern,
                self._timeout,
            )
            return None


def m3u_cp1252_fallback(error):
    """Codec error handler: decode an invalid UTF-8 byte run as cp1252.

    Registered once, below, as the ``m3u_cp1252_fallback`` error handler and
    used at every playlist decode site (#217). Provider playlists are not
    always valid UTF-8 -- Latin-1/Windows-1252 with accented channel names
    ("Séries", "Cinéma") is common -- and the strict decode used to raise
    UnicodeDecodeError there instead of importing with the right names.
    cp1252's five undefined byte codes (0x81, 0x8D, 0x8F, 0x90, 0x9D) fall
    back to the U+FFFD replacement character rather than raising again.
    """
    bad_bytes = error.object[error.start:error.end]
    return bad_bytes.decode("cp1252", errors="replace"), error.end


codecs.register_error("m3u_cp1252_fallback", m3u_cp1252_fallback)


def convert_js_numbered_backreferences(replacement):
    """Translate JS-style ``$1``/``$2`` backreferences to Python ``\\1``/``\\2``.

    Auto-sync replace patterns are authored in JS regex syntax, but Python's
    regex engines honor backslash backreferences, not ``$1``. The live rename
    and the UI preview must convert identically, so both call this single
    helper and cannot drift apart (otherwise the preview promises an output
    the sync would never produce).
    """
    return regex.sub(r"\$(\d+)", r"\\\1", replacement)


def parse_is_adult(value):
    """Return True when a provider adult flag is 1 or \"1\".

    XC providers send is_adult as an int or string. Invalid values
    (None, \"None\", empty) are treated as non-adult.
    """
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return False


def normalize_stream_url(url):
    """
    Normalize stream URLs for compatibility with FFmpeg.

    Handles VLC-specific syntax like udp://@239.0.0.1:1234 by removing the @ symbol.
    FFmpeg doesn't recognize the @ prefix for multicast addresses.

    Args:
        url (str): The stream URL to normalize

    Returns:
        str: The normalized URL
    """
    if not url:
        return url

    # Handle VLC-style UDP multicast URLs: udp://@239.0.0.1:1234 -> udp://239.0.0.1:1234
    # The @ symbol in VLC means "listen on all interfaces" but FFmpeg doesn't use this syntax
    if url.startswith('udp://@'):
        normalized = url.replace('udp://@', 'udp://', 1)
        logger.debug(
            "Normalized VLC-style UDP URL: %s -> %s",
            redact_url(url),
            redact_url(normalized),
        )
        return normalized

    # Could add other normalizations here in the future (rtp://@, etc.)
    return url


def increment_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        current_usage += 1
        active_streams_map[account.id] = current_usage
        account.active_streams = current_usage
        account.save(update_fields=['active_streams'])

def decrement_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        if current_usage > 0:
            current_usage -= 1
            if current_usage == 0:
                del active_streams_map[account.id]
            else:
                active_streams_map[account.id] = current_usage
            account.active_streams = current_usage
            account.save(update_fields=['active_streams'])


def calculate_tuner_count(minimum=1, unlimited_default=10):
    """
    Calculate tuner/connection count from active M3U profiles and custom streams.
    This is the centralized function used by both HDHR and XtreamCodes APIs.

    Args:
        minimum (int): Minimum number to return (default: 1)
        unlimited_default (int): Default value when unlimited profiles exist (default: 10)

    Returns:
        int: Calculated tuner/connection count
    """
    try:
        from apps.m3u.models import M3UAccountProfile
        from apps.channels.models import Stream

        # Calculate tuner count from active profiles from active M3U accounts (excluding default "custom Default" profile)
        profiles = M3UAccountProfile.objects.filter(
            is_active=True,
            m3u_account__is_active=True,  # Only include profiles from enabled M3U accounts
        ).exclude(id=1)

        # 1. Check if any profile has unlimited streams (max_streams=0)
        has_unlimited = profiles.filter(max_streams=0).exists()

        # 2. Calculate tuner count from limited profiles
        limited_tuners = 0
        if not has_unlimited:
            limited_tuners = (
                profiles.filter(max_streams__gt=0)
                .aggregate(total=models.Sum("max_streams"))
                .get("total", 0)
                or 0
            )

        # 3. Add custom stream count to tuner count
        custom_stream_count = Stream.objects.filter(is_custom=True).count()
        logger.debug(f"Found {custom_stream_count} custom streams")

        # 4. Calculate final tuner count
        if has_unlimited:
            # If there are unlimited profiles, start with unlimited_default plus custom streams
            tuner_count = unlimited_default + custom_stream_count
        else:
            # Otherwise use the limited profile sum plus custom streams
            tuner_count = limited_tuners + custom_stream_count

        # 5. Ensure minimum number
        tuner_count = max(minimum, tuner_count)

        logger.debug(
            f"Calculated tuner count: {tuner_count} (limited profiles: {limited_tuners}, custom streams: {custom_stream_count}, unlimited: {has_unlimited})"
        )

        return tuner_count

    except Exception as e:
        logger.error(f"Error calculating tuner count: {e}")
        return minimum  # Fallback to minimum value
