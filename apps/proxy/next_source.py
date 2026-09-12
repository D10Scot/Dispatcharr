"""Which stream a channel plays next — Django's answer, not the relay's.

Phase 1 PR 6. Everything here used to live in
apps/proxy/live_proxy/url_utils.py and ran inside the relay: the ordered
traversal of a channel's streams, the per-profile capacity check, the
provider-slot reservation, and the URL/user-agent/transcode derivation.
It moves here whole, not rewritten — the relay reaches it over
POST /api/relay/channels/<identifier>/next-source (ADR 0005), and the six
Django-side callers reach it by import.

Nothing in this module runs in the relay process. It is the only place
Channel.get_stream(), Channel.release_stream() and
Channel.update_stream_profile() are called from, which is what gives
channel_stream:* and stream_profile:* a single writer.
"""

import logging
from typing import List, Optional

import regex
from django.db import close_old_connections
from django.shortcuts import get_object_or_404

from apps.channels.models import Channel, Stream
from apps.m3u.connection_pool import (
    get_profile_connection_count,
    profile_available_for_channel_switch,
)
from apps.m3u.models import M3UAccount, M3UAccountProfile
from core.models import StreamProfile
from dispatcharr.utils import redact_url

# next_source.py gets its own logger rather than reusing url_utils's (built
# from .utils.get_logger, another live_proxy import that would reintroduce
# the module-level cycle this move is meant to close). "live_proxy" is the
# same logger name services/channel_service.py already uses, so every moved
# line still logs to the stream it logs to today.
logger = logging.getLogger("live_proxy")


def _resolve_live_stream_url(stream, m3u_account, m3u_profile):
    """
    Build the upstream URL for live playback.

    XC accounts use current transformed credentials plus provider stream_id so
    playback matches the account login (not a stale stream.url from an old sync).
    STD/M3U accounts keep using the URL stored on the stream row.
    """
    if (
        m3u_account.account_type == M3UAccount.Types.XC
        and stream.stream_id
    ):
        from apps.m3u.tasks import get_transformed_credentials

        server_url, username, password = get_transformed_credentials(
            m3u_account, m3u_profile
        )
        if server_url and username and password:
            base = server_url.rstrip("/")
            return f"{base}/live/{username}/{password}/{stream.stream_id}.ts"

    return transform_url(
        stream.url or "",
        m3u_profile.search_pattern,
        m3u_profile.replace_pattern,
    )


# Sentinel for "the caller did not pass a memoized locked-ffmpeg profile",
# distinct from None -- None is itself a valid, meaningful return from
# _locked_ffmpeg_profile() ("no locked profile installed").
_UNRESOLVED_FFMPEG_PROFILE = object()


def _locked_ffmpeg_profile():
    """The locked 'ffmpeg' StreamProfile, flattened, or None.

    input/manager.py:737 used to run this query inside the relay process on
    the force-ffmpeg reconnect path (HLS/RTSP/UDP upstreams detected at
    connect time). Phase 2 PR 2b-1 folds it into every next-source answer
    instead: Django is already holding an open ORM here, and the relay
    cannot be.

    None means "no locked ffmpeg profile is installed", which is what the
    relay's own `except StreamProfile.DoesNotExist` branch already handled
    by falling back to the channel's own profile. The key is always
    present so the relay can tell "not installed" from "old Django".

    Callers inside this module that run once per resolve_source() call
    (resolve_initial_source, _source_from_info, _resolve_alternates,
    _commit) take a `locked_ffmpeg_profile` kwarg instead of calling this
    directly, so resolve_source() can resolve it once and thread the same
    value through every Source it builds -- see the N-alternates note on
    resolve_source() itself. Call this function directly only from
    resolve_source() (or a test).
    """
    profile = StreamProfile.objects.filter(name="ffmpeg", locked=True).first()
    if profile is None:
        return None
    return {"id": profile.id, "command": profile.command, "args": profile.parameters}


def get_stream_object(id: str):
    try:
        logger.info(f"Fetching channel ID {id}")
        return get_object_or_404(Channel, uuid=id)
    except:
        # UUID check failed, assume stream hash
        logger.info(f"Fetching stream hash {id}")
        return get_object_or_404(
            Stream.objects.select_related("m3u_account__user_agent"),
            stream_hash=id,
        )


# Bounds catastrophic backtracking on user-authored profile patterns.
# Matches the rename / regex-preview timeout used elsewhere.
URL_TRANSFORM_REGEX_TIMEOUT = 0.1


