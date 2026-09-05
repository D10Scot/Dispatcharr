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
from urllib.parse import urlsplit

import requests
from django.core.exceptions import ImproperlyConfigured
from django.http.request import split_domain_port

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from dispatcharr.utils import redact_url

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


# Set once we have logged the ImproperlyConfigured message for this
# process. Mirrors _events_down below: every misconfigured call still
# raises (the caller must not degrade on it), but the process only writes
# the explanation to the log once instead of once per tune.
_host_validation_warned = False


def _subject(var_name, raw_value, url):
    # var_name/raw_value name the environment variable responsible, for
    # the explicit and modular branches; dev/aio have no user-supplied
    # hostname to blame, so they fall back to naming the URL itself --
    # always the literal 127.0.0.1 form, never anything a caller supplied.
    return f"{var_name}={raw_value}" if var_name else f"the control-plane URL {url!r}"


def _raise_and_warn_once(message, var_name):
    # var_name travels on the exception (not just baked into the message)
    # so a catcher that must not repeat the message -- release_source(),
    # which logs its own ERROR without the URL -- can still name which
    # variable is responsible.
    global _host_validation_warned
    if not _host_validation_warned:
        logger.error(message)
        _host_validation_warned = True
    exc = ImproperlyConfigured(message)
    exc.var_name = var_name
    raise exc


