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
from importlib import import_module

from django.conf import settings as django_settings
from django.http import HttpRequest, JsonResponse, parse_cookie
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
    META_INTERNAL,
    HEADER_RELAY_CHANNEL,
    HEADER_RELAY_CLIENT,
    HEADER_RELAY_CLIENT_IP,
    HEADER_RELAY_NAME,
    HEADER_RELAY_OUTPUT,
    HEADER_RELAY_OUTPUT_FORMAT,
    HEADER_RELAY_USER,
    META_AUTHORIZED,
    META_ORIGINAL_URI,
    META_RELAY_CHANNEL,
    META_RELAY_CLIENT,
    META_RELAY_CLIENT_IP,
    META_RELAY_OUTPUT,
    META_RELAY_OUTPUT_FORMAT,
    META_RELAY_USER,
    internal_principal_token,
    request_is_internal,
    request_is_relay_trusted,
)
from apps.proxy.permissions import IsInternalRelay

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
    location blanks all seven.
    """
    from django.conf import settings

    # 2b-2. The live surfaces no longer need the row at all: the output
    # format arrives on X-Relay-Output-Format and the client hash is
    # written from this string, so nothing on that path reads
    # AuthorizeResult.user. Skipping the query there is what closes the
    # spec's Stage 2b row for authorize_views.py:112-141.
    #
    # Every other surface keeps it, verbatim. D1 (spec line 433) leaves
    # /proxy/vod/, /proxy/catchup/ and /streaming/timeshift.php in Python
    # and they read the row at eleven `is None`/`is not None` sites and
    # three truthiness ones (see the 2b-2 plan's Ruling R1). A lazy proxy
    # cannot serve those: `is` is not overloadable, so a stand-in object
    # is never None and every identity check flips for a user deleted
    # mid-stream. Splitting on the surface keeps a real row or a real
    # None everywhere, and it splits exactly where the phase does -- the
    # live surfaces are the ones 2c ports to Go.
    #
    # The else branch below is not a fallback: it is the whole of the
    # VOD and catch-up behaviour, unchanged. Those views pass
    # SURFACE_VOD (vod_proxy/views.py:634), SURFACE_VOD_XC (:1417,
    # :1454), SURFACE_CATCHUP_XC (timeshift/views.py:162) and
    # SURFACE_CATCHUP (:292) -- never a live surface -- so every
    # consumer downstream still gets a real row or a real None. That
    # matters most at vod_proxy/views.py:783, where `if user is None`
    # is a RECOVERY path that re-resolves the principal from the Redis
    # session mapping when a VOD redirect stripped the token; a
    # non-None stand-in there would make it dead code and silently
    # drop the user.
    user_id = (request.META.get(META_RELAY_USER) or "").strip()
    user = None
    if surface in (SURFACE_LIVE, SURFACE_LIVE_XC):
        if not user_id.isdigit():
            user_id = ""
    else:
        if user_id.isdigit():
            user = User.objects.filter(id=int(user_id)).first()
        user_id = str(user.id) if user is not None else ""

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
        user_id=user_id,
        relay_name=settings.RELAY_DEFAULT_NAME,
        user=user,
        trusted=True,
        # Same header, same check, one module. nginx does not blank
        # X-Dispatcharr-Internal on a relay-bound location -- it is not
        # one of the five names dispatcharr_api_params.conf clears -- so
        # the DVR's token reaches the relay exactly as it reached the hop.
        is_internal=request_is_internal(request),
        output_format=(request.META.get(META_RELAY_OUTPUT_FORMAT) or "").strip(),
        client_ip=(request.META.get(META_RELAY_CLIENT_IP) or "").strip(),
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
    # 2b-2. Both resolved by authorize_stream above, so the relay does
    # not re-read a User row (output_format) and does not need
    # get_client_ip's trusted-proxy configuration (client_ip).
    response[HEADER_RELAY_OUTPUT_FORMAT] = result.output_format
    response[HEADER_RELAY_CLIENT_IP] = result.client_ip
    return response


# --- The Go relay's dev fallback (spec D5, exception 2) -----------------
#
# POST /_dispatcharr/authorize-internal. ITS OWN PATH, not the nginx-facing
# `= /_dispatcharr/authorize` above, and the distinct path is the whole
# point: that location is declared `internal;` in docker/nginx.conf:120, an
# EXACT-match location that wins over every prefix and regex one, so a POST
# to it is 404'd by nginx before Django sees it in every nginx-fronted
# deployment. Harmless for the fallback's intended use (a shape with no
# nginx has no nginx to 404 it) and NOT harmless for the failure mode Phase
# 1 deliberately made safe: when nginx's rendered RELAY_TRUST_TOKEN and a
# relay's own derived token disagree, request_is_relay_trusted() returns
# False and the Python relay falls through to an inline authorize_stream
# call, warning once per process (_TRUST_MISMATCH_WARNED above). Reusing
# the shielded path here would turn that degraded-but-working mode into
# every live tune failing outright post-cutover.
#
# THE VIEW BUILDS THE REQUEST IT AUTHORIZES ENTIRELY FROM THE BODY AND
# INHERITS NOTHING FROM THE TRANSPORT REQUEST. Every field below is
# load-bearing and each has its own failure signature, all of them silent:
#
#   uri        the full path and query string, X-Original-URI's equivalent.
#              _surface_for resolves the surface from it, and
#              authorize_view:299 reads session_id off its query for the
#              catch-up surface.
#   client_ip  REMOTE_ADDR. authorize.py:425 evaluates the STREAMS ACL
#              against the request's own address, so a view that passed its
#              own transport request through would judge the RELAY's address
#              -- wrong in exactly the nginx-less deployments this exists
#              for, where there is no auth_request subrequest inheriting the
#              client's.
#   internal   whether the CLIENT's request was internal. Never the
#              transport's own X-Dispatcharr-Internal header, which
#              IsInternalRelay requires the relay to send and which
#              therefore says only "this caller is part of the deployment".
#              authorize_stream:417-419 reads request_is_internal off the
#              request it is handed, and _resolve_principal:309-310 returns
#              INTERNAL_PRINCIPAL before any channel flag, adult filter,
#              profile membership or XC credential is looked at -- so
#              passing the transport request through would authorize every
#              tune in every nginx-less deployment, unconditionally.
#   headers    the three credential-bearing headers the authenticator union
#              can consume: authorization, cookie and x-api-key.
#              ApiKeyAuthentication (apps/accounts/authentication.py:46-85)
#              checks X-API-Key BEFORE falling back to an
#              `Authorization: ApiKey ...` header, so omitting the third
#              would resolve such a client to anonymous here and to its real
#              user in production -- the cross-shape divergence D5 exists to
#              prevent.
#
# They travel in the BODY rather than as headers because the bound token
# (internal_auth.internal_request_token) signs exactly five fields -- the
# context, the method, the full path, the timestamp and sha256(BODY) -- and
# headers are not among them. A captured X-Dispatcharr-Internal-Request for
# this path would otherwise stay valid for 120 seconds against ANY
# combination of forwarded headers.


class AuthorizeInternalHeadersSerializer(serializers.Serializer):
    """The three credential-bearing headers, each null when the client sent
    none. A `headers` sub-object rather than three flat fields so a fourth
    credential header discovered later is a field, not a body-shape
    redesign."""

    authorization = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    cookie = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    # The wire name is the lowercased header, hyphen and all, which is not a
    # Python identifier. `source=` alone is NOT enough and getting that wrong
    # is silent: DRF reads INPUT by a field's NAME (`x_api_key`) and uses
    # `source` only for where the value lands in validated_data, so a body
    # carrying `"x-api-key"` would deserialize to None and an API-key client
    # would resolve to ANONYMOUS here and to its real user in production --
    # the exact cross-shape divergence D5 exists to prevent, and the one
    # § The contract added this third field to close. Found by a coverage
    # test, not by review. to_internal_value below is what makes the wire
    # name the wire name.
    x_api_key = serializers.CharField(
        source="x-api-key",
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
    )

    def to_internal_value(self, data):
        if isinstance(data, dict) and "x-api-key" in data:
            data = {**data, "x_api_key": data["x-api-key"]}
        return super().to_internal_value(data)


class AuthorizeInternalRequestSerializer(serializers.Serializer):
    """The question this route answers, in full, so sha256(body) binds it."""

    uri = serializers.CharField()
    client_ip = serializers.CharField(allow_blank=True)
    internal = serializers.BooleanField()
    headers = AuthorizeInternalHeadersSerializer(required=False)


def _synthetic_request(data) -> HttpRequest:
    """The request authorize_stream is handed, built from the body alone.

    Nothing here reads the incoming POST. The session is loaded the way
    django.contrib.sessions.middleware.SessionMiddleware.process_request
    loads it, from the body's cookie, because _session_user
    (authorize.py:268-287) calls django.contrib.auth.get_user(request) --
    which reads the SESSION, not request.user -- and a view that forwarded
    the cookie but resolved the principal from request.user would downgrade
    a session viewer to anonymous with NO ERROR: a hidden channel would
    still 403, so the visible half of authorization would look correct,
    while an ordinary channel streamed a 200 with real bytes and
    user_level, Channel Profile membership, adult filtering and the
    per-user stream limit had all quietly stopped applying.
    """
    split = urlsplit(data["uri"])
    # authorize_view's own two decode steps, for its own reasons: a
    # percent-encoded XC credential segment, and a raw-UTF-8 one that
    # arrived latin-1 decoded.
    path = split.path
    try:
        path = path.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    path = unquote(path)

    headers = data.get("headers") or {}
    cookie = headers.get("cookie") or ""

    request = HttpRequest()
    request.method = "GET"
    request.path = path
    request.path_info = path
    request.META = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": split.query,
        # get_client_ip reads REMOTE_ADDR and honours X-Real-IP /
        # X-Forwarded-For only when REMOTE_ADDR is a trusted proxy. Neither
        # forwarded header is set here -- the body carries no such field --
        # so the address the relay observed is the address judged.
        "REMOTE_ADDR": data["client_ip"],
    }
    if headers.get("authorization"):
        request.META["HTTP_AUTHORIZATION"] = headers["authorization"]
    if cookie:
        request.META["HTTP_COOKIE"] = cookie
    if headers.get("x-api-key"):
        request.META["HTTP_X_API_KEY"] = headers["x-api-key"]
    if data["internal"]:
        # From the BODY's flag, minted here -- never copied from the
        # transport request's own header. Absent entirely when the body
        # says false, so request_is_internal answers False.
        request.META[META_INTERNAL] = internal_principal_token()

    request.GET = _query_dict(split.query)
    request.COOKIES = parse_cookie(cookie)
    engine = import_module(django_settings.SESSION_ENGINE)
    request.session = engine.SessionStore(
        request.COOKIES.get(django_settings.SESSION_COOKIE_NAME)
    )
    return request


@extend_schema(
    operation_id="internal_authorize_stream_post",
    description=(
        "Internal. The Go relay's fallback when no nginx auth_request "
        "authorized the tune: the same authorize_stream() decision, reached "
        "over HTTP because a Go process cannot import Python. Registered in "
        "every deployment shape and never called in one that runs nginx. "
        "Not part of the client API."
    ),
    request=AuthorizeInternalRequestSerializer,
    responses={
        200: OpenApiResponse(
            description=(
                "Authorized; the decision is in the seven X-Relay-* headers, "
                "the same set a relay-bound nginx location carries."
            )
        ),
        401: AuthorizeDenialSerializer,
        403: AuthorizeDenialSerializer,
        404: AuthorizeDenialSerializer,
        429: AuthorizeDenialSerializer,
    },
    tags=["internal"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([IsInternalRelay])
def authorize_internal_view(request):
    payload = AuthorizeInternalRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data

    http_request = _synthetic_request(data)

    try:
        match = resolve(http_request.path)
    except Resolver404:
        return authorize_error_response(AuthorizeDenied(404, "Not found"))

    surface, identity = _surface_for(match)
    if surface is None:
        return authorize_error_response(AuthorizeDenied(403, "Forbidden"))
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
        # THE TRUE STATUS, never subrequest_error_response's 403 collapse.
        # That shape exists only because ngx_http_auth_request_module can
        # transport a 2xx, a 401 or a 403 and nothing else; a direct POST
        # has no such constraint, and collapsing here would hand the Go
        # relay a 403 where production answers 404 for an unknown channel
        # or 429 for a user over their stream limit.
        return authorize_error_response(exc)

    response = Response(status=200)
    response[HEADER_RELAY_CHANNEL] = result.channel_uuid
    response[HEADER_RELAY_OUTPUT] = result.output_profile_id
    response[HEADER_RELAY_CLIENT] = result.client_id
    response[HEADER_RELAY_USER] = result.user_id
    response[HEADER_RELAY_NAME] = result.relay_name
    response[HEADER_RELAY_OUTPUT_FORMAT] = result.output_format
    # In the nginx-less shape this response is the ONLY source of
    # ip_address -- there is no hop-set header to read -- which is what
    # closes parity-matrix row 17's stated gap for the Go relay.
    response[HEADER_RELAY_CLIENT_IP] = result.client_ip
    return response


def _query_dict(query: str):
    from django.http import QueryDict

    return QueryDict(query, mutable=False)
