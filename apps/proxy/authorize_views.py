"""The two ways authorize_stream() is reached (Phase 1 PR 5).

1. authorize_view — what nginx calls with `auth_request` at the internal
   location `= /_dispatcharr/authorize`, once per tune, before it proxies
   a single byte to the relay. It answers only 2xx, 401 or 403, carrying
   the true status in X-Authorize-Status on every denial (nginx's
   auth_request module cannot transport a 404 or 429 as itself). On a
   200, it carries the decision in five X-Relay-* response headers, which
   nginx copies into variables with auth_request_set (the only context in
   which a subrequest's response headers are readable) and re-emits toward
   the relay as uwsgi_param HTTP_X_RELAY_* values.

2. resolve_authorization — what each stream view calls. It trusts nginx's
   answer only when X-Dispatcharr-Authorized carries
   HMAC(SECRET_KEY, "relay-trust"); otherwise it authorizes inline, which
   is what makes `manage.py runserver` and any nginx-less shape behave
   identically. Same function underneath, so the two cannot drift.
"""

import logging
from django.http import JsonResponse
from django.urls import Resolver404, resolve
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from urllib.parse import unquote, urlsplit

from apps.accounts.models import User
from apps.proxy.authorize import (
    SURFACE_CATCHUP,
    SURFACE_CATCHUP_XC,
    SURFACE_LIVE,
    SURFACE_LIVE_XC,
    SURFACE_VOD,
    SURFACE_VOD_XC,
    AuthorizeDenied,
    AuthorizeResult,
    authorize_stream,
)
from apps.proxy.internal_auth import (
    HEADER_AUTHORIZE_STATUS,
    HEADER_RELAY_CHANNEL,
    HEADER_RELAY_CLIENT,
    HEADER_RELAY_NAME,
    HEADER_RELAY_OUTPUT,
    HEADER_RELAY_USER,
    META_AUTHORIZED,
    META_ORIGINAL_URI,
    META_RELAY_CHANNEL,
    META_RELAY_CLIENT,
    META_RELAY_OUTPUT,
    META_RELAY_USER,
    request_is_relay_trusted,
)

logger = logging.getLogger(__name__)

# M1 (final-review.md § 3): a present-but-mismatched trust marker means
# nginx's rendered token and this process's token disagree (a SECRET_KEY
# mismatch between web and relay, or /data/jwt rotated under a non-
# idempotent docker/init/03-init-dispatcharr.sh restart). The outcome is
# fail-safe -- every tune authorizes inline -- but silent, so warn once per
# process rather than once per request.
_TRUST_MISMATCH_WARNED = False


class AuthorizeDenialSerializer(serializers.Serializer):
    """The body of every non-2xx answer from the hop."""

    error = serializers.CharField()


def authorize_error_response(exc: AuthorizeDenied) -> JsonResponse:
    """A refusal with its true status. Used by the stream views (inline)."""
    serializer = AuthorizeDenialSerializer({"error": exc.detail})
    return JsonResponse(serializer.data, status=exc.status)


def subrequest_error_response(exc: AuthorizeDenied) -> JsonResponse:
    """A refusal shaped for what nginx's auth_request module can carry.

    The module allows on 2xx, denies verbatim on 401 and 403, and treats
    every other status as an error — answering the client 500. A 404 or
    429 sent from here would therefore reach a viewer as 500: an unknown
    channel id in a cached playlist, and a user over their stream limit,
    both turning into "something broke".

    So every non-401 denial leaves as 403 with the real code in
    X-Authorize-Status, and each relay-bound location's
    `error_page 403 = @authorize_denied` restores it. 401 is passed
    through as itself, being the other status the module carries.
    """
    status = exc.status if exc.status == 401 else 403
    serializer = AuthorizeDenialSerializer({"error": exc.detail})
    response = JsonResponse(serializer.data, status=status)
    response[HEADER_AUTHORIZE_STATUS] = str(exc.status)
    return response


