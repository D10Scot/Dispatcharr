"""Turning the relay's posted transitions into rows and pushes.

Phase 1 PR 6. The relay used to call log_system_event() at thirteen sites
and Stream.save() at one; both now arrive here as
POST /api/relay/events. This module lives in core/, not in apps/proxy/,
for two reasons that point the same way: log_system_event's own
implementation is here (core/utils.py), and
scripts/metrics/collect_architecture.py counts every ORM write under
apps/proxy/ into proxy_orm_writes, whose Phase 1 target is zero. The view
is in apps/proxy/api_views.py (D12); the writes are here.
"""

import logging
import time

from django.db import close_old_connections
from django.utils import timezone

from core.models import SystemEvent
from core.utils import log_system_event, send_websocket_update

logger = logging.getLogger(__name__)

# The transitions a human watching the Stats page cares about. Each also
# becomes a SystemEvent row; the push is what stops the UI polling
# channel_status to notice a switch.
RELAY_WS_EVENT_TYPES = frozenset(
    {"channel_failover", "stream_switch", "client_disconnect"}
)

# Everything the push may carry. Never the raw details dict:
# input/manager.py's stream_switch puts a truncated provider URL in
# new_url, and a channel UUID is a capability against anonymous
# /proxy/ts/stream/<uuid>. dispatcharr/consumers.py keeps the whole type
# admin-only for the same reason it keeps channel_stats admin-only.
_WS_FIELDS = ("channel_id", "channel_name", "client_id", "stream_id", "reason")

# stream_stats is not a SystemEvent type -- it writes the Stream row
# instead (see _apply_stream_stats) and must never create a row. Every
# other accepted type is one of SystemEvent's own EVENT_TYPES; anything
# else is rejected rather than raised, since a relay running ahead of a
# Django upgrade must not be able to 500 the events route.
_KNOWN_EVENT_TYPES = frozenset(dict(SystemEvent.EVENT_TYPES))


def _clean(value):
    """"" becomes None. Belt and braces beside the serializer's default=None:

    SystemEvent.channel_id is a UUIDField (core/models.py, null=True);
    UUIDField.to_python("") raises ValidationError, which
    log_system_event's bare `except Exception` swallows -- no row, no
    Connect fan-out, one error log per event. Every channel-less event
    hits this: vod_start and vod_stop carry no channel at all, and they
    are written today.
    """
    return None if value == "" else value


def _push(event):
    payload = {
        "success": True,
        "type": "relay_event",
        "event": event["type"],
        "timestamp": time.time(),
    }
    details = event.get("details") or {}
    for field in _WS_FIELDS:
        # Not `event.get(field, details.get(field))`: through the view,
        # RelayEventSerializer's validated_data always carries the
        # identity fields explicitly, as None when absent -- a dict.get
        # default only fires when the key is missing, never when it is
        # present with value None, so that form never actually falls back
        # to details.
        value = event.get(field)
        if value is None:
            value = details.get(field)
        if value is not None:
            payload[field] = value
    send_websocket_update("updates", "update", payload)


def _apply_stream_stats(event):
    """core.relay_events version of ChannelService._update_stream_stats_in_db.

    Moved verbatim, including the `if value is not None` merge (a None in
    the batch never overwrites an existing key) and the
    close_old_connections() in `finally` -- the geventpool property
    apps/proxy/live_proxy/tests/test_atomic_db_close.py used to pin on the
    relay side now lives here (Task 10 retargets that test to the post).
    """
    from apps.channels.models import Stream

    stream_id = event.get("stream_id")
    # Task 10's emit_event("stream_stats", stream_id=stream_id, **stats)
    # copies stream_id to the top level but leaves it in details too --
    # exclude it here, or it lands inside Stream.stream_stats itself,
    # which today's ChannelService._update_stream_stats_in_db(stream_id,
    # **stats) never stored.
    stats = {
        key: value
        for key, value in (event.get("details") or {}).items()
        if key != "stream_id"
    }
    try:
        stream = Stream.objects.get(id=stream_id)

        current_stats = stream.stream_stats or {}
        for key, value in stats.items():
            if value is not None:
                current_stats[key] = value

        stream.stream_stats = current_stats
        stream.stream_stats_updated_at = timezone.now()
        stream.save(update_fields=["stream_stats", "stream_stats_updated_at"])

        logger.debug(
            "Updated stream stats in database for stream %s: %s", stream_id, stats
        )
        return True
    except Exception as e:
        logger.error(
            "Error updating stream stats in database for stream %s: %s", stream_id, e
        )
        return False
    finally:
        # geventpool keeps checked-out connections until close(); release
        # promptly since this runs outside a normal request cycle.
        close_old_connections()


def _username_for(user_id):
    """The display name for a relay-posted user id, or None.

    Never raises: a malformed id, a deleted user and a database hiccup
    all mean "no name to show", and one bad entry must not lose the rest
    of the batch.
    """
    from django.contrib.auth import get_user_model

    try:
        return (
            get_user_model()
            .objects.filter(id=int(user_id))
            .values_list("username", flat=True)
            .first()
        )
    except (TypeError, ValueError):
        return None
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        logger.warning("Could not resolve username for relay event: %s", exc)
        return None


def apply_event_batch(events):
    """Turn a batch of relay-posted events into rows and pushes.

    Returns {"accepted": int, "rejected": int}. An unknown event type is
    counted as rejected, never raised -- a batch is many independent
    transitions and one bad entry must not lose the rest.

    The counts are advisory telemetry only, not a delivery guarantee:
    log_system_event() swallows its own errors internally (a bare `except
    Exception`, logged, returning None either way), so a write that fails
    inside it is still counted as accepted here. No caller of this
    function inspects the counts to retry or alert on a mismatch.
    """
    accepted = 0
    rejected = 0
    for event in events:
        event_type = event.get("type")

        if event_type == "stream_stats":
            if _apply_stream_stats(event):
                accepted += 1
            else:
                rejected += 1
            continue

        if event_type not in _KNOWN_EVENT_TYPES:
            rejected += 1
            continue

        channel_id = _clean(event.get("channel_id"))
        channel_name = _clean(event.get("channel_name"))
        details = dict(event.get("details") or {})
        # channel_id, channel_name and event_type (the positional first
        # argument) are already bound above by name; control_plane's own
        # emit_event() never puts them in details, but a hand-built batch
        # (a Phase 2 relay, or a malformed request) could, and any of the
        # three would collide as a duplicate keyword argument and raise
        # TypeError -- one bad entry must not 500 the whole batch.
        details.pop("channel_id", None)
        details.pop("channel_name", None)
        details.pop("event_type", None)

        # 2b-2: the relay posts a user id because it no longer holds a
        # User row on a live surface (apps/proxy/authorize_views.py's
        # result_from_headers, 2b-2 Ruling R1). Resolve
        # the display name here, where the SystemEvent write already
        # runs. An explicit username from the untrusted path wins; an
        # unknown id becomes None, exactly what the relay used to send
        # for an anonymous client.
        user_id = details.pop("user_id", None)
        if user_id and "username" not in details:
            details["username"] = _username_for(user_id)

        try:
            log_system_event(
                event_type, channel_id=channel_id, channel_name=channel_name, **details
            )
        except TypeError:
            logger.error(
                "Rejecting malformed relay event %r: details collided with a "
                "reserved argument name",
                event_type,
            )
            rejected += 1
            continue

        if event_type in RELAY_WS_EVENT_TYPES:
            _push(event)

        accepted += 1

    return {"accepted": accepted, "rejected": rejected}
