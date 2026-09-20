import json
import time
import re
import pathlib
from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections
from django.http import (
    StreamingHttpResponse,
    JsonResponse,
    HttpResponseRedirect,
    HttpResponse,
    Http404,
)
from django.views.decorators.csrf import csrf_exempt
from .server import ProxyServer
from .output.ts.generator import create_stream_generator
from .output.fmp4.generator import create_fmp4_stream_generator
from dispatcharr.utils import get_client_ip, redact_url
from .redis_keys import RedisKeys
from core.models import CoreSettings, PROXY_PROFILE_NAME
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from apps.accounts.permissions import (
    IsAdmin,
    permission_classes_by_method,
    permission_classes_by_action,
)
from .constants import ChannelState, ChannelMetadataField
from .services.channel_service import ChannelService
from core.utils import send_websocket_update
from .url_utils import (
    generate_stream_url,
    get_stream_object,
    tune_extras as build_tune_extras,
)
from .utils import get_logger
from uuid import UUID
import gevent
from apps.proxy.authorize import (
    SURFACE_LIVE,
    SURFACE_LIVE_XC,
    AuthorizeDenied,
    mint_client_id,
    resolve_output_profile,
)
from apps.proxy.authorize_views import authorize_error_response, resolve_authorization

logger = get_logger()


def _channel_stopping_response():
    response = JsonResponse(
        {"error": "Channel is stopping, retry shortly"},
        status=503,
    )
    response["Retry-After"] = "1"
    return response


def _channel_setup_needed(proxy_server, channel_id):
    """
    Decide whether this worker still needs to run full channel setup.

    Returns (needs_setup, state, wait_for_init).
    """
    state = None
    if proxy_server.redis_client:
        metadata = proxy_server.redis_client.hgetall(RedisKeys.channel_metadata(channel_id))
        if metadata:
            state = metadata.get(ChannelMetadataField.STATE)
            if state in (
                ChannelState.ACTIVE,
                ChannelState.WAITING_FOR_CLIENTS,
                ChannelState.BUFFERING,
                ChannelState.INITIALIZING,
                ChannelState.CONNECTING,
            ):
                wait_for_init = state in (
                    ChannelState.INITIALIZING,
                    ChannelState.CONNECTING,
                )
                return False, state, wait_for_init
            if state == ChannelState.STOPPING:
                return False, state, False
            if state in (ChannelState.ERROR, ChannelState.STOPPED):
                return True, state, False

            # Unknown/empty state: trust a live owner worker, otherwise re-setup
            owner = metadata.get(ChannelMetadataField.OWNER)
            if owner:
                owner_heartbeat_key = f"live:worker:{owner}:heartbeat"
                if proxy_server.redis_client.exists(owner_heartbeat_key):
                    return False, state, False
                return True, state, False

    if proxy_server.check_if_channel_exists(channel_id):
        return False, state, False

    return True, state, False


def _drop_pre_registered_client(proxy_server, channel_id, client_id):
    """Undo an early add_client() when setup aborts before streaming starts."""
    mgr = proxy_server.client_managers.get(channel_id)
    if mgr:
        mgr.remove_client(client_id)
        return
    if not proxy_server.redis_client:
        return
    proxy_server.redis_client.srem(RedisKeys.clients(channel_id), client_id)
    proxy_server.redis_client.delete(RedisKeys.client_metadata(channel_id, client_id))


def _resolve_output_format(user, force=None, request=None, decision=None):
    """Return the output format string to use for this client.

    The rule itself lives in apps/proxy/authorize.py (2b-2), so the hop
    and the inline path cannot drift. When nginx authorized the tune, the
    hop already applied it and the answer is on X-Relay-Output-Format --
    reading it here is what removes the User query
    authorize_views.result_from_headers used to run on every trusted tune.

    `force` still wins: it is stream_xc's extension-derived override
    (.ts/.mp4), a property of this call and not of the decision, so the
    hop never saw it.
    """
    from apps.proxy.authorize import resolve_output_format

    if force:
        return force
    if decision is not None and decision.trusted:
        return decision.output_format or CoreSettings.get_default_output_format()
    return resolve_output_format(request, user, force=None)


