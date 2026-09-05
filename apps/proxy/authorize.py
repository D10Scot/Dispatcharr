"""One function decides whether a stream may be served (Phase 1 PR 5, ADR 0005).

Two callers, never a third:

  * apps/proxy/authorize_views.py's authorize_view, which nginx reaches
    with auth_request once per tune, and
  * resolve_authorization() in the same module, called inline by the seven
    stream views when nginx's trust marker is absent (dev runserver, and
    any deployment shape without nginx in front).

Same function both ways, so the two paths cannot drift. What this module
decides — the ACL, the principal, user_level, Channel Profile membership,
hidden_from_output, is_adult against the user's hide_adult_content, the
Output Profile and (on the live surfaces) the per-user stream limit — is
exactly the set of checks that used to be copy-pasted across
live_proxy/views.py, vod_proxy/views.py and timeshift/views.py.

What it deliberately does NOT decide:

  * VOD content resolution. The XC movie/series routes resolve an
    M3UMovieRelation/M3UEpisodeRelation to a content uuid inside the view;
    the hop resolves the principal, not the content object.
  * The VOD and catch-up stream limits. Both need an identifier that only
    exists further into their own views (a content uuid from the relation
    above; a <channel>_<programme> media id and a pool-derived client id
    from _serve_catchup's session resolution). Enforcing them here with the
    identifiers available would 429 a legitimate mid-programme seek — the
    sibling exemption in apps/proxy/utils.py matches on exactly those.
"""

import random
import time
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.http import Http404

from apps.accounts.authentication import (
    ApiKeyAuthentication,
    QueryParamJWTAuthentication,
)
from apps.accounts.models import User
from apps.proxy.internal_auth import request_is_internal
from apps.proxy.utils import check_user_stream_limits
from dispatcharr.utils import network_access_allowed
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

# --- Surfaces -----------------------------------------------------------
# One per URL family, because the ACL key, the identifier and the checks
# differ by family. Not one per view: stream_xc_movie and stream_xc_episode
# authorize identically.
SURFACE_LIVE = "live"              # /proxy/ts/stream/<uuid or stream_hash>
SURFACE_LIVE_XC = "live_xc"        # /live/<u>/<p>/<id> and the bare <u>/<p>/<id>
SURFACE_CATCHUP = "catchup"        # /proxy/catchup/<uuid>
SURFACE_CATCHUP_XC = "catchup_xc"  # /timeshift/... and /streaming/timeshift.php
SURFACE_VOD = "vod"                # /proxy/vod/<type>/<uuid>[/<session>[/<profile>]]
SURFACE_VOD_XC = "vod_xc"          # /movie/<u>/<p>/<id>.<ext>, /series/...

ALL_SURFACES = frozenset(
    {
        SURFACE_LIVE,
        SURFACE_LIVE_XC,
        SURFACE_CATCHUP,
        SURFACE_CATCHUP_XC,
        SURFACE_VOD,
        SURFACE_VOD_XC,
    }
)

_XC_SURFACES = frozenset({SURFACE_LIVE_XC, SURFACE_CATCHUP_XC, SURFACE_VOD_XC})
_CHANNEL_SURFACES = frozenset(
    {SURFACE_LIVE, SURFACE_LIVE_XC, SURFACE_CATCHUP, SURFACE_CATCHUP_XC}
)
# Surfaces that require a resolved principal. Catch-up has never served an
# anonymous request (apps/timeshift/views.py answers 401), and the XC
# families carry credentials in the path by construction. Live is the one
# that stays anonymous: the channel UUID is the capability, exactly as
# today, and every cached playlist and tuner URL depends on it (ADR 0005).
_PRINCIPAL_REQUIRED = frozenset(
    {SURFACE_LIVE_XC, SURFACE_CATCHUP, SURFACE_CATCHUP_XC, SURFACE_VOD_XC}
)
# The catch-up XC path is the one surface gated on XC_API rather than
# STREAMS (apps/timeshift/views.py's _timeshift_proxy_impl). Preserved
# exactly: an operator who narrowed XC_API expects it to bind here.
_ACL_KEYS = {SURFACE_CATCHUP_XC: "XC_API"}

