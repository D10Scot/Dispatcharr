"""The relay's side of the boundary: how it asks Django things.

Phase 1 PR 6, D9. Three calls, all through nginx on the API role's port,
never to a raw uWSGI listener (D5):

  POST /api/relay/channels/<identifier>/next-source   what to play next
  POST /api/relay/channels/<identifier>/release       give the slot back
  POST /api/relay/events                              what just happened

Timeouts are (connect 2s, read 5s) with one retry, as the spec's
"Degraded fallback" row states. requests is safe to call from a relay
greenlet because gevent-early-monkey-patch is on: the socket read yields
the hub rather than blocking it, which is the same reason
url_utils.validate_stream_url already uses it on the tune path.

Nothing here imports apps/proxy/relay_client.py (D10) — that is the other
direction, Django to relay, and it is PR 7's.
"""

import json
import logging
import os
import time

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 2
READ_TIMEOUT = 5
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)
ATTEMPTS = 2  # the first try plus the one retry the spec allows
RETRY_DELAY = 0.1


class ControlPlaneUnavailable(Exception):
    """Django could not be reached, or answered 5xx. Degrade."""


class ControlPlaneRefused(Exception):
    """Django answered, and said no. Do not degrade — fail the attempt."""

    def __init__(self, status, path):
        # The path, never the body and never a URL: a refusal body can
        # echo request content, and scripts/check_credential_logging.py
        # cannot see what a caller formats into a log line from here.
        self.status = status
        super().__init__(f"{path} refused with {status}")


def get_control_plane_base_url():
    """Where Django answers, for this deployment shape (D9).

    The same four-branch formula as get_dvr_stream_base_url()
    (apps/channels/tasks.py), with its own override variable: explicit,
    then modular by service name, then dev (no nginx — uWSGI's own http
    listener), then AIO through nginx on DISPATCHARR_PORT.
    """
    explicit = os.environ.get("DISPATCHARR_INTERNAL_API_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    env = os.environ.get("DISPATCHARR_ENV", "aio").lower()
    if env == "modular":
        host = os.environ.get("DISPATCHARR_WEB_HOST", "web")
        port = os.environ.get("DISPATCHARR_PORT", "9191")
        return f"http://{host}:{port}"
    if env == "dev":
        return "http://127.0.0.1:5656"
    port = os.environ.get("DISPATCHARR_PORT", "9191")
    return f"http://127.0.0.1:{port}"


def _post(path, payload):
    """One POST, signed, with one retry. Raises ControlPlaneUnavailable."""
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header("POST", path, body),
    }
    url = get_control_plane_base_url() + path
    last = None
    for attempt in range(ATTEMPTS):
        try:
            response = requests.request(
                "POST", url, data=body, headers=headers, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            last = exc
        else:
            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as exc:
                    # A 2xx with a body that is not JSON is nginx or a
                    # proxy answering, not Django. Treat it as an outage
                    # so the caller's existing handling applies rather
                    # than letting a ValueError escape a greenlet.
                    raise ControlPlaneUnavailable(
                        f"{path} answered 2xx with a non-JSON body"
                    ) from exc
            if response.status_code < 500:
                # A refusal, not an outage — and the distinction is
                # load-bearing. Only ControlPlaneUnavailable fires the
                # degraded, unenforced fallback; a 404 (channel deleted
                # mid-playback) or a 403 (SECRET_KEY mismatch between the
                # api and relay roles) must fail the switch loudly instead
                # of making every failover on the deployment degrade
                # silently forever. Not a subclass: `except
                # ControlPlaneUnavailable` must not catch this.
                raise ControlPlaneRefused(response.status_code, path)
            last = ControlPlaneUnavailable(f"{path} answered {response.status_code}")
        if attempt + 1 < ATTEMPTS:
            # gevent-patched: this yields the hub, it does not block it.
            time.sleep(RETRY_DELAY)
    raise ControlPlaneUnavailable(f"{path} unreachable: {last}")


def next_source(
    identifier,
    *,
    exclude_stream_ids=(),
    current_url=None,
    target_stream_id=None,
    reason="initial",
    include_alternates=False,
):
    """Ask Django what this channel should play next.

    A 404 ("identifier not found") is the channel-deleted-mid-playback
    case: today get_alternate_streams answers it by catching Http404 and
    letting _try_next_stream return False, so it is mapped to an ordinary
    "no source" answer here rather than raised. Every other refusal (a
    400, or a 403 from a SECRET_KEY mismatch between the api and relay
    roles) propagates as ControlPlaneRefused — the caller must not
    degrade on it.
    """
    path = f"/api/relay/channels/{identifier}/next-source"
    payload = {
        "exclude_stream_ids": list(exclude_stream_ids),
        "reason": reason,
    }
    if current_url is not None:
        payload["current_url"] = current_url
    if target_stream_id is not None:
        payload["target_stream_id"] = target_stream_id
    if include_alternates:
        payload["include_alternates"] = True
    try:
        return _post(path, payload)
    except ControlPlaneRefused as exc:
        if exc.status == 404:
            return {"source": None, "alternates": [], "error": "identifier not found"}
        raise


def release_source(identifier, *, stream_id=None, m3u_profile_id=None, channel_pk=None):
    """Give a reserved slot back. Raises like _post — the caller decides
    whether an unreachable control plane is worth a WARNING and moving on
    (ruling 9), because that call site already knows what it was tearing
    down.
    """
    path = f"/api/relay/channels/{identifier}/release"
    payload = {
        "stream_id": stream_id,
        "m3u_profile_id": m3u_profile_id,
        "channel_pk": channel_pk,
    }
    answer = _post(path, payload)
    return bool(answer.get("released"))


def post_events(events):
    """POST one batch of events. Never raises — both exception types are
    swallowed here so a caller that wants fire-and-forget delivery (see
    emit_event) gets it; a caller that wants to know about a failure
    reads the boolean.
    """
    try:
        _post("/api/relay/events", {"events": events})
        return True
    except ControlPlaneUnavailable as exc:
        logger.warning("Could not post %d relay event(s): %s", len(events), exc)
        return False
    except ControlPlaneRefused as exc:
        logger.error(
            "Relay events refused with status %s", exc.status
        )
        return False


def emit_event(event_type, channel_id=None, channel_name=None, **details):
    """Post one transition. Same signature as core.utils.log_system_event.

    Fire and forget, on a greenlet, for the same reason
    _spawn_channel_stop_event already spawns: a teardown or a tune must
    not wait on Django, and this call now crosses a process boundary.
    The cost is that a worker dying inside the window loses the event;
    the alternative is a 5s stall on the byte path.
    """
    event = {"type": event_type, "details": details}
    if channel_id is not None:
        event["channel_id"] = str(channel_id)
    if channel_name is not None:
        event["channel_name"] = channel_name
    for key in ("client_id", "stream_id"):
        if key in details:
            event[key] = details[key]
    _spawn(post_events, [event])


def _spawn(fn, *args):
    from core.utils import _is_gevent_monkey_patched, _should_use_sync_websocket_send

    if _should_use_sync_websocket_send() or not _is_gevent_monkey_patched():
        fn(*args)
        return
    import gevent

    gevent.spawn(fn, *args)
