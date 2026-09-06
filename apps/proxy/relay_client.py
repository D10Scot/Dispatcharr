"""Django's side of the boundary: how the control plane asks the relay things.

Phase 1 PR 7, D9 and D10. Five routes, all reached through the api
role's nginx, which routes `location ^~ /proxy/relay/` to the relay_py
upstream -- never to a raw application port, because the relay has no
HTTP listener at all (D5):

  GET    /proxy/relay/channels[?clients=all]           list
  GET    /proxy/relay/channels/<id>[?fields=state]     one channel
  DELETE /proxy/relay/channels/<identifier>            stop the channel
  DELETE /proxy/relay/channels/<id>/clients/<client>   stop one client
  POST   /proxy/relay/channels/<identifier>/advance    switch source

D10 in one sentence: nothing under apps/proxy/live_proxy/,
apps/proxy/vod_proxy/ or apps/timeshift/'s streaming path may import
this module. The in-relay ChannelService statics are called 25 times
from inside the relay and are untouched; only the Django-side callers
move here. apps/proxy/live_proxy/views.py is the one file on both
sides of that line -- its five IsAdmin views run in the API process
after PR 4's routing -- so it imports this module function-locally,
inside those five views only.

Three timeout budgets, no retries anywhere:

  TUNE_TIMEOUT    (1, 2)   reads reached from Channel.get_stream(),
                           which itself runs inside the relay's
                           next-source call with a 5s read timeout.
                           Three seconds worst case leaves room.
  ADMIN_TIMEOUT   (2, 5)   reads and stops behind an admin request.
  ADVANCE_TIMEOUT (2, 20)  ChannelService.change_stream_url polls
                           RedisKeys.switch_status for up to
                           STREAM_SWITCH_CONFIRM_TIMEOUT = 15s on the
                           non-owner path before answering.

No retry, deliberately: a retried advance switches twice, a retried
stop doubles an admin's wait for an operation the relay has already
recorded, and a retried tune-path read exceeds the budget above.
control_plane's single retry exists because a failed next-source
strands a viewer; none of these five do.

Nothing logged here names a URL: scripts/check_credential_logging.py
cannot see what a caller formats, and a relay path carries a channel
UUID, which CLAUDE.md treats as a secret.
"""

import json
import logging
from urllib.parse import urlencode

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.internal_base_url import resolve_base_url

logger = logging.getLogger(__name__)

TUNE_TIMEOUT = (1, 2)
ADMIN_TIMEOUT = (2, 5)
ADVANCE_TIMEOUT = (2, 20)


class RelayUnavailable(Exception):
    """The relay could not be reached, or answered 5xx, or redirected."""


class RelayRefused(Exception):
    """The relay answered, and said no. Not a subclass of RelayUnavailable:
    a 404 for an unknown channel and a 403 from a SECRET_KEY mismatch are
    answers, and a caller that treats them as an outage hides both."""

    def __init__(self, status, path):
        # The path, never the body and never the full URL.
        self.status = status
        super().__init__(f"{path} refused with {status}")


def get_relay_control_base_url():
    """Where the relay answers, for this deployment shape (D9)."""
    return resolve_base_url(
        override_var="DISPATCHARR_RELAY_BASE_URL",
        modular_host_var="DISPATCHARR_WEB_HOST",
        modular_host_default="web",
    )


def _request(method, path, *, timeout, payload=None, params=None):
    """One signed call. Raises RelayUnavailable or RelayRefused."""
    body = json.dumps(payload).encode() if payload is not None else b""
    full_path = f"{path}?{urlencode(params)}" if params else path
    headers = {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(
            method, full_path, body
        ),
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    url = get_relay_control_base_url() + full_path
    try:
        response = requests.request(
            method,
            url,
            data=body or None,
            headers=headers,
            timeout=timeout,
            # Never followed: requests re-sends a redirected request
            # with every custom header intact, so a stray `return 301`
            # would forward the signed internal headers off this
            # deployment. Treated as an outage below instead.
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise RelayUnavailable(f"{path} unreachable: {exc}") from exc
    if 300 <= response.status_code < 400:
        raise RelayUnavailable(f"{path} redirected with {response.status_code}")
    if response.status_code >= 500:
        raise RelayUnavailable(f"{path} answered {response.status_code}")
    if response.status_code >= 400:
        raise RelayRefused(response.status_code, path)
    if not response.content:
        return {}
    try:
        answer = response.json()
    except ValueError as exc:
        raise RelayUnavailable(
            f"{path} answered 2xx with a non-JSON body"
        ) from exc
    if not isinstance(answer, dict):
        raise RelayUnavailable(f"{path} answered 2xx with a non-object body")
    return answer