def transform_url(input_url: str, search_pattern: str, replace_pattern: str) -> str:
    """
    Transform a URL using regex pattern replacement.

    Args:
        input_url: The base URL to transform
        search_pattern: The regex search pattern
        replace_pattern: The replacement pattern

    Returns:
        str: The transformed URL
    """
    try:
        logger.debug("Executing URL pattern replacement:")
        logger.debug(f"  base URL: {redact_url(input_url)}")
        logger.debug(f"  search: {search_pattern}")

        # Convert JS-style backreferences in replace pattern: $<name> -> \g<name>, $1 -> \1
        # Fixed conversion patterns only; timeout is reserved for the user search.
        safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', replace_pattern)
        safe_replace_pattern = regex.sub(r'\$(\d+)', r'\\\1', safe_replace_pattern)
        logger.debug(f"  replace: {replace_pattern}")
        logger.debug(f"  safe replace: {safe_replace_pattern}")

        # Apply the transformation (regex module accepts JS-style (?<name>...) natively).
        # timeout bounds ReDoS from nested quantifiers in search_pattern.
        stream_url, match_count = regex.subn(
            search_pattern,
            safe_replace_pattern,
            input_url,
            timeout=URL_TRANSFORM_REGEX_TIMEOUT,
        )
        if match_count == 0:
            logger.warning(f"URL pattern '{search_pattern}' did not match, falling back to original URL: {redact_url(input_url)}")
        else:
            logger.info(f"Generated stream url: {redact_url(stream_url)}")

        return stream_url
    except Exception as e:
        logger.error(f"Error transforming URL: {e}")
        return input_url  # Return original URL on error


def order_alternates_from_current(
    alternate_streams: List[dict],
    ordered_stream_ids: List[int],
    current_stream_id: Optional[int],
) -> List[dict]:
    """
    Reorder failover candidates to start after the current stream in channel order,
    wrapping around.
    """
    if not alternate_streams or not ordered_stream_ids or current_stream_id is None:
        return alternate_streams

    alt_by_id = {entry['stream_id']: entry for entry in alternate_streams}

    try:
        current_index = ordered_stream_ids.index(current_stream_id)
    except ValueError:
        return alternate_streams

    rotated = []
    for offset in range(1, len(ordered_stream_ids)):
        stream_id = ordered_stream_ids[(current_index + offset) % len(ordered_stream_ids)]
        entry = alt_by_id.get(stream_id)
        if entry is not None:
            rotated.append(entry)
    return rotated


def get_stream_info_for_switch(channel_id: str, target_stream_id: Optional[int] = None) -> dict:
    """
    Get stream information for a channel switch, optionally to a specific stream ID.

    Args:
        channel_id: The UUID of the channel
        target_stream_id: Optional specific stream ID to switch to

    Returns:
        dict: Stream information including URL, user agent and transcode flag
    """
    slot_reserved = False
    channel = None
    try:
        from core.utils import RedisClient
        from apps.proxy.live_proxy.redis_keys import RedisKeys

        channel = get_object_or_404(Channel, uuid=channel_id)
        redis_client = RedisClient.get_client()

        # Use the target stream if specified, otherwise use current stream
        if target_stream_id:
            stream_id = target_stream_id

            # Get the stream object
            stream = get_object_or_404(
                Stream.objects.select_related("m3u_account"),
                pk=stream_id,
            )

            # Find compatible profile for this stream with connection availability check
            m3u_account = stream.m3u_account
            if not m3u_account:
                return {'error': 'Stream has no M3U account'}

            m3u_profiles = m3u_account.profiles.filter(is_active=True)
            default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)

            if not default_profile:
                return {'error': 'M3U account has no default profile'}

            # Check profiles in order: default first, then others
            profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]

            selected_profile = None
            for profile in profiles:
                if redis_client:
                    channel_using_profile = False
                    existing_stream_id = redis_client.get(RedisKeys.channel_stream(channel.id))
                    if existing_stream_id:
                        existing_profile_id = redis_client.get(
                            RedisKeys.stream_profile(existing_stream_id)
                        )
                        if existing_profile_id and int(existing_profile_id) == profile.id:
                            channel_using_profile = True

                    if profile_available_for_channel_switch(
                        profile,
                        redis_client,
                        channel_already_on_profile=channel_using_profile,
                    ):
                        current_connections = get_profile_connection_count(
                            profile, redis_client
                        )
                        selected_profile = profile
                        logger.debug(
                            f"Selected profile {profile.id} with "
                            f"{current_connections}/{profile.max_streams} connections"
                        )
                        break
                    logger.debug(
                        f"Profile {profile.id} unavailable for channel switch"
                    )
                else:
                    selected_profile = profile
                    break

            if not selected_profile:
                return {'error': 'No profiles available with connection capacity'}

            m3u_profile_id = selected_profile.id
        else:
            stream_id, m3u_profile_id, error_reason, slot_reserved = channel.get_stream()
            if stream_id is None or m3u_profile_id is None:
                return {'error': error_reason or 'No stream assigned to channel'}

        stream = get_object_or_404(Stream, pk=stream_id)
        m3u_profile = get_object_or_404(
            M3UAccountProfile.objects.select_related("m3u_account__user_agent"),
            pk=m3u_profile_id,
        )

        m3u_account = m3u_profile.m3u_account
        user_agent = m3u_account.get_user_agent_string()

        stream_url = _resolve_live_stream_url(stream, m3u_account, m3u_profile)

        stream_profile = channel.get_stream_profile()
        # Redirect is treated like Proxy here too (see resolve_initial_source
        # below): StreamManager reads this flag on every failover/switch,
        # not just the initial tune, and a Redirect profile's build_command
        # is empty.
        transcode = not (
            stream_profile.is_proxy() or stream_profile.is_redirect() or stream_profile is None
        )
        profile_value = stream_profile.id

        return {
            'url': stream_url,
            'user_agent': user_agent,
            'transcode': transcode,
            'stream_profile': profile_value,
            'stream_id': stream_id,
            'm3u_profile_id': m3u_profile_id,
            'stream_name': stream.name,
            'channel_name': channel.name,
            'm3u_profile_name': m3u_profile.name,
        }
    except Exception as e:
        if slot_reserved and channel is not None:
            channel.release_stream()
        logger.error(f"Error getting stream info for switch: {e}", exc_info=True)
        return {'error': f'Error: {str(e)}'}
    finally:
        close_old_connections()


