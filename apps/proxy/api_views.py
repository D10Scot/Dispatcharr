"""The three internal routes the relay calls (Phase 1 PR 6, D12).

Gated by IsInternalRelay -- the two internal HMAC headers, never a DRF or
session principal, never IsAdmin (which would need a resolved User, the
one thing these hops must not need).

No ORM write appears in this file, deliberately: the event-row writes and
the Stream update live in core/relay_events.py, because
scripts/metrics/collect_architecture.py counts every write under
apps/proxy/ into proxy_orm_writes, whose Phase 1 target is zero, and
because the spec's Done grep runs over this directory.
"""

import logging

from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response

from apps.proxy import next_source
from apps.proxy.permissions import IsInternalRelay
from apps.proxy.serializers import (
    NextSourceRequestSerializer,
    NextSourceResponseSerializer,
    RelayEventBatchSerializer,
    RelayEventResponseSerializer,
    ReleaseRequestSerializer,
    ReleaseResponseSerializer,
)
from core.relay_events import apply_event_batch

logger = logging.getLogger(__name__)


@extend_schema(
    operation_id="internal_relay_next_source",
    description=(
        "Internal. The relay asks which stream to play next: at the initial "
        "tune, at a failover, and when an operator names a target. Django "
        "runs Channel.get_stream() and moves the provider slot; the relay "
        "never chooses. Not part of the client API."
    ),
    request=NextSourceRequestSerializer,
    responses={200: NextSourceResponseSerializer},
    tags=["internal"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def next_source_view(request, identifier):
    payload = NextSourceRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    try:
        answer = next_source.resolve_source(identifier, **payload.validated_data)
    except Http404:
        # Neither a Channel by uuid nor a Stream by stream_hash. The only
        # 4xx this route answers: "no candidate available" is a 200 with a
        # null source, because the client turns every 4xx into a refusal
        # and an exhausted channel is not a refusal (rulings 13 and 15).
        # Rendered through the same response serializer as the 200 path
        # (CLAUDE.md § Conventions) -- the client's own 404 mapping
        # (control_plane.next_source) substitutes exactly this shape.
        return Response(
            NextSourceResponseSerializer(
                next_source._with_proxy_settings(
                    {"source": None, "alternates": [], "error": "identifier not found"}
                )
            ).data,
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(NextSourceResponseSerializer(answer).data)


@extend_schema(
    operation_id="internal_relay_release_source",
    description=(
        "Internal. Give the provider slot back. The optional ids are what "
        "the relay read out of its own metadata hash, used when the Channel "
        "row was deleted mid-playback and neither ORM release can run."
    ),
    request=ReleaseRequestSerializer,
    responses={200: ReleaseResponseSerializer},
    tags=["internal"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def release_view(request, identifier):
    payload = ReleaseRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    released = next_source.release_source(identifier, **payload.validated_data)
    return Response(ReleaseResponseSerializer({"released": released}).data)


@extend_schema(
    operation_id="internal_relay_events",
    description=(
        "Internal. A batch of relay transitions. Each becomes a SystemEvent "
        "row and a Connect fan-out; the three UI-visible types also push a "
        "relay_event WebSocket message. stream_stats is the exception: it "
        "writes the Stream row and no event row."
    ),
    request=RelayEventBatchSerializer,
    responses={200: RelayEventResponseSerializer},
    tags=["internal"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def events_view(request):
    payload = RelayEventBatchSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    counts = apply_event_batch(payload.validated_data["events"])
    return Response(RelayEventResponseSerializer(counts).data)
