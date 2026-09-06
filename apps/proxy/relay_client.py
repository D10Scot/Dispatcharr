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
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.internal_base_url import resolve_base_url
from apps.proxy.live_proxy.constants import ChannelState

logger = logging.getLogger(__name__)

# Django's escape_uri_path safe set, minus '/': what get_full_path()
# reconstructs a path segment through on the server side, since nginx
# passes PATH_INFO already decoded and Django re-escapes it before the
# bound token is verified against it. quote(..., safe='') encodes more
# than that (':', for one), so the two sides would sign and verify
# different strings for the same identifier -- a spurious 403, not a
# routing failure, because nginx's <str:...> converter never sees the
# raw bytes either way. -_.~ are always safe in quote(), so they need
# not be repeated here.
_PATH_SEGMENT_SAFE = ":@&+$,!*'()"

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
        # type(exc).__name__ only, never str(exc): a requests exception's
        # own text carries the dialled host, port and full path with its
        # query string (e.g. "HTTPConnectionPool(host='web', port=80): Max
        # retries exceeded with url: /proxy/relay/channels/<uuid>?fields=
        # state"), and this line must name "the identifier and the status
        # code only, never the URL it dialled." `from exc` keeps the full
        # detail on the chained traceback for anyone reading logs directly.
        raise RelayUnavailable(f"{path} unreachable: {type(exc).__name__}") from exc
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


@dataclass(frozen=True)
class ChannelSnapshot:
    """What Channel.get_stream()'s reuse branch needs, in one round trip.

    present   the relay holds a metadata hash for this identifier
    active    ... and its state is one the tune path may reuse
    reachable the relay answered at all

    An unreachable relay reports (False, False, False) rather than
    raising: this runs inside Channel.get_stream(), which the relay
    itself reached over POST /api/relay/.../next-source with a five
    second read budget, and a raise here would turn a relay hiccup into
    a failed tune. present=False sends _stream_assignment_is_reusable to
    its stream_profile fallback, which reuses the existing assignment --
    the outcome that cannot leak a provider slot.
    """

    present: bool
    active: bool
    reachable: bool


def list_channels(*, all_clients=False, timeout=ADMIN_TIMEOUT):
    """Every channel the relay is running. Shape: {channels, count}."""
    params = {"clients": "all"} if all_clients else None
    return _request(
        "GET", "/proxy/relay/channels", timeout=timeout, params=params
    )


def get_channel(identifier, *, timeout=ADMIN_TIMEOUT, fields=None):
    """One channel's detailed status, or None when the relay has none.

    A 404 is an answer -- "this channel is not running" -- not an
    outage, so it becomes None. Every other refusal propagates: a 403
    means the two roles disagree about SECRET_KEY, and swallowing it
    would make every status read look like an idle system.

    fields="state" asks for the two-field tune-path form (ruling 20).
    It travels as a query parameter, which the bound token signs along
    with the path (ruling 17).
    """
    path = f"/proxy/relay/channels/{quote(str(identifier), safe=_PATH_SEGMENT_SAFE)}"
    params = {"fields": fields} if fields else None
    try:
        return _request("GET", path, timeout=timeout, params=params)
    except RelayRefused as exc:
        if exc.status == 404:
            return None
        raise


def channel_snapshot(identifier, *, timeout=TUNE_TIMEOUT):
    """The tune-path read. See ChannelSnapshot for the failure mode.

    Asks for ?fields=state (ruling 20), so the relay answers with one
    EXISTS and one HGET rather than get_detailed_channel_info's buffer
    chunk sampling, client walk and two ORM name fallbacks -- which
    would trip the two-second budget under load far more often than
    this question warrants.
    """
    reusable_states = (
        ChannelState.ACTIVE,
        ChannelState.WAITING_FOR_CLIENTS,
        ChannelState.BUFFERING,
        ChannelState.INITIALIZING,
        ChannelState.CONNECTING,
    )
    try:
        info = get_channel(identifier, timeout=timeout, fields="state")
    except (RelayUnavailable, RelayRefused) as exc:
        logger.warning(
            "Relay could not answer for channel %s: %s", identifier, exc
        )
        return ChannelSnapshot(present=False, active=False, reachable=False)
    if info is None:
        return ChannelSnapshot(present=False, active=False, reachable=True)
    return ChannelSnapshot(
        present=True, active=info.get("state") in reusable_states, reachable=True
    )


def stop_channel(identifier, *, timeout=ADMIN_TIMEOUT):
    """Stop a channel. Returns ChannelService.stop_channel's own dict."""
    path = f"/proxy/relay/channels/{quote(str(identifier), safe=_PATH_SEGMENT_SAFE)}"
    return _request("DELETE", path, timeout=timeout)


def stop_channels(identifiers):
    """Best-effort stop for each identifier. Never raises.

    Same contract as ChannelService.stop_channels, which the three
    Django-side callers relied on: proxy teardown runs before a DB
    delete and must never block it.
    """
    for identifier in identifiers:
        if not identifier:
            continue
        try:
            stop_channel(str(identifier))
        except Exception as exc:
            logger.warning(
                "Failed to stop proxy session for channel %s: %s",
                identifier,
                exc,
            )


def stop_client(identifier, client_id, *, timeout=ADMIN_TIMEOUT):
    """Stop one client on one channel."""
    path = (
        f"/proxy/relay/channels/{quote(str(identifier), safe=_PATH_SEGMENT_SAFE)}"
        f"/clients/{quote(str(client_id), safe=_PATH_SEGMENT_SAFE)}"
    )
    return _request("DELETE", path, timeout=timeout)


def advance(
    identifier,
    *,
    url,
    user_agent=None,
    stream_id=None,
    m3u_profile_id=None,
    stream_name=None,
    reset_tried=False,
):
    """Switch a running channel to an already-resolved source.

    url is required and always sent: Django resolved the candidate in
    the API process, where the ORM is (ruling 11). ADVANCE_TIMEOUT's
    20-second read budget covers ChannelService.change_stream_url's
    non-owner path, which polls for the owner's confirmation for up to
    STREAM_SWITCH_CONFIRM_TIMEOUT = 15s before answering.
    """
    path = f"/proxy/relay/channels/{quote(str(identifier), safe=_PATH_SEGMENT_SAFE)}/advance"
    return _request(
        "POST",
        path,
        timeout=ADVANCE_TIMEOUT,
        payload={
            "url": url,
            "user_agent": user_agent,
            "stream_id": stream_id,
            "m3u_profile_id": m3u_profile_id,
            "stream_name": stream_name,
            "reset_tried": reset_tried,
        },
    )
