"""The relay's control API (Phase 1 PR 7, D12).

Five routes under /proxy/relay/, served by the relay process, gated by
IsInternalRelay -- the static X-Dispatcharr-Internal plus the bound
X-Dispatcharr-Internal-Request, never a principal and never IsAdmin,
which would need a resolved User these hops must not need.

They exist so no control-plane process reads a relay-owned Redis key.
Everything here reads Redis or calls an in-relay ChannelService static;
nothing here queries the ORM for a decision and nothing writes a row.
The two ORM reads that survive are inside get_detailed_channel_info's
name fallbacks, which the spec's ORM-reads table keeps in the relay
precisely because this handler is now the relay's side of the boundary.

nginx routes these through `location ^~ /proxy/relay/`, which carries
the dispatcharr_api_params.conf blanking include and no authorize hop:
authorize_stream() would 404 a URI naming no channel (spec Amendment
S8), and the location must stay externally reachable because Django
dials it as an ordinary client, from the worker role across the compose
network and from the api role through its own nginx.
"""

import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response

from apps.proxy.live_proxy.channel_status import (
    ChannelStatus,
    build_live_channel_stats_data,
)
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer
from apps.proxy.live_proxy.services.channel_service import ChannelService
from apps.proxy.permissions import IsInternalRelay
from apps.proxy.relay_serializers import (
    RelayAdvanceRequestSerializer,
    RelayAdvanceResponseSerializer,
    RelayChannelDetailSerializer,
    RelayChannelListSerializer,
    RelayChannelStateSerializer,
    RelayStopResponseSerializer,
)

logger = logging.getLogger(__name__)

# What the Stats page and /proxy/stats/ have always shown. `?clients=all`
# lifts it for get_user_active_connections, which counts a user's
# connections and would under-count past ten on one channel.
DEFAULT_CLIENT_LIMIT = 10


