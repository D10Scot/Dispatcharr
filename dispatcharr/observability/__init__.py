"""OpenTelemetry for the Django, Celery and Daphne processes (observability spec O5).

Import-time safety: nothing in this package imports from ``apps.*`` at module
level. ``apps.proxy.internal_auth`` and friends are imported inside the
function that needs them, because ``apps/channels/models.py`` imports leaf
modules at module level and one more import chain there stops Django booting
(CLAUDE.md, the boot trap). Only this package imports ``opentelemetry.sdk`` or
an exporter.
"""
