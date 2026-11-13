"""The OIDC authorization-code + PKCE flow (SSO spec 3.2, 3.3, 3.3a; ADR 0012).

``start`` and ``link/start`` write a single-use transaction to Redis and bind it to the
browser with an HttpOnly cookie named per transaction (ruling B6). ``callback`` consumes the
transaction with ``GETDEL``, checks the binding, the provider and its version, exchanges the
code, validates the ID token, resolves the identity and mints the existing simplejwt pair,
which it parks behind a one-time handoff code delivered in the URL fragment. ``exchange``
redeems that code with ``GETDEL``.

No Django session is created (D3): nothing here calls ``django.contrib.auth.login``.

Nothing here logs or records ``code``, ``state``, ``nonce``, the verifier, the binding, a
token, the client credential, a claim set, ``sub`` or ``error_description``. Refusals carry a
code from a fixed vocabulary. Exceptions are logged by class name only.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from urllib.parse import unquote, urlencode, urlsplit

import redis
from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponseRedirect
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import OIDCProvider
from core.models import CoreSettings

from . import client_auth, discovery, provisioning, redirect, validate

logger = logging.getLogger(__name__)

TX_TTL = 600
HANDOFF_TTL = 60
HANDOFF_COOKIE_MAX_AGE = 120
HTTPS_COOKIE_PREFIX = "__Host-mino_oidc_tx_"
HTTP_COOKIE_PREFIX = "mino_oidc_tx_"
STALE_COOKIE_CAP = 5
NEXT_MAX = 512
TX_KEY = "oidc:tx:{}"
HANDOFF_KEY = "oidc:handoff:{}"
# state and the handoff code are 32 random bytes, base64url: 43 characters.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
# RFC 6749 4.1.2.1's fixed error codes; any other value is recorded as "other".
RFC6749_ERRORS = frozenset(
    {
        "invalid_request",
        "unauthorized_client",
        "access_denied",
        "unsupported_response_type",
        "invalid_scope",
        "server_error",
        "temporarily_unavailable",
    }
)
INTENT_LOGIN = "login"
INTENT_LINK = "link"

_GETDEL_LUA = "local v = redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1]); return v"

# Every response from start, link/start, callback and exchange carries these (spec 3.1).
NO_STORE_HEADERS = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


class FlowError(Exception):
    """A refusal with a fixed ``code``; ``status`` is used where the answer is JSON."""

    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


# ---- Redis ---------------------------------------------------------------------------


def _redis():
    from core.utils import RedisClient

    # max_retries=1: never sleep in a request path waiting for Redis.
    client = RedisClient.get_client(max_retries=1)
    if client is None:
        raise FlowError("sso_unavailable", status=503)
    return client


def _put(key, value, ttl):
    try:
        _redis().set(key, json.dumps(value), ex=ttl)
    except redis.RedisError as exc:
        logger.warning("OIDC transaction store failed: %s", type(exc).__name__)
        raise FlowError("sso_unavailable", status=503) from None


def take(key):
    """Fetch and delete in one step: ``GETDEL``, falling back to a Lua get-and-delete."""
    client = _redis()
    try:
        try:
            raw = client.getdel(key)
        except redis.ResponseError:
            raw = client.eval(_GETDEL_LUA, 1, key)
    except redis.RedisError as exc:
        logger.warning("OIDC transaction read failed: %s", type(exc).__name__)
        raise FlowError("sso_unavailable", status=503) from None
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# ---- helpers -------------------------------------------------------------------------


def _random(nbytes):
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def _sha256_hex(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_equal(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.isascii() and b.isascii() and (
        hmac.compare_digest(a, b)
    )


def tx_id(state):
    """The first 16 hex characters of ``sha256(state)``: names the binding cookie."""
    return _sha256_hex(state)[:16]


def cookie_prefix(base_url):
    return HTTPS_COOKIE_PREFIX if base_url.lower().startswith("https://") else HTTP_COOKIE_PREFIX


def binding_cookie_name(tx, base_url):
    """``__Host-`` prefixed under an https ``public_base_url``; unprefixed over plain http.

    Every reader and writer of the binding cookie calls this, so the two cannot disagree.
    """
    return cookie_prefix(base_url) + tx


def is_binding_cookie_name(name, base_url):
    """True only for the shape ``binding_cookie_name`` produces: the prefix and a ``tx_id``.

    Django's request parser accepts names ``http.cookies`` refuses to write; counting such a
    name as stale and expiring it would make ``set_cookie`` raise.
    """
    prefix = cookie_prefix(base_url)
    return name.startswith(prefix) and re.fullmatch(r"[0-9a-f]{16}", name[len(prefix):]) is not None


def _secure(base_url):
    return cookie_prefix(base_url) == HTTPS_COOKIE_PREFIX


def set_binding_cookie(response, name, value, base_url, max_age):
    # __Host- requires Secure, Path=/ and no Domain; Lax because the callback is a top-level
    # cross-site GET navigation from the IdP.
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=_secure(base_url),
        httponly=True,
        samesite="Lax",
    )


def delete_binding_cookie(response, name, base_url):
    set_binding_cookie(response, name, "", base_url, 0)


def safe_next(value):
    """Spec 3.2 step 2: a relative path or ``/``. Never an absolute URL."""
    if not isinstance(value, str) or not value or len(value) > NEXT_MAX:
        return "/"
    for candidate in (value, unquote(value)):
        if not candidate.startswith("/") or candidate.startswith(("//", "/\\")):
            return "/"
        if "\\" in candidate or any(ord(c) < 32 or ord(c) == 127 for c in candidate):
            return "/"
        try:
            parts = urlsplit(candidate)
        except ValueError:
            return "/"
        if parts.scheme or parts.netloc:
            return "/"
    return value


def public_base_url():
    """Read fresh from Postgres (spec 5.1). Never derived from the request (D6)."""
    return CoreSettings.get_auth_settings().get("public_base_url") or ""


def enabled_provider(slug):
    return OIDCProvider.objects.filter(slug=slug, enabled=True).first()


def _well_formed(token):
    return isinstance(token, str) and bool(_TOKEN_RE.match(token))


# ---- start ---------------------------------------------------------------------------


class Started:
    def __init__(self, authorize_url, base_url, cookie_name, binding, expire):
        self.authorize_url = authorize_url
        self.base_url = base_url
        self.cookie_name = cookie_name
        self.binding = binding
        self.expire = expire

    def apply_cookies(self, response):
        for name in self.expire:
            delete_binding_cookie(response, name, self.base_url)
        set_binding_cookie(response, self.cookie_name, self.binding, self.base_url, TX_TTL)
        return response


def begin(request, provider, base_url, *, intent, link_user_id, next_value):
    """Spec 3.2 steps 2-6. Raises ``FlowError`` or ``discovery.DiscoveryError``."""
    disco = discovery.get_discovery(provider)

    state = _random(32)
    nonce = _random(32)
    code_verifier = _random(64)
    binding = _random(32)
    tx = {
        "provider_id": provider.pk,
        "provider_version": provider.version,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "binding_hash": _sha256_hex(binding),
        "next": safe_next(next_value),
        "intent": intent,
        "link_user_id": link_user_id if intent == INTENT_LINK else None,
        "created": int(time.time()),
    }
    _put(TX_KEY.format(state), tx, TX_TTL)

    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect.redirect_uri(base_url, provider.slug),
        "scope": provider.scopes,
        "state": state,
        "nonce": nonce,
        # PKCE is always sent and never gated on discovery: Entra's document does not
        # advertise code_challenge_methods_supported and supports PKCE all the same.
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider.prompt_select_account:
        params["prompt"] = "select_account"
    endpoint = disco["authorization_endpoint"]
    joiner = "&" if urlsplit(endpoint).query else "?"
    authorize_url = endpoint + joiner + urlencode(params)

    stale = [n for n in request.COOKIES if is_binding_cookie_name(n, base_url)]
    # At five or more in-flight cookies, expire them all before setting the new one: bounds
    # the Cookie header at the cost of abandoning those transactions.
    expire = stale if len(stale) >= STALE_COOKIE_CAP else []
    return Started(authorize_url, base_url, binding_cookie_name(tx_id(state), base_url), binding, expire)


# ---- the last resort -----------------------------------------------------------------

UNEXPECTED_MARKER = "oidc_unexpected"
_SQLSTATE_LEN = 5


def sqlstate(exc):
    """The driver's five-character SQLSTATE behind a Django ``DatabaseError``, or None.

    A fixed code (``40P01`` a deadlock, ``55P03`` a lock timeout, ``23505`` a unique
    violation) that carries no data, unlike the error's message.
    """
    code = getattr(exc.__cause__, "sqlstate", None)
    if isinstance(code, str) and len(code) == _SQLSTATE_LEN and code.isascii() and code.isalnum():
        return code
    return None


def _innermost_frame(exc):
    tb = exc.__traceback__
    if tb is None:
        return "unknown"
    while tb.tb_next is not None:
        tb = tb.tb_next
    frame = tb.tb_frame
    return f"{frame.f_globals.get('__name__', '?')}:{frame.f_code.co_name}:{tb.tb_lineno}"


def log_unexpected(stage, exc):
    """Log an exception the flow did not anticipate, loudly and without its content.

    The class and the innermost frame's module, function and line only: never the message,
    a repr or a traceback, which could carry an IdP-controlled string or a secret.
    """
    logger.error(
        "%s: OIDC %s answered a refusal for an unexpected %s at %s",
        UNEXPECTED_MARKER,
        stage,
        type(exc).__name__,
        _innermost_frame(exc),
    )


# ---- callback ------------------------------------------------------------------------


def _client_meta(request):
    from dispatcharr.utils import get_client_ip

    return (get_client_ip(request) or "unknown", request.META.get("HTTP_USER_AGENT", "unknown"))


def _event(event_type, request, **details):
    from core.utils import log_system_event

    client_ip, user_agent = _client_meta(request)
    log_system_event(event_type, client_ip=client_ip, user_agent=user_agent, **details)


def login_failed(request, reason, provider_slug, user="sso", **extra):
    _event("login_failed", request, user=user, reason=reason, provider=provider_slug, **extra)


def mint(user, provider, identity, level):
    """The existing simplejwt pair (D2) with the five OIDC claims and a 12-hour refresh life.

    ``set_exp`` overwrites the ``exp`` the constructor stamped from the class lifetime;
    refresh enforces the token's own ``exp`` and ``ROTATE_REFRESH_TOKENS`` is off, so it is
    never re-stamped. Claims set on the refresh token are copied into every access token.
    """
    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=settings.OIDC_REFRESH_TOKEN_LIFETIME)
    refresh["auth_method"] = "oidc"
    refresh["oidc_provider"] = provider.pk
    refresh["oidc_provider_version"] = provider.version
    refresh["oidc_identity"] = identity.pk
    refresh["oidc_level"] = level
    return str(refresh.access_token), str(refresh)


def callback(request, provider, base_url):
    """Spec 3.3. Always answers a redirect; refusals go to ``/login?sso_error=<code>``."""
    params = request.GET
    state = params.get("state")
    state_ok = _well_formed(state)
    cookie_name = binding_cookie_name(tx_id(state), base_url) if state_ok else None

    def refuse(code, user="sso", **extra):
        response = HttpResponseRedirect(
            f"{base_url}/login?{urlencode({'sso_error': code})}"
        )
        if cookie_name:
            delete_binding_cookie(response, cookie_name, base_url)
        login_failed(request, code, provider.slug, user=user, **extra)
        return response

    try:
        # 1. The IdP reported an error. Only RFC 6749's fixed code is recorded.
        if "error" in params:
            if state_ok:
                take(TX_KEY.format(state))
            raw = params.get("error")
            return refuse("idp_error", idp_error=raw if raw in RFC6749_ERRORS else "other")

        # 2. Single use.
        tx = take(TX_KEY.format(state)) if state_ok else None
        if tx is None:
            return refuse("state_invalid")

        # 3. The browser binding: the login-CSRF defence.
        binding = request.COOKIES.get(cookie_name)
        if not isinstance(binding, str) or not binding or not _digest_equal(
            _sha256_hex(binding), tx.get("binding_hash")
        ):
            return refuse("binding_invalid")

        # 4. Mix-up: the transaction belongs to this provider at this version.
        if tx.get("provider_id") != provider.pk or tx.get("provider_version") != provider.version:
            return refuse("provider_mismatch")

        try:
            disco = discovery.get_discovery(provider)
        except discovery.DiscoveryError:
            return refuse("provider_unavailable")

        # 5. RFC 9207: required when advertised, and must match whenever present.
        iss = params.get("iss")
        if disco.get("authorization_response_iss_parameter_supported") is True and iss is None:
            return refuse("issuer_mismatch")
        if iss is not None and iss != provider.issuer:
            return refuse("issuer_mismatch")

        # 6. The token request.
        code = params.get("code")
        if not isinstance(code, str) or not code or len(code) > 4096:
            return refuse("token_exchange_failed")
        try:
            id_token = client_auth.exchange_code(
                provider,
                disco,
                code=code,
                redirect_uri=redirect.redirect_uri(base_url, provider.slug),
                code_verifier=tx.get("code_verifier") or "",
            )
        except client_auth.TokenExchangeFailed as exc:
            return refuse(exc.code)

        # 7. The ID token.
        try:
            claims = validate.validate_id_token(provider, id_token, tx.get("nonce"), disco)
        except (validate.IdTokenInvalid, discovery.DiscoveryError):
            return refuse("id_token_invalid")

        # The provider row was loaded before the token exchange. Re-read its version now, so
        # an edit that landed during the exchange (a mapping change bumps it) is refused as
        # step 4 would have refused it, rather than applying the mappings loaded earlier.
        current = (
            OIDCProvider.objects.filter(pk=provider.pk, enabled=True)
            .values_list("version", flat=True)
            .first()
        )
        if current != provider.version:
            return refuse("provider_mismatch")

        # 8. Identity and level.
        intent = INTENT_LINK if tx.get("intent") == INTENT_LINK else INTENT_LOGIN
        try:
            result = provisioning.resolve(
                provider,
                claims,
                intent=intent,
                link_user_id=tx.get("link_user_id") if intent == INTENT_LINK else None,
            )
        except provisioning.Refused as exc:
            return refuse(exc.code, user=exc.username or "sso")
        except (DatabaseError, UnicodeError) as exc:
            # resolve's transaction has rolled back. A value the database refuses (DataError,
            # or UnicodeEncodeError from the driver for text it cannot encode), or a deadlock
            # abort, answers a fixed code rather than a 500 that would put the callback's
            # query in the 5xx log. The character checks in validate and provisioning refuse
            # or strip what is known; this keeps the redirect promise when they miss one.
            # admin_floor.AdminFloorBusy is a DatabaseError too: the admin-floor lock was not
            # granted within its bound, logged as AdminFloorBusy sqlstate=55P03.
            logger.warning(
                "OIDC provisioning failed: %s sqlstate=%s", type(exc).__name__, sqlstate(exc)
            )
            return refuse("provisioning_failed")

        # 9-10. Mint and park behind the one-time handoff code.
        access, refresh_token = mint(result.user, provider, result.identity, result.level)
        handoff_code = _random(32)
        _put(
            HANDOFF_KEY.format(handoff_code),
            {
                "access": access,
                "refresh": refresh_token,
                "binding_hash": tx.get("binding_hash"),
                "tx_id": tx_id(state),
                "next": tx.get("next") or "/",
                "intent": intent,
            },
            HANDOFF_TTL,
        )
    except FlowError as exc:
        return refuse(exc.code)
    except Exception as exc:  # noqa: BLE001 - the last resort; see log_unexpected
        # Every specific handler above keeps its code. This one sits outside resolve's
        # transaction and the admin-floor lock (both have unwound by the time it runs), so
        # it never continues a broken transaction; it keeps the promise that the callback
        # answers a redirect, for an exception type nobody enumerated.
        log_unexpected("callback", exc)
        return refuse("provider_unavailable", unexpected=UNEXPECTED_MARKER)

    # 11. Fragment only: never sent to a server, a proxy log or a Referer.
    response = HttpResponseRedirect(f"{base_url}/login/sso#code={handoff_code}")
    set_binding_cookie(response, cookie_name, binding, base_url, HANDOFF_COOKIE_MAX_AGE)
    if intent == INTENT_LINK:
        _event(
            "login_success",
            request,
            user=result.user.username,
            method="oidc_link",
            provider=provider.slug,
            admin=result.user.username,
        )
    else:
        _event(
            "login_success",
            request,
            user=result.user.username,
            method="oidc",
            provider=provider.slug,
        )
    return response


# ---- exchange ------------------------------------------------------------------------


def exchange(request, code):
    """Spec 3.3a. Returns ``(payload, cookie_name_to_delete, base_url)`` or raises FlowError.

    On a binding mismatch the handoff is already consumed, so a stolen code is worth one
    failed attempt; the error carries the cookie to delete.
    """
    if not _well_formed(code):
        raise FlowError("handoff_invalid")
    handoff = take(HANDOFF_KEY.format(code))
    if handoff is None:
        raise FlowError("handoff_invalid")
    base_url = public_base_url()
    tx = handoff.get("tx_id")
    cookie_name = (
        binding_cookie_name(tx, base_url)
        if isinstance(tx, str) and re.fullmatch(r"[0-9a-f]{16}", tx)
        else None
    )
    binding = request.COOKIES.get(cookie_name) if cookie_name else None
    if not isinstance(binding, str) or not binding or not _digest_equal(
        _sha256_hex(binding), handoff.get("binding_hash")
    ):
        error = FlowError("handoff_invalid")
        error.cookie_name = cookie_name
        error.base_url = base_url
        raise error
    access = handoff.get("access")
    refresh_token = handoff.get("refresh")
    if not isinstance(access, str) or not isinstance(refresh_token, str):
        raise FlowError("handoff_invalid")
    intent = INTENT_LINK if handoff.get("intent") == INTENT_LINK else INTENT_LOGIN
    payload = {
        "access": access,
        "refresh": refresh_token,
        "next": safe_next(handoff.get("next")),
        "intent": intent,
    }
    return payload, cookie_name, base_url