# The union of what the four stream views accept today. /proxy/ts/stream/
# gains QueryParamJWTAuthentication by this union — a deliberate, small
# widening that matches what the frontend already does for recordings.
_AUTHENTICATOR_CLASSES = (
    JWTAuthentication,
    ApiKeyAuthentication,
    QueryParamJWTAuthentication,
)

#: The principal for a caller holding X-Dispatcharr-Internal. Not a User:
#: the DVR has no account, and giving it one would put a real row's
#: user_level and stream_limit in the path of every recording.
INTERNAL_PRINCIPAL = object()


class AuthorizeDenied(Exception):
    """A refusal, carrying the status the client must see.

    401 no principal where one is required, 403 ACL/flag/membership,
    404 nothing resolved for the identifier, 429 stream limit.
    """

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class AuthorizeResult:
    """What the hop tells the relay. The five string fields are the five
    X-Relay-* response headers, verbatim; `user` and `trusted` never cross
    the wire and exist only for the inline caller."""

    surface: str
    channel_uuid: str = ""
    output_profile_id: str = ""
    client_id: str = ""
    user_id: str = ""
    relay_name: str = ""
    user: object = None
    trusted: bool = False


def mint_client_id() -> str:
    """The client id the live path has always minted in the view."""
    return f"client_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"


def resolve_xc_user(username, password):
    """An Xtream principal, or None. Constant-time compare, plaintext at rest.

    Lifted from apps/timeshift/views.py's _authenticate_user, which already
    used compare_digest; live_proxy and vod_proxy used `!=` and now share
    this one.
    """
    if not username:
        return None
    user = User.objects.filter(username=username).first()
    if user is None:
        return None
    expected = (user.custom_properties or {}).get("xc_password")
    if not expected:
        return None
    import hmac

    # Bytes, not str: hmac.compare_digest raises TypeError on a non-ASCII
    # str operand, which would 500 the tune instead of authorizing or
    # 401ing it. The `!=` this replaces (live_proxy/views.py, vod_proxy)
    # never hit that trap; encoding is what keeps the constant-time
    # property without reintroducing it.
    if not hmac.compare_digest(
        str(expected).encode("utf-8"), str(password or "").encode("utf-8")
    ):
        return None
    return user


def user_can_access_channel(user, channel) -> bool:
    """Channel Profile membership, unchanged from apps/timeshift/views.py.

    Two bypasses are load-bearing and deliberate: an admin passes, and a
    user with no Channel Profiles at all passes (that is "unrestricted",
    not "restricted to nothing").
    """
    if user.user_level < channel.user_level:
        return False
    if user.user_level >= User.UserLevel.ADMIN:
        return True
    if user.channel_profiles.count() == 0:
        return True
    return (
        type(channel)
        .objects.filter(
            id=channel.id,
            channelprofilemembership__enabled=True,
            channelprofilemembership__channel_profile__in=user.channel_profiles.all(),
        )
        .exists()
    )


def resolve_output_profile(request, user):
    """?output_profile= then the user's custom_properties. Moved verbatim
    from apps/proxy/live_proxy/views.py:135-151 so the rule has one home."""
    from core.models import OutputProfile

    param = request.GET.get("output_profile")
    if param:
        try:
            return OutputProfile.objects.get(id=int(param), is_active=True)
        except (OutputProfile.DoesNotExist, ValueError, TypeError):
            return None
    if user:
        custom = getattr(user, "custom_properties", None) or {}
        profile_id = custom.get("output_profile")
        if profile_id:
            try:
                return OutputProfile.objects.get(id=int(profile_id), is_active=True)
            except (OutputProfile.DoesNotExist, ValueError, TypeError):
                return None
    return None


def _acl_key(surface: str) -> str:
    return _ACL_KEYS.get(surface, "STREAMS")


