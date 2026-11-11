"""Shared login rate limiting for JWT and Django admin."""

from django.http import HttpResponse
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle

from dispatcharr.utils import get_client_ip


class LoginRateThrottle(AnonRateThrottle):
    """Per-IP login throttle (scope ``login``, see REST_FRAMEWORK rates).

    Identity uses the same trusted-proxy-aware ``get_client_ip`` helper as
    ACLs and audit logs, instead of DRF's default ``get_ident``. DRF's
    default trusts a raw, client-suppliable ``X-Forwarded-For`` verbatim
    (nginx appends rather than replaces it), so a caller varying that header
    on every request would otherwise mint a fresh throttle bucket each time
    and never get rate limited.
    """

    scope = "login"

    def get_ident(self, request):
        return get_client_ip(request) or super().get_ident(request)


def enforce_login_rate_limit(request):
    """Return a 429 response when the shared login throttle denies *request*.

    Allowed checks consume a slot in the same ``login`` scope used by
    ``TokenObtainPairView``, so JWT and admin login attempts share one budget.
    Returns ``None`` when the request may proceed.
    """
    throttle = LoginRateThrottle()
    if throttle.allow_request(request, view=None):
        return None

    wait = throttle.wait()
    response = HttpResponse(
        "Too many login attempts. Try again later.",
        status=429,
        content_type="text/plain; charset=utf-8",
    )
    if wait is not None:
        response["Retry-After"] = str(max(1, int(wait)))
    return response


class OIDCRateThrottle(SimpleRateThrottle):
    """Per-IP throttle for the OIDC browser endpoints (scope ``oidc``, SSO spec 3.1).

    Keyed by the same trusted-proxy-aware client IP as ``LoginRateThrottle``, and applied to
    authenticated callers too (``link/start``), which ``AnonRateThrottle`` would skip.
    """

    scope = "oidc"

    def get_cache_key(self, request, view):
        ident = get_client_ip(request) or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
