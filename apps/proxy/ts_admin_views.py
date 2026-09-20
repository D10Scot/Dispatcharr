"""The five IsAdmin control views the admin Stats UI drives.

Moved here from apps/proxy/live_proxy/views.py by Phase 2 stage 2d-2,
unchanged: the same URLs, the same URL-pattern names, the same permission
class, the same methods, the same bodies and the same JSON. Nothing about
what they do moved -- only where they live.

They are Django's side of the relay boundary: every one of them is a thin
wrapper over apps/proxy/relay_client.py, and every one of them already runs
in the API process rather than the relay (docker/nginx.conf's
`location = /proxy/ts/status` and `location ^~ /proxy/`, both uwsgi_pass to
the API socket; only `^~ /proxy/ts/stream/` is relay-bound). Stage 2d-4
deletes apps/proxy/live_proxy/ and this surface has to survive it, which is
the whole reason for the move.

The two remaining live_proxy references are function-local on purpose and
are named in the stage 2d-4 dependency list: ProxyServer, for worker_id,
inside change_stream and next_stream.
"""

import json
import logging

from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes

from apps.accounts.permissions import IsAdmin
from apps.proxy.next_source import get_stream_object
from core.utils import send_websocket_update
from dispatcharr.utils import redact_url

# The same logger name these five lines log to today. views.py builds it
# with live_proxy/utils.py's get_logger(), which derives "live_proxy" plus
# the calling module's basename -- "live_proxy.views" for all five. Naming
# it literally here is apps/proxy/next_source.py:34-38's precedent applied
# one level down: that module took "live_proxy" rather than reintroduce the
# import, "so every moved line still logs to the stream it logs to today."
# Renaming it once the directory behind the name is gone is 2d-6's.
logger = logging.getLogger("live_proxy.views")


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def change_stream(request, channel_id):
    """Change stream URL for existing channel with enhanced diagnostics"""
    # Function-local, in this module's own idiom (D10) and for the reason
    # 2d-2 exists: ProxyServer lives in the package 2d-4 deletes, this
    # module survives it, and a module-level import here would be a tenth
    # boot-trap site (Amendment A10.3) in a surviving file. worker_id --
    # hostname:pid, server.py:96-98 -- is the only thing these two views
    # want from it, and it is in both of their response bodies. Called
    # here rather than lazily at the two bodies that read it so the
    # singleton is constructed at exactly the point it is today.
    from apps.proxy.live_proxy.server import ProxyServer

    proxy_server = ProxyServer.get_instance()
    from apps.proxy import relay_client

    try:
        data = json.loads(request.body)
        new_url = data.get("url")
        user_agent = data.get("user_agent")
        stream_id = data.get("stream_id")
        m3u_profile_id = None
        stream_name = None
        channel_name = None
        m3u_profile_name = None
        transcode = False
        stream_profile = None
        ffmpeg_stream_profile = None

        # Coerce at the boundary: the Stats card's Select yields a string id
        # and, in the split deployment, this travels to the relay as JSON
        # and lands in tried_stream_ids/current_stream_id, which
        # _try_next_stream later sorts alongside int ids from Django --
        # sorted({int, str}) raises TypeError and tears the channel down on
        # the next automatic failover (Phase 1 PR 6 fix wave B, final-review
        # Blocking finding). Reject a non-integer here instead of failing
        # later, opaquely, in the relay's main loop.
        if stream_id is not None:
            try:
                stream_id = int(stream_id)
            except (TypeError, ValueError):
                return JsonResponse(
                    {"error": "stream_id must be an integer"}, status=400
                )

        # If stream_id is provided, get the URL and user_agent from it
        if stream_id:
            logger.info(
                f"Stream ID {stream_id} provided, looking up stream info for channel {channel_id}"
            )
            # Resolved here, in the API process, where the ORM is (ruling
            # 11); the result is applied on the relay via
            # relay_client.advance() below.
            from apps.proxy.next_source import resolve_source

            answer = resolve_source(channel_id, target_stream_id=stream_id, reason="operator")
            stream_info = answer["source"] or {"error": answer["error"]}

            if "error" in stream_info:
                return JsonResponse(
                    {"error": stream_info["error"], "stream_id": stream_id}, status=404
                )

            # Use the info from the stream
            new_url = stream_info["url"]
            user_agent = stream_info["user_agent"]
            m3u_profile_id = stream_info.get("m3u_profile_id")
            # Phase 2 PR 2b-1: the Source carries the names now. Before this
            # PR the key did not exist, so this was always None and the relay
            # re-resolved the name by primary key
            # (services/channel_service.py:911).
            stream_name = stream_info.get("stream_name")
            channel_name = stream_info.get("channel_name")
            m3u_profile_name = stream_info.get("m3u_profile_name")
            # Phase 2 PR 2c-8: the Go relay builds no command line, so the
            # profile Django resolved travels with the source.
            transcode = stream_info.get("transcode", False)
            stream_profile = stream_info.get("stream_profile")
            ffmpeg_stream_profile = stream_info.get("ffmpeg_stream_profile")
        elif not new_url:
            return JsonResponse(
                {"error": "Either url or stream_id must be provided"}, status=400
            )

        if not stream_id:
            # A bare url with no stream_id: nothing resolved a Stream row, so
            # the profile is the CHANNEL's own -- which is what the Python
            # relay uses on this path too, since StreamManager keeps its own
            # across update_url. Built here because the Go relay builds no
            # command line (Phase 2 PR 2c-8, Amendment A4.1).
            from apps.proxy.next_source import channel_stream_profile_ref

            try:
                channel = get_stream_object(channel_id)
            except Http404:
                # Best-effort enrichment of a call that did no DB lookup at
                # all before 2c-8. An identifier that names no row leaves the
                # three fields unset, exactly as they were, and the Go relay
                # answers 400 because it genuinely cannot spawn without an
                # argv -- honest, and not a new 404 on a path that never had
                # one.
                channel = None
            if channel is not None:
                transcode, stream_profile, ffmpeg_stream_profile = (
                    channel_stream_profile_ref(
                        channel, url=new_url, user_agent=user_agent
                    )
                )

        logger.info(
            f"Attempting to change stream for channel {channel_id} to {redact_url(new_url)}"
        )

        # Phase 1 PR 7: the switch is applied by the relay, which is the
        # process that holds the StreamManager. reset_tried carries the
        # tried_stream_ids clear that used to happen here -- PR 4's
        # routing moved this view to the API process, where
        # proxy_server.stream_managers is always empty, so the reset had
        # silently stopped happening.
        result = relay_client.advance(
            channel_id,
            url=new_url,
            user_agent=user_agent,
            stream_id=stream_id,
            m3u_profile_id=m3u_profile_id,
            stream_name=stream_name,
            channel_name=channel_name,
            m3u_profile_name=m3u_profile_name,
            reset_tried=True,
            transcode=transcode,
            stream_profile=stream_profile,
            ffmpeg_stream_profile=ffmpeg_stream_profile,
        )

        if result.get("status") == "error":
            return JsonResponse(
                {
                    "error": result.get("message", "Unknown error"),
                    "diagnostics": result.get("diagnostics", {}),
                },
                status=404,
            )

        if result.get("success") is False:
            error_data = {
                "error": result.get("message", result.get("error", "Stream switch failed")),
                "channel": channel_id,
                "url": new_url,
                "owner": result.get("direct_update", False),
                "worker_id": proxy_server.worker_id,
            }
            if stream_id:
                error_data["stream_id"] = stream_id
            # confirmed=False means owner never responded (504); owner reported failure (502)
            status_code = 504 if result.get("confirmed") is False else 502
            return JsonResponse(error_data, status=status_code)

        # Format response based on whether it was a direct update or event-based
        response_data = {
            "message": "Stream changed successfully",
            "channel": channel_id,
            "url": new_url,
            "owner": result.get("direct_update", False),
            "worker_id": proxy_server.worker_id,
        }

        # Include stream_id in response if it was used
        if stream_id:
            response_data["stream_id"] = stream_id

        return JsonResponse(response_data)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the change_stream request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for change_stream: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        # A response body is not the place for validated_base_url()'s
        # message (it already redacted, but redacted still is not
        # nothing) or for the value it blames -- only the fixed string
        # below crosses the wire. The variable responsible goes to the
        # log only.
        logger.error(
            "Relay configuration error for change_stream: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to change stream: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([IsAdmin])
def channel_status(request, channel_id=None):
    """
    Returns status information about channels with detail level based on request:
    - /status/ returns basic summary of all channels
    - /status/{channel_id} returns detailed info about specific channel

    Phase 1 PR 7: the answer comes from the relay over
    GET /proxy/relay/channels[/<id>] rather than from this process's own
    Redis reads. The URL, the IsAdmin gate and the JSON are unchanged;
    the two new statuses below exist because "the relay did not answer"
    is a thing that can now happen and 500 would say nothing useful.
    """
    # Function-local (D10): this module also hosts stream_ts and
    # stream_xc, which run in the relay process, and relay_client is
    # Django's side of that boundary.
    from apps.proxy import relay_client

    try:
        if channel_id:
            channel_info = relay_client.get_channel(channel_id)
            if channel_info is None:
                return JsonResponse(
                    {"error": f"Channel {channel_id} not found"}, status=404
                )
            return JsonResponse(channel_info)

        live_stats = relay_client.list_channels()

        # Send WebSocket update with the stats
        # Format it the same way the original Celery task did
        send_websocket_update(
            "updates",
            "update",
            {
                "success": True,
                "type": "channel_stats",
                "stats": json.dumps(live_stats),
            }
        )

        return JsonResponse(live_stats)

    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused a status request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for status: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for channel_status: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Error in channel_status: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        close_old_connections()


@csrf_exempt
@api_view(["POST", "DELETE"])
@permission_classes([IsAdmin])
def stop_channel(request, channel_id):
    """Stop a channel and release all associated resources using PubSub events"""
    from apps.proxy import relay_client

    try:
        logger.info(f"Request to stop channel {channel_id} received")

        result = relay_client.stop_channel(channel_id)

        if result.get("status") == "error":
            return JsonResponse(
                {"error": result.get("message", "Unknown error")}, status=404
            )

        return JsonResponse(
            {
                "message": "Channel stop request sent",
                "channel_id": channel_id,
                "previous_state": result.get("previous_state"),
            }
        )

    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the stop request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for the stop request: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for stop_channel: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to stop channel: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def stop_client(request, channel_id):
    """Stop a specific client connection using existing client management"""
    from apps.proxy import relay_client

    try:
        # Parse request body to get client ID
        data = json.loads(request.body)
        client_id = data.get("client_id")

        if not client_id:
            return JsonResponse({"error": "No client_id provided"}, status=400)

        result = relay_client.stop_client(channel_id, client_id)

        if result.get("status") == "error":
            return JsonResponse({"error": result.get("message")}, status=404)

        return JsonResponse(
            {
                "message": "Client stop request processed",
                "channel_id": channel_id,
                "client_id": client_id,
                "locally_processed": result.get("locally_processed", False),
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the stop request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for the stop request: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for stop_client: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to stop client: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def next_stream(request, channel_id):
    """Switch to the next available stream for a channel"""
    # Function-local: see change_stream above.
    from apps.proxy.live_proxy.server import ProxyServer

    proxy_server = ProxyServer.get_instance()
    from apps.proxy import relay_client

    try:
        logger.info(
            f"Request to switch to next stream for channel {channel_id} received"
        )

        # Check if the channel exists
        channel = get_stream_object(channel_id)

        # Phase 1 PR 7: what is playing now comes from the relay, which
        # owns the metadata hash. This view runs in the API process after
        # PR 4's routing, so reading live:channel:<id>:metadata here was
        # the control plane reading a relay key -- invisible to the
        # spec's Done grep, which covers apps/channels, apps/m3u, core
        # and dispatcharr, and exactly what this PR removes.
        running = relay_client.get_channel(channel_id)
        current_stream_id = (running or {}).get("stream_id")
        profile_id = (running or {}).get("m3u_profile_id")
        if current_stream_id:
            logger.info(
                f"Found current stream ID {current_stream_id} from the relay for channel {channel_id}"
            )
            if profile_id:
                logger.info(
                    f"Found M3U profile ID {profile_id} from the relay for channel {channel_id}"
                )

        if not current_stream_id:
            # Channel is not running
            return JsonResponse(
                {"error": "No current stream found for channel"}, status=404
            )

        # Get all streams for this channel in their defined order
        streams = list(channel.streams.all().order_by("channelstream__order"))

        if len(streams) <= 1:
            return JsonResponse(
                {
                    "error": "No alternate streams available for this channel",
                    "current_stream_id": current_stream_id,
                },
                status=404,
            )

        # Find the current stream's position in the list
        current_index = None
        for i, stream in enumerate(streams):
            if stream.id == current_stream_id:
                current_index = i
                break

        if current_index is None:
            logger.warning(
                f"Current stream ID {current_stream_id} not found in channel's streams list"
            )
            # Fall back to the first stream that's not the current one
            next_stream = next((s for s in streams if s.id != current_stream_id), None)
            if not next_stream:
                return JsonResponse(
                    {
                        "error": "Could not find current stream in channel list",
                        "current_stream_id": current_stream_id,
                    },
                    status=404,
                )
        else:
            # Get the next stream in the rotation (with wrap-around)
            next_index = (current_index + 1) % len(streams)
            next_stream = streams[next_index]

        next_stream_id = next_stream.id
        logger.info(
            f"Rotating to next stream ID {next_stream_id} for channel {channel_id}"
        )

        # Get full stream info including URL for the next stream. Resolved
        # here, in the API process, where the ORM is; the result is
        # applied on the relay via relay_client.advance() below.
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(channel_id, target_stream_id=next_stream_id, reason="operator")
        stream_info = answer["source"] or {"error": answer["error"]}

        if "error" in stream_info:
            return JsonResponse(
                {
                    "error": stream_info["error"],
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                },
                status=404,
            )

        # Now apply the switch on the relay. reset_tried is deliberately
        # absent: next_stream has never cleared tried_stream_ids, and
        # rotating to the next stream is what the exclusion list is for.
        result = relay_client.advance(
            channel_id,
            url=stream_info["url"],
            user_agent=stream_info["user_agent"],
            stream_id=next_stream_id,
            m3u_profile_id=stream_info.get("m3u_profile_id"),
            # Phase 2 PR 2b-1: the Source carries the names now. Before this
            # PR the key did not exist, so this was always None and the relay
            # re-resolved the name by primary key
            # (services/channel_service.py:911).
            stream_name=stream_info.get("stream_name"),
            channel_name=stream_info.get("channel_name"),
            m3u_profile_name=stream_info.get("m3u_profile_name"),
            # Phase 2 PR 2c-8: the Go relay builds no command line, so the
            # profile Django resolved travels with the source.
            transcode=stream_info.get("transcode", False),
            stream_profile=stream_info.get("stream_profile"),
            ffmpeg_stream_profile=stream_info.get("ffmpeg_stream_profile"),
        )

        if result.get("status") == "error":
            return JsonResponse(
                {
                    "error": result.get("message", "Unknown error"),
                    "diagnostics": result.get("diagnostics", {}),
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                },
                status=404,
            )

        if result.get("success") is False:
            return JsonResponse(
                {
                    "error": result.get("message", result.get("error", "Stream switch failed")),
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                    "owner": result.get("direct_update", False),
                    "worker_id": proxy_server.worker_id,
                },
                status=504 if result.get("confirmed") is False else 502,
            )

        # Format success response
        response_data = {
            "message": "Stream switched to next available",
            "channel": channel_id,
            "previous_stream_id": current_stream_id,
            "new_stream_id": next_stream_id,
            "new_url": stream_info["url"],
            "owner": result.get("direct_update", False),
            "worker_id": proxy_server.worker_id,
        }

        return JsonResponse(response_data)

    except Http404:
        raise
    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the next_stream request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for next_stream: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for next_stream: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to switch to next stream: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        close_old_connections()