def _drf_user(http_request):
    """The union authenticator set, run explicitly rather than relied upon.

    A fresh rest_framework Request is built over the underlying
    HttpRequest so this behaves identically whether the caller is the
    nginx subrequest view (whose own DRF authentication ran against the
    subrequest's query string) or a stream view calling inline.

    A credential an authenticator explicitly rejects (a malformed Bearer
    JWT, an unknown API key) must 401, not fall through to anonymous —
    that is the behaviour `@api_view`'s own authentication gives
    `stream_ts` today, and the single decision function must not depend on
    the calling view's own `authentication_classes` to keep it (Task 4).
    Declining silently (no header presented at all) still returns None.

    When nothing here matches, reading `drf_request.user` sets
    `http_request.user` to AnonymousUser as a side effect — DRF's
    `Request.user` setter mirrors onto the wrapped request on every
    access, including the implicit one `_not_authenticated()` makes. Left
    alone, that silently overwrites whatever AuthenticationMiddleware had
    already resolved from a session cookie before `_session_user` gets a
    turn, making that fallback unreachable. Restored in that case only, so
    the two principal sources stay independent.
    """
    original_user = getattr(http_request, "user", None)
    try:
        drf_request = Request(
            http_request,
            authenticators=[cls() for cls in _AUTHENTICATOR_CLASSES],
        )
        user = drf_request.user
    except AuthenticationFailed:
        raise AuthorizeDenied(401, "Invalid credentials") from None
    except APIException:
        return None
    if user is not None and user.is_authenticated:
        return user
    http_request.user = original_user
    return None


def _session_user(http_request):
    """The principal a session cookie carries, read from the session directly.

    Not `http_request.user`: both callers reach this after `_drf_user`, and
    reading `drf_request.user` with no authenticator matching mirrors
    AnonymousUser onto `http_request.user` as a side effect of DRF's own
    `Request.user` setter — for the nginx subrequest view specifically, that
    clobber happens in `@api_view`'s own `dispatch()` (`authentication_classes([])`
    still runs `perform_authentication`), before this module's `_drf_user`
    ever gets a turn, so `_drf_user`'s own restore-on-miss does not reach it.
    `django.contrib.auth.get_user` re-resolves straight from the session,
    independent of whatever `request.user` currently holds.
    """
    if not hasattr(http_request, "session"):
        return None
    from django.contrib.auth import get_user

    user = get_user(http_request)
    return user if getattr(user, "is_authenticated", False) else None


def _catchup_session_user(identifier, session_id):
    """The principal a tokenless catch-up playback URL carries.

    POST /api/catchup/sessions/ mints a session_id bound to a user and a
    programme start; the playback URL then carries no credential at all.
    touch_catchup_session() inside this call is an idempotent TTL refresh,
    so running it here and again in the view is harmless.
    """
    from apps.timeshift.sessions import resolve_catchup_playback

    resolved = resolve_catchup_playback(session_id, identifier)
    if resolved is None:
        return None
    user, _start, _duration = resolved
    return user


def _resolve_principal(http_request, surface, username, password, identifier, session_id):
    if request_is_internal(http_request):
        return INTERNAL_PRINCIPAL
    if surface in _XC_SURFACES:
        user = resolve_xc_user(username, password)
        if user is None:
            raise AuthorizeDenied(401, "Invalid credentials")
        return user
    user = _drf_user(http_request) or _session_user(http_request)
    if user is None and surface == SURFACE_CATCHUP and session_id:
        user = _catchup_session_user(identifier, session_id)
    elif user is not None and surface == SURFACE_CATCHUP and session_id:
        # Today's cross-check (apps/timeshift/views.py:313-315): a
        # credentialed request may not drive someone else's session.
        session_user = _catchup_session_user(identifier, session_id)
        if session_user is not None and session_user.id != user.id:
            raise AuthorizeDenied(403, "Access denied")
    if user is None and surface in _PRINCIPAL_REQUIRED:
        raise AuthorizeDenied(401, "Authentication required")
    return user