def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None) -> List[dict]:
    """
    Get alternative streams for a channel when the current stream fails.

    Args:
        channel_id: The UUID of the channel
        current_stream_id: The currently failing stream ID to exclude

    Returns:
        List[dict]: List of stream information dictionaries with stream_id and profile_id
    """
    try:
        from core.utils import RedisClient
        from apps.proxy.live_proxy.redis_keys import RedisKeys

        # Get channel object
        channel = get_stream_object(channel_id)
        if isinstance(channel, Stream):
            logger.error(f"Stream is not a channel")
            return []

        redis_client = RedisClient.get_client()
        logger.debug(f"Looking for alternate streams for channel {channel_id}, current stream ID: {current_stream_id}")

        # Get all assigned streams for this channel using the correct ordering
        streams = channel.streams.all().order_by('channelstream__order')
        ordered_stream_ids = list(streams.values_list('id', flat=True))
        logger.debug(f"Channel {channel_id} has {len(ordered_stream_ids)} total assigned streams")

        if not ordered_stream_ids:
            logger.warning(f"No streams assigned to channel {channel_id}")
            return []

        alternate_streams = []

        # Process each stream in the user-defined order
        for stream in streams:
            logger.debug(f"Checking stream ID {stream.id} ({stream.name}) for channel {channel_id}")

            # Skip the current failing stream
            if current_stream_id and stream.id == current_stream_id:
                logger.debug(f"Skipping current stream ID {current_stream_id}")
                continue

            # Find compatible profiles for this stream with connection checking
            try:
                m3u_account = stream.m3u_account
                if not m3u_account:
                    logger.debug(f"Stream {stream.id} has no M3U account")
                    continue
                if m3u_account.is_active == False:
                    logger.debug(f"M3U account {m3u_account.id} is inactive, skipping.")
                    continue
                m3u_profiles = m3u_account.profiles.filter(is_active=True)
                default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)

                if not default_profile:
                    logger.debug(f"M3U account {m3u_account.id} has no default profile")
                    continue

                # Check profiles in order with connection availability
                profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]

                selected_profile = None
                for profile in profiles:
                    if redis_client:
                        channel_using_profile = False
                        existing_stream_id = redis_client.get(RedisKeys.channel_stream(channel.id))
                        if existing_stream_id:
                            existing_profile_id = redis_client.get(
                                RedisKeys.stream_profile(existing_stream_id)
                            )
                            if existing_profile_id and int(existing_profile_id) == profile.id:
                                channel_using_profile = True
                                logger.debug(
                                    f"Channel {channel.id} already using profile {profile.id}"
                                )

                        if profile_available_for_channel_switch(
                            profile,
                            redis_client,
                            channel_already_on_profile=channel_using_profile,
                        ):
                            current_connections = get_profile_connection_count(
                                profile, redis_client
                            )
                            selected_profile = profile
                            logger.debug(
                                f"Found available profile {profile.id} for stream {stream.id}: "
                                f"{current_connections}/{profile.max_streams} "
                                f"(already using: {channel_using_profile})"
                            )
                            break
                        logger.debug(
                            f"Profile {profile.id} unavailable for alternate stream {stream.id}"
                        )
                    else:
                        selected_profile = profile
                        break

                if selected_profile:
                    alternate_streams.append({
                        'stream_id': stream.id,
                        'profile_id': selected_profile.id,
                        'name': stream.name
                    })
                else:
                    logger.debug(f"No available profiles for stream ID {stream.id}")

            except Exception as inner_e:
                logger.error(f"Error finding profiles for stream {stream.id}: {inner_e}")
                continue

        if alternate_streams:
            stream_ids = ', '.join([str(s['stream_id']) for s in alternate_streams])
            logger.info(f"Found {len(alternate_streams)} alternate streams with available connections for channel {channel_id}: [{stream_ids}]")
        else:
            logger.warning(f"No alternate streams with available connections found for channel {channel_id}")

        return order_alternates_from_current(
            alternate_streams, ordered_stream_ids, current_stream_id
        )
    except Exception as e:
        logger.error(f"Error getting alternate streams for channel {channel_id}: {e}", exc_info=True)
        return []
    finally:
        close_old_connections()


