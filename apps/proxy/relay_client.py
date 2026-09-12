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
from django.core.exceptions import ImproperlyConfigured

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
    """The relay could not be reached, or answered 5xx, or redirected.

    `transport` is True only for the requests.ConnectionError branch in
    _request() -- a connection failure, which really is relay-wide.
    ReadTimeout and every other RequestException, a redirect, a 5xx and
    a garbled 2xx body are all per-request outcomes from a relay that
    answered at least once (a stuck single channel, one worker recycle,
    a full listen queue); they default to False. stop_channels() below
    uses the distinction: only a transport failure justifies aborting a
    whole batch (final review round, "the bound over-aborts", then
    corrected again when the first fix marked every RequestException --
    ReadTimeout included -- transport=True; a per-request failure must
    not strand channels that would have stopped fine)."""

    def __init__(self, message, *, transport=False):
        self.transport = transport
        super().__init__(message)


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
    except requests.ConnectionError as exc:
        # type(exc).__name__ only, never str(exc): a requests exception's
        # own text carries the dialled host, port and full path with its
        # query string (e.g. "HTTPConnectionPool(host='web', port=80): Max
        # retries exceeded with url: /proxy/relay/channels/<uuid>?fields=
        # state"), and this line must name "the identifier and the status
        # code only, never the URL it dialled." `from exc` keeps the full
        # detail on the chained traceback for anyone reading logs directly.
        #
        # transport=True only here: ConnectionError -- which ConnectTimeout
        # subclasses -- means the relay could not be reached at all, so
        # every remaining identifier in a stop_channels() batch would fail
        # the same way. The wider RequestException catch below, ReadTimeout
        # included, means the relay was reached and this one request then
        # failed (a single channel's teardown stuck past ADMIN_TIMEOUT's
        # five-second read budget, a garbled response mid-stream), which
        # says nothing about the next identifier -- final review round: an
        # earlier version of this branch caught ReadTimeout here too and
        # stranded channels a slow teardown would have let stop fine.
        raise RelayUnavailable(
            f"{path} unreachable: {type(exc).__name__}", transport=True
        ) from exc
    except requests.RequestException as exc:
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
    an outcome that leaks a provider slot only when stream_profile:<id>
    is ALSO already gone: in that case the fallback returns False,
    get_stream() calls _release_stale_stream_assignment() and re-reserves,
    which can leak (models.py:536, "profile_connections may leak") exactly
    as it already could before this module existed.
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