def _resolve_channel(surface, identifier):
    """The channel this tune is for, or None when the surface has none.

    Returns (channel, is_stream_hash). The stream-by-hash case
    (/proxy/ts/stream/<stream_hash>, the admin UI's single-stream preview)
    has no channel at all, so no channel check applies to it — there is
    nothing to apply one to.
    """
    from apps.channels.models import Channel

    if surface == SURFACE_LIVE:
        from apps.proxy.live_proxy.url_utils import get_stream_object

        try:
            target = get_stream_object(identifier)
        except Http404:
            raise AuthorizeDenied(404, "Not found") from None
        if isinstance(target, Channel):
            return target, False
        return None, True
    if surface == SURFACE_CATCHUP:
        # Unreachable inline (apps/timeshift/urls.py:11 is <uuid:channel_id>)
        # but reachable through authorize_view's X-Original-URI parser,
        # which does not itself validate the segment it hands on here.
        # Channel.objects.filter(uuid=...) raises ValidationError, not
        # DoesNotExist, for a non-UUID string — pre-validate so a bad
        # identifier 404s like every other unresolvable one, rather than
        # 500ing.
        try:
            uuid.UUID(str(identifier))
        except (ValueError, TypeError, AttributeError):
            raise AuthorizeDenied(404, "Not found") from None
        channel = Channel.objects.filter(uuid=identifier).first()
    else:
        # The XC families address a channel by its numeric id, with an
        # optional extension the caller has already stripped.
        try:
            channel = Channel.objects.filter(id=int(identifier)).first()
        except (TypeError, ValueError):
            channel = None
    if channel is None:
        raise AuthorizeDenied(404, "Not found")
    return channel, False


def _apply_channel_checks(channel, principal):
    if principal is INTERNAL_PRINCIPAL:
        return
    user = principal
    if user is not None and user.user_level >= User.UserLevel.ADMIN:
        # Before hidden_from_output, deliberately: the admin UI plays any
        # channel from the channels table with the admin's JWT on the
        # request, and 403ing that preview would be a regression, not a
        # fix. _user_can_access_channel granted exactly this bypass
        # already; this generalises it rather than inventing it.
        return
    if channel.hidden_from_output:
        # A property of the channel, needing no principal — which is why
        # this is the one check an anonymous request also fails.
        raise AuthorizeDenied(403, "Forbidden")
    if user is None:
        return
    if user.user_level < channel.user_level:
        raise AuthorizeDenied(403, "Forbidden")
    if channel.is_adult and (getattr(user, "custom_properties", None) or {}).get(
        "hide_adult_content"
    ):
        raise AuthorizeDenied(403, "Forbidden")
    if not user_can_access_channel(user, channel):
        raise AuthorizeDenied(403, "Forbidden")


def authorize_stream(
    request,
    surface,
    *,
    identifier=None,
    username=None,
    password=None,
    session_id=None,
) -> AuthorizeResult:
    """Authorize one tune. Raises AuthorizeDenied; never returns a refusal."""
    if surface not in ALL_SURFACES:
        # Fail closed: an unknown surface means the caller (or the nginx
        # location table) is asking about a URI this function was never
        # written to judge.
        raise AuthorizeDenied(403, "Forbidden")

    http_request = getattr(request, "_request", request)
    principal = _resolve_principal(
        http_request, surface, username, password, identifier, session_id
    )
    user = None if principal is INTERNAL_PRINCIPAL else principal

    if not network_access_allowed(http_request, _acl_key(surface), user):
        raise AuthorizeDenied(403, "Forbidden")

    channel = None
    if surface in _CHANNEL_SURFACES:
        channel, _by_hash = _resolve_channel(surface, identifier)
        if channel is not None:
            _apply_channel_checks(channel, principal)

    client_id = mint_client_id() if surface in (SURFACE_LIVE, SURFACE_LIVE_XC) else ""

    if user is not None and surface in (SURFACE_LIVE, SURFACE_LIVE_XC):
        media_id = str(channel.uuid) if channel is not None else str(identifier)
        if not check_user_stream_limits(user, client_id, media_id=media_id):
            raise AuthorizeDenied(
                429,
                f"Stream limit exceeded ({user.stream_limit} concurrent streams allowed)",
            )

    output_profile = resolve_output_profile(http_request, user)

    return AuthorizeResult(
        surface=surface,
        channel_uuid=str(channel.uuid) if channel is not None else "",
        output_profile_id=str(output_profile.id) if output_profile else "",
        client_id=client_id,
        user_id=str(user.id) if user is not None else "",
        relay_name=settings.RELAY_DEFAULT_NAME,
        user=user,
        trusted=False,
    )