def resolve_initial_source(identifier):
    """
    Resolve the source a channel or previewed stream should play right now.

    This is generate_stream_url's body (apps/proxy/live_proxy/url_utils.py),
    moved verbatim except for its return shape: a Source dict instead of the
    6-tuple, because Task 7 turns url_utils.generate_stream_url into an HTTP
    call and this is the answer that call carries.

    Each branch below calls _locked_ffmpeg_profile() only at the point it
    is actually about to build a successful Source, not eagerly at the top
    of this function -- eager resolution would query on every call,
    including the ones that end in "no stream available" and never build a
    Source at all. NextSourceDbCleanupTests's SimpleTestCase pins that this
    function makes no query until it has something to build. The caller
    (resolve_source()) reuses the value this function resolved rather than
    asking this function to accept and thread through a pre-resolved one --
    see resolve_source()'s N-alternates note.

    Returns {"source": <dict|None>, "error": <str|None>}.
    """
    try:
        channel_or_stream = get_stream_object(identifier)

        # Handle direct stream preview (custom streams)
        if isinstance(channel_or_stream, Stream):
            stream = channel_or_stream
            logger.info(f"Previewing stream directly: {stream.id} ({stream.name})")

            if not stream.m3u_account:
                logger.error(f"Stream {stream.id} has no M3U account")
                return {"source": None, "error": "Stream has no M3U account"}

            stream_id, profile_id, error_reason, slot_reserved = stream.get_stream()
            if not stream_id or not profile_id:
                logger.error(f"No profile available for stream {stream.id}: {error_reason}")
                return {"source": None, "error": error_reason}

            try:
                m3u_profile = M3UAccountProfile.objects.select_related(
                    "m3u_account__user_agent"
                ).get(id=profile_id)
                # Prefer the profile's account so select_related populates the UA.
                m3u_account = m3u_profile.m3u_account or stream.m3u_account

                stream_user_agent = m3u_account.get_user_agent_string()

                stream_url = _resolve_live_stream_url(stream, m3u_account, m3u_profile)

                stream_profile = stream.get_stream_profile()
                logger.debug(f"Using stream profile: {stream_profile.name}")

                # Redirect is treated like Proxy here: the relay never
                # spawns a subprocess for either, and StreamManager reads
                # this flag on every subsequent failover/switch, not just
                # the initial tune (Phase 1 PR 5 re-review).
                transcode = not (stream_profile.is_proxy() or stream_profile.is_redirect())

                return {
                    "source": {
                        "stream_id": stream_id,
                        "url": stream_url,
                        "user_agent": stream_user_agent,
                        "transcode": transcode,
                        "stream_profile": {
                            "id": stream_profile.id,
                            "command": stream_profile.command,
                            "args": stream_profile.parameters,
                        },
                        "m3u_profile_id": profile_id,
                        "slot_reserved": slot_reserved,
                        "channel_name": stream.name,
                        "stream_name": stream.name,
                        "m3u_profile_name": m3u_profile.name,
                        "ffmpeg_stream_profile": _locked_ffmpeg_profile(),
                    },
                    "error": None,
                }
            except Exception as e:
                logger.error(f"Error generating stream URL for stream {stream.id}: {e}")
                if slot_reserved:
                    stream.release_stream()
                return {"source": None, "error": str(e)}


        # Handle channel preview (existing logic)
        channel = channel_or_stream

        # Get stream and profile for this channel
        stream_id, profile_id, error_reason, slot_reserved = channel.get_stream()

        if not stream_id or not profile_id:
            logger.error(f"No stream available for channel {identifier}: {error_reason}")
            return {"source": None, "error": error_reason}

        # get_stream() allocated a connection slot - ensure it's released on any error
        try:
            stream = Stream.objects.get(id=stream_id)
            m3u_profile = M3UAccountProfile.objects.select_related(
                "m3u_account__user_agent"
            ).get(id=profile_id)

            m3u_account = m3u_profile.m3u_account
            stream_user_agent = m3u_account.get_user_agent_string()

            stream_url = _resolve_live_stream_url(stream, m3u_account, m3u_profile)

            # Check if transcoding is needed. Redirect is treated like Proxy
            # here: this is the value the initial DVR tune reads
            # (apps/proxy/live_proxy/views.py's stream_ts), and
            # get_stream_info_for_switch above must agree, or a Redirect
            # channel's first failover rebuilds this exact command from the
            # Redirect profile's empty command/parameters (Phase 1 PR 5
            # re-review).
            stream_profile = channel.get_stream_profile()
            if stream_profile.is_proxy() or stream_profile.is_redirect() or stream_profile is None:
                transcode = False
            else:
                transcode = True

            return {
                "source": {
                    "stream_id": stream_id,
                    "url": stream_url,
                    "user_agent": stream_user_agent,
                    "transcode": transcode,
                    "stream_profile": {
                        "id": stream_profile.id,
                        "command": stream_profile.command,
                        "args": stream_profile.parameters,
                    },
                    "m3u_profile_id": profile_id,
                    "slot_reserved": slot_reserved,
                    "channel_name": channel.name,
                    "stream_name": stream.name,
                    "m3u_profile_name": m3u_profile.name,
                    "ffmpeg_stream_profile": _locked_ffmpeg_profile(),
                },
                "error": None,
            }
        except Exception as e:
            logger.error(f"Error generating stream URL for channel {identifier}: {e}")
            if slot_reserved:
                if not channel.release_stream():
                    logger.warning(f"Failed to release stream for channel {identifier} after URL generation error")
            return {"source": None, "error": str(e)}
    except Exception as e:
        logger.error(f"Error generating stream URL: {e}")
        return {"source": None, "error": str(e)}
    finally:
        close_old_connections()


