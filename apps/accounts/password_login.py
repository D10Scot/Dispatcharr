"""Whether password login is on now (SSO spec 5.3, 5.6).

Precedence: the break-glass environment switch ``MINO_PASSWORD_LOGIN_FORCE=1``
(``settings.PASSWORD_LOGIN_FORCE``) wins; otherwise the stored ``auth_settings`` value, read
fresh from Postgres on every call and never through the Redis group cache (spec 5.1).

Every password gate asks ``allowed()``: the token and login endpoints, password-issued token
refresh, the Django admin login and ``has_permission``, and ``PATCH users/me/ {password}``.
The streaming surfaces' session check (``apps/proxy/authorize.py``'s ``_session_user``) reads
the same two inputs inline, because that module's ORM reads are pinned by a static ledger.
The lockout guard (``apps/accounts/oidc/guard.py``) reads the STORED value only, under the
``auth_settings`` row lock, never this function.
"""

from django.conf import settings

from core.models import CoreSettings

DISABLED_CODE = "password_login_disabled"


def forced():
    """The break-glass override is on (``MINO_PASSWORD_LOGIN_FORCE=1``)."""
    return bool(settings.PASSWORD_LOGIN_FORCE)


def stored_enabled():
    """The stored toggle, read fresh from Postgres."""
    return bool(CoreSettings.get_auth_settings().get("password_login_enabled", True))


def allowed():
    """Password login is on now: the override, else the stored value."""
    return forced() or stored_enabled()
