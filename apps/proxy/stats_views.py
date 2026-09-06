"""Combined connection stats for live, VOD, and catch-up."""

import logging
import time

from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes

from apps.accounts.permissions import IsAdmin
from apps.proxy import relay_client
from apps.proxy.vod_proxy.views import build_vod_stats_data
from apps.timeshift.stats import build_timeshift_stats_data
from core.utils import RedisClient

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsAdmin])
def combined_stats(request):
    """Return live, VOD, and catch-up stats in one response."""
    redis_client = RedisClient.get_client()
    if not redis_client:
        return JsonResponse({"error": "Redis not available"}, status=500)

    # Phase 1 PR 7: the live section comes from the relay; the VOD and
    # catch-up sections are built from Django-owned keys and stay here.
    # A relay that cannot answer degrades that one section to empty
    # rather than failing the whole response -- the Stats page reads all
    # three, and blanking VOD and catch-up because the relay is
    # restarting would be a worse answer than an empty live list.
    try:
        live = relay_client.list_channels()
    except (relay_client.RelayUnavailable, relay_client.RelayRefused) as e:
        logger.warning(f"Relay could not answer for combined stats: {e}")
        live = {"channels": [], "count": 0}
    except ImproperlyConfigured as exc:
        # Same degrade as an unreachable relay: a misconfigured base URL
        # cannot be fixed by aborting a stats read, and this is a
        # background/cleanup-shaped read, not a client-issued command.
        logger.warning(
            "Relay could not answer for combined stats: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        live = {"channels": [], "count": 0}

    return JsonResponse({
        "live": live,
        "vod": build_vod_stats_data(redis_client),
        "catchup": build_timeshift_stats_data(redis_client),
        "timestamp": time.time(),
    })
