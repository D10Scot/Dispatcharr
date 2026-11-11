"""Credential expiry reporting (SSO spec D26, section 5.2).

Each credential has its own expiry and the one reported is the one ``client_auth_method``
selects: the active certificate's ``notAfter`` for ``private_key_jwt``, the admin-entered
``client_secret_expires_at`` otherwise. Nothing here disables a provider.
"""


from django.utils import timezone

from . import certificates

EXPIRING_DAYS = 30

STATE_UNKNOWN = "unknown"
STATE_OK = "ok"
STATE_EXPIRING = "expiring"
STATE_EXPIRED = "expired"


def credential_expiry(provider, today=None):
    """``{expires_at, state, days_left}`` for the credential ``provider`` currently uses."""
    today = today or timezone.now().date()
    expires = None
    if provider.client_auth_method == provider.AUTH_PRIVATE_KEY_JWT:
        if provider.client_cert_pem:
            try:
                expires = certificates.not_after(provider.client_cert_pem).date()
            except ValueError:
                expires = None
    else:
        expires = provider.client_secret_expires_at

    if expires is None:
        return {"expires_at": None, "state": STATE_UNKNOWN, "days_left": None}
    days_left = (expires - today).days
    if days_left < 0:
        state = STATE_EXPIRED
    elif days_left <= EXPIRING_DAYS:
        state = STATE_EXPIRING
    else:
        state = STATE_OK
    return {"expires_at": expires.isoformat(), "state": state, "days_left": days_left}


def credential_warnings(today=None):
    """One ``{slug, state, days_left}`` per ENABLED provider whose credential is expiring or expired."""
    from apps.accounts.models import OIDCProvider

    warnings = []
    for provider in OIDCProvider.objects.filter(enabled=True).order_by("id"):
        info = credential_expiry(provider, today)
        if info["state"] in (STATE_EXPIRING, STATE_EXPIRED):
            warnings.append(
                {"slug": provider.slug, "state": info["state"], "days_left": info["days_left"]}
            )
    return warnings
