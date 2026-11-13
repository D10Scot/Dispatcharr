"""Redirect URIs and Entra's 256-character limit (SSO spec section 3.6, T36).

The URI is built from two rows (``auth_settings.public_base_url`` and a provider's slug), so
every write that can lengthen it takes the ``auth_settings`` row lock first, reloads both
inputs under it and validates what it reloaded. Callers MUST reach
``ensure_entra_redirect_fits`` through this module so a test can wrap it.
"""

from .errors import CodedError

ENTRA_MAX_REDIRECT_URI = 256
CALLBACK_PREFIX = "/api/accounts/oidc/"


def redirect_uri(base_url, slug):
    return f"{base_url}{CALLBACK_PREFIX}{slug}/callback/"


def ensure_entra_redirect_fits(base_url, slug_kind_pairs):
    """Raise 400 ``redirect_uri_too_long`` when an Entra provider's URI would exceed 256."""
    if not base_url:
        return
    for slug, kind in slug_kind_pairs:
        if kind == "entra" and len(redirect_uri(base_url, slug)) > ENTRA_MAX_REDIRECT_URI:
            raise CodedError("redirect_uri_too_long")