def _source_from_info(info, *, slot_reserved, locked_ffmpeg_profile=_UNRESOLVED_FFMPEG_PROFILE):
    """Shape one Source dict from a get_stream_info_for_switch answer.

    `info['stream_profile']` is a core.models.StreamProfile id (the
    ffmpeg/proxy/redirect profile), not the M3U profile — the seven fields
    here are the SourceSerializer contract Task 6 adds.

    locked_ffmpeg_profile: see resolve_source()'s N-alternates note --
    _resolve_alternates calls this once per candidate, so a caller that
    knows it in advance (that function, and _commit) should pass it rather
    than let each call re-run the query.
    """
    if locked_ffmpeg_profile is _UNRESOLVED_FFMPEG_PROFILE:
        locked_ffmpeg_profile = _locked_ffmpeg_profile()
    stream_profile = StreamProfile.objects.get(id=info["stream_profile"])
    return {
        "stream_id": info["stream_id"],
        "url": info["url"],
        "user_agent": info["user_agent"],
        "transcode": info["transcode"],
        "stream_profile": {
            "id": stream_profile.id,
            "command": stream_profile.command,
            "args": stream_profile.parameters,
        },
        "m3u_profile_id": info["m3u_profile_id"],
        "slot_reserved": slot_reserved,
        "channel_name": info.get("channel_name"),
        "stream_name": info.get("stream_name"),
        "m3u_profile_name": info.get("m3u_profile_name"),
        "ffmpeg_stream_profile": locked_ffmpeg_profile,
    }


def _resolve_alternates(identifier, current_stream_id, *, locked_ffmpeg_profile=_UNRESOLVED_FFMPEG_PROFILE):
    """Resolve every alternate candidate without reserving anything.

    locked_ffmpeg_profile is resolved once here (if not already passed in
    by resolve_source()) and threaded to every _source_from_info() call in
    the loop below, rather than letting each of the N candidates re-run
    the same query -- see resolve_source()'s N-alternates note.
    """
    if locked_ffmpeg_profile is _UNRESOLVED_FFMPEG_PROFILE:
        locked_ffmpeg_profile = _locked_ffmpeg_profile()
    alternates = []
    for candidate in get_alternate_streams(identifier, current_stream_id=current_stream_id):
        info = get_stream_info_for_switch(identifier, candidate["stream_id"])
        if "error" in info:
            continue
        alternates.append(
            _source_from_info(
                info, slot_reserved=False, locked_ffmpeg_profile=locked_ffmpeg_profile
            )
        )
    return alternates