def live_connections(user_id):
    """The live half of get_user_active_connections, over HTTP.

    live:channel:*:clients:* is relay-private state -- the family
    Phase 3 moves out of Redis -- so the control plane asks the relay
    for it rather than scanning it. all_clients=True because a cap
    under-counts a user with more than ten clients on one channel,
    which is exactly the case this function exists to catch, and
    TUNE_TIMEOUT because authorize_stream calls this on every tune.

    A relay that cannot answer contributes nothing and logs once. That
    fails open, and open is correct here: the relay is the only process
    serving live clients, so a relay that is not answering has none.
    Failing closed would 429 every tune for the length of a restart.

    Moved here from apps/proxy/utils.py in Phase 2 PR 2b-4. The body is
    unchanged; the home is. This function is one relay_client call plus
    its three failure arms plus shaping, so relay_client owns it -- and
    relay_client is inside Gate 2's denominator, which apps/proxy/utils.py
    is not, so the tune-path relay call now sits inside the gate that
    guards the Go port (reachability brief, § 8).
    """
    from django.core.exceptions import ImproperlyConfigured

    try:
        # TUNE_TIMEOUT, not the admin budget: check_user_stream_limits
        # calls this from inside authorize_stream, so it is on the tune
        # path for every stream-limited user, and Global Constraints put
        # tune-path reads at (1, 2) with no retry.
        payload = list_channels(all_clients=True, timeout=TUNE_TIMEOUT)
    except (RelayUnavailable, RelayRefused) as exc:
        logger.warning("[stream limits] the relay could not list channels: %s", exc)
        return []
    except ImproperlyConfigured as exc:
        # Unlike Channel.get_stream() this is a limit *check*, not the
        # reservation itself: failing open here (see the docstring) is
        # the same choice a misconfigured relay deserves as an
        # unreachable one -- propagating would 429/500 every tune for a
        # problem a retry cannot fix.
        logger.warning(
            "[stream limits] the relay could not list channels: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return []

    connections = []
    for channel in payload.get("channels") or []:
        media_id = channel.get("channel_id")
        for client in channel.get("clients") or []:
            raw_user_id = client.get("user_id")
            if user_id is not None:
                try:
                    if raw_user_id is None or int(raw_user_id) != user_id:
                        continue
                except (TypeError, ValueError):
                    continue
            try:
                connected_at = float(client.get("connected_at") or 0)
            except (TypeError, ValueError):
                continue
            connections.append({
                'media_id': media_id,
                'client_id': client.get("client_id"),
                'connected_at': connected_at,
                'type': 'live',
            })
    return connections


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

    Returns the list of identifiers actually stopped (stop_channel
    answered without raising), so a caller that deletes hundreds of
    channels in one request can report how many it actually reached.

    A whole-provider M3U delete can pass hundreds of identifiers here in
    one call (Kimi's PR #194 review, question 2). Only a connection-level
    failure -- RelayUnavailable(transport=True), meaning the relay could
    not be reached at all -- justifies aborting the rest of the batch:
    every remaining identifier would pay the same round trip and fail
    the same way, so a few hundred identifiers would otherwise turn one
    DELETE into minutes of blocked cleanup for no additional
    information. ImproperlyConfigured is the same shape: a bad base URL
    fails identically for every remaining identifier before a request is
    even attempted. Everything else is a per-channel outcome, not a
    relay-wide one, and keeps the loop going: RelayRefused (a 404 for a
    channel already stopped, a 403 a SECRET_KEY mismatch would also give
    every other identifier, but the existing contract already treats a
    refusal as one channel's problem); and a RelayUnavailable that is
    NOT a transport failure -- a redirect, a 5xx or a garbled 2xx body,
    which mean the relay answered at least once and this one request
    failed (a single stuck channel past ADMIN_TIMEOUT, one worker
    recycle, a full listen queue) (final review round: the earlier,
    coarser bound could abort a batch over one slow or transient
    per-channel failure that would have succeeded on retry with the
    next identifier).
    """
    stopped = []
    for identifier in identifiers:
        if not identifier:
            continue
        try:
            stop_channel(str(identifier))
        except RelayRefused as exc:
            logger.warning(
                "Failed to stop proxy session for channel %s: %s",
                identifier,
                exc,
            )
            continue
        except RelayUnavailable as exc:
            if not exc.transport:
                # The relay answered at least once; this one request
                # failed for a reason specific to it. Per-channel, like
                # RelayRefused.
                logger.warning(
                    "Failed to stop proxy session for channel %s: %s",
                    identifier,
                    exc,
                )
                continue
            logger.warning(
                "Relay could not be reached while stopping proxy "
                "sessions; stopping after %d of the identifiers given: %s",
                len(stopped),
                exc,
            )
            break
        except ImproperlyConfigured as exc:
            logger.warning(
                "Relay could not answer while stopping proxy sessions; "
                "stopping after %d of the identifiers given: %s is "
                "misconfigured",
                len(stopped),
                getattr(exc, "var_name", None) or "the relay base URL",
            )
            break
        except Exception as exc:
            # Not a relay-shaped failure (a bug in stop_channel itself,
            # say) -- still must not block the caller's DB delete, and
            # still per-identifier: one bad identifier says nothing
            # about the rest.
            logger.warning(
                "Failed to stop proxy session for channel %s: %s",
                identifier,
                exc,
            )
            continue
        else:
            stopped.append(identifier)
    return stopped


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
    channel_name=None,
    m3u_profile_name=None,
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
            "channel_name": channel_name,
            "m3u_profile_name": m3u_profile_name,
            "reset_tried": reset_tried,
        },
    )