def result_from_headers(request, surface: str) -> AuthorizeResult:
    """Rebuild the decision nginx already made, from the params it set.

    Only ever called after request_is_relay_trusted(), so every value here
    was written by nginx: the HTTP_-prefixed uwsgi_param override means a
    client's own header of the same name was replaced, and every non-relay
    location blanks all five.
    """
    from django.conf import settings

    user_id = (request.META.get(META_RELAY_USER) or "").strip()
    user = None
    if user_id.isdigit():
        user = User.objects.filter(id=int(user_id)).first()

    output_profile_id = (request.META.get(META_RELAY_OUTPUT) or "").strip()
    if output_profile_id and not output_profile_id.isdigit():
        # A trusted marker is only ever "" (no profile) or a digit string
        # nginx copied from X-Relay-Output; anything else means the
        # internal contract is broken, not that no profile was chosen.
        # OutputProfile.objects.filter(id=output_profile_id, ...) would
        # raise ValueError on a non-integer id and fail closed as an
        # uncontrolled 500 -- deny explicitly instead.
        raise AuthorizeDenied(403, "Forbidden")

    return AuthorizeResult(
        surface=surface,
        channel_uuid=(request.META.get(META_RELAY_CHANNEL) or "").strip(),
        output_profile_id=output_profile_id,
        client_id=(request.META.get(META_RELAY_CLIENT) or "").strip(),
        user_id=str(user.id) if user is not None else "",
        relay_name=settings.RELAY_DEFAULT_NAME,
        user=user,
        trusted=True,
    )


def resolve_authorization(request, surface: str, **identity) -> AuthorizeResult:
    """Trust nginx's decision, or make it here. Raises AuthorizeDenied."""
    http_request = getattr(request, "_request", request)
    if request_is_relay_trusted(http_request):
        return result_from_headers(http_request, surface)
    global _TRUST_MISMATCH_WARNED
    if http_request.META.get(META_AUTHORIZED) and not _TRUST_MISMATCH_WARNED:
        _TRUST_MISMATCH_WARNED = True
        logger.warning(
            "X-Dispatcharr-Authorized is present but does not match this "
            "process's relay trust token; every tune is authorizing inline "
            "instead of trusting nginx's decision"
        )
    return authorize_stream(http_request, surface, **identity)


# --- The nginx-facing view ---------------------------------------------
#
# The subrequest's own URI is /_dispatcharr/authorize, so the URI being
# authorized arrives in X-Original-URI ($request_uri, which nginx copies
# from the parent request and which includes the query string). Rather
# than re-deriving each surface's URL shape here — a second copy of the
# urlconf, guaranteed to drift — the path is handed to Django's own
# resolver and the resulting view function names the surface.

def _surface_for(match):
    view = getattr(match.func, "cls", None) or match.func
    name = getattr(view, "__name__", "")
    kwargs = dict(match.kwargs)
    if name == "stream_ts":
        return SURFACE_LIVE, {"identifier": kwargs.get("channel_id")}
    if name == "stream_xc":
        raw = str(kwargs.get("channel_id") or "")
        return SURFACE_LIVE_XC, {
            # stream_xc itself does pathlib.Path(channel_id).stem; the
            # extension only chooses the output format, never the channel.
            "identifier": raw.rsplit(".", 1)[0] if "." in raw else raw,
            "username": kwargs.get("username"),
            "password": kwargs.get("password"),
        }
    if name == "catchup_proxy":
        return SURFACE_CATCHUP, {"identifier": str(kwargs.get("channel_id") or "")}
    if name in ("timeshift_proxy", "timeshift_proxy_query"):
        return SURFACE_CATCHUP_XC, _timeshift_identity(name, kwargs)
    if name == "stream_vod":
        return SURFACE_VOD, {
            "identifier": str(kwargs.get("content_id") or ""),
            "session_id": kwargs.get("session_id"),
        }
    if name in ("stream_xc_movie", "stream_xc_episode"):
        return SURFACE_VOD_XC, {
            "identifier": str(kwargs.get("stream_id") or ""),
            "username": kwargs.get("username"),
            "password": kwargs.get("password"),
        }
    return None, {}


def _timeshift_identity(name, kwargs):
    if name == "timeshift_proxy":
        raw = str(kwargs.get("channel_id") or "")
        return {
            "identifier": raw[:-3] if raw.endswith(".ts") else raw,
            "username": kwargs.get("username"),
            "password": kwargs.get("password"),
        }
    # The QUERY layout carries its credentials and channel in the query
    # string, which the view reads the same way; this function is handed
    # the parsed query by authorize_view.
    return {}