def _validated(url, var_name=None, raw_value=None):
    """Reject a URL requests would turn into a Host header Django refuses.

    Two checks, in order:

    1. The scheme must be http or https. get_control_plane_base_url()
       only ever builds http:// URLs, so a scheme-less or malformed
       explicit value (e.g. "web:9191", urlsplit scheme "web") has no
       real host at all -- rejecting it with the host-shape message below
       would blame underscores for a problem that has nothing to do with
       them.
    2. What requests actually puts on the wire as the Host header is the
       netloc MINUS userinfo: requests turns "user:pw@host:9191" into
       HTTP Basic auth and sends "Host: host:9191", never forwarding the
       userinfo as part of the host. Validating the raw netloc (including
       userinfo) would reject a URL Django would happily accept, and
       validating it with Django's own split_domain_port -- exactly what
       HttpRequest.get_host() calls -- means the client and the server can
       never disagree about what counts as a valid Host header once
       userinfo is out of the way. It returns ('', '') for anything
       host_validation_re rejects (notably: an underscore anywhere in the
       host), and get_host() raises DisallowedHost for that BEFORE
       ALLOWED_HOSTS is even consulted. A relay that sent such a URL as an
       HTTP request would just get an opaque 400 with no indication why;
       failing here, at the source of the value, points at the actual
       variable and value responsible.

    raw_value must never carry a credential into the exception message or
    the log: a rejection here can surface in an anonymous streaming
    client's 500 response body by the time it reaches stream_ts's
    catch-all, so callers pass dispatcharr.utils.redact_url(explicit) for
    the explicit branch rather than the raw environment value. The
    modular branch's raw_value is a bare hostname and never carries
    userinfo, so it needs no redaction.

    No network access -- this is string parsing on a value already in
    hand, safe to run on every call.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        _raise_and_warn_once(
            f"{_subject(var_name, raw_value, url)} is not an http(s) URL: "
            "get_control_plane_base_url() only builds http:// URLs, and a "
            "scheme-less or malformed value has no host requests can send.",
            var_name,
        )
    host_for_wire = parsed.netloc.rpartition("@")[2]
    domain, _port = split_domain_port(host_for_wire)
    if domain:
        return url
    _raise_and_warn_once(
        f"{_subject(var_name, raw_value, url)} must be an http(s) URL "
        "whose host is letters, digits, dots and hyphens.",
        var_name,
    )


def get_control_plane_base_url():
    """Where Django answers, for this deployment shape (D9).

    The same four-branch formula as get_dvr_stream_base_url()
    (apps/channels/tasks.py), with its own override variable: explicit,
    then modular by service name, then dev (no nginx — uWSGI's own http
    listener), then AIO through nginx on DISPATCHARR_PORT. Every branch
    builds its URL and validates it the same way before returning, so a
    misconfigured host fails loudly here rather than as an opaque 400 on
    the first tune.
    """
    explicit = os.environ.get("DISPATCHARR_INTERNAL_API_BASE_URL")
    if explicit:
        return _validated(
            explicit.rstrip("/"),
            "DISPATCHARR_INTERNAL_API_BASE_URL",
            redact_url(explicit),
        )
    env = os.environ.get("DISPATCHARR_ENV", "aio").lower()
    if env == "modular":
        host = os.environ.get("DISPATCHARR_WEB_HOST", "web")
        port = os.environ.get("DISPATCHARR_PORT", "9191")
        return _validated(f"http://{host}:{port}", "DISPATCHARR_WEB_HOST", host)
    if env == "dev":
        return _validated("http://127.0.0.1:5656")
    port = os.environ.get("DISPATCHARR_PORT", "9191")
    return _validated(f"http://127.0.0.1:{port}")


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
                "POST",
                url,
                data=body,
                headers=headers,
                timeout=TIMEOUT,
                # Never follow a redirect: requests re-sends a redirected
                # POST with every custom header intact (it strips only
                # Authorization on a host change), so an nginx `return
                # 301 …` or a mis-set DISPATCHARR_INTERNAL_API_BASE_URL
                # would otherwise forward the signed internal headers off
                # this deployment. Handled as a 3xx below instead.
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            last = exc
        else:
            if response.status_code < 300:
                try:
                    answer = response.json()
                except ValueError as exc:
                    # A 2xx with a body that is not JSON is nginx or a
                    # proxy answering, not Django. Treat it as an outage
                    # so the caller's existing handling applies rather
                    # than letting a ValueError escape a greenlet.
                    raise ControlPlaneUnavailable(
                        f"{path} answered 2xx with a non-JSON body"
                    ) from exc
                if not isinstance(answer, dict):
                    # A 2xx whose JSON is a list, a string or null is not
                    # a shape any caller here expects; `answer.get(...)`
                    # would raise AttributeError out of a greenlet instead
                    # of being an ordinary, catchable outage.
                    raise ControlPlaneUnavailable(
                        f"{path} answered 2xx with a non-object body"
                    )
                return answer
            if response.status_code < 400:
                # A redirect: allow_redirects=False above means requests
                # handed it straight back rather than following it. Not
                # an answer, and not worth retrying — misconfiguration
                # doesn't fix itself inside the 120s signing window.
                raise ControlPlaneUnavailable(
                    f"{path} redirected with {response.status_code}"
                )
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
    current_stream_id=None,
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

    current_stream_id is the stream being failed over FROM; Django passes
    it straight through to the traversal so it starts right after that
    stream, wrapping (order_alternates_from_current), the same rotation
    today's pre-move get_alternate_streams(current_stream_id=) call gives.
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
    if current_stream_id is not None:
        payload["current_stream_id"] = current_stream_id
    if include_alternates:
        payload["include_alternates"] = True
    try:
        answer = _post(path, payload)
    except ControlPlaneRefused as exc:
        if exc.status == 404:
            return {"source": None, "alternates": [], "error": "identifier not found"}
        raise
    # _post already guarantees a dict; guard the two fields _try_next_stream
    # actually indexes into, so a malformed 200 (Django's serializer
    # rejecting its own contract, or a proxy answering with an unrelated
    # JSON object) becomes a catchable outage rather than a KeyError or a
    # TypeError deep inside the failover loop.
    source = answer.get("source")
    if source is not None and not isinstance(source, dict):
        raise ControlPlaneUnavailable(f"{path} answered a non-dict source")
    alternates = answer.get("alternates", [])
    if not isinstance(alternates, list):
        raise ControlPlaneUnavailable(f"{path} answered non-list alternates")
    return answer


def release_source(identifier, *, stream_id=None, m3u_profile_id=None, channel_pk=None):
    """Give a reserved slot back. Raises ControlPlaneRefused/Unavailable
    like _post — the caller decides whether an unreachable control plane
    is worth a WARNING and moving on (ruling 9), because that call site
    already knows what it was tearing down.

    A misconfigured host is different, and deliberately NOT raised here:
    "fail loudly on the first tune" (see next_source's docstring) belongs
    to the tune path, where a viewer is about to be told to try again.
    release_source() runs from a channel-stop cleanup path instead --
    aborting that cannot fix the configuration, and only leaks state (the
    channel's Redis keys, its ownership lease and a still-running ffmpeg
    holding a provider slot). It is also reachable in the worker role,
    which stops channels but never tunes, so "the first tune" may never
    happen there at all before a release is attempted. So
    ImproperlyConfigured is caught here, logged once per call (naming the
    variable only -- the offending value already got its once-per-process
    ERROR inside _validated) and treated as "not released": every caller
    already handles a False return the same way it handles the two
    control-plane exceptions.
    """
    path = f"/api/relay/channels/{identifier}/release"
    payload = {
        "stream_id": stream_id,
        "m3u_profile_id": m3u_profile_id,
        "channel_pk": channel_pk,
    }
    try:
        get_control_plane_base_url()
    except ImproperlyConfigured as exc:
        logger.error(
            "Could not release the slot for %s: %s is misconfigured",
            identifier,
            getattr(exc, "var_name", None) or "the control-plane base URL",
        )
        return False
    answer = _post(path, payload)
    return bool(answer.get("released"))


# Whether the last attempt to post an event batch failed. Module-level,
# mirroring StreamManager's per-channel _failover_degraded (Task 8) but
# scoped to the whole relay process rather than one channel, because the
# endpoint it tracks -- POST /api/relay/events -- is the same one for
# every channel. A stream_stats flush fires every 30s per channel plus on
# every parsed codec line, so a real Django outage would otherwise write
# one WARNING/ERROR per failed batch; this flag caps it to one line per
# transition into and out of the outage instead.
_events_down = False


def post_events(events):
    """POST one batch of events. Never raises — both exception types are
    swallowed here so a caller that wants fire-and-forget delivery (see
    emit_event) gets it; a caller that wants to know about a failure
    reads the boolean.
    """
    global _events_down
    try:
        _post("/api/relay/events", {"events": events})
    except ControlPlaneUnavailable as exc:
        if _events_down:
            logger.debug("Could not post %d relay event(s): %s", len(events), exc)
        else:
            logger.warning("Could not post %d relay event(s): %s", len(events), exc)
            _events_down = True
        return False
    except ControlPlaneRefused as exc:
        if _events_down:
            logger.debug("Relay events refused with status %s", exc.status)
        else:
            logger.error("Relay events refused with status %s", exc.status)
            _events_down = True
        return False
    else:
        if _events_down:
            logger.info("Relay events reachable again after an outage")
            _events_down = False
        return True


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
