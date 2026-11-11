"""``auth_config_changed`` audit events (SSO spec D18, section 7).

The payload names the changed fields and never their values. The event is written from
``transaction.on_commit``, so a write that was refused or rolled back leaves no event.
"""

from django.db import transaction

ACTION_PROVIDER_CREATED = "provider_created"
ACTION_PROVIDER_UPDATED = "provider_updated"
ACTION_PROVIDER_DELETED = "provider_deleted"
ACTION_SETTINGS_UPDATED = "auth_settings_updated"


def record_config_change(action, *, user, provider=None, fields=()):
    """Queue the audit event for after the surrounding transaction commits.

    ``user`` is the acting username (or ``'cli'``), ``provider`` a slug or None, and
    ``fields`` an iterable of field NAMES. Callers never pass a value.
    """
    names = sorted({str(f) for f in fields})

    def _write():
        from core.utils import log_system_event

        log_system_event(
            "auth_config_changed",
            user=user,
            action=action,
            provider=provider,
            fields=names,
        )

    transaction.on_commit(_write)