def _output_profile_for(decision, request, user):
    """The Output Profile this tune runs under.

    When nginx authorized the request, Django already applied the rule
    (?output_profile= then the user's custom_properties) and put the id
    in X-Relay-Output; the row is re-read here because
    OutputProfile.build_command() is model behaviour the relay needs and
    a header cannot carry a built ffmpeg command. Without a trusted
    marker — dev runserver, or any request that did not come through a
    relay-bound location — the same rule runs inline.
    """
    from core.models import OutputProfile

    if decision is not None and decision.trusted:
        if not decision.output_profile_id:
            return None
        return OutputProfile.objects.filter(
            id=decision.output_profile_id, is_active=True
        ).first()
    return resolve_output_profile(request, user)


@api_view(["GET"])
@permission_classes([AllowAny])
def stream_ts(request, channel_id, user=None, force_output_format=None, decision=None):
    """Stream TS data to client with immediate response and keep-alive packets during initialization"""
    if decision is None:
        # `decision` is supplied only by stream_xc, which authorized this
        # same tune under its own surface a moment ago; re-running the hop
        # would re-check a limit that has not changed and mint a second
        # client id.
        try:
            decision = resolve_authorization(
                request, SURFACE_LIVE, identifier=channel_id
            )
        except AuthorizeDenied as exc:
            return authorize_error_response(exc)
    if user is None:
        user = decision.user

    from apps.proxy import control_plane

    client_user_agent = None
    proxy_server = ProxyServer.get_instance()
    connection_allocated = False  # Track if connection slot was allocated via get_stream()
    # Initialized before the try so the exception handler can always safely
    # check/clean it up, regardless of where in the setup a failure occurs.
    _client_pre_registered = False
    channel = None
    client_id = None
    channel_display_name = None

    try:
        channel = get_stream_object(channel_id)
        channel_display_name = getattr(channel, "name", None)

        # Minted by the authorize hop (apps/proxy/authorize.py), so the id
        # nginx put in X-Relay-Client is the id this worker registers.
        client_id = decision.client_id or mint_client_id()
        # 2b-2 / parity-matrix row 17. The hop resolved this once with
        # get_client_ip's trusted-proxy rules (LOCAL_NETWORK_CIDRS /
        # DISPATCHARR_TRUSTED_PROXIES); reading it back is what lets a
        # relay behind proxy_pass -- which sees nginx as its peer, not
        # the viewer -- report the real address. Untrusted (dev
        # runserver, any request that did not come through a relay-bound
        # location) resolves it here exactly as before.
        client_ip = (
            decision.client_ip
            if decision is not None and decision.trusted and decision.client_ip
            else get_client_ip(request)
        )
        logger.info(f"[{client_id}] Requested stream for channel {channel_id}")

        # Extract client user agent early
        for header in ["HTTP_USER_AGENT", "User-Agent", "user-agent"]:
            if header in request.META:
                client_user_agent = request.META[header]
                logger.debug(
                    f"[{client_id}] Client connected with user agent: {client_user_agent}"
                )
                break

        if ChannelService.is_channel_unavailable_for_new_clients(channel_id):
            logger.info(
                f"[{client_id}] Channel {channel_id} unavailable. Teardown or pending shutdown"
            )
            return _channel_stopping_response()

        # Check if we need to reinitialize the channel
        needs_initialization, channel_state, channel_initializing = _channel_setup_needed(
            proxy_server, channel_id
        )
        if channel_state == ChannelState.STOPPING:
            logger.info(
                f"[{client_id}] Channel {channel_id} is stopping, rejecting request"
            )
            return _channel_stopping_response()
        if channel_initializing:
            logger.debug(
                f"[{client_id}] Channel {channel_id} is still initializing, client will wait"
            )
        elif not needs_initialization:
            logger.debug(
                f"[{client_id}] Channel {channel_id} in state {channel_state}, skipping initialization"
            )
        elif channel_state in (ChannelState.ERROR, ChannelState.STOPPED):
            logger.info(
                f"[{client_id}] Channel {channel_id} in terminal state {channel_state}, will reinitialize"
            )

        resolved_output_profile = None
        resolved_output_format = None
        output_options_resolved = False

        # Start initialization if needed
        if needs_initialization:
            if ChannelService.is_channel_unavailable_for_new_clients(channel_id):
                logger.info(
                    f"[{client_id}] Channel {channel_id} became unavailable before init, rejecting"
                )
                return _channel_stopping_response()

            logger.info(f"[{client_id}] Starting channel {channel_id} initialization")
            # Force cleanup of any previous instance if in terminal state
            if channel_state in [
                ChannelState.ERROR,
                ChannelState.STOPPING,
                ChannelState.STOPPED,
            ]:
                logger.warning(
                    f"[{client_id}] Channel {channel_id} in state {channel_state}, forcing cleanup"
                )
                ChannelService.stop_channel(channel_id)

            perform_setup = False
            owned_for_init = False
            init_lock = proxy_server._get_channel_init_lock(channel_id)
            init_lock.acquire()
            try:
                needs_setup, channel_state, wait_for_init = _channel_setup_needed(
                    proxy_server, channel_id
                )
                if channel_state == ChannelState.STOPPING or (
                    ChannelService.is_channel_unavailable_for_new_clients(channel_id)
                ):
                    logger.info(
                        f"[{client_id}] Channel {channel_id} unavailable after init lock, rejecting"
                    )
                    return _channel_stopping_response()

                if not needs_setup:
                    if wait_for_init:
                        channel_initializing = True
                    logger.info(
                        f"[{client_id}] Channel {channel_id} already set up after init lock "
                        f"(state={channel_state}), attaching as follower"
                    )
                elif channel_id in proxy_server._channels_setting_up:
                    channel_initializing = True
                    logger.info(
                        f"[{client_id}] Channel {channel_id} setup already in progress on this "
                        f"worker, skipping stream reservation and attaching as follower"
                    )
                elif not proxy_server.try_acquire_ownership(channel_id):
                    channel_initializing = True
                    logger.info(
                        f"[{client_id}] Channel {channel_id} owned by another worker, "
                        f"skipping stream reservation and attaching as follower"
                    )
                else:
                    owned_for_init = True
                    proxy_server._channels_setting_up.add(channel_id)
                    perform_setup = True
            finally:
                proxy_server._finish_channel_init_lock(channel_id, init_lock)

            if perform_setup:
                try:
                    # Use fixed retry interval and timeout
                    retry_timeout = 3  # 3 seconds total timeout
                    retry_interval = 0.1  # 100ms between attempts
                    wait_start_time = time.time()

                    stream_url = None
                    stream_user_agent = None
                    transcode = False
                    profile_value = None
                    slot_reserved = False
                    error_reason = None
                    tune_extras = build_tune_extras(None)
                    attempt = 0
                    should_retry = True

                    # Try to get a stream with fixed interval retries
                    while should_retry and time.time() - wait_start_time < retry_timeout:
                        attempt += 1
                        (
                            stream_url,
                            stream_user_agent,
                            transcode,
                            profile_value,
                            slot_reserved,
                            error_reason,
                            tune_extras,
                        ) = generate_stream_url(channel_id)

                        if stream_url is not None:
                            logger.info(
                                f"[{client_id}] Successfully obtained stream for channel {channel_id} after {attempt} attempts"
                            )
                            break

                        # On first failure, check if the error is retryable
                        if attempt == 1:
                            if error_reason and "maximum connection limits" not in error_reason:
                                logger.warning(
                                    f"[{client_id}] Can't retry - error not related to connection limits: {error_reason}"
                                )
                                should_retry = False
                                break

                        # Check if we have time remaining for another sleep cycle
                        elapsed_time = time.time() - wait_start_time
                        remaining_time = retry_timeout - elapsed_time

                        # If we don't have enough time for the next sleep interval, break
                        # but only after we've already made an attempt (the while condition will try one more time)
                        if remaining_time <= retry_interval:
                            logger.info(
                                f"[{client_id}] Insufficient time ({remaining_time:.1f}s) for another sleep cycle, will make one final attempt"
                            )
                            break

                        # Wait before retrying
                        logger.info(
                            f"[{client_id}] Waiting {retry_interval*1000:.0f}ms for a connection to become available (attempt {attempt}, {remaining_time:.1f}s remaining)"
                        )
                        gevent.sleep(retry_interval)
                        retry_interval += 0.025  # Increase wait time by 25ms for next attempt

                    # Make one final attempt if we still don't have a stream, should retry, and haven't exceeded timeout
                    if stream_url is None and should_retry and time.time() - wait_start_time < retry_timeout:
                        attempt += 1
                        logger.info(
                            f"[{client_id}] Making final attempt {attempt} at timeout boundary"
                        )
                        (
                            stream_url,
                            stream_user_agent,
                            transcode,
                            profile_value,
                            slot_reserved,
                            error_reason,
                            tune_extras,
                        ) = generate_stream_url(channel_id)
                        if stream_url is not None:
                            logger.info(
                                f"[{client_id}] Successfully obtained stream on final attempt for channel {channel_id}"
                            )

                    if stream_url is None:
                        if slot_reserved:
                            try:
                                released = control_plane.release_source(channel_id)
                            except (control_plane.ControlPlaneRefused, control_plane.ControlPlaneUnavailable) as exc:
                                logger.warning(f"Could not release the slot for {channel_id}: {exc}")
                                released = False
                            if not released:
                                logger.debug(f"[{client_id}] release_stream found no keys during failed init cleanup")

                        # Get the specific error message if available
                        wait_duration = f"{int(time.time() - wait_start_time)}s"
                        error_msg = (
                            error_reason
                            if error_reason
                            else "No available streams for this channel"
                        )
                        logger.info(
                            f"[{client_id}] Failed to obtain stream after {attempt} attempts over {wait_duration}: {error_msg}"
                        )
                        return JsonResponse(
                            {"error": error_msg, "waited": wait_duration}, status=503
                        )  # 503 Service Unavailable is appropriate here

                    # generate_stream_url() asked Django (control_plane.next_source),
                    # which called get_stream() and allocated a connection slot
                    # (INCR'd profile_connections) - track this for cleanup on error
                    if needs_initialization and slot_reserved:
                        connection_allocated = True

                    # Read stream assignment from Redis (already set by Django's
                    # next-source answer, via Channel.get_stream()).
                    # Avoid asking again (INCR profile counter)
                    # It could double-allocate if the keys were cleared by a concurrent release.
                    stream_id = None
                    m3u_profile_id = None
                    if proxy_server.redis_client:
                        stream_id_bytes = proxy_server.redis_client.get(RedisKeys.channel_stream(channel.id))
                        if stream_id_bytes:
                            stream_id = int(stream_id_bytes)
                            profile_id_bytes = proxy_server.redis_client.get(RedisKeys.stream_profile(stream_id))
                            if profile_id_bytes:
                                m3u_profile_id = int(profile_id_bytes)
                    logger.info(
                        f"Channel {channel_id} using stream ID {stream_id}, m3u account profile ID {m3u_profile_id}"
                    )

                    # Generate transcode command if needed
                    stream_profile = channel.get_stream_profile()
                    # Phase 1 PR 5: the relay never redirects an internal
                    # principal (the DVR) to a third-party provider. ffmpeg
                    # re-sends every `-headers` line to the redirect target
                    # on the new host, so a 302 here would hand the provider
                    # (and its access logs) a credential — X-Dispatcharr-
                    # Internal — that is otherwise never supposed to leave
                    # this deployment. Serve it through the Proxy path
                    # instead: server bandwidth is unchanged (the DVR runs
                    # server-side either way, whether ffmpeg reads the
                    # provider directly or the ring buffer), and the
                    # recording gains failover it didn't have. `transcode`
                    # was computed above from the channel's real (Redirect)
                    # profile and must be forced False here, or the
                    # Redirect profile's empty build_command() would be
                    # used to spawn a subprocess.
                    # The decision already resolved this; issue #181.
                    internal_principal = decision.is_internal
                    if stream_profile.is_redirect() and internal_principal:
                        logger.info(
                            f"[{client_id}] Internal principal on a Redirect-profile "
                            f"channel — serving via Proxy instead of a redirect"
                        )
                        transcode = False
                    elif stream_profile.is_redirect():
                        # Phase 1 PR 6: the alternates were resolved by
                        # Django on the next-source call a few lines above
                        # and cached in Redis; the relay no longer
                        # re-queries for them. Validation of each URL stays
                        # here, because it is an HTTP probe of the
                        # provider, not a database question.
                        from .url_utils import validate_stream_url, read_cached_alternates

                        # Try initial URL
                        logger.info(f"[{client_id}] Validating redirect URL: {redact_url(stream_url)}")
                        is_valid, final_url, status_code, message = validate_stream_url(
                            stream_url, user_agent=stream_user_agent, timeout=(5, 5)
                        )

                        # If first URL doesn't validate, try alternates
                        if not is_valid:
                            logger.warning(
                                f"[{client_id}] Primary stream URL failed validation: {message}"
                            )

                            # Track tried streams to avoid loops
                            tried_streams = {stream_id}

                            for alt in read_cached_alternates(channel_id):
                                if alt["stream_id"] in tried_streams:
                                    continue

                                tried_streams.add(alt["stream_id"])

                                logger.info(
                                    f"[{client_id}] Trying alternate stream #{alt['stream_id']}"
                                )
                                is_valid, final_url, status_code, message = validate_stream_url(
                                    alt["url"],
                                    user_agent=alt["user_agent"],
                                    timeout=(5, 5),
                                )

                                if is_valid:
                                    logger.info(
                                        f"[{client_id}] Alternate stream #{alt['stream_id']} validated successfully"
                                    )
                                    break
                                else:
                                    logger.warning(
                                        f"[{client_id}] Alternate stream #{alt['stream_id']} failed validation: {message}"
                                    )
                        # Release stream lock before redirecting only if we reserved a slot
                        if connection_allocated:
                            try:
                                released = control_plane.release_source(channel_id)
                            except (control_plane.ControlPlaneRefused, control_plane.ControlPlaneUnavailable) as exc:
                                logger.warning(f"Could not release the slot for {channel_id}: {exc}")
                                released = False
                            if not released:
                                logger.warning(f"[{client_id}] Failed to release stream before redirect")
                        connection_allocated = False
                        # Final decision based on validation results
                        if is_valid:
                            logger.info(
                                f"[{client_id}] Redirecting to validated URL: {redact_url(final_url)} ({message})"
                            )

                            # For non-HTTP protocols (RTSP/RTP/UDP), we need to manually create the redirect
                            # because Django's HttpResponseRedirect blocks them for security
                            if final_url.startswith(('rtsp://', 'rtp://', 'udp://')):
                                logger.info(f"[{client_id}] Using manual redirect for non-HTTP protocol")
                                response = HttpResponse(status=301)
                                response['Location'] = final_url
                                return response

                            return HttpResponseRedirect(final_url)
                        else:
                            logger.error(
                                f"[{client_id}] All available redirect URLs failed validation"
                            )
                            return JsonResponse(
                                {"error": "All available streams failed validation"}, status=502
                            )  # 502 Bad Gateway

                    # Initialize channel with the stream's user agent (not the client's)
                    if ChannelService.is_channel_unavailable_for_new_clients(channel_id):
                        if connection_allocated:
                            try:
                                released = control_plane.release_source(channel_id)
                            except (control_plane.ControlPlaneRefused, control_plane.ControlPlaneUnavailable) as exc:
                                logger.warning(f"Could not release the slot for {channel_id}: {exc}")
                                released = False
                            if not released:
                                logger.warning(f"[{client_id}] Failed to release stream before teardown reject")
                            connection_allocated = False
                        logger.info(
                            f"[{client_id}] Channel {channel_id} unavailable before init call, rejecting"
                        )
                        return _channel_stopping_response()

                    # channel_name has an or-fallback because `channel` (a
                    # Channel row, or a Stream row for the /<stream_hash>
                    # preview case) is already fetched locally regardless of
                    # Django's version. stream_name has no equivalent: it
                    # names a specific Stream selected by stream_id, not a
                    # property of the object already in hand, so a pre-2b-1
                    # Django (tune_extras() -> all-None, url_utils.py:41) or
                    # any other cause of a None here writes no STREAM_NAME
                    # into the metadata hash at init. Not unrecoverable --
                    # channel_status.py:74's ORM-by-stream_id fallback (keyed
                    # off stream_id, independent of tune_extras) repairs it
                    # on every status poll -- see the PR's "degrade story"
                    # section for the repeated-query cost that implies.
                    success = ChannelService.initialize_channel(
                        channel_id,
                        stream_url,
                        stream_user_agent,
                        transcode,
                        profile_value,
                        stream_id,
                        m3u_profile_id,
                        channel_name=tune_extras["channel_name"] or channel.name,
                        stream_name=tune_extras["stream_name"],
                        m3u_profile_name=tune_extras["m3u_profile_name"],
                        ffmpeg_stream_profile=tune_extras["ffmpeg_stream_profile"],
                    )

                    if not success:
                        if connection_allocated:
                            try:
                                released = control_plane.release_source(channel_id)
                            except (control_plane.ControlPlaneRefused, control_plane.ControlPlaneUnavailable) as exc:
                                logger.warning(f"Could not release the slot for {channel_id}: {exc}")
                                released = False
                            if not released:
                                logger.warning(f"[{client_id}] Failed to release stream after init failure")
                            connection_allocated = False
                        return JsonResponse(
                            {"error": "Failed to initialize channel"}, status=500
                        )

                    # Channel initialized: lifecycle owns the connection and ownership lock
                    connection_allocated = False
                    owned_for_init = False

                    # If we're the owner, register the client now so the watchdog
                    # doesn't stop the channel during connection (which can take
                    # longer than the grace period). The generator handles waiting
                    # with keepalive packets via _wait_for_initialization().
                    if proxy_server.am_i_owner(channel_id):
                        resolved_output_profile = _output_profile_for(decision, request, user)
                        resolved_output_format = _resolve_output_format(
                            user, force_output_format, request, decision=decision
                        )
                        output_options_resolved = True
                        resolved_format = (
                            f'{resolved_output_format}:p{resolved_output_profile.id}'
                            if resolved_output_profile else resolved_output_format
                        )
                        client_manager = proxy_server.client_managers[channel_id]
                        if not client_manager.add_client(
                            client_id, client_ip, client_user_agent, user,
                            user_id=decision.user_id if decision is not None else None,
                            output_format=resolved_output_format,
                            output_profile_id=resolved_output_profile.id if resolved_output_profile else None,
                        ):
                            logger.error(
                                f"[{client_id}] Failed to register client with channel {channel_id} during init"
                            )
                            return JsonResponse(
                                {"error": "Failed to register client"}, status=503
                            )
                        logger.info(
                            f"[{client_id}] Client registered with channel {channel_id} "
                            f"(output: {resolved_format}, profile: {resolved_output_profile.id if resolved_output_profile else None})"
                        )
                        _client_pre_registered = True

                    logger.info(f"[{client_id}] Successfully initialized channel {channel_id}")
                    channel_initializing = True
                finally:
                    proxy_server._clear_channel_setting_up(channel_id)
                    if owned_for_init:
                        proxy_server.release_ownership(channel_id, signal_stopping=False)

        # Register client - can do this regardless of initialization state
        # Create local resources if needed
        if (
            channel_id not in proxy_server.stream_buffers
            or channel_id not in proxy_server.client_managers
        ):
            logger.debug(
                f"[{client_id}] Channel {channel_id} exists in Redis but not initialized in this worker - initializing now"
            )

            # Get URL from Redis metadata
            url = None
            stream_user_agent = None  # Initialize the variable

            if proxy_server.redis_client:
                metadata_key = RedisKeys.channel_metadata(channel_id)
                url_bytes, ua_bytes, profile_bytes = proxy_server.redis_client.hmget(
                    metadata_key,
                    ChannelMetadataField.URL,
                    ChannelMetadataField.USER_AGENT,
                    ChannelMetadataField.STREAM_PROFILE,
                )

                if url_bytes:
                    url = url_bytes
                if ua_bytes:
                    stream_user_agent = ua_bytes
                # Extract transcode setting from Redis
                if profile_bytes:
                    profile_str = profile_bytes
                    use_transcode = (
                        profile_str == PROXY_PROFILE_NAME or profile_str == "None"
                    )
                    logger.debug(
                        f"Using profile '{profile_str}' for channel {channel_id}, transcode={use_transcode}"
                    )
                else:
                    # Default settings when profile not found in Redis
                    profile_str = "None"  # Default profile name
                    use_transcode = (
                        False  # Default to direct streaming without transcoding
                    )
                    logger.debug(
                        f"No profile found in Redis for channel {channel_id}, defaulting to transcode={use_transcode}"
                    )

            # Use client_user_agent as fallback if stream_user_agent is None
            success = proxy_server.initialize_channel(
                url,
                channel_id,
                stream_user_agent or client_user_agent,
                use_transcode,
                channel_name=channel_display_name,
            )
            if not success:
                logger.error(
                    f"[{client_id}] Failed to initialize channel {channel_id} locally"
                )
                return JsonResponse(
                    {"error": "Failed to initialize channel locally"}, status=500
                )

            logger.info(
                f"[{client_id}] Successfully initialized channel {channel_id} locally"
            )

        if ChannelService.is_channel_unavailable_for_new_clients(channel_id):
            if _client_pre_registered:
                _drop_pre_registered_client(proxy_server, channel_id, client_id)
            logger.info(
                f"[{client_id}] Channel {channel_id} became unavailable during setup, rejecting"
            )
            return _channel_stopping_response()

        if not output_options_resolved:
            resolved_output_profile = _output_profile_for(decision, request, user)
            resolved_output_format = _resolve_output_format(
                            user, force_output_format, request, decision=decision
                        )
        # When an output profile is active, append :p{id} to the format key so each
        # (format, profile) pair gets its own independent remux pipeline in Redis.
        resolved_format = (
            f'{resolved_output_format}:p{resolved_output_profile.id}'
            if resolved_output_profile else resolved_output_format
        )

        # Pre-register before slow setup (ensure_output_profile) so the non-owner
        # cleanup thread does not tear down local resources while connecting.
        if not _client_pre_registered:
            client_manager = proxy_server.client_managers.get(channel_id)
            if not client_manager:
                logger.error(
                    f"[{client_id}] Channel {channel_id} missing client_manager during setup"
                )
                return JsonResponse(
                    {"error": "Channel resources unavailable"}, status=503
                )
            if not client_manager.add_client(
                client_id, client_ip, client_user_agent, user,
                user_id=decision.user_id if decision is not None else None,
                output_format=resolved_output_format,
                output_profile_id=resolved_output_profile.id if resolved_output_profile else None,
            ):
                logger.error(
                    f"[{client_id}] Failed to register client with channel {channel_id}"
                )
                return JsonResponse(
                    {"error": "Failed to register client"}, status=503
                )
            _client_pre_registered = True
            logger.info(
                f"[{client_id}] Client registered with channel {channel_id} "
                f"(output: {resolved_format}, profile: {resolved_output_profile.id if resolved_output_profile else None})"
            )

        if resolved_output_profile:
            cmd = resolved_output_profile.build_command()
            if not proxy_server.ensure_output_profile(channel_id, resolved_output_profile.id, cmd):
                if _client_pre_registered:
                    _drop_pre_registered_client(proxy_server, channel_id, client_id)
                return JsonResponse(
                    {"error": "Failed to start output profile transcode"}, status=500
                )

        source_buffer = proxy_server.get_buffer(
            channel_id,
            profile=resolved_output_profile.id if resolved_output_profile else None
        )
        client_manager = proxy_server.client_managers.get(channel_id)
        if not client_manager:
            if _client_pre_registered:
                _drop_pre_registered_client(proxy_server, channel_id, client_id)
            logger.error(
                f"[{client_id}] Channel {channel_id} client_manager removed during setup"
            )
            return JsonResponse(
                {"error": "Channel resources unavailable"}, status=503
            )

        if resolved_output_format == 'fmp4':
            if not proxy_server.ensure_output_format(
                channel_id, resolved_format,
                source_buffer=source_buffer if resolved_output_profile else None,
            ):
                if _client_pre_registered:
                    _drop_pre_registered_client(proxy_server, channel_id, client_id)
                return JsonResponse(
                    {"error": "Failed to start output format remux"}, status=500
                )
            generate = create_fmp4_stream_generator(
                channel_id, client_id, client_ip, client_user_agent, channel_initializing, user=user,
                user_id=decision.user_id if decision is not None else None,
                fmt=resolved_format,
                channel_name=channel_display_name,
            )
            content_type = "video/mp4"
        else:
            generate = create_stream_generator(
                channel_id,
                client_id,
                client_ip,
                client_user_agent,
                channel_initializing,
                user=user,
                user_id=decision.user_id if decision is not None else None,
                buffer=source_buffer,
                channel_name=channel_display_name,
            )
            content_type = "video/mp2t"

        response = StreamingHttpResponse(
            streaming_content=generate(), content_type=content_type
        )
        response["Cache-Control"] = "no-cache"
        return response

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error in stream_ts: {e}", exc_info=True)
        if connection_allocated and channel is not None:
            try:
                released = control_plane.release_source(channel_id)
            except (control_plane.ControlPlaneRefused, control_plane.ControlPlaneUnavailable) as exc:
                logger.warning(f"Could not release the slot for {channel_id}: {exc}")
                released = False
            if not released:
                logger.warning(f"[{client_id}] Failed to release stream in exception handler")
        # Client may have been pre-registered (before ensure_output_profile /
        # get_buffer / generator setup) to protect against the non-owner
        # cleanup thread. If setup then failed with an unhandled exception,
        # remove it so it doesn't linger as a phantom connection.
        if _client_pre_registered:
            try:
                _drop_pre_registered_client(proxy_server, channel_id, client_id)
            except Exception:
                logger.warning(f"[{client_id}] Failed to remove client during exception cleanup")
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        # Runs before StreamingHttpResponse is handed to the WSGI server, so the
        # request greenlet does not hold a pool slot for the life of the stream.
        # Also covers Http404 from get_stream_object (re-raised above).
        close_old_connections()


@api_view(["GET"])
@permission_classes([AllowAny])
def stream_xc(request, username, password, channel_id):
    try:
        extension = pathlib.Path(channel_id).suffix
        stream_id = pathlib.Path(channel_id).stem

        try:
            decision = resolve_authorization(
                request,
                SURFACE_LIVE_XC,
                identifier=stream_id,
                username=username,
                password=password,
            )
        except AuthorizeDenied as exc:
            return authorize_error_response(exc)

        if extension.lower() == '.mp4':
            force_format = 'fmp4'
        elif extension.lower() == '.ts':
            force_format = 'mpegts'
        else:
            force_format = None
        # X-Relay-Channel is the uuid the hop resolved from the numeric
        # Xtream id — the lookup that used to be a copy of the channel
        # authorization filter, applied here for the fourth time in the
        # tree.
        return stream_ts(
            request._request,
            decision.channel_uuid,
            decision.user,
            force_output_format=force_format,
            decision=decision,
        )
    except Http404:
        raise
    finally:
        # stream_ts releases on its own paths; the hop's ORM work is done
        # by the time this returns.
        close_old_connections()