def _commit(identifier, info, *, locked_ffmpeg_profile=_UNRESOLVED_FFMPEG_PROFILE):
    """Move the provider slot to the chosen candidate, then shape it.

    This is exactly the call input/manager.py's update_url made at :1437,
    moved here because the credential-slot move belongs on the side that
    owns the counter. Channel.update_stream_profile() is UNCHANGED: it
    rewrites stream_profile:{the channel's ORIGINAL stream} and moves both
    profile_connections counters, and it never writes channel_stream:*.
    That chain is what release_stream(), get_stream()'s reuse branch and
    core/utils.py's event enrichment all read; PR 6 does not touch it
    (spec § PR 6 amendment S10).
    """
    channel = get_stream_object(identifier)
    slot_reserved = False
    if isinstance(channel, Channel) and info.get("m3u_profile_id"):
        slot_reserved = bool(channel.update_stream_profile(info["m3u_profile_id"]))
    return _source_from_info(
        info, slot_reserved=slot_reserved, locked_ffmpeg_profile=locked_ffmpeg_profile
    )


def _with_proxy_settings(answer):
    """Channel-start-time proxy settings, on every next-source answer.

    Spec § Stage 2b: "2b moves proxy_settings onto the next-source response
    (channel-start-time values only, matching D5's 'thresholds snapshotted
    at channel start' parity row)". Read through CoreSettings directly, not
    apps/proxy/config.py's TSConfig, so the 10-second process-local cache is
    not in the path. That cache is worse than merely stale: saving
    proxy_settings clears it in NO worker on the proxy path, because
    CoreSettings.invalidate_group_cache calls
    BaseConfig.clear_proxy_settings_cache() while every proxy read goes
    through TSConfig, whose own class attribute shadows the parent's
    (issue #232). The 10-second TTL is what actually ends the staleness.

    Nothing in the PYTHON relay consumes this yet, deliberately -- see this
    plan's § Self-review for the ruling and the reason, and this PR's
    description.
    """
    from core.models import CoreSettings

    answer["proxy_settings"] = CoreSettings.get_proxy_settings()
    return answer


def _with_output_profiles(answer):
    """Every active OutputProfile's built argv, on every next-source answer.

    Spec § Stage 2b, the `views.py:152` row: "A control-plane response
    body can [carry a built ffmpeg command], unlike a header."

    Deviation from that row, recorded in the 2b-2 plan as Ruling R3: the
    spec says "when X-Relay-Output names a profile", i.e. one profile per
    request. next-source is a per-CHANNEL call (initial tune, failover,
    resume); the profile is resolved per CLIENT, and the client that did
    not initialize the channel never makes a next-source call at all
    (apps/proxy/live_proxy/views.py:712). One profile per request
    therefore cannot answer any client's question but the first's, so the
    whole active set travels instead and a Go relay caches it per channel.

    Nothing in the PYTHON relay consumes this, deliberately: doing so
    would need either a per-client route (the spec rejects one) or a
    Redis cache with staleness semantics nothing has specified.
    apps/proxy/live_proxy/views.py:152's ORM read therefore stays, and
    2b-3 owns the decision to allowlist or close it.
    """
    from core.models import OutputProfile

    output_profiles = {}
    for profile in OutputProfile.objects.filter(is_active=True):
        try:
            argv = profile.build_command()
        except ValueError:
            # OutputProfileSerializer validates nothing, so an unbalanced
            # quote in `parameters` can already be sitting in the
            # database (issue found in review: B1). Before this map
            # existed, a malformed row only broke the clients that
            # selected it (views.py's stream_ts, inside its own broad
            # except); folding EVERY active profile into EVERY
            # next-source answer means one bad row would otherwise 500
            # next-source for every channel, on every tune, failover and
            # resume, regardless of which profile that channel uses.
            # Skip it and keep the rest of the map serving.
            logger.error(
                "OutputProfile %s has unparseable parameters; omitting "
                "it from next-source's output_profiles map",
                profile.id,
            )
            continue
        output_profiles[str(profile.id)] = {"id": profile.id, "argv": argv}
    answer["output_profiles"] = output_profiles
    return answer


