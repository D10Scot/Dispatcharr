"""Seed the ninth CoreSettings group, ``auth_settings`` (SSO spec section 5.1).

Unlike ``epg_settings``, which has no seeding migration, this group exists on every
instance so ``PATCH /api/accounts/oidc/settings/`` works on a fresh one. The reverse is a
no-op: removing the row would silently re-enable password login outside the guard.
"""

from django.db import migrations


def seed_auth_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    CoreSettings.objects.get_or_create(
        key="auth_settings",
        defaults={
            "name": "Authentication Settings",
            "value": {"public_base_url": "", "password_login_enabled": True},
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_outputprofile_hls_mode"),
    ]

    operations = [
        migrations.RunPython(seed_auth_settings, migrations.RunPython.noop),
    ]