@extend_schema(
    operation_id="internal_relay_list_channels",
    description=(
        "Internal. Every channel this relay is running, with the payload "
        "/proxy/stats/ and the channel_stats WebSocket message are built "
        "from. Not part of the client API."
    ),
    parameters=[
        OpenApiParameter(
            name="clients",
            description=(
                "Pass `all` for every client on each channel; omitted, the "
                "list is capped at ten, as the stats surfaces have always "
                "shown it."
            ),
            required=False,
            type=str,
        )
    ],
    responses={200: RelayChannelListSerializer},
    tags=["internal"],
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def channels_view(request):
    client_limit = (
        None
        if request.query_params.get("clients") == "all"
        else DEFAULT_CLIENT_LIMIT
    )
    proxy_server = ProxyServer.get_instance()
    payload = build_live_channel_stats_data(
        proxy_server.redis_client, client_limit=client_limit
    )
    return Response(RelayChannelListSerializer(payload).data)


@extend_schema(
    methods=["GET"],
    operation_id="internal_relay_channel",
    description=(
        "Internal. One channel's detailed status, the payload "
        "/proxy/ts/status/<id> is built from, serialized by "
        "RelayChannelDetailSerializer. With `?fields=state` the answer is "
        "instead a RelayChannelStateSerializer -- `channel_id` and `state` "
        "only -- read with one EXISTS and one HGET rather than the full "
        "diagnostic walk. Two shapes under one 200, so the schema names "
        "the full one and this description names the narrow one; a "
        "PolymorphicProxySerializer would need a discriminator field the "
        "wire does not carry."
    ),
    parameters=[
        OpenApiParameter(
            name="fields",
            description=(
                "Pass `state` for the two-field tune-path form "
                "(RelayChannelStateSerializer)."
            ),
            required=False,
            type=str,
        )
    ],
    responses={
        200: RelayChannelDetailSerializer,
        # The 404 body is the identifier and a null state, which is
        # exactly the narrow serializer's shape -- and true, since a
        # 404 here means the relay holds no metadata hash at all.
        404: RelayChannelStateSerializer,
    },
    tags=["internal"],
)
@extend_schema(
    methods=["DELETE"],
    operation_id="internal_relay_stop_channel",
    description=(
        "Internal. Stop the channel and release its resources, the "
        "operation /proxy/ts/stop/<id> wraps."
    ),
    responses={200: RelayStopResponseSerializer},
    tags=["internal"],
)
@api_view(["GET", "DELETE"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def channel_view(request, identifier):
    if request.method == "DELETE":
        result = ChannelService.stop_channel(identifier)
        return Response(RelayStopResponseSerializer(result).data)
    if request.query_params.get("fields") == "state":
        # The tune path's question and only that (ruling 20): one EXISTS
        # and one HGET, instead of get_detailed_channel_info's buffer
        # chunk sampling, client walk and two ORM name fallbacks, under
        # relay_client's two-second tune budget.
        #
        # Rendered through RelayChannelStateSerializer, not a partial
        # RelayChannelDetailSerializer: DRF skips a missing key only
        # when the field is neither allow_null nor defaulted, so the
        # detail serializer's four nullable fields would put
        # "url": null, "stream_profile": null and "owner": null into an
        # answer that knows none of them.
        redis_client = ProxyServer.get_instance().redis_client
        metadata_key = RedisKeys.channel_metadata(identifier)
        if not redis_client or not redis_client.exists(metadata_key):
            return Response(
                RelayChannelStateSerializer(
                    {"channel_id": identifier, "state": None}
                ).data,
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            RelayChannelStateSerializer(
                {
                    "channel_id": identifier,
                    "state": redis_client.hget(
                        metadata_key, ChannelMetadataField.STATE
                    ),
                }
            ).data
        )
    info = ChannelStatus.get_detailed_channel_info(identifier)
    if not info:
        # The relay has no metadata hash for this identifier. A real
        # answer, not a refusal -- but a 404 rather than a 200 with a
        # null, because relay_client.RelayRefused is how the Django-side
        # wrapper tells "no such running channel" from an outage, and
        # /proxy/ts/status/<id> has always answered 404 here. Rendered
        # through the narrow serializer, not a raw dict: CLAUDE.md
        # section Conventions, and the shape is exactly right.
        return Response(
            RelayChannelStateSerializer(
                {"channel_id": identifier, "state": None}
            ).data,
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(RelayChannelDetailSerializer(info).data)


@extend_schema(
    operation_id="internal_relay_stop_client",
    description=(
        "Internal. Stop one client connection on one channel: sets the "
        "client's stop key and, when the client is not on this worker, "
        "publishes the stop over live:events. Wrapped by "
        "/proxy/ts/stop_client/<id>."
    ),
    responses={200: RelayStopResponseSerializer},
    tags=["internal"],
)
@api_view(["DELETE"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def channel_client_view(request, identifier, client_id):
    result = ChannelService.stop_client(identifier, client_id)
    return Response(RelayStopResponseSerializer(result).data)


@extend_schema(
    operation_id="internal_relay_advance",
    description=(
        "Internal. Switch a running channel to an already-resolved source. "
        "Django resolves the candidate in the API process, where the ORM "
        "is; the relay only applies it. Wrapped by "
        "/proxy/ts/change_stream/<id> and /proxy/ts/next_stream/<id>."
    ),
    request=RelayAdvanceRequestSerializer,
    responses={200: RelayAdvanceResponseSerializer},
    tags=["internal"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def channel_advance_view(request, identifier):
    payload = RelayAdvanceRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    source = payload.validated_data
    # Positional exactly as change_stream_url declares them, with
    # new_url always present so its own next_source branch -- an ORM
    # query PR 6 took out of the relay process -- is never entered.
    result = ChannelService.change_stream_url(
        identifier,
        source["url"],
        source["user_agent"],
        source["stream_id"],
        source["m3u_profile_id"],
        stream_name=source["stream_name"],
    )
    return Response(RelayAdvanceResponseSerializer(result).data)