def resolve_source(
    identifier,
    *,
    exclude_stream_ids=(),
    current_url=None,
    target_stream_id=None,
    current_stream_id=None,
    reason="initial",
    include_alternates=False,
):
    """Resolve one playable source, and optionally the fallback list.

    Three shapes, one function:
      * no excludes, no target, no current_url, reason != "failover" ->
        Channel.get_stream() unchanged (D13), which reuses a live
        assignment or reserves a new slot. This is the tune path
        (reason="initial", never sends current_url) and the
        cancel_pending_shutdown resume path (reason="resume") — both want
        the reuse-or-reserve behaviour, not a traversal.
      * target_stream_id -> that stream, if a profile has capacity; the
        provider slot moves to its profile.
      * otherwise (exclude_stream_ids non-empty, OR current_url given, OR
        reason=="failover") -> the ordered traversal, skipping what the
        relay has already tried and anything resolving to current_url,
        then the slot moves to the winner. current_url is what lets
        Django make the whole decision: the relay used to loop
        candidates only to reject one whose URL matched its own.
        Routing on current_url/reason as well as exclude_stream_ids
        matters because a failover with nothing tried yet and no known
        current_stream_id still sends an empty exclude list — without
        this, that request would fall into the reuse branch above and
        Channel.get_stream() would hand back the URL already playing,
        which update_url then refuses to "switch" to (Phase 1 PR 6,
        Task 8 review round 1).

    current_stream_id is the stream the relay is failing over FROM. It is
    passed straight through to get_alternate_streams() in the failover
    branch below so order_alternates_from_current() can rotate candidates
    to start right after it, wrapping — the property
    apps.proxy.live_proxy.input.manager._try_next_stream relies on today
    by passing self.current_stream_id to the pre-move get_alternate_streams.
    Without it, the traversal silently falls back to channel order from
    the top, which is a different (worse) failover than today's.

    Returns {"source": <dict|None>, "alternates": [dict], "error": <str|None>}.
    Only "source" ever reserves or moves a slot; alternates are
    resolution only, which is what makes the relay's degraded fallback
    unenforced by construction. May reserve a profile slot for the
    returned source (`slot_reserved`); the double call from
    `change_stream` -> `update_url` is the pre-move behaviour, idempotent
    on both halves. This function adds no try/finally of its
    own: each moved helper still closes its own connections, and
    NextSourceDbCleanupTests asserts exactly one close on the initial path.

    N-alternates note (review round, #253-adjacent): _locked_ffmpeg_profile()
    is the same StreamProfile query regardless of which candidate is being
    shaped, so it must not run once per candidate. Before this, the
    include_alternates=True branch below ran it N+1 times per tune (once
    inside resolve_initial_source() for the primary source, then once more
    per alternate inside _resolve_alternates() -> _source_from_info()) for
    a value the relay never even reads off an alternate (the
    degraded-fallback path writes no FFMPEG_STREAM_PROFILE). It now runs
    exactly once: resolve_initial_source() still resolves it lazily, only
    if it is actually building a Source (so a "no stream available" answer
    still costs zero queries, unchanged from before), and the value it
    resolved is reused for every alternate rather than re-queried.
    test_resolving_with_alternates_runs_the_locked_ffmpeg_query_once below
    pins the count. _commit()'s own single call (the target-stream and
    failover branches) is unaffected -- it was never in a loop, so there
    was nothing to fix there.
    """
    # Resolve the identifier FIRST, outside every try. Both moved
    # helpers end in `except Exception` (originally url_utils.py:161-163
    # and :485) and would swallow the Http404 get_stream_object raises for
    # an unknown identifier, turning a 404 into a 200 with an opaque
    # "No Stream matches the given query." error string. The view's
    # `except Http404 -> 404` (Task 6) depends on this line, and so does
    # test_an_unknown_identifier_raises_http404. The DB-cleanup pin
    # patches this same name, so test_resolve_source_closes_db is
    # unaffected. Kept (not discarded) so the reuse-or-reserve branch below
    # can tell a channel from a previewed stream without a second lookup.
    resolved_object = get_stream_object(identifier)

    excluded = {int(sid) for sid in exclude_stream_ids or ()}

    # A failover request can carry an empty exclude list -- nothing tried
    # yet, and no current_stream_id to add to it -- so "no excludes" alone
    # cannot mean "reuse the live assignment". current_url is not None (the
    # tune and resume paths never send it) or reason=="failover" is what
    # actually distinguishes a failover from the reuse-or-reserve shape.
    is_failover_request = current_url is not None or reason == "failover"

    if not excluded and target_stream_id is None and not is_failover_request:
        # No pre-resolved locked_ffmpeg_profile here: resolve_initial_source
        # queries it lazily, only if it is about to build a Source, so a
        # "no stream available" answer costs no query at all -- eagerly
        # resolving it here first would query on every call, including
        # that one. When there IS a source and alternates are wanted, the
        # value resolve_initial_source already computed is reused below
        # instead of _resolve_alternates() resolving its own (see that
        # function's docstring and resolve_source()'s N-alternates note).
        answer = resolve_initial_source(identifier)
        # A previewed Stream has no assigned alternates -- get_alternate_streams()
        # walks Channel.streams, which a bare Stream doesn't have -- so
        # _resolve_alternates would call get_alternate_streams(), which logs
        # "Stream is not a channel" at ERROR on every preview tune. Skip it
        # for anything that isn't a Channel instead (Phase 1 PR 6 fix wave B).
        if (
            answer["source"] is not None
            and include_alternates
            and isinstance(resolved_object, Channel)
        ):
            answer["alternates"] = _resolve_alternates(
                identifier, answer["source"]["stream_id"],
                locked_ffmpeg_profile=answer["source"]["ffmpeg_stream_profile"],
            )
        answer.setdefault("alternates", [])
        return _with_output_profiles(_with_proxy_settings(answer))

    if target_stream_id is not None:
        info = get_stream_info_for_switch(identifier, target_stream_id)
        if "error" in info:
            return _with_output_profiles(_with_proxy_settings(
                {"source": None, "alternates": [], "error": info["error"]}
            ))
        return _with_output_profiles(_with_proxy_settings({
            "source": _commit(identifier, info),
            "alternates": [],
            "error": None,
        }))

    # Failover: the ordered traversal, minus what the relay has tried and
    # minus anything resolving to the URL already playing. That last check
    # is the only reason input/manager.py used to loop candidates itself.
    # current_stream_id rotates the start point (see docstring); passing
    # it through here is what keeps get_alternate_streams' rotation the
    # same as it is today.
    for candidate in get_alternate_streams(identifier, current_stream_id=current_stream_id):
        if candidate["stream_id"] in excluded:
            continue
        info = get_stream_info_for_switch(identifier, candidate["stream_id"])
        if "error" in info or not info.get("url"):
            continue
        if current_url and info["url"] == current_url:
            continue
        return _with_output_profiles(_with_proxy_settings({
            "source": _commit(identifier, info),
            "alternates": [],
            "error": None,
        }))
    return _with_output_profiles(_with_proxy_settings({
        "source": None,
        "alternates": [],
        "error": "No alternate stream with available connections",
    }))