@extend_schema(
    operation_id="internal_authorize_stream",
    description=(
        "Internal. nginx calls this with `auth_request` once per tune, at an "
        "`internal;` location, and copies the `X-Relay-*` response headers "
        "toward the relay. Not part of the client API; documented so the "
        "route is discoverable and so the schema records the status "
        "vocabulary the location table depends on."
    ),
    responses={
        200: OpenApiResponse(description="Authorized; the decision is in the X-Relay-* headers."),
        401: AuthorizeDenialSerializer,
        403: OpenApiResponse(
            response=AuthorizeDenialSerializer,
            description=(
                "Denied. X-Authorize-Status carries the real code — 403, or the 404 or "
                "429 nginx's auth_request module cannot transport, which the "
                "relay-bound location's error_page restores."
            ),
        ),
    },
    tags=["internal"],
)
@api_view(["GET", "HEAD"])
@authentication_classes([])
@permission_classes([AllowAny])
def authorize_view(request):
    # Every refusal from this view goes through subrequest_error_response,
    # never authorize_error_response: this is the nginx-facing form, and
    # nginx can only carry 401 and 403.
    original = request.META.get(META_ORIGINAL_URI) or ""
    if not original:
        return subrequest_error_response(AuthorizeDenied(403, "Forbidden"))

    split = urlsplit(original)
    http_request = request._request
    # The subrequest inherits the parent's args, but this makes the query
    # string a property of X-Original-URI rather than of nginx's subrequest
    # semantics — which is what lets ?token=, ?session_id= and
    # ?output_profile= behave identically here and in the view.
    http_request.META["QUERY_STRING"] = split.query
    http_request.GET = _query_dict(split.query)

    try:
        # X-Original-URI is nginx's $request_uri — the raw, percent-encoded
        # request line — while the inline path resolves Django's
        # path_info ($document_uri via uwsgi_params), which nginx has
        # already decoded. An XC credential segment carrying a reserved
        # character (a literal %40/%23/% or a space) would otherwise
        # authorize inline but 401 through this view. unquote is the
        # decode step that carries credentials; nginx's own // collapsing
        # and .. resolution on $document_uri has no bearing on identity.
        #
        # M2 (final-review.md § 3): that's the percent-encoded case. A
        # client that sends a non-ASCII credential as raw UTF-8 bytes in
        # the request line (some set-top players do; nginx accepts it)
        # arrives here already latin-1-decoded by uWSGI -- the same
        # WSGI-header rule internal_auth._matches works around -- so
        # re-encode to latin-1 and decode as UTF-8 before unquote. A no-op
        # for ASCII/percent-encoded input, since encode/decode round-trips
        # to the same string; UnicodeError means the bytes genuinely
        # weren't UTF-8, and the raw (mojibake) path is resolved as-is
        # rather than raising here.
        path = split.path
        try:
            path = path.encode("latin-1").decode("utf-8")
        except UnicodeError:
            pass
        match = resolve(unquote(path))
    except Resolver404:
        return subrequest_error_response(AuthorizeDenied(404, "Not found"))

    surface, identity = _surface_for(match)
    if surface is None:
        return subrequest_error_response(AuthorizeDenied(403, "Forbidden"))
    if surface == SURFACE_CATCHUP_XC and not identity:
        identity = {
            "identifier": (http_request.GET.get("stream") or "").removesuffix(".ts"),
            "username": http_request.GET.get("username"),
            "password": http_request.GET.get("password"),
        }
    if surface == SURFACE_CATCHUP:
        identity["session_id"] = http_request.GET.get("session_id")

    try:
        result = authorize_stream(http_request, surface, **identity)
    except AuthorizeDenied as exc:
        return subrequest_error_response(exc)

    response = Response(status=200)
    response[HEADER_RELAY_CHANNEL] = result.channel_uuid
    response[HEADER_RELAY_OUTPUT] = result.output_profile_id
    response[HEADER_RELAY_CLIENT] = result.client_id
    response[HEADER_RELAY_USER] = result.user_id
    response[HEADER_RELAY_NAME] = result.relay_name
    return response


def _query_dict(query: str):
    from django.http import QueryDict

    return QueryDict(query, mutable=False)
