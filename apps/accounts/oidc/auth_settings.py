"""The ``auth_settings`` CoreSettings group: write path, lock and ``public_base_url`` rule.

Every write takes ``select_for_update()`` on the group's row inside ``transaction.atomic()``
(SSO spec 5.5 serialization). Security decisions read the group fresh through
``CoreSettings.get_auth_settings()``, never through the Redis group cache.
"""

import copy
import ipaddress
from urllib.parse import urlsplit

from django.conf import settings
from rest_framework import serializers

from core.models import AUTH_SETTINGS_DEFAULTS, AUTH_SETTINGS_KEY, CoreSettings

from .errors import CodedError

ROW_NAME = "Authentication Settings"


def lock_row():
    """Lock (creating if absent) the ``auth_settings`` row. Must run inside ``atomic()``."""
    row, _ = CoreSettings.objects.select_for_update().get_or_create(
        key=AUTH_SETTINGS_KEY,
        defaults={"name": ROW_NAME, "value": copy.deepcopy(AUTH_SETTINGS_DEFAULTS)},
    )
    return row


def row_values(row):
    """The row's value merged over the defaults (as read under the lock)."""
    merged = copy.deepcopy(AUTH_SETTINGS_DEFAULTS)
    if isinstance(row.value, dict):
        merged.update(row.value)
    return merged


def _is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_public_base_url(value):
    """Validate and normalise ``public_base_url`` (SSO spec 5.1). Empty means unset.

    Absolute URL, no path beyond ``/``, no query, fragment or userinfo; stored without a
    trailing slash. ``https`` unless the host is a loopback literal or
    ``settings.OIDC_ALLOW_HTTP``: 400 ``public_base_url_insecure`` otherwise. Never derived
    from the request.
    """
    value = (value or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise serializers.ValidationError("must be an absolute http(s) URL") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not host:
        raise serializers.ValidationError("must be an absolute http(s) URL")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise serializers.ValidationError("must not contain user information")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise serializers.ValidationError("must have no path, query or fragment")
    if scheme == "http" and not (_is_loopback(host) or settings.OIDC_ALLOW_HTTP):
        raise CodedError("public_base_url_insecure")
    host_part = f"[{host}]" if ":" in host else host
    netloc = host_part if port is None else f"{host_part}:{port}"
    return f"{scheme}://{netloc}"