def release_source(identifier, *, stream_id=None, m3u_profile_id=None, channel_pk=None):
    """Give the provider slot back. Wraps release_stream() (D13).

    The three-step fallback is what apps/proxy/live_proxy/server.py used
    to run: Channel.release_stream(), then Stream.release_stream(), then
    — for a channel deleted mid-playback, where neither row exists — the
    ids the relay read out of its own metadata hash, which is why they
    arrive as arguments rather than being re-read here.
    """
    try:
        channel = Channel.objects.get(uuid=identifier)
        if channel.release_stream():
            return True
        logger.debug(f"Channel {identifier}: release_stream found no keys to clean")
    except Channel.DoesNotExist:
        pass
    except Exception as e:
        logger.debug(f"Channel {identifier}: release_stream via ORM failed: {e}")

    try:
        stream = Stream.objects.get(stream_hash=identifier)
        if stream.release_stream():
            return True
        logger.debug(f"Stream {identifier}: release_stream found no keys to clean")
    except Stream.DoesNotExist:
        pass
    except Exception as e:
        logger.debug(f"Stream {identifier}: release_stream via ORM failed: {e}")

    if not m3u_profile_id:
        logger.debug(f"No Channel, Stream, or profile info to release for {identifier}")
        return False

    from core.utils import RedisClient
    from apps.m3u.connection_pool import release_profile_slot
    from apps.proxy.live_proxy.redis_keys import RedisKeys

    redis_client = RedisClient.get_client()
    if not redis_client:
        return False

    if channel_pk is not None:
        redis_client.delete(RedisKeys.channel_stream(channel_pk))
    if stream_id is not None:
        redis_client.delete(RedisKeys.stream_profile(stream_id))

    release_profile_slot(int(m3u_profile_id), redis_client)
    logger.info(
        f"Released profile slot {m3u_profile_id} for {identifier} via relay metadata"
    )
    return True
